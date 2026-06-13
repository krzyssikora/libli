# Phase 0a — Project Skeleton & Core Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the libli Django project (uv + Django 5.2 + DRF + PostgreSQL, settings split, pytest/ruff/CI) with the three "painful to reverse" core schema pieces in place: the custom **User** model, the **Institution** singleton, and seeded **RBAC role** Groups.

**Architecture:** A standard Django project rooted at the repo top level with a `config/` settings package (base/local/test/production) and per-domain apps (`accounts`, `institution`). The custom user model is created *before the first migration*. Authentication, SSO, i18n, theming, and views are deliberately **out of scope** here — they land in plans 0b–0d.

**Tech Stack:** Python 3.13, uv, Django 5.2, Django REST Framework, PostgreSQL (psycopg 3), django-environ, django-extensions, whitenoise, pytest + pytest-django + factory_boy, ruff.

This plan implements the [Phase 0 spec](../specs/2026-06-13-phase-0-foundations-design.md) §"Stack & project layout", §1 (User), §2 (Roles), §3 (Institution). Cross-cutting style follows the fijit-playbook conventions referenced in the spec.

---

## File Structure

```
libli/
├── pyproject.toml                 # deps + ruff + pytest config
├── .python-version                # 3.13
├── manage.py                      # parses .env for DJANGO_SETTINGS_MODULE
├── .env.example                   # documented env contract
├── .env                           # local (gitignored)
├── config/
│   ├── __init__.py
│   ├── urls.py                    # root urlconf (health check only for now)
│   ├── wsgi.py
│   ├── asgi.py
│   └── settings/
│       ├── __init__.py
│       ├── base.py                # shared settings, loads .env
│       ├── local.py               # dev
│       ├── test.py                # CI/test
│       └── production.py          # prod
├── accounts/
│   ├── __init__.py
│   ├── apps.py
│   ├── models.py                  # User (AbstractUser subclass)
│   ├── admin.py
│   └── migrations/
├── institution/
│   ├── __init__.py
│   ├── apps.py
│   ├── models.py                  # Institution (singleton) + BrandColor
│   ├── roles.py                   # role name constants + seed_roles()
│   ├── admin.py
│   ├── management/commands/setup_roles.py
│   └── migrations/                # incl. data migration seeding roles
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── factories.py
│   ├── test_smoke.py
│   ├── test_user_model.py
│   ├── test_institution.py
│   └── test_roles.py
└── .github/workflows/ci.yml
```

---

### Task 1: Initialize the uv project and dependencies

**Files:**
- Create: `pyproject.toml`, `.python-version`

- [ ] **Step 1: Pin Python and init uv**

Run:
```bash
echo "3.13" > .python-version
uv init --bare --python 3.13
```
Expected: creates/updates `pyproject.toml`; no `src/` layout.

- [ ] **Step 2: Add runtime dependencies**

Run:
```bash
uv add "django>=5.2,<5.3" djangorestframework "psycopg[binary]>=3.2,<4.0" django-environ django-extensions whitenoise
```
Expected: dependencies resolve; `uv.lock` created.

- [ ] **Step 3: Add dev dependencies**

Run:
```bash
uv add --dev pytest pytest-django factory-boy ruff
```
Expected: dev group populated.

- [ ] **Step 4: Configure ruff and pytest in `pyproject.toml`**

Append:
```toml
[tool.ruff]
target-version = "py313"
extend-exclude = ["*/migrations/*.py"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "S"]
ignore = ["S101"]

[tool.ruff.lint.isort]
force-single-line = true

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings.test"
python_files = ["test_*.py"]
addopts = "-q"
```

- [ ] **Step 5: Verify the toolchain installs cleanly**

