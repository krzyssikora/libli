# Course Glance Bars Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Under each enrolled course on the dashboard ("My learning") and My courses, draw two thin number-free bars — progress (required lessons) and results (cumulative quiz score) — and replace the landing page's three hardcoded boxes with translated sample cards drawn by the same partial.

**Architecture:** Pure width helpers + `course_glance()` in `courses/rollups.py` reuse `build_outline` and `build_course_results` (no new arithmetic). A containment wrapper `course_glance_or_unknown()` keeps one broken course from 500-ing the dashboard. A new `courses/glance.py` builds `(course, glance)` pairs (it owns the access-layer `can_see_drafts` call so rollups stays access-free). One partial `templates/courses/_course_glance.html` renders both bars; CSS lives in `core/static/core/css/app.css`.

**Tech Stack:** Django templates + i18n (`trans`/`blocktrans … context`), pytest + pytest-django + factory_boy, BeautifulSoup for render assertions, Playwright (e2e marker) for the screenshot capture.

**Spec:** `docs/superpowers/specs/2026-09-22-course-glance-bars-design.md` — read it; the owner-decisions table D1–D9 is binding and must not be reversed.

## Global Constraints

- **Worktree setup (once, before Task 1):** the worktree has no `.env`. Copy it from the main repo: `cp ../../libli/.env .env` (it is gitignored — never commit it). Start the test DB container once: `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`. Never run two pytest processes at once (shared test DB).
- Run tests with `uv run pytest <paths>` from the worktree root. **Never pass `-q`** (addopts already has it; doubling hides the summary). Always read the final summary line — do not trust the exit code alone.
- Imports: ruff `force-single-line = true` — one `from x import y` per line. Before each commit, in this order: `uv run ruff format <changed .py files>`, `uv run ruff check --no-cache <changed .py files>`, `uv run ruff format --check <changed .py files>` (the plan's pasted code is not pre-formatted; `format` wraps it, then the gates must pass).
- Django template comments `{# #}` are SINGLE-LINE only; multi-line needs `{% comment %}`.
- CSS comments: never put `*/` inside a comment's text (it ends the comment early and eats the next rule).
- All new user-facing strings carry `context "course glance"`. Polish catalog is real Polish, not machine noise.
- i18n workflow: `uv run python manage.py makemessages -l pl -l en --no-obsolete`, translate, clear any `#, fuzzy` flag AND its `#| msgid` line, then `uv run python manage.py compilemessages`. Both `locale/en` and `locale/pl` `.po` + `.mo` are tracked and committed.
- Templates test `is None` / `== 0`, never truthiness and never ordering comparisons (`> 0`) on a width.
- Every include of the partial passes BOTH `progress_width` and `results_width` explicitly and uses `only`.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01JkhCCm7Sexv6PCaaAtV53p
  ```
- `git add` with explicit paths only (never `-A` / `.`).
- When a step says "append" tests that come with their own `import`/`from` lines, put those
  imports in the file's TOP import block (ruff `E402` forbids mid-file imports) and append
  only the helpers and tests.

## File structure

| File | Responsibility |
|---|---|
| `courses/rollups.py` (modify) | `_course_required_totals`, `_progress_width`, `_results_width`, `course_glance`, `UNKNOWN_GLANCE`, `course_glance_or_unknown`; `build_unit_nav` uses `_course_required_totals` |
| `courses/glance.py` (create) | `enrolled_course_glances(user)` → list of `(course, glance)` pairs, drafts chosen via `can_see_drafts` |
| `templates/courses/_course_glance.html` (create) | the two-bar partial |
| `core/static/core/css/app.css` (modify) | `.glance*`, `.glance-card*`, forced-colors; remove `.landing-visual .card` |
| `courses/views.py` (modify `my_courses`) / `templates/courses/my_courses.html` | pairs + partial in each `.dash-card` |
| `core/views.py` (modify `home`) / `templates/core/home.html` | pairs + partial in "My learning" |
| `templates/core/landing.html` | three `.glance-card` sample cards |
| `locale/{en,pl}/LC_MESSAGES/django.{po,mo}` | new msgids + Polish |
| `tests/test_course_glance.py` (create) | helpers, `course_glance`, containment, query counts |
| `tests/test_course_glance_render.py` (create) | partial render, i18n, views, landing |
| `tests/capture_glance_screenshots.py` (create) | e2e light/dark/forced-colors capture + contrast + timing (not auto-collected) |

---

### Task 1: Pure helpers and the shared required-totals helper

**Files:**
- Modify: `courses/rollups.py` (add helpers near `_pct` ~line 812; refactor `course_progress` in `build_unit_nav` ~line 1104)
- Test: `tests/test_course_glance.py` (create)

**Interfaces:**
- Produces: `_course_required_totals(tree) -> tuple[int, int]` (done, total); `_progress_width(done: int, total: int) -> int | None`; `_results_width(score, max_score, percent) -> int | None` (score/max_score are `Decimal | None`, percent `int | None`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_course_glance.py`:

```python
"""Course glance bars (spec 2026-09-22-course-glance-bars-design.md)."""

from decimal import Decimal

import pytest

from courses.rollups import _course_required_totals
from courses.rollups import _pct
from courses.rollups import _progress_width
from courses.rollups import _results_width


@pytest.mark.parametrize(
    ("done", "total", "expected"),
    [
        (0, 0, None),  # no required lessons: track only (D4)
        (0, 5, None),  # nothing done: track only, NO dot (D4)
        (1, 250, 1),  # rounds to 0 but must still draw a sliver
        (199, 200, 99),  # rounds to 100 but the course is not finished
        (1, 2, 50),
        (5, 5, 100),
        (6, 5, 100),  # defensive: done > total is still full, never 99
    ],
)
def test_progress_width(done, total, expected):
    assert _progress_width(done, total) == expected


@pytest.mark.parametrize(
    ("score", "max_score", "percent", "expected"),
    [
        (None, None, None, None),  # nothing submitted
        (Decimal("0"), Decimal("0"), None, None),  # pending-only / max 0: NOT the dot
        (Decimal("0"), Decimal("10"), 0, 0),  # scored zero: the dot (D3)
        (Decimal("1"), Decimal("300"), 0, 1),  # branches on score, not rounded pct
        (Decimal("299"), Decimal("300"), 100, 99),  # not full while short of max
        (Decimal("16"), Decimal("20"), 80, 80),  # D1 example
        (Decimal("10"), Decimal("10"), 100, 100),
        (Decimal("11"), Decimal("10"), 110, 100),  # score > max stays full
    ],
)
def test_results_width(score, max_score, percent, expected):
    assert _results_width(score, max_score, percent) == expected


def test_results_width_half_boundary_matches_pct():
    # 1/8 = 12.5 -> ROUND_HALF_EVEN -> 12, the same rounding as the spoken percent
    assert _results_width(Decimal("1"), Decimal("8"), _pct(1, 8)) == 12 == _pct(1, 8)


def test_course_required_totals_sums_top_level_items():
    tree = [
        {"required_done": 1, "required_total": 3},
        {"required_done": 2, "required_total": 2},
    ]
    assert _course_required_totals(tree) == (3, 5)
    assert _course_required_totals([]) == (0, 0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_course_glance.py`
Expected: collection ERROR — `ImportError: cannot import name '_course_required_totals'`.

- [ ] **Step 3: Implement the helpers**

In `courses/rollups.py`, directly after `_pct` (keep `_pct` unchanged), add:

```python
def _course_required_totals(tree):
    """(done, total) of required lessons over a build_outline tree's top-level items.

    The ONE place the course-level sum lives: build_unit_nav's course_progress and
    course_glance both read it, so "required" can never drift between the rail and
    the dashboard bars.
    """
    done = sum(d["required_done"] for d in tree)
    total = sum(d["required_total"] for d in tree)
    return done, total


def _clamp_partial(value):
    """A partial (not complete) width is drawn in 1..99: never an empty-looking 0
    for a started course, never a full-looking 100 for an unfinished one."""
    return min(max(value, 1), 99)


def _progress_width(done, total):
    """Drawn progress width. None = track only (no required lessons, or none done:
    D4 -- no dot for progress). 100 only when complete."""
    if total <= 0 or done <= 0:
        return None
    if done >= total:
        return 100
    return _clamp_partial(_pct(done, total))


def _results_width(score, max_score, percent):
    """Drawn results width. The check ORDER is load-bearing:

    1. percent None -> None (track only). Must come first: build_course_results
       returns score == Decimal("0"), not None, for a pending-only course or a
       max_score == 0 quiz, and those must not draw the zero-dot.
    2. score exactly 0 -> 0 (the zero-dot, D3).
    3. score >= max -> 100; else _pct (the percent's own rounding) clamped 1..99.

    Branches on `score`, never on the rounded percent: 1/300 is a sliver, not the dot.
    """
    if percent is None:
        return None
    if score == 0:
        return 0
    if score >= max_score:
        return 100
    return _clamp_partial(_pct(score, max_score))
```

In `build_unit_nav`, replace:

```python
    course_progress = {
        "done": sum(d["required_done"] for d in tree),
        "total": sum(d["required_total"] for d in tree),
    }
```

with:

```python
    done, total = _course_required_totals(tree)
    course_progress = {"done": done, "total": total}
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_course_glance.py tests/test_courses_rollups.py $(grep -rlE 'build_unit_nav|course_progress|unit-foot__course' --include='test_*.py' . | grep -v test_e2e_ | grep -v '/.venv/' | sort -u)
```

Expected: all PASS (every non-e2e test that touches `build_unit_nav` / `course_progress` / the footer bar proves the refactor changed nothing).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format courses/rollups.py tests/test_course_glance.py
uv run ruff check --no-cache courses/rollups.py tests/test_course_glance.py
uv run ruff format --check courses/rollups.py tests/test_course_glance.py
git add courses/rollups.py tests/test_course_glance.py
git commit -m "feat(glance): width helpers and shared required-totals sum"
```

---

### Task 2: `course_glance`, containment wrapper, and query-count guarantees

**Files:**
- Modify: `courses/rollups.py` (add `import logging`, `logger`, `course_glance`, `UNKNOWN_GLANCE`, `course_glance_or_unknown`)
- Test: `tests/test_course_glance.py` (append)

**Interfaces:**
- Consumes: Task 1 helpers; existing `build_outline(course, user, *, drafts)`, `build_course_results(course, student, *, drafts)`.
- Produces:
  - `course_glance(course, user, *, drafts) -> dict` with exactly the keys `progress_done: int`, `progress_total: int`, `results_pct: int | None`, `progress_width: int | None`, `results_width: int | None`.
  - `UNKNOWN_GLANCE: dict` = `{"progress_done": 0, "progress_total": 0, "results_pct": None, "progress_width": None, "results_width": None}`.
  - `course_glance_or_unknown(course, user, *, drafts) -> dict` — same keys; on any `Exception` from `course_glance` logs `logger.exception` with the course pk and returns a copy of `UNKNOWN_GLANCE`. It must call `course_glance` as a module global (tests patch `courses.rollups.course_glance`).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_course_glance.py`:

```python
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UnitProgressFactory
from tests.factories import UserFactory


def _lesson(course, *, obligatory=True, published=True):
    return ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        obligatory=obligatory,
        published=published,
    )


def _auto_quiz(course, student, *, score, max_score, max_marks=None):
    """A root quiz with one auto-marked short-text question and a SUBMITTED
    submission scored score/max_score."""
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=None)
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode="A", max_marks=max_marks or max_score
    )
    Element.objects.create(unit=unit, content_object=q)
    QuizSubmissionFactory(
        student=student,
        unit=unit,
        status="submitted",
        score=Decimal(score),
        max_score=Decimal(max_score),
    )
    return unit


def _review_quiz(course, student, *, reviewed):
    """A root quiz with one [R] extended-response question and a SUBMITTED
    submission; reviewed=True adds a reviewed response and scores it 4/5."""
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=None)
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss.",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal("5"),
    )
    el = Element.objects.create(unit=unit, content_object=q)
    sub = QuizSubmission.objects.create(
        student=student,
        unit=unit,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0.00"),
        max_score=Decimal("0.00"),
    )
    if reviewed:
        QuestionResponse.objects.create(
            submission=sub,
            element=el,
            earned_marks=Decimal("4.00"),
            fraction=Decimal("0.8000"),
            reviewed_at=timezone.now(),
            locked=True,
        )
        sub.score = Decimal("4.00")
        sub.max_score = Decimal("5.00")
        sub.save()
    return unit


GLANCE_KEYS = {
    "progress_done",
    "progress_total",
    "results_pct",
    "progress_width",
    "results_width",
}


@pytest.mark.django_db
def test_d1_cumulative_not_mean_of_percentages():
    from courses.rollups import course_glance

    course, student = CourseFactory(), UserFactory()
    _auto_quiz(course, student, score="9", max_score="10")
    _auto_quiz(course, student, score="3", max_score="5")
    _auto_quiz(course, student, score="4", max_score="5")
    g = course_glance(course, student, drafts="hide")
    assert set(g) == GLANCE_KEYS
    assert g["results_pct"] == 80  # 16/20, NOT mean(90, 60, 80) = 77
    assert g["results_width"] == 80


@pytest.mark.django_db
def test_no_submission_is_track_only():
    from courses.rollups import course_glance

    course, student = CourseFactory(), UserFactory()
    ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=None)
    g = course_glance(course, student, drafts="hide")
    assert g["results_pct"] is None and g["results_width"] is None


@pytest.mark.django_db
def test_scored_zero_is_the_dot():
    from courses.rollups import course_glance

    course, student = CourseFactory(), UserFactory()
    _auto_quiz(course, student, score="0", max_score="10")
    g = course_glance(course, student, drafts="hide")
    assert g["results_pct"] == 0 and g["results_width"] == 0


@pytest.mark.django_db
def test_pending_only_is_track_only_not_the_dot():
    from courses.rollups import course_glance

    course, student = CourseFactory(), UserFactory()
    _review_quiz(course, student, reviewed=False)
    g = course_glance(course, student, drafts="hide")
    assert g["results_pct"] is None
    assert g["results_width"] is None  # score is Decimal("0") here: order matters


@pytest.mark.django_db
def test_pending_quiz_is_excluded_from_the_sum():
    from courses.rollups import course_glance

    course, student = CourseFactory(), UserFactory()
    _auto_quiz(course, student, score="3", max_score="4")
    _review_quiz(course, student, reviewed=False)
    g = course_glance(course, student, drafts="hide")
    assert g["results_pct"] == 75 and g["results_width"] == 75


@pytest.mark.django_db
def test_max_score_zero_quiz_is_track_only():
    from courses.rollups import course_glance

    course, student = CourseFactory(), UserFactory()
    _auto_quiz(course, student, score="0", max_score="0", max_marks=Decimal("0"))
    g = course_glance(course, student, drafts="hide")
    assert g["results_pct"] is None and g["results_width"] is None


@pytest.mark.django_db
def test_progress_counts_only_required_lessons():
    from courses.rollups import course_glance

    course, student = CourseFactory(), UserFactory()
    done = _lesson(course)
    _lesson(course)
    extra = _lesson(course, obligatory=False)
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, obligatory=True
    )
    UnitProgressFactory(student=student, unit=done, completed=True)
    UnitProgressFactory(student=student, unit=extra, completed=True)
    UnitProgressFactory(student=student, unit=quiz, completed=True)
    g = course_glance(course, student, drafts="hide")
    assert (g["progress_done"], g["progress_total"]) == (1, 2)
    assert g["progress_width"] == 50


@pytest.mark.django_db
def test_zero_of_n_and_no_required_lessons_are_track_only():
    from courses.rollups import course_glance

    student = UserFactory()
    untouched = CourseFactory()
    _lesson(untouched)
    g = course_glance(untouched, student, drafts="hide")
    assert (g["progress_done"], g["progress_total"]) == (0, 1)
    assert g["progress_width"] is None

    empty = CourseFactory()
    g = course_glance(empty, student, drafts="hide")
    assert g["progress_total"] == 0 and g["progress_width"] is None


@pytest.mark.django_db
def test_drafts_hide_excludes_draft_lessons():
    from courses.rollups import course_glance

    course, student = CourseFactory(), UserFactory()
    _lesson(course)
    _lesson(course, published=False)
    assert course_glance(course, student, drafts="hide")["progress_total"] == 1
    assert course_glance(course, student, drafts="keep")["progress_total"] == 2


@pytest.mark.django_db
def test_containment_logs_and_returns_unknown(monkeypatch, caplog):
    import courses.rollups as rollups

    course, student = CourseFactory(), UserFactory()

    def boom(*args, **kwargs):
        raise RuntimeError("inconsistent tree")

    monkeypatch.setattr(rollups, "course_glance", boom)
    with caplog.at_level("ERROR", logger="courses.rollups"):
        g = rollups.course_glance_or_unknown(course, student, drafts="hide")
    assert g == rollups.UNKNOWN_GLANCE
    assert g is not rollups.UNKNOWN_GLANCE  # a copy: callers cannot mutate the constant
    assert f"pk={course.pk}" in caplog.text
    assert "inconsistent tree" in caplog.text


def _shaped_course(student, n):
    """The query-count fixture shape (spec Testing): every query branch non-empty,
    ONE question type. n of each: required lessons (all completed), additional
    lessons, reviewed [R] quizzes with submissions."""
    course = CourseFactory()
    for _ in range(n):
        req = _lesson(course)
        UnitProgressFactory(student=student, unit=req, completed=True)
        _lesson(course, obligatory=False)
        _review_quiz(course, student, reviewed=True)
    return course


@pytest.mark.django_db
def test_course_glance_query_count_is_size_independent():
    from courses.rollups import course_glance

    student = UserFactory()
    small = _shaped_course(student, 1)
    large = _shaped_course(student, 5)
    course_glance(small, student, drafts="hide")  # warm the ContentType cache
    with CaptureQueriesContext(connection) as c_small:
        course_glance(small, student, drafts="hide")
    with CaptureQueriesContext(connection) as c_large:
        course_glance(large, student, drafts="hide")
    assert len(c_small) == len(c_large)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_course_glance.py`
Expected: new tests FAIL with `ImportError: cannot import name 'course_glance'` (Task 1 tests still pass).

- [ ] **Step 3: Implement** — in `courses/rollups.py`:

At the top, add `import logging` before `from decimal import Decimal`, and after the imports block add:

```python
logger = logging.getLogger(__name__)
```

These inserted lines shift `build_outline` down. A comment in `build_unit_nav`'s neighbourhood (~line 1177 on master, ~1225 after Task 1 — trust the grep, not the number) cites `rollups.py:228-234, leaf key at :249` (build_outline's `completed` set and its `"completed"` key). After the edit, `grep -n "rollups.py:[0-9]" courses/*.py`, open `build_outline`, and update that citation to the lines where the `completed = set()` block and the `"completed": is_unit and …` key now sit.

