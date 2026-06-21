# Phase 2d-ii — Drag-to-image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the 8th question type — drag-to-image: students drag/tap/select text-or-KaTeX labels onto author-defined rectangle zones over an image; auto-marked per zone via the existing DnD substrate.

**Architecture:** A new `DragToImageQuestionElement` + `DragZone` sub-row reuse the 2d-i substrate (`courses/dnd.py`: `build_pool`/`mark_slots`/`_render_select`) wholesale — each zone is a target, the pool is the labels. The only genuinely new code is image-overlay rendering (numbered badges + a select list below), a rectangle-drawing authoring canvas (`zone-editor.js`), and a shared tap-to-assign enhancement added to `dnd.js`. Marking, persistence, resume, withhold, and results all flow through the unchanged existing dispatch.

**Tech Stack:** Python 3.13, Django 5.2, PostgreSQL, pytest + factory_boy, vanilla JS (no framework), KaTeX, Playwright (e2e). Spec: `docs/superpowers/specs/2026-06-21-phase-2d-ii-drag-to-image-design.md`.

## Global Constraints

- **No new dependencies.** Vanilla JS only (no DnD/canvas library), consistent with the bespoke front end.
- **No-JS parity for the student answering path is load-bearing** — image + numbered badges + `<select name="slot">` + submit must be a complete, working question with JS off. (No-JS *authoring* is scoped to editing existing zones only.)
- **Server is the sole marking authority.** Submitted label texts are validated for pool membership; forged/non-member/deleted labels score wrong, never error. Coordinates are authoring-only and never affect marking.
- **Token/label convention:** plain text + KaTeX delimiters (`\(x^2\)`), **never HTML-sanitised**, `max_length=500` (matches `Choice.text`/`DragBlank.correct_token`).
- **Reuse the substrate verbatim.** Do NOT alter `dnd.build_pool`, `dnd.mark_slots`, or `dnd._render_select` (option value stays the *raw* token; only the pre-selection test normalizes). Only ADD `dnd.render_zone_selects` and extend `dnd.js`.
- **Two naming schemes — do not conflate:** the render template uses the FULL `_meta.model_name` *with* the `element` suffix (`dragtoimagequestionelement.html`); the `type_key` is `model_name` *without* it (`dragtoimagequestion`, used in `FORM_FOR_TYPE`, the add-menu `data-add-type`, the `views_manage` allowlists, and the `_edit_<type_key>.html` include).
- **i18n:** every new user-facing string wrapped for EN/PL.
- **Tests:** pytest + factory_boy against real PostgreSQL; `tests/` is the top-level test dir; mirror the `test_questions_2d_*` family.

---

## File Structure

**Create:**
- `tests/test_questions_2dii_models.py` — model + coord-validation + `expected_tokens` tests
- `tests/test_questions_2dii_mark.py` — marking + `dnd.render_zone_selects` helper tests
- `tests/test_questions_2dii_render.py` — student render (badges + selects + no-leak) tests
- `tests/test_questions_2dii_form.py` — form course-scoping + formset clean/coord tests
- `tests/test_questions_2dii_builder.py` — builder persist (zones + course=) tests
- `tests/test_questions_2dii_authoring_views.py` — add/save/open + cross-course media on all 3 gates
- `tests/test_questions_2dii_consumption.py` — prefetch / KaTeX / CT-gate / resume-routing / results
- `tests/test_i18n_questions_2dii.py` — PL string render
- `tests/test_e2e_questions_2dii.py` — Playwright JS + no-JS + tap
- `templates/courses/elements/dragtoimagequestionelement.html` — student render template (repo-root `templates/`, where every existing element template lives)
- `templates/courses/elements/_reveal_dragimage.html` — per-zone reveal partial
- `templates/courses/manage/editor/_edit_dragtoimagequestion.html` — authoring partial (canvas + formset)
- `courses/static/courses/js/zone-editor.js` — rectangle-drawing authoring canvas

**Modify:**
- `courses/models.py` — `ZONE_COORD_EPSILON`, `DragToImageQuestionElement`, `DragZone`
- `courses/migrations/0018_dragtoimage.py` — new migration (generated)
- `courses/dnd.py` — add `render_zone_selects`
- `courses/templatetags/courses_extras.py` — add `render_image_selects` tag
- `courses/element_forms.py` — `DragToImageQuestionElementForm`, `BaseDragZoneFormSet`, `build_dragzone_formset`, register `FORM_FOR_TYPE`
- `courses/builder.py` — `dragtoimagequestion` persist branch
- `courses/views_manage.py` — allowlists (`element_add`/`element_save`) + 3 `course=` gates (`_render_open_form`, `element_form`)
- `courses/views.py` — prefetch `zones`, `_question_has_math` branch, `question_models` gate
- `courses/static/courses/js/dnd.js` — tap-to-assign + overlay-target discriminator
- `templates/courses/manage/editor/_add_menu.html` — add-element button
- `templates/courses/manage/editor/editor.html` — load `zone-editor.js`
- `tests/factories.py` — `DragToImageQuestionElementFactory`, `DragZoneFactory`
- `locale/pl/LC_MESSAGES/django.po` — PL translations

---

### Task 1: Model + migration + factories

**Files:**
- Modify: `courses/models.py` (add after `MatchPair`, ~line 730)
- Create: `courses/migrations/0018_dragtoimage.py` (generated)
- Modify: `tests/factories.py` (add after `MatchPairFactory`, ~line 219)
- Test: `tests/test_questions_2dii_models.py`

**Interfaces:**
- Produces: `DragToImageQuestionElement(media FK, alt, distractors, elements, expected_tokens()->list[str], build_answer(post)->list, mark(answer)->MarkResult)`; `DragZone(question FK related_name="zones", correct_label, x, y, w, h floats, order)`; module constant `ZONE_COORD_EPSILON = 1e-6`; factories `DragToImageQuestionElementFactory`, `DragZoneFactory`.
- Consumes: `dnd.build_pool`, `dnd.mark_slots` (existing), `MarkResult`, `OrderField`, `MediaAsset`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_questions_2dii_models.py
import pytest
from django.core.exceptions import ValidationError

from courses.models import DragToImageQuestionElement, DragZone
from tests.factories import (
    DragToImageQuestionElementFactory,
    DragZoneFactory,
    MediaAssetFactory,
)

pytestmark = pytest.mark.django_db


def test_expected_tokens_is_zone_order():
    q = DragToImageQuestionElementFactory()
    DragZoneFactory(question=q, correct_label="Nucleus", order=0)
    DragZoneFactory(question=q, correct_label="Membrane", order=1)
    assert q.expected_tokens() == ["Nucleus", "Membrane"]


def test_build_answer_reads_slot_getlist(rf):
    q = DragToImageQuestionElementFactory()
    req = rf.post("/", {"slot": ["A", "", "B"]})
    assert q.build_answer(req.POST) == ["A", "", "B"]


def test_zone_coord_validation_accepts_in_range():
    q = DragToImageQuestionElementFactory()
    z = DragZone(question=q, correct_label="x", x=0.1, y=0.1, w=0.3, h=0.3, order=0)
    z.full_clean()  # no raise


