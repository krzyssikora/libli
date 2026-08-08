"""Task 7: the tags and notes hubs that build their unit lists from join rows
(UnitTag, Note) rather than reaching the traversal layer, so parameterising
units_in_order (Task 6) filters nothing on them. courses.access.exclude_foreign_drafts
/ foreign_draft_q are the per-course filter these hubs need instead.
"""

import pytest

from notes import services as note_services
from tags import services as tag_services
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import NoteFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_units_by_tag_drops_drafted_unit_for_non_author_keeps_for_owner():
    """WR15. A student tags a unit that is later drafted by the course's
    author: the student's tags hub (units_by_tag) drops it from the tag's
    grouping. The author's own units_by_tag keeps it.

    Mutant: rely on the traversal keyword -- units_by_tag builds from UnitTag
    rows and filters nothing, so a student keeps seeing a live link to a
    drafted unit.
    """
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    unit = ContentNodeFactory(course=course, published=False, title="Drafted")
    tag_services.tag_unit(student, unit, "exam")
    tag_services.tag_unit(owner, unit, "exam")

    [(_tag, grouped_student)] = tag_services.units_by_tag(student)
    assert grouped_student == {}  # drafted unit dropped, zero-unit tag retained

    [(_tag, grouped_owner)] = tag_services.units_by_tag(owner)
    assert grouped_owner[course] == [unit]


def test_units_by_tag_keeps_managed_course_drafts_and_drops_others_in_one_result():
    """WR15b. A user manages course A (owner) but not course B (merely
    enrolled); both hold a drafted unit tagged with the SAME tag. Their
    units_by_tag must keep A's drafted unit and drop B's, in one result set.

    Mutant: a single can_see_drafts boolean -- it cannot even be evaluated,
    since these queries take only `author`.
    """
    user = UserFactory()
    course_a = CourseFactory(title="A-managed", owner=user)
    course_b = CourseFactory(title="B-not-managed")
    EnrollmentFactory(student=user, course=course_b)
    unit_a = ContentNodeFactory(course=course_a, published=False, title="Ua")
    unit_b = ContentNodeFactory(course=course_b, published=False, title="Ub")
    tag_services.tag_unit(user, unit_a, "exam")
    tag_services.tag_unit(user, unit_b, "exam")

    [(_tag, grouped)] = tag_services.units_by_tag(user)
    assert grouped[course_a] == [unit_a]
    assert course_b not in grouped


def test_course_notes_drops_drafted_lesson_note_for_non_author_keeps_for_author():
    """WR15d. The per-course notes hub (course_notes) drops a note on a
    drafted lesson for a student, keeps it for the author.

    Mutant: leave its units_in_order call unparameterised -> it inherits the
    "keep" default and leaks the drafted unit's title and live link. This is
    the one surface in the table that filters through the traversal keyword,
    so WR15's mutant is the opposite direction and green here.
    """
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    unit = ContentNodeFactory(course=course, published=False, title="Drafted-Lesson")
    NoteFactory(author=owner, unit=unit, body="owner note")

    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    NoteFactory(author=student, unit=unit, body="student note")

    owner_rows = note_services.course_notes(owner, course, drafts="keep")
    assert unit.pk in {r["unit"].pk for r in owner_rows}

    student_rows = note_services.course_notes(student, course, drafts="hide")
    assert unit.pk not in {r["unit"].pk for r in student_rows}
