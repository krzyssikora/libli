import re

import pytest

from courses.rollups import build_outline
from courses.rollups import build_unit_nav
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UnitProgressFactory
from tests.factories import make_verified_user


def _make_student(username):
    """A verified, enrollable user. Mirrors the file's existing factory idiom."""
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _course_with_part():
    course = CourseFactory()
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, order=0
    )
    l1 = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=0,
        obligatory=True,
    )
    l2 = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=1,
        obligatory=True,
    )
    return course, part, l1, l2


@pytest.mark.django_db
def test_unit_shell_wraps_lesson_article_and_keeps_seen_hook(client):
    course, part, l1, l2 = _course_with_part()
    user = make_verified_user(
        username="r1", email="r1@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=user, course=course)
    UnitProgressFactory(student=user, unit=l1, completed=True)
    client.force_login(user)

    html = client.get(f"/courses/{course.slug}/u/{l2.pk}/").content.decode()
    # Shell wraps the page.
    assert "unit-shell" in html
    # The seen-tracking article is intact (progress.js depends on it).
    assert 'class="lesson"' in html and "data-seen-url=" in html
    # Tree landmark + current highlight + completed badge.
    assert "aria-label" in html and "unit-tree" in html
    assert 'aria-current="page"' in html
    assert "badge--done" in html  # l1 completed → ✓ in the tree
    # Footer Prev shows the neighbour title — scope to the footer, since l1.title
    # also appears in the tree on every page (a bare `l1.title in html` would pass
    # even with a broken footer). Parse the footer region and assert the prev navtitle.
    foot = re.search(r'<footer class="unit-foot".*?</footer>', html, re.S).group(0)
    assert "unit-foot__nav" in foot and l1.title in foot  # prev neighbour in footer
    # Course hairline present (course has required units).
    assert "unit-foot__course" in html


@pytest.mark.django_db
def test_unit_shell_first_unit_disables_prev(client):
    course, part, l1, l2 = _course_with_part()
    user = make_verified_user(
        username="r2", email="r2@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=user, course=course)
    client.force_login(user)

    html = client.get(f"/courses/{course.slug}/u/{l1.pk}/").content.decode()
    # Disabled prev is a non-focusable span, not an <a>.
    assert '<span class="unit-foot__nav unit-foot__nav--disabled"' in html


@pytest.mark.django_db
def test_unit_shell_part_chip_hidden_for_root_unit(client):
    course = CourseFactory()
    u = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        order=0,
        obligatory=True,
    )
    user = make_verified_user(
        username="r3", email="r3@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=user, course=course)
    client.force_login(user)

    html = client.get(f"/courses/{course.slug}/u/{u.pk}/").content.decode()
    assert "unit-foot__part" not in html  # no enclosing part → chip hidden
    assert "unit-foot__course" in html  # hairline still shown (course has 1 required)


@pytest.mark.django_db
def test_stamp_current_chain_marks_only_the_ancestor_chain():
    """contains_current is True on the current unit and its ancestors, False elsewhere.

    The key is always PRESENT (initialised False), never merely absent — so the
    template's {% if %} has one meaning and this test can assert `is False`.
    """
    from courses.rollups import _stamp_current_chain

    student = _make_student("nav_render")
    course = CourseFactory(owner=student)
    part_a = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    chap_a = ContentNodeFactory(
        course=course, kind="chapter", parent=part_a, unit_type=None
    )
    target = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chap_a
    )
    sibling_chap = ContentNodeFactory(
        course=course, kind="chapter", parent=part_a, unit_type=None
    )
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=sibling_chap
    )
    part_b = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    # A deeper GROUP in an unrelated branch — a sibling root alone would not prove the
    # pass stops descending outside the chain.
    chap_b = ContentNodeFactory(
        course=course, kind="chapter", parent=part_b, unit_type=None
    )
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=chap_b)

    tree = build_outline(course, student)
    _stamp_current_chain(tree, target.pk)

    flags = {}

    def collect(items):
        for d in items:
            flags[d["node"].pk] = d["contains_current"]
            collect(d["children"])

    collect(tree)

    assert flags[target.pk] is True, "the current unit itself must be stamped"
    assert flags[chap_a.pk] is True, "the parent chapter must be stamped"
    assert flags[part_a.pk] is True, "the grandparent part must be stamped"
    assert flags[sibling_chap.pk] is False, "a sibling group must NOT be stamped"
    assert flags[part_b.pk] is False, "an unrelated root must NOT be stamped"
    assert flags[chap_b.pk] is False, (
        "a deeper group in an unrelated branch must NOT be stamped"
    )
    assert all(pk in flags for pk in (target.pk, chap_a.pk, part_a.pk)), (
        "key must be present"
    )


@pytest.mark.django_db
def test_top_level_part_still_returns_a_root_unit():
    """A depth-1 unit's root IS itself — build_unit_nav reads top["is_unit"] to
    suppress the part chip. The stamping pass must therefore stamp unit dicts too."""
    from courses.rollups import _stamp_current_chain
    from courses.rollups import _top_level_part

    student = _make_student("nav_render")
    course = CourseFactory(owner=student)
    root_unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )

    tree = build_outline(course, student)
    _stamp_current_chain(tree, root_unit.pk)
    top = _top_level_part(tree)

    assert top is not None
    assert top["node"].pk == root_unit.pk
    assert top["is_unit"] is True


@pytest.mark.django_db
def test_build_unit_nav_stamps_the_tree_it_returns():
    student = _make_student("nav_render")
    course = CourseFactory(owner=student)
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part
    )

    nav = build_unit_nav(course, student, unit)

    assert nav["tree"][0]["contains_current"] is True
    assert nav["tree"][0]["children"][0]["contains_current"] is True


@pytest.mark.django_db
def test_build_unit_nav_adds_no_queries(django_assert_num_queries):
    """Baseline measured on origin/master before this change: 2 queries.

    The stamping pass is pure dict mutation, so this number must not move. Measuring
    post-change and hard-coding the result would make this assertion incapable of
    detecting the regression it exists to catch.
    """
    student = _make_student("nav_render")
    course = CourseFactory(owner=student)
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part
    )

    with django_assert_num_queries(2):
        build_unit_nav(course, student, unit)
