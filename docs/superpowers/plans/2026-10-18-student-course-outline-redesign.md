# Student course outline redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the student course outline into numbered part cards with progress bars, status rings, a course-level progress bar, one clear next step, and "⋯" menus for every reset — without dropping any existing behaviour.

**Architecture:** All presentation data is computed once in Python by a new pure helper `_outline_presentation(outline, resume)` in `courses/views.py`, which stamps additive keys onto the `build_outline` dicts and returns head-level values. The templates (`outline.html`, `_outline_node.html`, `_resume_card.html`) only read those keys; `app.css` gets the visual system; `outline_tree.js` gets comments and an optional menu-close handler only. Strings land in English first and are translated in one i18n task.

**Tech Stack:** Django templates, plain CSS (tokens in `core/static/core/css/tokens.css`), vanilla JS, pytest + BeautifulSoup, Playwright (pytest-playwright, `-m e2e`).

**Spec:** `docs/superpowers/specs/2026-10-18-student-course-outline-redesign-design.md` — read it alongside this plan. Its §2 owner decisions (D1–D10, D3a, O12 supersession) are **protected**: no task may change their visible outcome.

## Global Constraints

- Every rule in spec §2 (D1–D10, D3a) and §2.1 is binding; the spec section cited in each step is the authority for exact values.
- No model, migration, URL, `build_outline` or `build_resume` behaviour change.
- No new colours: tokens only (`--surface-raised`, `--surface-sunken`, `--border-subtle`, `--border-default`, `--glance-fill`, `--primary`, `--primary-subtle`, `--text-primary`, `--text-secondary`, `--text-tertiary`, `--text-inverse`, `--accent`, `--danger`, `--shadow-md`, `--radius-lg`, `--space-*`).
- Breakpoints: page phone layout `max-width: 640px`; card head two-row grid `max-width: 899.98px` (one-row at ≥ 900px).
- D7: every tappable row, head, "⋯" button and menu item ≥ 44px tall at ≤ 640px.
- Every number written into an SVG attribute or a `style` is an integer stamped in the view and emitted with `|unlocalize` (`{% load l10n %}`).
- Every new UI string inside `<section class="outline">` carries `lang="{{ LANGUAGE_CODE }}"`; both `outline.html` and `_outline_node.html` call `{% get_current_language as LANGUAGE_CODE %}`.
- `{# #}` comments are single-line only; use `{% comment %}` for multi-line.
- The recursive `{% include "courses/_outline_node.html" %}` must NOT use `only`.
- Test runs: start the DB first — `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`; run with `uv run pytest <files>` (add `-m e2e` for Playwright files); **never pass `-q`**; read the summary line, not the exit code. One pytest run at a time.
- Owner rule (TDD with mutants): every new assertion is shown RED first (on the pre-change code, or against a hand-made mutant chosen from the failure mode), then GREEN. Revert a mutant by editing the file back by hand — never `git checkout`/`git restore`.
- After any CSS edit run every `tests/test_*css*.py`.
- State-specific rendering tests fake the resume with `monkeypatch.setattr("courses.views.build_resume", lambda c, u, t: {"node": unit, "state": s, "ancestors": []})` — the patch target is `courses.views`, not `courses.rollups` (views imports the name); the client must be an **enrolled** student (`EnrollmentFactory`), or the view never calls it; `node` must be a real unit in that course's tree. Pattern: `tests/test_courses_views.py::test_each_state_renders_its_own_eyebrow`.
- Known-red windows (do not "fix" early): the two T11 student tests are red from Task 2 until Task 7 (they assert Polish text); `test_e2e_outline_tree.py::test_start_fresh_link_does_not_disturb_the_fold_state` and `::test_head_buttons_share_one_vertical_level` and `test_e2e_outline_phone_layout.py` are red from Tasks 2/4 until Tasks 5/6. Each task's run step deselects exactly the ones not yet due.
- `ruff check --no-cache` and `ruff format --check` on every touched `.py`.
- Superseded existing assertions are changed **only** as listed in spec §6's table; every other existing assertion stays as is. List each superseded test in the commit message of the task that changes it.

## Review Focus

1. **Courses with units at the root mixed with cards** (e.g. a loose "Wprowadzenie" unit before part 1): numbering must skip it, it renders as a plain row, the highlight can land on it — pinned in Task 1 (`test_root_units_are_not_numbered_and_can_be_current`) and Task 6 (`test_root_unit_rows_sit_between_cards`).
2. **A tag filter that hides every card**: the page must not break or scroll sideways; "Działy · N" still shows N — pinned in Task 5 (`test_filter_hiding_every_card_keeps_the_page_intact`).
3. **Maths in a card title** (`$x^2$`, KaTeX renders after load): the card must not overflow at 360px — pinned in Task 6 (`test_math_card_title_fits_a_phone`).
4. **An unbreakable 60-character word in a part title at 360px**: wraps inside the card, no horizontal scroll — pinned in Task 6 (`test_unbreakable_card_title_fits_a_phone`).
5. **Author / staff preview** (not enrolled, drafts kept): no resume card or start button, empty progress UI, draft units still listed — pinned in Task 4 (`test_author_preview_shows_progress_ui_but_no_next_step`).

---

### Task 1: Presentation data in the view

**Files:**
- Modify: `courses/views.py` (new module-level constant + helper above `course_outline`; `course_outline` context)
- Test: `tests/test_outline_presentation.py` (new)

**Interfaces:**
- Consumes: `build_outline` dicts (`node`, `children`, `required_total`, `required_done`, `additional_done`, `is_unit`, `completed`, `has_state`, `depth`), `build_resume` result (`{"node", "state", "ancestors"}` or `None`), `courses.rollups._progress_width(done, total) -> int | None`, `courses.rollups._course_required_totals(tree) -> (done, total)`.
- Produces:
  - `ARC_FLOOR_PCT = 9` (module constant in `courses/views.py`).
  - `_outline_presentation(outline: list[dict], resume: dict | None) -> dict` returning `{"course_done": int, "course_total": int, "course_progress_width": int | None, "section_count": int, "current_row_pk": int | None, "arc_floor_pct": int}` and stamping, in place:
    - every container dict: `progress_width: int | None`, `arc_pct: int` (`max(progress_width or 0, ARC_FLOOR_PCT)`), `ring: None | "done" | "progress" | "none"`;
    - every root container: `card_number: int` (1-based over roots with `is_unit == False`, in order);
    - every unit dict: `ring: None | "done" | "progress" | "none"` (`None` for `unit_type == "quiz"`).
  - `course_outline` context gains all six returned keys.

