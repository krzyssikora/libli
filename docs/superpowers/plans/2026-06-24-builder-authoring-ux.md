# Builder & Editor Authoring-UX Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make creating/authoring a quiz unit less confusing in the course builder & unit editor (choose Lesson/Quiz at add time, change type from a visible editor toggle, grouped element menu, consistent monochrome icons) and fix a dark-mode contrast bug on the marking inputs.

**Architecture:** Five independent UX improvements to existing Phase-1b surfaces — mostly template + view + CSS edits, one small JS verification, and a form-mixin one-liner. No schema change, no migration. Spec: `docs/superpowers/specs/2026-06-24-builder-authoring-ux-design.md` (review-clean, 5 rounds).

**Tech Stack:** Django (server-rendered, token-driven CSS — no Bootstrap/React), vanilla JS, pytest + factory_boy, Playwright (e2e), `uv` for tooling, Django i18n (EN + PL).

## Global Constraints

- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH. Use `uv run ruff ...`, `uv run pytest ...`, `uv run python manage.py ...`.
- **Lint every task:** run `uv run ruff check .` AND `uv run ruff format .` before each commit (CI runs `ruff format --check`).
- **No-JS correctness:** the builder add (Task 1) and the editor type toggle (Task 2) must work with JavaScript disabled — plain form submits.
- **i18n:** every NEW user-facing string is wrapped (`{% trans %}`) AND given a PL translation in `locale/pl/LC_MESSAGES/django.po`; recompile `.mo`; clear any `#, fuzzy` (Task 6). Lesson/Quiz REUSE the existing translated `UnitType` msgids — `{% trans "Lesson" %}`/`{% trans "Quiz" %}` resolve to them, no new catalog entries.
- **Dark mode:** all new/changed UI verified legible in light AND dark via Playwright screenshots (throwaway harness, delete after review) before the task's commit.
- **Multi-line template comments** use `{% comment %}`/`{% endcomment %}` — never multi-line `{# #}`.
- **Design system:** bespoke token-driven CSS — reuse existing tokens (`--surface-*`, `--text-*`, `--border-*`, `--primary*`, `--space-*`, `--radius-*`); no new colour literals.
- **No new migrations** (no schema change). `uv run python manage.py makemigrations --check --dry-run` must stay clean.
- **Commits:** each commit ends with the repo trailers:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_019mQaCmD1zxvjunhtQKit9e
  ```
  (Omitted from the short commit lines below for brevity — add them.)
- **Branch:** all work on a `builder-authoring-ux` branch off `master` (not on `master`).

## File Structure

- **Modify** `courses/views_manage.py` — `node_add` (Lesson/Quiz inference, Task 1) and `node_rename` (type-only toggle path, Task 2).
- **Modify** `courses/builder.py` — `rename_node` (title-`_UNSET` gating, Task 2).
- **Modify** `templates/courses/manage/_add_affordance.html` — split the unit chip into `+ Lesson`/`+ Quiz` (Task 1).
- **Modify** `templates/courses/manage/editor/editor.html` — new editor header strip with the type toggle (Task 2) + include the icon sprite (Task 4).
- **Modify** `templates/courses/manage/editor/_unit_settings.html` — remove the type `<select>` + the summary type span (Task 2).
- **Modify** `templates/courses/manage/editor/_add_menu.html` — group into Content/Questions (Task 3) + swap icons to SVG (Task 4).
- **Create** `templates/courses/manage/_icon_sprite.html` — shared hidden SVG sprite (Task 4); **modify** `templates/courses/manage/builder.html` to include it.
- **Modify** `courses/static/courses/css/editor.css` — type-toggle, group-label, scoped `.typecard .ic` styles (Tasks 2-4).
- **Modify** `courses/element_forms.py` — `_MarkingFieldsMixin` adds `class="input"` (Task 5).
- **Modify** `locale/pl/LC_MESSAGES/django.po` + `.mo` (Task 6).
- **Tests:** `tests/test_manage_node_ops.py` (Task 1/2 view tests), a new `tests/test_e2e_builder_authoring.py` (Tasks 1-4 e2e), `tests/test_manage_editor.py` or the element-forms test file (Task 5 render test).

---

### Task 1: Create a unit as Lesson or Quiz (builder add)

**Files:**
- Modify: `courses/views_manage.py` (`node_add`, lines 199-216)
- Modify: `templates/courses/manage/_add_affordance.html`
- Modify (verify): `courses/static/courses/js/builder.js` (the chip add-path)
- Test: `tests/test_manage_node_ops.py`; e2e `tests/test_e2e_builder_authoring.py` (new)

**Interfaces:**
- Produces: `node_add` accepts the two new unit chips — a POST with `name=unit_type value=lesson|quiz` and NO `kind` creates a unit of that type. An explicit `kind` still wins (a stray `unit_type` on a non-unit is ignored).

- [ ] **Step 1: Write the failing view tests**

Append to `tests/test_manage_node_ops.py` (it already defines `FETCH`, `_setup`, and imports `ContentNode`, `ContentNodeFactory`, `CourseFactory`, `make_login`, `reverse`):

```python
@pytest.mark.django_db
def test_add_quiz_chip_creates_quiz_unit(client):
    # The + Quiz chip submits name=unit_type=quiz with NO kind.
    _, course = _setup(client)
    resp = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "c1"}),
        {"parent": "top", "parent_token": course.updated.isoformat(),
         "unit_type": "quiz", "title": "Q1"},
        **FETCH,
    )
    assert resp.status_code == 200
    node = ContentNode.objects.get(course=course, title="Q1")
    assert node.kind == "unit"
    assert node.unit_type == "quiz"


@pytest.mark.django_db
def test_add_lesson_chip_creates_lesson_unit(client):
    _, course = _setup(client)
    resp = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "c1"}),
        {"parent": "top", "parent_token": course.updated.isoformat(),
         "unit_type": "lesson", "title": "L1"},
        **FETCH,
    )
    assert resp.status_code == 200
    node = ContentNode.objects.get(course=course, title="L1")
    assert node.kind == "unit"
    assert node.unit_type == "lesson"


