import json

import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
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
def test_previewer_complete_redirects_without_write(client):
    from courses.models import UnitProgress

    staff = make_login(client, "staff2")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="pcx")  # staff not enrolled -> untracked preview
    unit, ids = _make_unit_with_elements(course, 1)
    r = client.post(
        reverse("courses:complete", kwargs={"slug": "pcx", "node_pk": unit.pk})
    )
    assert r.status_code in (302, 200)  # same redirect as the enrolled path
    # no write for previewer
    assert not UnitProgress.objects.filter(student=staff, unit=unit).exists()
