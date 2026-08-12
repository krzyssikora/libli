# Student-facing unit kind markers

## Purpose

Students cannot tell one unit from another. In the course outline and in the contents rail, a
quiz, an obligatory lesson and a non-obligatory lesson render identically — title, optional `✓`,
tags, note badge — so a student has no way to know that a row is a test they are about to sit, or
that a row is extra material they are not required to finish.

Both facts are already stored. `ContentNode.unit_type` is `lesson | quiz` and
`ContentNode.obligatory` is a boolean (**defaulting to `True`** — relevant to every fixture below).
The teacher-facing builder already renders both (`templates/courses/manage/_tree_node.html` draws
`L`/`Q` badges and `icm--req`/`icm--opt` glyphs). Only the student surfaces are silent. This design
makes them speak.

**No model or migration change.** `unit_type` and `obligatory` exist and are already authored; this
is a presentation change over data the author already controls.

### The state model: one axis, not two

| State | Condition | Marker |
| --- | --- | --- |
| Required lesson | `unit_type == lesson and obligatory` | **none** (the unmarked default) |
| Additional | `unit_type == lesson and not obligatory` | `Additional` |
| Quiz | `unit_type == quiz` | `Quiz` |

A quiz is **always** just "quiz". Its stored `obligatory` flag is deliberately ignored, because it
already has no student-visible consequence: `courses/rollups.py::is_obligatory_lesson` requires
`unit_type == LESSON`, so a quiz never contributes to `required_total` whatever its flag says.

**Required is unmarked.** It is by far the most common state, and marking it would put a chip on
nearly every row in the outline, which is the same undifferentiated wall the feature exists to
break up.

### Out of scope

- **The prev/next footer navigation** (`templates/courses/_unit_footer.html`). Declined at design
  time: the rail on the same page already carries the marker for every unit including the
  neighbours, so a second marker in a width-constrained sticky bar buys repetition. First follow-up
  to reconsider if a student reports being surprised by a quiz they clicked "Next" into.
- **The "My results" page** — quizzes only by construction, so a quiz marker would be noise.
- **Teacher *authoring* surfaces** — the builder tree already distinguishes these states. This
  exclusion is about authoring UI, **not** "any page a teacher can see": `_quiz_article.html` is
  shared with the **quiz previewer** (`previewing` branch), so a teacher previewing a quiz sees the
  chip. That is deliberate — the previewer's job is to show what a student sees.
- Any model, migration, or `FORMAT_VERSION` change.

## Architecture / components

### 1. `unit_marker(node)` — the single source of truth

Added to `courses/rollups.py`, beside the existing `is_obligatory_lesson` and `is_quiz_unit`.
Requires a new import, `from django.utils.translation import gettext_lazy` (the file imports
nothing from `django.utils.translation` today, and its import block is one name per line).

```python
MARKER_NONE = ""
MARKER_QUIZ = "quiz"
MARKER_ADDITIONAL = "additional"


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
cannot distinguish them. The quiz branch **does** delegate to `is_quiz_unit`, so the one predicate
that can be single-sourced is. Do not "simplify" the `additional` branch into
`not is_obligatory_lesson(node)` — that is precisely the mutant the tests exist to kill.

**The constants do not reach the templates.** A Django template cannot import a Python constant, so
`_unit_kind_icon.html` hardcodes `"quiz"` in its branch and both partials interpolate the raw key
into a class name. Renaming a constant therefore requires a grep of
`templates/courses/_unit_kind_*.html`; the render tests assert the rendered modifier class against
the constant, so a rename that misses the templates goes red rather than silent.

### 2. Exposure to templates: two filters on the node

In `courses/templatetags/courses_extras.py`:

- `unit_marker` — the marker key, for the CSS modifier class and the tests.
- `unit_marker_label` — the **translated** display word, or `""` for `MARKER_NONE`.

**Registration form is prescribed, not incidental:**

```python
from courses import rollups

register.filter("unit_marker", rollups.unit_marker)
register.filter("unit_marker_label", rollups.unit_marker_label)
```

Writing the obvious `from courses.rollups import unit_marker` followed by
`@register.filter def unit_marker(node): return unit_marker(node)` **rebinds the module-level
name** and produces unbounded recursion on the first render — not an import error, so it passes
review and fails in the browser. If a decorator is preferred, follow the file's existing
`@register.filter(name="marks") def marks_filter(...)` precedent with a distinct function name.

`unit_marker_label` lives in `rollups.py`:

```python
UNIT_MARKER_LABELS = {
    MARKER_QUIZ: gettext_lazy("Quiz"),
    MARKER_ADDITIONAL: gettext_lazy("Additional"),
}

