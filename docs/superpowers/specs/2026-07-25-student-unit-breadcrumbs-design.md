# Student unit-page breadcrumbs

## Purpose

A student reading a unit deep inside a long course has no compact "where am I" indicator. The
sidebar tree (PR #164) shows the current chain, but it is collapsible on desktop and lives behind a
drawer on mobile — so on a phone there is currently *nothing* on screen naming the enclosing
part/chapter/section.

This adds a quiet one-line breadcrumb above the unit title on both the lesson and the quiz page:

```
Algebra 2  ›  Sequences  ›  Series
# Convergence tests
```

Crumbs render **bare `ContentNode.title` values**. There is no kind label and no ordinal — nothing
in the data model stores one, and every existing chain renderer in the repo (`_unit_tree_node.html`,
`_outline_node.html`, `editor.html`) renders the bare title. Adding "Part 2 · " would mean deriving
an ordinal from sibling `order` and translating `get_kind_display`, which is out of scope.

### Scope decisions (settled during brainstorming — do not relitigate)

1. **The crumb is the path _to_ the page; the current unit is NOT a crumb.** The
   `<h1 class="lesson-unit__title">` immediately below already names it. Omitting it drops the
   usually-longest segment for free and caps the strip at four segments.
2. **Only the course crumb is a link** (to `courses:course_outline`). Part / chapter / section have
   no student-facing detail page, so those segments are plain text. Inventing one — or making them
   scroll the sidebar — was considered and rejected as scope the tree already covers.
3. **"Pinned ends, squeezed middle" truncation.** One line, always; never wraps. The course crumb
   (the escape hatch) and the deepest group crumb (the real context) survive; the middle absorbs
   the squeeze and then disappears below the collapse breakpoint.
4. **Zero JavaScript.** The collapse is pure CSS, so there is no runtime measurement, no resize
   observer, and no flash of the wrong state on first paint.
5. **Disclosure is a native `title` tooltip plus the existing Contents drawer** — see §Disclosure
   for what that does and does not buy, and for the accepted limitation.

### Non-goals

- No breadcrumb on the course outline page, the builder, or any manage view.
- **No breadcrumb on `quiz_results.html`.** `quiz_unit` redirects to `courses:quiz_results` for any
  SUBMITTED quiz (`courses/views.py`), so a student who has finished a quiz lands there rather than
  on `_quiz_article.html`. That page renders its own `<article class="quiz-results result">`
  *outside* `_unit_shell.html`, has no sidebar tree and no drawer, and has no `unit_nav` in its
  context. Covering it means a new `build_unit_nav` call (new queries on that view) plus its own
  alignment work against `.result`. That is real added scope beyond the approved design, so it is
  deliberately excluded and called out in the PR body as the obvious follow-up.
- No change to the sidebar tree, the mobile drawer, or the unit footer.
- No new student-facing URLs for part/chapter/section.

## Disclosure

What a student can do to read a segment the layout has shortened or hidden:

| Context | Affordance |
|---|---|
| Desktop, a segment clipped by `text-overflow` | Hovering the crumb shows its full title — a native `title` tooltip. |
| Desktop, mid segments collapsed to `…` | Hovering the `…` shows `hidden_path`, the exact titles it stands in for. |
| Any width, screen reader | Every crumb's text is real DOM text, so clipped titles are read in full. Where the mid crumbs are `display: none` they leave the accessibility tree, so the `…` carries their text as its accessible name (see §2). |
| Touch / no hover | **`title` does nothing.** The full chain is available from the **Contents** drawer in the unit footer, which the tree already opens to the current unit. |

**Accepted limitation, stated rather than papered over:** on a touch device the collapsed `…`
is not itself interactive and reveals nothing on tap. This is deliberate. Making it a
`<button>`/`<details>` would break the zero-JS decision (decision 4) and duplicate a disclosure the
Contents drawer already provides one tap away. The comment at `templates/courses/_unit_tree_node.html`
records the same reasoning for the tree's own labels: *"Touch has no hover, so the drawer wraps
these labels instead."* The breadcrumb is an orientation strip, not the system of record for the
chain — the drawer is.

A consequence worth naming: a screen-reader user on a narrow viewport hears
`Course › <deepest group>` plus the `…`'s accessible name. That is the whole path, in two pieces.

## Architecture / components

Four changes. No migrations, no new app, no new JS file.

### 1. Data — `courses/rollups.py`

`build_unit_nav(course, user, current_node)` already builds the full outline tree and calls
`_stamp_current_chain(tree, current_node.pk)`, which sets `contains_current = True` on the current
unit and on every one of its ancestors (and `False` everywhere else). The breadcrumb chain is
therefore **already computed** — it just needs collecting.

Add a module-level constant and a helper:

```python
CRUMB_SEP = " › "   # ALSO hard-coded in templates/courses/_unit_crumbs.html — see the invariant below

def _current_ancestors(tree):
    """Root→parent ContentNodes on the stamped current chain, excluding the unit itself."""
```

Contract, spelled out because two of the three branches are easy to get wrong:

- **Entry is at root level.** `tree` is a *list of roots*, not a children list. Scan `tree` for the
  root whose `contains_current` is True; from there descend by scanning each dict's `children` for
  the stamped child, and repeat.
- **Collect `d["node"]` for every stamped dict where `d["is_unit"]` is False**, so the current unit
  is excluded by construction. Returns a list, root-first, length 0–3.
- **Stamped but unmatched → `[]`, legitimately.** `_stamp_current_chain` stamps every dict `False`
  when `current_pk` is not in the tree. That is a real state — `build_unit_nav` already handles it
  defensively for prev/next (`idx is None`) — so no stamped root simply means an empty chain, not an
  error.
- **Unstamped → `KeyError`, deliberately.** Read `d["contains_current"]` directly rather than via
  `.get()`, matching `_top_level_part`'s existing contract, so a future caller that forgets to stamp
  fails loudly. This is distinct from the empty-result case above and the distinction is intentional.

`build_unit_nav` gains two keys in its returned dict, computed **after** the existing
`_stamp_current_chain` call:

| Key | Type | Meaning |
|---|---|---|
| `ancestors` | `list[ContentNode]` | root→parent, unit excluded; drives the template loop |
| `hidden_path` | `str` | the all-but-deepest ancestor titles joined with `CRUMB_SEP`; `""` when `len(ancestors) < 2` |

`hidden_path` is the `title` and accessible name for the collapsed `…`, pre-joined in Python so the
template needs no custom filter and no parallel list.

**Invariant — `hidden_path` must list exactly the crumbs the CSS hides.** Its correctness depends
entirely on "collapsed on narrow screens" meaning "every ancestor except the deepest". If the CSS
ever hides a different set, the tooltip silently describes the wrong crumbs — a plausible-but-wrong
string, the hardest kind of defect to notice. This coupling is guarded by an e2e assertion (see
§Testing) and may not be broken by the design pass.

**Invariant — one separator glyph, two call sites.** The glyph lives in `CRUMB_SEP` and in
`_unit_crumbs.html`. Changing it means changing both; a render test asserts the rendered separator
text equals `CRUMB_SEP.strip()` so the two cannot drift.

**Query budget: zero additional queries.** The tree is already materialised in memory; the helper is
pure dict traversal. A naive `unit.parent` walk (up to 3 queries per page load) is explicitly
rejected. `tests/test_unit_nav_render.py::test_build_unit_nav_adds_no_queries` already exists and
must continue to pass unchanged.

**Deliberate duplication.** `courses/views_manage.py::_unit_ancestors` walks `node.parent` to build
the *builder* breadcrumb. It stays as-is: the builder side has no materialised tree to read from, so
the parent walk is the right implementation there. Add a one-line comment on each function pointing
at the other so the duplication reads as deliberate rather than as drift.

### 2. Template — new `templates/courses/_unit_crumbs.html`

Structure, in DOM order:

1. `<nav class="unit-crumbs" aria-label="{% trans 'Breadcrumb' %}">`
2. `<ol class="unit-crumbs__list" role="list">`
3. **Course crumb** — `<li class="unit-crumbs__item unit-crumbs__item--course" title="{{ course.title }}">`
   containing `<a href="{% url 'courses:course_outline' slug=course.slug %}">{{ course.title }}</a>`
4. **Ellipsis pair**, emitted **iff `unit_nav.hidden_path` is non-empty**, immediately after the
   course crumb, in the order separator-then-item:
   - `<span class="unit-crumbs__sep unit-crumbs__sep--ellipsis" aria-hidden="true">›</span>`
   - `<li class="unit-crumbs__ellipsis">…<span class="visually-hidden">{{ unit_nav.hidden_path }}</span></li>`
     also carrying `title="{{ unit_nav.hidden_path }}"`
5. **For each ancestor**, a separator then an item, both carrying the same modifier:
   - mid (`not forloop.last`): `unit-crumbs__sep--mid` and `unit-crumbs__item--mid`
   - leaf (`forloop.last`): `unit-crumbs__sep--leaf` and `unit-crumbs__item--leaf`
   - each `<li>` carries `title="{{ a.title }}"`

Rules the markup must satisfy:

- **Separators are real elements**, not CSS `::before`: generated content is not selectable, is not
  copied with the text, and is read inconsistently by assistive tech. This is the *structural* point
  `.editor-crumb` also follows — note that it deviates in two details on purpose (it uses `/`, and
  it has no `aria-hidden`), so neither should be "fixed" to match the other.
- **A separator always carries the same modifier as the item it precedes**, so it is hidden by the
  same rule. Otherwise a collapsed view paints orphaned `›` glyphs.
- **The `…` pair is emitted only when `hidden_path` is non-empty.** A 0- or 1-ancestor course never
  emits it, so there is nothing to hide and nothing to mis-announce. (Round-1 review caught the
  earlier draft asserting both "always rendered" and "only when non-empty"; only the latter holds.)
- **`title` goes on the `<li>`, never on the `<a>`.** A `title` on the link would join its
  accessible name and be announced twice ("Algebra 2, Algebra 2"); on a non-interactive `<li>` it
  still produces the hover tooltip without touching any accessible name.
- **The `…` is not `aria-hidden`.** At the widths where it renders, the mid crumbs are
  `display: none` and therefore *absent* from the accessibility tree — so the `…` is the only
  carrier of that text, and it holds it in a `visually-hidden` span. (The earlier draft's rationale
  for `aria-hidden` — "the text is still in the DOM, unhidden, a few nodes earlier" — is false at
  exactly the breakpoint where the `…` exists.)
- **No `aria-current`, intentionally.** The conventional breadcrumb ends on the current page marked
  `aria-current="page"`; this one ends on an ancestor because of decision 1. The current page is the
  `<h1>` immediately below. Recording this so it does not read as an oversight next to
  `_unit_tree_node.html`, which does use `aria-current="page"`.
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

A new `.unit-crumbs` block adjacent to the existing `.lesson-unit__head` rules, **plus a dedicated
media query of its own** — not folded into an existing one. (`courses.css` has three
`@media (max-width: 640px)` blocks; the unit-shell one is the block containing
`.unit-shell { display: block }` / `.unit-tree { display: none }`. The crumb does not use it.)

Mechanism:

- `.unit-crumbs__list` — `display: flex; flex-wrap: nowrap; align-items: baseline; overflow: hidden;`
  `gap` supplies **all** spacing between crumbs and separators; `list-style: none` with margin and
  padding zeroed. `gap` rather than margins because a `display: none` item takes its gap with it,
  whereas a margin-based version leaves a dangling space.
  `overflow: hidden` here is the backstop that keeps a worst case from pushing the whole page into
  horizontal scroll. It does not mask the e2e guard: `scrollWidth` still reports the content width.
- Every `.unit-crumbs__item` — `min-width: 0; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap;`. `min-width: 0` is load-bearing: without it a flex item refuses to shrink
  below its content width and the strip overflows instead of clipping. It belongs on the *items*;
  the container does not need it (the ancestor `.unit-shell__main` already carries `min-width: 0`).
- `.unit-crumbs__item--mid` — a large `flex-shrink` (~200) so mid segments absorb essentially all of
  any deficit before the pinned ends give up a pixel, **and a floor** (`min-width` of roughly
  `4ch`). The floor is not cosmetic: with `min-width: 0` and a 200× factor a mid would otherwise
  collapse toward 0px while its separator keeps full width, producing `Algebra 2 › › Series` —
  the same orphaned-separator failure the collapse rule exists to prevent, just at a wider viewport.
- `.unit-crumbs__item--course` and `--leaf` — `flex-shrink: 1`.
- `.unit-crumbs__sep` — `flex: 0 0 auto` so separators never shrink or clip.
- `.unit-crumbs__ellipsis` and `.unit-crumbs__sep--ellipsis` — `display: none` by default.
- **Collapse query — `@media (max-width: 52rem)`:** `--mid` items and `--mid` separators go
  `display: none`; the `…` and `--ellipsis` separator become visible.

**Why 52rem and not the shell's 640px.** The content column is *narrowest just above* the shell
breakpoint: at 641px the 14rem rail is still present, leaving ~417px, whereas at 360px the rail is
gone and the column is ~328px of a much simpler layout. Collapsing at the shell breakpoint would
leave the worst case uncollapsed. 52rem is a starting value the design pass may tune.

**Invariants the design pass may not break** (colour, size, weight, glyph, spacing, and the
breakpoint value are all otherwise free):

1. The strip is exactly one line at every viewport width.
2. It never causes page-level horizontal scroll.
3. A rendered separator always has rendered text on both sides — no orphaned glyphs.
4. The course crumb and the deepest crumb are always present and legible.
5. The set of crumbs hidden by the collapse query is exactly the set `hidden_path` names.
6. The separator glyph matches `CRUMB_SEP`.

Baseline styling: `--text-tertiary`, ~0.85rem, `--space-3` bottom margin, course link inheriting the
muted colour rather than the default link blue. Because `overflow: hidden` on an item clips a focus
ring drawn outside the link's border box, the course crumb needs either an inner wrapper to carry
the clipping or an `outline-offset`/padding allowance — keyboard focus visibility on that link is an
explicit item on the design-pass QA checklist.

## Data flow

```
lesson_unit  ─→ full_lesson_render_context ─┐
check_answer ─→ full_lesson_render_context ─┤
                                            ├─→ build_unit_nav(course, user, unit)
quiz_unit           ─→ ctx["unit_nav"] = ───┤
_quiz_render_feedback ─→ ctx["unit_nav"] = ─┘
                                              ├─ build_outline(course, user)         → tree             (2 queries, existing)
                                              ├─ _stamp_current_chain(tree, unit.pk) → contains_current (0 queries, existing)
                                              └─ _current_ancestors(tree)            → ancestors        (0 queries, NEW)
                                                   └─ hidden_path = CRUMB_SEP.join(a.title for a in ancestors[:-1])

templates: lesson_unit.html / quiz_unit.html
  └─ _unit_shell.html
       └─ _lesson_article.html / _quiz_article.html
            └─ _unit_crumbs.html   ← reads course.*, unit_nav.ancestors, unit_nav.hidden_path
```

**Note the asymmetry.** The lesson side is genuinely single-sourced: every render path goes through
`full_lesson_render_context`, which sets `unit_nav`. The quiz side is **not** — `build_quiz_context`
does not call `build_unit_nav`; `quiz_unit` and `_quiz_render_feedback` each set `ctx["unit_nav"]`
themselves. Hoisting it into `build_quiz_context` is out of scope for this change (it would alter a
context builder shared with other callers), so the mitigation is coverage: §Testing requires a render
assertion at **both** quiz sites, and the graceful-degrade row in §Error handling covers a future
third site that forgets.

The partial reads exactly three context values: `course`, `unit_nav.ancestors`,
`unit_nav.hidden_path`. It never touches `unit`.

## Error handling

There is no user input and no write path here; the failure modes are all "missing or unusual data".

| Situation | Behaviour |
|---|---|
| **Flat course, 0 ancestors** | Render the `<nav>` with the course crumb alone. It is still a useful top-of-page route back to the contents. Do **not** suppress the whole strip. `hidden_path == ""`, so no `…` pair is emitted. |
| **1 ancestor** | `Course › Part`. `hidden_path == ""` → no `…` pair, and nothing is ever hidden by the collapse query. |
| **Skipped levels** (a unit whose only ancestor is a part, in a course flagged "Full") | Renders `Course › Part`. This is exactly why the chain comes from the real `parent` links and never from `Course.uses_parts/uses_chapters/uses_sections` — those flags are authoring policy, not a guarantee about existing rows. |
| **`unit_nav` absent from the context** on some re-render path | Django resolves the missing variable to empty: the `{% for %}` yields nothing, `hidden_path` is empty, and the course crumb still renders. Degrades; does not raise. |
| **`current_pk` not present in the tree** | `_current_ancestors` returns `[]` → course crumb only. A legitimate empty result, not an error. |
| **Unstamped tree passed to `_current_ancestors`** | `KeyError`, deliberately — matches `_top_level_part`'s existing contract, so a future caller that forgets to stamp fails loudly instead of silently rendering an empty crumb. |
| **Pathological title lengths** (`ContentNode.title` allows 200 chars) | CSS clips with an ellipsis. Even when the course crumb and the leaf crumb alone exceed the viewport, both shrink proportionally, the list's `overflow: hidden` absorbs the remainder, and the strip stays one line without scrolling the page. |

## Testing

### Unit / render — extend `tests/test_unit_nav_render.py`

1. `_current_ancestors` returns the right nodes, root-first, at depths 0, 1, 2 and 3.
2. `_current_ancestors` excludes the current unit itself.
3. `_current_ancestors` returns `[]` for a stamped tree with no match, and raises `KeyError` for an
   unstamped tree.
4. Skipped level: unit → part only (in a `uses_*`-all-True course) yields exactly `[part]`.
5. `hidden_path` equals the all-but-deepest titles joined with `CRUMB_SEP`; `""` at 0 and 1
   ancestors.
6. The rendered separator text equals `CRUMB_SEP.strip()` — locks the glyph's two call sites
   together.
7. Crumb renders at **all four** unit render sites: the lesson GET, the quiz GET, and both no-JS
   POST re-renders (`check_answer` and `quiz_answer` without the fragment header). Assert the
   ancestors are present, not merely that the page returns 200 — these are the paths §Data flow
   flags as fragile.
8. The course crumb is an `<a href>` to `courses:course_outline`.
9. **No `<a>` inside any group crumb** — the "plain text" decision, guarded.
10. Every mid separator carries `unit-crumbs__sep--mid`, and the leaf separator carries
    `--leaf` — the pairing rule from §2, which is otherwise invisible until it breaks on mobile.
11. Flat course renders the `<nav>` with the course crumb and **no** `…` pair.
12. `test_build_unit_nav_adds_no_queries` (already present) still passes — the zero-query guarantee.

### Falsification — mandatory

Per the recorded lesson in `falsify-tests-not-run-them`: for **each** test above, delete or invert
the thing it guards and confirm the test goes **RED** before keeping it. A test that cannot be made
to fail is not a test. The plan must name the falsifying mutation per test.

### e2e — `tests/test_e2e_unit_crumbs.py`

New file, `pytestmark = pytest.mark.e2e`, following the fixtures in `tests/test_e2e_unit_nav.py`
(`page`, `live_server`, `_login`) and extending its `_seed_nav_course` helper to take explicit
titles. Seed a deliberately pathological path: a ~60-char course title and three ~60-char group
titles. Run focused and in the foreground — a background `-m e2e` sweep spawns runaway browsers.

- **The real guard, at 1280px and at 360px:** `.unit-crumbs__list` `scrollWidth <= clientWidth`,
  and `document.documentElement.scrollWidth <= window.innerWidth`. **Falsifying mutation:** delete
  `min-width: 0` from `.unit-crumbs__item` — items then refuse to shrink and the first assertion
  goes red. The height check below does **not** catch this, which is why it is not the primary
  guard.
- Secondary: `.unit-crumbs__list` `offsetHeight` equals one line height. Cheap, and catches an
  accidental `flex-wrap: wrap`.
- At 360px: no `--mid` item is visible, the `…` **is** visible, and the count of **visible** `›`
  glyphs is exactly the count of visible crumbs minus one — the assertion that actually catches an
  orphaned separator, which a `--mid`-only locator cannot.
- At 360px: the `…`'s `title` equals `CRUMB_SEP.join(titles of the crumbs that are display:none)` —
  the guard on the §1 invariant coupling `hidden_path` to the collapse query.
- At 1280px with a short path: the `…` is not visible and every ancestor is.
- Screenshots at both widths × light and dark, reviewed per `verify-ui-with-screenshots`. Force dark
  with `data-theme="dark"` on `documentElement`.

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
screenshot QA pass across desktop × mobile × light × dark, including keyboard focus on the course
link. This is an explicit user request and an explicit deliverable of this work, not an optional
polish step — a previous pipeline run shipped unpolished UI precisely by treating it as optional.
The design pass may freely change the visual treatment; it may not break the six invariants listed
in §4.
