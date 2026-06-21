import pytest

from courses import builder
from courses.models import DragToImageQuestionElement
from tests.factories import CourseFactory
from tests.factories import MediaAssetFactory
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def test_save_element_creates_zones():
    course = CourseFactory()
    unit = make_quiz_unit(course=course)
    media = MediaAssetFactory(course=course, kind="image")
    post = {
        # save_element calls _check_token(unit.updated, post["unit_token"]) at builder.py:212
        # BEFORE any branch; omitting it raises ConflictError. Seed it like the existing
        # tests/test_questions_2d_builder.py:13 helper does.
        "unit_token": unit.updated.isoformat(),
        "type": "dragtoimagequestion",
        "media": str(media.pk),
        "alt": "Cell",
        "distractors": "D",
        "marking_mode": "A",
        "max_attempts": "1",
        "max_marks": "1",
        "zones-TOTAL_FORMS": "2",
        "zones-INITIAL_FORMS": "0",
        "zones-MIN_NUM_FORMS": "0",
        "zones-MAX_NUM_FORMS": "1000",
        "zones-0-correct_label": "A",
        "zones-0-x": "0.1",
        "zones-0-y": "0.1",
        "zones-0-w": "0.2",
        "zones-0-h": "0.2",
        "zones-0-order": "0",
        "zones-1-correct_label": "B",
        "zones-1-x": "0.5",
        "zones-1-y": "0.5",
        "zones-1-w": "0.2",
        "zones-1-h": "0.2",
        "zones-1-order": "1",
    }
    # Verified signature: save_element(course, unit_pk, type_key, element_ref, post_data, files)
    # Create is gated on `element_ref == "new"` (builder.py:213); any other value (incl.
    # None) hits the edit path and raises ConflictError. Pass the literal "new".
    builder.save_element(course, unit.pk, "dragtoimagequestion", "new", post, None)
    q = DragToImageQuestionElement.objects.get()
    assert q.expected_tokens() == ["A", "B"]
