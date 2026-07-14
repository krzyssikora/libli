import pytest

from courses import fillblank
from courses.builder import _NESTABLE_FORM_KEY_ALIASES
from courses.builder import NESTABLE_TYPE_KEYS
from courses.models import SwitchGridElement
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.schema import TransferError

pytestmark = pytest.mark.django_db


def _tok(i):
    return fillblank.SENTINEL + str(i) + fillblank.SENTINEL


def test_registered_and_nestable():
    assert "switch_grid" in SERIALIZERS
    assert "switch_grid" in VALIDATORS
    assert "switch_grid" in BUILDERS
    assert "switch_grid" in NESTABLE_TYPE_KEYS
    # form key ("switchgrid") diverges from the transfer key ("switch_grid"),
    # so resolve_scope needs the alias to reach NESTABLE_TYPE_KEYS
    assert _NESTABLE_FORM_KEY_ALIASES["switchgrid"] == "switch_grid"
    # invariant guarded by the tabs transfer tests
    assert NESTABLE_TYPE_KEYS <= set(SERIALIZERS)


def test_switch_grid_is_nestable_via_resolve_scope():
    # Prove nesting is actually allowed through the real resolve_scope() path
    # (form key "switchgrid"), which exercises the form-key alias.
    from courses import builder
    from courses.models import Element
    from courses.models import TabsElement
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][0]["id"]
    parent_join, resolved_tab = builder.resolve_scope(
        unit, str(join.pk), tab_id, "switchgrid"
    )
    assert parent_join == join
    assert resolved_tab == tab_id


def _payload():
    return {
        "prompt": "P",
        "lines": [
            {"stem": "static", "cyclers": []},
            {
                "stem": f"a {_tok(0)} b",
                "cyclers": [{"options": ["+", "-"], "answer": 1}],
            },
        ],
    }


def test_round_trip_preserves_prompt_and_lines():
    model, ser = SERIALIZERS["switch_grid"]
    el = SwitchGridElement.objects.create(**_payload())
    data = ser(el, {})
    assert data["prompt"] == "P"
    assert data["lines"][1]["cyclers"][0]["answer"] == 1
    # validate (3-arg signature) + build
    assert VALIDATORS["switch_grid"](data, "el-1", set()) == set()  # must not raise
    obj, _refs = BUILDERS["switch_grid"](data, {})
    obj.refresh_from_db()
    assert obj.lines[0]["cyclers"] == []
    assert obj.lines[1]["cyclers"][0]["options"] == ["+", "-"]


def test_validator_rejects_marker_cycler_mismatch():
    bad = {
        "prompt": "",
        "lines": [
            {
                "stem": f"a {_tok(0)} b {_tok(1)}",
                "cyclers": [{"options": ["x", "y"], "answer": 0}],
            }
        ],
    }  # 2 markers, 1 cycler
    with pytest.raises(TransferError):
        VALIDATORS["switch_grid"](bad, "el-1", set())


def test_validator_rejects_out_of_range_answer():
    bad = {
        "prompt": "",
        "lines": [
            {"stem": f"a {_tok(0)}", "cyclers": [{"options": ["x", "y"], "answer": 5}]}
        ],
    }
    with pytest.raises(TransferError):
        VALIDATORS["switch_grid"](bad, "el-1", set())


def test_import_sanitizes_stem_segments():
    payload = {
        "prompt": "",
        "lines": [
            {
                "stem": f"<script>evil</script>ok {_tok(0)}",
                "cyclers": [{"options": ["a", "b"], "answer": 0}],
            }
        ],
    }
    obj, _refs = BUILDERS["switch_grid"](payload, {})
    obj.refresh_from_db()
    assert "<script>" not in obj.lines[0]["stem"]
    assert _tok(0) in obj.lines[0]["stem"]  # sentinel preserved
