import pytest

from courses.views import _element_has_math


@pytest.mark.django_db
def test_element_has_math_true_for_math_only_in_feedback():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="plain stem", multiple=False)
    Choice.objects.create(question=q, text="A", is_correct=True)  # plain
    Choice.objects.create(
        question=q, text="B", is_correct=False, feedback=r"try \(x^2\)"
    )
    assert _element_has_math(q) is True


@pytest.mark.django_db
def test_element_has_math_false_when_no_math_anywhere():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="plain", multiple=False)
    Choice.objects.create(question=q, text="A", is_correct=True, feedback="plain hint")
    Choice.objects.create(question=q, text="B", is_correct=False)
    assert _element_has_math(q) is False
