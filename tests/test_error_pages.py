"""Behaviour of the illustrated 404 / 403 pages.

Django forces DEBUG=False under test, so client.get() renders the REAL
templates -- no override_settings needed.
"""

import pytest

pytestmark = pytest.mark.django_db


def test_404_renders_the_illustrated_page(client):
    resp = client.get("/no-such-page/")
    assert resp.status_code == 404
    body = resp.content
    assert b"Nothing here" in body
    # b"..." not "...".encode() -- this string is ASCII, and ruff's UP012 rejects
    # a redundant encode. Reserve .encode() for the Polish assertions in Task 5.
    assert b"We appreciate your eagerness to discover" in body
    assert b"report it to your administrator" in body
    assert b"couldn" not in body.split(b"<main")[1], "old copy still present"


def test_404_echoes_the_attempted_path_in_a_code_element(client):
    resp = client.get("/no-such-page/")
    # Deliberately NOT a bare substring check: base.html's language-switch form
    # renders <input type="hidden" name="next" value="{{ request.path }}"> on
    # every page, so "/no-such-page/" is already in the body whether or not the
    # path line exists. Assert the element.
    assert b"<code>/no-such-page/</code>" in resp.content


def test_404_never_emits_a_raw_tag_from_the_attempted_path(client):
    # quote() in Django's page_not_found percent-encodes < > " ' & ( ) BEFORE the
    # template sees the value, so this cannot catch a stray |safe (the bytes are
    # identical either way). What it DOES catch is someone swapping
    # {{ request_path }} for the un-quoted {{ request.path }}.
    # Note: a bare b"<script>" assertion would be vacuous -- base.html emits
    # three literal <script> tags of its own.
    resp = client.get("/x/<script>alert(1)</script>/")
    assert resp.status_code == 404
    assert b"<script>alert" not in resp.content
    assert b"%3Cscript%3Ealert" in resp.content


def test_404_is_wired_to_the_error_page_stylesheet_and_classes(client):
    # All THREE block overrides, because none is implied by the prose assertions
    # above -- delete any one of them and every other test in this file still
    # passes while the page breaks visibly. Verified by deletion:
    #   extra_css   -> no stylesheet at all
    #   body_class  -> no watermark, no body flex column
    #   main_class  -> content pinned to the top instead of centred, AND painted
    #                  OVER by the fixed watermark (main loses z-index: 1)
    resp = client.get("/no-such-page/")
    assert b"core/css/error.css" in resp.content
    assert b'class="error-page"' in resp.content
    assert b'class="app-main error-page__main"' in resp.content
