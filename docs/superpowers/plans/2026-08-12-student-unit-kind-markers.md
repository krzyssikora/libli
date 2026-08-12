# Student-facing Unit Kind Markers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show students which units are quizzes and which are non-obligatory ("Additional"), on the course outline, the contents rail, the mobile drawer and the unit page.

**Architecture:** One pure function `unit_marker(node)` in `courses/rollups.py` collapses `unit_type` + `obligatory` into a three-state axis (`quiz` / `additional` / `""`), exposed to templates as a filter. Two shared partials render it — a text chip (outline, unit page) and an icon (rail, drawer). No model, migration or query changes: every field is already loaded.

**Tech Stack:** Django templates, `gettext_lazy`, plain CSS (no framework), pytest + BeautifulSoup for render tests, Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-08-12-student-unit-kind-markers-design.md` — read it. This plan
implements it; where they disagree, the spec wins — **with one recorded, reasoned exception**, in
Task 5 Step 7. The spec's Falsification list points the mobile-rule mutant at
`test_e2e_unit_head_layout.py`, but that file's own fixture cannot discriminate (the spec's §Testing
item 4 concedes as much), so the plan re-points it at the new phone unit-page arm. Following the
spec's bullet there would run a mutant that stays green and halt the task under this plan's
"a falsification step must go RED" rule.

## Global Constraints

- **All work happens in this worktree**: `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/student-unit-kind-markers`, branch `pipeline/student-unit-kind-markers`. It has its own `.env` with an isolated `TEST_DATABASE_URL` (database `libli_ukm`) so it cannot collide with the main checkout or the sibling pipeline worktree.
- **Start the test-DB container before any pytest run.** If it is down the suite looks hung for ~4m21s. Verify with `docker ps | grep libli-test-db`.
- **Tooling is not on PATH.** Every command is prefixed `uv run` — `uv run pytest`, `uv run ruff`, `uv run python`.
- **e2e requires `-m e2e`.** `pyproject.toml` sets `addopts = "-q -m 'not e2e'"`, so an e2e run without `-m e2e` silently deselects everything and exits 5.
- **Never `git checkout` a file to remove a mutant** — edit the mutant out by hand. `git checkout` destroys the surrounding work. This has bitten this repo three times.
- **A falsification step must go RED.** If a prescribed mutant leaves the test green, stop and report it — do not proceed. Several declarations in this change are deliberately inert and carry **no** mutant; those are named per task and must not have one invented for them.
- **Marker strings**: `MARKER_QUIZ = "quiz"`, `MARKER_ADDITIONAL = "additional"`, `MARKER_NONE = ""`. Templates hardcode `"quiz"`/`"additional"`; renaming a constant requires a grep of `templates/courses/_unit_kind_*.html`.
- **Student-facing word for non-obligatory is "Additional"**, never "Optional". Polish `msgstr` is `"Dodatkowa"`.
- **`obligatory` defaults to `True`** (`courses/models.py:212`) and `ContentNodeFactory` does not set it. Every fixture that must render a marker has to pass `obligatory=False` or use a quiz unit — otherwise the assertion is vacuous.
- **Run only affected tests per task.** A whole-repo sweep is a branch gate (Task 8), never a task step.
- **Every task ends with a lint pass**, not just Task 1:
  `uv run ruff check --no-cache <files>` and `uv run ruff format --check <files>`.
  `pyproject.toml:36` selects `["E","F","I","UP","B","S"]` with `force-single-line` isort.
- **"Append to `<test file>`" NEVER means "append the imports too."** Every import in an appended
  block is merged into that file's existing top-of-file import section, alphabetised, one name per
  line, and never duplicated. A mid-file import is **E402**; an unsorted one is **I001**; a
  re-import is **F811**. All three fail the gate.
- **i18n has a house convention document**: `docs/development/conventions.md:45-73`. Read it before
  Task 6. It is authoritative over this plan.
- **Do not pass a bare `-q` to pytest**: `pyproject.toml:49` already sets `addopts = "-q -m 'not e2e'"`,
  and a doubled `-q` suppresses the summary line. Use `--verbosity=0` when you need to override.
- **Capture scripts are not auto-collected**: `pyproject.toml:48` sets `python_files = ["test_*.py"]`,
  so any `capture_*.py` runs only when named explicitly on the command line.
- **Every line number in this plan is PRE-CHANGE. Anchor on the SELECTOR, not the number.** Task 2
  inserts rules at `app.css:132`, so Task 3's `:521`/`:544` have already moved by ~14 lines; Task 4's
  own comment insertion at `:789` shifts `:973-980` before the same step warns you not to paste over
  them; Task 5's `:834-835` and `:986` have shifted again. **Re-grep for the selector before every
  edit** — this matters most where the instruction is "do not paste over this region", because there
  following the stale number is what destroys authored source.

---

### Task 1: The marker rule and its template exposure

**Files:**
- Modify: `courses/rollups.py` (add import + constants + two functions between `is_quiz_unit`, which ends at `:171`, and `quiz_units_in_order`, which starts at `:174`)
- Modify: `courses/templatetags/courses_extras.py` (imports + two registrations)
- Test: `tests/test_unit_marker.py` (create)

**Interfaces:**
- Consumes: `ContentNode`, `is_quiz_unit` — both already in `courses/rollups.py`.
- Produces: `courses.rollups.MARKER_NONE | MARKER_QUIZ | MARKER_ADDITIONAL` (str constants); `unit_marker(node) -> str`; `marker_label(marker: str) -> str` (a lazy proxy or `""`). Template filter `unit_marker`, simple tag `marker_label` — both used by every later task.

- [ ] **Step 1: Write the failing test**

Create `tests/test_unit_marker.py`:

```python
"""unit_marker / marker_label: the single student-facing kind rule."""

import pytest
from django.utils import translation

from courses.rollups import MARKER_ADDITIONAL
from courses.rollups import MARKER_NONE
from courses.rollups import MARKER_QUIZ
from courses.rollups import marker_label
from courses.rollups import unit_marker
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory


@pytest.mark.django_db
def test_marker_table():
    """Every branch, including the ones that exist to be SILENT.

    The two quiz rows are a pair on purpose: together they pin that `obligatory`
    is ignored on a quiz, which one row alone cannot.
    """
    course = CourseFactory()
    req = ContentNodeFactory(course=course, unit_type="lesson", obligatory=True)
    add = ContentNodeFactory(course=course, unit_type="lesson", obligatory=False)
    quiz_ob = ContentNodeFactory(course=course, unit_type="quiz", obligatory=True)
    quiz_opt = ContentNodeFactory(course=course, unit_type="quiz", obligatory=False)
    chapter = ContentNodeFactory(course=course, kind="chapter", unit_type=None)
    untyped = ContentNodeFactory(course=course, unit_type=None)

    assert unit_marker(req) == MARKER_NONE
    assert unit_marker(add) == MARKER_ADDITIONAL
    assert unit_marker(quiz_ob) == MARKER_QUIZ
    assert unit_marker(quiz_opt) == MARKER_QUIZ
    assert unit_marker(chapter) == MARKER_NONE
    assert unit_marker(untyped) == MARKER_NONE


def test_marker_is_quiet_for_non_nodes():
    """A partial included without `with node=...` resolves to Django's
    string_if_invalid (default ''). A bare attribute access would raise
    AttributeError and 500 the course outline; fail quiet instead."""
    assert unit_marker("") == MARKER_NONE
    assert unit_marker(None) == MARKER_NONE


@pytest.mark.django_db
def test_labels_under_default_locale():
    """LANGUAGE_CODE is 'en' (config/settings/base.py:142)."""
    course = CourseFactory()
    add = ContentNodeFactory(course=course, unit_type="lesson", obligatory=False)
    quiz = ContentNodeFactory(course=course, unit_type="quiz")
    req = ContentNodeFactory(course=course, unit_type="lesson", obligatory=True)

    assert str(marker_label(unit_marker(add))) == "Additional"
    assert str(marker_label(unit_marker(quiz))) == "Quiz"
    assert str(marker_label(unit_marker(req))) == ""
    assert marker_label("nonsense") == ""


@pytest.mark.xfail(reason="PL msgstr lands in Task 6", strict=True)
@pytest.mark.django_db
def test_label_is_a_lazy_proxy_not_a_frozen_string():
    """Pins the §6 catalog entry end-to-end AND proves gettext_lazy: a plain
    gettext call in a module-level dict would freeze the import-time language."""
    course = CourseFactory()
    add = ContentNodeFactory(course=course, unit_type="lesson", obligatory=False)
    with translation.override("pl"):
        assert str(marker_label(unit_marker(add))) == "Dodatkowa"
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
uv run pytest tests/test_unit_marker.py -v
```

Expected: FAIL — `ImportError: cannot import name 'MARKER_ADDITIONAL' from 'courses.rollups'`.

- [ ] **Step 3: Implement the rule**

In `courses/rollups.py`, add to the import block (it is one name per line):

```python
from django.utils.translation import gettext_lazy
```

Then, between `is_quiz_unit` (`:166-171`) and `quiz_units_in_order` (`:174`):

```python
MARKER_NONE = ""
MARKER_QUIZ = "quiz"
MARKER_ADDITIONAL = "additional"

UNIT_MARKER_LABELS = {
    MARKER_QUIZ: gettext_lazy("Quiz"),
    MARKER_ADDITIONAL: gettext_lazy("Additional"),
}


