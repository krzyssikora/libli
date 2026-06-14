# Phase 0d‑1 — UI Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up libli's UI foundation — a `core` app with a bespoke token-driven CSS system, the reusable app shell, per-institution `color-mix()` theming, light/dark/auto theme handling, and EN/PL i18n — then restyle the existing auth + home pages into the real warm-teal identity.

**Architecture:** A new `core` app owns base templates, static CSS/JS/fonts, two context processors, a cached read-only institution accessor, theme/language write views, and a language-seeder middleware. `tokens.css` derives the whole palette from two raw vars (`--brand-primary`/`--brand-accent`) via `color-mix()`; a `branding` template tag injects only those two vars (after `tokens.css`) when an institution overrides them. A pre-paint inline script resolves `auto`→OS theme with no flash. `LocaleMiddleware` activates the session language; a seeder keeps anonymous users within `Institution.enabled_languages`.

**Tech Stack:** Python 3.13 (uv), Django 5.2, django-allauth 65.18, PostgreSQL (psycopg 3), bespoke CSS (no framework; seeded from sibling `../bonnot/`), self-hosted Inter, pytest + pytest-django, ruff.

This plan implements [the Phase 0d‑1 spec](../specs/2026-06-14-phase-0d1-ui-foundation-design.md), refining [Phase 0 foundations](../specs/2026-06-13-phase-0-foundations-design.md) §5–§7 and the [design language](../../design-language.md).

---

## Execution environment

Developer machine is **Windows (win32)**, PowerShell primary, but every `bash` block here is **POSIX sh** and must run through the **Bash tool / Git Bash**. Always invoke Python through **`uv run python ...`** (system `python` is 3.11; uv manages 3.13). PostgreSQL from Plan 0a: role `libli` / password `libli` / database `libli` on `localhost:5432`. Run `uv run ruff format .` before **every** commit; `ruff check` enforces 88-column lines (E501) on all files including comments/docstrings — keep them ≤88 cols. Test fixture password is `tests.factories.TEST_PASSWORD`; `make_verified_user(username=..., email=...)` exists. Tests run under `DJANGO_SETTINGS_MODULE=config.settings.test` (pytest is already configured for this).

