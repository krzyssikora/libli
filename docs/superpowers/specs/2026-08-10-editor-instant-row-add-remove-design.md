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

**Choice is the exception and must not be described as broken.** `editor.js:496` toggles
`choice-row--del` on the checkbox's `change` event and `editor.css:178-179` dims the row
(`opacity: .5`, `line-through`). This is deliberate and tested. Choice already gives live feedback;
what it lacks is the row actually going away.

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
  uses the older clone-the-last-rendered-row idiom. It stays — but it needs a small amendment (see
  "Interaction with `addChoiceRow`"), because hidden rows would otherwise break it.
- **Undo for a removal.** See "No undo, and why" under Error handling.
- **Any server-side Python change.** See "No server changes".
- Editors that already support client-side add/remove: matrix grid, multi-select grid, tabs,
  gallery, table, fill-in table, switch grid, drag-to-image.

## Architecture

Two new JavaScript modules. They are deliberately **not** unified: the two element families store
their rows differently, and a single helper would be one function with two disjoint branches — more
code and less clarity than two honest files.

Both modules follow the **hybrid idiom `switchgrid_editor.js` already uses** (see its file tail):
document-level delegated listeners for clicks, *plus* a small exported init pass re-run after each
editor fragment swap. Delegation alone is not sufficient here, because the progressive-enhancement
reveal and the post-422 reconciliation both need a pass over the DOM.

**Every new control renders `type="button"` explicitly.** These buttons live inside the editor host
`<form>`, where a `<button>` with no `type` defaults to `submit` — clicking Remove would save the
element, an outcome far worse than the inert button this design exists to fix.

### Module 1 — `courses/static/courses/js/formset_rows.js` (Django inline formsets)

A generic add/remove helper for any Django inline formset, driven by data attributes so no
per-element JavaScript is needed.

**Markup contract.** `data-fsrows` goes on a **wrapper element that encloses the row list, the add
button, the `<template>`, and `{{ formset.management_form }}`** — not on the `<ul>`. This is
load-bearing: in every existing template the add button and the `<template>` are *siblings* of the
`<ul>` (e.g. `_edit_stepper.html`: list `:15-25`, button `:26`, template `:30`), so a handler
calling `closest("[data-fsrows]")` from the button would find nothing if the attribute sat on the
list.

**The wrapper must be `display: contents`.** `.el-editor` is a grid with `gap: var(--space-3)`
(`editor.css:114`), and today the `<ul>` and the add button are separate grid items. A plain `<div>`
wrapper would make them children of a non-grid box and collapse that gap in all four editors;
`display: contents` keeps the existing layout byte-for-byte while still being a real element for
`closest()`, which is DOM-based and unaffected by CSS. The rule goes in `editor.css`.

| Attribute | On | Meaning |
|---|---|---|
| `data-fsrows` | **wrapper** (`display: contents`) enclosing list + button + template + management form | Value is the formset prefix (`pairs`, `steps`, `items`, `choices`) |
| `data-fsrows-confirm` | wrapper | Translated confirm string for a non-empty removal |
| `data-fsrows-list` | the `<ul>` | Where new rows are appended |
| `data-fsrow` | a row | Marks one form's row |
| `data-fsrows-add` | button | Add control |
| `data-fsrows-template` | `<template>` | Blueprint row (see below) |
| `data-fsrow-remove` | button inside a row | Remove control (JS-only affordance) |

Every lookup resolves as `event.target.closest("[data-fsrows]")` then a scoped `querySelector`, so
nested containers and multiple formsets on one page cannot cross-talk.

**The prefix attribute value is authoritative.** `TOTAL_FORMS` is resolved as
`wrapper.querySelector('input[name="<prefix>-TOTAL_FORMS"]')`, not by a `[name$="-TOTAL_FORMS"]`
scope search. A scope search would appear to work and then silently bind the wrong formset in any
future nested case. Because a typo in the attribute would otherwise produce a silent dead button —
the defect being fixed — the module must **`console.warn` and no-op loudly** when the named
management input is absent.

**Existing data hooks.** The `data-*` policy differs per editor and is not a blanket rename:

- **Choice keeps `data-choice-rows` / `data-choice-row` / `data-choice-add` in addition** to the new
  attributes. They are load-bearing for `editor.js` (`addChoiceRow`, `syncChoiceFeedback`, the
  radio-exclusivity handler and the DELETE branch) and are asserted by `tests/test_e2e_questions.py`,
  `tests/test_e2e_choice_editor_feedback.py` and `tests/test_e2e_math_input.py`.
