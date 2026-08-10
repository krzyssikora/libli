# GeoGebra share-link sizing

**Date:** 2026-08-10
**Status:** Approved (ready for implementation planning)

## Purpose

A GeoGebra material added by its **share link** (`https://www.geogebra.org/m/dcjktevj`)
renders with a band of white space down its right-hand side. The same material added by
GeoGebra's suggested **static embed code** (`<iframe … width="880px" height="660px">`)
renders correctly. This design makes the share link render identically to the static embed.

### Measured mechanism

`canonicalize_geogebra_url` rewrites the share link to
`https://www.geogebra.org/material/iframe/id/dcjktevj`. Fetching that URL returns a page
whose entire sizing logic is client-side:

```js
const parameters = { …, "allowUpscale": "true", "scaleContainerClass": "frame" };
// width/height are read from the URL path segments, then:
parameters.width  = (parameters.width  || 800) * 1;
parameters.height = (parameters.height || 600) * 1;
```

Three fetches — a different material id, and the same id with and without a
`/width/…/height/…` tail — returned **byte-identical** documents (md5
`33b9101e9bb5777016b8a4ae4ac8e2a5`). GeoGebra serves one static shell for every embed;
the material's authored size never reaches the sizing code. The only inputs are the URL
path segments, and the fallback is **800×600 (4:3)**.

`scaleContainerClass` then scales that applet **uniformly** to fit the container, anchored
top-left. Measured in Chromium at the real 648px content width:

| case | wrapper | applet renders | gap right | gap bottom |
|---|---|---|---|---|
| current: 16:9 wrapper, bare src | 648 × 364.5 (1.778) | 486.7 × 365.0 (**1.333**) | **161.3px** | 0 |
| 4:3 wrapper, bare src | 648 × 486 (1.333) | 648 × 486 (1.333) | **0.0px** | 0 |
| 4:3 wrapper, src `/width/880/height/660` | 648 × 486 (1.333) | 648 × 486 (1.333) | **0.0px** | 0 |
| **2:1 wrapper**, src `/width/800/height/400` | 648 × 324 (2.000) | 648 × 324 (2.000) | **0.0px** | **0** |
| **4:3 wrapper**, src `/width/800/height/400` | 648 × 486 (1.333) | 648 × 324 (2.000) | 0 | **162.0px** |

The last two rows are deliberate: they use a **non-4:3** applet, so the rule cannot be a
coincidence of this material happening to be 4:3. The applet always renders at exactly the
ratio the URL specifies (or 800×600 when the URL specifies none), scaled uniformly, and any
wrapper mismatch shows as leftover space on the over-long axis. So the root cause is
precise and general: **our fallback ratio (16:9) disagrees with GeoGebra's own fallback
ratio (4:3).**

### The second, less visible half

Correcting the wrapper to 4:3 closes the gap but does **not** make a share link equal to
the static embed. GeoGebra's 800×600 default is ~9% tighter than this material's authored
880×660, so it **crops the construction**. In the measured screenshots the 4:3-bare case
shows a y-axis of 4→18, while the authored 880×660 case shows 0→18 — including a data
point at ≈(14, 2) that the default viewport omits entirely. On a correlation scatter plot
that is a content defect, not a cosmetic one.

A URL-only fix cannot recover it. The shell's alias table accepts exactly `width, height,
stb, smb, ai, asb, sri, ld, sdz, rc, sfsb, stbh, szb, border, id` — there is no
"fit the construction" parameter. **The crop can only be fixed by knowing the authored
width/height**, which `https://api.geogebra.org/v1.0/materials/<id>?scope=basic` supplies.

### Live verification of the API path

The measurements above were taken with `curl`. Because the shipped code uses
`urllib.request` — whose default `User-Agent: Python-urllib/3.x` is a plausible thing for
a CDN to reject — the exact call this design specifies was also run for real:

```
urllib.request.urlopen("https://api.geogebra.org/v1.0/materials/dcjktevj?scope=basic", timeout=5)
→ 200; elements[0].settings.width = 880, .height = 660
```

So the endpoint is reachable from this code path today with no custom header. An explicit
`User-Agent` is still specified below (see §1) as courtesy and future-proofing, not as a
fix for a present breakage. **Acceptance criterion:** re-run this one-off call through the
shipped `fetch_geogebra_dimensions` before opening the PR and record the returned pair in
the PR body — the offline test suite cannot detect the API moving. **Clear the default
cache (or use a fresh process) immediately before that check**, or a negative-cache
sentinel from an earlier failed attempt will short-circuit it and return `(None, None)`
with no request — indistinguishable from the very failure the check exists to detect.

### Scope in existing content, and every creation path

**Census — taken against the local dev database `libli`, which is the one containing
`mat-pp`** (the same database serving the `/courses/mat-pp/u/294/` page where this defect
was reported). Naming the database matters: a count taken against a mat-pp-free database
would say nothing about the real content set.

