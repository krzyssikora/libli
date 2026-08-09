import re

import pytest
from django.urls import reverse

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
    """WR8. Read data-updated out of the returned fragment and re-post it as
    token on a second edit; assert it succeeds rather than 409ing."""
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
    html = resp.content.decode()
    m = re.search(rf'id="node-{unit.pk}"[^>]*data-updated="([^"]+)"', html)
    assert m, html
    fresh_token = m.group(1)

    resp2 = client.post(
        _url(course),
        {
            "node": unit.pk,
            "flag": "obligatory",
            "value": "0",
            "scope": "node",
            "token": fresh_token,
        },
        **FETCH,
    )
    assert resp2.status_code == 200


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
    though its published column is untouched."""
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
    chapter_published_before = chapter.published

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
    assert chapter.published == chapter_published_before


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
    assert not (400 <= resp.status_code < 600)
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
