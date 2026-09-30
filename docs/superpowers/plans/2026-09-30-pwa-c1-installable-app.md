# PWA C1 — installable app, service worker, offline page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make libli installable as a branded app per school, with a hand-written service worker that caches only `/static/`, shows an offline page when the network is gone, and can be recalled from every device by an env-var kill switch.

**Architecture:** A new `core/pwa.py` owns every decision (version hash, manifest detection, branding read, passthrough constants, which worker to serve). Two new public views render templates: `/sw.js` (the normal worker or the kill worker, always 200, `no-cache`) and `/offline/` (a standalone page with no user data). `core/static/core/js/pwa.js` registers the worker and drives an "Install app" item in the account menu. The install guide is a new entry in the existing public-pages registry.

**Tech Stack:** Django 5.2 templates and views, vanilla JS (no build step), whitenoise `CompressedManifestStaticFilesStorage` in production, pytest + pytest-django, Playwright 1.60 (pytest-playwright 0.8, Chromium) for e2e.

**Spec:** `docs/superpowers/specs/2026-09-29-pwa-c1-installable-app-design.md` — read it alongside this plan. Its owner-decisions table D1–D10 is VERBATIM and binding; no task may reverse a row of it.

## Global Constraints

- Settings: `PWA_ENABLED = env.bool("LIBLI_PWA_ENABLED", default=False)` in `base.py`, `default=True` in `production.py`; `PWA_KILL_SWITCH = env.bool("LIBLI_PWA_KILL_SWITCH", default=False)`; `PWA_CACHE_UNHASHED_STATIC = False` (not env-backed); `test.py` pins `PWA_ENABLED = False` and `PWA_KILL_SWITCH = False`.
- `/sw.js` is ALWAYS HTTP 200, `Content-Type: text/javascript; charset=utf-8`, `Cache-Control: no-cache`. Normal worker only when `PWA_ENABLED and not PWA_KILL_SWITCH`; every other combination serves the kill worker.
- Cache names: `libli-static-<VERSION>`, `libli-offline-<VERSION>`; every libli cache starts with `libli-`.
- `PASSTHROUGH_PREFIXES = ("/media/",)`, `PASSTHROUGH_SUFFIXES = ("/export/",)`, `PRECACHE = ("/offline/",)`; matching on `new URL(request.url).pathname` only.
- The worker never caches pages (HTML) or `/media/` (D6). No `navigationPreload`.
- `offline_branding()` NEVER calls `Institution.load()` and never reads `get_site_config()`.
- `core/offline.html` never `{% include %}`s or `{% extends %}`s anything and references no `/static/` URL.
- Worker template JS lives inside `{% verbatim %}`; values arrive as `json.dumps(...)` strings emitted with `|safe`.
- The kill worker carries the marker comment `LIBLI_SW_KILL`; the normal worker never contains `LIBLI_SW_KILL`, `unregister` or `navigationPreload`.
- The `beforeinstallprompt` listener calls `preventDefault()` FIRST, unconditionally (D3: no banner, no auto-prompt).
- No migration, no new dependency, no `deploy.sh` change.
- Test runs: never pass `-q` (addopts has it); `-m e2e` is mandatory for Playwright tests; start the test-DB container before any pytest run; run tests scoped to the task's files — the whole-repo sweep is the branch gate (Task 11) only.
- i18n: `uv run python manage.py makemessages -l pl -l en --no-obsolete`; overwrite EVERY new pl `msgstr` from the table in Task 7 (makemessages fuzzy-prefills wrong translations); clear each `#, fuzzy` flag AND its `#| msgid` line; `uv run python manage.py compilemessages`; commit both `.po` and `.mo` for `en` and `pl`.
- Before EVERY task's commit step: `uv run ruff format <the task's .py files>` then `uv run ruff check --no-cache <the task's .py files>`, both clean (E501 is 88 columns; split long JS string literals with implicit concatenation).
- Mutants: every "mutant" step edits the file BY HAND and reverts BY HAND (never `git checkout`/`git restore` on a file carrying uncommitted work); read the `git diff` after applying each mutant to confirm it applied.

## Review Focus

1. **A rename of the school while pupils have the app open.** They expect the next page they open to show the new name, and no flip-flopping between old and new workers across gunicorn processes. Pinned by Task 1's `test_version_follows_a_signal_free_rename` (DB, not cache) and Task 10's e2e 5.
2. **A deploy (~24 s of Caddy 503) while a pupil clicks.** They expect the maintenance page, not "you're offline". Pinned by Task 10 e2e 3 (a real HTTP error passes through) and the mutant "fallback on any non-ok response".
3. **A teacher downloading a course export (up to ~1 GiB) or opening a video.** They expect the download or seek to behave exactly as without the worker. Pinned by Task 3's passthrough route test and Task 10 e2e 4.
4. **A pupil on a shared school computer after someone else logged out.** They expect no trace of the previous user in anything the worker stored. Pinned by Task 2's `test_offline_page_never_shows_the_requesting_user`.
5. **An operator pulling the kill switch in an emergency.** They expect it to take effect on the next visit and to be verifiable from outside. Pinned by Task 3's kill-row tests, Task 8's runbook guard and Task 10 e2e 6.

---

### Task 1: Settings, `core/pwa.py` and the `pwa_enabled` context flag

**Files:**
- Modify: `config/settings/base.py` (next to `VENDOR_INSTANCE`, ~line 289)
- Modify: `config/settings/production.py` (after the transport-security block)
- Modify: `config/settings/test.py` (after `VENDOR_INSTANCE = False`)
- Create: `core/pwa.py`
- Modify: `core/context_processors.py` (append a `pwa` function)
- Modify: `config/settings/base.py` `TEMPLATES[0]["OPTIONS"]["context_processors"]` (append `"core.context_processors.pwa"`)
- Test: `tests/test_pwa_core.py`

**Interfaces:**
- Consumes: `core.services._safe_color(value) -> str | None`, `core.services.effective_primary(cfg: dict) -> str`, `core.services.default_name() -> str`, `core.services.PRIMARY_DEFAULT: str`, `institution.models.Institution`, `BrandColor` (related name `brand_colors`, fields `key`, `value`).
- Produces (`core/pwa.py`): `PASSTHROUGH_PREFIXES: tuple[str, ...]`, `PASSTHROUGH_SUFFIXES: tuple[str, ...]`, `PRECACHE: tuple[str, ...]`, `NO_MANIFEST: bytes`, `_storage() -> Storage`, `_manifest_bytes() -> bytes` (lru_cached; has `.cache_clear()`), `cache_static() -> bool`, `serve_normal() -> bool`, `offline_branding() -> tuple[str, str]` (name, primary), `worker_version() -> str` (12 hex chars). Context key `pwa_enabled: bool`.
- Note: `worker_version()` hashes the SOURCE of `core/sw.js` and `core/offline.html`. Those templates are created in Tasks 2 and 3; Task 1 creates both as minimal placeholders so the hash works, and Tasks 2/3 replace them.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pwa_core.py`:

```python
"""PWA C1 core decisions (core/pwa.py) and the pwa_enabled context flag."""

import io

import pytest
from django.urls import reverse

from core import pwa
from core.services import PRIMARY_DEFAULT
from core.services import default_name
from core.services import get_site_config
from institution.models import BrandColor
from institution.models import Institution

pytestmark = pytest.mark.django_db


class _ManifestStorage:
    """Stands in for CompressedManifestStaticFilesStorage: only the surface
    _manifest_bytes() reads."""

    manifest_name = "staticfiles.json"

    def __init__(self, data):
        self.data = data

    def exists(self, name):
        return name == self.manifest_name

    def open(self, name):
        return io.BytesIO(self.data)


class _PlainStorage:
    """Stands in for StaticFilesStorage: no manifest_name at all."""


@pytest.fixture(autouse=True)
def _fresh_manifest_cache():
    pwa._manifest_bytes.cache_clear()
    yield
    pwa._manifest_bytes.cache_clear()


@pytest.fixture
def storage(monkeypatch):
    def _use(obj):
        pwa._manifest_bytes.cache_clear()
        monkeypatch.setattr(pwa, "_storage", lambda: obj)

    return _use


def test_plain_storage_has_no_manifest(storage):
    storage(_PlainStorage())
    assert pwa._manifest_bytes() == pwa.NO_MANIFEST


def test_manifest_storage_bytes_are_read(storage):
    storage(_ManifestStorage(b'{"paths": {"a.css": "a.123.css"}}'))
    assert pwa._manifest_bytes() == b'{"paths": {"a.css": "a.123.css"}}'


def test_manifest_name_without_the_file_is_no_manifest(storage):
    class _Missing(_ManifestStorage):
        def exists(self, name):
            return False

    storage(_Missing(b"x"))
    assert pwa._manifest_bytes() == pwa.NO_MANIFEST


def test_manifest_is_read_through_manifest_storage_when_present(storage):
    inner = _ManifestStorage(b"via-manifest-storage")

    class _Outer(_ManifestStorage):
        manifest_storage = inner

        def exists(self, name):
            return False  # the outer storage must NOT be the one consulted

    storage(_Outer(b"outer"))
    assert pwa._manifest_bytes() == b"via-manifest-storage"


def test_cache_static_is_false_without_a_manifest(storage, settings):
    settings.PWA_CACHE_UNHASHED_STATIC = False
    storage(_PlainStorage())
    assert pwa.cache_static() is False


def test_cache_static_is_true_with_the_test_override(storage, settings):
    settings.PWA_CACHE_UNHASHED_STATIC = True
    storage(_PlainStorage())
    assert pwa.cache_static() is True


def test_cache_static_is_true_with_a_manifest(storage, settings):
    settings.PWA_CACHE_UNHASHED_STATIC = False
    storage(_ManifestStorage(b"{}"))
    assert pwa.cache_static() is True


@pytest.mark.parametrize(
    "enabled,kill,expected",
    [(True, False, True), (True, True, False), (False, False, False), (False, True, False)],
)
def test_serve_normal_truth_table(settings, enabled, kill, expected):
    settings.PWA_ENABLED = enabled
    settings.PWA_KILL_SWITCH = kill
    assert pwa.serve_normal() is expected


def test_offline_branding_without_an_institution_row_creates_nothing():
    Institution.objects.all().delete()
    assert pwa.offline_branding() == (default_name(), PRIMARY_DEFAULT)
    assert Institution.objects.count() == 0


def test_offline_branding_strips_and_falls_back_on_a_blank_name():
    inst = Institution.load()
    Institution.objects.filter(pk=inst.pk).update(name="   ")
    assert pwa.offline_branding()[0] == default_name()


def _set_primary(inst, value):
    # institution/migrations/0002_seed_branding.py SEEDS the primary row and
    # BrandColor is unique on (institution, key): update it, never create() it.
    # update() is also signal-free, so the site-config cache is left stale.
    BrandColor.objects.filter(institution=inst, key="primary").update(value=value)


def test_offline_branding_reads_the_primary_brand_colour():
    inst = Institution.load()
    _set_primary(inst, "#123456")
    assert pwa.offline_branding()[1] == "#123456"


def test_offline_branding_rejects_an_invalid_colour():
    inst = Institution.load()
    # Signal-free write of a value the validator would refuse.
    _set_primary(inst, "red;}")
    assert pwa.offline_branding()[1] == PRIMARY_DEFAULT


def test_version_follows_a_signal_free_rename():
    """The DB, not the per-process site-config cache: warm the cache, then write
    with update() (no post_save, so the cache really is stale). Reading
    get_site_config() instead would leave the version unchanged."""
    inst = Institution.load()
    get_site_config()  # warm
    before = pwa.worker_version()
    Institution.objects.filter(pk=inst.pk).update(name="Fresh Name School")
    assert get_site_config()["name"] != "Fresh Name School"  # cache is stale
    assert pwa.offline_branding()[0] == "Fresh Name School"
    assert pwa.worker_version() != before


