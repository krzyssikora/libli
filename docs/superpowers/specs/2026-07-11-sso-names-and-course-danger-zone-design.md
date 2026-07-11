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
   falls back to the base `.btn` appearance (the markup is `btn btn--danger`, with no
   `btn--primary`) because `.btn--danger` is only defined in `people.css`, which is not
   loaded on that page — so it never reads as destructive. Introduce a proper, globally
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
  (`accounts/migrations/0006_user_names_locked.py` — the latest accounts migration is
  `0005_user_external_id.py`). Default `False` keeps every
  existing user in sync with their IdP. (Edge: an existing SSO user whose
  `first_name`/`last_name` were set out-of-band — e.g. via the Django admin — will have
  them overwritten on the next login under this default; accepted, since no prior libli
  UI populated these fields.)

- **`accounts.provisioning.apply_sso_names(user, sociallogin)`** — new pure-ish
  helper (side effect: one `user.save(update_fields=…)` when something changed):
  - Return immediately if `user.names_locked` is `True`.
  - **Read the claims through the provider's unwrap, NOT flat off `extra_data`.** For the
    `openid_connect` provider this repo uses, `extra_data` is nested —
    `{"userinfo": {…}, "id_token": {…}}` (built by
    `OpenIDConnectOAuth2Adapter.complete_login`) — so a literal
    `extra_data.get("given_name")` is **always `None`** and the sync would silently
    no-op in production. Unwrap first, mirroring the provider's `_pick_data`: take the
    first present of `extra_data["userinfo"]`, `extra_data["id_token"]`, else `extra_data`
    itself, then read `given_name` / `family_name` from that dict. Concretely, a small
    inline helper — `_claims(extra_data)` returning
    `extra_data.get("userinfo") or extra_data.get("id_token") or extra_data or {}` — is
    sufficient and unit-testable; the provider's own
    `get_provider_account().get_user_data()` / `extract_common_fields()` are equivalent
    routes. Tolerate a `None`/empty `extra_data` (→ `{}`).
  - **Never overwrite with a blank:** only assign `first_name` when the incoming
    `given_name` is non-empty (after `.strip()`), likewise `last_name` from
    `family_name`.
  - **Partial claims / `name`-only IdPs (scope boundary):** `first_name` and
    `last_name` are synced independently from `given_name` and `family_name`. An IdP
    that sends only one structured claim updates only that field; an IdP that sends
    neither (e.g. only the combined OIDC `name` claim) leaves both untouched — splitting
    a combined `name` claim is out of scope. Because the unchanged
    `list_display_name`/`sort_name` render "First Last" only when **both** fields are set
    (else they fall back to `display_name`/`username`), rosters reflect the synced names
    only for IdPs that provide both `given_name` and `family_name`. This is a documented
    limitation, not a silent failure.
  - Save only the fields that actually changed; no-op (no save) when nothing changed.

- **Sync names across the three login paths.** Name population is covered by three
  mechanisms, one per login path (verified against allauth 65.18.0):
  - **Net-new SSO user (JIT signup):** allauth's built-in
    `SocialAccountAdapter.populate_user` maps the OIDC `given_name`/`family_name` claims
    onto `first_name`/`last_name` at account creation (the repo does **not** override it,
    and this is the source of the existing `models.py` "populated for SSO users via
    allauth's default … mapping" comment). `social_account_added` does **not** fire on
    this path — it is emitted only from `SocialLogin.connect()` — so no custom receiver
    runs here. populate_user is sufficient and is not `names_locked`-gated, which is
    harmless because `names_locked` is `False` at creation.
  - **Link an existing local user by email (first SSO login of an admin-created
    account):** the adapter's `sociallogin.connect(...)` path (`accounts/adapters.py`)
    emits `social_account_added`; a receiver on that signal calls `apply_sso_names`, so a
    linked user's names populate on that first login (populate_user does not run for an
    already-existing user).
  - **Returning login (any user, 2nd+ login):** allauth refreshes
    `SocialAccount.extra_data` and emits `social_account_updated`; a receiver on that
    signal calls `apply_sso_names`.

  Register the two receivers in the existing `accounts/signals.py` for
  `allauth.socialaccount.signals.social_account_added` and `social_account_updated`. Both
  allauth signals deliver `(sender, request, sociallogin, **kwargs)`; the receivers use
  that exact signature (e.g.
  `def _sync_sso_names(sender, request, sociallogin, **kwargs):`) and call
  `apply_sso_names(sociallogin.account.user, sociallogin)`. Using signals rather than the
  adapter's `pre_social_login` avoids the early-return-for-existing-user branch. The
  receivers must be imported/connected at app-ready time (confirm `accounts.apps` imports
  `signals`, matching the existing pattern).

