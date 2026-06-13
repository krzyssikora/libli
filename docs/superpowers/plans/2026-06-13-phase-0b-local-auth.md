# Phase 0b — Local Authentication (django-allauth) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire **local** authentication into libli via django-allauth — login (username **or** email + password), logout, password change, password reset, mandatory email verification, and **signup gated by `Institution.signup_policy`** (open self-signup with honeypot + email confirmation; invite ⇒ signup disabled) — with new local signups landing in the **Student** group.

**Architecture:** Add `django-allauth` (account only) on top of the Phase 0a foundation (custom `accounts.User`, `Institution` singleton, seeded role Groups). A custom allauth **account adapter** reads the `Institution` singleton to open/close self-signup by policy. A `user_signed_up` signal assigns the Student group. Auth pages use allauth's own templates wrapped in a **minimal, unstyled** project `base.html` (bespoke CSS/branding is deliberately deferred to Plan 0d). No SSO/social, no JIT, no `init_platform`, no invite tokens (all later plans).

**Tech Stack:** Python 3.13, Django 5.2, **django-allauth 65.x** (`allauth.account` only), `django.contrib.sites`, PostgreSQL (psycopg 3), pytest + pytest-django + factory_boy, ruff. Dev email via Django's console backend; tests via the locmem backend.

This plan implements the [Phase 0 spec](../specs/2026-06-13-phase-0-foundations-design.md) §1 (username/email login), §4 (local auth + signup-policy gating + open-signup hardening), and §2 (Student-on-signup). It follows Plan 0a's conventions and execution environment.

---

## Execution environment

The developer machine is **Windows (win32)** with PowerShell as the primary shell, but
every `bash` block in this plan is written for **POSIX sh** and must be run through the
**Bash tool / Git Bash**. Always invoke Python through **`uv run python ...`** (the system
`python` is 3.11; uv manages 3.13). PostgreSQL is already provisioned from Plan 0a: role
`libli` / password `libli` / database `libli` on `localhost:5432` (the role has `CREATEDB`,
so pytest-django builds `test_libli` itself). Run `uv run ruff format .` before **every**
commit so CI's `ruff format --check` stays green.

The test password `Sup3r!pass9` is used for all signup-form POSTs (which run Plan 0a's
`AUTH_PASSWORD_VALIDATORS`). It clears all four: 11 chars (≥ MinimumLength 8), mixed case +
digit + symbol (not NumericPassword, not a CommonPassword), and dissimilar to the test
usernames/emails (passes UserAttributeSimilarity). If a signup `assert status_code == 302`
ever fails with the form re-rendering at 200, check for a password-validator error first.

## Scope boundary (decided during brainstorming, 2026-06-13)

**In scope (0b):** local login/logout/password-change/password-reset, mandatory email
verification, open-vs-invite signup gating via the singleton, open-signup honeypot +
allauth's default rate limits, Student-group-on-signup, a minimal unstyled `base.html`
layout + a placeholder post-login `home` page.

**Out of scope — deferred:**
- **0c:** SSO/social providers (`allauth.socialaccount`, `SocialApp`), the JIT-provisioning
  adapter, **invite tokens**, `init_platform`, and **pre-verifying admin/init-created users'
  emails** for the allauth front door (init_platform mints the first Platform Admin there).
- **0d:** bespoke token-driven CSS/theming, branded landing/dashboard/error pages, i18n.

> **allauth verification behavior (important):** with `ACCOUNT_EMAIL_VERIFICATION =
> "mandatory"`, a user **without a verified email** cannot log in through the allauth front
> door. This is correct for self-signup, but it also blocks **emailless** users (allauth 65.x
> has no per-user exception — see Task 5 Step 3). So in 0b: (a) **emailless front-door login is
> deferred** to a later plan — every login test uses an email-bearing verified user; (b) **dev
> superusers** still reach Django's `/admin/` via the ModelBackend, which ignores allauth
> verification. Ensuring *admin/init-created users with an email* are pre-verified for the
> allauth front door is a **0c** concern (init_platform), noted above.

