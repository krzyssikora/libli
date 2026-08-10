# GeoGebra share-link sizing

**Date:** 2026-08-10
**Status:** Approved (ready for implementation planning)

## Purpose

A GeoGebra material added by its **share link** (`https://www.geogebra.org/m/dcjktevj`)
renders with a band of white space down its right-hand side. The same material added by
GeoGebra's suggested **static embed code** (`<iframe … width="880px" height="660px">`)
renders correctly. This design makes the share link render identically to the static embed.

### Measured mechanism

`canonicalize_geogebra_url` rewrites the share link to
`https://www.geogebra.org/material/iframe/id/dcjktevj`. Fetching that URL returns a page
whose entire sizing logic is client-side:

```js
const parameters = { …, "allowUpscale": "true", "scaleContainerClass": "frame" };
// width/height are read from the URL path segments, then:
parameters.width  = (parameters.width  || 800) * 1;
parameters.height = (parameters.height || 600) * 1;
```

Three fetches — a different material id, and the same id with and without a
`/width/…/height/…` tail — returned **byte-identical** documents (md5
`33b9101e9bb5777016b8a4ae4ac8e2a5`). GeoGebra serves one static shell for every embed;
the material's authored size never reaches the sizing code. The only inputs are the URL
path segments, and the fallback is **800×600 (4:3)**.

`scaleContainerClass` then scales that applet **uniformly** to fit the container. Our
wrapper for an element with no captured dimensions is `.embed-frame`'s default
`aspect-ratio: 16 / 9`. Measured in Chromium at the real 648px content width:

| case | wrapper | applet renders | gap right |
|---|---|---|---|
| current: 16:9 wrapper, bare src | 648 × 364.5 (1.778) | 486.7 × 365.0 (**1.333**) | **161.3px** |
| 4:3 wrapper, bare src | 648 × 486 (1.333) | 648 × 486 (1.333) | **0.0px** |
| 4:3 wrapper, src `/width/880/height/660` | 648 × 486 (1.333) | 648 × 486 (1.333) | **0.0px** |

So the root cause is precise: **our fallback ratio (16:9) disagrees with GeoGebra's own
fallback ratio (4:3).** The applet renders at 1.333 whatever box it is given; the
remainder is white space.

### The second, less visible half

Correcting the wrapper to 4:3 closes the gap but does **not** make a share link equal to
the static embed. GeoGebra's 800×600 default is ~9% tighter than this material's authored
880×660, so it **crops the construction**. In the measured screenshots the 4:3-bare case
shows a y-axis of 4→18, while the authored 880×660 case shows 0→18 — including a data
point at ≈(14, 2) that the default viewport omits entirely. On a correlation scatter plot
that is a content defect, not a cosmetic one.

A URL-only fix cannot recover it. The shell's alias table accepts exactly `width, height,
stb, smb, ai, asb, sri, ld, sdz, rc, sfsb, stbh, szb, border, id` — there is no
"fit the construction" parameter. **The crop can only be fixed by knowing the authored
width/height**, which `https://api.geogebra.org/v1.0/materials/<id>?scope=basic` supplies.

### Live verification of the API path

The measurements above were taken with `curl`. Because the shipped code uses
`urllib.request` — whose default `User-Agent: Python-urllib/3.x` is a plausible thing for
a CDN to reject — the exact call this design specifies was also run for real:

```
urllib.request.urlopen("https://api.geogebra.org/v1.0/materials/dcjktevj?scope=basic", timeout=5)
→ 200; elements[0].settings.width = 880, .height = 660
```

So the endpoint is reachable from this code path today with no custom header. An explicit
`User-Agent` is still specified below (see §1) as courtesy and future-proofing, not as a
fix for a present breakage. **Acceptance criterion:** re-run this one-off call through the
shipped `fetch_geogebra_dimensions` before opening the PR and record the returned pair in
the PR body — the offline test suite cannot detect the API moving.

### Scope in existing content, and every creation path

