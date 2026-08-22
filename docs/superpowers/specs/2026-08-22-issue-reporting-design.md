# Issue reporting

## Purpose

Give selected users a way to report a problem from the page where they hit it, and
get that report — with the description, a screenshot and enough telemetry to act on
it — in front of a Platform Admin.

Today a student who hits a broken lesson page has no route to the people who run the
platform, and a Platform Admin who is told "it looks wrong on my laptop" has no way to
find out which page, which browser, or which window size. This feature closes both
halves of that gap.

The Platform Admin (PA) decides who may report, using a nested audience ladder plus an
explicit list of individually granted people. PAs can always report, regardless of the
ladder.

### Decisions taken during design, and why

These were settled with the user during brainstorming. They are recorded here so the
implementation does not silently re-litigate them.

| Decision | Rationale |
|---|---|
| Reports are **stored in the database and emailed**, not emailed only | Production SMTP is opt-in in this repo (`DJANGO_EMAIL_HOST` unset falls back to the console backend, `config/settings/production.py:30-39`). Email-only would tell the reporter "sent" while the report was written to a log and lost. The row is the source of truth; email is a notification on top. |
| Audience is a **nested ladder plus an additive extras list** | Matches how the audiences actually nest. One radio group and one picker, instead of independent role toggles that can express incoherent combinations. |
| A fourth **"Platform Admins only"** rung exists | Lets the feature be effectively off without a separate on/off switch, and is the safe default on upgrade. |
| **No categories** on the form | The user could not yet name a taxonomy. A taxonomy invented before reading real reports is one people mis-file. Adding a field later is a trivial migration; removing a field people have used is not. |
| The form is a **dialog on the current page**, with no no-JS fallback | Capturing the URL, viewport and screen of the page being complained about is the point; a separate page would describe itself instead. No-JS parity is not lowered by this: the account menu that hosts the trigger is already a `<button data-menu-trigger>` over a `hidden` panel (`templates/base.html`), so a JS-less visitor cannot open that menu today either. |
| **One optional screenshot**, user-chosen, never auto-captured | This repo is vanilla JS with no build step. `html2canvas` is a large dependency that re-renders the DOM and can disagree with what the user saw; `getDisplayMedia` raises its own permission prompt and captures the whole screen. A file the user picked is cheaper and more truthful. |
| Screenshots are stored **outside `MEDIA_ROOT`** and served by a PA-only view | `/media/` is served by nginx/CDN in production and by `serve_media` under DEBUG; neither checks login. A screenshot can contain another student's name, answers or grades. `TRANSFER_STAGING_DIR` (`config/settings/base.py:181`) is the existing precedent for "must never be web-served". |
| The screenshot is **attached to the email**, not linked | `extra_emails` may be a helpdesk alias with no libli account, for which a login-walled link is useless. |
| A **fixed** per-user rate limit, not a configurable one | The top rung of the ladder is "Everyone". One frustrated student on a broken page can otherwise fill an inbox in a minute. A configurable number is a field to explain, migrate and test for a value nobody will change. |
| Triage is a **list plus detail plus open/resolved**, not Django admin | This product deliberately does not send PAs to `/admin/`, and the telemetry renders there as an unreadable JSON blob. Without a status the list becomes undifferentiated within a month. |

### Out of scope

Each is a small addition later; none is free now, and none is needed for the feature to
be useful:

- Categories or tags on a report.
- A reporter-facing history of their own reports.
- A confirmation email to the reporter.
- Comment threads or replies on a report inside the app.
- Per-user **exclusions** (revoking someone the ladder admits).
- A configurable throttle limit.
- More than one screenshot per report.
- An unread-count badge in the nav (a query on every request for a number nobody waits
  on).

## Architecture

### A new `support` app

A new Django app, `support/`, added to `INSTALLED_APPS` in `config/settings/base.py`
after `integrations`. The repo is organised app-per-domain (`notifications`,
`integrations`, `notes`, `tags`) and this is a domain of its own: policy, model, form,
delivery and triage. Nothing about it belongs in `core` or `institution`.

```
support/
    __init__.py
    apps.py                 # ready(): connect the cache-invalidation signals
    models.py               # SupportSettings, IssueReport
    policy.py               # can_report(user) + the cached audience bundle
    storage.py              # private screenshot storage (callable, see below)
    forms.py                # SupportSettingsForm, IssueReportForm
    emails.py               # send_issue_report_email(report)
    views.py                # report_create (the dialog POST target)
    views_manage.py         # report_list, report_detail, report_resolve, screenshot
    urls.py
    migrations/
    templates/support/...
    static/support/js/report_dialog.js
    static/support/css/support.css
    tests/
```

