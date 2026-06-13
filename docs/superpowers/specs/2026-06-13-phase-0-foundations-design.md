# Phase 0 — Foundations: Design Spec

*Spec date: 2026-06-13. Phase 0 of the [libli roadmap](../../roadmap.md).
Companion docs: [view inventory](../../view-inventory.md), [Packt review](../../packt-review.md).*

## Goal

A fresh install boots into a branded, themed, EN/PL platform a user can log into
— locally **and** via SSO — with the custom user model, role system, institution
configuration, i18n, and base UI shell in place. **No learning content exists yet**;
that begins in Phase 1. Phase 0 is the "painful to reverse" foundation.

## Success criteria (Definition of Done)

1. Fresh database → an `init`-style management command mints the first **Platform Admin**.
2. That PA can log in with username **or** email + password.
3. With an SSO provider configured, a user can log in via SSO and be **JIT-provisioned**
   (gated by signup policy + email-domain allowlist), landing as a Student by default.
4. The UI renders **branded** (institution logo + primary/accent palette) and supports a
   per-user **light/dark/auto** theme toggle, in **EN and PL** with a language switch.
5. The post-login home is the **adaptive dashboard shell** (empty sections; fills in later phases).
6. The PA can edit institution config (name, branding, signup policy, allowed domains,
   languages) via Django admin and a minimal settings page.
7. `pytest` suite and CI are green; `ruff` clean.

---

## Stack & project layout

- **Python 3.13** (uv-managed; `uv sync` succeeds on fresh checkout). Run via `uv run python`.
- **Django 5.2 + DRF** — DRF is a declared dependency but **no API endpoints** are built in
  Phase 0 (server-rendered only).
- **PostgreSQL** (psycopg 3) in all environments; tests hit a real Postgres (no DB mocking).
- **django-allauth** for authentication (local + social/OIDC).
- **Frontend:** server-rendered Django templates + **Bootstrap 5.3** + vanilla JS (IIFE, `"use strict"`).
- **whitenoise** for static files. **ruff** lint/format. **pytest + pytest-django + factory_boy**.
- **Settings split:** `config/settings/{base,local,test,production}.py`; `base.py` loads `.env`
  via django-environ. `pyproject.toml` + `manage.py` at repo root. `STATIC_ROOT` set.

These follow the fijit-playbook baseline; libli deviates only where justified (it is **not**
deployed on the fijit droplet and may revisit vanilla-JS in later, more-interactive phases).

---

## Components

Phase 0 introduces these Django apps (names indicative):

| App | Responsibility |
|---|---|
| `accounts` | Custom user model, role/permission setup, allauth integration, auth adapters (JIT provisioning), profile/settings views. |
| `institution` | The singleton institution-config model + theming/branding mechanism + minimal settings page. |
| `core` (or `web`) | Base templates, layout shell, adaptive dashboard shell, landing page, error pages, i18n plumbing, theme toggle. |

### 1. Custom user model (`accounts.User`)

