# SSO name capture, PA name editing, and a course-settings danger zone

## Purpose

Three related management/settings improvements, grouped because they all touch the
account-edit and course-edit surfaces:

1. **First/family name from SSO + PA editing.** A user's `first_name`/`last_name`
   should be populated from the OIDC identity provider on every login (so a school
   that maintains names in its IdP keeps libli in sync automatically), and a
   Platform Admin (PA) should be able to edit both names. A PA can *pin* a manually
   entered name so SSO won't overwrite it, and later hand control back to the IdP.

2. **Make deleting a course harder.** Today the course-edit page's Delete button
   renders as a normal blue "primary" button because `.btn--danger` is only defined
   in `people.css`, which is not loaded on that page. Introduce a proper, globally
   available danger style and group the destructive action into a clearly demarcated
   "Danger zone" at the bottom of the edit form.

3. **Depth-picker clarity.** Keep the structure/depth picker where it is, but add a
   short note (on edit) explaining that a level can only be removed when no content
   exists at that level — mirroring the guard already enforced in `CourseForm.clean()`.

Non-goals: no change to the course-delete cascade, the flattening guard logic, the
label-display precedence (`list_display_name` / `sort_name`), or the OIDC config UI.

## Architecture / components

### Part 1 — SSO names + PA editing

- **`accounts.models.User`** gains one field: `names_locked = BooleanField(default=False)`.
  When `True`, SSO will not overwrite `first_name`/`last_name`. One migration
  (`accounts/migrations/00XX_user_names_locked.py`). Default `False` keeps every
  existing user in sync with their IdP.

- **`accounts.provisioning.apply_sso_names(user, sociallogin)`** — new pure-ish
  helper (side effect: one `user.save(update_fields=…)` when something changed):
  - Return immediately if `user.names_locked` is `True`.
  - Read `given_name` / `family_name` from `sociallogin.account.extra_data`
    (the OIDC claims, refreshed on each login), tolerating a `None`/empty
    `extra_data`.
  - **Never overwrite with a blank:** only assign `first_name` when the incoming
    `given_name` is non-empty (after `.strip()`), likewise `last_name` from
    `family_name`.
  - Save only the fields that actually changed; no-op (no save) when nothing changed.

- **Sync on every login via allauth signals.** Register receivers in the existing
  `accounts/signals.py` for `allauth.socialaccount.signals.social_account_added`
  (first link / JIT signup) and `social_account_updated` (every subsequent login,
  which is when allauth refreshes `extra_data`). Both receivers call
  `apply_sso_names(sociallogin.account.user, sociallogin)`. Using the signals rather
  than the adapter's `pre_social_login` avoids the early-return-for-existing-user
  branch and gives one uniform sync point for new and returning users. The receivers
  must be imported/connected at app-ready time (confirm `accounts.apps` imports
  `signals`, matching the existing pattern).

- **`accounts.forms.UserEditForm`** gains:
  - `first_name` and `last_name` — `CharField(max_length=150, required=False)`,
    initialized from the instance, editable in all cases (including `editing_self`;
    only `role` is disabled when editing self).
  - `sync_name_from_sso` — `BooleanField(required=False)`, shown **only when SSO is
    configured** (`accounts.sso_config.load_sso_app() is not None`). When shown, its
    initial value is `not instance.names_locked`.
  - `save()` change: assign `first_name`/`last_name` (stripped) onto the instance. If
    the `sync_name_from_sso` field is present (SSO configured), set
    `names_locked = not cleaned["sync_name_from_sso"]`. Extend the `update_fields`
    list accordingly (`first_name`, `last_name`, and `names_locked` when applicable).
    The existing role/last-PA-admin/email-reconcile logic is unchanged.

