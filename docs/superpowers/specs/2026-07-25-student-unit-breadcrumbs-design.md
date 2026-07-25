# Student unit-page breadcrumbs

## Purpose

A student reading a unit deep inside a long course has no compact "where am I" indicator. The
sidebar tree (PR #164) shows the current chain, but it is collapsible on desktop and lives behind a
drawer on mobile — so on a phone there is currently *nothing* on screen naming the enclosing
part/chapter/section.

This adds a quiet one-line breadcrumb above the unit title on both the lesson and the quiz page:

```
Algebra 2  ›  Part 2 · Sequences  ›  Chapter 4 · Series
# Convergence tests
```

### Scope decisions (settled during brainstorming — do not relitigate)

1. **The crumb is the path _to_ the page; the current unit is NOT a crumb.** The
   `<h1 class="lesson-unit__title">` immediately below already names it. Omitting it drops the
   usually-longest segment for free and caps the strip at four segments.
2. **Only the course crumb is a link** (to `courses:course_outline`). Part / chapter / section have
   no student-facing detail page, so those segments are plain text. Inventing one — or making them
   scroll the sidebar — was considered and rejected as scope the tree already covers.
3. **"Pinned ends, squeezed middle" truncation.** One line, always; never wraps. The course crumb
   (the escape hatch) and the deepest group crumb (the real context) survive; the middle absorbs
   the squeeze and then disappears below the mobile breakpoint.
4. **Zero JavaScript.** The collapse is pure CSS, so there is no runtime measurement, no resize
   observer, and no flash of the wrong state on first paint.
5. **Disclosure is a native `title` tooltip**, not a JS popover — see §Disclosure.

### Non-goals

- No breadcrumb on the course outline page, the builder, or any manage view.
- No change to the sidebar tree, the mobile drawer, or the unit footer.
- No new student-facing URLs for part/chapter/section.

## Architecture / components

Four changes. No migrations, no new app, no new JS file.

### 1. Data — `courses/rollups.py`

`build_unit_nav(course, user, current_node)` already builds the full outline tree and calls
`_stamp_current_chain(tree, current_node.pk)`, which sets `contains_current = True` on the current
unit and on every one of its ancestors (and `False` everywhere else). The breadcrumb chain is
therefore **already computed** — it just needs collecting.

Add a module-level helper:

```python
def _current_ancestors(tree):
    """Root→parent ContentNodes on the stamped current chain, excluding the unit itself."""
```

- Requires a tree already stamped by `_stamp_current_chain` (same precondition as
  `_top_level_part`); it reads `contains_current` directly so an unstamped tree raises `KeyError`
  loudly rather than silently returning `[]`.
- Descends the single stamped path: at each level, take the child dict with `contains_current` and
  recurse. Collects `d["node"]` for every stamped dict **where `is_unit` is False**, so the current
  unit is excluded by construction.
- Returns a list, root-first, length 0–3.

`build_unit_nav` gains two keys in its returned dict, computed **after** the existing
`_stamp_current_chain` call:

| Key | Type | Meaning |
|---|---|---|
| `ancestors` | `list[ContentNode]` | root→parent, unit excluded; drives the template loop |
| `hidden_path` | `str` | the all-but-deepest ancestor titles joined with `" › "`; `""` when `len(ancestors) < 2` |

`hidden_path` is the `title` text for the collapsed `…`, pre-joined in Python so the template needs
no custom filter and no parallel list.

**Query budget: zero additional queries.** The tree is already materialised in memory; the helper is
pure dict traversal. A naive `unit.parent` walk (up to 3 queries per page load) is explicitly
rejected. `tests/test_unit_nav_render.py::test_build_unit_nav_adds_no_queries` already exists and
must continue to pass unchanged.

**Deliberate duplication.** `courses/views_manage.py::_unit_ancestors` walks `node.parent` to build
the *builder* breadcrumb. It stays as-is: the builder side has no materialised tree to read from, so
the parent walk is the right implementation there. Add a one-line comment on each function pointing
at the other so the duplication reads as deliberate rather than as drift.

### 2. Template — new `templates/courses/_unit_crumbs.html`

```
<nav class="unit-crumbs" aria-label="{% trans 'Breadcrumb' %}">
  <ol class="unit-crumbs__list">
    <li class="unit-crumbs__item unit-crumbs__item--course" title="{{ course.title }}">
      <a href="{% url 'courses:course_outline' slug=course.slug %}">{{ course.title }}</a>
    </li>
    …for each ancestor: a separator <span> then an <li>…
  </ol>
</nav>
```

Rules the markup must satisfy:

- **Separators are real elements** — `<span class="unit-crumbs__sep" aria-hidden="true">›</span>` —
  matching how `.editor-crumb` does it. Not a CSS `::before`: generated content is not selectable,
  is not copied with the text, and is read inconsistently by assistive tech.
- **The last ancestor gets `unit-crumbs__item--leaf`** (`forloop.last`). That modifier is what the
  CSS protects from shrinking and keeps visible on mobile.
- **Middle ancestors get `unit-crumbs__item--mid`** (`not forloop.last`). That modifier is what the
  CSS shrinks first and hides on mobile. The separator preceding a mid item must carry the same
  modifier so it disappears with it — otherwise the mobile view renders orphaned `›` glyphs.
- **The `…` item is always rendered in the HTML**, hidden by CSS above the breakpoint:
  `<li class="unit-crumbs__ellipsis" aria-hidden="true" title="{{ unit_nav.hidden_path }}">…</li>`
  (plus its own separator). It is rendered only when `unit_nav.hidden_path` is non-empty, so a
  0- or 1-ancestor course never emits a stray `…`. It is `aria-hidden` because the text it stands in
  for is still in the DOM, unhidden, a few nodes earlier — announcing both would be redundant.
- **Every crumb carries `title="<its own full title>"`** so hovering a clipped segment completes it.
- `{% load i18n %}` at the top; `Breadcrumb` is the only new translatable string.

**No `lang` attribute is set inside this partial.** The include sits inside
`<article … lang="{{ course.language }}">`, so author-authored node titles already inherit the
course language — unlike the sidebar tree, which sits *outside* the article and therefore has to set
`lang` per title itself.

### 3. Placement — inside the two article partials

Add `{% include "courses/_unit_crumbs.html" %}` as the first child of the `<article>` in:

- `templates/courses/_lesson_article.html` — immediately above `<div class="lesson-unit__head">`
- `templates/courses/_quiz_article.html` — immediately above `<h1 class="lesson-unit__title">`
  (the quiz has no `lesson-unit__head` wrapper)

**Why not `_unit_shell.html`** (which would be one edit covering both): inside the shell,
`courses.css` overrides the article's standalone `max-width: 46rem` with
`.unit-shell__main > .lesson, .unit-shell__main > .quiz { max-width: none; margin-inline: 0;
padding: 1.25rem 1.5rem; }`. A crumb placed as a sibling of the article in `.unit-shell__main` would
sit outside that padding and fail to align with the title below it, and would have to duplicate both
the padding and its mobile override. Inside the article it inherits both, plus `lang`, for free.

### 4. CSS — `courses/static/courses/css/courses.css`

A new `.unit-crumbs` block adjacent to the existing `.lesson-unit__head` rules, plus additions to
the existing `@media (max-width: 640px)` block. Mechanism:

- `.unit-crumbs__list` — `display: flex; flex-wrap: nowrap; align-items: baseline; min-width: 0;`
  and `list-style: none` with margin/padding zeroed.
- Every `.unit-crumbs__item` — `min-width: 0; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap;`. `min-width: 0` is load-bearing: without it a flex item refuses to shrink
  below its content width and the strip overflows instead of clipping.
- `.unit-crumbs__item--mid` — a large `flex-shrink` (~200) so mid segments absorb essentially all of
  any deficit before the pinned ends give up a pixel. `flex-shrink` is applied in proportion to
  factor × base size, so a large factor is the mechanism, not a magic number.
- `.unit-crumbs__item--course` and `--leaf` — `flex-shrink: 1`.
- `.unit-crumbs__sep` — `flex: 0 0 auto` so separators never shrink or clip.
- `.unit-crumbs__ellipsis` — `display: none` by default.
- Inside `@media (max-width: 640px)`: `--mid` items and `--mid` separators go `display: none`; the
  `…` item and its separator become visible.

Baseline styling: `--text-tertiary`, ~0.85rem, `--space-3` bottom margin, course link inheriting the
muted colour rather than the default link blue. **The final visual treatment is decided by the
frontend-design pass (see below), not by this spec** — this spec fixes the *mechanism*, and the
design pass may change colour, size, weight, separator glyph, and spacing freely as long as the
one-line invariant and the shrink ordering survive.

## Data flow

```
lesson_unit / quiz_unit view
  └─ full_lesson_render_context / build_quiz_context
       └─ build_unit_nav(course, user, unit)
            ├─ build_outline(course, user)              → tree            (2 queries, existing)
            ├─ _stamp_current_chain(tree, unit.pk)      → contains_current (0 queries, existing)
            └─ _current_ancestors(tree)                 → ancestors        (0 queries, NEW)
                 └─ hidden_path = " › ".join(a.title for a in ancestors[:-1])
  └─ template: lesson_unit.html / quiz_unit.html
       └─ _unit_shell.html
            └─ _lesson_article.html / _quiz_article.html
                 └─ _unit_crumbs.html   ← reads course.*, unit_nav.ancestors, unit_nav.hidden_path
```

The partial reads exactly three context values: `course`, `unit_nav.ancestors`,
`unit_nav.hidden_path`. It never touches `unit`.

## Error handling

There is no user input and no write path here; the failure modes are all "missing or unusual data".

| Situation | Behaviour |
|---|---|
| **Flat course, 0 ancestors** | Render the `<nav>` with the course crumb alone. It is still a useful top-of-page route back to the contents. Do **not** suppress the whole strip. `hidden_path == ""`, so no `…`. |
| **1 ancestor** | `Course › Part`. `hidden_path == ""` → no `…` is emitted, and nothing is ever hidden on mobile. |
| **Skipped levels** (a unit whose only ancestor is a part, in a course flagged "Full") | Renders `Course › Part`. This is exactly why the chain comes from the real `parent` links and never from `Course.uses_parts/uses_chapters/uses_sections` — those flags are authoring policy, not a guarantee about existing rows. |
| **`unit_nav` absent from the context** on some re-render path | Django resolves the missing variable to empty: the `{% for %}` yields nothing, `hidden_path` is empty, and the course crumb still renders. Degrades; does not raise. |
| **Pathological title lengths** (`ContentNode.title` allows 200 chars) | CSS clips with an ellipsis. Even when the course crumb and the leaf crumb alone exceed the viewport, both shrink proportionally and the strip stays one line. |
| **Unstamped tree passed to `_current_ancestors`** | `KeyError`, deliberately — matches `_top_level_part`'s existing contract, so a future caller that forgets to stamp fails loudly instead of silently rendering an empty crumb. |

## Testing

### Unit / render — extend `tests/test_unit_nav_render.py`

1. `_current_ancestors` returns the right nodes, root-first, at depths 0, 1, 2 and 3.
2. `_current_ancestors` excludes the current unit itself.
3. Skipped level: unit → part only (in a `uses_*`-all-True course) yields exactly `[part]`.
4. `hidden_path` equals the all-but-deepest titles joined; `""` at 0 and 1 ancestors.
5. Crumb renders on the **lesson** page and on the **quiz** page.
6. The course crumb is an `<a href>` to `courses:course_outline`.
7. **No `<a>` inside any group crumb** — the "plain text" decision, guarded.
8. Flat course renders the `<nav>` with the course crumb and **no** `…` item.
9. `test_build_unit_nav_adds_no_queries` (already present) still passes — the zero-query guarantee.

### Falsification — mandatory

Per the recorded lesson in `falsify-tests-not-run-them`: for **each** test above, delete or invert the
thing it guards and confirm the test goes **RED**, before keeping it. A test that cannot be made to
fail is not a test. Note in the plan which mutation falsifies which test.

### e2e — the real guard on the design

Playwright, seeded with a deliberately pathological path (a ~60-char course title and three ~60-char
group titles):

- At **1280px** and at **360px**: assert the strip's rendered height equals exactly one line
  (compare `.unit-crumbs__list` `offsetHeight` against a single crumb's line height). This single
  assertion is what actually protects "one line, always" — the CSS is the feature.
- At 360px: assert `--mid` items are not visible and the `…` **is** visible.
- At 1280px with a short path: assert the `…` is not visible and every ancestor is.
- Screenshots at both widths × light and dark, reviewed per `verify-ui-with-screenshots`.

Force dark with `data-theme="dark"` on `documentElement`, per the established pattern.

### i18n

`Breadcrumb` is a new msgid. Run `makemessages -l pl -l en --no-obsolete`, supply the Polish
translation, and clear any fuzzy — checking for the failure mode in
`makemessages-fuzzy-prefills-wrong-translation`, where a fuzzy entry arrives pre-filled from an
unrelated msgid and clearing the flag promotes wrong text. Clearing a fuzzy means **two** deletions
(`#, fuzzy` and the `#| msgid` line). Then `compilemessages`; `tests/test_i18n_po_health.py` must
pass.

### Tooling notes

- `ruff`, `pytest` and `python` are not on PATH — everything runs under `uv run`, and
  `ruff format --check` is part of the gate.
- This runs in a git worktree: give it its own `DATABASE_URL` so the Postgres `test_libli` database
  does not collide with a concurrent session (see `test-db-contention-across-worktrees`).

## Frontend-design pass (required deliverable)

After the implementation is green, run the `frontend-design` skill on the breadcrumbs and then a
screenshot QA pass across desktop × mobile × light × dark. This is an explicit user request and an
explicit deliverable of this work, not an optional polish step — a previous pipeline run shipped
unpolished UI precisely by treating it as optional. The design pass may freely change the visual
treatment; it may not break the one-line invariant, the shrink ordering, or the zero-JS constraint.
