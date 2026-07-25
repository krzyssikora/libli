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
| Pointer device, narrow viewport (≤ the collapse breakpoint) | Hovering the `…` shows `hidden_path`, the exact titles it stands in for. Note this row is unreachable at desktop widths, where the `…` is `display: none`. |
| Any width, screen reader | Every crumb's text is real DOM text, so clipped titles are read in full. Where the mid crumbs are `display: none` they leave the accessibility tree, so the `…` carries their text as its accessible name (see §2). |
| Print | The collapse query is scoped to `screen`, and `@media print` lets the strip wrap. A printout always shows the complete path. |
| Touch / no hover, JS on | **`title` does nothing.** The full chain is available from the **Contents** drawer in the unit footer, which the tree already opens to the current unit. |
| Narrow viewport, JS off | Nothing discloses the mids. The drawer trigger is gated on `unit_nav.js` removing `[hidden]`, and the inline tree is `display: none` below 640px — so with JS off there is neither. Accepted; see below. |

`title` is emitted **unconditionally** on every crumb, not only on truncated ones — CSS cannot
express "is this element currently clipped", so the alternative is no tooltip at all. The cost is a
redundant tooltip when a title is fully visible. This matches `_unit_tree_node.html`, which does the
same, and is accepted; the design pass must not "fix" it.

**Accepted limitation, stated rather than papered over:** on a touch device the collapsed `…`
is not itself interactive and reveals nothing on tap. This is deliberate. Making it a
`<button>`/`<details>` would break the zero-JS decision (decision 4) and duplicate a disclosure the
Contents drawer already provides one tap away. The comment at `templates/courses/_unit_tree_node.html`
records the same reasoning for the tree's own labels: *"Touch has no hover, so the drawer wraps
these labels instead."* The breadcrumb is an orientation strip, not the system of record for the
chain — the drawer is.

**The drawer fallback is weaker than it first sounds, and the spec says so rather than overselling
it.** The Contents trigger only appears once `unit_nav.js` removes its `[hidden]`, and the inline
tree is `display: none` below 640px — so a narrow viewport *with JS disabled* has no route to the
mid titles at all. This is accepted for two reasons: it matches the pre-existing behaviour of the
tree itself (that combination already hid the chain before this change), and the breadcrumb strictly
improves on the status quo even in that case, since it still shows `Course › <deepest group>` where
previously there was nothing. It is recorded here so a future reader does not mistake it for an
oversight.

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
`_stamp_current_chain` call. **Its docstring must be updated too** — it currently documents the
exact return shape (`Returns {tree, current_pk, prev, next, part_progress, course_progress}`), and
leaving that stale would make the file contradict itself.

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

**Every separator lives inside the `<li>` it introduces.** An `<ol>`'s content model permits only
`<li>` (and script-supporting) children, so sibling `<span>` separators would be non-conforming
*and* would undermine the `role="list"` added below, whose owned children must all be `listitem`.
Nesting the separator also makes the pairing rule structural: a hidden crumb takes its separator
with it because the separator *is* part of it. There is no `--mid`/`--leaf` separator modifier and
no convention to hand-maintain.

Each `<li>` is itself a flex row of an optional separator plus a label; the label — not the `<li>` —
carries the clipping.

