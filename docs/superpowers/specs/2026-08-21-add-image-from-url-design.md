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

### 0. Transport: `urllib.request`, not `requests`

**This design deliberately reuses the repo's existing outbound-HTTP idiom rather than
introducing a second one.** No production module in this repo uses `requests` at all: both
existing outbound callers — `courses/geogebra.py` (the GeoGebra lookup) and
`integrations/delivery.py` (webhook delivery) — use `urllib.request` with a `_NoRedirect`
opener, a module-level socket timeout, and hand-written `S310` justifications.

The deciding factor is not stylistic consistency but that `geogebra.py` has already paid
for, measured, and documented the exact two lessons this feature needs, and a `requests`
implementation would have to re-learn both in a second dialect:

- **Socket timeouts do not bound a call.** `geogebra.py:57-63`: "This bounds urllib's
  SOCKET ops … NOT the total call … Measured: a peer dribbling one byte per second held a
  single read for 16.18s against this 3s timeout." The total bound is enforced separately.
- **`read1`, not `read`.** `geogebra.py:280-289`: "`HTTPResponse.read(n)` delegates to a
  `BufferedReader` that loops over `recv` until it has n bytes … Measured against a peer
  dripping one byte per 50ms: `read(8192)` blocked 10.13s for the whole body,
  `read1(8192)` returned in 0.05s." `requests.iter_content` has the same defect and
  exposes no `read1`, so a per-chunk deadline check under `iter_content` never fires on a
  drip body.

Using `urllib.request` therefore costs no new dependency (`pyproject.toml` is untouched),
inherits a proven transport seam for tests, and keeps one convention in the codebase. The
existing `geogebra.py` and `integrations/delivery.py` callers are left exactly as they are;
this feature simply joins them.

### 1. `validate_fetch_url()` — `courses/validators.py`

A deliberate twin of the existing `validate_embed_url` (`courses/validators.py:118`),
which guards video/iframe embeds.

**The value is stripped first.** The view passes `request.POST.get("url", "").strip()`,
and the stripped string is what is validated, fetched, and stored in `source_url`. This is
load-bearing rather than tidy-mindedness: a pasted URL routinely carries a leading space or
newline, and `urlsplit(" https://…")` yields an empty scheme, so an unstripped value fails
the scheme rule with "must use https" — exactly the misleading message rule 1 below exists
to prevent. Whitespace-only input must therefore test as empty.

Rules, checked in this order:

1. The URL must be non-empty **after stripping** → "Enter an image URL." It gets its own
   message because falling through to the scheme check would tell an author who submitted a
   blank field that their URL "must use https".
2. At most 500 characters, so it cannot overflow the `source_url` column → "That URL is too
   long (maximum 500 characters)."
3. It must pass Django's `URLValidator` → "That does not look like a valid URL." Running it
   here, before any network access, is what keeps the promise made in "Error handling" that
   nothing reaches `create_asset` un-validated: `create_asset` calls `full_clean()` with
   `source_url` set, so a URL that `urlsplit` parses but `URLValidator` rejects would
   otherwise surface as a late, mislabelled error *after* the bytes had been downloaded.
4. The scheme must be `https` — unless `settings.ALLOW_HTTP_IMAGE_FETCH` is true, in which
   case `http` is also accepted → "Image URLs must use https."
5. The host must equal, or be a subdomain of, an entry in
   `settings.ALLOWED_IMAGE_FETCH_DOMAINS` → "That image host is not on the allow-list."

Raises `ValidationError` on rejection. **All messages in this module and in
`media_fetch.py` use `gettext_lazy`**, deliberately diverging from `validate_embed_url`,
which raises bare English literals: §6 goes to real lengths to display these strings
verbatim to the author, so an untranslated literal would ship English into a Polish UI.
They are included in the `makemessages` pass.

**Why an allow-list rather than an open fetch with SSRF guards.** Pinning the host to a
known-good set *before any packet leaves the process* eliminates the entire SSRF class:
link-local metadata endpoints, the Postgres container, internal admin pages, and DNS
rebinding all become unreachable rather than merely defended against. An open fetch would
require resolving the host, rejecting private/loopback/link-local/CGNAT ranges, and
re-checking after every redirect — materially more code, more risk, and a much larger
review surface.

**The allow-list is the only defence, so widening it is not risk-free.** There is no
IP-level guard behind it, and the match rule inherited from `validate_embed_url`
(`host == d or host.endswith("." + d)`) accepts **every** subdomain. An operator who adds a
host whose subdomain tree is third-party controlled — `s3.amazonaws.com`, `github.io`,
`blogspot.com`, most CDNs — hands an attacker a hostname whose DNS they control, pointing
anywhere they like, including loopback and cloud metadata endpoints. Entries must therefore
be hosts whose **entire subdomain tree** is trusted. This warning belongs both here and as
a comment beside the `.env.example` line.

