import pytest
from django.http import QueryDict

from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import SwitchGateElementForm
from courses.models import SwitchGateElement
from courses.switchgate import SENTINEL_TOKEN

pytestmark = pytest.mark.django_db


def _post(stem, options, answer):
    qd = QueryDict(mutable=True)
    qd["stem"] = stem
    for o in options:
        qd.appendlist("option", o)
    if answer is not None:
        qd["answer"] = str(answer)
    return qd


def test_registered_in_form_for_type():
    assert FORM_FOR_TYPE["switchgate"] is SwitchGateElementForm


def test_valid_form_saves_token_stem_options_answer():
    form = SwitchGateElementForm(data=_post("pick {{choice}} here", ["a", "b", "c"], 2))
    assert form.is_valid(), form.errors
    el = form.save()
    assert el.stem == f"pick {SENTINEL_TOKEN} here"
    assert el.options == ["a", "b", "c"]
    assert el.answer == 2


def test_trailing_empty_options_ignored():
    form = SwitchGateElementForm(data=_post("x {{choice}} y", ["a", "b", "", ""], 1))
    assert form.is_valid(), form.errors
    assert form.save().options == ["a", "b"]


def test_interior_empty_option_rejected():
    form = SwitchGateElementForm(data=_post("x {{choice}} y", ["a", "", "b"], 2))
    assert not form.is_valid()


def test_fewer_than_two_options_rejected():
    form = SwitchGateElementForm(data=_post("x {{choice}} y", ["a"], 0))
    assert not form.is_valid()


def test_stem_without_marker_rejected():
    form = SwitchGateElementForm(data=_post("no marker", ["a", "b"], 0))
    assert not form.is_valid()
    assert "stem" in form.errors


def test_answer_out_of_range_rejected():
    form = SwitchGateElementForm(data=_post("x {{choice}} y", ["a", "b"], 5))
    assert not form.is_valid()


def test_missing_answer_rejected():
    form = SwitchGateElementForm(data=_post("x {{choice}} y", ["a", "b"], None))
    assert not form.is_valid()


def test_option_sanitized_to_empty_rejected():
    form = SwitchGateElementForm(
        data=_post("x {{choice}} y", ["<script>x</script>", "b", "c"], 1)
    )
    # first option sanitises to "" (script stripped, no text) -> interior empty
    # -> reject
    assert not form.is_valid()


def test_edit_prefills_author_stem_and_rows():
    el = SwitchGateElement.objects.create(
        stem=f"a {SENTINEL_TOKEN} b", options=["p", "q"], answer=1
    )
    form = SwitchGateElementForm(instance=el)
    assert form.initial["stem"] == "a {{choice}} b"
    rows = form.option_rows()
    assert rows[0] == {"value": "p", "checked": False}
    assert rows[1] == {"value": "q", "checked": True}
    assert len(rows) >= 6


def test_option_rows_prefer_posted_data_on_invalid_rerender():
    # invalid POST (no marker in stem) -> form re-rendered; rows must keep the
    # author's posted options + answer, not fall back to blank/instance state.
    form = SwitchGateElementForm(data=_post("no marker", ["typed-a", "typed-b"], 1))
    assert not form.is_valid()
    rows = form.option_rows()
    assert rows[0]["value"] == "typed-a"
    assert rows[1] == {"value": "typed-b", "checked": True}
