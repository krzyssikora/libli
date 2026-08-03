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
    gate fired, making the assertion vacuous. Asserting the MESSAGE, not just
    the class, is what makes this lethal: it fails if the gate is repointed at
    the wider builder.NESTABLE_TYPE_KEYS (the build would then succeed).
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
