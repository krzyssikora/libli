# Print lesson with notes

A student who has worked through a lesson — and annotated it — can print that lesson, or save it
as a PDF, **with their own notes on the page**.

## Purpose

Today a student cannot do this, and the reason is narrower than it looks.

**Printing a lesson already works.** The repo carries **10** `@media print` blocks — 2 in
`core/static/core/css/app.css` (lines 1183, 1913) and 8 in `courses/static/courses/css/courses.css`
(103, 967, 1113, 1349, 1852, 2105, 2308, 2359); three further textual hits are comments
(`app.css:597`, `courses.css:1346`, `courses.css:2411`) and are not blocks. Those blocks encode real
decisions: `.el--tabs` un-hides every `[role="tabpanel"][hidden]` and every carousel slide;
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
template passes a flag**. The full element, so the msgid list in §6 and the template test are
writable without guesswork:

```html
{% if show_print %}
  <button type="button" class="btn btn--ghost btn--small unit-strip__print" data-print-lesson>
    <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M6 9V3h12v6"/><path d="M6 18H4v-6h16v6h-2"/><path d="M6 14h12v7H6z"/>
    </svg>
    {% trans "Print" %}
  </button>
{% endif %}
```

`btn--small`, **not** `btn--sm`: only `.btn--small` is defined (`app.css:50`). The SVG carries
`aria-hidden="true" focusable="false"`, matching the Edit icon directly beside it. Monochrome
`currentColor`, never an emoji, per the project icon convention. The visible label is the accessible
name; no extra `aria-label` is needed.

`_unit_strip.html` is included by **three** templates — `lesson_unit.html`, `quiz_unit.html` and
`quiz_results.html` — and only the first renders notes at all (`_block_notes.html` is reached from
`_lesson_article.html`). Quiz print has never had a design pass, and printing a quiz mid-attempt is
a different feature with different answers. So `lesson_unit.html` alone passes
`{% include "courses/_unit_strip.html" with show_print=True %}`; the two quiz templates change by
zero lines and get no button.

**No-JS gating.** The button's only behaviour is `window.print()`, so with JS off it is a rendered
dead control — worse than no affordance. `base.html:15` already adds a `js` class to
`documentElement` in its prepaint script, so the button is gated on it in `courses.css`:

```css
.unit-strip__print { display: none; }
html.js .unit-strip__print { display: inline-flex; }
```

No-JS students are not left without a route: see §5.

### 2. The mechanism — `courses/static/courses/js/print.js` (new)

A small IIFE in the established style of the other lesson scripts, loaded `defer` from
`lesson_unit.html`. It lives under `courses/` rather than `notes/` because it is a **lesson-page**
concern — it owns the unit-strip button and the print lifecycle for the whole page — and is loaded
beside the other `courses/js/*.js` lesson scripts. The notes DOM it touches is incidental to that
role.

**Why JS and not CSS.** A print stylesheet cannot open a closed `<details>`. The content is hidden
by `content-visibility` on the UA `::details-content` pseudo-element; author CSS cannot reliably
override that across Chromium, Firefox and WebKit. Adding the `open` attribute is the only portable
mechanism.

Responsibilities:

1. **Wire the button** — `[data-print-lesson]` click → `window.print()`.
2. **Hook `beforeprint`** — load-bearing, not a nicety. Most people press `Ctrl+P` rather than hunt
   for a button, and a printout that included notes only via the button would be a trap.
3. **Sweep only panels that carry notes.** `_block_notes.html` renders an
   `<aside class="block-notes">` for **every** element on the page, whether or not it has notes; a
   note-less panel contains a `<p class="block-notes__add-label">Add a note</p>` and a composer.
   Opening all of them would print an "Add a note" line under every block of a fifty-block lesson.
   So the sweep is:

   ```js
   panels = [...document.querySelectorAll(".block-notes__panel:not([open])")]
              .filter(p => p.querySelector(".note-card"));
   ```

   plus the `.unanchored-notes > details` when it exists and is closed (it is rendered only when
   `unanchored_notes` is non-empty, and its notes are exactly the ones whose block was deleted — they
   must print, or the printout silently loses them).
