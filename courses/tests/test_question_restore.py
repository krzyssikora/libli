import pytest

from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import MatchPairQuestionElement
from courses.models import MultiGridQuestionElement
from courses.models import QuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement

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
