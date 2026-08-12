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

- **The prev/next footer navigation** (`templates/courses/_unit_footer.html`). Declined at design
  time: the footer sits on a unit page, and the contents rail on that same page already carries the
  marker for every unit including the neighbours, so a second marker in a width-constrained sticky
  bar buys repetition rather than information. If a student later reports being surprised by a quiz
  they clicked "Next" into, this is the first follow-up to reconsider.
- **The "My results" page** — quizzes only by construction, so a quiz marker would be noise.
- **Every teacher-facing surface** — the builder tree already distinguishes these states.
- Any model, migration, or `FORMAT_VERSION` change.

## Architecture / components

### 1. `unit_marker(node)` — the single source of truth

Added to `courses/rollups.py`, immediately beside the existing `is_obligatory_lesson` and
`is_quiz_unit`, which is where this vocabulary already lives.

Three module-level constants bind the marker values so they are not magic literals repeated across
`rollups.py`, two partials, four call sites and the test table:

```python
MARKER_NONE = ""
MARKER_QUIZ = "quiz"
MARKER_ADDITIONAL = "additional"
```

The rule, stated explicitly:

```python
def unit_marker(node):
    """MARKER_QUIZ | MARKER_ADDITIONAL | MARKER_NONE — the ONE student-facing kind rule.

    MARKER_NONE for a required lesson (the unmarked default), for any non-unit
    node, and for a unit whose unit_type is unset. A quiz is never 'additional':
    is_obligatory_lesson already excludes quizzes from required_total, so
    `obligatory` on a quiz node has no student meaning.
    """
    if is_quiz_unit(node):
        return MARKER_QUIZ
    if (
        node.kind == ContentNode.Kind.UNIT
        and node.unit_type == ContentNode.UnitType.LESSON
        and not node.obligatory
    ):
        return MARKER_ADDITIONAL
    return MARKER_NONE
```

**Why the `additional` branch is written out rather than composed from the existing predicates.**
`is_quiz_unit` and `is_obligatory_lesson` both return `False` for *all three* of an additional
lesson, a non-unit node, and a unit with `unit_type=None`, so a function built only from those two
cannot distinguish the three and could not satisfy the test table below. The quiz branch **does**
delegate to `is_quiz_unit`, so the one predicate that can be single-sourced is. Do not "simplify"
the `additional` branch into `not is_obligatory_lesson(node)` — that is precisely the mutant the
tests exist to kill.

### 2. Exposure to templates: two filters on the node

Registered in `courses/templatetags/courses_extras.py` (which already hosts
`strip_math_delimiters`, `dictkey`, `quiz_answer_url`):

- `@register.filter def unit_marker(node)` — returns the marker key. Used for the CSS modifier
  class and by the tests.
- `@register.filter def unit_marker_label(node)` — returns the **translated** display word, or
  `""` when the marker is `MARKER_NONE`.

`unit_marker_label` reads a module-level map in `rollups.py`:

```python
UNIT_MARKER_LABELS = {
    MARKER_QUIZ: gettext_lazy("Quiz"),
    MARKER_ADDITIONAL: gettext_lazy("Additional"),
}
```

`gettext_lazy`, **not** `gettext`: this is a module-level dict evaluated at import, before the
request's locale is active, and a non-lazy call there would freeze the first-seen language into
the process.

Putting the words in Python rather than in each partial is what makes each string authored exactly
once, and it is also what lets the icon partial put the word in a `title=` attribute — a
`{% include %}` cannot be used inside an attribute value, so a label-partial could not serve both
consumers.

**Filters on the node, not a key on the `build_outline` item dict.** This is load-bearing.
`_outline_node.html` and `_unit_tree_node.html` each render a `build_outline` item dict and could
read a dict key, but `_lesson_article.html` and `_quiz_article.html` receive only a bare `unit`
`ContentNode` with no dict anywhere in scope. A dict key would therefore cover two of the three
surfaces and force a second rule for the third — two rules that can drift. Node filters cover all
of them from one expression.

### 3. Two shared partials

One authoring site per surface family, and the glyph markup written once:

**`templates/courses/_unit_kind_chip.html`** — the text chip.

```html
{% load i18n courses_extras %}{% with m=node|unit_marker %}{% if m %}<span
  class="badge unit-kind-chip unit-kind-chip--{{ m }}">{{ node|unit_marker_label }}</span>{% endif %}{% endwith %}
```

**`templates/courses/_unit_kind_icon.html`** — the icon.

