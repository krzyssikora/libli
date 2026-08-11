"""Characterization tests: the POST shapes formset_rows.js emits are already
accepted by the unmodified server. Green on master by design (no application
Python changes), so they are a stated exception to the RED-before-fix rule. Their
job is to catch a FUTURE parser change that would break the editors."""

import pytest

from tests.helpers_editor_rows import base_post
from tests.helpers_editor_rows import save_url

pytestmark = pytest.mark.django_db


def test_more_rows_than_were_rendered_all_save(pa_client, matchpair_element):
    """The path that is unreachable today: the Add button has no handler, so the
    POST can never carry more forms than the server rendered."""
    course, unit, el = matchpair_element(pairs=[("a", "1"), ("b", "2")])
    data = base_post(course, unit, el, "matchpairquestion")
    data.update(
        {
            "stem": "",
            "pairs-TOTAL_FORMS": "5",
            "pairs-INITIAL_FORMS": "2",
            "pairs-MIN_NUM_FORMS": "0",
            "pairs-MAX_NUM_FORMS": "1000",
        }
    )
    for i, (left, right) in enumerate(
        [("a", "1"), ("b", "2"), ("c", "3"), ("d", "4"), ("e", "5")]
    ):
        data[f"pairs-{i}-left"] = left
        data[f"pairs-{i}-right"] = right
    for i, pair in enumerate(el.content_object.pairs.all()):
        data[f"pairs-{i}-id"] = pair.pk
    # X-Requested-With: the success path ends `if not _wants_fragment(request):
    # return redirect(...)`, so a plain post returns 302, not 200.
    resp = pa_client.post(save_url(course), data, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    el.content_object.refresh_from_db()
    assert el.content_object.pairs.count() == 5


def test_ticked_delete_removes_exactly_that_pair(pa_client, matchpair_element):
    course, unit, el = matchpair_element(pairs=[("a", "1"), ("b", "2"), ("c", "3")])
    pairs = list(el.content_object.pairs.all())
    data = base_post(course, unit, el, "matchpairquestion")
    data.update(
        {
            "stem": "",
            "pairs-TOTAL_FORMS": "3",
            "pairs-INITIAL_FORMS": "3",
            "pairs-MIN_NUM_FORMS": "0",
            "pairs-MAX_NUM_FORMS": "1000",
            "pairs-1-DELETE": "on",
        }
    )
    for i, p in enumerate(pairs):
        data[f"pairs-{i}-id"] = p.pk
        data[f"pairs-{i}-left"] = p.left
        data[f"pairs-{i}-right"] = p.right
    resp = pa_client.post(save_url(course), data, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    assert sorted(p.left for p in el.content_object.pairs.all()) == ["a", "c"]
