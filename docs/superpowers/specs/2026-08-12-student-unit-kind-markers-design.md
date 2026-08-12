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
- **Teacher *authoring* surfaces** — the builder tree (`manage/_tree_node.html`) already
  distinguishes these states and is not touched. Note this exclusion is about authoring UI, **not**
  about "any page a teacher can see": `_quiz_article.html` is shared with the **quiz previewer**
  (`previewing` branch), so a teacher previewing a quiz will see the chip. That is harmless and
  deliberate — the previewer's job is to show what a student sees.
- Any model, migration, or `FORMAT_VERSION` change.

## Architecture / components

### 1. `unit_marker(node)` — the single source of truth

Added to `courses/rollups.py`, immediately beside the existing `is_obligatory_lesson` and
`is_quiz_unit`, which is where this vocabulary already lives.

Three module-level constants bind the marker values so they are not magic literals repeated across
`rollups.py`, four Python call sites and the test table:

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
    node, for a unit whose unit_type is unset, AND for anything that is not a
    node at all. A quiz is never 'additional': is_obligatory_lesson already
    excludes quizzes from required_total, so `obligatory` on a quiz node has no
    student meaning.
    """
    # getattr, not node.kind: a template that includes a marker partial without
    # `with node=...` resolves the variable to string_if_invalid (default ''),
    # and a bare attribute access — or handing '' straight to is_quiz_unit —
    # raises AttributeError and 500s the course outline. Fail quiet instead.
    if getattr(node, "kind", None) != ContentNode.Kind.UNIT:
        return MARKER_NONE
    if is_quiz_unit(node):
        return MARKER_QUIZ
    if node.unit_type == ContentNode.UnitType.LESSON and not node.obligatory:
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

**The constants do not reach the templates.** A Django template cannot import a Python constant, so
`_unit_kind_icon.html` necessarily hardcodes `"quiz"` in its branch and both partials interpolate
the raw key into a class name. Renaming `MARKER_QUIZ` or `MARKER_ADDITIONAL` therefore requires a
grep of `templates/courses/_unit_kind_*.html`; the render tests assert the rendered modifier class
against the constant, so a rename that misses the templates goes red rather than silent.

### 2. Exposure to templates: two filters on the node

Registered in `courses/templatetags/courses_extras.py` (which already hosts
`strip_math_delimiters`, `dictkey`, `quiz_answer_url`):

- `unit_marker` — returns the marker key. Used for the CSS modifier class and by the tests.
- `unit_marker_label` — returns the **translated** display word, or `""` when the marker is
  `MARKER_NONE`.

**Registration form is prescribed, not incidental.** Register by passing the function, so the
template-tag module never binds a local name that shadows the import:

```python
from courses import rollups

register.filter("unit_marker", rollups.unit_marker)
register.filter("unit_marker_label", rollups.unit_marker_label)
```

Writing the obvious `from courses.rollups import unit_marker` followed by
`@register.filter def unit_marker(node): return unit_marker(node)` **rebinds the module-level
name** and produces unbounded recursion on the first render — not an import error, so it passes
review and fails in the browser. If a decorator is preferred, follow the file's existing
`@register.filter(name="marks") def marks_filter(...)` precedent and give the wrapper a distinct
function name.

`unit_marker_label` lives in `rollups.py` beside `unit_marker` and reads a module-level map:

```python
UNIT_MARKER_LABELS = {
    MARKER_QUIZ: gettext_lazy("Quiz"),
    MARKER_ADDITIONAL: gettext_lazy("Additional"),
}

def unit_marker_label(node):
    return UNIT_MARKER_LABELS.get(unit_marker(node), "")
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
{% load courses_extras %}{% with m=node|unit_marker %}{% if m %}<span
  class="badge unit-kind-chip unit-kind-chip--{{ m }}">{{ node|unit_marker_label }}</span>{% endif %}{% endwith %}
```

**`templates/courses/_unit_kind_icon.html`** — the icon.

```html
{% load courses_extras %}{% with m=node|unit_marker %}{% if m %}<span
  class="unit-kind unit-kind--{{ m }}" title="{{ node|unit_marker_label }}">
  {% if m == "quiz" %}
    <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="9"/>
      <path d="M9.4 9.3a2.7 2.7 0 0 1 5.2.9c0 1.8-2.6 2.4-2.6 2.4"/>
      <circle cx="12" cy="16.6" r=".95" fill="currentColor" stroke="none"/>
    </svg>
  {% else %}
    <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="9"/>
      <path d="M12 8.2v7.6M8.2 12h7.6"/>
    </svg>
  {% endif %}
  <span class="visually-hidden unit-kind__label">{{ node|unit_marker_label }}</span>
</span>{% endif %}{% endwith %}
```

Both render **nothing at all** when `unit_marker` is `MARKER_NONE`, and both call `unit_marker`
themselves, so no call site can pass a state the partial did not compute.

The two glyphs are given as concrete geometry rather than described, because §5's legibility
argument is about geometry: the `?` is a compound stroke path that reads as a blob if drawn
naively at rail size. The `fill="currentColor" stroke="none"` dot follows the existing pattern in
`_unit_shell.html`'s TOC-pin icon. Both glyphs are still subject to the screenshot acceptance step
in Testing — the paths above are the starting point, not a licence to skip looking at them.

**Include contract.** Every call site passes the node explicitly:
`{% include "courses/_unit_kind_chip.html" with node=item.node %}` on the outline and the rail
(where the `build_outline` dict is in scope) and `… with node=unit %}` on the article templates.
Omitting `node=` does not crash — `unit_marker`'s `getattr` guard makes it render nothing — but it
is still a bug, and there is a test for it (see Testing).

**Class contract (the test selectors).** The chip emits `badge unit-kind-chip
unit-kind-chip--<marker>`; the icon wrapper emits `unit-kind unit-kind--<marker>`. `.unit-kind-chip`
and `.unit-kind` are the stable selectors the render tests assert on. `.badge` is carried for the
existing neutral pill styling and is **not** a test selector, since many other things carry it;
`.unit-kind-chip` therefore needs no CSS rule of its own. The `--<marker>` modifier classes are
**reserved test/debug hooks with no styling attached today**, and §5 forbids giving them any — do
not add rules to "complete" them.

**Accessible-name contract.** On the icon: the `<svg>` is `aria-hidden`, so it contributes nothing;
`.unit-kind__label` is the text; the wrapper's `title=` supplies the hover tooltip. The enclosing
link's accessible name is computed **from contents**, so it depends on completion state:

| Surface | Not completed | Completed |
| --- | --- | --- |
| Rail (`_unit_tree_node.html`) | "*<title>*, Quiz" | "Completed, *<title>*, Quiz" |
| Outline (`_outline_node.html`) | "*<title>*, Additional" | "*<title>*, Additional, Completed" |

The `✓` carries `aria-label="Completed"` and **leads** in the rail but **trails** in the outline,
which is why the two orders differ. Render tests assert **substring containment** of the marker
word, never full-name equality — a full-name assertion written from one row would be red on the
other.

The wrapper's `title=` is a distinct hover target from the `title=` already on `.unit-tree__label`
in the same row — hovering the glyph shows the kind, hovering the text shows the full title. At
drawer scope the label becomes visible text and the `title=` is then redundant; it is deliberately
left in place rather than conditionally suppressed, because the partial is surface-agnostic and
touch has no hover for it to interfere with.

### 4. The four rendered surfaces

Full stylesheet paths, short-formed thereafter: `core/static/core/css/app.css` and
`courses/static/courses/css/courses.css`.

**New shared component CSS in `app.css`, next to `.badge` (`app.css:115-131`):**

```css
/* .unit-kind-chip carries .badge for the pill and is a test selector only — no rule. */
.unit-kind { display: inline-flex; align-items: center; gap: var(--space-1); flex: none; }
```

`.unit-kind` needs its own rule because **the flex item of `.unit-tree__unit` is the `.unit-kind`
wrapper, not the `<svg class="icon">` inside it**. `.icon { flex: none }` (`app.css:109`) governs
`.icon` only when `.icon` is itself a flex item; inside a non-flex `.unit-kind` it does nothing for
the wrapper, which would otherwise take the initial `flex: 0 1 auto`. The `display: inline-flex`
also makes `.icon`'s `flex: none` meaningful again for the glyph, and the `gap` spaces glyph from
label at drawer scope. `var(--space-1)` is 4px (`app.css:75`); the surrounding block is
token-driven, so a raw `.25rem` would be the odd one out.

**Outline page** — `templates/courses/_outline_node.html`.

The chip goes **inside** the `<a class="outline-unit">`, after `.outline-unit__title` and before the
`✓` badge. Inside the anchor on purpose: the `✓` already is, and placing the chip there makes the
state part of the link's accessible name, so a screen-reader user tabbing through links hears the
marker rather than a bare title with a detached span they never reach.

**Where it actually lands.** `.outline-unit` is `display: flex` (`app.css:513`) and
`.outline-unit__title` is `flex: 1` (`app.css:521`), so the title box absorbs all free space. The
chip therefore sits in the **right gutter**, immediately left of the `✓`:

```
Extra practice  ··············  [Additional]  ✓
```

This is accepted, not worked around — it gives the outline the same right-hand marker column the
rail gets below, so the two surfaces agree. Note that `.badge--done`'s `margin-left: auto`
(`app.css:559`) is consequently **inert** here (there is no free space left for it to consume); the
`✓`'s right position comes from the title's `flex: 1`, not from that margin.

**One required CSS change on this surface.** `.outline-unit__title` is `flex: 1` (= `1 1 0%`) with
**no `min-width: 0`** and no overflow handling, so its automatic minimum size is its min-content
width and it cannot shrink below its longest word. `.outline-unit` itself does not wrap (only the
parent `li.outline-node--unit` does). Adding a chip up to ~90px wide ("Additional" / "Dodatkowa")
can therefore push a 390px-wide row past its box for a long or unbroken title. Edit the rule in
place at `app.css:521`:

```css
.outline-unit__title { flex: 1; min-width: 0; overflow-wrap: break-word; }
```

This mirrors what `.lesson-unit__head .lesson-unit__title` already does (`courses.css:834-835`) and
is inert today — without a shrink-forcing sibling nothing changes — so it is safe against the
existing `li.outline-node--unit` wrap behaviour. The phone-width outline row joins the e2e set so
this is measured, not assumed.

**Accepted collision:** `.badge` fills with `--surface-sunken` (`app.css:119`), and so do
`.outline-unit:hover` (`app.css:519`) and `.outline-node:target > .outline-unit` (`app.css:534`).
On a hovered row and on an internal-link landing, the chip's fill matches the row and only its 1px
`--border-default` rim separates it. This is accepted rather than patched: the rim is a real
separation, and picking a different surface token would invert the problem in one of the two themes
(a token that reads against the hovered row can vanish against the row at rest). The hover and
`:target` states join the screenshot set so the rim is actually looked at in both themes. Existing
`.badge--done` dodges this only because it overrides the background with `--success-subtle`; this
chip is the first plain `.badge` inside `.outline-unit`.

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
ragged. Edit that existing rule **in place** at `courses.css:789`:

```css
.unit-tree__label { flex: 1 1 auto; min-width: 0; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
```

`1 1 auto`, deliberately **not** `1 1 0`: basis `auto` preserves the label's current sizing
behaviour, which matters because the drawer overrides this same class to `white-space: normal`
(`courses.css:977`) in a title column squeezed to ~98px, and a basis change there could move wrap
points. This runs against the general "use `flex: 1 1 0`" habit, so it is a deliberate exception
and the 390×780 drawer rendering is measured by a mechanical A/B (see Testing).

**Mobile drawer** — same template, rendered again into `.unit-drawer__list` by `_unit_shell.html`.

The drawer is a **touch** surface, and the template's own authored comment already records that
"Touch has no hover" — so `title=` yields nothing there. An icon alone in the drawer would be a
bare `+`/`?` with no text, no tooltip and no legend, while the outline page shows the word: two
vocabularies with nothing connecting them.

Resolution: `.unit-kind__label` carries `class="visually-hidden unit-kind__label"` and is un-hidden
at drawer scope. These rules go **inside the existing `@media (max-width: 640px)` block in
`courses.css` (:948-987), beside the `.unit-drawer__list .unit-tree__label` rule at `:977`**:

```css
.unit-drawer__list .unit-kind__label {
  position: static; width: auto; height: auto;
  overflow: visible; clip: auto; white-space: normal;
}
.unit-drawer__list .unit-kind { flex: 0 1 auto; min-width: 0; }
```

**All six declarations are required, and this is why they are written out rather than described as
"revert to visible".** `.visually-hidden` (`app.css:1217-1224`) is exactly six declarations —
`position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0);
white-space: nowrap`. An implementer who resets only the obvious `position: static` leaves the span
1px × 1px with `overflow: hidden` and a zero clip rect: the drawer shows a bare glyph, the central
drawer requirement silently fails, and every render test stays green. Specificity is not a concern —
`.unit-drawer__list .unit-kind__label` is (0,2,0) against `.visually-hidden`'s (0,1,0), so it wins
regardless of file order.

**The drawer row stays a single flex line — do NOT add `flex-wrap: wrap`.** It is tempting, to give
the marker its own line in a ~98px column, and it is wrong: flex line-breaking uses each item's
**hypothetical main size**, and with `flex: 1 1 auto` the label's base size is the max-content width
of the full title, which always exceeds a 98px line. `min-width: 0` lowers the shrink floor but not
the base size, so the row would break *before* the label — stranding the leading `✓`
(`flex: none`) alone on line 1, pushing the title to line 2 and the marker to line 3. That is a
three-line row with an orphan tick, and because `flex-wrap` is unconditional it would regress every
completed unit in the drawer **including ones with no marker at all**.

Instead `.unit-kind` is made shrinkable there (`flex: 0 1 auto; min-width: 0`) so its own label text
wraps inside its box, exactly as the title's does. Expected drawer row shape for a **completed
additional** unit: one flex line, `[✓] [title, wrapping] [⊕ Dodatkowa, wrapping]`. That shape is
asserted at 390×780 in the e2e.

For the same reason there is **no** `white-space: nowrap` on `.unit-kind`: it is `inline-flex`, so
the `<svg>` and the label are flex items and cannot break between each other regardless, and the
un-hide rule above sets `white-space: normal` on the label itself — a more specific match — so a
`nowrap` on the wrapper would be overridden exactly where it would matter.

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

**Resolution: an inner heading group, plus an explicit flex reset on the `<h1>`.** Both article
templates wrap the `<h1>` and the chip in one element:

```html
<div class="lesson-unit__heading">
  <h1 class="lesson-unit__title" data-math-title>{{ unit.title }}</h1>
  {% include "courses/_unit_kind_chip.html" with node=unit %}
</div>
```

Two rules in `courses.css`, placed **immediately after the existing `.lesson-unit__head
.lesson-unit__title` rule at `:834-835`** and therefore **before** the `@media` block at `:985-987`:

```css
.lesson-unit__heading { flex: 1 1 auto; min-width: 0;
  display: flex; align-items: baseline; flex-wrap: wrap; gap: var(--space-3); }
.lesson-unit__heading > .lesson-unit__title { flex: 0 1 auto; }
```

and **one rule added inside the `@media (max-width: 640px)` block beside `:986`**:

```css
.lesson-unit__heading { flex-basis: 100%; }
```

**The reset is mandatory.** `.lesson-unit__head .lesson-unit__title` (`courses.css:834`) is a
**descendant** selector, so it still matches the `<h1>` through the new wrapper and would make it
`flex: 1 1 0%` *inside the group* — absorbing every pixel and pushing the chip to the far right,
reproducing exactly the two failures this section claims to fix. `.lesson-unit__heading >
.lesson-unit__title` is (0,2,0), the same specificity as `:834`, so source order decides and it
must come after.

**The mobile rule is mandatory too, and for a reason source order alone does not cover.** Today
`.lesson-unit__head .lesson-unit__title { flex-basis: 100% }` at `:986` resolves 100% against
`.lesson-unit__head`, and that is what forces `.unit-done` and `.lesson-unit__reset` onto a second
row at phone width — the documented purpose of that rule (`courses.css:981-984`). After the wrapper
it resolves against `.lesson-unit__heading` instead, whose own basis is content-derived, so the
head's wrap decision would silently depend on the group's max-content contribution and a short title
would keep the pill beside it. Giving the **group** `flex-basis: 100%` at the same breakpoint
restores the old behaviour *by construction* rather than by argument: the group fills the head line,
the pill and reset drop below it as today, and inside the group `:986` still gives the `<h1>` basis
100% so the chip wraps beneath the title. `tests/test_e2e_unit_head_layout.py` is the pin for this
(see Testing).

Further notes on the group:

- What makes `space-between` safe is **the group's `flex: 1 1 auto`**, not the number of children.
  The head has **one** child on the quiz page (the group alone) and **two or three** on the lesson
  page (group, done pill, and the conditional `.lesson-unit__reset` that `_lesson_article.html:28-33`
  renders when `has_stateful_elements`). The group absorbs the free space in every one of those
  cases, so nothing is left for `space-between` to distribute and the one-child quiz row — the very
  case warned about above — is covered by the same rule as the others.
- `align-items: baseline` answers the vertical-alignment question: the chip sits on the `<h1>`'s
  baseline. `.lesson-unit__head`'s own `align-items: flex-start` (`courses.css:828`) applies to the
  group as a whole, and `.badge`'s `vertical-align: middle` is inert on a flex item, so without this
  the chip would top-align against a full-size heading.
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

**Maths-audit comment must be updated.** `courses.css:2310-2350` records a measured drawer audit
listing the sibling controls a KaTeX box was checked against (`.unit-tree__count`,
`.unit-tree__groupcheck`, `.unit-tree__check`, `.unit-tree__chevron`, `.unit-drawer__close`) and
explicitly says to re-check "if the drawer's title column ever narrows further". This change adds a
new sibling (`.unit-kind`) inside `.unit-tree__unit` **and** alters `.unit-tree__label`'s flex —
exactly that trigger. Add `.unit-kind` to that list and re-earn the "CONFIRMED clean" claim with the
maths-title drawer case in the e2e; do not leave the comment asserting a stale audit.

### 5. The glyphs

Both are monochrome line SVGs on the `viewBox="0 0 24 24"` grid, per the project icon convention
(`currentColor`, never emoji); the concrete geometry is in §3.

- **Quiz** — a `?` inside a circle. Chosen over a clipboard/checklist, which turns to mush at the
  ~1em the rail renders (`.unit-tree` is `font-size: .82rem`, `courses.css:665`). The standard
  objection is that a circled `?` reads as "help"; there is no help affordance anywhere in the
  contents rail, the drawer, or an outline row, so the collision is theoretical on these surfaces.
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
- Nowhere does the marker introduce a hue the row does not already have, which keeps `✓`
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
on the outline and ~1600 on each unit page (the rail and the drawer each render the full tree).
Both are pure in-memory template work with no query behind them, on pages that already render those
rows; no measurement is warranted before merge. If a page-render regression is ever observed on
that course, the cheap fix is to hoist the marker into the `build_outline` dict for the
dict-bearing surfaces — but not before there is a measurement to justify splitting the rule.

## Error handling

There is no user input and no failure mode in the ordinary sense. What matters is that the
degenerate cases render sanely:

- **Non-unit node** (part / chapter / section) — `unit_marker` returns `MARKER_NONE`. Group rows in
  the outline and `<summary>` rows in the rail get no marker, and the partials render nothing. This
  is reachable: both templates recurse over container nodes.
- **Unit with `unit_type` unset** — the model's `clean()` forbids it, but the field is
  `null=True, blank=True` at the database level, so a hand-edited or imported row can carry `None`.
  `unit_marker` returns `MARKER_NONE` for it (fail quiet), never raises: a 500 on the course
  outline would be a far worse outcome than an unmarked row.
- **No node at all** — a partial included without `with node=…` resolves the variable to Django's
  `string_if_invalid` (default `''`). The `getattr(node, "kind", None)` guard in §1 returns
  `MARKER_NONE`; without it, `is_quiz_unit('')` raises `AttributeError` and 500s the page. This is
  the one degenerate case that is a *coding* mistake rather than a data state, and it is guarded
  because the cost of the guard is one `getattr` and the cost of omitting it is a white-screen
  course outline.
- **Quiz with `obligatory = False`** — returns `MARKER_QUIZ`. Not an error, but the case that most
  invites a wrong implementation, so it is pinned by a test.
- **Completed additional unit** — carries both `✓` (leading, in the rail) and the kind marker
  (trailing). Intended, and the reason the icon trails.

## Testing

### Existing tests this change touches

Four existing files are affected. Naming them is part of the deliverable — three of them go
**silently** wrong rather than red, which is the failure mode this list exists to prevent.

1. **`tests/test_e2e_uniform_block_width.py::test_lesson_title_caps_in_a_two_item_head`** — must be
   repaired, not merely re-run. It works today because the `<h1>`'s *flex target* (~746px, the head
   minus the gap and the pill) exceeds the 736px prose cap, so `max-width` is what holds the title
   down and `title_w < 738` bites. The new `flex: 0 1 auto` makes the `<h1>` shrink-to-fit, so
   `title_w` becomes the title's content width (tens of px for the seeded title), the assertion
   passes **vacuously**, and the pin dies without ever going red. Repair: seed a title whose natural
   content width exceeds 736px so the cap still bites, and re-point the fixture-validity guard from
   "the head is a two-item row" to "the title's uncapped content would exceed the cap". The repaired
   test is stronger than the original — with content far above the cap, the docstring's reason for
   avoiding an exact `abs(title_w - 736) < 2` assertion no longer applies.
2. **`tests/test_e2e_unit_nav.py::test_quiz_chrome_tracks_the_column_across_both_page_states`** —
   its `.lesson-unit__title` cap assertion is defused the same way and needs the same repair.
3. **`tests/test_e2e_unit_head_layout.py`** — the dedicated e2e for `.lesson-unit__head`'s flex
   contract, and the pin for the mobile behaviour in §4. Its `MEASURE` does
   `head.querySelector('.lesson-unit__title')`, which is descendant-based and still finds the `<h1>`
   through the new wrapper, so the selector survives. Its phone assertions
   (`done_top >= title_bottom - 1`, `reset_top >= title_bottom - 1`) are exactly what the group's
   `flex-basis: 100%` rule preserves. **Expected outcome: unchanged, all green.** If any of those
   four assertions goes red, the mobile rule is wrong — do not update the test to match.
4. **`tests/test_quiz_previewer_render.py`** — renders `_quiz_article.html` directly via
   `render_to_string(build_quiz_context(...))` and must be re-run and updated for the new
   `.lesson-unit__head` / `.lesson-unit__heading` wrappers.

### Unit — `unit_marker` and `unit_marker_label`

New tests in `tests/test_unit_marker.py`. Every branch, including the ones that exist to be
*silent*:

| Input | `unit_marker` | `unit_marker_label` |
| --- | --- | --- |
| lesson, `obligatory=True` | `MARKER_NONE` | `""` |
| lesson, `obligatory=False` | `MARKER_ADDITIONAL` | `"Additional"` |
| quiz, `obligatory=True` | `MARKER_QUIZ` | `"Quiz"` |
| quiz, `obligatory=False` | `MARKER_QUIZ` | `"Quiz"` |
| non-unit node (e.g. chapter) | `MARKER_NONE` | `""` |
| unit with `unit_type=None` | `MARKER_NONE` | `""` |
| `""` (the `string_if_invalid` case) | `MARKER_NONE` | `""` |
| `None` | `MARKER_NONE` | `""` |

The two quiz rows are a pair on purpose: together they pin that `obligatory` is ignored on a quiz,
which one row alone cannot. The last two rows pin the `getattr` guard.

### Render — one test per rendered surface (four)

Each asserts the marker is **present** for an additional unit and for a quiz, **and absent for a
required lesson**. The absence assertion is the load-bearing one: it is what pins "required is the
unmarked default", and without it every mutant that marks every row stays green. Each also asserts
the rendered modifier class equals `f"unit-kind-chip--{MARKER_QUIZ}"` (resp. `unit-kind--…`) read
from the constant, so a rename that misses the templates goes red (§1).

1. **Course outline** (`courses:course_outline`) — a `.unit-kind-chip` is present, and is **inside**
   the `.outline-unit` anchor (not a detached sibling). New test in `tests/test_unit_marker.py`.
2. **Unit page, lesson** (`courses:lesson_unit`) — a `.unit-kind-chip` is present inside
   `.lesson-unit__heading`, and the `<h1 data-math-title>` does **not** contain it.
3. **Unit page, quiz** (`courses:quiz_unit`) — the same two assertions, on the quiz template.
4. **Contents rail** — joins the existing `tests/test_unit_nav_render.py`. A `.unit-kind` is present
   with its accessible name (substring containment, per §3), and it is the **last element child** of
   `.unit-tree__unit`, after `.unit-tree__label`. This position assertion is required, not optional:
   the leading-vs-trailing decision is the whole subject of two structural arguments in §4, and
   without it that decision is unpinned.

**Every rail/drawer selector must be scoped.** `_unit_shell.html` renders the whole tree **twice**
per unit page — once into the rail (`[data-unit-tree-list]`) and once into the drawer
(`[data-unit-drawer-list]`) — so every unit emits two `.unit-tree__unit` rows and two `.unit-kind`
wrappers in one document. An unscoped `select_one` silently tests only the rail copy, a
`len(select(...)) == 1` assertion fails on a **correct** build, and a Playwright `.unit-kind`
locator is a strict-mode violation. This is the same hazard `_unit_shell.html:8-10` already
documents for `[data-unit-tree-toggle]`. Test 4 targets `[data-unit-tree-list] .unit-tree__unit`
explicitly; the drawer copy is covered by the e2e below.

The `data-math-title` assertion appears on **both** article templates (2 and 3), because
`_lesson_article.html:7` and `_quiz_article.html:5` both carry that attribute and the constraint in
§4 is unconditional. One of the two uses a unit title containing maths, asserting the title still
typesets with the chip as a sibling; that case joins the existing
`tests/test_title_math_markers.py` suite rather than re-creating its machinery.

### e2e — `tests/test_e2e_unit_nav.py`, plus a `tests/capture_unit_marker_screenshots.py`

Every geometric claim below is written as a **differential** assertion. Measuring a position with
the rule present proves nothing — the marker sits somewhere either way — so each one is either a
comparison between two rendered rows or a mechanical A/B via `page.add_style_tag`.

**Desktop, rail gutter.** Take two units with markedly different title lengths in the same open
group, scoped to `[data-unit-tree-list]`, and assert their `.unit-kind` boxes share an `x` within
~1px, and that `x` is within a few px of the row's right content edge. Both facts are false when
`.unit-tree__label` has no `flex-grow`, which is what makes the paired mutant killable.

**Desktop, unit page.** The whole §4 heading-group resolution — the group, the reset, the source
order, `align-items: baseline` — otherwise has **zero** executable coverage, since render tests 2
and 3 are DOM-containment checks that a CSS deletion leaves green. Assert on both
`_lesson_article.html` and `_quiz_article.html` that the chip's left edge is within a few px of
`title_right + gap`, and far short of the head's right edge. Run in both rail states (expanded and
`html.unit-tree-collapsed`), since the collapsed state is where the title's cap changes where
`title_right` falls.

**Phone, 390×780 — the drawer must actually be opened.** `.unit-drawer` is `display: none` at base
(`courses.css:946`), is revealed only inside `@media (max-width: 640px)` via
`.unit-drawer:not([hidden])` (`courses.css:961`), and carries a literal `hidden` attribute until
`unit_nav.js` responds to the footer `[data-unit-drawer-open]` trigger. The required sequence:

1. resize to 390×780;
2. click the footer Contents trigger;
3. wait for `[data-unit-drawer]` to lose `hidden`;
4. assert `.unit-kind__label` inside `[data-unit-drawer-list]` has `box["width"] >= 30` **and**
   `box["height"] >= 8`.

**Step 4's thresholds are the point, and "non-empty" is not good enough.** `.visually-hidden` is
1px × 1px with a zero clip rect, which Playwright reports as **visible with a non-empty box** — so a
`bounding_box() is not None` assertion passes on a fully-hidden label and on the partial revert
(`position: static` only) that §4 calls the likeliest wrong implementation. A rendered "Quiz" or
"Dodatkowa" at `.82rem` is comfortably wider than 30px and taller than 8px; 1×1 is not. Without a
numeric floor the headline falsification below cannot go red.

Also at 390×780:

- assert the drawer row shape for a **completed additional** unit is a single flex line —
  `.unit-tree__check`, `.unit-tree__label` and `.unit-kind` all share a top within a few px — which
  is what catches the `flex-wrap: wrap` orphan §4 rejects;
- **A/B the label's wrap points**: record `.unit-tree__label`'s `getBoundingClientRect().height` for
  a fixed long title, then re-measure with `page.add_style_tag` neutralising
  `.unit-tree__label { flex: 1 1 auto }`, and assert the two are equal. This is the measurement §4
  requires rather than assumes, and it is mechanical rather than a remembered baseline;
- a long `\(…\)` maths title in the drawer, asserting no `.katex` box intersects `.unit-kind`'s rect
  — the re-earned audit §4 requires for the `courses.css:2310-2350` comment;
- the **outline** page at 390 wide with a long single-word / Polish title, asserting the row's
  content stays within its box — the pin for the `min-width: 0` change to `.outline-unit__title`.

**Screenshots** (`tests/capture_unit_marker_screenshots.py`): both glyphs at rail size, the outline
row at rest / hover / `:target`, and the unit-page head — all in light **and** dark, with dark
judged on its own rather than inferred from light. This is where the §3 glyph-legibility acceptance
step and the §4 `--surface-sunken` collision are actually looked at.

### Falsification

Each test is falsified against a mutant chosen from its own failure mode, not merely run green:

- `unit_marker` returning `MARKER_ADDITIONAL` for a non-obligatory quiz → the quiz-pair test goes
  red.
- `unit_marker`'s `additional` branch rewritten as `not is_obligatory_lesson(node)` → the non-unit
  and `unit_type=None` rows go red. (This is the specific over-simplification §1 warns against.)
- The `getattr` guard replaced by `node.kind` → the `""` / `None` rows go red.
- `unit_marker` returning a marker unconditionally → each surface's *absence* assertion goes red.
- `unit_marker_label` returning a non-empty string for `MARKER_NONE` → the label column's `""` rows
  go red.
- The rail icon rendered leading instead of trailing → the rail test's last-element-child assertion
  goes red.
- `.unit-tree__label`'s `flex: 1 1 auto` reverted to no `flex` → the desktop shared-`x` gutter
  assertion goes red.
- The `.unit-drawer__list .unit-kind__label` un-hide rule deleted → the 30×8 threshold goes red.
  Falsify **also** against the partial revert (`position: static` only), since that is the likelier
  mistake and it is the case a "non-empty box" assertion would have missed.
- `.lesson-unit__heading > .lesson-unit__title { flex: 0 1 auto }` deleted → the desktop unit-page
  chip-position assertion goes red, on both article templates.
- The mobile `.lesson-unit__heading { flex-basis: 100% }` deleted → `test_e2e_unit_head_layout.py`'s
  phone assertions go red.
- `flex-wrap: wrap` added to `.unit-drawer__list .unit-tree__unit` → the single-flex-line drawer
  assertion goes red.

A mutant must be removed by editing it out, never by `git checkout` of the file, which would
destroy the surrounding work.
