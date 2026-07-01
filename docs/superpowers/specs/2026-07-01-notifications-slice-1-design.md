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

- **Email delivery** (slice 2) — will reuse libli's existing synchronous `send_mail`
  (`accounts/invitations.py`) deferred via `transaction.on_commit` (the `on_commit`
  wrapper lives in `accounts/signals.py`, M3), plus a per-user on/off preference. No task
  queue is introduced.
- **Manually / directly enrolled students are not notified in slice 1 (I7)** — only
  self-enroll and group-driven enrollment fire `enrolled`. The `manual` enrollment source
  (staff enrolling a student directly, outside group assignment) has no emit in this
  slice; wiring it is a documented follow-up.
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
        indexes = [
            models.Index(fields=["recipient", "-created_at"]),
            # Covers the per-request nav unread COUNT (M4). Needs
            # `from django.db.models import Q`.
            models.Index(fields=["recipient"], name="notif_unread_idx",
                         condition=Q(read_at__isnull=True)),
        ]
        ordering = ["-created_at", "-id"]
```

Notes:
- `actor` is nullable (system-originated events / user later deleted → `SET_NULL`).
- `target_type` + `target_id` is a deliberate lightweight pointer (not a `GenericForeignKey`);
  the `data` JSON carries everything the list template needs to render, so a deleted
  target degrades gracefully (text still renders; link may 404, handled in §4).
- `data` payload per kind (denormalized at creation; keys are stable; carries both the
  display text **and** the identifiers needed to reverse the target URL without loading the
  target — I3):
  - `quiz_needs_review`: `{course_title, course_slug, unit_title, node_pk, student_name}`
    (the submission id lives in `target_id`; not duplicated in `data` — M1)
  - `quiz_graded`: `{course_title, course_slug, unit_title, node_pk}`
  - `enrolled`: `{course_title, course_slug}`
- **Monolingual titles (M5):** `course_title` / `unit_title` are captured in the
  creator's active language at emit time; a recipient viewing in the other language
  sees the source-language title (only the surrounding phrasing is translated). This
  mirrors the known monolingual `Subject.title` decision and is a documented
  limitation, not an i18n bug.
- Migration `0001_initial` only. No changes to other apps' models.

## 2. `notify()` choke-point service

`notifications/services.py`:

```python
def notify(*, recipient, kind, target, actor=None, data=None):
    """Record a notification. No-op (returns None) when recipient == actor.
    `target` is required — every current kind carries one (I8). Call inside the
    emit site's transaction.atomic() block."""
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
  `target` is required — there is no `None` case; every current kind carries a concrete
  `Course` or `QuizSubmission` (I8).