@pytest.mark.parametrize(
    "x,y,w,h",
    [
        (0.9, 0.0, 0.2, 0.2),   # x+w = 1.1 > 1+eps
        (0.0, 0.9, 0.2, 0.2),   # y+h overflow
        (0.0, 0.0, 0.0, 0.3),   # zero width
        (0.0, 0.0, 0.3, 0.0),   # zero height
        (-0.1, 0.0, 0.3, 0.3),  # negative x
    ],
)
def test_zone_coord_validation_rejects_bad(x, y, w, h):
    q = DragToImageQuestionElementFactory()
    z = DragZone(question=q, correct_label="x", x=x, y=y, w=w, h=h, order=0)
    with pytest.raises(ValidationError):
        z.full_clean()


def test_zone_coord_epsilon_boundary():
    from courses.models import ZONE_COORD_EPSILON

    q = DragToImageQuestionElementFactory()
    ok = DragZone(question=q, correct_label="x", x=0.5, y=0.0,
                  w=0.5 + ZONE_COORD_EPSILON, h=0.2, order=0)
    ok.full_clean()  # within epsilon → passes
    bad = DragZone(question=q, correct_label="x", x=0.5, y=0.0,
                   w=0.5 + 2 * ZONE_COORD_EPSILON, h=0.2, order=1)
    with pytest.raises(ValidationError):
        bad.full_clean()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_questions_2dii_models.py -v`
Expected: FAIL with `ImportError`/`cannot import name 'DragToImageQuestionElement'`.

- [ ] **Step 3: Add the models**

```python
# courses/models.py — add near the other DnD constants/imports if any; otherwise
# above DragToImageQuestionElement. 1e-6 absorbs float rounding from the canvas.
ZONE_COORD_EPSILON = 1e-6


class DragToImageQuestionElement(QuestionElement):
    """Drag labels onto author-defined rectangle zones over an image. Marking is
    per-zone via the shared DnD substrate; each zone's correct token is a DragZone
    row. `stem` (inherited) is the optional prompt above the image."""

    REVEAL_TEMPLATE = "courses/elements/_reveal_dragimage.html"

    media = models.ForeignKey(
        "MediaAsset", on_delete=models.PROTECT, limit_choices_to={"kind": "image"}
    )
    alt = models.CharField(max_length=255, blank=True)  # see a11y note in spec §7.2
    distractors = models.TextField(blank=True)  # newline-delimited wrong labels
    elements = GenericRelation(Element)

    def expected_tokens(self):
        # Order is load-bearing: expected_tokens()[n] aligns with zone n (the nth
        # <select name="slot"> and the nth badge). Keep zones order stable.
        return [z.correct_label for z in self.zones.all()]

    def build_answer(self, post):
        return post.getlist("slot")

    def mark(self, answer):
        from courses import dnd

        expected = self.expected_tokens()
        pool = dnd.build_pool(self)
        n_correct, reveal = dnd.mark_slots(expected, pool, answer)
        n = len(expected)
        return MarkResult(
            correct=(n_correct == n and n > 0),
            fraction=(n_correct / n) if n else 0.0,
            reveal=reveal,
        )


class DragZone(models.Model):
    question = models.ForeignKey(
        DragToImageQuestionElement, on_delete=models.CASCADE, related_name="zones"
    )
    correct_label = models.CharField(max_length=500)  # plain text + KaTeX; never sanitised
    x = models.FloatField()  # left,   fraction 0..1 of image width
    y = models.FloatField()  # top,    fraction 0..1 of image height
    w = models.FloatField()  # width,  fraction 0..1
    h = models.FloatField()  # height, fraction 0..1
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.correct_label

    def clean(self):
        e = ZONE_COORD_EPSILON
        if not (0 <= self.x <= 1 and 0 <= self.y <= 1):
            raise ValidationError(_("Zone position must be within the image."))
        if not (0 < self.w <= 1 and 0 < self.h <= 1):
            raise ValidationError(_("Zone must have a positive size."))
        if self.x + self.w > 1 + e or self.y + self.h > 1 + e:
            raise ValidationError(_("Zone must not extend past the image."))
```

Ensure `ValidationError` is imported in `models.py` (it already is — used by `VideoElement.clean`).

- [ ] **Step 4: Add the factories**

```python
# tests/factories.py — add after MatchPairFactory
class DragToImageQuestionElementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DragToImageQuestionElement

    media = factory.SubFactory(MediaAssetFactory)
    alt = "Diagram"
    distractors = ""


class DragZoneFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DragZone

    question = factory.SubFactory(DragToImageQuestionElementFactory)
    correct_label = factory.Sequence(lambda n: f"label{n}")
    x = 0.1
    y = 0.1
    w = 0.2
    h = 0.2
```

Add `DragToImageQuestionElement, DragZone` to the existing `from courses.models import (...)` block in `tests/factories.py`.

- [ ] **Step 5: Generate the migration**

Run: `python manage.py makemigrations courses --name dragtoimage`
Expected: creates `courses/migrations/0018_dragtoimage.py` with `dependencies = [("courses", "0017_dragfill_matchpair")]`. If `0018_*` already exists at the tip, accept the auto-assigned number — the dependency edge is the invariant.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_questions_2dii_models.py -v && python manage.py makemigrations --check`
Expected: PASS; `--check` reports no missing migrations.

- [ ] **Step 7: Commit**

```bash
git add courses/models.py courses/migrations/0018_dragtoimage.py tests/factories.py tests/test_questions_2dii_models.py
git commit -m "feat(2d-ii): DragToImageQuestionElement + DragZone model & migration"
```

---

### Task 2: Marking + `render_zone_selects` substrate helper

**Files:**
- Modify: `courses/dnd.py` (append `render_zone_selects` after `render_match_rows`, at the end of the file ~line 122)
- Test: `tests/test_questions_2dii_mark.py`

**Interfaces:**
- Consumes: `DragToImageQuestionElement.mark`, `dnd.build_pool`, `dnd.mark_slots`, `dnd._render_select` (all existing).
- Produces: `dnd.render_zone_selects(zones, pool, chosen=None) -> SafeString` — an `<ol class="dnd__rows">` of `(badge number, <select name="slot">)` rows in `zones` order.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_questions_2dii_mark.py
import pytest

from courses import dnd
from courses.models import MarkResult
from tests.factories import DragToImageQuestionElementFactory, DragZoneFactory

pytestmark = pytest.mark.django_db


def _q(labels, distractors=""):
    q = DragToImageQuestionElementFactory(distractors=distractors)
    for i, lab in enumerate(labels):
        DragZoneFactory(question=q, correct_label=lab, order=i)
    return q


def test_mark_all_correct():
    q = _q(["A", "B"])
    r = q.mark(["A", "B"])
    assert r.correct and r.fraction == 1.0


def test_mark_partial():
    q = _q(["A", "B"])
    r = q.mark(["A", "wrong"])
    assert not r.correct and r.fraction == 0.5


def test_mark_distractor_and_forged_score_wrong():
    q = _q(["A", "B"], distractors="D")
    assert q.mark(["D", "ZZZ"]).fraction == 0.0


def test_mark_reusable_label_satisfies_two_zones():
    q = _q(["A", "A"])
    assert q.mark(["A", "A"]).fraction == 1.0


def test_mark_short_list_treats_missing_as_unfilled():
    q = _q(["A", "B"])
    assert q.mark(["A"]).fraction == 0.5  # no IndexError