@pytest.mark.django_db
def test_add_neither_kind_nor_unit_type_is_422(client):
    # Malformed/no-button submit: no kind, no unit_type -> kind="" -> full_clean 422.
    _, course = _setup(client)
    resp = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "c1"}),
        {"parent": "top", "parent_token": course.updated.isoformat(), "title": "X"},
        **FETCH,
    )
    assert resp.status_code == 422
```

(`test_add_non_unit_ignores_submitted_unit_type` already covers the explicit-`kind`-wins/stray case — it MUST stay green.)

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_manage_node_ops.py -k "quiz_chip or lesson_chip or neither_kind" -v`
Expected: FAIL — the quiz/lesson chips currently create nothing (no `kind`, so today's `node_add` builds `kind=""` → 422).

- [ ] **Step 3: Rewrite the kind/unit_type derivation in `node_add`**

In `courses/views_manage.py`, replace the current lines 202-207:

```python
    kind = request.POST.get("kind", "")
    # The add form's `unit_type` <select> always submits a value (it is only visually
    # hidden, not disabled, with JS off — and FormData includes it with JS on). The
    # model's clean() forbids a unit_type on a non-unit, so honour the field only for
    # units; otherwise a "part" carrying the default "lesson" would 422 spuriously.
    unit_type = request.POST.get("unit_type") if kind == ContentNode.Kind.UNIT else None
```

with:

```python
    # The two unit chips submit name=unit_type (lesson|quiz) and NO kind; every other
    # chip submits name=kind. An explicit kind WINS — a stray unit_type on a non-unit is
    # ignored, never promoted to a unit (keeps the no-JS / forged-request contract and
    # test_add_non_unit_ignores_submitted_unit_type). Only when no kind is present do we
    # infer a unit from the unit_type the Lesson/Quiz chip carried.
    kind = request.POST.get("kind", "")
    if kind:
        unit_type = (
            request.POST.get("unit_type") if kind == ContentNode.Kind.UNIT else None
        )
    elif request.POST.get("unit_type"):
        kind = ContentNode.Kind.UNIT
        unit_type = request.POST.get("unit_type")
    else:
        unit_type = None
```

- [ ] **Step 4: Split the unit chip in `_add_affordance.html`**

In `templates/courses/manage/_add_affordance.html`: (a) delete the always-sent hidden input + its comment (current lines 12-14: the 2-line `{% comment %}…{% endcomment %}` block at 12-13 plus the `<input type="hidden" name="unit_type" value="lesson">` at 14) — **do NOT touch the `data-add-title` block right below it (the title `{% comment %}` at 15-17 and the `<input … data-add-title required>` at 18-19 are preserved unchanged); only lines 12-14 are removed.** (b) Replace the `{% for kind in kinds %}…{% endfor %}` chip loop (current lines 20-24) with:

```html
    {% for kind in kinds %}
      {% if kind == 'unit' %}
        <button type="submit" name="unit_type" value="lesson"
                class="chip chip--add{% if primary and kind != primary %} chip--overflow{% endif %}"
                data-add-kind="lesson">+ {% trans "Lesson" %}</button>
        <button type="submit" name="unit_type" value="quiz"
                class="chip chip--add{% if primary and kind != primary %} chip--overflow{% endif %}"
                data-add-kind="quiz">+ {% trans "Quiz" %}</button>
      {% else %}
        <button type="submit" name="kind" value="{{ kind }}"
                class="chip chip--add{% if kind == primary %} chip--primary{% endif %}{% if primary and kind != primary %} chip--overflow{% endif %}"
                data-add-kind="{{ kind }}">+ {% kind_label kind %}</button>
      {% endif %}
    {% endfor %}
```

(`unit` is never the `primary` kind — `PRIMARY_CHILD_KIND` maps only top-scope and `part` → `chapter` — so the unit chips never need `chip--primary`. The `{% if primary %}…+…{% endif %}` "More kinds" button below is unchanged. The template already `{% load i18n courses_manage_extras %}` at line 1, so `{% trans %}` resolves.)

- [ ] **Step 5: Run the new view tests + the existing node-op suite**

Run: `uv run pytest tests/test_manage_node_ops.py -v`
Expected: PASS — the 3 new tests pass; `test_add_unit_requires_unit_type` (kind=unit, no unit_type → 422) and `test_add_non_unit_ignores_submitted_unit_type` (kind=part + stray unit_type → part) BOTH still pass.

- [ ] **Step 6: Verify the builder.js chip add-path handles the new chips**

Read `courses/static/courses/js/builder.js` around the chip add-path (~lines 313-364). The add path has **no optimistic row insertion** — on a chip click it stores `form.dataset.pendingKind = chip.value`, re-finds the chip via `button[data-add-kind="<value>"]`, calls `form.requestSubmit(btn)`, and swaps in the **server-rendered fragment** (authoritative). Because the two unit chips use `data-add-kind="lesson"`/`"quiz"` aligned with their `value`, the existing store/re-find/`requestSubmit` logic works **unchanged — no JS edit is expected**. Confirm by reading that `pendingKind` and the re-find selector key off `chip.value`/`data-add-kind` (both now "lesson"/"quiz"); let the Step 7 e2e be the gate. Only if that reading reveals the add-path hard-codes the old `"unit"` kind anywhere should you make the minimal fix.

- [ ] **Step 7: Write + run the e2e (real `+ Quiz` click)**

Create `tests/test_e2e_builder_authoring.py` mirroring the harness of `tests/test_e2e_builder.py` — copy its module-private helpers `_make_pa_user(username)` and `_login(page, live_server, username)` into the new file (and `from tests.factories import TEST_PASSWORD`), same `page`/`live_server` fixtures. The test: log in as a course owner/PA, open `/manage/courses/<slug>/build/`. **Scope matters for visibility:** at the TOP scope `primary_child_kind` is `chapter`, so the unit chips render as `chip--overflow` and are hidden until the `+…` (`data-add-more`) toggle is clicked. So FIRST add a chapter via the visible primary `+ Chapter` chip, then add the unit INSIDE that chapter's add-row — under a chapter `primary` is `None`, so `+ Lesson`/`+ Quiz` render as plain VISIBLE chips (mirror the nesting in `test_builder_full_flow`). Type a title and `.click()` the `+ Quiz` chip in the chapter's scope; assert a quiz unit was created (the new row appears AND `ContentNode.objects.get(..., unit_type="quiz")` exists). Drive REAL gestures — `.fill()` + `.click()`; no `page.evaluate`/direct POST. Align the add gesture to `test_e2e_builder.py` if selectors differ.

Run: `uv run pytest tests/test_e2e_builder_authoring.py -m e2e -v`
Expected: PASS.

- [ ] **Step 8: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/views_manage.py templates/courses/manage/_add_affordance.html courses/static/courses/js/builder.js tests/test_manage_node_ops.py tests/test_e2e_builder_authoring.py
git commit -m "feat(builder): add + Lesson / + Quiz chips to create a unit's type at add time"
```

---

### Task 2: Change unit type from a new editor header toggle

**Files:**
- Modify: `courses/views_manage.py` (`node_rename`, lines 244-266) and `courses/builder.py` (`rename_node`, lines 58-84)
- Modify: `templates/courses/manage/editor/editor.html` (new header strip) and `templates/courses/manage/editor/_unit_settings.html` (remove type select + summary span)
- Modify: `courses/static/courses/css/editor.css` (type-toggle styles)
- Test: `tests/test_manage_node_ops.py`; e2e/screenshot

**Interfaces:**
- Consumes: `rename_node(course, node_pk, title, token, unit_type=_UNSET, obligatory=_UNSET, html_seed_js=_UNSET)` (Task 2 extends it to accept `title=builder_svc._UNSET`).
- Produces: a `type_only=1` POST marker on `node_rename` that flips only `unit_type`, leaving title/obligatory/html_seed_js untouched, and routes back to the editor (`ctx=editor`).

- [ ] **Step 1: Write the failing view tests**

Append to `tests/test_manage_node_ops.py`:

```python
from courses.models import ContentNode  # already imported at top


@pytest.mark.django_db
def test_type_toggle_flips_type_without_wiping_settings(client):
    _, course = _setup(client)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None,
        title="Keep me", obligatory=True, html_seed_js="{a:1}",
    )
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "c1"}),
        {"node": unit.pk, "token": unit.updated.isoformat(), "ctx": "editor",
         "type_only": "1", "unit_type": "quiz"},
    )  # full-page POST (no FETCH) -> editor redirect
    assert resp.status_code == 302
    unit.refresh_from_db()
    assert unit.unit_type == "quiz"           # flipped
    assert unit.title == "Keep me"            # NOT blanked
    assert unit.obligatory is True            # NOT cleared
    assert unit.html_seed_js == "{a:1}"       # NOT wiped


