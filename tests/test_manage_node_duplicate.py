from django.urls import reverse

from courses.models import ContentNode
from courses.models import Element
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


def _setup(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit = ContentNodeFactory(course=course, title="U1")
    Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>x</p>")
    )
    return owner, course, unit


def _url(course):
    return reverse("courses:manage_node_duplicate", kwargs={"slug": course.slug})


def test_duplicate_view_creates_sibling_fragment(client):
    _owner, course, unit = _setup(client)
    resp = client.post(
        _url(course), {"node": unit.pk, "token": unit.updated.isoformat()}, **FETCH
    )
    assert resp.status_code == 200
    assert ContentNode.objects.filter(course=course, title="U1").count() == 2


def test_duplicate_view_nested_returns_parent_scope(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c2", owner=owner)
    chapter = ContentNode.objects.create(course=course, kind="chapter", title="Ch")
    unit = ContentNodeFactory(course=course, title="U1", parent=chapter)
    Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>x</p>")
    )
    resp = client.post(
        _url(course), {"node": unit.pk, "token": unit.updated.isoformat()}, **FETCH
    )
    assert resp.status_code == 200
    # A nested unit re-renders the PARENT scope fragment, not the whole tree.
    assert f'data-scope="{chapter.pk}"' in resp.content.decode()
    assert (
        ContentNode.objects.filter(course=course, parent=chapter, title="U1").count()
        == 2
    )


def test_duplicate_view_stale_token_409(client):
    _owner, course, unit = _setup(client)
    resp = client.post(
        _url(course),
        {"node": unit.pk, "token": "2000-01-01T00:00:00+00:00"},
        **FETCH,
    )
    assert resp.status_code == 409
    assert ContentNode.objects.filter(course=course, title="U1").count() == 1


def test_duplicate_view_requires_manage(client):
    _owner, course, unit = _setup(client)
    make_login(client, "intruder")  # not a manager of this course
    resp = client.post(
        _url(course), {"node": unit.pk, "token": unit.updated.isoformat()}
    )
    assert resp.status_code == 403


def test_duplicate_view_non_unit_404(client):
    _owner, course, unit = _setup(client)
    chapter = ContentNode.objects.create(course=course, kind="chapter", title="C")
    resp = client.post(
        _url(course),
        {"node": chapter.pk, "token": chapter.updated.isoformat()},
        **FETCH,
    )
    assert resp.status_code == 404
    assert (
        not ContentNode.objects.filter(course=course, title="C")
        .exclude(pk=chapter.pk)
        .exists()
    )
