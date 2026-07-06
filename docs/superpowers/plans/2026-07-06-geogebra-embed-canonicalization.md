# GeoGebra Embed Canonicalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite every recognized `https` GeoGebra material URL (share link, classic share, full `<iframe>` embed, minimal URL) into the worksheet-only `https://www.geogebra.org/material/iframe/id/<ID>` form at the embed parse boundary, and backfill existing rows.

**Architecture:** A new pure function `canonicalize_geogebra_url(url)` in `courses/geogebra.py` recognizes GeoGebra material URLs and rebuilds them from scratch (host + material id), passing everything else through unchanged. It is wired into `courses/embed.py :: extract_embed_url` on both success branches (plain-URL and extracted iframe-`src`), just before the existing `validate_embed_url` allow-list gate — so it covers both the authoring form and course import, which share `extract_embed_url`. A one-off data migration reuses the same function to canonicalize already-stored `IframeElement` rows.

**Tech Stack:** Python 3.13, Django, pytest, `uv` for all tooling, `ruff` for lint/format.

## Global Constraints

- **Tooling is `uv`-prefixed:** bash `pytest`/`ruff`/`python` are NOT on PATH. Use `uv run pytest`, `uv run ruff`, `uv run python manage.py`.
- **Before every commit:** run `uv run ruff format` then `uv run ruff check` on the touched files (CI enforces `ruff format --check`).
- **`canonicalize_geogebra_url` never raises.** Any parse failure or missing/malformed id returns the input unchanged; validation stays entirely in `validate_embed_url`. The recognized-host set is hardcoded (`geogebra.org`, `www.geogebra.org`) and independent of `settings.ALLOWED_EMBED_DOMAINS`.
- **Migration 0029 imports `canonicalize_geogebra_url` directly** (single source of truth). Do NOT rename/move/change the signature of that function without updating (or squashing) migration `0029_backfill_geogebra_urls`, or a fresh-DB replay breaks.
- **`courses` migration head is `0028_extend_element_models`** — the new migration depends on it.
- Output URL is ALWAYS `https://www.geogebra.org/material/iframe/id/<ID>` (always `https`, always `www`, always `material/iframe`). Path segments are matched case-sensitively; only the host is lowercased. Only `https` inputs are recognized.

---

### Task 1: `canonicalize_geogebra_url` — the pure canonicalizer

**Files:**
- Create: `courses/geogebra.py`
- Test: `tests/test_geogebra.py`

**Interfaces:**
- Consumes: nothing (stdlib only: `re`, `urllib.parse.urlsplit`).
- Produces: `canonicalize_geogebra_url(url: str) -> str` — returns the canonical worksheet URL for a recognized `https` GeoGebra material URL, else returns `url` unchanged. Never raises.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/test_geogebra.py` with the full behavior matrix from the spec:

```python
import pytest

from courses.geogebra import canonicalize_geogebra_url

CANON = "https://www.geogebra.org/material/iframe/id/egZJdjsC"


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.geogebra.org/m/egZJdjsC",  # share short link
        "https://www.geogebra.org/material/show/id/egZJdjsC",  # classic share
        # full-embed src with the width/height/border cruft tail
        "https://www.geogebra.org/material/iframe/id/egZJdjsC/width/1600/height/763/border/888888/sfsb/true",
        "https://www.geogebra.org/material/iframe/id/egZJdjsC",  # already minimal
        "https://www.geogebra.org/material/iframe/id/egZJdjsC/",  # trailing slash
    ],
)
def test_recognized_forms_canonicalize(raw):
    assert canonicalize_geogebra_url(raw) == CANON


def test_idempotent_on_canonical():
    assert canonicalize_geogebra_url(CANON) == CANON


def test_bare_host_rewritten_to_www():
    assert (
        canonicalize_geogebra_url("https://geogebra.org/m/egZJdjsC")
        == CANON
    )


def test_id_with_dash_and_underscore_accepted():
    assert (
        canonicalize_geogebra_url("https://www.geogebra.org/m/a-b_C9")
        == "https://www.geogebra.org/material/iframe/id/a-b_C9"
    )


