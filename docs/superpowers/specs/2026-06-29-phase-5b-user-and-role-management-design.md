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
| Editable user fields (PA) | `role`, `is_active`, `display_name`, `email` | Role + activation are the PA's job; name/email are correctable identity fields. `language`/`theme` stay user-owned preferences. |
| Lockout guard | Cannot deactivate self; cannot deactivate/demote the last active Platform Admin | Prevents the institution from locking itself out. |
| Deactivation side-effects | None unwound | Group/teacher/cohort assignments are left intact; the user is simply blocked from login; reactivation restores them as-is. |

## Data model

### `Invitation` (`accounts/models.py`)

Add one field; one migration.

- `role = models.CharField(max_length=32, choices=ROLE_CHOICES, default=STUDENT)`
  — constrained to the 4 role names defined in `institution/roles.py`. Default
  **Student**. (`max_length=32` comfortably covers the longest role name.)

The choices/constant source is `institution/roles.py` (single source of truth —
do **not** redeclare role strings in `accounts`). `ROLE_CHOICES` is derived from
the existing role-name constants there.

No change to the `User` model: a user's role **is** their Group membership;
"active" is the existing `is_active`; staff/non-staff is the existing `is_staff`.

## Services

A small role service keeps the "exactly one role" invariant and staff-sync in one
place, reused by the role-assignment UI **and** the invite-accept flow.

### `set_user_role(user, role)` (`accounts/services.py` — new)

- Atomically swaps the user's role Group membership so they belong to **exactly
  one** of the 4 role Groups.
- Sets `is_staff` from the role: Student → `False`; Teacher / Course Admin /
  Platform Admin → `True`.
- Reuses the existing Phase-3a staff-sync (the `User.groups` `m2m_changed` hook +
  `recompute`/cohort logic) so demotion **to** Student re-syncs cohort
  membership and promotion **off** Student removes the user from cohorts. This
  service must not duplicate that logic — it triggers it.

### Lockout guard helpers

- `is_last_active_platform_admin(user)` — true when `user` is the only active
  member of the Platform Admin group.
- Enforced wherever a change could remove the last PA's powers (deactivate,
  demote) and on self-deactivation. Surfaced as a form/validation error, not a
  500.

## Accept-flow change

`accept_invite` / the shared resolver in `accounts/provisioning.py` (and the
SSO-JIT path in `accounts/adapters.py` that consumes a pending invite via
`Invitation.find_pending`) call `set_user_role(user, invitation.role)` instead of
hardcoding Student.

## Views, URLs & access control

All views live in the **`accounts`** app (new `accounts/views.py` management
views + routes under `/manage/people/`), gated exactly like the cohort/subject
precedent:

```
@login_required
@permission_required("accounts.<perm>", raise_exception=True)
```

The relevant Django model permissions (`accounts.view_user`,
`accounts.add_user`, `accounts.change_user`) are granted to the **Platform
Admin** group in `institution/roles.py` and applied via `setup_roles` after
migrate — **not** via a migration `RunPython` (per the Phase-3a lesson that
`Permission.DoesNotExist` is raised if perms are seeded inside a migration).

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

## The `/manage/people/` page

### Users tab
- **Search** by display name / email; **filter** by role and by active state.
- Table columns: name (display name, falling back to email) · role · status
  (Active / Inactive) · last login.
- Each row links to **Edit user**.
- Paginated.

### Edit user
- **Role** — single-select over the 4 roles; saving calls `set_user_role`.
- **Active** — Deactivate / Reactivate action (subject to the lockout guard).
- **`display_name`** and **`email`** — editable for corrections.
- `language` / `theme` are **not** shown (user-owned preferences).

### Invitations tab
- **Send invitation** — email + role (default Student); creates the `Invitation`
  and sends the existing invite email via `send_invitation_email`.
- List of invitations with status: **Pending** / **Accepted** / **Expired**
  (derived from `accepted_at` + `expires_at`, mirroring `Invitation.is_valid`).
- **Revoke** (pending only) — invalidates the token.
- **Resend** (pending only) — re-sends the email and refreshes `expires_at`.

## Validation & edge cases

- **Invite to an existing active account** — rejected with a clear message
  (don't create a dead invite).
- **Invite to an email with a still-pending invite** — resend/refresh rather than
  create a duplicate (mirrors `find_pending` semantics).
- **Self-deactivation** — blocked.
- **Last active Platform Admin** — cannot be deactivated or demoted.
- **Role change** — swaps Groups + `is_staff` atomically; does not unwind
  existing group/teacher/cohort assignments beyond the automatic cohort staff-sync.

## Cross-cutting

- **i18n** — EN/PL for every new string; clear any `#, fuzzy` flags and verify new
  msgids (per the `uv run` / makemessages note).
- **Styling** — per the design language; light/dark; mobile-responsive; new
  templates carry their per-page CSS link and use only defined utility classes.
  Verify with light+dark screenshots (throwaway Playwright harness, delete after
  review).
- **Tests** — pytest + factory_boy against real PostgreSQL: the role service
  (swap + staff-sync + lockout guard), invite-with-role accept, deactivate/
  reactivate, and the validation edge cases. One **e2e** test driving the real
  gesture path: invite (with a non-Student role) → accept → change role →
  deactivate.

## Open precedents reused

- Permission-gated `/manage/` views — cohort/subject pattern.
- `setup_roles`-after-migrate for new permission grants — Phase-3a lesson.
- Staff/non-staff cohort sync on `User.groups` change — Phase-3a grouping.
- `Invitation` model, token, email send, and `find_pending` — Phase 0c-1.
