# Add Image From URL — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a course manager paste an image URL in the media manager or the editor's image picker, and have the server fetch it once into a normal `MediaAsset`.

**Architecture:** A new `courses/media_fetch.py` validates the URL against a host allow-list, downloads the bytes on a deadline-bounded daemon thread using the repo's existing `urllib.request` idiom, verifies the payload with Pillow, and hands the result to the **existing** `create_asset()`. Everything downstream — derivatives, validation, the picker, table cells, export — is unchanged. Two small downstream additions: a provenance link on the asset cell, and `replace_asset` clearing that provenance.

**Tech Stack:** Django 5.2, Python 3.13, `urllib.request` (no new dependency), Pillow 12.2, pytest + pytest-django + pytest-playwright, ruff (with bandit `S` rules).

**Spec:** `docs/superpowers/specs/2026-08-21-add-image-from-url-design.md` — read it alongside this plan. Every task below argues from it; where this plan is terse, the spec has the reasoning.

## Global Constraints

- **No new dependency.** `pyproject.toml` is not modified. Use `urllib.request`, not `requests`.
- **Only one new module:** `courses/media_fetch.py`. `courses/geogebra.py` and `integrations/delivery.py` are never edited.
- **No `FORMAT_VERSION` bump.** It stays at 13. Neither `source_url` nor `content_hash` is exported.
- **Migration `0061_mediaasset_source_url`**, depending on `("courses", "0060_calloutelement_numbered")` — the current graph head. Verify the head is still `0060` before generating; if master moved, re-point.
- **All new user-facing strings are translated:** `{% trans %}` in templates, `gettext_lazy` in Python. Worker-thread errors use `ValidationError(msg, code=..., params={...})` — **never** `%`-format on the worker (gettext is thread-local).
- **Every test must be falsified against a named mutant** that proves it goes RED. Pick the mutant from the failure mode the test claims to detect. A test that passes on the broken build proves nothing.
- **Ruff:** `select = ["E","F","I","UP","B","S"]`, `force-single-line` imports. `S310` needs `# noqa: S310` on the `Request(...)` line **plus** a justification comment above it — and that comment must not *begin* with the directive text (ruff would parse it as a second suppression).
- **88-column limit** (`E501`, active via `select = ["E"]`). No production file in this repo exceeds it. Note that `ruff format` normalises inline-comment spacing but will **not** split a line whose overflow comes from a trailing comment — several snippets in this plan carry explanatory trailing comments that push past 88; move those comments onto their own line as you type them in.
- **Run `uv run ruff format .` LAST**, after every other edit; `ruff format --check` is a separate CI gate.

- **Every new test module that writes bytes needs its own `MEDIA_ROOT` redirect.**
  `MEDIA_ROOT = BASE_DIR / "media"` and the root `conftest.py` has **no** autouse
  isolation (it carries only `_reset_active_language`), so `create_asset` /
  `fetch_image_asset` write the original *plus* `thumb`/`web` derivatives straight into
  the working tree. Every sibling module that writes bytes redirects explicitly
  (`tests/conftest.py:379-395`, `test_e2e_image_size.py:58`,
  `test_e2e_media_manager.py:41`). Add this to **Tasks 3, 4, 6, 7, 13 and 14**:

  ```python
  @pytest.fixture(autouse=True)
  def _isolated_media(settings, tmp_path):
      settings.MEDIA_ROOT = str(tmp_path)
      return tmp_path
  ```

  Task 5 inherits it through the shared helpers only if its module defines it too — so
  add it there as well.

### Test-run mechanics (this repo, this worktree)

- `uv` is not on PATH; invoke as `uv run pytest ...` from the worktree root.
- **Start the test-DB container first** or the suite looks hung for ~4m21s.
- **This worktree shares a machine with other active worktrees.** Isolate the test DB by prefixing the command — never by editing `.env`:
  ```
  TEST_DATABASE_URL="postgres://libli@127.0.0.1:55433/libli_aifu" uv run pytest <paths>
  ```
- **Never run two pytest processes at once**; killing a competing run poisons the survivor with phantom `SystemExit: 2`.
- e2e needs `-m e2e` or every e2e test is silently deselected (exit 5).
- **pytest's exit code can be 0 while tests failed** — grep the summary line, don't trust `$?`.
- Scope runs to the affected tests. A whole-repo sweep is a branch-level gate (Task 13), never a per-task step.

---

## File Structure

| File | Responsibility |
|---|---|
| `courses/media_fetch.py` *(new)* | The fetch service: transport seam, deadline thread, redirect/status/content-type/cap rules, payload verification, filename derivation |
| `courses/validators.py` | `validate_fetch_url` — returns the stripped URL |
| `config/settings/base.py` | `ALLOWED_IMAGE_FETCH_DOMAINS`, `ALLOW_HTTP_IMAGE_FETCH` |
| `config/settings/test.py` | Replaces both for the suite |
| `.env.example` | Documents both, with the subdomain-trust warning |
| `courses/models.py` | `MediaAsset.source_url` + `source_host` property |
| `courses/migrations/0061_mediaasset_source_url.py` *(new)* | The field |
| `courses/media.py` | `create_asset` kwargs; `replace_asset` clears `source_url` |
| `courses/views_media.py` | `media_fetch` view |
| `courses/urls.py` | `manage_media_fetch` route |
| `templates/courses/manage/media/{manager,_picker,_asset_cell}.html` | The two entry points and the provenance link |
| `courses/static/courses/css/editor.css` | `.media-fetch`, picker panel, `.asset-source` |
| `courses/static/courses/js/media_picker.js` | `fetchPickerUrl`, manager submit listener, in-flight flag |
| `locale/{pl,en}/LC_MESSAGES/django.po` | Translations |
| `courses/tests/`, `tests/` | Unit, view, template, e2e |

---

### Task 1: Settings + `validate_fetch_url`

**Files:**
- Modify: `config/settings/base.py` (after `ALLOWED_EMBED_DOMAINS`, ~`:187`)
- Modify: `config/settings/test.py`
- Modify: `.env.example` (beside `:21`)
- Modify: `courses/validators.py` (after `validate_embed_url`, ~`:126`)
- Test: `courses/tests/test_fetch_url_validator.py` *(new)*

**Interfaces:**
- Consumes: nothing.
- Produces: `validate_fetch_url(url: str) -> str` — raises `ValidationError`, else **returns the stripped URL**. Settings `ALLOWED_IMAGE_FETCH_DOMAINS: list[str]`, `ALLOW_HTTP_IMAGE_FETCH: bool`.

- [ ] **Step 1: Write the failing tests**

```python
# courses/tests/test_fetch_url_validator.py
import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from courses.validators import validate_fetch_url

OK = ["upload.wikimedia.org"]


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
@pytest.mark.parametrize(
    "url,fragment",
    [
        ("", "Enter an image URL"),
        ("   \n ", "Enter an image URL"),
        ("https://upload.wikimedia.org/" + "a" * 500, "too long"),
        ("https://", "valid URL"),
        ("http://upload.wikimedia.org/x.png", "https"),
        ("https://evil.com/x.png", "allow-list"),
        # The host that DISTINGUISHES the mutant: "notupload.wikimedia.org" DOES
        # endswith("upload.wikimedia.org"), so endswith(d) accepts it while the
        # correct endswith("." + d) rejects it. MEASURED.
        ("https://notupload.wikimedia.org/x.png", "allow-list"),
        # A suffix case that both forms reject (endswith(d) is False here) -- kept
        # for coverage, but it does NOT falsify the mutant on its own.
        ("https://notupload.wikimedia.org.evil.com/x.png", "allow-list"),
    ],
)
def test_rejections(url, fragment):
    with pytest.raises(ValidationError) as exc:
        validate_fetch_url(url)
    assert fragment in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
@pytest.mark.parametrize(
    "url",
    [
        "https://upload.wikimedia.org/x.png",          # exact host
        "https://sub.upload.wikimedia.org/x.png",      # subdomain
    ],
)
def test_accepts(url):
    assert validate_fetch_url(url) == url


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=["Upload.Wikimedia.ORG"], ALLOW_HTTP_IMAGE_FETCH=False)
def test_allow_list_entry_is_case_folded():
    url = "https://upload.wikimedia.org/x.png"
    assert validate_fetch_url(url) == url


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_returns_stripped_value():
    assert validate_fetch_url("  https://upload.wikimedia.org/x.png\n") == (
        "https://upload.wikimedia.org/x.png"
    )


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=["localhost"], ALLOW_HTTP_IMAGE_FETCH=True)
def test_http_allowed_when_flag_on():
    url = "http://localhost:8000/x.png"
    assert validate_fetch_url(url) == url
```

- [ ] **Step 2: Run to verify it fails**

Run: `TEST_DATABASE_URL="postgres://libli@127.0.0.1:55433/libli_aifu" uv run pytest courses/tests/test_fetch_url_validator.py -q`
Expected: FAIL — `ImportError: cannot import name 'validate_fetch_url'`

- [ ] **Step 3: Add the settings**

In `config/settings/base.py`, immediately after the `ALLOWED_EMBED_DOMAINS` block:

```python
# Hosts this server will CONNECT TO to fetch an image. Deliberately separate from
# ALLOWED_EMBED_DOMAINS: that list authorises what a browser may load in an iframe,
# this one authorises server-side egress, and conflating them would silently widen
# a privilege. NOTE: the allow-list is the ONLY SSRF defence -- there is no IP-range
# check behind it, and the match accepts every subdomain, so each entry must be a
# host whose ENTIRE subdomain tree is trusted (never s3.amazonaws.com, github.io, a
# shared CDN, ...).
ALLOWED_IMAGE_FETCH_DOMAINS = env.list(
    "LIBLI_ALLOWED_IMAGE_FETCH_DOMAINS",
    default=["upload.wikimedia.org", "commons.wikimedia.org"],
)
# Test-only escape hatch: pytest-django's live_server speaks plain http, so an
# https-only rule would make a real end-to-end fetch test impossible. Default OFF,
# and that default is itself asserted by a test.
ALLOW_HTTP_IMAGE_FETCH = env.bool("LIBLI_ALLOW_HTTP_IMAGE_FETCH", default=False)
```

In `config/settings/test.py`, beside `GEOGEBRA_API_LOOKUP = False`:

```python
# REPLACES the production list rather than extending it -- with the Wikimedia hosts
# still present, a unit test whose transport mock failed to intercept could reach the
# real network. Both spellings: pytest-django resolves live_server to "localhost" by
# default, and 127.0.0.1 is listed so a --liveserver override does not break the e2e.
ALLOWED_IMAGE_FETCH_DOMAINS = ["localhost", "127.0.0.1"]
ALLOW_HTTP_IMAGE_FETCH = True
```

In `.env.example`, beside line 21:

```
# Hosts the server may FETCH images from. Each entry must be a host whose entire
# subdomain tree is trusted -- the allow-list is the only SSRF defence.
# LIBLI_ALLOWED_IMAGE_FETCH_DOMAINS=upload.wikimedia.org,commons.wikimedia.org
# LIBLI_ALLOW_HTTP_IMAGE_FETCH=false
```

- [ ] **Step 4: Write `validate_fetch_url`**

In `courses/validators.py`, after `validate_embed_url`:

```python
MAX_FETCH_URL_LENGTH = 500  # matches MediaAsset.source_url's max_length


def validate_fetch_url(url):
    """Guard for server-side image fetches. Returns the STRIPPED url.

    Twin of validate_embed_url, with three differences: it strips, it length-caps
    (source_url is a 500-char column), and it runs URLValidator. Callers MUST use the
    return value -- a bare call whose result is discarded leaves the caller's url
    unstripped, stores "\\nhttps://..." in source_url, and still passes every other
    test in the suite, because they all use clean urls.
    """
    url = (url or "").strip()
    if not url:
        raise ValidationError(_("Enter an image URL."), code="empty")
    if len(url) > MAX_FETCH_URL_LENGTH:
        # Literal 500, matching the spec's pinned error text exactly -- the spec's
        # error table is the single source for the implementation, the view tests AND
        # the .po entries, so parameterising it here would fork the msgid.
        raise ValidationError(
            _("That URL is too long (maximum 500 characters)."), code="too-long"
        )
    try:
        URLValidator()(url)
    except ValidationError as exc:
        raise ValidationError(
            _("That does not look like a valid URL."), code="malformed"
        ) from exc
    parts = urlsplit(url)
    allowed_schemes = {"https", "http"} if settings.ALLOW_HTTP_IMAGE_FETCH else {"https"}
    if parts.scheme not in allowed_schemes:
        raise ValidationError(_("Image URLs must use https."), code="scheme")
    host = (parts.hostname or "").lower()
    allowed = {d.lower() for d in settings.ALLOWED_IMAGE_FETCH_DOMAINS}
    if not any(host == d or host.endswith("." + d) for d in allowed):
        raise ValidationError(
            _("That image host is not on the allow-list."), code="host"
        )
    return url
```

Add `from django.core.validators import URLValidator` to the imports (single-line style).

- [ ] **Step 5: Run to verify it passes**

Run: same command as Step 2. Expected: PASS.

- [ ] **Step 6: Falsify — run each mutant, confirm RED, revert by hand**

⚠️ Do **not** revert with `git checkout` — edit the mutant out by hand, or you destroy the task's work.

| Mutant | Test that must go RED |
|---|---|
| Drop `url = (url or "").strip()` | `test_returns_stripped_value` and the `"   
 "` row only — the `""` row still passes, since `if not url` fires on it either way |
| `return None` instead of `return url` | `test_accepts`, `test_returns_stripped_value` |
| Drop `.lower()` on the allow-list set | `test_allow_list_entry_is_case_folded` |
| Change `host.endswith("." + d)` to `host.endswith(d)` | the **`notupload.wikimedia.org`** row (the `.evil.com` row stays GREEN on this mutant — `endswith(d)` is False for it) |

- [ ] **Step 7: Add the settings-default test**