**The port is deliberately unconstrained.** `urlsplit().hostname` drops the port, so
`https://upload.wikimedia.org:9999/x.png` is accepted and the server will connect to that
port. This is a conscious trade: the e2e reaches the live test server on a random high
port, so pinning the port to the scheme default would break the only end-to-end coverage.
It is a real part of the security surface and is acceptable only because of the
whole-subdomain-tree trust rule above.

**`ALLOW_HTTP_IMAGE_FETCH` exists solely so the e2e can be hermetic.** pytest-django's
`live_server.url` is plain **http** (`http://localhost:<port>` — see Testing), so an
https-only rule makes a real end-to-end fetch test impossible; the request would be rejected
on scheme before any network access. The setting defaults to `False` in
`config/settings/base.py` and is set to `True` **only** in `config/settings/test.py`.
Because this is a security-relevant escape hatch, **a unit test must assert that the base
settings module leaves it `False`** — the default being off is itself a tested property.

### 2. New settings — `config/settings/base.py`

Declared alongside `ALLOWED_EMBED_DOMAINS` (`base.py:187`) and read the same way:

```
ALLOWED_IMAGE_FETCH_DOMAINS = env.list(
    "LIBLI_ALLOWED_IMAGE_FETCH_DOMAINS",
    default=["upload.wikimedia.org", "commons.wikimedia.org"],
)
ALLOW_HTTP_IMAGE_FETCH = env.bool("LIBLI_ALLOW_HTTP_IMAGE_FETCH", default=False)
```

`ALLOWED_IMAGE_FETCH_DOMAINS` is kept **separate** from `ALLOWED_EMBED_DOMAINS` rather
than reusing it: the two lists authorise different things (an iframe the browser loads vs.
a host this server will connect to), and silently granting server-side fetch to every
embed host would be a privilege widening nobody asked for.

