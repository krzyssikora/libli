# Containerised demo deployment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build libli's first deployment — a containerised install (`app`, `db`, `caddy`) that stands up a working instance on a single Contabo VPS, plus fixes for the two defects a real deployment exposes.

**Architecture:** Caddy terminates TLS, serves `/media/` directly from a volume (giving HTTP Range, which Django lacks entirely), and reverse-proxies everything else to gunicorn. Whitenoise keeps `/static/` inside the app so its hashed manifest stays authoritative. A single `app` container runs an ordered entrypoint (`migrate` → `setup_roles` → Site domain → `init_platform` → gunicorn). Demo content is loaded separately and is not part of the install.

**Tech Stack:** Python 3.13, Django 5.2, PostgreSQL 16, uv, gunicorn, Caddy 2, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-26-demo-deployment-design.md`

## Global Constraints

- **Python `>=3.13`**, Django `>=5.2,<5.3`, PostgreSQL **16** (matches `.github/workflows/ci.yml`).
- **Exactly one `app` container.** This is what makes `migrate` in the entrypoint safe and lets `TRANSFER_STAGING_DIR` be a local volume. Do not add replicas.
- **Transfer-cap defaults must not change.** `TRANSFER_MAX_COMPRESSED_BYTES` stays `1 * 1024**3`, `TRANSFER_MAX_UNCOMPRESSED_BYTES` stays `1536 * 1024**2`, `TRANSFER_MAX_MEDIA_ENTRIES` stays `1000`, `TRANSFER_MAX_ELEMENTS` stays `20000`. Only their env-overridability is new. **Four caps, not three** — matematyka measures 20,226 elements.
- **`TRANSFER_STAGING_DIR` and `SUPPORT_SCREENSHOT_DIR` must never be web-served.** They must not appear in any Caddy route, and Task 5 Step 5 and Task 6 Step 2 both prove it with a real request, not a grep.
- **No hardcoded passwords** in new code. ruff `S105`/`S106`/`S107` are enabled outside `tests/`.
- **ruff must pass:** `uv run ruff check . --no-cache` and `uv run ruff format --check .` are separate gates. Note `B` (bugbear) and `S` (bandit) are selected, so an unused loop variable (`B007`) fails the build. `I` is selected too, and `ruff format` does NOT sort imports: run `uv run ruff check --fix` for `I001` before the gate.
- **Run tests narrowly.** Whole-repo sweeps are a branch gate, not a task step. Start the test DB first: `docker compose -f docker-compose.test.yml up -d`.
- **Every test must be shown RED against its named mutant** before the task is accepted. A test that cannot fail is not evidence.
- **The Python blocks in this plan are illustrative, not formatter-clean.** ruff format (black semantics) explodes multi-line collections one element per line, collapses calls that fit in 88 columns, and normalises inline comments. Run `uv run ruff format .` after transcribing a block and before the lint gate, rather than treating a `--check` failure as a defect in your transcription.

### Working location — read before Task 1

The spec and an **earlier, defective** version of this plan were merged to `master` as a
side effect of another branch being cut from them (PR #274). Both files are already on
master; this plan supersedes what is there.

Work in the dedicated worktree, not the shared checkout — a parallel session shares that
checkout's HEAD and has already switched branches mid-task once:

```bash
git -C <main-checkout> worktree list          # confirm the worktree exists
cd ../libli-wt-deploy                          # branch: fix/demo-deployment-plan-review
git rev-parse --abbrev-ref HEAD                # MUST print fix/demo-deployment-plan-review
```

**Re-check the branch after every long-running step**, not just before committing. A
subagent dispatch or a slow test run is exactly the window in which the shared checkout
moves. A worktree is immune, which is why the work lives in one.

**A worktree has no `.env`.** Copy it in before running anything that touches the database:
`cp <main-checkout>/.env .` — see the `env-file-cannot-override-an-exported-var` note.

---

## File Structure

**New application code**
- `institution/site_domain.py` — validation + persistence for the `django.contrib.sites` Site domain. One responsibility; consumed by both a management command and a form.
- `institution/management/commands/set_site_domain.py` — entrypoint-callable wrapper.

**Modified application code**
- `config/settings/base.py` — the three cap assignments at lines **175, 176 and 181** become `env.int` reads.
- `institution/forms.py` — `BrandingForm` gains `public_hostname`; its **existing** `__init__` (line 152) and **existing** `save` (line 236) are edited, not duplicated.
- `templates/institution/manage/_branding_fields.html` — renders the new field.
- `tests/conftest.py` — new autouse fixture resetting the sites-framework cache.
- `pyproject.toml` — add `gunicorn`.

**New infrastructure (repo root unless noted)**
- `Dockerfile`, `docker-entrypoint.sh`, `docker-compose.prod.yml`, `Caddyfile`, `.dockerignore`, `.env.production.example`
- `docs/deployment.md` — the runbook.

**New tests**
- `tests/test_transfer_caps_env.py`, `tests/test_site_domain.py`
- `tests/test_setup_wizard.py` — extended, not replaced.

Note `templates/institution/manage/_branding_fields.html` is included by **both** `templates/institution/setup/identity.html:8` and `templates/institution/manage/_branding_tab.html:13`. Adding the field there deliberately surfaces it on the manage settings page too, so a Platform Admin can correct the hostname after first run, not only during it.

---

### Task 1: Upload sizing settings become env-overridable

**Files:**
- Modify: `config/settings/base.py` lines 175, 176, 180, 181, plus one new setting
- Test: `tests/test_transfer_caps_env.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: env var names `LIBLI_TRANSFER_MAX_COMPRESSED_BYTES`, `LIBLI_TRANSFER_MAX_UNCOMPRESSED_BYTES`, `LIBLI_TRANSFER_MAX_MEDIA_ENTRIES`, `LIBLI_TRANSFER_MAX_ELEMENTS` (all integers, bytes / count), and `DJANGO_FILE_UPLOAD_TEMP_DIR` (path or unset). Task 5's compose file and `.env.production.example` set them; Task 6's runbook documents them.

**Why `FILE_UPLOAD_TEMP_DIR` belongs here.** Django spills any upload above
`FILE_UPLOAD_MAX_MEMORY_SIZE` to `FILE_UPLOAD_TEMP_DIR` **before** the view can move it to
`TRANSFER_STAGING_DIR`. Left at its default that is a multi-GB write to the container's
overlay filesystem on the host root disk — a copy the spec's disk arithmetic does not
name. Django reads settings from the settings module, never from arbitrary environment
variables, so setting it in compose alone does nothing: the read has to exist here.

It gets its **own** volume (`/app/upload_tmp`), deliberately not `TRANSFER_STAGING_DIR`.
`staging.sweep()` (`courses/transfer/staging.py:22`) unlinks **any** file in the staging
directory older than `TRANSFER_STAGING_MAX_AGE_HOURS`, not just `*.zip` — pointing the
spill there would let the sweeper delete an in-flight upload, and would leave orphaned
spill files that Task 6's `rm -f …/*.zip` cleanup does not match.

- [ ] **Step 1: Write the failing test**

Create `tests/test_transfer_caps_env.py`:

```python
"""The three transfer caps are deployment guardrails. A school's default install
must keep the shipped values; only an operator's env raises them. Both halves of
that contract are asserted here.

Both tests reload config.settings.base rather than reading django.conf.settings.
That is deliberate: base.py reads BASE_DIR/.env at import time and django-environ's
read_env copies those values into os.environ, so a developer who set the overrides
in their own .env -- exactly what docs/deployment.md tells them to do -- would
otherwise turn the defaults test red for reasons unrelated to the code.

Reloading config.settings.base does NOT disturb django.conf.settings, which is
already configured; this exercises the module's read logic in isolation.
"""

import importlib
import os
from unittest import mock

import pytest

CAP_ENV_NAMES = (
    "LIBLI_TRANSFER_MAX_COMPRESSED_BYTES",
    "LIBLI_TRANSFER_MAX_UNCOMPRESSED_BYTES",
    "LIBLI_TRANSFER_MAX_MEDIA_ENTRIES",
    "LIBLI_TRANSFER_MAX_ELEMENTS",
    "DJANGO_FILE_UPLOAD_TEMP_DIR",
)


@pytest.fixture
def reload_base():
    """Reload config.settings.base under a controlled environment.

    Neutralises read_env so the dict passed in is the ONLY input, and restores the
    real module afterwards so later tests in the session see normal settings.
    """
    import environ

    import config.settings.base as base

    def _reload(env_overrides):
        with (
            mock.patch.object(environ.Env, "read_env", lambda *a, **k: None),
            mock.patch.dict(os.environ, env_overrides),
        ):
            for name in CAP_ENV_NAMES:
                if name not in env_overrides:
                    os.environ.pop(name, None)
            return importlib.reload(base)

    yield _reload
    importlib.reload(base)


def test_transfer_caps_default_to_the_shipped_guardrails(reload_base):
    base = reload_base({})
    assert base.TRANSFER_MAX_COMPRESSED_BYTES == 1 * 1024**3
    assert base.TRANSFER_MAX_UNCOMPRESSED_BYTES == 1536 * 1024**2
    assert base.TRANSFER_MAX_MEDIA_ENTRIES == 1000
    assert base.TRANSFER_MAX_ELEMENTS == 20000


def test_transfer_caps_are_env_overridable(reload_base):
    base = reload_base(
        {
            # 5 GiB, 6 GiB
            "LIBLI_TRANSFER_MAX_COMPRESSED_BYTES": "5368709120",
            "LIBLI_TRANSFER_MAX_UNCOMPRESSED_BYTES": "6442450944",
            "LIBLI_TRANSFER_MAX_MEDIA_ENTRIES": "2000",
            "LIBLI_TRANSFER_MAX_ELEMENTS": "25000",
        }
    )
    assert base.TRANSFER_MAX_COMPRESSED_BYTES == 5368709120
    assert base.TRANSFER_MAX_UNCOMPRESSED_BYTES == 6442450944
    assert base.TRANSFER_MAX_MEDIA_ENTRIES == 2000
    assert base.TRANSFER_MAX_ELEMENTS == 25000


def test_file_upload_temp_dir_defaults_to_none(reload_base):
    """Unset, Django falls back to the system temp dir -- correct for local dev."""
    base = reload_base({})
    assert base.FILE_UPLOAD_TEMP_DIR is None


def test_file_upload_temp_dir_is_env_overridable(reload_base):
    """Setting it in compose alone would do nothing: Django reads settings from
    the settings module, never from arbitrary environment variables."""
    base = reload_base({"DJANGO_FILE_UPLOAD_TEMP_DIR": "/app/upload_tmp"})
    assert base.FILE_UPLOAD_TEMP_DIR == "/app/upload_tmp"
```

