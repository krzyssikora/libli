# "W skrócie" summary callout kind

**Status:** approved design (brainstorming 2026-10-03; D7 re-decided by the owner the same day).
**Template:** this follows the playbook of the Task-kind addition,
`docs/superpowers/specs/2026-08-08-callout-task-kind-design.md`. Its line citations are
stale, but its section list and its test table are the checklist.

## 1. Purpose

mat-pp has 34 units titled "Podsumowanie" / "… – podsumowanie". They recap many earlier
units, and today they read as walls of text. Some are a single text element holding every
topic as `h3` + nested bullets. Others are long runs of text and image elements (21 + 10,
or 53 + 25). Everything in a summary is equally important, so emphasis fails: a page of
"Important" callouts is heavy, and when everything is highlighted nothing stands out. The
missing ingredient is **chunking**, not emphasis.

This feature adds a visually **quiet** callout kind, "Key facts" / **"W skrócie"**. An
author puts one card per topic in a summary unit, with the topic name as its heading, and
the page reads as a scannable cheat sheet.

Converting the 34 units is the owner's authoring work and is **out of scope**.

## 2. Owner decisions (VERBATIM — review rounds must not reverse these)

| # | Decision |
|---|---|
| D1 | Cheat-sheet (scan), not self-test: everything visible. |
| D2 | New `CalloutElement` kind, value `"summary"`, label "Key facts" / Polish "W skrócie" (also the empty-heading fallback). |
| D3 | Layout: cards stack full width; side-by-side only by the author putting cards in the existing `TwoColumnElement`. NO auto-grid, no renderer grouping of adjacent elements. |
| D4 | Visual = option B′ "flat card": white surface (no accent tint), hairline border all round (`var(--border-subtle)`), 3px muted slate TOP bar (light `#4b6b8a`; a dark-theme value and a print rule like the other five kinds) INSTEAD of the left spine, NO shadow, NO icon chip, NO uppercase eyebrow. The heading is a real heading element in normal title case (the topic name). Rejected: hairline-only (C), because opened spoilers (`.spoiler__children`) and before/after panels (`.ba__panel`) already use a 2px left rule and would be confused with it. |
| D5 | Summary cards are NEVER numbered. `courses/numbering.py` `callout_numbers` skips `kind == "summary"`, so the shared unit-wide counter is not consumed. `CalloutElement.save()` forces `numbered=False` for summary. `KIND_DEFAULT_NUMBERED` gains `summary: False`. The editor hides the "numbered" checkbox for this kind and the server ignores it. |
| D6 | The back-link to the source lesson is an ordinary internal content link the author types in the card body. NO new "related lesson" field (deferred). |
| D7 | **`FORMAT_VERSION` is NOT bumped; it stays at 16** (owner, 2026-10-03, "yes, go with b"). This reverses an earlier approval of a bump, which rested on a false premise. It follows the Task-kind D2 precedent and the rule in `test_format_version_is_unchanged`: the version rises only when an EXISTING payload shape changes. Export never validates kinds, so exporting always works. An instance running a build from before this feature refuses an archive that contains a summary card, with "Element 'x' has an unknown callout kind". Every other archive still imports. There is one course (mat-pp), authored on libli.pl, so the sequence is: deploy, then author cards. |

## 3. Architecture / components

### 3.1 Model — `courses/models.py`

- `CalloutElement.Kind` gains `SUMMARY = "summary", _("Key facts")`, appended after `TASK`.
  `kind` is `CharField(max_length=12)`, so the value fits.
- The class docstring's kind list "(Example/Note/Tip/Important/Task)" gains "Key facts".
- `save()`: after the existing unknown-kind coercion, `if self.kind == self.Kind.SUMMARY:
  self.numbered = False` (D5). This is the single write-side guard. The editor form, the
  transfer importer, the admin and the seeders all go through it.
- `KIND_DEFAULT_NUMBERED` gains `CalloutElement.Kind.SUMMARY.value: False`.
  `KIND_DEFAULT_HEADING` is derived from the enum and needs no edit.
- Migration `0068_…`: a state-only `AlterField` on `CalloutElement.kind` for the new
  choices. No data step, so rollback is trivial. Check it is the graph head; see memory
  "migration restore must target graph head".
