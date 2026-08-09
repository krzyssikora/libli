"""Task 5: build_outline draft filtering + the two pruning passes.

Every fixture puts its units under a Part that keeps at least one PUBLISHED
unit, EXCEPT OUT5/OUT5b whose whole point is a root-level Part with only
drafts — those add a second, published Part alongside so the tree is not
empty and `roots[0]` stays safe.
"""

import pytest

from courses.rollups import build_outline
from courses.rollups import build_unit_nav
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UnitProgressFactory
from tests.factories import UserFactory


@pytest.mark.django_db
def test_prev_next_skips_over_a_draft():
    """OUT1: one Part; lesson units A, B, C in order; B is drafted. From A,
    build_unit_nav's next must be C — it steps OVER the draft."""
    course = CourseFactory()
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    a = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part, order=0
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=1,
        published=False,
    )
    c = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part, order=2
    )

    nav = build_unit_nav(course, student, a, drafts="hide")
    assert nav["next"].pk == c.pk


@pytest.mark.django_db
def test_required_total_excludes_drafts():
    """OUT2: 10 obligatory lesson units under one Part; 7 drafted, 3 stay
    published. The student's root required_total is 3."""
    course = CourseFactory()
    student = UserFactory()
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    for i in range(10):
        ContentNodeFactory(
            course=course,
            kind="unit",
            unit_type="lesson",
            parent=part,
            order=i,
            obligatory=True,
            published=(i < 3),
        )

    roots = build_outline(course, student, drafts="hide")
    assert sum(r["required_total"] for r in roots) == 3


@pytest.mark.django_db
def test_a_completed_unit_later_drafted_leaves_both_counters():
    """OUT3: one Part, two obligatory lesson units — the subject unit (with a
    completed UnitProgress row) and a published sibling that keeps the Part
    alive. Drafting the subject unit must drop it from BOTH required_total and
    required_done, and must NOT touch the UnitProgress row."""
    course = CourseFactory()
    student = UserFactory()
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    subject = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=0,
        obligatory=True,
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=1,
        obligatory=True,
    )
    progress = UnitProgressFactory(student=student, unit=subject, completed=True)

    roots = build_outline(course, student, drafts="hide")
    assert sum(r["required_total"] for r in roots) == 2
    assert sum(r["required_done"] for r in roots) == 1

    subject.published = False
    subject.save(update_fields=["published"])

    roots = build_outline(course, student, drafts="hide")
    assert sum(r["required_total"] for r in roots) == 1
    assert sum(r["required_done"] for r in roots) == 0

    progress.refresh_from_db()
    assert progress.completed is True


@pytest.mark.django_db
def test_additional_done_excludes_drafts_and_the_dict_is_gone():
    """OUT4: a Part holding a published obligatory lesson (keeps the Part
    alive) plus a non-obligatory, published, completed unit. Drafting that
    unit must zero additional_done AND remove its dict from the whole tree."""
    course = CourseFactory()
    student = UserFactory()
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=0,
        obligatory=True,
        published=True,
    )
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=1,
        obligatory=False,
        published=True,
    )
    UnitProgressFactory(student=student, unit=unit, completed=True)

    roots = build_outline(course, student, drafts="hide")
    assert sum(r["additional_done"] for r in roots) == 1

    unit.published = False
    unit.save(update_fields=["published"])

    roots = build_outline(course, student, drafts="hide")
    assert sum(r["additional_done"] for r in roots) == 0

    def _all_dicts(nodes):
        for d in nodes:
            yield d
            yield from _all_dicts(d["children"])

    assert all(d["node"].pk != unit.pk for d in _all_dicts(roots))


@pytest.mark.django_db
def test_a_root_level_part_with_only_drafts_is_pruned():
    """OUT5: a root-level Part holding two draft lesson units, plus a second
    published Part alongside so the tree is not empty. The empty Part must be
    pruned from `roots` (not just from some parent's children — it HAS no
    parent)."""
    course = CourseFactory()
    student = UserFactory()
    draft_part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, order=0
    )
    d1 = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=draft_part,
        order=0,
        published=False,
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=draft_part,
        order=1,
        published=False,
    )
    published_part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, order=1
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=published_part,
        order=0,
        published=True,
    )

    roots = build_outline(course, student, drafts="hide")
    assert len(roots) == 1
    assert roots[0]["node"].pk == published_part.pk

    d1.published = True
    d1.save(update_fields=["published"])

    roots = build_outline(course, student, drafts="hide")
    assert {r["node"].pk for r in roots} == {draft_part.pk, published_part.pk}


@pytest.mark.django_db
def test_pruning_is_mode_dependent():
    """OUT5b: a root-level Part holding one draft lesson unit with no
    UnitProgress and no QuizSubmission. drafts="keep" keeps the Part (the
    unit is retained). drafts="keep-with-data" with an empty with_data ALSO
    keeps the Part, even though the unit is filtered out — a teacher's
    breakdown must preserve the course's shape."""
    course = CourseFactory()
    student = UserFactory()
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=0,
        published=False,
    )

    roots_keep = build_outline(course, student, drafts="keep")
    assert len(roots_keep) == 1
    assert roots_keep[0]["children"] != []

    roots_kwd = build_outline(
        course, student, drafts="keep-with-data", with_data=frozenset()
    )
    assert len(roots_kwd) == 1
    assert roots_kwd[0]["node"].pk == part.pk
