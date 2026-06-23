# Video URL normalization — design

**Date:** 2026-06-23
**Status:** approved (brainstorm), pending spec-review
**Branch:** `fix/video-url-normalization` (off `master`)

## Problem

A content author adds a video element by pasting a YouTube (or Vimeo) URL. Only
the iframe `src` form actually plays:

- works in embed: `https://www.youtube.com/embed/lk5_OSsawz4`
- browser address bar: `https://www.youtube.com/watch?v=lk5_OSsawz4&source_ve_path=MTc4NDI0`
- Share button: `https://youtu.be/lk5_OSsawz4?si=xMBEVds6TCuZdtQO`

None of the forms a non-tech user naturally copies is the embed form. Today the
video element's `url` field only runs `validate_embed_url` (https + allow-list,
**no normalization**), and because `youtube.com` / `youtu.be` are themselves on
the allow-list, a pasted watch/share URL **passes validation but never plays**
(YouTube refuses to render `watch?v=…` inside an iframe). The author has no signal
that the embed is broken until a student sees a blank player.

Goal: let an author paste **any** common YouTube or Vimeo link and have it saved
as a working embed URL — or be rejected at author time with a clear message.

## Scope

In scope (confirmed with user):

- **YouTube**, all common forms → `https://www.youtube.com/embed/<ID>`
- **Vimeo**, common forms → `https://player.vimeo.com/video/<ID>`
- **Preserve start time** from the pasted link
- Reject a recognized-host URL with **no extractable video ID** with a friendly message

Out of scope:

- The `IframeElement` path (`courses/embed.py`) — that is `<iframe>`-snippet → `src`
  extraction for GeoGebra/Vimeo-iframe and is a separate concern. Untouched.
- Providers other than YouTube/Vimeo. Any unrecognized host passes through
  unchanged and is judged by the existing allow-list check (backward compatible).
- Playlist embedding, channel pages, model/migration changes.

## Approach

Chosen: **a new pure module `courses/video_url.py`** exposing
`canonicalize_video_url(raw) -> str`, called from a new `VideoElementForm.clean_url()`.
Isolated, unit-testable, mirrors the existing `courses/embed.py` pattern. (Rejected:
folding into `embed.py` — mixes two concerns; client-side JS — no server guarantee,
hardest to test, worst for the exact non-tech user we are helping.)

### `canonicalize_video_url(raw) -> str`

Pure function. Returns a normalized https embed URL, or raises
`django.core.exceptions.ValidationError`.

1. **Trim.** Empty / whitespace → return `""`. (The video element allows an empty
   URL when an uploaded media file is used instead; the url/media XOR stays in
   `VideoElement.clean()`.)
2. **Supply a scheme, then parse.** A non-tech user routinely pastes a
   scheme-less link (`youtu.be/lk5_OSsawz4`, `www.youtube.com/watch?v=…`,
   `vimeo.com/123456`). `urlsplit("youtu.be/ID")` puts the whole thing in `.path`
   and leaves `.hostname` empty, so host-dispatch would fail and the URL would fall
   through to pass-through → allow-list reject — silently rejecting the exact user
   this feature exists to help. Therefore: if `urlsplit(text).scheme` is empty (or
   the input does not start with a `scheme://`), prepend `https://` and re-parse.
   Inputs that already carry a scheme (`http://`, `https://`) keep it; a non-https
   scheme on a *recognized* host is upgraded to https by the rebuild, and on an
   *unrecognized* host is left for the allow-list to reject. Then lower-case the
   host for dispatch.
