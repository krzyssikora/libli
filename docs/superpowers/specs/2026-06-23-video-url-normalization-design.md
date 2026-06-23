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
2. **Parse** with `urllib.parse.urlsplit`. Lower-case the host.
3. **Dispatch on host:**
   - **YouTube hosts:** `youtube.com`, `www.youtube.com`, `m.youtube.com`,
     `music.youtube.com`, `youtube-nocookie.com`, `youtu.be`.
     Extract the 11-char video ID from, in order:
     - `youtu.be/<ID>` (ID = first path segment)
     - `/watch?v=<ID>` (query param `v`)
     - `/embed/<ID>`, `/shorts/<ID>`, `/live/<ID>` (ID = second path segment)
     - `/v/<ID>` (legacy)
     Output: `https://www.youtube.com/embed/<ID>` (+ start, see below).
   - **Vimeo hosts:** `vimeo.com`, `www.vimeo.com`, `player.vimeo.com`.
     Extract the numeric ID from:
     - `player.vimeo.com/video/<ID>`
     - `vimeo.com/<ID>` (ID = first **all-digit** path segment, so
       `vimeo.com/channels/staffpicks/<ID>` and `vimeo.com/<ID>/<hash>` both work;
       a non-numeric-only path like `vimeo.com/user12345` yields no ID → reject)
     Output: `https://player.vimeo.com/video/<ID>` (+ start, see below).
4. **Start time.**
   - YouTube: read query `t`, else `start`. Accept integer seconds (`90`),
     `90s`, and the colon-free duration form `1h2m3s` / `1m30s`. Convert to total
     seconds; if > 0 append `?start=<seconds>`.
   - Vimeo: read the fragment `#t=<...>` (e.g. `#t=90s` or `#t=1m30s`), same parse;
     if > 0 append `#t=<seconds>s`.
   - Unparseable / zero / absent start → omit (no error; the link itself is fine).
5. **Recognized host but no extractable ID** (bare `/watch`, `/playlist`,
   `/channel/…`, `vimeo.com/user…`) → raise `ValidationError`:
   *"That looks like a {YouTube|Vimeo} link but we couldn't find a single video in
   it — paste the link to one video."*
6. **Unrecognized host** → return `raw.strip()` unchanged. The existing
   `validate_embed_url` allow-list check (run later in `VideoElement.clean()`)
   decides accept/reject. Backward-compatible: anything that works today still works.

Because every recognized output is **rebuilt from scratch** (`scheme://host/path`
+ only the `start`/`t` we chose to keep), all tracking cruft — `?si=…`,
`&list=…`, `&source_ve_path=…`, `&feature=…` — is dropped automatically.

### Integration

`courses/element_forms.py`, `VideoElementForm`:

```python
def clean_url(self):
    return canonicalize_video_url(self.cleaned_data.get("url", ""))
```

`clean_url` runs before the existing `clean()`, which already sets
`instance.url = cleaned.get("url", "")` and calls `instance.clean()`. The
normalized `www.youtube.com` / `player.vimeo.com` URL then passes the existing
`validate_embed_url` allow-list with no further change. **No model or migration
changes.**

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
- already-embed `…/embed/ID` → unchanged (idempotent)
- start time: `&t=90`, `&t=90s`, `&t=1m30s`, `&start=120` → `?start=<n>`
- `vimeo.com/123456` → `player.vimeo.com/video/123456`
- `player.vimeo.com/video/123456` → unchanged (idempotent)
- vimeo `#t=90s` → `#t=90s`
- vimeo `vimeo.com/channels/x/123456` → `…/video/123456`
- reject: `youtube.com/playlist?list=…`, bare `youtube.com/watch`, `vimeo.com/user12`
- empty string → `""`
- pass-through: `https://www.geogebra.org/m/abc` returned unchanged

Form-level — extend `tests/test_courses_elements.py` (or `test_element_add_save.py`):

- `VideoElementForm` with a pasted `watch?v=…` URL is valid and saves
  `instance.url == "https://www.youtube.com/embed/<ID>"`
- `VideoElementForm` with a playlist URL is invalid with a `url` error

## DoD

- Full test suite green; `ruff check` and `ruff format --check` clean.
- Manual: paste each of the three real URLs from the problem report into the video
  editor → all save as `…/embed/lk5_OSsawz4` and play.
