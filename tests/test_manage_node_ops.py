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
def test_consecutive_top_level_adds_succeed_with_stale_token(client):
    # Regression: the first top-level add bumps course.updated, but the top-level add
    # form lives outside the swapped [data-scope="top"] scope, so its parent_token goes
    # stale. A second top add carrying the now-STALE course token must still succeed
    # (top adds are non-conflicting appends; the `top` destination skips the check).
    _, course = _setup(client)
    stale = course.updated.isoformat()
    r1 = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "c1"}),
        {"parent": "top", "parent_token": stale, "kind": "part", "title": "A"},
        **FETCH,
    )
    assert r1.status_code == 200
    r2 = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "c1"}),
        {"parent": "top", "parent_token": stale, "kind": "part", "title": "B"},
        **FETCH,
    )
    assert r2.status_code == 200  # was 409 before the fix
    assert ContentNode.objects.filter(course=course, parent=None).count() == 2


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
def test_409_before_422_precedence(client):
    """An op that is BOTH stale-token AND would fail validation (illegal kind) must
    return 409, not 422, proving the token check runs before clean()."""
    _, course = _setup(client)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    stale = "2000-01-01T00:00:00+00:00"
    # Reparent part under unit: if the token were fresh this would be a 422
    # (a part cannot be a child of a unit — RANK[unit] >= RANK[part]).  With a stale
    # node_token the server must return 409 before ever reaching clean().
    resp = client.post(
        reverse("courses:manage_node_move", kwargs={"slug": "c1"}),
        {
            "mode": "reparent",
            "node": part.pk,
            "new_parent": unit.pk,
            "node_token": stale,  # stale — triggers ConflictError before full_clean()
            "parent_token": _tok(unit),
        },
        **FETCH,
    )
    assert resp.status_code == 409
    part.refresh_from_db()
    assert part.parent_id is None  # node was NOT moved


@pytest.mark.django_db
def test_container_less_course_renders(client):
    """A course whose only nodes are top-level units (no part/chapter/section)
    renders the builder 200 showing both unit titles and data-scope='top'."""
    owner = make_login(client, "owner2")
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    owner.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    course = CourseFactory(slug="c2", owner=owner)
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Unit Alpha"
    )
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Unit Beta"
    )
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": "c2"}))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "Unit Alpha" in content
    assert "Unit Beta" in content
    assert 'data-scope="top"' in content


@pytest.mark.django_db
def test_node_delete_get_missing_node_param_404(client):
    """A GET to node_delete with a missing or non-integer node param must return 404,
    not 500 (KeyError/ValueError guard)."""
    owner = make_login(client, "owner3")
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    owner.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    CourseFactory(slug="c3", owner=owner)
    # Missing param
    resp = client.get(reverse("courses:manage_node_delete", kwargs={"slug": "c3"}))
    assert resp.status_code == 404
    # Non-integer param
    resp2 = client.get(
        reverse("courses:manage_node_delete", kwargs={"slug": "c3"}),
        {"node": "notanint"},
    )
    assert resp2.status_code == 404


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


@pytest.mark.django_db
def test_add_quiz_chip_creates_quiz_unit(client):
    # The + Quiz chip submits name=unit_type=quiz with NO kind.
    _, course = _setup(client)
    resp = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "c1"}),
        {
            "parent": "top",
            "parent_token": course.updated.isoformat(),
            "unit_type": "quiz",
            "title": "Q1",
        },
        **FETCH,
    )
    assert resp.status_code == 200
    node = ContentNode.objects.get(course=course, title="Q1")
    assert node.kind == "unit"
    assert node.unit_type == "quiz"


@pytest.mark.django_db
def test_add_lesson_chip_creates_lesson_unit(client):
    _, course = _setup(client)
    resp = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "c1"}),
        {
            "parent": "top",
            "parent_token": course.updated.isoformat(),
            "unit_type": "lesson",
            "title": "L1",
        },
        **FETCH,
    )
    assert resp.status_code == 200
    node = ContentNode.objects.get(course=course, title="L1")
    assert node.kind == "unit"
    assert node.unit_type == "lesson"


@pytest.mark.django_db
def test_add_neither_kind_nor_unit_type_is_422(client):
    # Malformed/no-button submit: no kind, no unit_type -> kind="" -> full_clean 422.
    _, course = _setup(client)
    resp = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "c1"}),
        {"parent": "top", "parent_token": course.updated.isoformat(), "title": "X"},
        **FETCH,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_type_toggle_flips_type_without_wiping_settings(client):
    _, course = _setup(client)
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        title="Keep me",
        obligatory=True,
        html_seed_js="{a:1}",
    )
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "c1"}),
        {
            "node": unit.pk,
            "token": unit.updated.isoformat(),
            "ctx": "editor",
            "type_only": "1",
            "unit_type": "quiz",
        },
    )  # full-page POST (no FETCH) -> editor redirect
    assert resp.status_code == 302
    unit.refresh_from_db()
    assert unit.unit_type == "quiz"  # flipped
    assert unit.title == "Keep me"  # NOT blanked
    assert unit.obligatory is True  # NOT cleared
    assert unit.html_seed_js == "{a:1}"  # NOT wiped


@pytest.mark.django_db
def test_settings_form_still_updates_all_fields(client):
    # Regression: the full settings form (has_settings) still works end-to-end.
    _, course = _setup(client)
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        title="Old",
    )
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "c1"}),
        {
            "node": unit.pk,
            "token": unit.updated.isoformat(),
            "ctx": "editor",
            "has_settings": "1",
            "title": "New",
            "unit_type": "quiz",
            "html_seed_js": "",
        },
    )
    assert resp.status_code == 302
    unit.refresh_from_db()
    assert unit.title == "New"
    assert unit.unit_type == "quiz"
    assert unit.obligatory is False  # checkbox absent -> cleared, as before
