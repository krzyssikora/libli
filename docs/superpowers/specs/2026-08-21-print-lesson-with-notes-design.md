# Print lesson with notes

A student who has worked through a lesson — and annotated it — can print that lesson, or save it as
a PDF, **with their own notes on the page**.

**Prerequisite: `2026-08-21-lesson-print-foundations-design.md`** must be merged first. It fixes two
pre-existing print defects (dark theme printing white-on-white; multi-slide lessons printing only the
active slide) that would otherwise make this button ship broken. Nothing here re-states them; the
tests assume they are in place.

## Purpose

**Notes print as nothing.** `notes/static/notes/css/notes.css` is 443 lines and contains the substring
`print` **zero** times. Every note on a lesson page lives inside `<details class="block-notes__panel">`,
closed by default (`notes/templates/notes/_block_notes.html`), and a closed `<details>` hides its
content via the UA rule `::details-content { content-visibility: hidden }` — so the subtree is in the
DOM, counted by `querySelectorAll`, carrying a stale non-zero `getBoundingClientRect()`, and **not
painted**, on screen or on paper.

**There is no affordance.** `templates/courses/_unit_strip.html` holds two things: the tag panel and,
for authors, `Edit unit`.

So: an affordance, a reliable way to get the panels open at print time, and print styling for the
cards.

### Scope

Print and "save to a file" are **one control**. `window.print()` opens the browser's own dialog, whose
destination list already includes *Save as PDF*. No PDF library enters `pyproject.toml`; no
server-side rendering path is built.

**Out of scope:** server-side PDF generation; whole-chapter or whole-course printing; an "include my
notes" toggle; a print affordance on quiz pages; **discoverability of the no-JS route** (§4's
`?notes=1` works if reached directly, but nothing surfaces it — a separable follow-up). The tag
panel's `🏷` emoji in the unit strip is a pre-existing blemish this feature neither introduces nor
worsens; left alone.

**Every new CSS rule this spec adds to `courses.css` is appended at the end of the file**, so no
existing line citation shifts.

## Architecture

### 1. The affordance — `templates/courses/_unit_strip.html`

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

`btn--small`, **not** `btn--sm`: only `.btn--small` is defined (`app.css:50`). Monochrome
`currentColor` SVG with `aria-hidden`/`focusable="false"`, matching the Edit icon beside it.

`_unit_strip.html` is included by **three** templates — `lesson_unit.html`, `quiz_unit.html`,
`quiz_results.html` — and only the first renders notes. So `lesson_unit.html` alone passes
`{% include "courses/_unit_strip.html" with show_print=True %}`; the quiz templates change by zero
lines. Quiz print has never had a design pass and printing a quiz mid-attempt is a different feature.

**No-JS gate, and the cascade trap it creates.** The button's only behaviour is `window.print()`, so
with JS off it is a dead control. `base.html:15` already adds `js` to `documentElement`, so:

```css
/* appended to the end of courses.css */
.unit-strip__print { display: none; }
html.js .unit-strip__print { display: inline-flex; }
/* Must match the gate at (0,2,1) AND follow it in source order: at (0,1,0) the gate wins
   and the button prints on paper. The .unit-strip__edit precedent at :2308 is (0,1,0) only
   because nothing gates it. */
@media print { html.js .unit-strip__print { display: none; } }
```

### 2. The mechanism — `courses/static/courses/js/print.js` (new)

An IIFE loaded `defer` from `lesson_unit.html` after `notes.js` (line 79) and `slideshow.js` (line 81).
That placement is **convention, not a dependency** — `notes.js` registers its capture-phase `toggle`
listener at IIFE top level (`notes.js:530`), so it is bound whatever the order. It lives under
`courses/` because it owns the unit-strip button and the page's print lifecycle.

**Why JS at all.** A print stylesheet cannot open a closed `<details>`: the content is hidden by
`content-visibility` on the UA `::details-content` pseudo-element, which author CSS cannot reliably
override across engines. Adding `open` is the only portable mechanism.

Responsibilities — the ordering of 3→5 is load-bearing:

1. **Wire the button** — `[data-print-lesson]` click → `window.print()`.
2. **Hook `beforeprint`.** Most people press `Ctrl+P` rather than hunt for a button; a printout that
   included notes only via the button would be a trap.
3. **Sweep only panels carrying note content:**

   ```js
   // A textarea's value is not layout, so it reads through a closed <details>.
   // Declared BEFORE use: the .filter() callback runs immediately.
   const hasTypedDraft = p => [...p.querySelectorAll(".note-composer__input")]
                                .some(ta => ta.value.trim() !== "");

   panels = [...document.querySelectorAll(".block-notes__panel:not([open])")]
              .filter(p => p.querySelector(".note-card, .note-composer--edit, .note-delete-confirm")
                        || hasTypedDraft(p));
   ```

   plus `.unanchored-notes > details` when present and closed. `_block_notes.html` renders an
   `<aside>` for **every** block, so an unfiltered sweep would leave every note-less block with a
   stray `open` attribute and an empty pop in the print tree.

   `.note-composer--edit` in that list is **redundant**, kept only for readability: `notes.js:286–290`
   builds the edit textarea with `.note-composer__input` and the note's own text, so `hasTypedDraft`
   already matches it — dropping it is therefore not a falsifiable mutant (row 9b). The
   `hasTypedDraft` arm is *not* redundant with `.note-composer--has-draft`: that class is applied by
   the enter path, so it cannot be a filter input.
