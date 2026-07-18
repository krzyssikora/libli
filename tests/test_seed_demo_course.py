import pytest
from django.core.management import call_command


@pytest.fixture(autouse=True)
def _isolate_media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.mark.django_db
def test_seed_is_idempotent_and_builds_demo():
    from courses.models import Course
    from courses.models import Element
    from courses.models import Enrollment

    call_command("seed_demo_course")
    courses_after_first = Course.objects.count()
    elements_after_first = Element.objects.count()
    enrollments_after_first = Enrollment.objects.count()
    assert courses_after_first == 1
    assert elements_after_first >= 5  # all five element types at least once
    # rerun: no duplicates, no IntegrityError
    call_command("seed_demo_course")
    assert Course.objects.count() == courses_after_first
    assert Element.objects.count() == elements_after_first
    assert Enrollment.objects.count() == enrollments_after_first


@pytest.mark.django_db
def test_seed_creates_verified_ca_owner_and_students():
    from allauth.account.models import EmailAddress
    from django.contrib.auth import get_user_model

    from courses.models import Course

    call_command("seed_demo_course")
    User = get_user_model()

    teacher = User.objects.get(username="demo_teacher")
    assert teacher.is_staff is True
    assert teacher.theme == "light"
    assert teacher.language == "en"
    assert EmailAddress.objects.filter(
        user=teacher, verified=True, primary=True
    ).exists()

    course = Course.objects.get(slug="demo-course")
    assert course.owner_id == teacher.id  # builder access = can_manage_course(owner)

    for name in ("demo_student", "demo_s1", "demo_s2", "demo_s3"):
        u = User.objects.get(username=name)
        assert EmailAddress.objects.filter(user=u, verified=True).exists()


@pytest.mark.django_db
def test_seed_has_diverse_leaf_elements():
    from courses.models import CalloutElement
    from courses.models import SpoilerElement
    from courses.models import TableElement

    call_command("seed_demo_course")
    assert CalloutElement.objects.count() == 1
    assert SpoilerElement.objects.count() == 1
    assert TableElement.objects.count() == 1

    call_command("seed_demo_course")  # idempotent: still one of each
    assert CalloutElement.objects.count() == 1
    assert SpoilerElement.objects.count() == 1
    assert TableElement.objects.count() == 1


