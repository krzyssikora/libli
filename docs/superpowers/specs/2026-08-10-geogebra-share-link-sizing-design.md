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
the PR body — the offline test suite cannot detect the API moving.

**Two short-circuits can fake a pass, and the check must defeat both.** Each returns
`(None, None)` with no request, indistinguishable from "the API moved":

1. a negative-cache sentinel from an earlier failed attempt — so **clear the default cache,
   or run in a fresh process**, immediately before the check;
2. `GEOGEBRA_API_LOOKUP` being false — which is exactly what `config/settings/test.py`
   ships, and `manage.py` resolves `DJANGO_SETTINGS_MODULE` from the environment
   (`default="config.settings.local"`), so a developer `.env` can silently pin it.

So the check must run under **`config/settings/local`** with the flag true, and must assert
**positively**: the returned pair equals `(880, 660)`. "It did not raise" is not a pass.

### Scope in existing content, and every creation path

**Census — taken against the local dev database `libli`, which is the one containing
`mat-pp`** (the same database serving the `/courses/mat-pp/u/294/` page where this defect
was reported). Naming the database matters: a count taken against a mat-pp-free database
would say nothing about the real content set.

Because `frame_ratio` keys on URL **shape** as well as on dimensions (§3), the census is
split by both. The counting predicate for "canonical" is a deliberately **looser superset**
of `is_geogebra_iframe_url`: GeoGebra host, segments starting `["material","iframe","id"]`,
no `width` segment — but it omits the https-scheme check and the `_ID_RE` id check that the
real predicate applies. So it can over-count, classifying as "canonical" a row the predicate
would reject (an `http://` URL, or an id failing the charset gate). It over-counts by zero
here — every row measured is https with a clean id — but a re-run on different data must
apply the stricter clauses before trusting the "canonical" column.

| course | URL shape | dimensions | rows |
|---|---|---|---|
| `mat-pp` | canonical | **usable** | **131** |
| `mat-pp` | non-GeoGebra | none | 5 |
| `demo-course` | canonical | usable | 1 |
| `demo-course` | canonical | **none** | **2** |

**Every GeoGebra row in the database is already canonical shape** — there are zero
GeoGebra-host-but-non-canonical rows, so the step-1 `None` branch of `frame_ratio` matches
nothing that exists today. Plus one orphaned `IframeElement` (`…/id/abc123`) with zero join
rows — a leftover fixture on no page.

So of 134 GeoGebra rows, exactly **two reachable ones lack dimensions**, both in
`demo-course` (units 16 and 106). **No published mat-pp unit changes appearance:** its 131
GeoGebra rows are canonical *and* dimensioned, so they emit `aspect-ratio: W / H` before and
after; its 5 non-GeoGebra dimensionless rows keep the 16:9 CSS default untouched.

### Why the reported page already looks correct — and how to reproduce the defect

That last paragraph appears to contradict the bug report, which named
`/courses/mat-pp/u/294/`. It does not, and the resolution is the acceptance path.

Unit 294 currently holds **two** GeoGebra iframes — elements 22019 (`…/id/wgzr7tsu`) and
22024 (`…/id/safjjtdz`) — both canonical and both stored 880×660. Those are the
**static-embed-code** versions. The original report says so explicitly: adding the material
*by share link* showed the white space, and adding it *by the embed code GeoGebra suggests*
looked right. The author had already replaced the broken element with the working one before
the census was taken. So unit 294 renders correctly today **because the bug was worked
around**, not because it was absent — and it is inside the 131.

**Acceptance path, therefore, is a fresh reproduction, not a revisit of unit 294:** in a
scratch unit, add material `dcjktevj` (or any GeoGebra material) *by share link*
`https://www.geogebra.org/m/dcjktevj`, and confirm the applet fills its frame with no
right-hand gap and the same viewport as the static embed. Before the change that element
renders 16:9 with the measured ~161px gap; after it, it must be indistinguishable from an
element created with the embed code.

That census is a snapshot, so here is every path that constructs an `IframeElement` and
whether it gets the lookup:

| path | gets the lookup? | why |
|---|---|---|
| `IframeElementForm` (editor create/edit) | **yes** | the interactive path this design targets |
| `courses/lal_loader/builders.py:350` (`IframeElement.objects.create(url=…, title=…)`) | **no** | bulk mat-pp ingest; a per-element network call would make a large import slow and network-dependent |
| `courses/management/commands/seed_demo_course.py` | **no** | fixture seeding, not authored content |
| `courses/transfer` import (`_build_iframe`) | **no** | archives from `FORMAT_VERSION` ≥ 2 carry the pair, so a lookup would be redundant *and* would put the network in the import path. A **legacy v1 archive** carries neither — `payloads.py:169-175` `setdefault`s both to `None` for exactly that reason — so it imports dimensionless and lands on the 4:3 + badge path, which is the intended degraded behaviour rather than an oversight |
| Django admin (`admin.site.register(IframeElement)`) | **no** | raw model form, no `clean_url`; a staff-only escape hatch |

Note the tension between rows one and two of that table and the census: `builders.py:350` is
`IframeElement.objects.create(url=canonicalize_geogebra_url(el["url"]), title=…)` — canonical
shape, **no** dimensions — yet mat-pp measures 131/131 *with* dimensions. Both facts are
measured, and the reconciliation is **not** established. Candidate explanations, none
verified: the rows arrived via `courses/transfer` (`_build_iframe` does carry `width`/
`height`) rather than the LAL loader; the loader had a different shape when mat-pp was
ingested; or the elements were re-saved through the editor form afterwards.

Because three decisions lean on that column — the no-appearance-change claim, the no-backfill
non-goal, and the blast-radius estimate — **the census must be reproducible rather than
believed.** This is the literal query; re-run it before implementing and restate the sections
below if the numbers differ:

```python
from urllib.parse import urlsplit
from collections import Counter
from courses.models import IframeElement
c = Counter()
for o in IframeElement.objects.all():
    for e in o.elements.all():                      # join rows; 0 joins == orphan
        p = urlsplit(o.url); segs = p.path.split("/")[1:]
        host = (p.hostname or "").lower()
        shape = ("non-geogebra" if host not in ("geogebra.org", "www.geogebra.org")
                 else "canonical" if segs[:3] == ["material","iframe","id"] and "width" not in segs
                 else "canonical+width" if segs[:3] == ["material","iframe","id"]
                 else "gg-host-other")
        c[(e.unit.course.slug, shape, bool(o.width and o.height))] += 1
```

If the 131 turn out to be dimensionless, the consequences are concrete and must be written up
rather than discovered: 131 published units flip 16:9 → 4:3, every one grows a badge, and
every subsequent save of any of them fires a live GET inside the unit row lock (case 3).

Independent of the reconciliation, the forward-looking consequence holds: **any future LAL
import produces dimensionless GeoGebra elements**, which now render at 4:3 with a badge
instead of silently at 16:9.

### Goals

1. A GeoGebra material added by share link **through the editor** renders identically to the
   same material added by its static embed code — no white space **and** no crop.
2. When the authored size cannot be determined, fall back to **4:3** (GeoGebra's own
   default, measured to leave a 0.0px gap) instead of today's 16:9.
3. When the authored size cannot be determined, tell the author so, non-blockingly, with a
   concrete workaround.
4. Authoring never fails because geogebra.org is slow or unreachable.

### Non-goals

- **No backfill mechanism.** The decision rests on the census and the recovery path, not on
  the absence of a deployment: two reachable rows are affected, both in `demo-course`, the
  user will fix them by hand, and any row missed anywhere is self-announcing (the badge) and
  self-healing (re-saving re-attempts the lookup, per case 3). The user confirms there is no
  deployment and no production database **today** — but `config/settings/production.py`
  exists and is fully env-driven, so a deployment is anticipated, and no argument here may
  depend on one never existing.
- **No lookup on the bulk paths** (LAL loader, seed command, transfer import, admin).
- **No manual width/height fields in the editor.** Considered and rejected during
  brainstorming; the static embed paste remains the explicit escape hatch.