- **Match's `data-pair-rows` / `data-pair-row` / `data-pair-add` are replaced** by the new
  attributes; nothing consumes them today.
- **Stepper's and checklist's hooks are replaced**, with their tests retargeted (see Testing).

**Add.** Read `TOTAL_FORMS` for the wrapper's prefix, clone the template, replace every `__prefix__`
with that index, append to `data-fsrows-list`, increment `TOTAL_FORMS`, recompute the disabled state,
then align and focus:

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

Note that roster **does not currently police `focus()`** — its only regex is
`\.scrollIntoView\s*\(`, and `stepper_editor.js:20` calls a bare `input.focus()` today while sitting
in the roster. So this change also **extends that test with a second regex** flagging a `.focus(`
call with no `preventScroll` in any pane-resident module. Without that extension the rule above is
convention-only and would silently rot.

**The template row.** Never `{{ formset.empty_form }}` bare — that invokes the form renderer and
emits Django's default `<div><label>…</label><input></div>` layout, which is structurally unlike the
loop-body row and would make an added row look nothing like a rendered one. Instead the blueprint
**reproduces the loop-body markup verbatim**, substituting field-by-field: `{{ f.left }}` becomes
`{{ formset.empty_form.left }}`, and likewise `.right`, `.id`, `.DELETE`. Django renders
`empty_form`'s index literal as `__prefix__`, so the tokens fall out for free — and because the
widgets come from the same ModelForm, the added row's `maxlength`, classes and `data-*` match a
server-rendered row exactly. This matters most for choice, whose row wraps its field in
`<span class="choice-row__text" data-math-field>` with a math trigger and preview
(`_edit_choicequestion.html:31-36`) that a hand-written row would silently drop, removing math
authoring from added rows. Stepper and checklist migrate from their hand-written templates (which
already hardcode `maxlength="500"`, a live drift hazard) to this form.

**Remove.**

1. **Guard:** if this is the last non-hidden row in the list, do nothing (and see "Disabled state").
   Removing every row would post an empty formset, which fails validation with "Add at least one
   pair." (`element_forms.py:920-923`) and leaves the author staring at an empty list.
2. **Confirm:** if the row is non-empty, `window.confirm(...)` with the wrapper's
   `data-fsrows-confirm` string. **Non-empty means:** any `input[type="text"]` or `textarea`
   descendant of the row whose `.value.trim()` is non-empty. The `DELETE` checkbox and the hidden
   `id` input are excluded by construction. This deliberately covers choice's feedback `<textarea>`
   (`_edit_choicequestion.html:41-43`), so a row carrying only feedback text is not destroyed
   silently. An empty row is removed with no prompt.
3. **Tick and dispatch:** set the row's `DELETE` checkbox `checked = true` and dispatch
   **`new Event("change", { bubbles: true })`**. The bubbling flag is mandatory: `editor.js:3` binds
   `var root = document.querySelector(".editor")` and registers its `change` handler on that root
   (`:474`, DELETE branch at `:493-497`), so a default non-bubbling event would never reach it and
   `choice-row--del` would never apply — the exact failure this step exists to prevent.
4. **Hide:** set `row.hidden = true`.

**The row is never detached from the DOM and `TOTAL_FORMS` is never decremented.** Django validates
forms `0 … TOTAL_FORMS-1`; punching a gap in the indices means a persisted row's `id` field vanishes
from the POST, and the formset then either mis-saves or rejects the submission. Hiding keeps the
indices contiguous while being visually identical to removal. A hidden, DELETE-ticked row for a
persisted pair deletes it on save; the same for a never-saved blank row is simply an empty extra
form, which the formset ignores.

**Removing the row that carries the correct-answer marker.** Choice's `is_correct` marker is
per-row (`_edit_choicequestion.html:26-28`). Nothing is re-marked automatically; the existing
server-side validation prompts on save. This mirrors module 2's identical decision for switchgate's
radio, and is a deliberate choice rather than an oversight: silently promoting another row to
"correct" is a worse failure than an explicit prompt.

**`[hidden]` needs an explicit CSS guard.** `row.hidden = true` alone will *not* hide these rows.
Every target row class sets an author-level `display` at equal specificity, which beats the UA
`[hidden] { display: none }` rule. The selectors live in **two different stylesheets**, so the rule
is split accordingly:

- `courses/static/courses/css/editor.css` — `.pair-row[hidden]`, `.choice-row[hidden]`
  (classes defined at `:141`, `:157`)
