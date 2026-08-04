import pytest
from django.urls import reverse

from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _seed(client, username="pa"):
    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    join = add_element(unit, TextElement.objects.create(body="<p>hi</p>"))
    unit.refresh_from_db()
    return course, unit, join


def _clip(client, course, unit, element, action="select"):
    return client.post(
        reverse("courses:manage_element_clip", kwargs={"slug": course.slug}),
        {"ctx": "editor", "element": element, "unit": unit.pk, "action": action},
        HTTP_X_REQUESTED_WITH="fetch",
    )


def test_select_marks_the_element_and_returns_both_fragments(client):
    course, unit, join = _seed(client)

    resp = _clip(client, course, unit, join.pk)

    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'data-scope="editor"' in body
    assert 'data-scope="preview"' in body
    assert client.session["element_clip"] == {"unit": unit.pk, "element": join.pk}


def test_both_pks_are_stored_as_ints(client):
    """The session is JSON: a string written here stays a string on every later
    request, and `clip["element"] == el.pk` is then False for every row -- so the
    toggle-off lifecycle never fires and the marked-row modifier never renders.
    Both failures are silent and closed."""
    course, unit, join = _seed(client)

    _clip(client, course, unit, str(join.pk))

    clip = client.session["element_clip"]
    assert isinstance(clip["element"], int)
    assert isinstance(clip["unit"], int)


def test_selecting_a_second_element_replaces_the_mark(client):
    course, unit, join = _seed(client)
    other = add_element(unit, TextElement.objects.create(body="<p>2</p>"))

    _clip(client, course, unit, join.pk)
    _clip(client, course, unit, other.pk)

    assert client.session["element_clip"]["element"] == other.pk


def test_selecting_the_marked_element_again_clears_it(client):
    """The row's own control toggles."""
    course, unit, join = _seed(client)

    _clip(client, course, unit, join.pk)
    _clip(client, course, unit, join.pk)

    assert "element_clip" not in client.session


def test_cancel_clears_the_mark(client):
    course, unit, join = _seed(client)
    _clip(client, course, unit, join.pk)

    resp = _clip(client, course, unit, join.pk, action="cancel")

    assert resp.status_code == 200
    assert "element_clip" not in client.session


def test_cancel_with_no_mark_is_harmless(client):
    course, unit, join = _seed(client)

    resp = _clip(client, course, unit, join.pk, action="cancel")

    assert resp.status_code == 200
    assert "element_clip" not in client.session


def test_a_non_numeric_element_is_a_400(client):
    """The one endpoint whose whole job is to be cheap and side-effect-free must
    not 500 on a malformed payload."""
    course, unit, _join = _seed(client)

    resp = _clip(client, course, unit, "abc")

    assert resp.status_code == 400
    assert "element_clip" not in client.session


def test_an_unknown_action_is_a_400(client):
    course, unit, join = _seed(client)

    resp = _clip(client, course, unit, join.pk, action="teleport")

    assert resp.status_code == 400


def test_an_element_from_another_unit_is_refused(client):
    """The mark is qualified by unit; a mark naming a row that is not in this unit
    would render paste buttons for something the paste would then refuse."""
    course, unit, _join = _seed(client)
    other_unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    foreign = add_element(other_unit, TextElement.objects.create(body="<p>f</p>"))

    resp = _clip(client, course, unit, foreign.pk)

    assert resp.status_code == 409
    assert "element_clip" not in client.session


def test_a_unit_from_another_course_renders_no_foreign_content(client):
    """It writes no data, but it ANSWERS with that unit's element list and live
    preview -- so a POST carrying a unit pk from a course this user does not manage
    must not render it."""
    course, unit, join = _seed(client, username="owner")
    other_course = CourseFactory(owner=CourseFactory().owner)
    foreign_unit = ContentNodeFactory(
        course=other_course, parent=None, kind="unit", unit_type="lesson"
    )
    add_element(foreign_unit, TextElement.objects.create(body="<p>SECRET</p>"))

    resp = client.post(
        reverse("courses:manage_element_clip", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "element": join.pk,
            "unit": foreign_unit.pk,
            "action": "select",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 409
    assert "SECRET" not in resp.content.decode()


def test_a_non_numeric_unit_is_a_409_not_a_500(client):
    """filter(pk="abc") raises ValueError when the queryset is evaluated.

    Guarding _clip_unit alone is NOT enough: _element_conflict opens with the same
    unguarded filter on the same POST field, so routing the failure there would
    re-raise the ValueError and answer 500. That is why this path returns
    _no_unit_409 instead, and why this test exists rather than being assumed."""
    course, unit, join = _seed(client)

    resp = client.post(
        reverse("courses:manage_element_clip", kwargs={"slug": course.slug}),
        {"ctx": "editor", "element": join.pk, "unit": "abc", "action": "select"},
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 409


def test_a_non_numeric_session_element_does_not_break_the_editor_render(client):
    """element_clip always writes element_clip["element"] through int(), so this
    shape is unreachable through that endpoint -- but _clip_context's marked lookup
    (unit.elements.filter(pk=clip.get("element"))) is unguarded, and filter(pk="abc")
    raises ValueError when the queryset is evaluated. A session written any other
    way would then 500 on EVERY editor render for that user until the cookie is
    cleared -- a sticky failure, unlike _clip_unit's analogous guard a few lines
    above. This is the regression that guard closes."""
    course, unit, _join = _seed(client)
    session = client.session
    session["element_clip"] = {"unit": unit.pk, "element": "abc"}
    session.save()

    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )

    assert resp.status_code == 200
    assert resp.context["clip_active"] is False


def test_a_user_who_cannot_manage_the_course_is_refused(client):
    from tests.factories import make_teacher

    course, unit, join = _seed(client, username="owner")
    client.logout()
    make_teacher(client, "teacher")

    resp = _clip(client, course, unit, join.pk)

    assert resp.status_code in (403, 404)