(`CAP_ENV_NAMES` carries four entries despite its name: the upload temp dir is cleared alongside the three caps so the defaults test sees a pristine environment.)

- [ ] **Step 2: Run the test and confirm it fails**

```bash
uv run python -m pytest tests/test_transfer_caps_env.py -v
```

Expected: 1 passed, 3 failed. `test_transfer_caps_default_to_the_shipped_guardrails` PASSES (those values are already correct); `test_transfer_caps_are_env_overridable` FAILS on `assert 1073741824 == 5368709120`; and **both** `FILE_UPLOAD_TEMP_DIR` tests FAIL with `AttributeError: module 'config.settings.base' has no attribute 'FILE_UPLOAD_TEMP_DIR'`, since Step 3 has not added it yet.

- [ ] **Step 3: Make the caps env-overridable**

In `config/settings/base.py`, replace the assignments at lines 175, 176 and 181. Leave `TRANSFER_MAX_COURSE_JSON_BYTES`, `TRANSFER_MAX_MANIFEST_BYTES` and `TRANSFER_MAX_NODES` untouched — measured against matematyka they all have headroom (5.76 MiB course.json, 229 B manifest, 1,010 nodes):

```python
# Env-overridable so a deployment hosting a large course can raise them without
# a code change; the DEFAULTS are unchanged, so a stock install keeps the
# guardrails. Raising these requires raising the proxy body-size and worker
# timeout to match — see docs/deployment-course-transfer.md.
TRANSFER_MAX_COMPRESSED_BYTES = env.int(
    "LIBLI_TRANSFER_MAX_COMPRESSED_BYTES", default=1 * 1024**3
)  # 1 GiB zip upload
TRANSFER_MAX_UNCOMPRESSED_BYTES = env.int(
    "LIBLI_TRANSFER_MAX_UNCOMPRESSED_BYTES", default=1536 * 1024**2
)  # 1.5 GiB declared/actual total
```

and

```python
TRANSFER_MAX_MEDIA_ENTRIES = env.int("LIBLI_TRANSFER_MAX_MEDIA_ENTRIES", default=1000)
```

and the element cap on line 180 — **measured, not assumed**: matematyka is 20,226 elements
against a default of 20,000. It is enforced on IMPORT only
(`courses/transfer/schema.py:211`), so leaving it fixed would reject the archive *after*
a 25-minute upload, with no way to raise it without a redeploy:

```python
TRANSFER_MAX_ELEMENTS = env.int("LIBLI_TRANSFER_MAX_ELEMENTS", default=20000)
```

Then add the new setting immediately after `TRANSFER_STAGING_DIR` (line 184), where the
staging comment already explains the surrounding intent:

```python
# Where Django spills an upload too large for memory, BEFORE the view moves it to
# TRANSFER_STAGING_DIR. None = the system temp dir, correct for local dev. A
# container sets this to a path on sized storage, or a multi-GB upload lands on
# the overlay filesystem. Not under MEDIA_ROOT, for the same reason as above.
FILE_UPLOAD_TEMP_DIR = env("DJANGO_FILE_UPLOAD_TEMP_DIR", default=None)
```

- [ ] **Step 4: Run the test and confirm it passes**

```bash
uv run python -m pytest tests/test_transfer_caps_env.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Falsify — confirm the test can fail**

Two mutants, one at a time, each **edited out by hand** — do not `git checkout` the file, which would destroy the whole task's work.

1. Revert one line to `TRANSFER_MAX_MEDIA_ENTRIES = 1000`. Expected: `test_transfer_caps_are_env_overridable` FAILS with `assert 1000 == 2000`.
2. Delete the `FILE_UPLOAD_TEMP_DIR` line entirely. Expected: `test_file_upload_temp_dir_is_env_overridable` FAILS with `AttributeError` — which is precisely the state the compose variable alone would have left the deployment in.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . --no-cache && uv run ruff format --check .
git add config/settings/base.py tests/test_transfer_caps_env.py
git commit -m "feat(settings): make the three transfer caps env-overridable

Defaults are unchanged -- a stock install keeps the shipped guardrails.
Only a deployment hosting an oversized course raises them, and only via
its own environment."
```

---

### Task 2: `Site` domain module, command, and the sites-cache fixture

**Files:**
- Create: `institution/site_domain.py`
- Create: `institution/management/commands/set_site_domain.py`
- Modify: `tests/conftest.py` (new autouse fixture)
- Test: `tests/test_site_domain.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `institution.site_domain.PLACEHOLDER_DOMAIN` — the literal `"example.com"` Django ships Site #1 with. Consumed by this task's `--only-if-placeholder` branch and by Task 3's form.
  - `institution.site_domain.validate_site_domain(value) -> str` — raises `django.core.exceptions.ValidationError` on a bad host. Task 3's form imports this.
  - `institution.site_domain.set_site_domain(domain, name=None) -> Site` — validates, writes, clears the sites-framework cache.
  - Management command `set_site_domain`, reading `--domain` or the `DJANGO_SITE_DOMAIN` env var. Task 4's entrypoint calls it.
  - Autouse fixture `_reset_sites_framework_cache` in `tests/conftest.py`. Task 3's tests depend on it.

- [ ] **Step 1: Add the sites-cache autouse fixture**

`django.contrib.sites.models.SITE_CACHE` is a module-level dict that the database
rollback does **not** undo. The repo already has an autouse fixture named
`_clear_site_cache` (`tests/conftest.py:406`) — it clears the Django **cache framework**
(LocMemCache), which is a different thing entirely, and the similar name is a trap.

Without this, Task 3's new `BrandingForm.__init__` calls `get_current()` on every
instantiation and repopulates the cache after each rollback, so a domain written by one
test leaks into the next and assertions on `"example.com"` fail order-dependently under
`pytest-xdist`.

Append to `tests/conftest.py`.

(The root `conftest.py` is where the repo puts cross-cutting isolation fixtures, and it says so. `tests/` scope is deliberate here: `Site` is touched only by `tests/`, and `courses/tests`, `integrations/tests` and `notifications/tests` never instantiate `BrandingForm`. If that changes, move it up to the root conftest next to `_reset_active_language`.)

```python
@pytest.fixture(autouse=True)
def _reset_sites_framework_cache():
    """Reset django.contrib.sites' SITE_CACHE around every test.

    NOT the same as _clear_site_cache above, which clears the Django CACHE
    FRAMEWORK. SITE_CACHE is a module-level dict in django.contrib.sites.models,
    is not transaction-scoped, and survives the per-test rollback. BrandingForm
    repopulates it on every instantiation, so a leaked domain makes later tests
    fail depending on execution order.
    """
    from django.contrib.sites.models import Site

    Site.objects.clear_cache()
    yield
    Site.objects.clear_cache()
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_site_domain.py`:

```python
"""Invitation and password-reset links are built from the django.contrib.sites
Site record (accounts/invitations.py:build_accept_url), deliberately, so they
cannot be host-spoofed. Django ships Site #1 as example.com, so without this
every such link on a fresh deployment is dead."""

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command


@pytest.mark.parametrize(
    "value",
    ["libli.example.org", "libli.example.org:8000", "localhost", "a-b.c-d.example"],
)
def test_valid_hosts_are_accepted(value):
    from institution.site_domain import validate_site_domain

    assert validate_site_domain(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "https://libli.example.org",   # scheme
        "libli.example.org/setup",     # path
        "libli.example.org/",          # trailing slash
        "user@libli.example.org",      # userinfo
        "-libli.example.org",          # leading hyphen in a label
        # 113 chars, every label <= 63: rejected by the LENGTH lookahead, not the
        # per-label rule -- so deleting (?=.{1,100}$) actually turns this red.
        "a" * 50 + "." + "b" * 50 + ".example.org",
        "",
    ],
)
def test_invalid_hosts_are_rejected(value):
    from institution.site_domain import validate_site_domain

    with pytest.raises(ValidationError):
        validate_site_domain(value)


@pytest.mark.django_db
def test_set_site_domain_persists_to_the_database():
    """Read the row back FRESH rather than through get_current(), which would
    hand back the same in-memory object set_site_domain just mutated."""
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    from institution.site_domain import set_site_domain

    set_site_domain("libli.example.org", name="libli")
    row = Site.objects.get(pk=dj_settings.SITE_ID)
    assert (row.domain, row.name) == ("libli.example.org", "libli")


@pytest.mark.django_db
def test_set_site_domain_clears_the_sites_cache():
    """Assert on the CACHE, not on get_current().domain.

    get_current() returns the object held in SITE_CACHE, and set_site_domain
    mutates that very object -- so an assertion on get_current().domain reports
    the new value whether or not clear_cache() ran, and the mutant survives.
    The only observable effect of the clear is the cache entry's absence.
    """
    from django.conf import settings as dj_settings
    from django.contrib.sites import models as sites_models
    from django.contrib.sites.models import Site

    from institution.site_domain import set_site_domain

    Site.objects.get_current()  # prime
    assert dj_settings.SITE_ID in sites_models.SITE_CACHE

    set_site_domain("libli.example.org")
    assert dj_settings.SITE_ID not in sites_models.SITE_CACHE


@pytest.mark.django_db
def test_command_sets_the_domain_from_the_argument():
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    call_command("set_site_domain", "--domain", "demo.example.org")
    assert Site.objects.get(pk=dj_settings.SITE_ID).domain == "demo.example.org"


@pytest.mark.django_db
def test_command_reads_the_env_var(monkeypatch):
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    monkeypatch.setenv("DJANGO_SITE_DOMAIN", "env.example.org")
    call_command("set_site_domain")
    assert Site.objects.get(pk=dj_settings.SITE_ID).domain == "env.example.org"


@pytest.mark.django_db
def test_command_is_a_no_op_when_unset(monkeypatch):
    """The entrypoint calls this unconditionally. With no domain configured it
    must warn and exit cleanly, never abort the boot of a running instance."""
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    monkeypatch.delenv("DJANGO_SITE_DOMAIN", raising=False)
    call_command("set_site_domain")
    assert Site.objects.get(pk=dj_settings.SITE_ID).domain == "example.com"


@pytest.mark.django_db
def test_command_rejects_a_url(monkeypatch):
    from django.core.management.base import CommandError

    monkeypatch.setenv("DJANGO_SITE_DOMAIN", "https://demo.example.org/")
    with pytest.raises(CommandError):
        call_command("set_site_domain")


