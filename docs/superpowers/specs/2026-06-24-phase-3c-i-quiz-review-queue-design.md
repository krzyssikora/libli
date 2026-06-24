# Phase 3c-i — Quiz review queue + force-submit: design

**Date:** 2026-06-24
**Status:** Spec (awaiting review)
**Depends on:** Phase 2d-iii (`[R]` REQUIRES_REVIEW marking mode; `QuestionResponse.reviewed_at`/`reviewed_by`; the "reviewed iff `reviewed_at is not None`" invariant); Phase 2e (`QuizSubmission.submitted_by` force-submit seam; `_score_submission` freeze path; `build_course_results` / `awaiting_review` element-driven status); Phase 3a (grouping substrate — `groups_visible_to`, `_is_platform_admin`, course-scoped group teachers).

## Goal

Give teachers a per-course surface to **grade `[R]` (requires-review) quiz responses** and
to **force-submit** a student's open quiz so it can be graded. Marking an `[R]` response
unfolds the quiz's frozen score: a quiz stays `awaiting_review` until **every** `[R]` in it
is reviewed, then reveals its full score to the student. This activates the seams left inert
by 2d-iii/2e (`reviewed_at`/`reviewed_by`/`fraction`/`earned_marks` on `QuestionResponse`,
`submitted_by` on `QuizSubmission`) and closes the grading loop for the half of the question
matrix that auto-grading cannot reach.

This is the **first** of the two Phase-3c slices. The **analytics matrix** (students × units
grid, score/progress aggregation) is **3c-ii** and is out of scope here.

## Locked decisions (from brainstorming)

1. **Decomposed: review queue first.** 3c-i = quiz review queue + force-submit + score
   recompute. 3c-ii = analytics matrix (deferred, separate spec/plan/build).
2. **Per-course surface.** The queue lives at `/manage/courses/<slug>/review-queue/`, matching
   the existing `/manage/courses/<slug>/` authoring structure. The deferred analytics matrix
   can later deep-link into the per-submission review screen.
3. **Marks out of max.** A teacher enters earned marks `0..max_marks` per `[R]` response;
   `fraction = earned/max_marks` is derived. Mirrors how `[A]` auto-grading writes
   `earned_marks` (`courses/views.py:509`).
4. **Mark + optional comment.** One new nullable column,
   `QuestionResponse.review_feedback (TextField, blank=True)`, shown to the student on their
   results page. No other schema change.
5. **Force-submit, `in_progress` only.** A teacher closes a student's started-but-unsubmitted
   quiz via the existing submit/grade/freeze path, stamping `submitted_by=teacher`.
   `not_started` (no submission row) is **out** — fabricating zero-rows for the absent is a
   distinct bulk "award 0 for non-attempt" feature, first candidate for 3c-ii.
6. **Final reveal, no partial scores.** Marks are recorded as the teacher works, but the
   submission stays `awaiting_review` (student sees "submitted for review", no number) until
   the **last** `[R]` is reviewed; then the full score reveals at once. Achieved purely by
   making the derived `awaiting_review` gate review-state-aware — no new status field, no
   special "finalize" code path.
7. **Marks re-editable.** A reviewed `[R]` can be re-marked anytime (grade corrections);
   re-saving recomputes the score. A finalized quiz stays finalized (re-marking does not
   re-open `awaiting_review` unless the edit clears a `reviewed_at`, which the UI never does).

## Non-goals

- The analytics matrix / gradebook grid (3c-ii).
- Overriding or re-grading auto `[A]` marks — the queue is `[R]`-only.
- `not_started` force-submit / "award 0 for non-attempt" / any bulk whole-class action.
- Active student notifications — the student simply sees their updated results page.
- A cross-course "all my reviews" inbox or a global nav count (per-course only; a global
  surface, if wanted, is a later add riding on the same `pending_reviews_for` query).
- Editing the question itself, attempts, or `[N]` (NOT_MARKED) responses — `[N]` is
  permanently unmarked and never enters the queue.

## Architecture

### 1. Schema — one migration in `courses`

Add to `QuestionResponse`:

```python
review_feedback = models.TextField(blank=True)
```