4. **Record what it opened.** A module-local array, so a panel the student had already opened is
   never closed behind their back.
5. **Restore on `afterprint`** — remove `open` from precisely the recorded elements, clear the list,
   and undo the `setupClamp` residue (§2b).
6. **Safari** fires `beforeprint`/`afterprint` unreliably; also subscribe to `matchMedia("print")`
   change events and route both to the same enter/leave handlers, guarded so a double-fire is
   idempotent.

The theme is **not** handled here — see §4.

#### 2a. `positionPop` writes an inline `top` — a cascade hazard, not a paper defect

`notes.js` listens for `toggle` **in the capture phase** (`notes.js:531`) and, when a
`.block-notes__panel` opens, calls `positionPop`, which sets `pop.style.top = handle.offsetTop + "px"`
(`notes.js:522`).

**How much this matters depends on the width the media query sees.** The absolute positioning lives
in `@media (min-width: 1200px)` (`notes.css:90`). When a browser actually prints, media queries are
evaluated against the **page box**, which for A4 is roughly 794 CSS px — so `min-width: 1200px` is
**false**, `.block-notes__pop` is already `position: static`, and an inline `top` on a static box is
inert. On paper this trap does not fire.

It fires under **Playwright's `emulate_media(media="print")`**, which switches media-type evaluation
while keeping the screen viewport — so at a ≥1200px test viewport the absolute rule is live and the
inline `top` applies. It would also fire on a very wide printer page box.

The reset is therefore kept as cheap insurance and as a cascade regression test, and the spec is
explicit that assertion 3 measures the cascade under emulation, **not** a claim about paper.

#### 2b. `setupClamp` truncates long notes to 6 lines, and leaves DOM residue

The same `toggle` handler calls `setupClamp` (`notes.js:97`), which adds `.note-card__body--clamp`
to every note body — `-webkit-line-clamp: 6; overflow: hidden` (`notes.css:186`) — and
`insertAdjacentElement`s a `<button class="note-card__more">` after each body that overflows.

Two consequences, both this feature's to fix:

- **In print:** every note longer than six lines is silently truncated — the feature would destroy
  the exact content it exists to preserve. Undone in CSS (§3).
- **After print:** the clamp classes and the injected buttons **persist in the live DOM** once
  `afterprint` closes the panels, and the print CSS no longer applies to them. The student is left
  with clamped notes and *Show more* buttons they never asked for. So `afterprint` must also remove
  `.note-card__body--clamp` and any `.note-card__more` from **the panels `print.js` opened** — panels
  the student opened by hand were clamped by their own gesture and are left alone.

#### 2c. `toggle` is asynchronous — the mitigations must be order-independent

The HTML specification queues a task for the `<details>` toggle event; it does not fire synchronously
on assignment. Whether that task runs before the browser snapshots the print document is
engine-dependent, so `positionPop` / `setupClamp` may run during the print pass, after it, or — if
`afterprint` already closed the panel, since the handler re-checks `panel.open` — not at all.

Two requirements follow. The §2a mitigation must be **CSS**, which applies whenever the declarations
land and needs no ordering guarantee (this is the decisive reason to prefer it over clearing
`pop.style.top` in JS). And **no test may assert that the toggle side effects happened** — only that
the printed result is correct either way. The §2b `afterprint` cleanup is written to be a no-op when
the side effects never ran.

### 3. The print stylesheet — a new `@media print` block at the end of `notes.css`

The file currently has none.

#### Specificity is the load-bearing constraint

`@media print` adds **no** specificity — `courses.css:1346` already records this lesson in a comment.
The rules being undone are not weak:

| Rule to undo | Selector | Weight |
|---|---|---|
| pop floats into the margin (`notes.css:90–107`) | `.notes-js .block-notes__panel[open] .block-notes__pop` | (0,4,0) |
| pop clamped to the right (`notes.css:110–113`) | `.notes-js .block-notes__panel[open] .block-notes__pop--clamped` | (0,4,0) |
| inline `top` from `positionPop` | — | inline |