Of 139 `IframeElement` rows locally, 134 are GeoGebra and **131 already carry dimensions**
(they were pasted as static embed code). Only three lack them, and one of those is an
orphan with zero join rows (`url …/id/abc123`, a leftover fixture). The two reachable ones
are both in `demo-course` (units 16 and 106), not `mat-pp`.

Counting rows is not enough, because rows keep being created. Every path that constructs
an `IframeElement`, and whether it gets the lookup:

| path | gets the lookup? | why |
|---|---|---|
| `IframeElementForm` (editor create/edit) | **yes** | the interactive path this design targets |
| `courses/lal_loader/builders.py:350` (`IframeElement.objects.create(url=…, title=…)`) | **no** | bulk mat-pp ingest; adding a per-element network call would make a large import slow and network-dependent. Imported GeoGebra elements land dimensionless and are covered by the 4:3 fallback + the badge. |
| `courses/management/commands/seed_demo_course.py` | **no** | fixture seeding, not authored content |
| `courses/transfer` import (`_build_iframe`) | **no** | archives already carry `width`/`height` (`FORMAT_VERSION` ≥ 2), so a lookup would be redundant *and* would put the network in the import path |
| Django admin (`admin.site.register(IframeElement)`) | **no** | raw model form, no `clean_url`; a staff-only escape hatch |

The defect therefore bites **future share-link pastes through the editor**, which is how it
was encountered, plus every future LAL import — the latter now visibly flagged by the badge
rather than silently mis-framed.

### Goals

1. A GeoGebra material added by share link **through the editor** renders identically to the
   same material added by its static embed code — no white space **and** no crop.
2. When the authored size cannot be determined, fall back to **4:3** (GeoGebra's own
   default, measured to leave a 0.0px gap) instead of today's 16:9.
3. When the authored size cannot be determined, tell the author so, non-blockingly, with a
   concrete workaround.
4. Authoring never fails because geogebra.org is slow or unreachable.

### Non-goals

- **No backfill mechanism.** Only two reachable rows are affected and the user will fix
  them by hand. There is no deployment and no production database, so there is no
  environment where a backfill would run unattended.
- **No lookup on the bulk paths** (LAL loader, seed command, transfer import, admin) — see
  the table above.
- **No manual width/height fields in the editor.** Considered and rejected during
  brainstorming; the API lookup removes the need, and the static embed paste remains the
  explicit escape hatch.
- **No change to non-GeoGebra embeds.** The 4:3 correction is scoped to the provider it
  was measured against; every other provider keeps the 16:9 CSS default.
- **No re-fetch or staleness handling.** A stored dimension pair is never re-derived (see
  the invariant in §2). If an author later resizes the material on geogebra.org, re-pasting
  the embed code is the way to update it.
- **No new e2e test.** An end-to-end assertion here would depend on geogebra.org being
  reachable and would be flaky. The browser measurement recorded above is the evidence for
  the ratio; the render assertions cover the code path; the one-off live check above covers
  the API contract.
- **No migration and no `FORMAT_VERSION` bump.** `IframeElement.width`/`.height` already
  exist and are nullable, and nothing new is persisted on the model.

## Architecture / components

Five changes plus one settings flag.

### 1. Lookup helper — `courses/geogebra.py`

This module stays the single GeoGebra parser. It gains constants, a transport seam, and
two public functions:

```python
GEOGEBRA_DEFAULT_SIZE = (800, 600)   # GeoGebra's own iframe-shell fallback → 4:3
_API_PREFIX = "https://api.geogebra.org/"
_TIMEOUT_SECONDS = 3          # module constant, matching integrations/delivery.py's precedent
_MAX_BODY_BYTES = 65536
_NEGATIVE_TTL_SECONDS = 600
_USER_AGENT = "libli/1.0 (+https://github.com/krzyssikora/libli)"

def _open(url, timeout):                       # the transport seam tests patch
def geogebra_material_id(url) -> str
def fetch_geogebra_dimensions(material_id) -> tuple[int, int] | tuple[None, None]
```

`geogebra_material_id` is the existing private `_material_id` logic promoted to a public
entry point that takes a URL: it returns the material id for a recognized https GeoGebra
URL and `""` for anything else. `canonicalize_geogebra_url` is refactored to call it, so
recognition logic exists in exactly one place.