| course | GeoGebra iframes **with** dimensions | **without** |
|---|---|---|
| `mat-pp` | **131** | **0** |
| `demo-course` | 1 | 2 |

Plus one orphaned `IframeElement` (`…/id/abc123`) with zero join rows — a leftover fixture
on no page. So of 134 GeoGebra rows, exactly **two reachable ones lack dimensions**, both in
`demo-course` (units 16 and 106). **No published mat-pp unit changes appearance** as a
result of this work.

That census is a snapshot, so here is every path that constructs an `IframeElement` and
whether it gets the lookup:

| path | gets the lookup? | why |
|---|---|---|
| `IframeElementForm` (editor create/edit) | **yes** | the interactive path this design targets |
| `courses/lal_loader/builders.py:350` (`IframeElement.objects.create(url=…, title=…)`) | **no** | bulk mat-pp ingest; a per-element network call would make a large import slow and network-dependent |
| `courses/management/commands/seed_demo_course.py` | **no** | fixture seeding, not authored content |
| `courses/transfer` import (`_build_iframe`) | **no** | archives already carry `width`/`height` (`FORMAT_VERSION` ≥ 2), so a lookup would be redundant *and* would put the network in the import path |
| Django admin (`admin.site.register(IframeElement)`) | **no** | raw model form, no `clean_url`; a staff-only escape hatch |

Note the tension between rows one and two of that table and the census: `builders.py:350`
constructs iframes with no dimensions, yet mat-pp measures 131/131 *with* dimensions. Both
facts are stated as measured; the reconciliation (mat-pp's iframes did not reach the
database through that constructor, or did so before it took its current form) is not
established and this design does not depend on it. What matters is the forward-looking
consequence: **any future LAL import will produce dimensionless GeoGebra elements**, and
those now render at 4:3 with a badge instead of silently at 16:9.

### Goals

1. A GeoGebra material added by share link **through the editor** renders identically to the
   same material added by its static embed code — no white space **and** no crop.
2. When the authored size cannot be determined, fall back to **4:3** (GeoGebra's own
   default, measured to leave a 0.0px gap) instead of today's 16:9.
3. When the authored size cannot be determined, tell the author so, non-blockingly, with a
   concrete workaround.
4. Authoring never fails because geogebra.org is slow or unreachable.

### Non-goals

- **No backfill mechanism.** Two reachable rows are affected, both in `demo-course`, and the
  user will fix them by hand. There is no deployment and no production database.
- **No lookup on the bulk paths** (LAL loader, seed command, transfer import, admin).
- **No manual width/height fields in the editor.** Considered and rejected during
  brainstorming; the static embed paste remains the explicit escape hatch.
- **No change to non-GeoGebra embeds.** The 4:3 correction is scoped to the provider it
  was measured against; every other provider keeps the 16:9 CSS default.
- **No periodic re-fetch or staleness handling.** Dimensions are re-derived only when the
  URL changes (§2). If an author resizes a material on geogebra.org without changing its
  URL, re-pasting the embed code is the way to update our copy.
- **No new e2e test.** An end-to-end assertion would depend on geogebra.org being reachable
  and would be flaky. The browser measurements above are the evidence for the ratio; the
  render assertions cover the code path; the one-off live check covers the API contract.
- **No migration and no `FORMAT_VERSION` bump.** `IframeElement.width`/`.height` already
  exist and are nullable, and nothing new is persisted on the model.

## Architecture / components

Five changes plus one settings flag and one CSS rule.

### 1. Lookup helper — `courses/geogebra.py`

This module stays the single GeoGebra parser. It gains constants, a transport seam, and
three public functions:

```python
GEOGEBRA_DEFAULT_SIZE = (800, 600)   # GeoGebra's own iframe-shell fallback → 4:3
_API_PREFIX = "https://api.geogebra.org/"
_TIMEOUT_SECONDS = 3          # module constant, matching integrations/delivery.py's precedent
_MAX_BODY_BYTES = 65536
_NEGATIVE_TTL_SECONDS = 60
_USER_AGENT = "libli/1.0 (+https://github.com/krzyssikora/libli)"
_DIM_MAX = 2147483647         # PositiveIntegerField ceiling

def usable_dimensions(width, height) -> bool   # the shared predicate — see §3
def _open(request, timeout)                    # the transport seam tests patch
def geogebra_material_id(url) -> str
def fetch_geogebra_dimensions(material_id) -> tuple[int, int] | tuple[None, None]
```

**Why these live here.** `usable_dimensions` is provider-neutral, yet `courses/geogebra.py`
is the only module in `courses/` that imports nothing from its own package — which makes it
the sole cycle-free home. The alternatives both create cycles or churn:
`courses/embed.py` already imports `geogebra`, so the predicate cannot live there without
inverting that edge, and `courses/models.py :: embed_src` deliberately imports `geogebra`
*lazily inside the method* to avoid a models→geogebra edge at import time. Putting the
predicate in `geogebra.py` lets `embed.py`, `element_forms.py`, and `models.py` all import it
at module level safely. `embed.py`'s existing `_INT_MAX` is folded into `_DIM_MAX` here so the
ceiling has one definition. The name deliberately carries **no leading underscore**: it is a
cross-module contract, and an underscore would invite a reviewer to "fix" the imports by
duplicating the predicate — the exact outcome it exists to prevent.

