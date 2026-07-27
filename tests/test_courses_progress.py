import json

import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UnitProgressFactory
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
def test_previewer_seen_no_write_synthetic(client):
    from courses.models import UnitProgress

    staff = make_login(client, "staff1")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="pp")  # staff not enrolled
    unit, ids = _make_unit_with_elements(course, 1)
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