**Return contract.** `fetch_geogebra_dimensions` is **all-or-nothing**: it returns either a
pair of positive ints or `(None, None)`. A partial pair such as `(880, None)` is
unreachable by construction, which is why the annotation is
`tuple[int, int] | tuple[None, None]` rather than the looser
`tuple[int | None, int | None]`.

**Transport.** `_open(url, timeout)` is a thin module-level wrapper around an opener built
the same way `integrations/delivery.py` builds its own:

```python
opener = urllib.request.build_opener(_NoRedirect)     # reuse the delivery.py pattern
req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
return opener.open(req, timeout=timeout)
```

Refusing redirects matters: `urlopen` follows them by default, so a checked-at-construction
URL says nothing about the host actually contacted. `integrations/delivery.py :: _NoRedirect`
already exists for exactly this reason and should be reused (imported, or the four-line
handler duplicated with a comment pointing at the original — the plan decides which, but the
behaviour is fixed).

The URL is built as `_API_PREFIX + "v1.0/materials/" + material_id + "?scope=basic"`, where
`material_id` has already been validated against `_ID_RE` (`^[A-Za-z0-9_-]+$`) so it cannot
introduce a scheme, host, or path traversal. A `startswith(_API_PREFIX)` check on the
constructed URL is **defensive only and unreachable by construction** — it is deliberately
*not* claimed as a security control and gets **no test**, because a branch that cannot be
driven cannot be falsified to RED. The real control is `_ID_RE` plus the no-redirect opener.
Observed ids are 8 characters; `_ID_RE` is unbounded, which is acceptable because the URL
reaching this code has already passed `URLField`'s own length cap upstream — noted so a
future reader does not mistake `_ID_RE` for a length guard.

**Body handling.** Read at most `_MAX_BODY_BYTES` (`resp.read(_MAX_BODY_BYTES)`) and parse.
An oversized, truncated, or otherwise unparseable body degrades to `(None, None)` via the
never-raises path — the socket timeout alone does not bound how much a slow or hostile
endpoint can send.

**Response shapes.** Two are observed. Here is a real `ws` response trimmed from the
document root down to the dimensions, so the paths below are verifiable from this spec
alone:

```json
{
  "id": "dcjktevj",
  "title": "korelacja 1",
  "type": "ws",
  "elements": [
    {
      "id": 42153397,
      "order": 0,
      "type": "G",
      "settings": { "appName": "classic", "width": 880, "height": 660, "scale": 1 }
    }
  ],
  "visibility": "S"
}
```

Verified against the live API: this `ws` document has **no top-level `settings` key** — its
root keys are exactly `creator_id, date_created, date_modified, date_published, deleted,
elements, id, supportsLesson, thumbUrl, title, type, visibility`. The `wseg` document
(`wgzr7tsu`) *does* carry a top-level `settings` object holding `width`/`height`, plus a
`worksheet_id` back-pointer.

| material `type` | example id | where the dimensions live |
|---|---|---|
| `wseg` (applet) | `wgzr7tsu` | `settings.width` / `settings.height` |
| `ws` (worksheet) | `dcjktevj` | `elements[N]["settings"]["width"]` / `["height"]` |

**Selection rule — a fallthrough on *usable dimensions*, not on key presence.** Keying on
"is there a `settings` object" would short-circuit a worksheet that carries a top-level
`settings` holding only layout keys, silently degrading the headline scenario while every
offline test still passed. So:

1. If top-level `settings` yields a usable pair, return it.
2. Otherwise scan `elements` in document order and return the first entry with
   `elements[N]["type"] == "G"` **whose settings yield a usable pair**. Keep scanning past a
   `"G"` entry that does not — do not stop at the first `"G"`.
3. If nothing yields a usable pair, return `(None, None)`.

"Usable pair" is the single predicate defined in §3 and shared by every consumer.

