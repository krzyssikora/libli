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

### 2. Exposure to templates: one filter, one tag

In `courses/templatetags/courses_extras.py`:

- `unit_marker` — a **filter**; the marker key, for the CSS modifier class and the tests.
- `marker_label` — a **simple tag**; marker key → translated word.

**Registration form is prescribed, not incidental:**

```python
from courses import rollups

register.filter("unit_marker", rollups.unit_marker)
register.simple_tag(rollups.marker_label, name="marker_label")
```

**There is deliberately no node→label filter.** An earlier draft had one, and it meant every
rendered chip and icon derived the marker **twice** — once for `{% with m=… %}` and again inside the
label lookup. Both partials already hold `m`, so they call `{% marker_label m %}` instead; the tag
also works inside an attribute value, which is what the icon's `title=` needs. One derivation per
render, one lookup function, and no unused registration left behind.

Writing the obvious `from courses.rollups import unit_marker` followed by
`@register.filter def unit_marker(node): return unit_marker(node)` **rebinds the module-level
name** and produces unbounded recursion on the first render — not an import error, so it passes
review and fails in the browser. If a decorator is preferred, follow the file's existing
`@register.filter(name="marks") def marks_filter(...)` precedent with a distinct function name.

The labels live in `rollups.py`, keyed on the **marker** rather than the node, so a caller holding
only a marker string reaches the same words as one holding a node:

```python
UNIT_MARKER_LABELS = {
    MARKER_QUIZ: gettext_lazy("Quiz"),
    MARKER_ADDITIONAL: gettext_lazy("Additional"),
}

def marker_label(marker):
    """Marker key -> translated word; "" for MARKER_NONE or any unknown key.

    Keyed on the marker, not the node: both partials already hold `m` from
    their own {% with %}, so this avoids deriving the marker a second time.
    """
    return UNIT_MARKER_LABELS.get(marker, "")
```

`gettext_lazy`, **not** `gettext`: a module-level dict is evaluated at import, before the request's
locale is active, and a non-lazy call there would freeze the first-seen language into the process.

Putting the words in Python is what makes each string authored once, and it is what lets the icon
partial put the word in a `title=` attribute cleanly. Note the precise reason a *label partial*
could not serve both consumers: it is **not** that `{% include %}` is illegal inside an attribute —
Django templates are plain text substitution with no HTML awareness, so `title="{% include … %}"`
compiles and renders. It is that an include's output is inserted **unescaped** (a quote or `&` in a
translated string would break out of the attribute) and it drags the partial's surrounding
whitespace and newlines into the attribute value. A simple tag returning a lazy string has neither
problem.

**Filters on the node, not a key on the `build_outline` item dict.** `_outline_node.html` and
`_unit_tree_node.html` render a `build_outline` dict and could read a key, but
`_lesson_article.html` and `_quiz_article.html` receive only a bare `unit` `ContentNode`. A dict key
would cover two surfaces and force a second, driftable rule for the third.

### 3. Two shared partials

**`templates/courses/_unit_kind_chip.html`**

```html
{% load i18n courses_extras %}{% get_current_language as LANGUAGE_CODE %}{% with m=node|unit_marker %}{% if m %}<span
  class="badge unit-kind-chip unit-kind-chip--{{ m }}"
  lang="{{ LANGUAGE_CODE }}">{% marker_label m %}</span>{% endif %}{% endwith %}
```

**`templates/courses/_unit_kind_glyph.html`** — the glyph markup, authored **once**, keyed on a bare
marker string `m`. Split out from the icon partial so the geometry lives in exactly one file, and
any future consumer holding only a marker string reuses it rather than copying the paths.

```html
{% if m == "quiz" %}
  <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <circle cx="12" cy="12" r="9"/>
    <path d="M9.4 9.3a2.7 2.7 0 0 1 5.2.9c0 1.8-2.6 2.4-2.6 2.4"/>
    <circle cx="12" cy="16.6" r=".95" fill="currentColor" stroke="none"/>
  </svg>
{% elif m == "additional" %}
  <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <circle cx="12" cy="12" r="9"/>
    <path d="M12 8.2v7.6M8.2 12h7.6"/>
  </svg>
{% endif %}
```

**Three-way, not `{% if %}…{% else %}`.** The "renders nothing for `MARKER_NONE`" guarantee belongs
to the chip and icon partials, which wrap their body in `{% if m %}`; this partial has no such guard
of its own. With an `{% else %}` branch, including it with `m=""` — or with a literal typo'd in a
future call site — would silently emit the *additional* `+` glyph rather than nothing. Since §1
already records that the templates hardcode these strings and that a rename needs a manual grep, the
`{% else %}` is precisely the branch a missed rename lands in. A render test pins it (see Testing).

**`templates/courses/_unit_kind_icon.html`**

```html
{% load i18n courses_extras %}{% get_current_language as LANGUAGE_CODE %}{% with m=node|unit_marker %}{% if m %}<span
  class="unit-kind unit-kind--{{ m }}" lang="{{ LANGUAGE_CODE }}" title="{% marker_label m %}">
  {% include "courses/_unit_kind_glyph.html" with m=m only %}
  <span class="visually-hidden unit-kind__label">{% marker_label m %}</span>
</span>{% endif %}{% endwith %}
```

**Why both carry `lang="{{ LANGUAGE_CODE }}"`.** Every call site sits inside a subtree switched
to the *course* language — `<a class="outline-unit" … lang="{{ course.language }}">`,
`<a class="unit-tree__unit" … lang="{{ course.language }}">`, and
`<article class="lesson"/"quiz" lang="{{ course.language }}">`. "Quiz" / "Additional" /
"Dodatkowa" are UI strings in the **user's** locale, not the course's, and they land in `title=`, in
a `.visually-hidden` label (visible at drawer scope) and in the chip text. `_quiz_article.html:12-15` records
the house rule verbatim: without it "a Polish UI string is announced as English inside an English
course". The same comment records why `LANGUAGE_CODE` must come from `{% get_current_language %}` —
**the i18n context processor is not enabled** — and `only` on every include means the partials
cannot inherit it from the parent context even if it were. Hence the tag inside each partial.

