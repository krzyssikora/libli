import json
import pathlib
import ssl
import urllib.error
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import override_settings

from courses.geogebra import DIM_MAX
from courses.geogebra import canonicalize_geogebra_url
from courses.geogebra import fetch_geogebra_dimensions
from courses.geogebra import geogebra_material_id
from courses.geogebra import geogebra_sized_src
from courses.geogebra import geogebra_url_size
from courses.geogebra import is_geogebra_iframe_url
from courses.geogebra import usable_dimensions

CANON = "https://www.geogebra.org/material/iframe/id/egZJdjsC"

_FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "geogebra"


def _payload(name):
    return (_FIXTURES / name).read_bytes()


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.geogebra.org/m/egZJdjsC",  # share short link
        "https://www.geogebra.org/material/show/id/egZJdjsC",  # classic share
        # full-embed src with the width/height/border cruft tail
        "https://www.geogebra.org/material/iframe/id/egZJdjsC/width/1600/height/763/border/888888/sfsb/true",
        "https://www.geogebra.org/material/iframe/id/egZJdjsC",  # already minimal
        "https://www.geogebra.org/material/iframe/id/egZJdjsC/",  # trailing slash
    ],
)
def test_recognized_forms_canonicalize(raw):
    assert canonicalize_geogebra_url(raw) == CANON


def test_idempotent_on_canonical():
    assert canonicalize_geogebra_url(CANON) == CANON


def test_bare_host_rewritten_to_www():
    assert canonicalize_geogebra_url("https://geogebra.org/m/egZJdjsC") == CANON


def test_id_with_dash_and_underscore_accepted():
    assert (
        canonicalize_geogebra_url("https://www.geogebra.org/m/a-b_C9")
        == "https://www.geogebra.org/material/iframe/id/a-b_C9"
    )


@pytest.mark.parametrize(
    "raw",
    [
        "https://beta.geogebra.org/m/egZJdjsC",  # subdomain not recognized
        "http://www.geogebra.org/m/egZJdjsC",  # non-https not recognized
        "//www.geogebra.org/m/egZJdjsC",  # scheme-relative not recognized
        "https://www.example.com/m/egZJdjsC",  # non-geogebra host
        "https://www.geogebra.org/classic/abc",  # app link (no m/, no id segment)
        "https://www.geogebra.org/M/egZJdjsC",  # mixed-case segment not recognized
        "https://www.geogebra.org/m/",  # m is final segment, empty id
        "https://www.geogebra.org/material/iframe/id",  # id final segment, empty id
        "https://www.geogebra.org/m/bad id",  # id fails charset (space)
        "https://www.geogebra.org",  # empty path (IndexError boundary)
        "https://www.geogebra.org/",  # slash-only path
        "https://[::1",  # malformed authority (defensive-parse backstop)
        "",  # empty input
    ],
)
def test_unrecognized_passes_through_unchanged(raw):
    assert canonicalize_geogebra_url(raw) == raw


# --- geogebra_sized_src: render-time /width/H so the applet fills the frame ---


def test_sized_src_appends_dimensions_to_canonical_url():
    assert geogebra_sized_src(CANON, 800, 760) == CANON + "/width/800/height/760"


def test_sized_src_unchanged_without_a_full_pair():
    assert geogebra_sized_src(CANON, None, None) == CANON
    assert geogebra_sized_src(CANON, 800, None) == CANON
    assert geogebra_sized_src(CANON, 0, 760) == CANON


def test_sized_src_unchanged_for_non_geogebra_url():
    url = "https://player.vimeo.com/video/123"
    assert geogebra_sized_src(url, 800, 760) == url


def test_sized_src_idempotent_when_already_sized():
    already = CANON + "/width/800/height/760"
    assert geogebra_sized_src(already, 800, 760) == already


def test_sized_src_unchanged_for_non_material_geogebra_path():
    url = "https://www.geogebra.org/m/egZJdjsC"
    assert geogebra_sized_src(url, 800, 760) == url


def test_sized_src_never_raises_on_junk():
    assert geogebra_sized_src("https://[::1", 800, 760) == "https://[::1"


@pytest.mark.parametrize("w,h", [(880, 660), (1, 1), (DIM_MAX, DIM_MAX)])
def test_usable_dimensions_accepts_positive_in_range_ints(w, h):
    assert usable_dimensions(w, h) is True