- **No change to non-GeoGebra embeds.** The 4:3 correction is scoped to the provider it
  was measured against; every other provider keeps the 16:9 CSS default.
- **No periodic re-fetch or staleness handling.** Dimensions are re-derived only when the
  URL changes (§2). If an author resizes a material on geogebra.org without changing its
  URL, re-pasting the embed code is the way to update our copy.
- **No new e2e test *for the embed itself*.** An end-to-end assertion on the rendered applet
  would depend on geogebra.org being reachable and would be flaky. The browser measurements
  above are the evidence for the ratio; the render assertions cover the code path; the
  one-off live check covers the API contract. **Explicitly carved out of this non-goal:** the
  editor-row layout check at 1130px (§4), which touches no network — it drives only our own
  editor page. See Testing for its mechanism.
- **No migration and no `FORMAT_VERSION` bump.** `IframeElement.width`/`.height` already
  exist and are nullable, and nothing new is persisted on the model.

## Architecture / components

Nine deliverables, in five sections: (1) the lookup helper, the three predicates
(`usable_dimensions`, `is_geogebra_iframe_url`, `geogebra_url_size`), and the rewritten module
docstring in `courses/geogebra.py` **and** the rewritten `clean_url` comment in
`courses/element_forms.py:186-190` (its current text — "a plain-URL / dimensionless input
leaves stored dims unchanged" — becomes false under the three firing cases and the
URL-change clear; keep its ceiling clause, restate the rest); (1b) the `_INT_MAX` → `DIM_MAX` fold in
`courses/embed.py`, **three** sites including the `_dimension` docstring, gated on
`grep -rn "_INT_MAX"` returning zero hits; (2) the `clean_url` capture; (3) the two model
properties and the consumption-template switch; (4) the editor badge **and** the new
`.el-row__flag` CSS rules **and** the Polish catalog entries; (5) the `GEOGEBRA_API_LOOKUP`
flag in **both** `config/settings/base.py` and `config/settings/test.py`, plus its
`.env.example` line. Test-side, three checked-in fixtures under `tests/fixtures/geogebra/`
(`ws.json`, `wseg.json`, `err_invalid_id.json`) plus the derived variants named in Testing.

### 1. Lookup helper — `courses/geogebra.py`

This module stays the single GeoGebra parser. It gains constants, a transport seam, and
three public functions.

**Its module docstring must be rewritten as part of this change** — a deliverable, not a
nicety. The current one ends *"It never raises — validation stays entirely in
`validate_embed_url`"* and describes a pure-parsing module with no network, no cache, and no
settings dependency. All three of those become false here, and a stale docstring at the top
of the file is the first thing the next reader trusts. The new text states the new contract:
URL parsing plus one capped, non-raising network lookup behind a kill switch.

```python
GEOGEBRA_DEFAULT_SIZE = (800, 600)   # GeoGebra's own iframe-shell fallback → 4:3
_API_PREFIX = "https://api.geogebra.org/"
_TIMEOUT_SECONDS = 3          # a module constant rather than a setting, matching the pattern
                              # of integrations/delivery.py :: TIMEOUT_SECONDS = 10; the
                              # shorter 3s is chosen because this call sits inside a row lock
_MAX_BODY_BYTES = 65536
_NEGATIVE_TTL_SECONDS = 60
_USER_AGENT = "libli/1.0 (+https://github.com/krzyssikora/libli)"
DIM_MAX = 2147483647          # PositiveIntegerField ceiling; no underscore — see below

def usable_dimensions(width, height) -> bool    # the shared dimension predicate — see §3
def is_geogebra_iframe_url(url) -> bool         # the render/badge predicate — see §3
def geogebra_url_size(url) -> tuple[int, int] | tuple[None, None]   # frame_ratio step 0
def _open(request, timeout)                     # the transport seam tests patch
def geogebra_material_id(url) -> str            # the lookup gate
def fetch_geogebra_dimensions(material_id) -> tuple[int, int] | tuple[None, None]
```

**Why these live here.** `usable_dimensions` is provider-neutral, yet `courses/geogebra.py`
is the only module in `courses/` that imports nothing from its own package — which makes it
the sole cycle-free home. The alternatives both create cycles or churn:
`courses/embed.py` already imports `geogebra`, so the predicate cannot live there without
inverting that edge, and `courses/models.py :: embed_src` deliberately imports `geogebra`
*lazily inside the method* to avoid a models→geogebra edge at import time. Putting the
predicate in `geogebra.py` lets `embed.py`, `element_forms.py`, and `models.py` all import it
at module level safely. **Decision on the existing lazy import: leave it alone.**
`embed_src` keeps its in-method `from courses.geogebra import geogebra_sized_src` and its
explanatory comment untouched — this change does not need to disturb it — while
**all five** names `frame_ratio`/`size_unknown` need — `usable_dimensions`,
`is_geogebra_iframe_url`, `geogebra_url_size`, `geogebra_material_id`, and
`GEOGEBRA_DEFAULT_SIZE` — are imported at module level in `models.py`. The cycle argument
covers them equally, so listing only two would invite an implementer to import the rest
lazily "for consistency" with `embed_src`. `geogebra_sized_src`'s in-method import is the
**sole** documented exception.
The comment is amended only to note that the module-level predicates are safe for the same
reason (`geogebra.py` imports nothing from `courses`), so the two import styles in one file
do not read as an accident. `embed.py`'s existing `_INT_MAX` is folded into `DIM_MAX` here so the
ceiling has one definition. The fold touches **three** sites in `embed.py`, not two — the
definition (line 27), the comparison (line 42), and the `_dimension` **docstring** (line 31,
"A positive int (1.._INT_MAX)…"), which would otherwise name a constant that no longer
exists. `grep -rn "_INT_MAX"` must return zero hits afterwards. **Both** `usable_dimensions` and `DIM_MAX` deliberately carry
**no leading underscore**: each is imported across module boundaries, and an underscore on a
cross-module name invites a reviewer to "fix" the import by re-declaring the thing locally —
the exact duplication these exist to prevent. The rule is applied consistently: names that
cross a module boundary are public, names that do not (`_open`, `_API_PREFIX`,
`_TIMEOUT_SECONDS`, `_MAX_BODY_BYTES`, `_NEGATIVE_TTL_SECONDS`, `_USER_AGENT`, `_ID_RE`) keep
the underscore.

**`geogebra_url_size(url)` — the parser behind `frame_ratio` step 0.** A URL of the form
`…/material/iframe/id/<id>/width/<W>/height/<H>` sizes the applet itself, so the frame must
match *it*. This needs its own function: `is_geogebra_iframe_url` returns **`False`** for
exactly that shape (the `"width" in segments` clause), so neither existing predicate can
serve, and without a named home an implementer would inline `urlsplit(...).path.split("/")`
inside `IframeElement.frame_ratio` — on the render path, with no guard.

Its contract, all three parts load-bearing:

- **Scoped like the other predicates, not to any URL carrying `width`/`height` segments.**
  It requires https, a GeoGebra host, and `segments[:3] == ["material","iframe","id"]`. A
  bare "the path contains `width`" rule would fire on a stored
  `https://player.vimeo.com/video/1/width/4/height/3` and give a non-GeoGebra embed an inline
  ratio it does not have today — contradicting the "no change to non-GeoGebra embeds"
  non-goal. The justification for step 0 ("such a URL sizes the applet itself") is a fact
  about the GeoGebra iframe shell only.
