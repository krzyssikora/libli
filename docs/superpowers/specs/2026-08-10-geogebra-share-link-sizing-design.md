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

### Scope in existing content

Of 139 `IframeElement` rows locally, 134 are GeoGebra and **131 already carry dimensions**
(they were pasted as static embed code). Only three lack them, and one of those is an
orphan with zero join rows (`url …/id/abc123`, a leftover fixture). The two reachable ones
are both in `demo-course` (units 16 and 106), not `mat-pp`. The defect therefore bites
**future share-link pastes**, which is how it was encountered.

### Goals

1. A GeoGebra material added by share link renders identically to the same material added
   by its static embed code — no white space **and** no crop.
2. When the authored size cannot be determined, fall back to **4:3** (GeoGebra's own
   default, measured to leave a 0.0px gap) instead of today's 16:9.
3. When the authored size cannot be determined, tell the author so, non-blockingly, with a
   concrete workaround.
4. Authoring never fails because geogebra.org is slow or unreachable.

### Non-goals

- **No backfill mechanism.** Only two reachable rows are affected and the user will fix
  them by hand. There is no deployment and no production database, so there is no
  environment where a backfill would run unattended.
- **No manual width/height fields in the editor.** Considered and rejected during
  brainstorming; the API lookup removes the need, and the static embed paste remains the
  explicit escape hatch.
- **No change to non-GeoGebra embeds.** The 4:3 correction is scoped to the provider it
  was measured against; every other provider keeps the 16:9 CSS default.
- **No re-fetch or staleness handling.** If an author later resizes the material on
  geogebra.org, our stored dimensions go stale. Re-pasting fixes it.
- **No new e2e test.** An end-to-end assertion here would depend on geogebra.org being
  reachable and would be flaky. The browser measurement recorded above is the evidence for
  the ratio; the render assertions cover the code path.
- **No migration and no `FORMAT_VERSION` bump.** `IframeElement.width`/`.height` already
  exist and are nullable, and nothing new is stored.

## Architecture / components

Five small changes across four files plus settings.

### 1. Lookup helper — `courses/geogebra.py`

This module stays the single GeoGebra parser. It gains a constant and two functions:

```python
GEOGEBRA_DEFAULT_SIZE = (800, 600)   # GeoGebra's own iframe-shell fallback → 4:3

def geogebra_material_id(url) -> str
def fetch_geogebra_dimensions(material_id) -> tuple[int | None, int | None]
```

`geogebra_material_id` is the existing private `_material_id` logic promoted to a public
entry point that takes a URL: it returns the material id for a recognized https GeoGebra
URL and `""` for anything else. `canonicalize_geogebra_url` is refactored to call it, so
recognition logic exists in exactly one place.

`fetch_geogebra_dimensions` performs `GET
https://api.geogebra.org/v1.0/materials/<id>?scope=basic` using stdlib `urllib.request` —
a single GET does not justify a new dependency, and `pyproject.toml` currently has no HTTP
client. The request URL is built from the hardcoded API prefix plus the id, which has
already been validated against `_ID_RE` (`^[A-Za-z0-9_-]+$`) so it cannot introduce a
scheme, host, or path traversal. The function verifies the constructed URL still starts
with `https://api.geogebra.org/` and returns `(None, None)` if it does not — a real guard
rather than an `assert` (which `-O` would strip), and what justifies the `S310`
suppression.

It must handle **both** observed response shapes:

| material `type` | example id | where the dimensions live |
|---|---|---|
| `wseg` (applet) | `wgzr7tsu` | `settings.width` / `settings.height` |
| `ws` (worksheet) | `dcjktevj` | `elements[N].settings.width` / `.height` |

Rule: use top-level `settings` when present; otherwise scan `elements` in order and use
the first entry whose `type == "G"`. A worksheet with several applets therefore resolves
to its first applet, matching what the iframe shell itself renders.

