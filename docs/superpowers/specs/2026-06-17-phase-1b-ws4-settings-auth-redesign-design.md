# Phase 1b — WS4: Settings & auth redesign (design, 2026-06-17)

Replaces the raw `{{ form.as_p }}` dropdowns on the two settings pages with
bonnot's friendly control vocabulary (segmented controls, SVG theme tiles,
toggle chips, radio cards), rendered in libli's warm-teal identity + top-bar
shell. Build-to-mockup: **`docs/mockups/settings_redesign_accepted.html`**
(accepted 2026-06-17, both pages × light/dark).

## Triage items covered

- **#4** (UX) — `/settings/` + `/settings/institution/` dropdowns aren't
  user-friendly → adopt bonnot's pattern. **Primary deliverable.**
- **#3** (Q/UX) — surface more institution fields → adds **name + logo**.
- **#2 / i18n** — every new/changed label + help string is wrapped in
  `gettext`/`{% trans %}` and translated to PL as part of this workstream
  (the WS4 slice of the i18n sweep).

**Not** covered here: login (#15, build-to `identity-directions_V2-chosen.html`,
implemented separately in WS4 but a distinct task), and the other auth screens
(1.3/1.4/1.5/1.7), which remain governed by `auth-and-settings_accepted.html`.

## Reconciliation with the existing accepted mockup

The new mockup **supersedes only the user-settings (2.2) card** of
`auth-and-settings_accepted.html`. The auth screens in that file remain
authoritative. README already records this (struck-through 2.2 + new row).

## Decisions locked in brainstorming (2026-06-17)

1. **Two pages, one visual language.** Keep `/settings/` (every user) and
   `/settings/institution/` (Platform-Admin) as separate URLs/views/templates;
   share the control CSS. No merge into tabs.
2. **Institution surfaces name + logo** (new), on top of the four operational
   fields. Brand **colours** stay Phase 5.
3. **User page** = Profile (display name / username read-only / **email
   editable**) + Preferences (language / theme) + **Security** (change-password
   link, Google-SSO status badge). **No danger zone** — accounts are
   school-managed; the old mockup had none.
4. **Control mapping:** theme → SVG **tile** radios; language + default-language
   → **segmented** radios; enabled_languages → **toggle-chip** checkboxes;
   signup_policy → **radio cards** with descriptions.
5. **Save model:** keep the existing **full-form POST + explicit Save bar**. The
   `set_ui_language` / `set_theme` instant-save endpoints stay as-is — they back
   the *chrome* switches (top-bar EN/PL + theme toggle), not this form, and are
   out of scope.
6. **Logo:** full **upload + remove + image validation** (not upload-only).
7. **Email:** editable; on change, keep allauth's primary `EmailAddress` in sync
   (see Area D) so password-reset stays consistent. No new
   verification-on-change flow (trusts the managed context — see Risks).
8. **Progressive enhancement baseline:** every control is a real
   `<input type=radio|checkbox>` / text input styled with CSS — the forms submit
   and validate **with JS disabled**. JS only adds nice-to-haves (Area E).

## Area designs

### A. Settings CSS (`core/static/core/css/settings.css`, new)

Page-specific stylesheet, loaded via `{% block extra_css %}` on both settings
templates only (precedent: `editor.css` / `builder.css` are page-scoped, not in
`app.css`). Token-driven; works light + dark with **no** theme-specific
overrides beyond what the tokens provide.

Classes (names mirror the accepted mockup):

- Layout: `.settings-wrap` (max-width 760, centered), `.settings-section`
  (`.section` in mockup — rename to `.settings-section` to avoid colliding with
  the dashboard `.section`), `.settings-sec-title`, `.settings-sec-lede`.
- Field row: `.settings-field` (grid label-block | control), `.settings-field-label`,
  `.settings-field-help`, `.settings-field-control`. Collapses to one column
  ≤680px.
- Controls: `.seg` / `.seg button.is-selected`; `.chips` / `.chip.is-on` /
  `.chip .tick`; `.radio-cards` / `.rcard.is-selected` / `.rcard .dot`;
  `.tiles` / `.tile.is-selected` / `.tile-label` (+ the theme-preview `svg`).
- Misc: `.settings-logo-row` / `.settings-logo-prev` / `.settings-logo-actions`;
  `.settings-srow` (security rows) / `.settings-badge` (`.is-off`);
  `.settings-save-bar`; `.settings-admin-badge`.