4. **Record what it opened** in a module-local **`Set` of nodes**, so a panel the student had already
   opened is never closed behind their back.
5. **Then — strictly after 3–4 — re-derive draft marks and stamp textarea heights.** A textarea inside
   a still-closed `<details>` is under `content-visibility: hidden`, so its layout is skipped and
   `scrollHeight` reads `0`; stamping before opening writes `height: 0px`.
6. **Restore on the leave path** — remove `open` from the recorded nodes, clear the Set, undo the
   `setupClamp` residue (§2c), clear stamps and marks. Every step must be a **no-op when the thing it
   removes is absent**, never an error.
7. **Two dispatchers, no mode flag.** Safari fires `beforeprint`/`afterprint` unreliably, so
   `matchMedia("print")` change events drive the same handlers, routed on `e.matches`.

   **There is deliberately no `entered` boolean.** A flag cleared only on leave becomes a trap: if
   *neither* leave dispatcher fires, it sticks `true` and every later print silently sweeps nothing.
   Idempotence falls out of the data structures instead — enter only queries `:not([open])`, so a
   second enter finds its work done; leave drains the Set, so a second leave iterates an empty one.

#### 2a. `positionPop` writes an inline `top` — a cascade hazard, not a paper defect

`notes.js` listens for `toggle` in the **capture phase** (`:531`) and on open calls `positionPop`,
which sets `pop.style.top = handle.offsetTop + "px"` (`:524`) and may add `.block-notes__pop--clamped`.

The absolute positioning lives in `@media (min-width: 1200px)` (`notes.css:90`). When a browser
actually prints, media queries evaluate against the **page box** — ~794 CSS px for A4 — so that query
is **false**, the pop is already `position: static`, and an inline `top` on a static box is inert. **On
paper this trap does not fire.** It fires under Playwright's `emulate_media`, which switches media type
while keeping the screen viewport. The reset is kept as cheap insurance and as a cascade regression
test; its assertions measure the cascade under emulation, not paper.

No leave-path cleanup is needed for it: `positionPop` clears both `pop.style.top` and the `--clamped`
class at the top of every run (`notes.js:518–519`) and re-runs on open and resize, so it self-heals.

#### 2b. Transient states: a note being edited or deleted is not a `.note-card`

`notes.js` replaces the card in two states:

- **Edit** — `card.replaceWith(form)` (`:316`) builds `form.note-composer.note-composer--edit` holding
  the note's text; restored by `form.replaceWith(card)` on cancel (`:309`).
- **Delete** — `card.replaceWith(confirm)` (`:336`) builds `div.note-delete-confirm` with a prompt and
  Yes/No. **It does not contain the note body.**

The sweep admits both, so sibling notes still print. §3 must not blanket-hide `.note-composer`, or a
student who presses `Ctrl+P` mid-edit loses that note. **The mid-delete note's text cannot print** —
it is not in the DOM, and `notes.js` holds the detached card in a closure `print.js` cannot reach. The
confirm strip is hidden so the printout omits that one note cleanly rather than printing "Delete? Yes
/ No". A knowing, documented loss, bounded to a two-click transient state.

#### 2c. `setupClamp` truncates long notes, and leaves DOM residue

The same `toggle` handler calls `setupClamp` (`notes.js:97`), which adds `.note-card__body--clamp`
(`-webkit-line-clamp: 6; overflow: hidden`, `notes.css:186`), **measures, and removes it again** for
bodies that fit (`:104–106`), appending a `<button class="note-card__more">` to those that overflow.
The residue is therefore exactly *the overflowing bodies plus their buttons* — and the leave-path
cleanup is scoped to that set, no wider.

- **In print:** every note past six lines would be silently truncated. Undone in CSS (§3).
- **After print:** the classes and buttons persist in the live DOM once panels close and the print CSS
  no longer applies. The leave path removes them from **the panels `print.js` opened** — panels the
  student opened by hand were clamped by their own gesture and are left alone.

#### 2d. `toggle` is asynchronous

The HTML spec queues the `<details>` toggle event; it does not fire synchronously on assignment.
Whether it runs before the print snapshot is engine-dependent, so `positionPop` / `setupClamp` may run
during the print pass, after it, or never. Two consequences: the §2a mitigation must be **CSS**, which
applies whenever the declarations land; and **no test may assert that the toggle side effects
happened** — tests needing the residue inject it.

### 3. The print stylesheet — a new `@media print` block at the end of `notes.css`