**The User-Agent is a shared module constant, not a setting.** `courses/geogebra.py:78`
already defines `_USER_AGENT = "libli/1.0 (+https://github.com/krzyssikora/libli)"` and
argues explicitly for a constant over a setting ("matching the pattern of
`integrations/delivery.py`"). Rather than duplicate that literal or contradict that
precedent, lift it to a single shared constant that both callers import — `core`-level or a
small `courses/http_ua.py` — and have `geogebra.py` import it too. It is **not optional**:
Wikimedia's User-Agent policy requires a descriptive, contactable UA and returns 403 to
generic library user-agents, and Wikimedia is the entire default allow-list, so the feature
would fail against the only hosts it is configured to reach out of the box.

`.env.example` gains commented lines for both settings, beside the existing
`LIBLI_ALLOWED_EMBED_DOMAINS` example at `.env.example:21`, with the
whole-subdomain-tree warning from §1 as a comment on the domains line.

**`config/settings/test.py` replaces the list outright** (it does not extend it):

```
ALLOWED_IMAGE_FETCH_DOMAINS = ["localhost", "127.0.0.1"]
ALLOW_HTTP_IMAGE_FETCH = True
```

Replacement, not extension, is deliberate and mirrors how `GEOGEBRA_API_LOOKUP = False` is
handled in the same file: with the Wikimedia hosts still listed, a unit test whose mock
failed to intercept could reach the real network. Consequently **mocked unit tests must
name their own hosts via `override_settings`** rather than assuming Wikimedia is
allow-listed.

### 3. `courses/media_fetch.py` — the fetch service (new module)

One public entry point:

```
fetch_image_asset(course, url, user, name="") -> MediaAsset
```

It validates, downloads under a cap and a wall-clock budget, verifies the payload, and
hands the bytes to the **existing** `create_asset()` (`courses/media.py:108`), so per-kind
extension/size validation (`full_clean()`), derivative generation, and the rest of the
asset pipeline run exactly as they do for an upload. Nothing downstream of `create_asset`
is aware a URL was involved.

Module constants, mirroring `geogebra.py`'s set: `MAX_REDIRECT_HOPS = 3`,
`TIMEOUT_SECONDS = 8` (per socket op), `DEADLINE_SECONDS = 20` (total),
`CHUNK_BYTES = 64 * 1024`.

**Naming.** The spec uses two distinct names throughout, and the implementation must too:
`submitted_url` (the stripped value the author pasted) and `current_url` (the hop being
requested). Collapsing them into one `url` variable is the natural way to write the
redirect loop and it silently breaks the Data section's guarantee that `source_url` stores
the submitted URL, because `url = urljoin(url, location)` would leave the final target in
scope at `create_asset` time.

Internal steps:

1. `validate_fetch_url(submitted_url)`.
2. Read `effective_max_image_bytes()` and `effective_image_extensions()` **once** into
   locals. Both go through `_site_config()` → `get_site_config()` (a cache read, and a DB
   read on a miss); calling them inside the chunk loop or per candidate extension would
   re-evaluate them needlessly.
3. **The whole transport runs on a daemon thread joined with a budget**, exactly as
   `geogebra.py:442-452` does: start the thread, `thread.join(DEADLINE_SECONDS)`, snapshot
   the result box once, and treat a missing result as "deadline exceeded". This is the
   *only* mechanism that actually bounds wall clock. A per-socket `timeout=` — whether
   urllib's or `requests`' — bounds each `connect`/`recv`, never the total call: a peer
   emitting one header byte every few seconds keeps every individual read inside the
   timeout and parks the worker indefinitely, which `geogebra.py:57-63` measured at 16.18 s
   against a 3 s timeout. Note this makes the repo's **second** production background
   thread; that is a deliberate choice, taken because the alternative is an unbounded
   worker.
4. On the worker thread, issue a `GET` via a `_NoRedirect` opener (the handler pattern in
   both `geogebra.py:272` and `integrations/delivery.py:23`), with `timeout=TIMEOUT_SECONDS`
   and headers `User-Agent: <shared constant>` and `Accept: image/*`. The `Accept` header
   costs nothing and improves the odds a content-negotiating host returns the image rather
   than an HTML page — the `commons.wikimedia.org` case below is exactly a
   negotiation-shaped failure.
5. **Redirects are followed manually.** The redirect status set is exactly
   `{301, 302, 303, 307, 308}`. For each such response:
   - a missing or empty `Location` header is a rejection → "The image host returned an
     invalid redirect.";
   - `Location` is resolved against `current_url` with `urljoin`, then passed through
     `validate_fetch_url` again before being requested → "That URL redirects to a host that
     is not on the allow-list." This is the load-bearing guard: an allow-listed host that
     redirects off the allow-list must not be followed, and an auto-following client would
     silently do exactly that;
   - every hop re-issues `GET` with the same headers and timeout, regardless of whether the
     status was 303 or 307/308;
   - at most `MAX_REDIRECT_HOPS` hops → "That URL redirects too many times." A redirect
     status arriving when the budget is exhausted reports *that*, never the not-200 message,
     so the two error rows stay distinct.
6. Reject any final (non-redirect) response whose status is not 200 → "The image host
   returned an error (status %(status)s)."
7. **Content-Type is a cheap pre-read gate.** Take the response's `Content-Type`, strip
   parameters at the first `;`, trim, case-fold, and reject anything that is not a key of
   the media-type map → "That URL did not return an image." This is checked *before* the
   body is read so an HTML page is abandoned early. It is a gate, not the authority on the
   extension — see step 11.
8. **Byte cap, read with `read1`.** Loop `response.read1(CHUNK_BYTES)`, accumulating, and
   reject as soon as the total exceeds the cap from step 2 → the existing "Image file too
   large (max %(mib)d MiB)." wording. `read1`, not `read`, is mandatory and is the reason
   the deadline check inside this loop can fire at all: `read(n)` loops over `recv` until it
   has n bytes, so on a drip body it never returns and a per-chunk check never runs. A
   declared `Content-Length` above the cap is an early reject purely to avoid pointless
   transfer — **advisory only**: absent, non-numeric, negative or duplicated headers are
   ignored, never a rejection and never a reason to relax the streaming check. The loop
   deliberately reads one chunk *past* the cap so oversize stays detectable, per
   `geogebra.py`'s comment on the same loop.
9. **Reject an empty body** → "The fetched file is empty.", mirroring `replace_asset`'s
   existing check (`courses/media.py:185`). Nothing downstream covers this: `media_upload`
   inherits its empty-file rejection from `MediaAssetForm`'s `forms.FileField`, which this
   path bypasses, and `MediaAsset.clean()` has no lower size bound. Without the guard a 200
   with `Content-Length: 0` creates a real asset with zero bytes, failed derivatives, and a
   200 response.
10. **Verify the payload really is an image, and capture its true format.** Open the
    buffered bytes with Pillow, keep `img.format`, then `verify()`. On failure reject with
    "That URL did not return a usable image."

    The handler is a **broad `except Exception`**, in the style of `geogebra.py`'s
    documented broad catches, and `PIL.Image.DecompressionBombError` is explicitly inside
    that set. A narrow `except UnidentifiedImageError` is a real 500: `Image.open` also
    raises `OSError`, `ValueError`, `SyntaxError` from individual plugins, and
    `DecompressionBombError` from `_decompression_bomb_check` at open time when the declared
    canvas exceeds 2 × `MAX_IMAGE_PIXELS` — reachable with a crafted few-hundred-KB PNG well
    inside the 5 MiB cap. Since the view catches only `ValidationError`
    (`courses/views_media.py:47`), anything not converted here is a 500, not the specified
    422. This is the same hole the spec closes for `urllib.error` in the transport section.

    Step 7's own argument compels this step: *nothing downstream ever looks at the bytes* —
    `_validate_file` checks extension and size only, and `generate_derivatives` swallows its
    failure — so an allow-listed host that mislabels its payload would otherwise produce
    exactly the silent broken-asset outcome step 7 exists to prevent.
11. Derive a filename (see below), using `img.format` from step 10.
12. Compute the SHA-256 of the bytes.
13. Wrap as `ContentFile(data, name=filename)` and call
    `create_asset(course, "image", content_file, user, name=name,
    source_url=submitted_url, content_hash=digest)`. The derived filename must be the
    wrapper's `.name`, not a separate argument: `create_asset` reads
    `truncate_filename(uploaded_file.name)` for both `original_filename` and the storage
    path, so a nameless `ContentFile` yields an empty `original_filename`. The wrapper must
    also be an **uncommitted** file object — a committed `FieldFile` makes `_validate_file`
    short-circuit and skip both the extension and the size check, the trap `replace_asset`'s
    docstring already documents.

**Response lifetime.** Every response — the initial request, *each discarded redirect hop*,
the non-200 rejection, and the abandoned mid-stream cap trip — is acquired via
`with opener.open(...) as resp:`. Dropping a response without closing it returns an
un-drained connection. There are four such sites and all four need it.

**Transport failures.** Both the request *and the read loop* are wrapped in
`except (TimeoutError, urllib.error.HTTPError, urllib.error.URLError, OSError)` — the set
`integrations/delivery.py:67` already uses, widened to `OSError` for mid-read socket
failures — and converted to a `ValidationError` reading "Could not reach the image host."
Wrapping only the `open()` call is not enough: a DNS failure raises there, but a truncated
body raises from inside the read loop, after the `with` block has been entered.

**Logging.** Every rejection point emits a `logger.warning` naming the host, the status or
Content-Type, and a reason token — never the response body. The author-facing message is
deliberately detail-free, so without this an operator diagnosing "an allow-listed host
started 403-ing our User-Agent" has nothing to work from. `geogebra.py` treats logging as
part of the contract for exactly this reason.

**`S310` (bandit, `urllib.request` audit) is satisfied with a written justification
comment**, in the same form `geogebra.py` and `integrations/delivery.py` already use — the
scheme is constrained to http/https by `validate_fetch_url` before any request is built.
It is never silenced with a bare `noqa`.

#### Filename derivation

The **sniffed format decides the extension**; the URL path contributes only a
human-friendly stem.

Media-type map, media type → candidate extensions in preference order:

```
image/png  → ("png",)
image/jpeg → ("jpg", "jpeg")
image/jpg  → ("jpg", "jpeg")      # non-standard but widely emitted
image/gif  → ("gif",)
image/webp → ("webp",)
```

Pillow-format map, `img.format` → the same candidate lists: `PNG`, `JPEG`, `GIF`, `WEBP`.

1. **The extension is chosen from `img.format` (step 10), not from `Content-Type`.** The
   header is only the pre-read gate. This is step 7's own argument applied one level
   further: a host serving GIF bytes under `Content-Type: image/png` passes the header gate
   *and* `verify()` — the bytes are a decodable image — and would be stored as `foo.png`
   containing a GIF, which `full_clean()` (extension only) would never notice. `img.format`
   is populated before `verify()` and survives it, is free, and is strictly more
   trustworthy than a remote header.
2. The extension is the **first candidate for that format present in
   `effective_image_extensions()`** (read once at step 2). Never a hardcoded literal: an
   admin may narrow the allowed set to `["jpeg"]` alone, in which case a fixed `jpg` would
   build a filename `full_clean()` then rejects for an image the server was configured to
   accept. If no candidate is allowed → "That image type is not allowed."
3. **The stem is sanitized, and the order of operations matters.** URL-unquote the path
   *first*, then take the basename, then strip path separators, `..` segments, control
   characters and leading dots; if nothing usable survives, use the literal `image`.
   Unquoting *after* the basename is a real defect, not a style point: a path ending
   `..%2F..%2Fx.png` has the basename `..%2F..%2Fx.png`, which unquotes to `../../x.png`,
   lands in `ContentFile.name`, and makes Django's `Storage.generate_filename` raise
   `SuspiciousFileOperation` — a 500, since only `ValidationError` is caught. Short of
   traversal, an unquoted stem can carry `/`, `\`, NUL or leading dots straight into
   `original_filename`, which has no validator.
4. The filename is `<stem>.<extension>`, passed through the existing `truncate_filename`
   (`courses/media.py:96`), which truncates while preserving the extension.
5. **The stem comes from `current_url`** — the final hop — not `submitted_url`. This is the
   one place the final target is the better source:
   `https://commons.wikimedia.org/wiki/Special:FilePath/Foo.jpg` redirects to an
   `upload.wikimedia.org` path whose basename is the useful one, while the submitted path's
   basename is `Special:FilePath`. `source_url` still stores `submitted_url` (Data).

Extension comparisons are case-folded throughout: `effective_image_extensions()` returns
lowercase (`courses/validators.py:60`), so an uppercase path extension must not mismatch.

### 4. `media_fetch` view + route

`media_fetch(request, slug)` in `courses/views_media.py`, decorated:

```
@require_POST  # above @login_required: a non-POST is a 405 regardless of auth
@login_required
```

The order is load-bearing and matches the existing convention at `courses/views_media.py`
(`media_delete`, `media_replace`), which carry that exact comment. With the decorators
reversed, an anonymous GET would redirect to the login page instead of returning 405.

**Import form:** `from courses.media_fetch import fetch_image_asset`. The module and the
view share the name `media_fetch`, so `from courses import media_fetch` followed by
`def media_fetch(...)` would rebind the name at module load and fail later with an
`AttributeError` at call time rather than at import. (The file's existing
`from courses import media as media_svc` alias exists for exactly this reason.)

The view is gated by the existing `_require_manage(request, slug)` exactly as every other
media view is. It reads `url` (stripped, per §1) and optional `name` from `request.POST`,
calls `fetch_image_asset`, and mirrors `media_upload`'s response contract:

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
`media_picker.js` handle the success response without modification.

The route is registered as `manage_media_fetch` at
`manage/courses/<slug:slug>/media/fetch/`, beside `manage_media_upload`
(`courses/urls.py:279`).

### 5. Templates

- **`templates/courses/manage/media/manager.html`** — a second small form next to the
  existing upload form, with `{% csrf_token %}`, an optional name input, a submit button,
  and a URL input pinned as
  `<input type="url" name="url" required placeholder="https://…">`. The `{% csrf_token %}`
  is called out because omitting it breaks *only* the no-JS path, which nothing else would
  catch: Django's test client does not enforce CSRF by default, and the e2e drives the JS
  path, which sends the header instead.

  `type="url"` + `required` is the deliberate choice: the browser blocks an empty or
  obviously malformed submit, saving a round trip. The server-side empty check is **not**
  thereby dead — it stays reachable from the picker (whose input is not inside a form, so
  no native validation applies) and from any non-browser client, and that is where its test
  lives.

  The endpoint is exposed to JS as `data-fetch-url` on the `.media-manager` root, mirroring
  the existing `data-upload-url` (`root.dataset.uploadUrl`).

- **`templates/courses/manage/media/_picker.html`** — a third tab and panel, "From URL",
  **rendered only under `{% if kind == "image" %}`**. This condition is required, not
  cosmetic: the picker is kind-generic (`<div class="picker" data-kind="{{ kind }}">`) and
  is opened for `VideoElement` too. An unconditional tab would offer a URL fetch in the
  video picker that creates an *image* asset and then selects it into a video field, where
  `_CourseScopedMediaForm` filters the queryset to `kind="video"` and rejects it — after
  the asset has already been created.

  **Panel contents and activation, stated explicitly** because the picker is not a form
  context: the overlay is appended to `document.body` (`media_picker.js:91`), so it has no
  `<form>` ancestor, no implicit submission exists, and every in-panel control is driven by
  the delegated `document` click handler at `media_picker.js:126`. The panel contains a
  single URL input `[data-picker-url]` and a button `[data-picker-fetch]` — **no name
  field**; `fetchPickerUrl(url)` is always called without a name, and an author who wants
  one renames the asset in the manager. Activation is (a) a new branch in the existing
  delegated `document` click handler keyed on `[data-picker-fetch]`, and (b) an explicit
  `keydown`/Enter handler on `[data-picker-url]`, mirroring how `[data-picker-search]` is
  wired for input events. Without (b), Enter in that input is silently dead.

  The endpoint is exposed as `data-fetch-url` on `.picker`, mirroring `data-upload-url`.

- **`templates/courses/manage/media/_asset_cell.html`** — when `asset.source_url` is set,
  show a small source link in the **`.asset-foot`** region (beside the usage details),
  with a new `.asset-source` class: `target="_blank" rel="noopener noreferrer"`, the
  **hostname only** as the visible label, and the full URL in `title`. A raw 500-character
  URL rendered inline would blow out the cell layout, which is why the cell already uses
  `middle_truncate` for names. Naming the region matters because it is what the light/dark
  screenshot verification below is checked against.

  The hostname comes from a **`MediaAsset.source_host` property** (the `urlsplit` hostname
  of `source_url`, or `""`), not from view context. Django has no hostname filter, and this
  cell is rendered from five places — the grid include, upload, rename, replace, and the
  new fetch view — so a hostname passed through context would be missing in most of them
  and the label would silently render blank. **The property must swallow `ValueError` and
  return `""`**: `urlsplit(...).hostname` raises on a malformed authority (a bracketed IPv6
  remnant, an out-of-range port), and this runs for every asset in the manager grid, so one
  bad row would otherwise 500 the whole page. `courses/geogebra.py`'s `geogebra_material_id`
  wraps the same call in `try/except (ValueError, TypeError, IndexError)` for this reason.

All new user-facing template strings go through `{% trans %}`; the Python-side messages use
`gettext_lazy` (§1). Both are covered by one `makemessages` pass with Polish translations
supplied. Expect the extraction to also sweep in msgids left unextracted by earlier work;
that is normal and not a defect of this change.

**Styling.** New CSS goes in `courses/static/courses/css/editor.css`, which already
carries `.media-upload` (`editor.css:343`) and the `.picker__*` family. The manager form
gets a `.media-fetch` class styled consistently with its `.media-upload` sibling; the new
picker panel reuses `.picker__panel` with styling for its text input and button; the cell
link gets `.asset-source`. This repo's standing rule is that every view ships styled, so all
three surfaces require light **and** dark screenshot verification, judged separately.

### 6. Client — `courses/static/courses/js/media_picker.js`

One new function, `fetchPickerUrl(url)`, mirroring the existing `uploadPickerFile`
(`media_picker.js:148`): POST to `data-fetch-url` with `X-CSRFToken: csrf()` and
`X-Requested-With: fetch` like every other POST in this file, and on a 200 parse the
returned cell fragment and call the existing `selectAsset` with its
`data-asset-id`/`data-name`/`data-url`. `selectAsset` itself is unchanged.

**In-flight state is required, not a nicety.** The fetch can legitimately take up to
`DEADLINE_SECONDS` (20 s) with no visual change. The delegated click handler has no guard,
so an author who clicks twice — the near-certain response to a dead-looking button — issues
two POSTs, and since URL-level dedup is an explicit non-goal, both succeed and two identical
assets are created (in the picker, the second `selectAsset` also overwrites the first). The
upload path is not a precedent: a file-picker dialog interposes a natural gate that a
paste-and-click does not. So: disable `[data-picker-fetch]` (and the manager submit button)
on dispatch, set `aria-busy`, and re-enable in **both** the success and failure branches.

**On a non-200 the server's reason is shown, not discarded.** `uploadPickerFile` currently
calls `flash(card, "Upload failed.")` (`media_picker.js:162`) — a hardcoded English literal
that throws the response body away. Mirroring that exactly would make every rejection reason
this spec enumerates invisible in the picker, one of the two entry points being shipped.

The mechanism must be precise, because the response is markup, not a string:
`_op_error.html` renders `<div class="op-error" role="alert">Couldn't apply that change:
{{ message }}</div>`, while `flash(host, msg)` sets `bar.textContent = msg`
(`media_picker.js:6`). Passing the raw response text to `flash()` would display the tags
literally; passing it as `innerHTML` would nest an `.op-error` with a second `role="alert"`
inside the flash's own. So: **parse the returned fragment** (as `uploadPickerFile` already
does for the cell), read the `.op-error` element's `textContent`, and pass that string to
`flash()`. The "Couldn't apply that change:" prefix is kept verbatim — it is what the
manager surface already shows for every other operation, and stripping it would need
special-casing.

