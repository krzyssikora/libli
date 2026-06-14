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
| Templates | `templates/accounts/sso_not_provisioned.html` *(new)*; `templates/account/login.html` *(new override)* | Minimal not-provisioned page; SSO button block added by a new allauth login override. |
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
   - else if `allowed_email_domains` is non-empty **and** the email's domain ∉ the list → `deny`,
     `reason = "domain"`.
   - else → `allow`, `invitation_to_consume = None`.

**Domain matching (canonical — no prior code to inherit from).** `allowed_email_domains` is a
free-form `JSONField(default=list)` with no validation, so entries may arrive as `"Example.com"`,
`"@example.com"`, or `" example.com "`. The function:
- derives the email domain as `email.rpartition("@")[2].lower()`;
- normalizes each stored entry as `entry.strip().lower().lstrip("@")` into a set, and tests exact
  set membership. **Subdomain matching is out of scope** (a stored `example.com` does **not** admit
  `alice@sub.example.com`) — exact host match only;
- treats an email with **no `@`** (shouldn't occur from an IdP) as a `deny` (`reason = "domain"`),
  defensively.
**An empty `allowed_email_domains` imposes no domain restriction** — under `open` policy any domain
is admitted (this is the field's default `[]` and the common production case).

`reason` exists for tests/logging only; the user-facing page is generic (no policy-vs-domain
enumeration — see Error handling). Validity of the invitation (`is_valid()`, email match) is
checked by the **caller** before passing it in, so the decision function stays pure (no clock,
no DB); it treats a passed-in `invitation` as already-valid.

**Caller's invitation lookup (in the adapter, not the pure fn).** `Invitation.email` is a plain
`EmailField` with no uniqueness constraint, so several pending rows for one address can exist.
The adapter resolves the single candidate as: filter `email__iexact=<idp_email>`, `accepted_at`
is null, `expires_at > timezone.now()` (`django.utils.timezone`; the SQL equivalent of
`is_valid()`), ordered by `created_at` descending, and take the first — i.e. the **most recently
created** still-valid invite. That one becomes `invitation_to_consume`; older pending duplicates
for the same address are left untouched (they expire naturally). No new email-lookup helper exists
today, so the plan adds one (e.g. an `Invitation` manager/classmethod) and unit-tests the
tie-break. The chosen invite is **re-validated with `is_valid()` at consumption time** in
`save_user` (see §2), so the queryset filter is a selection step, not the final guard.

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
     `User.email = NULL` and are naturally excluded.) **Resolution contract:** the refactored helper
     returns a single user, preferring the owner of a verified `EmailAddress` over a bare
     `User.email` match (with `ACCOUNT_UNIQUE_EMAIL = True` and the verified-elsewhere guard below,
     the two can only disagree under data drift); a `None` return is falsy, so the existing boolean
     `accept_invite`/`_consume_and_create` call sites keep identical behavior. The refactored helper
     is **read-only and side-effect-free** and its two non-SSO call sites use only its *truthiness*
     (never the returned user) — including the one inside `_consume_and_create`'s
     `select_for_update()` atomic block and the one in the post-`IntegrityError` recovery branch of
     `accept_invite`. A regression test for that `IntegrityError → "registered"` branch is kept so
     the refactor cannot silently alter it.
   - **Order side effects so a deny never leaves state behind (C1):** `SocialLogin.connect()` is
     **not** transactional — it immediately persists the `SocialAccount` and fires
     `social_account_added` (a connect-notification). So the adapter performs the
     **verified-elsewhere clash check first** (query `EmailAddress.objects.filter(email__iexact=email,
     verified=True).exclude(user=target)`): if a *different* user already owns a verified row for
     this address, **deny** (route to not-provisioned) **before** any `connect()`. Only once linking
     is known safe does it `connect(request, user)` then `ensure_verified_primary_email(user, email)`
     (which is now guaranteed not to raise), then return (allauth's standard login proceeds).
     **No new user, role preserved, and no dangling SocialAccount on the deny path.**
   - **Eligibility & role:** auto-link applies to a matched account regardless of its role,
     **including a staff/superuser (e.g. the PA who configured SSO with their own email)** — the
     IdP is authoritative for identity in this single-tenant trusted deployment. An **inactive**
     (`is_active = False`) match links but is **not** logged in (allauth's standard inactive-user
     handling applies); SSO never reactivates an account.
   - **Existing-primary precondition:** `ensure_verified_primary_email` does not demote another
     primary. A `User.email`-matched (admin-created) target has **no** `EmailAddress` row, so the
     created row is the sole primary — no conflict. A target that already owns a *different* primary
     address is data drift; the verified-elsewhere clash check above denies the verified case, and a
     target owning a different *unverified* primary is out of scope for 0c‑2 (documented, not
     handled — admin cleanup).
3. **Brand-new identity** → look up a valid pending `Invitation` for the email, then call
   `evaluate_sso_provisioning(...)`:
   - **deny** → `raise ImmediateHttpResponse(redirect(reverse("accounts:sso_not_provisioned")))`
     (`from allauth.core.exceptions import ImmediateHttpResponse` — note: `allauth.core.exceptions`,
     not `allauth.exceptions`, in 65.18). No partial account; the invitation (if any was
     invalid/expired) is untouched.
   - **allow** → stash the chosen `invitation_to_consume` on the `sociallogin` instance as a named
     attribute (e.g. `sociallogin._libli_invitation`); the **auto-signup path has no intermediate
     form/redirect** (guaranteed by `SOCIALACCOUNT_AUTO_SIGNUP = True` — allauth's default — plus
     `SOCIALACCOUNT_EMAIL_VERIFICATION = "none"`, see §4, so mandatory account-level verification
     does **not** interpose a confirmation interstitial for the IdP-asserted email), so
     `pre_social_login` and `save_user` share the same in-memory `SocialLogin`. Return; allauth
     proceeds to create the account. (Robustness fallback is specified in `save_user` below in case
     the attribute is ever absent.) A test asserts a brand-new allowed identity is provisioned with
     **no** interstitial form rendered.

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
needed). The adapter calls the base `save_user` **first** (which persists the user and may create
allauth's own `EmailAddress` row from `sociallogin.email_addresses`), then:

- **Pre-verify the email.** Take the email from the saved `user.email` (allauth populates it from
  the IdP-asserted primary `sociallogin.email_addresses` entry). Call
  `ensure_verified_primary_email(user, user.email)` — its get-or-create keyed on `(user, email)`
  composes with any `EmailAddress` row allauth already created (it forces that same row to
  verified+primary rather than duplicating it).
- **Consume the invitation.** Read the stashed `sociallogin._libli_invitation`. **Fallback:** if it
  is absent (defensive, e.g. an unexpected serialized-`SocialLogin` flow), re-run the §1 invitation
  lookup by `user.email`. Then, **inside `transaction.atomic()`**, re-fetch the row with
  `select_for_update()` and re-check `is_valid()` before setting `accepted_at = timezone.now()` and
  saving — genuinely mirroring `_consume_and_create`'s locked re-check (not just the staleness test),
  so concurrent accepts can't double-consume a single-use invite. (`timezone` =
  `django.utils.timezone`.)

The **Student group** is assigned by the existing `user_signed_up` receiver, which allauth fires
for social **signups** — no duplicate logic here. **Load-bearing invariant:** `connect()`-based
**linking** of an existing user is *not* a signup and does **not** emit `user_signed_up`, so a
linked PA/staff account is never silently given a Student group on top of its role. A test asserts a
non-Student account's group membership is unchanged after an SSO link.

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
- `SOCIALACCOUNT_AUTO_SIGNUP = True` (allauth's default; stated explicitly so a brand-new allowed
  identity is provisioned **form-lessly**) and `SOCIALACCOUNT_EMAIL_VERIFICATION = "none"` — the
  trusted IdP's email is authoritative and the adapter pre-verifies it, so the account-level
  `ACCOUNT_EMAIL_VERIFICATION = "mandatory"` (unchanged, still governs local signups) does **not**
  interpose an email-confirmation step on the SSO path.
- Place the new `SOCIALACCOUNT_*` settings as a grouped block **immediately after** the existing
  `ACCOUNT_*` settings block in `base.py`, and replace the existing section comment
  `# django-allauth (local accounts only; social/SSO lands in Plan 0c).` with exactly:
  `# django-allauth (local accounts + OIDC SSO; social/JIT provisioning added in Plan 0c-2).`
- No SSO provider secrets in settings — credentials live in a `SocialApp` row (Django admin),
  per foundations §4. `SITE_ID = 1` already set; the `SocialApp` is tied to the Site.

`config/urls.py`: `path("accounts/", include("allauth.socialaccount.urls"))` (beside the existing
`allauth.account.urls` include). The not-provisioned route is added under `accounts.urls`
(site-root app namespace) as `sso_not_provisioned`.

## 5. UI (minimal, unstyled — styling deferred to 0d)

- **Login page** (`templates/account/login.html`): there is **no** project-level login template
  today — the page rendered now is allauth's *bundled* `account/login.html`. So 0c‑2 **creates a new
  override**: copy allauth 65.18's `account/login.html` as the base and inject the SSO block (rather
  than patching non-existent project markup). The block does `{% load socialaccount %}`, then
  `{% get_providers as socialaccount_providers %}` and `{% if socialaccount_providers %}` … loop
  rendering `{% provider_login_url provider %}` per provider. Absent any `SocialApp` the list is
  empty and the block renders nothing (the page is visually unchanged for local-only installs).
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
