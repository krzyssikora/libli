import pytest
from django.core.exceptions import ValidationError

from courses.models import DragZone
from tests.factories import DragToImageQuestionElementFactory
from tests.factories import DragZoneFactory

pytestmark = pytest.mark.django_db


def test_expected_tokens_is_zone_order():
    q = DragToImageQuestionElementFactory()
    DragZoneFactory(question=q, correct_label="Nucleus", order=0)
    DragZoneFactory(question=q, correct_label="Membrane", order=1)
    assert q.expected_tokens() == ["Nucleus", "Membrane"]


def test_build_answer_reads_slot_getlist(rf):
    q = DragToImageQuestionElementFactory()
    req = rf.post("/", {"slot": ["A", "", "B"]})
    assert q.build_answer(req.POST) == ["A", "", "B"]


def test_zone_coord_validation_accepts_in_range():
    q = DragToImageQuestionElementFactory()
    z = DragZone(question=q, correct_label="x", x=0.1, y=0.1, w=0.3, h=0.3, order=0)
    z.full_clean()  # no raise


@pytest.mark.parametrize(
    "x,y,w,h",
    [
        (0.9, 0.0, 0.2, 0.2),  # x+w = 1.1 > 1+eps
        (0.0, 0.9, 0.2, 0.2),  # y+h overflow
        (0.0, 0.0, 0.0, 0.3),  # zero width
        (0.0, 0.0, 0.3, 0.0),  # zero height
        (-0.1, 0.0, 0.3, 0.3),  # negative x
    ],
)
def test_zone_coord_validation_rejects_bad(x, y, w, h):
    q = DragToImageQuestionElementFactory()
    z = DragZone(question=q, correct_label="x", x=x, y=y, w=w, h=h, order=0)
    with pytest.raises(ValidationError):
        z.full_clean()


def test_zone_coord_epsilon_boundary():
    from courses.models import ZONE_COORD_EPSILON

    q = DragToImageQuestionElementFactory()
    ok = DragZone(
        question=q,
        correct_label="x",
        x=0.5,
        y=0.0,
        w=0.5 + ZONE_COORD_EPSILON,
        h=0.2,
        order=0,
    )
    ok.full_clean()  # within epsilon → passes
    bad = DragZone(
        question=q,
        correct_label="x",
        x=0.5,
        y=0.0,
        w=0.5 + 2 * ZONE_COORD_EPSILON,
        h=0.2,
        order=1,
    )
    with pytest.raises(ValidationError):
        bad.full_clean()
