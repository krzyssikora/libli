# Instant add/remove of repeatable rows in the element editor

## Purpose

An author editing a **match-pairs** element cannot add more than two pairs without saving the
element and re-opening it. The `＋ Add pair` button that promises otherwise does nothing at all. A
prospective customer trying the authoring flow found this badly non-intuitive, and it is the kind of
defect that reads as "the editor is broken" rather than "the editor is limited."

This design makes repeatable rows behave the way an author expects: **rows appear and disappear
immediately, and nothing is persisted until Save.** It fixes the two element types that genuinely
cannot do this today, and makes "Remove" actually remove the row in the editors that share it.

A secondary win falls out of the switchgate work. `SwitchGateElementForm.clean()` rejects *interior*
blank options (`courses/element_forms.py:425-426`), while the editor renders six padded rows. An
author who fills rows 1, 2 and 6 today gets "Options cannot be empty." with **no way to close the
gap** — there is no remove control. The new remove control is the fix for that dead end.

## Background — what is actually wrong

Three distinct defects, in descending order of severity.

**1. Match pairs: the Add button is inert.**
`templates/courses/manage/editor/_edit_matchpairquestion.html:23` renders

```html
<button type="button" class="btn btn--small btn--ghost" data-pair-add>＋ {% trans "Add pair" %}</button>
```

A repo-wide search finds `data-pair-add` in that template and nowhere else — there is no handler in
`courses/static/courses/js/`. The button is `type="button"`, so it does not even submit the form.
Clicking it is a no-op with no feedback.

The row count is therefore fixed at render time: `MatchPairFormSet` is built with `extra=2`
(`courses/element_forms.py:927-940`), so the server renders *saved pairs + 2 blanks*. An author who
needs a fifth pair must fill two, Save, re-open, fill two more. The partial also has **no
`<template>` scaffold**, unlike every other formset editor that supports client-side add.

**2. "Remove" leaves the row on screen (three of four editors).**
In match (`_edit_matchpairquestion.html:18`), stepper (`_edit_stepper.html:21`) and checklist
(`_edit_markdone.html:21`), "Remove" is the raw Django `DELETE` checkbox: ticking it leaves the row
fully visible and unchanged until Save, with no feedback that anything happened.

**Choice is the exception.** `editor.js:496` toggles `choice-row--del` on the checkbox's `change`
event and `editor.css:178-179` dims the row (`opacity: .5`, `line-through`). Choice already gives
live feedback; what it lacks is the row actually going away. (This design makes that dim branch
unreachable — see "Dead code this change removes".)

**3. Choose & confirm (switchgate) has no add/remove control at all.**
`_edit_switchgate.html:11-21` renders a fixed list of option rows padded server-side to
`max(_MIN_ROWS, len(options) + 1)` with `_MIN_ROWS = 6` (`element_forms.py:362,402`). There is no add
button and no remove control. Exceeding the padded blanks requires Save-and-reopen, and interior
blanks cannot be closed at all.

## Scope

**In scope**

| Element | Add | Remove |
|---|---|---|
| Match pairs | new (button exists, needs a handler + a `<template>`) | new |
| Choose & confirm (switchgate) | new | new |
| Choice question | *keeps `addChoiceRow`*, amended below | new |
| Stepper | retrofit onto the shared helper | new |
| Checklist (mark-done) | retrofit onto the shared helper | new |

**Out of scope, deliberately**

- **Two-column.** Its column count is a genuine structural "Number of columns" field applied
  server-side, not a row list. Different problem, different fix.
- **Rewriting choice's add path.** `addChoiceRow` (`courses/static/courses/js/editor.js:419-443`)
  uses the older clone-the-last-rendered-row idiom. It stays — with a five-point amendment below.
- **Undo for a removal.** See "No undo, and why".
- **Any server-side Python change** outside test files. See "No server changes".
- Editors that already support client-side add/remove: matrix grid, multi-select grid, tabs,
  gallery, table, fill-in table, switch grid, drag-to-image.

## Architecture

Two new JavaScript modules. They are deliberately **not** unified: the two element families store
their rows differently, and a single helper would be one function with two disjoint branches — more
code and less clarity than two honest files.

Both modules follow the **hybrid idiom `switchgrid_editor.js` already uses** (see its file tail):
document-level delegated listeners for clicks, *plus* a small exported init pass. Delegation alone is
not sufficient, because the progressive-enhancement reveal and the post-422 reconciliation both need
a pass over the DOM.

**Every new control renders `type="button"` explicitly.** These buttons live inside the editor host
`<form>`, where a `<button>` with no `type` defaults to `submit` — clicking Remove would save the
element, an outcome far worse than the inert button this design exists to fix.

**Init contract, shared by both modules.** Each init function accepts **either an ancestor node or a
wrapper node itself**, mirroring `syncChoiceFeedback` (`editor.js:449-456`), which documents the trap
in its own comment: `querySelectorAll` finds only *descendants*, so a wrapper handed in directly
would match nothing. Implement as:

```js
var wraps = root.matches && root.matches(SEL) ? [root] : root.querySelectorAll(SEL);
```

This matters because the two call sites pass different things: `editor.js` passes the editor pane
(an ancestor), while `addChoiceRow` passes the wrapper itself.