**Never raises — a bare `except Exception`.** An enumerated tuple is not sufficient:
`urlopen` can raise `http.client.RemoteDisconnected`, `ConnectionResetError`, `ssl.SSLError`
variants, `UnicodeDecodeError` on a mis-encoded body, and `ValueError` from `Request()`
construction, none of which are `URLError` subclasses. Anything escaping into `clean_url`
would 500 the save — the exact failure this contract exists to prevent. Wrap the whole
fetch-and-parse body in a bare `except Exception:`, matching the precedent already set by
`courses/embed.py :: parse_iframe_dimensions`.

**Observability.** On any failure path, emit a `logger.warning` carrying the material id and
the exception type (or the HTTP status). Without it, a systemic failure — API path changed,
schema reshaped, UA blocked — is indistinguishable from "this material genuinely has no
dimensions", and the only signal is a badge the author reads as a property of their own
material. A successful lookup logs nothing.

**Negative cache.** A failed lookup caches a sentinel under `geogebra:dims:<material_id>` in
the default cache for `_NEGATIVE_TTL_SECONDS`, and a cached sentinel short-circuits to
`(None, None)` without a request. Only *failures* are cached; a success is persisted on the
model, so there is nothing to cache. This bounds the repeat cost called out in the risk
below: without it, every subsequent save of a dimensionless element re-pays the full timeout
while holding a row lock. `config/settings/test.py` already pins `LocMemCache`, and tests
that exercise the lookup must clear the cache between cases.

**Kill switch.** When `settings.GEOGEBRA_API_LOOKUP` is false, return `(None, None)`
immediately — no cache read, no request.

### 2. Capture — `IframeElementForm.clean_url`

The existing `parse_iframe_dimensions` capture is unchanged and runs first. The lookup is
attempted only when dimensions are unknown **both in the paste and on the instance**, and
the canonicalized URL is GeoGebra:

```python
url = extract_embed_url(raw)
width, height = parse_iframe_dimensions(raw)
stored = (self.instance.width, self.instance.height)
if not _usable(width, height) and not _usable(*stored):
    mid = geogebra_material_id(url)
    if mid:
        width, height = fetch_geogebra_dimensions(mid)
if _usable(width, height):
    self.instance.width = width
    self.instance.height = height
return url
```

**Invariant: a stored dimension pair is never re-derived.** The instance guard is
load-bearing, not defensive. On an edit the textarea is pre-filled with the stored
*canonical URL*, not the original `<iframe>` snippet — `tests/test_iframe_dimensions.py ::
test_form_plain_url_edit_preserves_existing_dimensions` posts exactly
`data={"url": URL, "title": "renamed"}`. So `parse_iframe_dimensions` returns `(None, None)`
on **every** subsequent edit of a static-embed element. Without the instance guard, a
title-only rename would fire a network call and, if GeoGebra now reported a different size,
would silently replace the author's captured 880×660. The guard is also what makes the claim
"pasting a static embed never touches the network" true for the life of the element, not just
its first save.

Re-pasting a full `<iframe>` still overwrites dimensions, because that path is satisfied by
`parse_iframe_dimensions` before the guard is consulted — preserving today's
`test_form_re_paste_overwrites_dimensions` behaviour.

`extract_embed_url` is deliberately **not** modified. It is shared with course import via
`courses/transfer/payloads.py :: _val_iframe` → `_canonical_embed`, so putting a network
call inside it would make imports hit geogebra.org.

**The lookup runs inside a locked transaction — stated, not hidden.**
`courses/builder.py :: save_element` is decorated `@transaction.atomic`, and its first act is
`_locked_unit(course, unit_pk)`, which is a `select_for_update()` on the unit's
`ContentNode` row. `form.is_valid()` — and therefore `clean_url` and the GET — runs after
that lock is taken. So the lookup holds an open transaction, a pooled DB connection, and an
exclusive row lock on the unit for the duration of the call.

