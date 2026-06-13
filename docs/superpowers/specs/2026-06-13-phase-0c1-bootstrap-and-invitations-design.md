# Phase 0c‑1 — Platform Bootstrap + Invitations: Design Spec

*Spec date: 2026-06-13. A sub-phase of Phase 0 of the [libli roadmap](../../roadmap.md).
Refines the [Phase 0 foundations spec](2026-06-13-phase-0-foundations-design.md) §8
(initial-admin bootstrap) and §4 (invite-token signup path), building on Plan 0a
(scaffold, custom `accounts.User`, `Institution` singleton, seeded role Groups) and
Plan 0b (django-allauth local auth, mandatory email verification, signup-policy gating).*

## Goal

Complete the **local** account-origin paths that Phase 0 still needs:

1. A one-command **platform bootstrap** (`init_platform`) that mints the first **Platform
   Admin** and ensures the roles/Groups + `Institution` singleton exist — the CLI path that
   gets a usable admin into a fresh database.
2. The **invite-token** path that powers `signup_policy == "invite"` (the counterpart to
   0b's hardened `open` self-signup): a bespoke `Invitation` model, admin-issued and
   auto-emailed, with a dedicated accept-invite view that works even when allauth's
   self-signup form is closed.

After 0c‑1, a fresh install boots to a logged-in Platform Admin, and under the `invite`
policy new users join via emailed single-use invite links, landing as Students.

## Scope boundary (decided during brainstorming, 2026-06-13)

**In scope (0c‑1):** `init_platform` (env-first / prompt-fallback credentials, idempotent,
mints a superuser PA in the Platform Admin group with a pre-verified email); a bespoke
`Invitation` model (email-bound, single-use, expiring); auto-email on invite creation; a
dedicated `/invite/accept/<token>/` view that creates the account, pre-verifies the invited
email, assigns the Student group, and logs the user in.

**Out of scope — deferred:**
- **0c‑2:** SSO/social providers (`allauth.socialaccount`, `SocialApp`), the JIT-provisioning
  adapter, and SSO's consumption of this `Invitation` model for "pre-invited" emails.
- **Phase 1:** emailless front-door login (a custom allauth login stage). Decided 2026-06-13
  that no account logging in during Phase 0 is emailless (PA, SSO, open-signup, and invited
  users all carry an email), so this is wired only when real emailless young-student accounts
  exist. **Open Phase 1 question:** do we require an email for every account, or support truly
  emailless young-student accounts? (Decide alongside rostering / CSV import.)
- **0d / Phase 5:** branded/styled accept + invalid-invite pages (0c‑1 uses 0b's minimal
  unstyled `base.html`); a friendly admin "send/resend invite" UI; **role-bearing invitations**
  (every invited user lands as Student in 0c‑1; a PA promotes staff via Django admin afterward).

## Execution environment

Windows (win32), PowerShell primary, but every `bash` block runs through the **Bash tool /
Git Bash** (POSIX sh). Always invoke Python through **`uv run python ...`** (system `python`
is 3.11; uv manages 3.13). PostgreSQL provisioned from Plan 0a: role `libli` / password
`libli` / database `libli` on `localhost:5432` (CREATEDB; pytest-django builds `test_libli`).
Run `uv run ruff format .` before every commit. Tests reuse 0b's `tests.factories.TEST_PASSWORD`
fixture password and the locmem email backend (`config/settings/test.py`), which populates
`django.core.mail.outbox`.

---

## Components

The new account-origin code (the `init_platform` command, the `Invitation` model + admin +
accept view) lives in the existing **`accounts`** app; no new Django app is introduced. The
**role Groups and the `Institution` singleton remain owned by the `institution` app** (Plan
0a) — `init_platform` does **not** re-home them; it cross-app-invokes `institution`'s
`setup_roles` command and `Institution.load()`. URLs get a dedicated `accounts/urls.py`
(with `app_name = "accounts"`) included from `config/urls.py`.

### 1. `init_platform` management command

- **Location:** `accounts/management/commands/init_platform.py`.
- **Invocation:** `uv run python manage.py init_platform`.
- **Credentials (env-first, prompt fallback):**
  - Reads `INIT_ADMIN_USERNAME`, `INIT_ADMIN_EMAIL`, `INIT_ADMIN_PASSWORD` from the
    environment (django-environ `.env` is already loaded by `config/settings/base.py`).
  - If any are missing **and** stdin is a TTY (interactive), prompt for the missing values
    (password read without echo, like `createsuperuser`).
  - If any are missing **and** the session is non-interactive, raise `CommandError` with a
    clear message naming the missing variables, and exit non-zero.
  - The supplied password is run through `AUTH_PASSWORD_VALIDATORS`, passing a constructed
    (unsaved) `User` carrying the username/email so `UserAttributeSimilarityValidator` can reject
    a password too similar to them; a failure is reported as a `CommandError` (no half-created
    admin).
- **Actions (idempotent, in order):**
  1. **Roles:** ensure the role Groups exist by delegating to Plan 0a's **`institution`-app**
     command (`call_command("setup_roles")`, which wraps `institution.roles.seed_roles`).
     Never re-implements role seeding.
  2. **Institution:** ensure the singleton exists via `Institution.load()`. Note the model's
     `signup_policy` **defaults to `"invite"`**, so a freshly-bootstrapped platform is
     invite-gated (allauth's open-signup form stays closed) and the accept-invite flow is the
     only self-serve path until a PA switches the policy to `open`. `init_platform` does not
     change the policy.
  3. **Platform Admin user:** create the PA via
     `User.objects.create_superuser(username, email, password)` (which **hashes** the password
     and sets `is_staff`/`is_superuser` — never assign `password` directly) and add it to the
     **Platform Admin** group, looked up by name from `institution.roles.PLATFORM_ADMIN`
     (`from institution.roles import PLATFORM_ADMIN`), never a hardcoded string — consistent with
     0a/0b. The group is guaranteed present because action 1 ran `setup_roles` first, so a direct
     `Group.objects.get(name=PLATFORM_ADMIN)` is safe. **If a user with that username already
     exists,** do not re-create it; instead **idempotently reconcile** it to the bootstrap
     contract — ensure `is_staff`/`is_superuser` are set and that it belongs to the Platform Admin
     group (action 4 then ensures its verified email) — and report what was reconciled.
     Reconciling rather than blindly skipping keeps the DoD ("a superuser PA in the Platform Admin
     group") true on every run. Reconcile is intentionally **non-destructive**: it does **not**
     overwrite the existing user's password or email (those are set only at creation, so a
     later password rotation survives re-runs). `init_platform` is a privileged bootstrap action,
     so the supplied `INIT_ADMIN_USERNAME` is **taken to denote the intended platform admin** —
     promoting a pre-existing account of that exact username to PA is the deliberate idempotent
     behavior, not an error.
  4. **Pre-verify email:** ensure a **verified + primary** allauth `EmailAddress` row exists
     for the PA's email, so the PA can authenticate through the allauth front door (not only
     the ModelBackend admin path). This uses a shared **production** helper
     `accounts.emails.ensure_verified_primary_email(user, email)` (get-or-create the row, then
     force `verified=True` + `primary=True`) — the same helper the accept view (§4) calls, and
     which 0b's `tests.factories.make_verified_user` is refactored to delegate to. (The
     reconciliation logic must NOT be imported from test code into production code.) The helper
     **get-or-creates keyed on `(user, email)`**; if a *verified* `EmailAddress` for the same
     address is already bound to a **different** user, it raises rather than silently re-pointing
     another account's primary email — at bootstrap the command surfaces this as a `CommandError`
     (e.g. re-running with a changed `INIT_ADMIN_EMAIL` that collides with another user).