def test_render_zone_selects_emits_one_select_per_zone_with_badge():
    q = _q(["A", "B"], distractors="D")
    html = str(dnd.render_zone_selects(list(q.zones.all()), dnd.build_pool(q)))
    assert html.count('name="slot"') == 2
    assert "— choose —" in html
    # badge numbers present
    assert ">1<" in html and ">2<" in html


def test_render_zone_selects_preselects_chosen():
    q = _q(["A", "B"])
    html = str(dnd.render_zone_selects(list(q.zones.all()), dnd.build_pool(q), ["B", ""]))
    assert '<option value="B" selected>' in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_questions_2dii_mark.py -v`
Expected: marking tests PASS (mark already works from Task 1); the two `render_zone_selects` tests FAIL with `AttributeError: module 'courses.dnd' has no attribute 'render_zone_selects'`.

- [ ] **Step 3: Add the helper**

```python
# courses/dnd.py — add after render_match_rows
def render_zone_selects(zones, pool, chosen=None):
    """Drag-to-image: an <ol> of (badge number, <select name="slot">) rows in zones
    order. Modeled on render_match_rows but emits the 1-based badge number instead of
    a left label; geometry lives on the badges in the template, not here."""
    chosen = list(chosen or [])
    rows = []
    for i, _zone in enumerate(zones):
        val = chosen[i] if i < len(chosen) else ""
        rows.append(
            format_html(
                '<li class="dnd__row"><span class="dnd__num">{}</span>{}</li>',
                i + 1,
                _render_select(pool, val),
            )
        )
    return format_html(
        '<ol class="dnd__rows">{}</ol>',
        mark_safe("".join(rows)),  # noqa: S308 — rows built via format_html; join is safe
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_questions_2dii_mark.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/dnd.py tests/test_questions_2dii_mark.py
git commit -m "feat(2d-ii): per-zone marking reuse + render_zone_selects helper"
```

---

### Task 3: Student render template + template tag + reveal partial

**Files:**
- Modify: `courses/templatetags/courses_extras.py` (add `render_image_selects` after `render_match_pairs`, ~line 90)
- Create: `templates/courses/elements/dragtoimagequestionelement.html` (repo-root `templates/` — the same dir as `matchpairquestionelement.html`; confirmed via `git grep -l matchpairquestionelement.html`)
- Create: `templates/courses/elements/_reveal_dragimage.html`
- Test: `tests/test_questions_2dii_render.py`

**Interfaces:**
- Consumes: `dnd.render_zone_selects`, `dnd.build_pool` (from Task 2); the inherited `QuestionElement.render`.
- Produces: template tag `render_image_selects(el, submitted_values=None)`; the render template dispatched by `_meta.model_name`; `_reveal_dragimage.html` consuming the `{index, correct, accepted}` reveal tuple.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_questions_2dii_render.py
import pytest

from tests.factories import (
    DragToImageQuestionElementFactory,
    DragZoneFactory,
    add_element,
)
from tests.factories import make_quiz_unit  # quiz unit helper

pytestmark = pytest.mark.django_db


def _q_on_unit():
    unit = make_quiz_unit()
    q = DragToImageQuestionElementFactory()
    DragZoneFactory(question=q, correct_label="A", x=0.1, y=0.2, w=0.3, h=0.3, order=0)
    DragZoneFactory(question=q, correct_label="B", x=0.5, y=0.5, w=0.2, h=0.2, order=1)
    el = add_element(unit, q)
    return q, el


def test_render_has_badges_with_geometry_dataattrs_and_selects():
    q, el = _q_on_unit()
    html = q.render(element=el, mode="lesson")
    # numbered badges carry data-zone + fractional geometry for the JS overlay
    assert 'data-zone="0"' in html and 'data-x="0.1"' in html
    assert 'data-zone="1"' in html
    # no-JS select list below the image
    assert html.count('name="slot"') == 2
    # image + alt rendered
    assert "<img" in html and 'data-dnd' in html


def test_render_does_not_leak_which_label_is_correct_pre_reveal():
    # The chip pool legitimately lists ALL labels (that is how DnD works), so the
    # no-leak invariant (spec §7.1) is NOT "no accepted text in the HTML" — it is
    # "pre-reveal HTML must not indicate WHICH label is correct per zone". Assert the
    # reveal block (the only thing that ties a zone to its accepted label) is absent,
    # and no per-zone correct-marker markup is present, when there is no mark_result.
    q, el = _q_on_unit()
    html = q.render(element=el, mode="quiz")
    assert "question__reveal" not in html        # reveal partial not rendered pre-reveal
    assert "answer-correct" not in html          # no per-zone correctness marker
    assert "data-correct" not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_questions_2dii_render.py -v`
Expected: FAIL with `TemplateDoesNotExist: courses/elements/dragtoimagequestionelement.html`.

- [ ] **Step 3: Add the template tag**

```python
# courses/templatetags/courses_extras.py — add after render_match_pairs
@register.simple_tag
def render_image_selects(el, submitted_values=None):
    """Render the drag-to-image no-JS select list: an <ol> of (badge number,
    <select name="slot">) rows. The pool is built here (mirroring the render_match_pairs
    tag, whose helper render_match_rows this one is modeled on). See courses.dnd."""
    from courses import dnd

    return dnd.render_zone_selects(
        list(el.zones.all()), dnd.build_pool(el), submitted_values
    )
```

- [ ] **Step 4: Add the student render template**

Mirror `matchpairquestionelement.html`. The image wrapper holds the badges (with geometry data-attrs); the select list sits below.

```django
{# templates/courses/elements/dragtoimagequestionelement.html #}
{% load i18n courses_extras %}
<div class="el el--question el--dragimage" data-question data-dnd>
  {% if el.stem %}<div class="question__stem">{{ el.stem|safe }}</div>{% endif %}
  {% if not el.alt %}{# decorative-but-functional: warning is authoring-side, not here #}{% endif %}
  {% if element %}
  <form class="question__form" method="post" action="{{ action_url }}">
    {% csrf_token %}
    <fieldset {% if quiz_submitted or locked %}disabled{% endif %} style="border:0;padding:0;margin:0;">
      <div class="dragimage__stage" data-dragimage-stage>
        <img class="dragimage__img" src="{{ el.media.file.url }}" alt="{{ el.alt }}">
        {% for z in el.zones.all %}
          <span class="dragimage__badge" data-zone="{{ forloop.counter0 }}"
                data-x="{{ z.x }}" data-y="{{ z.y }}" data-w="{{ z.w }}" data-h="{{ z.h }}"
                style="left:{{ z.x }}; top:{{ z.y }};">{{ forloop.counter }}</span>
        {% endfor %}
      </div>
      {% if element.pk == feedback_for_pk %}
        {% render_image_selects el submitted_values %}
      {% else %}
        {% render_image_selects el %}
      {% endif %}
      {% include "courses/elements/_dnd_pool.html" %}
    </fieldset>
    <button type="submit" class="btn btn--small" {% if quiz_submitted or locked %}disabled{% endif %}>{% trans "Check" %}</button>
    <div class="question__feedback" data-question-feedback>
      {% if mode == "quiz" %}{{ feedback_html|safe }}{% elif element.pk == feedback_for_pk %}{% include feedback_partial %}{% endif %}
    </div>
  </form>
  {% else %}
    <div class="dragimage__stage" data-dragimage-stage>
      <img class="dragimage__img" src="{{ el.media.file.url }}" alt="{{ el.alt }}">
      {% for z in el.zones.all %}
        <span class="dragimage__badge" data-zone="{{ forloop.counter0 }}"
              data-x="{{ z.x }}" data-y="{{ z.y }}" data-w="{{ z.w }}" data-h="{{ z.h }}"
              style="left:{{ z.x }}; top:{{ z.y }};">{{ forloop.counter }}</span>
      {% endfor %}
    </div>
    {% render_image_selects el %}{% include "courses/elements/_dnd_pool.html" %}
  {% endif %}
</div>
```

Note: badge CSS positioning uses the fraction as a unitless value; the stylesheet should `position:absolute` badges and treat `left`/`top` via a `calc()` or a small CSS hook. If the project's CSS expects percentages, render `style="left:{{ z.x|floatformat:4 }}; ..."` through a percent filter — but the **JS reads `data-x/y/w/h`, not the CSS**, so the inline style is purely the no-JS visual hint. Pick the percent form the stylesheet expects and keep `data-*` as the raw fraction. (Add a `dragimage` CSS block to the existing question stylesheet; visual only, not test-gated.)

- [ ] **Step 5: Add the reveal partial**

Mirror `_reveal_dragfill.html` (read it first: `git show HEAD:templates/courses/elements/_reveal_dragfill.html`).

```django
{# templates/courses/elements/_reveal_dragimage.html — mirrors _reveal_dragfill.html
   exactly: question__reveal* classes; accepted shown ONLY for incorrect rows. #}
{% load i18n %}
<ol class="question__reveal question__reveal--zones">
  {% for item in mark_result.reveal %}
    <li class="question__reveal-item {% if item.correct %}answer-correct{% else %}answer-wrong{% endif %}">
      <span class="question__reveal-num">{{ forloop.counter }}</span>
      {% if item.correct %}
        <span class="question__tick" aria-hidden="true">✓</span>
      {% else %}
        <span class="question__glyph" aria-hidden="true">✗</span>
        <span class="question__reveal-text">{% trans "Correct label:" %} <strong>{{ item.accepted }}</strong></span>
      {% endif %}
    </li>
  {% endfor %}
</ol>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_questions_2dii_render.py -v`
Expected: PASS. (If `data-x="0.1"` fails because Django renders `0.1` differently, assert on `data-zone` + `name="slot"` count and adjust the geometry assertion to the actual rendered float.)

- [ ] **Step 7: Commit**

```bash
git add courses/templatetags/courses_extras.py templates/courses/elements/dragtoimagequestionelement.html templates/courses/elements/_reveal_dragimage.html tests/test_questions_2dii_render.py
git commit -m "feat(2d-ii): student render template, render_image_selects tag, reveal partial"
```

---

### Task 4: Authoring form + zone formset + registration

**Files:**
- Modify: `courses/element_forms.py` (add `DragToImageQuestionElementForm`, `BaseDragZoneFormSet`, `DragZoneFormSet`, `build_dragzone_formset`; register in `FORM_FOR_TYPE`)
- Test: `tests/test_questions_2dii_form.py`

**Interfaces:**
- Consumes: `_MarkingFieldsMixin`, `_CourseScopedMediaForm`, `MediaAsset`, `DragToImageQuestionElement`, `DragZone`, `ZONE_COORD_EPSILON`.
- Produces: `DragToImageQuestionElementForm(_MarkingFieldsMixin, _CourseScopedMediaForm)` with `media_kind="image"`; `build_dragzone_formset(*, data=None, files=None, instance=None, prefix="zones")`; `FORM_FOR_TYPE["dragtoimagequestion"]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_questions_2dii_form.py
import pytest

from courses.element_forms import (
    DragToImageQuestionElementForm,
    build_dragzone_formset,
)
from tests.factories import CourseFactory, MediaAssetFactory

pytestmark = pytest.mark.django_db


def test_form_scopes_media_to_course_and_makes_marking_optional():
    c1 = CourseFactory()
    c2 = CourseFactory()
    mine = MediaAssetFactory(course=c1, kind="image")
    other = MediaAssetFactory(course=c2, kind="image")
    form = DragToImageQuestionElementForm(course=c1)
    qs = form.fields["media"].queryset
    assert mine in qs and other not in qs
    for f in ("marking_mode", "max_attempts", "max_marks"):
        assert form.fields[f].required is False


def test_form_constructs_without_typeerror_on_course_kwarg():
    DragToImageQuestionElementForm(course=CourseFactory())  # no TypeError


def test_formset_requires_at_least_one_zone():
    fs = build_dragzone_formset(data={
        "zones-TOTAL_FORMS": "0", "zones-INITIAL_FORMS": "0",
        "zones-MIN_NUM_FORMS": "0", "zones-MAX_NUM_FORMS": "1000",
    })
    assert not fs.is_valid()


def test_formset_rejects_out_of_range_coords():
    fs = build_dragzone_formset(data={
        "zones-TOTAL_FORMS": "1", "zones-INITIAL_FORMS": "0",
        "zones-MIN_NUM_FORMS": "0", "zones-MAX_NUM_FORMS": "1000",
        "zones-0-correct_label": "A",
        "zones-0-x": "0.9", "zones-0-y": "0.0", "zones-0-w": "0.5", "zones-0-h": "0.2",
        "zones-0-order": "0",
    })
    assert not fs.is_valid()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_questions_2dii_form.py -v`
Expected: FAIL with `ImportError: cannot import name 'DragToImageQuestionElementForm'`.

- [ ] **Step 3: Add the form, formset, and registration**

```python
# courses/element_forms.py — imports: add DragToImageQuestionElement, DragZone
# to the existing courses.models import; import inlineformset_factory is already used.


class DragToImageQuestionElementForm(_MarkingFieldsMixin, _CourseScopedMediaForm):
    media_kind = "image"

    class Meta:
        model = DragToImageQuestionElement
        # stem + explanation included (mirroring MatchPairQuestionElementForm) — the
        # spec calls stem "the optional prompt above the image", the render template
        # prints el.stem, and _question_has_math scans it. Omitting them would make
        # an unauthored, dead feature. (The spec §6 field list was incomplete here.)
        fields = [
            "stem", "media", "alt", "distractors", "explanation",
            "marking_mode", "max_attempts", "max_marks",
        ]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
            "distractors": forms.Textarea(attrs={"rows": 2}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)  # mixin -> _CourseScopedMediaForm (strips course)
        self.fields["media"].required = True


class BaseDragZoneFormSet(forms.BaseInlineFormSet):
    """At least one non-deleted, fully-filled zone. Mirrors BaseMatchPairFormSet:
    min_num/validate_min are NOT used (they miscount DELETE/empty extra rows)."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [
            f for f in self.forms
            if f.cleaned_data
            and not f.cleaned_data.get("DELETE")
            and f.cleaned_data.get("correct_label")
        ]
        if len(kept) < 1:
            raise forms.ValidationError(_("Add at least one zone."))


DragZoneFormSet = inlineformset_factory(
    DragToImageQuestionElement,
    DragZone,
    formset=BaseDragZoneFormSet,
    fields=["correct_label", "x", "y", "w", "h", "order"],
    extra=0,
    can_delete=True,
)


def build_dragzone_formset(*, data=None, files=None, instance=None, prefix="zones"):
    """Construct the DragZone inline formset (mirror of build_matchpair_formset)."""
    return DragZoneFormSet(data=data, files=files, instance=instance, prefix=prefix)
```

The per-row coordinate range is enforced by `DragZone.clean()` (Task 1) because `inlineformset_factory` calls `instance.full_clean()` during `form.is_valid()`. (Verify the test for out-of-range passes; if the formset does not call model `clean`, add an explicit `clean()` to the row `ModelForm` calling `self.instance.clean()` and `add_error`.)

Register in `FORM_FOR_TYPE`:

```python
FORM_FOR_TYPE = {
    # ... existing ...
    "matchpairquestion": MatchPairQuestionElementForm,
    "dragtoimagequestion": DragToImageQuestionElementForm,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_questions_2dii_form.py -v`
Expected: PASS. If `test_formset_rejects_out_of_range_coords` fails (model clean not invoked by formset), add a row-form `clean()` that calls `self.instance.clean()` via a custom `form=` on `inlineformset_factory`, then re-run.

- [ ] **Step 5: Commit**

```bash
git add courses/element_forms.py tests/test_questions_2dii_form.py
git commit -m "feat(2d-ii): drag-to-image form, zone formset, FORM_FOR_TYPE registration"
```

---

### Task 5: Builder persist branch (zones + course-scoping)

**Files:**
- Modify: `courses/builder.py` (add `dragtoimagequestion` branch in the `elif type_key` chain in `save_element`, before the `else`)
- Test: `tests/test_questions_2dii_builder.py`

**Interfaces:**
- Consumes: `DragToImageQuestionElementForm`, `build_dragzone_formset` (Task 4); `ElementFormInvalid`, `course` (in scope in `save_element`).
- Produces: a persisted `DragToImageQuestionElement` with its `DragZone` rows; raises `ElementFormInvalid(form, formset)` on invalid.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_questions_2dii_builder.py
import pytest

from courses import builder
from courses.models import DragToImageQuestionElement
from tests.factories import CourseFactory, MediaAssetFactory, make_quiz_unit

pytestmark = pytest.mark.django_db


def test_save_element_creates_zones():
    course = CourseFactory()
    unit = make_quiz_unit(course=course)
    media = MediaAssetFactory(course=course, kind="image")
    post = {
        "type": "dragtoimagequestion",
        "media": str(media.pk),
        "alt": "Cell",
        "distractors": "D",
        "marking_mode": "A", "max_attempts": "1", "max_marks": "1",
        "zones-TOTAL_FORMS": "2", "zones-INITIAL_FORMS": "0",
        "zones-MIN_NUM_FORMS": "0", "zones-MAX_NUM_FORMS": "1000",
        "zones-0-correct_label": "A", "zones-0-x": "0.1", "zones-0-y": "0.1",
        "zones-0-w": "0.2", "zones-0-h": "0.2", "zones-0-order": "0",
        "zones-1-correct_label": "B", "zones-1-x": "0.5", "zones-1-y": "0.5",
        "zones-1-w": "0.2", "zones-1-h": "0.2", "zones-1-order": "1",
    }
    # Verified signature: save_element(course, unit_pk, type_key, element_ref, post_data, files)
    # Create is gated on `element_ref == "new"` (builder.py:213); any other value (incl.
    # None) hits the edit path and raises ConflictError. Pass the literal "new".
    builder.save_element(course, unit.pk, "dragtoimagequestion", "new", post, None)
    q = DragToImageQuestionElement.objects.get()
    assert q.expected_tokens() == ["A", "B"]
```

The signature is `save_element(course, unit_pk, type_key, element_ref, post_data, files)` — all positional, `unit_pk` (not the unit object), `element_ref="new"` for a create (matching `element_save`'s `request.POST.get("element", "new")`).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_questions_2dii_builder.py -v`
Expected: FAIL — falls into the `else` branch, constructs the form without the formset, saves zero zones (or 400/validation error).

- [ ] **Step 3: Add the persist branch**

```python
# courses/builder.py — insert as a NEW elif in the existing chain, AFTER the
# `elif type_key == "matchpairquestion":` block and BEFORE the final `else:`.
# At that point `course`, `unit_pk`-derived context, `post_data`, `files`, and the
# computed `instance` are all in scope (the matchpair branch above uses `instance`
# and `post_data`/`files` the same way). Do NOT place it as the first `if`.
    elif type_key == "dragtoimagequestion":
        from courses.element_forms import (
            DragToImageQuestionElementForm,
            build_dragzone_formset,
        )

        form = DragToImageQuestionElementForm(
            data=post_data, files=files, instance=instance, course=course
        )
        form_valid = form.is_valid()
        formset = build_dragzone_formset(
            data=post_data, files=files, instance=instance
        )
        if not form_valid or not formset.is_valid():
            raise ElementFormInvalid(form, formset)
        obj = form.save()
        formset.instance = obj
        formset.save()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_questions_2dii_builder.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/builder.py tests/test_questions_2dii_builder.py
git commit -m "feat(2d-ii): builder persist branch creates zones with course-scoped form"
```

---

### Task 6: views_manage wiring — allowlists, the three `course=` gates, add-menu

**Files:**
- Modify: `courses/views_manage.py` (allowlists in `element_add`/`element_save`; extend the `("image","video")` gate at `_render_open_form` ~704 and `element_form` ~873 to include `"dragtoimagequestion"`)
- Modify: `templates/courses/manage/editor/_add_menu.html` (new button)
- Test: `tests/test_questions_2dii_authoring_views.py`

**Interfaces:**
- Consumes: the form/formset/builder from Tasks 4–5.
- Produces: working add-open, save, and edit-open HTTP paths; the `media` field course-scoped at all three gates.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_questions_2dii_authoring_views.py
import pytest

from courses.models import Element
from tests.factories import (
    CourseFactory, MediaAssetFactory, make_pa, add_element,
    DragToImageQuestionElementFactory, DragZoneFactory,
)
from courses.models import ContentNode

pytestmark = pytest.mark.django_db


def _quiz_unit(course):
    return ContentNode.objects.create(
        course=course, kind="unit", unit_type="quiz", title="U"
    )


from django.urls import reverse


def test_open_add_form_scopes_media(client):
    make_pa(client)
    course = CourseFactory()
    unit = _quiz_unit(course)
    mine = MediaAssetFactory(course=course, kind="image")
    other = MediaAssetFactory(course=CourseFactory(), kind="image")
    # element_add is a POST view reading type + unit from POST (views_manage.py:772)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "dragtoimagequestion", "unit": unit.pk},
    )
    body = resp.content.decode()
    assert str(mine.pk) in body and str(other.pk) not in body
    assert "zones-TOTAL_FORMS" in body  # zone formset wired into the open form


