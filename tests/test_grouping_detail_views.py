import pytest
from django.urls import reverse

from grouping import services
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_group_detail_shows_roster_and_owner(client):
    make_pa(client)
    # display_name="" so the roster renders the username (User.list_display_name
    # falls back to username without a display name / structured first+last).
    owner = UserFactory(username="courseowner", display_name="")
    course = CourseFactory(owner=owner)
    group = GroupFactory(course=course)
    student = UserFactory(username="rosterkid", display_name="")
    services.add_students_to_group(group, [student])
    resp = client.get(reverse("grouping:group_detail", args=[group.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "rosterkid" in body
    assert "courseowner" in body  # owner surfaced in the teacher list
    assert resp.context["student_count"] == 1


def test_my_groups_lists_visible_groups(client):
    make_pa(client)
    GroupFactory()
    resp = client.get(reverse("grouping:my_groups"))
    assert resp.status_code == 200


def test_group_detail_403_without_view_group_perm(client):
    # A user with no grouping perms is stopped at the permission gate (403),
    # before scoping runs.
    from tests.factories import make_login

    make_login(client, "noperms")
    group = GroupFactory()
    resp = client.get(reverse("grouping:group_detail", args=[group.pk]))
    assert resp.status_code == 403


def test_group_detail_404_for_teacher_out_of_scope(client):
    # A Teacher HAS grouping.view_group (passes the gate) but neither manages nor
    # teaches THIS group -> groups_visible_to excludes it -> get_object_or_404 = 404.
    # This is the real security-boundary assertion (distinct from the 403 above).
    from django.contrib.auth.models import Group as AuthGroup

    from institution.roles import seed_roles
    from tests.factories import make_login

    seed_roles()
    teacher = make_login(client, "scopedoutteacher")
    teacher.groups.add(AuthGroup.objects.get(name="Teacher"))
    group = GroupFactory()  # teacher does not teach it
    resp = client.get(reverse("grouping:group_detail", args=[group.pk]))
    assert resp.status_code == 404
