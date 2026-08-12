# Student-facing unit kind markers

## Purpose

Students cannot tell one unit from another. In the course outline and in the contents rail, a
quiz, an obligatory lesson and a non-obligatory lesson render identically — title, optional `✓`,
tags, note badge — so a student has no way to know that a row is a test they are about to sit, or
that a row is extra material they are not required to finish.

Both facts are already stored. `ContentNode.unit_type` is `lesson | quiz` and
`ContentNode.obligatory` is a boolean, and the teacher-facing builder already renders both
(`templates/courses/manage/_tree_node.html` draws `L`/`Q` badges and `icm--req`/`icm--opt`
glyphs). Only the student surfaces are silent. This design makes them speak.

**No model or migration change.** `unit_type` and `obligatory` exist and are already authored; this
is a presentation change over data the author already controls.

### The state model: one axis, not two

For a student the two stored flags collapse to a single three-state axis:

| State | Condition | Marker |
| --- | --- | --- |
| Required lesson | `unit_type == lesson and obligatory` | **none** (the unmarked default) |
| Additional | `unit_type == lesson and not obligatory` | `Additional` |
| Quiz | `unit_type == quiz` | `Quiz` |

A quiz is **always** just "quiz". Its stored `obligatory` flag is deliberately ignored, because it
already has no student-visible consequence: `courses/rollups.py::is_obligatory_lesson` requires
`unit_type == LESSON`, so a quiz never contributes to `required_total` whatever its flag says.
Surfacing an "optional quiz" state would advertise a distinction that changes nothing about a
student's progress.

**Required is unmarked.** It is by far the most common state, and marking it would put a chip on
nearly every row in the outline, which is the same undifferentiated wall the feature exists to
break up.

### Out of scope

- The prev/next footer navigation (`templates/courses/_unit_footer.html`).
- The "My results" page — quizzes only by construction, so a quiz marker would be noise.
- Every teacher-facing surface; the builder tree already distinguishes these states.
- Any model, migration, or `FORMAT_VERSION` change.

## Architecture / components

### 1. `unit_marker(node)` — the single source of truth

Added to `courses/rollups.py`, immediately beside the existing `is_obligatory_lesson` and
`is_quiz_unit`, which is where this vocabulary already lives.

```python
def unit_marker(node):
    """'quiz' | 'additional' | '' — the ONE student-facing kind rule.

    '' for a required lesson (the unmarked default) AND for any non-unit node.
    A quiz is never 'additional': is_obligatory_lesson already excludes quizzes
    from required_total, so `obligatory` on a quiz node has no student meaning.
    """
```

Implemented in terms of the two existing predicates rather than by re-testing `kind` /
`unit_type` / `obligatory` inline, so that a future change to what counts as a quiz or an
obligatory lesson cannot make the markers disagree with the rollups they are supposed to explain.

### 2. Exposure to templates: a filter on the node

Registered as a `@register.filter` in `courses/templatetags/courses_extras.py` (which already hosts
`strip_math_delimiters`, `dictkey`, `quiz_answer_url`).

**A filter on the node, not a key on the `build_outline` item dict.** This is load-bearing.
`_outline_node.html` and `_unit_tree_node.html` each render a `build_outline` item dict and could
read a dict key, but `_lesson_article.html` and `_quiz_article.html` receive only a bare `unit`
`ContentNode` with no dict anywhere in scope. A dict key would therefore cover two of the three
surfaces and force a second rule for the third — two rules that can drift. A node filter covers all
three from one expression.

### 3. Two shared partials

So the glyphs and the translatable strings each exist exactly once:

- `templates/courses/_unit_kind_chip.html` — the text chip. `.badge` (the existing neutral
  `--surface-sunken` / `--text-secondary` pill from `app.css:115`).
- `templates/courses/_unit_kind_icon.html` — the inline SVG. `class="icon"`, which already supplies
  `width/height: 1em`, `flex: none`, `fill: none`, `stroke: currentColor`, `stroke-width: 1.8`
  (`app.css:105-113`).

Both render **nothing at all** when `unit_marker` is `''`. Each takes the node and does its own
`unit_marker` call, so no call site can pass a state the partial did not compute.

### 4. The three surfaces

**Outline page** — `templates/courses/_outline_node.html`.

The chip goes **inside** the `<a class="outline-unit">`, directly after `.outline-unit__title` and
before the `✓` badge. Inside the anchor on purpose: the `✓` already is, and placing the chip there
makes the state part of the link's accessible name, so a screen-reader user tabbing through links
hears "Extra practice, Additional" rather than a bare title with a detached span they never reach.
The `✓` keeps its `margin-left: auto` (`app.css:559`), so a row reads:

```
Extra practice  [Additional]  ··············  ✓
```

