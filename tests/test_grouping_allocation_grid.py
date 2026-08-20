import pytest
from django.urls import reverse

from grouping import services
from grouping.models import CohortMembership
from grouping.models import GroupMembership
from tests.factories import AllocationFactory
from tests.factories import CohortFactory
from tests.factories import CohortMembershipFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory
from tests.factories import make_ca
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_teacher

pytestmark = pytest.mark.django_db


# --- 404/403 matrix -------------------------------------------------------


def test_change_group_without_change_allocation_gets_404(client):
    from django.contrib.auth.models import Permission

    user = make_login(client, "grid_partial")
    user.user_permissions.add(
        Permission.objects.get(
            codename="change_group", content_type__app_label="grouping"
        )
    )
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    a = AllocationFactory()
    resp = client.get(reverse("grouping:allocation_assign", args=[a.pk]))
    assert resp.status_code == 404  # NOT 403 — the decorator passes, scoping does not


def test_teacher_get_is_403_not_a_redirect(client):
    make_teacher(client)
    a = AllocationFactory()
    resp = client.get(reverse("grouping:allocation_assign", args=[a.pk]))
    assert resp.status_code == 403


def test_ca_on_an_unowned_course_gets_404(client):
    make_ca(client)
    a = AllocationFactory()  # course owned by nobody this CA manages
    resp = client.get(reverse("grouping:allocation_assign", args=[a.pk]))
    assert resp.status_code == 404


def test_pa_can_open_the_grid(client):
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    resp = client.get(reverse("grouping:allocation_assign", args=[a.pk]))
    assert resp.status_code == 200


# --- Row union --------------------------------------------------------


def test_row_union_includes_cohort_members_and_assigned_outsiders(client):
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    col = GroupFactory(course=a.course, allocation=a)
    cohort = CohortFactory()
    a.cohorts.add(cohort)
    cohort_student = UserFactory()
    CohortMembershipFactory(user=cohort_student, cohort=cohort)
    outsider = UserFactory()  # in no attached cohort, placed in a column directly
    CohortMembership.objects.filter(user=outsider).delete()
    services.add_students_to_group(col, [outsider])
    resp = client.get(reverse("grouping:allocation_assign", args=[a.pk]))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert f'name="student-{cohort_student.pk}"' in body
    assert f'name="student-{outsider.pk}"' in body


def test_cohort_less_student_renders_without_500(client):
    """Load-bearing: signals.ensure_cohort_membership auto-creates a membership
    on user create whenever a Default cohort exists, so the fixture must DELETE
    it — otherwise the student has one, renders under "outside these cohorts"
    with data-cohort="" anyway, and the mutant's direct relation read never raises."""
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    col = GroupFactory(course=a.course, allocation=a)
    student = UserFactory()
    services.add_students_to_group(col, [student])
    CohortMembership.objects.filter(user=student).delete()
    assert not CohortMembership.objects.filter(user=student).exists()
    resp = client.get(reverse("grouping:allocation_assign", args=[a.pk]))
    assert resp.status_code == 200
    assert 'data-cohort=""' in resp.content.decode()


# --- Row states and "also in" ------------------------------------------


def test_row_states_are_derived_correctly(client):
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    col1 = GroupFactory(course=a.course, allocation=a, name="Col A")
    col2 = GroupFactory(course=a.course, allocation=a, name="Col B")
    other_group = GroupFactory(course=a.course, name="Other")  # no allocation
    cohort = CohortFactory()
    a.cohorts.add(cohort)

    assigned = UserFactory()
    CohortMembershipFactory(user=assigned, cohort=cohort)
    services.add_students_to_group(col1, [assigned])
    services.add_students_to_group(other_group, [assigned])

    unassigned = UserFactory()
    CohortMembershipFactory(user=unassigned, cohort=cohort)

    conflicted = UserFactory()
    CohortMembershipFactory(user=conflicted, cohort=cohort)
    services.add_students_to_group(col1, [conflicted])
    services.add_students_to_group(col2, [conflicted])

    resp = client.get(reverse("grouping:allocation_assign", args=[a.pk]))
    rows_by_student = {
        row["student"].pk: row
        for section in resp.context["sections"]
        for row in section["rows"]
    }
    assert rows_by_student[assigned.pk]["state"] == "assigned"
    assert rows_by_student[assigned.pk]["selected_id"] == col1.pk
    assert rows_by_student[assigned.pk]["check_none"] is False
    assert rows_by_student[assigned.pk]["also_in"] == ["Other"]

    assert rows_by_student[unassigned.pk]["state"] == "unassigned"
    assert rows_by_student[unassigned.pk]["selected_id"] is None
    assert rows_by_student[unassigned.pk]["check_none"] is True

    assert rows_by_student[conflicted.pk]["state"] == "conflict"
    assert rows_by_student[conflicted.pk]["selected_id"] is None
    assert rows_by_student[conflicted.pk]["check_none"] is False


