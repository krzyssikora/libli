# Phase 2c — Quiz units & response persistence — Design

**Status:** spec (brainstormed 2026-06-20)
**Slice:** Phase 2c — makes `unit_type=quiz` live and lands the **first persistence of student answers**. A quiz unit renders its question elements with per-question answering + immediate feedback (reusing the 2a/2b marking loop), now **persisted**, **attempt-capped**, and **scored**; a **"Finish quiz"** action locks the quiz, computes the score, and shows the student their own results. Introduces the `QuizSubmission` / `QuestionResponse` / `Attempt` model, designed as the hook Phase 3 reads for group-scoped deadlines and teacher snapshots.
**Predecessors:** 2a (the `QuestionElement` abstract base, `MarkResult`, `mark()`, the `check_answer` answer→submit→feedback round-trip with JS-fragment + no-JS transports, `_question_feedback.html`, `build_lesson_context`, the no-leak/IDOR/CSRF invariants). 2b (short-text / numeric / fill-blank types + the `fraction` signal in `MarkResult`). 1a (`ContentNode.unit_type` lesson|quiz — the quiz branch is currently inert; `UnitProgress`; the `Element` GFK join-row pattern). All file references below are to the post-2b (PR #21) tree.

---

## 1. Purpose & scope

### 1.1 Phase 2 decomposition (context)

Phase 2 (quiz engine & results) is decomposed into five slices, each its own spec → plan → build cycle:

- **2a (shipped, PR #20):** Question foundations — `QuestionElement` base + `ChoiceQuestionElement` + `mark()` interface + answer→feedback loop, formative in lessons, no persistence.
- **2b (shipped, PR #21):** Auto-markable type expansion — short text, short numeric, fill-blanks. Still formative, still no persistence.
- **2c — Quiz units & response persistence (this slice):** makes `unit_type=quiz` live; per-question answering + immediate feedback now **persisted, attempt-capped, scored**; **Finish quiz** → locked results; the `QuizSubmission`/`QuestionResponse`/`Attempt` model; the `[A]`/`[N]` marking modes live, `[R]` stubbed in the schema.
- **2d — Rich interactive + review types:** drag-fill-blanks, match pairs, drag-to-image (pointer DnD), extended response; the `[R]` human-review **path** (the first `[R]`-native type).
- **2e — Results & metrics:** scores per question/unit/course, the `[R]` flag surfaced, student quiz summary.

### 1.2 Behavioral model (locked in brainstorming)

A quiz unit is behaviorally **the formative flow plus persistence, attempt caps, and scoring** — not a new "submit the whole quiz at once" gesture. The decisions:

- **Per-question attempts.** Each question is submitted independently (as today) and marked immediately; there is no single "submit all answers" grading event. (This supersedes the roadmap's loose "quiz-level submission" phrasing.)
- **Immediate, per-submission feedback.** After each submission the student sees the outcome right away — but subject to the withhold rule below.
- **Withhold-until-exhausted/correct.** On a **wrong** submission **with attempts remaining**, the quiz reveals only "Incorrect — try again (N left)" — *not* the correct answer or explanation. The correct answer + explanation reveal only once the student answers **correctly** or uses their **last** attempt. This keeps retries meaningful for scoring and is a feedback state distinct from the formative "always reveal."
- **Last attempt counts.** A question's recorded score is its most-recent attempt's `fraction × max_marks` — **intentionally**, even when a later attempt is *worse* than an earlier one (e.g. a partial fill-blank a student re-submits with fewer blanks right). This is the deliberate "your final answer stands" rule; we do **not** take the max across attempts. (A fully-correct `[A]` answer locks immediately per §3.1 step 5, so a correct answer can't be regressed; only not-yet-correct partials can move down.)
- **Partial credit.** `max_marks` is awarded as `fraction × max_marks` (exact `Decimal`). In practice only fill-blank yields a fraction strictly between 0 and 1; every other type's fraction is 0 or 1.
- **Finish is final.** A **"Finish quiz"** action locks the quiz, computes the score, and shows the student their own results. Exactly **one** (final) `QuizSubmission` exists per (student, quiz unit); there is no retake in 2c (within-session per-question retries up to `max_attempts` provide practice room).
- **Single scrolling screen.** A quiz renders like a lesson (same layout engine). Slideshow (paginated one-question-per-screen) is deferred.

### 1.3 Marking modes

A `marking_mode` field lands on the question abstraction with three values:

- **`[A]` auto** (default): auto-marked via `mark()`, scored. Every 2c question type is `[A]`-capable.
- **`[N]` not-marked**: answer recorded but contributes no score and is excluded from the quiz total. Single submission (no retry), neutral "Answer recorded" feedback.
- **`[R]` requires-review**: representable in the schema (a `QuestionResponse` can sit "awaiting review", `fraction`/`earned_marks` null) but **no `[R]`-native question type and no review UI ship in 2c** — those land in 2d (type + review path) and Phase 3 (review queue). The field + data states exist now so later slices plug in without a schema change.

### 1.4 Scope boundary — student-facing only

2c is **student-facing**. The teacher-facing machinery for the "teacher checkpoint" use case (assign a quiz to a *group*, set a *deadline*, lock at a time, snapshot results) depends on **groups & enrollment, which is Phase 3**. 2c builds the persistence model so Phase 3 layers cleanly on top: `QuizSubmission.status` + `submitted_at` are exactly the fields a deadline-snapshot will read/auto-set.

**No course-level deadline is built in 2c.** A deadline that is not group-scoped would wrongly lock self-directed learners out of practising a quiz after the cutoff; deadlines are inherently a per-group concept (Phase 3).

### 1.5 What this slice is NOT (deferred)

- **No slideshow.** Single scrolling screen only.
- **No teacher-facing controls** (deadlines, locks, group snapshots, review queue) — Phase 3.
- **No `[R]`-native question type / review UI** — 2d / Phase 3.
- **No retake** of a finished quiz — Finish is final.
- **No results/metrics surfaces** beyond the student's own post-Finish summary — aggregate metrics are 2e.
- **No reconciliation of mid-quiz author edits** — see §5.2 (documented limitation).

### 1.6 Non-goals

- No new dependency. Reuses Django, the `mark()`/`MarkResult` core, the existing `fetch` + `X-CSRFToken` transport, the `render_element` dispatch, and every 2a/2b invariant.
- No change to the concrete per-type element templates (the quiz-vs-lesson difference lives in the question *wrapper* + which view renders it — §4.3).
- No change to formative-in-lesson behavior: a question in a lesson stays ephemeral, unlimited-retry, always-reveal; the new fields are dormant there.

---

## 2. Data model

Three new models in `courses/models.py`, plus three fields on the `QuestionElement` abstraction.

### 2.1 New fields on `QuestionElement` (abstract base — inherited by all four concrete types)

```
marking_mode  CharField(max_length=1, choices=[("A", auto), ("N", not-marked), ("R", review)], default="A")
max_attempts  PositiveSmallIntegerField(null=True, blank=True, default=1)          # null = unlimited
max_marks     DecimalField(max_digits=7, decimal_places=2, default=Decimal("1"))   # > 0
```

**Decimal precision (used consistently across all models):** marks-valued fields (`max_marks`, `earned_marks`, `QuizSubmission.score`/`max_score`) use `max_digits=7, decimal_places=2` (up to `99999.99`); `fraction` fields use `max_digits=5, decimal_places=4` (`0.0000`–`1.0000`). Note `MarkResult.fraction` is a `float` upstream; it is converted to `Decimal` at the scoring boundary (§3.5), not stored raw.

- Dormant in lesson units (the formative path ignores them); consumed only by the quiz path.
- Each concrete question type owns its own table, so this is one column-set per existing question table → **one migration per type** (`choicequestionelement`, `shorttextquestionelement`, `shortnumericquestionelement`, `fillblankquestionelement`).
- `max_marks` validated `> 0`; `max_attempts` validated `>= 1` when not null.
- For `[N]`/`[R]` questions, `max_marks`/`max_attempts` are not consumed for scoring (excluded from the total); the fields still exist harmlessly.

### 2.2 `QuizSubmission` — per (student, quiz unit); the spine

```
student        FK(AUTH_USER_MODEL, on_delete=CASCADE, related_name="quiz_submissions")
unit           FK(ContentNode, on_delete=CASCADE, limit_choices_to={"kind": "unit"}, related_name="quiz_submissions")
status         CharField(choices=[("in_progress", …), ("submitted", …)], default="in_progress")
submitted_at   DateTimeField(null=True, blank=True)
score          DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)   # cached Σ earned marks at Finish
max_score      DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)   # cached Σ max_marks over [A] questions at Finish
created        DateTimeField(auto_now_add=True)
updated        DateTimeField(auto_now=True)

UniqueConstraint(fields=["student", "unit"], name="uniq_quizsubmission_student_unit")
```

- `status` + `submitted_at` are the Phase 3 deadline-snapshot hook.
- `score`/`max_score` are cached at Finish so the results summary and later 2e metrics need not recompute.
- `limit_choices_to={"kind": "unit"}` constrains to units but **not** to `unit_type == "quiz"` at the DB level; the quiz-vs-lesson constraint is **intentionally enforced at the view layer only** (`quiz_*` views require `unit_type == "quiz"`, §4.1). A `QuizSubmission` against a lesson unit is unreachable through the views; no DB-level guard is added.
- `save()` invariant: `status == "submitted"` ⇒ `submitted_at` set (mirrors `UnitProgress.completed ⇒ completed_at`).

### 2.3 `QuestionResponse` — per (student-submission, question); current state

```
submission      FK(QuizSubmission, on_delete=CASCADE, related_name="responses")
element         FK(Element, on_delete=CASCADE, related_name="responses")   # GFK join-row = stable per-unit question identity
attempt_count   PositiveSmallIntegerField(default=0)
latest_answer   JSONField(null=True, blank=True)    # last submitted payload (type-specific shape)
fraction        DecimalField(max_digits=5, decimal_places=4, null=True, blank=True) # last attempt's fraction (see §3.5 conversion)
earned_marks    DecimalField(max_digits=7, decimal_places=2, null=True, blank=True) # quantized fraction × max_marks (§3.5); null until first attempt
locked          BooleanField(default=False)         # true once correct OR attempts exhausted (or [N] recorded)
last_attempt_at DateTimeField(null=True, blank=True)

UniqueConstraint(fields=["submission", "element"], name="uniq_response_submission_element")
```

- Keyed on `Element` (the GFK join-row), not the concrete question — a stable identity independent of question type, matching how `check_answer` already locates a question (`Element` → `content_object`).
- The `element`'s `content_object` must be a `QuestionElement`; enforced at the view layer (a non-question element can never produce a `QuestionResponse`).

### 2.4 `Attempt` — full history, one row per submission of a question

```
response   FK(QuestionResponse, on_delete=CASCADE, related_name="attempts")
n          PositiveSmallIntegerField    # 1-based attempt number within the response
answer     JSONField                    # what the student submitted this try
fraction   DecimalField(max_digits=5, decimal_places=4)   # this try's fraction (Decimal(str(MarkResult.fraction)), §3.5)
correct    BooleanField                 # this try's MarkResult.correct
created    DateTimeField(auto_now_add=True)

ordering = ["n"]
UniqueConstraint(fields=["response", "n"], name="uniq_attempt_response_n")   # double-insert guard (§3.1 concurrency)
```

- One small insert per submission; preserves the per-try answer payload for 2e analytics and a future `[R]` review.

### 2.5 Alternative considered & rejected

Folding quiz state into the existing `UnitProgress` (already per student-per-unit). **Rejected:** `UnitProgress` is the generic completion record shared by lessons; overloading it with quiz status/score/lock muddies that contract and complicates the Phase 3 snapshot. `QuizSubmission` stays separate; `UnitProgress.completed` is simply *set* on Finish (§3.4), preserving the uniform completion signal the course outline already consumes.

---

## 3. Marking, scoring & the feedback state machine

### 3.1 Per-question submission (the quiz path)

A quiz-aware handler (a `quiz_answer` view, §4.1) does, server-authoritatively, inside a transaction:

1. Load-or-create the student's `QuizSubmission` for the unit. **Reject if `status == "submitted"`** (quiz locked) — the rejection branches on `_wants_fragment(request)`: **409** (with a "quiz already submitted" body) on the JS-fragment path, **redirect to `quiz_results`** on the no-JS path, consistent with §4.5.
2. Resolve the `Element` (scoped to the unit) and assert its `content_object` is a `QuestionElement`; load-or-create the `QuestionResponse`. **Reject if `response.locked`** or (`max_attempts` not null and `attempt_count >= max_attempts`).
3. `answer = question.build_answer(request.POST)`; `result = question.mark(answer)` — reusing the existing per-type `build_answer`/`mark`.
4. Append an `Attempt` (`n = attempt_count + 1`, `answer`, the converted `fraction`, `result.correct`); bump `attempt_count`; set `latest_answer`, `fraction = Decimal(str(result.fraction))`, `earned_marks` per the §3.5 conversion, `last_attempt_at = now`. (`MarkResult.fraction` is a `float` upstream — 2a/2b are unchanged — so it is converted to `Decimal` at this boundary; see §3.5.)
5. Set `locked = result.correct or (max_attempts is not None and attempt_count >= max_attempts)`.
6. Return the feedback state (§3.2).

**Concurrency.** A bare transaction is **not** enough — under Postgres `READ COMMITTED` two tabs could both read `attempt_count` below the cap and both insert. So step 2 takes a **row lock**: `QuestionResponse.objects.select_for_update()` on the response row *before* the cap check (the second tab blocks until the first commits, then re-reads the bumped count and is rejected). Belt-and-braces, `Attempt` carries `UniqueConstraint(response, n)` (§2.4) so a duplicate attempt number can never be inserted even if the lock is bypassed. The `QuizSubmission` row is the lock target for the load-or-create in step 1 (or `get_or_create` handling the race) so two tabs don't create two submissions despite the unique constraint.

### 3.2 Feedback state machine (the withhold rule) — `[A]` questions

| Situation | Shown to student | Reveal (correct answer + explanation)? |
|---|---|---|
| Correct | "Correct ✓" + explanation | **Yes** (locks) |
| Wrong, attempts remain | "Incorrect — try again (N left)" | **No** |
| Wrong, last attempt used | "Incorrect" + correct answer + explanation | **Yes** (locks) |
| Unlimited attempts, wrong | "Incorrect — try again" | **No** (reveals only on correct) |

- A **distinct partial** `_quiz_question_feedback.html`, separate from the formative `_question_feedback.html` (which always reveals).
- **No-leak (tightened).** `MarkResult.reveal` is **not** a boolean flag — it *is* the type-opaque accepted-answer payload (a `frozenset[int]` of correct choice ids, the accepted text/value, the per-blank `accepted` list, etc.; see `marking.py` + each type's `mark()`). So withholding is not "set a flag" but a **context-construction rule**: in a non-revealing state the quiz feedback context (and its no-JS equivalent) **must not** include `result.reveal` and **must not** render the type's `reveal_template`. The only `MarkResult`-derived data allowed through pre-reveal is `correct` (here always `False`) plus a server-computed "attempts left" integer. The quiz feedback path therefore does **not** reuse the formative `feedback_context()` (which always passes `reveal_template`); it builds a reveal-gated context. Asserted by regression test (§5.1).

### 3.3 `[N]` not-marked

`[N]` answer is recorded exactly like `[A]` (a single `Attempt` + a `QuestionResponse` with `latest_answer`), `locked = True` immediately (single submission, no retry), `fraction`/`earned_marks` left null; feedback is a neutral "Answer recorded" — no correct/incorrect, no score. Excluded from `max_score`. `[R]`: same persistence, Response sits "awaiting review" (`fraction`/`earned_marks` null, not locked-by-score but treated as locked for input); no `[R]` type/UI in 2c.

**Finish & resume for `[N]`/`[R]`:** **Finish never requires answering any question** (`[A]`, `[N]`, or `[R]`) — a student may finish with anything blank. An unanswered `[N]`/`[R]` simply has no `QuestionResponse`. `[R]` "awaiting review" does **not** block Finish in 2c. On resume (§4.4), an answered `[N]`/`[R]` rehydrates as recorded + locked with **no** attempt counter and **no** score; an unanswered one renders as a normal blank question (single-submission for `[N]`).

### 3.4 Scoring & Finish

On **Finish quiz** (`quiz_finish`, §4.1), server-authoritative, in a transaction (idempotent — a second Finish on a `submitted` quiz is a no-op redirect to results):

- For every **`[A]`** question (`Element`) in the unit: `earned = response.earned_marks or 0` (no response / unanswered → 0); `possible = question.max_marks`. `[N]`/`[R]` excluded from the total.
- `score = Σ earned`; `max_score = Σ possible`; `status = "submitted"`; `submitted_at = now`.
- **Lock reconciliation.** Finish sets `locked = True` on **every** existing `QuestionResponse` of the submission (including unlimited-attempts questions the student left open). Unanswered questions simply have **no** `QuestionResponse` (absence = unanswered, scored 0); no placeholder rows are created. **The submission-level lock is authoritative post-Finish:** once `status == "submitted"`, all rendering is read-only and the per-response `locked` flag is moot — so there is no "unlocked, attempts-left" question on a finished quiz, regardless of attempt mode.
- Set the unit's `UnitProgress.completed = True` for the student (load-or-create).
- Render the results summary: total `score / max_score` plus per-question outcome (correct / partial *n/m* / incorrect / not-marked / answer-recorded for `[N]`), now revealing all answers + explanations.

### 3.5 Fraction→marks conversion & quantization

`MarkResult.fraction` is a **`float`** in the existing marking core (`marking.py` — `1.0`/`0.0` for single-answer types, `n_correct/n` for fill-blank); 2a/2b are **not** changed. Scoring converts at the 2c boundary and quantizes, because a ratio like `2/3` is not exactly representable as a terminating `Decimal` regardless of the source type:

- `f = Decimal(str(result.fraction))` — `str()` first avoids binary-float artifacts (e.g. `Decimal(str(2/3))` = `Decimal("0.6666666666666666")`, not the 55-digit `Decimal(2/3)`).
- `earned_marks = (f * question.max_marks).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)` — stored to **2 decimal places**.
- `QuizSubmission.score = Σ earned_marks` over `[A]` responses — an exact sum of already-quantized 2dp values (no further rounding). `max_score = Σ max_marks`.

So storage is deterministic and 2dp-quantized (the earlier "exact, no rounding at storage" framing was wrong — exactness is impossible for thirds). **Display** trims trailing zeros (e.g. `2`, `1.5`, `0.67`). `import`s: `from decimal import Decimal, ROUND_HALF_UP`.

---

## 4. Views, transport & rendering

### 4.1 URLs / views (`courses/views.py`, mirroring `lesson_unit` / `check_answer`)

- `quiz_unit(slug, node_pk)` — GET. Renders the quiz unit. Load-or-create the student's `QuizSubmission`; if `submitted`, redirect to results. Otherwise **rehydrate** each question from its `QuestionResponse` (latest answer pre-filled, attempt counter, locked state).
- `quiz_answer(slug, node_pk, element_pk)` — POST (`@require_POST @login_required`). The §3.1 submission path. Returns `_quiz_question_feedback.html` (JS fragment) or re-renders `quiz_unit.html` (no-JS).
- `quiz_finish(slug, node_pk)` — POST (`@require_POST @login_required`). The §3.4 Finish path → results. **Load-or-creates** the `QuizSubmission` first, so a student who clicks Finish having answered nothing (no responses, possibly no submission yet) is well-defined: `score = 0`, `max_score = Σ [A] max_marks`.
- `quiz_results(slug, node_pk)` — GET. Read-only results summary. **If the student's `QuizSubmission` is absent or still `in_progress` → redirect to `quiz_unit`** (the mirror of `quiz_unit`'s redirect-to-results when `submitted`), so the two views form a closed loop with no dead-end.

All four enforce `can_access_course` + the unit guards; `quiz_*` additionally require `unit_type == "quiz"` (`Http404` otherwise — mirroring `lesson_unit`'s `require_lesson`). POSTs are CSRF-protected via the existing `fetch` + `X-CSRFToken` transport. IDOR: every view scopes the submission/responses by `request.user`.

### 4.2 Templates

- `courses/quiz_unit.html` — parallel to `lesson_unit.html`: elements via the same `render_element` dispatch, questions in **quiz mode**, plus a sticky **"Finish quiz"** button (a no-JS form POST + JS enhancement).
- `courses/elements/_quiz_question_feedback.html` — the withhold-aware feedback partial (§3.2).
- `courses/quiz_results.html` — score summary + per-question outcomes (full reveal).

### 4.3 Question rendering: quiz vs lesson

The concrete per-type element templates stay **shared and untouched**. The question **wrapper** takes a `mode` (`lesson` | `quiz`) controlling: which feedback partial, whether inputs lock (`disabled` when `response.locked`/`submitted`), whether the attempt counter shows, and (quiz) hydrating the saved `latest_answer`. The difference lives in the wrapper + which view renders it.

### 4.4 Resume

Because state is persisted, a student may leave and return: `quiz_unit` reconstructs in-progress state from `QuestionResponse` rows. Answered `[A]` questions show their last state + remaining attempts (or locked if correct/exhausted); answered `[N]`/`[R]` show recorded + locked with no attempt counter (§3.3); questions with no `QuestionResponse` render blank. A `submitted` quiz always lands on `quiz_results`.

### 4.5 No-JS parity

Every action (answer, finish) works without JS via full-page re-render, matching the 2a/2b discipline; the POST handlers branch on `_wants_fragment(request)`.

---

## 5. Invariants, edge cases & testing

### 5.1 Invariants

- **No-leak (tightened):** accepted answers / `reveal` reach the client **only** in a revealing state (§3.2). Regression test, **both** transports: for the **JS-fragment** path, assert the returned `_quiz_question_feedback.html` for a pre-reveal submission contains no accepted-answer text and no correct-answer data attributes (the fragment is just the one question, so a whole-response scan is valid). For the **no-JS** path — which re-renders the entire `quiz_unit.html`, where *other* questions may legitimately be revealed — the assertion must be **scoped to the just-answered question's wrapper** (located by its `element.pk`/anchor), not the whole page; the test fixture uses a question whose accepted-answer string does not coincidentally appear elsewhere on the page. (Alternatively a single-question quiz with no other revealed questions, but the scoped-wrapper assertion is the primary form.)
- **Server-authoritative:** attempt caps, lock state, scoring, and the submitted-lock are all enforced server-side. The client cannot exceed `max_attempts`, answer a `locked`/`submitted` question, or self-report a score.
- **IDOR:** a student reads/writes only their **own** `QuizSubmission`/`QuestionResponse`; `quiz_*` scope by `request.user`. CSRF on all POSTs.

### 5.2 Edge cases (handled explicitly)

- Submitting after Finish → rejected (quiz locked → redirect to results).
- Concurrent submissions in two tabs → `select_for_update()` row lock on the `QuestionResponse` + `UniqueConstraint(response, n)` on `Attempt` prevents cap bypass / double-insert (§3.1 Concurrency).
- Finishing with unanswered questions → no `QuestionResponse` exists for them; they score 0, counted in `max_score` (§3.4).
- Quiz unit with **zero `[A]` questions** → `max_score = 0`; results show "—", no divide-by-zero.
- `max_attempts` lowered below an existing `attempt_count` → this is the **same** `attempt_count >= max_attempts` guard in §3.1 step 2 (already rejects further attempts); the only extra requirement is that the displayed "N left" is clamped at 0 (never negative).
- **Mid-quiz author edits (documented limitation, not fully reconciled in 2c):** questions added after a student starts appear unanswered (score 0 if the student finishes without answering); `QuestionResponse` rows whose `Element` was deleted are ignored in scoring (CASCADE removes them). Full reconciliation (e.g. warning authors, versioning a quiz) is deferred to a later slice.

### 5.3 i18n

All new strings (feedback states, "Finish quiz", "N attempts left", results labels, "Answer recorded") wrapped for EN/PL, matching the 2b i18n pass.

### 5.4 Testing

- **Unit/integration (pytest + factory_boy, real PostgreSQL):** scoring math (partial credit incl. the `Decimal(str(fraction))` conversion + 2dp `ROUND_HALF_UP` quantization for fill-blank thirds, sum-of-quantized totals, 2dp-trimmed display, unanswered = 0, `[N]` excluded, zero-`[A]` quiz); attempt-cap enforcement + concurrent-tab cap; lock transitions; the withhold state machine per type; Finish idempotence + lock; resume rehydration; no-leak assertions; IDOR rejection; the `QuizSubmission` `submitted ⇒ submitted_at` invariant.
- **e2e (Playwright, JS + no-JS):** author a quiz unit (set `marking_mode`/`max_attempts`/`max_marks`) → student answers across all four types, exhausts attempts, finishes, sees results; assert no answer leak before reveal; assert locked-after-finish; assert resume after reload.
- New `factory_boy` factories for `QuizSubmission` / `QuestionResponse` / `Attempt`.

### 5.5 Authoring

`marking_mode` / `max_attempts` / `max_marks` are added to the question editor forms and shown **only when the unit being edited is a quiz** (dormant/hidden in lesson units). Validation: `max_marks > 0`; `max_attempts >= 1` or unlimited.