**Both modules self-init at load**, via a `DOMContentLoaded` pass over `document`, matching
`switchgrid_editor.js`'s file tail and the retired `stepper_editor.js:30`. Without this, any
first-paint render carrying an already-open edit form (`_editor_scope.html:51,53` render `open_form`
server-side, and `_render_open_form` is reachable outside the fragment path) would leave every
JS-only control permanently `hidden`. Both init passes must be **idempotent** — safe to run
repeatedly over the same nodes.

### Module 1 — `courses/static/courses/js/formset_rows.js` (Django inline formsets)

A generic add/remove helper for any Django inline formset, driven by data attributes so no
per-element JavaScript is needed.

**Markup contract.** `data-fsrows` goes on a **wrapper element that encloses the row list, the add
button, the `<template>`, and `{{ formset.management_form }}`** — not on the `<ul>`. This is
load-bearing: in every existing template the add button and the `<template>` are *siblings* of the
`<ul>` (e.g. `_edit_stepper.html`: list `:15-25`, button `:26`, template `:30`), so a handler
calling `closest("[data-fsrows]")` from the button would find nothing if the attribute sat on the
list.

**The wrapper is `display: contents`**, so its children keep participating as grid items of
`.el-editor` (`display: grid; gap: var(--space-3)`, `editor.css:114`) and the existing gap between
the list and the add button is preserved. Note this is *not* because "CSS is unaffected by the DOM"
— CSS combinators are DOM-based too, and `display: contents` removes the box, not the node, so any
`.el-editor > X`, `X + Y` or `:nth-child` rule crossing the new wrapper would still stop matching.
An audit was done, covering **all three** selector shapes:

- child combinator — `editor.css:779` (`.el-editor > .scroll-x`) is the only `.el-editor >` rule in
  the codebase, and none of the five touched partials use `.scroll-x`;
- sibling combinators and `:nth-child` — no rule of either shape touches `.el-editor*`,
  `.pair-row*`, `.choice-row*`, `.stepper-row*` or `.markdone-row*`.

So the risk is zero here. Both sweeps must be re-run if the wrapper's position changes; the
conclusion is only as good as its evidence, which is why both are recorded rather than just the
first.

| Attribute | On | Meaning |
|---|---|---|
| `data-fsrows` | **wrapper** (`display: contents`) enclosing list + button + template + management form | Value is the formset prefix (`pairs`, `steps`, `items`, `choices`) |
| `data-fsrows-confirm` | wrapper | Translated confirm string for a non-empty removal |
| `data-fsrows-list` | the `<ul>` | Where new rows are appended |
| `data-fsrows-min` | wrapper | Minimum non-hidden rows the remove guard enforces |
| `data-fsrows-max` | wrapper | Maximum non-hidden rows; disables the add button — **optional** |
| `data-fsrow-item` | a row | Marks one form's row |
| `data-fsrows-add` | button | Add control — **optional** |
| `data-fsrows-template` | `<template>` | Blueprint row — **optional** |
| `data-fsrow-remove` | button inside a row | Remove control (JS-only affordance) |

**The row hook is `data-fsrow-item`, not `data-fsrow`.** A bare `data-fsrow` is a strict *prefix* of
`data-fsrows`, `data-fsrows-list` and `data-fsrow-remove`, and this repo's render tests assert by raw
substring (`resp.content.count(b"data-stepper-row") >= 1`, `"data-markdone-editor" in html`). A
retargeted `count(b"data-fsrow") >= 1` would be satisfied by the wrapper alone, so a template
shipping **zero rows** would still pass — an assertion that cannot fail. Every retargeted and new
render assertion must additionally match a **delimited** form (`data-fsrow-item>` or
`data-fsrow-item=""`), never a bare prefix.

`data-fsrows-add` and `data-fsrows-template` are **optional and must be absent together**: a wrapper
without them is *remove-only* and must not trip the warn-and-no-op rule below. **Choice is exactly
this case** — it keeps `addChoiceRow` and its own `data-choice-add`, so its wrapper has no blueprint
and no `data-fsrows-add`.

**Consequence for the reveal:** init job 1 must reveal `[data-fsrows-add], [data-choice-add]` within
the wrapper, not `[data-fsrows-add]` alone. Choice's add button carries only `data-choice-add`, so a
single-selector reveal would render it `hidden` and never unhide it — permanently breaking a
*currently working* control (`editor.js:375-376` → `addChoiceRow`), which is strictly worse than the
inert match button this design exists to fix. The progressive-enhancement render test would have
locked that in.

Every lookup resolves as `event.target.closest("[data-fsrows]")` then a scoped `querySelector`, so
nested containers and multiple formsets on one page cannot cross-talk.

**The prefix attribute value is authoritative.** `TOTAL_FORMS` is resolved as
`wrapper.querySelector('input[name="<prefix>-TOTAL_FORMS"]')`, not by a `[name$="-TOTAL_FORMS"]`
scope search, which would appear to work and then silently bind the wrong formset in any future
nested case. Because a typo in the attribute would otherwise produce a silent dead button — the
defect being fixed — the module must **`console.warn` and no-op loudly** when a wrapper that *has*
an add button lacks the named management input.

**Existing data hooks.** The `data-*` policy differs per editor and is not a blanket rename:

- **Choice keeps `data-choice-rows` / `data-choice-row` / `data-choice-add` in addition** to the new
  attributes. They are load-bearing for `editor.js` (`addChoiceRow`, `syncChoiceFeedback`, the
  radio-exclusivity handler) and are asserted by `tests/test_e2e_questions.py`,
  `tests/test_e2e_choice_editor_feedback.py` and `tests/test_e2e_math_input.py`.