def unit_marker_label(node):
    return UNIT_MARKER_LABELS.get(unit_marker(node), "")
```

`gettext_lazy`, **not** `gettext`: a module-level dict is evaluated at import, before the request's
locale is active, and a non-lazy call there would freeze the first-seen language into the process.

Putting the words in Python is what makes each string authored once, and it is what lets the icon
partial put the word in a `title=` attribute — `{% include %}` cannot be used inside an attribute
value, so a label-partial could not serve both consumers.

**Filters on the node, not a key on the `build_outline` item dict.** `_outline_node.html` and
`_unit_tree_node.html` render a `build_outline` dict and could read a key, but
`_lesson_article.html` and `_quiz_article.html` receive only a bare `unit` `ContentNode`. A dict key
would cover two surfaces and force a second, driftable rule for the third.

### 3. Two shared partials

**`templates/courses/_unit_kind_chip.html`**

```html
{% load courses_extras %}{% with m=node|unit_marker %}{% if m %}<span
  class="badge unit-kind-chip unit-kind-chip--{{ m }}">{{ node|unit_marker_label }}</span>{% endif %}{% endwith %}
```

**`templates/courses/_unit_kind_icon.html`**

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

Both render **nothing at all** for `MARKER_NONE`, and both call `unit_marker` themselves, so no call
site can pass a state the partial did not compute.

The glyphs are given as concrete geometry rather than described, because §5's legibility argument is
about geometry: the `?` is a compound stroke path that reads as a blob if drawn naively at rail
size. The `fill="currentColor" stroke="none"` dot follows `_unit_shell.html`'s TOC-pin icon. Both
remain subject to the screenshot acceptance step in Testing.

**Include contract — always with `only`:**

```
{% include "courses/_unit_kind_chip.html" with node=item.node only %}
{% include "courses/_unit_kind_icon.html" with node=item.node only %}
{% include "courses/_unit_kind_chip.html" with node=unit only %}
```

`only` is required, not stylistic. Without it `{% include %}` inherits the parent context, and this
app **already has a `"node"` context key elsewhere** (`courses/views.py:782`,
`progress_reset_confirm.html`). None of the four target surfaces has an ambient `node` today, so the
guard in §1 would suffice — but that is a property of those four contexts, not of the guard, and a
future context key would silently mark the *wrong* node rather than fail. `only` makes the contract
structural.

**Class contract (test selectors).** The chip emits `badge unit-kind-chip unit-kind-chip--<marker>`;
the icon wrapper emits `unit-kind unit-kind--<marker>`. `.unit-kind-chip` and `.unit-kind` are the
stable selectors; `.badge` is carried for the existing pill styling and is **not** a test selector.
`.unit-kind-chip` needs no CSS rule of its own. The `--<marker>` modifiers are **reserved test/debug
hooks with no styling attached today**, and §5 forbids giving them any.

**Accessible-name contract.** The `<svg>` is `aria-hidden`; `.unit-kind__label` is the text (visually
hidden on **every** surface — see the drawer decision in §4); the wrapper's `title=` is the hover
tooltip. The enclosing link's accessible name is computed **from contents**, so it depends on
completion state:

| Surface | Not completed | Completed |
| --- | --- | --- |
| Rail (`_unit_tree_node.html`) | "*<title>*, Quiz" | "Completed, *<title>*, Quiz" |
| Outline (`_outline_node.html`) | "*<title>*, Additional" | "*<title>*, Additional, Completed" |

The `✓` carries `aria-label="Completed"` and **leads** in the rail but **trails** in the outline,
which is why the orders differ. Render tests assert **substring containment** of the marker word,
never full-name equality — a full-name assertion written from one row would be red on the other.

### 4. The rendered surfaces

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
the wrapper, which would otherwise take `flex: 0 1 auto` and squash under a `flex: 1 1 auto` label.
`display: inline-flex` also makes `.icon`'s `flex: none` meaningful again for the glyph.
`var(--space-1)` is 4px (`app.css:75`); the surrounding block is token-driven.

**Outline page** — `templates/courses/_outline_node.html`.

The chip goes **inside** the `<a class="outline-unit">`, after `.outline-unit__title` and before the
`✓` badge — inside the anchor because the `✓` already is, and because it puts the state in the
link's accessible name.

`.outline-unit` is `display: flex` (`app.css:513`) and `.outline-unit__title` is `flex: 1`
(`app.css:521`), so the title box absorbs all free space and the chip sits in the **right gutter**:

```
Extra practice  ··············  [Additional]  ✓
```

Accepted, not worked around — it gives the outline the same right-hand marker column as the rail.
`.badge--done`'s `margin-left: auto` (`app.css:559`) is consequently **inert** here; the `✓`'s right
position comes from the title's `flex: 1`.

**One required CSS change, and it is *not* inert.** Edit `app.css:521` in place:

```css
.outline-unit__title { flex: 1; min-width: 0; overflow-wrap: break-word; }
```

`flex: 1` is `1 1 0%` with no `min-width: 0`, so the title's automatic minimum is its min-content
width and it cannot shrink below its longest word; `.outline-unit` itself does not wrap (only the
parent `li.outline-node--unit` does). A chip up to ~90px ("Additional" / "Dodatkowa") can therefore
push a 390px row past its box. **This change alters behaviour on rows carrying no marker at all**:
the `✓` is already a shrink-forcing sibling on every completed row, so today a long unbroken title
overflows the anchor and afterwards it breaks instead. That is an improvement, and it is accepted —
but it is a real change, not a no-op, and it has its own mutant in Falsification.

**Accepted colour collision:** `.badge` fills with `--surface-sunken` (`app.css:119`), and so do
`.outline-unit:hover` (`app.css:519`) and `.outline-node:target > .outline-unit` (`app.css:534`). On
a hovered row and on an internal-link landing the chip's fill matches the row and only its 1px
`--border-default` rim separates it. Accepted rather than patched: the rim is a real separation, and
a different surface token would invert the problem in one theme (a token that reads against the
hovered row can vanish against the row at rest). Hover and `:target` join the screenshot set so the
rim is looked at in both themes. `.badge--done` dodges this only by overriding the background with
`--success-subtle`; this chip is the first plain `.badge` inside `.outline-unit`.

**Contents rail** — `templates/courses/_unit_tree_node.html`.

The icon is **trailing** — after `.unit-tree__label`, last element child of `.unit-tree__unit`:

1. The `✓` already **leads**. `courses.css:788` sets `.unit-tree__check { margin-left: 0 }`
   specifically to cancel `.badge--done`'s `margin-left: auto`. A second leading glyph would make
   every completed *additional* unit begin with two marks.
2. Trailing puts the kind icons in the same right-hand gutter as `.unit-tree__count` and
   `.unit-tree__groupcheck` on group rows.

**A required CSS change makes that gutter real.** Group rows right-align their chrome only because
`.unit-tree__grouptitle` is `flex: 1` (`courses.css:736`). `.unit-tree__label` (`courses.css:789`)
carries **no** `flex` declaration, so it defaults to `flex: 0 1 auto`, a short title does not fill
the row, and the marker column would be ragged. Edit that rule **in place**:

```css
.unit-tree__label { flex: 1 1 auto; min-width: 0; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
```

`1 1 auto`, deliberately **not** `1 1 0`: basis `auto` preserves the label's current sizing, which
matters because the drawer overrides this class to `white-space: normal` (`courses.css:977`) in a
title column squeezed to ~98px. This runs against the general "use `flex: 1 1 0`" habit, so it is a
deliberate exception, verified by a mechanical A/B (see Testing).

**Mobile drawer — icons stay icon-only; discoverability comes from a legend, not per-row words.**

The drawer is a **touch** surface and the template's own comment records that "Touch has no hover",
so `title=` yields nothing there and a bare glyph would be unexplained.

The obvious fix — un-hiding `.unit-kind__label` at drawer scope — was **considered and rejected on a
width budget**, and that reasoning is recorded here so it is not re-attempted. `courses.css:981-984`
documents the drawer title column as already squeezed to ~98px. A glyph (~13px) plus "Dodatkowa"
(~58px at `.82rem`) plus the gap leaves the title roughly 20–30px, which is unusable; and because
`.unit-kind__label` has no `overflow-wrap`, the unbreakable word would paint outside its box and
overlap the title. Making the row `flex-wrap: wrap` does not rescue it either: flex line-breaking
uses each item's **hypothetical main size**, and with `flex: 1 1 auto` the label's base size is the
max-content width of the full title, which always exceeds a 98px line — so the row would break
*before* the label, stranding the leading `✓` (`flex: none`) alone on line 1, the title on line 2
and the marker on line 3. That is a three-line row with an orphan tick, and since `flex-wrap` is
unconditional it would regress **every completed unit in the drawer, including unmarked ones**.

Instead, `_unit_shell.html`'s `.unit-drawer__bar` (currently heading + close button) gains a
one-line legend beneath it, rendering each glyph once beside its word:

```html
<p class="unit-drawer__legend">
  {% include "courses/_unit_kind_legend_item.html" with marker="additional" %}
  {% include "courses/_unit_kind_legend_item.html" with marker="quiz" %}
</p>
```

This costs one line at the top of the drawer and **zero per-row width**, keeps `.unit-kind__label`
visually hidden on every surface (so the accessible name in §3 is unchanged everywhere), and needs
no `.unit-drawer__list .unit-kind*` rules at all. The legend renders unconditionally rather than
being gated on "does this course contain any marked unit" — gating would need a tree scan, and a
static two-item line is cheap. A course with neither quizzes nor additional units shows a legend for
symbols it never uses; that is the accepted cost, and the first thing to revisit if it reads as
noise.

**Unit page** — `templates/courses/_lesson_article.html` and `templates/courses/_quiz_article.html`.

The naive placement — chip as a direct flex child of `.lesson-unit__head` — **does not work**:

- Inside the shell `.unit-shell__main > .lesson, > .quiz` are `max-width: none`
  (`courses.css:660-661`), so the head spans the full ~872px column, not 46rem.
- `.lesson-unit__head` is `justify-content: space-between` (`courses.css:828`) and
  `.lesson-unit__head .lesson-unit__title` is `flex: 1` (`courses.css:834`).
- Under `html.unit-tree-collapsed` the **title** is capped at the prose measure
  (`courses.css:~1097`) while the head is not, so `space-between` strands the chip mid-row.
- On the quiz page there is no done pill, so a lone chip flies to the far right.

**Resolution: an inner heading group with an explicit flex reset.** Both templates wrap the `<h1>`
and the chip:

```html
<div class="lesson-unit__heading">
  <h1 class="lesson-unit__title" data-math-title>{{ unit.title }}</h1>
  {% include "courses/_unit_kind_chip.html" with node=unit only %}
</div>
```

In `courses.css`, **immediately after the `.lesson-unit__head .lesson-unit__title` rule at
`:834-835`** and therefore **before** the `@media` block at `:985-987`:

```css
.lesson-unit__heading { flex: 1 1 auto; min-width: 0;
  display: flex; align-items: baseline; gap: var(--space-3); }
.lesson-unit__heading > .lesson-unit__title { flex: 0 1 auto; }
```

and inside the `@media (max-width: 640px)` block beside `:986`:

```css
.lesson-unit__heading { flex-basis: 100%; flex-wrap: wrap; }
```

**The group does NOT wrap at desktop.** `flex-wrap` is confined to the mobile rule, because at
desktop it would put the chip on its own line for exactly the titles the design cares about: in the
collapsed state the `<h1>`'s hypothetical size is `min(max-content, 736px)` while a lesson page's
group line is only `head(~872) − pill(~110) − gap(16) ≈ 746px`, so `736 + 12 + ~78 = ~826 > 746` and
any title reaching the cap would push the chip down. Without wrap the `<h1>` shrinks instead — it
keeps `min-width: 0` and `overflow-wrap: break-word` from `:834-835`, since the reset overrides only
`flex` — and the chip stays on the title's line at every width. At phone width the wrap is wanted,
which is why it is added there together with `flex-basis: 100%`.

Note this is why the capped-title e2e and the chip-geometry e2e do **not** conflict: the cap fixture
seeds a *required* lesson (`obligatory` defaults to `True`), which emits **no chip**, so its `<h1>`
is alone in the group and still reaches the 736px cap. The chip fixtures seed additional/quiz units,
where the `<h1>` shrinks to make room. Both are stated in Testing.

**The reset is mandatory.** `.lesson-unit__head .lesson-unit__title` (`:834`) is a **descendant**
selector, so it still matches the `<h1>` through the wrapper and would make it `flex: 1 1 0%`
*inside the group* — absorbing every pixel and pushing the chip to the far right, reproducing the
failures this section fixes. It is (0,2,0), the same specificity, so source order decides.

**The mobile rule is mandatory too, for a reason source order does not cover.** Today
`.lesson-unit__head .lesson-unit__title { flex-basis: 100% }` at `:986` resolves 100% against
`.lesson-unit__head`, which is what forces `.unit-done` and `.lesson-unit__reset` onto a second row
at phone width (`courses.css:981-984`). After the wrapper it resolves against
`.lesson-unit__heading`, whose basis is content-derived, so the head's wrap decision would depend on
the group's max-content contribution and a short title would keep the pill beside it. Giving the
**group** `flex-basis: 100%` restores the old behaviour *by construction*; inside the group `:986`
still gives the `<h1>` basis 100%, so the chip wraps beneath the title.
`tests/test_e2e_unit_head_layout.py` is the pin.

Further notes:

- What makes `space-between` safe is **the group's `flex: 1 1 auto`**, not the child count. The head
  has **one** child on the quiz page and **two or three** on the lesson page (group, done pill, and
  the conditional `.lesson-unit__reset` from `_lesson_article.html:28-33`). The group absorbs the
  free space in every case, so nothing is left to distribute and the one-child quiz row is covered
  by the same rule. This is asserted (pill's left edge ≈ group's right edge) rather than argued.
- `align-items: baseline` puts the chip on the `<h1>`'s baseline. `.lesson-unit__head`'s own
  `align-items: flex-start` applies to the group as a whole, and `.badge`'s `vertical-align: middle`
  is inert on a flex item, so without this the chip would top-align against a full-size heading.
- The collapsed-TOC allow-list (`courses.css:~1097`) still names `.lesson-unit__title`, so the
  heading keeps its prose measure while the group widens. **No allow-list edit** — and the comment
  at `:1076` records that `.lesson-unit__head` was deliberately taken off that list, which
  `.lesson-unit__heading` must likewise stay off.

`_quiz_article.html` also gains the `.lesson-unit__head` wrapper it currently lacks. That reuse is
safe: `.lesson-unit__head .lesson-unit__title { margin: 0 }` (`:834`) and
`.quiz .lesson-unit__title { margin-bottom: var(--space-6) }` (`:293`) are equal specificity
(0,2,0), so `:834` wins on source order, while `.lesson-unit__head` supplies the identical
`margin-bottom`. **The new head wraps only the `.lesson-unit__heading` group**; the
`{% if previewing %}` `<aside data-quiz-preview-notice>` stays a **sibling after** the head. Pulling
it inside would break `test_e2e_unit_nav.py`'s `[data-quiz-preview-notice]` column-width assertion.

**Hard constraint:** the chip must never go **inside** `<h1 data-math-title>` — `math.js` typesets
that element's contents. The chip is a **sibling** of the `<h1>`, inside the heading group.

**Maths-audit comment and its executable half must both be updated.** `courses.css:2310-2350`
records a measured drawer audit listing the siblings a KaTeX box was checked against
(`.unit-tree__count`, `.unit-tree__groupcheck`, `.unit-tree__check`, `.unit-tree__chevron`,
`.unit-drawer__close`) and says to re-check "if the drawer's title column ever narrows further".
This change adds `.unit-kind` inside `.unit-tree__unit` **and** alters `.unit-tree__label`'s flex —
exactly that trigger. Add `.unit-kind` to the comment's list, and add it to the **same list in
`tests/capture_title_math_screenshots.py`** (the `btns` selector at ~:483), which is the automated
half of that audit; updating only the comment leaves the executable check testing a stale set and
green over the new collision. While editing, refresh the comment's three stale refs — it cites
`.unit-tree__label (:755)`, `.unit-tree__grouptitle (:702-704)` and `courses.css:943`, where the
actual lines are 789, 736-738 and 977.

### 5. The glyphs

Monochrome line SVGs on the `viewBox="0 0 24 24"` grid (`currentColor`, never emoji); geometry in §3.

- **Quiz** — `?` in a circle. Chosen over a clipboard/checklist, which is mush at the ~1em the rail
  renders (`.unit-tree` is `font-size: .82rem`, `courses.css:665`). The "reads as help" objection is
  theoretical here: there is no help affordance in the rail, the drawer, or an outline row.
- **Additional** — `+` in a circle, echoing the `+{{ additional_done }} additional` rollup on the
  group row above (`_outline_node.html:23`). Same shape family, so the two read as one system.

**Colour: the marker never introduces a hue of its own — it inherits the row's.** `.icon` is
`stroke: currentColor` and the marker keeps that, with **no** colour rule on any surface:

- On `.unit-tree__unit.is-active` the row is `--primary` (`courses.css:774`), so the icon is too —
  the current unit is the row a student most needs to find, and the marker joining its accent is
  correct, not a competing third hue.
- On `.is-done` the row is `--text-tertiary` (`courses.css:770`), so the icon fades with the row.
  Intended: a completed unit is quieter, and the marker should not outshout its own title.
- The marker never adds a hue the row lacks, which keeps `✓` (`--success`) and the active row
  (`--primary`) as the rail's only two signals, and keeps the distinction on **shape plus the
  accessible name** — the colour-blind-safe answer.

There is deliberately **no** conditional "quieten it if too loud" rule: untestable, and a
rail-specific class from a surface-agnostic partial would contradict §3.

### 6. Wording and translation

The non-obligatory state is worded **"Additional"**, not "Optional" — `_outline_node.html:23`
already renders `+N additional` and `build_outline` calls the field `additional_done`, so the
counter and the chips name the same set.

**In Polish the two share a root but not an inflection, and that is accepted.** The existing msgid
`additional` is `"dodatkowe"` (`locale/pl/LC_MESSAGES/django.po:4208`), the form agreeing with its
count phrase. The new msgid `Additional`, naming one unit, takes `msgstr "Dodatkowa"`. A Polish
reader connects `dodatkow-` across both; forcing one surface form would make one ungrammatical. The
existing entry is **not** revisited.

The msgid `Quiz` **already exists**: `locale/pl:851` carries `msgstr "Quiz"`, sourced from
`courses/models.py:198` (the `UnitType.QUIZ` label), `manage/_add_affordance.html:26` and
`manage/editor/editor.html`. Reusing that exact msgid is required — the chip and the model's choice
label must never diverge.

`makemessages` regenerates **both** catalogs: `locale/pl` and `locale/en` (source, msgstrs empty).
It can fuzzy-prefill a wrong translation from a near-neighbour msgid, so any `#, fuzzy` on
`Additional` must be inspected and cleared — two deletions, the `#, fuzzy` line and the wrong
`msgstr`. The `.po` → `.mo` compile lands in the same change.

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

`unit_marker` is a pure function of three already-loaded fields. Every surface reads it through the
same filter, so they cannot disagree, and none triggers a database round-trip. `build_outline`,
`build_unit_nav` and the rollups are untouched. The `drafts` / publish filtering is unaffected: a
unit `unit_is_visible` excludes never reaches a template.

**Template-render cost, accepted.** One `{% include %}` and two filter calls per outline row and per
rail row, including the silent required-lesson majority. On the matematyka import (793 units) that
is ~800 extra includes on the outline and ~1600 per unit page (rail + drawer each render the full
tree). Pure in-memory template work with no query behind it, on pages already rendering those rows;
no measurement is warranted before merge. If a regression is ever observed there, the cheap fix is
hoisting the marker into the `build_outline` dict for the dict-bearing surfaces — but not before a
measurement justifies splitting the rule.

## Error handling

- **Non-unit node** (part / chapter / section) — `MARKER_NONE`; group rows and `<summary>` rows get
  nothing. Reachable: both templates recurse over containers.
- **Unit with `unit_type` unset** — `clean()` forbids it, but the field is `null=True, blank=True` at
  the database level, so a hand-edited or imported row can carry `None`. Returns `MARKER_NONE` (fail
  quiet), never raises: a 500 on the course outline is far worse than an unmarked row.
- **No node at all** — a partial included without `node=` resolves to `string_if_invalid` (default
  `''`). The `getattr` guard returns `MARKER_NONE`; without it `is_quiz_unit('')` raises
  `AttributeError`. A coding mistake rather than a data state, guarded because the guard costs one
  `getattr` and omitting it costs a white-screen outline. `only` on every include (§3) is the
  structural half of the same defence.
- **Quiz with `obligatory = False`** — `MARKER_QUIZ`. The case that most invites a wrong
  implementation, so it is pinned by a test.
- **Completed additional unit** — carries both `✓` (leading, in the rail) and the marker (trailing).
  Intended, and the reason the icon trails.

## Testing

### Existing tests and sites this change touches

Six existing locations. Naming them is part of the deliverable — most go **silently** wrong rather
than red.

1. **`tests/test_e2e_uniform_block_width.py::test_lesson_title_caps_in_a_two_item_head`** — must be
   **repaired**. It works today because the `<h1>`'s *flex target* (~746px) exceeds the 736px cap,
   so `max-width` holds the title and `title_w < 738` bites. The new `flex: 0 1 auto` makes the
   `<h1>` shrink-to-fit, so `title_w` becomes the content width, the assertion passes **vacuously**,
   and the pin dies without going red. Repair: seed a title whose natural content exceeds 736px so
   the cap still bites. The fixture-validity guard must be re-pointed, and **the mechanism is
   prescribed** because the obvious one measures nothing (with the cap applied and text wrapping,
   `scrollWidth == clientWidth`): neutralise `max-width` with `page.add_style_tag`, measure the
   uncapped content width, assert `> 736`, then restore. Equivalently assert `group_w > 738`, which
   is directly measurable and carries the same claim.
2. **`tests/test_e2e_unit_nav.py::test_quiz_chrome_tracks_the_column_across_both_page_states`** —
   its `.lesson-unit__title` cap assertion is defused identically and needs the same repair.
3. **`tests/test_e2e_uniform_block_width.py` (~:150-183)** — two inline comments this change
   falsifies: "the quiz page has no `.lesson-unit__head` at all" (it will have one) and "an uncapped
   title would measure ~746" (after the repair the mechanism is a >736px *content* width, not a
   746px flex target). The quiz page also becomes a second surface for the `.lesson-unit__head`
   column claim.