```python
# courses/tests/test_fetch_url_validator.py (append)
def test_base_settings_default_allow_http_is_false(monkeypatch):
    """The escape hatch's default-off state is a tested property.

    Must be environment-independent, and a naive reload is NOT: base.py calls
    env.read_env() at module scope and django-environ writes with
    os.environ.setdefault, so reloading re-inserts any .env value before env.bool()
    runs -- and monkeypatch.delenv(raising=False) records nothing to undo when the
    var was absent, leaking that insertion into every later test in the process.
    So: suppress the .env read too, and restore os.environ.
    """
    import importlib
    import os

    import environ

    monkeypatch.delenv("LIBLI_ALLOW_HTTP_IMAGE_FETCH", raising=False)
    monkeypatch.setattr(environ.Env, "read_env", staticmethod(lambda *a, **k: None))
    saved = dict(os.environ)
    try:
        base = importlib.import_module("config.settings.base")
        base = importlib.reload(base)
        assert base.ALLOW_HTTP_IMAGE_FETCH is False
    finally:
        os.environ.clear()
        os.environ.update(saved)
        # Deliberately NO second reload here: it would run while read_env is still
        # monkeypatched (undo happens at teardown, after this body), leaving `base`
        # cached WITHOUT its .env values. django.conf.settings is unaffected either
        # way, so restoring os.environ is the whole job.
```

- [ ] **Step 8: Run, falsify, commit**

Mutant: change the `env.bool` default to `True` → the test goes RED.

```bash
git add courses/tests/test_fetch_url_validator.py courses/validators.py config/settings/base.py config/settings/test.py .env.example
git commit -m "feat(media-fetch): allow-list validator and settings for image URL fetch"
```

---

### Task 2: `MediaAsset.source_url` + `source_host` + migration

**Files:**
- Modify: `courses/models.py` (`MediaAsset`, after `name`)
- Create: `courses/migrations/0061_mediaasset_source_url.py`
- Test: `courses/tests/test_media_source_url.py` *(new)*

**Interfaces:**
- Consumes: nothing.
- Produces: `MediaAsset.source_url: str` (blank default `""`), `MediaAsset.source_host: str` property.

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_media_source_url.py
import pytest

from courses.models import MediaAsset

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://upload.wikimedia.org/a/b.png", "upload.wikimedia.org"),
        ("", ""),
        ("https://[bad-ipv6/x.png", ""),   # malformed authority -> "" not a raise
    ],
)
def test_source_host(url, expected):
    assert MediaAsset(source_url=url).source_host == expected
```

- [ ] **Step 2: Run to verify it fails**

Run: `TEST_DATABASE_URL="postgres://libli@127.0.0.1:55433/libli_aifu" uv run pytest courses/tests/test_media_source_url.py -q`
Expected: FAIL — `TypeError: 'source_url' is an invalid keyword argument`

- [ ] **Step 3: Add the field and property**

In `courses/models.py`, inside `MediaAsset`, after `name`:

```python
    # Provenance for an asset fetched from a URL; blank for every upload. LOCAL
    # metadata, deliberately NOT exported -- the transfer manifest's media entry is
    # _exact_keys-validated and both this and content_hash describe how THIS instance
    # obtained the bytes, which is meaningless in an instance that received them in an
    # archive. max_length 500 matches validators.MAX_FETCH_URL_LENGTH.
    source_url = models.URLField(max_length=500, blank=True, default="")
```

And the property (near `display_name`):

```python
    @property
    def source_host(self):
        """Hostname of source_url, or "" -- never raises.

        urlsplit().hostname raises ValueError on a malformed authority (a bracketed
        IPv6 remnant, an out-of-range port), and this runs for EVERY cell in the
        manager grid, so one bad row would 500 the whole page. Same guard
        geogebra_material_id uses.
        """
        try:
            return urlsplit(self.source_url).hostname or ""
        except ValueError:
            return ""
