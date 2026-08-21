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

Because the fetched image becomes an ordinary `MediaAsset`, the **asset pipeline** —
derivative generation, validation, and every consuming element — needs no change at all,
and all of those surfaces gain the feature at once. Two deliberate exceptions exist
downstream, both covered below: `_asset_cell.html` shows a provenance link, and
`replace_asset` must clear that provenance.

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
inherits a proven transport seam for tests, and keeps one convention in the codebase.

**`media_fetch.py` defines its own module-level `_NoRedirect` and `_open`** rather than
importing geogebra's private ones — following the reason `geogebra.py:252-259` already gives
for duplicating `_NoRedirect` instead of importing delivery's. Tests therefore patch
`courses.media_fetch._open`.

**No existing module is edited by this feature.** `integrations/delivery.py` and
`geogebra.py` are untouched, including their User-Agent constant (§2).

### 1. `validate_fetch_url()` — `courses/validators.py`

A deliberate twin of the existing `validate_embed_url` (`courses/validators.py:118`),
which guards video/iframe embeds.

**`validate_fetch_url` strips its own input**, and `fetch_image_asset` uses the stripped
value as `submitted_url` — so the stripped form is what is validated, fetched, and stored in
`source_url`. Stripping belongs to the validation authority, not the view: the view's own
`.strip()` is redundant convenience at most, and if the view were the only place it happened
the validator could never see whitespace, making the two whitespace unit tests below
unwritable and leaving `source_url` holding the unstripped value.

This is load-bearing rather than tidy-mindedness: a pasted URL routinely carries a leading
space or newline, and `urlsplit(" https://…")` yields an empty scheme, so an unstripped
value fails the scheme rule with "must use https" — exactly the misleading message rule 1
below exists to prevent. Whitespace-only input therefore tests as empty.

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
   **Both sides are lower-cased before comparison** — the parsed hostname and every
   allow-list entry — exactly as `validate_embed_url` does
   (`host = (parts.hostname or "").lower()`, `{d.lower() for d in …}`). Without it an
   operator writing `Upload.Wikimedia.org` in `.env` gets a silently unreachable entry.

Raises `ValidationError` on rejection. **All messages in this module and in
`media_fetch.py` use `gettext_lazy`**, deliberately diverging from `validate_embed_url`,
which raises bare English literals: §6 goes to real lengths to display these strings
verbatim to the author, so an untranslated literal would ship English into a Polish UI.
They are included in the `makemessages` pass.

**Interpolated messages raised on the worker thread must pass `params=`, never `%`.**
Django's active language is thread-local and `core.middleware.SessionLocaleMiddleware`
(`config/settings/base.py:48`) activates it on the *request* thread only, so the daemon
thread has no activation and falls back to `LANGUAGE_CODE = "en"`. The natural
`_("… %(mib)d …") % {...}` idiom — which `courses/validators.py:104` already uses — resolves
the lazy string *at raise time*, on the worker, in English. Worker-raised errors must
therefore be `ValidationError(lazy_msg, params={...})`, deferring interpolation until
`"; ".join(e.messages)` runs on the request thread under the author's language. This applies
to both interpolated worker messages: the status message and the "too large" message. A test
asserts a worker-side interpolated message renders translated under `activate("pl")`.

**Why an allow-list rather than an open fetch with SSRF guards.** Pinning the host to a
known-good set *before any packet leaves the process* eliminates the entire SSRF class:
link-local metadata endpoints, the Postgres container, internal admin pages, and DNS
rebinding all become unreachable rather than merely defended against. An open fetch would
require resolving the host, rejecting private/loopback/link-local/CGNAT ranges, and
re-checking after every redirect — materially more code, more risk, and a much larger
review surface.

**The allow-list is the only defence, so widening it is not risk-free.** There is no
IP-level guard behind it, and the match rule inherited from `validate_embed_url` accepts
**every** subdomain. An operator who adds a host whose subdomain tree is third-party
controlled — `s3.amazonaws.com`, `github.io`, `blogspot.com`, most CDNs — hands an attacker
a hostname whose DNS they control, pointing anywhere they like, including loopback and cloud
metadata endpoints. Entries must therefore be hosts whose **entire subdomain tree** is
trusted. This warning belongs both here and as a comment beside the `.env.example` line.

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

**The User-Agent is a module constant, not a setting, and it is reused rather than moved.**
`courses/geogebra.py:77` already defines
`_USER_AGENT = "libli/1.0 (+https://github.com/krzyssikora/libli)"` and argues explicitly
for a constant over a setting ("matching the pattern of `integrations/delivery.py`").
`media_fetch.py` therefore does **`from courses.geogebra import _USER_AGENT`**.

This is the decision, not one of two options. Lifting the literal into a new shared module
was considered and rejected: it would create a second new module, edit a file this feature
otherwise never touches, and require leaving a `_USER_AGENT` alias behind because
`tests/test_geogebra.py:437` imports that exact name. Importing a private name across
modules is the lesser cost, and the import direction is safe — `geogebra.py` imports nothing
from `courses`, so there is no cycle.

