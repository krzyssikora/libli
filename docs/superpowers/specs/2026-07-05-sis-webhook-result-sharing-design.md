# External result sharing — SIS / e-register webhook (grade-sync)

*Design doc. Drafted 2026-07-05. First slice of the post-v1 "External result
sharing (webhook / SIS / e-register)" deferred capability (roadmap §Deferred).
Delivers a **grade-sync webhook**: when a student's quiz result is finalized, an
outbox row is enqueued and a cron-run flusher POSTs it (HMAC-signed) to one
configured external endpoint — a school's e-register / SIS.*

Companion: [`../../roadmap.md`](../../roadmap.md) (§Deferred reserves the hook and
notes the shared-substrate intent); [`2026-07-01-notifications-slice-1-design.md`](2026-07-01-notifications-slice-1-design.md)
(the sibling outbound layer whose emit-site conventions this mirrors).

---

## Goal

When a student's quiz submission reaches its **final marked state** — an
auto-graded quiz on submit, or a review-required quiz when the last `[R]` question
is reviewed — libli captures the result and **pushes it to the institution's
external register**: a JSON `POST`, HMAC-signed, to one platform-configured
endpoint. Delivery is durable: each push is persisted to an **outbox** and a
`flush_webhooks` management command (cron-run) sends pending rows, retrying failed
ones with exponential backoff so a temporarily-down register never loses a mark.

The register files each mark by three external identifiers it already owns:
**student number** (`User.external_id`), **class code** (`Group.external_id`), and
**subject code** (`Course.external_id`).

**Demonstrable end-to-end:** a PA configures the endpoint on `/manage/settings/`
(Integrations tab); a student finishes an auto-graded quiz in a course that has a
subject code → a `WebhookDelivery` row is enqueued → `flush_webhooks` POSTs the
signed payload → the row flips to `delivered` and appears in the settings-tab
recent-deliveries panel.

## Non-goals (explicitly out for this slice)

- **Multiple endpoints / per-event subscriptions.** One global endpoint, one event
  kind (`result_finalized`). The model is factored so more kinds/endpoints can be
  added later, but this slice ships exactly one of each.
- **Announcements-style or notification events over the wire.** Only finalized quiz
  results are pushed. The webhook does **not** consume the notification layer's
  `quiz_graded`/`enrolled` events (see §2 — coverage differs).
