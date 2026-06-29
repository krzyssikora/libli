# Phase 5b — User & Role Management

*Brainstormed 2026-06-29. A focused slice carved out of the broad "Phase 5 —
Platform admin polish" roadmap bundle, scoped to the **people** strand (user
directory, invitations, role assignment, activation).*

## Context

Phase 5's goal is "a non-technical Platform Admin can fully run the institution
without Django admin." Two of its strands are already shipped — **cohort
management** (Phase 3a, `/manage/cohorts/`) and **subjects management** (Phase
5a, `/manage/subjects/`). The remaining strands decompose into:

- **5b — User & Role Management** *(this slice)*
- 5c — Branding & platform-settings completion (`BrandColor` palette UI + the
  missing upload/storage whitelist and email-domain allowlist fields)
- 5d — SSO configuration UI (bespoke allauth `SocialApp` create/edit)
- 5e — First-run setup wizard + persistent dashboard checklist (capstone)

Today, **all** user and role administration is Django-admin-only:

- New users arrive through the existing `Invitation` flow (email-bound,
  single-use, expiring tokens — `accounts/models.py`, `accounts/invitations.py`,
  `accept_invite` in `accounts/views.py`), but invitations can only be **created**
  via Django admin (`accounts/admin.py`). The only invitation *view* is the
  public `accept_invite`.
- Acceptance **hardcodes the Student role** — there is no way to invite a Teacher
  or Course Admin.
- The 4 roles (Student / Teacher / Course Admin / Platform Admin) are Django
  Groups seeded by `institution/roles.py`; there is **no UI** to assign or change
  a user's role.
- There is no UI to list, search, or **deactivate** users.

This slice closes those gaps with one bespoke `/manage/people/` surface.

## Goals

1. A Platform Admin can **invite** a new user with a chosen role, from a bespoke
   UI — no Django admin.
2. A Platform Admin can **see and search** all users and filter by role / active
   state.
3. A Platform Admin can **change a user's role** (exactly one role per user).
4. A Platform Admin can **deactivate / reactivate** a user (no hard delete).
5. A Platform Admin can **manage pending invitations** (list, revoke, resend).

## Non-goals (explicitly deferred)

- **Hard delete / anonymize of users** — deactivation (`is_active=False`) only.
  Hard delete risks orphaning submissions/analytics and is out of scope; GDPR
  anonymize is a later follow-up.
- **PA-set passwords / direct user creation** — users only arrive via the invite
  (and SSO-JIT) flow. The admin UI never handles passwords.
- **Multiple roles per user** — each user holds exactly one role.
- **Course-Admin access to this surface** — Platform Admin only. CAs continue to
  manage their own groups/rosters via the Phase-3a grouping UI.
- **Bulk operations** (multi-select invite/deactivate) — single-record actions
  only in this slice.
- Branding (5c), SSO config (5d), and the first-run wizard (5e).

## Design decisions (from the brainstorm)

| Decision | Choice | Rationale |
|---|---|---|
| Add-user path | Invite-only, reusing `Invitation` | Cleanest security posture; no PA-set passwords; reuses the built flow. PA UI adds the *create/list/revoke/resend* surface that today only Django admin provides. |
| Invite carries a role | Add `role` to `Invitation`; accept assigns it | A PA can invite a Teacher/CA/PA directly in one step; no follow-up promotion needed. |
| Role cardinality | Exactly one role per user | Single-select UI; staff/non-staff derives from the role; keeps the cohort "students = non-staff" rule clean. |
| Remove semantics | Deactivate only (`is_active=False`) | Preserves all user data (progress, submissions, notes, sent invitations); reversible; no cascade surprises. |
| Page structure | One `/manage/people/` page, **Users** / **Invitations** tabs | Single People entry point chosen in the brainstorm. |
| Editable user fields (PA) | Edit **form**: `role`, `display_name`, `email`. Activation (`is_active`) is **not** a form field — toggled only via the dedicated Deactivate/Reactivate POST endpoints. | Role + name/email are correctable on the form; activation is a guarded button action so the lockout guard fires on its own endpoint. `language`/`theme` stay user-owned preferences. |
| Lockout guard | Cannot deactivate self; cannot deactivate/demote the last active Platform Admin | Prevents the institution from locking itself out. |
| Deactivation side-effects | None unwound | Group/teacher/cohort assignments are left intact; the user is simply blocked from login; reactivation restores them as-is. |

