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

## File Structure

- **Create** `courses/slideshow.py` — pure `partition_into_slides(elements)` helper.
- **Create** `courses/migrations/00NN_slidebreakelement.py` — new model (auto-generated).
- **Create** `templates/courses/elements/slidebreakelement.html` — defensive empty render template.
- **Create** `courses/static/courses/js/slideshow.js` — client pagination.
- **Modify** `courses/models.py` — `SlideBreakElement`, `ELEMENT_MODELS`, `ContentNode.is_slideshow` property.
- **Modify** `courses/views.py` — `build_lesson_context`/`build_quiz_context` add `slides`; `seen` view excludes breaks.
- **Modify** `courses/element_forms.py` — `SlideBreakElementForm`, `FORM_FOR_TYPE`.
- **Modify** `courses/views_manage.py` — `_EDITOR_TYPE_LABELS`, the two allowed-type tuples, direct-create path for the break.
- **Modify** `templates/courses/_lesson_article.html`, `templates/courses/_quiz_article.html` — slides loop.
- **Modify** the quiz question template/partial + `courses/static/courses/css/courses.css` — server-side numbering + `.slide` layering + FOUC.
- **Modify** `templates/courses/quiz_unit.html`, `templates/courses/lesson_unit.html` (+ any shared head) — load `slideshow.js`, synchronous `.js` root class.
- **Modify** `templates/courses/manage/editor/_add_menu.html`, `_element_row.html` (+ icon sprite) — palette entry + divider row + legend.
- **Modify** `courses/transfer/export.py`, `courses/transfer/payloads.py`, `courses/transfer/importer.py` — register `slide_break` in all three registries.
- **Tests** under `courses/tests/` (unit/view/template) and `e2e/` (Playwright), matching existing locations.

---

## Task 1: `SlideBreakElement` model + registration

**Files:**
- Modify: `courses/models.py` (add to `ELEMENT_MODELS`; add `SlideBreakElement`; add `ContentNode.is_slideshow`)
- Create: `courses/migrations/00NN_slidebreakelement.py` (via makemigrations)
- Test: `courses/tests/test_slideshow_model.py`

**Interfaces:**
- Produces: `SlideBreakElement(ElementBase)` — no content fields, `elements = GenericRelation(Element)`. `"slidebreakelement"` present in `ELEMENT_MODELS`. `ContentNode.is_slideshow` → bool (has ≥1 break among prefetched elements).

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_slideshow_model.py
import pytest
from django.contrib.contenttypes.models import ContentType
from courses.models import ELEMENT_MODELS, Element, SlideBreakElement


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

Run: `uv run pytest courses/tests/test_slideshow_model.py -v`
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

Add the `is_slideshow` property to `ContentNode` (used by non-taking consumers only; the taking articles gate on `slides|length`):

```python
    @property
    def is_slideshow(self):
        """True iff this unit contains at least one slide-break element.

        Iterates the prefetched `elements` (call after prefetch_related to avoid a
        query); a break's content_object is a SlideBreakElement."""
        return any(
            isinstance(el.content_object, SlideBreakElement)
            for el in self.elements.all()
        )
```

- [ ] **Step 4: Generate + run the migration**

