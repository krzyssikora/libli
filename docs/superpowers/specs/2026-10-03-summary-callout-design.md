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
  self.numbered = False` (D5). If `update_fields` was passed and lacks `"numbered"`, add
  it, so a `save(update_fields=["kind"])` that switches a row to summary still persists
  False. This is the write-side guard. Every ORM `save()` caller goes through it: the editor form, the transfer importer, the seeders and the shell.
  `CalloutElement` is not registered in the admin.
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

**Only the counter increment is skipped; the descent still runs.** A summary card is a
container, so an author can nest a numbered Example or Task inside it. The
`CONTAINER_MODELS` recursion is a separate `if` and must stay unconditional. Never write
the guard as an early `continue`, which would also skip the card's children and silently
drop their numbers (T3b).

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
  also h3. The level is **fixed, deliberately**, and not computed from nesting depth. Inside
  a Tabs panel or another callout, the card's h3 becomes a sibling of the container's h3
  rather than nesting under it. That is accepted; do not add depth-aware heading levels.
- **Exact structure.** In the summary branch, the h3 **replaces** the whole `<div
  class="callout__header">` wrapper; it is not placed inside it. The h3 is the first child
  of the `<aside>`. This avoids the wrapper's flex layout and its `margin-bottom` stacking
  with the h3's own margin. T5 asserts that the summary output contains no
  `callout__header`.
- The heading may contain inline KaTeX (`\(…\)`). The selector list in
  `courses/static/courses/js/math.js` `renderInlineText` (`.callout__heading`) does not
  match the new class. **Add `.callout__title` to that list.** Do not reuse
  `callout__heading` on the h3: it would inherit the uppercase eyebrow styling and
  contradict D4. T5b guards the selector list; an e2e check of KaTeX inside the h3 is
  optional extra proof.
- The other kinds' markup must stay **semantically identical**: the summary path is a
  separate `{% if %}` branch, and the existing branch's tags are untouched. Whitespace may
  shift because of the new `{% if %}`, so T6 compares after normalising whitespace.
- The `<aside class="callout callout--summary">` wrapper, the body and the `.callout__children`
  block are shared unchanged, so text, images, maths, nested questions and reveal scoping
  all work as they do in every callout.
- **Accepted, out of scope:** each card stays an unnamed `<aside>` (`complementary`
  landmark), exactly like every other callout kind today. A summary unit with many cards
  therefore lists many unnamed landmarks. Naming them with `aria-labelledby` would be a
  change for all callout kinds, so it belongs in its own change.
- `_callout_icon.html` is not edited. The summary branch never includes it. Its `{% else
  %}` book icon therefore stays the example icon only. Add a comment in the partial saying
  summary deliberately has no icon. Write it as `{% comment %}…{% endcomment %}`: Django's
  `{# #}` is single-line only, and a multi-line one renders as page text (shipped five times
  in this repo).

### 3.4 CSS — `courses/static/courses/css/courses.css`

Place this next to the per-kind accent rules, following their one-line aligned style:

- Light: `.callout--summary { --callout-accent: #4b6b8a; }`. Dark: `[data-theme="dark"]
  .callout--summary { --callout-accent: <light-on-dark slate> }`. The implementer picks a
  dark value in the family of the other dark accents, for example around `#9db4cb`.
  **Acceptance:** the top bar is the kind's only visual identity, so as non-text graphics
  both accents must reach **≥ 3:1** against `--surface-raised` **and** against
  `--surface-base` in their own theme (WCAG 1.4.11: the bar's neighbours are the card's
  inside and the page ground outside). A tinted parent callout, when a card is nested, is
  deliberately not checked. This is asserted by a test (T9b), not only judged from a screenshot.
- The kind-independent title rules sit with their eyebrow counterparts, before the per-kind
  accent groups and outside `@media print`: `.callout__title` and `.callout__title:last-child`
  right after `.callout__heading`, and `.callout__title .katex` right after
  `.callout__heading .katex`.
- **Exact positions**, because `test_print_tokens_css.py` splits the screen half at the
  FIRST `[data-theme="dark"] .callout--`:
  - the light one-liner goes right after `.callout--task` in the light group;
  - the dark one-liner goes right after `[data-theme="dark"] .callout--task` in the dark
    group;
  - the surface overrides go in **one** second `.callout--summary { … }` block after the
    whole dark group. The accent stays in its aligned one-liner, like the other kinds.
- **Summary surface block** contents:
  - `background: var(--surface-raised)`: no tint (D4);
  - `border-left: 1px solid var(--border-subtle)`: cancels the 3px spine;
  - `border-top: 3px solid var(--callout-accent)`: the top bar;
  - it inherits `border`, `border-radius`, `padding` and `margin` from `.callout`, and has no shadow.