#### Specificity is the load-bearing constraint

`@media print` adds **no** specificity (`courses.css:1346` records this). The rules being undone:

| Rule to undo | Selector | Weight |
|---|---|---|
| add-composer hide, read-first (`notes.css:181–182`) | `.notes-js .block-notes__pop--has-notes:not(.is-adding) .note-composer:not(.note-composer--edit)` | (0,5,0) |
| pop floats into the margin (`notes.css:90–107`) | `.notes-js .block-notes__panel[open] .block-notes__pop` | (0,4,0) |
| pop clamped right (`notes.css:109–112`) | …`.block-notes__pop--clamped` | (0,4,0) |
| "Add another note" reveal (`notes.css:177`) | `.notes-js .block-notes__pop--has-notes .block-notes__add-more` | (0,3,0) |
| focus highlight (`notes.css:278`, `:284`) | `.lesson-block.is-highlighted` / `.is-dimmed` | (0,2,0) |
| Print button's no-JS gate (§1) | `html.js .unit-strip__print` | (0,2,1) |
| unanchored summary padding (`notes.css:270`) | `.unanchored-notes summary` | (0,1,1) |
| inline `top` from `positionPop` | — | inline |

A print rule that must beat one of **these** is inert at (0,1,0) regardless of source order, and a
mutant written at that weight is equally inert and will mislead. Where weights tie, source order
decides and must be pinned. Note `[attr]` counts in the class column — miscounting it is how an inert
rule gets written.

This is **not** a blanket claim about print rules: the un-clamp rule below is (0,1,0) and works
*because* of source order, tying `notes.css:186` and winning by sitting later in the same file. That
is the one deliberate equal-weight case, safe only because the print block is pinned to the end.

If a `.visually-hidden` element is ever revealed in print, **all nine** declarations must be reset —
the class is defined three times (`app.css:1384` six; `notes.css:4` and `tags.css:6` nine each, adding
`padding: 0`, `margin: -1px`, `border: 0`) and `lesson_unit.html` loads all three. §3 avoids needing
this by using a real element for the label.

#### Scoping — per rule, not per file

`_note_card.html` is included by `_block_notes.html` and `_unanchored.html`, both inside
`<article class="lesson">`. **But the print block is written against classes**, and
`notes/templates/notes/course_notes.html` — the notes hub — also loads `notes.css` and renders
`.note-card`, `.note-card__body`, `.note-card__meta` via `_readonly_note_card.html`. So:

- **Rules that hide or replace content are scoped to `.lesson`.**
- **Rules that restore content are NOT scoped.** `notes.js:576–578` runs `setupClamp` on the hub too,
  so a `.lesson`-scoped un-clamp would leave the hub printing every long note truncated at six lines.

**Scope a hide, globalise an un-hide** — with one exemption: a reveal may carry the scope when its
element only exists inside a lesson anyway (`.note-card__print-date`, `.note-card__print-label`),
where it is inert rather than wrong.

#### The block must

- **Return the pop to flow**, written **verbatim as
  `.notes-js .block-notes__panel[open] .block-notes__pop`** — matching the original (0,4,0) exactly and
  winning by end-of-file source order. Reset every property that rule sets: `position`, `top`
  (`!important`, per the inline style), `left`, `right`, `width`, `margin-top`, `padding`,
  `background`, `border`, `border-radius`, `max-height`, `overflow-y`, `z-index`, `box-shadow`.
  `right` is named because `--clamped` sets `left: auto; right: 0` — resetting `left` alone leaves it.
- **Un-clamp bodies (unscoped):** `.note-card__body--clamp { display: block; -webkit-line-clamp: none;
  overflow: visible }`, and hide `.note-card__more`.
- **Hide every control except a note being edited or drafted:** `.note-card__actions`,
  `.block-notes__add-label`, `.note-delete-confirm`, **`.block-notes__add-more`** — which must be
  written `.lesson .block-notes__pop--has-notes .block-notes__add-more` at (0,3,0) or carry
  `!important`, since a plain `.lesson .block-notes__add-more` at (0,2,0) loses to its screen reveal —
  and
  `.note-composer:not(.note-composer--edit):not(.note-composer--has-draft):not(:has(.note-composer__error))`.

  The three `:not()`s spare, respectively: a note mid-edit (§2b); a **typed but unsaved draft**, marked
  by `print.js` because **CSS cannot see a textarea's value** (typing changes `value`, not DOM
  children, so `:empty`/`:has()` are blind); and the **no-JS error composer**, which
  `_block_notes.html` re-renders open with the student's rejected text. That last carve-out is a
  **no-JS guarantee only** — with `.notes-js` present, `notes.css:181–182` already hides that composer
  at (0,5,0), which no rule here attempts to beat.

  For every surviving composer, hide `.note-composer__actions` and print `.note-composer__input`
  readably — see the textarea note below.
