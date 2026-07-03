# Notifications Slice 4 — Retention / Purge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound the unbounded growth of the `notifications_notification` table by deleting old **read** rows and **orphaned** rows (target deleted), via a purge service + a management command (OS-scheduler entry point) + a PA settings tab with a retention-days field and a "Purge now" button.

**Architecture:** A pure `notifications/retention.py` service does the work (resolve window → collect orphaned + read-aged PK sets → batched delete); a thin management command wraps it as the scheduler entry point; a new "notifications" settings tab (reusing the existing four-tab `_action`/`_settings_context` pattern) exposes an editable retention window + a separate purge-action view. One additive `Institution` field. No Celery, no scheduler dependency, no `Notification` schema change.

**Tech Stack:** Django 5.2, PostgreSQL, pytest + factory_boy, Django i18n (EN/PL `.po`/`.mo`), Django management commands.

## Global Constraints

- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH — use `uv run ruff`, `uv run pytest`, `uv run python manage.py`. Run `uv run ruff format` (not just check) before committing; CI checks `ruff format --check`. `pytest -q` drops its summary line in this env — use `-v` or `--junitxml` to confirm counts.
- **No new dependency, no Celery, no scheduler package. One additive migration** (`Institution` field only). `notify()`, the emit sites, email delivery, the bell dropdown, and the `/notifications/` list are all untouched.
- **`MAX_RETENTION_DAYS = 3650`**, retention default **90**, `0` disables age-purge (orphans still purged). Window bounds `0..3650` enforced by `MaxValueValidator` (model/form) AND the service (guards the `--days` bypass).
- **Aging is measured from `created_at`** with a **strict `<`** boundary (a row exactly `days` old is kept).
- **i18n alias discipline:** module-level/class-body translatable strings (model `help_text`, form labels) use **`gettext_lazy`**; in-function/runtime strings (view messages, the `format_purge_result` output) use **eager `gettext`**. Never cross the two within a module. (`institution/models.py` already imports `gettext_lazy as _`; `institution/views_manage.py` already imports `gettext as _`.)
- **Bilingual:** every new user-facing string gets EN + PL `.po` entries + recompiled `.mo`. `makemessages` re-marks copied translations `#, fuzzy` and can mis-guess — grep new msgids and verify.
- **No hardcoded test passwords:** use the `make_pa`/`make_login` factory helpers (they use `tests.factories.TEST_PASSWORD`).
- **`Notification.created_at` is `auto_now_add=True`** — tests MUST backdate via `Notification.objects.filter(pk=…).update(created_at=…)` (or freeze `timezone.now`), never `create(created_at=…)`.
- **Commit-message trailers:** end each commit body with the repo's `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01Y3PMizmctCAMpfW88vcRou` trailers.

## File Structure

- `institution/models.py` — **modify**: add `MAX_RETENTION_DAYS` constant + `notification_retention_days` field.
- `institution/migrations/` — **create** one generated migration (the exact filename is auto-assigned by `makemigrations`, e.g. `00NN_institution_notification_retention_days.py`; the `000N_notification_retention_days.py` names used below are illustrative).
- `notifications/retention.py` — **create**: `PURGE_BATCH_SIZE`, `_target_models`, `_resolve_window`, `purge_notifications`, `format_purge_result`, module logger.
- `notifications/management/__init__.py`, `notifications/management/commands/__init__.py`, `notifications/management/commands/purge_notifications.py` — **create**: the command.
- `institution/forms.py` — **modify**: `RetentionForm`.
- `institution/views_manage.py` — **modify**: `TABS`, `_settings_context`, `settings_notifications`, `settings_notifications_purge`.
- `institution/urls.py` — **modify**: two new URLs.
- `templates/institution/manage/_tabs.html` — **modify**: add the Notifications tab link.
- `templates/institution/manage/settings.html` — **modify**: include the new panel.
- `templates/institution/manage/_notifications_tab.html` — **create**: the panel (retention form + purge form + hint).
- `docs/local-development.md` — **modify**: scheduling note.
- `locale/en|pl/LC_MESSAGES/django.po` + `.mo` — **modify**: new strings.
- Tests (**create**): `notifications/tests/test_retention.py` (field + service), `notifications/tests/test_purge_command.py`, `notifications/tests/test_retention_settings.py`, `notifications/tests/test_retention_i18n.py`.