(The existing `✓` badge's `aria-label="{% trans 'Completed' %}"` omits `lang` in both surfaces. That
is a pre-existing inconsistency, out of scope here; the new markers do not copy it.)

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
`.unit-kind-chip` **does** get a small rule in §4, but every declaration in it is inert
forward-defence carrying no test hook — the pill itself comes entirely from `.badge`.
The
`--<marker>` modifiers are **reserved test/debug
hooks with no styling attached today**, and §5 forbids giving them any.

**Accessible-name contract.** The `<svg>` is `aria-hidden`; `.unit-kind__label` is the text —
visually hidden in the rail and on the outline, and **un-hidden at drawer scope** (§4), which
changes nothing about the accessible name since a `.visually-hidden` span is already in the
accessibility tree; the wrapper's `title=` is the hover tooltip. The enclosing link's accessible name is computed **from contents**, so it depends on
completion state:

| Surface | Not completed | Completed |
| --- | --- | --- |
| Rail (`_unit_tree_node.html`) | "*<title>*, Quiz" | "Completed, *<title>*, Quiz" |
| Outline (`_outline_node.html`) | "*<title>*, Additional" | "*<title>*, Additional, Completed" |

The `✓` carries `aria-label="Completed"` and **leads** in the rail but **trails** in the outline,
which is why the orders differ. Render tests assert **substring containment** of the marker word,
never full-name equality — a full-name assertion written from one row would be red on the other.

**Two tooltips share a rail row, and they compete.** `.unit-tree__label` already carries a `title=`
for the truncated unit name, authored with a comment explaining why
(`_unit_tree_node.html:11-14`). Hovering a row therefore surfaces one tooltip or the other depending
on the exact pixel, never both. Accepted: the intended desktop path is hovering the ~19px glyph
specifically, and the title tooltip keeps the whole rest of the row. This is also why the drawer
shows the word on the row itself rather than relying on the tooltip — touch has no hover. At drawer
scope the `title=` is then redundant; it is left in place rather than conditionally suppressed,
because the partial is surface-agnostic and touch has no hover for it to interfere with.

### 4. The rendered surfaces

Full stylesheet paths, short-formed thereafter: `core/static/core/css/app.css` and
`courses/static/courses/css/courses.css`.

**New shared component CSS in `app.css`, next to `.badge` (`app.css:115-131`):**

```css
.unit-kind { display: inline-flex; align-items: center; gap: var(--space-1); flex: none; }
.unit-kind-chip { flex: none; white-space: nowrap; }
```

**What `.unit-kind` is actually for — and what it is not.** The rule does **not** exist to stop the
wrapper being squashed: by the automatic-minimum-size rule above, a bare span whose only in-flow
child is a 1em `<svg>` has a min-content of 1em (`.unit-kind__label` is `.visually-hidden`, i.e.
`position: absolute`, so it contributes nothing), and its automatic minimum therefore pins it at the
glyph's width on any build. Deleting the whole rule does not narrow the glyph, so there is **no
glyph-width mutant** for it.

What the rule genuinely buys is **`display: inline-flex` + `gap`**, which matter on a **drawer
row**, where the glyph sits beside a *visible* word: without them the span is blockified as a flex
item, `gap` (a flex/grid property) does not apply, and the word butts against the glyph with only
collapsed whitespace between. `align-items: center` sets the glyph/word alignment there too.
`flex: none` is carried for consistency with the chip and is likewise inert. The falsifiable part is
therefore the drawer row's glyph-to-word gap, not any rail measurement.

`var(--space-1)` is 4px (`core/static/core/css/tokens.css:75`); the surrounding block is
token-driven.

**`.unit-kind-chip` needs the same treatment, and for the same reason.** `.badge` (`app.css:115`) is
`display: inline-block` with **no `flex` and no `white-space`**, so as a flex item of
`.lesson-unit__heading` — and of `.outline-unit` — it resolves to `flex: 0 1 auto`.

**Both declarations are inert today, and neither gets a mutant. This is the automatic-minimum-size
rule, and it is easy to get wrong.** A flex item's automatic minimum size is its **min-content**
size (`min-width: auto`, `overflow: visible`). Both shipping labels — "Additional", "Dodatkowa",
"Quiz" — are single words with no soft-wrap opportunity, and `.badge` sets no
`overflow-wrap`/`word-break`, so for the chip min-content == max-content == its full ~78px. In
`resolve-flexible-lengths` a `flex: 0 1 auto` chip's shrink target (~70px) is therefore a **min
violation**: it is clamped and frozen at 78, and the entire ~80px deficit lands on the `<h1>` (656px)
— *identical* to the `flex: none` build. So:

- **`flex: none`** does not change any rendered width for the labels that ship. §4's "the `<h1>`
  shrinks instead" argument holds on both builds; it was never at risk.
- **`white-space: nowrap`** is likewise inert: under `white-space: normal` a single unbreakable word
  does not wrap, it overflows, and its min-content contribution is the same either way.

Both are kept as **forward-defence for a future multi-word translation** and for consistency with
the peer chips — `.unit-done { flex: none }` (`courses.css:836`), `.unit-done__pill
{ white-space: nowrap }` (`:837`), `.rollup { white-space: nowrap }` (`app.css:506-508`) — which make
this the house pattern. Because both are inert, **neither has a falsification mutant**: any test
claiming to redden on their removal would be green on the broken build, which is exactly the
green-mutant trap this spec treats as a hard stop.

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

**Two required CSS changes, and they are *not* inert.** The overflow exposure is at **two nested
levels**, and fixing only the inner one leaves the row broken:

```css
/* app.css:521 — the title inside the anchor */
.outline-unit__title { flex: 1; min-width: 0; overflow-wrap: anywhere; }
/* app.css:544 — the anchor inside the wrapping li */
.outline-node--unit > .outline-unit { flex: 1 1 auto; min-width: 0; }
```

- **Inner.** `flex: 1` is `1 1 0%` with no `min-width: 0`, so the title's automatic minimum is its
  min-content width and it cannot shrink below its longest word. A chip up to ~90px ("Additional" /
  "Dodatkowa") can therefore push a 390px row past its box.