### Models (`support/models.py`)

**`SupportSettings`** — a single-row (pk=1) configuration model with `save()` forcing
`self.pk = 1` and a `load()` classmethod, modelled directly on
`integrations.WebhookEndpoint` (`integrations/models.py:7-25`), **including its
discipline that reads on the render hot path go through `objects.filter(pk=1).first()`,
never `load()`**. `load()`'s `get_or_create` would write a row during a plain GET;
`institution/views_manage.py:_settings_context` already documents this exact trap for
`WebhookEndpoint`.

| Field | Type | Notes |
|---|---|---|
| `audience` | `CharField(max_length=16, choices=Audience.choices, default=Audience.ADMINS)` | The ladder |
| `extra_reporters` | `ManyToManyField(AUTH_USER_MODEL, blank=True, related_name="+")` | Individually granted people |
| `extra_emails` | `JSONField(default=list, blank=True)` | Extra recipient addresses |
| `updated_at` | `DateTimeField(auto_now=True)` | |

```python
class Audience(models.TextChoices):
    ADMINS = "admins", _("Platform Admins only")
    COURSE_ADMINS = "course_admins", _("Course Admins and Platform Admins")
    TEACHERS = "teachers", _("Teachers, Course Admins and Platform Admins")
    ALL = "all", _("Everyone, including students")
```

The rung labels name **everyone they admit**, not just the rung's own role, so the PA
never has to infer that the ladder is cumulative.

**`IssueReport`** — one row per submission.

| Field | Type | Notes |
|---|---|---|
| `reporter` | `FK(AUTH_USER_MODEL, null=True, on_delete=SET_NULL, related_name="issue_reports")` | |
| `reporter_label` | `CharField(max_length=200)` | Denormalised `"Display Name (username) <email>"` |
| `reporter_roles` | `CharField(max_length=200)` | Comma-joined **Group names** (storage keys, e.g. `Teacher`), never translated labels |
| `description` | `TextField()` | Required; `DESCRIPTION_MAX_LENGTH = 4000` enforced in the form |
| `page_url` | `TextField(blank=True)` | Untrusted; stored as text, never as a `URLField` |
| `page_title` | `CharField(max_length=300, blank=True)` | Untrusted |
| `screenshot` | `ImageField(blank=True, storage=..., upload_to=...)` | Optional; see "Screenshot storage" |
| `telemetry` | `JSONField(default=dict, blank=True)` | Sanitised client and server facts |
| `created_at` | `DateTimeField(auto_now_add=True)` | |
| `status` | `CharField(choices=Status.choices, default=Status.OPEN)` | `open` / `resolved` |
| `resolved_at` | `DateTimeField(null=True, blank=True)` | |
| `resolved_by` | `FK(AUTH_USER_MODEL, null=True, on_delete=SET_NULL, related_name="+")` | |
| `emailed_at` | `DateTimeField(null=True, blank=True)` | Null means the mail never went out |

`Meta.ordering = ["-created_at"]` plus an index on `("status", "-created_at")` — the
triage list always filters on status and orders by recency.

`reporter_label` and `reporter_roles` are **denormalised on purpose**. This repo hard-
deletes and keeps no orphan audit rows; a report whose provenance evaporates with the
account tells the PA nothing. `reporter` remains a FK so a live account still links.

Roles are stored as Group **names**, not `ROLE_LABELS` values: `institution/roles.py` is
explicit that the Group name is the storage key and `ROLE_LABELS` is display-only. The
triage template renders the stored names through `ROLE_LABELS`.

### Screenshot storage (`support/storage.py`)

```python
SUPPORT_SCREENSHOT_DIR = BASE_DIR / "support_screenshots"   # config/settings/base.py
```

Declared beside `TRANSFER_STAGING_DIR` and carrying the same kind of comment: **not
under `MEDIA_ROOT`, because these must never be web-served.**

`support/storage.py` exposes a **callable**, not a module-level storage instance:

```python
def screenshot_storage():
    return FileSystemStorage(location=settings.SUPPORT_SCREENSHOT_DIR)
```

used as `ImageField(storage=screenshot_storage, ...)`. This is load-bearing:
`FileSystemStorage` is deconstructible, so passing an *instance* would freeze this
machine's absolute `location` into the migration file. Django accepts a callable for
`storage=` and serialises the callable reference instead.

`upload_to` is a function producing `screenshots/<YYYY>/<MM>/<uuid4>.<ext>`, so the
filename never derives from user-supplied text.