## Data model

### `Invitation` (`accounts/models.py`)

Add one field; one migration.

- `role = models.CharField(max_length=32, choices=ROLE_CHOICES, default=STUDENT)`
  — constrained to the 4 role names defined in `institution/roles.py`. Default
  **Student**. (`max_length=32` comfortably covers the longest role name.)

The choices/constant source is `institution/roles.py` (single source of truth —
do **not** redeclare role strings in `accounts`). `roles.py` today defines
`ROLE_NAMES` but not the helpers this slice needs; add all three there:

- **`ROLE_CHOICES`** — `(group_name, label)` pairs derived from the role-name
  constants. The stored value is the **exact Group name** (e.g. the literal
  `"Course Admin"`, space included), so it resolves against
  `Group.objects.get(name=...)` with no extra lookup table. The choice **labels are
  the same translatable display labels** used everywhere else (below) — not a
  parallel label set.
- **`ROLE_LABELS`** — the `{group_name: label}` display mapping for the role
  column / filter / selects. Wrap each label in **`gettext_lazy`**: a module-level
  dict in `roles.py` is evaluated at app import, and eager `gettext` would freeze
  the labels to the import-time language (the exact PR #46 burn). `ROLE_CHOICES`
  draws its labels from this mapping.
- **`role_is_staff(role)`** — returns `False` only for `STUDENT`, `True` for the
  other three; used by `set_user_role`.

**Migration backfill:** existing *pending* `Invitation` rows take the
`default=STUDENT`. This matches today's accept flow (which already hardcodes
Student), so any pre-existing pending invite still lands the invitee as Student
exactly as it would have pre-migration — a conscious, no-surprise consequence.

No change to the `User` model: a user's role **is** their Group membership;
"active" is the existing `is_active`; staff/non-staff is the existing `is_staff`.

## Services

A small role service keeps the "exactly one role" invariant and staff-sync in one
place, reused by the role-assignment UI **and** the invite-accept flow.

### `set_user_role(user, role)` (`accounts/services.py` — new)

Runs inside `transaction.atomic()` so the staff update, group swap, and
signal-driven cohort re-sync commit or roll back together. The operation **order
matters** and is pinned:

1. **Set `is_staff` on the in-memory instance first, and `save()` it** — *before*
   touching groups. Compute `is_staff = role_is_staff(role) or user.is_superuser`:
   Student → `False`, Teacher / Course Admin / Platform Admin → `True`, **and
   always `True` for a superuser** (Django admin login requires `is_staff`, so we
   never strip a superuser's admin access — that is the recovery path). `is_superuser`
   itself is never modified here.
2. **Then** swap the role Group via `user.groups.set([role_group])` (clear + add)
   so the user belongs to **exactly one** of the 4 role Groups.

Order rationale (do **not** reorder): the Phase-3a cohort receiver
(`grouping/signals.py:sync_cohort_on_role_change`) fires *during* `groups.set` and
reads `user.is_staff` to decide cohort membership. If groups were swapped before
`is_staff` were updated, a Teacher→Student demote would still look like staff at
signal time and the user would **not** be rejoined to the Default cohort (the
later `is_staff=False` save is a `created=False` post_save that does no cohort
sync). Updating `is_staff` first makes the signal see the new state, so demotion
**to** Student re-syncs cohort membership and promotion **off** Student removes the
user from cohorts. This service must not duplicate that cohort logic — it triggers
it.

### Lockout guard helpers

- `is_last_active_platform_admin(user)` — true when `user` is the only active
  member of the Platform Admin **group**. Counting is by group membership;
  superusers outside the PA group are an intentional separate recovery path and
  are **not** counted here.
- Enforced on the actions that can remove the last PA's powers — **deactivate and
  demote** — and on self-deactivation. (Reactivate only ever *raises* the active-PA
  count, so the guard never applies there; do not add a check to it.) Mechanism per
  path:
  - **Deactivate (POST endpoint)** — runs in its own `transaction.atomic()`; reads
    active PA-group membership under `select_for_update` and rejects if this is the
    last active PA, returning the error as a message on the People page.
  - **Demote (edit-form save)** — a pre-flight check in the form's `clean()` gives
    fast UX feedback, but the **authoritative** check is an in-transaction
    `select_for_update` re-read inside the edit view's single `transaction.atomic()`
    (the same one wrapping the role + email writes). If it fails it raises a caught
    exception that rolls the transaction back and re-renders the form with a
    non-field error — so the `clean()`-runs-outside-a-transaction limitation can
    never let the count slip past.
  - This closes the TOCTOU window where two concurrent requests each demoting/
    deactivating a different one of the last two PAs could both pass a naive
    read-then-act check and leave zero active PAs.
- **Self-role-change is blocked outright.** A PA cannot change **their own** role
  (not merely the last-PA case) — mirroring the self-deactivation block — so a PA
  can never demote themselves out of the People surface mid-edit. Re-assigning a
  PA's role is done by another PA.

## Accept-flow change

Two call sites set the role today; both must route through `set_user_role`:

- **Invite accept (local).** The Student hardcode lives in
  `accounts/views.py._consume_and_create` (`Group.objects.get_or_create(name=
  STUDENT); user.groups.add(group)`), **not** in `provisioning.py` (which holds
  only read-only resolvers like `resolve_user_for_email` /
  `evaluate_sso_provisioning` and assigns no role). Replace that hardcode with
  `set_user_role(user, locked.role)` — read the role from the
  `locked = Invitation.objects.select_for_update().get(...)` row that
  `_consume_and_create` already re-fetches (authoritative, like its `locked.email`),
  not the possibly-stale in-memory `invitation`.
- **SSO-JIT.** The SSO path (`SocialAccountAdapter` in `accounts/adapters.py`, via
  `_consume_invitation`) today assigns **no** role group at all — it only stamps
  `accepted_at`. This slice makes it call `set_user_role`: when a pending invite
  is consumed, use `invitation.role`; when an SSO user signs up under the **open**
  policy with **no** pending invitation, default to **Student**. Pin this default
  explicitly so the invitation-less open-SSO role source is defined (it is
  undefined today).

## Views, URLs & access control

All views live in the **`accounts`** app (new `accounts/views.py` management
views + routes under `/manage/people/`), gated exactly like the cohort/subject
precedent:

```
@login_required
@permission_required("accounts.<perm>", raise_exception=True)
```

The relevant Django model permissions (`accounts.view_user`,
`accounts.add_user`, `accounts.change_user`) are **already** granted to the
**Platform Admin** group — `PLATFORM_ADMIN_PERMS` in `institution/roles.py`
already lists `accounts.add_user/change_user/view_user/delete_user`, applied via
`setup_roles` after migrate. So **no new grant work is needed**; the new views
simply consume the existing permissions. (Grants stay out of migration
`RunPython` per the Phase-3a lesson that `Permission.DoesNotExist` is raised if
perms are seeded inside a migration.)

| Route | View | Perm |
|---|---|---|
| `manage/people/` | People page, **Users** tab (default) | `accounts.view_user` |
| `manage/people/invitations/` | People page, **Invitations** tab | `accounts.view_user` |
| `manage/people/users/<pk>/edit/` | Edit user (role, active, name, email) | `accounts.change_user` |
| `manage/people/users/<pk>/deactivate/` (POST) | Deactivate | `accounts.change_user` |
| `manage/people/users/<pk>/reactivate/` (POST) | Reactivate | `accounts.change_user` |
| `manage/people/invitations/send/` | Send invitation (email + role) | `accounts.add_user` |
| `manage/people/invitations/<pk>/revoke/` (POST) | Revoke pending | `accounts.change_user` |
| `manage/people/invitations/<pk>/resend/` (POST) | Resend pending (refresh expiry) | `accounts.change_user` |

(Exact tab routing — query param vs sub-path — is an implementation detail; the
two-tab single page is the requirement.)

Invitation operations (send / revoke / resend) intentionally reuse the `User`
permissions (`add_user` / `change_user`) — there is no separate `Invitation`
permission and adding one is out of scope; this proxy is deliberate, not an
oversight.

## The `/manage/people/` page

### Users tab
- **Search** by display name / email; **filter** by role and by active state.
- Table columns: name (display name → email → **username**, matching
  `User.__str__`, so emailless/nameless "class" accounts never render blank) ·
  role · status (Active / Inactive) · last login.
- **Role-less / multi-role users.** Exactly-one-role is the invariant this slice
  *creates*, but existing data violates it: `createsuperuser` and admin-created
  accounts have **no** role group, and nothing prevents a pre-existing 2-group
  user. A role-less user renders **"— / None"** and is reachable via a dedicated
  **"No role"** filter bucket. A multi-role user shows its roles comma-joined and
  appears under **every** role filter it holds (not under "No role"). Assigning a
  role via Edit user normalizes either case to exactly one.
- The role **column, filter options, and single-select labels** are all rendered
  through the central `ROLE_LABELS` mapping (`gettext_lazy`, defined in
  `institution/roles.py` — see Data model), so PL shows localized role names even
  though the stored Group names are English data. The mapping is the single display
  source; the Group name stays the storage key.
- **Query specifics (pinned):** search is **case-insensitive** (`icontains` over
  display name + email + **username**, so emailless accounts are findable); default
  ordering is `display_name` then `email`; the active-state filter **defaults to
  "all"** (both active and inactive shown) so a PA can find a deactivated user
  without first changing a filter; page size **25**.
- Each row links to **Edit user**.
- Paginated.

### Edit user
- **Role** — single-select; saving calls `set_user_role`. The choices include an
  explicit blank **"— No role —"** initial option and the field has **no implicit
  default**: for a role-less user (every `createsuperuser`/admin-created account)
  or a multi-role user the select pre-selects blank, so a PA who edits only the
  email never silently assigns Student. Saving with the blank option still selected
  makes no role change. The field is disabled when editing **your own** account
  (self-role-change is blocked — see Lockout guard).
- **Active** — **not** an edit-form field; toggled only via the dedicated
  Deactivate / Reactivate POST endpoints. The **Deactivate** endpoint is subject to
  the lockout guard; **Reactivate** is not (it only raises the active count). The
  edit form covers role / name / email only.
- **`display_name`** and **`email`** — editable for corrections. Editing `email`
  must **reconcile allauth**: identity resolution (`resolve_user_for_email`)
  prefers the verified allauth `EmailAddress` row over `User.email`, so after
  `user.save()` the edit calls the existing
  `accounts/emails.py:reconcile_primary_email(user)` helper (it demotes other
  addresses and makes `user.email` the sole verified primary) — otherwise the user
  keeps being resolved by the stale address. **All email validation runs in the
  form's `clean()`, before any write** (so a bad email never commits a partial
  change), and the edit view wraps its writes (the `set_user_role` call +
  `user.save()` + reconcile) in a **single `transaction.atomic()`** so role and
  email succeed or roll back together. Two validation checks:
  - **Case-insensitive uniqueness** — reject when another user holds the address
    via `email__iexact` (excluding the edited instance); the DB `unique` constraint
    is case-sensitive and is **not** sufficient (`Foo@x.com` vs existing
    `foo@x.com`).
  - **Verified-elsewhere guard** — a *verified* `EmailAddress` for the new address
    bound to a different user (whose `User.email` may differ, so the uniqueness
    check above can pass) would make `reconcile_primary_email` raise `ValueError`.
    Reuse the **existing** `accounts/provisioning.py:verified_email_belongs_to_other(email, user)`
    helper (already used by `adapters.py`; importable from the edit form with no
    cycle) and call it in `clean()` to surface a field error pre-write — never reach
    the `ValueError`/500.