- **Idempotency contract:** a second run with the same inputs makes no changes beyond
  reconciliation and exits 0, printing what already existed vs. what it reconciled (roles
  present, institution present, admin present/promoted). The only genuinely create-once step is
  the user row itself (guarded by the username check); the superuser flags, Platform Admin group
  membership, and the verified primary email are re-asserted idempotently on every run.
- **Output:** concise, human-readable status lines (created vs already-present for each step).

### 2. `Invitation` model (`accounts.Invitation`)

| Field | Type | Notes |
|---|---|---|
| `email` | `EmailField` | The invited address; the account's email on accept. |
| `token` | `CharField`, unique, indexed | High-entropy, URL-safe (`secrets.token_urlsafe(32)` — 32 bytes ⇒ a 43-char token); generated on create. Stored raw (single-use, time-boxed, like a password-reset link). |
| `invited_by` | `FK → settings.AUTH_USER_MODEL`, `null=True`, `on_delete=SET_NULL` | The issuing PA; nullable so deleting the issuer keeps the audit trail. |
| `created_at` | `DateTimeField`, `auto_now_add=True` | |
| `expires_at` | `DateTimeField` | Set in `save()` to `timezone.now() + INVITE_TTL` (14 days) **when unset** — computed from `now()`, NOT from `created_at` (which `auto_now_add` only populates during the same INSERT, so it is `None`/stale inside `save()` before `super().save()`). |
| `accepted_at` | `DateTimeField`, `null=True` | Set on first successful accept; `null` ⇒ unused. |

