import re
from urllib.parse import urlencode

import pytest
from django.urls import reverse
from django.utils.dateparse import parse_datetime

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import make_login
from tests.factories import make_quiz_unit

# manage_node_flag distinguishes the JS/fragment path (200 + top-scope fragment) from
# the no-JS path (302 redirect on success, full builder/interstitial page on error or
# unconfirmed) via the `X-Requested-With: fetch` header -- same convention as every
# other node-op endpoint (see tests/test_manage_node_ops.py).
FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


def _setup(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    return owner, course


def _tok(node):
    return node.updated.isoformat()


def _url(course):
    return reverse("courses:manage_node_flag", kwargs={"slug": course.slug})


@pytest.mark.django_db
def test_wr1_student_and_group_teacher_are_rejected(client):
    """WR1. A student and an assigned group teacher are both rejected, on both the
    GET strip and the POST, with no write. Mutant: omit _require_manage."""
    _, course = _setup(client)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=True
    )
    url = _url(course)
    payload = {
        "node": unit.pk,
        "flag": "published",
        "value": "0",
        "scope": "node",
        "token": _tok(unit),
    }

    client.logout()
    make_login(client, "student")
    assert client.get(url, payload).status_code == 403
    assert client.post(url, payload, **FETCH).status_code == 403

    client.logout()
    teacher = make_login(client, "teacher")
    GroupFactory(course=course).teachers.add(teacher)
    assert client.get(url, payload).status_code == 403
    assert client.post(url, payload, **FETCH).status_code == 403

    unit.refresh_from_db()
    assert unit.published is True


@pytest.mark.django_db
def test_wr1b_anonymous_request_gets_login_redirect_not_403(client):
    """WR1b. Mutant: omit @login_required -> _require_manage's PermissionDenied
    403s where every neighbouring management view redirects."""
    _, course = _setup(client)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=True
    )
    url = _url(course)
    client.logout()

    resp = client.get(
        url,
        {
            "node": unit.pk,
            "flag": "published",
            "value": "0",
            "scope": "node",
            "token": _tok(unit),
        },
    )
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_wr2_bulk_publish_bumps_updated_on_every_descendant(client):
    """WR2. Highest-value test in the file: dropping updated=timezone.now() from
    the .update() is invisible until the NEXT edit to an affected row conflicts."""
    _, course = _setup(client)
    chapter = ContentNodeFactory(course=course, kind="chapter", title="Ch")
    u1 = ContentNodeFactory(
        course=course, parent=chapter, kind="unit", unit_type="lesson", published=False
    )
    u2 = ContentNodeFactory(
        course=course, parent=chapter, kind="unit", unit_type="lesson", published=False
    )
    old1, old2 = u1.updated, u2.updated

    resp = client.post(
        _url(course),
        {
            "node": chapter.pk,
            "flag": "published",
            "value": "1",
            "scope": "subtree",
            "token": _tok(chapter),
            "confirmed": "1",
        },
        **FETCH,
    )
    assert resp.status_code == 200

    u1.refresh_from_db()
    u2.refresh_from_db()
    assert u1.published is True
    assert u2.published is True
    assert u1.updated > old1
    assert u2.updated > old2


@pytest.mark.django_db
def test_wr3_stale_token_on_subtree_toggle_returns_409_and_writes_nothing(client):
    """WR3."""
    _, course = _setup(client)
    chapter = ContentNodeFactory(course=course, kind="chapter")
    unit = ContentNodeFactory(
        course=course, parent=chapter, kind="unit", unit_type="lesson", published=False
    )

    resp = client.post(
        _url(course),
        {
            "node": chapter.pk,
            "flag": "published",
            "value": "1",
            "scope": "subtree",
            "token": "2000-01-01T00:00:00+00:00",
            "confirmed": "1",
        },
        **FETCH,
    )
    assert resp.status_code == 409

    unit.refresh_from_db()
    assert unit.published is False