The file is validated by the **existing** `courses.validators.validate_image_file`,
which already applies `Institution.allowed_image_extensions` and `max_image_mib`
(ceiling 5 MiB). No new upload settings are introduced.

`post_delete` on `IssueReport` deletes the file. Django does not do this on its own, and
orphaned screenshots of student data accumulating on disk is exactly the failure mode to
avoid.

### Audience policy (`support/policy.py`)

`can_report(user) -> bool` is the single source of truth, evaluated in order:

1. Anonymous or inactive -> `False`.
2. Platform Admin -> `True`, unconditionally, whatever the ladder says.
3. The user's role Group names intersect the tier's admitted set -> `True`.
   (`admins` admits nothing extra; `course_admins` adds Course Admin; `teachers` adds
   Teacher; `all` adds Student.)
4. `user.id` is in the extras set -> `True`.
5. Otherwise `False`.

This runs on **every authenticated page render** (the context processor below feeds
`base.html`), so it must not cost queries per request. It reads a cached bundle
`{"audience": str, "extra_reporter_ids": frozenset[int]}` built by
`get_support_config()` and dropped by `invalidate_support_config()`, following the
`get_site_config` / `invalidate_site_config` pattern at `core/services.py:102-113`.

Invalidation must be connected to **both**:

- `post_save` on `SupportSettings`, and
- `m2m_changed` on `SupportSettings.extra_reporters.through`.

The `m2m_changed` receiver is the one that is easy to omit, and omitting it means a
newly-granted teacher cannot report until the cache TTL expires — a bug that looks like
"the setting didn't save".

### PA settings tab

A seventh tab, **Support**, on the existing settings page:

- `institution/views_manage.py`: add `"support"` to `TABS`, add a `settings_support`
  view, and build the form in `_settings_context` on every render from a **read-only**
  `SupportSettings.objects.filter(pk=1).first() or SupportSettings()` — never `load()` —
  exactly as the integrations panel already does.
- `institution/urls.py`: `manage/settings/support/` -> `institution:settings_support`.
- The form itself lives in `support/forms.py` as `SupportSettingsForm` and is imported by
  the institution view, the same direction as `IntegrationsForm` today.

Three controls:

1. **Who can report** — a radio group of the four rungs.
2. **Also allow these people** — the roster-picker pattern from
   `templates/grouping/group_form.html`: a searchable (`data-roster-search`) checkbox
   list of active non-PA users, filtered client-side. No new interaction is invented.
3. **Send reports to** — a textarea, one address per line, each validated with Django's
   `EmailValidator`; blank lines ignored; stored as a JSON list.

Above control 3, a read-only line names the Platform Admins who will be mailed
automatically, so "who gets this" is never a guess.

### Reporter surface

- `core/context_processors.py` gains `support_availability(request)` returning
  `{"can_report_issue": ...}` — the same shape as the existing `help_availability` —
  registered in `TEMPLATES["OPTIONS"]["context_processors"]` beside it.
- `templates/base.html`: the account menu gains a **Report an issue** item behind
  `{% if can_report_issue %}`, and includes `support/_report_dialog.html` once, also
  behind that flag.
- `support/static/support/js/report_dialog.js` opens the dialog, populates the hidden
  telemetry fields, handles paste-to-attach, posts `FormData` via `fetch`, and renders
  field errors back inside the dialog.
- The `<dialog>` needs **explicit theming**: in this codebase a `<dialog>` does not
  inherit the page theme, so its colours must be set from the theme tokens rather than
  inherited.

**Paste to attach.** A `paste` listener on the dialog reads an image out of
`event.clipboardData.items` and assigns it to the file input via a `DataTransfer`. On
Windows this makes the whole flow `Win+Shift+S`, open the dialog, `Ctrl+V`, type, send.
The `<input type="file">` remains, both as the fallback and as the control that shows
what is attached. This is the difference between a screenshot field people use and one
they skip.

### Triage surface

`support/views_manage.py`:

- `report_list` — paginated (`Paginator`, as in `accounts/views_manage.py`), newest
  first, with an open/resolved filter. Columns: created, reporter, role, first line of
  the description, a screenshot indicator, status.
- `report_detail` — the description, the telemetry rendered as **labelled rows, not a
  JSON blob**, the screenshot thumbnail, and a *Mark resolved* form.
- `report_resolve` — POST only; sets `status`, `resolved_at`, `resolved_by`.
- `screenshot` — `FileResponse` for the private file.

Reached from an **Issue reports** item in the Admin menu in `base.html`, beside
"Institution settings".

