"""HTTP Range support for locally-served media.

Django 5.2's FileResponse and django.views.static.serve implement no Range
handling at all: a `Range:` request gets 200 + the whole file and no
`Accept-Ranges`. A browser will not let a student scrub a <video> without
`206 Partial Content`, so uploaded videos could only be played straight through
-- no skipping forward, and replaying a moment meant restarting.

core.media_serve.serve_media wraps the stock view and adds the range half.
These run against a real file on disk through the real view (no mocks).
"""

import pytest
from django.test import RequestFactory

from core.media_serve import serve_media

BODY = bytes(range(256)) * 8  # 2048 bytes, every byte value -> offsets are checkable
NAME = "clip.mp4"


@pytest.fixture
def media_root(tmp_path):
    (tmp_path / NAME).write_bytes(BODY)
    return tmp_path


def _get(media_root, range_header=None):
    headers = {"Range": range_header} if range_header else {}
    request = RequestFactory().get(f"/media/{NAME}", headers=headers)
    return serve_media(request, NAME, document_root=str(media_root))


def _body(response):
    return b"".join(response.streaming_content)


def test_plain_get_advertises_range_support(media_root):
    """Without Accept-Ranges the browser never even offers a scrub bar."""
    response = _get(media_root)
    assert response.status_code == 200
    assert response.headers["Accept-Ranges"] == "bytes"
    assert _body(response) == BODY


def test_closed_range_returns_206_with_only_those_bytes(media_root):
    response = _get(media_root, "bytes=0-9")
    assert response.status_code == 206
    assert response.headers["Content-Range"] == f"bytes 0-9/{len(BODY)}"
    assert response.headers["Content-Length"] == "10"
    assert _body(response) == BODY[0:10]


def test_open_ended_range_runs_to_the_last_byte(media_root):
    """`bytes=500-` — what a player sends when you drag the scrub handle."""
    response = _get(media_root, "bytes=500-")
    assert response.status_code == 206
    assert response.headers["Content-Range"] == f"bytes 500-{len(BODY) - 1}/{len(BODY)}"
    assert _body(response) == BODY[500:]


def test_suffix_range_returns_the_final_bytes(media_root):
    """`bytes=-500` means the LAST 500 bytes, not the first 500 — an easy
    off-by-everything if the header is parsed as a start offset."""
    response = _get(media_root, "bytes=-500")
    assert response.status_code == 206
    start = len(BODY) - 500
    assert response.headers["Content-Range"] == (
        f"bytes {start}-{len(BODY) - 1}/{len(BODY)}"
    )
    assert _body(response) == BODY[-500:]


def test_end_beyond_eof_is_clamped(media_root):
    response = _get(media_root, "bytes=2040-999999")
    assert response.status_code == 206
    assert response.headers["Content-Range"] == (
        f"bytes 2040-{len(BODY) - 1}/{len(BODY)}"
    )
    assert _body(response) == BODY[2040:]


def test_range_starting_past_eof_is_416(media_root):
    """RFC 9110: an unsatisfiable range must be refused, not silently served."""
    response = _get(media_root, f"bytes={len(BODY)}-")
    assert response.status_code == 416
    assert response.headers["Content-Range"] == f"bytes */{len(BODY)}"


@pytest.mark.parametrize(
    "header",
    [
        "bytes=0-1,5-6",  # multi-range: legal to ignore, must not be mis-served
        "items=0-1",  # unknown unit
        "bytes=abc",  # malformed
        "bytes=-",  # no numbers at all
    ],
)
def test_unusable_range_headers_fall_back_to_the_whole_file(media_root, header):
    response = _get(media_root, header)
    assert response.status_code == 200
    assert _body(response) == BODY


def test_range_response_keeps_the_content_type(media_root):
    """A 206 that loses video/mp4 would break playback just as thoroughly."""
    full = _get(media_root)
    partial = _get(media_root, "bytes=0-9")
    assert partial.headers["Content-Type"] == full.headers["Content-Type"]
    assert partial.headers["Content-Type"] == "video/mp4"


def test_missing_file_still_404s(media_root):
    from django.http import Http404

    with pytest.raises(Http404):
        _get_missing = RequestFactory().get("/media/nope.mp4")
        serve_media(_get_missing, "nope.mp4", document_root=str(media_root))
