# Continue where you left off

A resume affordance at the top of the student course-outline page, so a returning student
re-enters the course at the unit they should work on next instead of hunting for it in the tree.

## Purpose

Today `templates/courses/outline.html` opens with a title, three utility links ("My results",
"My notes", "Start fresh") and a JS-revealed "Expand all" toggle button, then the full outline
tree.

There is **no course-level resume affordance**. The only resume affordance that exists today is
per-quiz and one click away: `templates/courses/course_results.html:32` renders a `resume` link
for each `in_progress` quiz row (and a `start` link for `not_started` rows), reachable via the
"My results" link in `.outline__head`. That page is quiz-only — `build_course_results` builds its
rows from quiz units — so its per-row statuses will **not** always agree with this card, which
also considers lessons. That divergence is expected, not a bug to reconcile.

This adds one card at the top of the outline pointing at a single unit, chosen by a **hybrid
resume rule**: the unit you were most recently working in, *if that is more recent than your last
completion*; otherwise the next unfinished unit after the one you most recently completed. The
"if that is more recent" qualifier is not a detail — without it the rule is the stray-click bug
described under step 3.

Out of scope (deliberately): the dashboard (`core/views.py::home`), the "My courses" list, the
catalog, `course_results.html`, any change to how progress is recorded, and any new model or
migration.

## Definition of the target

Stated as an **ordered algorithm with a single terminal `None`**, not a table of independent
rows — the branches overlap and their precedence is load-bearing.

Let `leaves` be the visible unit-leaf dicts in outline order, and `open` the subset whose
`completed` is false.

```
1. if `open` is empty                          -> return None
     (covers "no visible units" and "student completed everything")

2. `flight`, ts_f = most recent IN-FLIGHT unit, restricted to `open`      (sources A/B/C)
   `done`,   ts_d = most recent COMPLETED unit, restricted to `leaves`    (source D)

3. if `flight` exists AND (`done` does not exist OR ts_f >= ts_d)
                                               -> return flight,   state = "resume"

4. if `done` exists:
       forward = first member of `open` positioned after `done`
       if forward exists                       -> return forward,  state = "next"
       else                                    -> return open[0],  state = "gap"

5. if the student has ANY progress row in this course (source E)
                                               -> return open[0],  state = "next"

6. otherwise (no rows at all)                  -> return open[0],  state = "start"
```

**Steps 3 and 4 are jointly total** whenever `flight or done` is truthy: step 3 covers
`flight and not done` (and `flight` winning the comparison), step 4 covers every case where `done`
exists. So there is no fifth "flight lost but done was invisible" branch — that state cannot
arise, and an earlier draft's extra branch was dead code.

Every returning branch returns a member of `open`, so the card can never point at a finished unit.
Step 1 runs first, so no later step indexes an empty candidate set.

**Step 3's timestamp comparison is essential, not decorative.** `views.py:511` does
`UnitProgress.objects.get_or_create(...)` on *every* enrolled GET of a lesson, and `views.py:1349`
does the same for `QuizSubmission` on every quiz GET. So a single stray click on unit 3 a year ago
leaves a permanent `completed=False` / `IN_PROGRESS` row. Without the `ts_f >= ts_d` test, that row
outranks every completion made since and the card says "Pick up where you left off — unit 3"
**forever**, contradicting this document's own Purpose sentence. `>=` (not `>`) keeps an in-flight
unit winning a tie, which is the friendlier reading of "where you left off".

**Step 4's `gap` branch** is the wrap-around: a student who finished the final unit but skipped
unit 3 still has work, and a card that silently vanishes while unfinished units remain is worse
than one pointing back at the earliest gap. It gets its **own** state because "Up next" is a false
statement about a unit *earlier* in the course.

**Step 5 exists so `start` never lies.** The example must be one where *every* progress row sits
on a now-invisible unit — concretely, a course restructure that **unpublished** (or drafted) every
unit the student had touched. Such a student has plenty of history, but sources A–D (all
restricted to visible pks) return nothing, so without step 5 they would be told to "Start the
course". `start` fires only when the student genuinely has no progress rows at all.

**Deletion is NOT a route to step 5.** `UnitProgress.unit` and `QuizSubmission.unit` are both
`ForeignKey(ContentNode, on_delete=models.CASCADE)` (`models.py:2934-2939`, `2983-2988`) and
`ContentNode` has no soft-delete column, so deleting a unit destroys its progress rows — a
delete-only history leaves **zero** rows and lands on step 6 (`start`), correctly. Re-parenting a
unit into another course is likewise not a route: source E filters `unit__course=course`.
**Unpublishing/drafting is the only mechanism that reaches step 5**, which is why the cold-path
test fixture has to use an unpublished unit.

(A student who completed units 1–29 and lost only unit 30 to unpublishing does **not** reach step
5: units 1–29 are visible and completed, so source D returns unit 29 and step 4 fires. That case
motivates nothing here.)

**Optional lessons and quizzes count as targets.** `build_outline` distinguishes `required_total`
(obligatory **lesson** units only — `rollups.py::is_obligatory_lesson`) from additional lessons
and quizzes, and the outline surfaces that as `N/M required` plus `+K additional`. This rule
deliberately does **not** inherit that distinction: `open` is every uncompleted visible unit. The
outline lists additional lessons as real, openable content, and a card that skipped them would
leave a student who wants them with no affordance. The consequence — a student who has finished
all *required* work still sees a card pointing at an additional lesson — is intended and tested.