- **Outer.** `.outline-node--unit > .outline-unit` is itself `flex: 1 1 auto` (`app.css:544`) inside
  the wrapping `li.outline-node--unit` (`app.css:541-543`), with the default `min-width: auto`, so
  the **anchor**'s own automatic minimum is its min-content. This edit is **defence for title
  content that `overflow-wrap: anywhere` cannot break** — a KaTeX `.katex` inline-block, or any
  replaced element — not a second fix for the plain-text case. With `anywhere` in place a long
  *breakable* title collapses to roughly one character, putting the anchor's minimum at
  title(~1 char) + chip + `✓` + gaps + padding — comfortably inside the `li` at 390px, so on a
  plain-text fixture this declaration is inert and its mutant would be green. (Deliberately no
  pixel totals here: an earlier draft quoted two figures that could not both describe the same
  element, and the argument needs only the ordering, not the numbers. Measure at implementation.) It is pinned instead by the **maths-title** outline fixture (see Testing), where
  the atom genuinely cannot be broken. Note precisely what that fixture must be: **a single wide
  `\frac`/`\sqrt` with no top-level operator**, not merely a long formula — `courses.css:1687-1698`
  records that KaTeX breaks a multi-term formula between its `.base` spans, which would leave this
  mutant green. `.katex` is not an atomic inline-block.
- **`anywhere` vs `break-word`: the two are indistinguishable here, and no test can separate them.**
  They differ *only* in intrinsic (min-content) sizing; both break an over-long word at line-break
  time, producing pixel-identical rendering. The min-content contribution would matter only if the
  flex minimum were `auto` — and this very rule sets `min-width: 0` on the title, with a second
  `min-width: 0` on the anchor, so both minima are 0 and min-content never determines a used size.
  `anywhere` is chosen for **defence-in-depth** (it stays correct if a future edit drops
  `min-width: 0`) and for house consistency with `courses.css:940`, **not** because it measurably
  differs. Do not write a mutant that flips `anywhere` → `break-word`: it is green on every build.
  The only weakening the layout can see is removing `overflow-wrap` **entirely** (→ `normal`), and
  that is what Falsification names.

**These alter behaviour on rows carrying no marker at all**: the `✓` is already a shrink-forcing
sibling on every completed row, so today a long unbroken title overflows and afterwards it breaks
instead. That is an improvement and it is accepted — but it is a real change, not a no-op, and each
declaration has its own mutant in Falsification.

**Accepted colour collision:** `.badge` fills with `--surface-sunken` (`app.css:119`), and so do
`.outline-unit:hover` (`app.css:519`) and `.outline-node:target > .outline-unit` (`app.css:533`). On
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
title column squeezed to ~98px. This runs against the general "use `flex: 1 1 0`" habit — be precise
about why, because **no test distinguishes the two and none can**: `.unit-tree__label` is the only
flexible item on the row (`.unit-tree__check` and `.unit-kind` are both effectively rigid), so basis
`auto` and basis `0` resolve to the **same** used width in rail and drawer alike. `1 1 auto` is
chosen as the *minimal edit* to the existing rule, not because it measurably differs. What the A/B
in Testing guards is a different and real question — that adding `flex-grow` **at all** does not
move the drawer's wrap points.

**Mobile drawer** — same template, rendered again into `.unit-drawer__list` by `_unit_shell.html`.

The drawer is a **touch** surface, and the template's own authored comment records that "Touch has
no hover" — so `title=` yields nothing there. An icon alone would be a bare `+`/`?` with no text,
no tooltip and no legend, while the outline page shows the word: two vocabularies with nothing
connecting them.

Resolution: `.unit-kind__label` carries `class="visually-hidden unit-kind__label"` and is **un-hidden
at drawer scope**, so each marked drawer row shows its word. These rules go inside the existing
`@media (max-width: 640px)` block in `courses.css` (:948-987), beside the
`.unit-drawer__list .unit-tree__label` rule at `:977`:

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
1px x 1px with `overflow: hidden` and a zero clip rect: the drawer shows a bare glyph, the central
drawer requirement silently fails, and every render test stays green. Specificity is not a concern —
`.unit-drawer__list .unit-kind__label` is (0,2,0) against `.visually-hidden`'s (0,1,0).

**The width budget — and a correction that reverses an earlier decision in this spec.** An earlier
draft rejected the per-row word and shipped a one-line legend in `.unit-drawer__bar` instead,
because it read the drawer's title column as ~98px. **That figure is the RAIL's, not the drawer's.**
`courses.css:730` states it verbatim — "at the deepest level a **14rem rail** leaves the title
98px" — and the drawer audit comment at `:2339` carries the same number over, which is an error in
that existing comment. The drawer panel is `left: 0; right: 0` on the viewport:

```
390 (viewport)  −16 (.unit-drawer__list padding .5rem x2)  −~26 (.unit-tree__children .55rem/level,
                 0 for a top-level unit)  −~23 (.unit-tree__unit margin .35rem + 1px border
                 + padding .5rem x2)      ≈ 325px            (≈351px un-nested)
```

So the marker costs a 16px glyph + `.unit-tree__unit`'s `gap: .4rem` (~6.4px) + the ~71px word +
the wrapper's own 4px gap ≈ **~97px**, leaving the title **~230px** — a ~30% narrowing of a column
that had ~325px to give, not the ~5–10px residual the legend was justified by. The per-row word is
comfortably affordable, so it ships and **the legend apparatus does not exist**: no
`_unit_kind_legend_item.html`, no `.unit-drawer__legend`, no `aria-hidden` decision, no legend
placement contract, and no `.unit-kind__word` span.

**Do not add `flex-wrap: wrap` to the drawer row.** This part of the earlier analysis survives the
correction: flex line-breaking uses each item's **hypothetical main size**, and with
`flex: 1 1 auto` the label's base size is the max-content width of the full title, which still
exceeds a 325px line for any realistic title. The row would break *before* the label, stranding the
leading `✓` (`flex: none`) alone on line 1, the title on line 2 and the marker on line 3 — a
three-line row with an orphan tick, and because `flex-wrap` is unconditional it would regress
**every completed unit in the drawer, including unmarked ones**. `.unit-kind` is made shrinkable
instead (`flex: 0 1 auto; min-width: 0`) so its own word wraps inside its box, exactly as the
title's does. Expected drawer row shape for a **completed additional** unit: one flex line,
`[✓] [title, wrapping] [⊕ Dodatkowa, wrapping]`.

