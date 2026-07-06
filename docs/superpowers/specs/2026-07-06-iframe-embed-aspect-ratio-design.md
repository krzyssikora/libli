# Iframe embed aspect ratio — design

**Date:** 2026-07-06
**Status:** Approved (ready for implementation planning)

## Problem

The Embed/iframe element renders every embed inside a hard-coded 16:9 box.
`templates/courses/elements/iframeelement.html` wraps the `<iframe>` in
`<div class="embed-16x9">`, and `courses/static/courses/css/courses.css` pins
`.embed-16x9 { aspect-ratio: 16 / 9 }` with the iframe absolutely filling it.

Many embeds are not 16:9. A GeoGebra worksheet authored at `800×760` (≈1.05:1,
nearly square) is forced into a 1.78:1 frame, so it renders with the wrong
proportions. The pasted `<iframe>` carries the intended size in its `width`/
`height` attributes, but we currently discard them — `extract_embed_url` keeps
only the `src`, and the GeoGebra canonicalizer additionally strips the URL's
`/width/…/height/…` tail.

## Goals

1. When a full `<iframe>` is pasted, capture its `width`/`height` attributes and
   render the embed at that aspect ratio (still full-width and responsive).
2. Fall back to the current **16:9** when dimensions are unknown (a plain-URL
   paste, or a tag without usable numeric dimensions).
3. Apply generically to every iframe/embed provider — the mechanism reads the
   `<iframe>` attributes, so a YouTube `560×315` tag reproduces 16:9 (no change)
   and a GeoGebra `800×760` tag yields its true ratio.

## Non-goals

- No manual width/height fields in the editor UI — dimensions are auto-captured
  from the paste only.
- No ratio clamping (GeoGebra/YouTube dimensions are already sane).
- No parsing dimensions out of a bare GeoGebra URL's `/width/…/height/…` path —
  that is provider-specific; generic = `<iframe>` attributes only. A bare-URL
  paste therefore falls back to 16:9.
- No change to the **Video element** (`VideoElement`); it keeps its own 16:9
  rendering.

## Capture: `parse_iframe_dimensions`

New pure helper in `courses/embed.py`:

```
parse_iframe_dimensions(raw: str) -> tuple[int | None, int | None]
```

It reuses the existing `_IframeCollector` HTML parser to read the **first**
`<iframe>`'s `width` and `height` **attributes**:

- Strip a trailing `px` (case-insensitive) and surrounding whitespace, then parse
  an integer. `"800px"` → `800`, `"800"` → `800`.
- A value that is empty, `%`-suffixed, non-numeric, or a non-integer numeric
  string (e.g. `"800.5"` — `int("800.5")` raises → treated as unparseable), zero,
  or negative → `None` for that dimension.
- **Upper bound:** a value greater than `2147483647` (the `PositiveIntegerField`
  ceiling) → `None`. This is load-bearing, not cosmetic: `width`/`height` are not
  form fields, so `ModelForm._post_clean` does not run `full_clean` on them and
  the field's `MaxValueValidator` never fires — an unbounded pasted value would
  reach the DB and raise "integer out of range" (a 500) on save. Capping here
  degrades an absurd paste to the 16:9 fallback instead.
- No `<iframe>` in the input (a plain URL), more than one `<iframe>`, or a parse
  failure → `(None, None)`.

It returns `(width, height)` only as read; it does not decide storage — the form
does (below). Like the rest of `embed.py`, it never raises on arbitrary input.

`extract_embed_url`'s signature is unchanged — `parse_iframe_dimensions` is a
separate function, so the import path and its callers are untouched by capture.

## Model: `IframeElement.width` / `.height`

Add two fields to `IframeElement` (`courses/models.py`):

```
width = models.PositiveIntegerField(null=True, blank=True)
height = models.PositiveIntegerField(null=True, blank=True)
```

Plus a schema migration. `null` means "unknown → use the fallback ratio." The
form only ever stores a positive pair or leaves both null; a hand-authored or
legacy import archive could in principle set just one or a `0` (see Round-trip),
which the render guard tolerates by falling back to 16:9. A new `courses`
migration follows the current head.

## Form: capture point and the edit rule

Capture happens in `IframeElementForm.clean_url` (`courses/element_forms.py`) —
the same method that already calls `extract_embed_url`:

```python
def clean_url(self):
    raw = self.cleaned_data.get("url", "")
    url = extract_embed_url(raw)
    width, height = parse_iframe_dimensions(raw)
    if width and height:          # both usable → capture as a pair
        self.instance.width = width
        self.instance.height = height
    return url
```

**Edit rule (load-bearing):** dimensions are updated **only when the paste
provides both a usable numeric width and height** — i.e. a full `<iframe>`. A
plain-URL input leaves the stored dimensions **unchanged**. This matters because
re-opening an element to edit its title shows the canonical URL (a plain URL,
no tag) in the field; without this rule a title-only save would wipe a captured
ratio. Consequence: changing an existing element to a *different* bare URL keeps
the old dimensions (a rare edge, low harm — the author can paste the new full
`<iframe>` to refresh them).

## Render: dynamic aspect ratio with 16:9 fallback

Rename the CSS wrapper class from `.embed-16x9` to `.embed-frame` (the class no
longer always means 16:9). `.embed-frame` keeps `aspect-ratio: 16 / 9` as its
**default**; the template overrides it inline when dimensions are known.

`templates/courses/elements/iframeelement.html`:

```html
<div class="el el--iframe">
  <div class="embed-frame"{% if el.width and el.height %} style="aspect-ratio: {{ el.width }} / {{ el.height }}"{% endif %}>
    {% comment %}referrerpolicy: send the page origin to the embed provider; Django's
    default Referrer-Policy: same-origin would otherwise strip the Referer cross-origin.{% endcomment %}
    <iframe src="{{ el.url }}" loading="lazy"
            referrerpolicy="strict-origin-when-cross-origin"
            title="{{ el.title|default:_('embedded content') }}"></iframe>
  </div>
</div>
```