@pytest.mark.django_db
def test_wr4_flag_outside_allow_list_is_rejected(client):
    """WR4. flag outside the two-name allow-list is rejected before any write."""
    _, course = _setup(client)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=False
    )

    resp = client.post(
        _url(course),
        {
            "node": unit.pk,
            "flag": "title",
            "value": "1",
            "scope": "node",
            "token": _tok(unit),
        },
        **FETCH,
    )
    assert resp.status_code == 422

    unit.refresh_from_db()
    assert unit.published is False


@pytest.mark.django_db
def test_wr5_subtree_toggle_does_not_touch_sibling_chapter(client):
    """WR5. Mutant: build unit_pks from course.nodes.filter(kind="unit") instead of
    from _subtree_node_ids() -> the whole course flips on one click."""
    _, course = _setup(client)
    chapter_a = ContentNodeFactory(course=course, kind="chapter", title="A")
    chapter_b = ContentNodeFactory(course=course, kind="chapter", title="B")
    a1 = ContentNodeFactory(
        course=course,
        parent=chapter_a,
        kind="unit",
        unit_type="lesson",
        published=False,
    )
    b1 = ContentNodeFactory(
        course=course,
        parent=chapter_b,
        kind="unit",
        unit_type="lesson",
        published=False,
    )
    b1_updated = b1.updated

    resp = client.post(
        _url(course),
        {
            "node": chapter_a.pk,
            "flag": "published",
            "value": "1",
            "scope": "subtree",
            "token": _tok(chapter_a),
            "confirmed": "1",
        },
        **FETCH,
    )
    assert resp.status_code == 200

    a1.refresh_from_db()
    b1.refresh_from_db()
    assert a1.published is True
    assert b1.published is False
    assert b1.updated == b1_updated


@pytest.mark.django_db
def test_wr7_success_fragment_carries_top_scope_for_unit_and_subtree(client):
    """WR7. Assert the attribute, not just a 200 -- a wrong-shaped 200 is invisible
    to a status-code assertion alone."""
    _, course = _setup(client)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=False
    )

    resp = client.post(
        _url(course),
        {
            "node": unit.pk,
            "flag": "published",
            "value": "1",
            "scope": "node",
            "token": _tok(unit),
        },
        **FETCH,
    )
    assert resp.status_code == 200
    assert 'data-scope="top"' in resp.content.decode()

    chapter = ContentNodeFactory(course=course, kind="chapter")
    ContentNodeFactory(
        course=course, parent=chapter, kind="unit", unit_type="lesson", published=False
    )
    resp2 = client.post(
        _url(course),
        {
            "node": chapter.pk,
            "flag": "published",
            "value": "1",
            "scope": "subtree",
            "token": _tok(chapter),
            "confirmed": "1",
        },
        **FETCH,
    )
    assert resp2.status_code == 200
    assert 'data-scope="top"' in resp2.content.decode()