```django
{% load i18n %}{% get_current_language as LANGUAGE_CODE %}
<nav class="unit-crumbs" aria-label="{% trans 'Breadcrumb' %}" lang="{{ LANGUAGE_CODE }}">
  <ol class="unit-crumbs__list" role="list">
    <li class="unit-crumbs__item unit-crumbs__item--course" role="listitem"
        lang="{{ course.language }}" title="{{ course.title }}">
      <a class="unit-crumbs__label" href="{% url 'courses:course_outline' slug=course.slug %}">{{ course.title }}</a>
    </li>

    {% if unit_nav.ancestors|length > 1 %}
      <li class="unit-crumbs__item unit-crumbs__item--ellipsis" role="listitem"
          lang="{{ course.language }}" title="{{ unit_nav.hidden_path }}">
        <span class="unit-crumbs__sep" aria-hidden="true">›</span>
        <span class="unit-crumbs__label">…<span class="visually-hidden">{{ unit_nav.hidden_path }}</span></span>
      </li>
    {% endif %}

    {% for a in unit_nav.ancestors %}
      <li class="unit-crumbs__item unit-crumbs__item--{% if forloop.last %}leaf{% else %}mid{% endif %}"
          role="listitem" lang="{{ course.language }}" title="{{ a.title }}">
        <span class="unit-crumbs__sep" aria-hidden="true">›</span>
        <span class="unit-crumbs__label">{{ a.title }}</span>
      </li>
    {% endfor %}
  </ol>
</nav>
```

Rules this markup encodes, each with its reason:

- **Separators are real elements**, not CSS `::before`: generated content is not selectable, is not
  copied with the text, and is read inconsistently by assistive tech. This is the *structural* point
  `.editor-crumb` also follows — note that it deviates in two details on purpose (it uses `/`, and
  it has no `aria-hidden`), so neither should be "fixed" to match the other.
  *Accepted wrinkle:* because spacing comes from `gap` and the template's inter-element whitespace
  is whitespace-only text between flex items (not rendered), copying the strip yields
  `Algebra 2›Sequences›Series` without spaces. Padding the span with `&nbsp;` would fix the copy at
  the cost of double-spacing against the gap; copy fidelity is not worth that, so it is recorded and
  left.
- **Each `<li>` carries `role="listitem"`** to match the container's `role="list"`. WebKit drops
  list semantics under `list-style: none`, which is why the container role is there at all; changing
  an `<li>`'s `display` away from `list-item` — which §4 does, to `flex` — is a second reported
  trigger for losing the implicit child role. Restating both roles is the belt-and-braces
  convention and costs one attribute; omitting the child role would leave a `role="list"` whose
  owned children are not guaranteed `listitem`.
- **The course crumb has no separator**; every subsequent crumb has exactly one, leading. So the
  rendered glyph count is always `visible items − 1`, which is what the e2e asserts.
- **The `…` item is emitted on the structural condition `ancestors|length > 1`, not on
  `hidden_path` being truthy.** The CSS hides mids structurally (`len(ancestors) - 1` items carry
  `--mid`), so the emission test must be structural too. Keying it on the derived string would
  desynchronise the two whenever the string is empty but a mid still exists — a course whose only
  mid ancestor has a blank `title` yields `hidden_path == ""` with two ancestors, and the `…` would
  vanish while the CSS still hid a crumb, silently breaking §1's invariant 5. A 0- or 1-ancestor
  course still never emits it, which is the common case this rule also has to get right.
- **The `…` sits immediately after the course crumb** — the position the mid crumbs it replaces
  would occupy.
- **`title` goes on the `<li>`, never on the `<a>`.** A `title` on the link would join its
  accessible name and be announced twice ("Algebra 2, Algebra 2"); on a non-interactive `<li>` it
  still produces the hover tooltip without touching any accessible name.
- **The `…` is not `aria-hidden`.** At the widths where it renders, the mid crumbs are
  `display: none` and therefore *absent* from the accessibility tree — so the `…` is the only
  carrier of that text, and it holds it in a `visually-hidden` span (the utility already exists in
  `core/static/core/css/app.css`).
- **No `aria-current`, intentionally.** The conventional breadcrumb ends on the current page marked
  `aria-current="page"`; this one ends on an ancestor because of decision 1. The current page is the
  `<h1>` immediately below. Recording this so it does not read as an oversight next to
  `_unit_tree_node.html`, which does use `aria-current="page"`.
- `Breadcrumb` is the only new translatable string.