def unit_marker(node):
    """MARKER_QUIZ | MARKER_ADDITIONAL | MARKER_NONE — the ONE student-facing kind rule.

    MARKER_NONE for a required lesson (the unmarked default), for any non-unit
    node, for a unit whose unit_type is unset, AND for anything that is not a
    node at all. A quiz is never 'additional': is_obligatory_lesson already
    excludes quizzes from required_total, so `obligatory` on a quiz node has no
    student meaning.

    The `additional` branch is written out rather than composed from the two
    existing predicates: is_quiz_unit and is_obligatory_lesson BOTH return False
    for an additional lesson, a non-unit node, and an unset unit_type, so a
    function built only from those two cannot tell the three apart. Do not
    "simplify" it to `not is_obligatory_lesson(node)`.
    """
    # getattr, not node.kind: a template that includes a marker partial without
    # `with node=...` resolves the variable to string_if_invalid (default ''),
    # and a bare attribute access — or handing '' straight to is_quiz_unit —
    # raises AttributeError and 500s the course outline. Fail quiet instead.
    if getattr(node, "kind", None) != ContentNode.Kind.UNIT:
        return MARKER_NONE
    if is_quiz_unit(node):
        return MARKER_QUIZ
    if node.unit_type == ContentNode.UnitType.LESSON and not node.obligatory:
        return MARKER_ADDITIONAL
    return MARKER_NONE


def marker_label(marker):
    """Marker key -> translated word; "" for MARKER_NONE or any unknown key.

    Keyed on the marker, not the node: both partials already hold `m` from their
    own {% with %}, so this avoids deriving the marker a second time.
    """
    return UNIT_MARKER_LABELS.get(marker, "")
```

- [ ] **Step 4: Register the filter and the tag**

In `courses/templatetags/courses_extras.py`, add to the imports:

```python
from courses import rollups
```

and immediately after `register = template.Library()`:

```python
# Registered by passing the function, NOT by decorating a same-named wrapper.
# `from courses.rollups import unit_marker` + `@register.filter def unit_marker(...)`
# rebinds the module-level name and produces unbounded recursion on the first
# render — not an import error, so it passes review and fails in the browser.
register.filter("unit_marker", rollups.unit_marker)
register.simple_tag(rollups.marker_label, name="marker_label")
```

- [ ] **Step 5: Run the tests to make sure they pass**

```bash
uv run pytest tests/test_unit_marker.py -v
```

Expected: **3 passed, 1 xfailed**. The xfail is `test_label_is_a_lazy_proxy_not_a_frozen_string` —
it needs the Polish catalog entry that Task 6 adds. `strict=True` means it will fail loudly if it
starts passing early. **Task 6 removes the marker.**

- [ ] **Step 6: Falsify — three mutants, each must go RED**

Edit each mutant in by hand, run, confirm RED, then edit it back out (never `git checkout`):

| Mutant | Must redden |
| --- | --- |
| `return MARKER_ADDITIONAL` in the `is_quiz_unit` branch | the quiz pair in `test_marker_table` |
| `additional` branch → `if not is_obligatory_lesson(node):` | the **untyped** row. NOT the chapter row — the `getattr` guard returns before that branch is reached, so the chapter row is green under this mutant and is covered by the guard mutant below instead |
| `getattr(node, "kind", None)` → `node.kind` | `test_marker_is_quiet_for_non_nodes` |

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check --no-cache courses/rollups.py courses/templatetags/courses_extras.py tests/test_unit_marker.py
uv run ruff format --check courses/rollups.py courses/templatetags/courses_extras.py tests/test_unit_marker.py
git add courses/rollups.py courses/templatetags/courses_extras.py tests/test_unit_marker.py
git commit -m "feat(courses): unit_marker + marker_label, the student-facing kind rule"
```

---

### Task 2: The three partials and their shared CSS

**Files:**
- Create: `templates/courses/_unit_kind_glyph.html`, `templates/courses/_unit_kind_chip.html`, `templates/courses/_unit_kind_icon.html`
- Modify: `core/static/core/css/app.css` (add beside `.badge`, after line 131)
- Test: `tests/test_unit_marker.py` (append)

**Interfaces:**
- Consumes: the `unit_marker` filter and `marker_label` tag from Task 1.
- Produces: three includes. Chip emits `class="badge unit-kind-chip unit-kind-chip--<marker>"`; icon emits a wrapper `class="unit-kind unit-kind--<marker>"` containing `<svg class="icon">` + `<span class="visually-hidden unit-kind__label">`. Every call site passes `with node=<node> only`.

- [ ] **Step 1: Write the failing test**

Append the test functions below to `tests/test_unit_marker.py`. **Add
`from django.template.loader import render_to_string` to the file's existing top-of-file import
block** (alphabetised, one per line) — not here. `MARKER_QUIZ` is already imported by Task 1; do not
re-import it (F811).

```python
@pytest.mark.django_db
def test_chip_partial_renders_only_when_marked():
    course = CourseFactory()
    quiz = ContentNodeFactory(course=course, unit_type="quiz")
    req = ContentNodeFactory(course=course, unit_type="lesson", obligatory=True)

    marked = render_to_string("courses/_unit_kind_chip.html", {"node": quiz})
    assert "unit-kind-chip" in marked
    assert f"unit-kind-chip--{MARKER_QUIZ}" in marked
    assert "Quiz" in marked

    assert render_to_string("courses/_unit_kind_chip.html", {"node": req}).strip() == ""


@pytest.mark.django_db
def test_icon_partial_carries_a_hidden_label_and_a_title():
    course = CourseFactory()
    add = ContentNodeFactory(course=course, unit_type="lesson", obligatory=False)
    html = render_to_string("courses/_unit_kind_icon.html", {"node": add})
    assert 'class="unit-kind unit-kind--additional"' in html
    assert 'title="Additional"' in html
    assert 'lang="en"' in html                   # UI locale, not the course's
    assert 'aria-hidden="true"' in html          # on the <svg>
    assert "visually-hidden unit-kind__label" in html
    assert "Additional</span>" in html


def test_glyph_partial_emits_nothing_for_an_empty_marker():
    """The three-way {% elif %} pin. With an {% else %} branch this would emit
    the *additional* '+' glyph. No surface test can reach it, because the chip
    and icon partials guard the include behind {% if m %}."""
    assert "<svg" not in render_to_string("courses/_unit_kind_glyph.html", {"m": ""})
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
uv run pytest tests/test_unit_marker.py -k "partial or glyph" -v
```

Expected: FAIL — `TemplateDoesNotExist`. `-k` collects the chip test first, so the first error names
`courses/_unit_kind_chip.html`; all three templates are missing at this point.

- [ ] **Step 3: Create the glyph partial**

`templates/courses/_unit_kind_glyph.html`:

```html
{% comment %}Glyph geometry, authored ONCE, keyed on a bare marker string `m`.

Three-way, NOT {% if %}/{% else %}: the "renders nothing for MARKER_NONE"
guarantee belongs to the chip and icon partials, which guard their body behind
{% if m %}. This partial has no such guard, so an {% else %} branch would emit
the *additional* '+' glyph for m="" or for a literal typo'd in a future call
site — and a missed constant rename lands in exactly that branch.{% endcomment %}
{% if m == "quiz" %}
  <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <circle cx="12" cy="12" r="9"/>
    <path d="M9.4 9.3a2.7 2.7 0 0 1 5.2.9c0 1.8-2.6 2.4-2.6 2.4"/>
    <circle cx="12" cy="16.6" r=".95" fill="currentColor" stroke="none"/>
  </svg>
{% elif m == "additional" %}
  <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <circle cx="12" cy="12" r="9"/>
    <path d="M12 8.2v7.6M8.2 12h7.6"/>
  </svg>
{% endif %}
```

- [ ] **Step 4: Create the chip and icon partials**

`templates/courses/_unit_kind_chip.html`:

```html
{% load i18n courses_extras %}{% get_current_language as LANGUAGE_CODE %}{% with m=node|unit_marker %}{% if m %}<span
  class="badge unit-kind-chip unit-kind-chip--{{ m }}"
  lang="{{ LANGUAGE_CODE }}">{% marker_label m %}</span>{% endif %}{% endwith %}
```

`templates/courses/_unit_kind_icon.html`:

```html
{% load i18n courses_extras %}{% get_current_language as LANGUAGE_CODE %}{% with m=node|unit_marker %}{% if m %}<span
  class="unit-kind unit-kind--{{ m }}" lang="{{ LANGUAGE_CODE }}" title="{% marker_label m %}">
  {% include "courses/_unit_kind_glyph.html" with m=m only %}
  <span class="visually-hidden unit-kind__label">{% marker_label m %}</span>
</span>{% endif %}{% endwith %}
```

`lang=` is required on both: every call site sits inside a subtree switched to the *course* language, but these are UI strings in the *user's* locale. `LANGUAGE_CODE` must come from `{% get_current_language %}` — the i18n context processor is not enabled, and `only` on every include blocks inheritance anyway.

- [ ] **Step 5: Add the shared CSS**

In `core/static/core/css/app.css`, immediately after the `.badge--open` block (line 131):

```css
/* Unit kind markers (spec 2026-08-12). The flex item of a rail row is the
   .unit-kind WRAPPER, not the <svg class="icon"> inside it — .icon { flex: none }
   governs .icon only when .icon is itself a flex item. inline-flex + gap are what
   this rule genuinely buys: they space glyph from word where the word is visible
   (the drawer). Deleting the whole rule does NOT narrow the glyph — the wrapper's
   automatic minimum is its 1em min-content either way — so there is no
   glyph-width mutant for it.
   .unit-kind-chip's declarations are inert forward-defence for a future
   multi-word translation: both shipping labels are single unbreakable words, so
   a flex: 0 1 auto chip's shrink target is a min violation and it is frozen at
   its full width regardless. Neither carries a mutant. */
.unit-kind { display: inline-flex; align-items: center; gap: var(--space-1); flex: none; }
.unit-kind-chip { flex: none; white-space: nowrap; }
```