```html
{% load i18n courses_extras %}{% with m=node|unit_marker %}{% if m %}<span
  class="unit-kind unit-kind--{{ m }}" title="{{ node|unit_marker_label }}">
  <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">…</svg>
  <span class="unit-kind__label">{{ node|unit_marker_label }}</span>
</span>{% endif %}{% endwith %}
```

Both render **nothing at all** when `unit_marker` is `MARKER_NONE`, and both call `unit_marker`
themselves, so no call site can pass a state the partial did not compute.

**Include contract.** Every call site passes the node explicitly:
`{% include "courses/_unit_kind_chip.html" with node=item.node %}` on the outline (where the
`build_outline` dict is in scope) and `… with node=unit %}` on the article templates. The rail
passes `with node=item.node`.

**Class contract (the test selectors).** The chip emits `badge unit-kind-chip
unit-kind-chip--<marker>`; the icon wrapper emits `unit-kind unit-kind--<marker>`. `.unit-kind-chip`
and `.unit-kind` are the stable selectors the render tests assert on. `.badge` is carried for the
existing neutral pill styling (`app.css:115`) and is **not** a test selector, since many other
things carry it.

**Accessible-name contract (exactly one reading).** On the icon: the `<svg>` is `aria-hidden`, so it
contributes nothing; `.unit-kind__label` is the text; the wrapper's `title=` supplies the hover
tooltip. The accessible name of the enclosing rail link is therefore computed **from contents** and
reads "*<unit title>*, Quiz". The wrapper's `title=` is a distinct hover target from the
`title=` already on `.unit-tree__label` in the same row — hovering the glyph shows the kind,
hovering the text shows the full title.

### 4. The four rendered surfaces

**Outline page** — `templates/courses/_outline_node.html`.

The chip goes **inside** the `<a class="outline-unit">`, after `.outline-unit__title` and before the
`✓` badge. Inside the anchor on purpose: the `✓` already is, and placing the chip there makes the
state part of the link's accessible name, so a screen-reader user tabbing through links hears
"Extra practice, Additional" rather than a bare title with a detached span they never reach.

**Where it actually lands.** `.outline-unit` is `display: flex` (`app.css:513`) and
`.outline-unit__title` is `flex: 1` (`app.css:521`), so the title box absorbs all free space. The
chip therefore sits in the **right gutter**, immediately left of the `✓`:

```
Extra practice  ··············  [Additional]  ✓
```

This is accepted, not worked around — it gives the outline the same right-hand marker column the
rail gets below, so the two surfaces agree. Note that `.badge--done`'s `margin-left: auto`
(`app.css:559`) is consequently **inert** here (there is no free space left for it to consume); the
`✓`'s right position comes from the title's `flex: 1`, not from that margin. No CSS change is
required on this surface.

**Contents rail** — `templates/courses/_unit_tree_node.html`, rail rendering.

The icon is **trailing** — after `.unit-tree__label`, last element child of `.unit-tree__unit`. Two
reasons, both structural:

1. The `✓` already **leads**. `courses.css:788` sets `.unit-tree__check { margin-left: 0 }`
   specifically to cancel `.badge--done`'s `margin-left: auto` so the tick leads in a unit row. A
   second leading glyph would make every completed *additional* unit begin with two marks.
2. Trailing puts the kind icons in the same right-hand gutter that `.unit-tree__count` and
   `.unit-tree__groupcheck` occupy on group rows.

**A required CSS change makes that gutter real.** Group rows right-align their chrome only because
`.unit-tree__grouptitle` is `flex: 1` (`courses.css:736`). `.unit-tree__label` (`courses.css:789`)
carries **no** `flex` declaration, so it defaults to `flex: 0 1 auto` and a short title does not
fill the row — the icon would sit immediately after the text and the "one marker column" would be
ragged. So add:

```css
.unit-tree__label { flex: 1 1 auto; }
```

`1 1 auto`, deliberately **not** `1 1 0`: basis `auto` preserves the label's current sizing
behaviour, which matters because the drawer overrides this same class to `white-space: normal`
(`courses.css:977`) in a title column squeezed to ~98px, and a basis change there could move wrap
points. This runs against the general "use `flex: 1 1 0`" habit, so it is a deliberate exception
and the 390×780 drawer rendering must be **measured**, not assumed (see Testing).

`.icon` is already `flex: none` (`app.css:109`), so the icon itself needs no flex rule, and
`.unit-tree__label`'s existing `min-width: 0` keeps the ellipsis working.

**Mobile drawer** — same template, rendered again into `.unit-drawer__list` by `_unit_shell.html`.