Run: `uv run python manage.py makemigrations courses`
Expected: a new migration creating `SlideBreakElement`. Then `uv run python manage.py migrate`.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_slideshow_model.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add courses/models.py courses/migrations courses/tests/test_slideshow_model.py
git commit -m "feat(courses): SlideBreakElement field-less delimiter + is_slideshow"
```

---

## Task 2: `partition_into_slides` pure helper

**Files:**
- Create: `courses/slideshow.py`
- Test: `courses/tests/test_slideshow_partition.py`

**Interfaces:**
- Produces: `partition_into_slides(elements) -> list[list[Element]]`. Input is an ordered list of `Element` join-rows (with `content_object` available). Splits on any join-row whose `content_object` is a `SlideBreakElement`; drops empty groups; breaks are omitted from output. A list with no breaks → `[elements]` (one slide) when non-empty, else `[]`. Output holds the SAME `Element` join-row objects (identity preserved, never unwrapped to `content_object`).

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_slideshow_partition.py
import pytest
from courses.models import Element, SlideBreakElement, TextElement
from courses.slideshow import partition_into_slides
from courses.tests.factories import make_unit  # existing helper; see note below


def _text_join(unit, order):
    return Element.objects.create(unit=unit, content_object=TextElement.objects.create(body="x"), order=order)


def _break_join(unit, order):
    return Element.objects.create(unit=unit, content_object=SlideBreakElement.objects.create(), order=order)


@pytest.mark.django_db
def test_no_breaks_single_slide(course_unit):
    els = [_text_join(course_unit, 0), _text_join(course_unit, 1)]
    slides = partition_into_slides(els)
    assert slides == [els]  # identity preserved


@pytest.mark.django_db
def test_split_and_identity(course_unit):
    a, b = _text_join(course_unit, 0), _text_join(course_unit, 1)
    brk = _break_join(course_unit, 2)
    c = _text_join(course_unit, 3)
    slides = partition_into_slides([a, b, brk, c])
    assert slides == [[a, b], [c]]
    assert brk not in slides[0] and brk not in slides[1]  # break consumed


@pytest.mark.django_db
def test_leading_trailing_consecutive_breaks_drop_empties(course_unit):
    b0 = _break_join(course_unit, 0)
    a = _text_join(course_unit, 1)
    b1 = _break_join(course_unit, 2)
    b2 = _break_join(course_unit, 3)
    c = _text_join(course_unit, 4)
    b3 = _break_join(course_unit, 5)
    slides = partition_into_slides([b0, a, b1, b2, c, b3])
    assert slides == [[a], [c]]  # no empty slides


@pytest.mark.django_db
def test_only_breaks_yields_no_slides(course_unit):
    slides = partition_into_slides([_break_join(course_unit, 0), _break_join(course_unit, 1)])
    assert slides == []


@pytest.mark.django_db
def test_empty_input(course_unit):
    assert partition_into_slides([]) == []
```

Note: use whatever unit/course fixture the repo already provides (search `courses/tests/` for an existing `course_unit`/`make_unit` fixture; if none, build a `ContentNode` unit inline via the existing factories in `courses/tests/factories.py`). Do NOT introduce a new global fixture if one exists.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_slideshow_partition.py -v`
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

Run: `uv run pytest courses/tests/test_slideshow_partition.py -v`
Expected: PASS (all 5).

- [ ] **Step 5: Commit**

```bash
git add courses/slideshow.py courses/tests/test_slideshow_partition.py
git commit -m "feat(courses): partition_into_slides helper (split on break, drop empties)"
```

---

## Task 3: Context builders add `slides`

**Files:**
- Modify: `courses/views.py` (`build_lesson_context`, `build_quiz_context`)
- Test: `courses/tests/test_slideshow_context.py`

**Interfaces:**
- Consumes: `partition_into_slides` (Task 2).
- Produces: both context dicts gain `"slides"` (list of lists of `Element` join-rows). No `is_slideshow` key is added to the taking context (the render gate is `slides|length`).

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_slideshow_context.py
import pytest
from courses.models import Element, SlideBreakElement, TextElement
from courses.views import build_lesson_context, build_quiz_context
# Use existing helpers to build a lesson unit, a quiz unit, and an enrolled user.


@pytest.mark.django_db
def test_lesson_context_slides(lesson_unit_with_break, student):
    # unit: text, break, text  -> two slides
    ctx = build_lesson_context(lesson_unit_with_break, student)
    assert [len(s) for s in ctx["slides"]] == [1, 1]
    assert "is_slideshow" not in ctx  # taking context gates on slide count only


@pytest.mark.django_db
def test_quiz_context_single_slide_when_no_break(quiz_unit_no_break, student):
    ctx = build_quiz_context(quiz_unit_no_break, student)
    assert len(ctx["slides"]) == 1
    assert len(ctx["slides"][0]) == len(ctx["elements"])
```

