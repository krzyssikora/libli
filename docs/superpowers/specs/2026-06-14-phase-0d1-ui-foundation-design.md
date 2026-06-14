# Phase 0d‑1 — UI Foundation: Design Spec

*Spec date: 2026-06-14. First half of Phase 0d (the second, "surfaces", is Phase 0d‑2).
Refines [Phase 0 foundations](2026-06-13-phase-0-foundations-design.md) §5 (i18n) and §6
(theming & branding) and §7 (views). Visual direction is already decided — see
[design-language.md](../../design-language.md) and the accepted mockups in
[docs/mockups](../../mockups/README.md) (`app-shell-light-dark`, `identity-directions_V2`).*

## Goal

Stand up the libli **UI foundation**: a bespoke token-driven CSS system, the reusable
app shell (nav/brand/theme-toggle/language-switch/account-menu), the per-institution
theming-injection mechanism, and the EN/PL i18n infrastructure — then **restyle the
existing auth + home pages** into the real warm-teal identity as the end-to-end proof.
No new product surfaces are built here; the landing page, adaptive dashboard, settings
pages, and error pages are **Phase 0d‑2**, all building on this foundation.

This is the foundation layer: it is depended on by every later view, so it lands first.

## Scope split (why 0d‑1 / 0d‑2)

Phase 0d (i18n + bespoke CSS + UI shell + theming + landing/dashboard/settings + error
pages) is too large for one cycle. It is split:

- **0d‑1 (this spec) — Foundation.** CSS system, app shell, theming injection, i18n
  infrastructure; existing auth + home pages restyled. Demonstrable end-to-end (a real
  branded, themed, EN/PL login/home).
- **0d‑2 — Surfaces.** Public landing page, adaptive dashboard shell, user settings page,
  minimal institution settings page, branded 403/404/500. Each consumes 0d‑1's shell and
  components.

## Success criteria (Definition of Done)

1. The existing auth pages (login, signup, password reset request/confirm, email
   verification, logout, password change) and the home placeholder render inside the new
   **warm-teal app shell** with the bespoke component CSS.
2. A per-user **light/dark/auto** theme toggle works and persists (`User.theme` when
   authenticated, cookie otherwise), with **no flash of the wrong theme** on first paint.
3. An **EN↔PL** language switch works, persists (`User.language` when authenticated,
   session otherwise), and shows **real Polish** for the current UI strings; the active
   language set is constrained to `Institution.enabled_languages`.
4. The **institution palette** (`BrandColor` primary/accent) overrides the default warm-teal
   identity by injecting only **two raw CSS variables**; all derived shades and the dark-mode
   lift cascade from them.
5. `collectstatic` succeeds; self-hosted **Inter** and `tokens.css` are served.
6. `pytest` suite green; `ruff` check + format clean; `manage.py check` clean.

---

## Architecture

### New `core` app

A new `core` app owns the cross-cutting UI layer (the Phase 0 spec's "core/web"
component): base templates, the app shell, context processors, the CSS/JS/font static
assets, and the i18n/theme plumbing views. The placeholder `home` view relocates here
from `config/views.py` (it lived in `config/` only because 0b had no UI app yet); its
content stays a placeholder — the real adaptive dashboard is 0d‑2.

```
core/
├── apps.py
├── context_processors.py   # institution_branding (palette/logo/name) + ui_prefs (theme/lang/langs)
├── views.py                # home (relocated); set_language; set_theme
├── urls.py                 # /home/ (moved), /i18n/set-language/, /ui/set-theme/
├── templatetags/
│   └── branding.py         # inline brand-vars <style> from the cached Institution palette
└── static/core/
    ├── css/
    │   ├── tokens.css      # raw --brand-* inputs + color-mix-derived palette (light + dark)
    │   ├── reset.css       # base reset, focus rings, prefers-reduced-motion, sr-only
    │   └── app.css         # shell layout + primitive components (nav, buttons, inputs,
    │                       #   form fields, card, alerts, account menu, avatar)
    ├── js/
    │   └── ui.js           # IIFE "use strict": theme toggle, account menu, lang-switch submit
    └── fonts/inter/        # self-hosted Inter woff2 + @font-face in tokens.css (or fonts.css)
templates/
├── base.html               # rewritten: full shell, pre-paint script, asset includes, messages
├── core/home.html          # relocated placeholder, now inside the shell
└── allauth/layouts/base.html  # now extends the shell (currently a bare passthrough)
config/
├── settings/base.py        # + STATICFILES_DIRS, LocaleMiddleware, LANGUAGES, LOCALE_PATHS,
│                           #   context processors
└── urls.py                 # home route moves into core.urls; keep a thin redirect if needed
locale/
├── en/LC_MESSAGES/django.po (+ .mo)
└── pl/LC_MESSAGES/django.po (+ .mo)
```