4. **`tests/test_e2e_unit_head_layout.py`** — the pin for §4's mobile rule. Its `MEASURE` does
   `head.querySelector('.lesson-unit__title')`, which is descendant-based and still finds the `<h1>`
   through the wrapper. Its phone assertions (`done_top >= title_bottom - 1`,
   `reset_top >= title_bottom - 1`) are exactly what `flex-basis: 100%` on the group preserves.
   **Expected outcome: unchanged, all green.** If any goes red the mobile rule is wrong — do not
   update the test to match.
5. **`tests/capture_title_math_screenshots.py` (~:483)** — its `btns` selector list is the
   executable half of the drawer maths audit and must gain `.unit-kind` (see §4).
6. **`tests/test_quiz_previewer_render.py`** — renders `_quiz_article.html` directly via
   `render_to_string(build_quiz_context(...))`; must be re-run and updated for the new
   `.lesson-unit__head` / `.lesson-unit__heading` wrappers. `tests/test_title_math_markers.py:157`
   documents `span.unit-tree__label (_unit_tree_node.html:15)`; add a one-line mention of the new
   trailing `.unit-kind` sibling to that docstring's surface inventory.

### Unit — `unit_marker` and `unit_marker_label`

New tests in `tests/test_unit_marker.py`. The label column asserts under the **default `en` locale**
(`config/settings/base.py:142`, `LANGUAGE_CODE = "en"`).

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

