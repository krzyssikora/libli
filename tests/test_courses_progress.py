import json

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import UnitProgressFactory
from tests.factories import add_element
from tests.factories import make_login


def _seen_url(slug, pk):
    return reverse("courses:seen", kwargs={"slug": slug, "node_pk": pk})


def _make_unit_with_elements(course, n):
    from courses.models import Element
    from courses.models import TextElement

    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    ids = []
    for i in range(n):
        t = TextElement.objects.create(body=f"<p>e{i}</p>")
        ids.append(Element.objects.create(unit=unit, content_object=t).pk)
    return unit, ids


@pytest.mark.django_db
def test_seen_merges_and_autocompletes(client):
    user = make_login(client, "p1")
    course = CourseFactory(slug="pc")
    EnrollmentFactory(student=user, course=course)
    unit, ids = _make_unit_with_elements(course, 2)
    r1 = client.post(
        _seen_url("pc", unit.pk),
        data=json.dumps([ids[0]]),
        content_type="application/json",
    )
    assert r1.status_code == 200
    assert r1.json()["completed"] is False
    r2 = client.post(
        _seen_url("pc", unit.pk), data=json.dumps(ids), content_type="application/json"
    )
    assert r2.json()["completed"] is True
    assert r2.json()["completed_at"] is not None


@pytest.mark.django_db
def test_seen_filters_foreign_and_malformed_returns_200(client):
    user = make_login(client, "p2")
    course = CourseFactory(slug="pf")
    EnrollmentFactory(student=user, course=course)
    unit, ids = _make_unit_with_elements(course, 2)
    r = client.post(
        _seen_url("pf", unit.pk),
        data=json.dumps([ids[0], 999999, "x", True]),
        content_type="application/json",
    )
    assert r.status_code == 200
    assert r.json()["completed"] is False  # only one valid id of two
    bad = client.post(
        _seen_url("pf", unit.pk),
        data=json.dumps({"a": 1}),
        content_type="application/json",
    )
    assert bad.status_code == 400


@pytest.mark.django_db
def test_zero_element_unit_completes_only_via_fallback(client):
    user = make_login(client, "p3")
    course = CourseFactory(slug="pz")
    EnrollmentFactory(student=user, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    r = client.post(
        _seen_url("pz", unit.pk), data=json.dumps([]), content_type="application/json"
    )
    assert r.json()["completed"] is False  # empty unit never auto-completes
    comp = client.post(
        reverse("courses:complete", kwargs={"slug": "pz", "node_pk": unit.pk})
    )
    assert comp.status_code in (302, 200)
    from courses.models import UnitProgress

    assert UnitProgress.objects.get(student=user, unit=unit).completed is True


@pytest.mark.django_db
def test_quiz_seen_returns_404(client):
    user = make_login(client, "p4")
    course = CourseFactory(slug="pq")
    EnrollmentFactory(student=user, course=course)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    r = client.post(
        _seen_url("pq", quiz.pk), data=json.dumps([]), content_type="application/json"
    )
    assert r.status_code == 404


@pytest.mark.django_db
def test_previewer_seen_no_write_and_ignores_stored_completion(client):
    from courses.models import UnitProgress

    staff = make_login(client, "staff1")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="pp")  # staff not enrolled
    unit, ids = _make_unit_with_elements(course, 1)

    # (1) The pre-existing half, unchanged: no row exists, so no write and a synthetic
    # response.
    r = client.post(
        _seen_url("pp", unit.pk), data=json.dumps(ids), content_type="application/json"
    )
    assert r.status_code == 200
    assert r.json() == {
        "seen_element_ids": [],
        "completed": False,
        "completed_at": None,
    }
    assert not UnitProgress.objects.filter(student=staff, unit=unit).exists()

    # (2) NOW seed a completed row for THAT SAME viewer. student= and unit= are
    # mandatory here above all: every step-(3) assertion is negative, so a row minted
    # against an unrelated node leaves them all green -- and so does this extension's
    # own falsification recipe.
    row = UnitProgressFactory(student=staff, unit=unit, completed=True)
    stamped_at = UnitProgress.objects.get(pk=row.pk).completed_at

    # (3) seen STILL reports the synthetic response and STILL writes nothing.
    r2 = client.post(
        _seen_url("pp", unit.pk), data=json.dumps(ids), content_type="application/json"
    )
    assert r2.json() == {
        "seen_element_ids": [],
        "completed": False,
        "completed_at": None,
    }
    row.refresh_from_db()
    # Name the fields; do not compare whole objects (updated_at is auto_now).
    assert row.seen_element_ids == []  # the POSTed ids were not merged
    assert row.completed is True
    assert row.completed_at == stamped_at


