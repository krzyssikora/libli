import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from demo import errors

# Measured on the correct build, 2026-09-12, against the `small` fixture:
# a 5-pupil kit costs 897 queries and a 10-pupil kit 1581, so each additional
# pupil costs ~137. The two absolute ceilings below (1400 / 2400) are ~1.5x the
# measured totals and are a coarse backstop that also moves whenever the fixture
# grows a unit; `per_pupil` is the real test — it is what the design's whole
# "validate once, kit-wide" argument is about.
# ⚠️ A later breach means INVESTIGATING, not bumping the number.
MEASURED_PER_PUPIL = 137


@pytest.mark.django_db
def test_a_kit_provisions_a_teacher_a_student_and_pupils():
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course(), pupils=5)

    assert kit.users.count() == 7  # teacher + student + 5 pupils
    assert kit.teacher.is_staff and not kit.student.is_staff
    assert kit.group in kit.teacher.taught_groups.all()
    # Every user is in kit.users the moment it is created: R7 filters the
    # generator's writes by it and purge_kit's deletion set IS it.
    assert kit.teacher in kit.users.all()
    assert kit.student in kit.users.all()


@pytest.mark.django_db
def test_the_reps_student_can_reach_a_quiz_and_shows_a_human_name():
    """T20 — §1's requirement 2 has no other test. A Student that came out staff
    silently gets the read-only previewer instead of a real submission."""
    from courses.access import can_access_course
    from grouping.models import GroupMembership
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    kit = provision_for_test(course)

    assert not kit.student.is_staff
    assert GroupMembership.objects.filter(group=kit.group, student=kit.student).exists()
    assert can_access_course(kit.student, course)
    # The analytics templates render display_name|default:username and nothing
    # else, so a pupil without one shows as "sp-12-p01".
    pupil = kit.users.exclude(pk__in=[kit.teacher_id, kit.student_id]).first()
    assert pupil.display_name and " " in pupil.display_name


@pytest.mark.django_db
def test_passwords_authenticate_and_never_persist():
    """T22 — and the repr, since a dataclass repr would leak both into any
    traceback Django's error reporter renders."""
    from django.contrib.auth import authenticate

    from demo.services import provision_kit
    from tests.demo.fixtures import small_course

    course = small_course()
    with override_settings(VENDOR_INSTANCE=True):
        result = provision_kit("SP 12", course=course, days=14, pupils=5, seed=1)

    assert authenticate(
        username=result.kit.teacher.username, password=result.teacher_password
    )
    assert result.teacher_password not in repr(result)
    assert result.student_password not in repr(result)
    # Sweep EVERY string-valued column on the row, not just label/slug.
    # ⚠️ The old two-field loop was vacuous: `label` is operator input and `slug`
    # is derived from it, so neither could ever hold a freshly generated
    # 14-character secret — it was green on a build that added a
    # `teacher_password` column.
    result.kit.refresh_from_db()
    for f in result.kit._meta.get_fields():
        if not getattr(f, "concrete", False):
            continue
        value = getattr(result.kit, f.attname, None)
        if isinstance(value, str):
            assert result.teacher_password not in value, f.name
            assert result.student_password not in value, f.name


@pytest.mark.django_db
def test_every_pupil_holds_progress_and_a_scored_submission():
    """The post-generation invariant, satisfiable BY CONSTRUCTION (the forced
    first lesson and the reach-forward), not left to the dice."""
    from courses.models import QuizSubmission
    from courses.models import UnitProgress
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    kit = provision_for_test(small_course(), pupils=5)
    pupils = kit.users.exclude(pk__in=[kit.teacher_id, kit.student_id])
    for pupil in pupils:
        assert UnitProgress.objects.filter(student=pupil, completed=True).exists()
        assert (
            QuizSubmission.objects.filter(
                student=pupil, status=QuizSubmission.Status.SUBMITTED
            )
            .exclude(score=None)
            .exists()
        )


