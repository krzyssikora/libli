import pytest
from django.urls import reverse

from grouping.models import Allocation
from grouping.models import GroupMembership
from tests.factories import AllocationFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import make_ca
from tests.factories import make_pa
from tests.factories import make_teacher

pytestmark = pytest.mark.django_db


def _card_list(body):
    """Scope assertions to the list itself — the page also carries the nav, the
    tabs strip and the archived toggle, and a bare substring against the whole
    body is the shadowing shape this repo has been bitten by before."""
    return body.split('class="card-list"')[1].split("</ul>")[0]


def test_list_is_scoped_and_honours_the_archived_toggle(client):
    ca = make_ca(client)
    mine = AllocationFactory(course=CourseFactory(owner=ca), name="Mine")
    AllocationFactory(course=CourseFactory(owner=ca), name="Old", archived=True)
    AllocationFactory(name="Theirs")
    rows = _card_list(client.get(reverse("grouping:allocation_list")).content.decode())
    assert "Mine" in rows
    assert "Old" not in rows
    assert "Theirs" not in rows
    assert reverse("grouping:allocation_edit", args=[mine.pk]) in rows
    assert reverse("grouping:allocation_assign", args=[mine.pk]) in rows
    rows = _card_list(
        client.get(reverse("grouping:allocation_list") + "?archived=1").content.decode()
    )
    assert "Old" in rows
    assert "Mine" not in rows


def test_teacher_gets_403(client):
    make_teacher(client)
    a = AllocationFactory()
    assert client.get(reverse("grouping:allocation_list")).status_code == 403
    edit_url = reverse("grouping:allocation_edit", args=[a.pk])
    assert client.get(edit_url).status_code == 403


def test_ca_cannot_create_on_an_unowned_course(client):
    make_ca(client)
    theirs = CourseFactory()
    resp = client.post(
        reverse("grouping:allocation_create"), {"name": "X", "course": theirs.pk}
    )
    assert resp.status_code == 200  # re-render, not a redirect
    assert "course" in resp.context["form"].errors
    assert Allocation.objects.count() == 0


def test_archive_toggles_both_ways(client):
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    client.post(reverse("grouping:allocation_archive", args=[a.pk]))
    a.refresh_from_db()
    assert a.archived is True
    client.post(reverse("grouping:allocation_archive", args=[a.pk]))
    a.refresh_from_db()
    assert a.archived is False


def test_delete_view_nulls_the_fk_and_keeps_memberships(client):
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    group = GroupFactory(course=a.course, allocation=a)
    GroupMembershipFactory(group=group)
    resp = client.post(reverse("grouping:allocation_delete", args=[a.pk]))
    assert resp.status_code == 302
    group.refresh_from_db()
    assert group.allocation_id is None
    assert GroupMembership.objects.filter(group=group).count() == 1


def test_ca_sees_the_admin_menu_allocations_link(client):
    """Scoped to the admin menu panel — /manage/allocations/ also appears in the
    tabs strip, and a bare substring assertion would be satisfied by either."""
    make_ca(client)
    body = client.get(reverse("grouping:group_list")).content.decode()
    panel = body.split("data-menu-panel")[1].split("</div>")[0]
    assert reverse("grouping:allocation_list") in panel
