import pytest

from courses.models import Enrollment
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import UnitProgressFactory
from tests.factories import UserFactory
from tests.factories import make_login
from tests.factories import make_pa


def _course_with_lesson(owner):
    course = CourseFactory(owner=owner)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None)
    les = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, obligatory=True
    )
    return course, ch, les


@pytest.mark.django_db
def test_matrix_renders_for_owner_with_progress_default(client):
    owner = make_login(client, "owner")
    course, ch, les = _course_with_lesson(owner)
    student = UserFactory()
    Enrollment.objects.create(student=student, course=course)
    UnitProgressFactory(student=student, unit=les, completed=True)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/")
    assert resp.status_code == 200
    assert resp.context["mode"] == "progress"
    assert resp.context["matrix"]["rows"][0]["cells"][0]["percent"] == 100
    assert b"100%" in resp.content


@pytest.mark.django_db
def test_matrix_mode_results_and_lenient_mode_param(client):
    owner = make_login(client, "owner")
    course, ch, les = _course_with_lesson(owner)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/?mode=results")
    assert resp.context["mode"] == "results"
    # garbage mode -> progress
    resp2 = client.get(f"/manage/courses/{course.slug}/analytics/?mode=banana")
    assert resp2.context["mode"] == "progress"


@pytest.mark.django_db
def test_matrix_controls_round_trip_both_params(client):
    """Scope form carries mode; mode toggle links carry scope (spec §6)."""
    owner = make_login(client, "owner")
    course, ch, les = _course_with_lesson(owner)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/?mode=results")
    html = resp.content.decode()
    # the scope GET form preserves mode so changing scope keeps Results
    assert '<input type="hidden" name="mode" value="results">' in html
    # the toggle links preserve the current scope
    assert "scope=all&mode=progress" in html or "scope=all&amp;mode=progress" in html


@pytest.mark.django_db
def test_matrix_404_for_non_staff_outsider(client):
    make_login(client, "nobody")
    course = CourseFactory(owner=UserFactory())
    resp = client.get(f"/manage/courses/{course.slug}/analytics/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_matrix_group_scope_filters_rows(client):
    pa = make_pa(client)  # noqa: F841
    course = CourseFactory()
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None)  # noqa: F841
    g = GroupFactory(course=course)
    m = GroupMembershipFactory(group=g)
    other = UserFactory()
    Enrollment.objects.create(student=other, course=course)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/?scope=group:{g.pk}")
    students = [r["student"].pk for r in resp.context["matrix"]["rows"]]
    assert students == [m.student_id]


@pytest.mark.django_db
def test_matrix_cells_decorated_with_band_colors(client):
    owner = make_login(client, "owner")
    course, ch, les = _course_with_lesson(owner)
    student = UserFactory()
    Enrollment.objects.create(student=student, course=course)
    UnitProgressFactory(student=student, unit=les, completed=True)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/")
    cell = resp.context["matrix"]["rows"][0]["cells"][0]
    assert cell["color"] is not None and cell["text_color"] is not None