@pytest.mark.parametrize(
    "raw",
    [
        "https://beta.geogebra.org/m/egZJdjsC",  # subdomain not recognized
        "http://www.geogebra.org/m/egZJdjsC",  # non-https not recognized
        "//www.geogebra.org/m/egZJdjsC",  # scheme-relative not recognized
        "https://www.example.com/m/egZJdjsC",  # non-geogebra host
        "https://www.geogebra.org/classic/abc",  # app link (no m/, no id segment)
        "https://www.geogebra.org/M/egZJdjsC",  # mixed-case segment not recognized
        "https://www.geogebra.org/m/",  # m is final segment, empty id
        "https://www.geogebra.org/material/iframe/id",  # id final segment, empty id
        "https://www.geogebra.org/m/bad id",  # id fails charset (space)
        "https://www.geogebra.org",  # empty path (IndexError boundary)
        "https://www.geogebra.org/",  # slash-only path
        "https://[::1",  # malformed authority (defensive-parse backstop)
        "",  # empty input
    ],
)
def test_unrecognized_passes_through_unchanged(raw):
    assert canonicalize_geogebra_url(raw) == raw
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_geogebra.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'courses.geogebra'`.

- [ ] **Step 3: Write the implementation**

Create `courses/geogebra.py`:

```python
"""Canonicalize a recognized GeoGebra material URL to the worksheet-only embed URL.

GeoGebra publishes one material under several URL shapes; only
``https://www.geogebra.org/material/iframe/id/<ID>`` renders just the worksheet
(share links and the classic ``/material/show`` form render the full page).

This is the single GeoGebra parser: recognized ``https`` inputs are rebuilt from
scratch (host + material id, dropping any width/height/border cruft), and
everything else is returned unchanged for ``validate_embed_url`` to judge. It
never raises — validation stays entirely in ``validate_embed_url``.
"""

import re
from urllib.parse import urlsplit

# Recognized hosts are hardcoded and intentionally decoupled from
# settings.ALLOWED_EMBED_DOMAINS: this function only *rewrites*, it never
# *accepts* (validate_embed_url remains the sole gate).
_GEOGEBRA_HOSTS = ("geogebra.org", "www.geogebra.org")
# base64url superset of GeoGebra's observed base62 material ids, so a legitimate
# id carrying '-'/'_' is never silently rejected.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_CANONICAL = "https://www.geogebra.org/material/iframe/id/{}"


def _material_id(segments):
    """Return the material id from path segments, or '' if none is extractable.

    Two ordered, bounds-guarded checks (never IndexError):
      (a) first segment == 'm'    -> the segment after it   (share short link)
      (b) a whole segment == 'id' -> the segment after the first such 'id'
    Comparisons are case-sensitive (only the host is lowercased by the caller).
    """
    if segments and segments[0] == "m":
        return segments[1] if len(segments) > 1 else ""
    if "id" in segments:
        i = segments.index("id")
        return segments[i + 1] if len(segments) > i + 1 else ""
    return ""