This is **accepted deliberately** rather than restructured, on these grounds: the lookup
fires only on the first save of a dimensionless GeoGebra element (per the invariant above),
concurrent edits of the *same unit* are the only thing it can block, and the mitigations
above — 3s socket timeout, capped body read, refused redirects, and the negative cache —
keep the common failure path short and stop an outage from re-charging the lock on every
retry. Moving the resolution out of `clean_url` would mean leaking iframe-specific logic
into the view layer or changing `save_element`'s signature, which is a larger blast radius
than the risk warrants. The alternative is recorded here so a future reader can revisit it
rather than rediscover the lock.

### 3. Render — a provider-aware fallback ratio

**One predicate, shared.** Define a single module-level helper:

```python
def _usable(width, height):
    """True iff both dimensions are positive ints — the one definition of 'known size'."""
```

Every consumer uses it: the parser's selection rule, `clean_url`'s guards, `frame_ratio`,
and `size_unknown`. This is what stops the badge and the ratio from ever disagreeing, and it
pins down the partial/zero cases that `width` and `height` being independently nullable
allows (`check_int_or_null` in the transfer validator admits `(800, None)` and `(0, 0)` from
an archive).

`IframeElement` gains two properties:

```python
@property
def frame_ratio(self):
    """CSS aspect-ratio for the wrapper, or None to keep the .embed-frame default."""

@property
def size_unknown(self):
    """True for a GeoGebra embed whose dimensions are not usable — drives the editor badge."""
```

`frame_ratio` resolves in this order:

- `_usable(self.width, self.height)` → `"<width> / <height>"`
- else GeoGebra URL → `"800 / 600"`, formatted from `GEOGEBRA_DEFAULT_SIZE` so the constant
  is the single source of truth. This is the same ratio as `4 / 3` and renders identically;
  the spec and tests use the literal `800 / 600` everywhere to avoid an implementer/test
  mismatch.
- else → `None`

So a partial or zero pair on a GeoGebra element takes the `800 / 600` branch, and on any
other provider takes the `None` branch — never a malformed `aspect-ratio: 800 / None`.

`templates/courses/elements/iframeelement.html` switches from testing
`el.width and el.height` to testing `el.frame_ratio`:

```html
<div class="embed-frame"{% if el.frame_ratio %} style="aspect-ratio: {{ el.frame_ratio }}"{% endif %}>
```

`.embed-frame`'s `aspect-ratio: 16 / 9` stays as the CSS default and continues to govern
every non-GeoGebra embed with unknown dimensions. `embed_src` and `geogebra_sized_src` are
unchanged: once the lookup supplies dimensions, the existing code appends
`/width/W/height/H`, which is exactly what makes the share link match the static embed.

### 4. Author feedback — a persistent editor badge

`templates/courses/manage/editor/_element_row.html` has eight `{% elif %}` branches for
container types; an iframe element falls through to the **terminal `{% else %}` block**
(currently at line 300), which is where the badge goes. The concrete object is in scope as
`obj` — **not** `el`, which is the join row — so the condition is `{% if obj.size_unknown %}`.

Markup reuses the existing flag class from the revealgate branch
(`<span class="el-row__flag">{% trans "inactive in quizzes" %}</span>`, line 29), so **no
CSS change is needed** and the repo's "every view ships styled" rule is satisfied by an
existing rule rather than a new one. A two-sentence string is too heavy for an inline row
flag sitting next to `el-tag`/`el-actions`, so the workaround goes in a tooltip:

```html
<span class="el-row__flag"
      title="{% trans "The applet size is unknown, so it renders in a 4:3 frame and may be cropped. Paste the <iframe> embed code for exact sizing." %}">{% trans "applet size unknown" %}</span>
```

Both strings are autoescaped (never `|safe`), so the literal `<iframe>` in the tooltip
reaches the DOM as `&lt;iframe&gt;` and displays to the author as `<iframe>`. The backticks
used elsewhere in this spec are markdown and are **not** part of the string.

**Catalog deliverable.** Add the two strings to the Polish catalog as an explicit step: run
`makemessages -l pl -l en --no-obsolete`, write the translations, **clear any `#, fuzzy`
marker** the extractor pre-fills, and run `compilemessages`. The repo has a recorded hazard
where a fuzzy pre-fill silently ships a wrong translation and clearing it requires two
deletions — verify `0 fuzzy` before committing.