The fallback string, used only when the body is empty or unparseable, comes from a
`data-msg-fetch-failed` attribute read via the existing `msg(host, key, fallback)` helper
(`media_picker.js:240`) rather than a JS literal, so it is translatable. **The host element
differs per surface and must be named:** on the manager it is `.media-manager` (where every
existing `data-msg-*` attribute lives); in the picker, `msg()` must be called against the
`.picker` element, **not** the picker path's `root`, which is
`document.querySelector(".editor")` (`media_picker.js:20`) and carries no such attributes.
Getting this wrong is invisible at runtime — `msg()` silently returns the untranslated
fallback — which is why the attribute's presence is asserted by a test.

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
`MediaAsset` also gains the read-only `source_host` property described in §5.

`source_url` stores **`submitted_url`** — the stripped value the author pasted — not the
final post-redirect target: that is what the author will recognise, and what a future
URL-level dedup would need to short-circuit on before spending a download. (The *stem*
comes from the final hop; see Filename derivation step 5. These two deliberately differ.)

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
to `manage_media_fetch` → `_require_manage` authorises → `validate_fetch_url` accepts the
stripped URL → a daemon thread joined with a 20 s budget runs the transport: GET with the
shared User-Agent and `Accept: image/*`, ≤3 validated redirect hops, Content-Type gate,
body read with `read1` under the byte cap → payload verified by Pillow and its true format
captured → filename derived from that format, SHA-256 computed → `create_asset` runs
`full_clean()` (extension + size) and generates derivatives → `attach_usage` →
`_asset_cell.html` at 200 → the client inserts the cell in the manager, or selects the asset
in the picker.