def canonicalize_geogebra_url(url):
    """Rewrite a recognized https GeoGebra material URL to the worksheet embed URL.

    Anything not recognized — non-https, non-GeoGebra host, a *.geogebra.org
    subdomain, an app link, a missing/malformed id, or any parse failure — is
    returned unchanged.
    """
    try:
        parts = urlsplit(url)
        if parts.scheme != "https":
            return url
        host = (parts.hostname or "").lower()  # .hostname can raise / be None
        if host not in _GEOGEBRA_HOSTS:
            return url
        segments = parts.path.split("/")[1:]  # drop the single leading ''
        candidate = _material_id(segments)
        if _ID_RE.match(candidate):
            return _CANONICAL.format(candidate)
        return url
    except (ValueError, TypeError, IndexError):
        # Backstop: urlsplit/.hostname/.port can raise ValueError on a malformed
        # authority; bounds-guards above already prevent IndexError. Any failure
        # → pass through unchanged (honors the "never raises" contract).
        return url
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_geogebra.py -q`
Expected: PASS (all parametrized cases green).

- [ ] **Step 5: Lint, format, commit**

```bash
uv run ruff format courses/geogebra.py tests/test_geogebra.py
uv run ruff check courses/geogebra.py tests/test_geogebra.py
git add courses/geogebra.py tests/test_geogebra.py
git commit -m "feat(embed): add canonicalize_geogebra_url pure parser"
```

---

### Task 2: Wire canonicalization into `extract_embed_url` and reconcile parse-boundary tests

**Files:**
- Modify: `courses/embed.py` (the plain-URL branch and the iframe-`src` branch of `extract_embed_url`)
- Modify: `tests/test_embed.py` (rename one test + update three expectations + add one end-to-end form test)
- Modify: `tests/test_transfer_validation.py` (update `test_iframe_happy_path_canonicalizes_via_both_validate_calls`)

**Interfaces:**
- Consumes: `canonicalize_geogebra_url` from Task 1; existing `validate_embed_url` from `courses/validators.py`.
- Produces: unchanged public signature `extract_embed_url(raw) -> str`; now returns the canonicalized URL for GeoGebra inputs. `_val_iframe` (course import) inherits the new behavior automatically because it calls `extract_embed_url`.

- [ ] **Step 1: Update the affected existing tests and add the end-to-end test (they will fail first)**

In `tests/test_embed.py`:

1. Rename `test_plain_https_whitelisted_url_passes_through` and change its assertion to expect canonicalization:

```python
def test_geogebra_share_url_is_canonicalized():
    assert (
        extract_embed_url("https://www.geogebra.org/m/abc")
        == "https://www.geogebra.org/material/iframe/id/abc"
    )
```

2. Update `test_valid_snippet_extracts_src` — the `VALID` fixture's `.../id/abc123/width/800/height/600` src now canonicalizes (the cruft tail is dropped):

```python
def test_valid_snippet_extracts_src():
    assert extract_embed_url(VALID) == (
        "https://www.geogebra.org/material/iframe/id/abc123"
    )
```

3. Update `test_iframe_form_stores_only_src` — same fixture, stored URL is now the canonical form:

```python
@pytest.mark.django_db
def test_iframe_form_stores_only_src():
    from courses.element_forms import IframeElementForm

    form = IframeElementForm(data={"url": VALID, "title": "Demo"})
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.url == "https://www.geogebra.org/material/iframe/id/abc123"
```

4. Add a new end-to-end form test at the end of the file:

```python
@pytest.mark.django_db
def test_iframe_form_canonicalizes_share_link():
    from courses.element_forms import IframeElementForm

    form = IframeElementForm(
        data={"url": "https://www.geogebra.org/m/egZJdjsC", "title": "Geo"}
    )
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.url == "https://www.geogebra.org/material/iframe/id/egZJdjsC"
```

5. Add an end-to-end regression guard for spec Goal 2 — a full `<iframe>` for a *different* allow-listed provider must survive `extract_embed_url` unchanged (this confirms canonicalization is GeoGebra-only). Note: this test passes both **before and after** wiring, so it is a guard, not a fail-first TDD test:

```python
def test_non_geogebra_iframe_src_passes_through_unchanged():
    raw = '<iframe src="https://player.vimeo.com/video/123456"></iframe>'
    assert extract_embed_url(raw) == "https://player.vimeo.com/video/123456"
```

In `tests/test_transfer_validation.py`, update the import-path test's final assertion (the URL is now canonicalized on import):

```python
def test_iframe_happy_path_canonicalizes_via_both_validate_calls():
    # geogebra.org is on the default ALLOWED_EMBED_DOMAINS; this exercises
    # extract_embed_url's own validate_embed_url call *and* _canonical_embed's,
    # and now also its GeoGebra canonicalization.
    d = doc_with(
        el_of("iframe", {"url": "https://www.geogebra.org/m/abc", "title": "Demo"})
    )
    validate_document(d, kind="course")
    assert d["elements"][0]["data"]["url"] == (
        "https://www.geogebra.org/material/iframe/id/abc"
    )