Run: `uv sync`
Expected: `Resolved ... packages` then `Installed ...`, exit 0.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .python-version
git commit -m "chore: initialize uv project with Django/DRF/pytest/ruff"
```

---

### Task 2: Django project skeleton with split settings

**Files:**
- Create: `manage.py`, `config/__init__.py`, `config/urls.py`, `config/wsgi.py`, `config/asgi.py`, `config/settings/__init__.py`, `config/settings/base.py`, `config/settings/local.py`, `config/settings/test.py`, `config/settings/production.py`, `.env.example`, `.env`

- [ ] **Step 1: Create `manage.py` that reads `.env` for the settings module**

```python
#!/usr/bin/env python
import os
import sys
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent
env = environ.Env()
env_file = BASE_DIR / ".env"
if env_file.exists():
    env.read_env(str(env_file))


def main():
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE",
        env("DJANGO_SETTINGS_MODULE", default="config.settings.local"),
    )
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create `config/settings/base.py`**

```python
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env = environ.Env()
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    env.read_env(str(_env_file))
# In CI and production there is no .env file — config comes from real
# environment variables, and environ reads those directly.

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_extensions",
    "rest_framework",
    "accounts",
    "institution",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://libli:libli@localhost:5432/libli"),
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
```

- [ ] **Step 3: Create the per-environment settings files**

`config/settings/local.py`:
```python
from config.settings.base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
```

`config/settings/test.py`:
```python
from config.settings.base import *  # noqa: F403

DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # faster tests
```

`config/settings/production.py`:
```python
from config.settings.base import *  # noqa: F403

DEBUG = False
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

`config/settings/__init__.py`: empty file.

- [ ] **Step 4: Create `config/urls.py`, `config/wsgi.py`, `config/asgi.py`**

`config/urls.py`:
```python
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path


def healthz(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz, name="healthz"),
]
```

`config/wsgi.py`:
```python
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
application = get_wsgi_application()
```

`config/asgi.py`:
```python
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
application = get_asgi_application()
```

- [ ] **Step 5: Create `.env.example` and `.env`**

`.env.example`:
```
DJANGO_SETTINGS_MODULE=config.settings.local
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=true
DATABASE_URL=postgres://libli:libli@localhost:5432/libli
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
```

Run:
```bash
cp .env.example .env
cat > .gitignore <<'EOF'
# Python
__pycache__/
*.py[cod]
.venv/
# Django
*.log
staticfiles/
media/
# Env / secrets
.env
# Tooling / sessions
.superpowers/
.ruff_cache/
.pytest_cache/
EOF
```
(`uv.lock` is intentionally committed, not ignored. If a `.gitignore` already
exists with other entries — e.g. `.superpowers/` — merge rather than overwrite.)

- [ ] **Step 6: Create the local PostgreSQL role and database**

Run:
```bash
createuser libli 2>/dev/null || true
createdb libli -O libli 2>/dev/null || true
psql -c "ALTER USER libli WITH PASSWORD 'libli';" 2>/dev/null || true
```
Expected: idempotent; ignore "already exists".

- [ ] **Step 7: Create the two empty apps so `INSTALLED_APPS` imports succeed**

Run:
```bash
mkdir -p accounts/migrations institution/migrations
touch accounts/__init__.py accounts/migrations/__init__.py
touch institution/__init__.py institution/migrations/__init__.py
```

`accounts/apps.py`:
```python
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
```

`institution/apps.py`:
```python
from django.apps import AppConfig


class InstitutionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "institution"
```

Add empty `accounts/models.py` and `institution/models.py` (just `# models added in later tasks`) so the apps import.

- [ ] **Step 8: Verify the project boots**

Run: `uv run python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 9: Format, then commit**

```bash
uv run ruff format .
git add config manage.py accounts institution .env.example .gitignore
git commit -m "feat: Django project skeleton with split settings"
```
(Run `uv run ruff format .` before each later commit too, so CI's
`ruff format --check` passes on every pushed commit.)

---

### Task 3: Test harness, smoke test, and CI

**Files:**
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/test_smoke.py`, `.github/workflows/ci.yml`

- [ ] **Step 1: Create the test package and a smoke test**

`tests/__init__.py`: empty.