@pytest.mark.django_db
def test_wr8_fragment_carries_post_write_token_for_a_second_edit(client):
    """WR8. A SUBTREE write, and a second edit to a DESCENDANT (not the acted-on
    node itself) -- per the brief. Read data-updated out of the returned
    fragment for that descendant, assert it is strictly greater than the
    pre-write value, and re-post it as token on a second edit to the same
    descendant; assert that succeeds rather than 409ing.

    Mutant: omit updated=now from the bulk .update(). The row's DB `updated`
    is then left unbumped too, so a round-trip-only assertion (token
    accepted, 200) stays green: _render_scope reads back exactly the stale
    value it just wrote into the fragment, and the follow-up token still
    matches it. The strictly-greater-than-old assertion is what actually
    dies under that mutant.
    """
    _, course = _setup(client)
    chapter = ContentNodeFactory(course=course, kind="chapter")
    descendant = ContentNodeFactory(
        course=course, parent=chapter, kind="unit", unit_type="lesson", published=False
    )
    old_updated = descendant.updated

    resp = client.post(
        _url(course),
        {
            "node": chapter.pk,
            "flag": "published",
            "value": "1",
            "scope": "subtree",
            "token": _tok(chapter),
            "confirmed": "1",
            "open": str(
                chapter.pk
            ),  # keep the chapter's scope expanded in the fragment
        },
        **FETCH,
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    m = re.search(rf'id="node-{descendant.pk}"[^>]*data-updated="([^"]+)"', html)
    assert m, html
    fresh_token = m.group(1)
    assert parse_datetime(fresh_token) > old_updated

    resp2 = client.post(
        _url(course),
        {
            "node": descendant.pk,
            "flag": "obligatory",
            "value": "0",
            "scope": "node",
            "token": fresh_token,
        },
        **FETCH,
    )
    assert resp2.status_code == 200

    descendant.refresh_from_db()
    assert descendant.updated > old_updated


@pytest.mark.django_db
def test_wr9_no_js_post_shape_redirects_on_success(client):
    """WR9. Parameters as hidden inputs in request.POST, not a formaction query
    string. Mutant: read from request.GET only -> the interstitial silently 422s."""
    _, course = _setup(client)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=False
    )

    resp = client.post(
        _url(course),
        {
            "node": unit.pk,
            "flag": "published",
            "value": "1",
            "scope": "node",
            "token": _tok(unit),
        },
    )  # no FETCH header -- the no-JS path
    assert resp.status_code == 302

    unit.refresh_from_db()
    assert unit.published is True


@pytest.mark.django_db
def test_wr11_value_scope_and_confirmed_are_allow_listed(client):
    """WR11. Mutant: coerce value with bool() and default scope to "node" ->
    value="false" writes True and a typo'd scope silently narrows the action."""
    _, course = _setup(client)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=False
    )
    url = _url(course)
    base = {"node": unit.pk, "flag": "published", "token": _tok(unit)}

    cases = [
        {**base, "value": "true", "scope": "node"},
        {**base, "value": "", "scope": "node"},
        {**base, "value": "1"},  # missing scope
        {**base, "value": "1", "scope": "everything"},
        {**base, "value": "1", "scope": "node", "confirmed": "yes"},
    ]
    for payload in cases:
        resp = client.post(url, payload, **FETCH)
        assert resp.status_code == 422, payload

    unit.refresh_from_db()
    assert unit.published is False


@pytest.mark.django_db
def test_wr12_container_own_updated_bumped_by_subtree_write(client):
    """WR12. The container's own updated is bumped by a subtree write, even
    though the container's OWN flag column is untouched.

    The request writes flag=obligatory, so the column that must stay
    untouched on the container is `obligatory` -- not `published`, which no
    in-scope mutant can flip. (ContentNode.obligatory defaults to True.)
    """
    _, course = _setup(client)
    chapter = ContentNodeFactory(course=course, kind="chapter")
    ContentNodeFactory(
        course=course,
        parent=chapter,
        kind="unit",
        unit_type="lesson",
        obligatory=True,
    )
    old_chapter_updated = chapter.updated
    chapter_obligatory_before = chapter.obligatory

    resp = client.post(
        _url(course),
        {
            "node": chapter.pk,
            "flag": "obligatory",
            "value": "0",
            "scope": "subtree",
            "token": _tok(chapter),
            "confirmed": "1",
        },
        **FETCH,
    )
    assert resp.status_code == 200

    chapter.refresh_from_db()
    assert chapter.updated > old_chapter_updated
    assert chapter.obligatory == chapter_obligatory_before