@pytest.mark.django_db
def test_only_if_placeholder_writes_when_the_site_is_unset():
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    call_command("set_site_domain", "--domain", "first.example.org",
                 "--only-if-placeholder")
    assert Site.objects.get(pk=dj_settings.SITE_ID).domain == "first.example.org"


@pytest.mark.django_db
def test_only_if_placeholder_leaves_a_configured_site_alone():
    """The entrypoint runs on EVERY boot. Without this the container would
    silently revert a hostname a Platform Admin corrected through the settings
    UI -- and restart: unless-stopped makes reboots routine."""
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    from institution.site_domain import set_site_domain

    set_site_domain("chosen-by-the-admin.example.org")
    call_command("set_site_domain", "--domain", "from-the-env.example.org",
                 "--only-if-placeholder")
    assert (
        Site.objects.get(pk=dj_settings.SITE_ID).domain
        == "chosen-by-the-admin.example.org"
    )


# MUST stay last in this module. It is the ONLY test that observes
# _reset_sites_framework_cache directly, and it does so by asserting the state
# the preceding test leaves behind.
@pytest.mark.django_db
def test_site_cache_does_not_leak_from_the_previous_test():
    """Companion to the _reset_sites_framework_cache fixture.

    Every other assertion in this suite reads the Site ROW, which the per-test
    rollback restores whether or not SITE_CACHE was cleared -- so none of them
    can observe the fixture. SITE_CACHE is a module-level dict in
    django.contrib.sites.models and is NOT rolled back.

    The test immediately above calls get_current() and returns early without
    writing, so it leaves the cache populated. With the fixture in place this
    starts empty; without it, it does not. pytest runs in definition order here
    (pytest-randomly is not installed), which is what makes that deterministic.

    CAVEAT: under the branch gate's `pytest -n auto`, xdist's default --dist load
    may schedule this onto a worker that never ran the preceding test, so it
    asserts on an empty cache for an unrelated reason. It is not flaky -- it just
    stops proving anything there. Run the falsification sequentially, as the
    mutant step does.
    """
    from django.contrib.sites import models as sites_models

    assert sites_models.SITE_CACHE == {}
```

- [ ] **Step 3: Run the test and confirm it fails**

```bash
uv run python -m pytest tests/test_site_domain.py -v
```

Expected — and this baseline is deliberately precise, because two of these tests pass **vacuously** at this point and only become meaningful after Step 5:

- The 11 validator cases (4 valid + 7 invalid), `test_set_site_domain_*`, and `test_only_if_placeholder_leaves_a_configured_site_alone` fail with `ModuleNotFoundError: No module named 'institution.site_domain'` — the last one dies at its own import line, before reaching the command.
- Four of the six `call_command` tests fail with `CommandError: Unknown command: 'set_site_domain'`.
- `test_command_rejects_a_url` **PASSES** — it wraps the call in `pytest.raises(CommandError)`, and an unknown command raises exactly that.
- `test_site_cache_does_not_leak_from_the_previous_test` **PASSES** — the test before it dies at the import line before it can prime `SITE_CACHE`.

Do not treat those two passes as the tests being satisfied.

- [ ] **Step 4: Write `institution/site_domain.py`**

```python
"""Validation and persistence for the django.contrib.sites Site domain.

Security-sensitive links -- invitation acceptance, password reset -- are built
from the Site record rather than the request Host header
(accounts/invitations.py:build_accept_url), so they cannot be host-spoofed.
The cost of that choice is that the Site record must be set per environment;
Django ships Site #1 as the placeholder "example.com".

Shared by the `set_site_domain` management command (called from the container
entrypoint) and BrandingForm's public_hostname field (the non-technical
surface in the first-run wizard).

NOTE: institution/forms.py defines `_DOMAIN_RE` (search for the symbol, not a
line number -- Task 3 inserts ~25 lines above it). That is a DIFFERENT regex for
a different job: it validates email domains for AccessForm's allow-list and is
deliberately stricter (requires a dot, lowercase only). Do not merge them: a
public hostname may legitimately be a single label ("localhost") and carry a
port, neither of which is ever valid in an email domain.
"""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# A bare host with an optional :port. No scheme, no path, no userinfo, no
# trailing slash -- Site.domain is a host, and Django concatenates it directly.
# The length lookahead is 100, not DNS's 253: Site.domain is max_length=100, and
# a longer value would pass validation only to fail at save() with a database
# error instead of a form error.
_HOST_RE = re.compile(
    r"^(?=.{1,100}$)"
    r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*"
    r"(?::\d{1,5})?$"
)

INVALID_MESSAGE = _(
    "Enter a hostname such as libli.example.org — no http://, no path, "
    "no trailing slash."
)

# Django ships Site #1 with this domain. It is a VALID hostname, so it passes
# validate_site_domain -- it has to be recognised by identity, never by
# rejection. Consumed by the command's --only-if-placeholder branch and by
# BrandingForm, which leaves the field blank rather than pre-filling it.
PLACEHOLDER_DOMAIN = "example.com"


def validate_site_domain(value):
    """Return `value` unchanged if it is a bare host (optionally :port).

    Raises ValidationError otherwise. Used as a form field validator and as the
    command's argument check.
    """
    if not value or not _HOST_RE.match(value):
        raise ValidationError(INVALID_MESSAGE)
    return value


def set_site_domain(domain, name=None):
    """Validate `domain` and write it onto the current Site. Returns the Site.

    Clears the sites framework's per-SITE_ID cache: get_current() memoizes, so
    without this a long-lived process keeps serving the old domain in links.

    LIMITATION: SITE_CACHE is a per-PROCESS dict. With GUNICORN_WORKERS > 1 this
    clears only the worker that served the request; siblings keep building links
    from the old domain until they are recycled. After changing the hostname
    through the settings UI, restart the app service -- Task 6 says so.
    """
    from django.contrib.sites.models import Site

    validate_site_domain(domain)
    site = Site.objects.get_current()
    site.domain = domain
    fields = ["domain"]
    if name:
        site.name = name
        fields.append("name")
    site.save(update_fields=fields)
    Site.objects.clear_cache()
    return site
```

- [ ] **Step 5: Write `institution/management/commands/set_site_domain.py`**

```python
"""Set the django.contrib.sites Site domain from --domain or DJANGO_SITE_DOMAIN.

Called unconditionally by the container entrypoint after `migrate`, so that an
install is never *born* with dead invitation links. A no-op (with a warning)
when no domain is configured, because aborting here would stop an otherwise
healthy instance from booting.
"""

import os

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from institution.site_domain import PLACEHOLDER_DOMAIN
from institution.site_domain import set_site_domain


class Command(BaseCommand):
    help = "Set the Site domain used to build invitation and reset links."

    def add_arguments(self, parser):
        parser.add_argument(
            "--domain",
            default=None,
            help="Public hostname, e.g. libli.example.org (optional :port).",
        )
        parser.add_argument(
            "--name", default=None, help="Human-readable site name (optional)."
        )
        parser.add_argument(
            "--only-if-placeholder",
            action="store_true",
            help="Write only while the Site still holds Django's example.com "
            "placeholder. The entrypoint uses this so a hostname corrected "
            "through the settings UI is not reverted on the next restart.",
        )

    def handle(self, *args, **options):
        domain = options["domain"] or os.environ.get("DJANGO_SITE_DOMAIN", "")
        domain = domain.strip()
        if not domain:
            self.stdout.write(
                self.style.WARNING(
                    "No --domain and no DJANGO_SITE_DOMAIN; leaving the Site "
                    "record unchanged. Invitation and password-reset links will "
                    "point at whatever it currently holds."
                )
            )
            return
        if options["only_if_placeholder"]:
            from django.contrib.sites.models import Site

            current = Site.objects.get_current().domain
            if current != PLACEHOLDER_DOMAIN:
                self.stdout.write(
                    f"Site domain is already {current!r}; leaving it alone "
                    f"(--only-if-placeholder)."
                )
                return
        try:
            site = set_site_domain(domain, name=options["name"])
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(self.style.SUCCESS(f"Site domain set to {site.domain}"))
```

- [ ] **Step 6: Run the test and confirm it passes**

```bash
uv run python -m pytest tests/test_site_domain.py -v
```

Expected: 20 passed (4 + 7 parametrised cases, plus 9 behaviour tests).

- [ ] **Step 7: Falsify — confirm the tests can fail**

Three mutants, run one at a time and edit each out by hand afterwards:

1. Delete the `Site.objects.clear_cache()` line in `set_site_domain`. Expected: `test_set_site_domain_clears_the_sites_cache` FAILS — the SITE_ID key is still present. (`test_set_site_domain_persists_to_the_database` correctly still passes; it tests a different guarantee.)
2. Change the no-op branch to `raise CommandError(...)`. Expected: `test_command_is_a_no_op_when_unset` FAILS.
3. Delete the `r"^(?=.{1,100}$)"` lookahead from `_HOST_RE`. Expected: the 113-character parametrised case FAILS. That guard exists solely to stop a `DataError` at `Site.save()` (`Site.domain` is `max_length=100`); without a case whose labels are each under 63 characters it would be unfalsifiable.
The third mutant — deleting the `_reset_sites_framework_cache` fixture — needs the wizard tests that Task 3 adds, so it is **Task 3 Step 7 mutant 5**, not a deferred note here. Do not skip it: it is the only falsification of the new fixture.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check . --no-cache && uv run ruff format --check .
git add institution/site_domain.py institution/management/commands/set_site_domain.py tests/test_site_domain.py tests/conftest.py
git commit -m "feat(institution): set_site_domain command and validator

Site #1 ships as example.com, and build_accept_url builds invitation and
password-reset links from it deliberately (so they cannot be host-spoofed).
Without this step every such link on a fresh deployment is dead, and no
test catches it.

Also adds an autouse fixture resetting django.contrib.sites' SITE_CACHE,
which is module-level and survives the per-test rollback -- distinct from
the existing _clear_site_cache, which clears the cache framework."
```

---

### Task 3: `public_hostname` on `BrandingForm` — the non-technical surface

**Files:**
- Modify: `institution/forms.py` — the **existing** `__init__` (line 152) and the **existing** `save` (line 236); add one field declaration after `accent` (line 128)
- Modify: `templates/institution/manage/_branding_fields.html` (the Identity section, after the `favicon` field)
- Test: `tests/test_setup_wizard.py` (append)

