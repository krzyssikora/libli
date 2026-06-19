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
    # per spec, the 409 returns the unit's panel fragment (recovered via `unit`).
    # Task 4 collapsed the panel to a read-only element summary, so assert that marker.
    assert b"element-list--readonly" in resp.content


@pytest.mark.django_db
def test_place_element_moves_to_absolute_index():
    from courses.builder import reorder_element
    from courses.models import Element
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )
    els = []
    for i in range(4):
        t = TextElement.objects.create(body=f"<p>{i}</p>")
        els.append(Element.objects.create(unit=unit, content_object=t))
    token = unit.updated.isoformat()
    # move element at index 0 to index 2 (post-removal index)
    unit2, changed = reorder_element(course, els[0].pk, token, position=2)
    assert changed is True
    order = list(
        Element.objects.filter(unit=unit).order_by("order").values_list("pk", flat=True)
    )
    assert order == [els[1].pk, els[2].pk, els[0].pk, els[3].pk]


@pytest.mark.django_db
def test_place_element_clamps_out_of_range():
    from courses.builder import reorder_element
    from courses.models import Element
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )
    els = [
        Element.objects.create(
            unit=unit, content_object=TextElement.objects.create(body=f"<p>{i}</p>")
        )
        for i in range(3)
    ]
    token = unit.updated.isoformat()
    unit2, changed = reorder_element(course, els[0].pk, token, position=999)
    order = list(
        Element.objects.filter(unit=unit).order_by("order").values_list("pk", flat=True)
    )
    assert order == [els[1].pk, els[2].pk, els[0].pk]
    assert changed is True


@pytest.mark.django_db
def test_place_element_same_slot_is_noop():
    from courses.builder import reorder_element
    from courses.models import Element
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )
    els = [
        Element.objects.create(
            unit=unit, content_object=TextElement.objects.create(body=f"<p>{i}</p>")
        )
        for i in range(3)
    ]
    token = unit.updated.isoformat()
    unit2, changed = reorder_element(course, els[1].pk, token, position=1)
    assert changed is False


@pytest.mark.django_db
def test_element_save_persists_title_and_list_shows_it(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="celtitle", owner=owner)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", title="U")
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": "celtitle"}),
        {
            "type": "text",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "ctx": "editor",
            "body": "<p>hi</p>",
            "el_title": "Intro example",
        },
        **FETCH,
    )
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit)
    assert el.title == "Intro example"
    assert b"Intro example" in resp.content  # editor list shows the label


@pytest.mark.django_db
def test_preview_elements_carry_data_element_id(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="cprevid", owner=owner)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", title="U")
    el = Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>hi</p>")
    )
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": "cprevid", "pk": unit.pk})
    )
    assert resp.status_code == 200
    assert b'class="prev-el"' in resp.content
    assert f'data-element-id="{el.pk}"'.encode() in resp.content
