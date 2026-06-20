import pytest

from courses.element_forms import DragFillBlankQuestionElementForm


@pytest.mark.django_db
def test_form_parses_single_token_markers():
    form = DragFillBlankQuestionElementForm(
        data={"stem": "The capital is {{Paris}} and {{Madrid}}.", "distractors": "Rome"}
    )
    assert form.is_valid(), form.errors
    assert form.parsed_dragblanks == ["Paris", "Madrid"]


@pytest.mark.django_db
def test_form_rejects_pipe_with_dragfill_message():
    form = DragFillBlankQuestionElementForm(data={"stem": "{{a|b}}", "distractors": ""})
    assert not form.is_valid()
    assert any("single answer" in str(e).lower() or "one token" in str(e).lower()
               for e in form.errors["stem"])


@pytest.mark.django_db
def test_form_rejects_no_markers_without_fillblank_pipe_hint():
    form = DragFillBlankQuestionElementForm(data={"stem": "no gaps here", "distractors": ""})
    assert not form.is_valid()
    msg = " ".join(str(e) for e in form.errors["stem"]).lower()
    assert "gap" in msg and "alternativ" not in msg  # NOT fill-blank's "use | for alternatives"


@pytest.mark.django_db
def test_form_rejects_over_long_token():
    form = DragFillBlankQuestionElementForm(
        data={"stem": "{{" + "x" * 501 + "}}", "distractors": ""}
    )
    assert not form.is_valid()


@pytest.mark.django_db
def test_form_accepts_exactly_500_char_token():
    # Boundary: 500 is the max_length, so a 500-char token is accepted (501 rejected above).
    form = DragFillBlankQuestionElementForm(
        data={"stem": "{{" + "x" * 500 + "}}", "distractors": ""}
    )
    assert form.is_valid(), form.errors
    assert form.parsed_dragblanks == ["x" * 500]
