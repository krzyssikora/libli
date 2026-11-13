# Invitation Group Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An invitation may name one course group; accepting it adds the new student to that group (and so enrols them) in the same transaction that creates the account.

**Architecture:** A nullable `Invitation.group` FK, validated Student-only at model, form and service level. One accept helper in `accounts/services.py`, called from the password path (`accounts/views.py`) and the SSO path (`accounts/adapters.py`), delegates to the existing `grouping.services.add_students_to_group`. The People → Invitations form gains a Group select through a subclass so the setup wizard's form is untouched.

**Tech Stack:** Django, django-allauth, pytest + pytest-django, factory_boy, Playwright (screenshots only).

**Spec:** `docs/superpowers/specs/2026-11-13-invitation-group-design.md` — read it alongside this plan; it is the authority on behaviour, this plan on names and order.

## Global Constraints

- In new code in `accounts/` (services, forms, admin) and the new test files, the grouping model is ALWAYS imported as `from grouping.models import Group as CourseGroup`. Existing modules that already import `grouping.models.Group` (e.g. `seed_demo_course.py`) keep their import. `Group` in `accounts/services.py` and in tests near `AuthGroup` means `django.contrib.auth.models.Group` (roles).
- In `accounts/services.py`, grouping imports are lazy (inside functions). `grouping.services` imports `accounts.models`.
- `SendInvitationForm` (used by the setup wizard) is NOT modified.
- Student-only error copy: `"A group can only be given to a Student invitation."`; archived-group service error: `"This group is archived."`; empty choice: `"— no group —"`; marker: `"(archived)"`; field label / column header: `"Group"`. All translatable.
- Option / cell label: `"<group name> — <course title>"` (em dash, spaces around it).
- Email course line: `You have been invited to the course: <course title>.`, rendered unescaped, only when group set AND not archived AND role is Student.
- Tests: start the DB first (`docker start libli-test-db`), run `uv run pytest <paths> -p no:cacheprovider`. NEVER pass `-q` (addopts already has it; doubling hides the summary). Grep the summary line, don't trust the exit code alone.
- Commits: explicit paths only (never `git add -A` / `.`); end each message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- CSS edits: afterwards run every `tests/test_*css*.py`.
- "Run → FAIL" at Step 2 means the tests asserting a NEW effect fail. Tests that only assert an absence (no membership, no course line) may already pass at RED in Tasks 3, 4 and 6; that is expected, and the falsification steps (Task 2 Step 4b, Task 6 Step 4b) are what prove those guards. Undo every mutant BY HAND (re-edit the line), never with `git checkout` / `git restore`, which would discard the task's uncommitted work; then `git diff` to confirm the mutant is gone.

## Review Focus

1. A Course Admin or Teacher invitation that somehow carries a group (admin edit, shell, wizard refresh) must never put staff into a student group → role guard tests in Tasks 1, 2.
2. An SSO sign-up whose group add fails must not leave a role-less account that later logs straight in → rollback test in Task 4.
3. A course title with `&` / `'` must arrive readable in the plaintext email → Task 6.
4. Two groups called "3A" on different courses must be distinguishable everywhere the admin picks or reads one → label tests in Tasks 5, 7.
5. A long course title must not make the invite form scroll sideways on a phone → Task 5 CSS + 360px check.

---

### Task 1: `Invitation.group` field, model validation, migration

**Files:**
- Modify: `accounts/models.py` (class `Invitation`)
- Create: `accounts/migrations/0007_invitation_group.py` (generated)
- Modify: `tests/test_subject_migrations.py:48`, `tests/test_geogebra_migration.py:53` (restore calls)
- Test: `tests/test_invitation_group_model.py` (new)

**Interfaces:**
- Produces: `Invitation.group` (FK `grouping.Group`, `null=True, blank=True, on_delete=SET_NULL, related_name="invitations"`, help_text per spec); `Invitation.clean()` raising `ValidationError({"group": <Student-only message>})` when `group_id` is set and `role != STUDENT`.