- Non-null, `blank=True`, default `""` — no data backfill, every existing row reads `""`.
- Sanitized on write like other learner-facing rich text? **No** — it is plain teacher text
  rendered escaped (Django autoescape) in the student results template; no HTML is permitted,
  so no `sanitize_html` call (settle in plan if rich text is ever wanted — it is not now).
- All other fields already exist and were inert: `QuestionResponse.{reviewed_at, reviewed_by,
  fraction, earned_marks, locked}` (2d-iii) and `QuizSubmission.submitted_by` (2e). No change
  to `QuizSubmission`, `Attempt`, or any question model.

### 2. Scoring rule change — `courses/views.py` `_score_submission`

The current freeze path (`courses/views.py:540`) sums **AUTO questions only** into both
`score` and `max_score`; `[R]` and `[N]` are excluded entirely (`[R]` because unmarked at
submit, `[N]` because never marked). The review recompute must extend **both** `score` and
`max_score` to include each `[R]` response **once it is reviewed** (`reviewed_at is not None`).
`[N]` stays excluded forever.

Generalize the scoring rule (one shared helper, used by both submit/force-submit and review):

> **score** = Σ `earned_marks` over { AUTO responses with `fraction is not None` } ∪ { reviewed `[R]` responses }
> **max_score** = Σ `max_marks` over { AUTO questions } ∪ { reviewed `[R]` questions }
>
> *Guards (so the at-submit reduction is byte-identical to today):* an AUTO question adds to
> **score** only where its `QuestionResponse` exists **and** `fraction is not None` — matching
> `views.py:556`'s `if r is not None and r.fraction is not None` (an unanswered/`fraction`-null
> `[A]` adds 0 to score). Its `max_marks` adds to **max_score** unconditionally (matching
> `views.py:554`). A reviewed `[R]` always has `fraction`/`earned_marks` written by
> `review_response`, so it adds to both. `[N]` is in neither set, ever.

- **Asymmetry (intended):** an AUTO question counts toward `max_score` whether or not the
  student answered it, but an `[R]` counts toward `max_score` only once **reviewed**. So a
  quiz's `max_score` (and thus its "100%") grows as `[R]`s are graded — but because the quiz
  stays `awaiting_review` until the last `[R]` is reviewed, the student never sees a `max_score`
  that omits a still-pending `[R]`. Confirmed intended.
- At submit / force-submit time no `[R]` is reviewed yet, so the rule reduces to AUTO-only —
  **byte-identical to today's `_score_submission`** (regression-safe: the existing freeze
  tests must still pass unchanged). `[R]` enters `max_score` only as it is reviewed.
- Implementation: factor the AUTO/reviewed-`[R]` summation into a pure helper
  `compute_scores(node, submission) -> (score, max_score)` that both `_score_submission`
  (which additionally sets `status`/`locked`/`submitted_at`) and the review service call.
  `_score_submission`'s other responsibilities (lock all responses, set SUBMITTED, stamp
  `submitted_at`) are **unchanged** and do **not** run on a review save — a review only
  recomputes `score`/`max_score` on an already-SUBMITTED row. Settle the exact factoring in
  the plan; the **rule** above is the contract.
- **`compute_scores` is read-only (no writes):** it includes an `[R]` response only when
  `reviewed_at is not None`, taking that response's stored `earned_marks` directly (it does not
  re-derive from `fraction`; see §5 step 4). It loads full response objects exactly as
  `_score_submission` does today (`submission.responses.all()`), so `reviewed_at`/`earned_marks`
  are available with no extra query. The callers (`_score_submission`, `review_response`) own
  the writes.

### 3. Status derivation change — `courses/rollups.py` `build_course_results`

Today `pending = has_review.get(unit.pk, False)` (`rollups.py:173`) is **true whenever the
unit contains any `[R]` element**, regardless of whether it has been graded — correct in 2e
(nothing was reviewable yet), wrong now. 3c-i redefines:

> A SUBMITTED quiz is **`awaiting_review`** iff it has **≥1 `[R]` element that is not yet
> reviewed** for this submission. Once every `[R]` element has a reviewed `QuestionResponse`
> (`reviewed_at is not None`), the quiz derives to **`submitted`/graded** and its (now
> `[R]`-inclusive) score shows.

