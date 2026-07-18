import pytest

from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import Enrollment
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import MatchPairQuestionElement
from courses.models import MultiGridQuestionElement
from courses.models import QuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import UnitProgress
from courses.views import save_element_state
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db  # ensure module has DB access for the tests below

IN_SCOPE = [
    ChoiceQuestionElement,
    ShortTextQuestionElement,
    ExtendedResponseQuestionElement,
    ShortNumericQuestionElement,
    FillBlankQuestionElement,
]
DEFERRED = [
    ChoiceGridQuestionElement,
    MultiGridQuestionElement,
    MatchPairQuestionElement,
    DragToImageQuestionElement,
    DragFillBlankQuestionElement,
]


def test_base_default_is_false():
    assert QuestionElement.RESTORABLE_IN_LESSON is False


@pytest.mark.parametrize("cls", IN_SCOPE)
def test_in_scope_types_are_restorable(cls):
    assert cls.RESTORABLE_IN_LESSON is True


@pytest.mark.parametrize("cls", DEFERRED)
def test_deferred_types_are_not_restorable(cls):
    assert cls.RESTORABLE_IN_LESSON is False


def test_save_helper_stores_and_deletes():
    course, unit = make_course_with_unit()
    user = make_verified_user()
    Enrollment.objects.create(student=user, course=course)

    save_element_state(user, unit, 7, {"answer": "x"})
    up = UnitProgress.objects.get(student=user, unit=unit)
    assert up.element_state == {"7": {"answer": "x"}}

    save_element_state(user, unit, 7, None)
    up.refresh_from_db()
    assert "7" not in up.element_state


def test_save_helper_delete_does_not_spawn_a_row():
    course, unit = make_course_with_unit()
    user = make_verified_user()
    Enrollment.objects.create(student=user, course=course)

    # No UnitProgress row exists yet; deleting a key must NOT create one.
    save_element_state(user, unit, 7, None)
    assert not UnitProgress.objects.filter(student=user, unit=unit).exists()
