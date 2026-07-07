# Env production-readiness + docstrings/module-map — design (docs slice 4 of 4)

**Status:** approved in brainstorming 2026-07-07
**Slice:** 4 of 4 — the final slice of the documentation initiative (1 = SIS webhook guide #70; 2 = in-app `/help/` role manuals #71; 3 = developer onboarding README + `docs/development/` #74; **4 = docstring + `.env` gaps [this]**). This PR closes the initiative.

## Problem

Two gaps surfaced while writing the earlier slices:

1. **`.env.example` is incomplete and production email is not wired.** The file lists 5 variables, but `config/settings/` reads more (`LIBLI_ALLOWED_EMBED_DOMAINS`, `DJANGO_HTMLEL_SANDBOX_ORIGIN`, `DJANGO_SECURE_SSL_REDIRECT`, and the `INIT_ADMIN_*` bootstrap vars). More seriously, **`config/settings/production.py` has no email/SMTP configuration, no `ACCOUNT_DEFAULT_HTTP_PROTOCOL`, and no `CSRF_TRUSTED_ORIGINS`** — a real deploy cannot send invitation / password-reset mail, and emailed links default to `http` (compounding the `example.com` Site-domain gotcha already documented in `docs/local-development.md`). None of this is env-driven today.

2. **Silent helper modules.** Across the apps, ~31 pure-logic / service / helper modules have no module-level docstring, so a developer opening one directly gets no orientation. (A full function/class docstring sweep — 592 functions — is explicitly *out of scope*: high churn, low value, models and obvious views are self-documenting.)

## Decisions (from brainstorming)

1. **Wire production readiness** (not just document) — add env hooks for SMTP email, HTTPS protocol, CSRF trusted origins, and reverse-proxy SSL header, all with safe defaults so nothing breaks when unset.
2. **Docstrings = module-level only, on the ~31 silent seam modules** — no function/class/model docstrings, no signature changes.
3. **Add a "Module map" section to `architecture.md`** (from slice 3) as the single navigation aid, complementing the in-file module docstrings.
4. **Process** — direct TDD (one focused settings test) + one PR; not subagent-driven.

## Workstream A — environment & production readiness

### `config/settings/production.py`
Currently just `DEBUG=False` + `SECURE_SSL_REDIRECT` + secure cookies. Add, all env-driven:

- **Email (SMTP, opt-in):** read `DJANGO_EMAIL_HOST`, `DJANGO_EMAIL_PORT` (int, default 587), `DJANGO_EMAIL_HOST_USER`, `DJANGO_EMAIL_HOST_PASSWORD`, `DJANGO_EMAIL_USE_TLS` (bool, default true). If `DJANGO_EMAIL_HOST` is set, `EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"` and the host/port/user/password/TLS settings are applied; if it is **unset**, leave the backend at Django's default so an unconfigured deploy fails loudly/consistently rather than silently — **safe default: nothing changes when the var is absent.**
- **From addresses:** `DEFAULT_FROM_EMAIL` and `SERVER_EMAIL` from `DJANGO_DEFAULT_FROM_EMAIL` (default `"libli <no-reply@localhost>"`).
- **HTTPS link protocol:** `ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"` (allauth builds verification / invite / reset links with this; default is `http`). Static in production (not env-gated).
- **CSRF trusted origins:** `CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])` (scheme+host entries required by Django behind HTTPS).
- **Reverse proxy:** when `env.bool("DJANGO_BEHIND_PROXY", default=False)`, set `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` (the header the SSO live-test checklist calls out).

All reads use the existing `django-environ` `env` imported via `base import *`. `# noqa: F405` where the star-import triggers the undefined-name lint (matching the existing `SECURE_SSL_REDIRECT` line).

### `.env.example`
Rewrite as a commented, sectioned file. Every variable gets a one-line comment.

```
# --- core (all environments) ---
DJANGO_SETTINGS_MODULE, DJANGO_SECRET_KEY, DJANGO_DEBUG, DATABASE_URL, DJANGO_ALLOWED_HOSTS

# --- local dev extras (have safe defaults; override only if needed) ---
LIBLI_ALLOWED_EMBED_DOMAINS, DJANGO_HTMLEL_SANDBOX_ORIGIN

# --- production only ---
DJANGO_SECURE_SSL_REDIRECT, DJANGO_BEHIND_PROXY, DJANGO_CSRF_TRUSTED_ORIGINS,
DJANGO_EMAIL_HOST, DJANGO_EMAIL_PORT, DJANGO_EMAIL_HOST_USER,
DJANGO_EMAIL_HOST_PASSWORD, DJANGO_EMAIL_USE_TLS, DJANGO_DEFAULT_FROM_EMAIL

# --- bootstrap (init_platform; env OR interactive prompt) ---
INIT_ADMIN_USERNAME, INIT_ADMIN_EMAIL, INIT_ADMIN_PASSWORD
```

Production secrets (`DJANGO_EMAIL_HOST_PASSWORD`) appear as empty placeholders with a comment, never a real value. The local-dev block stays uncommented and working; production/bootstrap blocks are commented-out examples.

### Test
One focused test module (e.g. `tests/test_settings_production.py`) that loads the production settings with a patched environment and asserts:
- with SMTP env set → `EMAIL_BACKEND` is the SMTP backend and `EMAIL_HOST`/`EMAIL_PORT`/`EMAIL_USE_TLS`/`CSRF_TRUSTED_ORIGINS` reflect the env;
- `ACCOUNT_DEFAULT_HTTP_PROTOCOL == "https"`;
- with `DJANGO_BEHIND_PROXY=true` → `SECURE_PROXY_SSL_HEADER` is set; unset → absent;
- with **no** `DJANGO_EMAIL_HOST` → the backend is not switched to SMTP (safe default).

Mechanism: reload `config.settings.production` via `importlib` under `monkeypatch.setenv`, or read the resolved values through a small helper — chosen at build time to keep the test hermetic (must not leak env into other tests). Test file is `not e2e`, runs in the default suite.

## Workstream B — docstrings + module map

### Module docstrings (one line each)
Add a concise module-level docstring to the silent seam modules (verified list, 2026-07-07):

`accounts/adapters.py`; `courses/{access,builder,constants,element_forms,exporters,fields,gradebook,marking,media,ordering,rollups,sanitize,validators,widgets}.py`, `courses/templatetags/{courses_extras,courses_manage_extras}.py`, `courses/management/commands/seed_demo_course.py`; `grouping/{scoping,services}.py`; `institution/roles.py`, `institution/management/commands/setup_roles.py`; `integrations/management/commands/flush_webhooks.py`; `notes/{rendering,services}.py`, `notes/templatetags/notes_extras.py`; `notifications/{recipients,services}.py`, `notifications/management/commands/purge_notifications.py`; `tags/{rendering,services}.py`.

Each docstring states what the module is for in one sentence — no behavioral change, no imports moved, first statement in the file so ruff/format stay clean. (Modules that already have docstrings — `scoring.py`, `dnd.py`, `keywords.py`, `video_url.py`, `geogebra.py`, `provisioning.py`, etc. — are left untouched.)

### `docs/development/architecture.md` — "Module map"
Add a section listing the key modules grouped by app, one line each (what it owns), so a developer navigates from one doc:
- `courses/`: scoring, ordering, rollups, marking, keywords, dnd, media, exporters, builder, access, scoping-adjacent helpers, video_url, geogebra, sanitize, validators, fields, widgets, gradebook.
- `accounts/`: provisioning, adapters, invitations, emails.
- `grouping/`: scoping, services. `institution/`: roles, services. `notifications/`: services, recipients. `notes/` & `tags/`: services, rendering. `integrations/`: services, delivery, docs.
Keep to one line per module; this is a map, not an API reference. It complements (does not duplicate) the existing app-map and content-model sections.

## Non-goals
- No function/class/model docstring sweep (the 592 — out).
- No `.pl` translations of any of this.
- Not opinionated about an email provider — production email is made *configurable*, with a safe no-op default.
- No new runtime features, views, or URLs.

## Verification
- `uv run ruff check .` **and** `uv run ruff format --check .` clean.
- `uv run python -m pytest` green, including the new settings test.
- `uv run python manage.py check` clean; `makemigrations --check` clean (no model changes expected).
- Sanity: load production settings with a sample prod-like env and confirm the SMTP backend + https protocol resolve; confirm `.env.example` local-dev block still boots the app.
- All new `architecture.md` module-map links/paths are real.

## Process
Branch `docs/env-and-docstrings` off master (slice 3 / PR #74 merged). TDD the settings behaviour first, then module docstrings + `.env.example` + module map. One PR; closes the 4-slice documentation initiative.