**Interfaces:**
- Consumes: `institution.site_domain.validate_site_domain`, `institution.site_domain.set_site_domain`, and the `_reset_sites_framework_cache` fixture (all Task 2).
- Produces: form field named `public_hostname` on `BrandingForm`. No later task depends on it.

**`BrandingForm` already defines both `__init__` and `save`.** Adding second definitions
would leave two methods of the same name in one class body, and whichever is written later
silently wins — either the Site is never written, or every brand-colour save is destroyed.
Edit the existing methods.

The wizard's Identity step is handled by `_modelform_step` (`institution/views_setup.py`), which calls `form.save()`. Editing `BrandingForm.save()` is therefore sufficient — **do not modify `views_setup.py`**.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_setup_wizard.py`:

```python
_IDENTITY_POST = {
    "action": "next",
    "name": "Acme Academy",
    "enabled_languages": ["en", "pl"],
    "default_language": "en",
    "default_theme": "auto",
    "primary": "#147e78",
    "accent": "#c77b2a",
}


@pytest.mark.django_db
def test_identity_step_sets_the_site_domain(client):
    """The non-technical fix for dead invitation links: a Platform Admin types
    the public hostname during first-run setup and the Site record is written."""
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(
        reverse("institution:setup_step", kwargs={"step": "identity"}),
        _IDENTITY_POST | {"public_hostname": "libli.example.org"},
    )
    assert resp.status_code == 302
    site = Site.objects.get(pk=dj_settings.SITE_ID)
    assert site.domain == "libli.example.org"
    # allauth subject-lines every account email "[{site.name}] ", so a stale name
    # keeps "example.com" on the surface this task exists to fix.
    assert site.name == "Acme Academy"


@pytest.mark.django_db
def test_identity_step_still_saves_the_brand_colours(client):
    """Guards the C1 hazard: BrandingForm.save already wrote BrandColor rows, and
    a second save() definition would silently drop them."""
    from institution.models import BrandColor
    from tests.factories import make_pa

    make_pa(client)
    client.post(
        reverse("institution:setup_step", kwargs={"step": "identity"}),
        _IDENTITY_POST | {"public_hostname": "libli.example.org"},
    )
    rows = {c.key: c.value for c in BrandColor.objects.all()}
    assert rows["primary"] == "#147e78"
    assert rows["accent"] == "#c77b2a"


@pytest.mark.django_db
def test_identity_step_rejects_a_url_in_the_hostname(client):
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(
        reverse("institution:setup_step", kwargs={"step": "identity"}),
        _IDENTITY_POST | {"public_hostname": "https://libli.example.org/setup"},
    )
    assert resp.status_code == 200  # re-renders the step, does not advance
    assert Site.objects.get(pk=dj_settings.SITE_ID).domain == "example.com"


@pytest.mark.django_db
def test_identity_step_blank_hostname_leaves_the_site_alone(client):
    """The field is optional: an admin who skips it must not blank the domain."""
    from django.conf import settings as dj_settings
    from django.contrib.sites.models import Site

    from institution.site_domain import set_site_domain
    from tests.factories import make_pa

    set_site_domain("already.example.org")
    make_pa(client)
    resp = client.post(
        reverse("institution:setup_step", kwargs={"step": "identity"}),
        _IDENTITY_POST | {"public_hostname": ""},
    )
    assert resp.status_code == 302
    assert Site.objects.get(pk=dj_settings.SITE_ID).domain == "already.example.org"


@pytest.mark.django_db
def test_identity_step_seeds_the_hostname_field_from_the_site(client):
    from institution.site_domain import set_site_domain
    from tests.factories import make_pa

    set_site_domain("seeded.example.org")
    make_pa(client)
    resp = client.get(reverse("institution:setup_step", kwargs={"step": "identity"}))
    assert b'name="public_hostname"' in resp.content
    assert b"seeded.example.org" in resp.content


@pytest.mark.django_db
def test_identity_step_leaves_the_field_blank_on_a_placeholder_site(client):
    """Django's example.com placeholder is a VALID hostname, so pre-filling it
    would let an admin click Next and write the broken value straight back --
    confirming the exact state this field exists to fix."""
    from tests.factories import make_pa

    make_pa(client)  # Site #1 is still example.com
    resp = client.get(reverse("institution:setup_step", kwargs={"step": "identity"}))
    assert b'name="public_hostname"' in resp.content
    # Scoped to the field: tests/factories.py:236 gives users
    # "<username>@test.example.com", so a whole-page substring check would
    # break the moment the account menu rendered an email.
    assert b'name="public_hostname" value="example.com"' not in resp.content
    assert b'value="example.com"' not in resp.content
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
uv run python -m pytest tests/test_setup_wizard.py -k "site_domain or hostname or brand_colours or placeholder" -v
```

Expected: FAIL — the Site stays `example.com`, and `name="public_hostname"` is absent from the rendered page. (`test_identity_step_still_saves_the_brand_colours` passes already; it is the regression guard for Step 4.)

- [ ] **Step 3: Declare the field**

In `institution/forms.py`, add the imports near the existing ones:

```python
from institution.site_domain import PLACEHOLDER_DOMAIN
from institution.site_domain import set_site_domain
from institution.site_domain import validate_site_domain
```

All three are used by the edits below. Omitting `PLACEHOLDER_DOMAIN` raises `NameError` on
**every** `BrandingForm` instantiation — which includes `_settings_context` in
`institution/views_manage.py`, not just the wizard, so the manage settings page 500s too.

Inside `class BrandingForm(forms.ModelForm):`, after the `accent` declaration (line 128), add:

```python
    # NOT an Institution field: this writes django.contrib.sites.Site, which is
    # where build_accept_url reads the host for invitation and reset links.
    public_hostname = forms.CharField(
        required=False,
        label=_("Public hostname"),
        help_text=_(
            "The address people use to reach this site, e.g. libli.example.org. "
            "Used to build invitation and password-reset links. It does not "
            "change which addresses the server accepts — your host set that up."
        ),
    )
```

- [ ] **Step 4: Edit the EXISTING `__init__` and `save`**

`__init__` is at line 152 and already seeds the colour fields with `self.initial.setdefault`. Append one more `setdefault` in the same idiom, immediately before the method ends:

```python
        # Seed from the live Site so the admin edits the current value rather
        # than a blank box. Same setdefault idiom as the colours above.
        #
        # EXCEPT for Django's "example.com" placeholder: that value passes
        # validate_site_domain, so pre-filling it would let an admin click Next
        # and write back the exact broken state this field exists to fix. A blank
        # box prompts them instead.
        from django.contrib.sites.models import Site

        current = Site.objects.get_current().domain
        self.initial.setdefault(
            "public_hostname", "" if current == PLACEHOLDER_DOMAIN else current
        )
```

`PLACEHOLDER_DOMAIN` already exists — Task 2 Step 4 defines it in
`institution/site_domain.py`, because Task 2's `--only-if-placeholder` branch needs it too.
Import it here; do not redefine it.

Add the new `clean_public_hostname` alongside the existing `clean_*` methods:

```python
    def clean_public_hostname(self):
        value = (self.cleaned_data.get("public_hostname") or "").strip()
        if not value:
            return ""  # optional: blank leaves the Site record untouched
        return validate_site_domain(value)
```

`save` is at line 236 and already wraps `super().save()` in `transaction.atomic()` and
writes the `BrandColor` rows. Add the Site write **inside** it, after the colour loop —
do not add a second `save` method:

```python
    def save(self, commit=True):
        with transaction.atomic():
            inst = super().save(commit=commit)
            for key in ("primary", "accent"):
                BrandColor.objects.update_or_create(
                    institution=inst,
                    key=key,
                    defaults={"value": self.cleaned_data[key]},
                )
            # Inside the same atomic block: a failed Site write must not leave
            # the colours committed against a half-applied identity change.
            hostname = self.cleaned_data.get("public_hostname")
            if commit and hostname:
                # name= too: Django ships Site #1 with name AND domain set to
                # "example.com", and allauth prefixes every account email
                # subject with "[{site.name}] " and renders it in the body.
                # Leaving it keeps the placeholder on the very surface this fixes.
                set_site_domain(hostname, name=self.cleaned_data["name"])
        return inst
```

- [ ] **Step 5: Render the field**

In `templates/institution/manage/_branding_fields.html`, inside the `── Identity ──` section, immediately **after** the `form.favicon` `settings__field` div and before that section's closing `</div>`:

```html
  <div class="settings__field">
    <label class="settings__label" for="{{ form.public_hostname.id_for_label }}">{{ form.public_hostname.label }}</label>
    {{ form.public_hostname }}
    {% if form.public_hostname.help_text %}<span class="settings__help">{{ form.public_hostname.help_text }}</span>{% endif %}
    {{ form.public_hostname.errors }}
  </div>
```

- [ ] **Step 6: Run the test and confirm it passes**

```bash
uv run python -m pytest tests/test_setup_wizard.py -v
```

Expected: all pass, including the pre-existing wizard tests (the new field is optional, so the existing POST bodies that omit it must still succeed — if any now fail, `required=False` was lost).

- [ ] **Step 7: Falsify — confirm the tests can fail**

Six mutants, one at a time, each edited out by hand:

1. Delete the `set_site_domain(hostname)` call from `save()`. Expected: `test_identity_step_sets_the_site_domain` FAILS.
2. Change `clean_public_hostname` to `return value` without validating. Expected: `test_identity_step_rejects_a_url_in_the_hostname` FAILS (302 instead of 200, and the Site is corrupted).
3. Drop the `if commit and hostname:` guard so a blank writes through. Expected: `test_identity_step_blank_hostname_leaves_the_site_alone` turns red — but as an **error**, not a failed assertion: `set_site_domain("")` re-raises `ValidationError` out of `save()` and the view, so the request never returns 302. Red is red; do not go hunting for a blanked domain.
4. Add a **second** `def save(self, commit=True)` at the end of the class that only calls `super().save(commit)`. Expected: `test_identity_step_still_saves_the_brand_colours` FAILS — this is the C1 hazard made observable.
5. Delete the `_reset_sites_framework_cache` fixture added in Task 2 Step 1, then run:
   ```bash
   uv run python -m pytest tests/test_site_domain.py tests/test_setup_wizard.py  -v
   ```
   Expected: `test_site_cache_does_not_leak_from_the_previous_test` FAILS — `SITE_CACHE` still holds the entry the preceding test primed.

   That test is the **only** observer of the fixture. Every other assertion in both files reads the Site *row*, which the per-test rollback restores whether or not the cache was cleared, so none of them can fail on this mutant — do not expect a broader failure and do not treat its absence as the fixture being fine.