- **Validated exactly like every other dimension source, at fixed positions.** The tail must
  sit **immediately after the id** and be the whole path: `segments[4:8] == ["width", W,
  "height", H]` **and** `len(segments) == 8`. Both values must parse as decimal ints and pass
  `usable_dimensions` (1..`DIM_MAX`). The positional rule is stated because index-searching
  (`segments.index("width")`) silently accepts a trailing
  `…/width/880/height/660/width/999`, contradicting the repeated-segment rejection below.
  Anything else — `/width/abc/height/def`, `/width/880` with no height, `/width/0/height/0`,
  a reversed `…/height/H/width/W`, a repeated `width` segment, or extra segments before the
  tail — returns `(None, None)` and falls through to step 1.

  **This is a security boundary, not tidiness.** `frame_ratio`'s value is interpolated into
  `style="aspect-ratio: {{ el.frame_ratio }}"`. Django's autoescape covers `< > & " '` — it
  does **not** escape `;` or `:`, both of which are legal in a URL path segment. An
  admin-stored `…/width/1;position:fixed;top:0;height:100vh/height/1` would otherwise inject
  arbitrary declarations into the style attribute, on precisely the path this design already
  identifies as "reachable through the admin, which exposes `url` raw". Returning ints, never
  strings, closes it: the rendered value is built from two validated integers.
- **Never raises**, under the same guard as the predicates below.

**All three predicates never raise, and that contract is new.** `geogebra_material_id`,
`is_geogebra_iframe_url` and `geogebra_url_size` are called on arbitrary stored URLs *during
page render* (`frame_ratio`/`size_unknown` run while a student unit template renders) and
inside `clean_url`. `geogebra_url_size` matters most here because it runs **first** in
`frame_ratio`, ahead of every other branch — an unguarded `urlsplit("https://[::1")` there
500s the student unit page before any fallback can be reached. Today the `try/except (ValueError, TypeError, IndexError)` around
`urlsplit`/`.hostname` lives in `canonicalize_geogebra_url`, because a malformed authority
such as `https://[::1` really does raise. Promoting `_material_id` without carrying that
guard across would let a single bad row — written by an admin or a future importer — 500 the
render path. So the guard moves **into** both predicates, and `canonicalize_geogebra_url`
inherits it rather than wrapping it. Each gets a malformed-authority test.

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
with _open(req, timeout=_TIMEOUT_SECONDS) as resp:        # keyword, not positional
    payload = resp.read(_MAX_BODY_BYTES + 1)              # +1 so oversize is detectable

def _open(request, timeout):                      # the seam
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)
```

**`timeout` is passed by keyword** at the call site so the seam's contract is unambiguous
and the test can assert `call_args.kwargs["timeout"]`. An earlier draft passed it
positionally while the test asserted a keyword — two normative sections disagreeing, which a
TDD implementer hits on the first red-green cycle.

The `with` is required, not stylistic: `integrations/delivery.py` — the cited precedent —
uses `with opener.open(...) as resp:`, and because the read is capped the connection is
never drained, so an unclosed response leaks a socket per call and raises `ResourceWarning`
in tests. **The test double for `_open` must therefore be a context manager.**

**The `with` does not cover the error path.** Because `build_opener` keeps
`HTTPErrorProcessor`, a 4xx/5xx raises `HTTPError` from *inside* `_open`, so the `with` block
is never entered and the exception's own `fp` is never closed — leaking exactly the socket
the `with` was justified to protect, on the most common failure. Close it explicitly in the
handler (`exc.close()` / `exc.fp.close()`), or the 400 test will surface an unexplained
`ResourceWarning`.

Refusing redirects matters: `urlopen` follows them by default, so a check on the
*constructed* URL says nothing about the host actually contacted.
`integrations/delivery.py :: _NoRedirect` already exists for exactly this reason — but
**duplicate it in `courses/geogebra.py` with a comment pointing at the original; do not
import it.** This is decided here, not left to the plan, because the import has a real cost:
`integrations/delivery.py` does `from integrations.models import WebhookDelivery` at module
level, so importing `_NoRedirect` into `geogebra.py` — which `models.py` now imports at
module level — would pull `integrations.models` in at app-load time. Every existing
`courses → integrations` reference in the repo is a deliberate lazy in-function import
(`courses/review.py:71,100`, `courses/views.py:1565`), and §1 justifies `geogebra.py` as the
sole cycle-free home precisely because it imports nothing from its own package. Reaching
across an app boundary for a private four-line handler would trade that away. (A
function-local import inside `_open` would also work; duplication is preferred because the
handler is trivial and the comment keeps the two discoverable from each other.)

The URL is `_API_PREFIX + "v1.0/materials/" + material_id + "?scope=basic"`, where
`material_id` has passed `_ID_RE` and so cannot introduce a scheme, host, or traversal. A
`startswith(_API_PREFIX)` check on the constructed URL is **defensive only and unreachable
by construction** — deliberately *not* claimed as a security control and given **no test**,
because a branch that cannot be driven cannot be falsified to RED. The real controls are
`_ID_RE` and the no-redirect opener. Observed ids are 8 characters; `_ID_RE` is unbounded,
acceptable because the URL reaching this code has already passed `URLField`'s length cap —
noted so nobody mistakes `_ID_RE` for a length guard.

**Body handling.** Read `_MAX_BODY_BYTES + 1` bytes; if the read comes back full-length the
body is **oversized** — log it as such and return `(None, None)`. Reading one byte past the
cap is what makes "too large" *distinguishable* from "not JSON" in the warning log, instead
of both surfacing as a parse failure. The socket timeout alone does not bound how much a
slow or hostile endpoint can send.

The cap is sized against measurement, not guessed: the captured responses are **1,177 bytes**
(`ws`/`dcjktevj`), **891 bytes** (`wseg`/`wgzr7tsu`), and **35 bytes** (the 400). At 65,536 the
cap leaves ~55× headroom over the observed worksheet. A worksheet with many elements is
larger — each carries its own `settings` and `thumbUrl` — so the failure mode is worth
naming: a *valid* material whose document exceeds the cap degrades to the 4:3 fallback plus a
badge, indistinguishable to the author from a genuinely dimensionless one. The `logger.warning`
oversize signal is the only way to tell them apart, which is why it must say which case fired.

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
2. Otherwise scan `elements` in **array order** (the literal JSON sequence — *not* sorted by
   the `"order"` field, which the sample also carries and which can differ) and collect
   entries with `elements[N]["type"] == "G"` **whose settings yield a usable pair**. Keep
   scanning past a `"G"` entry that does not — do not stop at the first `"G"`.
   - **Exactly one** such entry → return its pair.
   - **More than one** → return `(None, None)` and log it. The iframe embeds the *whole
     worksheet*, not one applet, so on a multi-applet worksheet "the first `G`" is an
     arbitrary pick that need bear no relation to the rendered worksheet's aspect ratio.
     Guessing there would produce a confidently wrong frame with `size_unknown` False —
     no badge, no warning — which is strictly worse than falling back to 4:3 with both.
     Every captured `ws` document has exactly one element, so first-wins has no evidence
     behind it and the conservative branch is the honest one.
3. If nothing yields a usable pair, return `(None, None)`.

**On `"G"`:** it is the type code carried by the applet element in every captured response
(`elements[0]["type"] == "G"`, verified live). The full set of element type codes a worksheet
may contain is **not** established here — a worksheet can hold text and other blocks — so no
behaviour is specified for a hypothetical second applet code, and a non-`"G"` entry is never
used as a fallback. The `logger.warning` must therefore distinguish the step-2 failure modes
— "no `G` element found", "`G` elements had no usable dimensions", and "multiple sized `G`
elements" — because the Observability section's whole purpose is telling a schema change
apart from a genuinely sizeless material.

**Every access in that scan is defensive, per entry.** This is not a style note: the whole
fetch-and-parse body is wrapped in a bare `except Exception`, so a single malformed entry
raising mid-scan would abort the *entire* loop and return `(None, None)` even when a later
valid `"G"` entry exists — silently contradicting "keep scanning". So a top-level `settings`
that is not a dict, an `elements` value that is not a list, and any entry that is not a dict
are **skipped, not fatal**: check types with `isinstance` and read with `.get`, and let the
outer catch handle only genuinely unexpected failures.

**Never raises — a bare `except Exception`.** An enumerated tuple is insufficient:
`urlopen` can raise `http.client.RemoteDisconnected`, `ConnectionResetError`, `ssl.SSLError`
variants, `UnicodeDecodeError` on a mis-encoded body, and `ValueError` from `Request()`
construction, none of which are `URLError` subclasses. Anything escaping into `clean_url`
would 500 the save. Wrap the whole fetch-and-parse body in a bare `except Exception:`,
matching `courses/embed.py :: parse_iframe_dimensions`.

**Observability.** `courses/geogebra.py` has no logger today; add
`logger = logging.getLogger(__name__)` at module scope, mirroring `integrations/delivery.py:16`.
Tests assert on `record.name == "courses.geogebra"` as well as message content, so a
`caplog` assertion cannot be written against the wrong logger and pass vacuously. On any
failure path, emit a `logger.warning` carrying the material id and the exception type (or
HTTP status). Without it, a systemic failure — API path changed,
schema reshaped, UA blocked — is indistinguishable from "this material genuinely has no
dimensions", and the only signal is a badge the author reads as a property of their own
material. A successful lookup logs nothing.

**Negative cache.** A failed lookup caches a **truthy** sentinel —
`cache.set(key, True, _NEGATIVE_TTL_SECONDS)` under `geogebra:dims:<material_id>` — and a
cached sentinel short-circuits to `(None, None)` without a request. The value must be truthy
(or the read must use an explicit miss marker, `cache.get(key, _MISS)`): the natural-looking
`cache.set(key, None, …)` is indistinguishable from a miss under `cache.get(key)`, which
would make the entire negative cache a silent no-op that no test would notice. Only failures are cached; a success is persisted on the
model. This bounds the repeat cost: without it, every subsequent save of a dimensionless
element re-pays the full timeout while holding a row lock. The TTL is deliberately short —
the badge invites the author to retry, and a longer window would make that retry fail
deterministically with no request issued, which reads as an inexplicable bug. **Accepted
consequence:** a retry within 60 seconds of a failure is suppressed. Note also that
`config/settings/base.py` defines **no `CACHES`**, so Django's implicit per-process
`LocMemCache` applies — outside tests this bound is per worker process, not per site.

**Kill switch.** When `settings.GEOGEBRA_API_LOOKUP` is false, return `(None, None)`
immediately — no cache read, **no cache write**, no request. The write half matters: the
natural refactor to a shared `return _fail(mid)` exit that logs *and* caches would poison the
sentinel for 60s on the kill-switch path, so flipping the flag back on would still
short-circuit for a minute on every id an author had touched while it was off. **The flag is read inside
`fetch_geogebra_dimensions` on every call, never captured at import time.** A module-level
`LOOKUP = settings.GEOGEBRA_API_LOOKUP` would make every `override_settings(...=True)` a
silent no-op; the positive-assertion tests would catch that, but the invalid-input tests
would go on passing *vacuously* — the exact failure mode the `override_settings` requirement
exists to prevent.

### 2. Capture — `IframeElementForm.clean_url`

The existing `parse_iframe_dimensions` capture is unchanged and runs first. The lookup is
attempted only when dimensions are unknown in the paste **and** the instance has no usable
pair **for this same URL**:

```python
url = extract_embed_url(raw)
width, height = parse_iframe_dimensions(raw)
mid = geogebra_material_id(url)                 # hoisted: used by both guards below
url_changed = url != self.instance.url
if url_changed and not usable_dimensions(width, height) and mid:
    self.instance.width = self.instance.height = None   # stale: they describe the old material
