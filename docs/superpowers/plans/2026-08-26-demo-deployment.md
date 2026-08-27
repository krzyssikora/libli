# Containerised demo deployment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build libli's first deployment — a containerised install (`app`, `db`, `caddy`) that stands up a working instance on a single Contabo VPS, plus fixes for the two defects a real deployment exposes, plus a demo-data seeder.

**Architecture:** Caddy terminates TLS, serves `/media/` directly from a volume (giving HTTP Range, which Django lacks entirely), and reverse-proxies everything else to gunicorn. Whitenoise keeps `/static/` inside the app so its hashed manifest stays authoritative. A single `app` container runs an ordered entrypoint (`migrate` → `setup_roles` → Site domain → `init_platform` → gunicorn). Demo content is loaded separately and is not part of the install.

**Tech Stack:** Python 3.13, Django 5.2, PostgreSQL 16, uv, gunicorn, Caddy 2, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-26-demo-deployment-design.md`

## Global Constraints

- **Python `>=3.13`**, Django `>=5.2,<5.3`, PostgreSQL **16** (matches `.github/workflows/ci.yml`).
- **Exactly one `app` container.** This is what makes `migrate` in the entrypoint safe and lets `TRANSFER_STAGING_DIR` be a local volume. Do not add replicas.
- **Transfer-cap defaults must not change.** `TRANSFER_MAX_COMPRESSED_BYTES` stays `1 * 1024**3`, `TRANSFER_MAX_UNCOMPRESSED_BYTES` stays `1536 * 1024**2`, `TRANSFER_MAX_MEDIA_ENTRIES` stays `1000`. Only their env-overridability is new.
- **`TRANSFER_STAGING_DIR` and `SUPPORT_SCREENSHOT_DIR` must never be web-served.** They must not appear in any Caddy route, and Task 6/7 both prove it with a real request, not a grep.
- **No hardcoded passwords** in new code. ruff `S105`/`S106`/`S107` are enabled outside `tests/`.
- **ruff must pass:** `uv run ruff check . --no-cache` and `uv run ruff format --check .` are separate gates. Note `B` (bugbear) and `S` (bandit) are selected — an unused loop variable (`B007`) and a bare `random.Random` (`S311`) both fail the build. `I` is selected too, and `ruff format` does NOT sort imports: run `uv run ruff check --fix` for `I001` before the gate.
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
- `courses/management/commands/seed_demo_activity.py` — demo student cohort + activity.

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
- `tests/test_transfer_caps_env.py`, `tests/test_site_domain.py`, `tests/test_seed_demo_activity.py`
- `tests/test_setup_wizard.py` — extended, not replaced.

Note `templates/institution/manage/_branding_fields.html` is included by **both** `templates/institution/setup/identity.html:8` and `templates/institution/manage/_branding_tab.html:13`. Adding the field there deliberately surfaces it on the manage settings page too, so a Platform Admin can correct the hostname after first run, not only during it.

---

### Task 1: Upload sizing settings become env-overridable

**Files:**
- Modify: `config/settings/base.py` lines 175, 176, 181, plus one new setting
- Test: `tests/test_transfer_caps_env.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: env var names `LIBLI_TRANSFER_MAX_COMPRESSED_BYTES`, `LIBLI_TRANSFER_MAX_UNCOMPRESSED_BYTES`, `LIBLI_TRANSFER_MAX_MEDIA_ENTRIES` (all integers, bytes / count), and `DJANGO_FILE_UPLOAD_TEMP_DIR` (path or unset). Task 6's compose file and `.env.production.example` set them; Task 7's runbook documents them.

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
spill files that Task 7's `rm -f …/*.zip` cleanup does not match.

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


def test_transfer_caps_are_env_overridable(reload_base):
    base = reload_base(
        {
            # 5 GiB, 6 GiB
            "LIBLI_TRANSFER_MAX_COMPRESSED_BYTES": "5368709120",
            "LIBLI_TRANSFER_MAX_UNCOMPRESSED_BYTES": "6442450944",
            "LIBLI_TRANSFER_MAX_MEDIA_ENTRIES": "2000",
        }
    )
    assert base.TRANSFER_MAX_COMPRESSED_BYTES == 5368709120
    assert base.TRANSFER_MAX_UNCOMPRESSED_BYTES == 6442450944
    assert base.TRANSFER_MAX_MEDIA_ENTRIES == 2000


def test_file_upload_temp_dir_defaults_to_none(reload_base):
    """Unset, Django falls back to the system temp dir -- correct for local dev."""
    base = reload_base({})
    assert base.FILE_UPLOAD_TEMP_DIR is None


def test_file_upload_temp_dir_is_env_overridable(reload_base):
    """Setting it in compose alone would do nothing: Django reads settings from
    the settings module, never from arbitrary environment variables."""
    base = reload_base({"DJANGO_FILE_UPLOAD_TEMP_DIR": "/app/transfer_staging"})
    assert base.FILE_UPLOAD_TEMP_DIR == "/app/transfer_staging"
```

Add `DJANGO_FILE_UPLOAD_TEMP_DIR` to `CAP_ENV_NAMES` in the fixture above so it is cleared alongside the other three.

- [ ] **Step 2: Run the test and confirm it fails**

```bash
uv run python -m pytest tests/test_transfer_caps_env.py -v
```

Expected: `test_transfer_caps_default_to_the_shipped_guardrails` PASSES (values are already correct), `test_transfer_caps_are_env_overridable` FAILS — `assert 1073741824 == 5368709120`.

- [ ] **Step 3: Make the caps env-overridable**

In `config/settings/base.py`, replace the assignments at lines 175, 176 and 181. Leave `TRANSFER_MAX_COURSE_JSON_BYTES`, `TRANSFER_MAX_MANIFEST_BYTES`, `TRANSFER_MAX_NODES`, `TRANSFER_MAX_ELEMENTS` untouched:

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
  - `institution.site_domain.validate_site_domain(value) -> str` — raises `django.core.exceptions.ValidationError` on a bad host. Task 3's form imports this.
  - `institution.site_domain.set_site_domain(domain, name=None) -> Site` — validates, writes, clears the sites-framework cache.
  - Management command `set_site_domain`, reading `--domain` or the `DJANGO_SITE_DOMAIN` env var. Task 5's entrypoint calls it.
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

Append to `tests/conftest.py`:

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
        "a" * 95 + ".example.org",     # 107 chars: Site.domain is max_length=100
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
    """
    from django.contrib.sites import models as sites_models

    assert sites_models.SITE_CACHE == {}
```

