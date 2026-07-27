import re
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest
from django.http import Http404
from django.urls import reverse

from courses.builder_open import OPEN_KEY
from courses.builder_open import SIZE_THRESHOLD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login


def _big_course(owner, units_each=4):
    """Deliberately OVER SIZE_THRESHOLD, so the lazy path is exercised.

    A fixture under the threshold opens fully (spec section 3a) and would make
    every assertion below pass vacuously.
    """
    course = CourseFactory(slug="big", owner=owner)
    part = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="P0"
    )
    chapters = []
    while 1 + len(chapters) + sum(len(c[1]) for c in chapters) <= SIZE_THRESHOLD:
        ch = ContentNodeFactory(
            course=course,
            kind="chapter",
            unit_type=None,
            parent=part,
            title=f"C{len(chapters)}",
        )
        units = [
            ContentNodeFactory(
                course=course,
                kind="unit",
                unit_type="lesson",
                parent=ch,
                title=f"U{len(chapters)}-{i}",
            )
            for i in range(units_each)
        ]
        chapters.append((ch, units))
    return course, part, chapters


@pytest.mark.django_db
def test_collapsed_scope_emits_no_descendant_rows(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": "big"}))
    html = resp.content.decode()
    assert f'data-node="{part.pk}"' in html  # top level renders
    first_chapter = chapters[0][0]
    assert f'data-node="{first_chapter.pk}"' not in html  # its children do not
    assert f'data-scope="{part.pk}"' not in html


@pytest.mark.django_db
def test_open_param_renders_exactly_that_scope(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    ch = chapters[0][0]
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    html = client.get(f"{url}?open={part.pk}").content.decode()
    assert f'data-node="{ch.pk}"' in html  # part's children appear
    assert f'data-node="{chapters[0][1][0].pk}"' not in html  # chapter's do not


@pytest.mark.django_db
def test_builder_tree_query_count_does_not_grow_with_open_scopes(client):
    """The spec's query-count invariant. Compare the SAME page collapsed vs
    fully expanded: the tree path is one query either way, so any delta means
    an N+1 crept into _open_descendants, _extra_container_pks or the toggle."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    owner = make_login(client, "owner")
    _big_course(owner)
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    client.get(url)  # warm sessions/auth so the two counts are comparable
    with CaptureQueriesContext(connection) as collapsed:
        client.get(f"{url}?open=")
    with CaptureQueriesContext(connection) as expanded:
        client.get(f"{url}?open=all")
    assert len(expanded) == len(collapsed), (
        f"expanded={len(expanded)} collapsed={len(collapsed)}; "
        "an N+1 was introduced in the tree path"
    )


@pytest.mark.django_db
def test_small_course_still_arrives_fully_expanded(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="small", owner=owner)
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    ch = ContentNodeFactory(course=course, kind="chapter", parent=part, title="C")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, title="U"
    )
    html = client.get(
        reverse("courses:manage_builder", kwargs={"slug": "small"})
    ).content.decode()
    for node in (part, ch, unit):
        assert f'data-node="{node.pk}"' in html


@pytest.mark.django_db
def test_collapsed_container_renders_a_toggle_with_its_direct_child_count(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    html = client.get(
        reverse("courses:manage_builder", kwargs={"slug": "big"})
    ).content.decode()
    row = re.search(rf'data-node="{part.pk}".*?</div>', html, re.S).group(0)
    assert f'data-toggle="{part.pk}"' in row
    assert 'aria-expanded="false"' in row
    assert "aria-controls" not in row  # invalid ARIA while collapsed
    # Assert the WHOLE label. `str(len(chapters)) in row` is vacuous: with 30
    # chapters, "30" also appears inside data-updated timestamps, maxlength
    # and pks, so it can never fail.
    assert f'aria-label="Expand P0, {len(chapters)} items"' in row


@pytest.mark.django_db
def test_truncation_renders_a_keyed_info_entry(client, monkeypatch):
    """The ceiling is slice 1, so its user-visible consequence must be too."""
    monkeypatch.setattr("courses.builder_open.CEILING", 2)
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    html = client.get(
        reverse("courses:manage_builder", kwargs={"slug": "big"}) + "?open=all"
    ).content.decode()
    assert 'data-info-key="truncation"' in html
    assert 'role="status"' in html


@pytest.mark.django_db
def test_a_collapsed_container_with_zero_children_still_toggles(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    empty = ContentNodeFactory(
        course=course, kind="chapter", parent=part, title="Empty"
    )
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    html = client.get(f"{url}?open={part.pk}").content.decode()
    assert f'data-toggle="{empty.pk}"' in html
    opened = client.get(f"{url}?open={part.pk},{empty.pk}").content.decode()
    assert f'data-scope="{empty.pk}"' in opened
    # the add affordance lives INSIDE the scope, so it appears only when open
    assert f'data-add-scope="{empty.pk}"' in opened


@pytest.mark.django_db
def test_adding_a_unit_does_not_change_the_open_set(client):
    """extra_open's effect 1 drops unit pks; effect 2 (slice 2) keeps them."""
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    ch = chapters[0][0]
    resp = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "big"}),
        {
            "parent": ch.pk,
            "parent_token": ch.updated.isoformat(),
            "unit_type": "lesson",
            "title": "New unit",
            "open": f"{part.pk},{ch.pk}",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    new = course.nodes.get(title="New unit")
    html = resp.content.decode()
    assert f'data-node="{new.pk}"' in html  # the row is there
    assert f'data-scope="{new.pk}"' not in html  # a unit owns no scope


@pytest.mark.django_db
def test_render_scope_rejects_a_non_numeric_scope_ref():
    """The real hazard the routing-level 404 test does NOT cover: <int:pk>
    stops a bad pk at the resolver, but _render_scope is also called
    internally, where int(scope_ref) would raise a 500."""
    from django.test import RequestFactory

    from courses.views_manage import _render_scope

    course = CourseFactory(slug="rs")
    r = RequestFactory().get("/")
    r.session = {}
    with pytest.raises((ValueError, Http404)):
        _render_scope(r, course, "not-a-pk")


@pytest.mark.django_db
def test_expanded_container_pairs_aria_controls_with_the_scope_id(client):
    owner = make_login(client, "owner")
    course, part, _chapters = _big_course(owner)
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    html = client.get(f"{url}?open={part.pk}").content.decode()
    assert f'aria-controls="tree-scope-{part.pk}"' in html
    assert f'id="tree-scope-{part.pk}"' in html
    assert 'aria-expanded="true"' in html


def _toggle_open_pks(html, pk):
    """The `open` pks in the toggle href for `pk`, as a set of ints.

    Parses rather than substring-matching: comma-joined pks are
    prefix-colliding, so `str(31) not in "1,131"` is both wrong and the exact
    trap toggle_href itself is written to avoid. The regex is anchored on the
    emitted attribute ORDER (class, href, data-toggle) -- reversing it makes
    the match silently fail, and an `assert m is None or ...` would then pass
    on the miss.
    """
    m = re.search(
        rf'<a class="tree__toggle" href="([^"]+)"[^>]*data-toggle="{pk}"', html
    )
    assert m, f"no toggle href found for pk={pk}"
    qs = parse_qs(urlparse(m.group(1)).query)
    raw = (qs.get("open") or [""])[0]
    return {int(t) for t in raw.split(",") if t.strip().isdigit()}


@pytest.mark.django_db
def test_expand_href_adds_this_pk_to_the_open_set(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    html = client.get(
        reverse("courses:manage_builder", kwargs={"slug": "big"})
    ).content.decode()
    assert _toggle_open_pks(html, part.pk) == {part.pk}


@pytest.mark.django_db
def test_collapse_href_drops_this_pk_AND_its_open_descendants(client):
    """Collapse must forget descendants, or the no-JS path diverges from the
    JS path (which forgets them automatically by removing the subtree)."""
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    ch = chapters[0][0]
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    html = client.get(f"{url}?open={part.pk},{ch.pk}").content.decode()
    # the part is expanded, so its toggle is a COLLAPSE href
    assert _toggle_open_pks(html, part.pk) == set()
    # and the chapter's own toggle (also expanded) only drops itself
    assert _toggle_open_pks(html, ch.pk) == {part.pk}


@pytest.mark.django_db
def test_toggle_href_carries_a_row_anchor(client):
    owner = make_login(client, "owner")
    course, part, _c = _big_course(owner)
    html = client.get(
        reverse("courses:manage_builder", kwargs={"slug": "big"})
    ).content.decode()
    assert f"#node-{part.pk}" in html
    assert f'id="node-{part.pk}"' in html


@pytest.mark.django_db
def test_scope_endpoint_returns_one_scope_for_a_manager(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    resp = client.get(
        reverse("courses:manage_node_scope", kwargs={"slug": "big", "pk": part.pk})
    )
    assert resp.status_code == 200
    assert f'data-scope="{part.pk}"' in resp.content.decode()


@pytest.mark.django_db
def test_scope_endpoint_404s_on_a_unit_and_on_a_foreign_pk(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    unit = chapters[0][1][0]
    assert (
        client.get(
            reverse("courses:manage_node_scope", kwargs={"slug": "big", "pk": unit.pk})
        ).status_code
        == 404
    )
    foreign = ContentNodeFactory(
        course=CourseFactory(slug="other"), kind="part", parent=None
    )
    assert (
        client.get(
            reverse(
                "courses:manage_node_scope", kwargs={"slug": "big", "pk": foreign.pk}
            )
        ).status_code
        == 404
    )


@pytest.mark.django_db
def test_scope_endpoint_403s_a_non_manager_and_redirects_anonymous(client):
    owner = make_login(client, "owner")
    course, part, _c = _big_course(owner)
    url = reverse("courses:manage_node_scope", kwargs={"slug": "big", "pk": part.pk})
    make_login(client, "stranger")
    assert client.get(url).status_code == 403
    client.logout()
    assert client.get(url).status_code == 302


@pytest.mark.django_db
def test_reparent_into_a_collapsed_destination_returns_the_moved_node(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    src, dest = chapters[0][0], chapters[1][0]
    unit = chapters[0][1][0]
    resp = client.post(
        reverse("courses:manage_node_move", kwargs={"slug": "big"}),
        {
            "mode": "reparent",
            "node": unit.pk,
            "node_token": unit.updated.isoformat(),
            "new_parent": dest.pk,
            "position": 0,
            "open": str(src.pk),  # dest is NOT open
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    # Without extra_open the row vanishes with no marker -- indistinguishable
    # from failure, on the affordance that exists for unseen destinations.
    assert f'data-node="{unit.pk}"' in resp.content.decode()


@pytest.mark.django_db
def test_adding_a_container_returns_it_already_open(client):
    owner = make_login(client, "owner")
    course, part, _c = _big_course(owner)
    resp = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "big"}),
        {
            "parent": part.pk,
            "parent_token": part.updated.isoformat(),
            "kind": "chapter",
            "title": "Fresh",
            "open": str(part.pk),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    new = course.nodes.get(title="Fresh")
    assert f'data-scope="{new.pk}"' in html  # its own scope is rendered


@pytest.mark.django_db
def test_no_js_mutation_round_trips_the_open_set_through_the_session(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    client.get(f"{url}?open={part.pk}")  # persisted (step 2)
    assert client.session[OPEN_KEY]["big"] == [part.pk]
    resp = client.post(
        reverse("courses:manage_node_rename", kwargs={"slug": "big"}),
        {"node": part.pk, "token": part.updated.isoformat(), "title": "P0 renamed"},
    )
    assert resp.status_code == 302
    assert "open=session" in resp["Location"]
    html = client.get(resp["Location"]).content.decode()
    assert f'data-node="{chapters[0][0].pk}"' in html  # still expanded


@pytest.mark.django_db
def test_a_derived_open_set_is_not_persisted(client):
    """Only an explicit `open` (steps 1-2) is written back."""
    owner = make_login(client, "owner")
    course, part, _c = _big_course(owner)
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    client.get(f"{url}?open={part.pk}")
    client.get(url)  # seeded, not explicit
    assert client.session[OPEN_KEY]["big"] == [part.pk]  # unchanged


@pytest.mark.django_db
def test_no_js_add_carries_the_ANCESTOR_CHAIN_not_a_bare_pk(client):
    """Falsifies _persist_chain's central rule.

    With the session cleared, a bare [new_pk] is non-empty -- so `open=session`
    would NOT fall through, and the tree would render with every ancestor
    collapsed, hiding the node just created. Replace _ancestor_chain(node) with
    {node.pk} and this must go RED.
    """
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    ch = chapters[0][0]
    session = client.session
    session.pop(OPEN_KEY, None)
    session.save()
    resp = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": "big"}),
        {
            "parent": ch.pk,
            "parent_token": ch.updated.isoformat(),
            "kind": "section",
            "title": "Deep",
        },
    )
    assert "open=session" in resp["Location"]
    html = client.get(resp["Location"]).content.decode()
    new = course.nodes.get(title="Deep")
    assert f'data-node="{new.pk}"' in html  # visible, so the chain came too
    assert f'data-scope="{ch.pk}"' in html  # its parent is open


@pytest.mark.django_db
def test_no_js_reparent_via_the_picker_persists_the_destination_chain(client):
    """The picker exists for destinations the author cannot see; the no-JS half
    is the one with the reparent-capture ordering hazard."""
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    dest = chapters[1][0]
    unit = chapters[0][1][0]
    resp = client.post(
        reverse("courses:manage_node_move", kwargs={"slug": "big"}),
        {
            "mode": "reparent",
            "node": unit.pk,
            "node_token": unit.updated.isoformat(),
            "new_parent": dest.pk,
            "position": 0,
        },
    )
    assert "open=session" in resp["Location"]
    assert dest.pk in client.session[OPEN_KEY]["big"]
    html = client.get(resp["Location"]).content.decode()
    assert f'data-node="{unit.pk}"' in html


@pytest.mark.django_db
def test_builder_response_stays_small_and_shallow(client):
    """The spec calls this 'the test that actually guards this regression from
    coming back'. Ceilings are derived from Task 3 Step 11's measurement; raise
    them only with a measurement that justifies it.
    """
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": "big"}))
    html = resp.content.decode()
    assert html.count('class="tree__row"') <= 5  # top level only
    assert len(resp.content) < 120_000


@pytest.mark.django_db
def test_open_session_falling_through_does_not_persist_the_derived_set(client):
    """The case `"open" in request.GET` gets wrong.

    The parameter IS present, but the resolved set came from the size rule /
    seed. Gating on raw presence would overwrite the author's real set here.
    """
    owner = make_login(client, "owner")
    course, part, _c = _big_course(owner)
    url = reverse("courses:manage_builder", kwargs={"slug": "big"})
    session = client.session
    session.pop(OPEN_KEY, None)
    session.save()
    client.get(f"{url}?open=session")
    assert OPEN_KEY not in client.session or "big" not in client.session.get(
        OPEN_KEY, {}
    )


@pytest.mark.django_db
def test_delete_confirm_round_trips_the_open_set(client):
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    victim = chapters[0][1][0]
    confirm = client.get(
        reverse("courses:manage_node_delete", kwargs={"slug": "big"})
        + f"?node={victim.pk}&open={part.pk},{chapters[0][0].pk}"
    )
    assert f'value="{part.pk},{chapters[0][0].pk}"' in confirm.content.decode()
    resp = client.post(
        reverse("courses:manage_node_delete", kwargs={"slug": "big"}),
        {
            "node": victim.pk,
            "token": victim.updated.isoformat(),
            "open": f"{part.pk},{chapters[0][0].pk}",
        },
    )
    assert f"open={part.pk}" in resp["Location"]
    assert "open=session" not in resp["Location"]


@pytest.mark.django_db
def test_delete_without_an_open_param_falls_back_to_the_session_sentinel(client):
    """No-JS: there is no href rewrite, so `open` is absent -- and emitting
    `open=` would blank the tree instead of degrading."""
    owner = make_login(client, "owner")
    course, part, chapters = _big_course(owner)
    victim = chapters[0][1][0]
    resp = client.post(
        reverse("courses:manage_node_delete", kwargs={"slug": "big"}),
        {"node": victim.pk, "token": victim.updated.isoformat()},
    )
    assert "open=session" in resp["Location"]
