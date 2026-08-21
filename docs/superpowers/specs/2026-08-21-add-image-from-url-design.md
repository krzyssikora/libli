# Add image from URL

## Purpose

Today every image in libli must be uploaded as a file. An author who finds a suitable
illustration on the web — a Wikimedia Commons photograph, say — has to download it to
disk and then upload it again. This adds a third way to get an image into a course's
media library: paste its URL, and the server fetches it once into a normal `MediaAsset`.

The deliberate choice is to **store the bytes**, not to reference the remote URL. A
`<figure><img src="https://upload.wikimedia.org/…"></figure>` would have been a smaller
change, and it was considered and rejected for four reasons:

- **Rot.** Teaching material outlives blog posts; the image disappears when the remote
  host renames or removes it.
- **Learner privacy.** A remote `src` makes every student's browser contact a third-party
  host on every page view, disclosing their IP and Referer.
- **No derivatives.** `thumb`/`web` cannot exist for a remote `src`, so learners would
  download full-size originals — defeating the derivative work the media pipeline already
  does.
- **Export.** `write_archive_from` (`courses/transfer/export.py:957`) zips the actual
  bytes; a referenced URL would export as a locator that 404s on import elsewhere, and
  would only ever work in `ImageElement`, never in table cells, fill-table cells,
  drag-to-image or gallery, all of which key on the `MediaAsset` FK.

Because the fetched image becomes an ordinary `MediaAsset`, every one of those surfaces
gets the feature at once, and nothing downstream of asset creation needs to change.

### Non-goals

Explicitly out of scope, and not to be added opportunistically during implementation:

- **Dedup.** The data needed for it is captured (see "Data"), but no dedup logic is built.
- **Video by URL.** Already served by the embed path (`VideoElement.url`); fetching video
  *files* would be a redundant second mechanism with far larger downloads.
- **Hotlinking** the remote URL, per the Purpose section above.
- **Exporting `source_url`** — see "Data" for why.
- **A learner-facing attribution line.** The existing `figcaption` field already carries
  "Źródło: Wikimedia" or equivalent, and `imageelement.html` already renders it.

## Architecture

Six components. Only the first two are new modules; the rest are additions to existing
files.

### 1. `validate_fetch_url()` — `courses/validators.py`

A deliberate twin of the existing `validate_embed_url` (`courses/validators.py:118`),
which guards video/iframe embeds. Same two rules, same shape:

- the scheme must be `https`;
- the host must equal, or be a subdomain of, an entry in
  `settings.ALLOWED_IMAGE_FETCH_DOMAINS`.

Plus one rule the embed twin does not need: the URL must be at most 500 characters, so it
cannot overflow the `source_url` column. This is checked before any network access.

Raises `ValidationError` on rejection, matching every other validator in the module.

**Why an allow-list rather than an open fetch with SSRF guards.** Pinning the host to a
known-good set *before any packet leaves the process* eliminates the entire SSRF class:
link-local metadata endpoints, the Postgres container, internal admin pages, and DNS
rebinding all become unreachable rather than merely defended against. An open fetch would
require resolving the host, rejecting private/loopback/link-local/CGNAT ranges, and
re-checking after every redirect — materially more code, more risk, and a much larger
review surface. Widening an allow-list later is a one-line config change; narrowing an
open fetch later removes a capability authors already rely on.

### 2. `settings.ALLOWED_IMAGE_FETCH_DOMAINS` — `config/settings/base.py`

A new env-backed list, declared alongside `ALLOWED_EMBED_DOMAINS` (`base.py:187`) and
read the same way, defaulting to the Wikimedia image hosts:

```
ALLOWED_IMAGE_FETCH_DOMAINS = env.list(
    "LIBLI_ALLOWED_IMAGE_FETCH_DOMAINS",
    default=["upload.wikimedia.org", "commons.wikimedia.org"],
)
```

Kept as a **separate** setting from `ALLOWED_EMBED_DOMAINS` rather than reusing it: the
two lists authorise different things (an iframe the browser loads vs. a host this server
will connect to), and silently granting server-side fetch to every embed host would be a
privilege widening nobody asked for.

### 3. `courses/media_fetch.py` — the fetch service (new module)

One public entry point:

```
fetch_image_asset(course, url, user, name="") -> MediaAsset
```

It validates, downloads under a cap, and hands the bytes to the **existing**
`create_asset()` (`courses/media.py:108`), so per-kind extension/size validation
(`full_clean()`), derivative generation, and the rest of the asset pipeline run exactly as
they do for an upload. Nothing downstream of `create_asset` is aware a URL was involved.

Internal steps:

1. `validate_fetch_url(url)`.
2. Issue a `GET` with `stream=True`, `allow_redirects=False`, and an explicit
   `timeout=(5, 15)` (connect, read).