The existing `{% comment %}…referrerpolicy…{% endcomment %}` block is preserved
verbatim (it is load-bearing — do not drop it when rewriting the template).

The iframe stays absolutely positioned filling the wrapper, so the wrapper's
aspect-ratio governs. `courses.css` is updated so `.embed-frame` replaces
`.embed-16x9` (identical rules — the wrapper's default `aspect-ratio: 16 / 9`
and the `> iframe` absolute-fill — just a new name). The shared
`.el--video iframe, .el--iframe iframe { … aspect-ratio: 16 / 9 }` rule is left
untouched: the `.el--iframe iframe` is absolutely positioned and sized 100%×100%
by the wrapper, so its own `aspect-ratio` is inert there — no reason to split the
shared selector. Only `courses.css` (the definition) and `iframeelement.html`
(the usage) reference `.embed-16x9`, so the rename is self-contained.

The adjacent `courses.css` comment ("Responsive embed (#13): 16:9 wrapper, ignore
pasted width/height") is now false and must be updated to describe the new
behavior: a responsive wrapper that uses the pasted aspect ratio when known and
falls back to 16:9.

## Round-trip: course export / import

So an exported worksheet keeps its ratio on re-import, `width`/`height` join the
iframe transfer payload. The transfer format is versioned
(`courses/transfer/schema.py :: FORMAT_VERSION`, currently `1`; the importer
rejects archives with `format_version > FORMAT_VERSION` and accepts `<=`).

- **Bump `FORMAT_VERSION` to `2`.** New exports declare version 2; an older libli
  (still on version 1) will cleanly reject a version-2 archive via the existing
  version check rather than on an unexpected-key error. Two existing assertions
  hard-code version 1 and MUST be updated to `2` as part of this change:
  `tests/test_transfer_schema.py` (`assert FORMAT_VERSION == 1`) and
  `tests/test_transfer_export.py` (`assert manifest["format_version"] == 1`).
  Audit `tests/test_transfer_archive.py`'s `make_manifest` default too (it stays
  valid, but review it).
- **Export** (`courses/transfer/export.py :: _ser_iframe`) emits `width` and
  `height` for each iframe element (the model values, `null` when unknown).
- **Import validation** (`courses/transfer/payloads.py :: _val_iframe`): accept
  `width`/`height` as **optional** keys. `url`/`title` are required as today;
  `width`/`height` are validated with the existing `check_int_or_null(value, what)`
  when present. Because `schema.py` offers only the strict `_exact_keys` helper,
  inline the required-plus-optional check in `_val_iframe` (do NOT add a shared
  helper for a single call site): require `{url, title}`, allow `{width, height}`,
  reject any other key. **Then `data.setdefault("width", None)` and
  `data.setdefault("height", None)`** so the validated dict always carries both
  keys — this is what keeps a version-1 archive (which has neither) importable and
  prevents a `KeyError` downstream (see Import construction). Accepted asymmetry:
  `check_int_or_null` permits `0` and permits one dimension set while the other is
  null — looser than the capture-side "positive pair or neither" invariant. This
  is left as-is rather than adding bespoke validation: the render guard
  (`{% if el.width and el.height %}`) treats `0` and a lone dimension as falsy and
  falls back to 16:9, so no bad render results.
- **Import construction** (`courses/transfer/importer.py :: _build_iframe`): set
  the imported `IframeElement.width`/`.height` from `data["width"]`/`data["height"]`
  — safe because `_val_iframe`'s `setdefault` above guarantees both keys exist on
  the validated dict (so no `KeyError` on a legacy version-1 archive, which would
  otherwise escape the importer's `ValidationError`-only handler as a 500).

## Testing

TDD throughout.

- `tests` for `parse_iframe_dimensions`: `width="800px" height="760px"` → `(800,
  760)`; bare integers → parsed; `%`/missing/zero/negative/non-integer
  (`"800.5"`)/non-numeric → `None` for that side; a value `> 2147483647` → `None`
  (upper bound); a plain URL and a no-`<iframe>` snippet → `(None, None)`; the real
  user-provided GeoGebra tag → `(800, 760)`.
- Form tests: pasting the full GeoGebra `<iframe>` stores `width=800, height=760`;
  a subsequent plain-URL (title-only) save leaves them unchanged; **re-pasting a
  different full `<iframe>` overwrites the stored dimensions**; a fresh bare-URL
  paste leaves them `None`; **an oversized paste (`width="9999999999px"`)
  degrades to the 16:9 fallback and saves without a 500** (guards the I3 bound).
- Render test: an element with `width`/`height` renders the wrapper with
  `style="aspect-ratio: 800 / 760"`; an element without renders `.embed-frame`
  and no inline aspect-ratio (16:9 fallback).
- Transfer tests: round-trip export → re-import of an iframe with `width`/`height`
  preserves the dimensions; a version-1 archive without the keys still imports
  (dimensions `None`, no `KeyError`); and a payload with a single dimension or a
  `0` still imports and renders as the 16:9 fallback (the accepted asymmetry).
  Existing `FORMAT_VERSION`/`format_version` assertions updated to `2` (above).

## Delivery

This is a direct follow-up to the GeoGebra canonicalization work (same element,
same files: `embed.py`, `iframeelement.html`, `IframeElement`, the transfer
module) and PR #69 is still open, so it is built **on the same branch
(`geogebra-embed-canonicalization`) and extends PR #69** — avoiding conflicts
with the unmerged canonicalization changes and keeping the related embed
improvements together.