```

Add `from urllib.parse import urlsplit` to `courses/models.py` imports if absent.

- [ ] **Step 4: Generate the migration**

```bash
uv run python manage.py makemigrations courses --name mediaasset_source_url
```

Open the generated file and **verify** `dependencies = [("courses", "0060_calloutelement_numbered")]`. If master moved and the head is no longer `0060`, re-point it — a migration that does not target the graph head will not apply.

- [ ] **Step 5: Run to verify it passes**

Run: same as Step 2. Expected: PASS.

- [ ] **Step 6: Falsify**

Mutant: change `except ValueError: return ""` to `raise` → the malformed-authority case goes RED.

- [ ] **Step 7: Confirm no migration is missing**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected" (CI runs this gate).

- [ ] **Step 8: Commit**

```bash
git add courses/models.py courses/migrations/0061_mediaasset_source_url.py courses/tests/test_media_source_url.py
git commit -m "feat(media): MediaAsset.source_url + source_host property"
```

---

### Task 3: `create_asset` kwargs + `replace_asset` clears provenance

**Files:**
- Modify: `courses/media.py` (`create_asset` `:108`, `replace_asset` `:197`/`:208`)
- Test: `courses/tests/test_media_source_url.py` (append)

**Interfaces:**
- Consumes: `MediaAsset.source_url` (Task 2).
- Produces: `create_asset(course, kind, uploaded_file, user, name="", generate=True, source_url="", content_hash="")`.

- [ ] **Step 1: Write the failing tests**

⚠️ **Merge these imports into the file's existing top-of-file block** — do not append them
mid-file. Module-level imports after the first `def` trip `E402` (in the selected `E` set)
and `I001` (unsorted, in `I`); the `**/tests/**` per-file-ignores cover only `S105/S106/S107`.
The failure would surface in Task 14's branch-wide `ruff check`, far from its cause. The repo
uses `force-single-line`, so each `from … import …` gets its own line.

```python
# courses/tests/test_media_source_url.py -- ADD to the existing import block at the top
import hashlib

from django.core.files.base import ContentFile

from courses import media as media_svc
from tests.factories import CourseFactory
from tests.factories import UserFactory


def _png_bytes():
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, format="PNG")
    return buf.getvalue()


def test_create_asset_persists_provenance_and_hash():
    data = _png_bytes()
    digest = hashlib.sha256(data).hexdigest()
    asset = media_svc.create_asset(
        CourseFactory(),
        "image",
        ContentFile(data, name="x.png"),
        UserFactory(),
        source_url="https://upload.wikimedia.org/x.png",
        content_hash=digest,
    )
    asset.refresh_from_db()
    assert asset.source_url == "https://upload.wikimedia.org/x.png"
    assert asset.content_hash == digest


def test_create_asset_defaults_leave_both_blank():
    asset = media_svc.create_asset(
        CourseFactory(), "image", ContentFile(_png_bytes(), name="x.png"), UserFactory()
    )
    assert asset.source_url == ""
    assert asset.content_hash == ""


def test_replace_asset_clears_source_url():
    asset = media_svc.create_asset(
        CourseFactory(),
        "image",
        ContentFile(_png_bytes(), name="x.png"),
        UserFactory(),
        source_url="https://upload.wikimedia.org/x.png",
        content_hash="deadbeef",
    )
    media_svc.replace_asset(asset, ContentFile(_png_bytes(), name="y.png"))
    asset.refresh_from_db()
    assert asset.source_url == ""
    assert asset.content_hash == ""
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL — `create_asset() got an unexpected keyword argument 'source_url'`

- [ ] **Step 3: Implement**

`create_asset` — add the two kwargs and set them **before** `full_clean()` so the single existing validation authority covers them:

```python
def create_asset(
    course, kind, uploaded_file, user, name="", generate=True,
    source_url="", content_hash="",
):
    ...
    asset = MediaAsset(
        course=course,
        kind=kind,
        file=uploaded_file,
        original_filename=truncate_filename(uploaded_file.name),
        name=(name or "").strip()[:255],
        uploaded_by=user,
        # Set BEFORE full_clean() so the model stays the single validation authority.
        # Both default to "" so every existing caller -- including the transfer
        # importer's generate=False path -- behaves exactly as before.
        source_url=source_url,
        content_hash=content_hash,
    )
    asset.full_clean()
    ...
```

`replace_asset` — beside the existing `content_hash` line:

```python
    asset.content_hash = ""  # a STALE hash would mis-dedup a later LAL import
    # Same class of defect, one step worse: the cell's source link would actively
    # assert a provenance that no longer describes the stored bytes.
    asset.source_url = ""
```

and extend its `update_fields`:

```python
    asset.save(update_fields=["file", "original_filename", "content_hash", "source_url"])
```

- [ ] **Step 4: Run to verify it passes.** Expected: PASS.

- [ ] **Step 5: Falsify**

| Mutant | RED test |
|---|---|
| Drop `source_url` from `replace_asset`'s `update_fields` | `test_replace_asset_clears_source_url` |
| Move the two kwargs to *after* `full_clean()` | (no test — instead verify by hand that an over-long `source_url` is rejected) |

- [ ] **Step 6: Run the existing media suite for regressions**

Run: `TEST_DATABASE_URL="postgres://libli@127.0.0.1:55433/libli_aifu" uv run pytest tests/test_media_model.py tests/test_media_manager.py courses/tests/test_media_source_url.py -q`
Expected: all pass. Grep the summary line — do not trust the exit code.

- [ ] **Step 7: Commit**

```bash
git add courses/media.py courses/tests/test_media_source_url.py
git commit -m "feat(media): create_asset provenance kwargs; replace_asset clears them"
```

---

### Task 4: `media_fetch.py` — transport seam, deadline thread, happy path

**Files:**
- Create: `courses/media_fetch.py`
- Test: `courses/tests/test_media_fetch_transport.py` *(new)*

**Interfaces:**
- Consumes: `validate_fetch_url` (T1), `create_asset` kwargs (T3).
- Produces: `fetch_image_asset(course, submitted_url, user, name="") -> MediaAsset`; module globals `MAX_REDIRECT_HOPS`, `TIMEOUT_SECONDS`, `DEADLINE_SECONDS`, `CHUNK_BYTES`, `MAX_PIXELS`, `REDIRECT_STATUSES`; the patchable seam `_open(request, timeout)`; `_BudgetExceeded`.

This task builds the skeleton end-to-end for the simplest case (200, no redirects, PNG, known filename) so it is independently testable. Tasks 5–7 add the rule layers.

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_media_fetch_transport.py
import io
import threading

import pytest
from django.test import override_settings

from courses import media_fetch
from courses.models import DerivativesState
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

OK = ["upload.wikimedia.org"]
URL = "https://upload.wikimedia.org/Foo.png"


def png_bytes():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "blue").save(buf, format="PNG")
    return buf.getvalue()


class FakeResponse(io.BytesIO):
    """Stands in for an http.client.HTTPResponse.

    NOTE read1 is inherited from BytesIO and returns partial data, which is what the
    production loop calls. Do NOT replace this with a generator-based double: a
    generator yields instantly and would pass on a build that uses read() instead of
    read1(), which is the exact defect the drip tests exist to catch.
    """

    def __init__(self, data=b"", status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {"Content-Type": "image/png"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_happy_path_creates_a_normal_asset(monkeypatch):
    data = png_bytes()
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: FakeResponse(data))
    asset = media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert asset.kind == "image"
    assert asset.source_url == URL
    assert asset.content_hash  # populated
    assert asset.file.size == len(data)
    # The spec's "a normal MediaAsset with derivatives generated" -- without this a
    # mutant passing generate=False to create_asset is invisible, and the whole
    # "the asset pipeline needs no change" premise rests on derivatives running.
    assert asset.derivatives_state == DerivativesState.OK
    assert asset.thumb and asset.width


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_create_asset_runs_on_the_request_thread(monkeypatch):
    """The worker does steps 4-8 only; create_asset must NOT run on it.

    Asserting via a "django_db-visible write" would be an assertion that CANNOT
    FAIL: a background thread opens its own connection and really commits, so this
    connection sees the row anyway -- and that row survives the rollback and leaks
    into the next test. Record the thread instead.
    """
    seen = {}
    real = media_fetch.create_asset

    def spy(*a, **kw):
        seen["thread"] = threading.current_thread()
        return real(*a, **kw)

    monkeypatch.setattr(media_fetch, "create_asset", spy)
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: FakeResponse(png_bytes()))
    media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert seen["thread"] is threading.current_thread()


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_a_padded_url_is_stored_stripped(monkeypatch):
    """The spec's weakest-natural-coverage invariant, called out twice there.

    validate_fetch_url RETURNS the stripped url and step 1 must ASSIGN it. Every other
    test in this suite passes an already-clean url, so the bare-call mutant -- dropping
    the assignment -- stays GREEN across the whole suite except here. T1 does NOT cover
    this: it tests the validator's return value, not that fetch_image_asset uses it.
    """
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: FakeResponse(png_bytes()))
    asset = media_fetch.fetch_image_asset(
        CourseFactory(), "  " + URL + "\n", UserFactory()
    )
    assert asset.source_url == URL          # no leading/trailing whitespace


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_user_agent_and_accept_are_sent(monkeypatch):
    captured = {}

    def fake_open(req, timeout):
        captured["ua"] = req.get_header("User-agent")
        captured["accept"] = req.get_header("Accept")
        return FakeResponse(png_bytes())

    monkeypatch.setattr(media_fetch, "_open", fake_open)
    media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "libli" in captured["ua"]
    assert captured["accept"] == "image/*"
```

- [ ] **Step 2: Run to verify it fails.** Expected: `ModuleNotFoundError: courses.media_fetch`.

- [ ] **Step 3: Write the module skeleton**

```python
# courses/media_fetch.py
"""Fetch a remote image into a MediaAsset.

Transport is urllib.request, NOT requests -- matching courses/geogebra.py and
integrations/delivery.py, the repo's two existing outbound callers. That choice is
not stylistic: geogebra.py has already measured and documented the two lessons this
module needs (a socket timeout does not bound a call; read1 not read), and requests
would force both to be re-learned in a second dialect.

The worker's boundary rule, copied from geogebra.py: NO ORM, NO cache, NO LOGGING --
it only calls _open, reads bytes, and stores into a result box. create_asset and
everything else stays on the request thread.
"""

import hashlib
import logging
import threading
import urllib.error
import urllib.request
from io import BytesIO
from time import monotonic
from urllib.parse import unquote
from urllib.parse import urljoin
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.translation import gettext_lazy as _

from courses.geogebra import _USER_AGENT
from courses.media import create_asset
from courses.media import truncate_filename
from courses.validators import effective_image_extensions
from courses.validators import effective_max_image_bytes
from courses.validators import validate_fetch_url

logger = logging.getLogger(__name__)

# Params whose value adds nothing beyond the already-rendered message. NOTE `status`
# is interpolated into its message too but is deliberately NOT here: the log line
# carries no other field that identifies which status fired.
_MESSAGE_ONLY_PARAMS = {"mib"}

MAX_REDIRECT_HOPS = 3
TIMEOUT_SECONDS = 8          # per socket op -- does NOT bound the call
DEADLINE_SECONDS = 20        # total wall clock; the thread join is what enforces it
CHUNK_BYTES = 64 * 1024
MAX_PIXELS = 50_000_000
REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# Every constant above is read as a MODULE GLOBAL at call time -- never captured as a
# default argument and never re-exported -- so the deadline tests can monkeypatch them
# down. Both alternatives bind at import and would silently make those tests run for
# the full 20s or pass without exercising the path.


class _BudgetExceeded(Exception):
    """The worker's deadline ran out. Stores nothing, so the caller's empty-box
    branch reports the deadline. Its except clause MUST precede the broad one."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse automatic redirects so each hop can be re-validated.

    Duplicated from geogebra.py/delivery.py rather than imported, for the reason
    geogebra.py documents. Body copied verbatim -- it RAISES, it does not return None.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


def _open(request, timeout):
    """The transport seam. Patched by tests; the only place the network is touched."""
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)


def _build_request(url):
    # The scheme is constrained to http/https by validate_fetch_url before this runs,
    # and _NoRedirect stops the opener following one elsewhere. (This comment must not
    # BEGIN with the directive text -- ruff would read that as a second suppression.)
    return urllib.request.Request(  # noqa: S310
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "image/*"},
    )


def _remaining(deadline):
    left = deadline - monotonic()
    if left <= 0:
        raise _BudgetExceeded
    return left


def _fetch(submitted_url, deadline, max_bytes):
    """Worker body: steps 4-8. Returns (data, current_url). Raises only."""
    current_url = submitted_url
    with _open(_build_request(current_url), min(TIMEOUT_SECONDS, _remaining(deadline))) as resp:
        data = _read_capped(resp, deadline, max_bytes)
    return data, current_url


def _read_capped(resp, deadline, max_bytes):
    chunks, total = [], 0
    while True:
        _remaining(deadline)          # checked once per chunk
        chunk = resp.read1(CHUNK_BYTES)   # read1, NOT read -- see module docstring
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:         # one chunk past the cap keeps oversize detectable
            raise ValidationError(
                _("Image file too large (max %(mib)d MiB)."),
                code="too-large",
                params={"mib": max_bytes // (1024 * 1024)},
            )
    return b"".join(chunks)


def fetch_image_asset(course, submitted_url, user, name=""):
    submitted_url = validate_fetch_url(submitted_url)   # ASSIGNMENT, not a bare call
    max_bytes = effective_max_image_bytes()             # read ONCE, not per chunk
    allowed_exts = effective_image_extensions()

    box = {}
    deadline = monotonic() + DEADLINE_SECONDS   # computed immediately before start()

    def _run():
        try:
            box["result"] = _fetch(submitted_url, deadline, max_bytes)
        except _BudgetExceeded:
            pass                                  # stores nothing -> deadline branch
        except BaseException as exc:              # noqa: BLE001 - re-raised on the joiner
            box["exc"] = exc                      # store FIRST
            try:
                exc.close()                       # HTTPError only; harmless otherwise
            except Exception:                     # noqa: BLE001, S110
                pass

    thread = threading.Thread(target=_run, name="image-fetch", daemon=True)
    thread.start()
    thread.join(DEADLINE_SECONDS)                 # same value as the deadline

    result = dict(box)                            # ONE snapshot of a live dict
    if "exc" in result:
        _log_worker_failure(submitted_url, result["exc"])
        raise result["exc"]                       # unchanged, whatever its type
    if "result" not in result:
        logger.warning("image fetch: host=%s reason=deadline", urlsplit(submitted_url).hostname)
        raise ValidationError(_("Fetching the image took too long."), code="deadline")

    data, current_url = result["result"]
    return _build_asset(course, user, name, submitted_url, current_url, data, allowed_exts)


def _log_worker_failure(submitted_url, exc):
    """Log once, HERE on the request thread -- the worker must not log.

    Reads BOTH the token and the params defensively: the box may hold a
    non-ValidationError (a genuine worker bug, re-raised as a 500) or a
    ValidationError carrying an error_list/error_dict, which has neither attribute.
    A bare exc.code -- or a bare exc.params -- would raise INSIDE this call and turn
    an intended clean 500 into a different, misleading one.
    """
    if not isinstance(exc, ValidationError):
        return
    code = getattr(exc, "code", None)
    params = getattr(exc, "params", None) or {}
    logger.warning(
        "image fetch: host=%s reason=%s %s",
        urlsplit(submitted_url).hostname,
        code,
        # Omit keys already rendered in the author-facing message (they are not
        # extra diagnostics); keep the rest -- status, target_host, content_type, exc.
        {k: v for k, v in params.items() if k not in _MESSAGE_ONLY_PARAMS},
    )


def _build_asset(course, user, name, submitted_url, current_url, data, allowed_exts):
    """Steps 9-13, on the request thread."""
    filename = "image.png"   # replaced in Task 7
    digest = hashlib.sha256(data).hexdigest()   # EXACTLY lal_loader/media.py:33's form
    return create_asset(
        course,
        "image",
        ContentFile(data, name=filename),
        user,
        name=name,
        source_url=submitted_url,
        content_hash=digest,
    )
```

- [ ] **Step 4: Run to verify it passes.** Expected: PASS.

- [ ] **Step 5: Falsify**

| Mutant | RED test |
|---|---|
| Move the `create_asset` call inside `_run` | `test_create_asset_runs_on_the_request_thread` |
| Drop the `Accept` header | `test_user_agent_and_accept_are_sent` |
| `create_asset(..., generate=False)` | `test_happy_path_creates_a_normal_asset` (the derivatives assertions) |
| `validate_fetch_url(submitted_url)` as a **bare call** (drop the assignment) | `test_a_padded_url_is_stored_stripped` |

- [ ] **Step 6: Lint**

Run: `uv run ruff check --no-cache courses/media_fetch.py`

Expected: **four `F401` unused-import errors** — `BytesIO`, `unquote`, `urljoin` and
`truncate_filename` are imported here but not consumed until Tasks 5 and 7. That is fine at
this checkpoint; they clear once Task 7 lands. What must be **absent** is `S310`: if it
fires, the `noqa` is misplaced — it belongs on the `Request(` line, not the function.

(If you prefer a clean gate per task, move those four imports into the tasks that first use
them instead. Either way, do not let the false expectation "clean" send you hunting the
`noqa` placement.)

- [ ] **Step 7: Commit**

```bash
git add courses/media_fetch.py courses/tests/test_media_fetch_transport.py
git commit -m "feat(media-fetch): transport seam, deadline thread, happy path"
```

---

### Task 5: Redirects and status handling

**Files:**
- Modify: `courses/media_fetch.py` (`_fetch`)
- Test: `courses/tests/test_media_fetch_redirects.py` *(new)*

**Interfaces:**
- Consumes: T4's `_fetch`, `_open`, `_BudgetExceeded`.
- Produces: unchanged public signature; `_fetch` now follows ≤3 validated hops and returns the final hop as `current_url`.

- [ ] **Step 1: Write the failing tests**

```python
# courses/tests/test_media_fetch_redirects.py
import urllib.error

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from courses import media_fetch
from courses.tests.test_media_fetch_transport import FakeResponse
from courses.tests.test_media_fetch_transport import png_bytes
from tests.factories import CourseFactory, UserFactory

pytestmark = pytest.mark.django_db
OK = ["upload.wikimedia.org"]
URL = "https://upload.wikimedia.org/Foo.png"


def redirect(code, location):
    """A refused redirect arrives as a RAISED HTTPError -- never a returned response."""
    return urllib.error.HTTPError(URL, code, "redirect", {"Location": location}, None)


def sequence(*items):
    it = iter(items)

    def fake_open(req, timeout):
        nxt = next(it)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    return fake_open


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_exactly_three_redirects_succeed(monkeypatch):
    monkeypatch.setattr(media_fetch, "_open", sequence(
        redirect(302, "https://upload.wikimedia.org/a.png"),
        redirect(302, "https://upload.wikimedia.org/b.png"),
        redirect(302, "https://upload.wikimedia.org/c.png"),
        FakeResponse(png_bytes()),
    ))
    asset = media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert asset.source_url == URL
    # NOTE: the other half of the spec's paired invariant -- that the filename stem
    # comes from the FINAL hop -- is asserted in TASK 7, not here. _derive_filename
    # does not exist yet at this task, and Task 4's _build_asset hardcodes
    # filename="image.png", so an assertion on original_filename would be RED for a
    # reason that has nothing to do with redirects.


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_a_fourth_redirect_is_too_many(monkeypatch):
    monkeypatch.setattr(media_fetch, "_open", sequence(
        *[redirect(302, f"https://upload.wikimedia.org/{i}.png") for i in range(4)]
    ))
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "redirects too many times" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
@pytest.mark.parametrize(
    "location,fragment",
    [
        ("https://evil.com/x.png", "not on the allow-list"),
        ("http://upload.wikimedia.org/x.png", "not on the allow-list"),  # downgrade
        ("", "invalid redirect"),
    ],
)
def test_bad_redirect_targets(monkeypatch, location, fragment):
    monkeypatch.setattr(media_fetch, "_open", sequence(redirect(302, location)))
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert fragment in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_404_reports_status_not_transport(monkeypatch):
    """Proves the HTTPError clause precedes the URLError one.

    HTTPError SUBCLASSES URLError, so a URLError clause placed first swallows every
    redirect and status error and this reports "Could not reach the image host."
    """
    monkeypatch.setattr(media_fetch, "_open", sequence(
        urllib.error.HTTPError(URL, 404, "nope", {}, None)
    ))
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "returned an error" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_returned_206_is_rejected(monkeypatch):
    """206 never becomes an HTTPError -- HTTPErrorProcessor raises only outside
    200-299 -- so only the explicit resp.status != 200 check catches it."""
    monkeypatch.setattr(media_fetch, "_open",
                        lambda req, t: FakeResponse(png_bytes(), status=206))
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "returned an error" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_connection_failure_is_a_422_not_a_500(monkeypatch):
    def boom(req, timeout):
        raise urllib.error.URLError("dns")

    monkeypatch.setattr(media_fetch, "_open", boom)
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "Could not reach" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_mid_read_failure_is_also_a_422(monkeypatch):
    """The reason OSError is in the tuple and the try SPANS the read loop.

    A DNS failure raises from open(); a truncated body raises from inside the loop,
    AFTER the `with` has been entered. Narrowing the try to the open() call alone
    would keep test_connection_failure GREEN -- only this one goes RED.
    """
    class Truncating(FakeResponse):
        def __init__(self):
            super().__init__(png_bytes())
            self._calls = 0

        def read1(self, n=-1):
            self._calls += 1
            if self._calls > 1:
                raise OSError("connection reset mid-body")
            return super().read1(8)

    monkeypatch.setattr(media_fetch, "_open", lambda req, t: Truncating())
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "Could not reach" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_headers_are_sent_on_every_redirect_hop(monkeypatch):
    """Wikimedia 403s a generic UA, so a hop that drops the header silently breaks the
    feature against its own default allow-list. Capturing only the first call (as the
    Task-4 test does) would miss a refactor that reuses a bare url on the redirect path.
    """
    seen = []

    def fake_open(req, timeout):
        seen.append((req.get_header("User-agent"), req.get_header("Accept")))
        if len(seen) <= 3:
            raise redirect(302, f"https://upload.wikimedia.org/{len(seen)}.png")
        return FakeResponse(png_bytes())

    monkeypatch.setattr(media_fetch, "_open", fake_open)
    media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert len(seen) == 4
    assert all("libli" in ua and accept == "image/*" for ua, accept in seen)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_worker_message_renders_in_the_active_language(monkeypatch):
    """Proves the params= deferral. gettext is THREAD-LOCAL and the daemon thread has
    no activation, so a message %-formatted on the worker resolves to English there and
    this assertion goes RED. Every other test asserts English fragments, so this is the
    only guard on the rule.
    """
    from django.utils import translation

    monkeypatch.setattr(media_fetch, "_open", sequence(
        urllib.error.HTTPError(URL, 404, "nope", {}, None)
    ))
    with translation.override("pl"):
        with pytest.raises(ValidationError) as exc:
            media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
        rendered = "; ".join(exc.value.messages)
    assert "Serwer obrazów zwrócił błąd" in rendered
    assert "404" in rendered
```

⚠️ This last test depends on Task 12's Polish catalog existing. If Tasks are executed in
order it will fail until Task 12 lands — so **either move it to Task 12**, or mark it
`@pytest.mark.xfail(reason="needs the pl catalog from Task 12", strict=False)` here and
flip it to a hard assertion in Task 12. Do not skip it: it is the only coverage of the
`params=` rule.

- [ ] **Step 2: Run to verify it fails.** Expected: most fail — `_fetch` follows no redirects yet.

- [ ] **Step 3: Implement the loop**

Replace `_fetch` in `courses/media_fetch.py`:

```python
def _fetch(submitted_url, deadline, max_bytes):
    """Worker body: steps 4-8. Returns (data, current_url).

    Redirects and non-2xx arrive as RAISED HTTPError, never as returned responses:
    build_opener keeps HTTPErrorProcessor (which raises outside 200-299) and
    _NoRedirect raises on any 3xx. So opener.open() returns ONLY a 2xx.
    """
    current_url = submitted_url
    for hop in range(MAX_REDIRECT_HOPS + 1):   # one initial GET + at most 3 redirects
        # EXACTLY ONE budget check per iteration. It is deliberately fused into the
        # timeout computation rather than written as a separate bare call above: two
        # checks would make the first redundant (the argument is evaluated before
        # _open runs, and _BudgetExceeded escapes both except clauses either way), and
        # a "drop the top-of-loop check" mutant would then be a no-op that no test
        # could catch. One check, one mutant, one RED test.
        hop_timeout = min(TIMEOUT_SECONDS, _remaining(deadline))
        try:
            with _open(_build_request(current_url), hop_timeout) as resp:
                # HTTPErrorProcessor raises only OUTSIDE 200-299, so a 204/206 lands
                # here as a normal response and needs an explicit check.
                if getattr(resp, "status", 200) != 200:
                    raise ValidationError(
                        _("The image host returned an error (status %(status)s)."),
                        code="status",
                        params={"status": resp.status},
                    )
                _check_content_type(resp)        # Task 6 fills this in
                return _read_capped(resp, deadline, max_bytes), current_url
        except urllib.error.HTTPError as exc:
            # MUST precede the URLError clause below: HTTPError subclasses URLError.
            try:
                if exc.code not in REDIRECT_STATUSES:
                    raise ValidationError(
                        _("The image host returned an error (status %(status)s)."),
                        code="status",
                        params={"status": exc.code},
                    )
                if hop == MAX_REDIRECT_HOPS:
                    raise ValidationError(
                        _("That URL redirects too many times."), code="redirect-too-many"
                    )
                location = (exc.headers or {}).get("Location") or ""
                if not location:
                    raise ValidationError(
                        _("The image host returned an invalid redirect."),
                        code="redirect-invalid",
                    )
                target = urljoin(current_url, location)
                try:
                    current_url = validate_fetch_url(target)
                except ValidationError as inner:
                    # Replace the underlying rule's message: telling the author their
                    # URL "must use https" when it was the REDIRECT that downgraded is
                    # a false statement about what they typed.
                    raise ValidationError(
                        _("That URL redirects to a host that is not on the allow-list."),
                        code="redirect-off-allowlist",
                        params={"target_host": urlsplit(target).hostname or ""},
                    ) from inner
            finally:
                try:
                    exc.close()   # the `with` was never entered -- close it here
                except Exception:  # noqa: BLE001, S110
                    pass
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            # NOT delivery.py:67's tuple -- that one INCLUDES HTTPError, which would
            # swallow every redirect and status error above. This is delivery.py:144's,
            # plus OSError for mid-read socket failures.
            raise ValidationError(
                _("Could not reach the image host."),
                code="transport",
                params={"exc": type(exc).__name__},
            ) from exc
    # Deliberately undrivable, kept as a guard in the style of geogebra.py:405-412: the
    # `hop == MAX_REDIRECT_HOPS` branch already raises on the last iteration and every
    # other path returns or raises, so the loop cannot fall through. Do NOT write a test
    # for this line -- no input reaches it.
    raise ValidationError(
        _("That URL redirects too many times."), code="redirect-too-many"
    )
```

Add a placeholder `_check_content_type` (Task 6 implements it):

```python
def _check_content_type(resp):
    return None
```

- [ ] **Step 4: Run to verify it passes.** Expected: PASS.

- [ ] **Step 5: Falsify**

| Mutant | RED test |
|---|---|
| Put `except (TimeoutError, urllib.error.URLError, OSError)` **before** the `HTTPError` clause | `test_404_reports_status_not_transport` |
| Drop the `resp.status != 200` check | `test_returned_206_is_rejected` |
| Change `range(MAX_REDIRECT_HOPS + 1)` to `range(MAX_REDIRECT_HOPS)` | `test_exactly_three_redirects_succeed` |
| Let the inner `ValidationError` propagate instead of replacing it | the http-downgrade case |
| Set `source_url=current_url` in `_build_asset` | `test_exactly_three_redirects_succeed` |
| Narrow the `try` to the `open()` call only | `test_mid_read_failure_is_also_a_422` |
| Build hops without `_build_request` (drop the headers) | `test_headers_are_sent_on_every_redirect_hop` |
| `%`-format the status message on the worker | `test_worker_message_renders_in_the_active_language` |

- [ ] **Step 6: Commit**

```bash
git add courses/media_fetch.py courses/tests/test_media_fetch_redirects.py
git commit -m "feat(media-fetch): manual redirect following and status handling"
```

---

### Task 6: Content-Type gate and the byte cap

**Files:**
- Modify: `courses/media_fetch.py` (`_check_content_type`, `_read_capped`, **and `_build_asset`** — the empty-body guard). Task 7 rewrites `_build_asset` wholesale, so that guard must survive the rewrite, moving inside its new try/log wrapper.
- Test: `courses/tests/test_media_fetch_body.py` *(new)*

**Interfaces:**
- Consumes: T5's `_fetch`.
- Produces: `MEDIA_TYPE_MAP: dict[str, tuple[str, ...]]`; `_check_content_type(resp)` raising on a non-image type.

- [ ] **Step 1: Write the failing tests**

```python
# courses/tests/test_media_fetch_body.py
import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from courses import media_fetch
from courses.tests.test_media_fetch_transport import FakeResponse
from courses.tests.test_media_fetch_transport import png_bytes
from tests.factories import CourseFactory, UserFactory

pytestmark = pytest.mark.django_db
OK = ["upload.wikimedia.org"]
URL = "https://upload.wikimedia.org/Foo.jpg"   # a .jpg PATH, deliberately


def run(monkeypatch, **kw):
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: FakeResponse(**kw))
    return media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
@pytest.mark.parametrize(
    "ctype,fragment",
    [
        ("text/html", "did not return an image"),   # the commons.wikimedia.org case
        ("", "did not return an image"),            # header present but EMPTY
        ("image/svg+xml", "image type is not allowed"),  # honest message, not the above
    ],
)
def test_content_type_gate(monkeypatch, ctype, fragment):
    with pytest.raises(ValidationError) as exc:
        run(monkeypatch, data=b"<html>nope</html>", headers={"Content-Type": ctype})
    assert fragment in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_absent_content_type_header_is_rejected(monkeypatch):
    """The header MISSING ENTIRELY, distinct from the empty-string case above -- the
    spec requires both, and an implementer could plausibly treat absent as "unknown,
    let Pillow decide", which drops an enumerated message."""
    with pytest.raises(ValidationError) as exc:
        run(monkeypatch, data=b"<html>nope</html>", headers={})
    assert "did not return an image" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
@pytest.mark.parametrize("ctype", ["image/png", "image/PNG", "image/png; charset=binary"])
def test_content_type_accepted_forms(monkeypatch, ctype):
    assert run(monkeypatch, data=png_bytes(), headers={"Content-Type": ctype})


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_nonstandard_image_jpg_media_type_is_accepted(monkeypatch):
    """image/jpg is non-standard but widely emitted. Both documents justify the map
    entry explicitly, and without this test it could be deleted with nothing going
    RED."""
    import io as _io

    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format="JPEG")
    assert run(monkeypatch, data=buf.getvalue(), headers={"Content-Type": "image/jpg"})


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_cap_trips_mid_stream_when_content_length_lies(monkeypatch):
    """Assert the body was ABANDONED, not merely that the message appeared.

    A message-only assertion passes on the very mutant it is named for: with the cap
    check moved after the loop, the whole 11 MiB is still read and `total > max_bytes`
    raises the identical "too large". Counting read1 calls is what distinguishes
    "abandoned early" from "streamed it all, then complained".
    """
    cap = 5 * 1024 * 1024                              # the effective ceiling
    big = png_bytes() + b"\0" * (6 * 1024 * 1024)      # comfortably over it

    class Counting(FakeResponse):
        def __init__(self):
            super().__init__(big, headers={
                "Content-Type": "image/png",
                "Content-Length": "10",                # a lie, deliberately
            })
            self.reads = 0

        def read1(self, n=-1):
            self.reads += 1
            return super().read1(n)

    resp = Counting()
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: resp)
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "too large" in "; ".join(exc.value.messages)
    # The loop reads ONE chunk past the cap, then stops. Reading the whole body would
    # take ~2x as many chunks.
    assert resp.reads <= (cap // media_fetch.CHUNK_BYTES) + 2


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_over_cap_content_length_rejects_before_reading_the_body(monkeypatch):
    """The early-exit half. Without this, deleting the whole Content-Length block from
    _read_capped breaks NO test -- the malformed and lying cases both pass without it.
    Assert zero read1 calls, which is the only thing that distinguishes "rejected early"
    from "rejected after streaming 6 MiB".
    """
    class NeverRead(FakeResponse):
        def __init__(self):
            super().__init__(b"", headers={
                "Content-Type": "image/png",
                "Content-Length": str(50 * 1024 * 1024),
            })
            self.reads = 0

        def read1(self, n=-1):
            self.reads += 1
            raise AssertionError("body must not be read when Content-Length is over cap")

    resp = NeverRead()
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: resp)
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "too large" in "; ".join(exc.value.messages)
    assert resp.reads == 0


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
@pytest.mark.parametrize("cl", [None, "not-a-number", "-5"])
def test_malformed_content_length_is_ignored_not_rejected(monkeypatch, cl):
    headers = {"Content-Type": "image/png"}
    if cl is not None:
        headers["Content-Length"] = cl
    assert run(monkeypatch, data=png_bytes(), headers=headers)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_empty_body_is_rejected(monkeypatch):
    with pytest.raises(ValidationError) as exc:
        run(monkeypatch, data=b"", headers={"Content-Type": "image/png"})
    assert "empty" in "; ".join(exc.value.messages)
```

- [ ] **Step 2: Run to verify it fails.** Expected: FAIL — the gate is a no-op stub.

- [ ] **Step 3: Implement**

```python
MEDIA_TYPE_MAP = {
    "image/png": ("png",),
    "image/jpeg": ("jpg", "jpeg"),
    "image/jpg": ("jpg", "jpeg"),      # non-standard but widely emitted
    "image/gif": ("gif",),
    "image/webp": ("webp",),
}


def _media_type(resp):
    raw = (resp.headers or {}).get("Content-Type") or ""
    return raw.split(";", 1)[0].strip().lower()


def _check_content_type(resp):
    mt = _media_type(resp)
    if mt == "image/svg+xml":
        # Excluded on purpose (active content; the upload path refuses it too). But
        # Wikimedia serves a lot of SVG and IS the default allow-list, so an author
        # WILL paste one -- "did not return an image" would be false and unhelpful.
        raise ValidationError(_("That image type is not allowed."), code="content-type",
                              params={"content_type": mt})
    if mt not in MEDIA_TYPE_MAP:
        raise ValidationError(_("That URL did not return an image."), code="content-type",
                              params={"content_type": mt})
```

In `_read_capped`, add the advisory `Content-Length` early exit at the top:

```python
def _read_capped(resp, deadline, max_bytes):
    # ADVISORY ONLY: an absent/non-numeric/negative header is ignored, never a
    # rejection and never a reason to relax the streaming check below. It only saves
    # a pointless transfer. (iter-style reads yield DECOMPRESSED bytes, so a gzipped
    # response can declare a length well under the cap and still exceed it.)
    declared = (resp.headers or {}).get("Content-Length")
    try:
        if declared is not None and int(declared) > max_bytes:
            raise ValidationError(
                _("Image file too large (max %(mib)d MiB)."),
                code="too-large",
                params={"mib": max_bytes // (1024 * 1024)},
            )
    except (TypeError, ValueError):
        pass
    ...  # existing loop
```

And in `_build_asset`, before anything else:

```python
    if not data:
        # media_upload gets its empty-file rejection from MediaAssetForm's FileField,
        # which this path bypasses, and MediaAsset.clean() has no lower size bound --
        # so without this a 200 + Content-Length: 0 creates a real zero-byte asset.
        raise ValidationError(_("The fetched file is empty."), code="empty-body")
```

- [ ] **Step 4: Run to verify it passes.** Expected: PASS.

- [ ] **Step 5: Falsify**

| Mutant | RED test |
|---|---|
| Drop the `svg+xml` branch | the SVG parametrisation |
| Drop `.split(";")` | the `charset=binary` case |
| Move the cap check outside the read loop (check only at the end) | `test_cap_trips_mid_stream_when_content_length_lies` |
| Make a malformed `Content-Length` raise | `test_malformed_content_length_is_ignored_not_rejected` |
| Delete the `Content-Length` early-exit block entirely | `test_over_cap_content_length_rejects_before_reading_the_body` |
| Treat an absent `Content-Type` as "let Pillow decide" | `test_absent_content_type_header_is_rejected` |
| Remove the `image/jpg` entry from `MEDIA_TYPE_MAP` | `test_nonstandard_image_jpg_media_type_is_accepted` |
| Drop the `if not data` guard | `test_empty_body_is_rejected` |

- [ ] **Step 6: Commit**

```bash
git add courses/media_fetch.py courses/tests/test_media_fetch_body.py
git commit -m "feat(media-fetch): content-type gate, byte cap, empty-body guard"
```

---

### Task 7: Payload verification and filename derivation

**Files:**
- Modify: `courses/media_fetch.py` (`_build_asset`)
- Test: `courses/tests/test_media_fetch_filename.py` *(new)*

**Interfaces:**
- Consumes: T6.
- Produces: `PILLOW_FORMAT_MAP`; `_verify_payload(data) -> str` (returns `img.format`); `_derive_filename(current_url, fmt, allowed_exts) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# courses/tests/test_media_fetch_filename.py
import io

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from courses import media_fetch
from courses.tests.test_media_fetch_transport import FakeResponse
from tests.factories import CourseFactory, UserFactory

pytestmark = pytest.mark.django_db
OK = ["upload.wikimedia.org"]


def img_bytes(fmt="PNG", size=(4, 4)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, "green").save(buf, format=fmt)
    return buf.getvalue()


def run(monkeypatch, url, data, ctype):
    monkeypatch.setattr(media_fetch, "_open",
                        lambda req, t: FakeResponse(data, headers={"Content-Type": ctype}))
    return media_fetch.fetch_image_asset(CourseFactory(), url, UserFactory())


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
@pytest.mark.parametrize(
    "url,data_fmt,ctype,expected",
    [
        # EXACT equality, not "endswith" -- an endswith check would also pass for the
        # Foo.png.gif double-extension bug this rule exists to prevent.
        ("https://upload.wikimedia.org/Foo.png", "PNG", "image/png", "Foo.png"),
        ("https://upload.wikimedia.org/Foo.JPG", "JPEG", "image/jpeg", "Foo.jpg"),
        ("https://upload.wikimedia.org/Foo", "PNG", "image/png", "Foo.png"),
        ("https://upload.wikimedia.org/", "PNG", "image/png", "image.png"),
        # The sniffed format WINS over a lying header:
        ("https://upload.wikimedia.org/Foo.png", "GIF", "image/png", "Foo.gif"),
    ],
)
def test_filename(monkeypatch, url, data_fmt, ctype, expected):
    asset = run(monkeypatch, url, img_bytes(data_fmt), ctype)
    assert asset.original_filename == expected


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_stem_comes_from_the_final_hop(monkeypatch):
    """The other half of the spec's paired invariant (Task 5 asserts source_url).

    commons.wikimedia.org/wiki/Special:FilePath/Foo.jpg redirects to an
    upload.wikimedia.org path whose basename is the useful one; the submitted path's
    basename is "Special:FilePath". Deferred to THIS task because _derive_filename
    does not exist until now.
    """
    import urllib.error

    calls = []

    def fake_open(req, timeout):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                req.full_url, 302, "r",
                {"Location": "https://upload.wikimedia.org/Real.png"}, None,
            )
        return FakeResponse(img_bytes("PNG"), headers={"Content-Type": "image/png"})

    monkeypatch.setattr(media_fetch, "_open", fake_open)
    submitted = "https://upload.wikimedia.org/Special:FilePath"
    asset = media_fetch.fetch_image_asset(CourseFactory(), submitted, UserFactory())
    assert asset.source_url == submitted          # submitted url is STORED
    assert asset.original_filename == "Real.png"  # stem comes from the FINAL hop


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_narrowed_extensions_do_not_double_up(monkeypatch):
    """With the allowed set narrowed to ["jpeg"], a .jpg URL must store Foo.jpeg --
    never Foo.jpg.jpeg. This is what pins the trailing-extension strip to
    SAFE_IMAGE_EXTENSIONS rather than effective_image_extensions()."""
    monkeypatch.setattr(media_fetch, "effective_image_extensions", lambda: ["jpeg"])
    asset = run(monkeypatch, "https://upload.wikimedia.org/Foo.jpg",
                img_bytes("JPEG"), "image/jpeg")
    assert asset.original_filename == "Foo.jpeg"


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_traversal_in_path_cannot_escape(monkeypatch):
    asset = run(monkeypatch, "https://upload.wikimedia.org/a/..%2F..%2Fx.png",
                img_bytes("PNG"), "image/png")
    assert "/" not in asset.original_filename
    assert ".." not in asset.original_filename


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_html_under_an_image_content_type_is_rejected(monkeypatch):
    with pytest.raises(ValidationError) as exc:
        run(monkeypatch, "https://upload.wikimedia.org/Foo.png",
            b"<html>not an image</html>", "image/png")
    assert "usable image" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_unknown_pillow_format_is_a_422_not_a_keyerror(monkeypatch):
    with pytest.raises(ValidationError) as exc:
        run(monkeypatch, "https://upload.wikimedia.org/Foo.png",
            img_bytes("BMP"), "image/png")
    assert "image type is not allowed" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_pixel_bound_rejects_between_max_pixels_and_pillows_limit(monkeypatch):
    """Target the band THIS code owns: MAX_PIXELS (50M) < declared < 2x Pillow's
    89,478,485. Above 2x, Pillow refuses unaided and the test would pass on a build
    with no pixel check at all.

    NOTE this does NOT pin the check's ORDER relative to verify() -- a genuine 50x50
    PNG passes verify(), so moving the size check after it produces the identical
    error. See test_pixel_check_runs_before_verify for the ordering.
    """
    monkeypatch.setattr(media_fetch, "MAX_PIXELS", 100)
    with pytest.raises(ValidationError) as exc:
        run(monkeypatch, "https://upload.wikimedia.org/Foo.png",
            img_bytes("PNG", size=(50, 50)), "image/png")
    assert "dimensions are too large" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_pixel_check_runs_before_verify(monkeypatch):
    """The ordering the spec argues for, with the fixture that actually pins it.

    A PNG whose IHDR declares huge dimensions over a TRUNCATED body: Image.open reads
    the header and reports the size, but PngImageFile.verify() walks the remaining
    chunks and checks CRCs, so it would reject this as "not a usable image". Only when
    the pixel check runs FIRST does it report the dimensions message.
    """
    good = img_bytes("PNG", size=(8, 8))
    # Rewrite IHDR width/height to 9000x9000, RECOMPUTE THE CHUNK CRC, then truncate.
    # Without the CRC recompute the chunk is corrupt and Image.open raises
    # UnidentifiedImageError -- the broad clause fires, the message is "not a usable
    # image", and this test is RED on a CORRECT build. MEASURED on Pillow 12.2:
    #   no CRC fix  -> UnidentifiedImageError
    #   CRC fixed   -> Image.open reports (9000, 9000); verify() raises OSError
    import struct
    import zlib

    ihdr = good.index(b"IHDR")
    d = bytearray(good)
    d[ihdr + 4:ihdr + 12] = struct.pack(">II", 9000, 9000)
    d[ihdr + 17:ihdr + 21] = struct.pack(
        ">I", zlib.crc32(bytes(d[ihdr:ihdr + 17])) & 0xFFFFFFFF
    )
    truncated = bytes(d[: ihdr + 40])

    monkeypatch.setattr(media_fetch, "MAX_PIXELS", 1000)
    with pytest.raises(ValidationError) as exc:
        run(monkeypatch, "https://upload.wikimedia.org/Foo.png", truncated, "image/png")
    assert "dimensions are too large" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_truncated_png_is_rejected_by_the_broad_clause(monkeypatch):
    """What actually falsifies `except UnidentifiedImageError` only.

    MEASURED: HTML bytes raise precisely UnidentifiedImageError, so the narrowed
    clause catches them and test_html_under_an_image_content_type_is_rejected passes
    on that mutant. A truncated-but-valid PNG is the discriminator: Image.open
    SUCCEEDS and verify() raises OSError("Truncated File Read"), which only the broad
    clause converts -- the narrow one lets it escape as a 500.
    """
    good = img_bytes("PNG", size=(64, 64))
    truncated = good[: len(good) // 2]
    with pytest.raises(ValidationError) as exc:
        run(monkeypatch, "https://upload.wikimedia.org/Foo.png", truncated, "image/png")
    assert "usable image" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_decompression_bomb_reports_the_same_dimensions_message(monkeypatch):
    """The FAR side of the boundary. Above 2x Image.MAX_IMAGE_PIXELS, Pillow raises
    DecompressionBombError from Image.open -- BEFORE the explicit size check can run --
    so without the dedicated except clause it falls into the broad one and the author
    is told the file is "not a usable image", disagreeing with the smaller case.
    """
    from PIL import Image

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 16)   # 2x -> 32 px
    with pytest.raises(ValidationError) as exc:
        run(monkeypatch, "https://upload.wikimedia.org/Foo.png",
            img_bytes("PNG", size=(50, 50)), "image/png")
    assert "dimensions are too large" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_mpo_format_is_accepted_as_jpg(monkeypatch):
    """MPO is the NORMAL Pillow format for multi-picture JPEGs -- what most phone
    cameras produce. Omitting it from the map rejects a large share of real photos.

    Pillow will not save(format="MPO") from a plain Image.new, so build a two-frame
    JPEG (which Pillow opens as MPO) via append_images.
    """
    from PIL import Image

    buf = io.BytesIO()
    a = Image.new("RGB", (4, 4), "red")
    b = Image.new("RGB", (4, 4), "blue")
    # format="MPO", NOT "JPEG": Image.SAVE_ALL has no "JPEG" entry, so save_all with
    # format="JPEG" raises KeyError('JPEG') before the guard below runs. MEASURED.
    a.save(buf, format="MPO", save_all=True, append_images=[b])
    data = buf.getvalue()
    assert Image.open(io.BytesIO(data)).format == "MPO"   # guard the fixture itself

    asset = run(monkeypatch, "https://upload.wikimedia.org/Foo.jpg", data, "image/jpeg")
    assert asset.original_filename == "Foo.jpg"
```

- [ ] **Step 2: Run to verify it fails.** Expected: FAIL — filename is the hardcoded `image.png`.

- [ ] **Step 3: Implement**

```python
PILLOW_FORMAT_MAP = {
    "PNG": ("png",),
    "JPEG": ("jpg", "jpeg"),
    # Pillow reports MPO -- not JPEG -- for multi-picture JPEGs, which is what most
    # phone cameras produce and a large share of real web JPEGs. Omitting it would
    # reject them as an unknown format.
    "MPO": ("jpg", "jpeg"),
    "GIF": ("gif",),
    "WEBP": ("webp",),
}


def _verify_payload(data):
    """Return img.format. Rejects anything Pillow cannot open, and over-large canvases.

    Image.open's header sniff is the real format authority; Image.verify() is a no-op
    on the base class and is overridden by only a few plugins (notably PNG). A
    TRUNCATED jpeg/gif/webp passes both, is stored, and fails later inside
    generate_derivatives, which swallows it -- knowingly accepted, so do not write a
    truncation-rejection test.
    """
    from PIL import Image

    try:
        img = Image.open(BytesIO(data))
        fmt, size = img.format, img.size
        # Pixel check BEFORE verify(): PngImageFile.verify() walks chunks and checks
        # CRCs, so the natural huge-IHDR fixture would be rejected as "not a usable
        # image" and this test would fail on a CORRECT build.
        if size[0] * size[1] > MAX_PIXELS:
            raise ValidationError(
                _("That image's dimensions are too large."), code="too-many-pixels"
            )
        img.verify()
    except ValidationError:
        raise
    except Image.DecompressionBombError as exc:
        # Its own clause, BEFORE the broad one: Pillow raises this from Image.open
        # above 2x MAX_IMAGE_PIXELS, i.e. before the size check above can run. Mapping
        # it here keeps both sides of that boundary reporting the same condition.
        raise ValidationError(
            _("That image's dimensions are too large."), code="too-many-pixels"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - the view catches only ValidationError
        raise ValidationError(
            _("That URL did not return a usable image."), code="not-an-image"
        ) from exc
    return fmt


def _derive_filename(current_url, fmt, allowed_exts):
    from courses.validators import SAFE_IMAGE_EXTENSIONS

    candidates = PILLOW_FORMAT_MAP.get(fmt)
    if not candidates:
        raise ValidationError(_("That image type is not allowed."), code="format")
    ext = next((c for c in candidates if c in allowed_exts), None)
    if ext is None:
        raise ValidationError(_("That image type is not allowed."), code="format")

    # Unquote FIRST, then basename: taking the basename first leaves "..%2F..%2Fx.png"
    # intact, which unquotes to "../../x.png" and makes Django's storage raise
    # SuspiciousFileOperation -- a 500, since only ValidationError is caught.
    path = unquote(urlsplit(current_url).path)
    stem = path.rsplit("/", 1)[-1]
    head, dot, tail = stem.rpartition(".")
    # Strip against the FIXED safe universe, never effective_image_extensions(): the
    # latter is intersected with admin config, so under a narrowing to ["jpeg"] a
    # .jpg path would not be stripped and we would store Foo.jpg.jpeg.
    if dot and tail.lower() in SAFE_IMAGE_EXTENSIONS:
        stem = head
    stem = stem.replace("/", "").replace("\\", "").replace("..", "")
    stem = "".join(ch for ch in stem if ch.isprintable()).lstrip(".").strip()
    return truncate_filename(f"{stem or 'image'}.{ext}")
```

Wire both into `_build_asset`:

```python
def _build_asset(course, user, name, submitted_url, current_url, data, allowed_exts):
    # Steps 9-13 run HERE, on the request thread, so they log at their own sites --
    # the spec's fourth logging bullet. Without these, four enumerated conditions
    # (empty body, not-a-usable-image, too-many-pixels, unknown format) leave no
    # operator-visible trace at all.
    host = urlsplit(submitted_url).hostname
    try:
        if not data:
            raise ValidationError(_("The fetched file is empty."), code="empty-body")
        fmt = _verify_payload(data)
        filename = _derive_filename(current_url, fmt, allowed_exts)
    except ValidationError as exc:
        logger.warning(
            "image fetch: host=%s reason=%s", host, getattr(exc, "code", None)
        )
        raise
    digest = hashlib.sha256(data).hexdigest()
    return create_asset(...)   # unchanged
```

Note `_verify_payload` and `_derive_filename` themselves stay log-free — one wrapper at the
call site covers all four request-thread rejections without scattering `logger` calls
through the helpers.

- [ ] **Step 4: Run to verify it passes.** Expected: PASS.

- [ ] **Step 5: Falsify**

| Mutant | RED test |
|---|---|
| Strip against `allowed_exts` instead of `SAFE_IMAGE_EXTENSIONS` | `test_narrowed_extensions_do_not_double_up` |
| Drop the trailing-extension strip entirely | the `Foo.png` → `Foo.png.png` case |
| Derive the extension from the Content-Type instead of `fmt` | the GIF-served-as-png case |
| `PILLOW_FORMAT_MAP[fmt]` (bare subscript) | `test_unknown_pillow_format_is_a_422_not_a_keyerror` |
| Move the pixel check after `img.verify()` | `test_pixel_check_runs_before_verify` (**not** the constant-patch test — a real 50×50 PNG passes `verify()`, so that one stays GREEN) |
| Delete the `except Image.DecompressionBombError` clause | `test_decompression_bomb_reports_the_same_dimensions_message` |
| `except UnidentifiedImageError` only | `test_truncated_png_is_rejected_by_the_broad_clause` (**not** the HTML test — MEASURED, HTML bytes raise exactly `UnidentifiedImageError`, so the narrow clause handles them identically) |
| Basename before unquote | **no test — the two orders converge.** Correct: unquote → `/a/../../x.png` → basename `x.png`. Mutant: basename `..%2F..%2Fx.png` → unquote `../../x.png` → the sanitizer strips `/` and `..` → `x.png`. Identical. The test pins the SANITIZER, not the ordering; keep the ordering as defence-in-depth and do not claim a falsification it cannot deliver. |
| Remove `MPO` from the map | `test_mpo_format_is_accepted_as_jpg` |
| Pass `submitted_url` to `_derive_filename` instead of `current_url` | `test_stem_comes_from_the_final_hop` |

- [ ] **Step 6: Commit**

```bash
git add courses/media_fetch.py courses/tests/test_media_fetch_filename.py
git commit -m "feat(media-fetch): Pillow verification, pixel bound, filename derivation"
```

---

### Task 8: The deadline tests

**Files:**
- Test: `courses/tests/test_media_fetch_deadline.py` *(new)*

**Interfaces:** consumes T4–T7; adds no production code unless a test exposes a gap.

- [ ] **Step 1: Write the tests**

```python
# courses/tests/test_media_fetch_deadline.py
import io
import time

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from courses import media_fetch
from tests.factories import CourseFactory, UserFactory

pytestmark = pytest.mark.django_db
OK = ["upload.wikimedia.org"]
URL = "https://upload.wikimedia.org/Foo.png"


class DripBody(io.RawIOBase):
    """read1 returns PARTIAL data slowly.

    Deliberately NOT a generator: a generator-based double returns instantly and the
    test would pass GREEN on a build that reads with read() instead of read1() -- the
    exact "assertion that cannot fail" this repo has shipped before.
    """

    def __init__(self, delay):
        self.delay = delay
        self.headers = {"Content-Type": "image/png"}
        self.status = 200

    def read1(self, n=-1):
        time.sleep(self.delay)
        return b"\0" * 8

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_drip_body_hits_the_deadline(monkeypatch):
    # Patch the constants DOWN -- at 20s each of these would add ~20s to a suite that
    # otherwise runs affected tests in ~30s. The drip rate is expressed relative to
    # the patched value so the test stays meaningful if the constant changes.
    monkeypatch.setattr(media_fetch, "DEADLINE_SECONDS", 0.4)
    monkeypatch.setattr(media_fetch, "TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: DripBody(0.05))
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "took too long" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_drip_header_hits_the_deadline(monkeypatch):
    """A slow HEADER never reaches the chunk loop at all -- only the thread-join
    budget bounds it. A per-socket timeout would not fire."""
    monkeypatch.setattr(media_fetch, "DEADLINE_SECONDS", 0.3)

    def slow_open(req, timeout):
        time.sleep(5)

    monkeypatch.setattr(media_fetch, "_open", slow_open)
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "took too long" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_budget_is_checked_between_redirect_hops(monkeypatch):
    """Assert on the WORKER, not on the user-facing message.

    The message is the wrong probe: the joiner emits "took too long" unconditionally
    whenever join() times out with an empty box, whether or not the worker ever checked
    its budget. So with the top-of-loop _remaining() removed the worker keeps issuing
    hops on the daemon thread while the joiner still reports the deadline -- and a
    message-only assertion stays GREEN on the mutant it claims to catch.

    This is the spec's headline safety property: (MAX_REDIRECT_HOPS + 1) x
    TIMEOUT_SECONDS = 32s exceeds DEADLINE_SECONDS = 20s, and the per-iteration check
    is the only thing holding the bound. Count the calls instead.
    """
    import urllib.error

    monkeypatch.setattr(media_fetch, "DEADLINE_SECONDS", 0.3)
    started = []

    def slow_redirect(req, timeout):
        started.append(time.monotonic())
        time.sleep(0.2)
        raise urllib.error.HTTPError(
            URL, 302, "r", {"Location": "https://upload.wikimedia.org/next.png"}, None
        )

    monkeypatch.setattr(media_fetch, "_open", slow_redirect)
    t0 = time.monotonic()
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "took too long" in "; ".join(exc.value.messages)

    # Give the daemon thread a moment to make any further (forbidden) calls.
    time.sleep(0.5)
    assert started, "the worker never issued a request"
    # No hop may START after the deadline instant. Without the top-of-loop check the
    # worker fires all four hops and this fails.
    assert max(started) < t0 + 0.3, f"a hop started past the deadline: {started}"
    assert len(started) <= 2
```

- [ ] **Step 2: Run.** Expected: PASS (production code from T4–T5 already implements this).

- [ ] **Step 3: Falsify**

| Mutant | RED test |
|---|---|
| `resp.read(CHUNK_BYTES)` instead of `read1` | `test_drip_body_hits_the_deadline` (this is the whole point of `DripBody`) |
| Replace `min(TIMEOUT_SECONDS, _remaining(deadline))` with a bare `TIMEOUT_SECONDS` | `test_budget_is_checked_between_redirect_hops` — this is the **only** per-iteration budget check (see the comment in `_fetch`), so removing it really does let the worker keep issuing hops past the deadline |
| Replace `thread.join(DEADLINE_SECONDS)` with `thread.join()` | `test_drip_header_hits_the_deadline` |

- [ ] **Step 4: Confirm the suite is still fast**

Run the four `media_fetch` test files together and check wall-clock is single-digit seconds. If it is ~60s, a constant is being captured at import instead of read at call time.

- [ ] **Step 5: Commit**

```bash
git add courses/tests/test_media_fetch_deadline.py
git commit -m "test(media-fetch): drip body, drip header, inter-hop budget"
```

---

### Task 9: View + route

**Files:**
- Modify: `courses/views_media.py`
- Modify: `courses/urls.py` (beside `manage_media_upload`, ~`:279`)
- Test: `tests/test_media_fetch_view.py` *(new)*

**Interfaces:**
- Consumes: `fetch_image_asset` (T4–T7).
- Produces: URL name `courses:manage_media_fetch`.

- [ ] **Step 1: Write the failing tests**

⚠️ **This repo has no `course` / `manager_user` / `other_user` fixtures.** `tests/conftest.py`
defines only `course_with_image` and `course_with_image_media_root`. The convention in
`tests/test_media_manager.py` and `tests/test_media_picker.py` is factories plus a
locally-built privileged user. Build them in-module, as below — do **not** request fixtures
by those names or every test errors at collection with "fixture not found".

⚠️ **Every success-path test needs `@override_settings`.** Task 1 makes
`config/settings/test.py` *replace* `ALLOWED_IMAGE_FETCH_DOMAINS` with
`["localhost", "127.0.0.1"]` for the whole suite, so a bare
`https://upload.wikimedia.org/...` post returns 422 "not on the allow-list" and the test
fails for a reason that has nothing to do with the view.

```python
# tests/test_media_fetch_view.py
import pytest
from django.test import override_settings
from django.urls import reverse

from courses import media_fetch
from courses.models import MediaAsset
from courses.tests.test_media_fetch_transport import FakeResponse
from courses.tests.test_media_fetch_transport import png_bytes
from tests.factories import CourseFactory
from tests.factories import make_pa
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db

WIKI = ["upload.wikimedia.org"]
URL = "https://upload.wikimedia.org/Foo.png"


@pytest.fixture
def course_and_manager(client):
    """A logged-in course manager, via the repo's make_pa helper.

    Do NOT build this as UserFactory(...) + client.force_login(). UserFactory sets
    skip_postgeneration_save = True with password as a PostGenerationMethodCall, so
    set_password is NEVER PERSISTED -- the row's password stays "" while force_login
    stores the session hash of the in-memory hash. The next request's
    session-auth-hash check fails, the client is anonymous, and every test 302s to
    /accounts/login/. tests/test_notes_views.py:24-28 documents this exact trap.

    Access is owner-or-`courses.change_course` (courses/access.py:37-43, which says
    verbatim it does NOT key on is_staff), and make_pa supplies the Platform Admin
    group that carries the perm.
    """
    pa = make_pa(client, "pa")
    return CourseFactory(owner=pa), pa


def url_for(course):
    return reverse("courses:manage_media_fetch", kwargs={"slug": course.slug})


def patch_transport(monkeypatch):
    monkeypatch.setattr(
        media_fetch, "_open", lambda req, t: FakeResponse(png_bytes())
    )


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_success_returns_the_asset_cell(client, course_and_manager, monkeypatch):
    course, _ = course_and_manager
    patch_transport(monkeypatch)
    resp = client.post(
        url_for(course), {"url": URL}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert resp.status_code == 200
    assert b"asset-cell" in resp.content
    assert MediaAsset.objects.filter(course=course).count() == 1


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_rejection_is_422_with_the_message(client, course_and_manager):
    course, _ = course_and_manager
    resp = client.post(
        url_for(course),
        {"url": "https://evil.com/x.png"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 422
    assert b"That image host is not on the allow-list." in resp.content
    # str(ValidationError(...)) renders "['That image host is not...']" -- the list
    # repr also contains "allow-list", so a substring-only assertion passes on the
    # str(e) mutant. Pin the absence of the repr markers.
    assert b"[&#x27;" not in resp.content


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_missing_url_key_is_422_not_500(client, course_and_manager):
    """Bracket access on request.POST would raise MultiValueDictKeyError, which the
    view does not catch -- a 500 -- and it would make the error table's first row
    unreachable through any client."""
    course, _ = course_and_manager
    resp = client.post(url_for(course), {}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 422
    assert b"Enter an image URL" in resp.content


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_missing_name_key_succeeds(client, course_and_manager, monkeypatch):
    """The picker's shape: it sends no `name` key at all."""
    course, _ = course_and_manager
    patch_transport(monkeypatch)
    resp = client.post(
        url_for(course), {"url": URL}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert resp.status_code == 200


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_no_js_failure_redirects_with_a_message(client, course_and_manager):
    course, _ = course_and_manager
    resp = client.post(url_for(course), {"url": "https://evil.com/x.png"}, follow=True)
    assert resp.redirect_chain
    assert any("allow-list" in str(m) for m in resp.context["messages"])


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_authenticated_get_is_405(client, course_and_manager):
    """@require_POST must sit ABOVE @login_required, or this is a login redirect."""
    course, _ = course_and_manager
    assert client.get(url_for(course)).status_code == 405


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_non_manager_is_refused(client, course_and_manager, django_user_model):
    course, _ = course_and_manager
    # A SECOND client: `client` is already logged in as the PA by the fixture.
    from django.test import Client

    other = Client()
    make_verified_user(other, "nobody")   # logs `other` in as a plain user
    resp = other.post(url_for(course), {"url": URL})
    assert resp.status_code in (403, 404)
```

**On the cross-package import:** `courses/tests/` has no `__init__.py`, so
`from courses.tests.test_media_fetch_transport import FakeResponse` resolves as a PEP 420
namespace subpackage. It works, but pytest then holds two copies of that module. If that
causes trouble, move `FakeResponse`/`png_bytes` into `courses/tests/conftest.py` and import
them as fixtures instead — decide once, at this task, and keep it consistent for Tasks 5–8.

- [ ] **Step 2: Run to verify it fails.** Expected: `NoReverseMatch`.

- [ ] **Step 3: Implement the view**

```python
# courses/views_media.py
from courses.media_fetch import fetch_image_asset  # NOT `from courses import media_fetch`
                                                   # -- the module and the view share a
                                                   # name, and `def media_fetch` would
                                                   # rebind it at import.


@require_POST  # above @login_required: a non-POST is a 405 regardless of auth
@login_required
def media_fetch(request, slug):
    course = _require_manage(request, slug)
    try:
        asset = fetch_image_asset(
            course,
            request.POST.get("url") or "",          # .get, never bracket access
            request.user,
            name=(request.POST.get("name") or "").strip(),
        )
    except ValidationError as e:
        msg = "; ".join(e.messages)                 # not str(e) -- error_dict repr
        if not _wants_fragment(request):
            messages.error(request, msg)            # media_upload redirects SILENTLY;
            return redirect("courses:manage_media", slug=course.slug)  # this improves on it
        return render(request, "courses/manage/_op_error.html", {"message": msg}, status=422)
    if not _wants_fragment(request):
        return redirect("courses:manage_media", slug=course.slug)
    media_svc.attach_usage(asset)
    return render(request, "courses/manage/media/_asset_cell.html",
                  {"course": course, "asset": asset})
```

Add `from django.contrib import messages` if absent. Route in `courses/urls.py`:

```python
    path(
        "manage/courses/<slug:slug>/media/fetch/",
        views_media.media_fetch,
        name="manage_media_fetch",
    ),
```

- [ ] **Step 4: Run to verify it passes.** Expected: PASS.

- [ ] **Step 5: Falsify**

| Mutant | RED test |
|---|---|
| Swap the decorator order | `test_authenticated_get_is_405` |
| `request.POST["url"]` | `test_missing_url_key_is_422_not_500` |
| `request.POST["name"]` | `test_missing_name_key_succeeds` |
| `str(e)` instead of `"; ".join(e.messages)` | `test_rejection_is_422_with_the_message` |
| Drop `messages.error` | `test_no_js_failure_redirects_with_a_message` |

- [ ] **Step 6: Commit**

```bash
git add courses/views_media.py courses/urls.py tests/test_media_fetch_view.py
git commit -m "feat(media-fetch): manage_media_fetch view and route"
```

---

### Task 10: Templates + CSS

**Files:**
- Modify: `templates/courses/manage/media/manager.html`
- Modify: `templates/courses/manage/media/_picker.html`
- Modify: `templates/courses/manage/media/_asset_cell.html`
- Modify: `courses/static/courses/css/editor.css`
- Test: `tests/test_media_fetch_templates.py` *(new)*

- [ ] **Step 1: Write the failing tests**

⚠️ Same fixture warning as Task 9: build course/manager/assets in-module from factories.
The malformed-authority asset must be written with `.save()` / `update()` — `full_clean()`
would reject `https://[bad-ipv6/x.png` as a URLField, and the point of the test is a row
that already exists in that state.

```python
# tests/test_media_fetch_templates.py
import re

import pytest
from django.template.loader import render_to_string
from django.urls import reverse

from courses.models import MediaAsset
from tests.factories import CourseFactory
from tests.factories import MediaAssetFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


@pytest.fixture
def course_and_manager(client):
    # make_pa, NOT UserFactory + force_login -- see the note in Task 9's fixture.
    pa = make_pa(client, "pa")
    return CourseFactory(owner=pa), pa


def _fetched(course, source_url):
    asset = MediaAssetFactory(course=course, kind="image")
    # .update(), not .save(): a malformed authority would not survive full_clean(),
    # and the point is a row that is ALREADY in that state.
    MediaAsset.objects.filter(pk=asset.pk).update(source_url=source_url)
    asset.refresh_from_db()
    # attach_usage sets the img_uses/vid_uses/di_uses the cell template reads
    from courses import media as media_svc

    return media_svc.attach_usage(asset)


def test_video_picker_has_two_tabs_and_no_fetch_panel(course_and_manager):
    course, _ = course_and_manager
    html = render_to_string("courses/manage/media/_picker.html",
                            {"course": course, "kind": "video", "assets": []})
    assert html.count('class="picker__tab') == 2
    assert "data-picker-url" not in html


def test_image_picker_has_three_tabs_and_a_hidden_fetch_panel(course_and_manager):
    course, _ = course_and_manager
    html = render_to_string("courses/manage/media/_picker.html",
                            {"course": course, "kind": "image", "assets": []})
    assert html.count('class="picker__tab') == 3
    assert "data-picker-url" in html
    assert "data-msg-fetch-failed" in html
    # Every tab's data-tab must have a matching data-panel, or the delegated handler
    # (p.hidden = data-panel !== data-tab) hides EVERY panel on the first click.
    assert set(re.findall(r'data-tab="([^"]+)"', html)) == set(
        re.findall(r'data-panel="([^"]+)"', html)
    )
    # The panel MUST ship hidden -- without it it stacks on top of the library panel
    # until the first tab click, a visible layout break no other assertion catches.
    assert re.search(r'data-panel="fetch"[^>]*\shidden', html)
    # ...and its tab must NOT be is-on: exactly one tab is, the library one.
    assert html.count("is-on") == 1
    assert re.search(r'data-tab="library"[^>]*is-on|is-on[^>]*data-tab="library"', html)


def test_manager_form_posts_to_the_fetch_route(client, course_and_manager):
    course, _ = course_and_manager
    html = client.get(
        reverse("courses:manage_media", kwargs={"slug": course.slug})
    ).content.decode()
    fetch_url = reverse("courses:manage_media_fetch", kwargs={"slug": course.slug})
    # Scope to the NEW form. Bare substring checks all pass WITHOUT it: manager.html:20's
    # .media-upload already carries method="post", every .asset-del form in the included
    # grid carries method="post" + csrf_token, and the fetch URL appears in the
    # data-fetch-url attribute regardless.
    form = re.search(r'<form[^>]*class="media-fetch"[^>]*>.*?</form>', html, re.S)
    assert form, "no .media-fetch form rendered"
    markup = form.group(0)
    assert 'method="post"' in markup
    assert f'action="{fetch_url}"' in markup
    assert "csrfmiddlewaretoken" in markup
    assert 'name="url"' in markup and "data-fetch-submit" in markup
    # These two live on the .media-manager root, OUTSIDE the form
    assert "data-fetch-url" in html and "data-msg-fetch-failed" in html


def test_cell_renders_a_source_link_for_a_fetched_asset(course_and_manager):
    course, _ = course_and_manager
    url = "https://upload.wikimedia.org/Foo.png"
    asset = _fetched(course, url)
    html = render_to_string("courses/manage/media/_asset_cell.html",
                            {"course": course, "asset": asset})
    assert 'rel="noopener noreferrer"' in html
    assert 'target="_blank"' in html
    assert ">upload.wikimedia.org<" in html   # hostname is the LABEL
    assert url in html                        # full URL in title


def test_cell_renders_no_link_for_a_malformed_source(course_and_manager):
    course, _ = course_and_manager
    asset = _fetched(course, "https://[bad-ipv6/x.png")
    html = render_to_string("courses/manage/media/_asset_cell.html",
                            {"course": course, "asset": asset})
    assert "asset-source" not in html
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement the manager form**

In `manager.html`, immediately after the existing `.media-upload` form:

```html
<form class="media-fetch" method="post"
      action="{% url 'courses:manage_media_fetch' slug=course.slug %}">
  {% csrf_token %}
  <label class="field">{% trans "Image URL" %}
    <input type="url" name="url" required placeholder="https://…"></label>
  <label class="field">{% trans "Name" %} <span class="muted">({% trans "optional" %})</span>
    <input type="text" name="name"></label>
  <button class="btn" type="submit" data-fetch-submit>{% trans "Fetch" %}</button>
</form>
```

Add to the `.media-manager` root element:

```
data-fetch-url="{% url 'courses:manage_media_fetch' slug=course.slug %}"
data-msg-fetch-failed="{% trans 'Could not fetch that image.' %}"
```

- [ ] **Step 4: Implement the picker panel**

In `_picker.html`, add `data-fetch-url` and `data-msg-fetch-failed` to `.picker`, then —
**immediately after the Upload tab button and still inside `<div class="picker__tabs">`**
(pasted outside that wrapper the tab still counts in the template test but renders in the
wrong place):

```html
{% if kind == "image" %}
  <button type="button" class="picker__tab" data-tab="fetch">{% trans "From URL" %}</button>
{% endif %}
```

and, after the upload panel:

```html
{% if kind == "image" %}
  <div class="picker__panel" data-panel="fetch" hidden>
    <p class="muted">{% trans "Paste an image URL — fetched, added and selected." %}</p>
    <input type="url" class="input" data-picker-url placeholder="https://…">
    <button type="button" class="btn" data-picker-fetch>{% trans "Fetch" %}</button>
  </div>
{% endif %}
```

- [ ] **Step 5: Implement the cell link**

In `_asset_cell.html`, inside `.asset-foot`, **between the uses indicator and
`.asset-actions`** — the position is load-bearing, not free choice. `editor.css:752` makes
`.asset-foot` a `justify-content: space-between` flex row over exactly **two** children
today, and `editor.css:769` targets `.asset-foot > :first-child:not([open])` to give the
uses label `min-width: 0`. Inserting the link **first** would silently retarget that rule
away from the uses indicator; appending it **last** would push `.asset-actions` out of its
right-hand position. Middle insertion preserves both.

```html
{% if asset.source_host %}
  <a class="asset-source" href="{{ asset.source_url }}" title="{{ asset.source_url }}"
     target="_blank" rel="noopener noreferrer">{{ asset.source_host }}</a>
{% endif %}
```

Gate on `source_host`, **not** `source_url`: a malformed authority yields a truthy
`source_url` and an empty host, which would render a zero-width unlabelled link.

- [ ] **Step 6: CSS**

In `editor.css`, beside `.media-upload` (`:343`), add `.media-fetch` matching its layout
and styling for the picker panel's input + button. Use existing tokens — no new colours.

`.asset-source` needs its declarations **pinned**, because `.asset-foot` (`:752`) is
`display:flex; justify-content: space-between` and its comments at `:758-770` state it is
designed around exactly **two** children. A third child makes `space-between` push the link
to the centre, and flex items default to `min-width:auto` — the very failure the
`:first-child:not([open])` rule at `:769` exists to fix, and which by design does not match
the new middle child, so "truncating" alone will not truncate:

```css
.asset-source {
  min-width: 0; flex: 0 1 auto;
  margin-inline-start: auto;   /* keeps .asset-actions hard right */
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-size: var(--text-sm); color: var(--text-secondary);
}
```

`margin-inline-start: auto` preserves the existing two-child visual balance without changing
`.asset-foot`'s own `justify-content`, which every other cell still depends on.

- [ ] **Step 7: Run to verify it passes; falsify**

| Mutant | RED test |
|---|---|
| Drop the `{% if kind == "image" %}` guard | `test_video_picker_has_two_tabs_...` |
| `data-panel="url"` vs `data-tab="fetch"` | the tabs/panels set equality |
| Gate the cell link on `source_url` | `test_cell_renders_no_link_for_a_malformed_source` |
| Drop `method="post"` | `test_manager_form_posts_to_the_fetch_route` |

- [ ] **Step 8: Screenshot both surfaces, light AND dark**

Judge dark separately — do not assume it follows from light. Every view ships styled.

- [ ] **Step 9: Commit**

```bash
git add templates/courses/manage/media/ courses/static/courses/css/editor.css tests/test_media_fetch_templates.py
git commit -m "feat(media-fetch): manager form, picker tab, provenance link, styles"
```

---

### Task 11: JS client

**Files:**
- Modify: `courses/static/courses/js/media_picker.js`

- [ ] **Step 1: Implement `fetchPickerUrl` in the picker section**

```js
    // In-flight guard as a FLAG, not just a disabled button: the panel has a SECOND
    // activation route (Enter on [data-picker-url]) that never touches the button, so
    // DOM state alone lets two Enter presses create two duplicate assets.
    var fetchInFlight = false;

    function fetchPickerUrl(url) {
      var picker = overlay && overlay.querySelector(".picker");
      if (!picker || !url || fetchInFlight) return;
      var btn = overlay.querySelector("[data-picker-fetch]");
      fetchInFlight = true;
      if (btn) { btn.disabled = true; btn.setAttribute("aria-busy", "true"); }
      function done() {
        fetchInFlight = false;
        if (btn) { btn.disabled = false; btn.removeAttribute("aria-busy"); }
      }
      var fd = new FormData();
      fd.append("url", url);
      fetch(picker.getAttribute("data-fetch-url"), {
        method: "POST",
        headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
        body: fd,
      }).then(function (r) { return r.text().then(function (t) { return { status: r.status, text: t }; }); })
        .then(function (res) {
          var tmp = document.createElement("div"); tmp.innerHTML = res.text.trim();
          if (res.status !== 200 && res.status !== 201) {
            // Parse the fragment and flash its TEXT: _op_error.html is a full
            // <div class="op-error" role="alert">, and flash() sets textContent -- so
            // passing the raw body shows tags, and innerHTML would nest a second
            // role="alert" inside the flash's own.
            var err = tmp.querySelector(".op-error");
            var card = overlay && overlay.querySelector(".picker-card");  // NOT .picker
            // Guard like the model does (media_picker.js:161-162): the author can close
            // the picker during a 20s fetch, leaving overlay null, and flash() would then
            // throw on host.prepend() -- inside the promise chain, before .finally.
            if (card) {
              flash(card, (err && err.textContent.trim()) ||
                          msg(picker, "fetch-failed", "Could not fetch that image."));
            }
            return;
          }
          var cell = tmp.querySelector("[data-asset-id]");
          if (cell) selectAsset(cell.getAttribute("data-asset-id"),
                               cell.getAttribute("data-name"),
                               cell.getAttribute("data-url"));
        })
        .catch(function () {
          // The THIRD outcome. uploadPickerFile has no .catch at all, so without this
          // a network drop leaves the button disabled for the life of the page.
          var card = overlay && overlay.querySelector(".picker-card");
          if (card) flash(card, msg(picker, "fetch-failed", "Could not fetch that image."));
        })
        .finally(done);
    }
