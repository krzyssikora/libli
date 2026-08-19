# Continue where you left off

A resume affordance at the top of the student course-outline page, so a returning student
re-enters the course at the unit they should work on next instead of hunting for it in the tree.

## Purpose

Today `templates/courses/outline.html` opens with a title and four utility links
("Expand all", "My results", "My notes", "Start fresh") and then the full outline tree. There is
no course-level progress summary and **no resume affordance anywhere in the product** — a student
returning to a 60-unit course must remember where they were and scroll to find it.

This adds one card at the top of that page pointing at a single unit, chosen by a
**hybrid resume rule**: the unit you were last in if you had not finished it, otherwise the next
unfinished unit after it.

Out of scope (deliberately): the dashboard (`core/views.py::home`), the "My courses" list, the
catalog, any change to how progress is recorded, and any new model or migration.

## Definition of the target

Let `leaves` be the visible unit leaves of the course in outline order, and let `last` be the unit
in this course with the student's most recent activity.

| Situation | Target | `state` |
|---|---|---|
| `last` exists and is **not** completed | `last` | `resume` |
| `last` exists and **is** completed | first uncompleted leaf **after** `last`; if none, first uncompleted leaf **overall** | `next` |
| no activity in this course, or `last` is no longer a visible leaf | first uncompleted leaf | `start` |
| every visible leaf is completed, or there are no leaves | — (render nothing) | — |

The wrap-around in the `next` row is deliberate: a student who skipped ahead and finished the last
unit still has gaps, and a card that silently disappears while unfinished units remain is worse
than one that points back at the earliest gap.

The `start`-on-missing case covers three real situations with one branch: the student has never
opened anything; the unit they last touched has been deleted; or it has been unpublished / turned
into a draft since. In all three the stored pk is simply absent from `leaves`.

## Architecture / components

Four files change. No model, no migration, no new endpoint, no JavaScript.

### 1. `courses/rollups.py` — `build_resume(course, user, tree)`

The single new piece of logic, placed beside `build_unit_nav` because it consumes the same
`build_outline` tree and the same private helpers.

```
def build_resume(course, user, tree):
    """{"node", "state", "ancestors"} for the outline resume card, or None."""
```

- **`tree`** is the caller's already-built `build_outline(...)` tree — passed in, never rebuilt, so
  the card costs **zero additional tree queries**. This mirrors how `build_unit_nav` is the single
  source for the unit page.
