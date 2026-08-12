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

The labels live in `rollups.py`, keyed on the **marker** rather than the node — the drawer legend in
§4 has no node to derive one from:

```python
UNIT_MARKER_LABELS = {
    MARKER_QUIZ: gettext_lazy("Quiz"),
    MARKER_ADDITIONAL: gettext_lazy("Additional"),
}

def marker_label(marker):
    """Marker key -> translated word; "" for MARKER_NONE or any unknown key.

    Keyed on the marker, not the node, so the drawer legend — which has only a
    literal marker string — reaches the same words as the per-row partials
    instead of re-authoring {% trans %} in a third template.
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
marker string `m`. Split out from the icon partial so the drawer legend (§4), which has no node, can
reuse the identical geometry instead of copying it into a third template.

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
future legend row — would silently emit the *additional* `+` glyph rather than nothing. Since §1
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

**`templates/courses/_unit_kind_legend_item.html`** — one legend entry: the same glyph beside its
**visible** word. Used only by the drawer legend (§4).

```html
{% load i18n courses_extras %}{% get_current_language as LANGUAGE_CODE %}<span
  class="unit-kind unit-kind--{{ m }}" lang="{{ LANGUAGE_CODE }}">
  {% include "courses/_unit_kind_glyph.html" with m=m only %}
  {% marker_label m %}
