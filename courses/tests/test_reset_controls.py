import pytest
from django.urls import reverse

from courses.models import ContentNode
from courses.models import Element
from courses.models import Enrollment
from courses.models import MarkDoneElement
from courses.models import ShortTextQuestionElement
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _login(client, course):
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)
    return student


def _reset_url(course, unit):
    return reverse("courses:progress_reset", args=[course.slug, unit.pk])


def test_lesson_page_links_to_the_reset_interstitial(client):
    # Now seeds a state-bearing element: the link is gated on the unit CONTAINING a
    # type that can persist practice state (spec D1). No MarkDoneItem rows needed --
    # the flag is type-based, not content-based.
    course, unit = make_course_with_unit()
    add_element(unit, MarkDoneElement.objects.create(prompt="P"))
    _login(client, course)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    assert _reset_url(course, unit) in r.content.decode()


def test_lesson_page_hides_the_reset_link_on_a_unit_with_no_stateful_element(client):
    # A text/video-only unit can hold nothing element_state ever stores, so reset is a
    # guaranteed no-op there and the link is not offered (spec §Purpose).
    course, unit = make_course_with_unit()
    add_element(unit, TextElement.objects.create(body="<p>hi</p>"))
    _login(client, course)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    body = r.content.decode()
    # The positive anchor matters: "URL absent" is also satisfied by a 302 to login, a
    # 403, a 404 or a 500 -- i.e. by every failure mode of the FIXTURE rather than of
    # the condition under test.
    assert r.status_code == 200
    assert reverse("courses:complete", args=[course.slug, unit.pk]) in body
    assert _reset_url(course, unit) not in body


def test_lesson_page_shows_the_reset_link_for_an_element_nested_in_a_tab(client):
    # Children of a Tabs join row keep their own `unit` FK, so the flag's query is FLAT
    # (not parent__isnull=True). Scoping it to top level would hide the link on a unit
    # whose only interactive content lives inside a tab.
    course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][0]["id"]
    Element.objects.create(
        unit=unit,
        content_object=MarkDoneElement.objects.create(prompt="P"),
        parent=join,
        tab_id=tab_id,
    )
    _login(client, course)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    assert _reset_url(course, unit) in r.content.decode()


def test_lesson_page_shows_the_reset_link_on_a_question_only_unit(client):
    # Covers the RESTORABLE_IN_LESSON half of the union. Every other render-level test
    # uses the validator half, so without this a bad implementation could drop questions
    # entirely and stay green. Seed NOTHING else -- the question must be the only
    # interactive element for this test's falsification to bite.
    course, unit = make_course_with_unit()
    add_element(unit, ShortTextQuestionElement.objects.create(stem="Q", accepted="x"))
    _login(client, course)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    assert _reset_url(course, unit) in r.content.decode()


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
