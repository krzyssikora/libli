# Continue where you left off

A resume affordance at the top of the student course-outline page, so a returning student
re-enters the course at the unit they should work on next instead of hunting for it in the tree.

## Purpose

Today `templates/courses/outline.html` opens with a title, three utility links ("My results",
"My notes", "Start fresh") and a JS-revealed "Expand all" toggle button, then the full outline
tree. There is no course-level progress summary and **no resume affordance anywhere in the
product** — a student returning to a 60-unit course must remember where they were and scroll to
find it.

This adds one card at the top of that page pointing at a single unit, chosen by a
**hybrid resume rule**: the unit you were last working in if you had not finished it, otherwise
the next unfinished unit after the one you most recently completed.

Out of scope (deliberately): the dashboard (`core/views.py::home`), the "My courses" list, the
catalog, any change to how progress is recorded, and any new model or migration.

## Definition of the target

Stated as an **ordered algorithm with a single terminal `None`**, not a table of independent
rows — the branches overlap and their precedence is load-bearing.

Let `leaves` be the visible unit-leaf dicts of the course in outline order, and `open` be the
subset of `leaves` whose `completed` is false.

```
1. if `open` is empty                      -> return None
     (covers both "course has no visible units" and "student has completed everything")
2. `flight` = the most recent IN-FLIGHT unit that is present in `open`   (see "Recency sources")
     if `flight` exists                    -> return it,               state = "resume"
3. `done`   = the most recently COMPLETED unit that is present in `leaves`
     if `done` exists:
         forward = the first member of `open` positioned after `done`
         if forward exists                 -> return forward,          state = "next"
         else                              -> return open[0],          state = "gap"
4. if the student has ANY progress row in this course (even one that resolved
   to no visible leaf — a deleted or unpublished unit)
                                           -> return open[0],          state = "next"
5. otherwise (no rows at all)              -> return open[0],          state = "start"
```

Every branch that returns a unit returns a member of `open`, so the card can never point at a
unit the student has already finished. Step 1 runs first, so no later step can index an empty
candidate set.

**Step 3's `gap` branch** is the wrap-around: a student who finished the final unit but skipped
unit 3 still has work, and a card that silently vanishes while unfinished units remain is worse
than one that points back at the earliest gap. It gets its **own** state because "Up next" is a
false statement about a unit *earlier* in the course.

**Step 4 exists so `start` never lies.** A student who has completed units 1–29 and whose
most-recent unit 30 has since been unpublished has plenty of history; telling them to "Start the
course" would be false. `start` fires only when the student genuinely has no progress rows in
this course.

**Optional lessons and quizzes count as targets.** `build_outline` distinguishes `required_total`
(obligatory **lesson** units only — `rollups.py::is_obligatory_lesson`) from additional lessons
and quizzes, and the outline surfaces that as `N/M required` plus `+K additional`. This rule
deliberately does **not** inherit that distinction: `open` is every uncompleted visible unit. The
outline lists additional lessons as real, openable content, and a resume card that skips them
would leave a student who wants them with no affordance at all. The consequence — a student who
has finished all *required* work still sees a card pointing at an additional lesson until they
either complete or the course runs out — is intended, and is covered by its own test.

## Recency sources

"Most recent activity" needs four queries, not one, because **no single timestamp in the schema
means "the student was last working here"**. Each source below earns its place; each is filtered
so that **teacher-driven writes cannot move a student's resume target**.

### In-flight (step 2) — the later of these three

| # | Query | What it actually measures |
|---|---|---|
| A | `UnitProgress.filter(student, unit__course, completed=False).order_by("-updated_at", "-unit_id")` | Lesson work. `updated_at` is `auto_now`, advanced by the `get_or_create` on first open (`views.py:511`), by every `seen` batch the IntersectionObserver posts, and by every practice-state write. |
| B | `QuizSubmission.filter(student, unit__course, status=IN_PROGRESS).order_by("-updated", "-unit_id")` | **When the quiz was opened** — nothing more. See the warning below. |
| C | `QuestionResponse.filter(submission__student, submission__unit__course, submission__status=IN_PROGRESS, last_attempt_at__isnull=False).order_by("-last_attempt_at", "-submission__unit_id")` | Actual quiz answering. `last_attempt_at` is set explicitly on every attempt (`views.py:1654`). |