The drawer is a **touch** surface, and the template's own authored comment already records that
"Touch has no hover" — so `title=` yields nothing there. An icon alone in the drawer would be a
bare `+`/`?` with no text, no tooltip and no legend, while the outline page shows the word: two
vocabularies with nothing connecting them.

Resolution: `.unit-kind__label` is visually hidden by default and becomes **visible text** at
drawer scope. The drawer already lets labels wrap (`courses.css:977`), so width is not the
constraint it is in the 14rem rail.

```css
.unit-kind__label { /* the project's standard visually-hidden treatment */ }
.unit-drawer__list .unit-kind__label { /* revert to visible inline text */ }
```

The visually-hidden treatment must reuse the project's existing `.visually-hidden` definition
rather than re-authoring a second clip-rect pattern; the simplest implementation is for the span to
carry `class="visually-hidden unit-kind__label"` and for the drawer rule to un-hide it.

**Unit page** — `templates/courses/_lesson_article.html` and `templates/courses/_quiz_article.html`.

The naive placement — chip as a direct flex child of `.lesson-unit__head` — **does not work**, and
the reason must be recorded so it is not re-attempted:

- Inside the shell, `.unit-shell__main > .lesson, > .quiz` are `max-width: none`
  (`courses.css:660-661`), so the head row spans the full ~872px column, not 46rem.
- `.lesson-unit__head` is `justify-content: space-between` (`courses.css:828`) and
  `.lesson-unit__head .lesson-unit__title` is `flex: 1` (`courses.css:834`).
- Under `html.unit-tree-collapsed` the **title** is capped at the prose measure
  (`courses.css:~1097`) while the head is not, so `space-between` strands the chip in dead space
  mid-row.
- On the quiz page there is no done pill, so a chip as the only sibling flies to the far right of a
  full-width row.

**Resolution: an inner heading group.** Both article templates wrap the `<h1>` and the chip in one
element:

```html
<div class="lesson-unit__heading">
  <h1 class="lesson-unit__title" data-math-title>{{ unit.title }}</h1>
  {% include "courses/_unit_kind_chip.html" with node=unit %}
</div>
```

```css
.lesson-unit__heading { flex: 1 1 auto; min-width: 0;
  display: flex; align-items: baseline; flex-wrap: wrap; gap: var(--space-3); }
```

- The head row keeps exactly two children on the lesson page (heading group, done pill) and one on
  the quiz page, so `space-between` behaves as it does today.
- `align-items: baseline` on the inner group answers the vertical-alignment question: the chip sits
  on the `<h1>`'s baseline. `.lesson-unit__head`'s own `align-items: flex-start` (`courses.css:828`)
  applies to the group as a whole, and `.badge`'s `vertical-align: middle` is inert on a flex item,
  so without this the chip would top-align against a full-size heading.
- `flex-wrap: wrap` preserves the existing mobile behaviour: `courses.css:986` gives
  `.lesson-unit__title` `flex-basis: 100%` below the breakpoint, which now applies inside the group
  and drops the chip to the line beneath the title.
- The collapsed-TOC width allow-list (`courses.css:~1097`) still names `.lesson-unit__title`, so the
  heading keeps its prose measure while the group widens. **No allow-list edit** — and note the
  file's comment at `:1076` records that `.lesson-unit__head` was deliberately taken off that list,
  which `.lesson-unit__heading` must likewise stay off.

`_quiz_article.html` additionally gains the `.lesson-unit__head` wrapper it currently lacks. That
reuse is safe: `.lesson-unit__head .lesson-unit__title { margin: 0 }` (`courses.css:834`) and
`.quiz .lesson-unit__title { margin-bottom: var(--space-6) }` (`courses.css:293`) have **equal**
specificity (0,2,0), so source order decides and `:834` wins, while `.lesson-unit__head` supplies
the identical `margin-bottom: var(--space-6)` (`courses.css:829`). Net vertical rhythm unchanged.

**Hard constraint:** the chip must never be placed **inside** `<h1 data-math-title>`. `math.js`
typesets that element's contents, so a chip in there would enter the maths-title scan. The chip is
a **sibling** of the `<h1>`, inside the heading group.

### 5. The glyphs

Both are monochrome line SVGs on the `viewBox="0 0 24 24"` grid, per the project icon convention
(`currentColor`, never emoji).

- **Quiz** — a `?` inside a circle. Chosen over a clipboard/checklist, which turns to mush at the
  ~1em the rail renders. The standard objection is that a circled `?` reads as "help"; there is no
  help affordance anywhere in the contents rail, the drawer, or an outline row, so the collision is
  theoretical on these surfaces.