## Recency sources

"Most recent activity" needs several queries, because **no single timestamp in the schema means
"the student was last working here"**. Each source below earns its place, and each is filtered so
that **a teacher's grading writes cannot move a student's resume target** — see "Which teacher
writes can move the target, and which cannot" below for the one case (force-submit) that
legitimately can.

### Membership is enforced *inside* each query

Every source is restricted with `unit_id__in=<pk set>` — `open` pks for A/B/C, `leaves` pks for D.
This is normative and resolves two failure modes at once:

- **Ordering vs. membership.** Filtering first, then taking the latest survivor, is the normative
  reading. Taking the global latest and *then* checking membership is wrong: each source is a
  `LIMIT 1`, so a single row for a since-unpublished unit at the head of the ordering would
  discard every older, still-valid candidate behind it — sending an active student back to unit 1.
- It also **removes the join to `ContentNode`** (`unit__course=course` becomes redundant, since
  the pk sets are already course-scoped and visibility-filtered).

The pk sets come from the already-materialised tree and cost no query. Courses run to hundreds of
units, so the `IN` lists stay well inside sane parameter limits.

### In-flight (sources A, B, C)

| # | Query | What it actually measures |
|---|---|---|
| A | `UnitProgress.filter(student, unit_id__in=open_pks, completed=False).order_by("-updated_at", "-unit_id")` | Lesson work. `updated_at` is `auto_now`, advanced by the `get_or_create` on first open, by every `seen` batch the IntersectionObserver posts, and by every practice-state write. |
| B | `QuizSubmission.filter(student, unit_id__in=open_pks, status=IN_PROGRESS).order_by("-updated", "-unit_id")` | **When the quiz was opened** — nothing more. See the warning below. |
| C | `QuestionResponse.filter(submission__student, submission__unit_id__in=open_pks, submission__status=IN_PROGRESS, last_attempt_at__isnull=False).order_by("-last_attempt_at", "-submission__unit_id").values_list("submission__unit_id", "last_attempt_at").first()` | Actual quiz answering. `last_attempt_at` is set explicitly on every attempt (`views.py:1654`). |

**Source C's projection is normative.** Unlike A/B/D, whose `unit_id` is a local column, C's unit
id lives on the joined `QuizSubmission`. The natural implementation — `.first()` then
`row.submission.unit_id` — triggers a **second** query for the related submission and silently
breaks the pinned warm-path count of four. Use the `values_list("submission__unit_id", …)`
projection above (or `select_related("submission")`); do not dereference the relation.

> **`QuizSubmission.updated` does NOT advance while a student answers.** It is `auto_now`
> (`models.py:3008`), so it only moves on `submission.save()` — and the answer path
> (`views.py:1614-1665`) saves the `QuestionResponse` and creates an `Attempt` but **never saves
> the submission**; `get_or_create`'s *get* branch does not save either. So for an `IN_PROGRESS`
> row, `updated == created` in practice. Source B alone would resume a student who spent an hour
> answering quiz Q to whatever lesson they opened afterwards. **Source C is what makes quiz
> recency real; B only catches "opened the quiz, answered nothing yet".** An implementer who drops
> C because "B already covers quizzes" reintroduces exactly this bug.

**Cross-source tie-break.** Assemble the candidates in the **normative order A, then B, then C**,
and select `winner = max(candidates, key=lambda c: (c.timestamp, c.source_rank))` with
`source_rank` **C=2 > B=1 > A=0**. `ts_f` then denotes **the winner's `timestamp`** — a plain
datetime — so step 3's `ts_f >= ts_d` is unambiguously a datetime-to-datetime comparison, never a
tuple against a datetime. There is exactly one candidate per source, so an equal timestamp always
meets distinct ranks and no third tuple component is ever consulted; the per-query `-unit_id` /
`-submission__unit_id` keys break ties *within* one source and do not participate here.

The assembly order is normative because it is what makes the `source_rank` mutant killable: with
the rank dropped, `max` over an untied key returns the **first** maximal element, so an A-then-C
order yields A while the correct build yields C. Assembling `[C, B, A]` would make the mutant
coincidentally return C and the test would be GREEN.

**Producing a genuine tie in a test needs `freeze_time`, not a transaction.** `updated_at`,
`updated`, `last_attempt_at` **and `completed_at`** are all stamped **Python-side** with
`timezone.now()` (`completed_at` in `UnitProgress.save()`, `models.py:2965-2966`) — `auto_now` does
not use Postgres's transaction-scoped `now()`. Two writes inside one `transaction.atomic()`
therefore differ by microseconds and produce **no tie at all**, so a tie-break test built that way
exercises nothing and passes on the mutant. Every test that depends on a tie — the cross-source
one, the within-source one, **and the `ts_f >= ts_d` boundary test** — must use
`freezegun.freeze_time` (already a dev dependency, `pyproject.toml:23`) or a queryset `.update()`
that bypasses `auto_now`, and must **assert the two timestamps are equal** before asserting the
winner.

### Completion anchor (source D)

`UnitProgress.filter(student, unit_id__in=leaf_pks, completed=True, completed_at__isnull=False)
.order_by("-completed_at", "-unit_id")`.

**`completed_at__isnull=False` is not noise.** Postgres sorts NULLs **first** under `DESC`, so
without the guard a `completed_at IS NULL` row would win the `LIMIT 1` and step 3's `ts_f >= ts_d`
would compare a datetime against `None` and raise `TypeError`. The same reasoning is why source C
carries `last_attempt_at__isnull=False`. Neither clause may be dropped as redundant.

