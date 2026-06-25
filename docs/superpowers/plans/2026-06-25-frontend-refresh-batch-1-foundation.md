# Frontend Refresh — Batch 1: Design Foundation + Consistency Pass — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the static student-consumption pages (`home`, `my_courses`, `quiz_results`, `course_results`) and the in-page question/element rendering up to libli's established token-driven design language, and establish the shared CSS primitives later batches consume — with **no behaviour change**.

**Architecture:** Pure CSS + template work. Extend the existing token vocabulary (`core/static/core/css/tokens.css`, `app.css`, `courses/static/courses/css/courses.css`) — no new frameworks, no JS behaviour changes. Introduce two shared component groups (a **results/stat** vocabulary and a **`code-field`** primitive) and align legacy fallback variable names in `courses.css` to the real design tokens.

**Tech Stack:** Django templates, hand-authored token-driven CSS (no Bootstrap/React), `pytest` + Django test client, Playwright for throwaway screenshot self-review.

**Spec:** `docs/superpowers/specs/2026-06-25-frontend-design-refresh-and-navigation-design.md` (§2 batch 1, §5 code-field, §6 consistency pass, §8 testing).

**Accepted visual references:** `docs/mockups/` (the unit-nav / review mockups are for batches 2–3; the consumption pages here have no bespoke mockup and follow the established catalog/outline/manage vocabulary).

## Global Constraints

Copied from the spec; every task implicitly includes these.

- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH — use `uv run ruff`, `uv run pytest`, `uv run python manage.py`.
- **No behaviour change in batch 1** — CSS and template markup only. Do not change view logic, context shape, URLs, scoring, or progress hooks.
- **Token-driven CSS only** — no new CSS frameworks; reuse `tokens.css` variables and the established `.btn`/`.badge`/`.card`/`.card-list`/`.catalog__*`/`.outline-*`/`.manage`/`.course-list` vocabulary. No raw hex literals for themed surfaces/text (the one intentional exception — the sandbox iframe's `background:#fff` in `.html-el__frame` — stays, with its existing comment).
- **Dark-mode parity** — every colour comes from a token that has a `[data-theme="dark"]` value; verify light + dark.
- **i18n** — every new visible string is wrapped in `{% trans %}`/`{% blocktrans %}` and gets a Polish translation in the `pl` `.po`; recompile `.mo` (`uv run python manage.py compilemessages`). Watch the makemessages fuzzy-flag gotcha (clear stale `#, fuzzy` and verify new msgids). Batch 1 should introduce **few or no** new strings (it restyles existing markup); flag any it does.
- **Django comments** — multi-line comments use `{% comment %}…{% endcomment %}`, never multi-line `{# #}` (which renders as visible text).
- **Lint/format** — `uv run ruff check` and `uv run ruff format --check` must pass; the full suite (`uv run pytest`) must be green before each commit.
- **Visual verification** — for each restyle task, take throwaway Playwright screenshots in **light and dark**, self-critique against the established vocabulary, then delete the harness (per `verify-ui-with-screenshots`).

---

## File Structure

**CSS (modify):**
- `courses/static/courses/css/courses.css` — token-name alignment + element/feedback polish (Task 1); results/stat component block (Task 2); `code-field` primitive (Task 7).
- `core/static/core/css/app.css` — dashboard card-grid styles for `my_courses` (Task 5) and `home` (Task 6).

**Templates (modify):**
- `templates/courses/quiz_results.html` (Task 3)
- `templates/courses/course_results.html` (Task 4)
- `templates/courses/my_courses.html` (Task 5)
- `templates/core/home.html` (Task 6)

**Python (create, Task 7):**
- `courses/widgets.py` — a reusable `CodeTextarea` widget that renders a textarea inside the `code-field` wrapper markup.

**Tests (create):**
- `tests/test_consumption_css.py` — CSS-content guard tests (Tasks 1, 2, 7).
- `tests/test_consumption_pages.py` — render tests for the four restyled pages (Tasks 3–6).
- `tests/test_code_field_widget.py` — widget render test (Task 7).

Each restyle task asserts its new structural classes appear in the rendered HTML (a real red→green), then is finished with a light+dark screenshot self-review.

---

## Task 1: Consumption CSS — token alignment + feedback/widget/media polish

`courses.css` predates the token consolidation: it uses legacy fallback names (`--color-success`, `--color-danger`, `--color-warning`, `--text-muted`, `--surface`, `--border`, `--color-border`, `--muted`, `--primary-200`) and hand-rolled `rgba()` tints that don't adapt to dark mode. Replace them with real tokens (`--success`, `--danger`, `--warning`, `--text-tertiary`, `--surface-raised`, `--border-default`, `--*-subtle`), so feedback panels, question widgets, drag-and-drop chips, and media framing are theme-correct.

**Files:**
- Modify: `courses/static/courses/css/courses.css`
- Test: `tests/test_consumption_css.py`

**Interfaces:**
- Consumes: existing tokens in `tokens.css` (`--success`, `--success-subtle`, `--danger`, `--danger-subtle`, `--warning`, `--warning-subtle`, `--primary`, `--primary-subtle`, `--surface-raised`, `--surface-sunken`, `--text-tertiary`, `--border-default`, `--border-strong`, `--radius-sm`, `--space-*`).
- Produces: a token-clean `courses.css` that Tasks 2–3 and batches 2–4 build on.

- [ ] **Step 1: Write the failing test**

Create `tests/test_consumption_css.py`:

```python
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "courses/static/courses/css/courses.css"


def test_courses_css_has_no_legacy_fallback_tokens():
    """courses.css must use the real design tokens, not the pre-consolidation
    legacy fallback names (which have no dark-mode value)."""
    css = CSS.read_text(encoding="utf-8")
    legacy = [
        "--color-success",
        "--color-danger",
        "--color-warning",
        "--color-border",
        "--text-muted",
        "--primary-200",
        "var(--surface,",
        "var(--border,",
        "var(--muted,",
    ]
    present = [name for name in legacy if name in css]
    assert present == [], f"legacy token names still in courses.css: {present}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_consumption_css.py::test_courses_css_has_no_legacy_fallback_tokens -v`
Expected: FAIL — the legacy names are still present.

- [ ] **Step 3: Replace the legacy names with tokens**

In `courses/static/courses/css/courses.css`, make these substitutions (whole file):

- `var(--text-muted, #555)` → `var(--text-tertiary)`
- `var(--border, #d0d0d0)` → `var(--border-default)`
- `var(--surface, #fff)` (the `.html-el__label` background) → `var(--surface-raised)`
- `var(--muted, #666)` → `var(--text-tertiary)`
- `var(--color-border, #ccc)` and `var(--color-border, #ccc)` everywhere → `var(--border-default)`
- `var(--color-success, #1a7f4b)` → `var(--success)`
- `var(--color-danger, #b3261e)` and `var(--color-danger, #b00020)` → `var(--danger)`
- `var(--color-warning, #b26a00)` → `var(--warning)`
- `var(--primary, #0a7a5a)` → `var(--primary)`
- `var(--primary-200, rgba(10, 122, 90, 0.3))` → `var(--primary-subtle)`
- `var(--text-primary, #1a1a1a)` → `var(--text-primary)`
- `var(--border-strong, #bbb)` → `var(--border-strong)`
- `var(--radius-sm, 4px)` → `var(--radius-sm)`; `var(--radius-full, 999px)` → `var(--radius-full)`
- `var(--space-1, 0.25rem)` → `var(--space-1)`; likewise `--space-2`/`--space-3` fallbacks → the bare token.

Then replace the hand-rolled feedback-panel tints with `*-subtle` tokens so they adapt to dark mode. Replace the existing `.question__feedback-panel*` block (lines ~51–70) with:

```css
.question__feedback-panel {
  margin: var(--space-2) 0;
  padding: var(--space-2) var(--space-3);
  border-left: 4px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
}
.question__feedback-panel--correct {
  border-left-color: var(--success);
  background: var(--success-subtle);
}
.question__feedback-panel--incorrect,
.question__feedback-panel--not_answered {
  border-left-color: var(--danger);
  background: var(--danger-subtle);
}
.question__feedback-panel--partial {
  border-left-color: var(--warning);
  background: var(--warning-subtle);
}
.question__feedback-panel--neutral,
.question__feedback-panel--validation {
  border-left-color: var(--border-strong);
  background: var(--surface-sunken);
}
.question__verdict.is-correct { color: var(--success); }
.question__verdict.is-incorrect { color: var(--danger); }
```

Add a consistent focus ring for the question inputs and dnd slots (replace the bare `.dnd__slot:focus` rule and add an input rule), so keyboard focus is visible and on-token:

```css
.question__text-input:focus,
.question__blank-input:focus,
.dnd__select:focus,
.dnd__slot:focus,
.dnd__chip:focus {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}
```

Leave `.html-el__frame { background: #fff; }` and its comment as-is (intentional sandbox surface).

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_consumption_css.py -v`
Expected: PASS.

- [ ] **Step 5: Regression — the unit/quiz/results pages still render**

Run: `uv run pytest tests/test_courses_views.py tests/test_quiz_views.py tests/test_questions_2diii_results.py -q`
Expected: PASS (no selectors broken).

- [ ] **Step 6: Screenshot self-review (light + dark)**

Write a throwaway Playwright script that logs in, opens a quiz-results page with a mix of correct/incorrect/partial/awaiting-review rows, and a lesson unit with a question, and screenshots each in light and dark (`data-theme`). Self-critique the feedback-panel tints and focus rings against the catalog/outline vocabulary, then delete the harness.

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/css/courses.css tests/test_consumption_css.py
git commit -m "style(consumption): align courses.css to design tokens; theme-correct feedback panels + focus rings"
```

---

## Task 2: Shared results/stat CSS components

A small reusable vocabulary for the two results pages: a headline summary block (big tabular score + label + meta line) and a list of result rows (title · status chip · score · action). Both `quiz_results` and `course_results` consume it in Tasks 3–4.

**Files:**
- Modify: `courses/static/courses/css/courses.css`
- Test: `tests/test_consumption_css.py`

**Interfaces:**
- Produces (class contract consumed by Tasks 3–4):
  - `.result` — page container (max-width column).
  - `.result-summary`, `.result-summary__score`, `.result-summary__label`, `.result-summary__meta`.
  - `.result-list`, `.result-row`, `.result-row__title`, `.result-row__score`, `.result-row__actions`.
  - status chips reuse `.badge` + new `.badge--review` (amber) / `.badge--muted`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_consumption_css.py`:

```python
def test_courses_css_defines_result_components():
    css = CSS.read_text(encoding="utf-8")
    for cls in [
        ".result-summary",
        ".result-summary__score",
        ".result-list",
        ".result-row",
        ".badge--review",
    ]:
        assert cls in css, f"missing result component class: {cls}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_consumption_css.py::test_courses_css_defines_result_components -v`
Expected: FAIL.

- [ ] **Step 3: Add the component block**

Append to `courses/static/courses/css/courses.css`:

```css
/* ── Results / stat components (batch 1 primitive) ────────────────────────────
   Shared by quiz_results (per-quiz) and course_results (per-course). A headline
   summary (big tabular score) over a list of result rows; status reuses .badge. */
.result { max-width: 46rem; margin-inline: auto; }
.result__title { margin: 0 0 var(--space-5); }

.result-summary {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--space-2) var(--space-4);
  padding: var(--space-4) var(--space-5); margin-bottom: var(--space-6);
  background: var(--surface-sunken);
  border: 1px solid var(--border-subtle); border-radius: var(--radius-lg);
}
.result-summary__score {
  font-size: 1.6rem; font-weight: 700; color: var(--text-primary);
  font-variant-numeric: tabular-nums; letter-spacing: var(--heading-letter-spacing);
}
.result-summary__label {
  font-size: .7rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
  color: var(--text-tertiary);
}
.result-summary__meta {
  margin-left: auto; color: var(--text-secondary); font-size: .9rem;
  font-variant-numeric: tabular-nums;
}

.result-list { list-style: none; margin: 0; padding: 0; }
.result-row {
  display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2) var(--space-3);
  padding: var(--space-3) var(--space-2);
  border-bottom: 1px solid var(--border-subtle);
}
.result-row__title { flex: 1 1 14rem; min-width: 0; font-weight: 500; color: var(--text-primary); }
.result-row__score { font-variant-numeric: tabular-nums; color: var(--text-secondary); font-weight: 600; }
.result-row__actions { margin-left: auto; display: flex; gap: var(--space-2); align-items: center; }
.result-row__actions a { color: var(--accent); text-decoration: none; font-weight: 500; }
.result-row__actions a:hover { text-decoration: underline; }

/* amber "awaiting review" / muted "not started" chips on top of the base .badge */
.badge--review {
  background: var(--warning-subtle); color: var(--warning);
  border-color: color-mix(in srgb, var(--warning) 40%, var(--border-default));
}
.badge--muted { color: var(--text-tertiary); }

@media (max-width: 640px) {
  .result-summary__meta { margin-left: 0; }
  .result-row__actions { margin-left: 0; width: 100%; }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_consumption_css.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/css/courses.css tests/test_consumption_css.py
git commit -m "style(results): add shared results/stat CSS components"
```

---

## Task 3: Restyle `quiz_results.html`

Wrap the page in the `.result` vocabulary: a `.result-summary` headline (score + awaiting-review meta) over the existing per-question feedback list, with each `<li>` reading as a clean card. **No context change** — the same `submission`, `rows`, `pending_count`, `pending_marks` variables.

**Files:**
- Modify: `templates/courses/quiz_results.html`
- Test: `tests/test_consumption_pages.py`

**Interfaces:**
- Consumes: `.result*` classes (Task 2), `.question__feedback-panel*` (Task 1), the `marks` filter (existing `courses_extras`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_consumption_pages.py`:

```python
import pytest
from django.urls import reverse

from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import make_login
from tests.factories import make_quiz_unit


@pytest.mark.django_db
def test_quiz_results_uses_result_vocabulary(client):
    user = make_login(client, "qr")
    course = CourseFactory(slug="qrc")
    EnrollmentFactory(student=user, course=course)
    unit = make_quiz_unit(course=course, title="Quiz One")
    QuizSubmissionFactory(student=user, unit=unit, status="submitted")
    resp = client.get(
        reverse("courses:quiz_results", kwargs={"slug": "qrc", "node_pk": unit.pk})
    )
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "result-summary" in body
    assert "Quiz One" in body
```

(If `make_quiz_unit`/`QuizSubmissionFactory` need extra args in this repo, mirror their use in `tests/test_quiz_views.py`; the assertion of interest is `result-summary` in the body.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_consumption_pages.py::test_quiz_results_uses_result_vocabulary -v`
Expected: FAIL — `result-summary` not in body.

- [ ] **Step 3: Restyle the template**

Replace the `{% block content %}` of `templates/courses/quiz_results.html` with (keep the `extra_css`/`extra_js` blocks unchanged):

```html
{% block content %}
<article class="quiz-results result" lang="{{ course.language }}">
  <h1 class="result__title">{{ unit.title }} — {% trans "results" %}</h1>

  <div class="result-summary">
    <span class="result-summary__label">{% trans "Score" %}</span>
    {% if submission.max_score %}
      <span class="result-summary__score">{{ submission.score|marks }} / {{ submission.max_score|marks }}</span>
    {% else %}
      <span class="result-summary__score">—</span>
    {% endif %}
    {% if pending_count %}
      <span class="result-summary__meta">{% blocktrans count n=pending_count with m=pending_marks|marks %}{{ n }} question awaiting review (up to {{ m }} more marks){% plural %}{{ n }} questions awaiting review (up to {{ m }} more marks){% endblocktrans %}</span>
    {% endif %}
  </div>

  <ol class="quiz-results__list">
    {% for row in rows %}
    <li class="quiz-results__item is-{{ row.outcome }}" data-question>
      <div class="question__stem">{{ row.question.stem|safe }}</div>
      <div class="question__feedback-panel question__feedback-panel--{{ row.outcome }}">
      {% if row.outcome == "correct" %}<span class="badge">{% trans "Correct" %} ({{ row.earned|marks }}/{{ row.possible|marks }})</span>
      {% elif row.outcome == "partial" %}<span class="badge">{% trans "Partial" %} ({{ row.earned|marks }}/{{ row.possible|marks }})</span>
      {% elif row.outcome == "incorrect" %}<span class="badge">{% trans "Incorrect" %} (0/{{ row.possible|marks }})</span>
      {% elif row.outcome == "not_answered" %}<span class="badge badge--muted">{% trans "Not answered" %}</span>
      {% elif row.outcome == "recorded" %}<span class="badge">{% trans "Answer recorded" %}</span>
      {% elif row.outcome == "reviewed" %}<span class="badge">{% trans "Reviewed" %} ({{ row.earned|marks }}/{{ row.possible|marks }})</span>
      {% elif row.outcome == "review" %}<span class="badge badge--review">{% trans "Awaiting review" %} ({% blocktrans with m=row.possible|marks %}up to {{ m }} marks{% endblocktrans %})</span>{% endif %}
      {% if row.review_feedback %}
        <div class="question__feedback question__feedback--review">
          <p>{{ row.review_feedback }}</p>
        </div>
      {% endif %}
      {% if row.reveal_template and row.outcome != "correct" %}
        {% include row.reveal_template with el=row.question mark_result=row.reveal_result choices=row.choices answered=row.answered %}
      {% endif %}
      {% if row.question.explanation and row.outcome != "recorded" and row.outcome != "review" and row.outcome != "reviewed" %}
        <div class="question__explanation">{{ row.question.explanation|safe }}</div>
      {% endif %}
      </div>
    </li>
    {% endfor %}
  </ol>

  <a class="btn btn--ghost" href="{% url 'courses:course_outline' slug=course.slug %}">{% trans "Back to course" %}</a>
</article>
{% endblock %}
```

Add list/card chrome to `courses.css` (append):

```css
/* quiz-results: each result item reads as a quiet card */
.quiz-results__list { list-style: none; margin: 0 0 var(--space-6); padding: 0;
  display: flex; flex-direction: column; gap: var(--space-4); }
.quiz-results__item {
  padding: var(--space-4) var(--space-5);
  background: var(--surface-raised);
  border: 1px solid var(--border-subtle); border-radius: var(--radius-lg);
}
.quiz-results__item .question__stem { margin-bottom: var(--space-2); }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_consumption_pages.py::test_quiz_results_uses_result_vocabulary -v`
Expected: PASS.

- [ ] **Step 5: Screenshot self-review (light + dark)** — render a results page with correct/partial/incorrect/awaiting-review rows; verify the headline + chips + cards in both themes; delete the harness.

- [ ] **Step 6: Commit**

```bash
git add templates/courses/quiz_results.html courses/static/courses/css/courses.css tests/test_consumption_pages.py
git commit -m "style(quiz-results): adopt the results/stat vocabulary"
```

---

## Task 4: Restyle `course_results.html`

The per-course summary becomes a `.result-summary` headline over `.result-row` rows with status chips (`submitted`/`awaiting_review`/`in_progress`/`not started`). **No context change** — same `summary` object.

**Files:**
- Modify: `templates/courses/course_results.html`
- Test: `tests/test_consumption_pages.py`

**Interfaces:** consumes `.result*` classes (Task 2), `.badge`/`.badge--review`/`.badge--muted`, `marks` filter.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_consumption_pages.py`:

```python
@pytest.mark.django_db
def test_course_results_uses_result_rows(client):
    user = make_login(client, "cr")
    course = CourseFactory(slug="crc", title="Course X")
    EnrollmentFactory(student=user, course=course)
    resp = client.get(reverse("courses:course_results", kwargs={"slug": "crc"}))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "result-summary" in body
    assert "Course X" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_consumption_pages.py::test_course_results_uses_result_rows -v`
Expected: FAIL.

- [ ] **Step 3: Restyle the template**

Replace the `{% block content %}` of `templates/courses/course_results.html`:

```html
{% block content %}
<article class="course-results result" lang="{{ course.language }}">
  <h1 class="result__title">{{ course.title }} — {% trans "My results" %}</h1>

  <div class="result-summary">
    <span class="result-summary__label">{% trans "Quizzes" %}</span>
    <span class="result-summary__score">{% blocktrans with done=summary.done_count total=summary.total_count %}{{ done }} / {{ total }}{% endblocktrans %}</span>
    {% if summary.percent is not None %}
      <span class="result-summary__meta">{{ summary.percent }}% · {{ summary.score|marks }} / {{ summary.max_score|marks }}</span>
    {% endif %}
  </div>

  {% if summary.rows %}
  <ul class="result-list">
    {% for row in summary.rows %}
    <li class="result-row is-{{ row.status }}">
      <span class="result-row__title">{{ row.unit.title }}</span>
      {% if row.status == "submitted" %}
        {% if row.graded %}<span class="result-row__score">{{ row.score|marks }} / {{ row.max_score|marks }}</span>
        {% else %}<span class="badge badge--muted">{% trans "submitted — not graded" %}</span>{% endif %}
        <span class="result-row__actions"><a href="{% url row.url_name slug=course.slug node_pk=row.unit.pk %}">{% trans "details" %}</a></span>
      {% elif row.status == "awaiting_review" %}
        {% if row.graded %}<span class="result-row__score">{{ row.score|marks }} / {{ row.max_score|marks }}</span>{% endif %}
        <span class="badge badge--review">{% trans "Awaiting review" %}</span>
        <span class="result-row__actions"><a href="{% url row.url_name slug=course.slug node_pk=row.unit.pk %}">{% trans "details" %}</a></span>
      {% elif row.status == "in_progress" %}
        <span class="badge">{% trans "in progress" %}</span>
        <span class="result-row__actions"><a href="{% url row.url_name slug=course.slug node_pk=row.unit.pk %}">{% trans "resume" %}</a></span>
      {% else %}
        <span class="badge badge--muted">{% trans "not started" %}</span>
        <span class="result-row__actions"><a href="{% url row.url_name slug=course.slug node_pk=row.unit.pk %}">{% trans "start" %}</a></span>
      {% endif %}
    </li>
    {% endfor %}
  </ul>
  {% else %}
    <p class="result__empty muted">{% trans "No quizzes in this course yet" %}</p>
  {% endif %}

  <a class="btn btn--ghost" href="{% url 'courses:course_outline' slug=course.slug %}">{% trans "Back to course" %}</a>
</article>
{% endblock %}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_consumption_pages.py::test_course_results_uses_result_rows -v`
Expected: PASS.

- [ ] **Step 5: i18n** — `{% trans "Quizzes" %}` is the one likely-new msgid. Run `uv run python manage.py makemessages -l pl`, add the Polish translation (`"Quizy"`), clear any stray `#, fuzzy`, then `uv run python manage.py compilemessages`.

- [ ] **Step 6: Screenshot self-review (light + dark)** — a course with rows in each status; verify chips and the headline; delete the harness.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/course_results.html locale/ tests/test_consumption_pages.py
git commit -m "style(course-results): adopt result rows + status chips"
```

---

## Task 5: Restyle `my_courses.html`

The bare `<ul>` becomes a responsive card grid — one card per enrolled course linking to its outline, with a secondary "My results" link — reusing the catalog's calm card idiom (lighter, no spine).

**Files:**
- Modify: `templates/courses/my_courses.html`, `core/static/core/css/app.css`
- Test: `tests/test_consumption_pages.py`

**Interfaces:** consumes new `.dash-cards`/`.dash-card` classes (added here, in `app.css` which `my_courses` already loads via base).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_consumption_pages.py`:

```python
@pytest.mark.django_db
def test_my_courses_renders_cards(client):
    user = make_login(client, "mc")
    course = CourseFactory(slug="mcc", title="Algebra")
    EnrollmentFactory(student=user, course=course)
    resp = client.get(reverse("courses:my_courses"))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "dash-card" in body
    assert "Algebra" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_consumption_pages.py::test_my_courses_renders_cards -v`
Expected: FAIL.

- [ ] **Step 3: Restyle the template**

Replace `{% block content %}` of `templates/courses/my_courses.html`:

```html
{% block content %}
<section class="courses-list">
  <h1>{% trans "My courses" %}</h1>
  {% if courses %}
    <ul class="dash-cards">
      {% for course in courses %}
        <li class="dash-card">
          <a class="dash-card__title" href="{% url 'courses:course_outline' slug=course.slug %}">{{ course.title }}</a>
          <span class="dash-card__actions">
            <a href="{% url 'courses:course_results' slug=course.slug %}">{% trans "My results" %}</a>
          </span>
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <p class="empty muted">{% trans "You are not enrolled in any courses yet." %}</p>
  {% endif %}
</section>
{% endblock %}
```

Add to `core/static/core/css/app.css`:

```css
/* Dashboard / my-courses card grid */
.dash-cards { list-style: none; margin: var(--space-5) 0 0; padding: 0;
  display: grid; gap: var(--space-4); grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); }
.dash-card { display: flex; flex-direction: column; gap: var(--space-2);
  padding: var(--space-5); background: var(--surface-raised);
  border: 1px solid var(--border-subtle); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm); transition: box-shadow .15s ease, transform .15s ease; }
.dash-card:hover { box-shadow: var(--shadow-md); transform: translateY(-2px); }
.dash-card__title { font-size: 1.05rem; font-weight: 600; color: var(--text-primary); text-decoration: none; }
.dash-card__title:hover { text-decoration: underline; }
.dash-card__actions { margin-top: auto; }
.dash-card__actions a { color: var(--accent); text-decoration: none; font-weight: 500; font-size: .9rem; }
.dash-card__actions a:hover { text-decoration: underline; }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_consumption_pages.py::test_my_courses_renders_cards -v`
Expected: PASS. Also run the existing `tests/test_courses_views.py::test_my_courses_lists_only_enrollments` to confirm no regression.

- [ ] **Step 5: Screenshot self-review (light + dark)** — a few enrolled courses; verify grid + hover-lift; delete the harness.

- [ ] **Step 6: Commit**

```bash
git add templates/courses/my_courses.html core/static/core/css/app.css tests/test_consumption_pages.py
git commit -m "style(my-courses): responsive course-card grid"
```

---

## Task 6: Restyle `home.html` (dashboard)

The role-gated `.card` sections become a consistent dashboard panel grid (same surfaces/tokens, a clear panel header, a 2-up grid on wide screens). **No logic change** — keep every `{% if %}` gate and link exactly as-is; only the wrapper classes and CSS change.

**Files:**
- Modify: `templates/core/home.html`, `core/static/core/css/app.css`
- Test: `tests/test_consumption_pages.py`

**Interfaces:** consumes new `.dash-grid`/`.dash-panel` classes (added in `app.css`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_consumption_pages.py`:

```python
@pytest.mark.django_db
def test_home_dashboard_uses_panels(client):
    make_login(client, "home1")
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "dash-panel" in body
```

(Confirm the home URL name via `tests/` usage — it is `home` per `base.html`'s `{% url 'home' %}`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_consumption_pages.py::test_home_dashboard_uses_panels -v`
Expected: FAIL.

- [ ] **Step 3: Restyle the template**

In `templates/core/home.html`, wrap the sections in a grid and swap `class="card" data-section="…"` for `class="dash-panel" data-section="…"`, and each `<h2>` keeps its text but gains `class="dash-panel__title"`. Replace the body after the `<h1>` with:

```html
<div class="dash-grid">
{% if is_student or enrolled_courses %}
<section class="dash-panel" data-section="learning">
  <h2 class="dash-panel__title">{% trans "My learning" %}</h2>
  {% if enrolled_courses %}
  <ul class="dash-list">
    {% for course in enrolled_courses %}
    <li><a href="{% url 'courses:course_outline' slug=course.slug %}">{{ course.title }}</a></li>
    {% endfor %}
  </ul>
  {% else %}
  <p class="helptext">{% trans "No courses yet." %}</p>
  {% endif %}
</section>
{% endif %}

{% if is_teacher %}
<section class="dash-panel" data-section="teaching">
  <h2 class="dash-panel__title">{% trans "Teaching" %}</h2>
  <p class="helptext">{% trans "No classes assigned yet." %}</p>
</section>
{% endif %}

{% if can_manage_courses %}
<section class="dash-panel" data-section="manage">
  <h2 class="dash-panel__title">{% trans "Authoring" %}</h2>
  <p><a href="{% url 'courses:manage_course_list' %}">{% trans "Manage courses" %}</a></p>
</section>
{% endif %}

{% if is_course_admin or is_platform_admin %}
<section class="dash-panel" data-section="admin">
  <h2 class="dash-panel__title">{% trans "Administration" %}</h2>
  <p><a href="{% url 'core:user_settings' %}">{% trans "Settings" %}</a></p>
  {% if is_platform_admin %}
  <p><a href="{% url 'core:institution_settings' %}">{% trans "Institution settings" %}</a></p>
  {% endif %}
</section>
{% endif %}

{% if not is_student and not is_teacher and not is_course_admin and not is_platform_admin and not enrolled_courses and not can_manage_courses %}
<section class="dash-panel" data-section="generic">
  <p class="helptext">{% trans "Your dashboard will fill in as you are added to courses." %}</p>
</section>
{% endif %}
</div>

{% if not user.is_staff and not user.is_superuser and not is_teacher and not is_course_admin and not is_platform_admin %}
<p class="dash-browse"><a class="btn btn--ghost" href="{% url 'courses:catalog' %}">{% trans "Browse courses" %}</a></p>
{% endif %}
```

Add to `core/static/core/css/app.css`:

```css
/* Home dashboard panels */
.dash-grid { display: grid; gap: var(--space-4); margin-top: var(--space-5);
  grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); }
.dash-panel { padding: var(--space-5); background: var(--surface-raised);
  border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); box-shadow: var(--shadow-sm); }
.dash-panel__title { margin: 0 0 var(--space-3); font-size: 1rem; font-weight: 600; color: var(--text-primary); }
.dash-browse { margin-top: var(--space-6); }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_consumption_pages.py::test_home_dashboard_uses_panels -v`
Expected: PASS. Run any existing `home` tests to confirm the role gates still render.

- [ ] **Step 5: Screenshot self-review (light + dark)** — log in as a multi-role user (or stub the gates) so several panels show; verify the grid in both themes; delete the harness.

- [ ] **Step 6: Commit**

```bash
git add templates/core/home.html core/static/core/css/app.css tests/test_consumption_pages.py
git commit -m "style(home): dashboard panel grid"
```

---

## Task 7: `code-field` CSS primitive + reusable widget

The batch-1 primitive consumed by **batch 4** (the author code-editor fields). Per spec §5: a theme-following, monospace, line-number-guttered, no-soft-wrap container around a textarea — **plain monospace, no syntax highlighting, no JS in this batch** (the gutter/Tab JS ships in batch 4). Here we deliver the CSS + a reusable Django widget that emits the wrapper markup, so batch 4 only adds the JS enhancement.

**Files:**
- Create: `courses/widgets.py`
- Modify: `courses/static/courses/css/courses.css`
- Test: `tests/test_code_field_widget.py`, `tests/test_consumption_css.py`

**Interfaces:**
- Produces: `CodeTextarea` widget (in `courses/widgets.py`) rendering a `<div class="code-field" data-code-field>` wrapper around the textarea with a `code-field__gutter` placeholder; and the `.code-field*` CSS. Batch 4 consumes both (its JS targets `[data-code-field]`).

- [ ] **Step 1: Write the failing widget test**

Create `tests/test_code_field_widget.py`:

```python
from courses.widgets import CodeTextarea


def test_code_textarea_wraps_in_code_field():
    html = CodeTextarea().render("html", "<b>x</b>", attrs={"id": "id_html"})
    assert 'class="code-field"' in html
    assert "data-code-field" in html
    assert "<textarea" in html
    # the user's content is preserved and HTML-escaped inside the textarea
    assert "&lt;b&gt;x&lt;/b&gt;" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_code_field_widget.py -v`
Expected: FAIL — `courses.widgets` / `CodeTextarea` does not exist.

- [ ] **Step 3: Implement the widget**

Create `courses/widgets.py`:

```python
from django import forms
from django.utils.safestring import mark_safe


class CodeTextarea(forms.Textarea):
    """A plain-monospace code field: the standard textarea wrapped in the
    ``.code-field`` shell (header label + line-number gutter) that batch 4's
    JS enhances (gutter sync + Tab-to-indent). No syntax highlighting.

    With JS off it degrades to the styled monospace textarea — the wrapper and
    gutter are inert. The ``data-code-field`` hook is what the JS module targets.
    """

    def __init__(self, attrs=None):
        base = {"spellcheck": "false", "autocomplete": "off", "wrap": "off"}
        if attrs:
            base.update(attrs)
        super().__init__(attrs=base)

    def render(self, name, value, attrs=None, renderer=None):
        textarea = super().render(name, value, attrs=attrs, renderer=renderer)
        return mark_safe(
            '<div class="code-field" data-code-field>'
            '<div class="code-field__gutter" aria-hidden="true"></div>'
            f'<div class="code-field__area">{textarea}</div>'
            "</div>"
        )
```

- [ ] **Step 4: Run the widget test to verify it passes**

Run: `uv run pytest tests/test_code_field_widget.py -v`
Expected: PASS.

- [ ] **Step 5: Add the `.code-field` CSS + a CSS-presence guard**

Append to `tests/test_consumption_css.py`:

```python
def test_courses_css_defines_code_field():
    css = CSS.read_text(encoding="utf-8")
    for cls in [".code-field", ".code-field__gutter", ".code-field__area"]:
        assert cls in css, f"missing code-field class: {cls}"
```

Run it (FAIL), then append to `courses/static/courses/css/courses.css`:

```css
/* ── code-field primitive (batch 1; JS enhancement in batch 4) ────────────────
   Theme-following monospace editor look: header-less gutter + textarea, no soft
   wrap (gutter maps 1:1 to logical lines), no syntax highlighting. */
.code-field {
  display: flex; font-family: var(--font-mono, "SFMono-Regular", ui-monospace, "Cascadia Code", "Consolas", monospace);
  font-size: .85rem; line-height: 1.6;
  border: 1px solid var(--border-default); border-radius: var(--radius-sm);
  overflow: hidden; background: var(--surface-raised);
}
.code-field__gutter {
  flex: none; min-width: 2.25rem; padding: var(--space-2) var(--space-2);
  text-align: right; color: var(--text-tertiary); background: var(--surface-sunken);
  border-right: 1px solid var(--border-subtle); user-select: none; white-space: pre;
}
.code-field__area { flex: 1; min-width: 0; }
.code-field__area textarea {
  display: block; width: 100%; min-height: 9rem; margin: 0;
  padding: var(--space-2) var(--space-3); border: 0; border-radius: 0; resize: vertical;
  background: var(--surface-raised); color: var(--text-primary);
  font: inherit; white-space: pre; overflow-x: auto; tab-size: 2;
}
.code-field__area textarea:focus { outline: none; box-shadow: inset 0 0 0 2px var(--primary-subtle); }
```

Add a `--font-mono` token to `core/static/core/css/tokens.css` `:root` (after `--font-ui`) so the stack is centralised:

```css
  --font-mono: "SFMono-Regular", ui-monospace, "Cascadia Code", "Consolas", monospace;
```

(and drop the inline fallback in the `.code-field` rule to `var(--font-mono)` once the token exists.)

- [ ] **Step 6: Run the CSS guard + format**

Run: `uv run pytest tests/test_consumption_css.py -v`
Expected: PASS.

- [ ] **Step 7: Lint + full suite**

Run: `uv run ruff check courses/widgets.py tests/test_code_field_widget.py` and `uv run ruff format --check courses/widgets.py tests/test_code_field_widget.py`, then `uv run pytest -q`.
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add courses/widgets.py courses/static/courses/css/courses.css core/static/core/css/tokens.css tests/test_code_field_widget.py tests/test_consumption_css.py
git commit -m "feat(code-field): monospace code-field widget + CSS primitive (batch-1, JS in batch 4)"
```

---

## Final verification (whole batch)

- [ ] **Run the full suite + lint/format:**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all green.

- [ ] **Recompile translations** (if Task 4 added the `Quizzes` msgid): `uv run python manage.py compilemessages`.

- [ ] **Whole-batch screenshot pass:** light + dark screenshots of `home`, `my_courses`, `quiz_results`, `course_results`, and a lesson/quiz unit (feedback panels); self-critique for consistency with the catalog/outline/manage vocabulary; delete the harness.

---

## Self-Review (author checklist — completed)

**1. Spec coverage (batch 1 scope):**
- §6 consistency-pass pages: `home` (Task 6), `my_courses` (Task 5), `quiz_results` (Task 3), `course_results` (Task 4) ✓
- §6 element-display polish (feedback/reveal partials, widgets, media, dark-mode parity): Task 1 (token alignment + feedback panels + focus + media via the shared `.el--*`/`.dnd__*`/`.question__*` rules) ✓
- §2 results/stat components primitive: Task 2 ✓
- §5 code-field primitive (CSS + widget; **no JS**, no highlighter): Task 7 ✓
- **Deliberately deferred (surfaced to the user):** the **unit-shell** CSS+partial primitive → moved to batch 2 (first task), because a CSS-only primitive with no consumer/test in batch 1 isn't independently verifiable; its CSS lands in shared `courses.css` so batch 3's roster still reuses it (preserving the spec's "dependency through shared primitives, not batch 2→3" intent). The spec's §2/§3.1 wording ("unit shell extracted in batch 1") should be reconciled to "batch 2" — noted for the user.

**2. Placeholder scan:** no TBD/TODO; every step shows real CSS/markup/Python and exact `uv run` commands with expected results. ✓

**3. Type/name consistency:** the class contract produced in Task 2 (`.result-summary`, `.result-row`, `.badge--review`, `.badge--muted`) is exactly what Tasks 3–4 consume; the `code-field`/`data-code-field` hook produced in Task 7 is what batch 4 will target; `CodeTextarea` is the single widget name. ✓
