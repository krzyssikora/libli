# Video URL Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a content author paste any common YouTube or Vimeo link into a video element and have it saved as a working `/embed` URL (start time preserved), or rejected at author time with a clear message.

**Architecture:** A new pure module `courses/video_url.py` exposes `canonicalize_video_url(raw) -> str`. `VideoElementForm` overrides its `url` field to a free-text `CharField` (so the raw paste reaches a `clean_url` that calls the canonicalizer, mirroring the existing `IframeElementForm` precedent), then the normalized `www.youtube.com` / `player.vimeo.com` URL passes the existing `validate_embed_url` allow-list. Note that allow-list check runs because the **form's** `clean()` explicitly calls `instance.clean()` during `is_valid()` — `VideoElement` has no `save()`-level `full_clean()`, so a direct model `.save()` would bypass it; the form path is the enforcement boundary. The editor template's hand-rolled URL input switches `type="url"` → `type="text"` so the browser doesn't block scheme-less pastes. No model or migration changes.

**Tech Stack:** Python 3 / Django, `urllib.parse`, `re`, pytest, ruff, Django i18n (`gettext`).

## Global Constraints

- **No model or migration changes.** `VideoElement.url` stays `models.URLField(blank=True)`; the form overrides the *form field* only.
- **`canonicalize_video_url` is the single parser.** All URL parsing lives in `courses/video_url.py`; the form/template never re-parse.
- **Lint:** CI runs `ruff format --check` AND `ruff check`. Run BOTH `ruff format courses/ tests/` and `ruff check courses/ tests/` before every commit.
- **Tests:** `pytest`. Run from repo root.
- **User-facing strings are translatable:** wrap new template strings and the reject message in `gettext` / `{% trans %}`; add Polish (`pl`) `.po` entries. Proper nouns "YouTube"/"Vimeo" are NOT translated.
- **Template comments:** any explanatory comment must be single-line `{# … #}` or a `{% comment %}…{% endcomment %}` block — never a multi-line `{# #}` (recurring project bug ships them visible).
- **Recognized-host output contract:** YouTube → `https://www.youtube.com/embed/<ID>`; Vimeo → `https://player.vimeo.com/video/<ID>`. Both are on the default `ALLOWED_EMBED_DOMAINS`.

---

## File Structure

- **Create** `courses/video_url.py` — the pure canonicalizer + private helpers (`_parse_duration`, host detection, ID/hash extraction). One responsibility: turn a pasted string into a validated embed URL or raise.
- **Create** `tests/test_video_url.py` — unit tests for the pure function.
- **Modify** `courses/element_forms.py` — `VideoElementForm`: `url` field override, `clean_url`, guarded `clean()`.
- **Modify** `tests/test_courses_elements.py` — form-level integration tests.
- **Modify** `templates/courses/manage/editor/_edit_video.html` — input `type`, label, help text, `{% trans %}`.
- **Modify** `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`) — Polish translations.

---

### Task 1: Duration parser helper

**Files:**
- Create: `courses/video_url.py`
- Test: `tests/test_video_url.py`

**Interfaces:**
- Produces: `_parse_duration(value: str) -> int` — total seconds for a YouTube/Vimeo start value. Returns `0` for absent / empty / unparseable / zero input. Accepts bare seconds (`"90"`) or an ordered `h`/`m`/`s` form (`"1h2m3s"`, `"1m30s"`, `"90s"`, `"2h"`, `"90m"`). Out-of-order or trailing-garbage input → `0`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_video_url.py`:

```python
import pytest
from django.core.exceptions import ValidationError

from courses.video_url import _parse_duration


@pytest.mark.parametrize(
    "value,expected",
    [
        ("90", 90),
        ("90s", 90),
        ("1m30s", 90),
        ("1h2m3s", 3723),
        ("2h", 7200),
        ("90m", 5400),
        ("0", 0),
        ("", 0),
        ("   ", 0),
        ("1m30sxyz", 0),  # trailing garbage
        ("s", 0),         # bare unit, no number
        ("1s30m", 0),     # out of order
    ],
)
def test_parse_duration(value, expected):
    assert _parse_duration(value) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_video_url.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'courses.video_url'`.

- [ ] **Step 3: Write minimal implementation**

Create `courses/video_url.py`:

```python
"""Canonicalize a pasted YouTube/Vimeo link into a working embed URL.

The single parser for video-element URLs. Recognized hosts are rebuilt from
scratch (host + path + only the start/hash we keep), dropping all tracking
cruft; unrecognized hosts pass through unchanged for the allow-list to judge.
"""