@pytest.mark.django_db
def test_previewer_complete_persists_and_redirects(client):
    from courses.models import UnitProgress

    staff = make_login(client, "staff2")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="pcx")  # staff not enrolled -> previewer
    unit, ids = _make_unit_with_elements(course, 1)

    r = client.post(
        reverse("courses:complete", kwargs={"slug": "pcx", "node_pk": unit.pk})
    )

    # The redirect assertion is KEPT from the old test (the inversion replaces the
    # WRITE assertion, not the response-shape one) and tightened: complete() ends in
    # redirect(), so a 200 would now mean something went wrong.
    assert r.status_code == 302
    assert r["Location"] == reverse(
        "courses:lesson_unit", kwargs={"slug": "pcx", "node_pk": unit.pk}
    )
    row = UnitProgress.objects.get(student=staff, unit=unit)
    assert row.completed is True
    assert row.completed_at is not None


@pytest.mark.django_db
def test_previewer_complete_over_checklist_row_preserves_practice_state(client):
    from courses.models import UnitProgress

    staff = make_login(client, "staff1b")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="pcb")
    unit, ids = _make_unit_with_elements(course, 1)
    # STRING keys: element_state is a JSONField, so an int-keyed seed round-trips as
    # {"<pk>": ...} and comparing to the in-memory literal would fail against CORRECT
    # code. This is production shape -- save_element_state stores str(element_pk).
    seeded = {str(ids[0]): {"checked": True}}
    # Both student= and unit= are mandatory: they are SubFactory fields, and omitting
    # them mints a row for an unrelated user on an unrelated node.
    UnitProgressFactory(student=staff, unit=unit, completed=False, element_state=seeded)

    client.post(reverse("courses:complete", kwargs={"slug": "pcb", "node_pk": unit.pk}))

    row = UnitProgress.objects.get(student=staff, unit=unit)
    assert row.completed is True
    assert row.completed_at is not None
    assert row.element_state == seeded


@pytest.mark.django_db
def test_enrolled_complete_over_existing_row_preserves_state_and_seen_ids(client):
    from courses.models import UnitProgress

    student = make_login(client, "enr1c")
    course = CourseFactory(slug="pcc")
    EnrollmentFactory(student=student, course=course)
    unit, ids = _make_unit_with_elements(course, 1)
    seeded_state = {str(ids[0]): {"checked": True}}
    # seen_element_ids is the column the lost-update argument actually centres on:
    # `seen` is the unhardened full-row writer, and only an ENROLLED row realistically
    # carries a non-empty seen-set (a previewer never reaches seen's write).
    UnitProgressFactory(
        student=student,
        unit=unit,
        completed=False,
        element_state=seeded_state,
        seen_element_ids=[ids[0]],
    )

    client.post(reverse("courses:complete", kwargs={"slug": "pcc", "node_pk": unit.pk}))

    row = UnitProgress.objects.get(student=student, unit=unit)
    assert row.completed is True
    assert row.element_state == seeded_state
    assert row.seen_element_ids == [ids[0]]


@pytest.mark.django_db
def test_previewer_sees_completed_pill_after_marking(client):
    from courses.models import UnitProgress

    staff = make_login(client, "staff3")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="prd")
    unit, ids = _make_unit_with_elements(course, 1)
    client.post(reverse("courses:complete", kwargs={"slug": "prd", "node_pk": unit.pk}))
    assert UnitProgress.objects.filter(
        student=staff, unit=unit, completed=True
    ).exists()

    # A SEPARATE GET -- deliberately not follow=True on the POST, or "test 1 stays
    # green while this goes RED" in the falsification below would mean nothing.
    r = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": "prd", "node_pk": unit.pk})
    )

    assert r.status_code == 200
    # Scope to the [data-unit-done] subtree: is-complete is safe as a body substring
    # only by accident today, and "Completed" is always present via data-done-label.
    pill = BeautifulSoup(r.content, "html.parser").select_one("[data-unit-done]")
    assert pill is not None
    assert "is-complete" in pill.get("class", [])
    assert pill.select_one("button.unit-done__pill--btn") is None


@pytest.mark.django_db
def test_previewer_pre_existing_completed_row_shows_pill_without_posting(client):
    staff = make_login(client, "staff6a")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="p6a")
    unit, ids = _make_unit_with_elements(course, 1)
    # The "was enrolled earlier" population: a row survives the enrollment going away.
    UnitProgressFactory(student=staff, unit=unit, completed=True)

    r = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": "p6a", "node_pk": unit.pk})
    )

    assert r.status_code == 200
    pill = BeautifulSoup(r.content, "html.parser").select_one("[data-unit-done]")
    assert "is-complete" in pill.get("class", [])
    assert pill.select_one("button.unit-done__pill--btn") is None


@pytest.mark.django_db
def test_previewer_incomplete_row_still_renders_the_button(client):
    staff = make_login(client, "staff6b")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="p6b")
    unit, ids = _make_unit_with_elements(course, 1)
    # The most common previewer row in production once this ships: a checklist tick
    # creates exactly this shape. Both kwargs mandatory (SubFactory fields).
    UnitProgressFactory(
        student=staff,
        unit=unit,
        completed=False,
        element_state={str(ids[0]): {"checked": True}},
    )

    r = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": "p6b", "node_pk": unit.pk})
    )

    assert r.status_code == 200
    pill = BeautifulSoup(r.content, "html.parser").select_one("[data-unit-done]")
    # Two DIFFERENT elements: the div's own class list, and a descendant button.
    assert "is-complete" not in pill.get("class", [])
    assert pill.select_one("button.unit-done__pill--btn") is not None


