# Notifications — Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `notifications` Django app that persists system-generated event notifications (quiz-needs-review → teacher, quiz-graded → student, enrolled → student) and surfaces them on a minimal server-rendered `/notifications/` page with an unread badge in the nav and per-row / mark-all read controls.

**Architecture:** One `Notification` model with a lightweight `(target_type, target_id)` pointer plus a denormalized `data` JSON. A single `notify()` choke-point service records rows; per-kind emit helpers (`notify_needs_review`, `notify_graded`, `notify_enrolled`) are called from existing domain services/views **inside their `transaction.atomic()` blocks** via function-local imports (no signals, no import cycle). Read state is a per-row `read_at` timestamp. The page is server-rendered and styled via the global `app.css`; the nav badge comes from a context processor.

**Tech Stack:** Python 3.13 + Django 5.2, PostgreSQL, pytest + factory_boy, Playwright (e2e), gettext i18n (EN/PL), `uv` for all tooling.

Spec: `docs/superpowers/specs/2026-07-01-notifications-slice-1-design.md` (read it before starting).

## Global Constraints

- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH. Use `uv run ruff ...`, `uv run pytest ...`, `uv run python manage.py ...`.
- **Lint gate:** every task ends with `uv run ruff check .` AND `uv run ruff format .` clean (CI runs `ruff format --check`).
- **Tests:** unit/integration tests use `pytestmark = pytest.mark.django_db`. e2e tests use `@pytest.mark.e2e` (excluded by default; run with `-m e2e`). Default run excludes e2e (`addopts = -q -m 'not e2e'`).
- **Test password:** always `from tests.factories import TEST_PASSWORD`; never a new password literal (GitGuardian CI flags them).
- **i18n:** user-facing choice labels use `gettext_lazy as _` at module level; templates use `{% load i18n %}` + `{% trans %}` / `{% blocktrans %}`. EN is the source language (no `.po`); PL lives in `locale/pl/LC_MESSAGES/django.po` and must be compiled to `.mo`.
- **Import direction:** the emit sites in `courses/` and `grouping/` import `notifications.services` via **function-local imports** only (avoids a load-time cycle). The `notifications` app may import `courses`/`grouping` at module level.
- **Styling:** no bare HTML. All styles live in `core/static/core/css/app.css` (linked once in `templates/base.html`). Icons are monochrome `currentColor` line SVGs. Verify the page light + dark with a throwaway screenshot before the final task.
- **App label:** register the app as `"notifications"` in `config/settings/base.py` INSTALLED_APPS (mirrors `"notes"`).

---

## File Structure

**New files (the `notifications` app):**
- `notifications/__init__.py` — empty package marker.
- `notifications/apps.py` — `NotificationsConfig`.
- `notifications/models.py` — the `Notification` model (Kind, TargetType, fields, indexes).
- `notifications/services.py` — `notify()`, `_resolve_target()`, `unread_count()`, `recent_for()`, `notify_needs_review()`, `notify_graded()`, `notify_enrolled()`, `notification_url()`.
- `notifications/recipients.py` — `teachers_for()`, `review_recipients()`.
- `notifications/views.py` — `notification_list`, `mark_read`, `mark_all_read`.
- `notifications/urls.py` — `notifications:` routes.
- `notifications/migrations/0001_initial.py` — generated.
- `notifications/templates/notifications/list.html` — the page.
- `notifications/tests/__init__.py`, `test_model.py` (Task 1), `test_services.py` (Task 2), `test_recipients.py` (Task 3), `test_emit_review.py` (Task 4), `test_emit_helpers.py` (Task 5), `test_wire_review.py` (Task 6), `test_wire_graded.py` (Task 7), `test_wire_enrolled.py` (Task 8), `test_views.py` (Task 9), `test_mark.py` (Task 10), `test_badge.py` (Task 11), `test_i18n.py` (Task 12), `test_e2e_notifications.py` (Task 13).

**Modified files:**
- `config/settings/base.py` — add `"notifications"` to INSTALLED_APPS; add the context processor.
- `config/urls.py` — `include("notifications.urls")`.
- `courses/views.py` — `quiz_finish`: emit `notify_needs_review`.
- `courses/review.py` — `force_submit_quiz`: emit `notify_needs_review`; `review_response`: emit `notify_graded`.
- `grouping/services.py` — `enroll_self` + `recompute_enrollment`: emit `notify_enrolled`.
- `core/context_processors.py` — `notifications_badge`.
- `templates/base.html` — nav notifications link + unread badge.
- `core/static/core/css/app.css` — `.notif-*` and `.nav-badge` styles.
- `locale/pl/LC_MESSAGES/django.po` / `.mo` — PL translations.

---

### Task 1: Scaffold the `notifications` app + `Notification` model

**Files:**
- Create: `notifications/__init__.py`, `notifications/apps.py`, `notifications/models.py`, `notifications/tests/__init__.py`, `notifications/tests/test_model.py`
- Modify: `config/settings/base.py` (INSTALLED_APPS)
- Generated: `notifications/migrations/0001_initial.py`

**Interfaces:**
- Produces: `notifications.models.Notification` with `Kind` (`QUIZ_NEEDS_REVIEW`, `QUIZ_GRADED`, `ENROLLED`) and `TargetType` (`SUBMISSION`, `COURSE`) TextChoices; fields `recipient` FK, `kind`, `actor` nullable FK, `target_type`, `target_id` BigInteger, `data` JSON, `created_at`, `read_at` nullable. `Meta.ordering = ["-created_at", "-id"]`.

- [ ] **Step 1: Write the failing model test**

Create `notifications/tests/__init__.py` (empty) and `notifications/tests/test_model.py`:

```python
import pytest

from notifications.models import Notification
from tests.factories import CourseFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_notification_defaults_and_fields():
    user = UserFactory()
    course = CourseFactory()
    n = Notification.objects.create(
        recipient=user,
        kind=Notification.Kind.ENROLLED,
        target_type=Notification.TargetType.COURSE,
        target_id=course.pk,
    )
    assert n.read_at is None
    assert n.data == {}
    assert n.actor is None
    assert n.created_at is not None


def test_notification_ordering_newest_first():
    user = UserFactory()
    first = Notification.objects.create(
        recipient=user, kind=Notification.Kind.ENROLLED,
        target_type=Notification.TargetType.COURSE, target_id=1,
    )
    second = Notification.objects.create(
        recipient=user, kind=Notification.Kind.ENROLLED,
        target_type=Notification.TargetType.COURSE, target_id=2,
    )
    assert list(Notification.objects.filter(recipient=user)) == [second, first]
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest notifications/tests/test_model.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'notifications'`.

- [ ] **Step 3: Create the app package + config**

`notifications/__init__.py`: empty file.

`notifications/apps.py`:
```python
from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"
```

- [ ] **Step 4: Write the model**

`notifications/models.py`:
```python
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class Notification(models.Model):
    class Kind(models.TextChoices):
        QUIZ_NEEDS_REVIEW = "quiz_needs_review", _("Quiz needs review")
        QUIZ_GRADED = "quiz_graded", _("Quiz graded")
        ENROLLED = "enrolled", _("Enrolled in course")

    class TargetType(models.TextChoices):
        SUBMISSION = "submission", _("Quiz submission")
        COURSE = "course", _("Course")

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    target_type = models.CharField(max_length=16, choices=TargetType.choices)
    target_id = models.BigIntegerField()
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["recipient", "-created_at"]),
            models.Index(
                fields=["recipient"],
                name="notif_unread_idx",
                condition=Q(read_at__isnull=True),
            ),
        ]

    def __str__(self):
        return f"{self.kind} → {self.recipient_id}"
```

- [ ] **Step 5: Register the app**

In `config/settings/base.py`, add `"notifications",` to INSTALLED_APPS next to `"notes"`.

- [ ] **Step 6: Generate the migration**

Run: `uv run python manage.py makemigrations notifications`
Expected: creates `notifications/migrations/0001_initial.py` (model + two indexes). Confirm the file exists.

- [ ] **Step 7: Run the tests — expect PASS**

Run: `uv run pytest notifications/tests/test_model.py -q`
Expected: PASS (2 tests). Then `uv run ruff check . && uv run ruff format .`.

- [ ] **Step 8: Commit**