- `courses/static/courses/css/courses.css` — `.stepper-row[hidden]`, `.markdone-row[hidden]`
  (classes defined at `:1990`, `:2048`)

each declaring `display: none`. The stylesheet-guard test reads **both** files and fails if either
rule is deleted. This repo has been bitten by this same gotcha at least five times —
`core/static/core/css/app.css` carries explicit guards with comments naming it at `:42`, `:185`,
`:546`, `:1009`, `:1191`.

**Disabled state.** When the guard in step 1 would fire — exactly one non-hidden row remains — the
remove buttons are set `disabled`, not left live to silently no-op. A control that does nothing when
clicked is the very defect this design exists to remove. The state is recomputed after every add,
every remove, and every fragment swap.

**The DELETE checkbox stays** (progressive enhancement). The existing
`<label class="…__del">{{ f.DELETE }} Remove</label>` remains in the DOM as the state carrier and as
the **no-JS affordance**. The init pass hides the checkbox label — so JS authors do not see two
remove controls, one of which leaves the row on screen — and reveals the `data-fsrow-remove` button,
which the template renders with a bare `hidden` attribute so it never appears without JS.

**Remove-button affordance.** The button carries a translated `aria-label` and `title`. If it renders
as a compact control rather than a text label, its glyph must be a monochrome SVG using
`currentColor`, per the repo's icon convention — never an emoji or a bare `×` character.

**Init pass.** `window.libliInitFormsetRows(root)`, called from `editor.js` after each fragment swap
alongside the existing init calls, performs three idempotent jobs:

1. swap the checkbox label for the button (above);
2. **hide every row whose `DELETE` checkbox is already ticked** — this reconciles the 422 re-render
   (see Error handling);
3. recompute the disabled state of the remove buttons.

**Consumers.** Match pairs (add + remove; gains its first `<template>`), stepper and checklist
(retrofitted — `stepper_editor.js` and `markdone_editor.js` are retired), choice (remove only).

**Interaction with `addChoiceRow`.** `editor.js:419-443` clones `rows[rows.length - 1]`. Once a row
can be hidden, cloning the last row can clone a *hidden* one, producing a new row the author cannot
see while `TOTAL_FORMS` still increments. `addChoiceRow` must therefore:

- clone the last **non-hidden** row;
- strip `hidden`, untick `DELETE`, and remove `choice-row--del` from the clone;
- clear `disabled` on the clone's remove button; and
- call `window.libliInitFormsetRows(...)` on the enclosing wrapper afterwards, so the disabled state
  is recomputed. `addChoiceRow` lives in `editor.js`, not in module 1, so module 1's own
  recompute-after-add does not cover it — without this call an author who removes down to one choice
  and then adds a row gets a second row whose remove button is still disabled, and `cloneNode(true)`
  copies that `disabled` attribute onto the clone as well.

**Wiring.** `editor.html` loads every editor module by an explicit `<script src=… defer>` line
(`:259-289`); there is no glob. It must gain tags for **both** new modules, with the customary
explanatory `{% comment %}`, and lose the two retired ones (`:269`, `:277`). `editor.js:125-126`
loses the two retired `libliInit*` calls and gains `libliInitFormsetRows` and
`libliInitSwitchGateEditor`.

### Module 2 — `courses/static/courses/js/switchgate_editor.js` (positional option list)

**Filename caution.** The directory already holds `switchgate.js` (the student runtime) and
`switchgrid_editor.js` (a *different* element, one letter apart). The name follows the repo's
`X.js` / `X_editor.js` convention and is kept, but the file must open with a header comment naming
both siblings so it is not mis-edited.

Switchgate is **not** a formset. Its options are repeated `name="option"` inputs read positionally
via `data.getlist("option")` (`element_forms.py:386`), and the correct answer is a radio whose value
is the option's **index** (`_edit_switchgate.html:15`, `value="{{ forloop.counter0 }}"`).

**Markup contract.** `_edit_switchgate.html:12-21` currently has zero data hooks and must gain them.
As in module 1, the delegation root is a **wrapper enclosing the option list, the add button and the
`<template>`** — putting it on `.el-editor__options` (the list) alone would leave the add button
outside it and `closest()` would return `null`, reproducing exactly the dead-button defect this
design exists to fix. The wrapper is `display: contents` for the same layout reason as module 1.