@pytest.mark.django_db
def test_previewer_completed_pill_survives_no_js_check_answer_rerender(client):
    from courses.models import Enrollment
    from courses.models import ShortTextQuestionElement

    staff = make_login(client, "staff7")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="p7")
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    # Field names and URL shape copied from the repo's ONLY no-JS check_answer test
    # (courses/tests/test_reset_controls.py:156-177): ShortTextQuestionElement takes
    # stem/accepted, and add_element returns the JOIN ROW whose pk is the third URL
    # argument. Copy that recipe only -- never that file's _login helper, which calls
    # Enrollment.objects.create() before force_login and would silently make this an
    # ENROLLED-path test whose falsification recipe stays GREEN.
    q_row = add_element(
        unit, ShortTextQuestionElement.objects.create(stem="Q", accepted="x")
    )
    # Seeded directly, NOT via a complete() POST: this test's falsification targets the
    # READ assignment, and routing it through the write would couple it to an edit it
    # does not guard.
    UnitProgressFactory(student=staff, unit=unit, completed=True)
    # Access comes from the is_staff pin above, not from any fixture.
    assert not Enrollment.objects.filter(student=staff, course=course).exists()

    r = client.post(
        reverse("courses:check_answer", args=[course.slug, unit.pk, q_row.pk]),
        {"answer": "x"},  # NON-EMPTY: an empty answer takes the clear branch instead
    )  # NO HTTP_X_REQUESTED_WITH: the header would take the fragment branch instead

    assert r.status_code == 200
    pill = BeautifulSoup(r.content, "html.parser").select_one("[data-unit-done]")
    assert pill is not None
    assert "is-complete" in pill.get("class", [])
    assert pill.select_one("button.unit-done__pill--btn") is None


@pytest.mark.django_db
def test_non_staff_course_owner_can_complete(client):
    from courses.models import Enrollment
    from courses.models import UnitProgress

    owner = make_login(client, "owner5a")
    # owner= is MANDATORY: CourseFactory declares no owner and Course.owner is
    # null=True, so a bare CourseFactory() leaves route (a) non-existent.
    course = CourseFactory(slug="p5a", owner=owner)
    unit, ids = _make_unit_with_elements(course, 1)
    # Trap 1: accessible_courses returns Course.objects.all() at `if user.is_staff:`
    # BEFORE evaluating Q(owner=user), so a staff owner would pass via the wrong route.
    assert owner.is_staff is False
    # Trap 2: an enrolled owner writes on the BASE commit too, making this vacuous.
    assert not Enrollment.objects.filter(student=owner, course=course).exists()

    client.post(reverse("courses:complete", kwargs={"slug": "p5a", "node_pk": unit.pk}))

    assert UnitProgress.objects.get(student=owner, unit=unit).completed is True


@pytest.mark.django_db
def test_non_staff_teacher_of_live_group_can_complete(client):
    from courses.models import Enrollment
    from courses.models import UnitProgress

    teacher = make_login(client, "teach5d")
    course = CourseFactory(slug="p5d")
    unit, ids = _make_unit_with_elements(course, 1)
    # archived defaults to False on the model; GroupFactory declares no such field.
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    assert teacher.is_staff is False
    assert not Enrollment.objects.filter(student=teacher, course=course).exists()

    client.post(reverse("courses:complete", kwargs={"slug": "p5d", "node_pk": unit.pk}))

    assert UnitProgress.objects.get(student=teacher, unit=unit).completed is True


@pytest.mark.django_db
def test_teacher_of_archived_group_is_denied(client):
    from courses.models import UnitProgress

    teacher = make_login(client, "teach5b")
    course = CourseFactory(slug="p5b")
    unit, ids = _make_unit_with_elements(course, 1)
    # archived=True is a PASSTHROUGH model kwarg, not a declared factory field.
    # Setting group.archived = True without a .save() would silently turn this into
    # route (d) and the test would pass while proving the opposite of its claim.
    group = GroupFactory(course=course, archived=True)
    group.teachers.add(teacher)
    # Kept because this test's whole claim is about the groups__archived=False pin,
    # which is only legible if the fixture shows the user reaching the group clause.
    assert teacher.is_staff is False

    r = client.post(
        reverse("courses:complete", kwargs={"slug": "p5b", "node_pk": unit.pk})
    )

    assert r.status_code == 403
    assert not UnitProgress.objects.filter(student=teacher, unit=unit).exists()


@pytest.mark.django_db
def test_unrelated_logged_in_user_is_denied(client):
    from courses.models import UnitProgress

    stranger = make_login(client, "stranger5c")
    course = CourseFactory(slug="p5c")
    unit, ids = _make_unit_with_elements(course, 1)

    r = client.post(
        reverse("courses:complete", kwargs={"slug": "p5c", "node_pk": unit.pk})
    )

    assert r.status_code == 403
    assert not UnitProgress.objects.filter(student=stranger, unit=unit).exists()