```bash
git add notifications/ config/settings/base.py
git commit -m "feat(notifications): scaffold app + Notification model"
```

---

### Task 2: `notify()` choke-point + `_resolve_target` + read helpers

**Files:**
- Create: `notifications/services.py`, `notifications/tests/test_services.py`

**Interfaces:**
- Consumes: `notifications.models.Notification`; `courses.models.Course`, `courses.models.QuizSubmission`.
- Produces:
  - `notify(*, recipient, kind, target, actor=None, data=None) -> Notification | None` — creates a row; returns `None` (no create) when `actor is not None and recipient == actor`.
  - `_resolve_target(target) -> tuple[str, int]` — `Course → ("course", pk)`, `QuizSubmission → ("submission", pk)`, else `TypeError`.
  - `unread_count(user) -> int`.
  - `recent_for(user, limit) -> QuerySet[Notification]`.

- [ ] **Step 1: Write the failing test**

`notifications/tests/test_services.py`:
```python
import pytest

from notifications import services
from notifications.models import Notification
from tests.factories import CourseFactory, QuizSubmissionFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_notify_creates_row():
    recipient = UserFactory()
    course = CourseFactory()
    n = services.notify(
        recipient=recipient,
        kind=Notification.Kind.ENROLLED,
        target=course,
        data={"course_title": course.title},
    )
    assert n is not None
    assert n.recipient == recipient
    assert n.target_type == "course"
    assert n.target_id == course.pk
    assert n.data == {"course_title": course.title}


def test_notify_self_is_noop():
    user = UserFactory()
    course = CourseFactory()
    result = services.notify(
        recipient=user, kind=Notification.Kind.ENROLLED, target=course, actor=user
    )
    assert result is None
    assert Notification.objects.count() == 0


def test_resolve_target_course_and_submission():
    course = CourseFactory()
    sub = QuizSubmissionFactory()
    assert services._resolve_target(course) == ("course", course.pk)
    assert services._resolve_target(sub) == ("submission", sub.pk)


def test_resolve_target_rejects_unknown():
    with pytest.raises(TypeError):
        services._resolve_target(object())


def test_unread_count_and_recent_for():
    user = UserFactory()
    course = CourseFactory()
    a = services.notify(recipient=user, kind=Notification.Kind.ENROLLED, target=course)
    b = services.notify(recipient=user, kind=Notification.Kind.ENROLLED, target=course)
    assert services.unread_count(user) == 2
    a.read_at = b.created_at
    a.save(update_fields=["read_at"])
    assert services.unread_count(user) == 1
    assert list(services.recent_for(user, 1)) == [b]
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `uv run pytest notifications/tests/test_services.py -q`
Expected: FAIL (`services` has no `notify`).

- [ ] **Step 3: Implement `notifications/services.py`**

```python
from courses.models import Course, QuizSubmission

from notifications.models import Notification


def _resolve_target(target):
    """Map a domain object to (target_type, target_id). No None case."""
    if isinstance(target, QuizSubmission):
        return (Notification.TargetType.SUBMISSION, target.pk)
    if isinstance(target, Course):
        return (Notification.TargetType.COURSE, target.pk)
    raise TypeError(f"Unsupported notification target: {type(target)!r}")


def notify(*, recipient, kind, target, actor=None, data=None):
    """Record a notification. No-op (returns None) when recipient == actor.
    Call inside the emit site's transaction.atomic() block."""
    if actor is not None and recipient == actor:
        return None
    target_type, target_id = _resolve_target(target)
    return Notification.objects.create(
        recipient=recipient,
        kind=kind,
        actor=actor,
        target_type=target_type,
        target_id=target_id,
        data=data or {},
    )


def unread_count(user):
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()


def recent_for(user, limit):
    return Notification.objects.filter(recipient=user)[:limit]
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest notifications/tests/test_services.py -q` → PASS. Then `uv run ruff check . && uv run ruff format .`.

- [ ] **Step 5: Commit**

```bash
git add notifications/services.py notifications/tests/test_services.py
git commit -m "feat(notifications): notify() choke-point + read helpers"
```

---

### Task 3: `teachers_for` + `review_recipients` recipient resolution

**Files:**
- Create: `notifications/recipients.py`, `notifications/tests/test_recipients.py`

**Interfaces:**
- Consumes: `grouping.models.Group`, `grouping.models.GroupMembership`; `Course.owner`; the User model.
- Produces:
  - `teachers_for(student, course) -> list[User]` — distinct union of `Group.teachers` across the student's **non-archived** groups for that course.
  - `review_recipients(submission) -> list[User]` — `teachers_for(...)` if non-empty, else `[course.owner]` (empty if owner is `None`).

- [ ] **Step 1: Write the failing test**

`notifications/tests/test_recipients.py`:
```python
import pytest

from notifications.recipients import review_recipients, teachers_for
from tests.factories import (
    CourseFactory,
    GroupFactory,
    GroupMembershipFactory,
    QuizSubmissionFactory,
    UserFactory,
    make_quiz_unit,
)

pytestmark = pytest.mark.django_db


def _grouped_student(course, teachers, *, archived=False):
    student = UserFactory()
    group = GroupFactory(course=course, archived=archived)
    for t in teachers:
        group.teachers.add(t)
    GroupMembershipFactory(group=group, student=student)
    return student, group


def test_teachers_for_single_group():
    course = CourseFactory()
    t1 = UserFactory()
    student, _ = _grouped_student(course, [t1])
    assert teachers_for(student, course) == [t1]


def test_teachers_for_unions_multiple_groups_and_dedupes():
    course = CourseFactory()
    t1, t2, shared = UserFactory(), UserFactory(), UserFactory()
    student = UserFactory()
    g1 = GroupFactory(course=course)
    g1.teachers.add(t1, shared)
    GroupMembershipFactory(group=g1, student=student)
    g2 = GroupFactory(course=course)
    g2.teachers.add(t2, shared)
    GroupMembershipFactory(group=g2, student=student)
    result = set(teachers_for(student, course))
    assert result == {t1, t2, shared}
    assert len(teachers_for(student, course)) == 3  # shared not duplicated


def test_teachers_for_excludes_archived_group():
    course = CourseFactory()
    t1 = UserFactory()
    student, _ = _grouped_student(course, [t1], archived=True)
    assert teachers_for(student, course) == []


def test_teachers_for_empty_when_group_has_no_teachers():
    course = CourseFactory()
    student, _ = _grouped_student(course, [])
    assert teachers_for(student, course) == []


def test_review_recipients_uses_teachers_when_present():
    course = CourseFactory()
    t1 = UserFactory()
    student, _ = _grouped_student(course, [t1])
    sub = QuizSubmissionFactory(student=student, unit=make_quiz_unit(course=course))
    assert review_recipients(sub) == [t1]


def test_review_recipients_falls_back_to_owner_when_no_teachers():
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    student, _ = _grouped_student(course, [])  # teacher-less group → empty set
    sub = QuizSubmissionFactory(student=student, unit=make_quiz_unit(course=course))
    assert review_recipients(sub) == [owner]


def test_review_recipients_empty_when_no_teachers_and_no_owner():
    course = CourseFactory(owner=None)
    student = UserFactory()  # no group at all
    sub = QuizSubmissionFactory(student=student, unit=make_quiz_unit(course=course))
    assert review_recipients(sub) == []
```

> Note: `QuizSubmissionFactory.unit` is a `LazyFunction(make_quiz_unit)` (not a `SubFactory`), so passing `unit__course=` is **silently ignored** — it would build a unit on a *different random* course and make these assertions fail confusingly. Always build the quiz unit explicitly with `make_quiz_unit(course=course)` (`tests/factories.py:167`) and pass `unit=`, as shown above.

- [ ] **Step 2: Run it — expect FAIL**

Run: `uv run pytest notifications/tests/test_recipients.py -q`
Expected: FAIL (`notifications.recipients` missing). If it errors on the `unit__course=` kwarg, switch those two tests to the explicit-unit construction noted above.

- [ ] **Step 3: Implement `notifications/recipients.py`**

```python
from django.contrib.auth import get_user_model

User = get_user_model()