stored_usable = usable_dimensions(self.instance.width, self.instance.height)
if not usable_dimensions(width, height) and not stored_usable and mid:
    width, height = fetch_geogebra_dimensions(mid)
if usable_dimensions(width, height):
    self.instance.width = width
    self.instance.height = height
return url
```

**This depends on `clean_url` running before `_post_clean`.** `self.instance.url` still holds
the **database** value during field cleaning, because Django only copies cleaned data onto the
instance in `construct_instance`, which `_post_clean` calls afterwards. The entire
`url_changed` mechanism silently inverts — every save looking like "URL unchanged" — if this
logic is ever moved to `_post_clean` or `save()`. Stated so a future refactor is a deliberate
choice rather than a silent regression.

**Invariant: a *usable* stored pair is never re-derived for an unchanged URL.** Every word
is load-bearing, and the corollary matters as much as the rule: **the lookup fires on three
occasions, not two** —

1. a fresh element whose paste carries no dimensions,
2. an edit that changes the URL (the stale pair is cleared first), and
3. **any save of an element whose stored pair is unusable** — including a title-only rename
   of a dimensionless element.

Case 3 is deliberate, not an oversight. It is the retry path: the badge tells the author the
size is unknown, and re-saving is the natural response, so a save must be able to try again.
It is also why `_NEGATIVE_TTL_SECONDS` is only 60s — long enough to stop an outage from
re-charging the row lock on every attempt, short enough that a deliberate retry works. An
implementer who gated on `url_changed` alone would satisfy the prose but kill the retry.

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

*Why the clause is scoped to GeoGebra.* The `geogebra_material_id(url)` conjunct is
deliberate. Clearing provider-neutrally would wipe a **non-GeoGebra** element's captured
pair — a Vimeo embed pasted as `<iframe … width="640" height="360">` — the moment its URL
changed, with no lookup available to restore it, permanently reverting it to the 16:9
default. And because the textarea is pre-filled with the stored URL, *any* edit to that field
sets `url_changed`. That would be a behaviour change on non-GeoGebra content, contradicting
the stated non-goal. Scoped as written, a non-GeoGebra URL change keeps its dimensions;
a form test pins this.

*The conjunct tests the **new** URL, which leaves one case open — accepted explicitly.*
Editing a GeoGebra element's URL to a **non**-GeoGebra one (a plain Vimeo URL, no dimensions
in the paste) keeps the GeoGebra 880×660 and renders a video in a 4:3 frame. That is the same
"the pair describes the old material" failure the clause exists to prevent, in the direction
the conjunct does not cover. It is **not** a regression — today's code never clears — and the
alternative (clear when the *old* URL was GeoGebra and the new one is not) is deliberately
not taken here: it would add a second, opposite-keyed branch to a guard whose whole value is
being easy to reason about, for a provider-swap-in-place that is rare and self-evident to the
author, who can re-paste the correct embed code. Recorded as a known, bounded gap rather than
silently left undiscussed; a form test pins the current behaviour so a future change is a
deliberate one.

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

This is **accepted deliberately** rather than restructured. Note honestly what that
accepts: by case 3 above, *every* save of a dimensionless GeoGebra element issues a live GET
inside the lock once the 60s sentinel expires — and the LAL-imported population is exactly
that shape. The only thing it can block is a concurrent edit of the *same unit*, and the
mitigations — 3s socket timeout, capped body read, refused redirects, 60s negative cache —
keep the common failure path short. Moving resolution out of `clean_url`
would leak iframe-specific logic into the view layer or change `save_element`'s signature, a
larger blast radius than the risk warrants. The alternative is recorded so a future reader
can revisit it rather than rediscover the lock.

### 3. Render — a provider-aware fallback ratio

**One predicate, shared** (`courses/geogebra.py`, see §1 for why it lives there):

```python
def usable_dimensions(width, height):
    """True iff both are real, positive, in-range ints (1 .. DIM_MAX).

    bool is excluded explicitly (isinstance(True, int) is True in Python, so a
    payload of {"width": true} would otherwise render `aspect-ratio: True / 660`).
    Non-int types are rejected outright, including an integral float like 880.0.
    """