This condition is derived purely from the element's own state. `_editor_rows` already yields
`(join_row, concrete_obj)` pairs, so **no plumbing through `builder_svc.save_element` is
needed**. It is also strictly more useful than a one-shot banner: it survives later editor
loads, flags the pre-existing dimensionless rows and every future LAL-imported one
automatically, and clears itself once dimensions are known.

### 5. Settings

`config/settings/base.py` gains exactly one flag:

```python
GEOGEBRA_API_LOOKUP = True      # kill switch; False in test.py
```

It is a Django setting rather than a module constant specifically because
`config/settings/test.py` must be able to turn it off suite-wide. The timeout and the other
tunables stay **module constants** in `courses/geogebra.py` (`_TIMEOUT_SECONDS`,
`_MAX_BODY_BYTES`, `_NEGATIVE_TTL_SECONDS`), matching the precedent of
`integrations/delivery.py :: TIMEOUT_SECONDS = 10`. Neither is `env()`-backed and neither
goes in `.env.example`, because there is no deployment to configure them for.

`config/settings/test.py` sets `GEOGEBRA_API_LOOKUP = False`, so the suite cannot reach the
network even if a test forgets to patch the seam. See the Testing section for the
`override_settings` consequence — it is not optional.

## Data flow

```
author pastes …
├── static embed <iframe … width="880px" height="660px">
│     parse_iframe_dimensions → (880, 660)          [no network]
│     stored 880×660 → wrapper 880/660, src /width/880/height/660
│
├── later title-only edit of that element
│     parse_iframe_dimensions → (None, None)  (field holds the canonical URL)
│     instance already usable → guard short-circuits   [no network, dims untouched]
│
├── share link https://www.geogebra.org/m/dcjktevj
│     canonicalize → …/material/iframe/id/dcjktevj
│     parse_iframe_dimensions → (None, None); instance empty
│     geogebra_material_id → "dcjktevj"
│     fetch_geogebra_dimensions → (880, 660)   [one GET, inside the unit's row lock]
│     stored 880×660 → wrapper 880/660, src /width/880/height/660
│     ⇒ identical render to the static embed
│
└── share link, lookup unavailable
      logger.warning; negative-cache the id for 10 min
      stored NULL → wrapper 800/600 (= 4:3), bare src, editor badge shown
      ⇒ no white space; applet may be cropped to GeoGebra's 800×600 viewport
```

## Error handling

| condition | behaviour |
|---|---|
| API 400 `err_invalid_id`, 5xx, DNS failure, timeout | `(None, None)` → save succeeds, 4:3, badge, warning logged, id negative-cached |
| redirect response | refused by the no-redirect opener → `(None, None)` |
| body larger than `_MAX_BODY_BYTES`, truncated, or not JSON | `(None, None)` → same |
| any exception type at all, listed or not | caught by the bare `except Exception` → `(None, None)` |
| no `settings` and no `"G"` element yielding a usable pair | `(None, None)` → same |
| dimension ≤ 0, non-int, or > 2147483647 | not usable → `(None, None)` → same |
| id already in the negative cache | `(None, None)` without a request |
| `GEOGEBRA_API_LOOKUP` false | `(None, None)` without a cache read or request |
| non-GeoGebra URL with no dimensions | unchanged: 16:9 CSS default, no badge |

The element **always saves**. No failure mode of a third-party API can block authoring, and
no failure mode can raise out of `courses/geogebra.py`.

**The upper bound on a save is not a hard 3 seconds.** `urlopen(..., timeout=N)` sets the
*socket* timeout: it applies per blocking socket operation — the connect, and each
individual `recv` — not to the total exchange. An endpoint dripping one byte every 2.9s
keeps the request alive well past 3s, and `getaddrinfo` name resolution is not covered by
the socket timeout at all, so a stalled resolver can block before the connect is even
attempted. The capped read bounds total bytes, which bounds the drip scenario in practice,
but the honest statement is: **the worst case is bounded by the capped read, not by a
wall-clock guarantee, and DNS stalls are out of scope.** The mitigation for the repeat case
is the negative cache, not the timeout.