`tests/test_smoke.py`:
```python
def test_healthz(client):
    response = client.get("/healthz/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Create `tests/conftest.py`**

```python
import pytest


@pytest.fixture(autouse=True)
def _enable_db_access(db):
    """Give every test DB access (small project; convenient default).

    Consequence: every test — including the /healthz smoke test — needs a
    running PostgreSQL. That coupling is intentional for this project."""
```

- [ ] **Step 3: Run the smoke test to verify the harness works**

Run: `uv run python -m pytest tests/test_smoke.py -v`
Expected: PASS (the smoke test passes). If it fails with a DB connection error, re-check Task 2 Step 6.

- [ ] **Step 4: Create the CI workflow**

`.github/workflows/ci.yml`:
```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: libli
          POSTGRES_PASSWORD: libli
          POSTGRES_DB: libli
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready --health-interval 10s
          --health-timeout 5s --health-retries 5
    env:
      DJANGO_SETTINGS_MODULE: config.settings.test
      DATABASE_URL: postgres://libli:libli@localhost:5432/libli
      DJANGO_SECRET_KEY: ci-secret
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.13"
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run python -m pytest
```

- [ ] **Step 5: Verify lint and format pass locally**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: `All checks passed!` (run `uv run ruff format .` first if needed).

- [ ] **Step 6: Commit**

```bash
git add tests .github
git commit -m "test: add pytest harness, smoke test, and CI workflow"
```

---

### Task 4: Custom User model

**Files:**
- Modify: `accounts/models.py`
- Create: `tests/factories.py`, `tests/test_user_model.py`
- Migration: `accounts/migrations/0001_initial.py` (generated)

- [ ] **Step 1: Write the failing tests**

`tests/test_user_model.py`:
```python
import pytest
from django.db import IntegrityError

from accounts.models import User


def test_user_with_username_only_has_no_email():
    user = User.objects.create_user(username="young.student", password="x")
    assert user.username == "young.student"
    assert user.email == ""
    assert user.language == "en"
    assert user.theme == "auto"


def test_user_str_prefers_display_name():
    user = User.objects.create_user(username="jan", display_name="Jan Kowalski", password="x")
    assert str(user) == "Jan Kowalski"


def test_user_str_falls_back_to_username():
    user = User.objects.create_user(username="jan", password="x")
    assert str(user) == "jan"


def test_email_is_unique_when_present():
    User.objects.create_user(username="a", email="dup@x.edu", password="x")
    with pytest.raises(IntegrityError):
        User.objects.create_user(username="b", email="dup@x.edu", password="x")


def test_blank_emails_do_not_collide():
    User.objects.create_user(username="a", password="x")
    User.objects.create_user(username="b", password="x")  # both have no email -> NULL, allowed
    assert User.objects.count() == 2


def test_auth_user_model_is_custom():
    # Guards the spec's one non-reversible risk: the swappable user model must be
    # accounts.User from the first migration on.
    from django.conf import settings
    from django.contrib.auth import get_user_model

    assert settings.AUTH_USER_MODEL == "accounts.User"
    assert get_user_model() is User
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_user_model.py -v`
Expected: FAIL (cannot import `User`, or model not defined).

- [ ] **Step 3: Implement the `User` model**

`accounts/models.py`:
```python
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """libli user. Username is the required identifier; email is optional
    (required only on the open self-signup form). See Phase 0 spec §1."""

    LANG_CHOICES = [("en", "English"), ("pl", "Polski")]
    THEME_CHOICES = [("light", "Light"), ("dark", "Dark"), ("auto", "Auto")]

    # Email is optional but unique when present. Empty input is normalized to
    # NULL in save() so Postgres's unique index ignores it (many emailless users
    # are allowed). INVARIANT: all user creation goes through create_user()/save();
    # do not bulk_create users, which would bypass this normalization.
    email = models.EmailField("email address", blank=True, null=True, unique=True)
    # Optional human-friendly name; falls back to username in __str__.
    display_name = models.CharField(max_length=150, blank=True)
    language = models.CharField(max_length=5, choices=LANG_CHOICES, default="en")
    theme = models.CharField(max_length=5, choices=THEME_CHOICES, default="auto")

    def save(self, *args, **kwargs):
        # Normalize blank email to NULL so the unique constraint ignores it.
        if not self.email:
            self.email = None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name or self.username
