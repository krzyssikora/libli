# Phase 0d‑2 — Surfaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build libli's product surfaces on the 0d‑1 UI foundation — public landing page, authenticated dashboard scaffold, user settings, minimal institution settings, branded 403/404/500 error pages — plus an i18n re-clamp fix and a Playwright E2E smoke suite wired into CI.

**Architecture:** No new app. New views/forms/templates/URLs live in the existing **`core`** app (the institution-settings form lives in `institution`). Surfaces consume the 0d‑1 shell (`templates/base.html`), context processors, cached `get_site_config()`, and EN/PL i18n unchanged. Data-dependent features (courses, analytics) ship as empty-state chrome only. Role gating is Group-based via a new `user_roles` context processor; the institution-settings view is permission-gated.

**Tech Stack:** Python 3.13 (uv), Django 5.2, django-allauth 65.18 (incl. `openid_connect`), PostgreSQL (psycopg 3), bespoke CSS (from 0d‑1), pytest + pytest-django, **pytest-playwright** (new), ruff.

This plan implements [the Phase 0d‑2 spec](../specs/2026-06-14-phase-0d2-surfaces-design.md), refining [Phase 0 foundations](../specs/2026-06-13-phase-0-foundations-design.md) §7 and building on [Phase 0d‑1](../specs/2026-06-14-phase-0d1-ui-foundation-design.md).

---

## Execution environment

Developer machine is **Windows (win32)**, PowerShell primary, but every `bash` block here is **POSIX sh** and must run through the **Bash tool / Git Bash**. Always invoke Python through **`uv run python ...`** (system `python` is 3.11; uv manages 3.13). PostgreSQL from Plan 0a: role `libli` / password `libli` / database `libli` on `localhost:5432`. Run `uv run ruff format .` before **every** commit; `ruff check` enforces 88-column lines (E501). Tests run under `DJANGO_SETTINGS_MODULE=config.settings.test` (pytest is configured for this; `addopts = -q`). Test fixture password is `tests.factories.TEST_PASSWORD`; `make_verified_user(username=..., email=...)` and the SSO helper `tests._sso.make_oidc_app()` exist.

**i18n tooling (Task 10):** `makemessages`/`compilemessages` need GNU **gettext** (`msgfmt`, `xgettext`) on PATH. Verify with `msgfmt --version`. If unavailable, hand-edit the `.po` and compile with Python's `msgfmt.py` (the 0d‑1 fallback).

**Branch:** work on `phase-0d2-surfaces` (already checked out; the spec + spec-review commits live here).

## Verified-against-source facts (drive specific decisions)

1. `core/services.py` `get_site_config()` returns a dict with keys `name, logo_url, primary, accent, enabled_languages, default_language, default_theme` — **no `signup_policy`** (Task 1 adds it). `Institution`/`BrandColor` `save`/`delete` fire `invalidate_site_config` (connected in `core/apps.py:ready()` since 0d‑1).
2. `core/context_processors.py` defines `THEME_VALUES`, `COOKIE_THEME = "libli_theme"`, `institution_branding`, `ui_prefs` (which computes `hide_auth_cta = view_name.startswith(("account_", "accounts:"))`). Registered processors: `request`, `auth`, `messages`, `institution_branding`, `ui_prefs` (`config/settings/base.py:60-66`).
3. `core/middleware.py`: `LANGUAGE_SESSION_KEY = "_language"`; `LanguageSeederMiddleware.__call__` only seeds when `not request.session.get(KEY)`; `SessionLocaleMiddleware` activates the session key. Seeder runs **before** `SessionLocaleMiddleware` and `AuthenticationMiddleware` (`base.py:41-45`).
4. `core/views.py` already imports `from core.middleware import LANGUAGE_SESSION_KEY as SESSION_KEY`, `from core.services import get_site_config`, `from core.context_processors import THEME_VALUES`, and `home` is `@login_required` rendering `core/home.html`. `core/urls.py` has `app_name="core"` + `ui/set-language/`, `ui/set-theme/`.
5. `config/urls.py` imports `from core.views import home` (bare) and registers `admin/`, `healthz/`, `home/`, then empty-prefix `include("core.urls")` / `include("accounts.urls")` then the allauth includes. Root `""` currently 404s.
6. `accounts.User` fields: `display_name` (`blank=True, max_length=150`), `language` (choices en/pl, default `"en"`), `theme` (choices light/dark/auto, default `"auto"`). `__str__` = `display_name or username`.
7. `institution.Institution`: `name` (default "My Institution"), `signup_policy` (choices invite/open, default `"invite"`), `enabled_languages` (**JSONField**, default `["en","pl"]`), `default_language` (`"en"`), `default_theme` (`"auto"`); `load()` does `get_or_create(pk=1)`.
8. `institution/roles.py`: constants `STUDENT/TEACHER/COURSE_ADMIN/PLATFORM_ADMIN`; `seed_roles()` creates the four Groups and assigns `institution.change_institution` (+ others) to **Platform Admin**.
9. `templates/base.html` account menu (authenticated) currently holds only `{{ user }}` + a logout form, inside `.menu__panel[data-menu-panel]`. The shell's anonymous header CTA is `<a class="btn--ghost" href="{% url 'account_login' %}">` shown when `not hide_auth_cta`.
10. `tests/conftest.py` has an autouse `_enable_db_access(db)` (all tests get DB). The cache-clear autouse fixture currently lives only in `tests/test_ui_foundation.py` (Task 1 centralizes it).
11. The configured OIDC `SocialApp` login URL is served at `/accounts/oidc/<provider_id>/login/` (see `tests/test_sso_provisioning.py` + `tests/_sso.py:make_oidc_app` → `provider_id="testidp"`).

## File Structure

```
core/
├── views.py                 # +landing, +user_settings, +institution_settings
├── urls.py                  # +settings/, +settings/institution/ (core: namespace)
├── forms.py                 # NEW: UserSettingsForm
├── context_processors.py    # +user_roles; extend ui_prefs (landing hide_auth_cta)
├── services.py              # +signup_policy in _DEFAULTS/_build
├── middleware.py            # extend LanguageSeederMiddleware (re-clamp)
└── static/core/css/app.css  # +landing-specific rules (hero/footer/eyebrow)
institution/
└── forms.py                 # NEW: InstitutionSettingsForm
config/
├── settings/base.py         # register user_roles context processor
└── urls.py                  # +path("", landing, name="landing")
templates/
├── base.html                # account-menu Settings + (PA) Institution settings links
├── core/home.html           # rebuilt: dashboard role-section scaffold
├── core/landing.html        # NEW
├── core/user_settings.html  # NEW
├── core/institution_settings.html  # NEW
├── 404.html                 # NEW (extends shell)
├── 403.html                 # NEW (extends shell)
└── 500.html                 # NEW (self-contained, no context processors)
tests/
├── conftest.py              # +autouse _clear_site_cache
├── test_surfaces.py         # NEW: client/wiring tests (Tasks 1-9)
└── test_e2e_smoke.py        # NEW: Playwright suite (Task 11)
locale/{en,pl}/LC_MESSAGES/django.po(+.mo)   # updated (Task 10)
.github/workflows/ci.yml     # +e2e job/step (Task 11)
pyproject.toml               # +pytest-playwright dev dep; e2e marker; addopts
```