@pytest.mark.django_db
def test_settings_form_still_updates_all_fields(client):
    # Regression: the full settings form (has_settings) still works end-to-end.
    _, course = _setup(client)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Old",
    )
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "c1"}),
        {"node": unit.pk, "token": unit.updated.isoformat(), "ctx": "editor",
         "has_settings": "1", "title": "New", "unit_type": "quiz", "html_seed_js": ""},
    )
    assert resp.status_code == 302
    unit.refresh_from_db()
    assert unit.title == "New"
    assert unit.unit_type == "quiz"
    assert unit.obligatory is False  # checkbox absent -> cleared, as before
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_manage_node_ops.py -k "type_toggle or settings_form_still" -v`
Expected: FAIL — `test_type_toggle...` blanks the title (today `node_rename` forwards `title=POST.get("title","")=""` and `rename_node` assigns it unconditionally → `full_clean` 422 or blanked title).

- [ ] **Step 3: Add the title-`_UNSET` gate in `rename_node`**

In `courses/builder.py`, replace the body of `rename_node` from `node.title = title` through the `fields` build (current lines 70-81) — replace:

```python
    node.title = title
    fields = ["title", "updated"]
    if node.kind == ContentNode.Kind.UNIT:
        if unit_type is not _UNSET:
            node.unit_type = unit_type
            fields.append("unit_type")
        if obligatory is not _UNSET:
            node.obligatory = obligatory
            fields.append("obligatory")
        if html_seed_js is not _UNSET:
            node.html_seed_js = html_seed_js
            fields.append("html_seed_js")
```

with:

```python
    fields = ["updated"]
    if title is not _UNSET:
        node.title = title
        fields.append("title")
    if node.kind == ContentNode.Kind.UNIT:
        if unit_type is not _UNSET:
            node.unit_type = unit_type
            fields.append("unit_type")
        if obligatory is not _UNSET:
            node.obligatory = obligatory
            fields.append("obligatory")
        if html_seed_js is not _UNSET:
            node.html_seed_js = html_seed_js
            fields.append("html_seed_js")
```

(When `title is _UNSET`, `node.title` keeps its loaded DB value; `full_clean()` at line 82 still validates it; `"title"` is dropped from `update_fields` so the unchanged value isn't re-saved.)

- [ ] **Step 4: Add the `type_only` path in `node_rename`**

In `courses/views_manage.py`, in `node_rename`, after `is_settings = "has_settings" in request.POST` (line 246) add `is_type_only = "type_only" in request.POST`, then replace the `rename_node(...)` call's `title` and `unit_type` arguments (lines 255-259) so:

```python
        node = builder_svc.rename_node(
            course,
            node_pk,
            # type-only toggle leaves the title untouched (never blanks it)
            builder_svc._UNSET if is_type_only else request.POST.get("title", ""),
            request.POST.get("token"),
            unit_type=request.POST.get("unit_type")
            if (is_settings or is_type_only)
            else builder_svc._UNSET,
            obligatory=("obligatory" in request.POST)
            if is_settings
            else builder_svc._UNSET,
            html_seed_js=request.POST.get("html_seed_js", "")
            if is_settings
            else builder_svc._UNSET,
        )
