# Notifications

libli notifies users in-app (via the bell in the header) and by email for a
small set of events. Platform-wide behaviour is configured from
**Admin → Institution settings → Notifications**.

## Notification kinds

- **Quiz needs review** — sent to teachers/admins when a student's
  submission requires manual grading.
- **Quiz graded** — sent to the student once their submission is graded.
- **Enrolled in course** — sent to a student when they're enrolled in a
  course (suppressed for self-enrolment, since the student just did it
  themselves).

## Email delivery

Each notification also appears in the bell dropdown; email delivery for the
same event is a separate, per-user, per-kind opt-out — every user controls
which of the three kinds they receive by email from their own account
settings. There is no platform-wide email switch; this tab governs
retention, not delivery.

## Retention and purge

Set the **retention window (days)** for how long a *read* notification is
kept before it's eligible for cleanup; unread notifications are never
purged by age. Notifications belonging to a since-deleted submission or
course (orphaned rows) are always cleaned up regardless of the window. Use
**Purge now** on this tab to run the cleanup immediately, or rely on the
scheduled `flush`/purge job configured for your deployment to do it
automatically on the same window.