def test_edit_open_form_scopes_media(client):
    make_pa(client)
    course = CourseFactory()
    unit = _quiz_unit(course)
    q = DragToImageQuestionElementFactory(media=MediaAssetFactory(course=course, kind="image"))
    DragZoneFactory(question=q, correct_label="A")
    el = add_element(unit, q)
    other = MediaAssetFactory(course=CourseFactory(), kind="image")
    # element_form is a GET view keyed by slug + element pk (views_manage.py:864)
    resp = client.get(
        reverse("courses:manage_element_form", kwargs={"slug": course.slug, "pk": el.pk})
    )
    body = resp.content.decode()
    assert str(other.pk) not in body
    assert "zones-TOTAL_FORMS" in body
```

Route names verified in `courses/urls.py`: `manage_element_add` (POST, `<slug>`), `manage_element_form` (GET, `<slug>`/`<int:pk>`), `manage_element_save` (POST, `<slug>`). The existing `test_questions_2d_authoring_views.py` shows the same setup for matchpair — copy any auth/scaffolding details from it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_questions_2dii_authoring_views.py -v`
Expected: FAIL — either `"bad type"` 400 (allowlist) or `other.pk` present (gate not extended).

- [ ] **Step 3: Extend the allowlists**

In `element_add` and `element_save`, add `"dragtoimagequestion"` to the `if type_key not in (...)` allowlist tuple in both.