`geogebra_material_id` promotes the existing private `_material_id` logic to a public entry
point taking a URL. **It must also apply `_ID_RE`** (`^[A-Za-z0-9_-]+$`) before returning:
today's `_material_id` does *not*, because `canonicalize_geogebra_url` applies the regex
afterwards. A verbatim promotion would make
`geogebra_material_id("https://www.geogebra.org/m/bad id")` return `"bad id"` — truthy, so
`clean_url` would proceed and build an API URL containing a raw space. It returns `""` for
anything unrecognised, non-https, on a non-GeoGebra host, or failing the charset check.
`canonicalize_geogebra_url` is refactored to call it, so recognition exists in one place.

**Return contract.** `fetch_geogebra_dimensions` is **all-or-nothing**: either a pair of
usable ints or `(None, None)`. A partial pair such as `(880, None)` is unreachable by
construction, hence the annotation `tuple[int, int] | tuple[None, None]`.

**Transport.** The `Request` is built by `fetch_geogebra_dimensions` and passed *into* the
seam, so a test patching `_open` can inspect its headers:

```python
req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
with _open(req, _TIMEOUT_SECONDS) as resp:
    payload = resp.read(_MAX_BODY_BYTES)

def _open(request, timeout):                      # the seam
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)
```

The `with` is required, not stylistic: `integrations/delivery.py` — the cited precedent —
uses `with opener.open(...) as resp:`, and because the read is capped the connection is
never drained, so an unclosed response leaks a socket per call and raises `ResourceWarning`
in tests. **The test double for `_open` must therefore be a context manager.**

Refusing redirects matters: `urlopen` follows them by default, so a check on the
*constructed* URL says nothing about the host actually contacted.
`integrations/delivery.py :: _NoRedirect` already exists for exactly this reason and should
be reused (imported, or duplicated with a comment pointing at the original — the plan
decides which; the behaviour is fixed).

The URL is `_API_PREFIX + "v1.0/materials/" + material_id + "?scope=basic"`, where
`material_id` has passed `_ID_RE` and so cannot introduce a scheme, host, or traversal. A
`startswith(_API_PREFIX)` check on the constructed URL is **defensive only and unreachable
by construction** — deliberately *not* claimed as a security control and given **no test**,
because a branch that cannot be driven cannot be falsified to RED. The real controls are
`_ID_RE` and the no-redirect opener. Observed ids are 8 characters; `_ID_RE` is unbounded,
acceptable because the URL reaching this code has already passed `URLField`'s length cap —
noted so nobody mistakes `_ID_RE` for a length guard.

**Body handling.** Read at most `_MAX_BODY_BYTES` and parse. An oversized, truncated, or
non-JSON body degrades to `(None, None)` — the socket timeout alone does not bound how much
a slow or hostile endpoint can send.

**Response shapes.** Two are observed. A real `ws` response, trimmed from the document root
down to the dimensions so the paths below are verifiable from this spec alone:

```json
{
  "id": "dcjktevj",
  "title": "korelacja 1",
  "type": "ws",
  "elements": [
    {
      "id": 42153397,
      "order": 0,
      "type": "G",
      "settings": { "appName": "classic", "width": 880, "height": 660, "scale": 1 }
    }
  ],
  "visibility": "S"
}
```

Verified against the live API: this `ws` document has **no top-level `settings` key** — its
root keys are exactly `creator_id, date_created, date_modified, date_published, deleted,
elements, id, supportsLesson, thumbUrl, title, type, visibility`. The `wseg` document
(`wgzr7tsu`) *does* carry a top-level `settings` object with `width`/`height`, plus a
`worksheet_id` back-pointer.

| material `type` | example id | where the dimensions live |
|---|---|---|
| `wseg` (applet) | `wgzr7tsu` | `settings.width` / `settings.height` |
| `ws` (worksheet) | `dcjktevj` | `elements[N]["settings"]["width"]` / `["height"]` |

**Selection rule — a fallthrough on *usable dimensions*, not on key presence:**

1. If top-level `settings` yields a usable pair, return it.
2. Otherwise scan `elements` in document order and return the first entry with
   `elements[N]["type"] == "G"` **whose settings yield a usable pair**. Keep scanning past a
   `"G"` entry that does not — do not stop at the first `"G"`.
3. If nothing yields a usable pair, return `(None, None)`.