There is **no** `white-space: nowrap` on `.unit-kind`: it is `inline-flex`, so the `<svg>` and the
label are flex items that cannot break between each other regardless, and the un-hide rule above
sets `white-space: normal` on the label itself — a more specific match.

**Typography note: the same glyph is a different size in the two surfaces.** `font-size: .82rem` is
set on `.unit-tree` **alone** (`courses.css:665`), i.e. the `<nav>` that `_unit_tree.html` renders.
The drawer is a **sibling** of that nav — `_unit_shell.html` puts `.unit-drawer` directly under
`.unit-shell` — and no rule on the drawer chain sets a font size, so drawer rows render at
1rem/16px. `.icon` is `1em`, so the marker is **~13px in the rail and ~16px in the drawer**, and §5's
legibility acceptance must look at both.

**The maths-audit re-check trigger still fires**, but for a smaller narrowing than the earlier draft
claimed: `courses.css:2344-2345` says to re-check "if the drawer's title column ever narrows
further", and ~325px → ~230px is a real narrowing. Record the **measured** residual in that comment,
not a figure derived from the rail's 98px — and while editing, correct that comment's own ~98px
drawer claim, which is the error this section had to unwind.

**`overflow-wrap: anywhere` on the drawer label is inert forward-defence with no mutant.** Extend the
`:977` override with it for consistency with `.unit-tree__grouptitle` (`:736-738`), but do not claim
a test can see it: at a ~230px column, a single unbroken token would have to exceed ~230px (roughly
28+ characters) to overflow, which no realistic title does — `test_e2e_unit_head_layout.py`'s
`LONG_TITLE` token "przedziałach" is ~95px and does not come close. A mutant deleting it would be
green, which this spec treats as a hard stop, so none is listed.


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
`:834-835`** and therefore **before** the `@media (max-width: 640px)` block at `:948-987`, whose
`.lesson-unit__head` rules sit at `:985-986`:

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
  at `:1075` records that `.lesson-unit__head` was deliberately taken off that list, which
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
green over the new collision. While editing, **refresh every line reference in that block** — every
row in the table below, and do not stop at the first few (naming a count invites exactly that):

| Cited | Actual |
| --- | --- |
| `.unit-tree__label (:755)` | 789 |
| `.unit-tree__grouptitle (:702-704)` | 736-738 |
| `courses.css:943` (drawer label override) | 977 |
| `.unit-foot__navtitle (:778)` | 812 |
| `.unit-crumbs__label (:848)` | 882 |
| `courses.css:903-907` (print re-open) | 939-941 |

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

- **Non-unit node** (part / chapter / section) — `MARKER_NONE`. **Defensive, and currently
  unreachable from the four shipped call sites**: §4 places the chip inside
  `<a class="outline-unit">` and the icon inside `.unit-tree__unit`, both of which live in the
  `{% if item.is_unit %}` branch, while containers render through `.outline-node__head` and
  `<summary class="unit-tree__head">` — neither of which includes a marker partial. The recursion
  over containers is real, but no container node is ever passed to `unit_marker`. Guarded anyway,
  because a future include placed on a container row would otherwise mark a whole group. (Stated
  this way deliberately: this repo has already seen a reachability claim flip when a new flow
  appeared, so an over-claim in *either* direction is worth correcting.)
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
   the cap still bites. The fixture-validity guard must be re-pointed **at the title**, and **the
   mechanism is prescribed** because the obvious one measures nothing (with the cap applied and text
   wrapping, `scrollWidth == clientWidth`): neutralise `max-width` with `page.add_style_tag`,
   measure the uncapped `<h1>` content width, assert **`>= 740`**, then restore. Note the threshold
   is 740, **not** 736: the assertion being guarded is `title_w < 738`, so a fixture landing in
   (736, 738] would satisfy a `> 736` guard while leaving that assertion green on the cap-removed
   build — reintroducing exactly the vacuity the guard exists to prevent. With the cap neutralised
   the measured quantity is `min(max-content, flex target ≈ 746)`, which is what actually decides
   the assertion.

   **Do not substitute `group_w > 738`.** It looks equivalent and is not:
   `.lesson-unit__heading` is `flex: 1 1 auto`, so under `space-between` the group always grows to
   `head_w − pill_w − gap ≈ 746` **regardless of the title's content**. That assertion is a rename
   of the existing `target > 738` guard (`test_e2e_uniform_block_width.py:220-227`), which measures
   *available space*, not whether the title needs the cap — so it would leave `title_w < 738`
   vacuously green on a short title and a guard blind to fixture drift, i.e. exactly the death this
   item exists to repair.
2. **`tests/test_e2e_unit_nav.py::test_quiz_chrome_tracks_the_column_across_both_page_states`** —
   defused identically and needs the same repair, but **its fixture is a quiz, so it DOES emit a
   chip** and the chiplessness argument in §4 does not carry it. Its repaired assertion is
   non-vacuous through different arithmetic, stated here because it is fragile: the quiz head has no
   done pill, so the group spans the full collapsed column (~872px), and
   `736 + 12 + ~46 = ~794 < 872` leaves the cap — not the flex remainder — holding the title. That
   headroom is state-dependent: in the **expanded** state the quiz column is 648px (the test's own
   comment at `:1400`), where capped and uncapped builds both land the `<h1>` at ~582 and
   `title_w <= 738` is vacuous either way. Both cap assertions are therefore non-vacuous **only
   under the collapsed-state guard the test already enforces** — do not remove it. Apply the repair
   to **both** assertions: the test
   asserts `title_w <= 736 + 2` **twice**, once per page state (`~:1387` for the
   not-enrolled/preview load and `~:1421` after `page.reload()` with enrolment flipped). Repairing
   only the first leaves the second silently vacuous in the very test whose docstring exists to stop
   the quiz entries going untested. The seeded long title survives the reload — it is the same node.