```

- [ ] **Step 2: Wire both activation routes**

Add to the existing delegated `document` click handler (`:126`):

```js
      var fetchBtn = e.target.closest("[data-picker-fetch]");
      if (fetchBtn && overlay.contains(fetchBtn)) {
        var box = overlay.querySelector("[data-picker-url]");
        fetchPickerUrl(box ? box.value.trim() : "");
        return;
      }
```

and an Enter handler (the panel has no `<form>`, so there is no implicit submission):

```js
    document.addEventListener("keydown", function (e) {
      if (!overlay || e.key !== "Enter") return;
      var box = e.target.closest("[data-picker-url]");
      if (!box || !overlay.contains(box)) return;
      e.preventDefault();
      fetchPickerUrl(box.value.trim());
    });
```

- [ ] **Step 3: Wire the manager**

Inside `wireManager(root)`, a **second** submit listener — the `.media-upload` path is
not generic (it early-returns unless a file input has files):

```js
    var fetchForm = root.querySelector(".media-fetch");
    if (fetchForm) {
      var mgrInFlight = false;
      fetchForm.addEventListener("submit", function (e) {
        e.preventDefault();
        if (mgrInFlight) return;
        var btn = fetchForm.querySelector("[data-fetch-submit]");
        mgrInFlight = true;
        if (btn) { btn.disabled = true; btn.setAttribute("aria-busy", "true"); }
        var fd = new FormData(fetchForm);
        fetch(root.dataset.fetchUrl, {
          method: "POST",
          headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
          body: fd,
        }).then(function (r) { return r.text().then(function (t) { return { status: r.status, text: t }; }); })
          .then(function (res) {
            var tmp = document.createElement("div"); tmp.innerHTML = res.text.trim();
            if (res.status === 200 || res.status === 201) {
              insertCell(res.text);
              fetchForm.reset();   // else the URL stays and one more click duplicates
              return;
            }
            var err = tmp.querySelector(".op-error");
            flash(root, (err && err.textContent.trim()) ||
                        msg(root, "fetch-failed", "Could not fetch that image."));
          })
          .catch(function () { flash(root, msg(root, "fetch-failed", "Could not fetch that image.")); })
          .finally(function () {
            mgrInFlight = false;
            if (btn) { btn.disabled = false; btn.removeAttribute("aria-busy"); }
          });
      });
    }