def teachers_for(student, course):
    """Distinct union of Group.teachers across the student's non-archived groups
    for `course`. Front-line group teachers only (not the inverse of
    reviewable_students — owner/PA reach is deliberately not fanned out)."""
    return list(
        User.objects.filter(
            taught_groups__course=course,
            taught_groups__archived=False,
            taught_groups__memberships__student=student,
        ).distinct()
    )


def review_recipients(submission):
    """teachers_for(...) if non-empty, else [course.owner] (empty if owner None).
    The fallback triggers on an EMPTY resolved-teacher set — covers both a
    no-group student and a member of a teacher-less non-archived group."""
    course = submission.unit.course
    teachers = teachers_for(submission.student, course)
    if teachers:
        return teachers
    owner = course.owner
    return [owner] if owner is not None else []
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest notifications/tests/test_recipients.py -q` → PASS. Then ruff check + format.

- [ ] **Step 5: Commit**

```bash
git add notifications/recipients.py notifications/tests/test_recipients.py
git commit -m "feat(notifications): teachers_for + review_recipients resolution"
```

---

### Task 4: `notify_needs_review` emit helper

**Files:**
- Modify: `notifications/services.py`
- Create: `notifications/tests/test_emit_review.py`

**Interfaces:**
- Consumes: `courses.review.submission_review_state`; `notifications.recipients.review_recipients`.
- Produces: `notify_needs_review(submission, actor) -> None` — no-op when `submission_review_state(submission)["total"] == 0`; otherwise one `notify()` per `review_recipients(submission)` with `kind=QUIZ_NEEDS_REVIEW`, `target=submission`, `actor=actor`, and the needs-review `data` payload. The `recipient == actor` guard in `notify()` self-suppresses the acting teacher.

- [ ] **Step 1: Write the failing test**

`notifications/tests/test_emit_review.py`:
```python
from decimal import Decimal

import pytest

from courses.models import Element, ExtendedResponseQuestionElement, QuestionElement
from notifications import services
from notifications.models import Notification
from tests.factories import (
    CourseFactory,
    GroupFactory,
    GroupMembershipFactory,
    QuizSubmissionFactory,
    UserFactory,
    make_quiz_unit,
)

pytestmark = pytest.mark.django_db


def _review_q(unit, *, max_marks="5"):
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss.",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal(max_marks),
    )
    return Element.objects.create(unit=unit, content_object=q)


def _student_in_group(course, teachers):
    student = UserFactory()
    group = GroupFactory(course=course)
    for t in teachers:
        group.teachers.add(t)
    GroupMembershipFactory(group=group, student=student)
    return student


def test_notify_needs_review_fans_out_to_group_teachers():
    course = CourseFactory()
    t1, t2 = UserFactory(), UserFactory()
    student = _student_in_group(course, [t1, t2])
    sub = QuizSubmissionFactory(student=student, unit=make_quiz_unit(course=course))
    _review_q(sub.unit)

    services.notify_needs_review(sub, actor=student)

    recipients = set(
        Notification.objects.filter(kind=Notification.Kind.QUIZ_NEEDS_REVIEW)
        .values_list("recipient", flat=True)
    )
    assert recipients == {t1.pk, t2.pk}
    row = Notification.objects.filter(recipient=t1).get()
    assert row.data["student_name"] == str(student)
    assert row.data["course_slug"] == course.slug
    assert row.target_id == sub.pk


def test_notify_needs_review_noop_without_review_question():
    course = CourseFactory()
    t1 = UserFactory()
    student = _student_in_group(course, [t1])
    sub = QuizSubmissionFactory(student=student, unit=make_quiz_unit(course=course))
    # No [R] question on the unit.
    services.notify_needs_review(sub, actor=student)
    assert Notification.objects.count() == 0


def test_notify_needs_review_suppresses_acting_teacher():
    course = CourseFactory()
    t1, t2 = UserFactory(), UserFactory()
    student = _student_in_group(course, [t1, t2])
    sub = QuizSubmissionFactory(student=student, unit=make_quiz_unit(course=course))
    _review_q(sub.unit)
    # t1 force-submits: they should NOT notify themselves, but t2 should be notified.
    services.notify_needs_review(sub, actor=t1)
    recipients = set(
        Notification.objects.values_list("recipient", flat=True)
    )
    assert recipients == {t2.pk}
```

> `make_quiz_unit(course=course)` builds the quiz unit on the target course (see the I2 note in Task 3 — `unit__course=` is silently ignored).

- [ ] **Step 2: Run it — expect FAIL** (`services` has no `notify_needs_review`).

Run: `uv run pytest notifications/tests/test_emit_review.py -q`

- [ ] **Step 3: Add `notify_needs_review` to `notifications/services.py`**

Append:
```python
def notify_needs_review(submission, actor):
    """Fan a quiz-needs-review notification out to the front-line teachers of the
    submitting student's group(s), or the course owner fallback. No-op when the
    unit has no [R] questions. Call inside the caller's atomic block, only on the
    not-SUBMITTED -> SUBMITTED transition branch (the guard lives at the call site)."""
    from courses.review import submission_review_state

    from notifications.recipients import review_recipients

    if submission_review_state(submission)["total"] == 0:
        return
    course = submission.unit.course
    data = {
        "course_title": course.title,
        "course_slug": course.slug,
        "unit_title": submission.unit.title,
        # carried for parity with quiz_graded; this kind's link uses target_id, not node_pk
        "node_pk": submission.unit_id,
        "student_name": str(submission.student),
    }
    for teacher in review_recipients(submission):
        notify(
            recipient=teacher,
            kind=Notification.Kind.QUIZ_NEEDS_REVIEW,
            target=submission,
            actor=actor,
            data=data,
        )
```

> `submission_review_state` is imported function-locally: `courses.review` will import `notifications.services` function-locally in Task 6, so a module-level import here would risk a cycle.

- [ ] **Step 4: Run tests — expect PASS.** Then ruff check + format.

- [ ] **Step 5: Commit**

```bash
git add notifications/services.py notifications/tests/test_emit_review.py
git commit -m "feat(notifications): notify_needs_review fan-out helper"
```

---

### Task 5: `notify_graded` + `notify_enrolled` emit helpers

**Files:**
- Modify: `notifications/services.py`
- Create: `notifications/tests/test_emit_helpers.py`

**Interfaces:**
- Produces:
  - `notify_graded(submission, reviewer) -> None` — one `notify()` to `submission.student`, `kind=QUIZ_GRADED`, `target=submission`, `actor=reviewer`, payload `{course_title, course_slug, unit_title, node_pk}`.
  - `notify_enrolled(student, course) -> None` — one `notify()` to `student`, `kind=ENROLLED`, `target=course`, `actor=None`, payload `{course_title, course_slug}`.

- [ ] **Step 1: Write the failing test**

`notifications/tests/test_emit_helpers.py`:
```python
import pytest

from notifications import services
from notifications.models import Notification
from tests.factories import CourseFactory, QuizSubmissionFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_notify_graded_targets_student():
    reviewer = UserFactory()
    sub = QuizSubmissionFactory()
    services.notify_graded(sub, reviewer)
    n = Notification.objects.get(kind=Notification.Kind.QUIZ_GRADED)
    assert n.recipient == sub.student
    assert n.actor == reviewer
    assert n.target_id == sub.pk
    assert n.data["course_slug"] == sub.unit.course.slug
    assert n.data["node_pk"] == sub.unit_id


def test_notify_enrolled_targets_student_with_null_actor():
    student = UserFactory()
    course = CourseFactory()
    services.notify_enrolled(student, course)
    n = Notification.objects.get(kind=Notification.Kind.ENROLLED)
    assert n.recipient == student
    assert n.actor is None
    assert n.target_id == course.pk
    assert n.data == {"course_title": course.title, "course_slug": course.slug}
```

- [ ] **Step 2: Run it — expect FAIL.**

Run: `uv run pytest notifications/tests/test_emit_helpers.py -q`

- [ ] **Step 3: Add both helpers to `notifications/services.py`**

```python
def notify_graded(submission, reviewer):
    course = submission.unit.course
    notify(
        recipient=submission.student,
        kind=Notification.Kind.QUIZ_GRADED,
        target=submission,
        actor=reviewer,
        data={
            "course_title": course.title,
            "course_slug": course.slug,
            "unit_title": submission.unit.title,
            "node_pk": submission.unit_id,
        },
    )