</span>
```

Note the legend entry deliberately carries **no** `title=` and **no** `.visually-hidden` — its word
is already visible, so a tooltip would duplicate it and a hidden copy would double-announce it.

**Why all three carry `lang="{{ LANGUAGE_CODE }}"`.** Every call site sits inside a subtree switched
to the *course* language — `<a class="outline-unit" … lang="{{ course.language }}">`,
`<a class="unit-tree__unit" … lang="{{ course.language }}">`, and
`<article class="lesson"/"quiz" lang="{{ course.language }}">`. "Quiz" / "Additional" /
"Dodatkowa" are UI strings in the **user's** locale, not the course's, and they land in `title=`, in
a `.visually-hidden` label, in the chip text and in the legend. `_quiz_article.html:12-15` records
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

**Two tooltips share a rail row, and they compete.** `.unit-tree__label` already carries a `title=`
for the truncated unit name, authored with a comment explaining why
(`_unit_tree_node.html:11-14`). Hovering a row therefore surfaces one tooltip or the other depending
on the exact pixel, never both. Accepted: the intended desktop path is hovering the ~19px glyph
specifically, and the title tooltip keeps the whole rest of the row. This is also why the drawer
needs the legend rather than the tooltip — touch has no hover for either of them.

### 4. The rendered surfaces

Full stylesheet paths, short-formed thereafter: `core/static/core/css/app.css` and
`courses/static/courses/css/courses.css`.

**New shared component CSS in `app.css`, next to `.badge` (`app.css:115-131`):**

```css
.unit-kind { display: inline-flex; align-items: center; gap: var(--space-1); flex: none; }
.unit-kind-chip { flex: none; white-space: nowrap; }
```

`.unit-kind` needs its own rule because **the flex item of `.unit-tree__unit` is the `.unit-kind`
wrapper, not the `<svg class="icon">` inside it**. `.icon { flex: none }` (`app.css:109`) governs
`.icon` only when `.icon` is itself a flex item; inside a non-flex `.unit-kind` it does nothing for
the wrapper, which would otherwise take `flex: 0 1 auto` and squash under a `flex: 1 1 auto` label.
`display: inline-flex` also makes `.icon`'s `flex: none` meaningful again for the glyph.
`var(--space-1)` is 4px (`core/static/core/css/tokens.css:75`); the surrounding block is
token-driven.

**`.unit-kind-chip` needs the same treatment, and for the same reason.** `.badge` (`app.css:115`) is
`display: inline-block` with **no `flex` and no `white-space`**, so as a flex item of
`.lesson-unit__heading` — and of `.outline-unit` — it resolves to `flex: 0 1 auto` and shrinks. Flex
shrink is basis-weighted, so with an ~80px deficit (`<h1>` basis 736, chip basis ~78, gap 12,
line ~746) the chip absorbs `78/814 × 80 ≈ 8px`. That falsifies §4's "the `<h1>` shrinks instead"
argument, which assumes the chip holds its width. **`flex: none` is the load-bearing half of this
rule** and is pinned by a chip-width assertion in Testing.

**`white-space: nowrap` is forward-defence, not a live fix — do not justify it as one.** Both
shipping labels ("Additional", "Dodatkowa") are single words with no space, so they have no
soft-wrap opportunity, and `.badge` sets no `overflow-wrap`/`word-break`; under `white-space: normal`
such a word cannot wrap, it overflows. The declaration is therefore **inert for the two labels that
actually ship**, and its min-content contribution is identical either way. It is kept for a future
multi-word translation and for consistency with the peer chips — `.unit-done__pill
{ white-space: nowrap }` (`courses.css:837`) and `.rollup { white-space: nowrap }`
(`app.css:506-508`) — alongside `.unit-done { flex: none }` (`courses.css:836`), which make this the
house pattern. Because it is inert today it has **no mutant**: any test claiming to redden on its
removal would be green on the broken build.

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
  the wrapping `li.outline-node--unit` (`app.css:541-543`), with the default `min-width: auto` — so
  the **anchor** can equally refuse to shrink and overflow the `li`, no matter what the title does.
  The title edit alone cannot fix that, which is why both are required.
- **`anywhere`, not `break-word`.** `overflow-wrap: break-word` permits breaking at paint time but
  **does not reduce the element's min-content contribution**, so it does not lower the flex minimum
  that causes the overflow in the first place. `anywhere` does, which is why this repo already
  reaches for it wherever overflow must actually be prevented (`courses.css:940`).

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
title column squeezed to ~98px. This runs against the general "use `flex: 1 1 0`" habit, so it is a
deliberate exception, verified by a mechanical A/B (see Testing).

**Mobile drawer — icons stay icon-only; discoverability comes from a legend, not per-row words.**

The drawer is a **touch** surface and the template's own comment records that "Touch has no hover",
so `title=` yields nothing there and a bare glyph would be unexplained.

The obvious fix — un-hiding `.unit-kind__label` at drawer scope — was **considered and rejected on a
width budget**, and that reasoning is recorded here so it is not re-attempted. `courses.css:2339`
documents the **drawer's** title column as already squeezed to ~98px — note that `:981-984` records
a coincidentally identical ~98px for a *different* element (`.lesson-unit__head`'s title beside the
action buttons), so the two must not be conflated. A glyph (~16px — see the typography note below)
plus "Dodatkowa" (~71px at 1rem) plus the gap leaves the title roughly 5–10px, which is unusable;
and because
`.unit-kind__label` has no `overflow-wrap`, the unbreakable word would paint outside its box and
overlap the title. Making the row `flex-wrap: wrap` does not rescue it either: flex line-breaking
uses each item's **hypothetical main size**, and with `flex: 1 1 auto` the label's base size is the
max-content width of the full title, which always exceeds a 98px line — so the row would break
*before* the label, stranding the leading `✓` (`flex: none`) alone on line 1, the title on line 2
and the marker on line 3. That is a three-line row with an orphan tick, and since `flex-wrap` is
unconditional it would regress **every completed unit in the drawer, including unmarked ones**.

Instead, `_unit_shell.html` gains a one-line legend rendering each glyph once beside its word. **It
is a sibling *after* `.unit-drawer__bar`, not a child of it** — between that `</div>` and
`<ul class="unit-drawer__list">`:

```html
      </div>            <!-- .unit-drawer__bar ends -->
      <p class="unit-drawer__legend" aria-hidden="true"> … </p>
      <ul class="unit-tree__list unit-drawer__list" data-unit-drawer-list>