After `_results_width`, add:

```python
def course_glance(course, user, *, drafts):
    """The two at-a-glance figures for one enrolled course (spec §1).

    Spoken figures (exact) and drawn widths (clamped) are separate keys. Reuses
    build_outline and build_course_results -- no new arithmetic for "required" or
    for the D1 cumulative percent. `drafts` is REQUIRED: the caller decides.
    """
    done, total = _course_required_totals(build_outline(course, user, drafts=drafts))
    summary = build_course_results(course, user, drafts=drafts)
    return {
        "progress_done": done,
        "progress_total": total,
        "results_pct": summary["percent"],
        "progress_width": _progress_width(done, total),
        "results_width": _results_width(
            summary["score"], summary["max_score"], summary["percent"]
        ),
    }


UNKNOWN_GLANCE = {
    "progress_done": 0,
    "progress_total": 0,
    "results_pct": None,
    "progress_width": None,
    "results_width": None,
}


def course_glance_or_unknown(course, user, *, drafts):
    """course_glance, contained: the dashboard is the post-login landing page, so a
    rollup that raises for ONE course must not 500 it for every student in that
    course. Logs the full traceback and draws that course as track-only. The course's
    own outline/results pages still raise, so the bug stays visible there."""
    try:
        return course_glance(course, user, drafts=drafts)
    except Exception:
        logger.exception("course_glance failed for course pk=%s", course.pk)
        return dict(UNKNOWN_GLANCE)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_course_glance.py tests/test_courses_rollups.py`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format courses/rollups.py tests/test_course_glance.py