def notify_enrolled(student, course):
    notify(
        recipient=student,
        kind=Notification.Kind.ENROLLED,
        target=course,
        actor=None,
        data={"course_title": course.title, "course_slug": course.slug},
    )
```

- [ ] **Step 4: Run tests — expect PASS.** Then ruff check + format.

- [ ] **Step 5: Commit**

```bash
git add notifications/services.py notifications/tests/test_emit_helpers.py
git commit -m "feat(notifications): notify_graded + notify_enrolled helpers"
```

---

### Task 6: Wire `quiz_needs_review` into the two submit paths

**Files:**
- Modify: `courses/views.py` (`quiz_finish`, ~line 620), `courses/review.py` (`force_submit_quiz`, ~line 62)
- Create: `notifications/tests/test_wire_review.py`

**Interfaces:**
- Consumes: `notifications.services.notify_needs_review`.
- The emit sits **inside** each existing `transaction.atomic()` block, on the branch that performed the not-SUBMITTED → SUBMITTED transition.

- [ ] **Step 1: Write the failing integration test**

`notifications/tests/test_wire_review.py`:
```python
from decimal import Decimal

import pytest

from courses import review as review_svc
from courses.models import (
    Element,
    ExtendedResponseQuestionElement,
    QuestionElement,
    QuizSubmission,
)
from notifications.models import Notification
from tests.factories import (
    CourseFactory,
    GroupFactory,
    GroupMembershipFactory,
    QuizSubmissionFactory,
    UserFactory,
    make_quiz_unit,
)

pytestmark = pytest.mark.django_db


def _review_q(unit):
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss.", required_keywords="", forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW, max_marks=Decimal("5"),
    )
    return Element.objects.create(unit=unit, content_object=q)


def _setup(course=None, teachers=()):
    course = course or CourseFactory()
    student = UserFactory()
    group = GroupFactory(course=course)
    for t in teachers:
        group.teachers.add(t)
    GroupMembershipFactory(group=group, student=student)
    sub = QuizSubmissionFactory(
        student=student,
        unit=make_quiz_unit(course=course),
        status=QuizSubmission.Status.IN_PROGRESS,
    )
    _review_q(sub.unit)
    return course, student, sub


def test_force_submit_quiz_emits_needs_review():
    t1 = UserFactory()
    outsider = UserFactory()
    _, student, sub = _setup(teachers=[t1])
    review_svc.force_submit_quiz(sub, by=outsider)
    assert Notification.objects.filter(
        kind=Notification.Kind.QUIZ_NEEDS_REVIEW, recipient=t1
    ).count() == 1


def test_force_submit_already_submitted_does_not_renotify():
    t1 = UserFactory()
    outsider = UserFactory()
    _, student, sub = _setup(teachers=[t1])
    review_svc.force_submit_quiz(sub, by=outsider)
    review_svc.force_submit_quiz(sub, by=outsider)  # now SUBMITTED → early return
    assert Notification.objects.filter(
        kind=Notification.Kind.QUIZ_NEEDS_REVIEW, recipient=t1
    ).count() == 1
```

- [ ] **Step 2: Run it — expect FAIL** (no notification created yet).

Run: `uv run pytest notifications/tests/test_wire_review.py -q`

- [ ] **Step 3: Wire `force_submit_quiz`**

In `courses/review.py`, inside `force_submit_quiz`, after the progress block, still inside the `with transaction.atomic():`:
```python
        if not progress.completed:
            progress.completed = True
            progress.save()
        from notifications.services import notify_needs_review

        notify_needs_review(locked, actor=by)
```

- [ ] **Step 4: Wire `quiz_finish`**

In `courses/views.py`, inside `quiz_finish`, inside the `if submission.status != QuizSubmission.Status.SUBMITTED:` branch, after the progress block (still inside `with transaction.atomic():`):
```python
            if not progress.completed:
                progress.completed = True
                progress.save()
            from notifications.services import notify_needs_review

            notify_needs_review(submission, actor=request.user)
```

- [ ] **Step 5: Run tests — expect PASS.** Also run the existing courses suite to catch regressions: `uv run pytest courses/ notifications/ -q`. Then ruff check + format.

- [ ] **Step 6: Add the bulk-path + student-path coverage**

Append to `notifications/tests/test_wire_review.py`:
```python
def test_force_submit_all_covers_each_student(client):
    from courses.models import Enrollment
    from django.contrib.auth.models import Group as AuthGroup
    from django.urls import reverse
    from institution.roles import PLATFORM_ADMIN, seed_roles
    from tests.factories import make_verified_user

    seed_roles()
    course = CourseFactory()
    t1 = UserFactory()
    _, s1, sub1 = _setup(course=course, teachers=[t1])
    # second student in the same course/group set
    _, s2, sub2 = _setup(course=course, teachers=[t1])
    # force_submit_all filters candidates to reviewable_students, which for a PA is
    # Enrollment.objects.filter(course=...). GroupMembershipFactory creates NO enrollment
    # row, so the students must be enrolled explicitly or the view force-submits nothing.
    Enrollment.objects.create(student=s1, course=course, source="group")
    Enrollment.objects.create(student=s2, course=course, source="group")
    pa = make_verified_user(username="pa_force", email="pa_force@test.example.com")
    pa.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    client.force_login(pa)
    # Route name is `manage_review_force_submit_all` (courses/urls.py). Each _setup
    # built its own unit, so force-submit per unit.
    client.post(reverse("courses:manage_review_force_submit_all", kwargs={"slug": course.slug, "unit_pk": sub1.unit_id}))
    client.post(reverse("courses:manage_review_force_submit_all", kwargs={"slug": course.slug, "unit_pk": sub2.unit_id}))
    # kind-filtered, so the `enrolled` rows above don't interfere.
    assert Notification.objects.filter(kind=Notification.Kind.QUIZ_NEEDS_REVIEW).count() == 2


def test_quiz_finish_by_student_emits_needs_review(client):
    """The spec's PRIMARY trigger: a student finishing a quiz with an [R] question
    notifies their group teacher(s), through the real quiz_finish view."""
    from django.contrib.auth.models import Group as AuthGroup
    from django.urls import reverse
    from institution.roles import STUDENT, seed_roles
    from tests.factories import make_login

    from courses.models import Enrollment

    seed_roles()
    course = CourseFactory()
    t1 = UserFactory()
    unit = make_quiz_unit(course=course)
    _review_q(unit)
    group = GroupFactory(course=course)
    group.teachers.add(t1)
    student = make_login(client, "qf_student")  # verified user + logged in
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    GroupMembershipFactory(group=group, student=student)
    # quiz_finish guards on is_enrolled(student, course) (courses/views.py:625).
    Enrollment.objects.create(student=student, course=course, source="group")

    url = reverse("courses:quiz_finish", kwargs={"slug": course.slug, "node_pk": unit.pk})
    client.post(url)  # IN_PROGRESS -> SUBMITTED transition (get_or_create makes the submission)
    assert Notification.objects.filter(
        kind=Notification.Kind.QUIZ_NEEDS_REVIEW, recipient=t1
    ).count() == 1
    client.post(url)  # already SUBMITTED -> no re-notify
    assert Notification.objects.filter(
        kind=Notification.Kind.QUIZ_NEEDS_REVIEW, recipient=t1
    ).count() == 1
```

> `quiz_finish` is `@require_POST @login_required`; it `get_or_create`s the submission (default `IN_PROGRESS`), so no pre-created submission is needed. `make_login` returns a verified, logged-in user. The `[R]` question makes `submission_review_state["total"] > 0`, so the emit fires; the second POST hits the `status == SUBMITTED` early path and does not re-notify (transition guard at the call site).

> `_setup` builds a distinct unit per student. The bulk view is per-unit, so we POST once per unit. The students are enrolled explicitly because `force_submit_all` scopes candidates to `reviewable_students`, which for a PA is `Enrollment.objects.filter(course=...)` — `GroupMembershipFactory` alone creates no enrollment row. (The PA permission is not the issue; the students being unenrolled would be.)

- [ ] **Step 7: Run the new tests (bulk + student `quiz_finish`) — expect PASS.** Run `uv run pytest notifications/tests/test_wire_review.py -q`. Then ruff check + format.

- [ ] **Step 8: Commit**

```bash
git add courses/views.py courses/review.py notifications/tests/test_wire_review.py
git commit -m "feat(notifications): emit quiz_needs_review on student + teacher submit"
```

---

### Task 7: Wire `quiz_graded` into `review_response`

**Files:**
- Modify: `courses/review.py` (`review_response`, ~line 17)
- Create: `notifications/tests/test_wire_graded.py`

**Interfaces:**
- Consumes: `notifications.services.notify_graded`; `courses.review.submission_review_state`.
- Fires exactly once on the `not fully_reviewed → fully_reviewed` transition, inside `review_response`'s atomic block.

- [ ] **Step 1: Write the failing test**

`notifications/tests/test_wire_graded.py`:
```python
from decimal import Decimal