(Build `lesson_unit_with_break`, `quiz_unit_no_break`, `student` from existing factories; a break is `Element.objects.create(unit=unit, content_object=SlideBreakElement.objects.create(), order=N)`.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_slideshow_context.py -v`
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

Run: `uv run pytest courses/tests/test_slideshow_context.py -v`
Expected: PASS.

- [ ] **Step 5: Run the broader view suite for regressions**

Run: `uv run pytest courses/tests/ -k "lesson or quiz" -q`
Expected: PASS (no regressions from the added key).

- [ ] **Step 6: Commit**

```bash
git add courses/views.py courses/tests/test_slideshow_context.py
git commit -m "feat(courses): context builders emit slides via partition_into_slides"
```

---

## Task 4: `seen` view excludes breaks + union-semantics lock

**Files:**
- Modify: `courses/views.py` (`seen`)
- Test: `courses/tests/test_slideshow_seen.py`

**Interfaces:**
- Consumes: `seen` view POST (JSON array of `Element` join-row pks).
- Produces: completion `current` set excludes slide-break join-rows (filtered by `ContentType`); union semantics unchanged (verified by test).

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_slideshow_seen.py
import json
import pytest
from django.contrib.contenttypes.models import ContentType
from courses.models import Element, SlideBreakElement, TextElement, UnitProgress
from tests.factories import TEST_PASSWORD


@pytest.mark.django_db
def test_completion_ignores_break_and_unions(client, enrolled_lesson_with_break, student):
    unit = enrolled_lesson_with_break
    client.force_login(student)
    content_pks = list(
        unit.elements.exclude(
            content_type=ContentType.objects.get_for_model(SlideBreakElement)
        ).values_list("pk", flat=True)
    )
    url = f"/courses/{unit.course.slug}/unit/{unit.pk}/seen/"  # match courses/urls.py name
    # Two disjoint partial POSTs; union must be retained and completion reached.
    half = len(content_pks) // 2
    client.post(url, json.dumps(content_pks[:half]), content_type="application/json")
    r = client.post(url, json.dumps(content_pks[half:]), content_type="application/json")
    assert r.json()["completed"] is True
    prog = UnitProgress.objects.get(student=student, unit=unit)
    assert set(prog.seen_element_ids) == set(content_pks)  # union, not replace
```

(Resolve the seen URL via `reverse("courses:seen", ...)` rather than a hardcoded path — match the existing name in `courses/urls.py`.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_slideshow_seen.py -v`
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

Run: `uv run pytest courses/tests/test_slideshow_seen.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/views.py courses/tests/test_slideshow_seen.py
git commit -m "fix(courses): exclude slide-breaks from lesson completion set"
```

---

## Task 5: Server-side quiz question numbering (replace CSS counter)

**Files:**
- Modify: the quiz question wrapper template/partial that renders `.el--question` (find via `grep -rn "el--question" templates/ courses/`), passing/emitting a server-computed number.
- Modify: `courses/static/courses/css/courses.css` (remove the `counter-reset`/`counter-increment`/`content: counter(quiz-q)` rules; keep the number's visual styling driven by a real element/attribute).
- Modify: `build_quiz_context` (or the render loop) to compute a 1-based number per question element in document order.
- Test: `courses/tests/test_slideshow_numbering.py`

**Interfaces:**
- Produces: each rendered quiz question carries its number in the markup (e.g. a `data-qnum`/rendered `1.` span), contiguous in document order across the whole unit — so hiding a slide with `display:none` cannot renumber.

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_slideshow_numbering.py
import re, pytest
# Render a quiz unit page with 3 questions across a slide break and assert the
# markup contains question numbers 1,2,3 in order (not via CSS ::before, which a
# server-rendered-HTML assertion can't see).


@pytest.mark.django_db
def test_quiz_numbers_are_in_markup_and_contiguous(client, quiz_three_questions_one_break, student):
    client.force_login(student)
    unit = quiz_three_questions_one_break
    html = client.get(f"/courses/{unit.course.slug}/unit/{unit.pk}/").content.decode()
    nums = re.findall(r'data-qnum="(\d+)"', html)
    assert nums == ["1", "2", "3"]
```

(Match the actual quiz-take URL name via `reverse`.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_slideshow_numbering.py -v`
Expected: FAIL (no `data-qnum` in markup — numbering is CSS-only today).

- [ ] **Step 3: Implement server-side numbering**

- In `build_quiz_context`, compute a per-question number in document order over `elements` (only `QuestionElement` instances count, matching what `.el--question` marked). Attach it so the template can render it — e.g. build `{element_pk: number}` and add to context, or annotate each join-row.
- In the quiz question wrapper template, render the number into the markup with a stable hook, e.g. `<span class="el__qnum" data-qnum="{{ qnum }}">{{ qnum }}.</span>`, replacing the CSS-counter `::before`.
- In `courses.css`, DELETE the `.quiz { counter-reset: quiz-q }`, `.quiz .el--question { counter-increment: quiz-q }`, and `.quiz .el--question ... ::before { content: counter(quiz-q) }` rules (grep `quiz-q`), and restyle `.el__qnum` to match the previous visual (same weight/size/colour). Verify the flat (non-slideshow) quiz still shows identical numbering.

- [ ] **Step 4: Run to verify it passes + visually check**

Run: `uv run pytest courses/tests/test_slideshow_numbering.py -v`
Expected: PASS. Then screenshot a normal (non-slideshow) quiz light+dark and confirm numbering is visually unchanged from before.

- [ ] **Step 5: Update any tests/screenshots that asserted counter-based numbering**

Run: `uv run pytest courses/tests/ -k "quiz" -q` and fix any test that depended on the CSS counter.

- [ ] **Step 6: Commit**

```bash
git add courses/views.py courses/static/courses/css/courses.css templates courses/tests/test_slideshow_numbering.py
git commit -m "refactor(courses): server-side quiz question numbering (display:none-safe)"
```

---

## Task 6: Article templates render slides + defensive break template

**Files:**
- Modify: `templates/courses/_lesson_article.html`, `templates/courses/_quiz_article.html`
- Create: `templates/courses/elements/slidebreakelement.html` (empty)
- Test: `courses/tests/test_slideshow_templates.py`

**Interfaces:**
- Consumes: `slides` (Task 3).
- Produces: one `<div class="slide">` per group wrapping the existing `<section data-element-id>` blocks; the article root element carries `data-slideshow` iff `slides|length > 1`.

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_slideshow_templates.py
import pytest


@pytest.mark.django_db
def test_multi_slide_marks_article_and_wraps(client, lesson_two_slides, student):
    client.force_login(student)
    html = client.get(lesson_two_slides.get_take_url()).content.decode()  # or reverse()
    assert "data-slideshow" in html
    assert html.count('class="slide"') == 2


@pytest.mark.django_db
def test_single_slide_not_marked(client, lesson_one_slide_trailing_break, student):
    client.force_login(student)
    html = client.get(lesson_one_slide_trailing_break.get_take_url()).content.decode()
    assert "data-slideshow" not in html  # lone trailing break -> one slide, flat
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_slideshow_templates.py -v`
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

Mirror the same slides loop in `_quiz_article.html` (wrap the existing per-element `<section data-element-id>` in `{% for slide in slides %}<div class="slide">…</div>{% endfor %}`, add `{% if slides|length > 1 %}data-slideshow{% endif %}` to `<article class="quiz" ...>`). Keep the `quiz-finish` form AFTER the `{% for slide %}` loop, outside every `.slide` (unchanged position).

- [ ] **Step 4: Create the defensive empty template**

```django
{# templates/courses/elements/slidebreakelement.html — intentionally empty: breaks are consumed by partition_into_slides before render; this exists only so ElementBase.render() cannot 500 on a missing template. #}
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest courses/tests/test_slideshow_templates.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/courses/_lesson_article.html templates/courses/_quiz_article.html templates/courses/elements/slidebreakelement.html courses/tests/test_slideshow_templates.py
git commit -m "feat(courses): render units as slide groups (data-slideshow iff >1 slide)"
```

---

## Task 7: CSS slide layering + FOUC pre-hide + synchronous `.js` class

**Files:**
- Modify: `courses/static/courses/css/courses.css`
- Modify: the base/head template so a tiny synchronous script adds a `js` class to `<html>` before paint (find `base.html`; add near the top of `<head>`, inline, NOT deferred).
- Test: covered by the Task 8 e2e (no-JS fallback) + a template assertion here.

**Interfaces:**
- Produces: `.slide { display: contents }` default; `[data-slideshow] .slide { display: block }`; inactive slide hidden via a `.slide[hidden]` / `.slide:not(.is-active)` `display:none`; FOUC rule `html.js [data-slideshow] .slide:not(:first-child){ display:none }` so non-first slides are hidden before `slideshow.js` runs; no-JS (no `html.js`) shows all.

- [ ] **Step 1: Add the synchronous class script**

In `base.html` `<head>`, as the FIRST element inside `<head>` (before CSS), add:

```html
<script>document.documentElement.classList.add('js');</script>
```

(Inline + synchronous so `html.js` is set before first paint; no-JS never sets it.)

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

/* FOUC: before deferred slideshow.js runs, pre-hide non-first slides when JS is on.
   No-JS (no html.js) leaves all slides visible = flat page. */
html.js [data-slideshow] .slide:not(:first-child) { display: none; }
```

Also add `.slideshow-bar` control-bar styling (flex row, Prev/counter/Next; disabled-button state; light+dark tokens) — bespoke, matching the app's existing button/token styles.

- [ ] **Step 3: Verify no-JS fallback via a template render assertion**

Add to `test_slideshow_templates.py`: render a 2-slide unit and confirm the server markup applies NO hiding attribute/class (all `.slide` present, none carry `is-active`/`hidden` server-side) — hiding is JS-only.

- [ ] **Step 4: Commit**

```bash
git add templates/base.html courses/static/courses/css/courses.css courses/tests/test_slideshow_templates.py
git commit -m "feat(courses): slide CSS layering + FOUC pre-hide + html.js class"
```

---

## Task 8: `slideshow.js` core — pagination, counter, keyboard, guards

**Files:**
- Create: `courses/static/courses/js/slideshow.js`
- Modify: `templates/courses/lesson_unit.html`, `templates/courses/quiz_unit.html` (load the script, deferred)
- Test: `e2e/test_slideshow_nav.spec.*` (match the repo's Playwright layout/runner)

**Interfaces:**
- Produces: on a `[data-slideshow]` article, a control bar `◀ Prev · N / total · Next ▶` inserted after the last `.slide`; slide 0 active on load; free Prev/Next (disabled at ends); counter `role=status` `aria-live=polite`; arrow-key nav that bails on form-control/editable targets; scroll-new-slide-top; no-op when `≤1` slide.

- [ ] **Step 1: Write the failing e2e test**

```js
// e2e/test_slideshow_nav.spec.<ext> — follow the existing e2e harness (login helper,
// base URL, fixtures). Seed a lesson unit with 3 slides via the test data path.
test('prev/next paginate and update the counter', async ({ page }) => {
  await loginAsStudent(page);
  await page.goto(slideshowLessonUrl);
  await expect(page.locator('.slideshow-bar')).toBeVisible();
  await expect(page.locator('[data-slideshow-counter]')).toHaveText('1 / 3');
  await expect(page.locator('.slide.is-active')).toHaveCount(1);
  await page.getByRole('button', { name: /next/i }).click();
  await expect(page.locator('[data-slideshow-counter]')).toHaveText('2 / 3');
  // Prev disabled on slide 1, Next disabled on slide 3:
  await page.getByRole('button', { name: /next/i }).click();
  await expect(page.getByRole('button', { name: /next/i })).toBeDisabled();
});

test('arrow key inside a text field does not change slide', async ({ page }) => {
  await loginAsStudent(page);
  await page.goto(slideshowQuizUrl);
  const input = page.locator('.slide.is-active input[type=text]').first();
  await input.click();
  await input.press('ArrowRight');
  await expect(page.locator('[data-slideshow-counter]')).toHaveText('1 / 3');
});

test('single-slide unit renders no control bar', async ({ page }) => {
  await loginAsStudent(page);
  await page.goto(singleSlideUrl);
  await expect(page.locator('.slideshow-bar')).toHaveCount(0);
});
```

- [ ] **Step 2: Run to verify it fails**

Run the e2e suite for this spec (match the repo's command, e.g. `uv run pytest e2e/test_slideshow_nav.py` or the Playwright runner). Expected: FAIL (no control bar).

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

  var bar = document.createElement("nav");
  bar.className = "slideshow-bar";
  bar.setAttribute("aria-label", i18n.nav || "Slides");
  var prev = document.createElement("button");
  prev.type = "button"; prev.className = "slideshow-bar__prev"; prev.textContent = "◀ " + i18n.prev;
  var counter = document.createElement("span");
  counter.className = "slideshow-bar__counter";
  counter.setAttribute("data-slideshow-counter", "");
  counter.setAttribute("role", "status");
  counter.setAttribute("aria-live", "polite");
  var next = document.createElement("button");
  next.type = "button"; next.className = "slideshow-bar__next"; next.textContent = i18n.next + " ▶";
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

Run the e2e spec. Expected: PASS (nav, arrow-guard, single-slide).

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/slideshow.js templates/courses/lesson_unit.html templates/courses/quiz_unit.html e2e/test_slideshow_nav.*
git commit -m "feat(courses): slideshow.js pagination, counter, keyboard guard"
```

---

## Task 9: Lesson mark-seen-on-reveal (batched union POST)

**Files:**
- Modify: `courses/static/courses/js/slideshow.js` (`onReveal`)
- Test: `e2e/test_slideshow_progress.spec.*`

**Interfaces:**
- Produces: on each reveal (including initial slide 0), if the article has `data-seen-url` (lessons only), POST that slide's `data-element-id` pks as a JSON array to the seen endpoint (batched, idempotent). Quizzes (no `data-seen-url`) do nothing.

- [ ] **Step 1: Write the failing e2e test**

```js
test('lesson completes after paging all slides, including a tall slide', async ({ page }) => {
  await loginAsStudent(page);
  await page.goto(tallSlidesLessonUrl); // slide 0 is taller than viewport
  // Never scroll; just page to the end.
  await page.getByRole('button', { name: /next/i }).click();
  await page.getByRole('button', { name: /next/i }).click();
  await expect(page.locator('[data-unit-done]')).toHaveClass(/is-complete/);
});
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL (bottom of tall slides never marked seen).

- [ ] **Step 3: Implement `onReveal` seen reporting**

```js
  var seenUrl = article.getAttribute("data-seen-url"); // lessons only; quizzes lack it
  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? m[1] : "";
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
    }).catch(function () {});
  }
