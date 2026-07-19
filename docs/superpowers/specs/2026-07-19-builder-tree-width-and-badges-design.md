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

**Badge classes.** The unit badge keeps its existing `tree__badge tree__badge--unit`
classes (the `--unit` modifier is what carries `color: var(--accent)`, so it must stay
for the colour to remain unchanged). Additionally, **only when `unit_type` is
non-empty**, append a per-type modifier — `tree__badge--lesson` or
`tree__badge--quiz` — so the template stays declarative and a future colour split is a
one-line CSS change. Gate this modifier on a non-empty `unit_type` (e.g. inside the
same branch that emits the L/Q letter) so the defensive fallback path never renders a
malformed empty modifier (`tree__badge--`). **No colour split ships now** — no CSS is
added for `--lesson`/`--quiz`; both continue to inherit the `--unit` accent colour.
The fallback (empty `unit_type`) render reproduces **today's** badge markup exactly:
classes `tree__badge tree__badge--unit`, text `get_kind_display`, and **no `title`
attribute** — the whole L/Q-letter + tooltip + per-type modifier is one branch gated
on a non-empty `unit_type`, and the else branch emits neither the letter nor the
tooltip (so no stray `title=""` from an empty `get_unit_type_display`).

### 2. Column ratio `1fr 1fr` → `2fr 1fr`

File: `courses/static/courses/css/builder.css`.

- `.builder { grid-template-columns: 2fr 1fr; }` — the tree gets two-thirds of the
  width, the panel one-third.
- The existing mobile breakpoint (`@media (max-width: 720px) { grid-template-columns:
  1fr; }`) is untouched, so small screens stay single-column.
- In the now-narrower panel, the four ghost buttons must stack **one per line**
  rather than sitting side-by-side. The panel's direct children already get vertical
  rhythm via `.builder__panel .panel > * + * { margin-top: ... }`, but the `<a
  class="btn">` links are inline-block and flow horizontally until they wrap.
- **Scope the change to the empty/course state only.** The inner `.panel` element is
  shared by all three panel renders — `_course_panel.html`, `_node_panel.html`, and
  `_unit_panel.html` — but only the course render (shown when no node is selected) is
  the "nearly empty, buttons side-by-side" case. The course render is uniquely tagged
  `<div class="panel" data-panel-for="course">`; the node and unit renders carry
  `data-panel-for="{{ node.pk }}"` instead. So target exactly
  **`.builder__panel .panel[data-panel-for="course"]`** and make *that* selector a
  flex column (`display: flex; flex-direction: column; align-items: flex-start`). Its
  direct children are the `<a class="btn">` links **plus** the `<h2>` course title and
  the `<p class="panel__meta">` line; under `align-items: flex-start` all of these
  shrink-wrap to content width and each occupies its own line — this is intended
  (the heading and meta no longer span the full panel, which is fine). The four
  buttons stacking one-per-line is the goal; the existing owl-selector top-margins
  keep working as the inter-item gap.
- **Do not** apply flex to the bare `.builder__panel .panel` (would regress the unit
  panel — see below) nor to `.builder__panel` (the grid cell, whose only child is the
  single `.panel`, so flex there would not stack the grandchild buttons and the fix
  would silently no-op).
- **Regression to avoid:** the unit panel's `.unit-summary`
  (`display: grid; grid-template-columns: auto 1fr`), `.element-list` (`display:
  grid`), and `.panel__seam` rely on occupying the full panel width. An unscoped
  flex-column with `align-items: flex-start` would shrink those to content width and
  break `.element-list__summary`'s ellipsis truncation. Scoping to
  `[data-panel-for="course"]` keeps the unit/node panels untouched.

### 3. Long titles truncate instead of wrap

Files: `courses/static/courses/css/builder.css` + `templates/courses/manage/_tree_node.html`.

- `.tree__title` gains `min-width: 0; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis;`. `min-width: 0` is required for a flex item to be allowed
  to shrink below its content width so `text-overflow` can engage. `.tree__title` is a
  `<button>`; `text-overflow` needs a block-container box, so if the ellipsis fails to
  engage in testing, add `display: block` (it is already `flex: 1` inside the flex row,
  which combined with `min-width: 0` is normally sufficient). The one-line-truncation
  check in visual verification is the guard here.
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

- **Template rendering test** (extends the existing builder/tree template tests).
  **Scope every assertion to the badge `<span>`**, not the whole row — the title
  button also gains a `title="..."` attribute in edit #3, so a row-wide grep for
  `title="Lesson"` or for the letter could false-pass. Parse/isolate the
  `.tree__badge` element (e.g. via the test's HTML parser or a regex anchored to the
  badge class) and assert against its text and its `title` attribute specifically.
  Use fixture unit titles that are **not** "Lesson"/"Quiz" (e.g. "Intro", "Chapter
  test") so a title collision can't mask a wrong assertion.
  - a `lesson` unit row: badge span text is `L`, badge `title` is `Lesson` (default
    locale);
  - a `quiz` unit row: badge span text is `Q`, badge `title` is `Quiz`;
  - a container node (e.g. chapter) still renders its word badge (`Chapter`);
  - **Non-translation of the letter:** render under `pl` and confirm the badge span
    text is still `L`/`Q` (the letters are hardcoded, not run through gettext).
  - **Tooltip localization:** assert on the **lesson** row — under `pl` the lesson
    badge `title` becomes `Lekcja`. (The quiz tooltip is "Quiz" in both EN and PL per
    the model choices, so only the lesson tooltip visibly changes between locales;
    don't assert a locale change on the quiz row.)
  - **Falsification (per the repo "falsify tests, don't run them" convention),
    targeting the actual production behavior — each bullet must be *achievable* (can
    be made to fail by a real production change):**
    - the test goes RED if the L/Q letter mapping is broken or swapped (e.g. lesson→Q),
      pinning the mapping itself — not just its presence;
    - the test goes RED if a unit badge falls back to `get_kind_display` ("Unit").
    - Note: do **not** frame "letter is not translated" as a falsification — the
      letters `L`/`Q` have no msgid in the catalog, so wrapping them in `{% trans %}`
      is a behavioral no-op and such a test could never go red (the "vacuous test"
      trap). Cross-locale identity is instead pinned by the **positive** assertion
      above (badge span text is still `L`/`Q` when rendered under `pl`).
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
  prose that describes the "Unit" tree badge. **Only if such prose exists**, update it
  to describe the L/Q (lesson/quiz) scheme (EN + PL where a PL variant exists). An
  empty grep result is an acceptable outcome — the builder help currently describes
  adding units via the "+ Lesson"/"+ Quiz" chips and does not name the tree badge
  letter, so this step may legitimately be a no-op. Do not invent new badge prose
  where none existed.