## File Structure

```
libli/
├── pyproject.toml                       # + django-allauth dependency
├── config/
│   ├── settings/
│   │   ├── base.py                      # + sites/allauth apps, middleware, backends, ACCOUNT_* settings
│   │   ├── local.py                     # + console email backend
│   │   └── test.py                      # + locmem email backend
│   ├── urls.py                          # + allauth.account.urls, + home/
│   └── views.py                         # NEW: home placeholder view (login-required)
├── accounts/
│   ├── adapters.py                      # NEW: AccountAdapter.is_open_for_signup (reads Institution)
│   ├── signals.py                       # NEW: user_signed_up -> add to Student group
│   └── apps.py                          # ready() imports signals
├── templates/
│   ├── base.html                        # NEW: minimal unstyled layout (block head_title, content)
│   ├── home.html                        # NEW: post-login placeholder
│   └── allauth/layouts/base.html        # NEW: extends "base.html" so allauth pages use our layout
└── tests/
    ├── factories.py                     # + helper for a user with a verified email
    ├── test_auth_login.py               # NEW: username/email login, logout, password change
    ├── test_signup_policy.py            # NEW: open vs invite gating, Student-on-signup
    └── test_signup_hardening.py         # NEW: email verification flow, honeypot, reset no-enumeration
```

---

### Task 1: Add django-allauth and configure base settings

**Files:**
- Modify: `pyproject.toml` (add dependency), `config/settings/base.py`, `config/settings/local.py`, `config/settings/test.py`, `config/urls.py`

- [ ] **Step 1: Add the dependency**

Run:
```bash
uv add "django-allauth>=65.0,<66.0"
```
Expected: resolves and installs `django-allauth==65.x`; `uv.lock` updated.

- [ ] **Step 2: Register the apps, site, middleware, and auth backends in `config/settings/base.py`**

In `INSTALLED_APPS`, add `django.contrib.sites` and the two allauth apps. The block becomes:
```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django_extensions",
    "rest_framework",
    "allauth",
    "allauth.account",
    "accounts",
    "institution",
]
```

Add `allauth.account.middleware.AccountMiddleware` as the **last** entry of `MIDDLEWARE`:
```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]
```

- [ ] **Step 3: Add the allauth configuration block to `config/settings/base.py`**

Append (after the existing `AUTH_USER_MODEL` line is fine; keep it grouped near auth settings):
```python
# django-allauth (local accounts only; social/SSO lands in Plan 0c).
SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",  # Django admin / username-password
    "allauth.account.auth_backends.AuthenticationBackend",  # allauth front door
]

# Log in with username OR email + password (spec §1).
ACCOUNT_LOGIN_METHODS = {"username", "email"}
# Self-signup form fields; "*" marks required. Email is required and (below) confirmed.
ACCOUNT_SIGNUP_FIELDS = ["username*", "email*", "password1*", "password2*"]
ACCOUNT_UNIQUE_EMAIL = True
# Open self-signup requires a confirmed email (double opt-in); the policy adapter
# (Task 3) only enables signup when Institution.signup_policy == "open".
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
# Bot defense for the open-signup form: a hidden trap field (spec §4). allauth's
# default rate limits are also active out of the box.
ACCOUNT_SIGNUP_FORM_HONEYPOT_FIELD = "phone_number"

# Policy-gating adapter is added in Task 3 via ACCOUNT_ADAPTER.
LOGIN_URL = "account_login"  # explicit (Django's default happens to match the allauth mount)
LOGIN_REDIRECT_URL = "home"  # home view added in Task 2; not exercised until then, so safe
ACCOUNT_LOGOUT_REDIRECT_URL = "account_login"
```

> Do **not** set `ACCOUNT_ADAPTER` yet — it points at a class created in Task 3. Until then
> allauth uses its default adapter (signup open), which is fine for Task 1/2.