**i18n tooling:** `makemessages`/`compilemessages` require GNU **gettext** (`msgfmt`, `xgettext`) on PATH. On Windows install via the gettext binaries or `choco install gettext`; verify with `msgfmt --version` (Bash tool). If gettext is unavailable, Task 10 will note the fallback (hand-write the `.po` and compile with Python's `msgfmt.py`).

## Verified-against-source facts (drive specific decisions)

1. `accounts.User` has `theme` (choices light/dark/auto, **default `"auto"`**, never empty) and `language` (choices en/pl, default `"en"`) and `display_name` (blank). `__str__` returns `display_name or username`.
2. `institution.Institution` is a singleton (`load()` does `get_or_create(pk=1)` — a **write**), with `name`, `logo` (nullable `ImageField`), `enabled_languages` (JSON, default `["en","pl"]`), `default_language` (`"en"`), `default_theme` (`"auto"`). `BrandColor(institution FK related_name="brand_colors", key SlugField, value CharField max_length=64)`; seeded `primary=#147E78`, `accent=#C77B2A` (migration `institution/0002_seed_branding.py`).
3. Current `MIDDLEWARE` (config/settings/base.py:35-45): Security, WhiteNoise, **Session**, Common, Csrf, Authentication, Message, XFrameOptions, allauth Account. `CACHES` is **not** defined (Django default = LocMemCache). `CSRF_COOKIE_HTTPONLY` is **not** set (default `False`).
4. `TEMPLATES["OPTIONS"]["context_processors"]` currently has exactly: request, auth, messages (base.py:56-60).
5. `config/views.py` holds only `home` (`@login_required`, `render(request, "home.html")`); `config/urls.py` has `path("home/", home, name="home")` and `LOGIN_REDIRECT_URL = "home"`. `templates/base.html` is a barebones stub; `templates/allauth/layouts/base.html` is `{% extends "base.html" %}`.

## File Structure

```
core/                                 # NEW app
├── __init__.py
├── apps.py                           # AppConfig; ready() connects cache-invalidation signals
├── services.py                       # get_site_config() cached read-only accessor + defaults
├── context_processors.py             # institution_branding, ui_prefs
├── middleware.py                     # LanguageSeederMiddleware
├── signals.py                        # user_logged_in/out receivers (lang seed, cookie clear)
├── views.py                          # home (relocated); set_ui_language; set_theme
├── urls.py                           # app_name="core"; /home/, /ui/set-language/, /ui/set-theme/
├── templatetags/__init__.py
├── templatetags/branding.py         # {% brand_vars %} inline <style>
└── static/core/{css,js,fonts/inter}/ # tokens.css, reset.css, app.css, ui.js, Inter woff2
institution/
└── validators.py                     # NEW: validate_css_color (shared by model + tag)
templates/
├── base.html                         # rewritten shell
├── core/home.html                    # relocated placeholder
└── allauth/layouts/base.html         # extends the shell with hide_auth_cta
config/
├── settings/base.py                  # +core app, +middleware, +LANGUAGES/LOCALE_PATHS, +ctx procs
├── settings/test.py                  # staticfiles storage override (no manifest in tests)
├── urls.py                           # include("core.urls"); drop home import
└── views.py                          # DELETED (home moved; healthz lives in urls.py)
locale/{en,pl}/LC_MESSAGES/django.po(+.mo)   # NEW
tests/test_ui_foundation.py           # NEW
```

---

### Task 1: `core` app skeleton + relocate `home` + URL/app wiring

**Files:**
- Create: `core/__init__.py`, `core/apps.py`, `core/views.py`, `core/urls.py`, `templates/core/home.html`
- Modify: `config/settings/base.py` (INSTALLED_APPS), `config/urls.py`
- Delete: `config/views.py`, `templates/home.html`
- Test: `tests/test_ui_foundation.py`

- [ ] **Step 1: Write the failing tests** — create `tests/test_ui_foundation.py`:
```python
import pytest
from django.urls import reverse

from tests.factories import make_verified_user


@pytest.fixture(autouse=True)
def _clear_site_cache():
    # Defined here in Task 1 ON PURPOSE (forward reference) so every later task's
    # tests inherit it. It is a harmless no-op until Task 3 adds the cached
    # site-config, which uses LocMemCache (NOT transaction-scoped) — without this a
    # BrandColor set in one test would leak into the next.
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_home_url_name_resolves_and_path_unchanged():
    assert reverse("home") == "/home/"


@pytest.mark.django_db
def test_home_requires_login_anonymous_redirects(client):
    resp = client.get("/home/")
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_home_authenticated_returns_200(client):
    user = make_verified_user(username="alice", email="alice@school.edu")
    client.force_login(user)
    resp = client.get("/home/")
    assert resp.status_code == 200
    assert b"alice" in resp.content
```

- [ ] **Step 2: Run the tests to capture the baseline**

Run: `uv run python -m pytest tests/test_ui_foundation.py -v`
This task is a **refactor**: `home` already exists at `config/views.py`, so all three tests
should PASS now. Capture that green baseline, do the move in Steps 3–4, then re-run (Step 5)
and confirm they still pass — the behavior is unchanged, only the file locations move.

- [ ] **Step 3: Create the `core` app skeleton**

`core/__init__.py`: empty file.

`core/apps.py`:
```python
from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
```

`core/views.py`:
```python
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    """Placeholder post-login page; the real adaptive dashboard is Phase 0d-2."""
    return render(request, "core/home.html")
```

`core/urls.py` — declares the `core:` namespace; `home` is intentionally **not** here (it
stays a top-level route in `config/urls.py` so the bare name `home` keeps resolving for
`LOGIN_REDIRECT_URL` and `{% url 'home' %}`). The `set_ui_language`/`set_theme` views are
added to this list in Task 8; for now it is empty:
```python
from django.urls import path  # noqa: F401  (used once Task 8 adds routes)

app_name = "core"

urlpatterns = [
    # set_ui_language / set_theme are added in Task 8.
]
```

`templates/core/home.html`:
```django
{% extends "base.html" %}
{% block content %}<p>You are logged in as {{ user }}.</p>{% endblock %}
```

- [ ] **Step 4: Rewire settings and URLs; delete the old files**

In `config/settings/base.py` add `"core"` to `INSTALLED_APPS` immediately before `"accounts"`:
```python
    "allauth.socialaccount.providers.openid_connect",
    "core",
    "accounts",
    "institution",
```

Rewrite `config/urls.py` to import `home` from `core.views` and include `core.urls`:
```python
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from core.views import home


def healthz(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz, name="healthz"),
    path("home/", home, name="home"),
    path("", include("core.urls")),
    path("", include("accounts.urls")),
    path("accounts/", include("allauth.account.urls")),
    path("accounts/", include("allauth.socialaccount.urls")),
    path("accounts/", include("allauth.socialaccount.providers.openid_connect.urls")),
]
```

Delete the now-empty files:
```bash
git rm config/views.py templates/home.html
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_ui_foundation.py -v`
Expected: PASS (all three). Also run the full suite to confirm no regression from the move:
`uv run python -m pytest -q` → all green.

- [ ] **Step 6: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add -A
git commit -m "feat(core): add core app; relocate home view+template into it"
```

---

### Task 2: `validate_css_color` + apply to `BrandColor.value`

**Files:**
- Create: `institution/validators.py`
- Modify: `institution/models.py`
- Create: `institution/migrations/0004_brandcolor_value_validator.py` (via makemigrations)
- Test: append to `tests/test_ui_foundation.py`

> The same color validation guards both the admin (model validator) and the runtime
> inline-`<style>` injection (Task 6 reuses `is_valid_css_color`). It lives in `institution`
> (not `core`) so the model can import it without a `core → institution → core` cycle.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_ui_foundation.py`:
```python
from django.core.exceptions import ValidationError

from institution.validators import is_valid_css_color, validate_css_color


def test_is_valid_css_color_accepts_hex_and_functions():
    assert is_valid_css_color("#147E78")
    assert is_valid_css_color("#abc")
    assert is_valid_css_color("  #147E78  ")  # surrounding whitespace stripped
    assert is_valid_css_color("rgb(20, 126, 120)")
    assert is_valid_css_color("rgba(20,126,120,0.5)")
    assert is_valid_css_color("hsl(176, 72%, 29%)")


def test_is_valid_css_color_rejects_injection_and_junk():
    for bad in ["red; }", "#fff;}body{x", "</style>", "url(x)", "", "147E78", "#12"]:
        assert not is_valid_css_color(bad)


def test_validate_css_color_raises_on_bad():
    with pytest.raises(ValidationError):
        validate_css_color("red; } body{display:none")
    # valid value does not raise
    validate_css_color("#147E78")


@pytest.mark.django_db
def test_brandcolor_full_clean_rejects_unsafe_value():
    from institution.models import BrandColor, Institution

    inst = Institution.load()
    bc = BrandColor(institution=inst, key="primary", value="</style><script>")
    with pytest.raises(ValidationError):
        bc.full_clean()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k "css_color or brandcolor_full_clean" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'institution.validators'`.

- [ ] **Step 3: Implement the validator** — `institution/validators.py`:
```python
"""Strict CSS-color validation shared by the BrandColor model (admin-time) and
the branding template tag (render-time). Anchored so nothing but a color string
can pass — closing the inline-<style> injection vector."""

import re

from django.core.exceptions import ValidationError

# Anchored: #rgb / #rrggbb, or rgb()/rgba()/hsl()/hsla() with numeric args.
_HEX = r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})"
_NUM = r"[0-9]{1,3}(?:\.[0-9]+)?%?"
_ALPHA = r"(?:0|1|0?\.[0-9]+)"
_RGB = rf"rgba?\(\s*{_NUM}\s*,\s*{_NUM}\s*,\s*{_NUM}\s*(?:,\s*{_ALPHA}\s*)?\)"
_HSL = rf"hsla?\(\s*{_NUM}\s*,\s*{_NUM}\s*,\s*{_NUM}\s*(?:,\s*{_ALPHA}\s*)?\)"
CSS_COLOR_RE = re.compile(rf"^(?:{_HEX}|{_RGB}|{_HSL})$")


def is_valid_css_color(value):
    """True iff `value` (after stripping surrounding whitespace) is a safe CSS color."""
    return bool(CSS_COLOR_RE.match((value or "").strip()))


def validate_css_color(value):
    """Django field validator raising ValidationError on a non-color value."""
    if not is_valid_css_color(value):
        raise ValidationError(
            "Enter a valid CSS color (hex like #147E78, or rgb()/hsl()).",
            code="invalid_css_color",
        )
```

- [ ] **Step 4: Apply the validator to the model** — in `institution/models.py`, import it and add to `value`:
```python
from institution.validators import validate_css_color
```
Change the `BrandColor.value` field to:
```python
    value = models.CharField(
        max_length=64, validators=[validate_css_color]
    )  # CSS color string; validated (anchored) before admin save + inline emit
```

- [ ] **Step 5: Make the migration**
```bash
uv run python manage.py makemigrations institution --name brandcolor_value_validator
```
Expected: creates `institution/migrations/0004_brandcolor_value_validator.py` altering
`BrandColor.value` (validators are not enforced at the DB level, but Django records the field
change). The `--name` pins the filename (otherwise it is auto-generated). Then:
```bash
uv run python manage.py makemigrations --check --dry-run
```
Expected: `No changes detected`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k "css_color or brandcolor_full_clean" -v`
Expected: PASS (all four).

- [ ] **Step 7: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add institution/ tests/test_ui_foundation.py
git commit -m "feat(institution): anchored CSS-color validator on BrandColor.value"
```

---

### Task 3: Cached read-only site-config accessor + invalidation signals

**Files:**
- Create: `core/services.py`
- Modify: `core/apps.py`
- Test: append to `tests/test_ui_foundation.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_ui_foundation.py`:
```python
@pytest.mark.django_db
def test_get_site_config_returns_defaults_bundle():
    from core.services import get_site_config

    cfg = get_site_config()
    assert cfg["name"]
    assert cfg["logo_url"] is None  # no logo uploaded
    assert cfg["primary"] == "#147E78"  # seeded default
    assert cfg["accent"] == "#C77B2A"
    assert cfg["enabled_languages"] == ["en", "pl"]
    assert cfg["default_language"] == "en"
    assert cfg["default_theme"] == "auto"


@pytest.mark.django_db
def test_get_site_config_is_cached_and_invalidated_on_save():
    from core.services import get_site_config
    from institution.models import BrandColor, Institution

    assert get_site_config()["primary"] == "#147E78"
    BrandColor.objects.filter(key="primary").update(value="#222222")  # bypasses signals
    assert get_site_config()["primary"] == "#147E78"  # still cached
    # A real save fires the post_save signal → cache cleared.
    inst = Institution.load()
    bc = BrandColor.objects.get(institution=inst, key="primary")
    bc.value = "#333333"
    bc.save()
    assert get_site_config()["primary"] == "#333333"


@pytest.mark.django_db
def test_get_site_config_skips_invalid_stored_color():
    # A value that somehow bypassed validation is treated as absent (None).
    from core.services import get_site_config
    from institution.models import BrandColor

    BrandColor.objects.filter(key="primary").update(value="garbage; }")
    from django.core.cache import cache

    cache.clear()
    assert get_site_config()["primary"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k site_config -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.services'`.

- [ ] **Step 3: Implement the accessor** — `core/services.py`:
```python
"""Cached, read-only access to the singleton institution's render-time config.

Read on every request (theming, nav, i18n seeding), so it is cached in Django's
cache framework with a short TTL and invalidated by signals (see core/apps.py).
It NEVER writes — `Institution.load()` does get_or_create (a write) and must not
run on the GET render path; this uses a plain read with a default fallback."""

from django.core.cache import cache

from institution.validators import is_valid_css_color

CACHE_KEY = "core:site_config"
CACHE_TTL = 300  # seconds; bounds cross-worker staleness under the default LocMemCache

PRIMARY_DEFAULT = "#147E78"
ACCENT_DEFAULT = "#C77B2A"

_DEFAULTS = {
    "name": "My Institution",
    "logo_url": None,
    "primary": PRIMARY_DEFAULT,
    "accent": ACCENT_DEFAULT,
    "enabled_languages": ["en", "pl"],
    "default_language": "en",
    "default_theme": "auto",
}


def _safe_color(value):
    """Return the stored color iff it passes validation, else None (absent)."""
    return value if (value and is_valid_css_color(value)) else None


def _build():
    from institution.models import Institution

    inst = (
        Institution.objects.filter(pk=1).prefetch_related("brand_colors").first()
    )
    if inst is None:
        return dict(_DEFAULTS)
    colors = {c.key: c.value for c in inst.brand_colors.all()}
    return {
        "name": inst.name or _DEFAULTS["name"],
        # Guard: dereferencing .url on an empty ImageField raises ValueError.
        "logo_url": inst.logo.url if inst.logo else None,
        "primary": _safe_color(colors.get("primary")),
        "accent": _safe_color(colors.get("accent")),
        "enabled_languages": inst.enabled_languages or _DEFAULTS["enabled_languages"],
        "default_language": inst.default_language or _DEFAULTS["default_language"],
        "default_theme": inst.default_theme or _DEFAULTS["default_theme"],
    }


def get_site_config():
    """The cached site-config bundle. Read-only; safe on the GET render path."""
    cfg = cache.get(CACHE_KEY)
    if cfg is None:
        cfg = _build()
        cache.set(CACHE_KEY, cfg, CACHE_TTL)
    return cfg


def invalidate_site_config(*args, **kwargs):
    """Signal receiver: drop the cached bundle so the next read rebuilds it."""
    cache.delete(CACHE_KEY)
```
> Note: the defaults bundle reports `primary`/`accent` as the seeded hex (not `None`), but
> `_build()` returns `None` for an absent/invalid stored color. With the seed migration
> present, a fresh DB has the hexes; `test_get_site_config_returns_defaults_bundle` asserts
> the seeded values. The branding tag (Task 6) treats both "equals default" and `None` as
> "emit nothing".
> **The pk=1 row always exists in tests:** `institution/migrations/0002_seed_branding.py` does
> `Institution.load()` (a `get_or_create(pk=1)`) plus the two seeded `BrandColor`s, so every
> migrated test DB has the singleton row. Therefore `_build()` (not the `_DEFAULTS` fallback)
> is the live path, and `get_site_config()["default_theme"]` resolves to the stored `"auto"`
> — which the theme-resolution chain in Task 4 relies on.

- [ ] **Step 4: Connect invalidation signals** — rewrite `core/apps.py`:
```python
from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from core.services import invalidate_site_config
        from institution.models import BrandColor, Institution

        for model in (Institution, BrandColor):
            post_save.connect(invalidate_site_config, sender=model)
            post_delete.connect(invalidate_site_config, sender=model)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k site_config -v`
Expected: PASS (all three).

- [ ] **Step 6: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add core/ tests/test_ui_foundation.py
git commit -m "feat(core): cached read-only site-config accessor + invalidation signals"
```

---

### Task 4: Context processors + theme resolution

**Files:**
- Create: `core/context_processors.py`
- Modify: `config/settings/base.py` (TEMPLATES context_processors)
- Test: append to `tests/test_ui_foundation.py`

> `institution_branding` exposes name/logo/palette; `ui_prefs` exposes the resolved theme
> preference (raw, incl. `auto`), the `auto`→`light` `data-theme` projection, and the
> active/enabled languages for the shell switch.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_ui_foundation.py`:
```python
def _ctx(processor, request):
    return processor(request)


@pytest.mark.django_db
def test_ui_prefs_anonymous_default_theme_auto(rf):
    from django.contrib.auth.models import AnonymousUser

    from core.context_processors import ui_prefs

    request = rf.get("/")
    request.user = AnonymousUser()
    request.COOKIES = {}
    ctx = ui_prefs(request)
    assert ctx["theme_pref"] == "auto"
    assert ctx["data_theme"] == "light"  # auto -> light server projection


@pytest.mark.django_db
def test_ui_prefs_authenticated_uses_user_theme(rf):
    from core.context_processors import ui_prefs

    user = make_verified_user(username="bob", email="bob@school.edu")
    user.theme = "dark"
    user.save()
    request = rf.get("/")
    request.user = user
    request.COOKIES = {}
    ctx = ui_prefs(request)
    assert ctx["theme_pref"] == "dark"
    assert ctx["data_theme"] == "dark"


@pytest.mark.django_db
def test_ui_prefs_anonymous_cookie_wins_over_institution_default(rf):
    from django.contrib.auth.models import AnonymousUser

    from core.context_processors import ui_prefs

    request = rf.get("/")
    request.user = AnonymousUser()
    request.COOKIES = {"libli_theme": "dark"}
    ctx = ui_prefs(request)
    assert ctx["theme_pref"] == "dark"
    assert ctx["data_theme"] == "dark"


@pytest.mark.django_db
def test_institution_branding_exposes_bundle(rf):
    from core.context_processors import institution_branding

    ctx = institution_branding(rf.get("/"))
    assert ctx["site"]["name"]
    assert ctx["site"]["primary"] == "#147E78"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k "ui_prefs or institution_branding" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.context_processors'`.

- [ ] **Step 3: Implement** — `core/context_processors.py`:
```python
"""Template context processors for the app shell: branding bundle + UI prefs."""

from django.utils import translation

from core.services import get_site_config

THEME_VALUES = {"light", "dark", "auto"}
COOKIE_THEME = "libli_theme"


def institution_branding(request):
    """Expose the cached site bundle (name/logo/palette) to every template."""
    return {"site": get_site_config()}


def _resolve_theme_pref(request):
    """Winning-precedence theme preference (raw, may be 'auto').

    User.theme (authed) -> libli_theme cookie -> Institution.default_theme.
    User.theme is never empty, so for an authed user the later rungs are unreachable.
    """
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.theme in THEME_VALUES:
        return user.theme
    cookie = request.COOKIES.get(COOKIE_THEME)
    if cookie in THEME_VALUES:
        return cookie
    return get_site_config()["default_theme"]


def ui_prefs(request):
    """Resolved theme attributes + language switch data for the shell."""
    pref = _resolve_theme_pref(request)
    data_theme = "light" if pref == "auto" else pref  # server can't know OS -> light
    cfg = get_site_config()
    active = translation.get_language() or cfg["default_language"]
    # Offer only enabled languages, labelled from settings.LANGUAGES.
    from django.conf import settings

    labels = dict(settings.LANGUAGES)
    languages = [
        {"code": code, "label": labels.get(code, code), "active": code == active}
        for code in cfg["enabled_languages"]
    ]
    return {
        "theme_pref": pref,
        "data_theme": data_theme,
        "active_language": active,
        "languages": languages,
    }
```

- [ ] **Step 4: Register the processors** — in `config/settings/base.py`, extend the
existing `context_processors` list (keep the three existing entries):
```python
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.institution_branding",
                "core.context_processors.ui_prefs",
            ],
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k "ui_prefs or institution_branding" -v`
Expected: PASS (all four).

- [ ] **Step 6: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add core/context_processors.py config/settings/base.py tests/test_ui_foundation.py
git commit -m "feat(core): institution_branding + ui_prefs context processors"
```

---

### Task 5: Static assets — CSS system + self-hosted Inter + test-storage override

**Files:**
- Create: `core/static/core/css/tokens.css`, `reset.css`, `app.css`
- Create: `core/static/core/fonts/inter/*.woff2` (vendored)
- Modify: `config/settings/test.py`
- Test: append to `tests/test_ui_foundation.py`

> CSS is not unit-tested for pixels. The test here asserts the files are collectible/servable
> and that `tokens.css` contains the load-bearing `color-mix()` derivation. `app.css`/`reset.css`
> are seeded conceptually from `../bonnot/mockups/{base,components}.css` and
> `../bonnot/frontend/src/styles/*` — adapt to the tokens below; full concrete content is given.

- [ ] **Step 1: Vendor Inter (woff2)**

Download Inter (OFL) variable or static woff2 and place four static weights at:
```
core/static/core/fonts/inter/Inter-Regular.woff2   (400)
core/static/core/fonts/inter/Inter-Medium.woff2    (500)
core/static/core/fonts/inter/Inter-SemiBold.woff2  (600)
core/static/core/fonts/inter/Inter-Bold.woff2      (700)
```
Source: https://github.com/rsms/inter/releases (the `Inter-*.woff2` web fonts) or the
`@fontsource/inter` package. These files MUST exist before `collectstatic`
(`CompressedManifestStaticFilesStorage` post-processes `url()` refs and errors on a missing
target).

- [ ] **Step 2: Write `tokens.css`** — `core/static/core/css/tokens.css`:
```css
/* libli design tokens. @font-face first; then the palette derived via color-mix()
   from two raw institution-overridable inputs. See docs/design-language.md. */
@font-face {
  font-family: "Inter"; font-style: normal; font-weight: 400; font-display: swap;
  src: url("../fonts/inter/Inter-Regular.woff2") format("woff2");
}
@font-face {
  font-family: "Inter"; font-style: normal; font-weight: 500; font-display: swap;
  src: url("../fonts/inter/Inter-Medium.woff2") format("woff2");
}
@font-face {
  font-family: "Inter"; font-style: normal; font-weight: 600; font-display: swap;
  src: url("../fonts/inter/Inter-SemiBold.woff2") format("woff2");
}
@font-face {
  font-family: "Inter"; font-style: normal; font-weight: 700; font-display: swap;
  src: url("../fonts/inter/Inter-Bold.woff2") format("woff2");
}

:root {
  /* raw institution-overridable inputs (defaults = warm teal / amber) */
  --brand-primary: #147E78;
  --brand-accent:  #C77B2A;

  /* derived brand families (light) */
  --primary:        var(--brand-primary);
  --primary-hover:  color-mix(in srgb, var(--brand-primary) 88%, black);
  --primary-active: color-mix(in srgb, var(--brand-primary) 78%, black);
  --primary-subtle: color-mix(in srgb, var(--brand-primary) 16%, var(--surface-raised));
  --accent:         var(--brand-accent);
  --accent-hover:   color-mix(in srgb, var(--brand-accent) 88%, black);
  --accent-subtle:  color-mix(in srgb, var(--brand-accent) 18%, var(--surface-raised));

  /* surfaces / text / borders — flat literals (design-language.md, light) */
  --surface-base: #F4F1EA; --surface-raised: #FFFFFF; --surface-sunken: #FAF8F3;
  --surface-overlay: rgba(30,28,24,0.45);
  --text-primary: #1E1C18; --text-secondary: #5A544A; --text-tertiary: #8A8477;
  --text-inverse: #FBF9F4;
  --border-subtle: #EDE8DE; --border-default: #E7E1D6; --border-strong: #D6CFC1;

  /* semantic */
  --success: #5A7D3C; --success-subtle: #E3ECD7;
  --warning: #B8811F; --warning-subtle: #F4E8CD;
  --danger:  #A8392E; --danger-subtle:  #F2D9D5;

  /* radius / shadow / type / spacing */
  --radius-sm: 7px; --radius-md: 10px; --radius-lg: 12px; --radius-xl: 18px;
  --radius-full: 9999px;
  --shadow-xs: 0 1px 2px rgba(30,28,24,.06);
  --shadow-sm: 0 2px 6px rgba(30,28,24,.08);
  --shadow-md: 0 6px 16px rgba(30,28,24,.10);
  --shadow-lg: 0 16px 40px rgba(30,28,24,.14);
  --font-ui: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --heading-letter-spacing: -0.015em;
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
  --space-5: 20px; --space-6: 24px; --space-8: 32px; --space-10: 40px;
}

[data-theme="dark"] {
  /* brand lift (dark) */
  --primary:        color-mix(in srgb, var(--brand-primary) 68%, white);
  --primary-hover:  color-mix(in srgb, var(--brand-primary) 78%, white);
  --primary-active: color-mix(in srgb, var(--brand-primary) 88%, white);
  --primary-subtle: color-mix(in srgb, var(--brand-primary) 24%, var(--surface-raised));
  --accent:         color-mix(in srgb, var(--brand-accent) 70%, white);
  --accent-hover:   color-mix(in srgb, var(--brand-accent) 80%, white);
  --accent-subtle:  color-mix(in srgb, var(--brand-accent) 26%, var(--surface-raised));

  /* surfaces / text / borders — flat literals (design-language.md, dark) */
  --surface-base: #1A1816; --surface-raised: #2C2925; --surface-sunken: #15130F;
  --surface-overlay: rgba(0,0,0,0.55);
  --text-primary: #F2EFE9; --text-secondary: #BDB6A8; --text-tertiary: #8A8477;
  --text-inverse: #1E1C18;
  --border-subtle: #2A2620; --border-default: #322E29; --border-strong: #4A4036;
  --success: #9FBF7B; --success-subtle: #2A3620;
  --warning: #E8B761; --warning-subtle: #3A2F18;
  --danger:  #E57373; --danger-subtle:  #3A1E1A;
  --shadow-xs: 0 1px 2px rgba(0,0,0,.4);
  --shadow-sm: 0 2px 6px rgba(0,0,0,.45);
  --shadow-md: 0 6px 16px rgba(0,0,0,.5);
  --shadow-lg: 0 16px 40px rgba(0,0,0,.55);
}
```
> After writing, **verify the default-brand derived shades** are close to the design-language
> literals (`--primary-hover`≈#0F6A65, `--primary-active`≈#0B5651, dark `--primary`≈#4FB3AC,
> dark `--accent`≈#E5A159) by eyeballing in a browser. If a `*-subtle` can't be matched by the
> mix, replace that one line with the literal (#DCEDEB light / #1B3A38 dark) and note it.

- [ ] **Step 3: Write `reset.css`** — `core/static/core/css/reset.css`:
```css
/* Base reset + a11y primitives (adapted from bonnot). */
*, *::before, *::after { box-sizing: border-box; }
* { margin: 0; }
html { -webkit-text-size-adjust: 100%; }
body {
  min-height: 100vh; font-family: var(--font-ui); line-height: 1.5;
  background: var(--surface-base); color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
}
h1, h2, h3, h4 { line-height: 1.15; letter-spacing: var(--heading-letter-spacing); }
img, picture, svg { display: block; max-width: 100%; }
button, input, select, textarea { font: inherit; color: inherit; }
a { color: var(--accent); text-underline-offset: 2px; }
:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; border-radius: 3px; }
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .001ms !important; animation-iteration-count: 1 !important;
    transition-duration: .001ms !important; scroll-behavior: auto !important;
  }
}
```

- [ ] **Step 4: Write `app.css`** — `core/static/core/css/app.css`:
```css
/* libli app shell + primitive components. */
.app-header {
  display: flex; align-items: center; gap: var(--space-4);
  padding: var(--space-3) var(--space-5);
  background: var(--surface-raised); border-bottom: 1px solid var(--border-default);
}
.brand { display: inline-flex; align-items: baseline; gap: 2px; font-weight: 700;
  font-size: 1.25rem; color: var(--text-primary); text-decoration: none; }
