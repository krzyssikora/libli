import pytest
from django.test import Client
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login


@pytest.fixture
def filtered_course(client, db):
    """part > chapter > units, with exactly one matching unit deep down.

    `make_login(client, username)` takes the CLIENT and returns the USER
    (tests/factories.py:175) -- the repo idiom is the pytest-django `client`
    fixture plus `owner = make_login(client, "...")`, as in
    tests/test_builder_lazy_scopes.py:52.
    """
    owner = make_login(client, "pa")
    course = CourseFactory(slug="filt", owner=owner)
    part = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Czesc I"
    )
    chap = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, title="Rozdzial"
    )
    hit = ContentNodeFactory(
        course=course, kind="unit", parent=chap, title="Trygonometria & wektory"
    )
    miss = ContentNodeFactory(course=course, kind="unit", parent=chap, title="Logika")
    # A CHILDLESS container, so _scope.html's {% empty %} branch is reachable
    # at all: without it no scope in this fixture is ever empty under
    # `open=all`, and the unfiltered half of the empty-message row cannot pass.
    # "Pusty" matches no query used anywhere in this plan.
    ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, title="Pusty"
    )
    return client, course, part, chap, hit, miss


def test_a_filtered_page_shows_the_match_and_hides_the_rest(filtered_course):
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "trygo"}).content.decode()
    assert f'data-node="{hit.pk}"' in body
    assert f'data-node="{chap.pk}"' in body
    assert f'data-node="{part.pk}"' in body
    assert f'data-node="{miss.pk}"' not in body


def test_a_below_floor_query_renders_unfiltered_and_emits_no_filter_entry(
    filtered_course,
):
    """?q=a is a PRESENT q that is INACTIVE. Catches a q_active derived from
    bool(q.strip()) rather than from the floor.

    The SECOND assertion is a carry-forward, not a gate for this task: at Task
    3 `_info_entries` still has its interim truncation-only body, so no
    `filter` entry can be emitted by anything and the assertion cannot fail.
    It starts biting at Task 5 Step 3, which is what makes it worth writing
    now rather than then.
    """
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "a", "open": "all"}).content.decode()
    assert f'data-node="{miss.pk}"' in body
    assert 'data-info-key="filter"' not in body


def test_data_applied_q_holds_the_raw_q_and_is_always_present(filtered_course):
    """A conditionally-emitted attribute puts null in the tracker; the
    TypeError surfaces later in the input handler and filtering goes silently
    inert (spec 3k)."""
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    for params, expected in (({}, ""), ({"q": "a"}, "a"), ({"q": "trygo"}, "trygo")):
        body = client.get(url, params).content.decode()
        assert f'data-applied-q="{expected}"' in body, params


def test_data_q_min_is_emitted_and_read_through_the_module(
    filtered_course, monkeypatch
):
    client, course, *_ = filtered_course
    monkeypatch.setattr("courses.builder_filter.MIN_QUERY", 3)
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    assert 'data-q-min="3"' in client.get(url).content.decode()


def test_a_matched_container_renders_OPEN_over_an_empty_scope(filtered_course):
    """Spec 1d. The fixture must pick a matched container with NO matching
    descendant, or the scope is non-empty and the row proves nothing."""
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "rozdzial"}).content.decode()
    toggle = body.split(f'data-toggle="{chap.pk}"')[1].split(">")[0]
    assert 'aria-expanded="true"' in toggle
    assert f'aria-controls="tree-scope-{chap.pk}"' in toggle
    assert f'data-node="{hit.pk}"' not in body  # no descendant matched
    # The "No matching titles." wording is Task 6's; asserting it here would
    # make this task's own gate red until then.


def test_remember_open_does_NOT_write_while_a_filter_is_active(filtered_course):
    """Asserted ON THE SESSION, never on the render. Driven through a TOGGLE
    under an active filter: a bare filtered GET resolves via step 3, which is
    not `explicit`, so the write is already suppressed and the row would pass
    without the rule. This is the half slice 1 could not write."""
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    client.get(url, {"open": f"{part.pk},{chap.pk}"})  # persists the real set
    before = client.session.get("builder_open", {}).get(course.slug)
    client.get(url, {"q": "trygo", "open": str(part.pk)})  # a toggle, filtered
    assert client.session.get("builder_open", {}).get(course.slug) == before