So a print rule written as `.block-notes__pop { position: static; … }` at (0,1,0) is **inert
regardless of source order**, and a mutant written at (0,1,0) is equally inert and will mislead.
Every print declaration that undoes one of the above must either **match the original selector at
(0,4,0) or higher**, or carry `!important`; the inline `top` needs `!important` unconditionally.
This applies to the `.visually-hidden` family too — see the note below.

#### The block must

- **Return the pop to flow.** Reset `position`, `top` (`!important`, per the inline style), `left`,
  `right`, `width`, `max-height`, `overflow-y`, `z-index` and `box-shadow`. `right` is named
  explicitly because `.block-notes__pop--clamped` sets `left: auto; right: 0`: resetting `left` alone
  leaves `right: 0` applied. Alternatively `print.js` may strip the `--clamped` class from the panels
  it opens; the CSS reset is required either way, because a panel the *student* opened carries the
  same class and `print.js` never touches it.
- **Un-clamp bodies.** `.note-card__body--clamp { display: block; -webkit-line-clamp: none;
  overflow: visible; }`, and hide `.note-card__more`.
- **Hide every control.** `.block-notes__handle` (the toggle icon), `.note-card__actions` (edit /
  delete), `.note-composer`, **`.block-notes__add-more`** ("Add another note", rendered whenever a
  block *has* notes) and **`.block-notes__add-label`** ("Add a note"). The last two are easy to miss
  and would otherwise print as if they were lesson content.
- **Reset the hover/focus highlight state.** `notes.js` adds `.lesson-block.is-highlighted`
  (background tint + outline, `notes.css:278`) to one block and `.lesson-block.is-dimmed`
  (`opacity: .45`, `notes.css:284`) to every other when a note card is hovered or focused, clearing
  it only on blur. A student who clicks a note and then presses `Ctrl+P` would print most of the
  lesson at 45% opacity. Print resets `.is-dimmed` to `opacity: 1` and neutralises `.is-highlighted`'s
  background and outline. `.block-notes__handle.is-highlighted` and `.note-card.is-highlighted`
  (`notes.css:287, 292`) are covered by the control-hiding and card rules respectively.
- **Keep the card, keep the rail.** `.note-card` already carries
  `border-left: 4px solid var(--note-accent, …)` with eight stable per-block hues bound via
  `data-colour`. Print keeps that rail — borders are painted even when the browser's "background
  graphics" option strips backgrounds — and adds `break-inside: avoid`.
- **Label the annotation** and **give an absolute date** — see below.

`courses.css` gains one declaration **inside** the existing block at line 2308, which becomes:

```css
@media print { .unit-strip__edit, .unit-strip__print { display: none; } }
```

Inside, not beside: a rule placed next to the block rather than within it would hide the Print button
on screen as well — the entire affordance — and would look almost identical in review.

#### The `MY NOTE` label — decided

`_note_card.html` gains a print-only element:

```html
<p class="note-card__print-label" aria-hidden="true">{% trans "MY NOTE" %}</p>
```

hidden on screen (`display: none` in the base block) and revealed in the print block. This is chosen
over the two alternatives deliberately: a `::before` with `content` from a custom property makes the
string awkward to translate, and un-hiding the existing `.note-card__on` paragraph would sit directly
on the `.visually-hidden` trap below. A real element is also the only one of the three that the e2e
can measure with `checkVisibility()` and a height threshold.

**Blast radius.** `_note_card.html` is included by exactly two templates, `_block_notes.html` and
`_unanchored.html` — **both on the lesson page**. (`course_notes.html` and the notes hub use a
different template, `_readonly_note_card.html`, which is untouched.) So the card-level print changes
do not reach the hub or the outline, and no scoping selector is needed.

#### The absolute date

`.note-card__meta` renders `added 3 days ago` / `edited 3 days ago` via `timesince`, which is
meaningless on paper read weeks later. Both phrasings already read **`note.updated`** —
`note.created` is never rendered — so the print date uses `note.updated` too, for consistency with
the relative form beside it:

```html
<span class="note-card__print-date">{{ note.updated|date:"SHORT_DATE_FORMAT" }}</span>
```

Localised by Django's `L10N` / `DATE_FORMAT` machinery, **not** through `gettext`: a date *format* is
not a translatable message, and routing it through the catalogue is the easily-wrong choice. Hidden
on screen, revealed in print; the relative `timesince` form is hidden in print so the two never
appear together.

