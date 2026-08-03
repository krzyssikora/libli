import pytest

from courses.lal_loader.builders import LoaderError
from courses.lal_loader.builders import build_element
from tests.factories import make_course_with_unit


@pytest.mark.django_db
def test_spoiler_gate_rejects_a_type_the_wider_allowlist_would_admit():
    """`mark_done` is in NESTABLE_TYPE_KEYS but NOT in LAL_SPOILER_CHILD_TYPES,
    the LAL loader's own (deliberately narrower) spoiler-child allowlist.

    It must be a type the loader CAN build (builders.py handles "mark_done" by
    creating a MarkDoneElement) -- an unknown type would raise LoaderError from
    the unknown-type fallthrough at the end of build_element whether or not the
    gate fired, making the assertion vacuous.

    This is NOT the gate's only guard: test_build_spoiler_rejects_container_child
    (tests/test_lal_loader_units.py) already covers the same branch (builders.py:
    132-141) and would also go RED under the "widen to NESTABLE_TYPE_KEYS" mutant,
    since its child type ("tabs") has its own build branch too. What this test adds
    over that one: (1) it asserts the error MESSAGE, not just the exception class
    -- the sibling only checks `pytest.raises(LoaderError)`, so it wouldn't catch a
    regression that raised the right exception for the wrong reason; and (2) it
    exercises the OTHER rejected category from builders.py:122-124's own comment
    -- an excluded non-container leaf/question type ("mark_done"), distinct from
    the sibling's excluded NATIVE container ("tabs").
    """
    course, unit = make_course_with_unit()
    spoiler_dict = {
        "type": "spoiler",
        "label": "Hint",
        "elements": [{"type": "mark_done", "prompt": "x", "items": ["a"]}],
    }
    with pytest.raises(LoaderError) as exc:
        build_element(
            course, unit, spoiler_dict, source_root="", source_dir="", allow_html=False
        )
    assert "not allowed inside a spoiler" in str(exc.value)
