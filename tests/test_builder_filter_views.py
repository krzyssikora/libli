import pytest
from django.test import Client
from django.urls import reverse

from courses.models import ContentNode
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


def test_render_scope_always_sets_the_header_and_uses_none_when_empty(filtered_course):
    """`none` rather than an absent header: the client cannot otherwise tell a
    rename 200 (must NOT clear) from a code-less scope response (must clear).
    """
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_tree", kwargs={"slug": course.slug})
    assert client.get(url)["X-Builder-Info"] == "none"
    filtered = client.get(url, {"q": "trygo"})
    assert filtered["X-Builder-Info"] == "filter;shown=1;total=1"


def test_the_header_is_machine_readable_under_the_polish_locale(
    filtered_course, monkeypatch
):
    """A human string in the header would reach the JS as a value it then
    pastes into a role=status region, in whatever locale the request happened
    to use -- and `raw.split(", ")` would shred it into bogus keys.

    CEILING=0 forces the TRUNCATION entry alongside the filter one, and it is
    the only notice whose Polish contains a non-ASCII character
    ("...zakresów."). Without it this row cannot fail: "Filtrowane: 1 / 1" is
    pure ASCII, so an implementation that put the human text in the header
    would still satisfy every assertion below.

    Note what actually bites: `ó` IS latin-1-encodable, so Django does NOT
    MIME-encode it -- the header simply comes back non-ASCII. `isascii()` is
    the load-bearing assertion; the `=?utf-8?` one covers the strings that are
    not latin-1-encodable.
    """
    monkeypatch.setattr("courses.builder_open.CEILING", 0)
    client, course, *_ = filtered_course
    url = reverse("courses:manage_tree", kwargs={"slug": course.slug})
    # The session key, NOT `with override("pl")` and NOT Accept-Language
    # alone. Two middlewares/signals stack against both:
    #   * core.middleware.SessionLocaleMiddleware (installed at
    #     config/settings/base.py:48) calls translation.activate per request
    #     (core/middleware.py:48-54), discarding an ambient `override`.
    #   * `make_login` calls force_login, which fires user_logged_in, and
    #     core/signals.py:14-21 seeds session["_language"] from user.language
    #     -- which accounts/models.py:28 defaults to "en". That key is what
    #     SessionLocaleMiddleware PREFERS (core/middleware.py:49-51), so it
    #     never reaches Accept-Language at all.
    # So Accept-Language alone renders `en` and the Content-Language guard
    # below goes red. Seed the session, exactly as
    # tests/test_builder_lazy_scopes.py:634-641 already does.
    session = client.session
    session["_language"] = "pl"
    session.save()
    resp = client.get(
        url,
        {"q": "trygo"},
        HTTP_ACCEPT_LANGUAGE="pl",
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    # Content-Language alone: this response is a bare <ol> fragment, so the
    # "Filtrowane" notice (which lives in builder.html's info slot) is never
    # part of it. core/middleware.py:43 subclasses LocaleMiddleware, whose
    # process_response sets this header.
    assert resp["Content-Language"] == "pl", (
        "the Polish locale is not actually active; the assertions below would "
        "be vacuous"
    )
    value = resp["X-Builder-Info"]
    assert value.isascii()
    assert "=?utf-8?" not in value


def test_a_rename_and_a_422_carry_no_header_at_all(filtered_course):
    """They never reach _render_scope, so they neither set nor clear."""
    client, course, part, chap, hit, miss = filtered_course
    rename = reverse("courses:manage_node_rename", kwargs={"slug": course.slug})
    resp = client.post(
        rename,
        {
            "node": hit.pk,
            "token": hit.updated.isoformat(),
            "title": "Nowy",
            "q": "trygo",
        },
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    assert resp.status_code == 200
    assert "X-Builder-Info" not in resp

    # the 422 half the test's name promises: an empty title is rejected by the
    # form, and _op_error.html never reaches _render_scope either
    bad = client.post(
        reverse("courses:manage_node_add", kwargs={"slug": course.slug}),
        {
            "parent": chap.pk,
            "parent_token": chap.updated.isoformat(),
            "kind": "unit",
            "unit_type": "lesson",
            "title": "",
            "q": "trygo",
        },
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    assert bad.status_code == 422
    assert "X-Builder-Info" not in bad


def test_the_info_slot_is_present_and_empty_on_an_unfiltered_page(filtered_course):
    """Present, not hidden, and with NO text content: `:empty` does not match
    an element containing whitespace, and one newline leaves a sunken grey bar
    on every builder page, permanently."""
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url).content.decode()
    assert 'class="builder__info"' in body
    assert "hidden" not in body.split('class="builder__info"')[1].split(">")[0]
    marker = body.split('class="builder__info"')[1]
    open_tag_end = marker.index(">")
    assert marker[open_tag_end + 1 : open_tag_end + 6].startswith("</ul>")


def test_a_server_rendered_notice_is_visible_without_js(filtered_course):
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "trygo"}).content.decode()
    assert 'data-info-key="filter"' in body


