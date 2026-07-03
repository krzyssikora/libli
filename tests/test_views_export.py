# tests/test_views_export.py
import pytest
from django.urls import reverse

from courses.models import Enrollment
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import UserFactory
from tests.factories import make_login


def _chapter(course):
    return ContentNodeFactory(
        course=course, kind="chapter", parent=None, unit_type=None
    )


def _quiz(course, parent, **kw):
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=parent, **kw
    )


def _url(course):
    return reverse("courses:manage_analytics_export", kwargs={"slug": course.slug})


@pytest.mark.django_db
def test_export_requires_review_reach(client):
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    make_login(client, "outsider")
    resp = client.get(_url(course), {"shape": "matrix", "format": "csv"})
    assert resp.status_code == 404


@pytest.mark.django_db
def test_export_csv_content_type_and_disposition(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    _chapter(course)
    resp = client.get(
        _url(course), {"shape": "matrix", "format": "csv", "mode": "progress"}
    )
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    assert "attachment" in resp["Content-Disposition"]
    assert course.slug in resp["Content-Disposition"]


@pytest.mark.django_db
def test_export_xlsx_and_html_dispatch(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    _chapter(course)
    xlsx = client.get(_url(course), {"shape": "quiz", "format": "xlsx"})
    assert xlsx["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    html = client.get(_url(course), {"shape": "quiz", "format": "html"})
    assert html.status_code == 200
    assert b"Quiz gradebook" in html.content or b"gb-print" in html.content


@pytest.mark.django_db
def test_export_title_reflects_resolved_scope_not_forged(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    _chapter(course)
    # forged group scope the owner can't reach -> falls back to "all my students"
    resp = client.get(
        _url(course), {"shape": "matrix", "format": "csv", "scope": "group:99999"}
    )
    body = resp.content.decode("utf-8-sig")
    assert "All my students" in body
    assert "group:99999" not in body


@pytest.mark.django_db
def test_export_unknown_params_coerce_to_defaults(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    _chapter(course)
    resp = client.get(_url(course), {"shape": "junk", "format": "junk", "mode": "junk"})
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")  # format defaulted to csv


@pytest.mark.django_db
def test_export_restricted_to_group_teachers_students(client):
    # The central safety property: a group teacher's export never reveals a
    # student outside the groups they teach (spec §7 scope enforcement).
    course = CourseFactory(owner=UserFactory())
    _chapter(course)
    teacher = make_login(client, "teacher")
    g = GroupFactory(course=course)
    g.teachers.add(teacher)  # gives review reach over g's members only
    member = GroupMembershipFactory(group=g).student
    outsider = UserFactory(username="outsider")
    Enrollment.objects.create(student=outsider, course=course)  # enrolled, not in g
    body = client.get(
        _url(course), {"shape": "matrix", "format": "csv"}
    ).content.decode("utf-8-sig")
    assert member.username in body
    assert "outsider" not in body


@pytest.mark.django_db
def test_export_honours_student_subset(client):
    # The cherry-pick subset (C3): export contains exactly the selected students.
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    _chapter(course)
    a = UserFactory(username="alpha")
    b = UserFactory(username="bravo")
    Enrollment.objects.create(student=a, course=course)
    Enrollment.objects.create(student=b, course=course)
    body = client.get(
        _url(course), {"shape": "matrix", "format": "csv", "student": a.pk}
    ).content.decode("utf-8-sig")
    assert "alpha" in body and "bravo" not in body
    # a forged/out-of-pool student pk is intersected away -> full scope (both shown)
    full = client.get(
        _url(course), {"shape": "matrix", "format": "csv", "student": "999999"}
    ).content.decode("utf-8-sig")
    assert "alpha" in full and "bravo" in full