- [ ] **Step 6: Run the tests to make sure they pass**

```bash
uv run pytest tests/test_unit_marker.py -v
```

Expected: PASS (all except the xfail from Task 1).

- [ ] **Step 7: Falsify — one mutant**

Change `{% elif m == "additional" %}` to `{% else %}` in the glyph partial. `test_glyph_partial_emits_nothing_for_an_empty_marker` must go RED. Edit it back.

Deliberately **no** mutant for `.unit-kind`'s `flex: none` (its automatic minimum is the 1em glyph
either way, so a glyph-width test is green on both builds), nor for `.unit-kind-chip`'s `flex: none`
or `white-space: nowrap` (both inert for single-word labels). Do not invent one for those.

`.unit-kind`'s **`gap`** is a different matter — it IS falsifiable, and Task 7 owns that mutant.

- [ ] **Step 8: Commit**

```bash
uv run ruff check --no-cache tests/test_unit_marker.py
uv run ruff format --check tests/test_unit_marker.py
git add templates/courses/_unit_kind_glyph.html templates/courses/_unit_kind_chip.html templates/courses/_unit_kind_icon.html core/static/core/css/app.css tests/test_unit_marker.py
git commit -m "feat(courses): unit kind marker partials + shared CSS"
```

---

### Task 3: Outline page

**Files:**
- Modify: `templates/courses/_outline_node.html` (inside the `<a class="outline-unit">`, after `.outline-unit__title`)
- Modify: `core/static/core/css/app.css:521` and `:544` (edit both rules in place)
- Test: `tests/test_unit_marker.py` (append)

**Interfaces:**
- Consumes: `_unit_kind_chip.html` from Task 2.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

Append the helper and tests below. **Merge these into the file's existing top-of-file import block**
(alphabetised, one per line), not into the body: `from bs4 import BeautifulSoup`,
`from django.urls import reverse`, `from tests.factories import EnrollmentFactory`,
`from tests.factories import TEST_PASSWORD`, `from tests.factories import UnitProgressFactory`,
`from tests.factories import make_verified_user`.

```python
def _outline_soup(client, course):
    resp = client.get(reverse("courses:course_outline", kwargs={"slug": course.slug}))
    assert resp.status_code == 200
    return BeautifulSoup(resp.content.decode(), "html.parser")


@pytest.mark.django_db
def test_outline_marks_quiz_and_additional_but_not_required(client):
    course = CourseFactory()
    student = make_verified_user(
        username="s_outline", email="s_outline@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=student, course=course)
    req = ContentNodeFactory(course=course, unit_type="lesson", obligatory=True,
                             title="Required one")
    add = ContentNodeFactory(course=course, unit_type="lesson", obligatory=False,
                             title="Extra practice")
    quiz = ContentNodeFactory(course=course, unit_type="quiz", title="End test")
    client.force_login(student)
    soup = _outline_soup(client, course)

    def row(node):
        return soup.select_one(f'li#node-{node.pk} a.outline-unit')

    # present for additional + quiz, and INSIDE the anchor (not a detached sibling)
    assert row(add).select_one(".unit-kind-chip").get_text(strip=True) == "Additional"
    assert row(quiz).select_one(".unit-kind-chip").get_text(strip=True) == "Quiz"
    assert f"unit-kind-chip--{MARKER_QUIZ}" in row(quiz).select_one(".unit-kind-chip")["class"]

    # ABSENT for a required lesson — the load-bearing assertion. Without it every
    # mutant that marks every row stays green.
    assert row(req).select_one(".unit-kind-chip") is None


@pytest.mark.django_db
def test_outline_chip_follows_the_title_and_precedes_the_tick(client):
    """§4 argues at length for right-gutter placement; without a position
    assertion, moving the chip before the title keeps every other check green."""
    course = CourseFactory()
    student = make_verified_user(
        username="s_pos", email="s_pos@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=student, course=course)
    quiz = ContentNodeFactory(course=course, unit_type="quiz", title="Ordered")
    # COMPLETED, so .badge--done actually renders — otherwise the "precedes the
    # tick" half of this test asserts nothing and moving the chip after the tick
    # stays green.
    UnitProgressFactory(student=student, unit=quiz, completed=True)
    client.force_login(student)
    anchor = _outline_soup(client, course).select_one(f'li#node-{quiz.pk} a.outline-unit')

    classes = [" ".join(c.get("class", [])) for c in anchor.find_all(recursive=False)]
    title_i = next(i for i, c in enumerate(classes) if "outline-unit__title" in c)
    chip_i = next(i for i, c in enumerate(classes) if "unit-kind-chip" in c)
    done_i = next(i for i, c in enumerate(classes) if "badge--done" in c)
    assert chip_i == title_i + 1, f"chip must directly follow the title, got {classes}"
    assert chip_i < done_i, f"chip must precede the tick, got {classes}"


@pytest.mark.django_db
def test_outline_chip_is_tagged_with_the_ui_language_not_the_course_language(client):
    """The chip sits inside lang="{{ course.language }}"; its word is a UI string."""
    course = CourseFactory(language="pl")     # deliberately NOT the UI locale
    student = make_verified_user(
        username="s_lang", email="s_lang@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=student, course=course)
    quiz = ContentNodeFactory(course=course, unit_type="quiz", title="Lang")
    client.force_login(student)
    chip = _outline_soup(client, course).select_one(".unit-kind-chip")
    assert chip["lang"] == "en"
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
uv run pytest tests/test_unit_marker.py -k outline -v
```

Expected: FAIL — `AttributeError: 'NoneType' object has no attribute 'get_text'` (no `.unit-kind-chip`).

- [ ] **Step 3: Wire the chip into the outline row**

In `templates/courses/_outline_node.html`, inside the `<a class="outline-unit">`, between the title `<span>` and the `✓` badge:

```html
      <span class="outline-unit__title" data-math-title>{{ item.node.title }}</span>
      {% include "courses/_unit_kind_chip.html" with node=item.node only %}
      {% if item.completed %}<span class="badge badge--done" aria-label="{% trans 'Completed' %}">✓</span>{% endif %}
```

`only` is required: this app already has a `"node"` context key elsewhere (`courses/views.py:782`), and without `only` a future context key would silently mark the wrong node.

- [ ] **Step 4: Edit the two CSS rules in place**

`core/static/core/css/app.css:521`:

```css
.outline-unit__title { flex: 1; min-width: 0; overflow-wrap: anywhere; }
```

`core/static/core/css/app.css:544`:

```css
.outline-node--unit > .outline-unit { flex: 1 1 auto; min-width: 0; }
```

Place the comment block below **above the `:521` rule only**, and put a one-line cross-reference
above `:544` (`/* min-width: 0 here for the same reason as .outline-unit__title — see :521. */`).
The two rules are ~23 lines apart with unrelated rules between them, so one block cannot sit above
both:

```css
/* The chip can add ~90px to a 390px row. `flex: 1` is `1 1 0%` with no
   min-width: 0, so the title's automatic minimum is its min-content and it
   cannot shrink below its longest word; the anchor has the same exposure one
   level up. `anywhere` (not `break-word`) for house consistency with
   courses.css:940 — with min-width: 0 co-applied the two are indistinguishable
   and no test can separate them, so do NOT write an anywhere→break-word mutant.
   Both min-width: 0 declarations are inert forward-defence against unbreakable
   atoms and carry no mutant (see the plan's Task 3 falsification note). */
```

- [ ] **Step 5: Run the tests to make sure they pass**

```bash
uv run pytest tests/test_unit_marker.py -v
```

Expected: PASS, plus the Task 1 xfail (`test_label_is_a_lazy_proxy_not_a_frozen_string`), which
stays until Task 6.

- [ ] **Step 6: Falsify — two mutants**

| Mutant | Must redden |
| --- | --- |
| Move the `{% include %}` above the title `<span>` | `test_outline_chip_follows_the_title_and_precedes_the_tick` |
| Drop `lang="{{ LANGUAGE_CODE }}"` from `_unit_kind_chip.html` | `test_outline_chip_is_tagged_with_the_ui_language_not_the_course_language` |

**No mutants** for either `min-width: 0` or for `anywhere`→`break-word` — the first pair is inert with `anywhere` present, and the second is pixel-identical on every build. The removal of `overflow-wrap` entirely is covered by the e2e in Task 7.

- [ ] **Step 7: Commit**

```bash
uv run ruff check --no-cache tests/test_unit_marker.py
uv run ruff format --check tests/test_unit_marker.py
git add templates/courses/_outline_node.html core/static/core/css/app.css tests/test_unit_marker.py
git commit -m "feat(courses): mark quizzes and additional units on the course outline"
```

---

### Task 4: Contents rail and mobile drawer

**Files:**
- Modify: `templates/courses/_unit_tree_node.html` (last child of `.unit-tree__unit`)
- Modify: `courses/static/courses/css/courses.css:789` (edit in place), and add two rules inside the `@media (max-width: 640px)` block beside `:977`
- Modify: `courses/static/courses/css/courses.css:2310-2350` (the maths-audit comment)
- Modify: `tests/capture_title_math_screenshots.py` (the `btns` selector ~:483, and the seed)
- Test: `tests/test_unit_nav_render.py` (append)

**Interfaces:**
- Consumes: `_unit_kind_icon.html` from Task 2.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

Append the test below to `tests/test_unit_nav_render.py`. **Merge
`from courses.rollups import MARKER_ADDITIONAL` into that file's existing top-of-file import block**
(it already imports `HIDDEN_PATH_SEP`, `build_outline` and others from `courses.rollups`), not here.