def test_toggle_hrefs_preserve_q(filtered_course):
    """Sliced to the TOGGLE anchor specifically.

    A bare `assert "q=trygo" in body` is vacuous: Step 5 puts `&q=trygo` into
    the delete and Move href of every rendered row (and Task 9 adds two bulk
    hrefs), so it passes with the toggle_href edit reverted entirely. Nothing
    else in this plan can go red against that, which is how an unguarded edit
    ships.
    """
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "trygo"}).content.decode()
    # The toggle is an <a> whose href toggle_href builds and which ends
    # `#node-<pk>`; slice backwards from its data-toggle hook to that anchor's
    # own `href="`.
    marker = f'data-toggle="{chap.pk}"'
    assert marker in body, "the chapter toggle did not render; the row proves nothing"
    tag = body[body.rindex("<a", 0, body.index(marker)) : body.index(marker)]
    assert "q=trygo" in tag, tag
    assert f"#node-{chap.pk}" in tag, "not the toggle anchor -- re-derive the slice"


def test_markup_hrefs_percent_encode_q(filtered_course):
    """Django autoescapes HTML but does NOT percent-encode. A query with an
    `&` splits into a second parameter -- filtering for `x&open=all` makes the
    delete-confirm GET arrive with open=all attached -- and a `#` truncates
    the href outright."""
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    # The query must BOTH contain `&`/space AND FOLD INTO a title. A query
    # that matches nothing renders an empty restricted map, `_scope.html`
    # takes {% empty %}, no _tree_node.html is included -- so there is no
    # delete or Move href in the response at all and the falsification is
    # unreachable. `hit` is titled "Trygonometria & wektory" for this row.
    # MEASURED, not eyeballed. Two earlier drafts of this row shipped a query
    # that matched NOTHING: fold("tryg & wek") is not a substring of
    # fold("Trygonometria & wektory"), because `tryg` is followed by
    # `onometria`. Check any replacement the same way -- run
    # `fold(q) in fold(title)` and require True -- rather than by reading it.
    body = client.get(url, {"q": "metria & wek"}).content.decode()
    assert f'data-node="{hit.pk}"' in body, "no row rendered; the row proves nothing"
    # space -> %20 or +, & -> %26; the raw `&` must NOT survive into the href
    assert "q=metria%20%26%20wek" in body or "q=metria+%26+wek" in body
    # The template writes `&amp;q=`, so THAT is what the HTML source holds.
    delete_href = body.split('data-delete="')[0].rsplit('href="', 1)[1]
    assert "&amp;q=" in delete_href
    assert "& wek" not in delete_href
    # Asserted ON THE DELETE HREF, not on the body. The two assertions above
    # cannot tell `{{ q|urlencode }}` from a bare `{{ q }}` and MEASURABLY do
    # not: autoescaping renders the bare form as `&amp;q=metria &amp; wek`,
    # which still satisfies `"&amp;q=" in delete_href` and still contains no
    # literal `"& wek"` -- while the entity decodes back to a real `&` in the
    # browser and splits the query into `q=metria ` plus ` wek=`. And the
    # body-level percent-encoding assertion is satisfied by toggle_href's own
    # `q=metria+%26+wek` whatever this href holds.
    assert "q=metria%20%26%20wek" in delete_href or "q=metria+%26+wek" in delete_href