- `INVITE_TTL` is a module-level constant **in `accounts/models.py`**
  (`datetime.timedelta(days=14)`); not yet institution-configurable (YAGNI; a settings hook is a
  later nicety). The two invite constants live in **different modules deliberately** — `INVITE_TTL`
  beside the model that consumes it in `save()`, `INVITE_SUBJECT` (§3) beside the send helper — so
  don't "tidy" them into one place (and to avoid a models↔invitations import cycle).
- **`is_valid()`** ⇒ `accepted_at is None and expires_at > now()`. (Single-use + unexpired.)
- Multiple invitations may target the same email; each token is independent and single-use.
  Once one is accepted (the account exists), any sibling tokens to that email remain `pending` and
  **harmless** — presenting one hits the "already has an account" branch (no account created), and
  0c‑1 does not auto-invalidate siblings (deferred cleanup; a PA can delete stale rows in admin).
- The `token` is generated with `secrets.token_urlsafe(32)` on first save. A `unique`-constraint
  collision is treated as negligible (43-char random token); no retry loop is added — an
  `IntegrityError` would simply propagate (YAGNI).
- `__str__` returns `f"{email} ({status})"` for legible admin lists, where `status` is one of
  `"accepted"`, `"expired"`, or `"pending"`, evaluated in that precedence (accepted wins over
  expired wins over pending).

### 3. Invitation issuance + email (`accounts/admin.py`, `accounts/invitations.py`)

- **`InvitationAdmin`** registers the model with a sensible list display (email, invited_by,
  created/expires, accepted state) and shows the **accept URL** read-only so a PA can copy it; the admin builds this URL with the same
  request-independent `Site`-based builder as the email, so the displayed and emailed URLs are
  identical.
  `token`, `created_at`, `accepted_at` are read-only; `email` is the main entry field.
- **Auto-email on creation:** a `post_save` receiver (registered in `accounts/apps.ready()`,
  alongside 0b's `user_signed_up` receiver) fires only on `created=True` and schedules the
  send-invite helper via **`transaction.on_commit(...)`**, so the email is sent only after the
  invitation row actually commits (no send on a rolled-back admin save, and no ordering race in
  tests). Editing an existing invitation does **not** resend. **Send failure:** the helper lets
  a transient backend error propagate to be logged by Django, but because it runs post-commit
  the `Invitation` row is already persisted and is **not** lost — a PA can resend later (resend
  UI is deferred). In tests the locmem backend never fails.
- **`accounts/invitations.py`** holds the pure helpers and the `INVITE_SUBJECT` constant: token
  generation, absolute accept-URL building, and `send_invitation_email(invitation)` which renders
  `templates/accounts/invite_email.txt` and sends a **plaintext-only** email (no HTML alternative
  in 0c‑1) via Django's configured backend, with the fixed
  `INVITE_SUBJECT = "You're invited to libli"` and the project default `From` address. **Absolute
  URL building is deterministic and request-independent:** the path is
  `reverse("accounts:accept_invite", args=[token])` and the host is **always**
  `Site.objects.get_current().domain` — never derived from a request `Host` header (a security
  link must not be host-spoofable, and the same builder serves the request-less
  `transaction.on_commit` send, the admin display, and the email identically). The scheme reuses
  allauth's existing **`ACCOUNT_DEFAULT_HTTP_PROTOCOL`** setting (`https` by default, `http` in
  dev) so invite links match allauth's own confirmation/reset emails. Kept separate from the
  signal so it is unit-testable and reusable by 0c‑2.