- `language` / `theme` are **not** shown (user-owned preferences).

### Invitations tab
- **Send invitation** — email + role; the role select offers the 4 `ROLE_CHOICES`
  (default **Student**) with **no** blank option (every invite carries a role).
  Creates the `Invitation` with **`invited_by=request.user`** (preserving the
  "who invited this person" audit trail) and sends the existing invite email via
  `send_invitation_email`.
- **List columns (pinned):** email · role (via the same `ROLE_LABELS` mapping) ·
  status · expiry (`expires_at`) · sent (`created_at`), ordered
  most-recent-first. Status is **Pending** / **Accepted** / **Expired**, read from
  the existing `Invitation.status` property (returns `"pending"` / `"accepted"` /
  `"expired"`); map its three values to localized labels rather than re-deriving
  from `accepted_at` / `expires_at`.
- **Per-status actions:** Pending rows get **Revoke** + **Resend**; Accepted and
  **Expired** rows are **inert** (no actions). Re-inviting after expiry is done via
  **Send** (covered by the "only-expired prior invites → new invite" edge case).
- **Revoke** (pending only) — **deletes the pending `Invitation` row** (it carries
  no user data; a token never accepted is safe to remove). Revoke therefore drops
  the invite from the list entirely — chosen over expire-in-place precisely so a
  revoked invite is not confused with a naturally **Expired** one. No new model
  field is required.