---

### Task 1: Centralize cache fixture + add `signup_policy` to the cached bundle

**Files:**
- Modify: `tests/conftest.py`, `core/services.py`, `tests/test_ui_foundation.py` (remove duplicate fixture)
- Test: `tests/test_surfaces.py` (NEW)

- [ ] **Step 1: Centralize the autouse cache-clear fixture** — (a) append the fixture
below to `tests/conftest.py`, **and** (b) **delete** the now-duplicate `_clear_site_cache`
fixture from `tests/test_ui_foundation.py` (the `@pytest.fixture(autouse=True)` block at
lines 13-24, including its local `from django.core.cache import cache`) so the fixture is
defined **once** (in conftest, applying project-wide). Leave that module's other imports/tests
intact.
```python
@pytest.fixture(autouse=True)
def _clear_site_cache():
    """LocMemCache is not transaction-scoped; clear it around every test so a
    cached site-config (palette / signup_policy / enabled_languages) from one test
    never leaks into the next."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()
```

- [ ] **Step 2: Write the failing tests** — create `tests/test_surfaces.py`:
```python
import pytest
from django.urls import reverse

from tests.factories import make_verified_user


@pytest.mark.django_db
def test_site_config_includes_signup_policy_default():
    from core.services import get_site_config

    assert get_site_config()["signup_policy"] == "invite"


@pytest.mark.django_db
def test_site_config_signup_policy_reflects_save():
    from core.services import get_site_config
    from institution.models import Institution

    assert get_site_config()["signup_policy"] == "invite"
    inst = Institution.load()
    inst.signup_policy = "open"
    inst.save()  # fires invalidate_site_config
    assert get_site_config()["signup_policy"] == "open"
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run python -m pytest tests/test_surfaces.py -k signup_policy -v`
Expected: FAIL — `KeyError: 'signup_policy'`.

- [ ] **Step 4: Add `signup_policy` to the bundle** — in `core/services.py`, add to `_DEFAULTS`:
```python
    "default_theme": "auto",
    "signup_policy": "invite",
```
and to the dict returned by `_build()` (next to `default_theme`):
```python
        "default_theme": inst.default_theme or _DEFAULTS["default_theme"],
        "signup_policy": inst.signup_policy or _DEFAULTS["signup_policy"],
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_surfaces.py -k signup_policy -v` → PASS (both).
Run: `uv run python -m pytest -q` → all green (no regression).

- [ ] **Step 6: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add tests/conftest.py tests/test_ui_foundation.py core/services.py tests/test_surfaces.py
git commit -m "feat(core): expose signup_policy in cached site-config; central cache fixture"
```

---

### Task 2: `user_roles` context processor + register it

**Files:**
- Modify: `core/context_processors.py`, `config/settings/base.py`
- Test: append to `tests/test_surfaces.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_surfaces.py`:
```python
@pytest.mark.django_db
def test_user_roles_anonymous_all_false(rf):
    from django.contrib.auth.models import AnonymousUser

    from core.context_processors import user_roles

    request = rf.get("/")
    request.user = AnonymousUser()
    assert user_roles(request) == {
        "is_student": False,
        "is_teacher": False,
        "is_course_admin": False,
        "is_platform_admin": False,
    }