3. **Dispatch on host (two explicit branches; extraction is host-gated — never
   apply one host's path rule to another host).** The video ID is accepted only if
   it matches `^[A-Za-z0-9_-]{11}$` (YouTube) or `^\d+$` (Vimeo); a candidate
   segment that fails its shape is treated as **no extractable ID** → reject (step
   5), so `youtu.be/playlist`, `youtu.be/watch`, etc. route to the friendly error
   instead of producing a dead embed.
   - **YouTube hosts:** `youtube.com`, `www.youtube.com`, `m.youtube.com`,
     `music.youtube.com`, `youtube-nocookie.com`, `youtu.be`.
     - If host is `youtu.be`: ID = the **first** path segment, validated against the
       YouTube ID regex. No other rule applies to `youtu.be`.
     - Otherwise (the `*.youtube.com` family): try, in order, `/watch?v=<ID>` (query
       param `v`); `/embed/<ID>`, `/shorts/<ID>`, `/live/<ID>`, `/v/<ID>` (ID =
       second path segment). The first-path-segment `youtu.be` rule is **never**
       applied here.
     Output: `https://www.youtube.com/embed/<ID>` (+ start, see below).
   - **Vimeo hosts:** `vimeo.com`, `www.vimeo.com`, `player.vimeo.com`.
     Extract the numeric ID (validated against `^\d+$`) from:
     - `player.vimeo.com/video/<ID>`
     - `vimeo.com/<ID>` (ID = first **all-digit** path segment, so
       `vimeo.com/channels/staffpicks/<ID>` and `vimeo.com/<ID>/<hash>` both work;
       a non-numeric path like `vimeo.com/user12345` yields no ID → reject)
     Output: `https://player.vimeo.com/video/<ID>` (+ start, see below).
4. **Start time.** A single duration parser is shared by both providers. Its
   grammar is pinned (not by-example) so two implementers can't diverge — a value
   is parseable iff it matches **either** `^\d+$` (bare seconds) **or**
   `^(?=\d+[hms])(\d+h)?(\d+m)?(\d+s)?$` (at least one of h/m/s, each component
   optional but order fixed h→m→s, each a run of digits). Total seconds = h·3600 +
   m·60 + s. Components may exceed their "natural" range (`90m` = 5400s is fine).
   Anything else (`1m30sxyz`, bare `s`, `1s30m` out-of-order, empty) → unparseable.
   - YouTube: read query param `t`, else `start`. Parse per the grammar above; if
     the result is > 0 append `?start=<seconds>`. The `start` form on an
     already-embed URL is read the same way, so `…/embed/ID?start=90` round-trips.
   - Vimeo: read **only** the fragment `#t=<...>` (e.g. `#t=90s`, `#t=1m30s`); a
     Vimeo query `t` is ignored. Parse per the same grammar; if > 0 append
     `#t=<seconds>s` (always the bare-seconds form, so `#t=1m30s` normalizes to
     `#t=90s`).
   - Unparseable / zero / absent start → omit (no error; the link itself is fine).
5. **Recognized host but no extractable ID** (bare `/watch`, `/playlist`,
   `/channel/…`, `vimeo.com/user…`, or any segment failing the ID-shape check) →
   raise `ValidationError`. The provider name in the message is filled from the
   matched host branch (YouTube vs. Vimeo), via a gettext-friendly
   `%(provider)s`-interpolated string (one translatable template, not a literal
   `{YouTube|Vimeo}` alternation), e.g.: *"That looks like a %(provider)s link but
   we couldn't find a single video in it — paste the link to one video."*
6. **Unrecognized host** → return the input **byte-for-byte** (only `.strip()`
   applied; do **not** lowercase or otherwise normalize it — `validate_embed_url`
   does its own host case-folding downstream, so altering the pass-through value
   risks breaking a URL that works today). The existing `validate_embed_url`
   allow-list check (run later in `VideoElement.clean()`) decides accept/reject.
   Backward-compatible: anything that works today still works.

Because every recognized output is **rebuilt from scratch** (`scheme://host/path`
+ only the `start`/`t` we chose to keep), all tracking cruft — `?si=…`,
`&list=…`, `&source_ve_path=…`, `&feature=…` — is dropped automatically.

The recognizer's **input** host set is deliberately wider than
`ALLOWED_EMBED_DOMAINS` (which lists `www.youtube.com`, `youtube.com`, `youtu.be`,
`player.vimeo.com`, `geogebra.org` — but not `m.youtube.com`, `music.youtube.com`,
`youtube-nocookie.com`, `vimeo.com`, or `www.vimeo.com`). This is intentional and
needs **no allow-list change**: every recognized input rebuilds to `www.youtube.com`
or `player.vimeo.com`, both of which are on the allow-list, so `validate_embed_url`
always sees a listed host on the recognized path.

### Integration

`courses/element_forms.py`, `VideoElementForm`:

```python
def clean_url(self):
    return canonicalize_video_url(self.cleaned_data.get("url", ""))
```

`clean_url` runs before the existing `clean()` (Django runs all `clean_<field>`
methods in `_clean_fields` before the form-level `clean()`), which already sets
`instance.url = cleaned.get("url", "")` and calls `instance.clean()`. The
normalized `www.youtube.com` / `player.vimeo.com` URL then passes the existing
`validate_embed_url` allow-list with no further change. **No model or migration
changes.**

**Error precedence with the url/media XOR:** a URL-shape error from `clean_url`
surfaces as a `url` **field** error and pre-empts the XOR check — when `clean_url`
raises, `cleaned_data` has no `url`, so the recognized-host-no-ID case fails on the
field before `VideoElement.clean()`'s "exactly one of url/media" (non-field) rule is
reached. A *valid* URL supplied together with a media file passes `clean_url`, then
trips the XOR error as today. This ordering is a guaranteed property of Django form
cleaning; the plan should pin it with a test so a future refactor can't silently
reorder it.

Editor template `templates/courses/manage/editor/_edit_video.html`: relabel the
field to *"YouTube / Vimeo link"* and add short help text ("Paste any link — the
address bar, the Share button, or an embed URL all work."), with `{% trans %}` +
Polish `.po` entries. Cosmetic; no logic in the template.

## Error handling

- Empty URL: allowed (`""`), media-XOR enforced downstream as today.
- Recognized host, no ID: rejected at author time with the friendly message above,
  surfaced as a `form.url` field error (existing template already renders
  `form.url.errors`).
- Unrecognized host: unchanged behavior (allow-list decides).
- Malformed input that `urlsplit` tolerates (it rarely raises): treated as
  unrecognized host → pass-through → allow-list rejects non-https / non-listed.

## Testing

Unit — `tests/test_video_url.py` against `canonicalize_video_url`:

- `watch?v=ID` + tracking params → `…/embed/ID`
- `youtu.be/ID?si=…` → `…/embed/ID`
- `shorts/ID`, `live/ID`, `/v/ID`, `m.youtube.com/watch?v=ID` → `…/embed/ID`
- **scheme-less** input: `youtu.be/ID`, `www.youtube.com/watch?v=ID`,
  `vimeo.com/123456` (no `https://`) → correct embed (regression-prone; from C1)
- **mixed-case host**: `YOUTU.BE/ID`, `WWW.YouTube.com/watch?v=ID` → correct embed
- already-embed `…/embed/ID` → unchanged (idempotent)
- already-embed **with start** `…/embed/ID?start=90` → unchanged (idempotent)
- start time: `&t=90`, `&t=90s`, `&t=1m30s`, `&start=120` → `?start=<n>`
- duration grammar edges: `&t=2h` → `?start=7200`, `&t=90m` → `?start=5400`;
  unparseable `&t=1m30sxyz`, `&t=s`, `&t=1s30m` → start omitted (no error)
- ID-shape reject: `youtu.be/playlist`, `youtu.be/watch` (segment fails the
  11-char ID regex) → `ValidationError` (from C2)
- `vimeo.com/123456` → `player.vimeo.com/video/123456`
- `player.vimeo.com/video/123456` → unchanged (idempotent)
- vimeo fragment: `#t=90s` → `#t=90s` (idempotent) AND `#t=1m30s` → `#t=90s`
  (normalized — distinct case, from I3)
- vimeo query `t` is ignored: `vimeo.com/123456?t=90` → no `#t=` appended
- vimeo `vimeo.com/channels/x/123456` → `…/video/123456`
- reject: `youtube.com/playlist?list=…`, bare `youtube.com/watch`, `vimeo.com/user12`
- empty string → `""`
- pass-through byte-for-byte: `https://www.geogebra.org/m/abc` and mixed-case
  `https://Www.GeoGebra.org/m/abc` each returned exactly as given (no lowercasing)

Form-level — extend `tests/test_courses_elements.py` (or `test_element_add_save.py`):

- `VideoElementForm` with a pasted `watch?v=…` URL is valid and saves
  `instance.url == "https://www.youtube.com/embed/<ID>"`
- `VideoElementForm` with a playlist URL is invalid with a `url` field error
- `VideoElementForm` with a **valid URL + a media file** is invalid with the
  non-field XOR error (URL passed `clean_url`, XOR then fired — pins the precedence
  from I5)

## DoD

- Full test suite green; `ruff check` and `ruff format --check` clean.
- Manual: paste each of the three real URLs from the problem report into the video
  editor → all save as `…/embed/lk5_OSsawz4` and play.
