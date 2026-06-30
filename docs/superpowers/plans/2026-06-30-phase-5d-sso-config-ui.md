# Phase 5d — SSO Configuration UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Platform Admin a bespoke `/manage/settings/?tab=sso` form to configure the institution's single OpenID Connect SSO provider — display name, issuer URL, client id, write-only client secret, and an enable toggle — replacing Django-admin `SocialApp` editing, with the toggle governing every SSO sign-in surface (login + landing).

**Architecture:** A new `accounts/sso_config.py` service is the sole reader/writer of allauth's one `openid_connect` `SocialApp` + its `Site` link. A plain `SsoForm` (write-only secret, enable-completeness in `clean`) feeds it. The `institution` settings surface gains a 4th "SSO" tab that delegates to the service; `core/views.landing` is made Site-aware so the toggle hides its SSO button too. **No project model is added — there is no migration.**

**Tech Stack:** Django 5.2.15, django-allauth 65.18.0 (`socialaccount` + `openid_connect`), pytest + pytest-django, Playwright (e2e), gettext (EN/PL).

## Global Constraints

- **No new model / no migration.** Back the UI with allauth's existing `SocialApp`; `makemigrations --check --dry-run` must stay clean.
- **Tooling:** system `python`/`ruff`/`pytest` are NOT on PATH — always `uv run …` (`uv run pytest`, `uv run ruff check .`, `uv run ruff format .`, `uv run python manage.py …`). Run `uv run ruff format .` before every commit; `ruff check` enforces E501 (≤88 cols).
- **Single-provider invariant:** "the one row with `provider="openid_connect"`". Load and save key on `provider` only; `provider_id` defaults to the constant `"sso"` for a new row.
- **Version-pinned facts (verified):** allauth 65.18.0's `openid_connect` mounts a single parametrized route `oidc/<provider_id>/login/callback/` (and `…/login/`) at import time, so `reverse(...)` works with zero `SocialApp` rows. allauth's `wk_server_url` appends `/.well-known/openid-configuration` to the stored `server_url` iff it lacks `/.well-known/`. Django 5.2 `URLField` defaults the assumed scheme to `http` (with `RemovedInDjango60Warning`) → use `assume_scheme="https"`.
- **Write-only secret:** never render the stored secret to HTML; blank field keeps it, a typed value replaces it. No in-UI clear (admin-only) — by design.
- **Payload source:** the view passes `form.cleaned_data` (NOT `request.POST`) into the service — the `assume_scheme` rescheme and the trailing-slash `.rstrip("/")` live only in `cleaned_data`.
- **i18n:** all user-facing strings translatable; module-level form labels/help via `gettext_lazy` (eager `gettext` froze editor labels before). Add PL catalog entries, clear `#, fuzzy` flags, verify msgids, compile `.mo`.
- **No hard-coded test passwords:** use `tests.factories.TEST_PASSWORD` / the `make_pa` / `make_login` helpers.
- **Permission:** all SSO config views are gated `@login_required` + `@permission_required("institution.change_institution", raise_exception=True)` (same as the other settings tabs; the PA group holds it).
- **Every view ships styled** and is verified light/dark/mobile via throwaway Playwright screenshots before the task closes.

---

## File Structure

- **Create** `accounts/sso_config.py` — the SSO config service (constants, `effective_provider_id`, `load_sso_app`, `is_enabled`, `redirect_uri`, `save_sso_config`).
- **Modify** `accounts/forms.py` — add `SsoForm`.
- **Modify** `institution/views_manage.py` — `TABS += "sso"`; thread `request` into `_settings_context`; new `settings_sso` action; GET `settings` passes `request`.
- **Modify** `institution/urls.py` — `settings_sso` route.
- **Modify** `core/views.py` — `landing` gates SSO on Site membership + effective slug.
- **Create** `templates/institution/manage/_sso_tab.html` — the SSO form panel.
- **Modify** `templates/institution/manage/_tabs.html` — 4th tab.
- **Modify** `templates/institution/manage/settings.html` — SSO panel include.
- **Modify** `institution/static/institution/settings.css` — minimal SSO styling (redirect-URI block, toggle).
- **Create** `tests/test_sso_config.py` — service/form/view/integration tests.
- **Create** `tests/test_e2e_sso_5d.py` — one Playwright e2e (both surfaces, anonymous landing).
- **Modify** `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`) — PL translations.

---

### Task 1: SSO config service — read helpers

**Files:**
- Create: `accounts/sso_config.py`
- Test: `tests/test_sso_config.py`

**Interfaces:**
- Consumes: allauth `SocialApp`; Django `reverse`, `RequestFactory`.
- Produces:
  - `OIDC_PROVIDER = "openid_connect"`, `OIDC_PROVIDER_ID = "sso"`
  - `effective_provider_id(app) -> str` (None-tolerant; `(app.provider_id if app else "") or OIDC_PROVIDER_ID`)
  - `load_sso_app() -> SocialApp | None`
  - `is_enabled(app, site) -> bool`
  - `redirect_uri(request, app) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sso_config.py`:

```python
"""Phase 5d — SSO configuration service, form, view, and surface-gating tests."""

import pytest
from django.contrib.sites.models import Site
from django.urls import reverse

from tests._sso import make_oidc_app


def test_effective_provider_id_none_tolerant():
    from accounts.sso_config import effective_provider_id

    assert effective_provider_id(None) == "sso"


def test_redirect_uri_resolves_with_zero_rows(rf):
    from accounts.sso_config import redirect_uri

    req = rf.get("/manage/settings/")
    assert redirect_uri(req, None).endswith("/accounts/oidc/sso/login/callback/")


def test_both_oidc_routes_resolve_with_zero_rows():
    # Landing button (openid_connect_login) + callback both import-time parametrized.
    assert reverse(
        "openid_connect_login", kwargs={"provider_id": "sso"}
    ).endswith("/login/")
    assert reverse(
        "openid_connect_callback", kwargs={"provider_id": "sso"}
    ).endswith("/login/callback/")


@pytest.mark.django_db
def test_load_sso_app_returns_none_when_unconfigured():
    from accounts.sso_config import load_sso_app

    assert load_sso_app() is None


@pytest.mark.django_db
def test_load_sso_app_returns_the_oidc_row():
    from accounts.sso_config import load_sso_app

    app = make_oidc_app()
    assert load_sso_app().pk == app.pk


@pytest.mark.django_db
def test_is_enabled_reflects_site_membership():
    from accounts.sso_config import is_enabled, load_sso_app

    site = Site.objects.get_current()
    assert is_enabled(load_sso_app(), site) is False  # no row
    app = make_oidc_app()  # make_oidc_app attaches the current Site
    assert is_enabled(app, site) is True
    app.sites.remove(site)
    assert is_enabled(load_sso_app(), site) is False


@pytest.mark.django_db
def test_effective_provider_id_uses_stored_slug():
    from accounts.sso_config import effective_provider_id

    app = make_oidc_app()  # provider_id="testidp"
    assert effective_provider_id(app) == "testidp"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sso_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'accounts.sso_config'`.

- [ ] **Step 3: Write the service read-helpers**

Create `accounts/sso_config.py`:

```python
"""Platform-admin SSO (OIDC) configuration service. The single place that reads and
writes the institution's one allauth openid_connect SocialApp and its Site link, so
the form, the settings view, and the landing page all resolve the same row + slug."""

from allauth.socialaccount.models import SocialApp
from django.urls import reverse

OIDC_PROVIDER = "openid_connect"  # allauth provider key — single-provider invariant
OIDC_PROVIDER_ID = "sso"  # default slug for a NEW row -> stable redirect URI


def effective_provider_id(app):
    """The provider_id to build callback/login URLs from. None-tolerant: a fresh
    install (app is None) and a legacy blank-slug row both fall back to "sso" (NOT
    app.provider) — which is what save_sso_config canonicalizes a blank slug to."""
    return (app.provider_id if app else "") or OIDC_PROVIDER_ID


def load_sso_app():
    """The one openid_connect SocialApp, or None. order_by("pk") matches the existing
    core/views login-button query so every surface resolves the same row."""
    return SocialApp.objects.filter(provider=OIDC_PROVIDER).order_by("pk").first()


def is_enabled(app, site):
    """SSO is 'live' iff the row exists and the current Site is attached."""
    return app is not None and app.sites.filter(pk=site.pk).exists()


def redirect_uri(request, app):
    """Absolute OIDC callback URL for the PA to register with their IdP. Built from
    the request (correct scheme/host behind a proxy) and the row's effective slug."""
    return request.build_absolute_uri(
        reverse(
            "openid_connect_callback",
            kwargs={"provider_id": effective_provider_id(app)},
        )
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_sso_config.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format accounts/sso_config.py tests/test_sso_config.py
uv run ruff check accounts/sso_config.py tests/test_sso_config.py
git add accounts/sso_config.py tests/test_sso_config.py
git commit -m "feat(5d): SSO config service read-helpers (load/is_enabled/redirect_uri)"
```

---

### Task 2: SSO config service — `save_sso_config`

**Files:**
- Modify: `accounts/sso_config.py`
- Test: `tests/test_sso_config.py`

**Interfaces:**
- Consumes: `load_sso_app`, `OIDC_PROVIDER`, `OIDC_PROVIDER_ID` (Task 1); `transaction.atomic`.
- Produces: `save_sso_config(*, name, server_url, client_id, client_secret, enabled, site) -> SocialApp | None` (returns `None` on the blank-disabled no-op).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sso_config.py`:

```python
@pytest.mark.django_db
def test_save_creates_canonical_row():
    from accounts.sso_config import save_sso_config

    app = save_sso_config(
        name="Acme IdP",
        server_url="https://idp.example.com",
        client_id="cid",
        client_secret="sek",
        enabled=True,
        site=Site.objects.get_current(),
    )
    assert app.provider == "openid_connect"
    assert app.provider_id == "sso"
    assert app.settings["server_url"] == "https://idp.example.com"
    assert app.client_id == "cid"
    assert app.secret == "sek"
    assert app.sites.filter(pk=Site.objects.get_current().pk).exists()


@pytest.mark.django_db
def test_save_keeps_secret_when_blank_replaces_when_typed():
    from accounts.sso_config import save_sso_config

    site = Site.objects.get_current()
    save_sso_config(name="A", server_url="https://i.example", client_id="c",
                    client_secret="orig", enabled=True, site=site)
    # blank secret keeps it
    app = save_sso_config(name="A", server_url="https://i.example", client_id="c",
                          client_secret="", enabled=True, site=site)
    assert app.secret == "orig"
    # typed secret replaces it
    app = save_sso_config(name="A", server_url="https://i.example", client_id="c",
                          client_secret="new", enabled=True, site=site)
    assert app.secret == "new"


@pytest.mark.django_db
def test_disable_removes_site_keeps_credentials():
    from accounts.sso_config import is_enabled, save_sso_config

    site = Site.objects.get_current()
    save_sso_config(name="A", server_url="https://i.example", client_id="c",
                    client_secret="sek", enabled=True, site=site)
    app = save_sso_config(name="A", server_url="https://i.example", client_id="c",
                          client_secret="", enabled=False, site=site)
    assert is_enabled(app, site) is False
    assert app.secret == "sek"  # credentials preserved on disable


@pytest.mark.django_db
def test_blank_disabled_save_is_noop():
    from allauth.socialaccount.models import SocialApp

    from accounts.sso_config import save_sso_config

    result = save_sso_config(name="", server_url="", client_id="",
                             client_secret="", enabled=False,
                             site=Site.objects.get_current())
    assert result is None
    assert SocialApp.objects.count() == 0


