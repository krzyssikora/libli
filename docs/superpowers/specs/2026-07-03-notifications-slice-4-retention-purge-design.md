# Notifications Slice 4 — Retention / Purge — Design

*Drafted 2026-07-03. Fourth notifications slice, after Slice 1 (event
notifications + in-app list, PR #61), Slice 2 (email delivery, PR #62), and
Slice 3 (bell dropdown, PR #63). This slice bounds the unbounded growth of the
`notifications_notification` table by deleting old **read** rows and **orphaned**
rows (whose denormalized target no longer exists).*

Companion docs: [`roadmap.md`](../../roadmap.md) (Deferred → Notifications row),
`2026-07-01-notifications-slice-1-design.md`,
`2026-07-02-notifications-slice-3-bell-dropdown-design.md`.

---

## Problem

`Notification` rows accumulate without limit. Two growth vectors:

1. **Read rows never expire.** Once read, a row stays forever; the
   `/notifications/` list paginates through the entire history (25/page). (The
   bell dropdown is capped at 8, so it doesn't *display* the growth, but the rows
   are still stored.)
2. **Orphaned rows.** `Notification` stores a **denormalized** `(target_type,
   target_id)` pointer — deliberately **not** a FK — so deleting the target
   (a course or a quiz submission) leaves the notification behind. Its "Open"
   link 404s gracefully (by design), but the dead row lingers indefinitely, and
   an *unread* orphaned row keeps inflating the unread badge with something the
   user can never meaningfully act on.

There is **no Celery / task queue / scheduler** in the stack (Slice 2 was
deliberately no-Celery), so cleanup cannot run itself on a timer without an
operator-provided scheduler.

---

## Goal

- A **purge service** that deletes (a) read rows older than a retention window
  and (b) orphaned rows (target gone), in bounded batches, with a dry-run mode.
- A **management command** wrapping it — the entry point an operator schedules
  via the OS scheduler (cron / Windows Task Scheduler).
- A **PA control** on `/manage/settings/`: an editable retention-days field plus
  a "Purge old notifications now" button, so a non-technical admin can tune the
  window and run a purge on demand without any scheduler.

**No new dependency, no Celery, no scheduler package.** One additive migration.
`notify()` and the emit sites are untouched.

---

## What already exists (reused)

- `notifications.models.Notification` — fields `recipient` (CASCADE), `actor`
  (SET_NULL), `target_type` + `target_id` (denormalized, no FK), `data` (JSON),
  `created_at`, `read_at`. `read_at IS NULL` ⇒ unread. `TargetType` choices:
  `submission`, `course`.
- `notifications.services._resolve_target` — already maps a domain object to
  `(target_type, target_id)`; this slice adds the **inverse** map
  (`target_type → model`) for orphan detection. Target models:
  `courses.models.QuizSubmission` (submission), `courses.models.Course` (course).
- `institution.models.Institution` — the single-row (`pk=1`), runtime-editable
  platform-config singleton (`Institution.load()`); this slice adds one field to
  it.
- The Phase-5c PA settings surface `/manage/settings/` (PA-only, permission
  `institution.change_institution`) — a **four-tab** surface
  (`TABS = ("branding", "access", "uploads", "sso")` in `institution/views_manage.py`),
  each tab a `ModelForm` + view + POST URL sharing the `_action(...)` /
  `_index_url(...)` helpers, all panels rendered by
  `institution/manage/settings.html`. This slice adds a fifth tab + a purge
  action alongside them (§4).

---

## Design

### 1. Data model (`institution.models.Institution`)

Add one field to the singleton:

```python
MAX_RETENTION_DAYS = 3650  # 10 years — a sane policy ceiling (mirrors the form's
                           # MaxValueValidator). Incidentally also far below
                           # timedelta's ~1e9-day OverflowError limit, so an
                           # absurd value can never overflow — but the cap exists
                           # as policy, not as overflow protection.

notification_retention_days = models.PositiveIntegerField(
    default=90,
    validators=[MaxValueValidator(MAX_RETENTION_DAYS)],
    help_text=_(
        "Delete read notifications older than this many days, measured from "
        "when each notification was created. 0 keeps read notifications "
        "indefinitely; orphaned notifications are removed regardless."
    ),
)
```

- Default **90** days.
- **Aging is measured from `created_at`, not `read_at`** (I1) — a row 91 days old
  that was read yesterday is eligible now. This matches "delete old read
  notifications"; the alternative (age-since-read) is deliberately not used
  (simpler, and no need to keep a separate read-age timer). The help text says so.
- **`0` = disable age-based purge** — read rows are then kept indefinitely, but
  **orphan purge still runs** (orphaned rows are dead regardless of the window).
- `PositiveIntegerField` + `MaxValueValidator(MAX_RETENTION_DAYS)` bound the value
  to `0..3650` at the *model/form* layer. `MAX_RETENTION_DAYS` is defined **once**
  in `institution.models` (next to the field); the retention service imports it
  function-locally — the same place it imports `Institution.load()` — so there's
  a single source of truth and no new top-level `notifications → institution`
  import. The `--days` command arg bypasses form validation, so the **service
  guards both bounds** — a window `< 0` (C2) or `> MAX_RETENTION_DAYS` (policy
  ceiling, M2) raises before constructing the `timedelta` (see §2), preventing the
  negative-cutoff mass-delete.
- **i18n alias (I1):** this `help_text` is evaluated at class-body/import time, so
  its `_` **must be `gettext_lazy`** or it freezes to English (the exact eager-vs-
  lazy bug fixed in PR #46). `institution/models.py` already imports
  `gettext_lazy as _`, so use that module's alias here; any `RetentionForm`-
  declared label is likewise lazy. In-function/runtime strings (`messages.success`,
  `_("Retention settings saved.")` in `views_manage.py`) use **eager `gettext`**
  (as that module already does). Do not cross the two aliases within a module.
- One additive migration (the next sequential `institution/000N_...`). No change
  to `Notification`.

### 2. Purge service (`notifications/retention.py`)

New module (keeps the growing `services.py` focused; retention is a distinct
concern with its own target-model map).

```python
PURGE_BATCH_SIZE = 1000

# Inverse of services._resolve_target's mapping. A target_type absent here is
# skipped (never mass-deleted) — defensive against a future kind whose model
# isn't wired up yet. A test asserts full coverage (see Testing, M4) so adding a
# TargetType without wiring its model here fails loudly rather than silently
# leaving that type's orphans un-purged.
def _target_models():
    from courses.models import Course, QuizSubmission
    return {
        Notification.TargetType.SUBMISSION: QuizSubmission,
        Notification.TargetType.COURSE: Course,
    }

def purge_notifications(*, days=None, dry_run=False) -> dict:
    """Delete read-and-aged rows + orphaned rows. Returns
    {"read_aged": int, "orphaned": int}. When dry_run, counts without deleting."""
```

Behaviour:

- **Resolve the window.** `days is None` ⇒ fall back to
  `Institution.load().notification_retention_days`; an explicit int wins. So
  `None` = "use the configured setting" and `0` = "disable age purge" are
  **distinct** — the caller must pass `None`, not `0`, to mean "use the setting"
  (I2, distinct-default). After resolving, **reject an out-of-range window** —
  `raise ValueError` (or `CommandError` at the command layer), deleting nothing —
  for `days < 0` (a negative cutoff is in the *future* and would delete the entire
  read history, C2) **and** for `days > MAX_RETENTION_DAYS` (the policy ceiling
  mirroring the field's `MaxValueValidator`; it also keeps `days` far below
  `timedelta`'s overflow limit, but that safety is incidental, not the reason, M2).
- **Read + aged.** When the resolved window `> 0`: target rows where
  `read_at__isnull=False AND created_at < timezone.now() - timedelta(days=days)`
  — aged by `created_at`, `django.utils.timezone.now()` (aware, M1). The boundary
  is **strict `<`** (a row exactly `days` old is *kept*; only strictly-older rows
  are deleted, M2). When the window `== 0`: skip this category entirely (count 0).
- **Orphaned.** For each `(target_type, Model)` in `_target_models()`, select
  `Notification.objects.filter(target_type=t).exclude(target_id__in=Model.objects.values("pk"))`
  — a DB-side correlated subquery (do **not** pull all target PKs into Python).
  Applies **regardless of `read_at`**. Rows whose `target_type` is not in the map
  are left alone. This relies on `Notification.target_id` being a **non-NULL**
  `BigIntegerField` whose values are the integer PKs of the mapped models
  (`Course`/`QuizSubmission`), so the `__in` membership test is type-compatible and
  has no NULL three-valued-logic surprise (M1, r5+r6); `_resolve_target` always
  writes `target_type` and an integer `target_id` together, so a mapped-type row
  never has a NULL id.
- **Dedup.** A row can be both aged-read and orphaned; count it once. Compute the
  orphaned id-set first, then the read-aged id-set **minus** the orphaned ids, so
  the two counts are disjoint and sum to the rows actually deleted.
- **Batched deletes.** Snapshot the target PKs into the two disjoint id-**sets**
  first (needed for the dedup arithmetic + exact dry-run counts), then
  **materialize the union to a `list`** and delete it in slices of
  `PURGE_BATCH_SIZE` (`Notification.objects.filter(pk__in=chunk).delete()` — a
  `set` is not sliceable, M2), so no single DELETE holds a long lock or loads
  every *row object* at once. The per-chunk deletes are **intentionally not wrapped
  in one transaction** — an interruption (proxy timeout, killed cron) leaves a
  partial purge, which is safe because a re-run is idempotent (delete-by-pk over
  freshly-recomputed id-sets). No all-or-nothing atomicity is offered or needed
  (M3).
  `Notification` has no cascade children, so `.delete()` is cheap.
  - **Memory (I4):** the id-sets hold every matching PK (ints), so this is O(N)
    in PKs, not truly constant-memory — an accepted trade-off at the expected
    single-school scale (thousands, not millions; a few thousand ints is
    negligible). The batching bounds *lock/statement* size, not total PK memory.
    A streaming iterator is out of scope unless profiling ever shows it matters.
  - **Counts are best-effort snapshots (M4):** a row present at snapshot time but
    concurrently deleted/read before its slice runs is counted yet removes
    nothing (delete-by-pk is idempotent, so this is harmless). Tests must not
    assert "sum == rows removed" under concurrency; assert the *eligible rows are
    gone* and the counts on a quiescent DB.
- **`dry_run`.** Compute both id-sets and return their sizes; delete nothing.
- Returns the two counts. Emits one `INFO` log line via a module logger
  (`logging.getLogger("notifications.retention")`) that includes the **`dry_run`
  flag, the resolved window, and both counts** (M5) — so a dry-run and a real
  purge are distinguishable in the ops log (e.g.
  `retention purge (dry_run=False, days=90): 142 read, 7 orphaned`).

Single entry point; no side effects beyond the deletes; fully unit-testable.
**Test-writing gotcha (I1):** `Notification.created_at` is `auto_now_add=True`, so
`objects.create(created_at=…)` is silently overwritten with the current time. To
backdate a row for an aging/boundary test, create it then
`Notification.objects.filter(pk=…).update(created_at=…)` (which bypasses
`auto_now_add`), or mock `timezone.now`. Never rely on `create(created_at=…)`.

### 3. Management command (`notifications/management/commands/purge_notifications.py`)

Thin wrapper — parses args, calls the service, prints the result:

- `--days N` — override the setting for this run (e.g. a one-off deep clean).
  Declared `add_argument("--days", type=int, default=None)` — **`type=int` is
  required** so a non-numeric arg is rejected at parse time and the value reaching
  the service is always an `int`; otherwise the service's numeric guards would hit
  a `TypeError` (str vs int) that the `except ValueError` misses, re-introducing
  the traceback (I1, round 5). **Defaults to `None`** (option omitted ⇒ the
  service falls back to the configured `Institution` window). A plain scheduled run therefore honours the
  setting; only an explicit `--days 0` disables age purge. The command **wraps the
  service call in `try/except ValueError → raise CommandError`** so *both*
  out-of-range bounds (`< 0`, C2; `> MAX_RETENTION_DAYS`, I2) surface as a clean
  one-line error rather than a traceback; nothing is deleted before the service
  validates.
- `--dry-run` — report counts, delete nothing.
- Writes the **canonical result phrasing** produced by a single shared formatter
  `format_purge_result(counts, *, dry_run) -> str` in `retention.py`, which both
  the command and the PA button call (so the wording cannot drift — M1).

**Message i18n (I1).** The two counts vary independently, so a single sentence
with a literal `(s)` can't be pluralized (`ngettext` keys on one number; Polish
has 3–4 forms). Sidestep pluralization with a **label : number** form, where the
counts are plain trailing numbers that need no grammatical agreement:

- real: `_("Notifications purged — read: %(read_aged)d, orphaned: %(orphaned)d")`
- dry-run: `_("Would purge — read: %(read_aged)d, orphaned: %(orphaned)d")`

The placeholder names **match the returned dict keys** (`read_aged`/`orphaned`) so
`format_purge_result` can interpolate `msgid % counts` directly with no remapping
and no `KeyError` (M2); the visible label stays "read".

These two `gettext` msgids (plus the retention **help text**, the tab **label**,
the **"Save"/"Purge old notifications now"** button labels, the save-first
**hint**, and the `"Retention settings saved."` success) get EN/PL `.po` entries
and a recompiled `.mo`, per the project's bilingual discipline (watch the
`makemessages` fuzzy-flag gotcha). The `format_purge_result` output is used
verbatim by both surfaces.

This is the **OS-scheduler entry point**. It adds no scheduling itself.

### 4. PA settings UI (`/manage/settings/`)

The settings surface is **not** a single ModelForm — it is four independent
tabs, each with its own `ModelForm`, its own view, and its own POST URL, all
rendered by `institution/manage/settings.html`. `TABS = ("branding", "access",
"uploads", "sso")`; each tab's form is saved by a small view that delegates to
the shared `_action(request, form_cls, ctx_key, tab, success_msg)` helper
(GET→redirect to `?tab=`, POST→validate+save+message+redirect), and
`_settings_context` seeds every form on each render. This slice follows that
established pattern rather than a submit-name branch (C1).

- **New "notifications" tab.** Use the **single identifier `"notifications"` for
  the tab id AND the context key** (matching the existing 1:1 convention —
  branding/access/uploads/sso — so `_active_tab`/`_index_url`/`TABS` and the
  panel/`_settings_context` all key off the same string; only the *form class* is
  named `RetentionForm`, M3). Concretely:
  - Add `"notifications"` to `TABS`.
  - New `RetentionForm(forms.ModelForm)`, `Meta.fields = ["notification_retention_days"]`
    (number input carrying the field's help text).
  - **Extend `_settings_context`** — it does not iterate `TABS`; it takes one
    keyword-only form param per tab (`*, branding=None, access=None, uploads=None,
    sso=None`). Add a `notifications=None` param and a
    `"notifications": notifications or RetentionForm(instance=inst)` entry seeded on
    **every** render (settings.html renders all panels each time; and the `_action`
    error-path passes `**{ "notifications": form }`, which would `TypeError` on an
    unknown kwarg otherwise).
  - Add a panel to `settings.html`, plus a `settings_notifications` view +
    `institution:settings_notifications` URL calling
    `_action(request, RetentionForm, "notifications", "notifications", _("Retention settings saved."))`.
    Saving persists the window to the `Institution` singleton like every other tab.
  - **Audit:** adding a fifth `TABS` entry breaks any existing settings test that
    pins the exact 4-tuple or the rendered-tab count — grep and update those, and
    make sure every place that iterates `TABS` (the template tab strip,
    `_active_tab`) accounts for the new tab.
- **"Purge old notifications now" button.** A **separate** PA-gated POST view +
  URL (e.g. `settings_notifications_purge` / `institution:settings_notifications_purge`,
  guarded by `permission_required("institution.change_institution")` like the
  other settings views), rendered as its own small form on the notifications
  panel. It calls `purge_notifications()` (no args ⇒ uses the **saved**
  `Institution` window), then `messages.success(format_purge_result(counts, dry_run=False))`
  — the **same shared formatter** the command uses (M1), e.g. *"Notifications
  purged — read: 142, orphaned: 7"* — and redirects to `_index_url("notifications")`.
- **Saved-value UX (I5).** Because the purge view reads the *persisted*
  `Institution` window (it does not receive the form field), an admin who edits
  the number but clicks Purge **without saving first** would purge against the
  old value. Make this explicit: render a short hint on the panel — *"Purge uses
  the saved retention value; save your changes first."* — next to the button.
  (The two forms are independent: the retention `<form>` saves the field, the
  purge `<form>` runs the action.)
- **Synchronous-run bound (I3).** The button runs the purge inline in the request.
  At the expected single-school scale this is fine (the batched deletes keep each
  statement small). The **first-ever purge of a very large accumulated backlog**
  is the case that could approach an HTTP/proxy timeout — document that the
  button is for routine/incremental cleanup and that a large first-run backlog
  should be cleared with the management command (§3) instead. No async job is
  added.

### 5. Docs

A deploy note (in the local-development / deployment docs) showing how to
schedule the command, both a cron line and the Windows Task Scheduler
equivalent, e.g. daily:

```
# crontab (daily 03:30)
30 3 * * * cd /app && uv run python manage.py purge_notifications
```

State plainly that **without** a scheduled command (or manual PA purges), rows
are not auto-deleted — the app ships correct, just growing.

---

## Testing

- **Service (`notifications/retention.py`):** (backdate `created_at` via
  `queryset.update(created_at=…)`, never `create(created_at=…)` — auto_now_add, I1)
  - read + `created_at` older than the window → deleted; read but within window →
    kept; unread + aged (target alive) → kept.
  - orphaned (target row deleted) → deleted, **including when unread**; a row
    whose target still exists → kept.
  - a row both aged-read and orphaned is counted once — on a **quiescent** DB the
    two counts are disjoint and their sum equals the rows removed (do not assert
    this under concurrency — M4).
  - **`days=0` → age category skipped** (read rows kept) but orphans still purged;
    **`days=None` → uses the `Institution` setting** — assert these two are
    distinct (I2).
  - **out-of-range window → raises** and deletes nothing: `days < 0` (C2) **and**
    `days > MAX_RETENTION_DAYS` (I2, guards the `timedelta` overflow).
  - **boundary:** a row whose `created_at` is *exactly* `days` old is **kept**
    (strict `<`); one a second older is deleted (M2). The **kept** half requires a
    **single frozen `now`** shared by row construction and the service (mock/freeze
    `timezone.now` to one reference, then set `created_at = frozen_now -
    timedelta(days=days)`) — otherwise the service's own later `now()` moves the
    cutoff past the row and deletes it, failing the assertion (I1, round 4). The
    "one second older → deleted" half is robust without freezing.
  - **target-type coverage (M4):** assert `set(_target_models()) == set(Notification.TargetType)`
    so a future `TargetType` added without wiring its model fails loudly.
  - `dry_run=True` → returns non-zero counts, deletes nothing (row count
    unchanged).
  - batching: create > `PURGE_BATCH_SIZE` deletable rows and assert all are gone
    (exercises the batch loop).
  - unknown `target_type` rows are never deleted by the orphan pass.
  - window falls back to `Institution.load().notification_retention_days` when
    `days` is None.
- **Command:** `--dry-run` deletes nothing and prints the formatter's dry-run
  string (asserts on **"Would purge"**, the actual `format_purge_result` output —
  M1); `--days N` overrides the setting; `--days` omitted uses the setting (not 0);
  `--days -1` **and** `--days 99999` (> MAX_RETENTION_DAYS) each raise a clean
  `CommandError` (no traceback) and delete nothing (I2); a plain run deletes and
  prints the canonical message.
- **Settings UI:** the new **notifications** tab renders the retention field;
  POSTing `settings_notifications` persists it to the singleton; **seed one aged-read
  and one orphaned row** — the aged-read row's `created_at` backdated **strictly
  beyond the saved window** (e.g. save a small window, or backdate well past 90
  days), so `read: 1` is deterministic (M2, round 4) — then POSTing
  `settings_notifications_purge` deletes them and flashes the canonical message
  showing the **non-zero counts** (read: 1, orphaned: 1); assert the rows are
  actually gone, not just that a banner appeared (M3); both views require `institution.change_institution` (a non-PA
  gets the 403/redirect); the purge view uses the **saved** window
  (edit-without-save does not affect the run — I5).
- **e2e (optional, real gesture):** with an aged-read + orphaned row seeded, a PA
  opens the notifications tab, changes the retention field, saves, then clicks
  "Purge old notifications now" and sees the confirmation banner with non-zero
  counts (M3).

---

## Scope guardrails

- **One additive migration** (the `Institution` field). No `Notification` schema
  change.
- **No scheduler dependency / no Celery.** The command is scheduler-agnostic; the
  OS scheduler (or the PA button) drives it.
- `notify()`, the emit sites, email delivery, the bell dropdown, and the
  `/notifications/` list view are all untouched (the list simply paginates over
  fewer rows after a purge).
- Orphan detection is limited to the `target_type`s present in `_target_models()`;
  adding a future target type requires adding it there (and is the safe default —
  unmapped types are never purged).
- **No new index (M3).** The read+aged filter (`read_at`, `created_at`) and the
  orphan `exclude(... __in=...)` scan have no dedicated covering index, and the
  existing `notif_unread_idx` (partial, `read_at IS NULL`) does not serve them. At
  the expected single-school scale a sequential scan during an occasional
  scheduled/manual purge is acceptable. A covering index is deferred unless
  profiling on a real deployment shows it matters (it would make the migration
  non-trivial, so it is out of scope here).

---

## Out of scope (future)

- **Announcements** (announcement → group broadcast) — the other still-unbuilt
  half of the Notifications roadmap row.
- Async / queued email delivery (separate deferred item).
- A real in-app scheduler (Celery Beat / APScheduler) — explicitly rejected here
  in favour of the OS scheduler + manual button.
- Per-user retention overrides or a per-user "clear all" control.
