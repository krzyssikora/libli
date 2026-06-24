# Builder & Editor Authoring-UX Polish — Design

**Date:** 2026-06-24
**Status:** Draft (brainstormed; pending user review)
**Type:** UX polish batch (course-authoring builder + unit editor). Not a roadmap phase — a focused improvement pass on existing Phase-1b surfaces, prompted by manual-testing friction found while exercising the Phase-3c-i quiz-review work.

## Goal

Make creating and authoring a **quiz** unit (and authoring in general) less confusing in the course builder / unit editor, and tidy two visual rough edges. Five small, independent improvements shipped as one spec → plan → build cycle.

> **Committed follow-up:** a per-course **structure / depth** feature is the agreed **next cycle, ahead of any new development** — see "Committed next cycle" at the end. The "Structure legend" idea raised during this brainstorm is deliberately folded into that cycle (it should reflect a course's *configured* levels, not a fixed four-level diagram).

## Background / current state (verified in code)

- **Content tree:** one `ContentNode` model, `kind ∈ {part, chapter, section, unit}` (`courses/models.py:97-101`), `unit_type ∈ {lesson, quiz}` (nullable; required on units, forbidden on non-units; `models.py:103-105,138-142`). `RANK = {part:0, chapter:1, section:2, unit:3}`. A child must be a strictly deeper kind than its parent (`courses/ordering.py:126-133`); `legal_child_kinds(None)` (top scope) allows all kinds, so **levels are skippable** and the same kind menu is available in every course (`differences.md` §"Course depth"). There is no per-course restriction yet — that is the committed next cycle.
- **Adding a unit:** the builder add-row (`templates/courses/manage/_add_affordance.html`) renders one `+ <Kind>` chip per legal child kind, a title input, and a hidden `unit_type=lesson` that is **always** sent. `node_add` (`courses/views_manage.py:199-240`) reads `kind` from the clicked button and `unit_type` from POST (honoured only when `kind=="unit"`), then calls `builder.add_node`. **Result: every new unit is created as a Lesson; there is no way to choose Quiz at add time.**
- **Changing a unit's type:** only via the editor's collapsed `<details class="unit-settings">` (`templates/courses/manage/editor/_unit_settings.html`) — title + `<select name="unit_type">` + obligatory + html_seed_js — POSTing to `node_rename` with `has_settings=1`, `ctx=editor` (`views_manage.py:244-297`, `builder.rename_node` with a `_UNSET` sentinel). Reaching it is: click unit name → open editor → expand Settings.
- **Add-element menu:** `templates/courses/manage/editor/_add_menu.html` — a `.typemenu` of 15 `.typecard` buttons in one flat grid. Icons are a `.ic` span holding an **emoji or a unicode glyph**. The 6 content types (text/image/video/iframe/math/html) and 9 question types are mixed. `editor.js:180-196` POSTs the clicked `data-add-type` to `element_add`, which whitelists all 14 type keys with **no unit-type gating** (`views_manage.py:788-820`). NOTE: `differences.md` §Unit lines 14-15 ("lesson allows all; quiz allows quiz elements only") is **deliberately not enforced** — by decision, any element type is allowed in either unit type (e.g. a shared image/passage a quiz question addresses); only marking differs. So this item is grouping only, not filtering.
- **Icons elsewhere:** the builder tree action buttons use a real **monochrome SVG sprite** — `<svg class="ic"><use href="#bi-grip"/></svg>` (`templates/courses/manage/_tree_node.html`), with `<symbol id="bi-…">` definitions currently inline in `templates/courses/manage/builder.html` (only `bi-up/down/grip/move/trash` exist today). A monochrome, theme-coloured icon system already exists in-repo; the element cards just don't use it.
- **Marking inputs:** `templates/courses/manage/editor/_marking_fields.html` renders bare Django widgets `{{ form.marking_mode }}`, `{{ form.max_attempts }}`, `{{ form.max_marks }}` (gated by `is_quiz`). These render with default/un-themed colours and are **illegible in dark mode** (light background, light text).

## Scope — five items

1. **Create a unit as Lesson or Quiz at add time** (builder).
2. **Change a unit's type from the editor header** (a visible Lesson/Quiz toggle), not only from collapsed Settings.
3. **Group the add-element menu** into Content vs Questions (all types stay available in both unit types).
4. **Unify the element-card icons** as monochrome SVG.
5. **Fix dark-mode legibility of the marking inputs.**

### Not in this batch

- **Per-course structure / depth config** ("a simple course shouldn't deal with the full depth"; restrict which kinds a course uses). → **Committed next cycle** (see end). This is considered higher-value than author skip-levels and is sequenced before any new development.
- **The "Structure" legend** — folded into the next cycle, where it can show the course's *configured* levels.
- **Inline (double-click) title editing** in the editor — a larger interaction (mobile fallback, inline save/validate, tree-title sync); deferred. Title editing stays in Settings.
- **Filtering / reordering the element menu by unit type** — by decision, all element types stay available in both lesson and quiz units; the menu is grouped, not filtered.
- **Quiz-level marking type ([A]/[N]/[R]) + question-compatibility prompt** (`differences.md` lines 41-48) — documented but not yet built; a separate feature, not this batch.

---

## Item 1 — Create a unit as Lesson or Quiz

**Behaviour:** wherever the add-row currently offers a single `+ Unit` chip, it instead offers **two chips: `+ Lesson` and `+ Quiz`**. Clicking either creates the unit of that type immediately, using the typed title. Higher levels (Part/Chapter/Section) are unaffected — only the `unit` kind splits into two type-specific chips.

**Why chips (not a toggle):** the add-row is already a row of stateless `+ <Kind>` action chips; two unit chips fit that pattern. One gesture ("type title → click `+ Quiz`") vs a stateful toggle that's easy to leave on the wrong setting — exactly the "it defaulted to Lesson" problem being fixed. A unit is almost always the only legal child at its level, so the row stays tidy (`+ Lesson  + Quiz`).

**Mechanism (design intent; exact wiring in the plan):**
- Drop the always-on hidden `unit_type=lesson`. Render the two unit chips so each carries its own `unit_type` (`lesson` / `quiz`); the non-unit kind chips are unchanged.
- `node_add` infers `kind=unit` when a unit-type chip is the submitter (a `unit_type` value arrived from a Lesson/Quiz button), otherwise uses the `kind` button value with `unit_type=None` — preserving the model invariant (units have a type; non-units don't).
- **No-JS correctness is required:** with JS off, clicking `+ Quiz` must create a *quiz*, not silently fall back to Lesson. The chosen mechanism (chip carries its `unit_type`; view infers `unit` kind from it) satisfies this with one submit button per submission. The async builder add-path (`data-op="add"` / `data-add-kind`) must carry the unit type for the two chips without regressing the optimistic add.
- **Overflow:** where `unit` appears in the `+…` overflow set (a parent that can contain a unit by skipping levels), both `+ Lesson` and `+ Quiz` appear there.

**Affected:** `_add_affordance.html`, the builder add JS, `views_manage.node_add`, possibly the `courses_manage_extras` kind-chip rendering. Labels reuse the existing translated `UnitType` choice labels.

**Tests:** view test — `+ Quiz` creates `unit_type="quiz"`; `+ Lesson` creates `lesson`; non-unit chips still create their kind with `unit_type=None`. e2e — a real click on `+ Quiz` produces a quiz unit (the quiz editor/marking path becomes available). No-JS path asserted at the view level.

---

## Item 2 — Change unit type from the editor header

**Behaviour:** the unit editor shows a compact **`Lesson · Quiz` segmented toggle in the header, next to the unit title**, reflecting the current type; clicking the inactive option switches it. The `<select name="unit_type">` is **removed from the Settings `<details>`** (no duplicate control); Settings keeps title, obligatory, and html_seed_js. Title editing stays in Settings (inline-title editing is out of scope).

**Mechanism:** a small form (segmented control = two buttons; the active type is current, clicking the other submits) reusing the existing `node_rename` path (a `has_settings`-style update of just `unit_type`, carrying the optimistic-concurrency `token`). Must be **no-JS correct** (a plain form submit switches the type and re-renders the editor). Switching is already supported today (Settings does it); this only makes it discoverable, and has no data risk — `unit_type` gates rendering/marking visibility, not question data.

**Affected:** the editor header template, `_unit_settings.html` (remove the type select), `views_manage.node_rename` (confirm it still accepts a type-only settings update), editor CSS for the segmented control (legible light + dark).

**Tests:** view test — a toggle POST flips `unit_type` and re-renders; Settings no longer contains a type select. e2e/screenshot — the toggle is visible in the header and reflects/changes type. Light + dark screenshot check.

---

## Item 3 — Group the add-element menu (Content vs Questions)

**Behaviour:** split the flat `.typemenu` into two labelled groups — **"Content"** (text, image, video, iframe, math, html) and **"Questions"** (the 9 question types) — separated by a labelled divider (a small per-group subheading; optionally a subtle background tint on the Questions group). **All 15 cards stay available in both lesson and quiz units** (decision: the `differences.md` §Unit lines 14-15 lesson/quiz element rule is deliberately not enforced; a quiz may use any element type, e.g. a shared image a question addresses). Fixed order (Content first). No filtering, no unit-type branching, no server change.

**Affected:** `_add_menu.html` (two `<div>` groups with `<p class="typemenu__group-label">` headings + a divider), `editor.css` (group headings; keep the existing `.typecard`). New strings: `{% trans "Content" %}`, `{% trans "Questions" %}` → PL.

**Tests:** render test — both group labels present; all 15 `data-add-type` cards still present, content cards under "Content", question cards under "Questions" (no card lost in the regroup). Light/dark screenshot check.

---

## Item 4 — Unify element-card icons as monochrome SVG

**Behaviour:** replace every `.ic` emoji/glyph in `_add_menu.html` with a **monochrome SVG** `<svg class="ic"><use href="#…"/></svg>`, matching the builder tree icons, so all element-card icons are one consistent, theme-coloured (`currentColor`) set. (Chosen over swapping to monochrome unicode glyphs: the SVG route matches the existing tree icons and is crisp across platforms.)

**Mechanism:**
- The icon **sprite** (the `<symbol id="bi-…">` block currently inline in `builder.html`) must be available on the **editor** page where the typecards render. Extract the sprite into a shared partial (e.g. `templates/courses/manage/_icon_sprite.html`) and include it on both the builder and editor pages (the editor already relies on `#bi-grip` etc. via the tree, so the sprite must reach it — confirm and consolidate).
- Add ~15 element-type `<symbol>` definitions (from the Bootstrap Icons set the project already vendors; pull the path data for each). **Suggested mapping** (final names chosen in the plan; substitute a small custom symbol where bi lacks a clean match, e.g. math): text→`bi-card-text`, image→`bi-image`, video→`bi-play-btn`, iframe→`bi-window`, math→`bi-calculator` (or custom ∑), html→`bi-code-slash`, single-choice→`bi-record-circle`, multiple-choice→`bi-check2-square`, short-text→`bi-input-cursor-text`, short-numeric→`bi-123`, fill-blank→`bi-input-cursor`, drag-the-words→`bi-hand-index`, match-pairs→`bi-link-45deg`, drag-to-image→`bi-bounding-box`, extended-response→`bi-pencil-square`.
- Reconcile `.ic` sizing: `.ic` is used both as an emoji span (`editor.css .typecard .ic { font-size: 1.2rem }`) and as an SVG (tree). Give the SVG `.ic` explicit width/height so the typecards render at the intended size, and `fill: currentColor` so the cards' `--text-secondary` / hover `--text-primary` colours apply (matching the existing card hover behaviour).

**Affected:** `_add_menu.html`, the extracted `_icon_sprite.html` (+ its includes), `editor.css` (`.ic` SVG sizing/fill).

**Tests:** render test — each typecard contains `<svg class="ic"><use href="#…"/>` and no emoji; the referenced symbol ids exist in the sprite. Screenshot (light + dark) — icons render monochrome and theme-coloured, consistent with tree icons.

---

## Item 5 — Dark-mode legibility of marking inputs

**Behaviour:** the `marking_mode` select and the `max_attempts` / `max_marks` inputs in `_marking_fields.html` adopt the editor's themed input appearance so they are clearly legible in dark mode (dark surface, light text), matching the other editor inputs.

**Mechanism (plan to confirm exact cause):** these inputs are bare Django widgets with no shared input class, so they miss whatever styling the other (legible) editor inputs get. Fix by either (a) applying the editor's standard input class to these widgets in the form, or (b) a CSS rule scoped to `.el-editor__marking-fields select, .el-editor__marking-fields input` using the input design tokens (surface/border/text) plus an appropriate `color-scheme` so the native number spinner matches. Prefer whichever matches how the other editor inputs are already styled.

**Affected:** `_marking_fields.html` and/or `element_forms.py` (the QuestionElement-base marking widgets) and `editor.css`. CSS-/markup-only; no behaviour change.

**Tests:** screenshot (dark mode) — the three controls show legible contrast; light mode unchanged. (Primarily visual; add a render assertion if the class-based fix is chosen.)

---

## Global constraints

- **Tooling:** `uv run ruff`/`pytest`/`python` (not on PATH bare); `ruff check --fix && ruff format` per task (CI runs `ruff format --check`).
- **i18n:** every new user-facing string wrapped and given a PL translation in `locale/pl/LC_MESSAGES/django.po`; recompile `.mo`; clear any `#, fuzzy`. New strings: "Content", "Questions" (+ any toggle labels); Lesson/Quiz reuse existing translated `UnitType` labels.
- **No-JS correctness:** the builder add (Item 1) and the editor type toggle (Item 2) must work with JavaScript disabled.
- **Dark mode:** all new/changed UI verified legible in light **and** dark via Playwright screenshots (delete-after-review harness) before shipping.
- **Multi-line template comments** use `{% comment %}` (never multi-line `{# #}`).
- **Design system:** bespoke token-driven CSS — reuse existing tokens (`--surface-*`, `--text-*`, `--border-*`, `--primary*`, `--space-*`, `--radius-*`); no new colour literals.

## Testing strategy

Mostly template/render + view tests (Items 1–3), plus a builder e2e for Item 1 (real click creating a quiz unit) and an editor e2e/screenshot for Item 2. Items 4 and 5 are primarily verified by light+dark screenshots; add a render assertion where a class/markup change is testable. **No new migrations** (no schema change).

## Open questions

- **Item 2 toggle placement & styling:** exact header layout for the `Lesson · Quiz` segmented control (confirm in the plan against the current editor header).
- **Item 4 icon names:** final Bootstrap-Icons symbol choices and whether math needs a small custom symbol — settle in the plan.

---

## Committed next cycle (before any new feature work) — per-course structure / depth

Per the user, this is the **immediate next spec → plan → build cycle, ahead of any new development**, and is valued **above** the existing author-skips-levels flexibility.

**Captured intent:**
- A course should be able to adopt a **constant, simpler structure** so a simple course never has to deal with the full Part › Chapter › Section › Unit depth. Likely shape: a per-course **structure preset** — e.g. *Flat* (course › unit), *Chapters* (course › chapter › unit), *Full* (course › part › chapter › section › unit) — that drives which `+` chips the builder offers (a simple course never sees Parts/Sections).
- "A constant structure is fine" — arbitrary skip-anywhere is not required; a per-course constant set of levels is acceptable and preferred for simplicity.
- Needs: a course-level setting (the chosen structure), making `legal_child_kinds` **per-course** (currently global in `courses/ordering.py`), a settings UI, and a migration / handling path for existing content sitting at a now-excluded level.
- **Folds in the "Structure" legend**: a builder-side legend showing *the course's configured levels* — the right fix for the "so many components, I feel lost" problem.

Recorded here (and in project memory) so it is not lost; it gets its own brainstorm → spec → plan → build before any other new feature.