```

(`obligatory`/`html_seed_js` stay `_UNSET` for the toggle because `is_type_only` does not set `is_settings`; `ctx=editor` makes `to_editor` true so success/422/conflict all route back to the editor — unchanged routing.)

- [ ] **Step 5: Run the view tests + node-op regression**

Run: `uv run pytest tests/test_manage_node_ops.py -v`
Expected: PASS — both new tests pass; existing rename/settings tests stay green.

- [ ] **Step 6: Add the editor header strip + remove the duplicate type controls**

In `templates/courses/manage/editor/editor.html`, immediately AFTER the `</p>` that closes `editor-crumb` (line 34) and BEFORE the `{% include "courses/manage/editor/_unit_settings.html" %}` (line 35), insert:

```html
  <div class="editor-head">
    <h1 class="editor-head__title">{{ unit.title }}</h1>
    <form class="type-toggle" method="post" action="{% url 'courses:manage_node_rename' slug=course.slug %}">
      {% csrf_token %}
      <input type="hidden" name="node" value="{{ unit.pk }}">
      <input type="hidden" name="token" value="{{ unit.updated.isoformat }}">
      <input type="hidden" name="ctx" value="editor">
      <input type="hidden" name="type_only" value="1">
      <button type="submit" name="unit_type" value="lesson"
              class="type-toggle__btn{% if unit.unit_type == 'lesson' %} is-active{% endif %}"
              {% if unit.unit_type == 'lesson' %}aria-current="true"{% endif %}>{% trans "Lesson" %}</button>
      <button type="submit" name="unit_type" value="quiz"
              class="type-toggle__btn{% if unit.unit_type == 'quiz' %} is-active{% endif %}"
              {% if unit.unit_type == 'quiz' %}aria-current="true"{% endif %}>{% trans "Quiz" %}</button>
    </form>
  </div>
```

In `templates/courses/manage/editor/_unit_settings.html`: (a) delete line 5 (`<span class="editor-head__type">…</span>`); (b) delete the Type-select block (lines 15-20, from `<label>{% trans "Type" %}` through its `</label>`).

- [ ] **Step 7: Style the toggle in `editor.css`**

Add to `courses/static/courses/css/editor.css` (reuse existing tokens; legible light + dark):

```css
.editor-head { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; margin: var(--space-2) 0; }
.editor-head__title { font-size: 1.1rem; margin: 0; }
.type-toggle { display: inline-flex; border: 1px solid var(--border-default); border-radius: var(--radius-md); overflow: hidden; }
.type-toggle__btn { padding: 4px 12px; background: var(--surface-sunken); color: var(--text-secondary); border: 0; cursor: pointer; font: inherit; }
.type-toggle__btn + .type-toggle__btn { border-left: 1px solid var(--border-default); }
.type-toggle__btn.is-active { background: var(--primary); color: var(--surface-raised); }
```

Also delete the now-orphaned `.editor-head__type { … }` rule at `editor.css:199` — its only span was removed in Step 6, and the new header uses `.editor-head__title` (a different class), so the old rule is dead CSS.

- [ ] **Step 8: Add a retained e2e for the toggle gesture**

Add a test to `tests/test_e2e_builder_authoring.py` (created in Task 1): log in as the course owner, open a lesson unit's editor (`/manage/courses/<slug>/build/unit/<pk>/edit/`), click the `Quiz` button in `.type-toggle` (real `.click()`), wait for the editor to re-render, and assert the unit is now a quiz (`ContentNode.objects.get(pk=...).unit_type == "quiz"` AND the rendered `Quiz` button now carries `is-active`). No `page.evaluate`/direct POST.

Run: `uv run pytest tests/test_e2e_builder_authoring.py -m e2e -k toggle -v`
Expected: PASS.

- [ ] **Step 9: Verify in the browser (light + dark) + run the editor view suite**

Write a throwaway Playwright screenshot script (delete after review) that opens a unit editor in light and dark and captures the header; confirm the `Lesson · Quiz` toggle is visible, the active type is highlighted legibly in BOTH themes, the unit title shows, and Settings no longer shows a Type select or a duplicate type label. Delete the script.

Run: `uv run pytest tests/test_manage_node_ops.py -q` (whole file green)
Expected: PASS.

- [ ] **Step 10: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/views_manage.py courses/builder.py templates/courses/manage/editor/editor.html templates/courses/manage/editor/_unit_settings.html courses/static/courses/css/editor.css tests/test_manage_node_ops.py tests/test_e2e_builder_authoring.py
git commit -m "feat(editor): Lesson/Quiz toggle in the editor header (type-only rename path)"
```

---

### Task 3: Group the add-element menu (Content vs Questions)

**Files:**
- Modify: `templates/courses/manage/editor/_add_menu.html`
- Modify: `courses/static/courses/css/editor.css`
- Test: create `tests/test_manage_editor_menu.py` (GET the editor page for a unit — the editor renders `_add_menu` via `_editor_scope.html:15`); e2e in `tests/test_e2e_builder_authoring.py`

**Interfaces:**
- Produces: `_add_menu.html` renders two labelled groups; the outer wrapper keeps `data-type-menu`; all 15 `.typecard` cards remain.

- [ ] **Step 1: Write the failing render test**

Create `tests/test_manage_editor_menu.py` — GET the editor page for a unit (it renders `_add_menu` via `_editor_scope.html`) and assert BOTH group labels + the per-group card split (uses the same `make_login`/`CourseFactory`/`ContentNodeFactory` helpers as `tests/test_manage_node_ops.py`):

