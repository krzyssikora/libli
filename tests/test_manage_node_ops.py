import pytest
from django.urls import reverse

from courses.models import ContentNode
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

# Node-op endpoints distinguish the JS/fragment path (200 + scope/tree fragment) from
# the no-JS path (302 redirect on success, full builder page on error) via the
# `X-Requested-With: fetch` header (see spec §No-JS fallback). These tests exercise the
# fragment contract, so every mutating POST carries the header.
FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


def _setup(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    return owner, course


def _tok(node):
    return node.updated.isoformat()


@pytest.mark.django_db
def test_add_top_level_node(client):
    _, course = _setup(client)
    resp = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "c1"}),
        {
            "parent": "top",
            "parent_token": course.updated.isoformat(),
            "kind": "part",
            "title": "Foundations",
        },
        **FETCH,
    )
    assert resp.status_code == 200
    assert ContentNode.objects.filter(
        course=course, title="Foundations", kind="part"
    ).exists()


@pytest.mark.django_db
def test_add_unit_requires_unit_type(client):
    _, course = _setup(client)
    resp = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "c1"}),
        {
            "parent": "top",
            "parent_token": course.updated.isoformat(),
            "kind": "unit",
            "title": "U",
        },
        **FETCH,
    )  # missing unit_type
    assert resp.status_code == 422


@pytest.mark.django_db
def test_add_non_unit_ignores_submitted_unit_type(client):
    # The add form's unit_type <select> always submits a value (it is only visually
    # hidden, never disabled — and FormData includes it under JS too). A non-unit kind
    # must ignore that stray value rather than 422 on clean()'s "only units may have a
    # unit_type" rule. Guards the no-JS add fallback (e2e: test_no_js_fallback_add).
    _, course = _setup(client)
    resp = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "c1"}),
        {
            "parent": "top",
            "parent_token": course.updated.isoformat(),
            "kind": "part",
            "title": "Foundations",
            "unit_type": "lesson",  # stray default from the always-submitting select
        },
        **FETCH,
    )
    assert resp.status_code == 200
    node = ContentNode.objects.get(course=course, title="Foundations")
    assert node.kind == "part"
    assert not node.unit_type  # the stray unit_type was dropped, not persisted


@pytest.mark.django_db
def test_reorder_up(client):
    _, course = _setup(client)
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="a"
    )
    b = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="b"
    )
    resp = client.post(
        reverse("courses:manage_node_move", kwargs={"slug": "c1"}),
        {"mode": "reorder", "node": b.pk, "direction": "up", "token": _tok(b)},
        **FETCH,
    )
    assert resp.status_code == 200
    titles = list(
        ContentNode.objects.filter(course=course, parent=None)
        .order_by("order")
        .values_list("title", flat=True)
    )
    assert titles == ["b", "a"]


@pytest.mark.django_db
def test_stale_token_returns_409_and_does_not_write(client):
    _, course = _setup(client)
    a = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="a"
    )
    stale = "2000-01-01T00:00:00+00:00"
    resp = client.post(
        reverse("courses:manage_node_move", kwargs={"slug": "c1"}),
        {"mode": "reorder", "node": a.pk, "direction": "down", "token": stale},
        **FETCH,
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_reparent_into_legal_parent(client):
    _, course = _setup(client)
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    resp = client.post(
        reverse("courses:manage_node_move", kwargs={"slug": "c1"}),
        {
            "mode": "reparent",
            "node": unit.pk,
            "new_parent": part.pk,
            "node_token": _tok(unit),
            "parent_token": _tok(part),
        },
        **FETCH,
    )
    assert resp.status_code == 200
    unit.refresh_from_db()
    assert unit.parent_id == part.pk


@pytest.mark.django_db
def test_reparent_picker_path_without_parent_token_succeeds(client):
    # The no-JS Move picker submits node_token + new_parent (+ position) but NO
    # parent_token; destination existence is guaranteed by the locked re-fetch, so the
    # strict stale-check is skipped. Proves the Move UI path is not permanently 409.
    _, course = _setup(client)
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    resp = client.post(
        reverse("courses:manage_node_move", kwargs={"slug": "c1"}),
        {
            "mode": "reparent",
            "node": unit.pk,
            "new_parent": part.pk,
            "position": "0",
            "node_token": _tok(unit),
        },  # no parent_token
        **FETCH,
    )
    assert resp.status_code == 200
    unit.refresh_from_db()
    assert unit.parent_id == part.pk


@pytest.mark.django_db
def test_reparent_respects_position(client):
    _, course = _setup(client)
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part, title="a"
    )
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part, title="b"
    )
    moving = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="m"
    )
    resp = client.post(
        reverse("courses:manage_node_move", kwargs={"slug": "c1"}),
        {
            "mode": "reparent",
            "node": moving.pk,
            "new_parent": part.pk,
            "position": "1",
            "node_token": _tok(moving),
            "parent_token": _tok(part),
        },
        **FETCH,
    )
    assert resp.status_code == 200
    titles = list(
        ContentNode.objects.filter(course=course, parent=part)
        .order_by("order")
        .values_list("title", flat=True)
    )
    assert titles == ["a", "m", "b"]  # landed at 0-based position 1


@pytest.mark.django_db
def test_reparent_illegal_kind_returns_422(client):
    _, course = _setup(client)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    # try to put a PART under a UNIT (units are leaves / kind-depth violation)
    resp = client.post(
        reverse("courses:manage_node_move", kwargs={"slug": "c1"}),
        {
            "mode": "reparent",
            "node": part.pk,
            "new_parent": unit.pk,
            "node_token": _tok(part),
            "parent_token": _tok(unit),
        },
        **FETCH,
    )
    assert resp.status_code == 422
    part.refresh_from_db()
    assert part.parent_id is None


@pytest.mark.django_db
def test_reparent_destination_gone_returns_409(client):
    _, course = _setup(client)
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    ghost_pk = part.pk
    part.delete()
    resp = client.post(
        reverse("courses:manage_node_move", kwargs={"slug": "c1"}),
        {
            "mode": "reparent",
            "node": unit.pk,
            "new_parent": ghost_pk,
            "node_token": _tok(unit),
            "parent_token": "2000-01-01T00:00:00+00:00",
        },
        **FETCH,
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_delete_cascades_and_compacts(client):
    _, course = _setup(client)
    ContentNodeFactory(course=course, kind="part", parent=None, title="a")
    b = ContentNodeFactory(course=course, kind="part", parent=None, title="b")
    ContentNodeFactory(course=course, kind="part", parent=None, title="c")
    resp = client.post(
        reverse("courses:manage_node_delete", kwargs={"slug": "c1"}),
        {"node": b.pk, "token": _tok(b)},
        **FETCH,
    )
    assert resp.status_code == 200
    orders = sorted(
        ContentNode.objects.filter(course=course, parent=None).values_list(
            "order", flat=True
        )
    )
    assert orders == [0, 1]


@pytest.mark.django_db
def test_unknown_mode_400(client):
    _, course = _setup(client)
    a = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=None)
    resp = client.post(
        reverse("courses:manage_node_move", kwargs={"slug": "c1"}),
        {"mode": "wat", "node": a.pk, "token": _tok(a)},
        **FETCH,
    )
    assert resp.status_code == 400