```

**The `1 .. DIM_MAX` bound is inside the predicate, not merely in the parser.** It has to
be: `IframeElement.width` is a `PositiveIntegerField` whose ceiling is *not* re-checked at
save — `clean_url`'s existing comment says so ("the ceiling is enforced in
parse_iframe_dimensions, not here") because `width`/`height` are absent from
`Meta.fields` and `_post_clean` therefore excludes them from `full_clean`. A predicate that
merely said "positive int" would accept `2147483648` from the API, assign it, and produce a
psycopg *integer out of range* on `form.save()` — a 500 on the exact path the never-raises
contract exists to protect.

Every consumer uses it: the parser's selection rule, `geogebra_url_size`, `clean_url`'s
guards, `frame_ratio`, and `size_unknown`. **One deliberate exception:** `geogebra_sized_src`
stays unchanged and keeps its bare-truthiness gate (`if not (width and height): return url`).
The two cannot diverge for a DB-loaded row — `width`/`height` are `PositiveIntegerField`, so a
stored value is either `None` or an int within range — but render tests build **in-memory**
`IframeElement`s where the values are unconstrained, so a test author must not assume the
`usable_dimensions` contract holds inside that function. That is what stops the badge and the ratio from ever disagreeing, and it pins
down the partial/zero cases that independently-nullable columns allow (`check_int_or_null` in
the transfer validator admits `(800, None)` and `(0, 0)` from an archive).

**"Is this a GeoGebra embed?" is one named predicate too — and it must match
`geogebra_sized_src` exactly.** Define
`is_geogebra_iframe_url(url)`, true only for the **canonical worksheet shape** that
`geogebra_sized_src` already rewrites. Mirror that function's guard **in full** — both
disjuncts, not just the first:

```python
segments[:3] == ["material", "iframe", "id"]   # canonical prefix
and "width" not in segments                    # ← the easily-missed second half
and _ID_RE.match(segments[3])                  # a valid id follows
```

`geogebra_sized_src` bails on `segments[:3] != [...] or "width" in segments`. Dropping the
`"width"` clause would make a stored `…/id/abc/width/880/height/660` — reachable through the
same admin path that motivates this split — `True` for the predicate while
`geogebra_sized_src` refuses to touch it, reopening the very ratio/src disagreement the
split exists to close.

**It is a *stricter* guard, not an exact mirror** — the `_ID_RE.match(segments[3])` clause has
no counterpart in `geogebra_sized_src`, which never indexes `segments[3]` at all. The two
therefore diverge on two shapes, both deliberate and both tested:

| URL | `geogebra_sized_src` | `is_geogebra_iframe_url` | why the divergence is right |
|---|---|---|---|
| `…/material/iframe/id` (no id) | would append `/width/…` | `False` (`IndexError` → the never-raises guard) | appending to an id-less URL yields a nonsense src; claiming a ratio for it would be worse |
| `…/material/iframe/id/ab%20cd` | would append `/width/…` | `False` (charset) | an id we would refuse to look up is not one whose ratio we should assert |

**What actually happens for these two is not "16:9 while the src is sized"** — an earlier
draft said so and was wrong in both directions. `geogebra_material_id` returns `""` for both
(no segment follows `id`; `%` fails `_ID_RE`), so `frame_ratio` **step 1 is skipped** and the
outcome depends only on the stored columns:

- **with** usable stored dimensions → step 2 emits `W / H`, and `geogebra_sized_src` *does*
  append `/width/W/height/H` (its guard passes: canonical prefix, no `width` segment). Frame
  and src **agree**; nothing is wrong.
- **without** stored dimensions → step 3 is skipped (the predicate is `False`), so step 4
  gives `None` → the CSS 16:9 default, while the src stays bare and GeoGebra renders its
  800×600 default. That is the original white-space defect, on these two shapes only.

Both are accepted: neither URL can be produced by `clean_url` (both fail
`extract_embed_url`/`_ID_RE`), so reaching them requires an admin hand-writing a degenerate
URL. Tests must pin the *stored-dimension precondition* explicitly rather than assuming a
16:9 outcome.

Host membership is explicitly *not* the test: `https://www.geogebra.org/x` (a shape the LAL
parser stores un-canonicalized) and `https://www.geogebra.org/classic/abc` sit on a GeoGebra
host but are not worksheet embeds. Under a host-based reading such an element would get
`aspect-ratio: 800 / 600` while `embed_src` left the src bare, forcing a full GeoGebra *web
page* into a 4:3 box and showing a badge whose workaround cannot help.

But `bool(geogebra_material_id(url))` is **also** wrong here, for the mirror-image reason:
it accepts `/m/<id>` and `/material/show/id/<id>`, which `geogebra_sized_src` does **not**
rewrite (it requires `segments[:3] == ["material","iframe","id"]`). A stored `/m/<id>`
carrying a usable pair would then get `aspect-ratio: W / H` from `frame_ratio` while the src
stayed bare — GeoGebra would render its 800×600 default inside a W/H frame, i.e. reproduce
the exact white-space defect this design exists to remove, with `size_unknown` False so no
badge explains it. The form canonicalises every URL it stores, but the **Django admin path
exposes `url`, `width` and `height` as raw model fields**, so that state is reachable with
no code change at all.

Two predicates, two jobs, stated explicitly so they cannot drift:

- `geogebra_material_id(url)` — "can I look this up?" Gates the lookup in `clean_url`, where
  the URL has already been canonicalised. Accepts every recognised material form.
- `is_geogebra_iframe_url(url)` — "will `geogebra_sized_src` rewrite this?" Gates
  `frame_ratio`'s 4:3 branch and `size_unknown`. Accepts only the canonical shape.

`IframeElement` gains two properties:

```python
@property
def frame_ratio(self):
    """CSS aspect-ratio for the wrapper, or None to keep the .embed-frame default."""

@property
def size_unknown(self):
    """True for a GeoGebra embed in the canonical material/iframe/id shape whose
    dimensions are not usable. Deliberately NARROWER than "a material embed" —
    /m/<id> and /material/show/id/<id> are excluded, because geogebra_sized_src
    will not size them either."""
```

`frame_ratio` resolves in **five** ordered steps, numbered 0–4. Steps 0 and 1 are easy to
omit and their omission silently reintroduces the original bug in one direction or the other:

0. **`geogebra_url_size(self.url)` returns a usable pair → `"W / H"` from those ints.**
   Such a URL sizes the applet itself, so the frame must match *it*, not the stored columns
   and not 16:9. Without this step the shape falls to step 4 and gets the CSS 16:9 default
   around an 880×660 applet — reproducing the original defect in the mirror direction, with
   `size_unknown` False so no badge explains it. The ratio/src invariant runs **both** ways:
   never a frame ratio the src does not back up, and never a src ratio the frame does not
   back up. (Reachable through the admin, which exposes `url` raw.) The value comes from
   `geogebra_url_size`'s validated ints — never from raw path text; see §1 for why that is a
   security boundary and not a style preference.
1. **`geogebra_material_id(self.url)` truthy AND `is_geogebra_iframe_url(self.url)` false
   → `None`.** A GeoGebra material in a shape `geogebra_sized_src` will not rewrite *and*
   which carries no sizing of its own. Stored dimensions must be *ignored* here, because
   emitting `W / H` while the src stays bare frames GeoGebra's 800×600 default in a W/H box —
   the exact white-space defect this design removes. This step must come **before** step 2,
   or a `/m/<id>` row carrying 880×660 takes the ratio branch and contradicts the render test
   that pins it.
2. `usable_dimensions(self.width, self.height)` → `"<width> / <height>"`. This is also the
   branch every **non-GeoGebra** provider with a captured pair (Vimeo, YouTube) reaches —
   step 1 cannot swallow them, since `geogebra_material_id` is falsy for them.
3. `is_geogebra_iframe_url(self.url)` → `"800 / 600"`, formatted from
   `GEOGEBRA_DEFAULT_SIZE` so the constant is the single source of truth. Same ratio as
   `4 / 3`, renders identically; the spec and tests use the literal `800 / 600` throughout to
   avoid an implementer/test mismatch.
4. else → `None`

So a partial or zero pair on a canonical GeoGebra embed takes step 3, a non-canonical
GeoGebra material takes step 1, and anything else takes step 4 — never a malformed
`aspect-ratio: 800 / None`, and never a ratio the src does not back up.

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

`templates/courses/manage/editor/_element_row.html` dispatches on element type through six
top-level `{% elif %}` branches (revealgate, tabs, twocolumn, spoiler, beforeafter, callout);
an iframe element falls through to the **terminal `{% else %}` block** (currently line 300),
which is where the badge goes. The concrete object is in scope as
`obj` — **not** `el`, which is the join row — so the condition is `{% if obj.size_unknown %}`.

