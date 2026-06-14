# Phase 0c‑2 — SSO + JIT Provisioning: Design Spec

*Spec date: 2026-06-14. A sub-phase of Phase 0 of the [libli roadmap](../../roadmap.md).
Refines the [Phase 0 foundations spec](2026-06-13-phase-0-foundations-design.md) §4 (SSO +
JIT provisioning) and §8, building on Plan 0a (scaffold, custom `accounts.User`, `Institution`
singleton with `signup_policy` + `allowed_email_domains`, seeded role Groups), Plan 0b
(django-allauth local auth, mandatory email verification, signup-policy `AccountAdapter`,
`user_signed_up` → Student signal), and Plan 0c‑1 (the `Invitation` model + the shared
`accounts.emails.ensure_verified_primary_email` helper).*

## Goal

Add the **SSO account-origin path** — the third and final origin Phase 0 needs (after admin-
created and local self-signup/invite). With a single OpenID Connect provider configured (via a
`SocialApp` row in Django admin), a user can log in through their institution's IdP and be
**just-in-time (JIT) provisioned**: gated by signup policy, email-domain allowlist, and pending
invitations; landing as a **Student** with a pre-verified email; or, if their email already
belongs to a local account, **linked** to that account rather than duplicated. Disallowed users
get a generic "not provisioned — contact your admin" page and **no** account is created.

After 0c‑2, all three Phase‑0 account origins exist on one `accounts.User` model: admin-created,
local (invite/open self-signup), and SSO/JIT.

## Scope boundary (decided during brainstorming, 2026-06-14)

**In scope (0c‑2):**
- `allauth.socialaccount` + the **generic `openid_connect`** provider (provider-agnostic; covers
  Google/Microsoft/any standards-compliant IdP via their OIDC endpoints).
- A pure **decision function** `accounts.provisioning.evaluate_sso_provisioning(...)` encoding the
  whole gating policy (invite-override → policy → domain).
- A thin **`SocialAccountAdapter`** (allauth integration shell) that: links to an existing local
  user by email when one exists; otherwise calls the decision function to allow/deny a brand-new
  identity; pre-verifies the IdP email; and consumes a matched invitation.
- **Invitation consumption on SSO** — an SSO login whose email matches a valid pending
  `Invitation` is provisioned and the invite is marked accepted.
- A **not-provisioned** view + route + minimal (unstyled) template (foundations view 1.3).
- A **minimal conditional SSO button** block on the existing login page, shown only when a
  `SocialApp` is configured.
- Run `migrate` to apply allauth's **bundled** `socialaccount`/`openid_connect` migrations (the
  project authors no migration of its own here — no project model changes); focused tests for
  every gating/linking branch.

**Out of scope — deferred:**
- **Provider-specific apps** (`allauth...providers.google`, `...microsoft`): the generic OIDC
  provider covers them now; add dedicated provider apps only if a provider's OIDC support proves
  insufficient.
- **Phase 5:** a friendly **SSO configuration UI** (0c‑2 configures providers through the Django
  admin `SocialApp`, per foundations §4); SAML.
- **0d:** bespoke styling of the login SSO button + not-provisioned page (0c‑2 reuses 0b's
  minimal unstyled `base.html`).
- **Phase 5 / 0d:** **role-bearing** provisioning (every SSO-provisioned user lands as Student; a
  PA promotes staff via Django admin afterward — same rule as 0c‑1 invites).
- **Emailless front-door login** (Phase 1) is unrelated to SSO (SSO accounts always carry an IdP
  email) and remains deferred.

## Execution environment

Windows (win32), PowerShell primary, but every `bash` block runs through the **Bash tool /
Git Bash** (POSIX sh). Always invoke Python through **`uv run python ...`** (system `python`
is 3.11; uv manages 3.13). PostgreSQL provisioned from Plan 0a: role `libli` / password
`libli` / database `libli` on `localhost:5432` (CREATEDB; pytest-django builds `test_libli`).
Run `uv run ruff format .` before every commit; keep comment/docstring lines ≤88 cols
(`ruff check` enforces E501). Tests reuse 0b's `tests.factories.TEST_PASSWORD` fixture password,
the `make_verified_user` factory, and the locmem email backend.

---

## Components

All new code lives in the existing **`accounts`** app; no new Django app is introduced. The
**role Groups and the `Institution` singleton remain owned by the `institution` app** (Plan 0a);
0c‑2 only *reads* `Institution.signup_policy` and `Institution.allowed_email_domains`.