@pytest.mark.django_db
def test_disabled_draft_with_one_field_persists():
    from allauth.socialaccount.models import SocialApp

    from accounts.sso_config import save_sso_config

    app = save_sso_config(name="Draft", server_url="", client_id="",
                          client_secret="", enabled=False,
                          site=Site.objects.get_current())
    assert app is not None
    assert SocialApp.objects.count() == 1
    assert app.name == "Draft"


@pytest.mark.django_db
def test_legacy_blank_slug_row_adopted_and_canonicalized():
    from allauth.socialaccount.models import SocialApp

    from accounts.sso_config import save_sso_config

    legacy = SocialApp.objects.create(provider="openid_connect", provider_id="",
                                      name="Legacy", client_id="c")
    app = save_sso_config(name="L", server_url="https://i.example", client_id="c",
                          client_secret="s", enabled=True,
                          site=Site.objects.get_current())
    assert app.pk == legacy.pk  # adopted, not duplicated
    assert app.provider_id == "sso"  # blank canonicalized
    assert SocialApp.objects.count() == 1


@pytest.mark.django_db
def test_legacy_nonblank_slug_preserved():
    from allauth.socialaccount.models import SocialApp

    from accounts.sso_config import effective_provider_id, save_sso_config

    SocialApp.objects.create(provider="openid_connect", provider_id="google",
                             name="G", client_id="c")
    app = save_sso_config(name="G", server_url="https://i.example", client_id="c",
                          client_secret="s", enabled=True,
                          site=Site.objects.get_current())
    assert app.provider_id == "google"  # non-blank slug preserved
    assert effective_provider_id(app) == "google"
    assert SocialApp.objects.count() == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sso_config.py -k save -v`
Expected: FAIL with `ImportError: cannot import name 'save_sso_config'`.

- [ ] **Step 3: Implement `save_sso_config`**

Add to `accounts/sso_config.py` (add `from django.db import transaction` to the imports):

```python
def save_sso_config(*, name, server_url, client_id, client_secret, enabled, site):
    """Adopt-or-create the single OIDC SocialApp and apply the form payload. Keys on
    `provider` so a legacy 0c-2 row is adopted (never duplicated); a blank provider_id
    is canonicalized to "sso" (a non-blank legacy slug is preserved). The secret is
    only overwritten when a non-empty value is passed. Returns the app, or None on the
    blank-disabled no-op (nothing to persist and no row exists)."""
    with transaction.atomic():
        app = load_sso_app()
        if app is None and not enabled and not any(
            (name, server_url, client_id, client_secret)
        ):
            return None  # no-op: disabled + all four inputs empty + no existing row
        if app is None:
            app = SocialApp(provider=OIDC_PROVIDER)
        if not app.provider_id:
            app.provider_id = OIDC_PROVIDER_ID  # canonicalize blank legacy slug
        app.name = name
        app.client_id = client_id
        app.settings = {**(app.settings or {}), "server_url": server_url}
        if client_secret:
            app.secret = client_secret  # blank -> keep existing
        app.save()
        if enabled:
            app.sites.add(site)
        else:
            app.sites.remove(site)
        return app
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_sso_config.py -v`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format accounts/sso_config.py tests/test_sso_config.py
uv run ruff check accounts/sso_config.py tests/test_sso_config.py
git add accounts/sso_config.py tests/test_sso_config.py
git commit -m "feat(5d): save_sso_config — adopt/canonicalize row, secret-keep, site toggle, no-op"
```

---

### Task 3: `SsoForm`

**Files:**
- Modify: `accounts/forms.py`
- Test: `tests/test_sso_config.py`

**Interfaces:**
- Consumes: `django.forms`, `gettext_lazy as _`.
- Produces: `SsoForm(*args, app=None, **kwargs)` with fields `enabled, name, server_url, client_id, client_secret`; `clean` enforces https, writes back normalized `server_url`, and enforces enable-completeness without double-reporting an already-errored field.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sso_config.py`:

```python
def _form(data, app=None):
    from accounts.forms import SsoForm

    return SsoForm(data, app=app)


@pytest.mark.django_db
def test_form_rejects_non_https_issuer():
    form = _form({"server_url": "http://idp.example.com", "enabled": False})
    assert not form.is_valid()
    assert "server_url" in form.errors


@pytest.mark.django_db
def test_form_normalizes_bare_domain_and_trailing_slash():
    form = _form({"server_url": "idp.example.test/", "enabled": False})
    assert form.is_valid(), form.errors
    assert form.cleaned_data["server_url"] == "https://idp.example.test"


@pytest.mark.django_db
def test_form_enable_requires_all_fields():
    form = _form({"enabled": True, "name": "", "server_url": "",
                  "client_id": "", "client_secret": ""})
    assert not form.is_valid()
    for field in ("name", "server_url", "client_id", "client_secret"):
        assert field in form.errors


@pytest.mark.django_db
def test_form_enable_accepts_stored_secret_with_blank_field():
    app = make_oidc_app()  # has secret="secret"
    form = _form({"enabled": True, "name": "X",
                  "server_url": "https://idp.example.com", "client_id": "c",
                  "client_secret": ""}, app=app)
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_form_enable_without_secret_errors_on_secret_field():
    form = _form({"enabled": True, "name": "X",
                  "server_url": "https://idp.example.com", "client_id": "c",
                  "client_secret": ""})  # no app -> no stored secret
    assert not form.is_valid()
    assert "client_secret" in form.errors


@pytest.mark.django_db
def test_form_invalid_issuer_while_enabling_does_not_double_report():
    # non-https + enabled: only the https error on server_url, not a spurious "required".
    form = _form({"enabled": True, "name": "X",
                  "server_url": "http://idp.example.com", "client_id": "c",
                  "client_secret": "s"})
    assert not form.is_valid()
    assert len(form.errors["server_url"]) == 1