6. Change the `__init__` seeding to `self.initial.setdefault("public_hostname", Site.objects.get_current().domain)` (i.e. drop the placeholder guard from Step 4). Expected: `test_identity_step_leaves_the_field_blank_on_a_placeholder_site` FAILS — the box would be pre-filled with `example.com`, which validates, so an admin clicking Next writes the broken value straight back.

- [ ] **Step 8: Check the manage settings page still renders**

The template is shared with `templates/institution/manage/_branding_tab.html:13`. Confirm nothing there broke:

```bash
uv run python -m pytest tests/ -k "branding" -v
```

Expected: pass.

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff check . --no-cache && uv run ruff format --check .
git add institution/site_domain.py institution/forms.py templates/institution/manage/_branding_fields.html tests/test_setup_wizard.py
git commit -m "feat(institution): public hostname field on the identity step

Closes the gap docs/local-development.md describes as intended but never
built: nothing in the wizard touched django.contrib.sites.Site, so Site #1
stayed example.com and every invitation link on a fresh install was dead.

Edits the EXISTING save() rather than adding a second one -- a duplicate
definition would have silently dropped the BrandColor writes.

The field is shared with the manage settings branding tab, so a Platform
Admin can also correct it after first run."
```

---

### Task 4: `gunicorn`, `Dockerfile`, entrypoint

**Files:**
- Modify: `pyproject.toml` and `uv.lock` (dependencies)
- Create: `Dockerfile`, `docker-entrypoint.sh`, `.dockerignore`

**Interfaces:**
- Consumes: `set_site_domain` management command (Task 2).
- Produces: an image whose entrypoint accepts `DJANGO_SITE_DOMAIN`, `INIT_ADMIN_USERNAME`, `INIT_ADMIN_EMAIL`, `INIT_ADMIN_PASSWORD`, serves on container port `8000`, exposes `/healthz/` for a healthcheck, and **execs any command passed as arguments** instead of starting gunicorn. Task 5's compose file depends on all of these.

This task's real verification is Task 5 Step 5, which runs the stack. The checks here are build-time only, and the plan says so rather than implying more.

- [ ] **Step 1: Add gunicorn**

In `pyproject.toml`, add to `[project] dependencies` (production, not the dev group):

```toml
    "gunicorn>=23.0,<24.0",
```

Then:

```bash
uv sync
```

- [ ] **Step 2: Write `.dockerignore`**

Media is 3.8 GB and must never enter the build context — it lives in a volume.

```
.git
.venv
media
staticfiles
transfer_staging
support_screenshots
.pytest_cache
.ruff_cache
**/__pycache__
*.log
.env*
docker-compose.test.yml
tests
**/tests
docs/superpowers
docs/mockups
docs/planning
```

**`docs/` itself must NOT be excluded.** `core/help.py:21` sets
`DOCS_ROOT = <repo root>/docs` and `render_markdown_doc` (`core/help.py:135`) reads those
files **at request time** — its docstring says "A missing file is a packaging/deploy bug —
fail loud." Excluding the tree would make every `/help/<slug>/` page raise
`FileNotFoundError` in production. Only the sub-trees the running app never reads are
excluded above.

- [ ] **Step 3: Write the `Dockerfile`**

```dockerfile
# libli production image. Single-stage: uv makes the dependency install fast
# enough that a builder stage buys little, and the runtime needs the same
# interpreter anyway.
FROM python:3.13-slim

# UV_FROZEN: never re-resolve at runtime. Without it every `uv run` in the
# entrypoint re-checks the lockfile, which can become a network operation on a
# box with restricted egress.
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_FROZEN=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

# curl for the compose healthcheck defined in Task 5. libpq5 is belt-and-braces:
# psycopg[binary] ships its own libpq, so it is only needed if that pin is ever
# swapped for a source build.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/*

# Pinned: :latest would let a uv release change `sync`/`run` behaviour and break
# the deploy with no diff in the repo.
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, so a source-only change does not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# collectstatic MUST run at build time, not at boot: STORAGES["staticfiles"] is
# whitenoise's CompressedManifestStaticFilesStorage (config/settings/base.py:156),
# which is manifest-based -- without the manifest in the image every {% static %}
# reference raises at runtime.
#
# A throwaway SECRET_KEY and a dummy DATABASE_URL. NOT because settings import
# needs them -- base.py:14 and base.py:84 both carry defaults -- but so the build
# is explicit about its configuration and never bakes the insecure dev default
# into a compiled module or a build log.
#
# /app/.venv/bin/python, NOT `uv run`: uv run re-syncs the environment before
# executing and does NOT inherit the --no-dev above, so it would reinstall
# pytest, pytest-django, pytest-xdist and pytest-playwright into the production
# image -- and need network access on a layer that should need none.
RUN DJANGO_SECRET_KEY=build-only-not-a-runtime-secret \
    DATABASE_URL=postgres://u:p@localhost:5432/db \
    /app/.venv/bin/python manage.py collectstatic --noinput

# locale/*/LC_MESSAGES/*.mo are committed, so no compilemessages step.

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
```

**The container runs as root, and that is an accepted risk for this demo, not an
oversight.** A non-root `USER` is the better posture, but the four named volumes are
created root-owned on first `up`, so adding it without also fixing volume ownership
produces a container that cannot write `media/` or `transfer_staging/` — a new failure mode
introduced at the last step before a live deploy. Revisit it when this stack carries
anything beyond demo data; record it in the runbook's "Known constraints".

- [ ] **Step 4: Write `docker-entrypoint.sh`**

Use LF line endings. On Windows confirm with `file docker-entrypoint.sh` — a CRLF shebang fails with `no such file or directory`.

```bash
#!/bin/sh
# libli container entrypoint. Ordered bootstrap, then either the command passed
# as arguments or the app server.
#
# Safe ONLY because there is exactly one app container: `migrate` here would
# race between replicas. Do not scale this service.
set -eu

VENV_PY=/app/.venv/bin/python

echo "==> waiting for the database"
i=0
until "$VENV_PY" -c "
import django
django.setup()
from django.db import connection
connection.ensure_connection()
"; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    echo "!! database unreachable after 60 attempts; refusing to start" >&2
    exit 1
  fi
  sleep 2
done

echo "==> migrate"
"$VENV_PY" manage.py migrate --noinput

# Unconditional, even though init_platform also calls it. Permissions live as
# constants in institution/roles.py but are only ASSIGNED by seed_roles(); on an
# already-bootstrapped instance init_platform is skipped below, so this would be
# the only caller. No test can catch its omission -- tests/factories.py calls
# seed_roles() itself, so the suite passes either way.
echo "==> setup_roles"
"$VENV_PY" manage.py setup_roles

# Site #1 ships as example.com and build_accept_url builds invitation and
# password-reset links from it. A no-op when DJANGO_SITE_DOMAIN is unset.
echo "==> set_site_domain"
# --only-if-placeholder: DJANGO_SITE_DOMAIN is mandatory on this stack (compose
# guards it with :?), so without the flag this would rewrite the Site on EVERY
# boot -- silently reverting any correction a Platform Admin made through the
# settings UI, which restart: unless-stopped makes routine. Env seeds the value
# once; the UI owns it thereafter.
# --name too: Django ships Site #1 with name AND domain as "example.com", and
# allauth prefixes every account email subject with "[{site.name}] ". The
# ${VAR:+...} form omits the flag entirely when DJANGO_SITE_NAME is unset.
"$VENV_PY" manage.py set_site_domain --only-if-placeholder \
  ${DJANGO_SITE_NAME:+--name "$DJANGO_SITE_NAME"}

# Only when fully specified: init_platform fails fast on missing credentials
# when non-interactive, which must not stop a healthy instance from booting.
if [ -n "${INIT_ADMIN_USERNAME:-}" ] \
   && [ -n "${INIT_ADMIN_EMAIL:-}" ] \
   && [ -n "${INIT_ADMIN_PASSWORD:-}" ]; then
  echo "==> init_platform"
  "$VENV_PY" manage.py init_platform
else
  echo "==> init_platform skipped (INIT_ADMIN_* not fully set)"
fi

# `docker compose run app <cmd>` must run <cmd>, not silently boot a web server.
if [ "$#" -gt 0 ]; then
  echo "==> exec $*"
  exec "$@"
fi

echo "==> gunicorn"
# The venv binary directly, NOT `uv run gunicorn`: gunicorn must be PID 1 so it
# receives SIGTERM itself. With --timeout 1800 chosen so a 25-minute import is
# not killed, a TERM swallowed by an intermediate process is a data-loss path.
#
# --timeout 1800: a multi-GB course import occupies one worker for ~25 minutes
# of sustained upload; the 30s default would kill it mid-stage.
# --threads: keeps the site responsive while one worker is consumed by that import.
exec /app/.venv/bin/gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-1800}" \
  --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-120}" \
  --access-logfile - \
  --error-logfile -
```

- [ ] **Step 5: Build the image**

```bash
docker build -t libli:local .
```

Expected: builds clean. The `collectstatic` layer must report the number of files copied — if it errors on a missing static reference, that is a real bug to fix now, not at deploy time.

Then confirm the production image carries no test dependencies and no secrets:

```bash
docker run --rm --entrypoint sh libli:local -c 'ls /app/.venv/bin | grep -c pytest || true'   # MUST be 0
docker run --rm --entrypoint sh libli:local -c 'ls -a /app | grep "^\.env" || echo "no env files"'
```

Expected: `0`, then `no env files`. A non-zero pytest count means `uv run` crept back into a build layer; an `.env*` file means the `.dockerignore` exclusion is wrong and secrets are baked into a layer.

- [ ] **Step 6: Verify the bootstrap starts and gunicorn is not reached**

```bash
docker run --rm libli:local /app/.venv/bin/python -c "print('exec-ok')" 2>&1 | tail -3
```

Expected: it reaches `==> waiting for the database` and eventually exits non-zero (no database is running) — which proves the bootstrap runs. What matters is that it does **not** print `==> gunicorn`.

**This takes about four minutes**: the DB-wait loop is 60 attempts of `django.setup()` plus `sleep 2`. That is not a hang. To shorten it, temporarily lower the `-ge 60` ceiling while testing.

**The loop alone cannot tell you *why* it failed.** It swallows every probe failure, and `DATABASE_URL` and `DJANGO_SECRET_KEY` both have defaults (`base.py:84`, `base.py:14`) — so a typo in `DJANGO_SETTINGS_MODULE` or any import-time error in `config.settings.production` produces a byte-identical result to "no database". Run the probe once, directly, to discriminate:

```bash
docker run --rm --entrypoint /app/.venv/bin/python libli:local -c   "import django; django.setup(); from django.db import connection; connection.ensure_connection()"
```

Expected: `OperationalError` (nothing is listening). An `ImproperlyConfigured`, `ImportError` or `ModuleNotFoundError` means the image is broken, not the database absent — fix that before going further.

Do **not** verify this with `docker run --entrypoint sh` — replacing the entrypoint bypasses the very script under test, so such a check proves only that the image contains a shell. The full passthrough test runs against the live stack in Task 5 Step 5.

The *ordering* of the bootstrap is verified in Task 5 Step 5 against the runtime log, not by grepping this file — grepping the file just written proves only that `COPY` worked.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock Dockerfile docker-entrypoint.sh .dockerignore
git commit -m "feat(deploy): production image and ordered entrypoint

gunicorn was not a dependency at all. collectstatic runs at build time
because whitenoise's manifest storage needs the manifest in the image.
setup_roles runs unconditionally: init_platform is conditional, and no
test can catch a missing role seed.

gunicorn is exec'd from the venv rather than through `uv run` so it is
PID 1 and receives SIGTERM itself; with --timeout 1800 a swallowed TERM
would abort an in-flight import."
```

