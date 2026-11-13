# Invitation can put the student in a group

Approved by the owner on 2026-11-13 (conversation design, "A" of two options; "B", bulk
invitations, is a separate follow-up).

## Purpose

An invited student should see their course the first time they log in. Today an
`accounts.Invitation` carries only `email`, `role` and expiry. Accepting it creates the
account and sets the role, and nothing else, so a new student lands enrolled on nothing
until someone opens a group and ticks them. That is a dead gap in the student's
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

`Invitation.clean()` raises `ValidationError({"group": ...})` when `group` is set and
`role != STUDENT` (same message as the form). This is what the Django admin's
ModelAdmin runs, so the admin cannot create a staff invitation with a group. The
form's own check (below) stays, since the invite forms are plain `Form`s.

### Form — new `accounts.forms.SendStudentInvitationForm`

`SendInvitationForm` has two consumers today: the People → Invitations view and the
first-run setup wizard (`institution/views_setup.py::_team_step`, rendered field by
field in `templates/institution/setup/team.html`). The wizard must not change, so
`SendInvitationForm` itself is **left untouched** and the group field lives on a
subclass, `SendStudentInvitationForm(SendInvitationForm)` (name is the builder's call),
used only by the People view (`people_invitations` and `invitation_send`).

- New `group = forms.ModelChoiceField(required=False, label=_("Group"), ...)`, placed
  after `role`; its
  queryset is assigned in `__init__` (not at class definition), using the `CourseGroup`
  alias.
- Queryset: non-archived groups (`Group.objects.filter(archived=False)`), ordered by
  course title then group name, `select_related("course")`. Deliberately
  platform-wide: sending invitations needs `accounts.add_user`, which only the Platform
  Admin role holds, so no per-course scoping applies. Equally deliberately, there is no
  filter on the course's visibility or published state: the student is enrolled
  whatever the course's state, exactly as a manual group add would do.
- Option label: `"<group name> — <course title>"`.
- Empty choice label: "— no group —" (translatable).
- `clean()`: a group together with any role other than Student raises a field error on
  `group`. The check runs only when `role` is present in `cleaned_data` (an invalid,
  tampered role already has its own error; no `KeyError`, no second error): "A group can only be given to a Student invitation." (translatable).

### Service — `accounts.services.create_or_refresh_invitation`

Signature gains a keyword-only `group` parameter whose default is a module-level
sentinel (`_UNSET`), not `None`, so callers that don't know about groups (the wizard)
leave an existing pending invite's group alone. `group=None` passed explicitly means
"no group" and clears it.

- Create path: `Invitation.objects.create(..., group=group)`.
- Refresh path (a pending invite for the same email): updates `role`, `invited_by`,
  `expires_at`, and `group` **only when `group` was passed** (the People view always
  passes it, so leaving the group empty there clears it), then re-sends, as today.
  `update_fields` gains `"group"` only in that case. On the create path `_UNSET` means
  no group. Exception: when `group` is `_UNSET` and the new role is **not** Student, a
  stored group is cleared (and `update_fields` gains `"group"`), so a wizard re-invite
  that changes a grouped Student invite to Teacher never leaves a group on a
  non-Student row.
- The existing-account rejection is unchanged and still runs first.
- A `group` with `role != STUDENT` raises `InvitationError` ("A group can only be given
  to a Student invitation."), before anything is created or refreshed, so every future
  caller (bulk invites, the shell) gets the Student-only rule too. From the People view
  this branch is unreachable (the form's `clean()` rejects the combination first), so
  the view's existing `form.add_error("email", ...)` handler is left as is.
- An archived group raises `InvitationError` ("This group is archived.") as well, so no
  caller can store a group that would be silently dropped at accept. (Unreachable from
  the People view, whose queryset excludes archived groups.)

### View / template — People → Invitations

- `accounts/views_manage.py::invitation_send` passes `group=form.cleaned_data["group"]`.
- `templates/accounts/manage/invitations.html`: the form renders a **Group** field after
  Role (same `manage__field` label pattern), with `{{ form.group.errors }}`.
- The list gets a **Group** column after Role (header `{% translate "Group" %}`), showing `"<group> — <course>"` or an
  empty cell. A group archived after the invitation was sent is shown with a
  translatable "(archived)" marker on **pending** rows only, so the admin can see that
  accepting will not add the student anywhere. Accepted and expired rows show the group
  plainly (for an accepted row the student was added before the archive). `_render_invitations` adds `select_related("group__course")` to avoid N+1.

### Accept — one shared helper, two call sites

New helper in `accounts/services.py` (name is the builder's call, e.g.
`apply_invitation_group(invitation, user)`):

- If `invitation.group_id` is `None` → do nothing.
- If `invitation.role != STUDENT` → do nothing (defence in depth: `clean()` already
  forbids it, but rows can exist that never went through `clean()`, e.g. a shell edit).
- Re-read the group as `CourseGroup.objects.select_for_update().filter(pk=invitation.group_id,
  archived=False).first()`, inside the caller's transaction. No `select_related` on
  this read (or, if one is added, `select_for_update(of=("self",))`), so only the
  group row is locked, never the course row. If that returns `None`
  (deleted or archived) → do nothing. The row lock serialises with
  `set_group_archived`, whose `save()` takes the row lock before it reads the
  membership list, so a group archived concurrently cannot slip through. A concurrent
  `delete_group` is NOT covered: it reads its member list before `group.delete()` waits
  on the lock. That is a pre-existing race shared with every manual add
  (`add_students_to_group` locks nothing either) and is accepted here.
- Otherwise call `grouping.services.add_students_to_group(group, [user],
  added_by=invitation.invited_by)`. That service already creates the membership,
  recomputes enrolment and fires `notify_enrolled`. It is idempotent.
- Imports, lazily inside the function: `from grouping.models import Group as
  CourseGroup` and `from grouping.services import add_students_to_group`. Two reasons.
  (1) Name clash: `accounts/services.py` already imports
  `django.contrib.auth.models.Group` at module level for roles (`set_user_role`); that
  name must keep meaning the auth role group, so the grouping model is always imported
  under the alias `CourseGroup`, here and in the form and admin too. (2) Cycle risk:
  `grouping.services` imports `accounts.models`, so a top-level import from
  `accounts/services.py` risks an import cycle. Only `services.py` needs the lazy
  import; the model FK (string reference) and the form/admin (which build their
  querysets in `__init__` / `get_form`, see below) do not create an import-time cycle.

Call sites:

1. **Password accept** — `accounts/views.py::_consume_and_create`, inside the existing
   `transaction.atomic()`, after `set_user_role(user, locked.role)`. It uses `locked`
   (the `select_for_update` row), so the invitation's `group_id` is read consistently;
   the group's own `archived` state is read under the helper's own row lock (above).
2. **SSO accept** — `accounts/adapters.py::SocialAccountAdapter._consume_invitation`,
   inside its existing `atomic()` and `if locked.is_valid():` branch, after
   `set_user_role`, and it passes **`locked`** (the `select_for_update` re-read), never
   the `invitation` stashed in `pre_social_login` (read in an earlier request, before
   the OAuth round-trip, so its `group_id` and `invited_by` may be stale). Not on the
   "no invitation → Student" branch.

   In addition, the whole body of `SocialAccountAdapter.save_user` (the `super()` call
   that creates the User and SocialAccount, `ensure_verified_primary_email`, and
   `_consume_invitation`) is wrapped in one `transaction.atomic()`. allauth does not
   wrap `save_user` in a transaction and `ATOMIC_REQUESTS` is off, so without this an
   exception in the helper would roll back only the invitation's `accepted_at` and the
   role, leaving a role-less user + SocialAccount that the next SSO login would sign
   straight in (`sociallogin.is_existing`), with the invitation never consumed. With
   the wrap, the SSO path matches the password path: nothing is created, the
   invitation stays pending, and a retry works.

Both call it only after the role is set, and only for a still-valid invitation.

### Email — `templates/accounts/invite_email.txt`

When `invitation.group` is set, **not archived, and `invitation.role` is Student**, add a
line naming the course, e.g.
"You have been invited to the course: <course title>." Otherwise the email is unchanged.
The subject is unchanged.

The template is plaintext but rendered by Django's engine, which autoescapes `.txt`
too, so the course title must be rendered unescaped (`{% autoescape off %}` around the
line, or `|safe` on the title). Otherwise a title with `&` or an apostrophe arrives as
`&amp;` / `&#x27;`.

### Django admin — `accounts/admin.py::InvitationAdmin`

Add `role` and `group` to `list_display` and `fields`, editable on the change form only
(not in `list_editable`), so whoever sets a
group can see the role it depends on (today `role` is not shown in the admin at all).
`list_select_related = ("invited_by", "group__course")` avoids one query per row
(the explicit tuple replaces Django's automatic join of `list_display` FKs, so
`invited_by` must be listed too). The changelist's group column is an
`@admin.display(description="Group")` method showing `"<group> — <course>"`, not the
bare `group` field, so two "3A" groups are distinguishable. `autocomplete_fields`
is not needed.

The admin's `group` choices are restricted like the People form's: non-archived groups,
**plus** the invitation's current group when editing an existing row (so re-saving an
old invitation whose group was archived later does not fail validation). Done in the
ModelAdmin's form (`get_form` / a custom `ModelForm`), not in `Invitation.clean()`.
The admin's choices use the **same option label** (`"<group name> — <course title>"`),
ordering and `select_related("course")` as the People form, since
`grouping.Group.__str__` is the bare name and several courses can each have a "3A".
Share one `ModelChoiceField` subclass (its `label_from_instance`) between the two
forms. Creating an invite through the admin still relies on the existing post_save
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
  the invitation remains unconsumed and can be retried. On SSO this relies on the
  `save_user` wrap described under "SSO accept"; the account and SocialAccount are
  rolled back too. (Swallowing would leave an
  account with no group and no trace; the anti-goal covers *expected* degradations
  only: missing or archived group.)
- Form: group + non-Student role → field error, nothing created or sent.
- Re-inviting a pending email whose group has since been archived: the form no longer
  offers that group, so the refresh drops it (or replaces it with whatever was picked).
  This is intended.
- Editing a pending invitation's group in the Django admin does not resend the email
  (post_save sends only on create), so the student's email may name the old course.
  Accepted: the People form's re-invite is the path that resends.
- An `IntegrityError` raised inside the helper would be caught by `accept_invite`'s
  existing handler and shown as "username taken". Accepted: `add_students_to_group`
  already absorbs the one expected integrity race (concurrent membership/enrolment)
  with `get_or_create` in savepoints, so no other `IntegrityError` is expected there.
- Django admin form, a posted group outside the restricted choices together with a
  role change: the ModelForm reports "select a valid choice" on `group`, and
  `Invitation.clean()` may add a second error about the row's old group. Accepted: the
  save is refused either way, and this is an admin-only screen.
- Several pending invitations for one email (possible only via the Django admin): a
  refresh updates only the newest (`find_pending`), and an older token, if accepted,
  applies its own group. Accepted as is: the People form never creates duplicates, and
  each token carries the group it was sent with.

## Testing

- **Model/migration**: the field exists, is nullable, and deleting the group nulls it
  (the invitation survives).
- **Form**: group optional; an invalid role plus a group → only the role error; group + Teacher (and each non-Student role) → error on
  `group`; group + Student → valid; archived groups are not offered; option label
  format.
- **Service**: a group with a non-Student role raises `InvitationError` and creates
  nothing; create stores the group; refresh replaces it and clears it when `None`;
  the wizard call (no group kwarg) still works, and a wizard-style refresh (no `group`
  kwarg) of a pending invite **keeps** its group, while an explicit `group=None` clears
  it; an archived group raises `InvitationError`. A pending Student+group invite
  refreshed wizard-style (no `group` kwarg) to Teacher → the group is cleared and the
  resent email has no course line.
- **Wizard unchanged**: the setup wizard's team step renders without a group field and
  a Student invite through it still succeeds.
- **Password accept**: with a group → membership + enrolment on the group's course +
  `notify_enrolled` fired; without a group → no membership; group archived → account
  created, no membership; group deleted → account created, no membership.
- **Password accept, rollback**: the helper forced to raise a non-`IntegrityError`
  (which `accept_invite` does not catch) → the exception propagates, no User exists,
  `accepted_at` is still `None`.
- **SSO accept, stale stash**: stash an invitation in `pre_social_login`, then change
  its group in the DB (and, separately, clear it) before `save_user` runs → the student
  lands in the new group (or in none).
- **SSO accept**: same four cases through `SocialAccountAdapter` (following the
  existing SSO adapter tests' setup), plus: the helper forced to raise → no User, no
  SocialAccount, invitation still pending.
- **Role guard**: an invitation row with a group and role Teacher (written bypassing
  `clean()`) → accept creates the account, no membership; `Invitation.full_clean()` on
  such a row raises on `group`.
- **Archived race**: the helper's group read takes a row lock. Assert it in a way that
  fails if the lock is removed: run the helper inside `CaptureQueriesContext` and
  assert that the query whose `FROM` is `"grouping_group"` and which filters on the
  group's pk contains `FOR UPDATE` (other queries in the call tree join
  `grouping_group` too, so a loose substring match is not enough). (The archived-group
  behaviour case alone stays green without the lock.) A true concurrency test is not
  required.
- **View**: POST to `invitation_send` with a group saves it; the list shows the Group
  column, with the "(archived)" marker for an archived group on a pending row and no
  marker on an accepted row; the page does not N+1 (query count with several invitations).
- **Email**: with a group the body contains the course title; without one it doesn't.
  Also on the refresh path: re-invite with a different group → the resent body names
  the new course; re-invite with no group → the line is gone. The body always reflects
  the group as just saved. One case uses a course title containing `&` and an
  apostrophe and asserts they arrive unescaped. Resend (`resend_invitation`) of an
  invitation whose group has since been archived → no course line.
- **Admin**: the changelist and change form render with role and group (the changelist
  group cell includes the course title, and its query count does not grow with the
  number of rows); saving a
  non-Student invitation with a group through the admin form is rejected; the admin's
  group choices exclude archived groups except the row's current one, and each option's
  text includes the course title.
- **i18n**: new strings (field label and column header "Group", "— no group —", the
  Student-only error, "(archived)") have Polish translations in `locale/pl/LC_MESSAGES/django.po`,
  compiled `.mo` regenerated.
- **Help docs**: `docs/help/platform-admin/invitations.md` and `.pl.md` gain a short
  paragraph on the Group field.
