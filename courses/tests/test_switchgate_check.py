import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from courses.models import Element
from courses.models import SwitchGateElement
from courses.models import TextElement
from courses.switchgate import SENTINEL_TOKEN
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
    user = make_login(client, "switchgate-student")
    EnrollmentFactory(student=user, course=enrolled_unit.course)
    return client


@pytest.fixture
def client_without_access(client):
    make_login(client, "switchgate-outsider")
    return client


def _make_gate(enrolled_unit, answer=1, options=("a", "b", "c")):
    el = SwitchGateElement.objects.create(
        stem=SENTINEL_TOKEN, options=list(options), answer=answer
    )
    join = Element.objects.create(
        unit=enrolled_unit,
        content_type=ContentType.objects.get_for_model(SwitchGateElement),
        object_id=el.pk,
    )
    return join


def _url(pk):
    return reverse("courses:switchgate_check", args=[pk])


def test_correct_choice(enrolled_client, enrolled_unit):
    join = _make_gate(enrolled_unit, answer=1)
    r = enrolled_client.post(_url(join.pk), {"choice": "1"})
    assert r.status_code == 200
    assert r.json() == {"correct": True}


def test_wrong_choice(enrolled_client, enrolled_unit):
    join = _make_gate(enrolled_unit, answer=1)
    r = enrolled_client.post(_url(join.pk), {"choice": "0"})
    assert r.json() == {"correct": False}


@pytest.mark.parametrize("choice", ["-1", "9", "", "abc"])
def test_placeholder_out_of_range_and_malformed_all_false(
    enrolled_client, enrolled_unit, choice
):
    join = _make_gate(enrolled_unit, answer=1)
    r = enrolled_client.post(_url(join.pk), {"choice": choice})
    assert r.status_code == 200
    assert r.json() == {"correct": False}


def test_unresolved_pk_soft_200(enrolled_client):
    r = enrolled_client.post(_url(999999), {"choice": "0"})
    assert r.status_code == 200
    assert r.json() == {"correct": False}


def test_wrong_type_pk_soft_200(enrolled_client, enrolled_unit):
    # a REAL Element join whose content_object is a *different* element type ->
    # the isinstance(...) check misses -> soft 200 {correct:false} (NOT 404).
    text = TextElement.objects.create(body="<p>hi</p>")
    join = Element.objects.create(
        unit=enrolled_unit,
        content_type=ContentType.objects.get_for_model(TextElement),
        object_id=text.pk,
    )
    r = enrolled_client.post(_url(join.pk), {"choice": "0"})
    assert r.status_code == 200
    assert r.json() == {"correct": False}


def test_get_405(enrolled_client, enrolled_unit):
    join = _make_gate(enrolled_unit)
    assert enrolled_client.get(_url(join.pk)).status_code == 405


def test_access_denied_non_200(client_without_access, enrolled_unit):
    join = _make_gate(enrolled_unit)
    r = client_without_access.post(_url(join.pk), {"choice": "1"})
    assert r.status_code in (403, 302)
