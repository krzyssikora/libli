import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from courses.models import ContentNode
from tests.factories import CourseFactory
from tests.factories import DragToImageQuestionElementFactory
from tests.factories import DragZoneFactory
from tests.factories import MediaAssetFactory
from tests.factories import add_element
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _quiz_unit(course):
    return ContentNode.objects.create(
        course=course, kind="unit", unit_type="quiz", title="U"
    )


def _media_option_values(body):
    """The media select's option values -- the only place a MediaAsset pk belongs.

    Scoping to the select is load-bearing, not tidiness. This form renders
    `value="<int>"` from ten places: the element pk and the unit pk (five hidden
    inputs each, in the move forms), DragZone pks (`zones-0-id`), the zones
    formset's management counts (TOTAL/INITIAL/MIN/MAX = 1/1/0/1000), the plain
    `max_attempts` field, and the media options. `MediaAsset`, `ContentNode` and
    `Element` are independent pk sequences, so a bare
    `f'value="{pk}"' not in body` passes or fails on whether those sequences happen
    to have drifted apart -- which under `-n auto` depends on which other tests
    landed in the same worker.
    """
    select = BeautifulSoup(body, "html.parser").select_one('select[name="media"]')
    assert select is not None, "media select not rendered"
    return {o.get("value") for o in select.select("option")}


def test_open_add_form_scopes_media(client):
    make_pa(client)
    course = CourseFactory()
    unit = _quiz_unit(course)
    mine = MediaAssetFactory(course=course, kind="image")
    other = MediaAssetFactory(course=CourseFactory(), kind="image")
    # element_add is a POST view reading type + unit from POST (views_manage.py:772)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "dragtoimagequestion", "unit": unit.pk},
    )
    options = _media_option_values(resp.content.decode())
    assert str(mine.pk) in options
    assert str(other.pk) not in options
    assert "zones-TOTAL_FORMS" in resp.content.decode()  # formset wired in


def test_edit_open_form_scopes_media(client):
    make_pa(client)
    course = CourseFactory()
    unit = _quiz_unit(course)
    q = DragToImageQuestionElementFactory(
        media=MediaAssetFactory(course=course, kind="image")
    )
    DragZoneFactory(question=q, correct_label="A")
    el = add_element(unit, q)
    other = MediaAssetFactory(course=CourseFactory(), kind="image")
    # element_form is a GET view keyed by slug + element pk (views_manage.py:864)
    resp = client.get(
        reverse(
            "courses:manage_element_form",
            kwargs={"slug": course.slug, "pk": el.pk},
        )
    )
    body = resp.content.decode()
    options = _media_option_values(body)
    # Positive proof: the in-course media IS rendered (guards against a regression
    # that empties the queryset, which would pass the negative check vacuously).
    assert str(q.media.pk) in options
    assert str(other.pk) not in options
    assert "zones-TOTAL_FORMS" in body


def test_media_scoping_survives_a_pk_collision_with_the_unit(client):
    """The scoping assertions must read the media SELECT, not the whole page.

    `MediaAsset`, `ContentNode` and `Element` are independent pk sequences, and this
    form renders `value="<int>"` for the element pk, the unit pk, DragZone pks, the
    zones formset's management counts (0 / 1 / 1000) and the plain `max_attempts`
    field -- ten sources, one of which is the media select. So a bare
    `f'value="{other.pk}"' not in body` fails spuriously the moment a MediaAsset pk
    coincides with any of them, which is exactly what happens under `-n auto` when
    earlier tests in the same worker consume those sequences unevenly.

    This test forces that coincidence (`other.pk == unit.pk`) so the ambiguity is
    deterministic rather than waiting on CI to shuffle the sequences into it.
    """
    make_pa(client)
    course = CourseFactory()
    for _ in range(6):  # push the unit's pk clear of 1
        _quiz_unit(course)
    unit = _quiz_unit(course)
    q = DragToImageQuestionElementFactory(
        media=MediaAssetFactory(course=course, kind="image")
    )
    DragZoneFactory(question=q, correct_label="A")
    el = add_element(unit, q)

    filler = CourseFactory()
    while MediaAssetFactory(course=filler, kind="image").pk < unit.pk - 1:
        pass
    other = MediaAssetFactory(course=CourseFactory(), kind="image")
    assert other.pk == unit.pk, f"setup failed: {other.pk} != {unit.pk}"

    resp = client.get(
        reverse(
            "courses:manage_element_form",
            kwargs={"slug": course.slug, "pk": el.pk},
        )
    )
    options = _media_option_values(resp.content.decode())
    assert str(q.media.pk) in options
    assert str(other.pk) not in options
