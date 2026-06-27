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


# ---------------------------------------------------------------------------
# Task 5: per-student breakdown
# ---------------------------------------------------------------------------


def _course_with_section_lesson(owner):
    course = CourseFactory(owner=owner)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch"
    )
    sec = ContentNodeFactory(
        course=course, kind="section", unit_type=None, parent=ch, title="Sec"
    )
    les = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=sec,
        obligatory=True,
        title="U",
    )
    return course, ch, sec, les


@pytest.mark.django_db
def test_breakdown_renders_for_owner_with_pills(client):
    from courses.models import QuizSubmission

    owner = make_login(client, "owner")
    course, ch, sec, les = _course_with_section_lesson(owner)
    qz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=ch, title="Qz"
    )
    student = UserFactory(display_name="Ada L.")
    Enrollment.objects.create(student=student, course=course)
    UnitProgressFactory(student=student, unit=les, completed=True)
    from decimal import Decimal

    from courses.models import Element
    from courses.models import QuestionElement
    from courses.models import ShortTextQuestionElement

    q = ShortTextQuestionElement.objects.create(
        stem="q",
        accepted="a",
        marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("10"),
    )
    Element.objects.create(unit=qz, content_object=q)
    QuizSubmission.objects.create(
        student=student,
        unit=qz,
        status="submitted",
        score=Decimal("9"),
        max_score=Decimal("10"),
    )
    resp = client.get(f"/manage/courses/{course.slug}/analytics/student/{student.pk}/")
    assert resp.status_code == 200
    assert b"Ada L." in resp.content
    assert b"90%" in resp.content  # scored pill


@pytest.mark.django_db
def test_breakdown_404_for_student_out_of_reach(client):
    teacher = make_login(client, "teach")
    course = CourseFactory(owner=UserFactory())
    from tests.factories import GroupFactory

    g = GroupFactory(course=course)
    g.teachers.add(teacher)  # teacher reviews g's students only
    outsider = UserFactory()
    Enrollment.objects.create(student=outsider, course=course)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/student/{outsider.pk}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_breakdown_404_for_non_staff(client):
    make_login(client, "nobody")
    course = CourseFactory(owner=UserFactory())
    s = UserFactory()
    resp = client.get(f"/manage/courses/{course.slug}/analytics/student/{s.pk}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_breakdown_awaiting_review_shows_cross_link(client):
    from decimal import Decimal

    from courses.models import Element
    from courses.models import QuestionElement
    from courses.models import QuizSubmission
    from courses.models import ShortTextQuestionElement

    owner = make_login(client, "owner")
    course, ch, sec, les = _course_with_section_lesson(owner)
    qz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=ch, title="Qz"
    )
    q = ShortTextQuestionElement.objects.create(
        stem="q",
        accepted="a",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal("10"),
    )
    Element.objects.create(unit=qz, content_object=q)
    student = UserFactory()
    Enrollment.objects.create(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student,
        unit=qz,
        status="submitted",
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    resp = client.get(f"/manage/courses/{course.slug}/analytics/student/{student.pk}/")
    # cross-link to manage_review_submission
    assert f"/review/{sub.pk}/".encode() in resp.content


# ---------------------------------------------------------------------------
# Task 6: interactive matrix — expand chips, headers, gated student links
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_matrix_expand_renders_chip_and_subcolumns(client):
    owner = make_login(client, "owner")
    course, ch, sec, les = _course_with_section_lesson(owner)
    student = UserFactory()
    Enrollment.objects.create(student=student, course=course)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/?expand={ch.pk}")
    assert resp.status_code == 200
    m = resp.context["matrix"]
    assert [e["pk"] for e in m["expanded_nodes"]] == [ch.pk]
    assert m["columns"][0]["node"].pk == sec.pk  # ch replaced by its child
    html = resp.content.decode()
    assert "Ch ▸ Sec" in html  # breadcrumb column title rendered


@pytest.mark.django_db
def test_matrix_scope_form_carries_expand_hidden_inputs(client):
    owner = make_login(client, "owner")
    course, ch, sec, les = _course_with_section_lesson(owner)
    resp = client.get(f"/manage/courses/{course.slug}/analytics/?expand={ch.pk}")
    html = resp.content.decode()
    assert f'<input type="hidden" name="expand" value="{ch.pk}">' in html


@pytest.mark.django_db
def test_matrix_garbage_expand_is_ignored(client):
    owner = make_login(client, "owner")
    course, ch, sec, les = _course_with_section_lesson(owner)
    resp = client.get(
        f"/manage/courses/{course.slug}/analytics/?expand=abc&expand=999999"
    )
    assert resp.status_code == 200
    assert resp.context["matrix"]["expanded_nodes"] == []


@pytest.mark.django_db
def test_matrix_student_link_gated_on_reviewable(client):
    """Collection scope can show a student the viewer can't drill into -> plain text."""
    from tests.factories import CollectionFactory
    from tests.factories import GroupFactory
    from tests.factories import GroupMembershipFactory

    teacher = make_login(client, "teach")
    course = CourseFactory(owner=UserFactory())
    ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None)
    taught = GroupFactory(course=course)
    taught.teachers.add(teacher)
    untaught = GroupFactory(course=course)
    coll = CollectionFactory(course=course)
    coll.groups.add(taught, untaught)
    mine = GroupMembershipFactory(group=taught)
    theirs = GroupMembershipFactory(group=untaught)
    resp = client.get(
        f"/manage/courses/{course.slug}/analytics/?scope=collection:{coll.pk}"
    )
    rows = {r["student"].pk: r for r in resp.context["matrix"]["rows"]}
    assert rows[mine.student_id]["breakdown_url"]  # drillable
    assert rows[theirs.student_id].get("breakdown_url") is None  # plain text


# ---------------------------------------------------------------------------
# Task 7: colour-bands page round-trips expand
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bands_get_carries_expand_hidden_inputs(client):
    owner = make_login(client, "owner")
    course, ch, sec, les = _course_with_section_lesson(owner)
    resp = client.get(
        f"/manage/courses/{course.slug}/analytics/colors/?scope=all&mode=progress&expand={ch.pk}"
    )
    expected = f'<input type="hidden" name="expand" value="{ch.pk}">'
    assert expected in resp.content.decode()


@pytest.mark.django_db
def test_bands_save_redirect_preserves_expand(client):
    owner = make_login(client, "owner")
    course, ch, sec, les = _course_with_section_lesson(owner)
    resp = client.post(
        f"/manage/courses/{course.slug}/analytics/colors/",
        {
            "scope": "all",
            "mode": "progress",
            "expand": [str(ch.pk)],
            "reset": "1",  # reset path is simplest; exercises the same redirect
        },
    )
    assert resp.status_code == 302
    assert f"expand={ch.pk}" in resp.url