- Read helpers live here too: `unread_count(user)` and `recent_for(user, limit)`
  (thin queryset wrappers so views/nav don't hand-roll queries).

### Emit-site wiring

All three fire via explicit `notify()` calls inside existing `transaction.atomic()`
blocks — never signals.

| Event | Emit site (current code) | Recipient(s) | Actor |
|---|---|---|---|
| `quiz_needs_review` | on transition to `SUBMITTED` when `submission_review_state(submission)["total"] > 0` (M3); wired at the student `quiz_finish` view (`courses/views.py:620`) and inside the teacher `force_submit_quiz` **service** (`courses/review.py:62`) — see emit-placement note; fires only on the not-`SUBMITTED`→`SUBMITTED` transition (I6) | **each distinct teacher** per `teachers_for` (+ `course.owner` fallback) | the acting user — student on self-finish, teacher on force-submit |
| `quiz_graded` | `courses/review.py::review_response`, only on the not-fully-reviewed → fully-reviewed transition (see quiz_graded timing note) | the student who owns the submission | the reviewing teacher |
| `enrolled` | `grouping/services.py::enroll_self` and `recompute_enrollment` when a **new** enrollment is created (not on re-sync of an existing one) | the student | `None` (system-granted; see note) |

Notes / decisions:
- **Teacher fan-out** for `quiz_needs_review`: a helper
  `notifications/recipients.py::teachers_for(student, course)` returns the **union of
  teachers across *all* of the student's non-archived groups for that course** — a student
  may belong to more than one `Group` in a course — **de-duplicated** so a teacher who
  teaches two of the student's groups is notified once. Query:
  `Group.objects.filter(course=course, archived=False, memberships__student=student)` →
  `teachers`, mirroring `reviewable_students` (so the fan-out set matches who actually has
  review reach; a teacher of an archived group is excluded). One `notify()` per distinct
  teacher. The archived-group exclusion is tested.
- **No-group fallback (C1):** self-enrolled students (Phase 3b) have no `GroupMembership`,
  so `teachers_for` can be empty. When it is, fall back to notifying `course.owner` (the
  nullable `Course.owner` FK — *not* a permission holder; `courses.change_course` is a
  global PA-only model permission and would resolve to every platform admin, so it is not
  used). When `course.owner` is `None` the notification is skipped, and that is acceptable
  for slice 1. Both the multi-group/shared-teacher and the no-group cases are tested.
- **`quiz_graded` timing:** the transition check and `notify()` live **inside
  `review_response`'s own `transaction.atomic()` block** (`courses/review.py`) — capture the
  reviewed-count / `submission_review_state` at the top, *before* `response.save()`, and
  compare after — so the notification commits atomically with the graded write and never in
  a separate caller-side transaction. It fires exactly once on the
  `not fully_reviewed → fully_reviewed` transition; a later review *edit* on an
  already-complete submission recomputes `fully_reviewed → fully_reviewed` and must **not**
  re-notify. Tested with a second review edit after completion.
- **Auto-graded quizzes (M2):** a submission with no `[R]` questions never reaches a
  review-completion transition, so it intentionally produces **no** `quiz_graded`
  notification — results are instant and already visible. Documented, not a gap.
- **Force-submit:** `force_submit_quiz` is treated identically to self-finish — it emits
  `quiz_needs_review` on the transition with `actor` = the force-submitting teacher. If that
  teacher is one of the group's teachers, the `recipient == actor` guard suppresses
  self-notification; the other teachers are still notified.
- **`quiz_needs_review` emit placement (I2/M2/M3):** the student path is wired in the
  `quiz_finish` view (`courses/views.py:620`); the teacher path is wired **inside the
  `force_submit_quiz` service** (`courses/review.py:62`), *not* its view — so the bulk
  `force_submit_all` loop (`courses/views_review.py:190`) is covered automatically. Both
  entry points call one shared helper `notify_needs_review(submission, actor)` that applies
  the `submission_review_state(submission)["total"] > 0` gate (M3), the not-`SUBMITTED`→
  `SUBMITTED` transition guard (I6), and the `teachers_for` fan-out — so the paths cannot
  drift. `force_submit_all` coverage is tested.
- **Import direction (M5):** the emit sites (`grouping/services.py`, `courses/views.py`,
  `courses/review.py`) use **function-local imports** of `notifications.services` /
  `notifications.recipients` to avoid a load-time cycle (those helpers import from
  `grouping` / `courses`), consistent with the 3b precedent.
- **`enrolled` self-enroll:** the student is both actor and recipient → the
  `recipient == actor` guard would suppress it. So self-enroll passes `actor=None`
  (it's the *system* granting access, which is the truthful framing) so the student
  **is** notified. Group-driven enrollment passes `actor=None` too (staff action, but we
  don't surface which staff member). Rationale recorded so the guard isn't seen as a bug.
- **Idempotency:**
  - `enrolled`: `enroll_self` / `recompute_enrollment` (`grouping/services.py:163,174`)
    currently call `get_or_create` but **discard** the `created` flag; the emit wiring must
    modify them to capture it and `notify()` only on the *created* branch (M1). The
    concurrent-create race (`recompute_enrollment`'s `IntegrityError` fallback) counts as
    **not created** → no notification. Batch re-syncs therefore don't spam.
  - `quiz_graded`: fires only on the completion *transition*.
  - `quiz_needs_review` (I6): fires only on the not-`SUBMITTED`→`SUBMITTED` transition. A
    repeated save of an already-`SUBMITTED` submission does not re-notify — this is the
    slice-1 realizable case and is tested. A reopen/re-submit path that returns a submission
    to `SUBMITTED` would fire again by design, but no such path exists in the current code
    (M4), so that half is forward-looking and not tested in slice 1.

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
  - **Pagination (I5):** the list is paginated with Django's `Paginator` (page size 25);
    because there is no purge (§7), rows accumulate and the page must never render the
    whole table. `recent_for(user, limit)` is a separate small-N helper reserved for the
    future bell dropdown — not used by the page.
  - "Mark all read" action; empty state when there are none.
  - **Target links, keyed on `kind`** — the two `submission`-targeted kinds link to
    *different* destinations, so link resolution is keyed on `kind`, not just
    `target_type`, and each URL is reversed from the **denormalized `data` identifiers**
    (no per-target load, so no N+1 across the paginated page — I3):

    | kind | route | reversed from |
    |---|---|---|
    | `quiz_needs_review` | `courses:manage_review_submission` | `course_slug`, `target_id` (submission pk) |
    | `quiz_graded` | `courses:quiz_results` | `course_slug`, `node_pk` |
    | `enrolled` | `courses:course_outline` | `course_slug` |

    A link is omitted only if the `data` identifiers are absent/blank (e.g. a legacy row);
    the row always renders its text (no dead link / 500). Because the URL is built from
    `data`, not a live lookup, a link to a since-deleted target may 404 on click — an
    accepted, rare edge for slice 1.
- **Unread badge in the top nav** — a small count next to a notifications/bell link,
  computed per request via a **context processor** registered in
  `core/context_processors.py` (M6 — matches the existing convention there),
  authenticated users only, a single cheap COUNT covered by the partial index from §1.
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
- **Emit sites:**
  - `quiz_needs_review`: submitting a quiz with an `[R]` question notifies **each
    distinct** teacher across the student's non-archived group(s) — fan-out asserted with 2
    teachers, shared-teacher de-dup asserted with a teacher in two of the student's groups,
    and archived-group exclusion asserted (I4); a **no-group** (self-enrolled) student's
    review notifies `course.owner`, and is skipped when `owner is None` (C1); no one else is
    notified; a repeated already-`SUBMITTED` save does not re-notify (I6, the
    reopen/re-submit half is forward-looking); `force_submit_quiz` by a teacher emits with
    that teacher as actor and does not self-notify, and the bulk `force_submit_all` path is
    covered (I2/I3).
  - `quiz_graded`: completing the review notifies the student once (not per question); a
    second review edit after completion does **not** re-notify (I2); an auto-graded
    (no-`[R]`) submission produces **no** `quiz_graded` (M2).
  - `enrolled`: a new enrollment (self + group) notifies the student; a re-sync of an
    existing enrollment does **not**; manual/direct enrollment produces no notification in
    slice 1 (I7).
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
6. **Manual/direct enrollment** notifications (the `manual` source; see I7).