@pytest.mark.django_db
def test_bounds_and_preconditions_raise_named_errors():
    """T15b/T22 — enforced in the SERVICE, so PR 3's form inherits them.

    ⚠️ ONE import block. `with` creates no scope, so re-importing `DemoKit` or
    `small_course` beside the later cases puts two bindings in the same function
    scope — `F811 redefinition of unused ...`, a real lint failure that surfaces
    only at Final verification."""
    from courses.models import Course
    from demo.models import DemoKit
    from demo.services import provision_kit
    from tests.demo.fixtures import small_course

    course = small_course()
    with override_settings(VENDOR_INSTANCE=True):
        with pytest.raises(errors.InvalidBounds) as exc:
            provision_kit("SP", course=course, days=14, pupils=2, seed=1)
        assert exc.value.field == "pupils"

        with pytest.raises(errors.InvalidBounds):
            provision_kit("SP", course=course, days=0, pupils=5, seed=1)

        with pytest.raises(errors.InvalidLabel):
            provision_kit("   ", course=course, days=14, pupils=5, seed=1)

        empty = Course.objects.create(slug="empty", title="Empty", language="pl")
        with pytest.raises(errors.EmptyCourse):
            provision_kit("SP", course=empty, days=14, pupils=5, seed=1)

        # A course with units but NOTHING ANSWERABLE — caught up front, by the
        # course-shaped message, not by the per-pupil EmptyKit loop after every
        # row has been written. Assert on the empty DemoKit table: a late raise
        # also rolls back, so pytest.raises alone cannot tell them apart.
        prose_only = small_course(slug="prose-only", quiz_without_questions=True)
        prose_only.nodes.filter(unit_type="quiz").exclude(
            title="Prose-only quiz"
        ).update(published=False)
        before = DemoKit.objects.count()
        with pytest.raises(errors.EmptyCourse) as exc:
            provision_kit("SP", course=prose_only, days=14, pupils=5, seed=1)
        assert "quiz" in str(exc.value)
        assert DemoKit.objects.count() == before

        # frontier_part is validated UP FRONT, like days and pupils — not deep
        # inside generate() after every user has been written. Asserting on the
        # empty DemoKit table is what proves the check ran early; a late raise
        # still rolls back, so `pytest.raises` alone cannot tell the difference.
        before = DemoKit.objects.count()
        with pytest.raises(errors.InvalidFrontierPart) as exc:
            provision_kit(
                "SP", course=course, days=14, pupils=5, seed=1, frontier_part=99
            )
        assert exc.value.field == "frontier_part"  # it is an InvalidBounds
        assert DemoKit.objects.count() == before


@pytest.mark.django_db
def test_a_second_kit_for_the_same_school_gets_distinct_usernames():
    """T17 — a taken name BUMPS the integer; it is never adopted."""
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    first = provision_for_test(course, label="SP 12")
    second = provision_for_test(course, label="SP 12")

    assert first.teacher.username != second.teacher.username
    assert first.slug == second.slug  # the SLUG is deliberately not unique


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=False)
def test_provisioning_refuses_on_a_school_box():
    from demo.models import DemoKit
    from demo.services import provision_kit
    from tests.demo.fixtures import small_course

    course = small_course()
    with pytest.raises(ImproperlyConfigured):
        provision_kit("SP", course=course, days=14, pupils=5, seed=1)
    assert DemoKit.objects.count() == 0


