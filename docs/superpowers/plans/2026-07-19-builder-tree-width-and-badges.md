# Tidy the builder tree — reclaim width & sharpen unit badges — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the course-builder tree read cleanly — replace the long "Unit"/"Jednostka" unit badge with a short, informative `L`/`Q` (lesson/quiz) badge, widen the tree column to a 2:1 ratio, and truncate over-long unit titles with an ellipsis instead of wrapping.

**Architecture:** Presentation-only. Three coordinated edits: (1) the unit badge in the `_tree_node.html` template partial becomes a Django `{% if %}` conditional emitting a hardcoded `L`/`Q` letter with a translated `title` tooltip, defensively falling back to today's word badge; (2) `builder.css` changes the builder grid from `1fr 1fr` to `2fr 1fr` and makes only the empty/course panel a flex column so its buttons stack; (3) `.tree__title` gets single-line ellipsis truncation plus a `title` hover attribute. No model, view, migration, or JS changes.

**Tech Stack:** Django templates + i18n (`gettext`), a token-driven bespoke CSS file (no Bootstrap), pytest / pytest-django for render + CSS-text tests, Playwright (`page`, `live_server` fixtures) for the e2e visual check.

## Global Constraints

- **Tooling runs under `uv`:** bash `ruff`/`pytest`/`python` are NOT on PATH. Use `uv run ruff …`, `uv run pytest …`. `ruff format --check` too.
- **pytest verdict lines don't survive the Bash pipe** — judge pass/fail by the process exit code and by grepping for `FAILED`/`PASSED`, not by expecting the summary line to print.
- **The `L`/`Q` letters are hardcoded and identical in every language** — they MUST NOT be wrapped in `{% trans %}`/`gettext`. Only the tooltip (`get_unit_type_display`) localizes.
- **No hardcoded test passwords** — use `tests.factories.TEST_PASSWORD` / the `make_login` / `make_verified_user` helpers.
- **Django template comments must be single-line** `{# … #}` (or `{% comment %}`), never multi-line.
- **`get_unit_type_display` / `get_kind_display`** are Django's auto-generated, already-translatable accessors — do not re-wrap them.
- **Move picker (`_move_picker.html`) is deliberately out of scope** — it renders its own badge markup and is left on the word badge. Do NOT edit it.
- **Exact CSS scope:** the panel flex-column rule targets ONLY `.builder__panel .panel[data-panel-for="course"]` — never the bare `.builder__panel .panel` (regresses the unit panel) nor `.builder__panel` (no-op).

---

### Task 1: Unit badge `L`/`Q` + tooltips in the tree partial

Replace the unit badge with a hardcoded `L`/`Q` letter + translated tooltip, add a hover `title` to the title button, and pin the behavior with Django render tests. Units are leaves (`_tree_node.html` guards the child-scope include with `{% if node.kind != "unit" %}`), so a unit node renders via `render_to_string` with a trivial context and no scope recursion — this is what makes the locale-specific assertions clean and middleware-free.

**Files:**
- Modify: `templates/courses/manage/_tree_node.html` (badge `<span>` at line 5; title `<button>` at lines 6–7)
- Create: `tests/test_tree_badge.py`

**Interfaces:**
- Consumes: `ContentNode.kind`, `ContentNode.unit_type` (existing fields, values `"lesson"`/`"quiz"`), `node.get_unit_type_display`, `node.get_kind_display`. Test factories `CourseFactory`, `ContentNodeFactory`, `make_login` from `tests/factories.py`.
- Produces: the exact unit-badge markup other code/tests depend on —
  - lesson: `<span class="tree__badge tree__badge--unit tree__badge--lesson" title="{localized}">L</span>`
  - quiz: `<span class="tree__badge tree__badge--unit tree__badge--quiz" title="{localized}">Q</span>`
  - fallback (any `unit_type` outside `lesson`/`quiz`, incl. empty): `<span class="tree__badge tree__badge--unit">Unit</span>` (no `title`)
  - title button now carries `title="{{ node.title }}"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tree_badge.py`:

```python
import re

import pytest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

# Scoped to the UNIT badge span only (requires the load-bearing tree__badge--unit
# colour hook). Groups: 1=per-type modifier, 2=title attr, 3=inner text. Attribute
# order is fixed by the template, so this stays deterministic.
UNIT_BADGE_RE = re.compile(
    r'<span class="tree__badge tree__badge--unit'
    r'(?: tree__badge--(lesson|quiz))?"'
    r'(?: title="([^"]*)")?>'
    r'([^<]*)</span>'
)
# The title button's hover-title (edit #3). [^>]* spans the tag's line break
# because it also matches newlines (any char except '>').
TITLE_BTN_RE = re.compile(r'<button class="tree__title"[^>]*\btitle="([^"]*)"')


def _render_unit(unit_type, title="Intro", lang=None):
    """Render a single leaf unit row. Units render no child scope, so a trivial
    context suffices. `lang` wraps the render in that locale."""
    course = CourseFactory(slug="c1")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type=unit_type, parent=None, title=title
    )
    ctx = {"node": unit, "children_map": {}, "is_first": True, "is_last": True}
    if lang:
        with translation.override(lang):
            return render_to_string("courses/manage/_tree_node.html", ctx)
    return render_to_string("courses/manage/_tree_node.html", ctx)


def _badge(body):
    m = UNIT_BADGE_RE.search(body)
    assert m, "unit badge span not found"
    return {"modifier": m.group(1), "title": m.group(2), "text": m.group(3), "span": m.group(0)}


@pytest.mark.django_db
def test_lesson_badge_is_L_with_localized_tooltip():
    b = _badge(_render_unit("lesson"))
    assert b["text"] == "L"
    assert b["title"] == "Lesson"
    assert b["modifier"] == "lesson"


@pytest.mark.django_db
def test_quiz_badge_is_Q_with_tooltip():
    b = _badge(_render_unit("quiz"))
    assert b["text"] == "Q"
    assert b["title"] == "Quiz"
    assert b["modifier"] == "quiz"


@pytest.mark.django_db
def test_unit_badge_keeps_accent_colour_class():
    # The whole span is rewritten by edit #1; the accent-colour hook must survive.
    for ut in ("lesson", "quiz"):
        assert "tree__badge--unit" in _badge(_render_unit(ut))["span"]


@pytest.mark.django_db
def test_title_button_has_hover_title():
    m = TITLE_BTN_RE.search(_render_unit("lesson", title="Intro"))
    assert m, "title button title attr not found"
    assert m.group(1) == "Intro"


@pytest.mark.django_db
def test_letter_is_not_translated_under_pl():
    # L/Q are hardcoded — identical across locales.
    assert _badge(_render_unit("lesson", lang="pl"))["text"] == "L"
    assert _badge(_render_unit("quiz", lang="pl"))["text"] == "Q"


@pytest.mark.django_db
def test_lesson_tooltip_localizes_to_pl():
    # Only the lesson tooltip visibly changes (PL "Quiz" == EN "Quiz").
    assert _badge(_render_unit("lesson", lang="pl"))["title"] == "Lekcja"


@pytest.mark.django_db
def test_container_node_keeps_word_badge(client):
    # A chapter renders its word badge, not an L/Q unit badge. Use the full builder
    # page (default EN locale) so the child-scope machinery has real context.
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    ContentNodeFactory(course=course, kind="chapter", parent=None, title="Foundations")
    body = client.get(reverse("courses:manage_builder", kwargs={"slug": "c1"})).content.decode()
    assert 'tree__badge tree__badge--chapter' in body
    assert '>Chapter</span>' in body
    assert not UNIT_BADGE_RE.search(body), "no unit badge expected for a chapter-only tree"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_tree_badge.py -v`
Expected: FAIL — the current template renders `>Unit</span>` (no `L`/`Q`, no per-type modifier, no badge `title`, no title-button `title`). Confirm failures in `test_lesson_badge_is_L_with_localized_tooltip` and `test_title_button_has_hover_title`.

- [ ] **Step 3: Edit the template**

In `templates/courses/manage/_tree_node.html`, replace the badge span (line 5) and add `title` to the title button (lines 6–7). The current block:

```django
  <div class="tree__rowhead">
    <span class="tree__badge tree__badge--{{ node.kind }}">{{ node.get_kind_display }}</span>
    <button class="tree__title" type="button" data-select="{{ node.pk }}"
            data-panel-url="{% url 'courses:manage_node_panel' slug=node.course.slug pk=node.pk %}">{{ node.title }}</button>
```

becomes:

```django
  <div class="tree__rowhead">
    {% if node.kind == "unit" and node.unit_type == "lesson" %}
    <span class="tree__badge tree__badge--unit tree__badge--lesson" title="{{ node.get_unit_type_display }}">L</span>
    {% elif node.kind == "unit" and node.unit_type == "quiz" %}
    <span class="tree__badge tree__badge--unit tree__badge--quiz" title="{{ node.get_unit_type_display }}">Q</span>
    {% else %}
    <span class="tree__badge tree__badge--{{ node.kind }}">{{ node.get_kind_display }}</span>
    {% endif %}
    <button class="tree__title" type="button" data-select="{{ node.pk }}" title="{{ node.title }}"
            data-panel-url="{% url 'courses:manage_node_panel' slug=node.course.slug pk=node.pk %}">{{ node.title }}</button>
```

Note: the `{% else %}` arm reproduces today's markup exactly (`tree__badge--{{ node.kind }}` + `get_kind_display`, no `title`), covering non-units AND any unit whose `unit_type` is empty or unrecognized — so the badge is never blank and never emits a stray `tree__badge--<x>` modifier.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_tree_badge.py -v`
Expected: PASS (all 7 tests). If `test_lesson_tooltip_localizes_to_pl` fails with `"Lesson"` instead of `"Lekcja"`, the PL catalog `.mo` isn't compiled — run `uv run python manage.py compilemessages -l pl` and re-run.

- [ ] **Step 5: Falsify the tests (prove they can go RED), then restore**

For each, make the change, run `uv run pytest tests/test_tree_badge.py -q`, confirm a FAILED, then revert:
- Swap the letters (`lesson` arm emits `Q`) → `test_lesson_badge_is_L_with_localized_tooltip` must fail (pins the mapping, not mere presence).
- Revert the badge to `{{ node.get_kind_display }}` for a unit → badge/colour tests must fail (pins non-fallback).
- Drop `tree__badge--unit` from the lesson arm → `test_unit_badge_keeps_accent_colour_class` must fail (pins the colour hook).

Restore the template to the Step-3 version afterward.

- [ ] **Step 6: Docs + regression sweep**

Grep the help pages for prose that names the tree badge letter/word:

Run: `grep -rniE "unit badge|tree badge|badge.*(unit|jednostka)" docs/help/ || echo "NO BADGE PROSE"`
Expected: `NO BADGE PROSE` (the builder help describes the "+ Lesson"/"+ Quiz" chips, not the tree badge letter). **Only if** real prose is found, update it to the L/Q scheme (EN + `.pl`) and include it in this task's commit. Do not invent new badge prose.

Then confirm no existing manage test asserted on the old `>Unit<` badge text:
Run: `uv run pytest tests/test_manage_builder.py tests/test_manage_node_ops.py -q`
Expected: exit code 0, no `FAILED`. If any assertion on the old badge text breaks, update it to the L/Q scheme.

- [ ] **Step 7: Lint + commit**

Run: `uv run ruff check tests/test_tree_badge.py` and `uv run ruff format --check tests/test_tree_badge.py` (fix with `uv run ruff format tests/test_tree_badge.py` if needed).

```bash
git add templates/courses/manage/_tree_node.html tests/test_tree_badge.py
git commit -m "feat(builder-tree): L/Q unit badge with localized tooltip + title hover"
```

(Include any `docs/help/**` file only if Step 6 actually changed one.)

---

### Task 2: Builder CSS — 2:1 columns, stacked course-panel buttons, title ellipsis

Change the grid ratio, scope a flex-column to the empty/course panel so its buttons stack, and truncate `.tree__title`. Guard the three rules with a CSS-text regression test in the repo's existing `*_styles.py` style.

**Files:**
- Modify: `courses/static/courses/css/builder.css` (line 1 `.builder`; line 19 `.tree__title`; add one rule near the `.builder__panel .panel` block ~line 76)
- Create: `tests/test_builder_styles.py`

**Interfaces:**
- Consumes: nothing from Task 1 (independent). Relies on the DOM facts that `_course_panel.html` is tagged `data-panel-for="course"` and `.tree__title` is a `flex: 1` child of the flex `.tree__rowhead`.
- Produces: no interface for later tasks; Task 3 visually exercises these rules.

- [ ] **Step 1: Write the failing test**

Create `tests/test_builder_styles.py`:

