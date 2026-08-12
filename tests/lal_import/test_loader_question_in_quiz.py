"""The LAL loader's lesson-only rule for NESTED questions (design section 6.3,
authority 5).

The loader builds nested Element rows directly, bypassing `builder` entirely, so
resolve_scope / paste_allowed / validate_nesting never see this path. The guard
sits at the TOP of build_element, keyed on `parent is not None`, because the
loader has TWO recursive nesting sites and they are not equally guarded: the
spoiler branch enforces LAL_SPOILER_CHILD_TYPES, while the tabs branch recurses
with no allowlist and no unit-type check at all.

These files carry no module-level `pytestmark`, so every test needs its own
@pytest.mark.django_db.
"""

import pytest

from courses.lal_loader.builders import LoaderError
from courses.lal_loader.builders import build_element
from courses.models import Element
from tests.factories import make_course_with_unit
from tests.factories import make_quiz_unit


@pytest.mark.django_db
def test_fillblank_in_a_spoiler_in_a_quiz_is_refused():
    """The spoiler path -- fill_blank is the only question type its allowlist
    admits, so this is the only question reachable that way.

    The assertion is on the MESSAGE: the spoiler branch raises LoaderError too
    (for a child outside LAL_SPOILER_CHILD_TYPES), so `pytest.raises(LoaderError)`
    alone would stay green if the new guard never fired and the child were merely
    rejected for the wrong reason.
    """
    course, _lesson = make_course_with_unit()
    quiz = make_quiz_unit(course=course)
    spoiler = {
        "type": "spoiler",
        "label": "Hint",
        "elements": [{"type": "fillblank", "stem": "Cap is {{paris}}.", "blanks": []}],
    }
    with pytest.raises(LoaderError) as exc:
        build_element(
            course, quiz, spoiler, source_root="", source_dir="", allow_html=False
        )
    assert "may not be nested in quiz unit" in str(exc.value)


@pytest.mark.django_db
def test_choice_in_a_tabs_element_in_a_quiz_is_refused():
    """The tabs path has NO allowlist at all, so a spoiler-only gate leaves this
    green. This is the case that proves the guard sits at build_element.

    "choice" is also not spellable through the spoiler branch, so this is the only
    place the SIX-member LAL_QUESTION_TYPES is exercised beyond fill_blank.
    """
    course, _lesson = make_course_with_unit()
    quiz = make_quiz_unit(course=course)
    tabs = {
        "type": "tabs",
        "tabs": [
            {
                "id": "t000000",
                "label": "Sposób I",
                "elements": [
                    {
                        "type": "choice",
                        "stem": "Pick one.",
                        "choices": [
                            {"text": "right", "is_correct": True},
                            {"text": "wrong"},
                        ],
                    }
                ],
            }
        ],
    }
    with pytest.raises(LoaderError) as exc:
        build_element(
            course, quiz, tabs, source_root="", source_dir="", allow_html=False
        )
    assert "may not be nested in quiz unit" in str(exc.value)


@pytest.mark.django_db
def test_flipping_to_quiz_while_dropping_the_nested_question_is_accepted():
    """upsert_node runs BEFORE rebuild_unit_elements, which deletes every element
    first -- so a guard on the FLIP would stale-read the previous run and refuse a
    legal manifest revision. The child-creation guard sees the NEW unit_type and
    the NEW children, and transaction.atomic rolls the flip back on refusal.

    Same container, same quiz unit, question child dropped: it must build. Without
    this, a guard keyed on `unit.unit_type == QUIZ` alone -- refusing every nested
    row in a quiz -- would pass both tests above.
    """
    course, _lesson = make_course_with_unit()
    quiz = make_quiz_unit(course=course)
    tabs = {
        "type": "tabs",
        "tabs": [
            {
                "id": "t000000",
                "label": "Sposób I",
                "elements": [{"type": "text", "body": "<p>a</p>"}],
            }
        ],
    }

    build_element(course, quiz, tabs, source_root="", source_dir="", allow_html=False)

    # The nested text row really was created -- otherwise "no exception" would be
    # satisfied by a build that never recursed at all.
    assert Element.objects.filter(unit=quiz, parent__isnull=False).count() == 1