The header is **not optional**: Wikimedia's User-Agent policy requires a descriptive,
contactable UA and returns 403 to generic library user-agents, and Wikimedia is the entire
default allow-list.

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
fetch_image_asset(course, submitted_url, user, name="") -> MediaAsset
```

The parameter is named `submitted_url`, not `url`, for the reason the Naming paragraph
below gives.

Module constants, mirroring `geogebra.py`'s set:

```
MAX_REDIRECT_HOPS  = 3
TIMEOUT_SECONDS    = 8               # per socket op
DEADLINE_SECONDS   = 20              # total wall clock
CHUNK_BYTES        = 64 * 1024
MAX_PIXELS         = 50_000_000      # ~50 MP; see below
REDIRECT_STATUSES  = {301, 302, 303, 307, 308}
```

**`MAX_PIXELS = 50_000_000` is a real number with a rationale, not a placeholder.** It sits
*below* Pillow's own `Image.MAX_IMAGE_PIXELS` default (89,478,485), which is what makes the
check meaningful: Pillow only *raises* above 2 × its limit, so everything from `MAX_PIXELS`
up to 178 M would otherwise reach `generate_derivatives` and be decoded in full. 50 MP is
roughly 200 MB decoded at 4 bytes/pixel — already far beyond any legitimate teaching
illustration, and comfortably above the largest real photographs authors paste (a 100 MP
camera image is ~11,600 × 8,700 = 101 MP and is *not* something this feature needs to
accept).

**The constants are not independent.** `MAX_REDIRECT_HOPS`, `TIMEOUT_SECONDS` and
`DEADLINE_SECONDS` must satisfy the relationship recorded under "Redirect handling" below;
changing any one without re-checking it silently breaks the wall-clock bound.

**Every constant is read as a module global at call time** — never captured as a default
argument (`def fetch_image_asset(..., deadline=DEADLINE_SECONDS)`) and never re-exported via
`from courses.media_fetch import DEADLINE_SECONDS` in a helper. Both bind at import and
would silently defeat the deadline tests, which monkeypatch the module attribute: those
tests would then either run for the full 20 s or pass without exercising the path at all.
`geogebra.py` pins the same rule ("ONE read of the global, at call time").

**Naming (a warning, not a mandate).** Two values must stay distinct: the stripped value the
author pasted, and the hop currently being requested. Collapsing them into one `url`
variable is the natural way to write the redirect loop and it silently breaks the Data
section's guarantee that `source_url` stores the submitted URL, because
`url = urljoin(url, location)` would leave the final target in scope at `create_asset` time.
The spec calls them `submitted_url` and `current_url` for readability; the enforcement is
the named unit test asserting a redirected fetch persists the submitted URL, not the choice
of identifier.

#### Thread boundary — what runs where

**The daemon thread performs steps 4–8 only, and returns `(data, current_url)`.** Steps
9–13 — the empty-body guard, the Pillow verification, filename derivation, the digest, and
`create_asset` — run on the **request thread**, after the join. This split is mandatory in
both directions:

- `create_asset` performs a DB write and a storage write. On a background thread that is a
  second, never-closed connection outside the request's transaction, invisible to
  `pytest.mark.django_db` isolation and un-rolled-back on failure.
- `current_url` is worker-local, and filename derivation needs it (step 5 of Filename
  derivation). `geogebra.py`'s worker returns only `box["body"]`; copying that shape
  verbatim would lose the final hop and silently degrade the stem to `Special:FilePath` —
  the exact case that rule exists for.

**The result box contract**, following `geogebra.py:436-452`:

- The worker stores `box["exc"] = exc` **first**, then `exc.close()` (guarded, so a close
  failure can never mask the original).
- A private `_BudgetExceeded` signals worker-side budget exhaustion and **stores nothing**,
  so the caller's "no result" branch reports the deadline. Its `except` clause must precede
  the broad one, or a budget exception is captured as a generic failure.
- After `thread.join(DEADLINE_SECONDS)` the main thread takes **one** snapshot of the box.
  A stored `ValidationError` is re-raised **unchanged**; a box with neither result nor
  exception yields "Fetching the image took too long."

Without this, every `ValidationError` raised on the worker (redirect off the allow-list, bad
`Location`, hop budget, non-200, Content-Type gate, byte cap) is lost — an exception on a
`threading.Thread` target does not propagate to the joiner — and all six conditions would
report the deadline message instead.

**The worker's deadline instant** is `monotonic() + DEADLINE_SECONDS`, computed
**immediately before `start()`** and passed into the read loop, with `thread.join()` given
the same `DEADLINE_SECONDS` value so there is no clock skew — `geogebra.py:426-450` pins
this exactly. This matters because the daemon thread keeps running after the join returns;
the deadline instant is its own stopping rule.

#### Steps

1. `validate_fetch_url(submitted_url)`.
2. Read `effective_max_image_bytes()` and `effective_image_extensions()` **once** into
   locals. Both go through `_site_config()` → `get_site_config()` (a cache read, and a DB
   read on a miss); calling them inside the chunk loop or per candidate extension would
   re-evaluate them needlessly.
3. Start the daemon thread with the deadline instant above; join with `DEADLINE_SECONDS`.
   This is the *only* mechanism that bounds wall clock. A per-socket `timeout=` bounds each
   `connect`/`recv`, never the total call: a peer emitting one header byte every few seconds
   keeps every individual read inside the timeout and parks the worker indefinitely, which
   `geogebra.py:57-63` measured at 16.18 s against a 3 s timeout. This makes the repo's
   **second** production background thread — a deliberate choice, taken because the
   alternative is an unbounded worker.

*Steps 4–8 run on the worker.*

4. Issue a `GET` via a `_NoRedirect` opener (the class at `courses/geogebra.py:251` and
   `integrations/delivery.py:23`; `_open` at `geogebra.py:272` is the seam), with
   `timeout=TIMEOUT_SECONDS` and headers `User-Agent: <shared constant>` and
   `Accept: image/*`. The `Accept` header costs nothing and improves the odds a
   content-negotiating host returns the image rather than an HTML page — the
   `commons.wikimedia.org` case below is exactly a negotiation-shaped failure.

5. **Redirects and non-200s arrive as raised `HTTPError`, not as returned responses.**
   This is the single most important control-flow fact in this module and it is easy to get
   wrong. `build_opener` keeps `HTTPErrorProcessor`, so 4xx/5xx raise
   (`integrations/delivery.py:29-31` says so verbatim), and both existing `_NoRedirect`
   handlers **raise** `HTTPError` rather than returning `None`
   (`geogebra.py:262-267`: "it RAISES, it does not return None"). `opener.open()` therefore
   returns **only** a 2xx response.

   The handler shape is consequently:

   ```
   try:
       with _open(req, TIMEOUT_SECONDS) as resp:
           ...            # 2xx only: steps 7-8
   except urllib.error.HTTPError as exc:
       ...                # 3xx and non-2xx: inspect exc.code / exc.headers, then exc.close()
   except (TimeoutError, urllib.error.URLError, OSError):
       ...                # genuine transport failure
   ```

   The call goes through the module's own `_open` seam (§0), never a locally built opener —
   that seam is what every unit test patches, so an inline `opener.open(...)` would make the
   entire unit suite unrunnable. Status is read as **`exc.code`**, matching both sibling
   modules (`geogebra.py:475`, `integrations/delivery.py:143`); `.status` is equivalent on
   3.13 but a lightweight test double written from those examples sets only `.code`.

   **The clause order is mandatory, not stylistic:** `HTTPError` is a subclass of
   `URLError`, so a `URLError` clause placed first swallows every redirect and every status
   error, and the five enumerated redirect/status messages become unreachable — the whole
   feature would report "Could not reach the image host." for a 404.

   Inside the `HTTPError` handler:
   - `exc.code in REDIRECT_STATUSES` → redirect handling (below);
   - anything else → "The image host returned an error (status %(status)s)."

   **A returned 2xx is not automatically a 200, and the difference must be checked
   explicitly.** `HTTPErrorProcessor.http_response` raises only when
   `not (200 <= code < 300)`, so **204 and 206 return normally through the `with` block**.
   The returned response is therefore rejected with the same status message unless
   `resp.status == 200`. Without that check a 206 would be accepted as a complete image
   (partial bytes, plausible header, and `verify()` passes for JPEG), and a 204 would fall
   through to the empty-body guard and report the wrong reason. A named unit test covers
   206.

6. **Redirect handling.** For a redirect `HTTPError`:
   - a missing or empty `Location` header → "The image host returned an invalid redirect.";
   - `Location` is resolved against `current_url` with `urljoin`, then re-validated;
   - every hop re-issues `GET` with the same headers and timeout, regardless of whether the
     status was 303 or 307/308;
   - **the budget is checked at the top of every iteration**, before the next hop is issued:
     `monotonic() >= deadline` raises `_BudgetExceeded`. Without this the deadline is only
     consulted inside the byte-read loop, and four requests (one initial plus three hops)
     each allowed `TIMEOUT_SECONDS` on connect alone can burn
     `(MAX_REDIRECT_HOPS + 1) × TIMEOUT_SECONDS` = **32 s** against a 20 s budget — with the
     daemon thread still opening sockets to a hostile host long after the author has been
     told it took too long. This is the constant relationship referred to above: whenever
     `(MAX_REDIRECT_HOPS + 1) × TIMEOUT_SECONDS > DEADLINE_SECONDS`, the per-iteration check
     is the only thing holding the bound.

   **The hop boundary is exact: one initial GET plus at most `MAX_REDIRECT_HOPS` followed
   redirects — four requests in total.** A chain of exactly three redirects therefore
   *succeeds*; a fourth redirect status raises "That URL redirects too many times." A
   redirect status arriving when the budget is exhausted reports *that*, never the not-200
   message. The unit test asserts **both** sides of that boundary, so the off-by-one cannot
   be settled by whichever way the implementation happened to go.

   **The re-validation's own messages are caught and replaced.** `validate_fetch_url` has
   five rules, and a redirect target can trip any of them: a downgrade to `http://` would
   otherwise tell the author "Image URLs must use https.", an over-long `Location` "That URL
   is too long", a malformed one "That does not look like a valid URL" — each of which is a
   false statement about the URL the author actually typed. So the redirect path catches
   `ValidationError` from the re-validation and re-raises the single redirect-specific
   message, "That URL redirects to a host that is not on the allow-list." The
   http-downgrade redirect is a named unit test.

7. **Content-Type is a cheap pre-read gate.** Take the response's `Content-Type`, strip
   parameters at the first `;`, trim, case-fold, and reject anything that is not a key of
   the media-type map → "That URL did not return an image." An **absent or empty**
   `Content-Type` takes this same branch (it is not a key), and is rejected rather than
   deferred to Pillow — stated explicitly so nobody implements "unknown, let Pillow decide".
   This is checked before the body is read so an HTML page is abandoned early. It is a gate,
   not the authority on the extension — see step 11.

8. **Byte cap, read with `read1`.** Loop `resp.read1(CHUNK_BYTES)`, accumulating, checking
   the deadline instant once per chunk, and reject as soon as the total exceeds the cap from
   step 2 → the existing "Image file too large (max %(mib)d MiB)." wording. `read1`, not
   `read`, is mandatory and is the reason the per-chunk deadline check can fire at all:
   `read(n)` loops over `recv` until it has n bytes, so on a drip body it never returns. A
   declared `Content-Length` above the cap is an early reject purely to avoid pointless
   transfer — **advisory only**: absent, non-numeric, negative or duplicated headers are
   ignored, never a rejection and never a reason to relax the streaming check. The loop
   deliberately reads one chunk *past* the cap so oversize stays detectable, per
   `geogebra.py`'s comment on the same loop. The worker returns `(data, current_url)`.

*Steps 9–13 run on the request thread, after the join.*

9. **Reject an empty body** → "The fetched file is empty.", mirroring `replace_asset`'s
   existing check (`courses/media.py:185`). Nothing downstream covers this: `media_upload`
   inherits its empty-file rejection from `MediaAssetForm`'s `forms.FileField`, which this
   path bypasses, and `MediaAsset.clean()` has no lower size bound. Without the guard a 200
   with `Content-Length: 0` creates a real asset with zero bytes, failed derivatives, and a
   200 response.

10. **Verify the payload really is an image; capture its format and size.** The order is
    pinned: `Image.open(BytesIO(data))` → keep `img.format` and `img.size` → **pixel-count
    check** → `verify()`. On failure reject with "That URL did not return a usable image."

    The pixel check runs **before** `verify()`, not after. `PngImageFile.verify()` walks the
    remaining chunks and checks CRCs, so the natural fixture for the pixel test — a PNG
    whose IHDR declares huge dimensions over a short synthetic body — would be rejected as
    "not a usable image" and the named test would fail on a *correct* build. Checking first
    also avoids doing verify work on a bomb.

    **What `Image.open`/`verify()` do and do not catch.** `Image.open`'s header sniff is the
    real format authority; `Image.verify()` is a no-op on the base class and is overridden by
    only a few plugins, notably PNG. A **truncated** JPEG/MPO/GIF/WEBP therefore passes both,
    is stored, and fails later inside `generate_derivatives`, which swallows the failure and
    records `DerivativesState.FAILED`. That is knowingly accepted — do not write a
    truncation-rejection test, because there is no truncation rejection.

    **`DecompressionBombError` is caught in its own clause, placed before the broad one**,
    and mapped to the *dimensions* message, not the not-a-usable-image one. Pillow raises it
    from `Image.open` above 2 × `Image.MAX_IMAGE_PIXELS`, i.e. before the explicit `img.size`
    check below can run — so without a dedicated clause an enormous image is told it is "not
    a usable image" while a merely large one is correctly told its dimensions are too large,
    and the two sides of that boundary disagree about what went wrong. The clause must
    precede the broad one for the same reason `_BudgetExceeded`'s does.

    Everything else is a **broad `except Exception`**, in the style of `geogebra.py`'s
    documented broad catches. A narrow `except UnidentifiedImageError` is a real 500:
    `Image.open` also raises `OSError`, `ValueError` and `SyntaxError` from individual
    plugins. Since the view catches only `ValidationError` (`courses/views_media.py:47`),
    anything not converted here is a 500, not a 422.

    **An explicit pixel bound is required, because Pillow's is not enough.** Pillow raises
    `DecompressionBombError` only above **2 ×** `Image.MAX_IMAGE_PIXELS` (2 × 89,478,485);
    below that it merely warns and proceeds, and `verify()` does not decode pixel data. An
    image in that gap would pass here, be stored, and then be fully decoded by
    `generate_derivatives`, which allocates the whole canvas. The byte cap does not bound
    pixel count — that is the entire point of a decompression bomb. So: check
    `img.size[0] * img.size[1]` against `MAX_PIXELS` here and reject with its own message,
    "That image's dimensions are too large."

    The bomb unit test must target the band **this new code is responsible for** —
    `MAX_PIXELS` (50 M) < declared pixels < 2 × `Image.MAX_IMAGE_PIXELS` (178.9 M) — not the
    >2× case, which Pillow refuses unaided and which would therefore pass on a build with no
    pixel bound at all.

    Step 7's own argument compels the whole of this step: *nothing downstream ever looks at
    the bytes* — `_validate_file` checks extension and size only, and `generate_derivatives`
    swallows its failure — so a mislabelling host would otherwise produce exactly the silent
    broken-asset outcome step 7 exists to prevent.

11. Derive a filename (see below), using `img.format` and `current_url`.
12. Compute the digest as **`hashlib.sha256(data).hexdigest()`** — byte-for-byte the same
    expression as `courses/lal_loader/media.py:31`, lowercase hex over the raw file bytes.
    The exact form is load-bearing, not incidental: any other encoding (uppercase, base64,
    `digest()`, or hashing the `ContentFile` after a read) produces a value that can never
    collide with a LAL digest, which would silently make the whole "Interaction with the
    existing LAL dedup" section dead — and a test that builds both sides through one shared
    helper would still pass.
13. Wrap as `ContentFile(data, name=filename)` and call
    `create_asset(course, "image", content_file, user, name=name,
    source_url=submitted_url, content_hash=digest)`. The derived filename must be the
    wrapper's `.name`, not a separate argument: `create_asset` reads
    `truncate_filename(uploaded_file.name)` for `original_filename` **only** — the storage
    path is built by Django from the raw `ContentFile.name`, which is exactly why Filename
    derivation step 6 truncates *before* wrapping rather than relying on `create_asset` to
    do it. A nameless `ContentFile` yields an empty `original_filename`. The wrapper must
    also be an **uncommitted** file object — a committed `FieldFile` makes `_validate_file`
    short-circuit and skip both the extension and the size check, the trap `replace_asset`'s
    docstring already documents.

**Response lifetime — two acquisition paths, not four sites.** Only a 2xx response is ever
returned and bound by `with _open(...) as resp:`. Every 3xx and non-2xx arrives as an
`HTTPError`, which never enters that `with` block, so **its `fp` must be closed explicitly
in the handler** — `exc.close()`, guarded so a close failure never masks the original.
`geogebra.py:453-458` documents precisely this: "A 4xx/5xx raises from inside `_open` ON THE
WORKER, so the `with` inside `_fetch_body` is never entered and the error's own fp is never
closed." The redirect loop is one code site executed up to `MAX_REDIRECT_HOPS + 1` times,
and each iteration's `HTTPError` needs that close.

**Transport failures.** Both the request *and the read loop* are wrapped in
`except (TimeoutError, urllib.error.URLError, OSError)` — the set
`integrations/delivery.py:67` uses, widened to `OSError` for mid-read socket failures —
and converted to a `ValidationError` reading "Could not reach the image host." This clause
comes **after** the `HTTPError` clause (see step 5). Wrapping only the `open()` call is not
enough: a DNS failure raises there, but a truncated body raises from inside the read loop,
after the `with` block has been entered.

**Logging.** Every rejection point **inside `media_fetch.py`** emits a `logger.warning`
naming the host, the status or Content-Type, and a reason token — never the response body —
on `logging.getLogger(__name__)` in that module, matching `geogebra.py:55`.
**`validate_fetch_url` does not log**: it lives in `courses/validators.py`, is a pure
validator that other callers may reuse, and its five rejections are all decided from the
submitted string before any network access, so they carry no diagnostic value an operator
could not read off the request itself. The author-facing message is deliberately
detail-free, so without the `media_fetch` logging an operator diagnosing "an allow-listed
host started 403-ing our User-Agent" would have nothing to work from.

**`S310` (bandit, `urllib.request` audit) is satisfied with a written justification
comment**, in the same form `geogebra.py` and `integrations/delivery.py` already use — the
scheme is constrained to http/https by `validate_fetch_url` before any request is built.
It is never silenced with a bare `noqa`.

#### Filename derivation

The **sniffed format decides the extension**; the URL path contributes only a
human-friendly stem.

Media-type map (the step 7 gate), media type → candidate extensions in preference order:

```
image/png  → ("png",)
image/jpeg → ("jpg", "jpeg")
image/jpg  → ("jpg", "jpeg")      # non-standard but widely emitted
image/gif  → ("gif",)
image/webp → ("webp",)
```

**SVG is deliberately excluded, and says so.** `image/svg+xml` is not in the map because
`SAFE_IMAGE_EXTENSIONS` does not include `svg` — SVG is an active-content format the upload
path refuses too. But Wikimedia serves a large share of its illustrations as SVG and is the
entire default allow-list, so an author *will* paste one, and telling them the URL "did not
return an image" is both false and points them at the wrong thing. `image/svg+xml`
therefore gets an explicit case in the gate that raises **"That image type is not
allowed."** — the honest message — rather than falling through to the not-an-image branch.

Pillow-format map, `img.format` → the same candidate lists:

```
PNG → ("png",)      JPEG → ("jpg", "jpeg")      MPO → ("jpg", "jpeg")
GIF → ("gif",)      WEBP → ("webp",)
```

`MPO` is listed because it is a **normal** outcome for an accepted `image/jpeg`: Pillow
reports `MPO`, not `JPEG`, for multi-picture JPEGs, which is what most phone cameras produce
and a substantial share of real-world web JPEGs.

1. **The extension is chosen from `img.format` (step 10), not from `Content-Type`.** The
   header is only the pre-read gate. This is step 7's own argument applied one level
   further: a host serving GIF bytes under `Content-Type: image/png` passes the header gate
   *and* `verify()` — the bytes are a decodable image — and would be stored as `foo.png`
   containing a GIF, which `full_clean()` (extension only) would never notice. `img.format`
   is populated before `verify()` and survives it, is free, and is strictly more
   trustworthy than a remote header.
2. **An `img.format` absent from the Pillow map is a `ValidationError`, never a `KeyError`.**
   `BMP`, `TIFF`, `ICO` and others are reachable whenever a host mislabels its payload —
   the very scenario step 1 exists to catch — and a bare `MAP[img.format]` lookup would be
   a 500, since the view catches only `ValidationError`. The message is "That image type is
   not allowed.", and the unknown-format branch is a named unit test.
3. The extension is the **first candidate for that format present in
   `effective_image_extensions()`** (read once at step 2). Never a hardcoded literal: an
   admin may narrow the allowed set to `["jpeg"]` alone, in which case a fixed `jpg` would
   build a filename `full_clean()` then rejects for an image the server was configured to
   accept. If no candidate is allowed → "That image type is not allowed."
4. **The stem is sanitized, and the order of operations matters.** URL-unquote the path
   *first*, then take the basename, **then drop a trailing extension when (case-folded) it
   is one of the known image extensions**, then strip path separators, `..` segments,
   control characters and leading dots; if nothing usable survives, use the literal `image`.

   Dropping the existing extension is not optional and is easy to lose: without it the
   spec's own headline example, `…/Foo.jpg`, yields the stem `Foo.jpg` and stores
   `Foo.jpg.jpg`. No loose "ends with `.gif`" assertion can detect that, which is why the
   format tests below assert **exact filename equality**.
   Unquoting *after* the basename is a real defect, not a style point: a path ending
   `..%2F..%2Fx.png` has the basename `..%2F..%2Fx.png`, which unquotes to `../../x.png`,
   lands in `ContentFile.name`, and makes Django's `Storage.generate_filename` raise
   `SuspiciousFileOperation` — a 500, since only `ValidationError` is caught.
5. **The stem comes from `current_url`** — the final hop — not `submitted_url`. This is the
   one place the final target is the better source:
   `https://commons.wikimedia.org/wiki/Special:FilePath/Foo.jpg` redirects to an
   `upload.wikimedia.org` path whose basename is the useful one, while the submitted path's
   basename is `Special:FilePath`. `source_url` still stores `submitted_url` (Data).
6. The filename is `<stem>.<extension>`, passed through the existing `truncate_filename`
   (`courses/media.py:96`), which truncates while preserving the extension.

Two comparisons are case-folded, and neither is a path-extension match (the path no longer
decides the extension at all): the `img.format` map lookup, and the membership test of each
candidate against `effective_image_extensions()`, which returns lowercase
(`courses/validators.py:60`). The trailing-extension strip in step 4 is likewise
case-folded, so a `…/Foo.JPG` path yields the stem `Foo`.

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
`AttributeError` at call time rather than at import.

The view is gated by the existing `_require_manage(request, slug)` exactly as every other
media view is. It reads `url` (stripped, per §1) and optional `name` from `request.POST`,
calls `fetch_image_asset`. Its **fragment** behaviour mirrors `media_upload` exactly; its
**non-fragment failure** path deliberately *improves* on it. `media_upload` redirects
silently with no message at all, so an implementer "matching the sibling" would drop the
`messages.error` call — the divergence is intentional, and its precedent is
`courses/views_transfer.py:49`.

- **fragment request, success** → render `courses/manage/media/_asset_cell.html` after
  `media_svc.attach_usage(asset)`, status 200;
- **fragment request, failure** → render `courses/manage/_op_error.html` with the message,
  status 422;
- **non-fragment request** (no JS) → `messages.error(request, <message>)` on failure, then
  `redirect("courses:manage_media", slug=course.slug)` in both cases. The messages
  framework is installed and already used this way in `courses/views_transfer.py:49`.

**The message is `"; ".join(e.messages)`**, not `str(e)` — the convention every sibling view
already uses (`courses/views_media.py`, `views_manage.py:799`). `create_asset`'s
`full_clean()` raises a `ValidationError` carrying an `error_dict`, so `str(e)` would put a
Python repr of a list or dict on the page — and §6 now displays that string verbatim in the
picker flash, making the defect user-visible rather than cosmetic.

The route is registered as `manage_media_fetch` at
`manage/courses/<slug:slug>/media/fetch/`, beside `manage_media_upload`
(`courses/urls.py:279`).

### 5. Templates

- **`templates/courses/manage/media/manager.html`** — a second small form next to the
  existing upload form, pinned in full because every attribute here is load-bearing on the
  no-JS path and nothing else would catch a missing one (Django's test client does not
  enforce CSRF by default, and the e2e drives the JS path):

  ```
  <form class="media-fetch" method="post"
        action="{% url 'courses:manage_media_fetch' slug=course.slug %}">
    {% csrf_token %}
    <input type="url" name="url" required placeholder="https://…">
    <input type="text" name="name">
    <button type="submit" data-fetch-submit>…</button>
  </form>
  ```

  Without `method="post"` and `action`, the form issues a GET to `manage_media` and the
  no-JS path never reaches the view at all — the same class of silent break as a missing
  `{% csrf_token %}`. `name="name"` is pinned so the no-JS form submits under the key the
  view reads; the view itself uses `(request.POST.get("name") or "").strip()`, as
  `media_upload` does — **never bracket access**, which would raise
  `MultiValueDictKeyError` (uncaught, hence a 500) on every picker fetch, since the picker
  deliberately sends no name at all. `[data-fetch-submit]` is pinned because §6's in-flight
  guard and e2e scenario (d) need a stable selector. A template assertion checks the form's
  `action` resolves to the fetch route.

  Both inputs are wrapped in the same `<label class="field">` convention the adjacent
  `.media-upload` form uses for all three of its controls — `{% trans "Image URL" %}` and
  `{% trans "Name" %} <span class="muted">({% trans "optional" %})</span>`. Without them the
  new form ships two unlabelled controls directly beside three labelled ones: an
  accessibility regression and a visible inconsistency, in a repo whose standing rule is
  that every view ships styled. The labels are part of what the light/dark screenshot
  verification checks.

  `type="url"` + `required` is the deliberate choice: the browser blocks an empty or
  obviously malformed submit, saving a round trip. The server-side empty check is **not**
  thereby dead — it stays reachable from the picker (whose input is not inside a form, so
  no native validation applies) and from any non-browser client, and that is where its test
  lives.

  The endpoint is exposed to JS as `data-fetch-url` on the `.media-manager` root, mirroring
  the existing `data-upload-url` (`root.dataset.uploadUrl`). **`.media-manager` also gains
  `data-msg-fetch-failed="{% trans '…' %}"`**, the translatable fallback §6 requires, with a
  Polish string supplied.

- **`templates/courses/manage/media/_picker.html`** — a third tab and panel, "From URL",
  **rendered only under `{% if kind == "image" %}`**. This condition is required, not
  cosmetic: the picker is kind-generic (`<div class="picker" data-kind="{{ kind }}">`) and
  is opened for `VideoElement` too. An unconditional tab would offer a URL fetch in the
  video picker that creates an *image* asset and then selects it into a video field, where
  `_CourseScopedMediaForm` filters the queryset to `kind="video"` and rejects it — after
  the asset has already been created.

  **The new panel carries `hidden` and its tab does not carry `is-on`**, matching the
  existing panels (`_picker.html:6-20`, where only the library tab is `is-on` and every
  other panel is `hidden`). A panel rendered without `hidden` stacks on top of the library
  panel until the first tab click. **The `data-tab`/`data-panel` pair must match** — pin
  both to `"fetch"`. The delegated handler switches panels via
  `p.hidden = p.getAttribute("data-panel") !== tab.getAttribute("data-tab")`, so a mismatched
  or omitted pair hides *every* panel on the first tab click; the template test asserts each
  tab's `data-tab` has a corresponding `data-panel`.

  **Panel contents and activation, stated explicitly** because the picker is not a form
  context: the overlay is appended to `document.body` (`media_picker.js:92`), so it has no
  `<form>` ancestor, no implicit submission exists, and every in-panel control is driven by
  the delegated `document` click handler at `media_picker.js:126`. The panel contains a
  single `<input type="url" data-picker-url>` (no `required` — there is no form to validate
  it) and a button `[data-picker-fetch]` — **no name field**; `fetchPickerUrl(url)` is
  always called without a name, and an author who wants one renames the asset in the
  manager. Activation is (a) a new branch in the existing delegated `document` click handler
  keyed on `[data-picker-fetch]`, and (b) an explicit `keydown`/Enter handler on
  `[data-picker-url]`, mirroring how `[data-picker-search]` is wired for input events.
  Without (b), Enter in that input is silently dead.

  The endpoint is exposed as `data-fetch-url` on `.picker`, mirroring `data-upload-url`.
  **`.picker` also gains `data-msg-fetch-failed="{% trans '…' %}"`.** Note this template
  currently carries *no* `data-msg-*` attribute at all (only `data-upload-url` and
  `data-search-url`), so this is a new class of attribute here, not an addition to an
  existing block.

- **`templates/courses/manage/media/_asset_cell.html`** — when **`asset.source_host`** is
  truthy (not `source_url` — see below), show a small source link in the **`.asset-foot`**
  region (beside the usage details),
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
  return `""`**: `urlsplit(...).hostname` raises on a malformed authority, and this runs for
  every asset in the manager grid, so one bad row would otherwise 500 the whole page.
  `courses/geogebra.py`'s `geogebra_material_id` wraps the same call in
  `try/except (ValueError, TypeError, IndexError)` for this reason.

  **Gating on `source_host` rather than `source_url` is what makes that fallback coherent:**
  a row whose `source_url` is set but whose authority is malformed has a truthy `source_url`
  and an empty `source_host`, so gating on the former would render an anchor with no visible
  label — a zero-width, unlabelled link. A template test asserts such a row renders no link
  at all.

All new user-facing template strings go through `{% trans %}`; the Python-side messages use
`gettext_lazy` (§1). Both are covered by one `makemessages` pass with Polish translations
supplied. Expect the extraction to also sweep in msgids left unextracted by earlier work.

**Styling.** New CSS goes in `courses/static/courses/css/editor.css`, which already
carries `.media-upload` (`editor.css:343`) and the `.picker__*` family. The manager form
gets a `.media-fetch` class styled consistently with its `.media-upload` sibling; the new
picker panel reuses `.picker__panel`; the cell link gets `.asset-source`. This repo's
standing rule is that every view ships styled, so all three surfaces require light **and**
dark screenshot verification, judged separately.

### 6. Client — `courses/static/courses/js/media_picker.js`

**Picker.** One new function, `fetchPickerUrl(url)`, mirroring `uploadPickerFile`
(`media_picker.js:148`): POST to `data-fetch-url` with `X-CSRFToken: csrf()` and
`X-Requested-With: fetch` like every other POST in this file, and on a 200 parse the
returned cell fragment and call the existing `selectAsset` with its
`data-asset-id`/`data-name`/`data-url`. `selectAsset` itself is unchanged.

**Manager.** The existing form-interception path is **not** generic and cannot simply be
"extended": `media_picker.js:276-288` binds one listener to `root.querySelector(".media-upload")`,
early-returns unless a `input[type='file']` has files, and calls `uploadFile()` with a
`FormData` carrying `file` and `kind` — none of which applies here. Instead, add a **second
`submit` listener on `.media-fetch`** that always `preventDefault()`s, POSTs `url` and
`name` to `root.dataset.fetchUrl` with the standard headers, reuses the existing
`insertCell()` on 200 **and calls `form.reset()`**, and on a non-200 applies the **same**
fragment-parse-then-flash treatment specified for the picker below.

`form.reset()` matters for the same reason the in-flight guard does: the upload path it
mirrors resets on success (`media_picker.js:281`), and without it the URL stays in the box
after the cell appears, so one more click creates a duplicate asset — URL-level dedup being
an explicit non-goal.

**In-flight state is required, not a nicety.** The fetch can legitimately take up to
`DEADLINE_SECONDS` (20 s) with no visual change. The delegated click handler has no guard,
so an author who clicks twice — the near-certain response to a dead-looking button — issues
two POSTs, and since URL-level dedup is an explicit non-goal, both succeed and two identical
assets are created (in the picker, the second `selectAsset` also overwrites the first). The
upload path is not a precedent: a file-picker dialog interposes a natural gate that a
paste-and-click does not.

**The guard is a JS in-flight flag consulted inside `fetchPickerUrl`, not merely a
`disabled` button.** Disabling the control is the *visible* expression of the flag, not the
mechanism. This matters because §5 deliberately gives the picker a **second** activation
route — Enter on `[data-picker-url]` — which never goes through the button at all, so a
DOM-state-only guard lets two Enter presses issue two POSTs and create two duplicate assets,
exactly the harm this paragraph exists to prevent. One flag checked at the top of
`fetchPickerUrl` gates both routes. (The manager form is unaffected either way: HTML
implicit submission fires a click at the default button, and a disabled default button
suppresses it — but it uses the same flag for consistency.) So: set the flag, disable
`[data-picker-fetch]` / the manager's `[data-fetch-submit]`, and set `aria-busy`.

**Re-enable on all *three* outcomes.** Success and failure are the two arms inside
`.then()`, and the model — `uploadPickerFile` (`media_picker.js:158-168`) — has no
`.catch()` at all. A network drop, a page-level abort, or an unparseable response rejects
the promise, neither arm runs, and the control stays disabled and `aria-busy` for the life
of the page with no message shown. That is the likeliest real-world path for a 20-second
request. A `.catch()` (or `finally`-equivalent) must both re-enable the control and flash
the `data-msg-fetch-failed` fallback.

**On a non-200 the server's reason is shown, not discarded.** `uploadPickerFile` currently
calls `flash(card, "Upload failed.")` (`media_picker.js:162`) — a hardcoded English literal
that throws the response body away, which would make every rejection reason this spec
enumerates invisible.

The mechanism must be precise, because the response is markup, not a string:
`_op_error.html` renders `<div class="op-error" role="alert">Couldn't apply that change:
{{ message }}</div>`, while `flash(host, msg)` sets `bar.textContent = msg`
(`media_picker.js:6`). Passing the raw text to `flash()` would display the tags literally;
passing it as `innerHTML` would nest an `.op-error` with a second `role="alert"` inside the
flash's own. So: **parse the returned fragment**, read the `.op-error` element's
`textContent`, and pass that string to `flash()`. The "Couldn't apply that change:" prefix
is kept verbatim — it is what the manager surface already shows for every other operation.

The fallback string, used only when the body is empty or unparseable, comes from a
`data-msg-fetch-failed` attribute read via the existing `msg(host, key, fallback)` helper
(`media_picker.js:240`) rather than a JS literal, so it is translatable. **The host element
differs per surface and must be named:** on the manager it is `.media-manager` (where every
existing `data-msg-*` attribute lives); in the picker, `msg()` must be called against the
`.picker` element, **not** the picker path's `root`, which is
`document.querySelector(".editor")` (`media_picker.js:20`) and carries no such attributes.
Getting this wrong is invisible at runtime, which is why the attribute's presence is
asserted by a test.

**The flash host is a third element again, and deliberately differs from the `msg()` host.**
`uploadPickerFile` flashes into `overlay.querySelector(".picker-card")`
(`media_picker.js:161`) — neither `.picker` nor `root` — and the fetch path must use that
same host, or e2e scenario (c) finds the bar somewhere the existing UI never puts it. So:
flash host `overlay.querySelector(".picker-card")`, `msg()` host
`overlay.querySelector(".picker")`. **On the manager the two coincide** — both are
`.media-manager`, matching the existing `flash(root, …)` at `media_picker.js:285` — which is
stated rather than left to be inferred from the coincidence.

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
instead of creating a second copy of the same bytes. That is the correct outcome, but it is
a real behaviour change and must be covered by a test rather than discovered later.

**One caveat on that queryset:** `.first()` runs on an unordered queryset, and because
URL-level dedup is a non-goal, the same URL fetched twice produces two rows with identical
`content_hash` in one course — in which case *which* row a later import inherits `name` and
`source_url` from is DB-order-dependent. The test must therefore construct exactly **one**
fetched asset, so it is not silently asserting on an unordered `.first()`.

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

**Happy path.** Author pastes a URL → POST to `manage_media_fetch` → `_require_manage`
authorises → `validate_fetch_url` accepts the stripped URL → a daemon thread joined with a
20 s budget runs the transport: GET with the shared User-Agent and `Accept: image/*`, ≤3
validated redirect hops (each arriving as an `HTTPError`), Content-Type gate, body read with
`read1` under the byte cap; it returns `(data, current_url)` → on the request thread the
body is checked non-empty, verified by Pillow with its format and pixel count captured, a
filename derived from that format, and a digest computed → `create_asset` runs `full_clean()`
and generates derivatives → `attach_usage` → `_asset_cell.html` at 200 → the client inserts
the cell in the manager, or selects the asset in the picker.

**Rejection path.** Any failure raises `ValidationError`; worker-side ones travel back via
`box["exc"]` and are re-raised unchanged. On a fragment request the view converts it to
`_op_error.html` at 422; on a non-fragment request it becomes a `messages.error` plus a
redirect.

## Error handling

Every condition is a `ValidationError` carrying the message below (all `gettext_lazy`).
**On a fragment request each returns 422**; on a no-JS request each becomes a
`messages.error` followed by a redirect (§4). Pinning the exact text here makes this the
single source for the implementation, the view tests, and the `.po` entries — the picker
shows these strings verbatim.

| Condition | Message | Detected by |
|---|---|---|
| `url` missing, empty, or whitespace-only | "Enter an image URL." | `validate_fetch_url` |
| URL longer than 500 characters | "That URL is too long (maximum 500 characters)." | `validate_fetch_url` |
| URL malformed | "That does not look like a valid URL." | `URLValidator` |
| Scheme not https (and http not permitted) | "Image URLs must use https." | `validate_fetch_url` |
| Host not on the allow-list | "That image host is not on the allow-list." | `validate_fetch_url` |
| Redirect with missing/empty `Location` | "The image host returned an invalid redirect." | redirect handling |
| Redirect target fails re-validation, for any of the five rules | "That URL redirects to a host that is not on the allow-list." | redirect handling (underlying message replaced) |
| More than 3 redirect hops | "That URL redirects too many times." | hop budget |
| Connection failure, timeout, or mid-read error | "Could not reach the image host." | `URLError`/`OSError`, after the `HTTPError` clause |
| Wall-clock deadline exceeded | "Fetching the image took too long." | thread join, empty box |
| Status is not 200 | "The image host returned an error (status %(status)s)." | `HTTPError` for non-2xx; an explicit `resp.status != 200` check for a returned 204/206 |
| `Content-Type` absent, empty, or not a known image type | "That URL did not return an image." | media-type gate |
| `img.format` unknown, or no allowed extension for it | "That image type is not allowed." | filename derivation |
| Body exceeds the cap (authoritative) | "Image file too large (max %(mib)d MiB)." | `read1` accumulator |
| Body is empty (zero bytes) | "The fetched file is empty." | empty-body guard |
| Bytes are not a decodable image | "That URL did not return a usable image." | Pillow, broad catch |
| Pixel count exceeds `MAX_PIXELS` | "That image's dimensions are too large." | `img.size` check |
| Extension or size rejected | (existing validator messages) | `create_asset`'s `full_clean()` |

A declared over-cap `Content-Length` uses the same "too large" message as the streaming
check; it is an early exit, not a distinct condition.

**The remote response body must never reach the user-facing message.** Error text is
composed by this application. Diagnostic detail goes to the log (§3), never to the author.

## Testing

TDD throughout. Per this repository's standing practice, **every new test must be
falsified against a deliberate mutant that proves it goes RED**, with the mutant chosen
from the failure mode the test claims to detect — a test that passes on a broken build
proves nothing, and this codebase has repeatedly shipped assertions that could not fail.

**The transport seam is `_open(request, timeout)`**, mirroring `geogebra.py:272` ("The
transport seam. Patched by tests; the only place the network is touched"). Unit tests patch
it; no unit test touches a real socket. **Doubles must raise `HTTPError` for 3xx and non-2xx
statuses**, not return a response object — a double that returns them tests a control flow
the real opener never produces.

**Unit — `validate_fetch_url`:** empty rejected with its own message; whitespace-only the
same; a whitespace-padded valid URL accepted, and the stripped value used; over-length
rejected; malformed rejected by `URLValidator`; an http URL rejected when
`ALLOW_HTTP_IMAGE_FETCH` is false; an allow-listed host accepted; a subdomain accepted; a
look-alike host that merely *ends with* the allowed string rejected; a mixed-case allow-list
entry still matches.

**`override_settings` covers both new settings, not just the host list.** `test.py` replaces
`ALLOWED_IMAGE_FETCH_DOMAINS` (§2), so hosts must be named per test — and it also sets
`ALLOW_HTTP_IMAGE_FETCH = True` for the whole suite, so the **http-rejection test and the
http-downgrade-redirect test must each set it `False` explicitly**. Without that the
downgrade test takes the *accepted* path and passes for entirely the wrong reason.

**Unit — settings default:** `config/settings/base.py` leaves `ALLOW_HTTP_IMAGE_FETCH`
false. **The mechanism must be environment-independent**, and the spec pins it rather than
leaving it open: the suite runs under `config.settings.test`, which sets the flag `True`, so
the test has to reach `base` some other way — and any plain import re-reads
`env.bool("LIBLI_ALLOW_HTTP_IMAGE_FETCH", default=False)`, failing for any developer who has
that variable exported or in `.env`. So: `monkeypatch.delenv("LIBLI_ALLOW_HTTP_IMAGE_FETCH",
raising=False)`, then reload `config.settings.base` and assert the resulting value, so the
test asserts the *declared default* rather than the ambient environment.

**Unit — the language of worker-raised messages:** under `activate("pl")`, an interpolated
message raised on the worker (the status message) renders **translated**, proving the
`params=` deferral. Mutant: `%`-format it on the worker.

**Unit — control flow (the round-4 defects):** a 404 reports "The image host returned an
error", **not** "Could not reach the image host" — the assertion that proves the `HTTPError`
clause precedes the `URLError` one; a worker-side `ValidationError` (e.g. the Content-Type
gate) surfaces as **its own message**, not as the deadline message — the assertion that
proves the exception box works.

**Unit — `create_asset` runs on the request thread.** The mechanism matters: asserting via a
"`django_db`-visible write" would be an assertion that *cannot fail*, because a background
thread opens its own connection and really commits, so the test's connection sees the row on
its next statement under READ COMMITTED — and worse, that row survives the test's rollback
and leaks into the next test. Instead patch `media_fetch.create_asset` with a wrapper that
records `threading.current_thread()` and assert it is the calling thread. Mutant: move the
`create_asset` call inside `_run`.

**Unit — `fetch_image_asset`, with `_open` patched:** a redirect leaving the allow-list is
rejected; an **http-downgrade** redirect reports the redirect message, not "must use https";
a redirect with no `Location` is rejected; the hop budget reports "too many redirects";
**a returned 206 is rejected with the status message** (it never becomes an `HTTPError`, so
only the explicit `resp.status != 200` check catches it); a `text/html` response at a `.jpg`
path is rejected; an **absent** `Content-Type` is
rejected; an `image/svg+xml` response reports "That image type is not allowed.", not the
not-an-image message; HTML bytes under an `image/png` Content-Type are rejected by Pillow;
**an `MPO`-format JPEG is accepted** (not rejected as unknown); **an unknown `img.format`
(e.g. `BMP`) is a 422, not a `KeyError`/500**; **GIF bytes served as `image/png` are stored
as exactly `Foo.gif`** — an *exact filename equality*, not an "ends with `.gif`" check,
which would also pass for the `Foo.png.gif` double-extension bug; **a `…/Foo.jpg` URL stores
exactly `Foo.jpg`, never `Foo.jpg.jpg`**; a `…/Foo.JPG` URL stores `Foo.jpg`; the extension
is chosen from `effective_image_extensions()` rather than a
literal, including when narrowed to `["jpeg"]`; `image/jpg` is accepted; a `Content-Type`
with parameters is accepted; a zero-byte body is rejected; the cap trips when
`Content-Length` under-reports; a declared over-cap `Content-Length` rejects before the body
is read; an absent or malformed `Content-Length` is ignored; a connect failure and a
**mid-read** failure both surface as `ValidationError`; a `%2F`-bearing path cannot escape
the media directory; a **redirected** fetch persists `submitted_url` in `source_url` while
taking its stem from the final hop; the shared User-Agent and `Accept: image/*` are sent on
the initial request **and every redirect hop**; `source_url` and `content_hash` are both
persisted; the created asset is a normal `MediaAsset` with derivatives generated.

**Unit — the pixel bound:** an image declaring **more than `MAX_PIXELS` (50 M) but fewer
than 2 × `Image.MAX_IMAGE_PIXELS` (178.9 M)** is rejected with "That image's dimensions are
too large." Targeting the >2× band instead would pass on a build with no pixel check at all,
since Pillow refuses those unaided. A second case covers the far side of that boundary: an
image **above** 2 × `Image.MAX_IMAGE_PIXELS` reports the *same* dimensions message, proving
`DecompressionBombError` is mapped rather than falling into the broad clause.

**Unit — the deadline, deliberately not a generator double.** The drip tests must use a
fake whose `read1` returns *partial* data slowly (a raw-file-like double or a real socket),
never a generator that yields on demand: a generator-based fake returns instantly and the
test passes GREEN on a build that reads with `read` instead of `read1` — the exact
"assertion that cannot fail" this repo has shipped before. Cover both a drip **body** and a
drip **header** (the latter is what the thread-join budget, not the socket timeout, is
there for), plus the **budget check between redirect hops**.

**These tests monkeypatch the constants down.** At the shipped values each would block for
`DEADLINE_SECONDS` (20 s), adding roughly a minute to a suite this repo otherwise runs in
~30 s for affected tests. Patch `media_fetch.DEADLINE_SECONDS` and `TIMEOUT_SECONDS` to
sub-second values and express the drip double's rate *relative to the patched value*, so the
tests stay meaningful if the constants ever change.

**Unit — `replace_asset`:** replacing a fetched asset's bytes clears `source_url` as well
as `content_hash`.

**Unit — LAL interaction:** a LAL import of bytes identical to a previously fetched asset
reuses the fetched row rather than creating a second one. The fixture creates exactly one
fetched asset (see the `.first()` caveat under Data), and drives the LAL side through the
**real loader path** rather than a shared digest helper — otherwise both sides compute the
hash the same way by construction and the test would still pass even if the digest form
diverged from `courses/lal_loader/media.py:31`.

**Unit — `source_host`:** returns the hostname for a normal URL, `""` for blank, and `""`
rather than raising for a malformed authority.

**View:** each error shape reaches `_op_error.html` at 422 on a fragment request; the
rendered message is the `"; ".join(e.messages)` form, not a Python repr; a no-JS request
gets a `messages.error` plus a redirect; success returns the asset cell at 200; a
non-manager user is refused by `_require_manage`; an **authenticated** GET is refused with
405 by `@require_POST`; **a POST carrying no `name` key at all succeeds** — the picker's
shape — which is what stops bracket access on `request.POST` surviving as a 500.

**Template:** the picker rendered with `kind="video"` has exactly two tabs and no From URL
panel; with `kind="image"`, three, and the new panel is `hidden` with its tab not `is-on`.
A fetched asset's `_asset_cell.html` renders the source link in `.asset-foot` with the
hostname as its label, the full URL in `title`, and `rel="noopener noreferrer"`. The
`data-msg-fetch-failed` attribute is present on `.media-manager` and on `.picker`.

**E2E:** (a) pasting a URL in the media manager makes the asset appear in the grid; (b) the
picker's From URL tab fetches and selects the asset into an image element; (c) a rejected
URL shows the server's reason text in the picker flash; (d) a second click while a fetch is
in flight issues no second request, on **both** the picker and the manager.

**Scenario (d) needs the in-flight window held open deliberately, and the second
interaction must be forced.** The accepted fixture is a loopback read of a 17,883-byte
static file and completes in single-digit milliseconds, so a plain double-click test
observes one request either way and passes GREEN on a build with no guard at all. Use a
Playwright `page.route` that **delays** the response to the fetch endpoint, count requests
through that handler, and assert the control's `disabled`/`aria-busy` state synchronously
after the first click.

The second interaction cannot be a plain `click()`: Playwright's actionability checks
include *enabled*, so on a **correct** build (button disabled) the call blocks until timeout
and the test fails, while on a broken build it succeeds — the assertion is inverted. Use
`click(force=True)` or `dispatch_event("click")`, and — per the in-flight-flag requirement
in §6 — also assert a second `press("Enter")` in the picker issues no request, since Enter
bypasses the button entirely.

**Two distinct e2e fixtures, not one.** Scenarios (a), (b) and (d) use the *accepted* URL
`{live_server.url}/static/core/img/learner.png` — an existing 17.9 KB PNG served by the live
server's staticfiles handler, so the fetch is genuinely end-to-end over a real socket while
remaining hermetic. Scenario (c) needs a URL the server *rejects*, which cannot be the same
one; it must be an **off-allow-list host** (e.g. `https://example.com/x.png`) so
`validate_fetch_url` fires before any socket opens. That requirement is the point: a
rejection fixture needing a live round trip could reach the real network.

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

**Concurrency is deliberately unbounded, and that decision is recorded rather than
overlooked.** Each in-flight fetch holds a daemon thread, a socket, and up to
`effective_max_image_bytes()` (5 MiB by default) of accumulated body for up to 20 s, so N
simultaneous fetches cost N × 5 MiB of resident memory and N threads. No limiter is being
added, because the endpoint is `_require_manage`-gated — only course managers can reach it,
which is a small, trusted, authenticated population. If this ever becomes reachable by a
wider role, revisit it.
