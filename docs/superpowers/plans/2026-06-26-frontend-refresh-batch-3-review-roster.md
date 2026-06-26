# Frontend Refresh Batch 3 — Quiz-Review Roster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the teacher quiz-review page (`review_submission.html`) a collapsible left roster of every sibling submission for the same quiz unit (grouped To review / In progress / Reviewed), Prev / "Next to review" footer navigation, and a "Force-submit all" action — reusing batch-2's `.unit-shell` CSS.

**Architecture:** A new pure service `roster_for_unit(reviewer, submission)` in `courses/review.py` materializes every in-scope submission for the unit, groups them with a predicate shared with `pending_reviews_for`, and returns one flat, stably-sorted sequence (groups are display-only). A pure `roster_neighbours()` derives Prev / Next-to-review from that flat sequence. The view passes both into a restructured `.unit-shell` template. A new per-unit `force_submit_all` endpoint re-queries the in-progress set server-side and reuses the existing race-safe `force_submit_quiz`. The individual `force_submit` redirect becomes context-dependent via a hidden `review_pk` field.

**Tech Stack:** Django (server-rendered templates, no SPA), vanilla JS (progressive enhancement, no framework), bespoke token-driven CSS, pytest + Playwright (`-m e2e`).

## Global Constraints

- **TDD always** — write the failing test, watch it fail, minimal code, watch it pass, commit. (per project norms)
- **Tooling:** bash `ruff`/`pytest`/`python` are **NOT on PATH** — use `uv run ruff …`, `uv run pytest …`, `uv run python manage.py …`.
- **Lint:** every task ends green on `uv run ruff check .` AND `uv run ruff format --check .` (CI checks format too).
- **i18n:** every new visible string is wrapped in `{% trans %}` / `gettext`, and gets a **Polish** translation in `locale/pl/LC_MESSAGES/django.po`; recompile `.mo` (`uv run python manage.py compilemessages`). Watch the makemessages **fuzzy-flag** gotcha — new msgids can be mis-matched to an existing pl string and flagged `#, fuzzy` (ignored at runtime); always grep the new msgids and clear stale `#, fuzzy` / drop `#~` obsolete (a `test_po_catalog_clean` test enforces this).
- **CSS reuse:** the roster reuses batch-2's `.unit-shell` two-column shell (already on master in `courses/static/courses/css/courses.css`). Do **not** fork a parallel shell.
- **Run e2e before pushing:** local `uv run pytest -q` EXCLUDES e2e; CI runs `-m e2e`. Always run `uv run pytest -m e2e` for any template/markup change.
- **Scope/security:** all roster + force-submit paths gate on `scoping.reviewable_students` / `scoping.can_review_course`; no new IDOR surface. Force-submit-all is the only new mutating behaviour — `@require_POST` + confirm + server re-query.

**Reference docs:** spec `docs/superpowers/specs/2026-06-25-frontend-design-refresh-and-navigation-design.md` §4 (feature), §8 (tests), §9 (risks); accepted mockup `docs/mockups/quiz-review-roster.html`.

**Existing symbols this plan builds on (verbatim, do not rename):**
- `courses/review.py`: `submission_review_state(submission) -> dict{total,reviewed,remaining,fully_reviewed}`, `_review_element_ids(unit)`, `force_submit_quiz(submission, *, by)`, `pending_reviews_for(user, course)`.
- `courses/views_review.py`: `_resolve_for_review(request, slug, submission_pk) -> (course, submission)`, `_review_context(course, submission) -> dict`, `review_submission`, `force_submit`, `review_queue`.
- `grouping/scoping.py`: `reviewable_students(user, course) -> QuerySet[User]`, `can_review_course(user, course) -> bool`.
- `courses/models.py`: `QuizSubmission.Status.{IN_PROGRESS,SUBMITTED}`, `QuizSubmission.student`/`.unit`/`.status`/`.responses` (related name), `QuestionElement.MarkingMode.REVIEW`, `QuestionElement.max_marks`, `QuestionResponse.{element_id,earned_marks,reviewed_at}`.
- URL names: `courses:manage_review_submission` (kwargs slug, submission_pk), `courses:manage_review_queue` (slug), `courses:manage_review_force_submit` (slug, submission_pk).
- Test helpers (`tests/`): `make_pa(client)` (creates+logs-in a platform admin reviewer), `make_login(client, ...)`, `CourseFactory(owner=…)`, `ContentNodeFactory(course=, kind="unit", unit_type="quiz")`, `UserFactory()`, `EnrollmentFactory(student=, course=)`, `QuizSubmissionFactory`, `QuestionResponseFactory`. The `_review_quiz(course)` and `_review_q(unit, *, max_marks)` / `_auto_q(unit, *, max_marks)` helper shapes in `tests/test_review_views.py` / `tests/test_review_services.py`.

---

## File Structure

**Modified:**
- `courses/review.py` — add `_awaiting_review(state)` predicate (refactor `pending_reviews_for` to use it), `roster_for_unit(reviewer, submission)`, `roster_neighbours(roster, current_submission)`.
- `courses/views_review.py` — split `_resolve_submission` out of `_resolve_for_review` + add SUBMITTED guard; add `_redirect_after_force(request, course)`; make individual `force_submit` use it; add `force_submit_all`; wire roster + neighbours + counts into `review_submission` context.
- `courses/urls.py` — add the `force_submit_all` per-unit route.
- `templates/courses/manage/review_submission.html` — restructure into `.unit-shell` with a left roster rail + right main + footer + force-all button.
- `templates/courses/manage/_roster_row.html` — **new** partial: one roster row (student name + group-specific marks / force-submit), included once per group by `review_submission.html`.
- `templates/base.html` — add a `{% block prepaint %}{% endblock %}` slot before the CSS links (so the roster collapse can restore pre-paint).
- `courses/static/courses/css/courses.css` — roster rail classes (reusing `.unit-shell`/`.unit-tree` base) + collapsed-rail state from `<html>`.
- `courses/static/courses/js/` — new `review_roster.js` (collapse toggle + persistence + force-all confirm).
- `locale/pl/LC_MESSAGES/django.po` (+ `.mo`) — Polish strings.

**New tests:**
- `tests/test_review_roster.py` — service unit tests (grouping, marks, neighbours) + view render/redirect tests + force-submit-all tests.
- `tests/test_e2e_review.py` — extend with roster-switch / next-to-review / force-submit-all e2e.

---

## Task 1: `roster_for_unit` service — grouping, marks, flat order, scope

**Files:**
- Modify: `courses/review.py`
- Test: `tests/test_review_roster.py` (create)

**Interfaces:**
- Consumes: `submission_review_state`-equivalent grouping rule; `scoping.reviewable_students`; `QuizSubmission`, `QuestionElement`, `QuestionResponse`.
- Produces:
  - `_awaiting_review(state: dict) -> bool` — `state["total"] > 0 and not state["fully_reviewed"]`.
  - `roster_for_unit(reviewer, submission) -> dict` with keys:
    - `"rows"`: flat list, stably sorted by `(display_name.lower(), submission.pk)`, of row dicts: `{"submission", "student", "display_name", "group" ∈ {"to_review","in_progress","reviewed"}, "is_current": bool, "earned": Decimal|None, "max": Decimal|None, "auto_marked": bool}`.
    - `"groups"`: `{"to_review": [...], "in_progress": [...], "reviewed": [...]}` (each preserving the flat sort).
    - `"to_review_count": int`, `"in_progress_count": int`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_review_roster.py`:

```python
from decimal import Decimal

import pytest
from django.utils import timezone

from courses import review as review_svc
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _review_q(unit, *, max_marks="10"):
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Explain.", required_keywords="", forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW, max_marks=Decimal(max_marks),
    )
    return Element.objects.create(unit=unit, content_object=q)


def _auto_q(unit, *, max_marks="2"):
    q = ShortTextQuestionElement.objects.create(
        stem="2+2?", accepted="4",
        marking_mode=QuestionElement.MarkingMode.AUTO, max_marks=Decimal(max_marks),
    )
    return Element.objects.create(unit=unit, content_object=q)


def _sub(unit, student, status):
    return QuizSubmission.objects.create(student=student, unit=unit, status=status)


def _enrolled(course, name):
    # display_name=name is REQUIRED: UserFactory defaults display_name to a random
    # Faker("name") (tests/factories.py:54), and the roster labels/sorts by
    # `display_name or username` — without this the name + order assertions below
    # would key off random names and be nondeterministic.
    u = UserFactory(username=name, display_name=name)
    EnrollmentFactory(student=u, course=course)
    return u


