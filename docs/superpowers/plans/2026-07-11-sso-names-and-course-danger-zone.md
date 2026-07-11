# SSO Name Capture + PA Name Editing + Course Danger Zone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate `first_name`/`last_name` from SSO on every login (PA-overridable via a lock), let a Platform Admin edit both names, and make course deletion clearly destructive via a "Danger zone" with a properly-red Delete button; add a flattening note to the depth picker.

**Architecture:** A new `User.names_locked` flag plus a pure `apply_sso_names` helper wired to two allauth signals covers name sync across the three login paths. `UserEditForm` gains name fields and a conditional sync-lock checkbox driven purely by field presence. `.btn--danger` is promoted from `people.css` to the global `app.css` (fixing several confirm pages at once), and the course-edit template grows a `.danger-zone` section. The depth note is appended to the `structure` field's help text.

**Tech Stack:** Django, django-allauth 65.18.0 (`openid_connect` provider), pytest, bespoke token-driven CSS (no framework).

## Global Constraints

- **allauth 65.18.0**, provider `openid_connect`. Its `SocialAccount.extra_data` is **nested**: `{"userinfo": {…}, "id_token": {…}}`. OIDC name claims (`given_name`, `family_name`) live inside `userinfo`/`id_token`, never at top level.
- **Tooling runs via `uv run`** — bash `ruff`/`pytest`/`python` are NOT on PATH. Use `uv run pytest …`, `uv run python manage.py …`, `uv run ruff …`.
- **All new user-facing strings are translatable** (`gettext`/`gettext_lazy` in Python, `{% trans %}` in templates) and added to both EN and PL catalogs (`locale/en`, `locale/pl`). Watch the makemessages fuzzy-flag gotcha; the i18n catalog tests must stay green.
- **No hardcoded test passwords** — use `tests.factories.TEST_PASSWORD` (GitGuardian CI flags new password literals).
- **Django `{# #}` comments must be single-line**; use `{% comment %}…{% endcomment %}` for multi-line, or it renders as visible text.
- **Do not change** the label-display precedence (`User.list_display_name` / `sort_name`), the course-delete cascade, or the flattening guard in `CourseForm.clean()`.
- **No new Playwright e2e** — Django test-client + unit tests only (per the project's e2e-runaway lesson). Full suite green + `uv run ruff check` + `uv run ruff format --check` is the definition of done.

---

### Task 1: `User.names_locked` field + migration

**Files:**
- Modify: `accounts/models.py` (the `User` model, after the `theme` field ~line 29)
- Create: `accounts/migrations/0006_user_names_locked.py` (via makemigrations)
- Test: `tests/test_names_locked_model.py`

**Interfaces:**
- Produces: `User.names_locked: bool` (BooleanField, default `False`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_names_locked_model.py
import pytest


@pytest.mark.django_db
def test_names_locked_defaults_false_and_is_settable():
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(username="nl", password=TEST_PASSWORD)
    assert u.names_locked is False
    u.names_locked = True
    u.save(update_fields=["names_locked"])
    u.refresh_from_db()
    assert u.names_locked is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_names_locked_model.py -v`
Expected: FAIL — `names_locked` is not a field / no such column.

- [ ] **Step 3: Add the field**

In `accounts/models.py`, immediately after the `theme` field:

```python
    theme = models.CharField(max_length=5, choices=THEME_CHOICES, default="auto")
    # When True, a PA has pinned first_name/last_name manually and SSO must not
    # overwrite them (accounts.provisioning.apply_sso_names honors this). Default
    # False keeps everyone in sync with the IdP.
    names_locked = models.BooleanField(default=False)
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations accounts`
Expected: creates `accounts/migrations/0006_user_names_locked.py` adding `names_locked` (depends on `0005_user_external_id`). Verify the filename is exactly `0006_user_names_locked.py`; rename if makemigrations chose a different suffix.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_names_locked_model.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add accounts/models.py accounts/migrations/0006_user_names_locked.py tests/test_names_locked_model.py
git commit -m "feat(accounts): add User.names_locked flag for SSO name pinning"
```

---

### Task 2: `apply_sso_names` + `_claims` unwrap helper

**Files:**
- Modify: `accounts/provisioning.py` (append helpers)
- Test: `tests/test_sso_name_sync.py`

**Interfaces:**
- Consumes: `User.names_locked` (Task 1).
- Produces:
  - `_claims(extra_data) -> dict` — unwraps nested OIDC `extra_data` to the flat claim set (mirrors the provider's `_pick_data`: `userinfo` → `id_token` → top-level; None-tolerant).
  - `apply_sso_names(user, sociallogin) -> None` — syncs `first_name`/`last_name` from `given_name`/`family_name` unless `user.names_locked`; never overwrites with a blank; saves only changed fields.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sso_name_sync.py
from types import SimpleNamespace

import pytest


def _sl(extra_data):
    """A minimal stand-in for a SocialLogin: apply_sso_names only reads
    sociallogin.account.extra_data."""
    return SimpleNamespace(account=SimpleNamespace(extra_data=extra_data))


def _nested(given=None, family=None):
    ui = {}
    if given is not None:
        ui["given_name"] = given
    if family is not None:
        ui["family_name"] = family
    return {"userinfo": ui, "id_token": {}}


@pytest.mark.django_db
def test_unlocked_user_gets_names_from_nested_claims():
    from accounts.provisioning import apply_sso_names
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(username="a", password=TEST_PASSWORD)
    apply_sso_names(u, _sl(_nested("Ada", "Lovelace")))
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Ada", "Lovelace")


@pytest.mark.django_db
def test_locked_user_is_never_modified():
    from accounts.provisioning import apply_sso_names
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(
        username="b", password=TEST_PASSWORD, first_name="Keep", last_name="Me"
    )
    u.names_locked = True
    u.save(update_fields=["names_locked"])
    apply_sso_names(u, _sl(_nested("New", "Name")))
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Keep", "Me")


@pytest.mark.django_db
def test_blank_or_missing_claims_never_overwrite():
    from accounts.provisioning import apply_sso_names
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(
        username="c", password=TEST_PASSWORD, first_name="Old", last_name="Value"
    )
    apply_sso_names(u, _sl(_nested(given="  ", family=None)))  # blank + absent
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Old", "Value")


@pytest.mark.django_db
def test_partial_claim_updates_only_that_field():
    from accounts.provisioning import apply_sso_names
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(
        username="d", password=TEST_PASSWORD, first_name="F", last_name="Stay"
    )
    apply_sso_names(u, _sl(_nested(given="Grace")))  # only given_name
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Grace", "Stay")


@pytest.mark.django_db
def test_noop_when_claims_match_and_tolerates_none_extra_data():
    from accounts.provisioning import apply_sso_names, _claims
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    assert _claims(None) == {}  # None-tolerant unwrap
    u = User.objects.create_user(
        username="e", password=TEST_PASSWORD, first_name="Same", last_name="Same"
    )
    apply_sso_names(u, _sl(None))  # no claims at all -> no error, no change
    apply_sso_names(u, _sl(_nested("Same", "Same")))  # equal -> no change
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Same", "Same")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sso_name_sync.py -v`
Expected: FAIL — cannot import `apply_sso_names` / `_claims`.

- [ ] **Step 3: Implement the helpers**

Append to `accounts/provisioning.py`:

```python
def _claims(extra_data):
    """Flatten the openid_connect provider's nested extra_data to the OIDC claim
    set. Mirrors the provider's _pick_data: prefer 'userinfo', then 'id_token',
    else the top-level dict. None/empty-tolerant."""
    if not extra_data:
        return {}
    return extra_data.get("userinfo") or extra_data.get("id_token") or extra_data


def apply_sso_names(user, sociallogin):
    """Sync first_name/last_name from the IdP's given_name/family_name claims,
    unless the user pinned them (names_locked). Never overwrites a name with a
    blank claim; each field syncs independently; saves only changed fields."""
    if user.names_locked:
        return
    claims = _claims(getattr(sociallogin.account, "extra_data", None))
    changed = []
    given = (claims.get("given_name") or "").strip()
    family = (claims.get("family_name") or "").strip()
    if given and given != user.first_name:
        user.first_name = given
        changed.append("first_name")
    if family and family != user.last_name:
        user.last_name = family
        changed.append("last_name")
    if changed:
        user.save(update_fields=changed)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sso_name_sync.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add accounts/provisioning.py tests/test_sso_name_sync.py
git commit -m "feat(accounts): apply_sso_names helper with nested-claim unwrap"
```

---

### Task 3: Wire the sync to allauth signals

**Files:**
- Modify: `accounts/signals.py` (add receivers; `accounts/apps.py` already imports this module)
- Test: `tests/test_sso_name_sync.py` (append integration tests using the real login driver)

**Interfaces:**
- Consumes: `apply_sso_names` (Task 2); the test harness `tests/_sso.py` (`make_oidc_app`, `make_request`, `make_sociallogin`) and the `_complete` login driver pattern from `tests/test_sso_provisioning.py`.
- Produces: a `_sync_sso_names(sender, request, sociallogin, **kwargs)` receiver connected to both `social_account_added` and `social_account_updated`.

- [ ] **Step 1: Write the failing integration tests**

```python
# append to tests/test_sso_name_sync.py

def _complete(request, sociallogin):
    from allauth.core import context
    from allauth.socialaccount.helpers import complete_social_login

    with context.request_context(request):
        return complete_social_login(request, sociallogin)


@pytest.fixture
def oidc_app(db):
    from tests._sso import make_oidc_app

    return make_oidc_app()


@pytest.mark.django_db
def test_link_by_email_first_login_syncs_names(oidc_app):
    # An admin-created local account, linked on first SSO login via connect(),
    # which emits social_account_added -> receiver -> apply_sso_names.
    from accounts.models import User
    from tests._sso import make_request, make_sociallogin
    from tests.factories import TEST_PASSWORD

    User.objects.create_user(
        username="teacher", email="teacher@school.edu", password=TEST_PASSWORD
    )
    request = make_request()
    sl = make_sociallogin(oidc_app, request, "teacher@school.edu", username="ignored")
    sl.account.extra_data = {"userinfo": {"given_name": "Tea", "family_name": "Cher"}}
    _complete(request, sl)
    linked = User.objects.get(username="teacher")
    assert (linked.first_name, linked.last_name) == ("Tea", "Cher")


@pytest.mark.django_db
def test_returning_login_updates_names_via_updated_signal(oidc_app):
    from allauth.socialaccount.models import SocialAccount
    from accounts.models import User
    from tests._sso import make_request, make_sociallogin
    from tests.factories import TEST_PASSWORD

    User.objects.create_user(
        username="ret", email="ret@school.edu", password=TEST_PASSWORD
    )
    # First login: link + initial names.
    r1 = make_request()
    sl1 = make_sociallogin(oidc_app, r1, "ret@school.edu", username="ignored", uid="sub-ret")
    sl1.account.extra_data = {"userinfo": {"given_name": "First", "family_name": "One"}}
    _complete(r1, sl1)
    # Second login (same uid): lookup refreshes extra_data + emits social_account_updated.
    r2 = make_request()
    sl2 = make_sociallogin(oidc_app, r2, "ret@school.edu", username="ignored", uid="sub-ret")
    sl2.account.extra_data = {"userinfo": {"given_name": "Second", "family_name": "Two"}}
    _complete(r2, sl2)
    u = User.objects.get(username="ret")
    assert (u.first_name, u.last_name) == ("Second", "Two")
    assert SocialAccount.objects.filter(user=u).count() == 1


@pytest.mark.django_db
def test_locked_user_names_untouched_on_login(oidc_app):
    from accounts.models import User
    from tests._sso import make_request, make_sociallogin
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(
        username="pin", email="pin@school.edu", password=TEST_PASSWORD,
        first_name="Pinned", last_name="Name",
    )
    u.names_locked = True
    u.save(update_fields=["names_locked"])
    request = make_request()
    sl = make_sociallogin(oidc_app, request, "pin@school.edu", username="ignored")
    sl.account.extra_data = {"userinfo": {"given_name": "Nope", "family_name": "Nope"}}
    _complete(request, sl)
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Pinned", "Name")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sso_name_sync.py -k "login" -v`
Expected: FAIL — names not synced (no receiver connected yet).

- [ ] **Step 3: Add the receivers**

In `accounts/signals.py`, add the imports near the top:

```python
from allauth.socialaccount.signals import social_account_added
from allauth.socialaccount.signals import social_account_updated

from accounts.provisioning import apply_sso_names
```

and append the receiver:

```python
@receiver(social_account_added)
@receiver(social_account_updated)
def _sync_sso_names(sender, request, sociallogin, **kwargs):
    """Sync first_name/last_name from the IdP on the login paths that carry a
    SocialLogin: social_account_added (link-an-existing-local-user-by-email, via
    connect()) and social_account_updated (every returning login). Net-new JIT
    signups get their names from allauth's built-in populate_user instead — that
    path does not emit social_account_added, so no receiver runs there."""
    apply_sso_names(sociallogin.account.user, sociallogin)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sso_name_sync.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add accounts/signals.py tests/test_sso_name_sync.py
git commit -m "feat(accounts): sync SSO names on login via allauth signals"
```

---

### Task 4: `UserEditForm` — name fields + sync-lock checkbox

**Files:**
- Modify: `accounts/forms.py` (`UserEditForm`)
- Test: `tests/test_user_edit_form.py`

**Interfaces:**
- Consumes: `User.names_locked` (Task 1), `accounts.sso_config.load_sso_app` (existing).
- Produces: `UserEditForm` with `first_name`, `last_name` (always) and `sync_name_from_sso` (present in `self.fields` iff `load_sso_app() is not None`); `save()` sets names always and `names_locked = not cleaned["sync_name_from_sso"]` when that field is present.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_user_edit_form.py
import pytest


def _form(instance, data, editing_self=False):
    from accounts.forms import UserEditForm

    return UserEditForm(data, instance=instance, editing_self=editing_self)


@pytest.mark.django_db
def test_saves_first_and_last_name():
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(username="u1", password=TEST_PASSWORD)
    f = _form(u, {"first_name": "Ada", "last_name": "Byron", "role": ""})
    assert f.is_valid(), f.errors
    f.save()
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Ada", "Byron")


@pytest.mark.django_db
def test_sync_checkbox_absent_without_sso_app():
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(username="u2", password=TEST_PASSWORD)
    f = _form(u, {"role": ""})
    assert "sync_name_from_sso" not in f.fields


@pytest.mark.django_db
def test_sync_checkbox_present_with_sso_app(db):
    from accounts.models import User
    from tests._sso import make_oidc_app
    from tests.factories import TEST_PASSWORD

    make_oidc_app()
    u = User.objects.create_user(username="u3", password=TEST_PASSWORD)
    f = _form(u, {"role": ""})
    assert "sync_name_from_sso" in f.fields
    # Initial reflects NOT names_locked (an unlocked user syncs -> box checked).
    assert f.fields["sync_name_from_sso"].initial is True


@pytest.mark.django_db
def test_unchecking_sync_locks_names(db):
    from accounts.models import User
    from tests._sso import make_oidc_app
    from tests.factories import TEST_PASSWORD

    make_oidc_app()
    u = User.objects.create_user(username="u4", password=TEST_PASSWORD)
    # Checkbox omitted from POST == unchecked.
    f = _form(u, {"first_name": "Man", "last_name": "Ual", "role": ""})
    assert f.is_valid(), f.errors
    f.save()
    u.refresh_from_db()
    assert u.names_locked is True


@pytest.mark.django_db
def test_checking_sync_unlocks_names(db):
    from accounts.models import User
    from tests._sso import make_oidc_app
    from tests.factories import TEST_PASSWORD

    make_oidc_app()
    u = User.objects.create_user(username="u5", password=TEST_PASSWORD)
    u.names_locked = True
    u.save(update_fields=["names_locked"])
    f = _form(u, {"role": "", "sync_name_from_sso": "on"})
    assert f.is_valid(), f.errors
    f.save()
    u.refresh_from_db()
    assert u.names_locked is False


@pytest.mark.django_db
def test_name_fields_editable_when_editing_self():
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(username="u6", password=TEST_PASSWORD)
    f = _form(u, {"first_name": "Self", "last_name": "Edit", "role": ""}, editing_self=True)
    assert f.fields["first_name"].disabled is False
    assert f.fields["last_name"].disabled is False
    assert f.is_valid(), f.errors
    f.save()
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Self", "Edit")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_user_edit_form.py -v`
Expected: FAIL — no `first_name`/`last_name`/`sync_name_from_sso` handling.

- [ ] **Step 3: Modify `UserEditForm`**

In `accounts/forms.py`, add fields to the `UserEditForm` class body (after `external_id`):

```python
    first_name = forms.CharField(max_length=150, required=False, label=_("First name"))
    last_name = forms.CharField(max_length=150, required=False, label=_("Last name"))
    sync_name_from_sso = forms.BooleanField(
        required=False,
        label=_("Keep name in sync with SSO"),
        help_text=_("Uncheck to pin a manually entered name so SSO won't overwrite it."),
    )
```

In `__init__`, after the existing `external_id` initial line, add:

```python
        self.fields["first_name"].initial = self.instance.first_name
        self.fields["last_name"].initial = self.instance.last_name
        # Single field-presence mechanism: the sync-lock checkbox exists ONLY when an
        # SSO app is configured. Presence drives the template guard and save() alike.
        from accounts.sso_config import load_sso_app

        if load_sso_app() is not None:
            self.fields["sync_name_from_sso"].initial = not self.instance.names_locked
        else:
            del self.fields["sync_name_from_sso"]
```

In `save()`, extend the field writes. Replace the existing block:

```python
            user.display_name = self.cleaned_data.get("display_name", "")
            user.email = new_email
            user.external_id = self.cleaned_data.get("external_id", "")
            user.save(update_fields=["display_name", "email", "external_id"])
```

with:

```python
            user.display_name = self.cleaned_data.get("display_name", "")
            user.email = new_email
            user.external_id = self.cleaned_data.get("external_id", "")
            user.first_name = self.cleaned_data.get("first_name", "").strip()
            user.last_name = self.cleaned_data.get("last_name", "").strip()
            fields = ["display_name", "email", "external_id", "first_name", "last_name"]
            if "sync_name_from_sso" in self.cleaned_data:  # SSO configured -> field present
                user.names_locked = not self.cleaned_data["sync_name_from_sso"]
                fields.append("names_locked")
            user.save(update_fields=fields)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_user_edit_form.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add accounts/forms.py tests/test_user_edit_form.py
git commit -m "feat(accounts): PA-editable first/last name + SSO sync-lock in UserEditForm"
```

---

### Task 5: User-edit template rows

**Files:**
- Modify: `templates/accounts/manage/user_form.html`
- Test: `tests/test_user_edit_view.py`

**Interfaces:**
- Consumes: `UserEditForm` (Task 4); the `user_edit` view context (`form`, `target`, `editing_self`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_user_edit_view.py
import pytest
from django.urls import reverse


def _pa_client(client):
    from django.contrib.auth.models import Group
    from accounts.models import User
    from institution.roles import PLATFORM_ADMIN
    from tests.factories import TEST_PASSWORD

    pa = User.objects.create_user(
        username="pa", email="pa@school.edu", password=TEST_PASSWORD, is_staff=True
    )
    pa.groups.add(Group.objects.get_or_create(name=PLATFORM_ADMIN)[0])
    from django.contrib.auth.models import Permission

    pa.user_permissions.add(Permission.objects.get(codename="change_user"))
    client.force_login(pa)
    return pa


@pytest.mark.django_db
def test_edit_page_shows_name_inputs(client):
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    _pa_client(client)
    target = User.objects.create_user(username="target", password=TEST_PASSWORD)
    body = client.get(reverse("accounts:user_edit", args=[target.pk])).content
    assert b'name="first_name"' in body
    assert b'name="last_name"' in body


@pytest.mark.django_db
def test_sync_checkbox_visibility_follows_sso_config(client):
    from accounts.models import User
    from tests._sso import make_oidc_app
    from tests.factories import TEST_PASSWORD

    _pa_client(client)
    target = User.objects.create_user(username="target2", password=TEST_PASSWORD)
    url = reverse("accounts:user_edit", args=[target.pk])
    assert b'name="sync_name_from_sso"' not in client.get(url).content
    make_oidc_app()
    assert b'name="sync_name_from_sso"' in client.get(url).content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_user_edit_view.py -v`
Expected: FAIL — the inputs/checkbox are not in the template yet.

- [ ] **Step 3: Add the rows**

In `templates/accounts/manage/user_form.html`, after the Display-name row (line 11) add:

```html
    <label class="manage__field"><span>{% trans "First name" %}</span>{{ form.first_name }}{{ form.first_name.errors }}</label>
    <label class="manage__field"><span>{% trans "Last name" %}</span>{{ form.last_name }}{{ form.last_name.errors }}</label>
```

Then, immediately before the `<div class="form__actions">` line, add the guarded checkbox row:

```html
    {% if form.sync_name_from_sso %}
    <label class="manage__field manage__field--check">{{ form.sync_name_from_sso }}<span>{{ form.sync_name_from_sso.label }}</span>{{ form.sync_name_from_sso.errors }}
      <small>{{ form.sync_name_from_sso.help_text }}</small>
    </label>
    {% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_user_edit_view.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add templates/accounts/manage/user_form.html tests/test_user_edit_view.py
git commit -m "feat(accounts): render first/last name + SSO sync-lock on user-edit page"
```

---

### Task 6: Promote `.btn--danger` into global `app.css`

**Files:**
- Modify: `core/static/core/css/app.css` (add after `.btn--primary`, line 53)
- Modify: `accounts/static/accounts/css/people.css` (remove the rule + its comment block, lines 103–114)
- Test: `tests/test_danger_button_css.py`

**Interfaces:**
- Produces: a global `.btn--danger` (resting + hover + active all red) so every template referencing it renders danger styling.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_danger_button_css.py
from pathlib import Path

from django.conf import settings


def _read(rel):
    return (Path(settings.BASE_DIR) / rel).read_text(encoding="utf-8")


def test_app_css_defines_danger_button_with_hover_and_active():
    css = _read("core/static/core/css/app.css")
    assert ".btn--danger" in css
    assert "var(--danger)" in css
    # Hover/active must set the danger background (else .btn:hover wins -> blue).
    assert ".btn--danger:hover" in css or ".btn--danger:active" in css


def test_people_css_no_longer_defines_danger_button():
    assert ".btn--danger" not in _read("accounts/static/accounts/css/people.css")
```

> If `settings.BASE_DIR` is a string, `Path(settings.BASE_DIR)` still works. If the test cannot resolve paths, fall back to `Path(__file__).resolve().parents[1]` as the repo root.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_danger_button_css.py -v`
Expected: FAIL — `.btn--danger` still only in people.css.

- [ ] **Step 3: Add the rule to `app.css`**

In `core/static/core/css/app.css`, immediately after the `.btn--primary` rule (line 53), add:

```css
/* Destructive action. Equal specificity to .btn, so it sits AFTER the base rule;
   hover/active also set the danger background or .btn:hover/.btn:active (0,2,0)
   would repaint it primary-blue. --danger token: light #A8392E / dark #E57373. */
.btn--danger { background: var(--danger); color: #fff; border-color: transparent; }
.btn--danger:hover, .btn--danger:active { background: var(--danger); filter: brightness(0.92); }
```

- [ ] **Step 4: Remove the copy from `people.css`**

In `accounts/static/accounts/css/people.css`, delete the comment block and both rules (lines 103–114): the `/* --- Danger button … */` comment, `.btn--danger { … }`, and `.btn--danger:hover { … }`. Leave the surrounding rules intact.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_danger_button_css.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/static/core/css/app.css accounts/static/accounts/css/people.css tests/test_danger_button_css.py
git commit -m "fix(ui): promote .btn--danger to global app.css with red hover/active"
```

---

### Task 7: Course-edit danger zone

**Files:**
- Modify: `templates/courses/manage/course_form.html`
- Modify: `courses/static/courses/css/courses.css` (add `.danger-zone` styles)
- Test: `tests/test_course_danger_zone.py`

**Interfaces:**
- Consumes: the global `.btn--danger` (Task 6); the `course_form` view context (`creating`, `course`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_course_danger_zone.py
import pytest
from django.urls import reverse


def _pa_client(client):
    from django.contrib.auth.models import Group, Permission
    from accounts.models import User
    from institution.roles import PLATFORM_ADMIN
    from tests.factories import TEST_PASSWORD

    pa = User.objects.create_user(
        username="pa", email="pa@school.edu", password=TEST_PASSWORD, is_staff=True
    )
    pa.groups.add(Group.objects.get_or_create(name=PLATFORM_ADMIN)[0])
    for code in ("add_course", "change_course", "delete_course", "view_course"):
        pa.user_permissions.add(Permission.objects.get(codename=code))
    client.force_login(pa)
    return pa


@pytest.mark.django_db
def test_edit_page_shows_danger_zone_with_red_delete(client):
    from courses.models import Course

    pa = _pa_client(client)
    course = Course.objects.create(title="C", slug="c", owner=pa)
    body = client.get(reverse("courses:manage_course_edit", args=["c"])).content
    assert b"danger-zone" in body
    assert b"btn--danger" in body


@pytest.mark.django_db
def test_create_page_has_no_danger_zone(client):
    _pa_client(client)
    body = client.get(reverse("courses:manage_course_create")).content
    assert b"danger-zone" not in body
    assert b"btn--danger" not in body
```

> Confirm the exact URL names with `courses/urls.py` (`manage_course_edit`, `manage_course_create`, `manage_course_delete`) and adjust if they differ.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_course_danger_zone.py -v`
Expected: FAIL — no `.danger-zone` block yet (Delete currently sits in `form__actions`).

- [ ] **Step 3: Restructure `course_form.html`**

Replace the existing actions block (lines 17–23):

```html
    <div class="form__actions">
      <button class="btn btn--primary" type="submit">{% trans "Save" %}</button>
      {% if not creating %}
        <a class="btn btn--ghost" href="{% url 'courses:manage_builder' slug=course.slug %}">{% trans "Open builder" %}</a>
        <a class="btn btn--danger" href="{% url 'courses:manage_course_delete' slug=course.slug %}">{% trans "Delete" %}</a>
      {% endif %}
    </div>
  </form>
```

with:

```html
    <div class="form__actions">
      <button class="btn btn--primary" type="submit">{% trans "Save" %}</button>
      {% if not creating %}
        <a class="btn btn--ghost" href="{% url 'courses:manage_builder' slug=course.slug %}">{% trans "Open builder" %}</a>
      {% endif %}
    </div>
  </form>
  {% if not creating %}
  <section class="danger-zone">
    <h2 class="danger-zone__title">{% trans "Danger zone" %}</h2>
    <p class="danger-zone__desc">{% trans "Permanently deletes this course and all its content, enrollments, and progress." %}</p>
    <a class="btn btn--danger" href="{% url 'courses:manage_course_delete' slug=course.slug %}">{% trans "Delete course" %}</a>
  </section>
  {% endif %}
```

- [ ] **Step 4: Add `.danger-zone` styles**

Append to `courses/static/courses/css/courses.css`:

```css
/* --- Course-settings danger zone --- */
.danger-zone {
  margin-top: var(--space-8);
  padding: var(--space-5);
  border: 1px solid var(--danger);
  border-radius: var(--radius-md, 8px);
  background: var(--danger-subtle);
}
.danger-zone__title { margin: 0 0 var(--space-2); font-size: 1rem; color: var(--danger); }
.danger-zone__desc { margin: 0 0 var(--space-4); color: var(--text-secondary); font-size: .9rem; }
```

> Verify `--danger-subtle`, `--radius-md`, and the `--space-*` scale exist in `core/static/core/css/tokens.css`; if a token is absent, use the nearest existing one (e.g. drop the `--radius-md` fallback to a literal `8px`, or reuse `--space-4`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_course_danger_zone.py -v`
Expected: PASS

- [ ] **Step 6: Verify the visual in light + dark**

Per the project convention, screenshot the course-edit page in both themes and confirm the danger zone reads as intentionally destructive (red border/heading, red Delete that stays red on hover). Adjust the CSS above if the accent is weak or the dark-theme contrast is poor. (This is the frontend-design polish pass for this task.)

- [ ] **Step 7: Commit**

```bash
git add templates/courses/manage/course_form.html courses/static/courses/css/courses.css tests/test_course_danger_zone.py
git commit -m "feat(courses): danger zone for course deletion on the edit page"
```

---

### Task 8: Depth-picker flattening note

**Files:**
- Modify: `courses/forms.py` (`CourseForm.__init__`)
- Test: `tests/test_course_structure.py` (append)

**Interfaces:**
- Consumes: the existing `structure` field and its Custom-course help_text branch in `CourseForm.__init__`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_course_structure.py
import pytest

_NOTE_FRAGMENT = "Removing a level is only possible"


@pytest.mark.django_db
def test_depth_note_shown_when_editing():
    from courses.forms import CourseForm
    from courses.models import Course
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    owner = User.objects.create_user(username="own", password=TEST_PASSWORD)
    course = Course.objects.create(title="C", slug="c", owner=owner)
    form = CourseForm(instance=course)
    assert _NOTE_FRAGMENT in str(form.fields["structure"].help_text)


@pytest.mark.django_db
def test_depth_note_absent_when_creating():
    from courses.forms import CourseForm

    form = CourseForm()
    assert _NOTE_FRAGMENT not in str(form.fields["structure"].help_text)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_course_structure.py -k depth_note -v`
Expected: FAIL — note not appended.

- [ ] **Step 3: Append the note**

In `courses/forms.py`, at the very end of `CourseForm.__init__` (after the `else: # editing` block that may replace `structure.help_text` for a Custom course), add:

```python
        # Depth note (edit only): appended AFTER the Custom-course help_text
        # replacement above, so both the base/Custom message and the note survive.
        if self.instance.pk:
            note = _(
                "Removing a level is only possible when no content exists at that "
                "level — move or delete that content first."
            )
            current = self.fields["structure"].help_text
            self.fields["structure"].help_text = f"{current} {note}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_course_structure.py -k depth_note -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add courses/forms.py tests/test_course_structure.py
git commit -m "feat(courses): note the flattening restriction on the depth picker"
```

---

### Task 9: Translations + full-suite verification

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po`

- [ ] **Step 1: Regenerate the message catalogs**

Run: `uv run python manage.py makemessages -l en -l pl`
This adds the new msgids (First name, Last name, Keep name in sync with SSO, the checkbox help text, Danger zone, the consequence line, Delete course, the depth note).

- [ ] **Step 2: Fill in Polish translations**

Edit `locale/pl/LC_MESSAGES/django.po`: provide `msgstr` for each new msgid. Suggested:
- "First name" → "Imię"
- "Last name" → "Nazwisko"
- "Keep name in sync with SSO" → "Synchronizuj nazwę z SSO"
- "Uncheck to pin a manually entered name so SSO won't overwrite it." → "Odznacz, aby zachować ręcznie wpisaną nazwę i nie pozwolić SSO jej nadpisać."
- "Danger zone" → "Strefa niebezpieczna"
- "Permanently deletes this course and all its content, enrollments, and progress." → "Trwale usuwa ten kurs wraz z całą jego zawartością, zapisami i postępami."
- "Delete course" → "Usuń kurs"
- "Removing a level is only possible when no content exists at that level — move or delete that content first." → "Usunięcie poziomu jest możliwe tylko, gdy nie zawiera on żadnych treści — najpierw przenieś lub usuń tę zawartość."

For EN, leave `msgstr` empty where the source string is the translation (Django falls back to msgid), matching the repo's existing EN catalog convention. **Remove any `#, fuzzy` flags** makemessages added to these entries, or the translation is ignored.

- [ ] **Step 3: Compile and run the i18n catalog + full suite**

Run:
```bash
uv run python manage.py compilemessages -l en -l pl
uv run pytest -p no:randomly -q
uv run ruff check .
uv run ruff format --check .
```
Expected: all tests pass (including any i18n catalog / no-obsolete tests), ruff clean. Fix any failures before committing.

- [ ] **Step 4: Commit**

```bash
git add locale/en/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.po
git commit -m "i18n: EN/PL catalogs for name fields and course danger zone"
```

---

## Self-Review

**Spec coverage:**
- Part 1 SSO capture → Tasks 1 (`names_locked`), 2 (`apply_sso_names`+unwrap), 3 (signal wiring across all three login paths). ✓
- Part 1 PA editing + lock → Tasks 4 (form), 5 (template). ✓
- Part 2 danger button + zone → Tasks 6 (global `.btn--danger` incl. hover/active), 7 (danger zone). ✓
- Part 3 depth note → Task 8. ✓
- i18n EN+PL, full-suite/ruff DoD → Task 9. ✓
- Nested-`extra_data` fixture shape → enforced in Tasks 2 & 3 tests. ✓
- Partial-claim independent sync → Task 2 test. ✓
- Single field-presence mechanism (no separate flag) → Task 4. ✓

**Placeholder scan:** No TBD/TODO; every code step shows concrete code; every command has expected output.

**Type consistency:** `apply_sso_names(user, sociallogin)` and `_claims(extra_data)` names match between Tasks 2 and 3; `sync_name_from_sso` / `names_locked` spelled consistently across Tasks 1, 4, 5.

**Note for the executor:** verify the exact `courses:` URL names in `courses/urls.py` (Task 7) and the token names in `tokens.css` (Task 7 CSS) before relying on them; both tasks flag the fallback.