def test_the_six_redirect_sites_carry_q(filtered_course):
    """One assertion per SITE, not one site standing for six.

    The four non-rename sites are otherwise unguarded by anything in this
    plan: Task 7's rows that follow those same redirects assert a row is
    PRESENT, which is equally true of a fully unfiltered render -- so dropping
    `_raw_q(request)` at node_add (:489), node_move reorder (:585), node_move
    reparent (:621) or node_duplicate (:715) would pass every other row here.
    """
    client, course, part, chap, hit, miss = filtered_course
    rename = reverse("courses:manage_node_rename", kwargs={"slug": course.slug})
    add = reverse("courses:manage_node_add", kwargs={"slug": course.slug})
    move = reverse("courses:manage_node_move", kwargs={"slug": course.slug})
    dup = reverse("courses:manage_node_duplicate", kwargs={"slug": course.slug})
    delete = reverse("courses:manage_node_delete", kwargs={"slug": course.slug})

    def tok(node):
        """Every mutation bumps `updated`, so read the token immediately
        before the post that uses it -- a token captured up front is stale by
        the second iteration and the row 409s instead of redirecting."""
        node.refresh_from_db()
        return node.updated.isoformat()

    def check(label, url, payload, q="trygo"):
        payload["q"] = q
        resp = client.post(url, payload)
        assert resp.status_code == 302, f"{label}: {resp.status_code}"
        assert "open=session" in resp["Location"], label
        if q == "metria & wek":
            # `&`-bearing q, asserted on the PERCENT-ENCODED form: "trygo"/"a"
            # are encoding-invariant and cannot tell Python's urlencode from a
            # raw f-string interpolation. Same idiom as
            # test_markup_hrefs_percent_encode_q.
            assert (
                "q=metria%20%26%20wek" in resp["Location"]
                or "q=metria+%26+wek" in resp["Location"]
            ), label
        else:
            assert f"q={q}" in resp["Location"], label

    check("rename", rename, {"node": hit.pk, "token": tok(hit), "title": "Nowy"})
    check(
        "add",
        add,
        {
            "parent": chap.pk,
            "parent_token": tok(chap),
            "kind": "unit",
            "unit_type": "lesson",
            "title": "Dodana",
        },
    )
    # BELOW the floor here only: Task 8 refuses a reorder under an ACTIVE
    # filter with 422, so q=trygo would assert against the refusal, not the
    # redirect. `miss` is not the first child, so "up" is a real move.
    check(
        "reorder",
        move,
        {"mode": "reorder", "node": miss.pk, "direction": "up", "token": tok(miss)},
        q="a",
    )
    check(
        "reparent",
        move,
        {
            "mode": "reparent",
            "node": miss.pk,
            "new_parent": part.pk,
            "position": 0,
            "node_token": tok(miss),
        },
    )
    check("duplicate", dup, {"node": hit.pk, "token": tok(hit)}, q="metria & wek")
    # LAST, and the sixth site: node_delete's NON-bespoke branch, i.e. no
    # `open` in the POST. The bespoke `open`-carrying branch is
    # test_node_delete_bespoke_redirect_carries_q.
    check("delete", delete, {"node": miss.pk, "token": tok(miss)})


def test_node_delete_bespoke_redirect_carries_q(filtered_course):
    """views_manage.py:672-675 builds its own redirect rather than going
    through _redirect_to_builder, and it is the JS-REWRITTEN path: a no-JS
    confirm POST carries no `open` and takes :675 instead. Driving this as a
    no-JS delete would go green on the six-site edit alone while :674 kept
    dropping q for every JS author."""
    client, course, part, chap, hit, miss = filtered_course
    delete = reverse("courses:manage_node_delete", kwargs={"slug": course.slug})
    resp = client.post(
        delete,
        {
            "node": miss.pk,
            "token": miss.updated.isoformat(),
            "open": str(chap.pk),
            "q": "trygo",
        },
    )
    assert resp.status_code == 302
    assert "q=trygo" in resp["Location"]


def test_the_no_js_move_picker_round_trip_stays_filtered(filtered_course):
    client, course, part, chap, hit, miss = filtered_course
    picker = reverse("courses:manage_node_move", kwargs={"slug": course.slug})
    body = client.get(picker, {"node": hit.pk, "q": "trygo"}).content.decode()
    # Sliced to the picker form itself, matching every sibling row in this
    # file -- a bare whole-body assertion does not tie `name="q"` and
    # `value="trygo"` to the same element.
    assert 'class="move-picker"' in body, "the picker form did not render"
    frag = body.split('class="move-picker"', 1)[1].split("</form>", 1)[0]
    assert 'name="q"' in frag
    assert 'value="trygo"' in frag


