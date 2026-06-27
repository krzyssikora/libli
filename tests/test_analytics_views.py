import pytest

from courses.color_bands import course_color_bands
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


@pytest.mark.django_db
def test_bands_page_owner_pa_only(client):
    teacher = make_login(client, "t")
    course = CourseFactory(owner=UserFactory())
    # a group teacher can view the matrix but NOT the bands page
    g = GroupFactory(course=course)
    g.teachers.add(teacher)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/colors/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_bands_save_persists_and_redirects_with_state(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    resp = client.post(
        f"/manage/courses/{course.slug}/analytics/colors/",
        {
            "color_0": "#e5e5e7",
            "color_1": "#e98b5a",
            "color_2": "#f1c453",
            "color_3": "#52b06a",
            "color_4": "#1e8e4a",
            "min_1": "30",
            "min_2": "55",
            "min_3": "70",
            "min_4": "85",
            "scope": "all",
            "mode": "results",
        },
    )
    assert resp.status_code == 302
    assert "mode=results" in resp.url
    course.refresh_from_db()
    assert [b["min"] for b in course_color_bands(course)] == [0, 30, 55, 70, 85]


@pytest.mark.django_db
def test_bands_reset_clears_to_defaults(client):
    owner = make_login(client, "owner")
    course = CourseFactory(
        owner=owner, color_bands=[{"key": "none", "min": 0, "color": "#000000"}]
    )
    resp = client.post(
        f"/manage/courses/{course.slug}/analytics/colors/",
        {"reset": "1", "scope": "all", "mode": "progress"},
    )
    assert resp.status_code == 302
    course.refresh_from_db()
    assert course.color_bands == []
