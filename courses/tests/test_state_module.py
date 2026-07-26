import pytest

from courses import state
from courses.models import MarkDoneElement
from courses.models import MarkDoneItem
from courses.models import StepperElement
from courses.models import StepperStep
from tests.factories import add_element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _mk():
    _course, unit = make_course_with_unit()
    obj = MarkDoneElement.objects.create(prompt="P")
    el = add_element(unit, obj)
    i1 = MarkDoneItem.objects.create(element=obj, content="a")
    i2 = MarkDoneItem.objects.create(element=obj, content="b")
    return el, obj, i1, i2


def test_empty_and_reject_are_distinct_and_not_falsy():
    # Load-bearing: EMPTY deletes the stored key, REJECT preserves it. An
    # implementer conflating them makes a malformed blob wipe good state.
    assert state.EMPTY is not state.REJECT
    assert state.EMPTY is not None and state.REJECT is not None
    assert bool(state.EMPTY) and bool(state.REJECT)


def test_markdone_stores_only_valid_item_pks():
    el, obj, i1, _i2 = _mk()
    other = MarkDoneElement.objects.create(prompt="other")
    foreign = MarkDoneItem.objects.create(element=other, content="x")
    out = state.validate_state(el, obj, {"items": [i1.pk, foreign.pk, 999999]})
    assert out == {"items": [i1.pk]}


def test_markdone_coerces_string_pks():
    el, obj, i1, _i2 = _mk()
    assert state.validate_state(el, obj, {"items": [str(i1.pk)]}) == {"items": [i1.pk]}


def test_markdone_empty_selection_is_EMPTY_not_reject():
    el, obj, _i1, _i2 = _mk()
    assert state.validate_state(el, obj, {"items": []}) is state.EMPTY


def test_markdone_non_dict_payload_is_REJECT():
    el, obj, _i1, _i2 = _mk()
    assert state.validate_state(el, obj, ["nope"]) is state.REJECT


def test_markdone_items_not_a_list_is_REJECT():
    el, obj, _i1, _i2 = _mk()
    assert state.validate_state(el, obj, {"items": "abc"}) is state.REJECT


def test_unknown_content_type_is_REJECT():
    from courses.models import TextElement

    _course, unit = make_course_with_unit()
    obj = TextElement.objects.create(body="hi")
    el = add_element(unit, obj)
    assert state.validate_state(el, obj, {"anything": 1}) is state.REJECT


def test_validator_exception_maps_to_REJECT(monkeypatch):
    el, obj, _i1, _i2 = _mk()

    def boom(element, o, payload):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(state.VALIDATORS, "markdoneelement", boom)
    assert state.validate_state(el, obj, {"items": []}) is state.REJECT


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"open": True}, {"open": True}),
        ({"open": True, "x": 1}, {"open": True}),  # extra keys normalized away
    ],
)
def test_val_open_gate_stores_open(payload, expected):
    assert state._val_open_gate(None, None, payload) == expected


@pytest.mark.parametrize("payload", [{"open": False}, {}, {"other": 1}])
def test_val_open_gate_empty(payload):
    # A well-formed "nothing to restore" DROPS the key -- EMPTY, never REJECT.
    assert state._val_open_gate(None, None, payload) is state.EMPTY


@pytest.mark.parametrize("payload", ["nope", 3, None, ["open"]])
def test_val_open_gate_rejects_non_dict(payload):
    assert state._val_open_gate(None, None, payload) is state.REJECT


def test_open_gate_registered_for_all_three_families():
    for key in ("revealgateelement", "fillgateelement", "switchgateelement"):
        assert state.VALIDATORS[key] is state._val_open_gate


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"done": True}, {"done": True}),
        ({"done": True, "x": 1}, {"done": True}),  # extra keys normalized away
    ],
)
def test_val_done_stores_done(payload, expected):
    assert state._val_done(None, None, payload) == expected


@pytest.mark.parametrize("payload", [{"done": False}, {}, {"other": 1}])
def test_val_done_empty(payload):
    # A well-formed "nothing to restore" DROPS the key -- EMPTY, never REJECT.
    assert state._val_done(None, None, payload) is state.EMPTY


@pytest.mark.parametrize("payload", ["nope", 3, None, ["done"]])
def test_val_done_rejects_non_dict(payload):
    assert state._val_done(None, None, payload) is state.REJECT


def test_done_registered_for_all_three_graded_selfcheck_families():
    for key in ("switchgridelement", "filltableelement", "guessnumberelement"):
        assert state.VALIDATORS[key] is state._val_done