**Never raises — a bare `except Exception`.** An enumerated tuple is insufficient:
`urlopen` can raise `http.client.RemoteDisconnected`, `ConnectionResetError`, `ssl.SSLError`
variants, `UnicodeDecodeError` on a mis-encoded body, and `ValueError` from `Request()`
construction, none of which are `URLError` subclasses. Anything escaping into `clean_url`
would 500 the save. Wrap the whole fetch-and-parse body in a bare `except Exception:`,
matching `courses/embed.py :: parse_iframe_dimensions`.

**Observability.** On any failure path, emit a `logger.warning` carrying the material id and
the exception type (or HTTP status). Without it, a systemic failure — API path changed,
schema reshaped, UA blocked — is indistinguishable from "this material genuinely has no
dimensions", and the only signal is a badge the author reads as a property of their own
material. A successful lookup logs nothing.

**Negative cache.** A failed lookup caches a sentinel under `geogebra:dims:<material_id>`
for `_NEGATIVE_TTL_SECONDS` (**60s**), and a cached sentinel short-circuits to
`(None, None)` without a request. Only failures are cached; a success is persisted on the
model. This bounds the repeat cost: without it, every subsequent save of a dimensionless
element re-pays the full timeout while holding a row lock. The TTL is deliberately short —
the badge invites the author to retry, and a longer window would make that retry fail
deterministically with no request issued, which reads as an inexplicable bug. **Accepted
consequence:** a retry within 60 seconds of a failure is suppressed. Note also that
`config/settings/base.py` defines **no `CACHES`**, so Django's implicit per-process
`LocMemCache` applies — outside tests this bound is per worker process, not per site.

**Kill switch.** When `settings.GEOGEBRA_API_LOOKUP` is false, return `(None, None)`
immediately — no cache read, no request.

### 2. Capture — `IframeElementForm.clean_url`

The existing `parse_iframe_dimensions` capture is unchanged and runs first. The lookup is
attempted only when dimensions are unknown in the paste **and** the instance has no usable
pair **for this same URL**:

```python
url = extract_embed_url(raw)
width, height = parse_iframe_dimensions(raw)
url_changed = url != self.instance.url
if url_changed and not usable_dimensions(width, height):
    self.instance.width = self.instance.height = None   # stale: they describe the old material
stored_usable = usable_dimensions(self.instance.width, self.instance.height)
if not usable_dimensions(width, height) and not stored_usable:
    mid = geogebra_material_id(url)
    if mid:
        width, height = fetch_geogebra_dimensions(mid)
if usable_dimensions(width, height):
    self.instance.width = width
    self.instance.height = height
return url
```

**Invariant: a stored dimension pair is never re-derived *for an unchanged URL*.** Both
halves are load-bearing.

*The instance guard.* On an edit the textarea is pre-filled with the stored **canonical
URL**, not the original `<iframe>` snippet — `tests/test_iframe_dimensions.py ::
test_form_plain_url_edit_preserves_existing_dimensions` posts exactly
`data={"url": URL, "title": "renamed"}`. So `parse_iframe_dimensions` returns `(None, None)`
on **every** subsequent edit of a static-embed element. Without the guard, a title-only
rename would fire a network call and, if GeoGebra now reported a different size, silently
replace the author's captured 880×660.

*The URL-change clause.* Without it the guard misfires in the opposite direction: an author
who edits an element and pastes a **different** share link gets
`parse_iframe_dimensions → (None, None)`, the instance guard short-circuits, and the
*previous* material's 880×660 is kept — so `embed_src` appends `/width/880/height/660` to
the new material's URL and the wrapper uses the old ratio. That is a wrong crop on a
material the author just changed, defeating Goal 1. Clearing the stale pair when the URL
changes makes the new material take the normal lookup path.

Re-pasting a full `<iframe>` still overwrites dimensions, because that path is satisfied by
`parse_iframe_dimensions` before either guard is consulted — preserving today's
`test_form_re_paste_overwrites_dimensions` behaviour.

`extract_embed_url` is deliberately **not** modified. It is shared with course import via
`courses/transfer/payloads.py :: _val_iframe` → `_canonical_embed`, so a network call inside
it would make imports hit geogebra.org.

**The lookup runs inside a locked transaction — stated, not hidden.**
`courses/builder.py :: save_element` is decorated `@transaction.atomic`, and its first act is
`_locked_unit(course, unit_pk)`, a `select_for_update()` on the unit's `ContentNode` row.
`form.is_valid()` — and therefore `clean_url` and the GET — runs after that lock is taken, so
the lookup holds an open transaction, a pooled DB connection, and an exclusive row lock on
the unit for the duration of the call.

This is **accepted deliberately** rather than restructured: the lookup fires only on a
first save or a URL change, the only thing it can block is a concurrent edit of the *same
unit*, and the mitigations — 3s socket timeout, capped body read, refused redirects, 60s
negative cache — keep the common failure path short. Moving resolution out of `clean_url`
would leak iframe-specific logic into the view layer or change `save_element`'s signature, a
larger blast radius than the risk warrants. The alternative is recorded so a future reader
can revisit it rather than rediscover the lock.

