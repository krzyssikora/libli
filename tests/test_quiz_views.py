import pytest
from django.http import Http404

from courses.access import get_node_or_404
from courses.models import QuizSubmission
from tests.factories import ContentNodeFactory
from tests.factories import EnrollmentFactory
from tests.factories import ShortTextQuestionElement
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit


@pytest.mark.django_db
def test_require_quiz_404s_lesson():
    lesson = ContentNodeFactory(unit_type="lesson")
    with pytest.raises(Http404):
        get_node_or_404(
            lesson.pk, lesson.course.slug, require_unit=True, require_quiz=True
        )


@pytest.mark.django_db
def test_require_quiz_passes_quiz():
    quiz = make_quiz_unit()
    node = get_node_or_404(
        quiz.pk, quiz.course.slug, require_unit=True, require_quiz=True
    )
    assert node.pk == quiz.pk


def _quiz_with_question(client, enroll=True):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    if enroll:
        EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    el = add_element(unit, q)
    return user, unit, el


@pytest.mark.django_db
def test_quiz_unit_get_renders_and_creates_submission_for_enrolled(client):
    user, unit, el = _quiz_with_question(client)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/"
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"Finish quiz" in resp.content
    assert QuizSubmission.objects.filter(student=user, unit=unit).count() == 1


@pytest.mark.django_db
def test_quiz_unit_get_no_submission_for_unenrolled_preview(client):
    user, unit, el = _quiz_with_question(client, enroll=False)
    user.is_staff = True
    user.save()
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/"
    resp = client.get(url)
    assert resp.status_code == 200
    assert not QuizSubmission.objects.filter(unit=unit).exists()
    # Read-only preview: no Finish button, inputs disabled (no live forms that 403).
    assert b"Finish quiz" not in resp.content
    assert b"disabled" in resp.content


@pytest.mark.django_db
def test_quiz_unit_get_redirects_to_results_when_submitted(client):
    user, unit, el = _quiz_with_question(client)
    QuizSubmission.objects.create(student=user, unit=unit, status="submitted")
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/"
    resp = client.get(url)
    assert resp.status_code == 302
    assert resp.url.endswith("/results/")