Ring rules (spec §3.4, §3.5 — precedence top to bottom):
- container: `required_total == 0` → `None`; `required_done == required_total` → `"done"`; `0 < required_done` **or** `has_state` **or** (`pk == current_row_pk` and `resume["state"] == "resume"`) → `"progress"`; else `"none"`.
- unit: quiz → `None`; `completed` → `"done"`; `has_state` **or** (`resume` and `resume["state"] == "resume"` and `node.pk == resume["node"].pk`) → `"progress"`; else `"none"` (unset `unit_type` is treated as a lesson).
- `current_row_pk`: `None` unless `resume` and `resume["state"] in {"resume", "next", "gap"}`; else the depth-1 container whose subtree contains `resume["node"]`, else `resume["node"].pk` when that unit is at depth 0 or depth 1. Pure dict walk; never read `contains_current`.

- [ ] **Step 1: Write the failing tests** in `tests/test_outline_presentation.py`, building real trees with `ContentNodeFactory` + `build_outline(course, user)` and hand-made resume dicts `{"node": unit, "state": s, "ancestors": []}`:

```python
def test_course_totals_and_width_come_from_the_rollups():          # 1 of 4 required done
    p = _outline_presentation(tree, None)
    assert (p["course_done"], p["course_total"]) == (1, 4)
    assert p["course_progress_width"] == 25

def test_course_width_is_none_when_nothing_done_and_100_only_when_complete(): ...
    # 0/4 -> None ; 4/4 -> 100 ; 39/40 -> 98 (clamped, not 100)

def test_cards_are_numbered_over_root_containers_only():
    # roots: unit U0, part P1, unit U1, part P2
    assert [d.get("card_number") for d in tree] == [None, 1, None, 2]
    assert p["section_count"] == 2

def test_root_units_are_not_numbered_and_can_be_current():        # Review Focus 1
    p = _outline_presentation(tree, {"node": u0, "state": "next", "ancestors": []})
    assert p["current_row_pk"] == u0.pk

@pytest.mark.parametrize("shape", ["under_depth1_container", "depth1_unit", "root_unit"])
def test_current_row_pk_for_each_target_shape(shape): ...           # spec §2.1 D5

@pytest.mark.parametrize("state", ["start", None])
def test_no_current_row_in_start_or_without_resume(state):
    assert p["current_row_pk"] is None

def test_container_ring_precedence():
    # all-quiz chapter -> None ; 2/2 -> "done" ; 1/40 -> "progress" ; 0/2 untouched -> "none"
    # 0/2 with a has_state unit -> "progress"

def test_resume_state_current_row_with_nothing_done_is_in_progress():
    # chapter 0/2, resume target a bare-visit lesson inside it, state "resume" -> "progress"
    # same chapter, state "next" -> "none"

def test_done_chapter_with_open_quiz_target_stays_done_and_current():
    # chapter 2/2 + open quiz inside, resume on the quiz, state "resume"
    assert chapter["ring"] == "done" and p["current_row_pk"] == chapter_node.pk

def test_arc_floor_applies_to_every_in_progress_arc():
    # 1/40 chapter: progress_width == _progress_width(1, 40) == 2 (ROUND_HALF_EVEN), arc_pct == 9 ; 20/40 -> arc_pct == 50
    # expected widths always come from _progress_width as it stands, never hand arithmetic
    assert isinstance(chapter["arc_pct"], int)

def test_unit_rings():
    # quiz -> None ; completed lesson with saved state -> "done" ; has_state lesson -> "progress"
    # the resume target lesson at depth 2, state "resume", no state -> "progress"
    # same lesson, state "next" -> "none" ; lesson with unit_type=None -> "none" (not None)

def test_view_puts_the_presentation_keys_in_context(client):
    # GET courses:course_outline as an enrolled student; all six keys present in r.context
```

- [ ] **Step 2: Run** `uv run pytest tests/test_outline_presentation.py` — expected: FAIL with `ImportError: cannot import name '_outline_presentation'`.

- [ ] **Step 3: Implement** `ARC_FLOOR_PCT` and `_outline_presentation(outline, resume) -> dict` in `courses/views.py` exactly per the Interfaces block (add `from courses.rollups import _course_required_totals` and `from courses.rollups import _progress_width`, one name per line like the existing imports); call it in `course_outline` after `build_resume` and merge its dict into the render context. The helper makes no ORM calls; no query-count assertion is needed.

- [ ] **Step 4: Run** `uv run pytest tests/test_outline_presentation.py tests/test_resume_target.py tests/test_courses_views.py` — expected: all PASS. Then falsify: set `ARC_FLOOR_PCT` handling to `progress_width or 0` (drop the floor) → `test_arc_floor_applies_to_every_in_progress_arc` RED; restore by hand. Drop the `resume`-state arm of the container rule → `test_resume_state_current_row_with_nothing_done_is_in_progress` RED; restore.

- [ ] **Step 5: Commit**

```bash
git add courses/views.py tests/test_outline_presentation.py
git commit -m "feat(outline): presentation data for cards, rings and the course bar"
```

---

### Task 2: Container markup — cards, rows, counts, menus

**Files:**
- Modify: `templates/courses/_outline_node.html` (container arms only)
- Test: `tests/test_outline_cards.py` (new); superseded: `tests/test_outline_collapsible.py::test_reset_link_is_a_sibling_of_details_not_inside_the_summary`