> **`QuizSubmission.updated` does NOT advance while a student answers.** It is `auto_now`
> (`models.py:3008`), so it only moves on `submission.save()` — and the answer path
> (`views.py:1614-1665`) saves the `QuestionResponse` and creates an `Attempt`, but **never saves
> the submission**; `get_or_create`'s *get* branch does not save either. So for an `IN_PROGRESS`
> row, `updated == created` in practice. Source B alone would resume a student who spent an hour
> answering quiz Q to whatever lesson they opened afterwards. **Source C is what makes quiz
> recency real; source B only catches "opened the quiz, answered nothing yet".** An implementer
> who drops C because "B already covers quizzes" reintroduces exactly this bug.

### Completion anchor (step 3)

`UnitProgress.filter(student, unit__course, completed=True, completed_at__isnull=False)
.order_by("-completed_at", "-unit_id")`.

**`completed_at`, never `updated_at`.** `completed_at` is stamped exactly once, in
`UnitProgress.save()`, at the moment `completed` first flips, and is never re-stamped. `updated_at`
is not stable: `courses/review.py::force_submit_quiz` does `get_or_create` + `progress.save()` on
the **student's** row, so a teacher closing a quiz would otherwise re-date it and jump the student
forward past every unit between. The `completed_at__isnull=False` guard is defensive — `save()`
enforces the invariant, but a future `.update()` write path could bypass it, and ordering by a
NULL column would put such a row first.

### Why teacher writes cannot move the target

- Grading (`review.py::review_response`) saves the `QuizSubmission` — but only for a **submitted**
  quiz, and sources B and C both filter to `status=IN_PROGRESS`.
- Force-submit (`review.py::force_submit_quiz`) sets `completed=True` and saves `UnitProgress` —
  source A filters to `completed=False`, and the completion anchor orders by the write-once
  `completed_at`.

This is a **decision**, not an accident, and it gets a test.

## Architecture / components

Six change sites. No model, no migration, no new endpoint, no JavaScript.

1. `courses/rollups.py` — new `build_resume`
2. `courses/views.py::course_outline` — one call, one context key
3. `templates/courses/_resume_card.html` — new
4. `templates/courses/outline.html` — the `{% include %}`
5. `core/static/core/css/app.css` — a `.resume` block
6. `locale/**/django.po` + regenerated `.mo` — four new strings

### 1. `courses/rollups.py` — `build_resume(course, user, tree)`

Placed beside `build_unit_nav`, which consumes the same tree and the same private helpers.

```
def build_resume(course, user, tree):
    """{"node": ContentNode, "state": str, "ancestors": [ContentNode]} or None."""
```

- **`tree`** is the caller's already-built `build_outline(...)` tree — passed in, never rebuilt, so
  the card costs **zero additional tree queries**.
- **`node` is the `ContentNode`, i.e. `leaf["node"]` — never the leaf dict.**
  `_flatten_unit_leaves` returns build_outline *dicts*, and the template does
  `resume.node.unit_type` and `{% include ... with node=resume.node only %}`. Returning the dict
  fails **silently in two places**: `unit_marker`'s `getattr(node, "kind", None)` check fails
  quiet and renders no chip, and `resume.node.unit_type` resolves to empty so every link goes to
  `lesson_unit`. The card needs nothing else from the dict.
- **Draft/unpublished units are already gone**: the view builds the tree with `drafts="hide"` for
  everyone except `can_see_drafts` holders, so the target can never be a unit the student cannot
  open. Note `can_see_drafts` is **deliberately not `is_staff`** — `courses/access.py` defines it
  as an alias of `can_manage_course` (course owner or a holder of `courses.change_course`) and
  documents that choice explicitly. Combined with the enrolled-only gate below, a draft target
  requires an enrolled course-owner, which is rare but not impossible; it is the same unit set
  their own outline already shows them, so no new visibility rule is introduced.
- **Every ordering carries an explicit `-<pk>` tiebreak.** `auto_now` timestamps written in the
  same transaction — routine in test fixtures — otherwise leave `.first()` returning an arbitrary
  row, making tests flaky rather than deterministic.
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
change that prunes in `outline_with_tags` would break it silently (the card would still render,
just pointing elsewhere).

### 3. `templates/courses/_resume_card.html` (new)

Included from `outline.html` between `.outline__head` and `_tags_filter_bar.html`, guarded by
`{% if resume %}`.

A single `<a>` wraps the whole card so the entire block is one large hit target. Contents:

- an **eyebrow**, one of four translated strings selected by `resume.state`:

  | `state` | string |
  |---|---|
  | `resume` | "Pick up where you left off" |
  | `next` | "Up next" |
  | `gap` | "Still to do" |
  | `start` | "Start the course" |

- the **ancestor path** (`resume.ancestors`), muted small text, `›`-joined. **Omitted entirely
  when `ancestors` is empty** (a root-level unit in a flat course). Each label carries
  `data-math-title`, and `strip_math_delimiters` is applied anywhere a title lands in an
  attribute — `math.js` typesets `[data-math-title]` and nothing else, so an ancestor titled
  `Rozwiąż \(x^2\)` would otherwise render its delimiters literally. This follows
  `_unit_crumbs.html`, which marks every ancestor label the same way.
