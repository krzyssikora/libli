# Unit-level Slideshow Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any unit (lesson or quiz) become a "slideshow" — its elements shown one slide at a time with a `N / total` counter and free Prev/Next — by inserting one or more slide-break elements between its elements.

**Architecture:** A new field-less `SlideBreakElement` concrete type acts as a pure delimiter. A pure helper partitions a unit's ordered `Element` join-rows into `slides` (splitting on breaks, dropping empty groups); the two context builders add `slides`; the article templates render one `<div class="slide">` per group and mark the article `[data-slideshow]` when `slides|length > 1`. A new deferred `slideshow.js` paginates client-side (with a no-JS fallback of all slides stacked). Quiz question numbering moves from a CSS counter to server-side markup so `display:none` hiding is safe.

**Tech Stack:** Django 5 (server-rendered templates), vanilla JS (no framework), token-driven CSS, pytest + pytest-django, Playwright e2e, `uv run` for all tooling.

## Global Constraints

- Tooling: run all Python tooling via `uv run` (bash `ruff`/`pytest`/`python` are NOT on PATH). Every task's DoD runs BOTH `uv run ruff check .` and `uv run ruff format --check .`.
- Icons: monochrome `currentColor` line SVGs referenced via `<svg class="ic"><use href="#el-..."/></svg>` sprite symbols; never multicolour emoji.
- i18n: module-level translatable strings use `gettext_lazy` (not eager `_`); template strings use `{% trans %}`/`{% blocktrans %}`; provide EN + PL. Keep the PL catalog free of obsolete `#~` entries; run the i18n catalog tests whenever a build removes a translatable string.
- No hardcoded test passwords: use `tests.factories.TEST_PASSWORD`.
- Django comments: `{# #}` single-line only; use `{% comment %}…{% endcomment %}` for multi-line.
- Every view ships styled and verified in light + dark (screenshot self-check per the repo's frontend rules).
- The unit-level mode is named "slideshow". Do NOT build the separate future in-unit image-carousel "slideshow element" — out of scope.
- Design source of truth: `docs/superpowers/specs/2026-07-08-slideshow-mode-design.md`.

---

## Test Infrastructure (READ FIRST — all task tests depend on this)

There is **no `courses/tests/` package**. All Python tests live in the top-level
**`tests/`** package; factories/helpers live in **`tests/factories.py`**. Every new
test file below is `tests/test_slideshow_*.py`, and every `uv run pytest` command
targets `tests/…` (never `courses/tests/…`). Use these REAL helpers (verified to
exist in `tests/factories.py`) — do NOT invent fixtures or `make_unit`:

- `TEST_PASSWORD` — the only allowed test password.
- `ContentNodeFactory(course=?, parent=?, kind="unit", unit_type="lesson"|"quiz", title=?)` — build a unit node.
- `make_quiz_unit(course=None, **kw)` — convenience quiz-unit builder.
- `add_element(unit, obj)` — attach a concrete element (e.g. `TextElement`, `SlideBreakElement`, a question) to a unit as an ordered `Element` join-row; returns the join-row. Use this everywhere instead of `Element.objects.create(...)`.
- `EnrollmentFactory(student=?, course=?)` — enrol a student (needed for quiz submissions / progress writes).
- `make_login(client, username)` / `make_student(client, username="student")` — create + log in a user; returns the user.

**Shared seed helper** — add ONE helper to `tests/factories.py` (Task 2 introduces it, later tasks reuse it) rather than per-task fixtures:

```python
# tests/factories.py
def seed_slideshow_unit(course, unit_type="lesson", *, layout):
    """Build a unit whose elements follow `layout`: a list where "q" = a question
    (ShortTextQuestionElement), "t" = a TextElement, "brk" = a SlideBreakElement.
    Returns the unit node. Uses add_element so join-row order matches list order."""
    from courses.models import (
        ContentNode, SlideBreakElement, TextElement, ShortTextQuestionElement,
    )
    unit = ContentNodeFactory(course=course, kind="unit", unit_type=unit_type)
    for token in layout:
        if token == "brk":
            add_element(unit, SlideBreakElement.objects.create())
        elif token == "q":
            add_element(unit, ShortTextQuestionElement.objects.create(stem="Q?"))
        else:
            add_element(unit, TextElement.objects.create(body="x"))
    return unit
```

Tests then do, e.g.: `unit = seed_slideshow_unit(course, "lesson", layout=["t", "brk", "t"])`, log in with `make_student(client)`, enrol with `EnrollmentFactory`, and resolve URLs via `reverse("courses:<name>", ...)` (never hardcode paths). A `course` is built with the existing `CourseFactory` (see `tests/factories.py`); reuse whatever the existing course tests use.

**e2e is Python `pytest-playwright`, NOT a JS runner.** There is **no `e2e/` directory**. e2e tests live in `tests/` as `tests/test_e2e_*.py`, marked `pytestmark = pytest.mark.e2e` (excluded from the default run; run with `-m e2e`), using the sync Playwright API (`page.get_by_role(...).click()`, `expect(locator).to_be_visible()`), the `page` + `live_server` fixtures, and a module-local `_login(page, live_server, username)` helper that fills the allauth form (see `tests/test_e2e_html_element.py` for the canonical harness — copy its `_allow_async_unsafe` autouse fixture, `_login`, and `_seed_*` pattern). Seed data via the ORM/`tests.factories` (e.g. `seed_slideshow_unit`) inside the test process and return the URL path to `page.goto(f"{live_server.url}{path}")`. All slideshow e2e goes in ONE file `tests/test_e2e_slideshow.py`; run with `uv run pytest tests/test_e2e_slideshow.py -m e2e`. Do NOT write `test('…', async ({ page }) => …)` JS specs or `getByRole` camelCase — those are wrong for this repo.

A reusable e2e seed helper (add near the other `_seed_*` helpers in the test file):

```python
def _seed_slideshow_lesson(viewer, *, slides, tall_first=False):
    """Build an enrolled course + a lesson unit whose elements form `slides`
    groups separated by breaks; return the take-URL path. `slides` is a list of
    ints (elements per slide). tall_first makes slide 0 exceed the viewport."""
    # Use CourseFactory + EnrollmentFactory(student=viewer, course=course) + add_element
    # with TextElement (body long/tall when tall_first) and SlideBreakElement between
    # groups; return reverse("courses:lesson_unit", kwargs={"slug":..., "node_pk":...}).
```

---

## File Structure

- **Create** `courses/slideshow.py` — pure `partition_into_slides(elements)` helper.
- **Create** `courses/migrations/00NN_slidebreakelement.py` — new model (auto-generated).
- **Create** `templates/courses/elements/slidebreakelement.html` — defensive empty render template (created in **Task 1**, before any page render of a break-containing unit).
- **Create** `courses/static/courses/js/slideshow.js` — client pagination.
- **Modify** `courses/models.py` — `SlideBreakElement`, `ELEMENT_MODELS`.
- **Modify** `courses/views.py` — `build_lesson_context`/`build_quiz_context` add `slides`; `seen` view excludes breaks.
- **Modify** `courses/element_forms.py` — `SlideBreakElementForm`, `FORM_FOR_TYPE`.
- **Modify** `courses/views_manage.py` — `_EDITOR_TYPE_LABELS`, the two allowed-type tuples, direct-create path for the break.
- **Modify** `templates/courses/_lesson_article.html`, `templates/courses/_quiz_article.html` — slides loop.
- **Modify** the quiz question template/partial + `courses/static/courses/css/courses.css` — server-side numbering + `.slide` layering + FOUC.
- **Modify** `templates/courses/quiz_unit.html`, `templates/courses/lesson_unit.html` (+ any shared head) — load `slideshow.js`, synchronous `.js` root class.
- **Modify** `templates/courses/manage/editor/_add_menu.html`, `_element_row.html` (+ icon sprite) — palette entry + divider row + legend.
- **Modify** `courses/transfer/export.py`, `courses/transfer/payloads.py`, `courses/transfer/importer.py` — register `slide_break` in all three registries.
- **Tests** under `tests/` (unit/view/template) and `e2e/` (Playwright), matching existing locations.

---

## Task 1: `SlideBreakElement` model + registration

**Files:**
- Modify: `courses/models.py` (add to `ELEMENT_MODELS`; add `SlideBreakElement`)
- Create: `courses/migrations/00NN_slidebreakelement.py` (via makemigrations)
- Create: `templates/courses/elements/slidebreakelement.html` (empty defensive template — see Step 3b; MUST exist before Task 5/6 render any break-containing page, or `ElementBase.render()` 500s on the missing template)
- Test: `tests/test_slideshow_model.py`

**Interfaces:**
- Produces: `SlideBreakElement(ElementBase)` — no content fields, `elements = GenericRelation(Element)`. `"slidebreakelement"` present in `ELEMENT_MODELS`.

> **Note:** an earlier draft added a `ContentNode.is_slideshow` property, but no code consumes it (the taking articles + JS gate on `slides|length`, per the spec), so it is deliberately NOT built here — YAGNI. If a builder badge later needs it, add it then, with its own test.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_slideshow_model.py
import pytest
from django.contrib.contenttypes.models import ContentType
from courses.models import ELEMENT_MODELS, SlideBreakElement


@pytest.mark.django_db
def test_slidebreakelement_registered_and_fieldless():
    assert "slidebreakelement" in ELEMENT_MODELS
    brk = SlideBreakElement.objects.create()
    # No content fields beyond the pk + GenericRelation.
    concrete_fields = [f.name for f in SlideBreakElement._meta.fields]
    assert concrete_fields == ["id"]
    # A ContentType row exists (needed by the transfer + seen-exclusion paths).
    ct = ContentType.objects.get_for_model(SlideBreakElement)
    assert ct.app_label == "courses"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_slideshow_model.py -v`
Expected: FAIL (ImportError: cannot import name 'SlideBreakElement').

- [ ] **Step 3: Implement the model**

In `courses/models.py`, add `"slidebreakelement"` to the `ELEMENT_MODELS` list (append at end). Add the model near the other `ElementBase` subclasses:

```python
class SlideBreakElement(ElementBase):
    """Field-less delimiter: splits a unit's elements into slides (slideshow mode).

    Rendered content is nothing — the taking view consumes breaks in
    partition_into_slides. A defensive empty template exists only so a generic
    .render() path (builder preview) cannot 500 on a missing template."""

    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row
```

- [ ] **Step 3b: Create the defensive empty render template**

```django
{# templates/courses/elements/slidebreakelement.html — intentionally empty: breaks are consumed by partition_into_slides before render (Task 6); this exists only so ElementBase.render() cannot 500 on a missing template when a break-containing page is rendered before/around the loop restructure. #}
```

- [ ] **Step 4: Generate + run the migration**

Run: `uv run python manage.py makemigrations courses`
Expected: a new migration creating `SlideBreakElement`. Then `uv run python manage.py migrate`.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_slideshow_model.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add courses/models.py courses/migrations templates/courses/elements/slidebreakelement.html tests/test_slideshow_model.py
git commit -m "feat(courses): SlideBreakElement field-less delimiter + defensive template"
```

---

## Task 2: `partition_into_slides` pure helper

**Files:**
- Create: `courses/slideshow.py`
- Test: `tests/test_slideshow_partition.py`

**Interfaces:**
- Produces: `partition_into_slides(elements) -> list[list[Element]]`. Input is an ordered list of `Element` join-rows (with `content_object` available). Splits on any join-row whose `content_object` is a `SlideBreakElement`; drops empty groups; breaks are omitted from output. A list with no breaks → `[elements]` (one slide) when non-empty, else `[]`. Output holds the SAME `Element` join-row objects (identity preserved, never unwrapped to `content_object`).

- [ ] **Step 1: Write the failing test**

First, add the `seed_slideshow_unit` helper to `tests/factories.py` (per the Test Infrastructure section) — later tasks reuse it. Then the pure-function test builds join-row lists directly with `add_element`:

```python
# tests/test_slideshow_partition.py
import pytest
from courses.models import SlideBreakElement, TextElement
from courses.slideshow import partition_into_slides
from tests.factories import CourseFactory, ContentNodeFactory, add_element


def _unit():
    return ContentNodeFactory(course=CourseFactory(), kind="unit", unit_type="lesson")


def _text(unit):
    return add_element(unit, TextElement.objects.create(body="x"))  # returns the Element join-row


def _brk(unit):
    return add_element(unit, SlideBreakElement.objects.create())


@pytest.mark.django_db
def test_no_breaks_single_slide():
    u = _unit()
    els = [_text(u), _text(u)]
    assert partition_into_slides(els) == [els]  # identity preserved


@pytest.mark.django_db
def test_split_and_identity():
    u = _unit()
    a, b = _text(u), _text(u)
    brk = _brk(u)
    c = _text(u)
    slides = partition_into_slides([a, b, brk, c])
    assert slides == [[a, b], [c]]
    assert brk not in slides[0] and brk not in slides[1]  # break consumed


@pytest.mark.django_db
def test_leading_trailing_consecutive_breaks_drop_empties():
    u = _unit()
    b0, a, b1, b2, c, b3 = _brk(u), _text(u), _brk(u), _brk(u), _text(u), _brk(u)
    assert partition_into_slides([b0, a, b1, b2, c, b3]) == [[a], [c]]  # no empty slides


@pytest.mark.django_db
def test_only_breaks_yields_no_slides():
    u = _unit()
    assert partition_into_slides([_brk(u), _brk(u)]) == []


@pytest.mark.django_db
def test_empty_input():
    assert partition_into_slides([]) == []
```

(Confirm `CourseFactory` / `add_element`'s exact signatures in `tests/factories.py` before writing — `add_element(unit, obj)` returns the created `Element` join-row and assigns order in call sequence.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_slideshow_partition.py -v`
Expected: FAIL (ModuleNotFoundError: courses.slideshow).

- [ ] **Step 3: Implement the helper**

```python
# courses/slideshow.py
"""Pure partitioning of a unit's elements into slides (slideshow mode).

A unit paginates when it contains at least one slide-break element. This helper
splits the ordered Element join-rows on each break, dropping empty groups so a
leading/trailing/consecutive break never yields an empty slide. It returns the
same join-row objects (never unwrapped to content_object) so the caller's render,
data-element-id, and progress paths keep working unchanged."""

from courses.models import SlideBreakElement


def partition_into_slides(elements):
    """Split ordered Element join-rows into a list of non-empty slide groups.

    Breaks are consumed (never emitted). Zero breaks -> one slide with everything
    (or [] if `elements` is empty). Only-breaks -> [] (no content slides)."""
    slides = []
    current = []
    for el in elements:
        if isinstance(el.content_object, SlideBreakElement):
            if current:
                slides.append(current)
                current = []
        else:
            current.append(el)
    if current:
        slides.append(current)
    return slides
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_slideshow_partition.py -v`
Expected: PASS (all 5).

- [ ] **Step 5: Commit**

```bash
git add courses/slideshow.py tests/test_slideshow_partition.py
git commit -m "feat(courses): partition_into_slides helper (split on break, drop empties)"
```

---

## Task 3: Context builders add `slides`

**Files:**
- Modify: `courses/views.py` (`build_lesson_context`, `build_quiz_context`)
- Test: `tests/test_slideshow_context.py`

**Interfaces:**
- Consumes: `partition_into_slides` (Task 2).
- Produces: both context dicts gain `"slides"` (list of lists of `Element` join-rows). No `is_slideshow` key is added to the taking context (the render gate is `slides|length`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_slideshow_context.py
import pytest
from courses.views import build_lesson_context, build_quiz_context
from tests.factories import CourseFactory, EnrollmentFactory, make_student, seed_slideshow_unit


@pytest.mark.django_db
def test_lesson_context_slides(client):
    course = CourseFactory()
    student = make_student(client)
    EnrollmentFactory(student=student, course=course)
    unit = seed_slideshow_unit(course, "lesson", layout=["t", "brk", "t"])  # -> two slides
    ctx = build_lesson_context(unit, student)
    assert [len(s) for s in ctx["slides"]] == [1, 1]
    assert "is_slideshow" not in ctx  # taking context gates on slide count only


@pytest.mark.django_db
def test_quiz_context_single_slide_when_no_break(client):
    course = CourseFactory()
    student = make_student(client)
    EnrollmentFactory(student=student, course=course)
    unit = seed_slideshow_unit(course, "quiz", layout=["q", "q"])  # no break
    ctx = build_quiz_context(unit, student)
    assert len(ctx["slides"]) == 1
    assert len(ctx["slides"][0]) == len(ctx["elements"])
```

(Confirm `build_quiz_context` requires an enrolled user for the submission `get_or_create`; if it tolerates a non-enrolled previewer, the `EnrollmentFactory` line can be dropped for the quiz test.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_slideshow_context.py -v`
Expected: FAIL (KeyError: 'slides').

- [ ] **Step 3: Implement**

In `build_lesson_context` and `build_quiz_context`, after the `elements` list is fully built and `content_object` is prefetched, add:

```python
    from courses.slideshow import partition_into_slides
    ...
    ctx = {
        ...
        "elements": elements,
        "slides": partition_into_slides(elements),
        ...
    }
```

Place the `partition_into_slides(elements)` call so it uses the already-prefetched `elements` list (do not re-query). Keep `"elements"` in the context (other includes/tests may reference it), but the article templates will iterate `slides`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_slideshow_context.py -v`
Expected: PASS.

- [ ] **Step 5: Run the broader view suite for regressions**

Run: `uv run pytest tests/ -k "lesson or quiz" -q`
Expected: PASS (no regressions from the added key).

- [ ] **Step 6: Commit**

```bash
git add courses/views.py tests/test_slideshow_context.py
git commit -m "feat(courses): context builders emit slides via partition_into_slides"
```

---

## Task 4: `seen` view excludes breaks + union-semantics lock

**Files:**
- Modify: `courses/views.py` (`seen`)
- Test: `tests/test_slideshow_seen.py`

**Interfaces:**
- Consumes: `seen` view POST (JSON array of `Element` join-row pks).
- Produces: completion `current` set excludes slide-break join-rows (filtered by `ContentType`); union semantics unchanged (verified by test).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_slideshow_seen.py
import json
import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from courses.models import SlideBreakElement, UnitProgress
from tests.factories import CourseFactory, EnrollmentFactory, make_student, seed_slideshow_unit


@pytest.mark.django_db
def test_completion_ignores_break_and_unions(client):
    course = CourseFactory()
    student = make_student(client)  # logs the client in
    EnrollmentFactory(student=student, course=course)
    unit = seed_slideshow_unit(course, "lesson", layout=["t", "brk", "t", "t"])
    content_pks = list(
        unit.elements.exclude(
            content_type=ContentType.objects.get_for_model(SlideBreakElement)
        ).values_list("pk", flat=True)
    )
    url = reverse("courses:seen", kwargs={"slug": course.slug, "node_pk": unit.pk})
    # Two disjoint partial POSTs; union must be retained and completion reached.
    half = len(content_pks) // 2
    client.post(url, json.dumps(content_pks[:half]), content_type="application/json")
    r = client.post(url, json.dumps(content_pks[half:]), content_type="application/json")
    assert r.json()["completed"] is True
    prog = UnitProgress.objects.get(student=student, unit=unit)
    assert set(prog.seen_element_ids) == set(content_pks)  # union, not replace
```

(Confirm the `seen` URL name + kwargs in `courses/urls.py`; the plan's earlier read shows `courses:seen` with `slug`/`node_pk`.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_slideshow_seen.py -v`
Expected: FAIL — completion is False because the break pk is still in `current` and never seen.

- [ ] **Step 3: Implement the exclusion**

In `courses/views.py` `seen`, change the `current` computation to exclude breaks by content type:

```python
    from django.contrib.contenttypes.models import ContentType
    from courses.models import SlideBreakElement
    ...
    break_ct = ContentType.objects.get_for_model(SlideBreakElement)
    current = set(
        node.elements.exclude(content_type=break_ct).values_list("pk", flat=True)
    )
```

Leave the `merged = set(progress.seen_element_ids) | incoming` union untouched — the test locks it.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_slideshow_seen.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/views.py tests/test_slideshow_seen.py
git commit -m "fix(courses): exclude slide-breaks from lesson completion set"
```

---

## Task 5: Server-side quiz question numbering (replace CSS counter)

**Files:**
- Modify: `courses/views.py` `build_quiz_context` — annotate each question join-row with a 1-based `qnum` in document order.
- Modify: `templates/courses/_quiz_article.html` — render the number in the QUIZ article (the number is threaded on the quiz path only; lessons never get it).
- Modify: `courses/static/courses/css/courses.css` — remove the `quiz-q` counter rules; style `.el__qnum`.
- Test: `tests/test_slideshow_numbering.py`

**Interfaces:**
- Produces: each rendered quiz question carries its number in the markup (`data-qnum` on an `.el__qnum` span), contiguous in document order across the whole unit — so hiding a slide with `display:none` cannot renumber. Lessons carry NO `data-qnum`.

**Why not thread through `render_element`:** `.el--question` is emitted by 8 separate element templates, and `render_element` / `QuestionElement.render()` have fixed signatures with no `qnum` parameter. Rather than add a kwarg to both and edit all 8 templates, annotate the join-row and render the number in `_quiz_article.html` (just inside the `<section data-element-id>`, before `render_element`). This places the number immediately above the question card in document order — a small visual move from the old `::before` position, accepted and screenshot-verified in Step 4.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_slideshow_numbering.py
import re, pytest
from django.urls import reverse
from tests.factories import CourseFactory, EnrollmentFactory, make_student, seed_slideshow_unit


@pytest.mark.django_db
def test_quiz_numbers_in_markup_contiguous_across_break(client):
    course = CourseFactory()
    student = make_student(client)
    EnrollmentFactory(student=student, course=course)
    unit = seed_slideshow_unit(course, "quiz", layout=["q", "brk", "q", "q"])  # 3 questions
    url = reverse("courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    html = client.get(url).content.decode()
    assert re.findall(r'data-qnum="(\d+)"', html) == ["1", "2", "3"]


@pytest.mark.django_db
def test_lesson_questions_have_no_qnum(client):
    # A quiz-type question element embedded in a LESSON must NOT be numbered.
    course = CourseFactory()
    student = make_student(client)
    EnrollmentFactory(student=student, course=course)
    unit = seed_slideshow_unit(course, "lesson", layout=["q", "q"])
    url = reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    html = client.get(url).content.decode()
    assert "data-qnum" not in html
```

(Confirm the quiz/lesson take-view URL names in `courses/urls.py` — the plan's reads show `courses:quiz_unit` and `courses:lesson_unit`.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_slideshow_numbering.py -v`
Expected: FAIL (no `data-qnum` in markup — numbering is CSS-only today).

- [ ] **Step 3: Implement server-side numbering (quiz path only)**

- In `build_quiz_context`, iterate `elements` in order and set a `qnum` attribute on each join-row whose `content_object` is a `QuestionElement`, incrementing a 1-based counter (non-question join-rows get no `qnum`). Since the join-row is a live `Element` model instance, `el.qnum = n` is a transient attribute the template can read. Do this ONLY in `build_quiz_context` (not the lesson builder), so lessons never number.
- In `templates/courses/_quiz_article.html`, inside the per-element `<section data-element-id>`, before the `{% render_element ... %}` call, add:
  `{% if el.qnum %}<span class="el__qnum" data-qnum="{{ el.qnum }}">{{ el.qnum }}.</span>{% endif %}`
- In `courses.css`, DELETE the `.quiz { counter-reset: quiz-q }`, `.quiz .el--question { counter-increment: quiz-q }`, and the `content: counter(quiz-q)` `::before` rule (grep `quiz-q`), and add `.el__qnum` styling matching the previous number's weight/size/colour, light + dark. Verify the flat (non-slideshow) quiz shows the same numbers as before.

- [ ] **Step 4: Run to verify it passes + visually check**

Run: `uv run pytest tests/test_slideshow_numbering.py -v`
Expected: PASS. Then screenshot a normal (non-slideshow) quiz light+dark and confirm numbering is visually unchanged from before.

- [ ] **Step 5: Update any tests/screenshots that asserted counter-based numbering**

Run: `uv run pytest tests/ -k "quiz" -q` and fix any test that depended on the CSS counter.

- [ ] **Step 6: Commit**

```bash
git add courses/views.py courses/static/courses/css/courses.css templates tests/test_slideshow_numbering.py
git commit -m "refactor(courses): server-side quiz question numbering (display:none-safe)"
```

---

## Task 6: Article templates render slides + defensive break template

**Files:**
- Modify: `templates/courses/_lesson_article.html`, `templates/courses/_quiz_article.html`
- Create: `templates/courses/elements/slidebreakelement.html` (empty)
- Test: `tests/test_slideshow_templates.py`

**Interfaces:**
- Consumes: `slides` (Task 3).
- Produces: one `<div class="slide">` per group wrapping the existing `<section data-element-id>` blocks; the article root element carries `data-slideshow` iff `slides|length > 1`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_slideshow_templates.py
import pytest
from django.urls import reverse
from tests.factories import CourseFactory, EnrollmentFactory, make_student, seed_slideshow_unit


def _take_url(unit):
    return reverse("courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk})


@pytest.mark.django_db
def test_multi_slide_marks_article_and_wraps(client):
    course = CourseFactory()
    student = make_student(client)
    EnrollmentFactory(student=student, course=course)
    unit = seed_slideshow_unit(course, "lesson", layout=["t", "brk", "t"])  # two slides
    html = client.get(_take_url(unit)).content.decode()
    assert "data-slideshow" in html
    assert html.count('class="slide"') == 2


@pytest.mark.django_db
def test_single_slide_not_marked(client):
    course = CourseFactory()
    student = make_student(client)
    EnrollmentFactory(student=student, course=course)
    unit = seed_slideshow_unit(course, "lesson", layout=["t", "t", "brk"])  # lone trailing break
    html = client.get(_take_url(unit)).content.decode()
    assert "data-slideshow" not in html  # one slide -> flat
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_slideshow_templates.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the templates**

In `_lesson_article.html`, change the `<article class="lesson" ...>` open tag to add the attribute and wrap the loop:

```django
<article class="lesson{% if slides|length > 1 %} lesson--slideshow{% endif %}" lang="{{ course.language }}"
         data-seen-url="{% url 'courses:seen' slug=course.slug node_pk=unit.pk %}"
         {% if slides|length > 1 %}data-slideshow{% endif %}>
  ... head ...
  {% for slide in slides %}
    <div class="slide">
      {% for el in slide %}
        <section data-element-id="{{ el.pk }}" class="lesson-block">
          <div class="lesson-block__body">{% render_element el feedback_for_pk=feedback_for_pk selected_ids=selected_ids submitted_values=submitted_values mark_result=mark_result %}</div>
          {% include "notes/_block_notes.html" with element=el notes_by_element=notes_by_element unit=unit course=course notes_show=notes_show %}
        </section>
      {% endfor %}
    </div>
  {% endfor %}
  {% include "notes/_unanchored.html" with unanchored_notes=unanchored_notes course=course notes_show=notes_show %}
</article>
```

Mirror the same slides loop in `_quiz_article.html`. **Preserve the quiz-specific per-element wrapper:** the real `_quiz_article.html` wraps each `<section data-element-id>` in `{% with st=render_states|dictkey:el.pk %}…{% endwith %}` (feeding `render_element`'s `locked`/`selected_ids`/`submitted_values`/`attempts_left`/`feedback_html`). The slides loop must keep that `{% with %}` per element, AND keep Task 5's `{% if el.qnum %}<span class="el__qnum" data-qnum="{{ el.qnum }}">{{ el.qnum }}.</span>{% endif %}` inside the `<section>` before `render_element`. Do NOT copy the lesson snippet's shape verbatim — the quiz per-element body is different. Add `{% if slides|length > 1 %}data-slideshow{% endif %}` to `<article class="quiz" ...>`, and keep the `quiz-finish` form AFTER the `{% for slide %}` loop, outside every `.slide` (unchanged position). The defensive `slidebreakelement.html` template already exists (Task 1).

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_slideshow_templates.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/courses/_lesson_article.html templates/courses/_quiz_article.html tests/test_slideshow_templates.py
git commit -m "feat(courses): render units as slide groups (data-slideshow iff >1 slide)"
```

---

## Task 7: CSS slide layering + FOUC pre-hide + synchronous `.js` class

**Files:**
- Modify: `courses/static/courses/css/courses.css`
- Modify: `templates/base.html` — add `document.documentElement.classList.add('js')` to the EXISTING pre-paint `<script>` block (base.html already has one that manipulates `document.documentElement` right after `<meta charset>`; append the class-add there — NOT before the charset meta, and not deferred).
- Test: covered by the Task 8 e2e (no-JS fallback) + a template assertion here.

**Interfaces:**
- Produces: `.slide { display: contents }` default; `[data-slideshow] .slide { display: block }`; inactive slide hidden via `[data-slideshow] .slide:not(.is-active){ display:none }`; a FOUC pre-hide rule that also excludes `.is-active` so it never fights the active slide; no-JS (no `html.js`) shows all.

- [ ] **Step 1: Add the synchronous class to the existing pre-paint script**

In `templates/base.html`, find the existing inline pre-paint `<script>` (it already does `var el = document.documentElement; …` right after the `<meta charset>`/viewport tags). Add, at the top of that script body:

```js
document.documentElement.classList.add('js');
```

(Reuse the existing synchronous block so `html.js` is set before first paint; do NOT insert a new script before `<meta charset>`.)

- [ ] **Step 2: Add the CSS**

In `courses.css`:

```css
/* Slideshow: .slide is invisible-by-default in non-slideshow units (display:contents
   makes the wrapper vanish from the box tree — inner sections behave as today). */
.slide { display: contents; }

/* A paginating unit turns each slide into a real block the client shows one at a time. */
[data-slideshow] .slide { display: block; }

/* Recommended hide: display:none is IntersectionObserver-safe and scroll-safe. The
   active slide is marked by slideshow.js; inactive ones collapse. */
[data-slideshow] .slide:not(.is-active) { display: none; }

/* FOUC pre-hide: before deferred slideshow.js runs, hide non-first slides when JS is
   on. CRITICAL: this MUST also exclude .is-active, or once JS navigates to slide 2+
   (adding .is-active), this higher-specificity rule would keep the active slide hidden
   and Prev/Next would appear to do nothing. No-JS (no html.js) leaves all slides
   visible = flat page. */
html.js [data-slideshow] .slide:not(:first-child):not(.is-active) { display: none; }
```

Also add `.slideshow-bar` control-bar styling (flex row, Prev/counter/Next; disabled-button state; light+dark tokens) — bespoke, matching the app's existing button/token styles.

- [ ] **Step 3: Verify no-JS fallback via a template render assertion**

Add to `test_slideshow_templates.py`: render a 2-slide unit and confirm the server markup applies NO hiding attribute/class (all `.slide` present, none carry `is-active`/`hidden` server-side) — hiding is JS-only.

- [ ] **Step 4: Commit**

```bash
git add templates/base.html courses/static/courses/css/courses.css tests/test_slideshow_templates.py
git commit -m "feat(courses): slide CSS layering + FOUC pre-hide + html.js class"
```

---

## Task 8: `slideshow.js` core — pagination, counter, keyboard, guards

**Files:**
- Create: `courses/static/courses/js/slideshow.js`
- Modify: `templates/courses/lesson_unit.html`, `templates/courses/quiz_unit.html` (load the script, deferred; inline `window.SLIDESHOW_I18N`)
- Test: `tests/test_e2e_slideshow.py` (Python `pytest-playwright`; see Test Infrastructure — NOT a JS `e2e/` spec)

(Control-bar chevrons are inline SVG built in `slideshow.js`, so no icon-sprite change is needed — the sprite isn't loaded on taking pages.)

**Interfaces:**
- Produces: on a `[data-slideshow]` article, a control bar `◀ Prev · N / total · Next ▶` inserted after the last `.slide`; slide 0 active on load; free Prev/Next (disabled at ends); counter `role=status` `aria-live=polite`; arrow-key nav that bails on form-control/editable targets; scroll-new-slide-top; no-op when `≤1` slide.

- [ ] **Step 1: Write the failing e2e test**

```python
# tests/test_e2e_slideshow.py  (Python pytest-playwright — mirror tests/test_e2e_html_element.py)
import os
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)  # from tests.factories
    form.locator("button[type='submit']").click()


def test_prev_next_paginate_and_counter(page, live_server):
    student, path = _seed_slideshow_lesson_3(username="s1")  # helper: enrolled lesson, 3 slides
    _login(page, live_server, "s1")
    page.goto(f"{live_server.url}{path}")
    expect(page.locator(".slideshow-bar")).to_be_visible()
    expect(page.locator("[data-slideshow-counter]")).to_have_text("1 / 3")
    expect(page.locator(".slide.is-active")).to_have_count(1)
    page.get_by_role("button", name="Next").click()
    expect(page.locator("[data-slideshow-counter]")).to_have_text("2 / 3")
    page.get_by_role("button", name="Next").click()
    expect(page.get_by_role("button", name="Next")).to_be_disabled()


def test_arrow_in_text_field_does_not_change_slide(page, live_server):
    student, path = _seed_slideshow_quiz_text("s2")  # quiz, slide 0 has a short-text question
    _login(page, live_server, "s2")
    page.goto(f"{live_server.url}{path}")
    field = page.locator(".slide.is-active input[type=text]").first
    field.click()
    field.press("ArrowRight")
    expect(page.locator("[data-slideshow-counter]")).to_have_text("1 / 3")


def test_arrow_in_select_or_radio_does_not_change_slide(page, live_server):
    # Non-caret answer control: arrows change the control's own selection, NOT the slide.
    student, path = _seed_slideshow_quiz_choice("s3")  # quiz, slide 0 has a radio/select answer
    _login(page, live_server, "s3")
    page.goto(f"{live_server.url}{path}")
    ctrl = page.locator(".slide.is-active input[type=radio], .slide.is-active select").first
    ctrl.focus()
    ctrl.press("ArrowDown")
    expect(page.locator("[data-slideshow-counter]")).to_have_text("1 / 3")


def test_arrow_on_bar_advances_slide(page, live_server):
    # Positive case: arrows DO paginate when focus is on the control bar / non-editable content.
    student, path = _seed_slideshow_lesson_3("s4")
    _login(page, live_server, "s4")
    page.goto(f"{live_server.url}{path}")
    page.get_by_role("button", name="Next").focus()
    page.keyboard.press("ArrowRight")
    expect(page.locator("[data-slideshow-counter]")).to_have_text("2 / 3")


def test_single_slide_no_control_bar(page, live_server):
    student, path = _seed_slideshow_lesson_single("s5")  # lone trailing break -> one slide
    _login(page, live_server, "s5")
    page.goto(f"{live_server.url}{path}")
    expect(page.locator(".slideshow-bar")).to_have_count(0)
```

Add the `_seed_slideshow_*` helpers in the same file (build course + `EnrollmentFactory` + units via `add_element`/`seed_slideshow_unit`, return `(user, url_path)`). Accessible name for the buttons is the visible `<span>` label ("Next"/"Prev") — match the actual translated string (default EN "Next").

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_e2e_slideshow.py -m e2e`
Expected: FAIL (no control bar / `slideshow.js` not written).

- [ ] **Step 3: Implement `slideshow.js`**

```js
(function () {
  "use strict";
  var article = document.querySelector("[data-slideshow]");
  if (!article) return;
  var slides = Array.prototype.slice.call(article.querySelectorAll(".slide"));
  if (slides.length <= 1) return; // degenerate guard (belt-and-suspenders)

  var i18n = window.SLIDESHOW_I18N || { prev: "Prev", next: "Next" };
  var idx = 0;

  // Icon buttons use INLINE monochrome currentColor line SVG (matching base.html's
  // inline-icon convention). NOT a sprite <use href="#..."> — the icon sprite
  // (templates/courses/manage/_icon_sprite.html) is included ONLY on the editor/builder
  // pages, NOT on the student taking pages where this control bar lives, so a <use>
  // reference would render blank. NOT unicode glyphs either. The visible <span> label
  // gives the button its accessible name (so page.get_by_role("button", name=...) still
  // matches). Chevron paths: left "M15 6l-6 6 6 6", right "M9 6l6 6-6 6".
  function iconBtn(cls, pathD, label, iconFirst) {
    var b = document.createElement("button");
    b.type = "button"; b.className = cls;
    var svg = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
              'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
              'aria-hidden="true" focusable="false"><path d="' + pathD + '"/></svg>';
    var lbl = document.createElement("span"); lbl.textContent = label;
    if (iconFirst) { b.insertAdjacentHTML("beforeend", svg); b.appendChild(lbl); }
    else { b.appendChild(lbl); b.insertAdjacentHTML("beforeend", svg); }
    return b;
  }

  var bar = document.createElement("nav");
  bar.className = "slideshow-bar";
  bar.setAttribute("aria-label", i18n.nav || "Slides");
  var prev = iconBtn("slideshow-bar__prev", "M15 6l-6 6 6 6", i18n.prev, true);
  var counter = document.createElement("span");
  counter.className = "slideshow-bar__counter";
  counter.setAttribute("data-slideshow-counter", "");
  counter.setAttribute("role", "status");
  counter.setAttribute("aria-live", "polite");
  var next = iconBtn("slideshow-bar__next", "M9 6l6 6-6 6", i18n.next, false);
  bar.appendChild(prev); bar.appendChild(counter); bar.appendChild(next);
  slides[slides.length - 1].after(bar); // after last slide, above trailing Finish/notes

  function show(n) {
    idx = Math.max(0, Math.min(slides.length - 1, n));
    slides.forEach(function (s, k) {
      var active = k === idx;
      s.classList.toggle("is-active", active);
      s.toggleAttribute("hidden", !active);
      if (active) { s.setAttribute("tabindex", "-1"); }
    });
    counter.textContent = (idx + 1) + " / " + slides.length;
    prev.disabled = idx === 0;
    next.disabled = idx === slides.length - 1;
    onReveal(slides[idx]);           // Task 9/10 hooks
    slides[idx].scrollIntoView({ block: "start" });
    try { slides[idx].focus(); } catch (e) {}
  }

  function onReveal(slide) { /* extended in Task 9 (mark-seen) + Task 10 (relayout, Finish) */ }

  prev.addEventListener("click", function () { show(idx - 1); });
  next.addEventListener("click", function () { show(idx + 1); });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    var t = e.target;
    var tag = t && t.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" ||
        (t && t.isContentEditable) || tag === "MATH-FIELD") return; // arrows meaningful in fields
    if (!article.contains(t) && !bar.contains(t)) return;
    e.preventDefault();
    show(idx + (e.key === "ArrowRight" ? 1 : -1));
  });

  show(0); // initial reveal
})();
```

- [ ] **Step 4: Load the script + i18n strings**

In `lesson_unit.html` and `quiz_unit.html` `{% block extra_js %}`, add `<script src="{% static 'courses/js/slideshow.js' %}" defer></script>` and a small inline `window.SLIDESHOW_I18N = { prev: "{% trans 'Prev' %}", next: "{% trans 'Next' %}", nav: "{% trans 'Slides' %}" };` (translated) BEFORE the deferred script tag.

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_e2e_slideshow.py -m e2e`. Expected: PASS (nav, both arrow guards, positive-advance, single-slide).

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/slideshow.js templates/courses/lesson_unit.html templates/courses/quiz_unit.html tests/test_e2e_slideshow.py
git commit -m "feat(courses): slideshow.js pagination, counter, keyboard guard"
```

---

## Task 9: Lesson mark-seen-on-reveal (batched union POST)

**Files:**
- Modify: `courses/static/courses/js/slideshow.js` (`onReveal`)
- Test: add to `tests/test_e2e_slideshow.py`

**Interfaces:**
- Produces: on each reveal (including initial slide 0), if the article has `data-seen-url` (lessons only), POST that slide's `data-element-id` pks as a JSON array to the seen endpoint (batched, idempotent). On a `{completed: true}` response, `slideshow.js` deterministically flips the completion pill itself (does not rely on `progress.js` timing). Quizzes (no `data-seen-url`) do nothing.

- [ ] **Step 1: Write the failing e2e test (append to `tests/test_e2e_slideshow.py`)**

```python
def test_lesson_completes_after_paging_tall_slides(page, live_server):
    # slide 0 is taller than the viewport; the student never scrolls, only pages.
    student, path = _seed_slideshow_lesson_tall("s6")  # 3 slides, slide 0 tall
    _login(page, live_server, "s6")
    page.goto(f"{live_server.url}{path}")
    page.get_by_role("button", name="Next").click()
    page.get_by_role("button", name="Next").click()
    expect(page.locator("[data-unit-done]")).to_have_class(__import__("re").compile(r"is-complete"))
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_e2e_slideshow.py -m e2e -k tall`
Expected: FAIL (bottom of the tall slide never seen; pill never flips).

- [ ] **Step 3: Implement `onReveal` seen reporting (deterministic pill flip)**

```js
  var seenUrl = article.getAttribute("data-seen-url"); // lessons only; quizzes lack it
  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }
  // Flip the completion pill directly on a completed response, so slideshow-driven
  // completion (tall slide, no scroll) is deterministic and does not depend on
  // progress.js's IntersectionObserver timing. Mirrors progress.js markDone().
  function markDone() {
    var c = document.querySelector("[data-unit-done]");
    if (!c || c.classList.contains("is-complete")) return;
    c.classList.add("is-complete");
    var label = c.getAttribute("data-done-label") || "Completed";
    c.innerHTML =
      '<span class="unit-done__pill"><span class="unit-done__check" aria-hidden="true">' +
      "✓</span> " + label + "</span>";
  }
  function markSlideSeen(slide) {
    if (!seenUrl) return; // quiz page: no seen path
    var pks = Array.prototype.map.call(
      slide.querySelectorAll("[data-element-id]"),
      function (el) { return parseInt(el.getAttribute("data-element-id"), 10); }
    ).filter(function (n) { return !isNaN(n); });
    if (!pks.length) return;
    fetch(seenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify(pks),
      keepalive: true,
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && d.completed) markDone(); })
      .catch(function () {});
  }
```

Call `markSlideSeen(slide)` from `onReveal`. Because the server unions pks (Task 4) and `progress.js` also posts, double-firing is idempotent. (The `markDone` here duplicates `progress.js`'s pill logic deliberately — that IIFE exposes no hook; keep the two in sync if either changes.)

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_e2e_slideshow.py -m e2e -k tall`
Expected: PASS (completion + pill flip without scrolling).

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/slideshow.js tests/test_e2e_slideshow.py
git commit -m "feat(courses): mark whole slide seen on reveal (lesson, deterministic completion)"
```

---

## Task 10: Quiz Finish gating + widget relayout on reveal

**Files:**
- Modify: `courses/static/courses/js/slideshow.js` (`onReveal`)
- Test: append to `tests/test_e2e_slideshow.py` (Python pytest-playwright)

**Interfaces:**
- Produces: on quiz pages, the `[data-quiz-finish]` form is hidden until the last slide is active; on every reveal a `resize` event is dispatched so MathLive/GeoGebra widgets re-measure.

- [ ] **Step 1: Write the failing e2e test (append to `tests/test_e2e_slideshow.py`)**

```python
def test_finish_hidden_until_last_slide(page, live_server):
    student, path = _seed_slideshow_quiz_3("s7")  # quiz, 3 slides
    _login(page, live_server, "s7")
    page.goto(f"{live_server.url}{path}")
    expect(page.locator("[data-quiz-finish]")).to_be_hidden()
    page.get_by_role("button", name="Next").click()
    page.get_by_role("button", name="Next").click()
    expect(page.locator("[data-quiz-finish]")).to_be_visible()


def test_math_widget_on_slide_2_renders_at_width(page, live_server):
    student, path = _seed_slideshow_quiz_math("s8")  # math-field on slide 2
    _login(page, live_server, "s8")
    page.goto(f"{live_server.url}{path}")
    page.get_by_role("button", name="Next").click()
    box = page.locator(".slide.is-active math-field").first.bounding_box()
    assert box["width"] > 50  # not collapsed to ~0 (relayout fired)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_e2e_slideshow.py -m e2e -k "finish or math"`
Expected: FAIL (Finish visible early; widget may be collapsed).

- [ ] **Step 3: Implement**

Extend `onReveal`:

```js
  var finish = document.querySelector("[data-quiz-finish]"); // quiz only; null on lessons
  function updateFinish() {
    if (finish) finish.toggleAttribute("hidden", idx !== slides.length - 1);
  }
  // in onReveal(slide):
  //   markSlideSeen(slide);
  //   updateFinish();
  //   window.dispatchEvent(new Event("resize")); // GeoGebra/MathLive re-measure
```

Ensure `updateFinish()` runs on load (initial `show(0)` hides Finish unless there is only one slide — but single-slide units don't reach here due to the guard, and a genuine multi-slide quiz correctly hides Finish until the end).

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_e2e_slideshow.py -m e2e -k "finish or math"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/slideshow.js tests/test_e2e_slideshow.py
git commit -m "feat(courses): quiz Finish gating on last slide + widget relayout on reveal"
```

---

## Task 11: `SlideBreakElementForm` + create wiring

**Files:**
- Modify: `courses/element_forms.py` (add `SlideBreakElementForm`, register in `FORM_FOR_TYPE` under key `"slidebreak"`)
- Modify: `courses/views_manage.py` (`_EDITOR_TYPE_LABELS`; add `"slidebreak"` to `element_save`'s allowed tuple ONLY)
- Test: `tests/test_slideshow_builder.py`

**CRITICAL naming note:** the builder namespace derives a type key from the model name via `el.content_object.__class__.__name__.lower().replace("element", "")` (see `courses/views_manage.py:935`, the element-edit path). For `SlideBreakElement` that yields **`"slidebreak"`** (no underscore). So ALL builder-side registrations use `"slidebreak"`. The underscored `"slide_break"` is a DIFFERENT namespace used only by the transfer registries (Task 13) — do not mix them.

**Interfaces:**
- Consumes: `save_element` generic branch (`FORM_FOR_TYPE[type_key](...).save()`).
- Produces: a field-less `SlideBreakElementForm`; builder key `"slidebreak"` accepted by `element_save` and creates a `SlideBreakElement` + `Element` join-row.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_slideshow_builder.py
import pytest
from courses.builder import save_element
from courses.models import SlideBreakElement
from tests.factories import make_quiz_unit


@pytest.mark.django_db
def test_save_element_creates_slide_break():
    unit = make_quiz_unit()  # a quiz unit; save_element takes (course, unit_pk, type_key, ref, post, files)
    post = {"unit_token": unit.updated.isoformat()}
    save_element(unit.course, unit.pk, "slidebreak", "new", post, {})
    assert any(isinstance(j.content_object, SlideBreakElement) for j in unit.elements.all())
```

(Confirm `make_quiz_unit()`'s return + that `unit.updated` is the token source `save_element` checks; if `make_quiz_unit` needs a course arg, pass one from `CourseFactory`.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_slideshow_builder.py -v`
Expected: FAIL (KeyError: 'slidebreak' in FORM_FOR_TYPE).

- [ ] **Step 3: Implement the form + registration**

In `courses/element_forms.py`:

```python
class SlideBreakElementForm(forms.ModelForm):
    class Meta:
        model = SlideBreakElement
        fields = []  # field-less: a break has nothing to edit
```

Add to `FORM_FOR_TYPE`: `"slidebreak": SlideBreakElementForm,`.

In `courses/views_manage.py`:
- Add `"slidebreak": gettext_lazy("Slide break"),` to `_EDITOR_TYPE_LABELS`.
- Add `"slidebreak"` to **`element_save`'s** allowed-type tuple ONLY. Do **NOT** add it to `element_add`'s tuple: `element_add` → `_render_open_form` → includes `courses/manage/editor/_edit_slidebreak.html`, which does not exist and would raise `TemplateDoesNotExist`. The break is created exclusively via Task 12's direct `element_save` POST (no editor pane).
- The generic `save_element` branch handles it: `FORM_FOR_TYPE["slidebreak"](data=post).save()` creates the row (`type_key not in ("image", "video")`, so no `course` extra).

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_slideshow_builder.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/element_forms.py courses/views_manage.py tests/test_slideshow_builder.py
git commit -m "feat(courses): field-less SlideBreakElementForm + save_element wiring"
```

---

## Task 12: Builder palette entry, divider row, direct-create, legend, icon

**Files:**
- Modify: `templates/courses/manage/editor/_add_menu.html` (palette entry)
- Modify: `templates/courses/manage/editor/_element_row.html` (render a break as a thin divider row, not a content card)
- Modify: the icon sprite (find the `<symbol id="el-...">` definitions; add `#el-slidebreak`, a monochrome line SVG)
- Modify: the editor JS (find the `data-add-type` handler) so `slidebreak` creates directly (POST to `element_save`) instead of opening an editor; and the builder legend text.
- Test: append to `tests/test_e2e_slideshow.py` (Python pytest-playwright; author adds a break, sees a divider row)

**Interfaces:**
- Produces: a "Slide break" palette button (`data-add-type="slidebreak"`); clicking it inserts a break row directly (no editor); the row renders as a divider; a legend note explains it.

- [ ] **Step 1: Write the failing e2e test (append to `tests/test_e2e_slideshow.py`; mirror `tests/test_e2e_builder*.py` for the author-login + builder-URL seed)**

```python
def test_author_adds_slide_break_divider_row(page, live_server):
    author, path = _seed_builder_unit("author1")  # PA/author + a unit in the builder; return builder URL
    _login(page, live_server, "author1")
    page.goto(f"{live_server.url}{path}")
    page.locator("[data-add-toggle]").click()
    page.locator('[data-add-type="slidebreak"]').click()
    expect(page.locator(".element-row--slidebreak, [data-slidebreak-row]")).to_have_count(1)
```

(Model `_seed_builder_unit` + the author login on `tests/test_e2e_builder.py` / `test_e2e_builder_authoring.py`.)

- [ ] **Step 2: Run to verify it fails.** Run `uv run pytest tests/test_e2e_slideshow.py -m e2e -k break`. Expected: FAIL (no palette entry).

- [ ] **Step 3: Implement**

- **Palette:** in `_add_menu.html`, add a small "Structure" group (or append to Content) with:
  `<button type="button" class="typecard" data-add-type="slidebreak"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-slidebreak"/></svg>{% trans "Slide break" %}</button>`
- **Icon:** add an `#el-slidebreak` symbol to the sprite (a horizontal dashed rule / divider, `currentColor`, `stroke` line style matching siblings).
- **Direct-create (with the unit token):** in the editor JS, special-case `data-add-type="slidebreak"`: instead of the normal add→open-editor flow, POST directly to the element-save endpoint. First read the required inputs from the editor pane DOM — the save URL from `[data-scope="editor"]`'s `data-save-url` and the unit token from its `data-updated` (this is `unit.updated.isoformat()`; `save_element` calls `_check_token(unit.updated, post_data.get("unit_token"))` and a missing/stale token 409s). POST `type=slidebreak`, `unit=<unit pk>`, `element=new`, `unit_token=<data-updated>` (plus CSRF), then refresh the element-list fragment exactly as the existing save flow does. Inspect the current `data-add-type` handler + the save flow to match request shape and field names precisely.
- **Divider row:** in `_element_row.html`, detect a break (`el.content_object` is a `SlideBreakElement`) and render a compact divider row — a labelled horizontal rule ("— Slide break —") with the existing reorder/delete controls, and NO edit affordance — instead of the standard content card. Give it a stable hook (`class="element-row--slidebreak"` or `data-slidebreak-row`).
- **Legend:** add a one-line note near the builder legend: `{% trans "Add a slide break to split this unit into a slideshow." %}`

- [ ] **Step 4: Run to verify it passes.** Expected: PASS. Screenshot the builder (light+dark) and confirm the divider row + palette entry read cleanly.

- [ ] **Step 5: Commit**

```bash
git add templates/courses/manage/editor/ courses/static tests/test_e2e_slideshow.py
git commit -m "feat(courses): builder slide-break palette, divider row, direct-create, legend"
```

---

## Task 13: Transfer round-trip (three registries)

**Files:**
- Modify: `courses/transfer/export.py` (`SERIALIZERS` + `_ser_slide_break`)
- Modify: `courses/transfer/payloads.py` (`VALIDATORS` + `_val_slide_break`)
- Modify: `courses/transfer/importer.py` (`BUILDERS` + `_build_slide_break`)
- Test: `tests/test_slideshow_transfer.py`

**Interfaces:**
- Produces: `slide_break` key registered in all THREE lockstep registries; export→import preserves breaks (and thus slideshow-ness).

- [ ] **Step 1: Write the failing test**

The transfer API (verified): export via `write_archive(course, node, fileobj)`; import via `open_archive(...)` — a **`@contextmanager` yielding a 4-tuple `(zf, manifest, document, media_entries)`** — then `validate_archive_document(zf, mani, doc, media, kind=..., target_course=...)` then `import_course(zf, mani, doc, media, user)`. Copy the exact call sequence from `tests/test_transfer_import.py:56-60` (`_import_zip` helper) — do NOT unpack `open_archive` without `with`, and pass `zf` (not `buf`) to `import_course`.

```python
# tests/test_slideshow_transfer.py
import io, pytest
from courses.models import SlideBreakElement
from courses.transfer.export import write_archive
from courses.transfer.importer import open_archive, import_course
from courses.transfer.schema import validate_archive_document  # confirm the import path
from tests.factories import CourseFactory, make_login, seed_slideshow_unit


@pytest.mark.django_db
def test_export_import_preserves_slide_break(client):
    src = CourseFactory()
    seed_slideshow_unit(src, "lesson", layout=["t", "brk", "t"])
    buf = io.BytesIO()
    write_archive(src, None, buf)  # whole-course export; confirm signature vs existing tests
    buf.seek(0)
    owner = make_login(client, "importer")
    with open_archive(buf, expected_kind="course") as (zf, mani, doc, media):
        validate_archive_document(zf, mani, doc, media, kind="course", target_course=None)
        dest = import_course(zf, mani, doc, media, owner)
    assert any(
        isinstance(j.content_object, SlideBreakElement)
        for node in dest.nodes.all()
        for j in node.elements.all()
    )
```

(Reconcile `validate_archive_document`'s import path + args against `tests/test_transfer_import.py`; the `_import_zip` helper there is the exact pattern to mirror.)

**Before writing:** open `tests/test_transfer_export.py` / `tests/test_transfer_archive.py` and copy their exact export→archive→open→import call sequence and return unpacking — the signatures above are from a grep and MUST be reconciled with how the existing tests actually invoke them (e.g. `open_archive` vs `read_archive`, the manifest/document/media tuple order).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_slideshow_transfer.py -v`
Expected: FAIL (export raises `TransferError: Unserializable element model: SlideBreakElement`).

- [ ] **Step 3: Implement the three registrations**

- `export.py`: add serializer + registry entry:

```python
def _ser_slide_break(concrete, media_ids):
    return {}  # field-less

# in SERIALIZERS:
    "slide_break": (SlideBreakElement, _ser_slide_break),
```
(import `SlideBreakElement` at the top with the other element models.)

- `payloads.py`: add validator + registry entry:

```python
def _val_slide_break(data, elid, media_kinds):
    return {}  # no fields to validate

# in VALIDATORS:
    "slide_break": _val_slide_break,
```

- `importer.py`: add builder + registry entry:

```python
def _build_slide_break(data, assets):
    from courses.models import SlideBreakElement
    return SlideBreakElement.objects.create(), []  # (concrete, child_rows)

# in BUILDERS:
    "slide_break": _build_slide_break,
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_slideshow_transfer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/transfer/ tests/test_slideshow_transfer.py
git commit -m "feat(courses): register slide_break in export/validate/import registries"
```

---

## Task 14: Registry sweep, i18n catalogs, full-suite DoD

**Files:**
- Modify: any remaining element-type maps found by the sweep (label/icon/choices/admin).
- Modify: `locale/*/LC_MESSAGES/django.po` (EN default + PL) — new strings ("Slide break", "Prev", "Next", "Slides", legend note).
- Test: full suite + i18n catalog tests.

- [ ] **Step 1: Registry sweep**

Run and inspect: `grep -rn "shorttextquestion\|dragtoimagequestion\|el--question\|_MODEL_TO_KEY\|type_key" courses/ templates/` plus `grep -rn "ELEMENT_MODELS\|SERIALIZERS\|VALIDATORS\|BUILDERS\|FORM_FOR_TYPE\|_EDITOR_TYPE_LABELS" courses/`. For each map that enumerates element types (including any `admin.py` registration, analytics type maps, icon maps), confirm `slide_break`/`SlideBreakElement` is added or intentionally excluded (e.g. analytics/scoring already skip non-`QuestionElement`, so no entry needed — but verify no `KeyError` path). Document exclusions in a comment.

- [ ] **Step 2: Generate + translate catalogs**

Run: `uv run python manage.py makemessages -l pl -l en` (match the repo's locale set). Fill in PL translations for every new string. Do NOT leave fuzzy flags; remove obsolete `#~` entries. Then `uv run python manage.py compilemessages`.

- [ ] **Step 3: Register the SlideBreakElement in admin if the pattern requires it**

If `courses/admin.py` registers each element model, add `SlideBreakElement` (or confirm it is intentionally unregistered). Match the existing pattern.

- [ ] **Step 4: Full-suite Definition of Done**

Run, and all must pass:
```
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
uv run pytest -q
```
Run the i18n catalog tests specifically (the repo has tests asserting no obsolete `#~` / no missing translations) — this build ADDS strings (doesn't remove), but run them to be safe. Then run the full Playwright e2e suite.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(courses): slide-break registry sweep + EN/PL catalogs"
```

---

## Self-Review Notes (coverage map)

- Spec §1 (model, ELEMENT_MODELS, registry sweep) → Tasks 1, 14. (`is_slideshow` property intentionally NOT built — no consumer; see Task 1 note.)
- Spec §2 (partition, slides context, div.slide, data-slideshow>1 gate, hide mechanism, server-side numbering, widget relayout) → Tasks 2, 3, 5, 6, 7, 10.
- Spec §3 (slideshow.js: control bar, counter aria-live, free nav, keyboard guard, degenerate guard, scroll, FOUC, Finish gating, mark-seen) → Tasks 7, 8, 9, 10.
- Spec §4 (builder palette, create pipeline, divider row, legend) → Tasks 11, 12.
- Data flow + Progress completion (seen exclusion, union, lesson-only, data-seen-url gate) → Tasks 4, 9.
- Error handling (defensive template, transfer 3 registries, scoring skip) → Tasks 6, 13, 14.
- Testing (unit/view/template/e2e incl. contiguous numbering, tall slide 0, single-slide, arrow-in-input incl. radio/select, widget relayout, export/import) → distributed across Tasks 2–14.

**Known deviation from spec text:** the spec called the transfer path a "dual registry (export.py + schema.py)"; the actual codebase has THREE lockstep registries — `export.py SERIALIZERS`, `payloads.py VALIDATORS`, `importer.py BUILDERS`. Task 13 registers all three (this is the correct, verified shape).