import pytest

from courses import review as review_svc
from courses.models import Element, ExtendedResponseQuestionElement, QuestionElement
from notifications.models import Notification
from tests.factories import QuizSubmissionFactory, UserFactory

pytestmark = pytest.mark.django_db


def _review_q(unit, max_marks="5"):
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss.", required_keywords="", forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW, max_marks=Decimal(max_marks),
    )
    return Element.objects.create(unit=unit, content_object=q)


def test_completing_review_notifies_student_once():
    reviewer = UserFactory()
    sub = QuizSubmissionFactory()
    q1 = _review_q(sub.unit)
    q2 = _review_q(sub.unit)
    # Grade the first [R]: not fully reviewed yet → no notification.
    review_svc.review_response(
        submission=sub, element=q1, earned_marks=Decimal("3"), feedback="", reviewer=reviewer
    )
    assert Notification.objects.filter(kind=Notification.Kind.QUIZ_GRADED).count() == 0
    # Grade the second [R]: now fully reviewed → exactly one notification.
    review_svc.review_response(
        submission=sub, element=q2, earned_marks=Decimal("4"), feedback="", reviewer=reviewer
    )
    n = Notification.objects.get(kind=Notification.Kind.QUIZ_GRADED)
    assert n.recipient == sub.student


def test_re_editing_completed_review_does_not_renotify():
    reviewer = UserFactory()
    sub = QuizSubmissionFactory()
    q1 = _review_q(sub.unit)
    review_svc.review_response(
        submission=sub, element=q1, earned_marks=Decimal("3"), feedback="", reviewer=reviewer
    )
    assert Notification.objects.filter(kind=Notification.Kind.QUIZ_GRADED).count() == 1
    # Edit marks after completion: fully_reviewed → fully_reviewed, no re-notify.
    review_svc.review_response(
        submission=sub, element=q1, earned_marks=Decimal("5"), feedback="", reviewer=reviewer
    )
    assert Notification.objects.filter(kind=Notification.Kind.QUIZ_GRADED).count() == 1
```

- [ ] **Step 2: Run it — expect FAIL.**

Run: `uv run pytest notifications/tests/test_wire_graded.py -q`

- [ ] **Step 3: Wire `review_response`**

In `courses/review.py::review_response`, **leave the code above the `with transaction.atomic():` unchanged** — the `question = element.content_object` line, the three `ValueError` validations (element-is-a-question / element-on-this-unit / element-is-`[R]`), and the `assert Decimal("0") <= earned_marks <= question.max_marks` bounds guard all stay exactly as they are. Inside the atomic block, add only two things: capture the pre-state right after the `select_for_update` lock, and emit after the submission save. The block below shows the full atomic block with the two added lines (marked); the pre-atomic guards are omitted here only for brevity, not removed:
```python
    # (unchanged above: question = element.content_object; the 3 ValueError guards; the assert)
    with transaction.atomic():
        submission.__class__.objects.select_for_update().get(pk=submission.pk)
        was_fully = submission_review_state(submission)["fully_reviewed"]
        response, _ = QuestionResponse.objects.get_or_create(
            submission=submission,
            element=element,
            defaults={"latest_answer": None, "attempt_count": 0, "locked": True},
        )
        response.earned_marks = earned_marks
        response.fraction = (earned_marks / question.max_marks).quantize(Decimal("0.0001"))
        response.review_feedback = feedback or ""
        response.reviewed_at = timezone.now()
        response.reviewed_by = reviewer
        response.save()

        score, max_score = quiz_svc.compute_scores(submission.unit, submission)
        submission.score = score
        submission.max_score = max_score
        submission.save()

        if not was_fully and submission_review_state(submission)["fully_reviewed"]:
            from notifications.services import notify_graded

            notify_graded(submission, reviewer)
    return response
```

> `submission_review_state` is already defined in `courses/review.py`, so it's a plain in-module call. Only `notify_graded` uses a function-local import.

- [ ] **Step 4: Run tests — expect PASS.** Then `uv run pytest courses/ notifications/ -q` for regressions, ruff check + format.

- [ ] **Step 5: Commit**

```bash
git add courses/review.py notifications/tests/test_wire_graded.py
git commit -m "feat(notifications): emit quiz_graded on review completion"
```

---

### Task 8: Wire `enrolled` into `enroll_self` + `recompute_enrollment`

**Files:**
- Modify: `grouping/services.py` (`enroll_self` ~163, `recompute_enrollment` ~174)
- Create: `notifications/tests/test_wire_enrolled.py`

**Interfaces:**
- Consumes: `notifications.services.notify_enrolled`.
- Fires only on the newly-`created` enrollment branch; the `IntegrityError`-race branch is treated as not-created (no notify).

- [ ] **Step 1: Write the failing test**

`notifications/tests/test_wire_enrolled.py`:
```python
import pytest