> **Notes:** (1) `ACCOUNT_LOGIN_METHODS` and `ACCOUNT_SIGNUP_FIELDS` are allauth 65.x's
> replacements for the spec's older `ACCOUNT_AUTHENTICATION_METHOD = "username_email"` and
> `ACCOUNT_EMAIL_REQUIRED`/`ACCOUNT_USERNAME_REQUIRED` (same intent — do not "correct" them
> back to the deprecated names). (2) allauth renders the honeypot as a form input whose HTML
> `name` attribute equals `ACCOUNT_SIGNUP_FORM_HONEYPOT_FIELD` (here `phone_number`); the
> Task 3/Task 6 tests match on that literal name. If a future allauth version changes the
> rendered name, the Task 6 honeypot test fails as "an account was created" (its Step 2 note
> covers that failure mode). (3) We deliberately do **not** set `ACCOUNT_PREVENT_ENUMERATION`
> or `ACCOUNT_EMAIL_UNKNOWN_ACCOUNTS`; both default `True` in allauth 65.x, which is exactly
> the non-enumerating password-reset behavior Task 7 tests (a courtesy email is sent even for
> unknown addresses so known vs unknown look identical).

- [ ] **Step 4: Add the console email backend to `config/settings/local.py`**

Append to `config/settings/local.py`:
```python
# Dev: print confirmation / password-reset emails to the runserver console.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
```

- [ ] **Step 5: Add the locmem email backend to `config/settings/test.py`**

Append to `config/settings/test.py`:
```python
# Tests assert on django.core.mail.outbox, which only the locmem backend populates.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
```

- [ ] **Step 6: Mount the allauth URLs in `config/urls.py`**

Add the include (keep the existing `admin/` and `healthz/` patterns). The file becomes:
```python
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include
from django.urls import path


def healthz(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz, name="healthz"),
    path("accounts/", include("allauth.account.urls")),
]
```

- [ ] **Step 7: Apply migrations and verify the project boots**

Run:
```bash
uv run python manage.py migrate
uv run python manage.py check
```
Expected: `sites` and `allauth.account` migrations apply; `System check identified no issues (0 silenced).`

> `django.contrib.sites` seeds a default `Site(pk=1, domain="example.com")` on migrate, which
> satisfies `SITE_ID = 1` (and is recreated automatically in the freshly-built test DB). allauth
> email links will therefore use `example.com` in dev/tests — acceptable for 0b; the real host
> is configured at deploy time later.

- [ ] **Step 8: Confirm migrations are in sync, format, lint, commit**

```bash
uv run python manage.py makemigrations --check --dry-run   # expect: No changes detected
uv run ruff format .
uv run ruff check .
git add pyproject.toml uv.lock config/settings/base.py config/settings/local.py config/settings/test.py config/urls.py
git commit -m "feat: add django-allauth (account) with base auth settings + URLs"
```

---

### Task 2: Minimal base layout + placeholder home page

**Files:**
- Create: `templates/base.html`, `templates/allauth/layouts/base.html`, `templates/home.html`, `config/views.py`
- Modify: `config/urls.py`
- Test: `tests/test_auth_login.py` (first test only — login page + home redirect)

- [ ] **Step 1: Write the failing test**

`tests/test_auth_login.py`:
```python
def test_login_page_renders(client):
    response = client.get("/accounts/login/")
    assert response.status_code == 200
    # <main> comes from templates/base.html's body (Step 3), which allauth pages reach ONLY
    # through the allauth/layouts/base.html override (Step 4) — so its presence proves our
    # layout actually wrapped the allauth page. (Validated against allauth 65.18.x, which Task 1
    # resolves under ">=65.0,<66.0": entrance.html/manage.html both extend allauth/layouts/base.html,
    # so the single override covers every page.) We do NOT assert <title>libli</title> here:
    # account/login.html overrides {% block head_title %} to "Sign In", so the libli default
    # title only appears on pages that don't override it (e.g. our home page).
    assert b"<main>" in response.content
    assert b"Sign In" in response.content  # allauth's login content rendered inside our layout


def test_home_requires_login(client):
    response = client.get("/home/")
    # @login_required redirects anonymous users to the allauth login URL.
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest tests/test_auth_login.py -v`
Expected: FAIL — `/home/` is not routed yet (404, not 302), and the login page has no `libli` title wrapper.