---

### Task 5: Compose stack, Caddyfile, env example, local smoke test

**Files:**
- Create: `docker-compose.prod.yml`, `Caddyfile`, `.env.production.example`
- Modify: `.gitignore` (Step 4 widens the `.env` rule; Step 6 commits it)

**Interfaces:**
- Consumes: the image, `/healthz/`, and the argument passthrough from Task 4; `LIBLI_TRANSFER_MAX_*` from Task 1; `DJANGO_SITE_DOMAIN` from Task 2.
- Produces: service names `app`, `db`, `caddy`; volumes `pgdata`, `media`, `transfer_staging`, `upload_tmp`, `support_screenshots`, `caddy_data`, `caddy_config` (seven). Task 6's runbook references these by name.

Named `docker-compose.prod.yml`, not `docker-compose.yml`, so it can never be picked up by a bare `docker compose` in the repo root alongside the existing `docker-compose.test.yml`. The app's env file is `.env.production`, **not** `.env` — the repo root already holds a local-dev `.env` with `DJANGO_DEBUG=true`, and pointing the container at it would inline local settings into a production run.

- [ ] **Step 1: Write `Caddyfile`**

```
# libli reverse proxy.
#
# Caddy, not nginx, for two measured reasons:
#  - nginx buffers the whole request body to disk before proxying
#    (proxy_request_buffering on by default), adding a FOURTH multi-GB copy
#    during a large course import. Caddy streams request bodies.
#  - file_server implements HTTP Range. Django implements none anywhere in its
#    response stack, and core/media_serve.py (which adds it) is DEBUG-only, so
#    without a Range-capable server a student cannot seek inside a <video>.

{$SITE_ADDRESS} {
	encode zstd gzip

	# Media is served straight off the volume: Django never sees it, so 3.7 GB
	# of mp4 traffic never occupies a gunicorn worker.
	handle_path /media/* {
		root * /srv/media
		file_server
	}

	# /static/ is deliberately NOT routed here. Whitenoise serves it from inside
	# the app so its hashed manifest stays authoritative.
	#
	# transfer_staging/ and support_screenshots/ are deliberately NOT routed
	# here either, and must never be: staged archives are raw unvalidated
	# uploads, and screenshots may carry another student's grades. Step 5 and
	# the runbook both prove they 404 with a real request, not a grep.

	handle {
		reverse_proxy app:8000 {
			header_up X-Forwarded-Proto {scheme}
		}
	}

	request_body {
		max_size {$CADDY_MAX_BODY:1200MiB}
	}
}
```

- [ ] **Step 2: Write `docker-compose.prod.yml`**

```yaml
# libli production stack. ONE app container by design -- `migrate` runs in the
# entrypoint, and TRANSFER_STAGING_DIR is a local volume that the preview and
# confirm requests of one import must both see. Do not scale `app`.
name: libli

services:
  db:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-libli}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env.production}
      POSTGRES_DB: ${POSTGRES_DB:-libli}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-libli}"]
      interval: 5s
      timeout: 5s
      retries: 20

  app:
    build: .
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    env_file: .env.production
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.production
      DATABASE_URL: postgres://${POSTGRES_USER:-libli}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-libli}
      DJANGO_BEHIND_PROXY: "true"
      # Interpolation-time guard, so a blank fails at `up` rather than silently
      # falling back to base.py's "dev-insecure-key-change-me". The :? form
      # fires on unset OR empty, which "fill every blank" in a runbook cannot.
      DJANGO_SECRET_KEY: ${DJANGO_SECRET_KEY:?set DJANGO_SECRET_KEY in .env.production}
      DJANGO_SITE_DOMAIN: ${DJANGO_SITE_DOMAIN:?set DJANGO_SITE_DOMAIN in .env.production}
      # Django spills uploads above FILE_UPLOAD_MAX_MEMORY_SIZE to the system
      # temp dir BEFORE the view moves them to TRANSFER_STAGING_DIR. Left at the
      # default that is a multi-GB write to the container's overlay filesystem on
      # the host root disk. Its OWN volume, deliberately NOT transfer_staging:
      # staging.sweep() (courses/transfer/staging.py:22) unlinks ANY file there
      # past the age cap, which would delete an in-flight spill.
      DJANGO_FILE_UPLOAD_TEMP_DIR: /app/upload_tmp
    volumes:
      - media:/app/media
      - transfer_staging:/app/transfer_staging
      - upload_tmp:/app/upload_tmp
      - support_screenshots:/app/support_screenshots
    expose:
      - "8000"
    healthcheck:
      # Gates caddy's start: without it the first requests after a deploy 502
      # while migrate runs, which is also when Caddy is completing ACME.
      #
      # Both headers are load-bearing:
      #  - Host: the request must present a name in DJANGO_ALLOWED_HOSTS or
      #    get_host() raises DisallowedHost -> 400 -> never healthy -> caddy
      #    never starts and the site is unreachable. "localhost" is in the
      #    shipped example's ALLOWED_HOSTS for exactly this reason.
      #  - X-Forwarded-Proto: with SECURE_SSL_REDIRECT=True (production.py:6)
      #    SecurityMiddleware answers plain HTTP with a 301 BEFORE the view runs,
      #    and `curl -f` treats a 301 as success -- degrading the check to
      #    "gunicorn accepted a socket". This makes request.is_secure() true so
      #    the check reaches the view.
      # Asserting the body, not just the status, is what makes it a real check.
      test:
        - CMD-SHELL
        - >-
          curl -fsS -H "Host: ${DJANGO_SITE_DOMAIN:-localhost}"
          -H "X-Forwarded-Proto: https"
          http://127.0.0.1:8000/healthz/ | grep -q '"status": *"ok"'
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 60s

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    depends_on:
      app:
        condition: service_healthy
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    environment:
      SITE_ADDRESS: ${SITE_ADDRESS:?set SITE_ADDRESS in .env.production}
      CADDY_MAX_BODY: ${CADDY_MAX_BODY:-1200MiB}
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      # Read-only: Caddy serves media, it never writes it.
      - media:/srv/media:ro
      - caddy_data:/data
      - caddy_config:/config

volumes:
  pgdata:
  media:
  transfer_staging:
  upload_tmp:
  support_screenshots:
  caddy_data:
  caddy_config:
```

- [ ] **Step 3: Write `.env.production.example`**

```bash
# Copy to .env.production next to docker-compose.prod.yml and fill in. Never
# commit the filled copy. NOT named .env -- the repo root already holds a
# local-dev .env with DJANGO_DEBUG=true.

# --- identity ---
# The address Caddy answers on and requests a certificate for. A bare hostname
# gets automatic HTTPS from Let's Encrypt. Use http://localhost for a local
# smoke test, which skips ACME entirely.
SITE_ADDRESS=libli.example.org

# Host part only. Used to build invitation and password-reset links, which come
# from the django.contrib.sites Site record, not the request Host header.
DJANGO_SITE_DOMAIN=libli.example.org

# localhost is REQUIRED here, not optional: the app container's healthcheck
# requests /healthz/ over the loopback, and a host outside this list raises
# DisallowedHost -> 400 -> the container never becomes healthy -> caddy never
# starts. Keep it even though nobody browses to it.
DJANGO_ALLOWED_HOSTS=libli.example.org,localhost,127.0.0.1
# Shown in allauth email subjects as "[<name>] ". Left unset, Site #1 keeps
# Django's "example.com" placeholder there even once the domain is correct.
DJANGO_SITE_NAME=libli
DJANGO_CSRF_TRUSTED_ORIGINS=https://libli.example.org

# --- secrets ---
# generate: python -c "import secrets; print(secrets.token_urlsafe(64))"
DJANGO_SECRET_KEY=
# generate the same way
POSTGRES_PASSWORD=
POSTGRES_USER=libli
POSTGRES_DB=libli

# --- first Platform Admin (read by init_platform; omit to skip bootstrap) ---
# The password must satisfy Django's validators (length, not-too-common, not
# similar to the username/email). init_platform raises CommandError otherwise,
# which under `set -e` kills the entrypoint -- and with restart: unless-stopped
# the container then crash-loops with caddy's health gate never releasing.
# If the site never comes up, check: logs app | grep '==> init_platform'
INIT_ADMIN_USERNAME=admin
INIT_ADMIN_EMAIL=admin@example.org
INIT_ADMIN_PASSWORD=

# --- email (left unset, mail is logged to the console, visibly unconfigured) ---
# DJANGO_EMAIL_HOST=smtp.example.org
# DJANGO_EMAIL_PORT=587
# DJANGO_EMAIL_HOST_USER=
# DJANGO_EMAIL_HOST_PASSWORD=
# DJANGO_EMAIL_USE_TLS=true
# DJANGO_DEFAULT_FROM_EMAIL=libli <no-reply@example.org>

# --- gunicorn ---
# 1800s covers a multi-GB course upload; the 30s default kills it mid-stage.
GUNICORN_WORKERS=2
GUNICORN_THREADS=4
GUNICORN_TIMEOUT=1800
GUNICORN_GRACEFUL_TIMEOUT=120

# --- transfer caps: RAISE ONLY IF YOU HOST AN OVERSIZED COURSE ---
# The shipped defaults (1 GiB / 1.5 GiB / 1000 entries) are deliberate
# guardrails. The matematyka demo course needs all three raised: it is 1,194
# media assets and ~3.8 GB, and mp4 does not compress.
# CADDY_MAX_BODY must be raised to match, or Caddy rejects the upload before
# Django ever sees it.
# LIBLI_TRANSFER_MAX_COMPRESSED_BYTES=5368709120
# LIBLI_TRANSFER_MAX_UNCOMPRESSED_BYTES=6442450944
# LIBLI_TRANSFER_MAX_MEDIA_ENTRIES=2000
# Measured: matematyka is 20,226 elements against a default of 20,000. Enforced
# on IMPORT only, so an un-raised cap rejects the archive after the whole upload.
# LIBLI_TRANSFER_MAX_ELEMENTS=25000
# CADDY_MAX_BODY=5500MiB
```

