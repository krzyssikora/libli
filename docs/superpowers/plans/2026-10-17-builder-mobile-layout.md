# Course builder on a phone — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the course builder usable on a touch phone (both orientations): wrapped titles, one ⋯ menu per row, a bottom sheet for the detail/course panel, a sticky Kurs + filter header, phone rename via ⋯ — with desktop byte-for-byte unchanged in behaviour and look.

**Architecture:** All new markup is server-rendered on every layout and neutralised on desktop (`display: contents` / `display: none`). One media condition, `(pointer: coarse) and (max-width: 959.98px)`, gates every phone CSS rule (always under `.js`) and, via `matchMedia`, a new "phone layout" section at the end of `builder.js` that owns the sheet, the shared row menu, the toast, phone rename and the toolbar move. Existing builder.js functions get small, phone-gated hooks (`setPanel`, the Move… handler, `dismissPicker`, the submit handler's picker branch, `notice`, the focusin loader, `applyRename`, `revert`).

**Tech Stack:** Django templates, vanilla JS (ES5 style, IIFE, like builder.js), bespoke token CSS (builder.css), Playwright (sync, pytest) e2e, Django i18n (`locale/pl`).

**Spec:** `docs/superpowers/specs/2026-10-17-builder-mobile-layout-design.md` (owner decisions D1–D11 are verbatim and binding; read the whole spec before any task). Approved mockup: `docs/mockups/builder-mobile-layout.html`.

## Global Constraints

- Phone layout condition, exactly: `(pointer: coarse) and (max-width: 959.98px)`; `pointer`, never `any-pointer`. One JS constant `PHONE_MQ` holds this string; CSS repeats it literally.
- Every phone-layout CSS rule is selector-prefixed with `.js ` AND sits inside that media block. Without JS the page keeps today's layout at every width.
- Desktop (anything not matching the condition) must look and behave exactly as today: same header order/look, sticky panel, rename-in-place, drag, 150 ms Tab debounce, focus-driven panel load, Move… picker fetch unguarded.
- Do not touch the unit editor (`templates/courses/manage/editor/*`, `editor.js`, `editor.css`) or any KaTeX CSS.
- No new per-row DOM beyond: the phone title `<button type="button" class="tree__ptitle">`, the ⋯ `<button type="button" class="ica tree__more">`, and the badge's `data-letter` attribute. The row menu is ONE shared element.
- `setPanel` remains the only writer of `panel.innerHTML` (`tests/test_builder_js_invariants.py`).
- The sheet wrapper is never a `<dialog>`; modal semantics are `role="dialog"` + `aria-modal="true"` + `aria-label` (`{% trans "Details" %}`), present only while the sheet is open on the phone layout.
- Strings: reuse existing msgids — "Course" (Kurs), "Close" (Zamknij), "Rename" (Zmień nazwę), "Loading…" (Wczytywanie…), "Details" (Szczegóły), "Clear the filter to reorder.". One new msgid: "More actions" → "Więcej akcji". After `makemessages`, clear any `#, fuzzy` on touched entries and run `compilemessages` (commit `.po` and `.mo`).
- Django template comments `{# #}` are single-line only; multi-line comments use `{% comment %}`.
- Stylesheet comments cite selectors, never line numbers (`tests/test_css_citations_are_durable.py`).
- Tests: `TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_buildermobile` exported on every pytest command (another worktree may be running tests); start the container first: `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`. e2e needs `-m e2e`; never pass `-q`; run e2e in the FOREGROUND with `-p no:xdist`; grep the pytest summary line, do not trust the exit code alone.
- Every new e2e test must be shown RED against the pre-change code (or a named mutant) before it is accepted GREEN — the per-task "verify it fails" step is mandatory.
- After any CSS change run every `tests/test_*css*.py` plus `tests/test_builder_styles.py`.
- `uv run ruff check .` and `uv run ruff format --check .` before each commit that touches Python.

## Review Focus

1. **A desktop mouse window between 720 and 960 px wide** — must get the desktop layout (pointer is fine). Pinned by Task 1's 945 px desktop test.
2. **A course whose tree is long and deeply nested (part › chapter › section › unit)** — titles of the deepest units must still get ≥45% of a landscape viewport; pinned in Task 2's geometry test with a 4-level fixture.
3. **Polish titles with diacritics and a very long unbroken word** (e.g. `Przekształcenia­izometryczne…` 60 chars, no spaces) — the clamp must not overflow the row horizontally; Task 2 asserts `scrollWidth <= clientWidth` on the title button for such a title.
4. **A network failure while the sheet is open** (panel GET fails) — the sheet shows "Network error — please reload." inside the open sheet, never a stuck placeholder; Task 4 adds a test aborting the panel route.
5. **The author double-taps a title** (two taps in quick succession on two different rows) — only the second row's panel ends up in the sheet; Task 4's race test covers it by holding the first response.

---

## File map

- Modify `templates/courses/manage/builder.html` — wrappers `data-phone-move`, Kurs button, sheet wrapper (dim, head, body, tools), toast, shared row menu, `data-msg-loading`.
- Modify `templates/courses/manage/_tree_node.html` — phone title button, ⋯ button, `data-letter` on container badges.
- Modify `courses/static/courses/css/builder.css` — desktop neutralisation rules + one phone media block.
- Modify `courses/static/courses/js/builder.js` — phone hooks in existing functions + new "phone layout" section at the end.
- Modify `locale/pl/LC_MESSAGES/django.po` / `.mo`.
- Modify `tests/test_builder_js_invariants.py` — only if the setPanel regex needs to tolerate the added line (it should not).
- Create `tests/helpers_builder_phone.py` — shared e2e helpers.
- Create `tests/test_builder_phone_markup.py` (non-e2e render + CSS-source tests).
- Create `tests/test_e2e_builder_phone_desktop_guard.py`, `tests/test_e2e_builder_phone_layout.py`, `tests/test_e2e_builder_phone_sheet.py`, `tests/test_e2e_builder_phone_menu.py`, `tests/test_e2e_builder_phone_rename.py`, `tests/test_e2e_builder_phone_flows.py`.

## Shared names (used across tasks)

DOM hooks (all server-rendered in Task 1):

| Hook | Element | Notes |
|---|---|---|
| `[data-phone-move="io"]` | `<span class="builder__movable">` around Import + Export | inside `header.manage__head` |
| `[data-phone-move="bulk"]` | `<span class="builder__movable">` around Expand all + Collapse all | inside header, after the filter form |
| `[data-phone-move="legends"]` | `<div class="builder__movable">` around structure legend + flag legend + `p.helptext` | after the header |
| `[data-sheet-course]` | `<button type="button" class="btn btn--ghost btn--small builder__kurs">{% trans "Course" %}</button>` | in header, directly after the h1 |
| `[data-sheet]` | `<div class="builder__sheet">` wrapping dim + panel shell | replaces `.builder__panel`'s position in `.builder` |
| `[data-sheet-dim]` | `<div class="builder__sheet-dim">` | first child of `[data-sheet]` |
| `[data-sheet-shell]` | `<div class="builder__sheet-shell">` | holds head + body |
| `[data-sheet-grab]` | `<div class="builder__sheet-head">` containing `<span class="builder__sheet-grabber" aria-hidden="true">` and the close button | swipe area |
| `[data-sheet-close]` | `<button type="button" class="builder__sheet-close" aria-label="{% trans 'Close' %}">×</button>` | stable focus target |
| `[data-sheet-body]` | `<div class="builder__sheet-body">` | the single phone scroll container |
| `[data-sheet-tools]` | `<div class="builder__sheet-tools">` | receives moved containers; first child of body |
| `[data-panel]` | existing `.builder__panel` | moved inside body, unchanged |
| `[data-toast]` | `<div class="builder__toast" role="alert" hidden>` | sibling of `[data-sheet]` inside `.builder` |
| `[data-row-menu]` / `id="row-menu"` | `<div class="row-menu" hidden>` | last child of `.builder__tree` |
| `.tree__ptitle` | phone title button per row | inside `form.tree__rowhead`, right after `input.tree__title` |
| `.tree__more` | ⋯ button per row | last child of `form.tree__rowhead` (after `.tree__cluster`) |

Row-menu items (inside `[data-row-menu]`, all `<button type="button" class="row-menu__item">`, attribute `data-menu-action`): `rename`, `up`, `down`, `move`, `duplicate`, `export`, `delete` (in that order; `delete` also has class `row-menu__item--danger`). Plus `<p class="row-menu__title" data-menu-title></p>` first and `<p class="row-menu__reason" data-menu-reason hidden>{% trans "Clear the filter to reorder." %}</p>` after `down`.

Row-control mapping (menu action → the row's real control, found inside the row's own `:scope > form.tree__rowhead`):
`up` → `button[data-op="reorder"][value="up"]`; `down` → `button[data-op="reorder"][value="down"]`; `move` → `a[data-move]`; `duplicate` → `button[data-op="duplicate"]` (absent for containers → item hidden); `export` → `a.icm--download`; `delete` → `a[data-delete]`.

JS (phone section of builder.js; private to the IIFE):
- `var PHONE_MQ = "(pointer: coarse) and (max-width: 959.98px)"; var phoneMq = window.matchMedia(PHONE_MQ); function isPhone() { return phoneMq.matches; }`
- `function invalidatePanel()` — `panelReq++`; clear and null `panelTimer`.
- `function openSheet(mode, opener)` — `mode` ∈ `"course" | "node" | "move"`; `opener` is `{ pk: string|null, target: "title" | "more" | "kurs" }`.
- `function closeSheet(opts)` — `opts = { focus: true|false }` (default true); returns nothing.
- `function sheetIsOpen()` → boolean.
- `function returnFocus(opener)` — focus rules from the spec's "Escape and focus layering".
- `function showToast(text)`.
- `function openMenu(moreBtn)`, `function closeMenu(restoreFocus)`, `var menuPk = null`.
- `function startPhoneRename(row)`, `function endPhoneRename(row, focusMore)`.
- `function syncPtitle(input)` — copies `input.defaultValue` into the row's `.tree__ptitle` text.
- `function moveToolbar(toPhone)`.
- `function applyLayout()` — run once at load and on `phoneMq` `change`.
- `var PLACEHOLDER_HTML` built from `root.getAttribute("data-msg-loading")`: `'<div class="panel" data-panel-loading><p class="panel__meta">Wczytywanie…</p></div>'` (text escaped via `escHtml`).

---

### Task 1: Markup scaffolding, desktop neutralisation, desktop guard

**Files:**
- Modify: `templates/courses/manage/builder.html`
- Modify: `templates/courses/manage/_tree_node.html`
- Modify: `courses/static/courses/css/builder.css` (new desktop-neutral rules, near the end of the file)
- Modify: `locale/pl/LC_MESSAGES/django.po`, `django.mo`
- Create: `tests/test_builder_phone_markup.py`
- Create: `tests/helpers_builder_phone.py`
- Create: `tests/test_e2e_builder_phone_desktop_guard.py`

**Interfaces:**
- Produces: every DOM hook in "Shared names"; root attribute `data-msg-loading="{% trans 'Loading…' %}"`; helper module functions below.
- `tests/helpers_builder_phone.py` exports:
  - `make_pa_user(username) -> User` and `login(page, live_server, username) -> None` (same bodies as `tests/test_e2e_builder_tree_layout.py`'s `_make_pa_user`/`_login`).
  - `seed_course(slug="phone-demo", long_title=False) -> dict` creating a course with parts/chapters/sections on: part "Geometria analityczna i przekształcenia" › chapter "Izometrie" › section "Przekształcenia" › lessons "Wprowadzenie do przekształceń płaszczyzny", "Izometria", "Czy przekształcenie jest izometrią?" (each with one TextElement) and a quiz "Sprawdzian: izometrie"; plus a second chapter "Okręgi i proste w układzie współrzędnych" with one lesson. Returns `{"course", "part", "chapter", "section", "lessons": [...], "quiz", "chapter2"}`. With `long_title=True` the course title is 120 chars and lesson[0]'s title is 180 chars including one unbroken 60-char word.
  - `phone_context(browser, orientation="portrait") -> BrowserContext` — `browser.new_context(viewport={"width": 390, "height": 844} | {"width": 890, "height": 410}, has_touch=True, is_mobile=True, device_scale_factor=2)`.
  - `assert_phone(page)` — asserts `page.evaluate("() => matchMedia('(pointer: coarse) and (max-width: 959.98px)').matches")` is True.
  - `assert_desktop(page)` — asserts the same expression is False.
  - `builder_url(live_server, course) -> str` → `f"{live_server.url}/manage/courses/{course.slug}/build/?open=all"`.
  - `cdp_swipe(page, x, y_from, y_to, steps=8)` — `cdp = page.context.new_cdp_session(page)`; `Input.dispatchTouchEvent` `touchStart` at (x, y_from), `steps` `touchMove`s linearly to y_to, `touchEnd`.
  - `cdp_touch_scroll(page, x, y_from, y_to)` — same as `cdp_swipe` (alias used for scroll attempts).

- [ ] **Step 1: Write the failing render test** in `tests/test_builder_phone_markup.py` (Django `client`, PA user via `make_pa_user`, `force_login`, GET `/manage/courses/<slug>/build/?open=all`):
  - `test_builder_renders_phone_scaffolding`: response HTML contains exactly one each of `data-sheet`, `data-sheet-dim`, `data-sheet-grab`, `data-sheet-close`, `data-sheet-body`, `data-sheet-tools`, `data-toast`, `data-row-menu`, `data-sheet-course`; three `data-phone-move=` (values `io`, `bulk`, `legends`); `data-panel` appears inside `data-sheet-body` (parse with `bs4.BeautifulSoup`, assert `soup.select_one("[data-sheet-body] [data-panel]")`); `[data-row-menu]` is a descendant of `.builder__tree`; the seven `data-menu-action` values in order `rename, up, down, move, duplicate, export, delete`.
  - `test_every_row_has_ptitle_and_more`: for every `li.tree__row`, its `form.tree__rowhead` has exactly one `button.tree__ptitle[type=button]` whose text equals the input's `value`, and exactly one `button.tree__more[type=button][aria-expanded=false][aria-controls=row-menu]`; the FIRST `button[type=submit]` in the form is still the visually-hidden Rename button.
  - `test_container_badges_carry_a_letter`: every `.tree__badge--part/--chapter/--section` has `data-letter` equal to the first character (uppercased) of its text; unit badges have no `data-letter`.
  - `test_header_order_unchanged`: the visible header controls in DOM order are h1, Kurs, Import, Export, filter form, Expand all, Collapse all.
- [ ] **Step 2: Run it** — `TEST_DATABASE_URL=… uv run pytest tests/test_builder_phone_markup.py -p no:xdist` → FAIL (hooks missing).
- [ ] **Step 3: Implement the markup.**
  - `builder.html`: add the three `.builder__movable` wrappers around exactly the nodes listed; add the Kurs button after the h1; add `data-msg-loading`; move `<div class="builder__panel" data-panel>` inside `[data-sheet] > [data-sheet-shell] > [data-sheet-body]` after `[data-sheet-tools]`; add `[data-toast]` after `[data-sheet]`; add the row menu as the last child of `.builder__tree` (items' visible labels: `{% trans "Rename" %}`, `{% trans "Move up" %}`, `{% trans "Move down" %}`, `{% trans "Move…" %}`, `{% trans "Duplicate" %}`, `{% trans "Export subtree" %}`, `{% trans "Delete" %}` — all existing msgids).
  - `_tree_node.html`: after `input.tree__title` add `<button type="button" class="tree__ptitle">{{ node.title }}</button>`; after `.tree__cluster` add `<button type="button" class="ica tree__more" aria-expanded="false" aria-controls="row-menu" aria-label="{% trans 'More actions' %}"></button>`; on the container badge add `data-letter="{{ node.get_kind_display|first|upper }}"`.
  - `builder.css` desktop neutralisation (outside any media query): `.builder__sheet, .builder__sheet-shell, .builder__sheet-body, .builder__movable { display: contents; }` and `.builder__sheet-dim, .builder__sheet-head, .builder__sheet-tools, .builder__toast, .builder__kurs, .tree__ptitle, .tree__more, .row-menu { display: none; }`.
  - i18n: `uv run python manage.py makemessages -l pl`, set "More actions" → "Więcej akcji", clear fuzzy flags on touched entries, `compilemessages -l pl`.
- [ ] **Step 4: Run the render test** → PASS.
- [ ] **Step 5: Write the desktop guard e2e** `tests/test_e2e_builder_phone_desktop_guard.py::test_desktop_window_keeps_desktop_layout` (default `page` fixture, `page.set_viewport_size({"width": 945, "height": 800})`, `assert_desktop(page)`, `seed_course()` with enough rows to scroll — add 30 extra lessons under chapter2):
  - `.tree__ptitle`, `.tree__more`, `.builder__kurs`, `[data-sheet-grab]`, `[data-toast]` are not visible; `input.tree__title` is visible.
  - `[data-panel]` bounding box `x` > tree's right edge (two columns) and `.builder` has exactly 2 grid columns (`getComputedStyle(root).gridTemplateColumns.split(" ").length == 2`) and `.builder`'s child grid items' rows: the panel's `top` equals the tree's `top` ±2 px (no new grid row).
  - After `page.mouse.wheel(0, 2500)` and waiting for `scrollY > 1000`, `[data-panel]`'s `boundingClientRect().top` is between 0 and 40 (sticky still works).
  - Neither `[data-sheet]` nor `[data-panel]` has the `inert` attribute; `getComputedStyle(panel).visibility == "visible"`; pressing Tab from the last course-panel-preceding focusable reaches a link inside `[data-panel]` (focus the filter input, then Tab until `document.activeElement.closest('[data-panel]')` or 200 presses; assert reached).
  - Clicking a lesson's `input.tree__title` focuses it and loads its unit panel (`[data-panel] .panel[data-panel-for="<pk>"]` appears) — rename-in-place + focus loader intact.
- [ ] **Step 6: Run it on the pre-change commit to prove it discriminates** — `git stash` is forbidden (memory: never revert with checkout/stash); instead run it against a mutant: temporarily remove the `display: contents` line for `.builder__sheet, …` by hand, run → FAIL (panel no longer sticky / new grid row). Restore the line by hand, run → PASS. Record both outcomes in the task report.
- [ ] **Step 7: Run all CSS tests** — `uv run pytest tests/test_builder_styles.py $(ls tests/test_*css*.py) -p no:xdist` → PASS. Run the existing builder e2e suite at desktop: `uv run pytest tests/test_e2e_builder.py tests/test_e2e_builder_tree_layout.py tests/test_e2e_builder_reorder.py tests/test_e2e_builder_toggle.py tests/test_e2e_builder_filter.py tests/test_e2e_builder_ws2.py tests/test_e2e_builder_authoring.py -m e2e -p no:xdist` → all pass (some tests count badge text or header buttons — if one fails because of the new hidden markup, fix the markup, never the assertion, unless the assertion counted elements that are now legitimately present but hidden; justify any such edit in the report).
- [ ] **Step 8: Commit** — `git add templates/courses/manage/builder.html templates/courses/manage/_tree_node.html courses/static/courses/css/builder.css locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/helpers_builder_phone.py tests/test_builder_phone_markup.py tests/test_e2e_builder_phone_desktop_guard.py` · message `feat(builder): server-render phone scaffolding, neutral on desktop`.

### Task 2: Phone CSS layout (rows, header, sheet chrome, toast)

**Files:**
- Modify: `courses/static/courses/css/builder.css` (one new block at the end: `@media (pointer: coarse) and (max-width: 959.98px) { … }`)
- Modify: `tests/test_builder_phone_markup.py` (CSS source test)
- Create: `tests/test_e2e_builder_phone_layout.py`

**Interfaces:**
- Consumes: Task 1 hooks.
- Produces: CSS state classes JS will toggle: `.builder__sheet.is-open` (sheet visible), `.builder__sheet[data-mode="course"]` (tools visible), `.tree__rowhead.is-editing` (phone rename visible), `.builder__toast:not([hidden])`. Custom property `--phone-head-h` set by JS on `document.documentElement` (sticky header height, px) and used for `scroll-padding-top`.

Rules to write (all `.js`-prefixed, inside the media block; values are decisions):
- `.builder`: `display: block` (drops the 2-col grid); `.builder__tree`: `border-right: 0; padding-right: 0`.
- `.builder__panel`: `position: static; max-height: none; overflow: visible` (beats both the base sticky rule and the 720 px override).
- Header: `.builder__tree > .manage__head` `position: sticky; top: 0; z-index: 5; background: var(--surface-base); padding-block: var(--space-2); flex-wrap: wrap;` h1 `flex: 1 1 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 1.05rem`; `.builder__kurs { display: inline-flex }`; `.builder__filter { flex: 1 1 0; min-width: 0 }` so Kurs + filter share one row; the moved wrappers are hidden while still in the header (`.manage__head .builder__movable { display: none }`) — after JS moves them they live in `[data-sheet-tools]` where they become `display: flex; flex-wrap: wrap; gap: var(--space-2)`. `html.js { scroll-padding-top: var(--phone-head-h, 0px) }` (JS sets `--phone-head-h` on `document.documentElement`).
- Rows: `.tree__scope { padding-left: 8px; margin-left: 4px }`; `.tree__rowhead { align-items: flex-start }`; hide `input.tree__title:not(:focus)` unless `.is-editing` → `.tree__rowhead:not(.is-editing) > input.tree__title:not(:focus) { display: none }`; `.tree__rowhead.is-editing > .tree__ptitle { display: none }`; `.tree__ptitle { display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; flex: 1 1 0; min-width: 0; order: 4; text-align: left; background: none; border: 0; padding: 2px 0; font: inherit; color: var(--text-primary); }`; `.tree__row--draft .tree__ptitle { text-decoration: line-through }`; `.tree__rowhead > .tree__flag { order: 5 }`; `.tree__cluster { display: none }`; `.tree__more { display: inline-flex; order: 6 }` with a masked three-dot icon `--icm` (new `.tree__more::before` mask, same mechanism as `.icm--*`, three circles); container badges: `.tree__badge[data-letter] { font-size: 0; width: 22px; height: 22px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; padding: 0 }` and `::before { content: attr(data-letter); font-size: .7rem; }`; touch targets ≥ 32 px for `.tree__more`, flags and toggle (`min-width/min-height: 32px`).
- Sheet: `.builder__sheet { display: block; position: fixed; inset: 0; z-index: 40; visibility: hidden; pointer-events: none }`; `.builder__sheet.is-open { visibility: visible; pointer-events: auto }`; `.builder__sheet-dim { display: block; position: absolute; inset: 0; background: rgb(0 0 0 / .45); opacity: 0; transition: opacity .2s }` / `.is-open .builder__sheet-dim { opacity: 1 }`; `.builder__sheet-shell { display: flex; flex-direction: column; position: absolute; left: 0; right: 0; bottom: 0; height: 67dvh; background: var(--surface-raised); border-radius: 16px 16px 0 0; box-shadow: var(--shadow-lg, 0 -8px 24px rgb(0 0 0 / .35)); transform: translateY(100%); transition: transform .22s ease }` / `.is-open .builder__sheet-shell { transform: translateY(var(--sheet-drag, 0px)) }`; landscape: nested `@media (orientation: landscape) { .js .builder__sheet-shell { height: 94dvh } }`; `.builder__sheet-head { display: flex; align-items: center; justify-content: center; position: relative; min-height: 40px; touch-action: none }`; grabber 40×4 px bar `var(--border-strong)`; close button absolute right, 40×40; `.builder__sheet-body { display: block; flex: 1 1 auto; overflow-y: auto; overscroll-behavior: contain; padding: 0 var(--space-4) var(--space-4) }`; `.builder__sheet-tools { display: none }` / `[data-mode="course"] .builder__sheet-tools { display: block; padding-bottom: var(--space-3); border-bottom: 1px solid var(--border-subtle); margin-bottom: var(--space-3) }`; `@media (prefers-reduced-motion: reduce)` → no transitions.
- Toast: `.builder__toast { display: block; position: fixed; left: var(--space-3); right: var(--space-3); bottom: var(--space-4); z-index: 60; }` with the same colours as `.builder__panel > .op-error`; `[hidden]` keeps it hidden.
- Menu: `.row-menu { display: block; position: fixed; left: var(--space-3); right: var(--space-3); bottom: var(--space-3); z-index: 50; background: var(--surface-raised); border: 1px solid var(--border-default); border-radius: 12px; box-shadow: …; max-height: 80dvh; overflow-y: auto }` (my call: a bottom action sheet, not anchored to ⋯); `[hidden]` hides it; `.row-menu__title` unclamped, `overflow-wrap: anywhere`, secondary colour; items full-width 44 px tall; `.row-menu__item--danger { color: var(--danger) }`; `.row-menu__item:disabled { opacity: .45 }`.
- Inert dimming of the tree is provided by the dim layer (it covers the tree), no extra rule.

- [ ] **Step 1: Write the CSS source test** `test_phone_rules_are_js_scoped` in `tests/test_builder_phone_markup.py`: read builder.css, extract the block(s) starting `@media (pointer: coarse) and (max-width: 959.98px)` (brace-matched); assert at least one exists; assert every selector list inside (split rules on `{`, skip nested `@media` headers) has every comma-separated selector starting with `.js ` or `html.js`. Also `test_no_any_pointer`: `any-pointer` does not occur in builder.css.
- [ ] **Step 2: Write the e2e** `tests/test_e2e_builder_phone_layout.py` (phone context per test; close in `finally`):
  - `test_portrait_rows`: 390×844, `assert_phone`; every visible row shows `.tree__ptitle` and `.tree__more`, `input.tree__title` hidden, `.tree__cluster` hidden, grip hidden; a container badge's rendered width ≤ 26 px; ptitle of the 180-char lesson has `getClientRects`-based line count 2 (height between 1.8× and 2.3× its computed line-height) and `scrollWidth <= clientWidth + 1`; flags are to the right of the ptitle (`flag.x > ptitle.x`).
  - `test_landscape_geometry`: 890×410, course with `long_title=True`; top-level part row's ptitle width > 0.60 × 890; the deepest lesson's ptitle width > 0.45 × 890; `header.manage__head` height ≤ 0.25 × 410 and h1 is single-line (height ≤ 1.5× line-height); Kurs and filter share a row (their `top` equal ±4).
  - `test_sticky_header`: portrait, scroll to bottom (`cdp_touch_scroll` up the screen until `scrollY > 600`), header `top` == 0 ±1 and its background is opaque (`getComputedStyle(head).backgroundColor` alpha == 1).
  - `test_without_js_keeps_desktop_rows`: context with `java_script_enabled=False`, has_touch, 390×844: `input.tree__title` visible, `.tree__ptitle` not visible, `.tree__more` not visible, cluster visible.
- [ ] **Step 3: Run both** → FAIL (no phone CSS yet).
- [ ] **Step 4: Implement the phone media block** per the rules above (JS-independent parts only; the toolbar move and `--phone-head-h` come in Task 3 — for `test_landscape_geometry` the hidden-in-header wrappers already keep the header short).
- [ ] **Step 5: Run both** → PASS. Run all CSS tests + Task 1's desktop guard → PASS.
- [ ] **Step 6: Mutant check** — change `max-width: 959.98px` to `max-width: 359px` by hand → `test_portrait_rows` FAILs; restore by hand → PASS.
- [ ] **Step 7: Commit** — paths: `courses/static/courses/css/builder.css tests/test_builder_phone_markup.py tests/test_e2e_builder_phone_layout.py` · `feat(builder): phone layout CSS for rows, header, sheet and menu`.

### Task 3: Phone mode controller, sheet open/close, Kurs sheet, toolbar move

**Files:**
- Modify: `courses/static/courses/js/builder.js` (new section `// ---- phone layout ----` at the end of the IIFE, plus: `focusin` loader early-return on phone; `setPanel` resets `sheetBody.scrollTop`)
- Create: `tests/test_e2e_builder_phone_sheet.py`

**Interfaces:**
- Consumes: Task 1 hooks, Task 2 classes.
- Produces: `isPhone`, `invalidatePanel`, `openSheet`, `closeSheet`, `sheetIsOpen`, `returnFocus`, `moveToolbar`, `applyLayout`, `PLACEHOLDER_HTML`.

Behaviour to implement (decisions):
- `setPanel(html)`: append `if (sheetBody) sheetBody.scrollTop = 0;` inside the existing body (declare `var sheetBody = root.querySelector("[data-sheet-body]");` next to `panel` at the top). Keep the regex in `test_builder_js_invariants.py` green (no `}` before the existing `scrollTop = 0`).
- `focusin` handler (builder.js "Inline rename: selection"): after the timer clearing, `if (isPhone()) return;`. `isPhone`/`phoneMq` must therefore be declared near the top of the IIFE (hoist the two `var`s and the function to just after `neutralPanel`).
- `openSheet(mode, opener)`: close the row menu (`closeMenu(false)` — stub until Task 5: define `function closeMenu() {}` placeholder here, replaced in Task 5), `root.querySelectorAll("[data-flag-strip]").forEach(dismissStrip)` without focus side effects (call `strip.remove()` directly), set `sheet.dataset.mode = mode`, remember `sheetOpener = opener`, save `lockedY = window.scrollY`, lock page scroll by `document.documentElement.classList.add("builder-sheet-lock")` + CSS `html.builder-sheet-lock body { position: fixed; top: calc(-1 * var(--lock-y)); left: 0; right: 0 }` with `--lock-y` set to `lockedY + "px"` on `<html>` (add these two rules to the Task 2 media block in this task), `treePane.inert = true`, `sheet.inert = false`, `sheet.setAttribute("role","dialog")`, `aria-modal="true"`, `aria-label` = root `data-msg-details` (add `data-msg-details="{% trans 'Details' %}"` to builder.html), `sheet.classList.add("is-open")`, `sheetBody.scrollTop = 0`, `sheetClose.focus()`.
- `closeSheet(opts)`: if not open return; if `panel.querySelector("form.move-picker")` → `clearMoving(); setPanel(neutralPanel);` (picker cleanup without focus); `invalidatePanel()`; remove `is-open`, role, aria-modal, aria-label; `sheet.inert = true`; `treePane.inert = false`; unlock (remove class, `window.scrollTo(0, lockedY)`); `sheet.style.removeProperty("--sheet-drag")`; THEN if `opts.focus !== false` → `returnFocus(sheetOpener)`; `sheetOpener = null`.
- `returnFocus(opener)`: target = opener.target `"kurs"` → Kurs button; `"title"` → `.tree__ptitle` of `li.tree__row[data-node=pk]`; `"more"` → `.tree__more` of that row; if the element is missing or `!el.checkVisibility()` → Kurs button. Focus it with `{ preventScroll: false }`.
- Kurs click (`[data-sheet-course]`, delegated on root): `invalidatePanel(); setPanel(neutralPanel); openSheet("course", { pk: null, target: "kurs" })`.
- Close triggers: `[data-sheet-close]` click, `[data-sheet-dim]` click → `closeSheet()`.
- Escape owner: `document.addEventListener("keydown", fn, true)` (capture): if `!isPhone() || !sheetIsOpen() || e.key !== "Escape"` return; `e.preventDefault(); e.stopPropagation();` then if a picker shows → `dismissPicker()` (which, on phone, closes the sheet — Task 5 wires that; in this task closeSheet already cleans the picker, so call `closeSheet()`), else `closeSheet()`.
- Expand all / Collapse all on phone: a root click listener registered in the phone section: if `isPhone() && sheetIsOpen()` and target is `[data-expand-all]` with neither `aria-disabled="true"` nor root `data-expand-all-disabled`, or target is `[data-collapse-all]` → `closeSheet({ focus: true })` with `sheetOpener` forced to Kurs. The existing handlers still run (listener order irrelevant: neither stops propagation).
- Disabled Expand all explanation: in the phone media block, `.js [data-sheet-tools] [data-expand-all][aria-disabled="true"]::after { content: attr(title); display: block; font-size: .8rem; color: var(--text-secondary) }` (visible text from the existing `title`).
- `moveToolbar(toPhone)`: on first call create one `document.createComment("phone-move:" + key)` marker per `[data-phone-move]` node, inserted immediately after the node (so it marks the original slot). `toPhone` → append the three nodes to `sheetTools` in order io, bulk, legends; else → for each, `marker.parentNode.insertBefore(node, marker)`.
- `applyLayout()`: if `isPhone()` → `moveToolbar(true)`, `sheet.inert = true` (closed), set `--phone-head-h` on `document.documentElement` to the header's `offsetHeight + "px"`; else → `closeSheet({ focus: false })` if open, `moveToolbar(false)`, `sheet.inert = false`, `treePane.inert = false`, remove `--phone-head-h`, `setPanel(neutralPanel)` only when coming FROM phone (track `var wasPhone`), `clearMoving()`. Call once at load; `phoneMq.addEventListener("change", applyLayout)`. Desktop → phone with a picker showing: `dismissPicker`-style cleanup without focus (`clearMoving(); setPanel(neutralPanel)`); with a node panel: keep it.
- `pageshow`: `window.addEventListener("pageshow", function (e) { if (e.persisted && sheetIsOpen()) closeSheet({ focus: false }); })`.

- [ ] **Step 1: Write the failing e2e** `tests/test_e2e_builder_phone_sheet.py` (phone portrait unless stated):
  - `test_kurs_sheet_shows_course_panel_and_tools`: tap Kurs → `[data-sheet].is-open` visible; `[data-panel] .panel[data-panel-for="course"]` visible; `[data-sheet-tools]` contains Import, Export, Expand all, Collapse all, the structure legend, the flag legend, the help line (each visible); header still shows h1, Kurs, filter; `document.activeElement` is `[data-sheet-close]`.
  - `test_sheet_close_paths_restore_scroll_and_scopes`: scroll to `scrollY ≥ 400` with `cdp_touch_scroll`, record `scrollY` and the sorted list of `ol[data-scope]` values; for each of: ✕ tap, dim tap (tap at (195, 60)), `keyboard.press("Escape")`: open via Kurs, close, assert sheet hidden, `scrollY` equal ±1, scopes equal, focus on Kurs.
  - `test_modality_while_open`: open Kurs sheet; `.builder__tree` has `inert`; with the sheet open, pressing Tab 30 times never puts focus inside `.builder__tree`; a touch-drag scroll attempt inside the sheet body (`cdp_touch_scroll(page, 195, 780, 500)`) leaves `window.scrollY` unchanged. Then tap at a tree row's coordinates (covered by the dim): no request to `/build/node/` is made (record requests), the filter input is not focused, and the sheet closes (the dim-tap close rule) — no tree action happens.
  - `test_closed_sheet_is_unreachable`: sheet closed; focus the last row's ⋯ via `focus()`, press Tab 15 times: `document.activeElement.closest('[data-sheet]')` stays null each time.
  - `test_expand_collapse_close_sheet`: Kurs → Collapse all → sheet closes and no `ol[data-scope]` other than `top` remains; Kurs → Expand all → sheet closes and scopes reappear (wait for `ol[data-scope="<chapter pk>"]`). Bulk hrefs after a filter: type "Izo" into the filter, submit, wait for the filter response; Kurs → Expand all's `href` contains `q=Izo`.
  - `test_disabled_expand_all_keeps_sheet_open`: seed a course over `CEILING` is too heavy — instead set `expand_all_disabled` by monkeypatching `courses.builder_open.CEILING` to 1 via `settings`-free `monkeypatch.setattr` before the page load (the view reads the module constant; verify in `views_manage.py` which name it imports and patch that name); Kurs → tap Expand all → sheet stays open and the explanation text "This course is too large to expand at once." is visible inside `[data-sheet-tools]`.
  - `test_fresh_phone_load_moves_toolbar`: on load (no interaction) the three `[data-phone-move]` nodes are children of `[data-sheet-tools]`; `--phone-head-h` on `<html>` is a positive px value.
  - `test_pageshow_persisted_closes_sheet`: open Kurs sheet, `page.evaluate("() => window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")` → sheet closed, tree not inert.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the behaviour above.
- [ ] **Step 4: Run** the new file, Task 1 desktop guard, Task 2 layout file, `tests/test_builder_js_invariants.py` → PASS.
- [ ] **Step 5: Mutant check** — remove `treePane.inert = true` by hand → `test_modality_while_open` FAILs (Tab reaches the tree); restore → PASS. Remove the `window.scrollTo(0, lockedY)` → `test_sheet_close_paths_restore_scroll_and_scopes` FAILs; restore → PASS.
- [ ] **Step 6: Commit** — `courses/static/courses/js/builder.js courses/static/courses/css/builder.css templates/courses/manage/builder.html tests/test_e2e_builder_phone_sheet.py` · `feat(builder): phone sheet, Kurs sheet and toolbar move`.

### Task 4: Row tap → node panel in the sheet (placeholder, last-request-wins)

**Files:**
- Modify: `courses/static/courses/js/builder.js` (phone section; `loadPanel` failure path unchanged)
- Modify: `tests/test_builder_js_invariants.py` (no change expected; run it)
- Modify: `tests/test_e2e_builder_phone_sheet.py` (add tests)

**Interfaces:**
- Consumes: `openSheet`, `invalidatePanel`, `PLACEHOLDER_HTML`, existing `loadPanel(url)` and `data-panel-url` substitution (`tpl.replace(/\/0\/$/, "/" + pk + "/")`).
- Produces: `function openNodeSheet(row)`.

Behaviour: a root `click` listener for `.tree__ptitle` (phone only; on desktop the element is hidden anyway): `e.preventDefault(); openNodeSheet(row)` where `openNodeSheet` = `invalidatePanel(); setPanel(PLACEHOLDER_HTML); openSheet("node", { pk: row.dataset.node, target: "title" }); loadPanel(urlFor(row));` (setPanel BEFORE openSheet so the previous panel is never visible). Enter/Space on the button fire `click` natively. Update the comment above `setPanel` ("Nine call sites") to the new count — count the `setPanel(` call sites after Tasks 4–5 and write the number; keep it accurate at the end of Task 5 too.

- [ ] **Step 1: Write the failing tests** (append to `test_e2e_builder_phone_sheet.py`):
  - `test_tap_title_opens_that_units_panel`: tap lesson "Izometria"'s ptitle → sheet open, `[data-panel] .panel[data-panel-for="<pk>"]` visible with the h2 containing "Izometria"; `document.activeElement` is not an `input`/`textarea`/`[contenteditable]` and is inside `[data-sheet]`; close with ✕ → focus is that row's ptitle.
  - `test_placeholder_never_shows_previous_panel`: open lesson A's sheet, close; hold the next `/build/node/<B>/` GET (`page.route` on that URL, store the route, do not continue); tap B → assert `[data-panel] [data-panel-loading]` visible and no `.panel[data-panel-for="<A>"]` in the DOM; release the route → B's panel visible; `document.activeElement` still inside `[data-sheet]`.
  - `test_late_panel_response_is_dropped`: hold A's GET; tap A; close the sheet with ✕; tap Kurs → course panel; release A's route; wait 300 ms (negative assertion must outlive the response) → still the course panel. Second variant: hold A, tap A, close, tap B (unheld) → B's panel; release A → still B.
  - `test_panel_network_error_shows_in_sheet`: `page.route` the GET and `route.abort()` → the sheet shows "Network error — please reload.".
  - `test_keyboard_enter_opens_sheet`: `ptitle.focus(); keyboard.press("Enter")` → sheet open for that row; Escape → focus back on that ptitle.
  - `test_sheet_scroll_resets_between_opens`: Kurs sheet, scroll `[data-sheet-body]` to 200 (`el.scrollTop = 200` is acceptable here: it sets up state, it does not assert behaviour), close, tap a lesson → `[data-sheet-body]` `scrollTop == 0`; landscape context: `[data-panel]` `scrollHeight <= clientHeight + 1` (no own scroll).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `openNodeSheet` and the listener.
- [ ] **Step 4: Run** → PASS (plus invariants test and desktop guard).
- [ ] **Step 5: Mutant check** — swap the order to `openSheet(...)` before `setPanel(PLACEHOLDER_HTML)` and drop `invalidatePanel()` in `closeSheet` → `test_late_panel_response_is_dropped` FAILs; restore → PASS.
- [ ] **Step 6: Commit** — `courses/static/courses/js/builder.js tests/test_e2e_builder_phone_sheet.py` · `feat(builder): tap a title to open its panel in the phone sheet`.

### Task 5: Notices as a toast on the phone

**Files:**
- Modify: `courses/static/courses/js/builder.js` (`notice`, phone section `showToast`)
- Create: `tests/test_e2e_builder_phone_flows.py` (first tests)

**Interfaces:**
- Produces: `showToast(text)`; `notice(text)` routes to it on phone.

Behaviour: `notice(text)`: first line `if (isPhone()) { showToast(text); return; }` (desktop path unchanged). `showToast`: set `toast.textContent = text`, `toast.hidden = false`, clear any previous timer, `setTimeout(… hidden = true, 6000)`. Toast z-index above the sheet (Task 2 CSS: 60 > 40).

- [ ] **Step 1: Failing tests** in `tests/test_e2e_builder_phone_flows.py`:
  - `test_conflict_notice_visible_with_sheet_closed`: after page load, make a lesson's row token stale by calling `.save()` on that `ContentNode` instance (bumps `updated`); tap the row's publish toggle (visible on the phone row) → server 409 → `[data-toast]` visible with "This changed elsewhere — reloaded to the latest."; `[data-panel] .op-error` count == 0. (If the flag endpoint does not check the token, use the rename path instead once Task 7 exists — verify in `courses/views_manage.py` which ops return 409 and pick one reachable on the phone row now.)
  - `test_network_notice_toast`: `page.route("**/build/node/flag/**", lambda r: r.abort())` (verify the flag URL in `courses/urls.py` first and use its real path), tap a publish toggle → toast shows "Network error — please try again.".
  - `test_toast_hides_after_six_seconds`: after a toast, `expect(toast).to_be_hidden(timeout=8000)`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS; desktop guard still PASS; run `tests/test_e2e_builder_toggle.py` and any desktop test asserting `.op-error` in the panel → PASS.
- [ ] **Step 5: Commit** — `courses/static/courses/js/builder.js tests/test_e2e_builder_phone_flows.py` · `feat(builder): phone notices as a toast`.

### Task 6: The shared ⋯ row menu and Move… in the sheet

**Files:**
- Modify: `courses/static/courses/js/builder.js` (phone section: menu; Move… handler phone guard; `dismissPicker` phone branch; submit handler's `if (inPanel) setPanel(neutralPanel)` phone branch; replace the `closeMenu` stub)
- Create: `tests/test_e2e_builder_phone_menu.py`

**Interfaces:**
- Consumes: hooks, `openSheet`, `closeSheet`, `invalidatePanel`, `PLACEHOLDER_HTML`, `effectiveQ`, `appliedQ`, `initPicker`, `clearMoving`.
- Produces: `openMenu(moreBtn)`, `closeMenu(restoreFocus)`, `menuPk`, `function focusRowMore(pk)` (re-find + visibility fallback to Kurs).

Behaviour (decisions):
- `openMenu(moreBtn)`: if another opener is expanded, set it to `aria-expanded="false"`; close any open add row (`root.querySelectorAll("form.tree__add.is-adding").forEach(closeAdd)`); `menuPk = row.dataset.node`; title ← row's `input.tree__title.defaultValue`; for each action find the real control via the mapping; hide the item if the control is absent; `item.disabled = control.disabled || control.getAttribute("aria-disabled") === "true"`; reason paragraph visible iff `effectiveQ(appliedQ) !== ""` and the up or down item is disabled; `menu.hidden = false`; `moreBtn.setAttribute("aria-expanded","true")`; focus the first enabled item.
- `closeMenu(restoreFocus)`: `menu.hidden = true`; reset the opener's `aria-expanded`; if `restoreFocus` → `focusRowMore(menuPk)`; `menuPk = null`.
- Menu click (`[data-menu-action]`, listener on the menu element — the menu is inside root, so ALSO guard: the root's other delegated listeners ignore it because the menu carries no hook attributes): re-find `li.tree__row[data-node="<menuPk>"]`; if missing → `closeMenu(false)` and stop. `rename` → `closeMenu(false); startPhoneRename(row)` (Task 7; until then a stub `function startPhoneRename() {}`). `move` → `closeMenu(false); control.click()`. All others → `focusRowMore(menuPk)` first, `closeMenu(false)`, then `control.click()`; after the op response the row is replaced — restore focus: record `pendingFocusPk = menuPk` and, in the submit handler right after `applyFragment(text)` (existing line), add `if (pendingFocusPk && isPhone()) { focusRowMore(pendingFocusPk); pendingFocusPk = null; }`.
- Outside tap: a `document` `pointerdown` listener closes the menu when the target is outside the menu and not a `.tree__more`. Escape: in the capture handler from Task 3 extend: if `!sheetIsOpen()` and the menu is open → `preventDefault(); closeMenu(true)`. If the opener row is replaced while the menu is open (detect in the submit handler after `applyFragment`: `if (menuPk && !menuOpener.isConnected) closeMenu(false)`).
- `.tree__more` click (root delegated): `e.preventDefault(); if (menuPk === row.dataset.node && !menu.hidden) closeMenu(true); else openMenu(btn)`.
- Move… on phone (existing `[data-move]` handler): before the fetch, `if (isPhone()) { invalidatePanel(); setPanel(PLACEHOLDER_HTML); openSheet("move", { pk: String(nodePk), target: "more" }); var moveReq = ++panelReq; }` and in the `.then` before `setPanel(html)`: `if (isPhone() && moveReq !== panelReq) return;` (desktop path untouched).
- `dismissPicker()` on phone: replace the focus part — `var pk = movingPk; setPanel(neutralPanel); clearMoving(); if (isPhone()) { closeSheet({ focus: false }); focusRowMore(pk); return; }` then the existing desktop focus code.
- Picker submit success/409 on phone: in the existing `if (inPanel) setPanel(neutralPanel);` line, change to `if (inPanel) { var movedPk = movingPk; setPanel(neutralPanel); if (isPhone()) { closeSheet({ focus: false }); focusRowMore(movedPk); } }` — note `clearMoving()` on the next line must still run; capture `movingPk` BEFORE it.
- Picker 422 on phone: unchanged (`notice` → toast, sheet stays open with the picker).

- [ ] **Step 1: Failing tests** `tests/test_e2e_builder_phone_menu.py`:
  - `test_menu_lists_items_in_order`: tap a lesson's ⋯ → menu visible; visible item labels in order "Zmień nazwę/Rename", "Move up", "Move down", "Move…", "Duplicate", "Export subtree", "Delete" (assert against the active language's rendered strings by reading them from the template-rendered DOM, i.e. compare `data-menu-action` order); title shows the full lesson title; focus on the first enabled item; the ⋯ has `aria-expanded="true"`; for a chapter row "Duplicate" is hidden.
  - `test_first_and_last_disabled`: first lesson's menu → Move up disabled; last unit's menu → Move down disabled.
  - `test_filter_reason_visible`: apply filter "Izo" → open a menu → up and down disabled and the reason "Clear the filter to reorder." visible.
  - `test_move_up_via_menu_keeps_focus`: lesson 2 ⋯ → Move up → wait for the order change (lesson 2 now first in its scope) → `document.activeElement` is lesson 2's `.tree__more`.
  - `test_duplicate_via_menu`: lesson 1 ⋯ → Duplicate → a new row "… (kopia)" (read the actual suffix the server uses: check `courses/builder.py:duplicate_unit` and use that) appears directly after it.
  - `test_delete_href_carries_open_set`: ⋯ → Delete → the browser navigates to the confirm page whose URL has an `open=` parameter listing the open scopes (assert `"open=" in page.url` and the chapter pk is in it).
  - `test_menu_escape_and_outside_tap`: Escape closes the menu and focuses the ⋯; tap on the sticky header closes it.
  - `test_menu_escape_over_strip`: tap a chapter's publish anchor (opens the confirm strip), then that row's ⋯ → menu opens; Escape → menu closed, strip still present.
  - `test_move_via_menu_in_sheet`: lesson 1 ⋯ → Move… → sheet open (mode move) showing the picker (`form.move-picker`), `[data-sheet-tools]` hidden; choose chapter2 as destination (tap `.move-dest[data-dest="<chapter2 pk>"]`), tap the submit → sheet closes, lesson 1 is now under chapter2, focus on lesson 1's ⋯.
  - `test_move_sheet_escape_dismisses_picker`: Move… → Escape → sheet closed, no `.moving` row, Kurs sheet afterwards shows the course panel (no picker); focus on that row's ⋯.
  - `test_move_sheet_close_by_dim_cleans_up`: Move… → dim tap → no `.moving` row.
  - `test_late_picker_is_dropped`: hold the picker GET; ⋯ → Move… → placeholder visible; ✕; release → no `.moving` row; Kurs → course panel, no `form.move-picker`.
  - `test_picker_422_toast_over_sheet`: Move… → choose a destination → `page.route` the move POST to fulfil `status=422, body="<p>That move isn't allowed here.</p>"` → toast visible and its bounding box is on top (`document.elementFromPoint(toastCenter)` is inside the toast) while the sheet is open.
  - `test_focus_returns_to_replaced_row`: ⋯ → Move… on lesson 2, choose its own section as destination and the first slot, submit → the scope is re-rendered (`applyFragment` replaces the row element) → focus is on the NEW lesson-2 `.tree__more` (assert `document.activeElement.closest('li').dataset.node == str(pk)` and that the element `isConnected`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the menu file + sheet file + desktop guard + `tests/test_e2e_builder_reorder.py tests/test_e2e_builder.py` (desktop Move… unchanged) → PASS.
- [ ] **Step 5: Mutant check** — make the `move` action copy `href` into `location.href` instead of `control.click()` → `test_move_via_menu_in_sheet` FAILs (no picker, full navigation); restore. Remove the `moveReq !== panelReq` guard → `test_late_picker_is_dropped` FAILs; restore.
- [ ] **Step 6: Commit** — `courses/static/courses/js/builder.js tests/test_e2e_builder_phone_menu.py` · `feat(builder): shared row menu and Move… in the phone sheet`.

### Task 7: Phone rename

**Files:**
- Modify: `courses/static/courses/js/builder.js` (`applyRename`, `revert` → `syncPtitle`; phone section `startPhoneRename`/`endPhoneRename`; rename keydown/focusout phone hooks; replace stub)
- Create: `tests/test_e2e_builder_phone_rename.py`

**Interfaces:**
- Consumes: existing `commitRename(input)`, `revert(input)`, `applyRename(form, html)`, `titleForm(input)`, `form.dataset.submitting`.
- Produces: `startPhoneRename(row)`, `endPhoneRename(row, focusMore)`, `syncPtitle(input)`; per-row state `rowhead.classList.contains("is-editing")` and `rowhead.dataset.renameExit` ∈ `"keys" | "blur"` (set when the exit trigger is known).

Behaviour (decisions, mapping the spec's exit table onto existing code paths):
- `syncPtitle(input)`: `row.querySelector(":scope > form.tree__rowhead > .tree__ptitle").textContent = input.defaultValue`. Called at the end of `applyRename` (after `input.defaultValue = title`) and of `revert`.
- `startPhoneRename(row)`: add `is-editing` to the rowhead; focus the input; `input.select()`.
- `endPhoneRename(row, focusMore)`: if `focusMore` → `focusRowMore(pk)` FIRST; then remove `is-editing` (the input is hidden by CSS only after it lost focus — CSS hides `:not(:focus)` anyway).
- Escape (existing keydown branch): after `revert(input)`, `if (isPhone() && rowhead.classList.contains("is-editing")) endPhoneRename(row, true)`.
- Enter: existing `commitRename(input)`. Detect the no-request case: if `trimmed === defaultValue.trim()` → `if (isPhone()) endPhoneRename(row, true)`; if invalid (empty) → stay. Implement by giving `commitRename` a return value: `"unchanged" | "invalid" | "sent" | "busy"` (callers that ignore it are unaffected). Before `requestSubmit()` set `form.dataset.renameExit = "keys"` (Enter) — the focusout path sets `"blur"`.
- focusout (existing handler): on phone, branch 4 (emptied → revert) and an `"unchanged"` result → `endPhoneRename(row, false)`; `"sent"` → `form.dataset.renameExit = "blur"`.
- Response handling in the submit handler (op `rename`): after `applyRename(form, text)` on 200: `if (isPhone()) finishRenameExit(form)`; on 409 (after `applyFragment`): `finishRenameExit(form)` using the pk read before the swap; on 422: if `renameExit === "blur"` → `revert(input); endPhoneRename(row, false)` else stay editing (`releaseForm` already unlocks the input). `finishRenameExit(form)`: `endPhoneRename(row, form.dataset.renameExit === "keys")` (blur exits never move focus), then delete `dataset.renameExit`. Read the row pk BEFORE `applyFragment` and re-find the row after it.
- Desktop → phone flip during a rename: in `applyLayout()` when becoming phone, if `document.activeElement` is an `input.tree__title` → add `is-editing` to its rowhead (the CSS already never hides a focused input).

- [ ] **Step 1: Failing tests** `tests/test_e2e_builder_phone_rename.py` (record POSTs to the rename URL with `page.on("request")`):
  - `test_rename_escape`: ⋯ → Rename → input visible + focused; type "Nowa" → Escape → 0 POSTs, ptitle text unchanged, input hidden, focus on the ⋯.
  - `test_rename_enter_commits`: ⋯ → Rename → fill "Izometria — część 2" → Enter → exactly 1 POST; ptitle shows the new title; focus on ⋯.
  - `test_rename_enter_unchanged`: ⋯ → Rename → Enter → 0 POSTs, editing ended, focus on ⋯.
  - `test_rename_empty_blur_reverts`: ⋯ → Rename → clear the field → tap the filter input → 0 POSTs, title reverted, focus in the filter.
  - `test_rename_blur_commit_keeps_focus`: ⋯ → Rename → type → tap the filter → 1 POST; after the response, focus still in the filter; ptitle updated.
  - `test_rename_blur_409_keeps_focus_in_sheet`: make the lesson's token stale (`node.save()`), ⋯ → Rename → type; hold the rename POST with `page.route` (it is a fetch, not a navigation, so holding is safe); tap another row's ptitle (the blur sends the POST, the tap opens that row's sheet) → `route.continue_()` → the server answers 409 → focus is inside `[data-sheet]`.
  - `test_rename_422_after_enter_stays_editing`: fulfil the rename POST with 422 → the field stays visible and editing, toast visible.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the rename file + `tests/test_e2e_builder.py` (desktop rename tests) + `tests/test_e2e_builder_authoring.py` → PASS.
- [ ] **Step 5: Mutant check** — make `finishRenameExit` always focus ⋯ → `test_rename_blur_commit_keeps_focus` FAILs; restore.
- [ ] **Step 6: Commit** — `courses/static/courses/js/builder.js tests/test_e2e_builder_phone_rename.py` · `feat(builder): rename via the row menu on the phone`.

### Task 8: Swipe down to close

**Files:**
- Modify: `courses/static/courses/js/builder.js` (phone section)
- Modify: `tests/test_e2e_builder_phone_sheet.py`

**Interfaces:**
- Consumes: `closeSheet`, `[data-sheet-grab]`, CSS var `--sheet-drag` on `[data-sheet]`'s shell (Task 2 uses `translateY(var(--sheet-drag, 0px))`).

Behaviour: `pointerdown` on `[data-sheet-grab]` with `e.pointerType === "touch"` and the target not the close button → record `startY`, `setPointerCapture`, disable the shell transition (`shell.style.transition = "none"`). `pointermove` → `dy = Math.max(0, e.clientY - startY)`; set `--sheet-drag: dy + "px"` on the shell. `pointerup` → threshold `Math.min(80, shell.offsetHeight / 4)`; restore transition; if `dy >= threshold` → `closeSheet()` else remove `--sheet-drag` (snap back). `pointercancel` → snap back. A press with `dy < 4` is a tap, never a close.

- [ ] **Step 1: Failing tests:** `test_swipe_down_closes`: Kurs → `cdp_swipe(page, 195, head_y, head_y + 200)` → sheet closed, focus on Kurs. `test_short_swipe_snaps_back`: swipe 30 px → sheet open, shell `transform` back to `translateY(0px)` (or `none`) after 400 ms. `test_tap_on_header_is_not_a_swipe`: tap the grabber → sheet stays open.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Mutant check** — remove `touch-action: none` from `.builder__sheet-head` → `test_swipe_down_closes` FAILs (pointercancel); restore. If it does NOT fail, record that in the task report (it means CDP touch does not trigger browser panning here) and keep the rule anyway.
- [ ] **Step 6: Commit** — `courses/static/courses/js/builder.js tests/test_e2e_builder_phone_sheet.py` · `feat(builder): swipe the phone sheet down to close`.

### Task 9: Layout flips, confirm strip, end-to-end flows, landscape

**Files:**
- Modify: `courses/static/courses/js/builder.js` (only if the tests find a gap)
- Modify: `courses/static/courses/css/builder.css` (only if the strip needs a phone tweak)
- Modify: `tests/test_e2e_builder_phone_flows.py`

**Interfaces:** Consumes everything above.

- [ ] **Step 1: Write the tests** (append to `tests/test_e2e_builder_phone_flows.py`):
  - `test_split_a_unit_flow` (spec test 1): filter "Izometria" → ⋯ Duplicate on "Izometria" → ⋯ Rename the copy to "Izometria II" (ptitle changes) → tap "Izometria II" → sheet shows its unit panel (h2 contains "Izometria II", not the original) → tap "Open editor →" → URL is `/manage/courses/<slug>/build/unit/<copy pk>/edit/`.
  - `test_confirm_strip_on_phone` (spec test 7): tap the chapter's publish anchor → `[data-flag-strip]` visible, its bounding box within 0..390 horizontally; ✕ dismisses; reopen; Escape dismisses.
  - `test_flip_phone_to_desktop_with_sheet_open` (spec test 9): touch context at 900×800 (`assert_phone`), open a lesson sheet → `page.set_viewport_size({"width": 1000, "height": 800})` → `assert_desktop` → sheet not open, `.builder__tree` not inert, `[data-sheet]` not inert, `[data-panel]` shows the course panel and is visible, the three movable nodes are back in their original positions (header child order equals Task 1's `test_header_order_unchanged` order, legends div directly after the header), Tab from the filter reaches a link in `[data-panel]`.
  - `test_flip_desktop_to_phone_with_picker`: touch context at 1000×800 (desktop), click a lesson's Move… icon (`a[data-move]`) → picker in the panel → resize to 900×800 → picker dismissed (no `form.move-picker`, no `.moving`), sheet closed, toolbar in `[data-sheet-tools]`, Kurs visible.
  - `test_flip_desktop_to_phone_mid_rename`: touch context at 1000×800, click a lesson title input, type "abc" (dirty) → resize to 900×800 → force layout (`page.evaluate("() => document.body.offsetHeight")`) → 0 rename POSTs, the input still visible and focused with the typed value, rowhead has `is-editing`.
  - `test_landscape_split_flow_smoke`: landscape context, tap a lesson → sheet height ≥ 0.9 × 410 (shell `offsetHeight`), panel visible.
- [ ] **Step 2: Run** → expect PASS for most; any FAIL is a real gap — fix it in builder.js/builder.css with the smallest change and note it in the report.
- [ ] **Step 3: Full phone + desktop regression run** — all new phone e2e files, Task 1 guard, and the existing builder e2e files listed in Task 1 Step 7, plus `tests/test_builder_*.py tests/test_manage_builder.py tests/test_builder_phone_markup.py` and all CSS tests → PASS (grep the summary line).
- [ ] **Step 4: Commit** — `tests/test_e2e_builder_phone_flows.py` (+ any fixed source files by explicit path) · `test(builder): phone flows, flips and confirm strip`.

## Final verification (controller, after all tasks)

- `uv run ruff check .` and `uv run ruff format --check .` → clean.
- Screenshots (scratchpad, not committed): phone portrait (tree, ⋯ menu, node sheet, Kurs sheet) and landscape (tree, node sheet) in light AND dark (`page.emulate_media(color_scheme="dark")` plus whatever theme attribute base.html uses — check `data-theme` handling in `templates/base.html`), and one desktop 1280×800 shot of the builder for the no-regression check. Judge dark mode separately.