@pytest.mark.django_db
def test_user_roles_reflects_group_membership(rf):
    from django.contrib.auth.models import Group

    from core.context_processors import user_roles
    from institution.roles import PLATFORM_ADMIN

    user = make_verified_user(username="pa", email="pa@school.edu")
    user.groups.add(Group.objects.get_or_create(name=PLATFORM_ADMIN)[0])
    request = rf.get("/")
    request.user = user
    ctx = user_roles(request)
    assert ctx["is_platform_admin"] is True
    assert ctx["is_student"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_surfaces.py -k user_roles -v`
Expected: FAIL — `ImportError: cannot import name 'user_roles'`.

- [ ] **Step 3: Implement** — append to `core/context_processors.py`:
```python
def user_roles(request):
    """Group-based role flags for the dashboard sections + account menu.

    Early-returns all-False for anonymous (never touches .groups). One cheap
    query per authed request. Group names come from institution.roles constants
    (re-sliceable; no inline magic strings)."""
    from institution.roles import COURSE_ADMIN
    from institution.roles import PLATFORM_ADMIN
    from institution.roles import STUDENT
    from institution.roles import TEACHER

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {
            "is_student": False,
            "is_teacher": False,
            "is_course_admin": False,
            "is_platform_admin": False,
        }
    names = set(user.groups.values_list("name", flat=True))
    return {
        "is_student": STUDENT in names,
        "is_teacher": TEACHER in names,
        "is_course_admin": COURSE_ADMIN in names,
        "is_platform_admin": PLATFORM_ADMIN in names,
    }
```

- [ ] **Step 4: Register the processor** — in `config/settings/base.py`, add to the
`context_processors` list (after `ui_prefs`):
```python
                "core.context_processors.institution_branding",
                "core.context_processors.ui_prefs",
                "core.context_processors.user_roles",
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_surfaces.py -k user_roles -v` → PASS (both).
Run: `uv run python -m pytest -q` → all green.

- [ ] **Step 6: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add core/context_processors.py config/settings/base.py tests/test_surfaces.py
git commit -m "feat(core): user_roles context processor (group-based role flags)"
```

---

### Task 3: User settings — form, view, route, template, re-sync

**Files:**
- Create: `core/forms.py`, `templates/core/user_settings.html`
- Modify: `core/views.py`, `core/urls.py`
- Test: append to `tests/test_surfaces.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_surfaces.py`:
```python
@pytest.mark.django_db
def test_user_settings_requires_login(client):
    resp = client.get(reverse("core:user_settings"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_user_settings_get_renders(client):
    user = make_verified_user(username="settingsuser", email="setu@school.edu")
    client.force_login(user)
    resp = client.get(reverse("core:user_settings"))
    assert resp.status_code == 200
    assert b"settingsuser" in resp.content  # read-only username shown (distinctive)


@pytest.mark.django_db
def test_user_settings_post_persists_and_resyncs(client):
    user = make_verified_user(username="su2", email="su2@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:user_settings"),
        {"theme": "dark", "language": "pl", "display_name": "Sue", "username": "hacker"},
    )
    assert resp.status_code == 302
    user.refresh_from_db()
    assert user.theme == "dark"
    assert user.language == "pl"
    assert user.display_name == "Sue"
    assert user.username == "su2"  # username NOT editable (absent from the form)
    assert client.session["_language"] == "pl"
    assert resp.cookies["libli_theme"].value == "dark"
    # (The success-message flash is not separately asserted; the messages middleware
    # + context processor are already wired in config/settings/base.py.)


@pytest.mark.django_db
def test_user_settings_rejects_disabled_language(client):
    from institution.models import Institution

    inst = Institution.load()
    inst.enabled_languages = ["en"]  # pl disabled
    inst.save()
    user = make_verified_user(username="su3", email="su3@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:user_settings"),
        {"theme": "auto", "language": "pl", "display_name": ""},
    )
    assert resp.status_code == 200  # re-render with errors, no redirect
    user.refresh_from_db()
    assert user.language == "en"  # unchanged (default)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_surfaces.py -k user_settings -v`
Expected: FAIL — `NoReverseMatch: 'core:user_settings'`.

- [ ] **Step 3: Create the form** — `core/forms.py`:
```python
"""Forms for the core surfaces."""

from django import forms
from django.conf import settings

from accounts.models import User
from core.services import get_site_config


class UserSettingsForm(forms.ModelForm):
    """Edit the current user's UI prefs. `username` is intentionally NOT a field
    (school-assigned, read-only). `language` choices are narrowed at init to the
    institution's enabled languages."""

    class Meta:
        model = User
        fields = ["theme", "language", "display_name"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = dict(settings.LANGUAGES)
        enabled = get_site_config()["enabled_languages"]
        self.fields["language"].choices = [(c, labels.get(c, c)) for c in enabled]
```

- [ ] **Step 4: Add the view** — in `core/views.py`, add imports at the top
(next to the existing imports):
```python
from django.contrib import messages
from django.utils.translation import gettext_lazy as _

from core.context_processors import COOKIE_THEME
from core.forms import UserSettingsForm
```
and the view (after `home`):
```python
@login_required
def user_settings(request):
    """Edit theme/language/display_name; re-sync session language + theme cookie."""
    if request.method == "POST":
        form = UserSettingsForm(request.POST, instance=request.user)
        if form.is_valid():
            user = form.save()
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
    return render(request, "core/user_settings.html", {"form": form})
```

- [ ] **Step 5: Add the route** — in `core/urls.py`, add to `urlpatterns`:
```python
    path("settings/", views.user_settings, name="user_settings"),
```

- [ ] **Step 6: Create the template** — `templates/core/user_settings.html`:
```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Settings" %} · libli{% endblock %}
{% block content %}
<div class="card">
  <h1>{% trans "Settings" %}</h1>
  <p class="helptext">{% trans "Username" %}: <strong>{{ user.username }}</strong></p>
  <form method="post">
    {% csrf_token %}
    {{ form.as_p }}
    <button class="btn" type="submit">{% trans "Save" %}</button>
  </form>
  <p><a href="{% url 'account_change_password' %}">{% trans "Change password" %}</a></p>
</div>
{% endblock %}
```
> Verify `account_change_password` resolves: `uv run python -c "import django; django.setup(); from django.urls import reverse; print(reverse('account_change_password'))"` (set `DJANGO_SETTINGS_MODULE=config.settings.test` in the env first, or run via `uv run python manage.py shell -c "from django.urls import reverse; print(reverse('account_change_password'))"`). It is the standard allauth 65.18 name.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_surfaces.py -k user_settings -v` → PASS (all four).
Run: `uv run python -m pytest -q` → all green.

- [ ] **Step 8: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add core/forms.py core/views.py core/urls.py templates/core/user_settings.html tests/test_surfaces.py
git commit -m "feat(core): user settings page (theme/language/display_name + re-sync)"
```

---

### Task 4: Institution settings — form, view (perm-gated), route, template

**Files:**
- Create: `institution/forms.py`, `templates/core/institution_settings.html`
- Modify: `core/views.py`, `core/urls.py`
- Test: append to `tests/test_surfaces.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_surfaces.py`:
```python
def _make_platform_admin(username, email):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()  # idempotent; assigns institution.change_institution to PA group
    user = make_verified_user(username=username, email=email)
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


@pytest.mark.django_db
def test_institution_settings_anonymous_redirects(client):
    resp = client.get(reverse("core:institution_settings"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_institution_settings_non_pa_forbidden(client):
    user = make_verified_user(username="nopa", email="nopa@school.edu")
    client.force_login(user)
    resp = client.get(reverse("core:institution_settings"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_institution_settings_pa_can_load_and_save(client):
    from core.services import get_site_config

    user = _make_platform_admin("pa1", "pa1@school.edu")
    client.force_login(user)
    assert client.get(reverse("core:institution_settings")).status_code == 200
    resp = client.post(
        reverse("core:institution_settings"),
        {
            "enabled_languages": ["en", "pl"],
            "default_language": "pl",
            "default_theme": "dark",
            "signup_policy": "open",
        },
    )
    assert resp.status_code == 302
    cfg = get_site_config()  # cache invalidated on save
    assert cfg["default_language"] == "pl"
    assert cfg["default_theme"] == "dark"
    assert cfg["signup_policy"] == "open"


@pytest.mark.django_db
def test_institution_settings_validation_errors(client):
    user = _make_platform_admin("pa2", "pa2@school.edu")
    client.force_login(user)
    # default_language not in enabled_languages
    resp = client.post(
        reverse("core:institution_settings"),
        {"enabled_languages": ["en"], "default_language": "pl",
         "default_theme": "auto", "signup_policy": "invite"},
    )
    assert resp.status_code == 200
    assert b"enabled language" in resp.content.lower()
    # empty enabled_languages
    resp = client.post(
        reverse("core:institution_settings"),
        {"enabled_languages": [], "default_language": "en",
         "default_theme": "auto", "signup_policy": "invite"},
    )
    assert resp.status_code == 200
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_surfaces.py -k institution_settings -v`
Expected: FAIL — `NoReverseMatch: 'core:institution_settings'`.

- [ ] **Step 3: Create the form** — `institution/forms.py`:
```python
"""Minimal operational institution settings (branding admin is Phase 5)."""

from django import forms
from django.conf import settings

from institution.models import Institution


class InstitutionSettingsForm(forms.ModelForm):
    # enabled_languages is a JSONField; a plain ModelForm renders a raw-JSON
    # textarea. Override with a multi-select so it round-trips to a list.
    enabled_languages = forms.MultipleChoiceField(
        choices=settings.LANGUAGES, widget=forms.CheckboxSelectMultiple
    )
    # default_language has no model choices; constrain it to the supported set.
    default_language = forms.ChoiceField(choices=settings.LANGUAGES)

    class Meta:
        model = Institution
        fields = [
            "enabled_languages",
            "default_language",
            "default_theme",
            "signup_policy",
        ]

    def clean_enabled_languages(self):
        value = self.cleaned_data["enabled_languages"]
        if not value:
            raise forms.ValidationError("Enable at least one language.")
        return value  # a list -> stored in the JSONField

    def clean(self):
        cleaned = super().clean()
        enabled = cleaned.get("enabled_languages") or []
        default = cleaned.get("default_language")
        if default and default not in enabled:
            self.add_error(
                "default_language",
                "Default language must be an enabled language.",
            )
        return cleaned
```

- [ ] **Step 4: Add the view** — in `core/views.py`, add imports:
```python
from django.contrib.auth.decorators import permission_required

from institution.forms import InstitutionSettingsForm
from institution.models import Institution
```
and the view:
```python
@login_required
@permission_required("institution.change_institution", raise_exception=True)
def institution_settings(request):
    """Platform-Admin-only operational settings. login_required runs first so an
    anonymous request redirects to login; an authed user lacking the perm gets 403."""
    inst = Institution.load()  # bootstrap/admin write path (get_or_create) — OK here
    if request.method == "POST":
        form = InstitutionSettingsForm(request.POST, instance=inst)
        if form.is_valid():
            form.save()  # fires post_save -> invalidate_site_config
            messages.success(request, _("Institution settings saved."))
            return redirect("core:institution_settings")
    else:
        form = InstitutionSettingsForm(instance=inst)
    return render(request, "core/institution_settings.html", {"form": form})
```

- [ ] **Step 5: Add the route** — in `core/urls.py`, add to `urlpatterns`:
```python
    path(
        "settings/institution/",
        views.institution_settings,
        name="institution_settings",
    ),
```

- [ ] **Step 6: Create the template** — `templates/core/institution_settings.html`:
```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Institution settings" %} · libli{% endblock %}
{% block content %}
<div class="card">
  <h1>{% trans "Institution settings" %}</h1>
  <form method="post">
    {% csrf_token %}
    {{ form.as_p }}
    <button class="btn" type="submit">{% trans "Save" %}</button>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_surfaces.py -k institution_settings -v` → PASS (all four).
Run: `uv run python -m pytest -q` → all green.
> Note: the 403 test currently returns Django's default 403 body (no `403.html` yet — Task 9 adds it). The assertion is on `status_code == 403`, which holds regardless.

- [ ] **Step 8: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add institution/forms.py core/views.py core/urls.py templates/core/institution_settings.html tests/test_surfaces.py
git commit -m "feat(core): institution settings page (operational fields, perm-gated)"
```

---

### Task 5: Account-menu navigation (Settings + Institution settings links)

**Files:**
- Modify: `templates/base.html`
- Test: append to `tests/test_surfaces.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_surfaces.py`:
```python
@pytest.mark.django_db
def test_account_menu_has_settings_link(client):
    user = make_verified_user(username="m1", email="m1@school.edu")
    client.force_login(user)
    resp = client.get(reverse("home"))
    assert reverse("core:user_settings").encode() in resp.content
    # non-PA: no institution-settings link
    assert reverse("core:institution_settings").encode() not in resp.content


@pytest.mark.django_db
def test_account_menu_shows_institution_settings_for_pa(client):
    user = _make_platform_admin("m2", "m2@school.edu")
    client.force_login(user)
    resp = client.get(reverse("home"))
    assert reverse("core:institution_settings").encode() in resp.content
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_surfaces.py -k account_menu -v`
Expected: FAIL — links not present in the rendered menu.

- [ ] **Step 3: Add the links** — in `templates/base.html`, replace the account-menu
panel body. **The match is whitespace-sensitive** — the panel is indented 10 spaces in
`base.html`; copy the existing indentation verbatim (or edit against the live file) so the
exact-string replace succeeds. Find:
```django
          <div class="menu__panel account-menu" data-menu-panel hidden>
            <span class="menu__item">{{ user }}</span>
            <form method="post" action="{% url 'account_logout' %}">
              {% csrf_token %}
              <button class="menu__item" type="submit">{% trans "Log out" %}</button>
            </form>
          </div>
```
and replace with:
```django
          <div class="menu__panel account-menu" data-menu-panel hidden>
            <span class="menu__item">{{ user }}</span>
            <a class="menu__item" href="{% url 'core:user_settings' %}">{% trans "Settings" %}</a>
            {% if is_platform_admin %}
              <a class="menu__item" href="{% url 'core:institution_settings' %}">{% trans "Institution settings" %}</a>
            {% endif %}
            <form method="post" action="{% url 'account_logout' %}">
              {% csrf_token %}
              <button class="menu__item" type="submit">{% trans "Log out" %}</button>
            </form>
          </div>
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_surfaces.py -k account_menu -v` → PASS (both).
Run: `uv run python -m pytest -q` → all green.

- [ ] **Step 5: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add templates/base.html tests/test_surfaces.py
git commit -m "feat(core): account-menu Settings + (PA) Institution settings links"
```

---

### Task 6: Dashboard — rebuild `core/home.html` with role-aware sections

**Files:**
- Modify: `templates/core/home.html`
- Test: append to `tests/test_surfaces.py`

> The `home` view is unchanged (it already renders `core/home.html`); only the
> template body is rebuilt. Role flags come from the `user_roles` processor (Task 2) —
> the view passes none.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_surfaces.py`:
```python
def _make_in_group(username, email, group_name):
    from django.contrib.auth.models import Group

    user = make_verified_user(username=username, email=email)
    user.groups.add(Group.objects.get_or_create(name=group_name)[0])
    return user


@pytest.mark.django_db
def test_dashboard_student_sees_learning_not_admin(client):
    from institution.roles import STUDENT

    user = _make_in_group("st", "st@school.edu", STUDENT)
    client.force_login(user)
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    assert b"data-section=\"learning\"" in resp.content
    assert b"data-section=\"admin\"" not in resp.content
    # (The is_course_admin-only branch shares the "admin" section markup; it is
    # covered transitively by the Platform-Admin case below, not as its own test.)


@pytest.mark.django_db
def test_dashboard_platform_admin_sees_admin_section(client):
    user = _make_platform_admin("da", "da@school.edu")
    client.force_login(user)
    resp = client.get(reverse("home"))
    assert b"data-section=\"admin\"" in resp.content
    assert reverse("core:institution_settings").encode() in resp.content


@pytest.mark.django_db
def test_dashboard_no_group_sees_generic(client):
    user = make_verified_user(username="ng", email="ng@school.edu")
    client.force_login(user)
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    assert b"data-section=\"generic\"" in resp.content
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_surfaces.py -k dashboard -v`
Expected: FAIL — the placeholder template has none of these section markers.

- [ ] **Step 3: Rebuild the template** — overwrite `templates/core/home.html`:
```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Dashboard" %} · libli{% endblock %}
{% block content %}
<h1>
  {% blocktrans with name=user.display_name|default:user.username %}Welcome, {{ name }}{% endblocktrans %}
</h1>

{% if is_student %}
<section class="card" data-section="learning">
  <h2>{% trans "My learning" %}</h2>
  <p class="helptext">{% trans "No courses yet." %}</p>
</section>
{% endif %}

{% if is_teacher %}
<section class="card" data-section="teaching">
  <h2>{% trans "Teaching" %}</h2>
  <p class="helptext">{% trans "No classes assigned yet." %}</p>
</section>
{% endif %}

{% if is_course_admin or is_platform_admin %}
<section class="card" data-section="admin">
  <h2>{% trans "Administration" %}</h2>
  <p><a href="{% url 'core:user_settings' %}">{% trans "Settings" %}</a></p>
  {% if is_platform_admin %}
  <p><a href="{% url 'core:institution_settings' %}">{% trans "Institution settings" %}</a></p>
  {% endif %}
  <p class="helptext">{% trans "Course and branding admin arrive in a later phase." %}</p>
</section>
{% endif %}

{% if not is_student and not is_teacher and not is_course_admin and not is_platform_admin %}
<section class="card" data-section="generic">
  <p class="helptext">{% trans "Your dashboard will fill in as you are added to courses." %}</p>
</section>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_surfaces.py -k dashboard -v` → PASS (all three).
Run: `uv run python -m pytest -q` → all green.
> The 0d‑1 home test (`test_home_authenticated_returns_200`, asserts the username appears) still passes — the greeting renders `display_name|default:username`, and `make_verified_user` sets no display_name → username shows.

- [ ] **Step 5: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add templates/core/home.html tests/test_surfaces.py
git commit -m "feat(core): role-aware dashboard scaffold with empty states"
```

---

### Task 7: Landing page — route, view, template, CTAs

**Files:**
- Modify: `config/urls.py`, `core/views.py`, `core/context_processors.py`
- Create: `templates/core/landing.html`
- Test: append to `tests/test_surfaces.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_surfaces.py`:
```python
@pytest.mark.django_db
def test_landing_anonymous_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"data-account-menu" not in resp.content  # anonymous variant
    assert reverse("account_login").encode() in resp.content  # hero CTA


@pytest.mark.django_db
def test_landing_authenticated_redirects_home(client):
    user = make_verified_user(username="ld", email="ld@school.edu")
    client.force_login(user)
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp["Location"] == reverse("home")


@pytest.mark.django_db
def test_landing_hides_header_cta(rf):
    from django.contrib.auth.models import AnonymousUser
    from django.urls import resolve

    from core.context_processors import ui_prefs

    request = rf.get("/")
    request.user = AnonymousUser()
    request.COOKIES = {}
    request.resolver_match = resolve("/")  # view_name == "landing"
    assert ui_prefs(request)["hide_auth_cta"] is True


@pytest.mark.django_db
def test_landing_signup_cta_only_when_open(client):
    from institution.models import Institution

    # default policy = invite -> no create-account CTA
    resp = client.get("/")
    assert reverse("account_signup").encode() not in resp.content
    inst = Institution.load()
    inst.signup_policy = "open"
    inst.save()  # fires invalidate_site_config
    resp = client.get("/")
    assert reverse("account_signup").encode() in resp.content


@pytest.mark.django_db
def test_landing_sso_button_visibility_and_url(client):
    # no OIDC app -> no SSO button
    assert b"/accounts/oidc/" not in client.get("/").content
    from tests._sso import make_oidc_app

    make_oidc_app()  # provider_id="testidp"
    body = client.get("/").content
    assert b"/accounts/oidc/testidp/login/" in body
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_surfaces.py -k landing -v`
Expected: FAIL — the client-based landing tests fail because `/` returns 404 (no `landing`
route yet); `test_landing_hides_header_cta` fails with `Resolver404` from its `resolve("/")`
setup line (also expected — the route lands in Step 5). Both are the intended pre-implementation
failures.

- [ ] **Step 3: Extend `ui_prefs` to suppress the header CTA on landing** — in
`core/context_processors.py`, change the `hide_auth_cta` line inside `ui_prefs`:
```python
    hide_auth_cta = (
        view_name.startswith(("account_", "accounts:")) or view_name == "landing"
    )
```

- [ ] **Step 4a: Verify the OIDC login-URL call BEFORE writing the view** (the exact
allauth 65.18 API is uncertain; do not code blind). Run **both** candidates against a seeded
provider and pick the one that prints the served route `/accounts/oidc/testidp/login/`:
```bash
uv run python manage.py shell -c "
from tests._sso import make_oidc_app
from django.test import RequestFactory
from django.urls import reverse
a = make_oidc_app(); r = RequestFactory().get('/')
try:
    print('provider-helper:', a.get_provider(r).get_login_url(r))
except Exception as e:
    print('provider-helper FAILED:', e)
try:
    print('reverse:', reverse('openid_connect_login', kwargs={'provider_id': a.provider_id}))
except Exception as e:
    print('reverse FAILED:', e)
# Also confirm account_signup resolves (used by the landing create-account CTA). allauth
# always registers this URL name regardless of signup policy, but verify to be safe:
try:
    print('account_signup:', reverse('account_signup'))
except Exception as e:
    print('account_signup FAILED:', e)
"
```
Use whichever prints `/accounts/oidc/testidp/login/` in Step 4 below (prefer the `reverse`
form if both work — it is deterministic and reads as the served route). Record the chosen
expression.

- [ ] **Step 4: Add the `landing` view** — in `core/views.py`, add the view, substituting
`<VERIFIED_SSO_URL_EXPR>` with the call confirmed in Step 4a (shown with the deterministic
`reverse` form, the recommended default):
```python
def landing(request):
    """Public marketing entry. Authenticated users are bounced to the dashboard."""
    if request.user.is_authenticated:
        return redirect("home")
    from allauth.socialaccount.models import SocialApp

    app = (
        SocialApp.objects.filter(provider="openid_connect").order_by("pk").first()
    )
    sso_enabled = app is not None
    # URL confirmed in Step 4a to equal /accounts/oidc/<provider_id>/login/.
    sso_login_url = (
        reverse("openid_connect_login", kwargs={"provider_id": app.provider_id})
        if app
        else None
    )
    return render(
        request,
        "core/landing.html",
        {
            "sso_enabled": sso_enabled,
            "sso_login_url": sso_login_url,
            "signup_open": get_site_config()["signup_policy"] == "open",
        },
    )
```
`reverse` is already imported in `core/views.py` (from 0d‑1). If Step 4a proved only the
provider-helper form works, use `app.get_provider(request).get_login_url(request)` instead.
Step 7's `test_landing_sso_button_visibility_and_url` pins the served path, so a wrong choice
fails loudly there.

- [ ] **Step 5: Add the root route** — in `config/urls.py`, add a `landing` import **on its
own line** (the repo's isort is `force-single-line`; do NOT merge into
`from core.views import home, landing`, which fails `ruff check` I001). The two import lines:
```python
from core.views import home
from core.views import landing
```
and add the pattern **after** `home/` and **before** the empty-prefix includes:
```python
    path("home/", home, name="home"),
    path("", landing, name="landing"),
    path("", include("core.urls")),
```

- [ ] **Step 6: Create the template** — `templates/core/landing.html`:
```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{{ site.name|default:"libli" }}{% endblock %}
{% block content %}
<section class="landing-hero">
  <p class="eyebrow">{{ site.name|default:"libli" }} · {% trans "learning platform" %}</p>
  <h1>{% trans "Everything you’re learning, in one calm place." %}</h1>
  <p class="lead">
    {% trans "Lessons, quizzes and your progress — for every class, on any device." %}
  </p>
  <div class="cta">
    <a class="btn" href="{% url 'account_login' %}">{% trans "Log in" %}</a>
    {% if sso_enabled %}
      <a class="btn btn--ghost" href="{{ sso_login_url }}">{% trans "Continue with SSO" %}</a>
    {% endif %}
    {% if signup_open %}
      <a class="btn--ghost" href="{% url 'account_signup' %}">{% trans "Create your account" %}</a>
    {% endif %}
  </div>
  <div class="landing-visual" aria-hidden="true">
    <div class="card">Hiszpański A2 · 62%</div>
    <div class="card">Matematyka · 30%</div>
    <div class="card">Biology · 88%</div>
  </div>
  {# Phase 3: open-courses teaser — conditional on Course.objects.filter(open=True) #}
</section>
<footer class="landing-footer">
  <span class="brand">libli<span class="brand__dot">.</span></span>
  <span>· {{ site.name|default:"libli" }}</span>
  <span class="app-header__spacer"></span>
  <span>{% trans "Privacy" %}</span>
  <span>{% trans "Help" %}</span>
  <span aria-hidden="true">EN / PL</span>
</footer>
{% endblock %}
```
> The `landing-hero`/`landing-visual`/`landing-footer`/`eyebrow`/`lead`/`cta` classes are
> landing-specific; add minimal rules for them to `core/static/core/css/app.css` (a hero
> grid, the eyebrow uppercase/accent, the footer flex row) using existing tokens. No new
> tokens. (Pixel-exactness is not tested; keep it tidy and theme-aware.)

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_surfaces.py -k landing -v` → PASS (all five).
Run: `uv run python -m pytest -q` → all green.

- [ ] **Step 8: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add config/urls.py core/views.py core/context_processors.py templates/core/landing.html core/static/core/css/app.css tests/test_surfaces.py
git commit -m "feat(core): public landing page (hero, SSO/signup CTAs, deferred catalog)"
```

---

### Task 8: i18n re-clamp — extend `LanguageSeederMiddleware`

**Files:**
- Modify: `core/middleware.py`
- Test: append to `tests/test_surfaces.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_surfaces.py`:
```python
@pytest.mark.django_db
def test_reclamp_resets_disabled_session_language(client):
    from institution.models import Institution

    user = make_verified_user(username="rc", email="rc@school.edu")
    user.language = "pl"
    user.save()
    client.force_login(user)
    # Pin the session language explicitly so the test isolates the re-clamp branch and
    # does not depend on login-receiver timing. (force_login DOES fire user_logged_in
    # in Django 5.2 — 0d-1 relies on it — but pinning here keeps the test focused.)
    session = client.session
    session["_language"] = "pl"
    session.save()
    assert client.session["_language"] == "pl"
    inst = Institution.load()
    inst.enabled_languages = ["en"]  # disable pl
    inst.default_language = "en"
    inst.save()
    client.get(reverse("home"))  # seeder observes pl-disabled -> resets to en
    assert client.session["_language"] == "en"
    user.refresh_from_db()
    assert user.language == "pl"  # stored choice NOT mutated
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_surfaces.py -k reclamp -v`
Expected: FAIL — session stays `"pl"` (current seeder only acts when the key is absent).

- [ ] **Step 3: Restructure the seeder** — in `core/middleware.py`, replace the body of
`LanguageSeederMiddleware.__call__` (the part before `response = self.get_response(request)`):
```python
    def __call__(self, request):
        cfg = get_site_config()  # one cached read serves both branches
        value = request.session.get(LANGUAGE_SESSION_KEY)
        if not value:
            # Absent (or empty): seed default when the resolved candidate is disabled.
            candidate = translation.get_language_from_request(request)
            if candidate not in cfg["enabled_languages"]:
                request.session[LANGUAGE_SESSION_KEY] = cfg["default_language"]
        elif value not in cfg["enabled_languages"]:
            # Present but disabled (e.g. a PA just disabled it): re-clamp to default.
            request.session[LANGUAGE_SESSION_KEY] = cfg["default_language"]
        response = self.get_response(request)
        if getattr(request, "_libli_clear_theme", False):
            response.delete_cookie(COOKIE_THEME, path="/", samesite="Lax")
        return response
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_surfaces.py -k reclamp -v` → PASS.
Run: `uv run python -m pytest -q` → all green (the 0d‑1 i18n tests still pass — the
absent-key branch is preserved verbatim).

- [ ] **Step 5: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add core/middleware.py tests/test_surfaces.py
git commit -m "feat(core): re-clamp session language to enabled set (0d-1 follow-up)"
```

---

### Task 9: Error pages — 403 / 404 / 500

**Files:**
- Create: `templates/403.html`, `templates/404.html`, `templates/500.html`
- Test: append to `tests/test_surfaces.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_surfaces.py`:
```python
@pytest.mark.django_db
def test_404_renders_branded(client):
    resp = client.get("/this-path-does-not-exist/")
    assert resp.status_code == 404
    assert b"libli" in resp.content  # shell brand present


@pytest.mark.django_db
def test_500_template_is_self_contained():
    from django.template.loader import render_to_string

    from core.services import ACCENT_DEFAULT
    from core.services import PRIMARY_DEFAULT

    html = render_to_string("500.html").lower()  # NO request/context
    assert "app-header" not in html  # does NOT extend the shell
    # Drift guard, case-insensitive so a lowercase-hex formatter doesn't break it.
    assert PRIMARY_DEFAULT.lower() in html
    assert ACCENT_DEFAULT.lower() in html
    # Source guard: no request-dependent tags (they'd render empty here but break the
    # real empty-context 500 handler).
    from pathlib import Path

    from django.conf import settings

    src = (Path(settings.BASE_DIR) / "templates/500.html").read_text(encoding="utf-8")
    for tag in ("{% url", "{% trans", "{% static", "{% blocktrans"):
        assert tag not in src
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_surfaces.py -k "404_renders or 500_template" -v`
Expected: FAIL — `404.html` not found / default 404 lacks "libli"; `500.html` missing.
> If `render_to_string("500.html")` raises `TemplateDoesNotExist`, that is the expected
> failure for the 500 test.

- [ ] **Step 3: Create `templates/404.html`**:
```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Page not found" %} · libli{% endblock %}
{% block content %}
<div class="card">
  <h1>{% trans "Page not found" %}</h1>
  <p class="helptext">{% trans "We couldn’t find that page." %}</p>
  <p><a class="btn" href="/">{% trans "Back to home" %}</a></p>
</div>
{% endblock %}
```

- [ ] **Step 4: Create `templates/403.html`**:
```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Access denied" %} · libli{% endblock %}
{% block content %}
<div class="card">
  <h1>{% trans "Access denied" %}</h1>
  <p class="helptext">{% trans "You don’t have permission to view this page." %}</p>
  <p><a class="btn" href="/">{% trans "Back to home" %}</a></p>
</div>
{% endblock %}
```

- [ ] **Step 5: Create `templates/500.html`** — self-contained, NO context processors,
NO `{% url %}`/`{% trans %}`/`{% static %}`-with-context, NO shell extension:
```django
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Something went wrong · libli</title>
  <style>
    /* Literal default brand — intentionally duplicated from core/services.py
       (PRIMARY_DEFAULT / ACCENT_DEFAULT). No token cascade: this page renders with
       an empty Context() (no context processors) and must not depend on collected
       static, which can itself be the cause of a 500. */
    body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      background: #F4F1EA; color: #1E1C18; margin: 0;
      display: flex; min-height: 100vh; align-items: center; justify-content: center; }
    .box { max-width: 28rem; padding: 2rem; background: #FFFFFF;
      border: 1px solid #E7E1D6; border-radius: 12px; text-align: center; }
    .brand { font-weight: 700; font-size: 1.25rem; color: #147E78; }
    .brand .dot { color: #C77B2A; }
    a { color: #147E78; }
  </style>
</head>
<body>
  <div class="box">
    <p class="brand">libli<span class="dot">.</span></p>
    <h1>Something went wrong</h1>
    <p>An unexpected error occurred. Please try again.</p>
    <p><a href="/">Back to home</a></p>
  </div>
</body>
</html>
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_surfaces.py -k "404_renders or 500_template" -v` → PASS.
Run: `uv run python -m pytest -q` → all green.
> `403.html` is exercised indirectly by `test_institution_settings_non_pa_forbidden`
> (Task 4): with the template present, Django's default `handler403` now renders it; the
> status assertion (403) still holds.

- [ ] **Step 7: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add templates/403.html templates/404.html templates/500.html tests/test_surfaces.py
git commit -m "feat(core): branded 403/404 + self-contained 500 error pages"
```

---

### Task 10: i18n — extract and translate new 0d‑2 UI strings

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po` (+`.mo`), `locale/pl/LC_MESSAGES/django.po` (+`.mo`)

> Tasks 3–9 added many `{% trans %}`/`{% blocktrans %}` strings (dashboard, settings,
> landing, error pages). Extract them, write **real Polish**, and compile — matching the
> 0d‑1 i18n contract.

- [ ] **Step 1: Confirm gettext is available**

Run: `msgfmt --version` (Bash tool). If missing, use the Python fallback in Step 3.

- [ ] **Step 2: Extract messages** (repeated `-l` and the comma form `-l en,pl` are both
valid Django; use whichever matches the 0d‑1 workflow — check the prior i18n commit
`ad70fdb` if unsure). After running, **confirm BOTH `.po` files were updated** (not just one):
```bash
uv run python manage.py makemessages -l en -l pl
```
Expected: `locale/en/LC_MESSAGES/django.po` and `locale/pl/LC_MESSAGES/django.po` gain the
new `msgid`s (landing headline/lead/CTAs, "Settings", "Institution settings", "My learning",
"Teaching", "Administration", "Save", "Change password", error-page strings, etc.).

- [ ] **Step 3: Fill in translations**

In `locale/pl/LC_MESSAGES/django.po`, provide real Polish `msgstr` for every new empty
entry (e.g. `"Settings"` → `"Ustawienia"`, `"My learning"` → `"Moja nauka"`, `"Save"` →
`"Zapisz"`, `"Page not found"` → `"Nie znaleziono strony"`, etc.). **Pin `"Log in"` →
`"Zaloguj się"` exactly** — the EN↔PL E2E test (Task 11 #4) asserts the substring `Zaloguj`
after switching to Polish, so this specific `msgstr` is load-bearing.
Leave `locale/en/LC_MESSAGES/django.po` `msgstr`s as the English source (or copy `msgid`).
Then compile:
```bash
uv run python manage.py compilemessages
```
(Fallback if no gettext: hand-edit the `.po` files and run
`uv run python -m django.bin.django-admin compilemessages`, or
`uv run python Tools/i18n/msgfmt.py` — whichever 0d‑1 used.)

- [ ] **Step 4: Verify a known string renders in Polish**
```bash
uv run python manage.py shell -c "from django.utils import translation; translation.activate('pl'); from django.utils.translation import gettext as _; print(_('Settings'))"
```
Expected: prints the Polish translation (e.g. `Ustawienia`).

- [ ] **Step 5: Run the suite + checks**

Run: `uv run python -m pytest -q` → all green.
Run: `uv run python manage.py check` → no issues.

- [ ] **Step 6: Commit**
```bash
git add locale/
git commit -m "i18n(0d2): extract new UI strings; Polish translations; compile"
```

---

### Task 11: Playwright E2E smoke suite + CI

**Files:**
- Modify: `pyproject.toml`, `.github/workflows/ci.yml`
- Create: `tests/test_e2e_smoke.py`

- [ ] **Step 1: Add the dependency + marker + default exclusion** — in `pyproject.toml`:

Add to `[dependency-groups].dev`:
```toml
    "pytest-playwright>=0.5.0",
```
Change `[tool.pytest.ini_options]`:
```toml
[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings.test"
python_files = ["test_*.py"]
addopts = "-q -m 'not e2e'"
markers = ["e2e: browser end-to-end tests (excluded by default; run with -m e2e)"]
```
Then — **save the `pyproject.toml` edits first**, then install (so `uv sync` regenerates
`uv.lock` with the new dependency, which Step 5 commits):
```bash
uv sync
uv run playwright install chromium
```

- [ ] **Step 2: Write the E2E suite** — create `tests/test_e2e_smoke.py`:
```python
"""Playwright smoke suite — the JS/no-flash critical path the Django test client
cannot observe. Marked `e2e` (excluded from the default run); needs a browser.

Uses pytest-django's `live_server` (transactional DB, committed so the server
thread sees seeded data) + pytest-playwright's `page`."""

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


def _login(page, live_server, username, password=TEST_PASSWORD):
    page.goto(f"{live_server.url}/accounts/login/")
    page.fill("input[name='login']", username)
    page.fill("input[name='password']", password)
    page.click("button[type='submit'], input[type='submit']")


@pytest.mark.django_db(transaction=True)
def test_boot_and_static_load(page, live_server):
    failures = []
    page.on("response", lambda r: failures.append(r.url) if r.status >= 400 else None)
    page.goto(f"{live_server.url}/")
    assert page.locator(".brand").first.is_visible()  # shell header booted
    assert page.locator(".landing-hero").is_visible()  # landing-specific content rendered
    # No head-linked asset (css/js/fonts) 404s — self-adjusting, no hardcoded names.
    asset_failures = [u for u in failures if any(
        u.endswith(ext) for ext in (".css", ".js", ".woff2"))]
    assert asset_failures == [], asset_failures


@pytest.mark.django_db(transaction=True)
def test_login_lands_on_themed_dashboard(page, live_server):
    make_verified_user(username="e2euser", email="e2e@school.edu")
    _login(page, live_server, "e2euser")
    page.wait_for_url(f"{live_server.url}/home/")
    assert page.locator("header.app-header").is_visible()


@pytest.mark.django_db(transaction=True)
def test_theme_toggle_persists_across_reload(page, live_server):
    make_verified_user(username="e2etheme", email="e2et@school.edu")
    # Emulate a DARK OS pref so the seeded user's `auto` theme resolves to a visible
    # "dark" first, and the toggle's auto->light step produces an observable
    # data-theme flip (dark -> light). Without this, `auto` resolves to "light" under
    # Playwright's default light scheme and the first click leaves data-theme unchanged.
    page.emulate_media(color_scheme="dark")
    _login(page, live_server, "e2etheme")
    page.wait_for_url(f"{live_server.url}/home/")
    before = page.locator("html").get_attribute("data-theme")  # "dark"
    page.click("[data-theme-toggle]")  # auto -> light
    after = page.locator("html").get_attribute("data-theme")  # "light"
    assert after != before
    # cookie written client-side
    assert any(c["name"] == "libli_theme" for c in page.context.cookies())
    page.reload()
    assert page.locator("html").get_attribute("data-theme") == after


@pytest.mark.django_db(transaction=True)
def test_language_switch_renders_polish(page, live_server):
    page.goto(f"{live_server.url}/")
    page.click("button[name='language'][value='pl']")
    assert page.locator("html").get_attribute("lang") == "pl"
    # Task 10 pins "Log in" -> "Zaloguj się"; assert that exact translation is live.
    assert "Zaloguj" in page.content()


@pytest.mark.django_db(transaction=True)
def test_no_flash_auto_pref_resolves_dark_before_paint(page, live_server):
    # Guarantee the anonymous default theme is auto — don't rely on cross-test DB
    # state under transactional live_server.
    from institution.models import Institution

    inst = Institution.load()
    inst.default_theme = "auto"
    inst.save()
    # Server renders data-theme="light" for an auto pref; emulating a dark OS pref
    # must flip data-theme to "dark" via the pre-paint script.
    page.emulate_media(color_scheme="dark")
    page.goto(f"{live_server.url}/")
    assert page.locator("html").get_attribute("data-theme") == "dark"
    assert page.locator("html").get_attribute("data-theme-pref") == "auto"
```
> Notes: (1) `live_server` upgrades the DB to transactional and commits, so the
> `@pytest.mark.django_db(transaction=True)` seeds are visible to the server thread
> (the autouse `_enable_db_access(db)` is compatible — transactional wins). (2) The
> allauth login field is named `login`; the password field `password`. If a selector
> doesn't match, inspect `/accounts/login/` markup and adjust. (3) Adjust the Polish
> assertion to whatever string Task 10 actually translated.

- [ ] **Step 3: Run the E2E suite locally**

Run: `uv run python -m pytest -m e2e -v`
Expected: 5 passed. (If the login selectors differ, fix per the note and re-run.)
Then confirm the default run still excludes e2e and stays green:
Run: `uv run python -m pytest -q` → all green, e2e deselected.

- [ ] **Step 4: Wire CI** — in `.github/workflows/ci.yml`, **append the two e2e steps at the
very end of the `steps:` list, after the existing `setup_roles` step** (the current tail is
`uv run python -m pytest`, then `uv run python manage.py migrate`, then
`uv run python manage.py setup_roles` — the e2e steps go *after* `setup_roles`, not between
pytest and migrate). The result tail:
```yaml
      - run: uv run python -m pytest
      - run: uv run python manage.py migrate        # verify the real deploy path
      - run: uv run python manage.py setup_roles     # asserts seed_roles works post-migrate
      - run: uv run playwright install --with-deps chromium
      - run: uv run python -m pytest -m e2e
```
> The Postgres service + env are already present; `--with-deps` installs the browser's
> system libs on the ubuntu runner. The first `pytest` step stays browser-free via the
> `-m 'not e2e'` default in `addopts`; the appended `-m e2e` step runs only the browser suite.

- [ ] **Step 5: Commit**
```bash
uv run ruff format .
uv run ruff check .
git add pyproject.toml uv.lock tests/test_e2e_smoke.py .github/workflows/ci.yml
git commit -m "test(0d2): Playwright E2E smoke suite (critical path) + CI job"
```

---

## Final verification (run before opening the PR)

- [ ] `uv run ruff format --check .` → clean
- [ ] `uv run ruff check .` → clean
- [ ] `uv run python manage.py makemigrations --check --dry-run` → `No changes detected`
- [ ] `uv run python manage.py check` → no issues
- [ ] `uv run python -m pytest -q` → all green (e2e deselected)
- [ ] `uv run python -m pytest -m e2e` → 5 passed
- [ ] `collectstatic` succeeds, then clean up (run via the Bash tool / Git Bash):
```bash
uv run python manage.py collectstatic --noinput
rm -rf staticfiles
```

## Self-review

- **Spec coverage:** DoD #1 landing (Task 7) ✓; #2 dashboard scaffold (Tasks 2, 6) ✓;
  #3 user settings (Task 3) ✓; #4 institution settings (Task 4) ✓; #5 error pages (Task 9)
  ✓; #6 Playwright E2E (Task 11) ✓; #7 green suite/ruff/check/no-migration (Final
  verification) ✓. i18n re-clamp (Task 8) ✓; account-menu navigation (Task 5) ✓;
  `signup_policy` in bundle (Task 1) ✓; new-string translation (Task 10) ✓.
- **Type/name consistency:** `core:user_settings`/`core:institution_settings` reverse
  names are used identically in views, templates, and tests; `signup_open`/`sso_enabled`/
  `sso_login_url` context keys match the landing template; `is_student`/`is_teacher`/
  `is_course_admin`/`is_platform_admin` flags are produced by `user_roles` (Task 2) and
  consumed in `home.html` (Task 6) + `base.html` (Task 5); `LANGUAGE_SESSION_KEY`/
  `COOKIE_THEME`/`SESSION_KEY`/`THEME_VALUES` reuse the 0d‑1 names.
- **No placeholders:** every code/template/test step shows complete content; the two
  flagged uncertainties (the OIDC `get_login_url` API and the allauth login-form selectors)
  carry concrete primary code, a pinning test, and an exact verification command + fallback.
- **Ordering:** settings URLs (Tasks 3–4) precede the templates that reverse them (Tasks 5–6);
  `user_roles` (Task 2) precedes its consumers; `signup_policy` (Task 1) precedes the landing
  (Task 7); translations (Task 10) precede the EN↔PL E2E (Task 11). Every task leaves the
  suite green and committed.
```