uv run ruff check --no-cache courses/rollups.py tests/test_course_glance.py
uv run ruff format --check courses/rollups.py tests/test_course_glance.py
git add courses/rollups.py tests/test_course_glance.py
git commit -m "feat(glance): course_glance and contained wrapper"
```

---

### Task 3: The partial, its CSS, and the translated strings

**Files:**
- Create: `templates/courses/_course_glance.html`
- Modify: `core/static/core/css/app.css` (add a block directly after the `.dash-card__actions a:hover` rule, ~line 869)
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: `tests/test_course_glance_render.py` (create)

**Interfaces:**
- Consumes: the glance dict keys from Task 2.
- Produces: `templates/courses/_course_glance.html`, included as
  `{% include "courses/_course_glance.html" with progress_width=… results_width=… progress_done=… progress_total=… results_pct=… only %}`
  or, decorative, `{% include "courses/_course_glance.html" with progress_width=… results_width=… decorative=True only %}`.
  DOM contract: `.glance` > two `.glance__row` > (`.glance__label[aria-hidden=true]`, `.glance__track`); inside a track, `.glance__fill[style="width: N%"]` or `.glance__dot` or nothing. Non-decorative tracks have `role="img"` and an `aria-label`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_course_glance_render.py`:

```python
"""Render contract of courses/_course_glance.html and its placements."""

import re

import pytest
from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.utils import translation


def _render(**ctx):
    ctx.setdefault("progress_done", 0)
    ctx.setdefault("progress_total", 0)
    ctx.setdefault("results_pct", None)
    html = render_to_string("courses/_course_glance.html", ctx)
    return BeautifulSoup(html, "html.parser")


def _tracks(soup):
    return soup.select(".glance__track")


@pytest.mark.parametrize(
    ("width", "fill", "dot"),
    [(None, False, False), (0, False, True), (1, True, False), (100, True, False)],
)
def test_results_fill_rules(width, fill, dot):
    soup = _render(progress_width=None, results_width=width, results_pct=width)
    track = _tracks(soup)[1]
    assert bool(track.select(".glance__fill")) is fill
    assert bool(track.select(".glance__dot")) is dot
    if fill:
        assert track.select_one(".glance__fill")["style"] == f"width: {width}%"


def test_progress_zero_of_n_draws_neither_fill_nor_dot():
    soup = _render(progress_width=None, results_width=None, progress_total=4)
    track = _tracks(soup)[0]
    assert not track.select(".glance__fill") and not track.select(".glance__dot")


def test_progress_fill_width():
    soup = _render(progress_width=37, results_width=None, progress_done=3, progress_total=8)
    assert _tracks(soup)[0].select_one(".glance__fill")["style"] == "width: 37%"


def test_labels_are_hidden_and_tracks_carry_names():
    soup = _render(progress_width=50, results_width=80, progress_done=1,
                   progress_total=2, results_pct=80)
    for label in soup.select(".glance__label"):
        assert label["aria-hidden"] == "true"
    progress, results = _tracks(soup)
    assert progress["role"] == "img" and results["role"] == "img"
    assert progress["aria-label"] == "Progress: 1 of 2 lessons"
    assert results["aria-label"] == "Results: 80%"


def test_english_plural_uses_count():
    one = _tracks(_render(progress_width=None, results_width=None,
                          progress_done=0, progress_total=1))[0]
    two = _tracks(_render(progress_width=None, results_width=None,
                          progress_done=0, progress_total=2))[0]
    assert one["aria-label"] == "Progress: 0 of 1 lesson"
    assert two["aria-label"] == "Progress: 0 of 2 lessons"


def test_none_figures_are_spoken():
    progress, results = _tracks(_render(progress_width=None, results_width=None))
    assert progress["aria-label"] == "Progress: no lessons to track"
    assert results["aria-label"] == "Results: no scores yet"


def test_no_visible_digits():
    soup = _render(progress_width=37, results_width=80, progress_done=3,
                   progress_total=8, results_pct=80)
    assert not re.search(r"\d", soup.select_one(".glance").get_text())


def test_decorative_emits_no_roles_or_labels():
    soup = _render(progress_width=70, results_width=85, decorative=True)
    for track in _tracks(soup):
        assert not track.has_attr("role") and not track.has_attr("aria-label")
    assert len(soup.select(".glance__fill")) == 2


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (1, "Postęp: 0 z 1 lekcji"),
        (3, "Postęp: 0 z 3 lekcji"),
        (5, "Postęp: 0 z 5 lekcji"),
    ],
)
def test_polish_progress_label(total, expected):
    with translation.override("pl"):
        track = _tracks(_render(progress_width=None, results_width=None,
                                progress_done=0, progress_total=total))[0]
    assert track["aria-label"] == expected


def test_polish_results_and_labels():
    with translation.override("pl"):
        soup = _render(progress_width=None, results_width=80, results_pct=80)
    assert _tracks(soup)[1]["aria-label"] == "Wyniki: 80%"  # single %, not %%
    labels = [x.get_text(strip=True) for x in soup.select(".glance__label")]
    assert labels == ["Postęp", "Wyniki"]
    with translation.override("pl"):
        none = _tracks(_render(progress_width=None, results_width=None))
    assert none[0]["aria-label"] == "Postęp: brak lekcji obowiązkowych"
    assert none[1]["aria-label"] == "Wyniki: jeszcze brak punktów"


def test_every_polish_plural_index_is_filled():
    from pathlib import Path

    from django.conf import settings

    po = (Path(settings.BASE_DIR) / "locale/pl/LC_MESSAGES/django.po").read_text(
        encoding="utf-8"
    )
    block = po.split('msgid "Progress: %(done)s of %(counter)s lesson"', 1)[1]
    block = block.split("\n\n", 1)[0]
    for i in range(3):
        m = re.search(rf'msgstr\[{i}\] "(.*)"', block)
        assert m and m.group(1), f"msgstr[{i}] is empty"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_course_glance_render.py`
