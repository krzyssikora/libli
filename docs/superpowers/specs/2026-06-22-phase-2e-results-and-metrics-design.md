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
- The student's **`QuizSubmission`s** for this course — one query: `QuizSubmission.objects.filter(student=student, unit__course=course)`, indexed into a `{unit_id: submission}` dict. The **≤1-per-unit invariant is DB-enforced** by `UniqueConstraint(fields=["student", "unit"], name="uniq_quizsubmission_student_unit")` (models.py:920–922) — *not* status-scoped, so the index can never silently overwrite a row.

Headline (per §1.4): over submissions with `status == SUBMITTED`, `score = Σ submission.score` (a `Decimal`), `max_score = Σ submission.max_score` (a `Decimal`), `percent = int(round(100 * score / max_score))` — **explicitly cast to a Python `int`** so the template comparison `percent is None` and test assertions are type-stable — guarded for `max_score in (None, 0)` → `percent is None` (rendered "—"). `score`/`max_score` stay `Decimal` (passed to the `marks` filter). `done_count` = number of `SUBMITTED` submissions (this **includes** a fully-`[N]` submitted quiz — it *is* submitted — even though it contributes `0/0` to the score sums; see §4.2); `total_count` = number of quiz units in the course.

### 2.2 `QuizSubmission` — the reserved force-submit seam (1 nullable column)

In `courses/models.py`, add to the existing `QuizSubmission`:

```
submitted_by = models.ForeignKey(
                   settings.AUTH_USER_MODEL, null=True, blank=True,
                   on_delete=models.SET_NULL, related_name="+")
```

- **Nullable, no default change to existing rows** (an `AddField(null=True)` is a metadata-only migration). **No 2e code reads or writes it** — `course_results` and `build_course_results` ignore it entirely.
- **Semantics for Phase 3 (documented, not enforced here):** `submitted_by is None` ⇔ a self-submitted quiz. **Every 2e-created submission leaves `submitted_by` at its `NULL` default; no 2e code path assigns it** (the existing `quiz_finish` is untouched — §4.1). When Phase 3 builds teacher force-submit, it sets `submitted_by` = the teacher; the existing `student` FK stays the owning student, so the summary picks the submission up unchanged.
- `related_name="+"` (no reverse accessor) — Phase 3 can widen it; 2e needs no `user.submitted_for` query. **`"+"` is used specifically to avoid a reverse-accessor clash** with the user model's other FKs (`QuizSubmission.student`, `QuestionResponse.reviewed_by`/`student` — several FKs already target `AUTH_USER_MODEL`); without it Django would require a unique `related_name` and could collide.
- Because `submitted_by` targets `settings.AUTH_USER_MODEL`, `makemigrations` auto-adds the `migrations.swappable_dependency(settings.AUTH_USER_MODEL)` dependency — **generate the migration, do not hand-write it.**

### 2.3 Migration (next available; `0020` indicative)

One migration: `AddField QuizSubmission.submitted_by` (nullable, metadata-only). No data migration. The number is **`0020` as the next available** (the latest migration **at spec time** is `0019_extendedresponsequestionelement_and_more` — not a hard precondition; it can shift if other work lands first); `makemigrations` assigns it — treat `0020` as indicative and **re-check at build time**. Passes the migration-consistency gate. *(If the §1.5 seam is dropped at review, 2e has **no migration** at all.)*

---

## 3. The helper, view & rendering

### 3.1 `build_course_results(course, student)` — pure aggregation helper

A new function in **`courses/rollups.py`** (sibling of `build_outline`, same shape: a tree walk + one per-user query, returning plain dicts). Pure of side effects; deterministic given `(course, student)` + DB state.

```
def build_course_results(course, student) -> dict
```

**`student` here means "the viewing user" (`request.user`)** — named `student` for the common case, but it is whoever is viewing (a previewing teacher is admitted by `can_access_course` and sees their own, usually empty, submissions). Either naming (`user` à la `build_outline`, or `student`) is acceptable at build time as long as the docstring states this.