- **A generic domain-event bus.** We add one focused choke-point
  (`emit_result_finalized`), not a pub/sub registry that notifications also route
  through. Consolidating the two outbound layers is a documented future option
  (roadmap's "single event-emit hook"), not this slice (approach A, chosen over B).
- **Async delivery via a task queue.** libli has no Celery; delivery is a cron-run
  management command over a DB outbox (mirrors `purge_notifications`).
- **Inbound sync / roster import from the register.** Outbound push only.
- **Secret encryption at rest.** The HMAC secret is stored plaintext in the DB
  (required to sign; DB access is already admin-level). Encryption is a noted
  future hardening, not this slice.
- **A "send test event" button.** Nice-to-have; deferred. The recent-deliveries
  panel is the feedback surface for this slice.

## Established libli conventions this slice follows

- **New app pattern:** `integrations/` mirrors how `notifications`, `notes`, `tags`
  were added (own `models`, `services`, `views`/settings-tab wiring, `urls` where
  needed, `management/commands`, `tests`, migrations).
- **Explicit service calls at emit sites, never signals** — `emit_result_finalized`
  is called from the finalize functions inside their existing `transaction.atomic()`
  blocks, using **function-local imports** to avoid a load-time cycle (the
  `notifications` / 3b precedent).
- **Durable-outbox + cron command** (not a queue), like `purge_notifications`.
- **Denormalized payload** captured at emit time (like `Notification.data`) so a
  later data/target change or deletion can't corrupt an in-flight delivery.
- **Every settings surface ships styled** — the Integrations tab uses libli's
  token-driven CSS, verified light + dark; no bare HTML, no undefined classes.
- **i18n:** `gettext_lazy` for labels/choices, `{% trans %}` in templates; EN + PL
  `.po` updated (fuzzy flags cleared + machine-guesses verified), `.mo` compiled.
- **Tooling:** `uv run …` for ruff/pytest/manage (bare `ruff`/`pytest`/`python`
  are not on PATH).

---

## 1. Data model

### 1a. New app `integrations`, two models

```python
class WebhookEndpoint(models.Model):
    """Single-row config for the one outbound endpoint (this slice). Deliberately
    NOT on Institution and NOT in the get_site_config() cache: it holds a secret and
    is read only by the flush command + the settings form, never on the render path.
    Use WebhookEndpoint.load() (get_or_create pk=1), same idiom as Institution."""
    enabled    = models.BooleanField(default=False)
    url        = models.URLField(blank=True)     # https(s) only; validated in the form
    secret     = models.CharField(max_length=255, blank=True)  # HMAC key, plaintext
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class WebhookDelivery(models.Model):
    """One outbox row = one pending/attempted POST of one finalized result."""
    class Event(models.TextChoices):
        RESULT_FINALIZED = "result_finalized", _("Result finalized")

    class Status(models.TextChoices):
        PENDING    = "pending",    _("Pending")
        DELIVERED  = "delivered",  _("Delivered")
        DEAD       = "dead",       _("Dead")        # exhausted retries
        SUPERSEDED = "superseded", _("Superseded")  # a newer emit replaced it (§2d)

    event           = models.CharField(max_length=32, choices=Event.choices,
                        default=Event.RESULT_FINALIZED)
    dedupe_key      = models.CharField(max_length=128)  # identity for supersede (§2d)
    payload         = models.JSONField()        # fully rendered at emit time
    status          = models.CharField(max_length=16, choices=Status.choices,
                        default=Status.PENDING)
    attempts        = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField()    # due time; set to now() at creation
    last_error      = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    delivered_at    = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            # Covers the flusher's "due pending rows, oldest first" scan.
            models.Index(fields=["status", "next_attempt_at"]),
            # Covers the emit-time supersede lookup: still-pending rows for one key.
            models.Index(fields=["dedupe_key", "status"]),
            models.Index(fields=["-created_at"]),
        ]
        ordering = ["-created_at", "-id"]
```

Notes:
- `payload` is the **complete signed body** (§2), denormalized at emit — the flusher
  loads **no payload entities** (student / course / submission), so a since-deleted
  target cannot break or mutate a queued delivery. (It does read the one
  `WebhookEndpoint` config row for the live `url`/`secret`; see §3.)
- No FK to `QuizSubmission`. A delivery outlives its submission by design (same
  stance as `Notification`'s lightweight pointer). The submission id lives *inside*
  `payload` for traceability only.
- `dedupe_key` = `f"{submission_id}:{group_external_id or ''}"` — the delivery
  **identity** (a submission already pins student+unit+course; the group external id
  distinguishes the per-group fan-out rows). Used by the emit-time supersede rule
  (§2d) so a correction can retire a not-yet-sent earlier delivery for the same
  identity. Non-unique (a delivered row and a later pending correction share it).
- `next_attempt_at` is non-null (set to `timezone.now()` at creation) so the "due"
  query is a single indexed range scan.

### 1b. Three external-id fields (one additive migration each)

| Field | App / model | Register concept | Editable in |
|---|---|---|---|
| `external_id` | `accounts.User` | student number | `/manage/people/` user edit (5b) |
| `external_id` | `courses.Course` | subject / subject-part code | course settings (CA/PA) |
| `external_id` | `grouping.Group` | class code | group edit (CA) |

All `CharField(max_length=64, blank=True, default="")`, indexed=False. Optional and
inert until the register maps them. **No uniqueness constraint** — external systems
may legitimately reuse codes, and enforcing uniqueness here would be a footgun.

---

## 2. The `result_finalized` event & emit sites

### 2a. Why a new event (not the notification `quiz_graded`)

The notification layer emits `quiz_graded` **only on the review-completion
transition** and **never for auto-graded quizzes** (a no-`[R]` submission is instant
and produces no `quiz_graded`). A register wants **every** final mark. So the
webhook needs a distinct event, `result_finalized`, covering **both** finalize
paths. This is why approach A (a new focused choke-point) is correct and approach C
(hang off `notify()`) was rejected: `notify()` structurally cannot deliver
auto-graded marks.

### 2b. The choke-point

`integrations/services.py`:

```python
def emit_result_finalized(submission):
    """Enqueue outbox deliveries for a finalized quiz result. Call INSIDE the
    caller's transaction.atomic() block, only on a genuine finalize transition
    (see call-site rules below). No-op unless the endpoint is enabled AND the
    course has a subject code (external_id) — that presence IS the per-course
    opt-in. Enqueues one WebhookDelivery per class the student is in for the
    course (per-group fan-out), or one group-null delivery if the student has no
    non-archived group."""
```

- **Gates (both required, else no-op):** the endpoint is enabled **and**
  `submission.unit.course.external_id` is non-blank. The enabled flag is read with a
  **read-only** query — `WebhookEndpoint.objects.filter(pk=1).first()`, treating a
  missing row as disabled — **not** `WebhookEndpoint.load()`. `load()` does a
  write-capable `get_or_create` and must never run on the quiz-finalize path; this
  mirrors the deliberate read-only Institution access in `core/services.py:47`
  (which uses `.filter(pk=1).first()` for exactly this reason). A course with no
  subject code never pushes (a push with no subject code is unfileable by the
  register), and this doubles as the opt-in switch — no separate per-course flag.
- **Per-group fan-out:** resolve the student's **non-archived** groups for the
  course:
  `Group.objects.filter(course=course, archived=False, memberships__student=submission.student)`.
  - ≥1 group → **one delivery per group**, each carrying that group's `external_id`
    (and `name`); a student in two classes for one subject yields two deliveries with
    **distinct `dedupe_key`s** (they differ by group external id), so both survive.
  - 0 groups (e.g. self-enrolled) → **one delivery with `group: null`**. The register
    may reject/park it, but libli sends what it truthfully has; suppressing it would
    silently drop a real mark.
- **Supersede prior pending (§2d):** for each fan-out delivery, before creating it,
  set `status=SUPERSEDED` on any existing `status=PENDING` row with the **same
  `dedupe_key`** (a not-yet-sent earlier emit/correction for the same identity), so
  only the newest queued copy per identity is ever sent. Already-`delivered` rows are
  untouched (the receiver reconciles those via `finalized_at`; see §2d).
- **Payload built once** (shared across the fan-out except the `group` block),
  denormalized from already-loaded objects. Score comes from the submission's stored
  `score` / `max_score` (populated by `compute_scores`; `courses/quiz.py:92`).
  **Both must be non-null at emit** (finalize populates them on every emit path); the
  payload builder asserts this and never `str()`s a `None` into the JSON (M1).
- Each enqueue is `WebhookDelivery.objects.create(status=PENDING, dedupe_key=…,
  next_attempt_at=timezone.now(), payload=…)` — committing atomically with the
  finalize write, so a rolled-back finalize enqueues nothing.
- **Failure isolation (I5):** the enqueue (config read + group query + the
  `create()`s + supersede update) runs **inside** the caller's finalize
  `atomic()`, so on success it commits atomically with the mark — no lost push, no
  half state. These are all local DB operations whose failure modes match the
  finalize's own writes; an exception rolls the finalize back and the student simply
  retries. We **accept** that coupling (the same stance as the in-`atomic()`
  `Notification` row create), rather than swallowing enqueue errors — silently
  losing a grade push is worse than a retryable finalize error. Rationale recorded so
  this is a decision, not an oversight.

### 2c. Payload

```json
{
  "event": "result_finalized",
  "finalized_at": "2026-07-05T12:00:00+00:00",
  "student": {"external_id": "S-123", "email": "a@b.pl", "name": "Jan Kowalski"},
  "course":  {"external_id": "MATH-A", "slug": "algebra-1", "title": "Algebra 1"},
  "group":   {"external_id": "7B", "name": "Class 7B"},
  "unit":    {"id": 42, "title": "Fractions quiz"},
  "score":   {"earned": "8.00", "max": "10.00", "percent": 80.0}
}
```

- `student.external_id` / `group.external_id` may be `""`/absent if unmapped; the
  register matches on what's present (email is the documented fallback for student).
  `course.external_id` is always present (it's the gate).
- `group` is `null` for a no-group student.
- `score.earned` / `max` are decimal **strings** (avoid float rounding); `percent`
  is a convenience float (`0` when `max == 0`).
- `finalized_at` is ISO-8601 UTC (`timezone.now()`), letting the register order
  corrections (§2d).

### 2d. Emit sites (all already inside `atomic()`)

| Path | File:line | When it emits |
|---|---|---|
| Student self-finish | `courses/views.py::quiz_finish` (~627) | after `finalize_submission`, **iff** `submission_review_state(submission)["total"] == 0` (auto-final: no `[R]` → final now) |
| Teacher force-submit | `courses/review.py::force_submit_quiz` (~74) | same auto-final condition (a force-submitted quiz *with* `[R]` is not yet final — no emit here) |
| Review completion / correction | `courses/review.py::review_response` (~34) | inside the existing lock block: emit when `not was_fully and now fully_reviewed` (completion) **or** `was_fully and score changed` (post-completion correction re-push) |

- **Transition-guard responsibility** lives at the call site (mirrors the
  notifications stance): each caller invokes `emit_result_finalized` only on the
  branch that actually reached a final/changed-final state.
- **Corrections re-push (decision 3):** `review_response` already recomputes
  `score`/`max_score`. Capture the pre-save `score` alongside the existing
  `was_fully`; emit when completion transitions **or** an already-complete
  submission's `score` changes. A no-op re-save of an unchanged complete submission
  emits nothing. Each correction is a fresh delivery with a later `finalized_at`.
- **Receiver identity contract (C1):** the register must upsert by
  **`(student, course, group, unit)`** — the same tuple as `dedupe_key` plus the
  course — **not** `(student, course, unit)`. The per-group fan-out deliberately
  produces one row *per class*, and those rows share student/course/unit; keying
  without the group would let one class's mark silently overwrite the other. A
  `group: null` delivery occupies the "no class" slot of that key.
- **Correction ordering (I6):** because deliveries retry with backoff, an earlier
  correction can dead-letter and be POSTed *after* a newer one. libli mitigates the
  common case libli-side — the emit-time **supersede** rule (§2b) retires any
  *still-pending* earlier delivery for the same `dedupe_key`, so two queued
  corrections never race. For a correction that lands after an **already-delivered**
  one, ordering falls to the receiver: it **must** treat `finalized_at` as
  authoritative and ignore an arriving payload whose `finalized_at` is older than the
  last it filed. This is a stated **receiver contract**, not a libli guarantee;
  documented here so the dependency is explicit, not assumed.
- **Import direction (M):** the three emit sites use **function-local imports** of
  `integrations.services` (which imports from `courses`/`grouping`), avoiding a
  load-time cycle — the `notifications` precedent.
- **Placement note:** `emit_result_finalized` is called from
  `force_submit_quiz` (the **service**, `courses/review.py`), not its view, so the
  bulk `force_submit_all` loop is covered automatically — exactly as
  `notify_needs_review` is wired.

---

## 3. Delivery — `flush_webhooks` management command

`integrations/management/commands/flush_webhooks.py`, cron-run (documented, like
`purge_notifications`); safe to overlap:

- **Selection & per-row transaction (I1):** first read a bounded list of candidate
  **ids** (`WebhookDelivery.objects.filter(status=PENDING,
  next_attempt_at__lte=now).order_by("created_at").values_list("pk", flat=True)[:limit]`,
  `--limit` default 100) **outside** any long-held transaction. Then process each id
  in its **own** short transaction: `with transaction.atomic(): row =
  WebhookDelivery.objects.select_for_update(skip_locked=True).filter(pk=id,
  status=PENDING).first()` — if `None` (another run took it, or it was superseded),
  skip; otherwise POST, record the outcome on that row, and commit. This keeps the
  DB lock and connection held only for the single row being sent, so one slow
  endpoint never holds locks across the whole batch (a ~10s POST × 100 rows must not
  become a ~1000s transaction). `skip_locked` lets concurrent runs not double-send.
- **Send:** `POST body` as JSON to the endpoint's current `url` with headers:
  - `Content-Type: application/json`
  - `X-Libli-Event: result_finalized`
  - `X-Libli-Delivery: <row pk>` — the receiver's idempotency key. **Scope (M7):**
    this dedupes *retries of one row* only. Two *separate* emits for the same result
    (the correction path) are distinct rows with distinct pks; cross-emit
    reconciliation is the receiver's `(student, course, group, unit)` upsert +
    `finalized_at` contract (§2d), not this header. libli's own supersede rule (§2b)
    already prevents two *pending* copies from both sending.
  - `X-Libli-Signature: sha256=<hex>` — `hmac.new(secret.encode("utf-8"), raw_body,
    sha256).hexdigest()`, where `raw_body` is the **exact bytes sent** (serialize the
    JSON once to bytes, sign those bytes, send those bytes). The secret is a `str`
    column, so it is UTF-8 encoded for the HMAC key.
  - 10s timeout; **no redirect following**; **http(s) schemes only**.
- **SSRF note (M6):** scheme-restriction + no-redirects blocks `file://` and
  redirect-based escapes, but does **not** stop a PA pointing the URL at a private /
  loopback / link-local host (`127.0.0.1`, `169.254.169.254`, RFC-1918). Because the
  URL is set only by a Platform Admin, that is **out of scope** for this slice; an
  optional deny-private-IP / allowlist guard is noted as a follow-up (§9).
- **Outcome:**
  - `2xx` → `status=delivered`, `delivered_at=now`, `last_error=""`.
  - non-2xx / timeout / connection error → `attempts += 1`, `last_error=<summary>`,
    then: if `attempts >= MAX_ATTEMPTS` → `status=dead`; else reschedule
    `next_attempt_at = now + BACKOFF[min(attempts - 1, len(BACKOFF) - 1)]`.
- **Backoff (I4):** `BACKOFF` (module constant, minutes) = `[1, 5, 15, 60, 180, 360,
  720]` (7 entries) with `MAX_ATTEMPTS = 8`. Mapping: after failed attempt *N*
  (`attempts` now = N), a row with `N < 8` reschedules by `BACKOFF[min(N-1, 6)]`, so
  failures 1→7 use delays `1, 5, 15, 60, 180, 360, 720` (every entry is reachable);
  the 8th failure sets `dead`. No schedule value is dead code and the
  `attempts→delay` index is fully pinned. Tunable via settings; constants are fine
  for the slice. (Test asserts this exact `attempts → next_attempt_at` sequence.)
- **HTTP client:** the stdlib (`urllib.request`) — `requests` is **not** a current
  dependency (verified), so we avoid adding one.
- **Command is a no-op** when the endpoint is disabled or unconfigured (logs a single
  line); it never sends, but pending rows remain for when it's re-enabled.
- **Endpoint changed after enqueue:** the flusher reads the *current* `url`/`secret`
  at send time (payload is fixed at emit, transport config is live) — rotating the
  secret re-signs pending rows with the new key, which is the intended behaviour.

---

## 4. Configuration & editing UI

### 4a. Integrations settings tab (`/manage/settings/?tab=integrations`, PA-only)

- Add `"integrations"` to `institution/views_manage.py::TABS`, an `IntegrationsForm`
  to the `_settings_context` bundle, and a panel in the settings template. **Bind
  target (M5):** unlike the Institution-backed tabs, this form is a ModelForm over
  `WebhookEndpoint` and must bind `instance=WebhookEndpoint.load()` (settings-form
  path — the write-capable `load()` is fine here, it's not the render hot path),
  so it does **not** reuse the Institution-instance `_action` helper unchanged —
  it diverges the same way the SSO tab does. (The form is the only place `load()`
  is used; emit reads config read-only per §2b.)
- Fields: `enabled` (toggle), `url` (URLField; form validation restricts scheme to
  `http`/`https` and requires a value when `enabled`), `secret` (rendered as a
  set/rotate control — shows "configured" without echoing the value; a blank submit
  leaves it unchanged, a new value replaces it).
- **Recent-deliveries panel:** read-only list of the last ~20 `WebhookDelivery`
  rows (`event`, status badge, `created_at`, `attempts`, truncated `last_error`) so
  an admin can confirm it's working and spot `dead` rows. Styled, light + dark.

### 4b. External-id fields on existing edit surfaces

- `User.external_id` → the `/manage/people/` user edit form (5b). **Note (I3):**
  `UserEditForm` (`accounts/forms.py:69`) is a plain `forms.Form` with a bespoke save
  path (not a ModelForm), so this needs a **manually declared** `external_id` field
  plus a line in that view's custom save to persist it — a touch more work than the
  ModelForm rows below.
- `Course.external_id` → the course settings **ModelForm** (CA/PA), near the existing
  self-enrolment/visibility fields, with help text ("Subject code in your external
  register; leave blank to disable result sync for this course").
- `Group.external_id` → the group edit **ModelForm** (CA), help text ("Class code in
  your external register").

Course and Group are one field added to an existing ModelForm + template; User is
the manual-field case above. No new views.

---

## 5. Permissions & scoping

- The Integrations tab and all config edits are PA-only (`change` permission on the
  settings surface, same gate as the other tabs).
- Course/Group `external_id` follow their host form's existing role gates (CA/PA).
- `flush_webhooks` is an operator command (cron / shell), no in-app auth surface.
- No new roles or permissions are introduced.

---

## 6. i18n

- `WebhookDelivery.Event` / `.Status` labels via `gettext_lazy`.
- Integrations tab labels, help text, status badges, and the field help texts via
  `{% trans %}` / form label kwargs.
- EN + PL `.po` updated, fuzzy flags cleared and machine-guesses verified (the
  makemessages fuzzy gotcha), `.mo` compiled.

---

## 7. Testing

- **Emit (`emit_result_finalized`):**
  - auto-graded self-finish enqueues one delivery; correct gate — **no** enqueue
    when endpoint disabled, and **no** enqueue when the course has no `external_id`.
  - review-completion transition enqueues; a no-op re-save of an already-complete
    submission does **not**; a **post-completion correction that changes the score**
    enqueues a fresh delivery (decision 3).
  - **supersede:** a correction while an earlier delivery for the same `dedupe_key`
    is still `pending` flips that earlier row to `superseded` and only the newest
    sends; an already-`delivered` earlier row is **not** superseded.
  - force-submit of a no-`[R]` quiz enqueues; force-submit of an `[R]` quiz does not
    (not yet final); the bulk `force_submit_all` path is covered.
  - per-group fan-out: student in two non-archived groups → two deliveries with the
    two class codes **and distinct `dedupe_key`s** (neither supersedes the other);
    archived group excluded; no-group student → one `group: null` delivery.
  - **gate reads config read-only** (no `WebhookEndpoint` row is created by an emit
    on a disabled/unconfigured install — asserts `load()` is not on the hot path).
  - payload shape: all three external ids populated when set; decimal-string score
    (never `"None"` — `score`/`max_score` non-null asserted); `percent` (and
    `percent == 0` when `max == 0`); ISO `finalized_at`.
- **Flush command:**
  - `2xx` → `delivered`; a failing send increments `attempts` and sets
    `next_attempt_at` to the **exact** `BACKOFF` sequence (`1,5,15,60,180,360,720`
    min for failures 1→7); the 8th failure → `dead` (asserted as a concrete
    `attempts → delay` sequence, not "advances somehow").
  - **HMAC signature** recomputed by the test — `hmac.new(secret.encode(),
    sent_bytes, sha256).hexdigest()` — matches the `X-Libli-Signature` header
    (sign-what-you-send, secret UTF-8 encoded).
  - only **due** pending rows are sent (a future `next_attempt_at` is skipped);
    `--limit` bounds the candidate batch; disabled endpoint → no send; a row already
    `superseded` between selection and lock is skipped (re-checked under the lock).
  - outbound HTTP is **mocked** (no live network); one test asserts the request URL,
    headers, and body bytes.
- **Config form:** PA-only; `url` scheme validation; `enabled` requires a URL;
  secret set/rotate/leave-unchanged semantics.
- **External-id fields:** editable and persisted via each host form; blank default.
- **e2e (real gestures):** PA sets endpoint on the Integrations tab; the recent-
  deliveries panel renders. (The outbound POST is not exercised over a real socket in
  e2e; the flush path is covered by the mocked command tests above.)
- Full suite + new tests + ruff check/format clean; `.mo` compiled; migrate clean on
  a fresh DB; `uv run` for all tooling.

---

## 8. Definition of done

- New `integrations` app: `WebhookEndpoint` + `WebhookDelivery` (+ `0001_initial`);
  additive `external_id` migrations on `accounts.User`, `courses.Course`,
  `grouping.Group`.
- `emit_result_finalized` wired at the three finalize sites via function-local
  imports; read-only config gate + course subject code; per-group fan-out; corrections
  re-push with emit-time supersede of same-`dedupe_key` pending rows.
- `flush_webhooks` command: per-row `skip_locked` transactions, HMAC-signed POST,
  exact `BACKOFF` schedule → `dead`; documented cron cadence.
- Integrations settings tab (config + recent-deliveries panel) and the three
  external-id form fields, styled and verified light + dark.
- EN + PL translations complete and compiled.
- Full test suite (incl. new tests + the config e2e) green; ruff clean; migrate clean.

---

## 9. Open items intentionally deferred (tracked, not forgotten)

1. **Multiple endpoints / per-event subscriptions** — the `Event`/`Status` choices
   and single-endpoint config are the seam; a later slice generalizes.
2. **Consolidating notifications + webhook onto one domain-event hub** (roadmap's
   "single event-emit hook"; approach B) — deferred; notifications stay as-is.
3. **Async delivery** (queue) — remains a cron command until volume warrants.
4. **Secret encryption at rest.**
5. **Inbound SIS sync** (roster/grade import) — outbound only for now.
6. **"Send test event" button** on the Integrations tab.
7. **`purge`/retention of old `delivered`/`dead`/`superseded` deliveries** — rows
   accumulate; a `--days` purge (like `purge_notifications`) is a documented
   follow-up.
8. **Deny-private-IP / allowlist SSRF guard** (M6) — reject loopback / link-local /
   RFC-1918 endpoint hosts, or an explicit host allowlist; out of scope while the URL
   is PA-only.