The CSS seed source is the sibling **bonnot** app (on disk at `../bonnot/`): its base
reset, focus-ring, `prefers-reduced-motion`/`sr-only` utilities, spacing (4px grid) and
motion scales, and primitive component CSS are adapted to libli's tokens. We do **not**
adopt React/Vite — CSS only.

### Cached institution accessor

Theming and branding read the singleton `Institution` (+ its `BrandColor` set) on **every**
render. To avoid a per-request DB hit, reads go through a **cached accessor** (e.g.
`Institution.load()` already exists; add a small cache around the resolved palette/logo/name
or cache the colors map). The cache is **invalidated on `Institution`/`BrandColor` save**
(via `post_save`/`post_delete` signals). Templates degrade gracefully when logo/colors are
unset (fall back to defaults).

---

## CSS system & theming (approach A: `color-mix()` from raw brand vars)

### Token derivation

`tokens.css` defines **two raw inputs** and derives everything from them:

```css
:root {
  /* raw institution-overridable inputs (defaults = libli warm teal / amber) */
  --brand-primary: #147E78;
  --brand-accent:  #C77B2A;

  /* derived — light mode */
  --primary:        var(--brand-primary);
  --primary-hover:  color-mix(in srgb, var(--brand-primary) 88%, black);
  --primary-active: color-mix(in srgb, var(--brand-primary) 78%, black);
  --primary-subtle: color-mix(in srgb, var(--brand-primary) 16%, var(--surface-raised));
  --accent:         var(--brand-accent);
  --accent-hover:   color-mix(in srgb, var(--brand-accent) 88%, black);
  --accent-subtle:  color-mix(in srgb, var(--brand-accent) 18%, var(--surface-raised));

  /* surfaces, text, borders, semantic, radii, shadow, spacing, typography:
     literal values straight from design-language.md (+ bonnot scales) */
}

[data-theme="dark"] {
  /* dark surfaces/text/borders/semantic per design-language.md, plus the brand lift */
  --primary:        color-mix(in srgb, var(--brand-primary) 68%, white);
  --primary-hover:  color-mix(in srgb, var(--brand-primary) 78%, white);
  --primary-active: color-mix(in srgb, var(--brand-primary) 88%, white);
  --primary-subtle: color-mix(in srgb, var(--brand-primary) 24%, var(--surface-raised));
  --accent:         color-mix(in srgb, var(--brand-accent) 70%, white);
  /* ... */
}
```

The exact mix percentages are **tuned so the default brand reproduces the hand-picked
light/dark values in `design-language.md` closely** (e.g. dark `--primary` ≈ `#4FB3AC`,
dark `--accent` ≈ `#E5A159`). For an arbitrary institution color the same mixes produce a
sensible (approximate) light/dark family — the Phase 0 spec already accepts manual tuning
of dark derivation later; this is the documented, tolerated approximation.

`color-mix()` is supported in all current evergreen browsers (Chrome/Edge/Firefox/Safari,
2023+), which is acceptable for this audience.

### Per-institution injection

- A `core` context processor (`institution_branding`) exposes the cached institution
  name/logo (for the nav) and palette.
- `base.html` calls a `core` **`branding` template tag** that renders a **minimal inline
  `<style>`** in `<head>` setting only `--brand-primary`/`--brand-accent` — and only when
  the institution's stored colors differ from the defaults (nothing emitted when they
  match). All shades cascade via the `color-mix()` rules above. (The conditional-emit logic
  lives in the tag rather than template `{% if %}` soup.) This keeps the "a school re-themes
  by editing two colors" contract literally true and the per-request inline CSS to ~2 lines.

### Theme attribute & no-flash

- `data-theme` on `<html>` drives light/dark. The server renders the **stored preference**
  source-of-truth: `User.theme` when authenticated, else the `libli_theme` cookie, else
  `Institution.default_theme`.
