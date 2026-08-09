import pytest

from courses.models import BeforeAfterElement
from courses.models import Element
from courses.models import TextElement
from tests.factories import make_course_with_unit


def _ba_with_children(unit, label="Flip"):
    obj = BeforeAfterElement.objects.create(button_label=label)
    join = Element.objects.create(unit=unit, content_object=obj)
    for slot, body in (
        (BeforeAfterElement.BEFORE_SLOT_ID, "problem"),
        (BeforeAfterElement.AFTER_SLOT_ID, "answer"),
    ):
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(body=body),
            parent=join,
            tab_id=slot,
        )
    return join, obj


# build_element_export(unit, root_join) -> (document, media_assets, problems).
# TWO positionals and a 3-TUPLE (export.py:993) -- not build_element_export(join).
# See tests/test_transfer_element_scope.py:54 for the call convention.


@pytest.mark.django_db
def test_export_emits_both_children_under_their_slot_ids():
    """Mutant: omit the emit() walker isinstance branch -> the serializer runs but
    ZERO children are emitted, and export succeeds silently.
    """
    from courses.transfer.export import build_element_export

    _course, unit = make_course_with_unit()
    join, _obj = _ba_with_children(unit)
    document, _media, _problems = build_element_export(unit, join)
    tabs = {el["tab"] for el in document["elements"] if el["parent"] is not None}
    assert tabs == set(BeforeAfterElement.SLOT_IDS)


@pytest.mark.django_db
def test_export_carries_button_label():
    """Mutant: _ser_before_after returns {} -> the label is silently lost on every
    export, import AND duplicate_element.
    """
    from courses.transfer.export import build_element_export

    _course, unit = make_course_with_unit()
    join, _obj = _ba_with_children(unit, label="Show solution")
    document, _media, _problems = build_element_export(unit, join)
    root = [el for el in document["elements"] if el["parent"] is None][0]
    assert root["data"] == {"button_label": "Show solution"}


@pytest.mark.django_db
def test_a_stray_child_exports_under_the_before_slot():
    """resolved_slots() re-homes an unknown tab_id into `before`, so the walker
    must yield the PAIR's slot id -- never the child's own tab_id, which would
    emit a payload validate_nesting rejects (export.py:595-598 documents exactly
    this invariant).

    Mutant: yield child.tab_id -> the archive carries "bogus" and re-import fails.
    """
    from courses.transfer.export import build_element_export

    _course, unit = make_course_with_unit()
    join, _obj = _ba_with_children(unit)
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="stray"),
        parent=join,
        tab_id="bogus",
    )
    document, _media, _problems = build_element_export(unit, join)
    children = [el for el in document["elements"] if el["parent"] is not None]
    assert len(children) == 3
    assert all(el["tab"] in BeforeAfterElement.SLOT_IDS for el in children)
    stray = [el for el in children if el["data"].get("body") == "stray"]
    assert len(stray) == 1
    assert stray[0]["tab"] == BeforeAfterElement.BEFORE_SLOT_ID


@pytest.mark.django_db
def test_duplicate_element_copies_children_and_label():
    """duplicate_element routes through build_element_export -> graft_elements, so
    the same walker mutant makes duplication return 200 with an empty copy.

    Signature is duplicate_element(course, element_pk, unit_token) returning
    (unit, new_join) -- builder.py:709. Model the call on
    tests/test_builder_duplicate_element.py.
    """
    from courses import builder

    course, unit = make_course_with_unit()
    join, _obj = _ba_with_children(unit, label="Flip")
    _unit, new_join = builder.duplicate_element(
        course, join.pk, unit.updated.isoformat()
    )
    copy = new_join.content_object
    assert copy.button_label == "Flip"
    assert [len(children) for _sid, children in copy.resolved_slots()] == [1, 1]


@pytest.mark.django_db
def test_validate_nesting_accepts_both_slots_and_rejects_a_bad_one():
    """The _CONTAINER_SLOT_KEY reshape in Task 3 changed the branch computing
    valid_slot_ids for ALL FIVE container types, not just this one. Nothing else
    in the plan exercises the rewritten `isinstance(slot_key, str)` ternary
    end-to-end, so inverting it could regress spoiler/callout imports with the
    whole suite green.

    Mutant: invert the ternary -> the before/after case raises and the spoiler
    case stops raising.
    """
    from courses.models import SINGLE_SLOT_ID
    from courses.transfer.payloads import validate_nesting
    from courses.transfer.schema import TransferError

    def _els(parent_type, tab, parent_data=None):
        return [
            {
                "id": "p",
                "type": parent_type,
                "parent": None,
                "tab": "",
                "data": parent_data or {},
            },
            {"id": "c", "type": "text", "parent": "p", "tab": tab, "data": {}},
        ]

    for slot in BeforeAfterElement.SLOT_IDS:
        validate_nesting(_els("before_after", slot))  # accepted
    with pytest.raises(TransferError):
        validate_nesting(_els("before_after", "bogus"))  # rejected
    # The reshape must not regress the other fixed-slot containers.
    validate_nesting(_els("spoiler", SINGLE_SLOT_ID))
    with pytest.raises(TransferError):
        validate_nesting(_els("spoiler", "bogus"))


def test_validator_rejects_unknown_and_missing_keys():
    from courses.transfer.payloads import VALIDATORS
    from courses.transfer.schema import TransferError

    val = VALIDATORS["before_after"]
    assert val({"button_label": "ok"}, "e1", set()) == set()
    with pytest.raises(TransferError):
        val({}, "e1", set())
    with pytest.raises(TransferError):
        val({"button_label": "ok", "extra": 1}, "e1", set())
    with pytest.raises(TransferError):
        val({"button_label": "x" * 121}, "e1", set())


def test_format_version_is_pinned():
    """Before/after itself never bumped this (a new element TYPE doesn't change
    an EXISTING payload shape) -- the version rises only when something else
    does. Renamed from test_format_version_is_unchanged: Task 9 (published on
    the node payload) bumped FORMAT_VERSION to 10, so a name asserting "is
    unchanged" would now contradict its own body. Not bumping-for-this-feature
    also sidesteps the silent-merge hazard (two branches setting the same new
    number do not conflict in git).
    """
    from courses.transfer.schema import FORMAT_VERSION

    assert FORMAT_VERSION == 11
