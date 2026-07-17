import pytest
from django.urls import reverse

from courses.models import ContentNode
from courses.models import Enrollment
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _login(client, course):
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)
    return student


def test_lesson_page_links_to_the_reset_interstitial(client):
    course, unit = make_course_with_unit()
    _login(client, course)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert (
        reverse("courses:progress_reset", args=[course.slug, unit.pk])
        in r.content.decode()
    )


def test_outline_links_to_the_course_level_reset(client):
    course, _unit = make_course_with_unit()
    _login(client, course)
    r = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert (
        reverse("courses:progress_reset_course", args=[course.slug])
        in r.content.decode()
    )


def test_outline_links_reset_per_grouping_node(client):
    course, _unit = make_course_with_unit()
    ch = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.CHAPTER, title="c"
    )
    ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        parent=ch,
        unit_type=ContentNode.UnitType.LESSON,
        title="u",
    )
    _login(client, course)
    r = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert (
        reverse("courses:progress_reset", args=[course.slug, ch.pk])
        in r.content.decode()
    )


def test_editor_preview_markdone_is_inert(client):
    """Drive the REAL preview view as the course author.

    Calling el.render(..., slug=None, node_pk=None) directly would only prove that
    `{% url ... as %}` swallows NoReverseMatch -- it hand-passes the very Nones it
    claims to discover, so it would stay green even if _preview.html's context GAINED
    slug/node_pk. The claim under test is about the preview VIEW's context.
    """
    from django.urls import reverse

    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem
    from tests.factories import add_element
    from tests.factories import make_course_with_unit
    from tests.factories import make_verified_user

    author = make_verified_user(username="prevauth", email="prevauth@school.edu")
    course, unit = make_course_with_unit(owner=author)
    el = MarkDoneElement.objects.create(prompt="P")
    add_element(unit, el)
    MarkDoneItem.objects.create(element=el, content="a")
    client.force_login(author)
    r = client.get(reverse("courses:manage_editor", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    # eid is NON-zero here (the preview passes real join rows). What makes it inert is
    # the absent slug/node_pk -> empty save_url -> markdone.js no-ops on fetch("").
    assert 'data-markdone-url=""' in r.content.decode()
    # The [S1] entry asks for both halves: empty save_url AND no row created/written.
    from courses.models import UnitProgress

    assert not UnitProgress.objects.filter(unit=unit).exists()