- [ ] **Step 3: Create the minimal project layout** — `templates/base.html`:
```django
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block head_title %}libli{% endblock %}</title>
</head>
<body>
  <main>
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 4: Wrap allauth pages in our layout** — `templates/allauth/layouts/base.html`:
```django
{% extends "base.html" %}
```
> allauth's entrance/manage layouts extend `allauth/layouts/base.html`; overriding it to
> extend our `base.html` flows every allauth page's `{% block content %}` /
> `{% block head_title %}` through our minimal (unstyled) layout. Styling lands in Plan 0d.

> The `Write` tool creates parent directories automatically. If creating these files via
> shell instead, run `mkdir -p templates/allauth/layouts` first (the nested path is new —
> the repo has no `templates/` directory yet).

- [ ] **Step 5: Create the placeholder home view** — `config/views.py`:
```python
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    """Placeholder post-login page. Deliberate 0b stop-gap: it lives in config/ only because
    0b has no UI app yet. Plan 0d relocates it into the core/web app (spec §Components) as the
    real adaptive dashboard shell."""
    return render(request, "home.html")
```

`templates/home.html`:
```django
{% extends "base.html" %}
{% block content %}<p>You are logged in as {{ user }}.</p>{% endblock %}
```

- [ ] **Step 6: Route the home view** — update `config/urls.py` to import and mount it:
```python
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include
from django.urls import path

from config.views import home


def healthz(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz, name="healthz"),
    path("home/", home, name="home"),
    path("accounts/", include("allauth.account.urls")),
]
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `uv run python -m pytest tests/test_auth_login.py -v`
Expected: PASS (both tests).

- [ ] **Step 8: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add templates config/views.py config/urls.py tests/test_auth_login.py
git commit -m "feat: minimal base layout + placeholder home page for allauth"
```

---

### Task 3: Policy-gating account adapter

**Files:**
- Create: `accounts/adapters.py`
- Modify: `config/settings/base.py` (set `ACCOUNT_ADAPTER`)
- Test: `tests/test_signup_policy.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_signup_policy.py`:
```python
from institution.models import Institution


def _set_policy(policy):
    inst = Institution.load()
    inst.signup_policy = policy
    inst.save()


def test_signup_open_when_policy_open(client):
    _set_policy("open")
    response = client.get("/accounts/signup/")
    assert response.status_code == 200
    assert b'name="phone_number"' in response.content  # honeypot input is rendered on the open form


def test_signup_closed_when_policy_invite(client):
    from accounts.models import User

    _set_policy("invite")
    # GET shows allauth's default account/signup_closed.html (an allauth-provided template,
    # rendered at 200) instead of the form. Discriminate on the absence of the signup form's
    # username input rather than the honeypot field name.
    get_response = client.get("/accounts/signup/")
    assert get_response.status_code == 200
    assert b'name="username"' not in get_response.content  # the signup form is not rendered
    # POST must not create an account.
    client.post(
        "/accounts/signup/",
        {"username": "sneaky", "email": "s@x.edu", "password1": "Sup3r!pass9", "password2": "Sup3r!pass9"},
    )
    assert not User.objects.filter(username="sneaky").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_signup_policy.py -v`
Expected: FAIL — without the custom adapter signup is open regardless of policy, so the
invite case still renders the form / could create the account.

- [ ] **Step 3: Implement the adapter** — `accounts/adapters.py`:
```python
from allauth.account.adapter import DefaultAccountAdapter

from institution.models import Institution


