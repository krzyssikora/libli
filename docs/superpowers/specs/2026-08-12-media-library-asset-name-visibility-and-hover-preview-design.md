# Media library: asset name visibility and hover preview

Date: 2026-08-12

## Purpose

In the course media manager grid, assets whose names differ only in a numeric
suffix (`przykladowa_parabola_0_1.png`, `przykladowa_parabola_0_2.png`) cannot
be told apart. Two independent causes, plus one irritant:

1. **The name spills out of the card.** `.asset-dname`
   (`courses/static/courses/css/editor.css:719-720`) carries no truncation rule
   at all — no `overflow`, no `text-overflow`, no `white-space`. It is a flex
   item inside `.asset-names` (`flex-wrap: wrap`), and a flex item defaults to
   `min-width: auto`, which refuses to shrink below the content's min-content
   width. A filename offers no break opportunity, so min-content is the entire
   string. The span therefore overflows its card and the neighbouring card's
   `--surface-raised` background paints over the overflow. The last card in a
   row shows its full name because nothing sits to its right — that asymmetry is
   the tell. The text is not being truncated; it is being covered.

2. **The thumbnail crops.** `.asset-thumb` uses `object-fit: cover` at
   `aspect-ratio: 4 / 3` (`editor.css:360-365`). When the only difference
   between two images lies outside that crop, the thumbnails are identical
   pixel-for-pixel and no name fix can help.

3. **The name is printed twice.** `_asset_cell.html:12` renders
   `asset.display_name` and `:15` renders `asset.original_filename`, but
   `display_name` is `self.name or self.original_filename`
   (`courses/models.py:754-756`). For any asset that was never renamed the card
   prints the same string on both lines.

**Success criteria.** A user scanning a row of similarly-named assets can (a)
read enough of each name to tell them apart without hovering, (b) get the exact
full name on hover, and (c) see a crop-free enlargement of any image without
leaving the grid.

**Scope.** The manager grid cell
(`templates/courses/manage/media/_asset_cell.html`) and the CSS it shares with
the picker. Out of scope: thumbnail generation, the picker's own `.asset-name`
cell (`_picker_grid.html`), and the `cursor: pointer` on a non-clickable
manager cell.

## Architecture / components

Four components, each independently testable.

### 1. `middle_truncate` template filter

New filter in `courses/templatetags/courses_manage_extras.py` (the existing home
for manage-side filters — `register = template.Library()` at `:26`).

Signature: `middle_truncate(value, budget=42)` → `str`.

- Returns `value` unchanged when `len(value) <= budget`.
- Otherwise returns `head + "…" + tail`, where `tail` is the **last 14
  characters** and `head` is taken from the front so that the total rendered
  length (including the ellipsis) equals `budget`.
- The budget of 42 is three lines at roughly 14 characters per line in the
  128 px minimum grid column; a 14-character tail covers a numeric suffix plus a
  four-character extension with room to spare.
- Pure string arithmetic on character counts. Deterministic and unit-testable;
  measuring rendered text width in JS is neither.

### 2. Card markup — `_asset_cell.html`

- `:12` gains `title="{{ asset.display_name }}"` and renders
  `{{ asset.display_name|middle_truncate }}`. The `title` carries the **full,
  untruncated** name, so the tooltip is a superset of what is displayed.
- `:15` (`.asset-fname`) is wrapped in a condition so it renders only when
  `asset.original_filename != asset.display_name`.

### 3. Card CSS — `editor.css`

- `.asset-dname` gains `min-width: 0` and `overflow-wrap: anywhere` so the name
  wraps inside the card instead of spilling out of it, plus
  `display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3;
  overflow: hidden` as the visual backstop for a within-budget name that still
  wraps past three lines in a narrow column.
- `.asset-names` changes from `align-items: center` to `align-items: start`, so
  the ✎ button stays on the first line rather than floating to the vertical
  middle of a three-line name.
- New `.asset-preview` overlay styles (see below).

### 4. Hover preview — new JS module

One reused overlay element for the whole grid, not one per card. Lives in
`courses/static/courses/js/` alongside `media_picker.js`, wired from the media
manager page.

- **Trigger.** `mouseenter` on `.asset-cell`, opening after a ~250 ms dwell so
  that sweeping the pointer across a row does not strobe. `mouseleave` hides it
  immediately and cancels a pending open.
- **Keyboard.** The manager cell is a `div` and is not focusable, and giving
  each card a tab stop would add a fourth to the three buttons it already holds.
  The overlay therefore opens on `focusin` anywhere within the cell — so tabbing
  to ✎ / ⇄ / 🗑 surfaces the preview at no extra cost — and closes on `focusout`
  and on Escape.
- **Content.** The image at `object-fit: contain`, capped at about 320 px, with
  the full filename beneath it. `contain` is the substantive part: it undoes the
  4:3 `cover` crop that can hide the differing region entirely.
- **Position.** Appended to the media-manager root, `position: fixed`, anchored
  beside the card and flipped when it would cross the viewport edge. A CSS-only
  `:hover` child cannot flip and would be clipped off-screen on the last column.