- Do NOT touch migration `0060` or `test_callout_numbered_migration.py`. They are a frozen
  historical record of five kinds.

### 3.2 Numbering — `courses/numbering.py`

In `walk()`, the numbered branch becomes `isinstance(obj, CalloutElement) and obj.numbered
and obj.kind != CalloutElement.Kind.SUMMARY` (D5). This is a belt-and-braces guard on the
read side. `save()` already keeps `numbered` False, but a row written by `QuerySet.update()`
or a raw migration bypasses `save()`, and the shared counter must never be consumed by a
card. The module docstring gets one sentence on why.

### 3.3 Rendering — `templates/courses/elements/calloutelement.html`

Today the header is `{% include "_callout_icon.html" %}` plus `<span
class="callout__heading">`, an uppercase eyebrow showing "KIND n. heading". For
`el.kind == "summary"` the header becomes **only**:

```html
<h3 class="callout__title">{{ el.display_heading }}</h3>
```

- There is no icon include, no number and no eyebrow span. `display_heading` already falls
  back to the kind label, so an empty heading renders "W skrócie" (D2).
- **Why h3:** the unit title is `<h1 class="lesson-unit__title">`. The summary units' topics
  are `<h3>` in their text bodies today, so a card replacing an `h3` + list keeps the same
  outline level. The only other heading in an element template, the tabs panel label, is
  also h3.
- **Exact structure.** In the summary branch, the h3 **replaces** the whole `<div
  class="callout__header">` wrapper; it is not placed inside it. The h3 is the first child
  of the `<aside>`. This avoids the wrapper's flex layout and its `margin-bottom` stacking
  with the h3's own margin. T5 asserts that the summary output contains no
  `callout__header`.
- The heading may contain inline KaTeX (`\(…\)`). The selector list in
  `courses/static/courses/js/math.js` `renderInlineText` (`.callout__heading`) does not
  match the new class. **Add `.callout__title` to that list.** Do not reuse
  `callout__heading` on the h3: it would inherit the uppercase eyebrow styling and
  contradict D4. The heading test must assert that KaTeX output lands inside the h3; an
  e2e or JS-level check is acceptable here because math.js runs client-side.
- The other kinds' markup must stay **semantically identical**: the summary path is a
  separate `{% if %}` branch, and the existing branch's tags are untouched. Whitespace may
  shift because of the new `{% if %}`, so T6 compares after normalising whitespace.
- The `<aside class="callout callout--summary">` wrapper, the body and the `.callout__children`
  block are shared unchanged, so text, images, maths, nested questions and reveal scoping
  all work as they do in every callout.
- `_callout_icon.html` is not edited. The summary branch never includes it. Its `{% else
  %}` book icon therefore stays the example icon only. Add a comment in the partial saying
  summary deliberately has no icon.

### 3.4 CSS — `courses/static/courses/css/courses.css`

Place this next to the per-kind accent rules, following their one-line aligned style:

- Light: `.callout--summary { --callout-accent: #4b6b8a; }`. Dark: `[data-theme="dark"]
  .callout--summary { --callout-accent: <light-on-dark slate> }`. The implementer picks a
  dark value in the family of the other dark accents, for example around `#9db4cb`.
  **Acceptance:** the top bar is the kind's only visual identity, so as non-text graphics
  both accents must reach **≥ 3:1** against `--surface-raised` in their own theme (WCAG
  1.4.11). This is asserted by a test (T9b), not only judged from a screenshot.
- Surface overrides for `.callout--summary`:
  - `background: var(--surface-raised)`: no tint (D4);
  - `border-left: 1px solid var(--border-subtle)`: cancels the 3px spine;
  - `border-top: 3px solid var(--callout-accent)`: the top bar.
  - It inherits `border`, `border-radius`, `padding` and `margin` from `.callout`. No shadow.
