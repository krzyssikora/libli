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
- A value that is empty, `%`-suffixed, non-numeric, zero, or negative → `None`
  for that dimension.
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

Plus a schema migration. `null` means "unknown → use the fallback ratio." In
practice they are set both-or-neither (the form only stores a pair). A new
`courses` migration follows the current head.

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
    <iframe src="{{ el.url }}" loading="lazy"
            referrerpolicy="strict-origin-when-cross-origin"
            title="{{ el.title|default:_('embedded content') }}"></iframe>
  </div>
</div>
```

The iframe stays absolutely positioned filling the wrapper, so the wrapper's
aspect-ratio governs. `courses.css` is updated so `.embed-frame` replaces
`.embed-16x9` (identical rules — the wrapper's default `aspect-ratio: 16 / 9`
and the `> iframe` absolute-fill — just a new name). The shared
`.el--video iframe, .el--iframe iframe { … aspect-ratio: 16 / 9 }` rule is left
untouched: the `.el--iframe iframe` is absolutely positioned and sized 100%×100%
by the wrapper, so its own `aspect-ratio` is inert there — no reason to split the
shared selector. Only `courses.css` (the definition) and `iframeelement.html`
(the usage) reference `.embed-16x9`, so the rename is self-contained.

## Round-trip: course export / import

So an exported worksheet keeps its ratio on re-import, `width`/`height` join the
iframe transfer payload. The transfer format is versioned
(`courses/transfer/schema.py :: FORMAT_VERSION`, currently `1`; the importer
rejects archives with `format_version > FORMAT_VERSION` and accepts `<=`).

- **Bump `FORMAT_VERSION` to `2`.** New exports declare version 2; an older libli
  (still on version 1) will cleanly reject a version-2 archive via the existing
  version check rather than on an unexpected-key error.
- **Export** (`courses/transfer/export.py` document builder) emits `width` and
  `height` for each iframe element (the model values, `null` when unknown).
- **Import validation** (`courses/transfer/payloads.py :: _val_iframe`): accept
  `width`/`height` as **optional** keys — `url` and `title` required as today,
  `width`/`height` validated with the existing
  `check_int_or_null(value, what)` when present and defaulted to `None` when
  absent. This keeps **backward compatibility**: a version-1 archive (no
  `width`/`height`) still validates. This replaces the strict
  `_exact_keys(data, ["url", "title"], …)` call for iframe with a required-plus-
  optional key check (required `{url, title}`, optional `{width, height}`, no
  other keys allowed).
- **Import construction** (`courses/transfer/importer.py`): set the imported
  `IframeElement.width`/`.height` from the (possibly `None`) payload values.

## Testing

TDD throughout.

- `tests` for `parse_iframe_dimensions`: `width="800px" height="760px"` → `(800,
  760)`; bare integers → parsed; `%`/missing/zero/negative/non-numeric → `None`
  for that side; a plain URL and a no-`<iframe>` snippet → `(None, None)`; the
  real user-provided GeoGebra tag → `(800, 760)`.
- Form tests: pasting the full GeoGebra `<iframe>` stores `width=800, height=760`;
  a subsequent plain-URL (title-only) save leaves them unchanged; a fresh
  bare-URL paste leaves them `None`.
- Render test: an element with `width`/`height` renders the wrapper with
  `style="aspect-ratio: 800 / 760"`; an element without renders `.embed-frame`
  and no inline aspect-ratio (16:9 fallback).
- Transfer round-trip test: export a course whose iframe has `width`/`height`,
  re-import, assert the dimensions survive; and a version-1 archive without the
  keys still imports (dimensions `None`).

## Delivery

This is a direct follow-up to the GeoGebra canonicalization work (same element,
same files: `embed.py`, `iframeelement.html`, `IframeElement`, the transfer
module) and PR #69 is still open, so it is built **on the same branch
(`geogebra-embed-canonicalization`) and extends PR #69** — avoiding conflicts
with the unmerged canonicalization changes and keeping the related embed
improvements together.
