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
- **Profile** — `display_name` (text), `username` (static read-only, rendered
  from `user.username`; intentionally **not** in `Meta.fields`, so a forged POST
  `username=` is ignored by the ModelForm — no extra guard needed), `email`
  (text, new form field).
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
up that validation. Add `clean_email` (lowercase + verified-clash guard — see
Area D, steps 1–2). Help/labels wrapped in `gettext_lazy`.

### C. Institution settings (`templates/core/institution_settings.html`, rewrite)

Renders `InstitutionSettingsForm` field-by-field. `<form …
enctype="multipart/form-data">` (logo upload). Sections:
- **Identity** — `name` (text, new; **required** per the model —
  `CharField(max_length=200)`, no `blank=True` — so an empty submission surfaces
  the standard "required" error in the field's `.err` slot; values are
  `.strip()`-trimmed, no min-length beyond non-empty), `logo` (new; `.settings-logo-row` =
  current-logo thumbnail or "GS"-style initials placeholder + Upload button +
  Remove). **Render `{{ form.logo }}` (the `ClearableFileInput`) rather than
  hand-rolled inputs**, so Django's expected field names round-trip: the file
  input `name="logo"` and, when a logo exists, the clear checkbox
  `name="logo-clear"`. Style those native controls via CSS (label-wrapped,
  visually-hidden input → styled "Upload…"/"Remove" faces) — do **not** rename
  the fields. After a successful clear, the thumbnail falls back to the initials
  placeholder.