| Unit | File | Responsibility |
|---|---|---|
| Decision function | `accounts/provisioning.py` *(new)* | Pure, side-effect-free gating logic. No DB writes, no allauth objects passed in. |
| Social adapter | `accounts/adapters.py` *(modified)* | `SocialAccountAdapter` beside the existing `AccountAdapter`: link-or-gate, email pre-verify, invite consume. |
| Student-on-signup | `accounts/signals.py` *(unchanged)* | The existing `user_signed_up` receiver already fires for social signups → Student for free. |
| Not-provisioned view | `accounts/views.py` *(modified)* | A `GET` view rendering the generic not-provisioned page. |
| Route | `accounts/urls.py` *(modified)* | `name="sso_not_provisioned"`. |
| Templates | `templates/accounts/sso_not_provisioned.html` *(new)*; `templates/account/login.html` *(modified)* | Minimal not-provisioned page; conditional SSO button block on login. |
| Settings | `config/settings/base.py` *(modified)* | socialaccount apps, `SOCIALACCOUNT_ADAPTER`, email-auth linking flags. |
| URLs | `config/urls.py` *(modified)* | include `allauth.socialaccount.urls`. |

---

## 1. The decision function (`accounts/provisioning.py`)

The gating policy is isolated into one pure function so every branch is unit-testable without
allauth machinery or the database:

```
evaluate_sso_provisioning(email, *, signup_policy, allowed_email_domains, invitation) -> Decision
```

- **Inputs are plain values**, not ORM objects: the caller (adapter) resolves the institution
  config and looks up any matching pending `invitation` first, then passes primitives +
  the invitation object (or `None`).
- **`Decision`** is a small dataclass: `allow: bool`, `reason: str = ""`, and
  `invitation_to_consume` (the invitation when the allow was *because of* an invite, else `None`).

**Logic (in order):**

1. **Pre-invited:** if `invitation` is a valid pending invite for `email` → `allow`,
   `invitation_to_consume = invitation`. **Overrides both policy and domain.**
2. **Un-invited** signup:
   - `signup_policy != "open"` → `deny`, `reason = "policy"`.
   - else `allowed_email_domains` non-empty **and** the email's domain (case-insensitive) ∉ list
     → `deny`, `reason = "domain"`.
   - else → `allow`, `invitation_to_consume = None`.

`reason` exists for tests/logging only; the user-facing page is generic (no policy-vs-domain
enumeration — see Error handling). Validity of the invitation (`is_valid()`, email match) is
checked by the **caller** before passing it in, so the decision function stays pure (no clock,
no DB); it treats a passed-in `invitation` as already-valid.

**Caller's invitation lookup (in the adapter, not the pure fn).** `Invitation.email` is a plain
`EmailField` with no uniqueness constraint, so several pending rows for one address can exist.
The adapter resolves the single candidate as: filter `email__iexact=<idp_email>`, `accepted_at`
is null, `expires_at > now()` (the SQL equivalent of `is_valid()`), ordered by `created_at`
descending, and take the first — i.e. the **most recently created** still-valid invite. That one
becomes `invitation_to_consume`; older pending duplicates for the same address are left untouched
(they expire naturally). No new email-lookup helper exists today, so the plan adds one (e.g. an
`Invitation` manager/classmethod) and unit-tests the tie-break.

## 2. The social adapter (`accounts/adapters.py` → `SocialAccountAdapter`)

A `DefaultSocialAccountAdapter` subclass, registered via `SOCIALACCOUNT_ADAPTER`. It is the thin
shell that turns the pure decision into allauth side effects.

### `pre_social_login(request, sociallogin)`

Runs after the IdP authenticates the user, before allauth logs them in or shows a signup form.