.brand__dot { color: var(--accent); }
.brand__logo { height: 28px; width: auto; }
.app-header__spacer { flex: 1; }
.app-header__cluster { display: flex; align-items: center; gap: var(--space-3); }
.app-main { max-width: 960px; margin: 0 auto; padding: var(--space-8) var(--space-5); }

.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: var(--space-2);
  padding: var(--space-2) var(--space-4); border-radius: var(--radius-sm);
  border: 1px solid transparent; background: var(--primary); color: var(--text-inverse);
  font-weight: 500; cursor: pointer; text-decoration: none;
}
.btn:hover { background: var(--primary-hover); }
.btn:active { background: var(--primary-active); }
.btn--ghost { background: transparent; color: var(--text-primary);
  border-color: var(--border-strong); }
.btn--ghost:hover { background: var(--surface-sunken); }
.btn--icon { padding: var(--space-2); border-radius: var(--radius-full);
  background: transparent; color: var(--text-secondary); border-color: var(--border-default); }

form p, .form-row { margin-bottom: var(--space-4); }
label { display: block; font-weight: 500; margin-bottom: var(--space-1);
  color: var(--text-secondary); }
input[type=text], input[type=email], input[type=password], input[type=url], select, textarea {
  width: 100%; padding: var(--space-2) var(--space-3);
  background: var(--surface-sunken); color: var(--text-primary);
  border: 1px solid var(--border-default); border-radius: var(--radius-sm);
}
.errorlist { list-style: none; padding: 0; margin: var(--space-1) 0 0;
  color: var(--danger); font-size: .875rem; }