**`lang` is set in two directions, deliberately.** The include sits inside
`<article … lang="{{ course.language }}">`, so *author content* inherits the course language for
free. But `aria-label="{% trans 'Breadcrumb' %}"` is *interface* text in the active UI language, and
it would inherit the course language too — announcing a Polish label with an English voice on an
`en` course. So the `<nav>` carries `lang="{{ LANGUAGE_CODE }}"` (via
`{% get_current_language %}`, the pattern `base.html` already uses) and each **`<li>`** carries
`lang="{{ course.language }}"` back. This mirrors what `_unit_tree_node.html` does for the same
reason.

The attribute sits on the `<li>` rather than the label deliberately: the `title` attributes are
author content too — they hold the very same node titles — and AT can expose them as descriptions.
Putting `lang` on the `<li>` covers the `title`, the label, and the ellipsis's `visually-hidden`
span in one place, all by inheritance. On the label alone it would have covered only the visible
text and left the tooltips announced in the wrong language.

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

A new `.unit-crumbs` block adjacent to the existing `.lesson-unit__head` rules, plus **two new media
queries authored alongside it** — one `screen` collapse query and one `print` query. Neither is
folded into an existing block: `courses.css` has three `@media (max-width: 640px)` blocks (the
unit-shell one contains `.unit-shell { display: block }` / `.unit-tree { display: none }`) and a
`@media print` block at `courses.css:1238` whose every rule is `.el--tabs`-scoped under a
tabs-specific comment. Dropping generic crumb rules into any of them would file them under a comment
that does not describe them. The tabs print block is cited below as *precedent*, not reused.

**Minimum supported viewport: 360px.** Two claims below rest on this number, and the e2e asserts at
exactly that width.

Mechanism:

- `.unit-crumbs__list` — `display: flex; flex-wrap: nowrap; align-items: center; overflow: hidden;`
  with `list-style: none` and margin/padding zeroed. `gap` supplies **all** spacing between crumbs,
  rather than margins, because a `display: none` item takes its gap with it whereas a margin-based
  version leaves a dangling space.
  `overflow: hidden` is the backstop keeping a worst case from pushing the whole page into
  horizontal scroll. It does not mask the e2e guard: `scrollWidth` still reports content width.
- `.unit-crumbs__item` — `display: flex; align-items: center; min-width: 0;` plus its own internal
  `gap` between separator and label. **`min-width: 0` here is the load-bearing declaration** — the
  item is a flex child with the default `overflow: visible`, so without it its automatic minimum
  size resolves to the full nowrap width of sep + label and the strip overflows instead of clipping.
- `.unit-crumbs__label` — `overflow: hidden; text-overflow: ellipsis; white-space: nowrap;`.
  **This is where clipping lives**, not on the `<li>`. It carries **no `min-width` of any kind**:
  per CSS Flexbox §4.5 a flex item whose computed main-axis overflow is not `visible` already has an
  automatic minimum size of zero, so `min-width: 0` here is a no-op (do not mistake it for the
  guard — see the e2e falsifying mutation in §Testing), and a `min-width` *floor* here is actively
  wrong (see the shrink-order section below).
- `.unit-crumbs__sep` — `flex: 0 0 auto` so separators never shrink or clip.

**`align-items: center`, not `baseline`.** A flex item with `overflow: hidden` is a scroll container
and exposes no text baseline, so the UA synthesizes one from its border box. Baseline-aligning the
plain-text separator against that synthesized edge shifts the label a few pixels off its own
separator, at both levels of nesting. Centring sidesteps it. If the design pass wants baseline
alignment it must *measure* sep/label alignment at both viewports, not assume it.

**Spacing is one quantity, not two.** The rendered sequence is
`label — list-gap — sep — item-gap — label`, so the list gap and the item gap must resolve to the
same value or the separator sits visibly off-centre between its neighbours. Express both from a
single custom property (e.g. `--crumb-gap`) so the design pass has one knob, not two.