- [ ] **Step 1: Write failing tests** (`@pytest.mark.django_db`, use `GroupFactory` from `tests.factories`):
  - `test_group_is_optional`: `Invitation.objects.create(email="a@x.edu").group is None`.
  - `test_deleting_group_nulls_invitation_group`: create with `group=g`; `g.delete()`; `inv.refresh_from_db()`; `inv.group is None` and the row still exists.
  - `test_full_clean_rejects_group_on_non_student`: for each of `TEACHER, COURSE_ADMIN, PLATFORM_ADMIN` (from `institution.roles`), `Invitation(email=..., role=r, group=g).full_clean()` raises `ValidationError` with `"group"` in `exc.message_dict`.
  - `test_full_clean_accepts_group_on_student`: role `STUDENT` + group → no error.
  - `test_group_column_present_after_migration_tests` (`@pytest.mark.django_db(transaction=True)`): creates an Invitation with a group and reads it back; guards the restore fix in Step 3b.
- [ ] **Step 2: Run** `uv run pytest tests/test_invitation_group_model.py -p no:cacheprovider` → FAIL (no field).
- [ ] **Step 3: Implement** the field and `clean()` (call `super().clean()` first; import `STUDENT` from `institution.roles`, message via `gettext_lazy`). Generate the migration: `uv run python manage.py makemigrations accounts -n invitation_group`. Check it depends on the latest `grouping` migration (`0005_allocation`) and only adds the field.
- [ ] **Step 3a: See the ordering failure.** Run the ordering check (command in Step 4) now, before Step 3b: `test_group_column_present_after_migration_tests` must FAIL with a missing `group_id` column. If it passes, stop and report: the premise of Step 3b is wrong.
- [ ] **Step 3b: Fix the migration tests' restore.** `grouping.0005_allocation` depends on `courses.0060`, so the two migration tests that migrate `courses` back below 0060 (`test_subject_migrations` to 0023/0024, `test_geogebra_migration` to 0028) also unapply `accounts.0007`, and their restore `call_command("migrate", "courses", ...)` never re-applies it (the column is then missing for every later test in the process). The `test_attempts_migration*` files only go back to 0069 and are left alone. Also replace the trailing `_migrate(AFTER)` at the end of `test_title_is_copied_into_title_en` in `tests/test_subject_migrations.py` with the same whole-graph restore (run alone, it would otherwise leave `accounts.0007` unapplied). Change those restore calls to `call_command("migrate", verbosity=0)` (no app: whole graph head), keeping the existing comments' intent.
- [ ] **Step 4: Run** the new tests plus `tests/test_invitations.py tests/test_invitation_role_field.py` → all PASS. Then the ordering check, in one process: `uv run pytest tests/test_subject_migrations.py tests/test_geogebra_migration.py tests/test_invitation_group_model.py -p no:cacheprovider` (pytest runs files in the order given; transactional tests run last) → PASS (it failed in Step 3a).
- [ ] **Step 5: Commit** `accounts/models.py accounts/migrations/0007_invitation_group.py tests/test_invitation_group_model.py` and the two migration-test files — `feat(invitations): optional group on an invitation`.

### Task 2: service — `create_or_refresh_invitation(group=…)` and `apply_invitation_group`

**Files:**
- Modify: `accounts/services.py`
- Test: `tests/test_invitation_group_services.py` (new)

**Interfaces:**
- Consumes: Task 1's `Invitation.group`.
- Produces:
  - `_UNSET = object()` (module level).
  - `create_or_refresh_invitation(*, email, role, invited_by, group=_UNSET) -> tuple[Invitation, bool]` (same return as today).
  - `apply_invitation_group(invitation, user) -> None`.

