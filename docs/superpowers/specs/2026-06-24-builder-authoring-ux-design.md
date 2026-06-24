# Builder & Editor Authoring-UX Polish — Design

**Date:** 2026-06-24
**Status:** Draft (brainstormed; pending user review)
**Type:** UX polish batch (course-authoring builder + unit editor). Not a roadmap phase — a focused improvement pass on existing Phase-1b surfaces, prompted by manual-testing friction found while exercising the Phase-3c-i quiz-review work.

## Goal

Make creating and authoring a **quiz** unit (and authoring in general) less confusing in the course builder / unit editor, and tidy two visual rough edges. Five small, independent improvements shipped as one spec → plan → build cycle.

> **Committed follow-up:** a per-course **structure / depth** feature is the agreed **next cycle, ahead of any new development** — see "Committed next cycle" at the end. The "Structure legend" idea raised during this brainstorm is deliberately folded into that cycle (it should reflect a course's *configured* levels, not a fixed four-level diagram).

## Background / current state (verified in code)

- **Content tree:** one `ContentNode` model, `kind ∈ {part, chapter, section, unit}` (`courses/models.py:97-101`), `unit_type ∈ {lesson, quiz}` (nullable; required on units, forbidden on non-units; `models.py:103-105,138-142`). `RANK = {part:0, chapter:1, section:2, unit:3}`. A child must be a strictly deeper kind than its parent (`courses/ordering.py:126-133`); `legal_child_kinds(None)` (top scope) allows all kinds, so **levels are skippable** and the same kind menu is available in every course (`differences.md` §"Course depth"). There is no per-course restriction yet — that is the committed next cycle.
- **Adding a unit:** the builder add-row (`templates/courses/manage/_add_affordance.html`) renders one `+ <Kind>` chip per legal child kind, a single shared title input (`required`), and a hidden `unit_type=lesson` that is **always** sent. `node_add` (`courses/views_manage.py:199-216`) reads `kind` from `POST["kind"]` (the clicked button's `name=kind value=<kind>`) and `unit_type = POST.get("unit_type") if kind=="unit" else None`, then calls `builder.add_node`. A template comment at `_add_affordance.html:12-14` explains the always-sent `unit_type=lesson` is safe *because* `node_add` nulls it for non-units, and says **"do NOT change the backend"** — Item 1 deliberately supersedes that comment. **Result today: every new unit is created as a Lesson; there is no way to choose Quiz at add time.**
- **Changing a unit's type:** only via the editor's collapsed `<details class="unit-settings">` (`templates/courses/manage/editor/_unit_settings.html`). Its `<summary>` shows the unit title (`unit-settings__title`) and a static type label `Unit · {{ unit.get_unit_type_display }}` (`editor-head__type`, line 5); the body has title (`required`), a `<select name="unit_type">`, an `obligatory` checkbox, and an `html_seed_js` textarea. It POSTs to `node_rename` with `has_settings=1`, `ctx=editor` (`views_manage.py:244-297`). **Crucially, when `has_settings` is present `node_rename` reads ALL of `title`, `obligatory` (checkbox → False when absent), and `html_seed_js` from POST** and passes them to `builder.rename_node` (only fields *outside* the settings post stay at the `_UNSET` sentinel). Reaching this is: click unit name → open editor → expand Settings.
- **Editor page layout:** `templates/courses/manage/editor/editor.html`. It has its **own** inline sprite `editor__sprite` containing toolbar `ed-*` symbols (bold/italic/…); a breadcrumb `<p class="editor-crumb">` (back-arrow + course/ancestor path + Media-library link — it does **not** show the unit title); then the `_unit_settings.html` include and the editor scope. There is **no dedicated unit-title header**; the unit title appears only in the settings `<summary>` and `<head_title>`.
- **Add-element menu:** `templates/courses/manage/editor/_add_menu.html` — a `.typemenu` (carrying `data-type-menu`) of **15** `.typecard` buttons in one flat grid; the JS toggles the menu via `[data-type-menu]` and handles card clicks via `[data-add-type]` (`editor.js:180-196`). The 15 cards map to **14** `element_add` type keys because *Single choice* and *Multiple choice* are two cards that both resolve to the one `choicequestion` key (`views_manage.py:792-795`). Icons are a `.ic` span holding an **emoji or a unicode glyph** (mixed colour-emoji + monochrome glyphs). `element_add` whitelists all 14 keys with **no unit-type gating** (`views_manage.py:788-820`). NOTE: `differences.md` §Unit lines 14-15 ("lesson allows all; quiz allows quiz elements only") is **deliberately not enforced** — by decision, any element type is allowed in either unit type (e.g. a shared image/passage a quiz question addresses); only marking differs. So Item 3 is grouping only, not filtering.
- **Icons in-repo:** the **builder page** (`templates/courses/manage/builder.html`) carries an inline `<symbol id="bi-…">` sprite (only `bi-up/down/grip/move/trash` — hand-authored, not a vendored Bootstrap-Icons asset) and its tree rows use `<svg class="ic"><use href="#bi-grip"/></svg>` (`_tree_node.html`). **The editor page does NOT include this `bi-*` sprite at all** — it has the unrelated `editor__sprite` (toolbar) and its element rows (`_element_row.html`) use raw unicode glyphs (⠿ ✎ ✕ ↑ ↓ 🗑, class `iconbtn`), not `bi-*`. So no monochrome element-icon sprite reaches the editor today; Item 4 must newly deliver one there.
- **Marking inputs:** `templates/courses/manage/editor/_marking_fields.html` renders bare Django widgets `{{ form.marking_mode }}`, `{{ form.max_attempts }}`, `{{ form.max_marks }}` (gated by `is_quiz`) with **no CSS class**. The editor's themed input hook is the `.input` class (`editor.css:330` — `background: var(--surface-sunken)`, theme-aware); because the marking widgets lack it, they fall back to un-themed browser colours and are **illegible in dark mode** (light background, light text).

## Scope — five items

1. **Create a unit as Lesson or Quiz at add time** (builder).
2. **Change a unit's type from a new editor header** (a visible Lesson/Quiz toggle), not only from collapsed Settings.
3. **Group the add-element menu** into Content vs Questions (all types stay available in both unit types).
4. **Unify the element-card icons** as monochrome SVG.
5. **Fix dark-mode legibility of the marking inputs.**

### Not in this batch

- **Per-course structure / depth config** ("a simple course shouldn't deal with the full depth"; restrict which kinds a course uses). → **Committed next cycle** (see end). Higher-value than author skip-levels; sequenced before any new development.
- **The "Structure" legend** — folded into the next cycle, where it can show the course's *configured* levels.
- **Migrating the editor's existing `_element_row.html` glyph icons (⠿ ✎ ✕ ↑ ↓ 🗑) to the new SVG sprite** — out of scope; only the add-element *cards* are converted in Item 4. (Noted because it leaves a temporary visual inconsistency between the new SVG cards and the glyph row-actions; a later pass can unify them.)
- **Inline (double-click) title editing** in the editor — deferred. Title editing stays in Settings.
- **Filtering / reordering the element menu by unit type** — by decision, all element types stay available in both unit types; grouped, not filtered.
- **Quiz-level marking type ([A]/[N]/[R]) + question-compatibility prompt** (`differences.md` lines 41-48) — documented but not built; a separate feature.

---

## Item 1 — Create a unit as Lesson or Quiz

**Behaviour:** wherever the add-row currently offers a single `+ Unit` chip, it instead offers **two chips: `+ Lesson` and `+ Quiz`**. Clicking either creates the unit of that type immediately, using the typed title. Higher levels (Part/Chapter/Section) are unaffected — only the `unit` kind splits into two type-specific chips.

**Why chips (not a toggle):** the add-row is already a row of stateless `+ <Kind>` action chips; two unit chips fit that pattern. One gesture ("type title → click `+ Quiz`") vs a stateful toggle that's easy to leave on the wrong setting — exactly the "it defaulted to Lesson" problem being fixed. A unit is almost always the only legal child at its level, so the row stays tidy (`+ Lesson  + Quiz`).

**Mechanism (no-JS-correct encoding — pin this exactly):**
- The two unit chips are submit buttons that carry the **type in their own `name`/`value`**: `<button name="unit_type" value="lesson">+ Lesson</button>` and `<button name="unit_type" value="quiz">+ Quiz</button>`. (A single submit button contributes only its own `name=value`, so it cannot also send `kind=unit` — hence the type rides the button and the kind is *inferred*.) Drop the always-on hidden `unit_type=lesson`. Non-unit kind chips keep `name=kind value=<kind>` unchanged.
- **`node_add` resolution order (define precisely):** if the submitter carried a `unit_type` value → `kind = ContentNode.Kind.UNIT`, `unit_type = that value` (ignore any `kind` param). Else → `kind = POST["kind"]`, `unit_type = None`. This inverts today's "read unit_type only when kind==unit" dependency; add a test for the **mixed/stray** case (a non-unit `kind` chip submitted while a stray `unit_type` is also present → resolution must follow the stated order deterministically).
- **No-JS correctness:** with JS off, clicking `+ Quiz` submits `unit_type=quiz` and the view infers a quiz unit — never a silent Lesson fallback.
- **Async builder add-path (`builder.js`):** today it stores `form.dataset.pendingKind = kind` and re-finds the chip by kind to `requestSubmit(btn)`. Two unit chips sharing `kind=unit` would make that ambiguous. Disambiguate: give the unit chips distinct identifiers (e.g. `data-add-kind="lesson"`/`"quiz"`, or keep `data-add-kind="unit"` plus a `data-add-unit-type` attribute) and store the chosen type alongside `pendingKind`; the deferred `requestSubmit(btn)` must target the **exact** clicked chip, and the optimistic-add preview must reflect the right type. No regression to the optimistic add.
- **Supersede the guardrail comment:** update/remove the `_add_affordance.html:12-14` "do NOT change the backend" comment (it is now wrong) and confirm no other caller relies on the always-sent `unit_type=lesson` default.

**Affected:** `_add_affordance.html`, `builder.js` (add-path), `views_manage.node_add`, possibly the `courses_manage_extras` kind-chip rendering. Labels reuse the existing translated `UnitType` choice labels.

**Tests:** view tests — `+ Quiz` creates `unit_type="quiz"`; `+ Lesson` creates `lesson`; a non-unit chip creates its kind with `unit_type=None`; the mixed/stray case resolves per the stated order. e2e — a real click on `+ Quiz` produces a quiz unit (the quiz editor/marking path becomes available). No-JS path asserted at the view level.

---

## Item 2 — Change unit type from a new editor header

**Behaviour:** add a small **editor header region** (a new strip, placed with/just below the existing `editor-crumb` breadcrumb in `editor.html`) that shows the **unit title** and a compact **`Lesson · Quiz` segmented toggle** reflecting the current type; clicking the inactive option switches it. (There is no unit-title header today — this item *creates* one; see Background.) The `<select name="unit_type">` is **removed from the Settings `<details>`**, and the static `Unit · {{ unit.get_unit_type_display }}` label in the settings `<summary>` (`_unit_settings.html:5`) is **removed** so the type is shown/controlled in exactly one place (the new header toggle). Settings keeps title, obligatory, and html_seed_js. Title editing stays in Settings (inline-title editing is out of scope).

**Mechanism (avoid the settings-bundle data-loss trap):** the toggle is a small form (segmented control = two buttons; the active type is current, clicking the other submits). It must **NOT** reuse the `has_settings` path: that path makes `node_rename` read `title`, `obligatory`, and `html_seed_js` from POST, so a type-only form (which doesn't carry them) would blank the title (failing the required-title), **clear `obligatory`** (unchecked → False), and wipe `html_seed_js`. Instead, give the toggle a **focused update that sets only `unit_type`** and leaves title/obligatory/html_seed_js at `_UNSET` (e.g. a distinct POST marker the view maps to a unit_type-only `rename_node` call) — or, if reusing the existing form, carry the current title/obligatory/html_seed_js as hidden fields. Must carry the optimistic-concurrency `token`. Must be **no-JS correct** (a plain form submit switches the type and re-renders the editor). Switching is already supported (Settings does it today); this only makes it discoverable and has no data risk to question data (`unit_type` gates rendering/marking visibility, not stored answers).

**Affected:** `editor.html` (new header region), `_unit_settings.html` (remove the type select AND the summary type label), `views_manage.node_rename` / `builder.rename_node` (a unit_type-only update mode that leaves other fields `_UNSET`), editor CSS for the segmented control (legible light + dark).

**Tests:** view tests — the toggle POST flips `unit_type` and **leaves `obligatory`/`html_seed_js`/`title` unchanged** (explicitly assert no wipe); Settings no longer contains a type select; the summary no longer shows a duplicate type label. e2e/screenshot — the header toggle is visible, shows the unit title, reflects/changes type. Light + dark screenshot check.

---

## Item 3 — Group the add-element menu (Content vs Questions)

**Behaviour:** split the flat `.typemenu` into two labelled groups — **"Content"** (text, image, video, iframe, math, html) and **"Questions"** (the 9 question cards) — separated by a labelled divider (a small per-group subheading; optionally a subtle background tint on the Questions group). **All 15 cards stay available in both lesson and quiz units** (decision: the `differences.md` §Unit lines 14-15 lesson/quiz element rule is deliberately not enforced). Fixed order (Content first). No filtering, no unit-type branching, no server change.

**Mechanism:** keep `data-type-menu` on the **outer** `.typemenu` wrapper (the JS open/close handler targets it) and nest the cards inside two child group `<div>`s; the card click handler matches `[data-add-type]` regardless of nesting depth, so confirm it still resolves cards one level deeper (descendant match). No change to `editor.js` behaviour intended.

**Affected:** `_add_menu.html` (two group `<div>`s with `<p class="typemenu__group-label">` headings + a divider, `data-type-menu` unmoved), `editor.css` (group headings; keep the existing `.typecard`). New strings: `{% trans "Content" %}`, `{% trans "Questions" %}` → PL.

**Tests:** render test — both group labels present; the menu wrapper still carries `data-type-menu`; all 15 `data-add-type` cards present (content cards under "Content", question cards under "Questions", none lost in the regroup). A focused JS/e2e check that opening the menu and clicking a (now-nested) card still adds an element. Light/dark screenshot check.

---

## Item 4 — Unify element-card icons as monochrome SVG

**Behaviour:** replace every `.ic` emoji/glyph in `_add_menu.html` with a **monochrome SVG** `<svg class="ic"><use href="#…"/></svg>`, so all element-card icons are one consistent, theme-coloured (`currentColor`) set in the style of the builder tree icons. (Chosen over swapping to monochrome unicode glyphs: SVG is crisp and theme-coloured across platforms.)

**Mechanism:**
- **Deliver a sprite to the editor page** (it currently has none of the element symbols — see Background). Extract a shared `templates/courses/manage/_icon_sprite.html` (move the builder's hand-authored `bi-*` block into it) and `{% include %}` it on **both** the builder page and `editor.html` (the editor needs it newly; the builder keeps working). Alternatively the symbols may be added into the editor's existing `editor__sprite` block — but a shared partial is preferred so both pages stay in sync.
- **Author ~15 element-type `<symbol>`s.** Bootstrap Icons is **not** vendored as a full sprite/font in this repo — only the 5 tree symbols are hand-authored inline. So these ~15 symbols are **hand-authored SVG paths taken from the upstream Bootstrap Icons source** (MIT-licensed — include a short attribution/source comment in the sprite partial), in the same hand-authored style as the existing `bi-*`/`ed-*` symbols. **Suggested mapping** (names/shapes finalised in the plan; use a small custom symbol where BI lacks a clean match, e.g. math): text→`card-text`, image→`image`, video→`play-btn`, iframe→`window`, math→`calculator` (or custom ∑), html→`code-slash`, single-choice→`record-circle`, multiple-choice→`check2-square`, short-text→`input-cursor-text`, short-numeric→`123`, fill-blank→`input-cursor`, drag-the-words→`hand-index`, match-pairs→`link-45deg`, drag-to-image→`bounding-box`, extended-response→`pencil-square`.
- **Scope the CSS so the tree icons can't regress.** `.ic` is shared (typecard emoji span uses `editor.css .typecard .ic { font-size: 1.2rem }`; the builder tree uses `.ic` on its SVGs). Apply the SVG sizing/`fill: currentColor` rule **scoped to `.typecard .ic`** (or a new class on the cards) — do **not** add a global `svg.ic { … }` rule that could alter the existing `_tree_node.html` tree icons. Require a before/after screenshot of the builder tree icons to confirm no regression.

**Affected:** `_add_menu.html`, the new `_icon_sprite.html` (+ includes in `builder.html` and `editor.html`), `editor.css` (`.typecard .ic` SVG sizing/fill).

**Tests:** render test — each typecard contains `<svg class="ic"><use href="#…"/>` and no emoji; the referenced symbol ids exist in the included sprite; the editor page now includes the sprite. Screenshots (light + dark) — card icons render monochrome/theme-coloured; the builder tree icons are unchanged (before/after).

---

## Item 5 — Dark-mode legibility of marking inputs

**Behaviour:** the `marking_mode` select and the `max_attempts` / `max_marks` inputs in `_marking_fields.html` get the editor's themed input appearance so they are clearly legible in dark mode, matching the other editor inputs.

**Mechanism:** the root cause is confirmed — these are bare Django widgets with **no `.input` class**, the editor's themed input hook (`editor.css:330` — `.input { background: var(--surface-sunken); … }`, theme-aware). **Preferred fix: add `class="input"` to the three marking widgets** in `element_forms.py` (the QuestionElement-base marking fields), mirroring how the other editor inputs are themed, rather than a one-off CSS selector. Since the marking widgets are **editor-only** (rendered solely by `_marking_fields.html`, not on the student consumption side), the form-level class change cannot affect consumption rendering — but verify the same widgets aren't reused anywhere consumption-facing before committing.

**Affected:** `element_forms.py` (the QuestionElement-base marking widgets gain `class="input"`); no CSS change expected (reuses `.input`). Markup/form only; no behaviour change.

**Tests:** render test — the rendered marking inputs carry `class="input"`. Screenshot (dark mode) — the three controls are legible; light mode unchanged.

---

## Global constraints

- **Tooling:** `uv run ruff`/`pytest`/`python` (not on PATH bare); `ruff check --fix && ruff format` per task (CI runs `ruff format --check`).
- **i18n:** every new user-facing string wrapped and given a PL translation in `locale/pl/LC_MESSAGES/django.po`; recompile `.mo`; clear any `#, fuzzy`. New strings: "Content", "Questions" (+ any toggle labels); Lesson/Quiz reuse existing translated `UnitType` labels.
- **No-JS correctness:** the builder add (Item 1) and the editor type toggle (Item 2) must work with JavaScript disabled.
- **Dark mode:** all new/changed UI verified legible in light **and** dark via Playwright screenshots (delete-after-review harness) before shipping.
- **Multi-line template comments** use `{% comment %}` (never multi-line `{# #}`).
- **Design system:** bespoke token-driven CSS — reuse existing tokens (`--surface-*`, `--text-*`, `--border-*`, `--primary*`, `--space-*`, `--radius-*`); no new colour literals.

## Testing strategy

Mostly template/render + view tests (Items 1–3, 5), plus a builder e2e for Item 1 (real click creating a quiz unit) and an editor e2e/screenshot for Item 2. Item 4 is verified by render assertions (sprite present, cards use `<use>`) + light/dark screenshots incl. a tree-icon no-regression check. **No new migrations** (no schema change).

## Open questions

- **Item 2 header design:** the exact markup/styling of the new editor header strip (unit title + segmented toggle) relative to the existing `editor-crumb` — settle in the plan. (The header itself is a new element this item introduces, not a pre-existing one.)
- **Item 4 symbol set:** final hand-authored Bootstrap-Icons symbol shapes/ids and whether math needs a small custom symbol — settle in the plan, with upstream-source attribution in the sprite partial.

---

## Committed next cycle (before any new feature work) — per-course structure / depth

Per the user, this is the **immediate next spec → plan → build cycle, ahead of any new development**, and is valued **above** the existing author-skips-levels flexibility.

**Captured intent:**
- A course should be able to adopt a **constant, simpler structure** so a simple course never has to deal with the full Part › Chapter › Section › Unit depth. Likely shape: a per-course **structure preset** — e.g. *Flat* (course › unit), *Chapters* (course › chapter › unit), *Full* (course › part › chapter › section › unit) — that drives which `+` chips the builder offers (a simple course never sees Parts/Sections).
- "A constant structure is fine" — arbitrary skip-anywhere is not required; a per-course constant set of levels is acceptable and preferred for simplicity.
- Needs: a course-level setting (the chosen structure), making `legal_child_kinds` **per-course** (currently global in `courses/ordering.py`), a settings UI, and a migration / handling path for existing content sitting at a now-excluded level.
- **Folds in the "Structure" legend**: a builder-side legend showing *the course's configured levels* — the right fix for the "so many components, I feel lost" problem.

Recorded here (and in project memory) so it is not lost; it gets its own brainstorm → spec → plan → build before any other new feature.