```

- [ ] **Step 2: Run the updated tests to verify they fail against the un-wired code**

Run: `uv run pytest tests/test_embed.py tests/test_transfer_validation.py::test_iframe_happy_path_canonicalizes_via_both_validate_calls -q`
Expected: a MIX of pass and fail — the unchanged error-path / blank-input / wrapper-div tests still pass, and so does the new `test_non_geogebra_iframe_src_passes_through_unchanged` guard. The FAILING tests must be exactly these five, which still see the old pass-through URLs (e.g. `https://www.geogebra.org/m/abc` instead of the canonical form): `test_geogebra_share_url_is_canonicalized`, `test_valid_snippet_extracts_src`, `test_iframe_form_stores_only_src`, `test_iframe_form_canonicalizes_share_link` (all in `test_embed.py`), and `test_iframe_happy_path_canonicalizes_via_both_validate_calls` (transfer).

- [ ] **Step 3: Wire `canonicalize_geogebra_url` into `extract_embed_url`**

In `courses/embed.py`, add the import near the top (with the existing `from courses.validators import validate_embed_url`):

```python
from courses.geogebra import canonicalize_geogebra_url
from courses.validators import validate_embed_url
```

Change the **plain-URL branch** from:

```python
    if not text.startswith("<"):
        validate_embed_url(text)  # raises on non-https / non-whitelisted
        return text
```

to:

```python
    if not text.startswith("<"):
        url = canonicalize_geogebra_url(text)
        validate_embed_url(url)  # raises on non-https / non-whitelisted
        return url
```

Change the **iframe-`src` branch** from:

```python
    src = iframes[0].get("src", "").strip()
    if not src:
        raise ValidationError("The pasted <iframe> has no src.")
    validate_embed_url(src)  # https + allow-list; never receives ""
    return src
```

to:

```python
    src = iframes[0].get("src", "").strip()
    if not src:
        raise ValidationError("The pasted <iframe> has no src.")
    url = canonicalize_geogebra_url(src)
    validate_embed_url(url)  # https + allow-list; never receives ""
    return url
```

- [ ] **Step 4: Run the parse-boundary tests to verify they pass**

Run: `uv run pytest tests/test_embed.py tests/test_transfer_validation.py -q`
Expected: PASS — including the unchanged `test_wrapper_div_with_single_iframe_is_valid` (still asserts only the `geogebra.org` prefix) and all error-path tests.

- [ ] **Step 5: Lint, format, commit**

```bash
uv run ruff format courses/embed.py tests/test_embed.py tests/test_transfer_validation.py
uv run ruff check courses/embed.py tests/test_embed.py tests/test_transfer_validation.py
git add courses/embed.py tests/test_embed.py tests/test_transfer_validation.py
git commit -m "feat(embed): canonicalize GeoGebra URLs in extract_embed_url"
```

---

### Task 3: Backfill migration for existing `IframeElement` rows

**Files:**
- Create: `courses/migrations/0029_backfill_geogebra_urls.py`
- Test: `tests/test_geogebra_migration.py`

**Interfaces:**
- Consumes: `canonicalize_geogebra_url` from Task 1 (imported directly into the migration); the historical `IframeElement` model via `apps.get_model`.
- Produces: a data migration `courses.0029_backfill_geogebra_urls` depending on `0028_extend_element_models`, with a reverse no-op.

- [ ] **Step 1: Write the failing migration test**

