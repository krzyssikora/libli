import re

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UnitProgressFactory
from tests.factories import make_verified_user


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
    assert "unit-foot__nav--disabled" in html


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
