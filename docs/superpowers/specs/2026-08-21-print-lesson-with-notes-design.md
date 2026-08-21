# Print lesson with notes

A student who has worked through a lesson — and annotated it — can print that lesson, or save it
as a PDF, **with their own notes on the page**.

## Purpose

Today a student cannot do this, and the reason is narrower than it looks.

**Printing a lesson already works.** The repo carries **13** `@media print` blocks — 3 in
`core/static/core/css/app.css`, 10 in `courses/static/courses/css/courses.css` — and they encode
real decisions: `.el--tabs` un-hides every `[role="tabpanel"][hidden]` and every carousel slide;
`beforeafterelement` prints both sides and reveals its `.ba__side-heading`; reveal-gates un-hide
their downstream blocks while the gate *buttons* drop out (with `[data-filltablegate]` deliberately
exempted, because a marked fill-table **is the student's work**); `.el--image--*` gets mm height
caps; `.unit-strip__edit`, `.draft-banner__form`, the TOC pin and the scroll-edge gradients all
disappear. This is a considered print story, not an accident.

**Notes print as nothing.** `notes/static/notes/css/notes.css` is 443 lines and contains the
substring `print` **zero** times. `tags.css` likewise has 0 `@media print` blocks. Every note on a
lesson page lives inside `<details class="block-notes__panel">`, closed by default
(`notes/templates/notes/_block_notes.html`), and a closed `<details>` hides its content via the UA
rule `::details-content { content-visibility: hidden }` — so the note subtree is present in the DOM,
counted by `querySelectorAll`, carrying a stale non-zero `getBoundingClientRect()`, and **not
painted**, on screen or on paper.

**There is also no affordance.** `templates/courses/_unit_strip.html` holds exactly two things: the
tag panel and, for authors, `Edit unit`. Nothing anywhere in the student UI offers to print.

So the feature is: an affordance, a reliable way to get the note panels open at print time, and
print styling for the note cards. The lesson body itself needs no new work.

### Scope

Print and "save to a file" are **one control**, not two. `window.print()` opens the browser's own
dialog, whose destination list already includes *Save as PDF* on Chrome, Edge, Firefox and Safari.
That is a real PDF, produced by the same engine that already renders KaTeX and the lesson's images
correctly. No PDF library enters `pyproject.toml`; no server-side rendering path is built.

**Explicitly out of scope:** server-side PDF generation; whole-chapter or whole-course printing; an
"include my notes" toggle; a print affordance on quiz pages.

## Architecture / components

### 1. The affordance — `templates/courses/_unit_strip.html`

A `Print` button, placed before the existing `Edit unit` link, rendered **only when the including
template passes a flag**:

```
{% if show_print %}<button type="button" class="btn btn--ghost btn--small unit-strip__print" data-print-lesson>…</button>{% endif %}
```

`_unit_strip.html` is included by **three** templates — `lesson_unit.html`, `quiz_unit.html` and
`quiz_results.html` — and only the first renders notes at all (`_block_notes.html` is reached from
`_lesson_article.html`). Quiz print has never had a design pass, and printing a quiz mid-attempt is
a different feature with different answers. So `lesson_unit.html` alone passes
`{% include "courses/_unit_strip.html" with show_print=True %}`; the two quiz templates change by
zero lines and get no button.

The icon follows the project convention: a monochrome inline SVG using `currentColor`, never an
emoji.

### 2. The mechanism — `courses/static/courses/js/print.js` (new)

A small IIFE in the established style of the other lesson scripts, loaded `defer` from
`lesson_unit.html`.

**Why JS and not CSS.** A print stylesheet cannot open a closed `<details>`. The content is hidden
by `content-visibility` on the UA `::details-content` pseudo-element; author CSS cannot reliably
override that across Chromium, Firefox and WebKit. Adding the `open` attribute is the only portable
mechanism.

Responsibilities:

1. **Wire the button** — `[data-print-lesson]` click → `window.print()`.
2. **Hook `beforeprint`** — this is load-bearing, not a nicety. Most people will press `Ctrl+P`
   rather than hunt for a button, and a printout that includes notes only via the button would be a
   trap. On `beforeprint`: add `open` to every `.block-notes__panel` and to the
   `.unanchored-notes > details` that is not already open, and **record exactly which elements were
   opened** (a local array, not a class, so nothing leaks into the DOM). On `afterprint`: remove
   `open` from precisely those recorded elements and clear the list. A panel the student had already
   opened is never closed behind their back.
3. **Neutralise the two enhancement side-effects below**, both triggered *by* step 2.
4. **Force the light palette for the duration** — see §4.
5. **Safari** fires `beforeprint`/`afterprint` unreliably; also subscribe to
   `matchMedia("print")` change events and route both to the same enter/leave handlers, guarded so a
   double-fire is idempotent.

#### 2a. Trap: `positionPop` writes an inline `top`

`notes.js` listens for `toggle` **in the capture phase** (`notes.js:531`) and, when a
`.block-notes__panel` opens, calls `positionPop`, which sets `pop.style.top = handle.offsetTop + "px"`
(`notes.js:522`). Setting `open` from `print.js` therefore fires `toggle` and stamps an inline
`top` of arbitrary magnitude onto `.block-notes__pop`.

An inline style beats any author rule without `!important`, so the print stylesheet must reset it
that way (§3), **or** `print.js` must clear `pop.style.top` after opening. The spec takes the CSS
route with `!important`, because it also covers the case of a panel the *student* opened before
printing — which carries the same inline `top` and which `print.js` never touches.

#### 2b. Trap: `setupClamp` truncates long notes to 6 lines

The same `toggle` handler also calls `setupClamp` (`notes.js:97`), which adds
`.note-card__body--clamp` to every note body — `-webkit-line-clamp: 6; overflow: hidden`
(`notes.css:186`) — and appends a *Show more* button when the body overflows.

Consequence: opening the panels for print **truncates every note longer than six lines**, silently,
losing the exact content the student asked to keep. The print stylesheet must un-clamp
(§3). This is a defect the feature *creates* and must therefore carry the fix for.

### 3. The print stylesheet — a new `@media print` block at the end of `notes.css`

The file currently has none. The block must:

- **Return the pop to flow.** At `≥1200px` under `.notes-js`, `.block-notes__pop` is
  `position: absolute; left: calc(100% + 1rem); width: 15rem; max-height: min(70vh, 34rem);
  overflow-y: auto` with a shadow and a z-index (`notes.css:90–107`). Print reverts position, left,
  width, max-height and overflow, drops the shadow, and clears the inline `top` with
  `top: auto !important` (per §2a).
- **Un-clamp bodies.** `.note-card__body--clamp { display: block; -webkit-line-clamp: none;
  overflow: visible; }` and hide `.note-card__more` (per §2b).
- **Hide the controls.** `.block-notes__handle` (the toggle icon), `.note-card__actions` (the
  edit/delete links) and `.note-composer` are all interaction, not content.
- **Keep the card, keep the rail.** `.note-card` already carries
  `border-left: 4px solid var(--note-accent, …)` and the eight stable per-block hues are already
  bound via `data-colour`. Print keeps that rail — borders are painted even when the browser's
  "background graphics" option strips backgrounds — and adds `break-inside: avoid` so a note is not
  split across a page boundary.
- **Label the annotation.** A print-only `MY NOTE` label so a reader can never mistake a student's
  annotation for the author's lesson text. See §Open decision below for the mechanism.
- **Give an absolute date.** `.note-card__meta` renders `added 3 days ago` via `timesince`
  (`_note_card.html`), which is meaningless on paper read weeks later. The card gains a print-only
  absolute date; the relative form stays on screen.

`courses.css` gains one rule beside the existing `@media print { .unit-strip__edit { display: none; } }`
(line 2308): `.unit-strip__print { display: none; }`.

#### Specificity note

Any un-hide of a `.visually-hidden` element on this page must be written at **(0,2,0) or higher**.
`.visually-hidden` is defined in **three** stylesheets — `app.css:1384` (6 declarations), plus
`notes.css:4` and `tags.css:6` (**9** each, adding `padding: 0`, `margin: -1px`, `border: 0`) — and
`lesson_unit.html` loads `courses.css`, then `notes.css`, then `tags.css`. A single-class un-hide is
dead on arrival, and a mutant written at (0,1,0) is inert and will mislead. A full un-hide must also
reset all nine declarations, `margin: -1px` included.

### 4. Dark theme — an in-scope, pre-existing defect

`tokens.css:79` defines `[data-theme="dark"]` with `--text-primary: #F2EFE9` (near-white). **No**
print rule anywhere resets the theme, and `print-color-adjust` appears nowhere in the repo. Browsers
strip backgrounds by default when printing. So a dark-theme student printing a lesson today gets
near-white text on white paper — a blank page.

The theme is attribute-driven only: `tokens.css` contains no `prefers-color-scheme` query, and the
attribute is server-rendered from `user.theme`. So the fix is one line in `print.js`'s enter/leave
handlers: stash `documentElement.dataset.theme`, set it to `light` for the duration of printing,
restore it after. This reuses the exact light palette with zero token duplication and no risk of the
two drifting.

This is included rather than deferred because shipping a Print button that yields a blank page for
every dark-theme student would be shipping a broken feature. It is nonetheless separable: the notes
work stands without it.

### 5. Degradation (no JS)

With JS off, `notes.js` never adds `.notes-js`, the panels stay closed, and the button does nothing.
This is stated, not hidden. The existing `?notes=1` query parameter is the no-JS route and **already
works today**: `_block_notes.html` server-renders `<details … open>` when `notes_show` is set and the
block has notes, so `…/u/<pk>/?notes=1` followed by `Ctrl+P` prints a lesson with its notes open,
with no JS at all. No new server-side work is required for this path.

### 6. i18n

The new user-visible strings (`Print`, the `MY NOTE` label, the absolute-date format) go through
`{% trans %}` / `gettext` and into the `pl` catalogue via `makemessages`. Two known hazards apply:
`makemessages` pre-fills fuzzy entries with a **wrong** translation, and clearing one requires
deleting **both** the `#, fuzzy` marker and the bogus `msgstr`; and the binary `.mo` must be
regenerated at the end rather than carried stale through a long branch.

## Data flow

Nothing is persisted, and no request is made. There is no new view, no new URL, no new model field
and no migration. The whole feature is client-side, over markup the server already renders:

```
student clicks Print  ─┐
                       ├─→ window.print()
student presses Ctrl+P ─┘        │
                                 ▼
                         'beforeprint' fires
                                 │
                 ┌───────────────┼────────────────┬─────────────────┐
                 ▼               ▼                ▼                 ▼
        stash data-theme   open closed      (notes.js toggle    record which
        → 'light'          .block-notes__     handler fires:     panels WE
                           panel + the        positionPop        opened
                           unanchored         stamps inline
                           <details>          top; setupClamp
                                              clamps bodies)
                                 │
                                 ▼
                    @media print in notes.css undoes both
                    (top:auto !important; un-clamp) and hides
                    handle / actions / composer
                                 │
                                 ▼
                       browser paints the sheet
                       (or writes the PDF)
                                 │
                                 ▼
                         'afterprint' fires
                                 │
                    restore data-theme; close exactly
                    the panels we opened
```

## Error handling

- **`afterprint` never fires** (a known browser inconsistency, notably when a print job is
  cancelled). The page would be left with panels open and the theme forced light. Mitigation: drive
  the leave path from the `matchMedia("print")` change event as well, which is the more reliable
  signal on Safari, and make both paths idempotent so a double-fire is harmless.
- **`checkVisibility()` is undefined** on engines older than Chromium 105 / Firefox 125 /
  Safari 17.4, and calling it **throws**, which at module scope inside an IIFE aborts the rest of the
  file. Any use of it must be feature-detected, following the pattern already used in `unit_nav.js`.
- **A student had panels open before printing.** Handled by construction: `print.js` records only
  the panels it opened itself and restores only those.
- **No JS.** Documented degradation, with `?notes=1` as the working alternative (§5).
- **A unit with no notes.** The button still prints, producing the lesson exactly as it prints
  today. No empty "My notes" furniture is emitted.

## Testing

The house rule applies: **falsify the tests, do not merely run them.** Each assertion below is
paired with the mutant that must turn it RED, chosen from the failure mode it is meant to catch.

### e2e — `tests/test_e2e_print_lesson_notes.py` (new, `pytestmark = pytest.mark.e2e`)

Driven with `page.emulate_media(media="print")`, following the login/fixture pattern already proven
in `tests/test_e2e_notes.py` (allauth `input[name='login']`, `TEST_PASSWORD`, `seed_roles()`,
`published=True` on the unit).

| # | Assertion | Mutant that must make it RED |
|---|---|---|
| 1 | Under print media, a note body is **genuinely visible** | delete the `beforeprint` handler from `print.js` |
| 2 | A note body longer than 6 lines prints **in full** | delete the un-clamp rule from the print block |
| 3 | `.block-notes__pop` sits **in flow** (its box is left-aligned with its block, not offset into the margin) at a ≥1200px viewport | delete the `position`/`top` reset from the print block |
| 4 | `.block-notes__handle`, `.note-card__actions` and `.note-composer` are **not** visible under print media | delete the control-hiding rule |
| 5 | A panel the student opened by hand is **still open** after `afterprint` | make `afterprint` close all panels rather than only the recorded ones |
| 6 | For a `user.theme == "dark"` student, printed text colour is **dark** | delete the theme stash/restore from `print.js` |
| 7 | The Print button is absent from `quiz_unit.html` | render the button unconditionally in `_unit_strip.html` |

Three measurement traps in this repo's history bear directly on assertions 1 and 4 and must be
respected, or the tests will pass on a broken build:

- **`bounding_box()` stays non-zero through a closed `<details>`** — measured 52.4×22 for a real
  element inside a closed group — and `querySelectorAll` counts it. The only correct discriminator is
  **`el.checkVisibility()` with no options**, which per spec returns `false` unconditionally when a
  flat-tree ancestor has `content-visibility: hidden`.
- **Playwright reports a `.visually-hidden` element as VISIBLE** (it is 1×1 with a zero clip rect,
  so its bounding box is non-empty). `expect(...).to_be_visible()` on `.note-card__on` therefore
  cannot fail, and `.note-card__on` must never stand in for the note body. Where a size assertion is
  needed, assert a numeric threshold on `bounding_box()["height"]`, not mere presence.
- **`wait_for_selector(sel)` defaults to `state="visible"`** and will hang on a clipped-but-present
  element; use `state="attached"`.

### Non-e2e

- `tests/test_notes_presentation.py` gains assertions that the shipped `notes.css` contains the
  print block and each rule the e2e depends on — cheap, and it fails loudly if the block is ever
  dropped wholesale.
- A template test that `lesson_unit.html` passes `show_print=True` and the two quiz templates do
  not.
- `tests/test_i18n_notes.py` (or the project's existing i18n test) covers the new strings.

### Test-run mechanics

`-m e2e` is mandatory or the e2e tests deselect and the run exits 5; the test-DB container must be
started first; `pytest`'s exit code can report 0 with failures present, so the summary line must be
grepped rather than the exit code trusted. Runs stay scoped to the affected tests, not the whole
suite.

## Open decision (for review)

The `MY NOTE` print label has three viable mechanisms and the spec deliberately does not pick one,
because the choice interacts with i18n and with the (0,2,0) specificity constraint above:

1. a `::before` on `.note-card` whose `content` reads a custom property set from a translated
   string;
2. un-hiding the existing `.note-card__on` paragraph (which already reads `on: <block>` and is
   already translated) — but this requires resetting all **nine** `.visually-hidden` declarations at
   (0,2,0)+;
3. a new print-only element in `_note_card.html`, hidden on screen.

Option 3 is the most explicit and the least entangled with the `.visually-hidden` triple definition;
option 2 reuses an existing translated string but inherits the specificity trap. The implementation
plan should settle this.