The kind chip sits inside the anchor while the tag chips and note badge stay outside it, as today.

**Contents rail and mobile drawer** — `templates/courses/_unit_tree_node.html`.

One file serves both: `_unit_tree.html` renders it into the rail and `_unit_shell.html` renders it
again into `.unit-drawer__list`, so both surfaces are covered by a single edit.

The icon is **trailing** — after `.unit-tree__label`, last child of `.unit-tree__unit`. Two reasons,
both structural:

1. The `✓` already **leads**. `courses.css:788` sets `.unit-tree__check { margin-left: 0 }`
   specifically to cancel `.badge--done`'s `margin-left: auto` so the tick leads in a unit row. A
   second leading glyph would make every completed *additional* unit begin with two marks.
2. Trailing puts the kind icons in the same right-hand gutter that `.unit-tree__count` and
   `.unit-tree__groupcheck` already occupy on group rows, so the rail gains one marker column
   rather than a second, competing one.

`.unit-tree__label` is `min-width: 0; overflow: hidden; text-overflow: ellipsis`
(`courses.css:789`) and `.icon` is already `flex: none`, so the label absorbs the ~1em the icon
takes with no new CSS and no layout risk. No new rule is required for the icon itself; only a small
`.unit-tree__kind` colour/opacity rule if the inherited row colour proves too loud (see below).

**Unit page** — `templates/courses/_lesson_article.html` and `templates/courses/_quiz_article.html`.

The chip becomes a flex item in `.lesson-unit__head`, after the `<h1>` and **left of** the done
pill.

`_lesson_article.html` already has that head row, so it gains one include. `_quiz_article.html`
currently has a bare `<h1 class="lesson-unit__title">` with no head wrapper, so it gains the same
`.lesson-unit__head` div. That reuse is free rather than risky, and the CSS already proves it:

- `.lesson-unit__head .lesson-unit__title { margin: 0 }` (`courses.css:834`) and
  `.quiz .lesson-unit__title { margin-bottom: var(--space-6) }` (`courses.css:293`) have **equal
  specificity** (0,2,0), so source order decides and `:834` wins. `.lesson-unit__head` then supplies
  the identical `margin-bottom: var(--space-6)` (`courses.css:829`). Net vertical rhythm is
  unchanged.
- The collapsed-TOC width allow-list (`courses.css:~1097`) lists `.lesson-unit__title` and
  **deliberately excludes** `.lesson-unit__head` — the file's own comment at `:1076` records that
  `.lesson-unit__head` was taken off that list because it is chrome drawn around the cards. So the
  heading keeps its prose measure while the head row widens, and **no allow-list edit is needed**.
- The mobile query at `courses.css:985` already gives `.lesson-unit__title` `flex-basis: 100%` and
  sets the head `flex-wrap: wrap`, so on a phone the chip drops to the row below the title rather
  than squeezing it.

**Hard constraint:** the chip must never be placed **inside** `<h1 data-math-title>`. `math.js`
typesets that element's contents, so a chip in there would enter the maths-title scan.

### 5. The glyphs

Both are monochrome line SVGs on the `viewBox="0 0 24 24"` grid, per the project icon convention
(`currentColor`, never emoji).

- **Quiz** — a `?` inside a circle. Chosen over a clipboard/checklist, which turns to mush at the
  ~1em the rail renders. The standard objection is that a circled `?` reads as "help"; there is no
  help affordance anywhere in the contents rail, the drawer, or an outline row, so the collision is
  theoretical on these three surfaces.
- **Additional** — a `+` inside a circle, deliberately echoing the `+{{ additional_done }}
  additional` rollup that already sits on the group row directly above these units
  (`_outline_node.html:23`). Same shape family as the quiz mark, so the two read as one system.

**No hue on either.** The rail already spends `--success` on `✓` and `--primary` on the active row;
two further hues in a 14rem column would compete with the two signals that matter most. Shape plus
the accessible name carries the distinction, which is also the colour-blind-safe answer. If the
icon at the inherited row colour proves too loud against the title, the only permitted adjustment is
a quieter neutral — and it must be checked against the note that `--text-tertiary` fails AA at body
size, so any such rule must be verified rather than assumed (icons are graphical objects at a 3:1
bar, but the check must actually be made, not waved through).

### 6. Wording and accessibility

The non-obligatory state is worded **"Additional"**, not "Optional". `_outline_node.html:23`
already renders `+N additional` on the group row and `build_outline` calls the field
`additional_done`; using the same word means the counter and the chips beneath it name the same
set, and a student can connect the two. "Optional" would leave one concept worded twice with
neither pointing at the other.

Two msgids — `Quiz` and `Additional` — used by **both** partials:

- The chip renders the string as visible text.
- The icon carries it as a `title=` attribute **plus** a `.visually-hidden` span, giving it a real
  accessible name and a hover tooltip. That pairing is what removes the need for a legend anywhere.
  The `<svg>` itself is `aria-hidden="true"`.

`Quiz` is very likely already in the catalog from the editor's type toggle
(`manage/editor/editor.html:91`); it must be **reused**, not duplicated.

Polish translations and the `.po` → `.mo` regeneration land in the same change. `makemessages` can
fuzzy-prefill a wrong translation from a near-neighbour msgid, so any fuzzy entry on these two must
be inspected and cleared (which is two deletions — the `#, fuzzy` line and the wrong `msgstr`),
never accepted as-is.

## Data flow

No new queries and no change to any existing query.

```
ContentNode (unit_type, obligatory)  ── already loaded ──┐
                                                         │
  build_outline() ──> item dicts ──> _outline_node.html ─┤
                                     _unit_tree_node.html┤──> unit_marker(node)
                                                         │       │
  view context "unit" (bare node) ──> _lesson_article ───┤       ├─> '' ......... render nothing
                                      _quiz_article ─────┘       ├─> 'quiz' ..... Quiz chip / icon
                                                                 └─> 'additional' Additional chip / icon
```

`unit_marker` is a pure function of three already-loaded fields on a node the template already
holds. Every surface reads it through the same filter, so the three surfaces cannot disagree, and
none of them triggers a database round-trip. `build_outline`, `build_unit_nav`, and the rollups are
untouched.

The `drafts` / publish filtering is unaffected: a unit that `unit_is_visible` excludes never reaches
a template, so it has no marker to render.

## Error handling

There is no user input and no failure mode in the ordinary sense. What matters is that the
degenerate cases render sanely:

- **Non-unit node** (part / chapter / section) — `unit_marker` returns `''`. Group rows in the
  outline and `<summary>` rows in the rail get no marker, and the partials render nothing. This is
  reachable: `_outline_node.html` and `_unit_tree_node.html` both recurse over container nodes.
- **Unit with `unit_type` unset** — the model's `clean()` forbids it, but the field is
  `null=True, blank=True` at the database level, so a hand-edited or imported row can carry `None`.
  `unit_marker` must return `''` for it (fail quiet), never raise: a 500 on the course outline
  would be a far worse outcome than an unmarked row.
- **Quiz with `obligatory = False`** — returns `'quiz'`. Not an error, but the case that most
  invites a wrong implementation, so it is called out here and pinned by a test.
- **Completed additional unit** — carries both `✓` (leading, in the rail) and the kind marker
  (trailing). Intended, and the reason the icon trails.

## Testing

### Unit — `unit_marker`

Every branch, including the two that exist to be *silent*:

| Input | Expected |
| --- | --- |
| lesson, `obligatory=True` | `''` |
| lesson, `obligatory=False` | `'additional'` |
| quiz, `obligatory=True` | `'quiz'` |
| quiz, `obligatory=False` | `'quiz'` |
| non-unit node (e.g. chapter) | `''` |
| unit with `unit_type=None` | `''` |

The two quiz rows are a pair on purpose: together they pin that `obligatory` is ignored on a quiz,
which one row alone cannot.

### Render — one test per surface

Each asserts the marker is **present** for an additional unit and for a quiz, **and absent for a
required lesson**. The absence assertion is the load-bearing one: it is what pins "required is the
unmarked default", and without it every mutant that marks every row stays green.

- Course outline (`courses:course_outline`) — chip present, and inside the `.outline-unit` anchor.
- Unit page, lesson (`courses:lesson_unit`) — chip present in `.lesson-unit__head`.
- Unit page, quiz (`courses:quiz_unit`) — chip present, and the `<h1>` is not inside it (the
  `data-math-title` constraint).
- Contents rail (rendered by any unit page) — icon present with its accessible name.

### e2e

One navigation test covering the rail **and** the drawer — the same template at two widths, so a
rule that only works at desktop width is caught. Run in light and dark, with dark judged on its own
rather than inferred from light.

`.visually-hidden` in this project is the 1×1 + `clip` pattern, which Playwright reports as
**visible** with a non-empty box. Any assertion about these icons must therefore measure the
`<svg>`'s `bounding_box()`, not the wrapper's visibility.

### Falsification

Each test is falsified against a mutant chosen from its own failure mode, not merely run green:

- `unit_marker` returning `'additional'` for a non-obligatory quiz → the quiz-pair test must go red.
- `unit_marker` returning a marker unconditionally → each surface's *absence* assertion must go red.
- The rail icon rendered leading instead of trailing → the rail test's position assertion must go
  red (or the assertion is not testing position and should be strengthened).

A mutant must be removed by editing it out, never by `git checkout` of the file, which would
destroy the surrounding work.