1. **Already linked** (`sociallogin.is_existing`) → return; allauth logs the existing user in.
2. **Link to an existing local user by email.** Two mechanisms cover two distinct cases; the
   adapter only owns the second:
   - **Verified-`EmailAddress` match → allauth's own auto-connect handles it.** With
     `SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True`, allauth connects the social login
     to the user owning a *verified* `EmailAddress` for the IdP email before the adapter would
     need to. The adapter does **not** re-`connect()` this case.
   - **`User.email` match with no (verified) `EmailAddress` row → the adapter links it.** This is
     the gap allauth leaves — chiefly **admin-created** accounts. Resolve the link target with the
     **same dual `iexact` lookup as the existing `accounts/views.py:_email_is_registered`**
     (refactored to return the user, not just a bool, so the invite and SSO paths can't diverge):
     match `EmailAddress.email__iexact` **or** `User.email__iexact`. (Emailless users have
     `User.email = NULL` and are naturally excluded.) If a user is found:
     - `sociallogin.connect(request, user)` to attach the `SocialAccount`,
     - `ensure_verified_primary_email(user, email)` (trusted-IdP: the email becomes verified+primary),
     - return (allauth's standard login proceeds). **No new user, role preserved.**
   - **Eligibility & role:** auto-link applies to a matched account regardless of its role,
     **including a staff/superuser (e.g. the PA who configured SSO with their own email)** — the
     IdP is authoritative for identity in this single-tenant trusted deployment. An **inactive**
     (`is_active = False`) match links but is **not** logged in (allauth's standard inactive-user
     handling applies); SSO never reactivates an account.
   - **Verified-elsewhere conflict (C1 guard):** if the resolved link target is *not* the user who
     already owns a *verified* `EmailAddress` for that address (data drift: the IdP email is
     verified on a **different** user than the `User.email` match), `ensure_verified_primary_email`
     would raise `ValueError`. The adapter treats this as un-resolvable: catch it and route to the
     not-provisioned page (deny) rather than 500. By construction this is rare — the dual lookup
     normally resolves to exactly the user owning the email.
3. **Brand-new identity** → look up a valid pending `Invitation` for the email, then call
   `evaluate_sso_provisioning(...)`:
   - **deny** → `raise ImmediateHttpResponse(redirect(reverse("accounts:sso_not_provisioned")))`.
     No partial account; the invitation (if any was invalid/expired) is untouched.
   - **allow** → stash the `invitation_to_consume` as an attribute on the `sociallogin` instance
     (same request cycle reaches `save_user`), and return; allauth proceeds to create the account.

### `is_open_for_signup(request, sociallogin)`

Returns **`True`**. By the time allauth calls this, `pre_social_login` has already either logged
in/linked an existing user or short-circuited a denied brand-new identity with
`ImmediateHttpResponse` — so any sociallogin that reaches `is_open_for_signup` has already been
allowed. (allauth gives no shared return channel between the two hooks, so there is no decision to
"re-use"; returning `True` here simply lets the already-vetted signup proceed and stops allauth
falling back to its own closed-signup page.)

### `save_user(request, sociallogin, form=None)`

allauth generates a **unique username** here by default (derived from the IdP
`preferred_username`/email local-part, with a numeric suffix on collision — no custom code
needed). After the base `save_user`:

- `ensure_verified_primary_email(user, email)` — pre-verify the IdP email.
- If an `invitation_to_consume` was stashed → set `accepted_at = now()` and save it (idempotent;
  same single-use semantics as 0c‑1's accept view).

The **Student group** is assigned by the existing `user_signed_up` receiver, which allauth fires
for social signups — no duplicate logic here.

### Username + email population

Username derivation and uniqueness are left to allauth's defaults (collision suffixing). The
account's email is the IdP-asserted email. `ACCOUNT_UNIQUE_EMAIL = True` (already set) keeps one
email per user; the link-by-email step (2 above) prevents the unique constraint from ever being
hit by a same-email SSO signup.

## 3. Linking & email trust

- **Trusted IdP:** because this is a single-tenant deploy whose PA configures one IdP they
  control, the IdP's email assertion is authoritative. SSO-provisioned and SSO-linked emails are
  marked verified+primary via `ensure_verified_primary_email`.
- **Link target resolution** checks **both** `EmailAddress` and `User.email` so admin-created
  accounts (which may lack an `EmailAddress` row) link correctly instead of colliding.
- `SOCIALACCOUNT_EMAIL_AUTHENTICATION = True` **and**
  `SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True` enable allauth's own verified-email
  connect path (it auto-connects to the user owning a verified `EmailAddress`); the adapter's
  explicit `User.email` check (§2 step 2) covers the gap allauth leaves for admin-created
  (no-`EmailAddress`) accounts.

## 4. Settings & URLs

`config/settings/base.py`:
- `INSTALLED_APPS` += `"allauth.socialaccount"`, `"allauth.socialaccount.providers.openid_connect"`.
- `SOCIALACCOUNT_ADAPTER = "accounts.adapters.SocialAccountAdapter"`.
- `SOCIALACCOUNT_EMAIL_AUTHENTICATION = True` and
  `SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True` (verified-email linking without an
  interstitial form).
- Refresh the existing allauth-section comment in `base.py` (currently "local accounts only;
  social/SSO lands in Plan 0c") to reflect that SSO now lands here in 0c‑2.
- No SSO provider secrets in settings — credentials live in a `SocialApp` row (Django admin),
  per foundations §4. `SITE_ID = 1` already set; the `SocialApp` is tied to the Site.

`config/urls.py`: `path("accounts/", include("allauth.socialaccount.urls"))` (beside the existing
`allauth.account.urls` include). The not-provisioned route is added under `accounts.urls`
(site-root app namespace) as `sso_not_provisioned`.

## 5. UI (minimal, unstyled — styling deferred to 0d)

- **Login page** (`templates/account/login.html`): a conditional block that `{% load socialaccount %}`
  and, when `{% get_providers %}` is non-empty, renders an SSO login link per provider via
  `{% provider_login_url %}`. Absent any `SocialApp`, the guarded block renders nothing (the page
  is unchanged for local-only installs).
- **Not-provisioned page** (`templates/accounts/sso_not_provisioned.html`): extends `base.html`;
  a generic "Your account isn't provisioned for this platform — please contact your
  administrator." message. No reason enumeration.

> **Template-directory casing is intentional, not a typo:** `templates/account/` (singular) is
> allauth's override territory (the login page we're extending); `templates/accounts/` (plural) is
> *this* app's own templates (joining `accept_invite.html`, `invite_invalid.html`). Both are correct.

---

## Data flow

**SSO login → new allowed user:** SSO button → IdP → allauth callback → `pre_social_login`
(not linked, no local user, decision = allow) → allauth `save_user` (unique username, email from
IdP) → `ensure_verified_primary_email` + consume any invite → `user_signed_up` adds Student →
session → `LOGIN_REDIRECT_URL` (`/home/`).

**SSO login → existing local user:** callback → `pre_social_login` finds a local user by
email → `connect` + verify email → session → `/home/`. (No new user; existing role kept.)

**SSO login → disallowed:** callback → `pre_social_login` decision = deny →
`ImmediateHttpResponse` → not-provisioned page. **No account, no invite consumed.**

## Error handling

- **Disallowed SSO** → generic not-provisioned page; **no** partial account; any (invalid) invite
  untouched.
- **Generic messaging** — the page never reveals whether policy or domain caused the denial
  (mirrors 0c‑1's no-enumeration `invite_invalid` page and the password-reset non-enumeration).
- **Expired/used invitation** → not treated as pre-invited; the login falls through to the
  un-invited policy/domain branches (and is denied under `invite` policy, as expected).
- **Concurrent same-email signup** — the link-by-email step plus `ACCOUNT_UNIQUE_EMAIL` make a
  duplicate-email SSO account unreachable in normal flow; allauth surfaces its standard error if a
  genuine race occurs.

## Testing (no live IdP)

Drive the adapter and decision function directly — no network. Set up a test `SocialApp` for the
`openid_connect` provider and construct allauth `SocialLogin` objects in tests.

- **Decision function (pure):** invite-override (bypasses both `invite` policy and a
  non-matching domain); `open` + empty domains → allow; `open` + matching domain → allow;
  `open` + non-matching domain → deny(`domain`); `invite` policy, no invite → deny(`policy`).
- **Adapter / integration:** brand-new allowed identity → user created, Student group,
  verified+primary email, unique username; **username collision** → numeric suffix;
  **link by `EmailAddress`** (open-signup/invited user) → no new user, SocialAccount attached;
  **link by `User.email`** (admin-created, no `EmailAddress` row) → links, email becomes verified;
  **invite consumed** on SSO match (`accepted_at` set) and **domain bypassed** by the invite;
  **deny** → redirect to not-provisioned, **no** user created, **no** invite consumed;
  **already-linked** login → logs in, no duplicate.
- **Views/routing:** not-provisioned page renders (200, generic copy); login page shows the SSO
  link when a `SocialApp` exists and omits it when none does.

No mocking of the DB layer (project rule). Tests live in `tests/test_sso_provisioning.py` (+ any
adapter/view split if the file grows large).

---

## Definition of Done (Phase 0c‑2)

- With a single `openid_connect` `SocialApp` configured, an allowed user logs in via SSO and is
  JIT-provisioned: new `accounts.User` (auto-unique username, IdP email **verified+primary**), in
  the **Student** group, landing logged-in at `/home/`.
- An SSO login whose email matches an existing local account (incl. admin-created, no
  `EmailAddress` row) **links** to that account — no duplicate, role preserved.
- An SSO login whose email matches a valid pending **Invitation** is provisioned regardless of
  policy/domain, and the invite is marked accepted (single-use).
- A disallowed SSO login (policy/domain, un-invited) renders the generic not-provisioned page;
  **no** account is created and **no** invite is consumed.
- `uv run python -m pytest` green (all existing 0a/0b/0c‑1 tests plus the new SSO tests);
  `ruff check .` + `ruff format --check .` pass; `makemigrations --check --dry-run` clean;
  `manage.py check` clean.

**Out of scope (later):** provider-specific apps, SSO config UI + SAML (Phase 5), bespoke styling
(0d), role-bearing provisioning (0d/Phase 5), emailless login (Phase 1).