- [ ] **Step 4: Validate the compose file**

```bash
cp .env.production.example .env.production
printf '\nPOSTGRES_PASSWORD=localsmoke\nDJANGO_SECRET_KEY=localsmoke\n' >> .env.production
sed -i 's|^SITE_ADDRESS=.*|SITE_ADDRESS=http://localhost|' .env.production
sed -i 's|^DJANGO_CSRF_TRUSTED_ORIGINS=.*|DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost|' .env.production
sed -i 's|^DJANGO_SITE_DOMAIN=.*|DJANGO_SITE_DOMAIN=localhost|' .env.production

docker compose -f docker-compose.prod.yml --env-file .env.production config \
  | grep -E "DJANGO_SETTINGS_MODULE|DJANGO_FILE_UPLOAD_TEMP_DIR"
```

Expected: `DJANGO_SETTINGS_MODULE: config.settings.production` and the `DJANGO_FILE_UPLOAD_TEMP_DIR` line. If `config.settings.local` appears, the service is reading the wrong env file.

**`DJANGO_ALLOWED_HOSTS` is deliberately NOT overridden** — it keeps the shipped example's
value, which now includes `localhost`. Rewriting it would make the local run the one
configuration in which a broken healthcheck can still pass, which is how the
`DisallowedHost` bug hid in an earlier draft.

**`DJANGO_SECURE_SSL_REDIRECT=false` IS required locally**, and the reason matters. Caddy
sends `X-Forwarded-Proto: {scheme}`, and on an `http://localhost` site `{scheme}` is
`http`. With `DJANGO_BEHIND_PROXY=true` Django trusts that header, so `request.is_secure()`
is **False**, and `SECURE_SSL_REDIRECT` (True by default, `config/settings/production.py:6`)
makes `SecurityMiddleware` return a **301** before any view runs. Every app-routed check
below would then get 301 instead of 200/404 — including the two staging-directory checks
that must be 404 — while only the `/media/` Range check survives, because Caddy answers
that one without Django. The container healthcheck is unaffected only because it hand-sets
`X-Forwarded-Proto: https`.

```bash
printf '\nDJANGO_SECURE_SSL_REDIRECT=false\n' >> .env.production
```

This is the one axis on which local and production legitimately differ, and it is a
documented knob (`.env.example` lists it). Everything else stays as shipped.

Note this `config` check proves only that the *variable* reaches the container. That
`FILE_UPLOAD_TEMP_DIR` is actually *applied* is proven at runtime in Step 5 — a grep of
rendered compose output is the same grep-instead-of-request weakness this plan rejects
elsewhere.

**`.gitignore:10` is the literal string `.env`, not a glob — so `.env.production` is NOT ignored.** Before creating the file, change that line to `.env*` and add `!.env.example` and `!.env.production.example` beneath it (both are committed and must stay tracked), then confirm with `git check-ignore -v .env.production`. A filled secrets file showing up in `git status` is one careless `git add -A` from being committed.

- [ ] **Step 5: Run the whole stack locally — the real verification**

This is the first time `app`, `db` and `caddy` run together. Every integration failure the
build steps cannot see — the DB-wait loop, `migrate` under the production settings module,
whitenoise behind Caddy, the media mount, `env_file` resolution, the gunicorn bind, the
healthcheck gate — surfaces here rather than on the VPS with ACME in flight.

`SITE_ADDRESS=http://localhost` makes Caddy serve plain HTTP and skip Let's Encrypt.

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f app     # Ctrl-C once gunicorn starts
```

Assert the bootstrap ran in the right order — against the **runtime log**, not the script:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production logs app | grep '==>'
```

Expected, in this order: `waiting for the database`, `migrate`, `setup_roles`,
`set_site_domain`, `init_platform` (or its "skipped" line), `gunicorn`.

Then:

```bash
# a media file to range-test
docker compose -f docker-compose.prod.yml --env-file .env.production exec app \
  sh -c 'mkdir -p /app/media/smoke && head -c 1048576 /dev/urandom > /app/media/smoke/probe.bin'

curl -sI http://localhost/healthz/                                   # 200
curl -sI http://localhost/                                           # 200 -- the landing page
# Whitenoise serves BOTH admin/css/base.css and admin/css/base.<hash>.css from
# STATIC_ROOT, so the un-hashed path returns 200 even with a broken manifest --
# while every {% static %} call raises. Resolve a real hashed name and request THAT.
MANIFEST=/app/staticfiles/staticfiles.json
HASHED=$(docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app \
  /app/.venv/bin/python -c "import json; print(json.load(open('$MANIFEST'))['paths']['admin/css/base.css'])" \
  | tr -d '\r')
echo "resolved: $HASHED"
curl -sI "http://localhost/static/$HASHED"                           # 200

# Range: a GET with the body discarded, NOT a HEAD. Range-on-HEAD is a file-server
# implementation detail; a <video> issues a GET, so that is what must be proven.
curl -s -o /dev/null -D - -r 0-100 http://localhost/media/smoke/probe.bin | head -5
#   MUST be 206 Partial Content with accept-ranges: bytes

# FILE_UPLOAD_TEMP_DIR is APPLIED, not merely present in the environment. Django
# reads settings from the settings module; an env var alone changes nothing.
docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app \
  /app/.venv/bin/python -c \
  "from django.conf import settings; print(settings.FILE_UPLOAD_TEMP_DIR)"
#   MUST print /app/upload_tmp

# The Site domain was actually WRITTEN. "==> set_site_domain" in the log is an
# unconditional echo -- it prints whether the command wrote, no-op'd, or was
# skipped by --only-if-placeholder. This is one of the two headline defects the
# whole plan exists to fix, so it gets a real read, not a log grep.
docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app   /app/.venv/bin/python -c   "import django; django.setup(); from django.contrib.sites.models import Site; print(Site.objects.get_current().domain)"
#   MUST print localhost -- NOT example.com

# The staging directories must NOT be reachable. A grep of the Caddyfile cannot
# prove this; a request can.
curl -so /dev/null -w '%{http_code}\n' http://localhost/transfer_staging/
curl -so /dev/null -w '%{http_code}\n' http://localhost/support_screenshots/
#   both MUST be 404 (or 403) -- never 200 and never a directory listing

# Argument passthrough (Task 4's interface)
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm app \
  /app/.venv/bin/python manage.py showmigrations --plan | tail -3
```

Tear down, destroying the volumes so nothing local leaks into a later run:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production down -v
rm .env.production
```

- [ ] **Step 6: Commit**

```bash
git add docker-compose.prod.yml Caddyfile .env.production.example .gitignore
git commit -m "feat(deploy): compose stack with Caddy serving media

Caddy over nginx for two reasons that matter at this size: it streams
request bodies (nginx buffers the whole body to disk, a fourth multi-GB
copy during import) and its file_server does HTTP Range, which Django
does not implement anywhere and which video seeking requires.

FILE_UPLOAD_TEMP_DIR gets its OWN upload_tmp volume -- deliberately not
transfer_staging, whose sweep() unlinks any file past the age cap and would
delete an in-flight spill. Django spills large uploads to the temp dir before
the view stages them, which by default is a multi-GB write to the container
overlay on the root disk.