### 4. Dark theme — fixed in CSS, site-wide

`tokens.css:79` defines `[data-theme="dark"]` with `--text-primary: #F2EFE9` (near-white). **No**
print rule anywhere resets the theme, and `print-color-adjust` appears nowhere in the repo. Browsers
strip backgrounds by default when printing. So a dark-theme student printing a lesson today gets
near-white text on white paper — a blank page.

**The mechanism is richer than "an attribute from `user.theme`."** `base.html:4–5` renders both
`data-theme` and `data-theme-pref`; a prepaint script (`base.html:17–26`) overwrites `data-theme`
from `matchMedia("(prefers-color-scheme: dark)")` when the pref is `auto`, falling back to a
`libli_theme` cookie when the attribute is absent, and `ui.js` rewrites both on toggle. What is true
is that `tokens.css` itself contains no `prefers-color-scheme` query — the resolved theme always
arrives as the `data-theme` attribute.

**The fix is a `@media print` override in `tokens.css`** that re-declares the dark block's
surface / text / border tokens to their light values, rather than a JS stash-and-restore in
`print.js`. Three reasons, each of which the JS route fails:

1. **It reaches the no-JS route.** §5 offers `?notes=1` + `Ctrl+P` as the supported no-JS path; with
   JS off, `print.js` never runs, so a JS-only theme fix would print §4's blank page for exactly
   those users.
2. **It reaches every page.** `print.js` loads only from `lesson_unit.html`. A JS fix would leave the
   quiz page, the course outline and the notes hub printing white-on-white — an inconsistency a later
   reader would read as intentional.
3. **It needs no restore**, so it cannot be left half-applied by an `afterprint` that never fires.

The cost is that the light token values are stated twice. That is pinned by a test asserting the
print block's values match the `:root` values token-for-token, so the two cannot drift silently.

This is a pre-existing, site-wide defect pulled into this branch because shipping a Print button that
yields a blank page for every dark-theme student would be shipping a broken feature. It remains
separable: the notes work stands without it.

### 5. Degradation (no JS)

With JS off, `notes.js` never adds `.notes-js`, the panels stay closed, and the Print button is
hidden by the `html.js` gate in §1 rather than rendered dead.

The no-JS route is the existing `?notes=1` query parameter, which **already works today**:
`_block_notes.html` server-renders `<details … open>` when `notes_show` is set and the block has
notes, so `…/u/<pk>/?notes=1` followed by `Ctrl+P` prints a lesson with its notes open, with no JS at
all. Because §4's theme fix is CSS, this route is correct in dark theme too. No new server-side work
is required for it.

### 6. i18n

Two new user-visible strings — `Print` (§1) and `MY NOTE` (§3) — go through `{% trans %}` and into
the `pl` catalogue via `makemessages`. The absolute date is **not** on this list: it is a Django
format, not a msgid (§3).

Two known hazards apply: `makemessages` pre-fills fuzzy entries with a **wrong** translation, and
clearing one requires deleting **both** the `#, fuzzy` marker and the bogus `msgstr`; and the binary
`.mo` must be regenerated at the end rather than carried stale through a long branch.

## Data flow

Nothing is persisted, and no request is made. There is no new view, no new URL, no new model field
and no migration. The whole feature is client-side, over markup the server already renders:

```
student clicks Print  ─┐
                       ├─→ window.print()
student presses Ctrl+P ─┘        │
                                 ▼
                         'beforeprint' (or matchMedia("print") change)
                                 │
                  ┌──────────────┴───────────────┐
                  ▼                              ▼
        open the closed panels that       record exactly which
        contain a .note-card, plus        elements were opened
        .unanchored-notes > details
                                 │
                                 ▼
                  (notes.js's capture-phase toggle handler MAY run,
                   now or later or never — §2c: positionPop stamps an
                   inline top, setupClamp clamps bodies to 6 lines)
                                 │
                                 ▼
                @media print in notes.css undoes both, order-independently,
                at (0,4,0)+/!important; hides handle / actions / composer /
                add-more / add-label; resets is-dimmed / is-highlighted;
                reveals the MY NOTE label and the absolute date.
                @media print in tokens.css supplies the light palette.
                                 │
                                 ▼
                       browser paints the sheet
                       (or writes the PDF)
                                 │
                                 ▼
                         'afterprint' (or matchMedia leave)
                                 │
                    close exactly the panels we opened; strip
                    .note-card__body--clamp and .note-card__more
                    from inside them. Theme needs no restore —
                    it was never mutated.
```

