import pytest

from courses.marking import MarkResult


@pytest.mark.django_db
def test_mark_single_choice_set_equality():
    from courses.models import ChoiceQuestionElement, Choice

    q = ChoiceQuestionElement.objects.create(stem="2+2?", multiple=False)
    a = Choice.objects.create(question=q, text="4", is_correct=True)
    b = Choice.objects.create(question=q, text="5", is_correct=False)

    correct = q.mark({a.pk})
    assert isinstance(correct, MarkResult)
    assert correct.correct is True and correct.fraction == 1.0
    assert correct.reveal == frozenset({a.pk})

    assert q.mark({b.pk}).correct is False
    # forged: two ids in single mode -> not equal to the singleton correct set
    assert q.mark({a.pk, b.pk}).correct is False
    # empty submission -> incorrect
    assert q.mark(set()).correct is False and q.mark(set()).fraction == 0.0


@pytest.mark.django_db
def test_mark_multiple_choice_all_or_nothing():
    from courses.models import ChoiceQuestionElement, Choice

    q = ChoiceQuestionElement.objects.create(stem="Primes?", multiple=True)
    c2 = Choice.objects.create(question=q, text="2", is_correct=True)
    c3 = Choice.objects.create(question=q, text="3", is_correct=True)
    c4 = Choice.objects.create(question=q, text="4", is_correct=False)

    assert q.mark({c2.pk, c3.pk}).correct is True
    assert q.mark({c2.pk}).correct is False          # partial -> wrong (all-or-nothing)
    assert q.mark({c2.pk, c3.pk, c4.pk}).correct is False
    assert q.mark(set()).correct is False


@pytest.mark.django_db
def test_stem_and_explanation_sanitised_on_save():
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(
        stem="<p>ok</p><script>alert(1)</script>",
        explanation="<p>why</p><script>bad()</script>",
    )
    assert "<script>" not in q.stem and "<p>ok</p>" in q.stem
    assert "<script>" not in q.explanation and "<p>why</p>" in q.explanation


@pytest.mark.django_db
def test_choice_order_autonumbers_and_survives_delete_then_add():
    from courses.models import ChoiceQuestionElement, Choice

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    a = Choice.objects.create(question=q, text="a")
    b = Choice.objects.create(question=q, text="b")
    c = Choice.objects.create(question=q, text="c")
    assert [x.order for x in (a, b, c)] == [0, 1, 2]  # OrderField base is 0
    b.delete()  # leaves a gap at order 1
    d = Choice.objects.create(question=q, text="d")
    assert d.order == 3  # max(order)+1, not reusing the gap
    # effective display order is (order, pk): a(0), c(2), d(3)
    assert [x.text for x in q.choices.all()] == ["a", "c", "d"]


@pytest.mark.django_db
def test_choicequestionelement_in_element_models():
    from courses.models import ELEMENT_MODELS

    assert "choicequestionelement" in ELEMENT_MODELS