def test_every_tree_form_carries_a_hidden_q(filtered_course):
    """Step 4's edit is the most-repeated one in this task and the whole no-JS
    story rests on it, yet nothing else can observe it: every other row POSTs
    `q` in the payload BY HAND, so all four forms could ship without the input
    and the suite would stay green while a no-JS author loses the filter on
    every rename, add, reorder and duplicate.

    Asserted per FORM, not once over the body -- a single hidden input
    anywhere would otherwise satisfy all of them.

    A row is ONE form now (rename + reorder + duplicate share it via
    `formaction`), so its single hidden `q` covers three of the four ops -- but
    only while those buttons really are inside it. That containment is asserted
    here too: move a button out of the rowhead form and it silently loses `q`
    for no-JS authors, which no other test would notice.
    """
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "trygo", "open": "all"}).content.decode()
    forms = {
        "rowhead": 'class="tree__rowhead"',
        "add": 'class="tree__add"',
    }
    for label, marker in forms.items():
        assert marker in body, f"{label}: form absent; the row proves nothing"
        frag = body.split(marker, 1)[1].split("</form>", 1)[0]
        assert 'name="q"' in frag and 'value="trygo"' in frag, label

    # The ops that no longer own a form must sit INSIDE the rowhead form.
    # Anchored on a UNIT's row: `duplicate` renders only for units, so taking the
    # first rowhead in the document would test a part and pass on its absence.
    unit_row = body.split(f'data-node="{hit.pk}"', 1)[1]
    rowhead = unit_row.split('class="tree__rowhead"', 1)[1].split("</form>", 1)[0]
    for op in ("reorder", "duplicate"):
        assert f'data-op="{op}"' in rowhead, (
            f"{op} button is outside the rowhead form -- it would post without q"
        )
    assert 'name="title"' in rowhead, "rename input is outside the rowhead form"


def test_the_delete_confirm_round_trip_stays_filtered(filtered_course):
    """The GET nothing else reaches. Both other delete rows POST straight to
    manage_node_delete, so `node_confirm_delete.html`'s hidden input, its
    Cancel href and node_delete's GET context key are all unguarded -- and if
    the context key is forgotten, `{{ q }}` renders empty, the {% if q %}
    input disappears, and the confirm POST silently drops the filter.
    """
    client, course, part, chap, hit, miss = filtered_course
    confirm = reverse("courses:manage_node_delete", kwargs={"slug": course.slug})
    body = client.get(confirm, {"node": miss.pk, "q": "trygo"}).content.decode()

    # 1. the hidden input the confirm POST will carry.
    #    Anchor on the form's OWN action, never on the first `<form` in the
    #    document: node_confirm_delete.html extends base.html, which emits
    #    `<form class="lang-switch">` at :60 -- ~90 lines before
    #    `{% block content %}` at :152 -- so a naive split returns the
    #    language switcher and both assertions fail on a CORRECT
    #    implementation.
    form = body.split(f'action="{confirm}"', 1)[1].split("</form>", 1)[0]
    assert 'name="token"' in form, "sliced the wrong form; re-derive the anchor"
    assert 'name="q"' in form and 'value="trygo"' in form

    # 2. the Cancel href. No `open` in the GET, so the template takes its
    #    `{% else %}?open=session{% endif %}` arm and `q` appends with `&`.
    assert "?open=session&amp;q=trygo" in body

    # 3. the POST that form makes -- the filter must survive the redirect
    resp = client.post(
        confirm, {"node": miss.pk, "token": miss.updated.isoformat(), "q": "trygo"}
    )
    assert resp.status_code == 302
    assert "q=trygo" in resp["Location"]