### 3. Render — a provider-aware fallback ratio

**One predicate, shared** (`courses/geogebra.py`, see §1 for why it lives there):

```python
def usable_dimensions(width, height):
    """True iff both are real, positive, in-range ints (1 .. _DIM_MAX).

    bool is excluded explicitly (isinstance(True, int) is True in Python, so a
    payload of {"width": true} would otherwise render `aspect-ratio: True / 660`).
    Non-int types are rejected outright, including an integral float like 880.0.
    """
```

**The `1 .. _DIM_MAX` bound is inside the predicate, not merely in the parser.** It has to
be: `IframeElement.width` is a `PositiveIntegerField` whose ceiling is *not* re-checked at
save — `clean_url`'s existing comment says so ("the ceiling is enforced in
parse_iframe_dimensions, not here") because `width`/`height` are absent from
`Meta.fields` and `_post_clean` therefore excludes them from `full_clean`. A predicate that
merely said "positive int" would accept `2147483648` from the API, assign it, and produce a
psycopg *integer out of range* on `form.save()` — a 500 on the exact path the never-raises
contract exists to protect.

Every consumer uses it: the parser's selection rule, `clean_url`'s guards, `frame_ratio`, and
`size_unknown`. That is what stops the badge and the ratio from ever disagreeing, and it pins
down the partial/zero cases that independently-nullable columns allow (`check_int_or_null` in
the transfer validator admits `(800, None)` and `(0, 0)` from an archive).

**"Is this a GeoGebra embed?" is one named predicate too:** `bool(geogebra_material_id(self.url))`
— the same gate `clean_url` uses. Host membership is explicitly *not* the test. The two
diverge on URLs that exist in this database: `https://www.geogebra.org/x` (a shape the LAL
parser stores un-canonicalized) and `https://www.geogebra.org/classic/abc` are on a GeoGebra
host but yield no material id. Under a host-based reading such an element would get
`aspect-ratio: 800 / 600` while `embed_src` left the src bare (`geogebra_sized_src` requires
`segments[:3] == ["material","iframe","id"]`), forcing a full GeoGebra *web page* into a 4:3
box and showing a badge whose workaround cannot help. Using the material-id predicate, those
URLs take the `None` branch and no badge.

`IframeElement` gains two properties:

```python
@property
def frame_ratio(self):
    """CSS aspect-ratio for the wrapper, or None to keep the .embed-frame default."""

@property
def size_unknown(self):
    """True for a GeoGebra *material* embed whose dimensions are not usable."""
```

`frame_ratio` resolves in order:

- `usable_dimensions(self.width, self.height)` → `"<width> / <height>"`
- else `bool(geogebra_material_id(self.url))` → `"800 / 600"`, formatted from
  `GEOGEBRA_DEFAULT_SIZE` so the constant is the single source of truth. Same ratio as
  `4 / 3`, renders identically; the spec and tests use the literal `800 / 600` throughout to
  avoid an implementer/test mismatch.
- else → `None`

So a partial or zero pair on a GeoGebra material takes the `800 / 600` branch, and anything
else takes the `None` branch — never a malformed `aspect-ratio: 800 / None`.

`templates/courses/elements/iframeelement.html` switches from `el.width and el.height` to
`el.frame_ratio`:

```html
<div class="embed-frame"{% if el.frame_ratio %} style="aspect-ratio: {{ el.frame_ratio }}"{% endif %}>
```

`.embed-frame`'s `aspect-ratio: 16 / 9` stays the CSS default and continues to govern every
non-GeoGebra embed with unknown dimensions. `embed_src` and `geogebra_sized_src` are
unchanged: once the lookup supplies dimensions the existing code appends
`/width/W/height/H`, which is what makes the share link match the static embed.

### 4. Author feedback — a persistent editor badge

`templates/courses/manage/editor/_element_row.html` has eight `{% elif %}` branches for
container types; an iframe element falls through to the **terminal `{% else %}` block**
(currently line 300), which is where the badge goes. The concrete object is in scope as
`obj` — **not** `el`, which is the join row — so the condition is `{% if obj.size_unknown %}`.

```html
<span class="el-row__flag"
      title="{% trans "The applet size is unknown, so it renders in a 4:3 frame and may be cropped. Paste the <iframe> embed code for exact sizing." %}">{% trans "applet size unknown" %}</span>
```

Both strings are autoescaped (never `|safe`), so the literal `<iframe>` reaches the DOM as
`&lt;iframe&gt;` and displays to the author as `<iframe>`. Backticks elsewhere in this spec
are markdown and are **not** part of the string.