- **Reset the focus highlight.** `notes.js` adds `.lesson-block.is-highlighted` (background + outline)
  to one block and `.is-dimmed` (`opacity: .45`) to every other on hover/focus, clearing only on blur.
  A student who clicks a note then presses `Ctrl+P` would print most of the lesson at 45% opacity and
  one block visibly ringed — outlines, like borders, survive the strip-backgrounds default. Both rules
  are (0,2,0), so a (0,1,0) neutralisation is inert.
- **Hide a pop with nothing in it:**

  ```css
  .lesson .block-notes__pop:not(:has(
      .note-card, .note-composer--edit, .note-composer--has-draft, .note-composer__error)) {
    display: none;
  }
  ```

  `.note-composer--has-draft` and `.note-composer__error` **must** be in that list: `_block_notes.html`
  renders a composer for every block, note-less ones included, and re-opens the panel with a rejected
  `note_error` draft on note-less blocks too — without them this rule hides the pop and both carve-outs
  above buy nothing. `.note-delete-confirm` is deliberately **out**, so a block whose only note is
  mid-delete loses its pop entirely, which is what §2b's "omitted cleanly" means.

  **How to assert it:** the residual box on the mutant build is **zero-height** (the pop's border and
  padding come only from the ≥1200px block, which the reset above zeroes anyway) — `bounding_box()`
  returns `height: 0` and `checkVisibility()` returns `true`. Rows 8a/9c must use `checkVisibility()`,
  never a height threshold, which passes on both builds.
- **Keep the card, keep the rail.** `.note-card` already carries
  `border-left: 4px solid var(--note-accent)` with eight per-block hues bound via `data-colour`. Print
  keeps it — borders paint even when backgrounds are stripped — and adds `break-inside: avoid`.
- **Suppress both `<summary>` elements** with `visibility: hidden; height: 0; padding: 0; margin: 0;
  border: 0; overflow: hidden` — **not** `display: none`, since engines differ on whether a `<details>`
  renders its children when the summary is not rendered, and that `<details>` is load-bearing for the
  unanchored section printing at all. The full reset matters, and the two have **different
  competitors**: `.block-notes__handle`'s padding is its own (0,1,0) rule (`notes.css:59`), but
  `.unanchored-notes__handle` has **no rule of its own** — its padding comes from
  `.unanchored-notes summary` at **(0,1,1)** (`notes.css:270`), so a (0,1,0) suppression loses the
  padding and, with `box-sizing: border-box`, a `height: 0` box still measures 8px. The `.lesson` scope
  is **load-bearing** there: `.lesson .unanchored-notes__handle` is (0,2,0).
- **Fix `.block-notes`'s negative margin.** `notes.css:45` sets `margin-top: -.85rem` to pull the
  screen affordance against its element; with the handle gone that drags the note card over the block
  it annotates. Print sets `margin-top: .35rem; margin-bottom: .75rem`.
- **Flatten the unanchored container** (dashed border, raised background) to a plain rule; its notes
  print as ordinary cards at the end, provenance carried by the label.

#### The textarea, which `height: auto` does not fit

Both composers render `<textarea rows="3" maxlength="5000">` (`_composer.html:6`; `notes.js:288` sets
`ta.rows = 3`). A textarea's intrinsic block size derives from `rows`, so `auto` resolves to three rows
with the remaining ~4900 characters scrolled out of view — silently defeating §2b. Two mechanisms:

- **`print.js` stamps the measured height** on the enter path — `ta.style.height = ta.scrollHeight +
  "px"` — cleared on leave. "Surviving" is defined **operationally** (a composer carrying `--edit`,
  `--has-draft`, or a `.note-composer__error` descendant), never
  `querySelectorAll(".note-composer__input")`, which would reach note-less panels the sweep never
  opens and stamp `height: 0px` across the lesson. Belt and braces: **skip the stamp when
  `scrollHeight` is `0`.**

  That skip alone would lose every composer on a **non-active slide**. Briefly, since the full
  analysis lives in the prerequisite spec's §3: `slideshow.js` moves slides into a JS-built
  `.slideshow-deck > .slideshow-stage`, non-active ones carry `[hidden]` → `display: none`
  (`courses.css:396`), and `settleHidden` re-adds that attribute after the 320 ms fade.
  `_lesson_article.html:38–47` renders `_block_notes.html` **inside** each `.slide`, so a composer
  there is unmeasurable at `beforeprint`. So when a surviving textarea measures `0` and has a `[hidden]`
  `.slide` ancestor, the enter path **temporarily clears that ancestor's `hidden`, re-measures, and
  restores it synchronously within the same task.**

  The measurement is taken under the *screen* cascade, and the error direction is stated: the printed
  pop is **wider** than the ≥1200px floating pop, so the same text needs fewer lines and the stamp is
  **over-tall, never short**. Over-tall prints trailing whitespace; short would clip words.
  `.note-composer__input` is `box-sizing: border-box` (`notes.css:209`) and inherits `input[type]`
  border/padding, so `scrollHeight` (padding-box) is short by the border width — the print block's
  `border: 0` is what recovers it. **Do not delete that declaration as chrome.**
