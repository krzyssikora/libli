from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from courses.models import GuessNumberElement
from courses.models import QuestionResponse
from courses.models import TextElement
from courses.models import UnitProgress
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _post(client, eid, guess):
    return client.post(
        reverse("courses:guessnumber_check", args=[eid]), {"guess": guess}
    )


@pytest.fixture
def auth_client():
    """A fresh logged-in client for the course owner. Never shares session state
    with other_auth_client — each test.Client logs in independently."""
    c = Client()
    c.user = make_login(c, "gn-owner")
    return c


@pytest.fixture
def other_auth_client():
    """A separate fresh client for a user with no relationship (owner/enrolled/
    teacher) to the course the elements below live in — always denied."""
    c = Client()
    c.user = make_login(c, "gn-outsider")
    return c


@pytest.fixture
def gn_eid(auth_client):
    course = CourseFactory(owner=auth_client.user)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )
    obj = GuessNumberElement(target=Decimal(42), tolerance=Decimal(0))
    obj.save()
    element = add_element(unit, obj)
    return element.pk


@pytest.fixture
def gn_tolerant_eid(auth_client):
    course = CourseFactory(owner=auth_client.user)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )
    obj = GuessNumberElement(target=Decimal(42), tolerance=Decimal("0.5"))
    obj.save()
    element = add_element(unit, obj)
    return element.pk


@pytest.fixture
def other_element_eid(auth_client):
    course = CourseFactory(owner=auth_client.user)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )
    obj = TextElement(body="<p>not a guess-number</p>")
    obj.save()
    element = add_element(unit, obj)
    return element.pk


@pytest.mark.parametrize(
    "guess,correct,direction",
    [
        ("42", True, None),
        ("43", False, "high"),
        ("41", False, "low"),
        ("abc", False, None),  # unparseable: wrong, but no direction
        ("1 000", False, None),  # thousands separator rejected by parse_number
        ("", False, None),
    ],
)
def test_verdicts(auth_client, gn_eid, guess, correct, direction):
    r = _post(auth_client, gn_eid, guess)
    assert r.status_code == 200
    assert r.json() == {"correct": correct, "direction": direction}


def test_tolerance_boundary_is_inclusive(auth_client, gn_tolerant_eid):
    # target=42, tolerance=0.5 -> exactly 42.5 is CORRECT
    assert _post(auth_client, gn_tolerant_eid, "42.5").json()["correct"] is True
    assert _post(auth_client, gn_tolerant_eid, "42.6").json() == {
        "correct": False,
        "direction": "high",
    }


@pytest.mark.parametrize("guess", ["42,0", "42.0"])
def test_comma_and_period_decimals_both_correct(auth_client, gn_eid, guess):
    assert _post(auth_client, gn_eid, guess).json()["correct"] is True


def test_missing_pk_is_benign_200(auth_client):
    r = _post(auth_client, 999999, "42")
    assert r.status_code == 200
    assert r.json() == {"correct": False, "direction": None}


def test_wrong_type_pk_is_benign_200(auth_client, other_element_eid):
    r = _post(auth_client, other_element_eid, "42")
    assert r.status_code == 200
    assert r.json() == {"correct": False, "direction": None}


def test_no_course_access_is_403(other_auth_client, gn_eid):
    assert _post(other_auth_client, gn_eid, "42").status_code == 403


def test_get_not_allowed(auth_client, gn_eid):
    url = reverse("courses:guessnumber_check", args=[gn_eid])
    assert auth_client.get(url).status_code == 405


def test_anonymous_redirected(client, gn_eid):
    assert _post(client, gn_eid, "42").status_code in (302, 403)


def test_nothing_is_persisted(auth_client, gn_eid):
    _post(auth_client, gn_eid, "43")
    assert QuestionResponse.objects.count() == 0
    assert UnitProgress.objects.count() == 0  # the likelier accidental write
