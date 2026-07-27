import re

import pytest
from django.http import Http404
from django.urls import reverse

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
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P0")
    chapters = []
    while 1 + len(chapters) + sum(len(c[1]) for c in chapters) <= SIZE_THRESHOLD:
        ch = ContentNodeFactory(
            course=course, kind="chapter", parent=part, title=f"C{len(chapters)}"
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
