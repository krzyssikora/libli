# Auth / login redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stock-allauth auth screens with libli's warm-teal centered auth card (login #15 to mockup fidelity, siblings to their accepted mockups, long-tail pages cleanly inheriting), and fold in the #9b-i18n JS-notice carry-over — closing the Phase-1b UX-triage backlog.

**Architecture:** One centered-card layout built once by overriding `templates/allauth/layouts/entrance.html` (the verified common ancestor of every entrance page); `base.html` gains block hooks (`header`/`body_class`/`main_class`/`extra_head`/`extra_body`) so the layout reskins the chrome without duplicating the `<head>`. Hero templates (login/signup/reset/invite/sso-not-provisioned) are bespoke plain-HTML forms in `auth.css`'s token-only vocabulary; long-tail pages split by parent chain into Bucket A (entrance → centered) and Bucket B (manage → existing full shell). No new models, migrations, or Python views.

**Tech Stack:** Django 5.2, django-allauth 65.18, server-rendered templates, token-driven bespoke CSS (`color-mix`, light/dark), Playwright e2e, pytest, ruff, gettext (PL).

**Spec:** `docs/superpowers/specs/2026-06-18-phase-1b-auth-login-redesign-design.md`

**Conventions (verified against the repo):**
- Run Python via `uv run` (system python is 3.11; uv manages 3.13).
- Default test run excludes e2e: `uv run pytest -q` (pyproject `addopts -m 'not e2e'`). e2e: `uv run pytest -m e2e <path>`.
- `LoginForm` (allauth `account/forms.py`) fields are **`login`**, **`password`**, and **`remember`** (the last is `del`-eted when `ACCOUNT_SESSION_REMEMBER` is not `None`).
- `redirect_field` IS the allauth `LoginView` context var (stock `login.html` renders `{{ redirect_field }}`).
- `site` = `get_site_config()` dict, keys incl. `name` (coalesced to `"My Institution"`) and `signup_policy`. Exposed by the `institution_branding` context processor; **no bare `site_name` var exists**.
- The lang-switch form + theme-toggle button live in `base.html:42-54`; reuse them verbatim.
- Commit trailer: end each commit message with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

**Modify:**
- `templates/base.html` — add `{% block header %}`, `{% block body_class %}`, `{% block main_class %}app-main{% endblock %}`, `{% block extra_head %}`, `{% block extra_body %}`.
- `templates/accounts/accept_invite.html` — re-point to entrance layout, drop `form.as_p`.
- `templates/accounts/sso_not_provisioned.html` — re-point to entrance layout, card markup.
- `config/settings/test.py` — add `tests/templates` to `TEMPLATES[0]["DIRS"]` (for the extra_body probe).
- `#9b-i18n`: `courses/static/courses/js/editor.js`, `courses/static/courses/js/media_picker.js`, `courses/static/courses/js/builder.js`, `templates/courses/manage/editor/editor.html`, `templates/courses/manage/media/manager.html`, `templates/courses/manage/builder.html`, `locale/pl/LC_MESSAGES/django.po` (+ recompiled `.mo`).

**Create:**
- `templates/allauth/layouts/entrance.html` — the centered-card layout override.
- `core/static/core/css/auth.css` — token-only auth vocabulary.
- `templates/account/login.html`, `signup.html`, `password_reset.html`, `password_reset_done.html`, `password_reset_from_key.html`, `password_reset_from_key_done.html` — bespoke hero overrides.
- `tests/templates/_extra_body_probe.html` — route-free extra_body test vehicle.
- `tests/test_auth_styles.py`, `tests/test_auth_pages.py`, `tests/test_i18n_auth.py`, `tests/test_e2e_auth.py`.

---

## Task 1: `base.html` block hooks (the reskin seam)

**Files:**
- Modify: `templates/base.html`
- Test: `tests/test_auth_pages.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_auth_pages.py`:

```python
"""Unit/integration tests for the auth redesign (no Playwright — Django test client)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE_TPL = ROOT / "templates" / "base.html"


def test_base_html_exposes_reskin_blocks():
    body = BASE_TPL.read_text(encoding="utf-8")
    for block in (
        "{% block header %}",
        "{% block body_class %}",
        "{% block main_class %}",
        "{% block extra_head %}",
        "{% block extra_body %}",
    ):
        assert block in body, f"base.html must declare {block}"
    # The header block must wrap the existing app-header (not replace it).
    assert "app-header" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_auth_pages.py::test_base_html_exposes_reskin_blocks -v`
Expected: FAIL (blocks not present yet).

- [ ] **Step 3: Edit `templates/base.html`**

Wrap the `<html>`/`<body>`/`<main>` tags and header. Apply these exact edits:

`<html ...>` line — add a body-class hook on `<body>` (line 35):
```html
<body class="{% block body_class %}{% endblock %}">
```

Wrap the header (lines 36-76) so the whole `<header class="app-header">…</header>` is enclosed:
```html
  {% block header %}
  <header class="app-header">
    ... (existing header markup unchanged) ...
  </header>
  {% endblock %}
```

`<main>` tag (line 77):
```html
  <main class="{% block main_class %}app-main{% endblock %}">
```

In `<head>`, immediately after the `{% block extra_css %}{% endblock %}` line (line 33):
```html
  {% block extra_head %}{% endblock %}
```

Just before `{% block extra_js %}{% endblock %}` / `</body>` (after the `ui.js` script, line 85), add:
```html
  {% block extra_body %}{% endblock %}
```

Leave the messages loop, stylesheet links, `{% brand_vars %}`, pre-paint script, and `ui.js` exactly where they are.

- [ ] **Step 4: Run tests to verify they pass + nothing regressed**

Run: `uv run pytest tests/test_auth_pages.py::test_base_html_exposes_reskin_blocks -v`
Expected: PASS

Run: `uv run pytest -q`
Expected: PASS (existing pages render byte-identically — blocks are additive with defaults).

- [ ] **Step 5: Commit**

```bash
git add templates/base.html tests/test_auth_pages.py
git commit -m "refactor(base): add header/body/main/extra_head/extra_body block hooks

$(printf 'Reskin seam for the centered auth layout; additive (existing pages unchanged).\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 2: Entrance layout override + `auth.css` skeleton

**Files:**
- Create: `templates/allauth/layouts/entrance.html`
- Create: `core/static/core/css/auth.css`
- Create: `tests/test_auth_styles.py`
- Modify: `config/settings/test.py`
- Create: `tests/templates/_extra_body_probe.html`

- [ ] **Step 1: Write the failing style/centering/bridge guard**

Create `tests/test_auth_styles.py`:

```python
"""Regression guard for the auth redesign layout (mirrors test_settings_styles.py).

Asserts auth.css defines the bespoke .auth-* vocabulary, that the entrance override
extends base.html and re-skins the chrome, and that the extra_body bridge survives.
"""

