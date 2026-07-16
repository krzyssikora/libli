from decimal import Decimal

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import GuessNumberElement
from courses.models import TabsElement
from courses.models import TwoColumnElement
from courses.views import build_lesson_context
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _enrolled_lesson(client):
    """-> (course, unit, user). Copy test_context_stepper.py's _enrolled_lesson."""
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    return course, unit, user


def _lesson_with_gn(client, *, stem="{{42}}", success_message="", nest=None):
    """Seed a lesson holding one GuessNumberElement. -> (course, unit, user).

    nest=None      -> top-level
    nest="tab"     -> inside a TabsElement panel
    nest="column"  -> inside a TwoColumnElement column (parent=<2col join row>,
                      tab_id=<column id from its normalized ids>)
    """
    course, unit, user = _enrolled_lesson(client)
    gn = GuessNumberElement.objects.create(
        stem=stem,
        target=Decimal("42"),
        tolerance=Decimal("0"),
        success_message=success_message,
    )
    if nest is None:
        add_element(unit, gn)
    elif nest == "tab":
        tabs = TabsElement.objects.create(
            data={"tabs": [{"id": "t000001", "label": "One"}]}
        )
        parent = add_element(unit, tabs)
        Element.objects.create(
            unit=unit, content_object=gn, parent=parent, tab_id="t000001"
        )
    elif nest == "column":
        col = TwoColumnElement(data=TwoColumnElement.default_data())
        col.save()
        parent = add_element(unit, col)
        column_id = col.data["columns"][0]["id"]
        Element.objects.create(
            unit=unit, content_object=gn, parent=parent, tab_id=column_id
        )
    else:
        raise ValueError(f"unknown nest={nest!r}")
    return course, unit, user


def test_has_math_true_for_math_in_stem(client):
    _c, unit, user = _lesson_with_gn(client, stem=r"\(201^2=\){{40401}}")
    assert build_lesson_context(unit, user)["has_math"] is True


def test_has_math_true_for_math_in_success_message(client):
    # Independently of the stem — an unknown type returns False and loads NO KaTeX.
    _c, unit, user = _lesson_with_gn(client, success_message=r"o \(100\%\)")
    assert build_lesson_context(unit, user)["has_math"] is True


def test_has_guess_number_top_level(client):
    _c, unit, user = _lesson_with_gn(client)
    assert build_lesson_context(unit, user)["has_guess_number"] is True


def test_has_guess_number_nested_in_tab(client):
    # build_lesson_context's `elements` list is parent__isnull=True, so a flag
    # computed from it misses nested children and the JS never loads.
    _c, unit, user = _lesson_with_gn(client, nest="tab")
    assert build_lesson_context(unit, user)["has_guess_number"] is True


def test_has_guess_number_nested_in_column(client):
    _c, unit, user = _lesson_with_gn(client, nest="column")
    assert build_lesson_context(unit, user)["has_guess_number"] is True


def test_lesson_page_loads_the_script(client):
    course, unit, _user = _lesson_with_gn(client)
    # A correct flag with a forgotten <script> tag ships a dead widget and the
    # flag test above still passes. Spec §7 calls this the exact class of
    # silent-breakage miss. Precedents: tests/test_stepper_assets.py,
    # tests/test_lesson_stepper_wiring.py — copy their lesson-GET shape, which
    # is reverse("courses:lesson_unit", slug=..., node_pk=...). There is NO
    # get_absolute_url() anywhere in this project.
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    )
    assert "guessnumber.js" in resp.content.decode()


def test_lesson_without_the_element_omits_the_script(client):
    course, plain, _user = _enrolled_lesson(client)
    resp = client.get(
        reverse(
            "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": plain.pk}
        )
    )
    assert "guessnumber.js" not in resp.content.decode()