```python
import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory, CourseFactory, make_login


@pytest.mark.django_db
def test_add_menu_grouped_content_and_questions(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="U"
    )
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": "c1", "pk": unit.pk})
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Content" in body and "Questions" in body          # group labels
    assert body.count('data-add-type="') == 15                # all 15 cards kept
    assert 'data-type-menu' in body                           # wrapper unmoved
    for key in ("text", "image", "video", "iframe", "math", "html"):
        assert f'data-add-type="{key}"' in body               # 6 content cards
    for key in ("choice-single", "choice-multi", "shorttextquestion",
                "shortnumericquestion", "fillblankquestion", "dragfillblankquestion",
                "matchpairquestion", "dragtoimagequestion", "extendedresponsequestion"):
        assert f'data-add-type="{key}"' in body               # 9 question cards
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest -k "add_menu_grouped" -v`
Expected: FAIL — "Content"/"Questions" labels absent from the flat menu.

- [ ] **Step 3: Regroup the cards in `_add_menu.html`**

Rewrite `templates/courses/manage/editor/_add_menu.html` so the 15 cards live in two child groups inside the existing `[data-type-menu]` wrapper (keep every `data-add-type` value and the `.ic` icon spans exactly as they are — icons become SVG in Task 4):

```html
{% load i18n %}
<div class="addwrap" data-add-menu>
  <button type="button" class="addbtn" data-add-toggle>＋ {% trans "Add element" %}</button>
  <div class="typemenu" hidden data-type-menu>
    <p class="typemenu__group-label">{% trans "Content" %}</p>
    <div class="typemenu__group">
      <button type="button" class="typecard" data-add-type="text"><span class="ic">📝</span>{% trans "Text" %}</button>
      <button type="button" class="typecard" data-add-type="image"><span class="ic">🖼</span>{% trans "Image" %}</button>
      <button type="button" class="typecard" data-add-type="video"><span class="ic">▶</span>{% trans "Video" %}</button>
      <button type="button" class="typecard" data-add-type="iframe"><span class="ic">🔗</span>{% trans "Iframe" %}</button>
      <button type="button" class="typecard" data-add-type="math"><span class="ic">∑</span>{% trans "Math" %}</button>
      <button type="button" class="typecard" data-add-type="html"><span class="ic">&lt;/&gt;</span>{% trans "HTML" %}</button>
    </div>
    <p class="typemenu__group-label">{% trans "Questions" %}</p>
    <div class="typemenu__group">
      <button type="button" class="typecard" data-add-type="choice-single"><span class="ic">◉</span>{% trans "Single choice" %}</button>
      <button type="button" class="typecard" data-add-type="choice-multi"><span class="ic">☑</span>{% trans "Multiple choice" %}</button>
      <button type="button" class="typecard" data-add-type="shorttextquestion"><span class="ic">⌨</span>{% trans "Short text" %}</button>
      <button type="button" class="typecard" data-add-type="shortnumericquestion"><span class="ic">#</span>{% trans "Short numeric" %}</button>
      <button type="button" class="typecard" data-add-type="fillblankquestion"><span class="ic">▭</span>{% trans "Fill in the blanks" %}</button>
      <button type="button" class="typecard" data-add-type="dragfillblankquestion"><span class="ic">🧲</span>{% trans "Drag the words" %}</button>
      <button type="button" class="typecard" data-add-type="matchpairquestion"><span class="ic">🔗</span>{% trans "Match pairs" %}</button>
      <button type="button" class="typecard" data-add-type="dragtoimagequestion"><span class="ic">🖼️</span>{% trans "Drag to image" %}</button>
      <button type="button" class="typecard" data-add-type="extendedresponsequestion"><span class="ic">✍</span>{% trans "Extended response" %}</button>
    </div>
  </div>
</div>
```

(The click handler is `e.target.closest("[data-add-type]")` at `editor.js:180` — a descendant match — so nesting cards inside `.typemenu__group` needs NO JS change. `data-type-menu` stays on the outer `.typemenu` for the open/close handler.)

- [ ] **Step 4: Style the groups in `editor.css`**

Migrate the grid OFF `.typemenu` onto `.typemenu__group` and add the label style. `.typemenu` IS a grid today (`editor.css:289` `.typemenu { margin-top: …; display: grid; grid-template-columns: …; gap: …; }`) with a mobile override at `editor.css:300` (`@media (max-width: 720px) { .typemenu { grid-template-columns: repeat(3, 1fr); } }`). After regrouping, the two `<p>` labels and the two group `<div>`s are the menu's direct children, so `.typemenu` must NOT be a grid (else the labels become grid cells). Read the actual `.typemenu` rule (lines 289-292) first to preserve any other declarations, then make these three changes:

```css
/* line 289: .typemenu becomes a plain block container — keep margin-top, drop display:grid + grid-template-columns + gap */
.typemenu { margin-top: var(--space-2); }
.typemenu[hidden] { display: none; }   /* unchanged */
.typemenu__group-label { margin: var(--space-2) 0 4px; font-size: .72rem; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--text-secondary); }
.typemenu__group { display: grid; grid-template-columns: repeat(auto-fill, minmax(96px, 1fr)); gap: var(--space-2); }
/* line 300: RETARGET the mobile override from .typemenu to .typemenu__group (else it strands on a non-grid) */
@media (max-width: 720px) { .typemenu__group { grid-template-columns: repeat(3, 1fr); } }
```

- [ ] **Step 5: Run the render test + verify the menu still works (light + dark)**

Run: `uv run pytest -k "add_menu_grouped" -v` → PASS.
Add an e2e step to `tests/test_e2e_builder_authoring.py` (or extend the Task-1 e2e): open the editor, click `Add element`, assert both group labels are visible, click a card under "Questions" (e.g. Extended response), and assert the element form opens. Throwaway-screenshot the open menu in light + dark to confirm the divider/labels read clearly; delete the script.