- **How T9 reads the CSS.** T9 takes as its input **everything before** the Python literal
  `'@media print {\n  [data-theme="dark"] .callout--'` (newline plus two spaces), the same
  print marker `test_print_tokens_css.py` uses. This is NOT the light/dark split above, whose
  light half would exclude the post-dark-group surface block. It runs the **presence**
  checks for the three declarations above over the **concatenation** of all
  `.callout--summary` blocks, so the accent one-liners need not contain them, and the
  **`box-shadow` absence** check over **every** summary block. Blocks are found with the
  **unanchored** regex `\.callout--summary\s*\{([^}]*)\}`, which also catches the
  `[data-theme="dark"]`-prefixed one-liner. For the title, it matches the
  base block with the anchored multiline regex `^\.callout__title\s*\{([^}]*)\}` and checks its
  declarations only inside that block. `.callout__title:last-child` gets its own anchored
  match. `.callout__title .katex` is never read for them.
- `.callout__title`: exactly `font-size: 1.05rem; font-weight: 700; line-height: 1.3;
  letter-spacing: normal; color: var(--text-primary); margin: 0 0 var(--space-3);`, normal
  case. T9 pins the three declarations that override `reset.css` (`letter-spacing`,
  `line-height`, `margin`) and the `:last-child` rule. `font-size`, `font-weight` and
  `color` are left to the screenshot check. `.callout__body`'s first-child margin reset already
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

### 3.5 Editor — `templates/courses/manage/editor/_edit_callout.html` and `courses/element_forms.py`

`CalloutElementForm` lives in `courses/element_forms.py` and today has only `Meta`. It
gains the `__init__` and `clean()` overrides described below.

- The kind `<select>` loops over `form.fields.kind.choices`, so "W skrócie" appears
  automatically.
- The hand-written "Number this callout" checkbox block is wrapped in `{% if
  form.original_kind != "summary" %}` (D5). `original_kind` is a public attribute set in
  `CalloutElementForm.__init__` **after** `super().__init__(*args, **kwargs)`, as
  `self.original_kind = self.instance.kind`. On the create path, `builder` passes
  `instance=None` and the create view builds the form with no instance, so the kind cannot
  be read from kwargs beforehand. After `super().__init__`, `self.instance` is either the
  saved row or a fresh `CalloutElement()` with the default `example`. Nothing has been
  mutated yet at that point: `construct_instance` runs later, in `full_clean()`. It is the same value the restore rule below reads,
  so the checkbox and the restore literally share one attribute. Do **not** key on
  `form.instance.kind` or `form.kind.value`. On an invalid POST, Django's
  `BaseModelForm._post_clean()` still runs `construct_instance()`, copying every field
  that reached `cleaned_data` onto `self.instance`. `element_save` re-renders that very
  form on a 422, so `form.instance.kind` would already hold the POSTed kind. No editor JS toggles fields by
  kind today, and none is added. Switching the select from Example to W skrócie leaves the
  checkbox visible until the next save. That is harmless, because `save()` forces False,
  and the re-render hides it. State this in a `{% comment %}…{% endcomment %}` block (never a
  multi-line `{# #}`) so nobody "fixes" it with JS.
- **The reverse switch (summary → another kind) restores that kind's default.** When a
  summary card is edited, the checkbox is not rendered, so the POST carries no `numbered`.
  Without care, switching it to Example saves `numbered=False` and silently unnumbers it.
  `CalloutElementForm` records the instance's kind at `__init__` as `self.original_kind`.
  In `clean()`, it reads `new_kind = cleaned_data.get("kind")`. If that is absent, because
  the kind failed choice validation, it skips the restore so the normal field error
  returns a 422 rather than a `KeyError`. Otherwise, if the original kind was `summary`,
  the new kind is not, **and `self.add_prefix("numbered") not in self.data`** (prefix-safe), it sets
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
  `SUMMARY` enum member. The gate is the deployed code, not the migration. Before
  importing an archive with W skrócie cards into any other instance (for example a school
  box on a tagged release), confirm that instance runs a release containing this feature.*
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
  ikoną"), and the next clause describes the "Number this callout" checkbox. For the new
  kind the icon and the numbering do not apply, but the accent colour does, as the top bar.
  Qualify both in both files: Key facts / W skrócie keeps its own accent colour as a top
  bar, has no icon, and is never numbered. Say that each card should carry its topic name as the heading, because a blank one shows
  the generic "Key facts" / "W skrócie", and several of those make a run of identical
  headings. Add one sentence saying it is meant for summary units, one card per
  topic, and can go two-up inside the container the docs already call **Columns**. Add a
  tip: avoid H2/H3 inside a card and use H4 or bold text for sub-points, because a typed
  H2 or H3 would look bigger than the card's title. In the
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
- `numbered=True` arriving for a summary by form, archive, seeder or shell: forced False in
  `save()`. If a row bypasses `save()`, numbering still skips it (§3.2).