class AccountAdapter(DefaultAccountAdapter):
    """Gate self-signup on the institution's runtime signup policy (spec §4).

    `open`  -> self-signup enabled (email required + confirmed; honeypot active).
    `invite` (or anything else) -> self-signup disabled; accounts arrive via the
    Django admin (Plan 0a) and, later, invite tokens (Plan 0c).
    """

    def is_open_for_signup(self, request):
        return Institution.load().signup_policy == "open"
```

- [ ] **Step 4: Point allauth at the adapter** — append to `config/settings/base.py`:
```python
ACCOUNT_ADAPTER = "accounts.adapters.AccountAdapter"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_signup_policy.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add accounts/adapters.py config/settings/base.py tests/test_signup_policy.py
git commit -m "feat: gate self-signup on Institution.signup_policy via allauth adapter"
```

---

### Task 4: New signups default to the Student group

**Files:**
- Create: `accounts/signals.py`
- Modify: `accounts/apps.py` (connect signals in `ready()`)
- Test: add to `tests/test_signup_policy.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_signup_policy.py`:
```python
def test_signup_adds_user_to_student_group(client):
    from accounts.models import User

    _set_policy("open")
    response = client.post(
        "/accounts/signup/",
        {
            "username": "newbie",
            "email": "newbie@school.edu",
            "password1": "Sup3r!pass9",
            "password2": "Sup3r!pass9",
        },
    )
    # A successful signup redirects (to the verification-sent page under mandatory
    # verification); asserting 302 makes a rejected form fail at the POST, not the ORM lookup.
    assert response.status_code == 302
    user = User.objects.get(username="newbie")
    assert user.groups.filter(name="Student").exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest tests/test_signup_policy.py::test_signup_adds_user_to_student_group -v`
Expected: FAIL — the new user is created but belongs to no group.

- [ ] **Step 3: Implement the signal** — `accounts/signals.py`:
```python
from allauth.account.signals import user_signed_up
from django.contrib.auth.models import Group
from django.dispatch import receiver

from institution.roles import STUDENT


@receiver(user_signed_up)
def assign_default_student_group(sender, request, user, **kwargs):
    """New local self-signups default to the Student group (spec §2). Roles are
    Groups seeded in Plan 0a; we never branch on role *name* in app logic."""
    group, _ = Group.objects.get_or_create(name=STUDENT)
    user.groups.add(group)
```

- [ ] **Step 4: Connect the signal in `accounts/apps.py`** — add a `ready()` method:
```python
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        from accounts import signals  # noqa: F401  (registers the user_signed_up receiver)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run python -m pytest tests/test_signup_policy.py -v`
Expected: PASS (all three tests in the file).

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add accounts/signals.py accounts/apps.py tests/test_signup_policy.py
git commit -m "feat: assign new local signups to the Student group"
```

---

### Task 5: Login (username + email), logout, password change

**Files:**
- Modify: `tests/factories.py` (add a verified-email helper), `tests/test_auth_login.py`

- [ ] **Step 1: Add a verified-user helper** — append to `tests/factories.py`:
```python
def make_verified_user(username="member", email="member@school.edu", password="Sup3r!pass9"):
    """Create a user with a *verified, primary* allauth EmailAddress so that, under
    mandatory email verification, they can log in via username OR email. allauth resolves
    email-login against the `EmailAddress` table (not `auth_user.email`), so this row must
    exist for email login to succeed."""
    # Local import keeps shared test infra (UserFactory) from importing allauth at module load.
    from allauth.account.models import EmailAddress

    user = User.objects.create_user(username=username, email=email, password=password)
    # create_user does not trigger allauth's EmailAddress sync, so get_or_create simply yields
    # (and then forces verified + primary on) the EmailAddress that email login needs.
    email_address, _ = EmailAddress.objects.get_or_create(
        user=user, email=email, defaults={"verified": True, "primary": True}
    )
    if not (email_address.verified and email_address.primary):
        email_address.verified = True
        email_address.primary = True
        email_address.save()
    return user