@pytest.mark.django_db
def test_seeded_ca_can_open_builder(client):
    # The whole PoC rests on the seeded CA being able to open the demo-course
    # builder. Pin it here (200, not 302/403) so a missing owner relationship
    # fails fast in CI instead of only as a capture selector timeout.
    from django.contrib.auth import get_user_model

    call_command("seed_demo_course")
    teacher = get_user_model().objects.get(username="demo_teacher")
    client.force_login(teacher)
    resp = client.get("/manage/courses/demo-course/build/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_seed_quiz_group_populate_analytics():
    from courses.models import ContentNode
    from courses.models import Course
    from courses.models import QuizSubmission
    from courses.rollups import build_results_matrix
    from courses.rollups import quiz_units_in_order
    from grouping.models import Group
    from grouping.models import GroupMembership

    call_command("seed_demo_course")
    course = Course.objects.get(slug="demo-course")

    quizzes = list(quiz_units_in_order(course))
    # Task 2 (slice-3 seed enrichment) added a second quiz unit ("Practice quiz")
    # to host the REVIEW flow separately from "Demo quiz" — see the seed's
    # handle() comment. Select "Demo quiz" explicitly by title below since
    # quiz_units_in_order's ordering between the two is not guaranteed.
    assert len(quizzes) == 2
    quiz = ContentNode.objects.get(course=course, title="Demo quiz")
    assert quiz.unit_type == "quiz"

    group = Group.objects.get(name="Demo Group", course=course)
    students = [m.student for m in GroupMembership.objects.filter(group=group)]
    assert len(students) == 3
    assert group.teachers.filter(username="demo_teacher").exists()

    # Every group member has a SUBMITTED, scored submission on the course gradeable
    # (the non-empty-intersection requirement — a populated matrix, not empty cells).
    for st in students:
        sub = QuizSubmission.objects.get(student=st, unit=quiz)
        assert sub.status == QuizSubmission.Status.SUBMITTED
        assert sub.max_score and sub.max_score > 0

    matrix = build_results_matrix(course, students, expanded=set(), values="percent")
    # "Demo quiz" is AUTO-only (the REVIEW question now lives on the separate
    # "Practice quiz"), so the group's fully-graded submissions populate the
    # percent matrix: at least one populated cell exists across the group×quiz
    # grid. Cells are dicts {"percent": .., "label": ..} (courses/rollups.py
    # _cell); a populated cell has a non-None percent.
    flat = [c for row in matrix["rows"] for c in row["cells"]]
    assert any(c["percent"] is not None for c in flat)


@pytest.mark.django_db
def test_seed_quiz_group_idempotent():
    from courses.models import QuizSubmission

    call_command("seed_demo_course")
    subs = QuizSubmission.objects.count()
    call_command("seed_demo_course")
    assert QuizSubmission.objects.count() == subs


@pytest.mark.django_db
def test_seed_materializes_demo_image_idempotently(settings, tmp_path):
    from courses.models import MediaAsset

    call_command("seed_demo_course")
    asset = MediaAsset.objects.get(original_filename="demo.png")
    assert asset.file  # a file is set
    assert asset.file.storage.exists(asset.file.name)  # and exists on disk
    assert asset.file.size > 0
    first_name = asset.file.name

    call_command("seed_demo_course")  # rerun
    asset.refresh_from_db()
    assert asset.file.name == first_name  # stable name, no demo_<rand>.png


@pytest.mark.django_db
def test_seed_creates_pa_and_review_and_collection():
    from django.contrib.auth import get_user_model

    from courses.models import ContentNode
    from courses.models import Element
    from courses.models import QuizSubmission
    from grouping.models import Cohort
    from grouping.models import Collection
    from notes.models import Note
    from tags.models import Tag

    call_command("seed_demo_course")
    User = get_user_model()

    admin = User.objects.get(username="demo_admin")
    assert admin.is_staff  # last_login is stamped at capture-time login, not seeded

    # The REVIEW question + demo_student's unreviewed submission live on the
    # separate "Practice quiz" unit, not "Demo quiz" (kept AUTO-only so its
    # analytics populate — see seed's handle() comment).
    review_quiz = ContentNode.objects.get(title="Practice quiz")
    assert Element.objects.filter(
        unit=review_quiz, content_type__model="extendedresponsequestionelement"
    ).exists()
    student = User.objects.get(username="demo_student")
    sub = QuizSubmission.objects.get(student=student, unit=review_quiz)
    assert sub.status == QuizSubmission.Status.SUBMITTED

    assert Collection.objects.filter(name="Demo Collection").count() == 1
    assert Cohort.objects.filter(name="Autumn 2026").exists()
    assert Note.objects.filter(author__username="demo_teacher").exists()
    assert Tag.objects.filter(author__username="demo_teacher", name="Revision").exists()


@pytest.mark.django_db
def test_seed_review_submission_is_in_review_queue():
    from django.contrib.auth import get_user_model

    from courses.models import Course
    from courses.review import pending_reviews_for

    call_command("seed_demo_course")
    User = get_user_model()
    teacher = User.objects.get(username="demo_teacher")
    course = Course.objects.get(slug="demo-course")
    pending = pending_reviews_for(teacher, course)
    assert pending["awaiting"], (
        "expected an awaiting-review submission for the queue shot"
    )


@pytest.mark.django_db
def test_seed_is_idempotent_second_run():
    from grouping.models import Collection

    call_command("seed_demo_course")
    call_command("seed_demo_course")  # must not raise / duplicate

    assert Collection.objects.filter(name="Demo Collection").count() == 1