```

> Note: storing blank email as `NULL` lets Postgres's unique index ignore empty values (multiple emailless users are allowed). The test asserts `user.email == ""` — handle this by reading back through a refresh; adjust: see Step 3b.

- [ ] **Step 3b: Reconcile the empty-vs-null email representation**

Update the first test so the contract is explicit (empty input normalizes to `None`):
```python
def test_user_with_username_only_has_no_email():
    user = User.objects.create_user(username="young.student", password="x")
    assert user.username == "young.student"
    assert not user.email          # None — no email
    assert user.language == "en"
    assert user.theme == "auto"
```

- [ ] **Step 4: Make the initial migration**

Run: `uv run python manage.py makemigrations accounts`
Expected: `Create model User` migration `accounts/migrations/0001_initial.py`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_user_model.py -v`
Expected: PASS (all tests in the file pass).

- [ ] **Step 6: Add a User factory for later tasks**

`tests/factories.py`:
```python
import factory

from accounts.models import User


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user{n}")
    display_name = factory.Faker("name")
    password = factory.PostGenerationMethodCall("set_password", "password123")
```

- [ ] **Step 7: Commit**

```bash
git add accounts/models.py accounts/migrations tests/test_user_model.py tests/factories.py
git commit -m "feat: custom User model (username required, optional unique email)"
```

---

### Task 5: Institution singleton + BrandColor

**Files:**
- Modify: `institution/models.py`
- Create: `tests/test_institution.py`
- Migration: `institution/migrations/0001_initial.py` (generated)

- [ ] **Step 1: Write the failing tests**

`tests/test_institution.py`:
```python
from institution.models import BrandColor
from institution.models import Institution


def test_load_creates_and_returns_singleton():
    first = Institution.load()
    second = Institution.load()
    assert first.pk == second.pk == 1
    assert Institution.objects.count() == 1


def test_saving_always_uses_pk_1():
    inst = Institution(name="Greenfield")
    inst.save()
    assert inst.pk == 1
    assert Institution.objects.count() == 1  # never inserts a duplicate row


def test_defaults():
    inst = Institution.load()
    assert inst.signup_policy == "invite"
    assert inst.default_theme == "auto"
    assert inst.default_language == "en"
    assert inst.enabled_languages == ["en", "pl"]
    assert inst.allowed_email_domains == []


def test_brand_colors_are_extensible():
    # Use non-default keys: primary/accent are seeded by migration 0002 (Step 6),
    # so re-creating them here would violate (institution, key) uniqueness.
    inst = Institution.load()
    BrandColor.objects.create(institution=inst, key="surface", value="#F4F1EA")
    BrandColor.objects.create(institution=inst, key="highlight", value="#E76F51")  # future colors, no schema change
    keys = set(inst.brand_colors.values_list("key", flat=True))
    assert {"surface", "highlight"} <= keys
    assert inst.brand_colors.get(key="surface").value == "#F4F1EA"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_institution.py -v`
Expected: FAIL (cannot import models).

- [ ] **Step 3: Implement the models**