The two quiz rows are a pair on purpose: together they pin that `obligatory` is ignored on a quiz.
The last two pin the `getattr` guard. One extra row asserts `"Dodatkowa"` under
`translation.override("pl")`, which pins the §6 catalog entry end-to-end and proves the label is a
lazy proxy rather than a frozen string.

### Render — one test per rendered surface (four)

Each asserts the marker is **present** for an additional unit and for a quiz, **and absent for a
required lesson**. The absence assertion is load-bearing: without it every mutant that marks every
row stays green. Each also asserts the rendered modifier class against the constant (§1).

1. **Course outline** (`courses:course_outline`) — `.unit-kind-chip` is present **inside** the
   `.outline-unit` anchor, is the `.outline-unit__title`'s **next element sibling**, and **precedes**
   `.badge--done` on a completed row. The position assertions are required by the same standard as
   the rail's: §4 argues at length for right-gutter placement, and without them moving the chip
   before the title or after the `✓` keeps every outline assertion green.
2. **Unit page, lesson** (`courses:lesson_unit`) — `.unit-kind-chip` inside `.lesson-unit__heading`,
   and `<h1 data-math-title>` does **not** contain it.
3. **Unit page, quiz** (`courses:quiz_unit`) — the same two assertions.
4. **Contents rail** — joins `tests/test_unit_nav_render.py`. `.unit-kind` present with its
   accessible name (substring containment, §3), and the **last element child** of
   `.unit-tree__unit`.

