import pytest

from courses import state
from courses.models import MarkDoneElement
from courses.models import MarkDoneItem
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
