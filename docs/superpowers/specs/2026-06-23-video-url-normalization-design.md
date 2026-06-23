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
   this feature exists to help. Therefore, the prepend rule is a single
   deterministic test: **prepend `https://` iff the input does not match
   `^[a-zA-Z][a-zA-Z0-9+.-]*://`** (i.e. has no `scheme://` authority prefix), then
   re-parse. This one regex resolves the ambiguous cases: a scheme-relative
   `//youtu.be/ID` (no `scheme://`) gets `https://` prepended and is recognized; a
   `mailto:foo` or Windows-path `C:/x` (no `://`) likewise gets `https://`
   prepended and then resolves to an unrecognized host → pass-through →
   allow-list reject (correct — those are not video links). Inputs that already
   carry a `scheme://` keep it; a non-https scheme on a *recognized* host is
   upgraded to https by the rebuild, and on an *unrecognized* host is left for the
   allow-list to reject. Read the host from `urlsplit(...).hostname` (the stdlib
   already lowercases it and strips any `user:pass@` / `:port`); the explicit
   lowercase is then belt-and-suspenders, not the primary mechanism.
3. **Dispatch on host (two explicit branches; extraction is host-gated — never
   apply one host's path rule to another host).** The video ID is accepted only if
   it matches `^[A-Za-z0-9_-]{11}$` (YouTube) or `^\d+$` (Vimeo); a candidate
   segment that fails its shape is treated as **no extractable ID** → reject (step
   5), so `youtu.be/playlist`, `youtu.be/watch`, etc. route to the friendly error
   instead of producing a dead embed.
   - **YouTube hosts** — host equals `youtu.be`, or equals/ends-in
     `.youtube.com` (covers `www.`/`m.`/`music.youtube.com`), or equals/ends-in
     `.youtube-nocookie.com` plus the bare `youtube-nocookie.com` (covers
     `www.youtube-nocookie.com`). Suffix matching, not a fixed enumeration, so a new
     `*.youtube.com` subdomain is handled without a spec change.
     - If host is `youtu.be`: ID = the **first non-empty** path segment, validated
       against the YouTube ID regex. Bare `youtu.be` / `youtu.be/` (no segment) and a
       leading empty segment from `youtu.be//ID` yield an empty/invalid first segment
       → fail the ID-shape check → reject (step 5). No crash on missing path. (This
       "first-segment only" rule governs **ID extraction**; start-time extraction in
       step 4 still applies to `youtu.be` — see I3 note there.)
     - Otherwise (the youtube.com / youtube-nocookie.com family): the rule is selected
       by **path**, not tried in fallthrough order (`/watch` and `/embed` are mutually
       exclusive paths) — on `/watch`, ID = query param `v` (first occurrence; an
       empty `v=` → no ID → reject); on `/embed/<ID>`, `/shorts/<ID>`, `/live/<ID>`,
       `/v/<ID>`, ID = the second path segment. A path matching none of these → no ID
       → reject. The first-path-segment `youtu.be` rule is **never** applied here.
     Output: `https://www.youtube.com/embed/<ID>` (+ start, see below).
   - **Vimeo hosts:** `vimeo.com`, `www.vimeo.com`, `player.vimeo.com`.
     All path-segment extraction below operates on `urlsplit(...).path` segments —
     `urlsplit` has already split off `.query` and `.fragment`, so the hash regex
     (`^[A-Za-z0-9_-]{1,40}$`, see below) sees a clean segment (never `abc123#t=90s`).
     Extract the numeric ID (validated against `^\d+$`) — and, for unlisted videos,
     the privacy hash — from:
     - `player.vimeo.com/video/<ID>` (optionally `?h=<hash>` or `/video/<ID>/<hash>`)
     - `vimeo.com/<ID>` (ID = first **all-digit** path segment, so
       `vimeo.com/channels/staffpicks/<ID>` works; a non-numeric path like
       `vimeo.com/user12345` yields no ID → reject)
     - `vimeo.com/<ID>/<hash>` — **unlisted video**: `<hash>` is the required privacy
       token.
     **Hash extraction is bounded to avoid mistaking a public-video slug for a hash.**
     The hash is taken from, in precedence order: (a) the query param `h` if present;
     else (b) the **single** path segment **immediately following** the numeric ID,
     and only when it matches `^[A-Za-z0-9_-]{1,40}$` *and* is the last segment (path
     is exactly `…/<ID>/<hash>`). The charset matches the YouTube ID alphabet so a
     hash containing `-`/`_` is preserved rather than silently dropped (which would
     re-create the broken-unlisted-embed failure). A path with extra segments after that
     (`/<ID>/<seg>/<more>`, e.g. a review link) is **not** treated as a hash → ID only.
     Query `h` wins over a trailing path segment when both somehow appear.
     Output: `https://player.vimeo.com/video/<ID>`, **with `?h=<hash>` appended when a
     hash was found** (a bare `/video/<ID>` embed of an unlisted video fails to play —
     exactly the silent-broken-embed this feature prevents). If both a hash and a
     start are present, the order is `?h=<hash>#t=<seconds>s`.
4. **Start time.** A single duration parser is shared by both providers. Its
   grammar is pinned (not by-example) so two implementers can't diverge — a value
   is parseable iff it matches **either** `^\d+$` (bare seconds) **or**
   `^(?=\d+[hms])(\d+h)?(\d+m)?(\d+s)?$` (at least one of h/m/s, each component
   optional but order fixed h→m→s, each a run of digits). Total seconds = h·3600 +
   m·60 + s. Components may exceed their "natural" range (`90m` = 5400s is fine).
   Anything else (`1m30sxyz`, bare `s`, `1s30m` out-of-order, empty) → unparseable.
   - YouTube — **all** YouTube hosts including `youtu.be` (the real Share URL is
     `youtu.be/ID?t=90`; the "first-segment only" rule in step 3 scopes ID
     extraction, not start). Read the query param `t`, else `start`; take the
     **first** occurrence of each (a repeated `?t=10&t=90` uses the first; an empty
     value `?t=` is treated as absent). Resolution order: try `t` first — if `t` is
     absent, empty, **or present-but-unparseable**, fall through to `start`. (So
     `?t=s&start=90` → `start=90`: a junk `t` does not suppress a valid `start`.)
     Parse per the grammar above; if the result is > 0 append `?start=<seconds>`. The
     `start` form on an already-embed URL is read the same way, so
     `…/embed/ID?start=90` round-trips.
   - Vimeo: read **only** the fragment `#t=<...>` (e.g. `#t=90s`, `#t=1m30s`); a
     Vimeo query `t` is ignored. Parse per the same grammar; if > 0 append
     `#t=<seconds>s` (always the bare-seconds form, so `#t=1m30s` normalizes to
     `#t=90s`). See step 3 for ordering when a privacy hash is also present.
   - Unparseable / zero / absent start → omit (no error; the link itself is fine).
     An explicit `start=0` / `t=0` is treated as absent and dropped, so the function
     is **not** strictly idempotent for `start=0` (`…/embed/ID?start=0` → `…/embed/ID`);
     this is intentional and harmless (both start at the beginning).
5. **Recognized host but no extractable ID** (bare `/watch`, `/playlist`,
   `/channel/…`, `vimeo.com/user…`, or any segment failing the ID-shape check) →
   raise `ValidationError`. The provider name is bound to a single local variable
   **at the moment host-dispatch selects the YouTube vs. Vimeo branch** (not
   recomputed per sub-rule), so every reject inside that branch — whichever
   sub-rule failed — carries the correct provider. It is rendered via a
   gettext-friendly `%(provider)s`-interpolated string (one translatable template,
   not a literal `{YouTube|Vimeo}` alternation), e.g.: *"That looks like a
   %(provider)s link but we couldn't find a single video in it — paste the link to
   one video."*
6. **Unrecognized host** → return the **stripped input unchanged** (no further
   normalization — no lowercasing, no rebuild; only the leading/trailing-whitespace
   `.strip()` is applied). `validate_embed_url` does its own host case-folding
   downstream, so altering the pass-through value risks breaking a URL that works
   today. The existing `validate_embed_url`
   allow-list check (run later in `VideoElement.clean()`) decides accept/reject.
   Backward-compatible: anything that works today still works.

Because every recognized output is **rebuilt from scratch** (`scheme://host/path`
+ only the `start`/`t` we chose to keep), all tracking cruft — `?si=…`,
`&list=…`, `&source_ve_path=…`, `&feature=…` — is dropped automatically.

The recognizer's **input** host set is deliberately wider than
`ALLOWED_EMBED_DOMAINS` (whose default in `base.py` is `www.youtube.com`,
`youtube.com`, `youtu.be`, `player.vimeo.com`, `www.geogebra.org`, `geogebra.org`
— but not `m.youtube.com`, `music.youtube.com`, `youtube-nocookie.com`,
`vimeo.com`, or `www.vimeo.com`). This is intentional and needs **no allow-list
change**: every recognized input rebuilds to `www.youtube.com` or
`player.vimeo.com`, both of which are on the default allow-list, so
`validate_embed_url` sees a listed host on the recognized path. Caveat: the
allow-list is env-overridable (`env.list("LIBLI_ALLOWED_EMBED_DOMAINS", …)`); the
two rebuild targets (`www.youtube.com`, `player.vimeo.com`) are therefore an
implicit contract with that config — a deployment that overrides the env var to
exclude them would make normalization produce a URL the allow-list then rejects
("we normalized your link but it's still rejected"). This analysis assumes the
default list.

### Integration

`courses/element_forms.py`, `VideoElementForm`:

```python
# Override the model's URLField as free-text so the raw pasted value
# (scheme-less, with tracking params, etc.) reaches clean_url intact;
# canonicalize_video_url is the single parser, and the normalized output is
# re-validated by validate_embed_url in VideoElement.clean(). Mirrors the
# IframeElementForm precedent (element_forms.py).
url = forms.CharField(required=False)

def clean_url(self):
    return canonicalize_video_url(self.cleaned_data.get("url", ""))
```

**Why the field override (do not skip this):** `VideoElement.url` is a
`models.URLField`, so without this override the `ModelForm` renders it as
`forms.URLField`, whose `to_python` rewrites/validates the value (adds or rejects a
scheme — and Django's `assume_scheme` default is itself in flux across versions)
**before** `clean_url` runs. That would defeat the scheme-less paste support and
make `canonicalize_video_url` no longer the single source of parsing truth.
Overriding to `forms.CharField` hands the raw string to `clean_url`. It MUST be
`required=False` — otherwise an empty paste (valid when an uploaded media file is
used instead) becomes a "This field is required" field error that pre-empts the
url/media XOR. (`VideoElementForm.__init__` already sets `url`/`media` to
`required=False`; declaring it on the field too keeps the intent local and
explicit.) The form *field* widget is irrelevant to rendering here — the editor
template **hand-rolls** the `<input>` element (see the template note below), not
`{{ form.url }}` — so no `widget=` is needed; only the POST field name `url` must
match.

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

Two sub-cases worth pinning explicitly:
- **Bad url + media present:** `clean_url` raises, so `cleaned.get("url", "")` is
  `""` in `clean()` → `instance.url=""`, `instance.media` set → the XOR is
  *satisfied* and silent; the form is invalid solely on the `url` field error. This
  is intended — the author sees the specific "couldn't find a video" message, not a
  confusing XOR error. With `instance.url=""` the model `clean()` takes its
  `has_url=False` branch and never calls `validate_embed_url("")`, so no spurious
  https/allow-list error stacks on top of the field error.
- **Value survives a reject:** because `url` is a `CharField`, on a re-rendered bound
  form `form.url.value()` returns the author's **original pasted string**, so the
  hand-rolled `value="{{ form.url.value|default:'' }}"` re-populates the field with
  what they typed — they can fix it in place rather than re-paste. Pin this with a
  test asserting the rejected raw input is present on re-render.

Editor template `templates/courses/manage/editor/_edit_video.html`: the URL input
is **hand-rolled** (`<input type="url" name="url" value="{{ form.url.value|default:'' }}">`
on the existing line), not a `{{ form.url }}` render. Three changes:
1. Change `type="url"` → `type="text"`. **This is load-bearing, not cosmetic:** an
   HTML5 `type="url"` input fails client-side validation on a scheme-less paste
   (`youtu.be/ID`) and the browser blocks submission *before* the server ever sees
   it — defeating the headline feature. `type="text"` lets the raw value POST; the
   server-side `canonicalize_video_url` + `validate_embed_url` remain the validators.
   Audited safe: the URL field is rendered solely by the literal `<input>` on the
   existing template line (no `{{ form.url }}`, so no form-widget interaction), and
   the source/upload pane toggle is pure CSS (radio `:checked` siblings in
   `editor.css`) — **no editor JS reads `input[type=url]`** (grep-confirmed), so the
   type change has no behavioral side effect.
2. Relabel the field to *"YouTube / Vimeo link"* and add short help text ("Paste any
   link — the address bar, the Share button, or an embed URL all work.").
3. Wrap both new strings in `{% trans %}` and add Polish `.po` entries; **compile
   the `.po`** (`django-admin compilemessages`). Prerequisite: `compilemessages`
   needs the GNU `msgfmt` binary, which is often absent on a Windows dev box (this
   environment is win32) — install gettext (or follow the project's existing
   translation-build path) before running it, so a missing binary doesn't masquerade
   as a feature failure. Any explanatory template comment must be single-line
   `{# … #}` or a `{% comment %}…{% endcomment %}` block — a recurring project bug
   has shipped visible multi-line `{# #}` comments.

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
- **scheme-relative** input: `//youtu.be/ID` → correct embed (from r2 I1)
- **mixed-case host**: `YOUTU.BE/ID`, `WWW.YouTube.com/watch?v=ID` → correct embed
- already-embed `…/embed/ID` → unchanged (idempotent)
- already-embed **with start** `…/embed/ID?start=90` → unchanged (idempotent)
- host rewrite: `music.youtube.com/embed/ID` → `https://www.youtube.com/embed/ID`
  (non-`www` embed re-paste normalizes to `www`; from r2 M2)
- `www.youtube-nocookie.com/embed/ID` recognized → `www.youtube.com/embed/ID`
  (from r2 M1)
- start time: `&t=90`, `&t=90s`, `&t=1m30s`, `&start=120` → `?start=<n>`
- **`youtu.be/ID?t=90` (real Share URL) → `…/embed/ID?start=90`** (from r2 I3)
- query value selection: `?t=&start=90` → `?start=90` (empty `t` is absent);
  `?t=10&t=90` → `?start=10` (first occurrence; from r2 I2)
- junk `t` falls through to `start`: `?t=s&start=90` → `?start=90` (from r4 I3)
- `/watch` with empty `v=` → reject; non-`/watch`-non-`/embed`-family path → reject
  (path-selected dispatch, from r4 I2)
- duration grammar edges: `&t=2h` → `?start=7200`, `&t=90m` → `?start=5400`;
  unparseable `&t=1m30sxyz`, `&t=s`, `&t=1s30m` → start omitted (no error)
- ID-shape reject: `youtu.be/playlist`, `youtu.be/watch` (segment fails the
  11-char ID regex) → `ValidationError` (from C2)
- ID-length boundary: a 12-char `[A-Za-z0-9_-]` YouTube segment → reject and a
  clean 11-char → accept (proves the `{11}` anchor is exact, from r3 M3)
- `youtu.be` / `youtu.be/` (bare host / empty first segment) and `youtu.be//ID`
  (leading empty segment) → reject, no crash (from r3 I5)
- `vimeo.com/123456` → `player.vimeo.com/video/123456`
- `player.vimeo.com/video/123456` → unchanged (idempotent)
- **Vimeo unlisted** `vimeo.com/123456/abc123` → `player.vimeo.com/video/123456?h=abc123`
  (privacy hash preserved); `player.vimeo.com/video/123456?h=abc123` → unchanged
  (idempotent); `player.vimeo.com/video/123456/abc123` (path-form on player host) →
  `…/video/123456?h=abc123` (from r4 M2); unlisted + start
  `vimeo.com/123456/abc123#t=90s` → `…/video/123456?h=abc123#t=90s` (from r2 I4)
- **hash+start idempotency**: `player.vimeo.com/video/123456?h=abc123#t=90s` →
  unchanged (re-parse reads `h` from query, `t` from fragment; from r4 I4)
- extra path segments are **not** a hash: `vimeo.com/123456/review/xyz` →
  `…/video/123456` (ID only, no `?h=`; from r4 I1)
- vimeo fragment: `#t=90s` → `#t=90s` (idempotent) AND `#t=1m30s` → `#t=90s`
  (normalized — distinct case, from I3)
- vimeo query `t` is ignored: `vimeo.com/123456?t=90` → no `#t=` appended
- vimeo `vimeo.com/channels/x/123456` → `…/video/123456`
- reject: `youtube.com/playlist?list=…`, bare `youtube.com/watch`, `vimeo.com/user12`
- empty string → `""`
- pass-through byte-for-byte: `https://www.geogebra.org/m/abc` and mixed-case
  `https://Www.GeoGebra.org/m/abc` each returned exactly as given (no lowercasing)

Form-level — extend `tests/test_courses_elements.py` (or `test_element_add_save.py`):

- `VideoElementForm` with a pasted **scheme-less** `youtu.be/<ID>` URL is valid and
  saves `instance.url == "https://www.youtube.com/embed/<ID>"` (proves the
  `CharField` override from r2 C1 lets the raw value reach `clean_url`)
- `VideoElementForm` with a pasted `watch?v=…` URL is valid and saves
  `instance.url == "https://www.youtube.com/embed/<ID>"`
- `VideoElementForm` with a playlist URL is invalid with a `url` field error
- `VideoElementForm` with an **empty url + a media file** is valid (XOR satisfied —
  confirms `required=False` on the override did not reintroduce a required-field
  error; from r2 C2)
- `VideoElementForm` with a **valid URL + a media file** is invalid with the
  non-field XOR error (URL passed `clean_url`, XOR then fired — pins the precedence
  from I5)
- `VideoElementForm` with a **bad (no-ID) URL + a media file** is invalid with a
  `url` field error and **no** non-field XOR error (the bad-url+media sub-case from
  r3 I3)
- After a no-ID reject, the re-rendered bound form's `form.url.value()` equals the
  author's original pasted string (raw input survives for in-place fix; from r3 C2)

## DoD

- Full test suite green; `ruff check` and `ruff format --check` clean.
- Manual: paste each of the three real URLs from the problem report into the video
  editor → all save as `…/embed/lk5_OSsawz4` and play.
- Manual (start round-trip): paste `…/watch?v=lk5_OSsawz4&t=90` (and a
  `youtu.be/lk5_OSsawz4?t=90` Share link) → saves as
  `…/embed/lk5_OSsawz4?start=90` and the player starts at 1:30.
