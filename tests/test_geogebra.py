import pytest

from courses.geogebra import canonicalize_geogebra_url
from courses.geogebra import geogebra_sized_src

CANON = "https://www.geogebra.org/material/iframe/id/egZJdjsC"


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
