"""Canonicalize a pasted YouTube/Vimeo link into a working embed URL.

The single parser for video-element URLs. Recognized hosts are rebuilt from
scratch (host + path + only the start/hash we keep), dropping all tracking
cruft; unrecognized hosts pass through unchanged for the allow-list to judge.
"""

import re
from urllib.parse import parse_qs
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

_BARE_SECONDS = re.compile(r"^\d+$")
# At least one of h/m/s, in that fixed order, each component a run of digits.
_HMS = re.compile(r"^(?=\d+[hms])(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")


def _parse_duration(value):
    """Return total seconds for a start value, or 0 if absent/unparseable/zero."""
    value = (value or "").strip()
    if _BARE_SECONDS.match(value):
        return int(value)
    m = _HMS.match(value)
    if not m:
        return 0
    h, mm, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mm * 60 + s


_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

_NO_VIDEO_MSG = _(
    "That looks like a %(provider)s link but we couldn't find a single "
    "video in it — paste the link to one video."
)


def _first(query, key):
    """First value of a query param, or '' if absent.

    keep_blank_values=True is load-bearing: it makes an empty `?t=` / `?v=`
    surface as "" (→ start fall-through to `start`, and empty-`v=` → no ID →
    reject). Do not drop it — two unrelated tests depend on it.
    """
    vals = parse_qs(query, keep_blank_values=True).get(key)
    return vals[0] if vals else ""


def _is_youtube(host):
    return (
        host == "youtu.be"
        or host == "youtube.com"
        or host.endswith(".youtube.com")
        or host == "youtube-nocookie.com"
        or host.endswith(".youtube-nocookie.com")
    )


def _youtube_id(host, path, query):
    """Return the validated 11-char ID, or None if none is extractable."""
    segs = path.split("/")[1:]  # drop leading '' from the leading slash
    if host == "youtu.be":
        cand = segs[0] if segs else ""
    else:
        first = segs[0] if segs else ""
        if first == "watch":
            cand = _first(query, "v")
        elif first in ("embed", "shorts", "live", "v"):
            cand = segs[1] if len(segs) > 1 else ""
        else:
            cand = ""
    return cand if _YT_ID.match(cand or "") else None


def _youtube_start(query):
    """Seconds from t, else start; first occurrence; junk t falls through to start."""
    for key in ("t", "start"):
        secs = _parse_duration(_first(query, key))
        if secs > 0:
            return secs
    return 0


def canonicalize_video_url(raw):
    text = (raw or "").strip()
    if not text:
        return ""
    if _SCHEME_RE.match(text):
        to_parse = text
    elif text.startswith("//"):
        to_parse = "https:" + text
    else:
        to_parse = "https://" + text
    parts = urlsplit(to_parse)
    host = parts.hostname or ""  # urlsplit lowercases hostname, strips port/userinfo
    if _is_youtube(host):
        vid = _youtube_id(host, parts.path, parts.query)
        if vid is None:
            raise ValidationError(_NO_VIDEO_MSG % {"provider": "YouTube"})
        out = "https://www.youtube.com/embed/" + vid
        start = _youtube_start(parts.query)
        if start > 0:
            out += f"?start={start}"
        return out
    # Vimeo branch inserted here in Task 3.
    return text  # unrecognized host → stripped input unchanged