transfer_staging and support_screenshots are volumes but deliberately
have no Caddy route, proven by a request rather than a grep."
```

---

### Task 6: The runbook

**Files:**
- Create: `docs/deployment.md`
- Modify: `docs/roadmap.md` — the "Non-technical deployment/install" bullet (begins at line **174**); point it at the new doc.

**Interfaces:**
- Consumes: every artifact from Tasks 1-5.
- Produces: nothing consumed by code.

- [ ] **Step 1: Write `docs/deployment.md`**

1. **Provision.** Contabo VPS, Ubuntu 24.04, **50 GB disk minimum** (peak usage during a matematyka import is ~17 GB; steady is ~9 GB). Order early — Contabo accounts sometimes get manual review before provisioning, which can take a day.

   ```bash
   # on the VPS, as root
   apt-get update && apt-get install -y ca-certificates curl git
   install -m 0755 -d /etc/apt/keyrings
   curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
   chmod a+r /etc/apt/keyrings/docker.asc
   echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
     https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
     > /etc/apt/sources.list.d/docker.list
   apt-get update
   apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
   ```

2. **DNS.** An `A` record for `SITE_ADDRESS` pointing at the VPS, resolving *before* first boot — Caddy requests a certificate on startup and retries noisily otherwise. Confirm from the VPS:

   ```bash
   getent hosts libli.example.org      # must return this VPS's address
   ```

3. **Clone, configure, boot.**

   ```bash
   git clone <repo-url> /opt/libli && cd /opt/libli
   cp .env.production.example .env.production
   python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # DJANGO_SECRET_KEY
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # POSTGRES_PASSWORD
   nano .env.production   # fill every blank AND replace every libli.example.org

   # Four keys ship with the PLACEHOLDER hostname rather than a blank, so
   # "fill every blank" misses them and the compose :? guards do not fire on a
   # non-empty wrong value. A stale DJANGO_ALLOWED_HOSTS makes the healthcheck
   # 400 -> the app never becomes healthy -> caddy never starts -> the site is
   # simply unreachable. A stale CSRF origin 403s every wizard POST instead.
   grep -n 'example\.org' .env.production   # MUST return nothing before you boot
   chmod 600 .env.production
   docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
   docker compose -f docker-compose.prod.yml --env-file .env.production logs -f app
   ```

   The log must show, in order: `waiting for the database`, `migrate`, `setup_roles`, `set_site_domain`, `init_platform`, `gunicorn`.

4. **Verify** — run every check in Step 2 below before going further.

5. **Walk the first-run wizard** at `https://<host>/manage/setup/` (the route is `manage/setup/`, `institution/urls.py:57` — there is no bare `/setup/`), signed in as the `INIT_ADMIN_USERNAME` account. Confirm the Identity step shows the **Public hostname** field pre-filled with the value the entrypoint set, and that the five steps (Welcome → Identity → Access → Team → SSO) complete. This is the non-developer surface — walk it as a school admin would, without a shell open.

   **On the Access step, leave the signup policy on `invite`.** This is a public box with a
   real DNS name; "open" means strangers can self-register on it. `init_platform` defaults
   to invite, so this is a matter of not changing it. Verify afterwards:

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app \
     /app/.venv/bin/python -c \
     "import django; django.setup(); from institution.models import Institution; print(Institution.load().signup_policy)"
   # MUST print: invite
   ```

6. **Load matematyka.** This is the step that delivers the demo, and it is a multi-GB
   upload over the operator's own connection — budget ~25 minutes of sustained transfer
   and do it on a link you can leave alone.

   **6a. Raise the caps on the server.** In `.env.production`, uncomment **all four**
   `LIBLI_TRANSFER_MAX_*` overrides (compressed, uncompressed, media entries **and
   elements**) and `CADDY_MAX_BODY`, then apply and confirm headroom:

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production up -d
   df -h /                      # MUST show >= 17 GB free before you start
   ```

   **6b. Export from your local instance.** With the local dev server running, sign in as
   a user who can manage the course and open the builder for matematyka
   (`/manage/courses/<slug>/`). Use its **Export course** action
   (`courses:manage_course_export`). The browser downloads a single `.zip`; expect roughly
   the size of `media/` (~3.8 GB), since mp4 does not compress. If an export pre-flight
   page appears listing problems, read it — confirming past it is `?confirm=1`.

   **Free ~8 GB on the drive holding your system temp dir first.**
   `courses/views_transfer.py:59` builds the whole archive into a
   `SpooledTemporaryFile(max_size=32 MB)` **before** the response emits its first byte, so
   the archive exists twice locally: once spilled to temp, once as the download. Expect
   **several minutes with no browser progress at all** while it compresses 3.7 GB of
   incompressible mp4 — that is not a hang.

   **6c. Import on the server.** Open `https://<host>/manage/courses/import/`
   (`courses:manage_course_import`), choose the archive, and upload. This is a
   **two-request flow**: the upload is staged and a **preview** is rendered, then a
   separate **confirm** POST performs the import. Both requests must reach the same
   container — they do here, because there is exactly one `app` service and
   `TRANSFER_STAGING_DIR` is a local volume. Do not close the tab between the two.

   **Success** looks like: the preview page lists the course title and its node/media
   counts; after confirm, you land on the imported course's builder and
   `/manage/courses/` shows it.

   **On failure:** a dropped upload has **no resume** — the staged file is discarded and
   you start 6c again. If it fails twice, stop retrying and use the escape hatch the spec
   names: copy the archive to the box with `scp`/`rsync` and import it server-side with a
   small command wrapping `courses.transfer.importer.import_course()`. That command is not
   written yet; writing it is a ~20-line job and strictly better than a third upload.

   Distinguish a stall from progress by watching the staged file grow:

   ```bash
   watch -n 10 'docker compose -f docker-compose.prod.yml --env-file .env.production \
     exec -T app sh -c "ls -l /app/transfer_staging /app/upload_tmp"'
   ```

   After success, delete the staged archive rather than waiting out the 6-hour `TRANSFER_STAGING_MAX_AGE_HOURS`:

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production exec app \
     sh -c 'rm -f /app/transfer_staging/*.zip'
   ```

   Then **lower the caps back** and `up -d` again, so the demo box does not sit with a 5 GB upload ceiling.

7. **Sanity-check the import.** Confirm the course arrived with the structure you expect —
   the importer assigns the slug, so it is not guaranteed to be `matematyka`, and knowing
   the real one saves confusion later:

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production exec app \
     /app/.venv/bin/python manage.py shell -c "
   from courses.models import ContentNode, Course, MediaAsset
   for c in Course.objects.all():
       print(c.pk, repr(c.slug), c.title,
             '| nodes:', ContentNode.objects.filter(course=c).count(),
             '| media:', MediaAsset.objects.filter(course=c).count())
   "
   ```

   For matematyka expect roughly **1,010 nodes and 1,194 media assets**. A materially
   lower media count means the archive was truncated — re-import rather than proceeding.

8. **Seed the second, smaller course.** `seed_demo_course` is already written and
   idempotent, so this is one line:

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production exec app \
     /app/.venv/bin/python manage.py seed_demo_course
   ```

   **Fake students and analytics data are deliberately NOT part of this deployment.**
   The `seed_demo_activity` command is a separate piece of work with its own spec and
   plan, written against the imported matematyka rather than guessed at in advance — see
   "After the plan". Until it lands, the analytics matrix on matematyka is empty, which is
   expected, not a deployment fault. Demo Course carries the one seeded student
   `seed_demo_course` already creates.

9. **Schedule the notification purge.** There is no built-in scheduler and the table grows
   without one. `docs/local-development.md:55` gives the host form (`cd /app && uv run …`),
   which does **not** apply here — this deployment runs the command inside the container:

   ```cron
   # /etc/crontab or `crontab -e` on the VPS — daily at 03:30
   30 3 * * * cd /opt/libli && docker compose -f docker-compose.prod.yml \
     --env-file .env.production exec -T app \
     /app/.venv/bin/python manage.py purge_notifications
   ```

   `exec -T` is required: cron has no TTY. Test it once by hand with `--dry-run` first.

10. **Known constraints.** One app container only. No backups. `TRANSFER_STAGING_DIR` and `SUPPORT_SCREENSHOT_DIR` must never be web-served. Signup policy stays `invite`. The app container runs as root (accepted; see Task 4). After changing the hostname through the settings UI, `restart app` so every gunicorn worker picks it up — `SITE_CACHE` is per-process. The same applies to **any** settings or branding change: there is no `CACHES` setting, so Django's default LocMemCache is per-process too, and `core/services.py:17` caches the whole site-config bundle for `CACHE_TTL = 300`. With two workers, up to five minutes of refreshes can alternate between old and new values. `restart app` clears it immediately. Peak disk during import is ~17 GB including the `FILE_UPLOAD_TEMP_DIR` copy.

- [ ] **Step 2: Put the post-deploy checks in the runbook verbatim**

```bash
# Pick a real media file first -- this check is the one most likely to be
# skipped, and a placeholder path is why.
MP4=$(docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app \
        sh -c 'find /app/media -name "*.mp4" | head -1' | tr -d '\r')
REL=${MP4#/app/media/}
echo "https://<host>/media/$REL"

# Video seeking. A 200 here means every student's <video> is unseekable --
# the page looks fine and only someone trying to replay a passage finds out.
# A GET with the body discarded, NOT a HEAD: Range-on-HEAD is a file-server
# implementation detail, whereas a <video> element issues a GET.
curl -s -o /dev/null -D - -r 0-100 "https://<host>/media/$REL" | head -5
# MUST show: HTTP/2 206  and  accept-ranges: bytes

curl -sI https://<host>/healthz/                               # 200
curl -sI https://<host>/                                       # 200 -- the landing page
curl -sI "https://<host>/static/$HASHED"                       # 200 ($HASHED as in Task 5 Step 5)
curl -sI http://<host>/ | head -3                              # 301/308 to https

# Staging dirs must be unreachable -- a request, not a grep.
curl -so /dev/null -w '%{http_code}\n' https://<host>/transfer_staging/
curl -so /dev/null -w '%{http_code}\n' https://<host>/support_screenshots/
# both MUST be 404/403

df -h /                                                        # ≥17 GB before importing
```

- [ ] **Step 3: Update the roadmap**

In `docs/roadmap.md`, amend the "Non-technical deployment/install" bullet (line 174) to note that the containerised install now exists and point at `docs/deployment.md`. Keep the edit **line-count neutral** if practical — line-inserting diffs rot `file:line` citations elsewhere in the docs.

- [ ] **Step 4: Commit**

```bash
git add docs/deployment.md docs/roadmap.md
git commit -m "docs: deployment runbook

Includes the Range check on /media/, which is the one post-deploy
verification that must not be skipped: a 200 there is a silent failure.
The slug and subtree pk are looked up rather than assumed -- the importer
assigns the slug."
```

---

## Deliberately out of scope: the demo-activity seeder

An earlier draft carried a seventh artifact, `seed_demo_activity`, generating ~20 fake
students and enough quiz activity to populate the analytics matrix. **It was split out
after three review rounds**, and the reason is worth recording so it is not merged back
in casually.

Every other task in this plan went quiet after round 1. The seeder produced new CRITICAL
defects in all three rounds, each time because generating *semantically valid* quiz data
turns out to be coupled to domain rules that only surface when you run it against real
content: the score has to be derived from the answer or a correct answer sits beside a
failing mark; `_quiz_review_maps` derives `total_review` from a unit's REVIEW **elements**,
so skipping one unanswerable question silently drops the whole submission from the matrix;
and tying quiz attempts to lesson progress means nobody reaches a quiz on a course whose
quizzes sit at the end. Each fix created the next defect.

That is a signal the work was being specified too far ahead of execution. It gets its own
spec and plan, written **after** matematyka is imported, against the question types that
course actually contains — which the audit command below can then answer for real rather
than in the abstract.

The restructured draft is not lost: it is in this branch's history at commit `8dae86e3`,
including the derived-score model, the whole-unit skip, and twelve named mutants. Start
from it rather than from scratch.

Consequence for this deployment: the analytics matrix on matematyka will be empty until
that work lands. `seed_demo_course` still provides a second course with one enrolled
student, so the analytics surfaces are reachable and demonstrable, just sparse.

## After the plan

Once the box is live, the seeder above is the immediate follow-up, and two memory files are stale and must be corrected rather than left:

- `no-deployment-no-prod-db` becomes **false**. Rewrite it; do not delete it.
- `first-deployment-checklist`'s deferred items (migration 0060 + `FORMAT_VERSION 13`, the internal-link cutover runbook with `--start-at`) become live work.

Run the full suite as a branch gate before opening the PR — not per task:

```bash
docker compose -f docker-compose.test.yml up -d
uv run python -m pytest -n auto
uv run ruff check . --no-cache && uv run ruff format --check .
```

Grep the summary line rather than trusting the exit code, which can report 0 alongside `1 failed`.