- [ ] **Step 3: Run the test and confirm it fails**

```bash
uv run python -m pytest tests/test_site_domain.py -v
```

Expected: all FAIL, in two distinct ways. The validator tests fail with `ModuleNotFoundError: No module named 'institution.site_domain'`; the four `call_command` tests fail with `CommandError: Unknown command: 'set_site_domain'`. Both are expected — a single failure mode here would mean one half was not written.

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
    through the settings UI, restart the app service -- Task 7 says so.
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

Expected: 19 passed (4 + 6 parametrised cases, plus 9 behaviour tests).

- [ ] **Step 7: Falsify — confirm the tests can fail**

Three mutants, run one at a time and edit each out by hand afterwards:

1. Delete the `Site.objects.clear_cache()` line in `set_site_domain`. Expected: `test_set_site_domain_clears_the_sites_cache` FAILS — the SITE_ID key is still present. (`test_set_site_domain_persists_to_the_database` correctly still passes; it tests a different guarantee.)
2. Change the no-op branch to `raise CommandError(...)`. Expected: `test_command_is_a_no_op_when_unset` FAILS.
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
    assert Site.objects.get(pk=dj_settings.SITE_ID).domain == "libli.example.org"


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

`PLACEHOLDER_DOMAIN` is a new constant in `institution/site_domain.py`, exported alongside
the validator so both halves agree on what "unset" looks like:

```python
# Django ships Site #1 with this domain. It is a valid hostname, so it passes
# validation -- it must be recognised by identity, not by rejection.
PLACEHOLDER_DOMAIN = "example.com"
```

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
                set_site_domain(hostname)
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

Four mutants, one at a time, each edited out by hand:

1. Delete the `set_site_domain(hostname)` call from `save()`. Expected: `test_identity_step_sets_the_site_domain` FAILS.
2. Change `clean_public_hostname` to `return value` without validating. Expected: `test_identity_step_rejects_a_url_in_the_hostname` FAILS (302 instead of 200, and the Site is corrupted).
3. Drop the `if commit and hostname:` guard so a blank writes through. Expected: `test_identity_step_blank_hostname_leaves_the_site_alone` FAILS — the domain is blanked.
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

### Task 4: `seed_demo_activity` management command

**Files:**
- Create: `courses/management/commands/seed_demo_activity.py`
- Test: `tests/test_seed_demo_activity.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: management command `seed_demo_activity`, invoked by Task 7's runbook as
  `seed_demo_activity --course <slug> --subtree <pk> --students 20 --groups 2 --seed 12345 --password <pw>`.

**Read `courses/management/commands/seed_demo_course.py:320-370` before starting.** It is the reference implementation for the submission/progress half, and its docstrings document two traps this command must not re-fall into.

Six hard constraints, each from existing code:

1. **Enrollment is derived, never written.** `grouping/services.py:127` defines reachability as group membership; `add_students_to_group` calls `recompute_enrollment` per student (`grouping/services.py:216`). Writing `Enrollment` rows directly produces state no production path produces.
2. **`UnitProgress` and `QuizSubmission` are separate writes.** `finalize_submission()` deliberately does not touch progress — see the docstring at `seed_demo_course.py:333`.
3. **Review-mode responses must be stamped `reviewed_at`.** `rollups.submission_is_counted` (`courses/rollups.py:402`) excludes a submission with any unreviewed `REVIEW` question, so its score would silently vanish from the matrix.
4. **No hardcoded password** — ruff `S106`.
5. **`set_user_role` before `assign_student_to_cohort`.** `set_user_role` syncs Default-cohort membership through an `m2m_changed` receiver that reads `is_staff` during `groups.set`; assigning the demo cohort first would be undone.
6. **Mail must be discarded, not captured.** `config/settings/test.py:7` already pins locmem, which *collects* mail into `mailoutbox` — so a locmem override proves nothing. Use the `dummy` backend, which discards.

- [ ] **Step 1: Write the failing test**

Create `tests/test_seed_demo_activity.py`:

```python
"""seed_demo_activity: demo cohort + analytics-visible activity, idempotently.

Every query here is scoped to `demo.student*`. The seeded_course fixture runs
seed_demo_course, which creates its OWN students and -- deliberately -- one
unreviewed REVIEW response (seed_demo_course.py:448). An unscoped assertion
would fail on a perfectly correct seed_demo_activity.
"""

import pytest
from django.core.management import call_command

OWNED = "demo.student"


@pytest.fixture
def seeded_course(db):
    """A small course with a lesson unit and a quiz unit carrying questions.
    seed_demo_course builds exactly this shape and is idempotent."""
    call_command("seed_demo_course")
    from courses.models import Course

    return Course.objects.get(slug="demo-course")


def _run(course, **kw):
    opts = {
        "course": course.slug,
        "students": 6,
        "groups": 2,
        "seed": 12345,
        "password": "seed-only-not-a-real-credential",  # noqa: S106
    }
    opts.update(kw)
    call_command("seed_demo_activity", **opts)


def _owned_responses():
    from courses.models import QuestionResponse

    return QuestionResponse.objects.filter(
        submission__student__username__startswith=OWNED
    )


def _owned_submissions():
    from courses.models import QuizSubmission

    return QuizSubmission.objects.filter(student__username__startswith=OWNED)


@pytest.mark.django_db
def test_creates_the_requested_students_with_unroutable_emails(seeded_course):
    from accounts.models import User

    _run(seeded_course)
    students = User.objects.filter(username__startswith=OWNED)
    assert students.count() == 6
    # .invalid is reserved and can never resolve: no seeded mail can escape.
    assert all(u.email.endswith("@example.invalid") for u in students)


@pytest.mark.django_db
def test_students_get_a_display_name(seeded_course):
    """User.__str__ returns display_name or username (accounts/models.py:41), so
    without this the matrix renders demo.student01 and the name pairs are wasted."""
    from accounts.models import User

    _run(seeded_course)
    for user in User.objects.filter(username__startswith=OWNED):
        assert user.display_name
        assert user.display_name != user.username


