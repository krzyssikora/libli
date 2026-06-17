# Phase 1b — WS4: Settings & auth redesign (design, 2026-06-17)

Replaces the raw `{{ form.as_p }}` dropdowns on the two settings pages with
bonnot's friendly control vocabulary (segmented controls, SVG theme tiles,
toggle chips, radio cards), rendered in libli's warm-teal identity + top-bar
shell. Build-to-mockup: **`docs/mockups/settings_redesign_accepted.html`**
(accepted 2026-06-17, both pages × light/dark). The mockup is the source of truth
for *layout and visual treatment*; where a CSS class name in the mockup diverges
from Area A's list, **Area A's names are authoritative** for the implementation.

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
- **Security** (display-only) — **password link is conditional on
  `user.has_usable_password()`:** if true, "Change password…" →
  `{% url 'account_change_password' %}`; if false (SSO/JIT-only user with no local
  password — the same users who show an SSO badge), "Set password…" →
  `{% url 'account_set_password' %}`. (allauth auto-redirects change→set anyway, but
  rendering the right label avoids confusing SSO-only users.) Badge shows
  **Connected · &lt;email/uid&gt;** (labelled per `sso_provider_label`) or **Not
  connected**, from the `sso_account` context (Area D).
- Save bar: Cancel (link back to dashboard) + Save (submit).

Form change (`core/forms.py`): add `email` to `UserSettingsForm.Meta.fields`
(`["theme", "language", "display_name", "email"]`). `User.email` is already
unique-when-present and blank→NULL-normalized in `save()`; the ModelForm picks
up that validation. Add `clean_email` (lowercase + verified-clash guard — see
Area D, steps 1–2). Help/labels wrapped in `gettext_lazy`.

### C. Institution settings (`templates/core/institution_settings.html`, rewrite)

