# Invitation can put the student in a group

Approved by the owner on 2026-11-13 (conversation design, "A" of two options; "B", bulk
invitations, is a separate follow-up).

## Purpose

An invited student should see their course the first time they log in. Today an
`accounts.Invitation` carries only `email`, `role` and expiry. Accepting it creates the
account and sets the role, and nothing else, so a new student lands enrolled on nothing
until a Course Admin opens a group and ticks them. That is a dead gap in the student's
first experience, and it needs a second visit from the admin for every invitee.

The immediate need is the E8 maths pilot (two students invited to one course). The
longer-term need is the course's planned invitation-based access.

### Goals

- An invitation may optionally name one **group**. Accepting it adds the new student to
  that group as part of account creation, which (through the existing grouping service)
  enrols them on the group's course and sends the usual "you've been enrolled"
  notification.
- Leaving the group empty keeps today's behaviour exactly.

### Non-goals

- Pasting a list of emails; adding an *existing* account to a group from the invite
  form (follow-up B).
- More than one group per invitation.
- Inviting teachers into a group (group is Student-only).
- Any change to the first-run setup wizard's invite step.
- Translating the invitation email (it is English-only today; unchanged here apart from
  the new course line).

### Anti-goals

- Signup must never fail, or be refused, because of the group. A missing or archived
  group degrades to "account created, not added".

## Architecture / components

### Data model — `accounts.Invitation`

New field:

```python
group = models.ForeignKey(
    "grouping.Group",
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name="invitations",
    help_text="Student is added to this group on accept (optional).",
)
```

Plus one migration in `accounts`. `SET_NULL` means deleting the group (or its course,
which cascades to the group) silently drops the link; the invitation stays valid.

### Form — `accounts.forms.SendInvitationForm`

- New `group = forms.ModelChoiceField(required=False, ...)`, placed after `role`.
- Queryset: non-archived groups (`Group.objects.filter(archived=False)`), ordered by
  course title then group name, `select_related("course")`.
- Option label: `"<group name> — <course title>"`.
- Empty choice label: "— no group —" (translatable).
- `clean()`: a group together with any role other than Student raises a field error on
  `group`: "A group can only be given to a Student invitation." (translatable).

### Service — `accounts.services.create_or_refresh_invitation`

Signature gains `group=None` (keyword-only, defaulting to `None` so the first-run wizard
call site is unchanged).

- Create path: `Invitation.objects.create(..., group=group)`.
- Refresh path (a pending invite for the same email): updates `role`, `invited_by`,
  `expires_at` **and `group`** (so leaving the group empty on a re-invite clears it), then
  re-sends, as today. `update_fields` gains `"group"`.
- The existing-account rejection is unchanged and still runs first.

Builder's call: the wizard path passes no group, so a wizard re-invite of a pending
email clears any group on it. The wizard invites staff at first run, so this is accepted.

### View / template — People → Invitations

- `accounts/views_manage.py::invitation_send` passes `group=form.cleaned_data["group"]`.
- `templates/accounts/manage/invitations.html`: the form renders a **Group** field after
  Role (same `manage__field` label pattern), with `{{ form.group.errors }}`.
- The list gets a **Group** column after Role, showing `"<group> — <course>"` or an
  empty cell. `_render_invitations` adds `select_related("group__course")` to avoid N+1.

### Accept — one shared helper, two call sites

New helper in `accounts/services.py` (name is the builder's call, e.g.
`apply_invitation_group(invitation, user)`):

- If `invitation.group_id` is `None` → do nothing.
- If the group is archived → do nothing.
- Otherwise call `grouping.services.add_students_to_group(group, [user],
  added_by=invitation.invited_by)`. That service already creates the membership,
  recomputes enrolment and fires `notify_enrolled`. It is idempotent.
- Import `grouping.services` lazily inside the function (as `adapters.py` already does
  for `set_user_role`) to keep `accounts` free of an import-time dependency on
  `grouping`.

Call sites:

1. **Password accept** — `accounts/views.py::_consume_and_create`, inside the existing
   `transaction.atomic()`, after `set_user_role(user, locked.role)`. It uses `locked`
   (the `select_for_update` row), so a group change racing the accept is read
   consistently.
2. **SSO accept** — `accounts/adapters.py::SocialAccountAdapter._consume_invitation`,
   inside its existing `atomic()` and `if locked.is_valid():` branch, after
   `set_user_role`. Not on the "no invitation → Student" branch.

Both call it only after the role is set, and only for a still-valid invitation.

### Email — `templates/accounts/invite_email.txt`

When `invitation.group` is set, add a line naming the course, e.g.
"You have been invited to the course: <course title>." Otherwise the email is unchanged.
The subject is unchanged.

### Django admin — `accounts/admin.py::InvitationAdmin`

Add `group` to `list_display` and `fields` (editable; `autocomplete_fields` is not
needed). Creating an invite through the admin still relies on the existing post_save
signal to send the email.

## Data flow

1. Admin opens People → Invitations, enters email, role Student, picks group G.
2. `invitation_send` validates the form → `create_or_refresh_invitation(email, role,
   invited_by, group=G)` → `Invitation(group=G)` saved → post_save signal emails the link
   (the email now names G's course).
3. The student opens the link:
   - Password: `accept_invite` → `_consume_and_create` → user created, role set, helper
     adds them to G → `add_students_to_group` → `GroupMembership` +
     `Enrollment(source="group")` + notification → `perform_login`.
   - SSO: `pre_social_login` stashes the invite → `save_user` →
     `_consume_invitation` → role set, helper adds them to G.
4. On first login the course is in the student's course list.

## Error handling

- Group deleted before accept → FK is `NULL` → no-op; account created.
- Group archived before accept → no-op; account created. (Adding a student to an
  archived group would create a membership that grants no enrolment and that nobody
  sees.)
- Concurrent add of the same student (e.g. an admin ticks them at the same moment):
  `add_students_to_group` already uses a per-student savepoint and `get_or_create`.
- Any unexpected exception inside the helper must **not** be swallowed silently; it
  propagates and rolls back the atomic block, so the user sees the normal error, and
  the invitation remains unconsumed and can be retried. (Swallowing would leave an
  account with no group and no trace; the anti-goal covers *expected* degradations
  only: missing or archived group.)
- Form: group + non-Student role → field error, nothing created or sent.

## Testing

- **Model/migration**: the field exists, is nullable, and deleting the group nulls it
  (the invitation survives).
- **Form**: group optional; group + Teacher (and each non-Student role) → error on
  `group`; group + Student → valid; archived groups are not offered; option label
  format.
- **Service**: create stores the group; refresh replaces it and clears it when `None`;
  the wizard call (no group kwarg) still works.
- **Password accept**: with a group → membership + enrolment on the group's course +
  `notify_enrolled` fired; without a group → no membership; group archived → account
  created, no membership; group deleted → account created, no membership.
- **SSO accept**: same four cases through `SocialAccountAdapter` (following the
  existing SSO adapter tests' setup).
- **View**: POST to `invitation_send` with a group saves it; the list shows the Group
  column; the page does not N+1 (query count with several invitations).
- **Email**: with a group the body contains the course title; without one it doesn't.
- **Admin**: the changelist and change form render with the group.
- **i18n**: new strings have Polish translations in `locale/pl/LC_MESSAGES/django.po`,
  compiled `.mo` regenerated.
- **Help docs**: `docs/help/platform-admin/invitations.md` and `.pl.md` gain a short
  paragraph on the Group field.