**Every rail/drawer selector must be scoped.** `_unit_shell.html` renders the tree **twice** per unit
page — rail (`[data-unit-tree-list]`) and drawer (`[data-unit-drawer-list]`) — so every unit emits
two `.unit-tree__unit` rows and two `.unit-kind` wrappers. An unscoped `select_one` silently tests
only the rail, a `len(...) == 1` assertion fails on a **correct** build, and a Playwright
`.unit-kind` locator is a strict-mode violation — the hazard `_unit_shell.html:8-10` already
documents for `[data-unit-tree-toggle]`. Test 4 targets `[data-unit-tree-list] .unit-tree__unit`.

The `data-math-title` assertion appears on **both** article templates, since `_lesson_article.html:7`
and `_quiz_article.html:5` both carry it. One uses a maths title, asserting it still typesets with
the chip as a sibling; that case joins `tests/test_title_math_markers.py`.

### e2e — `tests/test_e2e_unit_nav.py`, plus `tests/capture_unit_marker_screenshots.py`

Every geometric claim is a **differential** assertion: measuring a position with the rule present
proves nothing, so each is either a comparison between two rendered rows or a mechanical A/B via
`page.add_style_tag`.

**Fixtures: `obligatory` defaults to `True`.** Every comparison row below must be an *additional* or
*quiz* unit, set explicitly — a required lesson emits no `.unit-kind` at all, so a default-factory
fixture yields zero elements and either a `None` bounding box or a vacuous pass.