`institution/models.py`:
```python
from django.db import models


class Institution(models.Model):
    """Single-row, runtime-editable institution config. Use Institution.load()."""

    SIGNUP_CHOICES = [("invite", "Invite only"), ("open", "Open self-signup")]
    THEME_CHOICES = [("light", "Light"), ("dark", "Dark"), ("auto", "Auto")]

    name = models.CharField(max_length=200, default="My Institution")
    logo = models.ImageField(upload_to="branding/", blank=True, null=True)
    signup_policy = models.CharField(max_length=10, choices=SIGNUP_CHOICES, default="invite")
    allowed_email_domains = models.JSONField(default=list, blank=True)
    enabled_languages = models.JSONField(default=lambda: ["en", "pl"], blank=True)
    default_language = models.CharField(max_length=5, default="en")
    default_theme = models.CharField(max_length=5, choices=THEME_CHOICES, default="auto")

    def save(self, *args, **kwargs):
        # Enforce singleton: always row pk=1. A second save() updates that one
        # row rather than inserting a duplicate.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return self.name


class BrandColor(models.Model):
    """Named brand color (e.g. 'primary', 'accent'). Extensible without schema change."""

    institution = models.ForeignKey(Institution, related_name="brand_colors", on_delete=models.CASCADE)
    key = models.SlugField(max_length=40)
    value = models.CharField(max_length=64)  # CSS color string; Phase 0 uses hex (e.g. #147E78)

    class Meta:
        unique_together = [("institution", "key")]

    def __str__(self):
        return f"{self.key}={self.value}"
```

> `enabled_languages` uses `default=lambda: [...]`. Django migrations cannot serialize a lambda — use a module-level function instead. See Step 3b.

- [ ] **Step 3b: Replace the lambda default with a named callable**

In `institution/models.py`, above the class:
```python
def default_languages():
    return ["en", "pl"]
```
And change the field to `enabled_languages = models.JSONField(default=default_languages, blank=True)`.

- [ ] **Step 4: Make the migration**

Run: `uv run python manage.py makemigrations institution`
Expected: creates `institution/migrations/0001_initial.py` with `Institution` and `BrandColor`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_institution.py -v`
Expected: PASS (all tests in the file pass).

- [ ] **Step 6: Seed the default Institution row and brand colors (data migration)**

The spec (§3) requires the palette to be seeded with `primary` and `accent`.

Run: `uv run python manage.py makemigrations institution --empty --name seed_branding`
Then edit `institution/migrations/0002_seed_branding.py`:
```python
from django.db import migrations

DEFAULT_COLORS = {"primary": "#147E78", "accent": "#C77B2A"}


def forwards(apps, schema_editor):
    Institution = apps.get_model("institution", "Institution")
    BrandColor = apps.get_model("institution", "BrandColor")
    inst, _ = Institution.objects.get_or_create(pk=1)
    for key, value in DEFAULT_COLORS.items():
        BrandColor.objects.get_or_create(institution=inst, key=key, defaults={"value": value})


def backwards(apps, schema_editor):
    BrandColor = apps.get_model("institution", "BrandColor")
    BrandColor.objects.filter(key__in=DEFAULT_COLORS).delete()


class Migration(migrations.Migration):
    dependencies = [("institution", "0001_initial")]
    operations = [migrations.RunPython(forwards, backwards)]
```

> Historical migration models have no custom `save()`, so `get_or_create(pk=1)`
> sets the singleton explicitly. Default hex values come from `docs/design-language.md`.

- [ ] **Step 7: Add a test that the default brand colors are seeded**

Append to `tests/test_institution.py`:
```python
def test_default_brand_colors_seeded():
    # Seeded by migration 0002_seed_branding when the test DB is built.
    inst = Institution.load()
    keys = set(inst.brand_colors.values_list("key", flat=True))
    assert {"primary", "accent"} <= keys
    assert inst.brand_colors.get(key="primary").value == "#147E78"
```

Run: `uv run python -m pytest tests/test_institution.py -v`
Expected: PASS (all tests in the file pass).

- [ ] **Step 8: Format and commit**

```bash
uv run ruff format .
git add institution/models.py institution/migrations tests/test_institution.py
git commit -m "feat: Institution singleton + extensible BrandColor + seeded primary/accent"
```

---

### Task 6: RBAC role seeding

**Files:**
- Create: `institution/roles.py`, `institution/management/__init__.py`, `institution/management/commands/__init__.py`, `institution/management/commands/setup_roles.py`, `tests/test_roles.py`
- Migration: `institution/migrations/0002_seed_roles.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_roles.py`:
```python
from django.contrib.auth.models import Group