| Attribute | On | Meaning |
|---|---|---|
| `data-sgate` | **wrapper** (`display: contents`) enclosing list + button + template | Delegation root |
| `data-sgate-confirm` | wrapper | Translated confirm string |
| `data-sgate-list` | `.el-editor__options` | Where new rows are appended |
| `data-sgate-row` | `.el-editor__option-row` | One option |
| `data-sgate-add` | button | Add control |
| `data-sgate-template` | `<template>` inside the wrapper | Blank row blueprint |
| `data-sgate-remove` | button inside a row | Remove control |

**The blueprint row is a verbatim copy of the loop body** with only tokens substituted. Switchgate
is not a formset, so there is no `empty_form` to guarantee parity — this is the hand-written
blueprint module 1 avoids, and the asymmetry is unavoidable. To bound the drift risk, the blueprint
must preserve every attribute the rendered row carries: the radio's `name="answer"` and
`aria-label="{% trans 'Correct option' %}"`, and the text input's `name="option"` and
`class="rte-source"` (`_edit_switchgate.html:15-18`).

**Two distinct tokens are required**, because the rendered row is 0-based in one place and 1-based
in the other (`value="{{ forloop.counter0 }}"` at `:15`, `placeholder="… {{ forloop.counter }}"` at
`:18`):

- `__index__` → the 0-based radio `value`;
- `__pos__` → `index + 1`, the placeholder's number.

Substituting one token into both would render "Option 0, Option 1, …". The renumber pass writes
both.

**Add.** Append a row from the template with the next index, blank text, radio unchecked; recompute
the disabled state; then `libliAlignTopInPane` + `focus({ preventScroll: true })` on the row's text
input, as in module 1.

**Remove.**

1. **Guard:** when exactly two rows remain, the remove buttons are `disabled` (see "Minimum guard").
2. **Confirm:** prompt only when the row's `input[type="text"]` has a non-empty `.value.trim()`.
   Blank rows are removed with no prompt — essential, because the padded render is mostly blank rows
   and closing an *interior blank* is the headline use case; prompting on every blank removal would
   make the fix worse than the defect.
3. **Detach and renumber:** see below.

Unlike module 1, the row **must be detached from the DOM**. Hiding is not sufficient and would
actively corrupt the data: a hidden input still submits, and `clean()` (`element_forms.py:421-428`)
drops only *trailing* blanks and explicitly **rejects interior blanks** with "Options cannot be
empty." After detaching, **renumber every remaining row** — the radio's `value` (`__index__`) *and*
the placeholder's number (`__pos__`), or the surviving placeholders read "Option 1, Option 3,
Option 4".

If the removed row was the checked one, **leave nothing checked.** The existing validation
("Select the correct option.", `element_forms.py:435-438`) then prompts the author on save.

**Minimum guard.** The guard counts **DOM rows, not filled values** — a value-based guard would fire
on a legitimately blank-but-in-progress list, and the padded render always starts with blanks. When
exactly two rows remain, the remove buttons are `disabled`. The stricter "at least two *non-empty*
options" rule stays server-side, where `_MIN_OPTIONS` (`element_forms.py:427`) already enforces it.

**Init pass.** `window.libliInitSwitchGateEditor(root)`, called from `editor.js` after each fragment
swap, performs three idempotent jobs, mirroring module 1:

1. reveal the JS-only add and remove controls (which render `hidden`, per below);
2. recompute the two-row disabled state;
3. renumber the rows, so a re-swap or a 422 re-render always lands on contiguous indices.

**No-JS story.** Both switchgate controls render with a bare `hidden` attribute and are revealed by
the init pass. Without this a no-JS author would be shown a brand-new Add button and per-row Remove
buttons with no server-side handler behind either — clicking them would do nothing, which is
precisely the defect Purpose condemns.

**CSS scoping.** `.el-editor__option-row` is **shared**: defined at `core/static/core/css/app.css:1223`
and re-styled under `.el-editor--switchgrid` at `:1437-1445`. Every new rule for the switchgate
add/remove controls must be scoped under `.el-editor--switchgate`, or it leaks into the switch-grid
cycler rows.

### No server changes

Both mechanics emit POST payloads the existing parsers already accept:

- module 1 posts a well-formed formset with a possibly larger `TOTAL_FORMS` and some `DELETE` flags —
  exactly what `build_matchpair_formset` / `build_stepper_formset` / `build_markdone_formset` /
  `build_choice_formset` already handle;
- module 2 posts a shorter `option` list with a consistent `answer` index — exactly what
  `SwitchGateElementForm.clean()` already handles.