```

Call `markSlideSeen(slide)` from `onReveal`. Because the server unions pks (Task 4) and `progress.js` also posts, double-firing is idempotent.

- [ ] **Step 4: Run to verify it passes**

Expected: PASS (completion without scrolling).

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/slideshow.js e2e/test_slideshow_progress.*
git commit -m "feat(courses): mark whole slide seen on reveal (lesson, batched union POST)"
```

---

## Task 10: Quiz Finish gating + widget relayout on reveal

**Files:**
- Modify: `courses/static/courses/js/slideshow.js` (`onReveal`)
- Test: `e2e/test_slideshow_quiz.spec.*`

**Interfaces:**
- Produces: on quiz pages, the `[data-quiz-finish]` form is hidden until the last slide is active; on every reveal a `resize` event is dispatched so MathLive/GeoGebra widgets re-measure.

- [ ] **Step 1: Write the failing e2e test**

```js
test('finish hidden until last slide', async ({ page }) => {
  await loginAsStudent(page);
  await page.goto(slideshowQuizUrl); // 3 slides
  await expect(page.locator('[data-quiz-finish]')).toBeHidden();
  await page.getByRole('button', { name: /next/i }).click();
  await page.getByRole('button', { name: /next/i }).click();
  await expect(page.locator('[data-quiz-finish]')).toBeVisible();
});

test('math widget on slide 2 renders at correct width', async ({ page }) => {
  await loginAsStudent(page);
  await page.goto(quizWithMathOnSlide2Url);
  await page.getByRole('button', { name: /next/i }).click();
  const box = await page.locator('.slide.is-active math-field').first().boundingBox();
  expect(box.width).toBeGreaterThan(50); // not collapsed to ~0
});
```