**`completed_at`, never `updated_at`.** `completed_at` is stamped exactly once, in
`UnitProgress.save()`, when `completed` first flips, and is never re-stamped. `updated_at` is not
stable for a completed unit: `courses/views.py::seen` calls `progress.save()` **unconditionally**
on every batch the IntersectionObserver posts — including for an already-completed unit — so
simply re-reading a finished unit re-dates `updated_at` while `completed_at` stays put. Ordering
the anchor by `updated_at` would therefore rewind a student to just after whichever old unit they
last skimmed.

(Note: `courses/review.py::force_submit_quiz` is **not** a divergence source, despite the obvious
suspicion. Its write is guarded by `if not progress.completed`, so it can never re-date an
already-completed row, and on the one path where it does save, `save()` stamps `completed_at` in
the same instant — the two columns agree. Do not use force-submit to justify or test this choice.)

### Existence probe (source E, lazy)

Only evaluated when steps 3–4 both fail — i.e. the student has no visible in-flight work and no
visible completion. Two short-circuiting existence queries:

```
UnitProgress.filter(student=user, unit__course=course).exists()
  or QuizSubmission.filter(student=user, unit__course=course).exists()
```

These are deliberately **unfiltered** by `open`/`leaves` and by status — that is the whole point:
they detect history on units that are no longer visible, which is what separates step 5 from
step 6. Sources A–D cannot serve this role, because their `unit_id__in` restriction is exactly
what blinds them to such rows. These two are the only queries in the design that still join
`ContentNode`.

**The `or` short-circuits, so source E costs one probe or two.** A student whose surviving history
is a `UnitProgress` row pays **one** (cold path, `build_resume` only: 5). A student whose history is only a
`QuizSubmission` row, and a step-6 student with no rows at all, pay **two** (cold path, `build_resume` only: 6).
Any cold-path query-count assertion must therefore name its fixture rather than quoting a single
number.

### Which teacher writes can move the target, and which cannot

The earlier absolute claim ("teacher writes cannot move the target") was **false**. The accurate
statement is narrower:

- **Grading (`review.py::review_response`) cannot move it.** It saves the `QuizSubmission`,
  bumping `updated` — but only ever for a **SUBMITTED** submission, and B and C both filter to
  `status=IN_PROGRESS`. (The protection is that status filter, **not** `open_pks` membership: as
  the accepted limitation below records, a submitted quiz's unit *can* remain in `open_pks`.)
  Grading also writes `reviewed_at`, never `last_attempt_at`, so C's ordering is untouched.
- **Force-submit (`review.py::force_submit_quiz`) CAN move it, legitimately.** Its write is
  guarded by `if not progress.completed`, so it cannot re-date an already-completed row — but for
  a row that was *not* yet complete, `save()` stamps `completed_at = timezone.now()` at the
  **teacher's** clock. That unit then becomes source D's newest completion, and step 4 re-points
  the card at the first open unit after it. A teacher force-submitting an old forgotten quiz
  therefore rewinds the student's card.

  This is **accepted**: force-submit *is* a completion, and the anchor moving to the most recent
  completion is precisely the rule. Write-once `completed_at` protects the case that matters —
  a teacher touching an already-finished unit — which `updated_at` would not.

**`status=IN_PROGRESS` on B and C is load-bearing and IS tested.** The tempting argument against
testing it goes: both *production* submission-closing paths — `views.py` quiz submit
(`1689-1694`) and `review.py::force_submit_quiz` (`88-95`) — write `UnitProgress.completed = True`,
so a SUBMITTED quiz's unit is always `completed` in `build_outline` and therefore already excluded
by `unit_id__in=open_pks`, making the status filter unobservable.

**That argument is false, and the counterexample ships in this repo.**
`courses/management/commands/seed_demo_course.py` calls `finalize_submission(...)` at lines **346**
and **414** — which sets `status=SUBMITTED` and saves, bumping `updated` — and the file contains
**zero** references to `UnitProgress`. Every demo-seeded submitted quiz therefore has no progress
row at all, so its unit stays in `open_pks`, and dropping the status filter would make source B
return that submitted quiz as the freshest in-flight candidate. The mutant is killable with a
fixture shaped exactly like the repo's own seeder.

**Source A's `completed=False` is the opposite case: deliberate redundancy, NOT falsifiable.**
`open_pks` is derived from `build_outline`'s `completed` set, which is *exactly*
`UnitProgress.objects.filter(student=user, unit__course=course, completed=True)`
(`rollups.py:244-250`, consumed at the leaf key `"completed": is_unit and node.pk in completed`,
`:265`). Any row with `completed=True` has already had its unit removed from `open_pks`, so A's
filter can never change a result and **no mutant of it can go RED**. It stays because it states
the intent locally and costs nothing — but do **not** spend a falsification round on it, and do
not add a test row for it. (The contrast with B/C is the whole point: `open` is derived from
`UnitProgress.completed`, so it subsumes A's filter, while it knows nothing whatever about
`QuizSubmission.status`, so it does not subsume B/C's.)

D's `completed_at` ordering **is** load-bearing and **is** tested.

**Consequence for `open` (accepted, not fixed here).** `build_outline`'s `completed` flag derives
solely from `UnitProgress.completed=True` (`rollups.py:244-250`, leaf key at `:265`); it knows nothing about
`QuizSubmission.status`. So a SUBMITTED submission whose unit lacks a completed `UnitProgress` row
stays in `open` indefinitely, and step 4's `forward` (or `open[0]`) can point at a quiz the student
already submitted, under the eyebrow "Up next". The invariant this violates is *"a SUBMITTED
submission always has a completed `UnitProgress`"* — which every production path upholds and only
the demo seeder breaks. The right repair is in the seeder, not in this card, and is **out of scope**;
adding a fifth query to compensate for a fixture-only state is poor value. A test documents the
behaviour so it is a recorded choice rather than an accident.

## Architecture / components

Six change sites. No model, no migration, no new endpoint, no JavaScript.

### 1. `courses/rollups.py` — `build_resume(course, user, tree)`

Placed beside `build_unit_nav`, which consumes the same tree and the same private helpers.

```
def build_resume(course, user, tree):
    """{"node": ContentNode, "state": str, "ancestors": [ContentNode]} or None."""
```

- **`tree`** is the caller's already-built `build_outline(...)` tree — passed in, never rebuilt, so
  the card costs **zero additional tree queries**.
- **`node` is the `ContentNode`, i.e. `leaf["node"]` — never the leaf dict.**
  `_flatten_unit_leaves` returns build_outline *dicts*. Returning the dict **fails loudly** at
  `{% url 'courses:lesson_unit' … node_pk=resume.node.pk %}`: `pk` resolves to `""` against
  `courses/urls.py`'s `<int:node_pk>`, raising `NoReverseMatch` and 500-ing the outline. The quiet
  symptoms behind it — `unit_marker`'s `getattr(node, "kind", None)` failing quiet so no chip
  renders, and `resume.node.unit_type` resolving empty so every link takes the lesson branch —
  are what an implementer would chase first. The card needs nothing else from the dict.
- **Draft/unpublished units are already gone**: the view builds the tree with `drafts="hide"` for
  everyone except `can_see_drafts` holders, so the target can never be a unit the student cannot
  open. `can_see_drafts` is **deliberately not `is_staff`** — `courses/access.py` defines it as an
  alias of `can_manage_course` (course owner or a holder of `courses.change_course`) and documents
  that choice. Combined with the enrolled-only gate, a draft target requires an enrolled
  course-owner: rare, not impossible, and the same unit set their own outline already shows them.
- **Every ordering carries an explicit deterministic secondary key** — `-unit_id` for A/B/D,
  `-submission__unit_id` for C. These are not row pks: for A/B/D the `(student, unit)` unique
  constraint makes `unit_id` unique per student, so the row is pinned; for C it pins the
  **unit** even when two responses in one submission tie, which is all the algorithm needs.
- **Ancestors** reuse `_stamp_current_chain(tree, target_pk)` + `_current_ancestors(tree)` — pure
  dict traversal, **no queries**, the same mechanism the unit-page breadcrumbs use. Reusing them
  rather than adding a third ancestor walk is a deliberate anti-drift choice:
  `courses/views_manage.py::_unit_ancestors` is already a documented deliberate twin of
  `_current_ancestors`; a third copy would be one too many. `_current_ancestors` legitimately
  returns `[]` for a root-level unit.

### 2. `courses/views.py::course_outline`

**Two** edits, not one — the second is easy to omit and fails silently:

```
resume = build_resume(course, request.user, outline) if is_enrolled(request.user, course) else None
```

and the key must be added to the existing `render(...)` context dict:

```
"resume": resume,
```

Without the second, `{% if resume %}` reads a missing variable, which is falsy, and the card simply
never appears — no error, no failing template.

**Enrolled-only.** `can_access_course` also admits authors, teachers and staff previewing a course
they are not taking; a "Start the course" call to action would be noise for them. This matches the
existing precedent that the `seen` write route is enrolled-only by design.

**Call order.** `build_resume` runs after `tag_services.outline_with_tags(...)`. The target is
computed **independently of the active tag filter**: `outline_with_tags` annotates in place and
does not prune, and the filter is a browsing aid that hides rows rather than a scope restriction,
so filtering to one tag must not change where "Continue" sends you. The card may therefore point
at a unit whose row is currently hidden — correct, deliberate, and **tested**, because any future
change that prunes in `outline_with_tags` would break it silently.

### 3. `templates/courses/_resume_card.html` (new)

**Must begin** `{% load i18n %}{% get_current_language as LANGUAGE_CODE %}`, mirroring the
prologue of `_unit_crumbs.html` and `_unit_kind_chip.html`.
`django.template.context_processors.i18n` is **not** in `config/settings/base.py`'s
context-processor list, so without that tag `LANGUAGE_CODE` resolves to `string_if_invalid` (`""`)
and the eyebrow ships `lang=""` — valid HTML meaning "undetermined", so the failure is **silent**
and the page still renders. (`courses_extras` is deliberately **not** loaded: the card uses no
filter or tag from it — `unit_marker`/`marker_label` are consumed inside `_unit_kind_chip.html`,
which loads the library itself — and `strip_math_delimiters` has no site here. A future tooltip
would need both.)

**The class names below are normative**, because four sites must agree on them: the template, the
CSS, `tests/test_title_math_markers.py` (which asserts through CSS selectors such as
`_marked(body, "span.outline-unit__title")`), and the render tests.

| Element | Tag + class (both normative) |
|---|---|
| the wrapping `<a>` | `a.resume` |
| eyebrow | `span.resume__eyebrow` |
| ancestor path container | `span.resume__path` |
| one ancestor label | `span.resume__crumb` |
| unit title | `span.resume__title` |

A single `<a class="resume">` wraps the whole card so the entire block is one large hit target.
Contents:

- an **eyebrow**, one of four translated strings selected by `resume.state`:

  | `state` | string |
  |---|---|
  | `resume` | "Pick up where you left off" |
  | `next` | "Up next" |
  | `gap` | "Still to do" |
  | `start` | "Start the course" |

- the **ancestor path** (`resume.ancestors`), muted small text, `›`-joined, each label carrying
  `data-math-title`. **Omitted entirely when `ancestors` is empty** (a root-level unit in a flat
  course).
- the **unit title**, also `data-math-title`. No view change is needed: `has_math` is already
  `tree_titles_have_math(outline)` over the whole tree, and the target is by construction a node
  in that tree.
- `{% include "courses/_unit_kind_chip.html" with node=resume.node only %}` — this renders the same
  Quiz/Additional marker the outline rows use, and **renders nothing for an obligatory lesson**
  (`unit_marker` returns `MARKER_NONE`). Lesson-vs-quiz is conveyed by the presence of a "Quiz"
  chip, not by a chip always being present; no test should assert one always is.

**Titles appear only as element text, never in an attribute.** The card carries no `title=`
tooltip and no `aria-label` holding author content, so `strip_math_delimiters` has no site here —
unlike `_unit_crumbs.html`, which needs it for its per-`<li>` `title=`. `[data-math-title]` is the
only hook by which a node title gets typeset (it is one entry in `math.js`'s `renderInlineText`
selector list); attributes are never typeset at all. If a later revision adds a tooltip, it must
apply `|strip_math_delimiters` there.

`href` branches on `resume.node.unit_type`: `courses:quiz_unit` for a quiz, `courses:lesson_unit`
otherwise. The existing outline rows send everything through `lesson_unit` and rely on its
redirect (`views.py:798-799`); linking directly avoids a redirect hop on the page's most prominent
control.

**`lang`.** `outline.html` wraps everything in
`<section class="outline" lang="{{ course.language }}">`, so UI text would otherwise be announced
in the course language. Following `_unit_crumbs.html`'s documented split: the eyebrow (UI text)
takes `lang="{{ LANGUAGE_CODE }}"`; the unit title and ancestor labels (author content) keep the
course language.

**Accessibility.** The eyebrow is the link's leading text, so it reads as "Pick up where you left
off, <Chapter>, <Unit title>" rather than a bare title. `›` separators are `aria-hidden`,
following `_unit_crumbs.html`.

### 4. `templates/courses/outline.html`

Exactly one line, between `.outline__head` and `_tags_filter_bar.html`:

```
{% if resume %}{% include "courses/_resume_card.html" with resume=resume course=course only %}{% endif %}
```

`only` is load-bearing and so is passing `course` explicitly: the partial reverses both URL
branches with `slug=course.slug` and reads `course.language`, so `only` **without** `with
course=course` raises `NoReverseMatch` and 500s the outline. Omitting `only` would let the partial
silently inherit the whole context — the fragile convention `_outline_node.html`'s own comment
warns about. The partial may read `resume` and `course` and nothing else.

### 5. `core/static/core/css/app.css` — a `.resume` block

Placed in the existing "Course outline (syllabus)" section next to `.outline__head`. Token-driven
only: `--surface-raised` for the card ground, the border ramp cut against that raised surface
(never against base), existing `--space-*`/`--text-*` tokens. `.outline` is `max-width: 52rem` and
centred (`app.css:494`), so the card inherits the column width and needs none of its own.

**`.resume:hover` and `.resume:focus-visible` are required, not optional.** The whole card is one
`<a>`, and this repo puts an explicit focus ring on every interactive surface (`app.css:606`,
`1037`, `1069`, `1177`, `1270`, …); the outline rows also carry hover feedback. Cut the focus ring
against `--surface-raised`, matching the card ground rather than the page base. The light/dark
screenshots below do not capture focus state, so add a **keyboard-focus screenshot** as well.

### 6. `locale/**/django.po` + regenerated `.mo`

Four new strings (the eyebrows). See the i18n subsection under Testing.

## Data flow

```
GET /courses/<slug>/
  └─ course_outline
       ├─ build_outline(course, user, drafts=…)              2 queries  (existing)
       ├─ outline_with_tags(...)                                        (existing)
       ├─ is_enrolled(user, course)                          1 query    (NEW)
       └─ build_resume(course, user, outline)                4 queries  (NEW, warm path)
            ├─ _flatten_unit_leaves(tree)                    0 queries
            ├─ A  UnitProgress    unit_id__in=open,   completed=False  -updated_at
            ├─ B  QuizSubmission  unit_id__in=open,   IN_PROGRESS      -updated
            ├─ C  QuestionResponse submission__unit_id__in=open        -last_attempt_at
            ├─ D  UnitProgress    unit_id__in=leaves, completed=True   -completed_at
            ├─ E  existence probe  (LAZY — only when steps 3–4 both fail)  0–2 queries
            └─ _stamp_current_chain + _current_ancestors     0 queries
  └─ render outline.html
       └─ {% if resume %}{% include "courses/_resume_card.html" … only %}{% endif %}
```

**Net cost: five extra queries on the warm path** — four in `build_resume` plus the `is_enrolled`
gate, which runs on every outline render including for the enrolled majority. (This repo already
treats a redundant `is_enrolled` as a defect worth commenting on at `views.py:1344-1346`, the "Hoisted: is_enrolled was already called here" comment, so the
gate is counted here rather than hidden.) The **cold path** — a student with no visible in-flight
work and no visible completion — adds one or two more for source E, for **six or seven at view
level**.

**What is actually pinned by tests:** the `build_resume`-level counts **4** (warm), **5** and **6**
(cold), and a **same-user view-level delta of 4**. The view-level absolute totals (5 warm, 6-or-7
cold) are **not** pinned — no test asserts the `is_enrolled` query on its own except the
`CaptureQueriesContext` check described under Testing.

None of the three queried models declares `Meta.indexes`; the only declared constraints are
`UniqueConstraint(student, unit)` on `UnitProgress`/`QuizSubmission` and `(submission, element)` on
`QuestionResponse`. Django's default `db_index` on the FKs lets the `student_id`/`submission_id`
filter seek, but no **ordering** column is indexed, so each of A–D is a seek-then-sort with
`LIMIT 1` bounding the rows *returned*, not the rows *sorted*. The real bound is the student's row
count within one course — small, and unchanged by catalogue size. Adding a composite index is
explicitly **not** part of this change, which ships no migration.

Beyond the queries the card costs two linear passes over an already-materialised list of dicts.

### What bumps recency, and what does not

`progress_reset` ("Start fresh") writes with `rows.update(element_state={})`, and a queryset
`.update()` does **not** fire `auto_now`. So resetting practice state deliberately leaves
`updated_at`, `completed` and `completed_at` untouched, and the resume target does not move —
clearing your scratch work should not send you back to unit 1. Intended, and **tested**; the
coupling would break silently if that write ever became a `.save()`.

The comment above that call currently asserts *"nothing reads updated_at for practice state"* —
the `.update() deliberately bypasses save()` comment in `progress_reset` — which this feature
falsifies. **That comment must be corrected in this change**, kept line-count neutral so it does
not rot citations in surrounding untouched code. (Cited by anchor rather than line number for
exactly that reason.)

## Error handling

- **No visible leaves, or all completed** → step 1 returns `None`; the template renders nothing.
  No empty card, no placeholder.
- **A stored pk that is not a visible leaf** (unpublished or drafted — *not* deleted, whose rows
  cascade away; see step 5) →
  invisible to A–D by construction, because membership is a filter *inside* each query rather than
  a post-check on a `LIMIT 1` result. Older still-valid candidates are therefore never discarded.
  Such rows are detected only by source E, which is what makes step 5 reachable.
- **Not enrolled** → the view never calls `build_resume`; `resume` is `None`.
- **Anonymous user** → unreachable because `course_outline` is `@login_required`, and that is the
  **only** guard. `is_enrolled` would **raise**, not return False, on an `AnonymousUser`:
  `access.py:12-13` calls `Enrollment.objects.filter(student=user, …)`, and `Enrollment.student` is
  declared an FK to `AUTH_USER_MODEL` in `courses/models.py`. Do not treat
  `is_enrolled` as a second safety net, and do not remove the decorator.
- **Unstamped-tree contract.** `_current_ancestors` reads `contains_current` directly and raises
  `KeyError` on an unstamped tree by design. `build_resume` always calls `_stamp_current_chain`
  immediately before it, at the single call site.
- **Stamping is inert on this page.** `_stamp_current_chain` mutates the tree the template then
  renders, adding `contains_current` to every dict. That key is read only by
  `_unit_tree_node.html` (the unit-page rail); `_outline_node.html` never reads it.

## Testing

Every test is written failing-first, and each guard is falsified against a mutant chosen from its
own failure mode — a test that cannot go RED on the broken build does not ship.

### `tests/test_resume_target.py` — `build_resume` unit tests

| Test | Mutant it must catch |
|---|---|
| in-flight uncompleted unit, newer than any completion → `resume`, that unit | returning the *next* unit instead |
| **opened unit 3 once, then completed units 4–10** → `next`, unit 11 (**not** unit 3) | **dropping the `ts_f >= ts_d` comparison in step 3** — the stray-visit-pins-the-card bug |
| in-flight unit ties the completion timestamp exactly — **built with `freeze_time`, asserting `ts_f == ts_d` first** → `resume` (the `>=` arm) | flipping `>=` to `>`. Without a forced tie this row is vacuous: `ts_f > ts_d` passes on **both** builds, and `ts_f < ts_d` fails on the correct one. |
| most recent unit completed → `next`, the following uncompleted unit | returning the completed unit |
| no rows at all → `start`, first uncompleted leaf | returning `None` |
| all leaves completed → `None`; and, separately, no visible leaves at all → `None` | **deleting step 1**, whose symptom in *both* fixtures is the same `IndexError` on `open[0]` (with step 1 gone, `flight` is `None`, `done` is the last completed leaf, `forward` is `None`, and step 4 indexes an empty list). There is no "returns the last unit" code path to hunt for. |
| rows exist but none resolve to a visible leaf → `next` (**not** `start`) | collapsing step 5 into step 6 |
| **unit 30 unpublished, student actively mid-unit-5, and unit 30's `updated_at` strictly NEWER than unit 5's** → `resume`, unit 5 (**not** unit 1) | moving the membership test outside the query, so one invisible head row discards source A. The strictly-newer requirement is load-bearing: if unit 5's row sorts first the mutant never reaches unit 30's and stays GREEN. |
| finished the final unit, unit 3 still open → `gap`, unit 3 | dropping the wrap-around, returning `None` |
| **quiz answered but not submitted is the target** — a `QuestionResponse.last_attempt_at` newer than a later-opened lesson | **dropping source C**; source B alone passes a naive version of this test |
| quiz opened, nothing answered, most recent — **plus an older in-flight `UnitProgress` on a different open unit** → the quiz is the target AND `state == "resume"` | dropping source B. Without the rival the mutant falls through to step 5 and returns `open[0]`, which may be the same node; asserting the state as well as the node closes the remaining gap. |
| completed quiz counts as done — **fixture: the completed quiz is the LAST REMAINING unit**, correct build → `None` | treating `unit_type == quiz` as never-complete → mutant returns `gap` on the quiz. The obvious "quiz mid-course, assert we advance past it" fixture is **vacuous**: under that mutant the quiz re-enters `open` but A still excludes it (`completed=False`) and B/C still exclude it (SUBMITTED), so `flight` stays `None`, `done` is the quiz, and `forward` is the same unit the correct build returns. |
| **SUBMITTED `QuizSubmission` with NO `UnitProgress` row** (the `seed_demo_course.py` shape), **PLUS an in-flight lesson `UnitProgress` whose `updated_at` is strictly OLDER than the submission's `updated`, AND a `QuestionResponse` on that submission with `last_attempt_at` set and newer than the lesson's** → target is the **lesson**, state `resume` | dropping `status=IN_PROGRESS` from source **B** (quiz becomes freshest in-flight); and, separately, dropping `submission__status=IN_PROGRESS` from source **C**. Both mutants need the competing older lesson: without it the correct build reaches step 5 and returns `open[0]` — possibly the quiz itself — so "is not the target" would fail on a correct build. The `QuestionResponse` is what makes C's filter killable at all. |
| the same seeder-shaped submitted quiz **can** surface as a `next` target — documenting the accepted `open`-derivation limitation | silently "fixing" it with an extra query, which this design rejects as out of scope |
| **complete unit 3, complete unit 5, then `seen` unit 3 again** → `next`, unit 6 | **ordering source D by `updated_at` instead of `completed_at`** → mutant returns unit 4. (This is the *only* scenario that separates the two columns; a force-submit scenario cannot — see the note under "Completion anchor".) |
| all *required* lessons done, one additional lesson open → card still points at the additional lesson | filtering `open` to obligatory lessons |
| **units 1–5 completed (anchor = 5, target = 6, `next`) PLUS a stale uncompleted `UnitProgress` row on a later unit whose `updated_at` is STRICTLY OLDER than unit 5's `completed_at`**; `progress_reset` the course → target stays unit 6. Backdating needs `freeze_time` or a queryset `.update(updated_at=…)` — a plain `save()` cannot do it, and creating the row last (the natural fixture order) makes it the *newest*, so the correct build already answers `resume` on it and the test fails before the mutant is applied | making the reset write through `save()` → the mutant re-dates the stale row, flipping the answer to that unit with state `resume`. The naive one-in-flight-unit fixture is **vacuous**: the mutant re-dates the row that was already the target. |
| exact cross-source tie between A and C, **built with `freeze_time`** and asserted equal before the act → C wins | dropping the `source_rank` tie-break |
| within-source tie between two A rows, **built with `freeze_time`**, inserting the **lower** `unit_id` first | dropping the `-unit_id` key → Postgres's unspecified order among equal sort keys follows scan order in practice, so the mutant returns the first-inserted row; inserting the lower id first guarantees it differs from the correct highest-`unit_id` answer. Inserting the higher first would make the mutant coincidentally right. |
| `ancestors` is the root→parent chain, unit excluded | off-by-one including the unit itself |
| root-level unit in a flat course → `ancestors == []`, no crash | assuming a non-empty chain |
| returned `node` is a `ContentNode`, not a leaf dict | returning `leaf` instead of `leaf["node"]` |
| exactly **4** queries for a direct warm-path `build_resume(...)` call. **Fixture: the student must have BOTH a live `UnitProgress` row AND an `IN_PROGRESS` `QuizSubmission` on an open quiz unit carrying a `QuestionResponse` with `last_attempt_at` set** — so source C actually returns a row | **making source E eager** (→ 5 or 6); **dereferencing `row.submission` in source C** instead of the `values_list` projection; rebuilding the tree; an N+1 over leaves. The lone-`UnitProgress` fixture is **vacuous for the source-C mutant**: C's `.first()` returns `None`, so nothing is dereferenced and the count stays 4. |
| cold path, **fixture: no rows at all** (both E probes run) → exactly **6** | dropping the `QuizSubmission` arm of source E (→ 5). (A `Q(...) \| Q(...)` collapse is **not** a constructible mutant — the two probes hit two different models — so do not attempt to falsify against it.) |
| cold path, **fixture: history only on a since-unpublished unit's `UnitProgress`** (E short-circuits after one probe) → exactly **5** | making the `or` eager rather than short-circuiting |

### Render tests — `tests/test_courses_views.py` (outline render/permission home)

- the card links to `courses:quiz_unit` for a quiz target and `courses:lesson_unit` for a lesson —
  mutant: pointing both at `lesson_unit`;
- each of the four `state` values renders its own eyebrow string — mutant: collapsing them to one;
- a **non-enrolled** viewer with `can_access_course` (author/staff) gets **no** card;
- loading the outline with `?tags=<id>` that excludes the target still points at the target —
  mutant: filtering `leaves` on `tag_hidden`;
- the **`.resume__eyebrow` element** carries `lang="pl"` — read off that selector, never off the
  page, because `outline.html` already emits `lang="{{ course.language }}"` on
  `<section class="outline">` and a document-wide search for `lang="pl"` would pass for the wrong
  reason. Mutant: dropping `{% get_current_language as LANGUAGE_CODE %}`, which yields `lang=""` —
  a presence-only assertion would be GREEN on it.

  **Set the language the repo's way, NOT with `translation.override`.**
  `core/middleware.py::SessionLocaleMiddleware.process_request` calls `translation.activate(...)`
  on **every** request (session key, else `LocaleMiddleware`'s resolution), discarding any outer
  override — so with `LANGUAGE_CODE = "en"` an `override("pl")` test would render `lang="en"` and
  go **RED on a correct build**. Use the established pattern: `session["_language"] = "pl";
  session.save()` plus `HTTP_ACCEPT_LANGUAGE="pl"`. Precedents: `tests/test_i18n_catalog.py:11-13`,
  `tests/test_editor_count_i18n.py:31-33`, `tests/test_builder_lazy_scopes.py:658-660`;
**There is deliberately NO view-level query-count test.** This is a recorded decision, not an
omission. Three successive attempts to specify one each failed on a different hazard, and the
residual value was nil:

1. An **absolute** `django_assert_num_queries(N)` cannot demonstrate a *delta* — the baseline
   (notes counts, tags, branding/context processors) is fixture-dependent.
2. A **two-user A/B** does not cancel: `can_see_drafts`/`can_manage_course` short-circuits on
   ownership, `accessible_courses` takes the `is_staff` branch for staff,
   `core/help.py::user_has_any_help` varies by permission set, and `drafts` flips `keep`/`hide`.
3. A **same-user A/B** (own + enrol, request, delete the `Enrollment`, request again) cancels the
   user differences but still breaks two ways: `tests/conftest.py`'s autouse `_clear_site_cache`
   calls `cache.clear()` around every test, and `institution_branding`/`ui_prefs` both call
   `core/services.py::get_site_config()` — so **arm 1 pays the cache-warm queries and arm 2 does
   not**, and the measured delta exceeds four on a *correct* build.

And even a working version could only ever see code in the **enrolled-only branch**, since a delta
cancels everything common to both arms — which is exactly what the `build_resume`-level counts
(4 / 5 / 6) already pin. The one thing it might have added, *wiring* (calling `build_resume`
unconditionally instead of behind the gate), is pinned more robustly and more legibly by the
"non-enrolled viewer gets **no** card" render test above.

A related trap, recorded so nobody re-derives it: asserting "the non-enrolled arm issues exactly
one query against the `Enrollment` table" is **false**. `course_outline` calls `can_access_course`
→ `accessible_courses`, which for a non-staff user compiles
`Q(pk__in=Enrollment.objects.filter(student=user).values("course_id")) | …` — Django inlines that
as `IN (SELECT … FROM "courses_enrollment" …)`, so a table-name match over `captured_queries`
counts **two**, not one.

### Inert-stamping guard — `tests/test_resume_target.py`

Executable A/B rather than a vague "renders identically": build one tree, render it, call
`_stamp_current_chain(tree, pk)`, render again, assert the two strings are **byte-identical**.
The in-product arms are not comparable — `build_resume` always stamps when it returns a target —
so the A/B must be constructed directly.

**Mutant:** adding a `{% if item.contains_current %} open{% endif %}` read to
`_outline_node.html` (i.e. the outline starting to depend on the key the card's stamping writes).

**The tree shape is load-bearing for that mutant.** ` open` belongs to the container arm, which
renders only for a non-unit node **with children** (`{% if item.children %}`). So the stamped pk
must be a unit nested under **at least one container that survives pruning** — stamp a root-level
unit and no dict with `contains_current == True` ever reaches that branch, the two renders are
byte-identical on both builds, and the test is GREEN on the mutant.

**Setup the test must supply**, because a `build_outline` tree is a *list* of roots and the
partial is per-node: loop the roots and `render_to_string("courses/_outline_node.html", ...)` for
each, with the context keys `_outline_node.html` actually reads — `item`, `course`, `note_counts`,
and `active_tag_ids` — concatenating the results for comparison.

### `tests/test_title_math_markers.py`

Extend the outline section so the card's unit title (`span.resume__title`) **and** each ancestor
label (`span.resume__crumb`) are covered by the existing marker-coverage suite, asserted through
its `_marked(body, <selector>)` helper — mutant: dropping `data-math-title` from the ancestor
labels.

### Manual verification

Screenshots of the outline page in **light and dark**, judged separately, at desktop width and at
**640px**. 640 is the only outline-scoped `max-width: 640px` block (`app.css:688-690`, which drops
`.outline__results`' `margin-left: auto`); `.outline__head` itself wraps continuously via
`flex-wrap: wrap` rather than reflowing at a breakpoint. (832px is the `.unit-crumbs` breakpoint in
`courses.css` and is **not** relevant here.)

### i18n

**Four** new translatable strings. `makemessages`, Polish translations filled in, `.mo`
regenerated, and the branch rebased before the PR so the binary `.mo` does not conflict.

### Definition of done

`ruff check --no-cache` and `ruff format --check` clean; `manage.py makemigrations --check` clean
(this change must add none); `manage.py check` clean; the courses non-e2e suite green.