- **CSS** supplies `field-sizing: content; height: auto; max-height: none; overflow: visible;
  border: 0; resize: none`. `field-sizing` is Chromium-only, so it is progressive enhancement, not the
  mechanism — but it keeps the printout correct if the enter path never ran.

#### Template edits — `_note_card.html`

**A `My note` label**, as the **first child** of `<article class="note-card">`, **outside** the
`{% if note.element_id %}` guard (after the body it reads as a caption; inside the guard it vanishes
from exactly the unanchored notes that need it for provenance):

```html
<p class="note-card__print-label" aria-hidden="true">{% trans "My note" %}</p>
```

Sentence case in the msgid, matching `Add a note` / `Edit note`; the shouting is presentation
(`text-transform: uppercase; letter-spacing: .08em`, the `.ba__side-heading` treatment at
`courses.css:2113`). `display: none` in the base block, revealed in print. A real element rather than a
`::before` with a custom property (awkward to translate) or un-hiding `.note-card__on` (the
`.visually-hidden` trap) — and the only one of the three the e2e can measure.

**An absolute date.** `.note-card__meta` renders `added 3 days ago` via `timesince`, meaningless on
paper weeks later — and **the relative text is a bare text node**, so no selector can target it. Hence
the template edit:

```html
<p class="note-card__meta">
  <span class="note-card__meta-rel">{% if note|note_edited %}…{% else %}…{% endif %}</span>
  <span class="note-card__print-date">{% if note|note_edited %}{% blocktrans with date=note.updated|date:"SHORT_DATE_FORMAT" %}edited {{ date }}{% endblocktrans %}{% else %}{% blocktrans with date=note.updated|date:"SHORT_DATE_FORMAT" %}added {{ date }}{% endblocktrans %}{% endif %}</span>
</p>
```

The verb is kept: hiding `.note-card__meta-rel` would otherwise leave a naked `21.08.2026` with no
indication whether it is a creation or last-edit date. Both phrasings already read `note.updated`
(`note.created` is never rendered). The **date** is localised by Django's `L10N`/`DATE_FORMAT`, never
by `gettext`; only the verb is a msgid.

Both halves need a rule: base block `.note-card__print-date { display: none }` — without it every card
on screen reads "added 3 days ago 21.08.2026" — and, in print scoped to `.lesson`,
`.note-card__meta-rel` hidden, `.note-card__print-date` revealed. `_readonly_note_card.html` (the hub)
is not edited and has **no `.note-card__meta-rel` at all**, so that scope is **defensive, not
load-bearing** — a mutant removing it is dead.

### 4. Degradation (no JS)

`notes.js` never adds `.notes-js`, panels stay closed, and the button is hidden by the `html.js` gate
rather than rendered dead. The working route is `?notes=1`, which **already works today**:
`_block_notes.html` server-renders `<details … open>` when `notes_show` is set and the block has notes.
Nothing surfaces it (§Scope). No new server-side work.

### 5. i18n

**Three** new msgids: `My note`, `added %(date)s`, `edited %(date)s`. `Print` is **not** new —
`msgid "Print"` exists at `locale/pl/LC_MESSAGES/django.po:5231` (`msgstr "Drukuj"`); `makemessages`
only adds a source reference. Translations: `Moja notatka`, `dodano %(date)s`, `edytowano %(date)s`.

**The fuzzy hazard is at its maximum here:** the catalogue already carries `added %(when)s ago`
(`:3210`) and `edited %(when)s ago` (`:3204`), near-identical strings, so `makemessages` will likely
pre-fill the new entries with those wrong translations — and clearing one requires deleting **both**
the `#, fuzzy` marker and the bogus `msgstr`. Each new `blocktrans` carries a `{# Translators: … #}`
comment saying the placeholder is a date. Regenerate the binary `.mo` at the end rather than carrying a
stale one.

## Data flow

Nothing is persisted and no request is made — no new view, URL, model field or migration.

```
click Print ─┐
             ├─→ window.print()
Ctrl+P ──────┘        │
                      ▼
   'beforeprint' OR matchMedia("print") change (matches === true)
                      │
   open closed panels containing .note-card / --edit / .note-delete-confirm
   / a typed textarea value, plus .unanchored-notes > details;
   add each to the Set
                      │
                      ▼  (strictly after opening — §2 step 5)
   re-derive .note-composer--has-draft; stamp each surviving textarea
   (measuring through a [hidden] slide where needed); record in a second Set
                      │
        (notes.js's capture-phase toggle handler MAY run, now or later or
         never — §2d: positionPop stamps an inline top; setupClamp clamps)
                      │
                      ▼
   @media print in notes.css undoes both, order-independently, at
   (0,4,0)+/!important; hides controls; resets the highlight; reveals the
   label and absolute date. courses.css hides the Print button at (0,2,1).
                      │
                      ▼
          browser paints the sheet (or writes the PDF)
                      │
                      ▼
   'afterprint' OR matchMedia change (matches === false)
                      │
   close exactly the nodes in the Set; strip clamp residue from inside them;
   clear stamps and marks; clear both Sets. positionPop's residue self-heals.
```