- **`leaves = _flatten_unit_leaves(tree)`** gives the ordered unit-leaf dicts. Each already carries
  `completed` (set by `build_outline` from the student's `UnitProgress.completed` set) and
  `node`. Because the view builds the tree with `drafts="hide"` for students, draft and unpublished
  units are already pruned — the target can never be a unit the student cannot open.
- **Last-touched lookup — two queries, taking the later timestamp:**

  ```
  UnitProgress.objects.filter(student=user, unit__course=course)
      .order_by("-updated_at").values_list("unit_id", "updated_at").first()
  QuizSubmission.objects.filter(student=user, unit__course=course)
      .order_by("-updated").values_list("unit_id", "updated").first()
  ```

  **Both are required.** Loading a quiz page mints a `QuizSubmission` (`views.py:1349`) but **not**
  a `UnitProgress` row, so `UnitProgress` alone is blind to "student is part-way through a quiz".
  Conversely `QuizSubmission` alone is blind to lessons. Ties (identical timestamps) resolve to the
  `UnitProgress` row; the case is degenerate and either answer is defensible.
- **Completion needs no special-casing across unit types.** Submitting a quiz sets
  `UnitProgress.completed = True` (`views.py:1689-1693`), and teacher review does the same
  (`review.py:94`), so the `completed` flag on the leaf dicts is already uniform over lessons and
  quizzes. The lookup above is only about *recency*, never about *doneness*.
- **Ancestors** for the card's `Chapter › Section` line reuse the existing
  `_stamp_current_chain(tree, target_pk)` + `_current_ancestors(tree)` pair — pure dict traversal,
  **no queries**, the same mechanism the unit-page breadcrumbs use. Reusing them rather than adding
  a third ancestor walk is a deliberate anti-drift choice: `courses/views_manage.py::_unit_ancestors`
  is already a documented deliberate twin of `_current_ancestors`, and a third copy would be one
  copy too many.
- Returns `None` for the "render nothing" rows of the table above. `None` is the only signal the
  template needs; it never has to distinguish "course finished" from "course empty".

### 2. `courses/views.py::course_outline`

One added call and one added context key:

```
resume = build_resume(course, request.user, outline) if is_enrolled(request.user, course) else None
```

**Enrolled-only.** `can_access_course` also admits authors, teachers and staff previewing a course
they are not taking; showing them a "Start the course" call to action would be noise. This matches
the existing precedent that the `seen` write route is enrolled-only by design.

**Call order.** `build_resume` runs after `tag_services.outline_with_tags(...)`, but the target is
computed **independently of the active tag filter**: the filter is a browsing aid that hides rows,
not a scope restriction, so filtering to one tag must not change where "Continue" sends you. The
card therefore may point at a unit whose row is currently hidden by the filter — correct, and
stated here so a reviewer does not read it as a bug.

**Draft visibility follows the tree.** A student who is also staff gets `drafts="keep"`, so their
tree — and therefore their resume target — may include a draft unit. That is the same set of units
their outline already shows them; the card does not introduce a new visibility rule.

### 3. `templates/courses/_resume_card.html` (new), included from `outline.html`

Included between `.outline__head` and `{% include "courses/_tags_filter_bar.html" %}`, guarded by
`{% if resume %}`.

Structure — a single `<a>` wrapping the whole card so the entire block is one large hit target:

- an **eyebrow** line, one of three translated strings selected by `resume.state`:
  - `resume` → "Pick up where you left off"
  - `next` → "Up next"
  - `start` → "Start the course"
- the **ancestor path** (`resume.ancestors`) as muted small text, joined with the `›` glyph
- the **unit title**, carrying `data-math-title` so KaTeX typesets it exactly like every other
  title on the page. No view change is needed for this: `has_math` is already computed as
  `tree_titles_have_math(outline)` over the whole tree, and the target is by construction a node
  in that tree.
- `{% include "courses/_unit_kind_chip.html" with node=resume.node only %}` so lesson-vs-quiz is
  visible before the click.

`href` branches on `resume.node.unit_type`: `courses:quiz_unit` for a quiz, `courses:lesson_unit`
otherwise. The existing outline rows link everything through `lesson_unit` and rely on its
redirect (`views.py:798-799`); linking directly costs nothing and avoids a redirect hop on the
page's most prominent control.

**Accessibility.** The eyebrow is the accessible name's leading text, so the link reads as
"Pick up where you left off, <Chapter>, <Unit title>" rather than a bare title. The `›`
separators are `aria-hidden`, following `_unit_crumbs.html`.

### 4. `core/static/core/css/app.css` — a `.resume` block

Placed in the existing "Course outline (syllabus)" section next to `.outline__head`, so the file's
one-section-per-surface organisation holds. Token-driven only: `--surface-raised` for the card
ground, the established border ramp cut against that raised surface (never against base), existing
`--space-*` and `--text-*` tokens. `.outline` is `max-width: 52rem` and centred, so the card
inherits the column width and needs no width of its own.

## Data flow

```
GET /courses/<slug>/
  └─ course_outline
       ├─ build_outline(course, user, drafts=…)         2 queries  (existing)
       ├─ outline_with_tags(...)                                   (existing)
       └─ build_resume(course, user, outline)           2 queries  (new)
            ├─ _flatten_unit_leaves(tree)               0 queries
            ├─ UnitProgress   … order_by(-updated_at).first()
            ├─ QuizSubmission … order_by(-updated).first()
            └─ _stamp_current_chain + _current_ancestors  0 queries
  └─ render outline.html
       └─ _resume_card.html   (guarded by {% if resume %})
```

Net cost: **two extra queries**, each an indexed single-row lookup, and no extra tree walk beyond
two linear passes over an already-materialised list of dicts.

### What bumps recency, and what does not

`UnitProgress.updated_at` is `auto_now`, so it advances on every `save()`: the first `get_or_create`
when an enrolled student opens a lesson (`views.py:511`), each `seen` batch the
IntersectionObserver posts as they read, each practice-state write, and completion.

`progress_reset` ("Start fresh") writes with `rows.update(element_state={})`, and a queryset
`.update()` **does not** fire `auto_now`. So resetting practice state deliberately leaves both
`updated_at` and `completed` untouched, and the resume target does not move. This is the intended
behaviour — clearing your scratch work should not send you back to unit 1 — but note that the
comment above that call currently asserts *"nothing reads updated_at for practice state"*, which
this feature falsifies. **That comment must be corrected in this change**, in a line-count-neutral
way, or it becomes a false statement that no test can catch.

## Error handling

- **No leaves / everything completed** → `build_resume` returns `None`, template renders nothing.
  No empty card, no placeholder.
- **Stored last-touched pk not in `leaves`** (deleted, unpublished, or moved out of the course) →
  falls into the `start` branch. No exception, no query for the missing node — membership is tested
  against the in-memory leaf list, so a dangling pk is structurally impossible to dereference.
- **Not enrolled** → the view never calls `build_resume`; `resume` is `None`.
- **Anonymous user** → unreachable: `course_outline` is `@login_required`, and `is_enrolled` is
  false for anonymous users regardless.
- **Unstamped-tree contract.** `_current_ancestors` reads `contains_current` directly and raises
  `KeyError` on an unstamped tree by design. `build_resume` always calls `_stamp_current_chain`
  immediately before it, so the contract is satisfied at the single call site.
- **Stamping is inert on this page.** `_stamp_current_chain` mutates the tree the template then
  renders, adding `contains_current` to every dict. `contains_current` is read only by
  `templates/courses/_unit_tree_node.html` (the unit-page rail); `_outline_node.html` never reads
  it, so stamping has no visual effect on the outline. This is load-bearing and gets its own test.

## Testing

All tests are written failing-first, and each guard is falsified against a mutant chosen from its
own failure mode — a test that cannot go RED on the broken build does not ship.

**`tests/test_resume_target.py` — `build_resume` unit tests**

| Test | Mutant it must catch |
|---|---|
| last-touched unit incomplete → `resume`, that unit | returning the *next* unit instead |
| last-touched unit completed → `next`, the following uncompleted unit | returning the completed unit |
| no activity at all → `start`, first uncompleted leaf | returning `None` |
| all leaves completed → `None` | returning the last unit |
| last-touched pk absent from `leaves` (unit unpublished after the visit) → `start` | `KeyError`/`None` |
| skipped ahead: finished the final unit, unit 3 still open → wraps to unit 3 | dropping the wrap-around, returning `None` |
| in-progress **quiz** (a `QuizSubmission` but no `UnitProgress` row) is the target | dropping the `QuizSubmission` query — this is the whole reason it exists |
| a **completed quiz** counts as done and is advanced past | treating `unit_type == quiz` as never-complete |
| `ancestors` is the root→parent chain, unit excluded | off-by-one including the unit itself |
| query count is exactly 2 beyond `build_outline` | rebuilding the tree, or an N+1 over leaves |

**Render tests (extending the existing outline render suite)**

- the card links to `courses:quiz_unit` when the target is a quiz and `courses:lesson_unit` when it
  is a lesson — falsified by pointing both at `lesson_unit`;
- each of the three `state` values renders its own eyebrow string — falsified by collapsing them to
  one string;
- a **non-enrolled** viewer with `can_access_course` (author/staff) gets **no** card;
- the outline tree renders identically with and without stamping (the inert-mutation guard).

**Manual verification**

Screenshots of the outline page in **light and dark**, judged separately, at desktop and at the
832px narrow breakpoint the outline already targets.

**i18n**

Three new translatable strings. `makemessages`, Polish translations filled in, `.mo` regenerated,
and the branch rebased before the PR so the binary `.mo` does not conflict.

**Definition of done**

`ruff check --no-cache` and `ruff format --check` clean; `manage.py makemigrations --check` clean
(this change must add none); `manage.py check` clean; the courses non-e2e suite green.