@pytest.mark.django_db
def test_provisioning_is_silent(django_capture_on_commit_callbacks):
    """T12 — R6.

    ⚠️ TWO TRAPS, both of which made the earlier version of this test green on a
    build that mails the world.

    1. `mail.outbox == []` alone proves NOTHING here. provision_kit is
       @transaction.atomic and pytest-django rolls back, so the on_commit
       callbacks that actually send are DISCARDED, never run. The assertion is
       green whether or not the suppression exists. Hence
       `django_capture_on_commit_callbacks(execute=True)`, which runs them.
    2. The observable, transaction-independent fact is the Notification ROWS —
       assert on those too, because they are written synchronously and would show
       up in the demo Teacher's own bell menu.
    """
    from django.core import mail

    from integrations.models import WebhookDelivery
    from integrations.models import WebhookEndpoint
    from notifications.models import Notification
    from notifications.services import notify
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test
    from tests.factories import make_verified_user

    endpoint = WebhookEndpoint.load()
    endpoint.enabled = True
    endpoint.url = "https://sis.example/hook"
    endpoint.save()

    before = WebhookDelivery.objects.count()
    with django_capture_on_commit_callbacks(execute=True):
        result = provision_for_test(small_course(), full=True)

    assert mail.outbox == []
    assert not Notification.objects.filter(
        recipient__in=result.kit.users.all()
    ).exists(), "enrolment notifications leaked into the kit users' bell menus"

    # The mute is SCOPED, not global: it must be OFF again afterwards, or every
    # other request in this worker loses its notifications for the duration.
    # ⚠️ Assert on a real notify() call, not just on the flag — a module-attribute
    # swap that forgot to restore would leave the flag False and notify() dead.
    bystander = make_verified_user(username="bystander", email="b@example.com")
    assert (
        notify(
            recipient=bystander,
            kind=Notification.Kind.ENROLLED,
            target=result.kit.course,
            data={"course_title": "x", "course_slug": "small"},
        )
        is not None
    ), "notify() was still muted after provisioning returned"
    # ⚠️ The delivery count below is a REGRESSION GUARD ONLY, and is currently
    # vacuous: emit_result_finalized is called from courses/views.py and
    # courses/review.py, never from finalize_submission, so the generator's path
    # cannot create a WebhookDelivery on ANY build. Keep it for the day someone
    # routes the generator through the view layer — do not read it as live cover.
    assert WebhookDelivery.objects.count() == before
    # ...and the operator is TOLD the endpoint is live (it is a data-leak
    # surface the moment a rep presses Force submit).
    # ⚠️ This needs the FULL ProvisionResult. The old form asserted
    # `result_kit is not None` on the bare `.kit` — true on every build,
    # including one where _webhook_warnings() returns [] unconditionally, so the
    # half of the test its own comment describes was measuring nothing.
    hits = [w for w in result.warnings if w.kind == "active_webhook_endpoint"]
    assert len(hits) == 1
    assert hits[0].reason == endpoint.url


@pytest.mark.django_db
def test_the_review_queue_is_non_empty_for_the_kit_teacher():
    """T25 — §1's fourth requirement. MOVED HERE from Task 9 because it needs
    provision_kit; Task 9 keeps only the plan-level half so it can end green.

    pending_reviews_for filters on reviewable_students AND quiz_units_in_order,
    so a submission written for the wrong scope leaves the queue silently empty —
    asserting on the QuizSubmission table alone would not catch that, which is
    why the queue itself is queried.
    """
    from courses.models import QuizSubmission
    from courses.models import UnitProgress
    from courses.review import pending_reviews_for
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    kit = provision_for_test(course)

    queue = pending_reviews_for(kit.teacher, course, drafts="hide")
    assert queue["in_progress"], "the teacher's own queue, not just the table"
    # ⚠️ queue["awaiting"] is EXPECTED to be empty — any quiz holding a REVIEW
    # question is skipped whole (see Task 6's accepted consequence). Asserting it
    # non-empty would be red on correct code.

    in_progress = QuizSubmission.objects.filter(
        status=QuizSubmission.Status.IN_PROGRESS
    )
    assert in_progress.count() == 2  # IN_PROGRESS_PUPILS, by construction

    # R4's negative half: an unfinished quiz carries NO completed progress.
    for submission in in_progress:
        assert not UnitProgress.objects.filter(
            student=submission.student, unit=submission.unit, completed=True
        ).exists()

    # And it is only kit pupils.
    assert set(in_progress.values_list("student_id", flat=True)) <= set(
        kit.users.values_list("pk", flat=True)
    )