```html
<span class="el-row__flag"
      title="{% trans 'The applet size is unknown, so it renders in a 4:3 frame and may be cropped. Paste the <iframe> embed code for exact sizing.' %}">{% trans "applet size unknown" %}</span>
```

The tag argument inside the attribute uses **single quotes**, matching every other
`{% trans %}`-in-attribute in this template (e.g. `title="{% trans 'Drag to reorder' %}"`).
The double-quoted form parses, but it reads as a quoting bug and breaks the moment anyone
adds a literal `"` to the string.

Both strings are autoescaped (never `|safe`), so the literal `<iframe>` reaches the DOM as
`&lt;iframe&gt;` and displays to the author as `<iframe>`. Backticks elsewhere in this spec
are markdown and are **not** part of the string.

**A CSS rule is required — `.el-row__flag` is currently unstyled.** An earlier draft claimed
reuse made CSS unnecessary; that was wrong. `grep -rn "el-row__flag"` over the worktree
returns exactly one non-spec hit — `_element_row.html:29`, the revealgate flag — and **no
selector in `courses/static/courses/css/editor.css` or any other stylesheet**. Shipping the
badge without a rule would put unstyled inline body text inside the flex `.el-row__top`,
violating the repo's "every view ships styled" rule rather than satisfying it. Add a rule
beside `.el-tag` (editor.css:79), mirroring its token usage:

```css
/* Typography only — applies to this badge AND the existing revealgate flag. */
.el-row__flag { font-size: .7rem; color: var(--text-secondary); }
.el-row__flag[title] { cursor: help; }
/* Shrink behaviour is scoped to the badge's own context, NOT shared — see below. */
.el-row__top > .el-row__flag {
  flex: 0 1 auto; min-width: 0;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
```

**The shrink properties are deliberately not shared with the revealgate flag.** That flag
(`_element_row.html:29`, "inactive in quizzes") is a shipped, load-bearing warning sitting in
a different flex row. Today it has `min-width: auto` and never shrinks below its text. Giving
it `min-width: 0` + `overflow: hidden` + ellipsis would let it degrade to "inactive in…" or
nearly vanish at a narrow split — a *behavioural* change to an existing surface, in a change
described as purely additive. Splitting the rule means the revealgate flag gains only the
typography it always should have had, and the badge alone becomes shrinkable. `cursor: help`
stays attribute-scoped for the same reason: that flag has no `title`, so an unscoped rule
would promise it a tooltip that never appears.