- [ ] **Step 2: Run to verify it fails**

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

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/slideshow.js e2e/test_slideshow_quiz.*
git commit -m "feat(courses): quiz Finish gating on last slide + widget relayout on reveal"
```

---

## Task 11: `SlideBreakElementForm` + create wiring

**Files:**
- Modify: `courses/element_forms.py` (add `SlideBreakElementForm`, register in `FORM_FOR_TYPE`)
- Modify: `courses/views_manage.py` (`_EDITOR_TYPE_LABELS`, both allowed-type tuples in `element_add`/`element_save`)
- Test: `courses/tests/test_slideshow_builder.py`

**Interfaces:**
- Consumes: `save_element` generic branch (`FORM_FOR_TYPE[type_key](...).save()`).
- Produces: a field-less `SlideBreakElementForm`; `type_key == "slide_break"` accepted by add/save and creates a `SlideBreakElement` + `Element` join-row.

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_slideshow_builder.py
import pytest
from courses.builder import save_element
from courses.models import Element, SlideBreakElement


@pytest.mark.django_db
def test_save_element_creates_slide_break(manage_quiz_unit):
    unit = manage_quiz_unit
    post = {"unit_token": unit.updated.isoformat()}
    save_element(unit.course, unit.pk, "slide_break", "new", post, {})
    joins = list(unit.elements.all())
    assert any(isinstance(j.content_object, SlideBreakElement) for j in joins)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_slideshow_builder.py -v`
