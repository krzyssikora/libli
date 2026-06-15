import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


def _unit_with_elements(course, n=2):
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    els = []
    for i in range(n):
        te = TextElement.objects.create(body=f"<p>e{i}</p>")
        els.append(Element.objects.create(unit=unit, content_object=te))
    return unit, els


@pytest.mark.django_db
def test_unit_panel_lists_elements_with_type_label(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit, _ = _unit_with_elements(course)
    resp = client.get(
        reverse("courses:manage_node_panel", kwargs={"slug": "c1", "pk": unit.pk})
    )
    assert resp.status_code == 200
    assert b"Text" in resp.content  # gettext label, not raw "textelement"


@pytest.mark.django_db
def test_unit_settings_update(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Old"
    )
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "c1"}),
        {"node": unit.pk, "title": "New", "token": unit.updated.isoformat()},
        **FETCH,
    )
    assert resp.status_code == 200
    unit.refresh_from_db()
    assert unit.title == "New"


@pytest.mark.django_db
def test_unit_settings_flip_type_and_obligatory(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        obligatory=True,
        parent=None,
        title="U",
    )
    # settings submit (has_settings marker, obligatory checkbox OMITTED -> False)
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "c1"}),
        {
            "node": unit.pk,
            "title": "U",
            "token": unit.updated.isoformat(),
            "has_settings": "1",
            "unit_type": "quiz",
        },
        **FETCH,
    )
    assert resp.status_code == 200
    unit.refresh_from_db()
    assert unit.unit_type == "quiz"
    assert unit.obligatory is False  # unchecked box on a settings submit -> False


@pytest.mark.django_db
def test_plain_rename_leaves_obligatory_untouched(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        obligatory=True,
        parent=None,
        title="U",
    )
    # plain rename (NO has_settings marker) must not flip obligatory to False
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "c1"}),
        {"node": unit.pk, "title": "U2", "token": unit.updated.isoformat()},
        **FETCH,
    )
    assert resp.status_code == 200
    unit.refresh_from_db()
    assert unit.title == "U2"
    assert unit.obligatory is True  # untouched


@pytest.mark.django_db
def test_element_reorder(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit, els = _unit_with_elements(course, 2)
    e0, e1 = els
    resp = client.post(
        reverse("courses:manage_element_move", kwargs={"slug": "c1"}),
        {
            "element": e1.pk,
            "unit": unit.pk,
            "direction": "up",
            "unit_token": unit.updated.isoformat(),
        },
        **FETCH,
    )
    assert resp.status_code == 200
    order = list(
        Element.objects.filter(unit=unit).order_by("order").values_list("pk", flat=True)
    )
    assert order == [e1.pk, e0.pk]


@pytest.mark.django_db
def test_element_delete_cascades_concrete_and_joinrow(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit, els = _unit_with_elements(course, 2)
    target = els[0]
    concrete_pk = target.object_id
    resp = client.post(
        reverse("courses:manage_element_delete", kwargs={"slug": "c1"}),
        {"element": target.pk, "unit": unit.pk, "unit_token": unit.updated.isoformat()},
        **FETCH,
    )
    assert resp.status_code == 200
    assert not Element.objects.filter(pk=target.pk).exists()
    assert not TextElement.objects.filter(pk=concrete_pk).exists()  # concrete gone too


@pytest.mark.django_db
def test_element_op_vanished_row_409(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit, els = _unit_with_elements(course, 1)
    e0 = els[0]
    ghost = e0.pk
    e0.content_object.delete()  # removes join-row via GenericRelation
    resp = client.post(
        reverse("courses:manage_element_delete", kwargs={"slug": "c1"}),
        {"element": ghost, "unit": unit.pk, "unit_token": unit.updated.isoformat()},
        **FETCH,
    )
    assert resp.status_code == 409
    # per spec, the 409 returns the unit's element-list fragment (recovered via `unit`)
    assert b"data-unit" in resp.content