from pathlib import Path

from django.template.loader import render_to_string

ROOT = Path(__file__).resolve().parent.parent
AUTH_CSS = ROOT / "core" / "static" / "core" / "css" / "auth.css"
ENTRANCE = ROOT / "templates" / "allauth" / "layouts" / "entrance.html"


def test_auth_css_defines_card_vocabulary():
    css = AUTH_CSS.read_text(encoding="utf-8")
    for cls in (
        ".auth-main",
        ".auth-card",
        ".auth-card__wordmark",
        ".auth-card__title",
        ".auth-label",
        ".auth-input",
        ".auth-divider",
        ".auth-sso",
        ".auth-foot",
        ".auth-error",
        ".auth-chrome",
    ):
        assert cls in css, f"auth.css must style {cls}"


def test_auth_css_is_token_only_no_raw_hex():
    # Bespoke-from-tokens rule: no hardcoded #rrggbb in auth.css.
    import re

    css = AUTH_CSS.read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "auth.css must use tokens, not raw hex"


def test_entrance_override_extends_base_and_reskins():
    body = ENTRANCE.read_text(encoding="utf-8")
    assert '{% extends "base.html" %}' in body
    assert "auth-main" in body  # main_class
    assert "auth-chrome" in body  # header reskin
    assert "core/css/auth.css" in body  # loads auth.css via extra_css
    # Must NOT redeclare an empty content block (children fill base.html's directly).
    assert "{% block content %}" not in body


def test_extra_body_bridge_renders_through():
    # A template extending the entrance chain must surface its extra_body content.
    # (tests/templates is on TEMPLATES DIRS via config/settings/test.py, Step 5.)
    out = render_to_string("_extra_body_probe.html")
    assert "EXTRA_BODY_PROBE_MARKER" in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_auth_styles.py -v`
Expected: FAIL (auth.css/entrance.html/probe missing).

- [ ] **Step 3: Create the entrance override**

Create `templates/allauth/layouts/entrance.html`:

```html
{# Overrides allauth's bundled allauth/layouts/entrance.html — the common ancestor
   of every entrance (unauthenticated) page. Centers content in the auth card and
   strips the full-shell chrome. Authenticated "manage" pages are unaffected. #}
{% extends "base.html" %}
{% load static i18n %}
{% block body_class %}auth{% endblock %}
{% block main_class %}auth-main{% endblock %}
{% block header %}
  <div class="auth-chrome">
    <form class="lang-switch" method="post" action="{% url 'core:set_ui_language' %}">
      {% csrf_token %}
      <input type="hidden" name="next" value="{{ request.path }}">
      {% for lang in languages %}
        <button type="submit" name="language" value="{{ lang.code }}"
          aria-current="{% if lang.active %}true{% else %}false{% endif %}">
          {{ lang.code|upper }}</button>
      {% endfor %}
    </form>
    <button class="btn--icon" type="button" data-theme-toggle
      data-set-theme-url="{% url 'core:set_theme' %}"
      title="{% trans 'Toggle theme' %}" aria-label="{% trans 'Toggle theme' %}">◐</button>
  </div>
{% endblock %}
{% block extra_css %}{{ block.super }}<link rel="stylesheet" href="{% static 'core/css/auth.css' %}">{% endblock %}
```

- [ ] **Step 4: Create `core/static/core/css/auth.css`**

Token-only (no raw hex). Light + dark inherit the existing `tokens.css` switch.

```css
/* Auth/entrance layout — centered card. Token-only; light/dark via tokens.css. */

.auth-main {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 2 * var(--space-6));
  padding: var(--space-8) var(--space-5);
  gap: var(--space-4);
}

.auth-chrome {
  position: absolute;
  top: var(--space-5);
  right: var(--space-5);
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.auth-card {
  width: 100%;
  max-width: 380px;
  background: var(--surface-raised);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: var(--space-8) var(--space-6) var(--space-6);
}

.auth-card__wordmark {
  font-weight: 800;
  font-size: 1.75rem;
  letter-spacing: var(--heading-letter-spacing);
  color: var(--text-primary);
}

.auth-card__title {
  margin: var(--space-4) 0 var(--space-1);
  font-size: 1.2rem;
  font-weight: 700;
  letter-spacing: var(--heading-letter-spacing);
  color: var(--text-primary);
}

.auth-card__subtitle {
  margin: 0 0 var(--space-5);
  color: var(--text-secondary);
  font-size: 0.875rem;
}

.auth-field { margin-bottom: var(--space-3); }

.auth-label {
  display: block;
  margin-bottom: var(--space-1);
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--text-secondary);
}

.auth-input {
  width: 100%;
  padding: var(--space-3);
  font: inherit;
  font-size: 0.9rem;
  color: var(--text-primary);
  background: var(--surface-sunken);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
}
.auth-input:focus { outline: 2px solid var(--primary); outline-offset: 1px; }

.auth-divider {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin: var(--space-4) 0;
  color: var(--text-tertiary);
  font-size: 0.78rem;
}
.auth-divider::before,
.auth-divider::after { content: ""; flex: 1; height: 1px; background: var(--border-default); }

.auth-sso {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-3);
  font: inherit;
  font-weight: 600;
  font-size: 0.85rem;
  color: var(--text-primary);
  background: var(--surface-sunken);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  text-decoration: none;
}
.auth-sso:hover { background: var(--surface-base); }
.auth-sso__g {
  width: 15px; height: 15px; border-radius: 50%;
  background: conic-gradient(#ea4335 0 25%, #fbbc05 0 50%, #34a853 0 75%, #4285f4 0 100%);
}

.auth-foot {
  margin-top: var(--space-4);
  text-align: center;
  font-size: 0.8rem;
  color: var(--text-tertiary);
}
.auth-foot a { color: var(--accent); font-weight: 700; text-decoration: none; }

.auth-error {
  margin-bottom: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--danger-subtle);
  border: 1px solid var(--danger);
  color: var(--text-primary);
  font-size: 0.82rem;
}