3. **`tests/test_e2e_uniform_block_width.py` (~:150-183)** — **three** inline claims this change
   falsifies:
   - "the quiz page has no `.lesson-unit__head` at all" — it will have one, and the quiz page
     becomes a second surface for the `.lesson-unit__head` column claim;
   - "an uncapped title would measure ~746" — after the repair the mechanism is a >736px *content*
     width, not a 746px flex target;
   - "The title is flex:1, so it lands at ~643.6 whether or not `.lesson-unit__title` is in the cap:
     NO prose-cap mutation reddens either assertion" (`~:170-179`) — the `<h1>` is now
     `flex: 0 1 auto` inside the group and shrink-wraps to its content (~100px for that fixture), so
     both the ~643.6 figure and the "inert by construction" mechanism are wrong. The two assertions
     below it stay inert, but for a *different* reason, and leaving the comment stale re-creates the
     false-mechanism failure this spec guards against elsewhere.
4. **`tests/test_e2e_unit_head_layout.py`** — the pin for §4's mobile rule. Its `MEASURE` does
   `head.querySelector('.lesson-unit__title')`, which is descendant-based and still finds the `<h1>`
   through the wrapper. Its phone assertions (`done_top >= title_bottom - 1`,
   `reset_top >= title_bottom - 1`) are exactly what `flex-basis: 100%` on the group preserves.
   **Expected outcome: unchanged, all green.** If any goes red the mobile rule is wrong — do not
   update the test to match.

   Note what this file does **not** cover: its `_seed` builds an ordinary lesson and `obligatory`
   defaults to `True` (`courses/models.py:212`), so it renders **no chip**. It therefore pins only
   the *chipless* half of the mobile rule; the behaviour the rule was actually written for — the
   chip wrapping beneath the title at 390px — needs its own assertion in the new e2e (see below).
5. **`tests/capture_title_math_screenshots.py` (~:483)** — its `btns` selector list is the
   executable half of the drawer maths audit and must gain `.unit-kind` (see §4).
6. **`tests/test_quiz_previewer_render.py`** — renders `_quiz_article.html` directly via
   `render_to_string(build_quiz_context(...))`; must be re-run and updated for the new
   `.lesson-unit__head` / `.lesson-unit__heading` wrappers. `tests/test_title_math_markers.py:157`
   documents `span.unit-tree__label (_unit_tree_node.html:15)`; add a one-line mention of the new
   trailing `.unit-kind` sibling to that docstring's surface inventory.

### Unit — `unit_marker` and `marker_label`

New tests in `tests/test_unit_marker.py`. The label column is
`marker_label(unit_marker(node))` — the composition the templates perform — and asserts under the
**default `en` locale** (`config/settings/base.py:142`, `LANGUAGE_CODE = "en"`).

| Input | `unit_marker` | `marker_label(...)` |
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

One further case belongs here rather than in the surface tests: rendering
`courses/_unit_kind_glyph.html` directly with `m=""` must emit **no `<svg>`**. That is the pin for
the three-way `{% elif %}` in §3 — with an `{% else %}` it would emit the `+` glyph, and no
surface test can reach that branch because the chip and icon partials guard it behind `{% if m %}`.

### Render — one test per rendered surface (four)

Each asserts the marker is **present** for an additional unit and for a quiz, **and absent for a
required lesson**. The absence assertion is load-bearing: without it every mutant that marks every
row stays green. Each also asserts the rendered modifier class against the constant (§1), and that
the marker element carries `lang="en"` (the UI locale) even though it sits inside a
`lang="{{ course.language }}"` subtree — the §3 requirement, which is invisible to every geometric
assertion. Seed the course with a `language` **other than** the UI locale, or the assertion is
vacuous.

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
two `.unit-tree__unit` rows and two `.unit-kind` wrappers. Scope the drawer maths re-check to
`[data-unit-drawer-list] .unit-kind` and the `btns` entry in `capture_title_math_screenshots.py` to
`[data-unit-drawer] .unit-drawer__list .unit-kind`. An unscoped `select_one` silently tests
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
both marked, scoped to `[data-unit-tree-list]`: assert their `.unit-kind` boxes share a **`right`**
within ~1px, and that `icon.right == row.right - 8` — `.unit-tree__unit`'s `padding: .3rem .5rem`
(`courses.css:766`). Both are false when `.unit-tree__label` has no `flex-grow`.