from institution.roles import ROLE_NAMES
from institution.roles import seed_roles


def test_seed_roles_creates_all_four():
    seed_roles()
    assert set(Group.objects.values_list("name", flat=True)) >= set(ROLE_NAMES)


def test_seed_roles_is_idempotent():
    seed_roles()
    seed_roles()
    for name in ROLE_NAMES:
        assert Group.objects.filter(name=name).count() == 1


def test_platform_admin_gets_phase0_permissions():
    seed_roles()
    pa = Group.objects.get(name="Platform Admin")
    codenames = set(pa.permissions.values_list("codename", flat=True))
    assert {"change_institution", "view_institution", "change_user"} <= codenames
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_roles.py -v`
Expected: FAIL (cannot import `institution.roles`).

- [ ] **Step 3: Implement `institution/roles.py`**

```python
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission

STUDENT = "Student"
TEACHER = "Teacher"
COURSE_ADMIN = "Course Admin"
PLATFORM_ADMIN = "Platform Admin"

ROLE_NAMES = [STUDENT, TEACHER, COURSE_ADMIN, PLATFORM_ADMIN]

# Phase 0 ships only account/institution-management permissions, assigned to
# Platform Admin (spec §2). Later phases attach their own permissions to the
# relevant roles. Codenames are Django's auto-generated add/change/delete/view.
PLATFORM_ADMIN_PERMS = [
    "accounts.add_user",
    "accounts.change_user",
    "accounts.view_user",
    "accounts.delete_user",
    "institution.change_institution",
    "institution.view_institution",
    "institution.add_brandcolor",
    "institution.change_brandcolor",
    "institution.delete_brandcolor",
    "institution.view_brandcolor",
]


def _permission(label):
    app_label, codename = label.split(".")
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def seed_roles():
    """Create the four role Groups (idempotent) and assign Phase-0 permissions to
    Platform Admin. Permissions must already exist, so run this after `migrate`
    (the setup_roles command and the DoD do exactly that)."""
    groups = {name: Group.objects.get_or_create(name=name)[0] for name in ROLE_NAMES}
    groups[PLATFORM_ADMIN].permissions.set([_permission(label) for label in PLATFORM_ADMIN_PERMS])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_roles.py -v`
Expected: PASS (all tests in the file pass).

- [ ] **Step 5: Add a management command wrapper**

`institution/management/commands/setup_roles.py`:
```python
from django.core.management.base import BaseCommand

from institution.roles import seed_roles


class Command(BaseCommand):
    help = "Create the four libli role Groups (idempotent)."

    def handle(self, *args, **options):
        seed_roles()
        self.stdout.write(self.style.SUCCESS("Roles ensured."))
```
Create the empty `__init__.py` files for `institution/management/` and `institution/management/commands/`.

- [ ] **Step 6: Add a data migration so roles exist on every deploy**

Run: `uv run python manage.py makemigrations institution --empty --name seed_roles`
(auto-numbers to `0003_seed_roles` after `0002_seed_branding`.) Then edit
`institution/migrations/0003_seed_roles.py` — this migration creates only the
Groups; the Phase-0 *permissions* are assigned by `seed_roles()` / `setup_roles`,
because permission rows are created by a post-migrate signal and aren't reliably
available mid-migration:
```python
from django.db import migrations


