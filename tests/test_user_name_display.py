"""User.list_display_name / User.sort_name — graceful-degradation naming.

Structured first/last names (populated for SSO users via allauth's default
OIDC given_name/family_name mapping) drive a "First Last" label sorted by
family name; users without them fall back to display_name-or-username, matching
the rest of the app's roster convention.
"""

import pytest

from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _user(**kw):
    # UserFactory sets a Faker display_name by default; override explicitly per case.
    return UserFactory.build(**kw)


def test_first_last_present_gives_first_last_label_and_last_first_sort():
    u = _user(first_name="Anna", last_name="Kowalska", display_name="", username="ak1")
    assert u.list_display_name == "Anna Kowalska"
    assert u.sort_name == "Kowalska Anna"


def test_no_structured_names_falls_back_to_display_name():
    u = _user(first_name="", last_name="", display_name="Anna K.", username="ak1")
    assert u.list_display_name == "Anna K."
    assert u.sort_name == "Anna K."


def test_no_structured_or_display_name_falls_back_to_username():
    u = _user(first_name="", last_name="", display_name="", username="ak1")
    assert u.list_display_name == "ak1"
    assert u.sort_name == "ak1"


def test_partial_structured_name_falls_back_to_display_name():
    # Only one of first/last -> not enough for "First Last"; fall back.
    u = _user(first_name="Anna", last_name="", display_name="Anna K.", username="ak1")
    assert u.list_display_name == "Anna K."
    assert u.sort_name == "Anna K."


def test_distinct_display_name_appended_in_parens():
    u = _user(
        first_name="Robert", last_name="Nowak", display_name="Bob", username="rn1"
    )
    assert u.list_display_name == "Robert Nowak (Bob)"
    assert u.sort_name == "Nowak Robert"


def test_display_name_equal_to_full_name_not_duplicated():
    u = _user(
        first_name="Anna",
        last_name="Kowalska",
        display_name="Anna Kowalska",
        username="ak1",
    )
    assert u.list_display_name == "Anna Kowalska"


def test_display_name_equal_to_a_name_part_not_appended():
    u = _user(
        first_name="Anna", last_name="Kowalska", display_name="Anna", username="ak1"
    )
    assert u.list_display_name == "Anna Kowalska"


def test_surrounding_whitespace_ignored():
    u = _user(
        first_name="  Anna ", last_name=" Kowalska ", display_name="", username="ak1"
    )
    assert u.list_display_name == "Anna Kowalska"
    assert u.sort_name == "Kowalska Anna"