@pytest.mark.django_db
def test_students_hold_the_student_role(seeded_course):
    from accounts.models import User
    from institution.roles import STUDENT

    _run(seeded_course)
    for user in User.objects.filter(username__startswith=OWNED):
        assert user.groups.filter(name=STUDENT).exists()


@pytest.mark.django_db
def test_enrollment_is_derived_from_group_membership(seeded_course):
    """Not written directly: the command must drive the real grouping services,
    so every Enrollment carries source='group' exactly as production creates it."""
    from courses.models import Enrollment

    _run(seeded_course)
    rows = Enrollment.objects.filter(
        course=seeded_course, student__username__startswith=OWNED
    )
    assert rows.count() == 6
    assert set(rows.values_list("source", flat=True)) == {"group"}


@pytest.mark.django_db
def test_students_are_spread_across_the_requested_groups(seeded_course):
    from grouping.models import Group

    _run(seeded_course, groups=2)
    # "Demo cohort group", not "Demo group": seed_demo_course.py:383 already
    # creates a group literally named "Demo Group" on this course, and the two
    # would differ only by case -- which PostgreSQL LIKE happens to distinguish,
    # making this assertion silently order-of-the-day fragile.
    groups = Group.objects.filter(
        course=seeded_course, name__startswith="Demo cohort group"
    )
    assert groups.count() == 2
    assert all(g.memberships.count() == 3 for g in groups)


@pytest.mark.django_db
def test_is_idempotent(seeded_course):
    from accounts.models import User
    from courses.models import Enrollment

    _run(seeded_course)
    first = (
        User.objects.filter(username__startswith=OWNED).count(),
        Enrollment.objects.filter(course=seeded_course).count(),
        _owned_submissions().count(),
        _owned_responses().count(),
    )
    _run(seeded_course)
    second = (
        User.objects.filter(username__startswith=OWNED).count(),
        Enrollment.objects.filter(course=seeded_course).count(),
        _owned_submissions().count(),
        _owned_responses().count(),
    )
    assert first == second


@pytest.mark.django_db
def test_submitted_quizzes_have_a_completed_unit_progress(seeded_course):
    """finalize_submission does not touch UnitProgress; writing it is the
    caller's half of the invariant (seed_demo_course.py:333). Without it the
    unit stays in build_outline's `open` set."""
    from courses.models import QuizSubmission
    from courses.models import UnitProgress

    _run(seeded_course)
    submitted = _owned_submissions().filter(status=QuizSubmission.Status.SUBMITTED)
    assert submitted.exists()  # the assertion below is vacuous otherwise
    for sub in submitted:
        assert UnitProgress.objects.filter(
            student=sub.student, unit=sub.unit, completed=True
        ).exists()


@pytest.mark.django_db
def test_review_responses_are_marked_reviewed(seeded_course):
    """rollups.submission_is_counted excludes a submission with any unreviewed
    REVIEW question, so its score would silently vanish from the matrix.

    Scoped to this command's own rows: seed_demo_course deliberately leaves one
    REVIEW response unreviewed so it lands in the review queue."""
    from courses.models import QuestionElement

    _run(seeded_course)
    review_rows = [
        r
        for r in _owned_responses().select_related("element")
        if getattr(r.element.content_object, "marking_mode", None)
        == QuestionElement.MarkingMode.REVIEW
    ]
    assert review_rows  # the assertion below is vacuous otherwise
    assert [r for r in review_rows if r.reviewed_at is None] == []


@pytest.mark.django_db
def test_a_review_unit_yields_a_counted_submission(seeded_course):
    """The end-to-end version of the constraint above.

    rollups._quiz_review_maps derives total_review from the unit's REVIEW
    ELEMENTS (courses/rollups.py:344), not from the responses written -- so
    both an unreviewed response AND a skipped one leave reviewed < total and
    drop the whole submission from the matrix. This asserts the outcome the
    matrix actually reads, rather than the reviewed_at column alone."""
    from courses.rollups import _quiz_review_maps
    from courses.rollups import submission_is_counted

    _run(seeded_course)
    subs = list(_owned_submissions())
    assert subs
    _has_auto, total_review, reviewed_counts = _quiz_review_maps(
        [s.unit_id for s in subs], subs
    )
    review_subs = [s for s in subs if total_review.get(s.unit_id, 0) > 0]
    assert review_subs, "no seeded submission covers a REVIEW question"
    for sub in review_subs:
        assert submission_is_counted(sub, total_review, reviewed_counts)


@pytest.mark.django_db
def test_scores_vary_across_students(seeded_course):
    """A flat block of identical scores makes the colour bands useless.

    Asserts across STUDENTS, not just across rows: an earlier draft passed
    because one lone student happened to draw two different fractions, while
    every other student never reached a quiz at all."""
    _run(seeded_course)
    rows = set(
        _owned_responses().values_list("submission__student__username", "fraction")
    )
    assert len({username for username, _ in rows}) > 1
    assert len({fraction for _, fraction in rows}) > 1


@pytest.mark.django_db
def test_every_student_attempts_at_least_one_quiz(seeded_course):
    """Quiz participation is drawn independently of the lesson prefix. Tying the
    two meant that on a course whose quiz sits at the end -- the normal shape --
    almost nobody reached one and the quiz matrix stayed empty."""
    from accounts.models import User

    _run(seeded_course)
    attempted = set(_owned_submissions().values_list("student__username", flat=True))
    everyone = set(
        User.objects.filter(username__startswith=OWNED).values_list(
            "username", flat=True
        )
    )
    assert attempted == everyone


@pytest.mark.django_db
def test_a_wrong_answer_is_not_stored_as_the_correct_one(seeded_course):
    """The score is derived from the answer (seed_demo_course.py:318), so a
    response scored below 1.0 must not hold the fully-correct answer -- a
    browsing visitor would see the right option selected beside a failing mark."""
    from courses.models import ChoiceQuestionElement

    _run(seeded_course)
    for r in _owned_responses().select_related("element"):
        question = r.element.content_object
        if not isinstance(question, ChoiceQuestionElement):
            continue
        correct = sorted(
            question.choices.filter(is_correct=True).values_list("pk", flat=True)
        )
        if r.fraction < 1:
            assert r.latest_answer != correct