```

**`aria-hidden="true"` on the legend is a decision, not an oversight.** `.unit-kind__label` already
gives every marked row its own spoken "Quiz" / "Additional", so a screen-reader user has the
information per row and in context. Exposing the legend as well would announce a bare, unframed
"Additional Quiz" paragraph on entering the drawer — the same duplication the legend *entry* avoids
by carrying no `.visually-hidden` copy, one level up. The legend is a **visual** key for a touch
surface that has no hover; AT does not need it. Pinned by an assertion in the 390px e2e arm.

The placement is a contract, not a detail. `.unit-drawer__bar` is `display: flex;
align-items: center` (`courses.css:967`), so a `<p>` placed **inside** it lands on the *same* flex
line as the heading, and `.unit-drawer__close { margin-left: auto }` (`:970`) shoves the close
button past it — the opposite of "beneath". Getting it beneath while inside would need
`flex-wrap: wrap` on the bar plus `flex-basis: 100%` on the legend, neither of which is wanted.

**The legend scrolls with the list; it is deliberately not sticky.** The bar is
`position: sticky; top: 0` (`courses.css:967-969`) inside an `overflow-y: auto`, `max-height: 80vh`
panel (`:963-966`), so as a sibling the legend scrolls away on the first flick while the heading
stays pinned. That is the right trade in an 80vh panel: a legend is reference information read once
on open, and permanently spending a line of a phone-height drawer on it would cost more than it
returns. Do not "fix" this by extending the sticky region.

```html
<p class="unit-drawer__legend">
  {% include "courses/_unit_kind_legend_item.html" with m="additional" only %}
  {% include "courses/_unit_kind_legend_item.html" with m="quiz" only %}
</p>
```

The two literals `"additional"` / `"quiz"` are the same template-side hardcoding §1 already records
for `_unit_kind_icon.html`, and are covered by the same rename-grep note. The legend's own CSS is
one rule beside the other drawer rules in the `@media (max-width: 640px)` block:

```css
.unit-drawer__legend { display: flex; gap: var(--space-3); margin: 0;
  padding: 0 .9rem .6rem; font-size: .75rem; color: var(--text-secondary); }
