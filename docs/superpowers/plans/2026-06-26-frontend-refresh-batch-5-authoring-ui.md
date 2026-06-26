# Frontend Refresh Batch 5 — Authoring UI Restyle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining visual gaps in the authoring UI (course builder, element editor, marking fields, media manager) so every authoring surface uses the shared design vocabulary and has light/dark parity — the final, lightest batch of the frontend refresh.

**Architecture:** This is a **CSS-only** pass. A static survey found the authoring pages' outer layouts already token-driven and matching the accepted mockups (built in earlier phases 1b/WS2/WS3); what remains is a set of class names that templates already emit but which have **no CSS rule in the stylesheet that page actually loads** (so they render unstyled — a couple, like `.element-list`, are defined in `editor.css` but the builder page never loads it), plus two hardcoded-color dark-mode fixes. We add the missing rules to the existing CSS files (`core/static/core/css/app.css`, `courses/static/courses/css/editor.css`, `courses/static/courses/css/builder.css`) and fix the two dark-mode literals (`courses.css`, `editor.css`). **No `.html` template changes** — the class hooks are already in place. **No model/schema/migration, no JS, no new visible strings.**

**Tech Stack:** Django (server-rendered templates), bespoke token-driven CSS (CSS custom properties; dark mode via `<html data-theme="dark">`), pytest + Playwright (`-m e2e`) for the screenshot harnesses.

## Global Constraints

- **Visual-only, CSS-only:** do **not** change any `.html` template structure, any view, any JS, or any model. Only edit the four CSS files named in the File Structure. The undefined class names are already present in the templates verbatim — add rules for them, do not rename them.
- **Reuse the design tokens, never hardcode colors:** all colors/spacing/radius come from `core/static/core/css/tokens.css` custom properties — `--surface-base|raised|sunken`, `--text-primary|secondary|tertiary|inverse`, `--border-subtle|default|strong`, `--primary`, `--primary-subtle`, `--accent`, `--danger`, `--space-1..10` (4/8/12/16/20/24/32/40px), `--radius-sm|md|lg` (7/10/12px), `--shadow-xs`. **No hex, no rgb(), no `#fff`/`#000`** in any rule this batch adds or touches (the whole point of the two dark-mode fixes is to remove literals).
- **Dark-mode parity:** every rule added must render correctly under both `data-theme="light"` and `data-theme="dark"` — which is automatic if it only uses tokens. Verify with screenshots in BOTH themes (spec §8).
- **No new i18n strings:** CSS introduces none; `test_po_catalog_clean` must stay green (no `.po`/`.mo` work expected).
- **Screenshot-driven DoD (spec §8 "consistency pass"):** each task's primary verification is a throwaway Playwright screenshot of the real page in **light + dark**, self-critiqued against the checklist, then deleted (per `verify-ui-with-screenshots` / the delete-after pattern). The CSS values given below are concrete, sensible starting points; tuning them against the screenshots IS the task, not a placeholder.
- **Tooling:** bash `ruff`/`pytest`/`python` are **NOT on PATH** — use `uv run ruff …`, `uv run pytest …`, `uv run python manage.py …`. Local `uv run pytest -q` EXCLUDES e2e; the screenshot harnesses are `@pytest.mark.e2e` and run with `-m e2e`.
- **Lint:** every task ends green on `uv run ruff check .` AND `uv run ruff format --check .` (CSS is not linted by ruff, but any throwaway `.py` harness committed transiently must be removed before commit; ruff covers Python).

**Reference docs:** spec `docs/superpowers/specs/2026-06-25-frontend-design-refresh-and-navigation-design.md` §2 (batch order — batch 5 is last), §7 (Authoring UI scope: "a lighter restyle of `builder.html`, `editor/*`, marking fields, and `media/manager.html` to the shared vocabulary … No structural rework"), §8 (DoD). Accepted mockups: `docs/mockups/builder_accepted.html`, `content-editor_accepted-A.html`, `media-manager-and-picker_accepted.html`.

**Note on line numbers:** all `editor.css` line numbers below are **round-start (pre-edit) references**. Tasks 1, 3, 4 and 5 all edit `editor.css`, so earlier insertions/removals shift later line numbers — always re-locate a rule by its **string/selector**, never by a literal line number, when its task runs.