**Rejection path.** Any failure below raises `ValidationError`. On a fragment request the
view converts it to `_op_error.html` at 422 — identical to how `media_upload` surfaces a
rejected upload. On a non-fragment request it becomes a `messages.error` plus a redirect.

## Error handling

Every condition is a `ValidationError` carrying the message below (all `gettext_lazy`).
**On a fragment request each returns 422**; on a no-JS request each becomes a
`messages.error` followed by a redirect to the manager (§4). Pinning the exact text here
makes this the single source for the implementation, the view tests, and the `.po` entries —
the picker now shows these strings verbatim.

| Condition | Message | Detected by |
|---|---|---|
| `url` missing, empty, or whitespace-only | "Enter an image URL." | `validate_fetch_url` |
| URL longer than 500 characters | "That URL is too long (maximum 500 characters)." | `validate_fetch_url` |
| URL malformed | "That does not look like a valid URL." | `URLValidator` |
| Scheme not https (and http not permitted) | "Image URLs must use https." | `validate_fetch_url` |
| Host not on the allow-list | "That image host is not on the allow-list." | `validate_fetch_url` |
| Redirect with missing/empty `Location` | "The image host returned an invalid redirect." | redirect handling |
| Redirect target leaves the allow-list | "That URL redirects to a host that is not on the allow-list." | per-hop re-validation |
| More than 3 redirect hops | "That URL redirects too many times." | hop budget |
| Connection failure, timeout, or mid-read error | "Could not reach the image host." | `urllib.error`/`OSError`, converted |
| Wall-clock deadline exceeded | "Fetching the image took too long." | thread join budget |
| Final status is not 200 | "The image host returned an error (status %(status)s)." | status check |
| `Content-Type` is not a known image media type | "That URL did not return an image." | media-type gate |
| No allowed extension for the sniffed format | "That image type is not allowed." | filename derivation |
| Body exceeds the cap (authoritative) | "Image file too large (max %(mib)d MiB)." | `read1` accumulator |
| Body is empty (zero bytes) | "The fetched file is empty." | empty-body guard |
| Bytes are not a decodable image | "That URL did not return a usable image." | Pillow, broad catch |
| Extension or size rejected | (existing validator messages) | `create_asset`'s `full_clean()` |