## Testing

All tests run offline. The three real API responses captured while diagnosing this —
a `ws` worksheet (`dcjktevj`), a `wseg` applet (`wgzr7tsu`), and the 400 `err_invalid_id` —
are checked in as JSON fixtures under `tests/fixtures/geogebra/` named `ws.json`,
`wseg.json`, and `err_invalid_id.json`, so the parser is tested against real payloads.

**The two seams, named explicitly** — the test groups patch *different* things and must not
be conflated:

- **Parser tests** patch `courses.geogebra._open`, the module-level transport seam, and
  assert on the returned pair and on the recorded call arguments.
- **Form / import tests** patch `courses.element_forms.fetch_geogebra_dimensions` and assert
  **call counts** (including zero).

**`GEOGEBRA_API_LOOKUP` is False for the whole suite** (`pyproject.toml` pins
`DJANGO_SETTINGS_MODULE = "config.settings.test"`). Every test that exercises the lookup —
including the "invalid input → `(None, None)`" cases, which would otherwise pass vacuously
by short-circuiting before the parser runs and could never be falsified to RED — must wrap
in `override_settings(GEOGEBRA_API_LOOKUP=True)`. Exactly one test deliberately runs under
the `False` default: the kill-switch test below. Tests touching the negative cache clear the
default cache between cases.

**Parser (`fetch_geogebra_dimensions`), `_open` patched, `GEOGEBRA_API_LOOKUP=True`:**
- `wseg.json` → `(880, 660)` from top-level `settings`
- `ws.json` → `(880, 660)` from `elements[0]["settings"]`
- a **derived** fixture — the real `ws.json` hand-edited to put a non-`"G"` element first —
  → the first `"G"` entry is used. Noted as derived, since no captured response exhibits
  this; the fixture-realism rule yields here to covering the branch.
- a second derived fixture where the first `"G"` entry's settings carry no usable pair and a
  later `"G"` entry does → the later one is used (pins the "keep scanning" rule)
- a derived fixture with a top-level `settings` holding only layout keys plus a usable
  `elements[0]` → falls through to the element (pins the usable-dimensions fallthrough)
- `err_invalid_id.json` served as a 400 `HTTPError` → `(None, None)`
- timeout / `URLError` / invalid JSON / missing `settings` → `(None, None)`, no raise
- `_open` raising an **unlisted** exception type (e.g. `ssl.SSLError`) → `(None, None)`,
  proving the bare `except Exception` rather than an enumerated tuple
- `width: 0`, `width: -5`, `width: "880"`, `width: 2147483648` → `(None, None)`
- a body exceeding `_MAX_BODY_BYTES` → `(None, None)`
- **timeout passthrough:** assert `_open` received `timeout=_TIMEOUT_SECONDS`. Without this,
  an implementation that reads the constant but forgets the `timeout=` kwarg — leaving
  `socket.getdefaulttimeout()`, i.e. no timeout at all — passes every other test here.
- **User-Agent:** assert the request carries the explicit `_USER_AGENT`, not
  `Python-urllib`.
- **negative cache:** two consecutive failing calls for the same id issue exactly **one**
  `_open` call
- **kill switch** (the one test under the `False` default): `_open` is never called and the
  result is `(None, None)`

**`geogebra_material_id`** — literal inputs, not category names:
- `https://www.geogebra.org/m/dcjktevj` → `"dcjktevj"`
- `https://www.geogebra.org/material/show/id/dcjktevj` → `"dcjktevj"`
- `https://www.geogebra.org/material/iframe/id/dcjktevj` → `"dcjktevj"`
- `https://www.geogebra.org/classic/dcjktevj` → `""` (an app link, not a material URL —
  stated explicitly because "classic" is otherwise ambiguous with the `/material/show/`
  form)
- `http://www.geogebra.org/m/dcjktevj` (non-https) → `""`
- `https://beta.geogebra.org/m/dcjktevj` (subdomain) → `""`
- `https://example.com/m/dcjktevj` → `""`

