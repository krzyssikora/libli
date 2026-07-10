import pytest

from courses.models import Element
from courses.models import GalleryElement
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import make_course_with_unit
from tests.factories import make_image_asset
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def _tabs_with_child(unit, child_obj, tab_index=1):
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][tab_index]["id"]
    Element.objects.create(
        unit=unit, content_object=child_obj, parent=join, tab_id=tab_id
    )
    return tabs, join


def test_nested_child_is_not_a_top_level_lesson_block(client, django_user_model):
    from courses.views import build_lesson_context

    course, unit = make_course_with_unit()
    _tabs_with_child(unit, TextElement.objects.create(body="inside"))
    ctx = build_lesson_context(unit, django_user_model.objects.create(username="u"))
    assert len(ctx["elements"]) == 1  # the tabs element only
    assert all(el.parent_id is None for el in ctx["elements"])


def test_nested_child_is_not_a_top_level_editor_row():
    from courses.views_manage import _editor_rows

    course, unit = make_course_with_unit()
    _tabs_with_child(unit, TextElement.objects.create(body="inside"))
    join_rows, rows = _editor_rows(unit)
    assert len(join_rows) == 1
    assert all(j.parent_id is None for j in join_rows)


def test_has_math_recurses_into_a_nested_gallery_description(
    django_user_model, tmp_path, settings
):
    """A bare nested MathElement would pass even a naive isinstance() recursion.
    A gallery DESCRIPTION forces the per-type predicate path."""
    from courses.views import build_lesson_context

    course, unit = make_course_with_unit()
    a = make_image_asset(course, "x.png")
    b = make_image_asset(course, "y.png")
    gal = GalleryElement.objects.create(
        data={
            "desc_pos": "below",
            "images": [
                {"media": a.pk, "desc": r"\(x^2\)"},
                {"media": b.pk, "desc": ""},
            ],
        }
    )
    _tabs_with_child(unit, gal)
    ctx = build_lesson_context(unit, django_user_model.objects.create(username="m"))
    assert ctx["has_math"] is True


def test_a_unit_with_a_populated_tabs_element_can_still_complete():
    """The `seen` endpoint's `current` set must exclude nested children. The frontend
    only ever reports top-level .lesson-block ids, so a nested pk in `current` could
    never be satisfied and the unit would never complete."""
    from courses.views import _seen_current_ids

    course, unit = make_course_with_unit()
    tabs, join = _tabs_with_child(unit, TextElement.objects.create(body="inside"))
    current = _seen_current_ids(unit)
    assert current == {join.pk}, "a nested child's pk leaked into the completion set"


def test_quiz_has_math_recurses_into_a_nested_gallery_description(
    django_user_model,
):
    from courses.views import build_quiz_context

    course, _lesson = make_course_with_unit()
    unit = make_quiz_unit(course=course)  # the repo's real quiz-unit helper
    a = make_image_asset(course, "x.png")
    b = make_image_asset(course, "y.png")
    gal = GalleryElement.objects.create(
        data={
            "desc_pos": "below",
            "images": [
                {"media": a.pk, "desc": r"\(y^2\)"},
                {"media": b.pk, "desc": ""},
            ],
        }
    )
    _tabs_with_child(unit, gal)
    ctx = build_quiz_context(unit, django_user_model.objects.create(username="q"))
    assert ctx["has_math"] is True
