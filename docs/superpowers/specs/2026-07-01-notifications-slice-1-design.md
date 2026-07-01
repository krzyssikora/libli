# Notifications — Slice 1: event notifications + minimal in-app list

*Design doc. Drafted 2026-07-01. First slice of the post-v1 "Notifications &
announcements" deferred capability (roadmap §Deferred). Delivers system-generated
**event notifications** persisted to a new `notifications` app and surfaced via a
minimal server-rendered in-app list plus an unread badge in the nav.*

Companion: [`../../roadmap.md`](../../roadmap.md) (§Deferred reserves the hooks).

---

## Goal

When something relevant happens to a user — a quiz they submitted needs no further
action but was flagged for teacher review, a submission they own has been graded, or
they were enrolled in a course — a `Notification` row is created for the right
recipient(s), and each user can see their own notifications on an in-app page with an
unread count in the nav and a way to mark them read.

**Demonstrable end-to-end:** trigger any of the three events → the recipient's nav
badge increments → they open `/notifications/` → see the item, follow it to its
target, and mark it read.

## Non-goals (reserved for later slices)

- **Email delivery** (slice 2) — will reuse libli's existing synchronous
  `transaction.on_commit` + `send_mail` path (as in `accounts/invitations.py`), plus a
  per-user on/off preference. No task queue is introduced.
- **Live bell dropdown panel** — the polished bell + fetch-driven dropdown; will reuse
  the existing `_wants_fragment` helper (`courses/views.py:65`).
- **Announcements** — human-authored one-to-many broadcasts to a group/cohort/course.
- **Group/cohort-assignment notifications** — deliberately out; enrollment already
  covers the learner-facing "you now have access" case.
- **Retention/purge** — see §7; deferred to a management command later.
- **Per-notification email/mute preferences** — arrive with slice 2.

## Prior art: bonnot's `notifications` app

libli's sibling project `bonnot` (`apps/notifications/`) has a mature notifications
app. We **borrow its design DNA** and **drop the pieces that don't fit libli**:

**Borrow:**
- The `Notification` model shape: `recipient` FK + a `kind` `TextChoices` + a
  lightweight subject pointer + a `data` JSON of denormalized display fields + an index
  on `(recipient, -created_at)`.
- A single **`notify()` choke-point** service that records the row and short-circuits
  when `recipient == actor`, called inside the emit site's `transaction.atomic()` block.
- Denormalizing display fields into `data` so the list renders without extra joins and
  survives later deletion of the target.