Returned values are validated as positive ints `1..2147483647`. That ceiling is shared
with `courses/embed.py` and remains **load-bearing**: `width`/`height` are not in
`IframeElementForm.Meta.fields`, so `ModelForm._post_clean` excludes them from
`full_clean` and the `PositiveIntegerField` range validator never fires on the form path.
An out-of-range value degrades to `(None, None)`, i.e. the 4:3 fallback.

Like everything else in this module, it **never raises**. `HTTPError` (the API answers a
bad id with **400 `{"error":{"code":"err_invalid_id"}}`**, not 404), `URLError`, socket
timeout, invalid JSON, missing keys, and wrong types all collapse to `(None, None)`.

When `settings.GEOGEBRA_API_LOOKUP` is false it returns `(None, None)` without touching
the network.

### 2. Capture — `IframeElementForm.clean_url`

The existing `parse_iframe_dimensions` capture is unchanged and runs first. The lookup is
attempted only when dimensions are still unknown **and** the canonicalized URL is
GeoGebra:

```python
url = extract_embed_url(raw)
width, height = parse_iframe_dimensions(raw)
if not (width and height):
    mid = geogebra_material_id(url)
    if mid:
        width, height = fetch_geogebra_dimensions(mid)
if width and height:
    self.instance.width = width
    self.instance.height = height
return url
```

Two consequences worth stating: pasting a static embed never touches the network (its
attributes already answer the question), and the existing rule that a title-only edit
never wipes captured dimensions is preserved, because the assignment is still guarded by
`if width and height`.

`extract_embed_url` is deliberately **not** modified. It is shared with course import via
`courses/transfer/payloads.py :: _val_iframe` → `_canonical_embed`, so putting a network
call inside it would make imports hit geogebra.org. Import needs no lookup anyway:
archives have carried `width`/`height` since `FORMAT_VERSION` 2.

### 3. Render — a provider-aware fallback ratio

`IframeElement` gains a property:

```python
@property
def frame_ratio(self):
    """CSS aspect-ratio for the wrapper, or None to keep the .embed-frame default."""
```

- both dimensions known → `"<width> / <height>"`
- GeoGebra with unknown dimensions → `"800 / 600"`, formatted from
  `GEOGEBRA_DEFAULT_SIZE` so the constant is the single source of truth. This is the same
  ratio as `4 / 3` and renders identically; the spec and tests use the literal
  `800 / 600` everywhere to avoid an implementer/test mismatch.
- otherwise → `None`

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

`IframeElement` gains a second property, `size_unknown` — true when the URL is GeoGebra and
either dimension is missing. `templates/courses/manage/editor/_element_row.html` renders a
small hint when it is set. The string, wrapped in `{% translate %}` and given a Polish
catalog entry like every other editor string, is:

> Applet size unknown — using a 4:3 frame, which may crop it. Paste the GeoGebra
> `<iframe>` embed code for exact sizing.

This is derived purely from the element's own state. `_editor_rows` already yields
`(join_row, concrete_obj)` pairs, so the concrete `IframeElement` is in template scope and
**no plumbing through `builder_svc.save_element` is needed**. It is also strictly more
useful than a one-shot banner: it survives later editor loads, flags the pre-existing
dimensionless rows automatically, and clears itself once dimensions are known.

### 5. Settings

`config/settings/base.py`:

```python
GEOGEBRA_API_LOOKUP = True
GEOGEBRA_API_TIMEOUT = 3        # seconds; measured responses were 0.22–0.27s
```

`config/settings/test.py` sets `GEOGEBRA_API_LOOKUP = False`, so the suite cannot reach
the network even if a test forgets to patch.

## Data flow