There is **no model change, no migration, and no `FORMAT_VERSION` bump.** Template, CSS and
JavaScript changes are not "server changes" in this sense; no Python is modified except the test
files named below.

## Data flow

**Adding a match pair.** Click `data-fsrows-add` → read `pairs-TOTAL_FORMS` (say `3`) → clone the
blueprint → `pairs-__prefix__-left` becomes `pairs-3-left` → append → `TOTAL_FORMS = 4` → recompute
disabled state → align + focus. On Save the POST carries four forms; `formset.save()` creates the new
`MatchPair` rows. Nothing reached the server before Save.

**Removing a saved pair.** Click `data-fsrow-remove` on row 1 → row has text → confirm → tick
`pairs-1-DELETE`, dispatch a bubbling `change`, hide the row. POST still carries `pairs-1-id` and
`pairs-1-DELETE=on`; `formset.save()` deletes that `MatchPair`. `TOTAL_FORMS` is unchanged.

**Removing a switchgate option.** Click remove on the middle of three filled options → confirm →
detach the row → the two survivors are renumbered to `0`/`1` (radio value) and "Option 1"/"Option 2"
(placeholder). `getlist("option")` now returns two values in DOM order and `answer` indexes
correctly into them.

**Switchgate removals of blank rows do not persist — by design.** `option_rows()` re-pads to
`max(_MIN_ROWS, len(opts) + 1)` on every unbound render (`element_forms.py:402`, `_MIN_ROWS = 6`).
So removing a blank padding row, saving, and re-opening brings the blanks back. This is correct:
blanks are not data, and the padding exists so an author always has somewhere to type. What the
remove control buys within a session is real — it is the only way to close an **interior** blank and
get past "Options cannot be empty." Removals that drop a *filled* option persist normally.

## Error handling

**The 422 re-render.** When a save fails validation, the server re-renders the form from the POST
(`courses/views_manage.py:2257-2278`). Rows the author removed come back **visible with their DELETE
box ticked**, because the server knows nothing about the client-side `row.hidden`.

The fix is client-side, **not** a template rule keyed on `f.DELETE.value()`. The init pass hides
every row whose DELETE is already ticked (job 2). Keying it in the template instead was considered
and rejected: it would hide the row for **no-JS authors too**, and since the DELETE checkbox lives
*inside* the row it hides, a no-JS author who ticked a box and then hit any unrelated validation
error could never untick it — a real capability regression.

Switchgate needs no equivalent: `option_rows()` prefers the posted options on a bound form
(`element_forms.py:393-398`), so a removed option is already absent from the re-render and the
posted `answer` index is preserved.

**No undo, and why.** A removed row cannot be restored within the session (its checkbox is inside
the hidden row). This is accepted rather than solved: non-empty rows are confirm-guarded, so the
only un-prompted removals discard nothing, and the editor's Cancel discards the whole session. An
"N rows removed — restore" affordance is deliberate future scope.

**What this trades away.** `editor.js:492` currently documents the DELETE tick as "Reversible: untick
to restore the row." For **no-JS authors that stays exactly true** — the checkbox is visible and
behaves as it does today. **JS authors trade it**: the reversible tick becomes an irreversible,
confirm-guarded removal. That is the intended bargain (a tick that leaves the row on screen is the
reported defect), but it is a real change, not a pure addition, and the now-stale comment at
`editor.js:492` must be amended in the same change.

**Editor fragment swaps.** Delegated listeners survive swaps automatically; the init passes are
re-run by `editor.js` for the progressive-enhancement reveal and the DELETE reconciliation, exactly
as `libliInitSwitchGridEditors` is today.

**Confirm dialogs.** `window.confirm` with the translated string read from a data attribute, matching
`tabs_editor.js:146` and the existing precedent for translated strings on a row container
(`_edit_choicequestion.html:19-20`).

**Degradation without JavaScript.** In the formset editors the DELETE checkboxes stay visible and
functional and the remove buttons stay `hidden`. In switchgate both new controls stay `hidden`. The
server still renders `extra` blank rows and switchgate's six padded rows. A no-JS author retains
exactly today's capability in every editor touched.

## Testing

**Existing tests this change breaks — must be updated, not deleted.**

- `tests/test_stepper_editor_assets.py` — asserts `stepper_editor.js` contains
  `window.libliInitStepperEditor` (`:14`), `steps-TOTAL_FORMS` (`:15`) and `__prefix__` (`:16`), and
  that the editor page references the file (`:28`). Retarget to `formset_rows.js` /
  `libliInitFormsetRows`. The `steps-TOTAL_FORMS` assertion must be **dropped** — it is a
  prefix-specific artefact of the retired module and a prefix-agnostic helper can never contain that
  literal.