A declared over-cap `Content-Length` uses the same "too large" message as the streaming
check; it is an early exit, not a distinct condition.

**The remote response body must never reach the user-facing message.** Error text is
composed by this application; a remote server's bytes are never echoed into a rendered
page. Diagnostic detail goes to the log (§3), never to the author.

A `ValidationError` from any stage leaves no partial asset behind: `create_asset` is
reached only after the bytes are fully in hand, verified as an image, and validated as far
as this layer can.

## Testing

TDD throughout. Per this repository's standing practice, **every new test must be
falsified against a deliberate mutant that proves it goes RED**, with the mutant chosen
from the failure mode the test claims to detect — a test that passes on a broken build
proves nothing, and this codebase has repeatedly shipped assertions that could not fail.

**The transport seam is `_open(request, timeout)`**, mirroring `geogebra.py:272` ("The
transport seam. Patched by tests; the only place the network is touched"). Unit tests patch
it; no unit test touches a real socket.

**Unit — `validate_fetch_url`:** empty URL rejected with its own message; whitespace-only
rejected the same way; a whitespace-padded valid URL accepted, and the stripped value is
what is used; over-length rejected; malformed rejected by `URLValidator`; an http URL
rejected when `ALLOW_HTTP_IMAGE_FETCH` is false; an allow-listed host accepted; a subdomain
accepted; a look-alike host that merely *ends with* the allowed string rejected. Hosts come
from `override_settings`, since `test.py` replaces the production list (§2).

**Unit — settings default:** `config/settings/base.py` leaves `ALLOW_HTTP_IMAGE_FETCH`
false. The escape hatch's default-off state is a tested property.

**Unit — `fetch_image_asset`, with `_open` patched:** a redirect leaving the allow-list is
rejected; a redirect with no `Location` is rejected; the hop budget reports "too many
redirects", not a not-200 error; a `text/html` response at a `.jpg` path is rejected (the
`commons.wikimedia.org` case); HTML bytes under an `image/png` Content-Type are rejected by
Pillow; **a decompression-bomb PNG is rejected as a 422, not raised as a 500**; **GIF bytes
served as `image/png` are stored with a `.gif` name** (the sniffed format wins over the
header); the extension is chosen from `effective_image_extensions()` rather than a literal,
including when the allowed set is narrowed to `["jpeg"]`; a `Content-Type` with parameters
(`image/jpeg; charset=binary`) is accepted; `image/jpg` is accepted; a zero-byte body is
rejected; the cap trips when `Content-Length` under-reports; a declared over-cap
`Content-Length` rejects before the body is read; an absent or malformed `Content-Length` is
ignored; a connect failure and a **mid-read** failure both surface as `ValidationError`
rather than 500; a `%2F`-bearing path cannot escape the media directory and falls back
safely; a **redirected** fetch persists `submitted_url` in `source_url` while taking its
stem from the final hop; the shared User-Agent and `Accept: image/*` are sent on the initial
request **and every redirect hop**; `source_url` and `content_hash` are both persisted; the
created asset is a normal `MediaAsset` with derivatives generated.