def test_the_delete_confirm_cancel_href_percent_encodes_q(filtered_course):
    """Companion to test_the_delete_confirm_round_trip_stays_filtered's Cancel
    href assertion, which uses `q="trygo"` -- an encoding-invariant value, so
    `"?open=session&amp;q=trygo" in body` is byte-identical whether
    node_confirm_delete.html:19 uses `{{ q|urlencode }}` or a bare `{{ q }}`.
    That row leaves the Cancel href's encoding entirely untested.

    Here `q` contains `&` and a space, and the assertion is made ON THE
    SLICED HREF, never on the whole body -- same idiom as
    test_markup_hrefs_percent_encode_q's delete-href row.
    """
    client, course, part, chap, hit, miss = filtered_course
    confirm = reverse("courses:manage_node_delete", kwargs={"slug": course.slug})
    body = client.get(confirm, {"node": miss.pk, "q": "metria & wek"}).content.decode()
    assert 'class="btn btn--ghost"' in body, "no Cancel link rendered"
    # class comes before href in this anchor's attribute order -- slice from
    # the class marker to the tag's own closing `>`.
    cancel_frag = body.split('class="btn btn--ghost"', 1)[1].split(">", 1)[0]
    assert "href=" in cancel_frag, "sliced past the anchor -- re-derive"
    cancel_href = cancel_frag.split('href="', 1)[1].rsplit('"', 1)[0]
    assert "q=metria%20%26%20wek" in cancel_href or "q=metria+%26+wek" in cancel_href


def test_an_empty_filtered_scope_says_no_matching_titles(filtered_course):
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    filtered = client.get(url, {"q": "rozdzial"}).content.decode()
    assert "No matching titles." in filtered or "Brak pasuj" in filtered
    plain = client.get(url, {"open": "all"}).content.decode()
    assert "No children yet." in plain or "Nie ma jeszcze" in plain


def test_a_no_js_unit_add_under_a_filter_shows_the_new_row(filtered_course):
    """The unit kind is load-bearing: a container would survive a
    `& container_pks(...)` intersection and hide the trap."""
    client, course, part, chap, hit, miss = filtered_course
    add = reverse("courses:manage_node_add", kwargs={"slug": course.slug})
    resp = client.post(
        add,
        {
            "parent": chap.pk,
            "parent_token": chap.updated.isoformat(),
            "kind": "unit",
            "unit_type": "lesson",
            "title": "Zupelnie inny tytul",
            "q": "trygo",
        },
    )
    assert resp.status_code == 302
    body = client.get(resp["Location"]).content.decode()
    assert "Zupelnie inny tytul" in body


def test_builder_force_is_consumed_exactly_once(filtered_course):
    """The clear is the half with no visible symptom when it is missing: an
    uncleared stash passes every other row while pinning a stale pk into
    every filtered render for that slug."""
    client, course, part, chap, hit, miss = filtered_course
    add = reverse("courses:manage_node_add", kwargs={"slug": course.slug})
    resp = client.post(
        add,
        {
            "parent": chap.pk,
            "parent_token": chap.updated.isoformat(),
            "kind": "unit",
            "unit_type": "lesson",
            "title": "Zupelnie inny tytul",
            "q": "trygo",
        },
    )
    client.get(resp["Location"])
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    second = client.get(url, {"q": "trygo"}).content.decode()
    assert "Zupelnie inny tytul" not in second