- `tests/test_editor_stepper_add.py:27-28` — asserts `data-stepper-editor` and `data-stepper-row`
  appear in the response. Retarget to the new attribute names.
- `tests/test_editor_js_scroll_invariants.py:24-35` — its hardcoded `PANE_RESIDENT` roster reads each
  file from disk and asserts existence, so it *raises* on the two removed files. Drop them, add
  `formset_rows.js` and `switchgate_editor.js`, and **extend the test with a second regex** flagging
  a bare `.focus(` (no `preventScroll`) in any pane-resident module. `stepper_editor.js:20` violates
  that rule today, which is why the extension is part of this change rather than a follow-up.
- `tests/test_e2e_questions.py:310-317` — does
  `row2.locator("input[name='choices-2-DELETE']").check()`. That checkbox sits **inside** the
  `<label class="choice-row__del">` the init pass hides, so under JS — the only mode Playwright runs
  in — `.check()` fails actionability. Rewrite it to click `data-fsrow-remove` instead, then assert
  both that `choice-row--del` is applied (proving the bubbling `change` dispatch works) and that the
  row is no longer visible.

**New form-level tests (pytest).**

- A match POST with **more rows than the server rendered** — the path that is impossible to reach
  today — saves all of them. This is the direct regression test for the reported defect.
- A ticked `DELETE` on a persisted pair deletes exactly that pair and leaves the others intact.
- A switchgate POST with a middle option removed and `answer` renumbered stores the intended option
  as correct.
- A stylesheet guard reading **both** `editor.css` and `courses.css`, asserting the four
  `[hidden] { display: none }` rules exist, structured so deleting either rule fails the test.
- An asset test asserting `editor.html` references both new modules.

**Retrofit no-regression tests (the riskiest part of this change).** Stepper and checklist are
*working* editors being rewired onto a new module; nothing above would catch a regression there. Add,
for each: add a row past `extra`, fill it, save, re-open, assert it persisted; and remove a persisted
row and assert it is gone. These are a **GREEN-on-master, GREEN-after** pair — not falsifiable
against the current build, which is the point.

**New end-to-end tests (Playwright).**

- Open a **saved** match element, click `Add pair` three times **with no intervening save**, fill all
  three, save, re-open, and assert three new pairs persisted.
- Remove a filled pair through the confirm dialog; assert it is gone after save. *(Needs a `dialog`
  handler — the row is non-empty.)*
- **The 422 reconciliation**, which is the subtlest mechanism in the design and would otherwise ship
  untested: remove a row, trigger a validation failure on save, assert the removed row comes back
  **not visible** with its DELETE still ticked, then fix the error and assert the removal persisted.
- Switchgate: add an option beyond the padded blanks; remove a middle *filled* option and assert the
  correct answer still points at the intended option **text** (not index) after save *(needs a
  `dialog` handler)*; and remove an *interior blank* row and assert the save now succeeds where it
  previously failed with "Options cannot be empty." *(no `dialog` handler — a blank row is removed
  without a prompt)*.

**Falsification.** Per this repo's standing rule, every *new* test above must be shown **RED** before
the fix, with the mutant chosen from the failure mode rather than the assertion. The match "add three
pairs" test is RED on `master` by construction — the button does nothing. The retrofit tests are the
stated exception.

**Three known traps that make a correct build look broken:**

- Playwright **auto-dismisses** `confirm`. A removal test without an explicit `dialog` handler takes
  the *cancel* path, so the row is never removed and the test fails against a correct
  implementation. The bullets above state which tests need one.
- A hidden row is still **matched by `locator.count()`**; assert on visibility, not on count, when
  checking that a row disappeared.
- The test-DB container must be started before any pytest run in this repo, or the suite appears to
  hang for ~4m21s.

## Delivery

New translated strings ship in this change: a confirm string per editor, the switchgate add label,
and the remove buttons' labels/`aria-label`s. Delivery therefore includes
`makemessages -l pl -l en --no-obsolete` plus `compilemessages`, with an explicit Polish translation
for each new string and **every fuzzy flag cleared** — this repo has a documented trap where
`makemessages` fuzzy-prefills a *wrong* translation. Extend the existing i18n catalog guard (e.g.
`tests/test_i18n_stepper.py`) to cover the new strings. Run `uv run ruff format .` last, after every
other edit.