**Existing CSS anchors to match (verbatim, for style consistency — do not modify unless named):**
- `editor.css:66-68` — `.el-editor { display: grid; gap: var(--space-3); }` and `.el-editor label { color: var(--text-secondary); }` and `.el-editor__hint { … font-size: .8rem; color: var(--text-secondary); }`.
- `editor.css:77-91` — `.choice-rows`/`.choice-row`/`.choice-row__del` (the pattern the new `.pair-*` rules mirror).
- `editor.css:314-316` — `.zone-row__badge { … background: var(--primary); color: #fff; … }` (the `#fff` is the dark-mode bug to fix).
- `editor.css:326` — `.muted { color: var(--text-tertiary); font-size: .85rem; }` (to RELOCATE to app.css; review pages don't load editor.css).
- `courses.css:222-229` — `.dragimage__target { … background: rgba(255, 255, 255, 0.15); … }` (the rgba white literal to fix).
- `builder.css:8,20` — `.tree__scope`/`.tree__empty` patterns (the unit panel list rules sit alongside these; builder pages load only `builder.css` + `app.css` + `tokens.css`, NOT `editor.css`).
- `app.css:118` `.card`, `app.css:231` `.card-list` — neighbours for where shared rules live.

---

## File Structure

**Modified (CSS only):**
- `core/static/core/css/app.css` — add `.empty-state` (used in 5 templates, currently undefined everywhere) and `.muted` (relocated here from `editor.css` to always-loaded `app.css` so the review pages get it — and, as a deliberate side-effect, so do the 6 other `.muted`-using pages that render it unstyled today: student `quiz_results`/`course_results` + the 4 grouping pages; verified in Task 1 Step 4).
- `courses/static/courses/css/editor.css` — add `.el-editor__label`, `.el-editor__marking-fields`, `.el-editor__check`, `.math-field-wrap`, `.edit-html`/`.edit-html__label`/`.edit-html__help`, `.pair-rows`/`.pair-row`/`.pair-row__del`, `.asset-del`, `.picker__file`; **remove** the relocated `.muted` (line 326); **fix** `.zone-row__badge` `color: #fff` → `var(--text-inverse)`.
- `courses/static/courses/css/builder.css` — add `.element-list`, `.element-list__item`, `.element-list__type`, `.element-list__summary`, `.unit-summary` (the read-only unit panel list; builder doesn't load `editor.css`).
- `courses/static/courses/css/courses.css` — fix `.dragimage__target` `background: rgba(255,255,255,0.15)` → a token-driven translucent tint.

**Throwaway (created then deleted each task):** Playwright screenshot harnesses appended to the relevant e2e file (`tests/test_e2e_editor.py`, `tests/test_e2e_review.py`, or a small standalone in the scratchpad), reusing existing helpers, removed before the task's commit.

**No new files. No template/JS/model/migration changes.**

---

## Task 1: Shared primitives — `.empty-state` + relocate `.muted`

**Files:**
- Modify: `core/static/core/css/app.css`, `courses/static/courses/css/editor.css`

**Interfaces:**
- Produces: `.empty-state` and `.muted` defined in `app.css` (loaded on every page via `base.html`). `.muted` removed from `editor.css` (no duplicate). Consumed by Tasks 2–5 and by the review pages (`review_submission.html`/`review_queue.html`, which load `courses.css` + `app.css` but NOT `editor.css`).

- [ ] **Step 1: Confirm the current state**

Grep to confirm the survey before editing:
```bash
grep -rn "\.empty-state" core/static/core/css/app.css courses/static/courses/css/*.css   # expect: no matches
grep -n "\.muted" core/static/core/css/editor.css                                          # expect: line 326 only
grep -rn "\.muted" core/static/core/css/app.css courses/static/courses/css/courses.css     # expect: no matches
```
Expected: `.empty-state` is undefined anywhere; `.muted` exists only in `editor.css:326`. (If `.muted` already exists in `app.css`/`courses.css`, do NOT add a duplicate — stop and report.)

- [ ] **Step 2: Add the two shared rules to `app.css`**

In `core/static/core/css/app.css`, append these rules at **top level** (NOT inside any media query). The `.card-list` section ends with a `@media (max-width: 640px) { … }` block (originally lines 239–242) that contains `.card-list li { flex-direction: column; … }` and `.row-actions { … }`. Append the new rules **after that media block's closing `}`** (i.e. after line 242, before the next top-level comment) — do NOT append after the `.card-list li { flex-direction: column;` line, which is *inside* the media query and would scope `.empty-state`/`.muted` to ≤640px only:

```css
/* Shared utility text states (batch 5). .empty-state was referenced by builder,
   editor, preview and media templates but never defined; .muted is relocated here
   from editor.css (the only prior definition) to always-loaded app.css. NOTE the
   blast radius: .muted is used by 11 templates, and SIX outside the authoring scope
   render it unstyled today because they don't load editor.css — the student
   quiz_results.html + course_results.html (load courses.css only) and the four
   grouping pages group_list/my_groups/group_detail/collection_detail (load app.css
   only). This relocation intentionally fixes that latent gap; the tertiary/.85rem
   muted look is the desired appearance on all of them (verified in Step 4). */
.empty-state { color: var(--text-tertiary); font-style: italic; padding: var(--space-4) 0; margin: 0; }
.muted { color: var(--text-tertiary); font-size: .85rem; }
```

- [ ] **Step 3: Remove the now-duplicate `.muted` from `editor.css`**

In `courses/static/courses/css/editor.css`, delete line 326 (`.muted { color: var(--text-tertiary); font-size: .85rem; }`). The media manager (which loads `editor.css`) still gets `.muted` from `app.css` (also always loaded), so no regression.

- [ ] **Step 4: Screenshot verification (light + dark)**

Write a throwaway Playwright harness (reuse `tests/test_e2e_review.py` helpers for a review page that shows `.muted`, e.g. the per-row `/ {{ row.max_marks }}` span in `review_submission.html` and the queue's "Nothing awaiting review." `.muted`; and a builder/editor page that shows `.empty-state`, e.g. a unit with no elements → `_unit_panel.html`'s "No elements yet." or the editor preview's empty message). For each, set `document.documentElement.setAttribute('data-theme', 'light'|'dark')` and screenshot to the session scratchpad.

**Also screenshot the out-of-scope pages the `.muted` relocation newly affects** (see the blast-radius note above) — at minimum the student `quiz_results.html` and `course_results.html`, and one grouping page (e.g. `group_list.html`) — light + dark. These render `.muted` unstyled today; confirm the new tertiary/.85rem muted look is correct and desired on each (it should read as intentional de-emphasis, not a regression).

Self-critique: the previously-flat `.muted` text now reads as smaller tertiary on the review, student-results, and grouping pages; `.empty-state` reads as muted italic with breathing room; nothing on those out-of-scope pages looks broken by the change; all legible in dark. Delete the harness.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check .
git add core/static/core/css/app.css courses/static/courses/css/editor.css
git commit -m "style(authoring): define .empty-state + relocate .muted to app.css"
```

---

## Task 2: Builder unit panel — read-only element list + summary

**Files:**
- Modify: `courses/static/courses/css/builder.css`

**Interfaces:**
- Consumes: `.empty-state` from Task 1 (the `{% empty %}` row in `_unit_panel.html`).
- Produces: `.element-list`, `.element-list__item`, `.element-list__type`, `.element-list__summary`, `.unit-summary` defined in `builder.css`. Styles the read-only element list shown in the builder's right panel when a Unit is selected (`templates/courses/manage/_unit_panel.html`: `<dl class="panel__meta unit-summary">` + `<ol class="element-list element-list--readonly">` of `<li class="element-list__item"><span class="element-list__type">…</span><span class="element-list__summary">…</span></li>`).

- [ ] **Step 1: Add the rules to `builder.css`**

In `courses/static/courses/css/builder.css`, append at the end of the file:

> **Note on `.element-list`:** `editor.css` already defines `.element-list` / `.element-list--readonly` / `.element-list--readonly .el-row` for the *editor* context. The builder pages load only `builder.css` + `app.css` (NOT `editor.css`), so the rules below are scoped to the builder and do **not** collide with the editor's. The `.element-list--readonly` modifier emitted by `_unit_panel.html` is intentionally a **no-op** in the builder context (the base `.element-list` rule suffices) — we do not redefine it here.

```css
/* Unit detail panel (batch 5): read-only summary + element list. The builder pages
   load only builder.css + app.css (NOT editor.css), so these classes are defined
   here rather than reusing editor.css's .el-row family. (.element-list also exists
   in editor.css for the editor context — no collision; builder never loads it.) */
.unit-summary { display: grid; grid-template-columns: auto 1fr; gap: var(--space-1) var(--space-3); align-items: baseline; }
.unit-summary dt { color: var(--text-tertiary); font-size: .8rem; }
.unit-summary dd { margin: 0; color: var(--text-primary); }
.element-list { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-1); }
.element-list__item { display: flex; align-items: baseline; gap: var(--space-2); padding: var(--space-2) 0; border-bottom: 1px solid var(--border-subtle); }
.element-list__type { flex: none; font-size: .7rem; text-transform: uppercase; letter-spacing: .03em; color: var(--primary); }
.element-list__summary { flex: 1; min-width: 0; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
```

(The `.unit-summary` rule layers onto the existing `.panel__meta` colour; `grid-template-columns: auto 1fr` lays the `dt`/`dd` pairs as a label/value grid. `.element-list__type` echoes the `.tree__badge` type-tag colour vocabulary; the summary truncates to one line.)

- [ ] **Step 2: Screenshot verification (light + dark)**

Throwaway harness: log in as a course author (reuse `tests/test_e2e_editor.py`'s `_make_pa_user`/`_login`/`_seed_course_and_unit`), seed a unit with a couple of elements, open the **builder** page (`/manage/courses/<slug>/build/`), click the unit's title to load `_unit_panel.html` into the right panel. The editor helpers only seed/navigate the editor, NOT the builder click→fragment flow — borrow the navigate-and-click-unit pattern (the `.tree__title` button selector + the wait for the `[data-panel-for=<pk>]` fragment swap) from the existing `tests/test_e2e_builder.py` so you don't invent the selector/wait from scratch. Screenshot the panel light + dark. Also screenshot a unit with **no** elements (the `.empty-state` "No elements yet." row) to confirm Task 1's rule.

Self-critique: the Type/Obligatory summary reads as a clean label/value grid; each element row shows a teal type-tag + truncated summary with a hairline divider; spacing matches the surrounding panel; dark theme legible. Adjust spacing/tokens if cramped. Delete the harness.

- [ ] **Step 3: Lint + commit**

```bash
uv run ruff check .
git add courses/static/courses/css/builder.css
git commit -m "style(builder): style read-only unit panel element list + summary"
```

---

## Task 3: Editor edit-forms — labels, marking box, match-pairs, html field

**Files:**
- Modify: `courses/static/courses/css/editor.css`

**Interfaces:**
- Produces in `editor.css`: `.el-editor__label`, `.el-editor__marking-fields`, `.el-editor__check`, `.math-field-wrap`, `.edit-html`/`.edit-html__label`/`.edit-html__help`, `.pair-rows`/`.pair-row`/`.pair-row__del`. Styles the inner edit-form content of the element editors under `templates/courses/manage/editor/` — section-heading labels (used on nearly every `_edit_*` partial as `<label class="el-editor__label">`), the marking-fields box (`_marking_fields.html`), the match-pairs editor (`_edit_matchpairquestion.html`: `<ul class="pair-rows"><li class="pair-row">{{f.left}} {{f.right}} <label class="pair-row__del">…</label></li>`), and the HTML element field (`_edit_html.html`).

- [ ] **Step 1: Add the rules to `editor.css`**

In `courses/static/courses/css/editor.css`, locate the `.el-editor__hint` rule by string (originally ~line 68) and append this single combined block immediately after it. All the new rules go in this one block in this one place — do not split them across the file:

```css
/* Section-heading labels inside edit forms (batch 5). .el-editor label already
   sets the secondary colour (line 67); this adds the heading weight/size so a
   field's section title is distinct from inline field text. */
.el-editor__label { font-size: .8rem; font-weight: 600; color: var(--text-secondary); }
.el-editor__check { display: inline-flex; align-items: center; gap: var(--space-2); }
/* The "accepted answers" group in the short-text editor: a <span> wrapping a
   <textarea name="accepted">, the ∑ .math-trigger button, and the .math-preview span
   (NOT a <math-field>). As a direct child of .el-editor (display:grid) it is already
   blockified, so a bare display:block would be a no-op; grid+gap here gives its three
   children even vertical spacing, and justify-items:start keeps the ∑ button at its
   natural width while the textarea (width:100% from app.css) still fills the row.
   Verify against the short-text screenshot (Step 2 #4). */
.math-field-wrap { display: grid; gap: var(--space-2); justify-items: start; }
.el-editor__marking-fields { display: grid; gap: var(--space-3); padding: var(--space-3); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); background: var(--surface-sunken); }
.el-editor__marking-fields [data-marks-fields] { display: grid; gap: var(--space-3); }
/* HTML/CSS/JS element field wrapper. */
.edit-html { display: grid; gap: var(--space-2); }
.edit-html__label { font-size: .8rem; font-weight: 600; color: var(--text-secondary); }
.edit-html__help { font-size: .8rem; color: var(--text-tertiary); margin: 0; }
/* Match-pairs editor — mirrors the .choice-rows/.choice-row/.choice-row__del pattern. */
.pair-rows { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); }
.pair-row { display: flex; align-items: center; gap: var(--space-2); }
.pair-row input[type="text"] { flex: 1; min-width: 0; }
.pair-row__del { display: inline-flex; align-items: center; gap: var(--space-1); white-space: nowrap; font-size: .75rem; color: var(--text-secondary); cursor: pointer; }
```

(`.el-editor__label` has class specificity > the `.el-editor label` descendant rule, so its `font-weight`/`font-size` win while inheriting the secondary colour intent. The `.pair-*` rules are deliberately identical in shape to `.choice-*` so the two question editors look consistent.)

- [ ] **Step 2: Screenshot verification (light + dark)**

Throwaway harness (reuse `tests/test_e2e_editor.py` `_seed_course_and_unit` + `_add_element(page, "<type>")`). The confirmed `_add_menu.html` `data-add-type` keys are: `html`, `matchpairquestion`, `shorttextquestion`, `extendedresponsequestion` — call `_add_element(page, "<key>")` directly. Open, in the real editor page, four editors and screenshot each light + dark:
1. a **match-pairs** question editor — `_add_element(page, "matchpairquestion")` (the `.pair-rows` list — previously fully unstyled);
2. an **HTML** element editor — `_add_element(page, "html")` (`.edit-html__label` + `.edit-html__help`);
3. a question editor showing the **marking-fields** box (`_marking_fields.html` — Marking mode / Max attempts / Max marks; e.g. `extendedresponsequestion` or any of the above);
4. a **short-text** question editor — `_add_element(page, "shorttextquestion")` (`_edit_shorttextquestion.html` — the only template carrying `.el-editor__check` and `.math-field-wrap`, so those two of the seven new rules don't ship unverified).

Self-critique: section labels read as small-caps-ish bold headings distinct from field text; the match-pairs rows align like the choice-question rows (left/right inputs share the row, Remove control trailing); the marking box reads as a grouped sunken sub-panel; in the short-text editor the `.el-editor__check` label is a tidy inline-flex checkbox row and the `.math-field-wrap` group lays its textarea / ∑ trigger / preview out with even spacing (∑ button at natural width); dark legible. Tune spacing/weights. Delete the harness.

- [ ] **Step 3: Lint + commit**

```bash
uv run ruff check .
git add courses/static/courses/css/editor.css
git commit -m "style(editor): style edit-form labels, match-pairs, html field + marking box"
```

---

## Task 4: Dark-mode fixes — zone badge + drag-to-image target

**Files:**
- Modify: `courses/static/courses/css/editor.css`, `courses/static/courses/css/courses.css`

**Interfaces:**
- Produces: `.zone-row__badge` uses `var(--text-inverse)` instead of `#fff`; `.dragimage__target` uses a token-driven translucent tint instead of `rgba(255,255,255,0.15)`. Affects the drag-to-image question editor (zone list badges) and its student/preview canvas (drop-target overlays).

- [ ] **Step 1: Fix `.zone-row__badge` in `editor.css`**

In `courses/static/courses/css/editor.css`, **locate the `.zone-row__badge` rule by string match** (do NOT trust an absolute line number — Task 3 inserted a block earlier in this file, so the rule has shifted down from its original ~line 315). Find `color: #fff` inside the `.zone-row__badge` rule (it is the only `#fff` in the file) and change it to `var(--text-inverse)` (dark text on light-teal in dark mode, light text on dark-teal in light mode), so the rule becomes:

```css
.zone-row__badge { flex: none; width: 1.5rem; height: 1.5rem; border-radius: 50%;
  background: var(--primary); color: var(--text-inverse); display: inline-flex; align-items: center;
  justify-content: center; font-size: .8rem; font-weight: 700; }
```

- [ ] **Step 2: Fix `.dragimage__target` in `courses.css`**

In `courses/static/courses/css/courses.css`, change line 226 — `background: rgba(255, 255, 255, 0.15);` — to a theme-following translucent tint (matching the `color-mix(... transparent)` pattern already used at `builder.css:102`):

```css
  background: color-mix(in srgb, var(--primary) 12%, transparent);
```

(Leave the rest of the `.dragimage__target` rule unchanged. The tint now lifts with `--primary` per theme and stays translucent so the underlying image shows through.)

- [ ] **Step 3: Screenshot verification (DARK especially, + light)**

Throwaway harness: open a **drag-to-image** question editor (zone badges) and, via the editor preview pane (`_preview.html`) or a seeded student render, the **drag-to-image target overlay**. Screenshot dark + light.

Self-critique: zone badge digits are readable on the teal circle in BOTH themes (not white-on-light-teal mush in dark); the drop-target overlay is visible (a subtle teal tint) on the image in dark mode, not the near-invisible white wash it was. Delete the harness.

- [ ] **Step 4: Lint + commit**

```bash
uv run ruff check .
git add courses/static/courses/css/editor.css courses/static/courses/css/courses.css
git commit -m "style(editor): token-drive zone badge + drag-to-image target for dark mode"
```

---

## Task 5: Media manager polish — delete form + file input

**Files:**
- Modify: `courses/static/courses/css/editor.css`

**Interfaces:**
- Consumes: `.empty-state` from Task 1 (the empty asset grid / picker grid messages).
- Produces: `.asset-del`, `.picker__file` defined in `editor.css`. Styles the media manager asset-cell delete form (`media/_asset_cell.html`: `<form class="asset-del">`) and the picker's file input (`media/_picker.html`: `<input type="file" class="picker__file">`).

- [ ] **Step 1: Add the rules to `editor.css`**

In `courses/static/courses/css/editor.css`, after the media-manager block (near the `.asset-foot` rules), append:

```css
/* Media manager polish (batch 5). The delete <form> wraps an icon button inside
   the flex .asset-foot — display:contents lets the button sit directly in that
   flex row instead of the form introducing a block-level gap. */
.asset-del { display: contents; }
.picker__file { font-size: .85rem; color: var(--text-secondary); }
```

(If `display: contents` causes a layout issue under the actual `.asset-foot` flexbox during the screenshot step, fall back to `.asset-del { margin: 0; }` — note which you used in the report.)

- [ ] **Step 2: Screenshot verification (light + dark)**

Throwaway harness: open the **media manager** (`/manage/courses/<slug>/media/` — confirm the route) with at least one asset (so an asset-cell with its delete form renders) and the **picker** modal (Upload tab → the file input). Screenshot light + dark. Also confirm the empty asset grid shows the Task-1 `.empty-state` styling.

Self-critique: the delete (trash) icon button sits inline in the asset footer with the rename/usage controls (no stray gap); the file input text reads as secondary; empty grid reads as muted italic; dark legible. Delete the harness.

- [ ] **Step 3: Lint + commit**

```bash
uv run ruff check .
git add courses/static/courses/css/editor.css
git commit -m "style(media): style asset delete form + picker file input"
```

---

## Task 6: DoD — full suite, lint, render smoke, i18n, final screenshot pass

**Files:**
- (verification only)

- [ ] **Step 1: Full suite + lint**

```bash
uv run pytest -q            # non-e2e: expect all green (CSS-only change touches no Python)
uv run pytest -q -m e2e     # e2e: expect green (run touched files alone if live_server port contention)
uv run ruff check .
uv run ruff format --check .
```
Expected: all green. The change is CSS-only, so no behaviour test should move; if any test fails, investigate (a failing render test would mean a template was touched — it must not have been).

- [ ] **Step 2: Render smoke (no template breaks)**

Confirm the four authoring page groups still render (the existing manage/editor/builder/media/review view tests cover this — run them explicitly):
```bash
uv run pytest -q -k "builder or editor or media or review"
```
Expected: PASS. Use the keyword `review` (NOT `review_submission`/`review_queue`, which match no test node-ids) — it collects the non-e2e `test_review_roster.py`/`test_review_services.py`/`test_review_views.py` (~54 tests) that render the review pages. (CSS-only change introduces no template/markup risk; this guards against an accidental template edit. The review/student/grouping pages' *appearance* is additionally covered by the Task 1 Step 4 screenshots.)

- [ ] **Step 3: i18n check (expect: no change)**

```bash
uv run python manage.py makemessages -l pl
git diff locale/pl/LC_MESSAGES/django.po
```
Expected: **only the `POT-Creation-Date:` header line changes** — `makemessages` re-stamps that header on every run, so `--stat` will always show the file as modified; that is benign. Inspect the full `git diff` (not just `--stat`): if the ONLY change is the `POT-Creation-Date` header (no added/changed/removed `msgid`/`msgstr`, no `#:` location-comment churn), discard it: `git checkout -- locale/pl/LC_MESSAGES/django.po`. If a real `msgid`/`msgstr` change appears, a template was touched accidentally — revert the template change (this batch is CSS-only). Then: `uv run pytest -k po_catalog_clean -q` → PASS.

> **Static-collection note:** the source CSS under `core/static/`, `courses/static/` is the source of truth (and what `runserver` serves in dev). Collected artifacts under `staticfiles/` are stale — they still contain an OLD `.empty-state { opacity: .7; … }` from when it lived in `builder.css`. This does not affect dev or the screenshot harnesses, but if this deployment serves collected static, run `uv run python manage.py collectstatic --noinput` so the artifacts pick up the new rules. No source impact.

- [ ] **Step 4: Final light/dark screenshot pass + self-review**

Per `verify-ui-with-screenshots`: throwaway harness capturing all four groups (builder unit panel, an element editor incl. match-pairs, the drag-to-image dark fix, media manager) in light + dark. Confirm: every previously-unstyled class now reads intentionally; dark parity holds; nothing regressed elsewhere (the shared `.empty-state`/`.muted` didn't bleed into unintended places). Save finals to the scratchpad, report paths, delete the harness.

- [ ] **Step 5: Commit (only if Step 3/4 produced any tweak)**

```bash
# only if a screenshot-driven CSS tweak or i18n change was needed:
git add -A
git commit -m "style(authoring): batch-5 screenshot-pass polish"
```

---

## Self-Review (author checklist — completed)

**Spec coverage (§7 + §8):**
- "lighter restyle of `builder.html`" → Task 2 (unit panel) + Task 1 (`.empty-state`). ✓
- "`editor/*`" → Task 3 (edit-form labels, match-pairs, html field, marking box) + Task 4 (dark-mode zone badge). ✓
- "marking fields" → Task 3 (`.el-editor__marking-fields`/`.el-editor__label`). ✓
- "`media/manager.html`" → Task 5 + Task 1 (`.empty-state`). ✓
- "shared vocabulary … dark-mode parity" → tokens-only rules throughout + Task 4 removes the two color literals. ✓
- "No structural rework" → CSS-only; no template/JS/model change (Global Constraints). ✓
- §8 "assertions that no template breaks render" → Task 6 Step 2; "throwaway screenshots light+dark, self-critique, delete-after" → every task's verification step; "every batch: full suite + ruff + i18n" → Task 6. ✓

**Placeholder scan:** every CSS rule is concrete with token values; the only "tuning" is the screenshot self-critique step, which is the spec-mandated DoD for a visual batch, not a deferred decision. The `display:contents` fallback (Task 5) and the add-menu `data-add-type` keys (Task 3) are flagged to verify against the codebase during the task, not silent TODOs.

**Type/name consistency:** the class names added match those the templates emit (verified against `_unit_panel.html`, `_edit_matchpairquestion.html`, `_edit_html.html`, `_marking_fields.html`, `_asset_cell.html`, `_picker.html`). One emitted modifier — `.element-list--readonly` (builder) — is deliberately left undefined in `builder.css` as a no-op (the base `.element-list` rule suffices); it is not a missing rule. `.muted` is defined once (relocated, not duplicated). Token names match `tokens.css` (`--text-inverse`, `--primary`, `--surface-sunken`, `--border-subtle`, `--space-*`, `--radius-sm`).