- **Languages** — `enabled_languages` (toggle-chip checkboxes over
  `settings.LANGUAGES`; its existing `clean_enabled_languages` raises "Enable at
  least one language" when all chips are off — render an `.err` slot under the
  chip group for that error too, not only under `default_language`),
  `default_language` (segmented over `settings.LANGUAGES`). Existing `clean()`
  already enforces *default ∈ enabled* server-side; surface that as a field error
  on `default_language`.
  **No-JS baseline when the stored `default_language` isn't in the current
  enabled set** (possible after a prior save, or mid-edit): the segmented control
  still renders **all** `settings.LANGUAGES` and keeps the stored value as the
  checked segment (so it's never silently lost); the `clean()` field error renders
  in the field's `.err` slot directly under the control, and the form won't save
  until the user picks an enabled language. The optional JS (Area E) only *adds*
  live greying of non-enabled segments — it is not required for correctness.
  *Scope:* this baseline covers only *default ∉ enabled* (the value is still within
  `settings.LANGUAGES`, so the field's own `choices=settings.LANGUAGES` validation
  passes and `clean()` is what flags it). A stored `default_language` *outside*
  `settings.LANGUAGES` is assumed impossible (the supported set is stable) and is
  out of scope — the `ChoiceField` would reject it at field level before `clean()`.
- **Appearance** — `default_theme` (tile radios).
- **Access** — `signup_policy` (radio cards w/ descriptions).
- Save bar.

Form change (`institution/forms.py`): add `name` and `logo` to
`InstitutionSettingsForm.Meta.fields`. `logo` uses the model `ImageField`
(Pillow already a dep — the field exists today). The model `ImageField` + Pillow
already reject non-images by *decoding* the upload, so **`clean_logo` is
size-only**: define a module constant `MAX_LOGO_BYTES = 2 * 1024 * 1024` (exactly
2 MB) and reject `value.size > MAX_LOGO_BYTES`; do **not** gate on the spoofable
browser `content_type`. **Guard the no-file paths first:** with a
`ClearableFileInput`, `clean_logo` receives `False` (clear checked) or the unchanged
stored file / `None` when no new upload — short-circuit (`if not value or value is
False: return value`) and only read `.size` on a genuinely uploaded
`UploadedFile`, or `False.size` raises `AttributeError`. The "rejects a non-image"
form test relies on `ImageField`/Pillow validation, the "rejects oversized" test on
`clean_logo` against `MAX_LOGO_BYTES`.
Wrap all `choices`/labels/help in `gettext_lazy`,
including the model `SIGNUP_CHOICES` / `THEME_CHOICES` display strings used in
the radio-card / tile copy.

View change (`core/views.py::institution_settings`): pass
`request.FILES` to the form on POST (`InstitutionSettingsForm(request.POST,
request.FILES, instance=inst)`).

### D. SSO status badge + email/allauth sync

**Badge (read-only).** In `user_settings`, look up the user's social account
filtered to libli's configured provider — `SocialAccount.objects.filter(
user=request.user, provider="openid_connect").first()` (libli's only social
provider; the OIDC app is set up in landing/SSO as `provider="openid_connect"`).
Pass `sso_account` to the template; the badge shows the provider's display name +
the account email/uid when present, else "Not connected." The mockup labels it
"Google" illustratively — the real label follows the configured provider.
Display-only: no connect/disconnect in WS4 (allauth's own connections page
handles that; not linked here, to keep scope tight).

**Email sync — exact algorithm.** `User.email` (unique-when-present, NULL when
blank) and allauth's `EmailAddress` table are *separate* stores; this keeps them
consistent so password reset targets the right address. The existing helper
`accounts/emails.py::ensure_verified_primary_email(user, email)` (a) lowercases,
(b) **raises `ValueError`** if a *verified* `EmailAddress` for that address is
bound to a *different* user, and (c) per its docstring **does not demote an
existing primary** — so calling it naively on an email *change* would leave the
user with two `primary=True` rows. The spec therefore pins the full algorithm,
in `user_settings` POST, **inside the `if form.is_valid()` block** (where the
session/cookie re-sync already lives):

1. **Case-fold at the form boundary.** Add `UserSettingsForm.clean_email`: lower-
   case a non-empty value (so `User.email` matches allauth's stored casing —
   resolves the NULL-vs-lowercase divergence) and **return `None` (not `""`) for
   blank** — matching the model's NULL normalization and the field's `empty_value`,
   so the `changed_data` comparison against `initial=None` (step 5) is stable and a
   NULL-email user who leaves the field blank registers *no* change.
2. **Pre-empt the clash in the form, not the view.** `clean_email` also runs the
   helper's clash query — a *verified* `EmailAddress` for this address on another
   user → `forms.ValidationError` on the `email` field. This surfaces as a field
   error **before** `form.save()`, so the `ValueError` path can never 500 mid-save.
   **Two independent uniqueness checks — keep them distinct:** (a) `User.email`'s
   model-level `unique=True` makes the ModelForm reject a duplicate that already
   sits on *another `User` row* (a User↔User collision); (b) this `clean_email`
   clash guard rejects an address held as a *verified `EmailAddress`* by another
   user (an allauth-side collision) — the two stores can diverge (e.g. an SSO/JIT
   user owns an `EmailAddress` not mirrored on `User.email`). Both surface on the
   `email` field. The "rejects a duplicate email" test targets path (a); a separate
   test covers path (b).
3. Capture `old_email = form.initial.get("email")` **before** `form.save()` (the
   pre-save value; `form.save()` overwrites `instance.email`).
4. `user = form.save()`; then re-sync session/cookie as today.
5. If `"email" in form.changed_data`:
   - **Set/changed to a non-empty address:** demote **every other** address —
     `EmailAddress.objects.filter(user=user).exclude(
     email__iexact=user.email).update(primary=False)` (demote *all* non-target
     rows, not just ones currently flagged primary; non-primary rows are a no-op,
     and this is robust regardless of the pre-existing row mix) — then call
     `ensure_verified_primary_email(user, user.email)`, which get-or-creates the
     target row and forces it verified+primary. Net result: the target is the sole
     `primary=True`. Covers the case where the user *already* holds the new address
     as a non-primary (verified or unverified) row — the helper finds and promotes
     it. (Demote-all-then-assert is what keeps a single primary; the helper alone
     does not.)
   - **Cleared to blank (→ NULL):** delete the user's allauth rows —
     `EmailAddress.objects.filter(user=user).delete()` — leaving no canonical
     address (correct for an emailless class account). `old_email` is available
     from step 3 if a narrower delete is preferred, but delete-all is the chosen,
     simplest consistent state.

**Risk note (verification):** step 2's clash guard blocks *hijacking* a
confirmed address, but step 5 still marks the user's *own* new address verified
without proof of ownership — accepted per Decision 7's managed-trust model.

### E. Optional JS (progressive enhancement, low priority)

A tiny `settings.js` (loaded via `extra_js`) may: (1) grey out / disable the
`default_language` segments that aren't currently checked in `enabled_languages`
and live-sync as chips toggle; (2) swap the logo thumbnail on file-pick. **Both
optional** — the no-JS baseline (server validation + full-list segments) is the
contract. Defer if the plan runs long.

## Model / endpoint / file changes (summary)

| File | Change |
|---|---|
| `core/forms.py` | `UserSettingsForm`: add `email` to fields + `clean_email` (lowercase, blank→`None`, verified-clash guard — Area D). |
| `institution/forms.py` | `InstitutionSettingsForm`: add `name`, `logo`; `clean_logo` size-only guard (`MAX_LOGO_BYTES`, no-file short-circuit); wrap choice/label/help strings in `gettext_lazy`. |
| `core/views.py` | `institution_settings`: pass `request.FILES`. `user_settings`: compute `sso_account` context; sync allauth email on change (Area D). |
| `templates/core/user_settings.html` | Full rewrite (Area B). Templates live under `templates/` (a configured template `DIRS` root), so the views' `render(request, "core/…")` paths resolve here — no view path change. |
| `templates/core/institution_settings.html` | Full rewrite + `enctype` (Area C). |
| `core/static/core/css/settings.css` | **New** — all control CSS (Area A). |
| `core/static/core/js/settings.js` | **New, optional** (Area E). |
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
  - `UserSettingsForm` accepts/saves `email`; `clean_email` lowercases mixed-case
    input; **path (a)** rejects an email already on another `User` row
    (`User.email` uniqueness); **path (b)** rejects an address held as a verified
    `EmailAddress` by another user (clash guard); blank email → NULL; a NULL-email
    user submitting an untouched blank field registers **no** `changed_data`
    (no spurious `EmailAddress` delete).
  - `InstitutionSettingsForm` accepts `name` + `logo`; **empty `name` → required
    error**; `clean_logo` rejects an upload `> MAX_LOGO_BYTES`; a non-image upload
    is rejected by `ImageField`/Pillow; submitting with the clear checkbox set
    (no file) does **not** raise; existing default∈enabled + "enable at least one"
    rules still fire.
  - **Test fixtures:** build the *valid* image with Pillow into a `BytesIO`
    (`Image.new("RGB",(1,1)).save(buf,"PNG")`) wrapped in `SimpleUploadedFile`, so
    it survives the `ImageField` decode; the *non-image* fixture is arbitrary bytes
    with a `.png` name (Pillow fails to decode). A faked `SimpleUploadedFile(b"...",
    content_type="image/png")` would wrongly fail the *accept* test.
- **View tests** (`@override_settings(MEDIA_ROOT=<tmp_path>)` so logo uploads are
  hermetic — assert `inst.logo.name` starts with `branding/`): institution POST
  with a logo file (multipart) persists it; user POST changing email updates
  `User.email` **and** leaves exactly one `primary=True` allauth `EmailAddress` at
  the new address; clearing email deletes the user's `EmailAddress` rows; SSO badge
  context present/absent renders correctly.
- **e2e** (`-m e2e`, Playwright; precedent: WS3 e2e): on each page, assert
  **both** that no raw `<select>` survives **and** that each expected styled
  control is present (user: `.seg` + `.tile`; institution: `.chip` + `.seg` +
  `.tile` + `.rcard`) — "no `<select>`" alone wouldn't catch a field that
  silently rendered nothing. Then a selection submits and the saved value
  round-trips after reload. Light + dark both readable (no
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
password", "Save"). The institution model `choices` display labels
(`SIGNUP_CHOICES`, `THEME_CHOICES`) get wrapped at their definition so the
radio-card / tile copy is translatable from one source. The **language segment
labels come from `settings.LANGUAGES`** (institution form's `ChoiceField`/
`MultipleChoiceField`, and the user form's `__init__` narrowing) — *not* from
`User.LANG_CHOICES`, which drives no WS4 control; wrap the `settings.LANGUAGES`
labels (in `config/settings`) as the i18n source for language copy.

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