def _mk_stepper(n):
    _course, unit = make_course_with_unit()
    obj = StepperElement.objects.create(prompt="P")
    for i in range(n):
        StepperStep.objects.create(stepper=obj, content=f"s{i}")
    el = add_element(unit, obj)
    return el, obj


def test_val_stepper_stores_clamped_count():
    el, obj = _mk_stepper(3)
    assert state.validate_state(el, obj, {"shown": 2}) == {"shown": 2}


def test_val_stepper_clamps_to_step_count():
    # A stored value above the count stores the count, not the input (self-heal).
    el, obj = _mk_stepper(3)
    assert state.validate_state(el, obj, {"shown": 9}) == {"shown": 3}


def test_val_stepper_below_two_is_EMPTY():
    el, obj = _mk_stepper(3)
    assert state.validate_state(el, obj, {"shown": 1}) is state.EMPTY
    assert state.validate_state(el, obj, {"shown": 0}) is state.EMPTY


def test_val_stepper_non_dict_is_REJECT():
    el, obj = _mk_stepper(3)
    assert state.validate_state(el, obj, ["nope"]) is state.REJECT


def test_val_stepper_absent_or_non_numeric_shown_is_REJECT():
    el, obj = _mk_stepper(3)
    assert state.validate_state(el, obj, {}) is state.REJECT
    assert state.validate_state(el, obj, {"shown": "abc"}) is state.REJECT


def test_val_stepper_float_shown_is_floored_not_rejected():
    # int() floors 2.9 -> 2 (consistent with _val_markdone); NOT REJECT.
    el, obj = _mk_stepper(3)
    assert state.validate_state(el, obj, {"shown": 2.9}) == {"shown": 2}


def test_val_stepper_single_step_never_restores():
    el, obj = _mk_stepper(1)
    assert state.validate_state(el, obj, {"shown": 5}) is state.EMPTY


def test_stepper_registered():
    assert state.VALIDATORS["stepperelement"] is state._val_stepper


# The 18 element types that can persist practice state, written out literally.
# DELIBERATELY hard-coded rather than re-derived: re-implementing state.py's
# comprehension here would be green by construction and could never go RED
# (spec §Testing, test 8). Derive in production, pin literally in the test.
STATEFUL_MODEL_NAMES = {
    # the state.VALIDATORS half -- self-checks and gates
    "markdoneelement",
    "revealgateelement",
    "fillgateelement",
    "switchgateelement",
    "switchgridelement",
    "filltableelement",
    "guessnumberelement",
    "stepperelement",
    # the RESTORABLE_IN_LESSON half -- lesson-mode question answers
    "choicequestionelement",
    "shorttextquestionelement",
    "extendedresponsequestionelement",
    "shortnumericquestionelement",
    "fillblankquestionelement",
    "dragfillblankquestionelement",
    "matchpairquestionelement",
    "dragtoimagequestionelement",
    "choicegridquestionelement",
    "multigridquestionelement",
}


def test_stateful_element_model_names_is_the_expected_18():
    from courses.models import ELEMENT_MODELS

    names = state.stateful_element_model_names()

    assert set(names) == STATEFUL_MODEL_NAMES
    # Sortedness: compare against a TUPLE, not a list. `list(names) == sorted(names)`
    # would let a raw set pass whenever its hash order happened to be sorted, making
    # the RED hash-seed dependent; a set never equals a tuple (spec §Testing, test 8).
    assert names == tuple(sorted(names))
    # Known-inert types stay out (shares the equality guard's falsification).
    assert "textelement" not in names
    assert "videoelement" not in names
    # The registry contract the `& known` intersection relies on. Falsified TEST-SIDE
    # only (monkeypatching in a bogus key) -- no production edit fires this one.
    assert set(state.VALIDATORS) <= set(ELEMENT_MODELS)


def test_a_bogus_validator_key_is_dropped_from_the_derived_names(monkeypatch):
    """The `& known` intersection itself, which nothing else can falsify.

    The real VALIDATORS is clean by construction, so deleting `& known` from
    state.py leaves the whole suite green. Only a bogus key surfaces it.
    """
    monkeypatch.setitem(state.VALIDATORS, "nosuchelement", lambda *a: None)

    # Equality, not `"nosuchelement" not in ...`: a widened result must be caught as
    # a value change, since the names feed a content_type__model__in filter.
    assert set(state.stateful_element_model_names()) == STATEFUL_MODEL_NAMES
