"""Long node titles stay identifiable in the contents tree.

Unit labels are truncated with `text-overflow: ellipsis` in a 14rem rail, so a
set of units whose names share a prefix and differ only near the end all render
as the same "Przedziały liczbowe i dział…" and are impossible to tell apart.

Two halves, because hover does not exist on touch:
  * every tree row carries `title` (desktop hover + assistive tech), and
  * the mobile drawer lets unit labels WRAP instead of truncating, matching what
    group titles already do there.
"""

import re

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_verified_user

LONG_UNIT = "Przedziały liczbowe i działania na przedziałach — część 1"
LONG_UNIT_2 = "Przedziały liczbowe i działania na przedziałach — część 2"
LONG_GROUP = "Funkcje wymierne i ich własności — rozdział pierwszy"


def _seed(username):
    course = CourseFactory()
    group = ContentNodeFactory(
        course=course,
        kind="chapter",
        parent=None,
        unit_type=None,
        order=0,
        title=LONG_GROUP,
    )
    u1 = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=group,
        order=0,
        title=LONG_UNIT,
    )
    u2 = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=group,
        order=1,
        title=LONG_UNIT_2,
    )
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=user, course=course)
    return course, u1, u2, user


@pytest.mark.django_db
def test_unit_rows_carry_a_title_attribute_with_the_full_name(client):
    """Hovering a truncated row must reveal which unit it actually is."""
    course, u1, u2, user = _seed("tt_unit")
    client.force_login(user)
    html = client.get(f"/courses/{course.slug}/u/{u1.pk}/").content.decode()

    for label in re.findall(r"<span class=\"unit-tree__label\"[^>]*>", html):
        assert "title=" in label, f"unit label without a title attribute: {label}"
    assert f'title="{LONG_UNIT}"' in html
    assert f'title="{LONG_UNIT_2}"' in html


@pytest.mark.django_db
def test_group_rows_carry_a_title_attribute_with_the_full_name(client):
    """Group titles truncate in the collapsed rail too."""
    course, u1, u2, user = _seed("tt_group")
    client.force_login(user)
    html = client.get(f"/courses/{course.slug}/u/{u1.pk}/").content.decode()

    for title in re.findall(r"<span class=\"unit-tree__grouptitle\"[^>]*>", html):
        assert "title=" in title, f"group title without a title attribute: {title}"
    assert f'title="{LONG_GROUP}"' in html


def test_drawer_lets_unit_labels_wrap():
    """The mobile drawer has no hover, so the name must be visible outright.

    Pinned in CSS because nothing else ties the drawer scope to the label rule.
    """
    from pathlib import Path

    css = (
        Path(__file__).resolve().parent.parent
        / "courses/static/courses/css/courses.css"
    ).read_text(encoding="utf-8")

    match = re.search(r"\.unit-drawer__list\s+\.unit-tree__label\s*\{([^}]*)\}", css)
    assert match, "no .unit-drawer__list .unit-tree__label rule — labels still truncate"
    body = match.group(1)
    assert "white-space: normal" in body, body
    assert "text-overflow: clip" in body, body
