# libli

**libli** is a self-hosted, single-tenant, multi-language (English / Polish)
e-learning platform. An institution — a school, say — runs its own instance:
authors build courses, teachers group students and track progress, and students
work through lessons and quizzes. It is built from scratch with Django and is
**server-rendered** (no SPA); the interactive bits are vanilla JS.

- **Stack:** Python 3.13 · Django 5.2 · [uv](https://docs.astral.sh/uv/) · PostgreSQL 16 · server-rendered templates + vanilla JS (no React, no Bootstrap)
- **Roles:** Student · Teacher · Course Admin · Platform Admin (RBAC via Django groups)
- **Auth:** local accounts + invitations (django-allauth) and optional OIDC SSO

## Quickstart

Assumes [uv](https://docs.astral.sh/uv/getting-started/installation/) and a
running PostgreSQL 16. This is the five-minute path; see
[`docs/development/setup.md`](docs/development/setup.md) for the full walkthrough
(prerequisites, the database role, environment variables, gotchas).

```bash
# 1. Install dependencies (creates the virtualenv from the lockfile)
uv sync

# 2. Configure the environment
cp .env.example .env          # then edit DJANGO_SECRET_KEY

# 3. Create the Postgres role + database (matches DATABASE_URL in .env.example)
createuser --createdb libli --pwprompt   # password: libli
createdb --owner libli libli

# 4. Migrate and bootstrap the first Platform Admin
uv run python manage.py migrate
uv run python manage.py init_platform     # prompts for admin username/email/password

# 5. (Optional) seed a demo course with an enrolled student
uv run python manage.py seed_demo_course

# 6. Run the server, then log in at http://localhost:8000/
uv run python manage.py runserver
```

> **Local email links** (invitations, password reset) point at `example.com`
> until you set the Site domain once — see
> [`docs/local-development.md`](docs/local-development.md).

## Documentation

| If you want to… | Read |
| --- | --- |
| Get libli running locally, end to end | [`docs/development/setup.md`](docs/development/setup.md) |
| Understand the apps, the content model, and the layout | [`docs/development/architecture.md`](docs/development/architecture.md) |
| Know the code conventions (style, tests, i18n) | [`docs/development/conventions.md`](docs/development/conventions.md) |
| Learn the product as an admin / author / teacher | the in-app help at **`/help/`** (login required) |
| See the original vision and roadmap | [`docs/planning/`](docs/planning/) · [`docs/roadmap.md`](docs/roadmap.md) |

## Tests

```bash
uv run pytest                 # unit + integration (browser e2e excluded by default)
uv run playwright install chromium
uv run pytest -m e2e          # browser end-to-end tests
```

See [`docs/development/conventions.md`](docs/development/conventions.md) for the
full checks CI runs (ruff lint **and** format, migrations, e2e).