Expected: FAIL with `TemplateDoesNotExist: courses/_course_glance.html` (and the .po test with IndexError).

- [ ] **Step 3: Create the partial** `templates/courses/_course_glance.html`:

```django
{% load i18n %}
{% comment %}
Course glance: two number-free bars (spec 2026-09-22-course-glance-bars-design.md).
Widths: None = track only, 0 = the zero-dot, 1..100 = a fill. Never test a width with
truthiness or ">": None and 0 mean different things (D3/D4). Every include passes both
widths and `only`. `decorative` (landing) reads only the widths and emits no role/label.
{% endcomment %}
<div class="glance">
  <div class="glance__row">
    <span class="glance__label" aria-hidden="true">{% trans "Progress" context "course glance" %}</span>
    <div class="glance__track"{% if not decorative %} role="img" aria-label="{% if progress_total == 0 %}{% trans "Progress: no lessons to track" context "course glance" %}{% else %}{% blocktrans with done=progress_done count counter=progress_total context "course glance" %}Progress: {{ done }} of {{ counter }} lesson{% plural %}Progress: {{ done }} of {{ counter }} lessons{% endblocktrans %}{% endif %}"{% endif %}>{% if progress_width is None %}{% elif progress_width == 0 %}<span class="glance__dot"></span>{% else %}<span class="glance__fill" style="width: {{ progress_width }}%"></span>{% endif %}</div>
  </div>
  <div class="glance__row">
    <span class="glance__label" aria-hidden="true">{% trans "Results" context "course glance" %}</span>
    <div class="glance__track"{% if not decorative %} role="img" aria-label="{% if results_pct is None %}{% trans "Results: no scores yet" context "course glance" %}{% else %}{% blocktrans with pct=results_pct context "course glance" %}Results: {{ pct }}%{% endblocktrans %}{% endif %}"{% endif %}>{% if results_width is None %}{% elif results_width == 0 %}<span class="glance__dot"></span>{% else %}<span class="glance__fill" style="width: {{ results_width }}%"></span>{% endif %}</div>
  </div>
</div>
```

- [ ] **Step 4: Add the CSS** — in `core/static/core/css/app.css`, directly after the line `.dash-card__actions a:hover { text-decoration: underline; }`, insert:

```css

/* Course glance bars (templates/courses/_course_glance.html). The track is
   deliberately light (owner decision D9); the fill carries the information. */
.glance { display: grid; grid-template-columns: max-content 1fr; align-items: center;
  column-gap: var(--space-2); row-gap: var(--space-1); margin-top: var(--space-1); }
.glance__row { display: contents; }
.glance__label { font-size: .75rem; color: var(--text-secondary); white-space: nowrap; }
.glance__track { display: flex; height: 6px; border-radius: 999px; overflow: hidden;
  background: var(--border-subtle); }
.glance__fill, .glance__dot { display: block; height: 6px; border-radius: 999px;
  background: var(--accent); }
.glance__fill { min-width: 6px; }
.glance__dot { width: 6px; flex: none; }
@media (forced-colors: active) {
  .glance__track { background: transparent; border: 1px solid CanvasText; }
  .glance__fill, .glance__dot { forced-color-adjust: none; background: Highlight; }
}
```

- [ ] **Step 5: Catalog** — run `uv run python manage.py makemessages -l pl -l en --no-obsolete`. In `locale/pl/LC_MESSAGES/django.po` fill these entries (search by msgid; clear any `#, fuzzy` flag and its `#| msgid` line):

```po
msgctxt "course glance"
msgid "Progress"
msgstr "Postęp"

msgctxt "course glance"
msgid "Results"
msgstr "Wyniki"

msgctxt "course glance"
msgid "Progress: no lessons to track"
msgstr "Postęp: brak lekcji obowiązkowych"

msgctxt "course glance"
msgid "Progress: %(done)s of %(counter)s lesson"
msgid_plural "Progress: %(done)s of %(counter)s lessons"
msgstr[0] "Postęp: %(done)s z %(counter)s lekcji"
msgstr[1] "Postęp: %(done)s z %(counter)s lekcji"
msgstr[2] "Postęp: %(done)s z %(counter)s lekcji"

msgctxt "course glance"
msgid "Results: no scores yet"
msgstr "Wyniki: jeszcze brak punktów"

msgctxt "course glance"
msgid "Results: %(pct)s%%"
msgstr "Wyniki: %(pct)s%%"
```