**Real-input styling.** Each radio/checkbox control is a `<label>` wrapping a
visually-hidden native input + the styled face. Selection state is driven by
`:checked` (e.g. `.tile input:checked + .tile-face`), **not** a server-set
`.is-selected` class, so it works without JS and reflects user clicks live.
Focus-visible rings on the labels for keyboard a11y.

### B. User settings (`templates/core/user_settings.html`, rewrite)

Renders `UserSettingsForm` field-by-field (no `form.as_p`) inside the shell
markup from the mockup. Wrapped in `{% if form.non_field_errors %}` + per-field
`{{ field.errors }}` rendering (`.err`).

Sections:
- **Profile** — `display_name` (text), `username` (static read-only, not a form
  field — rendered from `user.username`), `email` (text, new form field).
- **Preferences** — `language` (segmented over the institution's enabled
  languages — `form.language` choices are already narrowed at form init),
  `theme` (tile radios: Light/Dark/Auto).
- **Security** (display-only) — "Change password…" links to
  `{% url 'account_change_password' %}`; Google badge shows **Connected ·
  &lt;email/uid&gt;** or **Not connected**, from `sso_account` context (Area D).
- Save bar: Cancel (link back to dashboard) + Save (submit).

Form change (`core/forms.py`): add `email` to `UserSettingsForm.Meta.fields`
(`["theme", "language", "display_name", "email"]`). `User.email` is already
unique-when-present and blank→NULL-normalized in `save()`; the ModelForm picks
up that validation. Help/labels wrapped in `gettext_lazy`.

### C. Institution settings (`templates/core/institution_settings.html`, rewrite)

Renders `InstitutionSettingsForm` field-by-field. `<form …
enctype="multipart/form-data">` (logo upload). Sections:
- **Identity** — `name` (text, new), `logo` (new; `.settings-logo-row` =
  current-logo thumbnail or "GS"-style initials placeholder + Upload button +
  Remove). Remove maps to the `ClearableFileInput` clear checkbox, restyled.
- **Languages** — `enabled_languages` (toggle-chip checkboxes over
  `settings.LANGUAGES`), `default_language` (segmented over
  `settings.LANGUAGES`). Existing `clean()` already enforces *default ∈ enabled*
  server-side; surface that as a field error on `default_language`.
- **Appearance** — `default_theme` (tile radios).
- **Access** — `signup_policy` (radio cards w/ descriptions).
- Save bar.