- [ ] **Step 4: Extend the three `course=` gates**

```python
# courses/views_manage.py  (_render_open_form ~704)
extra = {"course": unit.course} if type_key in ("image", "video", "dragtoimagequestion") else {}
# courses/views_manage.py  (element_form ~873)
extra = {"course": course} if type_key in ("image", "video", "dragtoimagequestion") else {}
```

(The save path's `course=` is already handled by Task 5's builder branch; the 422 re-render reuses `e.form` from there, so no separate gate.)

- [ ] **Step 5: Wire `build_dragzone_formset` into the open paths (both sites, concrete)**

Two distinct functions each special-case the formset types. Add a `dragtoimagequestion` branch to **both**, mirroring the verified matchpair blocks.

In `_render_open_form` (`views_manage.py` ~723, the `elif type_key == "matchpairquestion" and formset is None:` block):

```python
    elif type_key == "matchpairquestion" and formset is None:
        from courses.element_forms import build_matchpair_formset
        formset = build_matchpair_formset(instance=instance)
    elif type_key == "dragtoimagequestion" and formset is None:
        from courses.element_forms import build_dragzone_formset
        formset = build_dragzone_formset(instance=instance)
```

In `element_form` (`views_manage.py` ~878, the `elif type_key == "matchpairquestion":` block):