- **Match's `data-pair-rows` / `data-pair-row` / `data-pair-add` are replaced**; nothing consumes
  them today.
- **Stepper's and checklist's hooks are replaced**, with their tests retargeted (see Testing).

**Add.**

1. Read `TOTAL_FORMS` for the wrapper's prefix.
2. Clone the template, replacing every `__prefix__` with that index.
3. Append to `data-fsrows-list`; increment `TOTAL_FORMS`.
4. **Call `libliInitFormsetRows(wrapper)`.** This is mandatory, not a disabled-state recompute: the
   blueprint reproduces the loop body verbatim, so the cloned row arrives with a *visible* DELETE
   label and a *hidden* remove button. Without the init call every JS-added row would show exactly
   the two-controls-one-of-which-is-inert state this design exists to eliminate.
5. Align and focus:

```js
if (window.libliAlignTopInPane) window.libliAlignTopInPane(row);
target.focus({ preventScroll: true });
```

`target` is the row's **first `input[type="text"]`, falling back to its first `textarea`** — match
rows carry two text inputs, choice rows a text input plus a feedback textarea.

A **bare `focus()` is forbidden.** The editor page's viewport is `overflow:hidden`, so a focus that
scrolls ancestor scrollports leaves the author unable to scroll back — the bug `switchgrid_editor.js`
documents in its own comments. `scrollIntoView` is likewise forbidden; both new modules join the
`PANE_RESIDENT` roster in `tests/test_editor_js_scroll_invariants.py`.

That roster **does not currently police `focus()`** — its only regex is `\.scrollIntoView\s*\(`. This
change adds a second regex flagging a `.focus(` call with no `preventScroll`, but **scoped to the two
new modules only**, via an explicit opt-in list separate from `PANE_RESIDENT`.

The scoping is not timidity: a repo-wide version would be **RED the moment it is added**. Bare
`.focus()` calls exist today throughout the roster — `filltable_editor.js:540,573,644,805,827,881,893`,
`table_editor.js:478,545,690,712,765,777`, `gallery_editor.js:75,86`, `text_toolbar.js:77,121,163`,
`tabs_editor.js:183` — 22 sites across five modules this change does not otherwise touch. Fixing them
is a separate piece of work, and several are legitimately different (`text_toolbar.js` refocuses an
editing surface, not a newly added row). The opt-in list must also match a **call**, not a mention:
`filltable_editor.js:570,642,879` and `unit_nav.js:75` discuss `.focus()` in comments, exactly the
hazard the file's existing `CALL` comment warns about.

**The blueprint.** Never `{{ formset.empty_form }}` bare — that invokes the form renderer and emits
Django's default `<div><label>…</label><input></div>` layout, structurally unlike the loop-body row.
Instead the blueprint **reproduces the loop-body markup verbatim**, substituting field-by-field:
`{{ f.left }}` becomes `{{ formset.empty_form.left }}`, likewise `.right`, `.id`, `.DELETE`. Django
renders `empty_form`'s index literal as `__prefix__`, so the tokens fall out for free — and because
the widgets come from the same ModelForm, the added row's `maxlength`, classes and `data-*` match a
server-rendered row exactly. Stepper and checklist migrate from their hand-written templates (which
hardcode `maxlength="500"`, a live drift hazard) to this form; match gains its first blueprint. The
three blueprint consumers are **match, stepper and checklist** — choice has no blueprint at all.

**Remove.**

1. **Guard:** if removing would take the list below the wrapper's `data-fsrows-min`, do nothing (see
   "Disabled state").
2. **Confirm:** if the row is non-empty, `window.confirm(...)` with the wrapper's
   `data-fsrows-confirm` string. **Non-empty means:** any `input[type="text"]` or `textarea`
   descendant whose `.value.trim()` is non-empty. The `DELETE` checkbox and hidden `id` input are
   excluded by construction. This deliberately covers choice's feedback `<textarea>`
   (`_edit_choicequestion.html:41-43`), so a row carrying only feedback text is not destroyed
   silently. An empty row is removed with no prompt.
3. **Tick:** set the row's `DELETE` checkbox `checked = true`. **No `change` event is dispatched** —
   see "Dead code this change removes" for why the only listener becomes unreachable.
4. **Hide:** set `row.hidden = true`.
5. Recompute the disabled state.
6. **Move focus.** The click left focus on a button that is now hidden, so focus would otherwise fall
   to `<body>` — a keyboard-a11y regression and, on this `overflow:hidden` page, the same scroll
   hazard the add path guards against. Move it to the remove button of the nearest **following**
   non-hidden row, falling back to the nearest preceding one, then to the add button, using
   `focus({ preventScroll: true })`. Module 2 does the same after detaching.

**The row is never detached from the DOM and `TOTAL_FORMS` is never decremented.** Django validates
forms `0 … TOTAL_FORMS-1`; punching a gap in the indices means a persisted row's `id` field vanishes
from the POST, and the formset then either mis-saves or rejects the submission. Hiding keeps the
indices contiguous while being visually identical to removal. A hidden, DELETE-ticked row for a
persisted pair deletes it on save; the same for a never-saved blank row is an empty extra form,
which the formset ignores.