Expected: FAIL (KeyError: 'slide_break' in FORM_FOR_TYPE).

- [ ] **Step 3: Implement the form + registration**

In `courses/element_forms.py`:

```python
class SlideBreakElementForm(forms.ModelForm):
    class Meta:
        model = SlideBreakElement
        fields = []  # field-less: a break has nothing to edit
```

Add to `FORM_FOR_TYPE`: `"slide_break": SlideBreakElementForm,`.

In `courses/views_manage.py`: add `"slide_break": gettext_lazy("Slide break"),` to `_EDITOR_TYPE_LABELS`, and add `"slide_break"` to BOTH allowed-type tuples (in `element_add` and `element_save`). The generic `save_element` branch already handles it (`FORM_FOR_TYPE["slide_break"](data=post).save()` creates the row; `type_key not in ("image", "video")` so no `course` extra).

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest courses/tests/test_slideshow_builder.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/element_forms.py courses/views_manage.py courses/tests/test_slideshow_builder.py
git commit -m "feat(courses): field-less SlideBreakElementForm + save_element wiring"
```

---

## Task 12: Builder palette entry, divider row, direct-create, legend, icon

**Files:**
- Modify: `templates/courses/manage/editor/_add_menu.html` (palette entry)
- Modify: `templates/courses/manage/editor/_element_row.html` (render a break as a thin divider row, not a content card)
- Modify: the icon sprite (find the `<symbol id="el-...">` definitions; add `#el-slidebreak`, a monochrome line SVG)
- Modify: the editor JS (find the `data-add-type` handler) so `slide_break` creates directly (POST to `element_save`) instead of opening an editor; and the builder legend text.
- Test: `e2e/test_slideshow_builder.spec.*` (author adds a break; sees a divider row)