- **Quiz-unit enumeration & ordering (pin the flatten).** Quiz units are emitted in the **depth-first pre-order** of the content tree — the order they appear walking the outline top-to-bottom — and the flattened sequence is **filtered to `kind == UNIT and unit_type == QUIZ`** (lesson units and container nodes — part/chapter/section — are **excluded** from rows). **Critical implementation note:** `course.nodes.all()` is a *flat, globally-sorted* queryset (sorted by `ContentNode.Meta.ordering = ["order", "pk"]` — models.py:109–110) across **all** depths at once; a **linear iteration of that flat queryset is NOT depth-first pre-order** and is **not** a valid implementation (sibling `order` values are only locally monotonic — `OrderField(for_fields=["course", "parent"])`, models.py:99 — so a chapter `order=0` with a child section `order=5` and a sibling chapter `order=1` interleave wrongly in a flat scan). The flatten **MUST recurse the `parent_id`-grouped structure** (group nodes by `parent_id`, recurse children in `Meta.ordering`). **Chosen path (pinned): build_course_results does its own private `parent_id`-grouped pre-order walk over the single `course.nodes.all()` query it already issues** — it does **NOT** call `build_outline` (which would run its own extra nodes + `UnitProgress` queries and inflate the budget). (A shared flattener over `build_outline`'s nested result is acceptable *only* if its extra queries are folded into the budget — but the pinned path avoids that.) **The tested properties:** (1) row order equals the depth-first pre-order quiz sequence of the outline; (2) lesson units and container nodes never appear as rows. The order test **interleaves a lesson unit** among quizzes to prove it is skipped while order is preserved.
- **Query budget — the invariant is N-independence, not a hand-counted integer.** The helper's query count must be **independent of the number of quiz units and submissions** (no per-row/per-unit N+1); it grows **only** with the number of distinct question **content-types** present (the GFK batch). The base queries are: **(1)** the course's nodes (one `course.nodes.all()`, reused for both the flatten and the element scan); **(2)** the student's `QuizSubmission`s (`filter(student=student, unit__course=course)`), indexed `{unit_id: submission}`; **(3)** the **question `Element`s of the course's quiz units** in one query — **filtered to question content-types** (`Element.objects.filter(unit__in=<quiz unit pks>, content_type_id__in=<question_ct_ids>)`, the `question_ct_ids` set built exactly as views.py:101 does), since `Element` is the GFK join-row that can point at *any* element (Text/Image/Math/Html too — models.py:154); without the `content_type_id__in` filter the scan and its GFK batch would also pull non-question elements — **with their GFK content_objects batched** via `prefetch_related("content_object")` (one query per **question** content-type). This supplies each unit's question `marking_mode`s for the `awaiting_review` test (see next bullet). (Defensive parity with `quiz_results`: even with the CT filter, treat the scan as "skip anything that isn't a `QuestionElement`," mirroring views.py:585's `isinstance(q, QuestionElement)` guard.) The budget thus grows only with the number of distinct **question** content-types present. **2e does NOT query `QuestionResponse` at all** (the score lives on the frozen submission; the `[R]`-pending signal is element-driven — C1 below). **Do not assert a hand-counted integer in the spec** — the FK-then-GFK prefetch's exact query count is implementation-dependent; the **test author derives the exact `N` empirically** (`django_assert_num_queries`) and pins it as a regression guard. What the spec pins is the *shape*: `N` stays constant when you 10× the units/submissions and changes only when you add a new question content-type. (`build_outline`'s "two queries" is a *sibling precedent*, not a budget this helper must match.)
- **`awaiting_review` is element-driven, not response-driven (C1 — load-bearing).** `QuestionResponse` rows are created **lazily, only when a student answers a question** (`get_or_create` in `quiz_answer`, views.py:464). So a student who **submits a quiz without answering an `[R]` question has no response row for it** — scanning responses would miss that pending `[R]` and mislabel the quiz `submitted`, disagreeing with `quiz_results`' own `pending_count`, which counts `[R]` **elements** of `node.elements` regardless of whether they were answered (views.py:591). Therefore detect `[R]`-pendingness from the unit's **question elements**, exactly like `pending_count`: a `SUBMITTED` quiz is `awaiting_review` iff its unit has **≥1 question element with `marking_mode == REVIEW`**. `marking_mode`/`max_marks` live on `QuestionElement` (each concrete subclass's own column, since the base is abstract) reached via `element.content_object` (the `GenericForeignKey`, models.py:171) on each `Element` (models.py:939) of the unit — the same resolution `_score_submission`/`_results_row` use, read at **current** mode. This is the query-(3) element scan above. **Why this is correct for 2e specifically:** `reviewed_at` is never set in 2e (no review path), so every `[R]` element is unreviewed → "has an `[R]` element" ≡ "awaiting review." (Phase 3, when reviews exist, refines this to "has an `[R]` element **whose review is not yet complete**" by joining `QuestionResponse.reviewed_at` — and also owns the score recompute; out of scope here.)
- **Per quiz unit**, build a **row** dict: `{ "unit": node, "status": <str>, "graded": <bool>, "score": <Decimal|None>, "max_score": <Decimal|None>, "pending": <bool>, "url_name": <str> }`. (Only `url_name` is stored — the template resolves the link with `{% url row.url_name course.slug row.unit.pk %}`; no pre-resolved `url` string, to avoid two drifting sources of the same link.) **`graded`** = `True` iff the **unit has ≥1 `[A]` question element** (element-driven, symmetric with the `awaiting_review` rule — derived from the same query-(3) marking-mode scan). **This is equivalent to `max_score > 0`** because every `[A]` question's `max_marks` carries `MinValueValidator(Decimal("0.01"))` (models.py:332–336), so any `[A]` question contributes a strictly positive amount and `max_score == 0 ⇔ no [A] question`; defining `graded` element-driven (rather than `max_score > 0`) avoids any reliance on the score-sum and is robust even if a future change weakened that validator. `graded` discriminates a normally-marked `submitted` row (`graded=True`, render `X/Y`) from a fully-`[N]` `submitted` row (`graded=False`, render the "submitted — not graded" cue) — see §3.3. `not_started`/`in_progress` rows are `graded=False` (no submitted score).
- **`status`** ∈ `{"not_started", "in_progress", "submitted", "awaiting_review"}`:
  - **`not_started`** — **no `QuizSubmission` row** for the unit. `score=max_score=None`, `pending=False`. **Create-point boundary (pinned against 2c):** `quiz_unit`'s GET does `QuizSubmission.objects.get_or_create(student=user, unit=node)` for any **enrolled** user (views.py:329), so a row is created the moment a student **opens** the quiz. Therefore `not_started` means **"never opened the quiz page"** (no GET as an enrolled student), not merely "no answers." (A non-enrolled previewing staff user never triggers the `get_or_create` — guarded by `is_enrolled` — so their rows are all `not_started`.)
  - **`in_progress`** — a `QuizSubmission` with `status == IN_PROGRESS` (i.e. **opened but not finished**, including the opened-with-zero-answers case, per the create-point above). `score=max_score=None`.
  - **`submitted`** — a `SUBMITTED` submission whose unit has **no `[R]` question element** (element-driven, per the C1 bullet). `score`/`max_score` = the frozen submission values; `pending=False`. `graded` then distinguishes a marked quiz (`max_score > 0` → render `X/Y`) from a fully-`[N]` quiz (`max_score == 0` → "submitted — not graded").
  - **`awaiting_review`** — a `SUBMITTED` submission whose unit has **≥1 `[R]` question element** (element-driven; see the C1 bullet — *not* a response scan). `score`/`max_score` = the frozen `[A]`-only values (shown as "so far"), `pending=True`, `graded` per the same `max_score > 0` rule. **The `[A]` portion still counts in the course total** (it *is* the frozen `submission.score`); the pending `[R]` marks do not (consistent with 2c's `[A]`-only freeze). *(Within 2e `reviewed_at` is never set, so an `[R]`-bearing submitted quiz is always `awaiting_review`; see §4.2.)*
- **`url_name`** per status: `submitted`/`awaiting_review` → `courses:quiz_results`; `not_started` → `courses:quiz_unit` (go take it); `in_progress` → `courses:quiz_unit` (resume). (Storing `url_name` keeps the template free of status→route logic.) **Drill-down reuse is known-good, not assumed:** `quiz_results` filters `status=SUBMITTED` (and an `awaiting_review` submission *is* `SUBMITTED`), and its `_results_row` already classifies an unreviewed `[R]` response as the `"review"` outcome (2d-iii §3.4) — so an `awaiting_review` row's drill-down renders the existing page correctly with the `[R]` questions shown as "awaiting review." **Pinned by a test** (§4.4) that a SUBMITTED-with-unreviewed-`[R]` submission renders without error and shows the review outcome.
- **Returns** `{ "course": course, "rows": [...], "done_count": int, "total_count": int, "score": Decimal|None, "max_score": Decimal|None, "percent": int|None }`, applying the §2.1 headline rule over the rows. `percent` is a Python **`int`** (`int(round(...))`, §2.1) or `None`; `done_count`/`total_count` are plain Python **`int`s** (from `len(...)`, not a `Decimal`/queryset `.count()` surprise); `score`/`max_score` are passed through as `Decimal|None` to the `marks` filter. So every headline scalar's type is uniformly pinned.

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

- **Context:** `course` is passed **top-level intentionally** as the template's canonical source even though `summary` also carries a `course` key (§3.1); the template references the top-level `course` (see §3.3).
- **Access guard = the existing `can_access_course`** (same as `course_outline`/`quiz_results`). **The view never accepts a student id** — it is always `request.user`, so there is no IDOR surface (§4).
- **Previewing teacher/CA/PA:** `can_access_course` admits them; they see *their own* submissions (i.e. an empty summary unless they took the quizzes), exactly as §3.1 of the inventory says staff "preview like a student, untracked." The cross-student teacher view is Phase 3.
- **URL** in `courses/urls.py`: `path("courses/<slug:slug>/results/", views.course_results, name="course_results")` — note the **`courses/` prefix**, which every sibling pattern in `courses/urls.py` carries (`courses/<slug:slug>/` for the outline, `courses/<slug:slug>/u/<int:node_pk>/quiz/results/` for `quiz_results`); omitting it would not match the app's URL layout. (Distinct from the per-quiz `quiz_results` at `courses/<slug>/u/<node_pk>/quiz/results/`.)

### 3.3 Template `templates/courses/course_results.html`

- **Header:** course title + *"My results"* heading, then the headline line with **two canonical forms** (pinned verbatim so the §4.4 string tests aren't brittle):
  - **`percent is not None`** → *"Done {X} of {Y} quizzes · {NN}% · {S} / {M}"* (e.g. "Done 3 of 5 quizzes · 60% · 9 / 15").
  - **`percent is None`** (no submitted quizzes, or only-`[N]`) → *"Done {X} of {Y} quizzes · —"* — the **entire `{NN}% · {S} / {M}` tail is suppressed and replaced by a single "—"** (NOT "· — · — / —"). Template: `Done {{ summary.done_count }} of {{ summary.total_count }} quizzes ·{% if summary.percent is None %} —{% else %} {{ summary.percent }}% · {{ summary.score|marks }} / {{ summary.max_score|marks }}{% endif %}`. (This both avoids the "None%" literal and keeps the empty-state to a single dash.)
- **List:** one row per `summary.rows` entry, mirroring the outline's visual rhythm (bespoke token CSS, no new deps). Each row: quiz title, a status presentation, the score (`X/Y` for graded rows; "—" otherwise), and a link via `{% url row.url_name course.slug row.unit.pk %}`. **All four row targets take `(slug, node_pk=row.unit.pk)`** — `quiz_results` and `quiz_unit` are both `<slug>/u/<int:node_pk>/…` routes, and `row.unit` is the quiz `ContentNode` whose `.pk` is the `node_pk` (there is no "no-node_pk" target among the rows). **`course` here is the top-level context var the view passes** (§3.2), not `summary.course` — the helper also returns `course` inside its dict (handy for callers/tests), but the template references the explicit `course` context var to keep one canonical source. Status presentation:
  - `submitted` → **branch on `row.graded`:** if `graded` (a marked quiz, `max_score > 0`) render `{{ row.score|marks }} / {{ row.max_score|marks }}` + "details" link; if **not** `graded` (a fully-`[N]` quiz, `max_score == 0`) render the **"submitted — not graded"** cue (the distinct §4.3 i18n string) + "details" link — **do not render "0 / 0"** for the `[N]` case.
  - `awaiting_review` → an "awaiting review" cue + "details" link, **plus** `{{ row.score|marks }} / {{ row.max_score|marks }}` ("so far") **only when `row.graded`** (i.e. the quiz has an `[A]` portion); an all-`[R]` quiz (`max_score == 0`, `graded=False`) shows just the cue, no "0 / 0". **The "⏳" glyph stays a template literal outside the `{% trans %}` wrapper** — only the text "awaiting review" is translated (don't bundle the emoji into the i18n string).
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
- **`done_count` counts every `SUBMITTED` quiz (incl. fully-`[N]`); the percent denominator excludes ungraded marks** — a deliberate, pinned asymmetry: `done_count`/`total_count` measure *completion*, while `percent = Σ score / Σ max_score` measures *graded performance*, and a fully-`[N]` quiz is "done" (counts) but contributes `0/0` (no denominator effect). A test pins this on the mixed `[N]`+`[A]` course. *(A secondary "graded N of M" sub-count that would make the asymmetry explicit in the headline is considered and **deferred** — not v1; the per-row "submitted — not graded" cue carries that signal for now.)*

### 4.2 Edge cases (handled explicitly)

- **Zero submitted quizzes** → headline "Done 0 of N · —" (percent `None`), all rows `not_started`. No div-by-zero.
- **Course with no quiz units at all** → empty-state card; page still reachable (no crash, `total_count == 0`, percent `None`).
- **Fully-`[N]` quiz** (all questions not-marked) → `max_score == Decimal("0.00")` on submit; row shows status `submitted` with `score/max_score = 0/0` ("submitted — not graded"). It **counts toward `done_count`** (it *is* a `SUBMITTED` submission) but adds `0` to **both** the score and max-score sums — so it is **score-neutral**, not "excluded": the headline percentage is `Σ score / Σ max` over the *other* quizzes, unchanged by the `0/0` term. Worked example to lock the numbers: one `[N]` quiz (`0/0`) + one `[A]` quiz (`5/10`) → headline **"Done 2 of 2 · 50% · 5 / 10"** (the `5/10` legitimately does not visibly account for the ungraded `[N]` quiz — that is intended). The **per-row "submitted — not graded" cue** on the `[N]` row (§3.3, `graded=False`) is what disambiguates the headline for the student; this minor headline-vs-rows asymmetry is an **accepted UX tradeoff**, not a defect. A course of **only** `[N]` quizzes yields `Σ max == 0` → the global zero-guard makes `percent` `None` → "—". It is **never** `awaiting_review` (no `[R]` responses). A test pins both the mixed `[N]`+`[A]` headline and the all-`[N]` "—".
- **Fully-combined headline (the implementer-trip case, locked):** a course of **5** quiz units — A: `submitted [A]` `6/10`; B: `awaiting_review [A+R]` with frozen `[A]` portion `3/5`; C: fully-`[N]` `0/0` submitted; D: `in_progress` (opened, unfinished); E: `not_started` (never opened) — yields **`done_count = 3`** (A, B, C are `SUBMITTED`; D and E are not), **`total_count = 5`**, **`score = 9`** (`6 + 3 + 0`), **`max_score = 15`** (`10 + 5 + 0`), **`percent = 60`** → headline **"Done 3 of 5 · 60% · 9 / 15"**, with B also surfacing its `pending` "awaiting review" cue. A test locks these exact numbers (this is the one case that combines every status — it is the canonical headline regression test).
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
  - **Query budget — N-independence (not a hand-counted constant):** with a fixed fixture, record the **empirical** query count `N` (`django_assert_num_queries`) and pin it as a regression guard; then assert that **10×-ing the number of quiz units/submissions leaves the count unchanged** (no per-row/per-unit N+1), and that it rises only when a new question content-type is introduced. Do not assert a hand-derived integer — read what Django actually issues for the fixture (§3.1).
  - **`awaiting_review` is element-driven (guards C1):** a SUBMITTED quiz whose unit has an `[R]` question classifies as `awaiting_review`; an all-`[A]` SUBMITTED quiz classifies as `submitted`; pins the `element.content_object.marking_mode` traversal over `node.elements`. **Critical regression:** a SUBMITTED quiz where the `[R]` question was **left unanswered** (so **no `QuestionResponse` row** exists for it — responses are lazy, views.py:464) **still** classifies as `awaiting_review` — a response-driven scan would wrongly call it `submitted`. (Also assert it agrees with `quiz_results`' `pending_count` for the same quiz.)
  - **`graded` discriminator / `[N]`-row rendering:** a fully-`[N]` SUBMITTED quiz has `status=="submitted"`, `graded==False`, and the row renders the **"submitted — not graded"** cue (the §4.3 string), **not** "0 / 0"; a marked `[A]` SUBMITTED quiz has `graded==True` and renders `X/Y`. An all-`[R]` quiz is `awaiting_review`, `graded==False`, renders the cue with no "0 / 0".
  - **Terminal submission:** a finished submission stays `SUBMITTED` (no revert-to-`IN_PROGRESS` path); the row never flips back to `in_progress`.
  - Row URLs: `submitted`/`awaiting_review` → `quiz_results`; `not_started`/`in_progress` → `quiz_unit`.
  - **Drill-down reuse (guards C3):** the existing `quiz_results` page renders a SUBMITTED submission whose unit has an **unreviewed `[R]` question** (answered **or** unanswered) without error and shows the `"review"` outcome for it — so an `awaiting_review` row's link is known-good.
  - View access — **three distinct assertions:** (a) **unauthenticated** GET → **302** login redirect (via `@login_required`); (b) **authenticated but non-enrolled** *non-staff* student → **403** (`PermissionDenied` from `can_access_course`); (c) **non-enrolled `is_staff` previewer** → **200** with an **all-`not_started` empty summary** ("Done 0 of N", no submissions — `is_enrolled` guards the `get_or_create`, so the previewer creates nothing), locking the §3.2 staff-preview promise. Plus: an enrolled student renders the headline + rows.
  - **IDOR:** `course_results` derives the student solely from `request.user` and exposes no student-id parameter — a student can only ever see their own submissions (assert student A's page reflects only A's data; there is no URL to request B's).
  - **Seam (only if the §2.2 `submitted_by` column is kept — conditional on the §1.5 review-gate decision):** migration adds `submitted_by` nullable; a 2c-shaped submission leaves it null and finishes identically; the aggregation ignores it. *(If the seam is dropped, this bullet and §4.5 are void.)*
- **e2e (Playwright, JS + no-JS):** student takes **1 of 2** quizzes → opens "My results" from the outline → sees "Done 1 of 2", the taken quiz's `X/Y` with a working **drill-down** to its `quiz_results` page, and the other quiz as "not started" with a "start" link; for a quiz containing an `[R]` question, the row shows **"awaiting review"**; the "My results" links from **both** the outline header and the My-courses card resolve to the page. (No JS dependency — the page is plain server-rendered links, works identically JS on/off.)

### 4.5 Migration

One migration — `AddField QuizSubmission.submitted_by` (nullable, metadata-only AddField with the auto-added swappable_dependency). The number is **`0020` as the next available** (the latest migration **at spec time** is `0019_extendedresponsequestionelement_and_more`, not a hard precondition); `makemigrations` assigns it — re-check at build time. No alteration to existing tables' data. Passes the migration-consistency gate. *(If the §1.5 reserved seam is dropped at the review gate, this section is void — 2e ships with no migration.)*
