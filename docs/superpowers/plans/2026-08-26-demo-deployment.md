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
- **`TRANSFER_STAGING_DIR` and `SUPPORT_SCREENSHOT_DIR` must never be web-served.** They must not appear in any Caddy route.
- **No hardcoded passwords** in new code. ruff `S105`/`S106`/`S107` are enabled outside `tests/`.
- **ruff must pass:** `uv run ruff check . --no-cache` and `uv run ruff format --check .` are separate gates.
- **Run tests narrowly.** Whole-repo sweeps are a branch gate, not a task step. Start the test DB first: `docker compose -f docker-compose.test.yml up -d`.
- **Every test must be shown RED against its named mutant** before the task is accepted. A test that cannot fail is not evidence.
- **Branch:** `feat/demo-deployment` (already created; the spec is committed there).

---

## File Structure

**New application code**
- `institution/site_domain.py` — validation + persistence for the `django.contrib.sites` Site domain. One responsibility; consumed by both a management command and a form.
- `institution/management/commands/set_site_domain.py` — entrypoint-callable wrapper.
- `courses/management/commands/seed_demo_activity.py` — demo student cohort + activity.

**Modified application code**
- `config/settings/base.py:174-181` — three caps become `env.int` reads.
- `institution/forms.py:118-145` — `BrandingForm` gains `public_hostname`.
- `templates/institution/manage/_branding_fields.html` — renders the new field.
- `pyproject.toml` — add `gunicorn`.

**New infrastructure (repo root unless noted)**
- `Dockerfile`, `docker-entrypoint.sh`, `docker-compose.prod.yml`, `Caddyfile`, `.dockerignore`, `.env.production.example`
- `docs/deployment.md` — the runbook.

**New tests**
- `tests/test_transfer_caps_env.py`, `tests/test_site_domain.py`, `tests/test_seed_demo_activity.py`
- `tests/test_setup_wizard.py` — extended, not replaced.

Note `templates/institution/manage/_branding_fields.html` is included by **both** `templates/institution/setup/identity.html:8` and `templates/institution/manage/_branding_tab.html:13`. Adding the field there deliberately surfaces it on the manage settings page too, so a Platform Admin can correct the hostname after first run, not only during it.

---

### Task 1: Transfer caps become env-overridable

**Files:**
- Modify: `config/settings/base.py:174-181`
- Test: `tests/test_transfer_caps_env.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: env var names `LIBLI_TRANSFER_MAX_COMPRESSED_BYTES`, `LIBLI_TRANSFER_MAX_UNCOMPRESSED_BYTES`, `LIBLI_TRANSFER_MAX_MEDIA_ENTRIES` (all integers, bytes / count). Task 6's `.env.production.example` documents them; Task 7's runbook sets them.

- [ ] **Step 1: Write the failing test**

Create `tests/test_transfer_caps_env.py`:

```python
"""The three transfer caps are deployment guardrails (config/settings/base.py:172-174).
A school's default install must keep the shipped values; only an operator's env
raises them. Both halves of that contract are asserted here."""

import importlib
import os
from unittest import mock


def test_transfer_caps_default_to_the_shipped_guardrails():
    from django.conf import settings

    assert settings.TRANSFER_MAX_COMPRESSED_BYTES == 1 * 1024**3
    assert settings.TRANSFER_MAX_UNCOMPRESSED_BYTES == 1536 * 1024**2
    assert settings.TRANSFER_MAX_MEDIA_ENTRIES == 1000


def test_transfer_caps_are_env_overridable():
    """Reload the settings module with the vars set. A hardcoded constant keeps
    the old value and fails; an env.int() read picks the new one up.

    Reloading config.settings.base does NOT disturb django.conf.settings, which
    is already configured — this exercises the module's read logic in isolation.
    """
    import config.settings.base as base

    overrides = {
        "LIBLI_TRANSFER_MAX_COMPRESSED_BYTES": "5368709120",   # 5 GiB
        "LIBLI_TRANSFER_MAX_UNCOMPRESSED_BYTES": "6442450944",  # 6 GiB
        "LIBLI_TRANSFER_MAX_MEDIA_ENTRIES": "2000",
    }
    try:
        with mock.patch.dict(os.environ, overrides):
            reloaded = importlib.reload(base)
            assert reloaded.TRANSFER_MAX_COMPRESSED_BYTES == 5368709120
            assert reloaded.TRANSFER_MAX_UNCOMPRESSED_BYTES == 6442450944
            assert reloaded.TRANSFER_MAX_MEDIA_ENTRIES == 2000
    finally:
        importlib.reload(base)  # restore module state for the rest of the session
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
uv run python -m pytest tests/test_transfer_caps_env.py -v
```

Expected: `test_transfer_caps_default_to_the_shipped_guardrails` PASSES (values are already correct), `test_transfer_caps_are_env_overridable` FAILS — `assert 1073741824 == 5368709120`.

- [ ] **Step 3: Make the caps env-overridable**

In `config/settings/base.py`, replace the three constant assignments (currently lines 175, 176, 181). Leave `TRANSFER_MAX_COURSE_JSON_BYTES`, `TRANSFER_MAX_MANIFEST_BYTES`, `TRANSFER_MAX_NODES`, `TRANSFER_MAX_ELEMENTS` untouched:

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

- [ ] **Step 4: Run the test and confirm it passes**

```bash
uv run python -m pytest tests/test_transfer_caps_env.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Falsify — confirm the test can fail**

