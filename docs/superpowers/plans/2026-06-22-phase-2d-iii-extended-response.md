# Phase 2d-iii — Extended-response + the `[R]` human-review path — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the 9th/final question type — `ExtendedResponseQuestionElement` (long free text, `[A]`-marked by required/forbidden keywords) — plus the generic `[R]` "awaiting review" pending-score substrate and a 2-column persistence seam for Phase 3's teacher queue.

**Architecture:** A single-row `QuestionElement` subclass (no sub-tables, plain-string answer) mirroring `ShortTextQuestionElement`, scored by a pure `courses/keywords.py` helper. It reuses the 2c quiz machinery and 2a/2b formative machinery wholesale — **no new view functions**. **Grounded deviation from spec §1.2/§3.4:** the per-question `[R]`/`[N]` feedback cards (`_quiz_question_feedback.html:8-11`) and the results-page `[R]`/`[N]` badges (`quiz_results.html:21-22`) **already exist** from 2c and are **type-agnostic** (keyed on `neutral`/`outcome`, not type), so they work for this type with no change. The genuinely-new substrate work is only: the **pending-review footer**, the **"up to M marks"** detail on the `[R]` results row, the **`answered`-flag reveal** for the extended-response reveal partial, and the **seam columns**.

**Tech Stack:** Python 3.13, Django 5.2, PostgreSQL, pytest + factory_boy, Playwright (e2e), stdlib `re` (no new dependency).

## Global Constraints

Copied verbatim from the spec; every task implicitly includes these:

- **No new dependency.** The keyword matcher is stdlib `re` + the existing `courses.marking.normalize_text`.
- **No new view functions, URLs, or persistence model** beyond the 2 nullable `QuestionResponse` columns. Reuse `check_answer`/`quiz_answer`/`quiz_finish`/`quiz_results` and `QuizSubmission`/`QuestionResponse`/`Attempt`.
- **`EXTENDED_RESPONSE_MAX_CHARS = 10_000`**, defined in `courses/models.py`; the student `<textarea maxlength="10000">` mirrors it (a drift-guarded coupling — a test asserts they match).
- **Whole-word/phrase matching**, case-folded via `normalize_text` (diacritics preserved, **not** stripped — accent-insensitivity is a non-goal). Never substring.
- **Keyword scoring:** `fraction = (R_found/R_total) × (1 − F_found/F_total)`; each factor is `1.0` when its list is empty; `correct = (fraction == 1.0)`.
- **i18n:** all new strings wrapped for EN/PL with real Polish; **no `#~` obsolete entries** in the `.po` (the project forbids them — `test_po_catalog_clean`).
- **Per task:** run `ruff check --fix <files> && ruff format <files>`, then `python manage.py makemigrations --check` and `python manage.py check` must be clean. Default test run is `pytest -m "not e2e"` against real PostgreSQL.
- **Carries the platform no-JS `csrf_token` ticket** (empty token in `render_to_string` without a request) at exact parity with every other type — not fixed here.

---

## File Structure

**New files:**
- `courses/keywords.py` — the pure `mark_keywords(answer, required, forbidden)` helper.
- `templates/courses/elements/extendedresponsequestionelement.html` — student-facing render (textarea + feedback container).
- `templates/courses/elements/_reveal_extendedresponse.html` — per-keyword reveal (answered) / neutral guide (unanswered).
- `templates/courses/manage/editor/_edit_extendedresponsequestion.html` — authoring editor partial.
- `tests/test_questions_2diii_keywords.py`, `tests/test_questions_2diii_model.py`, `tests/test_questions_2diii_form.py`, `tests/test_questions_2diii_authoring.py`, `tests/test_questions_2diii_quiz.py`, `tests/test_questions_2diii_results.py`, `tests/test_e2e_questions_2diii.py`.

**Modified files:**
- `courses/models.py` — `EXTENDED_RESPONSE_MAX_CHARS`, `ExtendedResponseQuestionElement`, `QuestionResponse.reviewed_at`/`reviewed_by`.
- `courses/migrations/0019_extendedresponse.py` — generated.
- `courses/element_forms.py` — `ExtendedResponseQuestionElementForm` + `FORM_FOR_TYPE` entry.
- `courses/views.py` — `question_models` list (lesson CT-gate); `_results_row` `answered` key; `quiz_results` pending tally.
- `courses/views_manage.py` — `_EDITOR_TYPE_LABELS` + both `type_key` allowlists.
- `courses/templatetags/courses_manage_extras.py` — `_ELEMENT_LABELS`.
- `templates/courses/manage/editor/_add_menu.html` — add-element button.
- `templates/courses/quiz_results.html` — `answered=` on the reveal include, "up to M marks" on the `[R]` badge, the pending footer.
- `tests/factories.py` — `ExtendedResponseQuestionElementFactory`.
- `locale/pl/LC_MESSAGES/django.po` — Polish translations.

---

## Task 1: `mark_keywords` pure helper

**Files:**
- Create: `courses/keywords.py`
- Test: `tests/test_questions_2diii_keywords.py`

**Interfaces:**
- Consumes: `courses.marking.normalize_text` (signature `normalize_text(s, *, case_sensitive=False)`).
- Produces: `mark_keywords(answer: str, required: list[str], forbidden: list[str]) -> tuple[float, tuple, bool]` returning `(fraction, reveal, correct)`. `reveal` is a tuple of `{"keyword": str, "kind": "required"|"forbidden", "found": bool}` dicts, required-then-forbidden in author order, `keyword` already `.strip()`-ed for display.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_questions_2diii_keywords.py
import math

from courses.keywords import mark_keywords


def _frac(answer, required, forbidden):
    return mark_keywords(answer, required, forbidden)[0]


def test_all_required_no_forbidden_is_full():
    assert _frac("alpha beta", ["alpha", "beta"], []) == 1.0


def test_partial_required():
    assert _frac("alpha only", ["alpha", "beta"], []) == 0.5


def test_only_forbidden_zero_guard_full_when_clean():
    # No required -> req factor 1.0; no forbidden present -> 1.0.
    assert _frac("nice clean text", [], ["banned"]) == 1.0


def test_only_required_zero_guard():
    assert _frac("alpha", ["alpha"], []) == 1.0


def test_forbidden_graduated_penalty():
    # all required + 1 of 4 forbidden -> 1 * (1 - 0.25) = 0.75
    frac = _frac("alpha w1", ["alpha"], ["w1", "w2", "w3", "w4"])
    assert math.isclose(frac, 0.75)


def test_single_forbidden_is_hard_fail():
    assert _frac("alpha banned", ["alpha"], ["banned"]) == 0.0