```

- [ ] **Step 4: Verify both surfaces by hand before committing**

Every other task has a run-and-falsify loop; this one is only exercised two tasks later by
the e2e, so a syntax error or a wrong selector would be committed and surface far from its
cause. Run the dev server, then:

1. Media manager -> paste an allow-listed image URL -> the cell appears **without a
   reload** and the URL box clears (`form.reset()`).
2. Unit editor -> add an Image element -> open the picker -> **From URL** tab -> paste the
   same URL -> the asset is selected into the element.
3. Paste an off-allow-list URL on both surfaces -> the **server's** message text appears in
   the flash, not the generic fallback.
4. Browser console clean on both.

(For 1-3, temporarily add your test host to `LIBLI_ALLOWED_IMAGE_FETCH_DOMAINS` in `.env`.)

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/media_picker.js
git commit -m "feat(media-fetch): picker and manager clients with in-flight guard"
```

---

### Task 12: i18n

**Files:** `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po` (+ `.mo`)

- [ ] **Step 1: Extract**

```bash
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

- [ ] **Step 2: Translate every new msgid in `pl`**

Suggested strings — match the repo's existing register:

| msgid | pl |
|---|---|
| Enter an image URL. | Podaj adres URL obrazu. |
| That URL is too long (maximum 500 characters). | Ten adres URL jest za długi (maksymalnie 500 znaków). |
| That does not look like a valid URL. | To nie wygląda na poprawny adres URL. |
| Image URLs must use https. | Adresy URL obrazów muszą używać https. |
| That image host is not on the allow-list. | Ten serwer obrazów nie znajduje się na liście dozwolonych. |
| The image host returned an invalid redirect. | Serwer obrazów zwrócił nieprawidłowe przekierowanie. |
| That URL redirects to a host that is not on the allow-list. | Ten adres przekierowuje do serwera spoza listy dozwolonych. |
| That URL redirects too many times. | Ten adres przekierowuje zbyt wiele razy. |
| Could not reach the image host. | Nie można połączyć się z serwerem obrazów. |
| Fetching the image took too long. | Pobieranie obrazu trwało zbyt długo. |
| The image host returned an error (status %(status)s). | Serwer obrazów zwrócił błąd (status %(status)s). |
| That URL did not return an image. | Ten adres nie zwrócił obrazu. |
| That image type is not allowed. | Ten typ obrazu nie jest dozwolony. |
| The fetched file is empty. | Pobrany plik jest pusty. |
| That URL did not return a usable image. | Ten adres nie zwrócił użytecznego obrazu. |
| That image's dimensions are too large. | Wymiary tego obrazu są zbyt duże. |
| Image URL | Adres URL obrazu |
| Fetch | Pobierz |
| From URL | Z adresu URL |
| Paste an image URL — fetched, added and selected. | Wklej adres URL obrazu — zostanie pobrany, dodany i wybrany. |
| Could not fetch that image. | Nie udało się pobrać tego obrazu. |

- [ ] **Step 3: Flip the parked xfail**

If `test_worker_message_renders_in_the_active_language` was marked `xfail` in Task 5
(because the Polish catalog did not exist yet), **remove the marker now** and re-run:

```
TEST_DATABASE_URL="postgres://libli@127.0.0.1:55433/libli_aifu" uv run pytest courses/tests/test_media_fetch_redirects.py
```

`strict=False` means a passing xfail reports XPASS, not a failure — so a forgotten marker is
permanently invisible, and this is the **only** coverage of the `params=` deferral rule the
spec calls mandatory. Do not skip this step.

- [ ] **Step 4: Check for fuzzies**

`makemessages` pre-fills a **wrong** translation as fuzzy for a similar msgid; clearing it
means deleting **both** the `#, fuzzy` line and the bogus `msgstr`. Verify **0 fuzzy**:

```bash
grep -c "#, fuzzy" locale/pl/LC_MESSAGES/django.po   # expect 0
```

- [ ] **Step 5: Compile and commit**

```bash
uv run python manage.py compilemessages
git add locale/
git commit -m "i18n(media-fetch): Polish translations for the URL fetch strings"
```

⚠️ If master has moved and `.mo` conflicts on the eventual merge: resolve by **regenerating**
(`makemessages` + `compilemessages`), never by hand-merging the binary.

---

### Task 13: E2E

**Files:** `tests/test_e2e_media_fetch.py` *(new)*

- [ ] **Step 1: Write the four scenarios**

⚠️ **Two module-local fixtures are mandatory and are NOT in any conftest.py.** Copy both
from `tests/test_e2e_media_manager.py:34-60`:

- `_allow_sync_orm_under_playwright` (session, autouse) sets `DJANGO_ALLOW_ASYNC_UNSAFE`.
  Without it, ORM-touching e2e setup raises `SynchronousOnlyOperation`.
- `_isolated_media` (autouse) redirects `MEDIA_ROOT` to `tmp_path` **before any asset
  exists**. This matters more for this feature than for any other: it *writes* fetched
  images, so without the redirect every e2e run drops real files into the working tree's
  `media/` directory.

Each test also carries `@pytest.mark.django_db(transaction=True)`, matching the sibling
e2e modules.

