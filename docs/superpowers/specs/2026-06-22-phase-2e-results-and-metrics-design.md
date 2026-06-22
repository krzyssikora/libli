# Phase 2e — Results & metrics (student per-course quiz summary) — Design

**Status:** spec (brainstormed 2026-06-22)
**Slice:** Phase 2e — the **final slice of Phase 2** and the close of the quiz engine. Ships **one new student-facing view** — *"Quiz summary — own performance"* (view-inventory §3.7) — a lean per-course page that lists every quiz unit in a course with the student's score + status, a course-level headline, and drill-down links to the **existing** per-quiz `quiz_results` page. Behind it sits a single pure aggregation helper. This is a **read/aggregate slice**: it reuses the frozen `QuizSubmission.score`/`max_score` from 2c untouched and adds **no new scoring logic**.
**Predecessors:** 2c (the quiz persistence model `QuizSubmission`/`QuestionResponse`/`Attempt`; the frozen `[A]`-only `score`/`max_score` set by `_score_submission` at Finish; the per-quiz `quiz_results` page + `_results_row`; `UnitProgress`; the `can_access_course` enrollment guard; the no-leak/IDOR invariants). 2d-i…iii (all 9 question types now exist; 2d-iii pre-reserved the `reviewed_at`/`reviewed_by` columns on `QuestionResponse` as the Phase-3 review seam — this slice mirrors that pattern for `submitted_by`). 1a (`build_outline` in `courses/rollups.py`, the tree-walk + per-user rollup precedent this slice's helper is modelled on). All file references are to the post-2d-iii (PR #27, merge `8040f37`) tree.

---

## 1. Purpose & scope

### 1.1 Where 2e sits

The 2c spec §1.1 enumerated Phase 2 as 2a (question foundations) → 2b (auto-markable types) → 2c (quiz units) → 2d (rich interactive + review types, sub-split i/ii/iii) → **2e (Results & metrics)**. After 2d-iii all **9 question types** exist and the per-*submission* results page (`quiz_results`) is complete. The roadmap's Phase 2 bullet for this slice reads: *"Results metrics (scores per question/unit/course); the `[R]` flag is produced here (the teacher review queue lands in Phase 3); Student quiz summary (own performance)."*

The per-**question** and per-**unit** metrics already exist (the `quiz_results` page + `QuizSubmission.score`). The `[R]` flag is already produced (2c/2d-iii). So the only genuinely **new** metric in 2e is the **per-course rollup**, and its single consumer in v1 is the **student's own performance summary**. Teacher-facing metrics (the analytics matrix, cross-student rollups, the review *queue*) are **Phase 3** — they need groups to scope "their students." **2e closes Phase 2.**

### 1.2 The deliverable (locked in brainstorming 2026-06-22)

A new student view **`course_results`** at `/courses/<slug>/results/` rendering, for the logged-in student, a per-course quiz summary:

- A **course-level headline**: *"Done X of Y quizzes · NN% · S / M"* (see §2.1 for the basis).
- A **row per quiz unit** in the course (in outline order), each showing the student's score + a **status**, and linking onward (drill-down to the existing `quiz_results` for taken quizzes; to `quiz_unit` to take/resume otherwise).

Reached by a **"My results"** link from the course outline header and the My-courses card. No score data is crammed into those existing pages — they keep their current responsibilities; the new page owns scores.

### 1.3 Granularity decisions (locked in brainstorming)

- **Course → per-quiz, drill to the existing results page** (NOT chapter/section rollup, NOT an all-courses dashboard). The summary lists individual quiz units and links each taken quiz to the already-built `quiz_results` page; it does **not** roll scores up the content tree or aggregate across courses.
- **No color bands.** Plain numbers/percentages, with a neutral textual cue for `not started` / `awaiting review` / `not graded`. The configurable per-course color-band config (Course-settings thresholds + colors) is **deferred to Phase 3**, where the teacher analytics matrix — its primary consumer — lands.
- **Placement: a standalone page** (its own URL + template), not folded into the outline tree. Matches §3.7's framing of it as a distinct view, keeps the outline focused on navigation/progress (and free for Phase-4 notes/tags badges), and gives Phase 3's teacher matrix a natural shape to mirror.

### 1.4 Headline basis (locked in brainstorming)

**The course total sums only over `SUBMITTED` quizzes.** Untaken quizzes are listed (as `not started`) but excluded from the total — the headline reads as *"of what you've done, how you scored,"* not a final grade. Concretely: `score = Σ submission.score`, `max_score = Σ submission.max_score`, over the student's **`SUBMITTED`** submissions in this course; `percent = score / max_score` (zero-denominator guarded → "—"). Because each `QuizSubmission.score` is already the frozen `[A]`-only total from 2c, the course total is a **faithful sum of existing frozen scores** — no re-marking, no tree-wide score recompute.

### 1.5 The teacher force-submit hook (deferred capability; reserved seam)

In brainstorming the user noted: *"it would be nice if a teacher could later mark a quiz as submitted, even if it was not."* The **capability** is Phase 3 — it needs teacher identity + the "their students" scoping that only groups provide, exactly like the review queue. It is **out of scope for 2e**. But it folds cleanly into this design: a teacher-force-submitted quiz simply *becomes another `QuizSubmission`* (with `student` = the student) and is picked up by the summary automatically; no special path.

**Reserved seam (decision: reserve now — §2.2).** To avoid a Phase-3 schema change, 2e adds **one nullable, inert column** to `QuizSubmission`: `submitted_by` (the actor who submitted — null for a normal student self-submit). This mirrors how 2d-iii pre-reserved `reviewed_by` on `QuestionResponse`. **No 2e code writes it**; it is the reserved hook only (roadmap principle: "reserve hooks for deferred features so adding them later doesn't force a schema rewrite"). *(Open at the spec-review gate: if preferred, drop §2.2 entirely and let Phase 3 add the column — 2e then ships with **zero** migrations.)*

### 1.6 What this slice IS / IS NOT

**Is:** one new student view + URL + template; one pure aggregation helper (`build_course_results`) alongside `build_outline`; two entry-point links (outline header, My-courses card); one reserved nullable column (§1.5); i18n; tests.

**Is NOT (deferred):**
- **No teacher-facing view of any kind** — no analytics matrix, no cross-student rollup, no review queue, no teacher force-submit UI/behaviour (all Phase 3). 2e ships only the *student's own* view.
- **No color-band config or color coding** (Phase 3).
- **No chapter/section score rollup; no all-courses dashboard** (§1.3).
- **No new scoring logic, no change to `_score_submission`, `scoring.py`, `QuizSubmission.score/max_score`, or the per-quiz `quiz_results` page** — all reused read-only.
- **No lessons.** Lessons are progress-tracked (surfaced on the outline via `build_outline`), not scored; the summary is **quizzes only**.
- **No denormalized score cache** — computed live per request (quizzes-per-course is small; YAGNI).

### 1.7 Non-goals

No new dependency. No change to `MarkResult`, the 2c withhold machinery, the frozen-score boundary, or any question type. No export (CSV/printable gradebook is an explicitly deferred post-v1 item — but the aggregation helper returns plain dicts, export-friendly when that lands). No charts/graphs.

---

## 2. Data model

### 2.1 Aggregation rule (no new stored field)

The per-course total is **computed live** from existing rows — no denormalized column on `Course`/`Enrollment`. Inputs:

- The course's **quiz units** — `ContentNode`s with `kind == UNIT and unit_type == QUIZ`, gathered in outline order from the same tree the outline walk uses.
- The student's **`QuizSubmission`s** for this course — one query: `QuizSubmission.objects.filter(student=student, unit__course=course)`, indexed into a `{unit_id: submission}` dict (the `(student, unit)` unique constraint guarantees ≤1 per unit).

Headline (per §1.4): over submissions with `status == SUBMITTED`, `score = Σ submission.score` (a `Decimal`), `max_score = Σ submission.max_score` (a `Decimal`), `percent = int(round(100 * score / max_score))` — **explicitly cast to a Python `int`** so the template comparison `percent is None` and test assertions are type-stable — guarded for `max_score in (None, 0)` → `percent is None` (rendered "—"). `score`/`max_score` stay `Decimal` (passed to the `marks` filter). `done_count` = number of `SUBMITTED` submissions (this **includes** a fully-`[N]` submitted quiz — it *is* submitted — even though it contributes `0/0` to the score sums; see §4.2); `total_count` = number of quiz units in the course.

### 2.2 `QuizSubmission` — the reserved force-submit seam (1 nullable column)

In `courses/models.py`, add to the existing `QuizSubmission`:

```
submitted_by = models.ForeignKey(
                   settings.AUTH_USER_MODEL, null=True, blank=True,
                   on_delete=models.SET_NULL, related_name="+")
```

- **Nullable, no default change to existing rows** (an `AddField(null=True)` is a metadata-only migration). **No 2e code reads or writes it** — `course_results` and `build_course_results` ignore it entirely.
- **Semantics for Phase 3 (documented, not enforced here):** `submitted_by is None` ⇔ the student submitted their own quiz (the only case 2e ever produces). When Phase 3 builds teacher force-submit, it sets `submitted_by` = the teacher; the existing `student` FK stays the owning student, so the summary picks the submission up unchanged.
- `related_name="+"` (no reverse accessor) — Phase 3 can widen it; 2e needs no `user.submitted_for` query. **`"+"` is used specifically to avoid a reverse-accessor clash** with the user model's other FKs (`QuizSubmission.student`, `QuestionResponse.reviewed_by`/`student` — several FKs already target `AUTH_USER_MODEL`); without it Django would require a unique `related_name` and could collide.
- Because `submitted_by` targets `settings.AUTH_USER_MODEL`, `makemigrations` auto-adds the `migrations.swappable_dependency(settings.AUTH_USER_MODEL)` dependency — **generate the migration, do not hand-write it.**

### 2.3 Migration (0020)

One migration: `AddField QuizSubmission.submitted_by` (nullable, metadata-only). No data migration. The number is **`0020` as the next available** (latest is `0019_extendedresponsequestionelement_and_more`); `makemigrations` assigns it — treat `0020` as indicative and re-check at build time. Passes the migration-consistency gate. *(If the §1.5 seam is dropped at review, 2e has **no migration** at all.)*

---

## 3. The helper, view & rendering

### 3.1 `build_course_results(course, student)` — pure aggregation helper

A new function in **`courses/rollups.py`** (sibling of `build_outline`, same shape: a tree walk + one per-user query, returning plain dicts). Pure of side effects; deterministic given `(course, student)` + DB state.

```
def build_course_results(course, student) -> dict
```

**`student` here means "the viewing user" (`request.user`)** — named `student` for the common case, but it is whoever is viewing (a previewing teacher is admitted by `can_access_course` and sees their own, usually empty, submissions). Either naming (`user` à la `build_outline`, or `student`) is acceptable at build time as long as the docstring states this.

- **Quiz-unit enumeration & ordering (pin the flatten).** `build_course_results` walks the **same node tree** `build_outline` uses (`course.nodes.all()`, which is ordered by **`ContentNode.Meta.ordering = ["order", "pk"]`** — models.py:109–110) and emits the course's **quiz units** (`kind == UNIT and unit_type == QUIZ`) in **depth-first pre-order** of that tree. Because `build_outline` returns a *nested* tree (a list of dicts with `children`), not a flat list, the helper either (a) calls a small shared flattener over that tree, or (b) re-walks `course.nodes.all()` with the identical sibling ordering — **the pinned, tested property is that row order equals the depth-first pre-order quiz-unit sequence of the outline.** Two implementers must produce the same order.
- **Query budget — pin the count.** The helper issues a **bounded, N-independent** number of queries (no per-row/per-unit N+1): **(1)** the course's nodes; **(2)** the student's `QuizSubmission`s in this course (`filter(student=student, unit__course=course)`), indexed `{unit_id: submission}`; **(3)** the student's `QuestionResponse`s for those submissions in one query (`filter(submission__in=…)`), **with their question resolved via the GFK** (see next bullet). That is **3 base queries + one query per question *content-type* present** (the GFK batch — see below). The `assertNumQueries` test fixes the fixture's question types so the count is deterministic; §4.4 states the same number. (`build_outline`'s "two queries" is a *sibling precedent*, not a budget this helper must match — it does more.)
- **`marking_mode` lives on the question, reached via the GFK (pin the traversal).** `marking_mode`/`max_marks` are on `QuestionElement` (each concrete subclass's own column, since `QuestionElement` is abstract) — **not** on `QuestionResponse`. From a response the path is `response.element` (FK → the `Element` GFK join-row, models.py:939) → `element.content_object` (the `GenericForeignKey`, models.py:171) → `.marking_mode`. This is exactly how `_score_submission`/`_results_row` resolve it today. To avoid N+1, **batch the GFK resolution** with `prefetch_related("element__content_object")` on the responses query — Django prefetches GFKs **one query per content type**, so the total stays bounded (the "3 + one-per-type" above). The detection reads the **current** `marking_mode` (consistent with `_score_submission`/`_results_row`).
- **Per quiz unit**, build a **row** dict: `{ "unit": node, "status": <str>, "score": <Decimal|None>, "max_score": <Decimal|None>, "pending": <bool>, "url": <str>, "url_name": <str> }`.
- **`status`** ∈ `{"not_started", "in_progress", "submitted", "awaiting_review"}`:
  - **`not_started`** — no submission for the unit. `score=max_score=None`, `pending=False`.
  - **`in_progress`** — a submission with `status == IN_PROGRESS`. `score=max_score=None`.
  - **`submitted`** — a `SUBMITTED` submission with **no** unreviewed `[R]` response. `score`/`max_score` = the frozen submission values.
  - **`awaiting_review`** — a `SUBMITTED` submission that **has** at least one response whose question is `marking_mode == REVIEW` with `reviewed_at is None` (resolved via the GFK path above). `score`/`max_score` = the frozen `[A]`-only values (shown as "so far"), `pending=True`. **The `[A]` portion still counts in the course total** (it *is* the frozen `submission.score`); the pending `[R]` marks do not (consistent with 2c's `[A]`-only freeze). *(Within 2e `reviewed_at` is never set — no review path exists — so every `[R]` response is pending; see §4.2 I-note.)*
- **`url`/`url_name`** per status: `submitted`/`awaiting_review` → `courses:quiz_results`; `not_started` → `courses:quiz_unit` (go take it); `in_progress` → `courses:quiz_unit` (resume). (Storing `url_name` keeps the template free of status→route logic.) **Drill-down reuse is known-good, not assumed:** `quiz_results` filters `status=SUBMITTED` (and an `awaiting_review` submission *is* `SUBMITTED`), and its `_results_row` already classifies an unreviewed `[R]` response as the `"review"` outcome (2d-iii §3.4) — so an `awaiting_review` row's drill-down renders the existing page correctly with the `[R]` questions shown as "awaiting review." **Pinned by a test** (§4.4) that a SUBMITTED-with-unreviewed-`[R]` submission renders without error and shows the review outcome.
- **Returns** `{ "course": course, "rows": [...], "done_count": int, "total_count": int, "score": Decimal|None, "max_score": Decimal|None, "percent": int|None }`, applying the §2.1 headline rule over the rows. `percent` is a Python **`int`** (`int(round(...))`, §2.1) or `None`; `score`/`max_score` are passed through as `Decimal|None` to the `marks` filter.

**Pinned property (tested):** `build_course_results` is a pure function of `(course, student)` + DB; it never writes; the headline sums **submitted-only**; an `awaiting_review` row contributes its frozen `[A]` score to the total but is flagged `pending`; row order is the outline's depth-first pre-order quiz sequence; `percent` is `int|None`.

### 3.2 View `course_results`

In `courses/views.py`, a new `@login_required` view modelled on `course_outline`:

```
@login_required
def course_results(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_access_course(request.user, course):
        raise PermissionDenied
    summary = build_course_results(course, request.user)
    return render(request, "courses/course_results.html",
                  {"course": course, "summary": summary})
```

- **Access guard = the existing `can_access_course`** (same as `course_outline`/`quiz_results`). **The view never accepts a student id** — it is always `request.user`, so there is no IDOR surface (§4).
- **Previewing teacher/CA/PA:** `can_access_course` admits them; they see *their own* submissions (i.e. an empty summary unless they took the quizzes), exactly as §3.1 of the inventory says staff "preview like a student, untracked." The cross-student teacher view is Phase 3.
- **URL** in `courses/urls.py`: `path("courses/<slug:slug>/results/", views.course_results, name="course_results")` — note the **`courses/` prefix**, which every sibling pattern in `courses/urls.py` carries (`courses/<slug:slug>/` for the outline, `courses/<slug:slug>/u/<int:node_pk>/quiz/results/` for `quiz_results`); omitting it would not match the app's URL layout. (Distinct from the per-quiz `quiz_results` at `courses/<slug>/u/<node_pk>/quiz/results/`.)

### 3.3 Template `templates/courses/course_results.html`

- **Header:** course title + *"My results"* heading; the headline line *"Done {{ summary.done_count }} of {{ summary.total_count }} quizzes · NN% · S / M"*. **The percent token must be None-guarded in the template** — `{{ summary.percent }}%` would render the literal "None%" when `percent is None`; use `{% if summary.percent is None %}—{% else %}{{ summary.percent }}%{% endif %}` (or a None-aware filter). The score uses the `marks` filter (`{{ summary.score|marks }} / {{ summary.max_score|marks }}`), which already renders "—" for `None`; when `percent is None` (no submitted quizzes / only-`[N]`) the whole headline tail collapses to "—".
- **List:** one row per `summary.rows` entry, mirroring the outline's visual rhythm (bespoke token CSS, no new deps). Each row: quiz title, a status presentation, the score (`X/Y` for graded rows; "—" otherwise), and a link via `{% url row.url_name course.slug row.unit.pk %}`. **All four row targets take `(slug, node_pk=row.unit.pk)`** — `quiz_results` and `quiz_unit` are both `<slug>/u/<int:node_pk>/…` routes, and `row.unit` is the quiz `ContentNode` whose `.pk` is the `node_pk` (there is no "no-node_pk" target among the rows). Status presentation:
  - `submitted` → `{{ row.score|marks }} / {{ row.max_score|marks }}` + "details" link.
  - `awaiting_review` → `{{ row.score|marks }} / {{ row.max_score|marks }}` + "⏳ awaiting review" cue + "details" link.
  - `in_progress` → "in progress" + "resume" link.
  - `not_started` → "— · not started" + "start" link.
- **Empty states:** a course with **no quiz units** renders a friendly "No quizzes in this course yet"; a student who has taken **none** renders the rows all-`not_started` with headline "Done 0 of N · —".
- **Footer:** "Back to course" → `course_outline`.

### 3.4 Entry points (minimal edits)

- **Course outline header** (`templates/courses/outline.html`): add a **"My results"** link → `courses:course_results`. (No score data on the outline itself.)
- **My-courses card** (`templates/courses/my_courses.html`): add a **"My results"** link per course card → `courses:course_results`. (No per-course total computed on the My-courses list — that would be an N-course aggregation the user declined; the link is the entry point.)

---

## 4. Invariants, edge cases & testing

### 4.1 Invariants

- **IDOR / own-data-only:** `course_results` derives the student solely from `request.user`; it exposes no student-id parameter. A student can never view another student's results. Pinned by test (authenticated as student A, the view shows only A's submissions; there is no URL by which to request B's).
- **No new leak:** the summary shows only scores/statuses the student is already entitled to on their own `quiz_results` pages. It renders **no question stems, answers, or keyword/reveal payloads** — it links to `quiz_results`, which enforces its own 2c reveal gating unchanged. No keyword/answer text appears on the summary page.
- **Read-only / no scoring change:** 2e writes nothing to `QuizSubmission.score`/`max_score`/`QuestionResponse`; `_score_submission` and `scoring.py` are untouched; a quiz's frozen total is byte-identical to 2c. The reserved `submitted_by` is never written by 2e (§2.2).
- **Current-mode classification:** `awaiting_review` reads the **current** `marking_mode` (consistent with `_results_row`/`_score_submission`), so a quiz re-marked `[R]→[A]` after submit behaves consistently across the results page and the summary.
- **`SUBMITTED` is terminal (no revert):** in the current 2c model, `quiz_finish` freezes the score and locks the responses; there is **no path that reverts a `SUBMITTED` submission back to `IN_PROGRESS`** (no quiz-level retake — `max_attempts` is per-question, within an in-progress submission). So a quiz once counted in the headline never silently flips back to `in_progress` and loses its frozen score. The status matrix relies on this; a test asserts a finished submission stays `SUBMITTED`. (If a future phase adds quiz retakes, it must define the headline/status consequence then — out of scope here.)

### 4.2 Edge cases (handled explicitly)

- **Zero submitted quizzes** → headline "Done 0 of N · —" (percent `None`), all rows `not_started`. No div-by-zero.
- **Course with no quiz units at all** → empty-state card; page still reachable (no crash, `total_count == 0`, percent `None`).
- **Fully-`[N]` quiz** (all questions not-marked) → `max_score == Decimal("0.00")` on submit; row shows status `submitted` with `score/max_score = 0/0` ("submitted — not graded"). It **counts toward `done_count`** (it *is* a `SUBMITTED` submission) but adds `0` to **both** the score and max-score sums — so it is **score-neutral**, not "excluded": the headline percentage is `Σ score / Σ max` over the *other* quizzes, unchanged by the `0/0` term. Worked example to lock the numbers: one `[N]` quiz (`0/0`) + one `[A]` quiz (`5/10`) → headline **"Done 2 of 2 · 50% · 5 / 10"** (the `5/10` legitimately does not visibly account for the ungraded `[N]` quiz — that is intended). A course of **only** `[N]` quizzes yields `Σ max == 0` → the global zero-guard makes `percent` `None` → "—". It is **never** `awaiting_review` (no `[R]` responses). A test pins both the mixed `[N]`+`[A]` headline and the all-`[N]` "—".
- **Mixed `[A]`+`[R]` quiz, submitted, unreviewed** → `awaiting_review`; frozen `[A]` score counts; `pending=True` surfaces the cue. (When Phase 3 reviews it and folds the `[R]` marks into the total, the summary reflects the new frozen score automatically — that recompute is Phase 3's job.)
- **Reviewed-`[R]` is unreachable in 2e (the "stale `submitted` score" trap):** one might worry that a `SUBMITTED` quiz whose `[R]` responses were all reviewed would fall into status `submitted` while still carrying its `[A]`-only frozen `score` (which excludes the reviewed `[R]` marks) — a misleadingly "final-looking" number. **This state cannot occur in 2e:** `reviewed_at` is only ever set by Phase 3's review flow (2e writes nothing — §4.1), so within 2e every `[R]` response has `reviewed_at is None` and any `[R]`-bearing submission is therefore always `awaiting_review`, never a `submitted` with hidden-stale score. Phase 3, when it sets `reviewed_at`, also owns the score recompute that keeps `submitted` honest. A test asserts that in 2e an `[R]`-bearing submission classifies as `awaiting_review`.
- **In-progress (resumable) submission** → `in_progress`, excluded from the headline, links to resume.
- **Reserved seam inert** → a normal student submission leaves `submitted_by` null and the aggregation ignores it (test).

### 4.3 i18n

All new strings — the headline ("Done X of Y quizzes", the "/" score), the statuses ("not started", "in progress", "awaiting review", "submitted — not graded"), the "details"/"resume"/"start" link labels, "My results", "Back to course", and the two empty-states — wrapped for EN/PL with real Polish, matching the 2b/2c/2d i18n passes.

### 4.4 Testing

- **Unit/integration (pytest + factory_boy, real PostgreSQL):**
  - `build_course_results` purity + the status matrix: `not_started`, `in_progress`, `submitted`, `awaiting_review`, fully-`[N]` (`submitted`/not-graded), and a mixed course; assert `done_count`/`total_count`, that the headline sums **submitted-only**, the zero-denominator guard (no quizzes; only-`[N]`; none-taken), and that an `awaiting_review` row contributes its frozen `[A]` score to the total while flagged `pending`.
  - **Headline numbers (locked):** mixed `[N]`(`0/0`)+`[A]`(`5/10`) course → "Done 2 of 2 · 50% · 5 / 10"; all-`[N]` course → percent `None` ("—"); `percent` is asserted to be a Python `int` (not `Decimal`) on a graded course.
  - **Row order:** assert rows come back in the outline's **depth-first pre-order** quiz-unit sequence (build a course with quizzes nested under multiple chapters/sections in a known `order` and check the row sequence).
  - **Query budget — a single concrete count:** with a fixed fixture (known question content-types), assert `build_course_results` runs **exactly N** queries (`N = 3 base — nodes, submissions, responses — + one per question content-type present`), proving no per-row/per-unit N+1 (`assertNumQueries`/`django_assert_num_queries`). State the exact N for the chosen fixture in the test.
  - **`awaiting_review` detection via the GFK:** a SUBMITTED quiz with an `[R]` question (and `reviewed_at is None`) classifies as `awaiting_review`; an all-`[A]` SUBMITTED quiz classifies as `submitted`; pins the `response.element.content_object.marking_mode` traversal.
  - **Terminal submission:** a finished submission stays `SUBMITTED` (no revert-to-`IN_PROGRESS` path); the row never flips back to `in_progress`.
  - Row URLs: `submitted`/`awaiting_review` → `quiz_results`; `not_started`/`in_progress` → `quiz_unit`.
  - **Drill-down reuse (guards C3):** the existing `quiz_results` page renders a SUBMITTED submission that has an **unreviewed `[R]`** response without error and shows the `"review"` outcome for it — so an `awaiting_review` row's link is known-good.
  - View access — **two distinct assertions:** (a) **unauthenticated** GET → **302** login redirect (via `@login_required`); (b) **authenticated but non-enrolled** student → **403** (`PermissionDenied` from `can_access_course`). Plus: an enrolled student renders the headline + rows.
  - **IDOR:** `course_results` derives the student solely from `request.user` and exposes no student-id parameter — a student can only ever see their own submissions (assert student A's page reflects only A's data; there is no URL to request B's).
  - **Seam (only if the §2.2 `submitted_by` column is kept — conditional on the §1.5 review-gate decision):** migration adds `submitted_by` nullable; a 2c-shaped submission leaves it null and finishes identically; the aggregation ignores it. *(If the seam is dropped, this bullet and §4.5 are void.)*
- **e2e (Playwright, JS + no-JS):** student takes **1 of 2** quizzes → opens "My results" from the outline → sees "Done 1 of 2", the taken quiz's `X/Y` with a working **drill-down** to its `quiz_results` page, and the other quiz as "not started" with a "start" link; for a quiz containing an `[R]` question, the row shows **"awaiting review"**; the "My results" links from **both** the outline header and the My-courses card resolve to the page. (No JS dependency — the page is plain server-rendered links, works identically JS on/off.)

### 4.5 Migration

One migration — `AddField QuizSubmission.submitted_by` (nullable, metadata-only AddField with the auto-added swappable_dependency). The number is **`0020` as the next available today** (latest is `0019_extendedresponsequestionelement_and_more`); `makemigrations` assigns it. No alteration to existing tables' data. Passes the migration-consistency gate. *(If the §1.5 reserved seam is dropped at the review gate, this section is void — 2e ships with no migration.)*