**Interfaces:**
- Produces: a "Slide break" palette button; clicking it inserts a break row directly (no editor); the row renders as a divider; a legend note explains it.

- [ ] **Step 1: Write the failing e2e test**

```js
test('author adds a slide break and sees a divider row', async ({ page }) => {
  await loginAsAuthor(page);
  await page.goto(builderUnitUrl);
  await page.locator('[data-add-toggle]').click();
  await page.locator('[data-add-type="slide_break"]').click();
  await expect(page.locator('.element-row--slidebreak, [data-slidebreak-row]')).toHaveCount(1);
});
```

- [ ] **Step 2: Run to verify it fails.** Expected: FAIL (no palette entry).

- [ ] **Step 3: Implement**

- **Palette:** in `_add_menu.html`, add a small "Structure" group (or append to Content) with:
  `<button type="button" class="typecard" data-add-type="slide_break"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-slidebreak"/></svg>{% trans "Slide break" %}</button>`
- **Icon:** add an `#el-slidebreak` symbol to the sprite (a horizontal dashed rule / scissors-free divider, `currentColor`, `stroke` line style matching siblings).
- **Direct-create:** in the editor JS, special-case `data-add-type="slide_break"`: instead of the normal add→open-editor flow, POST directly to the `element_save` endpoint with `type=slide_break` + the unit token, then refresh the element list fragment (reuse the existing fragment-refresh the editor already performs on save). Match how the current `data-add-type` handler builds its request.
- **Divider row:** in `_element_row.html`, detect a break (`el.content_object` is a `SlideBreakElement`) and render a compact divider row — a labelled horizontal rule ("— Slide break —") with the existing reorder/delete controls, and NO edit affordance — instead of the standard content card.
- **Legend:** add a one-line note near the builder legend: `{% trans "Add a slide break to split this unit into a slideshow." %}`