**Shrink order, pinned explicitly** — this is the whole "pinned ends, squeezed middle" mechanic and
the order matters at every width.

**The floors go on the `<li>`, sized to include the separator and the internal gap.** This is
load-bearing and was got wrong twice, so the reasoning is recorded. The `<li>` is the flex item the
*list* shrinks; a floor on `.unit-crumbs__label` is a floor on a descendant, which flexbox does not
consult when sizing the `<li>`. With `min-width: 0` on the item and the floor on the label, the item
collapses toward a few pixels while the label refuses to shrink and simply **overflows its own
`<li>`**, painting over the neighbouring crumb — and the overflowing text is then outside the
element carrying the `title`, so the tooltip disclosure breaks too. The earlier objection to
item-level floors (a bare 4ch item floor leaves ~2ch for text once the separator is inside it) is a
*sizing* problem, answered by sizing the floor to cover the separator, not by relocating it:

| Crumb | `flex-shrink` (item) | `min-width` floor (item) |
|---|---|---|
| `--mid` | ~200 | `calc(4ch + 1em + var(--crumb-gap))` |
| `--course` | 3 | `calc(6ch + 1em + var(--crumb-gap))` |
| `--leaf` | 1 | `calc(6ch + 1em + var(--crumb-gap))` |

(The `1em` term is the separator's own advance width; `--course` has no separator, so its floor may
drop that term. Treat the ch/em values as starting points to verify by measurement, not as
constants.) `.unit-crumbs__label` carries **no** `min-width` at all — `overflow: hidden` already
zeroes its automatic minimum size, and adding one there is what caused the overflow above.

Mids absorb essentially all of any deficit first; then the course crumb; the leaf last.

**Source-order rule.** With the floors back on the item, `.unit-crumbs__item { min-width: 0 }` and
`.unit-crumbs__item--mid { min-width: … }` target the same element at identical specificity, so the
cascade is decided by source order alone: every modifier rule must appear **after** the base
`.unit-crumbs__item` rule in the file, or `min-width: 0` silently wins and the floors never apply.

**When even the floors do not fit** — i.e. when the container is narrower than the summed floors
plus gaps — the list's `overflow: hidden` clips at the inline-end, so the leaf is what gets cut. The
threshold is exactly that sum; at the starting values above it lands well under the 360px minimum
supported viewport, but it is a computed consequence of whatever the floors end up being, not an
independent number to quote. The e2e asserts no clipping occurs at 360px, which is the check that
actually matters.

- `.unit-crumbs__item--ellipsis` — `display: none` by default; `flex: 0 0 auto` (it is one glyph and
  must never shrink).
- **Collapse query — `@media screen and (max-width: 52rem)`:** `--mid` items go `display: none`;
  `--ellipsis` goes `display: flex` (the value is immaterial since a flex container blockifies its
  children, but naming it stops it being re-litigated).
- **Print query — a new `@media print` block colocated with the `.unit-crumbs` rules:** the collapse
  never applies (it is `screen`-scoped), and `.unit-crumbs__list` gets `flex-wrap: wrap` with
  `.unit-crumbs__label { overflow: visible; white-space: normal; text-overflow: clip; }` so a long
  path wraps instead of being clipped. Precedent for taking print seriously: the `.el--tabs` print
  block at `courses.css:1238` exists because a screen-only hiding rule once silently destroyed
  printed content.

**Why 52rem and not the shell's 640px.** The content column is *narrowest just above* the shell
breakpoint: at 641px the 14rem rail is still present, leaving ~417px, whereas at 360px the rail is
gone and the column is ~328px of a much simpler layout. Collapsing at the shell breakpoint would
leave the worst case uncollapsed.

**Invariants the design pass may not break.** Colour, size, weight, glyph and spacing are free. The
breakpoint is **tunable but bounded**: it must sit strictly between 360px and 1280px, because the
e2e pins the collapsed state at 360px and the expanded state at 1280px. Those two widths are the
contract; 52rem is just a value inside them.