**Scope note (no Playwright e2e):** the spec marks e2e optional. The notifications panel has **no client-side JS** (both the retention save and the purge are plain form POSTs — unlike the bell dropdown's keepalive fetch), so the Django-test-client integration tests in Task 4 fully exercise save→persist and purge→delete→message→permission. A real-browser e2e would add flakiness for no coverage gain, so it is deliberately omitted (YAGNI).

---

### Task 1: `Institution.notification_retention_days` field + migration

**Files:**
- Modify: `institution/models.py`
- Create: one generated migration under `institution/migrations/` (name auto-assigned by `makemigrations`; `000N_notification_retention_days.py` is illustrative — `git add institution/migrations/` in Step 6 picks up whatever name it gets)
- Test: `notifications/tests/test_retention.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `institution.models.MAX_RETENTION_DAYS = 3650` and the `Institution.notification_retention_days` `PositiveIntegerField(default=90, validators=[MaxValueValidator(3650)])`.

- [ ] **Step 1: Write the failing test**

Create `notifications/tests/test_retention.py`:

```python
import pytest
from django.core.exceptions import ValidationError

from institution.models import MAX_RETENTION_DAYS
from institution.models import Institution

pytestmark = pytest.mark.django_db


def test_retention_field_default_is_90():
    assert Institution.load().notification_retention_days == 90


def test_retention_field_rejects_over_ceiling():
    inst = Institution.load()
    inst.notification_retention_days = MAX_RETENTION_DAYS + 1
    with pytest.raises(ValidationError):
        inst.full_clean()


def test_retention_field_accepts_zero_and_ceiling():
    inst = Institution.load()
    for v in (0, MAX_RETENTION_DAYS):
        inst.notification_retention_days = v
        inst.full_clean()  # no raise
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest notifications/tests/test_retention.py -v`
Expected: FAIL — `ImportError: cannot import name 'MAX_RETENTION_DAYS'` / `AttributeError` for the field.

- [ ] **Step 3: Add the constant + field to `institution/models.py`**

At the top of `institution/models.py`, add to the imports (the module already has `from django.db import models` and `from django.utils.translation import gettext_lazy as _`):

```python
from django.core.validators import MaxValueValidator
```

Inside `class Institution(models.Model)`, add the constant and field (place the field alongside the other config fields, e.g. after `onboarded`):

```python
    MAX_RETENTION_DAYS = 3650  # 10-year policy ceiling (mirrors the form validator).

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

Also add a module-level alias right after the class so `from institution.models import MAX_RETENTION_DAYS` works (the service imports it this way):

```python
MAX_RETENTION_DAYS = Institution.MAX_RETENTION_DAYS
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations institution`
Expected: creates `institution/migrations/000N_notification_retention_days.py` with one `AddField`. Confirm it is purely additive (no data migration).

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest notifications/tests/test_retention.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format institution/models.py notifications/tests/test_retention.py
uv run ruff check institution/models.py notifications/tests/test_retention.py
git add institution/models.py institution/migrations/ notifications/tests/test_retention.py
git commit -m "feat(notifications): Institution.notification_retention_days field"
```

---

### Task 2: Purge service `notifications/retention.py`

**Files:**
- Create: `notifications/retention.py`
- Test: `notifications/tests/test_retention.py` (append)

**Interfaces:**
- Consumes: `Institution.load().notification_retention_days` + `institution.models.MAX_RETENTION_DAYS` (Task 1); `Notification` (`TargetType`, `target_type`, `target_id`, `read_at`, `created_at`); `courses.models.Course` / `QuizSubmission`.
- Produces: `PURGE_BATCH_SIZE=1000`; `_target_models() -> dict[TargetType, Model]`; `purge_notifications(*, days=None, dry_run=False) -> {"read_aged": int, "orphaned": int}` (raises `ValueError` on out-of-range window); `format_purge_result(counts, *, dry_run) -> str`.

- [ ] **Step 1: Write the failing tests**

Append the test functions below to `notifications/tests/test_retention.py`. **Import placement matters:** the new `import`/`from` lines shown first must be merged into the existing top-of-file import block created in Task 1 — do NOT paste them below the Task 1 test functions. Ruff selects `E` and `I` (pyproject.toml), so module-level imports after code trip `E402` (not auto-fixable) plus `I001`, which fails the Step 5 `ruff check` gate. Only the `def test_*` bodies get appended; the imports move up top.

```python
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from notifications.models import Notification
from notifications.retention import format_purge_result
from notifications.retention import purge_notifications
from tests.factories import CourseFactory
from tests.factories import UserFactory


def _notif(user, *, ttype, tid, read, days_old=None, kind=Notification.Kind.ENROLLED):
    n = Notification.objects.create(
        recipient=user,
        kind=kind,
        target_type=ttype,
        target_id=tid,
        read_at=timezone.now() if read else None,
        data={},
    )
    if days_old is not None:
        Notification.objects.filter(pk=n.pk).update(
            created_at=timezone.now() - timedelta(days=days_old)
        )
    return n


def test_read_aged_deleted_recent_and_unread_kept():
    u = UserFactory()
    c = CourseFactory()
    aged = _notif(u, ttype="course", tid=c.pk, read=True, days_old=100)
    recent = _notif(u, ttype="course", tid=c.pk, read=True, days_old=10)
    unread_aged = _notif(u, ttype="course", tid=c.pk, read=False, days_old=100)
    counts = purge_notifications(days=90)
    assert counts["read_aged"] == 1
    assert not Notification.objects.filter(pk=aged.pk).exists()
    assert Notification.objects.filter(pk=recent.pk).exists()
    assert Notification.objects.filter(pk=unread_aged.pk).exists()


def test_orphaned_deleted_including_unread_alive_kept():
    u = UserFactory()
    alive = CourseFactory()
    dead = CourseFactory()
    dead_pk = dead.pk
    dead.delete()
    orphan_unread = _notif(u, ttype="course", tid=dead_pk, read=False, days_old=1)
    alive_row = _notif(u, ttype="course", tid=alive.pk, read=False, days_old=1)
    counts = purge_notifications(days=90)
    assert counts["orphaned"] == 1
    assert not Notification.objects.filter(pk=orphan_unread.pk).exists()
    assert Notification.objects.filter(pk=alive_row.pk).exists()


def test_row_both_aged_and_orphaned_counted_once():
    u = UserFactory()
    c = CourseFactory()
    c_pk = c.pk
    c.delete()  # orphaned
    both = _notif(u, ttype="course", tid=c_pk, read=True, days_old=100)  # also aged
    counts = purge_notifications(days=90)
    assert counts == {"read_aged": 0, "orphaned": 1}  # counted once, as orphaned
    assert not Notification.objects.filter(pk=both.pk).exists()


def test_days_zero_skips_age_but_orphans_purged():
    u = UserFactory()
    alive = CourseFactory()  # aged row points here so it is NOT orphaned
    dead = CourseFactory()
    dead_pk = dead.pk
    aged = _notif(u, ttype="course", tid=alive.pk, read=True, days_old=100)
    dead.delete()
    orphan = _notif(u, ttype="course", tid=dead_pk, read=False, days_old=1)
    counts = purge_notifications(days=0)
    assert counts == {"read_aged": 0, "orphaned": 1}
    assert Notification.objects.filter(pk=aged.pk).exists()  # age skipped
    assert not Notification.objects.filter(pk=orphan.pk).exists()


def test_days_none_uses_institution_setting():
    inst = Institution.load()
    inst.notification_retention_days = 30
    inst.save()
    u = UserFactory()
    c = CourseFactory()
    aged = _notif(u, ttype="course", tid=c.pk, read=True, days_old=40)
    kept = _notif(u, ttype="course", tid=c.pk, read=True, days_old=20)
    counts = purge_notifications(days=None)
    assert counts["read_aged"] == 1
    assert not Notification.objects.filter(pk=aged.pk).exists()
    assert Notification.objects.filter(pk=kept.pk).exists()


def test_out_of_range_window_raises_and_deletes_nothing():
    u = UserFactory()
    c = CourseFactory()
    _notif(u, ttype="course", tid=c.pk, read=True, days_old=100)
    before = Notification.objects.count()
    for bad in (-1, MAX_RETENTION_DAYS + 1):
        with pytest.raises(ValueError):
            purge_notifications(days=bad)
    assert Notification.objects.count() == before


def test_boundary_exact_is_kept_one_second_older_deleted():
    u = UserFactory()
    c = CourseFactory()
    frozen = timezone.now()
    with mock.patch("notifications.retention.timezone.now", return_value=frozen):
        exact = _notif(u, ttype="course", tid=c.pk, read=True)
        Notification.objects.filter(pk=exact.pk).update(
            created_at=frozen - timedelta(days=30)
        )
        older = _notif(u, ttype="course", tid=c.pk, read=True)
        Notification.objects.filter(pk=older.pk).update(
            created_at=frozen - timedelta(days=30, seconds=1)
        )
        purge_notifications(days=30)
    assert Notification.objects.filter(pk=exact.pk).exists()  # exactly 30d → kept
    assert not Notification.objects.filter(pk=older.pk).exists()  # older → deleted


def test_target_models_covers_every_target_type():
    from notifications.retention import _target_models

    assert set(_target_models()) == set(Notification.TargetType)


def test_dry_run_counts_without_deleting():
    u = UserFactory()
    c = CourseFactory()
    _notif(u, ttype="course", tid=c.pk, read=True, days_old=100)
    before = Notification.objects.count()
    counts = purge_notifications(days=90, dry_run=True)
    assert counts["read_aged"] == 1
    assert Notification.objects.count() == before  # nothing deleted


def test_batching_deletes_more_than_one_batch():
    from notifications.retention import PURGE_BATCH_SIZE

    u = UserFactory()
    c = CourseFactory()
    rows = [
        Notification(
            recipient=u,
            kind=Notification.Kind.ENROLLED,
            target_type="course",
            target_id=c.pk,
            read_at=timezone.now(),
            data={},
        )
        for _ in range(PURGE_BATCH_SIZE + 5)
    ]
    Notification.objects.bulk_create(rows)
    Notification.objects.filter(recipient=u).update(
        created_at=timezone.now() - timedelta(days=100)
    )
    counts = purge_notifications(days=90)
    assert counts["read_aged"] == PURGE_BATCH_SIZE + 5
    assert Notification.objects.filter(recipient=u).count() == 0


def test_unmapped_target_type_ignored_by_orphan_pass():
    u = UserFactory()
    # A target_type not in _target_models() must never be touched by the orphan
    # pass. .create() does not enforce the field's choices, so we can store a
    # bogus type; unread so the age pass ignores it too.
    row = Notification.objects.create(
        recipient=u,
        kind=Notification.Kind.ENROLLED,
        target_type="bogus_unmapped",
        target_id=1,
        read_at=None,
        data={},
    )
    purge_notifications(days=90)
    assert Notification.objects.filter(pk=row.pk).exists()


def test_format_purge_result_real_and_dry():
    counts = {"read_aged": 142, "orphaned": 7}
    assert "read: 142" in format_purge_result(counts, dry_run=False)
    assert "orphaned: 7" in format_purge_result(counts, dry_run=False)
    assert format_purge_result(counts, dry_run=True).startswith("Would purge")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest notifications/tests/test_retention.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notifications.retention'`.

- [ ] **Step 3: Implement `notifications/retention.py`**

Create `notifications/retention.py`:

```python
"""Retention/purge for notifications: delete read-and-aged + orphaned rows.

A distinct concern from services.py (its own target-model map). The only entry
point is purge_notifications(); format_purge_result() is the shared message
formatter used by the management command and the PA "Purge now" button.
"""

import logging
from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext as _  # runtime strings → eager

from notifications.models import Notification

logger = logging.getLogger("notifications.retention")

PURGE_BATCH_SIZE = 1000


def _target_models():
    # Inverse of services._resolve_target's mapping. A target_type absent here is
    # skipped (never mass-deleted). test_target_models_covers_every_target_type
    # asserts full coverage so a future TargetType fails loudly instead of
    # silently leaving its orphans un-purged. Function-local import: avoids a
    # top-level notifications -> courses import.
    from courses.models import Course
    from courses.models import QuizSubmission

    return {
        Notification.TargetType.SUBMISSION: QuizSubmission,
        Notification.TargetType.COURSE: Course,
    }


def _resolve_window(days):
    """None -> Institution setting; validate 0..MAX_RETENTION_DAYS. Function-local
    institution import keeps a single source of truth with no top-level cycle."""
    from institution.models import MAX_RETENTION_DAYS
    from institution.models import Institution

    if days is None:
        days = Institution.load().notification_retention_days
    if days < 0 or days > MAX_RETENTION_DAYS:
        raise ValueError(
            f"retention window must be 0..{MAX_RETENTION_DAYS}, got {days}"
        )
    return days


def purge_notifications(*, days=None, dry_run=False) -> dict:
    days = _resolve_window(days)

    # Orphaned first (regardless of read state) — DB-side correlated subquery.
    orphaned_ids = set()
    for target_type, model in _target_models().items():
        qs = Notification.objects.filter(target_type=target_type).exclude(
            target_id__in=model.objects.values("pk")
        )
        orphaned_ids.update(qs.values_list("pk", flat=True))

    # Read + aged (strict <), disjoint from orphaned so counts don't double.
    read_aged_ids = set()
    if days > 0:
        cutoff = timezone.now() - timedelta(days=days)
        qs = Notification.objects.filter(read_at__isnull=False, created_at__lt=cutoff)
        read_aged_ids = set(qs.values_list("pk", flat=True)) - orphaned_ids

    counts = {"read_aged": len(read_aged_ids), "orphaned": len(orphaned_ids)}

    if not dry_run:
        all_ids = list(orphaned_ids | read_aged_ids)  # set is not sliceable
        for i in range(0, len(all_ids), PURGE_BATCH_SIZE):
            chunk = all_ids[i : i + PURGE_BATCH_SIZE]
            Notification.objects.filter(pk__in=chunk).delete()

    logger.info(
        "retention purge (dry_run=%s, days=%s): %s read, %s orphaned",
        dry_run,
        days,
        counts["read_aged"],
        counts["orphaned"],
    )
    return counts


def format_purge_result(counts, *, dry_run):
    """Canonical user-facing message for both the command and the PA button.
    Placeholder keys match the counts dict, so `template % counts` needs no
    remapping. label:number form (no plural agreement — Polish-safe)."""
    template = (
        _("Would purge — read: %(read_aged)d, orphaned: %(orphaned)d")
        if dry_run
        else _("Notifications purged — read: %(read_aged)d, orphaned: %(orphaned)d")
    )
    return template % counts
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest notifications/tests/test_retention.py -v`
Expected: PASS (all service + field tests green).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format notifications/retention.py notifications/tests/test_retention.py
uv run ruff check notifications/retention.py notifications/tests/test_retention.py
git add notifications/retention.py notifications/tests/test_retention.py
git commit -m "feat(notifications): retention purge service (read-aged + orphaned)"
```

---

### Task 3: Management command + scheduling doc

**Files:**
- Create: `notifications/management/__init__.py`, `notifications/management/commands/__init__.py`, `notifications/management/commands/purge_notifications.py`
- Modify: `docs/local-development.md`
- Test: `notifications/tests/test_purge_command.py` (create)

**Interfaces:**
- Consumes: `purge_notifications`, `format_purge_result` (Task 2).
- Produces: `manage.py purge_notifications [--days N] [--dry-run]`.

- [ ] **Step 1: Write the failing tests**

Create `notifications/tests/test_purge_command.py`:

```python
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from institution.models import Institution
from institution.models import MAX_RETENTION_DAYS
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _aged_read(user, course, days_old):
    n = Notification.objects.create(
        recipient=user,
        kind=Notification.Kind.ENROLLED,
        target_type="course",
        target_id=course.pk,
        read_at=timezone.now(),
        data={},
    )
    Notification.objects.filter(pk=n.pk).update(
        created_at=timezone.now() - timedelta(days=days_old)
    )
    return n


def test_plain_run_deletes_and_prints():
    u = UserFactory()
    c = CourseFactory()
    _aged_read(u, c, 100)
    out = StringIO()
    call_command("purge_notifications", stdout=out)
    assert "Notifications purged" in out.getvalue()
    assert Notification.objects.count() == 0


def test_dry_run_prints_would_purge_and_deletes_nothing():
    u = UserFactory()
    c = CourseFactory()
    _aged_read(u, c, 100)
    out = StringIO()
    call_command("purge_notifications", "--dry-run", stdout=out)
    assert "Would purge" in out.getvalue()
    assert Notification.objects.count() == 1


def test_days_overrides_setting():
    inst = Institution.load()
    inst.notification_retention_days = 0  # setting would skip age purge
    inst.save()
    u = UserFactory()
    c = CourseFactory()
    _aged_read(u, c, 100)
    call_command("purge_notifications", "--days", "90")  # explicit override
    assert Notification.objects.count() == 0


def test_negative_and_over_max_raise_command_error():
    u = UserFactory()
    c = CourseFactory()
    _aged_read(u, c, 100)
    for bad in ("-1", str(MAX_RETENTION_DAYS + 1)):
        with pytest.raises(CommandError):
            call_command("purge_notifications", "--days", bad)
    assert Notification.objects.count() == 1  # nothing deleted
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest notifications/tests/test_purge_command.py -v`
Expected: FAIL — `CommandError: Unknown command: 'purge_notifications'`.

- [ ] **Step 3: Create the command package + command**

Create empty `notifications/management/__init__.py` and `notifications/management/commands/__init__.py` (both empty files).

Create `notifications/management/commands/purge_notifications.py`:

```python
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from notifications.retention import format_purge_result
from notifications.retention import purge_notifications


class Command(BaseCommand):
    help = "Delete read-and-aged and orphaned notifications (retention purge)."

    def add_arguments(self, parser):
        # type=int is required: a str window would hit a TypeError in the
        # service's numeric guards that our except ValueError would miss.
        parser.add_argument("--days", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            counts = purge_notifications(
                days=options["days"], dry_run=options["dry_run"]
            )
        except ValueError as exc:  # out-of-range window → clean CLI error
            raise CommandError(str(exc)) from exc
        self.stdout.write(format_purge_result(counts, dry_run=options["dry_run"]))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest notifications/tests/test_purge_command.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Add the scheduling note to `docs/local-development.md`**

Append this section to `docs/local-development.md` (create the section at the end of the file). **Fence note:** the block below is wrapped in a FOUR-backtick ````` ````markdown ````` / ````` ```` ````` pair — that outer four-backtick pair is only the plan's wrapper and is NOT copied. Everything between them (including the inner three-backtick ```` ```bash ```` and ```` ```cron ```` fences, which ARE part of the doc content) is exactly what goes into `docs/local-development.md`. There is only ONE closing wrapper fence.

````markdown
## Scheduling notification purge

Read + aged and orphaned notifications are removed by a management command.
There is no built-in scheduler — point your OS scheduler at it (or use the
"Purge old notifications now" button on `/manage/settings/` → Notifications).

```bash
# Dry run (report only, deletes nothing)
uv run python manage.py purge_notifications --dry-run

# Real run (honours the retention window configured in settings)
uv run python manage.py purge_notifications
```

Schedule it daily:

```cron
# crontab (daily 03:30)
30 3 * * * cd /app && uv run python manage.py purge_notifications
```

On Windows, create a Task Scheduler task running
`uv run python manage.py purge_notifications` in the project directory on a
daily trigger.

**Without** a scheduled command (or manual purges) notifications are never
auto-deleted — the app is correct, the table just grows.
````

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format notifications/management/ notifications/tests/test_purge_command.py
uv run ruff check notifications/management/ notifications/tests/test_purge_command.py
git add notifications/management/ notifications/tests/test_purge_command.py docs/local-development.md
git commit -m "feat(notifications): purge_notifications management command + deploy note"
```

---

### Task 4: PA settings "notifications" tab (form + views + urls + templates)

**Files:**
- Modify: `institution/forms.py` (add `RetentionForm`), `institution/views_manage.py` (`TABS`, `_settings_context`, two views), `institution/urls.py` (two URLs)
- Modify: `templates/institution/manage/_tabs.html`, `templates/institution/manage/settings.html`
- Create: `templates/institution/manage/_notifications_tab.html`
- Test: `notifications/tests/test_retention_settings.py` (create)

**Interfaces:**
- Consumes: `purge_notifications`, `format_purge_result` (Task 2); `Institution`; the existing `_action`/`_index_url`/`_settings_context`/`_active_tab` helpers.
- Produces: URL names `institution:settings_notifications` (save) + `institution:settings_notifications_purge` (purge); context key `"notifications"`; `RetentionForm`.

- [ ] **Step 1: Write the failing tests**

Create `notifications/tests/test_retention_settings.py`:

```python
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from institution.models import Institution
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import UserFactory
from tests.factories import make_login
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_notifications_tab_renders_field_for_pa(client):
    make_pa(client, "pa")
    resp = client.get(reverse("institution:settings") + "?tab=notifications")
    assert resp.status_code == 200
    assert resp.context["active_tab"] == "notifications"
    assert "notifications" in resp.context  # the RetentionForm
    assert "notification_retention_days" in resp.content.decode()


def test_save_persists_retention_window(client):
    make_pa(client, "pa")
    resp = client.post(
        reverse("institution:settings_notifications"),
        {"notification_retention_days": 45},
    )
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=notifications")
    assert Institution.load().notification_retention_days == 45


def test_purge_button_deletes_seeded_rows_and_flashes_counts(client):
    make_pa(client, "pa")
    inst = Institution.load()
    inst.notification_retention_days = 30
    inst.save()
    u = UserFactory()
    c = CourseFactory()
    # aged-read: backdated well beyond the 30-day window
    aged = Notification.objects.create(
        recipient=u, kind=Notification.Kind.ENROLLED, target_type="course",
        target_id=c.pk, read_at=timezone.now(), data={},
    )
    Notification.objects.filter(pk=aged.pk).update(
        created_at=timezone.now() - timedelta(days=60)
    )
    # orphaned: points at a deleted course
    dead = CourseFactory()
    dead_pk = dead.pk
    dead.delete()
    orphan = Notification.objects.create(
        recipient=u, kind=Notification.Kind.ENROLLED, target_type="course",
        target_id=dead_pk, read_at=None, data={},
    )
    resp = client.post(reverse("institution:settings_notifications_purge"), follow=True)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "read: 1" in body and "orphaned: 1" in body
    assert not Notification.objects.filter(pk__in=[aged.pk, orphan.pk]).exists()


def test_settings_views_are_pa_only(client):
    make_login(client, "plain")  # non-PA
    assert client.post(
        reverse("institution:settings_notifications"),
        {"notification_retention_days": 45},
    ).status_code == 403
    assert client.post(
        reverse("institution:settings_notifications_purge")
    ).status_code == 403


def test_purge_get_redirects_to_tab(client):
    make_pa(client, "pa")
    resp = client.get(reverse("institution:settings_notifications_purge"))
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=notifications")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest notifications/tests/test_retention_settings.py -v`
Expected: FAIL — `NoReverseMatch` for `institution:settings_notifications`.

- [ ] **Step 3: Add `RetentionForm` to `institution/forms.py`**

Append to `institution/forms.py` (the module already imports `forms`, `Institution`, and `gettext_lazy as _`):

```python
class RetentionForm(forms.ModelForm):
    class Meta:
        model = Institution
        fields = ["notification_retention_days"]
        labels = {"notification_retention_days": _("Retention window (days)")}
```

- [ ] **Step 4: Wire `institution/views_manage.py`**

Add the import near the other form imports:

```python
from institution.forms import RetentionForm
```

Change `TABS`:

```python
TABS = ("branding", "access", "uploads", "sso", "notifications")
```

Add a `notifications=None` keyword param to `_settings_context` and seed it. Also update the function's docstring — it currently says "Assemble the four-form context" / "renders all four panels"; change the count to five so it stays accurate. The signature becomes:

```python
def _settings_context(
    request, inst, active_tab, *, branding=None, access=None, uploads=None,
    sso=None, notifications=None
):
```

and add this entry to the returned dict (alongside `"uploads": ...`):

```python
        "notifications": notifications or RetentionForm(instance=inst),
```

Add the two views (after `settings_uploads`):

```python
@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_notifications(request):
    return _action(
        request,
        RetentionForm,
        "notifications",
        "notifications",
        _("Retention settings saved."),
    )


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_notifications_purge(request):
    if request.method == "GET":
        return redirect(_index_url("notifications"))  # actions are POST targets
    # Function-local import: keeps notifications out of this module's import graph.
    from notifications.retention import format_purge_result
    from notifications.retention import purge_notifications

    counts = purge_notifications()  # no days ⇒ uses the saved Institution window
    messages.success(request, format_purge_result(counts, dry_run=False))
    return redirect(_index_url("notifications"))
```

- [ ] **Step 5: Add the two URLs to `institution/urls.py`**

Insert after the `settings_sso` path (before the setup-wizard paths):

```python
    path(
        "manage/settings/notifications/",
        views_manage.settings_notifications,
        name="settings_notifications",
    ),
    path(
        "manage/settings/notifications/purge/",
        views_manage.settings_notifications_purge,
        name="settings_notifications_purge",
    ),
```

- [ ] **Step 6: Add the tab link + panel include + panel partial**

In `templates/institution/manage/_tabs.html`, add before `</nav>` (after the SSO link):

```html
  <a class="settings__tab{% if active_tab == 'notifications' %} is-on{% endif %}"
     href="{% url 'institution:settings' %}?tab=notifications">{% trans "Notifications" %}</a>
```

In `templates/institution/manage/settings.html`, add after the `sso` panel `<div>` (before `</section>`):

```html
  <div data-tab="notifications" {% if active_tab != "notifications" %}hidden{% endif %}>
    {% include "institution/manage/_notifications_tab.html" %}
  </div>
```

Create `templates/institution/manage/_notifications_tab.html`:

```html
{% load i18n %}
<form class="settings__form" method="post" action="{% url 'institution:settings_notifications' %}">
  {% csrf_token %}
  {{ notifications.non_field_errors }}
  <div class="settings__section">
    <h2 class="settings__section-title">{% trans "Notification retention" %}</h2>
    <div class="settings__field">
      <label class="settings__label" for="{{ notifications.notification_retention_days.id_for_label }}">{{ notifications.notification_retention_days.label }}</label>
      {{ notifications.notification_retention_days }}
      {% if notifications.notification_retention_days.help_text %}<span class="settings__help">{{ notifications.notification_retention_days.help_text }}</span>{% endif %}
      {{ notifications.notification_retention_days.errors }}
    </div>
    <div class="settings__actions">
      <button class="btn" type="submit">{% trans "Save retention settings" %}</button>
    </div>
  </div>
</form>

<form class="settings__form" method="post" action="{% url 'institution:settings_notifications_purge' %}">
  {% csrf_token %}
  <div class="settings__section">
    <h2 class="settings__section-title">{% trans "Purge now" %}</h2>
    <p class="settings__help">{% trans "Purge uses the saved retention value; save your changes first." %}</p>
    <div class="settings__actions">
      <button class="btn" type="submit">{% trans "Purge old notifications now" %}</button>
    </div>
  </div>
</form>
```

- [ ] **Step 7: Run the settings tests to verify they pass**

Run: `uv run pytest notifications/tests/test_retention_settings.py -v`
Expected: PASS (5 passed).

- [ ] **Step 8: Confirm no existing settings test broke (the TABS audit)**

Run: `uv run pytest tests/test_settings_5c_views.py -v`
Expected: PASS — those tests assert specific context keys present (not the exact `TABS` tuple/count), so the fifth tab does not break them. If any test does pin the 4-tuple, update it to include `"notifications"`.

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff format institution/ notifications/tests/test_retention_settings.py
uv run ruff check institution/ notifications/tests/test_retention_settings.py
git add institution/forms.py institution/views_manage.py institution/urls.py templates/institution/manage/ notifications/tests/test_retention_settings.py
git commit -m "feat(notifications): PA notifications settings tab (retention + purge)"
```

---

### Task 5: i18n — EN/PL strings + compile

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po` + `.mo`, `locale/pl/LC_MESSAGES/django.po` + `.mo`
- Test: `notifications/tests/test_retention_i18n.py` (create)

**Interfaces:**
- Consumes: the new msgids from Tasks 1–4 (model help text, form label, panel strings, view success, tab label, the two `format_purge_result` messages).

- [ ] **Step 1: Write the failing test**

Create `notifications/tests/test_retention_i18n.py`:

```python
from django.utils.translation import gettext
from django.utils.translation import override

from notifications.retention import format_purge_result


def test_purge_message_translated_and_interpolates_pl():
    with override("pl"):
        msg = format_purge_result({"read_aged": 3, "orphaned": 1}, dry_run=False)
    assert "3" in msg and "1" in msg
    assert "read:" not in msg  # the label itself is translated, not left English


def test_retention_strings_have_polish():
    with override("pl"):
        assert gettext("Save retention settings") == "Zapisz ustawienia przechowywania"
        assert gettext("Purge old notifications now") == "Wyczyść stare powiadomienia teraz"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest notifications/tests/test_retention_i18n.py -v`
Expected: FAIL — the PL msgstrs are empty, so `gettext` echoes the English msgid (`"read:"` still present; asserts fail).

- [ ] **Step 3: Extract messages**

Run: `uv run python manage.py makemessages -l en -l pl`
This adds the new msgids to both `.po` files. `makemessages` may mark copied entries `#, fuzzy` — clear that flag on any entry you fill.

- [ ] **Step 4: Fill the Polish translations**

In `locale/pl/LC_MESSAGES/django.po`, set (removing any `#, fuzzy` line above each):

```
msgid ""
"Delete read notifications older than this many days, measured from when each "
"notification was created. 0 keeps read notifications indefinitely; orphaned "
"notifications are removed regardless."
msgstr ""
"Usuwaj przeczytane powiadomienia starsze niż podana liczba dni, licząc od "
"utworzenia powiadomienia. 0 zachowuje przeczytane powiadomienia bezterminowo; "
"osierocone powiadomienia są usuwane niezależnie."

msgid "Retention window (days)"
msgstr "Okno przechowywania (dni)"

msgid "Notification retention"
msgstr "Przechowywanie powiadomień"

msgid "Save retention settings"
msgstr "Zapisz ustawienia przechowywania"

msgid "Purge now"
msgstr "Wyczyść teraz"

msgid "Purge uses the saved retention value; save your changes first."
msgstr "Czyszczenie używa zapisanej wartości; najpierw zapisz zmiany."

msgid "Purge old notifications now"
msgstr "Wyczyść stare powiadomienia teraz"

msgid "Retention settings saved."
msgstr "Zapisano ustawienia przechowywania."

msgid "Notifications purged — read: %(read_aged)d, orphaned: %(orphaned)d"
msgstr "Wyczyszczono powiadomienia — przeczytane: %(read_aged)d, osierocone: %(orphaned)d"

msgid "Would purge — read: %(read_aged)d, orphaned: %(orphaned)d"
msgstr "Do wyczyszczenia — przeczytane: %(read_aged)d, osierocone: %(orphaned)d"
```

The **tab label** `"Notifications"` almost certainly already has a PL entry (`"Powiadomienia"`) from the nav in an earlier slice — verify it is present and translated; if `makemessages` created a fresh empty one, fill it `"Powiadomienia"`. Leave the EN `.po` msgstrs empty (EN is the source), matching surrounding entries.

- [ ] **Step 5: Verify the new msgids are translated + compile**

Run: `git grep -n "Wyczyść stare powiadomienia teraz\|Okno przechowywania\|Wyczyszczono powiadomienia" -- locale/pl/LC_MESSAGES/django.po` → confirm each has a non-empty, non-fuzzy msgstr.
Run: `uv run python manage.py compilemessages`
Expected: compiles `locale/pl/LC_MESSAGES/django.mo` (and `en`) with no errors.

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest notifications/tests/test_retention_i18n.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo notifications/tests/test_retention_i18n.py
git commit -m "i18n(notifications): EN/PL strings for retention/purge"
```

---

### Final verification (after all tasks)

- [ ] Full non-e2e suite: `uv run pytest --junitxml=<scratch>/dod.xml -q >/dev/null 2>&1; echo $?` then read the `<testsuite>` line for `failures="0" errors="0"`.
- [ ] `uv run ruff format --check .` and `uv run ruff check .` → clean.
- [ ] `uv run python manage.py makemigrations --check --dry-run` → "No changes detected" (confirms the only migration is Task 1's, already committed).
- [ ] Optional visual check: `uv run python manage.py runserver`, log in as a PA, open `/manage/settings/?tab=notifications`, confirm the field + both buttons render in light and dark. (No JS on this panel, so a screenshot pass is optional.)

---

## Notes for the implementer

- **Do not modify** `notifications/services.py`, `notify()`, the emit sites, `emails.py`, the bell dropdown, or the `/notifications/` list view. This slice is purely additive.
- **Import direction:** `notifications/retention.py` imports `institution.models` and `courses.models` **function-locally** only (no top-level cross-app imports). `institution/views_manage.py` imports `notifications.retention` **function-locally** in the purge view. Keep it that way.
- The `Institution` singleton is loaded via `Institution.load()` (get-or-create pk=1); tests can just call it.
- If `makemessages` churns unrelated `#:` location comments across the `.po` files, that is normal — do not hand-edit existing msgstrs; only the new entries gain content.