## Error handling

- **`afterprint` never fires** (a known browser inconsistency, notably on a cancelled print job). The
  page would be left with panels open and clamp residue inside them. Mitigation: drive the leave path
  from the `matchMedia("print")` change event as well, which is the more reliable signal on Safari,
  and make both paths idempotent so a double-fire is harmless. Because the theme is CSS-only, no
  palette state can be stranded.
- **The toggle side effects never ran** (§2c). The `afterprint` cleanup removes classes and elements
  that may not exist; it must be written as a no-op in that case, not an error.
- **A student had panels open before printing.** Handled by construction: `print.js` records only the
  panels it opened itself, and restores and de-clamps only those.
- **No JS.** The button is hidden rather than dead, and `?notes=1` is the working alternative (§5).
- **A unit with no notes.** The button still prints, producing the lesson exactly as it prints today.
  Because the sweep is filtered on `.note-card`, no note-less panel is opened and no "Add a note"
  furniture is emitted.

## Testing

The house rule applies: **falsify the tests, do not merely run them.** Each assertion below is paired
with the mutant that must turn it RED, chosen from the failure mode it is meant to catch.

### How print state is entered in a test — pin this first

`page.emulate_media(media="print")` **only** re-evaluates CSS media queries. It does **not** dispatch
`beforeprint`, and `window.print()` is a no-op in headless Chromium. So neither one alone can drive
these tests, and a test that conflates them cannot falsify anything:

- **CSS-only assertions** (the print block's effect) need `emulate_media` alone.
- **JS-lifecycle assertions** (panels opening/closing) need an explicit
  `page.evaluate("window.dispatchEvent(new Event('beforeprint'))")` — and `afterprint` likewise.

Because §2 specifies **two** dispatchers (the `beforeprint`/`afterprint` events *and* the
`matchMedia("print")` change), a single-dispatcher mutant survives any test that does not name its
trigger. Each lifecycle assertion below therefore states its dispatcher, and the two dispatchers get
one assertion each so that each mutant kills exactly one test.

### e2e — `tests/test_e2e_print_lesson_notes.py` (new, `pytestmark = pytest.mark.e2e`)

Fixtures follow the pattern already proven in `tests/test_e2e_notes.py`: allauth
`input[name='login']`, `TEST_PASSWORD`, `seed_roles()`, `published=True` on the unit.

| # | Assertion | Trigger | Mutant that must make it RED |
|---|---|---|---|
| 1 | A note body is **genuinely visible** after the print-enter path | explicit `beforeprint` dispatch | delete the `beforeprint`/`afterprint` listener registration |
| 2 | Same, via the media route | `matchMedia("print")` change | delete the `matchMedia` listener registration |
| 3 | A note body longer than 6 lines prints **in full** | `emulate_media` + `beforeprint` | delete the un-clamp rule |
| 4 | `.block-notes__pop` sits **in flow** at a ≥1200px viewport — *a cascade regression test under emulation, not a claim about paper (§2a)*; fixture must force the `--clamped` state so `right` is exercised | `emulate_media` + `beforeprint` | delete the `position`/`top`/`right` reset, **or** re-write it at (0,1,0) |
| 5 | `.block-notes__handle`, `.note-card__actions`, `.note-composer`, `.block-notes__add-more`, `.block-notes__add-label` are all **not** visible | `emulate_media` | delete the control-hiding rule |
| 6 | A **note-less** block prints no note furniture at all | `emulate_media` + `beforeprint` | drop the `.note-card` filter from the sweep (open every panel) |
| 7 | The **unanchored** notes section prints (fixture: a note whose element was deleted) | `emulate_media` + `beforeprint` | drop `.unanchored-notes > details` from the sweep |
| 8 | The `MY NOTE` label is visible in print and **absent on screen** | `emulate_media` | delete the label reveal rule |
| 9 | The absolute date is visible in print and the `timesince` text is **not** | `emulate_media` | delete the date reveal / relative-hide rule |
| 10 | Blocks are **not** dimmed in print after a note card is focused | focus a card, then `emulate_media` | delete the `.is-dimmed` reset |
| 11 | The Print button is **visible on screen** on the lesson page and **not** in print | screen, then `emulate_media` | move the `.unit-strip__print` rule outside the `@media print` block |
| 12 | A panel the student opened by hand is **still open** after the leave path | `beforeprint` then `afterprint` | make the leave path close all panels rather than only the recorded ones |
| 13 | Panels opened by print **are closed** after the leave path | `beforeprint` then `afterprint` | skip the removal loop |
| 14 | After the leave path, no `.note-card__body--clamp` or `.note-card__more` remains in the panels print opened | `beforeprint` then `afterprint` | skip the de-clamp cleanup |
| 15 | For a dark-theme student, printed text colour is **dark**; fixture must produce `data-theme-pref="dark"`, not `auto` | `emulate_media` | delete the `@media print` token override in `tokens.css` |

Three measurement traps in this repo's history bear directly on assertions 1, 2, 5 and 8, and must be
respected or the tests will pass on a broken build:

- **`bounding_box()` stays non-zero through a closed `<details>`** — measured 52.4×22 for a real
  element inside a closed group — and `querySelectorAll` counts it. The only correct discriminator is
  **`el.checkVisibility()` with no options**, which per spec returns `false` unconditionally when a
  flat-tree ancestor has `content-visibility: hidden`. (It exists in current Playwright Chromium, so
  the e2e needs no feature detection; `unit_nav.js:18`'s guarded pattern is for shipped code.)
- **Playwright reports a `.visually-hidden` element as VISIBLE** (1×1 with a zero clip rect, so its
  bounding box is non-empty). `expect(...).to_be_visible()` on `.note-card__on` therefore cannot
  fail, and `.note-card__on` must never stand in for the note body. Assertions 1, 2 and 8 use
  `checkVisibility()` **plus** a numeric `bounding_box()["height"]` threshold, never bare presence.
- **`wait_for_selector(sel)` defaults to `state="visible"`** and will hang on a clipped-but-present
  element; use `state="attached"`.

### Non-e2e

- **Template test:** `lesson_unit.html` passes `show_print=True`; `quiz_unit.html` and
  `quiz_results.html` do not. Mutant: render the button unconditionally in `_unit_strip.html`. This
  replaces an e2e row — rendering the template proves the absence without a login, a seeded quiz and
  a page load.
- **Token-parity test:** the `@media print` override in `tokens.css` re-declares the dark block's
  tokens to values that match `:root` token-for-token. Mutant: change one value. This is what makes
  §4's duplication safe.
- **CSS deletion tripwire** in `tests/test_notes_presentation.py`: the shipped `notes.css` contains
  the print block. Framed as a *wholesale-deletion* tripwire only — a substring assertion cannot
  detect the specificity failure the §3 table warns about, since a rule can be present and inert.
  Cascade-level confirmation comes from the e2e A/B (assertion 4 measured with and without the rule),
  per the project rule that a CSS claim needs an A/B, not a measurement.
- **i18n:** the two new msgids reach the `pl` catalogue.

### Not automatically verified

`break-inside: avoid` cannot be observed by `emulate_media`, which does not paginate. It is covered
by the deletion tripwire only, plus a **manual print-preview check in light and dark** before the PR
is opened. This is stated rather than quietly assumed, so the gap is visible.

### Test-run mechanics

`-m e2e` is mandatory or the e2e tests deselect and the run exits 5; the test-DB container must be
started first; `pytest`'s exit code can report 0 with failures present, so the summary line must be
grepped rather than the exit code trusted. Runs stay scoped to the affected tests, not the whole
suite.

Edits to existing comments (e.g. `courses.css:2102`, which enumerates what print hides and should
gain `.unit-strip__print`) must be **line-count neutral**, so the many line-number citations in
neighbouring comments and in this spec do not rot.