**Unit — the deadline, deliberately not a generator double.** The drip tests must use a
fake whose `read1` returns *partial* data slowly (a raw-file-like double or a real socket),
never a generator that yields on demand: a generator-based fake returns instantly and the
test passes GREEN on a build that reads with `read` instead of `read1` — the exact
"assertion that cannot fail" this repo has shipped before. Cover both a drip **body** and a
drip **header** (the latter is what the thread-join budget, not the socket timeout, is
there for).

**Unit — `replace_asset`:** replacing a fetched asset's bytes clears `source_url` as well
as `content_hash`.

**Unit — LAL interaction:** a LAL import of bytes identical to a previously fetched asset
reuses the fetched row rather than creating a second one.

**Unit — `source_host`:** returns the hostname for a normal URL, `""` for blank, and `""`
rather than raising for a malformed authority.

**View:** each error shape reaches `_op_error.html` at 422 on a fragment request; a no-JS
request gets a `messages.error` plus a redirect; success returns the asset cell at 200; a
non-manager user is refused by `_require_manage`; an **authenticated** GET is refused with
405 by `@require_POST` (stated explicitly, because the decorator order is what makes this a
405 rather than a login redirect).

**Template:** the picker rendered with `kind="video"` has exactly two tabs and no From URL
panel; with `kind="image"`, three. A fetched asset's `_asset_cell.html` renders the source
link in `.asset-foot` with the hostname as its label, the full URL in `title`, and
`rel="noopener noreferrer"`. The `data-msg-fetch-failed` attribute is present on
`.media-manager` and on `.picker` — asserted because a missing attribute is invisible at
runtime, `msg()` silently falling back to the untranslated literal.