def _quiz_unit(course):
    return ContentNodeFactory(course=course, kind="unit", unit_type="quiz")


def test_roster_groups_submitted_in_progress_reviewed(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    el = _review_q(unit, max_marks="10")
    ada = _enrolled(course, "ada")
    bob = _enrolled(course, "bob")
    cara = _enrolled(course, "cara")
    s_ada = _sub(unit, ada, QuizSubmission.Status.SUBMITTED)  # to review (unreviewed)
    _sub(unit, bob, QuizSubmission.Status.IN_PROGRESS)        # in progress
    s_cara = _sub(unit, cara, QuizSubmission.Status.SUBMITTED)  # reviewed below
    QuestionResponse.objects.create(
        submission=s_cara, element=el, earned_marks=Decimal("8.00"),
        fraction=Decimal("0.8000"), reviewed_at=timezone.now(), locked=True,
    )
    roster = review_svc.roster_for_unit(pa, s_ada)
    groups = {r["display_name"]: r["group"] for r in roster["rows"]}
    assert groups == {"ada": "to_review", "bob": "in_progress", "cara": "reviewed"}
    assert roster["to_review_count"] == 1
    assert roster["in_progress_count"] == 1


def test_roster_reviewed_row_carries_marks(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    el = _review_q(unit, max_marks="10")
    cara = _enrolled(course, "cara")
    s = _sub(unit, cara, QuizSubmission.Status.SUBMITTED)
    QuestionResponse.objects.create(
        submission=s, element=el, earned_marks=Decimal("8.00"),
        fraction=Decimal("0.8000"), reviewed_at=timezone.now(), locked=True,
    )
    row = review_svc.roster_for_unit(pa, s)["rows"][0]
    assert row["group"] == "reviewed"
    assert row["earned"] == Decimal("8.00")
    assert row["max"] == Decimal("10")
    assert row["auto_marked"] is False


def test_roster_auto_only_quiz_goes_to_reviewed_with_no_marks(client):
    # A quiz with ZERO [R] elements: submission_review_state.fully_reviewed is False
    # (total==0) but it must NOT land in "to review" — route it to Reviewed, labelled
    # auto-marked, with no score (spec §4.2).
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _auto_q(unit, max_marks="2")  # auto only, no [R]
    cara = _enrolled(course, "cara")
    s = _sub(unit, cara, QuizSubmission.Status.SUBMITTED)
    row = review_svc.roster_for_unit(pa, s)["rows"][0]
    assert row["group"] == "reviewed"
    assert row["auto_marked"] is True
    assert row["earned"] is None and row["max"] is None


def test_roster_is_scoped_and_current_flagged(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    other = CourseFactory(owner=UserFactory())
    unit = _quiz_unit(course)
    _review_q(unit)
    ada = _enrolled(course, "ada")
    s_ada = _sub(unit, ada, QuizSubmission.Status.SUBMITTED)
    # A submission for a DIFFERENT course's unit must never appear.
    outsider = _enrolled(other, "zzz")
    _sub(_quiz_unit(other), outsider, QuizSubmission.Status.SUBMITTED)
    roster = review_svc.roster_for_unit(pa, s_ada)
    names = [r["display_name"] for r in roster["rows"]]
    assert names == ["ada"]
    assert roster["rows"][0]["is_current"] is True


def test_roster_flat_order_is_name_then_pk(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    # Insertion order deliberately NOT alphabetical; expect sorted by lower(name), pk.
    for name in ("Zoe", "amy", "Bob"):
        _sub(unit, _enrolled(course, name), QuizSubmission.Status.SUBMITTED)
    current = QuizSubmission.objects.filter(unit=unit).first()
    rows = review_svc.roster_for_unit(pa, current)["rows"]
    assert [r["display_name"] for r in rows] == ["amy", "Bob", "Zoe"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_roster.py -x -q`
Expected: FAIL — `AttributeError: module 'courses.review' has no attribute 'roster_for_unit'`.

- [ ] **Step 3: Implement the service**

In `courses/review.py`, add (after `submission_review_state`):

```python
def _awaiting_review(state):
    """Shared grouping predicate: a SUBMITTED submission whose unit has at least
    one [R] element and is not yet fully reviewed. Both pending_reviews_for and
    roster_for_unit call this so the two groupings cannot drift (spec §4.2)."""
    return state["total"] > 0 and not state["fully_reviewed"]


def _review_marks_from_prefetch(submission, review_elements):
    """(earned, max, reviewed_count) over the unit's [R] elements, using the
    submission's PREFETCHED responses — no per-row query. `review_elements` is a
    list of (Element, QuestionElement) pairs gathered once per unit."""
    by_el = {r.element_id: r for r in submission.responses.all()}
    earned = Decimal("0")
    max_total = Decimal("0")
    reviewed = 0
    for el, q in review_elements:
        max_total += q.max_marks
        r = by_el.get(el.pk)
        if r is not None and r.reviewed_at is not None:
            reviewed += 1
            if r.earned_marks is not None:
                earned += r.earned_marks
    return earned, max_total, reviewed


def roster_for_unit(reviewer, submission):
    """Every in-scope sibling submission for submission.unit, grouped for the
    review roster (spec §4.2). One flat list sorted by (lower(name), pk); groups
    are a display concern. No N+1 (responses + content_object prefetched)."""
    unit = submission.unit
    course = unit.course
    student_ids = scoping.reviewable_students(reviewer, course).values("pk")
    subs = list(
        QuizSubmission.objects.filter(unit=unit, student_id__in=student_ids)
        .select_related("student")
        .prefetch_related("responses")
    )
    review_elements = [
        (el, el.content_object)
        for el in unit.elements.all().prefetch_related("content_object")
        if isinstance(el.content_object, QuestionElement)
        and el.content_object.marking_mode == QuestionElement.MarkingMode.REVIEW
    ]
    total = len(review_elements)

    rows = []
    for sub in subs:
        earned, max_total, reviewed = _review_marks_from_prefetch(sub, review_elements)
        state = {"total": total, "fully_reviewed": total > 0 and reviewed >= total}
        if sub.status == QuizSubmission.Status.IN_PROGRESS:
            group = "in_progress"
        elif _awaiting_review(state):
            group = "to_review"
        else:
            group = "reviewed"  # SUBMITTED & (fully reviewed OR zero-[R] auto-only)
        is_reviewed_with_marks = group == "reviewed" and total > 0
        name = sub.student.display_name or sub.student.username
        rows.append(
            {
                "submission": sub,
                "student": sub.student,
                "display_name": name,
                "group": group,
                "is_current": sub.pk == submission.pk,
                "earned": earned if is_reviewed_with_marks else None,
                "max": max_total if is_reviewed_with_marks else None,
                "auto_marked": group == "reviewed" and total == 0,
            }
        )
    rows.sort(key=lambda r: (r["display_name"].lower(), r["submission"].pk))
    groups = {"to_review": [], "in_progress": [], "reviewed": []}
    for r in rows:
        groups[r["group"]].append(r)
    return {
        "rows": rows,
        "groups": groups,
        "to_review_count": len(groups["to_review"]),
        "in_progress_count": len(groups["in_progress"]),
    }
```

Refactor `pending_reviews_for` to use the shared predicate — replace the line
`if st["total"] > 0 and not st["fully_reviewed"]:` with `if _awaiting_review(st):`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_roster.py -q`
Expected: PASS (5 tests). Then `uv run pytest tests/test_review_services.py -q` — the refactored `pending_reviews_for` still PASSES.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/review.py tests/test_review_roster.py
uv run ruff format courses/review.py tests/test_review_roster.py
git add courses/review.py tests/test_review_roster.py
git commit -m "feat(review): roster_for_unit service with shared grouping predicate"
```

---

## Task 2: `roster_neighbours` — Prev / Next-to-review over the flat order

**Files:**
- Modify: `courses/review.py`
- Test: `tests/test_review_roster.py`

**Interfaces:**
- Consumes: `roster_for_unit(...)` output (the `"rows"` flat list).
- Produces: `roster_neighbours(roster: dict, current_submission) -> dict` with `{"prev": QuizSubmission|None, "next_to_review": QuizSubmission|None}`. `prev` = the submission immediately before current in flat order (any group). `next_to_review` = the first `group == "to_review"` submission strictly after current in flat order, excluding current. Both `None` at the ends.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_review_roster.py`:

```python
def test_neighbours_prev_any_group_next_only_to_review(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    el = _review_q(unit, max_marks="10")
    # Flat order by name: amy(reviewed), bob(to_review), cara(to_review)
    amy = _enrolled(course, "amy")
    bob = _enrolled(course, "bob")
    cara = _enrolled(course, "cara")
    s_amy = _sub(unit, amy, QuizSubmission.Status.SUBMITTED)
    QuestionResponse.objects.create(
        submission=s_amy, element=el, earned_marks=Decimal("10"),
        fraction=Decimal("1.0000"), reviewed_at=timezone.now(), locked=True,
    )
    s_bob = _sub(unit, bob, QuizSubmission.Status.SUBMITTED)
    s_cara = _sub(unit, cara, QuizSubmission.Status.SUBMITTED)
    roster = review_svc.roster_for_unit(pa, s_bob)
    nb = review_svc.roster_neighbours(roster, s_bob)
    assert nb["prev"].pk == s_amy.pk           # prev = any group
    assert nb["next_to_review"].pk == s_cara.pk  # next to_review after bob


def test_neighbours_none_at_ends(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    amy = _enrolled(course, "amy")
    s_amy = _sub(unit, amy, QuizSubmission.Status.SUBMITTED)
    roster = review_svc.roster_for_unit(pa, s_amy)
    nb = review_svc.roster_neighbours(roster, s_amy)
    assert nb["prev"] is None  # first row
    assert nb["next_to_review"] is None  # no other to_review after it
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_roster.py -k neighbours -q`
Expected: FAIL — `AttributeError: … has no attribute 'roster_neighbours'`.

- [ ] **Step 3: Implement**

In `courses/review.py` add:

```python
def roster_neighbours(roster, current_submission):
    """Prev (any group) + Next-to-review for footer nav, over the flat roster
    order (spec §4.3). Both None at the ends."""
    rows = roster["rows"]
    idx = next(
        (i for i, r in enumerate(rows)
         if r["submission"].pk == current_submission.pk),
        None,
    )
    if idx is None:
        return {"prev": None, "next_to_review": None}
    prev = rows[idx - 1]["submission"] if idx > 0 else None
    next_to_review = None
    for r in rows[idx + 1:]:
        if r["group"] == "to_review":
            next_to_review = r["submission"]
            break
    return {"prev": prev, "next_to_review": next_to_review}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_roster.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/review.py tests/test_review_roster.py
uv run ruff format courses/review.py tests/test_review_roster.py
git add courses/review.py tests/test_review_roster.py
git commit -m "feat(review): roster_neighbours prev/next-to-review over flat order"
```

---

## Task 3: SUBMITTED guard — split `_resolve_submission` out of `_resolve_for_review`

**Files:**
- Modify: `courses/views_review.py`
- Test: `tests/test_review_roster.py`

**Interfaces:**
- Produces:
  - `_resolve_submission(request, slug, submission_pk) -> (course, submission)` — course-bind + scope check, **no** status guard (used by `force_submit`, which acts on IN_PROGRESS).
  - `_resolve_for_review(request, slug, submission_pk) -> (course, submission)` — calls `_resolve_submission` then **404s unless `submission.status == SUBMITTED`** (used by the review GET/POST view). Opening an IN_PROGRESS submission for review is rejected.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_review_roster.py`:

```python
from django.urls import reverse


def test_review_page_404s_for_in_progress_submission(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    ada = _enrolled(course, "ada")
    s = _sub(unit, ada, QuizSubmission.Status.IN_PROGRESS)
    url = reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": s.pk},
    )
    assert client.get(url).status_code == 404


def test_review_page_200_for_submitted(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    ada = _enrolled(course, "ada")
    s = _sub(unit, ada, QuizSubmission.Status.SUBMITTED)
    url = reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": s.pk},
    )
    assert client.get(url).status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_roster.py -k "in_progress_submission or 200_for_submitted" -q`
Expected: the `in_progress` test FAILS (currently returns 200, not 404).

- [ ] **Step 3: Implement**

In `courses/views_review.py`, replace `_resolve_for_review` with:

```python
def _resolve_submission(request, slug, submission_pk):
    """Course-bind + scope check, NO status guard. Used by force_submit, which
    deliberately acts on an IN_PROGRESS submission."""
    course = get_object_or_404(Course, slug=slug)
    submission = get_object_or_404(QuizSubmission, pk=submission_pk)
    if submission.unit.course_id != course.id:
        raise Http404
    if (
        not scoping.reviewable_students(request.user, course)
        .filter(pk=submission.student_id)
        .exists()
    ):
        raise Http404
    return course, submission


def _resolve_for_review(request, slug, submission_pk):
    """As _resolve_submission, but only a SUBMITTED submission can be opened for
    review (spec §4.4) — an IN_PROGRESS one 404s."""
    course, submission = _resolve_submission(request, slug, submission_pk)
    if submission.status != QuizSubmission.Status.SUBMITTED:
        raise Http404
    return course, submission
```

In `force_submit`, change its first line from
`course, submission = _resolve_for_review(request, slug, submission_pk)` to
`course, submission = _resolve_submission(request, slug, submission_pk)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_roster.py tests/test_review_views.py -q`
Expected: PASS (the new guard tests pass; existing review-view tests — including any individual force-submit test — still pass because `force_submit` now uses `_resolve_submission`).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/views_review.py tests/test_review_roster.py
uv run ruff format courses/views_review.py tests/test_review_roster.py
git add courses/views_review.py tests/test_review_roster.py
git commit -m "feat(review): SUBMITTED guard for review page; force_submit keeps IN_PROGRESS path"
```

---

## Task 4: Context-dependent redirect for individual `force_submit`

**Files:**
- Modify: `courses/views_review.py`
- Test: `tests/test_review_roster.py`

**Interfaces:**
- Produces: `_redirect_after_force(request, course) -> HttpResponseRedirect`. Reads a hidden POST field `review_pk`; if present and it resolves to a **SUBMITTED** submission within `reviewable_students(course)`, redirect to `courses:manage_review_submission` for it; otherwise fall back to `courses:manage_review_queue`. Never honours a free-form `next`/referrer.
- `force_submit` keeps its existing success message (`"Quiz submitted for <student>."`) and now returns `_redirect_after_force(request, course)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_review_roster.py`:

```python
def test_force_submit_redirects_to_review_when_review_pk_given(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    ada = _enrolled(course, "ada")
    bob = _enrolled(course, "bob")
    in_prog = _sub(unit, ada, QuizSubmission.Status.IN_PROGRESS)
    current = _sub(unit, bob, QuizSubmission.Status.SUBMITTED)  # the page we came from
    url = reverse(
        "courses:manage_review_force_submit",
        kwargs={"slug": course.slug, "submission_pk": in_prog.pk},
    )
    resp = client.post(url, {"review_pk": current.pk})
    assert resp.status_code == 302
    assert resp.url == reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": current.pk},
    )
    # message still emitted (public API, not the private _messages attr)
    from django.contrib.messages import get_messages

    msgs = [str(m).lower() for m in get_messages(resp.wsgi_request)]
    assert any("submitted for" in m for m in msgs)
    in_prog.refresh_from_db()
    assert in_prog.status == QuizSubmission.Status.SUBMITTED


def test_force_submit_falls_back_to_queue_without_review_pk(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    ada = _enrolled(course, "ada")
    in_prog = _sub(unit, ada, QuizSubmission.Status.IN_PROGRESS)
    url = reverse(
        "courses:manage_review_force_submit",
        kwargs={"slug": course.slug, "submission_pk": in_prog.pk},
    )
    resp = client.post(url, {})
    assert resp.status_code == 302
    assert resp.url == reverse(
        "courses:manage_review_queue", kwargs={"slug": course.slug}
    )
```

> NOTE for the implementer: the redirect URL + status change are the load-bearing
> assertions. The `get_messages(resp.wsgi_request)` check above is the public API
> for reading flash messages on a non-followed 302; if the existing
> `tests/test_review_views.py` force-submit test reads messages a different way,
> mirror that convention.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_roster.py -k force_submit -q`
Expected: the `review_pk` test FAILS — current `force_submit` always redirects to the queue.

- [ ] **Step 3: Implement**

In `courses/views_review.py` add the helper and rewrite `force_submit`'s return:

```python
def _redirect_after_force(request, course):
    """Server-computed redirect target for a force-submit action: back to the
    review page named by the hidden `review_pk` if it resolves to a SUBMITTED
    in-scope submission, else the legacy queue. Never trusts a free-form next/
    referrer (avoids open-redirect)."""
    review_pk = request.POST.get("review_pk")
    if review_pk:
        target = (
            QuizSubmission.objects.filter(
                pk=review_pk,
                unit__course_id=course.id,
                status=QuizSubmission.Status.SUBMITTED,
            )
            .filter(
                student_id__in=scoping.reviewable_students(
                    request.user, course
                ).values("pk")
            )
            .first()
        )
        if target is not None:
            return redirect(
                "courses:manage_review_submission",
                slug=course.slug,
                submission_pk=target.pk,
            )
    return redirect("courses:manage_review_queue", slug=course.slug)
```

Change the end of `force_submit` from
`return redirect("courses:manage_review_queue", slug=course.slug)`
to
`return _redirect_after_force(request, course)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_roster.py tests/test_review_views.py -q`
Expected: PASS (the legacy `tests/test_review_views.py` force-submit test still passes because, with no `review_pk`, the helper falls back to the queue).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/views_review.py tests/test_review_roster.py
uv run ruff format courses/views_review.py tests/test_review_roster.py
git add courses/views_review.py tests/test_review_roster.py
git commit -m "feat(review): context-dependent redirect for individual force-submit"
```

---

## Task 5: `force_submit_all` endpoint + URL

**Files:**
- Modify: `courses/views_review.py`, `courses/urls.py`
- Test: `tests/test_review_roster.py`

**Interfaces:**
- Produces: `force_submit_all(request, slug, unit_pk)` — `@login_required @require_POST`. URL name `courses:manage_review_force_submit_all`, path `manage/courses/<slug:slug>/review/unit/<int:unit_pk>/force-submit-all/`. Verifies unit belongs to course (404), gates `can_review_course` (404). Re-queries IN_PROGRESS submissions for the unit within `reviewable_students` **inside the request** and force-submits each via `force_submit_quiz`. Empty set → neutral info message, no error. Redirects via `_redirect_after_force` (Task 4) — i.e. back to the review page named by hidden `review_pk`, else the queue.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_review_roster.py`:

```python
def test_force_submit_all_submits_every_in_progress(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    a = _sub(unit, _enrolled(course, "a"), QuizSubmission.Status.IN_PROGRESS)
    b = _sub(unit, _enrolled(course, "b"), QuizSubmission.Status.IN_PROGRESS)
    current = _sub(unit, _enrolled(course, "c"), QuizSubmission.Status.SUBMITTED)
    url = reverse(
        "courses:manage_review_force_submit_all",
        kwargs={"slug": course.slug, "unit_pk": unit.pk},
    )
    resp = client.post(url, {"review_pk": current.pk})
    assert resp.status_code == 302
    assert resp.url == reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": current.pk},
    )
    a.refresh_from_db(); b.refresh_from_db()
    assert a.status == QuizSubmission.Status.SUBMITTED
    assert b.status == QuizSubmission.Status.SUBMITTED


def test_force_submit_all_empty_set_is_noop(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    current = _sub(unit, _enrolled(course, "c"), QuizSubmission.Status.SUBMITTED)
    url = reverse(
        "courses:manage_review_force_submit_all",
        kwargs={"slug": course.slug, "unit_pk": unit.pk},
    )
    resp = client.post(url, {"review_pk": current.pk}, follow=True)
    assert resp.status_code == 200  # no error, lands on review page
    body = resp.content.decode()
    assert "already submitted" in body.lower()  # neutral info message rendered


def test_force_submit_all_404_for_foreign_unit(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    other = CourseFactory(owner=UserFactory())
    foreign_unit = _quiz_unit(other)
    url = reverse(
        "courses:manage_review_force_submit_all",
        kwargs={"slug": course.slug, "unit_pk": foreign_unit.pk},
    )
    assert client.post(url, {}).status_code == 404


def test_force_submit_all_skips_student_who_submits_between_render_and_post(client):
    # Race: a student in the in-progress set submits normally before the POST.
    # force_submit_quiz no-ops on non-IN_PROGRESS, so the action is harmless.
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    a = _sub(unit, _enrolled(course, "a"), QuizSubmission.Status.SUBMITTED)  # already in
    b = _sub(unit, _enrolled(course, "b"), QuizSubmission.Status.IN_PROGRESS)
    url = reverse(
        "courses:manage_review_force_submit_all",
        kwargs={"slug": course.slug, "unit_pk": unit.pk},
    )
    client.post(url, {"review_pk": a.pk})
    a.refresh_from_db(); b.refresh_from_db()
    assert a.status == QuizSubmission.Status.SUBMITTED  # untouched
    assert b.status == QuizSubmission.Status.SUBMITTED  # forced
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_roster.py -k force_submit_all -q`
Expected: FAIL — `NoReverseMatch: 'manage_review_force_submit_all'`.

- [ ] **Step 3: Implement**

In `courses/views_review.py` add:

```python
@login_required
@require_POST
def force_submit_all(request, slug, unit_pk):
    course = get_object_or_404(Course, slug=slug)
    if not scoping.can_review_course(request.user, course):
        raise Http404
    unit = get_object_or_404(course.nodes, pk=unit_pk)  # course-bind: 404 if foreign
    in_scope = scoping.reviewable_students(request.user, course).values("pk")
    pending = QuizSubmission.objects.filter(
        unit=unit,
        student_id__in=in_scope,
        status=QuizSubmission.Status.IN_PROGRESS,
    )
    count = 0
    for sub in pending:
        review_svc.force_submit_quiz(sub, by=request.user)
        count += 1
    if count:
        # ngettext (NOT the singular _ with a "(zes)" hack) so Polish gets its real
        # 3-form plural set in Task 11. Import: `from django.utils.translation
        # import ngettext` alongside the existing `gettext as _`.
        messages.success(
            request,
            ngettext(
                "Force-submitted %(n)s quiz.",
                "Force-submitted %(n)s quizzes.",
                count,
            )
            % {"n": count},
        )
    else:
        # count==0 means every in-progress submission was submitted between page
        # render and this POST (the button only renders when in_progress_count>0,
        # so "already submitted" is accurate for the real flow; the no-submissions
        # case is only reachable via a forged POST with no button). Spec §4.4 wording.
        messages.info(request, _("All quizzes already submitted."))
    return _redirect_after_force(request, course)
```

> Implementer note: confirm the `Course` → units reverse accessor is `course.nodes`
> (the `ContentNode.course` FK related_name). If it differs, use
> `get_object_or_404(ContentNode, pk=unit_pk, course=course)` instead — the
> course-bind 404 is the contract, not the accessor name.

In `courses/urls.py`, in the review-queue routes block, add:

```python
    path(
        "manage/courses/<slug:slug>/review/unit/<int:unit_pk>/force-submit-all/",
        views_review.force_submit_all,
        name="manage_review_force_submit_all",
    ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_roster.py -q`
Expected: PASS (all roster tests, including force-submit-all).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/views_review.py courses/urls.py tests/test_review_roster.py
uv run ruff format courses/views_review.py courses/urls.py tests/test_review_roster.py
git add courses/views_review.py courses/urls.py tests/test_review_roster.py
git commit -m "feat(review): force-submit-all per-unit endpoint (re-query, idempotent, no-op empty)"
```

---

## Task 6: Wire roster + neighbours + counts into the review view context

**Files:**
- Modify: `courses/views_review.py`
- Test: `tests/test_review_roster.py`

**Interfaces:**
- Consumes: `roster_for_unit`, `roster_neighbours`.
- Produces: `review_submission` GET context additionally carries: `roster` (dict from `roster_for_unit`), `nav` (dict from `roster_neighbours`), `to_review_count`, `in_progress_count`. (Existing keys — `course`, `submission`, `rows`, `state`, `has_math` — unchanged.)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_review_roster.py`:

```python
def test_review_page_context_has_roster_and_nav(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    a = _sub(unit, _enrolled(course, "amy"), QuizSubmission.Status.SUBMITTED)
    _sub(unit, _enrolled(course, "bob"), QuizSubmission.Status.SUBMITTED)
    _sub(unit, _enrolled(course, "cy"), QuizSubmission.Status.IN_PROGRESS)
    url = reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": a.pk},
    )
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.context["to_review_count"] == 2  # amy + bob
    assert resp.context["in_progress_count"] == 1  # cy
    assert [r["display_name"] for r in resp.context["roster"]["rows"]] == [
        "amy", "bob", "cy",
    ]
    assert resp.context["nav"]["next_to_review"].pk  # bob is next after amy
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `uv run pytest tests/test_review_roster.py -k context_has_roster -q`
Expected: FAIL — `KeyError: 'to_review_count'` (context lacks the keys).

- [ ] **Step 3: Implement**

In `courses/views_review.py`, update `review_submission`'s GET branch. Replace the `render(...)` call in the GET path so it merges roster data:

```python
@login_required
def review_submission(request, slug, submission_pk):
    course, submission = _resolve_for_review(request, slug, submission_pk)
    if request.method == "POST":
        return _review_submission_post(request, course, submission)
    roster = review_svc.roster_for_unit(request.user, submission)
    context = _review_context(course, submission)
    context.update(
        {
            "roster": roster,
            "nav": review_svc.roster_neighbours(roster, submission),
            "to_review_count": roster["to_review_count"],
            "in_progress_count": roster["in_progress_count"],
        }
    )
    return render(request, "courses/manage/review_submission.html", context)
```

> Implementer note: the POST path (`_review_submission_post`) re-renders the same
> template on a 422 validation error via `_review_context` only — that error
> re-render will lack the roster. That's acceptable for this batch (a rare invalid
> marks submit); the template (Task 7) must guard every roster reference with
> `{% if roster %}` so the 422 re-render still renders. Keep this note in mind for
> Task 7.

- [ ] **Step 4: Run tests to verify it passes**

Run: `uv run pytest tests/test_review_roster.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/views_review.py tests/test_review_roster.py
uv run ruff format courses/views_review.py tests/test_review_roster.py
git add courses/views_review.py tests/test_review_roster.py
git commit -m "feat(review): pass roster + nav + counts into review_submission context"
```

---

## Task 7: Restructure `review_submission.html` into the unit-shell + roster

**Files:**
- Modify: `templates/courses/manage/review_submission.html`, `templates/base.html`
- Test: `tests/test_review_roster.py` (template-render assertions)

**Interfaces:**
- Consumes: context keys `roster`, `nav`, `to_review_count`, `in_progress_count`, plus existing `rows`, `submission`, `course`, `state`.
- Produces: a `{% block prepaint %}{% endblock %}` slot in `base.html` (before the CSS links); the restructured review template using `.unit-shell` with a left roster rail (id `review-roster`, header strip "Submissions" + toggle), grouped rows (To review / In progress / Reviewed), a top-bar with the "N to review" badge + "Force-submit all (N)" button (rendered only when `in_progress_count > 0`), the existing review cards in the right column, and a footer with Prev / Next-to-review.

- [ ] **Step 1: Write the failing template-render tests**

Append to `tests/test_review_roster.py`:

```python
def test_review_template_renders_roster_groups_and_force_all(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    a = _sub(unit, _enrolled(course, "amy"), QuizSubmission.Status.SUBMITTED)
    _sub(unit, _enrolled(course, "bob"), QuizSubmission.Status.IN_PROGRESS)
    url = reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": a.pk},
    )
    body = client.get(url).content.decode()
    assert "unit-shell" in body            # reuses batch-2 shell
    assert "review-roster" in body         # the rail
    assert "Submissions" in body           # header strip
    assert "1 to review" in body           # top-bar roster-total badge (§4.3); amy
    # Force-submit-all button present (1 in-progress) and posts to the unit route
    assert reverse(
        "courses:manage_review_force_submit_all",
        kwargs={"slug": course.slug, "unit_pk": unit.pk},
    ) in body


def test_review_template_hides_force_all_when_none_in_progress(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    a = _sub(unit, _enrolled(course, "amy"), QuizSubmission.Status.SUBMITTED)
    url = reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": a.pk},
    )
    body = client.get(url).content.decode()
    assert reverse(
        "courses:manage_review_force_submit_all",
        kwargs={"slug": course.slug, "unit_pk": unit.pk},
    ) not in body  # no force-all button when 0 in-progress
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_roster.py -k template_renders_roster -q`
Expected: FAIL — `"unit-shell"`/`"review-roster"` not in the current (flat) template.

- [ ] **Step 3a: Add the prepaint slot to `base.html`**

In `templates/base.html`, immediately **after** the unit-tree pre-paint `<script>` block (the one ending `})();</script>` around the `libli_unit_tree_collapsed` reader) and **before** `<link rel="stylesheet" href="{% static 'core/css/reset.css' %}">`, insert:

```html
  {% block prepaint %}{% endblock %}
```

- [ ] **Step 3b: Rewrite the review template**

Replace the body of `templates/courses/manage/review_submission.html`. **Keep** `{% extends "base.html" %}`, `{% load i18n static %}` (REQUIRED — every `{% trans %}`/`{% static %}`/`{% url %}`/`{% blocktrans %}` below needs it), and the `head_title` block verbatim. **Change the `extra_css` block** to ALSO link `courses.css` UNCONDITIONALLY (mirroring `quiz_unit.html:5`) — this page never loaded it before (`base.html` only links reset/tokens/app.css), so without this link ALL of the new `.unit-shell`/`.review-roster*`/`.review-topbar*`/`.review-foot` rules AND `badge--review`/`badge--muted` — all defined in `courses.css` — would be dead and the roster would ship completely unstyled:

```html
{% block extra_css %}
  <link rel="stylesheet" href="{% static 'courses/css/courses.css' %}">
  {% if has_math %}<link rel="stylesheet" href="{% static 'courses/vendor/katex/katex.min.css' %}">{% endif %}
{% endblock %}
```

New `{% block content %}`:

```html
{% block prepaint %}
<script>
  // Pre-paint: restore the review-roster collapse choice onto <html> (no flash).
  (function () {
    "use strict";
    try {
      if (localStorage.getItem("libli_review_roster_collapsed") === "1") {
        document.documentElement.classList.add("review-roster-collapsed");
      }
    } catch (e) {}
  })();
</script>
{% endblock %}

{% block content %}
<div class="unit-shell review-shell">
  {% if roster %}
  {# NOTE: the rail uses its OWN review-roster* classes — NOT .unit-tree* — so it does
     not inherit the lesson tree's <html>.unit-tree-collapsed state (set unconditionally
     by base.html's pre-paint from the SEPARATE libli_unit_tree_collapsed key) nor the
     .unit-tree mobile display:none. Task 8 styles these classes, borrowing declarations
     from .unit-tree rather than reusing its class. #}
  <nav class="review-roster" id="review-roster" aria-label="{% trans 'Submissions' %}">
    <div class="review-roster__bar">
      <span class="review-roster__heading">{% trans "Submissions" %}</span>
      <button type="button" class="review-roster__toggle" data-roster-toggle
              aria-label="{% trans 'Collapse submissions' %}">‹</button>
    </div>
    <div class="review-roster__list">
      {% if roster.groups.to_review %}
        <p class="review-roster__group">{% trans "To review" %}
          <span class="review-roster__count">{{ to_review_count }}</span></p>
        {% for r in roster.groups.to_review %}{% include "courses/manage/_roster_row.html" %}{% endfor %}
      {% endif %}
      {% if roster.groups.in_progress %}
        <p class="review-roster__group">{% trans "In progress" %}
          <span class="review-roster__count">{{ in_progress_count }}</span></p>
        {% for r in roster.groups.in_progress %}{% include "courses/manage/_roster_row.html" %}{% endfor %}
      {% endif %}
      {% if roster.groups.reviewed %}
        <p class="review-roster__group">{% trans "Reviewed" %}</p>
        {% for r in roster.groups.reviewed %}{% include "courses/manage/_roster_row.html" %}{% endfor %}
      {% endif %}
    </div>
  </nav>
  {% endif %}

  <div class="unit-shell__main">
    <header class="review-topbar">
      <h1 class="review-topbar__title">{% trans "Review" %}: {{ submission.student.display_name|default:submission.student.username }} — {{ submission.unit.title }}</h1>
      <span class="review-topbar__sp"></span>
      {% if in_progress_count %}
      <form method="post"
            action="{% url 'courses:manage_review_force_submit_all' slug=course.slug unit_pk=submission.unit.pk %}"
            data-confirm="{% blocktrans count n=in_progress_count %}Force-submit {{ n }} in-progress quiz?{% plural %}Force-submit all {{ n }} in-progress quizzes?{% endblocktrans %}">
        {% csrf_token %}
        <input type="hidden" name="review_pk" value="{{ submission.pk }}">
        <button type="submit" class="btn btn--ghost btn--small">{% blocktrans count n=in_progress_count %}Force-submit all ({{ n }}){% plural %}Force-submit all ({{ n }}){% endblocktrans %}</button>
      </form>
      {% endif %}
      {# Roster total "N to review" badge (spec §4.3 + mockup line 77) — counts ALL
         to_review submissions incl. the current one if itself still pending; distinct
         from the per-submission "X of Y reviewed" badge below. #}
      {% if to_review_count %}
      <span class="badge badge--review review-topbar__toreview">{% blocktrans count n=to_review_count %}{{ n }} to review{% plural %}{{ n }} to review{% endblocktrans %}</span>
      {% endif %}
      {% if state.fully_reviewed %}
        <span class="badge badge--muted">{% trans "Fully reviewed" %}</span>
      {% else %}
        <span class="badge badge--muted">{% blocktrans with done=state.reviewed total=state.total %}{{ done }} of {{ total }} reviewed{% endblocktrans %}</span>
      {% endif %}
    </header>

    {% for row in rows %}
    <article class="card review">
      {% comment %}Read-only display: stem + the student's answer as plain text — NOT
      the live widget. Wrapped in [data-question] (no form) so question.js typesets
      inline math.{% endcomment %}
      <div data-question>
        <div class="question__stem">{{ row.question.stem|safe }}</div>
        <p class="review__answer-label">{% trans "Answer" %}</p>
        {% if row.answer_text %}
          <div class="review__answer">{{ row.answer_text }}</div>
        {% else %}
          <div class="review__answer review__answer--empty">{% trans "No answer" %}</div>
        {% endif %}
      </div>
      <form method="post" action="{% url 'courses:manage_review_submission' slug=course.slug submission_pk=submission.pk %}">
        {% csrf_token %}
        <input type="hidden" name="element_pk" value="{{ row.element.pk }}">
        <label>{% trans "Marks awarded" %} <span class="muted">/ {{ row.max_marks }}</span>
          <input type="number" step="0.01" min="0" max="{{ row.max_marks }}" name="earned_marks"
                 value="{% if row.earned_marks is not None %}{{ row.earned_marks }}{% endif %}">
        </label>
        <label>{% trans "Feedback (optional)" %}
          <textarea name="feedback" rows="4">{{ row.feedback }}</textarea>
        </label>
        <button class="btn btn--primary btn--small" type="submit">{% trans "Save" %}</button>
      </form>
    </article>
    {% endfor %}

    {% if nav %}
    <footer class="review-foot">
      {% if nav.prev %}
        <a class="btn btn--ghost btn--small" href="{% url 'courses:manage_review_submission' slug=course.slug submission_pk=nav.prev.pk %}">‹ {{ nav.prev.student.display_name|default:nav.prev.student.username }}</a>
      {% else %}
        <span class="btn btn--ghost btn--small is-disabled" aria-disabled="true">‹ {% trans "Prev" %}</span>
      {% endif %}
      {% if nav.next_to_review %}
        <a class="btn btn--primary btn--small" href="{% url 'courses:manage_review_submission' slug=course.slug submission_pk=nav.next_to_review.pk %}">{% trans "Next to review" %} · {{ nav.next_to_review.student.display_name|default:nav.next_to_review.student.username }} ›</a>
      {% else %}
        <span class="btn btn--primary btn--small is-disabled" aria-disabled="true">{% trans "Next to review" %} ›</span>
      {% endif %}
    </footer>
    {% endif %}
  </div>
</div>
{% endblock %}

{% block extra_js %}
  {% if has_math %}
    {% comment %}PRESERVE the existing math trio — the read-only stem/answer live in a
    form-less [data-question] and question.js's initial pass typesets their inline
    math. Dropping these regresses math rendering AND breaks
    test_review_views.py::test_review_loads_katex_when_stem_has_math.{% endcomment %}
    <script src="{% static 'courses/vendor/katex/katex.min.js' %}" defer></script>
    <script src="{% static 'courses/vendor/katex/contrib/auto-render.min.js' %}" defer></script>
    <script src="{% static 'courses/js/question.js' %}" defer></script>
  {% endif %}
  {% if roster %}<script src="{% static 'courses/js/review_roster.js' %}" defer></script>{% endif %}
{% endblock %}
```

Create the roster-row partial `templates/courses/manage/_roster_row.html`:

```html
{% load i18n %}
{% comment %}Three row containers — the current row is a non-link <span> (highlighted),
the in-progress row is a <div> that holds the Force-submit <form> (NEVER an <a>: a
form/button nested in an anchor is invalid HTML5 and a button click would also fire
the anchor). Only to_review / reviewed rows are real links.{% endcomment %}
{% if r.is_current %}
<span class="review-roster__row is-active">
{% elif r.group == 'in_progress' %}
<div class="review-roster__row is-progress">
{% else %}
<a class="review-roster__row{% if r.group == 'reviewed' %} is-done{% endif %}"
   href="{% url 'courses:manage_review_submission' slug=course.slug submission_pk=r.submission.pk %}">
{% endif %}
  {% if r.group == 'reviewed' and not r.auto_marked %}<span class="review-roster__check" aria-hidden="true">✓</span>{% endif %}
  <span class="review-roster__name">{{ r.display_name }}</span>
  {% if r.group == 'reviewed' %}
    {% if r.auto_marked %}<span class="review-roster__mark">{% trans "Auto-marked" %}</span>
    {% else %}<span class="review-roster__mark">{{ r.earned }}/{{ r.max }}</span>{% endif %}
  {% endif %}
  {% if r.group == 'in_progress' %}
    <form method="post" action="{% url 'courses:manage_review_force_submit' slug=course.slug submission_pk=r.submission.pk %}" class="review-roster__force">
      {% csrf_token %}
      <input type="hidden" name="review_pk" value="{{ submission.pk }}">
      <button type="submit" class="review-roster__force-btn">{% trans "Force-submit" %}</button>
    </form>
  {% endif %}
{% if r.is_current %}</span>{% elif r.group == 'in_progress' %}</div>{% else %}</a>{% endif %}
```

> NOTE: the `is-active` current row is a `<span>` (not a link to itself); the
> in-progress row is a `<div>` (the review page only opens SUBMITTED — Task 3 — so
> it would not be a useful link, and it carries the Force-submit form). Only
> to_review / reviewed rows are `<a>` links. `badge--review` / `badge--muted` (used
> by the topbar below) live in **`courses.css`** (shipped batch 1, used by
> `quiz_results.html`/`course_results.html`) — NOT `app.css` — which is exactly why
> the `extra_css` block must link `courses.css` (see Step 3b). Only `badge--open` is
> in `app.css`.

- [ ] **Step 4: Run tests + a broad render smoke**

Run: `uv run pytest tests/test_review_roster.py -q`
Expected: PASS. Then `uv run pytest tests/test_review_views.py -q` — ALL existing review-view tests still pass. Check these markup-sensitive ones explicitly, since the full-content rewrite is most likely to break them:
- `test_review_loads_katex_when_stem_has_math` — the preserved `{% if has_math %}` trio keeps `katex.min.js` in the body.
- `test_review_stem_not_doubled` — the stem must still render exactly once (don't print `submission`/`row.question.stem` twice).
- `test_review_shows_answer_as_readonly_text_not_widget` — the answer stays plain `.review__answer` text; no live question widget (`question__form` / `name="answer"`) leaks in.
- the 422 invalid-marks re-render path — renders because every roster reference is `{% if roster %}`-guarded.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check tests/test_review_roster.py
uv run ruff format tests/test_review_roster.py
git add templates/base.html templates/courses/manage/review_submission.html templates/courses/manage/_roster_row.html tests/test_review_roster.py
git commit -m "feat(review): restructure review page into unit-shell + sibling roster"
```

---

## Task 8: Roster CSS (reuses the `.unit-shell` wrapper; rail has its own classes)

**Files:**
- Modify: `courses/static/courses/css/courses.css`
- Test: visual (screenshots in Task 11); a render-smoke assertion already covers class presence (Task 7).

**Interfaces:** reuses the `.unit-shell` / `.unit-shell__main` two-column wrapper from batch 2; defines its **own** rail classes `.review-roster` / `.review-roster__bar` / `__heading` / `__toggle` / `__list` (box declarations borrowed from `.unit-tree` but NOT its class, to stay decoupled from the lesson-tree collapse key + `.unit-tree` mobile-hide — see I1/I3), plus `.review-roster__group/row/...`, `.review-topbar*`, `.review-foot`, the `<html>.review-roster-collapsed` sliver-collapse, and a `≤640px` mobile stack.

- [ ] **Step 1: Add the styles**

Append to `courses/static/courses/css/courses.css` (after the `.unit-tree` block). The CSS below uses these tokens — confirm each resolves in `core/static/core/css/tokens.css` before relying on it: `--surface-sunken`, `--surface-raised`, `--border-default`, `--border-subtle`, `--border-strong`, `--text-tertiary`, `--text-secondary`, `--text-primary`, `--primary`, `--primary-subtle`, `--success` (all present in batch-1's token set; an unlisted/typo'd token silently no-ops):

```css
/* ── Quiz-review roster (batch 3) ───────────────────────────────────────────────
   Reuses the .unit-shell two-column WRAPPER, but the rail has its OWN review-roster*
   classes (NOT .unit-tree*) so it does not inherit the lesson tree's <html>
   .unit-tree-collapsed state (a separate localStorage key) nor the .unit-tree mobile
   display:none. Box declarations are borrowed from .unit-tree, not the class itself. */
.review-shell { align-items: stretch; }

/* Rail box (borrows .unit-tree: sticky, fixed width, sunken surface, scrolls). */
.review-roster { flex: 0 0 14rem; align-self: stretch; background: var(--surface-sunken);
  border-right: 1px solid var(--border-default); position: sticky; top: 0;
  max-height: 100vh; overflow-y: auto; font-size: .78rem; }
.review-roster__bar { display: flex; align-items: center; gap: .5rem; padding: .55rem .65rem;
  border-bottom: 1px solid var(--border-subtle); position: sticky; top: 0;
  background: var(--surface-sunken); }
.review-roster__heading { flex: 1; font-size: .62rem; font-weight: 700; letter-spacing: .06em;
  text-transform: uppercase; color: var(--text-tertiary); }
.review-roster__toggle { width: 1.4rem; height: 1.4rem; border: 1px solid var(--border-default);
  border-radius: .4rem; background: var(--surface-raised); color: var(--text-tertiary);
  cursor: pointer; line-height: 1; }
.review-roster__toggle:hover { color: var(--text-secondary); }
.review-roster__list { padding: .2rem .5rem 1rem; }

.review-roster__group { display: flex; align-items: center; justify-content: space-between;
  font-size: .6rem; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
  color: var(--text-tertiary); margin: .75rem .55rem .25rem; }
.review-roster__count { font-weight: 700; }
.review-roster__row { display: flex; align-items: center; gap: .5rem; padding: .35rem .5rem;
  margin: .05rem .15rem; border-radius: .45rem; color: var(--text-secondary);
  text-decoration: none; }
.review-roster__row:hover { background: var(--surface-raised); color: var(--text-primary); }
.review-roster__name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }
.review-roster__mark { font-size: .68rem; color: var(--text-tertiary);
  font-variant-numeric: tabular-nums; }
.review-roster__check { color: var(--success); }
.review-roster__row.is-active { background: var(--primary-subtle); color: var(--primary);
  font-weight: 600; }
.review-roster__row.is-done .review-roster__name { color: var(--text-tertiary); }
.review-roster__row.is-progress { color: var(--text-tertiary); font-style: italic; }
.review-roster__force { margin: 0; }
.review-roster__force-btn { font-style: normal; font-size: .62rem; font-weight: 600;
  border: 1px solid var(--border-default); border-radius: .4rem; padding: .1rem .4rem;
  color: var(--text-secondary); background: var(--surface-raised); cursor: pointer; }
.review-roster__force-btn:hover { color: var(--text-primary); border-color: var(--border-strong); }

.review-topbar { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap;
  padding: .75rem 1rem; border-bottom: 1px solid var(--border-default);
  background: var(--surface-raised); }
.review-topbar__title { font-size: 1.02rem; margin: 0; }
.review-topbar__sp { flex: 1; }
.review-topbar form { margin: 0; }

.review-foot { display: flex; justify-content: space-between; gap: .6rem;
  padding: .7rem 1rem; border-top: 1px solid var(--border-default);
  background: var(--surface-raised); position: sticky; bottom: 0; }
.review-foot .is-disabled { opacity: .45; pointer-events: none; }

/* Collapsed rail (C1 fix) — shrink to a SLIVER but KEEP the bar + toggle visible (flipped)
   so the user can re-expand; do NOT `display:none` the whole rail (that would bury its
   only toggle). Mirrors batch-2's unit-tree collapse. Keyed off <html> for no-flash via
   review_roster.js's pre-paint (separate libli_review_roster_collapsed key). */
.review-roster-collapsed .review-roster { flex-basis: 2.4rem; }
.review-roster-collapsed .review-roster__heading,
.review-roster-collapsed .review-roster__list { display: none; }
.review-roster-collapsed .review-roster__toggle { transform: scaleX(-1); }

/* Mobile (I3 fix) — .unit-shell becomes display:block below 640px (batch-2 rule), so the
   roster stacks ABOVE the main column. Full width, a bottom border instead of a right one,
   and a capped scroll height so a long roster doesn't push the review cards off-screen.
   It is NOT hidden here (it does not carry the .unit-tree class). */
@media (max-width: 640px) {
  .review-roster { flex-basis: auto; width: 100%; max-height: 40vh; position: static;
    border-right: 0; border-bottom: 1px solid var(--border-default); }
  .review-roster-collapsed .review-roster { flex-basis: auto; }
}
```

> Implementer note: the rail width lives on `.review-roster { flex: 0 0 14rem }` above
> (it does NOT inherit `.unit-tree`). If "name + mark" rows feel cramped, widen the
> `flex-basis` — verify against the Task 11 screenshots, don't guess.

- [ ] **Step 2: Manual render check (no unit test for pure CSS)**

Run: `uv run pytest tests/test_review_roster.py -q` (still green — CSS doesn't change render assertions). Visual verification deferred to Task 11.

- [ ] **Step 3: Lint + commit**

```bash
uv run ruff check . ; uv run ruff format --check courses/ tests/
git add courses/static/courses/css/courses.css
git commit -m "feat(review): roster rail + topbar + footer styles (reusing unit-shell)"
```

---

## Task 9: `review_roster.js` — collapse persistence + force-all confirm

**Files:**
- Create: `courses/static/courses/js/review_roster.js`
- Test: covered by e2e (Task 10); no unit test for vanilla JS.

**Interfaces:** consumes `[data-roster-toggle]` (the header toggle) and `[data-confirm]` (the force-all form, matching the quiz-finish confirm pattern). Persists collapse under `localStorage["libli_review_roster_collapsed"]`, toggling `<html>.review-roster-collapsed` (the pre-paint script in Task 7 restores it).

- [ ] **Step 1: Write the JS**

Create `courses/static/courses/js/review_roster.js`:

```javascript
(function () {
  "use strict";
  var KEY = "libli_review_roster_collapsed";
  var root = document.documentElement;

  // Collapse toggle — persist to localStorage; pre-paint script restores it.
  var toggle = document.querySelector("[data-roster-toggle]");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var collapsed = root.classList.toggle("review-roster-collapsed");
      try { localStorage.setItem(KEY, collapsed ? "1" : "0"); } catch (e) {}
    });
  }

  // Force-submit-all confirm (same pattern as quiz-finish): block submit unless
  // the user confirms. data-confirm carries the localized prompt.
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.getAttribute("data-confirm"))) {
        e.preventDefault();
      }
    });
  });
})();
```

- [ ] **Step 2: Wire-up check**

The template (Task 7) already loads it via `{% block extra_js %}` and renders
`[data-roster-toggle]` + `[data-confirm]`. Confirm `base.html` has an `extra_js`
block; if the block name differs (e.g. `scripts`), match the existing convention
used by `lesson_unit.html`/`quiz_unit.html`.

Run: `uv run pytest tests/test_review_roster.py -q` (still green).

- [ ] **Step 3: Lint + commit**

```bash
git add courses/static/courses/js/review_roster.js templates/courses/manage/review_submission.html
git commit -m "feat(review): roster collapse persistence + force-all confirm JS"
```

---

## Task 10: e2e — roster switch, Next-to-review, Force-submit-all

**Files:**
- Modify: `tests/test_e2e_review.py`
- (Reference `tests/test_e2e_review.py` for the existing reviewer-login + course-build helpers; reuse them.)

**Interfaces:** drives the real browser per `e2e-must-drive-real-ui` — clicks an actual roster row link, the actual "Next to review" link, and the actual "Force-submit all" button through its confirm dialog.

- [ ] **Step 1: Write the failing e2e**

Append to `tests/test_e2e_review.py` (mirror the file's existing fixtures/login; sketch shown — adapt selectors/helpers to the file's conventions):

```python
@pytest.mark.django_db(transaction=True)
def test_roster_switch_and_force_submit_all(page, live_server, client):
    # CONCRETE seeding so "Next to review" provably has a later to_review sibling.
    # _build_course_with_review_quiz(owner) returns (course, unit, _student); extend
    # it (or seed inline) so the unit has THREE students by display_name order:
    #   "alpha"   -> SUBMITTED, unreviewed  (to_review)  ← the page we open
    #   "bravo"   -> SUBMITTED, unreviewed  (to_review)  ← the Next-to-review target
    #   "charlie" -> IN_PROGRESS                          (in_progress)
    # Each student is make_verified_user(... display_name=name) + EnrollmentFactory;
    # submissions are QuizSubmission.objects.create(student=, unit=, status=).
    owner = make_pa(client, "rosterowner")
    # ... build course/unit/[R] el with owner; seed alpha/bravo/charlie as above ...
    _login(page, live_server, "rosterowner")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/review/{alpha_sub.pk}/")

    # Roster shows the three groups.
    assert page.locator(".review-roster").is_visible()
    page.locator("text=Submissions").wait_for(timeout=4000)

    # "Next to review" is the enabled primary link (bravo, the next to_review after
    # alpha in name order) — NOT a disabled <span>. Click it → lands on bravo's page.
    next_link = page.locator(".review-foot a.btn--primary")
    assert next_link.count() == 1  # an <a>, not the disabled <span> end-state
    next_link.click()
    page.wait_for_load_state("networkidle")
    assert f"/review/{bravo_sub.pk}/" in page.url

    # Force-submit all: accept the confirm dialog, then charlie (in_progress) becomes
    # SUBMITTED and the "In progress" group disappears from the roster.
    page.once("dialog", lambda d: d.accept())
    page.locator(".review-topbar button[type='submit']").click()
    page.wait_for_load_state("networkidle")
    charlie_sub.refresh_from_db()
    assert charlie_sub.status == QuizSubmission.Status.SUBMITTED
    assert page.locator("text=In progress").count() == 0