**Interfaces:**
- Consumes (Task 1): item keys `card_number`, `progress_width`, `arc_pct`, `ring`; context `current_row_pk`, `resume`, `arc_floor_pct`.
- Produces — DOM contract later tasks style and test:
  - card `<li>` (only when `item.depth == 0 and item.children` — a childless depth-0 bare dict is never a card): classes `outline-node outline-node--{kind} outline-node--card`; summary children in order: `span.outline-card__num[aria-hidden=true]`, `span.outline-node__title#node-title-{pk}`, then (only when `required_total > 0` or `additional_done`) `span.outline-card__meta` containing `span.outline-card__bar[aria-hidden=true] > span.outline-card__fill[style="width: N%"]` (fill omitted when `progress_width` is None) and **one** `span.outline-card__countcell` wrapping `span.outline-count` (see below) and the "+N" chip (the count and chip share one grid cell — spec §3.2); then the chevron `svg.outline-node__chevron` **last**.
  - depth-1 container summary children: `span.outline-ring.outline-ring--{done|progress|none}[aria-hidden=true]` (or an empty `span.outline-ring[aria-hidden=true]` slot when `ring` is None), title `#node-title-{pk}`, `span.outline-count`, `span.visually-hidden.outline-status` (status word; absent when `ring` is None), "+N" chip, chevron last. Summary gets `class="outline-node__head is-current" aria-current="step"` only when `node.pk == current_row_pk`.
  - depth ≥ 2 container summary: chevron first, title, `span.outline-count`, "+N" chip (no ring).
  - `span.outline-count` = `<span class="outline-count__short" aria-hidden="true">{{ done }}/{{ total }}</span><span class="outline-count__long visually-hidden" lang="…">{% blocktrans %}{{ done }} of {{ counter }} lesson…{% endblocktrans %}</span>`; on cards the long span is NOT `visually-hidden` (CSS swaps at ≤ 640px, Task 6) — give it class `outline-count__long` only.
  - "⋯" menu (when `item.has_state`), a sibling directly after the `<details>`: `<details class="outline-menu"><summary class="outline-menu__button" aria-label="{% trans 'More actions' %}" aria-describedby="node-title-{pk}" lang="…">⋯</summary><div class="outline-menu__panel"><a class="outline-node__reset outline-menu__item" href="…unchanged…" title="…" aria-label="…">{% trans "Start fresh" %}</a></div></details>`.
  - ring SVG: 20×20 `viewBox="0 0 20 20"`, track `circle.outline-ring__track` r=8; progress adds `circle.outline-ring__arc pathLength="100" stroke-dasharray="{{ item.arc_pct|unlocalize }} 100"`; done = `circle.outline-ring__fill` r=9 + `path.outline-ring__tick`.
  - childless arm (`div.outline-node__head`): title, `span.outline-count`, menu at the end; no badge/bar/ring/chevron; must not raise when `card_number`/`progress_width`/`ring`/`has_state` are missing.
- Bars and `span.outline-count` render only when `required_total > 0`, at every depth (no "0/0", no empty track on an all-quiz node).
- No `.rollup` "lessons: %(done)s/%(total)s" chip remains in this template (the msgid stays in the catalogue — the teacher page `_breakdown_node.html` uses it).

- [ ] **Step 1: Write the failing tests** in `tests/test_outline_cards.py` (BeautifulSoup over `client.get(course_outline)`; English UI):

```python
def test_root_containers_render_as_numbered_cards():
    cards = soup.select("li.outline-node--card")
    assert [c.select_one(".outline-card__num").get_text(strip=True) for c in cards] == ["1", "2"]
    assert all(c.select_one(".outline-card__num")["aria-hidden"] == "true" for c in cards)

def test_card_bar_width_and_counts():                     # part with 1/4 required done
    card = ...
    assert card.select_one(".outline-card__fill")["style"] == "width: 25%"
    assert card.select_one(".outline-count__short").get_text(strip=True) == "1/4"
    assert card.select_one(".outline-count__long").get_text(strip=True) == "1 of 4 lessons"

def test_card_with_nothing_done_has_an_empty_track(): # .outline-card__bar present, no .outline-card__fill
def test_all_quiz_card_has_no_bar_count_or_meta_row(): # no .outline-card__meta at all
def test_additional_chip_still_renders():               # "+1 additional" inside .outline-card__countcell, next to .outline-count
def test_card_meta_has_exactly_two_children():          # .outline-card__bar and .outline-card__countcell
def test_chevron_is_the_last_child_of_a_card_summary():
def test_depth1_row_ring_classes_and_status_word():      # done/progress/none + "Completed"/"In progress"/"Not started"
def test_all_quiz_row_has_an_empty_ring_slot_and_no_status_word():
def test_depth1_summary_accessible_text_starts_with_title_then_count():
    assert summary.get_text(" ", strip=True).startswith("Chapter A 1/2 1 of 2 lessons")
def test_exactly_one_current_row_with_aria_current():    # shape "under a depth-1 container" only (unit shapes: Task 3)
    assert len(soup.select('[aria-current="step"]')) == len(soup.select(".is-current")) == 1
def test_no_current_row_in_start_state():
def test_depth2_head_has_count_pair_and_no_ring_or_chip():
    assert not soup.select(".rollup:-soup-contains('lessons:')")
def test_reset_links_live_only_inside_menus():
    assert all(a.find_parent("details", class_="outline-menu") for a in soup.select("a.outline-node__reset"))
def test_menu_present_iff_node_has_state_and_href_unchanged():
def test_every_aria_describedby_resolves():
    ids = {el["id"] for el in soup.select("[id]")}
    assert all(el["aria-describedby"] in ids for el in soup.select("[aria-describedby]"))
def test_arc_dasharray_is_an_integer_pair():              # "9 100" for a 0-done has_state row
def test_childless_arm_renders_from_a_bare_dict():       # render_to_string with no card_number/ring keys; depth 0
    assert "outline-node--card" not in html and "outline-card__num" not in html
def test_no_bar_or_count_when_no_required_lessons():     # card with only a done optional lesson: meta row has the +N chip, no bar, no count; all-quiz depth-1 row: no count
@pytest.mark.parametrize("source", ["saved_state", "bare_visit", "quiz_in_progress"])
def test_resume_from_each_real_source_lights_the_current_row(source):
    # real build_resume, enrolled student. Fixture: part > chapter > [lesson L1 (not done), target T]; T = lesson with
    # UnitProgress(element_state={"1": {}}) / lesson with UnitProgress(element_state={}) / quiz with
    # QuizSubmissionFactory(status=IN_PROGRESS) — L1 keeps the chapter's required_total > 0 and not done.
    # First assert r.context["resume"]["state"] == "resume" (guards the fixture), then:
    row = soup.select_one("summary.is-current")
    assert "outline-ring--progress" in row.select_one(".outline-ring")["class"]
    assert row.select_one(".outline-status").get_text(strip=True) == "In progress"
def test_every_li_keeps_its_node_id_and_filtered_cards_are_hidden():   # #node-N on every li; ?tags= hides a card li with [hidden]
```