/* Long-tail allauth pages: tidy default element output inside the card (Task 7
   extends this). */
.auth-card h1 { font-size: 1.2rem; color: var(--text-primary); margin-top: 0; }
.auth-card p { color: var(--text-secondary); font-size: 0.875rem; }
```

> NOTE the `.auth-sso__g` Google glyph is the one allowed gradient using brand-fixed
> Google hues (matches the mockup); it is a third-party logo, not theme chrome. The
> `test_auth_css_is_token_only_no_raw_hex` guard must therefore **exclude** the
> `.auth-sso__g` rule — scope the regex to skip that line (e.g. filter out lines
> containing `conic-gradient`) so the brand-logo hexes don't trip the token gate.

Adjust the test from Step 1 accordingly:

```python
def test_auth_css_is_token_only_no_raw_hex():
    import re

    css = AUTH_CSS.read_text(encoding="utf-8")
    # The Google-logo conic-gradient is the one allowed brand-fixed exception.
    scanned = "\n".join(l for l in css.splitlines() if "conic-gradient" not in l)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", scanned), "auth.css must use tokens, not raw hex"
```

- [ ] **Step 5: Wire the extra_body probe**

Create `tests/templates/_extra_body_probe.html`:

```html
{% extends "allauth/layouts/entrance.html" %}
{% block extra_body %}{{ block.super }}<span>EXTRA_BODY_PROBE_MARKER</span>{% endblock %}
```

Edit `config/settings/test.py` — append the test templates dir so `render_to_string`
finds the probe. Add after the imports/STORAGES block:

```python
# Let render_to_string find route-free test-only templates (e.g. the extra_body probe).
TEMPLATES[0]["DIRS"] = [*TEMPLATES[0]["DIRS"], BASE_DIR / "tests" / "templates"]  # noqa: F405
```

- [ ] **Step 6: Run the guard + full suite**

Run: `uv run pytest tests/test_auth_styles.py -v`
Expected: PASS (all four tests).

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add templates/allauth/layouts/entrance.html core/static/core/css/auth.css tests/test_auth_styles.py tests/templates/_extra_body_probe.html config/settings/test.py
git commit -m "feat(auth): centered entrance layout + auth.css token vocabulary

$(printf 'Override allauth/layouts/entrance.html (the entrance common ancestor); token-only\nauth card CSS; style/centering/extra_body-bridge guards.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 3: `account/login.html` bespoke (#15 core)

**Files:**
- Create: `templates/account/login.html`
- Test: `tests/test_auth_pages.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_auth_pages.py`:

```python
import pytest


@pytest.mark.django_db
def test_login_page_renders_bespoke_card(client):
    resp = client.get("/accounts/login/")
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'class="auth-card"' in html
    assert "auth-card__wordmark" in html
    assert "Sign in to" in html            # title (institution name follows)
    assert 'name="login"' in html
    assert 'name="password"' in html
    assert 'name="csrfmiddlewaretoken"' in html
    assert "{{ form.as_p }}" not in html
    assert "form.as_p" not in html


@pytest.mark.django_db
def test_login_preserves_next_redirect(client):
    resp = client.get("/accounts/login/?next=/dashboard/")
    html = resp.content.decode()
    assert 'name="next"' in html
    assert "/dashboard/" in html


@pytest.mark.django_db
def test_login_title_uses_institution_name_not_libli(client):
    resp = client.get("/accounts/login/")
    html = resp.content.decode()
    # Default unconfigured institution name is "My Institution" (services._DEFAULTS).
    assert "My Institution" in html
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_auth_pages.py -k login -v`
Expected: FAIL (stock allauth login.html, no `.auth-card`).

- [ ] **Step 3: Create `templates/account/login.html`**

```html
{% extends "allauth/layouts/entrance.html" %}
{% load i18n socialaccount %}
{% block head_title %}{% blocktranslate with site_name=site.name %}Sign in · {{ site_name }}{% endblocktranslate %}{% endblock %}
{% block content %}
<div class="auth-card">
  <div class="auth-card__wordmark">libli<span class="brand__dot">.</span></div>
  <h1 class="auth-card__title">{% blocktranslate with site_name=site.name %}Sign in to {{ site_name }}{% endblocktranslate %}</h1>
  <p class="auth-card__subtitle">{% trans "Welcome back — pick up where you left off." %}</p>

  <form method="post" action="{% url 'account_login' %}">
    {% csrf_token %}
    {{ redirect_field }}
    {% if form.non_field_errors %}
      <div class="auth-error">{{ form.non_field_errors }}</div>
    {% endif %}

    <div class="auth-field">
      <label class="auth-label" for="{{ form.login.id_for_label }}">{% trans "Username or email" %}</label>
      {% if form.login %}
        <input class="auth-input" type="text" name="{{ form.login.html_name }}"
               id="{{ form.login.id_for_label }}" value="{{ form.login.value|default:'' }}"
               autocomplete="username" autofocus>
      {% else %}{{ form.login }}{% endif %}
      {% if form.login.errors %}<div class="auth-error">{{ form.login.errors }}</div>{% endif %}
    </div>

    <div class="auth-field">
      <label class="auth-label" for="{{ form.password.id_for_label }}">{% trans "Password" %}</label>
      {% if form.password %}
        <input class="auth-input" type="password" name="{{ form.password.html_name }}"
               id="{{ form.password.id_for_label }}" autocomplete="current-password">
      {% else %}{{ form.password }}{% endif %}
      {% if form.password.errors %}<div class="auth-error">{{ form.password.errors }}</div>{% endif %}
    </div>

    {% if form.remember %}
      <div class="auth-field">
        <label class="auth-label">{{ form.remember }} {% trans "Remember me" %}</label>
      </div>
    {% endif %}

    <button class="btn" type="submit" style="width:100%">{% trans "Sign in" %}</button>
  </form>

  {% block sso %}{% endblock %}

  <p class="auth-foot">
    {% if site.signup_policy == "open" %}
      {% trans "No account?" %} <a href="{% url 'account_signup' %}">{% trans "Sign up" %}</a>
    {% else %}
      {% trans "No account? Ask your administrator." %}
    {% endif %}
  </p>
</div>
{% endblock %}
```

> The `{% block sso %}{% endblock %}` placeholder is filled in Task 4 — kept empty here
> so this task ships a working, testable login page on its own.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth_pages.py -k login -v`
Expected: PASS (3 login tests).

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/account/login.html tests/test_auth_pages.py
git commit -m "feat(auth): bespoke login page to V2 mockup (#15)