(Polish "z N lekcji" takes the genitive, identical for every form — that is correct, not a shortcut.) The `en` catalog entries stay with empty `msgstr` (English falls back to the msgid). Then run `uv run python manage.py compilemessages`.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_course_glance_render.py tests/test_course_glance.py`
Then the catalog-hygiene test: `uv run pytest tests/test_i18n_po_health.py` (never a `-k` sweep over the whole `tests/` tree — the full collection is heavy), and the stylesheet guards for the `app.css` edit: `uv run pytest tests/test_css_comments_are_terminated_once.py tests/test_css_citations_are_durable.py tests/test_print_tokens_css.py`.
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
uv run ruff format tests/test_course_glance_render.py
uv run ruff check --no-cache tests/test_course_glance_render.py
uv run ruff format --check tests/test_course_glance_render.py
git add templates/courses/_course_glance.html core/static/core/css/app.css locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_course_glance_render.py
git commit -m "feat(glance): two-bar partial, styles and Polish strings"
```

---

### Task 4: Wire My courses and the dashboard

**Files:**
- Create: `courses/glance.py`
- Modify: `courses/views.py` (`my_courses`, ~line 648), `templates/courses/my_courses.html`
- Modify: `core/views.py` (`home`, ~line 26), `templates/core/home.html`
- Test: `tests/test_course_glance_render.py` (append)

**Interfaces:**
- Consumes: `course_glance_or_unknown(course, user, *, drafts)` (Task 2); the partial (Task 3); `courses.access.can_see_drafts(user, course)`.
- Produces: `courses.glance.enrolled_course_glances(user) -> list[tuple[Course, dict]]`, ordered by course title. Context keys unchanged: `courses` (my_courses) and `enrolled_courses` (home), now lists of pairs.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_course_glance_render.py`:

```python
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from courses.models import Element
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UnitProgressFactory
from tests.factories import make_login
from tests.test_course_glance import _shaped_course

PAGES = [reverse("home"), reverse("courses:my_courses")]


def _glance_for(soup, title):
    """The .glance that follows the course title link on either page."""
    link = soup.find("a", string=title)
    assert link is not None, f"{title} not listed"
    return link.find_next(class_="glance")


def _student_with_two_courses(client):
    student = make_login(client, "glance_student")
    started = CourseFactory(title="Started Course")
    EnrollmentFactory(student=student, course=started)
    done = ContentNodeFactory(course=started, kind="unit", unit_type="lesson",
                              parent=None, obligatory=True)
    ContentNodeFactory(course=started, kind="unit", unit_type="lesson",
                       parent=None, obligatory=True)
    UnitProgressFactory(student=student, unit=done, completed=True)
    quiz = ContentNodeFactory(course=started, kind="unit", unit_type="quiz", parent=None)
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode="A", max_marks=Decimal("10"))
    Element.objects.create(unit=quiz, content_object=q)
    QuizSubmissionFactory(student=student, unit=quiz, status="submitted",
                          score=Decimal("0"), max_score=Decimal("10"))
    untouched = CourseFactory(title="Untouched Course")
    EnrollmentFactory(student=student, course=untouched)
    ContentNodeFactory(course=untouched, kind="unit", unit_type="lesson",
                       parent=None, obligatory=True)
    return student


@pytest.mark.django_db
@pytest.mark.parametrize("url", PAGES)
def test_pages_render_each_state(client, url):
    _student_with_two_courses(client)
    resp = client.get(url)
    assert resp.status_code == 200
    soup = BeautifulSoup(resp.content, "html.parser")

    started = _glance_for(soup, "Started Course")
    p_track, r_track = started.select(".glance__track")
    assert p_track.select_one(".glance__fill")["style"] == "width: 50%"
    assert r_track.select(".glance__dot") and not r_track.select(".glance__fill")
    assert r_track["aria-label"] == "Results: 0%"

    untouched = _glance_for(soup, "Untouched Course")
    p_track, r_track = untouched.select(".glance__track")
    assert not p_track.select(".glance__fill") and not p_track.select(".glance__dot")
    assert p_track["aria-label"] == "Progress: 0 of 1 lesson"
    assert not r_track.select(".glance__fill") and not r_track.select(".glance__dot")
    assert not re.search(r"\d", started.get_text() + untouched.get_text())


@pytest.mark.django_db
@pytest.mark.parametrize("url", PAGES)
def test_one_broken_course_does_not_break_the_page(client, url, monkeypatch, caplog):
    import courses.rollups as rollups

    _student_with_two_courses(client)
    real = rollups.course_glance

    def flaky(course, user, *, drafts):
        if course.title == "Untouched Course":
            raise RuntimeError("inconsistent tree")
        return real(course, user, drafts=drafts)

    monkeypatch.setattr(rollups, "course_glance", flaky)
    with caplog.at_level("ERROR", logger="courses.rollups"):
        resp = client.get(url)
    assert resp.status_code == 200
    soup = BeautifulSoup(resp.content, "html.parser")
    assert _glance_for(soup, "Started Course").select(".glance__fill")
    broken = _glance_for(soup, "Untouched Course").select(".glance__track")
    assert broken[0]["aria-label"] == "Progress: no lessons to track"
    assert "inconsistent tree" in caplog.text


@pytest.mark.django_db
def test_teaching_and_studio_panels_have_no_glance(client):
    # The user teaches one course, owns another, AND is enrolled in a third, so a
    # glance DOES render (in My learning) -- the guard is not vacuous.
    teacher = make_login(client, "glance_teacher")
    taught = CourseFactory(title="Taught Course")
    GroupFactory(course=taught).teachers.add(teacher)
    CourseFactory(title="Owned Course", owner=teacher)
    EnrollmentFactory(student=teacher, course=CourseFactory(title="Learned Course"))
    soup = BeautifulSoup(client.get(reverse("home")).content, "html.parser")
    learning = soup.select_one('[data-section="learning"]')
    teaching = soup.select_one('[data-section="teaching"]')
    studio = soup.select_one('[data-section="manage"]')
    assert learning.select(".glance")
    assert teaching.find("a", string="Taught Course")  # panel content unchanged
    assert not teaching.select(".glance")
    assert studio.find("a", string="Owned Course")
    assert not studio.select(".glance")


@pytest.mark.django_db
@pytest.mark.parametrize("url", PAGES)
def test_view_query_cost_is_linear_in_courses(client, url):
    student = make_login(client, "glance_queries")
    counts = {}
    for n in (1, 2, 3):
        EnrollmentFactory(student=student, course=_shaped_course(student, 2))
        client.get(url)  # warm caches for this N
        with CaptureQueriesContext(connection) as ctx:
            assert client.get(url).status_code == 200
        counts[n] = len(ctx)
    assert counts[3] - counts[2] == counts[2] - counts[1]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_course_glance_render.py`
Expected: `test_pages_render_each_state`, `test_one_broken_course_does_not_break_the_page` and `test_teaching_and_studio_panels_have_no_glance` FAIL (no `.glance` in the pages yet). `test_view_query_cost_is_linear_in_courses` is a regression guard and PASSES already (zero per-course cost is trivially linear) — that is expected.

- [ ] **Step 3: Create `courses/glance.py`**:

```python
"""(course, glance) pairs for the dashboard's "My learning" and My courses.

Lives outside courses.rollups on purpose: rollups imports no access-layer code, and
choosing `drafts` needs can_see_drafts.
"""

from courses.access import can_see_drafts
from courses.models import Course
from courses.rollups import course_glance_or_unknown


def enrolled_course_glances(user):
    """Every course `user` is enrolled in, by title, paired with its glance.

    drafts is chosen exactly as course_outline / course_results choose it, so the
    bars, the outline and My results never disagree.
    """
    courses = Course.objects.filter(enrollments__student=user).order_by("title")
    return [
        (
            course,
            course_glance_or_unknown(
                course,
                user,
                drafts="keep" if can_see_drafts(user, course) else "hide",
            ),
        )
        for course in courses
    ]