**E2E:** (a) pasting a URL in the media manager makes the asset appear in the grid; (b) the
picker's From URL tab fetches and selects the asset into an image element; (c) a rejected
URL shows the server's reason text in the picker flash — the one client behaviour §6 argues
hardest for, and otherwise untested; (d) a second click while a fetch is in flight issues no
second request.

**Two distinct e2e fixtures, not one.** Scenarios (a), (b) and (d) use the *accepted* URL
`{live_server.url}/static/core/img/learner.png` — an existing 17.9 KB PNG served by the live
server's staticfiles handler, so the fetch is genuinely end-to-end over a real socket while
remaining hermetic. Scenario (c) needs a URL the server *rejects*, which cannot be the same
one; it must be an **off-allow-list host** (e.g. `https://example.com/x.png`) so
`validate_fetch_url` fires before any socket opens. That requirement is the point: a
rejection fixture that needed a live round trip could reach the real network.

**`localhost` is the spelling that matters, and it is not obvious.** pytest-django resolves
the live-server address as
`config.getvalue("liveserver") or os.getenv("DJANGO_LIVE_TEST_SERVER_ADDRESS") or "localhost"`
(`pytest_django/fixtures.py:608-611`), and this repo sets neither, so `live_server.url` is
`http://localhost:<port>`. `validate_fetch_url` compares `urlsplit(url).hostname`, and
`"localhost"` neither equals nor is a subdomain of `"127.0.0.1"` — an allow-list containing
only the numeric address would reject every e2e before a socket opened. `127.0.0.1` is
listed as well so a future `--liveserver` override does not silently break them, and **the
tests must derive the host from `live_server.url` rather than hardcoding either spelling.**

The e2e should assert the fixture URL returns 200 before relying on it, so a
staticfiles-serving change fails loudly rather than as a confusing fetch rejection.

**Test-run mechanics for this repository:** the test-DB container must be started before
any run or the suite appears to hang; e2e requires `-m e2e` or every e2e test is
deselected; pytest's exit code can report 0 with failures present, so the summary line
must be read rather than the exit status trusted. Test runs must be scoped narrowly to the
affected tests — a whole-repo sweep is a branch-level gate, not a per-task step. This
worktree shares a machine with other active worktrees, so its test database must be
isolated via a `TEST_DATABASE_URL` prefix rather than by editing `.env`, and two pytest
runs must never execute concurrently.

## Deployment note

`DEADLINE_SECONDS = 20` is sized to stay under a conventional ~30 s worker timeout. **No
gunicorn/uwsgi/Procfile configuration exists in this repo today** — the only timeout in the
compose files is a 3 s healthcheck — so that figure is a target for a future deployment, not
a measured constraint of the current one. Recorded here so nobody later mistakes it for a
verified fact.