# --- geogebra_material_id: the lookup gate ---


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.geogebra.org/m/dcjktevj", "dcjktevj"),
        ("https://geogebra.org/m/dcjktevj", "dcjktevj"),  # bare host
        ("https://www.geogebra.org/material/show/id/dcjktevj", "dcjktevj"),
        ("https://www.geogebra.org/material/iframe/id/dcjktevj", "dcjktevj"),
        # _ID_RE charset gate
        ("https://www.geogebra.org/m/bad id", ""),
        # app link, not a material
        ("https://www.geogebra.org/classic/dcjktevj", ""),
        # the LAL-stored shape
        ("https://www.geogebra.org/x", ""),
        ("http://www.geogebra.org/m/dcjktevj", ""),  # non-https
        ("https://beta.geogebra.org/m/dcjktevj", ""),  # subdomain
        ("https://example.com/m/dcjktevj", ""),  # other host
    ],
)
def test_geogebra_material_id(url, expected):
    assert geogebra_material_id(url) == expected


def test_geogebra_material_id_never_raises_on_malformed_authority():
    # urlsplit("https://[::1").hostname raises ValueError; this runs on the render
    # path, so it must degrade rather than 500 the page.
    assert geogebra_material_id("https://[::1") == ""


@pytest.mark.parametrize(
    "w,h",
    [
        (0, 660),  # zero
        (-5, 660),  # negative
        (880, 0),
        (None, 660),  # partial pair
        (880, None),
        (None, None),
        ("880", 660),  # string, not int
        (880.0, 660),  # integral float still rejected
        (True, 660),  # bool is an int subclass in Python — must NOT pass
        (880, True),
        (DIM_MAX + 1, 660),  # over the PositiveIntegerField ceiling
        (880, DIM_MAX + 1),
    ],
)
def test_usable_dimensions_rejects_everything_else(w, h):
    assert usable_dimensions(w, h) is False


# --- is_geogebra_iframe_url: the render/badge predicate ---


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.geogebra.org/material/iframe/id/dcjktevj", True),
        ("https://geogebra.org/material/iframe/id/dcjktevj", True),  # bare host
        # the "width" in segments clause — geogebra_sized_src refuses this one too
        (
            "https://www.geogebra.org/material/iframe/id/dcjktevj/width/880/height/660",
            False,
        ),
        # not a shape sized_src rewrites
        ("https://www.geogebra.org/m/dcjktevj", False),
        ("https://www.geogebra.org/material/show/id/dcjktevj", False),
        ("https://www.geogebra.org/x", False),
        ("https://www.geogebra.org/classic/abc", False),
        # non-https
        ("http://www.geogebra.org/material/iframe/id/dcjktevj", False),
        ("https://example.com/material/iframe/id/dcjktevj", False),
        # deliberately STRICTER than geogebra_sized_src, which never indexes segments[3]
        ("https://www.geogebra.org/material/iframe/id", False),  # no id at all
        # id fails _ID_RE
        ("https://www.geogebra.org/material/iframe/id/ab%20cd", False),
    ],
)
def test_is_geogebra_iframe_url(url, expected):
    assert is_geogebra_iframe_url(url) is expected


def test_is_geogebra_iframe_url_never_raises_on_malformed_authority():
    assert is_geogebra_iframe_url("https://[::1") is False


# --- geogebra_url_size: frame_ratio step 0, the URL-sized-applet override ---

_BASE = "https://www.geogebra.org/material/iframe/id/abc"


@pytest.mark.parametrize(
    "url,expected",
    [
        (f"{_BASE}/width/880/height/660", (880, 660)),
        (f"{_BASE}/width/800/height/400", (800, 400)),  # non-4:3: read, not assumed
        (f"{_BASE}/width/abc/height/def", (None, None)),  # non-numeric
        (f"{_BASE}/width/880", (None, None)),  # height segment missing
        (f"{_BASE}/width/0/height/0", (None, None)),  # fails usable_dimensions
        (f"{_BASE}/height/660/width/880", (None, None)),  # reversed order
        # Trailing segments after offset 7 are IGNORED, so the first positional pair
        # wins. Same rule that admits GeoGebra's real border/sfsb cruft below.
        (f"{_BASE}/width/880/height/660/width/999", (880, 660)),
        (_BASE, (None, None)),  # no tail at all
        # scoped to GeoGebra: another provider with width/height path segments
        ("https://player.vimeo.com/video/1/width/4/height/3", (None, None)),
        # non-https
        (
            "http://www.geogebra.org/material/iframe/id/abc/width/880/height/660",
            (None, None),
        ),
    ],
)
def test_geogebra_url_size(url, expected):
    assert geogebra_url_size(url) == expected