@pytest.mark.django_db
def test_wr13_unconfirmed_post_does_not_write_and_returns_the_strip(client):
    """WR13. Drive it with a hand-rolled POST, not through the UI. Mutant: let the
    template's element choice be the only guard -> a direct POST unpublishes a
    quiz with no confirmation, and every UI-driven test stays green."""
    _, course = _setup(client)
    quiz = make_quiz_unit(course=course, published=True)
    QuizSubmissionFactory(unit=quiz)

    resp = client.post(
        _url(course),
        {
            "node": quiz.pk,
            "flag": "published",
            "value": "0",
            "scope": "node",
            "token": _tok(quiz),
        },
    )  # no confirmed=1, no fetch header -> the full-page interstitial
    assert resp.status_code == 200
    assert any(
        t.name == "courses/manage/node_confirm_flag.html" for t in resp.templates
    )

    quiz.refresh_from_db()
    assert quiz.published is True


@pytest.mark.django_db
def test_wr14_obligatory_subtree_write_touches_lesson_units_only(client):
    """WR14. Mutant A: restrict to kind="unit" alone -> the quiz's inert flag is
    stamped. Mutant B: fork on flag and omit updated from the obligatory arm."""
    _, course = _setup(client)
    chapter = ContentNodeFactory(course=course, kind="chapter")
    lesson = ContentNodeFactory(
        course=course, parent=chapter, kind="unit", unit_type="lesson", obligatory=True
    )
    quiz = make_quiz_unit(course=course, parent=chapter, obligatory=True)
    old_lesson_updated = lesson.updated
    old_quiz_updated = quiz.updated

    resp = client.post(
        _url(course),
        {
            "node": chapter.pk,
            "flag": "obligatory",
            "value": "0",
            "scope": "subtree",
            "token": _tok(chapter),
            "confirmed": "1",
        },
        **FETCH,
    )
    assert resp.status_code == 200

    lesson.refresh_from_db()
    quiz.refresh_from_db()
    assert lesson.obligatory is False
    assert lesson.updated > old_lesson_updated
    assert quiz.obligatory is True
    assert quiz.updated == old_quiz_updated


@pytest.mark.django_db
def test_wr16_scope_must_agree_with_node_kind(client):
    """WR16. scope=node on a container and scope=subtree on a unit both 422, no
    write. The critical half is scope=subtree on a UNIT: needs_confirmation starts
    with scope=="subtree", so if the view computed it before this check, the
    request would short-circuit to the confirm strip (200) instead of 422ing."""
    _, course = _setup(client)
    chapter = ContentNodeFactory(course=course, kind="chapter")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=False
    )
    url = _url(course)

    resp1 = client.post(
        url,
        {
            "node": chapter.pk,
            "flag": "published",
            "value": "1",
            "scope": "node",
            "token": _tok(chapter),
        },
        **FETCH,
    )
    assert resp1.status_code == 422

    resp2 = client.post(
        url,
        {
            "node": unit.pk,
            "flag": "published",
            "value": "1",
            "scope": "subtree",
            "token": _tok(unit),
        },
        **FETCH,
    )
    assert resp2.status_code == 422

    unit.refresh_from_db()
    assert unit.published is False


@pytest.mark.django_db
def test_wr18_confirmed_write_under_a_filter_stays_filtered(client):
    """WR18. Mutant: omit q from the success _redirect_to_builder call ->
    _raw_q finds nothing and the CA's filter is silently cleared. Fixture: the
    confirming QUIZ anchor -- container anchors are inert under a filter."""
    _, course = _setup(client)
    quiz = make_quiz_unit(course=course, title="Algebra Quiz", published=True)
    QuizSubmissionFactory(unit=quiz)

    resp = client.post(
        _url(course),
        {
            "node": quiz.pk,
            "flag": "published",
            "value": "0",
            "scope": "node",
            "token": _tok(quiz),
            "confirmed": "1",
            "q": "Algebra",
        },
    )  # no fetch header -- the no-JS redirect path
    assert resp.status_code == 302
    assert "q=Algebra" in resp["Location"]

    quiz.refresh_from_db()
    assert quiz.published is False