Temporarily revert one line to `TRANSFER_MAX_MEDIA_ENTRIES = 1000`. Re-run. Expected: `test_transfer_caps_are_env_overridable` FAILS with `assert 1000 == 2000`. **Edit the mutant out by hand** — do not `git checkout` the file, which would destroy the whole task's work.

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

### Task 2: `Site` domain module and management command

**Files:**
- Create: `institution/site_domain.py`
- Create: `institution/management/commands/set_site_domain.py`
- Create: `institution/management/__init__.py`, `institution/management/commands/__init__.py` *(only if absent — `institution/management/commands/setup_roles.py` already exists, so they are present)*
- Test: `tests/test_site_domain.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `institution.site_domain.validate_site_domain(value) -> str` — raises `django.core.exceptions.ValidationError` on a bad host. Task 3's form imports this.
  - `institution.site_domain.set_site_domain(domain, name=None) -> Site` — validates, writes, clears the Site cache.
  - Management command `set_site_domain`, reading `--domain` or the `DJANGO_SITE_DOMAIN` env var. Task 5's entrypoint calls it.

- [ ] **Step 1: Write the failing test**

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
        "",
    ],
)
def test_invalid_hosts_are_rejected(value):
    from institution.site_domain import validate_site_domain

    with pytest.raises(ValidationError):
        validate_site_domain(value)


@pytest.mark.django_db
def test_set_site_domain_writes_and_clears_the_cache():
    from django.contrib.sites.models import Site

    from institution.site_domain import set_site_domain

    Site.objects.get_current()  # prime the SITE_ID cache with example.com
    set_site_domain("libli.example.org", name="libli")

    assert Site.objects.get_current().domain == "libli.example.org"
    assert Site.objects.get_current().name == "libli"


@pytest.mark.django_db
def test_command_sets_the_domain_from_the_argument():
    from django.contrib.sites.models import Site

    call_command("set_site_domain", "--domain", "demo.example.org")
    assert Site.objects.get_current().domain == "demo.example.org"


@pytest.mark.django_db
def test_command_reads_the_env_var(monkeypatch):
    from django.contrib.sites.models import Site

    monkeypatch.setenv("DJANGO_SITE_DOMAIN", "env.example.org")
    call_command("set_site_domain")
    assert Site.objects.get_current().domain == "env.example.org"


@pytest.mark.django_db
def test_command_is_a_no_op_when_unset(monkeypatch):
    """The entrypoint calls this unconditionally. With no domain configured it
    must warn and exit cleanly, never abort the boot of a running instance."""
    from django.contrib.sites.models import Site

    monkeypatch.delenv("DJANGO_SITE_DOMAIN", raising=False)
    call_command("set_site_domain")
    assert Site.objects.get_current().domain == "example.com"  # untouched


@pytest.mark.django_db
def test_command_rejects_a_url(monkeypatch):
    from django.core.management.base import CommandError

    monkeypatch.setenv("DJANGO_SITE_DOMAIN", "https://demo.example.org/")
    with pytest.raises(CommandError):
        call_command("set_site_domain")
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
uv run python -m pytest tests/test_site_domain.py -v
```

Expected: all FAIL with `ModuleNotFoundError: No module named 'institution.site_domain'`.