```python
# tests/test_e2e_media_fetch.py
import os

import pytest

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py -- it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """Redirect MEDIA_ROOT before any asset exists.

    THIS feature writes fetched image files, so without the redirect each run leaves
    real bytes in the working tree's media/ directory.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path

# The ACCEPTED fixture: an existing 17,883-byte PNG served by live_server's staticfiles
# handler, so the fetch is genuinely end-to-end over a real socket while staying
# hermetic. Derive the host from live_server.url -- never hardcode it: pytest-django
# resolves to "localhost", NOT 127.0.0.1, and a hardcoded numeric host would be
# rejected by the allow-list before a socket ever opened.
FIXTURE_PATH = "/static/core/img/learner.png"
# The REJECTED fixture must be a DIFFERENT url and must open no socket at all:
REJECT_URL = "https://example.com/x.png"   # off the allow-list -> validator fires first


def fixture_url(live_server):
    return f"{live_server.url}{FIXTURE_PATH}"


def test_manager_paste_adds_the_asset(page, live_server, ...):
    # assert the fixture serves 200 FIRST, so a staticfiles change fails loudly rather
    # than as a confusing fetch rejection
    assert page.request.get(fixture_url(live_server)).status == 200
    _open_manager(page, live_server, ...)
    page.fill(".media-fetch input[name=url]", fixture_url(live_server))
    page.click("[data-fetch-submit]")
    page.wait_for_selector(".asset-cell")
    ...


def test_picker_from_url_selects_into_an_image_element(page, live_server, ...):
    ...
    page.click('[data-tab="fetch"]')
    page.fill("[data-picker-url]", fixture_url(live_server))
    page.click("[data-picker-fetch]")
    ...


def test_rejected_url_shows_the_server_reason_in_the_picker_flash(page, live_server, ...):
    page.fill("[data-picker-url]", REJECT_URL)
    page.click("[data-picker-fetch]")
    flash = page.wait_for_selector(".picker-card .op-error")
    assert "allow-list" in flash.inner_text()


@pytest.mark.django_db(transaction=True)
def test_second_activation_while_in_flight_issues_no_second_request(page, live_server, ...):
    """Hold the window open deliberately -- the loopback fixture completes in single-
    digit ms, so a plain double-click observes one request either way and passes GREEN
    with no guard at all.

    The hold must NOT be `page.wait_for_timeout` inside the route handler: with the sync
    API, handlers are dispatched on the SAME thread that runs the test, so sleeping there
    blocks the dispatcher and the ordering of the assertions below relative to the hold
    is not guaranteed -- `len(calls) == 1` would then pass vacuously. Arm the route and
    release it explicitly instead.
    """
    import threading

    calls = []
    release = threading.Event()

    # Hold the window open SERVER-SIDE, not in a route handler. playwright-python's
    # sync API is greenlet-based on a SINGLE OS thread, so a blocking wait inside a
    # route handler freezes the dispatcher: the test greenlet never resumes,
    # release.set() can never run, and the handler only unblocks at its timeout -- by
    # which point the button is re-enabled and `assert is_disabled()` fails on a
    # CORRECT build. live_server runs in-process, so blocking Django's worker thread
    # instead leaves Playwright fully responsive.
    real_open = media_fetch._open

    def blocking_open(req, timeout):
        release.wait(10)
        return real_open(req, timeout)

    monkeypatch.setattr(media_fetch, "_open", blocking_open)
    # Count requests with a NON-blocking route handler.
    page.route("**/media/fetch/", lambda r: (calls.append(r.request.url), r.continue_()))

    page.fill("[data-picker-url]", fixture_url(live_server))
    page.click("[data-picker-fetch]")

    btn = page.locator("[data-picker-fetch]")
    expect(btn).to_be_disabled()                   # the guard's visible expression
    # force=True: Playwright's actionability check includes ENABLED, so a plain click()
    # would block until timeout on a CORRECT build -- inverting the assertion.
    btn.click(force=True)
    page.locator("[data-picker-url]").press("Enter")   # the SECOND activation route,
                                                       # which bypasses the button
    assert len(calls) == 1
    release.set()
    # The picker's real success signal: selectAsset closes the modal. There is no
    # .asset-cell on the editor page (the grid left with the overlay) and no
    # .picker-card either, so waiting on those would hang to timeout.
    page.wait_for_selector(".picker-overlay", state="detached")


@pytest.mark.django_db(transaction=True)
def test_manager_second_submit_while_in_flight_issues_no_second_request(page, live_server, ...):
    """The manager half. Task 11 gives it a SEPARATE mgrInFlight flag on a SEPARATE
    listener, so the picker test above does not cover it -- removing the manager guard
    (and with it form.reset()'s duplicate protection) would otherwise pass everything.
    """
    import threading

    calls = []
    release = threading.Event()
    real_open = media_fetch._open

    def blocking_open(req, timeout):
        release.wait(10)
        return real_open(req, timeout)

    _open_manager(page, live_server, "pa-fetch", course)
    monkeypatch.setattr(media_fetch, "_open", blocking_open)   # server-side hold, per above
    page.route("**/media/fetch/", lambda r: (calls.append(r.request.url), r.continue_()))

    page.fill(".media-fetch input[name=url]", fixture_url(live_server))
    page.click("[data-fetch-submit]")
    expect(page.locator("[data-fetch-submit]")).to_be_disabled()
    page.locator("[data-fetch-submit]").click(force=True)
    assert len(calls) == 1
    release.set()
    page.wait_for_selector(".asset-cell")
    # form.reset() ran, so a further submit cannot silently duplicate the asset
    assert page.input_value(".media-fetch input[name=url]") == ""
    # form.reset() ran, so a further submit cannot silently duplicate the asset
    assert page.input_value(".media-fetch input[name=url]") == ""
```