Form change (`institution/forms.py`): add `name` and `logo` to
`InstitutionSettingsForm.Meta.fields`. `logo` uses the model `ImageField`
(Pillow already a dep — the field exists today). Optional: cap size with a
`clean_logo` (e.g. ≤ 2 MB, content-type image/*) — **include** a basic
`clean_logo` size guard. Wrap all `choices`/labels/help in `gettext_lazy`,
including the model `SIGNUP_CHOICES` / `THEME_CHOICES` display strings used in
the radio-card / tile copy.

View change (`core/views.py::institution_settings`): pass
`request.FILES` to the form on POST (`InstitutionSettingsForm(request.POST,
request.FILES, instance=inst)`).

### D. Google-SSO status badge + email/allauth sync

**Badge (read-only).** In `user_settings`, look up
`allauth.socialaccount.models.SocialAccount.objects.filter(user=request.user)
.first()`. Pass `sso_account` to the template; badge shows provider + the
account email/uid when present, else "Not connected." Display-only — no
connect/disconnect in WS4 (allauth's own connections page handles that; not
linked here to keep scope tight).

**Email sync.** On a successful `UserSettingsForm` save where `email` changed,
reuse `accounts/emails.py::ensure_verified_primary_email(user, new_email)` (the
existing helper) to keep allauth's primary `EmailAddress` consistent with
`User.email`, so password reset targets the new address. If `email` was cleared
to empty (→ NULL), remove/never-create an allauth `EmailAddress`. This lives in
the view (after `form.save()`), guarded by `"email" in form.changed_data`.

### E. Optional JS (progressive enhancement, low priority)

A tiny `settings.js` (loaded via `extra_js`) may: (1) grey out / disable the
`default_language` segments that aren't currently checked in `enabled_languages`
and live-sync as chips toggle; (2) swap the logo thumbnail on file-pick. **Both
optional** — the no-JS baseline (server validation + full-list segments) is the
contract. Defer if the plan runs long.

## Model / endpoint / file changes (summary)

| File | Change |
|---|---|
| `core/forms.py` | `UserSettingsForm`: add `email` to fields. |
| `institution/forms.py` | `InstitutionSettingsForm`: add `name`, `logo`; `clean_logo` size/type guard; wrap choice/label/help strings in `gettext_lazy`. |
| `core/views.py` | `institution_settings`: pass `request.FILES`. `user_settings`: compute `sso_account` context; sync allauth email on change (Area D). |
| `templates/core/user_settings.html` | Full rewrite (Area B). |
| `templates/core/institution_settings.html` | Full rewrite + `enctype` (Area C). |
| `core/static/core/css/settings.css` | **New** — all control CSS (Area A). |
| `core/static/core/css/settings.js` | **New, optional** (Area E). |
| `accounts/models.py` `User` / `institution/models.py` | **No schema change** — all fields already exist (email, name, logo). No migration. |
| `locale/pl/LC_MESSAGES/django.po` | New msgids translated (i18n). |

**No DB migration** — every surfaced field already exists on its model.

## Testing & Done-gate

- **Style regression guard** (`tests/test_settings_styles.py`, mirrors
  `test_editor_styles.py`): assert `settings.css` defines the control classes
  the templates depend on (`.seg`, `.chip`, `.tile`, `.rcard`,
  `.settings-field`, …), since `app.css` doesn't and a missing rule = invisible/
  broken control. Assert both templates link `settings.css` via `extra_css`.
- **Form tests** (extend `tests/test_institution.py`, add user-settings test):
  - `UserSettingsForm` accepts/saves `email`; rejects a duplicate email;
    blank email → NULL.
  - `InstitutionSettingsForm` accepts `name` + `logo`; `clean_logo` rejects an
    oversized/non-image upload; existing default∈enabled rule still fires.
- **View tests**: institution POST with a logo file (multipart) persists it;
  user POST changing email updates `User.email` **and** the allauth primary
  `EmailAddress`; SSO badge context present/absent renders correctly.
- **e2e** (`-m e2e`, Playwright; precedent: WS3 e2e): on each page, the radio/
  checkbox controls render (no raw `<select>`), a selection submits, and the
  saved value round-trips after reload. Light + dark both readable (no
  invisible-control regression).
- **Done-gate:** `ruff` clean; all of the above green; **no raw `{{ form.as_p }}`
  remains** in either template; PL catalog has no empty/`fuzzy` msgstr for the
  strings this WS touches (per the triage i18n done-gate, scoped to WS4 strings).
- **Visual confirmation owed by user:** dark/light eyeball pass on both real
  pages after implementation (FIXED-in-code ≠ verified, per triage vocabulary).

## i18n

Every label, help string, section title/lede, button, badge, and choice-display
string introduced or touched is wrapped (`gettext_lazy` in Python,
`{% trans %}`/`{% blocktrans %}` in templates), then `makemessages -l pl` +
translate. Reuse existing msgids where wording already exists (e.g. "Change
password", "Save"). Model `choices` display labels (`SIGNUP_CHOICES`,
`THEME_CHOICES`, `LANG_CHOICES`) get wrapped at their definition so the
radio-card / tile / segment copy is translatable from one source.

## Risks / open points

- **Email-change without re-verification** sets a verified primary
  `EmailAddress` for an address the user hasn't proven they own. Accepted for
  the school-managed trust model (same as SSO JIT provisioning); flagged so it
  can be revisited if libli later opens self-service email changes. The
  alternative (send a confirmation, defer the change) is out of scope for a
  restyle workstream.
- **`.section` name collision** — the dashboard mockup uses `.section`; this
  spec renames the settings card class to `.settings-section` to avoid leaking
  styles between pages. Confirm no shared selector during implementation.

## Out of scope

- Login (#15) and the other auth screens — separate tasks/mockups.
- Brand **colours** / full branding admin (Phase 5).
- SSO connect/disconnect management UI (allauth's own pages).
- Self-service email-change verification flow.
- Account deletion / danger zone.
- Merging the two settings pages or adding a settings nav/tab structure.

## Sequencing hint (for the plan)

1. `settings.css` + the style regression guard (TDD: guard first).
2. Form changes (`email`; `name`/`logo`/`clean_logo`) + form tests.
3. Template rewrites (user, then institution) + view wiring (`request.FILES`,
   SSO context, email sync) + view tests.
4. i18n wrap + PL catalog.
5. e2e + final ruff/light-dark pass.
6. Optional JS (Area E) last, only if time allows.