def test_version_follows_a_signal_free_recolour():
    inst = Institution.load()
    _set_primary(inst, "#112233")
    get_site_config()  # warm
    before = pwa.worker_version()
    _set_primary(inst, "#445566")
    assert pwa.offline_branding()[1] == "#445566"
    assert pwa.worker_version() != before


def test_version_follows_the_manifest_bytes(storage):
    storage(_ManifestStorage(b"one"))
    first = pwa.worker_version()
    storage(_ManifestStorage(b"two"))
    assert pwa.worker_version() != first


def test_version_is_stable_with_nothing_changed():
    Institution.load()
    assert pwa.worker_version() == pwa.worker_version()
    assert len(pwa.worker_version()) == 12
    int(pwa.worker_version(), 16)  # hex


def test_context_flag_on_only_in_the_first_row(client, settings):
    settings.PWA_ENABLED = True
    settings.PWA_KILL_SWITCH = False
    assert client.get(reverse("account_login")).context["pwa_enabled"] is True
    settings.PWA_KILL_SWITCH = True
    assert client.get(reverse("account_login")).context["pwa_enabled"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_pwa_core.py`
Expected: collection ERROR, `ImportError: cannot import name 'pwa' from 'core'`.

- [ ] **Step 3: Add the settings**

In `config/settings/base.py`, directly after the `VENDOR_INSTANCE = env.bool(...)` line, add:

```python

# PWA (docs/superpowers/specs/2026-09-29-pwa-c1-installable-app-design.md). Off
# unless production.py turns it on: a service worker registered on a dev origin
# outlives the code that registered it. The kill switch makes /sw.js serve a
# worker that deletes libli's caches and unregisters itself.
PWA_ENABLED = env.bool("LIBLI_PWA_ENABLED", default=False)
PWA_KILL_SWITCH = env.bool("LIBLI_PWA_KILL_SWITCH", default=False)
# Test-only: cache /static/ even without a staticfiles manifest (the e2e suite has
# none). Never env-backed -- without a manifest the worker's version does not track
# static content, so a developer's JS/CSS edits would freeze.
PWA_CACHE_UNHASHED_STATIC = False
```

In `config/settings/production.py`, after the `if env.bool("DJANGO_BEHIND_PROXY"...` block, add:

```python

# --- PWA --- on by default in production; "LIBLI_PWA_ENABLED=" (blank) parses as off.
PWA_ENABLED = env.bool("LIBLI_PWA_ENABLED", default=True)  # noqa: F405
```

In `config/settings/test.py`, after `VENDOR_INSTANCE = False`, add:

```python

# Pinned for the same reason as VENDOR_INSTANCE: base.py reads a developer's .env.
# Tests that exercise the worker opt in with the settings fixture.
PWA_ENABLED = False
PWA_KILL_SWITCH = False
```

- [ ] **Step 4: Create `core/pwa.py`**

```python
"""Service-worker decisions for the PWA (spec:
docs/superpowers/specs/2026-09-29-pwa-c1-installable-app-design.md).

Everything the worker's behaviour depends on is decided here, once: which body
/sw.js serves, the version that retires old caches, whether /static/ may be
cached, and what the offline page shows."""

import functools
import hashlib

from django.conf import settings
from django.core.files.storage import storages
from django.template.loader import get_template

from core.services import PRIMARY_DEFAULT
from core.services import _safe_color
from core.services import default_name
from core.services import effective_primary

# Paths the worker never touches, not even as navigations: /media/ keeps HTTP
# Range for video seeking and keeps GBs of media out of the cache; /export/ is the
# course/subtree archive download (up to ~1 GiB) and the analytics CSV.
PASSTHROUGH_PREFIXES = ("/media/",)
PASSTHROUGH_SUFFIXES = ("/export/",)
PRECACHE = ("/offline/",)
NO_MANIFEST = b"nomanifest"

_VERSIONED_TEMPLATES = ("core/sw.js", "core/offline.html")


def _storage():
    return storages["staticfiles"]


@functools.lru_cache(maxsize=1)
def _manifest_bytes():
    """The staticfiles manifest's bytes, or NO_MANIFEST. THE one place that decides
    whether the storage has a manifest. Memoised per process: the manifest cannot
    change without a restart."""
    storage = _storage()
    name = getattr(storage, "manifest_name", None)
    if not name:
        return NO_MANIFEST
    reader = getattr(storage, "manifest_storage", None) or storage
    if not reader.exists(name):
        return NO_MANIFEST
    with reader.open(name) as fh:
        return fh.read()


def cache_static():
    return _manifest_bytes() != NO_MANIFEST or settings.PWA_CACHE_UNHASHED_STATIC


def serve_normal():
    """First row of the spec's §1 table; every other row serves the kill worker."""
    return bool(settings.PWA_ENABLED and not settings.PWA_KILL_SWITCH)


def offline_branding():
    """(name, primary) for the offline page, read from the DATABASE.

    Never get_site_config(): that cache is per-process with a 300 s TTL, so after
    a rename different gunicorn workers would serve different /sw.js bytes and a
    device could flip between versions. Never Institution.load(): that is
    get_or_create, a write on an anonymous GET."""
    from institution.models import Institution

    inst = Institution.objects.filter(pk=1).prefetch_related("brand_colors").first()
    if inst is None:
        return default_name(), PRIMARY_DEFAULT
    colors = {c.key: c.value for c in inst.brand_colors.all()}
    name = (inst.name or "").strip() or default_name()
    return name, effective_primary({"primary": _safe_color(colors.get("primary"))})


def worker_version():
    # Not hashed: the compiled .mo catalogs. A release that changes ONLY the
    # offline page's translations leaves devices on the old wording until the next
    # VERSION change -- accepted in the spec (§2, beside the language-switch note).
    h = hashlib.sha256()
    h.update(_manifest_bytes())
    for name in _VERSIONED_TEMPLATES:
        h.update(b"\0")
        h.update(get_template(name).template.source.encode())
    for value in offline_branding():
        h.update(b"\0")
        h.update(str(value).encode())
    return h.hexdigest()[:12]
```

Create the two placeholder templates so `worker_version()` can read them (Tasks 2 and 3 replace their contents):

`templates/core/sw.js`:

```
{# PWA worker -- replaced in Task 3. #}
```

`templates/core/offline.html`:

```
{# Offline page -- replaced in Task 2. #}
```

- [ ] **Step 5: Add the context processor**

Append to `core/context_processors.py`:

```python


def pwa(request):
    """`pwa_enabled`: include pwa.js (register the worker) only in the first row of
    the spec's §1 table -- with the kill switch on, nothing may re-register."""
    from core.pwa import serve_normal

    return {"pwa_enabled": serve_normal()}
```

In `config/settings/base.py`, append `"core.context_processors.pwa",` after `"core.context_processors.support_availability",` in the `context_processors` list.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_pwa_core.py`
Expected: all PASS (grep the summary line for `passed` and `0 failed`; the exit code alone can lie).

- [ ] **Step 7: Mutants (each must turn a named test RED; revert by hand)**

1. In `offline_branding`, replace the body with `cfg = get_site_config(); return (cfg["name"], effective_primary(cfg))` (import `get_site_config`) → RED: `test_version_follows_a_signal_free_rename`, `test_version_follows_a_signal_free_recolour`.
2. Replace `Institution.objects.filter(pk=1)...first()` with `Institution.load()` → RED: `test_offline_branding_without_an_institution_row_creates_nothing`.
3. Change `reader = getattr(...) or storage` to `reader = storage` → RED: `test_manifest_is_read_through_manifest_storage_when_present`.
4. Drop `h.update(_manifest_bytes())` → RED: `test_version_follows_the_manifest_bytes`.

Run: `uv run python -m pytest tests/test_pwa_core.py` after each; restore by hand; re-run green.

- [ ] **Step 8: Commit**

```bash
git add config/settings/base.py config/settings/production.py config/settings/test.py core/pwa.py core/context_processors.py templates/core/sw.js templates/core/offline.html tests/test_pwa_core.py
git commit -m "feat(pwa): settings, core/pwa.py decisions and the pwa_enabled flag"
```

---

### Task 2: The `/offline/` page

**Files:**
- Modify: `core/views.py` (add `offline` view)
- Modify: `core/urls.py` (add route)
- Replace: `templates/core/offline.html`
- Test: `tests/test_pwa_offline.py`

**Interfaces:**
- Consumes: `core.pwa.offline_branding() -> (name, primary)`.
- Produces: route `core:offline` at `/offline/`; view `core.views.offline(request)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pwa_offline.py`:

```python
"""PWA C1: the standalone offline page (spec §4)."""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.template.loader import get_template
from django.urls import reverse

from institution.models import Institution
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db

FAVICON_SVG = Path(settings.BASE_DIR) / "core/static/core/img/favicon/favicon.svg"


def test_offline_is_public_uncached_and_unindexed(client):
    r = client.get(reverse("core:offline"))
    assert r.status_code == 200
    assert r["Cache-Control"] == "no-store"
    assert r["X-Robots-Tag"] == "noindex"


def test_offline_page_never_shows_the_requesting_user(client):
    user = make_verified_user(
        username="offline-probe-user", email="offline-probe@probe.example.com"
    )
    client.force_login(user)
    body = client.get(reverse("core:offline")).content.decode()
    assert "offline-probe-user" not in body
    assert "offline-probe@probe.example.com" not in body
    assert "bell" not in body  # the notification bell's markup
    assert "data-account-menu" not in body


def test_offline_page_loads_nothing_from_static(client):
    body = client.get(reverse("core:offline")).content.decode()
    assert "/static/" not in body
    assert not re.search(r'<(script|link)[^>]+(src|href)=', body)


def test_offline_page_shows_the_current_name(client):
    inst = Institution.load()
    Institution.objects.filter(pk=inst.pk).update(name="Szkoła Testowa")
    assert "Szkoła Testowa" in client.get(reverse("core:offline")).content.decode()


def test_offline_template_is_self_contained():
    source = get_template("core/offline.html").template.source
    assert "{% include" not in source
    assert "{% extends" not in source


def test_offline_mark_matches_the_favicon():
    """The inlined libli mark must not drift from the shipped favicon."""
    source = get_template("core/offline.html").template.source
    for line in FAVICON_SVG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(("<rect", "<circle")):
            assert line in source, line


def test_offline_button_uses_the_primary_only_as_a_border(client):
    body = client.get(reverse("core:offline")).content.decode()
    assert "border-color: #147E78" in body or "border-color:#147E78" in body
    assert "location.reload()" in body
    assert 'addEventListener("online"' in body
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_pwa_offline.py`
Expected: FAIL with `NoReverseMatch: Reverse for 'offline' not found`.

- [ ] **Step 3: Add the view and route**

In `core/views.py` add the imports `from django.template.loader import render_to_string` and `from core.pwa import offline_branding`, then add:

```python
def offline(request):
    """The worker's offline fallback (spec §4). Rendered WITHOUT the request, so
    no context processor runs and nothing about the user can reach the page: it is
    cached on the device and shown to whoever uses it next."""
    name, primary = offline_branding()
    html = render_to_string(
        "core/offline.html", {"school_name": name, "primary": primary}
    )
    response = HttpResponse(html)
    response["Cache-Control"] = "no-store"
    response["X-Robots-Tag"] = "noindex"
    return response
```

In `core/urls.py`, after the `site.webmanifest` route, add:

```python
    path("offline/", views.offline, name="offline"),
```

- [ ] **Step 4: Replace `templates/core/offline.html`**

```html
{% load i18n %}{% get_current_language as LANGUAGE_CODE %}<!DOCTYPE html>
<html lang="{{ LANGUAGE_CODE }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <title>{% trans "You're offline" %} · {{ school_name }}</title>
  {% comment %}
  Standalone on purpose (spec §4): no base.html, no include, no static file. The
  worker caches this page and shows it to whoever holds the device, and VERSION
  hashes this file's source -- an included file would change without moving it.
  {% endcomment %}
  <style>
    :root { --bg: #F4F1EA; --text: #1A1816; --muted: #5B5650; }
    @media (prefers-color-scheme: dark) {
      :root { --bg: #1A1816; --text: #F4F1EA; --muted: #B8B2A8; }
    }
    html, body { margin: 0; background: var(--bg); color: var(--text);
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
    main { max-width: 28rem; margin: 18vh auto 0; padding: 0 1.5rem; text-align: center; }
    svg { width: 4rem; height: 4rem; }
    .school { color: var(--muted); margin: 1rem 0 0; }
    h1 { font-size: 1.5rem; margin: 0.5rem 0; }
    p { line-height: 1.5; }
    button { margin-top: 1rem; padding: 0.6rem 1.4rem; font: inherit; cursor: pointer;
      background: transparent; color: var(--text); border: 2px solid; border-radius: 0.5rem;
      border-color: {{ primary }}; }
  </style>
</head>
<body>
  <main>
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" aria-hidden="true">
      <rect x="0" y="0" width="512" height="512" rx="112" fill="#147E78"/>
      <rect x="172" y="129" width="64" height="254" rx="32" fill="#FFFFFF"/>
      <circle cx="298" cy="341" r="42" fill="#C77B2A"/>
    </svg>
    <p class="school">{{ school_name }}</p>
    <h1>{% trans "You're offline" %}</h1>
    <p>{% trans "Check your connection and try again." %}</p>
    <button type="button" onclick="location.reload()">{% trans "Try again" %}</button>
  </main>
  <script>
    window.addEventListener("online", function () { location.reload(); });
  </script>
</body>
</html>
```

(The `border-color: {{ primary }};` line renders as `border-color: #147E78;` for the default, which the test's first alternative matches. `primary` is always a validated CSS colour — `effective_primary` guarantees it.)

- [ ] **Step 5: Run to verify pass**

Run: `uv run python -m pytest tests/test_pwa_offline.py tests/test_pwa_core.py`
Expected: all PASS.

- [ ] **Step 6: Mutants**

1. Change `render_to_string("core/offline.html", {...})` to `render(request, "core/offline.html", {...})` and add `{{ user.username }}` inside `<main>` → RED: `test_offline_page_never_shows_the_requesting_user`. (Two edits: the template edit is what an accidental base.html-style dependency looks like.)
2. Add `{% include "core/_public_footer.html" %}` to the template → RED: `test_offline_template_is_self_contained`.
3. Put `{% extends "base.html" %}` as the template's first line → RED: `test_offline_template_is_self_contained`.
4. Change `fill="#C77B2A"` to `fill="#C77B2B"` → RED: `test_offline_mark_matches_the_favicon`.

Revert each by hand; re-run green.

- [ ] **Step 7: Commit**

```bash
git add core/views.py core/urls.py templates/core/offline.html tests/test_pwa_offline.py
git commit -m "feat(pwa): standalone /offline/ page with no user data"
```

---

### Task 3: `/sw.js` — the normal worker and the kill worker

**Files:**
- Modify: `core/views.py` (add `service_worker` view)
- Modify: `core/urls.py` (add route)
- Replace: `templates/core/sw.js`
- Create: `templates/core/sw_kill.js`
- Test: `tests/test_pwa_worker.py`

**Interfaces:**
- Consumes: `core.pwa.serve_normal()`, `worker_version()`, `cache_static()`, `PRECACHE`, `PASSTHROUGH_PREFIXES`, `PASSTHROUGH_SUFFIXES`.
- Produces: route `core:service_worker` at `/sw.js`; JS globals inside the worker `VERSION`, `PRECACHE`, `CACHE_STATIC`, `PASSTHROUGH_PREFIXES`, `PASSTHROUGH_SUFFIXES`; cache names `libli-static-<VERSION>` / `libli-offline-<VERSION>` (Task 10's e2e reads these).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pwa_worker.py`:

```python
"""PWA C1: /sw.js (spec §2, §3) -- the truth table, the rendered values and
source guards on both worker templates."""

import json
import re

import pytest
from django.conf import settings as dj_settings
from django.template.loader import get_template
from django.urls import reverse

from core import pwa

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fresh_manifest_cache():
    pwa._manifest_bytes.cache_clear()
    yield
    pwa._manifest_bytes.cache_clear()


def _sw(client):
    return client.get("/sw.js")


def test_sw_route_is_the_root_path():
    assert reverse("core:service_worker") == "/sw.js"


def test_normal_worker_headers_and_values(client, settings):
    settings.PWA_ENABLED = True
    settings.PWA_KILL_SWITCH = False
    r = _sw(client)
    assert r.status_code == 200
    assert r["Content-Type"] == "text/javascript; charset=utf-8"
    assert r["Cache-Control"] == "no-cache"
    body = r.content.decode()
    assert f"const VERSION = {json.dumps(pwa.worker_version())};" in body
    assert 'const PRECACHE = ["/offline/"];' in body
    assert "const CACHE_STATIC = false;" in body  # plain storage in the suite
    assert 'const PASSTHROUGH_PREFIXES = ["/media/"];' in body
    assert 'const PASSTHROUGH_SUFFIXES = ["/export/"];' in body
    assert "respondWith" in body
    assert "LIBLI_SW_KILL" not in body


def test_normal_worker_reports_cache_static_true_with_the_override(client, settings):
    settings.PWA_ENABLED = True
    settings.PWA_KILL_SWITCH = False
    settings.PWA_CACHE_UNHASHED_STATIC = True
    assert "const CACHE_STATIC = true;" in _sw(client).content.decode()


@pytest.mark.parametrize("enabled,kill", [(True, True), (False, False), (False, True)])
def test_every_other_row_serves_the_kill_worker(client, settings, enabled, kill):
    settings.PWA_ENABLED = enabled
    settings.PWA_KILL_SWITCH = kill
    r = _sw(client)
    assert r.status_code == 200
    assert r["Cache-Control"] == "no-cache"
    body = r.content.decode()
    for needle in ("LIBLI_SW_KILL", "unregister", "caches.delete", "libli-"):
        assert needle in body, needle
    assert "respondWith" not in body


def test_download_routes_match_a_passthrough_suffix():
    """Renaming an export route must not silently stream a GB download through
    the worker."""
    for path in (
        reverse("courses:manage_course_export", kwargs={"slug": "c"}),
        reverse("courses:manage_node_export", kwargs={"slug": "c", "pk": 1}),
        reverse("courses:manage_analytics_export", kwargs={"slug": "c"}),
    ):
        assert path.endswith(pwa.PASSTHROUGH_SUFFIXES), path


def test_media_url_matches_a_passthrough_prefix():
    assert dj_settings.MEDIA_URL.startswith(pwa.PASSTHROUGH_PREFIXES)


def _outside_verbatim(source):
    return re.sub(r"\{% verbatim %\}.*?\{% endverbatim %\}", "", source, flags=re.S)


@pytest.mark.parametrize("name", ["core/sw.js", "core/sw_kill.js"])
def test_worker_js_lives_inside_verbatim(name):
    """Outside {% verbatim %} only Django comments and `const X = {{ y|safe }};`
    value slots may appear, so no JS can be eaten by the template engine."""
    source = get_template(name).template.source
    assert "{% verbatim %}" in source
    for line in _outside_verbatim(source).splitlines():
        line = line.strip()
        if not line:
            continue
        assert re.fullmatch(
            r"\{#.*#\}|const [A-Z_]+ = \{\{ [a-z_]+\|safe \}\};", line
        ), line


def test_normal_worker_source_guards():
    source = get_template("core/sw.js").template.source
    assert "LIBLI_SW_KILL" not in source
    assert "unregister" not in source
    assert "navigationPreload" not in source
    assert "new URL(request.url)" in source and ".pathname" in source
    assert 'request.destination === "document"' in source
    # A hit must not caches.open() (which recreates a deleted cache).
    assert "caches.match(request, { cacheName: STATIC_CACHE })" in source
    assert "ignoreVary: true" in source


def test_passthrough_matches_on_the_pathname_only():
    """Aimed at passthrough() itself, not at substrings found elsewhere in the
    file: the archive download is `.../export/?confirm=1`, so a path built from
    the full URL (or pathname + search) would stream a GB through the worker."""
    source = get_template("core/sw.js").template.source
    body = source[source.index("function passthrough(") :]
    body = body[: body.index("\n}\n")]
    assert "const path = url.pathname;" in body
    assert "url.search" not in body
    assert "url.href" not in body
    assert body.count("request.url") == 1  # only inside new URL(request.url)


def test_kill_worker_source_guards():
    source = get_template("core/sw_kill.js").template.source
    assert "LIBLI_SW_KILL" in source
    assert "addEventListener(\"fetch\"" not in source
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_pwa_worker.py`
Expected: FAIL (`NoReverseMatch` for `service_worker`; `TemplateDoesNotExist: core/sw_kill.js`).

- [ ] **Step 3: Add the view and route**

In `core/views.py` add `import json` and extend the `core.pwa` import to `from core.pwa import PASSTHROUGH_PREFIXES, PASSTHROUGH_SUFFIXES, PRECACHE, cache_static, offline_branding, serve_normal, worker_version` (one name per line, matching the file's one-import-per-line style). Then add:

```python
def service_worker(request):
    """/sw.js (spec §1 table). ALWAYS 200: a 404 would make the browser keep the
    worker it already has, forever. no-cache so every navigation revalidates it --
    that is what makes the kill switch and every fix reach devices."""
    if serve_normal():
        body = render_to_string(
            "core/sw.js",
            {
                "version_json": json.dumps(worker_version()),
                "precache_json": json.dumps(list(PRECACHE)),
                "cache_static_json": json.dumps(cache_static()),
                "prefixes_json": json.dumps(list(PASSTHROUGH_PREFIXES)),
                "suffixes_json": json.dumps(list(PASSTHROUGH_SUFFIXES)),
            },
        )
    else:
        body = render_to_string("core/sw_kill.js")
    response = HttpResponse(body, content_type="text/javascript; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    return response
```

In `core/urls.py`, before the `offline/` route, add:

```python
    path("sw.js", views.service_worker, name="service_worker"),
```

- [ ] **Step 4: Replace `templates/core/sw.js`**

```
{# libli service worker (spec docs/superpowers/specs/2026-09-29-pwa-c1-installable-app-design.md §2). #}
{# Values arrive as JSON from core.views.service_worker; all JS stays inside verbatim. #}
const VERSION = {{ version_json|safe }};
const PRECACHE = {{ precache_json|safe }};
const CACHE_STATIC = {{ cache_static_json|safe }};
const PASSTHROUGH_PREFIXES = {{ prefixes_json|safe }};
const PASSTHROUGH_SUFFIXES = {{ suffixes_json|safe }};
{% verbatim %}
// No "use strict" here: a directive must be a script's FIRST statement, and the
// value slots above come first. Workers are classic scripts, not modules.
const STATIC_CACHE = "libli-static-" + VERSION;
const OFFLINE_CACHE = "libli-offline-" + VERSION;
const OFFLINE_URL = "/offline/";

self.addEventListener("install", (event) => {
  // A failed precache fails the install, and the previous worker stays in charge.
  event.waitUntil(
    caches.open(OFFLINE_CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  const keep = new Set([STATIC_CACHE, OFFLINE_CACHE]);
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key.startsWith("libli-") && !keep.has(key))
          .map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

// Rule 0. Pathname only: the archive download may carry ?confirm=1.
function passthrough(request) {
  if (request.method !== "GET") return true;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return true;
  const path = url.pathname;
  return PASSTHROUGH_PREFIXES.some((prefix) => path.startsWith(prefix)) ||
    PASSTHROUGH_SUFFIXES.some((suffix) => path.endsWith(suffix));
}

function staticFirst(event) {
  const request = event.request;
  // Look up WITHOUT caches.open(): open() CREATES a missing cache, so even a hit
  // served after a newer (or kill) worker deleted this cache would resurrect it
  // as an orphan. Only the miss path opens it, to put.
  return caches.match(request, { cacheName: STATIC_CACHE }).then((hit) => {
    if (hit) return hit;
    return fetch(request).then((response) => {
      // 200 only: a 206 cannot be put, and an error must never be cached.
      if (response.status === 200 && response.type === "basic") {
        const copy = response.clone();
        event.waitUntil(
          caches.open(STATIC_CACHE)
            .then((cache) => cache.put(request, copy))
            .catch(() => {})
        );
      }
      return response;
    });
  });
}

function offlinePage() {
  // By the literal URL, never the navigation request; ignoreVary because the
  // response carries Vary: Cookie, Accept-Language.
  return caches.match(OFFLINE_URL, { cacheName: OFFLINE_CACHE, ignoreVary: true })
    .then((hit) => hit || Response.error());
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (passthrough(request)) return;                                   // rule 0
  const path = new URL(request.url).pathname;
  if (CACHE_STATIC && path.startsWith("/static/")) {                  // rule 1
    event.respondWith(staticFirst(event));
    return;
  }
  if (request.mode === "navigate" && request.destination === "document") {  // rule 2
    // Only a REJECTED fetch (no network) falls back; every HTTP response,
    // including Caddy's 503 maintenance page, passes through unchanged.
    event.respondWith(fetch(request).catch(offlinePage));
  }
  // rule 3: everything else passes.
});
{% endverbatim %}
```

- [ ] **Step 5: Create `templates/core/sw_kill.js`**

```
{# libli kill worker (spec §3): served whenever the worker must go away. #}
{% verbatim %}
// LIBLI_SW_KILL -- the runbook's curl check greps for this marker; only this file carries it.
"use strict";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key.startsWith("libli-")).map((key) => caches.delete(key))))
      .then(() => self.registration.unregister())
  );
});
{% endverbatim %}
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run python -m pytest tests/test_pwa_worker.py tests/test_pwa_core.py tests/test_pwa_offline.py`
Expected: all PASS.

- [ ] **Step 7: Mutants**

1. In `service_worker`, return 404 (`HttpResponse(status=404)`) in the `else` branch → RED: `test_every_other_row_serves_the_kill_worker`.
2. In `sw.js`'s activate handler, add `self.registration.navigationPreload.enable();` → RED: `test_normal_worker_source_guards`.
3. In `staticFirst`, replace `caches.match(request, { cacheName: STATIC_CACHE })` with `caches.open(STATIC_CACHE).then((c) => c.match(request))` → RED: `test_normal_worker_source_guards`.
4. In `passthrough()`, change `const path = url.pathname;` to `const path = url.pathname + url.search;` → RED: `test_passthrough_matches_on_the_pathname_only`.
5. In `sw_kill.js`, add `self.addEventListener("fetch", (e) => e.respondWith(fetch(e.request)));` (and nothing else) → RED: `test_every_other_row_serves_the_kill_worker`, `test_kill_worker_source_guards`.
6. Emit `{{ version_json }}` without `|safe` → RED: `test_normal_worker_headers_and_values` and `test_worker_js_lives_inside_verbatim`.
7. Move the `const STATIC_CACHE = ...;` line above `{% verbatim %}` → RED: `test_worker_js_lives_inside_verbatim`.
8. Rename the `manage_course_export` route's path to `manage/courses/<slug:slug>/export-archive/` in `courses/urls.py` → RED: `test_download_routes_match_a_passthrough_suffix`.

Revert each by hand; re-run green.

- [ ] **Step 8: Commit**

```bash
git add core/views.py core/urls.py templates/core/sw.js templates/core/sw_kill.js tests/test_pwa_worker.py
git commit -m "feat(pwa): /sw.js serves the normal or the kill worker, always 200"
```

---

### Task 4: The `/install-app/` public guide and its links

**Files:**
- Modify: `core/public_pages.py` (`PAGES` entry)
- Modify: `core/views_public.py` (add `install_app`)
- Modify: `core/urls.py` (route)
- Create: `docs/public/install-app.md`, `docs/public/install-app.pl.md`
- Modify: `docs/public/getting-started.md`, `docs/public/getting-started.pl.md` (one paragraph each)
- Modify: `templates/core/_public_footer.html` (link after Help)
- Modify: `templates/help/index.html` (link at the top)
- Modify: `tests/test_public_pages.py:29` (registry pin)
- Modify: `tests/test_public_pages_views.py:70-73` (parametrize list gains `install-app`)
- Modify: `tests/test_public_pages_content.py` `SHIPPED` (two entries)
- Modify: `tests/test_public_pages_settings.py:50-57` (replace the literal `4` with a derived count and rewrite its comment)
- Test: `tests/test_pwa_install_page.py`

**Interfaces:**
- Produces: route `core:install_app` at `/install-app/` (Task 6 links to it).

- [ ] **Step 1: Write the failing tests and update the pins**

Create `tests/test_pwa_install_page.py`:

```python
"""PWA C1: the public install guide (spec §8)."""

import pytest
from django.urls import reverse

from core.public_pages import DEMO_NOTICE_SLUGS
from core.public_pages import PAGES
from core.public_pages import VENDOR_ONLY_SLUGS
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def test_install_page_is_registered_and_neither_demo_nor_vendor_only():
    assert PAGES["install-app"].path == "public/install-app.md"
    assert "install-app" not in DEMO_NOTICE_SLUGS
    assert "install-app" not in VENDOR_ONLY_SLUGS


def test_install_page_renders_anonymously_in_both_languages(client):
    url = reverse("core:install_app")
    assert url == "/install-app/"
    en = client.get(url, headers={"accept-language": "en"})
    pl = client.get(url, headers={"accept-language": "pl"})
    assert en.status_code == pl.status_code == 200
    assert en.context["resolved_lang"] == "en"
    assert pl.context["resolved_lang"] == "pl"
    assert "Add to Home Screen" in en.content.decode()
    assert "Do ekranu początkowego" in pl.content.decode()


def test_public_footer_links_the_guide(client):
    body = client.get(reverse("core:privacy")).content.decode()
    assert f'href="{reverse("core:install_app")}"' in body


def test_getting_started_links_the_guide(client):
    for lang in ("en", "pl"):
        body = client.get(
            reverse("core:getting_started"), headers={"accept-language": lang}
        ).content.decode()
        assert 'href="/install-app/"' in body, lang


def test_staff_help_index_links_the_guide(client):
    from django.contrib.auth.models import Group

    from institution.roles import TEACHER
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(username="help-probe", email="h@probe.example.com")
    user.groups.add(Group.objects.get(name=TEACHER))
    client.force_login(user)
    body = client.get(reverse("core:help_index")).content.decode()
    assert f'href="{reverse("core:install_app")}"' in body
```

Update the existing pins:
- `tests/test_public_pages_views.py` `test_page_emits_its_real_description_title_and_one_h1`: extend its parametrize list to `[("privacy", "core:privacy"), ("getting-started", "core:getting_started"), ("install-app", "core:install_app")]` (composed `<title>`, meta description and exactly one `<h1>` for the new page).
- `tests/test_public_pages.py` line 29: `assert set(PAGES) == {"privacy", "getting-started", "for-schools", "install-app"}` and add below the existing path asserts: `assert PAGES["install-app"].path == "public/install-app.md"`.
- `tests/test_public_pages_content.py` `SHIPPED`: append `"public/install-app.md",` and `"public/install-app.pl.md",`.
- `tests/test_public_pages_settings.py`: in `test_panel_renders_one_textarea_per_page_per_language`, extend the loop's tuple to `("privacy", "getting-started", "install-app")`, and replace the comment block plus `assert body.count('name="override-') == 4` with:

```python
    # EXACT count: a presence check does not kill "iterate settings.LANGUAGES",
    # which is a superset and would render extra textareas while staying green.
    # Derived, not a literal: every page except the vendor-only for-schools (the
    # suite pins VENDOR_INSTANCE=False, so _page_overrides() filters it out), times
    # two languages. A count of len(PAGES) * 2 here would mean the vendor-only
    # filter regressed.
    expected = (len(PAGES) - len(VENDOR_ONLY_SLUGS)) * 2
    assert body.count('name="override-') == expected
```

  and add `from core.public_pages import VENDOR_ONLY_SLUGS` to that file's imports.

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_pwa_install_page.py tests/test_public_pages.py tests/test_public_pages_content.py tests/test_public_pages_settings.py`
Expected: FAIL (`KeyError: 'install-app'`, `NoReverseMatch`, missing files).

- [ ] **Step 3: Register the page, view and route**

In `core/public_pages.py` `PAGES`, after the `"for-schools"` entry, add:

```python
    "install-app": Page(
        "install-app",
        "public/install-app.md",
        _("Install the app"),
        _("How to add libli to your phone, tablet or computer as an app."),
    ),
```

In `core/views_public.py` add:

```python
def install_app(request):
    return _public_page(request, "install-app")
```

In `core/urls.py`, after the `for-schools/` route, add:

```python
    path("install-app/", views_public.install_app, name="install_app"),
```

- [ ] **Step 4: Write the guide**

`docs/public/install-app.md`:

```markdown
# Install the app

You can add libli to your phone, tablet or computer so that it opens like an app: from its own
icon, full screen, without the browser's address bar. Nothing is downloaded from an app store,
and it is the same libli you use in the browser.

## Android phone or tablet

1. Open this site in **Chrome**.
2. Tap the menu (three dots, top right).
3. Tap **Install app** or **Add to Home screen**, then confirm.

If you are logged in, you can also use **Install app** in your account menu (the round button
with your initial, top right).

## iPhone or iPad

1. Open this site in **Safari**.
2. Tap the **Share** button (a square with an arrow pointing up).
3. Scroll down and tap **Add to Home Screen**, then **Add**.

## Computer

In **Chrome** or **Edge**, click the install icon at the right end of the address bar (a screen
with a small arrow), or use **Install app** in your account menu, then confirm.

## Good to know

- **On iPhone and iPad you log in once more** inside the app: it keeps its own login, separate
  from Safari.
- **Lessons still need an internet connection.** Without one, the app shows a short "You're
  offline" page until the connection returns.
- **To remove the app**, delete it like any other app: press and hold its icon on a phone or
  tablet, or open it on a computer and choose *Uninstall* from its menu.
```

`docs/public/install-app.pl.md`:

```markdown
# Instalacja aplikacji

libli można dodać do telefonu, tabletu lub komputera tak, aby otwierało się jak aplikacja: z
własnej ikony, na pełnym ekranie, bez paska adresu przeglądarki. Niczego nie pobiera się ze
sklepu z aplikacjami — to to samo libli, którego używasz w przeglądarce.

## Telefon lub tablet z Androidem

1. Otwórz tę stronę w **Chrome**.
2. Stuknij menu (trzy kropki w prawym górnym rogu).
3. Stuknij **Zainstaluj aplikację** lub **Dodaj do ekranu głównego** i potwierdź.

Po zalogowaniu możesz też użyć pozycji **Zainstaluj aplikację** w menu konta (okrągły przycisk
z Twoim inicjałem, w prawym górnym rogu).

## iPhone lub iPad

1. Otwórz tę stronę w **Safari**.
2. Stuknij przycisk **Udostępnij** (kwadrat ze strzałką w górę).
3. Przewiń w dół, stuknij **Do ekranu początkowego**, a potem **Dodaj**.

## Komputer

W **Chrome** lub **Edge** kliknij ikonę instalacji na prawym końcu paska adresu (ekran z małą
strzałką) albo użyj pozycji **Zainstaluj aplikację** w menu konta i potwierdź.

## Warto wiedzieć

- **Na iPhonie i iPadzie zaloguj się jeszcze raz** w samej aplikacji: ma ona własne logowanie,
  niezależne od Safari.
- **Lekcje nadal wymagają połączenia z internetem.** Bez niego aplikacja pokazuje krótką stronę
  „Jesteś offline”, dopóki połączenie nie wróci.
- **Aby usunąć aplikację**, usuń ją jak każdą inną: przytrzymaj jej ikonę na telefonie lub
  tablecie albo otwórz ją na komputerze i wybierz z jej menu *Odinstaluj*.
```

- [ ] **Step 5: Add the links**

Append to `docs/public/getting-started.md` (end of file):

```markdown

To use libli like an app on a phone, tablet or computer, see
[how to install it](/install-app/).
```

Append to `docs/public/getting-started.pl.md` (end of file):

```markdown

Aby korzystać z libli jak z aplikacji na telefonie, tablecie lub komputerze, zobacz
[jak ją zainstalować](/install-app/).
```

The landing page (`templates/core/landing.html`) has its OWN `landing-footer`, which this task deliberately does NOT touch: the spec lists `_public_footer.html` only, and extending it is an owner question raised at plan handoff. Do not add it silently.

In `templates/core/_public_footer.html`, after the `Help` link line, add:

```html
  <a href="{% url 'core:install_app' %}">{% trans "Install app" %}</a>
```

In `templates/help/index.html`, directly after `<h1>{% trans "Help" %}</h1>`, add:

```html
  <p><a href="{% url 'core:install_app' %}">{% trans "Install libli as an app" %}</a></p>
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run python -m pytest tests/test_pwa_install_page.py tests/test_public_pages.py tests/test_public_pages_content.py tests/test_public_pages_settings.py tests/test_public_pages_views.py tests/test_public_pages_render.py tests/test_public_pages_footer.py tests/test_getting_started_trim.py tests/test_for_schools_route.py`
Expected: all PASS (the PL-language assertion passes on the markdown file alone; msgid translations arrive in Task 7).

- [ ] **Step 7: Mutant**

Add `"install-app"` to `DEMO_NOTICE_SLUGS` → RED: `test_install_page_is_registered_and_neither_demo_nor_vendor_only`. Revert by hand.

- [ ] **Step 8: Commit**

```bash
git add tests/test_public_pages_views.py core/public_pages.py core/views_public.py core/urls.py docs/public/install-app.md docs/public/install-app.pl.md docs/public/getting-started.md docs/public/getting-started.pl.md templates/core/_public_footer.html templates/help/index.html tests/test_pwa_install_page.py tests/test_public_pages.py tests/test_public_pages_content.py tests/test_public_pages_settings.py
git commit -m "feat(pwa): public /install-app/ guide, linked from footer, getting-started and Help"
```

---

### Task 5: Manifest fields, iOS head tags and `short_name` moved to services

**Files:**
- Modify: `core/services.py` (add `short_name` after `default_name`)
- Modify: `core/views.py` (delete `_short_name`; `webmanifest` imports `short_name`; add `id`, `scope`, `lang`, `description`)
- Modify: `core/templatetags/branding.py` (`favicon_links` appends two meta tags)
- Modify: `tests/test_favicon_render.py:185-188` (import from `core.services`)
- Test: `tests/test_pwa_manifest.py`

**Interfaces:**
- Consumes: `get_site_config()["default_language"]`, `["name"]`.
- Produces: `core.services.short_name(name: str | None) -> str` (the former `core.views._short_name`, renamed public because two modules import it).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pwa_manifest.py`:

```python
"""PWA C1: manifest identity fields and the iOS head tags (spec §5)."""

import json

import pytest
from django.urls import reverse

from core.services import short_name
from institution.models import Institution

pytestmark = pytest.mark.django_db


def _manifest(client, **headers):
    return json.loads(client.get(reverse("core:webmanifest"), headers=headers).content)


def test_manifest_identity_fields(client):
    data = _manifest(client)
    assert data["id"] == "/"
    assert data["scope"] == "/"
    assert data["lang"] == "en"
    assert data["description"] == "Lessons and courses from your school"


def test_manifest_description_follows_default_language_not_the_session(client):
    inst = Institution.load()
    inst.default_language = "en"
    inst.save()
    data = _manifest(client, **{"accept-language": "pl"})
    assert data["lang"] == "en"
    assert data["description"] == "Lessons and courses from your school"


def test_head_carries_the_ios_app_title_and_capable_tags(client):
    inst = Institution.load()
    inst.name = "Liceum Ogólnokształcące nr 5"
    inst.save()
    body = client.get(reverse("account_login")).content.decode()
    assert (
        f'<meta name="apple-mobile-web-app-title" content="{short_name(inst.name)}">'
        in body
    )
    assert '<meta name="mobile-web-app-capable" content="yes">' in body
```

In `tests/test_favicon_render.py`, change the body of `test_short_name_boundaries` to:

```python
    from core.services import short_name

    assert short_name(name) == expected
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_pwa_manifest.py tests/test_favicon_render.py`
Expected: FAIL (`ImportError: cannot import name 'short_name' from 'core.services'`).

- [ ] **Step 3: Move `_short_name`**

Cut `_short_name` (with its docstring) from `core/views.py`, paste it into `core/services.py` directly after `default_name`, renamed `short_name`. Its body calls `default_name()`, which is now local. In `core/views.py`, replace every `_short_name(` call with `short_name(` and add `from core.services import short_name`.

- [ ] **Step 4: Extend `webmanifest`**

In `core/views.py`, add `from django.utils import translation`. In `webmanifest`, before `return JsonResponse(`, add:

```python
    # In the language `lang` declares, whatever the requesting session's language.
    with translation.override(cfg["default_language"]):
        description = str(_("Lessons and courses from your school"))
```

and add to the dict, after `"short_name": ...`:

```python
            "id": "/",
            "scope": "/",
            "lang": cfg["default_language"],
            "description": description,
```

- [ ] **Step 5: Extend `favicon_links`**

In `core/templatetags/branding.py`, add `from core.services import short_name`, and just before `return format_html_join(...)` add:

```python
    # iOS labels a home-screen icon with the page title unless told otherwise.
    parts.append(
        format_html(
            '<meta name="apple-mobile-web-app-title" content="{}">',
            short_name(cfg.get("name")),
        )
    )
    # An argument, not a bare literal: format_html() with no args is deprecated.
    parts.append(
        format_html('<meta name="{}" content="yes">', "mobile-web-app-capable")
    )
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run python -m pytest tests/test_pwa_manifest.py tests/test_favicon_render.py`
Expected: all PASS.

- [ ] **Step 7: Mutant**

Remove the `with translation.override(...)` wrapper (compute `description` with the ambient language) → the manifest tests stay GREEN here: with no pl catalog entry yet, the description is English in every language, so neither manifest test can tell. This mutant is run in Task 7 Step 5 instead, where it turns `test_manifest_description_in_the_default_language_pl` RED. Record that in the commit message body.

- [ ] **Step 8: Commit**

```bash
git add core/services.py core/views.py core/templatetags/branding.py tests/test_favicon_render.py tests/test_pwa_manifest.py
git commit -m "feat(pwa): manifest id/scope/lang/description; iOS app-title head tags

short_name moves to core.services (two modules import it). The
default_language mutant for the description is exercised in the catalog
task, once a pl translation exists."
```

---

### Task 6: `pwa.js`, the account-menu "Install app" item and the `[hidden]` rule

**Files:**
- Create: `core/static/core/js/pwa.js`
- Modify: `templates/base.html` (account menu, after the Settings link ~line 141; script after `ui.js` ~line 166)
- Modify: `core/static/core/css/app.css` (after the `.menu__item { ... }` rule, ~line 293)
- Test: `tests/test_pwa_shell.py`

**Interfaces:**
- Consumes: context `pwa_enabled` (Task 1); route `core:install_app` (Task 4).
- Produces: DOM hook `[data-install-app]` (an `<a class="menu__item">`); attribute `data-install-mode="prompt"` set on it while a kept install event exists (Task 10 e2e 7 reads it); window listeners for `beforeinstallprompt` / `appinstalled`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pwa_shell.py`:

```python
"""PWA C1: pwa.js inclusion, the Install app item and the [hidden] rule."""

import re
from pathlib import Path

import pytest
from django.conf import settings as dj_settings
from django.urls import reverse

from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db

APP_CSS = Path(dj_settings.BASE_DIR) / "core/static/core/css/app.css"


def test_pwa_js_included_only_when_enabled(client, settings):
    settings.PWA_ENABLED = True
    settings.PWA_KILL_SWITCH = False
    assert "core/js/pwa.js" in client.get(reverse("account_login")).content.decode()
    settings.PWA_KILL_SWITCH = True
    assert "core/js/pwa.js" not in client.get(reverse("account_login")).content.decode()
    settings.PWA_ENABLED = False
    settings.PWA_KILL_SWITCH = False
    assert "core/js/pwa.js" not in client.get(reverse("account_login")).content.decode()
    settings.PWA_KILL_SWITCH = True
    assert "core/js/pwa.js" not in client.get(reverse("account_login")).content.decode()


def test_account_menu_links_the_install_guide(client):
    client.force_login(make_verified_user(username="menu-probe", email="m@probe.example.com"))
    body = client.get(reverse("home")).content.decode()
    m = re.search(r'<a class="menu__item" href="([^"]+)" data-install-app>', body)
    assert m and m.group(1) == reverse("core:install_app")


def test_install_item_renders_with_the_worker_off(client, settings):
    settings.PWA_ENABLED = False
    client.force_login(make_verified_user(username="menu-off", email="o@probe.example.com"))
    assert "data-install-app" in client.get(reverse("home")).content.decode()


def test_menu_item_hidden_attribute_is_honoured():
    """.menu__item sets display:block, which beats the UA [hidden] rule."""
    css = APP_CSS.read_text(encoding="utf-8")
    assert re.search(r"\.menu__item\[hidden\]\s*\{\s*display:\s*none;\s*\}", css)


def test_pwa_js_prevents_the_prompt_before_anything_else():
    js = (Path(dj_settings.BASE_DIR) / "core/static/core/js/pwa.js").read_text(encoding="utf-8")
    listener = js[js.index('"beforeinstallprompt"'):]
    assert listener.index("preventDefault()") < listener.index("return")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_pwa_shell.py`
Expected: FAIL (no `pwa.js` in page, no `data-install-app`, missing CSS rule, `FileNotFoundError` for pwa.js).

- [ ] **Step 3: Create `core/static/core/js/pwa.js`**

```js
/* PWA client (spec docs/superpowers/specs/2026-09-29-pwa-c1-installable-app-design.md §6).
   Loaded only when pwa_enabled. Registers /sw.js and drives the account menu's
   "Install app" item ([data-install-app]), which is a plain link to the install
   guide unless the browser hands us an install prompt. */
(function () {
  "use strict";

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker
      .register("/sw.js", { scope: "/", updateViaCache: "none" })
      .catch(function (err) {
        console.warn("libli: service worker registration failed", err);
      });
  }

  var kept = null; // the single-use beforeinstallprompt event

  function item() {
    return document.querySelector("[data-install-app]");
  }

  function hide() {
    var el = item();
    if (el) el.hidden = true;
  }

  function standalone() {
    return window.matchMedia("(display-mode: standalone)").matches ||
      navigator.standalone === true;
  }

  window.addEventListener("beforeinstallprompt", function (event) {
    // FIRST and unconditionally: no browser mini-infobar on any page (D3).
    event.preventDefault();
    var el = item();
    if (!el) return;
    kept = event;
    el.setAttribute("data-install-mode", "prompt");
  });

  window.addEventListener("appinstalled", hide);

  document.addEventListener("click", function (event) {
    var el = item();
    if (!el || !kept || !el.contains(event.target)) return;
    event.preventDefault();
    var prompt = kept;
    // Dropped synchronously: the event is single-use, and nothing here awaits
    // prompt()'s promise or userChoice.
    kept = null;
    el.removeAttribute("data-install-mode");
    prompt.prompt();
  });

  if (standalone()) hide();
})();
```

- [ ] **Step 4: Wire `base.html` and `app.css`**

In `templates/base.html`, in the account menu, directly after
`<a class="menu__item" href="{% url 'core:user_settings' %}">{% trans "Settings" %}</a>` add:

```html
            <a class="menu__item" href="{% url 'core:install_app' %}" data-install-app>{% trans "Install app" %}</a>
```

After `<script src="{% static 'core/js/ui.js' %}" defer></script>` add:

```html
  {% if pwa_enabled %}<script src="{% static 'core/js/pwa.js' %}" defer></script>{% endif %}
```

In `core/static/core/css/app.css`, directly after the `.menu__item { ... }` rule (the three-line rule ending `text-decoration: none; cursor: pointer; }`), add:

```css
.menu__item[hidden] { display: none; }  /* .menu__item's display:block beats the UA [hidden] rule */
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run python -m pytest tests/test_pwa_shell.py tests/test_public_pages_footer.py`
Expected: all PASS.

- [ ] **Step 6: Mutants**

1. Delete the `.menu__item[hidden]` line → RED: `test_menu_item_hidden_attribute_is_honoured`.
2. Move `var el = item(); if (!el) return;` above `event.preventDefault();` → RED: `test_pwa_js_prevents_the_prompt_before_anything_else`.
3. Wrap the new menu `<a>` in `{% if pwa_enabled %}...{% endif %}` → RED: `test_install_item_renders_with_the_worker_off`.

Revert each by hand; re-run green.

- [ ] **Step 7: Commit**

```bash
git add core/static/core/js/pwa.js templates/base.html core/static/core/css/app.css tests/test_pwa_shell.py
git commit -m "feat(pwa): pwa.js registers the worker; Install app menu item"
```

---

### Task 7: Catalog — Polish translations for every new msgid

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `django.mo`; `locale/en/LC_MESSAGES/django.po`, `django.mo`
- Test: `tests/test_pwa_i18n.py`

**Interfaces:**
- Consumes: the msgids added in Tasks 2, 4, 5 and 6.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pwa_i18n.py`:

```python
"""PWA C1: Polish renderings of the new strings."""

import json

import pytest
from django.urls import reverse

from institution.models import Institution

pytestmark = pytest.mark.django_db


def test_offline_page_in_polish(client):
    response = client.get(reverse("core:offline"), headers={"accept-language": "pl"})
    body = response.content.decode()
    assert "Jesteś offline" in body
    assert "Sprawdź połączenie z internetem i spróbuj ponownie." in body
    assert "Spróbuj ponownie" in body


def test_manifest_description_in_the_default_language_pl(client):
    inst = Institution.load()
    inst.enabled_languages = ["en", "pl"]
    inst.default_language = "pl"
    inst.save()
    data = json.loads(
        client.get(reverse("core:webmanifest"), headers={"accept-language": "en"}).content
    )
    assert data["lang"] == "pl"
    assert data["description"] == "Lekcje i kursy Twojej szkoły"


def test_install_link_in_polish(client):
    # Anonymous surface (the public footer): a logged-in user's stored language
    # preference could outrank the Accept-Language header.
    url = reverse("core:privacy")
    body = client.get(url, headers={"accept-language": "pl"}).content.decode()
    assert "Zainstaluj aplikację" in body


def test_install_page_title_and_description_in_polish(client):
    # The composed <title> and the meta description come from the msgids; the
    # markdown's own "# Instalacja aplikacji" heading would pass a bare substring
    # check with no catalog at all.
    url = reverse("core:install_app")
    body = client.get(url, headers={"accept-language": "pl"}).content.decode()
    assert "<title>Instalacja aplikacji ·" in body
    assert (
        '<meta name="description" content="Jak dodać libli jako aplikację na '
        'telefonie, tablecie lub komputerze.">'
    ) in body
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_pwa_i18n.py`
Expected: FAIL (English strings rendered).

- [ ] **Step 3: Extract and translate**

Run: `uv run python manage.py makemessages -l pl -l en --no-obsolete`

In `locale/pl/LC_MESSAGES/django.po`, find each msgid below and OVERWRITE its `msgstr` with the table's value — unconditionally, even if makemessages pre-filled one. Delete every `#, fuzzy` flag on these entries AND its `#| msgid ...` line.

| msgid | pl msgstr |
|---|---|
| `You're offline` | `Jesteś offline` |
| `Check your connection and try again.` | `Sprawdź połączenie z internetem i spróbuj ponownie.` |
| `Try again` | `Spróbuj ponownie` |
| `Install app` | `Zainstaluj aplikację` |
| `Install the app` | `Instalacja aplikacji` |
| `How to add libli to your phone, tablet or computer as an app.` | `Jak dodać libli jako aplikację na telefonie, tablecie lub komputerze.` |
| `Lessons and courses from your school` | `Lekcje i kursy Twojej szkoły` |
| `Install libli as an app` | `Zainstaluj libli jako aplikację` |

The `en` catalog entries stay with empty `msgstr`. Then run: `uv run python manage.py compilemessages`.

Check no other entry changed meaning: `git diff locale/pl/LC_MESSAGES/django.po` must show SEVEN new entries plus location-comment churn — `Try again` already exists (`Spróbuj ponownie`) and only gains a location comment; still confirm its msgstr is unchanged.

- [ ] **Step 4: Run to verify pass**

Run: `uv run python -m pytest tests/test_pwa_i18n.py tests/test_i18n_po_health.py tests/test_pwa_manifest.py`
Expected: all PASS.

- [ ] **Step 5: Deferred mutant from Task 5**

Remove the `with translation.override(cfg["default_language"]):` wrapper in `webmanifest` (dedent the line) → RED: `test_manifest_description_in_the_default_language_pl`. Revert by hand; re-run green.

- [ ] **Step 6: Commit**

```bash
git add locale/
git add tests/test_pwa_i18n.py
git commit -m "i18n(pwa): Polish strings for the offline page, install item and guide"
```

---

### Task 8: Runbook and environment example

**Files:**
- Modify: `docs/deployment.md` (new subsection at the end of `## 9. Schools`, before `## Known constraints`)
- Modify: `.env.production.example` (new `--- pwa ---` block before `--- vendor-only ---`)
- Test: `tests/test_pwa_runbook.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pwa_runbook.py`:

```python
"""PWA C1: the kill-switch runbook carries the commands that actually work."""

from pathlib import Path

from django.conf import settings

ROOT = Path(settings.BASE_DIR)


def _section():
    text = (ROOT / "docs/deployment.md").read_text(encoding="utf-8")
    start = text.index("### PWA kill switch")
    return text[start : text.index("\n## ", start)]


def test_runbook_recreates_rather_than_restarts():
    section = _section()
    assert "up -d --force-recreate app" in section
    assert "docker compose restart" in section  # named, as the thing NOT to do
    assert "LIBLI_SW_KILL" in section
    assert "grep -c LIBLI_SW_KILL" in section
    # a box provisioned before the worker shipped has no line: the command appends
    assert "echo 'LIBLI_PWA_KILL_SWITCH=true' >> .env.production" in section


def test_env_example_documents_both_variables():
    text = (ROOT / ".env.production.example").read_text(encoding="utf-8")
    assert "\nLIBLI_PWA_KILL_SWITCH=\n" in text
    assert "\n# LIBLI_PWA_ENABLED=" in text  # commented: unset means on
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_pwa_runbook.py`
Expected: FAIL (`ValueError: substring not found`).

- [ ] **Step 3: Write the runbook section**

In `docs/deployment.md`, immediately before the `## Known constraints` heading, insert:

````markdown
### PWA kill switch

Every page registers a service worker (`/sw.js`). If it ever misbehaves, recall it from every
device: set the switch, then RECREATE the app container.

```bash
# on the box, in /opt/libli -- a box provisioned before the worker shipped has no
# LIBLI_PWA_KILL_SWITCH line at all, so replace it if present, append it if not
if grep -q '^LIBLI_PWA_KILL_SWITCH=' .env.production; then
  sed -i 's/^LIBLI_PWA_KILL_SWITCH=.*/LIBLI_PWA_KILL_SWITCH=true/' .env.production
else
  echo 'LIBLI_PWA_KILL_SWITCH=true' >> .env.production
fi
grep '^LIBLI_PWA_KILL_SWITCH=' .env.production   # MUST print LIBLI_PWA_KILL_SWITCH=true
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --force-recreate app
```

Never `docker compose restart`: it keeps the container's old environment and does not re-read
`.env.production`, so the switch silently never takes effect. Recreating shows the usual ~24 s
maintenance page, like a deploy, so do it outside lesson time where possible.

Once `/sw.js` answers 200 again, verify from anywhere:

```bash
curl -s https://<host>/sw.js | grep -c LIBLI_SW_KILL
# 1 = the kill worker is being served; each device drops the worker and its caches on its next visit
```

To undo, blank the value (`LIBLI_PWA_KILL_SWITCH=`), recreate the same way, and check that the
same `curl` prints `0`. A school box may take a release that carries the worker before it has
been checked on libli.pl, but only with this switch set first.
````

- [ ] **Step 4: Extend `.env.production.example`**

Immediately before the `# --- vendor-only ---` line, insert:

```
# --- pwa ---
# Set to true to recall the service worker from every device (runbook §9, "PWA kill
# switch"). Takes effect only after `up -d --force-recreate app`, never `restart`.
LIBLI_PWA_KILL_SWITCH=
# The worker is ON in production when this is unset. A BLANK value parses as off.
# LIBLI_PWA_ENABLED=false

```

- [ ] **Step 5: Run to verify pass**

Run: `uv run python -m pytest tests/test_pwa_runbook.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add docs/deployment.md .env.production.example tests/test_pwa_runbook.py
git commit -m "docs(pwa): kill-switch runbook section and env example"
```

---

### Task 9: e2e spike — how to go offline and how to observe the export

This task produces HELPERS, not tests. Its output is `tests/pwa_e2e.py` plus a findings paragraph in that module's docstring. **If no option works, STOP and ask Krzysztof** (spec: e2e 2 and its mutants then move to the manual device checklist; never ship a test that cannot fail).

**Files:**
- Create: `tests/pwa_e2e.py`
- Create (throwaway, not committed): `tests/test_e2e_pwa_spike.py`

**Interfaces:**
- Produces (`tests/pwa_e2e.py`):
  - `enable_pwa(settings) -> None` — sets `PWA_ENABLED=True`, `PWA_KILL_SWITCH=False`, `PWA_CACHE_UNHASHED_STATIC=True`.
  - `wait_controlled(page) -> None` — waits until `navigator.serviceWorker.controller` is non-null, reloading once after `navigator.serviceWorker.ready` if needed.
  - `outage(context, page, *, fires_online: bool)` — a context manager: inside it, EVERY same-origin request the worker makes rejects, whatever its path (e2e 2 navigates to a page it has not visited before, `/getting-started/`); on exit the network is back, firing the `online` event iff `fires_online`.
  - `export_observer(context) -> list` — starts recording what the spike found observable for requests whose path ends with `/export/`; each recorded item exposes `.served_by_worker: bool`.
  - `PWA_ENV: dict[str, str]` — env vars the PWA e2e module needs (empty if none).

- [ ] **Step 1: Write the spike module**

Create `tests/test_e2e_pwa_spike.py` (NOT committed) that:
1. enables the PWA via the `settings` fixture, logs in nobody, opens `/privacy/`, waits controlled;
2. tries each outage option in order, and after each, navigates to a DIFFERENT page, `/getting-started/` (exactly as e2e 2 does), and checks whether the offline page text `You're offline` appears; a route-based option must use a path-agnostic pattern (`**/*`, narrowed only by origin) so any page is covered:
   - (i) re-run the file with `PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS=1` exported, then `context.set_offline(True)`; also try `context.route("**/*", lambda r: r.abort())` and record whether the route handler is called for the WORKER's fetch (log `route.request.service_worker`);
   - (ii) `cdp = context.new_cdp_session(page)`; `cdp.send("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": False, "flatten": True})`, find the service-worker target via `cdp.send("Target.getTargets")`, attach, `Network.enable`, `Network.emulateNetworkConditions` with `offline: True`;
   - (iii) stop the live server's listener: `live_server.thread.httpd.shutdown()` is session-scoped — do NOT do this in the real module unless it can be restarted; record only whether it works;
3. for the export: seed a small course with `make_course_with_unit(owner=make_verified_user(username="pwa-owner", email="pwa-owner@probe.example.com"))` (a bare `make_course_with_unit()` owner is a `UserFactory` user whose password is not `TEST_PASSWORD` and who has no verified email, so it cannot log in under mandatory verification; ownership alone grants `can_manage_course`), log in as that owner, navigate to `…/export/?confirm=1` with `page.expect_download()`, and record which of `context.on("request")` (with option (i)'s env var) / `context.on("response")` observed the request, and whether `request.service_worker` / `response.from_service_worker` is readable.

Run: `uv run python -m pytest tests/test_e2e_pwa_spike.py -m e2e -s` (foreground, never backgrounded).

- [ ] **Step 2: Write `tests/pwa_e2e.py` from the findings**

Implement the interface above with ONLY the mechanisms the spike showed working. Put a `Findings (2026-..-..):` paragraph at the top of the module docstring naming: which option makes the worker's fetch reject; whether `set_offline` alone suffices; which route filter catches the worker's inner fetch (keyed on URL path, never `is_navigation_request()`); where `PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS` must be set if used, and whether the rest of the e2e suite still passes with it (run `uv run python -m pytest -m e2e -n 2` with it set, or record that `tests/test_e2e_pwa.py` must run in its own invocation: in `.github/workflows/ci.yml`'s e2e job change the existing step to `uv run python -m pytest -m e2e -n 2 --ignore=tests/test_e2e_pwa.py` AND add a step `PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS=1 uv run python -m pytest -m e2e tests/test_e2e_pwa.py` — a second invocation alone would leave the module failing in the first); and which export observation works. **`fires_online=False` must be PROVEN**: register an init script that counts `online` events (`addEventListener("online", () => window.__onlineCount = (window.__onlineCount || 0) + 1)`) and show the count stays 0 across an `outage(..., fires_online=False)` exit — otherwise e2e 2b passes with the Try again button broken. If the only working outage mechanism fires `online` on exit (e.g. `set_offline`/CDP offline, no working route abort), implement `fires_online=False` by adding, for that exit only, an init script on the page that swallows the event (`window.addEventListener("online", e => e.stopImmediatePropagation(), true)` registered before the page's own listener) and prove it with the same counter; if even that cannot be made reliable, STOP and ask Krzysztof whether e2e 2b moves to the manual device checklist. If no export observation works, `export_observer` is omitted and the docstring says Task 10 e2e 4's export half is replaced by the source test `test_passthrough_matches_on_the_pathname_only` (Task 3; it reads `passthrough()`'s own body) — the weaker guard, recorded as such.

- [ ] **Step 3: Delete the spike file and commit the helpers**

```bash
rm tests/test_e2e_pwa_spike.py
git add tests/pwa_e2e.py
git commit -m "test(pwa): e2e helpers from the offline/export observation spike"
```

(If `.github/workflows/ci.yml` changed per Step 2, add it to this commit.)

---

### Task 10: Playwright e2e — the worker's behaviour end to end

**Files:**
- Create: `tests/test_e2e_pwa.py`

**Accepted (record in the PR body):** a cache HIT touches no cache (`caches.match` with `cacheName` never creates one), so only a MISS can orphan: its `caches.open(...).put` still in flight in the old worker when a newer or kill worker's activate runs can land after the delete and leave one `libli-static-<old>` cache. It holds only static files, is never read again, and carries no user data; the browser evicts it under storage pressure. e2e 5 and 6 avoid the race by construction (every static resource warmed first, so the next navigation is all hits) rather than tolerating it.

**Interfaces:**
- Consumes: `tests/pwa_e2e.py` (Task 9); `core.pwa.worker_version()`; factories `CourseFactory`, `ContentNodeFactory`, `add_element`, `make_image_asset`, `make_verified_user`, `EnrollmentFactory`, `make_course_with_unit`, `TEST_PASSWORD`; `courses.models.ImageElement`; route `courses:lesson_unit`.

- [ ] **Step 1: Write the module**

Create `tests/test_e2e_pwa.py`. Skeleton and every test (fill `outage`/`export_observer` calls exactly as `tests/pwa_e2e.py` defines them):

```python
"""e2e: the PWA worker.

Spec: docs/superpowers/specs/2026-09-29-pwa-c1-installable-app-design.md

Marked e2e (excluded by default). Run focused and in the FOREGROUND:
    uv run python -m pytest tests/test_e2e_pwa.py -m e2e
Every wait is on a condition, never a sleep. Mechanisms for going offline and for
observing the export download come from tests/pwa_e2e.py -- read its Findings.
"""

import os
import uuid

import pytest
from django.urls import reverse

from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_course_with_unit  # drop if the Findings omit the export half
from tests.factories import make_image_asset
from tests.factories import make_verified_user
from tests.pwa_e2e import enable_pwa
from tests.pwa_e2e import export_observer  # drop if the Findings omit it
from tests.pwa_e2e import outage
from tests.pwa_e2e import wait_controlled

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

OFFLINE_TEXT = "You're offline"


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _pwa(settings, tmp_path):
    enable_pwa(settings)
    settings.MEDIA_ROOT = str(tmp_path)  # live_server serves /media/ from here


def _login(page, live_server, user):
    # Scoped to the login form: the header's language switcher is also a submit.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(user.username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_selector("form[action*='login']", state="detached")


def _cache_keys(page):
    return page.evaluate("async () => await caches.keys()")


def _poll_cache_has(page, cache_name, url, timeout=5000):
    page.wait_for_function(
        """async ([name, url]) => {
            const cache = await caches.open(name);
            return !!(await cache.match(url));
        }""",
        arg=[cache_name, url],
        timeout=timeout,
    )


def _warm_static(page, version):
    """Wait until every /static/ resource the current page loaded is in the
    static cache -- including tokens.css's @font-face woff2 files and any
    CSS-referenced image, which no element selector finds. Without it, a miss on
    the NEXT navigation puts after a new (or kill) worker's activate deleted the
    old cache and recreates it, and a poll on caches.keys() times out."""
    urls = page.evaluate(
        "() => performance.getEntriesByType('resource').map(e => e.name)"
        ".filter(u => new URL(u).pathname.startsWith('/static/'))"
    )
    assert urls, "non-vacuity: the page loaded no /static/ file"
    # The browser fetches icons ITSELF (<link rel=icon>, apple-touch-icon, the
    # manifest's icons for the installability check): those requests go through
    # the worker but never appear in the page's Resource Timing. Fetch each once
    # through the controlled page so it is cached, then wait for it like the rest.
    icons = page.evaluate(
        """async () => {
            const links = [...document.querySelectorAll(
                'link[rel~="icon"], link[rel="apple-touch-icon"]')].map(l => l.href);
            const manifest = document.querySelector('link[rel="manifest"]');
            const data = manifest ? await (await fetch(manifest.href)).json() : {};
            const fromManifest = (data.icons || [])
                .map(i => new URL(i.src, location.href).href);
            const all = [...links, ...fromManifest]
                .filter(u => new URL(u).pathname.startsWith('/static/'));
            await Promise.all(all.map(u => fetch(u)));
            return all;
        }"""
    )
    for url in [*urls, *icons]:
        _poll_cache_has(page, f"libli-static-{version}", url)


def test_static_is_really_cached(page, live_server):
    from core.pwa import worker_version

    page.goto(f"{live_server.url}/privacy/")
    wait_controlled(page)
    page.reload()
    ui_js = page.evaluate(
        "() => document.querySelector('script[src*=\"core/js/ui.js\"]').src"
    )
    _poll_cache_has(page, f"libli-static-{worker_version()}", ui_js)


def test_offline_then_back_online_without_a_click(page, live_server, context):
    page.goto(f"{live_server.url}/privacy/")
    wait_controlled(page)
    with outage(context, page, fires_online=True):
        page.goto(f"{live_server.url}/getting-started/")
        page.get_by_text(OFFLINE_TEXT).wait_for()
    # the page's own `online` listener reloads it -- no click. Wait for the REAL
    # page's content: the URL is /getting-started/ even while the offline page shows.
    page.get_by_role("heading", name="Getting started", level=1).wait_for()


def test_offline_then_try_again(page, live_server, context):
    page.goto(f"{live_server.url}/privacy/")
    wait_controlled(page)
    with outage(context, page, fires_online=False):
        page.goto(f"{live_server.url}/getting-started/")
        page.get_by_text(OFFLINE_TEXT).wait_for()
    page.get_by_role("button", name="Try again").click()
    page.get_by_role("heading", name="Getting started", level=1).wait_for()


def test_real_errors_and_posts_pass_through(page, live_server):
    from core.pwa import worker_version

    page.goto(f"{live_server.url}/privacy/")
    wait_controlled(page)
    # A real 404 is shown as itself, not as the offline page.
    resp = page.goto(f"{live_server.url}/no-such-page-{uuid.uuid4().hex}/")
    assert resp.status == 404
    assert OFFLINE_TEXT not in page.content()
    # A failed static fetch is not stored.
    missing = f"{live_server.url}/static/core/nonexistent-{uuid.uuid4().hex}.css"
    status = page.evaluate("async (u) => (await fetch(u)).status", missing)
    assert status == 404
    # Positive control, fetched AFTER the missing file: once IT is cached, the
    # worker has had the same chance to (wrongly) store the 404. It must be a file
    # neither /privacy/ nor the web manifest requests (pwa.js, ui.js or a manifest
    # icon could already be cached, and the poll would return before the 404's put
    # could land): doc-page.css is loaded only by the staff help pages.
    control = f"{live_server.url}/static/core/css/doc-page.css"
    page.evaluate("async (u) => { await fetch(u); }", control)
    _poll_cache_has(page, f"libli-static-{worker_version()}", control)
    has = page.evaluate(
        """async ([name, url]) => !!(await (await caches.open(name)).match(url))""",
        [f"libli-static-{worker_version()}", missing],
    )
    assert has is False
    # A POST (the header language switcher) is not served by the worker.
    page.goto(f"{live_server.url}/privacy/")
    with page.expect_response(lambda r: r.request.method == "POST") as posted:
        page.locator("button[name='language']").first.click()
    assert posted.value.from_service_worker is False


def test_anonymous_login_page_is_quiet_and_suppresses_the_banner(page, live_server):
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(f"{live_server.url}/accounts/login/")
    wait_controlled(page)
    prevented = page.evaluate(
        """() => {
            const e = new Event("beforeinstallprompt", { cancelable: true });
            e.prompt = () => Promise.resolve({ outcome: "accepted" });
            e.userChoice = Promise.resolve({ outcome: "accepted" });
            window.dispatchEvent(e);
            return e.defaultPrevented;
        }"""
    )
    assert prevented is True
    assert errors == []


@pytest.fixture
def image_lesson(transactional_db):
    from courses.models import ImageElement

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    asset = make_image_asset(course, filename="pwa-probe.png")
    add_element(unit, ImageElement.objects.create(media=asset, alt="probe", size="full"))
    user = make_verified_user(username="pwa-student", email="pwa-student@probe.example.com")
    EnrollmentFactory(course=course, student=user)
    return unit, user, asset


def test_media_is_never_intercepted(page, live_server, context, image_lesson):
    unit, user, asset = image_lesson
    _login(page, live_server, user)
    url = reverse("courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk})
    seen = []
    page.on("response", lambda r: seen.append(r) if "/media/" in r.url else None)
    page.goto(f"{live_server.url}{url}")
    wait_controlled(page)
    seen.clear()  # only CONTROLLED loads count toward the non-emptiness checks
    page.reload()
    page.wait_for_function(
        "() => [...document.images]"
        ".some(i => i.src.includes('/media/') && i.complete)"
    )
    sub = [r for r in seen if r.request.resource_type == "image"]
    page.goto(f"{live_server.url}{asset.file.url}")
    nav = [r for r in seen if r.request.resource_type == "document"]
    assert sub, "no /media/ subresource observed"
    assert nav, "no /media/ navigation observed"
    assert all(r.from_service_worker is False for r in sub + nav)
    # Export half: use export_observer from tests/pwa_e2e.py per its Findings --
    # navigate a course manager to .../export/?confirm=1 under page.expect_download(),
    # assert EXACTLY one export observation and that it was not served by the worker.
    # If the Findings say no observation works, this half is omitted and the module
    # docstring names test_passthrough_matches_on_the_pathname_only (Task 3) as
    # the (weaker) guard.


def test_rename_reaches_the_next_navigation(page, live_server):
    from core.pwa import worker_version
    from institution.models import Institution

    inst = Institution.load()
    inst.name = "Before School"
    inst.save()
    page.goto(f"{live_server.url}/privacy/")
    wait_controlled(page)
    page.goto(f"{live_server.url}/privacy/")  # visited while controlled, pre-rename
    # Every /static/ file this page loads must be cached BEFORE the rename, or the
    # old worker's late puts on the next navigation can recreate the old static
    # cache after the new worker's activate deleted it (the poll below then times
    # out). Same warm-up as the kill-switch test.
    _warm_static(page, worker_version())
    inst.name = "After School"
    inst.save()  # post_save clears the in-process site-config cache
    new = worker_version()
    page.goto(f"{live_server.url}/privacy/")  # the FIRST post-rename navigation
    assert "After School" in page.title()  # read from THIS document, no reload
    page.wait_for_function(
        """async (v) => {
            const keys = await caches.keys();
            const ours = keys.filter(k => k.startsWith("libli-"));
            return ours.includes("libli-offline-" + v)
                && ours.every(k => k.endsWith(v));
        }""",
        arg=new,
    )


def test_kill_switch_recalls_the_worker(page, live_server, settings):
    from core.pwa import worker_version

    page.goto(f"{live_server.url}/privacy/")
    wait_controlled(page)
    # Warm the static cache for THIS page first, and navigate back to the same page
    # after flipping the switch: its static files are then cache hits, which touch
    # no cache, so the old worker has no miss-path put that could land after the
    # kill worker's delete and recreate an orphan (the poll below would time out).
    page.reload()
    _warm_static(page, worker_version())
    settings.PWA_KILL_SWITCH = True
    page.goto(f"{live_server.url}/privacy/")
    page.wait_for_function(
        """async () => {
            const regs = await navigator.serviceWorker.getRegistrations();
            const keys = (await caches.keys()).filter(k => k.startsWith("libli-"));
            return regs.length === 0 && keys.length === 0;
        }"""
    )


def _open_account_menu(page):
    page.locator("[data-account-menu] [data-menu-trigger]").click()
    page.get_by_role("link", name="Settings").wait_for(state="visible")


# Chromium may fire a REAL beforeinstallprompt (the page is installable); it
# would replace the fake as the kept event. This init script, registered before
# pwa.js, swallows every such event not flagged as the test's own.
SWALLOW_REAL_PROMPTS = """window.addEventListener("beforeinstallprompt", (e) => {
    if (!e.__fake) e.stopImmediatePropagation();
}, true);"""

FAKE_PROMPT = """() => {
    window.__promptCalls = 0;
    const e = new Event("beforeinstallprompt", { cancelable: true });
    e.__fake = true;
    e.prompt = () => {
        window.__promptCalls += 1;
        return Promise.resolve({ outcome: "accepted" });
    };
    e.userChoice = Promise.resolve({ outcome: "accepted" });
    window.dispatchEvent(e);
}"""


@pytest.fixture
def member(transactional_db):
    return make_verified_user(username="pwa-member", email="pwa-member@probe.example.com")


def test_install_item_prompt_is_single_use(page, live_server, member):
    page.add_init_script(SWALLOW_REAL_PROMPTS)
    _login(page, live_server, member)
    page.goto(f"{live_server.url}/home/")
    item = page.locator("[data-install-app]")
    page.evaluate(FAKE_PROMPT)
    assert item.get_attribute("data-install-mode") == "prompt"
    _open_account_menu(page)
    item.click()
    assert page.evaluate("() => window.__promptCalls") == 1
    assert "/home/" in page.url
    if not item.is_visible():  # re-opening an open menu would toggle it shut
        _open_account_menu(page)
    with page.expect_navigation():
        item.click()
    assert page.url.endswith("/install-app/")


def test_appinstalled_hides_the_item(page, live_server, member):
    _login(page, live_server, member)
    page.goto(f"{live_server.url}/home/")
    _open_account_menu(page)
    page.evaluate("() => window.dispatchEvent(new Event('appinstalled'))")
    assert page.locator("[data-install-app]").is_hidden()


def test_standalone_hides_the_item_on_load(page, live_server, member):
    page.add_init_script(
        """(() => {
            const real = window.matchMedia.bind(window);
            const standalone = {
                matches: true,
                media: "(display-mode: standalone)",
                addEventListener() {},
                removeEventListener() {},
            };
            window.matchMedia = (q) =>
                q.includes("display-mode: standalone") ? standalone : real(q);
        })();"""
    )
    _login(page, live_server, member)
    page.goto(f"{live_server.url}/home/")
    _open_account_menu(page)
    assert page.locator("[data-install-app]").is_hidden()
```

Replace the export-half comment in `test_media_is_never_intercepted` with real code using `export_observer` exactly as `tests/pwa_e2e.py` defines it (the manager is created as `make_course_with_unit(owner=make_verified_user(username="pwa-owner", email="pwa-owner@probe.example.com"))[0].owner` — never a bare `make_course_with_unit()`, whose `UserFactory` owner cannot log in; then call `context.clear_cookies()` and log in as them with `_login` on the same `page` — `context.new_page()` would share the student's cookie jar and allauth (`ACCOUNT_AUTHENTICATED_LOGIN_REDIRECTS` default True) would redirect away from the login form; after logging in, navigate once to a controlled page and `wait_controlled(page)` before the export navigation), or delete the comment and state the weaker guard in the module docstring, per Task 9's Findings. Same-origin half of rule 0: if a controlled page in this module loads a cross-origin subresource, assert it with `from_service_worker is False`; otherwise add to the module docstring: "The same-origin half of rule 0 is deliberately unguarded: no controlled page loads a cross-origin subresource in the e2e fixtures."

- [ ] **Step 2: Run the module**

Run (in the foreground; add `PWA_ENV` from `tests/pwa_e2e.py` if the Findings require it): `uv run python -m pytest tests/test_e2e_pwa.py -m e2e`
Expected: all PASS. A failure that appears as a TIMEOUT: if it is a `caches.keys()` poll, first suspect the orphan-cache race (a static resource not warmed by `_warm_static` before the navigation); otherwise check parallel load (run the test alone) before blaming the code. (A stale developer service worker cannot interfere here — each test gets a fresh browser context; that check belongs to Task 11 Step 5's manual smoke.)

- [ ] **Step 3: Mutants — each in the file its row names (`sw.js`, `sw_kill.js`, `offline.html`, `pwa.js`, `core/views.py`, `app.css`), each RED on the named test**

| Mutant (edit by hand, revert by hand) | Must turn RED |
|---|---|
| rule 1: replace `staticFirst(event)` with `fetch(event.request)` | `test_static_is_really_cached` |
| rule 1: delete the WHOLE `event.waitUntil(caches.open(STATIC_CACHE)...catch(() => {}));` statement (five lines; deleting one line leaves a syntax error that fails everything) | `test_static_is_really_cached` |
| delete the offline page's `online` listener | `test_offline_then_back_online_without_a_click` |
| change the Try again button's `onclick` to `""` | `test_offline_then_try_again` |
| rule 2: serve navigations cache-first (`caches.match(request).then(h => h || fetch(request))` and `put` every navigation) | `test_rename_reaches_the_next_navigation` |
| rule 2: `fetch(request).then(r => r.ok ? r : offlinePage())` | `test_real_errors_and_posts_pass_through` |
| `offlinePage`: `caches.match(event.request...)` (by the navigation request) — pass `request` into it | `test_offline_then_back_online_without_a_click` |
| replace the two-line `return PASSTHROUGH_PREFIXES.some(...) \|\| PASSTHROUGH_SUFFIXES.some(...);` with exactly `return PASSTHROUGH_SUFFIXES.some((suffix) => path.endsWith(suffix));` (deleting only the first operand would leave a bare `return` that ASI turns into `return;`) | `test_media_is_never_intercepted` |
| move the `if (passthrough(request)) return;` line below rule 2 | `test_media_is_never_intercepted` |
| rule 0: `const path = url.pathname + url.search;` (the variant that breaks `?confirm=1`) | export half of `test_media_is_never_intercepted`, AND `test_passthrough_matches_on_the_pathname_only` (Task 3) |
| store guard: `if (true)` instead of `response.status === 200 && ...` | `test_real_errors_and_posts_pass_through` |
| delete `if (request.method !== "GET") return true;` | `test_real_errors_and_posts_pass_through` |
| activate: delete the `.filter(...).map(caches.delete)` step | `test_rename_reaches_the_next_navigation` |
| `VERSION` constant: in the view, `json.dumps("fixed")` | `test_rename_reaches_the_next_navigation` |
| kill worker: delete the `.then(() => self.registration.unregister())` step (only that) | `test_kill_switch_recalls_the_worker` |
| `pwa.js`: delete `kept = null;` in the click handler | `test_install_item_prompt_is_single_use` |
| `pwa.js`: move `if (!el) return;` above `event.preventDefault();` | `test_anonymous_login_page_is_quiet_and_suppresses_the_banner` |
| `app.css`: delete `.menu__item[hidden]` | `test_appinstalled_hides_the_item`, `test_standalone_hides_the_item_on_load` |

After each: run only the named test, confirm RED, revert by hand, confirm `git diff` is clean for that file.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_pwa.py
git commit -m "test(pwa): e2e for static cache, offline fallback, passthrough, update, kill switch, install item"
```

---

### Task 11: Branch gate

- [ ] **Step 1: Lint and format**

Run: `uv run ruff check --no-cache .` and `uv run ruff format --check --no-cache .`
Expected: both clean.

- [ ] **Step 2: No migration**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 3: Whole non-e2e suite, in ~4 chunks (a single run is OOM-killed)**

Start the test-DB container first. Split `tests/` into four roughly equal file lists (e.g. by `ls tests/test_*.py | grep -v test_e2e_ | grep -v capture_` into quarters) plus the app-level test dirs `courses/tests`, `integrations/tests` and `notifications/tests`, and run each: `uv run python -m pytest <files>`. Never two runs at once. Grep each summary for `failed`/`error`; the exit code alone can lie.
Expected: 0 failed, 0 errors.

- [ ] **Step 4: e2e — the PWA module plus a neighbour sweep**

Run the PWA module with `PWA_ENV` from `tests/pwa_e2e.py` applied (e.g. `PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS=1` exported, if the Findings require it): `uv run python -m pytest tests/test_e2e_pwa.py -m e2e`
Then the neighbours WITHOUT it: `uv run python -m pytest tests/test_e2e_favicon.py tests/test_e2e_error_pages.py tests/test_e2e_auth.py -m e2e`
Expected: all PASS in both. (CI runs the full e2e suite, split the same way if Task 9 required it.)

- [ ] **Step 5: Manual smoke in dev**

With `LIBLI_PWA_ENABLED=true` exported (NOT in `.env` — an exported var is what takes effect), run the dev server, open `/privacy/` in a fresh browser profile, confirm in DevTools → Application → Service workers that `/sw.js` is activated, then set `LIBLI_PWA_KILL_SWITCH=true`, restart, navigate, and confirm the worker is gone. Unset both afterwards and unregister any worker left on `127.0.0.1:8000`.

- [ ] **Step 6: Open the PR**

PR body must carry: the spec path; D9/D10 verbatim; the **manual device checklist** from the spec as unticked boxes, stating it runs on libli.pl right after merge (D9) and that no *Deploy release* carries this to a school until every box is ticked; the Task 9 Findings paragraph; and the list of mutants shown RED.