@pytest.mark.django_db
def test_the_demo_teacher_can_read_every_course_on_the_box():
    """⚠️ THIS TEST DOCUMENTS A KNOWN WIDENING, and is expected to PASS — read
    the note under Step 3 before changing it.

    `accessible_courses` (courses/access.py:22-23) returns Course.objects.all() for
    ANY is_staff user, and the demo Teacher receives is_staff=True from its
    TEACHER role — `set_user_role` derives the flag via `role_is_staff`, so this
    is not something _make_user chose. So a school rep's demo login can read every
    other course hosted on the vendor instance, including another school's kit.
    Pinning it here means the day someone narrows staff access, this test goes
    red and the narrowing is a deliberate decision rather than a surprise.
    """
    from courses.access import accessible_courses
    from courses.models import Course
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    course = small_course()
    other = Course.objects.create(slug="other", title="Other", language="pl")
    kit = provision_for_test(course)

    assert kit.teacher.is_staff
    assert other in accessible_courses(kit.teacher)
    # The rep's STUDENT login is correctly narrow — that half is not a widening.
    assert other not in accessible_courses(kit.student)


@pytest.mark.django_db
def test_provisioning_queries_do_not_scale_with_the_class(
    django_assert_max_num_queries,
):
    """The 20x multiplier this whole design removes lives in the PUPIL LOOP, so
    that is what has to be measured.

    ⚠️ `django_assert_max_num_queries`, NOT `django_assert_num_queries` — the
    latter wraps assertNumQueries and asserts EQUALITY (`exact=True`), so a
    ceiling written with it fails on correct code the moment the count is
    anything but the literal.

    ⚠️ And it must provision TWICE at different class sizes. A single
    `build_course_plan(course)` pin cannot see the regression it would be named
    for: that function takes no pupil count and touches no pupil, so
    reintroducing per-pupil mark() calls inside _answer_quiz leaves it green.
    """
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    # ⚠️ DISTINCT SLUGS. Course.slug is unique=True, so a second bare
    # small_course() raises IntegrityError and this test cannot run at all.
    small_five = small_course(slug="scale-5")
    with django_assert_max_num_queries(1400) as five:
        provision_for_test(small_five, label="Five", pupils=5)

    small_ten = small_course(slug="scale-10")
    with django_assert_max_num_queries(2400) as ten:
        provision_for_test(small_ten, label="Ten", pupils=10)

    # THE MARGINAL COST PER PUPIL — the quantity a per-pupil content pass
    # inflates. Measured on the correct build (see below) and pinned with
    # headroom.
    #
    # ⚠️ NOT A RATIO. `assert len(ten) < len(five) * 2.5` cannot fail for ANY
    # input: query cost is B + p*X (a fixed base plus a per-pupil term), so the
    # 5->10 ratio is (B + 10X)/(B + 5X), which is strictly less than 2 for every
    # B > 0 and approaches 2 only as B -> 0. Moving the content pass inside the
    # loop multiplies X — it does not make growth superlinear — so the ratio
    # stays under 2 either way and the guard is green on the broken build.
    per_pupil = (len(ten) - len(five)) / 5
    assert per_pupil <= MEASURED_PER_PUPIL * 1.5, (
        f"{per_pupil:.1f} queries per additional pupil vs a measured "
        f"{MEASURED_PER_PUPIL} — the content pass is running inside the loop"
    )


@pytest.mark.django_db
def test_wrong_answers_vary_between_pupils():
    """T28 — what PR 5's per-question view will render. Two guards, or the
    assertion is decided by the dice."""
    from courses.models import QuestionResponse
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test

    provision_for_test(small_course(), pupils=20, seed=99)

    by_element = {}
    for r in QuestionResponse.objects.filter(fraction=0):
        by_element.setdefault(r.element_id, []).append(repr(r.latest_answer))
    multi = [v for v in by_element.values() if len(v) >= 2]
    assert multi, "guard: at least one question must be wrong for >= 2 pupils"
    assert any(len(set(v)) >= 2 for v in multi), (
        "guard: at least two distinct stored wrong answers"
    )