```

- [ ] **Step 4: Wire `my_courses`** — in `courses/views.py` replace:

```python
@login_required
def my_courses(request):
    courses = Course.objects.filter(enrollments__student=request.user).order_by("title")
    return render(request, "courses/my_courses.html", {"courses": courses})
```

with:

```python
@login_required
def my_courses(request):
    from courses.glance import enrolled_course_glances

    return render(
        request,
        "courses/my_courses.html",
        {"courses": enrolled_course_glances(request.user)},
    )
```

(If `Course` is now unused in `courses/views.py`, ruff F401 will say so — it is used elsewhere there, so expect no change to imports.)

In `templates/courses/my_courses.html` replace the loop body:

```django
      {% for course in courses %}
        <li class="dash-card">
          <a class="dash-card__title" href="{% url 'courses:course_outline' slug=course.slug %}">{{ course.title }}</a>
          <span class="dash-card__actions">
```

with:

```django
      {% for course, glance in courses %}
        <li class="dash-card">
          <a class="dash-card__title" href="{% url 'courses:course_outline' slug=course.slug %}">{{ course.title }}</a>
          {% include "courses/_course_glance.html" with progress_width=glance.progress_width results_width=glance.results_width progress_done=glance.progress_done progress_total=glance.progress_total results_pct=glance.results_pct only %}
          <span class="dash-card__actions">
```

- [ ] **Step 5: Wire `home`** — in `core/views.py` `home`, replace:

```python
    enrolled_courses = Course.objects.filter(
        enrollments__student=request.user
    ).order_by("title")
```

and fold the new import into the existing local import so the block stays sorted (ruff I001) — the result reads:

```python
    from courses.glance import enrolled_course_glances
    from courses.models import Course

    enrolled_courses = enrolled_course_glances(request.user)
```

(`Course` is still used further down in `home` for `taught_courses` / `owned_courses`.)

In `templates/core/home.html` replace:

```django
    {% for course in enrolled_courses %}
    <li><a href="{% url 'courses:course_outline' slug=course.slug %}">{{ course.title }}</a></li>
    {% endfor %}
```

with:

```django
    {% for course, glance in enrolled_courses %}
    <li><a href="{% url 'courses:course_outline' slug=course.slug %}">{{ course.title }}</a>
      {% include "courses/_course_glance.html" with progress_width=glance.progress_width results_width=glance.results_width progress_done=glance.progress_done progress_total=glance.progress_total results_pct=glance.results_pct only %}
    </li>
    {% endfor %}
```

- [ ] **Step 5b: Re-point shifted line citations**

The `my_courses` and `home` edits change line counts in `courses/views.py` and `core/views.py`. FIRST run `uv run ruff format courses/views.py core/views.py` so formatting cannot shift lines again after you fix them. Then run `grep -rnE "(courses|core)/views\.py:[0-9]" --include=*.py --include=*.html --include=*.css . | grep -v '/.venv/'`. For every citation whose cited line lies BELOW the edited function, open the file, find the code the comment describes, and update the number to where it now sits (a citation that was already stale before this task: point it at the right line too, or leave it and note it — never make it worse).

- [ ] **Step 6: Run the new tests, then the scoped regression set**

Run: `uv run pytest tests/test_course_glance_render.py tests/test_course_glance.py`
Expected: PASS.

Then build the regression list and run it in one process:

```bash
grep -rlE 'reverse\("home"\)|my_courses|landing|"/home/"|"/courses/"' . --include='test_*.py' | grep -v test_e2e_ | grep -v '/.venv/' | sort -u > /tmp/glance_regress.txt
uv run pytest tests/test_consumption_pages.py tests/test_courses_views.py tests/test_surfaces.py tests/test_help.py tests/test_subject_admin_views.py tests/test_dashboard_panels.py tests/test_nav_structure.py tests/test_grouping_course_links.py tests/test_auth_login.py tests/test_ui_foundation.py $(cat /tmp/glance_regress.txt)
```

Expected: summary line shows 0 failed, 0 errors.

- [ ] **Step 7: Commit**

```bash
uv run ruff format courses/glance.py courses/views.py core/views.py tests/test_course_glance_render.py
uv run ruff check --no-cache courses/glance.py courses/views.py core/views.py tests/test_course_glance_render.py
uv run ruff format --check courses/glance.py courses/views.py core/views.py tests/test_course_glance_render.py
git add courses/glance.py courses/views.py core/views.py templates/courses/my_courses.html templates/core/home.html tests/test_course_glance_render.py
# plus, by explicit path, every file whose citation Step 5b re-pointed (e.g. demo/generator.py)
git commit -m "feat(glance): bars on My courses and the dashboard"
```

---

### Task 5: Landing page sample cards

**Files:**
- Modify: `templates/core/landing.html:20-24`
- Modify: `core/static/core/css/app.css` (remove the `.landing-visual .card { … }` rule ~line 326; add `.glance-card` rules to the glance block from Task 3)
- Modify: `locale/{en,pl}/LC_MESSAGES/django.{po,mo}`
- Test: `tests/test_course_glance_render.py` (append)

**Interfaces:**
- Consumes: the partial with `decorative=True` (Task 3).

- [ ] **Step 1: Write the failing tests** — append:

```python
def _landing(client, lang):
    from core.middleware import LANGUAGE_SESSION_KEY

    session = client.session
    session[LANGUAGE_SESSION_KEY] = lang
    session.save()
    resp = client.get("/")
    assert resp.status_code == 200
    return resp


def _cards(resp):
    soup = BeautifulSoup(resp.content, "html.parser")
    visual = soup.select_one(".landing-visual")
    assert visual is not None and visual["aria-hidden"] == "true"
    return visual, {
        c.select_one(".glance-card__title").get_text(strip=True): c
        for c in visual.select(".glance-card")
    }


@pytest.mark.django_db
def test_landing_polish_titles_and_states(client):
    resp = _landing(client, "pl")
    visual, cards = _cards(resp)
    assert list(cards) == ["Hiszpański A2", "Matematyka", "Biologia"]
    assert not visual.select("a") and not visual.select('[role="img"]')
    assert not visual.select(".dash-card")

    def widths(card):
        return [f["style"] for f in card.select(".glance__fill")]

    assert widths(cards["Hiszpański A2"]) == ["width: 70%", "width: 85%"]
    assert widths(cards["Matematyka"]) == ["width: 20%", "width: 55%"]
    biology = cards["Biologia"]
    assert widths(biology) == ["width: 5%"]
    results_track = biology.select(".glance__track")[1]
    assert not results_track.select(".glance__fill, .glance__dot")
    assert "width: %" not in resp.content.decode()


@pytest.mark.django_db
def test_landing_english_titles(client):
    _visual, cards = _cards(_landing(client, "en"))
    assert list(cards) == ["Spanish A2", "Mathematics", "Biology"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_course_glance_render.py -k landing`
Expected: FAIL (no `.glance-card`).

- [ ] **Step 3: Replace the landing boxes** — in `templates/core/landing.html` replace:

```django
  <div class="landing-visual" aria-hidden="true">
    <div class="card">Hiszpański A2 · 62%</div>
    <div class="card">Matematyka · 30%</div>
    <div class="card">Biology · 88%</div>
  </div>
```

with:

```django
  <div class="landing-visual" aria-hidden="true">
    <div class="glance-card">
      <p class="glance-card__title">{% trans "Spanish A2" context "course glance" %}</p>
      {% include "courses/_course_glance.html" with progress_width=70 results_width=85 decorative=True only %}
    </div>
    <div class="glance-card">
      <p class="glance-card__title">{% trans "Mathematics" context "course glance" %}</p>
      {% include "courses/_course_glance.html" with progress_width=20 results_width=55 decorative=True only %}
    </div>
    <div class="glance-card">
      <p class="glance-card__title">{% trans "Biology" context "course glance" %}</p>
      {% include "courses/_course_glance.html" with progress_width=5 results_width=None decorative=True only %}
    </div>
  </div>
```

- [ ] **Step 4: CSS** — in `core/static/core/css/app.css` delete the whole rule:

```css
.landing-visual .card {
  max-width: 12rem; margin: 0; font-size: .875rem;
  color: var(--text-secondary); text-align: center;
}
```

(first `grep -rn "landing-visual" templates` to confirm nothing else uses it). Then, directly before the `@media (forced-colors: active)` block added in Task 3, add:

```css
/* Landing sample cards: look like a .dash-card at rest, but static (no hover lift,
   not a link) -- they advertise, they do not navigate. */
.glance-card { width: 14rem; margin: 0; padding: var(--space-4); text-align: left;
  background: var(--surface-raised); border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg); box-shadow: var(--shadow-sm); }