```

- [ ] **Step 2: Write the failing login/logout/password tests** — append to `tests/test_auth_login.py`:
```python
def test_login_with_username(client):
    # A user with a verified email logs in via their USERNAME identifier (proves the username
    # login method). 0b uses email-bearing verified users for login tests; emailless
    # front-door login is deferred — see the verification note in Task 5 Step 3.
    from tests.factories import make_verified_user

    make_verified_user(username="member", email="member@school.edu")
    response = client.post("/accounts/login/", {"login": "member", "password": "Sup3r!pass9"})
    assert response.status_code == 302
    assert response["Location"].endswith("/home/")
    assert client.session.get("_auth_user_id")  # session is authenticated


def test_login_with_email(client):
    from tests.factories import make_verified_user

    make_verified_user(username="emailer", email="emailer@school.edu")
    response = client.post(
        "/accounts/login/", {"login": "emailer@school.edu", "password": "Sup3r!pass9"}
    )
    assert response.status_code == 302
    assert response["Location"].endswith("/home/")
    assert client.session.get("_auth_user_id")


def test_logout(client):
    from tests.factories import make_verified_user

    make_verified_user(username="member", email="member@school.edu")
    client.post("/accounts/login/", {"login": "member", "password": "Sup3r!pass9"})
    assert client.session.get("_auth_user_id")
    # allauth 65.x logs out on POST (a GET shows a confirmation page); assert the response
    # so a future verb change fails loudly instead of leaving the session silently set.
    logout_response = client.post("/accounts/logout/")
    assert logout_response.status_code in (200, 302)
    assert not client.session.get("_auth_user_id")


def test_password_change_requires_login(client):
    response = client.get("/accounts/password/change/")
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]
```

- [ ] **Step 3: Run the tests to verify status**

Run: `uv run python -m pytest tests/test_auth_login.py -v`
Expected: these tests exercise allauth wiring already configured in Tasks 1–2. They should
**PASS** as written.

> **Verification + emailless login — a real allauth constraint (decided 2026-06-13).** Under
> `ACCOUNT_EMAIL_VERIFICATION = "mandatory"`, allauth's `EmailVerificationStage` blocks login
> for **any** user lacking a verified email — including username-only/emailless users. (Verified
> against allauth 65.18 source: the MANDATORY branch returns `respond_email_verification_sent`
> whenever `has_verified_email(login.user, login.email)` is False, with no emailless exception;
> and 65.x exposes **no** per-user adapter hook — `DefaultAccountAdapter` has no
> `is_email_verification_mandatory`/verification-level method — to vary this.) That is why every
> login test in 0b uses an **email-bearing, verified** user via `make_verified_user`, which is
> realistic: 0b's only account-creation path (open self-signup) produces confirmed-email users,
> and the Plan 0c Platform Admin has an email too. **Emailless front-door login is deliberately
> deferred** to a later plan — it requires a custom login stage, and emailless accounts plus a
> real post-login app don't exist until later (0b's `home` is only a placeholder). Do **not**
> add a per-user verification override in 0b.

> This task is verification-first rather than red→green: the behavior is provided by allauth
> config from earlier tasks. The tests lock that behavior in so later tasks can't regress it.

- [ ] **Step 4: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add tests/factories.py tests/test_auth_login.py
git commit -m "test: lock in username/email login, logout, password-change gating"
```

---

### Task 6: Open-signup hardening — email verification + honeypot