- **Images only.** A video cell is a ▶ glyph (`_asset_cell.html:9`) with no
  image to enlarge; `data-kind` on the cell root (`:2`) distinguishes them.
- **No new request.** The overlay reuses the `data-url` the thumbnail already
  fetched, so the browser serves it from cache.

## Data flow

**Render.** `manage_media` view → `_asset_grid.html` → one `_asset_cell.html`
per asset. `asset.display_name` (model property, `courses/models.py:754`) flows
into three places on the card: the `title` attribute (full), the visible span
body (via `middle_truncate`), and the pre-existing `data-name` attribute on the
cell root (`:3`, full, already present). `asset.original_filename` flows into
`.asset-fname` only when it differs from `display_name`.

**Hover.** `mouseenter` on `.asset-cell` → dwell timer → read `data-kind`,
`data-url`, `data-name` from the cell root → populate and position the single
overlay → show. `mouseleave` / `focusout` / Escape / scroll → hide.

**Rename.** The pencil swaps `[data-asset-dname]` for an input
(`media_picker.js:335-339`) and reinserts the **same span node** on cancel
(`:344`), on a non-200 (`:351`), and on network failure (`:367`) — so a
server-rendered `title` attribute survives every one of those paths. The
success path replaces the whole cell with freshly rendered server HTML
(`:363`), which carries the attribute natively. No JS change is needed to keep
the tooltip correct.

## Error handling

- **Overlay outlives its anchor.** The overlay is appended outside `.asset-grid`,
  so it survives events that destroy the cell that opened it: the debounced
  filter swaps the entire grid, and replace and rename each swap a single cell.
  The teardown keys on the anchor **node** — a selector-keyed guard is a no-op
  when the event is a node replacement. On any swap, if the anchor node is no
  longer connected to the document, the overlay closes.
- **Scroll.** A `fixed`-positioned overlay anchored to a moving card would
  detach visually, so scroll closes it rather than repositioning it.
- **Missing or broken image.** If the overlay's image fails to load, the overlay
  shows the filename alone rather than an empty box.
- **Truncation degenerate inputs.** `middle_truncate` handles a name shorter
  than the tail length, a name with no extension, and a non-ASCII name without
  raising; it never returns a string longer than `budget`.
- **No JS.** With scripts disabled, the wrapped name, the middle truncation, and
  the `title` tooltip all still work — only the preview is lost.

## Testing

**Unit — `middle_truncate`.** Short name returned unchanged; over-budget name
keeps both the extension and the tail; the exact boundary length; a name with no
extension; a non-ASCII name; a name shorter than the tail length.

**Django client — `_asset_cell.html`.** `title=` present on `.asset-dname` and
carrying the full name even when the visible text is truncated; `.asset-fname`
present when `original_filename` differs from `display_name` and absent when
they match.

**e2e — measured, not eyeballed.** A CSS assertion made with the rule in place
proves nothing, so each of these is falsified against a targeted mutant before
it is believed:

| Test | Mutant that must turn it red |
| --- | --- |
| At a 360 px viewport, `.asset-dname`'s bounding box stays inside its card's box | drop `min-width: 0` |
| Two similar assets render different visible title text | drop `min-width: 0` |
| A name past the budget shows head and tail, not head alone | off-by-one in `middle_truncate` |
| Hover opens the overlay with the right `src` and a box larger than the thumb | drop the `mouseenter` binding |
| `mouseleave`, Escape, and `focusout` each close it | drop each handler in turn |
| Focusing a card button opens it | drop the `focusin` binding |
| Filter-swapping the grid while the overlay is open closes it | drop the detach teardown |

`test_screenshots_light_and_dark` (`tests/test_e2e_media_manager.py:588`) is
refreshed — card height changes — and dark mode is judged on its own rather than
assumed to follow from light.

**Existing tests to repoint.** Suppressing the duplicate `.asset-fname` breaks
assertions that key on it. In those fixtures the asset carries no custom `name`,
so after a replace `display_name` falls back to the new `original_filename`, the
two match, and the secondary line is not rendered. Each moves to `.asset-dname`,
which always renders:

- `test_replace_swaps_the_cell_and_the_rendered_image` — `:136`
- `test_two_consecutive_replaces_both_succeed` — `:250`, `:259`
- `test_a_filter_swap_mid_flight_still_updates_the_cell` — `:309`
- `test_an_upload_after_filtering_lands_in_the_live_grid` — `:436`

`tests/test_media_manager.py` asserts on the response body rather than on a
selector, so it is unaffected.

**Constraint on any comment added to the cell template.**
`test_no_template_comment_leaks_into_the_asset_cell`
(`tests/test_media_manager.py:629`) rejects `{#`, `#}`, `{%`, `%}` in the
rendered body, so commentary in `_asset_cell.html` must be a single-line
`{# … #}` that Django strips.

## Consequences

Cards in a row grow to the tallest card, as they already do. Two or three title
lines is the expected range at the 128 px column minimum.