@pytest.mark.django_db
def test_completion_varies_across_students(seeded_course):
    """The same argument applied to the OTHER matrix. If every student completes
    every unit the progress view renders one uniform colour, which is exactly the
    flat block this seeder exists to avoid."""
    from django.db.models import Count

    from courses.models import UnitProgress

    _run(seeded_course, students=6)
    counts = (
        UnitProgress.objects.filter(
            student__username__startswith=OWNED, completed=True
        )
        .values("student_id")
        .annotate(n=Count("id"))
        .values_list("n", flat=True)
    )
    assert len(set(counts)) > 1


@pytest.mark.django_db
def test_responses_record_an_answer(seeded_course):
    """courses/views.py:1788 keys "answered" on latest_answer being non-null.
    Without it every seeded quiz renders as unanswered with a score beside it --
    on a box whose whole purpose is being browsed."""
    _run(seeded_course)
    assert _owned_responses().exists()
    assert not _owned_responses().filter(latest_answer__isnull=True).exists()


@pytest.mark.django_db(transaction=True)
def test_seeding_sends_no_email():
    """notify() defers delivery to transaction.on_commit
    (notifications/services.py:37), which never fires under a plain django_db
    test -- so a naive version of this test is unconditionally green.

    transaction=True, NOT django_capture_on_commit_callbacks: the command's dummy
    backend is installed by an override_settings block inside handle(), which
    exits when call_command returns. Capturing the callbacks would run them
    AFTER that override lifted, under the test settings' locmem backend
    (config/settings/test.py:7), and six messages would land in the outbox on a
    perfectly correct build. With transaction=True the command's own
    @transaction.atomic really commits, inside the override, which is the
    production ordering.

    deliver_notification_email bails only on a BLANK address
    (notifications/emails.py:88), so @example.invalid does not save us here.

    Builds its own course rather than using the seeded_course fixture, which is
    bound to the non-transactional `db` fixture.
    """
    from django.core import mail

    from courses.models import Course

    call_command("seed_demo_course")
    course = Course.objects.get(slug="demo-course")
    mail.outbox.clear()
    _run(course)
    assert mail.outbox == []


@pytest.mark.django_db
def test_same_seed_produces_the_same_scores(seeded_course):
    """Scoped deletes: wiping every submission would destroy seed_demo_course's
    rows too, and only seed_demo_activity re-runs."""
    _run(seeded_course, seed=999)
    first = sorted(
        _owned_responses().values_list("submission__student__username", "fraction")
    )
    _owned_responses().delete()
    _owned_submissions().delete()
    _run(seeded_course, seed=999)
    second = sorted(
        _owned_responses().values_list("submission__student__username", "fraction")
    )
    assert first == second
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
docker compose -f docker-compose.test.yml up -d
uv run python -m pytest tests/test_seed_demo_activity.py -v
```

Expected: all FAIL with `Unknown command: 'seed_demo_activity'`.

- [ ] **Step 3a: Audit which question types the target course actually uses**

`_latest_answer` (below) covers choice and short-text, and returns `None` for anything
else — which the command counts and reports rather than writing an unanswerable response.
Before implementing, find out what you are actually up against:

```bash
uv run python manage.py shell -c "
from collections import Counter
from django.contrib.contenttypes.models import ContentType
from courses.models import Element
from courses.rollups import _QUESTION_MODELS
ids = {ContentType.objects.get_for_model(m).id: m.__name__ for m in _QUESTION_MODELS}
rows = Element.objects.filter(content_type_id__in=ids).values_list('content_type_id', flat=True)
for name, n in Counter(ids[i] for i in rows).most_common():
    print(f'{n:6d}  {name}')
"
```

If a type outside choice/short-text dominates the subtree you intend to seed, widen
`_latest_answer` to cover it — **do not** invent a placeholder answer. The results page
renders whatever is stored, so a wrong-shaped value is worse than a skipped question.

- [ ] **Step 3: Write the command**

Create `courses/management/commands/seed_demo_activity.py`:

```python
"""Seed a demo student cohort and enough activity to populate the analytics
matrix, idempotently and deterministically.

Not part of any install: this exists so a demo instance shows realistic data.
A school's own instance never runs it.

Six constraints, each from existing code:

1. Enrollment is DERIVED, never written. grouping/services.py:127 defines
   reachability as group membership, and add_students_to_group already calls
   recompute_enrollment per student (grouping/services.py:216).
2. UnitProgress and QuizSubmission are separate writes. finalize_submission()
   deliberately does not touch progress -- see seed_demo_course.py:333.
3. REVIEW-mode responses must carry reviewed_at, or
   rollups.submission_is_counted (courses/rollups.py:402) drops the whole
   submission from the matrix.
4. No hardcoded password (ruff S106).
5. set_user_role BEFORE assign_student_to_cohort: set_user_role syncs
   Default-cohort membership via an m2m_changed receiver that reads is_staff
   during groups.set, so assigning the demo cohort first would be undone.
6. Mail is DISCARDED, not captured. notify_enrolled sends one message per
   student. The dummy backend throws them away; locmem would collect them,
   which is what the test suite already installs.
"""

import os
import random
import secrets
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from django.test.utils import override_settings
from django.utils import timezone

from accounts.emails import ensure_verified_primary_email
from accounts.models import User
from accounts.services import set_user_role
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.models import UnitProgress
from courses.models import _accepted_lines
from courses.quiz import finalize_submission
from courses.rollups import _QUESTION_MODELS
from courses.rollups import is_quiz_unit
from courses.rollups import units_in_order
from courses.rollups import units_under
from courses.scoring import earned_marks
from courses.scoring import to_stored_fraction
from grouping.models import Allocation
from grouping.models import Cohort
from grouping.models import Group
from grouping.services import add_students_to_group
from grouping.services import assign_student_to_cohort
from institution.roles import STUDENT
from institution.roles import seed_roles

# Ability bands: (share of the cohort, low fraction, high fraction). Chosen so
# the analytics colour bands show range rather than a flat block.
_BANDS = [(0.15, 0.80, 0.98), (0.65, 0.45, 0.78), (0.20, 0.15, 0.42)]

_FIRST = ["Anna", "Piotr", "Maria", "Jakub", "Zofia", "Marcin", "Julia", "Tomasz",
          "Alicja", "Michal", "Hanna", "Adam", "Lena", "Pawel", "Nina", "Filip",
          "Ewa", "Krzysztof", "Ola", "Bartosz"]
