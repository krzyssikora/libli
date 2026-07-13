import pytest
from django.urls import reverse

from tests.factories import make_pa
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


# Helper: match a nav link by its rendered form `class="app-nav__link" href="<url>"`.
# Asserting on this form (not a bare url substring) is robust because `/courses/`
# is a substring of `/manage/courses/` and of outline links.
def _nav_link(url):
    return f'app-nav__link" href="{url}"'


def test_nav_has_no_courses_link(client):
    user = make_verified_user(username="nav_noc", email="nav_noc@school.edu")
    client.force_login(user)
    body = client.get(reverse("home")).content.decode()
    assert _nav_link(reverse("courses:my_courses")) not in body


def test_nav_shows_studio_not_manage_for_change_course_holder(client):
    from core.services import mark_onboarded

    make_pa(client, "nav_pa")  # holds courses.change_course
    mark_onboarded()
    body = client.get(reverse("home")).content.decode()
    # The nav Studio link points at the ledger and is labelled "Studio".
    assert _nav_link(reverse("courses:manage_course_list")) + ">Studio<" in body
    # The old nav link labelled "Manage" (same href) is gone.
    assert _nav_link(reverse("courses:manage_course_list")) + ">Manage<" not in body


def test_nav_single_groups_link_targets_my_groups(client):
    from core.services import mark_onboarded

    make_pa(client, "nav_pa_groups")  # holds grouping.view_group (+ view_collection)
    mark_onboarded()
    body = client.get(reverse("home")).content.decode()
    # Single Groups entry -> my_groups, labelled "Groups".
    assert _nav_link(reverse("grouping:my_groups")) + ">Groups<" in body
    # The old separate nav link to group_list ("Manage groups" entry) is gone
    # from the nav.
    assert _nav_link(reverse("grouping:group_list")) not in body
