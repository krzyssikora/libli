# Phase 1b — WS4: Settings & auth redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the raw `{{ form.as_p }}` dropdowns on `/settings/` and `/settings/institution/` with friendly, no-JS controls (segmented radios, SVG theme tiles, toggle chips, radio cards), surface institution name + logo, add editable email with allauth sync, and an SSO status badge — all in libli's warm-teal identity.

**Architecture:** Server-rendered Django templates extend the existing `base.html` shell and fill `{% block content %}` with a `.settings-wrap` of titled sections. Each control is a **real** `<input type=radio|checkbox>`/text input styled via a new page-scoped `core/static/core/css/settings.css` using `:checked`-driven selection — works with JS disabled. Form/model fields already exist (no migration); the only logic additions are `UserSettingsForm.clean_email`, `InstitutionSettingsForm` name/logo + `clean_logo`, a `reconcile_primary_email` helper, and view wiring (request.FILES, SSO context, atomic email sync).

**Tech Stack:** Django 5, django-allauth, Pillow (already deps), pytest-django, pytest-playwright, ruff.

**Spec:** `docs/superpowers/specs/2026-06-17-phase-1b-ws4-settings-auth-redesign-design.md`
**Mockup (build-to):** `docs/mockups/settings_redesign_accepted.html`

**Conventions to follow (verified in-repo):**
- Tests run from repo root; default `addopts = "-q -m 'not e2e'"`. Run unit tests with `uv run pytest <path> -v`. Run e2e with `uv run pytest -m e2e <path> -v`.
- Test helpers: `tests/factories.py` (`make_verified_user`, `make_pa`, `TEST_PASSWORD`, `UserFactory`), `tests/_sso.py` (`make_oidc_app`).
- Django's `{{ field.errors }}` renders `<ul class="errorlist">`, already styled in `app.css` — reuse it as the error slot (the spec's conceptual `.err`).
- `base.html` provides the top-bar shell (brand, lang switch, theme toggle, avatar menu). Settings templates only provide `{% block content %}` + `{% block extra_css %}`.
- Bash commands below use POSIX (`uv run …`); on this Windows box run them via the Bash tool, not PowerShell.

---

## File Structure

| File | Responsibility |
|---|---|
| `core/static/core/css/settings.css` | **New.** All settings control CSS (layout, seg, chips, radio-cards, tiles, logo, security, save-bar), token-driven, `:checked`-selection. |
| `accounts/emails.py` | **Modify.** Add `reconcile_primary_email(user)` (demote-all-then-assert, or delete-all when NULL). |
| `core/forms.py` | **Modify.** `UserSettingsForm`: add `email` field + `clean_email` (lowercase, blank→None, reuse `verified_email_belongs_to_other`). |
| `institution/models.py` | **Modify.** Wrap `SIGNUP_CHOICES` / `THEME_CHOICES` display labels in `gettext_lazy`. |
| `institution/forms.py` | **Modify.** `InstitutionSettingsForm`: add `name` + `logo`; `MAX_LOGO_BYTES` + `clean_logo`; wrap labels/help in `gettext_lazy`. |
| `core/views.py` | **Modify.** `user_settings`: SSO context (all render paths) + atomic email sync. `institution_settings`: pass `request.FILES`. |
| `templates/core/_theme_tiles.html` | **New.** Shared partial: the 3 SVG theme-preview tile radios (used by user `theme` + institution `default_theme`). |
| `templates/core/user_settings.html` | **Rewrite.** Field-by-field, new controls + Security section. |
| `templates/core/institution_settings.html` | **Rewrite.** Field-by-field + `enctype="multipart/form-data"`. |
| `tests/test_settings_styles.py` | **New.** Style regression guard (classes defined + templates link the CSS). |
| `tests/test_settings_forms.py` | **New.** `UserSettingsForm.clean_email` + `InstitutionSettingsForm` name/logo unit tests. |
| `tests/test_accounts_emails.py` | **Modify.** `reconcile_primary_email` unit tests. |
| `tests/test_surfaces.py` | **Modify.** View-level tests (email sync, SSO badge, logo upload/clear, invalid re-render). |
| `tests/test_e2e_settings.py` | **New.** Playwright: controls render, submit, round-trip, light+dark. |
| `core/static/core/js/settings.js` | **New, optional (Task 11).** Progressive enhancement only. |

No DB migration — `User.email`, `Institution.name`, `Institution.logo` all already exist.

---

## Task 1: Settings CSS + style regression guard