def test_geogebra_url_size_reads_geogebras_real_embed_tail():
    # THE regression guard on the len(segments) rule. This is the shape GeoGebra's own
    # embed code ships, already pinned verbatim at tests/test_geogebra.py:15 -- 12
    # segments, not 8. A `len(segments) != 8` rule rejects it, frame_ratio then claims
    # NO ratio (is_geogebra_iframe_url is False because "width" in segments), and the
    # wrapper keeps 16:9 while the src imposes 1600/763 -- the original defect.
    url = (
        "https://www.geogebra.org/material/iframe/id/egZJdjsC"
        "/width/1600/height/763/border/888888/sfsb/true"
    )
    assert geogebra_url_size(url) == (1600, 763)


def test_geogebra_url_size_rejects_style_injection():
    # ';' and ':' are legal in a path segment and Django's autoescape does not
    # escape them. Returning raw text here would inject CSS declarations into the
    # style attribute. Must reject, and must return ints when it does not.
    hostile = f"{_BASE}/width/1;position:fixed;top:0;height:100vh/height/1"
    assert geogebra_url_size(hostile) == (None, None)


def test_geogebra_url_size_never_raises_on_malformed_authority():
    assert geogebra_url_size("https://[::1") == (None, None)


# --- fetch_geogebra_dimensions: the API lookup ---


def _patch_open(body=None, exc=None):
    """Patch the transport seam; return the mock so tests can assert on call args.

    The double MUST be a context manager: fetch_geogebra_dimensions uses
    `with _open(...) as resp:` (needed because the read is capped, so the connection is
    never drained and an unclosed response leaks a socket per call).
    """

    class _Resp:
        def read(self, n=-1):
            return body[:n] if n and n > 0 else body

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    def _side_effect(request, timeout=None):
        if exc is not None:
            raise exc
        return _Resp()

    return patch("courses.geogebra._open", side_effect=_side_effect)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_reads_top_level_settings_for_an_applet():
    with _patch_open(_payload("wseg.json")):
        assert fetch_geogebra_dimensions("wgzr7tsu") == (880, 660)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_reads_element_settings_for_a_worksheet():
    with _patch_open(_payload("ws.json")):
        assert fetch_geogebra_dimensions("dcjktevj") == (880, 660)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_skips_non_g_and_junk_entries_without_aborting_the_scan():
    # The bare `except Exception` wraps the whole body, so a junk entry raising
    # mid-scan would abort it and return (None, None) even though a usable G
    # follows. Per-entry access must be defensive.
    with _patch_open(_payload("ws_non_g_first.json")):
        assert fetch_geogebra_dimensions("derived") == (880, 660)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_keeps_scanning_past_a_g_with_no_usable_pair():
    with _patch_open(_payload("ws_first_g_unsized.json")):
        assert fetch_geogebra_dimensions("derived") == (800, 400)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_refuses_to_guess_on_a_multi_applet_worksheet(caplog):
    # The iframe embeds the WHOLE worksheet, so "the first G" is an arbitrary pick
    # that need bear no relation to the rendered ratio. A confidently wrong frame
    # with size_unknown False is worse than the 4:3 fallback plus a badge.
    with _patch_open(_payload("ws_two_sized_g.json")):
        assert fetch_geogebra_dimensions("derived") == (None, None)
    # Filter by logger name, like the HTTP-error test below: an unfiltered scan of
    # caplog.records would be satisfied by ANY logger emitting the substring.
    assert any(
        "multiple" in r.message.lower()
        for r in caplog.records
        if r.name == "courses.geogebra"
    )


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_falls_through_a_top_level_settings_without_dimensions():
    with _patch_open(_payload("ws_layout_settings.json")):
        assert fetch_geogebra_dimensions("derived") == (880, 660)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_degrades_on_http_error_and_logs_it(caplog):
    err = urllib.error.HTTPError(
        "https://api.geogebra.org/x", 400, "Bad Request", {}, None
    )
    with _patch_open(exc=err):
        assert fetch_geogebra_dimensions("nosuchid00") == (None, None)
    record = next(r for r in caplog.records if r.name == "courses.geogebra")
    assert "nosuchid00" in record.message and "400" in record.message


@override_settings(GEOGEBRA_API_LOOKUP=True)
@pytest.mark.parametrize(
    "exc",
    [
        urllib.error.URLError("unreachable"),
        TimeoutError("timed out"),
        # NOT a URLError subclass — proves the bare except is needed
        ssl.SSLError("handshake"),
    ],
)
def test_fetch_degrades_on_any_transport_exception(exc):
    with _patch_open(exc=exc):
        assert fetch_geogebra_dimensions("dcjktevj") == (None, None)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_degrades_on_unparseable_body():
    with _patch_open(b"not json at all"):
        assert fetch_geogebra_dimensions("dcjktevj") == (None, None)