import re

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_video_url.py -v`
Expected: PASS (all parametrized cases).

- [ ] **Step 5: Lint and commit**

```bash
ruff format courses/video_url.py tests/test_video_url.py
ruff check courses/video_url.py tests/test_video_url.py
git add courses/video_url.py tests/test_video_url.py
git commit -m "feat(video): add _parse_duration start-time helper"
```

---

### Task 2: `canonicalize_video_url` — YouTube + pass-through + empty

**Files:**
- Modify: `courses/video_url.py`
- Test: `tests/test_video_url.py`

**Interfaces:**
- Consumes: `_parse_duration` (Task 1).
- Produces: `canonicalize_video_url(raw: str) -> str`. Returns a validated https embed URL for recognized hosts, `""` for empty input, or the stripped input unchanged for unrecognized hosts. Raises `django.core.exceptions.ValidationError` for a recognized host with no extractable video ID. (Vimeo handled in Task 3 — until then a Vimeo host falls through to pass-through; no Vimeo tests exist yet.)

- [ ] **Step 1: Write the failing test**

First extend the existing top-of-file import (do NOT add a new `import` line lower
in the file — ruff E402 "module-import-not-at-top-of-file" runs on `tests/` and
would fail the Step 5 commit gate). Change the Task 1 import line:

```python
from courses.video_url import _parse_duration, canonicalize_video_url
```

Then append the test code below to `tests/test_video_url.py`:

```python
YT = "https://www.youtube.com/embed/lk5_OSsawz4"


@pytest.mark.parametrize(
    "raw,expected",
    [
        # watch / share / shorts / live / legacy, all → embed, cruft dropped
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&source_ve_path=MTc4", YT),
        ("https://youtu.be/lk5_OSsawz4?si=xMBEVds6TCuZdtQO", YT),
        ("https://www.youtube.com/shorts/lk5_OSsawz4", YT),
        ("https://www.youtube.com/live/lk5_OSsawz4", YT),
        ("https://www.youtube.com/v/lk5_OSsawz4", YT),
        ("https://m.youtube.com/watch?v=lk5_OSsawz4", YT),
        ("https://music.youtube.com/embed/lk5_OSsawz4", YT),
        ("https://www.youtube-nocookie.com/embed/lk5_OSsawz4", YT),
        # already-embed: idempotent (with and without start)
        (YT, YT),
        (YT + "?start=90", YT + "?start=90"),
        # scheme-less and scheme-relative paste
        ("youtu.be/lk5_OSsawz4", YT),
        ("www.youtube.com/watch?v=lk5_OSsawz4", YT),
        ("//youtu.be/lk5_OSsawz4", YT),
        # mixed-case host
        ("https://YOUTU.BE/lk5_OSsawz4", YT),
        ("https://WWW.YouTube.com/watch?v=lk5_OSsawz4", YT),
        # start time, all forms
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=90", YT + "?start=90"),
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=90s", YT + "?start=90"),
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=1m30s", YT + "?start=90"),
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&start=120", YT + "?start=120"),
        ("https://youtu.be/lk5_OSsawz4?t=90", YT + "?start=90"),  # share-link start
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=2h", YT + "?start=7200"),
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=90m", YT + "?start=5400"),
        # query-value selection
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=&start=90", YT + "?start=90"),
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=10&t=90", YT + "?start=10"),
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=s&start=90", YT + "?start=90"),
        ("https://www.youtube.com/watch?v=lk5_OSsawz4&t=0", YT),  # start=0 dropped
        # empty input
        ("", ""),
        ("   ", ""),
        # unrecognized host: stripped input returned unchanged (no lowercasing)
        ("https://www.geogebra.org/m/abc", "https://www.geogebra.org/m/abc"),
        ("https://Www.GeoGebra.org/m/abc", "https://Www.GeoGebra.org/m/abc"),
    ],
)
def test_canonicalize_youtube_and_passthrough(raw, expected):
    assert canonicalize_video_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/watch",          # no v=
        "https://www.youtube.com/watch?v=",        # empty v=
        "https://youtu.be/playlist",               # segment fails 11-char regex
        "https://youtu.be/watch",
        "https://youtu.be/aaaaaaaaaaaa",           # 12 chars → reject
        "https://youtu.be/",                       # empty first segment
        "https://youtu.be",                        # bare host, no path
        "https://youtu.be//lk5_OSsawz4",           # leading empty segment
        "https://www.youtube.com/channel/UCabc",   # non-watch/embed path
    ],
)
def test_canonicalize_youtube_rejects(raw):
    with pytest.raises(ValidationError) as ei:
        canonicalize_video_url(raw)
    assert "YouTube" in str(ei.value)