- [ ] **Step 2: Run** `uv run pytest tests/test_outline_cards.py` — expected: FAIL (no `li.outline-node--card`). (From this task on, the e2e tests named under Known-red windows are expected red until Tasks 5/6; this task runs no e2e.)

- [ ] **Step 3: Implement** the Interfaces DOM contract in `_outline_node.html`. Add `{% load l10n %}` and `{% get_current_language as LANGUAGE_CODE %}` at the top. Card vs row vs deeper is decided by `item.depth` (0 / 1 / ≥ 2). Keep `id="node-{pk}"`, `data-node`, `data-depth`, the D1/D8 `open` logic and the `{% comment %}` blocks (update their wording where they mention the moved reset link). New strings in English with `{% trans %}`/`{% blocktrans count counter=… %}`: "%(done)s of %(counter)s lesson" / "…lessons"; "Not started"; reuse "Completed", "In progress", "More actions", "Start fresh", "additional".

- [ ] **Step 4: Update the superseded tests** (spec §6 table rows): `test_reset_link_is_a_sibling_of_details_not_inside_the_summary` → select the first `summary.outline-node__head` with BeautifulSoup, assert the reset link is inside `details.outline-menu` and that menu is the `<details>`' next sibling; the two T11 student tests render under a Polish UI, so they are updated in **Task 7** (Polish text); until then deselect them.

- [ ] **Step 5: Run** `uv run pytest tests/test_outline_cards.py tests/test_outline_collapsible.py tests/test_outline_anchors.py tests/test_tags_outline.py tests/test_publish_outline.py tests/test_analytics_student_page.py tests/test_title_math_markers.py --deselect tests/test_analytics_student_page.py::test_rt_t11_student_outline_chip_reads_lekcje --deselect tests/test_analytics_student_page.py::test_rt_t11_childless_outline_branch_chip_reads_lekcje` — expected: all PASS. Falsify: remove `aria-hidden` from the badge → `test_root_containers_render_as_numbered_cards` RED; restore.

- [ ] **Step 6: Commit** (message lists the superseded test and the two T11 tests left red until Task 7)

```bash
git add templates/courses/_outline_node.html tests/test_outline_cards.py tests/test_outline_collapsible.py
git commit -m "feat(outline): card, row and menu markup for containers"
```

---

### Task 3: Unit rows — leading glyph, quiz icon, highlight

**Files:**
- Modify: `templates/courses/_outline_node.html` (unit arm only)
- Test: `tests/test_outline_unit_rows.py` (new)

**Interfaces:**
- Consumes (Task 1): unit `ring`; context `current_row_pk`, `arc_floor_pct`.
- Produces: inside `a.outline-unit`, the **first child** is either `span.outline-ring.outline-ring--{done|progress|none}[aria-hidden=true]` (lesson / unset type; progress arc uses `stroke-dasharray="{{ arc_floor_pct|unlocalize }} 100"`) or `svg.outline-quiz-icon[aria-hidden=true]` (quiz; 20×20, `stroke="currentColor"`, the mockup clipboard-with-tick paths). `a.outline-unit` gets `is-current` + `aria-current="step"` iff `node.pk == current_row_pk`. Title, kind chip (and its order: chip after the title, before the ✓ — `test_unit_marker.py` pins it relative to those two), ✓ badge, the `outline-unit--done` class, tag chips, tag-edit link and notes badge unchanged; the ring has no status word.

- [ ] **Step 1: Write the failing tests:**

```python
def test_lesson_row_starts_with_a_decorative_ring():
    a = soup.select_one(f"#node-{lesson.pk} > a.outline-unit")
    first = a.find(True)
    assert "outline-ring" in first["class"] and first["aria-hidden"] == "true"

def test_quiz_row_has_icon_and_exactly_one_quiz_label():
    assert a.select_one("svg.outline-quiz-icon")
    assert len(a.select(".unit-kind-chip--quiz")) == 1

def test_completed_lesson_with_saved_state_draws_done():
def test_resume_target_lesson_at_depth2_draws_progress_but_is_not_current():
    assert "outline-ring--progress" in ring["class"] and "is-current" not in a["class"]
def test_root_and_depth1_unit_targets_are_current_and_draw_progress():   # lesson targets, state "resume"
    assert len(soup.select('[aria-current="step"]')) == len(soup.select(".is-current")) == 1
def test_unit_row_keeps_chips_badges_and_links(): # ✓ badge aria-label, tag chip, edit-tags href, notes badge
```

- [ ] **Step 2: Run** `uv run pytest tests/test_outline_unit_rows.py` — expected: FAIL.

- [ ] **Step 3: Implement** the unit arm per Interfaces.

- [ ] **Step 4: Run** `uv run pytest tests/test_outline_unit_rows.py tests/test_outline_cards.py tests/test_tags_outline.py tests/test_courses_views.py tests/test_unit_marker.py tests/test_courses_progress.py` — expected: PASS. Falsify: key the unit highlight on `resume.node.pk` instead of `current_row_pk` → `test_resume_target_lesson_at_depth2_draws_progress_but_is_not_current` RED; restore.

- [ ] **Step 5: Commit**

```bash
git add templates/courses/_outline_node.html tests/test_outline_unit_rows.py
git commit -m "feat(outline): unit row status rings, quiz icon and highlight"
```

---

### Task 4: Course head, list header and the start button

