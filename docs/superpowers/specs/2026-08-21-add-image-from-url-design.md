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

- **URL-level dedup.** No logic that recognises "this URL was already fetched" and reuses
  the existing asset. Note this is specifically *URL-level*: content-hash dedup already
  exists in the LAL loader, and this change interacts with it deliberately — see
  "Interaction with the existing LAL dedup" under Data.
- **Video by URL.** Already served by the embed path (`VideoElement.url`); fetching video
  *files* would be a redundant second mechanism with far larger downloads.
- **Hotlinking** the remote URL, per the Purpose section above.
- **Exporting `source_url`** — see "Data" for why.
- **A learner-facing attribution line.** The existing `figcaption` field already carries
  "Źródło: Wikimedia" or equivalent, and `imageelement.html` already renders it.

## Architecture

Six components. Only one is a new module; the rest are additions to existing files.

### 1. `validate_fetch_url()` — `courses/validators.py`

A deliberate twin of the existing `validate_embed_url` (`courses/validators.py:118`),
which guards video/iframe embeds. Rules, checked in this order:

1. The URL must be non-empty. An empty or missing value gets its **own** message ("Enter
   an image URL."), because falling through to the scheme check would tell an author who
   simply submitted a blank field that their URL "must use https", which is misleading.
2. The URL must be at most 500 characters, so it cannot overflow the `source_url` column.
   Checked before any network access.
3. The scheme must be `https` — **unless** `settings.ALLOW_HTTP_IMAGE_FETCH` is true, in
   which case `http` is also accepted. See below.
4. The host must equal, or be a subdomain of, an entry in
   `settings.ALLOWED_IMAGE_FETCH_DOMAINS`.

Raises `ValidationError` on rejection, matching every other validator in the module.

**Why an allow-list rather than an open fetch with SSRF guards.** Pinning the host to a
known-good set *before any packet leaves the process* eliminates the entire SSRF class:
link-local metadata endpoints, the Postgres container, internal admin pages, and DNS
rebinding all become unreachable rather than merely defended against. An open fetch would
require resolving the host, rejecting private/loopback/link-local/CGNAT ranges, and
re-checking after every redirect — materially more code, more risk, and a much larger
review surface. Widening an allow-list later is a one-line config change; narrowing an
open fetch later removes a capability authors already rely on.

**`ALLOW_HTTP_IMAGE_FETCH` exists solely so the e2e can be hermetic.** pytest-django's
`live_server.url` is `http://127.0.0.1:<port>` — plain http — so an https-only rule makes
a real end-to-end fetch test impossible; the request would be rejected on scheme before
any network access. The setting defaults to `False` in `config/settings/base.py` and is
set to `True` **only** in `config/settings/test.py`. Because this is a security-relevant
escape hatch, **a unit test must assert that the base settings module leaves it `False`** —
the default being off is itself a tested property, not a convention.

### 2. New settings — `config/settings/base.py`

Declared alongside `ALLOWED_EMBED_DOMAINS` (`base.py:187`) and read the same way:

```
ALLOWED_IMAGE_FETCH_DOMAINS = env.list(
    "LIBLI_ALLOWED_IMAGE_FETCH_DOMAINS",
    default=["upload.wikimedia.org", "commons.wikimedia.org"],
)
IMAGE_FETCH_USER_AGENT = env(
    "LIBLI_IMAGE_FETCH_USER_AGENT",
    default="libli/1.0 (+https://github.com/krzyssikora/libli)",
)
ALLOW_HTTP_IMAGE_FETCH = env.bool("LIBLI_ALLOW_HTTP_IMAGE_FETCH", default=False)
```

`ALLOWED_IMAGE_FETCH_DOMAINS` is kept **separate** from `ALLOWED_EMBED_DOMAINS` rather
than reusing it: the two lists authorise different things (an iframe the browser loads vs.
a host this server will connect to), and silently granting server-side fetch to every
embed host would be a privilege widening nobody asked for.

`IMAGE_FETCH_USER_AGENT` is **not optional**. Wikimedia's User-Agent policy requires a
descriptive, contactable UA and returns 403 to generic library user-agents — and Wikimedia
is the entire default allow-list, so shipping without an explicit UA would mean the feature
fails against the only hosts it is configured to reach out of the box.

`.env.example` gains commented lines for all three, beside the existing
`LIBLI_ALLOWED_EMBED_DOMAINS` example at `.env.example:21`, so operators can discover them.

### 3. `courses/media_fetch.py` — the fetch service (new module)

One public entry point:

```
fetch_image_asset(course, url, user, name="") -> MediaAsset
```

It validates, downloads under a cap, and hands the bytes to the **existing**
`create_asset()` (`courses/media.py:108`), so per-kind extension/size validation
(`full_clean()`), derivative generation, and the rest of the asset pipeline run exactly as
they do for an upload. Nothing downstream of `create_asset` is aware a URL was involved.

Constants: `MAX_REDIRECT_HOPS = 3`, `FETCH_DEADLINE_SECONDS = 20`,
`CONNECT_TIMEOUT = 5`, `READ_TIMEOUT = 15`.

Internal steps:

1. `validate_fetch_url(url)`.
2. Record a monotonic deadline `FETCH_DEADLINE_SECONDS` from now (see step 6).
3. Issue a `GET` with `stream=True`, `allow_redirects=False`,
   `timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)`, and
   `headers={"User-Agent": settings.IMAGE_FETCH_USER_AGENT}`.
4. **Redirects are followed manually.** The redirect status set is exactly
   `{301, 302, 303, 307, 308}`. For each such response:
   - a missing or empty `Location` header is a rejection ("The image host returned an
     invalid redirect");
   - `Location` is resolved against the *current* URL with `urljoin` and then passed
     through `validate_fetch_url` again before being requested. This is the load-bearing
     guard: an allow-listed host that redirects off the allow-list must not be followed,
     and letting the HTTP client follow redirects itself would silently do exactly that;
   - every hop re-issues `GET` (the original method) with the same headers, timeouts and
     `allow_redirects=False`, regardless of whether the status was 303 or 307/308;
   - at most `MAX_REDIRECT_HOPS` hops are followed. A redirect status arriving when the
     budget is exhausted is reported as **"too many redirects"** — it never falls through
     to the not-200 branch, so the two error rows stay distinct.
5. Reject any final (non-redirect) response whose status is not 200.
6. **Content-Type is authoritative**, not a fallback. Take the response's `Content-Type`,
   strip parameters at the first `;`, trim, and case-fold. If the resulting media type is
   not a key of the media-type map (below), reject — *regardless of what the URL path
   looks like*. This is load-bearing: `https://commons.wikimedia.org/wiki/File:Example.jpg`
   is on the default allow-list, has a `.jpg` path, and returns `text/html`. Trusting the
   path extension would store an HTML page as a JPEG, and it would not even surface as an
   error, because `full_clean()` validates only extension and size and
   `generate_derivatives` never raises (it records `DerivativesState.FAILED` and returns),
   so the author would get a 200 and a broken asset.
7. **Byte cap.** The authoritative check is the streaming accumulator: read
   `iter_content` chunks, summing bytes, and reject as soon as the total exceeds
   `effective_max_image_bytes()`. A declared `Content-Length` above the cap is used as an
   early reject purely to avoid pointless transfer — it is **advisory only**: an absent,
   non-numeric, negative or duplicated header is simply ignored (never a rejection, and
   never a reason to relax the streaming check). This matters because `iter_content`
   yields *decompressed* bytes, so a gzipped response can declare a compressed length well
   under the cap and still exceed it once expanded.
8. **Wall-clock deadline.** The `requests` read timeout is per-socket-read, not a total
   deadline, so a slow-drip response staying under the byte cap could hold a worker
   indefinitely; across the initial request plus three hops the connect/read budget alone
   reaches roughly 80 s, well past a typical 30 s worker timeout. The deadline from step 2
   is therefore checked **between redirect hops and inside the chunk loop**, and exceeding
   it is a rejection.
9. **Reject an empty body.** Zero bytes is a rejection ("The fetched file is empty."),
   mirroring `replace_asset`'s existing check (`courses/media.py:185`). This is not
   covered by anything downstream: `media_upload` inherits its empty-file rejection from
   `MediaAssetForm`'s `forms.FileField`, which this path bypasses entirely, and
   `MediaAsset.clean()` has no lower size bound. Without this guard a `200` with
   `Content-Length: 0` creates a real asset with zero bytes, failed derivatives, and a 200
   response.
10. Derive a filename (see below).
11. Compute the SHA-256 of the fetched bytes.
12. Wrap the bytes in an uploaded-file object and call `create_asset(course, "image", …,
    source_url=url, content_hash=digest)`.

**Response lifetime.** Every response — the initial request, *each discarded redirect
hop*, the non-200 rejection, and the abandoned mid-stream cap trip — must be acquired via
`with requests.get(...) as resp:` or closed in a `finally`. With `stream=True`, dropping a
response without closing it returns an un-drained connection to the pool. There are four
such sites and all four need it.

`requests` is promoted from a transitive dependency to an explicit entry in
`pyproject.toml` — it is already resolved in `uv.lock` via django-allauth, but depending
on it directly without declaring it would be an undeclared dependency.

Ruff runs bandit rules (`select` includes `"S"` in `pyproject.toml`). `S113` (request
without timeout) must be satisfied by the real `timeout=` argument above, never by a
`noqa`.

#### Filename derivation

`MediaAsset` validation is extension-driven, so a fetched image needs a filename with an
allowed extension. The **media type decides the extension**; the URL path contributes only
a human-friendly stem.

Media-type map, media type → candidate extensions in preference order:

```
image/png  → ("png",)
image/jpeg → ("jpg", "jpeg")
image/gif  → ("gif",)
image/webp → ("webp",)
```

1. Media type comes from step 6 above (parameters stripped, case-folded), and is already
   known to be a key of the map.
2. The extension is the **first candidate for that media type that appears in
   `effective_image_extensions()`**. It must not be a hardcoded literal: an admin may
   narrow the allowed set to `["jpeg"]` alone, in which case a fixed `jpg` would build a
   filename that `full_clean()` then rejects for an image the server was configured to
   accept. If no candidate is allowed, reject ("This image type is not allowed.").
3. The stem is the basename of `urlsplit(url).path`, URL-unquoted, with any existing
   extension dropped; if the path yields no usable stem, the literal `image` is used.
   Django's storage backend uniquifies colliding names on save, so no further
   de-duplication is needed here.
4. The filename is `<stem>.<extension>`, passed through the existing `truncate_filename`
   (`courses/media.py:96`), which truncates while preserving the extension.

Extension comparisons are case-folded throughout: `effective_image_extensions()` returns
lowercase (`courses/validators.py:60`), so an uppercase path extension must not cause a
mismatch.

### 4. `media_fetch` view + route

`media_fetch(request, slug)` in `courses/views_media.py`, decorated:

```
@require_POST  # above @login_required: a non-POST is a 405 regardless of auth
@login_required
```

The order is load-bearing and matches the existing convention at `courses/views_media.py`
(`media_delete`, `media_replace`), which carry that exact comment. With the decorators
reversed, an anonymous GET would redirect to the login page instead of returning 405.

The view is gated by the existing `_require_manage(request, slug)` exactly as every other
media view is. It reads `url` and optional `name` from `request.POST`, calls
`fetch_image_asset`, and mirrors `media_upload`'s response contract:

- **fragment request, success** → render `courses/manage/media/_asset_cell.html` after
  `media_svc.attach_usage(asset)`, status 200;
- **fragment request, failure** → render `courses/manage/_op_error.html` with the message,
  status 422;
- **non-fragment request** (no JS) → `messages.error(request, <message>)` on failure, then
  `redirect("courses:manage_media", slug=course.slug)` in both cases. The messages
  framework is installed and already used this way in `courses/views_transfer.py:49`.
  Without the `messages.error` call a no-JS author pasting a rejected URL would get a bare
  302 back to the manager with no indication of what went wrong.

Matching the fragment contract exactly is what lets the existing client code in
`media_picker.js` handle the response without modification.

The route is registered as `manage_media_fetch` at
`manage/courses/<slug:slug>/media/fetch/`, beside `manage_media_upload`
(`courses/urls.py:279`).

### 5. Templates

- **`templates/courses/manage/media/manager.html`** — a second small form next to the
  existing upload form: a URL text input, the optional name input, and a submit button,
  posting to `manage_media_fetch`. The form's endpoint is also exposed to JS as
  `data-fetch-url` on the `.media-manager` root, mirroring the existing
  `data-upload-url` (`root.dataset.uploadUrl`).
- **`templates/courses/manage/media/_picker.html`** — a third tab and panel, "From URL",
  **rendered only under `{% if kind == "image" %}`**. This condition is required, not
  cosmetic: the picker is kind-generic (`<div class="picker" data-kind="{{ kind }}">`) and
  is opened for `VideoElement` too. An unconditional tab would offer a URL fetch in the
  video picker that creates an *image* asset and then selects it into a video field, where
  `_CourseScopedMediaForm` filters the queryset to `kind="video"` and rejects it — after
  the asset has already been created. The endpoint is exposed as `data-fetch-url` on
  `.picker`, mirroring the existing `data-upload-url`.
- **`templates/courses/manage/media/_asset_cell.html`** — when `asset.source_url` is set,
  show a small source link: `target="_blank" rel="noopener noreferrer"`, with the
  **hostname only** as the visible label and the full URL in `title`. A raw 500-character
  URL rendered inline would blow out the cell layout, which is why the cell already uses
  `middle_truncate` for names.

All new user-facing strings go through `{% trans %}`, followed by a `makemessages` pass
with Polish translations supplied. Expect the extraction to also sweep in msgids left
unextracted by earlier work; that is normal and not a defect of this change.

**Styling.** New CSS goes in `courses/static/courses/css/editor.css`, which already
carries `.media-upload` (`editor.css:343`) and the `.picker__*` family. The manager form
gets a `.media-fetch` class styled consistently with its `.media-upload` sibling, and the
new picker panel reuses `.picker__panel` with styling for its text input and button. This
repo's standing rule is that every view ships styled, so both surfaces require
light **and** dark screenshot verification, judged separately.

### 6. Client — `courses/static/courses/js/media_picker.js`

One new function, `fetchPickerUrl(url, name)`, mirroring the existing `uploadPickerFile`
(`media_picker.js:148`): POST to `data-fetch-url`, and on a 200 parse the returned cell
fragment and call the existing `selectAsset` with its `data-asset-id`/`data-name`/
`data-url`. `selectAsset` itself is unchanged.

**On a non-200 the returned `_op_error.html` text is rendered into the flash**, not
discarded. `uploadPickerFile` currently calls `flash(card, "Upload failed.")`
(`media_picker.js:162`) — a hardcoded English literal that throws the response body away.
Mirroring that exactly would make every rejection reason this spec enumerates ("Image host
is not on the allow-list", "The fetched file is empty", "This image type is not allowed")
invisible in the picker, which is one of the two entry points being shipped. The fallback
string, used only when the body is empty or unparseable, comes from a `data-msg-*`
attribute via the existing `msg(root, key, fallback)` helper (`media_picker.js:324`) rather
than a JS literal, so it is translatable.

The manager page's existing form-interception path is extended the same way, so a
successful fetch prepends the new cell to the grid without a reload, and a rejection
flashes the server's message.

## Data

One migration, `courses/migrations/0061_mediaasset_source_url.py`, with
`dependencies = [("courses", "0060_calloutelement_numbered")]` — the current graph head in
this branch. It adds one field to `MediaAsset`:

```
source_url = models.URLField(max_length=500, blank=True, default="")
```

Blank for every existing row and for every uploaded asset; set only on the fetch path.

`source_url` stores the URL **as pasted**, not the final post-redirect target: that is what
the author will recognise, and what a future URL-level dedup would need to short-circuit on
before spending a download.

To keep both new values validated by the single existing authority, `create_asset` gains
two optional keyword arguments, `source_url=""` and `content_hash=""`, which it sets on the
model **before** `full_clean()`. Defaulting both to empty leaves every existing caller —
including the transfer importer's `generate=False` path — behaving exactly as before.

**`replace_asset` must also clear `source_url`**, adding it to its
`update_fields=["file", "original_filename", "content_hash"]` list
(`courses/media.py:208`). `replace_asset` already blanks `content_hash` because a stale
hash mis-dedups a later LAL import (`courses/media.py:197`); `source_url` is the same class
of defect one step worse, because the `_asset_cell.html` source link would actively assert
a provenance that no longer describes the stored bytes.

### Interaction with the existing LAL dedup

Populating `content_hash` on this path is **not** behaviour-neutral, and the interaction is
intended rather than incidental. `courses/lal_loader/media.py:40` already does
`MediaAsset.objects.filter(course=course, content_hash=digest).first()` and reuses the row
it finds. Once fetched assets carry a hash, a later LAL import of byte-identical content
will reuse the fetched asset — inheriting its author-set `name` and its `source_url` —
instead of creating a second copy of the same bytes. That is the correct outcome (identical
bytes should be one asset, which is the point of the field), but it is a real behaviour
change and must be covered by a test rather than discovered later.

`create_asset` does not currently set `content_hash` at all — only the LAL loader does —
so computing it here is nearly free, because the bytes are already in hand.

### Why neither field is exported

The transfer manifest's media entry is validated by
`_exact_keys(m, ["id", "kind", "name", "original_filename", "file"], …)`
(`courses/transfer/schema.py:310`), which deliberately rejects unknown media keys. Both
`source_url` and `content_hash` are **local provenance, not portable content**: they
describe how this instance obtained the bytes, which has no meaning in another instance
that received them through an archive. `content_hash` is already local-only for exactly
this reason, and `source_url` follows that precedent.

**This change does not bump `FORMAT_VERSION`** (currently 13, `courses/transfer/schema.py:14`).

## Data flow

**Happy path.** Author pastes a URL in the manager (or the picker's From URL tab) → POST
to `manage_media_fetch` → `_require_manage` authorises → `validate_fetch_url` accepts →
streaming GET with the libli User-Agent, ≤3 validated redirect hops, Content-Type checked,
body read under the byte cap and the wall-clock deadline → filename derived from the media
type, SHA-256 computed → `create_asset` runs `full_clean()` (extension + size) and
generates derivatives → `attach_usage` → `_asset_cell.html` at 200 → the client inserts the
cell in the manager, or selects the asset in the picker.

**Rejection path.** Any failure below raises `ValidationError`. On a fragment request the
view converts it to `_op_error.html` at 422 — identical to how `media_upload` surfaces a
rejected upload. On a non-fragment request it becomes a `messages.error` plus a redirect.

## Error handling

Every condition below is a `ValidationError` carrying a short, human-readable message.
**On a fragment request each returns 422**; on a no-JS request each becomes a
`messages.error` followed by a redirect to the manager (see §4).

| Condition | Detected by |
|---|---|
| `url` missing or empty | `validate_fetch_url` |
| URL longer than 500 characters | `validate_fetch_url` |
| Scheme is not https (and http not permitted) | `validate_fetch_url` |
| Host not on the allow-list | `validate_fetch_url` |
| Redirect response with missing/empty `Location` | redirect handling |
| Redirect target leaves the allow-list | per-hop re-validation |
| More than 3 redirect hops | hop budget |
| Connection failure or timeout | `requests` exception, caught |
| Wall-clock deadline exceeded | deadline check |
| Final status is not 200 | status check |
| `Content-Type` is not a known image media type | media-type check |
| No allowed extension for that media type | filename derivation |
| `Content-Length` exceeds the cap (early reject) | pre-read header check |
| Body exceeds the cap mid-stream (authoritative) | streaming accumulator |
| Body is empty (zero bytes) | empty-body guard |
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

**Unit — `validate_fetch_url`:** empty URL rejected with its own message; over-length URL
rejected; an http URL rejected when `ALLOW_HTTP_IMAGE_FETCH` is false; an allow-listed host
accepted; a subdomain of an allow-listed host accepted; a look-alike host that merely
*ends with* the allowed string but is not a subdomain rejected.

**Unit — settings default:** `config/settings/base.py` leaves `ALLOW_HTTP_IMAGE_FETCH`
false. The escape hatch's default-off state is a tested property.

**Unit — `fetch_image_asset`, against a mocked transport** (no real network in any unit
test): a redirect leaving the allow-list is rejected; a redirect with no `Location` is
rejected; the hop budget is enforced and reports "too many redirects" rather than a
not-200 error; a `text/html` response at a `.jpg` path is rejected (the
`commons.wikimedia.org` case); the extension is chosen from `effective_image_extensions()`
rather than a literal, including when the allowed set is narrowed to `["jpeg"]`; a
`Content-Type` with parameters (`image/jpeg; charset=binary`) is accepted; a zero-byte body
is rejected; the cap trips mid-stream when `Content-Length` under-reports the true size; a
declared over-cap `Content-Length` rejects before the body is read; an absent or malformed
`Content-Length` is ignored rather than rejected; a timeout surfaces as a
`ValidationError`; the wall-clock deadline fires on a slow-drip body that stays under the
byte cap; the configured User-Agent is sent on the initial request **and on every redirect
hop**; `source_url` and `content_hash` are both persisted; the created asset is a normal
`MediaAsset` with derivatives generated.

**Unit — `replace_asset`:** replacing a fetched asset's bytes clears `source_url` as well
as `content_hash`.

**Unit — LAL interaction:** a LAL import of bytes identical to a previously fetched asset
reuses the fetched row rather than creating a second one.

**View:** each error shape reaches `_op_error.html` at 422 on a fragment request; a no-JS
request gets a `messages.error` plus a redirect; success returns the asset cell at 200; a
non-manager user is refused by `_require_manage`; an **authenticated** GET is refused with
405 by `@require_POST` (stated explicitly, because the decorator order is what makes this a
405 rather than a login redirect).

**Template:** the picker rendered with `kind="video"` has exactly two tabs and no From URL
panel; rendered with `kind="image"` it has three.

**E2E:** (a) pasting a URL in the media manager makes the asset appear in the grid; (b) the
picker's From URL tab fetches and selects the asset into an image element.

**The e2e must not touch the real network.** The mechanism is explicit: `config/settings/test.py`
sets `ALLOW_HTTP_IMAGE_FETCH = True` and puts `127.0.0.1` on `ALLOWED_IMAGE_FETCH_DOMAINS`,
and the URL under test is `{live_server.url}/static/core/img/learner.png` — an existing
17.9 KB PNG served by the live server's staticfiles handler, so the fetch is genuinely
end-to-end over a real socket while remaining hermetic and deterministic. The test should
assert that URL returns 200 before relying on it, so a staticfiles-serving change fails
loudly rather than as a confusing fetch rejection. Both e2e scenarios reuse the same URL.

**Test-run mechanics for this repository:** the test-DB container must be started before
any run or the suite appears to hang; e2e requires `-m e2e` or every e2e test is
deselected; pytest's exit code can report 0 with failures present, so the summary line
must be read rather than the exit status trusted. Test runs must be scoped narrowly to the
affected tests — a whole-repo sweep is a branch-level gate, not a per-task step. This
worktree shares a machine with other active worktrees, so its test database must be
isolated via a `TEST_DATABASE_URL` prefix rather than by editing `.env`, and two pytest
runs must never execute concurrently.
