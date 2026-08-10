# GeoGebra Share-Link Sizing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a GeoGebra material added by share link render identically to the same material added by GeoGebra's static embed code — no white space and no crop — by looking the authored size up from the GeoGebra API at save time, with a measured-correct 4:3 fallback plus an editor badge when that lookup is unavailable.

**Architecture:** `courses/geogebra.py` (the only module in `courses/` that imports nothing from its own package, and therefore the sole cycle-free home) gains a shared dimension predicate, three URL predicates, and one capped non-raising network lookup behind a kill switch. `IframeElementForm.clean_url` calls the lookup only when dimensions are unknown in both the paste and the instance. Two new `IframeElement` properties drive a provider-aware wrapper ratio and a persistent editor badge. Nothing new is persisted, so there is **no migration and no `FORMAT_VERSION` bump**.

**Tech Stack:** Django 5.2, Python 3.13, stdlib `urllib.request` (no new dependency), pytest + pytest-django, Playwright for the one layout e2e, `uv run` for all tooling.

## Global Constraints

- **Run everything through `uv run`** — `ruff`, `pytest` and `python` are not on PATH.
- **Start the test-DB container before any pytest run:** `docker compose -f docker-compose.test.yml up -d`. If it is down the suite looks hung for ~4m21s.
- **Scope test runs narrowly.** Run the named test file/node, never the whole suite, until the final branch gate.
- **Every test must be falsified to RED before it counts.** Run the new test and see it fail for the *stated* reason before writing the implementation. A passing test proves nothing until its failure mode has been demonstrated. The one declared exception is the `_API_PREFIX` defensive check, which is unreachable by construction and deliberately has no test.
- **`DIM_MAX = 2147483647`** — the `PositiveIntegerField` ceiling. Single definition, in `courses/geogebra.py`.
- **`GEOGEBRA_DEFAULT_SIZE = (800, 600)`** — GeoGebra's own iframe-shell fallback. `frame_ratio` emits the literal `"800 / 600"` (identical to `4 / 3`); the plan and tests use `800 / 600` everywhere.
- **`GEOGEBRA_API_LOOKUP` is `False` for the whole suite** (`pyproject.toml` pins `DJANGO_SETTINGS_MODULE = "config.settings.test"`). Every test that exercises the lookup — **including the invalid-input cases, which would otherwise pass vacuously** — must wrap in `override_settings(GEOGEBRA_API_LOOKUP=True)`.
- **Public vs private naming:** names that **cross a module boundary** are public (`usable_dimensions`, `DIM_MAX`, `is_geogebra_iframe_url`, `geogebra_url_size`, `geogebra_material_id`, `fetch_geogebra_dimensions`, `GEOGEBRA_DEFAULT_SIZE`); names that **do not cross a module boundary keep the underscore** (`_open`, `_API_PREFIX`, `_TIMEOUT_SECONDS`, `_MAX_BODY_BYTES`, `_NEGATIVE_TTL_SECONDS`, `_USER_AGENT`, `_ID_RE`, `_NoRedirect`). `_open` is the only underscore name a test may **patch** — it is the transport seam, and that is deliberate. Tests additionally **read** `_MAX_BODY_BYTES`, `_TIMEOUT_SECONDS`, `_USER_AGENT` and `_NoRedirect` through in-function imports (Task 5); reading them is fine and does **not** justify promoting any of the four to a public name.
- **Where new imports go — production files too, not just tests.** `I001` gates every file, so the two production modules need named insertion points in their existing single-line isort-ordered `from courses.*` blocks: in `courses/models.py` the five `courses.geogebra` lines go **between `courses.fields` (line 22) and `courses.marking` (line 23)**; in `courses/element_forms.py` the three go **between `courses.embed` (lines 15-16) and `courses.marking` (line 17)**. Appending them below the block instead fires `I001` on the final `ruff check .` gate.
- **Where new test imports go.** Each task's test block shows the *tests*; put every new import at the **top of the module**, in the existing single-line isort-ordered import block. Do **not** paste import lines mid-file: ruff selects `E` and `I`, only `S105/S106/S107` are ignored under `tests/**`, so mid-file imports fire `E402` and `I001` and the final `ruff check .` gate goes red for reasons unrelated to the feature. (`config/settings/test.py` carries an explicit `# noqa: E402` for exactly this rule.)
- **Keep every line of pasted code at or under 88 characters.** `ruff`'s `E` selection includes **E501** and the repo sets no `line-length` override, so the default 88 applies (verified: an 89-char line reports `E501 Line too long`). This matters more than it looks — the final gate runs `ruff check .` *before* `ruff format .`, and roughly half of this plan's long lines are **comments and docstrings, which `ruff format` cannot rewrap at all**. Every code block below has been wrapped to fit; if you re-flow one while editing, re-check its width.
- **`urllib.request.Request` needs `# noqa: S310`** with a one-line justification, mirroring `integrations/delivery.py:50,122`.
- **The `# noqa: BLE001` markers on the bare `except Exception` handlers are anticipatory, not active.** `pyproject.toml` selects `["E", "F", "I", "UP", "B", "S"]`, so `BLE` is not enabled and the suppression currently does nothing (`RUF100` is not selected either, so an inert `noqa` is not itself flagged). Keep them — they document the intent and pre-empt a future `BLE` selection — but do not read them as evidence a lint rule is being silenced today, and do not "fix" a `BLE` failure that cannot occur.
- **`element_forms.py` must use the from-import style** (`from courses.geogebra import fetch_geogebra_dimensions`) — the form tests patch `courses.element_forms.fetch_geogebra_dimensions`, which only exists under that style.
- **Run `uv run ruff format .` LAST**, after every other edit — CI gates on `ruff format --check`.

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `courses/geogebra.py` | The single GeoGebra parser: dimension predicate, three URL predicates, one network lookup | 1–5 |
| `courses/embed.py` | `_INT_MAX` → `DIM_MAX` fold (3 sites) | 1 |
| `config/settings/base.py`, `config/settings/test.py`, `.env.example` | The `GEOGEBRA_API_LOOKUP` kill switch | 5 |
| `courses/element_forms.py` | Capture wiring in `clean_url` | 6 |
| `courses/models.py` | `frame_ratio` + `size_unknown` on `IframeElement` | 7 |
| `templates/courses/elements/iframeelement.html` | Wrapper ratio | 7 |
| `templates/courses/manage/editor/_element_row.html` | The editor badge | 8 |
| `courses/static/courses/css/editor.css` | `.el-row__flag` rules | 8 |
| `locale/{pl,en}/LC_MESSAGES/django.po` + `.mo` | Badge strings | 8 |
| `tests/fixtures/geogebra/*.json` | Real + derived API payloads | 5 |
| `tests/test_geogebra.py` | Predicate + lookup tests | 1–5 |
| `tests/test_iframe_dimensions.py` | Form + render tests, incl. the four existing tests that must change | 6, 7 |
| `tests/test_transfer_import.py` (existing) | Import-path no-lookup guard | 10 |
| `tests/test_e2e_editor_row_layout.py` | The 1130px layout measurement | 9 |

---

### Task 0: Re-run the census before writing any code

**Files:** none — this is a measurement gate.

**Interfaces:** produces the numbers three of the spec's decisions rest on.

The spec's "no backfill", "no published mat-pp unit changes appearance", and blast-radius claims all rest on a census whose origin is *not* fully established: `courses/lal_loader/builders.py:350` constructs iframes with **no** dimensions, yet mat-pp measures 131/131 *with* them. The spec therefore requires the census to be reproducible rather than believed.

- [ ] **Step 1: Run the literal census query**

**Do not start the test-DB container for this** — the census must run against the **dev** database `libli`, the one holding mat-pp. A count taken against the test DB (or any mat-pp-free database) prints four zeroes, which reads as "the numbers differ → STOP" for entirely the wrong reason. `manage.py` resolves `DJANGO_SETTINGS_MODULE` from the environment with `default="config.settings.local"`, so a developer `.env` can silently redirect it — which is why the snippet prints what it connected to **before** the counts, and why you must check that line first.

```bash
uv run python manage.py shell -c "
from django.conf import settings
print('SETTINGS:', settings.SETTINGS_MODULE)
print('DATABASE:', settings.DATABASES['default']['NAME'])   # must be 'libli'
from urllib.parse import urlsplit
from collections import Counter
from courses.models import IframeElement
c = Counter()
for o in IframeElement.objects.all():
    try:
        p = urlsplit(o.url); segs = p.path.split('/')[1:]
        host = (p.hostname or '').lower()
        shape = ('non-geogebra' if host not in ('geogebra.org','www.geogebra.org')
                 else 'canonical' if segs[:3]==['material','iframe','id'] and 'width' not in segs
                 else 'canonical+width' if segs[:3]==['material','iframe','id']
                 else 'gg-host-other')
    except (ValueError, TypeError, IndexError):
        # urlsplit('https://[::1').hostname RAISES. This is the same hazard the plan
        # guards against in geogebra_material_id -- unguarded here, ONE malformed row
        # would abort the gate that blocks every other task.
        shape = 'unparseable'
    for e in o.elements.all():
        c[(e.unit.course.slug, shape, bool(o.width and o.height))] += 1
for k in sorted(c): print(k, c[k])
"
```

- [ ] **Step 2: Evaluate the gate predicate (not an exact-match comparison)**

Reference counts, as measured 2026-08-10 against the `libli` dev DB:

```
('demo-course', 'canonical', False) 2
('demo-course', 'canonical', True) 1
('mat-pp', 'canonical', True) 131
('mat-pp', 'non-geogebra', False) 5
```

**Gate on the predicate, not on the four numbers.** Only one claim is load-bearing:

> **`('mat-pp', 'canonical', False)` is absent, i.e. its count is 0** — no mat-pp canonical GeoGebra row is dimensionless.

**If that predicate is violated → STOP and report before continuing.** The consequences are concrete, not cosmetic: every dimensionless mat-pp row flips 16:9 → 4:3, grows a badge, and fires a live GET inside the unit row lock on its next save. That changes whether a backfill is warranted, which is a design decision, not an implementation one.

**If the predicate holds but the other counts have drifted, that is expected — proceed.** The reference numbers are one developer's dev DB on one date; local authoring since, a colleague's machine, or a fresh checkout will all differ without touching the design conclusion. Record the numbers you actually saw in the PR body; do not halt on them.

**If the dev DB is unavailable or holds no mat-pp rows, that is a third outcome, not a violation.** `manage.py` defaults `DATABASE_URL` to `postgres://libli:libli@localhost:5432/libli`, so with the Postgres server down this step dies with a connection error rather than printing counts, and a fresh checkout prints nothing at all. In either case the predicate is *unevaluated*, not *false*: record that in the PR body and proceed — the design decision it guards (no backfill) is only actionable on a database that actually holds mat-pp.

Note the counting predicate is a deliberately *looser superset* of `is_geogebra_iframe_url` — it omits the https-scheme and `_ID_RE` checks, so it can over-count "canonical". It over-counted by zero on the measured data. A fifth bucket, `'unparseable'`, appears only if some stored URL has a malformed authority; any rows landing there should be reported alongside the counts, since they are the shape every `never raises` guard in this plan exists for.

---

### Task 1: `usable_dimensions` + the `DIM_MAX` fold

**Files:**
- Modify: `courses/geogebra.py` (add constant + predicate near the top, after `_CANONICAL`)
- Modify: `courses/embed.py:27,31,42` (fold `_INT_MAX` → `DIM_MAX`)
- Test: `tests/test_geogebra.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `DIM_MAX: int`, `GEOGEBRA_DEFAULT_SIZE: tuple[int, int]`, and `usable_dimensions(width, height) -> bool`. **Every** later task uses `usable_dimensions` as the single definition of "known size"; the ceiling living *inside* it is what stops an over-range API value reaching the `PositiveIntegerField` and 500-ing the save (`width`/`height` are not in `IframeElementForm.Meta.fields`, so `_post_clean` excludes them from `full_clean` and the DB validator never fires). `GEOGEBRA_DEFAULT_SIZE` is consumed only by `frame_ratio` step 3 (Task 7) but is defined here so every constant lives together.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_geogebra.py`. **`import pytest` is already line 1 of that file** — the only *new* imports here are the two `courses.geogebra` ones, which join the existing isort block at the top (see Global Constraints); pasting the `import pytest` line again would duplicate it.

```python
from courses.geogebra import DIM_MAX
from courses.geogebra import usable_dimensions


@pytest.mark.parametrize("w,h", [(880, 660), (1, 1), (DIM_MAX, DIM_MAX)])
def test_usable_dimensions_accepts_positive_in_range_ints(w, h):
    assert usable_dimensions(w, h) is True


@pytest.mark.parametrize(
    "w,h",
    [
        (0, 660),           # zero
        (-5, 660),          # negative
        (880, 0),
        (None, 660),        # partial pair
        (880, None),
        (None, None),
        ("880", 660),       # string, not int
        (880.0, 660),       # integral float still rejected
        (True, 660),        # bool is an int subclass in Python — must NOT pass
        (880, True),
        (DIM_MAX + 1, 660), # over the PositiveIntegerField ceiling
        (880, DIM_MAX + 1),
    ],
)
def test_usable_dimensions_rejects_everything_else(w, h):
    assert usable_dimensions(w, h) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_geogebra.py -k usable_dimensions -v`
Expected: FAIL — `ImportError: cannot import name 'DIM_MAX' from 'courses.geogebra'`.

- [ ] **Step 3: Write minimal implementation**

In `courses/geogebra.py`, after the `_CANONICAL` constant:

```python
DIM_MAX = 2147483647  # PositiveIntegerField ceiling; public — imported across modules
GEOGEBRA_DEFAULT_SIZE = (800, 600)  # GeoGebra's own iframe-shell fallback -> 4:3
# ^ The shell hardcodes `parameters.width = (parameters.width || 800) * 1`, so a
#   dimensionless embed ALWAYS renders 800x600 whatever the material's authored size.
#   Measured: a 4:3 wrapper leaves a 0.0px gap; today's 16:9 leaves 161.3px at the
#   648px content width. Consumed by frame_ratio step 3 (Task 7).


def usable_dimensions(width, height):
    """True iff both are real, positive, in-range ints (1..DIM_MAX).

    The single definition of "known size", shared by the API parser, clean_url's
    guards, frame_ratio and size_unknown, so the badge and the ratio can never
    disagree. The ceiling lives HERE rather than only in the API parser: width and
    height are absent from IframeElementForm.Meta.fields, so ModelForm._post_clean
    excludes them from full_clean and the PositiveIntegerField range validator never
    runs — an over-range value would reach the DB and 500 on save.

    bool is excluded explicitly: isinstance(True, int) is True in Python, so a
    payload of {"width": true} would otherwise render `aspect-ratio: True / 660`.
    Non-int types are rejected outright, including an integral float like 880.0.
    """
    for value in (width, height):
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        if value < 1 or value > DIM_MAX:
            return False
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_geogebra.py -k usable_dimensions -v`
Expected: PASS (15 cases).

- [ ] **Step 5: Fold `_INT_MAX` into `DIM_MAX`**

In `courses/embed.py`, three sites:

1. Delete the definition `_INT_MAX = 2147483647  # PositiveIntegerField ceiling` (line 27) and add `DIM_MAX` to the existing geogebra import at the top:

```python
from courses.geogebra import DIM_MAX
from courses.geogebra import canonicalize_geogebra_url
```

2. In `_dimension`'s docstring, change `A positive int (1.._INT_MAX) from an iframe width/height attribute, else None.` to `A positive int (1..DIM_MAX) from an iframe width/height attribute, else None.`
3. Change the comparison `if n <= 0 or n > _INT_MAX:` to `if n <= 0 or n > DIM_MAX:`.

- [ ] **Step 6: Verify the fold is complete and nothing regressed**

Use the **`Grep` tool** for `_INT_MAX`, scoped to `courses/`, `config/` and `tests/` (not `uv run grep` — `grep` is not a project entry point, so `uv run` just resolves whatever is on PATH, which under PowerShell is nothing).
Expected: **zero hits in those three directories**.

**Do not run this repo-wide and do not expect zero hits there.** A *correct* fold still leaves `_INT_MAX` in:

- `docs/superpowers/plans/2026-07-06-iframe-embed-aspect-ratio.md` (3 hits) — the historical plan that introduced the constant;
- `docs/superpowers/specs/2026-08-10-geogebra-share-link-sizing-design.md` (5 hits) — including this very fold's own acceptance sentence;
- this plan file (6 hits).

Those are prose records of a past state. **Do not edit historical design docs to make a grep go quiet** — an implementer chasing a repo-wide zero will either rewrite documents that should not change or conclude a correct fold is incomplete. (The spec's own wording, `grep -rn "_INT_MAX"` must return zero hits", is the un-scoped version of this criterion and is superseded here.)

Run: `uv run pytest tests/test_embed.py tests/test_geogebra.py -v`
Expected: PASS — the existing `parse_iframe_dimensions` cap tests still hold against `DIM_MAX`.

- [ ] **Step 7: Commit**

```bash
git add courses/geogebra.py courses/embed.py tests/test_geogebra.py
git commit -m "feat(geogebra): add usable_dimensions predicate, fold _INT_MAX into DIM_MAX"
```

---

### Task 2: `geogebra_material_id` — the lookup gate

**Files:**
- Modify: `courses/geogebra.py` (new public function; refactor `canonicalize_geogebra_url` to use it)
- Test: `tests/test_geogebra.py`

**Interfaces:**
- Consumes: `_material_id`, `_ID_RE`, `_GEOGEBRA_HOSTS`, `_CANONICAL` (all existing, private).
- Produces: `geogebra_material_id(url) -> str` — the material id for a recognized https GeoGebra URL, `""` otherwise. **Never raises.** Used by `clean_url` (Task 6) as the lookup gate and by `frame_ratio` step 1 (Task 7).

**Critical detail:** today's `_material_id` does **not** apply `_ID_RE` — `canonicalize_geogebra_url` applies it afterwards. A verbatim promotion would make `geogebra_material_id("https://www.geogebra.org/m/bad id")` return `"bad id"`, which is truthy, so `clean_url` would proceed and build an API URL containing a raw space. The regex must move *into* the promoted function.

**Second critical detail:** the `try/except (ValueError, TypeError, IndexError)` currently guarding `urlsplit`/`.hostname` inside `canonicalize_geogebra_url` moves into `geogebra_material_id`, and `canonicalize_geogebra_url` inherits it. A malformed authority such as `https://[::1` really does raise, and this function is called during page render.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_geogebra.py`:

```python
from courses.geogebra import geogebra_material_id


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.geogebra.org/m/dcjktevj", "dcjktevj"),
        ("https://geogebra.org/m/dcjktevj", "dcjktevj"),            # bare host
        ("https://www.geogebra.org/material/show/id/dcjktevj", "dcjktevj"),
        ("https://www.geogebra.org/material/iframe/id/dcjktevj", "dcjktevj"),
        # _ID_RE charset gate
        ("https://www.geogebra.org/m/bad id", ""),
        # app link, not a material
        ("https://www.geogebra.org/classic/dcjktevj", ""),
        # the LAL-stored shape
        ("https://www.geogebra.org/x", ""),
        ("http://www.geogebra.org/m/dcjktevj", ""),     # non-https
        ("https://beta.geogebra.org/m/dcjktevj", ""),   # subdomain
        ("https://example.com/m/dcjktevj", ""),         # other host
    ],
)
def test_geogebra_material_id(url, expected):
    assert geogebra_material_id(url) == expected


def test_geogebra_material_id_never_raises_on_malformed_authority():
    # urlsplit("https://[::1").hostname raises ValueError; this runs on the render
    # path, so it must degrade rather than 500 the page.
    assert geogebra_material_id("https://[::1") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_geogebra.py -k geogebra_material_id -v`
Expected: FAIL — `ImportError: cannot import name 'geogebra_material_id'`.

- [ ] **Step 3: Write minimal implementation**

Add to `courses/geogebra.py`, and rewrite `canonicalize_geogebra_url` to delegate:

```python
def geogebra_material_id(url):
    """Return the material id for a recognized https GeoGebra URL, else "".

    Applies _ID_RE, which _material_id does NOT — canonicalize_geogebra_url used to
    apply it afterwards. Without the regex here, ".../m/bad id" would return a truthy
    "bad id" and clean_url would build an API URL containing a raw space.

    Never raises: urlsplit/.hostname can raise ValueError on a malformed authority,
    and this runs during page render (frame_ratio) as well as in clean_url.
    """
    try:
        parts = urlsplit(url)
        if parts.scheme != "https":
            return ""
        if (parts.hostname or "").lower() not in _GEOGEBRA_HOSTS:
            return ""
        candidate = _material_id(parts.path.split("/")[1:])
        return candidate if _ID_RE.match(candidate) else ""
    except (ValueError, TypeError, IndexError):
        return ""


def canonicalize_geogebra_url(url):
    """Rewrite a recognized https GeoGebra material URL to the worksheet embed URL.

    Anything not recognized — non-https, non-GeoGebra host, a *.geogebra.org
    subdomain, an app link, a missing/malformed id, or any parse failure — is
    returned unchanged. Recognition lives entirely in geogebra_material_id.
    """
    material_id = geogebra_material_id(url)
    return _CANONICAL.format(material_id) if material_id else url
```

- [ ] **Step 4: Run test to verify it passes, and that the refactor preserved behaviour**

Run: `uv run pytest tests/test_geogebra.py -v`
Expected: PASS — **including every pre-existing `canonicalize_geogebra_url` test, unchanged.** Those are the regression guard on the promotion; if any needed editing, the refactor changed behaviour and is wrong.

- [ ] **Step 5: Commit**

```bash
git add courses/geogebra.py tests/test_geogebra.py
git commit -m "feat(geogebra): promote material-id extraction to a public, _ID_RE-gated helper"
```

---

### Task 3: `is_geogebra_iframe_url` — the render/badge predicate

**Files:**
- Modify: `courses/geogebra.py`
- Test: `tests/test_geogebra.py`

**Interfaces:**
- Consumes: `_GEOGEBRA_HOSTS`, `_ID_RE`.
- Produces: `is_geogebra_iframe_url(url) -> bool`. **Never raises.** Gates `frame_ratio` step 3 and `size_unknown` (Task 7).

**Why this is a second predicate and not `bool(geogebra_material_id(url))`:** it must agree with what `geogebra_sized_src` actually rewrites. That function bails on `segments[:3] != ["material","iframe","id"] **or "width" in segments**`. `geogebra_material_id` accepts `/m/<id>` and `/material/show/id/<id>`, which `geogebra_sized_src` will *not* size — so using it here would emit `aspect-ratio: W / H` while the src stayed bare, framing GeoGebra's 800×600 default in a W/H box and reproducing the original defect with no badge to explain it. Reachable via the Django admin, which exposes `url`, `width` and `height` as raw model fields.

It is deliberately **stricter** than `geogebra_sized_src` (which never validates `segments[3]`). The two documented divergences are tested below.

- [ ] **Step 1: Write the failing test**

```python
from courses.geogebra import is_geogebra_iframe_url


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.geogebra.org/material/iframe/id/dcjktevj", True),
        ("https://geogebra.org/material/iframe/id/dcjktevj", True),      # bare host
        # the "width" in segments clause — geogebra_sized_src refuses this one too
        (
            "https://www.geogebra.org/material/iframe/id/dcjktevj"
            "/width/880/height/660",
            False,
        ),
        # not a shape sized_src rewrites
        ("https://www.geogebra.org/m/dcjktevj", False),
        ("https://www.geogebra.org/material/show/id/dcjktevj", False),
        ("https://www.geogebra.org/x", False),
        ("https://www.geogebra.org/classic/abc", False),
        # non-https
        ("http://www.geogebra.org/material/iframe/id/dcjktevj", False),
        ("https://example.com/material/iframe/id/dcjktevj", False),
        # deliberately STRICTER than geogebra_sized_src, which never indexes segments[3]
        ("https://www.geogebra.org/material/iframe/id", False),  # no id at all
        # id fails _ID_RE
        ("https://www.geogebra.org/material/iframe/id/ab%20cd", False),
    ],
)
def test_is_geogebra_iframe_url(url, expected):
    assert is_geogebra_iframe_url(url) is expected


def test_is_geogebra_iframe_url_never_raises_on_malformed_authority():
    assert is_geogebra_iframe_url("https://[::1") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_geogebra.py -k is_geogebra_iframe_url -v`
Expected: FAIL — `ImportError: cannot import name 'is_geogebra_iframe_url'`.

- [ ] **Step 3: Write minimal implementation**

```python
def is_geogebra_iframe_url(url):
    """True only for the canonical shape geogebra_sized_src will rewrite.

    Mirrors that function's guard in FULL — including the easily-missed
    `"width" in segments` disjunct — so frame_ratio can never claim a ratio the
    rendered src does not back up. Deliberately STRICTER in one respect:
    geogebra_sized_src never validates segments[3], so ".../id" (no id) and an id
    failing _ID_RE are True there and False here. Both are degenerate shapes that
    clean_url cannot produce; see the design doc's divergence table.

    Never raises.
    """
    try:
        parts = urlsplit(url)
        if parts.scheme != "https":
            return False
        if (parts.hostname or "").lower() not in _GEOGEBRA_HOSTS:
            return False
        segments = parts.path.split("/")[1:]
        if segments[:3] != ["material", "iframe", "id"] or "width" in segments:
            return False
        return len(segments) > 3 and bool(_ID_RE.match(segments[3]))
    except (ValueError, TypeError, IndexError):
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_geogebra.py -k is_geogebra_iframe_url -v`
Expected: PASS (12 cases).

- [ ] **Step 5: Commit**

```bash
git add courses/geogebra.py tests/test_geogebra.py
git commit -m "feat(geogebra): add is_geogebra_iframe_url, mirroring geogebra_sized_src's guard"
```

---

### Task 4: `geogebra_url_size` — `frame_ratio` step 0

**Files:**
- Modify: `courses/geogebra.py`
- Test: `tests/test_geogebra.py`

**Interfaces:**
- Consumes: `usable_dimensions` (Task 1), `_GEOGEBRA_HOSTS`, `_ID_RE`.
- Produces: `geogebra_url_size(url) -> tuple[int, int] | tuple[None, None]`. **Never raises.** Drives `frame_ratio` step 0 (Task 7).

**Three load-bearing properties, all tested below:**

1. **GeoGebra-scoped.** A bare "the path contains `width`" rule would fire on a stored `https://player.vimeo.com/video/1/width/4/height/3` and give a non-GeoGebra embed an inline ratio it does not have today, contradicting the "no change to non-GeoGebra embeds" non-goal.
2. **Returns validated ints, never raw path text.** `frame_ratio` is interpolated into `style="aspect-ratio: {{ el.frame_ratio }}"`, and Django's autoescape covers `< > & " '` but **not `;` or `:`**, both legal in a URL path segment. Raw text would let an admin-stored `…/width/1;position:fixed;top:0;height:100vh/height/1` inject arbitrary declarations. **This is a security boundary.**
3. **Positional, not index-searched — but the tail need not end the path.** The pair must sit at fixed offsets immediately after the id (`segments[4] == "width"`, `segments[6] == "height"`, `len(segments) >= 8`); anything *after* offset 7 is ignored. `segments.index("width")` would instead hunt the whole path and accept a `width` at any depth.

   **The `>=` is load-bearing, not laxity.** GeoGebra's own published embed src carries a longer tail — the repo's existing `tests/test_geogebra.py:15` pins the real captured shape:

   ```
   https://www.geogebra.org/material/iframe/id/egZJdjsC/width/1600/height/763/border/888888/sfsb/true
   ```

   That is **12** segments. Under a `len == 8` rule it would be rejected at step 0; `is_geogebra_iframe_url` also returns False for it (`"width" in segments`), so `frame_ratio` step 1 would return `None` and the wrapper would keep the CSS 16:9 default **while the src imposes 1600/763** — violating the "never ignore a ratio the src *does* impose" half of `frame_ratio`'s stated invariant, and reproducing the exact ~161px-gap defect this feature exists to fix. `clean_url` canonicalizes such a URL away, so this shape reaches `frame_ratio` only via the admin or legacy rows — but the census's `canonical+width` bucket exists precisely to count it, and "unreachable today" is not a reason to encode the wrong rule.

   Consequence to accept deliberately: `…/width/880/height/660/width/999` now yields `(880, 660)` — the **first positional pair wins** and the trailing repeat is ignored, exactly as the `border`/`sfsb` cruft is. That is the same rule, not an exception to it, and it is pinned by a test below.

- [ ] **Step 1: Write the failing test**

```python
from courses.geogebra import geogebra_url_size