**Files:**
- Modify: `templates/courses/outline.html`, `templates/courses/_resume_card.html`, `courses/views.py` (label helper + context key)
- Test: `tests/test_outline_head.py` (new); superseded in `tests/test_courses_views.py` (`test_each_state_renders_its_own_eyebrow` start case, `test_card_links_to_quiz_unit_for_a_quiz_target`, `test_card_links_to_lesson_unit_for_a_lesson_target`, `test_eyebrow_carries_the_active_ui_language`, `test_resume_card_renders_its_path_separator_and_affordance`) and `tests/test_title_math_markers.py::test_resume_card_title_and_crumbs_are_marked`

**Interfaces:**
- Consumes (Task 1): context `course_done`, `course_total`, `course_progress_width`, `section_count`; existing `resume`, `has_saved_work`.
- Produces (DOM, styled in Task 5):
  - `header.outline__head` (the element changes from today's `<div>`; grep `tests/` and `*.css` for `div.outline__head` first and keep any selector working) > `h1.outline__title#outline-title`; `div.outline__progress` (only when `course_total > 0`) > `div.outline__bar[aria-hidden=true]` (> `span.outline__fill[style="width: N%"]` when width not None) + `span.outline__progress-label[lang]`; then the resume include; then `div.outline__actions` > `a.btn.btn--ghost.btn--small.outline__results`, `a.btn.btn--ghost.btn--small.outline__notes`, and when `has_saved_work` a `details.outline-menu` whose summary has `aria-describedby="outline-title"` and whose item is `a.outline__reset.outline-menu__item` (no `btn` classes; href unchanged).
  - D1 label is built in the view (the request's language is already active there): `_progress_label(done: int, total: int, sections: int) -> str` in `courses/views.py`, context key `progress_label`. done > 0 → `ngettext("%(done)s of %(counter)s lesson completed", "%(done)s of %(counter)s lessons completed", total) % {...}`; done == 0 → `ngettext("%(counter)s lesson", "%(counter)s lessons", total) % {...}`, and when `sections > 0` the composition `_("%(lessons)s %(sections)s")` (views.py's existing `gettext as _`) % {"lessons": …, "sections": ngettext("in %(counter)s topic", "in %(counter)s topics", sections) % {...}}` — no trailing space when `sections == 0` (tests compare exact stripped text). The template only prints `{{ progress_label }}`.
  - `div.outline-list__head` placed directly **before** `<nav class="outline-tree">` (after the tag filter bar), with `hidden` when `section_count == 0`; children `span.outline-list__count[lang]` = `{% blocktrans with n=section_count %}Topics · {{ n }}{% endblocktrans %}` (only when `section_count > 0`) and `<button type="button" class="outline__toggle-all" hidden data-outline-toggle-all data-label-expand="…" data-label-collapse="…">` — `hidden` must precede `data-outline-toggle-all` (`test_header_button_and_nav_attributes` splits on it).
  - `_resume_card.html`: `{% if resume.state == "start" %}` → `a.btn.btn--primary.outline__start[lang]` "Start the first lesson" + `svg.outline__start-arrow.icon[aria-hidden=true]` chevron path, href = the card's existing quiz/lesson branch; `{% else %}` the card, whose eyebrow loses its `start`/else arm.

- [ ] **Step 1: Write the failing tests:**

```python
def test_title_has_its_id_and_the_bar_is_hidden_from_at():
def test_progress_label_some_done():        # "1 of 4 lessons completed"
def test_progress_label_nothing_done():     # "4 lessons in 2 topics"
def test_progress_label_without_containers(): # root units only -> "4 lessons", list head has hidden
def test_no_progress_block_when_no_required_lessons():
def test_course_bar_width_is_clamped():     # 39/40 -> "width: 98%"
def test_start_state_renders_the_button_not_the_card():   # lesson target -> lesson_unit href
def test_start_button_links_to_quiz_unit_for_a_quiz():
def test_start_button_accessible_name_has_no_arrow():
    assert btn.get_text(strip=True) == "Start the first lesson"
@pytest.mark.parametrize("state", ["resume", "next", "gap"])
def test_returning_states_keep_the_card(state):
def test_course_reset_lives_in_a_menu_iff_saved_work():
def test_actions_row_holds_results_notes_and_menu():
def test_list_header_sits_before_the_nav_and_counts_topics():
def test_author_preview_shows_progress_ui_but_no_next_step():   # Review Focus 5: staff, drafts kept
```

- [ ] **Step 2: Run** `uv run pytest tests/test_outline_head.py` — expected: FAIL.

- [ ] **Step 3: Implement** per Interfaces; add `from django.utils.translation import ngettext` to `courses/views.py` (it imports only `gettext as _` today); add `{% load l10n %}` and `{% get_current_language as LANGUAGE_CODE %}` to `outline.html`. New English msgids: "%(done)s of %(counter)s lesson completed" (plural), "%(counter)s lesson" (plural), "in %(counter)s topic" (plural), "%(lessons)s %(sections)s", "Topics · %(n)s", "Start the first lesson".

- [ ] **Step 4: Update the superseded tests** exactly per spec §6: the `start` row of `test_each_state_renders_its_own_eyebrow` becomes a separate assertion that `start` renders `a.outline__start` "Start the first lesson" and no `a.resume`; the four card tests and the math-marker test seed one completed earlier unit (`UnitProgressFactory(..., completed=True, completed_at=…)`) so the state is `next`, keeping their card assertions; the two href tests also assert the same href on the start button in `start`.

- [ ] **Step 5: Run** `uv run pytest tests/test_outline_head.py tests/test_courses_views.py tests/test_title_math_markers.py tests/test_outline_collapsible.py tests/test_resume_target.py` — expected: PASS. Falsify: move `hidden` after `data-outline-toggle-all` → `test_header_button_and_nav_attributes` RED; restore.

- [ ] **Step 6: Commit** (message lists the six superseded tests)

```bash
git add courses/views.py templates/courses/outline.html templates/courses/_resume_card.html tests/test_outline_head.py tests/test_courses_views.py tests/test_title_math_markers.py
git commit -m "feat(outline): course progress head, list header and start button"
```

---

### Task 5: Head, list header and menu styling (+ JS notes)

**Files:**
- Modify: `core/static/core/css/app.css` (Course outline block: `.outline__head` → grid, `.outline__progress`, `.outline__bar`, `.outline__fill`, `.outline__actions`, `.outline__start`, `.outline__start-arrow`, `.outline-list__head`, `.outline__toggle-all` text style + `:disabled` rewrite, `[hidden]` rules, `.outline-menu*`), `courses/static/courses/js/outline_tree.js` (comment + optional close handler)
- Test: `tests/test_e2e_outline_head.py` (new); superseded: `tests/test_e2e_outline_tree.py::test_head_buttons_share_one_vertical_level`, `test_start_fresh_link_does_not_disturb_the_fold_state` (click + keyboard, ~:574–655), `tests/test_e2e_outline_phone_layout.py::test_outline_head_stays_on_one_line_on_desktop`

**Interfaces:**
- Consumes: Task 2 and Task 4 DOM.
- Produces: CSS rules named above; desktop head grid areas `"title actions" "progress actions" "next next"` (actions `align-self: end`); phone single column in DOM order; `.outline-list__head[hidden], .outline__toggle-all[hidden] { display: none; }` declared after their display rules with a comment; `.outline-menu { position: relative; }` plus `.outline-node > .outline-menu { grid-column: 2; grid-row: 1; justify-self: end; align-self: start; }` (the course-head menu in `.outline__actions` is not grid-placed), `.outline-menu__panel { position: absolute; top: 100%; right: 0; z-index: … }`, summary 32×32 (44×44 at ≤ 640px), `list-style: none` + hidden `::-webkit-details-marker`; `.outline-menu__item` full-width, ≥ 44px tall at ≤ 640px, hover `--surface-sunken` + `--danger` text. Remove the old `.outline-node__reset` inline-link declarations (grid placement moves to `.outline-menu`) and PR #397's `:has(> .outline-node__reset)` 7.5rem rule + its comment.

- [ ] **Step 1: Write the failing e2e tests** (pattern: `tests/test_e2e_editor_crumb_phone.py` / `tests/test_e2e_outline_phone_layout.py` — real login, PL via `form.lang-switch button[value='pl']` where wording matters):

```python
@pytest.mark.parametrize("width", [360, 412])
def test_phone_head_stacks_in_dom_order(width):   # title, bar, card/button, actions; actions count == 3; no h-scroll
def test_desktop_actions_sit_right_of_the_title_column():   # 1280: actions.x > title right; bottoms aligned with bar ±2px
def test_actions_share_one_vertical_level():      # superseded T: results, notes, ⋯ summary centre y equal ±1px
def test_toggle_hidden_rules_beat_display():       # header with section_count 0 and a hidden toggle compute display none
def test_menu_opens_out_of_flow_without_reflow():  # 360: row heights equal before/after open; no h-scroll; panel right edge <= viewport
def test_menu_targets_are_44px_on_a_phone():
def test_menu_reset_link_reaches_the_confirm_page():
def test_filter_hiding_every_card_keeps_the_page_intact():   # Review Focus 2
def test_opening_a_menu_does_not_touch_the_stored_fold_state():   # localStorage libli_outline_open:<slug> equal before/after open+close of a card menu
```

- [ ] **Step 2: Run** `uv run pytest tests/test_e2e_outline_head.py -m e2e` — expected: FAIL (layout not styled).

- [ ] **Step 3: Implement** the CSS per Interfaces; in `outline_tree.js` add a comment at the capture-phase `toggle` listener that menu `<details>` also fire it and `syncLabel` must keep reading only `groups`. Optional: close an open `.outline-menu` on outside click — if added, a single `document` `click` listener, no keydown handler.

- [ ] **Step 4: Update the superseded e2e tests** per spec §6 (head buttons → `.outline__actions` children incl. the ⋯ summary, keep the align-self mutant; `test_start_fresh_link_does_not_disturb_the_fold_state` rewritten **in place** — open the row's "⋯" before clicking `a.outline-node__reset`; keyboard path Tab from the collapsed summary → `details.outline-menu > summary`, Enter opens it, Tab → `a.outline-node__reset`; keep its route-abort mechanics and fold-state partition assertions; desktop head line → actions in the top row right of the title column).

- [ ] **Step 5: Run** `uv run pytest tests/test_e2e_outline_head.py tests/test_e2e_outline_tree.py tests/test_e2e_outline_phone_layout.py -m e2e --deselect tests/test_e2e_outline_phone_layout.py::test_outline_fits_a_phone` (rewritten in Task 6; expected red here) and every `tests/test_*css*.py` — expected: PASS. Falsify: delete `.outline__toggle-all[hidden]` rule → `test_toggle_hidden_rules_beat_display` RED; make the panel `position: static` → `test_menu_opens_out_of_flow_without_reflow` RED; restore both by hand.

- [ ] **Step 6: Commit**

```bash
git add core/static/core/css/app.css courses/static/courses/js/outline_tree.js tests/test_e2e_outline_head.py tests/test_e2e_outline_tree.py tests/test_e2e_outline_phone_layout.py
git commit -m "style(outline): course head, list header and ⋯ menus"
```

---

### Task 6: Card, row, ring and type styling

**Files:**
- Modify: `core/static/core/css/app.css` (cards, card head grid, `.outline-card__*`, `.outline-count*`, `.outline-ring*`, `.outline-quiz-icon`, `.outline-unit .unit-kind-chip--quiz`, type scale, hover, `is-current`, list rhythm, forced colours), `core/static/core/css/tokens.css` (print-block `--text-inverse` comment only)
- Test: `tests/test_e2e_outline_cards.py` (new); superseded: the comment in `tests/test_e2e_outline_tree.py::test_first_visit_opens_depth0_only` (~:169, mentions "lessons: 0/1"; comment only — no assertion depends on it) and `::test_nested_type_scale_and_guide_rule_survive_the_details_nesting` (T17), `tests/test_e2e_outline_phone_layout.py::test_outline_fits_a_phone`

**Interfaces:**
- Consumes: Task 2 and Task 3 DOM.
- Produces (values from spec §3.2, §3.4, §3.8):
  - `.outline-node--card`: `--surface-raised`, `1px solid var(--border-subtle)`, `--radius-lg`, padding `--space-4` (≤ 640px) / `--space-5`; no `overflow`, `transform`, `filter` or `isolation`. Keep the existing `.outline-node--part/--chapter/--section` grid rule declared **above** `.outline-node[hidden]`.
  - Card summary grid ≥ 900px: `grid-template-columns: auto minmax(0,1fr) 12.5rem minmax(7.5rem, max-content) auto` (badge | title | bar | count cell | chevron) — the meta wrapper uses `display: contents` there, so its two children (`.outline-card__bar`, `.outline-card__countcell`) fill the bar and count-cell tracks; < 900px: two rows **only when** `.outline-card__meta` exists (row 2 = the meta spanning under the title); a card without a meta row is a single row with no empty band or row-gap with bar `minmax(0,1fr)` + count `max-content`. Badge/chevron `align-self: start` (first title line).
  - Reservation: `.outline-node:has(> .outline-menu) > .outline-node__group > summary.outline-node__head { padding-inline-end: calc(32px + var(--space-2) + var(--space-2)); }` (44px at ≤ 640px); summaries inside cards `padding-inline: var(--space-2)`.
  - Count swap, **card summaries only** (selector base `.outline-node--card > .outline-node__group > summary`): ≥ 641px its `.outline-count__short` is hidden; ≤ 640px its `.outline-count__long` gets the `.visually-hidden` declarations (never `display: none`). Rows (depth ≥ 1) and the childless arm always show `.outline-count__short`; their long span is always `.visually-hidden` (from the markup).
  - Type scale table (spec §3.8) incl. card-title override resetting `text-transform: none; letter-spacing: normal; color: var(--text-primary)` with a specificity comment; depth-1 by position.
  - `.outline-node--card > .outline-node__group > ul { border-left: 0; padding-left: 0; }`; root rhythm `.outline-tree > ul > .outline-node--card { margin-bottom: var(--space-6); }` (remove the generic root margin; a run of root units gets `--space-6` before the next card).
  - Hover inside cards `color-mix(in srgb, var(--surface-sunken) 50%, var(--surface-raised))`; `is-current` = `--surface-sunken`, no hover repaint; unit band via `.outline-node--unit:has(> .outline-unit.is-current)`.
  - Rings: track `--border-default`, arc/fill `--glance-fill`, tick `--text-inverse`; quiz icon + `.outline-unit .unit-kind-chip--quiz` teal `--primary`, `text-transform: uppercase`.
  - D7 `min-height: 44px` on `.outline-unit` and container heads at ≤ 640px.
  - `@media (forced-colors: active)`: bars `1px solid CanvasText`, fills `Highlight` with `forced-color-adjust: none`; `.outline-ring { forced-color-adjust: none; }` track `stroke: CanvasText`, arc/fill `Highlight`, tick `stroke: Canvas`.
  - tokens.css: extend the print comment to name the outline done tick as a `--text-inverse` consumer.

- [ ] **Step 1: Write the failing e2e tests:**

```python
@pytest.mark.parametrize("width", [360, 412])
def test_cards_fit_a_phone(width):  # no h-scroll; title starts on badge line right of badge; meta row below title; bar width > 0 and inside card; every row/head >= 44px
def test_menu_space_is_reserved_only_where_a_menu_exists():  # content-box rule from spec §6 phone row; mutants: drop :has(), delete rule
def test_long_count_stays_in_the_a11y_tree_on_a_phone():     # 360: card long span display != none AND bounding width <= 1px; card short span visible
def test_row_short_count_is_visible_on_desktop():             # 1280: a depth-1 row's .outline-count__short visible; card short hidden, card long visible (mutant: drop the card scope)
def test_all_quiz_card_head_is_one_row_on_a_tablet():          # 700: badge, title, chevron overlap vertically; head height ~ one title line
def test_tablet_card_head_is_two_rows():                      # 700: title width >= 60% of card inner width; "199 of 199 lessons" one line
def test_desktop_card_head_is_one_line():                      # 1280 short title: badge, title, bar, count, chevron overlap vertically; two menu-less cards' chevron x equal
def test_long_title_wraps_with_badge_on_first_line():          # 1280
def test_chip_card_keeps_its_chevron_on_the_first_row():       # 1280, card with a +N chip: chevron overlaps the title's first line vertically
def test_tapping_a_chapter_unfolds_it_inside_the_card():       # D5
def test_last_card_menu_is_not_clipped():
def test_card_list_has_no_guide_rule_but_chapters_do():
def test_section_card_title_is_not_micro_type():               # mutant: drop the override
def test_type_scale_superseded_t17():                          # depth-1 chapter 15px; depth-2 section 12px uppercase; guide rule kept
def test_resume_card_quiz_chip_keeps_its_style():              # computed colour + text-transform equal to master's values recorded in the test
def test_root_unit_rows_sit_between_cards():                   # Review Focus 1
def test_unbreakable_card_title_fits_a_phone():                # Review Focus 4
def test_math_card_title_fits_a_phone():                       # Review Focus 3, wait for .katex
def test_rings_differ_under_forced_colors():                   # page.emulate_media(forced_colors="active")
def test_expand_all_toggles_cards_and_chapters():
def test_deep_link_rings_a_non_current_chapter():              # :target box-shadow on its head; chapter != current_row_pk
def test_tag_filter_hides_and_restores_a_card():
```

- [ ] **Step 1b: Capture the baseline for `test_resume_card_quiz_chip_keeps_its_style`** before any CSS change: run its `evaluate` (computed `color`, `text-transform` of `.resume .unit-kind-chip--quiz`) on the current build in light and dark, and hard-code those values in the test. Its RED proof is the mutant "drop the `.outline-unit` scope from the quiz-chip rule" after Step 3.

- [ ] **Step 2: Run** `uv run pytest tests/test_e2e_outline_cards.py -m e2e` — expected: FAIL.

- [ ] **Step 3: Implement** the CSS per Interfaces and the tokens.css comment.

- [ ] **Step 4: Update the superseded e2e tests** per spec §6 (the ~:169 comment in `test_first_visit_opens_depth0_only` → describe the count pair; no assertion change; T17 → 15px; `test_outline_fits_a_phone` → the card-layout assertions in the spec's row, incl. the `== 3` / `== 2` actions count).

- [ ] **Step 5: Run** `uv run pytest tests/test_e2e_outline_cards.py tests/test_e2e_outline_head.py tests/test_e2e_outline_tree.py tests/test_e2e_outline_phone_layout.py tests/test_e2e_tags.py tests/test_e2e_link_dialog.py -m e2e` and every `tests/test_*css*.py` — expected: PASS. Falsify the reservation mutants named in Step 1, the card-title override, and the forced-colours ring rule (each RED, then restored by hand).

- [ ] **Step 6: Commit** (message lists the three superseded tests)

```bash
git add core/static/core/css/app.css core/static/core/css/tokens.css tests/test_e2e_outline_cards.py tests/test_e2e_outline_tree.py tests/test_e2e_outline_phone_layout.py
git commit -m "style(outline): part cards, status rings and type scale"
```

---

### Task 7: Polish catalogue and localisation guards

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po`, both `django.mo`
- Test: `tests/test_outline_i18n.py` (new); superseded: `tests/test_analytics_student_page.py::test_rt_t11_student_outline_chip_reads_lekcje`, `::test_rt_t11_childless_outline_branch_chip_reads_lekcje`

**Interfaces:**
- Consumes: msgids from Tasks 2 and 4.
- Produces: Polish entries exactly per spec §3.9 (plural forms one/few/many; "Nie rozpoczęto" new; "Ukończono", "W toku", "Więcej akcji", "Zacznij od nowa" reused unchanged). "Start the course" becomes obsolete only if no template uses it (grep first).

- [ ] **Step 1: Write the failing tests** (Polish UI via session `_language="pl"` as in `test_unit_edit_link.py::test_polish_view_live_label`):

```python
@pytest.mark.parametrize("total,expected", [(1, "1 z 1 lekcji ukończonej"), (2, "1 z 2 lekcji ukończonych"), (5, "1 z 5 lekcji ukończonych")])
def test_some_done_label_plurals(total, expected):
@pytest.mark.parametrize("lessons,sections,expected", [(1, 1, "1 lekcja w 1 dziale"), (2, 2, "2 lekcje w 2 działach"), (5, 5, "5 lekcji w 5 działach")])
def test_nothing_done_label_plurals(lessons, sections, expected):
def test_card_long_count_and_topics_label_in_polish():   # "1 z 2 lekcji", "Działy · 2"
def test_start_button_in_polish_carries_ui_lang_on_an_en_course():   # text "Zacznij pierwszą lekcję", lang="pl"
def test_status_word_in_polish_carries_ui_lang():                     # "Nie rozpoczęto", lang="pl"
def test_svg_and_style_numbers_have_no_decimal_comma():               # 0-done progress row dasharray "9 100"; bar style "width: 25%"
```

- [ ] **Step 2: Run** `uv run pytest tests/test_outline_i18n.py` — expected: FAIL (English text).

- [ ] **Step 3: Implement:** run `uv run python manage.py makemessages -l pl -l en` (without `--no-obsolete`), fill the new Polish `msgstr`s, clear any `#, fuzzy` pre-fill on the new entries (both the flag and the wrong `msgstr`), then `uv run python manage.py compilemessages`.

- [ ] **Step 3b: Update the T11 student tests** (spec §6): `test_rt_t11_student_outline_chip_reads_lekcje` → on the card heads, `.outline-count__long` "1 z 2 lekcji" / `.outline-count__short` "1/2" ("Czesc pierwsza") and "0 z 1 lekcji" / "0/1" ("Czesc druga"), and no `.rollup` containing "lekcje:" anywhere on the page; `test_rt_t11_childless_outline_branch_chip_reads_lekcje` → `div.outline-node__head .outline-count__long` "1 z 2 lekcji", `.outline-count__short` "1/2", no `.rollup`. Leave `test_rt_t11_teacher_chip_reads_lekcje` and `test_rt_t11_catalogs_drop_the_unused_msgids` untouched.

- [ ] **Step 4: Run** `uv run pytest tests/test_outline_i18n.py tests/test_analytics_student_page.py tests/test_courses_views.py` — expected: PASS (incl. `test_rt_t11_catalogs_drop_the_unused_msgids`). Falsify: temporarily stamp `item["arc_pct"] = 8.33` in `_outline_presentation` **and** drop `|unlocalize` from the arc's `stroke-dasharray` in `_outline_node.html` → `test_svg_and_style_numbers_have_no_decimal_comma` RED ("8,33 100"); restore both by hand.

- [ ] **Step 5: Commit**

```bash
git add locale/ tests/test_outline_i18n.py tests/test_analytics_student_page.py
git commit -m "i18n(outline): Polish strings for the course outline redesign"
```

---

### Task 8: Full verification and screenshots

**Files:** none expected; fixes, if any, go in the file they belong to with their own failing test.

- [ ] **Step 1:** Run every outline-related suite: `uv run pytest tests/test_outline_presentation.py tests/test_outline_cards.py tests/test_outline_unit_rows.py tests/test_outline_head.py tests/test_outline_i18n.py tests/test_outline_collapsible.py tests/test_outline_anchors.py tests/test_tags_outline.py tests/test_publish_outline.py tests/test_resume_target.py tests/test_courses_views.py tests/test_analytics_student_page.py tests/test_title_math_markers.py tests/test_unit_marker.py tests/test_courses_progress.py tests/test_title_math_assets.py tests/test_publish_call_sites.py tests/test_tags_notes_hub.py` + every `tests/test_*css*.py`, then the e2e set `tests/test_e2e_outline_*.py tests/test_e2e_tags.py tests/test_e2e_link_dialog.py tests/test_e2e_publish_toggle.py -m e2e`. Expected: all PASS (grep the summary line).
- [ ] **Step 2:** Capture screenshots with a temporary script (not committed; do not use or overwrite `capture_*` files) at 360 / 412 / 900 / 1280 in light and dark for: a new student, a student mid-course with an open menu, hovering the highlighted row, a print-media render, and a forced-colours render. Save under the session scratchpad. Look at each; judge dark separately; check the tick contrast and the absence of a UA triangle beside "⋯".
- [ ] **Step 3:** `uv run ruff check --no-cache` and `uv run ruff format --check` on every touched `.py`.
- [ ] **Step 4:** Commit only if Step 1–3 required a fix (with its test).