_LAST = ["Kowalska", "Nowak", "Wisniewska", "Wojcik", "Kowalczyk", "Kaminska",
         "Lewandowski", "Zielinska", "Szymanski", "Wozniak", "Dabrowska",
         "Kozlowski", "Jankowska", "Mazur", "Krawczyk", "Piotrowska",
         "Grabowski", "Nowicka", "Pawlowski", "Michalska"]


class Command(BaseCommand):
    help = "Seed demo students, groups and activity for the analytics matrix."

    def add_arguments(self, parser):
        parser.add_argument("--course", required=True, help="Course slug.")
        parser.add_argument(
            "--subtree",
            type=int,
            default=None,
            help="ContentNode pk to scope activity to. Omit for the whole course.",
        )
        parser.add_argument("--students", type=int, default=20)
        parser.add_argument("--groups", type=int, default=2)
        parser.add_argument("--seed", type=int, default=12345)
        parser.add_argument(
            "--password",
            default=None,
            help="Shared demo password. Falls back to DEMO_STUDENT_PASSWORD, "
            "else one is generated and printed once. NOTE: it applies only to "
            "students CREATED on this run; existing ones keep their password.",
        )

    def handle(self, *args, **options):
        # The dummy backend DISCARDS. recompute_enrollment -> notify_enrolled
        # sends one message per student, and seeding 20 against a live SMTP host
        # would fire 20 at @example.invalid. override_settings is a test utility,
        # used here deliberately: it is the only way to swap the backend for the
        # duration of a call without threading a connection through
        # grouping.services, which this command must not modify.
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.dummy.EmailBackend"
        ):
            self._run(options)

    @transaction.atomic
    def _run(self, options):
        course = Course.objects.filter(slug=options["course"]).first()
        if course is None:
            raise CommandError(f"No course with slug {options['course']!r}.")

        n_students = options["students"]
        n_groups = options["groups"]
        if n_groups < 1 or n_students < n_groups:
            raise CommandError("--students must be >= --groups, and --groups >= 1.")

        password = options["password"] or os.environ.get("DEMO_STUDENT_PASSWORD")
        generated = password is None
        if generated:
            password = secrets.token_urlsafe(12)

        rng = random.Random(options["seed"])  # noqa: S311 - demo data, not a secret
        seed_roles()  # the role auth-groups must exist before set_user_role

        self._skipped_units = set()
        units = self._units(course, options["subtree"])
        students = self._students(n_students, password)
        self._place(course, students, n_groups)
        self._activity(units, students, rng)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(students)} students across {n_groups} groups "
                f"on {course.slug} ({len(units)} units)."
            )
        )
        if self._skipped_units:
            # Never silent: a bounded run that reports full coverage reads as
            # "everything is answered" when it is not.
            self.stdout.write(
                self.style.WARNING(
                    f"Skipped {len(self._skipped_units)} quiz unit(s) holding a "
                    f"question type this seeder cannot answer. The WHOLE unit is "
                    f"skipped: a partial one would leave reviewed < total and "
                    f"vanish from the analytics matrix entirely. Widen "
                    f"_latest_answer to cover them."
                )
            )
        if generated:
            self.stdout.write(
                self.style.WARNING(
                    f"Generated demo password (applies to students created on "
                    f"THIS run only): {password}"
                )
            )

    def _units(self, course, subtree_pk):
        """Units to generate activity for, in document order.

        units_in_order / units_under are the same helpers the analytics matrix
        walks, so the seeded rows land in exactly the cells the matrix renders.

        units_under returns a SET, not a list -- its docstring is explicit about
        this. Iterating it directly would give a different order per process,
        and --seed would stop meaning anything, because rng draws are consumed
        in unit order. Intersecting with the ordered whole-course walk restores
        document order AND makes the run reproducible.
        """
        ordered = list(units_in_order(course, drafts="hide"))
        if subtree_pk is None:
            units = ordered
        else:
            root = ContentNode.objects.filter(pk=subtree_pk, course=course).first()
            if root is None:
                raise CommandError(
                    f"No node {subtree_pk} in course {course.slug!r}."
                )
            subtree = units_under(root, drafts="hide")
            units = [u for u in ordered if u in subtree]
        if not units:
            raise CommandError("That scope contains no visible units.")
        return units

    def _students(self, n, password):
        """Fixed usernames make re-runs idempotent. @example.invalid is a
        reserved TLD that can never resolve, so no seeded mail can escape.

        display_name is what the UI shows: User.__str__ returns
        `display_name or username` (accounts/models.py:41), so without it the
        analytics matrix and group rosters would render demo.student01.
        """
        out = []
        for i in range(n):
            username = f"demo.student{i + 1:02d}"
            first = _FIRST[i % len(_FIRST)]
            last = _LAST[i % len(_LAST)]
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@example.invalid",
                    "first_name": first,
                    "last_name": last,
                    "display_name": f"{first} {last}",
                },
            )
            if created:
                user.set_password(password)
                user.save(update_fields=["password"])
                ensure_verified_primary_email(user, user.email)
                set_user_role(user, STUDENT)
            out.append(user)
        return out

    def _place(self, course, students, n_groups):
        """Cohort -> Allocation -> Groups -> membership. Enrollment is never
        written directly: add_students_to_group calls recompute_enrollment per
        student (grouping/services.py:216), which derives it from reachability.
        """
        cohort, _ = Cohort.objects.get_or_create(name="Demo cohort")
        allocation, _ = Allocation.objects.get_or_create(
            course=course, name="Demo allocation"
        )
        allocation.cohorts.add(cohort)

        groups = []
        for i in range(n_groups):
            group, _ = Group.objects.get_or_create(
                course=course,
                name=f"Demo cohort group {i + 1}",
                defaults={"allocation": allocation},
            )
            if group.allocation_id != allocation.pk:
                group.allocation = allocation
                group.save(update_fields=["allocation"])
            groups.append(group)

        for student in students:
            assign_student_to_cohort(student, cohort)
        for i, group in enumerate(groups):
            add_students_to_group(group, students[i::n_groups])

    def _ability(self, rng):
        roll = rng.random()
        cumulative = 0.0
        for share, low, high in _BANDS:
            cumulative += share
            if roll <= cumulative:
                return low, high
        return _BANDS[-1][1], _BANDS[-1][2]

    def _activity(self, units, students, rng):
        """Lessons follow a per-student prefix; quizzes are drawn separately.

        Tying quiz attempts to the lesson prefix does not work: quizzes sit at
        the END of a chapter, so on a realistic course almost no student ever
        reaches one and the quiz matrix -- the thing this seeder exists to
        populate -- stays empty. The two are therefore independent, with the
        first quiz guaranteed so every student contributes at least one row.
        """
        lessons = [u for u in units if not is_quiz_unit(u)]
        quizzes = [u for u in units if is_quiz_unit(u)]
        for student in students:
            low, high = self._ability(rng)
            # A deterministic PREFIX, not a per-unit coin flip: a student who has
            # worked through 60% of a course has done the FIRST 60%, and a random
            # scatter would look like nobody follows the ordering. Depth varies by
            # band, so the progress matrix shows range instead of one flat colour.
            depth = max(1, round(len(lessons) * (low + (high - low) * 0.5)))
            for unit in lessons[:depth]:
                self._complete(student, unit)
            for i, quiz in enumerate(quizzes):
                if i == 0 or rng.random() < high:  # noqa: S311
                    self._quiz(quiz, student, rng, low, high)

    def _complete(self, student, unit):
        """The caller's half of "a finished unit has a completed UnitProgress".
        Guarded on `completed` so a re-run never re-stamps completed_at, which
        UnitProgress.save() sets once on the False -> True transition."""
        progress, _ = UnitProgress.objects.get_or_create(student=student, unit=unit)
        if not progress.completed:
            progress.completed = True
            progress.save()

    def _questions(self, unit):
        """The same scan rollups.quiz_gradeable_max performs (courses/rollups.py:373),
        so the responses this writes and the maximum the matrix expects agree."""
        ct_ids = {ContentType.objects.get_for_model(m).id for m in _QUESTION_MODELS}
        return [
            el
            for el in Element.objects.filter(
                unit=unit, content_type_id__in=ct_ids, parent__isnull=True
            ).prefetch_related("content_object")
            if isinstance(el.content_object, QuestionElement)
        ]

    def _latest_answer(self, question, want_correct):
        """A plausible stored answer for `question`, or None if this seeder
        cannot produce one faithfully.

        courses/views.py:1788 sets "answered" from `latest_answer is not None`,
        so a response without one renders as unanswered with a score beside it --
        every blank marked wrong, on a box whose purpose is being browsed.

        `want_correct` exists because the SCORE IS DERIVED FROM THE ANSWER (see
        _quiz), exactly as seed_demo_course.py:318 does it. Storing a fully
        correct answer next to a random 0.45 would show a browsing visitor the
        right option selected beside a failing mark.

        Returning None (and skipping the whole UNIT) is deliberate: a
        wrong-SHAPED answer is worse than no answer, because the results page
        renders whatever is stored. Widen this method rather than inventing a
        placeholder.

        BEFORE IMPLEMENTING: run the audit in Step 3a to see which concrete
        question models the target course actually uses, and cover those.
        """
        if isinstance(question, ChoiceQuestionElement):
            # Same access path as seed_demo_course.py:370, and the same stored
            # shape: a SORTED LIST of Choice pks, not a set (JSONField).
            correct = sorted(
                question.choices.filter(is_correct=True).values_list("pk", flat=True)
            )
            if not correct:
                return None
            if want_correct:
                return correct
            # A wrong pick: any option that is not in the correct set, so the
            # stored answer actually matches the stored score.
            wrong = sorted(
                question.choices.exclude(is_correct=True).values_list("pk", flat=True)
            )
            return wrong[:1] or correct
        if isinstance(question, ShortTextQuestionElement):
            # `accepted` is a newline-delimited TextField, not a list
            # (courses/models.py:2432). build_answer returns a plain string, so
            # latest_answer must be a plain string too.
            lines = [ln.strip() for ln in question.accepted.splitlines() if ln.strip()]
            if not lines:
                return None
            return lines[0] if want_correct else "nie wiem"
        if isinstance(question, ExtendedResponseQuestionElement):
            # REVIEW-mode, and answerable: build_answer/mark take a plain string
            # (courses/models.py:2465). Covering it is not optional -- see the
            # REVIEW note in _quiz.
            return (
                "Rozwiązanie: " + " ".join(_accepted_lines(question.required_keywords))
                if want_correct
                else "Nie potrafię tego uzasadnić."
            )
        return None

    def _quiz(self, unit, student, rng, low, high):
        # select_for_update: finalize_submission's docstring requires the caller
        # to hold the row lock; _run is @transaction.atomic, which is the
        # enclosing transaction that lock needs.
        submission, _ = QuizSubmission.objects.select_for_update().get_or_create(
            student=student,
            unit=unit,
            defaults={"status": QuizSubmission.Status.IN_PROGRESS},
        )
        if submission.status != QuizSubmission.Status.SUBMITTED:
            gradeable = [
                el
                for el in self._questions(unit)
                if el.content_object.marking_mode
                != QuestionElement.MarkingMode.NOT_MARKED
            ]
            # Decide the answers for the WHOLE unit up front. If any question type
            # is unsupported, skip the entire unit rather than part of it:
            # _quiz_review_maps derives total_review from the unit's REVIEW
            # ELEMENTS, not from the responses written (courses/rollups.py:344),
            # so an omitted REVIEW response leaves reviewed < total and
            # submission_is_counted drops the whole submission from the matrix --
            # the exact outcome constraint 3 exists to prevent.
            plan = []
            for element in gradeable:
                question = element.content_object
                want_correct = rng.random() < high  # noqa: S311
                answer = self._latest_answer(question, want_correct)
                if answer is None:
                    self._skipped_units.add(unit.pk)
                    return
                plan.append((element, question, answer))

            for element, question, answer in plan:
                # The score is DERIVED from the answer, never drawn independently
                # (seed_demo_course.py:318). A random fraction beside a fully
                # correct answer is incoherent on a box built to be browsed.
                fraction = to_stored_fraction(question.mark(answer).fraction)
                response, _ = QuestionResponse.objects.get_or_create(
                    submission=submission,
                    element=element,
                    defaults={
                        "fraction": fraction,
                        "earned_marks": earned_marks(fraction, question.max_marks),
                        "latest_answer": answer,
                        "attempt_count": 1,
                        "last_attempt_at": timezone.now(),
                    },
                )
                # A REVIEW question left unreviewed makes the whole submission
                # "pending", and submission_is_counted drops its score from the
                # matrix (courses/rollups.py:402).
                if (
                    question.marking_mode == QuestionElement.MarkingMode.REVIEW
                    and response.reviewed_at is None
                ):
                    response.reviewed_at = timezone.now()
                    response.save(update_fields=["reviewed_at"])
            finalize_submission(unit, submission)
        # Unconditional: a run seeded before this write existed has no progress
        # row, and only an unconditional call converges it.
        self._complete(student, unit)
