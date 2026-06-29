import pytest
from django.urls import reverse

from courses.models import Enrollment
from tags import services
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import UserFactory
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _enrolled(user, **kw):
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    return ContentNodeFactory(course=course, **kw)


def _user(n=0):
    """Verified user — force_login works with allauth's AccountMiddleware."""
    return make_verified_user(
        username=f"consumer{n}", email=f"consumer{n}@test.example.com"
    )


def test_lesson_page_shows_existing_tag(client):
    user = _user(0)
    client.force_login(user)
    unit = _enrolled(user)
    services.tag_unit(user, unit, "exam")
    resp = client.get(reverse("courses:lesson_unit", args=[unit.course.slug, unit.pk]))
    assert b"exam" in resp.content


def test_quiz_page_renders_tag_panel(client):
    user = _user(1)
    client.force_login(user)
    quiz = _enrolled(user, unit_type="quiz")
    resp = client.get(reverse("courses:quiz_unit", args=[quiz.course.slug, quiz.pk]))
    assert resp.status_code == 200
    assert b"unit-tags" in resp.content


def test_panel_open_flag(client):
    user = _user(2)
    client.force_login(user)
    unit = _enrolled(user)
    resp = client.get(
        reverse("courses:lesson_unit", args=[unit.course.slug, unit.pk]) + "?panel=tags"
    )
    assert resp.context["tags_panel_open"] is True


def test_submitted_quiz_shows_panel_on_results(client):
    """A submitted quiz redirects to quiz_results; the panel must live there."""
    from courses.models import QuizSubmission

    user = _user(3)
    client.force_login(user)
    quiz = _enrolled(user, unit_type="quiz")
    QuizSubmission.objects.create(
        student=user, unit=quiz, status=QuizSubmission.Status.SUBMITTED
    )
    # quiz_unit?panel=tags forwards to quiz_results?panel=tags
    resp = client.get(
        reverse("courses:quiz_unit", args=[quiz.course.slug, quiz.pk]) + "?panel=tags",
        follow=True,
    )
    assert resp.status_code == 200
    assert b"unit-tags" in resp.content
    assert resp.context["tags_panel_open"] is True


def test_quiz_context_carries_tags_for_nojs_rerender():
    """build_quiz_context is the shared builder for quiz_unit AND the no-JS answer
    re-render (_quiz_render_feedback); the tag context must come from there, or a no-JS
    answer submit would re-render the panel with the quiz's tags dropped."""
    from courses.views import build_quiz_context  # defined in views.py (~line 354)

    user = UserFactory()
    quiz = _enrolled(user, unit_type="quiz")
    services.tag_unit(user, quiz, "revise")
    ctx = build_quiz_context(quiz, user)
    assert [t.name for t in ctx["unit_tags"]] == ["revise"]
    assert ctx["tags_panel_open"] is False  # closed by default; views override the flag