1. On screen, the strip is exactly one line at every viewport width ≥ 360px. (Print deliberately
   wraps.)
2. It never causes page-level horizontal scroll.
3. A rendered separator always has rendered text on both sides — no orphaned glyphs.
4. At 360px, every crumb's label is **contained within its own `<li>`**
   (`label.clientWidth <= li.clientWidth`) and no two adjacent crumbs' bounding boxes overlap.
   Stated against the *item*, not the label: a floor declared on the label is satisfied by
   construction whether or not the label fits, so asserting on the label would pass in exactly the
   broken state described in the shrink-order section. Overlap is the falsifying mutation.
5. The set of crumbs hidden by the collapse query is exactly the set `hidden_path` names.
6. The separator glyph matches `CRUMB_SEP`.

Baseline styling: `--text-tertiary`, ~0.85rem, `--space-3` bottom margin, course link inheriting the
muted colour rather than the default link blue.

**Focus ring.** The course crumb's `<a>` **is** `.unit-crumbs__label` — the label is the focusable
element, not an ancestor of it, and an element's own `overflow` never clips its own outline. So
exactly **one** ancestor clips the ring: `.unit-crumbs__list`, against which the first crumb sits
flush. The fix is inline padding on `.unit-crumbs__list` sized to the ring (overflow clips at the
padding box, so the padding buys the room), with a compensating negative inline margin if the crumb
must stay flush with the `<h1>`. **Do not relax `overflow` on `.unit-crumbs__label` as part of this
fix** — that is the declaration the entire shrink mechanic depends on. Keyboard focus on the course
link, **checked at the left edge specifically**, is an explicit item on the design-pass QA checklist.

**Focus scrolling.** `overflow: hidden` also makes the list a programmatically scrollable container.
If the focused link's border box ever exceeded the visible area, the UA would scroll the list to
reveal it — and with no scrollbar and no keyboard scroll affordance the strip would stay shifted,
hiding the leaf, until re-layout. It does not happen here because the label's *box* always fits (it
is the text that ellipses, not the box), but that is a property to confirm rather than assume: the
QA checklist item asserts `list.scrollLeft === 0` after focusing the course link at 360px.

## Data flow

```
lesson_unit           ─→ full_lesson_render_context ─┐
check_answer          ─→ full_lesson_render_context ─┤
notes (no-JS 422)     ─→ full_lesson_render_context ─┤
                                                     ├─→ build_unit_nav(course, user, unit)
quiz_unit             ─→ ctx["unit_nav"] = ──────────┤
_quiz_render_feedback ─→ ctx["unit_nav"] = ──────────┘
                                                       ├─ build_outline(course, user)         → tree             (2 queries, existing)
                                                       ├─ _stamp_current_chain(tree, unit.pk) → contains_current (0 queries, existing)
                                                       └─ _current_ancestors(tree)            → ancestors        (0 queries, NEW)
                                                            └─ hidden_path = CRUMB_SEP.join(a.title for a in ancestors[:-1])

templates: lesson_unit.html / quiz_unit.html
  └─ _unit_shell.html
       └─ _lesson_article.html / _quiz_article.html
            └─ _unit_crumbs.html   ← reads course.*, unit_nav.ancestors, unit_nav.hidden_path
```

**Five render sites, and the asymmetry between them.** The three lesson sites are genuinely
single-sourced — all go through `full_lesson_render_context`, which sets `unit_nav` — so one test
covers them. The quiz side is **not**: `build_quiz_context` does not call `build_unit_nav`;
`quiz_unit` and `_quiz_render_feedback` each set `ctx["unit_nav"]` themselves. Hoisting it into
`build_quiz_context` is out of scope (it would alter a context builder shared with other callers),
so the mitigation is coverage: §Testing requires an assertion at **both** quiz sites, and the
graceful-degrade row in §Error handling covers a future third site that forgets.