- **Template** (`templates/accounts/…` user-edit form — the page that renders
  `UserEditForm`): add rows for `first_name`, `last_name`, and the conditional
  `sync_name_from_sso` checkbox with help text explaining it (e.g. "Keep name in
  sync with SSO; uncheck to pin a manually entered name").

### Part 2 — Danger zone + global danger button

- **Promote `.btn--danger`** (and `.btn--danger:hover`) from
  `accounts/static/accounts/css/people.css` into the global
  `core/static/core/css/app.css` (loaded by `base.html` on every page). Remove the
  now-redundant copy from `people.css`. This fixes the blue-Delete bug on the course
  page and keeps the people page working (it inherits the global rule). Uses the
  existing `--danger` design token (defined for light and dark).

- **`templates/courses/manage/course_form.html`**: on edit only, remove the Delete
  link from `form__actions` and add a `.danger-zone` section after the form with a
  heading ("Danger zone"), a one-line consequence description ("Permanently deletes
  this course and all its content, enrollments, and progress"), and the red Delete
  button linking to the existing confirm page (`courses:manage_course_delete`). The
  confirm page (`course_confirm_delete.html`) is unchanged — deletion stays two-step.
  "Open builder" stays in the main actions.

- **`.danger-zone` styling** added to `courses/static/courses/css/courses.css`
  (loaded on that page): a bordered block with a danger accent that reads as
  intentional in light and dark. Apply the **frontend-design** skill during
  implementation.

### Part 3 — Depth note

- **`courses.forms.CourseForm.__init__`**: when editing (`self.instance.pk`), append a
  translatable note to the `structure` field's `help_text`: "Removing a level is only
  possible when no content exists at that level — move or delete that content first."
  Rendered by the existing per-field template loop (help_text is output with `|safe`),
  so no template change is required.

## Data flow

**SSO login (returning user):** IdP → allauth OIDC callback → allauth refreshes the
`SocialAccount.extra_data` and emits `social_account_updated` → receiver calls
`apply_sso_names` → if not `names_locked`, non-blank `given_name`/`family_name` claims
are written to `first_name`/`last_name` → next roster/list render shows the fresh
"First Last" via the unchanged `list_display_name`.

**PA edits a name:** PA opens the user-edit page → edits `first_name`/`last_name`,
optionally unchecks "Keep name in sync with SSO" → `UserEditForm.save()` writes the
names and sets `names_locked = True` → on that user's next SSO login `apply_sso_names`
sees `names_locked` and leaves the names untouched. Re-checking the box on a later
edit sets `names_locked = False`, so the following login re-syncs from the IdP.

**Course delete:** PA opens course-edit → sees the Danger zone → clicks red Delete →
existing confirm page shows cascade counts → confirms → `course_delete` view runs the
unchanged cascade.

## Error handling

- `apply_sso_names` is defensive: tolerates `extra_data` being `None` or missing the
  claim keys, strips whitespace, and never writes an empty string over an existing
  name. It performs at most one `save(update_fields=…)` and only when a value changed.
- The lock check happens first, so a locked user is never modified regardless of claims.
- `UserEditForm` keeps its existing validation (email uniqueness/verified-elsewhere
  guard, last-active-PA demotion guard under `select_for_update`, self-edit role
  disable). The new name fields are optional and free-text (max 150), matching
  `display_name`.
- When SSO is not configured, the `sync_name_from_sso` field is absent and
  `names_locked` is left unchanged by `save()` (stays at its default `False`).
- Course deletion is unchanged: still gated by `courses.delete_course` permission and
  the two-step confirm page.

## Testing

Unit / view tests (pytest, run with `uv run`):

- **`apply_sso_names`**: (a) locked user is never modified; (b) unlocked user gets
  `first_name`/`last_name` from claims; (c) blank/missing claims never overwrite an
  existing name; (d) no-op (no save) when claims match current values; (e) tolerates
  `extra_data = None`.
- **Signal wiring**: `social_account_added` and `social_account_updated` both invoke
  the sync (assert names populated for an unlocked user; untouched for a locked one).
- **`UserEditForm`**: saves `first_name`/`last_name`; unchecking `sync_name_from_sso`
  sets `names_locked=True`, checking it sets `False`; the checkbox is absent when SSO
  is not configured and present when it is; names are editable when `editing_self`.
- **Course-edit template**: Delete button carries `btn--danger` and lives in a
  `.danger-zone` block on edit; neither appears in create mode; `app.css` contains the
  `.btn--danger` rule (surface/CSS presence check in the spirit of `test_surfaces.py`).
- **Depth note**: the flattening note appears in the edit form's rendered
  `structure` help text and not in the create form.

E2E is intentionally minimal here (no new interactive gesture beyond a styled link);
follow the project lesson of running focused tests foreground rather than a broad e2e
sweep. Full-suite green is the definition of done, including the i18n catalog checks
if any translatable strings are added/removed.
