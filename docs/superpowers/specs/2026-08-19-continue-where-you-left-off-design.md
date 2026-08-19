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
resume rule**: the unit you were most recently working in if you had not finished it, otherwise
the next unfinished unit after the one you most recently completed.

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

5. if `flight` exists (i.e. it lost the ts comparison but `done` was invisible — unreachable
   in practice, kept so the branch is total)
                                               -> return flight,   state = "resume"

6. if the student has ANY progress row in this course (source E)
                                               -> return open[0],  state = "next"

7. otherwise (no rows at all)                  -> return open[0],  state = "start"
```

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

**Step 6 exists so `start` never lies.** A student who completed units 1–29 and whose
most-recent unit 30 has since been unpublished has plenty of history; "Start the course" would be
false. `start` fires only when the student genuinely has no progress rows in this course.

**Optional lessons and quizzes count as targets.** `build_outline` distinguishes `required_total`
(obligatory **lesson** units only — `rollups.py::is_obligatory_lesson`) from additional lessons
and quizzes, and the outline surfaces that as `N/M required` plus `+K additional`. This rule
deliberately does **not** inherit that distinction: `open` is every uncompleted visible unit. The
outline lists additional lessons as real, openable content, and a card that skipped them would
leave a student who wants them with no affordance. The consequence — a student who has finished
all *required* work still sees a card pointing at an additional lesson — is intended and tested.

## Recency sources

"Most recent activity" needs several queries, because **no single timestamp in the schema means
"the student was last working here"**. Each source below earns its place; each is filtered so that
**teacher-driven writes cannot move a student's resume target**.

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
| C | `QuestionResponse.filter(submission__student, submission__unit_id__in=open_pks, submission__status=IN_PROGRESS, last_attempt_at__isnull=False).order_by("-last_attempt_at", "-submission__unit_id")` | Actual quiz answering. `last_attempt_at` is set explicitly on every attempt (`views.py:1654`). |

> **`QuizSubmission.updated` does NOT advance while a student answers.** It is `auto_now`
> (`models.py:3008`), so it only moves on `submission.save()` — and the answer path
> (`views.py:1614-1665`) saves the `QuestionResponse` and creates an `Attempt` but **never saves
> the submission**; `get_or_create`'s *get* branch does not save either. So for an `IN_PROGRESS`
> row, `updated == created` in practice. Source B alone would resume a student who spent an hour
> answering quiz Q to whatever lesson they opened afterwards. **Source C is what makes quiz
> recency real; B only catches "opened the quiz, answered nothing yet".** An implementer who drops
> C because "B already covers quizzes" reintroduces exactly this bug.

**Cross-source tie-break.** `ts_f` is the maximum over A/B/C of the tuple
`(timestamp, source_rank, unit_id)` with `source_rank` **C=2 > B=1 > A=0**. The per-query
`-unit_id` keys only break ties *within* one source; fixtures that write in one transaction (or
freeze time) routinely produce exact cross-source ties, which is the same flakiness those keys
exist to prevent. Ranking C above B above A prefers the most specific evidence of real work.

### Completion anchor (source D)

`UnitProgress.filter(student, unit_id__in=leaf_pks, completed=True, completed_at__isnull=False)
.order_by("-completed_at", "-unit_id")`.

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

Only evaluated when steps 3–5 all fail — i.e. the student has no visible in-flight work and no
visible completion. Two short-circuiting existence queries:

```
UnitProgress.filter(student=user, unit__course=course).exists()
  or QuizSubmission.filter(student=user, unit__course=course).exists()
```

These are deliberately **unfiltered** by `open`/`leaves` and by status — that is the whole point:
they detect history on units that are no longer visible, which is what separates step 6 from
step 7. Sources A–D cannot serve this role, because their `unit_id__in` restriction is exactly
what blinds them to such rows. These two are the only queries in the design that still join
`ContentNode`.

### Why teacher writes cannot move the target

- Grading (`review.py::review_response`) saves the `QuizSubmission` — but only for a **submitted**
  quiz, and B and C both filter to `status=IN_PROGRESS`.
- Force-submit (`review.py::force_submit_quiz`) sets `completed=True` and saves `UnitProgress` —
  A filters to `completed=False`, and D orders by the write-once `completed_at`.

This is a **decision**, not an accident, and it is tested.

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

```
resume = build_resume(course, request.user, outline) if is_enrolled(request.user, course) else None
```

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

**Must begin** `{% load i18n courses_extras %}{% get_current_language as LANGUAGE_CODE %}`, exactly
as `_unit_crumbs.html` and `_unit_kind_chip.html` do. `django.template.context_processors.i18n` is
**not** in `config/settings/base.py`'s context-processor list, so without that tag `LANGUAGE_CODE`
resolves to `string_if_invalid` (`""`) and the eyebrow ships `lang=""` — valid HTML meaning
"undetermined", so the failure is **silent** and the page still renders.

A single `<a>` wraps the whole card so the entire block is one large hit target. Contents:

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
            ├─ E  existence probe  (LAZY — only when steps 3–5 all fail)  0–2 queries
            └─ _stamp_current_chain + _current_ancestors     0 queries
  └─ render outline.html
       └─ {% if resume %}{% include "courses/_resume_card.html" … only %}{% endif %}
```