## Error handling

- **The leave path never fires** (notably on a cancelled print job). Either dispatcher restores the
  page. If **neither** arrives, panels stay open and the clamp residue remains — visible but harmless
  and self-correcting, because there is no mode flag: the next print still sweeps correctly.
- **The toggle side effects never ran** (§2d). The cleanup removes things that may not exist; it must
  be a no-op, never a throw — a throw would abort the restore half-done.
- **A student had panels open before printing.** `print.js` records only what it opened.
- **Mid-edit / mid-draft.** The composer survives the hide and its textarea prints as text.
- **Mid-delete.** Text is not in the DOM and cannot print; the confirm strip is hidden so the note is
  omitted cleanly. Documented loss (§2b).
- **A unit with no notes.** Prints exactly as today; the filtered sweep opens nothing.

## Testing

Falsify, don't merely run: each assertion is paired with the mutant that must turn it RED.

### Entering print state — pin this first

`emulate_media(media="print")` re-evaluates CSS media queries **and**, measured in this repo's
Chromium, delivers a `matchMedia("print")` change with `matches === true`, observable on the next
`evaluate`. It does **not** dispatch `beforeprint`, and `window.print()` is a no-op headless.

Consequences:

- Anything inside `.block-notes__pop` (i.e. inside `::details-content`) needs the panels open, or
  `checkVisibility()` is `false` on a **correct** build.
- **`emulate_media` runs the enter path.** A row proving the `beforeprint` listener exists must not
  call it first, or the mutant is rescued by the media route. Row 1 therefore asserts **on screen**
  with no `emulate_media`. A row needing *no* enter path must block `print.js` from loading
  (`page.route("**/print.js", lambda r: r.abort())`), not merely withhold a dispatch.
- Never `mql.dispatchEvent(new Event("change"))` — it carries no `matches`, so the handler takes the
  *leave* path and goes red on a correct build. A `MediaQueryListEvent` carrying `matches` is fine.
- Reads after `emulate_media` are **polling** (`expect(...).to_pass()`), since the listener is async.

Markers: *(event)* — killed by deleting the `beforeprint`/`afterprint` registration: rows **1, 7d, 9,
9b, 9d, 16c, 18, 19, 20, 20b**. *(media)* — row **2** only. *(shared)* — rows **10** and **17** depend
on sweep/restore logic, not on which listener ran. *(CSS)* — depend only on the stylesheet.

### The suite is Chromium-only, which shapes three rows

`conftest.py` uses the stock `pytest-playwright` `page` fixture with no browser parametrisation. The
textarea fit has two implementations by design — the stamp (every engine) and `field-sizing`
(Chromium) — and on Chromium they are **mutually rescuing**: delete either and the other still renders
full height. So no rendered-height assertion falsifies either alone. Resolution: row 7 lists a
**combined** mutant; the stamp is falsified by **asserting the mechanism** (row 7d, a non-empty inline
`style.height`) — a deliberate step down to implementation level, taken because the behavioural
difference is Firefox/WebKit-only; row 7c isolates the CSS by blocking `print.js` entirely.

### e2e — `tests/test_e2e_print_lesson_notes.py` (new, `pytestmark = pytest.mark.e2e`)

Fixtures follow `tests/test_e2e_notes.py`: allauth `input[name='login']`, `TEST_PASSWORD`,
`seed_roles()`, `published=True`.