**Compare `right`, not `x`.** `x` is the wrapper's *left* edge and the wrapper is one glyph wide
(~13px at the rail's `.82rem`), so on a correct build `x` sits ~13px inside the row's right content
edge. Asserting that `x` is "within a few px" of that edge would be **red on a correct build** — the
same trap this spec polices for the pill assertion, where the offset is stated explicitly rather
than approximated. (Sharing `right` and sharing `x` happen to be equivalent here because both glyphs
are the same width; `right` is the one that also pins the gutter position.)

**Drawer-row glyph-to-word gap.** In the open drawer, assert
`label.left - svg.right == 4` (±1) on a marked row, where `label` is `.unit-kind__label` (visible at
drawer scope) and `svg` is its sibling `.icon`. Both are elements with real boxes.

The mutant is **`gap: var(--space-1)` deleted from `.unit-kind`** — a clean 4px → 0px, since a flex
container drops whitespace-only text between items. Do **not** use `display: inline-flex` as the
mutant: blockifying the span replaces the 4px gap with a *rendered* collapsed space, ~4px at the
drawer's 16px font, which lands inside tolerance and may be green.

There is deliberately **no rail glyph-width assertion**: per §4 the wrapper's automatic minimum is
the 1em glyph on any build, so such a test would be green even with the whole rule deleted.

**Desktop, unit page.** The whole §4 heading-group resolution otherwise has **zero** executable
coverage, since render tests 2–3 are DOM-containment checks a CSS deletion leaves green. On both
article templates, and in both rail states (expanded and `html.unit-tree-collapsed`).

**This arm needs two fixtures, and which mutant each one kills is not interchangeable.** Adjacency
between two gapped flex siblings is invariant under *any* sizing mutant that keeps them on one line,
so a single cap-length row proves almost nothing:

- **Short-title row** — the `<h1>`'s content is far below the cap. Two assertions, and **both**
  mutants below are killable only here:
  1. **`chip.left - group.left < 200`**, on a fixture whose title content is ~100px. This kills
     deletion of `.lesson-unit__heading > .lesson-unit__title { flex: 0 1 auto }`: with the reset the
     `<h1>` shrink-wraps to ~100px and the chip follows it (~112px in); without it the `<h1>` is
     `flex: 1` and grows to the full ~656px remainder, putting the chip ~556px further right.

     **Write it as that absolute bound, not as `chip.left == title.right + gap`.** The natural
     reading of "the chip sits `gap` past the title" is **invariant across both builds** — without
     the reset the `<h1>` merely grows and the chip still sits `gap` past its right edge — so an
     adjacency assertion here is the same tautology §Testing already documents for the cap-length
     row. Only distance from the group's *left* edge discriminates.
  2. On the lesson page, **`.unit-done`'s left edge is `group.right + 16`** — measure `.unit-done`,
     the head's actual flex item (`flex: none`), **not** `.unit-done__pill`: on a not-completed
     fixture the pill is a button inside a `<form class="unit-progress">` nested within
     `.unit-done`, so its offset is not the one the exact-offset assertion guarantees. The existing
     `test_e2e_uniform_block_width.py` already measures `.unit-done` for the same reason. The head's
     `gap: 1rem` (`courses.css:829`), stated as an offset rather than "within a few px", which
     would be red on a correct build. This kills deletion of the group's `flex: 1 1 auto`.

  **Both must sit on the short-title row, not the cap-length one.** With the group mutated to
  `flex: 0 1 auto` *and* a cap-length title, the group's base (736 + 12 + 78 = 826) already exceeds
  the ~746px line, so it shrinks to fill it exactly, free space is zero, `space-between` degenerates
  to flex-start, and `pill.left == group.right + 16` holds on the **broken** build too. Only the
  short-title row leaves the ~556px of free space that `space-between` would spread.

- **Cap-length row** — the `<h1>`'s content exceeds 736px. **One** assertion: the chip has **not
  wrapped below the title** — `chip.top < title_bottom - 1`, or equivalently the chip's and the
  `<h1>`'s rects overlap vertically. That is what kills adding `flex-wrap: wrap` to the group at
  desktop.

  **Do not assert `chip.top ≈ title_top`.** §4 mandates `align-items: baseline` precisely so the
  chip does *not* top-align: the `<h1>` renders at heading size and the chip at `.badge` size, so
  their border-box tops differ by ~10–15px on a **correct** build. A top-equality assertion at this
  spec's usual ~1px tolerance would be red on correct CSS, and a tolerance loose enough to pass
  (~15px) would be undefined and meaningless.

  **This row cannot catch the missing `flex: 0 1 auto` reset, and it has no chip-width assertion.**
  With the reset the `<h1>`'s base is `min(max-content, 736)` = 736 and the chip is `flex: none`, so
  the entire ~80px deficit lands on the `<h1>` → 656px; without the reset the `<h1>` is `flex: 1 1 0%`
  and *grows* into the same ~656px remainder. `chip.left` is `group.left + 668` on both builds —
  pixel-identical, which is why assertion 1 lives on the short-title row. And per §4's
  automatic-minimum-size analysis, a `flex: 0 1 auto` chip's shrink target is a **min violation**
  (min-content == max-content == ~78px for every single-word label that ships), so it is clamped and
  frozen at 78 and the deficit again lands entirely on the `<h1>`. An A/B forcing `flex: 0 1 auto`
  on the chip would therefore measure 78px in **both** arms — the green-mutant trap this spec treats
  as a hard stop. `.unit-kind-chip`'s declarations are inert forward-defence with no mutant.

**Phone, 390×780 — the drawer must actually be opened.** `.unit-drawer` is `display: none` at base
(`courses.css:946`), revealed only inside `@media (max-width: 640px)` via
`.unit-drawer:not([hidden])` (`:961`), and carries a literal `hidden` attribute until `unit_nav.js`
responds to the footer `[data-unit-drawer-open]` trigger. Sequence: resize; click the footer Contents
trigger; wait for `[data-unit-drawer]` to lose `hidden`; then assert.

Assertions at that size:

- `.unit-kind__label` inside `[data-unit-drawer-list]` has a **non-trivial** box —
  `width >= 30` and `height >= 8` — i.e. the marker's **visible text**, not a bare glyph. The
  numeric thresholds are the point: `.visually-hidden` is 1px × 1px with a zero clip rect, which
  Playwright reports as **visible with a non-empty box**, so a `bounding_box() is not None`
  assertion cannot distinguish an un-hidden label from a still-hidden one, nor catch the partial
  revert (`position: static` only) that §4 calls the likeliest wrong implementation;
- **text-overflow on the label**, not a rect comparison: with a long unbreakable Polish word in the
  title, assert `label.scrollWidth - label.clientWidth <= 1`. A rect-intersection assertion between
  `.unit-kind` and `.unit-tree__label` was **considered and rejected as vacuous** — they are sibling
  flex items with a positive `gap: .4rem` and no negative margins, so their border boxes can never
  overlap on any build, correct or broken. The failure being policed is *text* painting outside the
  label box, and this repo already records that box geometry cannot see it:
  `tests/test_e2e_unit_head_layout.py`'s module docstring says "Box geometry alone does not catch
  this — the boxes stay 16px apart while the text overlaps — so the assertion is on TEXT overflow
  (scrollWidth vs clientWidth)". Do not re-introduce the rect form;
- **A/B the label's wrap points**: record `.unit-tree__label`'s
  `getBoundingClientRect().height` for a fixed long title, re-measure with `page.add_style_tag`
  injecting `.unit-drawer__list .unit-tree__label { flex: 0 1 auto !important }` — the pre-change
  computed value, named explicitly because `add_style_tag` can only *add* a declaration, and
  `flex: none` or `flex: 1 1 0` would change the base size and redden a correct build. Assert the
  two heights are equal; they are, because a long title leaves no free space for `flex-grow` to
  distribute. Mechanical rather than a
  remembered baseline;
- the drawer maths re-check, asserting no `.katex` box intersects `.unit-kind`'s rect. The **rect**
  form is right here (unlike the plain-text case above) because a `.base` span genuinely paints
  outside its parent's box. Three things must be stated, because none is obvious:

  1. **Reuse the title the existing audit measured** — the drawer title in
     `tests/capture_title_math_screenshots.py` — reuse the **whole `TITLES` seed** so every audited
     title is present in the drawer at once, rather than naming one key. The drawer arm navigates
     via `nodes["lesson_display"]` (`TITLES["display"]`) but screenshots the entire tree, which also
     contains `TITLES["long"]` — the "long maths title" the audit comment actually describes — so
     "the title that drives the drawer arm" would name the wrong one. That
     script is already being edited for the `btns` list, so the fixture is in hand. Cite
     `courses.css:2339-2345` only for the audit's *result*: that comment records "Task 11 MEASURED
     this at 390x780" but names no title string, so it cannot be used to find the fixture. Reusing
     it makes this a like-for-like re-measurement at ~76px against the original's ~98px; a
     freshly-invented formula would make the outcome a property of the fixture rather than of the
     column width.
  2. **Expected outcome: no intersection.** But note the precedent is thinner than it looks — the
     original audit checked `.katex` against `.unit-tree__count`, `.unit-tree__groupcheck`,
     `.unit-tree__chevron` (all on **group** rows), `.unit-tree__check` (which *leads* a unit row)
     and `.unit-drawer__close` (in the sticky bar). **None of them is a right-hand neighbour of a
     unit-row label.** `.unit-kind` is the first, only `gap: .4rem` (~6.4px) away, beside a label
     that keeps `overflow: visible`. So "CONFIRMED clean" carries no evidence for this geometry;
     the re-check is a genuine measurement, not a formality.
  3. **If it does intersect, that is a design change, not a test tweak.** The remedy is containment
     on the drawer label's maths (a `max-width`/`overflow` rule of the kind `courses.css:1685`
     already applies to tab labels) or moving the marker out of the row — decide it then, and record
     the decision in the audit comment. Do not widen the tolerance to make it pass;