- **`accounts.forms.UserEditForm`** gains:
  - `first_name` and `last_name` — `CharField(max_length=150, required=False)`,
    initialized from the instance, editable in all cases (including `editing_self`;
    only `role` is disabled when editing self).
  - `sync_name_from_sso` — `BooleanField(required=False)`, shown **only when an SSO app
    is configured** — gated on `accounts.sso_config.load_sso_app() is not None`. This is
    deliberately the *configured* check, not `sso_config.is_enabled(app, site)`: a
    temporarily-disabled-but-configured SSO should still expose the lock control, since
    sync resumes when it is re-enabled. When shown, its initial value is
    `not instance.names_locked`. **Single mechanism — field presence:** the field is
    conditionally *added to `self.fields` in `__init__`* only when
    `load_sso_app() is not None`, and omitted otherwise (either don't add it, or
    `del self.fields["sync_name_from_sso"]`). Field presence then drives everything
    consistently and there is **no separate view flag**: the template's
    `{% if form.sync_name_from_sso %}` guard is truthy iff the field is in `form.fields`,
    and `save()` keys off `"sync_name_from_sso" in self.cleaned_data`.
  - `save()` change: assign `first_name`/`last_name` (stripped) onto the instance. If
    `"sync_name_from_sso" in self.cleaned_data` (i.e. the field was added → SSO
    configured), set `names_locked = not cleaned["sync_name_from_sso"]`. Extend the
    `update_fields` list accordingly (`first_name`, `last_name`, and `names_locked` when
    applicable). The existing role/last-PA-admin/email-reconcile logic is unchanged.

