# Developer onboarding docs — design (docs slice 3 of 4)

**Status:** approved in brainstorming 2026-07-07
**Slice:** 3 of the 4-part documentation initiative (1 = SIS webhook guide, merged PR #70; 2 = in-app `/help/` role manuals, merged PR #71; **3 = developer onboarding [this]**; 4 = docstring + `.env.example` gaps).

## Problem

A developer who clones libli today gets **no orientation at all**: there is no top-level `README.md`. The only setup-adjacent doc is `docs/local-development.md`, which is two narrow gotchas (Site domain for emailed links, notification-purge scheduling) — not a setup guide. The original vision notes (`main_idea.md`, `roles.md`, `views.md`, `differences.md`) sit loose in the repo root, are partly stale, and are pre-build brainstorming rather than current reference.

Goal: give a developer who wants to **run libli locally and start adding features** a real README, a verified setup guide, an app-map/architecture overview, and the code conventions used here.

## Decisions (from brainstorming)

1. **Structure** — a concise top-level `README.md` that links into a new `docs/development/` folder of focused files. Not one giant README.
2. **Loose root notes** — move `main_idea.md`, `roles.md`, `views.md`, `differences.md` into `docs/planning/`, clearly labeled as the original/historical vision; the new docs are authoritative. `architecture.md` links to them as historical context.
3. **Language** — English only (code-facing docs; the codebase, commits, and comments are already English). No `.pl.md` variants, unlike the user-facing help slices.
4. **Conventions scope** — code-level conventions **only**. The spec→plan→subagent-driven meta-process is deliberately **out of scope** (it is about how the maintainer drives the build, not a contract a contributor needs).
5. **Process** — lighter than slices 1–2: this slice is pure Markdown + a file move, no runtime code and no new tests. Write the docs directly, **verify every command live**, ship one PR. (This design doc is still written for a reviewable artifact.)

## Deliverables

```
README.md                        NEW  — what libli is, quickstart, links out
docs/development/
  setup.md                       NEW  — full local setup, prereqs → running server + first login
  architecture.md                NEW  — app-map, data/request flow, key models, settings layout
  conventions.md                 NEW  — code style, testing, i18n, content-model pattern, migrations
docs/planning/                   MOVED from repo root (git mv), historical
  main_idea.md, roles.md, views.md, differences.md
docs/local-development.md        KEPT — setup.md links to it for the two deep gotchas
```

### README.md
- One-paragraph "what is libli": self-hosted, single-tenant, multi-language (EN/PL) e-learning platform; Django, server-rendered; RBAC (Student / Teacher / Course Admin / Platform Admin).
- Stack line: Python 3.13, Django 5.2, uv, PostgreSQL 16, server-rendered templates + vanilla JS (no React/Bootstrap).
- **Quickstart** (copy-paste): clone → `uv sync` → copy `.env.example` to `.env` → create the Postgres role/db → `uv run python manage.py migrate` → `uv run python manage.py init_platform` → `uv run python manage.py runserver`.
- **Where to go next** table: links to `docs/development/setup.md` (full setup), `architecture.md`, `conventions.md`, the in-app `/help/` manuals (for non-dev admins/authors), and `docs/planning/` (original vision).
- Keep it skimmable; depth lives in the linked files.

### docs/development/setup.md
- **Prerequisites**: uv, PostgreSQL 16. The dev DB triple from the project's convention: role `libli` / password `libli` / db `libli` on `:5432`, role needs `CREATEDB` (for the test DB). Include the `createuser`/`createdb` (or `psql`) commands.
- **Environment**: copy `.env.example` → `.env`; explain each of the 5 vars (`DJANGO_SETTINGS_MODULE`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DATABASE_URL`, `DJANGO_ALLOWED_HOSTS`). Note that base settings read `.env` if present, else real env vars (CI/prod path).
- **First run**: `uv sync`; `migrate`; `init_platform` (mints the first Platform Admin — credentials via `INIT_ADMIN_USERNAME/EMAIL/PASSWORD` env or interactive prompt; it also runs `setup_roles` and creates the Institution singleton). Optional `seed_demo_course` for a demo course + enrolled student. `runserver` and log in at `/`.
- **Running tests**: `uv run pytest` (unit/integration, e2e excluded by default via `addopts -m 'not e2e'`); e2e = `uv run playwright install chromium` then `uv run pytest -m e2e`.
- **Gotchas**: link `docs/local-development.md` for the Site-domain emailed-link fix (needed before invitations/password-reset links work locally) and notification purge.
- Every command sequence mirrors `.github/workflows/ci.yml` (the source of truth) and is verified live at build time.

### docs/development/architecture.md
- **One-liner per app** (9 apps): `core` (UI shell, tokens/theme/i18n middleware, help system, site config), `accounts` (auth via allauth, SSO/OIDC, invitations, bootstrap), `institution` (singleton branding + platform settings + RBAC role groups), `courses` (content model, authoring/builder, quiz engine + 9 question types, analytics, exports), `grouping` (cohorts / groups / collections + enrollment), `notes` (personal lesson notes), `tags` (personal unit tags), `notifications` (events + email + bell), `integrations` (SIS grade-sync webhook).
- **The core content model** (the one non-obvious pattern): `ContentNode` self-FK tree (`part < chapter < section < unit`, one `OrderField` space per parent) + `Element` GFK join-row pointing at concrete per-type element models (educa pattern). One paragraph + a small diagram sketch in text.
- **Settings layout**: `config/settings/{base,local,test,production}.py`; `DJANGO_SETTINGS_MODULE` selects; test pins non-manifest static + LocMemCache.
- **Request/consumption flow** (brief): outline → lesson/quiz unit views → progress (`UnitProgress` seen-elements). Where templates (`templates/`, per-app) and static (`core/static/`, vendored KaTeX/MathLive) live.
- **Historical context**: link `docs/planning/{main_idea,roles,views,differences}.md` and `docs/roadmap.md` as the original vision (may be stale; code is authoritative).

### docs/development/conventions.md
- **Code style**: `uv run ruff check .` **and** `uv run ruff format --check .` — both are required and CI runs both (a recurring trap: running only `ruff check`). Rule set `E,F,I,UP,B,S`; isort `force-single-line`; imports top-of-file (E402 is active and not auto-fixable).
- **Testing**: pytest + `pytest-django`; settings `config.settings.test`; use `tests.factories` and `tests.factories.TEST_PASSWORD` — never hardcode passwords (GitGuardian flags literals). Role factories `make_pa/make_ca/make_teacher/make_student`. The `e2e` marker (browser tests, excluded by default).
- **i18n**: EN/PL; `uv run python manage.py makemessages`/`compilemessages`; the fuzzy-match gotcha (new strings fuzzy-matched to unrelated old ones → clear the fuzzy flag); module-level translatable dicts need `gettext_lazy`, not `gettext`; the project forbids obsolete `#~` catalog entries.
- **Content model**: how to add a new element/question type (concrete per-type model + register with the `Element` GFK; quiz types subclass `QuestionElement`).
- **Migrations & settings**: `uv run python manage.py makemigrations --check` must be clean; `manage.py check` clean; split-settings layout.
- Keep each rule to a couple of lines with the "why"; cross-reference the memory-note learnings without duplicating them.

## Non-goals
- No `.pl.md` translations of dev docs.
- No spec/plan/superpowers meta-process documentation (out of scope per decision 4).
- No changes to runtime code, templates, or the app itself.
- Not exhaustively documenting every model/view — the app-map is a map, not an API reference.
- `.env.example` expansion and docstring gaps are **slice 4**, not here (setup.md documents the existing 5 vars only).

## Verification
- Run the full setup sequence (or verify each command against the real project) and fix any drift before shipping.
- `uv run ruff format --check .` clean (Markdown isn't linted, but keep the working tree clean).
- Confirm all intra-doc relative links resolve and the moved planning files are referenced from their new path.
- Sanity-check that `git mv` of the four root notes didn't leave a dangling reference elsewhere in the repo.

## Process
Direct write on branch `docs/dev-onboarding` → live command verification → one PR. No subagent-driven build.
