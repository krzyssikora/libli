"""Locally-served media with HTTP Range support.

Django 5.2 implements no Range handling anywhere in the response stack: both
`FileResponse` and `django.views.static.serve` answer a `Range:` request with
`200 OK` and the entire file, and never send `Accept-Ranges`. Browsers refuse to
seek a `<video>`/`<audio>` element served that way -- playback is start-to-finish
only, so a student cannot skip ahead and cannot replay a passage without
reloading the whole clip.

This wraps the stock view and adds the missing half: `Accept-Ranges` on every
response, `206 Partial Content` for a satisfiable single range, and `416` for one
that starts past EOF. Path safety, 404s, content-type sniffing and
`If-Modified-Since` all stay with `django.views.static.serve` -- this only
narrows what gets sent.

NOTE ON PRODUCTION: `config/urls.py` only routes `/media/` at all when
DEBUG=True, so this covers local runs. A deployment that serves `MEDIA_ROOT`
through a real web server (nginx, a CDN) gets range support from that server and
needs nothing here; one that puts Django in front of media must route it through
this view, or video seeking will be broken for students.
"""

import re

from django.http import FileResponse
from django.http import HttpResponse
from django.http import StreamingHttpResponse
from django.views.static import serve as django_serve

# A single byte range: "bytes=0-499", "bytes=500-", "bytes=-500". A multi-range
# header (comma-separated) deliberately does NOT match -- see _resolve_range.
_RANGE_RE = re.compile(r"^\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*$")

_UNSATISFIABLE = object()

_CHUNK = 64 * 1024


def _resolve_range(header, size):
    """(start, end) inclusive for a satisfiable single range.

    None  -> no usable range; caller serves the whole file with 200. This covers
             an absent header, a malformed one, an unknown unit, and a legal
             multi-range request (RFC 9110 permits a server to answer any range
             request with the full representation, and multipart/byteranges is
             not worth the machinery for a video tag that never sends it).
    _UNSATISFIABLE -> a well-formed range that starts at or past EOF; caller 416s.
    """
    if not header:
        return None
    match = _RANGE_RE.match(header)
    if not match:
        return None
    first, last = match.group(1), match.group(2)
    if not first and not last:
        return None  # "bytes=-" carries no numbers
    if not first:
        # Suffix form: the LAST `last` bytes, not an offset. A suffix longer than
        # the file is legal and means the whole file.
        length = int(last)
        if length == 0:
            return _UNSATISFIABLE
        return max(0, size - length), size - 1
    start = int(first)
    if start >= size:
        return _UNSATISFIABLE
    end = int(last) if last else size - 1
    # Clamp: asking past EOF is legal, answering past it is not.
    end = min(end, size - 1)
    if end < start:
        return None
    return start, end


def _bounded(handle, length):
    """Yield exactly `length` bytes from `handle`, then close it.

    The file object is borrowed from the FileResponse we discard, so nothing else
    will close it; the `finally` is what keeps a seek-heavy player from leaking a
    descriptor per scrub.
    """
    remaining = length
    try:
        while remaining > 0:
            chunk = handle.read(min(_CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        handle.close()


def serve_media(request, path, document_root=None, show_indexes=False):
    response = django_serve(
        request, path, document_root=document_root, show_indexes=show_indexes
    )
    # 304s and directory indexes carry no file to slice.
    if response.status_code != 200 or not isinstance(response, FileResponse):
        return response
    response.headers["Accept-Ranges"] = "bytes"

    handle = getattr(response, "file_to_stream", None)
    try:
        size = int(response.headers["Content-Length"])
    except (KeyError, TypeError, ValueError):
        size = None
    if handle is None or size is None:
        return response

    resolved = _resolve_range(request.headers.get("Range"), size)
    if resolved is None:
        return response
    if resolved is _UNSATISFIABLE:
        response.close()
        refused = HttpResponse(status=416)
        refused.headers["Content-Range"] = f"bytes */{size}"
        refused.headers["Accept-Ranges"] = "bytes"
        return refused

    start, end = resolved
    length = end - start + 1
    handle.seek(start)
    partial = StreamingHttpResponse(
        _bounded(handle, length),
        status=206,
        content_type=response.headers.get("Content-Type"),
    )
    partial.headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    partial.headers["Content-Length"] = str(length)
    partial.headers["Accept-Ranges"] = "bytes"
    for header in ("Last-Modified", "Content-Disposition"):
        if header in response.headers:
            partial.headers[header] = response.headers[header]
    # The discarded FileResponse must not close the handle we just handed to the
    # generator; drop its closer instead of calling response.close().
    response._resource_closers.clear()
    return partial