@pytest.mark.django_db(transaction=True)
def test_roster_collapse_persists_and_can_reexpand(page, live_server, client):
    # ... make_pa + build course/quiz + one SUBMITTED student + _login ...
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/review/{some_sub.pk}/")
    toggle = page.locator("[data-roster-toggle]")
    toggle.click()  # collapse
    assert page.locator("html.review-roster-collapsed").count() == 1
    # C1: the toggle must STAY visible when collapsed (sliver rail), so re-expand works.
    assert toggle.is_visible()
    page.reload()  # persisted across reload via localStorage + pre-paint script
    assert page.locator("html.review-roster-collapsed").count() == 1
    assert toggle.is_visible()
    toggle.click()  # re-expand
    assert page.locator("html.review-roster-collapsed").count() == 0
```

> Implementer: reuse this file's REAL fixtures/helpers (verified) rather than
> re-inventing — the tests take `(page, live_server, client)`; auth is
> `owner = make_pa(client, "<name>")` (PA reviewer) + the module's
> `_login(page, live_server, "<name>")` / `_logout(...)` helpers; build the
> course/quiz with the module's `_build_course_with_review_quiz(owner)` (extend it
> to seed the extra submitted/in-progress students you need). There is **no**
> `browser`/`review_url_for` here — use the `page` fixture directly and build URLs
> as `f"/manage/courses/{course.slug}/review/{sub.pk}/"`. The load-bearing
> gestures are: (1) click a real roster/Next link, (2) accept the real confirm
> dialog and click the real Force-submit-all button, (3) toggle + reload for
> persistence. Do NOT use `page.evaluate` shortcuts (per `e2e-must-drive-real-ui`).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_e2e_review.py -k "roster" -q -m e2e`
Expected: FAIL initially (selectors/flows not yet satisfied) — then iterate to green against the built UI.