- the **unit title**, also `data-math-title`. No view change is needed: `has_math` is already
  `tree_titles_have_math(outline)` over the whole tree, and the target is by construction a node
  in that tree.
- `{% include "courses/_unit_kind_chip.html" with node=resume.node only %}` — this renders the
  same Quiz/Additional marker the outline rows use, and **renders nothing for an obligatory
  lesson** (`unit_marker` returns `MARKER_NONE`). Lesson-vs-quiz is conveyed by the presence of a
  "Quiz" chip, not by a chip always being present; no test should assert one always is.

`href` branches on `resume.node.unit_type`: `courses:quiz_unit` for a quiz, `courses:lesson_unit`
otherwise. The existing outline rows send everything through `lesson_unit` and rely on its
redirect (`views.py:798-799`); linking directly avoids a redirect hop on the page's most
prominent control.

**`lang`.** `outline.html` wraps everything in `<section class="outline" lang="{{ course.language }}">`,
so UI text would otherwise be announced in the course language. Following `_unit_crumbs.html`'s
documented split: the eyebrow (UI text) takes `lang="{{ LANGUAGE_CODE }}"`; the unit title and
ancestor labels (author content) keep the course language.

**Accessibility.** The eyebrow is the link's leading text, so it reads as "Pick up where you left
off, <Chapter>, <Unit title>" rather than a bare title. `›` separators are `aria-hidden`,
following `_unit_crumbs.html`.

### 5. `core/static/core/css/app.css` — a `.resume` block

Placed in the existing "Course outline (syllabus)" section next to `.outline__head`. Token-driven
only: `--surface-raised` for the card ground, the border ramp cut against that raised surface
(never against base), existing `--space-*`/`--text-*` tokens. `.outline` is `max-width: 52rem` and
centred (`app.css:494`), so the card inherits the column width and needs none of its own.

## Data flow

```
GET /courses/<slug>/
  └─ course_outline
       ├─ build_outline(course, user, drafts=…)              2 queries  (existing)
       ├─ outline_with_tags(...)                                        (existing)
       ├─ is_enrolled(user, course)                          1 query    (NEW)
       └─ build_resume(course, user, outline)                4 queries  (NEW)
            ├─ _flatten_unit_leaves(tree)                    0 queries
            ├─ A  UnitProgress   completed=False   -updated_at
            ├─ B  QuizSubmission IN_PROGRESS       -updated
            ├─ C  QuestionResponse IN_PROGRESS     -last_attempt_at
            ├─ D  UnitProgress   completed=True    -completed_at
            └─ _stamp_current_chain + _current_ancestors     0 queries
  └─ render outline.html
       └─ _resume_card.html   (guarded by {% if resume %})
```

**Net cost: five extra queries** — four in `build_resume` plus the `is_enrolled` gate, which runs
on every outline render including for the enrolled majority. (This repo already treats a redundant
`is_enrolled` as a defect worth commenting on at `views.py:1343-1346`, so the gate is counted here
rather than hidden.)

Each of A–D is a filter + sort + `LIMIT 1`. **They are not index seeks**: neither model declares
`Meta.indexes`, only a `UniqueConstraint` on `(student, unit)`, so no ordering column is indexed
and `LIMIT 1` bounds the rows *returned*, not the rows *sorted*. The real bound is the student's
row count within one course — small, and unchanged by course catalogue size. Adding a composite
index is explicitly **not** part of this change, which ships no migration.

Beyond the queries the card costs two linear passes over an already-materialised list of dicts.

### What bumps recency, and what does not

`progress_reset` ("Start fresh") writes with `rows.update(element_state={})`, and a queryset
`.update()` does **not** fire `auto_now`. So resetting practice state deliberately leaves
`updated_at`, `completed` and `completed_at` untouched, and the resume target does not move —
clearing your scratch work should not send you back to unit 1. This is intended behaviour and
**is tested**; the coupling would break silently if that write ever became a `.save()`.

The comment above that call currently asserts *"nothing reads updated_at for practice state"*
(`courses/views.py:762-763`), which this feature falsifies. **That comment must be corrected in
this change**, and the correction kept line-count neutral so it does not rot citations in
surrounding untouched code.

## Error handling

- **No visible leaves, or all completed** → step 1 returns `None`; the template renders nothing.
  No empty card, no placeholder.