**A CSS rule is required — `.el-row__flag` is currently unstyled.** An earlier draft claimed
reuse made CSS unnecessary; that was wrong. `grep -rn "el-row__flag"` over the worktree
returns exactly one non-spec hit — `_element_row.html:29`, the revealgate flag — and **no
selector in `courses/static/courses/css/editor.css` or any other stylesheet**. Shipping the
badge without a rule would put unstyled inline body text inside the flex `.el-row__top`,
violating the repo's "every view ships styled" rule rather than satisfying it. Add a rule
beside `.el-tag` (editor.css:79), mirroring its token usage, and note that it also
**retro-styles the existing revealgate flag** — a latent defect this change incidentally
fixes:

```css
.el-row__flag {
  font-size: .7rem; color: var(--text-secondary);
  white-space: nowrap; cursor: help;
}
```

It sits inside `.el-row__top` (`display:flex; align-items:center; gap:var(--space-2)`) before
`.el-actions`, which carries `margin-left:auto` and therefore keeps its right alignment
regardless.

**Catalog deliverable.** Add both strings to the Polish catalog explicitly: run
`makemessages -l pl -l en --no-obsolete`, write the translations, **clear any `#, fuzzy`
marker** the extractor pre-fills, and run `compilemessages`. The repo has a recorded hazard
where a fuzzy pre-fill silently ships a wrong translation and clearing it requires two
deletions — verify `0 fuzzy` before committing.

The condition is derived purely from the element's own state; `_editor_rows` already yields
`(join_row, concrete_obj)` pairs, so **no plumbing through `builder_svc.save_element` is
needed**. It also survives later editor loads, flags every future LAL-imported element
automatically, and clears itself once dimensions are known.

### 5. Settings

`config/settings/base.py` gains exactly one flag:

```python
GEOGEBRA_API_LOOKUP = True      # kill switch; False in test.py
```

A Django setting rather than a module constant specifically because
`config/settings/test.py` must turn it off suite-wide. Timeout and other tunables stay
**module constants** in `courses/geogebra.py`, matching
`integrations/delivery.py :: TIMEOUT_SECONDS = 10`. Neither is `env()`-backed and neither
goes in `.env.example`, because there is no deployment to configure them for.

## Data flow

```
author pastes …
├── static embed <iframe … width="880px" height="660px">
│     parse_iframe_dimensions → (880, 660)          [no network]
│     stored 880×660 → wrapper 880/660, src /width/880/height/660
│
├── later title-only edit (URL unchanged)
│     parse → (None, None); url_changed = False; instance usable → short-circuit
│     [no network, dims untouched]
│
├── edit that pastes a DIFFERENT share link
│     url_changed = True → stale pair cleared → lookup runs for the new material
│
├── share link https://www.geogebra.org/m/dcjktevj (fresh element)
│     canonicalize → …/material/iframe/id/dcjktevj
│     geogebra_material_id → "dcjktevj"
│     fetch_geogebra_dimensions → (880, 660)   [one GET, inside the unit's row lock]
│     stored 880×660 → wrapper 880/660, src /width/880/height/660
│     ⇒ identical render to the static embed
│
└── share link, lookup unavailable
      logger.warning; negative-cache the id for 60s
      stored NULL → wrapper 800/600 (= 4:3), bare src, editor badge shown
      ⇒ no white space; applet may be cropped to GeoGebra's 800×600 viewport
```

## Error handling

| condition | behaviour |
|---|---|
| API 400 `err_invalid_id`, 5xx, DNS failure, timeout | `(None, None)` → save succeeds, 4:3, badge, warning logged, id negative-cached |
| redirect response | refused by the no-redirect opener → `(None, None)` |
| body larger than `_MAX_BODY_BYTES`, truncated, or not JSON | `(None, None)` → same |
| any exception type at all, listed or not | caught by the bare `except Exception` → `(None, None)` |
| no `settings` and no `"G"` element yielding a usable pair | `(None, None)` → same |
| dimension ≤ 0, non-int, `bool`, float, or > `_DIM_MAX` | not usable → `(None, None)` → same |
| id already in the negative cache | `(None, None)` without a request |
| `GEOGEBRA_API_LOOKUP` false | `(None, None)` without a cache read or request |
| GeoGebra host but no material id (`/x`, `/classic/…`) | not a material embed: 16:9 default, no badge, no lookup |
| non-GeoGebra URL with no dimensions | unchanged: 16:9 CSS default, no badge |

The element **always saves**. No failure mode of a third-party API can block authoring, and
no failure mode can raise out of `courses/geogebra.py`.

**The upper bound on a save is not a hard 3 seconds.** `urlopen(..., timeout=N)` sets the
*socket* timeout: it applies per blocking socket operation — the connect, and each
individual `recv` — not to the total exchange. An endpoint dripping one byte every 2.9s
keeps the request alive past 3s, and `getaddrinfo` name resolution is not covered by the
socket timeout at all, so a stalled resolver can block before the connect is attempted. The
capped read bounds total bytes, which bounds the drip scenario in practice, but the honest
statement is: **the worst case is bounded by the capped read, not by a wall-clock
guarantee, and DNS stalls are out of scope.** The mitigation for the repeat case is the
negative cache, not the timeout.

