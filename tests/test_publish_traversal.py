import pytest

from courses.rollups import build_outline
from courses.rollups import unit_is_visible
from courses.rollups import units_in_order
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import UserFactory


@pytest.mark.django_db
def test_unknown_drafts_mode_raises():
    """A typo like "keep_with_data" falling through to "keep" is a LEAK that
    no behavioural test would catch.
    """
    course = CourseFactory()
    with pytest.raises(ValueError):
        units_in_order(course, drafts="keep_with_data")


@pytest.mark.django_db
def test_keep_with_data_requires_with_data_even_on_an_empty_course():
    """ANA7 half one. The fixture has ZERO units, deliberately.

    Mutant: put the guard inside unit_is_visible -> it runs per node, so a
    zero-unit course never reaches it and the check is absent exactly where a
    brand-new course is concerned. Only a zero-unit fixture proves the guard
    runs BEFORE any traversal.
    """
    course = CourseFactory()  # no units at all
    assert course.nodes.count() == 0
    with pytest.raises(ValueError):
        build_outline(course, UserFactory(), drafts="keep-with-data")


@pytest.mark.django_db
def test_empty_with_data_is_legitimate():
    """ANA7 half two. The fixture has >=1 unit, deliberately — on a zero-unit
    course "does not raise" is vacuously true of every implementation.

    An empty with_data is the ordinary state of a course no student has
    touched. It must NOT raise.
    """
    course = CourseFactory()
    ContentNodeFactory(course=course, kind="unit", published=True)
    build_outline(course, UserFactory(), drafts="keep-with-data", with_data=frozenset())


@pytest.mark.django_db
def test_low_level_helpers_default_to_keep():
    """The "keep" default means adding the keyword changes NO existing
    behaviour.

    units_in_order's real production callers are exactly two --
    progress_reset (views.py:615) and notes.services.course_notes
    (notes/services.py:116) -- plus quiz_units_in_order internally. The
    builder and link_picker use _children_map, and build_export walks
    course.nodes.all() itself; none of the three calls this.

    The concrete reason for "keep": a "hide" default would silently narrow
    progress_reset's `targets`, the UNFILTERED list that drives the write
    (Task 6 Step 5).
    """
    course = CourseFactory()
    draft = ContentNodeFactory(course=course, kind="unit", published=False)
    assert draft in units_in_order(course)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "drafts,published,in_data,expected",
    [
        ("hide", True, False, True),
        ("hide", False, False, False),
        ("keep", False, False, True),
        ("keep-with-data", False, False, False),
        ("keep-with-data", False, True, True),
        ("keep-with-data", True, False, True),
    ],
)
def test_unit_is_visible_truth_table(drafts, published, in_data, expected):
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", published=published)
    with_data = frozenset({unit.pk}) if in_data else frozenset()
    assert unit_is_visible(unit, drafts=drafts, with_data=with_data) is expected
