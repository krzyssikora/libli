import pytest

from courses.marking import MarkResult


@pytest.mark.django_db
def test_mark_single_choice_set_equality():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

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
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="Primes?", multiple=True)
    c2 = Choice.objects.create(question=q, text="2", is_correct=True)
    c3 = Choice.objects.create(question=q, text="3", is_correct=True)
    c4 = Choice.objects.create(question=q, text="4", is_correct=False)

    assert q.mark({c2.pk, c3.pk}).correct is True
    assert q.mark({c2.pk}).correct is False  # partial -> wrong (all-or-nothing)
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
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

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


@pytest.mark.django_db
def test_choice_feedback_defaults_blank():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    c = Choice.objects.create(question=q, text="A", is_correct=True)
    assert c.feedback == ""  # default="" — no interactive migration prompt
    c.feedback = "Are you sure?"
    c.save()
    assert Choice.objects.get(pk=c.pk).feedback == "Are you sure?"


def test_markresult_annotated_defaults_empty_and_hashable():
    # annotated defaults to an empty frozenset and MarkResult stays hashable
    # (frozen=True + a frozenset field; a dict field would raise on hash()).
    r = MarkResult(correct=False, fraction=0.0, reveal=frozenset())
    assert r.annotated == frozenset()
    assert isinstance(hash(r), int)
    r2 = MarkResult(
        correct=False, fraction=0.0, reveal=frozenset(), annotated=frozenset({1, 2})
    )
    assert r2.annotated == frozenset({1, 2})
    assert isinstance(hash(r2), int)


@pytest.mark.django_db
def test_mark_annotated_selected_distractor_on_wrong():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    good = Choice.objects.create(question=q, text="A", is_correct=True, feedback="")
    bad = Choice.objects.create(
        question=q, text="B", is_correct=False, feedback="Not quite"
    )

    # wrong answer selecting the annotated distractor -> its pk is annotated
    assert q.mark({bad.pk}).annotated == frozenset({bad.pk})
    # correct answer -> nothing annotated
    assert q.mark({good.pk}).annotated == frozenset()


@pytest.mark.django_db
def test_mark_annotated_excludes_blank_and_unselected():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    Choice.objects.create(question=q, text="A", is_correct=True)  # correct, pk unused
    bad_blank = Choice.objects.create(
        question=q, text="B", is_correct=False, feedback=""
    )
    bad_annot = Choice.objects.create(
        question=q, text="C", is_correct=False, feedback="hint"
    )

    # selected a blank-feedback distractor -> nothing to annotate
    assert q.mark({bad_blank.pk}).annotated == frozenset()
    # an annotated distractor the student did NOT select -> not annotated
    assert bad_annot.pk not in q.mark({bad_blank.pk}).annotated


@pytest.mark.django_db
def test_mark_annotated_multi_excludes_selected_correct_pick():
    # multiple-choice: overall-wrong; the student selected an annotated CORRECT
    # choice. That choice is handled CORRECTLY (selected == correct), so it is NOT
    # annotated — only the wrongly-selected distractor is.
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=True)
    c_ok = Choice.objects.create(
        question=q, text="A", is_correct=True, feedback="good one"
    )
    Choice.objects.create(question=q, text="B", is_correct=True)  # correct, pk unused
    c_bad = Choice.objects.create(
        question=q, text="C", is_correct=False, feedback="nope"
    )

    # selected one correct + one distractor -> overall wrong; only c_bad is annotated
    res = q.mark({c_ok.pk, c_bad.pk})
    assert res.correct is False
    assert res.annotated == frozenset({c_bad.pk})  # c_ok excluded despite feedback


@pytest.mark.django_db
def test_mark_annotated_symmetric_includes_missed_correct():
    # NEW symmetric rule: an option is annotated iff the student's state for it
    # is wrong (selected XOR correct) AND it carries feedback. This covers BOTH
    # a selected distractor and a MISSED correct option (the omission case the
    # old asymmetric pre-rename rule never surfaced).
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=True)
    a = Choice.objects.create(question=q, text="A", is_correct=True, feedback="need A")
    # B: correct, no feedback
    b = Choice.objects.create(question=q, text="B", is_correct=True)
    c = Choice.objects.create(question=q, text="C", is_correct=False, feedback="trap C")

    # student picks only C (a trap) and misses both correct options.
    res = q.mark({c.pk})
    assert res.correct is False
    # C = selected distractor with feedback -> annotated
    # A = missed correct WITH feedback -> annotated (the new case)
    # B = missed correct but NO feedback -> excluded
    assert res.annotated == frozenset({a.pk, c.pk})
    # fully-correct answer -> empty annotated (stay quiet when right)
    assert q.mark({a.pk, b.pk}).annotated == frozenset()
    # UNANSWERED (empty answer, the results-page mark(empty) path): every
    # correct-with-feedback option is annotated (A), the no-feedback correct
    # one (B) is not. Guards the documented unanswered-[A]-results behavior.
    assert q.mark(frozenset()).annotated == frozenset({a.pk})
