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
  `institution.change_institution`) — its form + view are extended with the
  retention field and the purge button.

---

## Design

### 1. Data model (`institution.models.Institution`)

Add one field to the singleton:

```python
notification_retention_days = models.PositiveIntegerField(
    default=90,
    help_text=_(
        "Delete READ notifications older than this many days. 0 disables "
        "age-based deletion (orphaned notifications are still removed)."
    ),
)
```

- Default **90** days.
- **`0` = disable age-based purge** — read rows are then kept indefinitely, but
  **orphan purge still runs** (orphaned rows are dead regardless of the window).
- One additive migration (`institution/000X_...`). No change to `Notification`.

### 2. Purge service (`notifications/retention.py`)

New module (keeps the growing `services.py` focused; retention is a distinct
concern with its own target-model map).

```python
PURGE_BATCH_SIZE = 1000

# Inverse of services._resolve_target's mapping. A target_type absent here is
# skipped (never mass-deleted) — defensive against a future kind whose model
# isn't wired up yet.
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

- **Resolve the window.** `days` arg wins; else `Institution.load().notification_retention_days`.
- **Read + aged.** When `days > 0`: target rows where
  `read_at__isnull=False AND created_at < now() - timedelta(days=days)`. When
  `days == 0`: skip this category entirely (count 0).
- **Orphaned.** For each `(target_type, Model)` in `_target_models()`, select
  `Notification.objects.filter(target_type=t).exclude(target_id__in=Model.objects.values("pk"))`
  — a DB-side correlated subquery (do **not** pull all target PKs into Python).
  Applies **regardless of `read_at`**. Rows whose `target_type` is not in the map
  are left alone.
- **Dedup.** A row can be both aged-read and orphaned; count it once. Compute the
  orphaned id-set first, then the read-aged id-set **minus** the orphaned ids, so
  the two counts are disjoint and sum to the rows actually deleted.
- **Batched deletes.** Snapshot the target PKs into the two disjoint id-sets
  first (this also fixes the dry-run counts), then delete those PKs in slices of
  `PURGE_BATCH_SIZE` (`Notification.objects.filter(pk__in=slice).delete()`), so a
  large backlog never holds one long lock or loads every row at once.
  `Notification` has no cascade children, so `.delete()` is cheap.
- **`dry_run`.** Compute both id-sets and return their sizes; delete nothing.
- Returns the two counts. Emits an `INFO` log line with the result.

Single entry point; no side effects beyond the deletes; fully unit-testable with
a frozen "now" (pass `days` explicitly + create rows with backdated
`created_at`).

### 3. Management command (`notifications/management/commands/purge_notifications.py`)

Thin wrapper — parses args, calls the service, prints the result:

- `--days N` — override the setting for this run (e.g. a one-off deep clean).
- `--dry-run` — report counts, delete nothing.
- Writes `Deleted N read+aged and M orphaned notification(s).` (or, for
  dry-run, `Would delete …`) to stdout.

This is the **OS-scheduler entry point**. It adds no scheduling itself.

### 4. PA settings UI (`/manage/settings/`)

Extend the existing Phase-5c settings surface (PA-only):

- **Retention field.** The settings `ModelForm` includes
  `notification_retention_days` (rendered as a number input with the field's
  help text). Placed on the settings page under an appropriately labelled group
  (e.g. alongside the other operational limits). Saving persists it to the
  `Institution` singleton like every other setting.
- **"Purge old notifications now" button.** A separate POST (its own small form /
  submit name, distinct from the settings-save submit) that calls
  `purge_notifications()` (using the saved window) and adds a success message
  with the counts — e.g. *"Deleted 142 read and 7 orphaned notifications."*
  Gated by the same PA permission as the page. The button uses the saved setting,
  not an arbitrary value.

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

- **Service (`notifications/retention.py`):**
  - read + older than `days` → deleted; read but within window → kept; unread +
    aged (target alive) → kept.
  - orphaned (target row deleted) → deleted, **including when unread**; a row
    whose target still exists → kept.
  - a row both aged-read and orphaned is counted once (counts disjoint, sum ==
    rows actually gone).
  - `days=0` → age category skipped (read rows kept) but orphans still purged.
  - `dry_run=True` → returns non-zero counts, deletes nothing (row count
    unchanged).
  - batching: create > `PURGE_BATCH_SIZE` deletable rows and assert all are gone
    (exercises the batch loop).
  - unknown `target_type` rows are never deleted by the orphan pass.
  - window falls back to `Institution.load().notification_retention_days` when
    `days` is None.
- **Command:** `--dry-run` deletes nothing and prints "Would delete …";
  `--days N` overrides the setting; a plain run deletes and prints counts.
- **Settings UI:** the retention field renders, saving persists it to the
  singleton; the "Purge now" POST deletes eligible rows and flashes a message
  with the counts; the page/action require the PA permission (a non-PA gets the
  usual 403/redirect).
- **e2e (optional, real gesture):** a PA changes the retention field, saves, then
  clicks "Purge old notifications now" and sees the confirmation message.

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

---

## Out of scope (future)

- **Announcements** (announcement → group broadcast) — the other still-unbuilt
  half of the Notifications roadmap row.
- Async / queued email delivery (separate deferred item).
- A real in-app scheduler (Celery Beat / APScheduler) — explicitly rejected here
  in favour of the OS scheduler + manual button.
- Per-user retention overrides or a per-user "clear all" control.