Create `tests/test_geogebra_migration.py` (mirrors the repo's `tests/test_subject_migrations.py` `MigrationExecutor` pattern):

```python
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

APP = "courses"
BEFORE = "0028_extend_element_models"
AFTER = "0029_backfill_geogebra_urls"


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.migrate([(APP, target)])
    executor.loader.build_graph()
    return executor.loader.project_state([(APP, target)]).apps


def test_backfill_canonicalizes_existing_geogebra_rows():
    old_apps = _migrate(BEFORE)
    Iframe = old_apps.get_model(APP, "IframeElement")
    share = Iframe.objects.create(
        url="https://www.geogebra.org/m/abc", title="share"
    )
    cruft = Iframe.objects.create(
        url="https://www.geogebra.org/material/iframe/id/abc123/width/800/height/600",
        title="cruft",
    )
    canonical = Iframe.objects.create(
        url="https://www.geogebra.org/material/iframe/id/keep", title="canonical"
    )
    other = Iframe.objects.create(
        url="https://player.vimeo.com/video/123", title="other"
    )

    new_apps = _migrate(AFTER)
    NewIframe = new_apps.get_model(APP, "IframeElement")
    assert NewIframe.objects.get(pk=share.pk).url == (
        "https://www.geogebra.org/material/iframe/id/abc"
    )
    assert NewIframe.objects.get(pk=cruft.pk).url == (
        "https://www.geogebra.org/material/iframe/id/abc123"
    )
    assert NewIframe.objects.get(pk=canonical.pk).url == (
        "https://www.geogebra.org/material/iframe/id/keep"
    )
    assert NewIframe.objects.get(pk=other.pk).url == (
        "https://player.vimeo.com/video/123"
    )

    _migrate(AFTER)  # leave the DB migrated forward for the rest of the suite
```

- [ ] **Step 2: Run the migration test to verify it fails**

Run: `uv run pytest tests/test_geogebra_migration.py -q`
Expected: FAIL — the migration `0029_backfill_geogebra_urls` does not exist yet (`MigrationExecutor` cannot find the target node).

- [ ] **Step 3: Write the migration**

Create `courses/migrations/0029_backfill_geogebra_urls.py`:

```python
from django.db import migrations

# Direct import is deliberate — single source of truth. Do NOT rename/move
# canonicalize_geogebra_url without updating (or squashing) this migration,
# or a fresh-DB replay (CI) will break.
from courses.geogebra import canonicalize_geogebra_url


def forwards(apps, schema_editor):
    IframeElement = apps.get_model("courses", "IframeElement")
    for row in IframeElement.objects.all().iterator():
        new_url = canonicalize_geogebra_url(row.url)
        if new_url != row.url:
            row.url = new_url
            row.save(update_fields=["url"])


def backwards(apps, schema_editor):
    # Not reversible (the original share URL is lost); intentional no-op so the
    # migration can still be unapplied.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("courses", "0028_extend_element_models"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
```

- [ ] **Step 4: Run the migration test to verify it passes**

Run: `uv run pytest tests/test_geogebra_migration.py -q`
Expected: PASS — the share and cruft-tail rows are rewritten to their canonical forms; the already-canonical and non-GeoGebra rows are untouched.

- [ ] **Step 5: Confirm no schema drift and migrations are consistent**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected" (this is a data-only migration; no model changed).

- [ ] **Step 6: Lint, format, commit**

```bash
uv run ruff format courses/migrations/0029_backfill_geogebra_urls.py tests/test_geogebra_migration.py
uv run ruff check courses/migrations/0029_backfill_geogebra_urls.py tests/test_geogebra_migration.py
git add courses/migrations/0029_backfill_geogebra_urls.py tests/test_geogebra_migration.py
git commit -m "feat(embed): backfill existing IframeElement rows to canonical GeoGebra URLs"
```

---

## Definition of Done (run after Task 3)

- [ ] Full suite green: `uv run pytest -q`
- [ ] Lint/format clean repo-wide: `uv run ruff format --check .` and `uv run ruff check .`
- [ ] Migrations consistent: `uv run python manage.py makemigrations --check --dry-run` → "No changes detected"
- [ ] Manual smoke (optional but recommended): in the editor, add an Embed/iframe element and paste each of `https://www.geogebra.org/m/egZJdjsC`, the classic `/material/show/id/egZJdjsC`, and the full `<iframe …>` embed code — each stores `https://www.geogebra.org/material/iframe/id/egZJdjsC` and renders just the worksheet in consumption.