- `.callout__title`: normal case, no letter-spacing, `color: var(--text-primary)`, about
  `1.05rem` / 700, `margin: 0 0 var(--space-3)`, with an explicit `line-height` (about
  1.3), and `letter-spacing: normal`. `.callout__body`'s first-child margin reset already
  handles what follows. `reset.css` zeroes all margins but gives headings `line-height:
  1.15` and `letter-spacing: var(--heading-letter-spacing)`. Override both explicitly, and
  set the bottom margin explicitly for the gap. Add `.callout__title:last-child {
  margin-bottom: 0; }`, so a card that has a heading but no body or children gets no extra
  bottom space: `.callout`'s padding blocks margin collapsing.
- `.callout__title .katex { font-size: 1em; font-weight: inherit; color: inherit; }`.
  Unlike the eyebrow's reset, there is no `text-transform` to undo, but KaTeX's default
  1.21em would make inline maths visibly larger than the heading text.
- The corner radius stays, and the bar is the `border-top` above; there is no
  pseudo-element fallback. The 3px top border meets the 1px sides on the rounded corner.
  The screenshot DoD records how that looks. If it reads badly, report it to the owner as
  a finding; do not improvise another drawing method. In particular, never put `overflow:
  hidden` on the card: callouts hold wide display maths and scroll boxes.
- The print block (`@media print`, "Print: callout accents") gains `[data-theme="dark"]
  .callout--summary { --callout-accent: #4b6b8a; }` in the exact whitespace format that
  `test_print_tokens_css.py` matches.
- The header comment's kind list "(Example / Note / Tip / Important / Task)" gains "Key
  facts". Cite selectors, never `courses.css:<line>`; `test_css_citations_are_durable`
  enforces this.
- Watch the memory "CSS comment `*/` eats the next rule". Run EVERY `test_*css*.py`.

### 3.5 Editor — `templates/courses/manage/editor/_edit_callout.html`

- The kind `<select>` loops over `form.fields.kind.choices`, so "W skrócie" appears
  automatically.
- The hand-written "Number this callout" checkbox block is wrapped in `{% if
  form.instance.kind != "summary" %}` (D5). It keys on the **saved** kind, not the bound
  POST value, so the checkbox and the restore rule below always read the same kind, even
  on a 422 re-render. No editor JS toggles fields by
  kind today, and none is added. Switching the select from Example to W skrócie leaves the
  checkbox visible until the next save. That is harmless, because `save()` forces False,
  and the re-render hides it. State this in the template comment so nobody "fixes" it
  with JS.
- **The reverse switch (summary → another kind) restores that kind's default.** When a
  summary card is edited, the checkbox is not rendered, so the POST carries no `numbered`.
  Without care, switching it to Example saves `numbered=False` and silently unnumbers it.
  `CalloutElementForm` records the instance's kind at `__init__` (`self._original_kind`).
  In `clean()`, it reads `new_kind = cleaned_data.get("kind")`. If that is absent, because
  the kind failed choice validation, it skips the restore so the normal field error
  returns a 422 rather than a `KeyError`. Otherwise, if the original kind was `summary`,
  the new kind is not, **and `"numbered" not in self.data`**, it sets
  `cleaned_data["numbered"] = KIND_DEFAULT_NUMBERED[new_kind]`. The restore only fills an
  absent key and never overrides a value that was sent. `clean()` calls `super().clean()`
  and returns `cleaned_data`. So Example → summary → Example ends numbered, and
  summary → Note ends unnumbered. This makes the form a second runtime reader of
  `KIND_DEFAULT_NUMBERED`. Three comments in `courses/models.py` go stale and must be
  updated: the map's "NOT read by CalloutElementForm"; its "Exactly ONE runtime caller";
  and the `numbered` field comment, which says the map "is consulted only by the backfill
  migration and by the importer's pre-v13 fallback".
- The "Leave blank to use the default for this kind" placeholder still holds.

### 3.6 Transfer — `courses/transfer/`

- `_val_callout` reads `CalloutElement.Kind.values` and `KIND_DEFAULT_NUMBERED`, so it
  accepts "summary" with no code change. An archive carrying `kind: "summary", numbered:
  true`, which this build can never export but a hand-edited archive could contain, imports
  as `numbered=False` through `save()`.
