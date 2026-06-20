import pytest

from tests.factories import (
    ChoiceQuestionElement, ShortTextQuestionElement, add_element, make_quiz_unit,
)


@pytest.mark.django_db
def test_quiz_render_text_posts_to_quiz_answer_and_can_lock():
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    el = add_element(unit, q)
    html = q.render(
        element=el, mode="quiz",
        action_url=f"/x/answer/{el.pk}/", locked=True, quiz_submitted=False,
    )
    assert f"/x/answer/{el.pk}/" in html      # form action redirected to quiz path
    assert "disabled" in html                  # locked input
    assert "/check/" not in html               # not the lesson action


@pytest.mark.django_db
def test_quiz_render_choice_uses_override_and_can_lock():
    # ChoiceQuestionElement has its OWN render() override — must honor quiz mode too.
    unit = make_quiz_unit()
    q = ChoiceQuestionElement.objects.create(stem="Pick", multiple=False)
    q.choices.create(text="A", is_correct=True)
    el = add_element(unit, q)
    html = q.render(
        element=el, mode="quiz", action_url=f"/x/answer/{el.pk}/", locked=True,
    )
    assert f"/x/answer/{el.pk}/" in html
    assert "disabled" in html                  # locked radio inputs


@pytest.mark.django_db
def test_lesson_render_unchanged_defaults():
    unit = make_quiz_unit()  # any unit; lesson-mode render
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    el = add_element(unit, q)
    html = q.render(element=el)               # mode defaults to lesson
    assert f"/q/{el.pk}/check/" in html        # full lesson check_answer path
    assert "disabled" not in html


@pytest.mark.django_db
def test_quiz_render_fillblank_locks_inputs():
    from tests.factories import FillBlankQuestionElement
    unit = make_quiz_unit()
    q = FillBlankQuestionElement.objects.create(stem="The capital is {{Paris}}.")
    el = add_element(unit, q)
    html = q.render(element=el, mode="quiz", action_url=f"/x/answer/{el.pk}/", locked=True)
    assert "<fieldset" in html and "disabled" in html