@pytest.mark.django_db
def test_form_disabled_partial_draft_is_valid():
    form = _form({"enabled": False, "name": "Draft"})
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_form_never_renders_stored_secret():
    from accounts.forms import SsoForm

    app = make_oidc_app()
    app.secret = "topsekretsentinel"  # distinctive value (not the word "secret",
    app.save()                        # which is a substring of name="client_secret")
    form = SsoForm(app=app, initial={"name": app.name})
    assert "topsekretsentinel" not in str(form["client_secret"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sso_config.py -k form -v`
Expected: FAIL with `ImportError: cannot import name 'SsoForm'`.

- [ ] **Step 3: Add `SsoForm` to `accounts/forms.py`**

At the top of `accounts/forms.py` ensure these imports exist (add any missing):

```python
from django import forms
from django.utils.translation import gettext_lazy as _
```

Append the form class:

```python
class SsoForm(forms.Form):
    """Platform-admin OIDC SSO config. Plain Form (settings is JSON, sites is M2M,
    secret is write-only). The `app` kwarg (loaded SocialApp or None) lets `clean`
    check the stored-secret case for the enable-completeness rule."""

    enabled = forms.BooleanField(required=False, label=_("Enable SSO"))
    name = forms.CharField(
        required=False,
        max_length=40,
        label=_("Display name"),
        help_text=_("Shown on the sign-in button, e.g. 'Continue with Acme'."),
    )
    server_url = forms.URLField(
        required=False,
        assume_scheme="https",
        label=_("Issuer / discovery URL"),
        help_text=_(
            "Your IdP's issuer base URL, e.g. https://idp.example.com. The "
            "/.well-known/openid-configuration discovery path is added automatically "
            "(you may also paste a full discovery URL)."
        ),
    )
    client_id = forms.CharField(
        required=False, max_length=191, label=_("Client ID")
    )
    client_secret = forms.CharField(
        required=False,
        max_length=191,
        widget=forms.PasswordInput(render_value=False),
        label=_("Client secret"),
    )

    def __init__(self, *args, app=None, **kwargs):
        self.app = app  # stored before super() so clean() can read self.app.secret
        # Distinct auto_id: settings.html renders all four tab forms at once, and
        # BrandingForm also has a `name` field -> a default "id_%s" would emit two
        # id="id_name" inputs and the SSO label's `for` would target the wrong one.
        kwargs.setdefault("auto_id", "id_sso_%s")
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        server_url = cleaned.get("server_url", "")
        if server_url:
            if not server_url.lower().startswith("https://"):
                self.add_error("server_url", _("The issuer URL must use https."))
            else:
                # Write the normalized value back so form.cleaned_data (which the
                # view hands to the service) carries the rstrip'd issuer.
                cleaned["server_url"] = server_url.rstrip("/")
        if cleaned.get("enabled"):
            # Skip a field already carrying an error: add_error() pops it from
            # cleaned_data, so a filled-but-invalid issuer must not also draw a
            # spurious "required to enable SSO".
            for field in ("name", "server_url", "client_id"):
                if not cleaned.get(field) and field not in self.errors:
                    self.add_error(field, _("Required to enable SSO."))
            has_secret = bool(cleaned.get("client_secret")) or bool(
                self.app and self.app.secret
            )
            if not has_secret and "client_secret" not in self.errors:
                self.add_error(
                    "client_secret", _("Enter the client secret to enable SSO.")
                )
        return cleaned
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_sso_config.py -v`
Expected: PASS (all tests so far).

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format accounts/forms.py tests/test_sso_config.py
uv run ruff check accounts/forms.py tests/test_sso_config.py
git add accounts/forms.py tests/test_sso_config.py
git commit -m "feat(5d): SsoForm — write-only secret, https+normalize, enable-completeness"
```

---

### Task 4: Settings SSO tab — view, URL, context, templates

**Files:**
- Modify: `institution/views_manage.py`
- Modify: `institution/urls.py`
- Create: `templates/institution/manage/_sso_tab.html`
- Modify: `templates/institution/manage/_tabs.html`
- Modify: `templates/institution/manage/settings.html`
- Modify: `institution/static/institution/settings.css`
- Test: `tests/test_sso_config.py`

**Interfaces:**
- Consumes: `load_sso_app`, `is_enabled`, `redirect_uri`, `save_sso_config` (service); `SsoForm` (form); existing `_index_url`, `_active_tab`, `Institution`.
- Produces: URL name `institution:settings_sso`; context keys `sso`, `sso_secret_saved`, `sso_redirect_uri` on every settings render.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sso_config.py` (import the factory helpers inside each test, matching the file's inline-import style so ruff doesn't flag E402):

```python
@pytest.mark.django_db
def test_sso_tab_requires_permission(client):
    from tests.factories import make_login

    make_login(client, "student")  # non-PA
    resp = client.get(reverse("institution:settings") + "?tab=sso")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_sso_tab_get_shows_redirect_uri(client):
    from tests.factories import make_pa

    make_pa(client)
    resp = client.get(reverse("institution:settings") + "?tab=sso")
    assert resp.status_code == 200
    assert b"/accounts/oidc/sso/login/callback/" in resp.content


@pytest.mark.django_db
def test_sso_post_valid_saves_and_redirects(client):
    from allauth.socialaccount.models import SocialApp

    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(reverse("institution:settings_sso"), {
        "enabled": "on", "name": "Acme",
        "server_url": "idp.example.test/", "client_id": "cid",
        "client_secret": "sek",
    })
    assert resp.status_code == 302
    assert resp.url == reverse("institution:settings") + "?tab=sso"
    app = SocialApp.objects.get(provider="openid_connect")
    # end-to-end normalization proves the view passed cleaned_data, not POST:
    assert app.settings["server_url"] == "https://idp.example.test"


@pytest.mark.django_db
def test_sso_post_invalid_rerenders_without_saving(client):
    from allauth.socialaccount.models import SocialApp

    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(reverse("institution:settings_sso"), {
        "enabled": "on", "name": "", "server_url": "", "client_id": "",
        "client_secret": "",
    })
    assert resp.status_code == 200
    assert SocialApp.objects.count() == 0  # nothing persisted on invalid


@pytest.mark.django_db
def test_sso_post_blank_disabled_is_noop(client):
    from allauth.socialaccount.models import SocialApp

    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(reverse("institution:settings_sso"), {"enabled": ""})
    assert resp.status_code == 302
    assert SocialApp.objects.count() == 0


@pytest.mark.django_db
def test_sso_action_get_redirects(client):
    from tests.factories import make_pa

    make_pa(client)
    resp = client.get(reverse("institution:settings_sso"))
    assert resp.status_code == 302
    assert resp.url == reverse("institution:settings") + "?tab=sso"


@pytest.mark.django_db
def test_sso_context_present_on_other_tab_invalid_post(client):
    # An invalid POST to the access tab still renders the always-present SSO panel.
    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(reverse("institution:settings_access"),
                       {"signup_policy": "not-a-choice"})
    assert resp.status_code == 200
    assert b"/accounts/oidc/sso/login/callback/" in resp.content
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sso_config.py -k "sso_tab or sso_post or sso_action or sso_context" -v`
Expected: FAIL — `NoReverseMatch` for `institution:settings_sso` (and template/context missing).

- [ ] **Step 3: Wire the URL**

In `institution/urls.py`, add inside `urlpatterns` (after the `uploads` path):

```python
    path(
        "manage/settings/sso/",
        views_manage.settings_sso,
        name="settings_sso",
    ),
```

- [ ] **Step 4: Update the view module**

In `institution/views_manage.py`:

Add imports near the top:

```python
from django.contrib.sites.shortcuts import get_current_site

from accounts.forms import SsoForm
from accounts.sso_config import is_enabled
from accounts.sso_config import load_sso_app
from accounts.sso_config import redirect_uri
from accounts.sso_config import save_sso_config
```

Change `TABS`:

```python
TABS = ("branding", "access", "uploads", "sso")
```

Replace `_settings_context` with the request-threaded version that always builds the SSO sub-context:

```python
def _settings_context(
    request, inst, active_tab, *, branding=None, access=None, uploads=None, sso=None
):
    """Assemble the four-form context. Any bound (errored) form passed in is used as-is;
    the rest are unbound — the three institution forms seeded from `inst`, the SSO form
    seeded from the service. The SSO sub-context is built on EVERY render because
    settings.html renders all four panels (inactive ones just hidden)."""
    app = load_sso_app()
    site = get_current_site(request)
    return {
        "active_tab": active_tab,
        "branding": branding or BrandingForm(instance=inst),
        "access": access or AccessForm(instance=inst),
        "uploads": uploads or UploadsForm(instance=inst),
        "sso": sso
        or SsoForm(
            app=app,
            initial={
                "enabled": is_enabled(app, site),
                "name": app.name if app else "",
                "server_url": (app.settings or {}).get("server_url", "") if app else "",
                "client_id": app.client_id if app else "",
            },
        ),
        "sso_secret_saved": bool(app and app.secret),
        "sso_redirect_uri": redirect_uri(request, app),
    }
```

Update the GET `settings` view to pass `request`:

```python
@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings(request):
    inst = Institution.load()
    ctx = _settings_context(request, inst, _active_tab(request))
    return render(request, "institution/manage/settings.html", ctx)
```

Update `_action` to thread `request` into the context builder (only the `_settings_context` call changes):

```python
    ctx = _settings_context(request, inst, tab, **{ctx_key: form})
    return render(request, "institution/manage/settings.html", ctx)
```

Add the new action view at the end of the file:

```python
@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_sso(request):
    if request.method == "GET":
        return redirect(_index_url("sso"))  # method contract: actions are POST targets
    form = SsoForm(request.POST, app=load_sso_app())
    if form.is_valid():
        cd = form.cleaned_data
        # Payload MUST come from cleaned_data (rescheme + rstrip live only there).
        saved = save_sso_config(
            name=cd["name"],
            server_url=cd["server_url"],
            client_id=cd["client_id"],
            client_secret=cd["client_secret"],
            enabled=cd["enabled"],
            site=get_current_site(request),
        )
        if saved is not None:
            messages.success(request, _("SSO settings saved."))
        else:
            messages.info(request, _("Nothing to save."))
        return redirect(_index_url("sso"))
    inst = Institution.load()
    return render(
        request,
        "institution/manage/settings.html",
        _settings_context(request, inst, "sso", sso=form),
    )
```

- [ ] **Step 5: Add the SSO tab + panel to the templates**

In `templates/institution/manage/_tabs.html`, add before `</nav>`:

```html
  <a class="settings__tab{% if active_tab == 'sso' %} is-on{% endif %}"
     href="{% url 'institution:settings' %}?tab=sso">{% trans "SSO" %}</a>
```

In `templates/institution/manage/settings.html`, add after the `uploads` panel div:

```html
  <div data-tab="sso" {% if active_tab != "sso" %}hidden{% endif %}>
    {% include "institution/manage/_sso_tab.html" %}
  </div>
```

Create `templates/institution/manage/_sso_tab.html`:

```html
{% load i18n %}
<form class="settings__form" method="post" action="{% url 'institution:settings_sso' %}">
  {% csrf_token %}
  {{ sso.non_field_errors }}

  {% comment %} ── Enable toggle ── {% endcomment %}
  <div class="settings__section">
    <h2 class="settings__section-title">{% trans "Single sign-on" %}</h2>
    <div class="settings__field">
      <label class="settings__label">{{ sso.enabled }} {{ sso.enabled.label }}</label>
      <span class="settings__help">{% trans "When off, the SSO sign-in button is hidden everywhere but your saved credentials are kept." %}</span>
      {{ sso.enabled.errors }}
    </div>
  </div>

  {% comment %} ── Provider credentials ── {% endcomment %}
  <div class="settings__section">
    <h2 class="settings__section-title">{% trans "Provider" %}</h2>

    <div class="settings__field">
      <label class="settings__label" for="{{ sso.name.id_for_label }}">{{ sso.name.label }}</label>
      {{ sso.name }}
      {% if sso.name.help_text %}<span class="settings__help">{{ sso.name.help_text }}</span>{% endif %}
      {{ sso.name.errors }}
    </div>

    <div class="settings__field">
      <label class="settings__label" for="{{ sso.server_url.id_for_label }}">{{ sso.server_url.label }}</label>
      {{ sso.server_url }}
      {% if sso.server_url.help_text %}<span class="settings__help">{{ sso.server_url.help_text }}</span>{% endif %}
      {{ sso.server_url.errors }}
    </div>

    <div class="settings__field">
      <label class="settings__label" for="{{ sso.client_id.id_for_label }}">{{ sso.client_id.label }}</label>
      {{ sso.client_id }}
      {{ sso.client_id.errors }}
    </div>

    <div class="settings__field">
      <label class="settings__label" for="{{ sso.client_secret.id_for_label }}">{{ sso.client_secret.label }}</label>
      {{ sso.client_secret }}
      {% if sso_secret_saved %}
        <span class="settings__help">{% trans "A client secret is saved. Leave blank to keep it; enter a value to replace it." %}</span>
      {% else %}
        <span class="settings__help">{% trans "Enter the client secret from your IdP." %}</span>
      {% endif %}
      {% if sso.errors and sso_secret_saved %}
        <span class="settings__help">{% trans "Re-enter the client secret if you were changing it." %}</span>
      {% endif %}
      {{ sso.client_secret.errors }}
    </div>
  </div>

  {% comment %} ── Redirect URI (read-only, for IdP registration) ── {% endcomment %}
  <div class="settings__section">
    <h2 class="settings__section-title">{% trans "Redirect URI" %}</h2>
    <div class="settings__field">
      <input class="settings__input settings__redirect-uri" type="text" readonly
             value="{{ sso_redirect_uri }}" aria-label="{% trans 'Redirect URI' %}"
             onclick="this.select()">
      <span class="settings__help">{% trans "Register this redirect URI with your identity provider." %}</span>
      <span class="settings__help">{% trans "If this shows http://, your deployment's HTTPS proxy header isn't configured; register the https:// form." %}</span>
    </div>
  </div>

  <div class="settings__actions">
    <button class="btn" type="submit">{% trans "Save SSO settings" %}</button>
  </div>
</form>
```

> Note: reuse `settings__input` if `_access_tab.html`/`_uploads_tab.html` already define inputs with that class; if the existing tabs use a different input class, match theirs. The read-only redirect-URI field adds the extra `settings__redirect-uri` modifier for styling.

- [ ] **Step 6: Add minimal styling**

In `institution/static/institution/settings.css`, append (adapt to the file's existing token names — match the surrounding `--border-strong` / `--surface` variables actually used in the file):

```css
/* Phase 5d — SSO redirect-URI display */
.settings__redirect-uri {
  width: 100%;
  font-family: var(--font-mono, monospace);
  font-size: 0.9rem;
  cursor: text;
}
```

- [ ] **Step 7: Run the tests + check migrations**

Run: `uv run pytest tests/test_sso_config.py -v`
Expected: PASS (all service/form/view tests).

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected` (no model added).

- [ ] **Step 8: Verify the tab renders styled (screenshots)**

Write a throwaway Playwright script (delete after review) that logs in a PA, opens `/manage/settings/?tab=sso`, and screenshots light + dark + a 390px-wide mobile viewport. Confirm: the toggle, four fields, "secret saved" hint state, and the read-only redirect-URI block render correctly and match the other tabs. Delete the script when satisfied.

- [ ] **Step 9: Format and commit**

```bash
uv run ruff format institution/views_manage.py tests/test_sso_config.py
uv run ruff check institution/views_manage.py
git add institution/views_manage.py institution/urls.py \
  templates/institution/manage/_sso_tab.html \
  templates/institution/manage/_tabs.html \
  templates/institution/manage/settings.html \
  institution/static/institution/settings.css tests/test_sso_config.py
git commit -m "feat(5d): /manage/settings/ SSO tab — view, URL, context, template, styling"
```

---

### Task 5: Landing-surface gating + both-surface integration

**Files:**
- Modify: `core/views.py` (the `landing` view, around lines 45-63)
- Test: `tests/test_sso_config.py`

**Interfaces:**
- Consumes: `load_sso_app`, `is_enabled`, `effective_provider_id` (service); `get_current_site`; `reverse`.
- Produces: `landing` renders `sso_enabled`/`sso_login_url` gated on Site membership; both login and landing surfaces honor the toggle.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sso_config.py`:

```python
@pytest.mark.django_db
def test_landing_button_follows_toggle_for_anonymous_visitor(client):
    from accounts.sso_config import save_sso_config

    site = Site.objects.get_current()
    save_sso_config(name="Acme", server_url="https://idp.example.com",
                    client_id="c", client_secret="s", enabled=True, site=site)
    resp = client.get("/")  # anonymous -> landing renders
    assert resp.status_code == 200
    assert b"/accounts/oidc/sso/login/" in resp.content

    save_sso_config(name="Acme", server_url="https://idp.example.com",
                    client_id="c", client_secret="", enabled=False, site=site)
    resp = client.get("/")
    assert b"/accounts/oidc/sso/login/" not in resp.content


@pytest.mark.django_db
def test_login_page_button_follows_toggle(client):
    from accounts.sso_config import save_sso_config

    site = Site.objects.get_current()
    save_sso_config(name="Acme", server_url="https://idp.example.com",
                    client_id="c", client_secret="s", enabled=True, site=site)
    resp = client.get(reverse("account_login"))
    assert b"oidc/sso/login/" in resp.content  # get_providers is site-aware

    save_sso_config(name="Acme", server_url="https://idp.example.com",
                    client_id="c", client_secret="", enabled=False, site=site)
    resp = client.get(reverse("account_login"))
    assert b"oidc/sso/login/" not in resp.content
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sso_config.py -k "landing_button or login_page_button" -v`
Expected: `test_landing_button_follows_toggle_for_anonymous_visitor` **FAILS** — `landing` is still non-site-aware (`sso_enabled = app is not None`), so its disabled-state assertion fails. `test_login_page_button_follows_toggle` already **PASSES** (the login page uses the site-aware `{% get_providers %}` and depends only on `save_sso_config` from Task 2) — it's a regression guard, not a red test for this task.

- [ ] **Step 3: Make `landing` Site-aware**

In `core/views.py`, replace the SSO block inside `landing` (currently):

```python
    app = SocialApp.objects.filter(provider="openid_connect").order_by("pk").first()
    sso_enabled = app is not None
    # URL confirmed in Step 4a to equal /accounts/oidc/<provider_id>/login/.
    sso_login_url = (
        reverse("openid_connect_login", kwargs={"provider_id": app.provider_id})
        if app
        else None
    )
```

with:

```python
    from django.contrib.sites.shortcuts import get_current_site

    from accounts.sso_config import effective_provider_id, is_enabled, load_sso_app

    app = load_sso_app()
    sso_enabled = is_enabled(app, get_current_site(request))  # toggle = Site attached
    sso_login_url = (
        reverse(
            "openid_connect_login",
            kwargs={"provider_id": effective_provider_id(app)},
        )
        if sso_enabled
        else None
    )
```

(The existing `from allauth.socialaccount.models import SocialApp` import in `landing` becomes unused — remove it if it's local to the function; if it's a module-level import used elsewhere, leave it.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_sso_config.py -v`
Expected: PASS (whole file).

- [ ] **Step 5: Format and commit**

```bash
uv run ruff format core/views.py tests/test_sso_config.py
uv run ruff check core/views.py
git add core/views.py tests/test_sso_config.py
git commit -m "feat(5d): landing SSO button gates on Site membership (toggle governs all surfaces)"
```

---

### Task 6: e2e — configure → enable → landing button (real gestures)

**Files:**
- Create: `tests/test_e2e_sso_5d.py`

**Interfaces:**
- Consumes: the full stack (Tasks 1-5); Playwright; `tests.factories.TEST_PASSWORD`.

- [ ] **Step 1: Write the e2e test**

Create `tests/test_e2e_sso_5d.py` (mirror the structure of `tests/test_e2e_settings_5c.py` — reuse its `_make_pa_user`, its `live_server`/`page` fixtures, and its login flow; adapt the assertions below):

```python
"""Playwright e2e for Phase 5d: a PA configures + enables SSO via the settings tab,
then an anonymous visitor sees the landing SSO button; disabling hides it.

Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest
from django.contrib.auth.models import Group as AuthGroup

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    from accounts.emails import ensure_verified_primary_email
    from accounts.models import User
    from institution.roles import PLATFORM_ADMIN, seed_roles

    seed_roles()
    user = User.objects.create_user(
        username=username, email=f"{username}@school.edu", password=TEST_PASSWORD
    )
    ensure_verified_primary_email(user, f"{username}@school.edu")
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    return user


@pytest.mark.django_db(transaction=True)
def test_sso_enable_shows_landing_button_then_disable_hides_it(live_server, page):
    _make_pa_user("pa")

    # Log in as PA (drive the real login form).
    page.goto(live_server.url + "/accounts/login/")
    page.fill("input[name='login']", "pa")
    page.fill("input[name='password']", TEST_PASSWORD)
    page.click("button[type='submit']")

    # Configure + enable SSO on the settings tab.
    page.goto(live_server.url + "/manage/settings/?tab=sso")
    # Scope to the SSO <form>: settings.html renders all four tab forms at once, and
    # BrandingForm also has input[name='name'] -> a bare selector is strict-mode-ambiguous.
    sso = "form[action*='settings/sso/'] "
    page.check(sso + "input[name='enabled']")
    page.fill(sso + "input[name='name']", "Acme IdP")
    page.fill(sso + "input[name='server_url']", "https://idp.example.com")
    page.fill(sso + "input[name='client_id']", "client-123")
    page.fill(sso + "input[name='client_secret']", "shh-secret")
    page.click(sso + "button[type='submit']")
    assert "tab=sso" in page.url

    # Anonymous visitor: log out, then the landing page shows the SSO button.
    page.goto(live_server.url + "/accounts/logout/")
    page.click("button[type='submit']")  # allauth logout confirm
    page.goto(live_server.url + "/")
    assert page.locator("a[href*='oidc/sso/login/']").count() == 1

    # Re-auth, disable, and confirm the anonymous landing button is gone.
    page.goto(live_server.url + "/accounts/login/")
    page.fill("input[name='login']", "pa")
    page.fill("input[name='password']", TEST_PASSWORD)
    page.click("button[type='submit']")
    page.goto(live_server.url + "/manage/settings/?tab=sso")
    page.uncheck(sso + "input[name='enabled']")
    page.click(sso + "button[type='submit']")

    page.goto(live_server.url + "/accounts/logout/")
    page.click("button[type='submit']")
    page.goto(live_server.url + "/")
    assert page.locator("a[href*='oidc/sso/login/']").count() == 0
```

> If `test_e2e_settings_5c.py` uses different fixture names or a helper login function, match those exactly. The key requirements: drive the real form gestures (no `page.evaluate` shortcut), and assert the landing button in a **logged-out** context (the landing view redirects authenticated users to `/home`).

- [ ] **Step 2: Run the e2e test**

Run: `uv run pytest tests/test_e2e_sso_5d.py -m e2e -v`
Expected: PASS (button present after enable, absent after disable).

- [ ] **Step 3: Format and commit**

```bash
uv run ruff format tests/test_e2e_sso_5d.py
uv run ruff check tests/test_e2e_sso_5d.py
git add tests/test_e2e_sso_5d.py
git commit -m "test(5d): e2e — PA enables SSO, anonymous landing button appears/disappears"
```

---

### Task 7: Polish language (PL) translations

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `django.mo`)

**Interfaces:**
- Consumes: the new `{% trans %}` / `gettext_lazy` msgids from Tasks 3-4.

- [ ] **Step 1: Extract new message strings**

Run: `uv run python manage.py makemessages -l pl`
This adds the new SSO msgids to `locale/pl/LC_MESSAGES/django.po` (untranslated, and possibly `#, fuzzy`-flagged copies of similar strings).

- [ ] **Step 2: Translate the new msgids and clear fuzzy flags**

Edit `locale/pl/LC_MESSAGES/django.po`. For each new msgid below, set the `msgstr` and **remove any `#, fuzzy` line** above it (fuzzy entries are ignored at runtime, and makemessages can mis-guess — verify each):

```
"Enable SSO"                         -> "Włącz logowanie SSO"
"Display name"                       -> "Nazwa wyświetlana"
"Shown on the sign-in button, e.g. 'Continue with Acme'."
                                     -> "Wyświetlana na przycisku logowania, np. „Kontynuuj z Acme”."
"Issuer / discovery URL"             -> "Adres wydawcy / discovery"
"Your IdP's issuer base URL, e.g. https://idp.example.com. The /.well-known/openid-configuration discovery path is added automatically (you may also paste a full discovery URL)."
                                     -> "Bazowy adres wydawcy Twojego dostawcy tożsamości, np. https://idp.example.com. Ścieżka /.well-known/openid-configuration jest dodawana automatycznie (możesz też wkleić pełny adres discovery)."
"Client ID"                          -> "Identyfikator klienta"
"Client secret"                      -> "Sekret klienta"
"The issuer URL must use https."     -> "Adres wydawcy musi używać https."
"Required to enable SSO."            -> "Wymagane do włączenia SSO."
"Enter the client secret to enable SSO."
                                     -> "Podaj sekret klienta, aby włączyć SSO."
"SSO settings saved."                -> "Ustawienia SSO zapisane."
"Nothing to save."                   -> "Brak zmian do zapisania."
"SSO"                                -> "SSO"
"Single sign-on"                     -> "Logowanie jednokrotne (SSO)"
"Provider"                           -> "Dostawca"
"When off, the SSO sign-in button is hidden everywhere but your saved credentials are kept."
                                     -> "Po wyłączeniu przycisk logowania SSO jest ukryty wszędzie, ale zapisane dane uwierzytelniające pozostają."
"A client secret is saved. Leave blank to keep it; enter a value to replace it."
                                     -> "Sekret klienta jest zapisany. Pozostaw puste, aby go zachować; wpisz wartość, aby go zmienić."
"Enter the client secret from your IdP."
                                     -> "Podaj sekret klienta od swojego dostawcy tożsamości."
"Re-enter the client secret if you were changing it."
                                     -> "Wpisz ponownie sekret klienta, jeśli go zmieniałeś."
"Redirect URI"                       -> "Adres przekierowania (Redirect URI)"
"Register this redirect URI with your identity provider."
                                     -> "Zarejestruj ten adres przekierowania u swojego dostawcy tożsamości."
"If this shows http://, your deployment's HTTPS proxy header isn't configured; register the https:// form."
                                     -> "Jeśli widoczne jest http://, nagłówek proxy HTTPS Twojego wdrożenia nie jest skonfigurowany; zarejestruj wersję https://."
"Save SSO settings"                  -> "Zapisz ustawienia SSO"
```

- [ ] **Step 3: Verify no untranslated/fuzzy SSO msgids remain**

Run: `uv run python manage.py makemessages -l pl` again, then grep the new strings to confirm each has a non-empty `msgstr` and no `#, fuzzy` flag:

Run: `grep -n "fuzzy" locale/pl/LC_MESSAGES/django.po`
Expected: none of the SSO entries are listed (other pre-existing fuzzies, if any, are out of scope — do not touch them).

- [ ] **Step 4: Compile**

Run: `uv run python manage.py compilemessages -l pl`
Expected: compiles `django.mo` without error.

- [ ] **Step 5: Quick PL render check**

Run: `uv run pytest tests/test_sso_config.py -k sso_tab -v`
Expected: still PASS (translations don't change structure). Optionally load `/manage/settings/?tab=sso` with `?lang=pl` (or the app's language switch) in a screenshot to confirm Polish copy renders.

- [ ] **Step 6: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(5d): Polish translations for the SSO settings tab"
```

---

## Final verification (run after all tasks)

- [ ] `uv run pytest` — full suite green (incl. new `tests/test_sso_config.py`).
- [ ] `uv run pytest -m e2e tests/test_e2e_sso_5d.py` — e2e green.
- [ ] `uv run ruff check .` and `uv run ruff format --check .` — clean.
- [ ] `uv run python manage.py makemigrations --check --dry-run` — `No changes detected`.
- [ ] `uv run python manage.py check` — clean.
- [ ] Manual: configure an OIDC provider end-to-end from `/manage/settings/?tab=sso`, confirm the write-only secret never appears in page source (view-source on the SSO tab), confirm the redirect URI is shown, and confirm enable/disable shows/hides the login + landing buttons.