def test_also_in_note_covers_all_three_cases(client):
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    GroupFactory(course=a.course, allocation=a, name="Col")  # a column, untouched
    cohort = CohortFactory()
    a.cohorts.add(cohort)
    student = UserFactory()
    CohortMembershipFactory(user=student, cohort=cohort)
    other_allocation = AllocationFactory(course=a.course)
    group_other_allocation = GroupFactory(
        course=a.course, allocation=other_allocation, name="OtherAlloc"
    )
    group_no_allocation = GroupFactory(course=a.course, name="NoAlloc")
    archived_column = GroupFactory(
        course=a.course, allocation=a, name="ArchivedCol", archived=True
    )
    services.add_students_to_group(group_other_allocation, [student])
    services.add_students_to_group(group_no_allocation, [student])
    services.add_students_to_group(archived_column, [student])
    resp = client.get(reverse("grouping:allocation_assign", args=[a.pk]))
    also_in = None
    for section in resp.context["sections"]:
        for row in section["rows"]:
            if row["student"].pk == student.pk:
                also_in = set(row["also_in"])
    assert also_in == {"OtherAlloc", "NoAlloc", "ArchivedCol"}


def test_conflict_row_radio_group_has_no_checked_radio(client):
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    cols = [GroupFactory(course=a.course, allocation=a, name=f"c{i}") for i in range(2)]
    cohort = CohortFactory()
    a.cohorts.add(cohort)
    student = UserFactory()
    CohortMembershipFactory(user=student, cohort=cohort)
    services.add_students_to_group(cols[0], [student])
    services.add_students_to_group(cols[1], [student])
    resp = client.get(reverse("grouping:allocation_assign", args=[a.pk]))
    body = resp.content.decode()
    start = body.index("is-conflict")
    row_markup = body[start : body.index("</tr>", start)]
    assert "checked" not in row_markup


# --- Whole-allocation summary --------------------------------------------


def test_summary_counts_the_whole_allocation(client):
    """Fixture is load-bearing: two attached cohorts plus a placed out-of-cohort
    student, asserting total = cohort A + cohort B + leftovers — with a single
    cohort, "the first heading" is every row and the mutant produces identical
    numbers."""
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    col = GroupFactory(course=a.course, allocation=a)
    cohort_a = CohortFactory(name="A")
    cohort_b = CohortFactory(name="B")
    a.cohorts.add(cohort_a, cohort_b)
    s1 = UserFactory()
    CohortMembershipFactory(user=s1, cohort=cohort_a)
    s2 = UserFactory()
    CohortMembershipFactory(user=s2, cohort=cohort_b)
    services.add_students_to_group(col, [s2])
    outsider = UserFactory()
    CohortMembership.objects.filter(user=outsider).delete()
    services.add_students_to_group(col, [outsider])
    resp = client.get(reverse("grouping:allocation_assign", args=[a.pk]))
    summary = resp.context["summary"]
    assert summary["total"] == 3
    assert summary["assigned"] == 2
    assert summary["unassigned"] == 1
    assert summary["conflict"] == 0


# --- Empty attached cohort ------------------------------------------------