_BASE = "https://www.geogebra.org/material/iframe/id/abc"


@pytest.mark.parametrize(
    "url,expected",
    [
        (f"{_BASE}/width/880/height/660", (880, 660)),
        (f"{_BASE}/width/800/height/400", (800, 400)),     # non-4:3: read, not assumed
        (f"{_BASE}/width/abc/height/def", (None, None)),   # non-numeric
        (f"{_BASE}/width/880", (None, None)),              # height segment missing
        (f"{_BASE}/width/0/height/0", (None, None)),       # fails usable_dimensions
        (f"{_BASE}/height/660/width/880", (None, None)),   # reversed order
        # Trailing segments after offset 7 are IGNORED, so the first positional pair
        # wins. Same rule that admits GeoGebra's real border/sfsb cruft below.
        (f"{_BASE}/width/880/height/660/width/999", (880, 660)),
        (_BASE, (None, None)),                             # no tail at all
        # scoped to GeoGebra: another provider with width/height path segments
        ("https://player.vimeo.com/video/1/width/4/height/3", (None, None)),
        # non-https
        (
            "http://www.geogebra.org/material/iframe/id/abc"
            "/width/880/height/660",
            (None, None),
        ),
    ],
)
def test_geogebra_url_size(url, expected):
    assert geogebra_url_size(url) == expected


def test_geogebra_url_size_reads_geogebras_real_embed_tail():
    # THE regression guard on the len(segments) rule. This is the shape GeoGebra's own
    # embed code ships, already pinned verbatim at tests/test_geogebra.py:15 -- 12
    # segments, not 8. A `len(segments) != 8` rule rejects it, frame_ratio then claims
    # NO ratio (is_geogebra_iframe_url is False because "width" in segments), and the
    # wrapper keeps 16:9 while the src imposes 1600/763 -- the original defect.
    url = (
        "https://www.geogebra.org/material/iframe/id/egZJdjsC"
        "/width/1600/height/763/border/888888/sfsb/true"
    )
    assert geogebra_url_size(url) == (1600, 763)


def test_geogebra_url_size_rejects_style_injection():
    # ';' and ':' are legal in a path segment and Django's autoescape does not
    # escape them. Returning raw text here would inject CSS declarations into the
    # style attribute. Must reject, and must return ints when it does not.
    hostile = f"{_BASE}/width/1;position:fixed;top:0;height:100vh/height/1"
    assert geogebra_url_size(hostile) == (None, None)