- [ ] **Step 4: Run to verify it passes.** Expected: PASS. Screenshot the builder (light+dark) and confirm the divider row + palette entry read cleanly.

- [ ] **Step 5: Commit**

```bash
git add templates/courses/manage/editor/ courses/static courses/tests e2e/test_slideshow_builder.*
git commit -m "feat(courses): builder slide-break palette, divider row, direct-create, legend"
```

---

## Task 13: Transfer round-trip (three registries)

**Files:**
- Modify: `courses/transfer/export.py` (`SERIALIZERS` + `_ser_slide_break`)
- Modify: `courses/transfer/payloads.py` (`VALIDATORS` + `_val_slide_break`)
- Modify: `courses/transfer/importer.py` (`BUILDERS` + `_build_slide_break`)
- Test: `courses/tests/test_slideshow_transfer.py`

**Interfaces:**
- Produces: `slide_break` key registered in all THREE lockstep registries; export→import preserves breaks (and thus slideshow-ness).

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_slideshow_transfer.py
import pytest
from courses.models import SlideBreakElement
# Use the existing export + import helpers (see courses/tests for the transfer round-trip pattern).


@pytest.mark.django_db
def test_export_import_preserves_slide_break(course_with_break):
    blob = export_course(course_with_break)          # existing exporter entrypoint
    imported = import_course(blob, owner=course_with_break.owner)  # existing importer entrypoint
    unit = imported.nodes.get(title=course_with_break.break_unit_title)
    assert any(isinstance(j.content_object, SlideBreakElement) for j in unit.elements.all())
```

(Match the actual export/import entrypoints + signatures used by the existing transfer tests.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_slideshow_transfer.py -v`
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

Run: `uv run pytest courses/tests/test_slideshow_transfer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/transfer/ courses/tests/test_slideshow_transfer.py
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

- Spec §1 (model, ELEMENT_MODELS, is_slideshow, registry sweep) → Tasks 1, 14.
- Spec §2 (partition, slides context, div.slide, data-slideshow>1 gate, hide mechanism, server-side numbering, widget relayout) → Tasks 2, 3, 5, 6, 7, 10.
- Spec §3 (slideshow.js: control bar, counter aria-live, free nav, keyboard guard, degenerate guard, scroll, FOUC, Finish gating, mark-seen) → Tasks 7, 8, 9, 10.
- Spec §4 (builder palette, create pipeline, divider row, legend) → Tasks 11, 12.
- Data flow + Progress completion (seen exclusion, union, lesson-only, data-seen-url gate) → Tasks 4, 9.
- Error handling (defensive template, transfer 3 registries, scoring skip) → Tasks 6, 13, 14.
- Testing (unit/view/template/e2e incl. contiguous numbering, tall slide 0, single-slide, arrow-in-input incl. radio/select, widget relayout, export/import) → distributed across Tasks 2–14.

**Known deviation from spec text:** the spec called the transfer path a "dual registry (export.py + schema.py)"; the actual codebase has THREE lockstep registries — `export.py SERIALIZERS`, `payloads.py VALIDATORS`, `importer.py BUILDERS`. Task 13 registers all three (this is the correct, verified shape).
