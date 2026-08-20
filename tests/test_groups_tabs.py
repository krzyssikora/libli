import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from tests.factories import make_ca
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_teacher

pytestmark = pytest.mark.django_db


def test_my_groups_shows_tab_strip_for_view_group_holder(client):
    make_pa(client, "grp_pa")  # holds grouping.view_group
    body = client.get(reverse("grouping:my_groups")).content.decode()
    # both tab links present (the strip)
    assert reverse("grouping:my_groups") in body
    assert reverse("grouping:group_list") in body


def test_group_list_shows_tab_strip_with_manage_active(client):
    make_pa(client, "grp_pa2")
    body = client.get(reverse("grouping:group_list")).content.decode()
    assert reverse("grouping:my_groups") in body
    assert reverse("grouping:group_list") in body


def test_my_groups_no_strip_for_view_collection_only_user(client):
    # A bespoke user with ONLY grouping.view_collection (no standard role has this
    # in isolation; grant the permission directly).
    user = make_login(client, "grp_collonly")
    user.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="grouping", codename="view_collection"
        )
    )
    # drop cached perms so the just-added permission is visible in-request
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    body = client.get(reverse("grouping:my_groups")).content.decode()
    # single tab entitled -> no strip -> the Manage (group_list) link is absent
    assert reverse("grouping:group_list") not in body


def test_tabs_show_allocations_for_a_course_admin(client):
    make_ca(client)
    body = client.get(reverse("grouping:group_list")).content.decode()
    strip = body.split('class="tnhub__tabs"')[1].split("</nav>")[0]
    assert reverse("grouping:allocation_list") in strip


def test_tabs_hide_allocations_from_a_teacher(client):
    make_teacher(client)
    body = client.get(reverse("grouping:my_groups")).content.decode()
    assert 'class="tnhub__tabs"' in body  # the strip still renders
    strip = body.split('class="tnhub__tabs"')[1].split("</nav>")[0]
    assert reverse("grouping:allocation_list") not in strip
