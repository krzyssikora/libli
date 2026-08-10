"""Characterization tests: the POST shape switchgate_editor.js emits is already
accepted by the unmodified server. Green on master by design (no application Python
changes), so a stated exception to the RED-before-fix rule. Their job is to pin the
"No server changes" claim for module 2 and to catch a FUTURE parser change."""

import pytest

from courses.element_forms import _MIN_OPTIONS
from tests.helpers_editor_rows import base_post
from tests.helpers_editor_rows import open_element_form
from tests.helpers_editor_rows import save_url

pytestmark = pytest.mark.django_db


def test_middle_option_removed_and_renumbered(pa_client, switchgate_element):
    """What module 2 emits after removing the middle of three options: a SHORTER
    option list plus an `answer` index renumbered to match its new position."""
    course, unit, el = switchgate_element(
        options=["alpha", "beta", "gamma"], answer=2, stem="2 {{choice}} 2 = 4"
    )
    data = base_post(course, unit, el, "switchgate")
    data["stem"] = "2 {{choice}} 2 = 4"
    # A LIST, not a string: Django's test client encodes a list as repeated keys,
    # which is what getlist("option") reads. A string would post one option and the
    # test would pass for the wrong reason.
    data["option"] = ["alpha", "gamma"]  # beta detached
    data["answer"] = "1"  # gamma moved from index 2 to 1
    resp = pa_client.post(save_url(course), data, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    obj = el.content_object
    obj.refresh_from_db()
    assert obj.options == ["alpha", "gamma"]
    assert obj.options[obj.answer] == "gamma"


def test_switchgate_min_bound_matches_the_server_constant(
    pa_client, switchgate_element
):
    """Built from _MIN_OPTIONS, not a literal 2: a literal on both sides stays green
    when the constant changes, so it could not catch the drift it exists for."""
    course, _unit, el = switchgate_element(options=["a", "b"], answer=0)
    html = open_element_form(pa_client, course, el)
    assert f'data-sgate-min="{_MIN_OPTIONS}"' in html