```python
    elif type_key == "matchpairquestion":
        from courses.element_forms import build_matchpair_formset
        formset = build_matchpair_formset(instance=el.content_object)
    elif type_key == "dragtoimagequestion":
        from courses.element_forms import build_dragzone_formset
        formset = build_dragzone_formset(instance=el.content_object)
```

Add an assertion to the Step 1 tests that the open form actually contains the zone formset (so a silently-absent formset can't pass):

```python
    assert "zones-TOTAL_FORMS" in body
```

- [ ] **Step 6: Add the add-menu button**

```django
{# templates/courses/manage/editor/_add_menu.html — add alongside the matchpair button #}
<button type="button" class="add-menu__item" data-add-type="dragtoimagequestion">
  <span class="add-menu__icon">🖼️</span>{% trans "Drag to image" %}
</button>
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_questions_2dii_authoring_views.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add courses/views_manage.py templates/courses/manage/editor/_add_menu.html tests/test_questions_2dii_authoring_views.py
git commit -m "feat(2d-ii): views_manage allowlists, course= gates, add-menu button"
```

---

### Task 7: Authoring partial + editor script tag + alt warning

**Files:**
- Create: `templates/courses/manage/editor/_edit_dragtoimagequestion.html`
- Modify: `templates/courses/manage/editor/editor.html` (load `zone-editor.js`)
- Create: `courses/static/courses/js/zone-editor.js`
- Test: covered by Task 6 view tests (open form renders) + Task 9 e2e (canvas behavior)

**Interfaces:**
- Consumes: the open-form formset wiring (Task 6); `media_picker.js` (existing image picker).
- Produces: the `_edit_<type_key>.html` partial `_host_form.html` includes; the loaded canvas module.

- [ ] **Step 1: Create the authoring partial**

Mirror `_edit_matchpairquestion.html`. It renders the media picker, alt (+ server-side empty-alt warning), the zone formset rows (hidden numeric coord inputs the canvas writes), distractors, and the marking-fields include.

```django
{# templates/courses/manage/editor/_edit_dragtoimagequestion.html #}
{% load i18n %}
<div class="el-editor el-editor--question el-editor--dragimage" data-zone-editor>
  <label class="el-editor__label">{% trans "Prompt (optional)" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="stem" class="rte-source" data-rte-source rows="2">{{ form.stem.value|default:"" }}</textarea>
  </div>

  <label class="el-editor__label">{% trans "Image" %}</label>
  {# reuse the same media-picker widget markup _edit_image.html uses for form.media #}
  {{ form.media }}
  <label class="el-editor__label">{% trans "Alt text" %}</label>
  <input type="text" name="alt" value="{{ form.alt.value|default:'' }}"
         placeholder="{% trans 'Describe the image — screen-reader users answer via the numbered dropdowns below it' %}">
  {% if not form.instance.alt and not form.alt.value %}
    <p class="el-editor__hint el-editor__hint--warn">
      {% trans "No alt text — recommended so screen-reader users have context." %}
    </p>
  {% endif %}

  <label class="el-editor__label">{% trans "Zones" %}</label>
  <p class="el-editor__hint">{% trans "Drag on the image to draw a zone, then name its label." %}</p>
  {{ formset.management_form }}
  <ul class="zone-rows" data-zone-rows>
    {% for f in formset %}
      <li class="zone-row" data-zone-row>
        {{ f.id }}
        {{ f.correct_label }}
        {{ f.x }} {{ f.y }} {{ f.w }} {{ f.h }} {{ f.order }}
        {% if formset.can_delete %}<label class="zone-row__del">{{ f.DELETE }} {% trans "Remove" %}</label>{% endif %}
      </li>
    {% endfor %}
  </ul>
  {# Clone template for the canvas. extra=0 means zero rows for a fresh question, so the
     editor.js add-row idiom (clone the last row) has nothing to clone — render the
     formset empty_form (with its __prefix__ placeholders) as a hidden template the
     canvas clones, replacing __prefix__ with the new index. #}
  <template data-zone-empty>
    <li class="zone-row" data-zone-row>
      {{ formset.empty_form.id }}
      {{ formset.empty_form.correct_label }}
      {{ formset.empty_form.x }} {{ formset.empty_form.y }} {{ formset.empty_form.w }} {{ formset.empty_form.h }} {{ formset.empty_form.order }}
      {% if formset.can_delete %}<label class="zone-row__del">{{ formset.empty_form.DELETE }} {% trans "Remove" %}</label>{% endif %}
    </li>
  </template>
  {% for e in formset.non_form_errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Extra labels (distractors, one per line)" %}</label>
  <textarea name="distractors" rows="2">{{ form.distractors.value|default:"" }}</textarea>

  {% include "courses/manage/editor/_marking_fields.html" %}

  <label class="el-editor__label">{% trans "Explanation (optional)" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="explanation" class="rte-source" data-rte-source rows="2">{{ form.explanation.value|default:"" }}</textarea>
  </div>
</div>
```

Confirm the media-picker markup matches `_edit_image.html` (read it; copy its `form.media` rendering + any `data-media-picker` hook so `media_picker.js` enhances it).

- [ ] **Step 2: Create the canvas module**

```javascript
// courses/static/courses/js/zone-editor.js
// Rectangle-drawing authoring canvas for drag-to-image. Reads/writes the DragZone
// formset's numeric x/y/w/h fields (fractions 0..1); recompacts `order` on every
// add/delete/reorder so ["order","pk"] stays gap-free and aligned with badge index.
(function () {
  "use strict";
  function init(root) {
    (root || document).querySelectorAll("[data-zone-editor]").forEach(setup);
  }
  function setup(editor) {
    if (editor.dataset.zoneReady) return;
    editor.dataset.zoneReady = "1";
    // 1. find the image, build an overlay stage, draw existing rows as rectangles
    //    from each row's x/y/w/h inputs.
    // 2. pointer-drag on the image -> ADD A ROW by cloning the hidden
    //    `<template data-zone-empty>` (rendered by _edit_dragtoimagequestion.html from
    //    `{{ formset.empty_form }}`), replacing the `__prefix__` placeholder in every
    //    name/id/for with the current TOTAL_FORMS index, appending to [data-zone-rows],
    //    bumping the `-TOTAL_FORMS` input, then writing fractional coords into the new
    //    row's x/y/w/h inputs.
    //    NOTE: there is NO existing JS add-row helper to copy literally — editor.js
    //    `addChoiceRow` (~line 222) clones the *last existing row* and renumbers it with
    //    `/([-_])\d+([-_])/` (already-numbered rows only); the match-pairs `data-pair-add`
    //    button has no handler at all. This canvas instead clones the empty_form template,
    //    so the swap must replace the LITERAL string `__prefix__` (e.g.
    //    attr.replace(/__prefix__/g, idx) on every name/id/for) — the `\d+` regex would
    //    leave `__prefix__` untouched. Borrow only the clone+bump-TOTAL_FORMS shape.
    // 3. click a rectangle/row -> select (highlight both); handles resize, body moves;
    //    clamp to [0,1] and x+w,y+h <= 1; write fractions back.
    // 4. delete -> tick the row's DELETE checkbox, remove the overlay.
    // 5. after any add/delete/reorder, renumber every kept row's `order` input 0..n.
  }
  window.libliZoneEditor = init;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { init(); });
  } else { init(); }
})();
```

Flesh out steps 1–5 following `editor_dnd.js`'s existing add-row idiom (the project already clones formset rows there for choice/match-pairs). Keep it dependency-free.

- [ ] **Step 3: Load the module in the editor**

```django
{# templates/courses/manage/editor/editor.html — add alongside editor_dnd.js (line ~57) #}
  <script src="{% static 'courses/js/zone-editor.js' %}" defer></script>
```

- [ ] **Step 4: Verify the open form renders (no TemplateDoesNotExist)**

Run: `pytest tests/test_questions_2dii_authoring_views.py -v`
Expected: PASS (the open-form view now finds `_edit_dragtoimagequestion.html`).

- [ ] **Step 5: Commit**

```bash
git add templates/courses/manage/editor/_edit_dragtoimagequestion.html templates/courses/manage/editor/editor.html courses/static/courses/js/zone-editor.js
git commit -m "feat(2d-ii): authoring partial, zone-editor canvas, editor script tag"
```

---

### Task 8: Consumption touchpoints — prefetch, KaTeX, CT gate, resume routing, results

**Files:**
- Modify: `courses/views.py` (prefetch `zones`; `_question_has_math` branch in `build_lesson_context`; `question_models`/`question_ct_ids` gate)
- Test: `tests/test_questions_2dii_consumption.py`

**Interfaces:**
- Consumes: `DragToImageQuestionElement` (Task 1); `quiz.rehydrate`/`answer_from_json`/`answer_to_json` (existing, default branch); `_results_row` (existing, generic).
- Produces: lesson/quiz pages that prefetch `zones`, load KaTeX when a drag-to-image stem/label has math, and gate `has_questions` correctly.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_questions_2dii_consumption.py
import pytest

from courses import quiz
from tests.factories import (
    DragToImageQuestionElementFactory, DragZoneFactory, add_element, make_quiz_unit,
)

pytestmark = pytest.mark.django_db


def test_resume_routing_uses_default_branch():
    q = DragToImageQuestionElementFactory()
    DragZoneFactory(question=q, correct_label="A", order=0)
    # answer_to_json passes the list through unchanged; answer_from_json returns it
    payload = ["A", ""]
    # answer_to_json(answer) takes ONE arg (no question); answer_from_json/rehydrate
    # take (question, latest_answer) — do not conflate.
    assert quiz.answer_to_json(payload) == payload
    assert quiz.answer_from_json(q, payload) == payload
    sel, vals = quiz.rehydrate(q, payload)
    assert sel == set() and vals == payload


def test_results_row_rebuilds_reveal_for_unanswered():
    # mark(build_answer(empty)) must yield a per-zone reveal without error
    q = DragToImageQuestionElementFactory()
    DragZoneFactory(question=q, correct_label="A", order=0)
    DragZoneFactory(question=q, correct_label="B", order=1)
    from django.http import QueryDict
    r = q.mark(q.build_answer(QueryDict()))
    assert len(r.reveal) == 2 and all("accepted" in d for d in r.reveal)
```

For the prefetch/KaTeX/CT-gate, add a view-level test mirroring `test_questions_2d_views_touchpoints.py`. **The KaTeX test must put the math in a `correct_label` (or `distractors`) and keep `stem` math-free** — `_question_has_math` returns `True` from the top-level `has_math_delimiters(q.stem)` check *before* any isinstance branch, so a question with math in `stem` would pass even if the new `DragToImageQuestionElement` branch were never added (false pass). With math only in `correct_label`, the assertion genuinely exercises Task 8 Step 4's branch. Also assert `has_questions` truthy; optionally assert query count with `django_assert_num_queries`.

- [ ] **Step 2: Run tests to verify they fail / partially pass**

Run: `pytest tests/test_questions_2dii_consumption.py -v`
Expected: the resume/results tests PASS already (generic reuse); the view-level KaTeX/CT-gate test FAILS until `views.py` is touched.

- [ ] **Step 3: Add the prefetch**

In `lesson_unit` and `quiz_unit`, alongside the existing `fill_qs`/`dragfill_qs`/`matchpair_qs` prefetch blocks:

```python
dragimage_qs = [q for q in questions if isinstance(q, DragToImageQuestionElement)]
if dragimage_qs:
    prefetch_related_objects(dragimage_qs, "zones")
```

(Match the exact local-variable / loop idiom already used for the other DnD types in `views.py`.)

- [ ] **Step 4: Add the KaTeX branch**

In `_question_has_math` (closure in `build_lesson_context`), add a branch using the existing `has_math_delimiters` helper (imported at `views.py:25`), mirroring the dragfill/matchpair branches. The closure already checks `has_math_delimiters(q.stem)` at the top, so the branch only needs distractors + labels:

```python
if isinstance(q, DragToImageQuestionElement):
    return has_math_delimiters(q.distractors) or any(
        has_math_delimiters(z.correct_label) for z in q.zones.all()
    )
```

Place it alongside the other `isinstance(q, ...)` branches. Also add `DragToImageQuestionElement` to the `from courses.models import (...)` in `views.py`.

- [ ] **Step 5: Add the CT gate**

Add `DragToImageQuestionElement` to the `question_models` list backing `question_ct_ids`/`has_questions` in `build_lesson_context`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_questions_2dii_consumption.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add courses/views.py tests/test_questions_2dii_consumption.py
git commit -m "feat(2d-ii): consumption touchpoints (prefetch, KaTeX, CT gate); resume/results reuse tests"
```

---

### Task 9: JS — tap-to-assign + overlay-target discriminator in dnd.js

**Files:**
- Modify: `courses/static/courses/js/dnd.js`
- Test: `tests/test_e2e_questions_2dii.py` (Playwright; covers drag, tap, no-JS select)

**Interfaces:**
- Consumes: existing `enhance()`, `setSelect()`, the `[data-dnd]` blocks, `[data-zone]` badges (Task 3), `[data-dnd-pool]`.
- Produces: tap-to-assign for all three DnD types + on-image overlay targets for drag-to-image.

- [ ] **Step 1: Extend `enhance()` — discriminator + overlay targets + tap**

In `dnd.js`, after building the chip pool, branch on the discriminator:

```javascript
// Inside enhance(block), choose target strategy:
var stage = block.querySelector("[data-dragimage-stage]");
var badges = Array.prototype.slice.call(block.querySelectorAll("[data-zone]"));
// If image-overlay block: build absolutely-positioned overlay targets from each
// badge's data-x/y/w/h, linked to selects[Number(badge.dataset.zone)].
// Else: build inline slots next to each select (existing behavior).
```

Add a shared "armed chip" state and tap handlers per the spec's tap state table:
- tap chip → toggle armed
- armed + empty target → assign (`setSelect`), disarm
- armed + filled target → overwrite, disarm
- unarmed + filled target → clear (`setSelect(sel, "")`)
- unarmed + empty target → no-op

Reuse `setSelect(sel, value)` so drag/tap/keyboard/no-JS stay byte-identical on assignment.

- [ ] **Step 2: Write the e2e tests**

```python
# tests/test_e2e_questions_2dii.py
# Mirror tests/test_e2e_questions_2d.py setup (Playwright fixtures, login, author flow).
# Cases:
#  - JS drag: author 2 zones + distractor; student drags chips onto overlay targets;
#    submit; correct/partial feedback.
#  - tap-to-assign: tap chip then tap target; assert recorded answer == drag answer.
#  - no-JS (<select>): set the selects directly; submit; same payload.
#  - quiz: exhaust attempts -> reveal shows accepted labels; assert NO accepted-label
#    text in the pre-reveal fragment (no-leak).
#  - tap state table: armed+filled overwrites (not clears); unarmed+filled clears.
#  - KaTeX (quiz): a \(x\) label typesets in chip + reveal (a .katex node); the native
#    <option> shows raw \(x\) source.
#  - no-JS authoring edit-existing: open an existing question with JS off, edit a zone's
#    numeric coords + label, save, confirm persisted.
```

Copy the concrete Playwright scaffolding from `test_e2e_questions_2d.py` (fixtures, the author-via-editor helper, the answer-and-submit helper) and adapt selectors to `.el--dragimage` / `[data-zone]` / `.dnd__chip`.

- [ ] **Step 3: Run the e2e suite**

Run: `pytest tests/test_e2e_questions_2dii.py -v`
Expected: PASS (headless browser). Iterate on `dnd.js` until drag, tap, and no-JS all record identical answers and no-leak holds.

- [ ] **Step 4: Commit**

```bash
git add courses/static/courses/js/dnd.js tests/test_e2e_questions_2dii.py
git commit -m "feat(2d-ii): dnd.js tap-to-assign + image overlay targets; e2e drag/tap/no-JS"
```

---

### Task 10: i18n (PL) + collectstatic check

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: `tests/test_i18n_questions_2dii.py`

**Interfaces:**
- Consumes: all `{% trans %}` / `_()` strings added in Tasks 1–9.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_i18n_questions_2dii.py
# Mirror tests/test_i18n_questions_2d.py: render the add-menu / authoring partial under
# activate("pl") and assert the Polish strings appear (e.g. the "Drag to image" label
# and the "Add at least one zone." validation message render translated).
```

- [ ] **Step 2: Extract and translate**

Run: `python manage.py makemessages -l pl`
Then fill in the `msgstr` for every new `msgid` (Drag to image; Add at least one zone.; Zone position…; Zone must have a positive size.; Zone must not extend past the image.; Drag on the image to draw a zone…; No alt text — recommended…; Describe the image…; Extra labels (distractors…); A token is too long… if reused; etc.).

Run: `python manage.py compilemessages`

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/test_i18n_questions_2dii.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_i18n_questions_2dii.py
git commit -m "i18n(2d-ii): Polish strings for drag-to-image"
```

---

### Task 11: Full-suite green + DoD

**Files:** none (verification task)

- [ ] **Step 1: Run the whole suite + migration check**

Run: `pytest -q && python manage.py makemigrations --check && ruff check .`
Expected: all green; no missing migrations; no lint errors.

- [ ] **Step 2: Manual smoke (optional, via the run skill)**

Author a drag-to-image question in a quiz unit, answer it three ways (drag, tap, dropdown), confirm scoring + reveal + resume.

- [ ] **Step 3: Commit any fixups**

```bash
git add -A && git commit -m "test(2d-ii): full-suite green"
```

---

## Self-Review

**1. Spec coverage**

| Spec section | Task |
|---|---|
| §2.1/§2.2 model, `ZONE_COORD_EPSILON`, coord clean | Task 1 |
| §2.3 persistence / resume routing | Task 8 |
| §3.1 render template + `render_image_selects` tag + badges/data-* | Tasks 2, 3 |
| §3.2 marking (substrate reuse) | Tasks 1, 2 |
| §3.3 withhold / empty-guard (reused) | Tasks 3, 9 (e2e) |
| §4.1 zone-editor canvas + no-JS edit-existing | Task 7 |
| §4.2 tap-to-assign + discriminator | Task 9 |
| §5 prefetch / KaTeX / CT gate / resume / results | Task 8 |
| §5 add-menu / allowlists / 3 course= gates / `_edit` partial / `editor.html` script | Tasks 6, 7 |
| §5 `builder.save_element` branch | Task 5 |
| §6 form + formset (BaseDragZoneFormSet) | Task 4 |
| §7 invariants/tests (no-leak, transport-agnostic, KaTeX-in-option) | Tasks 3, 9 |
| §7.5 migration 0018 dependency edge | Task 1 |
| i18n | Task 10 |

All sections map to a task.

**2. Placeholder scan:** The only intentionally-prose-described code is the `zone-editor.js` canvas internals (Task 7 Step 2) and the e2e bodies (Task 9 Step 2), which point to the exact existing files to mirror (`editor_dnd.js`, `test_e2e_questions_2d.py`) — these are inherently UI/integration code without a clean unit-test-first cycle; the structure, hooks, and acceptance behavior are fully specified. All Python deliverables have complete code.

**3. Type consistency:** `expected_tokens()`, `build_answer(post)->list`, `mark(answer)->MarkResult`, `dnd.render_zone_selects(zones, pool, chosen)`, `render_image_selects(el, submitted_values)`, `build_dragzone_formset(*, data, files, instance, prefix="zones")`, `DragToImageQuestionElementForm(_MarkingFieldsMixin, _CourseScopedMediaForm)`, `ZONE_COORD_EPSILON`, `type_key="dragtoimagequestion"` vs template `dragtoimagequestionelement.html` — all consistent across tasks.