**Why the badge must be shrinkable at all.** `editor.css` records a measurement above
`.el-actions`: at a 1130px viewport (the editor pane's floor) `.el-row__top` offers **196px**
while the action bar alone wants **250px**, and the bar overflowed the card by 41px *"because
every child is a nowrap inline-flex form the bar could not shrink"*. **Read the next line
too:** `.el-actions { flex-wrap: wrap; justify-content: flex-end; }` is the *fix* that
followed that diagnosis. So the 54px horizontal deficit no longer describes the live layout —
the bar wraps instead of escaping, and an earlier draft of this section quoted the diagnosis
as if it were current state.

That changes what the badge's cost actually is. Horizontally it is absorbed; the real risk is
**vertical** — pushing `.el-actions` onto an additional wrapped line, or growing the row. So
the requirement is stated as: adding the badge must not increase `.el-actions`' wrapped line
count or the row's height at 1130px. `text-overflow: ellipsis` still needs `white-space:
nowrap` (ellipsis only fires on content overflowing in the inline direction; without it the
label wraps and the span grows *taller*, which is the failure mode we are trying to avoid),
paired with `min-width: 0` and `flex: 0 1 auto` — the escape a text span has and a button bar
does not.

**Acceptance step:** measure at the 1130px floor (see Testing for the assertions).

`cursor: help` is scoped to `.el-row__flag[title]` on purpose. The existing revealgate flag
(`_element_row.html:29`) has **no `title` attribute**, so an unscoped rule would give it a
help cursor promising a tooltip that never appears — turning a pure fix into a small new
defect on a shipped surface. With the attribute selector, the badge gets the affordance and
the revealgate flag simply gains the typography it always should have had. Since that row is
being restyled either way, **re-check the revealgate row visually** as part of this change.

The badge sits inside `.el-row__top` (`display:flex; align-items:center; gap:var(--space-2)`)
before `.el-actions`, which carries `margin-left:auto` and keeps its right alignment
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

Two deliverables, not one — `config/settings/base.py` **and** `config/settings/test.py`:

```python
# base.py — env-backed so a deployed instance can disable the lookup without a code change
GEOGEBRA_API_LOOKUP = env.bool("LIBLI_GEOGEBRA_API_LOOKUP", default=True)

# test.py — the suite must never reach the network
GEOGEBRA_API_LOOKUP = False
```

A Django setting rather than a module constant specifically because `test.py` must turn it
off suite-wide. It is **`env()`-backed and gets an `.env.example` line**, matching
`ALLOWED_EMBED_DOMAINS` beside it: an instance deployed behind an egress-restricted network
would otherwise have no documented way to stop a per-save outbound call that always times
out. Timeout and the other tunables stay **module constants** in `courses/geogebra.py`,
matching the pattern of `integrations/delivery.py :: TIMEOUT_SECONDS = 10` — they are
implementation detail, not operational policy.

## Data flow

```
author pastes …
├── static embed <iframe … width="880px" height="660px">
│     parse_iframe_dimensions → (880, 660)          [no network]
│     stored 880×660 → wrapper 880/660, src /width/880/height/660
│
├── later title-only edit, URL unchanged, stored pair USABLE
│     parse → (None, None); url_changed = False; stored usable → short-circuit
│     [no network, dims untouched]
│
├── later title-only edit, URL unchanged, stored pair UNUSABLE  (case 3 — the retry)
│     stored not usable → lookup runs again (unless the 60s sentinel is live)
│     [this is how an author retries after a failed lookup]
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
| dimension ≤ 0, non-int, `bool`, float, or > `DIM_MAX` | not usable → `(None, None)` → same |
| id already in the negative cache | `(None, None)` without a request |
| `GEOGEBRA_API_LOOKUP` false | `(None, None)` without a cache read or request |
| GeoGebra host but no material id (`/x`, `/classic/…`) | not a material embed: 16:9 default, no badge, no lookup |
| GeoGebra material id in a non-canonical shape (`/m/<id>`, `/material/show/id/<id>`) stored directly (admin) | `frame_ratio` step 1 → `None` → 16:9 default, no badge, and no `/width/…` appended: the frame claims no ratio the src cannot deliver |
| stored URL already carrying `/width/W/height/H` (admin) | `frame_ratio` step 0 → `"W / H"` read from the URL itself, matching the applet the src sizes |
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
  **call counts** (including zero). That target only exists if `element_forms` uses the
  **from-import** form — `from courses.geogebra import fetch_geogebra_dimensions`, matching
  the module's existing `from courses.embed import parse_iframe_dimensions` style. An
  implementer who writes `from courses import geogebra` and calls
  `geogebra.fetch_geogebra_dimensions(...)` makes every form test fail with `AttributeError`
  at patch time.

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
  **sole** `"G"` entry is used and the non-`G` entry ahead of it is skipped. Worded that way
  deliberately: "the first `G` is used" would restate the first-wins rule the selection rule
  explicitly rejects, and would invite a wrong first draft even though this fixture has only
  one `G`. Flagged as derived: no captured response exhibits this, and the fixture-realism
  rule yields here to covering the branch.
- **derived** fixture where the first `"G"` entry has no usable pair and a later `"G"` does →
  the later one is returned, because it is the **only** `G` yielding a usable pair (pins
  "keep scanning past a `G` that does not")
- **derived** fixture with a top-level `settings` of layout-only keys plus a usable
  `elements[0]` → falls through to the element (pins the usable-dimensions fallthrough)
- `err_invalid_id.json` served as a 400 `HTTPError` → `(None, None)`. Note plainly: because
  `build_opener` keeps `HTTPErrorProcessor`, a 400 raises *before* `resp.read()`, so this test
  asserts only that an `HTTPError` degrades — the fixture's body is documentation of the real
  error shape, not an input the assertion depends on.
- timeout / `URLError` / invalid JSON / missing `settings` → `(None, None)`, no raise
- **the warning actually fires:** the 400 case additionally asserts with `caplog` that a
  `logger.warning` was emitted carrying the material id and the status. Without at least one
  non-oversize failure asserting on the log record, a build that swallows every failure
  silently stays green — and the Risks section names this warning as the primary detection
  channel for a systemic API change.
- `_open` raising an **unlisted** exception type (e.g. `ssl.SSLError`) → `(None, None)`,
  proving the bare `except Exception`
- `width` of `0`, `-5`, `"880"`, `2147483648`, `True`, `880.0` → `(None, None)`
- **multi-applet worksheet:** a derived fixture with two `"G"` entries both yielding usable
  pairs → `(None, None)` plus a "multiple sized G elements" warning, **not** the first pair
- **malformed authority:** `geogebra_material_id("https://[::1")` and
  `is_geogebra_iframe_url("https://[::1")` return `""` / `False` rather than raising
- **User-Agent:** the `Request` handed to `_open` carries `_USER_AGENT`, not `Python-urllib`.
  Assert it as **`req.get_header("User-agent")`** — lowercase `a`. `Request.add_header` stores
  keys `.capitalize()`d, so `Request(url, headers={"User-Agent": …})` yields
  `headers == {"User-agent": …}` and `get_header("User-Agent")` returns **`None`** (verified
  in a REPL). A test written with the intuitive capitalisation fails against a correct
  implementation and reads as an implementation bug.
- **junk elements do not abort the scan:** a derived fixture with a non-dict entry (a string
  and a `null`) *ahead* of a usable `"G"` entry → `(880, 660)`, not `(None, None)`. This is
  the regression guard on defensive per-entry access; it fails if the scan leans on the outer
  `except Exception`.
- **oversize is distinguishable:** a body of exactly `_MAX_BODY_BYTES + 1` bytes →
  `(None, None)` **and** an oversize-specific warning, not a generic parse failure
- **timeout argument:** `_open` receives `timeout=_TIMEOUT_SECONDS`. State precisely what this
  pins — it proves the *caller* passes the constant, and **nothing more**. The
  forgotten-`timeout=`-kwarg bug lives at `opener.open(...)` *inside* `_open`, below the patch
  point, so this test stays green on that broken build. To guard the socket timeout itself,
  add a separate assertion at the `OpenerDirector.open` / `build_opener` level, or keep `_open`
  a one-expression function and assert its body directly.
- **redirects:** a **new** `_NoRedirect` unit test asserting `redirect_request` refuses.
  There is no reuse option — `grep -rn "_NoRedirect\|redirect_request" tests/` returns
  **nothing**, so `integrations/delivery.py` ships this handler entirely untested today and
  an implementer must not assume otherwise. Without this the one behaviour called out as an
  SSRF control is unfalsified, and it cannot be exercised at the `_open` seam, where the
  handler never runs.
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
- **non-GeoGebra URL change keeps its dimensions:** an element with a stored 640×360 from a
  Vimeo `<iframe>` paste, edited to a different `player.vimeo.com` URL with no dimensions in
  the paste → dimensions **unchanged**, lookup not called. This pins the GeoGebra scoping of
  the stale-clear clause; without it the pair is wiped with no way to restore it.
- **GeoGebra → non-GeoGebra URL change keeps the GeoGebra pair:** an element storing 880×660
  edited to a plain `player.vimeo.com` URL → dimensions **unchanged** (880×660). Pins the
  known, accepted gap documented in §2 so a future change to it is deliberate.

**`is_geogebra_iframe_url`** (the render/badge predicate, distinct from
`geogebra_material_id`):
- `https://www.geogebra.org/material/iframe/id/dcjktevj` → `True`
- `https://geogebra.org/material/iframe/id/dcjktevj` → `True` (bare host)
- `https://www.geogebra.org/material/iframe/id/dcjktevj/width/880/height/660` → **`False`**
  (the `"width" in segments` clause — `geogebra_sized_src` refuses this one too)
- `https://[::1` (malformed authority) → `False`, not an exception
- `https://www.geogebra.org/m/dcjktevj` → **`False`** (a material id, but not a shape
  `geogebra_sized_src` rewrites)
- `https://www.geogebra.org/material/show/id/dcjktevj` → **`False`** (same reason)
- `https://www.geogebra.org/x`, `.../classic/abc`, `http://…`, `https://example.com/…` → `False`

**Render:**
- canonical GeoGebra iframe URL, 880×660 → `aspect-ratio: 880 / 660`, src ends
  `/width/880/height/660`
- canonical GeoGebra iframe URL, no dimensions → `aspect-ratio: 800 / 600`
- canonical GeoGebra iframe URL, `(800, None)` / `(None, 600)` / `(0, 0)` →
  `aspect-ratio: 800 / 600`
- **`https://www.geogebra.org/m/<id>` carrying a usable 880×660** → **no** inline
  `aspect-ratio`. This is the ratio/src-agreement guard (step 1 of `frame_ratio`):
  `geogebra_sized_src` leaves this URL bare, so emitting `880 / 660` here would frame
  GeoGebra's 800×600 default in a W/H box and reproduce the original defect. Reachable via
  the admin, which exposes the raw fields. **This test fails against the obvious
  three-branch implementation** — it is the reason step 1 exists.
- `…/material/iframe/id/abc/width/880/height/660` → `aspect-ratio: 880 / 660` **read from the
  URL** (step 0), both **with** stored 880×660 and **without** any stored dimensions. Falling
  to the 16:9 default here would put a 4:3 applet in a 16:9 frame — the original defect,
  mirrored.
- `…/material/iframe/id/abc/width/800/height/400` **with stored 880×660** →
  `aspect-ratio: 800 / 400`. **The disagreeing precondition is the whole point:** this is the
  test that separates step 0 from step 2, and it is the step-0 counterpart to the `/m/<id>`
  test that separates step 1 from step 2. Without a stored pair that *contradicts* the URL
  tail the assertion is unfalsifiable for ordering — the `/width/880/height/660` case cannot
  do it, because the tail and the stored pair carry the same numbers, and a dimensionless
  element only separates step 0 from step 4. **This test fails against a step-2-first
  implementation**, which would emit `880 / 660` around a 2:1 applet while
  `geogebra_sized_src` left the src alone (`"width" in segments`) — violating the "never a
  frame ratio the src does not back up" invariant that step 0 exists to enforce.
- **step-0 rejection cases**, each → **no** inline `aspect-ratio` (fall through to step 1):
  `/width/abc/height/def`, `/width/880` (no height segment), `/width/0/height/0`,
  `/height/660/width/880` (reversed order), and
  `…/id/abc/width/880/height/660/width/999` (repeated segment — the case that separates the
  positional rule from an index search)
- **style-injection guard:** `…/id/abc/width/1;position:fixed;top:0;height:100vh/height/1`
  emits **no** inline `aspect-ratio` — assert the rendered wrapper carries no
  `style="aspect-ratio:` at all. Django's autoescape does not escape `;` or `:`, so this is
  the test that proves step 0 emits validated ints rather than raw path text.
  **Do not assert that `position:fixed` is absent from the rendered HTML — that assertion is
  RED against a correct build.** The template renders `src="{{ el.embed_src }}"`, and
  `geogebra_sized_src` returns this URL unchanged (both because `"width" in segments` and
  because there are no dimensions to append), so the injected text legitimately survives
  inside the `src` attribute, where it is inert. Sanitising `embed_src` is **not** in scope
  and would be a wrong fix. If a positional assertion is wanted, scope it to the `style`
  attribute's contents, never to the whole document.
- **non-GeoGebra URL with `width`/`height` path segments**
  (`https://player.vimeo.com/video/1/width/4/height/3`) → **no** inline `aspect-ratio`;
  step 0 is scoped to GeoGebra and must not touch other providers
- **malformed authority:** `frame_ratio` and `size_unknown` on a stored `https://[::1`
  return `None`/`False` without raising — step 0 runs first, so an unguarded `urlsplit` here
  would 500 the unit page before any fallback
- the two stricter-than-`geogebra_sized_src` divergences, each with **both** dimension
  preconditions pinned (see §3 — the outcome depends entirely on the stored columns):
  - `…/material/iframe/id` (no id) and `…/material/iframe/id/ab%20cd`, **no stored
    dimensions** → no inline `aspect-ratio`, no exception
  - the same two URLs **with** stored 880×660 → `aspect-ratio: 880 / 660` (step 2), and the
    src is sized to match. Asserting "no inline aspect-ratio" here would be RED against a
    correct build.
- **non-GeoGebra with a usable pair** (`https://player.vimeo.com/video/123`, 640×360) →
  `aspect-ratio: 640 / 360`. Guards that step 1 does not swallow other providers.
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
coverage re-pointed at a **non-GeoGebra** URL. That needs **two** new constants, not one,
because the render and form tests have different validation exposure:

| constant | value | used by | why |
|---|---|---|---|
| `OTHER_RENDER_URL` | `https://example.com/embed/abc` | render tests only | render tests build an unsaved `IframeElement` and call `render_to_string`, bypassing validation entirely |
| `OTHER_FORM_URL` | `https://player.vimeo.com/video/123` | form tests | **`example.com` is not in `ALLOWED_EMBED_DOMAINS`** (`config/settings/base.py:187` lists youtube/youtu.be/player.vimeo.com/geogebra.org/edpuzzle.com/app.lumi.education), so a form test using it fails with a `ValidationError` on `url` — in the same module, under a name that looks interchangeable |

An implementer not told this will read the render-test failures as a defect in their own
code, and will lose time on the form-test `ValidationError`.

**Editor row:**
- canonical GeoGebra iframe URL without dimensions → badge present, with the tooltip text
- canonical GeoGebra iframe URL with dimensions → badge absent
- canonical GeoGebra iframe URL with a partial/zero pair → badge present (mirrors
  `frame_ratio` — both read `usable_dimensions`, so they cannot disagree)
- `https://www.geogebra.org/m/<id>` → badge absent (mirrors the render case above)
- GeoGebra host without a material id → badge absent
- non-GeoGebra without dimensions → badge absent

**Editor row layout — a real browser measurement, not an inspection.** At a **1130px**
viewport (the editor pane's floor, the width the existing `.el-actions` overflow was measured
at), a row carrying the badge must not overflow its card. Mechanism: an **e2e test** that sets the viewport to 1130px, loads the editor for a unit
containing a dimensionless GeoGebra element, and measures with `bounding_box()`.

**Assert on the elements that can actually overflow — not on `.el-row__top`.** Asserting
that `.el-row__top`'s right edge lies inside the card is an assertion that **cannot fail**:
`.el-row__head` is `display:grid; grid-template-columns:auto 1fr` and `.el-row__body` carries
`min-width:0`, so `.el-row__top`'s border box is sized *by the grid column* and is inside the
card by construction, on a broken build too. The defect the CSS comment records was a **child
escaping** its container — "🗑 rendered 41px OUTSIDE the card's rounded border".

Because `.el-actions` now wraps rather than escaping (§4), the badge's cost is mostly
vertical, so the load-bearing assertions are the height ones:

1. **(load-bearing)** the row's height, and `.el-actions`' wrapped line count via
   `getClientRects().length`, are **unchanged** by the badge's presence — compare the same
   row rendered with and without it at 1130px
2. **(load-bearing)** `.el-row__top`'s `scrollWidth <= clientWidth`
3. **(load-bearing)** `.el-actions`' right edge (or its last button's) lies within the card's
   right edge — the direct regression guard on the original 41px escape
