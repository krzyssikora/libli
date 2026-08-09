# Instant add/remove of repeatable rows in the element editor

## Purpose

An author editing a **match-pairs** element cannot add more than two pairs without saving the
element and re-opening it. The `＋ Add pair` button that promises otherwise does nothing at all. A
prospective customer trying the authoring flow found this badly non-intuitive, and it is the kind of
defect that reads as "the editor is broken" rather than "the editor is limited."

This design makes repeatable rows behave the way an author expects: **rows appear and disappear
immediately, and nothing is persisted until Save.** It fixes the two element types that genuinely
cannot do this today, and removes a smaller but related surprise — a "Remove" control that leaves
the row sitting on screen — from the editors that share it.

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

**2. "Remove" does not remove.**
In the four inline-formset editors — match (`_edit_matchpairquestion.html:18`), choice
(`_edit_choicequestion.html:38`), stepper (`_edit_stepper.html:21`) and checklist
(`_edit_markdone.html:21`) — "Remove" is the raw Django `DELETE` checkbox. Ticking it leaves the row
fully visible and unchanged until Save. The author gets no confirmation that anything happened.

**3. Choose & confirm (switchgate) has no add/remove control at all.**
`_edit_switchgate.html:11-21` renders a fixed list of option rows padded server-side to
`max(_MIN_ROWS, len(options) + 1)` (`element_forms.py:402`). There is no add button and no remove
control. Exceeding the padded blanks requires Save-and-reopen.

## Scope

**In scope**

| Element | Add | Remove |
|---|---|---|
| Match pairs | new (button exists, needs a handler + a `<template>`) | new |
| Choose & confirm (switchgate) | new | new |
| Choice question | *unchanged* | new |
| Stepper | retrofit onto the shared helper | new |
| Checklist (mark-done) | retrofit onto the shared helper | new |

**Out of scope, deliberately**

- **Two-column.** Its column count is a genuine structural "Number of columns" field applied
  server-side, not a row list. Different problem, different fix.
- **Choice's add path.** `addChoiceRow` (`courses/static/courses/js/editor.js:419-443`) uses the
  older clone-the-last-rendered-row idiom and renumbers with `/([-_])\d+([-_])/`. It works today,
  and its template has no `__prefix__` scaffold to convert to — changing it is regression risk with
  no user-visible gain. Choice gains instant remove only.
- **Any server-side change.** See "No server changes" below.
- Editors that already support client-side add/remove: matrix grid, multi-select grid, tabs,
  gallery, table, fill-in table, switch grid, drag-to-image.

## Architecture

Two new JavaScript modules. They are deliberately **not** unified: the two element families store
their rows differently, and a single helper would be one function with two disjoint branches — more
code and less clarity than two honest files.

### Module 1 — `courses/static/courses/js/formset_rows.js` (Django inline formsets)

A generic add/remove helper for any Django inline formset, driven entirely by data attributes so no
per-element JavaScript is needed. It uses a **single document-level delegated listener** (the idiom
`switchgrid_editor.js:61` already uses), which means it needs no `initOne`, no ready-flag, and no
re-initialisation after an editor fragment swap.

**Markup contract**

| Attribute | On | Meaning |
|---|---|---|
| `data-fsrows` | row container | Value is the formset prefix (`pairs`, `steps`, `items`, `choices`) |
| `data-fsrows-confirm` | row container | Translated confirm string for a non-empty removal |
| `data-fsrow` | a row | Marks one form's row |
| `data-fsrows-add` | button | Add control (scoped to the nearest container) |
| `data-fsrows-template` | `<template>` | Blueprint row using `__prefix__` |
| `data-fsrow-remove` | button inside a row | Remove control |

**Add.** Read `TOTAL_FORMS` for the prefix, clone the template, replace every `__prefix__` with that
index, append the row, increment `TOTAL_FORMS`, focus the row's first text input. This is
`stepper_editor.js:11-21` generalised over the prefix.

**Remove.** If the row contains any non-empty text input, `window.confirm(...)` first using the
container's `data-fsrows-confirm` string; an empty row is removed with no prompt. Then:

- tick the row's `DELETE` checkbox, and
- set `row.hidden = true`.

**The row is never detached from the DOM and `TOTAL_FORMS` is never decremented.** Django validates
forms `0 … TOTAL_FORMS-1`; punching a gap in the indices means a persisted row's `id` field vanishes
from the POST, and the formset then either mis-saves or rejects the submission. Hiding keeps the
indices contiguous while being visually identical to removal. A hidden, DELETE-ticked row for a
persisted pair deletes it on save; the same for a never-saved blank row is simply an empty extra
form, which the formset ignores.

**Consumers.** Match pairs (add + remove; gains its first `<template>`), stepper and checklist
(retrofitted — `stepper_editor.js` and `markdone_editor.js` are retired), choice (remove only,
keeping `addChoiceRow`).

Retiring the two per-editor modules also removes their script tags
(`templates/courses/manage/editor/editor.html:269,277`) and their post-swap re-init calls
(`courses/static/courses/js/editor.js:125-126`), because delegation makes both unnecessary.

### Module 2 — `courses/static/courses/js/switchgate_editor.js` (positional option list)

Switchgate is **not** a formset. Its options are repeated `name="option"` inputs read positionally
via `data.getlist("option")` (`element_forms.py:386`), and the correct answer is a radio whose value
is the option's **index** (`_edit_switchgate.html:15`, `value="{{ forloop.counter0 }}"`).

