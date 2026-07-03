# Local development notes

Gotchas and one-time setup for running libli locally.

## Email links point to `example.com` (Site domain)

**Symptom:** an invitation (or password-reset) link printed to the console / sent
by email looks like `http://example.com/invite/accept/<token>/` and doesn't work.

**Why:** security-sensitive links are built from the `django.contrib.sites` **Site**
record (`Site.objects.get_current().domain`), **not** from the request's `Host`
header — so an emailed link can never be host-spoofed (see
`accounts/invitations.py:build_accept_url`). Django ships Site #1 with the
placeholder domain `example.com`, and `SITE_ID = 1`. Until you override it, every
emailed link uses `example.com`.

**Fix (one-time, per environment — the Site is stored in the DB, not in settings):**

```bash
uv run python manage.py shell -c "from django.contrib.sites.models import Site; s=Site.objects.get(pk=1); s.domain='localhost:8000'; s.name='libli (dev)'; s.save(); print(s.domain)"
```

Use whatever host:port you run the dev server on (`localhost:8000` /
`127.0.0.1:8000`). You can also edit it in Django admin under **Sites**.

The link **scheme** comes from allauth's `ACCOUNT_DEFAULT_HTTP_PROTOCOL` (`http` by
default — correct for local dev).

**A token already emailed with `example.com` is still valid** — just swap the host
in the URL (invites last 14 days).

**Production:** set the Site domain to the real hostname and
`ACCOUNT_DEFAULT_HTTP_PROTOCOL=https`. This per-environment step should be captured
by the **first-run setup wizard / platform settings (Phase 5e)** so a non-technical
Platform Admin never sees an `example.com` link.

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
