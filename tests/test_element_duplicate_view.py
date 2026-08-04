import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _seed(client, username="pa"):
    """Returns (course, unit, join) with a logged-in manager."""
    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    join = add_element(unit, TextElement.objects.create(body="<p>hi</p>"))
    unit.refresh_from_db()  # add_element bumped nothing; re-read for a fresh token
    return course, unit, join


def _post(client, course, unit, join, token=None):
    return client.post(
        reverse("courses:manage_element_duplicate", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "element": join.pk,
            "unit": unit.pk,
            "unit_token": token if token is not None else unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )


def test_duplicate_returns_both_fragments(client):
    course, unit, join = _seed(client)

    resp = _post(client, course, unit, join)

    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'data-scope="editor"' in body
    assert 'data-scope="preview"' in body
    assert unit.elements.count() == 2


def test_duplicate_409s_on_a_stale_token(client):
    course, unit, join = _seed(client)

    resp = _post(client, course, unit, join, token="2020-01-01T00:00:00+00:00")

    assert resp.status_code == 409
    assert unit.elements.count() == 1


def test_duplicate_422s_with_a_visible_message_on_a_damaged_element(client):
    """Assert the BODY, not only the status: a 422 whose body is a bare op-error
    div passes a status-only assertion and is still invisible to the author.
    That is exactly how this error path was got wrong once already."""
    course, unit, join = _seed(client)
    # Repoint, don't delete: GenericRelation(Element) cascades, so deleting the
    # concrete would remove `join` itself -- _locked_element would then raise
    # ConflictError and the endpoint would answer 409, never reaching the 422
    # path this test exists to check. See tests/test_transfer_export.py:342-351.
    Element.objects.filter(pk=join.pk).update(object_id=9_999_999)

    resp = _post(client, course, unit, join)

    assert resp.status_code == 422
    body = resp.content.decode()
    assert 'data-scope="editor"' in body
    assert 'id="editor-error"' in body


def test_duplicate_409s_on_a_non_numeric_element_pk(client):
    """Guards Task 4 Step 3's widened except clause: _locked_element caught only
    DoesNotExist, so Element.objects.get(pk="abc") raised ValueError and the
    author got a 500."""
    course, unit, _join = _seed(client)

    resp = client.post(
        reverse("courses:manage_element_duplicate", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "element": "abc",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 409


def test_duplicate_refuses_a_user_who_cannot_manage_the_course(client):
    """Drive the surface AS the wrong role rather than asserting the decorator
    exists."""
    from tests.factories import make_teacher

    course, unit, join = _seed(client, username="owner")
    client.logout()
    make_teacher(client, "teacher")  # can log in, cannot manage this course

    resp = _post(client, course, unit, join)

    assert resp.status_code in (403, 404)
    assert unit.elements.count() == 1
