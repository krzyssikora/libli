import pytest
from django.urls import resolve
from django.urls import reverse

from courses.models import Enrollment
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login
from tests.factories import seed_roles

pytestmark = pytest.mark.django_db


def _course_with_chapter():
    course = CourseFactory()
    chapter = ContentNodeFactory(course=course, kind="chapter", parent=None, title="Ch")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="U"
    )
    return course, chapter, unit


def test_resolver_does_not_collide_with_course_slug():
    # /courses/n/12/ is three segments; courses/<slug>/ matches two. A course
    # slugged "n" must keep working.
    assert resolve("/courses/n/12/").view_name == "courses:node_permalink"
    assert resolve("/courses/n/").view_name == "courses:course_outline"


def test_lesson_unit_redirects_to_lesson_page(client):
    course, _chapter, unit = _course_with_chapter()
    user = make_login(client, "student")
    Enrollment.objects.create(student=user, course=course)
    resp = client.get(reverse("courses:node_permalink", kwargs={"node_pk": unit.pk}))
    assert resp.status_code == 302
    assert resp["Location"] == reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )


def test_quiz_unit_redirects_straight_to_quiz_in_one_hop(client):
    # Fixture pinned to NO submission: quiz_unit itself 302s to quiz_results for a
    # SUBMITTED submission, so a followed chain would fail for an unrelated reason.
    # Assert on the FIRST hop's Location.
    course = CourseFactory()
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Q"
    )
    user = make_login(client, "student")
    Enrollment.objects.create(student=user, course=course)
    resp = client.get(reverse("courses:node_permalink", kwargs={"node_pk": quiz.pk}))
    assert resp.status_code == 302
    assert resp["Location"] == reverse(
        "courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": quiz.pk}
    )


def test_chapter_redirects_to_outline_with_fragment(client):
    course, chapter, _unit = _course_with_chapter()
    user = make_login(client, "student")
    Enrollment.objects.create(student=user, course=course)
    resp = client.get(reverse("courses:node_permalink", kwargs={"node_pk": chapter.pk}))
    assert resp.status_code == 302
    expected = (
        reverse("courses:course_outline", kwargs={"slug": course.slug})
        + f"#node-{chapter.pk}"
    )
    assert resp["Location"] == expected


def test_missing_node_is_404(client):
    make_login(client, "someone")
    resp = client.get(reverse("courses:node_permalink", kwargs={"node_pk": 999999}))
    assert resp.status_code == 404


def test_inaccessible_course_is_404_not_403(client):
    # 404-before-403, matching get_node_or_404's documented convention. A 403 here
    # would make this the one route that answers "does node N exist?" for any
    # logged-in user -- a node/course enumeration oracle.
    course, _chapter, unit = _course_with_chapter()
    make_login(client, "outsider")
    resp = client.get(reverse("courses:node_permalink", kwargs={"node_pk": unit.pk}))
    assert resp.status_code == 404


def test_manager_who_is_not_an_accessor_gets_404(client):
    # Known, deliberate: can_manage_course (owner OR courses.change_course) and
    # can_access_course (staff OR owner OR enrolled OR teaches) are not nested. A PA
    # who is neither owner nor enrolled can author a link and then 404 on it. This is
    # pre-existing app-wide behaviour -- they cannot read ANY unit page -- pinned here
    # so it is a known behaviour rather than a surprise.
    from django.contrib.auth.models import Group as AuthGroup

    course, _chapter, unit = _course_with_chapter()
    seed_roles()
    user = make_login(client, "pa")
    user.groups.add(AuthGroup.objects.get(name="Platform Admin"))
    assert not user.is_staff
    resp = client.get(reverse("courses:node_permalink", kwargs={"node_pk": unit.pk}))
    assert resp.status_code == 404


def test_sanitiser_passes_internal_links_through_untouched():
    """The single assumption every other decision in part 1 rests on.

    No custom scheme, no marker class, href-prefix CSS -- all of it is justified by
    sanitize_html leaving a relative anchor alone. A future tightening of
    ALLOWED_ATTRIBUTES would silently void every stored link with nothing going red.
    The two negative rows are what the URL contract's rejections exist for.
    """
    from courses.sanitize import sanitize_html

    keeps = '<a href="/courses/n/12/">u</a>'
    assert sanitize_html(keeps) == keeps
    # Survives untouched -- an off-site link wearing a relative disguise, which is why
    # the dialog rejects it rather than trusting the sanitiser to.
    off_site = '<a href="//evil.com/x">x</a>'
    assert sanitize_html(off_site) == off_site
    # Stripped at SAVE, after the author saw a working-looking link -- which is why the
    # dialog rejects it up front instead.
    assert sanitize_html('<a href="javascript:alert(1)">j</a>') == "<a>j</a>"


def test_anonymous_is_redirected_to_login(client):
    course, _chapter, unit = _course_with_chapter()
    resp = client.get(reverse("courses:node_permalink", kwargs={"node_pk": unit.pk}))
    assert resp.status_code == 302
    assert "/login" in resp["Location"] or "accounts" in resp["Location"]
