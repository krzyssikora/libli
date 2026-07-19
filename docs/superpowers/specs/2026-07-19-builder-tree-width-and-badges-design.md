# Tidy the builder tree — reclaim width & sharpen unit badges

## Purpose

In the course builder view (`courses/manage/builder.html`), the course tree sits in
the left column and a detail panel in the right; the two columns are equal width
(`grid-template-columns: 1fr 1fr`). Three problems compound to make the tree read
poorly, most visibly in Polish:

1. Each unit row shows a kind badge rendered from `get_kind_display()` — for a unit
   that is **"Unit" / "jednostka"**. The Polish word is long; between it and the
   6–7 action icons in the row's control cluster, the title button gets squeezed and
   **wraps to a second line**, roughly doubling the tree's height.
2. The badge is also **uninformative**: every unit already carries a `unit_type`
   (`lesson` or `quiz`), but the badge never shows which — it just says "Unit".
3. The right panel, when no node is selected, holds only the course title and four
   ghost buttons, so half the viewport width sits **nearly empty** while the tree is
   cramped.

This change reclaims horizontal room for the tree and makes the unit badge both
shorter and more informative, with no change to builder behaviour or data.

Scope is deliberately narrow: presentation only (one template partial + one CSS
file), plus a docs touch-up and tests. No model, view, migration, or JS changes.

## Architecture / components

Three coordinated edits, each independent and low-risk:

### 1. Unit badge `Unit` / `jednostka` → `L` / `Q`

File: `templates/courses/manage/_tree_node.html` (the `.tree__badge` span).

- For `node.kind == "unit"`, render a single **hardcoded** letter derived from
  `node.unit_type`: `lesson → L`, `quiz → Q`. The letters are **not** run through
  `{% trans %}` / gettext — they are identical in every language, per the approved
  design.
- Add a translated tooltip: `title="{{ node.get_unit_type_display }}"`, so hovering
  the badge reveals the full word in the active language (EN "Lesson"/"Quiz",
  PL "Lekcja"/"Quiz"). `get_unit_type_display` is Django's auto-generated,
  already-translatable accessor for the `unit_type` choices.
- Non-unit nodes (Part / Chapter / Section) keep their current word badge
  (`get_kind_display`) unchanged.
- **Defensive fallback:** if a unit ever had an empty `unit_type` (it cannot in
  practice — `ContentNode.clean()` raises "Units require a unit_type." — but the DB
  column is `null=True`), fall back to the existing `get_kind_display` word so the
  badge never renders blank.
- Badge **colour is unchanged**: both L and Q keep the current
  `.tree__badge--unit { color: var(--accent); }`.

Because the letter depends on `unit_type` (lesson vs quiz), a per-`unit_type`
modifier class is added to the badge span so the template stays declarative and any
future colour split is a one-line CSS change — but no colour split ships now.

### 2. Column ratio `1fr 1fr` → `2fr 1fr`

File: `courses/static/courses/css/builder.css`.

- `.builder { grid-template-columns: 2fr 1fr; }` — the tree gets two-thirds of the
  width, the panel one-third.
- The existing mobile breakpoint (`@media (max-width: 720px) { grid-template-columns:
  1fr; }`) is untouched, so small screens stay single-column.
- In the now-narrower panel, the four ghost buttons must stack **one per line**
  rather than sitting side-by-side. The panel's direct children already get vertical
  rhythm via `.builder__panel .panel > * + * { margin-top: ... }`, but the `<a
  class="btn">` links are inline-block and flow horizontally until they wrap. Make
  the panel a **flex column** (`display: flex; flex-direction: column;
  align-items: flex-start`) so each button occupies its own line at its natural
  width. This keeps the existing owl-selector top-margins working as the inter-item
  gap.

### 3. Long titles truncate instead of wrap

Files: `courses/static/courses/css/builder.css` + `templates/courses/manage/_tree_node.html`.

- `.tree__title` gains `min-width: 0; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis;`. `min-width: 0` is required for a flex item to be allowed
  to shrink below its content width so `text-overflow` can engage.
- Add `title="{{ node.title }}"` to the title button so the full name is available on
  hover when it is truncated.

Belt-and-suspenders with edits 1 and 2: even after the badge shrinks and the column
widens, a pathologically long unit title now truncates on one line instead of
wrapping.

## Data flow

Purely render-time; no runtime data path changes.

- `ContentNode.kind` and `ContentNode.unit_type` (existing fields) are read in the
  template to choose the badge letter/word and tooltip. Both are already loaded for
  every node the builder renders — no new queries.
- `get_unit_type_display` and `get_kind_display` are Django model accessors already
  available on the node; the template already calls `get_kind_display`.
- CSS changes are static-file only; the builder page loads `builder.css` via
  `{% block extra_css %}` and no other page reuses these builder-scoped selectors.

## Error handling

- **Missing `unit_type` on a unit:** template branch falls back to `get_kind_display`
  (the current "Unit"/"jednostka" word) rather than emitting an empty badge. This is
  a defensive-only path; model validation forbids the state.
- **Non-unit nodes:** unaffected — the L/Q logic is gated on `node.kind == "unit"`,
  so Part/Chapter/Section render exactly as before.
- **No new failure surfaces:** no new views, queries, forms, or migrations; nothing
  can 500 that could not before. CSS is progressive — the ellipsis/nowrap rules
  degrade gracefully and the grid ratio has a mobile fallback.

## Testing

- **Template rendering test** (extends the existing builder/tree template tests):
  - a `lesson` unit row renders badge text `L` and `title="Lesson"` (default locale);
  - a `quiz` unit row renders badge text `Q` and `title="Quiz"`;
  - a container node (e.g. chapter) still renders its word badge (`Chapter`);
  - assert the L/Q letters are present **regardless of active language** (render under
    `pl` and confirm the badge letter is still `L`/`Q`, i.e. not translated), while the
    tooltip does localize.
  - Falsify the test per the repo convention: confirm it goes RED if the badge falls
    back to `get_kind_display` for a unit.
- **Visual verification** (repo convention for styling changes): drive the builder
  page with Playwright and screenshot **light and dark**, confirming (a) the tree
  column is visibly wider than the panel (~2:1), (b) the four panel buttons stack one
  per line, and (c) a deliberately long unit title truncates with an ellipsis on a
  single row. Self-critique the screenshots before shipping.
- **Regression guard:** run the existing courses/manage template + view test module
  to confirm nothing that asserted on the old "Unit" badge text breaks; update any
  such assertion to the new L/Q scheme.

## Docs

- Grep the in-app help pages (`docs/help/**`) and any builder-facing help topic for
  descriptions of the "Unit" tree badge; update prose that names the old badge to
  describe the L/Q (lesson/quiz) scheme. EN + PL where a PL variant exists.