**Files:**
- Test: `tests/test_settings_styles.py` (create)
- Create: `core/static/core/css/settings.css`

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings_styles.py`:

```python
"""Regression guard for settings styling (mirrors test_editor_styles.py).

The two settings templates render bespoke controls (.seg/.chip/.tile/.rcard) that
app.css does NOT define; a missing rule = an invisible/broken control. These tests
assert settings.css defines those classes and that both templates link it.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_CSS = ROOT / "core" / "static" / "core" / "css" / "settings.css"
USER_TPL = ROOT / "templates" / "core" / "user_settings.html"
INST_TPL = ROOT / "templates" / "core" / "institution_settings.html"


def test_settings_css_defines_control_classes():
    css = SETTINGS_CSS.read_text(encoding="utf-8")
    for cls in (
        ".settings-wrap",
        ".settings-section",
        ".settings-field",
        ".seg",
        ".chip",
        ".tile",
        ".rcard",
        ".settings-logo-row",
        ".settings-srow",
        ".settings-badge",
        ".settings-save-bar",
    ):
        assert cls in css, f"settings.css must style {cls}"


def test_settings_css_uses_checked_selection():
    # Selection must be :checked-driven (no JS), not a server-set .is-selected class.
    css = SETTINGS_CSS.read_text(encoding="utf-8")
    assert "input:checked" in css


def test_both_templates_link_settings_css():
    for tpl in (USER_TPL, INST_TPL):
        body = tpl.read_text(encoding="utf-8")
        assert "core/css/settings.css" in body, f"{tpl.name} must link settings.css"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_settings_styles.py -v`
Expected: FAIL — `settings.css` does not exist (FileNotFoundError) / templates don't link it yet.

- [ ] **Step 3: Create `core/static/core/css/settings.css`**

```css
/* Settings pages (user + institution). Page-scoped: loaded via {% block extra_css %}
   on the two settings templates only (precedent: editor.css / builder.css).
   Token-driven; selection is :checked-driven so every control works with JS off. */

.settings-wrap { max-width: 760px; margin: 0 auto; }

.settings-wrap .page-head { margin-bottom: var(--space-2); }
.settings-wrap .page-title { font-size: 1.5rem; font-weight: 700;
  letter-spacing: var(--heading-letter-spacing); color: var(--text-primary); margin: 0; }
.settings-wrap .page-meta { color: var(--text-secondary); font-size: .9rem; margin: 2px 0 0; }
.settings-admin-badge { display: inline-block; font-size: .7rem; font-weight: 700;
  border-radius: var(--radius-full); padding: 2px 9px; vertical-align: middle;
  background: var(--accent-subtle); color: var(--accent); margin-left: var(--space-2); }

.settings-section { background: var(--surface-raised); border: 1px solid var(--border-default);
  border-radius: var(--radius-lg); padding: var(--space-5) var(--space-6);
  margin-top: var(--space-4); box-shadow: var(--shadow-sm); }
.settings-sec-title { font-size: 1rem; font-weight: 700; color: var(--text-primary); margin: 0; }
.settings-sec-lede { color: var(--text-secondary); font-size: .85rem; margin: 3px 0 4px; line-height: 1.5; }

/* field row: label/help left, control right */
.settings-field { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1.15fr);
  gap: var(--space-5); align-items: start; padding: var(--space-4) 0;
  border-top: 1px solid var(--border-subtle); }
.settings-field:first-of-type { border-top: none; }
.settings-field-label { font-size: .9rem; font-weight: 600; color: var(--text-primary); }
.settings-field-help { font-size: .8rem; color: var(--text-tertiary); margin: 3px 0 0; line-height: 1.45; }
.settings-field-control { display: flex; flex-direction: column; gap: var(--space-2); min-width: 0; }
@media (max-width: 680px) { .settings-field { grid-template-columns: 1fr; gap: var(--space-2); } }

/* the field error slot reuses Django's .errorlist (styled in app.css) */
.settings-field .errorlist { margin-top: 2px; }

/* visually-hidden native input (the styled face sits next to it) */
.settings-wrap .vh { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

/* read-only text */
.input--readonly { color: var(--text-tertiary); background: var(--surface-base);
  cursor: not-allowed; }

/* segmented control (real radios) */
.seg { display: inline-flex; border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm); overflow: hidden; width: fit-content;
  font-size: .85rem; font-weight: 600; }
.seg label { display: inline-flex; align-items: center; margin: 0; padding: var(--space-2) var(--space-4);
  color: var(--text-secondary); cursor: pointer; border-left: 1px solid var(--border-strong); font-weight: 600; }
.seg label:first-of-type { border-left: none; }
.seg input:checked + span { color: inherit; }
.seg label:has(input:checked) { background: var(--primary); color: var(--text-inverse); }
.seg label:focus-within { outline: 2px solid var(--primary); outline-offset: -2px; }

/* toggle chips (real checkboxes) */
.chips { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.chip { display: inline-flex; align-items: center; gap: 7px; margin: 0; padding: 7px 13px;
  border-radius: var(--radius-full); border: 1px solid var(--border-strong);
  background: var(--surface-sunken); color: var(--text-secondary);
  font-size: .85rem; font-weight: 600; cursor: pointer; }
.chip .tick { width: 15px; height: 15px; border-radius: 50%; border: 1.5px solid var(--border-strong);
  display: inline-flex; align-items: center; justify-content: center; font-size: 10px; color: transparent; }
.chip:has(input:checked) { border-color: var(--primary); background: var(--primary-subtle); color: var(--primary); }
.chip:has(input:checked) .tick { background: var(--primary); border-color: var(--primary); color: var(--text-inverse); }
.chip:focus-within { outline: 2px solid var(--primary); outline-offset: 2px; }

/* radio cards (real radios w/ descriptions) */
.radio-cards { display: flex; flex-direction: column; gap: var(--space-2); }
.rcard { display: flex; gap: 11px; margin: 0; padding: 12px 13px; border: 1px solid var(--border-strong);
  border-radius: var(--radius-md); background: var(--surface-sunken); cursor: pointer; }
.rcard .dot { flex: 0 0 auto; width: 17px; height: 17px; border-radius: 50%;
  border: 2px solid var(--border-strong); margin-top: 1px; position: relative; }
.rcard:has(input:checked) { border-color: var(--primary); background: var(--primary-subtle); }
.rcard:has(input:checked) .dot { border-color: var(--primary); }
.rcard:has(input:checked) .dot::after { content: ""; position: absolute; inset: 3px;
  border-radius: 50%; background: var(--primary); }
.rcard:focus-within { outline: 2px solid var(--primary); outline-offset: 2px; }
.rc-title { font-size: .85rem; font-weight: 700; color: var(--text-primary); }
.rc-desc { font-size: .78rem; color: var(--text-secondary); margin-top: 2px; line-height: 1.45; }

/* theme tile grid (real radios + SVG previews) */
.tiles { display: flex; gap: var(--space-3); flex-wrap: wrap; }
.tile { width: 124px; margin: 0; border: 1px solid var(--border-strong); border-radius: var(--radius-md);
  background: var(--surface-sunken); padding: var(--space-2); cursor: pointer; text-align: center; }
.tile svg { width: 100%; height: auto; border-radius: 6px; display: block; border: 1px solid var(--border-default); }
.tile-label { display: block; margin-top: 7px; font-size: .8rem; font-weight: 600; color: var(--text-primary); }
.tile:has(input:checked) { border-color: var(--primary); box-shadow: 0 0 0 2px var(--primary-subtle); }
.tile:focus-within { outline: 2px solid var(--primary); outline-offset: 2px; }

/* logo field */
.settings-logo-row { display: flex; align-items: center; gap: var(--space-4); }
.settings-logo-prev { width: 56px; height: 56px; border-radius: var(--radius-md);
  border: 1px solid var(--border-default); background: var(--surface-base);
  display: flex; align-items: center; justify-content: center;
  color: var(--text-tertiary); font-weight: 800; font-size: 1.1rem; overflow: hidden; }
.settings-logo-prev img { width: 100%; height: 100%; object-fit: contain; }
.settings-logo-actions { display: flex; flex-direction: column; gap: var(--space-1); }
/* style the native file input + clear checkbox as buttons */
.settings-logo-actions input[type=file] { font-size: .8rem; color: var(--text-secondary); }
.settings-logo-actions label { display: inline-flex; align-items: center; gap: 6px;
  margin: 0; font-weight: 600; color: var(--text-secondary); font-size: .8rem; }

/* security rows */
.settings-srow { display: flex; align-items: center; justify-content: space-between;
  gap: var(--space-4); padding: var(--space-4) 0; border-top: 1px solid var(--border-subtle); }
.settings-srow:first-of-type { border-top: none; }
.settings-srow .k { font-size: .9rem; font-weight: 600; color: var(--text-primary); }
.settings-srow .d { font-size: .8rem; color: var(--text-tertiary); margin-top: 2px; }
.settings-badge { display: inline-flex; align-items: center; gap: 6px; font-size: .8rem; font-weight: 700;
  border-radius: var(--radius-full); padding: 4px 11px; background: var(--success-subtle); color: var(--success); }
.settings-badge.is-off { background: var(--surface-sunken); color: var(--text-tertiary); }

/* save bar */
.settings-save-bar { display: flex; gap: var(--space-3); justify-content: flex-end;
  margin-top: var(--space-5); padding-top: var(--space-2); }
```

- [ ] **Step 4: Run test to verify CSS classes pass (template link assertions still fail)**

Run: `uv run pytest tests/test_settings_styles.py -v`
Expected: `test_settings_css_defines_control_classes` PASS, `test_settings_css_uses_checked_selection` PASS, `test_both_templates_link_settings_css` FAIL (templates not rewritten yet — fixed in Tasks 7–8).

- [ ] **Step 5: Commit**

```bash
git add core/static/core/css/settings.css tests/test_settings_styles.py
git commit -m "feat(ws4): settings.css control vocabulary + style regression guard"
```

---

## Task 2: `reconcile_primary_email` helper

**Files:**
- Modify: `accounts/emails.py`
- Test: `tests/test_accounts_emails.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_accounts_emails.py`:

```python
def test_reconcile_sets_single_primary_on_change():
    from allauth.account.models import EmailAddress

    from accounts.emails import reconcile_primary_email

    user = User.objects.create_user(
        username="cyd", email="old@school.edu", password=TEST_PASSWORD
    )
    EmailAddress.objects.create(user=user, email="old@school.edu", verified=True, primary=True)
    user.email = "new@school.edu"  # simulate post-form.save()
    user.save()
    reconcile_primary_email(user)
    primaries = EmailAddress.objects.filter(user=user, primary=True)
    assert primaries.count() == 1
    assert primaries.first().email == "new@school.edu"
    assert primaries.first().verified


def test_reconcile_promotes_existing_nonprimary_row():
    from allauth.account.models import EmailAddress

    from accounts.emails import reconcile_primary_email

    user = User.objects.create_user(
        username="dee", email="dee@school.edu", password=TEST_PASSWORD
    )
    EmailAddress.objects.create(user=user, email="dee@school.edu", verified=False, primary=False)
    reconcile_primary_email(user)
    row = EmailAddress.objects.get(user=user, email="dee@school.edu")
    assert row.verified and row.primary
    assert EmailAddress.objects.filter(user=user, primary=True).count() == 1


def test_reconcile_deletes_all_rows_when_email_cleared():
    from allauth.account.models import EmailAddress

    from accounts.emails import reconcile_primary_email

    user = User.objects.create_user(
        username="eve", email="eve@school.edu", password=TEST_PASSWORD
    )
    EmailAddress.objects.create(user=user, email="eve@school.edu", verified=True, primary=True)
    user.email = None  # cleared (model normalizes blank->None)
    user.save()
    reconcile_primary_email(user)
    assert EmailAddress.objects.filter(user=user).count() == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_accounts_emails.py -k reconcile -v`
Expected: FAIL — `ImportError: cannot import name 'reconcile_primary_email'`.

- [ ] **Step 3: Implement the helper**

Append to `accounts/emails.py` (after `ensure_verified_primary_email`):

```python
def reconcile_primary_email(user):
    """Keep allauth's EmailAddress rows consistent with `user.email` after a change.

    Call AFTER user.save(). Two mutually-exclusive arms on emptiness so the demote
    query never sees a None email:
      - non-empty: demote every OTHER address, then ensure_verified_primary_email
        makes `user.email` the sole verified primary (it does not demote on its own).
      - cleared (NULL): delete all the user's rows (no canonical address — correct
        for an emailless class account).
    """
    from allauth.account.models import EmailAddress

    if user.email:
        EmailAddress.objects.filter(user=user).exclude(
            email__iexact=user.email
        ).update(primary=False)
        ensure_verified_primary_email(user, user.email)
    else:
        EmailAddress.objects.filter(user=user).delete()
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_accounts_emails.py -k reconcile -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add accounts/emails.py tests/test_accounts_emails.py
git commit -m "feat(ws4): reconcile_primary_email helper for settings email change"
```

---

## Task 3: `UserSettingsForm` — email field + `clean_email`

**Files:**
- Modify: `core/forms.py`
- Test: `tests/test_settings_forms.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_forms.py`:

```python
import pytest

from accounts.models import User
from core.forms import UserSettingsForm
from tests.factories import TEST_PASSWORD


def _base(**over):
    data = {"theme": "auto", "language": "en", "display_name": "X", "email": ""}
    data.update(over)
    return data


@pytest.mark.django_db
def test_clean_email_lowercases():
    u = User.objects.create_user(username="lc", password=TEST_PASSWORD)
    form = UserSettingsForm(_base(email="Mixed@Case.EDU"), instance=u)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["email"] == "mixed@case.edu"


@pytest.mark.django_db
def test_clean_email_blank_becomes_none():
    u = User.objects.create_user(username="bk", email="bk@school.edu", password=TEST_PASSWORD)
    form = UserSettingsForm(_base(email="   "), instance=u)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["email"] is None


@pytest.mark.django_db
def test_rejects_duplicate_user_email_path_a():
    # path (a): another User row already holds this email (model unique=True).
    User.objects.create_user(username="other", email="taken@school.edu", password=TEST_PASSWORD)
    u = User.objects.create_user(username="me", password=TEST_PASSWORD)
    form = UserSettingsForm(_base(email="taken@school.edu"), instance=u)
    assert not form.is_valid()
    assert "email" in form.errors


@pytest.mark.django_db
def test_rejects_verified_emailaddress_clash_path_b():
    # path (b): a *verified* allauth EmailAddress on another user (no User.email row).
    from allauth.account.models import EmailAddress

    other = User.objects.create_user(username="o2", password=TEST_PASSWORD)
    EmailAddress.objects.create(user=other, email="held@school.edu", verified=True, primary=True)
    u = User.objects.create_user(username="me2", password=TEST_PASSWORD)
    form = UserSettingsForm(_base(email="held@school.edu"), instance=u)
    assert not form.is_valid()
    assert "email" in form.errors


@pytest.mark.django_db
def test_unchanged_blank_email_is_not_in_changed_data():
    u = User.objects.create_user(username="nb", password=TEST_PASSWORD)  # email NULL at rest
    form = UserSettingsForm(_base(email=""), instance=u)
    assert form.is_valid(), form.errors
    assert "email" not in form.changed_data
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_settings_forms.py -v`
Expected: FAIL — `email` not a form field yet (KeyError/validation differences).

- [ ] **Step 3: Implement the form changes**

In `core/forms.py`, update `UserSettingsForm` (imports + Meta + clean_email):

```python
"""Forms for the core surfaces."""

from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from accounts.provisioning import verified_email_belongs_to_other
from core.services import get_site_config


class UserSettingsForm(forms.ModelForm):
    """Edit the current user's UI prefs + email. `username` is intentionally NOT a
    field (school-assigned, read-only). `language` choices are narrowed at init to
    the institution's enabled languages."""

    class Meta:
        model = User
        fields = ["theme", "language", "display_name", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = dict(settings.LANGUAGES)
        enabled = get_site_config()["enabled_languages"]
        self.fields["language"].choices = [(c, labels.get(c, c)) for c in enabled]

    def clean_email(self):
        # EmailField has already stripped; treat falsy as blank -> None (matches the
        # model's NULL normalization, so changed_data vs initial=None is stable).
        email = self.cleaned_data.get("email")
        if not email:
            return None
        email = email.lower()
        # Path (b): a verified allauth EmailAddress for this address on another user.
        # Reuse the existing guard so ensure_verified_primary_email can never raise.
        if verified_email_belongs_to_other(email, self.instance):
            raise forms.ValidationError(
                _("This email is already in use by another account.")
            )
        return email
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_settings_forms.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add core/forms.py tests/test_settings_forms.py
git commit -m "feat(ws4): UserSettingsForm email field + clean_email (lowercase, clash guard)"
```

---

## Task 4: `InstitutionSettingsForm` — name + logo + `clean_logo` + i18n choices

**Files:**
- Modify: `institution/models.py`
- Modify: `institution/forms.py`
- Test: `tests/test_settings_forms.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings_forms.py`:

```python
import io

from django.core.files.uploadedfile import SimpleUploadedFile

from institution.forms import MAX_LOGO_BYTES, InstitutionSettingsForm
from institution.models import Institution


def _png_upload(name="logo.png", size_pad=0):
    """A real, Pillow-decodable PNG (optionally padded to exceed a size limit)."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buf, "PNG")
    data = buf.getvalue() + (b"\0" * size_pad)
    return SimpleUploadedFile(name, data, content_type="image/png")


def _inst_data(**over):
    data = {
        "name": "Greenfield School",
        "enabled_languages": ["en", "pl"],
        "default_language": "en",
        "default_theme": "auto",
        "signup_policy": "invite",
    }
    data.update(over)
    return data


@pytest.mark.django_db
def test_institution_form_accepts_name_and_logo():
    inst = Institution.load()
    form = InstitutionSettingsForm(
        _inst_data(), {"logo": _png_upload()}, instance=inst
    )
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_institution_form_requires_name():
    inst = Institution.load()
    form = InstitutionSettingsForm(_inst_data(name=""), instance=inst)
    assert not form.is_valid()
    assert "name" in form.errors


@pytest.mark.django_db
def test_clean_logo_rejects_oversized():
    inst = Institution.load()
    big = _png_upload(size_pad=MAX_LOGO_BYTES + 1)
    form = InstitutionSettingsForm(_inst_data(), {"logo": big}, instance=inst)
    assert not form.is_valid()
    assert "logo" in form.errors


@pytest.mark.django_db
def test_logo_clear_checkbox_does_not_raise():
    # No new file + clear set: clean_logo must short-circuit (no .size on False).
    inst = Institution.load()
    form = InstitutionSettingsForm(_inst_data(**{"logo-clear": "on"}), instance=inst)
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_non_image_upload_rejected_by_imagefield():
    inst = Institution.load()
    bogus = SimpleUploadedFile("logo.png", b"not really an image", content_type="image/png")
    form = InstitutionSettingsForm(_inst_data(), {"logo": bogus}, instance=inst)
    assert not form.is_valid()
    assert "logo" in form.errors
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_settings_forms.py -k "institution or logo or name" -v`
Expected: FAIL — `MAX_LOGO_BYTES` / `name`/`logo` not yet on the form.

- [ ] **Step 3: Wrap institution model choice labels in `gettext_lazy`**

In `institution/models.py`, add the import and wrap the display labels (keep the stored codes identical):

```python
from django.db import models
from django.utils.translation import gettext_lazy as _

from institution.validators import validate_css_color
```

Then within `class Institution`:

```python
    SIGNUP_CHOICES = [("invite", _("Invite only")), ("open", _("Open self-signup"))]
    THEME_CHOICES = [("light", _("Light")), ("dark", _("Dark")), ("auto", _("Auto"))]
```

- [ ] **Step 4: Implement the form changes**

Rewrite `institution/forms.py`:

```python
"""Operational institution settings (branding colours admin is Phase 5)."""

from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from institution.models import Institution

MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB


class InstitutionSettingsForm(forms.ModelForm):
    # enabled_languages is a JSONField; a plain ModelForm renders a raw-JSON
    # textarea. Override with a multi-select so it round-trips to a list.
    enabled_languages = forms.MultipleChoiceField(
        choices=settings.LANGUAGES,
        widget=forms.CheckboxSelectMultiple,
        label=_("Enabled languages"),
    )
    # default_language has no model choices; constrain it to the supported set.
    default_language = forms.ChoiceField(
        choices=settings.LANGUAGES, label=_("Default language")
    )

    class Meta:
        model = Institution
        fields = [
            "name",
            "logo",
            "enabled_languages",
            "default_language",
            "default_theme",
            "signup_policy",
        ]

    def clean_enabled_languages(self):
        value = self.cleaned_data["enabled_languages"]
        if not value:
            raise forms.ValidationError(_("Enable at least one language."))
        return value  # a list -> stored in the JSONField

    def clean_logo(self):
        # ClearableFileInput yields False (clear), the unchanged stored file, or
        # None when no new upload. Only an actual upload has .size — short-circuit
        # the rest, or False.size raises AttributeError. ImageField+Pillow already
        # gate non-images by decoding; clean_logo is size-only.
        value = self.cleaned_data.get("logo")
        if not value:  # False (clear), None/"" (no upload) are all falsy -> nothing to size-check
            return value
        if getattr(value, "size", 0) > MAX_LOGO_BYTES:
            raise forms.ValidationError(_("Logo must be 2 MB or smaller."))
        return value

    def clean(self):
        cleaned = super().clean()
        enabled = cleaned.get("enabled_languages") or []
        default = cleaned.get("default_language")
        if default and default not in enabled:
            self.add_error(
                "default_language",
                _("Default language must be an enabled language."),
            )
        return cleaned
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_settings_forms.py tests/test_institution.py -v`
Expected: PASS (settings-forms institution tests pass; existing `test_institution.py` model tests still pass).

- [ ] **Step 6: Commit**

```bash
git add institution/models.py institution/forms.py tests/test_settings_forms.py
git commit -m "feat(ws4): InstitutionSettingsForm name+logo, clean_logo size guard, i18n choices"
```

---

## Task 5: `user_settings` view — SSO context + atomic email sync

**Files:**
- Modify: `core/views.py`
- Test: `tests/test_surfaces.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_surfaces.py`:

```python
@pytest.mark.django_db
def test_user_settings_email_change_syncs_single_primary(client):
    from allauth.account.models import EmailAddress

    user = make_verified_user(username="ec", email="ec-old@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:user_settings"),
        {"theme": "auto", "language": "en", "display_name": "E", "email": "ec-new@school.edu"},
    )
    assert resp.status_code == 302
    user.refresh_from_db()
    assert user.email == "ec-new@school.edu"
    primaries = EmailAddress.objects.filter(user=user, primary=True)
    assert primaries.count() == 1
    assert primaries.first().email == "ec-new@school.edu"


@pytest.mark.django_db
def test_user_settings_clearing_email_deletes_rows(client):
    from allauth.account.models import EmailAddress

    user = make_verified_user(username="cl", email="cl@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:user_settings"),
        {"theme": "auto", "language": "en", "display_name": "C", "email": ""},
    )
    assert resp.status_code == 302
    user.refresh_from_db()
    assert user.email is None
    assert EmailAddress.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_user_settings_sso_badge_context_present(client):
    from allauth.socialaccount.models import SocialAccount

    from tests._sso import make_oidc_app

    app = make_oidc_app()  # provider="openid_connect", provider_id="testidp", name="Test IdP"
    user = make_verified_user(username="ss", email="ss@school.edu")
    SocialAccount.objects.create(
        user=user, provider=app.provider_id, uid="sub-ss", extra_data={"email": "ss@idp.edu"}
    )
    client.force_login(user)
    resp = client.get(reverse("core:user_settings"))
    assert resp.status_code == 200
    assert resp.context["sso_account"] is not None
    assert resp.context["sso_provider_label"] == "Test IdP"


@pytest.mark.django_db
def test_user_settings_no_sso_account(client):
    user = make_verified_user(username="ns", email="ns@school.edu")
    client.force_login(user)
    resp = client.get(reverse("core:user_settings"))
    assert resp.context["sso_account"] is None


@pytest.mark.django_db
def test_user_settings_post_omitting_email_clears_it(client):
    # IMPORTANT semantics: a ModelForm field absent from POST is treated as blank.
    # The real template ALWAYS renders the email input, so a browser submit includes
    # it; but a POST that omits `email` clears it (changed_data fires, rows deleted).
    # This test PINS that behavior so it's intentional, not a surprise.
    from allauth.account.models import EmailAddress

    user = make_verified_user(username="oe", email="oe@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:user_settings"),
        {"theme": "auto", "language": "en", "display_name": "O"},  # no email key
    )
    assert resp.status_code == 302
    user.refresh_from_db()
    assert user.email is None
    assert EmailAddress.objects.filter(user=user).count() == 0
```

- [ ] **Step 1b: Update the two pre-existing user_settings POST tests to carry `email`**

Adding `email` to `UserSettingsForm` (Task 3) changes the contract for **existing** tests in `tests/test_surfaces.py` that POST without it — they would now blank the user's email. Edit both to send the user's current email so they keep testing what they mean to (and don't trip the email-clear path):

In `test_user_settings_post_persists_and_resyncs`, add `"email": "su2@school.edu"` to the POST dict.
In `test_user_settings_rejects_disabled_language`, add `"email": "su3@school.edu"` to the POST dict.

(The usernames/emails match the `make_verified_user(...)` calls already in those tests.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_surfaces.py -k "email_change or clearing_email or sso or omitting_email" -v`
Expected: FAIL — no `sso_account` in context; email not synced.

- [ ] **Step 3: Implement the view**

In `core/views.py`, replace the `user_settings` function with:

```python
@login_required
def user_settings(request):
    """Edit theme/language/display_name/email; re-sync session language + theme
    cookie; keep allauth's primary EmailAddress in step with User.email."""
    from allauth.socialaccount.models import SocialApp

    # SSO badge context — computed on every render path (GET + invalid-POST re-render).
    app = SocialApp.objects.filter(provider="openid_connect").first()
    sso_account = None
    sso_provider_label = None
    if app is not None:
        from allauth.socialaccount.models import SocialAccount

        # SocialAccount.provider stores app.provider_id, NOT "openid_connect".
        sso_account = SocialAccount.objects.filter(
            user=request.user, provider=app.provider_id
        ).first()
        sso_provider_label = app.name or app.provider_id

    if request.method == "POST":
        form = UserSettingsForm(request.POST, instance=request.user)
        if form.is_valid():
            from django.db import transaction

            from accounts.emails import reconcile_primary_email

            with transaction.atomic():
                user = form.save()
                if "email" in form.changed_data:
                    reconcile_primary_email(user)
            request.session[SESSION_KEY] = user.language
            messages.success(request, _("Your settings have been saved."))
            response = redirect("core:user_settings")
            response.set_cookie(
                COOKIE_THEME,
                user.theme,
                max_age=31_536_000,  # ~1 year
                path="/",
                samesite="Lax",
                secure=request.is_secure(),
            )
            return response
    else:
        form = UserSettingsForm(instance=request.user)
    return render(
        request,
        "core/user_settings.html",
        {
            "form": form,
            "sso_account": sso_account,
            "sso_provider_label": sso_provider_label,
        },
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_surfaces.py -k "user_settings or sso or email" -v`
Expected: PASS (new tests + existing `test_user_settings_*` still green).

- [ ] **Step 5: Commit**

```bash
git add core/views.py tests/test_surfaces.py
git commit -m "feat(ws4): user_settings SSO badge context + atomic email/allauth sync"
```

---

## Task 6: `institution_settings` view — accept `request.FILES`

**Files:**
- Modify: `core/views.py`
- Test: `tests/test_surfaces.py`

- [ ] **Step 1: Write the failing test**

> This test is **view/form-level** (POST → DB assertions) and is intentionally independent of the Task 8 template rewrite — it passes against the old `form.as_p` template too, because Task 4 already added `name`/`logo` to the form. It fails here only because the view doesn't yet pass `request.FILES`.

Append to `tests/test_surfaces.py`:

```python
@pytest.mark.django_db
def test_institution_settings_persists_logo(client, tmp_path, settings):
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    from institution.models import Institution

    settings.MEDIA_ROOT = str(tmp_path)  # hermetic media for this test
    user = _make_platform_admin("palogo", "palogo@school.edu")
    client.force_login(user)
    buf = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buf, "PNG")
    upload = SimpleUploadedFile("logo.png", buf.getvalue(), content_type="image/png")
    resp = client.post(
        reverse("core:institution_settings"),
        {
            "name": "Greenfield School",
            "enabled_languages": ["en", "pl"],
            "default_language": "en",
            "default_theme": "auto",
            "signup_policy": "invite",
            "logo": upload,
        },
    )
    assert resp.status_code == 302
    inst = Institution.load()
    assert inst.name == "Greenfield School"
    assert inst.logo.name.startswith("branding/")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_surfaces.py -k persists_logo -v`
Expected: FAIL — `request.FILES` not passed, so `logo` never binds (logo stays empty / 200 re-render).

- [ ] **Step 3: Implement the view change**

In `core/views.py`, update `institution_settings`'s POST line:

```python
    if request.method == "POST":
        form = InstitutionSettingsForm(request.POST, request.FILES, instance=inst)
```

(Leave the rest of `institution_settings` unchanged.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_surfaces.py -k "institution_settings or persists_logo" -v`
Expected: PASS (new logo test + existing institution view tests).

- [ ] **Step 5: Commit**

```bash
git add core/views.py tests/test_surfaces.py
git commit -m "feat(ws4): institution_settings accepts request.FILES (logo upload)"
```

---

## Task 7: Rewrite `user_settings.html` + shared theme-tiles partial

**Files:**
- Create: `templates/core/_theme_tiles.html`
- Rewrite: `templates/core/user_settings.html`
- Test: `tests/test_surfaces.py`

- [ ] **Step 1: Write the failing render tests**

Append to `tests/test_surfaces.py`:

```python
@pytest.mark.django_db
def test_user_settings_renders_controls_not_select(client):
    import re

    user = make_verified_user(username="rc2", email="rc2@school.edu")
    client.force_login(user)
    body = client.get(reverse("core:user_settings")).content
    assert b"<select" not in body  # no raw dropdowns
    assert b'class="seg"' in body  # language segmented control
    assert b'class="tile"' in body  # theme tiles
    assert b"core/css/settings.css" in body
    # the model default theme ("auto") must render as the *checked* tile on first GET
    # (guards against field.value being unmatched -> no selected control)
    assert re.search(r'value="auto"[^>]*checked', body.decode())


@pytest.mark.django_db
def test_user_settings_badge_connected_string(client):
    from allauth.socialaccount.models import SocialAccount

    from tests._sso import make_oidc_app

    app = make_oidc_app()
    user = make_verified_user(username="bc", email="bc@school.edu")
    SocialAccount.objects.create(
        user=user, provider=app.provider_id, uid="sub-bc", extra_data={"email": "bc@idp.edu"}
    )
    client.force_login(user)
    body = client.get(reverse("core:user_settings")).content
    assert b"bc@idp.edu" in body  # extra_data email rendered in the badge
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_surfaces.py -k "renders_controls or badge_connected" -v`
Expected: FAIL — old template still renders `form.as_p` (`<select>` present, no `.seg`/`.tile`).

- [ ] **Step 3: Create the shared theme-tiles partial**

Create `templates/core/_theme_tiles.html` (the literal-hex SVG previews are theme-independent — they *show* what each theme looks like; copy them verbatim from `docs/mockups/settings_redesign_accepted.html`). Usage: `{% include "core/_theme_tiles.html" with field=form.theme name="theme" %}`.

```django
{% load i18n %}
<div class="tiles" role="radiogroup">
  <label class="tile">
    <input class="vh" type="radio" name="{{ name }}" value="light"
      {% if field.value == "light" %}checked{% endif %}>
    <svg viewBox="0 0 160 100" aria-hidden="true">
      <rect width="160" height="100" fill="#F4F1EA"/><rect width="160" height="16" fill="#FFFFFF"/>
      <line x1="0" y1="16" x2="160" y2="16" stroke="#E4DFD4"/><circle cx="11" cy="8" r="3" fill="#147E78"/>
      <rect x="20" y="30" width="120" height="58" rx="4" fill="#FAF8F3" stroke="#E4DFD4"/>
      <line x1="30" y1="44" x2="125" y2="44" stroke="#D1CABD"/><line x1="30" y1="56" x2="110" y2="56" stroke="#E4DFD4"/>
    </svg>
    <span class="tile-label">{% trans "Light" %}</span>
  </label>
  <label class="tile">
    <input class="vh" type="radio" name="{{ name }}" value="dark"
      {% if field.value == "dark" %}checked{% endif %}>
    <svg viewBox="0 0 160 100" aria-hidden="true">
      <rect width="160" height="100" fill="#1A1816"/><rect width="160" height="16" fill="#2C2925"/>
      <line x1="0" y1="16" x2="160" y2="16" stroke="#322E29"/><circle cx="11" cy="8" r="3" fill="#4FB3AC"/>
      <rect x="20" y="30" width="120" height="58" rx="4" fill="#23201C" stroke="#322E29"/>
      <line x1="30" y1="44" x2="125" y2="44" stroke="#4A4036"/><line x1="30" y1="56" x2="110" y2="56" stroke="#322E29"/>
    </svg>
    <span class="tile-label">{% trans "Dark" %}</span>
  </label>
  <label class="tile">
    <input class="vh" type="radio" name="{{ name }}" value="auto"
      {% if field.value == "auto" %}checked{% endif %}>
    <svg viewBox="0 0 160 100" aria-hidden="true">
      <defs><clipPath id="lh-{{ name }}"><rect width="80" height="100"/></clipPath>
        <clipPath id="rh-{{ name }}"><rect x="80" width="80" height="100"/></clipPath></defs>
      <g clip-path="url(#lh-{{ name }})"><rect width="160" height="100" fill="#F4F1EA"/>
        <rect width="160" height="16" fill="#FFFFFF"/>
        <rect x="20" y="30" width="120" height="58" rx="4" fill="#FAF8F3" stroke="#E4DFD4"/>
        <line x1="30" y1="44" x2="125" y2="44" stroke="#D1CABD"/></g>
      <g clip-path="url(#rh-{{ name }})"><rect width="160" height="100" fill="#1A1816"/>
        <rect width="160" height="16" fill="#2C2925"/>
        <rect x="20" y="30" width="120" height="58" rx="4" fill="#23201C" stroke="#322E29"/>
        <line x1="30" y1="44" x2="125" y2="44" stroke="#4A4036"/></g>
      <line x1="80" y1="0" x2="80" y2="100" stroke="#A8A090" stroke-dasharray="3 3"/>
    </svg>
    <span class="tile-label">{% trans "Auto" %}</span>
  </label>
</div>
```

- [ ] **Step 4: Rewrite `templates/core/user_settings.html`**

```django
{% extends "base.html" %}
{% load i18n static %}
{% block head_title %}{% trans "Settings" %} · libli{% endblock %}
{% block extra_css %}<link rel="stylesheet" href="{% static 'core/css/settings.css' %}">{% endblock %}
{% block content %}
<div class="settings-wrap">
  <div class="page-head">
    <h1 class="page-title">{% trans "Settings" %}</h1>
    <p class="page-meta">{% trans "Manage your account and preferences." %}</p>
  </div>

  <form method="post">
    {% csrf_token %}
    {% if form.non_field_errors %}<div class="alert alert--error">{{ form.non_field_errors }}</div>{% endif %}

    <section class="settings-section">
      <h2 class="settings-sec-title">{% trans "Profile" %}</h2>
      <p class="settings-sec-lede">{% trans "How you appear in libli, and the email we use for password resets." %}</p>

      <div class="settings-field">
        <div>
          <div class="settings-field-label">{% trans "Display name" %}</div>
          <p class="settings-field-help">{% trans "Shown as the author on content you create." %}</p>
        </div>
        <div class="settings-field-control">
          <input type="text" name="display_name" value="{{ form.display_name.value|default:'' }}">
          {{ form.display_name.errors }}
        </div>
      </div>

      <div class="settings-field">
        <div>
          <div class="settings-field-label">{% trans "Username" %}</div>
          <p class="settings-field-help">{% trans "Set by your school — can’t be changed here." %}</p>
        </div>
        <div class="settings-field-control">
          <input class="input--readonly" type="text" value="{{ user.username }}" readonly>
        </div>
      </div>

      <div class="settings-field">
        <div>
          <div class="settings-field-label">{% trans "Email" %}</div>
          <p class="settings-field-help">{% trans "Used for password resets and notices. Optional for class accounts." %}</p>
        </div>
        <div class="settings-field-control">
          <input type="email" name="email" value="{{ form.email.value|default:'' }}">
          {{ form.email.errors }}
        </div>
      </div>
    </section>

    <section class="settings-section">
      <h2 class="settings-sec-title">{% trans "Preferences" %}</h2>
      <p class="settings-sec-lede">{% trans "Applies to your view of libli on this account." %}</p>

      <div class="settings-field">
        <div>
          <div class="settings-field-label">{% trans "Language" %}</div>
          <p class="settings-field-help">{% trans "Interface language. Content stays in whatever language it was written." %}</p>
        </div>
        <div class="settings-field-control">
          <div class="seg" role="radiogroup">
            {% for value, label in form.language.field.choices %}
              <label><input class="vh" type="radio" name="language" value="{{ value }}"
                {% if form.language.value == value %}checked{% endif %}><span>{{ label }}</span></label>
            {% endfor %}
          </div>
          {{ form.language.errors }}
        </div>
      </div>

      <div class="settings-field">
        <div>
          <div class="settings-field-label">{% trans "Theme" %}</div>
          <p class="settings-field-help">{% trans "“Auto” follows your device’s light/dark setting." %}</p>
        </div>
        <div class="settings-field-control">
          {% include "core/_theme_tiles.html" with field=form.theme name="theme" %}
          {{ form.theme.errors }}
        </div>
      </div>
    </section>

    <section class="settings-section">
      <h2 class="settings-sec-title">{% trans "Security" %}</h2>
      <p class="settings-sec-lede">{% trans "Keep your account safe. Passwords are hashed server-side." %}</p>

      <div class="settings-srow">
        <div>
          <div class="k">{% trans "Password" %}</div>
          <div class="d">{% trans "Sign in to libli with a password." %}</div>
        </div>
        {% if user.has_usable_password %}
          <a class="btn btn--ghost btn--small" href="{% url 'account_change_password' %}">{% trans "Change password…" %}</a>
        {% else %}
          <a class="btn btn--ghost btn--small" href="{% url 'account_set_password' %}">{% trans "Set password…" %}</a>
        {% endif %}
      </div>

      {% trans "Single sign-on" as default_sso %}
      <div class="settings-srow">
        <div>
          <div class="k">{% blocktrans with provider=sso_provider_label|default:default_sso %}{{ provider }} sign-in{% endblocktrans %}</div>
          <div class="d">{% if sso_account %}{{ sso_account.extra_data.email|default:sso_account.uid }}{% else %}{% trans "Not connected" %}{% endif %}</div>
        </div>
        {% if sso_account %}
          <span class="settings-badge">● {% trans "Connected" %}</span>
        {% else %}
          <span class="settings-badge is-off">{% trans "Not connected" %}</span>
        {% endif %}
      </div>
    </section>

    <div class="settings-save-bar">
      <a class="btn btn--ghost" href="{% url 'home' %}">{% trans "Cancel" %}</a>
      <button class="btn" type="submit">{% trans "Save changes" %}</button>
    </div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_surfaces.py tests/test_settings_styles.py -k "user_settings or renders_controls or badge or link_settings_css" -v`
Expected: PASS — controls render, badge string present, template links settings.css.

- [ ] **Step 6: Commit**

```bash
git add templates/core/_theme_tiles.html templates/core/user_settings.html tests/test_surfaces.py
git commit -m "feat(ws4): rewrite user_settings.html with friendly controls + security section"
```

---

## Task 8: Rewrite `institution_settings.html`

**Files:**
- Rewrite: `templates/core/institution_settings.html`
- Test: `tests/test_surfaces.py`

- [ ] **Step 1: Write the failing render tests**

Append to `tests/test_surfaces.py`:

```python
@pytest.mark.django_db
def test_institution_settings_renders_controls_not_select(client):
    import re

    user = _make_platform_admin("ic", "ic@school.edu")
    client.force_login(user)
    text = client.get(reverse("core:institution_settings")).content.decode()
    assert "<select" not in text
    for cls in ('class="chip"', 'class="seg"', 'class="tile"', 'class="rcard"'):
        assert cls in text
    assert 'enctype="multipart/form-data"' in text
    assert "core/css/settings.css" in text
    # the currently-enabled languages (default ["en","pl"]) render as CHECKED chips —
    # pins the `value in form.enabled_languages.value` membership comparison
    assert re.search(r'name="enabled_languages" value="en"[^>]*checked', text)
    assert re.search(r'name="enabled_languages" value="pl"[^>]*checked', text)


@pytest.mark.django_db
def test_institution_default_language_not_in_enabled_renders_and_errors(client):
    # Spec Area C no-JS baseline: a stored default_language outside the enabled set
    # still renders as the checked segment (never silently lost), and the invalid
    # combo re-renders 200 with the clean() field error.
    import re

    from institution.models import Institution

    inst = Institution.load()
    inst.enabled_languages = ["en"]
    inst.default_language = "pl"  # out of enabled (no model-level constraint)
    inst.save()
    user = _make_platform_admin("dn", "dn@school.edu")
    client.force_login(user)
    text = client.get(reverse("core:institution_settings")).content.decode()
    assert re.search(r'name="default_language" value="pl"[^>]*checked', text)
    resp = client.post(
        reverse("core:institution_settings"),
        {"name": "X", "enabled_languages": ["en"], "default_language": "pl",
         "default_theme": "auto", "signup_policy": "invite"},
    )
    assert resp.status_code == 200
    assert b"enabled language" in resp.content.lower()


@pytest.mark.django_db
def test_institution_settings_invalid_post_rerenders_bound(client):
    user = _make_platform_admin("iv", "iv@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:institution_settings"),
        {"name": "", "enabled_languages": ["en"], "default_language": "en",
         "default_theme": "auto", "signup_policy": "invite"},
    )
    assert resp.status_code == 200  # re-render, not redirect
    assert b"<select" not in resp.content  # still the styled controls, bound
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_surfaces.py -k "institution_settings_renders or invalid_post_rerenders" -v`
Expected: FAIL — old template uses `form.as_p`.

- [ ] **Step 3: Rewrite `templates/core/institution_settings.html`**

```django
{% extends "base.html" %}
{% load i18n static %}
{% block head_title %}{% trans "Institution settings" %} · libli{% endblock %}
{% block extra_css %}<link rel="stylesheet" href="{% static 'core/css/settings.css' %}">{% endblock %}
{% block content %}
<div class="settings-wrap">
  <div class="page-head">
    <h1 class="page-title">{% trans "Institution settings" %}<span class="settings-admin-badge">{% trans "Admin" %}</span></h1>
    <p class="page-meta">{% trans "Defaults and policy for everyone at your institution." %}</p>
  </div>

  <form method="post" enctype="multipart/form-data">
    {% csrf_token %}
    {% if form.non_field_errors %}<div class="alert alert--error">{{ form.non_field_errors }}</div>{% endif %}

    <section class="settings-section">
      <h2 class="settings-sec-title">{% trans "Identity" %}</h2>
      <p class="settings-sec-lede">{% trans "Your institution’s name and logo, shown across libli." %}</p>

      <div class="settings-field">
        <div>
          <div class="settings-field-label">{% trans "Name" %}</div>
          <p class="settings-field-help">{% trans "Displayed on sign-in, invites, and the app header." %}</p>
        </div>
        <div class="settings-field-control">
          <input type="text" name="name" value="{{ form.name.value|default:'' }}">
          {{ form.name.errors }}
        </div>
      </div>

      <div class="settings-field">
        <div>
          <div class="settings-field-label">{% trans "Logo" %}</div>
          <p class="settings-field-help">{% trans "PNG or SVG, square works best. Optional." %}</p>
        </div>
        <div class="settings-field-control">
          <div class="settings-logo-row">
            <div class="settings-logo-prev">
              {% if form.instance.logo %}<img src="{{ form.instance.logo.url }}" alt="">
              {% else %}{{ form.instance.name|slice:":2"|upper }}{% endif %}
            </div>
            <div class="settings-logo-actions">{{ form.logo }}</div>
          </div>
          {{ form.logo.errors }}
        </div>
      </div>
    </section>

    <section class="settings-section">
      <h2 class="settings-sec-title">{% trans "Languages" %}</h2>
      <p class="settings-sec-lede">{% trans "Which interface languages people can choose, and the default for new accounts." %}</p>

      <div class="settings-field">
        <div>
          <div class="settings-field-label">{% trans "Enabled languages" %}</div>
          <p class="settings-field-help">{% trans "At least one must stay enabled." %}</p>
        </div>
        <div class="settings-field-control">
          <div class="chips" role="group">
            {% for value, label in form.enabled_languages.field.choices %}
              <label class="chip"><input class="vh" type="checkbox" name="enabled_languages" value="{{ value }}"
                {% if value in form.enabled_languages.value %}checked{% endif %}><span class="tick">✓</span> {{ label }}</label>
            {% endfor %}
          </div>
          {{ form.enabled_languages.errors }}
        </div>
      </div>

      <div class="settings-field">
        <div>
          <div class="settings-field-label">{% trans "Default language" %}</div>
          <p class="settings-field-help">{% trans "Used for new accounts and signed-out pages. Must be an enabled language." %}</p>
        </div>
        <div class="settings-field-control">
          <div class="seg" role="radiogroup">
            {% for value, label in form.default_language.field.choices %}
              <label><input class="vh" type="radio" name="default_language" value="{{ value }}"
                {% if form.default_language.value == value %}checked{% endif %}><span>{{ label }}</span></label>
            {% endfor %}
          </div>
          {{ form.default_language.errors }}
        </div>
      </div>
    </section>

    <section class="settings-section">
      <h2 class="settings-sec-title">{% trans "Appearance" %}</h2>
      <p class="settings-sec-lede">{% trans "The starting theme for new accounts. Each person can still change their own." %}</p>

      <div class="settings-field">
        <div>
          <div class="settings-field-label">{% trans "Default theme" %}</div>
          <p class="settings-field-help">{% trans "“Auto” follows each device’s light/dark setting." %}</p>
        </div>
        <div class="settings-field-control">
          {% include "core/_theme_tiles.html" with field=form.default_theme name="default_theme" %}
          {{ form.default_theme.errors }}
        </div>
      </div>
    </section>

    <section class="settings-section">
      <h2 class="settings-sec-title">{% trans "Access" %}</h2>
      <p class="settings-sec-lede">{% trans "How new people get into libli." %}</p>

      <div class="settings-field">
        <div>
          <div class="settings-field-label">{% trans "Sign-up policy" %}</div>
          <p class="settings-field-help">{% trans "Controls who can create an account." %}</p>
        </div>
        <div class="settings-field-control">
          <div class="radio-cards" role="radiogroup">
            <label class="rcard">
              <input class="vh" type="radio" name="signup_policy" value="invite"
                {% if form.signup_policy.value == "invite" %}checked{% endif %}>
              <span class="dot"></span>
              <span><span class="rc-title">{% trans "Invite only" %}</span>
                <span class="rc-desc">{% trans "People join only via an invite link or code an admin sends." %}</span></span>
            </label>
            <label class="rcard">
              <input class="vh" type="radio" name="signup_policy" value="open"
                {% if form.signup_policy.value == "open" %}checked{% endif %}>
              <span class="dot"></span>
              <span><span class="rc-title">{% trans "Open self-signup" %}</span>
                <span class="rc-desc">{% trans "Anyone with a confirmed email can create their own account." %}</span></span>
            </label>
          </div>
          {{ form.signup_policy.errors }}
        </div>
      </div>
    </section>

    <div class="settings-save-bar">
      <a class="btn btn--ghost" href="{% url 'home' %}">{% trans "Cancel" %}</a>
      <button class="btn" type="submit">{% trans "Save changes" %}</button>
    </div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_surfaces.py tests/test_settings_styles.py -v`
Expected: PASS — both render tests + the style-guard `test_both_templates_link_settings_css` now green.

- [ ] **Step 5: Commit**

```bash
git add templates/core/institution_settings.html tests/test_surfaces.py
git commit -m "feat(ws4): rewrite institution_settings.html with friendly controls + logo"
```

---

## Task 9: i18n — extract & translate WS4 strings to PL

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- (Strings already wrapped in Tasks 3–8.)

- [ ] **Step 1: Baseline the PL catalog before adding strings**

Run (Bash tool — POSIX):
```bash
grep -c 'msgstr ""' locale/pl/LC_MESSAGES/django.po
grep -c '#, fuzzy' locale/pl/LC_MESSAGES/django.po
```
Record both counts (the done-gate is scoped to WS4 strings; pre-existing empties are a known baseline, not in scope).

- [ ] **Step 2: Extract messages**

Run: `uv run python manage.py makemessages -l pl`
Expected: `locale/pl/LC_MESSAGES/django.po` gains new `msgid`s for the WS4 labels/help/buttons (e.g. "Manage your account and preferences.", "Display name", "Default language", "Invite only", …). Note: `settings.LANGUAGES` labels ("English", "Polski") are already wrapped in `config/settings/base.py` — confirm they appear/are already translated; if they don't extract, that's the documented settings-scan caveat (spec i18n note) — they fall back to Django's built-in language-name translations, which is acceptable.

- [ ] **Step 3: Translate every new WS4 `msgid`**

Edit `locale/pl/LC_MESSAGES/django.po` — fill the `msgstr ""` for each new WS4 entry with the Polish translation, and clear any `#, fuzzy` flags on WS4 entries. (Reuse existing translations for shared msgids like "Save"/"Change password" — makemessages merges them automatically.)

- [ ] **Step 4: Compile**

Run: `uv run python manage.py compilemessages -l pl`
Expected: exits 0, writes `locale/pl/LC_MESSAGES/django.mo`.

- [ ] **Step 5: Gate per-WS4-msgid (not on aggregate counts)**

An aggregate `msgstr ""` count can stay flat while a WS4 string is untranslated (makemessages also obsoletes old entries), so gate on the *specific* WS4 msgids. Create `tests/test_i18n_ws4.py`:

```python
"""Done-gate: every WS4 settings string must be translated to PL.

Gates on the exact msgids introduced by Tasks 7-8 (NOT an aggregate empty-count
delta, which can mask a new untranslated string). Reused/pre-existing msgids
(Save changes / Cancel / Settings / Light / Dark / Auto / English / Polski) are
deliberately excluded — they were translated in earlier work.
"""

import pytest
from django.utils import translation

WS4_NEW_MSGIDS = [
    # user_settings.html
    "Manage your account and preferences.",
    "How you appear in libli, and the email we use for password resets.",
    "Display name",
    "Shown as the author on content you create.",
    "Set by your school — can’t be changed here.",
    "Used for password resets and notices. Optional for class accounts.",
    "Applies to your view of libli on this account.",
    "Interface language. Content stays in whatever language it was written.",
    "“Auto” follows your device’s light/dark setting.",
    "Keep your account safe. Passwords are hashed server-side.",
    "Change password…",
    "Set password…",
    "Not connected",
    # institution_settings.html
    "Defaults and policy for everyone at your institution.",
    "Your institution’s name and logo, shown across libli.",
    "Displayed on sign-in, invites, and the app header.",
    "PNG or SVG, square works best. Optional.",
    "Which interface languages people can choose, and the default for new accounts.",
    "Enabled languages",
    "At least one must stay enabled.",
    "Default language",
    "Used for new accounts and signed-out pages. Must be an enabled language.",
    "The starting theme for new accounts. Each person can still change their own.",
    "Default theme",
    "“Auto” follows each device’s light/dark setting.",
    "How new people get into libli.",
    "Sign-up policy",
    "Controls who can create an account.",
    "People join only via an invite link or code an admin sends.",
    "Anyone with a confirmed email can create their own account.",
    # form/model choice labels (institution/models.py + institution/forms.py)
    "Invite only",
    "Open self-signup",
    "Logo must be 2 MB or smaller.",
    "This email is already in use by another account.",
]


@pytest.mark.parametrize("msgid", WS4_NEW_MSGIDS)
def test_ws4_msgid_translated_to_pl(msgid):
    with translation.override("pl"):
        out = translation.gettext(msgid)
    assert out and out != msgid, f"WS4 msgid not translated to PL: {msgid!r}"
```

Run: `uv run pytest tests/test_i18n_ws4.py -v`
Expected: each parametrized case PASS (every WS4 msgid returns a non-English Polish string). Any FAIL names the exact untranslated msgid — go back to Step 3 and translate it.

> Keep `WS4_NEW_MSGIDS` in sync with the literal English strings you actually wrote in Tasks 3–8; the list above must match them character-for-character (curly quotes, em dashes, the trailing `…`). If you reworded any string, update both.

- [ ] **Step 6: Spot-check rendering after string changes**

Run: `uv run pytest tests/test_surfaces.py -k "renders_controls" -v` (sanity that templates still render).

- [ ] **Step 7: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_i18n_ws4.py
git commit -m "i18n(ws4): Polish for settings redesign strings + per-msgid gate"
```

---

## Task 10: e2e — controls render, submit, round-trip (light + dark)

**Files:**
- Create: `tests/test_e2e_settings.py`

- [ ] **Step 1: Write the e2e test**

Create `tests/test_e2e_settings.py`:

```python
"""Playwright e2e for WS4 settings redesign. Marked e2e (run with -m e2e).
Mirrors tests/test_e2e_editor_ws3.py: session async-ORM fixture + allauth login."""

import os

import pytest

from tests.factories import TEST_PASSWORD, make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa(username):
    # NOTE: factories.make_pa(client, username) takes a test *client* (it force_logins);
    # e2e drives a real browser via Playwright login, so we need a client-less variant.
    # That's why this re-declares the PA setup instead of reusing factories.make_pa.
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN, seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def test_user_settings_controls_and_roundtrip(page, live_server):
    make_verified_user(username="e2eu", email="e2eu@t.example.com", password=TEST_PASSWORD)
    _login(page, live_server, "e2eu")
    page.goto(f"{live_server.url}/settings/")
    # styled controls present, no raw <select>
    assert page.locator("select").count() == 0
    assert page.locator(".seg").count() >= 1
    assert page.locator(".tile").count() >= 1
    # pick Polski + dark, save, reload, assert it stuck
    page.locator('.seg input[value="pl"]').check(force=True)
    page.locator('.tile input[value="dark"]').check(force=True)
    page.locator('button[type="submit"]').click()
    page.goto(f"{live_server.url}/settings/")
    assert page.locator('.seg input[value="pl"]').is_checked()
    assert page.locator('.tile input[value="dark"]').is_checked()


def test_institution_settings_controls(page, live_server):
    _make_pa("e2epa")
    _login(page, live_server, "e2epa")
    page.goto(f"{live_server.url}/settings/institution/")
    assert page.locator("select").count() == 0
    for sel in (".chip", ".seg", ".tile", ".rcard"):
        assert page.locator(sel).count() >= 1, f"missing {sel}"
```

- [ ] **Step 2: Run the e2e suite**

Run: `uv run pytest -m e2e tests/test_e2e_settings.py -v`
Expected: PASS (2 tests). If Playwright browsers aren't installed: `uv run playwright install chromium` first.

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_settings.py
git commit -m "test(ws4): e2e settings controls render + round-trip"
```

---

## Task 11 (optional): progressive-enhancement JS

Only do this if time allows — the no-JS baseline is the contract.

**Files:**
- Create: `core/static/core/js/settings.js`
- Modify: `templates/core/institution_settings.html` (add `{% block extra_js %}`)

- [ ] **Step 1: Create `core/static/core/js/settings.js`**

```javascript
// Progressive enhancement for institution settings (no-JS baseline already works):
// grey out default_language segments whose language isn't currently enabled, and
// swap the logo thumbnail when a new file is picked.
(function () {
  "use strict";
  function syncDefaultLang() {
    var enabled = {};
    document.querySelectorAll('input[name="enabled_languages"]').forEach(function (cb) {
      enabled[cb.value] = cb.checked;
    });
    document.querySelectorAll('.seg input[name="default_language"]').forEach(function (r) {
      r.closest("label").style.opacity = enabled[r.value] ? "" : ".45";
    });
  }
  document.querySelectorAll('input[name="enabled_languages"]').forEach(function (cb) {
    cb.addEventListener("change", syncDefaultLang);
  });
  syncDefaultLang();

  var fileInput = document.querySelector('.settings-logo-actions input[type=file]');
  var prev = document.querySelector(".settings-logo-prev");
  if (fileInput && prev) {
    fileInput.addEventListener("change", function () {
      if (fileInput.files && fileInput.files[0]) {
        var url = URL.createObjectURL(fileInput.files[0]);
        prev.innerHTML = '<img src="' + url + '" alt="">';
      }
    });
  }
})();
```

- [ ] **Step 2: Wire it into the institution template**

Add to `templates/core/institution_settings.html` before `{% endblock %}` of content (or as a dedicated block):

```django
{% block extra_js %}<script src="{% static 'core/js/settings.js' %}" defer></script>{% endblock %}
```

- [ ] **Step 3: Manual check + commit**

Run: `uv run pytest tests/test_surfaces.py -k institution_settings -v` (regression — page still renders).

```bash
git add core/static/core/js/settings.js templates/core/institution_settings.html
git commit -m "feat(ws4): optional JS — default-language greying + logo preview"
```

---

## Final verification (Done-gate)

- [ ] **Full unit suite green:** `uv run pytest -q`
- [ ] **e2e green:** `uv run pytest -m e2e tests/test_e2e_settings.py -v`
- [ ] **Lint clean:** `uv run ruff check .` and `uv run ruff format --check .`
- [ ] **No raw `form.as_p`:** `grep -rn "form.as_p" templates/core/` returns nothing.
- [ ] **PL catalog WS4 slice clean** (Task 9 Step 4 baseline holds).
- [ ] **Owed to user (manual):** open `/settings/` and `/settings/institution/` in a browser, in **both** light and dark, and confirm every control is readable and the selected state is visible (per the triage "visual confirmation owed by user" gate). Cross-check against `docs/mockups/settings_redesign_accepted.html`.

---

## Notes for the implementer

- **`{% load static %}` placement:** both templates put `{% load i18n static %}` at the top (after `{% extends %}`), so `{% static 'core/css/settings.css' %}` in `{% block extra_css %}` resolves — never an inline `{% load %}` inside an attribute.
- **`form.<field>.value`** returns the bound value on a re-rendered POST and the instance/initial value on GET — that's why the manual radio/checkbox `checked` comparisons round-trip correctly on validation errors.
- **`{{ form.logo }}`** renders allauth-free Django's `ClearableFileInput`, which emits `name="logo"` (file) and, when a logo exists, `name="logo-clear"` (checkbox) — do **not** hand-roll these; the view's `request.FILES` + the clear name are what make upload/remove round-trip.
- **`verified_email_belongs_to_other(email, user)`** lives in `accounts/provisioning.py` and takes `(email, user)` in that order — don't swap the args.
- **Do not** add a migration: `User.email`, `Institution.name`, `Institution.logo` already exist.
