# Local setup

How to get libli running on your machine, from a fresh clone to a logged-in
Platform Admin. The command sequence mirrors
[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml), which is the source
of truth for how the project is built and tested.

## Prerequisites

- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — manages the
  Python 3.13 toolchain and the virtualenv. You do not need to install Python
  separately; `uv sync` provisions it.
- **PostgreSQL 16**, running locally on `:5432`. SQLite is not supported (the
  code uses Postgres-specific behaviour).

## 1. Install dependencies

```bash
uv sync
```

This creates `.venv/` from `uv.lock` (runtime + dev dependencies, including
pytest, ruff, and Playwright). Prefix project commands with `uv run` so they use
that environment — e.g. `uv run python manage.py …`. (Bare `python`, `ruff`, and
`pytest` are **not** on your PATH; always go through `uv run`.)

## 2. Database

Create a role and database that match `DATABASE_URL` in `.env.example`
(`postgres://libli:libli@localhost:5432/libli`). The role needs **CREATEDB** so
the test runner can create and drop the test database.

```bash
createuser --createdb libli --pwprompt   # enter password: libli
createdb --owner libli libli
```

(Equivalently, from `psql`:
`CREATE ROLE libli LOGIN PASSWORD 'libli' CREATEDB;`
`CREATE DATABASE libli OWNER libli;`)

## 3. Environment

```bash
cp .env.example .env
```

`.env` holds five variables. `config/settings/base.py` reads `.env` when it
exists; in CI and production there is no file and the same variables are read
from the real environment instead.

| Variable | Purpose |
| --- | --- |
| `DJANGO_SETTINGS_MODULE` | Which settings module to load. `config.settings.local` for development. |
| `DJANGO_SECRET_KEY` | Django secret. **Change it** from the placeholder, even locally. |
| `DJANGO_DEBUG` | `true` locally; never `true` in production. |
| `DATABASE_URL` | Postgres connection string (matches the role/db above). |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames; `localhost,127.0.0.1` for dev. |

The settings package is split into
`config/settings/{base,local,test,production}.py`; `DJANGO_SETTINGS_MODULE`
selects one. Tests always use `config.settings.test` (pinned in
`pyproject.toml`).

## 4. Migrate and bootstrap

```bash
uv run python manage.py migrate
uv run python manage.py init_platform
```

`init_platform` is idempotent and does three things: seeds the RBAC role groups
(it calls `setup_roles`), creates the `Institution` singleton, and mints the
first **Platform Admin**. Credentials come from the environment
(`INIT_ADMIN_USERNAME`, `INIT_ADMIN_EMAIL`, `INIT_ADMIN_PASSWORD`) or, when you
run it interactively, from prompts. The admin's email is pre-verified so you can
log in through the allauth front door immediately.

Optionally seed a demo course, content tree, and an enrolled student:

```bash
uv run python manage.py seed_demo_course
```

## 5. Run

```bash
uv run python manage.py runserver
```

Open <http://localhost:8000/> and log in as the Platform Admin you just created.
New Platform Admins land in a first-run setup wizard (branding, users, SSO)
before the dashboard.

## Running tests

```bash
uv run pytest                        # unit + integration; browser e2e excluded by default
```

Browser end-to-end tests are marked `e2e` and skipped by default (see
`addopts = "-q -m 'not e2e'"` in `pyproject.toml`). To run them, install the
Chromium browser once, then select the marker:

```bash
uv run playwright install chromium
uv run pytest -m e2e
```

## Gotchas

- **Emailed links say `example.com`.** Invitation and password-reset links are
  built from the `django.contrib.sites` Site record, which ships with the
  placeholder domain `example.com`. Set it once for local dev — see
  [`docs/local-development.md`](../local-development.md), which also covers
  scheduling the notification-purge command.
- **`uv run` for everything.** If a command "isn't found," you almost certainly
  dropped the `uv run` prefix.

## Where next

- [`architecture.md`](architecture.md) — the apps, the content model, the layout.
- [`conventions.md`](conventions.md) — code style, testing, i18n, migrations.