$(printf 'Token-styled card: wordmark, institution title (blocktranslate-with alias),\nnamed login/password fields, redirect_field preserved, policy-gated footer.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 4: Login SSO block

**Files:**
- Modify: `templates/account/login.html`
- Test: `tests/test_auth_pages.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_auth_pages.py`:

```python
from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site


def _seed_oidc_app():
    app = SocialApp.objects.create(
        provider="openid_connect", provider_id="testidp", name="Test IdP",
        client_id="cid", secret="sec",
    )
    app.sites.add(Site.objects.get_current())
    return app


@pytest.mark.django_db
def test_login_shows_sso_when_provider_configured(client):
    _seed_oidc_app()
    html = client.get("/accounts/login/").content.decode()
    assert "auth-sso" in html
    assert "auth-divider" in html
    assert "Continue with" in html


@pytest.mark.django_db
def test_login_hides_sso_when_no_provider(client):
    html = client.get("/accounts/login/").content.decode()
    assert "auth-sso" not in html
    assert "auth-divider" not in html
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_auth_pages.py -k sso -v`
Expected: FAIL (the `sso` block is empty; no `.auth-sso`).

- [ ] **Step 3: Fill the `{% block sso %}` in `templates/account/login.html`**

Replace `{% block sso %}{% endblock %}` with:

```html
  {% block sso %}
  {% get_providers as socialaccount_providers %}
  {% if socialaccount_providers %}
    <div class="auth-divider">{% trans "or" %}</div>
    {% for provider in socialaccount_providers %}
      <a class="auth-sso" href="{% provider_login_url provider process='login' %}">
        {% if provider.id == "openid_connect" %}<span class="auth-sso__g" aria-hidden="true"></span>{% endif %}
        {% blocktranslate with provider_name=provider.name %}Continue with {{ provider_name }}{% endblocktranslate %}
      </a>
    {% endfor %}
  {% endif %}
  {% endblock %}
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_auth_pages.py -k sso -v`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/account/login.html tests/test_auth_pages.py
git commit -m "feat(auth): SSO button on login (conditional, OIDC glyph)

$(printf 'allauth socialaccount tags; divider+button only when a provider is configured;\nGoogle glyph keyed on provider.id == openid_connect.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 5: `signup.html` + `accept_invite.html`

**Files:**
- Create: `templates/account/signup.html`
- Modify: `templates/accounts/accept_invite.html`
- Test: `tests/test_auth_pages.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_auth_pages.py`:

```python
from institution.models import Institution
from core.services import get_site_config


def _set_signup_open():
    # Mirror test_surfaces.py: flip the Institution singleton to open signup and
    # bust the site-config cache so get_site_config() reflects it.
    inst, _ = Institution.objects.get_or_create(pk=1)
    inst.signup_policy = "open"
    inst.save()
    get_site_config.cache_clear() if hasattr(get_site_config, "cache_clear") else None


@pytest.mark.django_db
def test_signup_renders_card_no_as_p(client):
    _set_signup_open()
    resp = client.get("/accounts/signup/")
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'class="auth-card"' in html
    assert "form.as_p" not in html
    assert 'name="csrfmiddlewaretoken"' in html


@pytest.mark.django_db
def test_accept_invite_template_has_no_as_p():
    body = (ROOT / "templates" / "accounts" / "accept_invite.html").read_text(encoding="utf-8")
    assert "form.as_p" not in body
    assert "auth-card" in body
```

> If `_set_signup_open()`'s singleton/cache mechanics differ from the real helper,
> mirror exactly what `tests/test_surfaces.py` does to set `signup_policy` — that file
> already exercises the open vs invite branch.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_auth_pages.py -k "signup or invite" -v`
Expected: FAIL.

- [ ] **Step 3: Create `templates/account/signup.html`**

```html
{% extends "allauth/layouts/entrance.html" %}
{% load i18n %}
{% block head_title %}{% trans "Create your account" %}{% endblock %}
{% block content %}
<div class="auth-card">
  <div class="auth-card__wordmark">libli<span class="brand__dot">.</span></div>
  <h1 class="auth-card__title">{% trans "Create your account" %}</h1>
  <form method="post" action="{% url 'account_signup' %}">
    {% csrf_token %}
    {{ redirect_field }}
    {% if form.non_field_errors %}<div class="auth-error">{{ form.non_field_errors }}</div>{% endif %}
    {% for field in form.visible_fields %}
      <div class="auth-field">
        <label class="auth-label" for="{{ field.id_for_label }}">{{ field.label }}</label>
        {{ field }}
        {% if field.errors %}<div class="auth-error">{{ field.errors }}</div>{% endif %}
        {% if field.help_text %}<small class="auth-foot" style="text-align:left">{{ field.help_text|safe }}</small>{% endif %}
      </div>
    {% endfor %}
    <button class="btn" type="submit" style="width:100%">{% trans "Sign up" %}</button>
  </form>
  <p class="auth-foot">{% trans "Already have an account?" %} <a href="{% url 'account_login' %}">{% trans "Sign in" %}</a></p>
</div>
{% endblock %}
```

> The generic `{{ field }}` widgets won't carry `.auth-input` automatically. Add a CSS
> rule to `auth.css` so they read clean: `.auth-card input:not([type=checkbox]):not([type=radio]), .auth-card select { width:100%; padding:var(--space-3); font:inherit; color:var(--text-primary); background:var(--surface-sunken); border:1px solid var(--border-strong); border-radius:var(--radius-sm); }`. (This also benefits Task 6/7 default-widget forms.)

- [ ] **Step 4: Rewrite `templates/accounts/accept_invite.html`**

```html
{% extends "allauth/layouts/entrance.html" %}
{% load i18n %}
{% block head_title %}{% trans "Accept invitation" %}{% endblock %}
{% block content %}
<div class="auth-card">
  <div class="auth-card__wordmark">libli<span class="brand__dot">.</span></div>
  <h1 class="auth-card__title">{% trans "Accept your invitation" %}</h1>
  <p class="auth-card__subtitle">{% blocktranslate %}Creating an account for {{ email }}.{% endblocktranslate %}</p>
  <form method="post">
    {% csrf_token %}
    {% if form.non_field_errors %}<div class="auth-error">{{ form.non_field_errors }}</div>{% endif %}
    {% for field in form.visible_fields %}
      <div class="auth-field">
        <label class="auth-label" for="{{ field.id_for_label }}">{{ field.label }}</label>
        {{ field }}
        {% if field.errors %}<div class="auth-error">{{ field.errors }}</div>{% endif %}
      </div>
    {% endfor %}
    <button class="btn" type="submit" style="width:100%">{% trans "Create account" %}</button>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests + full suite**

Run: `uv run pytest tests/test_auth_pages.py -k "signup or invite" -v`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS (existing invite-accept view tests still green — view/context unchanged).

- [ ] **Step 6: Commit**

```bash
git add templates/account/signup.html templates/accounts/accept_invite.html core/static/core/css/auth.css tests/test_auth_pages.py
git commit -m "feat(auth): signup + invite-accept to card layout (drop form.as_p)

$(printf 'Generic visible_fields loop in the shared card; default widgets styled via auth.css.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 6: Password-reset family + `sso_not_provisioned.html`

**Files:**
- Create: `templates/account/password_reset.html`, `password_reset_done.html`, `password_reset_from_key.html`, `password_reset_from_key_done.html`
- Modify: `templates/accounts/sso_not_provisioned.html`
- Test: `tests/test_auth_pages.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_auth_pages.py`:

```python
@pytest.mark.django_db
def test_password_reset_renders_card(client):
    html = client.get("/accounts/password/reset/").content.decode()
    assert 'class="auth-card"' in html
    assert "form.as_p" not in html


def test_sso_not_provisioned_template_is_card():
    body = (ROOT / "templates" / "accounts" / "sso_not_provisioned.html").read_text(encoding="utf-8")
    assert "auth-card" in body
    assert '{% extends "allauth/layouts/entrance.html" %}' in body
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_auth_pages.py -k "reset or provisioned" -v`
Expected: FAIL.

- [ ] **Step 3: Create `templates/account/password_reset.html`**

```html
{% extends "allauth/layouts/entrance.html" %}
{% load i18n %}
{% block head_title %}{% trans "Reset your password" %}{% endblock %}
{% block content %}
<div class="auth-card">
  <div class="auth-card__wordmark">libli<span class="brand__dot">.</span></div>
  <h1 class="auth-card__title">{% trans "Reset your password" %}</h1>
  <p class="auth-card__subtitle">{% trans "Enter your email and we'll send you a reset link." %}</p>
  <form method="post" action="{% url 'account_reset_password' %}">
    {% csrf_token %}
    {% if form.non_field_errors %}<div class="auth-error">{{ form.non_field_errors }}</div>{% endif %}
    {% for field in form.visible_fields %}
      <div class="auth-field">
        <label class="auth-label" for="{{ field.id_for_label }}">{{ field.label }}</label>
        {{ field }}
        {% if field.errors %}<div class="auth-error">{{ field.errors }}</div>{% endif %}
      </div>
    {% endfor %}
    <button class="btn" type="submit" style="width:100%">{% trans "Send reset link" %}</button>
  </form>
  <p class="auth-foot"><a href="{% url 'account_login' %}">{% trans "Back to sign in" %}</a></p>
</div>
{% endblock %}
```

- [ ] **Step 4: Create the three remaining reset templates**

`templates/account/password_reset_done.html`:

```html
{% extends "allauth/layouts/entrance.html" %}
{% load i18n %}
{% block head_title %}{% trans "Check your email" %}{% endblock %}
{% block content %}
<div class="auth-card">
  <div class="auth-card__wordmark">libli<span class="brand__dot">.</span></div>
  <h1 class="auth-card__title">{% trans "Check your email" %}</h1>
  <p class="auth-card__subtitle">{% trans "If an account matches, a password reset link is on its way." %}</p>
  <p class="auth-foot"><a href="{% url 'account_login' %}">{% trans "Back to sign in" %}</a></p>
</div>
{% endblock %}
```

`templates/account/password_reset_from_key.html`:

```html
{% extends "allauth/layouts/entrance.html" %}
{% load i18n %}
{% block head_title %}{% trans "Set a new password" %}{% endblock %}
{% block content %}
<div class="auth-card">
  <div class="auth-card__wordmark">libli<span class="brand__dot">.</span></div>
  <h1 class="auth-card__title">{% trans "Set a new password" %}</h1>
  {% if token_fail %}
    <p class="auth-card__subtitle">{% trans "This reset link is invalid or expired." %}</p>
    <p class="auth-foot"><a href="{% url 'account_reset_password' %}">{% trans "Request a new link" %}</a></p>
  {% else %}
    <form method="post" action="{{ action_url }}">
      {% csrf_token %}
      {% if form.non_field_errors %}<div class="auth-error">{{ form.non_field_errors }}</div>{% endif %}
      {% for field in form.visible_fields %}
        <div class="auth-field">
          <label class="auth-label" for="{{ field.id_for_label }}">{{ field.label }}</label>
          {{ field }}
          {% if field.errors %}<div class="auth-error">{{ field.errors }}</div>{% endif %}
        </div>
      {% endfor %}
      <button class="btn" type="submit" style="width:100%">{% trans "Set password" %}</button>
    </form>
  {% endif %}
</div>
{% endblock %}
```

`templates/account/password_reset_from_key_done.html`:

```html
{% extends "allauth/layouts/entrance.html" %}
{% load i18n %}
{% block head_title %}{% trans "Password changed" %}{% endblock %}
{% block content %}
<div class="auth-card">
  <div class="auth-card__wordmark">libli<span class="brand__dot">.</span></div>
  <h1 class="auth-card__title">{% trans "Password changed" %}</h1>
  <p class="auth-card__subtitle">{% trans "Your password has been updated." %}</p>
  <p class="auth-foot"><a href="{% url 'account_login' %}">{% trans "Sign in" %}</a></p>
</div>
{% endblock %}
```

- [ ] **Step 5: Rewrite `templates/accounts/sso_not_provisioned.html`**

```html
{% extends "allauth/layouts/entrance.html" %}
{% load i18n %}
{% block head_title %}{% trans "Account not provisioned" %}{% endblock %}
{% block content %}
<div class="auth-card">
  <div class="auth-card__wordmark">libli<span class="brand__dot">.</span></div>
  <h1 class="auth-card__title">{% trans "Account not provisioned" %}</h1>
  <p class="auth-card__subtitle">{% trans "Your account isn't provisioned for this platform — please contact your administrator." %}</p>
  <p class="auth-foot"><a href="{% url 'account_login' %}">{% trans "Back to sign in" %}</a></p>
</div>
{% endblock %}
```

- [ ] **Step 6: Run tests + full suite**

Run: `uv run pytest tests/test_auth_pages.py -k "reset or provisioned" -v`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add templates/account/password_reset*.html templates/accounts/sso_not_provisioned.html tests/test_auth_pages.py
git commit -m "feat(auth): password-reset family + sso-not-provisioned to card

$(printf 'Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 7: Long-tail entrance polish + `password_change` card

**Files:**
- Modify: `core/static/core/css/auth.css`
- Modify: `tests/test_auth_pages.py`

- [ ] **Step 1: Write the failing test (Bucket A centered)**

Append to `tests/test_auth_pages.py`:

```python
@pytest.mark.django_db
def test_account_inactive_inherits_centered_layout(client):
    # account_inactive extends allauth/layouts/entrance.html DIRECTLY — proves the
    # override point (entrance.html, not base_entrance.html) catches it.
    from django.template.loader import render_to_string
    out = render_to_string("account/account_inactive.html", {"site": get_site_config()})
    assert "auth-main" in out  # main_class from our override


@pytest.mark.django_db
def test_logout_stays_full_shell(client):
    # Bucket B (manage chain): logout keeps the app shell, NOT the centered card.
    from django.template.loader import render_to_string
    out = render_to_string("account/logout.html", {"site": get_site_config()})
    assert "auth-main" not in out
    assert "app-header" in out
```

> If `render_to_string` on these allauth templates raises for missing context, switch
> to asserting the rendered output of a real request through allauth's views (logout
> requires an authenticated client; account_inactive can be rendered via its view), or
> assert the parent-chain via template source inspection. Keep the invariant: Bucket A →
> `auth-main`, Bucket B → `app-header`.

- [ ] **Step 2: Run to verify the (likely) failure / smoke**

Run: `uv run pytest tests/test_auth_pages.py -k "inactive or logout" -v`
Expected: `account_inactive` PASS already (Task 2 made the override); `logout` PASS already. If `account_inactive` renders without the card styling cleanly, no CSS change needed beyond the `.auth-card`/element rules. The point of this task is the **element-styling sweep** below.

- [ ] **Step 3: Extend `auth.css` for default-element long-tail pages**

Append rules so allauth's default `{% element %}` output reads clean inside `.auth-main`
(these pages have no `.auth-card` wrapper — allauth emits `<h1>`, `<p>`, `<form>`,
`<button>`, `<ul>` directly into `content`). Wrap allauth's bare content in a card-like
band:

```css
/* Long-tail entrance pages render allauth default elements directly into auth-main
   (no .auth-card). Give that bare content a readable, centered band. */
.auth-main > h1,
.auth-main > p,
.auth-main > form,
.auth-main > .button-group { width: 100%; max-width: 380px; }
.auth-main > h1 { color: var(--text-primary); font-size: 1.3rem; text-align: center; }
.auth-main > p { color: var(--text-secondary); font-size: 0.9rem; text-align: center; }
.auth-main button[type="submit"] { width: 100%; }
```

- [ ] **Step 4: `password_change` card (Bucket B, full shell)**

`password_change` renders in the manage/full-shell. Add a CSS rule (app-shell-safe,
lives in `auth.css` which only loads on entrance pages — so instead add to the manage
surface). Simplest: since `password_change` is full-shell and authenticated, style its
form via `app.css`'s existing `.card`. Override `templates/account/password_change.html`
to wrap its allauth `{% element %}` form in a `.card`. **Verify first** whether the
settings page already links to a styled change-password flow; if `app.css` already makes
allauth manage forms legible, this is a no-op — record that and skip. Keep the boundary:
no `allauth/elements/*` overrides.

If a wrapper is warranted, create `templates/account/password_change.html`:

```html
{% extends "account/base_manage_password.html" %}
{% load allauth %}
{% block content %}
<div class="card" style="max-width:480px">
  {{ block.super }}
</div>
{% endblock %}
```

- [ ] **Step 5: Run + manual-smoke note**

Run: `uv run pytest tests/test_auth_pages.py -q`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS.

> Manual smoke (deferred to Task 10's DoD / user smoke): eyeball logout, verification_sent,
> account_inactive, password reset done in light + dark; any rough spot is a CSS rule here,
> not a template.

- [ ] **Step 6: Commit**

```bash
git add core/static/core/css/auth.css tests/test_auth_pages.py templates/account/password_change.html
git commit -m "feat(auth): long-tail entrance element styling + password_change card

$(printf 'Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 8: #9b-i18n — unify the JS conflict notice

**Files:**
- Modify: `templates/courses/manage/editor/editor.html`, `templates/courses/manage/media/manager.html`, `templates/courses/manage/builder.html`
- Modify: `courses/static/courses/js/editor.js`, `courses/static/courses/js/media_picker.js`, `courses/static/courses/js/builder.js`
- Test: `tests/test_auth_pages.py` (source assertions) — or a small `tests/test_i18n_conflict_notice.py`

- [ ] **Step 1: Write the failing source-level tests**

Create `tests/test_i18n_conflict_notice.py`:

```python
"""#9b-i18n: every JS conflict notice converges on ONE translated msgid."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANON = "This changed elsewhere — reloaded to the latest."
OLD = "This changed elsewhere — refreshed to the latest."
OLD_PICKER = "This changed elsewhere — please reload."


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_no_stale_conflict_wordings_remain():
    for rel in (
        "courses/static/courses/js/editor.js",
        "courses/static/courses/js/media_picker.js",
        "courses/static/courses/js/builder.js",
        "templates/courses/manage/builder.html",
    ):
        body = _read(rel)
        assert OLD not in body, f"{rel} still has the 'refreshed' wording"
        assert OLD_PICKER not in body, f"{rel} still has the 'please reload' wording"


def test_editor_and_manager_emit_data_msg_conflict():
    assert "data-msg-conflict" in _read("templates/courses/manage/editor/editor.html")
    assert "data-msg-conflict" in _read("templates/courses/manage/media/manager.html")


def test_canonical_wording_present_as_fallback():
    assert CANON in _read("courses/static/courses/js/editor.js")
    assert CANON in _read("courses/static/courses/js/media_picker.js")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_i18n_conflict_notice.py -v`
Expected: FAIL.

- [ ] **Step 3: Add `data-msg-conflict` to the editor root**

In `templates/courses/manage/editor/editor.html`, the `<section class="editor" ...>`
opening tag — add the attribute (alongside the existing `data-*`):

```html
<section class="editor" data-course-slug="{{ course.slug }}"
         data-picker-url="{% url 'courses:manage_media_picker' slug=course.slug %}"
         data-msg-conflict="{% trans 'This changed elsewhere — reloaded to the latest.' %}">
```

- [ ] **Step 4: Add `data-msg-conflict` to the media-manager root**

In `templates/courses/manage/media/manager.html`, the `<section class="media-manager" ...>`
opening tag — add:

```html
         data-msg-conflict="{% trans 'This changed elsewhere — reloaded to the latest.' %}"
```

(append to the existing `data-*` attribute list on that `<section>`).

- [ ] **Step 5: Wire `editor.js`**

In `courses/static/courses/js/editor.js`, add a reader near the top (after the `root`
capture, ~line 4) :

```javascript
  function msg(key, fallback) { return root.getAttribute("data-msg-" + key) || fallback; }
```

Change the line-44 conflict flash to use it:

```javascript
        if (res.status === 409) flash(msg("conflict", "This changed elsewhere — reloaded to the latest."));
```

- [ ] **Step 6: Wire `media_picker.js`**

In `courses/static/courses/js/media_picker.js`, add a reader (the `root` in scope at the
delete handler is the `.media-manager` element):

```javascript
  function msg(host, key, fallback) { return (host && host.getAttribute("data-msg-" + key)) || fallback; }
```

Change line 227:

```javascript
        else if (r.status === 409) flash(root, msg(root, "conflict", "This changed elsewhere — reloaded to the latest."));
```

> Confirm `root` is the `.media-manager` element at that call site by reading the file;
> if the picker modal uses a different root, read `data-msg-conflict` from `.editor`
> instead (both now carry the attr).

- [ ] **Step 7: Align `builder.js` + `builder.html` wording**

In `templates/courses/manage/builder.html` line 10, change "refreshed" → "reloaded":

```html
         data-msg-conflict="{% trans 'This changed elsewhere — reloaded to the latest.' %}"
```

In `courses/static/courses/js/builder.js`, change both fallback literals (lines ~158 and
~292) from `"This changed elsewhere — refreshed to the latest."` to
`"This changed elsewhere — reloaded to the latest."`.

- [ ] **Step 8: Run tests + JS-touching suite**

Run: `uv run pytest tests/test_i18n_conflict_notice.py -v`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS (builder/editor server-contract tests unaffected — only client strings changed).

- [ ] **Step 9: Commit**

```bash
git add templates/courses/manage/editor/editor.html templates/courses/manage/media/manager.html templates/courses/manage/builder.html courses/static/courses/js/editor.js courses/static/courses/js/media_picker.js courses/static/courses/js/builder.js tests/test_i18n_conflict_notice.py
git commit -m "i18n(#9b): unify JS conflict notice on the translated 'reloaded' msgid

$(printf 'editor.js/media_picker.js read data-msg-conflict; builder realigned refreshed->reloaded.\nThe .po cleanup (retire the dup msgid) is Task 9.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 9: i18n extraction, PL translations, and the per-msgid gate

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ recompiled `.mo`)
- Create: `tests/test_i18n_auth.py`

- [ ] **Step 1: Extract new strings**

Run: `uv run python manage.py makemessages -l pl`
This picks up the new `{% trans %}` / `{% blocktranslate %}` strings from the auth
templates and drops the now-unused `"…refreshed to the latest."` to obsolete (`#~`).

- [ ] **Step 2: Write the failing gate test**

Create `tests/test_i18n_auth.py` (mirrors `tests/test_i18n_ws4.py`):

```python
"""Done-gate: every NEW auth-redesign msgid is translated to PL, and the catalog
is clean (no untranslated / fuzzy / obsolete). Mirrors test_i18n_ws4.py."""

from pathlib import Path

import pytest
from django.utils import translation

ROOT = Path(__file__).resolve().parent.parent
POFILE = ROOT / "locale" / "pl" / "LC_MESSAGES" / "django.po"

AUTH_NEW_MSGIDS = [
    "Welcome back — pick up where you left off.",
    "Username or email",
    "Sign in",
    "No account? Ask your administrator.",
    "Create your account",
    "Already have an account?",
    "Reset your password",
    "Enter your email and we'll send you a reset link.",
    "Send reset link",
    "Back to sign in",
    "Check your email",
    "If an account matches, a password reset link is on its way.",
    "Set a new password",
    "This reset link is invalid or expired.",
    "Request a new link",
    "Set password",
    "Password changed",
    "Your password has been updated.",
    "Account not provisioned",
    "or",
]


@pytest.mark.parametrize("msgid", AUTH_NEW_MSGIDS)
def test_auth_msgid_translated_to_pl(msgid):
    with translation.override("pl"):
        assert str(translation.gettext(msgid)) != msgid, f"untranslated PL msgid: {msgid!r}"


def test_po_catalog_clean():
    text = POFILE.read_text(encoding="utf-8")
    # No fuzzy, no obsolete cruft.
    assert "#, fuzzy" not in text, "fuzzy entries present — review and clear"
    assert "#~" not in text, "obsolete entries present — drop them"


def test_old_refreshed_msgid_retired():
    text = POFILE.read_text(encoding="utf-8")
    assert "refreshed to the latest." not in text, "the duplicate JS msgid must be removed"
    assert "reloaded to the latest." in text, "the canonical msgid must remain"
```

> Adjust `AUTH_NEW_MSGIDS` to the exact strings `makemessages` extracted (character-for-
> character, incl. em-dash — and apostrophes). Some entries (e.g. "Sign in", "Back to sign
> in", "or") may already exist in the catalog and just gain source-location refs — keep
> them in the gate so a future rename can't silently drop the translation. The blocktranslate
> "Sign in to %(site_name)s" / "Sign in · %(site_name)s" / "Continue with %(provider_name)s"
> / "Creating an account for %(email)s." msgids must also be translated — add them in their
> exact `makemessages` placeholder form.

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_i18n_auth.py -v`
Expected: FAIL (new msgstrs empty; obsolete `#~` present).

- [ ] **Step 4: Translate + clean `django.po`**

Edit `locale/pl/LC_MESSAGES/django.po`:
- Fill the PL `msgstr` for every new auth msgid (real Polish — match the tone of the
  existing catalog). Example mappings:
  - `"Sign in"` → `"Zaloguj się"`
  - `"Username or email"` → `"Nazwa użytkownika lub e-mail"`
  - `"Welcome back — pick up where you left off."` → `"Witaj ponownie — wróć tam, gdzie skończyłeś."`
  - `"Reset your password"` → `"Zresetuj hasło"`
  - `"Back to sign in"` → `"Powrót do logowania"`
  - `"Account not provisioned"` → `"Konto nieautoryzowane"`
  - (translate the rest in the same register; mirror existing catalog choices where a
    string already appears.)
- **Delete** the obsolete (`#~`) `"…refreshed to the latest."` block entirely.
- Confirm `"This changed elsewhere — reloaded to the latest."` still has its existing PL
  `msgstr`.

- [ ] **Step 5: Compile + verify catalog is clean**

Run: `uv run python manage.py compilemessages -l pl`
Expected: no errors.

Run: `uv run pytest tests/test_i18n_auth.py -v`
Expected: PASS.

Optional audit (catalog clean):
Run: `uv run python -c "import re,io; t=open('locale/pl/LC_MESSAGES/django.po',encoding='utf-8').read(); import sys; print('fuzzy', t.count('#, fuzzy'), 'obsolete', t.count('#~'))"`
Expected: `fuzzy 0 obsolete 0`.

- [ ] **Step 6: Run full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_i18n_auth.py
git commit -m "i18n(auth): Polish for auth-redesign strings + retire dup conflict msgid

$(printf 'Per-msgid PL gate; catalog stays 0 untranslated / 0 fuzzy / 0 obsolete.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 10: Playwright e2e + DoD gate

**Files:**
- Create: `tests/test_e2e_auth.py`

- [ ] **Step 1: Write the e2e suite**

Create `tests/test_e2e_auth.py` (mirrors `tests/test_e2e_settings.py`'s harness):

```python
"""Playwright e2e for the auth/login redesign. Marked e2e (run with -m e2e)."""

import os

import pytest

from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def test_login_card_renders_and_logs_in(page, live_server, db):
    make_verified_user(username="alice", email="alice@school.edu", password=TEST_PASSWORD)
    page.goto(f"{live_server.url}/accounts/login/")
    assert page.locator(".auth-card").is_visible()
    assert page.locator(".auth-card__wordmark").is_visible()
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill("alice")
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_url(f"{live_server.url}/**")
    # Landed on an authenticated page (the app shell header returns).
    assert page.locator(".app-header").is_visible()


def test_login_language_switch_renders_polish(page, live_server, db):
    page.goto(f"{live_server.url}/accounts/login/")
    # The corner lang-switch (scoped past any other forms) flips to PL.
    page.locator(".auth-chrome form.lang-switch button[value='pl']").click()
    page.wait_for_load_state("networkidle")
    assert "Zaloguj" in page.content()


def test_login_sso_button_visible_when_provider_seeded(page, live_server, db):
    app = SocialApp.objects.create(
        provider="openid_connect", provider_id="testidp", name="Test IdP",
        client_id="cid", secret="sec",
    )
    app.sites.add(Site.objects.get_current())
    page.goto(f"{live_server.url}/accounts/login/")
    assert page.locator(".auth-sso").is_visible()


def test_login_dark_theme_card(page, live_server, db):
    page.goto(f"{live_server.url}/accounts/login/")
    page.locator(".auth-chrome [data-theme-toggle]").click()
    assert page.locator("html[data-theme='dark']").count() == 1
    assert page.locator(".auth-card").is_visible()
```

> Mirror `tests/test_e2e_settings.py` for any fixture details that differ (e.g. the exact
> `page`/`live_server` plugin wiring, `db` vs explicit transaction handling). The selector
> `form[action*='login']` and the `.auth-chrome`-scoped controls avoid the recurring libli
> header-button gotcha.

- [ ] **Step 2: Run the e2e suite**

Run: `uv run pytest -m e2e tests/test_e2e_auth.py -v`
Expected: PASS (4 tests). (Playwright browsers already installed per prior phases.)

- [ ] **Step 3: Run the full DoD gate**

```bash
uv run pytest -q                       # full suite, -m 'not e2e' by default
uv run pytest -m e2e tests/test_e2e_auth.py -v
uv run ruff check .
uv run ruff format --check .
uv run python manage.py check
uv run python manage.py makemigrations --check    # expect: no changes / no new migration
uv run python manage.py collectstatic --noinput
uv run python manage.py compilemessages -l pl
```

Expected: all green; `makemigrations --check` reports **no** new migration.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_auth.py
git commit -m "test(auth): Playwright e2e (card render, login, lang switch, SSO, dark)

$(printf 'Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

- [ ] **Step 5: Open the PR**

```bash
git push -u origin phase-1b-auth-login-redesign
gh pr create --title "Phase 1b: Auth/login redesign (#15 + bounded-full + #9b-i18n)" --body "$(cat <<'EOF'
Closes the last designed items of the Phase-1b UX-review-triage backlog.

- #15 login page → V2 warm-teal mockup (bespoke centered card)
- Shared centered auth layout via `allauth/layouts/entrance.html` override
- Signup / invite-accept / password-reset family / SSO-not-provisioned → accepted mockups
- Long-tail entrance pages inherit the card; manage pages stay full-shell
- #9b-i18n: unified JS conflict notice on the translated "reloaded" msgid

No new models/migrations/views. DoD: full suite + e2e green; ruff; check; makemigrations --check (none); collectstatic; compilemessages.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Notes for the executor

- **Static refresh:** editor/auth CSS + JS changes need `collectstatic` + a hard refresh
  (Ctrl+F5) in a running dev server (whitenoise manifest storage) — matters only for manual
  smoke, not the test suite (test settings use plain staticfiles storage).
- **Boundary discipline:** do NOT override `allauth/elements/*` or hand-design long-tail
  pages — fixes there are CSS rules in `auth.css` only (spec §3.3 non-goal).
- **No migration:** this whole plan adds none. If `makemigrations --check` reports a change,
  something modified a model — stop and investigate.
- **Manual smoke (user, after merge prep):** log in (local + with a seeded OIDC app), reset
  password, hit an invalid reset key, view account_inactive, all in light + dark + EN/PL.
```
