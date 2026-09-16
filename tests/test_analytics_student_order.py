"""Student order and names in the analytics matrix and gradebook export
(spec §3; T1-T4)."""

import csv
import io

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db

# (username, first, last, display_name). Usernames are in generation order,
# which disagrees with surname order on purpose (T4).
ROSTER = [
    ("a_swiatek", "Iga", "Świątek", "Iga Świątek"),
    ("b_nowakowska", "Beata", "Nowakowska", "Beata Nowakowska"),
    ("c_nowak", "Anna", "Nowak", "Anna Nowak"),
    ("d_zych", "Tomasz", "Zych", "TZ nick"),  # unrelated display name (T3)
    ("e_adamczyk_m", "Mateusz", "Adamczyk", "Mateusz Adamczyk"),
    ("f_adamczyk_k", "Kamil", "Adamczyk", "Kamil Adamczyk"),
    ("g_login", "", "", "Borys"),  # no structured names: sorts by display name
]
# Surname, then first name, Polish alphabetical. Świątek before Zych is the
# polish_sort_key case: by raw codepoint "Ś" sorts after "Z".
EXPECTED_USERNAMES = [
    "f_adamczyk_k",
    "e_adamczyk_m",
    "g_login",
    "c_nowak",
    "b_nowakowska",
    "a_swiatek",
    "d_zych",
]


def _class(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None
    )
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, obligatory=True
    )
    users = {}
    for username, first, last, display in ROSTER:
        user = UserFactory(
            username=username, first_name=first, last_name=last, display_name=display
        )
        EnrollmentFactory(student=user, course=course)
        users[username] = user
    return course, users


def _matrix_usernames(client, course):
    resp = client.get(reverse("courses:manage_analytics", kwargs={"slug": course.slug}))
    assert resp.status_code == 200
    return [row["student"].username for row in resp.context["matrix"]["rows"]]


def _export_rows(client, course, shape):
    body = client.get(
        reverse("courses:manage_analytics_export", kwargs={"slug": course.slug}),
        {"shape": shape, "format": "csv"},
    ).content.decode("utf-8-sig")
    usernames = {username for username, *_rest in ROSTER}
    # Column 1 is Username; the title, subtitle, header, Max and Average rows
    # never carry one of the roster's usernames.
    return [
        row for row in csv.reader(io.StringIO(body)) if row[1:2] and row[1] in usernames
    ]


def test_t4_fixture_username_order_disagrees_with_surname_order():
    assert sorted(EXPECTED_USERNAMES) != EXPECTED_USERNAMES


def test_t1_matrix_lists_students_by_surname_then_first_name(client):
    course, _users = _class(client)
    assert _matrix_usernames(client, course) == EXPECTED_USERNAMES


def test_t1_matrix_subset_keeps_the_same_order(client):
    course, users = _class(client)
    subset = [users["d_zych"], users["a_swiatek"], users["f_adamczyk_k"]]
    resp = client.get(
        reverse("courses:manage_analytics", kwargs={"slug": course.slug}),
        {"student": [u.pk for u in subset]},
    )
    got = [row["student"].username for row in resp.context["matrix"]["rows"]]
    assert got == ["f_adamczyk_k", "a_swiatek", "d_zych"]


@pytest.mark.parametrize("shape", ["matrix", "quiz"])
def test_t2_export_rows_follow_the_same_order(client, shape):
    course, _users = _class(client)
    assert [row[1] for row in _export_rows(client, course, shape)] == EXPECTED_USERNAMES


def _rowheads(client, course):
    html = client.get(
        reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    ).content.decode()
    return BeautifulSoup(html, "html.parser").select("tbody td.analytics__rowhead")


def test_t3_matrix_names_students_first_name_first(client):
    course, _users = _class(client)
    cells = _rowheads(client, course)
    by_text = {cell.get_text(" ", strip=True): cell for cell in cells}
    assert "Mateusz Adamczyk" in by_text
    assert "Borys" in by_text  # no structured names: display name
    assert "Tomasz Zych (TZ nick)" in by_text  # the parenthetical, in full
    # Zych's display name differs from his label, so reverting the aria-label
    # alone renders "Select TZ nick" and goes red.
    checkbox = by_text["Tomasz Zych (TZ nick)"].select_one("input[type=checkbox]")
    assert checkbox["aria-label"] == "Select Tomasz Zych (TZ nick)"


@pytest.mark.parametrize("shape", ["matrix", "quiz"])
def test_t3_export_names_students_first_name_first(client, shape):
    course, _users = _class(client)
    names = [row[0] for row in _export_rows(client, course, shape)]
    assert names == [
        "Kamil Adamczyk",
        "Mateusz Adamczyk",
        "Borys",
        "Anna Nowak",
        "Beata Nowakowska",
        "Iga Świątek",
        "Tomasz Zych (TZ nick)",
    ]