- **Resend** (pending only) — re-sends the email and refreshes expiry. Note
  `Invitation.save` only sets `expires_at` when it is `None`, so resend must assign
  `expires_at = timezone.now() + INVITE_TTL` **explicitly** (the model will not
  auto-refresh an already-set value).

## Validation & edge cases

- **Invite to an existing active account** — rejected at send with a clear message
  (don't create a dead invite).
- **Invite to an existing *inactive* account** — also rejected at send, with a
  "this email belongs to a deactivated user — **reactivate** them instead"
  message. (`accept_invite` rejects any *registered* email regardless of
  `is_active`, so such an invite could never be accepted; catch it at send.)
- **Invite to an email with a still-pending invite** — refresh the existing pending
  invite rather than create a duplicate (mirrors `find_pending` semantics), and
  **update its `role`, `invited_by`, and `expires_at` to the new submission** so the
  most recent Send wins (accept reads `locked.role`, so a stale role must not
  linger).
- **Invite to an email whose only prior invites are *expired*** — `find_pending`
  returns nothing, so a **new** invite is created; the stale Expired rows simply
  remain in the list (acceptable; no auto-cleanup in this slice).
- **Self-deactivation** — blocked. **Self-role-change** — blocked (a PA cannot
  change their own role at all; see Lockout guard).
- **Last active Platform Admin** — cannot be deactivated or demoted.
- **Revoke** — deletes the pending row (see Invitations tab); revoked invites
  disappear from the list rather than showing as Expired.
- **Role change** — within `transaction.atomic()`: updates `is_staff` (preserving
  superuser admin access) **then** swaps Groups via `groups.set([group])` (order
  pinned — see `set_user_role`); does not unwind existing group/teacher/cohort
  assignments beyond the automatic cohort staff-sync; never alters `is_superuser`.

## Cross-cutting

- **i18n** — EN/PL for every new string; clear any `#, fuzzy` flags and verify new
  msgids (per the `uv run` / makemessages note).
- **Styling** — per the design language; light/dark; mobile-responsive; new
  templates carry their per-page CSS link and use only defined utility classes.
  Verify with light+dark screenshots (throwaway Playwright harness, delete after
  review).
- **Tests** — pytest + factory_boy against real PostgreSQL: the role service
  (swap + staff-sync + lockout guard), including a **Teacher→Student demotion test
  asserting the user is rejoined to the Default cohort** (guards the `is_staff`-
  before-`groups.set` ordering) and a **superuser-keeps-`is_staff`** test;
  invite-with-role accept; the email-edit reconcile (case-insensitive uniqueness +
  verified-elsewhere `ValueError` surfaced as a field error); the role-less-user
  edit (blank initial, no silent Student assignment); deactivate / reactivate; and
  the validation edge cases. One **e2e** test driving the real gesture path: invite
  (with a non-Student role) → accept → change role → deactivate.

## Open precedents reused

- Permission-gated `/manage/` views — cohort/subject pattern.
- `setup_roles`-after-migrate for new permission grants — Phase-3a lesson.
- Staff/non-staff cohort sync on `User.groups` change — Phase-3a grouping.
- `Invitation` model, token, email send, and `find_pending` — Phase 0c-1.