def test_canonicalize_accepts_clean_11_char_id():
    # boundary: exactly 11 chars accepted
    assert canonicalize_video_url("https://youtu.be/abcdefghijk") == (
        "https://www.youtube.com/embed/abcdefghijk"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_video_url.py -v`
Expected: FAIL — `ImportError: cannot import name 'canonicalize_video_url'`.

- [ ] **Step 3: Write minimal implementation**

Edit `courses/video_url.py` — add imports at the top (below the docstring) and append the helpers + function:

```python
from urllib.parse import parse_qs, urlsplit

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
```

Use `gettext_lazy` (NOT `gettext`): `_NO_VIDEO_MSG` is built at **module import time**, when no request locale is active. Non-lazy `gettext` would resolve it to English once, permanently, and the Polish `.po` entry from Task 5 would never apply. The lazy proxy defers resolution; `_NO_VIDEO_MSG % {"provider": ...}` at the call site returns a lazy string that renders under the request locale, and `str(...)` in the reject tests evaluates it under the default (English) locale, so the `"YouTube"`/`"Vimeo"` substring assertions still hold. Every other `courses/` module that holds module-scope translatable strings uses `gettext_lazy`; match that.

Add after `_parse_duration`:

```python
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
    to_parse = text if _SCHEME_RE.match(text) else "https://" + text
    parts = urlsplit(to_parse)
    host = parts.hostname or ""  # urlsplit lowercases hostname, strips port/userinfo
    if _is_youtube(host):
        vid = _youtube_id(host, parts.path, parts.query)
        if vid is None:
            raise ValidationError(_NO_VIDEO_MSG % {"provider": "YouTube"})
        out = "https://www.youtube.com/embed/" + vid
        start = _youtube_start(parts.query)
        if start > 0:
            out += "?start=%d" % start
        return out
    # Vimeo branch inserted here in Task 3.
    return text  # unrecognized host → stripped input unchanged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_video_url.py -v`
Expected: PASS (all YouTube, reject, idempotency, pass-through, empty cases).

- [ ] **Step 5: Lint and commit**

```bash
ruff format courses/video_url.py tests/test_video_url.py
ruff check courses/video_url.py tests/test_video_url.py
git add courses/video_url.py tests/test_video_url.py
git commit -m "feat(video): canonicalize YouTube links to embed URLs"
```

---

### Task 3: `canonicalize_video_url` — Vimeo branch

**Files:**
- Modify: `courses/video_url.py`
- Test: `tests/test_video_url.py`

**Interfaces:**
- Consumes: `_parse_duration`, `_first`, `_NO_VIDEO_MSG` (Tasks 1–2).
- Produces: Vimeo handling inside `canonicalize_video_url`. `vimeo.com/<ID>` and `player.vimeo.com/video/<ID>` → `https://player.vimeo.com/video/<ID>`; unlisted `…/<ID>/<hash>` or `?h=<hash>` → `?h=<hash>` preserved; start from the `#t=` fragment only → `#t=<sec>s`; combined order `?h=<hash>#t=<sec>s`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_video_url.py`:

```python
V = "https://player.vimeo.com/video/123456"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://vimeo.com/123456", V),
        ("https://www.vimeo.com/123456", V),
        (V, V),  # idempotent
        ("vimeo.com/123456", V),  # scheme-less
        ("https://vimeo.com/channels/staffpicks/123456", V),
        # unlisted: privacy hash preserved
        ("https://vimeo.com/123456/abc123", V + "?h=abc123"),
        ("https://player.vimeo.com/video/123456?h=abc123", V + "?h=abc123"),
        ("https://player.vimeo.com/video/123456/abc123", V + "?h=abc123"),
        (V + "?h=abc123", V + "?h=abc123"),  # idempotent
        # hash containing - / _ is preserved (not dropped)
        ("https://vimeo.com/123456/ab-c_1", V + "?h=ab-c_1"),
        # start from fragment only; query t ignored
        ("https://vimeo.com/123456#t=90s", V + "#t=90s"),
        ("https://vimeo.com/123456#t=1m30s", V + "#t=90s"),  # normalized
        ("https://vimeo.com/123456?t=90", V),  # query t ignored
        # hash + start ordering and idempotency
        ("https://vimeo.com/123456/abc123#t=90s", V + "?h=abc123#t=90s"),
        (V + "?h=abc123#t=90s", V + "?h=abc123#t=90s"),  # idempotent
        # extra path segments are NOT a hash
        ("https://vimeo.com/123456/review/xyz", V),
    ],
)
def test_canonicalize_vimeo(raw, expected):
    assert canonicalize_video_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "https://vimeo.com/user12345",   # non-numeric, no ID
        "https://vimeo.com/channels/staffpicks",  # no numeric segment
    ],
)
def test_canonicalize_vimeo_rejects(raw):
    with pytest.raises(ValidationError) as ei:
        canonicalize_video_url(raw)
    assert "Vimeo" in str(ei.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_video_url.py::test_canonicalize_vimeo -v`
Expected: FAIL — Vimeo URLs currently hit pass-through and return the input unchanged (assert mismatch); the reject cases raise nothing.

- [ ] **Step 3: Write minimal implementation**

Edit `courses/video_url.py`. Add the Vimeo regexes/helpers after `_youtube_start`:

```python
_VIMEO_ID = re.compile(r"^\d+$")
_VIMEO_HASH = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _is_vimeo(host):
    return host in ("vimeo.com", "www.vimeo.com", "player.vimeo.com")


def _vimeo_id_hash(host, path, query):
    """Return (id, hash_or_None), or (None, None) if no numeric ID is found."""
    segs = path.split("/")[1:]
    if host == "player.vimeo.com" and segs and segs[0] == "video":
        segs = segs[1:]
    id_idx = next((i for i, s in enumerate(segs) if _VIMEO_ID.match(s)), None)
    if id_idx is None:
        return None, None
    vid = segs[id_idx]
    h = _first(query, "h")
    if h and _VIMEO_HASH.match(h):
        return vid, h
    rest = segs[id_idx + 1:]
    if len(rest) == 1 and _VIMEO_HASH.match(rest[0]):
        return vid, rest[0]
    return vid, None


def _vimeo_start(fragment):
    """Seconds from a #t=<...> fragment, else 0. Query t is ignored for Vimeo."""
    if fragment.startswith("t="):
        return _parse_duration(fragment[2:])
    return 0
```

Then replace the `# Vimeo branch inserted here in Task 3.` comment line in `canonicalize_video_url` with:

```python
    if _is_vimeo(host):
        vid, hash_ = _vimeo_id_hash(host, parts.path, parts.query)
        if vid is None:
            raise ValidationError(_NO_VIDEO_MSG % {"provider": "Vimeo"})
        out = "https://player.vimeo.com/video/" + vid
        if hash_:
            out += "?h=" + hash_
        start = _vimeo_start(parts.fragment)
        if start > 0:
            out += "#t=%ds" % start
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_video_url.py -v`
Expected: PASS (all YouTube + Vimeo + reject + idempotency cases).

- [ ] **Step 5: Lint and commit**

```bash
ruff format courses/video_url.py tests/test_video_url.py
ruff check courses/video_url.py tests/test_video_url.py
git add courses/video_url.py tests/test_video_url.py
git commit -m "feat(video): canonicalize Vimeo links incl unlisted privacy hash"
```

---

### Task 4: Wire the canonicalizer into `VideoElementForm`

**Files:**
- Modify: `courses/element_forms.py` (`VideoElementForm`, lines ~88-110; import near line 26)
- Test: `tests/test_courses_elements.py`

**Interfaces:**
- Consumes: `canonicalize_video_url` (Tasks 2–3).
- Produces: a `VideoElementForm` whose `url` field accepts free text, normalizes via `clean_url`, and whose guarded `clean()` shows only the precise URL error on a bad paste (no spurious XOR noise) while preserving the url/media XOR for valid input.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_courses_elements.py`. (Note: the url-only tests construct the
form without `course=`, while the media tests pass `course=course`. This is
intentional — `_CourseScopedMediaForm.__init__` accepts `course=None` and only
filters the media queryset when a course is given, which is irrelevant when no media
is submitted. Not an oversight.)

```python
@pytest.mark.django_db
def test_video_form_normalizes_schemeless_youtu_be():
    from courses.element_forms import VideoElementForm

    form = VideoElementForm(data={"url": "youtu.be/lk5_OSsawz4"})
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.url == "https://www.youtube.com/embed/lk5_OSsawz4"


@pytest.mark.django_db
def test_video_form_normalizes_watch_url():
    from courses.element_forms import VideoElementForm

    form = VideoElementForm(
        data={"url": "https://www.youtube.com/watch?v=lk5_OSsawz4&t=90"}
    )
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.url == "https://www.youtube.com/embed/lk5_OSsawz4?start=90"


@pytest.mark.django_db
def test_video_form_rejects_playlist_with_url_error_only():
    from courses.element_forms import VideoElementForm

    form = VideoElementForm(data={"url": "https://www.youtube.com/playlist?list=PL1"})
    assert not form.is_valid()
    assert "url" in form.errors
    # the precise message pre-empts the XOR — no confusing non-field error
    assert "__all__" not in form.errors


@pytest.mark.django_db
def test_video_form_rejected_paste_survives_rerender():
    from courses.element_forms import VideoElementForm

    raw = "https://www.youtube.com/playlist?list=PL1"
    form = VideoElementForm(data={"url": raw})
    assert not form.is_valid()
    assert form["url"].value() == raw


@pytest.mark.django_db
def test_video_form_empty_url_plus_media_is_valid():
    from courses.element_forms import VideoElementForm
    from courses.models import MediaAsset
    from tests.factories import CourseFactory

    course = CourseFactory()
    asset = MediaAsset.objects.create(
        course=course,
        kind="video",
        file="courses/media/x/v.mp4",
        original_filename="v.mp4",
    )
    form = VideoElementForm(
        data={"url": "", "media": str(asset.pk)}, course=course
    )
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_video_form_valid_url_plus_media_trips_xor():
    from courses.element_forms import VideoElementForm
    from courses.models import MediaAsset
    from tests.factories import CourseFactory

    course = CourseFactory()
    asset = MediaAsset.objects.create(
        course=course,
        kind="video",
        file="courses/media/x/v.mp4",
        original_filename="v.mp4",
    )
    form = VideoElementForm(
        data={"url": "youtu.be/lk5_OSsawz4", "media": str(asset.pk)}, course=course
    )
    assert not form.is_valid()
    assert "__all__" in form.errors  # non-field XOR error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_courses_elements.py -k video_form -v`
Expected: FAIL — `test_video_form_normalizes_schemeless_youtu_be` fails because the current `forms.URLField`-derived field rejects `youtu.be/lk5_OSsawz4` as an invalid URL (and no normalization occurs).

- [ ] **Step 3: Write minimal implementation**

In `courses/element_forms.py`, add the import near the other `courses` imports (e.g. below line 6 `from courses.embed import extract_embed_url`):

```python
from courses.video_url import canonicalize_video_url
```

Replace the existing `VideoElementForm` (currently lines ~88-110) with:

```python
class VideoElementForm(_CourseScopedMediaForm):
    media_kind = "video"

    # Override the model's URLField as free-text so the raw pasted value
    # (scheme-less, with tracking params, etc.) reaches clean_url intact;
    # canonicalize_video_url is the single parser, and its normalized output is
    # re-validated by validate_embed_url in VideoElement.clean(). Mirrors the
    # IframeElementForm precedent. required=False so an empty paste (valid when a
    # media file is used) is not a required-field error pre-empting the XOR.
    url = forms.CharField(required=False)

    class Meta:
        model = VideoElement
        fields = ["url", "media"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["url"].required = False
        self.fields["media"].required = False

    def clean_url(self):
        return canonicalize_video_url(self.cleaned_data.get("url", ""))

    def clean(self):
        cleaned = super().clean()
        # A clean_url ValidationError already reported a precise message; don't
        # stack the url/media XOR noise on top of it.
        if "url" in self.errors:
            return cleaned
        instance = self.instance
        instance.url = cleaned.get("url", "")
        instance.media = cleaned.get("media")
        try:
            instance.clean()
        except forms.ValidationError as e:
            self.add_error(None, e)
        return cleaned
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_courses_elements.py -k video -v`
Expected: PASS (new `video_form` tests plus the existing `test_video_xor_*` / `test_video_file_extension_allowlist` still green).

- [ ] **Step 5: Lint and commit**

```bash
ruff format courses/element_forms.py tests/test_courses_elements.py
ruff check courses/element_forms.py tests/test_courses_elements.py
git add courses/element_forms.py tests/test_courses_elements.py
git commit -m "feat(video): normalize pasted URLs in VideoElementForm"
```

---

### Task 5: Editor template — text input, label, help text, i18n

**Files:**
- Modify: `templates/courses/manage/editor/_edit_video.html`
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: `tests/test_courses_elements.py`

**Interfaces:**
- Consumes: `VideoElementForm` (Task 4) for the render test.
- Produces: a hand-rolled URL input with `type="text"`, a "YouTube / Vimeo link" label, help text, all translatable; Polish translations for the two template strings and the reject message.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_courses_elements.py`:

```python
@pytest.mark.django_db
def test_edit_video_template_uses_text_input_and_help():
    from django.template.loader import render_to_string

    from courses.element_forms import VideoElementForm

    html = render_to_string(
        "courses/manage/editor/_edit_video.html",
        {"form": VideoElementForm()},
    )
    # the URL input must be free-text so the browser doesn't block scheme-less paste
    assert 'name="url"' in html
    assert 'type="text"' in html
    assert 'type="url"' not in html
    # author-facing guidance is present
    assert "Share button" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_courses_elements.py::test_edit_video_template_uses_text_input_and_help -v`
Expected: FAIL — the template still renders `type="url"` and has no help text containing "Share button".

- [ ] **Step 3: Edit the template**

The current `templates/courses/manage/editor/_edit_video.html` has (lines 7-9):

```html
  <label data-video-pane="url">{% trans "URL" %}
    <input type="url" name="url" value="{{ form.url.value|default:'' }}">
  </label>
```

Replace those three lines with:

```html
  <label data-video-pane="url">{% trans "YouTube / Vimeo link" %}
    <input type="text" name="url" value="{{ form.url.value|default:'' }}">
    <small class="field-help">{% trans "Paste any link — the address bar, the Share button, or an embed URL all work." %}</small>
  </label>
```

(Only `type` changes on the input — `name="url"` and the `value=` binding stay so the POST field name and rejected-paste re-population are unchanged.)

- [ ] **Step 4: Run the template test to verify it passes**

Run: `pytest tests/test_courses_elements.py::test_edit_video_template_uses_text_input_and_help -v`
Expected: PASS.

- [ ] **Step 5: Add Polish translations**

Add these three entries to `locale/pl/LC_MESSAGES/django.po` (append near the other `courses` entries; keep `msgid` text byte-identical to the source strings). **The provider message carries `%(provider)s`, so it MUST be preceded by a `#, python-format` flag line** — every existing `%(…)s` entry in this `.po` has it, and `msgfmt --check` (run by `compilemessages`) validates placeholder consistency only when the entry is flagged:

```po
msgid "YouTube / Vimeo link"
msgstr "Link YouTube / Vimeo"

msgid "Paste any link — the address bar, the Share button, or an embed URL all work."
msgstr "Wklej dowolny link — pasek adresu, przycisk Udostępnij lub adres osadzenia, wszystkie działają."

#, python-format
msgid ""
"That looks like a %(provider)s link but we couldn't find a single video in "
"it — paste the link to one video."
msgstr ""
"To wygląda na link %(provider)s, ale nie znaleźliśmy w nim pojedynczego "
"filmu — wklej link do jednego filmu."
```

The first two entries have no placeholders, so no flag is needed for them.

The most robust path is to regenerate the catalog with `python manage.py makemessages -l pl` (which writes byte-exact `msgid`s, including any multi-line wrapping, and adds source-reference comments) and then fill in the three `msgstr`s, rather than hand-appending — if `xgettext`/`msgfmt` is available.

- [ ] **Step 6: Compile the catalog (conditional)**

```bash
python manage.py compilemessages -l pl
```

`compilemessages` needs the GNU `msgfmt` binary (part of gettext), which is often absent on a Windows dev box (this env is win32). Two cases — do NOT bury this in prose, decide explicitly:
- **`msgfmt` available:** run the command; confirm `git status` shows `locale/pl/LC_MESSAGES/django.mo` as modified (compiled fresh). Stage the `.mo` in Step 8.
- **`msgfmt` unavailable:** do NOT stage a stale `.mo`. Stage only the `.po`, change the Step 8 commit message to `feat(video): text URL input, paste-any-link help, pl .po (compile pending)`, and record "compile pl `.mo` (needs gettext/msgfmt)" as an explicit tracked follow-up (e.g. a checklist note in the PR description), not a silent omission.

- [ ] **Step 7: Run the full suite**

Run: `pytest -q`
Expected: PASS (whole suite green; no regressions).

- [ ] **Step 8: Lint and commit**

`ruff` first, then stage per the Step 6 `.mo` decision (the `git add` below assumes the `msgfmt`-available case; drop `django.mo` if it was not compiled):

```bash
ruff format tests/test_courses_elements.py
ruff check tests/test_courses_elements.py
git add templates/courses/manage/editor/_edit_video.html tests/test_courses_elements.py locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "feat(video): text URL input, paste-any-link help, pl i18n"
```

---

## Manual verification (DoD)

After all tasks, run the dev server and, in a course's content editor, add a video element and confirm:

- Paste `https://www.youtube.com/watch?v=lk5_OSsawz4&source_ve_path=MTc4` → saves and plays.
- Paste `https://youtu.be/lk5_OSsawz4?si=xMBEVds6TCuZdtQO` → saves as `…/embed/lk5_OSsawz4` and plays.
- Paste `https://www.youtube.com/watch?v=lk5_OSsawz4&t=90` (and `youtu.be/lk5_OSsawz4?t=90`) → saves as `…/embed/lk5_OSsawz4?start=90` and the player starts at 1:30.
- Paste a playlist URL → inline field error "couldn't find a single video", and the pasted text stays in the field so it can be fixed.
- Switch the locale to Polish → the label, help text, and reject message appear in Polish.

---

## Self-Review

**Spec coverage:**
- Scheme-less paste + https prepend → Task 2 (`_SCHEME_RE`, `to_parse`). ✓
- Host-gated dispatch, suffix matching, `.hostname` → Task 2 (`_is_youtube`, `_youtube_id`). ✓
- Exact ID regexes (YouTube `{11}`, Vimeo `\d+`), empty/oversize reject → Tasks 2/3. ✓
- Duration grammar + edges → Task 1; YouTube `t`→`start` fall-through, first occurrence, empty/junk, `start=0` → Task 2 (`_youtube_start`). ✓
- Vimeo `#t=` fragment only, query `t` ignored → Task 3 (`_vimeo_start`). ✓
- Vimeo unlisted hash: query `h` precedence, bounded single trailing segment, `[A-Za-z0-9_-]{1,40}`, `?h=…#t=…s` order, idempotency → Task 3. ✓
- Pass-through byte-for-byte (stripped, no lowercasing) + empty → Task 2 (`return text`, `return ""`). ✓
- Provider name via `%(provider)s`, bound at branch → Tasks 2/3 (`_NO_VIDEO_MSG`). ✓
- CharField override + `required=False` + `clean_url` + guarded `clean()` (XOR precedence, bad-url+media, raw re-render) → Task 4. ✓
- Template `type="url"`→`type="text"`, label, help, `{% trans %}` + pl `.po` + compile/msgfmt note, single-line comment discipline → Task 5. ✓
- No model/migration changes → confirmed; no migration task. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to" — every code step shows full code. ✓

**Type consistency:** `_parse_duration`, `_first(query, key)`, `_youtube_id(host, path, query)`, `_youtube_start(query)`, `_is_youtube/_is_vimeo(host)`, `_vimeo_id_hash(host, path, query) -> (id, hash|None)`, `_vimeo_start(fragment)`, `canonicalize_video_url(raw) -> str` — names/signatures match across Tasks 2–4 and the `VideoElementForm.clean_url` call site. ✓