- [ ] **Step 3: Make it pass**

Adjust selectors to the rendered markup until green. Run:
`uv run pytest tests/test_e2e_review.py -q -m e2e`
Expected: PASS (run this file alone — running many e2e files together can hit
live_server port contention, an infra artifact, not a real failure).

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_review.py
git commit -m "test(review): e2e roster switch, next-to-review, force-submit-all, collapse persist"
```

---

## Task 11: i18n (Polish) + DoD (full suite, ruff, screenshots)

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)

- [ ] **Step 1: Extract new strings**

Run: `uv run python manage.py makemessages -l pl`
Then **grep the new msgids** and add Polish translations, e.g.:
- `"Submissions"` → `"Zgłoszenia"`
- `"To review"` → `"Do sprawdzenia"`
- `"In progress"` → `"W toku"`
- `"Reviewed"` → `"Sprawdzone"`
- `"Auto-marked"` → `"Oceniono automatycznie"`
- `"Force-submit"` → `"Wymuś wysłanie"`
- `"Force-submit all (%(n)s)"` plural forms → Polish plural set (3 forms).
- `"Next to review"` → `"Następne do sprawdzenia"`
- the `{{ n }} to review` blocktrans-count badge → Polish 3-form plural (`%(n)s do sprawdzenia`).
- `"Prev"` → `"Poprzednie"`
- `"All quizzes already submitted."` → `"Wszystkie quizy zostały już wysłane."`
- the `ngettext` pair `"Force-submitted %(n)s quiz."` / `"Force-submitted %(n)s quizzes."` → one `msgid`+`msgid_plural` entry with the Polish 3-form `msgstr[0..2]` set.
- `"Collapse submissions"` → `"Zwiń zgłoszenia"`
- the confirm `"Force-submit … in-progress quiz(zes)?"` plural → Polish plural set.

**Clear any `#, fuzzy` flags** the extractor adds to these new msgids (verify each
guessed match is correct; drop `#~` obsolete lines). Then:
Run: `uv run python manage.py compilemessages`