- [ ] **Step 1: Write failing tests** (use `mailoutbox`, `django_capture_on_commit_callbacks(execute=True)` around creates since the create email is sent on commit):
  - `test_group_with_non_student_role_raises`: `role=TEACHER, group=g` → `InvitationError`; `Invitation.objects.count() == 0`.
  - `test_archived_group_raises`: `g.archived=True` saved; Student + `group=g` → `InvitationError`, nothing created.
  - `test_create_stores_group`: Student + `group=g` → `inv.group == g`.
  - `test_create_without_group_kwarg_has_no_group`.
  - `test_refresh_replaces_group`: create with `g1`, call again with `group=g2` → `g2`, `created is False`.
  - `test_refresh_explicit_none_clears_group`.
  - `test_refresh_without_group_kwarg_keeps_group` (wizard-style).
  - `test_refresh_without_group_kwarg_to_teacher_clears_group`: create Student+`g`; refresh `role=TEACHER` with no `group` → `inv.group is None` (the load-bearing check; the email side is covered by Task 6's `test_refresh_to_teacher_email_has_no_course_line`).
  - `test_apply_adds_student_and_enrols`: pending Student invite with `g`; `user = UserFactory()`; `apply_invitation_group(inv, user)` → `GroupMembership` for (g, user) exists; `Enrollment.objects.filter(student=user, course=g.course, source="group").exists()`; `Notification.objects.filter(recipient=user, kind=Notification.Kind.ENROLLED, actor__isnull=True).count() == 1`.
  - `test_apply_noop_without_group`, `test_apply_noop_for_non_student_row` (row written with `Invitation.objects.create(role=TEACHER, group=g)`, bypassing `clean()`), `test_apply_noop_for_archived_group`, `test_apply_noop_after_group_deleted`.
  - `test_apply_locks_group_row`: within `CaptureQueriesContext(connection)` call the helper; find queries whose SQL contains `FROM "grouping_group"` and matches `re.search(rf'"grouping_group"\."id" = {g.pk}\b', sql)` (a word-boundary regex, not a substring: `= 1` must not match `= 12`); assert at least one exists and all of them contain `FOR UPDATE`; also assert none of them contains `"courses_course"`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Add `from institution.roles import STUDENT` at module level next to the existing `institution.roles` imports. In `create_or_refresh_invitation`: keep the existing-account check first; then if `group is not _UNSET and group is not None`: raise `InvitationError(gettext("A group can only be given to a Student invitation."))` if `role != STUDENT`, then `InvitationError(gettext("This group is archived."))` if `group.archived` (same msgid as the form/model message, so one translation covers all three). Create path passes `group=None if group is _UNSET else group`. Refresh path: `fields = ["role", "invited_by", "expires_at"]`; if `group is not _UNSET`: set it and append `"group"`; elif `role != STUDENT and pending.group_id`: set `None`, append `"group"`. `apply_invitation_group`: exactly the spec's "Accept" bullets (lazy imports, `CourseGroup.objects.select_for_update().filter(pk=..., archived=False).first()`, no `select_related`, then `add_students_to_group(group, [user], added_by=invitation.invited_by)`).
- [ ] **Step 4: Run** the new file plus `tests/test_invitation_services.py tests/test_setup_wizard.py` → PASS.
- [ ] **Step 4b: Falsify the helper's guards**, one mutant at a time, each run against `tests/test_invitation_group_services.py`: (1) delete the `role != STUDENT` early return in `apply_invitation_group` → `test_apply_noop_for_non_student_row` must go RED; (2) drop `archived=False` from the group re-read → `test_apply_noop_for_archived_group` must go RED; (3) drop `.select_for_update()` → `test_apply_locks_group_row` must go RED; (4) in the refresh path, remove the "`_UNSET` + non-Student clears the group" branch → `test_refresh_without_group_kwarg_to_teacher_clears_group` must go RED. Undo each by hand and re-run green.
- [ ] **Step 5: Commit** `accounts/services.py tests/test_invitation_group_services.py` — `feat(invitations): service stores the group and applies it on accept`.

### Task 3: password accept adds the student to the group

**Files:**
- Modify: `accounts/views.py` (`_consume_and_create`)
- Test: `tests/test_invitation_group_accept.py` (new)

**Interfaces:**
- Consumes: `apply_invitation_group(invitation, user)` from Task 2.

- [ ] **Step 1: Write failing tests** (POST to `/invite/accept/<token>/` with `{"username": ..., "password": TEST_PASSWORD}`, as in `tests/test_invitations.py`):
  - `test_password_accept_with_group_enrols`: membership + `Enrollment(source="group")` on `g.course` + one ENROLLED notification.
  - `test_password_accept_without_group_no_membership`.
  - `test_password_accept_archived_group_creates_account_only`.
  - `test_password_accept_deleted_group_creates_account_only`.
  - `test_password_accept_non_student_row_with_group_no_membership` (row created bypassing `clean()`).
  - `test_password_accept_helper_failure_rolls_back`: `monkeypatch.setattr("accounts.views.apply_invitation_group", boom)` where `boom` raises `RuntimeError`; `with pytest.raises(RuntimeError)` around `client.post(...)` (set `client.raise_request_exception = True`, the default); then `not User.objects.filter(username=...).exists()` and `inv.refresh_from_db(); inv.accepted_at is None`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement:** `from accounts.services import apply_invitation_group` at module level in `accounts/views.py`; call `apply_invitation_group(locked, user)` inside the atomic block right after `set_user_role(user, locked.role)`.
- [ ] **Step 4: Run** the new file plus `tests/test_invitations.py tests/test_accept_role.py` → PASS.
- [ ] **Step 5: Commit** `accounts/views.py tests/test_invitation_group_accept.py` — `feat(invitations): password accept joins the invited group`.

### Task 4: SSO accept adds the student; `save_user` is atomic

**Files:**
- Modify: `accounts/adapters.py` (`SocialAccountAdapter.save_user`, `_consume_invitation`)
- Test: `tests/test_invitation_group_sso.py` (new; reuse the `oidc_app` fixture pattern, `tests._sso.make_request` / `make_sociallogin`, and `_adapter()` from `tests/test_sso_provisioning.py` — copy the small fixture/helper rather than importing test modules)

**Interfaces:**
- Consumes: `apply_invitation_group` from Task 2.

- [ ] **Step 1: Write failing tests:**
  - With group / without group / archived / deleted / non-Student row with a group (`Invitation.objects.create(role=TEACHER, group=g)`, as `test_sso_accept_non_student_row_with_group_no_membership`): the same five outcomes as Task 3, via `_adapter().save_user(request, sl)` with `sl._libli_invitation = inv`.
  - `test_sso_uses_locked_row_not_stale_stash`: stash `inv` (group `g1`); then `Invitation.objects.filter(pk=inv.pk).update(group=g2)`; `save_user` → member of `g2`, not `g1`. Second test: `.update(group=None)` → no membership.
  - `test_sso_helper_failure_rolls_back_everything`: monkeypatch `accounts.services.apply_invitation_group` to raise `RuntimeError` (adapters keeps importing it lazily inside `_consume_invitation`, like `set_user_role`, so the patched attribute is what it picks up); `pytest.raises(RuntimeError)`; then no `User` with that username, no `SocialAccount`, `inv.accepted_at is None`. Plain `@pytest.mark.django_db` (no `transaction=True`): the `save_user` atomic becomes a savepoint inside the test transaction, so its rollback is real and visible, and without the wrap the User row would survive (RED).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement:** wrap the whole body of `save_user` in `with transaction.atomic():` (returning `user` after the block). In `_consume_invitation`, add `from accounts.services import apply_invitation_group` next to the existing lazy `set_user_role` import (NOT at module level, or the test's monkeypatch of `accounts.services.apply_invitation_group` won't take effect), and inside the `if locked.is_valid():` branch after `set_user_role(user, locked.role)`, call `apply_invitation_group(locked, user)`. Do not touch the no-invitation branch.
- [ ] **Step 4: Run** the new file plus `tests/test_sso_provisioning.py tests/test_signup_policy_sso_only.py tests/test_sso_name_sync.py` → PASS.
- [ ] **Step 5: Commit** `accounts/adapters.py tests/test_invitation_group_sso.py` — `feat(invitations): SSO accept joins the invited group atomically`.

### Task 5: People → Invitations form, view, list column, phone width

**Files:**
- Modify: `accounts/forms.py`, `accounts/views_manage.py` (`_render_invitations`, `people_invitations`, `invitation_send`), `templates/accounts/manage/invitations.html`, `accounts/static/accounts/css/people.css`
- Test: `tests/test_people_invitations_group.py` (new)

**Interfaces:**
- Consumes: Task 2's `create_or_refresh_invitation(..., group=...)`.
- Produces (for Task 7): `class CourseGroupChoiceField(forms.ModelChoiceField)` with `label_from_instance(obj) -> str` returning `f"{obj.name} — {obj.course.title}"`; `def course_group_queryset(include_pk=None) -> QuerySet` returning `CourseGroup.objects.filter(Q(archived=False) | Q(pk=include_pk)).select_related("course").order_by("course__title", "name")` (with `include_pk=None` the `Q(pk=None)` matches nothing); `class SendStudentInvitationForm(SendInvitationForm)` with field `group`.

- [ ] **Step 1: Write failing tests** (reuse `make_pa(client)` from `tests/factories` or the local helper style in `tests/test_people_invitations_tab.py`):
  - Form: `test_group_optional`; `test_group_with_teacher_errors_on_group` (each non-Student role → `"group" in form.errors`); `test_invalid_role_with_group_only_role_error` (`role="Nope"` → `"role" in errors`, `"group" not in errors`); `test_archived_group_not_offered`; `test_option_label_has_course_title` (`form.fields["group"].label_from_instance(g) == f"{g.name} — {g.course.title}"`).
  - Wizard unchanged: `test_setup_wizard_form_has_no_group_field` (`"group" not in SendInvitationForm().fields`), and GET of `reverse("institution:setup_step", kwargs={"step": "team"})` as PA returns 200, contains `name="email"` (the invite form rendered) and does not contain `name="group"`.
  - View: `test_get_shows_same_named_groups_with_course` (two groups named "3A" on courses "Alpha" and "Beta": the GET HTML contains both `3A — Alpha` and `3A — Beta`); `test_send_with_group_saves_it` (POST `{"email", "role": "Student", "group": g.pk}` → `Invitation.group == g`); `test_list_shows_group_and_course`; `test_list_marks_archived_group_on_pending_row_only` (pending row with archived group shows `(archived)`; accepted row with archived group does not — assert per row via the email cell's `<tr>`); `test_list_query_count_flat` (create all five courses, groups and inviter users plus the first Invitation BEFORE anything is measured; then one unmeasured warm-up GET, so cache misses such as `get_site_config()` are paid outside the measurement; then GET inside `CaptureQueriesContext(connection)`; then ONLY `Invitation.objects.bulk_create(...)` the 4 remaining invitations (bulk_create sends no signals); GET again inside a second context; assert the two `len(ctx.captured_queries)` are equal).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** in `accounts/forms.py`: `CourseGroupChoiceField`, `course_group_queryset()` (lazy `CourseGroup` import inside the function), `SendStudentInvitationForm` with `group = CourseGroupChoiceField(queryset=None, required=False, label=_("Group"), empty_label=_("— no group —"))` at class level, and `self.fields["group"].queryset = course_group_queryset()` in `__init__`, `clean()` per spec (check only when `"role" in cleaned_data`). Views: both use `SendStudentInvitationForm`; `invitation_send` passes `group=form.cleaned_data["group"]`; `_render_invitations` uses `select_related("group__course")`. Template: Group field label after Role (`{{ form.group }}{{ form.group.errors }}`), `<th>{% trans "Group" %}</th>` after Role, cell `{% if row.inv.group %}{{ row.inv.group.name }} — {{ row.inv.group.course.title }}{% if row.inv.group.archived and row.inv.status == "pending" %} {% trans "(archived)" %}{% endif %}{% endif %}`. CSS: in `accounts/static/accounts/css/people.css` (the page-only sheet that owns `.invite-form`), add `.invite-form select { max-width: 100%; }` right after the TOP-LEVEL `.invite-form .manage__field` rule (outside the narrow-screen media query; the selector appears twice) (keep the change line-count small; don't reflow neighbours).
- [ ] **Step 4: Run** the new file plus `tests/test_people_invitations_tab.py tests/test_setup_wizard.py tests/test_invite_domain_warning.py` and every `tests/test_*css*.py` → PASS. Then the browser tests that submit this form: `uv run pytest tests/test_e2e_settings_5c.py tests/test_e2e_people.py -m e2e -p no:cacheprovider` → PASS. Then a 360px A/B check in a throwaway `tests/tmp_invite_width.py` marked `@pytest.mark.e2e`, using the same `live_server` / login fixtures as `tests/test_e2e_people.py`, run with `-m e2e`, deleted afterwards (not manual). For the "without" run, inject `page.add_style_tag(content=".invite-form select{max-width:none}")` instead of editing the CSS: the invitations page as PA, viewport 360 wide, with a group whose course title is 120 characters; record `document.documentElement.scrollWidth` once with the override injected and once without it. Expected: > 360 without, <= 360 with. If it is already <= 360 without the rule, drop the rule (and its commit line) and say so in the task report. Don't commit the throwaway.
- [ ] **Step 5: Commit** the four source files + `tests/test_people_invitations_group.py` — `feat(invitations): pick a group when inviting a student`.

### Task 6: invitation email names the course

**Files:**
- Modify: `templates/accounts/invite_email.txt`
- Test: `tests/test_invitation_group_email.py` (new)

**Interfaces:**
- Consumes: `create_or_refresh_invitation`, `resend_invitation` (existing), Task 1's field.

- [ ] **Step 1: Write failing tests** (course line = `"You have been invited to the course: "`):
  - `test_no_group_body_unchanged`: render `send_invitation_email` for a no-group invite and assert the body equals today's text. Compare line-ending-normalised: `body.replace("\r\n", "\n") == expected` (the template is checked out with CRLF on Windows and LF on CI). Capture the expected literal NOW, before any template edit: render today's body once, normalise it the same way, and paste it into the test with `\n` only, with two placeholders filled at test time: `build_accept_url(inv)` and `Template("{{ d }}").render(Context({"d": inv.expires_at}))` — never `str()`/`isoformat()`, which don't match Django's localised rendering. This test passes in Step 2 (expected); it guards Step 3.
  - `test_email_names_course_when_group_set` (create through the service under `django_capture_on_commit_callbacks(execute=True)`; body contains `f"...course: {g.course.title}."`).
  - `test_email_has_no_course_line_without_group`.
  - `test_email_unescapes_title`: course title `"Matma & fizyka 'plus'"` → body contains it verbatim, not `&amp;` / `&#x27;`.
  - `test_refresh_email_names_new_course` and `test_refresh_email_drops_line_when_cleared`.
  - `test_resend_after_archive_has_no_course_line` (`resend_invitation(inv)` after `g.archived=True` saved).
  - `test_non_student_row_has_no_course_line` (row bypassing `clean()`; `send_invitation_email(inv)`).
  - `test_refresh_to_teacher_email_has_no_course_line`: create Student + group through the service, then refresh the same email with `role=TEACHER` and no `group` kwarg; the resent body (last of `mailoutbox`) has no course line.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** in the template: `{% if invitation.group and not invitation.group.archived and invitation.role == "Student" %}{% autoescape off %}You have been invited to the course: {{ invitation.group.course.title }}.{% endautoescape %}{% endif %}` with the `{% if %}` opening at the END of line 1 (`You have been invited to join libli.{% if ... %}`), then a newline, a blank line, the course line, and `{% endif %}` at the end of that course line, so a false condition adds no line at all and a no-group email is unchanged. (The literal `"Student"` matches `institution.roles.STUDENT`.)
- [ ] **Step 4: Run** the new file plus `tests/test_invitations.py tests/test_people_invitations_tab.py` → PASS.
- [ ] **Step 4b: Falsify the template conditions**, one at a time against `tests/test_invitation_group_email.py`: (1) remove `and not invitation.group.archived` → `test_resend_after_archive_has_no_course_line` must go RED; (2) remove `and invitation.role == "Student"` → `test_non_student_row_has_no_course_line` must go RED; (3) remove `{% autoescape off %}`/`{% endautoescape %}` → `test_email_unescapes_title` must go RED; (4) move the blank line outside the `{% if %}` → `test_no_group_body_unchanged` must go RED. Undo each by hand and re-run green.
- [ ] **Step 5: Commit** `templates/accounts/invite_email.txt tests/test_invitation_group_email.py` — `feat(invitations): email names the course of the invited group`.

### Task 7: Django admin shows role and group

**Files:**
- Modify: `accounts/admin.py`
- Test: `tests/test_invitation_group_admin.py` (new; log in a superuser with `make_verified_user` + `is_superuser=True, is_staff=True` and `client.force_login`)

**Interfaces:**
- Consumes: `CourseGroupChoiceField`, `course_group_queryset` from Task 5.

- [ ] **Step 1: Write failing tests:**
  - `test_changelist_shows_role_and_group_with_course` (response contains `f"{g.name} — {g.course.title}"`).
  - `test_changelist_query_count_flat` (same method as Task 5: warm-up GET, measure with 1 row, `bulk_create` 4 more rows with groups and inviters, measure again, equal counts).
  - `test_change_form_offers_non_archived_groups_with_course_label` (an archived group's label absent, an active one present).
  - `test_change_form_keeps_current_archived_group` (row whose group is now archived: its label is offered, and re-POSTing the form unchanged saves → 302). Build the POST from the GET: `form = resp.context["adminform"].form`; `data = {name: form[name].value() for name in form.fields}`, splitting `timezone.localtime(form["expires_at"].value())` into `expires_at_0` (date `YYYY-MM-DD`) and `expires_at_1` (time `HH:MM:SS`), and dropping `None` values. Assert the 302 and that `inv.group` is unchanged.
  - `test_admin_rejects_group_on_teacher` (POST role Teacher + group → 200 with an error, row unchanged).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement:** add `from django.utils.translation import gettext_lazy as _` to `accounts/admin.py` (lazy, so labels follow the request language). `list_display = ("email", "role", "group_display", "invited_by", "created_at", "expires_at", "accepted_at")`; `list_select_related = ("invited_by", "group__course")`; `group_display` via `@admin.display(description=_("Group"))` returning the "group — course" label or `""`; `fields` gains `"role", "group"` after `"email"`; `formfield_for_foreignkey` is not enough for "current group" — override `get_form(request, obj=None, **kwargs)`: build the form via `super()`, then set `form.base_fields["group"] = CourseGroupChoiceField(queryset=course_group_queryset(include_pk=obj.group_id if obj else None), required=False, label=_("Group"), empty_label=_("— no group —"))`.
- [ ] **Step 4: Run** the new file plus `tests/test_invitations.py` → PASS.
- [ ] **Step 5: Commit** `accounts/admin.py tests/test_invitation_group_admin.py` — `feat(invitations): admin shows role and group`.

### Task 8: Polish translations, help docs, demo seed, screenshots

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ regenerated `django.mo`), `tests/test_seed_demo_course.py`, `docs/help/platform-admin/invitations.md`, `docs/help/platform-admin/invitations.pl.md`, `courses/management/commands/seed_demo_course.py` (`_invitation`), `core/static/core/img/help/invitations.en.png`, `core/static/core/img/help/invitations.pl.png`

- [ ] **Step 1:** `uv run python manage.py makemessages -l pl` then fill Polish for: "Group" → "Grupa"; "— no group —" → "— bez grupy —"; "A group can only be given to a Student invitation." → "Grupę można przypisać tylko zaproszeniu z rolą ucznia."; "This group is archived." → "Ta grupa jest zarchiwizowana."; "(archived)" → "(zarchiwizowana)". Remove any `#, fuzzy` flags makemessages added to these entries AND check their msgstr (fuzzy pre-fills can be wrong). Revert unrelated churn makemessages made elsewhere in the `.po` if any (keep the diff to these entries + header). `uv run python manage.py compilemessages -l pl`.
- [ ] **Step 2:** Help docs: after "## Sending an invite" in `invitations.md` and after "## Wysyłanie zaproszenia" in `invitations.pl.md`, add a short paragraph saying a Student invitation can name a group; on accepting, the student joins it and sees its course on first login; archived groups aren't offered; if the group is archived before they accept, the account is still created but not added.
- [ ] **Step 3:** Seed: `_invitation` sets `group` to the "Demo Group" of the demo course if it exists (look it up by name + `self.course`), in `defaults` AND on an existing row (`update_or_create` or a follow-up save) so a re-seeded DB shows it. Add to `tests/test_seed_demo_course.py`: after running the seed twice, `Invitation.objects.get(email="invitee@demo.example").group.name == "Demo Group"` (and add that test file to Step 6's commit).
- [ ] **Step 4:** Regenerate screenshots: `uv run python -m pytest tests/capture_help_screenshots.py -p no:cacheprovider` (first time: `uv run playwright install chromium`). Then `git status`: restore every changed PNG except `invitations.en.png` / `invitations.pl.png` with `git restore <path>`. Open both PNGs and check the Group field and column are visible.
- [ ] **Step 5: Run** `tests/test_i18n*.py` (if present), `tests/test_help*.py`, and the seed's tests (`grep -l seed_demo_course tests/test_*.py | grep -v capture_`) → PASS.
- [ ] **Step 6: Commit** the listed files only — `docs(invitations): Polish strings, help and screenshots for the group field`.