Access is a real permission, not a role-name check: `support.view_issuereport` and
`support.change_issuereport` are appended to `PLATFORM_ADMIN_PERMS` in
`institution/roles.py`, and the views use `permission_required`.

## Data flow

### Submitting a report

1. The user opens the account menu and clicks **Report an issue**. The dialog opens on
   the current page; nothing navigates.
2. `report_dialog.js` fills hidden fields: `page_url` (`location.href`), `page_title`
   (`document.title`), `viewport_w`/`viewport_h` (`innerWidth`/`innerHeight`),
   `screen_w`/`screen_h` (`screen.width`/`screen.height`), `dpr` (`devicePixelRatio`),
   `timezone` (`Intl.DateTimeFormat().resolvedOptions().timeZone`), `theme`
   (`documentElement.dataset.theme`), `ui_language` (`<html lang>`).
3. The user types a description and optionally pastes or picks a screenshot. A
   collapsible **"What will be sent"** block shows the collected values verbatim, so
   nothing is gathered behind the user's back.
4. `POST` `multipart/form-data` to `support:report_create`.
5. The view: `@login_required`, then **re-checks `can_report(request.user)` and 403s
   otherwise**, then the throttle, then `IssueReportForm` validation.
6. On success the row is saved with the sanitised telemetry and the role snapshot, and
   the email is queued with `transaction.on_commit`.
7. The response is JSON; the dialog shows a confirmation and closes. Field errors come
   back as JSON and render inside the dialog.

### Telemetry assembly and sanitisation

Everything in step 2 is **client-supplied and therefore untrusted**. The view builds the
stored `telemetry` dict itself:

- It reads only a **fixed allow-list of keys**; unknown keys are dropped.
- Every string value is truncated to a per-key cap before storage.
- Numeric values are coerced with a bounded fallback; a non-numeric viewport is dropped,
  never stored raw.
- Server-derived facts — `user_agent` (`HTTP_USER_AGENT`), `accept_language`
  (`HTTP_ACCEPT_LANGUAGE`), the role snapshot and the timestamp — are taken from
  `request` and from the database, never from the payload. Where a server fact and a
  client claim overlap, the server fact wins.
- **No IP address is collected.** This is a platform with student accounts; the
  diagnostic value does not justify the personal-data question.

`page_url` is the sharp edge. It is stored as text, rendered escaped everywhere, and in
the triage template is turned into a link **only if it parses to this site's own
origin**; otherwise it prints as inert text. A `javascript:` value must never reach an
`href`.

### Audience resolution

`can_report` calls `get_support_config()`, which either hits the cache or runs one query
for the settings row plus one for the extras ids and caches the bundle. A settings save
or an `extra_reporters` change drops the cache, so a grant takes effect on the next
request.

### Email delivery

`support/emails.py`, built like `notifications/emails.py`: `EmailMultiAlternatives` with
a plain-text body and an HTML alternative rendered by `render_to_string`, inside
`translation.override(...)` with **eager `gettext`** (not `gettext_lazy`) so
interpolation resolves inside the override block — the same rule that module already
documents.

- **Language:** the institution default (`get_site_config()["default_language"]`), not
  the reporter's. One message goes to every recipient, so it can only have one language.
- **Recipients:** every **active** Platform Admin with a non-empty email address, unioned
  with `extra_emails`, de-duplicated case-insensitively.
- **`reply_to`:** the reporter's address when they have one, so a PA can simply reply.
- **Subject:** institution name plus reporter display name, with **whitespace collapsed**
  — a display name containing a newline would otherwise split the header.
- **Body:** description, reporter, roles, page URL, and the telemetry as a labelled list.
  The screenshot is **attached** (capped at 5 MiB by the upload validator).
- **Ordering:** the row is committed first; the send runs in `transaction.on_commit`
  inside `try`/`except`. Success sets `emailed_at`; failure logs and leaves it null. With
  SMTP unconfigured the report still exists and the PA still sees it — the entire reason
  storage was chosen over email-only.

### Triage

The PA opens **Issue reports**, filters to open, opens one, reads the telemetry and the
screenshot, acts, and marks it resolved. `resolved_by` and `resolved_at` record who and
when.

## Error handling