**Add.** Append a row from a `<template>` with the next index, blank text, radio unchecked; focus
the text input.

**Remove.** Unlike module 1, the row **must be detached from the DOM**. Hiding is not sufficient and
would actively corrupt the data: a hidden input still submits, and `clean()`
(`element_forms.py:421-428`) drops only *trailing* blanks and explicitly **rejects interior blanks**
with "Options cannot be empty." After detaching, **renumber every remaining radio's `value` to its
new position**, or the correct answer silently points at the wrong option.

If the removed row was the checked one, **leave nothing checked.** The existing validation
("Select the correct option.", `element_forms.py:435-438`) then prompts the author on save. Silently
reassigning which answer is correct would be a worse failure than an explicit prompt.

**Minimum guard.** Refuse to remove below 2 options, mirroring `_MIN_OPTIONS`
(`element_forms.py:427`). The add/remove controls follow the same confirm-if-non-empty rule as
module 1.

### No server changes

Both mechanics emit POST payloads the existing parsers already accept:

- module 1 posts a well-formed formset with a possibly larger `TOTAL_FORMS` and some `DELETE` flags —
  exactly what `build_matchpair_formset` / `build_stepper_formset` / `build_markdone_formset` /
  `build_choice_formset` already handle;
- module 2 posts a shorter `option` list with a consistent `answer` index — exactly what
  `SwitchGateElementForm.clean()` already handles.

There is **no model change, no migration, and no `FORMAT_VERSION` bump.**

## Data flow

**Adding a match pair.** Click `data-fsrows-add` → read `pairs-TOTAL_FORMS` (say `3`) → clone
`<template data-fsrows-template>` → `pairs-__prefix__-left` becomes `pairs-3-left` → append →
`TOTAL_FORMS = 4` → focus. On Save the POST carries four forms; `formset.save()` creates the new
`MatchPair` rows. Nothing reached the server before Save.

**Removing a saved pair.** Click `data-fsrow-remove` on row 1 → row has text → confirm → tick
`pairs-1-DELETE`, hide the row. POST still carries `pairs-1-id` and `pairs-1-DELETE=on`;
`formset.save()` deletes that `MatchPair`. `TOTAL_FORMS` is unchanged throughout.

**Removing a switchgate option.** Click remove on the middle of three options → confirm → detach the
row → the two survivors' radios are renumbered to `0` and `1`. `getlist("option")` now returns two
values in DOM order and `answer` indexes correctly into them.

## Error handling

**The 422 re-render.** When a save fails validation, the server re-renders the form from the POST
(`courses/views_manage.py:2257-2278`). It knows nothing about the client-side `row.hidden`, so a row
the author removed **reappears fully visible with its DELETE box ticked** — the author sees a row
they deleted come back. The row templates must therefore render `hidden` when `f.DELETE.value()` is
true, so the server's re-render reproduces the client's state.

Switchgate needs no equivalent fix: `option_rows()` prefers the posted options on a bound form
(`element_forms.py:393-398`), so a removed option is already absent from the re-render, and the
posted `answer` index is preserved.

**Editor fragment swaps.** Both modules delegate from `document`, so a swapped-in fragment is live
immediately with no re-init hook. This is also why the retired modules' `libliInit*` calls can be
deleted rather than renamed.

**Confirm dialogs.** `window.confirm` with the translated string read from a data attribute, matching
`tabs_editor.js:146` (`window.confirm(label(editor, "confirm", "Delete this tab?"))`) and the
existing precedent for passing translated strings via data attributes on a row container
(`_edit_choicequestion.html:19-20`). Keeping the string in the template keeps it in the `.po`
catalogs.

**Degradation without JavaScript.** Unchanged from today: the DELETE checkboxes still work, and the
server still renders `extra` blank rows, so a no-JS author retains exactly the current (limited)
capability. No existing capability is removed.

## Testing

**Form-level (pytest).**

- A match POST with **more rows than the server rendered** — the path that is impossible to reach
  today — saves all of them. This is the direct regression test for the reported defect.
- A ticked `DELETE` on a persisted pair deletes exactly that pair and leaves the others intact.
- A switchgate POST with a middle option removed and `answer` renumbered stores the intended option
  as correct.
- A 422 re-render of a formset with a DELETE-ticked row renders that row `hidden`.

**End-to-end (Playwright).**

- Open a **saved** match element, click `Add pair` three times **with no intervening save**, fill all
  three, save, re-open, and assert three new pairs persisted.
- Remove a filled pair through the confirm dialog; assert it is gone after save.
- Switchgate: add an option beyond the padded blanks; separately, remove a middle option and assert
  the correct answer still points at the intended option **text** (not index) after save.

**Falsification.** Per this repo's standing rule, every test must be shown **RED** before the fix,
with the mutant chosen from the failure mode rather than the assertion. The match "add three pairs"
test is RED on `master` by construction — the button does nothing.

**Two known traps that make a correct build look broken:**

- Playwright **auto-dismisses** `confirm`. A removal test without an explicit `dialog` handler takes
  the *cancel* path, so the row is never removed and the test fails against a correct
  implementation.
- The test-DB container must be started before any pytest run in this repo, or the suite appears to
  hang for ~4m21s.