- **A stored pk that is not a visible leaf** (deleted, unpublished, moved out of the course) →
  the source is skipped at its step; step 4 still yields a `next` card. Membership is tested
  against the in-memory leaf list, so a dangling pk is structurally impossible to dereference and
  costs no query.
- **Not enrolled** → the view never calls `build_resume`; `resume` is `None`.
- **Anonymous user** → unreachable: `course_outline` is `@login_required`, and `is_enrolled` is
  false for anonymous users regardless.
- **Unstamped-tree contract.** `_current_ancestors` reads `contains_current` directly and raises
  `KeyError` on an unstamped tree by design. `build_resume` always calls `_stamp_current_chain`
  immediately before it, at the single call site.
- **Stamping is inert on this page.** `_stamp_current_chain` mutates the tree the template then
  renders, adding `contains_current` to every dict. That key is read only by
  `_unit_tree_node.html` (the unit-page rail); `_outline_node.html` never reads it. Load-bearing,
  and it gets its own test.

## Testing

Every test is written failing-first, and each guard is falsified against a mutant chosen from its
own failure mode — a test that cannot go RED on the broken build does not ship.

### `tests/test_resume_target.py` — `build_resume` unit tests

| Test | Mutant it must catch |
|---|---|
| in-flight uncompleted unit → `resume`, that unit | returning the *next* unit instead |
| most recent unit completed → `next`, the following uncompleted unit | returning the completed unit |
| no rows at all → `start`, first uncompleted leaf | returning `None` |
| all leaves completed → `None` | returning the last unit |
| no visible leaves at all → `None` | `IndexError` on `open[0]` |
| rows exist but none resolve to a visible leaf → `next` (**not** `start`) | collapsing step 4 into step 5 |
| finished the final unit, unit 3 still open → `gap`, unit 3 | dropping the wrap-around, returning `None` |
| **quiz answered but not submitted is the target** — seed a `QuestionResponse.last_attempt_at` newer than a later-opened lesson | **dropping source C**; this is the whole reason C exists, and source B alone passes a naive version of this test |
| quiz opened, nothing answered, most recent → still the target | dropping source B |
| completed quiz counts as done and is advanced past | treating `unit_type == quiz` as never-complete |
| teacher force-submits quiz 30 while student is mid-unit-5 → target stays unit 5 | ordering the completion anchor by `updated_at` instead of `completed_at` |
| teacher grades a submitted quiz → target unmoved | dropping the `status=IN_PROGRESS` filter on B/C |
| all *required* lessons done, one additional lesson open → card still points at the additional lesson | filtering `open` to obligatory lessons |
| `progress_reset` for the course leaves the target unmoved | making the reset write through `save()` |
| two rows written in one transaction → deterministic target | dropping the `-pk` tiebreak |
| `ancestors` is the root→parent chain, unit excluded | off-by-one including the unit itself |
| root-level unit in a flat course → `ancestors == []`, no crash | assuming a non-empty chain |
| returned `node` is a `ContentNode`, not a leaf dict | returning `leaf` instead of `leaf["node"]` |
| exactly 4 queries for a direct `build_resume(...)` call | rebuilding the tree, or an N+1 over leaves |

### Render tests — `tests/test_courses_views.py` (outline render/permission home)

- the card links to `courses:quiz_unit` for a quiz target and `courses:lesson_unit` for a lesson —
  mutant: pointing both at `lesson_unit`;
- each of the four `state` values renders its own eyebrow string — mutant: collapsing them to one;
- a **non-enrolled** viewer with `can_access_course` (author/staff) gets **no** card;
- loading the outline with `?tags=<id>` that excludes the target still points at the target —
  mutant: filtering `leaves` on `tag_hidden`;
- the outline tree renders identically with and without stamping (the inert-mutation guard);
- the eyebrow carries `lang="{{ LANGUAGE_CODE }}"` while the title keeps the course language.

### `tests/test_title_math_markers.py`

Extend the outline section so the card's unit title **and** each ancestor label are covered by the
existing marker-coverage suite — mutant: dropping `data-math-title` from the ancestor labels.

### Manual verification

Screenshots of the outline page in **light and dark**, judged separately, at desktop width and at
**640px** — the shell breakpoint `.outline__head` actually reflows at (`app.css:689-691`). (832px
is the `.unit-crumbs` breakpoint in `courses.css` and is *not* relevant here.)

### i18n

**Four** new translatable strings. `makemessages`, Polish translations filled in, `.mo`
regenerated, and the branch rebased before the PR so the binary `.mo` does not conflict.

### Definition of done

`ruff check --no-cache` and `ruff format --check` clean; `manage.py makemigrations --check` clean
(this change must add none); `manage.py check` clean; the courses non-e2e suite green.