```python
@pytest.mark.django_db
def test_rail_marks_quiz_and_additional_as_the_last_child(client):
    """The icon TRAILS the label. The ✓ already leads (courses.css:788 resets
    .badge--done's margin-left:auto for exactly that), so a second leading glyph
    would make every completed additional unit begin with two marks.

    Scoped to [data-unit-tree-list]: _unit_shell.html renders the whole tree
    TWICE per unit page (rail + drawer), so an unscoped select_one silently
    tests only the rail and a `len(...) == 1` assertion fails on a CORRECT build.
    """
    # language="pl" deliberately: CourseFactory defaults to "en", which would make
    # the lang assertion below pass whether the partial emits LANGUAGE_CODE or
    # simply inherits course.language.
    course = CourseFactory(language="pl")
    student = _make_student("s_rail_kind")
    EnrollmentFactory(student=student, course=course)
    req = ContentNodeFactory(course=course, unit_type="lesson", obligatory=True,
                             title="Required")
    add = ContentNodeFactory(course=course, unit_type="lesson", obligatory=False,
                             title="Additional one")
    client.force_login(student)
    resp = client.get(reverse("courses:lesson_unit",
                              kwargs={"slug": course.slug, "node_pk": req.pk}))
    soup = BeautifulSoup(resp.content.decode(), "html.parser")
    rail = soup.select_one("[data-unit-tree-list]")

    def row(node):
        return rail.select_one(f'a.unit-tree__unit[href$="/{node.pk}/"]')

    marked = row(add)
    kind = marked.select_one(".unit-kind")
    assert kind is not None
    assert "Additional" in kind.get_text()            # substring, not full-name equality:
    # the ✓ leads in the rail and trails in the outline, so the two orders differ.
    assert f"unit-kind--{MARKER_ADDITIONAL}" in kind["class"]   # modifier vs the constant
    assert kind["lang"] == "en"                       # UI locale inside lang="{{ course.language }}"
    assert marked.find_all(recursive=False)[-1] is kind, "the icon must be the LAST child"

    assert row(req).select_one(".unit-kind") is None  # required stays unmarked
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
uv run pytest tests/test_unit_nav_render.py -k rail_marks -v
```

Expected: FAIL — `assert None is not None`.

- [ ] **Step 3: Wire the icon into the rail row**

In `templates/courses/_unit_tree_node.html`, as the last child of the `<a class="unit-tree__unit">`, after the label `<span>`:

```html
      <span class="unit-tree__label" title="{{ item.node.title|strip_math_delimiters }}" data-math-title>{{ item.node.title }}</span>
      {% include "courses/_unit_kind_icon.html" with node=item.node only %}
    </a>
```

- [ ] **Step 4: Edit `.unit-tree__label` in place and add the drawer rules**

`courses/static/courses/css/courses.css:789` — add `flex: 1 1 auto` to the existing rule:

```css
.unit-tree__label { flex: 1 1 auto; min-width: 0; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
```

Add above it:

```css
/* flex-grow makes the trailing kind marker land in the same right-hand gutter
   .unit-tree__count occupies on group rows (which right-align only because
   .unit-tree__grouptitle is flex: 1, :736). Without it a short title does not
   fill the row and the marker column is ragged.
   `1 1 auto`, not `1 1 0`: basis auto is the minimal edit, and since this label
   is the only flexible item on the row (.unit-tree__check and .unit-kind are
   both flex: none) the two bases resolve to the same used width anyway — no
   test distinguishes them. */
```

