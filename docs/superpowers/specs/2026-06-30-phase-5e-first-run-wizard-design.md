# Phase 5e — First-Run Setup Wizard — Design

**Date:** 2026-06-30
**Branch:** `phase-5e-first-run-wizard` (off master @ dd7e896 — Phases 5b/5c/5d all merged)
**Status:** Design approved; spec written.

## Goal

Guide a freshly-bootstrapped Platform Admin (PA) through the essential platform configuration in a sequenced, stepped wizard the first time they sign in, then stop nagging once setup is finished. The wizard orchestrates configuration surfaces that already exist as standalone settings tabs (Branding, Access, SSO) plus the user-invite flow into one guided first-run experience, so a fresh install gets configured instead of silently running on placeholder defaults ("My Institution", no branding, invite-only with no domains).

**The wizard does NOT create the first admin.** A fresh deploy's first PA is already created out-of-band by the `init_platform` management command (env vars → `create_superuser` + `PLATFORM_ADMIN` group + `setup_roles` + `Institution.load()`). The wizard begins after that PA logs in.

## Dependencies

The wizard **reuses existing forms/services** rather than duplicating them — all are now on master:
- `BrandingForm` (Phase 5c)
- `AccessForm` (Phase 5c)
- `SendInvitationForm` + `create_or_refresh_invitation` (Phase 5b)
- `SsoForm` + `save_sso_config` (Phase 5d — merged to master via PR #58)

This branch is cut from master (`dd7e896`, which includes the 5d merge), so 5e is a normal (non-stacked) PR. The SSO step depends on the 5d code now present on master.

## Tech Stack

Django 5.2.15, django-allauth 65.18.0, pytest + pytest-django, Playwright (e2e), gettext (EN/PL). Bespoke token-driven CSS (cream/teal/terracotta), server-rendered templates — no Bootstrap/React.

---

## Architecture

### 1. The `onboarded` flag

- Add `onboarded = models.BooleanField(default=False)` to `Institution` (`institution/models.py`). Single migration (`institution/0006_institution_onboarded` or next number).
- Surface `onboarded` in the cached `get_site_config()` bundle (`core/services.py` — add to `_DEFAULTS` as `False` and to `_build()` from the instance) so the login gate reads it cache-cheaply and the absent-row case defaults to `False` (un-onboarded).
- A small service `mark_onboarded()` (in `institution/services.py` or `core/services.py`) sets `Institution.load().onboarded = True`, saves, and invalidates the site-config cache (reuse the existing Institution cache-invalidation hook). Idempotent.

### 2. Trigger / login gate

- **Gate location: the `home` view** (`core/views.py`), which is `LOGIN_REDIRECT_URL`. On entry, if **all** of:
  1. the request user is a Platform Admin (reuse the existing `is_platform_admin` determination — group membership / the `user_roles` context predicate), AND
  2. `get_site_config()["onboarded"]` is `False`, AND
  3. the session does not carry the skip flag `request.session.get("setup_skipped")`,
  then `redirect("institution:setup")` (the wizard's first step).
- This catches every post-login landing (home is the default authenticated destination) **without global middleware**, which was considered and rejected: middleware risks redirect loops and adds a per-request cost on every path. Gating at `home` is sufficient for "the PA can't miss setup on login" and is loop-safe (the wizard is not `home`).
- **Non-PAs are never redirected** (condition 1). Students/teachers are unaffected.
- **Idempotent for onboarded installs:** once `onboarded=True`, condition 2 fails and `home` renders normally forever.

### 3. "Skip setup for now" (whole-wizard escape)

- Every wizard step renders a subtle **"Skip setup for now"** control (distinct from the per-step "Skip"). It sets `request.session["setup_skipped"] = True` and redirects to `home`.
- The login gate honors `setup_skipped`, so the PA is not bounced again **this session**. A new session (next login) clears the session flag → the gate redirects again, until `onboarded` is flipped. This realizes the approved "auto-redirect until done, with a per-session skip-escape" behaviour.

### 4. Steps & navigation (stepped pages)

A declarative `STEPS` definition (e.g. a list of dataclasses/dicts in `institution/views_setup.py`) is the **single source** for ordering, the progress indicator, and Next/Back resolution. Each entry: `slug`, `label`, and (for config steps) the bound form class + a save callable.

Five indicator steps, in order:

| # | slug | label | form / action |
|---|------|-------|---------------|
| 1 | `welcome` | Welcome | none — intro + "Get started" |
| 2 | `identity` | Identity | `BrandingForm` → saves `Institution` + `BrandColor` rows |
| 3 | `access` | Access | `AccessForm` → `signup_policy` + `allowed_email_domains` |
| 4 | `team` | Team | `SendInvitationForm` + `create_or_refresh_invitation` (one invite per POST; lists invites sent so far) |
| 5 | `sso` | SSO | `SsoForm` + `save_sso_config` (incl. read-only redirect-URI block); marked **optional — can finish later on the SSO tab** |

After step 5, **Finish** completes the wizard.

- **URLs:** one route per step under `/manage/setup/`. Either a single `path("manage/setup/<slug:step>/", ...)` validated against `STEPS`, or `/manage/setup/` (welcome) + `/manage/setup/<step>/`. Bookmarkable / refresh-safe per step.
- **Per step controls:**
  - **Back** → GET previous step.
  - **Next** → POST: validate the step's form → save via the reused form/service → GET next step. The SSO step's primary button is **Finish** instead of Next.
  - **Skip** (per-step) → GET next step **without saving** (data already persists from prior visits or stays at defaults).
- **Welcome** has no form — intro text + a "Get started" button to step 2.
- **Progress indicator** renders all five steps with the current one highlighted and prior ones marked complete, derived from `STEPS` + current slug. "Step N of 5" label.

### 5. Persistence model (save-as-you-go)

Each config step writes the **real** models immediately on Next (there is no end-of-wizard commit and no separate draft/wizard-state storage):
- GET seeds the step's form from current values (`Institution` / `BrandColor` / `SocialApp`), so re-entering or resuming the wizard always reflects the live state.
- POST runs the existing form's full validation and the existing save path (same code as the standalone settings tab), then advances.
- The **Team** step is additive: each POST sends one invitation via the 5b service (which also fires the existing on-commit invitation email signal) and re-renders the step showing invitations sent, with "Invite another" and "Next".

### 6. Completion & re-launch

- **Finish** (on the SSO step) → `mark_onboarded()` (sets `onboarded=True`, invalidates cache) → clears `request.session["setup_skipped"]` (no longer needed) → `redirect("home")` with `messages.success(...)` ("Your platform is set up. You can revisit setup anytime from Settings.").
- **Re-launchable later:** a "Setup wizard" link in the manage area (settings index and/or the manage dashboard) re-enters the wizard at Welcome **even when `onboarded=True`**. Finishing again simply re-runs `mark_onboarded()` (idempotent). Re-running never resets `onboarded` to `False`.

### 7. Permissions & gating

- All wizard views: `@login_required` + `@permission_required("institution.change_institution", raise_exception=True)` (identical to the settings tabs; the PA group holds it). The Team-step invite POST additionally falls under `accounts.add_user`, which the PA group holds — gate the invite action accordingly (matching the 5b `invitation_send` view).
- Non-PA users hitting any `/manage/setup/` URL → 403 (raise_exception). The `home` gate only ever redirects PAs, so non-PAs never reach the wizard by redirect.

---

## File Structure (anticipated)

- **Modify** `institution/models.py` — add `onboarded` field.
- **Create** migration `institution/migrations/0006_*.py` — add the field (no data backfill needed; default `False`).
- **Modify** `core/services.py` — `onboarded` in `_DEFAULTS` + `_build()`; add `mark_onboarded()` (or place in `institution/services.py`).
- **Modify** `core/views.py` — `home` login gate (PA + not onboarded + not skipped → redirect to wizard).
- **Create** `institution/views_setup.py` — the `STEPS` definition + the stepped wizard views (welcome / per-step GET+POST / finish / skip).
- **Modify** `institution/urls.py` — wizard routes (`institution:setup` + per-step).
- **Create** `templates/institution/setup/` — `_wizard.html` (frame + progress indicator), `welcome.html`, and per-step templates (`identity.html`, `access.html`, `team.html`, `sso.html`), reusing the existing settings tab partials (`_branding_tab`-style field markup, `_sso_tab.html`) where it keeps markup DRY.
- **Modify** the manage area (settings index / manage dashboard template) — "Setup wizard" re-launch link.
- **Create/Modify** wizard CSS (progress indicator + step frame) — extend `institution/static/institution/settings.css` or a small `setup.css`.
- **Create** `tests/test_setup_wizard.py` — gate, per-step save round-trips, skip semantics, finish flips flag, re-launch, non-PA 403.
- **Create** `tests/test_e2e_setup_5e.py` — one Playwright e2e driving the real stepped flow Welcome→…→Finish, then asserting `home` no longer redirects.
- **Modify** `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`) — PL translations for all new strings.

---

## Global Constraints

- **Single migration, additive only.** One boolean field, default `False`; `makemigrations --check --dry-run` clean afterward.
- **Reuse, don't duplicate.** Wizard steps embed the existing `BrandingForm` / `AccessForm` / `SsoForm` / invite flow + their save paths. No re-implemented validation.
- **Save-as-you-go.** No end-of-wizard commit; no separate wizard-state model. Each step persists the real models on Next.
- **Gate at `home`, not middleware.** Loop-safe; PA-only; honors the per-session skip flag.
- **Tooling:** system `python`/`ruff`/`pytest` NOT on PATH — always `uv run …`. `uv run ruff format .` before every commit; `ruff check` enforces ≤88 cols (E501).
- **i18n:** all user-facing strings translatable; module-level form labels via `gettext_lazy`. Add PL catalog entries, clear `#, fuzzy`, keep catalog clean (0 fuzzy / 0 `#~` obsolete — project catalog-clean tests enforce this), compile `.mo`.
- **No hard-coded test passwords:** use `tests.factories.TEST_PASSWORD` / `make_pa` / `make_login`.
- **Every view ships styled** and is verified light/dark/mobile via throwaway Playwright screenshots before the relevant task closes.
- **Windows Edit-tool footgun:** the Edit tool has repeatedly converted ASCII quotes to curly U+201C/U+201D inside Python/`.po` literals → syntax/`msgfmt` errors. Run `uv run ruff check` after string-literal edits and confirm `compilemessages` exits 0.

---

## Out of Scope (YAGNI)

- **Uploads tab as a wizard step** — sensible ceiling defaults already exist; too in-the-weeds for first-run. Remains on its settings tab.
- **Bulk multi-email invite box** — the Team step reuses the one-at-a-time 5b invite flow ("Invite another" loop), not a new bulk parser.
- **Global onboarding middleware** — rejected for redirect-loop risk and per-request cost; the `home` gate suffices.
- **A separate wizard-state/draft model** — unnecessary because steps save real data as you go.
- **Creating the first admin in-browser** — handled out-of-band by `init_platform`.

## Open Questions

None at design time. (The login-gate-at-`home` and one-at-a-time invite decisions were confirmed with the user during brainstorming.)