@override_settings(GEOGEBRA_API_LOOKUP=True)
@pytest.mark.parametrize("body", [b"[]", b'"x"', b"42"])
def test_fetch_logs_a_valid_json_non_object_body(body, caplog):
    # Distinct from the unparseable case above: these PARSE fine, so they miss the
    # JSONDecodeError path entirely and take the non-dict early return. Without its
    # log line this is a silent fourth failure mode -- an API shape change would look
    # exactly like a material having no dimensions.
    with _patch_open(body):
        assert fetch_geogebra_dimensions("dcjktevj") == (None, None)
    assert any(
        "not an object" in r.message
        for r in caplog.records
        if r.name == "courses.geogebra"
    )


@override_settings(GEOGEBRA_API_LOOKUP=True)
@pytest.mark.parametrize("bad", [0, -5, "880", 2147483648, True, 880.0])
def test_fetch_rejects_unusable_width_values(bad):
    body = json.dumps(
        {"id": "x", "type": "wseg", "settings": {"width": bad, "height": 660}}
    ).encode()
    with _patch_open(body):
        assert fetch_geogebra_dimensions("x") == (None, None)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_treats_an_oversized_body_as_a_distinct_failure(caplog):
    from courses.geogebra import _MAX_BODY_BYTES

    with _patch_open(b"x" * (_MAX_BODY_BYTES + 1)):
        assert fetch_geogebra_dimensions("dcjktevj") == (None, None)
    assert any(
        "oversiz" in r.message.lower()
        for r in caplog.records
        if r.name == "courses.geogebra"
    )


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_sends_the_explicit_user_agent_and_the_configured_timeout():
    from courses.geogebra import _TIMEOUT_SECONDS
    from courses.geogebra import _USER_AGENT

    with _patch_open(_payload("wseg.json")) as opener:
        fetch_geogebra_dimensions("wgzr7tsu")
    request = opener.call_args.args[0]
    # Request.add_header stores keys .capitalize()d, so get_header("User-Agent")
    # returns None. Lowercase 'a' is the correct spelling here.
    assert request.get_header("User-agent") == _USER_AGENT
    assert opener.call_args.kwargs["timeout"] == _TIMEOUT_SECONDS
    # NOTE what this pins: that the CALLER passes the constant. The forgotten-kwarg
    # bug would live inside _open, below this patch point.


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_negative_caches_a_failure_for_the_same_id():
    with _patch_open(exc=urllib.error.URLError("down")) as opener:
        assert fetch_geogebra_dimensions("dcjktevj") == (None, None)
        assert fetch_geogebra_dimensions("dcjktevj") == (None, None)
    assert opener.call_count == 1


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_negative_cache_is_scoped_to_ONE_id():
    # THE guard on the {material_id} in the cache key. A build using a constant key
    # (e.g. "geogebra:dims") passes every other test here: the same-id test still sees
    # call_count == 1, and the kill-switch test asserts an ABSENCE, true for a constant
    # key too. The mutant is not cosmetic -- one 400 on a bad id would suppress sizing
    # for EVERY material for 60s, so unrelated embeds silently render 4:3 with a badge
    # and no log naming them.
    with _patch_open(exc=urllib.error.URLError("down")):
        assert fetch_geogebra_dimensions("badid0000") == (None, None)
    with _patch_open(_payload("wseg.json")) as opener:
        assert fetch_geogebra_dimensions("wgzr7tsu") == (880, 660)
    opener.assert_called_once()  # the second id was NOT short-circuited


def test_fetch_kill_switch_makes_no_request_and_writes_no_sentinel():
    # The ONE test that runs under the suite's GEOGEBRA_API_LOOKUP=False default.
    with _patch_open(_payload("wseg.json")) as opener:
        assert fetch_geogebra_dimensions("wgzr7tsu") == (None, None)
    opener.assert_not_called()
    # No cache WRITE either: a shared _fail() exit that cached here would poison the
    # sentinel for 60s, so flipping the flag on would still short-circuit.
    assert cache.get("geogebra:dims:wgzr7tsu") is None


def test_no_redirect_handler_refuses_redirects():
    from courses.geogebra import _NoRedirect

    # integrations/delivery.py ships this handler entirely untested — grep for
    # _NoRedirect under tests/ returns nothing — so this is a new test, not reuse.
    # It RAISES (matching delivery.py verbatim); it does not return None.
    class _Req:
        full_url = "https://api.geogebra.org/v1.0/materials/abc"

    with pytest.raises(urllib.error.HTTPError):
        _NoRedirect().redirect_request(_Req(), None, 302, "Found", {}, "http://evil")