def test_correct_iff_fraction_one():
    _, _, correct = mark_keywords("alpha beta", ["alpha", "beta"], ["bad"])
    assert correct is True
    _, _, correct2 = mark_keywords("alpha", ["alpha", "beta"], [])
    assert correct2 is False


def test_whole_word_not_substring():
    # "ion" must NOT match inside "question"; "cat" must NOT match "category".
    assert _frac("this is a question about category", ["ion", "cat"], []) == 0.0


def test_phrase_matches_contiguous_and_whitespace_collapsed():
    assert _frac("the French   Revolution began", ["French Revolution"], []) == 1.0
    assert _frac("French armies and a Revolution", ["French Revolution"], []) == 0.0


def test_accent_case_fold_match_but_not_accent_strip():
    # same accent, different case -> match; accent mismatch -> no match (non-goal).
    assert _frac("the révolté crowd", ["Révolté"], []) == 1.0
    assert _frac("the revolte crowd", ["Révolté"], []) == 0.0


def test_duplicate_occurrence_counts_once():
    assert _frac("alpha alpha alpha", ["alpha"], []) == 1.0


def test_reveal_shape_required_then_forbidden_stripped():
    _, reveal, _ = mark_keywords("alpha", ["  alpha ", "beta"], ["bad"])
    assert reveal == (
        {"keyword": "alpha", "kind": "required", "found": True},
        {"keyword": "beta", "kind": "required", "found": False},
        {"keyword": "bad", "kind": "forbidden", "found": False},
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_questions_2diii_keywords.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'courses.keywords'`.

- [ ] **Step 3: Write the implementation**

```python
# courses/keywords.py
"""Pure keyword scoring for the [A] extended-response type (Phase 2d-iii).

fraction = (R_found/R_total) * (1 - F_found/F_total), each factor 1.0 when its
list is empty. Whole-word/phrase match on normalize_text'd text (case-folded;
diacritics preserved). No DB, no randomness — referentially transparent."""

import re

from courses.marking import normalize_text


def _is_present(keyword, norm_answer):
    norm_kw = normalize_text(keyword)
    if not norm_kw:
        return False
    pattern = r"(?<!\w)" + re.escape(norm_kw) + r"(?!\w)"
    return bool(re.search(pattern, norm_answer))


def mark_keywords(answer, required, forbidden):
    norm_answer = normalize_text(answer)
    req_present = [_is_present(k, norm_answer) for k in required]
    forb_present = [_is_present(k, norm_answer) for k in forbidden]
    r_total, f_total = len(required), len(forbidden)
    r_found, f_found = sum(req_present), sum(forb_present)
    req_factor = (r_found / r_total) if r_total else 1.0
    forb_factor = (1 - f_found / f_total) if f_total else 1.0
    fraction = max(0.0, min(1.0, req_factor * forb_factor))
    reveal = tuple(
        {"keyword": k.strip(), "kind": "required", "found": p}
        for k, p in zip(required, req_present)
    ) + tuple(
        {"keyword": k.strip(), "kind": "forbidden", "found": p}
        for k, p in zip(forbidden, forb_present)
    )
    return fraction, reveal, fraction == 1.0
```

Note: the reveal stores `k.strip()` for display (realizing spec §3.3's "trim for display" in the helper, since Django templates have no `strip` filter). Matching is unaffected — `_is_present` normalizes the line independently.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_questions_2diii_keywords.py -v`
Expected: PASS (13 tests).

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix courses/keywords.py tests/test_questions_2diii_keywords.py
ruff format courses/keywords.py tests/test_questions_2diii_keywords.py
git add courses/keywords.py tests/test_questions_2diii_keywords.py
git commit -m "feat(2d-iii): pure mark_keywords helper for extended-response scoring"
```

---

## Task 2: `ExtendedResponseQuestionElement` model + seam columns + migration + factory

**Files:**
- Modify: `courses/models.py` (add constant + model; add 2 fields to `QuestionResponse`)
- Create: `courses/migrations/0019_extendedresponse.py` (generated)
- Modify: `tests/factories.py`
- Test: `tests/test_questions_2diii_model.py`

**Interfaces:**
- Consumes: `mark_keywords` (Task 1); `MarkResult` (from `courses.marking`); `_accepted_lines`, `QuestionElement`, `Element`, `GenericRelation`, `settings` (all already imported in `models.py`); base `QuestionElement.feedback_context` returning `{"el", "mark_result", "reveal_template"}`.
- Produces: `ExtendedResponseQuestionElement` with `required_keywords`/`forbidden_keywords` TextFields, `REVEAL_TEMPLATE`, `build_answer(post)->str`, `mark(answer)->MarkResult`, `feedback_context(mark_result)` (adds `answered=True`); `EXTENDED_RESPONSE_MAX_CHARS = 10_000`; `QuestionResponse.reviewed_at`/`reviewed_by`; `ExtendedResponseQuestionElementFactory`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_questions_2diii_model.py
import pytest
from django.db.models import QuerySet
from django.http import QueryDict

from courses.models import EXTENDED_RESPONSE_MAX_CHARS
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionResponse
from tests.factories import ExtendedResponseQuestionElementFactory

pytestmark = pytest.mark.django_db


def test_mark_full_credit():
    q = ExtendedResponseQuestionElementFactory(
        required_keywords="alpha\nbeta", forbidden_keywords=""
    )
    res = q.mark("alpha and beta")
    assert res.correct is True
    assert res.fraction == 1.0
    assert res.reveal[0]["keyword"] == "alpha"


def test_mark_partial_with_forbidden():
    q = ExtendedResponseQuestionElementFactory(
        required_keywords="alpha", forbidden_keywords="bad"
    )
    res = q.mark("alpha bad")
    assert res.fraction == 0.0
    assert res.correct is False


def test_build_answer_caps_length():
    q = ExtendedResponseQuestionElementFactory()
    post = QueryDict(mutable=True)
    post["answer"] = "x" * (EXTENDED_RESPONSE_MAX_CHARS + 50)
    assert len(q.build_answer(post)) == EXTENDED_RESPONSE_MAX_CHARS


def test_feedback_context_marks_answered():
    q = ExtendedResponseQuestionElementFactory(required_keywords="alpha")
    ctx = q.feedback_context(q.mark("alpha"))
    assert ctx["answered"] is True
    assert ctx["reveal_template"] == "courses/elements/_reveal_extendedresponse.html"


def test_seam_columns_default_null():
    f = QuestionResponse._meta.get_field("reviewed_at")
    assert f.null is True
    f2 = QuestionResponse._meta.get_field("reviewed_by")
    assert f2.null is True


def test_elements_generic_relation_present():
    q = ExtendedResponseQuestionElementFactory()
    assert isinstance(q.elements.all(), QuerySet)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_questions_2diii_model.py -v`
Expected: FAIL with `ImportError` (no `EXTENDED_RESPONSE_MAX_CHARS` / `ExtendedResponseQuestionElement`).

- [ ] **Step 3a: Add the constant + model to `courses/models.py`**

Place near the other `QuestionElement` subclasses (e.g. just after `ShortTextQuestionElement`):

```python
EXTENDED_RESPONSE_MAX_CHARS = 10_000


class ExtendedResponseQuestionElement(QuestionElement):
    """Long free text: [A] auto-marked by required/forbidden keywords, or
    [R] human-reviewed (Phase 3 queue) / [N] recorded. Single-row, no sub-tables."""

    REVEAL_TEMPLATE = "courses/elements/_reveal_extendedresponse.html"
    required_keywords = models.TextField(blank=True)
    forbidden_keywords = models.TextField(blank=True)
    elements = GenericRelation(Element)

    def build_answer(self, post):
        return post.get("answer", "")[:EXTENDED_RESPONSE_MAX_CHARS]

    def mark(self, answer):
        from courses.keywords import mark_keywords

        frac, reveal, correct = mark_keywords(
            answer,
            _accepted_lines(self.required_keywords),
            _accepted_lines(self.forbidden_keywords),
        )
        return MarkResult(correct=correct, fraction=frac, reveal=reveal)

    def feedback_context(self, mark_result):
        # The live reveal always follows a real submit -> answered=True.
        # The results page passes answered=row.answered explicitly instead.
        ctx = super().feedback_context(mark_result)
        ctx["answered"] = True
        return ctx
```

Construct `MarkResult` **by keyword** (never `MarkResult(*mark_keywords(...))` — the helper returns `(fraction, reveal, correct)` but `MarkResult`'s field order is `(correct, fraction, reveal)`, an invisible `bool`/`float` swap).

- [ ] **Step 3b: Add the seam columns to `QuestionResponse` in `courses/models.py`**

```python
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
```

These are the reserved Phase-3 hook — no 2d-iii code writes them.

- [ ] **Step 3c: Add the factory to `tests/factories.py`**

Mirror the existing `MatchPairQuestionElementFactory` (the question factories use a **class-ref** `model = <Class>`, not a `"courses.X"` string; there is **no** `ShortTextQuestionElementFactory`). Add `from courses.models import ExtendedResponseQuestionElement` to the imports at the top of `tests/factories.py`, then:

```python
class ExtendedResponseQuestionElementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ExtendedResponseQuestionElement

    stem = "Discuss the causes."
    required_keywords = "alpha"
    forbidden_keywords = ""
```

(The model defaults `marking_mode=AUTO` / `max_marks=Decimal("1")` apply; override per-test where needed.)

- [ ] **Step 3d: Generate the migration**

```bash
python manage.py makemigrations courses
```

Expected: creates `courses/migrations/0019_extendedresponse.py` with `CreateModel ExtendedResponseQuestionElement`, `AddField QuestionResponse.reviewed_at`, `AddField QuestionResponse.reviewed_by`, and an auto-added `swappable_dependency(settings.AUTH_USER_MODEL)`. **Generate, do not hand-write.** (If a sibling slice already took `0019`, accept the next number makemigrations assigns.)

- [ ] **Step 4: Run tests + migration check**

```bash
python manage.py makemigrations --check
python manage.py check
pytest tests/test_questions_2diii_model.py -v
```
Expected: makemigrations-check clean (no pending), `check` clean, 6 tests PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix courses/models.py tests/factories.py tests/test_questions_2diii_model.py
ruff format courses/models.py tests/factories.py tests/test_questions_2diii_model.py
git add courses/models.py courses/migrations/0019_extendedresponse.py tests/factories.py tests/test_questions_2diii_model.py
git commit -m "feat(2d-iii): ExtendedResponseQuestionElement model + review seam columns"
```

---

## Task 3: `ExtendedResponseQuestionElementForm` + registry

**Files:**
- Modify: `courses/element_forms.py`
- Test: `tests/test_questions_2diii_form.py`

**Interfaces:**
- Consumes: `_MarkingFieldsMixin`, `QuestionElement.MarkingMode`, the model from Task 2.
- Produces: `ExtendedResponseQuestionElementForm` (Meta-nested `fields`+`widgets`, cross-field `clean`); `FORM_FOR_TYPE["extendedresponsequestion"]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_questions_2diii_form.py
import pytest

from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import ExtendedResponseQuestionElementForm

pytestmark = pytest.mark.django_db


def _data(**over):
    base = {
        "stem": "Explain.",
        "explanation": "",
        "required_keywords": "",
        "forbidden_keywords": "",
        "marking_mode": "A",
        "max_attempts": "1",
        "max_marks": "1",
    }
    base.update(over)
    return base


def test_registered_in_form_for_type():
    assert FORM_FOR_TYPE["extendedresponsequestion"] is ExtendedResponseQuestionElementForm


def test_auto_with_no_keywords_rejected():
    form = ExtendedResponseQuestionElementForm(data=_data(marking_mode="A"))
    assert not form.is_valid()
    assert "at least one" in str(form.errors).lower()


def test_auto_with_marking_mode_omitted_from_post_rejected():
    # Hidden-field lesson path: marking_mode absent -> effective AUTO -> must still reject.
    data = _data()
    data.pop("marking_mode")
    form = ExtendedResponseQuestionElementForm(data=data)
    assert not form.is_valid()


def test_review_with_no_keywords_accepted():
    form = ExtendedResponseQuestionElementForm(data=_data(marking_mode="R"))
    assert form.is_valid(), form.errors


def test_auto_with_required_keyword_accepted():
    form = ExtendedResponseQuestionElementForm(data=_data(required_keywords="alpha"))
    assert form.is_valid(), form.errors
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_questions_2diii_form.py -v`
Expected: FAIL with `ImportError: cannot import name 'ExtendedResponseQuestionElementForm'`.

- [ ] **Step 3: Implement the form + register it**

Add two imports at the top of `courses/element_forms.py` (it currently imports the concrete subclasses but **not** the abstract base — the `clean()` below references `QuestionElement.MarkingMode`, which would `NameError` without it):

```python
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
```

Then add the form class:

```python
class ExtendedResponseQuestionElementForm(_MarkingFieldsMixin, forms.ModelForm):
    class Meta:
        model = ExtendedResponseQuestionElement
        fields = [
            "stem",
            "explanation",
            "required_keywords",
            "forbidden_keywords",
            "marking_mode",
            "max_attempts",
            "max_marks",
        ]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 3, "data-rte-source": ""}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
            "required_keywords": forms.Textarea(attrs={"rows": 3}),
            "forbidden_keywords": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        # Effective mode: _MarkingFieldsMixin makes marking_mode optional and the
        # lesson/hidden-field path omits it from POST, so an absent value means the
        # model default (AUTO) applies on save — validate against that.
        mode = cleaned.get("marking_mode") or QuestionElement.MarkingMode.AUTO
        if mode == QuestionElement.MarkingMode.AUTO:
            req = [ln for ln in (cleaned.get("required_keywords") or "").splitlines() if ln.strip()]
            forb = [ln for ln in (cleaned.get("forbidden_keywords") or "").splitlines() if ln.strip()]
            if not req and not forb:
                raise forms.ValidationError(
                    _("Auto-marked extended response needs at least one required or forbidden keyword.")
                )
        return cleaned
```

Add to the `FORM_FOR_TYPE` dict:

```python
    "extendedresponsequestion": ExtendedResponseQuestionElementForm,
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_questions_2diii_form.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix courses/element_forms.py tests/test_questions_2diii_form.py
ruff format courses/element_forms.py tests/test_questions_2diii_form.py
git add courses/element_forms.py tests/test_questions_2diii_form.py
git commit -m "feat(2d-iii): extended-response form with effective-mode keyword validation"
```

---

## Task 4: Student template + reveal partial

**Files:**
- Create: `templates/courses/elements/extendedresponsequestionelement.html`
- Create: `templates/courses/elements/_reveal_extendedresponse.html`
- Test: `tests/test_questions_2diii_model.py` (extend with render tests)

**Interfaces:**
- Consumes: the render context the base `QuestionElement.render()` passes (`el`, `element`, `action_url`, `mode`, `feedback_partial`, `feedback_html`, `feedback_for_pk`, `submitted_values`, `quiz_submitted`, `locked`); `mark_result.reveal` (Task 1 shape); `answered` flag (Task 2 `feedback_context` / Task 9 results include).
- Produces: the two templates. The reveal partial **defaults to the neutral guide when `answered` is falsy/undefined** (fail-safe).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_questions_2diii_model.py
from django.template.loader import render_to_string


def test_reveal_answered_shows_check_marks():
    q = ExtendedResponseQuestionElementFactory(required_keywords="alpha")
    html = render_to_string(
        "courses/elements/_reveal_extendedresponse.html",
        {"mark_result": q.mark("alpha"), "answered": True},
    )
    assert "alpha" in html
    assert "✓" in html


def test_reveal_unanswered_is_neutral_guide_no_check():
    q = ExtendedResponseQuestionElementFactory(
        required_keywords="", forbidden_keywords="banned"
    )
    # mark("") on only-forbidden -> all absent; unanswered must NOT show a green check.
    html = render_to_string(
        "courses/elements/_reveal_extendedresponse.html",
        {"mark_result": q.mark(""), "answered": False},
    )
    assert "banned" in html
    assert "✓" not in html


def test_student_template_has_textarea_maxlength():
    q = ExtendedResponseQuestionElementFactory()
    html = render_to_string(
        "courses/elements/extendedresponsequestionelement.html",
        {"el": q, "element": q, "action_url": "/x/", "mode": "lesson"},
    )
    assert 'name="answer"' in html
    assert 'maxlength="10000"' in html
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_questions_2diii_model.py -k reveal -v`
Expected: FAIL with `TemplateDoesNotExist`.

- [ ] **Step 3a: Create `extendedresponsequestionelement.html`**

```html
{% load i18n %}
<div class="el el--question" data-question>
  <div class="question__stem">{{ el.stem|safe }}</div>
  {% if element %}
  <form class="question__form" method="post" action="{{ action_url }}">
    {% csrf_token %}
    <textarea name="answer" class="question__text-input" rows="6" maxlength="10000"
              autocomplete="off"
              {% if quiz_submitted or locked %}disabled{% endif %}>{% if element.pk == feedback_for_pk %}{{ submitted_values }}{% endif %}</textarea>
    <button type="submit" class="btn btn--small"
            {% if quiz_submitted or locked %}disabled{% endif %}>{% trans "Submit" %}</button>
    <div class="question__feedback" data-question-feedback>
      {% if mode == "quiz" %}{{ feedback_html|safe }}{% elif element.pk == feedback_for_pk %}{% include feedback_partial %}{% endif %}
    </div>
  </form>
  {% endif %}
</div>
```

Note: the button label is `{% trans "Submit" %}` (deliberately **not** the other types' `{% trans "Check" %}`) — an `[R]` extended-response is *submitted for review*, not auto-checked. Task 10 translates "Submit" → "Wyślij".

- [ ] **Step 3b: Create `_reveal_extendedresponse.html`**

```html
{% load i18n %}
{% if answered %}
  <ul class="question__reveal-keywords">
    {% for item in mark_result.reveal %}
      {% if item.kind == "required" %}
        <li class="kw kw--required {% if item.found %}is-found{% else %}is-missing{% endif %}">
          {% if item.found %}✓{% else %}✗{% endif %}
          {% trans "Required" %}: <strong>{{ item.keyword }}</strong>
        </li>
      {% else %}
        <li class="kw kw--forbidden {% if item.found %}is-present{% else %}is-absent{% endif %}">
          {% if item.found %}✗{% else %}✓{% endif %}
          {% trans "Avoid" %}: <strong>{{ item.keyword }}</strong>
        </li>
      {% endif %}
    {% endfor %}
  </ul>
{% else %}
  {% comment %}Unanswered (results page mark("")): neutral guide, no per-keyword ✓/✗
  so an only-forbidden never-answered row doesn't show a false "you avoided them ✓".{% endcomment %}
  <div class="question__reveal-guide">
    {% for item in mark_result.reveal %}{% if item.kind == "required" %}
      <span class="kw kw--expected">{{ item.keyword }}</span>
    {% endif %}{% endfor %}
    {% for item in mark_result.reveal %}{% if item.kind == "forbidden" %}
      <span class="kw kw--avoid">{{ item.keyword }}</span>
    {% endif %}{% endfor %}
  </div>
{% endif %}
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_questions_2diii_model.py -k "reveal or textarea" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint and commit**

```bash
git add templates/courses/elements/extendedresponsequestionelement.html templates/courses/elements/_reveal_extendedresponse.html tests/test_questions_2diii_model.py
git commit -m "feat(2d-iii): student template + answered-aware reveal partial"
```

---

## Task 5: Editor partial + label maps

**Files:**
- Create: `templates/courses/manage/editor/_edit_extendedresponsequestion.html`
- Modify: `courses/views_manage.py` (`_EDITOR_TYPE_LABELS`)
- Modify: `courses/templatetags/courses_manage_extras.py` (`_ELEMENT_LABELS`)
- Test: `tests/test_questions_2diii_authoring.py`

**Interfaces:**
- Consumes: `_marking_fields.html`, `_rte_toolbar.html` (existing includes); the form from Task 3.
- Produces: the editor partial; `_EDITOR_TYPE_LABELS["extendedresponsequestion"] = _("Extended response")`; `_ELEMENT_LABELS["extendedresponsequestionelement"] = _("Essay")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_questions_2diii_authoring.py
import pytest
from django.template.loader import render_to_string

from courses.templatetags.courses_manage_extras import _ELEMENT_LABELS
from courses.templatetags.courses_manage_extras import element_type_label
from courses.views_manage import _EDITOR_TYPE_LABELS
from courses.element_forms import ExtendedResponseQuestionElementForm
from django.contrib.contenttypes.models import ContentType
from courses.models import ExtendedResponseQuestionElement

pytestmark = pytest.mark.django_db


def test_editor_type_label_present():
    assert str(_EDITOR_TYPE_LABELS["extendedresponsequestion"])


def test_element_outline_label_is_short():
    # The outline tile uses element_type_label(content_type, obj) -> _ELEMENT_LABELS
    # keyed on content_type.model. There is NO string-keyed `element_label` callable.
    assert str(_ELEMENT_LABELS["extendedresponsequestionelement"]) == "Essay"
    ct = ContentType.objects.get_for_model(ExtendedResponseQuestionElement)
    assert str(element_type_label(ct)) == "Essay"


def test_edit_partial_renders_keyword_textareas():
    form = ExtendedResponseQuestionElementForm()
    html = render_to_string(
        "courses/manage/editor/_edit_extendedresponsequestion.html", {"form": form}
    )
    assert 'name="required_keywords"' in html
    assert 'name="forbidden_keywords"' in html
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_questions_2diii_authoring.py -v`
Expected: FAIL (`KeyError`/`TemplateDoesNotExist`).

- [ ] **Step 3a: Create `_edit_extendedresponsequestion.html`**

```html
{% load i18n %}
<div class="el-editor el-editor--question">
  <label class="el-editor__label">{% trans "Question" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="stem" class="rte-source" data-rte-source rows="3">{{ form.stem.value|default:"" }}</textarea>
  </div>
  {% for e in form.stem.errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Required keywords (one per line)" %}</label>
  <textarea name="required_keywords" rows="3">{{ form.required_keywords.value|default:"" }}</textarea>
  {% for e in form.required_keywords.errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Forbidden keywords (one per line)" %}</label>
  <textarea name="forbidden_keywords" rows="3">{{ form.forbidden_keywords.value|default:"" }}</textarea>
  {% for e in form.forbidden_keywords.errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  {% include "courses/manage/editor/_marking_fields.html" %}
  {% for e in form.non_field_errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Explanation (optional)" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="explanation" class="rte-source" data-rte-source rows="2">{{ form.explanation.value|default:"" }}</textarea>
  </div>
</div>
```

The `non_field_errors` loop surfaces the cross-field "needs a keyword" message.

- [ ] **Step 3b: Add the label-map entries**

In `courses/views_manage.py`, inside `_EDITOR_TYPE_LABELS`:

```python
    "extendedresponsequestion": _("Extended response"),
```

In `courses/templatetags/courses_manage_extras.py`, inside `_ELEMENT_LABELS`:

```python
    "extendedresponsequestionelement": _("Essay"),
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_questions_2diii_authoring.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix courses/views_manage.py courses/templatetags/courses_manage_extras.py tests/test_questions_2diii_authoring.py
ruff format courses/views_manage.py courses/templatetags/courses_manage_extras.py tests/test_questions_2diii_authoring.py
git add templates/courses/manage/editor/_edit_extendedresponsequestion.html courses/views_manage.py courses/templatetags/courses_manage_extras.py tests/test_questions_2diii_authoring.py
git commit -m "feat(2d-iii): editor partial + editor/outline label maps"
```

---

## Task 6: Authoring wiring — add-menu + allowlists (builder rides the existing else)

**Files:**
- Modify: `templates/courses/manage/editor/_add_menu.html`
- Modify: `courses/views_manage.py` (both `type_key` allowlists)
- Test: `tests/test_questions_2diii_authoring.py` (extend)

**Interfaces:**
- Consumes: `builder.save_element`'s existing `else` branch (line ~299) — `FORM_FOR_TYPE[type_key]` plain `form.save()`, no sub-rows. Extended-response matches no `elif`, so it rides the `else` like `shorttextquestion` — **no new builder branch**.
- Produces: an add-menu button (`data-add-type="extendedresponsequestion"`); the key in both `element_add` and `element_save` allowlists.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_questions_2diii_authoring.py
from django.urls import reverse

from courses.models import ExtendedResponseQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa


def test_element_add_opens_form_not_400(client):
    # The type_key must pass the element_add allowlist (else 400 "bad type").
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "extendedresponsequestion", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert b'name="required_keywords"' in resp.content


def test_element_save_creates_element(client):
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "extendedresponsequestion",
            "unit": unit.pk,
            "element": "new",
            "unit_token": unit.updated.isoformat(),
            "stem": "Explain photosynthesis.",
            "explanation": "",
            "required_keywords": "chlorophyll\nlight",
            "forbidden_keywords": "",
            "marking_mode": "A",
            "max_attempts": "1",
            "max_marks": "1",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code in (200, 204)
    obj = ExtendedResponseQuestionElement.objects.get(stem="Explain photosynthesis.")
    assert obj.required_keywords == "chlorophyll\nlight"
```

(This mirrors `tests/test_questions_2d_authoring_views.py` exactly: a plain `client` + `make_pa(client, "pa")` platform-admin login, `CourseFactory` + `ContentNodeFactory(..., unit_type="quiz")`, the `reverse("courses:manage_element_add"/"manage_element_save")` URL names, the `unit_token=unit.updated.isoformat()` field, and `HTTP_X_REQUESTED_WITH="fetch"`. There are **no** `manage_client`/`unit_in_managed_course` fixtures — those were invented.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_questions_2diii_authoring.py -k add_and_save -v`
Expected: FAIL — the save returns 400 "bad type" (allowlist) or no element is created.

- [ ] **Step 3a: Add the add-menu button**

In `templates/courses/manage/editor/_add_menu.html`, after the `dragtoimagequestion` button:

```html
    <button type="button" class="typecard" data-add-type="extendedresponsequestion"><span class="ic">✍</span>{% trans "Extended response" %}</button>
```

- [ ] **Step 3b: Add the key to both allowlists in `courses/views_manage.py`**

In `element_add`'s tuple and `element_save`'s tuple, add:

```python
        "extendedresponsequestion",
```

- [ ] **Step 3c: Confirm `builder.save_element` needs no change**

Read `courses/builder.py` `save_element`: the `elif type_key ==` chain covers `choicequestion`/`fillblankquestion`/`dragfillblankquestion`/`matchpairquestion`/`dragtoimagequestion`; the `else` (line ~299) builds `FORM_FOR_TYPE[type_key]` and saves with no sub-rows. `"extendedresponsequestion"` matches no `elif`, so it correctly rides the `else` (no `course=` extra, no formset) — **make no edit here**, just verify by the passing test.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_questions_2diii_authoring.py -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix courses/views_manage.py tests/test_questions_2diii_authoring.py
ruff format courses/views_manage.py tests/test_questions_2diii_authoring.py
git add templates/courses/manage/editor/_add_menu.html courses/views_manage.py tests/test_questions_2diii_authoring.py
git commit -m "feat(2d-iii): wire extended-response into add-menu + element allowlists"
```

---

## Task 7: Lesson consumption — CT-gate + formative keyword self-check

**Files:**
- Modify: `courses/views.py` (`question_models` list in `build_lesson_context`; import the model)
- Test: `tests/test_questions_2diii_quiz.py` (lesson section)

**Interfaces:**
- Consumes: `build_lesson_context`'s `question_models` list (line ~90) and `_question_has_math` closure (no change — the generic `has_math_delimiters(q.stem)` at the top covers stem-only types; **no isinstance branch**). No prefetch (single-row).
- Produces: a lesson containing only an extended-response now reports `has_questions=True` and `check_answer` marks + reveals it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_questions_2diii_quiz.py
import pytest

from courses.models import ExtendedResponseQuestionElement
from courses.views import build_lesson_context
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import UserFactory
from tests.factories import add_element

pytestmark = pytest.mark.django_db


def test_lesson_with_only_extended_response_has_questions():
    # add_element (tests/factories.py) attaches a concrete element to a unit via the
    # Element GFK join-row — the same helper tests/test_questions_2d_results.py uses.
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Explain.", required_keywords="alpha", marking_mode="A"
    )
    add_element(unit, q)
    ctx = build_lesson_context(unit, UserFactory())
    assert ctx["has_questions"] is True
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_questions_2diii_quiz.py -k has_questions -v`
Expected: FAIL — `has_questions` is `False` (the model is not in `question_models`).

- [ ] **Step 3: Add the model to `question_models`**

In `courses/views.py`, import `ExtendedResponseQuestionElement` (alongside the other question-element imports) and add it to the `question_models` list in `build_lesson_context`:

```python
        ExtendedResponseQuestionElement,
```

Do **not** add a `_question_has_math` branch (the leading `has_math_delimiters(q.stem)` already covers it) and do **not** add any prefetch (no sub-rows).

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_questions_2diii_quiz.py -k has_questions -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix courses/views.py tests/test_questions_2diii_quiz.py
ruff format courses/views.py tests/test_questions_2diii_quiz.py
git add courses/views.py tests/test_questions_2diii_quiz.py
git commit -m "feat(2d-iii): register extended-response in the lesson question CT-gate"
```

---

## Task 8: Quiz integration — `[A]` scoring/resume, `[R]`/`[N]` cards (verify), `answered` on results row

**Files:**
- Modify: `courses/views.py` (`_results_row`: add `row["answered"]`)
- Test: `tests/test_questions_2diii_quiz.py` (extend)

**Interfaces:**
- Consumes: the 2c quiz path (`quiz_answer`/`quiz_finish`/`_score_submission`), `quiz.rehydrate`/`answer_from_json`/`answer_to_json` (default passthrough for a `str`), `quiz_feedback_context` (neutral cards already exist), `_results_row` (line ~601).
- Produces: `_results_row` row dict gains `"answered": response is not None and response.latest_answer is not None`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_questions_2diii_quiz.py
# (ExtendedResponseQuestionElement, add_element are already imported at the top from Task 7)
from courses import quiz as quizmod
from courses.models import QuestionResponse
from courses.views import _results_row
from tests.factories import EnrollmentFactory
from tests.factories import make_login
from tests.factories import make_quiz_unit


def test_resume_routing_stays_on_default_branch():
    q = ExtendedResponseQuestionElement.objects.create(
        stem="x", required_keywords="alpha", marking_mode="A"
    )
    assert quizmod.answer_to_json("alpha text") == "alpha text"
    assert quizmod.answer_from_json(q, "alpha text") == "alpha text"
    assert quizmod.rehydrate(q, "alpha text") == (set(), "alpha text")


def test_quiz_auto_scores_partial(client):
    # End-to-end [A] scoring through the real quiz_answer view (I4).
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Explain.", required_keywords="alpha\nbeta", marking_mode="A", max_marks="2"
    )
    el = add_element(unit, q)
    client.get(f"{base}/")  # materialize the QuizSubmission (student flow)
    client.post(
        f"{base}/q/{el.pk}/answer/", {"answer": "alpha only"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    r = QuestionResponse.objects.get(element_id=el.pk)
    assert float(r.fraction) == 0.5  # 1 of 2 required keywords found


def test_review_mode_records_unscored_and_shows_card(client):
    # 2c's _quiz_question_feedback.html renders the neutral card type-agnostically.
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    q = ExtendedResponseQuestionElement.objects.create(stem="Essay?", marking_mode="R")
    el = add_element(unit, q)
    client.get(f"{base}/")
    resp = client.post(
        f"{base}/q/{el.pk}/answer/", {"answer": "my essay"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert b"Submitted for review" in resp.content
    r = QuestionResponse.objects.get(element_id=el.pk)
    assert r.fraction is None and r.reviewed_at is None  # recorded, unscored, pending


def test_results_row_answered_false_when_no_response():
    q = ExtendedResponseQuestionElement.objects.create(
        stem="x", required_keywords="alpha", marking_mode="A"
    )
    assert _results_row(q, None)["answered"] is False
```

(`element_id` is the `Element` join-row pk that `add_element` returns; mirror `tests/test_questions_2d_results.py` if the exact `QuestionResponse` lookup field differs. The `answered=True` case is exercised on the results page in Task 9.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_questions_2diii_quiz.py -k "answered or auto_scores or review_mode" -v`
Expected: `test_results_row_answered_false_when_no_response` FAILS (`KeyError: 'answered'`); the quiz integration tests pass once Tasks 1-7 are in (the `answered` row key is the only new code here).

- [ ] **Step 3: Add `answered` to `_results_row`**

In `courses/views.py` `_results_row`, add to the `row` dict initialization (alongside `"reveal_result"`, `"choices"`):

```python
        "answered": response is not None and response.latest_answer is not None,
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_questions_2diii_quiz.py -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix courses/views.py tests/test_questions_2diii_quiz.py
ruff format courses/views.py tests/test_questions_2diii_quiz.py
git add courses/views.py tests/test_questions_2diii_quiz.py
git commit -m "feat(2d-iii): quiz [A] scoring/resume + answered flag on results rows"
```

---

## Task 9: Results page — `answered` include, "up to M marks", pending-review footer

**Files:**
- Modify: `courses/views.py` (`quiz_results`: accumulate `pending_count`/`pending_marks`, add to context)
- Modify: `templates/courses/quiz_results.html` (reveal include `answered=`; `[R]` badge "up to M marks"; footer)
- Test: `tests/test_questions_2diii_results.py`

**Interfaces:**
- Consumes: `quiz_results` loop (line ~583) + `render` context; `_results_row` `row["answered"]`/`row["possible"]` (Task 8); the reveal include at line 27; the `{% if submission.max_score %}` block (lines 8-12); `QuestionElement.MarkingMode.REVIEW`.
- Produces: `quiz_results` context keys `pending_count`/`pending_marks`; the template footer + the enhanced `[R]` badge + the `answered`-aware reveal include.
- Note: `answered` is consumed **only on `[A]` rows** — the reveal `{% include %}` is gated by `{% if row.reveal_template %}`, and `_results_row` sets `reveal_template` only for `[A]` rows (`[R]`/`[N]` leave it `None`). So `[R]`/`[N]` rows render no reveal at all (no leak); the `answered` flag only changes how the `[A]` reveal renders (per-keyword ✓/✗ vs neutral guide).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_questions_2diii_results.py
import pytest

from courses.models import ExtendedResponseQuestionElement
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def _submit_quiz(client, *questions):
    """Log in a student, build a quiz unit holding `questions`, submit it, and return
    the decoded results-page body. Mirrors tests/test_questions_2d_results.py."""
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    for q in questions:
        add_element(unit, q)
    client.get(f"{base}/")  # materialize the QuizSubmission
    client.post(f"{base}/finish/")
    return client.get(f"{base}/results/").content.decode()


def test_all_review_quiz_shows_pending_footer(client):
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Essay?", marking_mode="R", max_marks="5"
    )
    body = _submit_quiz(client, q)
    assert "Score: —" in body  # [A]-only total empty (max_score 0.00 -> falsy)...
    assert "awaiting review" in body.lower()  # ...but the footer still renders.


def test_review_row_shows_up_to_marks(client):
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Essay?", marking_mode="R", max_marks="3"
    )
    body = _submit_quiz(client, q)
    assert "Awaiting review" in body
    assert "up to" in body.lower() and "3" in body


def test_not_marked_excluded_from_pending(client):
    n = ExtendedResponseQuestionElement.objects.create(stem="N?", marking_mode="N")
    r = ExtendedResponseQuestionElement.objects.create(
        stem="R?", marking_mode="R", max_marks="2"
    )
    body = _submit_quiz(client, n, r)
    # footer counts only the [R]: singular "1 question awaiting review".
    assert "1 question awaiting review" in body.lower()


def test_unanswered_only_forbidden_no_false_check(client):
    # Single-question quiz: an [A] only-forbidden response never answered. The results
    # reveal must be the neutral guide (lists "banned", NO green ✓ anywhere on the page).
    q = ExtendedResponseQuestionElement.objects.create(
        stem="OnlyForbidden",
        required_keywords="",
        forbidden_keywords="banned",
        marking_mode="A",
    )
    body = _submit_quiz(client, q)
    assert "banned" in body
    assert "✓" not in body
```

(Build the four scenarios with the 2c quiz-submission fixtures: create a `QuizSubmission` in `SUBMITTED` status with `QuestionResponse`s, then GET the results URL. Mirror `tests/test_questions_2d_results.py` for the exact submission/response construction and the results URL name. For `test_unanswered_only_forbidden_no_false_check`, scope the `✓` assertion to the specific row's reveal fragment rather than the whole page if other rows legitimately contain ✓.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_questions_2diii_results.py -v`
Expected: FAIL — no footer, no "up to", `answered` not passed.

- [ ] **Step 3a: Accumulate the tally in `quiz_results`**

In `courses/views.py` `quiz_results`, initialize counters before the element loop and increment **after** the `isinstance(q, QuestionElement)` guard:

```python
    rows = []
    pending_count = 0
    pending_marks = 0
    for el in node.elements.order_by("order", "pk").prefetch_related("content_object"):
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        if q.marking_mode == QuestionElement.MarkingMode.REVIEW:
            pending_count += 1
            pending_marks += q.max_marks
        r = responses.get(el.pk)
        rows.append(_results_row(q, r))
```

Add the two keys to the existing `render(...)` context dict:

```python
            "pending_count": pending_count,
            "pending_marks": pending_marks,
```

- [ ] **Step 3b: Update `templates/courses/quiz_results.html`**

(1) Enhance the `[R]` badge (line ~22) to include the marks:

```html
      {% elif row.outcome == "review" %}<span class="badge">{% trans "Awaiting review" %} ({% blocktrans with m=row.possible|marks %}up to {{ m }} marks{% endblocktrans %})</span>{% endif %}
```

(2) Pass `answered` into the reveal include (line ~27):

```html
        {% include row.reveal_template with el=row.question mark_result=row.reveal_result choices=row.choices answered=row.answered %}
```

(3) Add the footer **outside** the `{% if submission.max_score %}` block — place it immediately after `{% endif %}` on line ~12, before the `<ol>`:

```html
  {% if pending_count %}
    <p class="quiz-results__pending">{% blocktrans count n=pending_count with m=pending_marks|marks %}{{ n }} question awaiting review (up to {{ m }} more marks){% plural %}{{ n }} questions awaiting review (up to {{ m }} more marks){% endblocktrans %}</p>
  {% endif %}
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_questions_2diii_results.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix courses/views.py tests/test_questions_2diii_results.py
ruff format courses/views.py tests/test_questions_2diii_results.py
git add courses/views.py templates/courses/quiz_results.html tests/test_questions_2diii_results.py
git commit -m "feat(2d-iii): pending-review footer + up-to-marks + answered-aware reveal"
```

---

## Task 10: i18n (EN/PL)

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: existing `tests/` i18n catalog test (`test_po_catalog_clean` or equivalent)

**Interfaces:**
- Consumes: every `{% trans %}`/`_()` string added in Tasks 2-9.
- Produces: real Polish translations; a clean catalog (no `#~`).

- [ ] **Step 1: Extract messages**

```bash
python manage.py makemessages -l pl
```

- [ ] **Step 2: Translate the new strings**

Edit `locale/pl/LC_MESSAGES/django.po`, filling Polish for each new msgid. Suggested translations:

```
"Extended response"  -> "Rozszerzona odpowiedź"
"Essay"              -> "Esej"
"Required keywords (one per line)"  -> "Wymagane słowa kluczowe (po jednym w wierszu)"
"Forbidden keywords (one per line)" -> "Zabronione słowa kluczowe (po jednym w wierszu)"
"Auto-marked extended response needs at least one required or forbidden keyword."
    -> "Automatycznie oceniana rozszerzona odpowiedź wymaga co najmniej jednego wymaganego lub zabronionego słowa kluczowego."
"Required"  -> "Wymagane"
"Avoid"     -> "Unikaj"
"Submit"    -> "Wyślij"
```

For the plural footer `blocktrans` add both Polish plural forms, e.g.:

```
msgid "%(n)s question awaiting review (up to %(m)s more marks)"
msgid_plural "%(n)s questions awaiting review (up to %(m)s more marks)"
msgstr[0] "%(n)s pytanie oczekuje na ocenę (do %(m)s dodatkowych punktów)"
msgstr[1] "%(n)s pytania oczekują na ocenę (do %(m)s dodatkowych punktów)"
msgstr[2] "%(n)s pytań oczekuje na ocenę (do %(m)s dodatkowych punktów)"
```

(Likewise translate the "up to {{ m }} marks" badge `blocktrans`.) **Remove any `#~` obsolete entries** `makemessages` leaves behind — the project forbids them.

- [ ] **Step 3: Compile**

```bash
python manage.py compilemessages
```

- [ ] **Step 4: Run the catalog + a render test**

```bash
pytest -k "po_catalog or i18n" -v
```
Expected: PASS (no `#~`, catalog parses, `.mo` compiles).

- [ ] **Step 5: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(2d-iii): Polish for extended-response + pending-review strings"
```

---

## Task 11: e2e (Playwright)

**Files:**
- Create: `tests/test_e2e_questions_2diii.py`
- Test: itself (run with `-m e2e`)

**Interfaces:**
- Consumes: the Playwright + `live_server` harness used by `tests/test_e2e_questions_2d.py` (the authoritative e2e precedent — copy its fixtures: manager login, course/unit setup, the element-authoring flow, the student-consume flow).

- [ ] **Step 1: Write the e2e tests**

```python
# tests/test_e2e_questions_2diii.py
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.django_db]


def test_author_then_answer_extended_response_in_lesson(...):
    # 1. As a course manager, add an extended-response to a LESSON unit:
    #    stem + required_keywords="alpha\nbeta", marking_mode left as [A].
    # 2. As an enrolled student, open the lesson, type "alpha and beta" in the
    #    <textarea name="answer">, submit.
    # 3. Assert the reveal shows the keyword breakdown (✓ for alpha/beta).
    ...


def test_quiz_review_mode_shows_awaiting_review_and_footer(...):
    # 1. Author an extended-response in a QUIZ unit with marking_mode=[R].
    # 2. Student submits an answer -> per-question card shows "Submitted for review".
    # 3. Finish the quiz -> results page shows "Awaiting review" + the pending footer,
    #    and NO keyword leak (the [R] row reveals nothing).
    ...


def test_quiz_auto_mode_no_leak_then_reveal(...):
    # [A] with max_attempts=1: wrong submit -> reveal after exhausting; assert the
    # required keyword does NOT appear pre-reveal; appears in the reveal.
    ...
```

Fill the `...` by mirroring `tests/test_e2e_questions_2d.py` exactly (its manager/student fixtures, the manage element-save POST or UI click flow, the lesson/quiz URLs, and the assertion helpers). Drive the **real** UI gestures (type into the textarea, click submit) — do not bypass via `page.evaluate`.

- [ ] **Step 2: Run the e2e suite**

Run: `pytest tests/test_e2e_questions_2diii.py -m e2e -v`
Expected: PASS (3 tests). Also re-run the existing 2d e2e to confirm no regression: `pytest tests/test_e2e_questions_2d.py -m e2e -v`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_questions_2diii.py
git commit -m "test(2d-iii): e2e for extended-response lesson/quiz [A]/[R] + no-leak"
```

---

## Final verification (run after Task 11)

```bash
ruff check .
ruff format --check .
python manage.py makemigrations --check
python manage.py check
pytest -m "not e2e"          # full non-e2e suite green
pytest -m e2e                 # full e2e suite green (or the 2d/2diii subset)
```

All must be clean before opening the PR.

---

## Self-Review (author checklist — completed)

**1. Spec coverage:**
- §2.1 model / §2.2 seam → Task 2. §2.4/§5.5 migration → Task 2 (generated). 
- §1.3 formula + §1.4 matching → Task 1. §3.1 helper / §3.2 MarkResult-by-keyword → Tasks 1-2.
- §3.3 student template + reveal partial (answered flag, .strip-for-display) → Task 4.
- §3.4 per-question `[R]`/`[N]` cards → **already exist (2c)**; verified in Task 8. Results badges + "up to M" + footer + `answered` include → Task 9.
- §4.1 form (effective-mode validation, Meta widgets) → Task 3. §4.3 touchpoints: add-menu/allowlists → Task 6; label maps → Task 5; CT-gate → Task 7; builder `else` (no branch) → Task 6; resume default → Task 8; results reveal → Task 9; no prefetch / no `_question_has_math` branch → Tasks 7-8 (explicit no-ops).
- §5.1 no-leak / §5.2 edge cases → Tasks 1, 9, 11. §5.3 i18n → Task 10. §5.4 tests → distributed per task. 

**2. Placeholder scan:** the only `...` blocks are in the e2e task (Task 11), which explicitly delegates to `tests/test_e2e_questions_2d.py` as the copy-source — acceptable for an e2e harness that must reuse session fixtures. All Python/template/code steps carry complete code.

**3. Type consistency:** `mark_keywords -> (fraction, reveal, correct)` (Task 1) is consumed by `mark` via keyword construction `MarkResult(correct=correct, fraction=frac, reveal=reveal)` (Task 2) — the splat-swap is explicitly forbidden. `reveal` dict keys `{keyword, kind, found}` (Task 1) match the reveal template (Task 4) and the `answered` flag flows model→Task 4 / `_results_row`→Task 8 / include→Task 9 consistently. `pending_count`/`pending_marks` defined in Task 9 view and consumed in the same task's template.