4. **(secondary, and weak by construction)** the badge ellipsised rather than pushed: its
   rendered `clientWidth < scrollWidth` when the row is narrow. Note that asserting the
   badge's *position* is inside the card would be near-unfalsifiable — it is rendered before
   `.el-actions`, so negative free space is pushed onto the trailing item and the badge's own
   box stays inside even on a build where it refuses to shrink.

Reading the CSS and concluding "it has `min-width: 0`, so it shrinks" is **not** acceptance
evidence.

The fixture element is built **directly via the ORM** — `IframeElement.objects.create(url=<a
canonical GeoGebra URL>, title=…)` with no width/height, plus its `Element` join row — so the
test depends on neither `IframeElementForm` nor the value of `GEOGEBRA_API_LOOKUP`, and can
never issue a live GET from an e2e run.

**The A/B baseline must differ only in the badge.** The comparison row is a **second**
`IframeElement` in the same unit with an **identical `title`** and *usable* width/height (so
`size_unknown` is False and no badge renders). Same element type keeps `.el-tag` identical. Identical titles are
belt-and-braces rather than the mechanism: `.el-row__label` (editor.css:531) is
`white-space: nowrap` + `overflow: hidden` + ellipsis and sits as a sibling *below*
`.el-row__top`, so a title can never wrap and never contributes to row height. **The height
risk actually being controlled is `.el-actions` gaining a wrapped line.** Matching the titles
anyway keeps the two rows byte-identical apart from the badge, so a measured difference has
exactly one possible cause. Row order is safe — `_element_row_controls.html`
is position-independent.

This e2e touches no external network (it renders our editor page, not the applet), which is
why it is carved out of the no-e2e non-goal. Capture light and dark screenshots for the PR
body.

**Import:** an existing round-trip test is extended to assert the import path performs no
GeoGebra lookup, guarding the `extract_embed_url` boundary decision. **This test needs a
third seam — not the form seam — or it cannot fail.** The import path is
`courses/transfer/payloads.py :: _val_iframe` → `_canonical_embed` → `extract_embed_url` (in
`courses/embed.py`); it never touches `courses.element_forms`, so `assert_not_called()` on
that module's re-export is true by construction on a correct build *and* on a build that
added a lookup inside `extract_embed_url` — the exact regression the boundary decision
exists to prevent. Patching `courses.geogebra.fetch_geogebra_dimensions` does not fix it
either: the mandated from-import style means a hypothetical `embed.py` consumer would hold
its own binding. And patching `_open` under the suite default is vacuous, because
`GEOGEBRA_API_LOOKUP=False` short-circuits before the seam.

So: wrap this one test in `override_settings(GEOGEBRA_API_LOOKUP=True)` and patch
**`courses.geogebra._open`**, asserting it is never called. That target goes RED for a lookup
introduced anywhere in the import path, whatever the import style.

Every test is falsified to RED before it counts. The one deliberate exception is the
`_API_PREFIX` defensive check, unreachable by construction and therefore specified as
untested rather than given a test that cannot fail.

## Risks

- **GeoGebra changes the 800×600 default or the shell.** The 4:3 fallback would drift. Low
  impact: it governs only the degraded path, and the primary path stores real dimensions.
- **A save depends on a network call made while holding the unit's row lock** (§2). It fires
  on a fresh element, on a URL change, **and on every save of an element whose stored pair is
  unusable** (the retry path) — so a dimensionless element re-attempts the lookup on each
  save once the 60s sentinel expires. Mitigated by the socket timeout, the capped read, and
  the negative cache; explicitly accepted, with the restructuring alternative recorded.
- **The worst-case save latency is not hard-bounded** (see Error handling). A slow-drip
  endpoint or a stalled DNS resolver can exceed the nominal 3s.
- **A retry within 60s of a failure is suppressed** by the negative cache, and outside tests
  that cache is per worker process.
- **API shape or endpoint change.** Handled by the never-raises contract: an unrecognised
  shape degrades to the fallback. Detection relies on the `logger.warning` and the pre-PR
  live check, since no automated test touches the network.