- **Unanswered-`[R]` subtlety preserved:** an unanswered `[R]` has no `QuestionResponse` row,
  so "fully reviewed" cannot be a response scan alone. It is: **count of `[R]` elements in the
  unit == count of this submission's `QuestionResponse` rows pointing at those `[R]` elements
  with `reviewed_at is not None`**. The review screen forces a row to exist for every `[R]`
  (§5), so finalization is reachable. The count equality is sound because
  `uniq_response_submission_element` (models.py:988) guarantees ≤1 response per
  (submission, element), so reviewed-row count can never exceed the `[R]`-element count.
- **No N+1:** keep the existing batched shape. `build_course_results` already loads the
  unit→element marking-mode map (`has_review`); add **one** batched query for reviewed-`[R]`
  response counts per submission (`QuestionResponse.objects.filter(submission_id__in=...,
  element__in=<[R] elements>, reviewed_at__isnull=False)` aggregated per `submission_id`),
  then `pending = has_review AND reviewed_R_count < total_R_count`. Pin the exact query shape
  in the plan; the **invariant** above is the contract.
- The score/percent rollup reads `sub.score`/`sub.max_score`, which §2 keeps current.
  **Locked (consistent with decision #6): the headline `score_sum`/`max_sum` MUST exclude
  still-`pending` (awaiting_review) submissions.** Otherwise the course percentage would reflect
  a sealed quiz's partial `max_score`. Today rollups.py:186-187 adds every SUBMITTED row's
  score/max unconditionally; 3c-i changes this to skip rows where `pending` is true. Per-row, a
  `pending` quiz still renders as "awaiting review" (no number shown).
- **Update the docstring.** `build_course_results`'s docstring (rollups.py:107-110) currently
  states awaiting_review is "element-driven … NOT a QuestionResponse scan". The new semantics
  *do* require a (batched) reviewed-row scan, so the docstring must be rewritten to match — an
  implementer must not leave the now-false rationale in place.

### 4. Scoping — `grouping/scoping.py`

Who may review/force-submit **whose** submissions, in a given course:

- **`reviewable_students(user, course) -> QuerySet[User]`**
  - PA (`_is_platform_admin`, i.e. `courses.change_course`) **or** the course owner
    (`course.owner_id == user.id`) → **all students with an `Enrollment` in the course**.
  - Otherwise a **group teacher**: students in the non-archived groups the user teaches or
    manages **on this course** — `groups_visible_to(user).filter(course=course, archived=False)`,
    joined to `GroupMembership.student`. `.distinct()` (a student can be in several of the user's
    groups). **The `archived=False` filter is required, not implied:** `groups_visible_to`
    *includes* archived groups (`groups_manageable_by` "Includes archived rows", scoping.py:18,
    and the taught arm `Group.objects.filter(teachers=user)` does not filter `archived` either).
    A student reachable only via an archived group is **not** reviewable by that teacher
    (intended — archived groups are inactive).
  - Returns `User.objects.none()` if the user has no review reach on the course.
  - **Enrollment-vs-group divergence (intended, the two arms scope on different relations):**
    the PA/owner arm scopes by `Enrollment`, the group-teacher arm by `GroupMembership`. A
    student who self-enrolled (`source="self"`, 3b) and is in no group the teacher reaches is
    therefore reviewable by **PA/owner but not by that group teacher** — intended (a group
    teacher grades only their own group's students). **No submission is stranded:** quiz-taking
    requires an `Enrollment` (`is_enrolled`/`can_access_course`), so `Enrollment` is the
    superset of "could have a `QuizSubmission`", and the PA/owner arm covers every such student.
    Every submission is reviewable by at least PA/owner.
- **`can_review_course(user, course) -> bool`** — `reviewable_students(user, course).exists()`,
  the page-level gate. (PA/owner short-circuit true without the membership query.)
- **Per-submission gate** (every review screen GET and every review/force-submit POST):
  `reviewable_students(user, course).filter(pk=submission.student_id).exists()`. Never trust
  the row; mismatch → 404 (consistent with `get_node_or_404`, avoids leaking which students a
  teacher cannot see).
- **Placement:** `grouping/scoping.py` already holds `groups_visible_to`/`_is_platform_admin`
  and may import `courses` (the established grouping→courses direction; `courses.access`/
  `courses.models` do **not** import grouping, so no cycle). The owner/PA short-circuit is
  written inline (`course.owner_id == user.id` + `_is_platform_admin`) per the existing
  convention — do **not** branch on role names.

### 5. Services — `courses/` (near the quiz/marking code)

- **`pending_reviews_for(user, course) -> {awaiting: QuerySet, in_progress: QuerySet}`**
  Two scoped querysets of `QuizSubmission`, filtered to `student__in=reviewable_students(...)`:
  - `awaiting` — `status=SUBMITTED` AND has ≥1 unreviewed `[R]` (same predicate as §3's
    `pending`, applied across students for the course's quiz units). Annotated with the
    unreviewed-`[R]` count for the row label; ordered by unit then student name.
  - `in_progress` — `status=IN_PROGRESS` for the course's quiz units (the force-submit list).
  Both `select_related("student", "unit")`; no N+1 over rows.

- **`review_response(*, submission, element, earned_marks, feedback, reviewer) -> QuestionResponse`**
  Atomic (per-call savepoint, `select_for_update` on the submission). Steps:
  1. Validate `element` is an `[R]` `QuestionElement` belonging to `submission.unit`
     (programming-error guard → 404 at the view, never a 500).
  2. Bounds `0 <= earned_marks <= question.max_marks` are enforced **in the form** (a `Form`
     field with `min_value=0`/`max_value=max_marks`), so the view re-renders with field errors
     on a bad value and `review_response` is only ever called with a validated `Decimal`
     (quantized to the column, 2dp). The service additionally **asserts** the bound as a
     programming-error guard — an assertion failure is a 500, never the user-facing rejection
     path (which is the form).
  3. `get_or_create` the `QuestionResponse(submission, element)` — **creates the row for an
     unanswered `[R]`** (`latest_answer=None`, `attempt_count=0`, `locked=True`).
  4. Store the teacher's entered `earned_marks` **directly** (no round-trip), and derive
     `fraction = earned_marks / max_marks` quantized to 4dp **for display/headline use only** —
     do **not** re-derive `earned_marks` from `fraction` (double-quantization could make stored
     marks differ from what the teacher typed). `to_stored_fraction` is float-oriented
     (`Decimal(str(raw))`, scoring.py:17) so it is **not** the right helper here; quantize the
     `Decimal/Decimal` division directly. Also write `review_feedback`, `reviewed_at = now`,
     `reviewed_by = reviewer`.
  5. Recompute `submission.score`/`max_score` via §2's rule and save (status untouched — stays
     SUBMITTED; the `awaiting_review`/graded distinction is **derived**, §3).
  Idempotent-ish: re-marking the same response overwrites marks and refreshes `reviewed_at`.

- **`force_submit(submission, *, by) -> None`**
  Atomic, `select_for_update`. Guard `status == IN_PROGRESS` (already-SUBMITTED → no-op, so a
  double-click can't double-grade). Derive `node = submission.unit` (the quiz `ContentNode`
  that `_score_submission` iterates via `node.elements.all()` — `submission.unit` *is* that
  node). Set `submission.submitted_by = by`, then call the **(refactored)**
  `_score_submission(node, submission)` — behavior-identical at submit time per §2 (locks
  responses, sets SUBMITTED, stamps `submitted_at`, AUTO-only score — matching a student's own
  finish; "refactored" because §2 routes it through `compute_scores`, but its at-submit output
  is unchanged). Also mirror
  `quiz_finish`'s `UnitProgress` completion side-effect so a force-submitted unit counts as
  done. A force-submitted `[R]` quiz then surfaces in `awaiting`; an all-`[A]` quiz is fully
  graded and drops off the queue.

### 6. Views / URLs — `courses` (manage namespace)

All `login_required`; all gate through §4 (page gate `can_review_course`, per-submission gate
`reviewable_students(...).filter(pk=...)`). Resolve the course by **slug** and units/nodes via
the IDOR-safe `get_node_or_404`; any scope/ownership mismatch → **404** (never 403), matching
`get_node_or_404`.

- **`review_queue` (GET)** — `/manage/courses/<slug>/review-queue/`. `can_review_course` or
  404. Renders the two sections from `pending_reviews_for(user, course)`: "Awaiting review"
  (rows link to `review_submission`) and "Open / in progress" (rows carry a force-submit POST
  form). Empty states for each.
- **`review_submission` (GET)** — `/manage/courses/<slug>/review/<submission_pk>/`.
  Per-submission gate or 404. Loads the submission's unit, enumerates **all `[R]` elements** in
  unit order, joins each to its `QuestionResponse` (may be absent → "no answer"). Renders, per
  `[R]`: question stem (read-only), the student's submitted answer **displayed read-only**,
  current marks/feedback if already reviewed, a marks input (`0..max_marks`) and a comment box.
  **No existing path renders an answer read-only:** the consumption render shows *interactive,
  rehydrated input widgets* (`rehydrate`/`answer_from_json`), and `quiz_feedback_context` yields
  only a "submitted for review" neutral banner for `[R]` (it does **not** surface the answer
  content). So the review screen needs either the rehydrated input templates rendered in a
  **disabled/readonly** mode or a small new read-only display per question type — settle the
  exact mechanism in the plan; do **not** assume `quiz_feedback_context` or the live consumption
  template shows the answer read-only. A "fully reviewed" banner when
  every `[R]` is done. (`[A]`/`[N]` elements are not shown — queue is `[R]`-only.)
- **`review_submission` (POST)** — same URL. CSRF, per-submission gate or 404. One POST grades
  **one** `[R]` response (calls `review_response`) and re-renders the screen with the row
  marked and the "remaining" count decremented; on the last one the "fully reviewed" banner
  shows and the student's score is now live. (Per-response POST keeps each save independent and
  the screen resilient to partial work; a single multi-field submit-all is a possible plan
  refinement but not required.)
- **`force_submit` (POST)** — `/manage/courses/<slug>/review/<submission_pk>/force-submit/`.
  CSRF, per-submission gate or 404. Calls `force_submit(submission, by=request.user)`,
  redirects back to `review_queue` with a `{% trans %}` success message (`[R]` quiz → "now
  awaiting review"; all-`[A]` → "submitted and graded"). Already-SUBMITTED → no-op + benign
  message (handles the double-click race).

### 7. UI / i18n

- **Bespoke, token-driven** pages matching the `/manage/courses/` ledger (PR #34) and roster
  (PR #29/#32) patterns — `.card-list` rows, `.btn`/`.badge`, dark-mode-aware, responsive
  stacking. No Bootstrap/React.
- **Queue page** — two labelled sections; awaiting rows show student · unit · "N to review"
  badge; in-progress rows show student · unit · a Force-submit button. Counts in the section
  headers. A "Review" link/entry from the manage course area (e.g. the course_list row and/or
  the course manage nav), optionally with an awaiting count.
- **Review screen** — vertical list of `[R]` cards: prompt, the student's answer **displayed
  read-only** (the consumption templates render interactive inputs, so this needs a
  disabled/readonly variant or a small read-only display per type — see §6, not an existing
  path), marks input with a visible `/ max_marks`, comment box, per-card Save. A progress
  affordance ("3 of 5 reviewed") and the fully-reviewed banner.
- **Student-facing** — the results page (`quiz_results` / the `build_course_results` summary)
  needs **no structural change**: `awaiting_review` rows already render as pending; once
  derived-graded they show the score; add the `review_feedback` comment under each reviewed
  `[R]` in the per-quiz results detail (escaped, plain text).
- **i18n** — EN + PL for **every** new string at build time (recurring project requirement;
  grouping shipped untranslated in 3a and had to be backfilled — do not repeat). Compile `.mo`.

### 8. Access — mostly unchanged

`can_access_course`/`can_manage_course` are untouched. Review authority is the **new, broader**
`reviewable_students`/`can_review_course` (§4): a group teacher who is neither course owner nor
PA gets review reach over exactly their group's students — `can_manage_course` (owner/PA only)
would wrongly exclude them. The student's own quiz-taking and results access paths are unchanged.

## Edge cases

| Case | Behavior |
|---|---|
| Unanswered `[R]` (no response row) | Review screen lists the element with "no answer"; saving a mark **creates** the row (`review_response` `get_or_create`) so finalization is reachable. |
| Quiz with mixed `[A]`+`[R]` | `[A]` frozen at submit (in `score`/`max_score`); `[R]` excluded until reviewed; stays `awaiting_review` until every `[R]` done, then both fold into the revealed score. |
| Teacher re-marks an already-reviewed `[R]` | Overwrite marks/feedback, refresh `reviewed_at`/`reviewed_by`, recompute score. Quiz stays graded (still 0 unreviewed `[R]`). |
| Force-submit an already-SUBMITTED quiz (double-click / race) | `force_submit` guard → no-op; benign message. No double-grade. |
| Force-submit an all-`[A]` in-progress quiz | Graded immediately by the reused `_score_submission`; not `awaiting_review`; drops off the queue. |
| Teacher loses reach (student removed from their group) mid-review | Next gate check 404s; no partial write leaks (each POST is independently gated). |
| Student in several of the teacher's groups | `reviewable_students` `.distinct()` → appears once. |
| Course owner is null (`SET_NULL`) | Owner arm never matches; PA-only review (mirrors `groups_manageable_by`'s owner-less convention). |
| `[N]` (NOT_MARKED) responses | Never enter the queue; never scored; unaffected. |

## Testing

- **Scoring rule (`compute_scores`/`_score_submission`)** — regression: existing freeze tests
  pass unchanged (AUTO-only at submit). New: after reviewing `[R]`, `score`/`max_score` include
  the reviewed `[R]`; `[N]` never counted; partial review counts only reviewed `[R]`.
- **`review_response`** — creates a row for an unanswered `[R]`; writes
  `fraction=earned/max_marks`, `earned_marks`, `feedback`, `reviewed_at`/`reviewed_by`; rejects
  `earned_marks > max_marks` and `< 0`; re-mark overwrites; recompute reflects the new mark.
- **`force_submit`** — `in_progress`→SUBMITTED with `submitted_by` set, `_score_submission`
  applied, `UnitProgress` completed; already-SUBMITTED → no-op; an `[R]` quiz lands in
  `awaiting`, an all-`[A]` quiz does not.
- **Status derivation (`build_course_results`)** — a SUBMITTED `[R]` quiz reads
  `awaiting_review` until the last `[R]` is reviewed, then `submitted`/graded with the
  `[R]`-inclusive score; the unanswered-`[R]` "fully reviewed" count uses element-vs-reviewed
  rather than a bare response scan; no N+1 (assert query count).
- **Scoping (`reviewable_students`/`can_review_course`)** — PA & owner see all course students;
  a group teacher sees only their group's students; a teacher with no reach → empty/404; the
  per-submission gate rejects a foreign student (404), and a non-staff student hitting any
  manage URL → 404.
- **Views** — queue lists the right two sections scoped correctly; review GET shows all `[R]`
  (incl. unanswered) and no `[A]`/`[N]`; review POST grades one and updates remaining; CSRF
  enforced; force-submit POST closes the quiz and redirects with the right message; every URL
  404s for an out-of-scope user.
- **e2e** — teacher opens the review queue → force-submits an in-progress quiz → reviews each
  `[R]` with marks + a comment → the quiz reveals its score; then a student loads results and
  sees the score and the comment. **Include a quiz with an unanswered `[R]`** (student left it
  blank): assert the review screen lists it as "no answer", the teacher can mark it, the
  create-the-row path fires, and it is *that* mark which finalizes the quiz — this exercises the
  subtlest finalization path (and is otherwise covered by an integration test if hard e2e-side).
  Drive the **real** click/submit path (no `page.evaluate` shortcuts — the e2e-must-drive-real-UI
  lesson).

## Decisions deferred to the implementation plan

- Exact factoring of the shared `compute_scores` helper out of `_score_submission` (the §2
  *rule* is fixed; the refactor shape is not).
- Exact batched-query shape for the reviewed-`[R]`-count in `build_course_results` and
  `pending_reviews_for` (the §3 *invariant* is fixed).
- Per-response Save vs. a single submit-all on the review screen (lean: per-response).
- Whether `review_feedback` is ever rich text (lean: no — plain escaped text now).
- Exact placement/label of the "Review" entry in the manage nav and whether it carries a count.
