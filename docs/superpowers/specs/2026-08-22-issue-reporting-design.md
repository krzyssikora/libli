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
| The extras picker lives on **its own page**, not inside the settings tab | `institution/views_manage.py:_settings_context` renders *every* settings panel on every settings render, hiding the inactive ones. A roster checkbox list inside the Support panel would therefore materialise one row per active user on every GET of the Branding tab. The cited precedent (`templates/grouping/group_form.html`) is a dedicated page, and this follows it properly. |

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
- **Automatic retention/expiry of reports.** Reports and their screenshots are kept
  indefinitely until a PA deletes them; deletion is a manual PA action (see "Triage
  surface"). A `TRANSFER_STAGING_MAX_AGE_HOURS`-style sweep is deliberately deferred
  until there is evidence of volume.

## Architecture

### A new `support` app

A new Django app, `support/`, added to `INSTALLED_APPS` in `config/settings/base.py`
after `integrations`. The repo is organised app-per-domain (`notifications`,
`integrations`, `notes`, `tags`) and this is a domain of its own: policy, model, form,
delivery and triage. Nothing about it belongs in `core` or `institution`.

```
support/
    __init__.py
    apps.py                 # ready(): connect support/signals.py
    signals.py              # cache invalidation + screenshot cleanup receivers
    constants.py            # every cap and limit named below
    models.py               # SupportSettings, IssueReport
    policy.py               # can_report() + the cached audience bundle
    storage.py              # ScreenshotStorage
    validators.py           # validate_screenshot_file
    telemetry.py            # allow-list, caps, sanitiser, display labels
    forms.py                # SupportSettingsForm, ReporterPickerForm, IssueReportForm
    emails.py               # send_issue_report_email(report)
    views.py                # report_create (the dialog POST target)
    views_manage.py         # reporters, report_list, report_detail,
                            # report_set_status, report_delete, screenshot
    urls.py
    migrations/
    templates/support/...
    static/support/js/report_dialog.js
    static/support/css/support.css
    tests/
```

**Root URLconf.** `config/urls.py` gains `path("", include("support.urls"))` alongside
the other app includes. `support/urls.py` uses `app_name = "support"` and these
prefixes:

| Route | Name | Audience |
|---|---|---|
| `report/` (POST) | `support:report_create` | any permitted reporter |
| `manage/issue-reports/` | `support:report_list` | PA |
| `manage/issue-reports/<pk>/` | `support:report_detail` | PA |
| `manage/issue-reports/<pk>/status/` (POST) | `support:report_set_status` | PA |
| `manage/issue-reports/<pk>/delete/` (POST) | `support:report_delete` | PA |
| `manage/issue-reports/<pk>/screenshot/` | `support:screenshot` | PA |
| `manage/settings/support/reporters/` | `support:reporters` | PA |

### Constants (`support/constants.py`)

Every limit the rest of this spec refers to is named here, so tests assert against a
name rather than a number they inferred from the implementation.

```python
from datetime import timedelta

DESCRIPTION_MAX_LENGTH = 4000
PAGE_URL_MAX_LENGTH = 2000
PAGE_TITLE_MAX_LENGTH = 300
REPORTER_LABEL_MAX_LENGTH = 200
REPORTER_ROLES_MAX_LENGTH = 200
THROTTLE_MAX_REPORTS = 5           # per user, per window
THROTTLE_WINDOW = timedelta(hours=1)
EXTRA_EMAILS_MAX = 20
SUPPORT_CONFIG_CACHE_KEY = "support:config"
SUPPORT_CONFIG_TTL = 300           # seconds; mirrors core.services.CACHE_TTL
LIST_PAGE_SIZE = 25
```

The per-key telemetry caps and numeric bounds are the one deliberate exception: they
live in `support/telemetry.py` next to the allow-list they belong to, as named module
constants (`TELEMETRY_CAPS`, `TELEMETRY_BOUNDS`). Tests import them from there. What
matters is that **no test asserts a bare literal**; splitting them across two modules is
fine, inventing them at the call site is not.

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

```python
class Status(models.TextChoices):
    OPEN = "open", pgettext_lazy("issue report status", "Open")
    RESOLVED = "resolved", pgettext_lazy("issue report status", "Resolved")
```

| Field | Type | Notes |
|---|---|---|
| `reporter` | `FK(AUTH_USER_MODEL, null=True, on_delete=SET_NULL, related_name="issue_reports")` | |
| `reporter_label` | `CharField(max_length=REPORTER_LABEL_MAX_LENGTH)` | Denormalised; **truncated on build**, see below |
| `reporter_roles` | `CharField(max_length=REPORTER_ROLES_MAX_LENGTH, blank=True)` | Comma-joined **Group names** (storage keys, e.g. `Teacher`), never translated labels; truncated on build |
| `description` | `TextField()` | Required; `DESCRIPTION_MAX_LENGTH` enforced in the form |
| `page_url` | `TextField(blank=True)` | Untrusted; truncated to `PAGE_URL_MAX_LENGTH` in the form, never a `URLField` |
| `page_title` | `CharField(max_length=PAGE_TITLE_MAX_LENGTH, blank=True)` | Untrusted; truncated in the form |
| `screenshot` | `ImageField(blank=True, storage=ScreenshotStorage, upload_to=screenshot_upload_to, validators=[validate_screenshot_file])` | Optional |
| `telemetry` | `JSONField(default=dict, blank=True)` | Sanitised client and server facts |
| `created_at` | `DateTimeField(auto_now_add=True)` | |
| `status` | `CharField(max_length=16, choices=Status.choices, default=Status.OPEN)` | |
| `resolved_at` | `DateTimeField(null=True, blank=True)` | |
| `resolved_by` | `FK(AUTH_USER_MODEL, null=True, on_delete=SET_NULL, related_name="+")` | |
| `emailed_at` | `DateTimeField(null=True, blank=True)` | Null means the mail never went out |

`Meta.ordering = ["-created_at"]`, with two indexes:

- `("status", "-created_at")` — the triage list always filters on status and orders by
  recency.
- `("reporter", "-created_at")` — serves the throttle's per-user count, which would
  otherwise scan.

**`reporter_label` truncation is mandatory, not incidental.** `User.display_name` is
`max_length=150`, `username` is 150 and `email` is 254, so the composed
`"Display Name (username) <email>"` can reach ~560 characters. Postgres raises
`DataError` on overflow, which would 500 the submission — losing the report at exactly
the moment the user is telling you something is broken. The label is built and then
sliced to `REPORTER_LABEL_MAX_LENGTH`.

`reporter_roles` is truncated **on a comma boundary**, dropping any trailing partial
name rather than slicing mid-string. A blind slice could store `Course Adm`, which the
`ROLE_LABELS` fallback below would then faithfully render as a role the user never held.
The four current roles cannot overflow 200 characters; the cap exists for future or
renamed Groups, which is precisely the case where a mid-token cut would lie.

`reporter_label` and `reporter_roles` are **denormalised on purpose**. This repo hard-
deletes and keeps no orphan audit rows; a report whose provenance evaporates with the
account tells the PA nothing. `reporter` remains a FK so a live account still links.

Roles are stored as Group **names**, not `ROLE_LABELS` values: `institution/roles.py` is
explicit that the Group name is the storage key and `ROLE_LABELS` is display-only. The
triage template renders each stored name through `ROLE_LABELS`, **falling back to the
raw stored name** when the key is absent — a snapshot can name a Group that has since
been renamed or removed, and that must render as text rather than raising or rendering
blank.

### Screenshot storage (`support/storage.py`)

```python
SUPPORT_SCREENSHOT_DIR = BASE_DIR / "support_screenshots"   # config/settings/base.py
```

Declared beside `TRANSFER_STAGING_DIR` and carrying the same kind of comment: **not
under `MEDIA_ROOT`, because these must never be web-served.**

```python
class ScreenshotStorage(FileSystemStorage):
    """Private storage for report screenshots.

    Resolves the directory on EVERY access rather than at import: Django's
    FileField.__init__ calls a callable `storage` immediately, so a storage built
    with location=settings.SUPPORT_SCREENSHOT_DIR would freeze that path at model-
    import time and override_settings(...) in tests would be a silent no-op —
    every screenshot test would write into the developer's working tree.

    BOTH base_location and location must be plain properties. In Django 5.2
    FileSystemStorage declares each as a separate @cached_property (location =
    abspath(base_location)), and every path operation — path(), _save(), exists() —
    goes through `location`, not `base_location`. Overriding only base_location
    would still freeze the resolved path on first access, and
    StorageSettingsMixin._clear_cached_properties only pops the cache for
    MEDIA_ROOT / MEDIA_URL, never for a custom setting name.

    url() raises, so a template reaching for the idiomatic {{ report.screenshot.url }}
    fails loudly instead of emitting a plausible /media/... link that bypasses the
    PA-only view and resolves to nothing. base_url is pinned to None as well, so the
    inherited cached_property can never quietly resolve to MEDIA_URL.

    The constructor's `location` argument is intentionally INERT: overriding the
    cached_property with a plain property means FileSystemStorage.__init__ stores
    self._location and nothing ever reads it. Tests must redirect the directory with
    override_settings(SUPPORT_SCREENSHOT_DIR=...), never ScreenshotStorage(location=...),
    which would silently use the real directory.
    """

    base_url = None

    @property
    def base_location(self):
        return settings.SUPPORT_SCREENSHOT_DIR

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def url(self, name):
        raise NotImplementedError("Use {% url 'support:screenshot' report.pk %}.")
```

The paired test must resolve a path under **two different** `override_settings`
values within one process. Asserting once passes even on the frozen implementation,
because the first access happens after the override — the freeze only shows up on the
second test in the same process, which is exactly the kind of order-dependent green
this repo's mutant discipline exists to catch.

The field passes the **class itself** as the callable: `storage=ScreenshotStorage`.
Django invokes it at field init and serialises the callable reference — not an
instance's absolute `location` — into the migration.

`screenshot_upload_to` produces `screenshots/<YYYY>/<MM>/<uuid4>.<ext>`, with the
extension taken from the validated original filename and **lower-cased** (a real upload
can be `Photo.PNG`, and `FileExtensionValidator` lower-cases before comparing while a
naive `rsplit(".")[-1]` does not). The stored name therefore never derives from
user-supplied text — no original basename, no path separators, no traversal. The
content-type lookup in the screenshot view is likewise case-insensitive.

The idiomatic `upload_to="screenshots/%Y/%m/"` is **wrong here** and is the thing an
implementer will reach for: it preserves the client-supplied basename. This is a
security property, so it carries its own test row and mutant.

**Validation uses `support/validators.py::validate_screenshot_file`, not
`courses.validators.validate_image_file`.** The latter applies
`Institution.allowed_image_extensions`, which a PA may narrow for *content* uploads; a
PA who restricts course images to `jpg`/`webp` would then silently break screenshot
paste, since clipboard images are PNG on Windows. `validate_screenshot_file` therefore
validates against the permanent `SAFE_IMAGE_EXTENSIONS` ceiling and
`MAX_IMAGE_MIB_CEILING` (5 MiB) from `courses.validators`, decoupling bug reporting
from an unrelated setting.

`post_delete` on `IssueReport` deletes the file. Django does not do this on its own, and
orphaned screenshots of student data accumulating on disk is exactly the failure mode to
avoid. All three receivers — `post_save` and `m2m_changed` for the cache,
`post_delete` for the file — live in **`support/signals.py`** and are connected from
`SupportConfig.ready()`, so none of them can end up in a module that is never imported.

**Rollback also orphans a file.** `form.save()` writes through the storage inside
`transaction.atomic()`, but filesystem writes are not transactional: if the transaction
rolls back, the row vanishes while the file stays on disk forever — no row means
`post_delete` never fires and no PA can ever see or delete it.

The cleanup has an exact shape, because the obvious one is broken:

```python
saved_name = None
try:
    with transaction.atomic():
        report = form.save()
        saved_name = report.screenshot.name or None
        ...
except Exception:
    if saved_name:
        ScreenshotStorage().delete(saved_name)
    raise
```

`saved_name` is initialised **before** the `try`. The likeliest failure is a database
error raised *by* `form.save()` itself, after the field's `pre_save` has already written
the file to disk; an `except` block that reads `report.screenshot.name` would then raise
`NameError` on an unbound name, masking the real exception *and* still orphaning the
file. The paired test must therefore simulate a failure **inside** `form.save()`, not
after it.

### Audience policy (`support/policy.py`)

`can_report(user, role_names=None) -> bool` is the single source of truth, evaluated in
order:

1. Anonymous, or `not user.is_active` -> `False`.
2. `user.is_superuser` -> `True`.
3. If the rung is `all` -> `True` for any authenticated active user, **without
   consulting Groups at all**.
4. Membership of the `Platform Admin` Group -> `True`, unconditionally, whatever the
   ladder says.
5. The user's role Group names intersect the rung's admitted set -> `True`.
   (`admins` admits nothing extra; `course_admins` adds Course Admin; `teachers` adds
   Teacher and Course Admin.)
6. `user.id` is in the extras set -> `True`.
7. Otherwise `False`.

**The ordering is deliberate.** Rules 1–3 are settled without touching Groups, so the
most permissive rung genuinely skips the Group lookup rather than merely claiming to.
Placing the Platform Admin check at 4 rather than 2 changes no outcome — a PA is
admitted by rule 3 under `all` anyway — but it keeps the stated performance property
true, and the tests are written against these numbers.

**Rules 2 and 4 split the superuser case deliberately.** `accounts/services.py`
(`is_last_active_platform_admin`) documents that "superusers outside the PA group are a
separate recovery path and are not counted", so Group membership and `is_superuser` are
genuinely distinct here. A recovery superuser is also the account most likely to be
debugging a broken deployment, and `permission_required` already grants them the triage
pages, so denying them the report dialog would be incoherent. Note the asymmetry, which
is intended: superusers **can report**, but are **not** email recipients — the recipient
query keys on Group membership only, matching `is_last_active_platform_admin`.

**Rule 3 exists because "Everyone" must mean everyone.** Evaluated purely as a Group
intersection, the `all` rung would deny an authenticated account holding no role Group —
a freshly `createsuperuser`'d account, an SSO-provisioned account before role
assignment, or an account whose Group was removed — under the one rung whose label
promises the opposite.

**Query budget.** `can_report` runs on **every authenticated page render** via the
context processor below. The settings row and the extras ids come from a cached bundle
`{"audience": str, "extra_reporter_ids": frozenset[int]}` built by
`get_support_config()` and dropped by `invalidate_support_config()`, following the
`get_site_config` / `invalidate_site_config` pattern at `core/services.py:102-113`.

The user's Group names are a per-user fact that no such bundle can hold, and
`core/context_processors.py:user_roles` **already** runs exactly that query on every
authenticated request. To avoid doubling it, `core/services.py` gains:

```python
def role_names_for(request):
    """Group names of request.user as a frozenset, memoised on the request."""
```

`user_roles` is refactored to use it, and `support_availability` passes its result into
`can_report(user, role_names=...)`. Net cost stays at **one** Group query per request,
not two. `report_create` has a live request and passes `role_names_for(request)` too;
only callers with no request at all (tests, management commands) omit the argument, in
which case `can_report` fetches the names itself.

**A naive query-count assertion would be false on a correct build.** `base.html`
evaluates `perms.*` for every authenticated user, which drives
`ModelBackend._get_group_permissions` — `Permission.objects.filter(group__user=user)`,
whose SQL also joins `auth_group`. Counting every statement mentioning `auth_group`
therefore yields at least two on a *correct* build. The auth backend's permission query
is expected and must be excluded; the test counts only statements selecting
`"auth_group"."name"`, which the permission query does not.

Cache invalidation must be connected to **both**:

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
- `SupportSettingsForm` lives in `support/forms.py` and is imported by the institution
  view, the same direction as `IntegrationsForm` today.

The tab holds exactly two editable controls plus one summary:

1. **Who can report** — a radio group of the four rungs.
2. **Send reports to** — a textarea, one address per line, each validated with Django's
   `EmailValidator`; blank lines ignored; addresses **lower-cased and de-duplicated on
   save**; at most `EXTRA_EMAILS_MAX` entries; stored as a JSON list. Normalising on
   save (not only at send) keeps the stored list and the send-time dedup consistent.

   `SupportSettingsForm` must **override this field explicitly** as a
   `CharField(widget=Textarea, required=False)` with a `clean_extra_emails` that splits,
   validates, normalises and returns a list, and with `initial` rendered as
   newline-joined text. Left to the ModelForm default, a `JSONField` yields
   `forms.JSONField`, whose textarea expects literal JSON — a field that looks right and
   rejects everything a PA types.
   Above it, a read-only line names the Platform Admins who will be mailed
   automatically, so "who gets this" is never a guess. **Below it, a warning line:**
   "These addresses receive the full report, including any attached screenshot, which
   may contain student data." That warning is load-bearing. This design goes to real
   lengths to keep screenshots behind `permission_required`, and then hands them,
   unauthenticated and unlogged, to whatever a PA types into a free-text box. Emailing
   the attachment is still the right call — a helpdesk alias with no libli account
   cannot open a login-walled link — but it is an **accepted disclosure**, and the
   person accepting it has to be told at the point of decision.
3. **Also allowed** — a read-only summary ("3 people also allowed") linking to the
   dedicated **Allowed reporters** page. `SupportSettingsForm` carries **no** M2M field,
   so the always-rendered Support panel costs nothing beyond the already-selected count.

   That count is taken **through the join table** —
   `SupportSettings.extra_reporters.through.objects.filter(supportsettings_id=1).count()`
   — never as `row.extra_reporters.count()` on the read-only fallback. `_settings_context`
   builds every panel on every render of *any* settings tab, and before the first save the
   fallback is an unsaved instance whose M2M access raises `ValueError`. Reaching for the
   natural `.count()` therefore 500s the settings page on a brand-new install, on every
   tab — the first-run path.

**Allowed reporters page** (`support:reporters`, `permission_required`): the roster
picker pattern from `templates/grouping/group_form.html` — a searchable
(`data-roster-search`) checkbox list of active non-PA users, filtered client-side. Being
a dedicated page, it renders that list only when a PA actually opens it.

Its POST path binds to `SupportSettings.load()` — writing is the whole point of the
page, so the singleton is materialised first and `save_m2m()` therefore always runs
against a row with `pk=1`. The first-ever save must both create the row and fire the
`m2m_changed` invalidation, and is tested as such.

`settings_support`'s POST binds to `load()` for the same reason, matching
`settings_integrations` (`institution/views_manage.py`), which already does exactly this
for `WebhookEndpoint`. So the rule is: **the two write paths — the Support tab's POST
and the Allowed reporters POST — use `load()`; every read path uses
`filter(pk=1).first()`.**

**Roster queryset:** active non-PA users **unioned with the currently-selected
`extra_reporters`**. A queryset of only "active non-PA users" would omit any already-
granted user who has since been deactivated or promoted to PA, and the next
`save_m2m()` would then silently *revoke* that grant — a PA opening the page to add one
person would drop an unrelated one without being told. Already-selected users outside
the base roster render checked, with a muted note explaining why they are listed.

### Reporter surface

- `core/context_processors.py` gains `support_availability(request)` returning
  `{"can_report_issue": ..., "report_description_max": DESCRIPTION_MAX_LENGTH}` —
  the same shape as the existing `help_availability` — registered in
  `TEMPLATES["OPTIONS"]["context_processors"]` beside it. The cap has to travel this
  way: the dialog is `{% include %}`d from `base.html` and so has no view context, and
  the `maxlength` attribute, the live counter and the JS all need the value. The
  template renders it into a `data-` attribute on the textarea and the JS reads it from
  there, so `DESCRIPTION_MAX_LENGTH` is written down exactly once.
- `templates/base.html`, behind `{% if can_report_issue %}` in two **separate**
  places: the **trigger** is a menu item inside the account-menu panel, while the
  `{% include "support/_report_dialog.html" %}` sits at body level, outside every
  `hidden` / `data-menu-panel` container. This split is required, not tidiness — the
  account panel carries the `hidden` attribute, and `showModal()` on a `<dialog>` inside
  a hidden subtree does not reliably work.
- `support/static/support/js/report_dialog.js` opens the dialog, populates the hidden
  telemetry fields, handles paste-to-attach, posts `FormData` via `fetch`, and renders
  errors back inside the dialog.
- Its `<link>` and `<script>` go **directly in `base.html`**, beside the shell's own
  asset tags and guarded by the same `{% if can_report_issue %}` — explicitly **not**
  inside `{% block extra_css %}` / `{% block extra_js %}`. Those blocks exist for child
  templates to override, and most pages do override them, which would drop the dialog's
  assets on exactly those routes: an unstyled, inert dialog on some pages and a working
  one on others.
- The `<dialog>` needs **explicit theming**: in this codebase a `<dialog>` does not
  inherit the page theme, so its colours must be set from the theme tokens rather than
  inherited.

**CSRF.** The dialog contains a real `<form method="post" action="{% url
'support:report_create' %}" enctype="multipart/form-data">` including `{% csrf_token %}`,
and the JS submits `new FormData(form)` — the token travels as a form field. The
telemetry inputs are real hidden `<input>`s inside that form, populated by JS, not
values assembled ad hoc in the fetch call. Building the `FormData` field-by-field would
omit the token and 403 every submission, which is easy to misdiagnose against the
permission 403 below.

**Paste to attach.** A `paste` listener on the dialog reads an image out of
`event.clipboardData.items`, **re-wraps it as `new File([blob], "screenshot.<ext>",
{type: blob.type})`** with the extension derived from the blob's MIME type, and assigns
it to the file input via a `DataTransfer`. The re-wrap is required, not cosmetic:
`getAsFile()` returns a browser-dependent name that is often extensionless or `blob`,
and `FileExtensionValidator` parses the filename — so the headline flow (`Win+Shift+S`,
`Ctrl+V`, send) would otherwise fail with a confusing "extension not allowed". The
`<input type="file">` remains, both as the fallback and as the control that shows what is
attached.

### Triage surface

`support/views_manage.py`, every view decorated
`@permission_required("support.<perm>_issuereport", raise_exception=True)`. The flag is
mandatory, not decoration: `permission_required` defaults to `raise_exception=False`,
which **redirects to `LOGIN_URL` (302)** instead of raising `PermissionDenied`, and
every 403 asserted in this spec would then be a 302. The repo is uniform on this —
`accounts/views_manage.py:40`, `courses/views_manage.py:85`, `grouping/views.py:35` and
`core/views.py:198` all pass it.

- `report_list` — paginated at `LIST_PAGE_SIZE` (`Paginator`, as in
  `accounts/views_manage.py`), newest first. Columns: created, reporter, role, first
  line of the description, a screenshot indicator, a **not-emailed** indicator, status.
  Filtered by `?status=`, accepting `open`, `resolved` and `all`; **the default is
  `open`**, because the list exists to show what still needs doing, and an unrecognised
  value falls back to `open` rather than erroring. The Admin-menu item links to the
  unfiltered (therefore open) URL.
- `report_detail` — the description, the telemetry rendered as **labelled rows, not a
  JSON blob** (labels from `support/telemetry.py`), the screenshot thumbnail, and the
  status and delete actions. When `emailed_at` is null it shows a **"not emailed"**
  notice: that column exists solely to record a delivery failure, and the error handling
  below leans on the triage surface being the safety net — which it is not if a PA
  cannot tell a delivered report from an undelivered one without a shell.
- `report_set_status` — POST only. The target comes from a `status` POST field whose
  only accepted values are `open` and `resolved`; anything missing or unrecognised
  returns **400 without touching the row**. Setting the status a report already has is a
  **no-op**: it must not overwrite an existing `resolved_by`/`resolved_at` and lose who
  actually triaged it. Resolving sets both; reopening clears both. Redirects back to
  `report_detail`.
- `report_delete` — POST only, with confirmation. This is the sole production path that
  removes a report and, via `post_delete`, its screenshot; without it the receiver is
  reachable only from tests and screenshots of student data accumulate forever.
  Redirects to `report_list`, preserving the current `?status=` filter — returning to
  `report_detail` would 404 on the row just deleted. The filter arrives as a **hidden
  input on the confirmation form**, validated against the same `{open, resolved, all}`
  set and falling back to the default otherwise. Not `HTTP_REFERER`, which is an open
  redirect waiting to happen.
- `screenshot` — `FileResponse` for the private file. **404** when the field is empty or
  the file is missing from disk (a DB restored against a fresh volume must not 500).
  Served `Content-Disposition: inline` with a `Content-Type` derived from the stored
  extension, never from anything the client sent.

Reached from an **Issue reports** item in the Admin menu in `base.html`, wrapped in
`{% if perms.support.view_issuereport %}`. The outer `.app-nav__admin` condition
(`templates/base.html:91`) is **left unchanged**: `view_issuereport` is PA-only, and
every PA already satisfies that chain via `perms.institution.change_institution`, so
adding a disjunct would be dead.

Access is a real permission, not a role-name check: `support.view_issuereport`,
`support.change_issuereport` and `support.delete_issuereport` are appended to
`PLATFORM_ADMIN_PERMS` in `institution/roles.py`.

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
   collapsible **"What will be sent"** block shows those values verbatim **and** a
   static line naming the facts collected server-side that it cannot display — "we also
   record your name and email address, your role, your browser identification and
   language, and the time". Without that line the transparency claim would be false, since
   the user agent, `Accept-Language`, the role snapshot and `reporter_label` never pass
   through the client.
4. `POST` `multipart/form-data` to `support:report_create`.
5. The view: `@login_required`, then **re-checks `can_report(request.user)` and 403s
   otherwise**, then the throttle, then `IssueReportForm` validation.
6. On success the row is saved inside `transaction.atomic()` with the sanitised
   telemetry and the role snapshot, and the email is queued with
   `transaction.on_commit`.
7. The dialog renders the JSON response per the contract below.

### The `report_create` JSON contract

Both sides are written against this table; nothing here is left to the implementer.

| Outcome | HTTP | Body | Dialog behaviour |
|---|---|---|---|
| Success | `201` | `{"ok": true, "message": "<thank-you text>"}` | Show `message`, **reset the form**, close |
| Not a POST | `405` | non-JSON | Generic banner (the `Content-Type` check routes it there) |
| Field errors | `400` | `{"ok": false, "message": null, "errors": {"<field>": ["<msg>", ...]}}` | Render each list under its field |
| Throttled | `429` | `{"ok": false, "message": "<polite text>", "errors": {}}` | Show `message` as a banner; keep the typed text |
| Not permitted | `403` | `{"ok": false, "message": "<text>", "errors": {}}` | Show `message` as a banner |
| Not authenticated | `401` | `{"ok": false, "message": "<text>", "errors": {}}` | Show `message`, offer a link to log in; never navigate away silently |
| Anything else, or a non-JSON body | any | — | Generic banner, dialog stays open, **typed description preserved** |
| `fetch` rejects (network) | — | — | Same generic banner |

The view is `@require_POST`. **Resetting the form on success is not cosmetic:** the
dialog lives in `base.html` and the page never navigates, so without a reset the next
open would show the previous description and still hold the previously attached file in
the `<input type="file">` — a short path to a duplicate report carrying a stale
screenshot. The reset clears the description, the file input and the paste-populated
`DataTransfer`; the telemetry fields are re-read on every open, since the user may have
resized or navigated in between.

**`report_create` does not use `@login_required`.** It checks
`request.user.is_authenticated` itself and returns the `401` above. This is not a style
preference: `fetch()` defaults to `redirect: "follow"`, so a `302` to the login page is
invisible to the client — it observes `status === 200`, `redirected === true` and an
HTML body, `response.json()` throws, and the dialog dies silently with the user's typed
description still in it. A dialog left open past session expiry is an entirely ordinary
path, so the contract must be observable.

The last two rows exist because a feature whose whole premise is "something on this page
is broken" must not itself fail silently. Django's CSRF failure view returns a `403`
with an **HTML** body, so the client **checks `Content-Type` before parsing** rather than
assuming JSON on a 403; a 500 or a dropped connection lands in the same generic-banner
branch. In every one of these cases the description the user typed is preserved.

`errors` is built from `form.errors.get_json_data()`, reduced to `{field: [message,
...]}`. The client distinguishes the cases by HTTP status, never by inspecting text.
Every response the view itself produces carries `Content-Type: application/json`.

### Telemetry assembly and sanitisation (`support/telemetry.py`)

Everything in step 2 is **client-supplied and therefore untrusted**. The view never
stores the payload; it builds the `telemetry` dict from a fixed allow-list. Unknown keys
are dropped silently.

The sanitiser reads **directly from `request.POST`** (and `request.META` for the two
server-side keys), never through `IssueReportForm`. The eight client keys are neither
model fields nor declared form fields, and routing them through the form would mean a
malformed telemetry value could *reject a bug report*. Bad telemetry is always dropped,
never an error.

| Key | Source | Type | Rule |
|---|---|---|---|
| `viewport_w`, `viewport_h` | client | int | Keep iff `1 <= v <= 20000`, else **drop the key** |
| `screen_w`, `screen_h` | client | int | Same bounds, same drop |
| `dpr` | client | float | Keep iff `0 < v <= 10`, rounded to 2dp, else drop |
| `timezone` | client | str | Truncate to 64 |
| `theme` | client | str | Keep iff exactly `light` or `dark`, else drop |
| `ui_language` | client | str | Truncate to 16 |
| `user_agent` | **server** (`HTTP_USER_AGENT`) | str | Truncate to 512 |
| `accept_language` | **server** (`HTTP_ACCEPT_LANGUAGE`) | str | Truncate to 256 |

Out-of-range or non-numeric values are **dropped, never clamped** — a clamped 20000px
viewport is a plausible-looking lie in a diagnostic record, while an absent key is
honestly absent. Where a server fact and a client claim would overlap, the server fact
wins.

`TELEMETRY_LABELS` in the same module maps each key to a translated display label, and
is the single source shared by the triage template and the email body, so the two can
never drift.

**No IP address is collected.** This is a platform with student accounts; the
diagnostic value does not justify the personal-data question.

`page_url` and `page_title` are their own columns, not telemetry keys, and are therefore
capped **in `IssueReportForm.clean_*`**: `page_url` truncated to `PAGE_URL_MAX_LENGTH`,
`page_title` to `PAGE_TITLE_MAX_LENGTH`. Left to the database, an over-long title raises
`DataError` and 500s the submission, and `page_url` — an unbounded `TextField` fed from
an untrusted POST field — would accept megabytes.

`page_url` is the sharp edge for rendering. It is stored as text, rendered escaped
everywhere, and in the triage template is turned into a link **only if** its scheme is
`http` or `https` **and** its host matches the current Site. The current Site — not
`request.get_host()`, not `ALLOWED_HOSTS` — is the source of truth, matching
`notifications/emails._absolute_url`, which uses it precisely so a link can never be
host-spoofed. A `javascript:` value must never reach an `href`.

The comparison is `urlparse(url).hostname` (already port-stripped and lower-cased)
against `Site.domain.split(":")[0].lower()`. Comparing `netloc` to `Site.domain`
directly would fail on every port-bearing deployment and throughout local development
(`localhost:8000` vs `localhost`). Note also that Django's default `Site.domain` is
`example.com`, so an install that never edited the Site row gets inert text for every
report — **by design, not a bug**: an unmatched host renders as plain text, and the page
still looks correct, so this is called out here to stop it being chased as a defect.

### Throttle

`support/policy.py::throttle_exceeded(user)` returns True when
`IssueReport.objects.filter(reporter=user, created_at__gte=now() -
THROTTLE_WINDOW).count() >= THROTTLE_MAX_REPORTS`. A **rolling** window, not a clock
hour. Served by the `("reporter", "-created_at")` index.

No one is exempt, PAs included: the limit is high enough not to obstruct honest use, and
an exemption is a branch nobody would test. Because the count reads stored rows,
deleting reports refunds quota — acceptable, since only PAs can delete.

### Audience resolution

`can_report` calls `get_support_config()`, which either hits the cache
(`SUPPORT_CONFIG_CACHE_KEY`, `SUPPORT_CONFIG_TTL`) or runs one query for the settings
row plus one for the extras ids and caches the bundle.

**The no-row branch must not touch the M2M.** When `filter(pk=1).first()` returns
`None`, `get_support_config()` returns
`{"audience": Audience.ADMINS, "extra_reporter_ids": frozenset()}` immediately and
**never constructs a fallback `SupportSettings()` to read `extra_reporters` from**.
Django raises `ValueError: … needs to have a primary key value before a many-to-many
relationship can be used` for any M2M access on an unsaved instance, and `can_report`
runs from a context processor on *every authenticated page render* — so taking the
`or SupportSettings()` shortcut here would 500 the entire site on a fresh install,
until someone happened to save the Allowed reporters page.

The general `filter(pk=1).first() or SupportSettings()` rule stated elsewhere in this
spec is about **scalar** fields, where an unsaved instance safely yields the model
defaults. It does not extend to `extra_reporters`, and every read of that relation must
be guarded on `pk` being set.

**The invalidation guarantee is bounded, and the spec states it honestly.** The default
cache is `LocMemCache`, which `core/services.py` already documents as per-process.
`invalidate_support_config()` therefore clears the bundle **immediately in the worker
that handled the save, and only within `SUPPORT_CONFIG_TTL` elsewhere** — exactly the
same property `get_site_config` has. This bounds **revocation** latency as well as
grants: a PA who narrows the rung may still see reports accepted by another worker for
up to the TTL. That is acceptable for this feature and is not worth a cross-process
invalidation mechanism, but it must not be described as instantaneous. The paired test
exercises the single-process path only, which is all a test process can observe.

### Email delivery

`support/emails.py`, built like `notifications/emails.py`: `EmailMultiAlternatives` with
a plain-text body and an HTML alternative rendered by `render_to_string`, inside
`translation.override(...)` with **eager `gettext`** (not `gettext_lazy`) so
interpolation resolves inside the override block — the same rule that module already
documents.

- **Language:** the institution default (`get_site_config()["default_language"]`), not
  the reporter's. One message goes to every recipient, so it can only have one language.
- **Recipients:** every **active** member of the `Platform Admin` Group with a non-empty
  email address, unioned with `extra_emails`, de-duplicated case-insensitively.
  Superusers outside that Group are not included (see "Audience policy", rule 2).
- **Envelope:** `to=[settings.DEFAULT_FROM_EMAIL]` with every resolved recipient in
  **`bcc`**. Putting them in `to` would disclose each PA's personal address to a
  helpdesk alias and to every other recipient — indefensible in a design whose other
  choices are explicitly privacy-driven.
- **Empty recipient set short-circuits before `send()`.** Because `to` is always
  non-empty, an empty `bcc` would still produce a valid message to
  `DEFAULT_FROM_EMAIL`; `send()` would return 1 and stamp `emailed_at`, making that
  column lie in precisely the case it exists to record. So: if the resolved recipient
  set is empty, log a warning, **skip `send()` entirely**, and leave `emailed_at` null.
- **This is a deliberate divergence** from `notifications/emails.py:107`, which sends one
  message *per* recipient with `[recipient.email]`. A single bcc'd message is right here
  because the audience is a fixed admin list rather than a per-user fan-out. Noted so a
  later reviewer does not "restore consistency" and undo it.
- **`reply_to`:** the reporter's address when they have one, so a PA can simply reply.
- **Subject:** institution name, the report id, and the reporter's display name, with
  **whitespace collapsed** (`" ".join(value.split())`) — a display name containing a
  newline would otherwise split the header. The id is what stops every report from one
  reporter sharing a byte-identical subject; without it mail clients thread them and the
  inbox becomes exactly as undifferentiated as the status-less list the design table
  rejects.
- **Body:** description, reporter, roles, page URL, the telemetry as a labelled list
  built from `TELEMETRY_LABELS`, and — first — an **absolute link to
  `support:report_detail`**, built with the same `Site`-based helper as
  `notifications/emails._absolute_url` so it cannot be host-spoofed. Without it a PA who
  wants the full-size screenshot or the resolve button has to open the triage list and
  guess which row this was, which undercuts the whole reason reports are stored. The
  screenshot is **attached** (capped at 5 MiB by the upload validator).
- **Ordering:** the view wraps the save in `transaction.atomic()` and the send runs in
  `transaction.on_commit` inside `try`/`except`. Success sets `emailed_at` with
  `save(update_fields=["emailed_at"])` — a bare `save()` from a post-commit callback
  would rewrite every field of a row a PA may have resolved in the meantime. Failure
  logs and leaves it null. With SMTP unconfigured the report still exists and the PA
  still sees it — the entire reason storage was chosen over email-only.

`ATOMIC_REQUESTS` is **not** set in this project, so without the explicit
`transaction.atomic()` the callback would fire immediately and the rollback guarantee
would be vacuous. Tests execute the callbacks with pytest-django's
`django_capture_on_commit_callbacks(execute=True)`; under a plain `django_db` mark they
do not run at all.

### Triage

The PA opens **Issue reports**, filters to open, opens one, reads the telemetry and the
screenshot, acts, and marks it resolved (or reopens it, or deletes it). `resolved_by`
and `resolved_at` record who and when.

## Error handling

| Situation | Behaviour |
|---|---|
| A user who may not report POSTs to `support:report_create` | **403** per the JSON contract. The menu item being hidden is not access control, and the ladder's top rung is "Everyone" — this gate *is* the feature. |
| Anonymous POST | **`401` JSON**, never a login redirect — a `fetch` follows a 302 invisibly and the dialog would die silently. |
| A 500, a network drop, or Django's HTML CSRF-failure 403 | Generic banner; the dialog stays open and the typed description is preserved. The client checks `Content-Type` before parsing. |
| The transaction rolls back after the screenshot file was written | The `except` around the atomic block deletes the orphaned file before re-raising. |
| Empty or whitespace-only description | `400` with a field error; no row, no mail. |
| Description over `DESCRIPTION_MAX_LENGTH` | `400` with a field error; the dialog also shows a live character counter so this is rare. |
| `page_url` / `page_title` over their caps | Silently truncated in `clean_*` — never a `DataError`, never a rejected report. |
| Screenshot too large, or a disallowed or non-image extension | `400` with a field error; the description the user typed is preserved client-side. |
| Pasted image with an extensionless name | Re-wrapped by the JS before it reaches the input; never surfaces as a validation error. |
| 6th report from one user within the rolling hour | `429` with a polite message; **no row written and no mail sent**. |
| SMTP unconfigured, or the send raises | The report row survives; `emailed_at` stays null; the failure is logged. The reporter is still told the report was received, because it was. |
| The enclosing transaction rolls back | `on_commit` never fires, so no email describes a report that does not exist. |
| No resolvable recipients (no PA has an email and `extra_emails` is empty) | The row is still written; nothing is sent; a warning is logged. The triage list is the safety net. |
| Hostile telemetry (`page_url` of `javascript:...`, over-long strings, unknown keys, a 10⁹-px viewport) | Dropped, truncated, or stored as inert escaped text; never emitted into an `href`. |
| A non-PA requests a screenshot URL | **403** from `permission_required`. |
| Screenshot requested for a report with none, or whose file is gone | **404**, not a 500. |
| A template reaches for `report.screenshot.url` | `NotImplementedError` — loud in tests rather than a silently broken `/media/` link. |
| A report is deleted | `post_delete` removes the screenshot file from disk. |
| `report_set_status` called with the status the report already has | No-op; `resolved_by` / `resolved_at` are preserved. |
| `report_set_status` with a missing or unrecognised `status` value | **400**, row untouched. |
| A `Site.domain` that never left its `example.com` default | Every `page_url` renders as inert text. Intended, not a defect. |
| A stored role name is no longer in `ROLE_LABELS` | Rendered as the raw stored name. |
| The `SupportSettings` row does not exist yet | Scalar reads use `filter(pk=1).first() or SupportSettings()`, so the defaults apply and no row is written on a GET. **`extra_reporters` is never read off that fallback** — an M2M access on an unsaved instance raises `ValueError`, which would 500 both the settings page and every authenticated render. The first save from either write path creates the row. |

## Testing

Following this repo's practice, **each test is paired with the mutant that must turn it
RED** — a test that cannot fail on a broken build is not evidence.

| Test | Mutant that must break it |
|---|---|
| **A permitted user's POST creates one row** with the expected `page_url`, `reporter_label`, `reporter_roles` snapshot and allow-listed telemetry, and returns `201` | Drop the role snapshot, or store `reporter` only |
| `can_report` matrix: 4 rungs by 4 roles, plus extras, a **group-less authenticated user**, a superuser outside the PA Group, an inactive user, and anonymous | Drop the "Platform Admin / superuser always" rule |
| Under the `all` rung, a user holding **no** role Group can report | Evaluate `all` as a Group intersection |
| **A Student POSTs `report_create` while the rung is `course_admins` -> 403** | Delete the server-side `can_report` gate from the view |
| A user added to `extra_reporters` can report on the very next request | Remove the `m2m_changed` cache-invalidation receiver |
| The **first-ever** save of the Allowed reporters page creates pk=1 and invalidates the cache | Read via `filter(pk=1).first()` on that page's POST path |
| Changing `audience` takes effect on the next request | Remove the `post_save` receiver |
| An authenticated render of `home` issues **one** role-names query, not two — `CaptureQueriesContext`, counting only statements that select `"auth_group"."name"` | Drop `role_names_for`'s per-request memo |
| An anonymous POST returns **`401` JSON**, not a redirect | Restore `@login_required` |
| A non-JSON / 5xx response leaves the dialog open with the description intact | Assume JSON on every response |
| A 150-char display name plus a long email yields a stored label of exactly `REPORTER_LABEL_MAX_LENGTH` | Drop the truncation |
| `page_title` over its cap is truncated, not rejected and not a `DataError` | Drop `clean_page_title` |
| 6th report within the rolling hour -> `429`, no row, no mail | Raise `THROTTLE_MAX_REPORTS` |
| Recipients = active PA-Group members with an email, unioned with `extra_emails`, de-duplicated | Drop `extra_emails` from the recipient union |
| Recipients are in **`bcc`**, not `to` | Move them to `to` |
| A PA with no email address is not a recipient, and does not break the send | Remove the non-empty-email filter |
| A display name containing `\n` / `\r` produces a **single-line subject** | Remove the whitespace collapse |
| The screenshot is attached to the outgoing message | Drop the attachment |
| `emailed_at` is set on success, via `update_fields` (a concurrent `status` change survives) | Use a bare `save()` |
| **A send that raises still leaves the report row** | Move the send out of the `try`/`except` |
| **A rolled-back transaction sends no email** | Call `send()` directly instead of via `on_commit` |
| A Teacher GETting the screenshot view -> 403 | Drop `permission_required` |
| A screenshot is written under `SUPPORT_SCREENSHOT_DIR`, not `MEDIA_ROOT` — resolving the path under **two different** `override_settings` values in one process | Override only `base_location`, leaving `location` a `cached_property` (a single-override test passes anyway) |
| A file named `../../evil name.png` is stored as `screenshots/<YYYY>/<MM>/<uuid4>.png`, with no trace of the original basename | `upload_to="screenshots/%Y/%m/"` |
| An upload named `Photo.PNG` stores a lower-cased extension and serves the right content type | Append the extension verbatim |
| A failure raised **inside** `form.save()` leaves no file on disk, and the original exception propagates (not a `NameError`) | Read `report.screenshot.name` in the `except` instead of a pre-initialised `saved_name` |
| **With no `SupportSettings` row**, an authenticated render succeeds and `can_report` is False for a Student | Read the extras ids off an unsaved `SupportSettings()` fallback |
| **With no `SupportSettings` row**, a GET of every settings tab renders 200 with "0 also allowed" | Call `.extra_reporters.count()` on the unsaved fallback |
| With no PA email and empty `extra_emails`, `mail.outbox` is empty and `emailed_at` is null | Send anyway, since `to` is non-empty |
| 5 reports timestamped 61 minutes ago -> the 6th succeeds; 5 timestamped 59 minutes ago -> throttled | Anchor the window on the current clock hour instead of `now() - THROTTLE_WINDOW` |
| A reporter whose language is `pl` with an institution default of `en` produces an **English** subject and body | Override to the reporter's language |
| An inactive or since-promoted existing extra **survives** a save that only adds someone else | Scope the roster queryset to active non-PA users alone |
| The dialog works on a page whose template overrides `{% block extra_css %}` / `{% block extra_js %}` | Put the dialog's assets inside those blocks |
| The rendered textarea's `maxlength` equals `DESCRIPTION_MAX_LENGTH` | Hardcode the number in the template |
| The unfiltered list shows only open reports; `?status=all` shows both; an unrecognised value falls back to `open` | Default to `all` |
| `extra_emails` accepts newline-separated addresses typed into the textarea | Leave the ModelForm's `forms.JSONField` default in place |
| POST `report_delete` as a PA removes the row, the file, and redirects to the filtered list | Delete the route or the view |
| POST `report_delete` as a Teacher -> 403; GET does not delete | Drop `raise_exception=True`; allow GET |
| `report_set_status` with a missing or bogus value -> 400, row untouched | Fall through to `resolved` |
| A non-PA hitting any triage view gets **403**, not a 302 to the login page | Drop `raise_exception=True` |
| `emailed_at` null renders a "not emailed" indicator on the detail page | Omit the indicator |
| The email body contains an absolute `report_detail` link and the id appears in the subject | Drop the link; drop the id |
| `reporter_roles` truncation drops a trailing partial name rather than cutting mid-token | Use a blind slice |
| `report.screenshot.url` raises | **Remove the `url()` override** (inheriting `FileSystemStorage.url`, which then builds a plausible `/media/...` link). Note the mutant is *not* "let `base_url` fall back" — `url()` raises unconditionally, so that mutant could never go RED |
| Screenshot view 404s for an empty field and for a missing file | `FileResponse` on the raw path |
| Deleting a report deletes its file | Remove the `post_delete` receiver |
| `page_url` of `javascript:alert(1)`, and one on a foreign host, render escaped and never as an `href` | Link `page_url` unconditionally |
| Unknown telemetry keys dropped; over-long strings truncated; an out-of-range viewport **dropped, not clamped** | Store the payload verbatim |
| A screenshot still validates after a PA narrows `Institution.allowed_image_extensions` | Validate with `validate_image_file` |
| A stored role name absent from `ROLE_LABELS` renders as the raw name | Index `ROLE_LABELS` directly |
| `report_set_status` to the current status preserves `resolved_by` / `resolved_at` | Write them unconditionally |
| The settings form rejects a malformed address, caps the list at `EXTRA_EMAILS_MAX`, and lower-cases on save | Drop the `EmailValidator` / the cap / the normalisation |
| A GET of any other settings tab writes no `SupportSettings` row **and renders no per-user roster** | Use `load()` in `_settings_context`; put the M2M field back on `SupportSettingsForm` |

**e2e (Playwright).** Open the dialog from the account menu, attach an image **by
dispatching a synthetic paste**, submit, and assert both the stored row and the
confirmation. The paste is performed with `page.evaluate`: fetch the fixture image as a
blob, build a `DataTransfer`, and dispatch a `ClipboardEvent("paste")` on the dialog.
`Ctrl+V` cannot work — Playwright cannot portably put an image on the OS clipboard, and
an empty paste would leave the optional screenshot empty while the submit still
succeeded, giving a test that cannot fail. **Mutant: remove the `paste` listener** — the
assertion on the stored screenshot must go RED.

Per this repo's e2e practice: drive the real UI rather than posting directly,
synchronise on conditions rather than sleeps, and take **light and dark** screenshots —
a `<dialog>` in dark mode needs `user.theme` set on the user, because the theme cookie
does not reach it.

**i18n.** All model, form and template strings use `gettext_lazy`; the email module uses
eager `gettext` inside its `translation.override(...)` block. Message catalogs are
regenerated and Polish translations supplied.

## Visual design

The new views — the report dialog, the Support settings tab, the Allowed reporters page,
and the triage list and detail — are built to match the existing design language
(token-driven CSS, no Bootstrap, monochrome SVG icons using `currentColor`, never
emoji). The `frontend-design` skill is applied to these views as a final pass, after the
behaviour is complete and tested, so the visual work happens once against finished
markup. Every new view ships styled in **both** light and dark themes.

## Deployment note

`support.view_issuereport`, `support.change_issuereport` and
`support.delete_issuereport` are new permissions attached to the Platform Admin group.
**`setup_roles` must be run after `migrate`** on deploy, or the permissions exist but
are attached to nobody and the triage pages 403 for everyone. No test catches this — it
is a deployment-ordering property, and it belongs in the release checklist.

`SUPPORT_SCREENSHOT_DIR` must exist and be writable by the application user, and — like
`transfer_staging` — must **not** be exposed by the web server.