**Desktop, rail gutter.** Two units with markedly different title lengths in the same open group,
both marked, scoped to `[data-unit-tree-list]`: assert their `.unit-kind` boxes share an `x` within
~1px, and that `x` is within a few px of the row's right content edge. Both are false when
`.unit-tree__label` has no `flex-grow`.

**Desktop, rail glyph size.** With a long title putting the row under shrink pressure, assert
`.unit-kind`'s rendered width ≈ the glyph's natural 1em. This is what kills a deletion of the
`.unit-kind` rule, which the gutter test cannot: a squashed-but-right-aligned wrapper still shares
its `x`.

**Desktop, unit page.** The whole §4 heading-group resolution otherwise has **zero** executable
coverage, since render tests 2–3 are DOM-containment checks a CSS deletion leaves green. On both
article templates, and in both rail states (expanded and `html.unit-tree-collapsed`):

- the chip's left edge is within a few px of `title_right + gap`, and far short of the head's right
  edge;
- on the lesson page, the **done pill's left edge is within a few px of the group's right edge** —
  this is what kills a deletion of the group's `flex: 1 1 auto`, which the chip-position assertions
  cannot (with `flex: 0 1 auto` the chip stays glued to the title; what moves is the pill).

**Phone, 390×780 — the drawer must actually be opened.** `.unit-drawer` is `display: none` at base
(`courses.css:946`), revealed only inside `@media (max-width: 640px)` via
`.unit-drawer:not([hidden])` (`:961`), and carries a literal `hidden` attribute until `unit_nav.js`
responds to the footer `[data-unit-drawer-open]` trigger. Sequence: resize; click the footer Contents
trigger; wait for `[data-unit-drawer]` to lose `hidden`; then assert.