**Files:**
- Create: `tests/test_signup_hardening.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_signup_hardening.py`:
```python
from django.core import mail

from accounts.models import User
from institution.models import Institution


def _open_signup():
    inst = Institution.load()
    inst.signup_policy = "open"
    inst.save()


def test_open_signup_sends_verification_and_blocks_login_until_verified(client):
    _open_signup()
    mail.outbox.clear()
    response = client.post(
        "/accounts/signup/",
        {
            "username": "pending",
            "email": "pending@school.edu",
            "password1": "Sup3r!pass9",
            "password2": "Sup3r!pass9",
        },
    )
    assert response.status_code == 302  # successful signup redirects to verification-sent
    # Account exists but a verification email was sent (mandatory verification).
    assert User.objects.filter(username="pending").exists()
    assert len(mail.outbox) == 1
    assert "pending@school.edu" in mail.outbox[0].to

    # Logging out then back in is blocked until the email is verified: allauth sends the
    # login into the "verification sent" flow and establishes no authenticated session.
    client.post("/accounts/logout/")
    response = client.post(
        "/accounts/login/", {"login": "pending", "password": "Sup3r!pass9"}
    )
    assert response.status_code == 302
    assert "/confirm-email/" in response["Location"]  # allauth's verification-sent page
    assert not client.session.get("_auth_user_id")  # positively: no authenticated session


def test_honeypot_filled_submission_creates_no_account(client):
    _open_signup()
    before = User.objects.count()
    response = client.post(
        "/accounts/signup/",
        {
            "username": "bot",
            "email": "bot@school.edu",
            "password1": "Sup3r!pass9",
            "password2": "Sup3r!pass9",
            "phone_number": "i-am-a-bot",  # the honeypot trap field
        },
    )
    # allauth fakes a *successful* signup (302 redirect) while creating nothing — asserting the
    # redirect distinguishes "bot trapped" from an unrelated 200 form rejection.
    assert response.status_code == 302
    assert User.objects.count() == before
    assert not User.objects.filter(username="bot").exists()


def test_open_signup_requires_email(client):
    # Spec §4: email is required (and confirmed) on the open self-signup form. A blank-email
    # POST must be rejected (form re-renders 200, no account) — this pins the "email*" marker
    # in ACCOUNT_SIGNUP_FIELDS that the bot-defense + SSO-linkage story depends on.
    _open_signup()
    before = User.objects.count()
    response = client.post(
        "/accounts/signup/",
        {"username": "noemail", "email": "", "password1": "Sup3r!pass9", "password2": "Sup3r!pass9"},
    )
    assert response.status_code == 200  # form re-rendered with errors, not a 302 redirect
    assert User.objects.count() == before
    assert not User.objects.filter(username="noemail").exists()
```

- [ ] **Step 2: Run the tests**

Run: `uv run python -m pytest tests/test_signup_hardening.py -v`
Expected: PASS — verification + honeypot are configured by Task 1's settings. If the honeypot
test fails because an account *was* created, recheck `ACCOUNT_SIGNUP_FORM_HONEYPOT_FIELD` in
`base.py` and that the field name in the POST matches it.

- [ ] **Step 3: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add tests/test_signup_hardening.py
git commit -m "test: open-signup email verification + honeypot bot defense"
```

---

### Task 7: Password reset (no user enumeration) + full verification

**Files:**
- Modify: `tests/test_signup_hardening.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_signup_hardening.py`:
```python
def test_password_reset_unknown_email_does_not_enumerate(client):
    # allauth defaults to ACCOUNT_PREVENT_ENUMERATION=True (and ACCOUNT_EMAIL_UNKNOWN_ACCOUNTS
    # =True): a reset for an address with NO account returns the SAME generic 302 to the
    # reset-done page AND still sends a courtesy email — so known vs unknown are
    # indistinguishable. The non-enumeration contract is "identical observable behavior", not
    # "no email". (Both defaults are on without us setting anything; see Task 1's note.)
    mail.outbox.clear()
    response = client.post("/accounts/password/reset/", {"email": "nobody@nowhere.edu"})
    assert response.status_code == 302
    assert response["Location"].endswith("/password/reset/done/")
    assert len(mail.outbox) == 1  # enumeration-prevention email; UX identical to a real account


def test_password_reset_known_email_sends_link(client):
    from tests.factories import make_verified_user

    make_verified_user(username="resetme", email="resetme@school.edu")
    mail.outbox.clear()
    response = client.post("/accounts/password/reset/", {"email": "resetme@school.edu"})
    # Identical observable behavior to the unknown-email case above (same 302, same outbox
    # count) — that symmetry is exactly what defeats enumeration.
    assert response.status_code == 302
    assert response["Location"].endswith("/password/reset/done/")
    assert len(mail.outbox) == 1
    assert "resetme@school.edu" in mail.outbox[0].to
