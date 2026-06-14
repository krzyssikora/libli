# Phase 0d‑2 — Surfaces: Design Spec

*Spec date: 2026-06-14. Second half of Phase 0d (the first, "foundation", shipped as
[Phase 0d‑1](2026-06-14-phase-0d1-ui-foundation-design.md), PR #4 → master). Refines
[Phase 0 foundations](2026-06-13-phase-0-foundations-design.md) §7 (views). Visual direction
is already decided — the accepted mockups `landing_accepted`, `app-shell-light-dark_accepted`,
`dashboard-multirole_accepted-A`, and `auth-and-settings_accepted` (see
[docs/mockups/README.md](../../mockups/README.md)) and the
[design language](../../design-language.md).*

## Goal

Build the libli **product surfaces** on top of the 0d‑1 UI foundation: a public **landing
page**, the authenticated **dashboard shell**, a **user settings** page, a minimal
**institution settings** page, and branded **403/404/500** error pages. Add a **Playwright
E2E smoke suite** (run in CI) that proves the critical path the Django test client cannot:
land → log in → themed dashboard, theme-toggle persistence across reload, EN↔PL rendering
Polish, and no-flash on first paint.

These surfaces consume — and do not modify — the 0d‑1 shell (`templates/base.html`),
`color-mix()` theming, context processors (`institution_branding`/`ui_prefs`), the cached
`get_site_config()` accessor, and the EN/PL i18n plumbing. Where a surface needs data that
does not exist until a later phase (courses, analytics, enrollment), 0d‑2 ships the **chrome
with an empty state**, not the data feature.

## Scope split recap (0d‑1 / 0d‑2)

- **0d‑1 — Foundation (done).** CSS system, app shell, theming injection, i18n infrastructure;
  existing auth + home pages restyled.
- **0d‑2 (this spec) — Surfaces.** Landing, dashboard shell, user/institution settings, error
  pages, E2E smoke suite. No new content models; no DRF; no branding/SSO admin UIs (Phase 5).

## Success criteria (Definition of Done)

1. **Landing** renders at `/` for anonymous visitors inside the shell's anonymous variant
   (brand, EN/PL switch, theme toggle, log-in + conditional SSO + invite-code CTAs). An
   **authenticated** request to `/` redirects (302) to `/home/`.
2. **Dashboard** (`/home/`, `@login_required`) renders a **role-aware section scaffold** with
   friendly empty states; sections are gated by the user's role Groups / permissions. No
   collapse/reorder/persistence (deferred to Phase 1).
3. **User settings** (`/settings/`, `@login_required`) edits `theme`, `language` (constrained
   to `enabled_languages`), and `display_name`; **username is read-only**; a "Change password"
   link routes to allauth's (already-styled) page. Saving persists the fields and re-syncs the
   active session language so the change takes effect immediately.
4. **Institution settings** (`/settings/institution/`) is gated on
   `institution.change_institution` (Platform Admin) and edits the **operational** settings
   `enabled_languages`, `default_language`, `default_theme`, `signup_policy`. Saving invalidates
   the site-config cache (existing signals). **No branding (logo/colors)** — Phase 5.
5. **403/404** extend the shell and render branded; **500** renders a **self-contained**
   branded fallback that depends on **no context processors** (Django renders 500 with an empty
   context). `handler403/404/500` are wired.
6. **Playwright E2E** smoke suite (~5–8 tests) passes locally and in CI: boot + static load,
   local login → themed shell, theme toggle flips **and persists across reload**, EN↔PL renders
   Polish, no-flash on first paint.
7. `pytest` suite green (client + E2E); `ruff` check + format clean; `manage.py check` clean;
   `makemigrations --check` clean (only the institution-settings change may add a migration —
   see below; if no model change, none expected).

---

## Architecture

No new app. All views, templates, and URLs live in the existing **`core`** app; the
institution-settings form may live in `institution` (form class) but its view/route stay in
`core` for one settings surface area.

### Routing

| Surface | Route | View (`core.views`) | Access |
|---|---|---|---|
| Landing | `/` (NEW root) | `landing` | Public; authenticated → 302 `/home/` |
| Dashboard | `/home/` (existing) | `home` (flesh out the placeholder) | `@login_required` |
| User settings | `/settings/` | `user_settings` | `@login_required` |
| Institution settings | `/settings/institution/` | `institution_settings` | perm `institution.change_institution` (raise → 403) |
| Errors | `handler403/404/500` | Django handlers + templates | n/a |

- **Root route.** `/` currently 404s (no pattern). Add `path("", views.landing, name="landing")`
  to **`config/urls.py`** *before* the existing `include("core.urls")` / `include("accounts.urls")`
  empty-prefix includes (so the exact `""` match resolves to `landing`, not a deeper include).
  Settings routes (`settings/`, `settings/institution/`) go in **`core/urls.py`** under the
  `core:` namespace (`core:user_settings`, `core:institution_settings`).
- **`name="home"` and `name="landing"` are distinct.** `LOGIN_REDIRECT_URL = "home"` is
  unchanged; the authenticated-→-home redirect on `/` reuses it.

### View responsibilities (one purpose each)

- `landing(request)` — if `request.user.is_authenticated`: `redirect("home")`. Else render
  `core/landing.html` with `hide_auth_cta=True` (the page itself carries the log-in CTA, so the
  shell's redundant header CTA is suppressed) and a flag `sso_enabled` (see below).
- `home(request)` — render `core/dashboard.html` with the viewer's role flags (below). Replaces
  the 0d‑1 placeholder body.
- `user_settings(request)` — GET renders the form bound to the current `User`; POST validates,
  saves `theme`/`language`/`display_name`, re-syncs the session language key + theme cookie,
  flashes success, redirects back (PRG).
- `institution_settings(request)` — GET/POST a `ModelForm` over `Institution.load()` limited to
  the four operational fields; POST saves (fires the cache-invalidation signal), flashes, PRG.

### RBAC gating (re-sliceable; no hardcoded role strings inline)

- **Admin section + institution settings:** gate on the **permission**
  `institution.change_institution` (already seeded to the Platform Admin group in
  `institution/roles.py`). Use `@permission_required("institution.change_institution",
  raise_exception=True)` on `institution_settings` (raises `PermissionDenied` → 403 page for
  authed-without-perm; redirects to login for anonymous).
- **Dashboard role sections:** Teacher/Course-Admin groups exist but carry **no permissions yet**
  (Phase 0 only seeds Platform-Admin perms), so dashboard *visibility* gates on **Group
  membership** using the name **constants** from `institution.roles`
  (`STUDENT`/`TEACHER`/`COURSE_ADMIN`/`PLATFORM_ADMIN`) — never inline magic strings. A small
  context helper (`core.context` or the view) computes booleans
  `is_student`/`is_teacher`/`is_course_admin`/`is_platform_admin` via
  `request.user.groups.filter(name__in=[...]).…`. This keeps the check Group-based (re-sliceable)
  per the roadmap's RBAC rule, and later phases swap each section's gate to a real permission as
  they add them.

---

## The surfaces

### Landing (`core/landing.html`)

Anonymous marketing entry, matching `landing_accepted`:

- **Shell anonymous variant** (brand, school name from `site.name`, EN/PL switch, theme toggle).
  `hide_auth_cta=True` suppresses the shell's header "Log in" link (the hero owns the CTA).
- **Hero:** eyebrow (`{{ site.name }} · learning platform`), headline, lead, and a CTA cluster:
  **Log in** (`account_login`), **Continue with SSO** (only when `sso_enabled`), and an
  invite-code link to `account_signup` / the invite flow.
- **`sso_enabled`** = an OIDC provider is configured, i.e.
  `SocialApp.objects.filter(provider="openid_connect").exists()` (allauth). When false, the SSO
  button is omitted entirely (no dead button). The provider login URL is allauth's
  `/accounts/oidc/<id>/login/` (wired in 0c‑2); the button links the configured provider.
- **Decorative hero visual:** the mockup's faux progress cards are static, **`aria-hidden`**,
  CSS-only — no data.
- **"Open courses" catalog is DEFERRED.** No `Course` model exists until Phase 1, so the section
  is **not built**: leave a single commented template hook (`{# Phase 3: open-courses teaser —
  conditional on Course.objects.filter(open=True) #}`) that renders nothing. This honours the
  mockup's "hidden entirely when there are no open courses" rule (it is always empty in 0d‑2).
- **Landing footer:** brand + school name + Privacy/Help placeholders + EN/PL marker. Static,
  shell-independent markup at the bottom of the landing template (other surfaces have no footer).

### Dashboard (`core/dashboard.html`, view `home`)

Authenticated home, scaffold from `app-shell-light-dark` + `dashboard-multirole_accepted-A`:

- A greeting (`{% blocktrans %}` with `{{ user }}`).
- **Role-aware section containers**, each rendered only when its role flag is true, each with an
  **empty state** (no data sources yet):
  - *My learning* (Student) — "No courses yet" empty state.
  - *Teaching* (Teacher) — "No classes assigned yet."
  - *Administration* (Course/Platform Admin) — links to **User settings**, **Institution
    settings** (Platform Admin only), and a note that course/branding admin arrives later.
- **No interactivity:** no collapse, no drag-reorder, no per-user layout persistence (Phase 1,
  when sections hold real, reorderable content). Sections are plain styled cards.
- A user with **no** role group still sees the greeting + a generic empty state (defensive: every
  account lands somewhere sensible).

### User settings (`core/user_settings.html`, view `user_settings`)

From `auth-and-settings_accepted` (settings card, 2.2):

- A `core.forms.UserSettingsForm` (`ModelForm` over `User`) with fields **`theme`**,
  **`language`**, **`display_name`**. `language` choices are constrained at form-init to
  `get_site_config()["enabled_languages"]` (labelled from `settings.LANGUAGES`); `theme` uses the
  model choices (light/dark/auto). **`username` is displayed read-only** (rendered as static text,
  not a form field — school-assigned).
- A **"Change password"** link → allauth's `account_change_password` (styled by the shell since
  0d‑1).
- **POST:** validate, `form.save()`, then **re-sync the active preferences** so the change is
  immediate without a re-login:
  - write the session language key (`core.middleware.LANGUAGE_SESSION_KEY` = `"_language"`) to the
    saved `User.language` (so `SessionLocaleMiddleware` activates it next request),
  - set the `libli_theme` cookie to the saved `User.theme` on the redirect response (keeps the
    anon-cookie precedence rung consistent and the pre-paint script correct on the next load).
  - Flash a success message; redirect to `core:user_settings` (PRG).
- The shell's inline theme toggle / language switch still work; this page is the **explicit**
  control surface and the two stay consistent because both write `User.theme`/`User.language`
  and the same session key + cookie.

### Institution settings (`core/institution_settings.html`, view `institution_settings`)

Minimal operational config (branding admin is Phase 5):

- `institution.forms.InstitutionSettingsForm` (`ModelForm` over `Institution`) limited to
  **`enabled_languages`**, **`default_language`**, **`default_theme`**, **`signup_policy`**.
  - `enabled_languages` — multi-select over the `settings.LANGUAGES` superset (`{en, pl}`);
    **must be non-empty**.
  - `default_language` — must be **within** the chosen `enabled_languages` (form `clean()`).
  - `default_theme` — model choices (light/dark/auto).
  - `signup_policy` — model choices (invite/open).
- **GET** binds to `Institution.load()` (the **bootstrap/admin write path** — an explicit admin
  action, so `load()`'s `get_or_create` is appropriate here, unlike the render path which uses the
  read-only cached accessor). **POST** saves → `Institution.save()` fires `post_save` →
  `invalidate_site_config` clears the cache → next render rebuilds. Flash + PRG.
- **Migration:** none expected — all four fields already exist on `Institution`. (If a field’s
  form/validators surface a model `choices`/`help_text` tweak, capture it in a named migration; do
  not change column types.)

### Error pages

- **`templates/404.html`, `templates/403.html`** — extend `base.html` (request context present →
  context processors run → branded shell). Friendly message + a link to `home`/`landing`.
- **`templates/500.html`** — **self-contained.** Django's production 500 handler renders this
  template with an **empty `Context()`**: context processors do **not** run, so it must not use
  `site.*`, `ui_prefs`, `{% url %}`, or `{% trans %}`-from-active-locale that depend on request
  state. It links the static CSS by `{% static %}` (the `static` tag needs no request context) and
  uses the **default** tokens (default warm-teal, light mode), with a plain English message and a
  hard-coded `/` link home. It deliberately does **not** extend the shell.
- **Wiring:** Django auto-discovers `403/404/500.html` at the template root with the default
  handlers; no custom `handlerNNN` is required unless we add context. Confirm `DEBUG=False`
  behaviour (the test settings already run non-debug).

---

## i18n hardening (0d‑1 follow-up, now in scope)

0d‑1's `SessionLocaleMiddleware`/seeder note a known gap: a session-pinned language is **not
re-clamped** to `enabled_languages` on every request, so disabling a language via the new
**institution settings** page would not take effect for a user who already pinned it until their
next session. 0d‑2 closes this: `LanguageSeederMiddleware` is extended so that when a `_language`
session key **is present but no longer in** `enabled_languages`, it is reset to
`default_language` (in addition to the existing absent-key seeding). The cached accessor remains
the data source (no extra DB hit). This makes "Platform Admin disables PL" take effect on the
next request for everyone. (`User.language` is **not** mutated — re-enabling restores the choice,
consistent with the 0d‑1 login-receiver fallback.)

---

## Data flow (representative)

- **Landing:** GET `/` → if authed, 302 `/home/`; else render landing (shell anon variant +
  `sso_enabled` computed from the OIDC `SocialApp` presence). No DB writes.
- **User settings save:** POST `/settings/` → form valid → `User.save()` → write `_language`
  session key + `libli_theme` cookie on the redirect → next render reflects the new theme/lang.
- **Institution settings save:** POST `/settings/institution/` (perm-gated) → `Institution.save()`
  → `post_save` → `invalidate_site_config()` → next render rebuilds the cached bundle → the seeder
  re-clamps any now-disabled pinned language.
- **500:** unhandled exception → Django renders `500.html` with empty context → standalone branded
  page (default tokens), no processors.

## Testing

pytest + pytest-django against **real PostgreSQL** (Django test client) for wiring, plus a
**Playwright** suite for the JS/no-flash critical path the client cannot observe.

### Django test client (wiring)

- **Routing/redirects:** anonymous `/` → 200 landing (anon variant, no account menu);
  authenticated `/` → 302 `/home/`; `/settings/` requires login (anon → 302 login);
  `/settings/institution/` → 403 for an authed non-PA user, 200 for a Platform-Admin-group user.
- **Landing SSO CTA visibility:** no OIDC `SocialApp` → SSO button absent; with one present →
  button present and links the provider login URL.
- **Dashboard role gating:** a Student-group user sees *My learning* and not *Administration*; a
  Platform-Admin user sees *Administration* with the institution-settings link; a no-group user
  sees the generic empty state.
- **User settings:** POST persists `theme`/`language`/`display_name`; the session `_language` key
  + `libli_theme` cookie are updated; `username` is not editable (POSTing a new username does not
  change it). A `language` outside `enabled_languages` is rejected by the form.
- **Institution settings:** POST updates the four fields; `default_language ∉ enabled_languages`
  is a form error; empty `enabled_languages` is a form error; a successful save **invalidates the
  cache** (next `get_site_config()` reflects the change).
- **i18n re-clamp:** with a session `_language="pl"` already set, disabling `pl`
  (`enabled_languages=["en"]`) makes the next request activate `en` (seeder re-clamp), **without**
  mutating any stored `User.language`.
- **Error templates:** `client.get("/does-not-exist/")` → 404 rendered from `404.html` (branded
  marker present); `403.html` rendered for the perm-denied case; **`500.html` renders standalone**
  — asserted via `django.template.loader.render_to_string("500.html")` succeeding with **no
  request/context** and **not** containing shell-only markers (proving no context-processor
  dependency).

### Playwright E2E (Python `pytest-playwright` + `live_server`)

Python toolchain (not bonnot's Node `@playwright/test`, which is a reference only) so the suite
reuses Django DB seeding and the pytest-django `live_server` fixture; `pytest-playwright` provides
`page`. Tests are marked `@pytest.mark.e2e` and **excluded from the default `pytest` run**
(`addopts = -m "not e2e"` or equivalent) so the fast unit job needs no browser; a dedicated step
runs `-m e2e`. ~5–8 tests, **critical path only:**

1. **Boot + static loads** — landing renders, `tokens.css`/`app.css`/Inter return 200 (no
   console 404s).
2. **Local login → themed shell** — seed a verified user, log in via the real form, land on the
   dashboard inside the warm-teal shell (assert a computed brand color / shell marker).
3. **Theme toggle persists** — click the toggle, assert `data-theme` flips and the `libli_theme`
   cookie / `User.theme` is written; **reload** and assert the theme survives (the 0d‑1 persist
   path, untestable by the client).
4. **EN↔PL switch renders Polish** — switch language, assert a known UI string renders in Polish
   and `<html lang="pl">`.
5. **No-flash on first paint** — assert `data-theme` is already concrete at first paint (the
   pre-paint script ran before stylesheet paint), e.g. via an `init_script`/early evaluation that
   the attribute is set before `DOMContentLoaded` styling — the structural proof the client can't
   give.

(SSO E2E is **deferred** — it needs a mock IdP; the 0c‑2 adapter is already unit-proven.)

### CI

Extend `.github/workflows/ci.yml`: after the existing fast `pytest` step, add a step (or job)
that installs Playwright browsers (`uv run playwright install --with-deps chromium`) and runs
`uv run python -m pytest -m e2e`. The Postgres service and env are already present. Browser
install is cached where the runner allows. The unit run stays browser-free via the `-m "not e2e"`
default.

## Out of scope (→ later phases)

- **Branding admin UI** (logo upload, color pickers), **SSO configuration UI**, **first-run
  wizard** — Phase 5.
- **Dashboard interactivity** (collapse/reorder, layout persistence) and **real dashboard data**
  (courses, progress, analytics) — Phase 1+/3.
- **Open-courses catalog / enrollment** — Phase 1 (Course model) / Phase 3 (enrollment).
- **`allowed_email_domains` editing** — pairs with the Phase 5 signup/SSO admin; not in the
  minimal operational form.
- Any DRF endpoints, notifications, exports, course content.
- **SSO E2E** (needs a mock IdP).

## Risks

- **500 page context-freeness.** Easy to accidentally add a `{% url %}`/`site.*` reference that
  works in dev (DEBUG technical 500) but breaks the real handler. Mitigated by the standalone
  template + the `render_to_string` no-context test.
- **Playwright flakiness / CI time.** Mitigated by a tiny critical-path-only suite, the `e2e`
  marker isolating it, and `expect`-based auto-waiting (no fixed sleeps).
- **i18n re-clamp regressions.** Extending the seeder touches every request; mitigated by the
  re-clamp test and keeping the change read-only via the cached accessor.
- **CSP (forward-looking).** Same inline pre-paint `<script>` / brand `<style>` caveat as 0d‑1; if
  a strict CSP lands later, these need nonces — flagged, not addressed here.

## Self-review

- **Spec coverage:** landing (anon shell, hero, conditional SSO, deferred catalog) ✓; dashboard
  scaffold with role gating + empty states ✓; user settings (theme/lang/display_name, read-only
  username, password link, re-sync) ✓; institution settings (4 operational fields, perm-gated,
  cache invalidation) ✓; 403/404 branded + standalone 500 ✓; i18n re-clamp hardening ✓; client +
  Playwright testing + CI ✓.
- **Decisions locked (from brainstorming):** dashboard = static scaffold + empty states;
  institution settings = operational only (branding stays Phase 5); password change = link to
  allauth; E2E = Python Playwright, wired into CI.
- **Scope check:** one coherent plan; every data-dependent feature is explicitly deferred with a
  documented hook. No new app, no schema change expected.
- **Ambiguity check:** root-route precedence, authed-→-home redirect, perm-vs-group gating, the
  500 no-context constraint, and the settings re-sync semantics are all made explicit.
