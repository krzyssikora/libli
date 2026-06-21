import pytest

from courses.element_forms import DragToImageQuestionElementForm
from courses.element_forms import build_dragzone_formset
from tests.factories import CourseFactory
from tests.factories import MediaAssetFactory

pytestmark = pytest.mark.django_db


def test_form_scopes_media_to_course_and_makes_marking_optional():
    c1 = CourseFactory()
    c2 = CourseFactory()
    mine = MediaAssetFactory(course=c1, kind="image")
    other = MediaAssetFactory(course=c2, kind="image")
    form = DragToImageQuestionElementForm(course=c1)
    qs = form.fields["media"].queryset
    assert mine in qs and other not in qs
    for f in ("marking_mode", "max_attempts", "max_marks"):
        assert form.fields[f].required is False


def test_form_constructs_without_typeerror_on_course_kwarg():
    DragToImageQuestionElementForm(course=CourseFactory())  # no TypeError


def test_formset_requires_at_least_one_zone():
    fs = build_dragzone_formset(
        data={
            "zones-TOTAL_FORMS": "0",
            "zones-INITIAL_FORMS": "0",
            "zones-MIN_NUM_FORMS": "0",
            "zones-MAX_NUM_FORMS": "1000",
        }
    )
    assert not fs.is_valid()


def test_formset_rejects_out_of_range_coords():
    fs = build_dragzone_formset(
        data={
            "zones-TOTAL_FORMS": "1",
            "zones-INITIAL_FORMS": "0",
            "zones-MIN_NUM_FORMS": "0",
            "zones-MAX_NUM_FORMS": "1000",
            "zones-0-correct_label": "A",
            "zones-0-x": "0.9",
            "zones-0-y": "0.0",
            "zones-0-w": "0.5",
            "zones-0-h": "0.2",
            "zones-0-order": "0",
        }
    )
    assert not fs.is_valid()
