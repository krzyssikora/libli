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
- A small service `mark_onboarded()` (in `institution/services.py` or `core/services.py`) sets `Institution.load().onboarded = True` and saves. Cache invalidation is automatic: `core/apps.py` already connects `invalidate_site_config` to `Institution` `post_save` (the signal fires even with `save(update_fields=["onboarded"])`), so no explicit invalidation call is needed — `mark_onboarded()` just saves. Idempotent.

### 2. Trigger / login gate

- **Gate location: the `home` view** (`core/views.py`), which is `LOGIN_REDIRECT_URL`. On entry, if **all** of:
  1. the request user passes `request.user.has_perm("institution.change_institution")` (the SAME permission the wizard views gate on, so the redirect predicate and the view's `@permission_required` can never disagree; this also correctly includes a superuser outside the PA group, who likewise passes the view gate), AND
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

A declarative `STEPS` definition (e.g. a list of dataclasses/dicts in `institution/views_setup.py`) is the **single source for ordering, the progress indicator, and Next/Back resolution** — it carries `slug` + `label` (and a reference to the step's handler). It is **not** a uniform save abstraction: the four config steps differ too much in construction and save signature to share one "save callable" (see the per-step wiring list immediately below), so each config step has its own bespoke form-construction + save wiring in its handler. What `STEPS` unifies is navigation, not persistence.

Per-step form construction / save wiring (each differs — do not force a single interface):
- **Identity** — `BrandingForm(request.POST, request.FILES, instance=Institution.load())` (the `request.FILES` is required for the `logo` ImageField — omitting it silently drops logo uploads; **the Identity step's `<form>` must also set `enctype="multipart/form-data"`**, or `request.FILES` arrives empty regardless — the wizard owns the `<form>` tag, embedding only the extracted Identity fields include, see "Template reuse strategy" below); save via `form.save()`.
- **Access** — `AccessForm(request.POST, instance=Institution.load())`; save via `form.save()`.
- **Team** — `SendInvitationForm(request.POST)` (plain Form); on the invite submit, `create_or_refresh_invitation(email=..., role=..., invited_by=request.user)`. **Mirror the 5b `invitation_send` error handling:** wrap the call in `try/except InvitationError` (the service raises it when the email already belongs to an active or deactivated account), attach the message as a form error on `email` (`form.add_error("email", str(exc))`), and re-render the Team step without advancing — an unhandled `InvitationError` would otherwise 500.
- **SSO** — `SsoForm(request.POST, app=load_sso_app())` (and on GET, `initial=` seeded from the current row, matching the 5d settings tab); save via `save_sso_config(**form.cleaned_data, site=get_current_site(request))`.

Five indicator steps, in order:

| # | slug | label | form / action |
|---|------|-------|---------------|
| 1 | `welcome` | Welcome | none — intro + "Get started" |
| 2 | `identity` | Identity | `BrandingForm` → saves `Institution` + `BrandColor` rows |
| 3 | `access` | Access | `AccessForm` → `signup_policy` + `allowed_email_domains` |
| 4 | `team` | Team | `SendInvitationForm` + `create_or_refresh_invitation` (one invite per POST; lists outstanding/pending invitations) |
| 5 | `sso` | SSO | `SsoForm` + `save_sso_config` (incl. read-only redirect-URI block); marked **optional — can finish later on the SSO tab** |

After step 5, **Finish** completes the wizard.

- **URLs:** one route per step under `/manage/setup/`. Either a single `path("manage/setup/<slug:step>/", ...)` validated against `STEPS`, or `/manage/setup/` (welcome) + `/manage/setup/<step>/`. Bookmarkable / refresh-safe per step. **An unknown `step` slug (not in `STEPS`) redirects to `institution:setup` (the Welcome step)** — never a 500. **Whichever URL design is chosen, a kwargless `institution:setup` name MUST resolve** (a bare `/manage/setup/` → welcome route, or a default-step route) — the login gate and the unknown-slug fallback both `redirect("institution:setup")` with no `step` kwarg, so a single `<slug:step>`-only route without a kwargless alias would raise `NoReverseMatch`.
- **Per step controls** (submit intent is disambiguated by a hidden/`name`d submit value, e.g. `action=next` / `action=skip` / `action=invite` / `action=finish`, since several steps render more than one submit):
  - **Back** → GET previous step.
  - **Next** → POST `action=next`: validate the step's form → save via that step's wiring → GET next step. On validation error, re-render the same step with errors (no advance). **Exception — Team step:** its **Next** advances **without** validating or sending (an empty email field must not block advancing); only **"Invite another"** (`action=invite`) runs the form + `create_or_refresh_invitation`. Because Next already advances without saving on this step, the Team step renders **only** Next — no separate per-step Skip control (it would be redundant). **Exception — SSO step:** its primary button is **Finish** (`action=finish`), not Next — see §6.
  - **Skip** (per-step, `action=skip`) → GET next step **without saving** (data already persists from prior visits or stays at defaults). **On the last step (SSO), per-step Skip is equivalent to Finish-without-saving:** it runs `mark_onboarded()` and redirects to `home` (otherwise skipping the final step would leave `onboarded=False` and re-nag the PA forever).
- **Welcome** has no form — intro text + a "Get started" button to step 2.
- **Progress indicator** renders all five steps with the current one highlighted and prior ones marked complete, derived from `STEPS` + current slug. "Step N of 5" label.

### 5. Persistence model (save-as-you-go)

Each config step writes the **real** models immediately on Next (there is no end-of-wizard commit and no separate draft/wizard-state storage):
- GET seeds the step's form from current values (`Institution` / `BrandColor` / `SocialApp`), so re-entering or resuming the wizard always reflects the live state.
- POST runs the existing form's full validation and the existing save path (same code as the standalone settings tab), then advances.
- The **Team** step is additive: each `action=invite` POST sends one invitation via the 5b service (which also fires the existing on-commit invitation email signal) and re-renders the step with "Invite another" and "Next". The step lists **pending invitations** — those not yet accepted and not yet expired, ordered newest-first — so the PA sees what's outstanding (not the entire historical invite log). **`Invitation.status` is a `@property`, not a DB field, so `.filter(status="pending")` raises `FieldError`;** the queryset must use the field predicate `accepted_at__isnull=True, expires_at__gt=timezone.now()` (the same condition as the existing `Invitation.find_pending` precedent). Test guidance: assert the freshly-sent invite appears in the list, and that an accepted invite (`accepted_at` set) and an expired invite (`expires_at` in the past) do not.
- **Domain-allowlist warning:** the 5b domain-mismatch `messages.warning` lives in the `invitation_send` *view*, not in `create_or_refresh_invitation`. The wizard Team step **must replicate that warning** (compute it the same way `invitation_send` does), because the Access step immediately prior may have just set the allowlist — inviting an out-of-allowlist address here should warn, not silently differ from the People tab.

### 6. Completion & re-launch

- **Finish** (`action=finish`, on the SSO step) **first persists the SSO form, then completes onboarding:**
  1. Validate `SsoForm`; on validation error, re-render the SSO step with errors and do **not** onboard.
  2. On valid, call `save_sso_config(**form.cleaned_data, site=get_current_site(request))` — this no-ops (returns `None`) on the all-blank/disabled input documented in 5d, so a PA who skips SSO and just clicks Finish persists nothing and is not blocked.
  3. Then `mark_onboarded()` → clear `request.session["setup_skipped"]` (no longer needed) → `redirect("home")` with `messages.success(...)` ("Your platform is set up. You can revisit setup anytime from Settings.").
  (Per-step **Skip** on the SSO step, by contrast, runs steps 3 only — it does not save the SSO form. See §4.)
- **Re-launchable later:** a "Setup wizard" link in the manage area (settings index and/or the manage dashboard) re-enters the wizard at Welcome **even when `onboarded=True`**. Finishing again simply re-runs `mark_onboarded()` (idempotent). Re-running never resets `onboarded` to `False`.

### 7. Permissions & gating

- All wizard views: `@login_required` + `@permission_required("institution.change_institution", raise_exception=True)` (identical to the settings tabs; the PA group holds it). The Team-step invite POST additionally falls under `accounts.add_user`, which the PA group holds — gate the invite action accordingly (matching the 5b `invitation_send` view).
- Non-PA users hitting any `/manage/setup/` URL → 403 (raise_exception). The `home` gate only ever redirects PAs, so non-PAs never reach the wizard by redirect.

---

## File Structure (anticipated)

- **Modify** `institution/models.py` — add `onboarded` field.
- **Create** migration `institution/migrations/0006_*.py` — add the field, default `False`. **Note on already-configured installs:** an existing deployment (configured via the settings tabs before 5e) gets `onboarded=False` and will be redirected into the wizard on the PA's next login. This is acceptable for a fresh-install-focused feature — the PA clicks through (or Skips, or Finishes once) and is never bothered again. A data migration that backfills `onboarded=True` for rows that already deviate from placeholder defaults (e.g. `name != "My Institution"` or `BrandColor` rows exist) is an OPTIONAL nicety, not required; if added, keep it in this same migration.
- **Modify** `core/services.py` — `onboarded` in `_DEFAULTS` + `_build()`; add `mark_onboarded()` (or place in `institution/services.py`).
- **Modify** `core/views.py` — `home` login gate (PA + not onboarded + not skipped → redirect to wizard).
- **Create** `institution/views_setup.py` — the `STEPS` definition + the stepped wizard views (welcome / per-step GET+POST / finish / skip).
- **Modify** `institution/urls.py` — wizard routes (`institution:setup` + per-step).
- **Refactor (prerequisite for reuse)** the existing settings tab templates `_branding_tab.html` / `_access_tab.html` / `_sso_tab.html` — extract their **fields-only** bodies into includes (`_branding_fields.html` / `_access_fields.html` / `_sso_fields.html`) and re-point the existing settings tabs at them. See "Template reuse strategy" below — this is required, not optional.
- **Create** `templates/institution/setup/` — `_wizard.html` (frame + progress indicator), `welcome.html`, and per-step templates (`identity.html`, `access.html`, `team.html`, `sso.html`). Each wizard step owns its own `<form>` (with the wizard's `action`/csrf/submit and the `action=` disambiguation) and embeds the matching extracted fields include.
- **Modify** the manage area (settings index / manage dashboard template) — "Setup wizard" re-launch link.
- **Create/Modify** wizard CSS (progress indicator + step frame) — extend `institution/static/institution/settings.css` or a small `setup.css`.
- **Create** `tests/test_setup_wizard.py` — gate, per-step save round-trips, skip semantics, finish flips flag, re-launch, non-PA 403.
- **Create** `tests/test_e2e_setup_5e.py` — one Playwright e2e driving the real stepped flow Welcome→…→Finish, then asserting `home` no longer redirects.
- **Modify** `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`) — PL translations for all new strings.

---

## Template reuse strategy

**The existing settings tab partials are full `<form>` elements, not reusable fragments.** `_branding_tab.html`, `_access_tab.html`, and `_sso_tab.html` each open with their own `<form class="settings__form" method="post" action="{% url 'institution:settings_branding'/'…_access'/'…_sso' %}">`, render their own `{% csrf_token %}`, and end with their own submit button. They **cannot** be `{% include %}`d inside the wizard's `<form>`:
- Embedding them produces **invalid nested `<form>`s**.
- Using them standalone makes their submit **POST to the settings endpoint** (`institution:settings_branding/_access/_sso`), so the wizard's Next/Back/Skip/Finish and the `action=` disambiguation never fire and the flow breaks.

**Required refactor:** extract each tab's fields-only body into an include (`_branding_fields.html` / `_access_fields.html` / `_sso_fields.html`) containing just the labelled field markup (no `<form>`, no csrf, no submit), and re-point the existing settings tabs to `{% include %}` that fields partial inside their current `<form>`. The wizard steps then include the same fields partials inside the wizard's own `<form>`. Both surfaces stay DRY and keep their own form/csrf/submit. This is behaviour-preserving for the settings tabs (verify their tests stay green) and is a prerequisite task, sequenced before the wizard step templates.

**Two reuse gotchas to carry into the extraction:**
- **Branding live-preview JS:** `_branding_tab.html` includes an inline `<script>` (live name/colour preview + logo-file mirroring) that binds to `document.querySelector(".settings__form")` and the logo widget's `data-logo-*` hooks. Decide whether the Identity step keeps that preview; if it does, the Identity step's `<form>` must retain the `settings__form` class (and the logo widget hooks), and the script should live in the shared fields partial (or be re-included) so it isn't silently dropped.
- **SSO context keys:** the SSO fields partial still needs the context keys `sso` (the form), `sso_secret_saved`, and `sso_redirect_uri`; the wizard SSO view must build them exactly as the 5d `_settings_context` does.

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