Inside the existing `@media (max-width: 640px)` block: **extend the declaration list of the
`.unit-drawer__list .unit-tree__label` rule at `:977-978` in place** (do not add a second rule —
`tests/test_unit_tree_long_titles.py` regex-matches that rule's body), then **append** the new
`.unit-kind__label` rule after the existing `.unit-drawer__list .unit-tree__unit` rule at `:979-980`.

Do not paste over the region: `:973-976` carries the authored "Touch has no hover" comment and
`:979-980` carries `align-items: flex-start`, which is load-bearing for Task 7's
"one flex line" drawer row assertion. Both must survive.

```css
  .unit-drawer__list .unit-tree__label {
    white-space: normal; overflow: visible; text-overflow: clip;
    overflow-wrap: anywhere; }
  /* Touch has no hover, so title= yields nothing in the drawer — show the word
     on the row. All SIX .visually-hidden declarations must be reset
     (app.css:1217-1224): resetting only `position` leaves a 1px×1px clipped
     span, the drawer shows a bare glyph, and every render test stays green.
     Do NOT add `.unit-drawer__list .unit-kind { flex: 0 1 auto; min-width: 0 }`:
     the label's base size is the title's max-content, so the row runs a large
     deficit and a shrinkable marker would be cut below its min-content with the
     min violation suppressed, painting its word outside its own box. */
  .unit-drawer__list .unit-kind__label {
    position: static; width: auto; height: auto;
    overflow: visible; clip: auto; white-space: normal; }
```

- [ ] **Step 5: Refresh the maths-audit comment and its executable half**

In `courses/static/courses/css/courses.css`, in the block at `:2310-2350`: add `.unit-kind` to the audited sibling list, correct the drawer column claim (it says `~98px`, which is the **rail's** figure per `:730`). Do not
write a *derived* figure: the spec says to record the **measured** residual, and Task 7's phone
drawer arm already opens the drawer at 390×780 — have it report `.unit-tree__label`'s rendered width
on a marked row and write **that** number in Task 8. (The arithmetic says ~325px bare, ~230px after
the marker; treat it as the expected order of magnitude, not the value to commit.)

**The comment's line references must be refreshed too — but NOT here.** The table below is
**pre-change**, and this very task inserts ~9 lines above `:789` while Task 5 inserts ~14 more at
`:836`, so writing these values into the comment now produces a freshly-stale citation block — the
exact defect the refresh exists to remove. **Do the refresh in Task 8 Step 2b**, re-deriving every
number with `grep -n` after all CSS insertions have landed. The table records which references are
wrong *today*, not what to write:

| Cited | Actual (pre-change — re-derive in Task 8) |
| --- | --- |
| `.unit-tree__label (:755)` | 789 |
| `.unit-tree__grouptitle (:702-704)` | 736-738 |
| `courses.css:943` | 977 |
| `.unit-foot__navtitle (:778)` | 812 |
| `.unit-crumbs__label (:848)` | 882 |
| `courses.css:903-907` | 939-941 |

In `tests/capture_title_math_screenshots.py`: add `[data-unit-drawer] .unit-drawer__list .unit-kind` to the `btns` selector list (~:483) — the
full scoped form the spec names; a bare `.unit-kind` would also match the rail tree
**and fix the seed**, because the selector edit alone measures nothing — all four maths-title units
are default-obligatory lessons (no marker), and the one quiz (`quiz_b`, `:186`) sits under `part_b`
whose `<details>` is closed on the drawer arm's page. Set `lesson_display` (the unit the drawer arm
navigates to, `:464`) to `obligatory=False` so it emits a marker in the open group, and add a guard
that `btns` is non-empty.

**That guard must `assert`, and the `page.evaluate` must be changed to make one possible.** `btns` is
a `const` local inside the `evaluate` at `~:478-503`, which currently returns a bare boolean — there
is no Python-side value to assert on. Change it to return a shape, e.g.
`{overlap, kx: kx.length, btns: btns.length}`, and on the Python side assert `result["btns"] > 0`
**and** `result["kx"] > 0` before recording the measurement. The existing `overlap` result is only
pushed onto `measurements` (~:490-505) — it asserts nothing — so a silently-empty `btns` reads as
success. Also
note `tests/helpers_title_math.py` hardcodes `obligatory=True` at `:72`, `:81`, `:90` and `:133`;
any maths-title fixture that must render a marker has to bypass or parameterise those.

- [ ] **Step 6: Run the affected tests**

```bash
uv run pytest tests/test_unit_nav_render.py tests/test_unit_tree_long_titles.py tests/test_unit_marker.py -v
# The capture script is NOT auto-collected (python_files = ["test_*.py"]), so name it explicitly:
uv run pytest tests/capture_title_math_screenshots.py -m e2e
uv run ruff check --no-cache tests/test_unit_nav_render.py tests/capture_title_math_screenshots.py
uv run ruff format --check tests/test_unit_nav_render.py tests/capture_title_math_screenshots.py
```

Expected: PASS. `test_unit_tree_long_titles.py::test_drawer_lets_unit_labels_wrap` is a **source-level regex pin** on the `:977` rule — it stays green only because the rule was extended in place.

- [ ] **Step 7: Falsify — three mutants**

| Mutant | Must redden |
| --- | --- |
| Move the `{% include %}` before `.unit-tree__label` | the last-child assertion |
| Render the icon for a required lesson (drop `{% if m %}` in `_unit_kind_icon.html`) | the `row(req)` absence assertion |
| Drop `lang="{{ LANGUAGE_CODE }}"` from `_unit_kind_icon.html` | the rail test's `lang == "en"` assertion |

The `.unit-tree__label` flex change, the un-hide rule and the drawer `overflow-wrap` are all covered by e2e mutants in Task 7 — not here. The drawer `overflow-wrap: anywhere` carries **no** mutant at all: at a ~230px column a token would need 28+ characters to overflow.

- [ ] **Step 8: Commit**

```bash
git add templates/courses/_unit_tree_node.html courses/static/courses/css/courses.css tests/capture_title_math_screenshots.py tests/test_unit_nav_render.py
git commit -m "feat(courses): mark unit kinds in the contents rail and mobile drawer"
```

---

### Task 5: Unit page, and the two existing cap tests it defuses

**Files:**
- Modify: `templates/courses/_lesson_article.html`, `templates/courses/_quiz_article.html`
- Modify: `courses/static/courses/css/courses.css` (two rules after `:834-835`; one inside the `@media` block beside `:986`)
- Modify: `tests/test_e2e_uniform_block_width.py`, `tests/test_e2e_unit_nav.py`, `tests/test_quiz_previewer_render.py`
- Test: `tests/test_unit_marker.py` (append)

**Interfaces:**
- Consumes: `_unit_kind_chip.html` from Task 2.
- Produces: `.lesson-unit__heading` — the wrapper the Task 7 e2e measures.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_unit_marker.py`:

```python
@pytest.mark.django_db
@pytest.mark.parametrize("unit_type,url_name,word,marker", [
    ("lesson", "courses:lesson_unit", "Additional", MARKER_ADDITIONAL),
    ("quiz", "courses:quiz_unit", "Quiz", MARKER_QUIZ),
])
def test_unit_page_chip_is_a_sibling_of_the_h1(client, unit_type, url_name, word, marker):
    """The chip must NEVER be inside <h1 data-math-title>: math.js typesets that
    element's contents, so a chip in there would enter the maths-title scan."""
    course = CourseFactory(language="pl")   # NOT the UI locale — see the lang assertion
    student = make_verified_user(
        username=f"s_up_{unit_type}", email=f"s_up_{unit_type}@t.example.com",
        password=TEST_PASSWORD,
    )
    EnrollmentFactory(student=student, course=course)
    kw = {"unit_type": unit_type, "title": "Marked unit"}
    if unit_type == "lesson":
        kw["obligatory"] = False
    unit = ContentNodeFactory(course=course, **kw)
    client.force_login(student)
    resp = client.get(reverse(url_name, kwargs={"slug": course.slug, "node_pk": unit.pk}))
    soup = BeautifulSoup(resp.content.decode(), "html.parser")

    group = soup.select_one(".lesson-unit__heading")
    assert group is not None, "both article templates gain the heading group"
    chip = group.select_one(".unit-kind-chip")
    assert chip is not None and chip.get_text(strip=True) == word
    assert f"unit-kind-chip--{marker}" in chip["class"]   # modifier vs the constant
    assert chip["lang"] == "en"                           # UI locale, not course.language
    assert group.select_one("h1.lesson-unit__title").select_one(".unit-kind-chip") is None


@pytest.mark.django_db
def test_unit_page_leaves_a_required_lesson_unmarked(client):
    """The absence half. Without it a mutant that marks every unit is caught on
    the unit page only indirectly, via Task 2's partial-level test."""
    course = CourseFactory()
    student = make_verified_user(
        username="s_up_req", email="s_up_req@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=student, course=course)
    unit = ContentNodeFactory(course=course, unit_type="lesson", obligatory=True,
                              title="Required unit")
    client.force_login(student)
    resp = client.get(reverse("courses:lesson_unit",
                              kwargs={"slug": course.slug, "node_pk": unit.pk}))
    soup = BeautifulSoup(resp.content.decode(), "html.parser")
    assert soup.select_one(".lesson-unit__heading .unit-kind-chip") is None
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
uv run pytest tests/test_unit_marker.py -k unit_page -v
```

Expected: FAIL — `assert None is not None` ("both article templates gain the heading group").

- [ ] **Step 3: Add the heading group to both article templates**

In `templates/courses/_lesson_article.html`, replace the bare `<h1>` inside `.lesson-unit__head`:

```html
  <div class="lesson-unit__head">
    <div class="lesson-unit__heading">
      <h1 class="lesson-unit__title" data-math-title>{{ unit.title }}</h1>
      {% include "courses/_unit_kind_chip.html" with node=unit only %}
    </div>
    {% comment %}Completion is auto-tracked FOR ENROLLED STUDENTS ONLY: ...unchanged...
```

**The closing `</div>` is load-bearing and easy to miss.** In `_lesson_article.html` the `<h1>` at
`:7` is followed by a `{% comment %}` block (`:8-15`) and `.unit-done` (`:16-27`); the anchor line
above shows where the group closes. Leave it open and `.unit-done` / `.lesson-unit__reset` nest
*inside* the heading group — which the new render test would still pass.

In `templates/courses/_quiz_article.html`, wrap the currently bare `<h1>` — the quiz template has no head row today. **The `{% if previewing %}` `<aside data-quiz-preview-notice>` stays a sibling AFTER the head**; pulling it inside would break `test_e2e_unit_nav.py`'s `[data-quiz-preview-notice]` column-width assertion:

```html
  <div class="lesson-unit__head">
    <div class="lesson-unit__heading">
      <h1 class="lesson-unit__title" data-math-title>{{ unit.title }}</h1>
      {% include "courses/_unit_kind_chip.html" with node=unit only %}
    </div>
  </div>
  {% if previewing %}
  ...unchanged...
```

- [ ] **Step 4: Add the three CSS rules**

In `courses/static/courses/css/courses.css`, **immediately after** the `.lesson-unit__head .lesson-unit__title` rule at `:834-835` (and therefore **before** the `@media` block):

```css
/* The reset is MANDATORY and its source position is load-bearing.
   `.lesson-unit__head .lesson-unit__title` (:834) is a DESCENDANT selector, so it
   still matches the <h1> through this wrapper and would make it flex: 1 1 0%
   *inside the group* — absorbing every pixel and pushing the chip to the far
   right, reproducing the exact failures the group exists to fix. Both selectors
   are (0,2,0), so only source order decides: this must come after :834.
   No flex-wrap here — at desktop it would push the chip onto its own line for
   any title reaching the 736px cap (736 + 12 + ~78 > the ~746px group line).
   The <h1> shrinks instead; it keeps min-width: 0 and overflow-wrap from :834-835
   because this rule overrides only `flex`. */
.lesson-unit__heading { flex: 1 1 auto; min-width: 0;
  display: flex; align-items: baseline; gap: var(--space-3); }
.lesson-unit__heading > .lesson-unit__title { flex: 0 1 auto; }
```

Inside the `@media (max-width: 640px)` block, beside `:986`:

```css
  /* :986 gives .lesson-unit__title flex-basis: 100%, which today resolves against
     .lesson-unit__head and is what drops .unit-done / .lesson-unit__reset to a
     second row. After the wrapper it would resolve against .lesson-unit__heading
     instead, so give the GROUP basis 100% to restore that by construction.
     flex-wrap is added here (and only here) so the chip wraps under the title. */
  .lesson-unit__heading { flex-basis: 100%; flex-wrap: wrap; }
```

- [ ] **Step 5: Repair the two cap tests this change defuses**

Both work today because the `<h1>`'s *flex target* (~746px) exceeds the 736px prose cap, so `max-width` is what holds it. With `flex: 0 1 auto` the `<h1>` shrink-wraps to its content and `title_w < 738` passes **vacuously** — the pin dies without ever going red.

`tests/test_e2e_uniform_block_width.py::test_lesson_title_caps_in_a_two_item_head`:
- Seed a title whose natural content width exceeds 736px. `_seed_unit(username)`
  (`test_e2e_uniform_block_width.py:60-66`) takes no title and is **shared with the three-item
  test**, so add a `title=None` keyword defaulting to current behaviour rather than changing it in
  place.
- Re-point the fixture-validity guard **at the title**: neutralise `max-width` with `page.add_style_tag`, measure the `<h1>`'s rendered width with the cap neutralised — i.e. `min(max-content, flex target ≈ 746)`, the quantity that actually decides the guarded assertion (with the cap gone the `<h1>` is still `flex: 0 1 auto` in a ~746px group, so `getBoundingClientRect().width` and `scrollWidth` both report ~746; there is no separate "content width" to hunt for) — and assert **`>= 740`** (not `> 736` — the guarded assertion is `title_w < 738`, so a fixture landing in (736, 738] would pass the guard and leave the assertion green), then restore.
- "Restore" needs a mechanism: `page.add_style_tag` returns an `ElementHandle`. Capture it and call
  `handle.evaluate("e => e.remove()")` — the override does not disappear on its own, and left in
  place it neutralises the cap for the very assertion it protects.
- Do **not** substitute `group_w > 738`: `.lesson-unit__heading` is `flex: 1 1 auto`, so the group always grows to `head − pill − gap ≈ 746` regardless of the title, making that a rename of the existing space-measuring guard.
- Update **every comment in `test_lesson_title_caps_in_a_two_item_head` and in the three-item block
  above it** — not just the `~:150-183` range. The function's own docstring at `~:187-197` states the
  falsified mechanism verbatim ("The title's flex target is then ~872 - 16 gap - ~110 pill = ~746,
  ABOVE the 736 cap -- so the cap is what holds it down"), and the fixture-guard comment at
  `~:211-220` repeats it ("the title's flex target here is only ~20px above the cap"). Leaving either
  is false mechanism inside the very test being repaired. The three in `~:150-183` are: "the quiz page has no `.lesson-unit__head` at all" (it will have one), "an uncapped title would measure ~746" (the mechanism is now a >736px *content* width), and the "~643.6 … NO prose-cap mutation reddens either assertion" note at `~:170-179` (the `<h1>` now shrink-wraps, so both the figure and the mechanism are wrong).

`tests/test_e2e_unit_nav.py::test_quiz_chrome_tracks_the_column_across_both_page_states`:
- Its fixture is `make_quiz_unit(course=course)`, whose title comes from `ContentNodeFactory`'s
  `Sequence` ("Node N") — nowhere near 736px — and it currently has **no** fixture-validity guard at
  all. So this is not literally "the same repair": **seed the quiz node with a title whose content
  exceeds 736px**, and **add** the cap-neutralising `>= 740` guard (there is none to re-point).
- The guard is added **before each** of the two `title_w <= 736 + 2` assertions (`~:1386` and
  `~:1420`), and `max-width` must be **restored after each** — the second assertion runs after a
  `page.reload()` with the enrolment flipped, and a guard left in place would neutralise the cap for
  the very assertion it protects.
- Applied to **both** cap assertions — the test asserts `title_w <= 736 + 2` twice, once per page state (`~:1386` and `~:1420`). Its fixture is a **quiz**, so it *does* emit a chip; the assertion stays non-vacuous through different arithmetic (no done pill, so the group spans the full ~872px collapsed column and `736 + 12 + ~46 < 872` leaves the cap holding). That headroom exists only in the collapsed state — keep the test's existing collapsed-state guard.

`tests/test_quiz_previewer_render.py` renders `_quiz_article.html` directly via
`render_to_string(build_quiz_context(...))`. **Re-run it; expected unchanged and green** — its
assertions are about the preview banner, the finish form and input liveness, none of which touch the
head structure. Update it only if an assertion turns out to depend on that structure, and only then
add it to the commit.

- [ ] **Step 5b: Add the maths-title render case (spec §Render)**

The spec requires that one of the two unit-page render cases uses a **maths** title, asserting it
still typesets with the chip as a sibling. It joins `tests/test_title_math_markers.py` rather than
re-creating that suite's machinery.

Its fixture must be **marked**, and this is the trap: `tests/helpers_title_math.py` hardcodes
`obligatory=True` at `:72`, `:81`, `:90` and `:133`, so `_lesson_body(client, maths_on="unitA", ...)`
builds units that emit no chip and the case would be vacuous. Parameterise those sites (add an
`obligatory=True` keyword argument defaulting to the current value) or seed the maths title on a
quiz unit. Assert the chip renders **beside** the `<h1 data-math-title>`, not inside it; that the `<h1>` still
carries `data-math-title` (use the file's existing `_marked(html, "h1.lesson-unit__title")` helper);
that the raw `\(…\)` delimiters survive in its visible text; and that the page's `has_math` gate is
still set. **Do not assert "the KaTeX renders"** — that file is a Django-client render suite
(`_lesson_body` at `:76` returns `client.get(url).content.decode()`), and KaTeX is produced by
browser-side `math.js`, so it is unassertable there. Browser typesetting is covered by Task 7's
drawer-maths arm.

- [ ] **Step 6: Run the affected tests**

```bash
uv run pytest tests/test_unit_marker.py tests/test_quiz_previewer_render.py tests/test_title_math_markers.py -v
# Expected: PASS, plus the Task 1 xfail, which stays until Task 6.
uv run pytest -m e2e tests/test_e2e_uniform_block_width.py tests/test_e2e_unit_head_layout.py   "tests/test_e2e_unit_nav.py::test_quiz_chrome_tracks_the_column_across_both_page_states" -v
```

`tests/test_e2e_unit_head_layout.py` must be **unchanged and all green** — its `MEASURE` uses `head.querySelector('.lesson-unit__title')`, which is descendant-based and still finds the `<h1>` through the wrapper, and its phone assertions (`done_top >= title_bottom - 1`, `reset_top >= title_bottom - 1`) are exactly what the group's `flex-basis: 100%` preserves. **If any of its eight assertions goes red, the mobile rule is wrong — do not update the test to
match.** The file has two tests with four assertions each: the phone test
(`done_top >= title_bottom - 1`, `reset_top >= title_bottom - 1`) is what the group's
`flex-basis: 100%` preserves, and the desktop test (`done_top < title_bottom`,
`reset_top < title_bottom`) is exposed by the heading-group change too.

- [ ] **Step 7: Falsify — two mutants**

| Mutant | Must redden |
| --- | --- |
| Put the `{% include %}` inside the `<h1>` | the `data-math-title` sibling assertion, both templates |
| Delete the mobile `.lesson-unit__heading { flex-basis: 100%; flex-wrap: wrap }` | the **new phone unit-page arm in Task 7 Step 3** (chip-bearing, short title). **NOT** `test_e2e_unit_head_layout.py`: its `_seed` uses a long `LONG_TITLE` (`:25`), so with the rule deleted the group's basis-`auto` hypothetical size still exceeds the 390px line and `.lesson-unit__head`'s pre-existing `flex-wrap` (`courses.css:985`) still drops the pill to row two — both its phone assertions stay green on the mutated build |

The `flex: 0 1 auto` reset and the group's `flex: 1 1 auto` are falsified by the Task 7 e2e (they need geometry, which DOM-containment tests cannot see).

- [ ] **Step 8: Commit**

```bash
uv run ruff check --no-cache tests/test_unit_marker.py tests/test_e2e_uniform_block_width.py tests/test_e2e_unit_nav.py tests/test_title_math_markers.py tests/helpers_title_math.py
uv run ruff format --check tests/test_unit_marker.py tests/test_e2e_uniform_block_width.py tests/test_e2e_unit_nav.py tests/test_title_math_markers.py tests/helpers_title_math.py
git add templates/courses/_lesson_article.html templates/courses/_quiz_article.html courses/static/courses/css/courses.css tests/test_unit_marker.py tests/test_e2e_uniform_block_width.py tests/test_e2e_unit_nav.py tests/test_quiz_previewer_render.py
git commit -m "feat(courses): mark the unit kind on the unit page; repair the two cap pins"
```

---

### Task 6: Translations

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Modify: `tests/test_unit_marker.py` (remove the Task 1 xfail marker)

- [ ] **Step 1: Regenerate both catalogs**

```bash
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

`--no-obsolete` is **mandatory**, not optional: `docs/development/conventions.md:45-73` gives this as
the house command and records that "the project forbids obsolete `#~` entries in the catalog; a test
asserts the catalog is clean" (`tests/test_i18n_po_health.py`). Omitting it writes `#~` entries for
any drifted msgid, reddening that test at the Task 8 gate with a large unintended diff in both
catalogs. Both locales, every time: `pl` is translated, `en` is the source catalog with empty
msgstrs, and running `-l pl` alone leaves English stale.

- [ ] **Step 2: Verify `Quiz` was reused, not duplicated**

```bash
grep -n 'msgid "Quiz"' locale/pl/LC_MESSAGES/django.po
```

Expected: exactly one, already `msgstr "Quiz"`, with `courses/rollups.py` now added to its source-reference comment alongside `courses/models.py:198`. The msgid is shared with the `UnitType.QUIZ` `TextChoices` label and the two must never diverge.

- [ ] **Step 3: Translate `Additional` and clear any fuzzy**

```bash
grep -n -B 3 'msgid "Additional"' locale/pl/LC_MESSAGES/django.po
```

Set `msgstr "Dodatkowa"`. If `makemessages` fuzzy-prefilled it from a near neighbour (the existing
`additional` → `"dodatkowe"` is the obvious candidate), clearing it is **two deletions, and the
second is not the msgstr**: per `docs/development/conventions.md:62-65`, Django runs
`msgmerge --previous`, which writes a `#| msgid "<old string>"` comment above the entry. Delete the
`#, fuzzy` line **and** that `#| msgid` line — the msgstr is overwritten, not deleted. Leaving the
`#| msgid` means a grep for a retired string still finds it. Never accept a fuzzy entry as-is. Do **not** revisit the existing `additional` → `"dodatkowe"` entry: it is the form that agrees with its own count phrase, and forcing one surface form would make one of the two ungrammatical.

- [ ] **Step 4: Compile and drop the xfail**

```bash
uv run python manage.py compilemessages
```

Remove the `@pytest.mark.xfail` from `test_label_is_a_lazy_proxy_not_a_frozen_string` (Task 1, Step 5).

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/test_unit_marker.py tests/test_i18n_po_health.py tests/test_i18n_auth.py   tests/test_i18n_notes.py tests/test_i18n_error_pages.py -v
```

Expected: PASS, including the `translation.override("pl")` row with no xfail. The catalog-health
tests are run **here**, not at the Task 8 gate: regenerating both `.po` files can redden them, and
run late the failure gets attributed to the wrong task.

- [ ] **Step 6: Falsify — one mutant**

Change `gettext_lazy` to `gettext` in `courses/rollups.py`'s `UNIT_MARKER_LABELS`. The `translation.override("pl")` test must go RED (the dict is evaluated at import, before any request locale is active, so a non-lazy call freezes the first-seen language). Edit it back.

- [ ] **Step 7: Commit**

```bash
uv run ruff check --no-cache tests/test_unit_marker.py
uv run ruff format --check tests/test_unit_marker.py
git add locale/ tests/test_unit_marker.py
git commit -m "i18n(courses): Polish for the Additional marker; reuse the existing Quiz msgid"
```

---

### Task 7: e2e geometry

**Files:**
- Modify: `tests/test_e2e_unit_nav.py` (append)

Every geometric claim is **differential** — measuring a position with the rule present proves nothing, so each is either a comparison between two rendered rows or a mechanical A/B via `page.add_style_tag`. Every fixture must be marked (`obligatory=False` or a quiz) or the assertion is vacuous.

**Step 0 - add the seed helper. None of the file's existing seeds can be reused.**
`_seed_traversal_course`, `_seed_nav_course`, `_seed_grouped_course` and `_seed_text_and_table_unit`
all build default-`obligatory=True` lessons, which emit no marker at all. Add:

```python
def _seed_marked_group(username, *, slug):
    """A course whose one chapter holds FIVE marked units plus one completion.
    The chapter is the current unit's ancestor, so its <details> renders `open`
    (_unit_tree_node.html sets open only on contains_current) and every row is
    measurable. obligatory=False is explicit everywhere: the model default is True
    and a default-factory unit renders no marker, making every assertion vacuous.

    long_unit is ALSO marked completed (UnitProgressFactory(student=user,
    unit=long_unit, completed=True)) so `.unit-tree__check` renders for the
    completed-row arm -- that tick is behind {% if item.completed %}
    (_unit_tree_node.html:10) and nothing else in this seed produces one.
    Deliberately NOT short_unit: a leading tick eats row width, and short_unit is
    the row whose >=20px free-space guard the rail-gutter arm depends on.
    """
```

Returns `(user, course, chapter, short_unit, long_unit, quiz_unit, maths_unit, token_unit)` — **five**
marked units, because three arms need title shapes the others cannot supply:

- `short_unit` — title measurably narrower than the row's content box (the rail-gutter guard, and the
  desktop unit-page short-title arm).
- `long_unit` — a long **multi-word** title (the rail-gutter comparison's other half).
- `quiz_unit` — for the quiz-side unit-page arms.
- `maths_unit` — `obligatory=False`, title **`capture_title_math_screenshots.TITLES["long"]`**, the
  long maths title the existing audit actually measured. `TITLES` is a plain module-level dict
  (`capture_title_math_screenshots.py:57`) and is importable; it is that script's *course builder*
  that cannot be reused here, not the titles. Do **not** substitute
  `helpers_title_math.MATHS_TITLE` — it is a short title from a different module, may not even wrap
  in the ~230px drawer column, and would make the re-check materially weaker than the like-for-like
  re-measurement the spec requires.
- `token_unit` — `obligatory=False`, title containing **one unbroken token measured wider than the
  390px outline title column**. Required by the outline arm: a multi-word long title wraps at spaces
  under `overflow-wrap: normal` too, leaving that mutant green.

Every arm below names which of these it drives.

- [ ] **Step 1: Desktop rail gutter**

Two units with markedly different title lengths in the same open group, **both marked**, scoped to `[data-unit-tree-list]`. Assert their `.unit-kind` boxes share a **`right`** within ~1px, and `abs(icon.right - (row.right - 8)) <= 1` (`.unit-tree__unit`'s `padding: .3rem .5rem`, `courses.css:766`).

Compare `right`, not `x`: `x` is the wrapper's *left* edge and the wrapper is ~13px wide at the rail's `.82rem`, so asserting `x` is "near" the row's right content edge is red on a correct build.

**Fixture-validity guard, required first:** assert the short row's `.unit-tree__label` width is at least ~20px under the row's content width. `.unit-tree__label` already has `overflow: hidden; text-overflow: ellipsis`, so on the reverted build a title whose max-content exceeds the row still fills it and the marker still lands flush — with two long titles **both assertions are green with `flex-grow` removed**.

- [ ] **Step 2: Desktop unit page — two fixtures, non-interchangeable**

Both article templates, both rail states. Use the file's existing **`_collapse(page)`**
(`test_e2e_unit_nav.py:49`), which waits on the `html.unit-tree-collapsed` class — do not toggle the
state another way. It is load-bearing: the 736px prose cap applies **only** in the collapsed state,
so the cap-length assertions are meaningful only there.

**Short-title row** (title content ~100px; guard first that the `<h1>` measures under ~150px, with a message saying the fixture no longer exercises the reset — the 200px bound below is red on a *correct* build once the heading passes ~188px):
1. `chip.left - group.left < 200`. Write it as that absolute bound, **not** as `chip.left == title.right + gap`: adjacency is invariant across both builds, since without the reset the `<h1>` merely grows and the chip still sits `gap` past its right edge.
2. Lesson page only: `.unit-done`'s left edge `== group.right + 16` (the head's `gap: 1rem`, `courses.css:829`). Measure `.unit-done` — the head's actual flex item — not `.unit-done__pill`, which on a not-completed fixture is a button inside a `<form>`.

Both must sit on the **short-title** row: with a cap-length title the group's base (736 + 12 + 78 = 826) already exceeds the ~746px line, free space is zero, `space-between` degenerates to flex-start, and the pill assertion holds on the broken build too.

**Cap-length row** (title content > 736px): one assertion — the chip has **not** wrapped below the title, `chip.top < title_bottom - 1`. Do **not** assert `chip.top ≈ title_top`: `align-items: baseline` makes the two tops differ by ~10–15px on a correct build. This row cannot catch the missing reset (both builds put `chip.left` at `group.left + 668`) and gets no chip-width assertion (a `flex: 0 1 auto` chip's shrink target is a min violation, so it freezes at its full width either way).

- [ ] **Step 3: Phone 390×780 — the drawer must actually be opened**

`.unit-drawer` is `display: none` at base (`courses.css:946`), revealed only inside `@media (max-width: 640px)` via `.unit-drawer:not([hidden])` (`:961`), and carries a literal `hidden` attribute until `unit_nav.js` responds to the footer `[data-unit-drawer-open]` trigger. Sequence: resize → click the footer Contents trigger → wait for `[data-unit-drawer]` to lose `hidden` → assert.

- `.unit-kind__label` inside `[data-unit-drawer-list]` has `width >= 30` **and** `height >= 8`. The numeric thresholds are the point: `.visually-hidden` is 1px×1px with a zero clip rect, which Playwright reports as **visible with a non-empty box**, so `bounding_box() is not None` cannot distinguish an un-hidden label from a still-hidden one, nor catch a partial revert.
- The marker keeps its width, **differentially** so no font metric is hardcoded: `label.right <= marker.right + 1`. Under a shrinkable-marker mutant the children keep their sizes while the wrapper is cut, so they overflow it. Do **not** assert an absolute "~91px ±1" — that figure is derived from an estimated word width and would likely be red on a correct build.
- Glyph-to-word gap: `label.left - svg.right == 4` (±1), where both are elements with real boxes.
- Containment: `.unit-kind`'s `right <= row.right - 8`. Kept from the spec, but note it holds on
  **both** builds (after a shrink the row still has zero free space and the marker still ends at the
  padding edge), so it carries **no mutant** — the differential `label.right <= marker.right + 1`
  above is the discriminating one.
- Row shape for a completed additional unit: one flex line — `.unit-tree__check`, `.unit-tree__label` and `.unit-kind` share a top within a few px.
- **A/B the label's wrap points**: record `.unit-tree__label`'s `getBoundingClientRect().height` for a fixed long title, re-measure with `page.add_style_tag` injecting `.unit-drawer__list .unit-tree__label { flex: 0 1 auto !important }` — the pre-change computed value, named explicitly because `add_style_tag` can only *add* a declaration and `flex: none`/`flex: 1 1 0` would change the base size and redden a correct build — and assert the two heights are equal. **Then tear the override down**:
  `page.add_style_tag` returns an `ElementHandle` and the `!important` rule does not disappear on its
  own — capture the handle and call `handle.evaluate("e => e.remove()")` immediately after the second
  measurement. It changes the drawer label's flex and therefore the marker's position, so leaving it
  in place corrupts every later assertion on that page (notably the maths re-check). Alternatively,
  make this the **last** assertion performed on that drawer page and say so.
- **Unit-page head at 390 wide** (spec §Testing; this arm exists because
  `test_e2e_unit_head_layout.py` structurally cannot cover it - its fixture renders no chip). Drive
  `quiz_unit` or `short_unit`: assert `chip.top >= title_bottom - 1` **and**
  `chip.left == group.left` (+/-1) - exact, not "near": at 390px the `<h1>` keeps `flex-basis: 100%`
  from `courses.css:986`, the group wraps, and the chip starts a fresh flex line at the group's
  content-box left under the default `justify-content: flex-start` (the group has no padding). This
  is the **sole** pin for the mobile `.lesson-unit__heading` rule (see Task 5's mutant table).
- **Drawer maths re-check** (spec §Testing): assert no `.katex` box intersects `.unit-kind`'s rect,
  scoped to `[data-unit-drawer-list] .unit-kind` - unscoped is a strict-mode violation, since the
  page renders the tree twice. Three requirements, none optional:
  1. **Fixture-validity guard first**: assert at least one `[data-unit-drawer-list] .unit-kind` has a
     non-`None` box **before** the intersection loop. Without it the loop iterates an empty list and
     is green on every build - and that is the default outcome, because
     `tests/helpers_title_math.py` hardcodes `obligatory=True` at `:72`, `:81`, `:90`, `:133`.
  2. Seed a **marked** unit carrying a maths title (flip one of those sites, or seed the maths title
     on a quiz).
  3. **Expected outcome: no intersection.** If it *does* intersect, that is a design change, not a
     test tweak - the remedy is containment on the drawer label's maths (the `max-width`/`overflow`
     shape `courses.css:1685` applies to tab labels) or moving the marker. Do not widen the
     tolerance. The original audit measured `.katex` only against controls that **lead** a unit row
     or live on group rows, so it carries no evidence for a right-hand neighbour: this is a genuine
     measurement, not a formality.
- Desktop, in the same file: `[data-unit-tree-list] .unit-kind__label` measures `width <= 2 and height <= 2` — i.e. still hidden in the rail. Without it, an un-hide rule placed **outside** the media query passes every other assertion while eating ~58px of the rail's ~98px title column.
- **Outline** at 390 wide, long unbroken / Polish title (measured wider than the rendered title column — measure it, do not derive it): `title.scrollWidth - title.clientWidth <= 1` on `.outline-unit__title`, plus `.outline-unit.right <= li.right + 1` and `document.documentElement.scrollWidth === clientWidth`.

- [ ] **Step 4: Run the e2e**

```bash
uv run pytest -m e2e tests/test_e2e_unit_nav.py -v
```

Windows note: a backgrounded pytest is reaped by the harness mid-run. Use `Start-Process` and poll the PID, and **grep the summary line** — a backgrounded run has reported exit 0 with `1 failed`.

- [ ] **Step 5: Falsify - eight mutants, TEN runs**

The un-hide row below is **three separate runs** (deletion, partial revert, mis-scoped). Do not read
the row count as the run count - that is exactly how the sole additive mutant gets skipped.

| Mutant | Must redden |
| --- | --- |
| `.unit-tree__label`'s `flex: 1 1 auto` reverted to no `flex` | shared-`right` gutter **and** the `icon.right` offset |
| `.lesson-unit__heading > .lesson-unit__title { flex: 0 1 auto }` deleted | the **short-title** chip-position assertion (not the cap-length one) |
| `.lesson-unit__heading`'s `flex: 1 1 auto` deleted | the pill-position assertion |
| `flex-wrap: wrap` **added** to the group at desktop | the cap-length not-wrapped assertion |
| The `.unit-drawer__list .unit-kind__label` un-hide deleted — **and separately** the partial revert (`position: static` only), and separately placing the block outside the media query | the 30×8 assertion (first two); the desktop rail ≤2×2 assertion (third) |
| `.unit-drawer__list .unit-kind { flex: 0 1 auto; min-width: 0 }` **added** | the marker-width assertion. This is the list's only **additive** mutant and its sole catcher — the 30×8 and gap assertions both stay green under it |
| `overflow-wrap` **removed entirely** (→ `normal`) from `.outline-unit__title` | the outline `title.scrollWidth` assertion |
| `gap: var(--space-1)` deleted from `.unit-kind` | the drawer row's glyph-to-word gap assertion (4px → 0px; a flex container drops whitespace-only text between items, so the delta is clean). **Not** `display: inline-flex`, whose removal substitutes a ~4px rendered space that lands inside tolerance |

**Do not** falsify `anywhere` → `break-word` (pixel-identical with `min-width: 0` co-applied), the drawer `overflow-wrap` (inert at ~230px), either `min-width: 0` (inert with `anywhere` present), or dropping the `.unit-drawer__list` selector while the block stays inside the media query (inert — `courses.css:950` hides the rail at ≤640px). Each would be green on the "broken" build.

- [ ] **Step 6: Commit**

```bash
uv run ruff check --no-cache tests/test_e2e_unit_nav.py
uv run ruff format --check tests/test_e2e_unit_nav.py
git add tests/test_e2e_unit_nav.py
git commit -m "test(e2e): geometry pins for the unit kind markers"
```

---

### Task 8: Screenshots and the branch gate

**Files:**
- Create: `tests/capture_unit_marker_screenshots.py`
- Modify: `tests/test_title_math_markers.py` (docstring only)

- [ ] **Step 1: Capture screenshots, light and dark**

**Mirror `tests/capture_title_math_screenshots.py`** — same harness (`_allow_async_unsafe`,
`pytestmark = pytest.mark.e2e`, `_login`, the gitignored shot directory) and the same conventions.
Dark mode is set via **`User.theme`, not a cookie**.

**Seed** — every unit must be marked or it renders nothing (`obligatory` defaults to `True`): one
`obligatory=False` lesson, one quiz, one required lesson as the unmarked control, and one
`obligatory=False` lesson whose title is a single wide `\frac{…}{…}` for the maths outline row.

**Shots**, each in light **and** dark:
1. rail rows, both glyphs (~13px);
2. a **drawer row** at 390×780, both glyphs (~16px — larger there because `font-size: .82rem` sits on
   `.unit-tree` alone and the drawer is its sibling);
3. outline row at rest, `:hover`, and `:target`;
4. **a maths outline row** — the only acceptance for the spec's documented-but-untested residual (an
   unbreakable KaTeX atom painting across the 8px gap into the chip);
5. the unit-page head.

**Invocation** — the file is `capture_*`, so `python_files = ["test_*.py"]` never auto-collects it
and neither pytest run in Step 3 would execute it:

```bash
uv run pytest tests/capture_unit_marker_screenshots.py -m e2e
```

Judge dark on its own rather than inferring it from light. This is where two deferred acceptance
steps actually happen: the **glyph legibility** argument in §5 (a circled `?` is a compound stroke
path that reads as a blob if drawn naively at small sizes) and the accepted `--surface-sunken`
collision on the outline (the chip's fill matches `.outline-unit:hover` and `.outline-node:target`,
leaving only its 1px rim as separation).

- [ ] **Step 2: Update the maths-marker docstring**

`tests/test_title_math_markers.py:157` sits inside an inventory of "the THREE true double-interpolation sites" — places where the same **node title** is interpolated twice. `.unit-kind`'s `title=` carries the **marker word**, not the title, so it does **not** belong on that list and must not be added to it. Add the mention to the docstring's *exclusion* paragraph instead, modelled on the existing "`h1.lesson-unit__title` is deliberately NOT in this guard" note at `:164-169`.

- [ ] **Step 2b: Refresh the line citations THIS change shifts**

Task 4 inserts a line into `_unit_tree_node.html` after `:15`; Task 5's snippet replaces one `<h1>`
line in `_quiz_article.html` with six (net **+5**), moving the `lang` house-rule comment from
`:12-15` to `:17-20`. The plan is meticulous about the six stale `courses.css` citations it
inherits — it must not leave behind the ones it creates.

**Discover them, do not enumerate them:**

```bash
grep -rn "_unit_tree_node.html:" tests/ templates/ courses/
grep -rn "_quiz_article.html:" tests/ templates/ courses/
```

**Refresh citations in live source and tests only.** Do **not** rewrite
`docs/superpowers/plans/` or `docs/superpowers/specs/` — those are historical records of the state at
their own authoring time (the grep finds eight such hits in
`docs/superpowers/plans/2026-08-10-latex-in-unit-titles.md` alone), and "correcting" them falsifies
the record.

Known hits at time of writing, per file: `test_title_math_filter.py:123` cites `:15` and `:131`
cites `:25`; `test_title_math_markers.py:119` cites `:60`. Note **`:15` does not move** — inserting
*after* it leaves `span.unit-tree__label` in place — so do not "fix" that one. Rely on the grep
rather than this list. There is no `_unit_tree_node.html:22` citation anywhere in the repo; that
figure appears only in the spec's prose, so nothing to refresh there.

- [ ] **Step 3: Branch gate — the full suite**

```bash
docker ps | grep libli-test-db          # must be up first
uv run pytest --verbosity=0
uv run pytest --verbosity=0 -m e2e
uv run pytest tests/capture_title_math_screenshots.py tests/capture_unit_marker_screenshots.py -m e2e
uv run ruff check --no-cache .
uv run ruff format --check .
```

`--verbosity=0`, not `-q`: `addopts` already carries one `-q`, and a **doubled** `-q` suppresses the
summary line this step tells you to grep. The two `capture_*` files are named explicitly because
`python_files` never collects them.

Grep the summary line of each run — do not trust the exit code alone. `ruff`'s `# noqa` warning is **cached away**, so a second run says "All checks passed"; `--no-cache` is mandatory. `ruff format --check` is a separate CI gate from `ruff check`.

- [ ] **Step 4: Re-run the source guards after the last mutant**

Several tests in this repo regex-match raw CSS/template source (`test_unit_tree_long_titles.py`, `test_title_math_markers.py`, `capture_title_math_screenshots.py`). Re-run them **after** every mutant has been edited back out, and read the final `git diff` in full — a missed mutant anchor plus suppressed stderr reads exactly like a passing mutant.

- [ ] **Step 5: Commit**

```bash
git add tests/capture_unit_marker_screenshots.py tests/test_title_math_markers.py
git commit -m "test: unit-marker screenshots; note the marker in the maths-title exclusions"
```

---

## Self-Review

**1. Spec coverage.** §1 → Task 1. §2 → Task 1 (registrations). §3 → Task 2 (three partials, class + accessible-name contracts). §4 outline → Task 3; rail + drawer + maths audit → Task 4; unit page → Task 5. §5 glyphs → Task 2 (geometry) + Task 8 (legibility acceptance). §6 → Task 6. Data-flow (no new queries) → no code, asserted by the absence of query changes. Error handling → Task 1's table (non-node, unset `unit_type`, non-unit) and the `only` include contract in Tasks 3–5. Testing §: unit → Task 1/2; render ×4 → Tasks 3, 4, 5; e2e → Task 7; screenshots → Task 8; the seven existing test locations → Tasks 4, 5, 8. Falsification: every mutant in the spec's list is assigned to a task, and every declaration the spec calls inert is explicitly excluded from having one.

**2. Placeholder scan.** No TBD/TODO. Every code step carries real code or an exact command. Task 7's e2e steps describe assertions and mechanisms rather than full Playwright bodies — deliberate: they depend on the file's existing harness (`_allow_async_unsafe`, `_login`, the drawer helpers), and each assertion states its exact comparison, tolerance and fixture constraint.

**3. Type consistency.** `unit_marker(node) -> str`, `marker_label(marker) -> str|lazy` used identically in Tasks 1–5. Filter name `unit_marker`, tag name `marker_label` consistent throughout. Class names `unit-kind-chip`, `unit-kind`, `unit-kind__label`, `lesson-unit__heading` consistent across tasks and tests. Constants `MARKER_QUIZ`/`MARKER_ADDITIONAL`/`MARKER_NONE` used in both the implementation and the assertions.