```
author pastes …
├── static embed <iframe … width="880px" height="660px">
│     parse_iframe_dimensions → (880, 660)          [no network]
│     stored 880×660 → wrapper 880/660, src /width/880/height/660
│
├── share link https://www.geogebra.org/m/dcjktevj
│     canonicalize → …/material/iframe/id/dcjktevj
│     parse_iframe_dimensions → (None, None)
│     geogebra_material_id → "dcjktevj"
│     fetch_geogebra_dimensions → (880, 660)         [one 3s-timeout GET]
│     stored 880×660 → wrapper 880/660, src /width/880/height/660
│     ⇒ identical render to the static embed
│
└── share link, lookup unavailable
      stored NULL → wrapper 800/600 (= 4:3), bare src, editor badge shown
      ⇒ no white space; applet may be cropped to GeoGebra's 800×600 viewport
```

## Error handling

| condition | behaviour |
|---|---|
| API 400 `err_invalid_id`, 5xx, DNS failure, timeout | `(None, None)` → save succeeds, 4:3, badge |
| malformed JSON / unexpected shape / missing `settings` | `(None, None)` → same |
| dimension ≤ 0, non-int, or > 2147483647 | `(None, None)` → same |
| constructed URL fails the `https://api.geogebra.org/` prefix check | `(None, None)`, no request |
| `GEOGEBRA_API_LOOKUP` false | `(None, None)` without a network call |
| non-GeoGebra URL with no dimensions | unchanged: 16:9 CSS default, no badge |

The element **always saves**. No failure mode of a third-party API can block authoring,
and no failure mode can raise out of `courses/geogebra.py`.

## Testing

All tests run offline. The three real API responses captured while diagnosing this —
a `ws` worksheet, a `wseg` applet, and the 400 `err_invalid_id` — become checked-in JSON
fixtures, so the parser is tested against real payloads rather than invented ones.

**Parser (`fetch_geogebra_dimensions`), network stubbed:**
- `wseg` fixture → `(880, 660)` from top-level `settings`
- `ws` fixture → `(880, 660)` from `elements[0].settings`
- worksheet whose first element is not `type == "G"` → the first `"G"` entry is used
- 400 `err_invalid_id` fixture → `(None, None)`
- timeout / `URLError` / invalid JSON / missing `settings` → `(None, None)`, no raise
- `width: 0`, `width: -5`, `width: "880"`, `width: 2147483648` → `(None, None)`
- `GEOGEBRA_API_LOOKUP = False` → `(None, None)` and the transport is never called

**`geogebra_material_id`:** share, classic, canonical and full-iframe forms → the id;
non-GeoGebra, http, subdomain, malformed → `""`. Existing `canonicalize_geogebra_url`
tests must still pass unchanged after the refactor.

**Form:**
- static embed paste → dimensions captured, lookup **not** called
- share-link paste, lookup returns `(880, 660)` → instance carries 880×660
- share-link paste, lookup fails → form is valid, dimensions stay NULL
- title-only edit of an element with captured dimensions → dimensions unchanged
- non-GeoGebra plain URL → lookup not called

**Render:**
- GeoGebra, no dimensions → `style="aspect-ratio: 800 / 600"`
- GeoGebra, 880×660 → `style="aspect-ratio: 880 / 660"` and src ends `/width/880/height/660`
- non-GeoGebra, no dimensions → **no** inline `aspect-ratio` (16:9 default stands)

**Editor row:**
- GeoGebra without dimensions → badge present
- GeoGebra with dimensions → badge absent
- non-GeoGebra without dimensions → badge absent

**Import:** an existing round-trip test is extended to assert the import path performs no
GeoGebra lookup, guarding the `extract_embed_url` boundary decision.

Every test is falsified to RED before it counts, per the repo's standing rule that a
passing test proves nothing until its failure mode has been demonstrated.

## Risks

- **GeoGebra changes the 800×600 default or the shell.** The 4:3 fallback would drift.
  Low impact: it only governs the degraded path, and the primary path stores real
  dimensions. The constant is named and documented at one site.
- **A save now depends on a network call.** Bounded by a 3s timeout, attempted only on
  the share-link path, and every failure is non-fatal. Worst case an author waits 3
  seconds and gets today's behaviour plus a badge.
- **API shape change.** Handled by the never-raises contract: a shape we no longer
  recognise degrades to the fallback rather than breaking authoring.