```python
import re
from pathlib import Path

BUILDER_CSS = (
    Path(__file__).resolve().parent.parent
    / "courses"
    / "static"
    / "courses"
    / "css"
    / "builder.css"
)


def _css():
    return BUILDER_CSS.read_text(encoding="utf-8")


def test_builder_columns_are_two_to_one():
    m = re.search(r"\.builder\s*\{[^}]*grid-template-columns:\s*2fr\s+1fr", _css())
    assert m, ".builder must use a 2fr 1fr column ratio"


def test_course_panel_is_flex_column():
    # Scoped to the empty/course state only, so the unit/node panels keep their grids.
    m = re.search(
        r'\.builder__panel\s+\.panel\[data-panel-for="course"\]\s*\{[^}]*'
        r"flex-direction:\s*column",
        _css(),
    )
    assert m, 'course panel must be a flex column (scoped to [data-panel-for="course"])'


def test_tree_title_truncates_with_ellipsis():
    css = _css()
    assert re.search(r"\.tree__title\s*\{[^}]*text-overflow:\s*ellipsis", css), (
        ".tree__title must truncate with an ellipsis"
    )
    assert re.search(r"\.tree__title\s*\{[^}]*min-width:\s*0", css), (
        ".tree__title needs min-width:0 to shrink below content width"
    )
    assert re.search(r"\.tree__title\s*\{[^}]*white-space:\s*nowrap", css), (
        ".tree__title needs white-space:nowrap for single-line truncation"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_builder_styles.py -v`
Expected: all three FAIL (current CSS is `1fr 1fr`, has no course-panel flex rule, and `.tree__title` has no ellipsis).

- [ ] **Step 3: Edit the CSS**

In `courses/static/courses/css/builder.css`:

1. Line 1 — change the grid ratio:
```css
.builder { display: grid; grid-template-columns: 2fr 1fr; gap: var(--space-4); position: relative; }
```

2. Line 19 — append the truncation rules to `.tree__title`:
```css
.tree__title { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; background: none; border: none; cursor: pointer; text-align: left; color: var(--text-primary); padding: 0; }
```