### 4. Accept-invite view (`accounts/views.py`, `accounts/urls.py`)

- **Route:** `path("invite/accept/<str:token>/", views.accept_invite, name="accept_invite")`
  in `accounts/urls.py`, which sets **`app_name = "accounts"`** (so `reverse("accounts:accept_invite")`
  resolves), included from `config/urls.py` as `path("", include("accounts.urls"))`. The invite
  route therefore lives at **site root** — `/invite/accept/<token>/` — **not** under allauth's
  `/accounts/` URL prefix, and the `accounts` app namespace is distinct from allauth's own
  `account` namespace. Independent of allauth's `/accounts/signup/`.
- **Behavior** (the view is wrapped with `@require_http_methods(["GET", "POST"])`, so any other
  method — including HEAD — returns 405; that is acceptable for a token-gated invite link and is
  not treated as a regression):
  - **Invalid / expired / already-accepted token** (or no matching token) → render
    `templates/accounts/invite_invalid.html` (HTTP 200, minimal unstyled page; 0d brands it).
    Do not reveal which failure mode for unknown tokens beyond a generic "invalid or expired."
  - **Email already has an account** → render the invalid page with a "this email already has
    an account — please log in" message and a link to `/accounts/login/`. No account created,
    invitation left unaccepted. "Has an account" means a **case-insensitive** match on either
    `EmailAddress.objects.filter(email__iexact=invitation.email)` **or**
    `User.objects.filter(email__iexact=invitation.email)` (allauth normalizes email case, so the
    `iexact` guards both stores). This check is performed **inside** the same atomic block as
    creation (below) to close the check-then-act race.
  - **Valid token, GET** → render `templates/accounts/accept_invite.html`: a minimal form
    showing the invited **email read-only** and inputs for **username + a single password
    field** (the form runs `AUTH_PASSWORD_VALIDATORS`). The single-password-field contract is
    fixed (no confirm field) so the form and its tests have a definite shape.
  - **Valid token, POST (valid form):** steps 1–4 run inside a single
    **`transaction.atomic()`** block that opens by re-locking and re-validating the invitation
    with `Invitation.objects.select_for_update().get(token=token)` + `is_valid()` (and the
    "already has an account" check above). If `is_valid()` fails for **any** reason between GET
    and POST — token now consumed, **now expired**, or the email now registered — the block
    aborts → invalid page, nothing created. Otherwise:
    1. Create the user with `User.objects.create_user(username, email, password)`, where
       **`email` is sourced from `invitation.email` server-side** and never from the POST body —
       the GET form shows it read-only, but the create + verify steps trust only the stored
       invitation address, so a tampered POST cannot bind or pre-verify a different email.
       `username` and `password` come from the validated form.
    2. Ensure a **verified + primary** allauth `EmailAddress` for the invited email via the
       shared `accounts.emails.ensure_verified_primary_email(user, email)` helper (the emailed
       link proves control of the address → no separate confirmation needed).
    3. Add the user to the **Student** group via
       `Group.objects.get_or_create(name=STUDENT)[0]` (`from institution.roles import STUDENT`) —
       defensively, exactly as 0b's `user_signed_up` signal already does, since this path does
       **not** fire that allauth signal. This does **not** re-implement role seeding: the Student
       role carries **no** Phase-0 model permissions (only Platform Admin does — see
       `institution.roles`), so a `get_or_create`d Student group is identical to the seeded one.
       In normal operation `setup_roles` has already run (bootstrap/deploy); the `get_or_create`
       is purely a safety net.
    4. Set `invitation.accepted_at = timezone.now()` and save (consumes the token).
    5. **After the `atomic()` block returns** (user + consumed token already committed), log the
       user in — preferring allauth's `perform_login`, falling back to
       `django.contrib.auth.login` with the explicit `AuthenticationBackend` — and redirect to
       **`settings.LOGIN_REDIRECT_URL`** (do not hardcode `redirect("home")`, which would ignore
       the setting). The `home` URL name + `/home/` route that `LOGIN_REDIRECT_URL` points at are
       a **Plan 0b prerequisite** (already present); this spec depends on them, it does not define
       them. Login is deliberately **outside** the atomic block so the `select_for_update` lock is
       not held across the session write; were login to fail here, the account still exists and is
       valid (the user can log in normally) — no rollback.
  - **Valid token, POST (invalid form)** → re-render the accept form with errors (HTTP 200),
    token unconsumed. The accept form **reuses allauth's signup username field + validators and
    uniqueness semantics** (rather than rolling its own) so an invited account is identical to an
    open-signup account — in particular the username **case-sensitivity matches 0b's allauth
    policy** (allauth's username-uniqueness handling, not a plain case-sensitive `username=`
    lookup), avoiding case-divergent duplicates between the two self-serve paths. A taken or
    invalid username surfaces as a normal field error (not a 500); as a backstop, an
    `IntegrityError` from a racing duplicate username inside the atomic block is caught and mapped
    to a username field error, with the token left unconsumed. A weak password is likewise a
    normal field error via `AUTH_PASSWORD_VALIDATORS`.