def test_an_add_into_an_EMPTY_filtered_scope_does_not_500(filtered_course):
    """The destination has NO key in the restricted map: _children_map only
    creates keys for parents that HAVE children, and spec 1d ships an add
    affordance into exactly this scope."""
    client, course, part, chap, hit, miss = filtered_course
    add = reverse("courses:manage_node_add", kwargs={"slug": course.slug})
    resp = client.post(
        add,
        {
            "parent": chap.pk,
            "parent_token": chap.updated.isoformat(),
            "kind": "unit",
            "unit_type": "lesson",
            "title": "Nowa lekcja",
            "q": "rozdzial",  # matches the CHAPTER; no descendant matches
        },
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    assert resp.status_code == 200
    assert "Nowa lekcja" in resp.content.decode()


def test_a_no_js_reparent_into_a_NON_MATCHING_destination_shows_the_node(
    filtered_course,
):
    """The row that actually proves the stash carried a CHAIN. An add form
    can only be submitted from a scope that is already visible, so its parent
    is a match or a walked ancestor either way and a bare-pk stash would pass
    that row. The Move picker is the one no-JS surface offering a destination
    the filter excludes."""
    client, course, part, chap, hit, miss = filtered_course
    other = ContentNodeFactory(
        course=course,
        kind="chapter",
        unit_type=None,
        parent=part,
        title="Zupelnie inny",
    )
    move = reverse("courses:manage_node_move", kwargs={"slug": course.slug})
    resp = client.post(
        move,
        {
            "mode": "reparent",
            # `miss`, NOT `hit`: moving a node that still matches the query
            # makes the row vacuous -- filtered_map would select it on its own
            # and walk `other` -> `part` into the chains unaided, so both
            # assertions pass with _stash_builder_force deleted entirely.
            "node": miss.pk,
            "new_parent": other.pk,
            "position": 0,
            "node_token": miss.updated.isoformat(),
            "q": "trygo",
        },
    )
    assert resp.status_code == 302
    body = client.get(resp["Location"]).content.decode()
    assert f'data-node="{miss.pk}"' in body
    assert f'data-node="{other.pk}"' in body  # the CHAIN, not just the pk


def test_a_forced_row_does_not_move_shown_or_total(filtered_course):
    """The rule is invisible in the markup and would otherwise rot: if a
    forced pk counted, the X-Builder-Info notice would stop matching the cap
    it describes."""
    client, course, part, chap, hit, miss = filtered_course
    add = reverse("courses:manage_node_add", kwargs={"slug": course.slug})
    resp = client.post(
        add,
        {
            "parent": chap.pk,
            "parent_token": chap.updated.isoformat(),
            "kind": "unit",
            "unit_type": "lesson",
            "title": "Zupelnie inny tytul",
            "q": "trygo",
        },
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    assert "Zupelnie inny tytul" in resp.content.decode()
    assert resp["X-Builder-Info"] == "filter;shown=1;total=1"


def test_force_inclusion_is_idempotent(filtered_course):
    """A duplicate <li data-node=X> makes the DOM collector double-count and
    dragover's :scope > queries pick an arbitrary one."""
    client, course, part, chap, hit, miss = filtered_course
    add = reverse("courses:manage_node_add", kwargs={"slug": course.slug})
    resp = client.post(
        add,
        {
            "parent": chap.pk,
            "parent_token": chap.updated.isoformat(),
            "kind": "unit",
            "unit_type": "lesson",
            "title": "Trygonometria druga",  # ALSO matches q
            "q": "trygo",
        },
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    # _tree_node.html:26-27 emits the title TWICE per row -- `value="..."` and
    # `title="..."` on the same input -- so a correct, non-duplicated row
    # yields 2. Count a per-row-unique token instead.
    new_pk = ContentNode.objects.get(title="Trygonometria druga").pk
    assert resp.content.decode().count(f'data-node="{new_pk}"') == 1


def test_the_arrows_and_the_grip_render_disabled_under_a_filter(filtered_course):
    """Both halves. Dropping `draggable` alone leaves .ica--grip's
    `cursor: grab` and `:active { cursor: grabbing }` intact, so the row still
    looks draggable -- the lying affordance this rule exists to remove.

    A SECOND MATCHING SIBLING is mandatory. _move_buttons.html already renders
    both arrows disabled on `is_first`/`is_last` alone, and under `q=trygo` the
    shared fixture gives `chap` exactly ONE surviving child -- so `hit` would
    be both first and last, both arrows would be disabled without the
    `or filtered` edit, and deleting that edit could not turn this row red.
    With two matches, `hit` is first-but-not-last, so the DOWN arrow is
    disabled only by `or filtered`.

    Added here rather than in the fixture: shown/total are asserted as 1/1 by
    test_counts_under_a_filter_are_the_filtered_counts and by
    test_a_forced_row_does_not_move_shown_or_total, and a second permanent
    match would redden both.
    """
    client, course, part, chap, hit, miss = filtered_course
    ContentNodeFactory(
        course=course, kind="unit", parent=chap, title="Trygonometria II"
    )
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    filtered = client.get(url, {"q": "trygo"}).content.decode()
    row = filtered.split(f'data-node="{hit.pk}"')[1].split("</li>")[0]
    assert "disabled" in row.split('value="down"')[1].split(">")[0], (
        "the DOWN arrow is the one only `or filtered` can disable here"
    )
    assert row.count("disabled") >= 3  # up, down, grip
    assert 'draggable="true"' not in row

    plain = client.get(url, {"open": "all"}).content.decode()
    prow = plain.split(f'data-node="{hit.pk}"')[1].split("</li>")[0]
    assert 'draggable="true"' in prow


def test_a_reorder_under_an_active_filter_is_refused_on_both_branches(filtered_course):
    """The form is trivially replayable, so the markup alone is not a guard."""
    client, course, part, chap, hit, miss = filtered_course
    move = reverse("courses:manage_node_move", kwargs={"slug": course.slug})
    before = list(
        type(hit)
        .objects.filter(parent=chap)
        .order_by("order", "pk")
        .values_list("pk", flat=True)
    )

    frag = client.post(
        move,
        {
            "mode": "reorder",
            "node": hit.pk,
            "direction": "down",
            "token": hit.updated.isoformat(),
            "q": "trygo",
        },
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    assert frag.status_code == 422
    assert "op-error" in frag.content.decode()

    page = client.post(
        move,
        {
            "mode": "reorder",
            "node": hit.pk,
            "direction": "down",
            "token": hit.updated.isoformat(),
            "q": "trygo",
        },
    )
    assert page.status_code == 422
    assert "builder__tree" in page.content.decode()  # a full page, not a bare fragment

    after = list(
        type(hit)
        .objects.filter(parent=chap)
        .order_by("order", "pk")
        .values_list("pk", flat=True)
    )
    assert before == after


def test_a_reorder_under_a_BELOW_FLOOR_q_still_succeeds(filtered_course):
    """The refusal row above passes under a truthiness gate
    (request.POST.get("q")) or a presence gate, both of which wrongly refuse
    here -- while the arrows render ENABLED, because `filtered` is False."""
    client, course, part, chap, hit, miss = filtered_course
    move = reverse("courses:manage_node_move", kwargs={"slug": course.slug})
    resp = client.post(
        move,
        {
            "mode": "reorder",
            "node": hit.pk,
            "direction": "down",
            "token": hit.updated.isoformat(),
            "q": "a",
        },
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    assert resp.status_code == 200


def test_a_positioned_REPARENT_under_a_filter_still_succeeds(filtered_course):
    """A drop and the Move picker post the same mode=reparent shape and are
    indistinguishable server-side, so a guard widened to "any positioned move"
    would break the one route spec 3m designates for moving while filtered."""
    client, course, part, chap, hit, miss = filtered_course
    move = reverse("courses:manage_node_move", kwargs={"slug": course.slug})
    resp = client.post(
        move,
        {
            "mode": "reparent",
            "node": hit.pk,
            "new_parent": part.pk,
            "position": 0,
            "node_token": hit.updated.isoformat(),
            "q": "trygo",
        },
        **{"HTTP_X_REQUESTED_WITH": "fetch"},
    )
    assert resp.status_code == 200
    hit.refresh_from_db()
    assert hit.parent_id == part.pk


def test_the_clear_anchor_is_always_in_the_dom_and_hidden_when_blank(filtered_course):
    """`{% if q %}` puts NOTHING in the DOM on an unfiltered page, so the JS
    rule has no element to show -- and `clear.hidden = !box.value` on a null
    querySelector throws inside the input handler on the most common entry
    point there is, killing filtering before the debounce is scheduled."""
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    blank = client.get(url).content.decode()
    assert "data-filter-clear" in blank
    tag = blank.split("data-filter-clear")[1].split(">")[0]
    assert "hidden" in tag

    filtered = client.get(url, {"q": "trygo"}).content.decode()
    tag2 = filtered.split("data-filter-clear")[1].split(">")[0]
    assert "hidden" not in tag2


def test_the_filter_input_has_an_accessible_name(filtered_course):
    """ "Filter" labels the BUTTON, not the field."""
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url).content.decode()
    assert 'id="builder-q"' in body
    assert 'for="builder-q"' in body


def test_expand_all_loses_its_href_over_the_ceiling(filtered_course, monkeypatch):
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})

    monkeypatch.setattr("courses.builder_open.CEILING", 0)
    over = client.get(url).content.decode()
    # Split on the ANCHOR's hook (with its trailing newline), never on the bare
    # string: `.builder` carries `data-expand-all-disabled` earlier in the
    # document and "data-expand-all" is a prefix of it, so a bare split lands
    # inside the <section> tag and every assertion below reads the wrong slice.
    tag = over.split("data-expand-all\n")[1].split(">")[0]
    assert "href" not in tag
    assert 'aria-disabled="true"' in tag
    assert "data-expand-all-disabled" in over

    monkeypatch.setattr("courses.builder_open.CEILING", 500)
    under = client.get(url).content.decode()
    assert "href" in under.split("data-expand-all\n")[1].split(">")[0]
    assert "data-expand-all-disabled" not in under


def test_both_bulk_controls_stay_ENABLED_under_an_active_filter(filtered_course):
    """Spec 6z. The tempting rule -- disable them while filtering, since a
    filtered tree is already fully open -- is FALSE once step 2 wins: after
    any toggle under a filter the resolved set is not the chains and filtered
    containers genuinely are collapsed."""
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    body = client.get(url, {"q": "trygo"}).content.decode()
    for hook in ("data-expand-all\n", "data-collapse-all\n"):
        # Split FORWARD from the hook: the href follows it in the markup, so
        # slicing backwards to the last `<a` yields only the class attribute.
        # And the hook needs its trailing newline -- `.builder` carries
        # `data-expand-all-disabled`, of which "data-expand-all" is a PREFIX,
        # and that attribute appears earlier in the document.
        tag = body.split(hook)[1].split(">")[0]
        assert "aria-disabled" not in tag
        assert "href" in tag


def test_expand_all_under_a_filter_returns_only_filtered_rows(filtered_course):
    """open=all + q renders the RESTRICTED map -- ~226 rows on mat-pp, not
    944 -- which is why 6z keeps the control enabled rather than disabling it
    on a cost argument that does not hold."""
    client, course, part, chap, hit, miss = filtered_course
    url = reverse("courses:manage_tree", kwargs={"slug": course.slug})
    body = client.get(url, {"open": "all", "q": "trygo"}).content.decode()
    assert f'data-node="{hit.pk}"' in body
    assert f'data-node="{miss.pk}"' not in body


def test_both_bulk_hrefs_carry_q(filtered_course):
    """BOTH, as the name says. Asserting only expand-all leaves the collapse
    anchor's `q` clause unguarded: no other row can catch its removal --
    test_both_bulk_controls_stay_ENABLED checks only href/aria-disabled,
    Task 13's over-ceiling row reads the collapse href AFTER rewriteBulkHrefs
    has re-added `q` client-side, and the below-floor row asserts `q=` is
    ABSENT. A no-JS author's Collapse all would silently drop the filter.
    """
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    for query in ("trygo", "a"):  # active AND present-but-inactive
        body = client.get(url, {"q": query}).content.decode()
        for hook in ("data-expand-all\n", "data-collapse-all\n"):
            tag = body.split(hook)[1].split(">")[0]
            assert f"q={query}" in tag, (hook, query)


def test_both_notice_routes_agree_in_polish(filtered_course):
    """The page route (the server-rendered notice) and the fragment route
    (the data-msg-filter attribute, read by JS on subsequent AJAX updates)
    render the SAME literal -- but it does NOT collapse to one catalog
    entry: Django's {% trans %} looks up a "%"-doubled msgid at runtime,
    while the Python _() call behind the server-rendered notice looks up
    the single-% form, so the literal necessarily occupies two msgids that
    must be kept in sync by hand. This test does not assert there is only
    one msgid -- there are two -- it pins the property that actually
    matters: both routes still agree once translated into Polish, so an
    author can trust the tree's data-msg-filter attribute is telling them
    the same thing the notice banner just said.

    They are not directly comparable -- the server interpolates while the
    attribute keeps its placeholders -- so a literal equality assertion fails
    on a CORRECT implementation. Substitute, then compare.
    """
    client, course, *_ = filtered_course
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    # The login signal has already pinned session["_language"] to "en", so
    # Accept-Language is never consulted. Without this seed the row still
    # passes, but vacuously: it would compare an English template against an
    # English render and could not detect the two literals drifting apart.
    session = client.session
    session["_language"] = "pl"
    session.save()
    body = client.get(url, {"q": "trygo"}, HTTP_ACCEPT_LANGUAGE="pl").content.decode()
    assert "Filtrowane" in body, "the Polish catalog is not active; the row is vacuous"
    template = body.split('data-msg-filter="')[1].split('"')[0]
    rendered = body.split('data-info-key="filter">')[1].split("<")[0]
    assert template % {"shown": 1, "total": 1} == rendered