- A tiny **pre-paint inline script** in `<head>` (before stylesheet links) resolves `auto`
  → `prefers-color-scheme` and sets the effective `data-theme="light|dark"` before paint,
  eliminating FOUC. It reads the same cookie so anonymous/first-load is correct.
- **Inter** is self-hosted (`@font-face`, woff2) — no Google Fonts dependency in production.
- whitenoise is already configured; add `STATICFILES_DIRS` so `core/static` is collected
  (`STATIC_ROOT`/`CompressedManifestStaticFilesStorage` already set).

---

## UI shell (`base.html`)

Rewritten from the current barebones stub into the reusable chrome from the accepted
`app-shell-light-dark` mockup:

- **Top bar:** the `libli` wordmark + bold **amber dot** (`libli.`, links to home);
  institution **logo** when set (graceful fallback when unset); a right cluster with the
  **language switch** (EN/PL), **theme toggle** (cycles light → dark → auto), and an
  **account menu** (avatar/initials → settings [0d‑2], logout). Authenticated vs anonymous
  variants: anonymous shows log-in / sign-up CTAs instead of the account menu.
- **Layout:** responsive single-column shell with a max-width content container; the nav
  collapses to a compact menu on narrow viewports. Template blocks: `head_title`,
  `content`, and `extra_css` / `extra_js` hooks for later pages.
- **Django messages** rendered as styled alerts (success / warning / danger / info) using
  the semantic tokens.
- **JS** — one vanilla IIFE (`ui.js`, `"use strict"`): theme toggle (updates `data-theme`
  + cookie immediately, then fire-and-forget POST to `set_theme` to persist `User.theme`
  when authenticated), account-menu open/close (with outside-click + Escape), and
  language-switch form submit. **Progressive enhancement:** the language switch is a real
  POST `<form>` that works without JS; the theme toggle degrades to its server-rendered
  state.

---

## i18n infrastructure (EN/PL)

- **Settings:** `USE_I18N` is already `True`. Add `django.middleware.locale.LocaleMiddleware`
  (after `SessionMiddleware`, before `CommonMiddleware`), `LOCALE_PATHS = [BASE_DIR / "locale"]`,
  and a `LANGUAGES = [("en", _("English")), ("pl", _("Polski"))]` supported set.
- **Active-language constraint:** the language switch only offers languages in
  `Institution.enabled_languages`; the effective default falls back to
  `Institution.default_language`. (`LANGUAGES` is the superset libli supports; the
  institution narrows it at runtime.)
- **Strings:** mark all current UI strings (shell nav, auth pages, account/settings labels,
  flash messages) with `{% trans %}` / `{% blocktrans %}` in templates and `gettext` in
  Python. Generate `locale/en` + `locale/pl`, write **real Polish** translations, and
  compile `.mo`.
- **Switch view:** a small `core` `set_language` **POST** view activates the chosen
  language, stores it in the session (`django.utils.translation.activate` + session key),
  and — when authenticated — saves `User.language`. On login the user's stored language is
  activated (a `user_logged_in` receiver or middleware reading `User.language`). Anonymous
  selection persists in the session.
- **`lang` attribute** on `<html>` reflects the active language for accessibility.

### Theme/language write endpoints vs the settings page

`set_theme` and `set_language` are tiny POST views in `core` — the **inline write path** for
the shell's toggle/switch. The full **user settings page** (explicit theme/language radios,
password change, display name) is **0d‑2**. 0d‑1 ships the inline toggles + endpoints, not a
settings page.

---

## Restyling the existing pages (the proof)

- **allauth pages** (login, signup, password reset request/confirm, email verification,
  logout, password change): styled by making `templates/allauth/layouts/base.html` extend
  the new shell and letting `app.css` style allauth's rendered form fields/buttons globally.
  Thin overrides of individual allauth element templates only where a class hook is genuinely
  needed — kept minimal to avoid drift against allauth's bundled templates.
- **accounts pages** (`accept_invite`, `invite_invalid`, `sso_not_provisioned`): already
  extend `base.html`, so they inherit the shell + styling automatically; light markup tweaks
  (card wrapper) to match the accepted mockup.
- **home** (`core/home.html`): relocated into the shell, still placeholder content.

The public **landing page** (site root) is **not** in 0d‑1 — it is a 0d‑2 surface; 0d‑1
leaves the root route as-is.

---

## Data flow (representative)