```

- [ ] **Step 4: Run the test and confirm it passes**

```bash
uv run python -m pytest tests/test_seed_demo_activity.py -v
```

Expected: 16 passed.

- [ ] **Step 5: Falsify — confirm the tests can fail**

**Twelve mutants**, one at a time, each edited out by hand afterwards:

1. Replace the `_place` group loop with `Enrollment.objects.create(student=student, course=course)` per student. Expected: `test_enrollment_is_derived_from_group_membership` FAILS on `source`.
2. Delete the trailing `self._complete(student, unit)` call in `_quiz`. Expected: `test_submitted_quizzes_have_a_completed_unit_progress` FAILS.
3. Delete the `reviewed_at` block. Expected: `test_review_responses_are_marked_reviewed` FAILS. (Its `assert review_rows` guard means a demo course with no REVIEW question fails loudly rather than passing vacuously.)
4. Change the backend in `handle` to `locmem`. Expected: `test_seeding_sends_no_email` FAILS with a non-empty outbox — this is what proves the guard is real, since the test settings already install locmem.
5. Drop `"display_name"` from the `_students` defaults. Expected: `test_students_get_a_display_name` FAILS.
6. In `_units`, replace the ordered intersection with `units = list(units_under(root, drafts="hide"))`. Expected: `test_same_seed_produces_the_same_scores` FAILS **intermittently** — set iteration order varies per process. If it passes, run it several times; an intermittent mutant that never trips still proves the ordering matters, so keep the intersection either way.
7. Replace `QuizSubmission.objects.select_for_update().get_or_create(...)` in `_quiz` with an unconditional `QuizSubmission.objects.create(...)`, and drop the `if submission.status != SUBMITTED:` guard. Expected: `test_is_idempotent` FAILS — the second run doubles the submission and response counts. Without this the idempotency test is unproven, and it is the one most likely to pass vacuously.
8. Delete the `break` in `_activity`'s unit loop so every student completes every unit. Expected: `test_completion_varies_across_students` FAILS — one uniform colour across the progress matrix.
9. Remove `"latest_answer": answer` from the `get_or_create` defaults. Expected: `test_responses_record_an_answer` FAILS — and this is the state in which every seeded quiz renders as "not answered".
10. In `_quiz`, replace the derived fraction with `fraction = to_stored_fraction(0.5)` while leaving `want_correct` alone. Expected: `test_a_wrong_answer_is_not_stored_as_the_correct_one` FAILS — the correct answer stored beside a half mark.
11. In `_activity`, gate quizzes on the lesson prefix again (`for quiz in quizzes[:depth]`). Expected: `test_every_student_attempts_at_least_one_quiz` FAILS — on a course whose quiz sits at the end, most students never reach one.
12. In `_quiz`, replace the whole-unit `return` on an unsupported question with `continue`. Expected: `test_a_review_unit_yields_a_counted_submission` FAILS — a partially answered REVIEW unit leaves reviewed < total and drops out of the matrix.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . --no-cache && uv run ruff format --check .
git add courses/management/commands/seed_demo_activity.py tests/test_seed_demo_activity.py
git commit -m "feat(courses): seed_demo_activity command

Deterministic, idempotent demo cohort with enough spread that the analytics
colour bands show range. Drives the real grouping services so Enrollment is
derived exactly as production derives it, stamps reviewed_at on REVIEW
questions so submission_is_counted keeps their scores, and discards mail so
seeding cannot fire one notification per student."
```