.helptext { color: var(--text-tertiary); font-size: .875rem; }

.card {
  max-width: 28rem; margin: var(--space-8) auto; padding: var(--space-6);
  background: var(--surface-raised); border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg); box-shadow: var(--shadow-sm);
}

.alert { padding: var(--space-3) var(--space-4); border-radius: var(--radius-sm);
  border: 1px solid var(--border-default); margin-bottom: var(--space-3); }
.alert--success { background: var(--success-subtle); border-color: var(--success); }
.alert--warning { background: var(--warning-subtle); border-color: var(--warning); }
.alert--error, .alert--danger { background: var(--danger-subtle); border-color: var(--danger); }
.alert--info { background: var(--primary-subtle); border-color: var(--primary); }

.avatar { display: inline-flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; border-radius: var(--radius-full);
  background: var(--primary-subtle); color: var(--primary-active); font-weight: 600;
  font-size: .8rem; }

.menu { position: relative; }
.menu__panel {
  position: absolute; right: 0; top: calc(100% + 6px); min-width: 11rem;
  background: var(--surface-raised); border: 1px solid var(--border-default);
  border-radius: var(--radius-md); box-shadow: var(--shadow-md); padding: var(--space-2);
}
.menu__panel[hidden] { display: none; }
.menu__item { display: block; width: 100%; text-align: left; padding: var(--space-2) var(--space-3);
  background: transparent; border: 0; border-radius: var(--radius-sm); color: var(--text-primary);
  text-decoration: none; cursor: pointer; }
.menu__item:hover { background: var(--surface-sunken); }

.lang-switch { display: inline-flex; gap: var(--space-1); }
.lang-switch button { background: transparent; border: 0; padding: 2px 6px;
  border-radius: var(--radius-sm); color: var(--text-secondary); cursor: pointer; }
.lang-switch button[aria-current="true"] { color: var(--primary); font-weight: 600; }