**Why the `hidden` attribute rather than a modifier class.** `zone-editor.js` already implements this
exact mechanic for the drag-to-image formset with a class — it ticks `[name$="-DELETE"]`, adds
`zone-row--del`, and `editor.css:659` reads `.zone-row--del { display: none; }` with the comment
"deleted rows: hidden; DELETE checkbox stays ticked". That is the closest prior art and is
deliberately *not* copied: both approaches need one CSS rule per row class, so the class idiom saves
nothing, while `hidden` additionally removes the row from the accessibility tree and from tab order —
which is what makes the DELETE checkbox genuinely unreachable under JS and lets the dim branch be
retired as dead code. The trade is stated here so a later reader can see it was a decision.

**Removing the row that carries the correct-answer marker.** Choice's `is_correct` marker is per-row
(`_edit_choicequestion.html:26-28`). Nothing is re-marked automatically; the existing server-side
validation prompts on save. This mirrors module 2's identical decision for switchgate's radio:
silently promoting another row to "correct" is a worse failure than an explicit prompt.

**`[hidden]` needs explicit CSS guards — for rows *and* for the DELETE labels.** `row.hidden = true`
alone will not hide these elements: every target class sets an author-level `display` at equal
specificity, which beats the UA `[hidden] { display: none }` rule. Eight selectors are needed, split
across two stylesheets:

- `courses/static/courses/css/editor.css` — `.pair-row[hidden]`, `.choice-row[hidden]`,
  `.pair-row__del[hidden]`, `.choice-row__del[hidden]` (classes at `:141`, `:157`, `:143`, `:165`)
- `courses/static/courses/css/courses.css` — `.stepper-row[hidden]`, `.markdone-row[hidden]`,
  `.stepper-row__del[hidden]`, `.markdone-row__del[hidden]` (classes at `:1990`, `:2048`, `:1992`,
  `:2050`)

each declaring `display: none`. The `__del` labels are `display: inline-flex` and are exactly as
affected as the rows — omitting them would leave the author looking at two remove controls, the
failure the reveal exists to prevent. The stylesheet-guard test reads **both** files and fails if any
of the eight rules is deleted. This repo has been bitten by this gotcha at least five times;
`core/static/core/css/app.css` carries guards with comments naming it at `:42`, `:185`, `:546`,
`:1009`, `:1191`.

**Disabled state.** When the guard in step 1 would fire, the remove buttons are set `disabled`, not
left live to silently no-op. A control that does nothing when clicked is the defect this design
exists to remove. Recomputed after every add, remove and init.

**The bounds are per-formset, carried on `data-fsrows-min` / `data-fsrows-max`** — a uniform "one"
would be wrong, and two of the four editors have a *maximum* as well. All four were read from the
code:

| Editor | min | max | Server rule |
|---|---|---|---|
| Match pairs | `1` | — | ≥1 complete pair — "Add at least one pair." (`element_forms.py:915-924`) |
| Choice | `2` | — | ≥2 non-deleted non-empty rows — "Add at least two choices." (`element_forms.py:667-674`) |
| Stepper | `1` | `20` | `StepperElement.MIN_STEPS` / `MAX_STEPS` (`models.py:618-619`), enforced at `element_forms.py:1888-1895` |
| Checklist | `1` | `20` | `MarkDoneElement.MIN_ITEMS` / `MAX_ITEMS` (`models.py:655-656`), enforced at `element_forms.py:1944-1952` |

Choice is why the minimum is an attribute rather than a constant: under a hard-coded "one" an author
could remove down to a single choice, hit Save, and get a validation error the client could have
prevented — inconsistent with switchgate's threshold of two and with the principle above.

**The maximum matters for the same reason, in the other direction.** Stepper and checklist reject a
21st row on save ("A stepper can have at most 20 steps."). An uncapped add button would let an author
type a 21st step and only discover the limit at Save — a new instance of exactly the
could-have-been-prevented failure this design is about. When the non-hidden row count reaches
`data-fsrows-max`, the **add** button is `disabled`, recomputed alongside the remove buttons. Editors
with no maximum omit the attribute.

**The remove button renders inside `{% if formset.can_delete %}`.** In all four templates the DELETE
label is wrapped in that conditional (`_edit_matchpairquestion.html:17-19`, `_edit_stepper.html:20-22`,
`_edit_markdone.html:20-22`, `_edit_choicequestion.html:37-39`). A remove button rendered *outside* it
would, on a `can_delete=False` formset, have no checkbox to tick — a silently inert control, the
defect this design condemns. Correspondingly, module 1 **skips (and `console.warn`s on) any row whose
`DELETE` input is absent**, mirroring the prefix warn-and-no-op rule.

**Progressive enhancement.** The existing `<label class="…__del">{{ f.DELETE }} Remove</label>`
remains in the DOM as the state carrier and as the **no-JS affordance**. The JS-only controls — the
per-row remove button **and the add button** — render with a bare `hidden` attribute. Init job 1
flips both: it hides the checkbox label (via the `hidden` attribute, hence the `__del` guards above)
and reveals the buttons.

**The add buttons are hidden too, in all four formset editors.** `_edit_matchpairquestion.html:23`
currently renders `＋ Add pair` unconditionally, so a no-JS author sees it and it does nothing — the
same inert-control defect Purpose condemns, in the very editor this design is named for. Hiding and
revealing every add button makes the rule uniform with switchgate's.