**Drop (don't fit libli):**
- **DRF ViewSet / serializers** — libli is server-rendered (no React/SPA). Slice 1 uses
  plain Django views + templates.
- **Celery `@shared_task`** (email + purge) — libli has no queue. Email is deferred to
  slice 2 via synchronous `on_commit`; purge is deferred to a management command.
- **UUID PKs** — libli uses `BigAutoField` integer PKs.
- **Single user-level `seen_at` timestamp** for read state — we use per-row `read_at`
  instead (see §3).

## Established libli conventions this slice follows

- **New app pattern:** mirrors how `notes` and `tags` were added (own app dir, `models`,
  `services`, `views`, `urls`, `templates`, `tests`, migrations).
- **Explicit service calls, never membership signals** for domain events
  (`grouping/services.py` stance) — `notify()` is called from the emit functions.
- **i18n:** module-level `gettext_lazy` for choice labels; `{% trans %}` in templates;
  EN + PL `.po` updated and `.mo` compiled.
- **Every view ships styled** — the page is styled per libli's token-driven CSS, verified
  light + dark; no bare HTML, no undefined CSS classes.
- **Tooling:** `uv run …` for ruff/pytest/manage (bash `ruff`/`pytest`/`python` are not
  on PATH).

---

## 1. Data model

New app `notifications`, one model:

```python
class Notification(models.Model):
    class Kind(models.TextChoices):
        QUIZ_NEEDS_REVIEW = "quiz_needs_review", _("Quiz needs review")
        QUIZ_GRADED       = "quiz_graded",       _("Quiz graded")
        ENROLLED          = "enrolled",          _("Enrolled in course")

    class TargetType(models.TextChoices):
        SUBMISSION = "submission", _("Quiz submission")
        COURSE     = "course",     _("Course")

    recipient   = models.ForeignKey(settings.AUTH_USER_MODEL,
                    on_delete=models.CASCADE, related_name="notifications")
    kind        = models.CharField(max_length=32, choices=Kind.choices)
    actor       = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                    on_delete=models.SET_NULL, related_name="+")
    target_type = models.CharField(max_length=16, choices=TargetType.choices)
    target_id   = models.BigIntegerField()
    data        = models.JSONField(default=dict, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    read_at     = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["recipient", "-created_at"])]
        ordering = ["-created_at", "-id"]
```

Notes:
- `actor` is nullable (system-originated events / user later deleted → `SET_NULL`).
- `target_type` + `target_id` is a deliberate lightweight pointer (not a `GenericForeignKey`);
  the `data` JSON carries everything the list template needs to render, so a deleted
  target degrades gracefully (text still renders; link may 404, handled in §4).
- `data` payload per kind (denormalized at creation; keys are stable):
  - `quiz_needs_review`: `{course_title, unit_title, student_name, submission_id}`
  - `quiz_graded`: `{course_title, unit_title}`
  - `enrolled`: `{course_title}`
- Migration `0001_initial` only. No changes to other apps' models.

## 2. `notify()` choke-point service

`notifications/services.py`:

```python
def notify(*, recipient, kind, actor=None, target=None, data=None):
    """Record a notification. No-op (returns None) when recipient == actor.
    Call inside the emit site's transaction.atomic() block."""
    if actor is not None and recipient == actor:
        return None
    target_type, target_id = _resolve_target(target)   # maps a Course/QuizSubmission → (type, id)
    return Notification.objects.create(
        recipient=recipient, kind=kind, actor=actor,
        target_type=target_type, target_id=target_id, data=data or {},
    )
```

- `_resolve_target` maps a passed domain object to `(target_type, target_id)`; keeps
  the pointer logic in one place. Callers pass the domain object, not raw ids.
- Read helpers live here too: `unread_count(user)` and `recent_for(user, limit)`
  (thin queryset wrappers so views/nav don't hand-roll queries).

### Emit-site wiring

All three fire via explicit `notify()` calls inside existing `transaction.atomic()`
blocks — never signals.

| Event | Emit site (current code) | Recipient(s) | Actor |
|---|---|---|---|
| `quiz_needs_review` | quiz submission path in `courses/` that flips a submission to `SUBMITTED` with ≥1 unreviewed `[R]` question (see `courses/review.py::submission_review_state`, `pending_reviews_for`) | **each teacher** of the submitting student's group for that course | the student |
| `quiz_graded` | `courses/review.py::review_response` when the submission's review becomes complete (all `[R]` responses now reviewed) | the student who owns the submission | the reviewing teacher |
| `enrolled` | `grouping/services.py::enroll_self` and `recompute_enrollment` when a **new** enrollment is created (not on re-sync of an existing one) | the student | `None` for group-driven; `None` for self-enroll (no "notify yourself") — see note |

Notes / decisions:
- **Teacher fan-out** for `quiz_needs_review`: resolve "teachers of the student's group
  for this course" using the existing grouping models/scoping. A small helper
  `notifications/recipients.py::teachers_for(student, course)` wraps the query
  (`Group` for the course whose membership includes the student → its `teachers` M2M),
  reused by tests. One `notify()` per teacher.
- **`quiz_graded` timing:** fire only when the *last* outstanding `[R]` response for the
  submission is reviewed (transition to fully-reviewed), so the student gets one
  "graded" notification per submission, not one per question.
- **`enrolled` self-enroll:** the student is both actor and recipient → the
  `recipient == actor` guard would suppress it. So self-enroll passes `actor=None`
  (it's the *system* granting access, which is the truthful framing) so the student
  **is** notified. Group-driven enrollment passes `actor=None` too (staff action, but we
  don't surface which staff member). Rationale recorded so the guard isn't seen as a bug.
- **Idempotency:** `enroll_self` / `recompute_enrollment` already distinguish new vs.
  existing enrollment (get-or-created); `notify()` fires only on the *created* branch, so
  batch re-syncs don't spam. `quiz_graded` fires on the completion *transition* only.

## 3. Read tracking

Per-row `read_at` (not bonnot's user-level `seen_at`):

- **Unread count** = `Notification.objects.filter(recipient=user, read_at__isnull=True).count()`.
- **Mark one read:** POST sets `read_at = now()` for that row (scoped to
  `recipient=user`; a foreign id 404s).
- **Mark all read:** POST sets `read_at = now()` for all the user's unread rows.
- Visiting `/notifications/` does **not** auto-mark-all — marking is always explicit, so
  nothing silently disappears from the unread count.

Rationale: the roadmap wants a richer inbox (bell + per-item read) later; per-row
`read_at` supports "read #3 but not #5" and "mark all read" now, avoiding a migration
when the bell panel lands. `seen_at` (a single timestamp) can't express per-item state.

## 4. UI surface (slice 1)

- **`/notifications/` page** — server-rendered, styled per libli's token CSS (verified
  light + dark, no undefined classes):
  - Reverse-chronological list; each row: a monochrome `currentColor` SVG icon chosen by
    `kind` (per the icons-are-line-SVG convention), the message text (built from `data`
    via `{% trans %}` templates, one phrasing per `kind`), a relative timestamp, a link to
    the target, and a per-row "mark read" control. Unread rows are visually distinct.
  - "Mark all read" action; empty state when there are none.
  - **Target links** are built from `data`/`target_*`; if a target no longer resolves,
    the row still renders its text and the link is omitted (no dead link / 500).
- **Unread badge in the top nav** — a small count next to a notifications/bell link,
  computed per request. Implemented via a lightweight context processor (or a nav
  include calling `unread_count`), authenticated users only, cheap single COUNT.
- `notifications/urls.py` wired under the project urlconf; views require login and always
  scope to `request.user` (you only ever see/mutate your own).

Deferred to later slices: the live bell dropdown (reuses `_wants_fragment`), email,
announcements.

## 5. Permissions & scoping

- Every view is login-required and filters strictly by `recipient=request.user`.
- No new roles/permissions. Recipient resolution at emit time uses existing grouping
  scoping; the *viewing* side needs no role checks beyond "it's mine".
- Mutations (mark read / mark all read) are POST + CSRF, scoped to the user; a
  non-owned/nonexistent id returns 404, never mutates another user's row.

## 6. i18n

- `Kind` labels via module-level `gettext_lazy`.
- Message phrasings live in the template(s) using `{% trans %}` / `{% blocktrans %}` with
  the `data` fields interpolated (one block per `kind`).
- EN + PL `.po` updated, fuzzy flags cleared and machine-guesses verified (per the
  makemessages fuzzy gotcha), `.mo` compiled.

## 7. Retention

Bonnot purges notifications older than 30 days via a Celery beat task. libli has no
queue, so slice 1 **does not purge** — rows accumulate. A `purge_notifications`
management command (with a `--days` option) is a documented follow-up, runnable from
cron/manually, added when volume warrants it. Recorded here so the absence is a
decision, not an oversight.

## 8. Testing

- **Model / service:** `notify()` creates a row; `recipient == actor` returns `None` and
  creates nothing; `_resolve_target` maps each target type; `unread_count` / `recent_for`.
- **Emit sites:** submitting a quiz with an `[R]` question notifies **each** teacher of
  the student's group (fan-out asserted with 2 teachers) and no one else; completing the
  review notifies the student once (not per question); a new enrollment (self + group)
  notifies the student; a re-sync of an existing enrollment does **not**.
- **Read tracking:** unread count; mark-one (owner only; foreign id 404 + untouched);
  mark-all.
- **View / access:** page renders styled and lists only the requesting user's rows;
  another user's notifications are never visible; login required.
- **e2e (real gestures):** trigger an event, see the nav badge, open the page, follow the
  target link, mark read, badge decrements.
- Full suite + ruff check/format clean; `.mo` compiled; `uv run` for all tooling.

## 9. Definition of done

- New `notifications` app with `0001_initial`; three emit sites wired via `notify()`.
- `/notifications/` page + nav unread badge, styled and verified light + dark.
- Per-row `read_at` with mark-one / mark-all; strictly self-scoped.
- EN + PL translations complete and compiled.
- Full test suite (incl. the new tests + one e2e) green; ruff clean.
- Migrate runs clean on a fresh DB.

---

## Open items intentionally deferred (tracked, not forgotten)

1. **Email delivery + per-user preference** (slice 2, synchronous `on_commit`).
2. **Bell dropdown panel** (fetch via `_wants_fragment`).
3. **Announcements** (human-authored broadcasts).
4. **Retention purge** management command.
5. **Group/cohort-assignment** notifications (if demand appears).