The partial reads exactly three context values: `course`, `unit_nav.ancestors`,
`unit_nav.hidden_path`. It never touches `unit`.

## Error handling

There is no user input and no write path here; the failure modes are all "missing or unusual data".

| Situation | Behaviour |
|---|---|
| **Flat course, 0 ancestors** | Render the `<nav>` with the course crumb alone. It is still a useful top-of-page route back to the contents. Do **not** suppress the whole strip. `hidden_path == ""`, so no `…` item is emitted. |
| **1 ancestor** | `Course › Part`. `hidden_path == ""` → no `…` item, and nothing is ever hidden by the collapse query. |
| **Skipped levels** (a unit whose only ancestor is a part, in a course flagged "Full") | Renders `Course › Part`. This is exactly why the chain comes from the real `parent` links and never from `Course.uses_parts/uses_chapters/uses_sections` — those flags are authoring policy, not a guarantee about existing rows. |
| **`unit_nav` absent from the context** on some re-render path | Django resolves the missing variable to empty: the `{% for %}` yields nothing, `hidden_path` is empty, and the course crumb still renders. Degrades; does not raise. |
| **`current_pk` not present in the tree** | `_current_ancestors` returns `[]` → course crumb only. A legitimate empty result, not an error. |
| **Unstamped tree passed to `_current_ancestors`** | `KeyError`, deliberately — matches `_top_level_part`'s existing contract, so a future caller that forgets to stamp fails loudly instead of silently rendering an empty crumb. |
| **Blank ancestor title** | The crumb renders empty and `hidden_path` keeps its slot, so three ancestors with a blank first title give `" › Chapter"` — a tooltip with a leading separator. Accepted, not filtered: a blank title is already a content defect the author should fix, and filtering blanks out of the join would desynchronise `hidden_path` from the §Testing e2e assertion that joins every `--mid` title verbatim. Emission of the `…` is unaffected because it is keyed on ancestor *count*, not on the string. |
| **Pathological title lengths** (`ContentNode.title` allows 200 chars) | Labels clip with an ellipsis in the §4 shrink order — mids first, then the course crumb, then the leaf. Below the collapse breakpoint the mids are gone entirely and only course + leaf compete. The strip stays one line and the page never scrolls horizontally. |

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
7. Crumb renders on the lesson GET and the quiz GET, and on **both** no-JS POST re-renders. Assert
   the ancestors are present, not merely that the page returns 200. Required fixture state, because
   these are easy to set up wrongly:
   - *quiz GET* — the student must have **no submission or an `IN_PROGRESS` one**; `quiz_unit`
     redirects a `SUBMITTED` quiz to `courses:quiz_results`, which is a non-goal.
   - *`quiz_answer` POST* — the student must be **enrolled** (a previewer gets `PermissionDenied`),
     the `QuestionResponse` must be **unlocked with attempts remaining**, and the body must carry a
     **non-empty** answer, or the view takes its validation branch. Omit the fragment header.
   - *`check_answer` POST* — omit the fragment header so the full page re-renders.
   - The three lesson sites (`lesson_unit`, `check_answer`, the notes no-JS 422) are collapsed into
     one assertion because `full_lesson_render_context` single-sources them.
8. The course crumb is an `<a href>` to `courses:course_outline`.
9. **No `<a>` inside any group crumb** — the "plain text" decision, guarded.
10. Every `<li>` after the first contains exactly one `.unit-crumbs__sep`, and the first contains
    none — the structural pairing rule from §2.
11. Flat course renders the `<nav>` with the course crumb and **no** `…` item.
12. **Ellipsis positive case** (≥2 ancestors): the `--ellipsis` `<li>` is emitted, its `title`
    equals `hidden_path`, and it contains a `.visually-hidden` descendant whose text is
    `hidden_path`. That span is the *sole* accessibility carrier behind §2's "not `aria-hidden`"
    rule, and without this test deleting it would ship green. Falsifying mutation: delete the span.