## Testing

All tests run offline. Three real API responses captured while diagnosing this —
a `ws` worksheet (`dcjktevj`), a `wseg` applet (`wgzr7tsu`), and the 400 `err_invalid_id` —
are checked in under `tests/fixtures/geogebra/` as `ws.json`, `wseg.json`,
`err_invalid_id.json`.

**Two seams, named explicitly** — the groups patch *different* things and must not be
conflated:

- **Parser tests** patch `courses.geogebra._open`, asserting on the returned pair and on the
  `Request` they receive. The double **must be a context manager**, since the caller uses
  `with`.
- **Form / import tests** patch `courses.element_forms.fetch_geogebra_dimensions` and assert
  **call counts** (including zero).

**`GEOGEBRA_API_LOOKUP` is False for the whole suite** (`pyproject.toml` pins
`DJANGO_SETTINGS_MODULE = "config.settings.test"`). Every test exercising the lookup —
including the "invalid input → `(None, None)`" cases, which would otherwise pass vacuously
by short-circuiting before the parser runs and could never be falsified to RED — must wrap in
`override_settings(GEOGEBRA_API_LOOKUP=True)`. Exactly one test deliberately runs under the
`False` default: the kill-switch test. Cache isolation between *tests* is already handled by
the autouse `tests/conftest.py :: _clear_site_cache` fixture (it calls `cache.clear()` before
and after every test), so no per-test teardown is needed — the only thing to watch is not
reusing one material id across two assertions **within** a single test.

**Parser (`fetch_geogebra_dimensions`), `_open` patched, `GEOGEBRA_API_LOOKUP=True`:**
- `wseg.json` → `(880, 660)` from top-level `settings`
- `ws.json` → `(880, 660)` from `elements[0]["settings"]`
- **derived** fixture (real `ws.json` hand-edited to put a non-`"G"` element first) → the
  first `"G"` entry is used. Flagged as derived: no captured response exhibits this, and the
  fixture-realism rule yields here to covering the branch.
- **derived** fixture where the first `"G"` entry has no usable pair and a later `"G"` does →
  the later one wins (pins "keep scanning")
- **derived** fixture with a top-level `settings` of layout-only keys plus a usable
  `elements[0]` → falls through to the element (pins the usable-dimensions fallthrough)
- `err_invalid_id.json` served as a 400 `HTTPError` → `(None, None)`. Note plainly: because
  `build_opener` keeps `HTTPErrorProcessor`, a 400 raises *before* `resp.read()`, so this test
  asserts only that an `HTTPError` degrades — the fixture's body is documentation of the real
  error shape, not an input the assertion depends on.
- timeout / `URLError` / invalid JSON / missing `settings` → `(None, None)`, no raise
- `_open` raising an **unlisted** exception type (e.g. `ssl.SSLError`) → `(None, None)`,
  proving the bare `except Exception`
- `width` of `0`, `-5`, `"880"`, `2147483648`, `True`, `880.0` → `(None, None)`
- body exceeding `_MAX_BODY_BYTES` → `(None, None)`
- **User-Agent:** the `Request` handed to `_open` carries `_USER_AGENT`, not `Python-urllib`
- **timeout argument:** `_open` receives `timeout=_TIMEOUT_SECONDS`. State precisely what this
  pins — it proves the *caller* passes the constant, and **nothing more**. The
  forgotten-`timeout=`-kwarg bug lives at `opener.open(...)` *inside* `_open`, below the patch
  point, so this test stays green on that broken build. To guard the socket timeout itself,
  add a separate assertion at the `OpenerDirector.open` / `build_opener` level, or keep `_open`
  a one-expression function and assert its body directly.
- **redirects:** a `_NoRedirect` unit test asserting `redirect_request` refuses (or, if
  `integrations/delivery.py` already has equivalent coverage, name that test and state the
  reuse). Without this the one behaviour called out as an SSRF control is unfalsified —
  and it cannot be exercised at the `_open` seam, where the handler never runs.
- **negative cache:** two consecutive failing calls for the same id issue exactly **one**
  `_open` call
- **kill switch** (the one test under the `False` default): `_open` never called, result
  `(None, None)`

**`geogebra_material_id`** — literal inputs, not category names:
- `https://www.geogebra.org/m/dcjktevj` → `"dcjktevj"`
- `https://geogebra.org/m/dcjktevj` → `"dcjktevj"` (bare host; `_GEOGEBRA_HOSTS` admits both)
- `https://www.geogebra.org/material/show/id/dcjktevj` → `"dcjktevj"`
- `https://www.geogebra.org/material/iframe/id/dcjktevj` → `"dcjktevj"`
- `https://www.geogebra.org/m/bad id` → `""` (the `_ID_RE` charset gate)
- `https://www.geogebra.org/classic/dcjktevj` → `""` (app link, not a material URL — stated
  explicitly because "classic" is otherwise ambiguous with `/material/show/`)