**Remove-button affordance.** In the formset editors the remove control is
`<button type="button" class="btn btn--small btn--ghost" data-fsrow-remove hidden>`, matching the add
buttons' existing classes, carrying a translated label. `.btn`'s `[hidden]` state is already guarded
(`app.css:42`), so this deliberately avoids introducing a new `display`-setting component that would
need its own guard. It is placed **immediately after the `__del` label** in each of the four row
templates — inside `.choice-row__main` for choice, and as the last child of the `<li>` for match,
stepper and checklist — so it occupies the position the hidden label vacates and row rhythm is
unchanged. (Switchgate differs — see module 2.)

**Init pass.** `window.libliInitFormsetRows(root)` performs three idempotent jobs:

1. hide each row's DELETE label and reveal the JS-only add and remove buttons;
2. **hide every row whose `DELETE` checkbox is already ticked** — this reconciles the 422 re-render;
3. recompute the disabled state of the remove buttons.

**Consumers.** Match pairs (add + remove; gains its first blueprint), stepper and checklist
(retrofitted — `stepper_editor.js` and `markdone_editor.js` are retired), choice (remove only).

**Interaction with `addChoiceRow`.** `editor.js:419-443` clones `rows[rows.length - 1]`. Once a row
can be hidden, cloning the last row can clone a *hidden* one, producing a new row the author cannot
see while `TOTAL_FORMS` still increments. Five amendments:

1. clone the last **non-hidden** row;
2. strip `hidden` and untick `DELETE` on the clone;
3. clear `disabled` on the clone's remove button (`cloneNode(true)` copies it);
4. call `window.libliInitFormsetRows(wrapper)` afterwards — `addChoiceRow` lives in `editor.js`, not
   module 1, so module 1's own post-add init does not cover it;
5. resolve `total` from the choice wrapper's prefix instead of `editor.js:421`'s
   `root.querySelector('[name$="-TOTAL_FORMS"]')`, which is the loose pattern this spec forbids —
   shipping the rule and a counter-example to it in one diff would be incoherent.

**Wiring.** `editor.html` loads every editor module by an explicit `<script src=… defer>` line
(`:259-289`); there is no glob. It gains tags for **both** new modules with the customary explanatory
`{% comment %}`, and loses the two retired ones (`:269`, `:277`). `editor.js:125-126` loses the two
retired `libliInit*` calls and gains `libliInitFormsetRows` and `libliInitSwitchGateEditor`.

### Dead code this change removes

Once init job 1 hides the DELETE label, the checkbox is out of the accessibility tree and out of tab
order, so **no JS author can ever fire its `change` event**. Its only listener therefore becomes
unreachable. Delete, in the same change:

- `editor.js:493-497` — the DELETE branch that toggles `choice-row--del`;
- `editor.css:178-179` — the `.choice-row--del` dim rule;
- `editor.js:439` — `clone.classList.remove("choice-row--del")` in `addChoiceRow`.

Verified: `choice-row--del` has exactly two references in the codebase (`editor.js:439`, `:496`);
`syncChoiceFeedback` does **not** read it. Leaving them would ship a rule that can never apply, and
the e2e that asserts the dim must be rewritten regardless (see Testing).

### Module 2 — `courses/static/courses/js/switchgate_editor.js` (positional option list)

**Filename caution.** The directory already holds `switchgate.js` (the student runtime) and
`switchgrid_editor.js` (a *different* element, one letter apart). The name follows the repo's
`X.js` / `X_editor.js` convention and is kept, but the file must open with a header comment naming
both siblings so it is not mis-edited.

Switchgate is **not** a formset. Its options are repeated `name="option"` inputs read positionally
via `data.getlist("option")` (`element_forms.py:386`), and the correct answer is a radio whose value
is the option's **index** (`_edit_switchgate.html:15`, `value="{{ forloop.counter0 }}"`).

**Markup contract.** `_edit_switchgate.html:12-21` has zero data hooks and must gain them. As in
module 1 the delegation root is a **wrapper enclosing the option list, the add button and the
`<template>`**, `display: contents`; putting it on `.el-editor__options` alone would leave the add
button outside it and `closest()` would return `null`, reproducing the dead-button defect.

| Attribute | On | Meaning |
|---|---|---|
| `data-sgate` | **wrapper** (`display: contents`) enclosing list + button + template | Delegation root |
| `data-sgate-confirm` | wrapper | Translated confirm string |
| `data-sgate-placeholder` | wrapper | Placeholder template, `"{% trans 'Option' %} __pos__"` |
| `data-sgate-list` | `.el-editor__options` | Where new rows are appended |
| `data-sgate-row` | `.el-editor__option-row` | One option |
| `data-sgate-add` | button | Add control |
| `data-sgate-template` | `<template>` inside the wrapper | Blank row blueprint |
| `data-sgate-remove` | button inside a row | Remove control |

**The blueprint row is a verbatim copy of the loop body** with only tokens substituted. Switchgate is
not a formset, so there is no `empty_form` to guarantee parity — this is the hand-written blueprint
module 1 avoids, and the asymmetry is unavoidable. To bound the drift risk the blueprint must
preserve every attribute the rendered row carries: the radio's `name="answer"` and
`aria-label="{% trans 'Correct option' %}"`, and the text input's `name="option"` and
`class="rte-source"` (`_edit_switchgate.html:15-18`).

**Two distinct tokens are required**, because the rendered row is 0-based in one place and 1-based in
the other (`value="{{ forloop.counter0 }}"` at `:15`, `placeholder="… {{ forloop.counter }}"` at
`:18`):