- **Template `templates/accounts/manage/user_form.html`** (renders `UserEditForm`):
  this template renders each field by hand as a `.manage__field` row
  (`<label class="manage__field">…</label>`), not via a field loop, and does not
  currently emit `help_text` for most fields. Add `.manage__field` rows for `first_name`
  and `last_name`, and a `{% if form.sync_name_from_sso %}`-guarded row for the checkbox
  with a `<small>` help text explaining it (e.g. "Keep name in sync with SSO; uncheck to
  pin a manually entered name"). All new strings are `{% trans %}`-wrapped.

### Part 2 — Danger zone + global danger button

- **Promote `.btn--danger`** (and `.btn--danger:hover`) from
  `accounts/static/accounts/css/people.css` into the global
  `core/static/core/css/app.css` (loaded by `base.html` on every page). Place the rules
  **after** the base `.btn` rule (they are equal single-class specificity, so source
  order decides — e.g. adjacent to `.btn--primary`), so `background: var(--danger)`
  overrides the base `background: var(--primary)`. **Cover the hover/active states too:**
  app.css has `.btn:hover { background: var(--primary-hover); }` and
  `.btn:active { background: var(--primary-active); }` at specificity (0,2,0), which beat
  a bare `.btn--danger` (0,1,0) — and the current `people.css` `.btn--danger:hover` sets
  only `filter: brightness(0.92)`, no background. Promoting it as-is would leave the
  Delete button red at rest but **primary-blue on hover/active**. The promoted rules must
  set the danger background in the hover and active states as well (e.g.
  `.btn--danger:hover, .btn--danger:active { background: var(--danger); filter: brightness(0.92); }`)
  so it stays red in every state. Remove the now-redundant copy from `people.css`
  **together with its accompanying `--danger`-token explanatory comment block** (which
  only makes sense next to the moved rule). This fixes the blue-Delete bug on the course
  page and keeps the people page working (it inherits the global rule). Uses the
  existing `--danger` design token (defined for light and dark). The same promotion also
  gives correct danger styling to the other templates that already reference
  `.btn--danger` without loading `people.css` — `course_confirm_delete.html`,
  `node_confirm_delete.html`, `notes/confirm_delete.html`, and `tags/delete_confirm.html`
  — an intended side effect (verify these paths during implementation).

- **`templates/courses/manage/course_form.html`**: on edit only — inside the existing
  `{% if not creating %}` branch that already wraps the Delete/Open-builder links —
  remove the Delete link from `form__actions` and add a `.danger-zone` section after the
  form with a
  heading ("Danger zone"), a one-line consequence description ("Permanently deletes
  this course and all its content, enrollments, and progress"), and the red Delete
  button linking to the existing confirm page (`courses:manage_course_delete`). The
  confirm page (`course_confirm_delete.html`) is unchanged — deletion stays two-step.
  "Open builder" stays in the main actions. All new user-facing strings here (the
  heading, the consequence line) are `{% trans %}`-wrapped and added to the EN + PL
  catalogs, matching the existing template convention.

- **`.danger-zone` styling** added to `courses/static/courses/css/courses.css`
  (loaded on that page): a bordered block with a danger accent that reads as
  intentional in light and dark. Apply the **frontend-design** skill during
  implementation.

### Part 3 — Depth note

- **`courses.forms.CourseForm.__init__`**: when editing (`self.instance.pk`), append a
  translatable note to the `structure` field's `help_text`. **Ordering is load-bearing:**
  the existing `__init__` has a branch that *replaces* `structure.help_text` entirely for
  a Custom course (`current is None` → `"Custom: %(chain)s (keeps current structure)."`),
  so the append must run **after** that branch and concatenate onto whatever help_text is
  then current — that way both the base/Custom message and the note survive for Custom
  courses. Format: join as a separate sentence with a leading space
  (`self.fields["structure"].help_text = f"{help_text} {note}"`). The note text (wrapped
  in `gettext`): "Removing a level is only possible when no content exists at that level —
  move or delete that content first." It is shown on every edit (including Flat courses,
  where it is harmless forward-looking context) and not shown when creating. Rendered by
  the existing per-field template loop (help_text is output with `|safe`), so no template
  change is required.

## Data flow

**SSO login (net-new user, first login):** IdP → allauth OIDC callback → no matching
local user → allauth's `populate_user` sets `first_name`/`last_name` from the
`given_name`/`family_name` claims as the account is created (`save_user`). No custom
receiver runs (`social_account_added` is not emitted on this path). `apply_sso_names`
takes over from the user's next login via `social_account_updated`.

**SSO login (existing local account, first SSO login — link-by-email):** IdP → callback →
adapter resolves an existing local user by verified email → `sociallogin.connect(...)`
emits `social_account_added` → receiver calls `apply_sso_names` → if not `names_locked`,
non-blank claims are written to `first_name`/`last_name`.

**SSO login (returning user):** IdP → allauth OIDC callback → allauth refreshes the
`SocialAccount.extra_data` and emits `social_account_updated` → receiver calls
`apply_sso_names` → if not `names_locked`, non-blank `given_name`/`family_name` claims
are written to `first_name`/`last_name` → next roster/list render shows the fresh
"First Last" via the unchanged `list_display_name` (when both fields are set).

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
  `extra_data = None`; (f) a partial claim set (only `given_name`, or only
  `family_name`) updates just that one field and leaves the other unchanged.
  **Fixture shape is load-bearing:** all `apply_sso_names` fixtures (and the mocked IdP
  response in the signal tests) must use the real *nested* `extra_data` shape —
  `{"userinfo": {"given_name": …, "family_name": …}}` (or under `id_token`) — never a
  flat `{"given_name": …}`, so that a top-level-only read (the C1 bug) fails the test
  rather than passing against a buggy implementation.
- **Signal wiring** (test each signal via its real trigger, not a manual `.send()` —
  per the project's "drive the real gesture" lesson): test `social_account_added` by
  exercising the **link-existing-local-user-by-email** path (which calls
  `sociallogin.connect()`), asserting an unlocked linked user's names populate and a
  locked one's do not; test `social_account_updated` via a **returning login**, same
  assertions. Do not assert `social_account_added` fires on a JIT (net-new) signup — it
  does not; that path's names come from allauth's `populate_user` and can be covered by a
  net-new-signup test asserting the names land at creation.
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