⚠️ **`_open_manager` is not in `tests/conftest.py`** — that file holds only element-editor
openers (matchpair, stepper, markdone, choice, switchgate, `open_element_editor`). The
helpers this module needs are **module-local in the two sibling e2e files** and must be
copied from them:

- `tests/test_e2e_media_manager.py` — `_login` (`:72`), `_seed` (`:80`), `_open_manager`
  (`:96`), `_seed_assets` (`:102`).
- `tests/test_e2e_media_picker.py` — `_login`, `_setup`, `_add_and_pick` for the editor
  picker flow.

Copy the pair you need verbatim (they use `make_verified_user` plus the real allauth login
form, then `goto(manage_media)` or `[data-pick-media]`). **Scenarios (b) and (c) also need
that setup written out** — as sketched above they begin mid-flow on a page that was never
navigated and a picker that was never opened.

Import `expect` from `playwright.sync_api` for the disabled-state assertions (the sibling
e2e modules do the same), and take `monkeypatch` as a fixture in the two in-flight tests.

- [ ] **Step 2: Run**

```
TEST_DATABASE_URL="postgres://libli@127.0.0.1:55433/libli_aifu" uv run pytest tests/test_e2e_media_fetch.py -m e2e
```

Without `-m e2e` every test is deselected and you get exit 5 with no failures — which
looks like success. Grep the summary line.

- [ ] **Step 3: Falsify**

| Mutant | RED test |
|---|---|
| Remove `localhost` from `test.py`'s allow-list | scenarios (a), (b), (d) |
| Remove the **picker** in-flight flag | scenario (d), picker test |
| Remove the **manager** `mgrInFlight` flag | scenario (d), manager test |
| Drop `form.reset()` | the manager test's final `input_value` assertion |
| Flash into `.picker` instead of `.picker-card` | scenario (c) |
| Drop the Enter handler | the picker test's `press("Enter")` half |
| Guard only via `disabled` (no JS flag) | the picker test's `press("Enter")` half |
| Drop `_isolated_media` | no test — verify by hand that `media/` stays clean after a run |

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_media_fetch.py
git commit -m "test(media-fetch): e2e for manager, picker, rejection and in-flight guard"
```

---

### Task 14: LAL interaction + branch gate

**Files:** `courses/tests/test_media_fetch_lal.py` *(new)*

- [ ] **Step 1: Write the LAL interaction test**

```python
# courses/tests/test_media_fetch_lal.py
import pytest
from django.test import override_settings

from courses import media_fetch
from courses.lal_loader.media import get_or_create_asset
from courses.models import MediaAsset
from courses.tests.test_media_fetch_transport import FakeResponse
from courses.tests.test_media_fetch_transport import png_bytes
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db
WIKI = ["upload.wikimedia.org"]


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_lal_import_reuses_a_byte_identical_fetched_asset(monkeypatch, tmp_path):
    """Populating content_hash is NOT behaviour-neutral: lal_loader/media.py:40 already
    dedups on (course, content_hash), so a later LAL import of identical bytes now
    reuses the fetched row, inheriting its name and source_url. Intended -- but a real
    behaviour change, so it is pinned here rather than discovered later.

    Exactly ONE fetched asset: .first() runs on an UNORDERED queryset, so with two
    identical-hash rows this would silently assert on DB order.

    The LAL side goes through the REAL loader, not a shared digest helper -- otherwise
    both sides compute the hash the same way by construction and the test would still
    pass if the digest form diverged from lal_loader/media.py:33.
    """
    course = CourseFactory()
    data = png_bytes()
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: FakeResponse(data))

    fetched = media_fetch.fetch_image_asset(
        course, "https://upload.wikimedia.org/Foo.png", UserFactory(), name="My picture"
    )

    # get_or_create_asset reads bytes from a FILESYSTEM PATH, not a file object --
    # write the identical bytes out and drive the real loader.
    path = tmp_path / "Foo.png"
    path.write_bytes(data)
    reused = get_or_create_asset(course, "image", path)

    assert reused.pk == fetched.pk
    assert MediaAsset.objects.filter(course=course).count() == 1
    assert reused.name == "My picture"        # inherited, as documented
    assert reused.source_url == "https://upload.wikimedia.org/Foo.png"
```

⚠️ Check `get_or_create_asset`'s real signature at `courses/lal_loader/media.py:36` before
writing this — if it takes `(course, kind, path)` in a different order, match the source,
not this snippet.

- [ ] **Step 2: Run and falsify**

Mutant: change the digest to `.digest()` or uppercase hex → the reuse assertion goes RED.

- [ ] **Step 3: Branch-wide gate**

Only now, as a branch gate rather than a per-task step:

```bash
uv run ruff format .                      # LAST, after every other edit
uv run ruff check --no-cache .
uv run python manage.py makemigrations --check --dry-run
TEST_DATABASE_URL="postgres://libli@127.0.0.1:55433/libli_aifu" uv run pytest
TEST_DATABASE_URL="postgres://libli@127.0.0.1:55433/libli_aifu" uv run pytest -m e2e
```

Grep both summary lines. `ruff format --check` is a separate CI gate from `ruff check`.

- [ ] **Step 4: Commit**

```bash
git add -A courses/tests/test_media_fetch_lal.py
git commit -m "test(media-fetch): LAL content-hash reuse interaction"
```

---

## Self-Review

**Spec coverage.** §0 transport → T4. §1 validator → T1. §2 settings → T1. §3 fetch service:
constants/seam/thread/box → T4; redirects/status → T5; content-type/cap/empty → T6;
Pillow/pixel/filename → T7; deadline → T8; logging → T4 (`_log_worker_failure`) with tokens
raised in T5–T7. §4 view/route → T9. §5 templates + CSS → T10. §6 client → T11. Data
(field/migration/property) → T2; `create_asset`/`replace_asset` → T3; LAL interaction → T14;
no-export → nothing to do, asserted by the absence of a `FORMAT_VERSION` change. Error table
→ T5/T6/T7/T9. Testing → T1–T14. i18n → T12. Deployment note → no code.

**Placeholder scan.** The only deliberate stubs are `...` inside test fixture wiring where
the repo's existing factories/openers must be matched — flagged inline at each site. No TBDs.

**Type consistency.** `validate_fetch_url(url) -> str` (T1) is consumed as an assignment in
T4. `fetch_image_asset(course, submitted_url, user, name="")` is called with that exact
signature in T9. `create_asset(..., source_url="", content_hash="")` (T3) is called with both
kwargs in T4. `MediaAsset.source_host` (T2) is used in T10's template and T10's test.
`_open(request, timeout)` is the patch target in every T4–T8 test.