@media (max-width: 640px) {
  .app-header { flex-wrap: wrap; gap: var(--space-2); }
  .app-main { padding: var(--space-5) var(--space-4); }
}
```

- [ ] **Step 5: Override staticfiles storage for tests** — append to `config/settings/test.py`:
```python
# Tests render {% static %} without running collectstatic, so avoid the manifest
# storage (which needs staticfiles.json) — use the plain finder-backed storage.
STORAGES = {
    **STORAGES,  # noqa: F405  (imported via `from base import *`)
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

# Pin the cache backend so the site-config cache-timing tests (Task 3) are stable
# regardless of any future production CACHES override. LocMemCache is per-process;
# the autouse `_clear_site_cache` fixture isolates each test.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}
```

- [ ] **Step 6: Write the asset-presence test** — append to `tests/test_ui_foundation.py`:
```python
def test_tokens_css_has_colormix_derivation():
    from pathlib import Path

    from django.conf import settings

    tokens = (
        Path(settings.BASE_DIR) / "core/static/core/css/tokens.css"
    ).read_text(encoding="utf-8")
    assert "--brand-primary: #147E78;" in tokens
    assert "color-mix(in srgb, var(--brand-primary)" in tokens
    assert '[data-theme="dark"]' in tokens
    assert "--surface-raised:" in tokens  # named literal the *-subtle mixes need


def test_static_css_resolves_via_finders():
    from django.contrib.staticfiles import finders

    for name in ["core/css/tokens.css", "core/css/reset.css", "core/css/app.css",
                 "core/js/ui.js"]:
        assert finders.find(name), f"missing static asset: {name}"
```
> The `core/js/ui.js` assertion is satisfied within THIS task: Step 7 creates the stub
> `core/static/core/js/ui.js` (so the suite stays green at this commit); Task 9 fleshes it out.

- [ ] **Step 7: Create the ui.js stub** — `core/static/core/js/ui.js`:
```javascript
"use strict";
// Fleshed out in Task 9 (theme toggle, account menu, language switch).
```

- [ ] **Step 8: Run the tests + collectstatic smoke**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k "tokens_css or static_css" -v` → PASS.
Run: `uv run python -m pytest -q` → all green.
Run (verifies fonts present + manifest post-processing): `uv run python manage.py collectstatic --noinput` → succeeds (reports N static files copied). Then clean up: `rm -rf staticfiles`.

- [ ] **Step 9: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add core/static config/settings/test.py tests/test_ui_foundation.py
git commit -m "feat(core): bespoke CSS tokens/reset/app + self-hosted Inter; test storage"
```

---

### Task 6: `brand_vars` template tag (conditional inline `<style>`)

**Files:**
- Create: `core/templatetags/__init__.py`, `core/templatetags/branding.py`
- Test: append to `tests/test_ui_foundation.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_ui_foundation.py`:
```python
@pytest.mark.django_db
def test_brand_vars_emits_nothing_for_default_palette():
    from django.template import Context, Template

    from django.core.cache import cache

    cache.clear()
    out = Template("{% load branding %}{% brand_vars %}").render(Context({}))
    assert out.strip() == ""  # seeded colors equal defaults -> no override


@pytest.mark.django_db
def test_brand_vars_emits_style_for_overridden_palette():
    from django.template import Context, Template

    from django.core.cache import cache
    from institution.models import BrandColor

    bc = BrandColor.objects.get(key="primary")
    bc.value = "#3355FF"
    bc.save()  # fires invalidation
    cache.clear()
    out = Template("{% load branding %}{% brand_vars %}").render(Context({}))
    assert "<style>" in out and "--brand-primary: #3355FF" in out
    assert "--brand-accent" not in out  # accent still default -> not emitted


@pytest.mark.django_db
def test_brand_vars_skips_invalid_color():
    from django.template import Context, Template

    from django.core.cache import cache
    from institution.models import BrandColor

    BrandColor.objects.filter(key="primary").update(value="x; }</style>")
    cache.clear()
    out = Template("{% load branding %}{% brand_vars %}").render(Context({}))
    assert "</style>" not in out
    assert "--brand-primary" not in out  # invalid -> treated as absent
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k brand_vars -v`
Expected: FAIL — `'branding' is not a registered tag library`.

- [ ] **Step 3: Implement** — `core/templatetags/__init__.py` empty; `core/templatetags/branding.py`:
```python
"""{% brand_vars %} — emits a tiny inline <style> overriding the two raw brand
vars when (and only when) the institution's stored colors differ from the
defaults and pass color validation. Placed in <head> AFTER tokens.css so the
override wins. Values are re-validated here as defense-in-depth."""

from django import template
from django.utils.safestring import mark_safe

from core.services import ACCENT_DEFAULT, PRIMARY_DEFAULT, get_site_config
from institution.validators import is_valid_css_color

register = template.Library()


def _override(value, default):
    """The value iff it is valid AND differs (case-insensitively) from default."""
    if not value or not is_valid_css_color(value):
        return None
    if value.strip().lower() == default.lower():
        return None
    return value.strip()


@register.simple_tag
def brand_vars():
    cfg = get_site_config()
    decls = []
    primary = _override(cfg.get("primary"), PRIMARY_DEFAULT)
    accent = _override(cfg.get("accent"), ACCENT_DEFAULT)
    if primary:
        decls.append(f"--brand-primary: {primary};")
    if accent:
        decls.append(f"--brand-accent: {accent};")
    if not decls:
        return ""
    return mark_safe(  # noqa: S308 — values are validated against an anchored color regex
        "<style>:root{" + "".join(decls) + "}</style>"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k brand_vars -v`
Expected: PASS (all three).

- [ ] **Step 5: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add core/templatetags tests/test_ui_foundation.py
git commit -m "feat(core): brand_vars tag — validated conditional inline brand override"
```

---

### Task 7: i18n settings + language seeder middleware + login/logout receivers

> **CORRECTION applied during execution (2026-06-14):** the code blocks below originally used
> `translation.LANGUAGE_SESSION_KEY`, which **does not exist in Django 5.2** (session-based
> language selection was removed in Django 4.0). As implemented: `core/middleware.py` defines its
> own `LANGUAGE_SESSION_KEY = "_language"` constant and a **`SessionLocaleMiddleware(LocaleMiddleware)`**
> subclass (overriding `process_request` to prefer that session key, else `super()`), used in
> MIDDLEWARE in place of `django.middleware.locale.LocaleMiddleware`. `core/signals.py` and
> `core/views.py` (Task 8) import the constant from `core.middleware`. The seeder/receivers/tests
> are otherwise as written. See the shipped `core/middleware.py` for the authoritative code.

**Files:**
- Modify: `config/settings/base.py`
- Create: `core/middleware.py`, `core/signals.py`
- Modify: `core/apps.py` (import signals)
- Test: append to `tests/test_ui_foundation.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_ui_foundation.py`:
```python
from django.utils import translation


@pytest.mark.django_db
def test_login_seeds_session_language_from_user(client):
    user = make_verified_user(username="pat", email="pat@school.edu")
    user.language = "pl"
    user.save()
    client.force_login(user)
    # The user_logged_in receiver fires on force_login.
    assert client.session.get("_language") == "pl"


@pytest.mark.django_db
def test_login_with_disabled_language_falls_back_without_mutating(client):
    from institution.models import Institution

    inst = Institution.load()
    inst.enabled_languages = ["en"]  # pl disabled
    inst.save()
    user = make_verified_user(username="ula", email="ula@school.edu")
    user.language = "pl"
    user.save()
    client.force_login(user)
    assert client.session.get("_language") == "en"  # fell back to default
    user.refresh_from_db()
    assert user.language == "pl"  # stored choice NOT overwritten


@pytest.mark.django_db
def test_logout_clears_theme_cookie(client):
    user = make_verified_user(username="rob", email="rob@school.edu")
    client.force_login(user)
    client.cookies["libli_theme"] = "dark"
    client.post(reverse("account_logout"))
    # The cookie is expired (Max-Age=0) by the user_logged_out receiver.
    morsel = client.cookies.get("libli_theme")
    assert morsel is None or morsel.value == "" or morsel["max-age"] in (0, "0")


@pytest.mark.django_db
def test_seeder_keeps_anonymous_within_enabled_languages(client):
    from institution.models import Institution

    inst = Institution.load()
    inst.enabled_languages = ["en"]
    inst.default_language = "en"
    inst.save()
    # Anonymous request advertising pl: seeder must NOT let pl activate.
    resp = client.get("/accounts/login/", HTTP_ACCEPT_LANGUAGE="pl")
    assert resp.status_code == 200
    assert translation.get_language() == "en"
```
> **Why `force_login` exercises the login receiver:** in Django 5.2, `Client.force_login`
> calls `login(request, user)` with a real `HttpRequest` carrying the client's session, so
> `user_logged_in` fires with `request` set — `seed_language_on_login` runs and its session
> write persists to `client.session`. (If a future Django changed this, the test would switch
> to a real login POST.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k "seeds_session or disabled_language or clears_theme or seeder_keeps" -v`
Expected: FAIL — receivers/middleware not present (`_language` not set; cookie not cleared).

- [ ] **Step 3: i18n settings** — in `config/settings/base.py`:

(a) At the top, ensure the lazy gettext import (place near the other imports):
```python
from django.utils.translation import gettext_lazy as _
```

(b) Replace the i18n block (currently `LANGUAGE_CODE`/`USE_I18N` etc.) with:
```python
LANGUAGE_CODE = "en"
LANGUAGES = [("en", _("English")), ("pl", _("Polski"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
```

(c) Insert the two middleware after `SessionMiddleware` and before `CommonMiddleware`
(seeder first, then Locale):
```python
    "django.contrib.sessions.middleware.SessionMiddleware",
    "core.middleware.LanguageSeederMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
```

- [ ] **Step 4: Implement the seeder** — `core/middleware.py`:
```python
"""Keeps the *anonymous, no-session-language* request within the institution's
enabled languages, defaulting to its default_language. Runs before LocaleMiddleware
so the session key it writes is the one LocaleMiddleware then activates."""

from django.utils import translation

from core.services import get_site_config

SESSION_KEY = translation.LANGUAGE_SESSION_KEY  # Django's "_language"


class LanguageSeederMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.session.get(SESSION_KEY):
            cfg = get_site_config()
            enabled = cfg["enabled_languages"]
            candidate = translation.get_language_from_request(request)
            if candidate not in enabled:
                request.session[SESSION_KEY] = cfg["default_language"]
        return self.get_response(request)
```
> `LANGUAGE_SESSION_KEY` is `"_language"` in Django 5.2; using the constant avoids drift.
> **Ordering constraint:** the seeder runs **before** `AuthenticationMiddleware` (which sits
> after `CsrfViewMiddleware`), so `request.user` is not yet available inside it. The seeder
> must rely **only** on the session and `Accept-Language` (via `get_language_from_request`) —
> never `request.user`. (The `user_logged_in` receiver, not the seeder, is what handles the
> authenticated case.)

- [ ] **Step 5: Implement the receivers** — `core/signals.py`:
```python
"""Login/logout side effects for UI prefs: seed the session language from the
user (clamped to enabled languages) at login; clear the theme cookie at logout."""

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.utils import translation

from core.services import get_site_config

SESSION_KEY = translation.LANGUAGE_SESSION_KEY


@receiver(user_logged_in)
def seed_language_on_login(sender, request, user, **kwargs):
    cfg = get_site_config()
    lang = user.language if user.language in cfg["enabled_languages"] else (
        cfg["default_language"]
    )
    if request is not None and hasattr(request, "session"):
        request.session[SESSION_KEY] = lang


@receiver(user_logged_out)
def clear_theme_cookie_on_logout(sender, request, user, **kwargs):
    # The actual deletion happens on the response; stash a flag the view layer
    # can't easily reach, so instead delete via a response cookie in middleware?
    # Simpler: mark the request so a tiny response step clears it. We use Django's
    # request._libli_clear_theme flag, honored in the logout flow below.
    if request is not None:
        request._libli_clear_theme = True
```
> **Cookie deletion needs a response.** Signals don't have the response object. Implement the
> deletion as part of the seeder middleware's response pass (it already wraps every response):
> after `response = self.get_response(request)`, add:
> ```python
>         if getattr(request, "_libli_clear_theme", False):
>             response.delete_cookie(COOKIE_THEME, path="/", samesite="Lax")
> ```
> Add the import `from core.context_processors import COOKIE_THEME` to `core/middleware.py`.
> Update `core/middleware.py` accordingly (full revised file):
```python
from django.utils import translation

from core.context_processors import COOKIE_THEME
from core.services import get_site_config

SESSION_KEY = translation.LANGUAGE_SESSION_KEY


class LanguageSeederMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.session.get(SESSION_KEY):
            cfg = get_site_config()
            candidate = translation.get_language_from_request(request)
            if candidate not in cfg["enabled_languages"]:
                request.session[SESSION_KEY] = cfg["default_language"]
        response = self.get_response(request)
        if getattr(request, "_libli_clear_theme", False):
            response.delete_cookie(COOKIE_THEME, path="/", samesite="Lax")
        return response
```

- [ ] **Step 6: Register the signals** — in `core/apps.py` `ready()`, add an import so the
receivers connect (append at the end of `ready`):
```python
        from core import signals  # noqa: F401  (registers login/logout receivers)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k "seeds_session or disabled_language or clears_theme or seeder_keeps" -v`
Expected: PASS (all four). Run the full file too: `uv run python -m pytest tests/test_ui_foundation.py -q`.

- [ ] **Step 8: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add config/settings/base.py core/ tests/test_ui_foundation.py
git commit -m "feat(core): i18n wiring + language seeder + login/logout receivers"
```

---

### Task 8: `set_ui_language` + `set_theme` views

**Files:**
- Modify: `core/views.py`, `core/urls.py`
- Test: append to `tests/test_ui_foundation.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_ui_foundation.py`:
```python
@pytest.mark.django_db
def test_set_ui_language_anonymous_writes_session_and_redirects(client):
    resp = client.post(
        reverse("core:set_ui_language"), {"language": "pl", "next": "/accounts/login/"}
    )
    assert resp.status_code == 302
    assert resp["Location"] == "/accounts/login/"
    assert client.session.get("_language") == "pl"


@pytest.mark.django_db
def test_set_ui_language_rejects_disabled_and_unsafe_next(client):
    from institution.models import Institution

    inst = Institution.load()
    inst.enabled_languages = ["en"]
    inst.save()
    resp = client.post(
        reverse("core:set_ui_language"),
        {"language": "pl", "next": "https://evil.test/x"},
    )
    # pl rejected (not enabled) -> session unchanged; unsafe next -> falls back to home.
    assert client.session.get("_language") in (None, "en")
    assert resp["Location"] == reverse("home")


@pytest.mark.django_db
def test_set_ui_language_authenticated_persists_user_language(client):
    user = make_verified_user(username="liz", email="liz@school.edu")
    client.force_login(user)
    client.post(reverse("core:set_ui_language"), {"language": "pl", "next": "/home/"})
    user.refresh_from_db()
    assert user.language == "pl"


@pytest.mark.django_db
def test_set_theme_requires_auth(client):
    resp = client.post(reverse("core:set_theme"), {"theme": "dark"})
    assert resp.status_code in (302, 403)  # login_required -> redirect (or 403)


@pytest.mark.django_db
def test_set_theme_persists_and_returns_204(client):
    user = make_verified_user(username="moe", email="moe@school.edu")
    client.force_login(user)
    resp = client.post(reverse("core:set_theme"), {"theme": "dark"})
    assert resp.status_code == 204
    user.refresh_from_db()
    assert user.theme == "dark"


@pytest.mark.django_db
def test_set_theme_rejects_invalid(client):
    user = make_verified_user(username="ned", email="ned@school.edu")
    client.force_login(user)
    resp = client.post(reverse("core:set_theme"), {"theme": "rainbow"})
    assert resp.status_code == 400
    user.refresh_from_db()
    assert user.theme == "auto"  # unchanged
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k "set_ui_language or set_theme" -v`
Expected: FAIL — `NoReverseMatch` for `core:set_ui_language` / `core:set_theme`.

- [ ] **Step 3: Implement the views** — append to `core/views.py`:
```python
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import translation
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.context_processors import THEME_VALUES
from core.services import get_site_config

SESSION_KEY = translation.LANGUAGE_SESSION_KEY


@require_POST
def set_ui_language(request):
    """Switch the UI language (session + User.language if authed); safe-redirect back."""
    lang = request.POST.get("language", "")
    if lang in get_site_config()["enabled_languages"]:
        request.session[SESSION_KEY] = lang
        if request.user.is_authenticated:
            request.user.language = lang
            request.user.save(update_fields=["language"])
    nxt = request.POST.get("next") or request.headers.get("referer", "")
    if not url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        nxt = reverse("home")
    return redirect(nxt)


@login_required
@require_POST
def set_theme(request):
    """Persist User.theme (fetch endpoint: 204 on success, 400 on bad value)."""
    theme = request.POST.get("theme", "")
    if theme not in THEME_VALUES:
        return HttpResponseBadRequest("invalid theme")
    request.user.theme = theme
    request.user.save(update_fields=["theme"])
    return HttpResponse(status=204)
```
> **Decorator order is load-bearing:** `@login_required` MUST be the **outer** decorator
> (listed first, above `@require_POST`) so an unauthenticated request gets the auth redirect
> **before** method checking — reversing them would return a 405 to anonymous GETs instead.

- [ ] **Step 4: Wire the URLs** — set `core/urls.py` to:
```python
from django.urls import path

from core import views

app_name = "core"

urlpatterns = [
    path("ui/set-language/", views.set_ui_language, name="set_ui_language"),
    path("ui/set-theme/", views.set_theme, name="set_theme"),
]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k "set_ui_language or set_theme" -v`
Expected: PASS (all six).

- [ ] **Step 6: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add core/views.py core/urls.py tests/test_ui_foundation.py
git commit -m "feat(core): set_ui_language + set_theme write endpoints"
```

---

### Task 9: `base.html` shell + `ui.js` + allauth/accounts restyle

**Files:**
- Modify: `templates/base.html`, `core/static/core/js/ui.js`, `templates/allauth/layouts/base.html`
- Modify: `templates/accounts/accept_invite.html`, `invite_invalid.html`, `sso_not_provisioned.html` (card wrapper — optional markup)
- Test: append to `tests/test_ui_foundation.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_ui_foundation.py`:
```python
import re


@pytest.mark.django_db
def test_login_page_renders_shell_anonymous_no_account_menu(client):
    html = client.get("/accounts/login/").content.decode()
    assert 'class="brand"' in html
    assert "account-menu" not in html  # anonymous variant
    # pre-paint script before any stylesheet link
    head = html[: html.index("</head>")]
    # "prefers-color-scheme" appears only inside the pre-paint script — use it to
    # assert the script precedes the first stylesheet link (the real no-flash check).
    script_idx = head.index("prefers-color-scheme")
    link_idx = head.index('rel="stylesheet"')
    assert script_idx < link_idx
    # inline brand <style> (if any) comes after tokens.css; tokens.css link present
    assert "core/css/tokens.css" in head


@pytest.mark.django_db
def test_html_has_theme_and_lang_attributes(client):
    html = client.get("/accounts/login/").content.decode()
    assert re.search(r"<html[^>]*data-theme=\"light\"", html)
    assert re.search(r"<html[^>]*data-theme-pref=\"auto\"", html)
    assert re.search(r"<html[^>]*lang=\"en\"", html)


@pytest.mark.django_db
def test_home_renders_shell_authenticated_with_account_menu(client):
    user = make_verified_user(username="ann", email="ann@school.edu")
    client.force_login(user)
    html = client.get("/home/").content.decode()
    assert "account-menu" in html
    assert "data-theme" in html


@pytest.mark.django_db
def test_dark_user_theme_attribute(client):
    user = make_verified_user(username="dee", email="dee@school.edu")
    user.theme = "dark"
    user.save()
    client.force_login(user)
    html = client.get("/home/").content.decode()
    assert 'data-theme="dark"' in html
    assert 'data-theme-pref="dark"' in html


@pytest.mark.django_db
def test_inline_brand_style_comes_after_tokens_css(client):
    # Load-bearing head order: an institution override must win over tokens.css.
    from institution.models import BrandColor

    bc = BrandColor.objects.get(key="primary")
    bc.value = "#3355FF"
    bc.save()
    head = client.get("/accounts/login/").content.decode()
    head = head[: head.index("</head>")]
    assert head.index("core/css/tokens.css") < head.index("--brand-primary: #3355FF")


@pytest.mark.django_db
def test_data_authenticated_attribute_matches_auth_state(client):
    # Pins the contract ui.js relies on to decide whether to POST set_theme.
    anon = client.get("/accounts/login/").content.decode()
    assert 'data-authenticated="0"' in anon
    user = make_verified_user(username="cam", email="cam@school.edu")
    client.force_login(user)
    authed = client.get("/home/").content.decode()
    assert 'data-authenticated="1"' in authed


@pytest.mark.django_db
def test_default_palette_emits_no_brand_style(client):
    # With seeded default colors, brand_vars emits nothing (no empty <style>).
    head = client.get("/accounts/login/").content.decode()
    head = head[: head.index("</head>")]
    assert "core/css/tokens.css" in head
    assert "--brand-primary:" not in head  # no override style for the default palette
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k "renders_shell or theme_and_lang or dark_user or brand_style_after" -v`
Expected: FAIL — current `base.html` has no shell/brand/static/theme attributes.

- [ ] **Step 3: Rewrite `base.html`** — `templates/base.html`:
```django
{% load static i18n branding %}
{% get_current_language as LANGUAGE_CODE %}
<!DOCTYPE html>
<html lang="{{ LANGUAGE_CODE }}" data-theme="{{ data_theme }}"
      data-theme-pref="{{ theme_pref }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block head_title %}libli{% endblock %}</title>
  <script>
    // Pre-paint: resolve auto -> OS theme before stylesheets paint (no flash).
    (function () {
      "use strict";
      var el = document.documentElement;
      var pref = el.getAttribute("data-theme-pref");
      if (!pref) {
        var m = document.cookie.match(/(?:^|; )libli_theme=([^;]+)/);
        pref = m ? m[1] : "auto";
      }
      if (pref === "auto") {
        var dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        el.setAttribute("data-theme", dark ? "dark" : "light");
      } else {
        el.setAttribute("data-theme", pref);
      }
    })();
  </script>
  <link rel="stylesheet" href="{% static 'core/css/reset.css' %}">
  <link rel="stylesheet" href="{% static 'core/css/tokens.css' %}">
  <link rel="stylesheet" href="{% static 'core/css/app.css' %}">
  {% brand_vars %}
  {% block extra_css %}{% endblock %}
</head>
<body>
  <header class="app-header">
    <a class="brand" href="{% url 'home' %}">
      {% if site.logo_url %}<img class="brand__logo" src="{{ site.logo_url }}"
        alt="{{ site.name }}">{% else %}libli<span class="brand__dot">.</span>{% endif %}
    </a>
    <div class="app-header__spacer"></div>
    <div class="app-header__cluster">
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
        title="{% trans 'Toggle theme' %}" aria-label="{% trans 'Toggle theme' %}">◐</button>
      {% if user.is_authenticated %}
        <div class="menu" data-account-menu>
          <button class="avatar" type="button" data-menu-trigger
            aria-haspopup="true" aria-expanded="false">
            {{ user.display_name|default:user.username|slice:":1"|upper }}</button>
          <div class="menu__panel account-menu" data-menu-panel hidden>
            <span class="menu__item">{{ user }}</span>
            <form method="post" action="{% url 'account_logout' %}">
              {% csrf_token %}
              <button class="menu__item" type="submit">{% trans "Log out" %}</button>
            </form>
          </div>
        </div>
      {% elif not hide_auth_cta %}
        <a class="btn--ghost" href="{% url 'account_login' %}">{% trans "Log in" %}</a>
      {% endif %}
    </div>
  </header>
  <main class="app-main">
    {% if messages %}
      {% for message in messages %}
        <div class="alert alert--{{ message.tags }}">{{ message }}</div>
      {% endfor %}
    {% endif %}
    {% block content %}{% endblock %}
  </main>
  <script src="{% static 'core/js/ui.js' %}" defer></script>
  {% block extra_js %}{% endblock %}
</body>
</html>
```
> `{{ message.tags }}` yields Django's level tag (`success`/`warning`/`error`/`info`/`debug`),
> matching the `.alert--*` modifiers in `app.css` (`error` and `danger` both styled).

- [ ] **Step 4: Flesh out `ui.js`** — replace `core/static/core/js/ui.js`:
```javascript
"use strict";
(function () {
  var THEMES = ["light", "dark", "auto"];
  var COOKIE = "libli_theme";
  var el = document.documentElement;

  function getCookie(name) {
    var m = document.cookie.match("(?:^|; )" + name + "=([^;]+)");
    return m ? decodeURIComponent(m[1]) : null;
  }
  function setCookie(name, value) {
    var secure = location.protocol === "https:" ? "; Secure" : "";
    document.cookie = name + "=" + value + "; Path=/; Max-Age=31536000" +
      "; SameSite=Lax" + secure;
  }
  function effective(pref) {
    if (pref === "auto") {
      return window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark" : "light";
    }
    return pref;
  }

  // Theme toggle: cycle pref, update DOM + cookie now; persist if authenticated.
  var toggle = document.querySelector("[data-theme-toggle]");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var cur = el.getAttribute("data-theme-pref") || "auto";
      var next = THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length];
      el.setAttribute("data-theme-pref", next);
      el.setAttribute("data-theme", effective(next));
      setCookie(COOKIE, next);
      if (el.getAttribute("data-authenticated") === "1") {
        var body = new URLSearchParams({ theme: next });
        fetch("/ui/set-theme/", {
          method: "POST", headers: { "X-CSRFToken": getCookie("csrftoken") },
          body: body, credentials: "same-origin",
        });
      }
    });
  }

  // Account menu: open/close with outside-click + Escape.
  var menu = document.querySelector("[data-account-menu]");
  if (menu) {
    var trigger = menu.querySelector("[data-menu-trigger]");
    var panel = menu.querySelector("[data-menu-panel]");
    function close() {
      panel.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    }
    trigger.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = panel.hidden;
      panel.hidden = !open;
      trigger.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("click", function (e) {
      if (!menu.contains(e.target)) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });
  }
})();
```
> The JS reads `data-authenticated` to decide whether to POST. Add that attribute to `<html>`
> in `base.html`: change the opening `<html ...>` tag to also carry
> `data-authenticated="{% if user.is_authenticated %}1{% else %}0{% endif %}"`.

- [ ] **Step 5: Add `data-authenticated` to `base.html`** — update the `<html>` tag:
```django
<html lang="{{ LANGUAGE_CODE }}" data-theme="{{ data_theme }}"
      data-theme-pref="{{ theme_pref }}"
      data-authenticated="{% if user.is_authenticated %}1{% else %}0{% endif %}">
```

- [ ] **Step 6: Compute `hide_auth_cta`** — the shell suppresses the "Log in" CTA on
auth/invite/SSO pages (where it is redundant or wrong). Drive it off the resolved view name.
In `core/context_processors.py`, inside `ui_prefs`, before building the return dict, add:
```python
    rm = getattr(request, "resolver_match", None)
    view_name = getattr(rm, "view_name", "") or ""
    # allauth login etc. resolve to "account_login"/"account_*"; the invite/SSO
    # pages resolve to "accounts:accept_invite"/"accounts:sso_not_provisioned".
    hide_auth_cta = view_name.startswith("account")
```
and add `"hide_auth_cta": hide_auth_cta,` to the returned dict. (`"account"` is a prefix of
both `account_*` and `accounts:*`, so one check covers all the pre-auth pages.)

- [ ] **Step 7: Keep the allauth layout minimal** — `templates/allauth/layouts/base.html`
stays exactly:
```django
{% extends "base.html" %}
```
allauth's element templates fill `{% block content %}` themselves, so this layout must NOT
redefine `content` (that would clobber them). The card styling comes from `app.css` applied
to the form markup; the anonymous shell variant (no account menu) and the suppressed CTA
(`hide_auth_cta`) handle the chrome. The `accept_invite`/`invite_invalid`/`sso_not_provisioned`
templates already extend `base.html` and need no change.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k "renders_shell or theme_and_lang or dark_user or brand_style_after or data_authenticated or default_palette" -v`
Expected: PASS (all seven). Run the whole file: `uv run python -m pytest tests/test_ui_foundation.py -q` → all green.

- [ ] **Step 9: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add templates/ core/static/core/js/ui.js core/context_processors.py
git commit -m "feat(core): app shell base.html + ui.js; restyle auth pages via shell"
```

---

### Task 10: i18n strings — mark, translate to Polish, compile

**Files:**
- Modify: templates (wrap UI strings already added with `{% trans %}` — done in Task 9 for the shell)
- Create: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: append to `tests/test_ui_foundation.py`

> The shell strings ("Log out", "Log in", "Toggle theme") were already marked with
> `{% trans %}` in Task 9. This task extracts them, writes Polish, and compiles.
>
> **Scope of "real Polish" (spec criterion 3):** libli translates only its **own** strings —
> the shell + any custom-page copy. **django-allauth ships its own translation catalog
> (including `pl`)**, so allauth's form labels ("Sign In", "Sign Up", etc.) render in Polish
> automatically when `pl` is active (Django's gettext loads every installed app's `locale/`).
> No libli work is needed for allauth's bundled strings. If a specific allauth string lacks a
> `pl` translation upstream, a thin `{% trans %}`-wrapped template override is a later nicety,
> not a 0d-1 requirement. The Polish-rendering test below asserts a **libli** shell string
> (`Wyloguj`) to verify libli's own catalog is wired and active.

- [ ] **Step 1: Write the failing test** — append to `tests/test_ui_foundation.py`:
```python
@pytest.mark.django_db
def test_polish_shell_string_renders_when_pl_active(client):
    # A pl-preferring user logs in; the login receiver activates pl; the shell's
    # "Log out" renders in Polish from libli's own catalog.
    user = make_verified_user(username="zoe", email="zoe@school.edu")
    user.language = "pl"
    user.save()
    client.force_login(user)
    html = client.get("/home/").content.decode()
    assert "Wyloguj" in html  # "Log out" in Polish
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k polish -v`
Expected: FAIL — no `pl` translation yet (renders English "Log out").

- [ ] **Step 3: Extract messages**
```bash
uv run python manage.py makemessages -l en -l pl --ignore=.venv --ignore=staticfiles
```
Expected: creates `locale/en/LC_MESSAGES/django.po` and `locale/pl/LC_MESSAGES/django.po`
populated with the marked strings (`Log out`, `Log in`, `Toggle theme`, plus any others
marked). If `xgettext` is missing, see the Execution-environment note.

- [ ] **Step 4: Translate to Polish** — edit `locale/pl/LC_MESSAGES/django.po`, filling each
`msgstr` (leave `en` as-is; English is the source). Required entries:
```po
msgid "Log out"
msgstr "Wyloguj"

msgid "Log in"
msgstr "Zaloguj"

msgid "Toggle theme"
msgstr "Przełącz motyw"
```
> Add a Polish `msgstr` for every `msgid` `makemessages` produced (the set is small; translate
> each accurately). Leave the file header's `Content-Type` as `text/plain; charset=UTF-8`.

- [ ] **Step 5: Compile**
```bash
uv run python manage.py compilemessages -l en -l pl
```
Expected: writes `django.mo` next to each `django.po`.

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run python -m pytest tests/test_ui_foundation.py -k polish -v`
Expected: PASS.

- [ ] **Step 7: Commit**
```bash
uv run ruff format .
uv run ruff check .
git add locale/ tests/test_ui_foundation.py
git commit -m "feat(i18n): extract UI strings; real Polish translations; compile"
```
> Commit the compiled `.mo` files (tests and runtime need them; CI does not run
> `compilemessages`). Confirm `.mo` is not gitignored — if it is, `git add -f locale/**/*.mo`
> and note it.

---

### Task 11: Full Plan‑0d‑1 verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full gate**
```bash
uv run ruff format .
uv run ruff check . && uv run ruff format --check .
uv run python -m pytest
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run python manage.py collectstatic --noinput
```
Expected: lint + format pass; **all tests green** (every prior 0a/0b/0c test plus the new
`tests/test_ui_foundation.py`); `No changes detected`; `System check identified no issues`;
`collectstatic` copies assets without error (Inter + tokens + manifest post-processing OK).
Then clean up the build dir: `rm -rf staticfiles`.

- [ ] **Step 2: Manual smoke (optional but recommended)**

Run the dev server and eyeball the shell in a browser (`uv run python manage.py runserver`,
`config.settings.local`): log in, confirm warm-teal identity, toggle theme (light→dark→auto,
no flash on reload), switch EN↔PL (Polish strings appear, returns to same page), and confirm
an institution `BrandColor` override (set `primary` to `#3355FF` in admin) re-themes via the
two injected vars.

- [ ] **Step 3: Commit any formatting-only changes** (if `ruff format` touched files)
```bash
git add -A
git commit -m "chore(0d1): final formatting pass"
```
(Skip if the tree is clean.)

---

## Definition of Done (Plan 0d‑1)

- The existing auth pages (login/signup/reset/verify/logout/password-change) and `/home/`
  render inside the warm-teal **app shell** (brand + `libli.` dot, theme toggle, language
  switch; account menu when authed, no account menu / no redundant CTA when anon).
- A light/dark/auto **theme toggle** works and persists (`User.theme` authed; `libli_theme`
  cookie anon), with the pre-paint script ordered before stylesheets (no flash) and the inline
  brand `<style>` after `tokens.css`.
- **EN↔PL** switch works and persists (`User.language` authed; session anon), constrained to
  `Institution.enabled_languages`, with **real Polish** strings; an anonymous `pl`
  `Accept-Language` is clamped to the default when `pl` is disabled.
- An institution `BrandColor` **primary/accent** override re-themes the whole palette by
  injecting only the two raw vars; invalid/unsafe color values are rejected (admin) and never
  emitted (tag).
- `pytest` green; `ruff check .` + `ruff format --check .` clean; `makemigrations --check`
  clean; `manage.py check` clean; `collectstatic` succeeds.

**Out of scope (Plan 0d‑2):** public landing page, adaptive dashboard shell, user settings
page, minimal institution settings page, branded 403/404/500 error pages.

---

## Self-Review

- **Spec coverage:** `core` app + relocation (Task 1) ✓; CSS-color validation (Task 2) ✓;
  cached read-only accessor + invalidation + guarded logo (Task 3) ✓; context processors +
  theme resolution precedence (Task 4) ✓; tokens/reset/app CSS + `color-mix()` +
  `--surface-raised` literal + Inter + app-static/no-STATICFILES_DIRS + test-storage override
  (Task 5) ✓; `brand_vars` conditional injection + validation guard + emit-after-tokens
  (Tasks 5/6/9) ✓; i18n settings + `gettext_lazy` + exact middleware order + seeder + login
  seed + stale-language fallback + logout cookie clear (Task 7) ✓; `set_ui_language`
  (validated + safe-redirect + hidden `next`) + `set_theme` (authed/204/400) (Task 8) ✓;
  shell `base.html` + two `data-theme*` attrs + pre-paint + head order + messages + anon
  variant + `hide_auth_cta` + logout-authenticated nuance + avatar initials + `ui.js` (Task 9)
  ✓; mark strings + real PL + compile (Task 10) ✓; full verification incl. collectstatic
  (Task 11) ✓.
- **Placeholder scan:** none — every code step shows full content; commands show expected
  output. Two steps contain explicit "revised/decision" narration (Task 1 `core/urls.py`,
  Task 9 `hide_auth_cta`) but each lands on a single concrete implementation.
- **Type/name consistency:** `get_site_config()` keys (`name`/`logo_url`/`primary`/`accent`/
  `enabled_languages`/`default_language`/`default_theme`) are used identically in services,
  context processors, middleware, signals, and the `brand_vars` tag; `THEME_VALUES` /
  `COOKIE_THEME` imported from `core.context_processors`; `validate_css_color` /
  `is_valid_css_color` shared from `institution.validators`; route names `core:set_ui_language`
  / `core:set_theme` and the bare `home` are consistent across views, URLs, templates, tests;
  `data-theme`/`data-theme-pref`/`data-authenticated` attributes match between `base.html` and
  `ui.js`.
- **Decisions honored:** approach A (`color-mix()` from two raw vars); read-only accessor (not
  `load()`); seeder + LocaleMiddleware insertion retaining XFrameOptions; cookie cleared on
  logout; emit-after-tokens head order; real EN/PL.