13. **Blank mid title:** a course with exactly two ancestors where the first has `title=""` still
    emits the `…` item — the structural-gating rule from §2. Falsifying mutation: change the
    template condition back to `{% if unit_nav.hidden_path %}`.
14. **Non-goal guard:** a GET for a **SUBMITTED** quiz (which redirects to `courses:quiz_results`)
    yields a final page containing **no** `unit-crumbs` markup. Pins the stated non-goal and doubles
    as a regression guard on the redirect that test 7's quiz-GET fixture note depends on.
15. **`lang` split:** on a course whose `language` differs from the active UI language, assert
    `nav.unit-crumbs[lang]` equals the active `LANGUAGE_CODE` and every `li.unit-crumbs__item[lang]`
    equals `course.language`. The pair is subtle and a "simplify the template" refactor would drop
    one silently — the failure is inaudible in CI and invisible in screenshots. Falsifying mutation:
    delete either attribute.
16. **Placement:** the crumb `<nav>` is a descendant of `article.lesson` and of `article.quiz`
    respectively. §3's whole argument for editing two files rather than one is padding and `lang`
    inheritance from the article; without this, a future "de-duplicate the include" move into
    `_unit_shell.html` keeps every other test green while breaking both. Falsifying mutation: move
    the include into `_unit_shell.html`.
17. `test_build_unit_nav_adds_no_queries` (already present) still passes — the zero-query guarantee.

### Falsification — mandatory

Per the recorded lesson in `falsify-tests-not-run-them`: for **each** test above, delete or invert
the thing it guards and confirm the test goes **RED** before keeping it. A test that cannot be made
to fail is not a test. The plan must name the falsifying mutation per test.

### e2e — `tests/test_e2e_unit_crumbs.py`

**Per-module boilerplate this file must define for itself** — none of it is inherited, and omitting
it fails at import or raises `SynchronousOnlyOperation`:

- `pytestmark = pytest.mark.e2e`
- the session-scoped autouse `_allow_async_unsafe` fixture setting `DJANGO_ALLOW_ASYNC_UNSAFE` —
  it lives module-locally in all ~35 existing `tests/test_e2e_*.py` files, **not** in any `conftest.py`
- `@pytest.mark.django_db(transaction=True)` on every test
- a `_make_student` helper and the `_login(page, live_server, username)` helper (import from
  `tests/test_e2e_unit_nav.py` or copy)

**Use `browser` + `live_server`, not the `page` fixture.** `pytest-playwright` does supply `page`,
`context` and `browser` — but the repo convention is `browser` + an explicit
`ctx = browser.new_context(viewport={...})` then `ctx.new_page()`, closing the context afterwards.
Follow it here for a concrete reason: the viewport must be fixed at context creation, and that
per-context viewport is how the two widths are obtained. Do not use `page.set_viewport_size()`.

**Seeding needs a new local helper, not an extension of `_seed_nav_course`.** That helper builds a
single `kind="part"` with unit children, so it can never yield three ancestors no matter what titles
it is given. The crumbs helper must build `part → chapter → section → unit` and pass an explicit
`CourseFactory(title=…)`, since the factory's default title is a `factory.Sequence`. Give the helper
explicit **`title_len`** and **`depth`** parameters — the assertions below need both a long-title
fixture (~60 chars at every level, depth 3) and a short-title one, and "seed long titles" alone
cannot serve both. Run focused and in the foreground — a background `-m e2e` sweep spawns runaway
browsers.