Run: `uv run pytest tests/test_e2e_builder_authoring.py -m e2e -v` → PASS.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add templates/courses/manage/editor/_add_menu.html courses/static/courses/css/editor.css tests/
git commit -m "feat(editor): group the add-element menu into Content and Questions"
```

---

### Task 4: Monochrome SVG element-card icons

**Files:**
- Create: `templates/courses/manage/_icon_sprite.html`
- Modify: `templates/courses/manage/builder.html` (move its inline `bi-*` sprite into the include) and `templates/courses/manage/editor/editor.html` (include the sprite)
- Modify: `templates/courses/manage/editor/_add_menu.html` (swap `.ic` spans → `<svg><use>`)
- Modify: `courses/static/courses/css/editor.css` (scoped `.typecard .ic`)
- Test: render test (sprite + `<use>` present); light/dark screenshots

**Interfaces:**
- Produces: `templates/courses/manage/_icon_sprite.html` — a hidden `<svg>` carrying the existing `bi-*` symbols plus 15 new `el-*` element-type symbols, included on both the builder and editor pages.

**Canonical mapping (single source of truth for Steps 1, 3, 4 — keep all three consistent with this table):**

| card `data-add-type` | symbol id | Bootstrap-Icons source (v1.11.x) |
|---|---|---|
| `text` | `el-text` | `card-text.svg` |
| `image` | `el-image` | `image.svg` |
| `video` | `el-video` | `play-btn.svg` |
| `iframe` | `el-iframe` | `window.svg` |
| `math` | `el-math` | `calculator.svg` (or custom ∑) |
| `html` | `el-html` | `code-slash.svg` |
| `choice-single` | `el-choice-single` | `record-circle.svg` |
| `choice-multi` | `el-choice-multi` | `check2-square.svg` |
| `shorttextquestion` | `el-shorttext` | `input-cursor-text.svg` |
| `shortnumericquestion` | `el-shortnumeric` | `123.svg` |
| `fillblankquestion` | `el-fillblank` | `input-cursor.svg` |
| `dragfillblankquestion` | `el-dragwords` | `hand-index.svg` |
| `matchpairquestion` | `el-matchpairs` | `link-45deg.svg` |
| `dragtoimagequestion` | `el-dragimage` | `bounding-box.svg` |
| `extendedresponsequestion` | `el-extended` | `pencil-square.svg` |

- [ ] **Step 1: Write the failing render test**

Add to `tests/test_manage_editor_menu.py` a test asserting EVERY card now uses its `el-*` SVG and the sprite defines each symbol — so a misnamed/missing id fails HERE, not only at screenshot review. The map mirrors the canonical mapping table above:

```python
EL_ICON_MAP = {
    "text": "el-text", "image": "el-image", "video": "el-video", "iframe": "el-iframe",
    "math": "el-math", "html": "el-html", "choice-single": "el-choice-single",
    "choice-multi": "el-choice-multi", "shorttextquestion": "el-shorttext",
    "shortnumericquestion": "el-shortnumeric", "fillblankquestion": "el-fillblank",
    "dragfillblankquestion": "el-dragwords", "matchpairquestion": "el-matchpairs",
    "dragtoimagequestion": "el-dragimage", "extendedresponsequestion": "el-extended",
}


@pytest.mark.django_db
def test_add_menu_icons_are_svg(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="U"
    )
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": "c1", "pk": unit.pk})
    )
    body = resp.content.decode()
    for sym in EL_ICON_MAP.values():
        assert f'<use href="#{sym}"' in body     # every card references its el-* symbol
        assert f'<symbol id="{sym}"' in body      # and the sprite defines it
    assert "📝" not in body and "🖼" not in body    # no emoji left in the menu
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest -k "add_menu_icons_are_svg" -v`
Expected: FAIL — the cards still use emoji; no `el-*` sprite on the page.

- [ ] **Step 3: Create the shared sprite partial**

Create `templates/courses/manage/_icon_sprite.html`. Move the existing `bi-*` `<symbol>` block out of `builder.html` into this file, and add 15 `el-*` symbols. **Source each shape verbatim from Bootstrap Icons v1.11.x** (`https://github.com/twbs/icons`, MIT): each `icons/<name>.svg` is already a `viewBox="0 0 16 16"` SVG whose inner `<path .../>` you copy UNCHANGED into the matching `<symbol id="el-…" viewBox="0 0 16 16">`, adding `fill="currentColor"` on the path (BI paths inherit fill from the root `<svg>`, which a `<symbol>`/`<use>` won't supply; the `.typecard .ic { fill: currentColor }` rule from Step 5 also supplies it — belt-and-suspenders). **BI source file per id:** `el-text`←`card-text.svg`, `el-image`←`image.svg`, `el-video`←`play-btn.svg`, `el-iframe`←`window.svg`, `el-html`←`code-slash.svg`, `el-choice-single`←`record-circle.svg`, `el-choice-multi`←`check2-square.svg`, `el-shorttext`←`input-cursor-text.svg`, `el-shortnumeric`←`123.svg`, `el-fillblank`←`input-cursor.svg`, `el-dragwords`←`hand-index.svg`, `el-matchpairs`←`link-45deg.svg`, `el-dragimage`←`bounding-box.svg`, `el-extended`←`pencil-square.svg`. `el-math` has no clean BI match — copy `calculator.svg` or hand-author a simple ∑ path. Keep a one-line MIT attribution comment. Skeleton:

```html
{% comment %}Hand-authored monochrome icon sprite (hidden). bi-* = builder tree
actions; el-* = element-type cards. el-* paths adapted from Bootstrap Icons
(MIT, https://github.com/twbs/icons).{% endcomment %}
<svg width="0" height="0" class="icon-sprite" aria-hidden="true" focusable="false">
  <!-- existing builder tree symbols (move the block verbatim from builder.html;
       its real order is bi-grip, bi-up, bi-down, bi-move, bi-trash — order is
       irrelevant to <use>, so the listing below is illustrative) -->
  <symbol id="bi-up" ...>...</symbol>
  <symbol id="bi-down" ...>...</symbol>
  <symbol id="bi-grip" ...>...</symbol>
  <symbol id="bi-move" ...>...</symbol>
  <symbol id="bi-trash" ...>...</symbol>
  <!-- element-type symbols -->
  <symbol id="el-text" viewBox="0 0 16 16"><path fill="currentColor" d="…"/></symbol>
  <symbol id="el-image" viewBox="0 0 16 16"><path fill="currentColor" d="…"/></symbol>
  <symbol id="el-video" viewBox="0 0 16 16"><path fill="currentColor" d="…"/></symbol>
  <symbol id="el-iframe" viewBox="0 0 16 16"><path fill="currentColor" d="…"/></symbol>
  <symbol id="el-math" viewBox="0 0 16 16"><path fill="currentColor" d="…"/></symbol>
  <symbol id="el-html" viewBox="0 0 16 16"><path fill="currentColor" d="…"/></symbol>
  <symbol id="el-choice-single" viewBox="0 0 16 16"><path fill="currentColor" d="…"/></symbol>
  <symbol id="el-choice-multi" viewBox="0 0 16 16"><path fill="currentColor" d="…"/></symbol>
  <symbol id="el-shorttext" viewBox="0 0 16 16"><path fill="currentColor" d="…"/></symbol>
  <symbol id="el-shortnumeric" viewBox="0 0 16 16"><path fill="currentColor" d="…"/></symbol>
  <symbol id="el-fillblank" viewBox="0 0 16 16"><path fill="currentColor" d="…"/></symbol>
  <symbol id="el-dragwords" viewBox="0 0 16 16"><path fill="currentColor" d="…"/></symbol>
  <symbol id="el-matchpairs" viewBox="0 0 16 16"><path fill="currentColor" d="…"/></symbol>
  <symbol id="el-dragimage" viewBox="0 0 16 16"><path fill="currentColor" d="…"/></symbol>
  <symbol id="el-extended" viewBox="0 0 16 16"><path fill="currentColor" d="…"/></symbol>
</svg>
```

In `templates/courses/manage/builder.html`, replace its inline `bi-*` `<svg>` sprite block with `{% include "courses/manage/_icon_sprite.html" %}`. In `templates/courses/manage/editor/editor.html`, add `{% include "courses/manage/_icon_sprite.html" %}` near the top of the `<section class="editor">` (just after the existing `editor__sprite` `</svg>`, line 24). (The shared partial carries `bi-*` for the builder and `el-*` for both pages; the editor only consumes `el-*`, so its 5 unused `bi-*` symbols are harmless dead weight — an accepted tradeoff of one shared partial.)

- [ ] **Step 4: Swap the menu icons to `<use>`**