- Older instance importing a card: refused at that element with "unknown callout kind"; other archives import (D7).
- Empty heading: falls back to "W skrócie".

## 6. Testing

Each test must be seen **RED against the named mutant** before being trusted (house rule).

| # | Test | Mutant it must catch |
|---|---|---|
| T1 | `test_callout_model`: `display_heading` of an empty-heading summary == "Key facts" (en) | drop the enum member / label |
| T2 | `test_callout_model`: save summary with `numbered=True` → reloads False; an existing numbered Example switched via `save(update_fields=["kind"])` → reloads `numbered=False` | remove the `save()` force; drop the `update_fields` extension |
| T3 | `test_callout_numbering`: unit = Example, Summary(numbered forced True via `.update()`), Example → numbers {ex1:1, ex2:2}, summary absent | remove the `kind != SUMMARY` guard in `walk()` |
| T3b | `test_callout_numbering`: unit = Example, Summary containing a nested numbered Example, Example → numbers {ex1:1, nested:2, ex3:3}, summary absent | skip the container descent for summary (`continue` before the recursion) |
| T4 | `test_callout_numbering`: key-set test passes and `KIND_DEFAULT_NUMBERED["summary"] is False` | set it True |
| T5 | `test_callout_render`: summary renders `callout--summary` with an `<h3 class="callout__title">` holding the heading text as the aside's first **element** child (e.g. `aside.find(True, recursive=False)`; whitespace text nodes precede it); **no** `callout__header`, **no** `callout__icon` and **no** `callout__heading` | render the summary through the generic branch |
| T5b | `courses/tests/test_math_selectors.py::test_every_typeset_region_is_in_the_selector_list`: add `.callout__title` to its region tuple. This is the deterministic catcher. An e2e check of KaTeX inside `h3.callout__title` is optional extra proof for the UI pass | drop `.callout__title` from the math.js selector list |
| T6 | in `courses/tests/test_callout_numbering_render.py`, using its `_rendered(el, join, numbers)` helper, because a bare unsaved `.render()` emits no number: for a numbered Example with a heading, whitespace-normalised output contains the exact header string: icon markup + `<span class="callout__heading">Example <span class="callout__number">1</span>. Heading</span>`; and no `callout__title` | an edit that leaks the summary branch into others or alters the generic header |
| T7 | `test_callout_authoring` (all T7/T7b POSTs reuse that module's existing POST helper, or send the full `element_save` shape: `type`, `unit_token`, `el_title` and the fields; a missing `el_title` blanks the title): the picker contains `<option value="summary">Key facts</option>`; POST kind=summary round-trips; the rendered form for a summary has no `name="numbered"` input, and for an example it does | remove the `{% if %}` around the checkbox |
| T7b | `test_callout_authoring`: POST that switches a saved summary to `example` with no `numbered` key → saved `numbered=True`; to `note` → False; a crafted POST switching a saved summary to `example` with the key present as `numbered=false` saves False, so a sent value is not overridden (Django's `CheckboxInput` reads `"false"` as False); editing an existing Example whose unticked box sends no `numbered` → stays False (the restore applies only when leaving summary); the rendered form for a saved example whose POST asked for summary and got a 422 still shows the checkbox. Force that 422 with `kind=summary` plus a 121-character heading (`max_length=120`): kind must stay valid for the mutant to be exercised. Assert status 422 and that `name="numbered"` is in the response; creating a new callout through the form (no instance) still works and its form renders the checkbox | remove the `clean()` restore, apply it unconditionally, drop the `not in self.data` check, or key the checkbox on `form.instance.kind` |
| T7c | `courses/tests/test_callout_form.py` (existing; tests `CalloutElementForm` directly): `CalloutElementForm(data=…, instance=summary)` switching to `example` with no `numbered` key → `cleaned_data["numbered"] is True`; with the key present as `false` → False; invalid data `instance=summary`, `kind="example"` (valid) plus a 121-character heading → after `is_valid()` is False, assert `form.original_kind == "summary"` **and** `form.instance.kind == "example"`, which proves the two diverged. With an unchanged kind the lazy mutant could never go red. T7/T7b keep the POST-level checks for the template `{% if %}` and the 422 re-render | remove the restore; drop the key-presence check; set `original_kind` lazily from `self.instance` after validation |
| T8 | `test_callout_transfer`: summary round-trip keeps kind/heading/body with `numbered` False; extend the existing validator-level pre-v13 test (`test_a_pre_v13_payload_imports_with_the_per_kind_default`) to assert `data["numbered"] is False` for summary **on the validated payload**, not the saved row, because `save()` would mask the mutant; the export manifest still says `format_version == 16` (D7) | drop the summary key from `KIND_DEFAULT_NUMBERED` |
| T9 | `test_callout_css`: anchored regexes pinning the light `#4b6b8a` and the **literal dark value the implementer picks** (as `test_callout_task_dark_accent_is_pinned` does; record the chosen value in the PR body); the concatenated non-print `.callout--summary` blocks contain `border-top: 3px solid var(--callout-accent)`, `border-left: 1px solid var(--border-subtle)` and `background: var(--surface-raised)`, and **no** block has a `box-shadow`; `.callout__title` declares `letter-spacing: normal`, `line-height: 1.3` and `margin: 0 0 var(--space-3)` ; also extend `test_courses_css_defines_callout_element`'s class list with `.callout--summary` and `.callout__title`; `.callout__title:last-child` sets `margin-bottom: 0` | delete the `border-top` line; change `border-left` back to 3px or to the accent; swap `background` back to the `color-mix` tint; add a `box-shadow` to any summary block, including the dark one-liner; drop `letter-spacing: normal` from `.callout__title` |
| T9b | `tests/test_callout_css.py`: read both summary accents **from `courses.css`** with T9's anchored regexes, never as literals, and the grounds from `LIGHT_SURFACES`/`DARK_SURFACES` in `tests/test_text_colour_css.py` (import them and its `_ratio` helper, or whatever that module's contrast helper is named). Assert ≥ 3:1 against both `--surface-raised` and `--surface-base` for each theme | edit the dark accent in `courses.css` to a too-pale value |
| T10 | `test_print_tokens_css`: `CALLOUT_KINDS` += "summary" | omit the print rule |
| T11 | `test_text_colour_css`: add `callout-summary` = the plain `--surface-raised` value (light and dark) to `LIGHT_SURFACES`/`DARK_SURFACES`, which the enum-derived test requires. Do **NOT** add "summary" to the 6%-mix kinds tuple in `test_surface_literals_still_match_the_css`: that loop recomputes the ground as accent mixed into `--surface-raised`, which can never equal an untinted ground. Pin it in two places: T9's `background: var(--surface-raised)` assertion pins the CSS side, and a new assertion in `test_surface_literals_still_match_the_css` pins the literal side: `surfaces["callout-summary"] == surfaces["--surface-raised"]` for both themes. Without it, a later `--surface-raised` change would leave a stale summary ground measuring green. Add `callout-summary` to `BORDER_GROUNDS` in `test_border_contrast_css`. Prose: the module docstring's "eleven surfaces" becomes "twelve surfaces" (verify by counting one list after the edit). The header comment's "recomputes the five callout grounds" stays **five**, plus a note that summary is untinted and checked by equality instead | remove `callout-summary` from `DARK_SURFACES` (`test_every_callout_kind_has_a_ground_in_both_surface_lists` goes red); misspell the `BORDER_GROUNDS` key (`test_border_grounds_all_exist_in_the_measured_surface_lists` goes red) |
| T12 | `test_i18n_callout_summary`: pl msgstr "W skrócie"; and, mirroring `test_en_catalog_has_the_task_msgid`, `locale/en` has exactly one live `msgid "Key facts"` whose msgstr is empty | an empty or fuzzy pl msgstr; a missing or duplicated en entry |
| T13 | `tests/test_help.py` (or a sibling): the `{el:callout}` paragraph of the en and pl content-editors docs contains "Key facts" / "W skrócie" respectively, and is still matched by `_EL_PARA_RE` (a stray blank line splitting the paragraph turns this red) | revert the help-doc edit, or split the paragraph |

**UI verification (DoD):** light and dark screenshots of a real converted fragment: three
cards stacked; two cards inside a two-column element; a card with a figure and a wide
display formula; a heading containing inline maths; a heading-only card with no body; a
card whose body holds a typed H3 and an H4 sub-heading next to the card title, so the owner
can judge the relative sizes (specifically, the H4 sub-point must read as subordinate to the
1.05rem title: an unstyled h4 is about 1em bold, only about 5% smaller. If it does not read
as subordinate, report that as a finding; do not restyle h4 in this change.) Also required: an Example after the cards showing an
unshifted number. Check the top corners of the bar, where the 3px border meets the 1px
sides on the radius, at zoom. Judge dark separately. Print preview in the dark theme shows
the slate bar at the light value.

**Run scope:** the callout, numbering, transfer, i18n and help tests, every
`test_*css*.py`, and `makemigrations --check`. A whole-repo sweep is a branch gate run in
chunks, never a task step.

## 7. Out of scope

Converting the 34 units; an auto-grid; a "related lesson" field (D6); flashcards; any change
to the other five kinds' look.