- the **unit page** head at 390 wide on a quiz or additional unit — the chip's `top >=
  title_bottom - 1` and `chip.left == group.left` (±1) — exact, not "near": at 390px the `<h1>`
  keeps `flex-basis: 100%` from `courses.css:986`, the group wraps, and the chip starts a fresh flex
  line at the group's content-box left under the default `justify-content: flex-start` (the group
  has no padding). This is the chip-bearing half of the
  mobile rule, which `test_e2e_unit_head_layout.py` structurally cannot cover;
- the **outline** page at 390 wide, with **two** marked rows, because the two CSS edits in §4 are
  pinned by different content:
  1. a long unbroken / Polish title — pins `.outline-unit__title`'s `overflow-wrap: anywhere`
     (`break-word` would not lower the min-content contribution);
  2. a **single unbreakable maths atom** — one wide `\frac{…}{…}` or `\sqrt{…}` with **no top-level
     operator or relation** — pins the **anchor**'s own `min-width: 0` (`app.css:544`).

     **"A long `\(…\)` title" will NOT do, and the repo already measured why.**
     `courses.css:1687-1698` records it: KaTeX splits a formula into several `.base` spans at
     top-level operators and relations — each `nowrap` internally but **breakable between** — so a
     long multi-term formula wraps, its min-content contribution collapses to the widest single
     `.base`, the anchor's automatic minimum stays small, and reverting `min-width: 0` produces no
     overflow. The mutant would be **green on the broken build**. That same comment names the one
     residual case that genuinely cannot wrap — "a single unbreakable atom (one very wide fraction
     or radical, no top-level operator to break at)" — and that is exactly the fixture required
     here. `.katex` is *not* an atomic inline-block; do not describe it as one.

     Size the atom deliberately, and **measure both bounds in the browser rather than deriving them
     from arithmetic**: **wider** than the space left in the `li` after chip + `✓` + gaps + padding
     (or the mutant does not bite), and **narrower** than the distance from the title's left edge to
     the viewport edge (or a correct build overflows the document — see below). The window is real
     but not wide, and it is the one fixture constraint in this spec that a wrong guess turns into a
     red assertion on correct CSS.

  For both rows, "stays within its box" is too loose to assert — under the two-level overflow in §4
  the anchor, the `li` and the viewport disagree, and if the anchor sizes itself at min-content and
  overflows the `li`, the *content* is still inside the *anchor* and a naive assertion passes on the
  broken build. The discriminating assertions are:

  - **plain-text row** — `title.scrollWidth - title.clientWidth <= 1` on `.outline-unit__title`.
    This is the **only** assertion that can see what `overflow-wrap` prevents: the failure is *text*
    painting outside the title box, and since the title has no `overflow: hidden`, its border box
    never moves and neither does the chip's or the tick's — so all three box-geometry assertions
    stay green under `overflow-wrap: normal`. It is the same mechanism, and the same lesson, that
    `test_e2e_unit_head_layout.py`'s docstring records and that this spec already applies to the
    drawer label. The fixture's word must be **measured wider than the title's rendered column at
    390** or even this assertion is vacuous — measure it, do not derive it; an earlier draft quoted
    a figure here that was ~60px out, which is exactly enough to make the mutant green;
  - **both rows** — `.outline-unit`'s `getBoundingClientRect().right <= li.right + 1` (pins the
    **anchor**'s `min-width: 0`);
  - **maths row additionally** — a `.katex`-vs-`.unit-kind-chip` **rect intersection check**, with
    the same treatment and the same escape hatch the drawer maths re-check gets. This change
    *introduces* the collision: today `.outline-unit__title` is `flex: 1` with `min-width: auto`, so
    an unbreakable atom holds the title box open and can never overlap a sibling. After the edit the
    title's minimum is 0, the atom is **by fixture construction** wider than the resulting box, and
    `overflow` stays visible — so on the **correct** build the atom paints rightward across the
    `.outline-unit` gap and into the chip, and both box assertions below stay green while the text
    overlaps. Expected outcome: no intersection at the chosen atom width. **If it does intersect,
    that is a design change, not a test tweak** — the remedy is containment on the outline title's
    maths (the `max-width`/`overflow` shape `courses.css:1685` already applies to tab labels) or
    dropping the maths fixture and reclassifying the anchor's `min-width: 0` as inert. Do not widen
    the tolerance. A maths outline row also joins the screenshot set so this is looked at, not only
    measured.
  - **maths row additionally** — `chip.right <= anchor.right + 1` (equivalently the `✓`'s right).
    This is the **only** assertion that pins the **title**'s own `min-width: 0`, and without it that
    declaration has no mutant at all. On the plain-text row it is inert, because
    `overflow-wrap: anywhere` already collapses the title's minimum to ~1 character. On the maths
    row it bites: reverting it makes the title's automatic minimum the atom's full width (~250px),
    so title + chip + `✓` + gaps exceeds the anchor's content box and pushes the chip and tick
    **outside the anchor** — while the anchor's own border box is unchanged,
    which is exactly why `anchor.right <= li.right + 1` cannot see it.

  **`document.documentElement.scrollWidth === clientWidth` is a whole-page invariant that both rows
  must satisfy — it cannot be scoped to one row.** Both fixtures live on the same outline page, and
  `documentElement.scrollWidth` is a property of the document, not of a row, so there is no way to
  assert it "for the plain-text row only".

  That is exactly why the atom is bounded on **both** sides above. Nothing on this page sets
  `overflow-x` (`.app-main`, `.outline`, `.outline-node*` all leave it visible), so an atom wider
  than the distance from the title's left edge to the viewport edge would grow the document and
  redden this assertion **on a correct build**. The window is satisfiable — roughly wider than the
  anchor's remaining space so the mutant bites, and narrower than that viewport gap — and staying
  inside it is a fixture requirement, not an optional refinement. Size the atom by measuring at
  implementation rather than by trusting the order-of-magnitude figures quoted in §4.

**Screenshots** (`tests/capture_unit_marker_screenshots.py`): both glyphs at rail size, both
glyphs on a marked **drawer row** at 390×780, the outline row at rest / hover / `:target`, a **maths** outline row (per the collision note in the outline e2e
arm), the
unit-page head — light **and** dark, with dark judged on its own. The drawer
row is not optional: per the typography note in §4 the glyph renders there at ~16px rather than the
rail's ~13px, beside a *wrapped* multi-line label under `align-items: flex-start`
(`courses.css:980`), so §5's legibility acceptance — argued "at the ~1em the rail renders" — would
otherwise never look at the larger of the two renderings it governs. This is where §3's glyph-legibility acceptance step and §4's
`--surface-sunken` collision are actually looked at.

### Falsification

Each test is falsified against a mutant from its own failure mode, not merely run green:

- `unit_marker` → `MARKER_ADDITIONAL` for a non-obligatory quiz → the quiz-pair test goes red.
- `unit_marker`'s `additional` branch → `not is_obligatory_lesson(node)` → the non-unit and
  `unit_type=None` rows go red.
- The `getattr` guard replaced by `node.kind` → the `""` / `None` rows go red.
- `unit_marker` returning a marker unconditionally → each surface's *absence* assertion goes red.
- `marker_label` returning a non-empty string for `MARKER_NONE` → the `""` rows go red; and
  `gettext_lazy` → `gettext` → the `translation.override("pl")` row goes red.
- `_unit_kind_glyph.html`'s `{% elif m == "additional" %}` widened back to `{% else %}` → the
  empty-marker glyph render test goes red.
- Rail icon rendered leading instead of trailing → the last-element-child assertion goes red.
- The chip moved before `.outline-unit__title` → the outline next-element-sibling assertion goes red.
- `.unit-tree__label`'s `flex: 1 1 auto` reverted → the shared-`right` gutter assertion **and** the
  `icon.right == row.right - 8` offset both go red.
- `gap: var(--space-1)` deleted from `.unit-kind` → the drawer row's glyph-to-word gap assertion goes
  red (4px → 0px). **Not** `display: inline-flex`, whose removal substitutes a ~3–4px rendered space
  that may land inside tolerance. Deleting the *whole* rule has deliberately **no rail mutant**: the
  wrapper's automatic minimum is the 1em glyph either way (§4).
- `.unit-kind-chip`'s `flex: none` and `white-space: nowrap` have deliberately **no mutants** — by
  the automatic-minimum-size rule in §4 both are inert for the single-word labels that ship, so any
  test claiming to redden on their removal would be green on the broken build.
- The `.lesson-unit__heading > .lesson-unit__title { flex: 0 1 auto }` reset deleted → the
  **short-title** desktop assertion goes red. NOT the cap-length one, which is pixel-identical on
  both builds.
- `overflow-wrap: anywhere` dropped from the drawer's `.unit-tree__label` override → the 390px
  `scrollWidth - clientWidth` assertion goes red.
- The title's `overflow-wrap` **removed entirely** (→ `normal`) → the plain-text row's
  `title.scrollWidth - title.clientWidth <= 1` assertion goes red. **Not** `anywhere` → `break-word`:
  with `min-width: 0` co-applied those two are pixel-identical, so that mutant is green on every
  build (§4).
- `.outline-unit__title`'s `min-width: 0` reverted → the **maths row's** `chip.right <=
  anchor.right + 1` assertion goes red. Only that row: on plain text `anywhere` already collapses
  the title's minimum, so the declaration is inert there and the mutant would be green.
- The anchor's `min-width: 0` (`app.css:544`) reverted → the 390-wide outline assertion goes red
  **only on the maths-title fixture**. It is inert on plain text, because `anywhere` already
  collapses the title's minimum to ~1 character (§4) — so falsify it against the maths row
  specifically, or it reads as a green mutant.
- `.lesson-unit__heading`'s `flex: 1 1 auto` deleted → the pill-position assertion goes red.
- The mobile `.lesson-unit__heading { flex-basis: 100%; flex-wrap: wrap }` deleted →
  `test_e2e_unit_head_layout.py`'s phone assertions go red.
- `flex-wrap: wrap` added to the group at **desktop** → the cap-length **not-wrapped** assertion
  (`chip.top < title_bottom - 1`) goes red. Note the assertion is deliberately *not* top-equality —
  `align-items: baseline` makes the two tops differ by ~10–15px on a correct build (§Testing).
- The `.unit-drawer__list .unit-kind__label` un-hide rule deleted → the 30×8 drawer-label assertion
  goes red. Falsify **also** against the partial revert (`position: static` only), since that is the
  likelier mistake and it is the case a "non-empty box" assertion would have missed.
- `lang="{{ LANGUAGE_CODE }}"` dropped from the chip → the render tests' `lang` assertion goes red.

A mutant must be removed by editing it out, never by `git checkout` of the file, which would destroy
the surrounding work.