- Subclass **`AbstractUser`** (keeps Django's permission/group machinery) with:
  - `username` — **required**, unique; the stable account identifier.
  - `email` — **optional** (`blank=True`), unique when present; used for SSO linkage and
    self-service password reset.
  - `display_name` — optional human-friendly name.
  - `language` — preferred UI language (`en`/`pl`), default from institution.
  - `theme` — `light` | `dark` | `auto` (default `auto`).
- `AUTH_USER_MODEL = "accounts.User"` set **before the first migration** (non-negotiable;
  swapping later is the one mistake we must not make — see Packt review).
- Login accepts **username or email** (allauth `ACCOUNT_AUTHENTICATION_METHOD = "username_email"`).
- Three account-origin paths, one model:
  - **SSO** — username auto-derived from IdP `preferred_username`/email local-part (numeric suffix
    on collision); email from IdP; external identity (`sub`) stored via allauth's `SocialAccount`.
  - **Admin-created** — admin sets `username` (+ optional email) and password; suits emailless
    young students. (Bulk CSV import is a **later** add, not Phase 0.)
  - **Self-signup** (only when policy = open, non-SSO) — user chooses username; email required here.

### 2. Roles & permissions (RBAC substrate)

- The four roles — **Student, Teacher, Course Admin, Platform Admin** — are Django **Groups**,
  created/seeded by a data migration (or idempotent `setup_roles` command).
- Authorization uses **Django model permissions** assigned to those Groups. **No code anywhere
  checks a role by string/name** (e.g. never `if user.group == "Teacher"`); checks use
  `user.has_perm(...)` or permission-required mixins. This keeps roles **re-sliceable** later
  (splitting Course Admin, adding Senior Teacher) by editing Group→permission mappings, not code.
- New users default to the **Student** group.
- Phase 0 ships only the permissions Phase 0 needs (account/institution management); later phases
  add their own permissions to the relevant Groups.

### 3. Institution config (`institution.Institution`)

- A **single-row** model (enforced singleton; e.g. fixed PK or a `django-solo`-style accessor),
  editable at **runtime** by the PA.
- Fields:
  - `name`.
  - **Branding:** `logo` (ImageField), and a palette modeled **extensibly** — a related
    `BrandColor` set (or a JSON map) **seeded with `primary` and `accent`**, so more named colors
    can be added later without a schema change. *(UI exposes only primary + accent for now.)*
  - `signup_policy` — `invite` | `open`.
  - `allowed_email_domains` — list; gates SSO JIT provisioning (empty = no domain restriction).
  - `enabled_languages` — subset of `{en, pl}`; `default_language`.
  - `default_theme` — `light` | `dark` | `auto`.
- **Secrets** (`SECRET_KEY`, DB creds, email API keys) live in `.env`, **not** this model.
- **SSO provider credentials** use allauth's own DB model (`SocialApp`), configurable via Django admin.

### 4. Authentication & SSO (django-allauth)

- Local accounts: login (username/email + password), logout, password change, password reset
  (email link; available only when the account has an email), optional email verification.
- **Signup honors `Institution.signup_policy`:**
  - `open` → self-signup view is enabled (with bot-hardening: honeypot + rate limit, per the
    fijit `open-signup-hardening` recipe).
  - `invite` → self-signup disabled; accounts arrive via invite token or admin creation.
- **SSO providers:** Google, Microsoft, generic OIDC (SAML deferred to a later add-on). Configured
  via `SocialApp` in Django admin (Phase 0); a friendly SSO config UI is Phase 5.
- **JIT provisioning** via a custom allauth **adapter**:
  - On first SSO login, allow account creation only if (a) `signup_policy` permits, or the email
    was pre-invited, **and** (b) the email domain is in `allowed_email_domains` (when set).
  - Disallowed → render the **"account not provisioned — contact your admin"** page (view 1.3),
    no account created.
  - Allowed → create user (username auto-derived, email from IdP), add to **Student** group, link `SocialAccount`.

### 5. i18n (EN/PL)

- `USE_I18N = True`, `LocaleMiddleware`, `gettext` for all UI strings; `locale/` with `en`, `pl`.
- `LANGUAGES` constrained to `Institution.enabled_languages`.
- Language switch in the nav; selection persisted to `User.language` (and session for anonymous).
- **Content translation is out of scope** here — flagged as the Phase 1 design question (whether
  course *content* is monolingual-per-course or translatable per element).

### 6. Theming & branding

- **Bootstrap 5.3 `data-bs-theme`** drives light/dark. Per-user `theme` (`light`/`dark`/`auto`);
  `auto` follows the OS via `prefers-color-scheme`. Default from `Institution.default_theme`.
- Institution palette injected as **CSS custom properties** overriding Bootstrap tokens
  (`--bs-primary`, accent, derived hovers/shades), generated for **both** light and dark.
- Logo rendered in the nav/landing; sensible fallback when unset.
- Toggle is vanilla JS (IIFE), persists via the user setting (and a cookie/localStorage for
  immediate, pre-auth application).

### 7. Views (Phase 0 surface)

Server-rendered, all responsive (mobile + desktop), all in light + dark + EN/PL:

| Ref | View | Notes |
|---|---|---|
| 1.1 | Landing | Branded public page; login/signup CTAs; SSO button(s) when configured. |
| 1.2 | Login | Username/email + password; SSO button(s). |
| 1.3 | SSO callback + "not provisioned" | Callback is mostly non-visual; the not-provisioned page is real. |
| 1.4 | Signup / accept invite | Shown only if policy permits; honors invite tokens. |
| 1.5–1.6 | Password reset request / confirm | Email-based; only for accounts with email. |
| 1.7 | Error pages | Branded 403 / 404 / 500. |
| 2.1 | Dashboard shell | Adaptive container; empty role sections now (collapsible/reorderable mechanics may stub until later phases have content). |
| 2.2 | User settings | At minimum: change password, language, theme. |
| — | Minimal institution settings | PA-only page to edit name/branding/policy/domains/languages (Django admin is the fuller surface in Phase 0). |

### 8. Initial-admin bootstrap

- A management command (e.g. `uv run python manage.py init_platform`) creates the first
  **Platform Admin** (prompts for username/email/password or reads env), ensures roles/Groups exist,
  and creates the singleton `Institution` with defaults. Idempotent where sensible.
- The guided **first-run wizard** is **Phase 5**; Phase 0 only needs this CLI path to get a PA in.

---

## Data flow (representative)

- **Local login:** form → allauth authenticates against `accounts.User` (username or email) →
  session cookie → redirect to dashboard shell.
- **SSO login:** SSO button → provider → allauth callback → custom adapter checks policy +
  domain → JIT-create-or-match → add to Student group → session → dashboard. Disallowed →
  not-provisioned page.
- **Theme/branding render:** every page reads the singleton `Institution` (cached) for palette/logo
  and the user's `theme`/`language`; CSS vars + `data-bs-theme` + `lang` set on the layout.

## Error handling

- Disallowed SSO → explicit not-provisioned page, **no** partial account.
- Password reset requested for an emailless/unknown account → generic "if an account exists…" response (no enumeration).
- Singleton `Institution` always present (created at bootstrap); templates degrade gracefully if logo/colors unset.
- Standard branded 403/404/500.

## Testing

- pytest + pytest-django against **real PostgreSQL**; `factory_boy` factories (one per model:
  `User`, `Institution`, `BrandColor`).
- Coverage focus: user model (username/email login, email optional), role/Group seeding +
  permission checks, the **JIT adapter** (allowed vs disallowed by policy/domain; collision-suffixed
  usernames), signup-policy gating (open vs invite), theme/language persistence, branded error pages.
- No mocking of the DB layer.

## Out of scope (Phase 0)

Branding/SSO/settings *rich admin UIs* (Django admin + minimal page suffice), first-run wizard,
CSV roster import, SAML, any course/learning content, DRF endpoints, notifications/exports.

## Open questions (deferred, not blocking Phase 0)

- **Content-translation strategy** — resolve at the start of Phase 1 (monolingual-per-course vs
  translatable per element).
- **Non-technical deployment/install ergonomics** — refined across Phase 0 (deploy skeleton) and
  Phase 5 (wizard); a one-command/containerized install is the likely direction.

## Risks

- **Custom user model must land before the first migration** — sequencing risk; mitigated by making
  it the very first implementation step.
- **allauth adapter complexity** — JIT + policy + domain gating is the subtle part; covered by
  focused tests for each branch.
- **Palette-in-dark-mode contrast** — auto-deriving readable dark variants from an arbitrary brand
  color is fiddly; start with primary+accent and sane derivation, accept manual tuning later.