- `__index__` → the 0-based radio `value`;
- `__pos__` → `index + 1`, the placeholder's number.

Substituting one token into both would render "Option 0, Option 1, …".

**Renumbering must not parse the rendered placeholder.** A server-rendered row carries a fully
substituted, **translated** literal (`placeholder="Opcja 3"` under `pl`), with no token left to
rewrite; a `replace(/\d+$/, n)` would be locale-fragile and silently wrong wherever the number is not
final. Instead the wrapper carries `data-sgate-placeholder="{% trans 'Option' %} __pos__"`, and the
renumber pass **rebuilds every row's placeholder from that single template string**. Server-rendered
and cloned rows then go down one code path.

**Add.** Append a row from the template with the next index, blank text, radio unchecked; **call
`libliInitSwitchGateEditor(wrapper)`** — mandatory for the same reason as module 1, since a verbatim
blueprint carries `hidden` on the remove button and the row just created is the one most likely to
need removing — then `libliAlignTopInPane` + `focus({ preventScroll: true })` on its text input.

**Remove.**

1. **Guard:** when exactly two rows remain, the remove buttons are `disabled`.
2. **Confirm:** prompt only when the row's `input[type="text"]` has a non-empty `.value.trim()`.
   Blank rows are removed with no prompt — essential, because the padded render is mostly blank rows
   and closing an *interior blank* is the headline use case; prompting on every blank removal would
   make the fix worse than the defect.
3. **Detach and renumber.**

Unlike module 1 the row **must be detached from the DOM**. Hiding is not sufficient and would
actively corrupt the data: a hidden input still submits, and `clean()` (`element_forms.py:421-428`)
drops only *trailing* blanks and explicitly **rejects interior blanks** with "Options cannot be
empty." After detaching, renumber every remaining row — the radio's `value` and the rebuilt
placeholder — or the survivors read "Option 1, Option 3, Option 4".

If the removed row was the checked one, **leave nothing checked.** The existing validation
("Select the correct option.", `element_forms.py:435-438`) prompts the author on save.

**Minimum guard.** The guard counts **DOM rows, not filled values** — a value-based guard would fire
on a legitimately blank-but-in-progress list, and the padded render always starts with blanks. The
stricter "at least two *non-empty* options" rule stays server-side, where `_MIN_OPTIONS`
(defined at `element_forms.py:361`, compared at `:427`) already enforces it.

**Init pass.** `window.libliInitSwitchGateEditor(root)`, three idempotent jobs:

1. reveal the JS-only add and remove controls;
2. recompute the two-row disabled state;
3. renumber the rows, so a re-swap or 422 re-render always lands on contiguous indices.

**No-JS story.** Both switchgate controls render with a bare `hidden` attribute and are revealed by
the init pass. Without this a no-JS author would be shown a brand-new Add button and per-row Remove
buttons with no server-side handler behind either.

**Affordance and CSS scoping.** Switchgate's remove control uses the `.el-editor__remove` `×`
component, matching the visually adjacent switch-grid editor — a `×`-free button beside switchgrid's
`×` would be a gratuitous inconsistency.

**That component is not currently reusable, and this is the one place the change adds CSS rather than
just guarding it.** Every rule for it is scoped to switchgrid — `app.css:1452-1478` holds the sizing,
`display: inline-grid`, `:hover` and `:focus-visible` blocks, all under
`.el-editor--switchgrid .el-editor__remove`. Dropping the bare class into a switchgate row would
inherit *none* of it and render a raw UA button. Two rules are therefore added, both scoped to
`.el-editor--switchgate`:

1. a **style twin** of the `app.css:1452` block (sizing, `display: inline-grid`, hover, focus), and
2. the `[hidden]` **guard twin**: `.el-editor--switchgate .el-editor__remove[hidden] { display: none; }`,
   mirroring `app.css:1469` and its comment "inline-grid overrides the [hidden] attribute".

Promoting the component to an unscoped `.el-editor__remove` was considered and rejected: it would
restyle switchgrid's shipped control as a side effect, and an unscoped `.el-editor__remove[hidden]`
ties on specificity with the existing `.el-editor--switchgrid .el-editor__remove` block, leaving the
outcome to source order. Duplicating under a scope leaves switchgrid untouched. Both new rules go in
the stylesheet-guard test.

`.el-editor__option-row` is likewise **shared**: defined at `app.css:1223` and re-styled under
`.el-editor--switchgrid` at `:1437-1445`. Every new rule must be scoped under
`.el-editor--switchgate` or it leaks into the switch-grid cycler rows.

### No server changes

Both mechanics emit POST payloads the existing parsers already accept:

- module 1 posts a well-formed formset with a possibly larger `TOTAL_FORMS` and some `DELETE` flags —
  exactly what `build_matchpair_formset` / `build_stepper_formset` / `build_markdone_formset` /
  `build_choice_formset` already handle;
- module 2 posts a shorter `option` list with a consistent `answer` index — exactly what
  `SwitchGateElementForm.clean()` already handles.

There is **no model change, no migration, and no `FORMAT_VERSION` bump.** No application Python is
modified; the only `.py` files touched are tests.

## Data flow