def test_remember_open_DOES_write_under_a_below_floor_q(filtered_course):
    """The half where this spec deliberately narrows the parent's "q is
    absent" to "q is ACTIVE". A presence gate (`"q" in request.GET`) is
    strictly stricter and passes the row above too, so only this one catches
    it -- and the loss it prevents is invisible: a no-JS author silently stops
    persisting expansions whenever a stray ?q=a sits in the URL."""
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    client.get(url, {"q": "a", "open": f"{part.pk},{chap.pk}"})
    stored = client.session.get("builder_open", {}).get(course.slug)
    assert stored == sorted([part.pk, chap.pk])


def test_counts_under_a_filter_are_the_filtered_counts(filtered_course):
    """The toggle promises what the filtered view will actually show."""
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "trygo"}).content.decode()
    # The chapter has two units in full, one under the filter.
    assert "1 item" in body or "1 element" in body
    assert "2 items" not in body


def test_effect_two_reinserts_into_a_parent_with_no_key(filtered_course):
    """Task 3's own red gate for `setdefault`. Direct on the helper, because
    the user-visible route (a no-JS add into an empty filtered scope) is not
    wired until Task 7. `chap` matches "rozdzial" and has no matching
    descendant, so the restricted map has NO key for it at all.
    """
    # `courses` sorts BEFORE `courses.views_manage`. ruff's I rules apply to
    # nested blocks too, and `ruff format` does not reorder imports -- pasted
    # the other way round this is an I001 at Step 10's `ruff check` gate,
    # which the commit depends on. (Verified: I001 fires on the nested block.)
    from courses import builder_filter
    from courses.views_manage import _apply_effect_two
    from courses.views_manage import _children_map

    _, course, part, chap, hit, miss = filtered_course
    cmap = _children_map(course)
    restricted, *_ = builder_filter.filtered_map(cmap, "rozdzial")
    assert chap.pk not in restricted, "fixture drifted; the row proves nothing"
    _apply_effect_two(restricted, (hit.pk,), cmap)
    assert [n.pk for n in restricted[chap.pk]] == [hit.pk]


def test_a_filtered_scope_fragment_returns_only_matching_children(filtered_course):
    """Task 3's own red gate for `nodes` AND `children_map` both coming from
    the RESTRICTED map. Task 11's e2e drives this through the browser; this
    drives the endpoint directly, in the commit that introduces the bug.

    Request PART's scope, not the chapter's. The chapter's children are units
    with no children of their own, so `children_map` is never read on that
    path and the second falsification below cannot go red. From `part`:
      * `nodes`        -> part's children: chapter "Rozdzial", NOT "Pusty"
      * `children_map` -> the recursive descent into Rozdzial: `hit`, not `miss`
    Under q=trygo the fragment carries no `open`, so precedence step 3 resolves
    to the chains {part, chap} and the descent actually happens (spec 3b).
    """
    client, course, part, chap, hit, miss = filtered_course
    url = reverse(
        "courses:manage_node_scope", kwargs={"slug": course.slug, "pk": part.pk}
    )
    text = client.get(
        url, {"q": "trygo"}, **{"HTTP_X_REQUESTED_WITH": "fetch"}
    ).content.decode()
    assert f'data-node="{chap.pk}"' in text
    assert f'data-node="{hit.pk}"' in text, "the descent did not happen; row is vacuous"
    assert f'data-node="{miss.pk}"' not in text  # children_map is restricted
    assert "Pusty" not in text  # nodes is restricted


def test_manage_tree_access_control(filtered_course):
    """The same rows as manage_node_scope MINUS the pk row -- four in total.
    NOT 'non-numeric pk -> 404': this route has no pk, so such a test would
    guard nothing (the resolver would 404 before the view ran)."""
    client, course, *_ = filtered_course
    url = reverse("courses:manage_tree", kwargs={"slug": course.slug})

    assert Client().get(url).status_code in (301, 302)

    other = Client()
    make_login(other, "nobody")
    assert other.get(url).status_code == 403

    assert client.get(url).status_code == 200

    missing = reverse("courses:manage_tree", kwargs={"slug": "no-such-course"})
    assert client.get(missing).status_code == 404


def test_manage_tree_returns_the_top_scope_and_nothing_else(filtered_course):
    """applyFragment consumes firstElementChild; returning .builder__tree
    with its header would break that single-element contract."""
    client, course, *_ = filtered_course
    url = reverse("courses:manage_tree", kwargs={"slug": course.slug})
    body = client.get(url).content.decode().strip()
    assert body.startswith("<ol")
    assert 'data-scope="top"' in body
    assert "builder__tree" not in body


def test_manage_tree_honours_q(filtered_course):
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_tree", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "trygo"}).content.decode()
    assert f'data-node="{hit.pk}"' in body
    assert f'data-node="{miss.pk}"' not in body