| # | Assertion | Trigger | Mutant that must make it RED |
|---|---|---|---|
| 1 | A note body is visible **on screen** after the event route | `beforeprint` only *(event)* | delete the `beforeprint`/`afterprint` registration |
| 2 | A note body is genuinely visible | `emulate_media` only, polling *(media)* | delete the `matchMedia` registration |
| 3 | Clicking the **real button** calls `window.print()` (stubbed via `add_init_script`) | real click | delete the click listener |
| 4 | A note body longer than 6 lines prints in full. Fixture **injects** `.note-card__body--clamp` after the enter path — §2d forbids waiting for `setupClamp`, which measures *after* adding the class (`notes.js:104`) and would remove it again with the un-clamp rule live | `beforeprint`, inject, `emulate_media` *(CSS)* | delete the un-clamp rule |
| 5a | `.block-notes__pop` is `position: static` at a ≥1200px viewport | `beforeprint` then `emulate_media` *(CSS)* | delete the reset; write it at (0,1,0); **or** as `.lesson details[open] .block-notes__pop` (0,3,1). *Not* `.lesson .block-notes__panel[open] .block-notes__pop` — that is also (0,4,0) and wins |
| 5b | An injected inline `top` is overridden | fixture sets `pop.style.top`, then enter *(CSS)* | drop `!important` from the `top` reset |
| 5c | `right: 0` from `--clamped` is overridden | fixture adds the class, then enter *(CSS)* | delete the `right` reset |
| 6a | `.note-card__actions` and `.block-notes__add-more` are not visible (`checkVisibility()` — both are `display: none`) | `beforeprint` then `emulate_media` *(CSS)* | delete the control-hiding rule; **separately**, write the add-more hide at (0,2,0) |
| 6a2 | `.block-notes__handle` has `bounding_box()["height"] == 0`. **Not** bare `checkVisibility()` — see the traps below | `beforeprint` then `emulate_media` *(CSS)* | delete the summary suppression |
| 6b | A composer made visible via *Add another note* and left **empty** is not visible. *Driven through `.is-adding`: otherwise `notes.css:181–182` hides it at (0,5,0) and the row passes on the mutant* | click *Add another note*, then enter *(CSS)* | delete the composer hide |
| 7 | A note **mid-edit** prints in full; the fixture note needs >3 rows and the textarea's `bounding_box()["height"]` exceeds a three-row threshold | open edit, then enter *(CSS + stamp)* | drop `:not(.note-composer--edit)`; **or** delete the stamp *and* the CSS group together |
| 7b | A **typed unsaved draft** prints, on a block that already has notes | *Add another note*, type, then enter | delete the `--has-draft` marking, or its carve-out |
| 7b2 | Same, on a **note-less** block. *Row 7b cannot cover it: Add another note only exists on `--has-notes` pops, whose `:has(.note-card)` keeps the empty-pop rule from firing* | hand-open a note-less panel, type, then enter | drop `--has-draft` from the **empty-pop** `:has()` list |
| 7c | With `print.js` **blocked from loading**, a mid-edit textarea still prints >3 rows | `page.route` abort, edit, `emulate_media` *(CSS)* | delete the CSS `height`/`field-sizing` group |
| 7d | A mid-edit textarea carries a non-empty inline `style.height` | open edit, `beforeprint` *(event)* | delete the `ta.style.height` stamp |
| 8 | Mid-delete: the confirm strip does not print, siblings do | start a delete, then enter *(CSS)* | omit `.note-delete-confirm` from the hide list |
| 8a | A block whose **only** note is mid-delete prints **no pop at all** (`checkVisibility()`) | single-note block, start delete, enter *(CSS)* | add `.note-delete-confirm` to the empty-pop `:has()` list |
| 8b | A **rejected no-JS draft** on a note-less block prints its text | post an invalid note with JS disabled, `emulate_media` *(CSS)* | drop `.note-composer__error` from the empty-pop `:has()` list |
| 9 | A note-less block does **not** carry `open` after the enter path. *DOM state, not paint: §3 hides the furniture anyway, so a paint assertion passes on the mutant* | `beforeprint` *(event)* | drop the filter from the sweep |
| 9b | A **delete-confirm** state on a **single-note** block, then closed, is re-opened. *Both constraints load-bearing: edit state is matched by `hasTypedDraft` (dead mutant), and a sibling `.note-card` would satisfy the filter* | `beforeprint` *(event)* | drop `.note-delete-confirm` from the filter |
| 9c | A note-less panel the student hand-opened prints **no** `.block-notes__pop` (`checkVisibility()`). Does not cover the add-label — see 9e | hand-open, then enter *(CSS)* | delete the empty-pop rule |
| 9d | A typed draft in a note-less panel the student then **closed** is re-opened and prints. *Only the `hasTypedDraft` arm finds it: the native toggle does not clear the textarea, only the Cancel path does (`notes.js:230`)* | `beforeprint` *(event)* | drop the `hasTypedDraft` arm |
| 9e | `.block-notes__add-label` is not visible on a note-less block whose pop **survives**. *Reuse 7b2's fixture; the label has no screen `display: none` (`notes.css:170–175`)* | type in a note-less panel, then enter *(CSS)* | delete the add-label hide |
| 10 | The **unanchored** section prints (fixture: a note whose element was deleted) | `beforeprint` then `emulate_media` *(shared)* | drop `.unanchored-notes > details` from the sweep |
| 10b | `.unanchored-notes__handle` has `bounding_box()["height"] == 0` | `beforeprint` then `emulate_media` *(CSS)* | delete the summary suppression; **separately**, write it at (0,1,0) so `.unanchored-notes summary`'s padding survives |
| 10c | `.block-notes`'s computed `margin-top` is positive | `beforeprint` then `emulate_media` *(CSS)* | delete the margin reset |
| 11 | The `My note` label is visible in print and **absent on screen** | screen, then enter *(CSS)* | delete the reveal, **or** the base-block `display: none` |
| 12 | The absolute date is visible in print and absent on screen; `.note-card__meta-rel` not visible in print | screen, then enter *(CSS)* | delete the base-block hide, **or** the relative-hide rule |
| 13 | The notes **hub** prints long notes un-truncated. *The date half is deliberately absent: the hub has no `.note-card__meta-rel`, so that scope's mutant is dead (§3)* | `emulate_media` on the hub *(CSS)* | add a `.lesson` scope to the un-clamp rule |
| 14 | After focusing a note card, in print: other blocks are not dimmed **and** the focused block's `outline-style` is `none` | focus a card, then `emulate_media` *(CSS)* | delete the `.is-dimmed` reset; **separately**, write the `.is-highlighted` reset at (0,1,0) |
| 15 | The Print button is visible on screen and **not** in print | screen, then `emulate_media` *(CSS)* | write the print rule at (0,1,0) so its own gate wins; **or** move the gate below it |
| 16 | **A note on a non-active slide prints**: after the enter path plus `emulate_media`, a `.note-card__body` on slide 2 passes `checkVisibility()` with a non-zero height. *This is the one place the two PRs interact — the sweep must find `.block-notes__panel` inside a `[hidden]` slide, and the foundations PR's slide reveal must reveal it — and it is exactly what a split loses, because each half looks covered on its own* | multi-slide fixture, await `.slideshow-deck`, `beforeprint`, `emulate_media` *(shared)* | drop the slide reveal from the foundations block; **or** drop the panel from the sweep |
| 16c | A mid-edit note on a **non-active slide** carries a non-empty inline `style.height`. *Asserted on the stamp: with the un-hide deleted the CSS alone still renders full height on Chromium, so a rendered-height assertion would be green on its own mutant. Slide 2 must be `[hidden]` at `beforeprint` — navigating to reach Edit makes it active, so navigate back and wait for `settleHidden`, or inject* | await `.slideshow-deck`, reach the state, `beforeprint` *(event)* | delete the temporary-un-hide step |
| 17 | A hand-opened panel is **still open** after the leave path | `beforeprint`, `afterprint` *(shared)* | make leave close all panels |
| 18 | Panels opened by print **are closed** after leave | `beforeprint`, `afterprint` *(event)* | skip the removal loop |
| 19 | Clamp residue is removed from the panels print opened. Fixture **injects** the residue after the enter path | `beforeprint`, inject, `afterprint` *(event)* | skip the de-clamp cleanup |
| 20 | A cycle with **no residue** leaves the page usable: a second cycle still opens and closes. *The only row exercising the empty-cleanup branch* | two cycles *(event)* | make the cleanup throw when the class is absent |
| 20b | After the first enter the fixture **re-closes one swept panel**; a second enter re-opens it. *The re-close is what makes this falsifiable — otherwise the first enter has opened everything and a flag's early return is invisible* | `beforeprint`, re-close, `beforeprint`, `afterprint` *(event)* | add an `entered` boolean that returns early |