- `https://www.geogebra.org/x` → `""` (the LAL-stored shape)
- `http://www.geogebra.org/m/dcjktevj` (non-https) → `""`
- `https://beta.geogebra.org/m/dcjktevj` (subdomain) → `""`
- `https://example.com/m/dcjktevj` → `""`

Existing `canonicalize_geogebra_url` tests must still pass **unchanged** — the regression
guard on promoting `_material_id`.

**Form** (patching `courses.element_forms.fetch_geogebra_dimensions`):
- static embed paste → dimensions captured, lookup called **zero** times
- **edit of an element with stored 880×660**, same URL, title changed → lookup called
  **zero** times, dimensions unchanged (the instance-guard regression test)
- lookup returning a *different* pair for an element that already has one → stored values
  unchanged (the invariant asserted directly, not inferred from a call count)
- **edit that replaces the URL with a different share link** → stale pair cleared, lookup
  called **once**, new dimensions stored (the URL-change regression test)
- share-link paste on a fresh element, lookup returns `(880, 660)` → instance carries 880×660
- share-link paste, lookup returns `(None, None)` → form valid, dimensions stay NULL
- re-paste of a different full `<iframe>` → dimensions overwritten, lookup not called
- non-GeoGebra plain URL → lookup not called
- GeoGebra host without a material id (`https://www.geogebra.org/x`) → lookup not called

**Render:**
- GeoGebra material, 880×660 → `aspect-ratio: 880 / 660`, src ends `/width/880/height/660`
- GeoGebra material, no dimensions → `aspect-ratio: 800 / 600`
- GeoGebra material, `(800, None)` / `(None, 600)` / `(0, 0)` → `aspect-ratio: 800 / 600`
- GeoGebra **host, no material id** (`/x`) → **no** inline `aspect-ratio`
- non-GeoGebra, no dimensions → **no** inline `aspect-ratio` (16:9 CSS default stands)
- non-GeoGebra, `(800, None)` / `(0, 0)` → no inline `aspect-ratio`

**Existing tests that must be updated — not bugs in the implementation.**
`tests/test_iframe_dimensions.py` defines `URL = "https://www.geogebra.org/material/iframe/id/abc"`,
i.e. a **GeoGebra** URL:

| test | inputs | today | after |
|---|---|---|---|
| `test_render_falls_back_to_16x9_when_dimensions_unknown` | `(None, None)` | no inline ratio | `aspect-ratio: 800 / 600` |
| `test_render_falls_back_when_dimensions_partial_or_zero` | `(800, None)`, `(None, 600)`, `(0, 0)` | no inline ratio | `aspect-ratio: 800 / 600` |
| `test_form_bare_url_paste_leaves_dimensions_none` | bare GeoGebra URL, fresh instance | asserts no capture | **now passes via the kill switch**, not via "no lookup fires" — rename or annotate so it is not misread as independent confirmation |
| `test_form_oversized_paste_degrades_without_500` | oversized `<iframe>` | as today | same caveat: green under `GEOGEBRA_API_LOOKUP=False` |

The first two must be rewritten to the new expectation, and the "16:9 default stands"
coverage re-pointed at a **non-GeoGebra** URL (a second module constant, e.g.
`OTHER_URL = "https://example.com/embed/abc"`). An implementer not told this will read the
failures as a defect in their own code.

**Editor row:**
- GeoGebra material without dimensions → badge present, with the tooltip text
- GeoGebra material with dimensions → badge absent
- GeoGebra material with a partial/zero pair → badge present (mirrors `frame_ratio`)
- GeoGebra host without a material id → badge absent
- non-GeoGebra without dimensions → badge absent

**Import:** an existing round-trip test is extended to assert the import path performs no
GeoGebra lookup, guarding the `extract_embed_url` boundary decision.

Every test is falsified to RED before it counts. The one deliberate exception is the
`_API_PREFIX` defensive check, unreachable by construction and therefore specified as
untested rather than given a test that cannot fail.

## Risks

- **GeoGebra changes the 800×600 default or the shell.** The 4:3 fallback would drift. Low
  impact: it governs only the degraded path, and the primary path stores real dimensions.
- **A save depends on a network call made while holding the unit's row lock** (§2). Mitigated
  by the first-save/URL-change-only invariant, the socket timeout, the capped read, and the
  negative cache; explicitly accepted, with the restructuring alternative recorded.
- **The worst-case save latency is not hard-bounded** (see Error handling). A slow-drip
  endpoint or a stalled DNS resolver can exceed the nominal 3s.
- **A retry within 60s of a failure is suppressed** by the negative cache, and outside tests
  that cache is per worker process.
- **API shape or endpoint change.** Handled by the never-raises contract: an unrecognised
  shape degrades to the fallback. Detection relies on the `logger.warning` and the pre-PR
  live check, since no automated test touches the network.
