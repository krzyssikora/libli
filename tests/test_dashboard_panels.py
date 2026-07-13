import pytest
from django.urls import reverse

from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_teacher

pytestmark = pytest.mark.django_db


def _teaching_setup(client, username, *, archived=False):
    user = make_login(client, username)
    course = CourseFactory(title="Taught Course")
    group = GroupFactory(course=course, archived=archived)
    group.teachers.add(user)
    return user, course


def test_teaching_panel_lists_taught_course_with_links(client):
    _user, course = _teaching_setup(client, "dash_teach")
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    assert 'data-section="teaching"' in body
    assert "Taught Course" in body
    assert reverse("courses:course_outline", kwargs={"slug": course.slug}) in body
    assert reverse("courses:manage_analytics", kwargs={"slug": course.slug}) in body


def test_teaching_panel_excludes_archived_group_course(client):
    _user, course = _teaching_setup(client, "dash_teach_arch", archived=True)
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    # archived-group course is not listed; no data-section=teaching for this user
    assert "Taught Course" not in body


def test_group_only_teacher_sees_teaching_not_generic_not_browse(client):
    # make_login user is NOT in the Teacher role group (is_teacher flag False),
    # but teaches via Group.teachers -> the widened gate must show Teaching and
    # suppress both the generic empty-state and the student Browse button.
    _user, _course = _teaching_setup(client, "dash_group_only")
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    assert 'data-section="teaching"' in body
    assert 'data-section="generic"' not in body
    # Assert the DASHBOARD Browse button is suppressed, scoped to its wrapper
    # (`<p class="dash-browse">…Browse courses…</p>`). Do NOT assert
    # `reverse("courses:catalog") not in body`: the nav still renders the
    # students-only Browse link at this point (it is not removed until Task 4),
    # so the whole-body check would false-fail here.
    assert "dash-browse" not in body


def test_role_teacher_with_no_taught_courses_sees_empty_state(client):
    make_teacher(client, "dash_role_teacher")  # Teacher role -> is_teacher True
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    assert 'data-section="teaching"' in body
    assert "No classes assigned yet." in body


def test_studio_panel_owner_sees_title_list_and_all_courses(client):
    owner = make_login(client, "studio_owner")
    course = CourseFactory(title="My Owned Course", owner=owner)
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    assert 'data-section="manage"' in body
    assert ">Studio<" in body  # panel title
    assert "My Owned Course" in body
    assert reverse("courses:manage_builder", kwargs={"slug": course.slug}) in body
    assert reverse("courses:manage_course_list") in body  # "All courses"


def test_studio_new_course_hidden_for_owner_without_add_course(client):
    owner = make_login(client, "studio_plain_owner")
    CourseFactory(title="Owned", owner=owner)
    resp = client.get(reverse("home"))
    # can_manage_courses True via ownership, but no add_course perm
    assert reverse("courses:manage_course_create") not in resp.content.decode()


def test_studio_new_course_shown_for_add_course_holder(client):
    from core.services import mark_onboarded

    make_pa(client, "studio_pa")  # PLATFORM_ADMIN holds courses.add_course
    mark_onboarded()  # avoid the first-run wizard redirect
    resp = client.get(reverse("home"))
    assert reverse("courses:manage_course_create") in resp.content.decode()