def test_geogebra_url_size_never_raises_on_malformed_authority():
    assert geogebra_url_size("https://[::1") == (None, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_geogebra.py -k geogebra_url_size -v`
Expected: FAIL — `ImportError: cannot import name 'geogebra_url_size'`.

- [ ] **Step 3: Write minimal implementation**

```python
def geogebra_url_size(url):
    """(W, H) from a canonical GeoGebra URL's /width/W/height/H tail, else (None, None).

    Drives frame_ratio step 0: such a URL sizes the applet itself, so the frame must
    match IT rather than the stored columns or the 16:9 default.

    Scoped to GeoGebra on purpose — a bare "the path contains width" rule would fire
    on other providers and give them an inline ratio they do not have today.

    Positional, not index-searched: the pair must sit at fixed offsets right after the
    id, so a `width` at any other depth is never picked up. Segments AFTER offset 7 are
    ignored -- GeoGebra's real embed src ships .../width/1600/height/763/border/888888/
    sfsb/true, and a `len == 8` rule would reject it, leaving the wrapper at 16:9 while
    the src imposes 1600/763. A trailing repeat therefore loses to the first pair.

    Returns validated ints, NEVER raw path text. frame_ratio's value is interpolated
    into style="aspect-ratio: ...", and Django's autoescape does not escape ';' or ':',
    both legal in a path segment — raw text would let an admin-stored URL inject CSS
    declarations. Never raises.
    """
    try:
        parts = urlsplit(url)
        if parts.scheme != "https":
            return None, None
        if (parts.hostname or "").lower() not in _GEOGEBRA_HOSTS:
            return None, None
        segments = parts.path.split("/")[1:]
        if len(segments) < 8 or segments[:3] != ["material", "iframe", "id"]:
            return None, None
        if segments[4] != "width" or segments[6] != "height":
            return None, None
        if not _ID_RE.match(segments[3]):
            return None, None
        raw_width, raw_height = segments[5], segments[7]
        # .isdecimal(), not .isdigit(): isdigit accepts Unicode superscripts that
        # int() then rejects with ValueError.
        if not (raw_width.isdecimal() and raw_height.isdecimal()):
            return None, None
        width, height = int(raw_width), int(raw_height)
        return (width, height) if usable_dimensions(width, height) else (None, None)
    except (ValueError, TypeError, IndexError):
        return None, None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_geogebra.py -k geogebra_url_size -v`
Expected: PASS (13 cases — 10 parametrized, plus the style-injection, malformed-authority and real-embed-tail tests).

- [ ] **Step 5: Commit**

```bash
git add courses/geogebra.py tests/test_geogebra.py
git commit -m "feat(geogebra): add geogebra_url_size for URL-sized applets"
```

---

### Task 5: `fetch_geogebra_dimensions` — the API lookup

**Files:**
- Modify: `courses/geogebra.py` (transport, logger, cache, lookup, **module docstring rewrite**)
- Modify: `config/settings/base.py`, `config/settings/test.py`, `.env.example`
- Create: `tests/fixtures/geogebra/ws.json`, `wseg.json`, `err_invalid_id.json`, `ws_non_g_first.json`, `ws_two_sized_g.json`, `ws_first_g_unsized.json`, `ws_layout_settings.json`
- Test: `tests/test_geogebra.py`

**Interfaces:**
- Consumes: `usable_dimensions` (Task 1).
- Produces: `fetch_geogebra_dimensions(material_id) -> tuple[int, int] | tuple[None, None]` — **all-or-nothing**, never a partial pair. Consumed by `clean_url` (Task 6). Also produces the transport seam `_open(request, timeout)`, which parser tests and the import guard (Task 10) patch.

**Observed API shapes** (both real, captured live):

| `type` | id | dimensions live at |
|---|---|---|
| `wseg` (applet) | `wgzr7tsu` | `settings.width` / `settings.height` |
| `ws` (worksheet) | `dcjktevj` | `elements[N]["settings"]["width"]` / `["height"]` |

- [ ] **Step 1: Create the fixtures**

`tests/fixtures/` does not exist yet — **create both directory levels** (`tests/fixtures/geogebra/`) before writing the files.

`err_invalid_id.json` deliberately has **no reader**: `test_fetch_degrades_on_http_error_and_logs_it` constructs the `HTTPError` directly with `fp=None`, because `build_opener` keeps `HTTPErrorProcessor` and a 400 therefore raises *before* `resp.read()`. The file is checked in as documentation of the real error shape, so a future reader can see what the API actually returns; the test asserts only that an `HTTPError` degrades.

`tests/fixtures/geogebra/ws.json` (the real `dcjktevj` response, trimmed — note it has **no** top-level `settings` key):

```json
{
  "id": "dcjktevj",
  "title": "korelacja 1",
  "type": "ws",
  "visibility": "S",
  "elements": [
    {
      "id": 42153397,
      "order": 0,
      "type": "G",
      "settings": {"appName": "classic", "width": 880, "height": 660, "scale": 1}
    }
  ]
}
```

`tests/fixtures/geogebra/wseg.json` (the real `wgzr7tsu` response, trimmed — dimensions at top level):

```json
{
  "id": "wgzr7tsu",
  "title": "",
  "type": "wseg",
  "visibility": "S",
  "worksheet_id": "dcjktevj",
  "settings": {"appName": "classic", "width": 880, "height": 660, "scale": 1}
}
```

`tests/fixtures/geogebra/err_invalid_id.json` (the real 400 body):

```json
{"error": {"code": "err_invalid_id"}}
```

`tests/fixtures/geogebra/ws_non_g_first.json` — **derived** (no captured response has this; the fixture-realism rule yields to covering the branch). A non-`G` entry, then junk entries that must be *skipped rather than fatal*, then the sole sized `G`:

```json
{
  "id": "derived",
  "type": "ws",
  "elements": [
    {"id": 1, "type": "T", "settings": {"width": 100, "height": 50}},
    "a string, not a dict",
    null,
    {"id": 2, "type": "G", "settings": {"appName": "classic", "width": 880, "height": 660}}
  ]
}
```

`tests/fixtures/geogebra/ws_first_g_unsized.json` — **derived**: first `G` has no usable pair, a later one does.

```json
{
  "id": "derived",
  "type": "ws",
  "elements": [
    {"id": 1, "type": "G", "settings": {"appName": "classic"}},
    {"id": 2, "type": "G", "settings": {"appName": "classic", "width": 800, "height": 400}}
  ]
}
```

`tests/fixtures/geogebra/ws_two_sized_g.json` — **derived**: two sized `G` entries.

```json
{
  "id": "derived",
  "type": "ws",
  "elements": [
    {"id": 1, "type": "G", "settings": {"appName": "classic", "width": 880, "height": 660}},
    {"id": 2, "type": "G", "settings": {"appName": "classic", "width": 800, "height": 400}}
  ]
}
```

`tests/fixtures/geogebra/ws_layout_settings.json` — **derived**: a top-level `settings` carrying only layout keys, plus a usable element. Pins the fallthrough-on-usable-dimensions rule.

```json
{
  "id": "derived",
  "type": "ws",
  "settings": {"appName": "classic", "scale": 1},
  "elements": [
    {"id": 1, "type": "G", "settings": {"appName": "classic", "width": 880, "height": 660}}
  ]
}
```

- [ ] **Step 2: Add the settings flag**

`config/settings/base.py`, beside `ALLOWED_EMBED_DOMAINS`:

```python
# Kill switch for the GeoGebra applet-size lookup (courses/geogebra.py). env-backed so
# a deployment behind an egress-restricted network can disable a per-save outbound call
# that would otherwise always time out.
GEOGEBRA_API_LOOKUP = env.bool("LIBLI_GEOGEBRA_API_LOOKUP", default=True)
```

`config/settings/test.py`:

```python
# The suite must never reach geogebra.org. Tests that exercise the lookup opt back in
# with override_settings(GEOGEBRA_API_LOOKUP=True).
GEOGEBRA_API_LOOKUP = False
```

`.env.example`, beside the other `LIBLI_` entries:

```
# Set to false to disable the GeoGebra applet-size lookup (e.g. no outbound network).
# LIBLI_GEOGEBRA_API_LOOKUP=true
```

The line is **commented out**, matching its neighbour `.env.example:21` (`# LIBLI_ALLOWED_EMBED_DOMAINS=…`). These entries are optional overrides of a settings default; an active line would make the override read as mandatory.

- [ ] **Step 3: Write the failing tests**

As in Task 1, **`import pytest` is already line 1** of `tests/test_geogebra.py` — it is shown below only to place the others in isort order, not to be pasted again.

```python
import json
import pathlib
import ssl
import urllib.error
from unittest.mock import patch

import pytest  # ALREADY PRESENT at line 1 — do not paste a second time
from django.core.cache import cache
from django.test import override_settings

from courses.geogebra import fetch_geogebra_dimensions

_FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "geogebra"


def _payload(name):
    return (_FIXTURES / name).read_bytes()


def _patch_open(body=None, exc=None):
    """Patch the transport seam; return the mock so tests can assert on call args.

    The double MUST be a context manager: fetch_geogebra_dimensions uses
    `with _open(...) as resp:` (needed because the read is capped, so the connection is
    never drained and an unclosed response leaks a socket per call).
    """

    class _Resp:
        def read(self, n=-1):
            return body[:n] if n and n > 0 else body

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    def _side_effect(request, timeout=None):
        if exc is not None:
            raise exc
        return _Resp()

    return patch("courses.geogebra._open", side_effect=_side_effect)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_reads_top_level_settings_for_an_applet():
    with _patch_open(_payload("wseg.json")):
        assert fetch_geogebra_dimensions("wgzr7tsu") == (880, 660)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_reads_element_settings_for_a_worksheet():
    with _patch_open(_payload("ws.json")):
        assert fetch_geogebra_dimensions("dcjktevj") == (880, 660)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_skips_non_g_and_junk_entries_without_aborting_the_scan():
    # The bare `except Exception` wraps the whole body, so a junk entry raising
    # mid-scan would abort it and return (None, None) even though a usable G
    # follows. Per-entry access must be defensive.
    with _patch_open(_payload("ws_non_g_first.json")):
        assert fetch_geogebra_dimensions("derived") == (880, 660)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_keeps_scanning_past_a_g_with_no_usable_pair():
    with _patch_open(_payload("ws_first_g_unsized.json")):
        assert fetch_geogebra_dimensions("derived") == (800, 400)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_refuses_to_guess_on_a_multi_applet_worksheet(caplog):
    # The iframe embeds the WHOLE worksheet, so "the first G" is an arbitrary pick
    # that need bear no relation to the rendered ratio. A confidently wrong frame
    # with size_unknown False is worse than the 4:3 fallback plus a badge.
    with _patch_open(_payload("ws_two_sized_g.json")):
        assert fetch_geogebra_dimensions("derived") == (None, None)
    assert any("multiple" in r.message.lower() for r in caplog.records)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_falls_through_a_top_level_settings_without_dimensions():
    with _patch_open(_payload("ws_layout_settings.json")):
        assert fetch_geogebra_dimensions("derived") == (880, 660)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_degrades_on_http_error_and_logs_it(caplog):
    err = urllib.error.HTTPError(
        "https://api.geogebra.org/x", 400, "Bad Request", {}, None
    )
    with _patch_open(exc=err):
        assert fetch_geogebra_dimensions("nosuchid00") == (None, None)
    record = next(r for r in caplog.records if r.name == "courses.geogebra")
    assert "nosuchid00" in record.message and "400" in record.message


@override_settings(GEOGEBRA_API_LOOKUP=True)
@pytest.mark.parametrize(
    "exc",
    [
        urllib.error.URLError("unreachable"),
        TimeoutError("timed out"),
        # NOT a URLError subclass — proves the bare except is needed
        ssl.SSLError("handshake"),
    ],
)
def test_fetch_degrades_on_any_transport_exception(exc):
    with _patch_open(exc=exc):
        assert fetch_geogebra_dimensions("dcjktevj") == (None, None)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_degrades_on_unparseable_body():
    with _patch_open(b"not json at all"):
        assert fetch_geogebra_dimensions("dcjktevj") == (None, None)


@override_settings(GEOGEBRA_API_LOOKUP=True)
@pytest.mark.parametrize("bad", [0, -5, "880", 2147483648, True, 880.0])
def test_fetch_rejects_unusable_width_values(bad):
    body = json.dumps(
        {"id": "x", "type": "wseg", "settings": {"width": bad, "height": 660}}
    ).encode()
    with _patch_open(body):
        assert fetch_geogebra_dimensions("x") == (None, None)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_treats_an_oversized_body_as_a_distinct_failure(caplog):
    from courses.geogebra import _MAX_BODY_BYTES

    with _patch_open(b"x" * (_MAX_BODY_BYTES + 1)):
        assert fetch_geogebra_dimensions("dcjktevj") == (None, None)
    assert any("oversiz" in r.message.lower() for r in caplog.records)


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_sends_the_explicit_user_agent_and_the_configured_timeout():
    from courses.geogebra import _TIMEOUT_SECONDS, _USER_AGENT

    with _patch_open(_payload("wseg.json")) as opener:
        fetch_geogebra_dimensions("wgzr7tsu")
    request = opener.call_args.args[0]
    # Request.add_header stores keys .capitalize()d, so get_header("User-Agent")
    # returns None. Lowercase 'a' is the correct spelling here.
    assert request.get_header("User-agent") == _USER_AGENT
    assert opener.call_args.kwargs["timeout"] == _TIMEOUT_SECONDS
    # NOTE what this pins: that the CALLER passes the constant. The forgotten-kwarg
    # bug would live inside _open, below this patch point.


@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_fetch_negative_caches_a_failure_for_the_same_id():
    with _patch_open(exc=urllib.error.URLError("down")) as opener:
        assert fetch_geogebra_dimensions("dcjktevj") == (None, None)
        assert fetch_geogebra_dimensions("dcjktevj") == (None, None)
    assert opener.call_count == 1


def test_fetch_kill_switch_makes_no_request_and_writes_no_sentinel():
    # The ONE test that runs under the suite's GEOGEBRA_API_LOOKUP=False default.
    with _patch_open(_payload("wseg.json")) as opener:
        assert fetch_geogebra_dimensions("wgzr7tsu") == (None, None)
    opener.assert_not_called()
    # No cache WRITE either: a shared _fail() exit that cached here would poison the
    # sentinel for 60s, so flipping the flag on would still short-circuit.
    assert cache.get("geogebra:dims:wgzr7tsu") is None


def test_no_redirect_handler_refuses_redirects():
    from courses.geogebra import _NoRedirect

    # integrations/delivery.py ships this handler entirely untested — grep for
    # _NoRedirect under tests/ returns nothing — so this is a new test, not reuse.
    # It RAISES (matching delivery.py verbatim); it does not return None.
    class _Req:
        full_url = "https://api.geogebra.org/v1.0/materials/abc"

    with pytest.raises(urllib.error.HTTPError):
        _NoRedirect().redirect_request(_Req(), None, 302, "Found", {}, "http://evil")
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/test_geogebra.py -k "fetch or no_redirect" -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_geogebra_dimensions'`.

**`or no_redirect` is not optional.** `test_no_redirect_handler_refuses_redirects` matches neither `fetch` nor anything else in a bare `-k fetch`, so under the original selector it would first execute at Step 7 against a *finished* implementation — green, having never been seen red. That is precisely the "a passing test proves nothing" hazard in Global Constraints, and it matters here more than usual: the plan's own note records that `integrations/delivery.py` ships this handler entirely untested, so this test is the first coverage the pattern has ever had.

Its RED reason differs from the others — it fails on `ImportError: cannot import name '_NoRedirect'` rather than on the missing `fetch_geogebra_dimensions`. After Step 5 lands, additionally confirm it can fail for the *behavioural* reason: temporarily change `redirect_request` to `return None` instead of raising, re-run, confirm `Failed: DID NOT RAISE`, then revert. An import-error red does not demonstrate that the assertion discriminates.

- [ ] **Step 5: Write the implementation**

This step adds three things to `courses/geogebra.py` in **three different places** — do not paste them as one block at the top of the file, which would strand `_NoRedirect`/`_open` above the existing `_GEOGEBRA_HOSTS`/`_ID_RE`/`_CANONICAL` constants and above Task 1's `usable_dimensions`.

**(a) Imports — merge into the existing top-of-file import block, in isort order** (`force-single-line = true`). The file already has `import re` and `from urllib.parse import urlsplit`; the stdlib names join that group, and `django` starts a new third-party group after it. Do **not** append these as a second block lower down — `I001` and `E402` both fire (see Global Constraints).

```python
import json
import logging
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
```

**(b) Constants and the logger — beside `DIM_MAX`**, in the constants region Task 1 established after `_CANONICAL`:

```python
logger = logging.getLogger(__name__)

_API_PREFIX = "https://api.geogebra.org/"
# A module constant rather than a setting, matching the pattern of
# integrations/delivery.py :: TIMEOUT_SECONDS = 10. The shorter 3s is chosen because
# this call sits inside save_element's row lock.
_TIMEOUT_SECONDS = 3
_MAX_BODY_BYTES = 65536  # ~55x the measured 1,177-byte ws response
_NEGATIVE_TTL_SECONDS = 60
_USER_AGENT = "libli/1.0 (+https://github.com/krzyssikora/libli)"
```

**(c) The transport — immediately above `fetch_geogebra_dimensions`**, i.e. below every parsing function, so the module still reads parsers-then-network:

```python
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects, so a URL checked at construction cannot be followed elsewhere.

    Duplicated from integrations/delivery.py :: _NoRedirect deliberately rather than
    imported: that module does `from integrations.models import WebhookDelivery` at
    module level, and courses/models.py imports this module at module level — an
    import would pull integrations.models into courses at app-load time. Every
    existing courses -> integrations reference in the repo is a lazy in-function
    import.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Body copied VERBATIM from delivery.py — it RAISES, it does not return None.
        # The raise is then swallowed by fetch_geogebra_dimensions' bare except and
        # degrades to the 4:3 fallback, which is the intended behaviour.
        raise urllib.error.HTTPError(
            req.full_url, code, "redirect refused", headers, fp
        )


def _open(request, timeout):
    """The transport seam. Patched by tests; the only place the network is touched."""
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)
```

And the lookup itself:

```python
def _settings_dimensions(node):
    """(W, H) from a node's `settings` block when usable, else (None, None).

    Defensive per entry: a non-dict node or non-dict settings is SKIPPED, not fatal.
    The outer bare `except Exception` would otherwise abort the whole elements scan on
    one malformed entry, silently contradicting "keep scanning".
    """
    if not isinstance(node, dict):
        return None, None
    block = node.get("settings")
    if not isinstance(block, dict):
        return None, None
    width, height = block.get("width"), block.get("height")
    return (width, height) if usable_dimensions(width, height) else (None, None)


def _dimensions_from_payload(payload, material_id):
    """Apply the selection rule; log which of the three failure modes fired."""
    if not isinstance(payload, dict):
        return None, None

    width, height = _settings_dimensions(payload)
    if usable_dimensions(width, height):
        return width, height

    elements = payload.get("elements")
    if not isinstance(elements, list):
        logger.warning(
            "geogebra %s: no usable settings and no elements list", material_id
        )
        return None, None

    sized = []
    for entry in elements:
        if not isinstance(entry, dict) or entry.get("type") != "G":
            continue
        entry_width, entry_height = _settings_dimensions(entry)
        if usable_dimensions(entry_width, entry_height):
            sized.append((entry_width, entry_height))

    if len(sized) == 1:
        return sized[0]
    if sized:
        # The iframe embeds the whole worksheet, so picking one applet's ratio would be
        # a guess. A confidently wrong frame with size_unknown False is worse than the
        # 4:3 fallback plus a badge.
        logger.warning(
            "geogebra %s: multiple sized G elements (%d), refusing to guess",
            material_id,
            len(sized),
        )
    else:
        logger.warning(
            "geogebra %s: no G element yielded usable dimensions", material_id
        )
    return None, None


def fetch_geogebra_dimensions(material_id):
    """The material's authored (width, height), or (None, None). All-or-nothing.

    Never raises — a bare `except Exception`, matching courses/embed.py's precedent:
    urlopen can raise RemoteDisconnected, ConnectionResetError, ssl.SSLError,
    UnicodeDecodeError and ValueError, none of which are URLError subclasses, and
    anything escaping into clean_url would 500 the save.
    """
    # Read the flag on EVERY call — capturing it at import would make every
    # override_settings a silent no-op and let the invalid-input tests pass vacuously.
    if not settings.GEOGEBRA_API_LOOKUP:
        return None, None  # no cache read, no cache WRITE, no request

    cache_key = f"geogebra:dims:{material_id}"
    if cache.get(cache_key):
        return None, None

    def _fail(reason):
        logger.warning("geogebra %s: %s", material_id, reason)
        # truthy: None reads as a cache miss
        cache.set(cache_key, True, _NEGATIVE_TTL_SECONDS)
        return None, None

    url = f"{_API_PREFIX}v1.0/materials/{material_id}?scope=basic"
    if not url.startswith(_API_PREFIX):
        # Defensive only and unreachable by construction (material_id has passed
        # _ID_RE, so it cannot introduce a scheme or host). Deliberately untested: a
        # branch that cannot be driven cannot be falsified to RED. The real controls
        # are _ID_RE and _NoRedirect.
        return None, None

    try:
        # noqa: S310 mirrors integrations/delivery.py:50,122 — the URL is built from a
        # hardcoded _API_PREFIX plus an _ID_RE-validated id, so it cannot carry an
        # attacker-chosen scheme or host, and _NoRedirect stops the opener from
        # following one.
        request = urllib.request.Request(  # noqa: S310
            url, headers={"User-Agent": _USER_AGENT}
        )
        with _open(request, timeout=_TIMEOUT_SECONDS) as response:
            body = response.read(_MAX_BODY_BYTES + 1)  # +1 so oversize is detectable
    except urllib.error.HTTPError as exc:
        # A 4xx/5xx raises from INSIDE _open, so the `with` above is never entered and
        # the error's own fp is never closed — close it explicitly or the 400 test
        # surfaces an unexplained ResourceWarning.
        try:
            exc.close()
        except Exception:  # noqa: BLE001 - closing must never mask the original failure
            pass
        return _fail(f"HTTP {exc.code}")
    except Exception as exc:  # noqa: BLE001 - the never-raises contract
        return _fail(f"lookup failed ({type(exc).__name__})")

    if len(body) > _MAX_BODY_BYTES:
        return _fail(f"response body oversized (>{_MAX_BODY_BYTES} bytes)")

    # The parse AND the selection scan both sit inside this try. Putting
    # _dimensions_from_payload outside it would let anything raising in the scan
    # propagate into clean_url and 500 the save -- the exact outcome the never-raises
    # contract exists to prevent, and worse than the abort the per-entry defensiveness
    # already guards against.
    try:
        payload = json.loads(body)
        width, height = _dimensions_from_payload(payload, material_id)
    except Exception as exc:  # noqa: BLE001 - the never-raises contract
        return _fail(f"unparseable payload ({type(exc).__name__})")

    if not usable_dimensions(width, height):
        cache.set(cache_key, True, _NEGATIVE_TTL_SECONDS)
        return None, None
    return width, height
```

- [ ] **Step 6: Rewrite the module docstring**

The current docstring ends *"It never raises — validation stays entirely in `validate_embed_url`"* and describes a pure-parsing module with no network, no cache and no settings dependency. All three are now false. Replace the module docstring's closing paragraph with:

```python
"""...

This module is both the single GeoGebra URL parser and the single place the GeoGebra
API is called. Parsing functions rebuild recognized https inputs from scratch and return
everything else unchanged; the one network function performs a single capped GET behind
the GEOGEBRA_API_LOOKUP kill switch. Nothing here raises — every failure degrades to a
neutral value, because these run inside form validation and inside page render, where an
exception would 500 a save or a student unit page.
"""
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_geogebra.py -v`
Expected: PASS (all tasks 1–5).

- [ ] **Step 8: Commit**

```bash
git add courses/geogebra.py config/settings/base.py config/settings/test.py .env.example \
        tests/test_geogebra.py tests/fixtures/geogebra/
git commit -m "feat(geogebra): look the authored applet size up from the GeoGebra API"
```

---

### Task 6: Wire the lookup into `IframeElementForm.clean_url`

**Files:**
- Modify: `courses/element_forms.py:182-194`
- Test: `tests/test_iframe_dimensions.py`

**Interfaces:**
- Consumes: `geogebra_material_id` (Task 2), `usable_dimensions` (Task 1), `fetch_geogebra_dimensions` (Task 5), plus existing `extract_embed_url` and `parse_iframe_dimensions`.
- Produces: no new names. Behaviour: the lookup fires on exactly three occasions (fresh dimensionless paste, URL change, and any save where the stored pair is unusable — the retry path).

**`extract_embed_url` is deliberately NOT modified.** It is shared with course import via `courses/transfer/payloads.py :: _val_iframe` → `_canonical_embed`, so a network call inside it would make imports hit geogebra.org. Task 10 guards this boundary.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_iframe_dimensions.py` (`URL` is the existing module constant, a canonical GeoGebra URL):

```python
from unittest.mock import patch

OTHER_FORM_URL = "https://player.vimeo.com/video/123"  # example.com is NOT whitelisted


def _patch_lookup(result=(880, 660)):
    return patch("courses.element_forms.fetch_geogebra_dimensions", return_value=result)


@pytest.mark.django_db
def test_form_share_link_paste_canonicalises_then_looks_up():
    # Post the actual SHARE-LINK shape, not the already-canonical URL: this is the
    # input the whole feature exists for, and asserting the lookup arg additionally
    # pins that clean_url gates on the CANONICALISED url, not the raw paste.
    form = IframeElementForm(
        data={"url": "https://www.geogebra.org/m/dcjktevj", "title": "P"}
    )
    with _patch_lookup() as lookup:
        assert form.is_valid(), form.errors
    saved = form.save()
    assert (saved.width, saved.height) == (880, 660)
    lookup.assert_called_once_with("dcjktevj")


@pytest.mark.django_db
def test_form_non_geogebra_dimensionless_paste_never_looks_up():
    # THE guard on the `and mid` conjunct. Every other form test either uses a
    # GeoGebra URL (lookup fires anyway) or short-circuits on a usable pair BEFORE
    # mid is consulted -- so without this test a build that DELETES `and mid` stays
    # green while issuing a live GET to
    # https://api.geogebra.org/v1.0/materials/?scope=basic (empty id!) on every
    # dimensionless non-GeoGebra paste, inside the unit row lock.
    form = IframeElementForm(data={"url": OTHER_FORM_URL, "title": "P"})
    with _patch_lookup() as lookup:
        assert form.is_valid(), form.errors
    lookup.assert_not_called()


@pytest.mark.django_db
def test_form_geogebra_host_without_a_material_id_never_looks_up():
    # Second half of the `and mid` guard: a GeoGebra HOST whose URL yields no
    # material id must not trigger a lookup either.
    form = IframeElementForm(
        data={"url": "https://www.geogebra.org/x", "title": "P"}
    )
    with _patch_lookup() as lookup:
        # If extract_embed_url rejects this URL the form is invalid -- that is fine
        # and the assertion below still holds; the point is that no lookup fires.
        form.is_valid()
    lookup.assert_not_called()


@pytest.mark.django_db
def test_form_static_embed_paste_never_looks_up():
    form = IframeElementForm(data={"url": _FULL_TAG, "title": "P"})
    with _patch_lookup() as lookup:
        assert form.is_valid(), form.errors
    lookup.assert_not_called()


@pytest.mark.django_db
def test_form_title_only_edit_of_a_sized_element_never_looks_up():
    # The textarea is pre-filled with the stored CANONICAL URL, so
    # parse_iframe_dimensions returns (None, None) on every later edit. Without the
    # instance guard this would fire a network call on every rename and could silently
    # replace the author's captured pair.
    obj = IframeElement.objects.create(url=URL, title="P", width=880, height=660)
    form = IframeElementForm(data={"url": URL, "title": "renamed"}, instance=obj)
    with _patch_lookup((640, 480)) as lookup:
        assert form.is_valid(), form.errors
    saved = form.save()
    lookup.assert_not_called()
    assert (saved.width, saved.height) == (880, 660)  # the invariant, asserted directly


@pytest.mark.django_db
def test_form_url_change_clears_the_stale_pair_and_looks_up_afresh():
    obj = IframeElement.objects.create(url=URL, title="P", width=880, height=660)
    new_url = "https://www.geogebra.org/material/iframe/id/other123"
    form = IframeElementForm(data={"url": new_url, "title": "P"}, instance=obj)
    with _patch_lookup((800, 400)) as lookup:
        assert form.is_valid(), form.errors
    saved = form.save()
    assert lookup.call_count == 1
    assert (saved.width, saved.height) == (800, 400)


@pytest.mark.django_db
def test_form_url_change_with_a_failed_lookup_does_not_keep_the_old_pair():
    # THE test for what the stale-clear actually prevents. Every other url-change test
    # patches the lookup to SUCCEED, so its assertion is satisfied by the lookup's own
    # overwrite and would still pass with the clear deleted entirely. Only a FAILED
    # lookup exposes the real failure mode: the new material silently inheriting the
    # previous material's 880x660, rendering a confidently wrong frame with
    # size_unknown False -- so not even a badge to explain it.
    #
    # lookup.call_count in the sibling test does detect the clear indirectly, but only
    # while the guard keeps its current shape; this asserts the user-visible outcome.
    obj = IframeElement.objects.create(url=URL, title="P", width=880, height=660)
    new_url = "https://www.geogebra.org/material/iframe/id/other123"
    form = IframeElementForm(data={"url": new_url, "title": "P"}, instance=obj)
    with _patch_lookup((None, None)):
        assert form.is_valid(), form.errors
    saved = form.save()
    assert (saved.width, saved.height) == (None, None)
    assert saved.size_unknown is True   # the badge the author needs, not a stale frame


@pytest.mark.django_db
def test_form_failed_lookup_saves_with_no_dimensions():
    form = IframeElementForm(data={"url": URL, "title": "P"})
    with _patch_lookup((None, None)):
        assert form.is_valid(), form.errors
    saved = form.save()
    assert (saved.width, saved.height) == (None, None)


@pytest.mark.django_db
def test_form_dimensionless_element_retries_the_lookup_on_a_later_save():
    # Firing case 3: the badge invites a retry, so a save of an element whose stored
    # pair is unusable MUST try again. Gating on url_changed alone would kill this.
    obj = IframeElement.objects.create(url=URL, title="P")
    form = IframeElementForm(data={"url": URL, "title": "P"}, instance=obj)
    with _patch_lookup((880, 660)) as lookup:
        assert form.is_valid(), form.errors
    saved = form.save()
    assert lookup.call_count == 1
    assert (saved.width, saved.height) == (880, 660)


@pytest.mark.django_db
def test_form_non_geogebra_url_change_keeps_its_dimensions():
    # The stale-clear is scoped to GeoGebra. Clearing provider-neutrally would wipe a
    # Vimeo element's captured pair on ANY url edit, with no lookup to restore it.
    obj = IframeElement.objects.create(
        url=OTHER_FORM_URL, title="P", width=640, height=360
    )
    form = IframeElementForm(
        data={"url": "https://player.vimeo.com/video/999", "title": "P"}, instance=obj
    )
    with _patch_lookup() as lookup:
        assert form.is_valid(), form.errors
    saved = form.save()
    lookup.assert_not_called()
    assert (saved.width, saved.height) == (640, 360)


@pytest.mark.django_db
def test_form_geogebra_to_non_geogebra_url_change_keeps_the_geogebra_pair():
    # A KNOWN, ACCEPTED gap: the conjunct tests the NEW url, so swapping a GeoGebra
    # element to a video keeps 880x660. Not a regression (today's code never clears);
    # pinned so a future change to it is deliberate.
    obj = IframeElement.objects.create(url=URL, title="P", width=880, height=660)
    form = IframeElementForm(data={"url": OTHER_FORM_URL, "title": "P"}, instance=obj)
    with _patch_lookup() as lookup:
        assert form.is_valid(), form.errors
    saved = form.save()
    lookup.assert_not_called()
    assert (saved.width, saved.height) == (880, 660)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: **`uv run pytest tests/test_iframe_dimensions.py -v`** — the whole file, not a `-k` subset.
Expected: FAIL — `AttributeError: <module 'courses.element_forms'> does not have the attribute 'fetch_geogebra_dimensions'` (the patch target does not exist yet).

**Do not narrow this with `-k "lookup or …"`.** Five of the ten new tests are named `…_looks_up`, and `looks_up` does **not** contain the substring `lookup`, so a `-k lookup` selector silently skips every one of them — including `test_form_share_link_paste_canonicalises_then_looks_up` (the headline case the whole feature exists for) and both tests this task calls "THE guard on the `and mid` conjunct". Half the new tests would never be seen RED, violating Global Constraints while appearing to satisfy them. Running the file is simpler than getting the selector right; if you do want a subset, `-k "looks_up or lookup or retries or url_change or keeps"` is the spelling that matches.

- [ ] **Step 3: Write the implementation**

In `courses/element_forms.py`, add the from-imports (the patch target only exists under this style):

```python
from courses.geogebra import fetch_geogebra_dimensions
from courses.geogebra import geogebra_material_id
from courses.geogebra import usable_dimensions
```

Replace the body of `IframeElementForm.clean_url`:

```python
    def clean_url(self):
        raw = self.cleaned_data.get("url", "")
        url = extract_embed_url(raw)
        width, height = parse_iframe_dimensions(raw)
        mid = geogebra_material_id(url)  # hoisted: both guards below use it
        url_changed = url != self.instance.url

        # A stored pair describes the OLD material once the URL changes, so drop it and
        # let the new material take the normal lookup path. Scoped to GeoGebra: clearing
        # provider-neutrally would wipe a Vimeo element's captured pair on any URL edit,
        # with no lookup available to restore it.
        if url_changed and not usable_dimensions(width, height) and mid:
            self.instance.width = self.instance.height = None

        # INVARIANT: a *usable* stored pair is never re-derived for an unchanged URL.
        # On an edit the textarea holds the stored canonical URL, so
        # parse_iframe_dimensions returns (None, None) every time; without the instance
        # guard a title-only rename would fire a network call and could silently replace
        # the author's captured size. The lookup therefore fires on exactly three
        # occasions: a fresh dimensionless paste, a URL change, and any save where the
        # stored pair is unusable -- the last being the deliberate retry path the badge
        # invites, and why _NEGATIVE_TTL_SECONDS is only 60s.
        #
        # NOTE: this depends on clean_url running BEFORE _post_clean. self.instance.url
        # still holds the DB value during field cleaning because Django only copies
        # cleaned data onto the instance in construct_instance, which _post_clean calls
        # afterwards. Moving this logic to _post_clean or save() silently inverts
        # url_changed. width/height are not in Meta.fields, so the ceiling is enforced
        # by usable_dimensions here, not by full_clean.
        stored_usable = usable_dimensions(self.instance.width, self.instance.height)
        if not usable_dimensions(width, height) and not stored_usable and mid:
            width, height = fetch_geogebra_dimensions(mid)

        if usable_dimensions(width, height):
            self.instance.width = width
            self.instance.height = height
        return url
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_iframe_dimensions.py -v`
Expected: PASS, **including the pre-existing** `test_form_plain_url_edit_preserves_existing_dimensions` and `test_form_re_paste_overwrites_dimensions`.

- [ ] **Step 5: Re-label the two pre-existing tests whose meaning THIS task changes**

Both are **form** tests, so their semantics change the moment this task lands — not in Task 7, which touches only `models.py` and the render template. Do this **before** the commit below, so the commit that changes the behaviour is also the commit that records it; otherwise the branch carries two committed tests whose names assert something the code no longer does.

| existing test | why it changes |
|---|---|
| `test_form_bare_url_paste_leaves_dimensions_none` | now passes via the **kill switch** (`GEOGEBRA_API_LOOKUP=False` under `config.settings.test`), not via "no lookup fires". Rename to `test_form_bare_url_paste_leaves_dimensions_none_when_lookup_disabled` and add a comment saying so, so it is not misread as independent confirmation that the wiring is inert |
| `test_form_oversized_paste_degrades_without_500` | same caveat — keep the name, add the comment |

Neither is an implementation bug, and neither should be "fixed" by changing production code.

- [ ] **Step 6: Commit**

```bash
git add courses/element_forms.py tests/test_iframe_dimensions.py
git commit -m "feat(embed): look up GeoGebra dimensions when a paste does not carry them"
```

---

### Task 7: `frame_ratio`, `size_unknown`, and the wrapper template

**Files:**
- Modify: `courses/models.py` (`IframeElement`, after `embed_src`)
- Modify: `templates/courses/elements/iframeelement.html:3`
- Test: `tests/test_iframe_dimensions.py` (**two existing render tests change here**; the two *form* tests that also change meaning on this branch were handled in Task 6 Step 5)

**Interfaces:**
- Consumes: `usable_dimensions`, `is_geogebra_iframe_url`, `geogebra_url_size`, `geogebra_material_id`, `GEOGEBRA_DEFAULT_SIZE` (Tasks 1–4).
- Produces: `IframeElement.frame_ratio -> str | None` and `IframeElement.size_unknown -> bool` (the latter consumed by Task 8).

**Import style:** all five names are imported at **module level** in `models.py`. The cycle argument covers them equally (`geogebra.py` imports nothing from `courses`). `embed_src`'s existing in-method `from courses.geogebra import geogebra_sized_src` stays as the **sole** exception — but its comment is **amended**, not left alone: with module-level imports of the same module now sitting a few lines above, an unexplained in-method import reads as an accident. Add a clause noting the module-level predicate imports are safe for the same reason (`geogebra.py` imports nothing from `courses`), so the two styles in one file are visibly deliberate.

**The five-step order is load-bearing.** Step 0 before step 2, and step 1 before step 2, are each pinned by a test with a *disagreeing* precondition.

- [ ] **Step 1: Write the failing tests**

In `tests/test_iframe_dimensions.py`, add a second render constant and the new cases. **`OTHER_RENDER_URL` is only safe in render tests** — they build an unsaved `IframeElement` and call `render_to_string`, bypassing validation; `example.com` is not in `ALLOWED_EMBED_DOMAINS` and would raise in a form test.

```python
# render tests only — example.com is NOT whitelisted, so a form test would raise
OTHER_RENDER_URL = "https://example.com/embed/abc"
SIZED_BASE = "https://www.geogebra.org/material/iframe/id/abc"
SIZED_URL = f"{SIZED_BASE}/width/880/height/660"


def _render_url(url, width=None, height=None):
    el = IframeElement(url=url, title="P", width=width, height=height)
    return render_to_string("courses/elements/iframeelement.html", {"el": el})


def _render(width, height):
    """The pre-existing helper, redefined in terms of _render_url.

    tests/test_iframe_dimensions.py:10 already defines _render(width, height) and two
    surviving tests still call it. Keep the name so those callers are untouched, but
    give it ONE implementation -- two near-identical render helpers in one module leave
    the next reader unable to tell which is canonical.
    """
    return _render_url(URL, width, height)


def test_render_geogebra_without_dimensions_uses_geogebras_own_default():
    html = _render_url(URL)
    assert "aspect-ratio: 800 / 600" in html


@pytest.mark.parametrize("w,h", [(800, None), (None, 600), (0, 0)])
def test_render_geogebra_partial_or_zero_pair_uses_the_default(w, h):
    assert "aspect-ratio: 800 / 600" in _render_url(URL, w, h)


def test_render_non_geogebra_without_dimensions_keeps_the_css_default():
    html = _render_url(OTHER_RENDER_URL)
    assert "embed-frame" in html
    assert "aspect-ratio:" not in html   # the .embed-frame 16:9 default stands


@pytest.mark.parametrize("w,h", [(800, None), (0, 0)])
def test_render_non_geogebra_partial_or_zero_pair_keeps_the_css_default(w, h):
    assert "aspect-ratio:" not in _render_url(OTHER_RENDER_URL, w, h)


def test_render_non_geogebra_with_a_usable_pair_still_gets_its_ratio():
    # Guards that step 1 does not swallow other providers.
    assert "aspect-ratio: 640 / 360" in _render_url(OTHER_RENDER_URL, 640, 360)


def test_render_url_sized_applet_reads_the_ratio_from_the_url():
    assert "aspect-ratio: 880 / 660" in _render_url(SIZED_URL)


def test_render_url_sized_applet_beats_a_disagreeing_stored_pair():
    # THE step-0-vs-step-2 ordering test. The stored pair deliberately DISAGREES with
    # the URL tail; a step-2-first build emits 880 / 660 around a 2:1 applet while
    # geogebra_sized_src leaves the src alone ("width" in segments), violating the
    # "never a frame ratio the src does not back up" invariant.
    url = "https://www.geogebra.org/material/iframe/id/abc/width/800/height/400"
    assert "aspect-ratio: 800 / 400" in _render_url(url, 880, 660)


def test_render_material_url_that_sized_src_will_not_rewrite_claims_no_ratio():
    # THE step-1-vs-step-2 ordering test. /m/<id> carries a material id but is not a
    # shape geogebra_sized_src rewrites, so emitting the stored ratio would frame
    # GeoGebra's 800x600 default in an 880x660 box. Reachable via the admin.
    # This FAILS against the obvious three-branch implementation.
    html = _render_url("https://www.geogebra.org/m/dcjktevj", 880, 660)
    assert "aspect-ratio:" not in html


def test_render_geogebra_host_without_a_material_id_keeps_the_css_default():
    assert "aspect-ratio:" not in _render_url("https://www.geogebra.org/x")


@pytest.mark.parametrize("stored", [(None, None), (880, 660)])
def test_render_degenerate_shapes_follow_the_stored_pair(stored):
    # The two stricter-than-sized_src divergences. geogebra_material_id returns "" for
    # both, so step 1 is SKIPPED and the outcome depends entirely on the stored columns.
    for url in (
        "https://www.geogebra.org/material/iframe/id",
        "https://www.geogebra.org/material/iframe/id/ab%20cd",
    ):
        html = _render_url(url, *stored)
        if stored == (880, 660):
            assert "aspect-ratio: 880 / 660" in html   # step 2
        else:
            assert "aspect-ratio:" not in html          # step 4


def test_render_rejects_style_injection_from_the_url():
    # ';' and ':' are legal path characters and Django's autoescape leaves them alone.
    # Assert on the STYLE attribute only: the injected text legitimately survives inside
    # src="{{ el.embed_src }}", where it is inert, so asserting its absence from the
    # whole document would be RED against a correct build. Sanitising embed_src is NOT
    # in scope.
    hostile = (
        "https://www.geogebra.org/material/iframe/id/abc"
        "/width/1;position:fixed;top:0;height:100vh/height/1"
    )
    html = _render_url(hostile)
    assert 'style="aspect-ratio:' not in html


@pytest.mark.parametrize(
    "url",
    [
        f"{SIZED_BASE}/width/abc/height/def",
        f"{SIZED_BASE}/width/880",
        f"{SIZED_BASE}/width/0/height/0",
        f"{SIZED_BASE}/height/660/width/880",
    ],
)
def test_render_step0_rejection_cases_fall_through_to_no_inline_ratio(url):
    # These are covered at the geogebra_url_size unit level too, but "(None, None)"
    # is NOT the same claim as "the wrapper carries no inline ratio" -- the render
    # outcome depends on steps 1 and 2 running afterwards, which a unit test cannot
    # exercise. That fall-through is exactly what these pin.
    #
    # ACCEPTED GAP, not an oversight: all four keep the CSS 16:9 AND get no badge
    # (size_unknown is False, because "width" in segments makes is_geogebra_iframe_url
    # False). See the note under this block for why 800/600 is NOT the right answer
    # here. If you are tempted to "fix" this, read that note first.
    assert "aspect-ratio:" not in _render_url(url)


def test_render_geogebras_real_embed_tail_gets_the_urls_own_ratio():
    # The other half of the len(segments) >= 8 rule, at render level: GeoGebra's own
    # published embed src (12 segments) must take its ratio from the URL. Under a
    # len == 8 rule this renders 16:9 while the src imposes 1600/763 -- the defect.
    url = (
        "https://www.geogebra.org/material/iframe/id/egZJdjsC"
        "/width/1600/height/763/border/888888/sfsb/true"
    )
    assert "aspect-ratio: 1600 / 763" in _render_url(url)


def test_render_non_geogebra_url_with_width_height_segments_gets_no_ratio():
    # geogebra_url_size is GeoGebra-scoped; a bare "path contains width" rule would
    # have given this provider an inline ratio it does not have today.
    url = "https://player.vimeo.com/video/1/width/4/height/3"
    assert "aspect-ratio:" not in _render_url(url)


def test_render_never_raises_on_a_malformed_authority():
    # frame_ratio's step 0 runs FIRST, so an unguarded urlsplit here would 500 the
    # student unit page before any fallback could be reached.
    assert "embed-frame" in _render_url("https://[::1")


@pytest.mark.parametrize(   # no django_db: an UNSAVED instance touches no database
    "url,width,height,expected",
    [
        (URL, None, None, True),            # canonical GeoGebra, no size -> badge
        (URL, 880, 660, False),             # sized -> no badge
        (URL, 800, None, True),             # partial pair mirrors frame_ratio
        # not the canonical shape sized_src rewrites
        ("https://www.geogebra.org/m/dcjktevj", None, None, False),
        ("https://www.geogebra.org/x", None, None, False),
        (OTHER_RENDER_URL, None, None, False),   # non-GeoGebra
    ],
)
def test_size_unknown_drives_the_editor_badge(url, width, height, expected):
    el = IframeElement(url=url, width=width, height=height)
    assert el.size_unknown is expected
```

`test_size_unknown_drives_the_editor_badge` lives **here, not in Task 8**, because Task 7 Step 3 is what adds the property. Left in Task 8 it would first run against an implementation that already exists and pass immediately, never demonstrating a failure mode — Task 7 would ship production code its own task never tests. Here it fails cleanly with `AttributeError: 'IframeElement' object has no attribute 'size_unknown'`.

It uses `OTHER_RENDER_URL` rather than `OTHER_FORM_URL` for the non-GeoGebra row: the instance is unsaved and never validated, so the whitelist is irrelevant, and this keeps the test next to the constant it sits beside.

**The malformed-tail gap, stated deliberately.** A canonical GeoGebra URL whose `/width/…/height/…` tail is junk (`…/width/abc/height/def`, `…/width/880` with no height, `…/width/0/height/0`, `…/height/660/width/880`) falls through **every** step: step 0 rejects the tail, step 1 returns `None` because `geogebra_material_id` finds the id while `is_geogebra_iframe_url` is False (`"width" in segments`), step 2 has no stored pair, and step 3 is gated on the same `is_geogebra_iframe_url`. Result: CSS 16:9, and `size_unknown` is False so **no badge appears either**.

This is accepted, and it is the conservative choice rather than a missed case:

- **It is unreachable through the product.** `clean_url` canonicalizes every paste, stripping the tail; only the Django admin or a legacy row can produce this shape. The census's `canonical+width` bucket counts it, and measured zero.
- **`800 / 600` would be a fabricated claim.** Step 3's fallback is justified by a *measurement* — GeoGebra's shell hardcodes `(parameters.width || 800) * 1`, so a **dimensionless** embed provably renders 800×600. A junk tail is not dimensionless: the shell receives `"abc"` and computes `NaN`, and what it renders then is unmeasured. Emitting `800 / 600` here would violate the invariant the five-step order exists to protect — never claim a ratio the src does not back up.
- **Widening `size_unknown` alone was considered and rejected for this branch.** A badge would genuinely help the author, and needs no ratio claim. But the property's stated contract is that it shares `usable_dimensions` with `frame_ratio` "so the badge and the ratio can never disagree", and widening one without the other breaks that invariant for a shape that cannot occur in production. Changing it is a design decision, not an implementation one — raise it as follow-up work rather than deciding it mid-execution.

Record this paragraph's conclusion in the PR body so the reviewer sees the gap was chosen, not missed.

**Delete or rewrite these two existing render tests** — they are not implementation bugs:

| existing test | why it changes |
|---|---|
| `test_render_falls_back_to_16x9_when_dimensions_unknown` | its `URL` is a **GeoGebra** URL, so `(None, None)` now yields `800 / 600` — replaced by `test_render_geogebra_without_dimensions_uses_geogebras_own_default` plus the non-GeoGebra case |
| `test_render_falls_back_when_dimensions_partial_or_zero` | same, for `(800, None)`, `(None, 600)`, `(0, 0)` — replaced by the two parametrized cases above |

Two *form* tests also change meaning on this branch — `test_form_bare_url_paste_leaves_dimensions_none` and `test_form_oversized_paste_degrades_without_500` — but they are handled in **Task 6, Step 5**, because it is Task 6 that changes their behaviour. This task touches only `models.py` and the render template; if they are still un-relabelled when you get here, Task 6 was executed incompletely.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_iframe_dimensions.py -v`
Expected: FAIL — the new render tests fail with `aspect-ratio: 800 / 600` absent (the template still tests `el.width and el.height`).

- [ ] **Step 3: Write the implementation**

In `courses/models.py`, at module level:

```python
from courses.geogebra import GEOGEBRA_DEFAULT_SIZE
from courses.geogebra import geogebra_material_id
from courses.geogebra import geogebra_url_size
from courses.geogebra import is_geogebra_iframe_url
from courses.geogebra import usable_dimensions
```

Add to `IframeElement`, after `embed_src`:

```python
    @property
    def frame_ratio(self):
        """CSS aspect-ratio for the wrapper, or None to keep .embed-frame's 16:9.

        FIVE ordered steps (0-4). The order is load-bearing in both directions: the
        rendered frame must never claim a ratio the src does not back up, and never
        ignore one the src does impose.
        """
        # 0. The URL sizes the applet itself -> match IT, not the stored columns. Must
        #    precede step 2, or a URL-sized applet gets a disagreeing stored ratio.
        url_width, url_height = geogebra_url_size(self.url)
        if usable_dimensions(url_width, url_height):
            return f"{url_width} / {url_height}"
        # 1. A GeoGebra material in a shape geogebra_sized_src will NOT rewrite: claim
        #    nothing, even with stored dimensions, or we frame GeoGebra's 800x600
        #    default in a W/H box. Must precede step 2.
        if geogebra_material_id(self.url) and not is_geogebra_iframe_url(self.url):
            return None
        # 2. A known size -- also the branch every non-GeoGebra provider reaches.
        if usable_dimensions(self.width, self.height):
            return f"{self.width} / {self.height}"
        # 3. A canonical GeoGebra embed with no known size renders at GeoGebra's own
        #    default, measured to leave a 0.0px gap; 16:9 leaves 161.3px.
        if is_geogebra_iframe_url(self.url):
            return "{} / {}".format(*GEOGEBRA_DEFAULT_SIZE)
        # 4. Everything else keeps the CSS default.
        return None

    @property
    def size_unknown(self):
        """True for a GeoGebra embed in the canonical material/iframe/id shape whose
        dimensions are not usable -- drives the editor badge.

        Deliberately NARROWER than "a material embed": /m/<id> and
        /material/show/id/<id> are excluded, because geogebra_sized_src will not size
        them either, so a badge telling the author to paste the embed code could not
        help. Shares usable_dimensions with frame_ratio, so badge and ratio cannot
        disagree.
        """
        return is_geogebra_iframe_url(self.url) and not usable_dimensions(
            self.width, self.height
        )
```

In `templates/courses/elements/iframeelement.html`, line 3. Bind the value **once** with `{% with %}` rather than naming the property twice:

```html
  {% with ratio=el.frame_ratio %}
  <div class="embed-frame"{% if ratio %} style="aspect-ratio: {{ ratio }}"{% endif %}>
    {# ... the existing children of this div, unchanged ... #}
  </div>
  {% endwith %}
```

The `{% with %}` wraps the **whole element** — opening tag, existing children, and `</div>`. Only the opening tag itself changes; the children are untouched and must stay where they are. (The block strictly only needs to span the one interpolation, but closing it immediately after the opening tag reads as a paste error and invites someone to "repair" it by moving the children out.)

**Why `{% with %}`:** `{% if el.frame_ratio %}…{{ el.frame_ratio }}` evaluates the property **twice**, and each evaluation calls `geogebra_url_size`, `geogebra_material_id` and `is_geogebra_iframe_url`, every one of which runs its own `urlsplit` — up to a dozen parses per iframe element per page render, on the student unit page, which can carry many. One binding halves it for free and costs nothing in clarity. (A `cached_property` would also work, but it would silently stale if `width`/`height` were reassigned after a first read; `{% with %}` has no such failure mode.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_iframe_dimensions.py -v`
Expected: PASS.

Run: `uv run pytest tests/test_geogebra.py tests/test_embed.py tests/test_transfer_import.py -v`
Expected: PASS — no collateral damage.

- [ ] **Step 5: Commit**

```bash
git add courses/models.py templates/courses/elements/iframeelement.html tests/test_iframe_dimensions.py
git commit -m "feat(embed): provider-aware wrapper ratio for GeoGebra embeds"
```

---

### Task 8: The editor badge, its CSS, and the catalog

**Files:**
- Modify: `templates/courses/manage/editor/_element_row.html` (between lines 308 and 309)
- Modify: `courses/static/courses/css/editor.css` (after the `.el-tag` rule at line 79)
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: `tests/test_iframe_dimensions.py`

**Interfaces:**
- Consumes: `IframeElement.size_unknown` (Task 7).
- Produces: nothing consumed by later tasks except the e2e in Task 9.

The concrete object is in scope as **`obj`**, not `el` (which is the join row). An iframe element falls through six top-level `{% elif %}` branches to the terminal `{% else %}` at line 300.

- [ ] **Step 1: Write the failing test**

The `size_unknown` property test lives in **Task 7**, alongside the code that adds the property. What this task adds is the render-level check that the badge actually reaches the page — **the property test alone would pass with the template never edited.** Fully concrete; nothing to substitute. Imports go at the top of the module (see Global Constraints):

```python
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_pa
```

```python
def _editor_html(client, obj):
    """Seed a unit holding `obj`, GET the real editor page, return its HTML."""
    make_pa(client, "pa")                      # creates + logs in a platform admin
    course = CourseFactory()
    unit = ContentNodeFactory(course=course)   # kind defaults to "unit"
    add_element(unit, obj)                     # Element.objects.create join row
    url = reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}
    )
    response = client.get(url)
    assert response.status_code == 200
    return response.content.decode()


@pytest.mark.django_db
def test_editor_row_shows_the_badge_for_a_dimensionless_geogebra_element(client):
    html = _editor_html(client, IframeElement.objects.create(url=URL, title="P"))
    assert "el-row__flag" in html
    assert "applet size unknown" in html


@pytest.mark.django_db
def test_editor_row_hides_the_badge_once_dimensions_are_known(client):
    html = _editor_html(
        client, IframeElement.objects.create(url=URL, title="P", width=880, height=660)
    )
    # Assert on the BADGE TEXT, not on the class: _element_row.html:29 emits an
    # .el-row__flag for revealgate elements too, so a class-only assertion would fail
    # for an unrelated reason if the seeded unit ever gained one.
    assert "applet size unknown" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_iframe_dimensions.py -k badge -v`
Expected: **exactly one failure** — `test_editor_row_shows_the_badge_for_a_dimensionless_geogebra_element`, with `el-row__flag` absent from the rendered row.

The other two selected tests pass at this point, and neither passing is evidence of anything:

- `test_size_unknown_drives_the_editor_badge` is **already green from Task 7**, where the property was added.
- `test_editor_row_hides_the_badge_once_dimensions_are_known` asserts an **absence** (`"applet size unknown" not in html`), which is trivially true against the unedited template. It cannot fail for the reason this step is about.

That second one is a guard against **over**-rendering, so its red condition is the opposite mutant. After Step 3 lands, falsify it separately: temporarily drop the `{% if obj.size_unknown %}` guard so the badge renders on every iframe row, re-run, confirm this test goes RED while the shows-badge test stays green, then revert. Without that, the branch ships an assertion that has never discriminated — the failure mode Global Constraints exists to prevent.

- [ ] **Step 3: Add the markup**

In `_element_row.html`, between the `.el-tag` span (line 308) and the `.el-actions` span (line 309):

```html
        {% if obj.size_unknown %}<span class="el-row__flag"
              title="{% trans 'The applet size is unknown, so it renders in a 4:3 frame and may be cropped. Paste the <iframe> embed code for exact sizing.' %}">{% trans 'applet size unknown' %}</span>{% endif %}
```

Single quotes inside the attribute, matching lines 305 and 312 of the same file. Both strings are autoescaped (never `|safe`), so the literal `<iframe>` reaches the DOM as `&lt;iframe&gt;` and displays to the author as `<iframe>`.

- [ ] **Step 4: Add the CSS**

`.el-row__flag` has **no rule anywhere in the repo** today — the existing revealgate flag at line 29 ships unstyled. Add after the `.el-tag` rule (editor.css:79):

```css
/* Typography applies to this badge AND the pre-existing revealgate flag, which has
   shipped unstyled. cursor:help is attribute-scoped because that flag has no title and
   would otherwise promise a tooltip that never appears. */
.el-row__flag { font-size: .7rem; color: var(--text-secondary); }
.el-row__flag[title] { cursor: help; }
/* Shrink behaviour is scoped to THIS row only. Giving it to the revealgate flag would
   make a shipped, load-bearing warning truncatable -- a behavioural change to an
   existing surface. `white-space: nowrap` is required for text-overflow to fire at all;
   `min-width: 0` + `flex: 0 1 auto` is what makes a flex text item shrink instead of
   pushing (the escape .el-actions lacked, being a bar of inline-flex forms). */
.el-row__top > .el-row__flag {
  flex: 0 1 auto; min-width: 0;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_iframe_dimensions.py -k badge -v`
Expected: PASS.

- [ ] **Step 6: Update the message catalogs**

```bash
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

Write the Polish translations for both new strings, then **clear any `#, fuzzy` marker** the extractor pre-filled — the repo has a recorded hazard where a fuzzy pre-fill ships a wrong translation and clearing it requires two deletions. Verify:

```bash
grep -c "#, fuzzy" locale/pl/LC_MESSAGES/django.po   # expect 0 — note grep -c EXITS 1
                                                     # when the count is 0, so a
                                                     # "failed" command here is the
                                                     # PASS case. Use the Grep tool if
                                                     # that ambiguity bothers you.
uv run python manage.py compilemessages
```

- [ ] **Step 7: Commit**

```bash
git add templates/courses/manage/editor/_element_row.html courses/static/courses/css/editor.css locale/ tests/test_iframe_dimensions.py
git commit -m "feat(editor): flag GeoGebra elements whose applet size is unknown"
```

---

### Task 9: The 1130px editor-row layout e2e

**Files:**
- Create: `tests/test_e2e_editor_row_layout.py`

**Interfaces:**
- Consumes: the badge markup and CSS (Task 8).
- Produces: nothing.

**Why this is an e2e when the spec otherwise forbids new e2e tests:** the no-e2e non-goal is about the *embed* (which would depend on geogebra.org being reachable). This test drives only our own editor page and touches no external network, so it is explicitly carved out. Viewport overflow cannot be measured any other way — reading the CSS and concluding "it has `min-width: 0`, so it shrinks" is not acceptance evidence.

**Fixture construction:** build both elements **directly via the ORM** (plus their `Element` join rows), so the test depends on neither `IframeElementForm` nor `GEOGEBRA_API_LOOKUP` and can never issue a live GET. The A/B baseline is a **second** `IframeElement` in the same unit with an **identical `title`** and a *usable* pair (so `size_unknown` is False and no badge renders) — same element type keeps `.el-tag` identical, and matching titles keep the two rows byte-identical apart from the badge, so a measured difference has exactly one possible cause.

- [ ] **Step 1: Write the failing test**

`tests/test_e2e_editor.py` has **no conftest login fixture** — it uses module-level helper *functions* and marks every test `@pytest.mark.django_db(transaction=True)`. Import those helpers rather than hand-rolling: without the marker `IframeElement.objects.create` raises "Database access not allowed", and without `_login` the `page.goto` redirects to `/accounts/login/` and every locator silently matches nothing.

**The new module must also define its own `DJANGO_ALLOW_ASYNC_UNSAFE` fixture — importing the helpers does NOT bring it.** `tests/test_e2e_editor.py:20-24` defines

```python
@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield
```

A fixture defined in a test *module* is visible only to that module **regardless of its scope**; `scope="session"` controls how often it runs, not who can see it. All 99 `tests/test_e2e_*.py` modules therefore each carry their own copy. Django's `async_unsafe` decorator reads the env var **at call time**, so without it `IframeElement.objects.create(...)` inside this Playwright sync test raises `SynchronousOnlyOperation` under this task's own Step 3 command (which runs the module alone). In a full `-m e2e -n 2` run it would pass or fail depending on which module the xdist worker happened to reach first — an order-dependent flake rather than a clean failure, which is worse.

```python
import os

import pytest

from courses.models import IframeElement
from tests.factories import add_element
from tests.test_e2e_editor import _editor_url
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # Copied, not imported: a module-level fixture is invisible outside its module.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.django_db(transaction=True)
def test_badge_does_not_grow_the_editor_row_at_the_pane_floor(page, live_server):
    """At 1130px -- the editor pane's floor, the width the existing .el-actions
    overflow was measured at -- adding the badge must not push the action bar onto an
    extra wrapped line or grow the row.

    .el-actions already carries flex-wrap: wrap (editor.css:572), the fix for the
    measured 41px escape, so the badge's cost is VERTICAL rather than horizontal.
    """
    page.set_viewport_size({"width": 1130, "height": 900})
    username = "pa-layout"
    _make_pa_user(username)
    unit = _seed_course_and_unit(username, slug="badge-layout", unit_title="Layout")
    _login(page, live_server, username)

    # Build BOTH elements directly via the ORM -- no form, so no dependence on
    # IframeElementForm or on GEOGEBRA_API_LOOKUP, and no possibility of a live GET.
    # Identical titles and identical element type mean the ONLY difference between the
    # two rows is the badge, so a measured height delta has exactly one possible cause.
    canonical = "https://www.geogebra.org/material/iframe/id/dcjktevj"
    badged = IframeElement.objects.create(url=canonical, title="Identical title")
    control = IframeElement.objects.create(
        url=canonical, title="Identical title", width=880, height=660
    )
    # KEEP THE JOIN ROWS: _element_row.html:302 emits data-element="{{ el.pk }}" where
    # `el` is the Element JOIN row, never the IframeElement. Locating on the concrete
    # pk would match nothing -- or, worse, a DIFFERENT element's row whose join pk
    # happens to collide, silently measuring the wrong two rows.
    badged_join = add_element(unit, badged)
    control_join = add_element(unit, control)

    page.goto(_editor_url(live_server, unit))

    badged_row = page.locator(f"[data-element='{badged_join.pk}'] .el-row__top")
    control_row = page.locator(f"[data-element='{control_join.pk}'] .el-row__top")
    badged_actions = badged_row.locator(".el-actions")
    control_actions = control_row.locator(".el-actions")

    # 1 (load-bearing): the badge changes neither the row height nor the action bar's.
    assert badged_row.bounding_box()["height"] == control_row.bounding_box()["height"]
    assert (
        badged_actions.bounding_box()["height"]
        == control_actions.bounding_box()["height"]
    )
    # Count wrapped lines by distinct child-button top offsets. Do NOT use
    # getClientRects().length on .el-actions -- it is inline-flex AND a flex item, so
    # it is blockified and the count is 1 on a broken build too.
    wrapped_lines = badged_actions.evaluate(
        "el => new Set([...el.children]"
        ".map(c => Math.round(c.getBoundingClientRect().top))).size"
    )
    assert wrapped_lines == control_actions.evaluate(
        "el => new Set([...el.children]"
        ".map(c => Math.round(c.getBoundingClientRect().top))).size"
    )

    # 2 (load-bearing): nothing overflows .el-row__top.
    assert badged_row.evaluate("el => el.scrollWidth <= el.clientWidth")

    # 3 (load-bearing): the direct regression guard on the original 41px escape --
    # the action bar's right edge stays inside the card.
    card = page.locator(f"[data-element='{badged_join.pk}']")
    actions_box, card_box = badged_actions.bounding_box(), card.bounding_box()
    assert (
        actions_box["x"] + actions_box["width"]
        <= card_box["x"] + card_box["width"] + 1
    )

    # 4 (secondary): the badge ellipsised rather than pushed. STRICT '<' -- the loose
    # 'clientWidth <= scrollWidth' holds for every element in every layout by the
    # definition of scrollWidth, i.e. it is a second unfalsifiable assertion, which
    # this plan's Global Constraints forbid. If it turns out the badge does not
    # overflow at 1130px on the real build, DELETE this assertion rather than
    # weakening the operator: a check that cannot discriminate is worse than none.
    badge = badged_row.locator(".el-row__flag")
    assert badge.evaluate("el => el.clientWidth < el.scrollWidth")
```

**Do not** assert that the badge's own box lies inside the card: it renders *before* `.el-actions`, so negative free space is pushed onto the trailing item and the badge's box stays inside even on a build where it refuses to shrink.

- [ ] **Step 2: Run it and confirm it passes on the real build**

Start the test DB first, then:

Run: `uv run pytest tests/test_e2e_editor_row_layout.py -m e2e -v`
(`-m e2e` is mandatory — e2e tests are deselected by default and the run would silently exit 5.)

A green run here establishes nothing on its own; Step 3 is what makes it evidence.

- [ ] **Step 3: Falsify each load-bearing assertion with its OWN mutant**

Three assertions are labelled load-bearing, and **each needs a mutant that drives it red specifically**. A single mutant that reddens assertion 1 says nothing about 2 and 3 — and both are of the shape this repo's history repeatedly flags as unfalsifiable, so "it passed" is exactly the evidence not to trust.

**Apply each mutant from a clean tree and revert fully before the next.** Mutant 2 is *not* applied on top of mutant 1's tree; it is its own edit that happens to include mutant 1's deletion (spelled out below), because the badge must be unshrinkable *before* removing the clipping can make it overflow. Each row states the complete edit.

| # | assertion | complete mutant (from a clean tree) | expected red |
|---|---|---|---|
| 1 | row heights equal | delete `min-width: 0` from `.el-row__top > .el-row__flag`, leaving `white-space: nowrap` — the badge can no longer shrink | assertion 1 |
| 2 | `scrollWidth <= clientWidth` on `.el-row__top` | delete `min-width: 0` **and** `overflow: hidden` **and** `text-overflow: ellipsis` from that same rule — now the unshrinkable badge overflows visibly instead of being clipped | assertion 2; **assertion 1 going red alongside it is expected**, since this mutant is a superset of mutant 1 |
| 3 | action bar's right edge inside the card | from a clean tree, remove `flex-wrap: wrap` from `.el-actions` (editor.css:572) — the fix for the originally-measured 41px escape — so the bar cannot wrap and pushes past the card edge | assertion 3 |

Record each row's actual outcome (red / not red, and at what viewport width) in the PR body.

**If a mutant does not turn its assertion red, that is a real outcome, not a mistake.** `.el-actions` already wraps and "applet size unknown" is short, so at 1130px there may simply be enough slack. In that case do **not** declare that assertion valid — escalate until it discriminates: widen the badge text (e.g. a temporary 80-character label) or narrow the viewport in 50px steps, and **record the width at which it goes red**. If an assertion cannot be made to fail at any plausible width, **delete it** and say so in the PR. An assertion that cannot discriminate is worse than no assertion: it reads as coverage while proving nothing. The same rule already applies to assertion 4, which the test's own comment marks for deletion rather than weakening.

Shipping four green assertions of which only one was ever seen red is the failure mode this branch has already hit six times.

- [ ] **Step 4: Capture screenshots for the PR — including the revealgate row**

Take light and dark screenshots of the badged row at 1130px. Dark mode needs `user.theme`, **not** the cookie. Judge the dark one separately rather than assuming it follows the light one.

**Also screenshot a revealgate element's row.** The `.el-row__flag` typography rule added in Task 8 restyles the pre-existing "inactive in quizzes" flag at `_element_row.html:29`, which has shipped **unstyled** and has no test coverage. Giving it `.7rem` + `--text-secondary` is a visible change to a shipped, load-bearing warning on a surface nothing else in this branch exercises. Seed a revealgate element into the same unit, capture light + dark, and confirm the flag is still legible and still reads as a warning — the shrink properties are scoped away from it (`.el-row__top > .el-row__flag`), so it must NOT have become truncatable.

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_editor_row_layout.py
git commit -m "test(e2e): measure the editor row at the pane floor with the badge present"
```

---

### Task 10: Guard the import-path boundary

**Files:**
- Modify: `tests/test_transfer_import.py` — **resolved, not a discovery task.** That module already imports `IframeElement` (line 21), `build_export` and `write_archive` (lines 32-33), constructs an `IframeElement` at line 169, and holds the full round-trip tests (`test_full_course_round_trip_new_course_shape` at line 259, `test_full_course_round_trip_graph_equality` at 277). It is the right home and Step 4 stages it by name.

Two sibling modules also mention iframes — `tests/test_transfer_validation.py` (which imports `_ser_iframe`/`_val_iframe` directly) and `tests/test_transfer_export.py` — but neither runs an export-then-import round trip, which is the boundary this test must cross. Do not relocate the test to them.

**Interfaces:**
- Consumes: `_open` (Task 5).
- Produces: nothing.

**This test needs the transport seam, not the form seam, or it cannot fail.** The import path is `courses/transfer/payloads.py :: _val_iframe` → `_canonical_embed` → `extract_embed_url` (in `courses/embed.py`); it never touches `courses.element_forms`, so `assert_not_called()` on that module's re-export is true by construction on a correct build **and** on a build that added a lookup inside `extract_embed_url` — exactly the regression the boundary decision exists to prevent. Patching `courses.geogebra.fetch_geogebra_dimensions` does not work either, because the mandated from-import style means a hypothetical `embed.py` consumer would hold its own binding. And patching `_open` under the suite default is vacuous, because `GEOGEBRA_API_LOOKUP=False` short-circuits before the seam.

- [ ] **Step 1: Read the existing round-trip helper you will reuse**

Open `tests/test_transfer_import.py` and read `test_full_course_round_trip_new_course_shape` (line 259) together with the fixture that seeds the source course (the `IframeElement.objects.create` at line 169). Reuse that setup and its `write_archive(source, None, buf)` → import call verbatim — **do not build a new archive by hand**, and do not re-derive the fixture.

If you need to search, use the **`Grep` tool**, not `uv run grep` — Task 1 Step 6 records why (`grep` is not a project entry point, so `uv run` resolves whatever is on PATH, which under PowerShell is nothing).

- [ ] **Step 2: Write the test**

```python
@pytest.mark.django_db
@override_settings(GEOGEBRA_API_LOOKUP=True)
def test_course_import_performs_no_geogebra_lookup(<round-trip fixtures>):
    """extract_embed_url is shared by the authoring form AND course import. The lookup
    lives in the form, deliberately, so imports stay offline -- archives have carried
    width/height since FORMAT_VERSION 2. (A legacy v1 archive carries neither and lands
    on the 4:3 + badge path, which is the intended degraded behaviour, not a gap.)

    Patch the TRANSPORT seam, not the form's re-export. courses.element_forms is never
    touched by the import path, so assert_not_called() there is true by construction --
    including on a build that added a lookup inside extract_embed_url, which is exactly
    the regression this guards. override_settings is required too: under the suite
    default the kill switch short-circuits before _open is ever reached, making the
    assertion vacuous a second way.
    """
    # <copied setup: a course containing an IframeElement with a canonical GeoGebra URL>
    with patch("courses.geogebra._open") as opener:
        # <copied call: export the course, then import the archive>
        pass

    opener.assert_not_called()
```

Substitute the round-trip test's own fixtures and export/import calls for the angle-bracketed parts.

Also add `from unittest.mock import patch` and `from django.test import override_settings` to the module's top import block if they are not already there — both are used above.

- [ ] **Step 3: Run it and falsify it**

Run: `uv run pytest <located module> -k geogebra_lookup -v`
Expected: PASS on the correct build. **Then prove it can fail** — temporarily, inside `courses/embed.py`:

1. add `from courses.geogebra import fetch_geogebra_dimensions` to the existing geogebra import group (today that file imports **only** `canonicalize_geogebra_url`, at line 13 — without this the mutant dies on `NameError`, which is still red but for the wrong reason and therefore demonstrates nothing);
2. add a `fetch_geogebra_dimensions("dcjktevj")` call inside `extract_embed_url`;
3. re-run, confirm RED with `opener.assert_not_called()` failing;
4. revert **both** edits.

A test that has never been seen RED is not evidence — and this one is specifically designed to catch a regression that two more obvious patch targets would silently miss.

- [ ] **Step 4: Commit**

```bash
git add tests/test_transfer_import.py
git commit -m "test(transfer): pin that course import performs no GeoGebra lookup"
```

---

## Final branch gate

- [ ] **Run the affected-test selection, then the full suite once**

```bash
docker compose -f docker-compose.test.yml up -d
uv run python scripts/affected_tests.py          # ~30s targeted selection
uv run pytest -n 2                                # unit suite
uv run pytest -m e2e -n 2                         # e2e suite
```

Never run two pytest invocations at once — the main repo currently has its own branch checked out and a concurrent run will fight over the test database.

- [ ] **Lint and format (format LAST)**

```bash
uv run ruff check .
uv run python manage.py makemigrations --check --dry-run   # expect: no changes
uv run ruff format .
```

`makemigrations --check` must report nothing: this change adds **no** model fields and therefore **no** migration. If it wants one, something was added that should not have been.

- [ ] **Live API acceptance check** (the offline suite cannot detect the API moving)

Run under `config.settings.local` with the flag on, in a **fresh process** so no negative-cache sentinel from an earlier failed attempt short-circuits it:

```bash
uv run python manage.py shell -c "
from django.conf import settings
print('SETTINGS:', settings.SETTINGS_MODULE)              # must NOT be config.settings.test
print('LOOKUP:', settings.GEOGEBRA_API_LOOKUP)            # must be True
from django.core.cache import cache; cache.clear()        # defeat a stale sentinel
from courses.geogebra import fetch_geogebra_dimensions
print('RESULT:', fetch_geogebra_dimensions('dcjktevj'))
"
```

Printing the settings module and the flag first is what makes a `(None, None)` diagnosable instead of a guess: both short-circuits return exactly that, with no request and no log.

Expected: exactly `(880, 660)`. **"It did not raise" is not a pass** — two short-circuits (the sentinel and `GEOGEBRA_API_LOOKUP=False`) both return `(None, None)` with no request, indistinguishable from the API having moved. Record the returned pair in the PR body.

- [ ] **Measure the timeout — the one claim the whole design rests on and nothing else checks**

`_TIMEOUT_SECONDS = 3` is the stated justification for the short timeout, the negative cache and the kill switch: this call sits inside `save_element`'s `@transaction.atomic` + `select_for_update` row lock. Yet every offline test patches `_open`, so the timeout is never exercised — and the plan's own note records that a forgotten `timeout=` kwarg would live *inside* `_open`, **below** the patch point. Such a build passes the entire suite and the live check above, then surfaces as an editor save that hangs for the stdlib default (no timeout at all) while holding a row lock.

Point the lookup at a blackhole address and time it, in a fresh process:

```bash
uv run python manage.py shell -c "
import time
from django.core.cache import cache
import courses.geogebra as gg
cache.clear()
gg._API_PREFIX = 'https://10.255.255.1/'   # RFC5737-style unroutable: connect stalls
t = time.monotonic()
print('RESULT:', gg.fetch_geogebra_dimensions('dcjktevj'))
print('ELAPSED: %.1fs' % (time.monotonic() - t))
"
```

Expected: `(None, None)` in **≈3s**, not ≈2 minutes. Anything much above 3s means the timeout is not reaching the socket — investigate before merging rather than shipping a lock-holding stall. Record the measured elapsed time in the PR body.

(Monkey-patching `_API_PREFIX` here is a throwaway shell mutation, not a code change — the module is reloaded fresh next process. It is also why the defensive `url.startswith(_API_PREFIX)` check stays unreachable in real code.)

- [ ] **Assemble the PR body**

Four artefacts were deliberately collected during execution and are worthless if they stay in the transcript. The PR body must contain all of them:

1. **Task 0** — the census counts you actually measured, or an explicit note that the predicate was *unevaluated* (dev DB unavailable / no mat-pp rows), plus any `'unparseable'` rows.
2. **Task 7** — the malformed-tail accepted-gap conclusion, so a reviewer sees it was chosen rather than missed.
3. **Task 9** — per-mutant outcomes for assertions 1-3 (red / not red, and the viewport width at which each discriminated), which assertions were deleted for failing to discriminate, and the light + dark screenshots **including the revealgate row**.
4. **Final gate** — the live `(880, 660)` result and the measured timeout elapsed time.

- [ ] **Manual acceptance: reproduce the original defect and confirm it is fixed**

Unit 294 renders correctly *today* because its two GeoGebra elements are the static-embed versions — the author replaced the broken share-link element before the census was taken. So do a **fresh** reproduction rather than revisiting it: in a scratch unit, add material `dcjktevj` **by share link** (`https://www.geogebra.org/m/dcjktevj`). Before this change it renders 16:9 with a ~161px right-hand gap; after it, it must be indistinguishable from an element created with the embed code — same viewport, no gap.