3. Add this rule directly after the existing `.builder__panel .form--inline` / panel block (near line 82, anywhere among the `.builder__panel` rules):
```css
/* Empty/course panel only (unique data-panel-for="course"): stack its title, meta,
   and the four ghost buttons one-per-line in the narrowed 1/3 column. Scoped so the
   unit/node panels' grids (.unit-summary, .element-list) keep full-width layout. */
.builder__panel .panel[data-panel-for="course"] { display: flex; flex-direction: column; align-items: flex-start; }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_builder_styles.py -v`
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/css/builder.css tests/test_builder_styles.py
git commit -m "feat(builder-tree): 2:1 columns, stacked course-panel buttons, title ellipsis"
```

---

### Task 3: e2e visual verification (real UI, light + dark)

Drive the real builder page in a browser and confirm the layout end-to-end: `L`/`Q` badges render, the tree column is ~2× the panel, a long title truncates (does not wrap), and capture light+dark screenshots for human review. Marked `e2e` (excluded from the default run). Self-contained per the repo's e2e convention (its own PA/login helpers).

**Files:**
- Create: `tests/test_e2e_builder_tree_layout.py`

**Interfaces:**
- Consumes: Playwright `page` + `live_server` fixtures; `tests.factories.TEST_PASSWORD` / `make_verified_user`; the `PLATFORM_ADMIN` role seed (mirrors `tests/test_e2e_builder.py`). The rendered artifacts from Tasks 1 & 2.
- Produces: screenshot PNGs under the pytest tmp path (surfaced in the run log) — no code interface.

- [ ] **Step 1: Write the e2e test**

Create `tests/test_e2e_builder_tree_layout.py`:

```python
"""Playwright e2e for the builder-tree layout refresh: L/Q unit badges, the 2:1
column ratio, and single-line title truncation. Self-contained (own PA/login
helpers, per the repo e2e convention). Marked e2e — run foreground only."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

LONG_TITLE = "A deliberately very long unit title that must truncate on one row"


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_builder_tree_layout(page, live_server, tmp_path):
    from courses.models import ContentNode
    from courses.models import Course

    _make_pa_user("pa")
    course = Course.objects.create(slug="layout-demo", title="Layout Demo")
    ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", title=LONG_TITLE
    )
    ContentNode.objects.create(
        course=course, kind="unit", unit_type="quiz", title="Quick check"
    )
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}/manage/courses/layout-demo/build/")

    # Badges: exactly the L and Q letters render in the tree.
    badges = page.locator(".tree__badge--unit")
    texts = sorted(badges.all_inner_texts())
    assert texts == ["L", "Q"], f"expected L and Q unit badges, got {texts}"

    # Column ratio ~2:1 (tree vs panel).
    tree_box = page.locator(".builder__tree").bounding_box()
    panel_box = page.locator(".builder__panel").bounding_box()
    ratio = tree_box["width"] / panel_box["width"]
    assert 1.7 < ratio < 2.4, f"tree:panel width ratio {ratio:.2f} not ~2:1"

    # Long title truncates on one line: overflowing content, single-line height.
    title = page.locator(".tree__title", has_text="deliberately very long").first
    metrics = title.evaluate(
        "el => ({sw: el.scrollWidth, cw: el.clientWidth, h: el.clientHeight,"
        " lh: parseFloat(getComputedStyle(el).lineHeight) || el.clientHeight})"
    )
    assert metrics["sw"] > metrics["cw"], "long title is not overflowing (not truncated)"
    assert metrics["h"] <= metrics["lh"] * 1.6, "title wrapped to a second line"

    # Capture light + dark for human review.
    page.emulate_media(color_scheme="light")
    page.screenshot(path=str(tmp_path / "builder_tree_light.png"), full_page=True)
    page.emulate_media(color_scheme="dark")
    page.screenshot(path=str(tmp_path / "builder_tree_dark.png"), full_page=True)
    print(f"SCREENSHOTS: {tmp_path}")
```

Note on the build URL: confirm the real path with
`uv run python -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.test'); django.setup(); from django.urls import reverse; print(reverse('courses:manage_builder', kwargs={'slug':'x'}))"`
and substitute it into `page.goto(...)` if it differs from `/manage/courses/<slug>/build/`.

- [ ] **Step 2: Run the e2e test FOREGROUND**

Run: `uv run pytest tests/test_e2e_builder_tree_layout.py -v -s`
(FOREGROUND only — never a broad `-m e2e` background run; that spawns runaway browsers.)
Expected: PASS. The `-s` surfaces the `SCREENSHOTS: <path>` line.

- [ ] **Step 3: Review the screenshots**

Open `builder_tree_light.png` and `builder_tree_dark.png` from the printed path. Self-critique against the spec's visual checklist: (a) tree column clearly wider than the panel (~2:1); (b) on the fresh/empty course panel the four ghost buttons stack one-per-line; (c) the long unit title shows an ellipsis on a single row; (d) the `L`/`Q` badges are legible and accent-coloured in both themes. If (d)/(b) look wrong, fix the template/CSS from Tasks 1–2 before committing.

- [ ] **Step 4: Lint + commit**

Run: `uv run ruff check tests/test_e2e_builder_tree_layout.py` and `uv run ruff format --check tests/test_e2e_builder_tree_layout.py`.

```bash
git add tests/test_e2e_builder_tree_layout.py
git commit -m "test(builder-tree): e2e visual check — L/Q badges, 2:1 columns, title ellipsis"
```

---

## Self-Review

**Spec coverage:**
- Edit #1 (L/Q badge + tooltip + defensive fallback + colour class + per-type modifier) → Task 1 (template + `test_tree_badge.py`). ✓
- Edit #2 (2fr 1fr grid; scoped course-panel flex-column) → Task 2 (`builder.css` + `test_builder_styles.py`) + Task 3 visual. ✓
- Edit #3 (`.tree__title` ellipsis + title hover attr) → Task 1 (title attr) + Task 2 (CSS) + Task 3 visual (c). ✓
- Testing: template render tests scoped to the badge span, non-colliding fixture titles, achievable falsifications, PL via `translation.override` (compiled-catalog note), chapter word badge under EN → Task 1. Visual light+dark incl. the unit panel state → Task 3. Regression sweep of manage tests → Task 1 Step 6. ✓
- Docs: conditional no-op grep → Task 1 Step 6. ✓
- Out-of-scope move picker → Global Constraints (untouched). ✓

**Placeholder scan:** none — every step has concrete code/commands.

**Type/name consistency:** `unit_type` string literals `"lesson"`/`"quiz"` match the template `{% if %}` and the tests; badge classes `tree__badge--unit`/`--lesson`/`--quiz` are identical across template, tests, and CSS; the `data-panel-for="course"` selector matches `_course_panel.html`.

**Note on Task 3 flakiness:** if the e2e proves environmentally flaky (browser/live_server), Tasks 1–2's automated tests already gate all substantive logic; treat a flaky e2e per the repo's "flaky tests → separate PR" convention rather than weakening the feature.