Assertions at that size:

- the `.unit-drawer__legend` is present with a **non-trivial** box —
  `width >= 30` and `height >= 8`. The thresholds are the point: `.visually-hidden` is 1px × 1px
  with a zero clip rect, which Playwright reports as **visible with a non-empty box**, so a
  `bounding_box() is not None` assertion cannot distinguish a rendered legend from a hidden one;
- each row's `.unit-kind` and `.unit-tree__label` rects **do not intersect** (plain text, not just
  maths) — the residual-width check the drawer column's ~98px demands;
- **A/B the label's wrap points**: record `.unit-tree__label`'s
  `getBoundingClientRect().height` for a fixed long title, re-measure with `page.add_style_tag`
  neutralising `.unit-tree__label { flex: 1 1 auto }`, assert equal. Mechanical rather than a
  remembered baseline;
- a long `\(…\)` maths title, asserting no `.katex` box intersects `.unit-kind`'s rect — the
  re-earned audit §4 requires;
- the **outline** page at 390 wide with a long unbroken / Polish title, asserting the row's content
  stays within its box — the pin for `.outline-unit__title`'s `min-width: 0`.

**Screenshots** (`tests/capture_unit_marker_screenshots.py`): both glyphs at rail size, the outline
row at rest / hover / `:target`, the unit-page head, and the drawer legend — light **and** dark,
with dark judged on its own. This is where §3's glyph-legibility acceptance step and §4's
`--surface-sunken` collision are actually looked at.