- [ ] **Step 3: Write `institution/site_domain.py`**

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
"""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# A bare host with an optional :port. No scheme, no path, no userinfo, no
# trailing slash -- Site.domain is a host, and Django concatenates it directly.
_HOST_RE = re.compile(
    r"^(?=.{1,253}(?::\d{1,5})?$)"
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

- [ ] **Step 4: Write `institution/management/commands/set_site_domain.py`**

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
        try:
            site = set_site_domain(domain, name=options["name"])
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(self.style.SUCCESS(f"Site domain set to {site.domain}"))
```

- [ ] **Step 5: Run the test and confirm it passes**

```bash
uv run python -m pytest tests/test_site_domain.py -v
```

Expected: 15 passed (4 + 6 parametrised cases, plus 5 behaviour tests).

- [ ] **Step 6: Falsify — confirm the tests can fail**

Two mutants, run one at a time and edit each out by hand afterwards:

1. Delete the `Site.objects.clear_cache()` line in `set_site_domain`. Re-run. Expected: `test_set_site_domain_writes_and_clears_the_cache` FAILS — `get_current()` returns the primed `example.com`. *This is the whole reason the line exists; if the test still passes, the test primes the cache incorrectly and must be fixed.*
2. Change the no-op branch to `raise CommandError(...)`. Re-run. Expected: `test_command_is_a_no_op_when_unset` FAILS.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check . --no-cache && uv run ruff format --check .
git add institution/site_domain.py institution/management/commands/set_site_domain.py tests/test_site_domain.py
git commit -m "feat(institution): set_site_domain command and validator

Site #1 ships as example.com, and build_accept_url builds invitation and
password-reset links from it deliberately (so they cannot be host-spoofed).
Without this step every such link on a fresh deployment is dead, and no
test catches it."
```

---

### Task 3: `public_hostname` on `BrandingForm` — the non-technical surface

**Files:**
- Modify: `institution/forms.py:118-145` (`BrandingForm`)
- Modify: `templates/institution/manage/_branding_fields.html` (the Identity section, after the `favicon` field)
- Test: `tests/test_setup_wizard.py` (append)

**Interfaces:**
- Consumes: `institution.site_domain.validate_site_domain`, `institution.site_domain.set_site_domain` (Task 2).
- Produces: form field named `public_hostname` on `BrandingForm`. No later task depends on it.

The wizard's Identity step is handled by `_modelform_step` (`institution/views_setup.py`), which calls `form.save()`. Overriding `BrandingForm.save()` is therefore sufficient — **do not modify `views_setup.py`**.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_setup_wizard.py`:

```python
@pytest.mark.django_db
def test_identity_step_sets_the_site_domain(client):
    """The non-technical fix for dead invitation links: a Platform Admin types
    the public hostname during first-run setup and the Site record is written."""
    from django.contrib.sites.models import Site

    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(
        reverse("institution:setup_step", kwargs={"step": "identity"}),
        {
            "action": "next",
            "name": "Acme Academy",
            "enabled_languages": ["en", "pl"],
            "default_language": "en",
            "default_theme": "auto",
            "primary": "#147e78",
            "accent": "#c77b2a",
            "public_hostname": "libli.example.org",
        },
    )
    assert resp.status_code == 302
    assert Site.objects.get_current().domain == "libli.example.org"


@pytest.mark.django_db
def test_identity_step_rejects_a_url_in_the_hostname(client):
    from django.contrib.sites.models import Site

    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(
        reverse("institution:setup_step", kwargs={"step": "identity"}),
        {
            "action": "next",
            "name": "Acme Academy",
            "enabled_languages": ["en", "pl"],
            "default_language": "en",
            "default_theme": "auto",
            "primary": "#147e78",
            "accent": "#c77b2a",
            "public_hostname": "https://libli.example.org/setup",
        },
    )
    assert resp.status_code == 200  # re-renders the step, does not advance
    assert Site.objects.get_current().domain == "example.com"  # untouched


@pytest.mark.django_db
def test_identity_step_blank_hostname_leaves_the_site_alone(client):
    """The field is optional: an admin who skips it must not blank the domain."""
    from django.contrib.sites.models import Site

    from institution.site_domain import set_site_domain
    from tests.factories import make_pa

    set_site_domain("already.example.org")
    make_pa(client)
    resp = client.post(
        reverse("institution:setup_step", kwargs={"step": "identity"}),
        {
            "action": "next",
            "name": "Acme Academy",
            "enabled_languages": ["en", "pl"],
            "default_language": "en",
            "default_theme": "auto",
            "primary": "#147e78",
            "accent": "#c77b2a",
            "public_hostname": "",
        },
    )
    assert resp.status_code == 302
    assert Site.objects.get_current().domain == "already.example.org"


@pytest.mark.django_db
def test_identity_step_seeds_the_hostname_field_from_the_site(client):
    from institution.site_domain import set_site_domain
    from tests.factories import make_pa

    set_site_domain("seeded.example.org")
    make_pa(client)
    resp = client.get(reverse("institution:setup_step", kwargs={"step": "identity"}))
    assert b'name="public_hostname"' in resp.content
    assert b"seeded.example.org" in resp.content
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
uv run python -m pytest tests/test_setup_wizard.py -k "site_domain or hostname" -v
```

Expected: FAIL — the Site stays `example.com`, and `name="public_hostname"` is absent from the rendered page.

- [ ] **Step 3: Add the field to `BrandingForm`**

In `institution/forms.py`, add the imports near the existing ones:

```python
from institution.site_domain import set_site_domain
from institution.site_domain import validate_site_domain
```

Inside `class BrandingForm(forms.ModelForm):`, after the `accent` declaration (currently line 128), add:

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

Then add these three methods to the class:

```python
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Seed from the live Site so the admin edits the current value rather
        # than a blank box. Import here: the sites app must be ready.
        from django.contrib.sites.models import Site

        self.fields["public_hostname"].initial = Site.objects.get_current().domain

    def clean_public_hostname(self):
        value = (self.cleaned_data.get("public_hostname") or "").strip()
        if not value:
            return ""  # optional: blank leaves the Site record untouched
        return validate_site_domain(value)

    def save(self, commit=True):
        instance = super().save(commit=commit)
        hostname = self.cleaned_data.get("public_hostname")
        if commit and hostname:
            set_site_domain(hostname)
        return instance
```

If `BrandingForm` already defines `__init__`, merge the two bodies rather than adding a second one.

- [ ] **Step 4: Render the field**

In `templates/institution/manage/_branding_fields.html`, inside the `── Identity ──` section, immediately **after** the `form.favicon` `settings__field` div and before that section's closing `</div>`:

```html
  <div class="settings__field">
    <label class="settings__label" for="{{ form.public_hostname.id_for_label }}">{{ form.public_hostname.label }}</label>
    {{ form.public_hostname }}
    {% if form.public_hostname.help_text %}<span class="settings__help">{{ form.public_hostname.help_text }}</span>{% endif %}
    {{ form.public_hostname.errors }}
  </div>
```

- [ ] **Step 5: Run the test and confirm it passes**

```bash
uv run python -m pytest tests/test_setup_wizard.py -v
```

Expected: all pass, including the pre-existing wizard tests (the new field is optional, so the existing POST bodies that omit it must still succeed — if any now fail, `required=False` was lost).

- [ ] **Step 6: Falsify — confirm the tests can fail**

Three mutants, one at a time, each edited out by hand:

1. Delete the `set_site_domain(hostname)` call in `save()`. Expected: `test_identity_step_sets_the_site_domain` FAILS.
2. Change `clean_public_hostname` to `return value` without validating. Expected: `test_identity_step_rejects_a_url_in_the_hostname` FAILS (302 instead of 200, and the Site is corrupted).
3. Drop the `if commit and hostname:` guard so a blank writes through. Expected: `test_identity_step_blank_hostname_leaves_the_site_alone` FAILS — the domain is blanked.

- [ ] **Step 7: Check the manage settings page still renders**

The template is shared with `templates/institution/manage/_branding_tab.html:13`. Confirm nothing there broke:

```bash
uv run python -m pytest tests/ -k "branding" -v
```

Expected: pass.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check . --no-cache && uv run ruff format --check .
git add institution/forms.py templates/institution/manage/_branding_fields.html tests/test_setup_wizard.py
git commit -m "feat(institution): public hostname field on the identity step

Closes the gap docs/local-development.md describes as intended but never
built: nothing in the wizard touched django.contrib.sites.Site, so Site #1
stayed example.com and every invitation link on a fresh install was dead.

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
  `seed_demo_activity --course <slug> --subtree <pk> --students 20 --groups 2 --seed 12345`.

**Read `courses/management/commands/seed_demo_course.py:320-370` before starting.** It is the reference implementation for the submission/progress half, and its docstrings document two traps this command must not re-fall into.

Four hard constraints, each from existing code:

1. **Enrollment is derived, never written.** `grouping/services.py:127` defines reachability as group membership; `recompute_enrollment` (`grouping/services.py:182`) creates the `Enrollment`. Writing `Enrollment` rows directly produces state no production path produces.
2. **`UnitProgress` and `QuizSubmission` are separate writes.** `finalize_submission()` deliberately does not touch progress — see the docstring at `seed_demo_course.py:333`.
3. **Review-mode responses must be stamped `reviewed_at`.** `rollups.submission_is_counted` (`courses/rollups.py:402`) excludes a submission with any unreviewed `REVIEW` question, so its score would silently vanish from the matrix.
4. **No hardcoded password** — ruff `S106`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_seed_demo_activity.py`:

```python
"""seed_demo_activity: demo cohort + analytics-visible activity, idempotently."""

import pytest
from django.core.management import call_command


@pytest.fixture
def seeded_course(db):
    """A small course with one lesson unit and one quiz unit carrying an AUTO
    question. seed_demo_course builds exactly this shape and is idempotent."""
    call_command("seed_demo_course")
    from courses.models import Course

    return Course.objects.get(slug="demo-course")


def _run(course, **kw):
    opts = {"course": course.slug, "students": 6, "groups": 2, "seed": 12345}
    opts.update(kw)
    call_command("seed_demo_activity", **opts)


@pytest.mark.django_db
def test_creates_the_requested_students_with_unroutable_emails(seeded_course):
    from accounts.models import User

    _run(seeded_course)
    students = User.objects.filter(username__startswith="demo.student")
    assert students.count() == 6
    # .invalid is reserved and can never resolve: no seeded mail can escape.
    assert all(u.email.endswith("@example.invalid") for u in students)


@pytest.mark.django_db
def test_enrollment_is_derived_from_group_membership(seeded_course):
    """Not written directly: the command must drive the real grouping services,
    so every Enrollment carries source='group' exactly as production creates it."""
    from courses.models import Enrollment

    _run(seeded_course)
    rows = Enrollment.objects.filter(course=seeded_course, student__username__startswith="demo.student")
    assert rows.count() == 6
    assert set(rows.values_list("source", flat=True)) == {"group"}


@pytest.mark.django_db
def test_students_are_spread_across_the_requested_groups(seeded_course):
    from grouping.models import Group

    _run(seeded_course, groups=2)
    groups = Group.objects.filter(course=seeded_course, name__startswith="Demo group")
    assert groups.count() == 2
    assert all(g.memberships.count() == 3 for g in groups)


@pytest.mark.django_db
def test_is_idempotent(seeded_course):
    from accounts.models import User
    from courses.models import Enrollment
    from courses.models import QuizSubmission

    _run(seeded_course)
    first = (
        User.objects.filter(username__startswith="demo.student").count(),
        Enrollment.objects.filter(course=seeded_course).count(),
        QuizSubmission.objects.count(),
    )
    _run(seeded_course)
    second = (
        User.objects.filter(username__startswith="demo.student").count(),
        Enrollment.objects.filter(course=seeded_course).count(),
        QuizSubmission.objects.count(),
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
    for sub in QuizSubmission.objects.filter(status=QuizSubmission.Status.SUBMITTED):
        assert UnitProgress.objects.filter(
            student=sub.student, unit=sub.unit, completed=True
        ).exists()


@pytest.mark.django_db
def test_review_responses_are_marked_reviewed(seeded_course):
    """rollups.submission_is_counted excludes a submission with any unreviewed
    REVIEW question, so its score would silently vanish from the matrix."""
    from courses.models import QuestionElement
    from courses.models import QuestionResponse

    _run(seeded_course)
    pending = [
        r
        for r in QuestionResponse.objects.select_related("element").all()
        if getattr(r.element.content_object, "marking_mode", None)
        == QuestionElement.MarkingMode.REVIEW
        and r.reviewed_at is None
    ]
    assert pending == []


@pytest.mark.django_db
def test_scores_vary_across_students(seeded_course):
    """A flat block of identical scores makes the colour bands useless. The
    seeded spread must actually spread."""
    from courses.models import QuestionResponse

    _run(seeded_course)
    fractions = set(QuestionResponse.objects.values_list("fraction", flat=True))
    assert len(fractions) > 1


@pytest.mark.django_db
def test_seeding_sends_no_email(seeded_course, mailoutbox):
    """recompute_enrollment calls notify_enrolled, which emails each student.
    Seeding 20 students against live SMTP would fire 20 sends."""
    _run(seeded_course)
    assert mailoutbox == []


@pytest.mark.django_db
def test_same_seed_produces_the_same_scores(seeded_course):
    from courses.models import QuestionResponse

    _run(seeded_course, seed=999)
    first = sorted(QuestionResponse.objects.values_list("submission__student__username", "fraction"))
    QuestionResponse.objects.all().delete()
    from courses.models import QuizSubmission

    QuizSubmission.objects.all().delete()
    _run(seeded_course, seed=999)
    second = sorted(QuestionResponse.objects.values_list("submission__student__username", "fraction"))
    assert first == second
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
docker compose -f docker-compose.test.yml up -d
uv run python -m pytest tests/test_seed_demo_activity.py -v
```

Expected: all FAIL with `Unknown command: 'seed_demo_activity'`.

- [ ] **Step 3: Write the command**

Create `courses/management/commands/seed_demo_activity.py`:

```python
"""Seed a demo student cohort and enough activity to populate the analytics
matrix, idempotently and deterministically.

