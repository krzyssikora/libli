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


def test_edit_link_is_a_sibling_of_the_tag_panel_not_a_child(client):
    """The Edit link must sit OUTSIDE <details class="unit-tags">.

    tags.js does panel.replaceWith(fresh) on the .unit-tags subtree when a tag is
    added, so a link inside the panel would be silently destroyed the first time
    the user tags a unit — with JS on only, passing every other server-side test.

    Do NOT reuse this module's _enrolled() helper: it builds a plain
    CourseFactory() with no owner, so the actor would not be a manager, step 1
    would fail, and the test would read as broken rather than as guarding
    something.
    """
    import re

    from tests.factories import make_login

    # `reverse`, `ContentNodeFactory` and `CourseFactory` are already imported at
    # the top of this module; `make_login` is not (it imports make_verified_user).

    # make_login (not a bare UserFactory + force_login): allauth's
    # AccountMiddleware enforces mandatory email verification and redirects an
    # unverified session to verify-email BEFORE any template renders.
    user = make_login(client, "containment")
    course = CourseFactory(owner=user)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    href = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})

    # 1. Plain URL, no ?panel=tags. Anchor the negative to a proven positive.
    resp = client.get(f"/courses/{course.slug}/u/{unit.pk}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert href in body, "editor link absent — the rest of this test is vacuous"

    # 2. Regex, not a literal: the partial emits
    #    <details class="unit-tags" {% if tags_panel_open %}open{% endif %}>,
    #    so the rendered markup is always `class="unit-tags" >` (trailing space)
    #    or `class="unit-tags" open>`. A naive literal never matches, and a
    #    str.find() without a -1 check would slice garbage and pass vacuously in
    #    BOTH the healthy and the regressed state.
    panel = re.search(r'<details class="unit-tags"[^>]*>.*?</details>', body, re.DOTALL)
    assert panel, "could not locate the tag panel in the rendered page"

    # 3. Negative half: the link is not inside the panel.
    assert href not in panel.group(0)

    # 4. Positive half. Without this, moving the anchor out of .unit-strip
    #    entirely (below .unit-shell, or as a sibling of the strip) leaves steps
    #    1-3 green while destroying the flex row.
    #    Order matters and the obvious phrasing is backwards: the anchor FOLLOWS
    #    </details>, so the href's index is GREATER than the panel's end.
    strip_start = body.index('<div class="unit-strip"')
    shell_start = body.index('<div class="unit-shell"')
    assert strip_start < panel.end() <= body.index(href) < shell_start
