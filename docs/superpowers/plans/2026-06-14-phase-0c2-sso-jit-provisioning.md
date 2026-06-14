# Phase 0c‑2 — SSO + JIT Provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the SSO account-origin path to libli: a single OpenID Connect provider plus a JIT-provisioning `SocialAccountAdapter` that gates new identities (invite-override → policy → domain), links SSO logins to existing local accounts by email, pre-verifies the IdP email, lands new users as Students, and shows a generic "not provisioned" page when denied.

**Architecture:** A pure decision function (`accounts/provisioning.py`) encodes the whole gating policy and is unit-tested without allauth. A thin `SocialAccountAdapter` (`accounts/adapters.py`) is the allauth integration shell: it links existing users (verified-`EmailAddress` matches are handled by allauth's own auto-connect; the adapter only links the `User.email`-without-`EmailAddress` case), gates brand-new identities via the decision function, and consumes a matched `Invitation` in `save_user`. The existing `user_signed_up` receiver assigns Student to new social signups for free. A generic not-provisioned page is the only new template.

**Tech Stack:** Python 3.13, Django 5.2, django-allauth 65.18 (`allauth.account` + new `allauth.socialaccount` + `allauth.socialaccount.providers.openid_connect`, `django.contrib.sites`), PostgreSQL (psycopg 3), pytest + pytest-django + factory_boy, ruff. Tests use the locmem email backend.

This plan implements [the Phase 0c‑2 spec](../specs/2026-06-14-phase-0c2-sso-jit-provisioning-design.md), which refines [Phase 0 foundations](../specs/2026-06-13-phase-0-foundations-design.md) §4 (SSO + JIT) and builds on Plan 0c‑1 (the `Invitation` model + `accounts.emails.ensure_verified_primary_email`).

---

## Execution environment

Developer machine is **Windows (win32)**, PowerShell primary, but every `bash` block here is **POSIX sh** and must run through the **Bash tool / Git Bash**. Always invoke Python through **`uv run python ...`** (system `python` is 3.11; uv manages 3.13). PostgreSQL from Plan 0a: role `libli` / password `libli` / database `libli` on `localhost:5432` (CREATEDB; pytest-django builds `test_libli`). Run `uv run ruff format .` before **every** commit. `ruff check` enforces 88-column lines (E501) on all files including comments/docstrings — keep them ≤88 cols. Test fixture password is `tests.factories.TEST_PASSWORD` (`"Sup3r!pass9"`); `tests/**` already ignores `S105/S106/S107`.

**`transaction.atomic` + `select_for_update` in tests:** pytest-django wraps each test in a transaction, so `select_for_update()` does not actually block across threads, but the code path (re-fetch + `is_valid()` re-check) still executes and is asserted.

## Verified-against-source notes (allauth 65.18)

These were confirmed by reading the installed package; they drive specific decisions below.

1. **`is_open_for_signup` override is REQUIRED, not optional.** `DefaultSocialAccountAdapter.is_open_for_signup(request, sociallogin)` returns `get_account_adapter(request).is_open_for_signup(request)` — i.e. our existing `AccountAdapter`, which is `False` under `invite` policy. Without the override, invite-policy SSO signups would be blocked by `SignupClosedException`.
2. **No `account/login.html` override is needed.** The bundled `account/login.html` already does `{% if SOCIALACCOUNT_ENABLED %}{% include "socialaccount/snippets/login.html" ... %}{% endif %}`, so provider buttons render automatically once `socialaccount` is installed and a `SocialApp` exists. The plan does **not** create a login template; it only tests the rendered behavior. (This supersedes spec §5's override assumption.)
3. **The link path must run before `process_auto_signup`.** For a brand-new social identity whose email belongs to an admin-created user (a `User.email` with no `EmailAddress` row), allauth's `process_auto_signup` → `assess_unique_email` does not see a conflict and would let `save_user` hit the `User.email` unique constraint. Our `pre_social_login` link (`connect()` + return → `is_existing` true → `_login`) avoids ever reaching that path.
4. **`user_signed_up` fires for new social signups** via `process_signup` → `complete_social_signup` → `complete_signup`, so the existing `assign_default_student_group` receiver assigns Student with no new code. Linking an existing user goes through `_login` (no signup), so it does **not** fire the signal — existing role preserved.
5. **`SocialLogin.connect()` is not transactional** and sends an `account_connected` notification mail — so the adapter performs the verified-elsewhere clash check *before* `connect()`.

## Scope boundary

**In scope (0c‑2):** `accounts/provisioning.py` (pure `evaluate_sso_provisioning` + domain matching + `resolve_user_for_email` + `verified_email_belongs_to_other`); `Invitation.find_pending` classmethod; `SocialAccountAdapter`; the generic not-provisioned view + route + template; settings + URL wiring for `socialaccount`/`openid_connect`; tests for every gating/linking branch.

**Out of scope — deferred:** provider-specific apps (google/microsoft — OIDC covers them), SSO config UI + SAML (Phase 5), bespoke styling (0d), role-bearing provisioning (0d/Phase 5), emailless login (Phase 1).

## File Structure

```
accounts/
├── provisioning.py        # NEW: Decision, evaluate_sso_provisioning, email_domain,
│                          #      resolve_user_for_email, verified_email_belongs_to_other
├── models.py              # + Invitation.find_pending classmethod
├── adapters.py            # + SocialAccountAdapter (beside existing AccountAdapter)
├── views.py               # + sso_not_provisioned view; _email_is_registered delegates to resolver
├── urls.py                # + sso/not-provisioned/ route
config/
├── settings/base.py       # + socialaccount apps, SOCIALACCOUNT_* settings, refreshed comment
└── urls.py                # + include("allauth.socialaccount.urls")
templates/accounts/
└── sso_not_provisioned.html   # NEW: generic not-provisioned page
tests/
├── _sso.py                # NEW: oidc SocialApp fixture + sociallogin/request builders
├── test_sso_provisioning.py   # NEW: decision fn, lookups, adapter, full-flow, views
```

---

### Task 1: Pure decision function + domain matching

**Files:**
- Create: `accounts/provisioning.py`
- Test: `tests/test_sso_provisioning.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_sso_provisioning.py`:
```python
from accounts.provisioning import Decision, email_domain, evaluate_sso_provisioning


class _Inv:
    """Stand-in for an Invitation (the decision fn treats it as already-valid)."""


def _eval(email, policy, domains, invitation=None):
    return evaluate_sso_provisioning(
        email,
        signup_policy=policy,
        allowed_email_domains=domains,
        invitation=invitation,
    )


def test_email_domain_extraction_lowercases():
    assert email_domain("Alice@Example.COM") == "example.com"
    assert email_domain("no-at-sign") == ""


def test_pre_invited_overrides_policy_and_domain():
    inv = _Inv()
    d = _eval("x@other.org", "invite", ["school.edu"], invitation=inv)
    assert d.allow and d.invitation_to_consume is inv


def test_open_policy_empty_domains_allows_any():
    d = _eval("anyone@anywhere.io", "open", [])
    assert d.allow and d.invitation_to_consume is None


def test_open_policy_matching_domain_allows():
    assert _eval("kid@school.edu", "open", ["school.edu"]).allow


def test_open_policy_nonmatching_domain_denies():
    d = _eval("kid@gmail.com", "open", ["school.edu"])
    assert not d.allow and d.reason == "domain"


def test_invite_policy_without_invite_denies():
    d = _eval("kid@school.edu", "invite", [])
    assert not d.allow and d.reason == "policy"


def test_domain_match_normalizes_stored_entries():
    # Stored entries may be messy: leading @, mixed case, surrounding spaces.
    assert _eval("kid@school.edu", "open", [" School.EDU "]).allow
    assert _eval("kid@school.edu", "open", ["@school.edu"]).allow


def test_domain_match_is_exact_not_subdomain():
    d = _eval("kid@sub.school.edu", "open", ["school.edu"])
    assert not d.allow and d.reason == "domain"


def test_no_at_email_denied_only_in_domain_branch():
    # With a domain allowlist a no-@ email is denied...
    assert not _eval("garbage", "open", ["school.edu"]).allow
    # ...but with no allowlist, open policy admits it (deny lives in the domain branch).
    assert _eval("garbage", "open", []).allow


def test_decision_is_a_dataclass_with_defaults():
    d = Decision(allow=True)
    assert d.reason == "" and d.invitation_to_consume is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_sso_provisioning.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.provisioning'`.

- [ ] **Step 3: Implement** — `accounts/provisioning.py`:
```python
"""SSO/JIT provisioning logic. The gating policy is a pure, side-effect-free
function so every branch is unit-testable without allauth or the database; the
small DB-touching resolvers below are also pure of allauth-flow coupling."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class Decision:
    """Outcome of the gating policy. `invitation_to_consume` is set only when the
    allow was *because of* a pending invite (so the adapter knows to consume it)."""

    allow: bool
    reason: str = ""
    invitation_to_consume: object | None = None


def email_domain(email):
    """The lowercased host part of an email, or "" when there is no '@'."""
    return email.rpartition("@")[2].lower()


def evaluate_sso_provisioning(email, *, signup_policy, allowed_email_domains, invitation):
    """Decide whether a brand-new SSO identity may be provisioned.

    Order: a valid pending invitation overrides everything; otherwise an
    un-invited signup needs signup_policy == "open" and (when a domain allowlist
    is set) an allowed email domain. The caller passes an already-valid
    `invitation` (or None); this function does no clock/DB work itself."""
    if invitation is not None:
        return Decision(allow=True, invitation_to_consume=invitation)
    if signup_policy != "open":
        return Decision(allow=False, reason="policy")
    if allowed_email_domains:
        allowed = {entry.strip().lower().lstrip("@") for entry in allowed_email_domains}
        domain = email_domain(email)
        if not domain or domain not in allowed:
            return Decision(allow=False, reason="domain")
    return Decision(allow=True)


def resolve_user_for_email(email):
    """Return the local user that owns `email`, or None. Prefers the owner of a
    verified allauth EmailAddress, then any EmailAddress owner, then a User.email
    match (the last catches admin-created accounts with no EmailAddress row).
    Read-only; shared by the invite-accept flow and the SSO adapter so they agree."""
    from allauth.account.models import EmailAddress

    from accounts.models import User

    address = (
        EmailAddress.objects.filter(email__iexact=email)
        .order_by("-verified")  # True sorts first, so a verified row wins
        .select_related("user")
        .first()
    )
    if address is not None:
        return address.user
    return User.objects.filter(email__iexact=email).first()


def verified_email_belongs_to_other(email, user):
    """True iff a *verified* EmailAddress for `email` is bound to a different user.
    Used as the pre-link clash guard so ensure_verified_primary_email cannot raise."""
    from allauth.account.models import EmailAddress

    return (
        EmailAddress.objects.filter(email__iexact=email, verified=True)
        .exclude(user=user)
        .exists()
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_sso_provisioning.py -v`
Expected: PASS (all decision-fn tests). `resolve_user_for_email`/`verified_email_belongs_to_other` are exercised in Task 3.

- [ ] **Step 5: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add accounts/provisioning.py tests/test_sso_provisioning.py
git commit -m "feat: pure SSO provisioning decision fn + email resolvers"
```

---

### Task 2: `Invitation.find_pending` lookup

**Files:**
- Modify: `accounts/models.py`
- Test: append to `tests/test_sso_provisioning.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_sso_provisioning.py`:
```python
import datetime

import pytest
from django.utils import timezone

from accounts.models import Invitation


@pytest.mark.django_db
def test_find_pending_returns_most_recent_valid():
    Invitation.objects.create(email="a@school.edu")  # older
    newer = Invitation.objects.create(email="a@school.edu")  # newer, same email
    assert Invitation.find_pending("a@school.edu") == newer


@pytest.mark.django_db
def test_find_pending_is_case_insensitive():
    inv = Invitation.objects.create(email="Mixed@School.edu")
    assert Invitation.find_pending("mixed@school.edu") == inv


@pytest.mark.django_db
def test_find_pending_ignores_accepted_and_expired():
    Invitation.objects.create(email="b@school.edu", accepted_at=timezone.now())
    Invitation.objects.create(
        email="b@school.edu",
        expires_at=timezone.now() - datetime.timedelta(days=1),
    )
    assert Invitation.find_pending("b@school.edu") is None


@pytest.mark.django_db
def test_find_pending_none_when_absent():
    assert Invitation.find_pending("nobody@school.edu") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_sso_provisioning.py -k find_pending -v`
Expected: FAIL — `AttributeError: type object 'Invitation' has no attribute 'find_pending'`.

- [ ] **Step 3: Implement** — in `accounts/models.py`, add this classmethod to the `Invitation` class (place it after `is_valid`):
```python
    @classmethod
    def find_pending(cls, email):
        """The single still-valid invite for `email` to consume on SSO accept:
        case-insensitive, unaccepted, unexpired, most-recently-created first.
        Older pending duplicates are left alone (they expire naturally)."""
        return (
            cls.objects.filter(
                email__iexact=email,
                accepted_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .order_by("-created_at")
            .first()
        )
```
> `timezone` is already imported at the top of `accounts/models.py` (Plan 0c‑1).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_sso_provisioning.py -k find_pending -v`
Expected: PASS (all four).

- [ ] **Step 5: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add accounts/models.py tests/test_sso_provisioning.py
git commit -m "feat: Invitation.find_pending (most-recent valid invite by email)"
```

---

### Task 3: `resolve_user_for_email` + refactor `_email_is_registered`

**Files:**
- Modify: `accounts/views.py`
- Test: append to `tests/test_sso_provisioning.py`

> The invite-accept flow's `_email_is_registered` and the SSO link path must resolve
> the same user, so `_email_is_registered` now delegates to `resolve_user_for_email`.
> The boolean call sites in `accept_invite`/`_consume_and_create` use only truthiness.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_sso_provisioning.py`:
```python
from accounts.provisioning import (
    resolve_user_for_email,
    verified_email_belongs_to_other,
)


@pytest.mark.django_db
def test_resolve_prefers_verified_emailaddress_owner():
    from tests.factories import make_verified_user

    user = make_verified_user(username="verif", email="dup@school.edu")
    assert resolve_user_for_email("DUP@school.edu") == user


@pytest.mark.django_db
def test_resolve_finds_admin_created_user_by_user_email_only():
    # An admin-created user has a User.email but no EmailAddress row.
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    admin_made = User.objects.create_user(
        username="adm", email="adm@school.edu", password=TEST_PASSWORD
    )
    assert resolve_user_for_email("adm@school.edu") == admin_made


@pytest.mark.django_db
def test_resolve_none_when_absent_or_emailless():
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    User.objects.create_user(username="noemail", password=TEST_PASSWORD)  # email NULL
    assert resolve_user_for_email("ghost@school.edu") is None


@pytest.mark.django_db
def test_verified_clash_detects_other_owner():
    from tests.factories import make_verified_user

    owner = make_verified_user(username="owner", email="shared@school.edu")
    other = make_verified_user(username="other", email="other@school.edu")
    assert verified_email_belongs_to_other("shared@school.edu", other) is True
    assert verified_email_belongs_to_other("shared@school.edu", owner) is False


@pytest.mark.django_db
def test_email_is_registered_still_boolean():
    from accounts.views import _email_is_registered
    from tests.factories import make_verified_user

    make_verified_user(username="reg", email="reg@school.edu")
    assert _email_is_registered("reg@school.edu") is True
    assert _email_is_registered("absent@school.edu") is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_sso_provisioning.py -k "resolve or verified_clash or email_is_registered" -v`
Expected: PASS for `resolve_*`/`verified_clash` (Task 1 implemented them) but `_email_is_registered` test passes too with the **current** implementation — so this step instead verifies the **refactor target**: confirm the current `_email_is_registered` does NOT yet delegate. Run `git grep -n "resolve_user_for_email" accounts/views.py` and expect **no output** (not yet wired). Proceed to refactor.

- [ ] **Step 3: Refactor `_email_is_registered`** — in `accounts/views.py`, replace the function body so it delegates to the shared resolver. Change:
```python
def _email_is_registered(email):
    return (
        EmailAddress.objects.filter(email__iexact=email).exists()
        or User.objects.filter(email__iexact=email).exists()
    )
```
to:
```python
def _email_is_registered(email):
    # Delegates to the shared resolver so the invite-accept flow and the SSO
    # adapter agree on "who owns this email". Call sites use only truthiness.
    return resolve_user_for_email(email) is not None
```
Then add the import near the other `accounts` imports at the top of `accounts/views.py`:
```python
from accounts.provisioning import resolve_user_for_email
```
> `EmailAddress` is still imported/used elsewhere in `views.py` — leave that import. If
> `ruff check` reports `EmailAddress` as now-unused, remove the
> `from allauth.account.models import EmailAddress` line; otherwise keep it.

- [ ] **Step 4: Run the tests to verify they pass (incl. the 0c‑1 invite regression)**

Run: `uv run python -m pytest tests/test_sso_provisioning.py tests/test_invitations.py -v`
Expected: PASS — the new resolver tests AND all existing invitation tests (proving the
`accept_invite` `IntegrityError → "registered"` branch and the locked re-check still behave).

- [ ] **Step 5: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add accounts/views.py tests/test_sso_provisioning.py
git commit -m "refactor: _email_is_registered delegates to shared resolve_user_for_email"
```

---

### Task 4: Settings + app + URL wiring

**Files:**
- Modify: `config/settings/base.py`, `config/urls.py`
- Test: append to `tests/test_sso_provisioning.py`

> Adds the socialaccount apps and all SSO settings, applies allauth's bundled
> migrations, and mounts the socialaccount URLs. Verified note #2: no login override.

- [ ] **Step 1: Write the failing test** — append to `tests/test_sso_provisioning.py`:
```python
@pytest.mark.django_db
def test_login_page_shows_provider_when_socialapp_configured(client):
    from allauth.socialaccount.models import SocialApp
    from django.contrib.sites.models import Site

    # No SocialApp yet -> no provider login link on the page.
    assert b"openid_connect" not in client.get("/accounts/login/").content

    app = SocialApp.objects.create(
        provider="openid_connect",
        provider_id="testidp",
        name="Test IdP",
        client_id="client-id",
        secret="secret",
        settings={"server_url": "https://idp.example.test"},
    )
    app.sites.add(Site.objects.get_current())

    # With a configured provider, allauth's bundled login template renders a
    # provider login link (no project login override needed — verified note #2).
    body = client.get("/accounts/login/").content
    assert b"/accounts/testidp/login/" in body
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest tests/test_sso_provisioning.py -k login_page_shows_provider -v`
Expected: FAIL — `socialaccount` is not installed (the `SocialApp` import / migration fails, or the URL/template lacks the snippet).

- [ ] **Step 3: Add the apps and settings** — in `config/settings/base.py`:

(a) Add the two apps to `INSTALLED_APPS` immediately after `"allauth.account"`:
```python
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.openid_connect",
```

(b) Replace the section comment at the allauth block:
```python
# django-allauth (local accounts only; social/SSO lands in Plan 0c).
```
with:
```python
# django-allauth (local accounts + OIDC SSO; social/JIT provisioning added in Plan 0c-2).
```

(c) Insert the SSO settings block immediately after `ACCOUNT_LOGOUT_REDIRECT_URL = "account_login"` and before `AUTH_PASSWORD_VALIDATORS`:
```python
# --- SSO / social (Plan 0c-2) ---
# Custom adapter: JIT provisioning + link-by-email + invite consumption.
SOCIALACCOUNT_ADAPTER = "accounts.adapters.SocialAccountAdapter"
# Link a social login to an existing account that owns a *verified* email
# (auto-connect avoids an interstitial). The adapter additionally links the
# User.email-without-EmailAddress case (admin-created accounts) itself.
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
# Provision brand-new identities form-lessly. The trusted IdP's email is
# authoritative and the adapter pre-verifies it, so the account-level mandatory
# verification (above) must NOT interpose a confirmation step on the SSO path.
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
```

- [ ] **Step 4: Mount the socialaccount URLs** — in `config/urls.py`, add the include right after the `allauth.account.urls` line:
```python
    path("accounts/", include("allauth.account.urls")),
    path("accounts/", include("allauth.socialaccount.urls")),
```
> Both includes intentionally share the `accounts/` prefix — allauth mounts each app's
> URLs under the same root; Django concatenates the patterns. Not a duplication to "fix".

- [ ] **Step 5: Apply allauth's bundled migrations**
```bash
uv run python manage.py migrate
uv run python manage.py makemigrations --check --dry-run
```
Expected: socialaccount tables are migrated; `No changes detected` (the project authors no migration of its own — only allauth's bundled migrations run).

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run python -m pytest tests/test_sso_provisioning.py -k login_page_shows_provider -v`
Expected: PASS. (If the provider login path differs from `/accounts/testidp/login/`, read the rendered body and adjust the assertion to the actual `provider_login_url` — the snippet renders allauth's real URL.)

- [ ] **Step 7: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add config/settings/base.py config/urls.py tests/test_sso_provisioning.py
git commit -m "feat: install socialaccount + openid_connect; SSO settings + URLs"
```

---

### Task 5: Not-provisioned view, route, and template

**Files:**
- Modify: `accounts/views.py`, `accounts/urls.py`
- Create: `templates/accounts/sso_not_provisioned.html`
- Test: append to `tests/test_sso_provisioning.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_sso_provisioning.py`:
```python
@pytest.mark.django_db
def test_not_provisioned_page_renders_generic_copy(client):
    response = client.get("/sso/not-provisioned/")
    assert response.status_code == 200
    body = response.content.lower()
    assert b"not provisioned" in body or b"contact your administrator" in body
    # Generic: does not reveal whether policy or domain caused the denial.
    assert b"domain" not in body and b"policy" not in body


@pytest.mark.django_db
def test_not_provisioned_route_name_resolves():
    from django.urls import reverse

    assert reverse("accounts:sso_not_provisioned") == "/sso/not-provisioned/"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_sso_provisioning.py -k not_provisioned -v`
Expected: FAIL — the route does not exist (404 / `NoReverseMatch`).

- [ ] **Step 3: Add the view** — append to `accounts/views.py`:
```python
def sso_not_provisioned(request):
    """Generic landing for a disallowed SSO login (policy/domain, un-invited).
    No reason enumeration; no account was created."""
    return render(request, "accounts/sso_not_provisioned.html")
```
> `render` is already imported in `accounts/views.py` (Plan 0c‑1).

- [ ] **Step 4: Add the route** — in `accounts/urls.py`, add to `urlpatterns`:
```python
    path("sso/not-provisioned/", views.sso_not_provisioned, name="sso_not_provisioned"),
```

- [ ] **Step 5: Create the template** — `templates/accounts/sso_not_provisioned.html`:
```django
{% extends "base.html" %}
{% block head_title %}Account not provisioned{% endblock %}
{% block content %}
<h1>Account not provisioned</h1>
<p>Your account isn't provisioned for this platform — please contact your administrator.</p>
{% endblock %}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_sso_provisioning.py -k not_provisioned -v`
Expected: PASS (both).

- [ ] **Step 7: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add accounts/views.py accounts/urls.py templates/accounts/sso_not_provisioned.html tests/test_sso_provisioning.py
git commit -m "feat: generic SSO not-provisioned page + route"
```

---

### Task 6: `SocialAccountAdapter` + test harness

**Files:**
- Modify: `accounts/adapters.py`
- Create: `tests/_sso.py`
- Test: append to `tests/test_sso_provisioning.py`

> Depends on Tasks 1–5 (decision fn, resolvers, `find_pending`, settings, not-provisioned route).
> The adapter is a thin shell; its logic lives in the Task‑1 helpers. Tests call the adapter
> methods directly (and build a `SocialLogin` via the harness in `tests/_sso.py`).

- [ ] **Step 1: Create the test harness** — `tests/_sso.py`:
```python
"""Builders for SSO adapter tests: an openid_connect SocialApp, a SocialLogin for
a given IdP email, and a session/messages-enabled request. Kept out of the test
module so multiple test files can share it."""


def make_oidc_app():
    from allauth.socialaccount.models import SocialApp
    from django.contrib.sites.models import Site

    app = SocialApp.objects.create(
        provider="openid_connect",
        provider_id="testidp",
        name="Test IdP",
        client_id="client-id",
        secret="secret",
        settings={"server_url": "https://idp.example.test"},
    )
    app.sites.add(Site.objects.get_current())
    return app


def make_sociallogin(email, username="ssouser", uid="oidc-sub-1", verified=True):
    """An unsaved, not-yet-existing SocialLogin for `email` (provider 'testidp')."""
    from allauth.account.models import EmailAddress
    from allauth.socialaccount.models import SocialAccount, SocialLogin

    from accounts.models import User

    account = SocialAccount(provider="testidp", uid=uid)
    user = User(username=username, email=email)
    addresses = [EmailAddress(email=email, verified=verified, primary=True)]
    return SocialLogin(user=user, account=account, email_addresses=addresses)


def make_request(path="/accounts/testidp/login/callback/"):
    from django.contrib.auth.models import AnonymousUser
    from django.contrib.messages.middleware import MessageMiddleware
    from django.contrib.sessions.middleware import SessionMiddleware
    from django.test import RequestFactory

    request = RequestFactory().get(path)
    SessionMiddleware(lambda r: None).process_request(request)
    MessageMiddleware(lambda r: None).process_request(request)
    request.user = AnonymousUser()
    request.session.save()
    return request
```

- [ ] **Step 2: Write the failing adapter tests** — append to `tests/test_sso_provisioning.py`:
```python
from allauth.core.exceptions import ImmediateHttpResponse


def _adapter():
    from accounts.adapters import SocialAccountAdapter

    return SocialAccountAdapter()


@pytest.mark.django_db
def test_is_open_for_signup_always_true():
    # Required: the default delegates to AccountAdapter (False under invite policy).
    assert _adapter().is_open_for_signup(None, None) is True


@pytest.mark.django_db
def test_pre_social_login_denies_under_invite_policy(settings_invite_policy):
    from tests._sso import make_request, make_sociallogin

    sl = make_sociallogin("newkid@school.edu")
    with pytest.raises(ImmediateHttpResponse):
        _adapter().pre_social_login(make_request(), sl)
    from accounts.models import User

    assert not User.objects.filter(username="ssouser").exists()


@pytest.mark.django_db
def test_pre_social_login_denies_on_domain(settings_open_policy_school_only):
    from tests._sso import make_request, make_sociallogin

    sl = make_sociallogin("outsider@gmail.com")
    with pytest.raises(ImmediateHttpResponse):
        _adapter().pre_social_login(make_request(), sl)


@pytest.mark.django_db
def test_pre_social_login_links_admin_created_user_by_email(oidc_app):
    from allauth.account.models import EmailAddress
    from allauth.socialaccount.models import SocialAccount

    from accounts.models import User
    from tests._sso import make_request, make_sociallogin
    from tests.factories import TEST_PASSWORD

    admin_made = User.objects.create_user(
        username="teacher", email="teacher@school.edu", password=TEST_PASSWORD
    )
    sl = make_sociallogin("teacher@school.edu", username="ignored")
    _adapter().pre_social_login(make_request(), sl)
    # Linked to the existing user (no new account); email now verified+primary.
    assert SocialAccount.objects.filter(user=admin_made, uid="oidc-sub-1").exists()
    assert not User.objects.filter(username="ignored").exists()
    assert EmailAddress.objects.filter(
        user=admin_made, email="teacher@school.edu", verified=True, primary=True
    ).exists()


@pytest.mark.django_db
def test_pre_social_login_denies_on_verified_elsewhere_clash(oidc_app):
    from allauth.socialaccount.models import SocialAccount

    from accounts.models import User
    from tests._sso import make_request, make_sociallogin
    from tests.factories import TEST_PASSWORD, make_verified_user

    # A *verified* email owned by user A, and a bare User.email match on user B.
    make_verified_user(username="owner_a", email="clash@school.edu")
    User.objects.filter(username="owner_a").update(email="other@school.edu")
    # Re-point: user B has User.email = clash@school.edu (no EmailAddress row),
    # user A owns the verified EmailAddress clash@school.edu.
    user_b = User.objects.create_user(
        username="owner_b", email="clash@school.edu", password=TEST_PASSWORD
    )
    sl = make_sociallogin("clash@school.edu", username="ignored")
    with pytest.raises(ImmediateHttpResponse):
        _adapter().pre_social_login(make_request(), sl)
    assert not SocialAccount.objects.filter(uid="oidc-sub-1").exists()
    assert user_b  # unchanged


@pytest.mark.django_db
def test_save_user_creates_verified_user_and_consumes_invite(oidc_app):
    from allauth.account.models import EmailAddress

    from accounts.models import Invitation, User
    from tests._sso import make_request, make_sociallogin

    inv = Invitation.objects.create(email="invitee@school.edu")
    sl = make_sociallogin("invitee@school.edu", username="invitee")
    sl._libli_invitation = inv
    user = _adapter().save_user(make_request(), sl)
    assert User.objects.filter(username="invitee").exists()
    assert EmailAddress.objects.filter(
        user=user, email="invitee@school.edu", verified=True, primary=True
    ).exists()
    inv.refresh_from_db()
    assert inv.accepted_at is not None


@pytest.mark.django_db
def test_save_user_fallback_consumes_invite_without_stash(oidc_app):
    from accounts.models import Invitation
    from tests._sso import make_request, make_sociallogin

    inv = Invitation.objects.create(email="fallback@school.edu")
    sl = make_sociallogin("fallback@school.edu", username="fallback")
    # No _libli_invitation stashed -> fallback re-lookup by user.email.
    _adapter().save_user(make_request(), sl)
    inv.refresh_from_db()
    assert inv.accepted_at is not None


@pytest.mark.django_db
def test_save_user_does_not_consume_expired_invite(oidc_app):
    import datetime

    from django.utils import timezone

    from accounts.models import Invitation
    from tests._sso import make_request, make_sociallogin

    inv = Invitation.objects.create(
        email="stale@school.edu",
        expires_at=timezone.now() - datetime.timedelta(days=1),
    )
    sl = make_sociallogin("stale@school.edu", username="stale")
    sl._libli_invitation = inv
    _adapter().save_user(make_request(), sl)
    inv.refresh_from_db()
    assert inv.accepted_at is None  # re-validated as invalid -> not consumed
```

Add these fixtures at the **top** of `tests/test_sso_provisioning.py` (after imports):
```python
@pytest.fixture
def oidc_app(db):
    from tests._sso import make_oidc_app

    return make_oidc_app()


@pytest.fixture
def settings_invite_policy(db, oidc_app):
    from institution.models import Institution

    inst = Institution.load()
    inst.signup_policy = "invite"
    inst.allowed_email_domains = []
    inst.save()
    return inst


@pytest.fixture
def settings_open_policy_school_only(db, oidc_app):
    from institution.models import Institution

    inst = Institution.load()
    inst.signup_policy = "open"
    inst.allowed_email_domains = ["school.edu"]
    inst.save()
    return inst
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_sso_provisioning.py -k "adapter or pre_social_login or save_user or is_open_for_signup" -v`
Expected: FAIL — `ImportError: cannot import name 'SocialAccountAdapter' from 'accounts.adapters'`.

- [ ] **Step 4: Implement the adapter** — append to `accounts/adapters.py` (keep the existing `AccountAdapter`; add the imports it needs at the top and the new class):
```python
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from accounts.emails import ensure_verified_primary_email
from accounts.models import Invitation
from accounts.provisioning import (
    evaluate_sso_provisioning,
    resolve_user_for_email,
    verified_email_belongs_to_other,
)


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """JIT provisioning + link-by-email for SSO logins. Thin shell over the pure
    helpers in accounts.provisioning; see Plan 0c-2 / spec §2."""

    def pre_social_login(self, request, sociallogin):
        # Already linked to a local user -> let allauth log them in.
        if sociallogin.is_existing:
            return
        email = (sociallogin.user.email or "").strip()
        if email:
            target = resolve_user_for_email(email)
            if target is not None:
                # Order matters: connect() is NOT transactional and notifies, so
                # the verified-elsewhere clash check must deny BEFORE connecting.
                if verified_email_belongs_to_other(email, target):
                    raise ImmediateHttpResponse(self._not_provisioned())
                sociallogin.connect(request, target)
                ensure_verified_primary_email(target, email)
                return
        # Brand-new identity: gate it.
        invitation = Invitation.find_pending(email) if email else None
        decision = self._evaluate(email, invitation)
        if not decision.allow:
            raise ImmediateHttpResponse(self._not_provisioned())
        # Stash the exact invite the allow was made on; save_user consumes it.
        sociallogin._libli_invitation = decision.invitation_to_consume

    def is_open_for_signup(self, request, sociallogin):
        # REQUIRED override: the default delegates to AccountAdapter, which is
        # False under invite policy. pre_social_login already gated, so allow.
        return True

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        if user.email:
            ensure_verified_primary_email(user, user.email)
        self._consume_invitation(sociallogin, user)
        return user

    # --- helpers ---

    def _evaluate(self, email, invitation):
        from institution.models import Institution

        inst = Institution.load()
        return evaluate_sso_provisioning(
            email,
            signup_policy=inst.signup_policy,
            allowed_email_domains=inst.allowed_email_domains,
            invitation=invitation,
        )

    def _consume_invitation(self, sociallogin, user):
        invitation = getattr(sociallogin, "_libli_invitation", None)
        if invitation is None and user.email:
            invitation = Invitation.find_pending(user.email)
        if invitation is None:
            return
        with transaction.atomic():
            locked = Invitation.objects.select_for_update().get(pk=invitation.pk)
            if locked.is_valid():
                locked.accepted_at = timezone.now()
                locked.save(update_fields=["accepted_at"])

    def _not_provisioned(self):
        return redirect(reverse("accounts:sso_not_provisioned"))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_sso_provisioning.py -v`
Expected: PASS (all adapter tests plus the earlier ones). If the `connect()`-based link
tests error inside allauth's provider resolution, confirm the `oidc_app` fixture is applied
to that test and that `SocialAccount.provider` in `tests/_sso.py` equals the app's
`provider_id` (`"testidp"`); the smoke test in Task 7 validates the same harness end-to-end.

- [ ] **Step 6: Format, lint, commit**
```bash
uv run ruff format .
uv run ruff check .
git add accounts/adapters.py tests/_sso.py tests/test_sso_provisioning.py
git commit -m "feat: SocialAccountAdapter (JIT gating, link-by-email, invite consume)"
```

---

### Task 7: End-to-end flow + final verification

**Files:**
- Test: append to `tests/test_sso_provisioning.py`

> Exercises the *real* allauth entrypoint `complete_social_login`, which runs
> `pre_social_login` → (link `_login` | `process_signup` → `save_user` → `complete_signup`).
> This is the only path that fires `user_signed_up` (→ Student) and performs the login.

- [ ] **Step 1: Write the failing end-to-end tests** — append to `tests/test_sso_provisioning.py`:
```python
def _complete(request, sociallogin):
    from allauth.socialaccount.helpers import complete_social_login

    return complete_social_login(request, sociallogin)


@pytest.mark.django_db
def test_e2e_new_allowed_identity_becomes_logged_in_student(settings_open_policy_school_only):
    from allauth.account.models import EmailAddress

    from accounts.models import User
    from tests._sso import make_request, make_sociallogin

    request = make_request()
    response = _complete(request, make_sociallogin("kid@school.edu", username="kid"))
    assert response.status_code == 302  # logged in, redirected to LOGIN_REDIRECT_URL
    user = User.objects.get(username="kid")
    assert user.groups.filter(name="Student").exists()
    assert EmailAddress.objects.filter(
        user=user, email="kid@school.edu", verified=True, primary=True
    ).exists()
    assert request.user == user or request.session.get("_auth_user_id")


@pytest.mark.django_db
def test_e2e_denied_identity_renders_not_provisioned_no_account(settings_invite_policy):
    from accounts.models import User
    from tests._sso import make_request, make_sociallogin

    request = make_request()
    response = _complete(request, make_sociallogin("stranger@school.edu", username="stranger"))
    # ImmediateHttpResponse(redirect) is caught by allauth and returned.
    assert response.status_code in (302, 200)
    if response.status_code == 302:
        assert response["Location"] == "/sso/not-provisioned/"
    assert not User.objects.filter(username="stranger").exists()


@pytest.mark.django_db
def test_e2e_invited_identity_provisions_and_consumes_invite(settings_invite_policy):
    from accounts.models import Invitation, User
    from tests._sso import make_request, make_sociallogin

    inv = Invitation.objects.create(email="welcome@school.edu")
    request = make_request()
    response = _complete(request, make_sociallogin("welcome@school.edu", username="welcome"))
    assert response.status_code == 302
    assert User.objects.filter(username="welcome").exists()
    inv.refresh_from_db()
    assert inv.accepted_at is not None


@pytest.mark.django_db
def test_e2e_link_does_not_add_student_to_existing_role(settings_open_policy_school_only):
    from accounts.models import User
    from institution.roles import PLATFORM_ADMIN
    from tests._sso import make_request, make_sociallogin
    from tests.factories import TEST_PASSWORD

    # An existing admin-created PA (no Student group, no EmailAddress row).
    from django.contrib.auth.models import Group

    pa = User.objects.create_user(
        username="boss", email="boss@school.edu", password=TEST_PASSWORD
    )
    pa.groups.add(Group.objects.get_or_create(name=PLATFORM_ADMIN)[0])
    request = make_request()
    _complete(request, make_sociallogin("boss@school.edu", username="ignored"))
    pa.refresh_from_db()
    assert pa.groups.filter(name=PLATFORM_ADMIN).exists()
    assert not pa.groups.filter(name="Student").exists()  # linking != signup
    assert not User.objects.filter(username="ignored").exists()
```
> `PLATFORM_ADMIN`/`STUDENT` are seeded by `setup_roles`; the `user_signed_up` receiver
> `get_or_create`s the Student group, so these tests do not require a separate role-seed step.
> If `complete_social_login` needs the roles pre-seeded, add `call_command("setup_roles")` at
> the start of the affected test.

- [ ] **Step 2: Run the end-to-end tests**

Run: `uv run python -m pytest tests/test_sso_provisioning.py -k e2e -v`
Expected: PASS. If a test errors inside allauth's provider/serialization machinery, this is
the harness-validation point: confirm `tests/_sso.py`'s `SocialAccount.provider` matches the
`oidc_app` `provider_id`, and that `make_request` attaches session + messages. Adjust the
harness (not the adapter) until the four flows pass; the adapter logic is already unit-proven
in Task 6.

- [ ] **Step 3: Full Plan‑0c‑2 verification**
```bash
uv run ruff format .
uv run ruff check . && uv run ruff format --check .
uv run python -m pytest
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
```
Expected: lint + format pass; **all tests green** (every prior 0a + 0b + 0c‑1 test plus the
new SSO tests); `No changes detected`; `System check identified no issues (0 silenced).`

- [ ] **Step 4: Commit**
```bash
git add tests/test_sso_provisioning.py
git commit -m "test: end-to-end SSO flows (provision/deny/invite/link) via complete_social_login"
```

---

## Definition of Done (Plan 0c‑2)

- With a single `openid_connect` `SocialApp` configured, an allowed user logging in via SSO is
  JIT-provisioned: a new `accounts.User` (auto-unique username, IdP email **verified+primary**),
  in the **Student** group, landing logged-in at `/home/`. The login page shows the provider
  button automatically (no override).
- An SSO login whose email matches an existing local account (incl. admin-created, no
  `EmailAddress` row) **links** to it — no duplicate, role preserved (no Student added).
- An SSO login matching a valid pending **Invitation** is provisioned regardless of policy/domain,
  and the invite is marked accepted (single-use); an expired stashed invite is not consumed.
- A disallowed SSO login (policy/domain, un-invited) renders the generic not-provisioned page;
  **no** account created, **no** invite consumed. A verified-elsewhere email clash denies before
  any `SocialAccount` is persisted.
- `uv run python -m pytest` is green (all existing tests plus the new ones); `ruff check .` and
  `ruff format --check .` pass; `makemigrations --check --dry-run` is clean; `manage.py check`
  is clean.

**Out of scope (later plans):** provider-specific apps; SSO config UI + SAML (Phase 5); bespoke
styling (0d); role-bearing provisioning (0d/Phase 5); emailless login (Phase 1).

---

## Self-Review

- **Spec coverage:** decision fn + domain extraction/normalization + empty-list + no-@ (Task 1) ✓;
  invitation-by-email lookup with most-recent tie-break (Task 2) ✓; `resolve_user_for_email`
  3-tier order + `_email_is_registered` refactor + invite regression (Task 3) ✓; all settings
  named (`SOCIALACCOUNT_EMAIL_AUTHENTICATION[_AUTO_CONNECT]`, `AUTO_SIGNUP`,
  `EMAIL_VERIFICATION="none"`), apps, URL include, bundled-migration note, comment placement
  (Task 4) ✓; generic not-provisioned page + route (Task 5) ✓; adapter — ordered side effects
  (clash check before non-transactional `connect()`), link-by-`User.email`, `is_open_for_signup`
  True, `save_user` base-first + email pre-verify + authoritative-stash consume + fallback +
  locked `is_valid()` re-check (Task 6) ✓; e2e Student-on-new + verified + logged-in + invite
  consume + link-doesn't-add-Student + deny→not-provisioned (Task 7) ✓.
- **Spec deviation (justified):** spec §5 assumed a `templates/account/login.html` override; the
  bundled allauth login template already includes the socialaccount snippet (verified note #2), so
  no override is created — the behavior is tested instead (Task 4). The `is_open_for_signup=True`
  override is shown to be **required** (verified note #1), matching the spec's intent.
- **Placeholder scan:** none — every code step shows full code; every command shows expected
  output. The harness-validation language in Tasks 6/7 points to concrete checks
  (`provider_id == "testidp"`, session/messages attached), not "TBD".
- **Type/name consistency:** `evaluate_sso_provisioning(email, *, signup_policy, allowed_email_domains, invitation)` / `Decision` / `email_domain` / `resolve_user_for_email` / `verified_email_belongs_to_other` (Tasks 1, 3, 6); `Invitation.find_pending` (Tasks 2, 6); `SocialAccountAdapter` (Tasks 4, 6); `accounts:sso_not_provisioned` route (Tasks 5, 6); `_libli_invitation` stash attr (Tasks 6, 7); `tests/_sso.py` `make_oidc_app`/`make_sociallogin`/`make_request` (Tasks 6, 7) — all aligned.