**Three viewports, not two.** 1280px and 360px alone never exercise the state where mids are
*visible but squeezed* — at 360px they are hidden and at 1280px there is room to spare. By §4's own
argument the content column is narrowest while the rail is still present, so the worst case for
invariant 3 and for label containment sits **just above the collapse breakpoint** (~833px at the
starting 52rem, where the column is roughly 561px for four crumbs). Derive the third width from the
declared breakpoint rather than hard-coding it, so tuning the breakpoint moves the test with it.

Assertions:

- **The real guard, at all three widths:** `.unit-crumbs__list` `scrollWidth <= clientWidth`, and
  `document.documentElement.scrollWidth <= document.documentElement.clientWidth` (**not**
  `window.innerWidth`, which includes the classic scrollbar gutter and would tolerate ~15px of real
  overflow). **Falsifying mutation: delete
  `min-width: 0` from `.unit-crumbs__item`** — the item is a flex child with `overflow: visible`, so
  its automatic minimum size snaps back to the full nowrap width of sep + label, the row refuses to
  shrink, and the first assertion goes red. Do **not** try to falsify by touching
  `.unit-crumbs__label`: `overflow: hidden` already zeroes that element's automatic minimum size, so
  removing a `min-width: 0` there changes nothing and the test stays green — which would look like a
  vacuous test rather than a wrong mutation. (Removing the label's `overflow: hidden` also works as
  a mutation, but it changes two behaviours at once.) The height check below does **not** catch any
  of this, which is why it is not the primary guard.
- Secondary, one-line check: compare the list's height to a single crumb's rather than to a guessed
  pixel value — `list.offsetHeight <= 1.5 * item.offsetHeight` for any `.unit-crumbs__item`. The
  focus-ring fix adds inline padding to the same element, so a hard-coded number or a raw
  `line-height` comparison would be brittle. Cheap, and catches an accidental `flex-wrap: wrap`.
- **Just above the breakpoint** (the third width), where mids are visible and squeezed: every
  `--mid` label has `clientWidth > 0`, every label is contained in its `<li>`
  (`label.clientWidth <= li.clientWidth`), and no two adjacent `<li>` bounding boxes overlap. This
  is the assertion that catches a floor declared in the wrong place — see §4's shrink-order section.
- At 360px: no `--mid` item is visible, the `…` **is** visible, and the count of **visible**
  `.unit-crumbs__sep` elements equals the count of visible `.unit-crumbs__item` minus one — the
  assertion that actually catches an orphaned separator.
- At 360px: read `get_attribute("title")` from each `li.unit-crumbs__item--mid` **in DOM order**
  (that selector only — separators and the leaf must not be swept in) and assert
  `CRUMB_SEP.join(those) == ` the `…` item's `title`. This is the guard on the §1 invariant coupling
  `hidden_path` to the collapse query.
- At 1280px: `--ellipsis` has zero client rects, and every `--mid` and `--leaf` has
  `clientWidth > 0`. Stated mechanically because "with a short path" was ambiguous — long titles are
  clipped, not hidden, so the assertion holds for either fixture and the short-title fixture is not
  what makes it meaningful.
- **Print**, via `page.emulate_media(media="print")` at a narrow width: every `--mid` is visible,
  the `--ellipsis` is not, `.unit-crumbs__list` `scrollWidth <= clientWidth`, and `offsetHeight`
  exceeds one line — proving it wrapped rather than clipped. §Disclosure promises a printout shows
  the complete path and §4 cites the `.el--tabs` block as precedent for a screen-only rule silently
  destroying printed content; without this the spec ships that exact risk untested. Falsifying
  mutation: remove `screen and` from the collapse query.
- Screenshots at all three widths × light and dark, reviewed per `verify-ui-with-screenshots`. Force
  dark with `data-theme="dark"` on `documentElement`.

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
link at the strip's left edge. This is an explicit user request and an explicit deliverable of this
work, not an optional polish step — a previous pipeline run shipped unpolished UI precisely by
treating it as optional. The design pass may freely change the visual treatment; it may not break
the six invariants listed in §4.