- [ ] **Step 2: i18n catalog test**

Run: `uv run pytest -k po_catalog_clean -q`
Expected: PASS (no stray fuzzy/obsolete entries).

- [ ] **Step 3: Full suite + lint (DoD)**

```bash
uv run pytest -q            # non-e2e: expect all green
uv run pytest -q -m e2e     # e2e: expect green (run review e2e file alone if port contention)
uv run ruff check .
uv run ruff format --check .
```
Expected: all green.

- [ ] **Step 4: Screenshot self-review (light + dark)**

Per `verify-ui-with-screenshots`: throwaway Playwright harness, screenshot the
review page **light + dark** at desktop width (roster visible, all three groups,
current row highlighted, footer Prev/Next, force-all button) and a narrow width
(roster behaviour on mobile). Self-critique: group labels legible, current-row
teal correct in both themes, marks aligned, force-submit buttons not cramped,
footer reachable. Fix any issues, delete the harness (delete-after pattern).

- [ ] **Step 5: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(review): Polish strings for the quiz-review roster"
```

---

## Self-Review (author checklist — completed)

**Spec coverage:**
- §4.1 layout (collapsible rail, "Submissions" header strip + toggle) → Tasks 7, 8, 9. ✓
- §4.2 `roster_for_unit` (shared predicate, three groups, zero-[R] auto-only → Reviewed "Auto-marked" no-score, Reviewed marks via prefetch, flat `(lower(name), pk)` sort, scope, current highlight) → Tasks 1, 7. ✓
- §4.3 footer Prev (any group) / Next-to-review (next to_review after current), "N to review" badge counts all incl. current → Tasks 2, 6, 7. ✓
- §4.4 force-submit-all (per-unit route, re-query, idempotent, empty no-op + neutral message, button hidden at N==0, confirm, redirect to current review page), `_resolve_for_review` SUBMITTED guard, individual force-submit context redirect via hidden `review_pk` keeping its message → Tasks 3, 4, 5, 7, 9. ✓
- §8 tests (service grouping incl. auto-only, force-all scope/idempotency/race/empty-no-op, neighbours, template render, e2e real gestures) → Tasks 1–7, 10. ✓
- §9 risks (no seen-hook added to this page; scope-gated mutation; pre-paint collapse on `<html>` with a **separate** localStorage key from the unit tree) → Tasks 7, 9. ✓

**Placeholder scan:** the e2e seed/login + `review_url_for` in Task 10 and the
exact PL plural forms in Task 11 are intentionally deferred to the file's existing
conventions / translator judgement (flagged inline), not silent TODOs. All
service/view/template/CSS/JS steps carry complete code.

**Type consistency:** `roster_for_unit` returns `{rows, groups, to_review_count, in_progress_count}`; `roster_neighbours(roster, submission)` reads `roster["rows"]` and returns `{prev, next_to_review}`; the view passes `roster`, `nav`, `to_review_count`, `in_progress_count`; the template reads exactly those. Row dict keys (`group`, `is_current`, `display_name`, `earned`, `max`, `auto_marked`, `submission`) are consistent across service, partial, and tests. `_resolve_submission` / `_resolve_for_review` / `_redirect_after_force` signatures match across Tasks 3–6.