@pytest.mark.django_db
def test_critical1_a_non_post_non_get_request_does_not_write(client):
    """CRITICAL 1 (fix round 1). Django's CsrfViewMiddleware exempts
    GET/HEAD/OPTIONS/TRACE, and HEAD is CORS-safelisted -- so a check phrased
    as `request.method == "GET"` lets a credentialed cross-origin HEAD (or a
    PUT/DELETE) fall through the strip branch entirely and reach
    set_node_flag without ever satisfying CSRF. The endpoint's stated premise
    is that the server, not the markup, is the guard; that must hold for
    every method, not just the two the UI happens to use."""
    _, course = _setup(client)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=False
    )
    payload = {
        "node": unit.pk,
        "flag": "published",
        "value": "1",
        "scope": "node",
        "token": _tok(unit),
    }

    resp = client.head(_url(course), payload)
    assert resp.status_code == 200
    unit.refresh_from_db()
    assert unit.published is False

    # PUT with the same shape as a `formaction` query string -- Django never
    # populates request.POST for a non-POST method, so the params ride the URL's
    # query string exactly as the JS toggle's formaction does.
    #
    # urlencode, NOT "&".join(f"{k}={v}"): the token is an aware UTC isoformat
    # ending in "+00:00", and a raw "+" in a query string is decoded by
    # QueryDict as a SPACE. The view would then see "...123456 00:00",
    # parse_datetime returns None, _check_token raises ConflictError and the
    # request 409s BEFORE reaching the write -- so `unit.published is False`
    # below would stay green on the very mutant it exists to kill
    # (`request.method == "GET"`), for the wrong reason. Encoded, the token
    # arrives intact and only the method guard stands between this request and
    # set_node_flag. Falsified by hand: with the guard mutated to `== "GET"`,
    # the `published is False` assertion goes RED, not just the status one.
    resp2 = client.put(f"{_url(course)}?{urlencode(payload)}")
    assert resp2.status_code == 200
    unit.refresh_from_db()
    assert unit.published is False


@pytest.mark.django_db
def test_ctx_editor_with_a_container_falls_back_to_the_builder_arm(client):
    """The `is_unit` conjunct in _flag_error: _editor_page and _unit_url are
    unit-only surfaces, but ctx=editor can arrive attached to a container
    node (e.g. a stray ctx carried by a container's rowhead). A 422 in that
    combination must fall through to the builder page, not attempt
    _editor_page on a non-unit and 404/error there."""
    _, course = _setup(client)
    chapter = ContentNodeFactory(course=course, kind="chapter")

    resp = client.post(
        _url(course),
        {
            "node": chapter.pk,
            "flag": "title",  # outside the allow-list -> 422
            "value": "1",
            "scope": "subtree",
            "token": _tok(chapter),
            "ctx": "editor",
        },
    )  # no fetch header -> the builder (non-fragment) arm
    assert resp.status_code == 422
    assert any(t.name == "courses/manage/builder.html" for t in resp.templates)
    assert not any(
        t.name == "courses/manage/editor/editor.html" for t in resp.templates
    )


@pytest.mark.django_db
def test_get_renders_the_strip_and_never_writes(client):
    """No test previously drove the GET path: every existing GET test returns
    early on 403/redirect before reaching _flag_strip, so deleting the GET
    (now `!= "POST"`) branch reddened nothing. A well-formed GET where
    needs_confirmation is False must still return the strip, unconfirmed and
    unwritten."""
    _, course = _setup(client)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=False
    )

    resp = client.get(
        _url(course),
        {
            "node": unit.pk,
            "flag": "published",
            "value": "1",
            "scope": "node",
            "token": _tok(unit),
        },
        **FETCH,
    )
    assert resp.status_code == 200
    assert any(t.name == "courses/manage/_flag_strip.html" for t in resp.templates)

    unit.refresh_from_db()
    assert unit.published is False