**Adding a match pair.** Click `data-fsrows-add` → read `pairs-TOTAL_FORMS` (say `3`) → clone the
blueprint → `pairs-__prefix__-left` becomes `pairs-3-left` → append → `TOTAL_FORMS = 4` → init the
wrapper (reveals the new row's remove button, hides its DELETE label, recomputes disabled) → align +
focus. On Save the POST carries four forms; `formset.save()` creates the new `MatchPair` rows.
Nothing reached the server before Save.

**Removing a saved pair.** Click `data-fsrow-remove` on row 1 → row has text → confirm → tick
`pairs-1-DELETE`, hide the row. POST still carries `pairs-1-id` and `pairs-1-DELETE=on`;
`formset.save()` deletes that `MatchPair`. `TOTAL_FORMS` is unchanged.

**Removing a switchgate option.** Click remove on the middle of three filled options → confirm →
detach the row → the two survivors are renumbered to `0`/`1` (radio value) and their placeholders
rebuilt as "Option 1"/"Option 2". `getlist("option")` returns two values in DOM order and `answer`
indexes correctly into them.

**Switchgate removals of blank rows do not persist — by design.** `option_rows()` re-pads to
`max(_MIN_ROWS, len(opts) + 1)` on every render (`element_forms.py:402`, `_MIN_ROWS = 6`). Removing a
blank padding row, saving and re-opening brings the blanks back. This is correct: blanks are not
data, and the padding exists so an author always has somewhere to type. What the remove control buys
within a session is real — it is the only way to close an **interior** blank and get past "Options
cannot be empty." Removals that drop a *filled* option persist normally.

## Error handling

**The 422 re-render.** When a save fails validation the server re-renders from the POST
(`courses/views_manage.py:2257-2278`). Rows the author removed come back **visible with their DELETE
box ticked**, because the server knows nothing about the client-side `row.hidden`.

The fix is client-side, **not** a template rule keyed on `f.DELETE.value()`. Init job 2 hides every
row whose DELETE is already ticked. Keying it in the template was considered and rejected: it would
hide the row for **no-JS authors too**, and since the DELETE checkbox lives *inside* the row it
hides, a no-JS author who ticked a box and then hit an unrelated validation error could never untick
it — a real capability regression.

Switchgate needs no equivalent, with one qualification. `option_rows()` prefers the posted options on
a bound form (`element_forms.py:393-398`), so **filled options stay removed**. It still re-pads to six
(`:402` runs on both branches), so the blank rows come back — benign, because they land *trailing*
and `clean()` pops trailing blanks.

**No undo, and why.** A removed row cannot be restored within the session (its checkbox is inside the
hidden row). Accepted rather than solved: non-empty rows are confirm-guarded, so un-prompted removals
discard nothing, and the editor's Cancel discards the whole session. An "N rows removed — restore"
affordance is deliberate future scope.

**What this trades away.** `editor.js:492` currently documents the DELETE tick as "Reversible: untick
to restore the row." For **no-JS authors that stays exactly true**. **JS authors trade it**: the
reversible tick becomes an irreversible, confirm-guarded removal. That is the intended bargain — a
tick that leaves the row on screen is the reported defect — but it is a real change, not a pure
addition, and the stale comment goes with the dead code above.

**Editor fragment swaps.** Delegated listeners survive swaps automatically; the init passes are
re-run by `editor.js`, exactly as `libliInitSwitchGridEditors` is today.

**Confirm dialogs.** `window.confirm` with the translated string read from a data attribute, matching
`tabs_editor.js:146` — which is `label(editor, "confirm", "Delete this tab?")`, a lookup **with a
hard-coded English default**. Both modules must do the same: a missing or mistyped
`data-fsrows-confirm` / `data-sgate-confirm` must fall back to a built-in default string and
`console.warn`, never reach `window.confirm(null)` (which renders a dialog reading "null"). Silence
there would contradict the loud-failure rule applied to a mistyped prefix.

**Degradation without JavaScript.** In the formset editors the DELETE checkbox labels stay visible
and functional while the add and remove buttons stay `hidden`. In switchgate both new controls stay
`hidden`. The server still renders `extra` blank rows and switchgate's six padded rows. A no-JS
author retains exactly today's capability in every editor touched — and in match pairs is no longer
shown an add button that does nothing.

## Testing

**Existing tests this change breaks — must be updated, not deleted.** Note the list spans **both**
`tests/` and `courses/tests/`; a narrowly scoped run over one directory will miss the other.

- `tests/test_stepper_editor_assets.py` — asserts `stepper_editor.js` contains
  `window.libliInitStepperEditor` (`:14`), `steps-TOTAL_FORMS` (`:15`) and `__prefix__` (`:16`), and
  that the editor page references the file (`:28`). Retarget to `formset_rows.js` /
  `libliInitFormsetRows`. **Drop the `steps-TOTAL_FORMS` assertion** — a prefix-agnostic helper can
  never contain that literal. See the blueprint-render test below for what replaces `__prefix__`.
- `courses/tests/test_markdone_editor.py` — `:20` asserts `"data-markdone-editor" in html` and `:30`
  asserts `"courses/js/markdone_editor.js" in body`. Both fail once the module is retired and the
  hooks are replaced; retarget both.
- `tests/test_editor_stepper_add.py:27-28` — asserts `data-stepper-editor` and `data-stepper-row`.
  Retarget to the new attribute names.
- `tests/test_editor_js_scroll_invariants.py:24-40` — the `PANE_RESIDENT` roster reads each file from
  disk and asserts existence, so it *raises* on the two removed files (`:31-32`). Drop them, add
  `formset_rows.js` and `switchgate_editor.js`, and **extend the test with a second regex** flagging
  a bare `.focus(`.
- `tests/test_e2e_questions.py:310-317` — does
  `row2.locator("input[name='choices-2-DELETE']").check()`. That checkbox sits inside the
  `<label class="choice-row__del">` the init pass hides, so under JS — the only mode Playwright runs
  in — `.check()` fails actionability. Rewrite to click `data-fsrow-remove` and assert the row is no
  longer visible and its DELETE is ticked. The `choice-row--del` assertion at `:315` is **deleted**
  along with the dim rule itself. ***Needs a `dialog` handler*** — the row is filled at `:301`
  (`fill("Gamma")`), so the removal is confirm-guarded and Playwright's auto-dismiss would otherwise
  take the cancel path and fail against a correct build.

**New form-level tests (pytest).**

- A match POST with **more rows than the server rendered** — impossible to reach today — saves all of
  them. The direct regression test for the reported defect.
- A ticked `DELETE` on a persisted pair deletes exactly that pair and leaves the others intact.
- A switchgate POST with a middle option removed and `answer` renumbered stores the intended option
  as correct.
- **Blueprint render, per formset editor with an add button** (match, stepper, checklist): the
  response contains a `data-fsrows-template` whose content carries `<prefix>-__prefix__-<field>`.
  This replaces the retired `__prefix__` assertion, which after retargeting would have landed on
  `formset_rows.js` — where the literal appears merely because the module performs the replace, so it
  would pass even if a template shipped no blueprint at all. Match, the headline defect, would
  otherwise gain its first blueprint with no test that it exists.
- **Progressive-enhancement render.** Two halves with different scopes: (a) across **all five**
  touched editors, the JS-only add and remove buttons render carrying `hidden`; (b) across the
  **four formset editors only**, the DELETE checkbox label renders *without* it. Switchgate has no
  formset and no DELETE checkbox (`_edit_switchgate.html:12-21` is a positional list), so half (b)
  does not apply there. This is the only guard on the no-JS story, which is why the checkbox stays
  and why the template-side `f.DELETE.value()` rule was rejected.
- **Bounds render:** each formset wrapper carries the `data-fsrows-min` (and, for stepper and
  checklist, `data-fsrows-max="20"`) matching the server constant, so a drift between the client
  guard and `MIN_STEPS`/`MAX_ITEMS` fails a test rather than reaching an author.
- A stylesheet guard reading **both** `editor.css` and `courses.css`, asserting all eight
  `[hidden] { display: none }` rules plus the switchgate `.el-editor__remove[hidden]` twin,
  structured so deleting any one fails the test.
- An asset test asserting `editor.html` references both new modules.

**Retrofit no-regression tests (the riskiest part of this change).** Stepper and checklist are
*working* editors being rewired onto a new module; nothing above would catch a regression there. Add,
for each: add a row past `extra`, fill it, save, re-open, assert it persisted; and remove a persisted
row and assert it is gone. These are a **GREEN-on-master, GREEN-after** pair — not falsifiable
against the current build, which is the point.

**New end-to-end tests (Playwright).**

- Open a **saved** match element, click `Add pair` three times **with no intervening save**, fill all
  three, save, re-open, assert three new pairs persisted.
- Remove a filled pair through the confirm dialog; assert it is gone after save. *(Needs a `dialog`
  handler.)*
- **Post-init state:** after the editor opens, the DELETE label is not visible and the remove button
  is — the JS half of the progressive-enhancement guarantee.
- **Focus after removal** does not fall to `<body>`: remove a middle row by keyboard and assert
  `document.activeElement` is the following row's remove button. Without this the keyboard path
  regresses silently, since a mouse user never notices.
- **The maximum cap:** on a stepper at 20 steps, the add button is `disabled`.
- **The 422 reconciliation**, the subtlest mechanism in the design: remove a row, trigger a
  validation failure on save, assert the removed row comes back **not visible** with its DELETE still
  ticked, then fix the error and assert the removal persisted.
- Switchgate: add an option beyond the padded blanks; remove a middle *filled* option and assert the
  correct answer still points at the intended option **text** after save *(needs a `dialog`
  handler)*; and remove an *interior blank* row and assert the save now succeeds where it previously
  failed with "Options cannot be empty." *(no `dialog` handler — blank rows are removed silently)*.

**Falsification.** Every *new* test above must be shown **RED** before the fix, with the mutant chosen
from the failure mode rather than the assertion. The match "add three pairs" test is RED on `master`
by construction. The retrofit tests are the stated exception.

**Three known traps that make a correct build look broken:**

- Playwright **auto-dismisses** `confirm`. A removal test without an explicit `dialog` handler takes
  the *cancel* path, so the row is never removed and the test fails against a correct
  implementation. The bullets above state which tests need one.
- A hidden row is still **matched by `locator.count()`**; assert on visibility, not count.
- The test-DB container must be started before any pytest run, or the suite appears to hang for
  ~4m21s.

## Delivery

New translated strings ship in this change: a confirm string per editor, the add labels, and the
remove buttons' labels/`aria-label`s. Delivery includes `makemessages -l pl -l en --no-obsolete` plus
`compilemessages`, with an explicit Polish translation for each new string and **every fuzzy flag
cleared** — this repo has a documented trap where `makemessages` fuzzy-prefills a *wrong*
translation. Extend the existing i18n catalog guard (e.g. `tests/test_i18n_stepper.py`) to cover the
new strings. Run `uv run ruff format .` last, after every other edit.