Existing `canonicalize_geogebra_url` tests must still pass **unchanged** after the refactor —
that is the regression guard on promoting `_material_id`.

**Form** (patching `courses.element_forms.fetch_geogebra_dimensions`):
- static embed paste → dimensions captured, lookup called **zero** times
- **edit of an element with stored 880×660** (posting the canonical URL, changing only the
  title) → lookup called **zero** times, dimensions unchanged. This is the C1 regression
  guard; it fails against a `parse_iframe_dimensions`-only guard.
- lookup returning a *different* pair for an element that already has one → stored values
  unchanged (the invariant, asserted directly rather than inferred from the call count)
- share-link paste on a fresh element, lookup returns `(880, 660)` → instance carries 880×660
- share-link paste, lookup returns `(None, None)` → form is valid, dimensions stay NULL
- re-paste of a different full `<iframe>` → dimensions overwritten, lookup not called
  (preserves `test_form_re_paste_overwrites_dimensions`)
- non-GeoGebra plain URL → lookup not called

**Render:**
- GeoGebra, 880×660 → `style="aspect-ratio: 880 / 660"`, src ends `/width/880/height/660`
- GeoGebra, no dimensions → `style="aspect-ratio: 800 / 600"`
- GeoGebra, `(800, None)` / `(None, 600)` / `(0, 0)` → `style="aspect-ratio: 800 / 600"`
- **non-GeoGebra**, no dimensions → **no** inline `aspect-ratio` (16:9 CSS default stands)
- **non-GeoGebra**, `(800, None)` / `(0, 0)` → no inline `aspect-ratio`

**Existing tests that must be updated — not bugs in the implementation.**
`tests/test_iframe_dimensions.py` defines `URL = "https://www.geogebra.org/material/iframe/id/abc"`,
i.e. a **GeoGebra** URL, and two tests assert `"aspect-ratio:" not in html`:

| test | inputs | today | after |
|---|---|---|---|
| `test_render_falls_back_to_16x9_when_dimensions_unknown` | `(None, None)` | no inline ratio | `aspect-ratio: 800 / 600` |
| `test_render_falls_back_when_dimensions_partial_or_zero` | `(800, None)`, `(None, 600)`, `(0, 0)` | no inline ratio | `aspect-ratio: 800 / 600` |

Both must be rewritten to the new expectation, and the "16:9 default stands" coverage
re-pointed at a **non-GeoGebra** URL (a second module-level constant, e.g.
`OTHER_URL = "https://example.com/embed/abc"`). An implementer who is not told this will read
the four failures as a defect in their own code.

**Editor row:**
- GeoGebra without dimensions → badge present, with the tooltip text
- GeoGebra with dimensions → badge absent
- GeoGebra with a partial/zero pair → badge present (mirrors `frame_ratio`, via `_usable`)
- non-GeoGebra without dimensions → badge absent

**Import:** an existing round-trip test is extended to assert the import path performs no
GeoGebra lookup, guarding the `extract_embed_url` boundary decision.

Every test is falsified to RED before it counts, per the repo's standing rule that a passing
test proves nothing until its failure mode has been demonstrated. The one deliberate
exception is the `_API_PREFIX` defensive check, which is unreachable by construction and is
therefore specified as untested rather than given a test that cannot fail.

## Risks

- **GeoGebra changes the 800×600 default or the shell.** The 4:3 fallback would drift.
  Low impact: it only governs the degraded path, and the primary path stores real
  dimensions. The constant is named and documented at one site.
- **A save depends on a network call made while holding the unit's row lock** (§2). Mitigated
  by the first-save-only invariant, the socket timeout, the capped read, and the negative
  cache; explicitly accepted, with the restructuring alternative recorded.
- **The worst-case save latency is not hard-bounded** (see Error handling). A slow-drip
  endpoint or a stalled DNS resolver can exceed the nominal 3s.
- **API shape or endpoint change.** Handled by the never-raises contract: an unrecognised
  shape degrades to the fallback rather than breaking authoring. Detection relies on the
  `logger.warning` and the pre-PR live check, since no automated test touches the network.