Not part of any install: this exists so a demo instance shows realistic data.
A school's own instance never runs it.

Four constraints, each from existing code:

1. Enrollment is DERIVED, never written. grouping/services.py:127 defines
   reachability as group membership and recompute_enrollment creates the row
   with source="group". Writing Enrollment directly produces state no
   production path produces.
2. UnitProgress and QuizSubmission are separate writes. finalize_submission()
   deliberately does not touch progress -- see seed_demo_course.py:333.
3. REVIEW-mode responses must carry reviewed_at, or
   rollups.submission_is_counted (courses/rollups.py:402) drops the whole
   submission from the matrix.
4. Email is suppressed for the duration: recompute_enrollment calls
   notify_enrolled, which sends one message per student.
"""

import random
import secrets
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from django.test.utils import override_settings
from django.utils import timezone

from accounts.emails import ensure_verified_primary_email
from accounts.models import User
from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import UnitProgress
from courses.quiz import finalize_submission
from courses.rollups import is_quiz_unit
from courses.rollups import units_in_order
from courses.rollups import units_under
from courses.scoring import earned_marks
from grouping.models import Allocation
from grouping.models import Cohort
from grouping.models import Group
from grouping.services import add_students_to_group
from grouping.services import assign_student_to_cohort
from grouping.services import recompute_enrollment
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
            "else one is generated and printed once.",
        )

    def handle(self, *args, **options):
        # Console backend for the whole run: recompute_enrollment ->
        # notify_enrolled sends one email per student, and seeding 20 students
        # against a live SMTP host would fire 20 messages at @example.invalid.
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
        ):
            self._run(options)

    @transaction.atomic
    def _run(self, options):
        import os

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

        rng = random.Random(options["seed"])
        seed_roles()  # role auth-groups must exist before set_user_role

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
        if generated:
            self.stdout.write(
                self.style.WARNING(f"Generated demo password: {password}")
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
        reserved TLD that can never resolve, so no seeded mail can escape."""
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
                },
            )
            if created:
                user.set_password(password)
                user.save(update_fields=["password"])
                ensure_verified_primary_email(user)
            out.append(user)
        return out

    def _place(self, course, students, n_groups):
        """Cohort -> Allocation -> Groups -> membership -> recompute_enrollment.
        Enrollment is never written directly; it is derived from reachability."""
        cohort, _ = Cohort.objects.get_or_create(name="Demo cohort")
        allocation, _ = Allocation.objects.get_or_create(
            course=course, name="Demo allocation"
        )
        allocation.cohorts.add(cohort)

        groups = []
        for i in range(n_groups):
            group, _ = Group.objects.get_or_create(
                course=course,
                name=f"Demo group {i + 1}",
                defaults={"allocation": allocation},
            )
            if group.allocation_id != allocation.pk:
                group.allocation = allocation
                group.save(update_fields=["allocation"])
            groups.append(group)

        for i, student in enumerate(students):
            assign_student_to_cohort(student, cohort)
        for i, group in enumerate(groups):
            members = students[i::n_groups]
            add_students_to_group(group, members)
        for student in students:
            recompute_enrollment(student, course)

    def _ability(self, rng):
        roll = rng.random()
        cumulative = 0.0
        for share, low, high in _BANDS:
            cumulative += share
            if roll <= cumulative:
                return low, high
        return _BANDS[-1][1], _BANDS[-1][2]

    def _activity(self, units, students, rng):
        for student in students:
            low, high = self._ability(rng)
            for unit in units:
                if is_quiz_unit(unit):
                    self._quiz(unit, student, rng, low, high)
                else:
                    self._complete(student, unit)

    def _complete(self, student, unit):
        """The caller's half of "a finished unit has a completed UnitProgress".
        Guarded on `completed` so a re-run never re-stamps completed_at, which
        UnitProgress.save() sets once on the False -> True transition."""
        progress, _ = UnitProgress.objects.get_or_create(student=student, unit=unit)
        if not progress.completed:
            progress.completed = True
            progress.save()

    def _questions(self, unit):
        """The same scan rollups.quiz_gradeable_max performs, so the responses
        this writes and the maximum the matrix expects agree."""
        from courses.rollups import _QUESTION_MODELS

        ct_ids = {ContentType.objects.get_for_model(m).id for m in _QUESTION_MODELS}
        return [
            el
            for el in Element.objects.filter(
                unit=unit, content_type_id__in=ct_ids, parent__isnull=True
            ).prefetch_related("content_object")
            if isinstance(el.content_object, QuestionElement)
        ]

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
            for element in self._questions(unit):
                question = element.content_object
                if question.marking_mode == QuestionElement.MarkingMode.NOT_MARKED:
                    continue
                fraction = Decimal(str(round(rng.uniform(low, high), 2)))
                response, _ = QuestionResponse.objects.get_or_create(
                    submission=submission,
                    element=element,
                    defaults={
                        "fraction": fraction,
                        "earned_marks": earned_marks(fraction, question.max_marks),
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

Expected: 9 passed. `_QUESTION_MODELS` is defined at `courses/rollups.py:27`; import it rather than duplicating the list, so the seeder scans exactly the elements `quiz_gradeable_max` scores.

- [ ] **Step 5: Falsify — confirm the tests can fail**

Four mutants, one at a time, each edited out by hand afterwards:

1. Replace the `_place` body's last loop with `Enrollment.objects.create(student=student, course=course)`. Expected: `test_enrollment_is_derived_from_group_membership` FAILS on `source`.
2. Delete the `self._complete(student, unit)` call at the end of `_quiz`. Expected: `test_submitted_quizzes_have_a_completed_unit_progress` FAILS.
3. Delete the `reviewed_at` block. Expected: `test_review_responses_are_marked_reviewed` FAILS. *If the demo course has no REVIEW-mode question this test is vacuous — add one to the fixture rather than accepting a test that cannot fail.*
4. Remove the `override_settings` wrapper. Expected: `test_seeding_sends_no_email` FAILS with a non-empty outbox.
5. In `_units`, replace the ordered intersection with `units = list(units_under(root, drafts="hide"))`. Expected: `test_same_seed_produces_the_same_scores` FAILS **intermittently** — set iteration order varies per process, so rng draws land on different units. If it passes, run it a few times under `-p no:randomly`; an intermittent mutant that never trips still proves the ordering matters, so keep the intersection either way.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . --no-cache && uv run ruff format --check .
git add courses/management/commands/seed_demo_activity.py tests/test_seed_demo_activity.py
git commit -m "feat(courses): seed_demo_activity command

Deterministic, idempotent demo cohort with enough spread that the analytics
colour bands show range. Drives the real grouping services so Enrollment is
derived exactly as production derives it, stamps reviewed_at on REVIEW
questions so submission_is_counted keeps their scores, and suppresses email
so seeding cannot fire one notification per student."
```

---

### Task 5: `gunicorn`, `Dockerfile`, entrypoint

**Files:**
- Modify: `pyproject.toml` (dependencies)
- Create: `Dockerfile`, `docker-entrypoint.sh`, `.dockerignore`

**Interfaces:**
- Consumes: `set_site_domain` management command (Task 2).
- Produces: an image whose entrypoint accepts `DJANGO_SITE_DOMAIN`, `INIT_ADMIN_USERNAME`, `INIT_ADMIN_EMAIL`, `INIT_ADMIN_PASSWORD`, and serves on container port `8000`. Task 6's compose file depends on these names.

This task has no pytest coverage — it is verified by building and running the image. That is stated rather than papered over with a test that asserts a file exists.

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
.env
docker-compose.test.yml
support_screenshots
transfer_staging
tests
docs
```

- [ ] **Step 3: Write the `Dockerfile`**

```dockerfile
# libli production image. Single-stage: uv makes the dependency install fast
# enough that a builder stage buys little, and the runtime needs the same
# interpreter anyway.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    DJANGO_SETTINGS_MODULE=config.settings.production

# libpq for psycopg, curl for the compose healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

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
# A throwaway SECRET_KEY and a blank DATABASE_URL: collectstatic touches neither,
# but settings import requires them to be present.
RUN DJANGO_SECRET_KEY=build-only-not-a-runtime-secret \
    DATABASE_URL=postgres://u:p@localhost:5432/db \
    uv run python manage.py collectstatic --noinput

# locale/*/LC_MESSAGES/*.mo are committed, so no compilemessages step.

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
```

- [ ] **Step 4: Write `docker-entrypoint.sh`**

Use LF line endings. On Windows confirm with `file docker-entrypoint.sh` — a CRLF shebang fails with `no such file or directory`.

```bash
#!/bin/sh
# libli container entrypoint. Ordered bootstrap, then the app server.
#
# Safe ONLY because there is exactly one app container: `migrate` here would
# race between replicas. Do not scale this service.
set -eu

echo "==> waiting for the database"
i=0
until uv run python -c "
import sys
from django.db import connection
import django
django.setup()
try:
    connection.ensure_connection()
except Exception as exc:
    print(exc, file=sys.stderr)
    sys.exit(1)
" 2>/dev/null; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    echo "!! database unreachable after 60 attempts; refusing to start" >&2
    exit 1
  fi
  sleep 2
done

echo "==> migrate"
uv run python manage.py migrate --noinput

# Unconditional, even though init_platform also calls it. Permissions live as
# constants in institution/roles.py but are only ASSIGNED by seed_roles(); on an
# already-bootstrapped instance init_platform is skipped below, so this would be
# the only caller. No test can catch its omission -- tests/factories.py calls
# seed_roles() itself, so the suite passes either way.
echo "==> setup_roles"
uv run python manage.py setup_roles

# Site #1 ships as example.com and build_accept_url builds invitation and
# password-reset links from it. A no-op when DJANGO_SITE_DOMAIN is unset.
echo "==> set_site_domain"
uv run python manage.py set_site_domain

# Only when fully specified: init_platform fails fast on missing credentials
# when non-interactive, which must not stop a healthy instance from booting.
if [ -n "${INIT_ADMIN_USERNAME:-}" ] \
   && [ -n "${INIT_ADMIN_EMAIL:-}" ] \
   && [ -n "${INIT_ADMIN_PASSWORD:-}" ]; then
  echo "==> init_platform"
  uv run python manage.py init_platform
else
  echo "==> init_platform skipped (INIT_ADMIN_* not fully set)"
fi

echo "==> gunicorn"
# --timeout 1800: a multi-GB course import occupies one worker for ~25 minutes
# of sustained upload; the 30s default would kill it mid-stage.
# --threads: keeps the site responsive while one worker is consumed by that import.
exec uv run gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-1800}" \
  --access-logfile - \
  --error-logfile -
```

- [ ] **Step 5: Build the image**

```bash
docker build -t libli:local .
```

Expected: builds clean. The `collectstatic` layer must report the number of files copied — if it errors on a missing static reference, that is a real bug to fix now, not at deploy time.

- [ ] **Step 6: Verify the entrypoint ordering is what shipped**

```bash
docker run --rm --entrypoint sh libli:local -c 'grep -n "^echo \"==>" /usr/local/bin/docker-entrypoint.sh'
```

Expected, in this order: waiting for the database, migrate, setup_roles, set_site_domain, gunicorn (with the conditional init_platform between the last two).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock Dockerfile docker-entrypoint.sh .dockerignore
git commit -m "feat(deploy): production image and ordered entrypoint

gunicorn was not a dependency at all. collectstatic runs at build time
because whitenoise's manifest storage needs the manifest in the image.
setup_roles runs unconditionally: init_platform is conditional, and no
test can catch a missing role seed."
```

---

### Task 6: Compose stack, Caddyfile, env example

**Files:**
- Create: `docker-compose.prod.yml`, `Caddyfile`, `.env.production.example`

**Interfaces:**
- Consumes: the image and env var names from Task 5; `LIBLI_TRANSFER_MAX_*` from Task 1; `DJANGO_SITE_DOMAIN` from Task 2.
- Produces: service names `app`, `db`, `caddy`; volumes `pgdata`, `media`, `transfer_staging`, `support_screenshots`, `caddy_data`, `caddy_config`. Task 7's runbook references these by name.

Named `docker-compose.prod.yml`, not `docker-compose.yml`, so it can never be picked up by a bare `docker compose` in the repo root alongside the existing `docker-compose.test.yml`.

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
	# uploads, and screenshots may carry another student's grades.

	handle {
		reverse_proxy app:8000 {
			header_up X-Forwarded-Proto {scheme}
		}
	}

	request_body {
		max_size {$CADDY_MAX_BODY:1GB}
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
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}
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
    env_file: .env
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.production
      DATABASE_URL: postgres://${POSTGRES_USER:-libli}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-libli}
      DJANGO_BEHIND_PROXY: "true"
    volumes:
      - media:/app/media
      - transfer_staging:/app/transfer_staging
      - support_screenshots:/app/support_screenshots
    expose:
      - "8000"

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    depends_on:
      - app
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    environment:
      SITE_ADDRESS: ${SITE_ADDRESS:?set SITE_ADDRESS in .env}
      CADDY_MAX_BODY: ${CADDY_MAX_BODY:-1GB}
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
  support_screenshots:
  caddy_data:
  caddy_config:
```

- [ ] **Step 3: Write `.env.production.example`**

```bash
# Copy to .env next to docker-compose.prod.yml and fill in. Never commit the
# filled copy. Mirrors the "production only" block of .env.example.

# --- identity ---
# The address Caddy answers on and requests a certificate for. A bare hostname
# gets automatic HTTPS from Let's Encrypt.
SITE_ADDRESS=libli.example.org

# Host part only. Used to build invitation and password-reset links, which come
# from the django.contrib.sites Site record, not the request Host header.
DJANGO_SITE_DOMAIN=libli.example.org

DJANGO_ALLOWED_HOSTS=libli.example.org
DJANGO_CSRF_TRUSTED_ORIGINS=https://libli.example.org

# --- secrets ---
DJANGO_SECRET_KEY=            # generate: python -c "import secrets;print(secrets.token_urlsafe(64))"
POSTGRES_PASSWORD=            # generate the same way
POSTGRES_USER=libli
POSTGRES_DB=libli

# --- first Platform Admin (read by init_platform; omit to skip bootstrap) ---
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

# --- transfer caps: RAISE ONLY IF YOU HOST AN OVERSIZED COURSE ---
# The shipped defaults (1 GiB / 1.5 GiB / 1000 entries) are deliberate
# guardrails. The matematyka demo course needs all three raised: it is 1,194
# media assets and ~3.8 GB, and mp4 does not compress.
# CADDY_MAX_BODY must be raised to match, or Caddy rejects the upload before
# Django ever sees it.
# LIBLI_TRANSFER_MAX_COMPRESSED_BYTES=5368709120
# LIBLI_TRANSFER_MAX_UNCOMPRESSED_BYTES=6442450944
# LIBLI_TRANSFER_MAX_MEDIA_ENTRIES=2000
# CADDY_MAX_BODY=5GB
```

- [ ] **Step 4: Validate the compose file**

```bash
cp .env.production.example .env.compose-check
printf '\nPOSTGRES_PASSWORD=x\nDJANGO_SECRET_KEY=y\n' >> .env.compose-check
docker compose -f docker-compose.prod.yml --env-file .env.compose-check config >/dev/null && echo OK
rm .env.compose-check
```

Expected: `OK`. A missing required variable surfaces here rather than on the droplet.

- [ ] **Step 5: Confirm the staging volumes are not web-served**

```bash
grep -n "transfer_staging\|support_screenshots" Caddyfile
```

Expected: **only** the comment lines — no `root`, `file_server`, or `handle` referencing either. Raw unvalidated uploads and other students' grades must not be reachable over HTTP.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.prod.yml Caddyfile .env.production.example
git commit -m "feat(deploy): compose stack with Caddy serving media

Caddy over nginx for two reasons that matter at this size: it streams
request bodies (nginx buffers the whole body to disk, a fourth multi-GB
copy during import) and its file_server does HTTP Range, which Django
does not implement anywhere and which video seeking requires.

transfer_staging and support_screenshots are volumes but deliberately
have no Caddy route."
```

---

### Task 7: The runbook

**Files:**
- Create: `docs/deployment.md`
- Modify: `docs/roadmap.md:175` — the cross-cutting concern is now partly resolved; point at the new doc.

**Interfaces:**
- Consumes: every artifact from Tasks 1-6.
- Produces: nothing consumed by code.

- [ ] **Step 1: Write `docs/deployment.md`**

Cover, in order, with real commands rather than descriptions:

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
   cp .env.production.example .env
   python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # DJANGO_SECRET_KEY
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # POSTGRES_PASSWORD
   nano .env                                                        # fill every blank
   chmod 600 .env
   docker compose -f docker-compose.prod.yml up -d --build
   docker compose -f docker-compose.prod.yml logs -f app            # watch the ordered bootstrap
   ```

   The log must show, in order: `waiting for the database`, `migrate`, `setup_roles`, `set_site_domain`, `init_platform`, `gunicorn`.

4. **Verify** — run every check in Step 2 below before going further.

5. **Walk the first-run wizard** at `https://<host>/setup/`, signed in as the `INIT_ADMIN_USERNAME` account. Confirm the Identity step shows the **Public hostname** field pre-filled with the value the entrypoint set, and that the five steps (Welcome → Identity → Access → Team → SSO) complete. This is the non-developer surface — walk it as a school admin would, without a shell open.
6. **Load matematyka.** Raise the three `LIBLI_TRANSFER_MAX_*` vars and `CADDY_MAX_BODY` in `.env`, restart, check `df -h` shows ≥17 GB free, export locally from the builder, then import through the web UI. After success, delete the staged archive rather than waiting out the 6-hour `TRANSFER_STAGING_MAX_AGE_HOURS`:
   ```bash
   docker compose -f docker-compose.prod.yml exec app sh -c 'rm -f /app/transfer_staging/*.zip'
   ```
   Then **lower the caps back** and restart, so the demo box does not sit with a 5 GB upload ceiling.
7. **Seed the demo data.**
   ```bash
   docker compose -f docker-compose.prod.yml exec app \
     uv run python manage.py seed_demo_course
   docker compose -f docker-compose.prod.yml exec app \
     uv run python manage.py seed_demo_activity \
       --course matematyka --subtree <pk> --students 20 --groups 2 --seed 12345
   ```
8. **Schedule the notification purge** — `docs/local-development.md` notes there is no built-in scheduler and the table grows without one.
9. **Known constraints.** One app container only. No backups. `TRANSFER_STAGING_DIR` and `SUPPORT_SCREENSHOT_DIR` must never be web-served.

- [ ] **Step 2: Put the post-deploy checks in the runbook verbatim**

```bash
# Video seeking. A 200 here means every student's <video> is unseekable --
# the page looks fine and only someone trying to replay a passage finds out.
curl -sI https://<host>/media/<some>.mp4 -H 'Range: bytes=0-100' | head -5
# MUST show: HTTP/2 206  and  accept-ranges: bytes

# Whitenoise manifest intact
curl -sI https://<host>/static/admin/css/base.css | head -3   # 200

# TLS and the HTTP redirect
curl -sI http://<host>/ | head -3                              # 301/308 to https

# Disk headroom BEFORE importing
df -h /
```

- [ ] **Step 3: Update the roadmap**

In `docs/roadmap.md`, amend the "Non-technical deployment/install" bullet to note that the containerised install now exists and point at `docs/deployment.md`. Keep the edit **line-count neutral** if practical — line-inserting diffs rot `file:line` citations elsewhere in the docs.

- [ ] **Step 4: Commit**

```bash
git add docs/deployment.md docs/roadmap.md
git commit -m "docs: deployment runbook

Includes the Range check on /media/, which is the one post-deploy
verification that must not be skipped: a 200 there is a silent failure."
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