def forwards(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ["Student", "Teacher", "Course Admin", "Platform Admin"]:
        Group.objects.get_or_create(name=name)


def backwards(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(
        name__in=["Student", "Teacher", "Course Admin", "Platform Admin"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("institution", "0002_seed_branding"),
        ("auth", "0001_initial"),  # Group model exists since auth's first migration (version-stable)
    ]
    operations = [migrations.RunPython(forwards, backwards)]
```

> The data migration hardcodes the names (migrations must not import app code that may change). `seed_roles()` / `ROLE_NAMES` remain the runtime source of truth and are covered by the Step 1 tests.

- [ ] **Step 7: Verify the command and migration run**

Run: `uv run python manage.py migrate && uv run python manage.py setup_roles`
Expected: migrations apply; `Roles ensured.`

- [ ] **Step 8: Commit**

```bash
git add institution/roles.py institution/management institution/migrations/0003_seed_roles.py tests/test_roles.py
git commit -m "feat: seed RBAC role Groups + Platform Admin Phase-0 permissions"
```

---

### Task 7: Admin registration and full verification

**Files:**
- Modify: `accounts/admin.py`, `institution/admin.py`

- [ ] **Step 1: Register the User in admin**

`accounts/admin.py`:
```python
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import User

class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("libli", {"fields": ("display_name", "language", "theme")}),
    )


admin.site.register(User, CustomUserAdmin)
```

- [ ] **Step 2: Register Institution and BrandColor in admin**

`institution/admin.py`:
```python
from django.contrib import admin

from institution.models import BrandColor
from institution.models import Institution


class BrandColorInline(admin.TabularInline):
    model = BrandColor
    extra = 0


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    inlines = [BrandColorInline]
```

- [ ] **Step 3: Run the full test suite + lint + migration check**

Run:
```bash
uv run ruff check . && uv run ruff format --check .
uv run python -m pytest -v
uv run python manage.py makemigrations --check --dry-run
```
Expected: lint passes; all tests pass; `No changes detected` for migrations.

- [ ] **Step 4: Manual smoke — create a superuser and open admin**

Run:
```bash
uv run python manage.py migrate
uv run python manage.py createsuperuser --username admin
uv run python manage.py runserver
```
Expected: visit `http://127.0.0.1:8000/admin/`, log in, see Users / Institutions / BrandColors. Confirm editing an Institution shows the BrandColor inline.

- [ ] **Step 5: Commit**

```bash
git add accounts/admin.py institution/admin.py
git commit -m "feat: admin for User, Institution, BrandColor"
```

---

## Definition of Done (Plan 0a)

- `uv sync` succeeds on a fresh checkout; `uv run python manage.py check` is clean.
- `uv run python -m pytest` is green (smoke, user model, institution, roles).
- `uv run ruff check .` and `uv run ruff format --check .` pass.
- `makemigrations --check --dry-run` reports no missing migrations.
- `AUTH_USER_MODEL = accounts.User` is active from the first migration (asserted by `test_auth_user_model_is_custom`).
- The four role Groups exist after `migrate`; after `setup_roles`, Platform Admin holds the Phase-0 account/institution-management permissions.
- The singleton Institution and its seeded `primary`/`accent` BrandColors exist after `migrate`.
- Admin lists Users, Institutions (with BrandColor inline).

**Out of scope (later plans):** allauth/login/signup (0b), SSO + JIT + `init_platform` (0c), i18n + bespoke CSS/theming + landing/dashboard/settings views + error pages (0d).

---

## Self-Review

- **Spec coverage:** Stack/layout (Task 1–2) ✓; custom User w/ username+optional email, display_name, language, theme, + AUTH_USER_MODEL verification (Task 4) ✓; Institution singleton w/ branding palette (BrandColor), signup_policy, allowed_email_domains, enabled_languages, default_theme, **+ seeded primary/accent** (Task 5) ✓; RBAC Groups seeded + re-sliceable + **Phase-0 permissions assigned to Platform Admin** (Task 6), with default-Student-on-signup deferred to 0b where account creation lives ✓; tests vs real Postgres + factory_boy + ruff + CI (Task 3) ✓. Auth/SSO/i18n/theming/views correctly deferred to 0b–0d.
- **Placeholder scan:** none — every code step shows full code; Steps 3b explicitly reconcile the two known Django gotchas (NULL email uniqueness, non-serializable lambda default).
- **Type consistency:** `Institution.load()`, `seed_roles()`/`ROLE_NAMES`, `User.display_name/language/theme`, `BrandColor(key, value, institution)` are used consistently across tasks and tests.