3. **Redirects are followed manually**, at most `MAX_REDIRECT_HOPS = 3`. Each hop's
   `Location` is resolved against the current URL with `urljoin` and then passed through
   `validate_fetch_url` again before being requested. This is the load-bearing guard: an
   allow-listed host that redirects off the allow-list must not be followed, and letting
   the HTTP client follow redirects itself would silently do exactly that. Exhausting the
   hop budget is a rejection, not a silent stop.
4. Reject any final response whose status is not 200.
5. **Byte cap, enforced twice** against `effective_max_image_bytes()`: a declared
   `Content-Length` above the cap rejects before the body is read, and the cap is *also*
   enforced while streaming chunks, so a missing or dishonest header cannot get past it.
   The stream is abandoned as soon as the cap is exceeded — the whole point is not to
   buffer an unbounded body.
6. Derive a filename (see "Filename derivation" below).
7. Compute the SHA-256 of the fetched bytes.
8. Wrap the bytes in an uploaded-file object and call `create_asset(course, "image", …,
   source_url=url, content_hash=digest)`.

`requests` is promoted from a transitive dependency to an explicit entry in
`pyproject.toml` — it is already resolved in `uv.lock` via django-allauth, but depending
on it directly without declaring it would be an undeclared dependency.

Ruff runs bandit rules (`select` includes `"S"` in `pyproject.toml`). `S113`
(request without timeout) must be satisfied by the real `timeout=` argument above, never
by a `noqa`. The scheme is constrained to https by `validate_fetch_url` before any
request is issued.

#### Filename derivation

`MediaAsset` validation is extension-driven, so a fetched image needs a filename with an
allowed extension. In order:

1. Take the basename of `urlsplit(url).path`, URL-unquoted.
2. If its extension is in `effective_image_extensions()`, use that filename.
3. Otherwise derive the extension from the response's `Content-Type`, mapping
   `image/png → png`, `image/jpeg → jpg`, `image/gif → gif`, `image/webp → webp`, and
   build a filename from the path basename (or a generic stem when the path has none).
4. If neither step yields an allowed extension, reject — do not invent one and let
   `full_clean()` produce a confusing downstream error.

The result passes through the existing `truncate_filename` (`courses/media.py:96`), which
already truncates while preserving the extension.

### 4. `media_fetch` view + route

`media_fetch(request, slug)` in `courses/views_media.py`, decorated `@login_required` and
`@require_POST`, gated by the existing `_require_manage(request, slug)` exactly as every
other media view is. It reads `url` and optional `name` from `request.POST`, calls
`fetch_image_asset`, and mirrors `media_upload`'s response contract precisely:

- **fragment request, success** → render `courses/manage/media/_asset_cell.html` after
  `media_svc.attach_usage(asset)`, status 200;
- **fragment request, failure** → render `courses/manage/_op_error.html` with the message,
  status 422;
- **non-fragment request** (no JS) → `redirect("courses:manage_media", slug=course.slug)`
  in both cases.

Matching that contract exactly is what lets the existing client code in
`media_picker.js` handle the response without modification.

The route is registered as `manage_media_fetch` at
`manage/courses/<slug:slug>/media/fetch/`, beside `manage_media_upload`
(`courses/urls.py:279`).

### 5. Templates

- **`templates/courses/manage/media/manager.html`** — a second small form next to the
  existing upload form: a URL text input, the optional name input, and a submit button,
  posting to `manage_media_fetch`.
- **`templates/courses/manage/media/_picker.html`** — a third tab, "From URL", alongside
  the existing Library and Upload tabs. The tab-switching code in `media_picker.js` is
  generic over `data-tab`/`data-panel` pairs, so the new panel needs no new tab logic.
- **`templates/courses/manage/media/_asset_cell.html`** — when `asset.source_url` is set,
  show a small link to the source, so an author can find the original later.

All new user-facing strings go through `{% trans %}`, followed by a `makemessages` pass
with Polish translations supplied. Expect the extraction to also sweep in msgids left
unextracted by earlier work; that is normal and not a defect of this change.

### 6. Client — `courses/static/courses/js/media_picker.js`

One new function, `fetchPickerUrl(url, name)`, mirroring the existing `uploadPickerFile`
(`media_picker.js:148`): POST to the fetch URL, and on a 200 parse the returned cell
fragment and call the existing `selectAsset` with its `data-asset-id`/`data-name`/
`data-url`. `selectAsset` itself is unchanged. On a non-200 it flashes the picker card,
exactly as the upload path does.

The manager page's existing form-interception path is extended the same way, so a
successful fetch prepends the new cell to the grid without a reload.

## Data

One migration, adding one field to `MediaAsset`:

```
source_url = models.URLField(max_length=500, blank=True, default="")
```

Blank for every existing row and for every uploaded asset; set only on the fetch path.

This path additionally populates the **existing** `content_hash` field, which
`create_asset` does not currently set — only the LAL loader does
(`courses/lal_loader/media.py:40`), and `replace_asset` deliberately blanks it
(`courses/media.py:197`). Computing it here is nearly free because the bytes are already
in hand.