Renders `InstitutionSettingsForm` field-by-field. `<form …
enctype="multipart/form-data">` (logo upload). Sections:
- **Identity** — `name` (text, new; **required**. The model is
  `CharField(max_length=200, default="My Institution")` and relies on Django's
  *implicit* `blank=False` (not written out); in a ModelForm the form field's
  `required` derives from `blank` (→ `required=True`), while the model `default`
  only seeds the form field's `initial` — it does **not** relax `required`. So an
  empty submission surfaces the standard "required" error in the field's `.err`
  slot rather than silently writing `""`. Values are `CharField`-stripped; no
  min-length beyond non-empty. **Invariant:** if `name` is declared as an explicit
  form field (e.g. for a widget), it must keep `required=True` — the empty-name
  test guards this), `logo` (new; `.settings-logo-row` =
  current-logo thumbnail or an initials placeholder — **first letters of up to the
  first two whitespace-split words of `name`, uppercased** (e.g. "Greenfield
  School" → "GS"; one-word name → its first letter) + Upload button +
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
Pass `sso_account` to the template. **Label source:** use the configured
`SocialApp.name` for that provider (admin-set; e.g. "Google") — **not**
allauth's registry name for `openid_connect`, which is the generic "OpenID
Connect." Look it up once (`SocialApp.objects.filter(provider="openid_connect")
.first().name`, the same row landing/SSO already resolves) and pass it as
`sso_provider_label`; fall back to the provider id if unnamed. Badge =
`Connected · <account email/uid>` when `sso_account` exists, else "Not connected."
Display-only: no connect/disconnect in WS4 (allauth's own connections page
handles that; not linked here, to keep scope tight).

**View wiring (both render paths).** Compute `sso_account` + `sso_provider_label`
**unconditionally, before the method branch**, and include them in **every**
`render()` of `user_settings.html`. The existing view already falls through to a
single `return render(request, "core/user_settings.html", {"form": form})` after
the POST branch, so an *invalid* POST re-renders the **bound** form (with
`{{ field.errors }}`/`non_field_errors`) — no new `else` branch is needed; just add
the two SSO context keys to that existing render dict so the badge survives an
invalid re-render. The email reconcile (steps 3–5) stays inside `if
form.is_valid()`.

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

1. **Case-fold at the form boundary.** Add `UserSettingsForm.clean_email`. It reads
   `self.cleaned_data["email"]`, which Django's `EmailField` has **already stripped**
   (so `"  "` arrives as `""` — no extra stripping needed). Treat falsy as blank →
   **return `None` (not `""`)**; otherwise return the value `.lower()`-cased (so
   `User.email` matches allauth's stored casing — resolves the NULL-vs-lowercase
   divergence). Returning `None` for blank matches the model's NULL normalization
   and the field's `empty_value`, so the `changed_data` comparison against
   `initial=None` (step 5) is stable and a NULL-email user who leaves the field
   blank registers *no* change. (Precondition: `User.email` is always NULL — never
   `""` — at rest, guaranteed by the model `save()` normalization, so `initial` is
   `None` and the comparison is exact. A legacy `""` row would re-normalize to NULL
   on its next save.)
2. **Pre-empt the clash in the form, not the view.** `clean_email` calls the
   **existing** `accounts/provisioning.py::verified_email_belongs_to_other(email,
   user) -> bool` (note the `(email, user)` arg order; it's the documented
   "pre-link clash guard so `ensure_verified_primary_email` cannot raise") — if it
   returns True, raise `forms.ValidationError` on the `email` field. This surfaces
   as a field error **before** `form.save()`, so the `ValueError` path can never
   500 mid-save. **Reuse this helper — do not write a new one;** it already holds
   the single `verified=True … exclude(user=user)` definition the inner save path
   relies on, so the two sites can't drift.
   **Two independent uniqueness checks — keep them distinct:** (a) `User.email`'s
   model-level `unique=True` makes the ModelForm reject a duplicate that already
   sits on *another `User` row* (a User↔User collision); (b) this `clean_email`
   clash guard rejects an address held as a *verified `EmailAddress`* by another
   user (an allauth-side collision) — the two stores can diverge (e.g. an SSO/JIT
   user owns an `EmailAddress` not mirrored on `User.email`). Both surface on the
   `email` field. The "rejects a duplicate email" test targets path (a); a separate
   test covers path (b).
3. **Encapsulation + atomicity.** Put the `EmailAddress` reconciliation in a new
   `accounts/emails.py` helper — `reconcile_primary_email(user)` (reads
   `user.email`; demote-all-then-assert, or delete-all when NULL) — so allauth's
   `EmailAddress` import stays out of `core/views.py` (matching the existing
   `provisioning.py` convention of importing it inside functions). Wrap **both**
   `form.save()` and the helper call in a single `transaction.atomic()` so a
   mid-sequence failure rolls back the `User.email` write too — the stores never
   diverge.
4. `user = form.save()`; re-sync session/cookie as today. (No pre-save email
   capture is needed — the reconcile keys off `user.email`, never the old value.)
5. **Only when the email actually changed** — `if "email" in form.changed_data:`,
   call `reconcile_primary_email(user)`, which branches on the new value, the two
   arms **mutually exclusive on emptiness** so the demote query never sees a `None`
   email:
   - **`if user.email:` (set/changed to a non-empty address):** demote **every
     other** address —
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
   - **`else:` (cleared to blank → `user.email is None`):** delete the user's
     allauth rows — `EmailAddress.objects.filter(user=user).delete()` — leaving no
     canonical address (correct for an emailless class account). Delete-all is the
     chosen, simplest consistent state (a narrower delete would need the old
     address, which is deliberately not captured).

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
| `core/forms.py` | `UserSettingsForm`: add `email` to fields + `clean_email` (lowercase, blank→`None`, reuse `verified_email_belongs_to_other` — Area D). |
| `institution/forms.py` | `InstitutionSettingsForm`: add `name`, `logo`; `clean_logo` size-only guard (`MAX_LOGO_BYTES`, no-file short-circuit); wrap choice/label/help strings in `gettext_lazy`. |
| `accounts/emails.py` | **New helper** `reconcile_primary_email(user)` (demote-all-then-assert, or delete-all when NULL); keeps allauth `EmailAddress` imports out of `core/views.py`. |
| `core/views.py` | `institution_settings`: pass `request.FILES`. `user_settings`: compute `sso_account`/`sso_provider_label` before the method branch (all render paths); on valid POST, `transaction.atomic()` around `form.save()` + `reconcile_primary_email` (Area D). |
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
    (`User.email` uniqueness) — fixture: a *second* `User` saved with a concrete
    lowercase email equal to the one under test (a blank/NULL fixture wouldn't
    clash, giving a false green); **path (b)** rejects an address held as a verified
    `EmailAddress` by another user (via `verified_email_belongs_to_other`); blank
    email → NULL; a NULL-email user submitting an untouched blank field registers
    **no** `changed_data` (no spurious `EmailAddress` delete).
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
  the new address; clearing email deletes the user's `EmailAddress` rows; a logo
  **clear** POST leaves `inst.logo` falsy and the page renders the initials
  placeholder (not a broken `<img>`); an **invalid** POST re-renders the bound form
  with the field error **and** the SSO badge still present; SSO badge context
  present/absent renders correctly.
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
labels come from `settings.LANGUAGES`** — *not* from `User.LANG_CHOICES`, which
drives no WS4 control. (The institution form uses `settings.LANGUAGES` directly
for both code set and labels; the **user** form's `__init__` takes its *labels*
from `settings.LANGUAGES` but narrows the rendered *code set* to
`get_site_config()["enabled_languages"]` — the institution's runtime config, not
all of `settings.LANGUAGES`. Only the labels need wrapping.) Wrap the `settings.LANGUAGES`
labels with `gettext_lazy` as the i18n source for language copy; **verify
`makemessages` actually extracts them** — a plain settings module isn't always on
the scan path, so if the strings don't appear in the catalog, move the labels to a
dedicated translatable module imported by settings (or rely on Django's own
already-translated language names). The done-gate's empty/`fuzzy` check catches a
miss here.

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