Measurement traps that decide several of these:

- **`bounding_box()` stays non-zero through a closed `<details>`** — measured 52.4×22 — and
  `querySelectorAll` counts it. The correct discriminator is **`checkVisibility()` with no options**,
  which returns `false` unconditionally under `content-visibility: hidden`.
- **`checkVisibility()` with no options returns `true` for `visibility: hidden`** (`visibilityProperty`
  defaults to `false`). It is right for the closed-`<details>` case and **wrong** for the two
  `<summary>` elements §3 suppresses with `visibility` — rows 6a2 and 10b measure the box instead.
  Using one method for both is how a row ends up red on a correct build.
- **Playwright reports `.visually-hidden` as VISIBLE** (1×1, zero clip rect). `.note-card__on` must
  never stand in for the note body; rows 1, 2 and 11 use `checkVisibility()` **plus** a numeric
  `bounding_box()["height"]` threshold.
- **`wait_for_selector` defaults to `state="visible"`** and hangs on a clipped-but-present element —
  use `state="attached"`.

### Non-e2e

- **Template test:** `lesson_unit.html` passes `show_print=True`; the two quiz templates do not.
  Mutant: render the button unconditionally. Replaces an e2e row — the template proves the absence
  without a login and a page load.
- **CSS deletion tripwire** in `tests/test_notes_presentation.py`: the shipped `notes.css` contains the
  print block. A *wholesale-deletion* tripwire only — a substring assertion cannot detect the
  specificity failures §3 warns about, since a rule can be present and inert. Cascade confirmation
  comes from the e2e A/B (rows 5a–c, 15), per the project rule that a CSS claim needs an A/B.
- **i18n:** all three msgids reach the `pl` catalogue with the §5 translations, asserted **non-empty
  and non-fuzzy**. The `Print` half is asserted as a new **source reference** on the existing entry —
  asserting the msgid exists would pass on a build where the `{% trans %}` was never added.

### Not automatically verified

`break-inside: avoid` cannot be observed by `emulate_media`, which does not paginate. Covered by the
deletion tripwire plus a **manual print-preview check in light and dark** before the PR is opened.

### Test-run mechanics

`-m e2e` is mandatory or the e2e tests deselect and the run exits 5; start the test-DB container first;
`pytest` can exit 0 with failures, so grep the summary. Keep runs scoped to the affected tests.