- **No version change (D7).** `courses/transfer/schema.py` and every test that pins 16 stay
  untouched. The PR body carries the operator note in the Task-kind D2 form: *deploy this
  build to libli.pl before authoring a W skrócie card; an archive that contains one is
  refused ("unknown callout kind") by any instance still running a build without the
  `SUMMARY` enum member. The gate is the deployed code, not the migration.*
- Note: the test D7 cites, `test_format_version_is_unchanged`, has since been renamed. Its
  rule now lives in `courses/tests/test_beforeafter_transfer.py::test_format_version_is_pinned`,
  whose docstring records the rename.

### 3.7 i18n and help docs

- `locale/pl/LC_MESSAGES/django.po`: `msgid "Key facts"` → `msgstr "W skrócie"`. The en
  catalog gets the same msgid with an empty msgstr (house convention,
  `test_i18n_po_health.py`). No existing msgid "Key facts" exists, so no `pgettext` is
  needed. Watch the makemessages fuzzy trap: clearing one means deleting both the `#,
  fuzzy` line and the `#|` line. Regenerate the `.mo`.
- New `tests/test_i18n_callout_summary.py`, sibling of `test_i18n_callout_task.py`, pins pl
  "W skrócie".
- `docs/help/course-admin/content-editors.md` and its `.pl.md`: add the kind to the inline
  list. In English: "Example, Note, Tip, Important, Task, or Key facts". In Polish, the
  existing "Ważne lub Zadanie" becomes "Ważne, Zadanie lub W skrócie". The sentence goes
  on to say "each with its own accent colour and icon" ("każdy z własnym kolorem akcentu i
  ikoną"), and the next clause describes the "Number this callout" checkbox. Neither holds
  for the new kind, so qualify both in both files: Key facts / W skrócie has no icon and
  is never numbered. Add one sentence saying it is meant for summary units, one card per
  topic, and can go two-up inside the container the docs already call **Columns**. In the
  `.pl.md`, use whatever Polish name that file already uses for this container; do not
  coin a new one. Keep the `{el:callout}` paragraph
  structure intact, because `core/help.py` and `test_help.py` parse it by position.

## 4. Data flow

Author picks "W skrócie" → `CalloutElementForm` (restores the per-kind `numbered` default when leaving summary, §3.5) → `save()` forces
`numbered=False` → the row is stored with `kind="summary"`. On a page request,
`callout_numbers(unit)` skips the card, so the numbers of the surrounding Examples and Tasks
are unaffected. `calloutelement.html` takes the summary branch and renders the h3 title,
the body and the children. CSS draws the flat card. Export: `_ser_callout` copies the
fields; the payload shape and the version (16) are unchanged (D7). Import:
`_val_callout` accepts the kind, then `save()` runs.

## 5. Error handling

- Unknown kind on save: existing coercion to example, unchanged.
- `numbered=True` arriving for a summary by form, archive, admin or shell: forced False in
  `save()`. If a row bypasses `save()`, numbering still skips it (§3.2).
- Older instance importing a card: refused at that element with "unknown callout kind"; other archives import (D7).
- Empty heading: falls back to "W skrócie".

## 6. Testing

Each test must be seen **RED against the named mutant** before being trusted (house rule).

| # | Test | Mutant it must catch |
|---|---|---|
| T1 | `test_callout_model`: `display_heading` of an empty-heading summary == "Key facts" (en) | drop the enum member / label |
| T2 | `test_callout_model`: save summary with `numbered=True` → reloads False | remove the `save()` force |
| T3 | `test_callout_numbering`: unit = Example, Summary(numbered forced True via `.update()`), Example → numbers {ex1:1, ex2:2}, summary absent | remove the `kind != SUMMARY` guard in `walk()` |
| T4 | `test_callout_numbering`: key-set test passes and `KIND_DEFAULT_NUMBERED["summary"] is False` | set it True |
| T5 | `test_callout_render`: summary renders `callout--summary` with an `<h3 class="callout__title">` holding the heading text as the aside's first child; **no** `callout__header`, **no** `callout__icon` and **no** `callout__heading` | render the summary through the generic branch |
| T5b | `courses/tests/test_math_selectors.py::test_every_typeset_region_is_in_the_selector_list`: add `.callout__title` to its region tuple. This is the deterministic catcher. An e2e check of KaTeX inside `h3.callout__title` is optional extra proof for the UI pass | drop `.callout__title` from the math.js selector list |
| T6 | in `courses/tests/test_callout_numbering_render.py`, using its `_rendered(el, join, numbers)` helper, because a bare unsaved `.render()` emits no number: for a numbered Example with a heading, whitespace-normalised output contains the exact header string: icon markup + `<span class="callout__heading">Example <span class="callout__number">1</span>. Heading</span>`; and no `callout__title` | an edit that leaks the summary branch into others or alters the generic header |
| T7 | `test_callout_authoring`: the picker contains `<option value="summary">Key facts</option>`; POST kind=summary round-trips; the rendered form for a summary has no `name="numbered"` input, and for an example it does | remove the `{% if %}` around the checkbox |
| T7b | `test_callout_authoring`: POST that switches a saved summary to `example` with no `numbered` key → saved `numbered=True`; to `note` → False; a saved summary switched to `example` **with** `numbered` sent unticked (key absent is the UI's only form; use a crafted POST with `numbered=""` / falsy where the form reads it as False) is not overridden when the key is present; editing an existing Example whose unticked box sends no `numbered` → stays False (the restore applies only when leaving summary); the rendered form for a saved example whose POST asked for summary and got a 422 still shows the checkbox | remove the `clean()` restore, apply it unconditionally, or drop the `not in self.data` check |
| T8 | `test_callout_transfer`: summary round-trip keeps kind/heading/body with `numbered` False; extend the existing validator-level pre-v13 test (`test_a_pre_v13_payload_imports_with_the_per_kind_default`) to assert `data["numbered"] is False` for summary **on the validated payload**, not the saved row, because `save()` would mask the mutant; the export manifest still says `format_version == 16` (D7) | drop the summary key from `KIND_DEFAULT_NUMBERED` |
| T9 | `test_callout_css`: anchored regexes for the light and dark summary accents; `.callout--summary` sets `border-top` with `--callout-accent`, `background: var(--surface-raised)`, and **no** `box-shadow` | delete or alter a rule |
| T9b | `tests/test_callout_css.py`: read both summary accents **from `courses.css`** with T9's anchored regexes, never as literals, and the grounds from `LIGHT_SURFACES`/`DARK_SURFACES` in `tests/test_text_colour_css.py` (import them and its `_ratio` helper, or whatever that module's contrast helper is named). Assert ≥ 3:1 for each theme | edit the dark accent in `courses.css` to a too-pale value |
| T10 | `test_print_tokens_css`: `CALLOUT_KINDS` += "summary" | omit the print rule |
| T11 | `test_text_colour_css`: add `callout-summary` = the plain `--surface-raised` value (light and dark) to `LIGHT_SURFACES`/`DARK_SURFACES`, which the enum-derived test requires. Do **NOT** add "summary" to the 6%-mix kinds tuple in `test_surface_literals_still_match_the_css`: that loop recomputes the ground as accent mixed into `--surface-raised`, which can never equal an untinted ground. Pin the untinted ground through T9's `background: var(--surface-raised)` assertion instead. Add `callout-summary` to `BORDER_GROUNDS` in `test_border_contrast_css`. Update the prose counts | the enum-derived test fails until added; T9 catches a tint added later |
| T12 | `test_i18n_callout_summary`: pl msgstr "W skrócie" | an empty or fuzzy msgstr |
| T13 | help-doc test, if `test_help.py` pins the kind list text | — |

**UI verification (DoD):** light and dark screenshots of a real converted fragment: three
cards stacked; two cards inside a two-column element; a card with a figure and a wide
display formula; a heading containing inline maths; a heading-only card with no body; an Example after the cards showing an
unshifted number. Check the top corners of the bar, where the 3px border meets the 1px
sides on the radius, at zoom. Judge dark separately. Print preview in the dark theme shows
the slate bar at the light value.

**Run scope:** the callout, numbering, transfer, i18n and help tests, every
`test_*css*.py`, and `makemigrations --check`. A whole-repo sweep is a branch gate run in
chunks, never a task step.

## 7. Out of scope

Converting the 34 units; an auto-grid; a "related lesson" field (D6); flashcards; any change
to the other five kinds' look.