---

### Task 5: `gunicorn`, `Dockerfile`, entrypoint

**Files:**
- Modify: `pyproject.toml` (dependencies)
- Create: `Dockerfile`, `docker-entrypoint.sh`, `.dockerignore`

**Interfaces:**
- Consumes: `set_site_domain` management command (Task 2).
- Produces: an image whose entrypoint accepts `DJANGO_SITE_DOMAIN`, `INIT_ADMIN_USERNAME`, `INIT_ADMIN_EMAIL`, `INIT_ADMIN_PASSWORD`, serves on container port `8000`, exposes `/healthz/` for a healthcheck, and **execs any command passed as arguments** instead of starting gunicorn. Task 6's compose file depends on all of these.

This task's real verification is Task 6 Step 5, which runs the stack. The checks here are build-time only, and the plan says so rather than implying more.

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

# libpq for psycopg; curl for the compose healthcheck defined in Task 6.
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
# A throwaway SECRET_KEY and a dummy DATABASE_URL: collectstatic touches neither,
# but settings import requires them to be present.
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
"$VENV_PY" manage.py set_site_domain --only-if-placeholder

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

Do **not** verify this with `docker run --entrypoint sh` — replacing the entrypoint bypasses the very script under test, so such a check proves only that the image contains a shell. The full passthrough test runs against the live stack in Task 6 Step 5.

The *ordering* of the bootstrap is verified in Task 6 Step 5 against the runtime log, not by grepping this file — grepping the file just written proves only that `COPY` worked.

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

### Task 6: Compose stack, Caddyfile, env example, local smoke test

**Files:**
- Create: `docker-compose.prod.yml`, `Caddyfile`, `.env.production.example`

**Interfaces:**
- Consumes: the image, `/healthz/`, and the argument passthrough from Task 5; `LIBLI_TRANSFER_MAX_*` from Task 1; `DJANGO_SITE_DOMAIN` from Task 2.
- Produces: service names `app`, `db`, `caddy`; volumes `pgdata`, `media`, `transfer_staging`, `support_screenshots`, `caddy_data`, `caddy_config`. Task 7's runbook references these by name.

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
		max_size {$CADDY_MAX_BODY:1GiB}
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
      # the host root disk. Point it at the staging volume so the transient copy
      # lands on sized storage that the disk arithmetic accounts for.
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
      CADDY_MAX_BODY: ${CADDY_MAX_BODY:-1GiB}
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
DJANGO_CSRF_TRUSTED_ORIGINS=https://libli.example.org