from grouping import services as grouping_svc
from notifications.models import Notification
from tests.factories import (
    CourseFactory,
    GroupFactory,
    GroupMembershipFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def test_self_enroll_notifies_once_and_is_idempotent():
    student = UserFactory()
    course = CourseFactory()
    grouping_svc.enroll_self(student, course)
    grouping_svc.enroll_self(student, course)  # idempotent, no second row
    assert Notification.objects.filter(
        kind=Notification.Kind.ENROLLED, recipient=student
    ).count() == 1


def test_group_enrollment_notifies_and_resync_does_not():
    student = UserFactory()
    course = CourseFactory()
    group = GroupFactory(course=course)
    grouping_svc.add_students_to_group(group, [student])
    assert Notification.objects.filter(
        kind=Notification.Kind.ENROLLED, recipient=student
    ).count() == 1
    # Re-sync an already-enrolled student: no new notification.
    grouping_svc.recompute_enrollment(student, course)
    assert Notification.objects.filter(
        kind=Notification.Kind.ENROLLED, recipient=student
    ).count() == 1
```

- [ ] **Step 2: Run it — expect FAIL.**

Run: `uv run pytest notifications/tests/test_wire_enrolled.py -q`

- [ ] **Step 3: Wire `enroll_self`**

In `grouping/services.py::enroll_self`:
```python
def enroll_self(student, course):
    with transaction.atomic():
        enrollment, created = Enrollment.objects.get_or_create(
            student=student, course=course, defaults={"source": "self"}
        )
        if created:
            from notifications.services import notify_enrolled

            notify_enrolled(student, course)
    return enrollment
```

- [ ] **Step 4: Wire `recompute_enrollment`**

In `grouping/services.py::recompute_enrollment`, the create branch:
```python
    if reachable and enrollment is None:
        try:
            with transaction.atomic():  # savepoint: a racing create won't poison the batch
                _, created = Enrollment.objects.get_or_create(
                    student=student, course=course, defaults={"source": "group"}
                )
                if created:
                    from notifications.services import notify_enrolled

                    notify_enrolled(student, course)
        except IntegrityError:
            pass  # concurrent create won; leave its row untouched
```

- [ ] **Step 5: Run tests — expect PASS.** Then `uv run pytest grouping/ notifications/ -q` for regressions, ruff check + format.

- [ ] **Step 6: Commit**

```bash
git add grouping/services.py notifications/tests/test_wire_enrolled.py
git commit -m "feat(notifications): emit enrolled on self + group enrollment"
```

---

### Task 9: `notification_url` + views (list + mark) + URLs + template

**Files:**
- Modify: `notifications/services.py` (add `notification_url`), `config/urls.py`
- Create: `notifications/views.py`, `notifications/urls.py`, `notifications/templates/notifications/list.html`, `notifications/tests/test_views.py`
- Modify: `core/static/core/css/app.css` (list styles)

**Interfaces:**
- Consumes: `notifications.models.Notification`, `notifications.services`.
- Produces: `notification_url(notification) -> str | None`; views `notification_list` (name `notifications:list`), `mark_read` (name `notifications:mark_read`, `<int:pk>`), `mark_all_read` (name `notifications:mark_all_read`) — all three implemented here so the list template's `{% url %}` references resolve and the page renders green in this task. Task 10 adds the mark-behavior tests.

> **Why all three views here (round-1 C2):** the list template references `notifications:mark_read` / `notifications:mark_all_read`, and `mark_*` redirect to `notifications:list`. These routes are mutually dependent, so all three are declared together in this task; the page cannot render (and Task 9's `test_list_shows_only_own` cannot pass) without the mark routes existing. Task 10 is a test-only task that hardens the mark behavior.

- [ ] **Step 1: Write the failing test**

`notifications/tests/test_views.py`:
```python
import pytest
from django.urls import reverse

from notifications import services
from notifications.models import Notification
from tests.factories import (
    CourseFactory,
    QuizSubmissionFactory,
    UserFactory,
    make_login,
    make_quiz_unit,
)

pytestmark = pytest.mark.django_db


def test_url_reversal_per_kind():
    course = CourseFactory(slug="c1")
    sub = QuizSubmissionFactory(unit=make_quiz_unit(course=course))
    needs_review = Notification(
        kind=Notification.Kind.QUIZ_NEEDS_REVIEW, target_type="submission",
        target_id=sub.pk, data={"course_slug": "c1", "node_pk": sub.unit_id},
    )
    assert services.notification_url(needs_review) == reverse(
        "courses:manage_review_submission", kwargs={"slug": "c1", "submission_pk": sub.pk}
    )
    graded = Notification(
        kind=Notification.Kind.QUIZ_GRADED, target_type="submission", target_id=sub.pk,
        data={"course_slug": "c1", "node_pk": sub.unit_id},
    )
    assert services.notification_url(graded) == reverse(
        "courses:quiz_results", kwargs={"slug": "c1", "node_pk": sub.unit_id}
    )
    enrolled = Notification(
        kind=Notification.Kind.ENROLLED, target_type="course", target_id=course.pk,
        data={"course_slug": "c1"},
    )
    assert services.notification_url(enrolled) == reverse(
        "courses:course_outline", kwargs={"slug": "c1"}
    )


def test_url_none_when_slug_missing():
    n = Notification(
        kind=Notification.Kind.ENROLLED, target_type="course", target_id=1, data={}
    )
    assert services.notification_url(n) is None


def test_list_requires_login(client):
    resp = client.get(reverse("notifications:list"))
    assert resp.status_code in (302, 301)  # redirect to login


def test_list_shows_only_own(client):
    mine = make_login(client, "owner")
    other = UserFactory()
    course = CourseFactory()
    services.notify_enrolled(mine, course)
    services.notify_enrolled(other, course)
    resp = client.get(reverse("notifications:list"))
    assert resp.status_code == 200
    rows = resp.context["page"].object_list
    assert all(n.recipient_id == mine.pk for n in rows)
    assert len(rows) == 1
```

> The quiz unit is built with `make_quiz_unit(course=course)` (see the I2 note in Task 3 — `unit__course=` is silently ignored).

- [ ] **Step 2: Run it — expect FAIL.**

Run: `uv run pytest notifications/tests/test_views.py -q`

- [ ] **Step 3: Add `notification_url` to `notifications/services.py`**

```python
def notification_url(notification):
    """Reverse the target URL from denormalized `data` (no DB load). None when
    the identifiers are missing or the route can't be reversed."""
    from django.urls import NoReverseMatch, reverse

    data = notification.data or {}
    slug = data.get("course_slug")
    try:
        if notification.kind == Notification.Kind.QUIZ_NEEDS_REVIEW:
            return reverse(
                "courses:manage_review_submission",
                kwargs={"slug": slug, "submission_pk": notification.target_id},
            )
        if notification.kind == Notification.Kind.QUIZ_GRADED:
            return reverse(
                "courses:quiz_results",
                kwargs={"slug": slug, "node_pk": data.get("node_pk")},
            )
        if notification.kind == Notification.Kind.ENROLLED:
            return reverse("courses:course_outline", kwargs={"slug": slug})
    except NoReverseMatch:
        return None
    return None
```

- [ ] **Step 4: Write the view**

`notifications/views.py` (all three views — the list plus the two mark endpoints):
```python
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from notifications import services
from notifications.models import Notification

PAGE_SIZE = 25


@login_required
def notification_list(request):
    qs = Notification.objects.filter(recipient=request.user)
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    for n in page.object_list:
        n.url = services.notification_url(n)
    return render(request, "notifications/list.html", {"page": page})


def _redirect_to_list(request):
    url = reverse("notifications:list")
    page = request.GET.get("page") or request.POST.get("page")
    if page:
        url = f"{url}?page={page}"
    return redirect(url)


@login_required
@require_POST
def mark_read(request, pk):
    n = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if n.read_at is None:
        n.read_at = timezone.now()
        n.save(update_fields=["read_at"])
    return _redirect_to_list(request)


@login_required
@require_POST
def mark_all_read(request):
    Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(
        read_at=timezone.now()
    )
    return _redirect_to_list(request)
```

- [ ] **Step 5: Write the urls + wire the project urlconf**

`notifications/urls.py` (all three routes):
```python
from django.urls import path

from notifications import views

app_name = "notifications"

urlpatterns = [
    path("notifications/", views.notification_list, name="list"),
    path("notifications/<int:pk>/read/", views.mark_read, name="mark_read"),
    path("notifications/read-all/", views.mark_all_read, name="mark_all_read"),
]
```

In `config/urls.py`, add next to the notes include:
```python
    path("", include("notifications.urls")),
```

- [ ] **Step 6: Write the template**

`notifications/templates/notifications/list.html`:
```html
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<main class="notif-page">
  <header class="notif-page__head">
    <h1>{% trans "Notifications" %}</h1>
    {% if page.object_list %}
    <form method="post" action="{% url 'notifications:mark_all_read' %}?page={{ page.number }}">
      {% csrf_token %}
      <button type="submit" class="btn btn--sm">{% trans "Mark all read" %}</button>
    </form>
    {% endif %}
  </header>

  {% if page.object_list %}
  <ul class="notif-list">
    {% for n in page.object_list %}
    <li class="notif-row{% if not n.read_at %} notif-row--unread{% endif %}">
      <span class="notif-row__body">
        {% if n.kind == 'quiz_needs_review' %}
          {% blocktrans with student=n.data.student_name unit=n.data.unit_title %}{{ student }} submitted a quiz for review: {{ unit }}{% endblocktrans %}
        {% elif n.kind == 'quiz_graded' %}
          {% blocktrans with unit=n.data.unit_title %}Your quiz was graded: {{ unit }}{% endblocktrans %}
        {% elif n.kind == 'enrolled' %}
          {% blocktrans with course=n.data.course_title %}You were enrolled in {{ course }}{% endblocktrans %}
        {% endif %}
      </span>
      {% if n.url %}<a class="notif-row__link" href="{{ n.url }}">{% trans "Open" %}</a>{% endif %}
      {% if not n.read_at %}
      <form method="post" action="{% url 'notifications:mark_read' n.pk %}?page={{ page.number }}">
        {% csrf_token %}
        <button type="submit" class="btn btn--ghost btn--sm">{% trans "Mark read" %}</button>
      </form>
      {% endif %}
    </li>
    {% endfor %}
  </ul>

  {% if page.has_other_pages %}
  <nav class="notif-pager" aria-label="{% trans 'Pagination' %}">
    {% if page.has_previous %}<a href="?page={{ page.previous_page_number }}">{% trans "Previous" %}</a>{% endif %}
    <span>{% blocktrans with num=page.number total=page.paginator.num_pages %}Page {{ num }} of {{ total }}{% endblocktrans %}</span>
    {% if page.has_next %}<a href="?page={{ page.next_page_number }}">{% trans "Next" %}</a>{% endif %}
  </nav>
  {% endif %}
  {% else %}
  <p class="notif-empty">{% trans "You have no notifications." %}</p>
  {% endif %}
</main>
{% endblock %}
```

> All three routes (`list`, `mark_read`, `mark_all_read`) are declared in this task's `urls.py` (Step 5) and all three views exist (Step 4), so the template's `{% url %}` references resolve and `test_list_shows_only_own` renders green. `btn`/`btn--sm`/`btn--ghost` are existing classes in `app.css`.

- [ ] **Step 7: Add list styles to `core/static/core/css/app.css`**

Append (adapt tokens to the existing palette variables in `tokens.css`):
```css
.notif-page { max-width: 46rem; margin: 0 auto; padding: 1.5rem 1rem; }
.notif-page__head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.notif-list { list-style: none; margin: 1rem 0 0; padding: 0; }
.notif-row { display: flex; align-items: center; gap: .75rem; padding: .75rem .5rem; border-bottom: 1px solid var(--border-strong); }
.notif-row__body { flex: 1; }
.notif-row--unread { background: var(--surface-raised); }
.notif-row--unread .notif-row__body { font-weight: 600; }
.notif-empty { color: var(--text-secondary); margin-top: 2rem; }
.notif-pager { display: flex; gap: 1rem; align-items: center; margin-top: 1rem; }
```

- [ ] **Step 8: Run tests — expect PASS.**

Run: `uv run pytest notifications/tests/test_views.py -q` → PASS (all three routes exist, template renders). Then `uv run ruff check . && uv run ruff format .`.

- [ ] **Step 9: Commit**

```bash
git add notifications/ config/urls.py core/static/core/css/app.css
git commit -m "feat(notifications): list + mark views, url resolver, template, styles"
```

---

### Task 10: mark-read behavior tests

**Files:**
- Create: `notifications/tests/test_mark.py`

> The `mark_read` / `mark_all_read` views and routes were implemented in Task 9 (they had to be, so the list template could render). This task adds the behavior tests that guard them: self-scoping, 404 on a foreign pk, mark-all, POST-only, and the 302 redirect preserving `?page=`.

**Interfaces:**
- Consumes: `notifications:mark_read` (`<int:pk>`), `notifications:mark_all_read` (both from Task 9); `notifications.services.notify_enrolled`, `unread_count`.

- [ ] **Step 1: Write the tests**

> Note (round-1 C1): `notify_enrolled` returns `None` (its contract is `-> None`), so **do not** write `n = services.notify_enrolled(...)`. Fire the notification, then fetch the row via the ORM.

`notifications/tests/test_mark.py`:
```python
import pytest
from django.urls import reverse

from notifications import services
from notifications.models import Notification
from tests.factories import CourseFactory, UserFactory, make_login

pytestmark = pytest.mark.django_db


def test_mark_read_owner_only(client):
    mine = make_login(client, "owner")
    course = CourseFactory()
    services.notify_enrolled(mine, course)
    n = Notification.objects.get(recipient=mine)
    resp = client.post(reverse("notifications:mark_read", kwargs={"pk": n.pk}))
    assert resp.status_code == 302
    n.refresh_from_db()
    assert n.read_at is not None


def test_mark_read_foreign_is_404_and_untouched(client):
    make_login(client, "owner")
    other = UserFactory()
    course = CourseFactory()
    services.notify_enrolled(other, course)
    foreign = Notification.objects.get(recipient=other)
    resp = client.post(reverse("notifications:mark_read", kwargs={"pk": foreign.pk}))
    assert resp.status_code == 404
    foreign.refresh_from_db()
    assert foreign.read_at is None


def test_mark_all_read(client):
    mine = make_login(client, "owner")
    course = CourseFactory()
    services.notify_enrolled(mine, course)
    services.notify_enrolled(mine, course)
    resp = client.post(reverse("notifications:mark_all_read") + "?page=2")
    assert resp.status_code == 302
    assert resp["Location"].endswith("?page=2")
    assert services.unread_count(mine) == 0


def test_mark_get_not_allowed(client):
    mine = make_login(client, "owner")
    course = CourseFactory()
    services.notify_enrolled(mine, course)
    n = Notification.objects.get(recipient=mine)
    resp = client.get(reverse("notifications:mark_read", kwargs={"pk": n.pk}))
    assert resp.status_code == 405
```

- [ ] **Step 2: Run the tests — expect PASS** (the views already exist from Task 9).

Run: `uv run pytest notifications/tests/test_mark.py -q`
If any fail, the defect is in Task 9's mark views — fix there. Then `uv run ruff check . && uv run ruff format .`.

- [ ] **Step 3: Commit**

```bash
git add notifications/tests/test_mark.py
git commit -m "test(notifications): mark-read + mark-all-read behavior"
```

---

### Task 11: Nav unread badge (context processor + base template)

**Files:**
- Modify: `core/context_processors.py`, `config/settings/base.py` (register), `templates/base.html`, `core/static/core/css/app.css`
- Create: `notifications/tests/test_badge.py`

**Interfaces:**
- Produces: context var `notifications_unread` (int) for authenticated requests; absent for anonymous.

- [ ] **Step 1: Write the failing test**

`notifications/tests/test_badge.py`:
```python
import pytest
from django.urls import reverse

from notifications import services
from tests.factories import CourseFactory, make_login

pytestmark = pytest.mark.django_db


def test_badge_count_in_context_for_authenticated(client):
    user = make_login(client, "owner")
    course = CourseFactory()
    services.notify_enrolled(user, course)
    services.notify_enrolled(user, course)
    resp = client.get(reverse("courses:my_courses"))
    assert resp.context["notifications_unread"] == 2


def test_badge_absent_for_anonymous(client):
    resp = client.get(reverse("account_login"))
    assert "notifications_unread" not in resp.context or not resp.context.get(
        "notifications_unread"
    )
```

> If `courses:my_courses` requires extra setup, use any authenticated GET that renders `base.html` (e.g. `notifications:list`). Confirm the login URL name (`account_login` is allauth's default).

- [ ] **Step 2: Run it — expect FAIL** (no `notifications_unread` in context).

Run: `uv run pytest notifications/tests/test_badge.py -q`

- [ ] **Step 3: Add the context processor**

Append to `core/context_processors.py`:
```python
def notifications_badge(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from notifications.services import unread_count

    return {"notifications_unread": unread_count(user)}
```

- [ ] **Step 4: Register it**

In `config/settings/base.py`, add to `TEMPLATES[...]["OPTIONS"]["context_processors"]` after `"core.context_processors.user_roles"`:
```python
        "core.context_processors.notifications_badge",
```

- [ ] **Step 5: Add the nav link + badge**

In `templates/base.html`, add the link as a **persistently-visible top-level `app-nav__link`** for authenticated users — place it alongside the always-visible links (e.g. right after the "Courses" link), **NOT** inside the platform-admin "Admin" dropdown and not inside any collapsible/`perms`-gated group, so every role sees it and the e2e can click it at the test viewport:
```html
{% if user.is_authenticated %}
<a class="app-nav__link" href="{% url 'notifications:list' %}">
  {% trans "Notifications" %}
  {% if notifications_unread %}<span class="nav-badge">{{ notifications_unread }}</span>{% endif %}
</a>
{% endif %}
```
> The nav was recently reorganized (Admin dropdown + mobile hamburger). Keep this link in the top-level flow that stays visible on mobile, matching the existing always-on links like "Courses".

Add to `core/static/core/css/app.css`:
```css
.nav-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 1.25rem; height: 1.25rem; padding: 0 .35rem; margin-left: .35rem; border-radius: 999px; background: var(--primary); color: var(--on-primary, #fff); font-size: .75rem; font-weight: 600; }
```

- [ ] **Step 6: Run tests — expect PASS.** Then `uv run pytest -q` (full non-e2e suite) to catch base-template regressions. ruff check + format.

- [ ] **Step 7: Commit**

```bash
git add core/context_processors.py config/settings/base.py templates/base.html core/static/core/css/app.css notifications/tests/test_badge.py
git commit -m "feat(notifications): nav unread badge via context processor"
```

---

### Task 12: i18n (EN/PL) + compile

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Create: `notifications/tests/test_i18n.py`

- [ ] **Step 1: Write the failing test**

`notifications/tests/test_i18n.py`:
```python
import pytest
from django.utils import translation

from notifications.models import Notification

pytestmark = pytest.mark.django_db


def test_kind_labels_translated_to_polish():
    with translation.override("pl"):
        assert str(Notification.Kind.QUIZ_GRADED.label) == "Quiz oceniony"
        assert str(Notification.Kind.ENROLLED.label) == "Zapisano na kurs"
        assert str(Notification.Kind.QUIZ_NEEDS_REVIEW.label) == "Quiz wymaga sprawdzenia"
```

- [ ] **Step 2: Run it — expect FAIL** (labels still English under `pl`).

Run: `uv run pytest notifications/tests/test_i18n.py -q`

- [ ] **Step 3: Extract messages**

Run: `uv run python manage.py makemessages -l pl`
This adds the new msgids (Kind labels + template `{% blocktrans %}` strings) to `locale/pl/LC_MESSAGES/django.po`.

- [ ] **Step 4: Fill in the Polish translations**

Edit `locale/pl/LC_MESSAGES/django.po` — set these msgstr values and **clear any `#, fuzzy` flags** makemessages added (fuzzy entries are ignored at runtime), and verify machine-guesses:
```
msgid "Quiz needs review"        → msgstr "Quiz wymaga sprawdzenia"
msgid "Quiz graded"              → msgstr "Quiz oceniony"
msgid "Enrolled in course"       → msgstr "Zapisano na kurs"
msgid "Notifications"            → msgstr "Powiadomienia"
msgid "Mark all read"            → msgstr "Oznacz wszystkie jako przeczytane"
msgid "Mark read"                → msgstr "Oznacz jako przeczytane"
msgid "Open"                     → msgstr "Otwórz"
msgid "You have no notifications." → msgstr "Nie masz powiadomień."
msgid "Previous"                 → msgstr "Poprzednia"
msgid "Next"                     → msgstr "Następna"
msgid "Pagination"               → msgstr "Paginacja"
```
For the `{% blocktrans %}` msgids (with placeholders), set:
```
msgid "%(student)s submitted a quiz for review: %(unit)s"
msgstr "%(student)s przesłał(a) quiz do sprawdzenia: %(unit)s"

msgid "Your quiz was graded: %(unit)s"
msgstr "Twój quiz został oceniony: %(unit)s"

msgid "You were enrolled in %(course)s"
msgstr "Zapisano Cię na kurs %(course)s"

msgid "Page %(num)s of %(total)s"
msgstr "Strona %(num)s z %(total)s"
```
> Exact msgids for blocktrans are generated from the template; if makemessages produced slightly different placeholder names (e.g. `%(student)s`), match whatever it wrote. Grep the `.po` for the new msgids and confirm each has a non-fuzzy msgstr.

- [ ] **Step 5: Compile**

Run: `uv run python manage.py compilemessages -l pl`
Expected: writes `locale/pl/LC_MESSAGES/django.mo`.

- [ ] **Step 6: Run tests — expect PASS.** Then ruff check + format.

- [ ] **Step 7: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo notifications/tests/test_i18n.py
git commit -m "i18n(notifications): Polish translations for notifications UI"
```

---

### Task 13: End-to-end (real gestures) + final verification

**Files:**
- Create: `notifications/tests/test_e2e_notifications.py`

**Interfaces:**
- Consumes: the whole stack. Drives the real UI: an event fires → nav badge shows → open `/notifications/` → follow a link → mark read → badge decrements.

- [ ] **Step 1: Write the e2e test**

`notifications/tests/test_e2e_notifications.py`:
```python
"""Playwright e2e for notifications slice 1: event → badge → page → mark read.

Real browser gestures only (project lesson: e2e that bypasses the real gesture
ships broken UX green). Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest
from django.contrib.auth.models import Group as AuthGroup
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_enrolled_notification_visible_and_markable(page, live_server):
    from courses.models import Course
    from grouping import services as grouping_svc
    from institution.roles import STUDENT, seed_roles
    from tests.factories import CourseFactory, make_verified_user

    seed_roles()
    course = CourseFactory(slug="e2e-notif", title="Astronomy")
    student = make_verified_user(
        username="e2e_notif_student", email="e2e_notif_student@test.example.com"
    )
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    # Fire an `enrolled` event via the real service.
    grouping_svc.enroll_self(student, course)

    _login(page, live_server, "e2e_notif_student")
    # Go straight to the notifications page — base.html renders the nav (and badge)
    # on every authenticated page, avoiding any assumption about what "/" shows.
    page.goto(f"{live_server.url}/notifications/")
    # Badge shows an unread count in the nav, and the row is visible.
    expect(page.locator(".nav-badge")).to_have_text("1")
    expect(page.locator(".notif-row")).to_contain_text("Astronomy")

    # Mark it read → redirect back to the list → badge gone.
    page.get_by_role("button", name="Mark read").first.click()
    expect(page.locator(".nav-badge")).to_have_count(0)
```

- [ ] **Step 2: Run the e2e test**

Run: `uv run pytest notifications/tests/test_e2e_notifications.py -m e2e -q`
Expected: PASS (a real browser drives login, badge, page, mark-read). If the nav link label differs, match the rendered `{% trans "Notifications" %}` text.

- [ ] **Step 3: Screenshot light + dark (throwaway) and self-review**

Write a short throwaway Playwright script (delete after) that logs in a user with a couple of notifications, opens `/notifications/`, and screenshots in light and dark theme. Confirm: unread rows distinct, badge legible on the nav, empty state styled, no undefined-class fallout. Fix any styling gaps in `app.css`. (Per the verify-UI-with-screenshots convention.)

- [ ] **Step 4: Full verification**

Run:
- `uv run pytest -q` (full non-e2e suite) → all green.
- `uv run pytest -m e2e -q` (e2e suite) → green.
- `uv run ruff check .` and `uv run ruff format --check .` → clean.
- `uv run python manage.py makemigrations --check --dry-run` → no missing migrations.

- [ ] **Step 5: Commit**

```bash
git add notifications/tests/test_e2e_notifications.py core/static/core/css/app.css
git commit -m "test(notifications): e2e event → badge → page → mark read"
```

---

## Self-Review (author checklist — completed)

**Spec coverage:**
- §1 data model → Task 1. `data` payloads (slug/node_pk) → Tasks 4/5. Partial unread index → Task 1.
- §2 `notify()` + `_resolve_target` + read helpers → Task 2. `teachers_for`/fallback → Task 3. Emit helpers → Tasks 4/5. Emit wiring (3 sites, atomic, transition guard at call site, force_submit_all) → Tasks 6/7/8.
- §3 read tracking (`read_at`, mark one/all, routes, 302 preserving `?page`) → Tasks 9/10.
- §4 UI (list, pagination, links keyed on kind, badge) → Tasks 9/11.
- §5 permissions/scoping (self-only, 404 on foreign) → Tasks 9/10.
- §6 i18n → Task 12.
- §7 retention → intentionally no code (documented non-goal).
- §8 testing (all enumerated cases) → distributed across Tasks 3–13; e2e → Task 13.
- §9 DoD → Task 13 Step 4.

**Placeholder scan:** no TBD/TODO; every code step shows real code. The two conditional notes (factory kwarg `unit__course=`; Task 9/10 route ordering) give explicit fallbacks, not placeholders.

**Type consistency:** `notify(*, recipient, kind, target, actor=None, data=None)` used identically everywhere; `notify_needs_review(submission, actor)`, `notify_graded(submission, reviewer)`, `notify_enrolled(student, course)`, `teachers_for(student, course)`, `review_recipients(submission)`, `notification_url(notification)` names match across definition and call sites. Kind string values (`"quiz_needs_review"`, `"quiz_graded"`, `"enrolled"`) match model choices and template branches.

**Known adaptation points for the implementer** (call out, not placeholders): the quiz unit is always built with `make_quiz_unit(course=course)` (`unit__course=` is silently ignored — round-1 I2); the bulk force-submit route is `courses:manage_review_force_submit_all` (round-1 I1); confirm `courses:my_courses` and `account_login` URL names for the badge test. `notify_enrolled`/`notify_graded` return `None` — tests fetch created rows via the ORM, never from the helper's return (round-1 C1).
