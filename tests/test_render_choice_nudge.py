import pytest
from django.template.loader import render_to_string

from courses.marking import MarkResult


@pytest.mark.django_db
def test_reveal_choice_shows_nudge_for_nudged_choice_only():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    good = Choice.objects.create(question=q, text="A", is_correct=True)
    bad = Choice.objects.create(
        question=q, text="B", is_correct=False, feedback="Re-read step 2"
    )

    choices = list(q.choices.all())
    mark_result = MarkResult(
        correct=False,
        fraction=0.0,
        reveal=frozenset({good.pk}),
        nudged=frozenset({bad.pk}),
    )
    html = render_to_string(
        "courses/elements/_reveal_choice.html",
        {"choices": choices, "mark_result": mark_result},
    )
    assert "Re-read step 2" in html  # nudge shown for the mis-picked distractor
    assert "question__nudge" in html  # rendered in the dedicated element
    # correct-tick behaviour unchanged: the correct choice still gets its marker
    assert "answer-correct" in html


@pytest.mark.django_db
def test_reveal_choice_no_nudge_when_none():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    good = Choice.objects.create(question=q, text="A", is_correct=True)
    Choice.objects.create(
        question=q, text="B", is_correct=False, feedback="hidden hint"
    )

    choices = list(q.choices.all())
    mark_result = MarkResult(
        correct=True, fraction=1.0, reveal=frozenset({good.pk}), nudged=frozenset()
    )
    html = render_to_string(
        "courses/elements/_reveal_choice.html",
        {"choices": choices, "mark_result": mark_result},
    )
    assert "hidden hint" not in html  # empty nudged -> no nudge leaks
    assert "question__nudge" not in html