```

This costs one line at the top of the drawer and **zero further per-row width** — "further" being
load-bearing, since the *glyph* still renders on every marked drawer row and is not free.

**Typography note, because the budget depends on it: the same glyph is a different size in the two
surfaces.** `font-size: .82rem` is set on `.unit-tree` **alone** (`courses.css:665`), i.e. the
`<nav>` that `_unit_tree.html` renders. The drawer is a **sibling** of that nav — `_unit_shell.html`
puts `.unit-drawer` directly under `.unit-shell`, not inside `.unit-tree` — and no rule on the
drawer chain (`.unit-drawer*`, `.unit-tree__list`) sets a font size, so drawer rows render at
1rem/16px. `.icon` is `1em`, so the marker is **~13px in the rail and ~16px in the drawer**.

Budget it at the drawer's own size: a 16px glyph plus `.unit-tree__unit`'s `gap: .4rem` (~6.4px)
takes **~22px** out of the ~98px title column documented at `courses.css:2339`, leaving
**~75–76px**. That is a **~23%** narrowing of exactly the column whose narrowing is the stated
re-check trigger for the maths audit (`courses.css:2344-2345`), so every drawer assertion in Testing
must hold at **~75–76px**, not at 98px — and that is the residual figure the re-check comment should
record. The rejected per-row word is rejected by a much wider margin than the glyph, not the same
one: the comparison the "zero" claim beats is the ~71px label, not the marker as a whole.

**Narrowing that column to ~75–76px requires a wrap guard the drawer label does not have.** The drawer
override at `courses.css:977-978` gives `.unit-tree__label` `white-space: normal; overflow: visible;
text-overflow: clip` — but, unlike `.unit-tree__grouptitle` (`:736-738`, which carries
`overflow-wrap: break-word; hyphens: auto`), `.unit-tree__label` has **no `overflow-wrap` at all**.
A single word wider than the column therefore paints *outside* the box, to the right — precisely
where the new trailing `.unit-kind` now sits. The existing drawer measurement was taken clean at
~98px, not at ~75–76px, and this repo's own phone fixture (`test_e2e_unit_head_layout.py`'s
`LONG_TITLE`) contains "przedziałach", which is plausible at 98px and not at 76px — and the gap
widened further once the glyph was re-measured at the drawer's 1rem rather than the rail's .82rem. So extend that
override:

```css
.unit-drawer__list .unit-tree__label {
  white-space: normal; overflow: visible; text-overflow: clip;
  overflow-wrap: anywhere;
}
```

`anywhere` rather than `break-word` for the same reason as the outline title: it reduces the
min-content contribution, which is what actually stops the overflow. Pinned by the text-overflow
assertion in Testing.

The legend keeps `.unit-kind__label` visually hidden on every surface (so the accessible name in §3
is unchanged everywhere) and needs no `.unit-drawer__list .unit-kind*` rules at all. It renders
unconditionally rather than
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
green over the new collision. While editing, **refresh every line reference in that block** — five
are stale, not three, and naming a count invites stopping early:

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
   measure the uncapped `<h1>` content width, assert `> 736`, then restore.

   **Do not substitute `group_w > 738`.** It looks equivalent and is not:
   `.lesson-unit__heading` is `flex: 1 1 auto`, so under `space-between` the group always grows to
   `head_w − pill_w − gap ≈ 746` **regardless of the title's content**. That assertion is a rename
   of the existing `target > 738` guard (`test_e2e_uniform_block_width.py:220-227`), which measures
   *available space*, not whether the title needs the cap — so it would leave `title_w < 738`
   vacuously green on a short title and a guard blind to fixture drift, i.e. exactly the death this
   item exists to repair.
2. **`tests/test_e2e_unit_nav.py::test_quiz_chrome_tracks_the_column_across_both_page_states`** —
   defused identically and needs the same repair, applied to **both** cap assertions: the test
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
article templates, and in both rail states (expanded and `html.unit-tree-collapsed`).

**This arm needs two fixtures, and which mutant each one kills is not interchangeable.** Adjacency
between two gapped flex siblings is invariant under *any* sizing mutant that keeps them on one line,
so a single cap-length row proves almost nothing:

- **Short-title row** — the `<h1>`'s content is far below the cap. Assert `chip.left` is near the
  **group's left** edge (`group.left + title_content_width + gap`, ~112px in), and specifically
  **not** near the group's right edge. This is the row that kills deletion of
  `.lesson-unit__heading > .lesson-unit__title { flex: 0 1 auto }`: with the reset the `<h1>`
  shrink-wraps to ~100px and the chip follows it; without it the `<h1>` is `flex: 1` and grows to
  the full ~656px remainder, putting the chip ~556px further right.
- **Cap-length row** — the `<h1>`'s content exceeds 736px. Assert the chip is on the **same line**
  as the title (`chip.top ≈ title_top`), which is what kills adding `flex-wrap: wrap` to the group
  at desktop. Also assert the chip's **width** ≈ its unshrunk natural width, A/B'd via
  `page.add_style_tag` forcing `flex: 0 1 auto` on it — that is what kills dropping
  `.unit-kind-chip { flex: none }`.

  **Do not expect the cap-length row to catch the missing `flex: 0 1 auto` reset — it cannot.** With
  the reset, the `<h1>`'s base is `min(max-content, 736)` = 736 and the chip is `flex: none`, so the
  entire ~80px deficit lands on the `<h1>` → 656px. Without the reset the `<h1>` is `flex: 1 1 0%`
  and *grows* into the same ~656px remainder. `chip.left` is `group.left + 668` on both builds. The
  two are pixel-identical, which is exactly why the short-title row exists.

  For the same reason, dropping `.unit-kind-chip { flex: none }` moves **both** edges together (the
  chip absorbs ~8px of the deficit, so the `<h1>` lands at ~663.7 and the chip at ~70.3) and leaves
  `chip.left ≈ title_right + gap` true — only the chip's *width* changes. This is the failure mode
  §4 already reasons about for `.unit-kind`; it applies to the chip identically.

- On the lesson page, the **done pill's left edge is `group.right + 16`** — the head's `gap: 1rem`
  (`courses.css:829`), stated as an offset rather than "within a few px", which would be red on a
  correct build. This is what kills a deletion of the group's `flex: 1 1 auto`, which no
  chip-position assertion can (with `flex: 0 1 auto` on the group the chip stays glued to the title;
  what moves is the pill).

**Phone, 390×780 — the drawer must actually be opened.** `.unit-drawer` is `display: none` at base
(`courses.css:946`), revealed only inside `@media (max-width: 640px)` via
`.unit-drawer:not([hidden])` (`:961`), and carries a literal `hidden` attribute until `unit_nav.js`
responds to the footer `[data-unit-drawer-open]` trigger. Sequence: resize; click the footer Contents
trigger; wait for `[data-unit-drawer]` to lose `hidden`; then assert.

Assertions at that size:

- the `.unit-drawer__legend` is present with a **non-trivial** box —
  `width >= 30` and `height >= 8` — and carries `aria-hidden="true"` (§4's decision; without the
  assertion nothing distinguishes a deliberate exclusion from a forgotten one). The thresholds are the point: `.visually-hidden` is 1px × 1px
  with a zero clip rect, which Playwright reports as **visible with a non-empty box**, so a
  `bounding_box() is not None` assertion cannot distinguish a rendered legend from a hidden one;
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
  neutralising `.unit-tree__label { flex: 1 1 auto }`, assert equal. Mechanical rather than a
  remembered baseline;
- a long `\(…\)` maths title, asserting no `.katex` box intersects `.unit-kind`'s rect — the
  re-earned audit §4 requires. Unlike the plain-text case above, the **rect** form is right here: a
  `.katex` inline-block genuinely escapes its parent's box, which is the whole reason that audit
  exists;
- the **unit page** head at 390 wide on a quiz or additional unit — the chip's `top >=
  title_bottom - 1` and its `left` near the group's left edge. This is the chip-bearing half of the
  mobile rule, which `test_e2e_unit_head_layout.py` structurally cannot cover;
- the **outline** page at 390 wide with a long unbroken / Polish title. "Stays within its box" is
  too loose to assert — under the two-level overflow in §4 the anchor, the `li` and the viewport
  disagree, and if the anchor sizes itself at min-content and overflows the `li`, the *content* is
  still inside the *anchor* and a naive assertion passes on the broken build. Assert both:
  `.outline-unit`'s `getBoundingClientRect().right <= li.right + 1` **and**
  `document.documentElement.scrollWidth === clientWidth`. These are the pins for
  `.outline-unit__title`'s `min-width: 0` / `overflow-wrap: anywhere` **and** for the anchor's own
  `min-width: 0`.

**Screenshots** (`tests/capture_unit_marker_screenshots.py`): both glyphs at rail size, both
glyphs on a marked **drawer row** at 390×780, the outline row at rest / hover / `:target`, the
unit-page head, and the drawer legend — light **and** dark, with dark judged on its own. The drawer
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
- `.unit-tree__label`'s `flex: 1 1 auto` reverted → the shared-`x` gutter assertion goes red.
- The `.unit-kind` rule deleted → the rail glyph-size assertion goes red.
- `.unit-kind-chip`'s `flex: none` dropped → the cap-length **chip-width** assertion goes red. NOT
  the chip-position assertion: both edges move together, so adjacency stays true (see the e2e note).
  `white-space: nowrap` has deliberately **no mutant** — it is inert for the two single-word labels
  that ship (§4), so any test claiming to redden on its removal would be green on the broken build.
- The `.lesson-unit__heading > .lesson-unit__title { flex: 0 1 auto }` reset deleted → the
  **short-title** desktop assertion goes red. NOT the cap-length one, which is pixel-identical on
  both builds.
- `overflow-wrap: anywhere` dropped from the drawer's `.unit-tree__label` override → the 390px
  `scrollWidth - clientWidth` assertion goes red.
- The anchor's `min-width: 0` (`app.css:544`) reverted, **or** the title's `overflow-wrap: anywhere`
  weakened to `break-word` → the 390-wide outline `scrollWidth === clientWidth` assertion goes red.
  Falsify these two **separately**: each alone is sufficient to break the row, so a single combined
  mutant would not prove both declarations are load-bearing.
- `.lesson-unit__heading`'s `flex: 1 1 auto` deleted → the pill-position assertion goes red.
- The mobile `.lesson-unit__heading { flex-basis: 100%; flex-wrap: wrap }` deleted →
  `test_e2e_unit_head_layout.py`'s phone assertions go red.
- `flex-wrap: wrap` added to the group at **desktop** → the cap-length **same-line** assertion
  (`chip.top ≈ title_top`) goes red.
- The drawer legend removed → the 30×8 legend assertion goes red.
- `lang="{{ LANGUAGE_CODE }}"` dropped from the chip → the render tests' `lang` assertion goes red.

A mutant must be removed by editing it out, never by `git checkout` of the file, which would destroy
the surrounding work.