def test_empty_cohort_section_renders_with_no_students_note(client):
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    GroupFactory(course=a.course, allocation=a)
    empty_cohort = CohortFactory(name="Empty")
    populated_cohort = CohortFactory(name="Populated")
    a.cohorts.add(empty_cohort, populated_cohort)
    student = UserFactory()
    CohortMembershipFactory(user=student, cohort=populated_cohort)
    resp = client.get(reverse("grouping:allocation_assign", args=[a.pk]))
    body = resp.content.decode()
    assert resp.status_code == 200
    sections = resp.context["sections"]
    empty_section = next(
        (s for s in sections if s["cohort_slug"] == empty_cohort.slug), None
    )
    assert empty_section is not None
    assert empty_section["rows"] == []
    assert empty_cohort.display_name in body
    assert "(no students)" in body


# --- Bounded query count ---------------------------------------------------


def test_grid_render_is_query_bounded(client, django_assert_num_queries):
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    col1 = GroupFactory(course=a.course, allocation=a, name="Col A")
    col2 = GroupFactory(course=a.course, allocation=a, name="Col B")
    other_group = GroupFactory(course=a.course, name="Other")
    cohort_a = CohortFactory(name="A")
    cohort_b = CohortFactory(name="B")
    a.cohorts.add(cohort_a, cohort_b)
    for i in range(6):
        student = UserFactory()
        CohortMembershipFactory(user=student, cohort=cohort_a if i % 2 else cohort_b)
        if i == 0:
            services.add_students_to_group(col1, [student])
            services.add_students_to_group(other_group, [student])
        elif i == 1:
            services.add_students_to_group(col1, [student])
            services.add_students_to_group(col2, [student])
    url = reverse("grouping:allocation_assign", args=[a.pk])
    client.get(url)  # warm session/auth caching
    with django_assert_num_queries(14):
        client.get(url)


# --- POST path: the sharpest edges (given verbatim) ------------------------


def test_a_posted_assignment_lands_through_the_view(client):
    """The only end-to-end proof that a save writes anything. Without it the
    int()-coercion bug drops every row behind a success redirect."""
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    col = GroupFactory(course=a.course, allocation=a)
    cohort = CohortFactory()
    a.cohorts.add(cohort)
    student = UserFactory()
    CohortMembershipFactory(user=student, cohort=cohort)
    resp = client.post(
        reverse("grouping:allocation_assign", args=[a.pk]),
        {
            "columns": services.allocation_columns_token([col]),
            f"student-{student.pk}": str(col.pk),
            f"student-{student.pk}-was": "",
        },
    )
    assert resp.status_code == 302
    assert GroupMembership.objects.filter(group=col, student=student).exists()


def test_an_absent_row_key_is_not_read_as_none(client):
    """Spec row 17a — the contract's sharpest edge, and it lives in the VIEW's
    dict-building, not in the service (which cannot distinguish a key that was
    never built). A conflict row posts no radio at all."""
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    cols = [GroupFactory(course=a.course, allocation=a, name=f"c{i}") for i in range(2)]
    cohort = CohortFactory()
    a.cohorts.add(cohort)
    student = UserFactory()
    CohortMembershipFactory(user=student, cohort=cohort)
    services.add_students_to_group(cols[0], [student])
    services.add_students_to_group(cols[1], [student])
    token = ",".join(str(pk) for pk in sorted(c.pk for c in cols))
    resp = client.post(
        reverse("grouping:allocation_assign", args=[a.pk]),
        {
            "columns": services.allocation_columns_token(cols),
            f"student-{student.pk}-was": token,  # hidden field posts; radio does not
        },
    )
    assert resp.status_code == 302
    assert GroupMembership.objects.filter(student=student).count() == 2


def test_a_missing_was_field_is_skipped_not_written(client):
    """Spec row 17's LIVE mutant is here, not in the service: the service can only
    see the None it was handed, so the `.get(key, "")` slip has to be caught at
    the layer that reads the POST. Load-bearing: the student must be in NO column
    (true token ""), or the mutant's "" coincidentally mismatches and skips too."""
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    col = GroupFactory(course=a.course, allocation=a)
    cohort = CohortFactory()
    a.cohorts.add(cohort)
    student = UserFactory()
    CohortMembershipFactory(user=student, cohort=cohort)
    resp = client.post(
        reverse("grouping:allocation_assign", args=[a.pk]),
        {
            "columns": services.allocation_columns_token([col]),
            f"student-{student.pk}": str(col.pk),  # no -was field at all
        },
    )
    assert resp.status_code == 302
    assert not GroupMembership.objects.filter(group=col, student=student).exists()