In `templates/courses/manage/editor/_add_menu.html`, replace each `<span class="ic">EMOJI</span>` with the matching SVG per the **canonical mapping table above**. The icons are decorative (the card's `{% trans %}` text label conveys meaning), so mark each `aria-hidden="true" focusable="false"` — matching the repo's other sprite-consuming SVGs. E.g. `text`→`<svg class="ic" aria-hidden="true" focusable="false"><use href="#el-text"/></svg>`; likewise `image`→`#el-image`, `video`→`#el-video`, `iframe`→`#el-iframe`, `math`→`#el-math`, `html`→`#el-html`, `choice-single`→`#el-choice-single`, `choice-multi`→`#el-choice-multi`, `shorttextquestion`→`#el-shorttext`, `shortnumericquestion`→`#el-shortnumeric`, `fillblankquestion`→`#el-fillblank`, `dragfillblankquestion`→`#el-dragwords`, `matchpairquestion`→`#el-matchpairs`, `dragtoimagequestion`→`#el-dragimage`, `extendedresponsequestion`→`#el-extended`.

- [ ] **Step 5: Scope the icon CSS (don't regress the tree icons)**

In `courses/static/courses/css/editor.css`, change the existing `.typecard .ic { font-size: 1.2rem; }` to size the SVG explicitly and inherit colour — scoped to `.typecard` so the builder tree's `.ic` SVGs are untouched:

```css
.typecard .ic { width: 1.2rem; height: 1.2rem; fill: currentColor; }
```

- [ ] **Step 6: Run the render test + screenshot (light + dark) + tree no-regression**

Run: `uv run pytest -k "add_menu_icons_are_svg" -v` → PASS.
Throwaway-screenshot the open add-menu in light + dark — confirm each card icon renders as a VISIBLE glyph (NOT an empty box: a wrong/empty `d` renders blank, which the render test can't catch), monochrome, theme-coloured, consistent — AND the builder tree (the `bi-*` grip/move/trash icons must look identical to before the sprite move — a before/after). Delete the script.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add templates/courses/manage/_icon_sprite.html templates/courses/manage/builder.html templates/courses/manage/editor/editor.html templates/courses/manage/editor/_add_menu.html courses/static/courses/css/editor.css tests/
git commit -m "feat(editor): monochrome SVG element-card icons via shared sprite"
```

---

### Task 5: Dark-mode legibility of the marking inputs

**Files:**
- Modify: `courses/element_forms.py` (`_MarkingFieldsMixin`, ~lines 31-44)
- Test: a render test asserting `class="input"` on the marking widgets for each question type (find the element-forms test file: `git grep -l "_MarkingFieldsMixin\|marking_mode\|ChoiceQuestionElementForm" tests/`)

**Interfaces:**
- Consumes: `_MarkingFieldsMixin.__init__` (already loops over the three marking fields).
- Produces: every question form's `marking_mode`/`max_attempts`/`max_marks` widget carries `class="input"`.

- [ ] **Step 1: Write the failing test**

In the element-forms test file, add:

```python
import pytest
from courses.element_forms import (
    ChoiceQuestionElementForm, ShortTextQuestionElementForm,
    ShortNumericQuestionElementForm, FillBlankQuestionElementForm,
    DragFillBlankQuestionElementForm, MatchPairQuestionElementForm,
    DragToImageQuestionElementForm, ExtendedResponseQuestionElementForm,
)

ALL_QUESTION_FORMS = [
    ChoiceQuestionElementForm, ShortTextQuestionElementForm,
    ShortNumericQuestionElementForm, FillBlankQuestionElementForm,
    DragFillBlankQuestionElementForm, MatchPairQuestionElementForm,
    DragToImageQuestionElementForm, ExtendedResponseQuestionElementForm,
]


@pytest.mark.django_db
@pytest.mark.parametrize("FormCls", ALL_QUESTION_FORMS)
def test_marking_widgets_have_input_class(FormCls):
    form = FormCls()  # all 8 construct bare: _CourseScopedMediaForm's course= defaults to None
    for name in ("marking_mode", "max_attempts", "max_marks"):
        assert "input" in form.fields[name].widget.attrs.get("class", "")
```

(All 8 question forms — including `DragToImageQuestionElementForm`, whose `_CourseScopedMediaForm.__init__(self, *args, course=None, **kwargs)` makes `course` optional — construct bare, so the parametrization covers every type the spec requires. `@pytest.mark.django_db` is set because a ModelForm with a `media` ModelChoiceField may touch the DB on init.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest -k "marking_widgets_have_input_class" -v`
Expected: FAIL — the marking widgets have no `class` attr today.

- [ ] **Step 3: Add the class in `_MarkingFieldsMixin.__init__`**

In `courses/element_forms.py`, inside `_MarkingFieldsMixin.__init__`'s existing `for field_name in ("marking_mode", "max_attempts", "max_marks"):` loop (where it sets `required = False`), also add the editor input class:

```python
        for field_name in ("marking_mode", "max_attempts", "max_marks"):
            if field_name in self.fields:
                self.fields[field_name].required = False
                self.fields[field_name].widget.attrs["class"] = "input"
```

(Match the existing loop body — keep whatever `required=False` / guard lines are already there; just add the `attrs["class"]` line inside the same `if field_name in self.fields:` guard. Only `class` is added — the widget's auto `id` (`id_marking_mode`, etc.) is untouched, so the `_marking_fields.html` `<label for="id_marking_mode">` bindings still match.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest -k "marking_widgets_have_input_class" -v`
Expected: PASS (all 7+ parametrized cases).

- [ ] **Step 5: Verify dark mode (screenshot)**

Throwaway-screenshot a quiz unit's element editor (a question form with the marking fields) in DARK mode: the `marking_mode` select and the `max_attempts`/`max_marks` inputs must show legible text on the themed `--surface-sunken` background. Also check the `marking_mode` select's dropdown-arrow legibility — if the native arrow stays dark-on-dark, add a small scoped CSS touch (e.g. a `color-scheme` or arrow override on `.el-editor__marking-fields select`) and re-shoot. Light mode unchanged. Delete the script.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/element_forms.py tests/
git commit -m "fix(editor): theme the quiz marking inputs so they're legible in dark mode"
```

---

### Task 6: i18n — Polish translations + compile, and final verification

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.mo`

**Interfaces:** none (string catalog + final DoD).

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l pl`
Expected: new `msgid`s for the strings added in Tasks 3 (and any new ones): **"Content"**, **"Questions"**. (Lesson/Quiz/Type/etc. reuse existing msgids — confirm no NEW entry was created for them. The toggle/header add no literal copy beyond Lesson/Quiz.)

- [ ] **Step 2: Translate the new msgids in `django.po`**

Translate **every** new `msgstr ""` entry `makemessages` produced (iterate the full `git diff` of the `.po` for empty/new msgstrs — do not assume only the two expected strings; the menu rewrite and toggle could surface another new msgid). The expected new entries:

```
msgid "Content"
msgstr "Treść"

msgid "Questions"
msgstr "Pytania"
```

CLEAR any `#, fuzzy` flag `makemessages` added. Grep each new msgid to confirm the `msgstr` is the correct Polish and not a mis-guessed copy:
Run: `git diff locale/pl/LC_MESSAGES/django.po | grep -B1 -A1 'msgstr "Treść"\|msgstr "Pytania"'`

- [ ] **Step 3: Compile**

Run: `uv run python manage.py compilemessages`
Expected: writes `locale/pl/LC_MESSAGES/django.mo` with no errors. (If `compilemessages` falsely reports "up to date" due to timestamps, invoke `uv run python -m django compilemessages` or `msgfmt` directly to force the rebuild, and confirm the `.mo` byte size grew.)

- [ ] **Step 4: Final DoD verification**

Run each and confirm green:
- `uv run pytest -q -m "not e2e"` — full non-e2e suite passes (incl. the existing builder/node-op/element-form regressions).
- `uv run pytest -m e2e -q` — e2e passes (incl. the new `tests/test_e2e_builder_authoring.py`, real gestures).
- `uv run ruff check .` and `uv run ruff format --check .` — both clean.
- `uv run python manage.py makemigrations --check --dry-run` — reports no changes (no schema touched).
- Manual smoke (or final screenshot review): add a unit via `+ Quiz` → it's a quiz; open its editor → the `Lesson · Quiz` header toggle reflects/flips type without wiping settings; the add-element menu shows Content/Questions groups with monochrome SVG icons; a quiz question's marking inputs are legible in dark mode.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(builder): Polish translations for the grouped add-element menu"
```

---

## Final verification

- [ ] Full suite green: `uv run pytest -q -m "not e2e"` and `uv run pytest -m e2e -q`.
- [ ] `uv run ruff check .` and `uv run ruff format --check .` both clean.
- [ ] `uv run python manage.py makemigrations --check --dry-run` reports no missing migrations.
- [ ] `.mo` recompiled; new PL strings render under the `pl` locale; no `#, fuzzy` left on new entries; no 3a/3b regression.
- [ ] Visual: builder add-row shows `+ Lesson`/`+ Quiz`; editor header shows the type toggle (no type control left in Settings, no duplicate type label); grouped menu with consistent monochrome icons; tree icons unchanged; marking inputs legible in dark mode.
