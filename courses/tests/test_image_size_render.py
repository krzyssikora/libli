import pytest

from courses.models import Element
from courses.models import ImageElement
from courses.models import MediaAsset
from courses.models import SpoilerElement
from tests.factories import add_element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _media(course):
    return MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )


def make_image(size, course=None):
    """A SAVED ImageElement — data-preview-el carries its pk, so it must exist."""
    if course is None:
        course, _unit = make_course_with_unit()
    return ImageElement.objects.create(media=_media(course), alt="a", size=size)


def render(el, *, element=None):
    return el.render(element=element)


@pytest.mark.parametrize("size", ["small", "medium", "large", "full"])
def test_figure_carries_its_preset_class(size):
    assert f"el--image--{size}" in render(make_image(size))


def test_figure_carries_the_preview_hook():
    el = make_image("medium")
    assert f'data-preview-el="{el.pk}"' in render(el)


def test_figure_does_not_carry_data_element_id():
    """Guards the progress.js invariant: [data-element-id] is queried unscoped on
    student pages and must stay top-level-only. See views.py:709-713."""
    assert "data-element-id" not in render(make_image("small"))


def test_nested_image_carries_the_hook_through_its_container():
    """Render the SPOILER, not the image, so this exercises a path the top-level test
    does not: the container's children-walk must emit the nested figure with its hook.

    Rendering `el` directly with `element=join` would NOT be that path —
    ElementBase.render feeds `element` only into _state_context's `eid`
    (models.py:371-385) and imageelement.html never reads `eid`, so that call is
    byte-identical to the top-level test and could not fail independently of it.

    `data-preview-el` is the IMAGE ELEMENT's pk at every depth (the same pk Task 2's
    `data-for-element` emits), never the Element join row's — assert both halves.
    """
    course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="s")
    sp_join = add_element(unit, sp)
    el = make_image("large", course=course)
    join = Element.objects.create(
        unit=unit, content_object=el, parent=sp_join, tab_id=SpoilerElement.SLOT_ID
    )
    html = sp.render(element=sp_join)
    assert "el--image--large" in html  # the child really rendered
    assert f'data-preview-el="{el.pk}"' in html  # ImageElement pk ...
    assert f'data-preview-el="{join.pk}"' not in html  # ... not the join pk


def test_a_nested_image_join_row_is_not_a_seen_id():
    """The nested image's ELEMENT join-row pk must be absent from the seen-set, which
    is what makes the data-element-id invariant above safe even if an attribute leaks.
    Note the two pk namespaces: `join.pk` here, `el.pk` in data-preview-el."""
    from courses.views import _seen_current_ids

    course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="s")
    sp_join = add_element(unit, sp)
    el = make_image("small", course=course)
    join = Element.objects.create(
        unit=unit, content_object=el, parent=sp_join, tab_id=SpoilerElement.SLOT_ID
    )
    seen = _seen_current_ids(unit)
    assert sp_join.pk in seen  # the top-level container IS reported
    assert join.pk not in seen  # its nested child is NOT