# --- secrets ---
DJANGO_SECRET_KEY=            # generate: python -c "import secrets;print(secrets.token_urlsafe(64))"
POSTGRES_PASSWORD=            # generate the same way
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

# --- demo data (only if you run seed_demo_activity; harmless otherwise) ---
# Set explicitly so a re-run does not print a NEW password that does not apply
# to the already-created students.
# DEMO_STUDENT_PASSWORD=

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
# CADDY_MAX_BODY=5GiB
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
curl -sI http://localhost/static/admin/css/base.css                  # 200, whitenoise manifest

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

# The staging directories must NOT be reachable. A grep of the Caddyfile cannot
# prove this; a request can.
curl -so /dev/null -w '%{http_code}\n' http://localhost/transfer_staging/
curl -so /dev/null -w '%{http_code}\n' http://localhost/support_screenshots/
#   both MUST be 404 (or 403) -- never 200 and never a directory listing

# Argument passthrough (Task 5's interface)
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

FILE_UPLOAD_TEMP_DIR points at the staging volume: Django spills large
uploads to the system temp dir before the view stages them, which by
default is a multi-GB write to the container overlay on the root disk.

transfer_staging and support_screenshots are volumes but deliberately
have no Caddy route, proven by a request rather than a grep."
```

---

### Task 7: The runbook

**Files:**
- Create: `docs/deployment.md`
- Modify: `docs/roadmap.md` — the "Non-technical deployment/install" bullet (begins at line **174**); point it at the new doc.

**Interfaces:**
- Consumes: every artifact from Tasks 1-6.
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
   nano .env.production                                             # fill every blank
   chmod 600 .env.production
   docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
   docker compose -f docker-compose.prod.yml --env-file .env.production logs -f app
   ```

   The log must show, in order: `waiting for the database`, `migrate`, `setup_roles`, `set_site_domain`, `init_platform`, `gunicorn`.

4. **Verify** — run every check in Step 2 below before going further.

5. **Walk the first-run wizard** at `https://<host>/setup/`, signed in as the `INIT_ADMIN_USERNAME` account. Confirm the Identity step shows the **Public hostname** field pre-filled with the value the entrypoint set, and that the five steps (Welcome → Identity → Access → Team → SSO) complete. This is the non-developer surface — walk it as a school admin would, without a shell open.

   **On the Access step, leave the signup policy on `invite`.** This is a public box with a
   real DNS name; "open" means strangers can self-register on it. `init_platform` defaults
   to invite, so this is a matter of not changing it. Verify afterwards:

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production exec -T app \
     /app/.venv/bin/python -c \
     "import django; django.setup(); from institution.models import Institution; print(Institution.load().signup_policy)"
   # MUST print: invite
   ```

6. **Load matematyka.** Raise the three `LIBLI_TRANSFER_MAX_*` vars and `CADDY_MAX_BODY` in `.env.production`, `docker compose … up -d` to apply, confirm `df -h /` shows **≥17 GB** free, then export locally from the builder and import through the web UI.

   After success, delete the staged archive rather than waiting out the 6-hour `TRANSFER_STAGING_MAX_AGE_HOURS`:

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production exec app \
     sh -c 'rm -f /app/transfer_staging/*.zip'
   ```

   Then **lower the caps back** and `up -d` again, so the demo box does not sit with a 5 GB upload ceiling.

7. **Find the course slug and subtree pk** before seeding — the importer assigns the slug, and it is not guaranteed to be `matematyka`:

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production exec app /app/.venv/bin/python manage.py shell -c "
   from courses.models import Course, ContentNode
   for c in Course.objects.all():
       print(c.pk, repr(c.slug), c.title)
   "
   # then, with the slug from above:
   docker compose -f docker-compose.prod.yml --env-file .env.production exec app /app/.venv/bin/python manage.py shell -c "
   from courses.models import ContentNode
   for n in ContentNode.objects.filter(course__slug='<slug>', parent__isnull=True).order_by('order'):
       print(n.pk, n.kind, n.title)
   "
   ```

8. **Seed the demo data.** Pass `--password` explicitly on the command line.

   Setting `DEMO_STUDENT_PASSWORD` in `.env.production` is **not** enough on its own:
   `docker compose exec` runs inside the *already-running* container, whose environment was
   fixed from `env_file` at start. Editing the file afterwards has no effect until the
   service is recreated, so the command would fall through to generating a random password
   — the exact outcome setting it was meant to avoid. Either pass `--password`, or run
   `… up -d app` after the edit and before seeding.

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production exec app \
     /app/.venv/bin/python manage.py seed_demo_course
   docker compose -f docker-compose.prod.yml --env-file .env.production exec app \
     /app/.venv/bin/python manage.py seed_demo_activity \
       --course <slug> --subtree <pk> --students 20 --groups 2 --seed 12345 \
       --password '<chosen-demo-password>'
   ```

   Record that password: a later re-run generates a *different* one, and because
   `get_or_create` skips `set_password` for students that already exist, the newly printed
   value would not be the one that works.

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

10. **Known constraints.** One app container only. No backups. `TRANSFER_STAGING_DIR` and `SUPPORT_SCREENSHOT_DIR` must never be web-served. Signup policy stays `invite`. The app container runs as root (accepted; see Task 5). After changing the hostname through the settings UI, `restart app` so every gunicorn worker picks it up — SITE_CACHE is per-process. Peak disk during import is ~17 GB including the `FILE_UPLOAD_TEMP_DIR` copy.

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
curl -sI https://<host>/static/admin/css/base.css              # 200
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

## After the plan

Once the box is live, two memory files are stale and must be corrected rather than left:

- `no-deployment-no-prod-db` becomes **false**. Rewrite it; do not delete it.
- `first-deployment-checklist`'s deferred items (migration 0060 + `FORMAT_VERSION 13`, the internal-link cutover runbook with `--start-at`) become live work.

Run the full suite as a branch gate before opening the PR — not per task:

```bash
docker compose -f docker-compose.test.yml up -d
uv run python -m pytest -n auto
uv run ruff check . --no-cache && uv run ruff format --check .
```

Grep the summary line rather than trusting the exit code, which can report 0 alongside `1 failed`.