**Net cost: five extra queries on the warm path** — four in `build_resume` plus the `is_enrolled`
gate, which runs on every outline render including for the enrolled majority. (This repo already
treats a redundant `is_enrolled` as a defect worth commenting on at `views.py:1343-1346`, so the
gate is counted here rather than hidden.) The **cold path** — a student with no visible in-flight
work and no visible completion — adds one or two more for source E, for six or seven. Both counts
are pinned by tests.

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
- **A stored pk that is not a visible leaf** (deleted, unpublished, moved out of the course) →
  invisible to A–D by construction, because membership is a filter *inside* each query rather than
  a post-check on a `LIMIT 1` result. Older still-valid candidates are therefore never discarded.
  Such rows are detected only by source E, which is what makes step 6 reachable.
- **Not enrolled** → the view never calls `build_resume`; `resume` is `None`.
- **Anonymous user** → unreachable: `course_outline` is `@login_required`, and `is_enrolled` is
  false for anonymous users regardless.
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
| in-flight unit ties the completion timestamp exactly → `resume` (the `>=` arm) | flipping `>=` to `>` |
| most recent unit completed → `next`, the following uncompleted unit | returning the completed unit |
| no rows at all → `start`, first uncompleted leaf | returning `None` |
| all leaves completed → `None` | returning the last unit |
| no visible leaves at all → `None` | `IndexError` on `open[0]` |
| rows exist but none resolve to a visible leaf → `next` (**not** `start`) | collapsing step 6 into step 7 |
| **unit 30 unpublished, student actively mid-unit-5** → `resume`, unit 5 (**not** unit 1) | moving the membership test outside the query, so one invisible head row discards source A |
| finished the final unit, unit 3 still open → `gap`, unit 3 | dropping the wrap-around, returning `None` |
| **quiz answered but not submitted is the target** — a `QuestionResponse.last_attempt_at` newer than a later-opened lesson | **dropping source C**; source B alone passes a naive version of this test |
| quiz opened, nothing answered, most recent → still the target | dropping source B |
| completed quiz counts as done and is advanced past | treating `unit_type == quiz` as never-complete |
| **complete unit 3, complete unit 5, then `seen` unit 3 again** → `next`, unit 6 | **ordering source D by `updated_at` instead of `completed_at`** → mutant returns unit 4. (This is the *only* scenario that separates the two columns; a force-submit scenario cannot — see the note under "Completion anchor".) |
| teacher grades a submitted quiz → target unmoved, and the scenario reaches step 3 with a live `flight` candidate so the mutant is killable | dropping the `status=IN_PROGRESS` filter on B/C |
| all *required* lessons done, one additional lesson open → card still points at the additional lesson | filtering `open` to obligatory lessons |
| `progress_reset` for the course leaves the target unmoved | making the reset write through `save()` |
| exact cross-source tie between A and C → C wins deterministically | dropping the `source_rank` tie-break |
| two rows written in one transaction → deterministic target | dropping the `-unit_id`/`-submission__unit_id` keys |
| `ancestors` is the root→parent chain, unit excluded | off-by-one including the unit itself |
| root-level unit in a flat course → `ancestors == []`, no crash | assuming a non-empty chain |
| returned `node` is a `ContentNode`, not a leaf dict | returning `leaf` instead of `leaf["node"]` |
| exactly **4** queries for a direct warm-path `build_resume(...)` call | rebuilding the tree, or an N+1 over leaves |
| exactly **6** queries on the cold path (steps 3–5 fail, source E fires) | making source E eager instead of lazy |

### Render tests — `tests/test_courses_views.py` (outline render/permission home)

- the card links to `courses:quiz_unit` for a quiz target and `courses:lesson_unit` for a lesson —
  mutant: pointing both at `lesson_unit`;
- each of the four `state` values renders its own eyebrow string — mutant: collapsing them to one;
- a **non-enrolled** viewer with `can_access_course` (author/staff) gets **no** card;
- loading the outline with `?tags=<id>` that excludes the target still points at the target —
  mutant: filtering `leaves` on `tag_hidden`;
- under `translation.override("pl")` the eyebrow carries the **actual active code**
  (`lang="pl"`), not merely some `lang` attribute — mutant: dropping
  `{% get_current_language as LANGUAGE_CODE %}`, which yields `lang=""` and would pass a
  presence-only assertion;
- `django_assert_num_queries` on `course_outline` pinning the **total** view query count, so the
  promised delta of five is guarded against a future double `is_enrolled` call or an in-view tree
  rebuild — neither of which the `build_resume`-level count can see.

### Inert-stamping guard — `tests/test_resume_target.py`

Executable A/B rather than a vague "renders identically": build one tree, `render_to_string` the
outline node partial over it, call `_stamp_current_chain(tree, pk)`, render again, and assert the
two strings are **byte-identical**. (The in-product arms are not comparable — `build_resume`
always stamps when it returns a target — so the A/B must be constructed directly.)

### `tests/test_title_math_markers.py`

Extend the outline section so the card's unit title **and** each ancestor label are covered by the
existing marker-coverage suite — mutant: dropping `data-math-title` from the ancestor labels.

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