```

- [ ] **Step 2: Run the tests to verify status**

Run: `uv run python -m pytest tests/test_signup_hardening.py -v`
Expected: PASS — allauth's default reset flow avoids enumeration by giving known and unknown
emails identical observable behavior (same 302 to `/password/reset/done/`, and — because
`ACCOUNT_PREVENT_ENUMERATION` defaults `True` — an email is sent in both cases).

- [ ] **Step 3: Full Plan-0b verification**

Run:
```bash
uv run ruff format .
uv run ruff check . && uv run ruff format --check .
uv run python -m pytest
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
```
Expected: lint + format pass; **all tests green** (0a's 16 + the new auth tests);
`No changes detected`; `System check identified no issues (0 silenced).`

- [ ] **Step 4: Commit**

```bash
git add tests/test_signup_hardening.py
git commit -m "test: password reset avoids user enumeration; sends link for real accounts"
```

---

## Definition of Done (Plan 0b)

- `uv sync` succeeds; `uv run python manage.py check` is clean.
- `uv run python -m pytest` is green: Plan 0a's 16 tests **plus** 14 new auth tests, by file:
  `test_auth_login.py` = 6 (2 from Task 2 + 4 from Task 5), `test_signup_policy.py` = 3,
  `test_signup_hardening.py` = 5 (3 from Task 6 + 2 from Task 7) → **30 total** (login by
  username/email, logout, password-change gating, signup-policy open/invite, Student-on-signup,
  email required + verification, honeypot, password-reset no-enumeration).
- `uv run ruff check .` and `uv run ruff format --check .` pass.
- `makemigrations --check --dry-run` reports no missing migrations.
- A user **with a verified email** can log in with **username or email** + password. (Emailless
  front-door login is deferred under mandatory verification — see Task 5 Step 3.)
- Self-signup is **enabled only under `signup_policy == "open"`**, requires a confirmed email
  (mandatory verification), is honeypot-guarded, and lands the new user in the **Student** group.
- Under `signup_policy == "invite"`, self-signup is disabled (no account created on POST).
- Password reset works for accounts with email and does not enumerate users.

**Out of scope (later plans):** SSO/social + `SocialApp` + JIT adapter + invite tokens +
`init_platform` + pre-verifying admin/init-created emails + **emailless front-door login**
(a custom login stage, **0c+**); bespoke CSS/theming, branded landing/dashboard/error pages,
i18n (**0d**).

---

## Self-Review

- **Spec coverage:** §1 username/email login (Task 1 settings + Task 5 tests) ✓; §4 local
  login/logout/password-change/reset + mandatory verification (Tasks 1, 5, 6, 7) ✓; §4
  signup-policy gating open/invite (Task 3) ✓; §4 open-signup hardening — honeypot + allauth
  default rate limits (Task 1 settings + Task 6 test) ✓; §2 Student-on-signup (Task 4) ✓.
  SSO/JIT/init_platform/invite-tokens and theming/views/i18n correctly deferred to 0c/0d.
- **Placeholder scan:** none — every code step shows full code; the one verification foot-gun
  (mandatory verification vs admin/init-created emails) is explicitly scoped to 0c with the
  emailless/superuser cases handled here.
- **Type/name consistency:** `Institution.load()` / `signup_policy`, `STUDENT` + Group name
  `"Student"` (from 0a `institution.roles`), `ACCOUNT_SIGNUP_FORM_HONEYPOT_FIELD = "phone_number"`
  matched by the honeypot test, `LOGIN_REDIRECT_URL = "home"` matched by the `home` URL name and
  the `/home/` redirect assertions, and `make_verified_user` used consistently across login/reset
  tests are all aligned across tasks.