.glance-card__title { margin: 0; font-size: .95rem; font-weight: 600;
  color: var(--text-primary); }
```

- [ ] **Step 5: Catalog** — `uv run python manage.py makemessages -l pl -l en --no-obsolete`, then in the pl `.po`:

```po
msgctxt "course glance"
msgid "Spanish A2"
msgstr "Hiszpański A2"

msgctxt "course glance"
msgid "Mathematics"
msgstr "Matematyka"

msgctxt "course glance"
msgid "Biology"
msgstr "Biologia"
```

Clear any fuzzy flags + `#|` lines, then `uv run python manage.py compilemessages`.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_course_glance_render.py tests/test_for_schools_footer.py tests/test_for_schools_page.py`
Expected: PASS. Then `uv run pytest tests/test_i18n_po_health.py tests/test_css_comments_are_terminated_once.py tests/test_css_citations_are_durable.py tests/test_print_tokens_css.py` (catalog hygiene + stylesheet guards for this task's `app.css` edit).

- [ ] **Step 7: Commit**

```bash
uv run ruff format tests/test_course_glance_render.py
uv run ruff check --no-cache tests/test_course_glance_render.py
uv run ruff format --check tests/test_course_glance_render.py
git add templates/core/landing.html core/static/core/css/app.css locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_course_glance_render.py
git commit -m "feat(glance): translated sample cards on the landing page"
```

---

### Task 6: Screenshots, contrast, timing and falsification

**Files:**
- Create: `tests/capture_glance_screenshots.py` (e2e, not auto-collected: filename not `test_`-prefixed)
- Output (gitignored): `.superpowers/shots/glance-*.png`, `.superpowers/shots/glance-verification.md`

**Interfaces:**
- Consumes: everything above. Produces the verification notes the PR body quotes.

- [ ] **Step 1: Write the capture script** `tests/capture_glance_screenshots.py`:

```python
"""Light + dark + forced-colors capture of the course glance bars, plus measured
contrast. Verification tool, not CI:

    uv run pytest tests/capture_glance_screenshots.py -m e2e

Dark for a logged-in user is set through User.theme (a cookie is ignored for an
authenticated user); the anonymous landing uses the libli_theme cookie.
Output: SHOT_DIR or ./.superpowers/shots/ (gitignored).
"""

import os
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings

from courses.models import Element
from courses.models import ShortTextQuestionElement
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UnitProgressFactory
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

OUT_DIR = Path(
    os.environ.get("SHOT_DIR", Path(settings.BASE_DIR) / ".superpowers" / "shots")
)

# Colours are normalised through a 1x1 canvas: dark --accent is a color-mix(), which
# Chromium reports as `color(srgb 0.87 0.69 0.51)` (0..1 channels), so a regex over
# the computed string would read it as near-black. The raw strings are returned too,
# so a normalisation failure is visible in the notes.
CONTRAST_JS = """
() => {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d', {willReadFrequently: true});
  const toRgb = css => {
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = '#000';
    ctx.fillStyle = css;
    ctx.fillRect(0, 0, 1, 1);
    return Array.from(ctx.getImageData(0, 0, 1, 1).data).slice(0, 3);
  };
  const lum = ([r, g, b]) => {
    const f = c => {
      c /= 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a, b) => {
    const [x, y] = [lum(toRgb(a)), lum(toRgb(b))].sort((p, q) => q - p);
    return ((x + 0.05) / (y + 0.05)).toFixed(2);
  };
  const bg = el => getComputedStyle(el).backgroundColor;
  const fill = document.querySelector('.glance__fill, .glance__dot');
  const track = fill.closest('.glance__track');
  // The surface is the nearest ANCESTOR of the track with a painted background
  // (.dash-card / .dash-panel / .glance-card / body) -- never the track itself.
  let surface = track.parentElement;
  while (surface && bg(surface) === 'rgba(0, 0, 0, 0)') surface = surface.parentElement;
  return {
    raw: {fill: bg(fill), track: bg(track), surface: bg(surface)},
    surface_el: surface.className || surface.tagName,
    fill_vs_track: ratio(bg(fill), bg(track)),
    fill_vs_surface: ratio(bg(fill), bg(surface)),
    track_vs_surface: ratio(bg(track), bg(surface)),
  };
}
"""


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_url(f"{live_server.url}/home/")


def _seed(student):
    """Four courses covering partial fill, zero-dot, track-only and full."""
    full = CourseFactory(title="Biology Basics")
    EnrollmentFactory(student=student, course=full)
    lesson = ContentNodeFactory(course=full, kind="unit", unit_type="lesson",
                                parent=None, obligatory=True)
    UnitProgressFactory(student=student, unit=lesson, completed=True)
    quiz = ContentNodeFactory(course=full, kind="unit", unit_type="quiz", parent=None)
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode="A", max_marks=Decimal("4"))
    Element.objects.create(unit=quiz, content_object=q)
    QuizSubmissionFactory(student=student, unit=quiz, status="submitted",
                          score=Decimal("4"), max_score=Decimal("4"))

    started = CourseFactory(title="Algebra Basics")
    EnrollmentFactory(student=student, course=started)
    lessons = [
        ContentNodeFactory(course=started, kind="unit", unit_type="lesson",
                           parent=None, obligatory=True)
        for _ in range(3)
    ]
    UnitProgressFactory(student=student, unit=lessons[0], completed=True)
    quiz = ContentNodeFactory(course=started, kind="unit", unit_type="quiz", parent=None)
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode="A", max_marks=Decimal("10"))
    Element.objects.create(unit=quiz, content_object=q)
    QuizSubmissionFactory(student=student, unit=quiz, status="submitted",
                          score=Decimal("7"), max_score=Decimal("10"))

    zero = CourseFactory(title="Chemistry Intro")
    EnrollmentFactory(student=student, course=zero)
    quiz = ContentNodeFactory(course=zero, kind="unit", unit_type="quiz", parent=None)
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode="A", max_marks=Decimal("5"))
    Element.objects.create(unit=quiz, content_object=q)
    QuizSubmissionFactory(student=student, unit=quiz, status="submitted",
                          score=Decimal("0"), max_score=Decimal("5"))

    untouched = CourseFactory(title="History Survey")
    EnrollmentFactory(student=student, course=untouched)
    ContentNodeFactory(course=untouched, kind="unit", unit_type="lesson",
                       parent=None, obligatory=True)


def test_capture(page, live_server):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    notes = ["# Course glance verification", ""]
    student = make_verified_user(
        username="glanceshots", email="glanceshots@t.example.com",
        password=TEST_PASSWORD)
    _seed(student)

    for theme in ("light", "dark"):
        student.theme = theme
        student.save(update_fields=["theme"])
        _login(page, live_server, "glanceshots")
        for name, path in (("dashboard", "/home/"), ("mycourses", "/courses/")):
            page.goto(f"{live_server.url}{path}")
            page.screenshot(path=str(OUT_DIR / f"glance-{name}-{theme}.png"), full_page=True)
            notes.append(f"- {name} {theme}: {page.evaluate(CONTRAST_JS)}")
        page.context.clear_cookies()

    for theme in ("light", "dark"):
        page.context.add_cookies([{"name": "libli_theme", "value": theme,
                                   "url": live_server.url}])
        page.goto(f"{live_server.url}/")
        page.screenshot(path=str(OUT_DIR / f"glance-landing-{theme}.png"), full_page=True)
        notes.append(f"- landing {theme}: {page.evaluate(CONTRAST_JS)}")

    # Polish dashboard: labels must neither wrap nor clip.
    student.theme = "light"
    student.language = "pl"
    student.save(update_fields=["theme", "language"])
    page.context.clear_cookies()
    _login(page, live_server, "glanceshots")
    page.goto(f"{live_server.url}/home/")
    page.screenshot(path=str(OUT_DIR / "glance-dashboard-pl.png"), full_page=True)
    page.context.clear_cookies()

    page.emulate_media(forced_colors="active")
    page.goto(f"{live_server.url}/")
    page.screenshot(path=str(OUT_DIR / "glance-landing-forced-colors.png"), full_page=True)
    # The dashboard has the zero-dot and empty tracks the landing lacks.
    _login(page, live_server, "glanceshots")
    page.screenshot(path=str(OUT_DIR / "glance-dashboard-forced-colors.png"), full_page=True)
    notes.append(
        "- Measured palette: the DEFAULT brand accent only; an install with a custom "
        "--brand-accent (core/templatetags/branding.py) is not covered."
    )

    (OUT_DIR / "glance-verification.md").write_text("\n".join(notes) + "\n", encoding="utf-8")
```

- [ ] **Step 2: Run the capture and LOOK at every image**

Run: `uv run pytest tests/capture_glance_screenshots.py -m e2e`
Open each `.superpowers/shots/glance-*.png` with the Read tool. Judge light and dark separately. Check: a fill is visibly drawn (not empty bars); the zero-dot is visible; an empty track reads as an empty bar, not as nothing; labels do not wrap or clip; both tracks start at the same x, including in the narrow dashboard "My learning" panel; landing cards have no hover lift; forced-colors shows the fill.
From `glance-verification.md`: every `fill_vs_track` and `fill_vs_surface` must be ≥ 3.00. If one is short, introduce a `--glance-fill` token and have `.glance__fill, .glance__dot` use `background: var(--glance-fill)`. Define it in `core/static/core/css/tokens.css`: in `:root` (`--glance-fill: var(--accent);`, or a darkened `color-mix(in srgb, var(--accent) 80%, black)` if LIGHT fell short) and in the `[data-theme="dark"]` block (~line 92) — the darkened value if DARK fell short, otherwise `--glance-fill: var(--accent);` whenever `:root` got a darkened value (without it, a light-only fix would also darken the dark theme's fill against dark surfaces). (Auto-theme users are covered by that block: `templates/base.html` sets `data-theme="dark"` from `matchMedia` in JS; there is no separate `prefers-color-scheme` token block.) If you add it to the dark block, you MUST also restate it with the `:root` value inside the `@media print { [data-theme="dark"] { … } }` block (~line 137-143) — that block puts the light palette back for printing, and `tests/test_print_tokens_css.py` fails if a dark token is not restated there. Then run `uv run pytest tests/test_print_tokens_css.py tests/test_css_comments_are_terminated_once.py tests/test_css_citations_are_durable.py`. Re-run the capture, re-check. Record `track_vs_surface` but do not change the track to reach 3:1 (owner decision D9: the track stays light). If `--border-subtle` makes the empty track invisible, switch the track to `--border-default` or `--border-strong` (still light).
In `glance-dashboard-pl.png` confirm the Polish labels do not wrap or clip. For every notes line, check `raw` holds sensible colours and `surface_el` names a card/panel (not `glance__track`); if not, the measurement is broken — fix the script before trusting any ratio.

- [ ] **Step 3: Timing**

First confirm "before" really is master: `git -C C:/Users/krzys/Documents/Python/own/libli rev-parse --abbrev-ref HEAD` must print `master` and `git -C C:/Users/krzys/Documents/Python/own/libli status --short` must be empty; record `git -C … rev-parse --short HEAD` next to the "before" medians (if either check fails, note it and do not present the numbers as master). With the dev server data (`uv run python manage.py runserver`) and a student enrolled in the largest local course plus several others, time `/home/` and `/courses/` five times each on `master` (`git stash` is NOT allowed — use the main repo checkout at `C:/Users/krzys/Documents/Python/own/libli` for "before", this worktree for "after"), e.g. `curl -s -o /dev/null -w "%{http_code} %{time_total}\n" -b "sessionid=<id>" http://127.0.0.1:8000/home/`. EVERY sample must print `200`; a fast 302 (rejected session, verification redirect, the Platform-Admin setup-wizard redirect in `home`) times a redirect, not the page — discard it and fix the cause. The timed user must be a plain student (no `institution.change_institution` permission). Get `<id>` by creating a session for the student in `uv run python manage.py shell`: `from django.contrib.sessions.backends.db import SessionStore; from django.contrib.auth import get_user_model, SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY; u = get_user_model().objects.get(username="<name>"); s = SessionStore(); s[SESSION_KEY] = str(u.pk); s[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"; s[HASH_SESSION_KEY] = u.get_session_auth_hash(); s.create(); print(s.session_key)` (both servers share the dev DB, so one session works for before and after; run them one at a time on port 8000). Append the before/after medians to `.superpowers/shots/glance-verification.md`. If the dev DB has no such student, say so in the notes rather than inventing numbers.

- [ ] **Step 4: Falsification — each mutant must turn at least one test RED**

For each mutant: edit the code BY HAND, run `git diff` and READ it to confirm the mutant is really applied, run `uv run pytest tests/test_course_glance.py tests/test_course_glance_render.py`, record which test failed, then revert BY HAND (never `git checkout`/`git restore` — that has destroyed uncommitted work before) and confirm `git diff` is empty.

1. `_results_width`: `return None` → `return 0` in the `percent is None` branch.
2. Partial: delete both `{% elif … == 0 %}<span class="glance__dot"></span>` branches.
3. `course_glance`: replace `summary["percent"]` with the mean of per-row `score_view["percent"]` values.
4. `_results_width`: branch on `percent == 0` instead of `score == 0`.
5. `_clamp_partial`: `min(max(value, 1), 99)` → `max(value, 1)`.
6. Partial: add `{{ results_pct }}` inside the results `.glance__label`.
7. `_results_width`: move the `if score == 0: return 0` check above `if percent is None`.
8. `_progress_width`: return `0` instead of `None` when `done <= 0` and `total > 0`.

Append the mutant → failing-test table to `.superpowers/shots/glance-verification.md`. Any mutant that stays GREEN: add the missing assertion to the right test file, commit it, and re-run that mutant.

- [ ] **Step 5: Commit the capture script (and any test added in Step 4)**

```bash
uv run ruff format tests/capture_glance_screenshots.py
uv run ruff check --no-cache tests/capture_glance_screenshots.py
uv run ruff format --check tests/capture_glance_screenshots.py
git add tests/capture_glance_screenshots.py
git commit -m "test(glance): screenshot, contrast and verification capture"
```

(Commit CSS tweaks from Step 2 separately: `git add core/static/core/css/app.css core/static/core/css/tokens.css` — tokens.css whenever `--glance-fill` was introduced, or the fill ships with an undefined token and renders EMPTY while every DOM test stays green — with a `fix(glance): …` message. Afterwards `git status --short` must show no modified tracked files.)