def test_added_by_is_recorded_through_the_view(client):
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    col = GroupFactory(course=a.course, allocation=a)
    cohort = CohortFactory()
    a.cohorts.add(cohort)
    student = UserFactory()
    CohortMembershipFactory(user=student, cohort=cohort)
    client.post(
        reverse("grouping:allocation_assign", args=[a.pk]),
        {
            "columns": services.allocation_columns_token([col]),
            f"student-{student.pk}": str(col.pk),
            f"student-{student.pk}-was": "",
        },
    )
    membership = GroupMembership.objects.get(group=col, student=student)
    assert membership.added_by_id == pa.pk


def test_a_student_on_the_grid_only_via_an_archived_column_can_be_assigned(client):
    """Spec row 25c. The failure is completely silent — the row-set branch that
    would drop them is the one place the design deliberately says nothing."""
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    live = GroupFactory(course=a.course, allocation=a, name="live")
    archived = GroupFactory(course=a.course, allocation=a, name="old", archived=True)
    student = UserFactory()  # in NO attached cohort
    services.add_students_to_group(archived, [student])
    resp = client.post(
        reverse("grouping:allocation_assign", args=[a.pk]),
        {
            "columns": services.allocation_columns_token([live]),
            f"student-{student.pk}": str(live.pk),
            f"student-{student.pk}-was": "",
        },
    )
    assert resp.status_code == 302
    assert GroupMembership.objects.filter(group=live, student=student).exists()


def test_a_forged_student_outside_the_row_set_is_ignored(client):
    """The forgery MUST carry a matching -was (""), or the guard skips the row
    even under the mutant and nothing is written either way."""
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    col = GroupFactory(course=a.course, allocation=a)
    outsider = UserFactory()  # in no cohort of this allocation
    CohortMembership.objects.filter(user=outsider).delete()
    resp = client.post(
        reverse("grouping:allocation_assign", args=[a.pk]),
        {
            "columns": services.allocation_columns_token([col]),
            f"student-{outsider.pk}": str(col.pk),
            f"student-{outsider.pk}-was": "",
        },
    )
    assert resp.status_code == 302
    assert not GroupMembership.objects.filter(group=col, student=outsider).exists()


# --- Column-set abort -------------------------------------------------------


def test_column_set_change_aborts_the_whole_save(client):
    """Fixture is load-bearing: the student must be IN the row set (via an
    attached cohort), or they fall outside it and the write would not land even
    without the column-set check — leaving only status_code carrying the test."""
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    col = GroupFactory(course=a.course, allocation=a)
    cohort = CohortFactory()
    a.cohorts.add(cohort)
    student = UserFactory()
    CohortMembershipFactory(user=student, cohort=cohort)
    resp = client.post(
        reverse("grouping:allocation_assign", args=[a.pk]),
        {
            "columns": "999999",  # not the current column set
            f"student-{student.pk}": str(col.pk),
            f"student-{student.pk}-was": "",
        },
    )
    assert resp.status_code == 200  # re-render, not a redirect
    assert not GroupMembership.objects.filter(group=col, student=student).exists()
    assert "changed while you were editing" in resp.content.decode()


def test_missing_columns_field_aborts_even_against_an_empty_token(client):
    """The one fixture where coercing an absent `columns` field to "" would
    coincidentally MATCH the current token (a groups-less allocation's token
    IS ""), silently letting a stale save through as a false no-op."""
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    cohort = CohortFactory()
    a.cohorts.add(cohort)
    student = UserFactory()
    CohortMembershipFactory(user=student, cohort=cohort)
    assert services.allocation_columns_token(list(services.allocation_columns(a))) == ""
    resp = client.post(
        reverse("grouping:allocation_assign", args=[a.pk]),
        {f"student-{student.pk}": "", f"student-{student.pk}-was": ""},
    )
    assert resp.status_code == 200
    assert "changed while you were editing" in resp.content.decode()