### Falsification

Each test is falsified against a mutant from its own failure mode, not merely run green:

- `unit_marker` → `MARKER_ADDITIONAL` for a non-obligatory quiz → the quiz-pair test goes red.
- `unit_marker`'s `additional` branch → `not is_obligatory_lesson(node)` → the non-unit and
  `unit_type=None` rows go red.
- The `getattr` guard replaced by `node.kind` → the `""` / `None` rows go red.
- `unit_marker` returning a marker unconditionally → each surface's *absence* assertion goes red.
- `unit_marker_label` returning a non-empty string for `MARKER_NONE` → the `""` rows go red; and
  `gettext_lazy` → `gettext` → the `translation.override("pl")` row goes red.
- Rail icon rendered leading instead of trailing → the last-element-child assertion goes red.
- The chip moved before `.outline-unit__title` → the outline next-element-sibling assertion goes red.
- `.unit-tree__label`'s `flex: 1 1 auto` reverted → the shared-`x` gutter assertion goes red.
- The `.unit-kind` rule deleted → the rail glyph-size assertion goes red.
- `.lesson-unit__heading > .lesson-unit__title { flex: 0 1 auto }` deleted → the desktop chip-position
  assertion goes red on both templates.
- `.lesson-unit__heading`'s `flex: 1 1 auto` deleted → the pill-position assertion goes red.
- The mobile `.lesson-unit__heading { flex-basis: 100%; flex-wrap: wrap }` deleted →
  `test_e2e_unit_head_layout.py`'s phone assertions go red.
- `flex-wrap: wrap` added to the group at **desktop** → the chip-position assertion goes red for a
  capped-length title.
- The drawer legend removed → the 30×8 legend assertion goes red.
- `.outline-unit__title`'s `min-width: 0` reverted → the 390-wide outline containment assertion goes
  red.

A mutant must be removed by editing it out, never by `git checkout` of the file, which would destroy
the surrounding work.