To keep both fields validated by the single existing authority, `create_asset` gains two
optional keyword arguments, `source_url=""` and `content_hash=""`, which it sets on the
model **before** `full_clean()`. Defaulting both to empty leaves every existing caller —
including the transfer importer's `generate=False` path — behaving exactly as before.

`source_url` stores the URL **as pasted**, not the final post-redirect target: that is
what the author will recognise, and what a future URL-level dedup would need to
short-circuit on before spending a download.

**Neither field is exported.** The transfer manifest's media entry is validated by
`_exact_keys(m, ["id", "kind", "name", "original_filename", "file"], …)`
(`courses/transfer/schema.py:310`), so carrying `source_url` across an export would force
`FORMAT_VERSION` to 14 — which would collide with the callout-numbering bump already
pending on another branch, and identical version-constant bumps merge silently with no
conflict. `content_hash` is already local-only for the same reason, so this follows
established precedent. **This change does not bump `FORMAT_VERSION`.**

Dedup itself is not implemented. Capturing both fields now simply means that when dedup is
built later it needs no backfill.

## Data flow

**Happy path.** Author pastes a URL in the manager (or the picker's From URL tab) → POST
to `manage_media_fetch` → `_require_manage` authorises → `validate_fetch_url` accepts →
streaming GET, ≤3 validated redirect hops, body read under the cap → filename derived,
SHA-256 computed → `create_asset` runs `full_clean()` (extension + size) and generates
derivatives → `attach_usage` → `_asset_cell.html` at 200 → the client inserts the cell in
the manager, or selects the asset in the picker.

**Rejection path.** Any failure below raises `ValidationError`, which the view converts to
`_op_error.html` at 422 — identical to how `media_upload` surfaces a rejected upload.

## Error handling

Every one of these returns 422 with a short, human-readable message:

| Condition | Detected by |
|---|---|
| Scheme is not https | `validate_fetch_url` |
| Host not on the allow-list | `validate_fetch_url` |
| URL longer than 500 characters | `validate_fetch_url` |
| Redirect target leaves the allow-list | per-hop re-validation |
| More than 3 redirect hops | hop budget |
| Connection failure or timeout | `requests` exception, caught |
| Final status is not 200 | status check |
| `Content-Length` exceeds the cap | pre-read header check |
| Body exceeds the cap mid-stream | streaming accumulator |
| No allowed extension derivable | filename derivation |
| Extension or size rejected | `create_asset`'s `full_clean()` |

**The remote response body must never reach the user-facing message.** Error text is
composed by this application; a remote server's bytes are never echoed into a rendered
page. Messages should name the reason ("Image host is not on the allow-list"), not leak
internal detail such as resolved addresses.

A `ValidationError` from any stage leaves no partial asset behind: `create_asset` is
reached only after the bytes are fully in hand and validated as far as this layer can.

## Testing

TDD throughout. Per this repository's standing practice, **every new test must be
falsified against a deliberate mutant that proves it goes RED**, with the mutant chosen
from the failure mode the test claims to detect — a test that passes on a broken build
proves nothing, and this codebase has repeatedly shipped assertions that could not fail.

**Unit — `validate_fetch_url`:** an http URL rejected; an allow-listed host accepted; a
subdomain of an allow-listed host accepted; a look-alike host that merely *ends with* the
allowed string but is not a subdomain rejected; an over-length URL rejected.

**Unit — `fetch_image_asset`, against a mocked transport** (no real network in any unit
test): a redirect leaving the allow-list is rejected; the hop budget is enforced; the cap
trips mid-stream when `Content-Length` under-reports the true size; a declared
over-cap `Content-Length` rejects before the body is read; a timeout surfaces as a
`ValidationError`; the filename extension is derived from `Content-Type` when the URL path
carries none; `source_url` and `content_hash` are both persisted; the created asset is a
normal `MediaAsset` with derivatives generated.

**View:** each 422 shape reaches `_op_error.html`; success returns the asset cell at 200;
a non-manager user is refused by `_require_manage`; a GET is refused by `@require_POST`.

**E2E:** (a) pasting a URL in the media manager makes the asset appear in the grid; (b) the
picker's From URL tab fetches and selects the asset into an image element.

**The e2e must not touch the real network.** The test settings put the live test server's
host on `ALLOWED_IMAGE_FETCH_DOMAINS` and serve a fixture image from it, so the fetch is
real end-to-end while remaining hermetic and deterministic.

**Test-run mechanics for this repository:** the test-DB container must be started before
any run or the suite appears to hang; e2e requires `-m e2e` or every e2e test is
deselected; pytest's exit code can report 0 with failures present, so the summary line
must be read rather than the exit status trusted. Test runs must be scoped narrowly to the
affected tests — a whole-repo sweep is a branch-level gate, not a per-task step. This
worktree shares a machine with other active worktrees, so its test database must be
isolated via a `TEST_DATABASE_URL` prefix rather than by editing `.env`, and two pytest
runs must never execute concurrently.