- **Additional** — a `+` inside a circle, deliberately echoing the `+{{ additional_done }}
  additional` rollup that already sits on the group row directly above these units
  (`_outline_node.html:23`). Same shape family as the quiz mark, so the two read as one system.

**Colour: the marker never introduces a hue of its own — it inherits the row's.** `.icon` is
`stroke: currentColor` (`app.css:109`) and the marker deliberately keeps that, with **no** colour
rule of its own on any surface. The consequences are stated rather than discovered:

- On `.unit-tree__unit.is-active` the row is `--primary` (`courses.css:774`), so the icon is too.
  That is the current unit, the one row a student most needs to find; the marker joining the row's
  accent is correct, not a third hue competing with it.
- On `.unit-tree__unit.is-done` the row is `--text-tertiary` (`courses.css:770`), so the icon fades
  with the row. Intended: a completed unit is quieter overall, and the marker has no business
  shouting louder than the title it belongs to.
- Nowhere does the marker introduce a hue the row does not already have, which is what keeps `✓`
  (`--success`) and the active row (`--primary`) as the only two signals in the rail, and keeps the
  quiz/additional distinction carried by **shape plus the accessible name** — the colour-blind-safe
  answer.

There is deliberately **no** conditional "quieten it if it proves too loud" rule: that would be an
untestable condition, and a rail-specific class emitted by a surface-agnostic partial would
contradict §3.

### 6. Wording and translation

The non-obligatory state is worded **"Additional"**, not "Optional". `_outline_node.html:23`
already renders `+N additional` on the group row and `build_outline` calls the field
`additional_done`; using the same word means the counter and the chips beneath it name the same
set.

**In Polish the two share a root but not an inflection, and that is accepted.** The existing msgid
`additional` is translated `"dodatkowe"` (`locale/pl/LC_MESSAGES/django.po:4208`) — the form that
agrees with its own count phrase. The new msgid `Additional`, naming one unit, takes
`msgstr "Dodatkowa"`. A Polish reader connects `dodatkow-` across both; forcing one identical
surface form would make one of the two ungrammatical. The existing `additional` → `"dodatkowe"`
entry is **not** revisited.

The msgid `Quiz` **already exists** and needs no new translation: `locale/pl:851` carries
`msgstr "Quiz"`, sourced from `courses/models.py:198` (the `UnitType.QUIZ` `TextChoices` label),
`manage/_add_affordance.html:26` and `manage/editor/editor.html`. Reusing that exact msgid is
required, not incidental — the chip and the model's own choice label must never diverge.

`makemessages` regenerates **both** catalogs: `locale/pl` (translated) and `locale/en` (the source
catalog, msgstrs empty). `makemessages` can fuzzy-prefill a wrong translation from a
near-neighbour msgid, so any `#, fuzzy` entry on `Additional` must be inspected and cleared —
which is two deletions, the `#, fuzzy` line and the wrong `msgstr` — never accepted as-is. The
`.po` → `.mo` compile lands in the same change.

## Data flow

No new queries and no change to any existing query.

```
ContentNode (kind, unit_type, obligatory) ── already loaded ──┐
                                                              │
  build_outline() ──> item dicts ──> _outline_node.html ──────┤
                                     _unit_tree_node.html ────┤──> unit_marker(node)
                                     (rail + drawer)          │      │
  view context "unit" (bare node) ──> _lesson_article.html ───┤      ├─> ''           → render nothing
                                      _quiz_article.html ─────┘      ├─> 'quiz'       → Quiz chip / icon
                                                                     └─> 'additional' → Additional chip / icon
```

`unit_marker` is a pure function of three already-loaded fields on a node the template already
holds. Every surface reads it through the same filter, so the surfaces cannot disagree, and none of
them triggers a database round-trip. `build_outline`, `build_unit_nav`, and the rollups are
untouched.

The `drafts` / publish filtering is unaffected: a unit that `unit_is_visible` excludes never reaches
a template, so it has no marker to render.

**Template-render cost, accepted.** This adds one `{% include %}` and two filter calls to every
outline row and every rail row — including the silent required-lesson majority, which renders
nothing. On the largest real course (the matematyka import, 793 units) that is ~800 extra includes
on the outline and ~800 on each unit page's rail. Both are pure in-memory template work with no
query behind them, on pages that already render 793 rows; no measurement is warranted before
merge. If a page-render regression is ever observed on that course, the cheap fix is to hoist the
marker into the `build_outline` dict for the two dict-bearing surfaces — but not before there is a
measurement to justify splitting the rule.

## Error handling

There is no user input and no failure mode in the ordinary sense. What matters is that the
degenerate cases render sanely:

- **Non-unit node** (part / chapter / section) — `unit_marker` returns `MARKER_NONE`. Group rows in
  the outline and `<summary>` rows in the rail get no marker, and the partials render nothing. This
  is reachable: both templates recurse over container nodes.
- **Unit with `unit_type` unset** — the model's `clean()` forbids it, but the field is
  `null=True, blank=True` at the database level, so a hand-edited or imported row can carry `None`.
  `unit_marker` must return `MARKER_NONE` for it (fail quiet), never raise: a 500 on the course
  outline would be a far worse outcome than an unmarked row.
- **Quiz with `obligatory = False`** — returns `MARKER_QUIZ`. Not an error, but the case that most
  invites a wrong implementation, so it is pinned by a test.
- **Completed additional unit** — carries both `✓` (leading, in the rail) and the kind marker
  (trailing). Intended, and the reason the icon trails.

## Testing

### Unit — `unit_marker`

Every branch, including the ones that exist to be *silent*:

| Input | Expected |
| --- | --- |
| lesson, `obligatory=True` | `MARKER_NONE` |
| lesson, `obligatory=False` | `MARKER_ADDITIONAL` |
| quiz, `obligatory=True` | `MARKER_QUIZ` |
| quiz, `obligatory=False` | `MARKER_QUIZ` |
| non-unit node (e.g. chapter) | `MARKER_NONE` |
| unit with `unit_type=None` | `MARKER_NONE` |

The two quiz rows are a pair on purpose: together they pin that `obligatory` is ignored on a quiz,
which one row alone cannot.

`unit_marker_label` is covered by the same shape: the quiz and additional nodes return the two
translated words, and all three `MARKER_NONE` inputs return `""`.

### Render — one test per rendered surface (four)

Each asserts the marker is **present** for an additional unit and for a quiz, **and absent for a
required lesson**. The absence assertion is the load-bearing one: it is what pins "required is the
unmarked default", and without it every mutant that marks every row stays green.

1. **Course outline** (`courses:course_outline`) — a `.unit-kind-chip` is present, and is **inside**
   the `.outline-unit` anchor (not a detached sibling).
2. **Unit page, lesson** (`courses:lesson_unit`) — a `.unit-kind-chip` is present inside
   `.lesson-unit__heading`, and the `<h1 data-math-title>` does **not** contain it.
3. **Unit page, quiz** (`courses:quiz_unit`) — the same two assertions, on the quiz template.
4. **Contents rail** (rendered by any unit page) — a `.unit-kind` is present with its accessible
   name, and it is the **last element child** of `.unit-tree__unit`, after `.unit-tree__label`.
   This position assertion is required, not optional: the leading-vs-trailing decision is the whole
   subject of two structural arguments in §4, and without it that decision is unpinned.

The `data-math-title` assertion appears on **both** article templates (2 and 3), because
`_lesson_article.html:7` and `_quiz_article.html:5` both carry that attribute and the constraint in
§4 is unconditional. One of the two cases uses a unit title containing maths, asserting the title
still typesets with the chip as a sibling.

### e2e

One navigation test covering the rail **and** the drawer — the same template at two widths, so a
rule that only works at desktop width is caught. It must specifically verify:

- the icon renders in the rail's right gutter (the `flex: 1 1 auto` change to `.unit-tree__label`);
- the drawer at **390×780** shows the marker's **visible text**, not a bare glyph, and that
  `.unit-tree__label`'s wrap points are unharmed by the flex change — this is the measurement §4
  requires rather than assumes;
- both light and dark, with dark judged on its own rather than inferred from light.

`.visually-hidden` in this project is the 1×1 + `clip` pattern, which Playwright reports as
**visible** with a non-empty box. Any assertion about the icon or its hidden label must therefore
measure `bounding_box()`, not the wrapper's visibility.

### Falsification

Each test is falsified against a mutant chosen from its own failure mode, not merely run green:

- `unit_marker` returning `MARKER_ADDITIONAL` for a non-obligatory quiz → the quiz-pair test goes
  red.
- `unit_marker`'s `additional` branch rewritten as `not is_obligatory_lesson(node)` → the non-unit
  and `unit_type=None` rows go red. (This is the specific over-simplification §1 warns against.)
- `unit_marker` returning a marker unconditionally → each surface's *absence* assertion goes red.
- The rail icon rendered leading instead of trailing → the rail test's last-element-child assertion
  goes red.
- The `.unit-tree__label { flex: 1 1 auto }` rule removed → the rail gutter e2e assertion goes red.

A mutant must be removed by editing it out, never by `git checkout` of the file, which would
destroy the surrounding work.
