import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from courses.models import Element
from courses.models import FillGateElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


@pytest.fixture
def enrolled_unit():
    course = CourseFactory()
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )


@pytest.fixture
def enrolled_client(client, enrolled_unit):
    user = make_login(client, "fillgate-student")
    EnrollmentFactory(student=user, course=enrolled_unit.course)
    return client


@pytest.fixture
def client_without_access(client):
    make_login(client, "fillgate-outsider")
    return client


def _gate(unit, answers):
    el = FillGateElement.objects.create(stem="q ￿0￿", answers=answers)
    return Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(FillGateElement),
        object_id=el.pk,
    )


def test_correct_and_wrong(enrolled_client, enrolled_unit):
    unit = enrolled_unit
    join = _gate(unit, [["4", "four"]])
    url = reverse("courses:fillgate_check", args=[join.pk])
    ok = enrolled_client.post(url, {"blank": ["four"]}).json()
    assert ok == {"correct": True, "blanks": [True]}
    bad = enrolled_client.post(url, {"blank": ["5"]}).json()
    assert bad == {"correct": False, "blanks": [False]}


def test_multi_blank_and_numeric(enrolled_client, enrolled_unit):
    join = _gate(enrolled_unit, [["4"], ["3.14"]])
    url = reverse("courses:fillgate_check", args=[join.pk])
    data = enrolled_client.post(url, {"blank": ["4", "3,14"]}).json()  # comma decimal
    assert data == {"correct": True, "blanks": [True, True]}
    mixed = enrolled_client.post(url, {"blank": ["4", "9"]}).json()
    assert mixed == {"correct": False, "blanks": [True, False]}


def test_get_405_and_bad_id_404(enrolled_client, enrolled_unit):
    join = _gate(enrolled_unit, [["4"]])
    url = reverse("courses:fillgate_check", args=[join.pk])
    assert enrolled_client.get(url).status_code == 405
    assert (
        enrolled_client.post(
            reverse("courses:fillgate_check", args=[999999])
        ).status_code
        == 404
    )


def test_access_denied(client_without_access, enrolled_unit):
    join = _gate(enrolled_unit, [["4"]])
    url = reverse("courses:fillgate_check", args=[join.pk])
    resp = client_without_access.post(url, {"blank": ["4"]})
    assert resp.status_code in (403, 302)  # PermissionDenied (or login redirect)