| Situation | Behaviour |
|---|---|
| A user who may not report POSTs to `support:report_create` | **403.** The menu item being hidden is not access control, and the ladder's top rung is "Everyone" — this gate *is* the feature. |
| Anonymous POST | `@login_required` redirect. |
| Empty or whitespace-only description | Form error rendered inside the dialog; no row, no mail. |
| Description over `DESCRIPTION_MAX_LENGTH` | Form error; the dialog also shows a live character counter so this is rare. |
| Screenshot too large, or a disallowed or non-image extension | `validate_image_file` error rendered inside the dialog; the description the user typed is preserved. |
| 6th report from one user within an hour | Refused with a polite message ("you have sent a few already — please try again later"), **no row written and no mail sent**. Counted from the stored rows; no new state. |
| SMTP unconfigured, or the send raises | The report row survives; `emailed_at` stays null; the failure is logged. The reporter is still told the report was received, because it was. |
| No resolvable recipients (no PA has an email and `extra_emails` is empty) | The row is still written; nothing is sent; a warning is logged. The triage list is the safety net. |
| Hostile telemetry (`page_url` of `javascript:...`, over-long strings, unknown keys) | Dropped, truncated, or stored as inert escaped text; never emitted into an `href`. |
| A non-PA requests a screenshot URL | **403** from `permission_required`. |
| A report is deleted | `post_delete` removes the screenshot file from disk. |
| The `SupportSettings` row does not exist yet | Every read path uses `filter(pk=1).first() or SupportSettings()`, so the defaults apply and no row is written on a GET. |

## Testing

Following this repo's practice, **each test is paired with the mutant that must turn it
RED** — a test that cannot fail on a broken build is not evidence.

| Test | Mutant that must break it |
|---|---|
| `can_report` matrix: 4 tiers by 4 roles, plus extras and anonymous | Drop the "Platform Admin always" rule |
| **A Student POSTs `report_create` while the tier is `course_admins` -> 403** | Delete the server-side `can_report` gate from the view |
| A user added to `extra_reporters` can report on the very next request | Remove the `m2m_changed` cache-invalidation receiver |
| Changing `audience` takes effect on the next request | Remove the `post_save` receiver |
| 6th report within an hour -> refused, no row, no mail | Raise the limit |
| Recipients = active PAs with an email, unioned with `extra_emails`, de-duplicated | Drop `extra_emails` from the recipient union |
| A PA with no email address is not a recipient, and does not break the send | Remove the non-empty-email filter |
| The screenshot is attached to the outgoing message | Drop the attachment |
| `emailed_at` is set on success | Never set it |
| **A send that raises still leaves the report row** | Move the send out of `on_commit`, or out of the `try` |
| A Teacher GETting the screenshot view -> 403 | Drop `permission_required` |
| A screenshot is written outside `MEDIA_ROOT` | Point the storage at `MEDIA_ROOT` |
| Deleting a report deletes its file | Remove the `post_delete` receiver |
| `page_url` of `javascript:alert(1)` renders escaped and never as an `href` | Link `page_url` unconditionally |
| Unknown telemetry keys are dropped; over-long values truncated | Store the payload verbatim |
| `reporter_label` survives deletion of the reporting account | Read the label through the FK instead of the snapshot |
| The settings form rejects a malformed address in `extra_emails` | Drop the `EmailValidator` |
| A GET of any other settings tab writes no `SupportSettings` row | Use `load()` instead of `filter(pk=1).first()` |

**e2e (Playwright).** Open the dialog from the account menu, paste an image from the
clipboard, submit, and assert both the stored row and the confirmation. Per this repo's
e2e practice: drive the real UI rather than posting directly, synchronise on conditions
rather than sleeps, and take **light and dark** screenshots — a `<dialog>` in dark mode
needs `user.theme` set on the user, because the theme cookie does not reach it.

**i18n.** All model, form and template strings use `gettext_lazy`; the email module uses
eager `gettext` inside its `translation.override(...)` block. Message catalogs are
regenerated and Polish translations supplied.

## Visual design

The new views — the report dialog, the Support settings tab, and the triage list and
detail — are built to match the existing design language (token-driven CSS, no
Bootstrap, monochrome SVG icons using `currentColor`, never emoji). The
`frontend-design` skill is applied to these views as a final pass, after the behaviour
is complete and tested, so the visual work happens once against finished markup. Every
new view ships styled in **both** light and dark themes.

## Deployment note

`support.view_issuereport` and `support.change_issuereport` are new permissions attached
to the Platform Admin group. **`setup_roles` must be run after `migrate`** on deploy, or
the permissions exist but are attached to nobody and the triage pages 403 for everyone.
No test catches this — it is a deployment-ordering property, and it belongs in the
release checklist.

`SUPPORT_SCREENSHOT_DIR` must exist and be writable by the application user, and — like
`transfer_staging` — must **not** be exposed by the web server.