- **No honeypot / rate-limit** on this view: possession of a valid single-use token is the
  bot gate. (Open self-signup keeps its 0b honeypot.)
- **Policy independence:** a valid token always works regardless of `Institution.signup_policy`.
  Under `invite` it is the only self-serve path (allauth's open-signup form stays closed via
  0b's adapter); under `open` it coexists with open self-signup.

---

## Data flow (representative)

- **Bootstrap:** `init_platform` → ensure roles (`setup_roles`) → ensure `Institution` →
  create superuser PA (if absent) in Platform Admin group → ensure verified+primary
  `EmailAddress` → PA can now log in via admin and the allauth front door.
- **Invite issue:** PA creates an `Invitation` in Django admin → `post_save` → render +
  send invite email (accept URL) → email lands in the console (dev) / `outbox` (tests).
- **Invite accept:** invitee opens `/invite/accept/<token>/` → token validated → choose
  username + password → user created, email pre-verified, Student group, token consumed,
  logged in → `/home/`.

## Error handling

- `init_platform`: missing non-interactive credentials → `CommandError`, non-zero exit, no
  partial admin. Password-validator failure → `CommandError`. Existing username → skip with a
  notice (idempotent). Re-run → no-op, exit 0.
- Accept view: invalid/expired/used token and already-registered email → generic, non-leaky
  invalid-invite page; **no** account created and the token is not consumed by a failed attempt.
  Concurrency is handled by the `select_for_update` re-check inside the atomic block (§4).
- Invite email send failure: because the send is scheduled via `transaction.on_commit`, a
  transient backend error after commit does not roll back or lose the persisted `Invitation`;
  the error is logged and the invite can be resent later.
- Singleton `Institution` is guaranteed present after bootstrap; `Institution.load()` creates it
  on demand if missing.

## Testing

pytest + pytest-django against **real PostgreSQL**; no DB mocking; assert on
`django.core.mail.outbox`; reuse 0b's `TEST_PASSWORD`.

- **`tests/test_init_platform.py`:**
  - Env-driven run creates the superuser PA (`is_staff`/`is_superuser`), in the Platform Admin
    group, with a **verified + primary** `EmailAddress`; the PA can authenticate via the allauth
    login endpoint.
  - Roles + `Institution` singleton exist afterward (delegation to `setup_roles` works).
  - **Idempotency:** a second run creates nothing new and exits 0.
  - Non-interactive run with incomplete env raises `CommandError` (non-zero), no user created.
  - (Interactive prompting is exercised by injecting env so the TTY path is not required in CI.)
- **`tests/test_invitations.py`:**
  - Creating an `Invitation` (admin/ORM) sends exactly one email to the invited address whose
    body contains the accept link. Tests assert on the **path + token**
    (`reverse("accounts:accept_invite", ...)`), **not** the host — the `django.contrib.sites`
    `Site` resolves to `example.com` in dev/tests (per 0b), and setting the real `Site.domain` is
    a deploy prerequisite, not something 0c‑1 tests pin.
  - `is_valid()` true for fresh, false for expired and for accepted.
  - Accept GET on a valid token renders the form (email shown); POST creates the user, sets a
    verified+primary `EmailAddress`, adds the **Student** group, consumes the token
    (`accepted_at` set), logs in, and redirects to `/home/`.
  - Accept on an **expired**, **already-accepted**, or **unknown** token → invalid page, no
    account created, token not consumed.
  - Accept for an **email that already has an account** → invalid page ("please log in"), no
    duplicate account.
  - A consumed token cannot be reused (second accept fails).

## File structure

```
accounts/
├── management/commands/init_platform.py   # NEW: bootstrap PA + roles + institution
├── models.py                              # + Invitation
├── admin.py                               # + InvitationAdmin (accept-URL read-only)
├── apps.py                                # ready(): also connect Invitation post_save
├── signals.py                             # + send-invite-on-create receiver (beside 0b's)
├── invitations.py                         # NEW: token gen, accept-URL, send_invitation_email
├── emails.py                              # NEW: ensure_verified_primary_email (shared by command + view + factory)
├── views.py                               # NEW: accept_invite view
├── urls.py                                # NEW: namespaced; /invite/accept/<token>/
├── migrations/                            # NEW: Invitation model
config/
└── urls.py                                # + include("accounts.urls")
templates/accounts/
├── invite_email.txt                       # NEW: invite email body (accept link)
├── accept_invite.html                     # NEW: minimal accept form (extends base.html)
└── invite_invalid.html                    # NEW: invalid/expired/used/already-registered
tests/
├── factories.py                           # MODIFIED: make_verified_user delegates to accounts.emails helper
├── test_init_platform.py                  # NEW
└── test_invitations.py                    # NEW
```

## Definition of Done (Plan 0c‑1)

- `uv run python manage.py init_platform` on a fresh DB (env-provided creds) creates a
  superuser Platform Admin in the Platform Admin group with a verified+primary email; the PA
  can log in via both Django admin and the allauth front door. Re-running is a clean no-op.
- Non-interactive `init_platform` with incomplete credentials fails clearly (non-zero, no
  partial admin).
- Creating an `Invitation` emails the invitee an accept link; opening a **valid** link lets
  them set username + password and lands them logged-in as a **Student** with a pre-verified
  email; the token is single-use and expires after 14 days.
- Invalid/expired/used tokens and already-registered emails get a generic invalid-invite page
  with no account created and no token consumed.
- Invites work under `signup_policy == "invite"` (where allauth's open-signup form stays
  closed) and coexist with open self-signup under `open`.
- `uv run python -m pytest` green (all existing 0a + 0b tests remain green, plus the new
  bootstrap/invitation tests); `ruff check .` and `ruff format --check .` pass;
  `makemigrations --check --dry-run` clean.

## Risks

- **`perform_login` vs manual `login`** for the accept view: allauth's login pipeline may run
  the email-verification stage. Because the invited email is created **verified** before login,
  the stage passes; the plan verifies the exact call against allauth 65.x source (as 0b did) and
  prefers allauth's `perform_login` for consistency, falling back to `django.contrib.auth.login`
  with the explicit `AuthenticationBackend` if cleaner.
- **Token in URL / storage:** the raw token is stored and emailed (like a password-reset link);
  acceptable for single-use, time-boxed invitations. Hashing at rest is a possible later
  hardening, noted but not required for 0c‑1.
- **Email link host:** allauth/`django.contrib.sites` resolves to `example.com` in dev/tests
  (per 0b); the real host is a deploy-time concern, unchanged here.