- **Theme/branding render:** every page → context processors read the cached `Institution`
  (palette/logo/name) and the user's `theme`/`language` → `base.html` sets `lang` and the
  stored `data-theme`, emits the (conditional) inline brand-vars `<style>`, and the pre-paint
  script resolves `auto` before first paint → `tokens.css` derives the full palette via
  `color-mix()`.
- **Theme toggle:** click → `ui.js` flips `data-theme` + cookie instantly → fire-and-forget
  POST `set_theme` persists `User.theme` (if authed).
- **Language switch:** POST `set_language` → activate + session + (`User.language` if authed)
  → redirect back; next render is in the new language.

## Error handling

- Missing institution logo/colors → graceful fallback to the default identity (no inline
  override emitted when colors equal defaults).
- `set_theme`/`set_language` with an invalid/disabled value → ignored (no-op), current
  preference preserved; anonymous writes persist to cookie/session only.
- `LANGUAGES` superset always present; a value outside `Institution.enabled_languages` is not
  offered and rejected by the switch view.

## Testing

pytest + pytest-django against **real PostgreSQL**; Django test client renders pages. We
test the **wiring**, not pixels:

- Context processors inject institution palette/logo/name + UI theme/lang; the cached
  accessor invalidates on `Institution`/`BrandColor` save.
- Brand override: a non-default `BrandColor` causes the inline `--brand-primary`/
  `--brand-accent` to be emitted; defaults emit none.
- `LocaleMiddleware` active; `LANGUAGES` constrained to `Institution.enabled_languages`;
  `set_language` persists to `User.language` (authed) + session (anon); login activates the
  stored language; a known UI string renders in **Polish** when `pl` is active.
- `set_theme` persists `User.theme` (authed) + cookie (anon); the pre-paint script is present
  in `<head>`.
- Existing pages (login, home, accept-invite, sso-not-provisioned) return 200 and extend the
  shell (brand/nav markers present) under both `data-theme` states.
- `collectstatic` succeeds; Inter + `tokens.css` are collected/served.

No DB mocking; no assertions on visual CSS values (only on the presence/contract of injected
vars and attributes).

## Out of scope (→ 0d‑2 and later)

- Public **landing page**, adaptive **dashboard shell**, **user settings page**, minimal
  **institution settings page**, branded **403/404/500** error pages — all 0d‑2.
- Rich branding/SSO/settings admin UIs and the first-run wizard — Phase 5.
- Any course/learning content, DRF endpoints, notifications/exports.
- Content translation (course content) — Phase 1 question; only **UI** strings are i18n'd here.

## Risks

- **Dark-mode brand derivation** from an arbitrary institution color is approximate; mitigated
  by tuning `color-mix()` percentages against the documented default and accepting manual
  tuning later (per the Phase 0 spec's stated tolerance).
- **allauth template restyling** can drift against allauth 65.18's bundled templates; mitigated
  by styling globally via `app.css` + the shared `layouts/base.html` and overriding individual
  allauth templates only when unavoidable.
- **FOUC** if the pre-paint script regresses; covered by a test asserting the script is present
  and by keeping it inline and first in `<head>`.

---

## Self-review

- **Spec coverage:** new `core` app + file structure ✓; cached institution accessor +
  invalidation ✓; `color-mix()` token derivation from two raw vars + conditional inline
  injection ✓; `data-theme` + pre-paint no-flash + self-hosted Inter ✓; app shell
  (brand/logo/lang-switch/theme-toggle/account-menu, responsive, messages, progressive-
  enhancement JS) ✓; i18n (LocaleMiddleware/LANGUAGES/LOCALE_PATHS, enabled-languages
  constraint, real EN/PL, switch persistence) ✓; theme/lang write endpoints with the settings
  page deferred to 0d‑2 ✓; restyle of existing allauth/accounts/home pages ✓; testing of the
  wiring ✓.
- **Decisions locked:** split 0d‑1/0d‑2; `core` app; approach **A** (`color-mix()` from raw
  `--brand-primary`/`--brand-accent`); full i18n infra with **real EN/PL**; restyle existing
  auth + home pages as the proof.
- **Scope check:** focused on the foundation; every product surface (landing/dashboard/
  settings/errors) is explicitly deferred to 0d‑2, so this is a single coherent plan.
- **Ambiguity check:** theme source-of-truth precedence (User → cookie → institution default)
  and language precedence (User → session, constrained by enabled_languages) are made explicit;
  the inline override is emitted only when colors differ from defaults.
