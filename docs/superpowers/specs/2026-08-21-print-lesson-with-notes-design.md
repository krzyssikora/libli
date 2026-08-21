# Print lesson with notes

A student who has worked through a lesson — and annotated it — can print that lesson, or save it
as a PDF, **with their own notes on the page**.

## Purpose

Today a student cannot do this, and the reason is narrower than it looks.

**Printing a lesson mostly works.** The repo carries **10** `@media print` blocks — 2 in
`core/static/core/css/app.css` (lines 1183, 1913) and 8 in `courses/static/courses/css/courses.css`
(103, 967, 1113, 1349, 1852, 2105, 2308, 2359); three further textual hits are comments
(`app.css:597`, `courses.css:1346`, `courses.css:2411`) and are not blocks. Those blocks encode real
decisions: `.el--tabs` un-hides every `[role="tabpanel"][hidden]` and every carousel slide;
`beforeafterelement` prints both sides and reveals its `.ba__side-heading`; reveal-gates un-hide
their downstream blocks while the gate *buttons* drop out (with `[data-filltablegate]` deliberately
exempted, because a marked fill-table **is the student's work**); `.el--image--*` gets mm height
caps; `.unit-strip__edit`, `.draft-banner__form`, the TOC pin and the scroll-edge gradients all
disappear.

**It has one hole, and this feature falls straight into it** — see §2d: a multi-slide lesson prints
only the active slide.

**Notes print as nothing.** `notes/static/notes/css/notes.css` is 443 lines and contains the
substring `print` **zero** times. `tags.css` likewise has 0 `@media print` blocks. Every note on a
lesson page lives inside `<details class="block-notes__panel">`, closed by default
(`notes/templates/notes/_block_notes.html`), and a closed `<details>` hides its content via the UA
rule `::details-content { content-visibility: hidden }` — so the note subtree is present in the DOM,
counted by `querySelectorAll`, carrying a stale non-zero `getBoundingClientRect()`, and **not
painted**, on screen or on paper.

**There is also no affordance.** `templates/courses/_unit_strip.html` holds exactly two things: the
tag panel and, for authors, `Edit unit`. Nothing anywhere in the student UI offers to print.

So the feature is: an affordance, a reliable way to get the note panels open at print time, print
styling for the note cards, and the two pre-existing print defects (§2d slides, §4 dark theme) that
would otherwise make the new button ship broken.

### Scope

Print and "save to a file" are **one control**, not two. `window.print()` opens the browser's own
dialog, whose destination list already includes *Save as PDF* on Chrome, Edge, Firefox and Safari.
That is a real PDF, produced by the same engine that already renders KaTeX and the lesson's images
correctly. No PDF library enters `pyproject.toml`; no server-side rendering path is built.

**Explicitly out of scope:** server-side PDF generation; whole-chapter or whole-course printing; an
"include my notes" toggle; a print affordance on quiz pages; and **discoverability of the no-JS
route**. That last one is a deliberate, named exclusion rather than an oversight: §5's `?notes=1`
parameter works, but with JS off the button is hidden and nothing surfaces the parameter, so it is
honest to say the route *works if reached directly* — not that it is offered. Adding a `<noscript>`
link or a help-page line is a small, separable follow-up.

### A note on line citations

This spec cites line numbers heavily as its verification surface. **Every new CSS rule it adds to
`courses.css` is appended at the end of the file** (§3), specifically so that no existing line number
— in this spec, in neighbouring comments, or in other specs — shifts. Citations were re-verified
against the worktree at the last revision; they must be re-checked once more when the plan is
written.

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

**The tag panel beside it is left alone, knowingly.** `_unit_strip.html`'s only other content is
`tags/_unit_tag_panel.html`, whose `<summary class="unit-tags__summary">` opens with a literal `🏷`
— a bare emoji against the project's monochrome-SVG convention, printing on every lesson right where
the new button sits, and `tags.css` has no `@media print` block at all. This is a pre-existing
blemish on a sibling element, not something this feature introduces or worsens, so it is named here
and left out of scope rather than quietly swept in — the same treatment §Scope gives the no-JS route.

`_unit_strip.html` is included by **three** templates — `lesson_unit.html`, `quiz_unit.html` and
`quiz_results.html` — and only the first renders notes at all (`_block_notes.html` is reached from
`_lesson_article.html`). Quiz print has never had a design pass, and printing a quiz mid-attempt is
a different feature with different answers. So `lesson_unit.html` alone passes
`{% include "courses/_unit_strip.html" with show_print=True %}`; the two quiz templates change by
zero lines and get no button.

**No-JS gating, the cascade trap it creates, and the source order that resolves it.** The button's
only behaviour is `window.print()`, so with JS off it is a rendered dead control — worse than no
affordance. `base.html:15` already adds a `js` class to `documentElement` in its prepaint script, so
the button is gated on it.

The gate is **(0,2,1)**. The existing print rule beside it — `.unit-strip__edit { display: none; }`
at (0,1,0) — works only because nothing gates `.unit-strip__edit`. A print rule for the new button
written at (0,1,0) would **lose to its own gate** and the button would print on paper. So the print
rule must also be `html.js .unit-strip__print`, at (0,2,1) — and at *equal* specificity the winner is
decided by **source order**, which must therefore be pinned rather than left to chance.

Both rules live together at the end of `courses.css`, gate first, print rule second:

```css
/* ── Print affordance (appended; see the spec's line-citation note) ────────── */
.unit-strip__print { display: none; }
html.js .unit-strip__print { display: inline-flex; }
/* Affordances for a second browser tab and for the print dialog are both noise on
   paper. This must match the html.js gate above at (0,2,1) and follow it in source
   order: at (0,1,0) the gate would win and the button would print. */
@media print { html.js .unit-strip__print { display: none; } }
```

This deliberately does **not** extend the existing `@media print` block at `courses.css:2308`. Doing
so would insert lines mid-file and shift every citation below (see the line-citation note above), and
would separate the print rule from the gate whose source order it depends on. The comment at
`courses.css:2307` stays accurate as-is, describing only `.unit-strip__edit`, and is not edited.

### 2. The mechanism — `courses/static/courses/js/print.js` (new)

A small IIFE in the established style of the other lesson scripts, loaded `defer` from
`lesson_unit.html` **after `notes.js` (line 79) and `slideshow.js` (line 81)**, unconditionally — not
behind a `has_*` flag like its neighbours, because `Ctrl+P` must work on every lesson.

The placement is **convention, not a dependency**, and the spec says so rather than inventing a
mechanism: `notes.js` registers its capture-phase `toggle` listener at IIFE top level
(`notes.js:530`), so it is bound whatever the order, and §2d is pure CSS that `print.js` never
touches. Sitting with the other `courses/js/*.js` lesson scripts is the whole reason. It lives under `courses/` rather than `notes/` because it is a **lesson-page**
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
3. **Sweep only panels that carry note content.** `_block_notes.html` renders an
   `<aside class="block-notes">` for **every** element on the page, whether or not it has notes.
   Opening all of them would leave every note-less block carrying a stray `open` attribute and an
   empty popover box in the print tree. The filter must admit three shapes, because `notes.js`
   *replaces* the card in two transient states (§2b):

   ```js
   // A textarea's value is not layout, so it reads correctly through a closed <details>.
   // Declared BEFORE use: the .filter() callback runs immediately, so a const declared
   // after the panels assignment would throw a TDZ ReferenceError on the first print.
   const hasTypedDraft = p => [...p.querySelectorAll(".note-composer__input")]
                                .some(ta => ta.value.trim() !== "");

   panels = [...document.querySelectorAll(".block-notes__panel:not([open])")]
              .filter(p => p.querySelector(".note-card, .note-composer--edit, .note-delete-confirm")
                        || hasTypedDraft(p));
   ```

   **`.note-composer--edit` in that list is now redundant** and is kept only for readability:
   `notes.js:286–290` builds the edit textarea with `className = "note-composer__input"` and
   `ta.value = body` — the note's own text, never empty — so `hasTypedDraft` already matches every
   edit-state panel. It follows that *dropping `.note-composer--edit` from the filter is not a
   falsifiable mutant*, which the test table must respect (row 9b).

   The `hasTypedDraft` arm is not redundant with `.note-composer--has-draft`: that class is applied
   *by* the enter path, so it cannot be a filter input. It covers the case of a student who opens a
   **note-less** block's panel, types, and closes the panel by clicking the handle — the native
   `<details>` toggle does **not** clear the textarea (only the Cancel/dismiss path does,
   `notes.js:230`), so the text is still there and would otherwise print as nothing. That is the same
   "enter a state, close the panel, `Ctrl+P`" shape row 9b covers for edit and delete.

   plus the `.unanchored-notes > details` when it exists and is closed (it is rendered only when
   `unanchored_notes` is non-empty, and its notes are exactly the ones whose block was deleted — they
   must print, or the printout silently loses them).
4. **Record what it opened** in a module-local **`Set` of nodes**, so a panel the student had
   already opened is never closed behind their back.
5. **Then — strictly after step 3–4 — mark typed drafts and fit every surviving textarea.** The
   ordering is load-bearing, not incidental: a textarea inside a still-closed `<details>` sits under
   `::details-content { content-visibility: hidden }`, so its layout is skipped and `scrollHeight`
   reads `0` or a stale value. Stamping before opening writes `height: 0px` onto the mid-edit
   textarea — precisely the failure this step exists to prevent. The enter path therefore **opens and
   records every panel first, and only then walks the surviving textareas**. A student who clicked *Add another note*
   and typed has an unsaved draft in a plain `.note-composer` — no `--edit` class, no error node.
   **CSS cannot detect it**: typing changes the textarea's `value`, not its DOM children, so
   `:empty` / `:has()` are blind to it. `print.js` therefore **re-derives** `.note-composer--has-draft` on every
   enter — adding it to any composer whose `.note-composer__input` has a non-empty trimmed `value`
   **and removing it from any whose value is empty** — and clears it on leave. Deriving rather than
   only adding matters: the marking is value-based and so runs even where the height stamp is skipped,
   so it is not covered by the stamped-textarea Set, and a stale mark on a since-emptied composer
   would both spare it from §3's hide and satisfy the empty-pop `:has()`, printing the empty bordered
   box row 9c exists to prevent. §3's hide spares that class. Without this a mid-**add** draft is dropped
   twice over — once by the composer hide, once by the empty-pop hide — a third silent loss beside
   the two §2b documents. It then stamps each surviving textarea's height (§3).
6. **Restore on the leave path** — remove `open` from precisely the recorded nodes, clear the Set,
   and undo the `setupClamp` residue (§2c). Every step must be a **no-op when the thing it removes
   is absent** (§2e), never an error.

   **Two different scopes, deliberately.** The clamp cleanup is Set-scoped ("no wider", §2c) because
   a panel the student opened by hand was clamped by their own gesture. The **height stamps and
   `.note-composer--has-draft` marks are not**: `print.js` writes them to every surviving textarea,
   including composers in panels the student had already opened and which the leave path therefore
   never closes. Mirroring the clamp's scoping here would freeze those textareas at their print
   height in the live DOM forever — the same class of residue §2c exists to prevent. So the enter
   path records the textareas it stamped in a **second module-local Set**, and the leave path clears
   from that, independently of which panels were opened.
7. **Two dispatchers, no mode flag.** Safari fires `beforeprint`/`afterprint` unreliably, so
   `matchMedia("print")` change events drive the same enter/leave handlers, routed on `e.matches`
   (`true` → enter, `false` → leave).

   **There is deliberately no `entered` boolean.** An earlier draft used one to make a double-fire
   idempotent, but a flag cleared only on leave becomes a trap: if *neither* leave dispatcher fires —
   the exact case Error handling names — the flag sticks `true` and every subsequent print on that
   page silently sweeps nothing. Idempotence instead falls out of the data structures, with no state
   to strand:

   - **enter** only ever queries `.block-notes__panel:not([open])`, so a second enter finds the
     panels it already opened are open and adds nothing;
   - **leave** drains the Set and clears it, so a second leave iterates an empty Set;
   - a leave arriving with no prior enter is likewise a no-op.

   This is strictly better than the flag: correct under double-fire *and* under a missing leave, with
   no recovery path needed.

The theme is **not** handled here — see §4.

#### 2a. `positionPop` writes an inline `top` — a cascade hazard, not a paper defect

`notes.js` listens for `toggle` **in the capture phase** (`notes.js:531`) and, when a
`.block-notes__panel` opens, calls `positionPop`, which sets `pop.style.top = handle.offsetTop + "px"`
(`notes.js:524`) and may add `.block-notes__pop--clamped`.

**How much this matters depends on the width the media query sees.** The absolute positioning lives
in `@media (min-width: 1200px)` (`notes.css:90`). When a browser actually prints, media queries are
evaluated against the **page box**, which for A4 is roughly 794 CSS px — so `min-width: 1200px` is
**false**, `.block-notes__pop` is already `position: static`, and an inline `top` on a static box is
inert. On paper this trap does not fire.

It fires under **Playwright's `emulate_media(media="print")`**, which switches media-type evaluation
while keeping the screen viewport — so at a ≥1200px test viewport the absolute rule is live and the
inline `top` applies. It would also fire on a very wide printer page box.

The reset is therefore kept as cheap insurance and as a cascade regression test, and the spec is
explicit that its assertions measure the cascade under emulation, **not** a claim about paper.

**Unlike the clamp residue, this residue needs no leave-path cleanup.** `positionPop` clears both
`pop.style.top` and the `--clamped` class at the top of every run (`notes.js:518–519`) and re-runs on
every open and on `resize`, so it self-heals. That asymmetry with §2c is deliberate, not an oversight.

#### 2b. A note mid-edit or mid-delete is not a `.note-card`

`notes.js` replaces the card in **two** transient states, both via the same mechanism:

- **Inline edit** — `card.replaceWith(form)` (`notes.js:316`) builds a
  `form.note-composer.note-composer--edit` holding the note's text in a textarea; the card is
  restored by `form.replaceWith(card)` on cancel (`notes.js:309`).
- **Inline delete** — `card.replaceWith(confirm)` builds a `div.note-delete-confirm` (`notes.js:336`)
  containing a "Delete?" prompt and Yes/No buttons. **It does not contain the note body.**

Consequences:

- The §2 sweep filter admits both, so a panel in either state still opens and its *sibling* notes
  print.
- The §3 control-hiding rule must **not** blanket-hide `.note-composer`, or a student who presses
  `Ctrl+P` mid-edit loses that note entirely. §3 hides
  `.note-composer:not(.note-composer--edit):not(:has(.note-composer__error))` and prints the edit
  form's textarea readably.
- **The mid-delete note's text cannot print**, because it is not in the DOM — `notes.js` holds the
  detached card in a closure `print.js` cannot reach. `.note-delete-confirm` is hidden in print, so
  the printout omits that one note rather than printing a stray "Delete? Yes / No" strip. This is a
  knowing, documented loss, bounded to a two-click transient state; restoring it would mean changing
  `notes.js`'s delete path to hide rather than detach the card, which is out of scope for this
  feature.

#### 2c. `setupClamp` truncates long notes to 6 lines, and leaves DOM residue

The same `toggle` handler calls `setupClamp` (`notes.js:97`), which adds `.note-card__body--clamp` to a
note body — `-webkit-line-clamp: 6; overflow: hidden` (`notes.css:186`) — then **measures and removes
it again** for any body that fits (`notes.js:104–106`), and `insertAdjacentElement`s a
`<button class="note-card__more">` after each body that does overflow. So the residue is exactly *the
overflowing bodies plus their injected buttons*, not every note on the page — and the leave-path
cleanup is scoped to precisely that set, no wider.

Two consequences, both this feature's to fix:

- **In print:** every note longer than six lines is silently truncated — the feature would destroy
  the exact content it exists to preserve. Undone in CSS (§3).
- **After print:** the clamp classes and the injected buttons **persist in the live DOM** once the
  leave path closes the panels, and the print CSS no longer applies to them. The student is left with
  clamped notes and *Show more* buttons they never asked for. So the leave path must also remove
  `.note-card__body--clamp` and any `.note-card__more` from **the panels `print.js` opened** — panels
  the student opened by hand were clamped by their own gesture and are left alone.

#### 2d. Slideshow lessons print one slide — the hole in the existing print story

**This section is written against the DOM as it exists at runtime, not as the server renders it.**
That distinction is the whole difficulty: `slideshow.js:48–56` **moves** every slide out of
`[data-slideshow]` into a JS-built wrapper — `deck = div.slideshow-deck`, `stage =
div.slideshow-stage.scroll-y`, then `stage.appendChild(s)` per slide and
`s.setAttribute("hidden", "")`. The live tree is:

```
[data-slideshow] > .slideshow-deck > .slideshow-stage > .slide
                                   > .slideshow-bar      (JS-built footer, slideshow.js:95)
```

So the three server-side rules that hide slides — `courses.css:348`
(`html.js [data-slideshow] > .slide:not(.is-active)`), `courses.css:355` (the FOUC pre-hide
`html.js [data-slideshow] > .slide:not(:first-child):not(.is-active)`, at (0,5,1)) and the `hidden`
attribute — **stop matching entirely once the deck is built**. `courses.css:361–363` says so in its
own comment: *"Deck slides are display:none at rest … same as the global rules that no longer reach
them."* Any print rule written against `[data-slideshow] > .slide` is inert, and so is any mutant of
it.

The rules actually in force after enhancement are:

| Rule | Effect |
|---|---|
| `.slideshow-deck { overflow: hidden; }` (`courses.css:364`) | clips anything past the stage |
| `.slideshow-stage { position: relative; height: clamp(360px, 62vh, 900px); }` (`courses.css:380`) | fixed-height box |
| `.slideshow-deck .slide { display: block; position: absolute; inset: 0; overflow-y: auto; }` (`courses.css:386`) | slides stack on top of one another |
| `.slideshow-deck .slide[hidden] { display: none; }` (`courses.css:396`) | only the active slide renders |

A multi-slide lesson therefore prints **only the active slide** today, and this feature would
faithfully open note panels on slides that never paint. A student printing an annotated slideshow
lesson would get one slide and a fraction of their notes.

**In scope**, on the same reasoning as §4: shipping a Print button that silently drops most of the
lesson is shipping a broken feature. `display: block` alone is **not** enough — it would leave every
slide absolutely positioned at `inset: 0`, stacked inside a clipping fixed-height box, i.e. still one
visible slide. The carousel precedent at `courses.css:1868–1869` handles exactly this shape by also
neutralising the stage's positioning and height, and §2d mirrors it in full:

```css
@media print {
  .slideshow-deck {
    overflow: visible !important;
    border: 0; border-radius: 0; box-shadow: none; background: none;  /* screen chrome */
    margin-block: 0;
  }
  .slideshow-stage { position: static !important; height: auto !important; }
  .slideshow-deck .slide,
  .slideshow-deck .slide[hidden] {
    display: block !important; position: static !important;
    overflow: visible !important;
    opacity: 1 !important; transition: none !important;
  }
  .slideshow-bar { display: none !important; }
}
```

`opacity: 1 !important` is neither optional nor decorative — but the hazard is the **outgoing**
slide, not the incoming one. `slideshow.js:180` does set `inn.style.opacity = "0"`, but `:186` sets it
back to `"1"` **synchronously, three statements later in the same task**, so no handler or print
snapshot can ever observe `inn` transparent. The declaration that actually persists is
`out.style.opacity = "0"` at **`:187`**, held for the full `FADE_MS = 320` window until
`settleHidden(out)` runs at `:191`. During those 320 ms the outgoing slide is **not yet `[hidden]`**,
so once §2d makes every slide `display: block` it prints as a blank page. A student who clicks Next
and immediately presses `Ctrl+P` lands inside that window.

**`transition: none !important` is required alongside it, and winning the cascade is not enough
without it.** `courses.css:393` puts `transition: opacity 320ms ease` on the *same*
`.slideshow-deck .slide` rule this block overrides. Changing a transitioned property's computed value
starts an animation rather than applying it, so `opacity: 1 !important` on its own makes the outgoing
slide *animate* from ~0 toward 1 over a further 320 ms — and the print snapshot (and any test
measurement) samples at the instant print styles apply, i.e. mid-animation, at a fraction. The
declaration wins and still does not produce an opaque slide. `courses.css:398–400`'s
`@media (prefers-reduced-motion: reduce) { .slideshow-deck .slide { transition: none } }` is the
existing precedent for exactly this shape. Only `!important` beats an inline style — the same rule §3 states
for `positionPop`'s inline `top` — and the carousel precedent carries the identical declaration at
`courses.css:1869`.

The other `!important`s are right too, but not all for the same reason, and the spec states the
actual competitor rather than a blanket one — a false mechanism is exactly the kind of thing that
survives review:

- `.slideshow-deck .slide` / `.slide[hidden]` tie their screen counterparts (`courses.css:386` at
  (0,2,0), `:396` at (0,3,0)) and would win on source order alone, since the print block is appended
  to the end of the same file. `!important` here is order-proof insurance, not a weight requirement —
  the same honest phrasing as the stage bullet below.
- `.slideshow-stage` beats only **single**-class rules — its own at `courses.css:380` and
  **`.scroll-y { position: relative }` at `app.css:1886`**, which `slideshow.js` adds to the stage
  alongside `.slideshow-stage`. Source order alone would win, since the print block is appended to a
  later-loaded sheet. `!important` is kept because it is cheap and order-proof, not because the
  weight demands it — and the `.scroll-y` competitor is why the `position` reset is needed at all. `.slideshow-bar` is hidden on the same principle the carousel block applies to
`.tabs__cbar` / `.tabs__status` (`courses.css:1870`) and the before/after block applies to
`.ba__toggle` — once every slide prints, Prev/Next navigation is meaningless ink.

This block is **appended at the end of `courses.css`** with the §1 print-affordance rules, not
inserted beside the slideshow rules, per the line-citation note.

#### 2e. `toggle` is asynchronous — the mitigations must be order-independent

The HTML specification queues a task for the `<details>` toggle event; it does not fire synchronously
on assignment. Whether that task runs before the browser snapshots the print document is
engine-dependent, so `positionPop` / `setupClamp` may run during the print pass, after it, or — if
the leave path already closed the panel, since the handler re-checks `panel.open` — not at all.

Two requirements follow. The §2a mitigation must be **CSS**, which applies whenever the declarations
land and needs no ordering guarantee (this is the decisive reason to prefer it over clearing
`pop.style.top` in JS). And **no test may assert that the toggle side effects happened** — only that
the printed result is correct either way. The §2c leave-path cleanup must be a no-op when the side
effects never ran, and its test establishes the residue deterministically rather than waiting for
`setupClamp` (see Testing).

### 3. The print stylesheet — a new `@media print` block at the end of `notes.css`

The file currently has none.

#### Specificity is the load-bearing constraint

`@media print` adds **no** specificity — `courses.css:1346` already records this lesson in a comment.
The rules being undone are not weak:

| Rule to undo | Selector | Weight |
|---|---|---|
| pop floats into the margin (`notes.css:90–107`) | `.notes-js .block-notes__panel[open] .block-notes__pop` | (0,4,0) |
| pop clamped to the right (`notes.css:109–112`) | `.notes-js .block-notes__panel[open] .block-notes__pop--clamped` | (0,4,0) |
| focus highlight (`notes.css:278`, `:284`) | `.lesson-block.is-highlighted` / `.is-dimmed` | (0,2,0) |
| unanchored summary padding (`notes.css:270`) | `.unanchored-notes summary` | (0,1,1) |
| add-composer hide in read-first mode (`notes.css:181–182`) | `.notes-js .block-notes__pop--has-notes:not(.is-adding) .note-composer:not(.note-composer--edit)` | (0,5,0) |
| "Add another note" reveal (`notes.css:177`) | `.notes-js .block-notes__pop--has-notes .block-notes__add-more` | (0,3,0) |
| Print button's no-JS gate (§1) | `html.js .unit-strip__print` | (0,2,1) |
| slideshow deck rules (§2d) | `.slideshow-deck .slide[hidden]` etc. | (0,3,0) |
| inline `top` from `positionPop` | — | inline |

So a print rule that must beat **one of the rules in the table above** is inert at (0,1,0)
regardless of source order, and a mutant written at that weight is equally inert and will mislead.

The claim is deliberately scoped to the table. It is **not** true of print rules generally: the
un-clamp rule below is `.note-card__body--clamp { … }` at (0,1,0) and it works *because* of source
order — it ties `notes.css:186` on weight and wins by sitting later in the same file. That is the one
deliberate equal-weight-plus-order case, and it is safe only because the print block is pinned to the
end of `notes.css`. Every print declaration that undoes one of the above must
either **match the original selector's weight or beat it**, or carry `!important`; the inline `top`
needs `!important` unconditionally. Where weights are equal, source order decides and must be pinned
(§1 does this explicitly for the button).

If any `.visually-hidden` element is ever revealed in print, **all nine** of its declarations must be
reset — the class is defined three times (`app.css:1384` with six declarations, `notes.css:4` and
`tags.css:6` with nine each, adding `padding: 0`, `margin: -1px`, `border: 0`) and `lesson_unit.html`
loads all three sheets. The `.tabs__panel-label` reveal at `courses.css:1859` is the precedent for a
complete reset. §3 deliberately avoids needing this by using a real element for the label, below.

#### Scoping — per rule, not per file

`_note_card.html` is included by exactly two templates, `_block_notes.html` and `_unanchored.html`,
both inside `<article class="lesson">`. **But the print block is written against classes, not
templates**, and `notes/templates/notes/course_notes.html` — the notes hub — also loads `notes.css`
and renders `.note-card`, `.note-card__body` and `.note-card__meta` via `_readonly_note_card.html`.

The scoping decision therefore splits by **what the rule does**:

- **Rules that hide or replace content are scoped to `.lesson`.** An unscoped relative-date hide
  would strip the *only* date from the hub's printout, where no `.note-card__print-date` and no label
  element exist to replace it.
- **Rules that restore content are NOT scoped.** The un-clamp rule and the `.note-card__more` hide
  are deliberately global, because `notes.js:576–578` runs `setupClamp` on the hub too
  (`[data-course-notes]`, via `requestAnimationFrame`). A `.lesson`-scoped un-clamp would leave the
  hub — a page a student is at least as likely to print — printing every long note truncated at six
  lines with a *Show more* button beside it. Restoring content can only improve the hub's printout,
  so it is safe to apply there.

That asymmetry is the rule: **scope a hide, globalise an un-hide** — with one stated exemption. A
reveal *may* carry the `.lesson` scope when the element it targets exists only inside a lesson
anyway, which is the case for `.note-card__print-date` and `.note-card__print-label` (both added to
`_note_card.html`, which the hub does not use). There the scope is inert rather than wrong, and it
keeps each reveal beside the hide it pairs with.

#### The block must

- **Return the pop to flow**, written **verbatim as
  `.notes-js .block-notes__panel[open] .block-notes__pop`** — unscoped, matching the original
  selector's (0,4,0) exactly and winning by end-of-file source order. Writing it verbatim is chosen
  because it cannot be got wrong by miscounting: it does not depend on `.lesson` being an ancestor,
  and it ties the rule it must beat by construction. (The `.lesson`-scoped write
  `.lesson .block-notes__panel[open] .block-notes__pop` is **also (0,4,0)** — `.lesson`,
  `.block-notes__panel`, `[open]` and `.block-notes__pop` all count in the class column — so it would
  work too; what does *not* work is any form that drops a class-column term, e.g.
  `.lesson details[open] .block-notes__pop` at (0,3,1).) Reset every property the original rule sets,
  not just the positioning ones: `position`, `top` (`!important`, per the inline style), `left`, `right`, `width`,
  `margin-top`, `padding`, `background`, `border`, `max-height`, `overflow-y`, `z-index`, `border-radius` and
  `box-shadow`. `right` is named explicitly because `.block-notes__pop--clamped` sets
  `left: auto; right: 0`: resetting `left` alone leaves `right: 0` applied. A partial reset leaves the
  pop printing as a bordered, padded floating card flush against its block, which is not "in flow".
- **Un-clamp bodies (unscoped).** `.note-card__body--clamp { display: block; -webkit-line-clamp: none;
  overflow: visible; }`, and hide `.note-card__more`.
- **Hide every control, except a note being edited.** `.note-card__actions` (edit / delete), `.block-notes__add-label`,
  `.note-delete-confirm` (§2b), **`.block-notes__add-more`** — which must be written
  `.lesson .block-notes__pop--has-notes .block-notes__add-more` at (0,3,0), or carry `!important`,
  because its screen reveal (`notes.css:177`) is (0,3,0) and a plain `.lesson .block-notes__add-more`
  at (0,2,0) loses to it regardless of source order; it is the **only** control in this list whose
  screen rule beats (0,2,0), which is why it is called out separately — and
  `.note-composer:not(.note-composer--edit):not(.note-composer--has-draft):not(:has(.note-composer__error))`.
  The first `:not()` is required by §2b; the second spares a **typed but unsaved draft**, marked by
  `print.js` because CSS cannot see a textarea's value (§2 responsibility 5); the third spares the
  **no-JS error composer** — when the no-JS create path
  rejects a note, `_block_notes.html` re-renders the panel `open` with the student's rejected text in
  a plain `.note-composer` plus a `.note-composer__error`, and hiding it would drop that unsaved text
  from a printout on the very no-JS route §5 documents.

  **That third carve-out is a no-JS-route guarantee only.** With `.notes-js` present and the pop
  carrying notes, `notes.css:181–182` already hides that composer at (0,5,0) — the most specific rule
  in the file — which no print rule here attempts to beat. "Not hidden by the print block" is
  therefore not the same as "shown"; the carve-out matters exactly where `.notes-js` is absent. For every composer that survives,
  hide `.note-composer__actions` and print `.note-composer__input` readably. **`height: auto` does
  not achieve this**: both composers render `<textarea rows="3" maxlength="5000">`
  (`_composer.html:6`; `notes.js:288` sets `ta.rows = 3`), and a textarea's intrinsic block size is
  derived from `rows`, so `auto` resolves to three rows with the remaining 4900-odd characters
  scrolled out of view — silently defeating §2b's promise that the note is not lost. Two mechanisms,
  both required:

  - **`print.js` stamps the measured height** on the enter path — `ta.style.height =
    ta.scrollHeight + "px"` — cleared on the leave path. This is the mechanism that works on every
    engine.

    **"Surviving" must be defined operationally, because it is otherwise a property of the print
    cascade that JS cannot evaluate.** The set is exactly the composers §3's hide spares: those
    carrying `.note-composer--edit`, `.note-composer--has-draft`, or a `.note-composer__error`
    descendant. It is emphatically **not** `document.querySelectorAll(".note-composer__input")` — that
    reaches the composers inside note-less panels, which responsibility 3 deliberately never opens, so
    they are still under `::details-content { content-visibility: hidden }`, `scrollHeight` reads `0`,
    and the enter path would write `height: 0px` onto every note-less block's composer. If the leave
    path then never fires (a case Error handling calls harmless), the student is left with unusable
    zero-height composers across the whole lesson.

    Belt and braces: **the stamp is skipped whenever `scrollHeight` is `0`**, so no build can write a
    zero height even if the selector is later widened.

    **That skip alone would silently lose every composer on a non-active slide.**
    `_lesson_article.html:37–46` renders `_block_notes.html` *inside* each `.slide`, and at
    `beforeprint` every non-active deck slide is `[hidden]` → `display: none` (`courses.css:396`), so
    a textarea inside one measures `scrollHeight === 0` and is skipped. §2d then makes that slide
    print. On Chromium `field-sizing: content` saves it; on Firefox and WebKit — where §3 calls
    `field-sizing` progressive enhancement, not the mechanism — it would print three rows with up to
    4900 characters clipped, which is exactly the loss this whole sub-section exists to prevent.

    So the enter path handles it rather than accepting it: when a surviving textarea measures `0` and
    has a `[hidden]` `.slide` ancestor, it **temporarily clears that ancestor's `hidden`, re-measures,
    and restores it — synchronously, within the same task**, so no layout the user or the print
    snapshot can observe is affected. If it still measures `0` after that, the stamp is skipped as
    above.

    **The measurement context is the screen cascade, and the error direction is stated.** At
    `beforeprint` the print geometry may not be resolved, so `scrollHeight` is read while the pop may
    still be `width: 15rem` (`notes.css:92–106`). The printed pop is returned to flow at full column
    width, which is **wider** — the same text needs *fewer* lines, so the stamped height is
    **over-tall, never short**. Over-tall prints trailing whitespace; short would clip the student's
    words. Over-tall is the acceptable failure direction, which is why no re-measurement after
    the print cascade is required.

    One caveat that makes a "decorative" reset load-bearing: `.note-composer__input` is
    `box-sizing: border-box` (`notes.css:209`) and inherits `input[type]` border and padding from
    `app.css`, so `ta.style.height = ta.scrollHeight + "px"` sets a *border-box* height from a
    *padding-box* measurement — short by the border width. The print block's `border: 0` is what
    recovers it. Do not delete that declaration as chrome.
  - **CSS** supplies `field-sizing: content; height: auto; max-height: none; overflow: visible;
    border: 0; resize: none;`. `field-sizing` is Chromium-only today, so it is progressive
    enhancement, not the mechanism — but it keeps the printout correct if the enter path never ran.
- **Reset the hover/focus highlight state.** `notes.js` adds `.lesson-block.is-highlighted`
  (background tint + outline, `notes.css:278`) to one block and `.lesson-block.is-dimmed`
  (`opacity: .45`, `notes.css:284`) to every other when a note card is hovered or focused, clearing
  it only on blur. A student who clicks a note and then presses `Ctrl+P` would print most of the
  lesson at 45% opacity. Print resets `.is-dimmed` to `opacity: 1` and neutralises `.is-highlighted`'s
  background and outline.
- **Keep the card, keep the rail.** `.note-card` already carries
  `border-left: 4px solid var(--note-accent, …)` with eight stable per-block hues bound via
  `data-colour`. Print keeps that rail — borders are painted even when the browser's "background
  graphics" option strips backgrounds — and adds `break-inside: avoid`.
- **Hide a pop with nothing in it** — and get its exemption list right, because this rule is the one
  most able to silently undo the three carve-outs above. The §2 filter governs only panels `print.js`
  opens; a note-less panel the *student* opened by hand stays open by design, and with its add-label
  and composer hidden it contributes a stray empty `.block-notes__pop` box to the print tree. The
  rule is:

  ```css
  .lesson .block-notes__pop:not(:has(
      .note-card, .note-composer--edit, .note-composer--has-draft, .note-composer__error)) {
    display: none;
  }
  ```

  Three things about that `:has()` list are deliberate:

  - **`.note-composer--has-draft` and `.note-composer__error` must be in it.** `_block_notes.html`
    renders a composer for **every** block, note-less ones included, and re-opens the panel with a
    rejected `note_error` draft on note-less blocks too. Without these two entries the empty-pop rule
    hides the whole pop and the draft is lost anyway — the marking in §2 responsibility 5 and the
    no-JS carve-out in the hide list would both buy exactly nothing. The `--error` case cannot be
    rescued by JS, since `print.js` never runs on the route that produces it.
  - **`.note-delete-confirm` is deliberately *not* in it.** §2b says a mid-delete note "is omitted
    cleanly rather than printing a stray Delete? Yes / No strip". Exempting the pop would instead
    leave an empty pop box for a block whose only note is mid-delete. Leaving it out makes the pop
    vanish, which is what "cleanly" means.

  **What the empty pop actually looks like — and therefore how to assert it.** Not a bordered, padded
  card: `.block-notes__pop`'s border, padding, background, radius and shadow come **only** from the
  `@media (min-width: 1200px)` block (`notes.css:92–107`), and the pop-to-flow reset above zeroes
  every one of them in print anyway. Measured in Chromium, the residual box on the mutant build is
  **zero-height** — `bounding_box()` returns `{… "height": 0}` and `checkVisibility()` returns
  `true` — against `bounding_box() is None` / `checkVisibility() false` on the correct build. So rows
  8a and 9c **must assert `checkVisibility()`**, never a `bounding_box()["height"] == 0` threshold:
  the height predicate is satisfied on *both* builds and the row would be dead. This is the `display:
  none` case row 6a already distinguishes, and the exact inverse of the `visibility: hidden` case in
  rows 6a2/10b — which is why the measurement-traps list below states both directions.
  - **The `.lesson` scope** is per the scoping rule ("scope a hide"). It is inert — `.block-notes__pop`
    exists only in lessons — but the rule is applied uniformly so no reader has to wonder whether an
    unscoped hide was a decision or an oversight.
- **Style the unanchored section.** `.unanchored-notes` carries a dashed border and raised
  background, and its `<summary class="unanchored-notes__handle">` renders a literal `⚠` glyph plus
  "N notes whose block was removed" — screen chrome, and a bare glyph against the project's
  monochrome-SVG convention. In print the summary is suppressed and the dashed container is flattened
  to a plain rule; the notes themselves print as ordinary cards at the end of the lesson. Their
  provenance is carried by the `My note` label.

  **The summary is suppressed with `visibility: hidden; height: 0; padding: 0; margin: 0; border: 0;
  overflow: hidden` rather than `display: none`.** The full reset matters: `.block-notes__handle`
  carries `padding: .2rem .35rem` (`notes.css:59`), which `height: 0` does not remove, leaving ~6.4px
  of blank box on **every** element in the lesson. This is the same standard §3 applies to the pop
  ("reset every property the rule sets").

  `.block-notes` itself carries `margin-top: -.85rem; margin-bottom: .35rem` (`notes.css:45`), tuned
  to pull the screen affordance up against its element. With the handle gone, that negative margin
  drags the note card up over the block it annotates. Print resets it to
  **`margin-top: .35rem; margin-bottom: .75rem`** — a small positive lead-in so the note reads as
  belonging to the block **above** it, and slightly more trailing space so it does not crowd the next
  block. Both values are stated rather than left to taste, so the rule is reviewable.

  **Both `<summary>` elements take this visibility-based treatment** — `.unanchored-notes__handle`
  and `.block-notes__handle` alike — but they have **different competitors**, and only one of the two
  scopes is inert. `.block-notes__handle`'s padding comes from its own (0,1,0) rule (`notes.css:59`).
  `.unanchored-notes__handle` has **no rule of its own in `notes.css` at all**; its padding comes from
  `.unanchored-notes summary { padding: .25rem 0 }` at `notes.css:270`, which is **(0,1,1)**. So a
  suppression written `.unanchored-notes__handle { … padding: 0 … }` at (0,1,0) **loses the padding
  declaration**, and with the global `box-sizing: border-box` (`reset.css:2`) a `height: 0` box still
  measures 8px — which would make row 10b RED on an otherwise-correct build. The `.lesson` scope on
  this particular suppression is therefore **load-bearing**, not defensive: `.lesson
  .unanchored-notes__handle` is (0,2,0) and beats it. Neither appears in the `display: none` list above, deliberately:
  the choice of mechanism is load-bearing rather than cosmetic, and naming the handle in both places
  would leave an implementer to pick.

  On the choice of mechanism:
  Engines differ on whether a `<details>` whose first `<summary>` is not rendered still renders its
  children when open, and that `<details>` is the load-bearing element for the whole unanchored
  section printing at all. The same caution does **not** apply to `.block-notes__handle`, whose
  `<details>` sibling content is separately guaranteed by the sweep — but for consistency and safety
  both use the same treatment.

#### The `My note` label — decided

`_note_card.html` gains a print-only element, as the **first child of `<article class="note-card">`,
outside the `{% if note.element_id %}` guard**:

```html
<p class="note-card__print-label" aria-hidden="true">{% trans "My note" %}</p>
```

Placement is specified because both alternatives are wrong: after the body it reads as a caption
rather than a heading, and inside the `element_id` guard it would vanish from exactly the unanchored
notes that depend on it for provenance.

Sentence case in the msgid, matching the catalogue's existing `Add a note` / `Edit note` /
`Delete note`; the shouting is presentation, applied in the print block as
`text-transform: uppercase; letter-spacing: .08em`, exactly the `.ba__side-heading` treatment at
`courses.css:2113`. Hidden on screen with `display: none` in the base block, revealed in print.

A real element is chosen over the two alternatives deliberately: a `::before` with `content` from a
custom property makes the string awkward to translate, and un-hiding the existing `.note-card__on`
paragraph would sit on the `.visually-hidden` trap above. A real element is also the only one of the
three the e2e can measure with `checkVisibility()` and a height threshold.

#### The absolute date — and the template edit it requires

`.note-card__meta` renders `added 3 days ago` / `edited 3 days ago` via `timesince`, which is
meaningless on paper read weeks later. **The relative text is currently a bare text node inside the
`<p>`, so no selector can target it.** The template edit is therefore part of this change:

```html
<p class="note-card__meta">
  <span class="note-card__meta-rel">{% if note|note_edited %}…{% else %}…{% endif %}</span>
  <span class="note-card__print-date">{% if note|note_edited %}{% blocktrans with date=note.updated|date:"SHORT_DATE_FORMAT" %}edited {{ date }}{% endblocktrans %}{% else %}{% blocktrans with date=note.updated|date:"SHORT_DATE_FORMAT" %}added {{ date }}{% endblocktrans %}{% endif %}</span>
</p>
```

**The verb is kept.** The relative form's `added` / `edited` distinction lives *inside* the
blocktrans that `.note-card__meta-rel` now wraps, so hiding that span would leave a naked
`21.08.2026` on paper with no indication whether it is a creation or a last-edit date — a real loss
of meaning weeks later. The print span therefore carries the same two phrasings, at a cost of two
msgids (§6).

Both phrasings already read **`note.updated`** — `note.created` is never rendered — so the print date
uses `note.updated` too. The *date* is localised by Django's `L10N` / `DATE_FORMAT` machinery, never
through `gettext`: a date format is not a translatable message. Only the surrounding verb is a msgid.

Both halves need a rule, symmetrically with the label:

- base block: `.note-card__print-date { display: none; }` — without it every card on screen would
  read "added 3 days ago 21.08.2026", a visible regression on the lesson page;
- print block, scoped to `.lesson`: `.note-card__meta-rel` hidden, `.note-card__print-date` revealed.

`_readonly_note_card.html` (the hub) is **not** edited and has **no `.note-card__meta-rel`
descendant at all** — it keeps a bare text node inside `.note-card__meta`. So this hide already
matches nothing on the hub, and the `.lesson` scope on *this particular rule* is **defensive, not
load-bearing**: dropping it would change nothing there. It is kept for consistency with the scoping
rule above, and against a future edit that gives the hub the same span.

That correction matters for the test table: a mutant that removes this scope is **dead**, and row 13
must not claim otherwise. The hub protection that *is* live is the un-clamp rule staying unscoped.

### 4. Dark theme — fixed in CSS, site-wide

`tokens.css:79` defines `[data-theme="dark"]` with `--text-primary: #F2EFE9` (near-white). **No**
print rule anywhere resets the theme, and `print-color-adjust` appears nowhere in the repo. Browsers
strip backgrounds by default when printing. So a dark-theme student printing a lesson today gets
near-white text on white paper — a blank page.

**The mechanism is richer than "an attribute from `user.theme`."** `base.html:4–5` renders both
`data-theme` and `data-theme-pref`; a prepaint script (`base.html:17–26`) overwrites `data-theme`
from `matchMedia("(prefers-color-scheme: dark)")` when the pref is `auto`, falling back to a
`libli_theme` cookie when **`data-theme-pref`** (not `data-theme`) is absent, and `ui.js` rewrites
both on toggle. What is true
is that `tokens.css` itself contains no `prefers-color-scheme` query — the resolved theme always
arrives as the `data-theme` attribute.

**The fix is a `@media print` override in `tokens.css`** rather than a JS stash-and-restore in
`print.js`. Three reasons, each of which the JS route fails:

1. **It reaches the no-JS route.** §5 offers `?notes=1` + `Ctrl+P` as the supported no-JS path; with
   JS off, `print.js` never runs, so a JS-only theme fix would print §4's blank page for exactly
   those users.
2. **It reaches every page.** `print.js` loads only from `lesson_unit.html`. A JS fix would leave the
   quiz page, the course outline and the notes hub printing white-on-white.
3. **It needs no restore**, so it cannot be left half-applied by an `afterprint` that never fires.

**Selector and placement are load-bearing.** `:root` and `[data-theme="dark"]` are both (0,1,0) and
both match `<html>`, so an override wins only by source order — it is **silently inert** anywhere
above line 79. The block must be `@media print { [data-theme="dark"] { … } }`, placed at the **end**
of `tokens.css`.

**The override set — one rule, no exceptions.** The print block restates **every token name the
`[data-theme="dark"]` block declares**, using `:root`'s declaration for that name **verbatim**. Not
"the literal ones": the seven brand tokens at `tokens.css:81–87` (`--primary`, `--primary-hover`,
`--primary-active`, `--primary-subtle`, `--accent`, `--accent-hover`, `--accent-subtle`) are
`color-mix()` formulas that differ genuinely from `:root`'s — dark mixes toward `white`, light toward
`black`, and `--primary-subtle` is 24% versus 16% — so copying `:root`'s formula is exactly what is
needed, and excluding them because they are "not literals" would leave brand-coloured elements
printing at dark-mode weights.

The set that matters most for ink is easy to under-count: besides `--surface-*`, `--text-*` and
`--border-*`, the dark block redefines the four author-selectable **body-text** colours as light
tints — `--tc-red: #EA8A82`, `--tc-blue: #8FBCE8`, `--tc-green: #9FBF7B`, `--tc-orange: #E8B761` —
plus `--success`, `--warning`, `--danger` and their `-subtle` partners, `--scroll-edge`,
`--surface-overlay` and the `--shadow-*` family. Omitting the `--tc-*` group would leave a lesson
with coloured text still printing near-white-on-white.

`--scrim-solid` is **not** in the set: it is declared only in `:root` (`tokens.css:49`), never in the
dark block, and an existing source-level test enforces that absence.

**`tokens.css` is not the only file with dark-only declarations, and the others are on the printed
lesson page.** `courses.css:2010–2014` declares a second set:

```css
[data-theme="dark"] .callout--example { --callout-accent: #7db0f7; }
[data-theme="dark"] .callout--note    { --callout-accent: #aabac8; }
[data-theme="dark"] .callout--tip     { --callout-accent: #5cd193; }
[data-theme="dark"] .callout--warning { --callout-accent: #e8b761; }
[data-theme="dark"] .callout--task    { --callout-accent: #ee9fd8; }
```

`--callout-accent` drives the callout heading and marker `color` (`courses.css:1962`, `:1972`) and
the `border-left: 3px solid` rail (`:1944`). These live in a **later-loaded sheet at (0,2,0)**, so the
`tokens.css` print block cannot reach them: a dark-theme student printing a lesson with callouts gets
`#7db0f7` (≈2.2:1) or `#e8b761` (≈1.9:1) headings on white — the exact legibility failure §4 exists
to prevent, on the exact page this button ships on.

So a **matching `@media print { [data-theme="dark"] .callout--* { … } }` block is appended to
`courses.css`** alongside §1's and §2d's rules.

**The value source is not `:root` here.** `--callout-accent` is never declared on `:root`; its
light values live on the modifier classes themselves (`courses.css:2004–2008`:
`.callout--example { --callout-accent: #2563c9 }` … `.callout--task { --callout-accent: #a8318f }`),
and `.callout` carries only the fallback `--callout-accent: var(--primary)` at `:1942`. So the
general contract is: **the print counterpart restates the value from the light-theme declaration of
the same selector**, which is `:root` for the `tokens.css` set and `courses.css:2004–2008` for the
callout set. Stated as "copy `:root`'s value" it would be unwritable for callouts. And the rule for the parity test
becomes a repo-wide one: *every* `[data-theme="dark"]` declaration in a shipped stylesheet needs a
print counterpart, not just `tokens.css`'s. A sweep at implementation time found exactly two sets
that matter for a printed lesson — `tokens.css:79` and `courses.css:2010–2014`. Three other dark rules are
excluded, each for its own stated reason — the parity test names them so a future reader can tell
"checked and excluded" from "missed":

- `error.css:50` and `editor.css:924` are on pages this feature does not print.
- `tags.css:329` **is** on the printed page — `lesson_unit.html:36` loads `tags.css`, and
  `_unit_strip.html` includes the tag panel — so "not on this page" would be a false rationale. It is
  excluded on the narrower and true ground that `.tag-delete-confirm` is a JS-built transient inside
  a `<details>` that is closed unless `tags_panel_open`, and is author-only.

The cost is that the light values are stated twice. That is pinned by a parity test (see Testing),
whose **extraction contract is itself load-bearing**: the repo's existing helper
`tests/test_text_colour_css.py:68` is `re.search(re.escape(selector) + r"\s*\{(.*?)
\}", css,
re.DOTALL)` — first match, non-greedy to the first column-0 `}`. Once a **second**
`[data-theme="dark"]` block exists inside `@media print`, that idiom returns the *screen* block for
both sides of the comparison and the test passes vacuously. The parity test must therefore locate
each block unambiguously rather than reuse that helper as-is.

This is a pre-existing, site-wide defect pulled into this branch because shipping a Print button that
yields a blank page for every dark-theme student would be shipping a broken feature. It remains
separable: the notes work stands without it.

### 5. Degradation (no JS)

With JS off, `notes.js` never adds `.notes-js`, the panels stay closed, and the Print button is
hidden by the `html.js` gate in §1 rather than rendered dead.

There is no no-JS *affordance* — see §Scope, where discoverability is explicitly excluded. What
exists is a working URL a student would have to already know: the `?notes=1` query parameter, which
**already works today**:
`_block_notes.html` server-renders `<details … open>` when `notes_show` is set and the block has
notes, so `…/u/<pk>/?notes=1` followed by `Ctrl+P` prints a lesson with its notes open, with no JS at
all. Because §4's theme fix is CSS, this route is correct in dark theme too. Slides need no help
either: without `html.js` the screen rules that hide inactive slides never apply and `slideshow.js`
never builds the deck, so every slide is already visible. The §3 `:has(.note-composer__error)` carve-
out keeps a rejected no-JS draft on the page. No new server-side work is required for this route.

### 6. i18n

**Three** new msgids: `My note` (§3), and the printed date's two verb phrasings,
`added %(date)s` and `edited %(date)s` (§3) — the latter two exist so the printout keeps the
created-vs-last-edited distinction the relative form carries. `Print` (§1) is **not** new — `msgid "Print"` already exists at
`locale/pl/LC_MESSAGES/django.po:5231` with `msgstr "Drukuj"`, referenced from
`analytics_matrix.html` and `gradebook_print.html`; `makemessages` will only add a `#:` source
reference to that entry. The absolute date is not on this list either: it is a Django format, not a
msgid (§3).

The `pl` translations are **`Moja notatka`**, **`dodano %(date)s`** and **`edytowano %(date)s`**; each must land non-fuzzy with a
non-empty `msgstr`.

**The fuzzy hazard is at its maximum here.** The catalogue already carries
`msgid "edited %(when)s ago"` (`django.po:3204`) and `"added %(when)s ago"` (`:3210`) — near-identical
strings, so `makemessages` is very likely to pre-fill the new entries with those wrong translations.
Each new `blocktrans` therefore carries a `{# Translators: … #}` comment saying the placeholder is a
date, and the placeholder is named `%(date)s` rather than an opaque `%(d)s` so a translator can tell
without the comment. Both hazards apply to it: `makemessages` pre-fills fuzzy entries with a **wrong**
translation, and clearing one requires deleting **both** the `#, fuzzy` marker and the bogus
`msgstr`; and the binary `.mo` must be regenerated at the end rather than carried stale through a
long branch.

## Data flow

Nothing is persisted, and no request is made. There is no new view, no new URL, no new model field
and no migration. The whole feature is client-side, over markup the server already renders:

```
student clicks Print  ─┐
                       ├─→ window.print()
student presses Ctrl+P ─┘        │
                                 ▼
            'beforeprint'  OR  matchMedia("print") change (e.matches === true)
                                 │
              (no mode flag — enter only queries :not([open]), so a
               second enter finds its own work already done: §2.7)
                                 │
                  ┌──────────────┴───────────────┐
                  ▼                              ▼
      open the closed panels containing      add each opened node to
      .note-card / .note-composer--edit /    the module-local Set
      .note-delete-confirm / a typed
      textarea value, plus
      .unanchored-notes > details
                    │
                    ▼  (strictly after opening — §2.5)
      re-derive .note-composer--has-draft, then stamp each
      surviving textarea's height (measuring through a
      [hidden] slide where needed); record those in a
      second Set
                                 │
                                 ▼
              (notes.js's capture-phase toggle handler MAY run,
               now or later or never — §2e: positionPop stamps an
               inline top and may add --clamped; setupClamp clamps
               bodies to 6 lines and injects Show-more buttons)
                                 │
                                 ▼
        @media print in notes.css undoes both, order-independently, at
        (0,4,0)+/!important; hides handle / actions / add-more /
        add-label / delete-confirm / non-edit non-error composer;
        resets is-dimmed / is-highlighted; reveals My note + the
        absolute date and hides the relative one (hides scoped to
        .lesson, un-clamp global — see Scoping).
        @media print appended to courses.css reveals every slideshow
        slide, flattens the deck/stage, hides .slideshow-bar, and hides
        the Print button at (0,2,1).
        @media print at the end of tokens.css supplies the light palette.
                                 │
                                 ▼
                       browser paints the sheet
                       (or writes the PDF)
                                 │
                                 ▼
            'afterprint'  OR  matchMedia change (e.matches === false)
                                 │
              (no mode flag — leave drains the Set, so a second
               leave iterates an empty one: §2.7)
                                 │
                    close exactly the nodes in the Set; strip
                    .note-card__body--clamp and .note-card__more
                    from inside them (no-op if absent); clear the
                    stamped heights and draft marks; clear the Set.
                    Theme, slides and positionPop's residue need
                    no restore.
```

## Error handling

- **The leave path never fires** (a known browser inconsistency, notably on a cancelled print job).
  Two cases, and the design covers both:
  - *One of the two dispatchers arrives.* Both drive the same handler, so the page is restored.
  - *Neither arrives.* The page keeps its panels open and the clamp residue — visible, but harmless
    and self-correcting: because there is no `entered` flag (§2 responsibility 7), the **next** print
    still sweeps correctly, and `positionPop` self-heals its own residue (§2a). An earlier draft used
    a mode flag here, which turned this case into a silent permanent failure; removing it is what
    makes this bullet true rather than aspirational.

  Because the theme and the slide reveal are CSS-only, no palette or layout state can be stranded.
- **The toggle side effects never ran** (§2e). The leave-path cleanup removes classes and elements
  that may not exist; it must be a no-op in that case, never an error. A throw would abort the
  restore half-done, leaving panels open and the Set un-cleared, so the next leave would close a
  stale set. Row 20 exists for exactly this branch.
- **A student had panels open before printing.** Handled by construction: `print.js` records only the
  panels it opened itself, and restores and de-clamps only those.
- **A note is mid-edit when printing** (§2b). The edit form survives the control-hiding rule and its
  textarea prints as text; the note is not lost.
- **A note is mid-delete when printing** (§2b). Its text is not in the DOM and cannot print; the
  confirm strip is hidden so the printout omits the note cleanly rather than printing "Delete? Yes /
  No". Documented loss.
- **A rejected no-JS draft is on the page** (§3). Its composer is spared by the
  `:has(.note-composer__error)` carve-out and prints as text.
- **A multi-slide lesson** (§2d). All slides print, so notes on every slide are reachable.
- **No JS.** The button is hidden rather than dead. `?notes=1` still produces a correct printout for
  anyone who reaches it directly, but nothing advertises it (§Scope).
- **A unit with no notes.** The button still prints, producing the lesson exactly as it prints today.
  Because the sweep is filtered, no note-less panel is opened.

## Testing

The house rule applies: **falsify the tests, do not merely run them.** Each assertion below is paired
with the mutant that must turn it RED, chosen from the failure mode it is meant to catch.

### Settled: `emulate_media` **does** fire a `matchMedia("print")` change

This was an open question in earlier drafts; it has since been **measured in this repo's Chromium**
and the answer is recorded here so no plan writer re-derives it: `page.emulate_media(media="print")`
**does** deliver a `change` event with `matches === true` to a `matchMedia("print")` listener, and it
is observable on the very next `evaluate`.

Two consequences, both load-bearing for the table below:

1. Row 2's trigger is simply `emulate_media` with no dispatch — no synthetic event is needed. (Had it
   not fired, the sanctioned fallback would have been a constructed
   `new MediaQueryListEvent("change", {media: "print", matches: true})`. A bare `new Event("change")`
   is never acceptable: it carries no `matches`, so a handler routing on `e.matches` reads `undefined`
   and takes the *leave* path, going red on a correct build.)
2. **`emulate_media` runs the enter path.** Any row that means to observe behaviour *without* the
   enter path having run must therefore prevent `print.js` from loading at all, not merely withhold a
   `beforeprint` dispatch. Row 7c does this with `page.route("**/print.js", lambda r: r.abort())`.

Reads after `emulate_media` should still be **polling** reads (`expect(...).to_pass()` style) rather
than a bare `evaluate`, since the listener runs asynchronously.

**Row 16b is the one exemption**, and deliberately so: it measures a state that a correct build
*ends* (an opaque slide is the pass condition, and on the mutant build the slide becomes opaque a
moment later of its own accord). Polling there would convert a real failure into a pass. Its state is
injected rather than raced, so a single non-polling read is both sufficient and deterministic.

### How print state is entered in a test — pin this first

`page.emulate_media(media="print")` **only** re-evaluates CSS media queries. It does **not** dispatch
`beforeprint`, and `window.print()` is a no-op in headless Chromium. So neither one alone can drive
these tests:

- **CSS-only assertions about elements outside a `<details>`** need `emulate_media` alone.
- **Anything inside `.block-notes__pop`** — which is inside `::details-content` — additionally needs
  the panels open, or `checkVisibility()` returns `false` on a **correct** build and the assertion is
  either red-on-green or unfalsifiable.
- **Leave-path assertions** dispatch `afterprint`.

**There is no mode flag, so dispatch order no longer buys listener isolation** — and the test plan
must not pretend otherwise. With both listeners live, calling `emulate_media` *at all* runs the enter
path via the media route. One sharp consequence: **a row that means to prove the `beforeprint`
listener exists must never call `emulate_media` before its assertion**, or the mutant that deletes
the `beforeprint` registration is silently rescued by the media route and the row is green on a
broken build.

Row 1 is therefore re-specified to assert **on screen**: dispatch `beforeprint`, then assert the note
body passes `checkVisibility()` with **no** `emulate_media` call. An open `<details>` is visible on
screen, so this is a valid observation, and only the `beforeprint` listener can produce it.

The markers therefore mean something narrower than an earlier draft claimed:

- *(event)* — killed by deleting the `beforeprint`/`afterprint` registration: rows **1, 7d, 9, 9b,
  9d, 16c, 18, 19, 20, 20b**. These either avoid `emulate_media` entirely or assert DOM state.
- *(media)* — killed by deleting the `matchMedia` registration: row **2** only.
- *(shared)* — rows **10** and **17** depend on the sweep/restore *logic*, not on which listener ran;
  their mutants target that logic. Marked `(shared)` rather than `(event)` because deleting the
  `beforeprint` registration leaves row 17 green: nothing runs, so a hand-opened panel is still open,
  which is exactly what it asserts.
- *(CSS)* — depend only on the stylesheet, and use whichever entry the row specifies.

The `matchMedia` handler routes on `e.matches` (§2 responsibility 7), so
`mql.dispatchEvent(new Event("change"))` must **not** be used — `matches` is the discriminator and a
bare `Event` has none, so it takes the leave path and goes red on a correct build. A
`MediaQueryListEvent` carrying `matches` is fine (see the spike contingency above).

### One constraint that shapes three rows: the suite is Chromium-only

`conftest.py` uses the stock `pytest-playwright` `page` fixture with no browser parametrisation, so
every row below runs on Chromium alone. That matters for exactly one mechanism — the textarea fit
(§3), which has **two** implementations by design: `print.js`'s `ta.style.height` stamp (every
engine) and the CSS `field-sizing: content` group (Chromium only).

On Chromium the two are **mutually rescuing**: delete either one and the other still renders the
textarea at full height. So *no rendered-height assertion can falsify either mechanism on its own*,
and rows that claim to must not pretend otherwise. The resolution:

- **Row 7** is the only rendered-height assertion, and it lists a **combined** mutant — delete the
  stamp **and** the CSS group — since either alone is rescued. (Rows 7b and 7b2 look adjacent but are
  not affected: their mutants target the hide rule and the empty-pop `:has()` list, for which plain
  visibility is the right discriminator and no height threshold is needed.)
- The stamp itself is falsified **by asserting the mechanism**: the textarea carries a non-empty
  inline `style.height` after the enter path. That is a deliberate step down from behaviour to
  implementation, taken because the behavioural difference is only observable on Firefox/WebKit,
  which this suite does not run.
- Row 7c isolates the CSS group by blocking `print.js` entirely, so no stamp exists to rescue it.

### e2e — `tests/test_e2e_print_lesson_notes.py` (new, `pytestmark = pytest.mark.e2e`)

Fixtures follow the pattern already proven in `tests/test_e2e_notes.py`: allauth
`input[name='login']`, `TEST_PASSWORD`, `seed_roles()`, `published=True` on the unit.

| # | Assertion | Trigger / dependency | Mutant that must make it RED |
|---|---|---|---|
| 1 | A note body is **genuinely visible on screen** after the event route. *No `emulate_media` call — see the protocol above; with both listeners live, emulating print would rescue the mutant via the media route* | `beforeprint` only *(event)* | delete the `beforeprint`/`afterprint` listener registration |
| 2 | A note body is **genuinely visible** | `emulate_media` only, polling read *(media)* | delete the `matchMedia` listener registration |
| 3 | Clicking the **real button** calls `window.print()` (stubbed via `add_init_script` to set a flag) | real click, no `page.evaluate` shortcut | delete the click listener |
| 4 | A note body longer than 6 lines prints **in full**. The fixture **injects** `.note-card__body--clamp` via `page.evaluate` after the enter path and then asserts the rendered height exceeds six lines — it must **not** wait for `setupClamp`. §2e forbids depending on the async toggle; worse, `setupClamp` measures *after* adding the class (`notes.js:104`), so with the un-clamp rule live it detects no overflow and removes the class again, leaving the row green on its own mutant | `beforeprint`, inject, `emulate_media` *(CSS)* | delete the un-clamp rule |
| 5a | `.block-notes__pop` is `position: static` in print at a ≥1200px viewport | `beforeprint` then `emulate_media` *(CSS)* | delete the `position` reset; re-write it at (0,1,0); **or** re-write it in a form that drops a class-column term, e.g. `.lesson details[open] .block-notes__pop` at (0,3,1), which is genuinely inert against (0,4,0). *Note the `.lesson`-scoped `.lesson .block-notes__panel[open] .block-notes__pop` is **not** a valid mutant — it is also (0,4,0) and wins on source order (§3)* |
| 5b | An inline `top` set by the fixture is overridden | fixture sets `pop.style.top` via `page.evaluate`, then enter *(CSS)* | drop `!important` from the `top` reset |
| 5c | `right: 0` from `--clamped` is overridden | fixture adds `block-notes__pop--clamped`, then enter *(CSS)* | delete the `right` reset |
| 6a | `.note-card__actions` and `.block-notes__add-more` are **not** visible, asserted with `checkVisibility()`. *These two are `display: none` in print, which `checkVisibility()` does detect* | `beforeprint` then `emulate_media` *(CSS)* | delete the control-hiding rule; **separately**, write the add-more hide at (0,2,0) |
| 6a2 | `.block-notes__handle` has `bounding_box()["height"] == 0`. *It must **not** be asserted with bare `checkVisibility()`: §3 suppresses it with `visibility: hidden`, and `checkVisibility()`'s default `visibilityProperty: false` means it returns **`true`** for such an element — the row would be RED on a correct build. Either measure the box or pass `{visibilityProperty: true}`* | `beforeprint` then `emulate_media` *(CSS)* | delete the summary suppression |
| 6b | A composer made visible by clicking *Add another note* (`.is-adding`) and left **empty** is not visible in print. *Driven through `.is-adding` deliberately: on a has-notes pop the composer is already hidden on screen by `notes.css:181–182` at (0,5,0), so asserting it without that state passes on the mutant too* | click *Add another note*, then enter *(CSS)* | delete the composer hide |
| 7 | A note **mid-edit** prints its text **in full**: the fixture note needs more than three rows, and the textarea's `bounding_box()["height"]` must exceed a stated three-row threshold. *Without the height check the row passes on a three-row box with the rest scrolled out — the very failure §3 says `height: auto` causes, leaving the stamp untested* | open inline edit, then enter *(CSS + stamp)* | drop `:not(.note-composer--edit)` from the hide rule; **or** delete the stamp *and* the CSS `height`/`field-sizing` group **together**. *Neither alone is a live mutant on Chromium — they rescue each other (see the constraint above). The stamp on its own is falsified by row 7d, the CSS group on its own by row 7c* |
| 7d | After the enter path, a mid-edit textarea carries a **non-empty inline `style.height`**. *An implementation-level assertion, and knowingly so: on Chromium `field-sizing` masks the stamp's absence in every rendered measurement, so this is the only way the stamp has a falsifier at all on the browser this suite runs* | open inline edit, then `beforeprint` *(event)* | delete the `ta.style.height` stamp |
| 7c | With `print.js` **blocked from loading** (`page.route("**/print.js", lambda r: r.abort())` before navigation, so `notes.js` still builds the inline-edit form but no listener and no stamp exist), a mid-edit textarea still prints more than three rows. *Withholding the `beforeprint` dispatch is **not** enough: `emulate_media` fires the media listener and the stamp rescues the mutant, which is what made an earlier version of this row dead. This is the row that gives the `field-sizing`/`height` fallback its only falsifying mutant* | block `print.js`, open inline edit, then `emulate_media` *(CSS)* | delete the CSS `height`/`field-sizing` group |
| 7b | A **typed but unsaved** new-note draft prints its text, on a block that **already has notes** | click *Add another note*, type, then enter *(CSS + stamp)* | delete the `.note-composer--has-draft` marking, or the `:not(.note-composer--has-draft)` carve-out |
| 7b2 | Same, on a **note-less** block. *Row 7b cannot cover this: *Add another note* only exists on `.block-notes__pop--has-notes`, so its pop satisfies `:has(.note-card)` and the empty-pop rule never fires. Only a note-less block exercises the interaction between the draft carve-out and the empty-pop hide* | hand-open a note-less panel, type in its composer, then enter *(CSS + stamp)* | drop `.note-composer--has-draft` from the **empty-pop** rule's `:has()` list |
| 8 | A note **mid-delete**: the confirm strip does not print, and sibling notes in the same panel do | start a delete, then enter *(CSS)* | omit `.note-delete-confirm` from the hide list |
| 8a | A block whose **only** note is mid-delete prints **no pop at all** — not an empty bordered box. *Pins §3's decision to keep `.note-delete-confirm` **out** of the empty-pop `:has()` list; row 8's fixture has siblings, so it cannot see this* | start a delete on a single-note block, then enter *(CSS)* | add `.note-delete-confirm` to the empty-pop rule's `:has()` list |
| 9 | A **note-less** block does **not** carry the `open` attribute after the enter path. *Asserted on DOM state, not on paint: §3 hides the add-label and composer anyway, so a paint-based assertion would pass on the mutant* | `beforeprint` *(event)* | drop the filter from the sweep (open every panel) |
| 9b | A panel put into **delete-confirm** state on a **single-note** block and then **closed** is re-opened by the sweep. *Both constraints are load-bearing. The edit state is **not** usable here: `notes.js:286–290` gives the edit textarea `.note-composer__input` and the note's own text, so `hasTypedDraft` matches it and dropping `.note-composer--edit` is a dead mutant. And with a sibling note present a surviving `.note-card` satisfies the filter, killing the delete-confirm mutant too* | `beforeprint` *(event)* | drop `.note-delete-confirm` from the filter |
| 8b | A **rejected no-JS draft** on a **note-less** block prints its text. *Drives the real no-JS create-failure path (`note_error`), which server-renders the panel open with the student's text; `print.js` cannot rescue this one, so only the empty-pop rule's `:has()` list protects it* | post an invalid note with JS disabled, then `emulate_media` *(CSS)* | drop `.note-composer__error` from the empty-pop rule's `:has()` list |
| 9d | A typed draft in a **note-less** panel that the student then **closed** is re-opened by the sweep and prints its text. *Neither `.note-card` nor any marker class is present — the native `<details>` toggle does not clear the textarea (only the Cancel path does, `notes.js:230`) — so only the `hasTypedDraft` arm of the filter finds it* | type in a note-less panel, close it, then enter *(event)* | drop the `hasTypedDraft` arm from the sweep filter |
| 9c | A **note-less** panel the *student* opened by hand prints **no** `.block-notes__pop` box. *The only row covering the empty-pop rule, and the reason `.block-notes__add-label` needs no row of its own: it is rendered only on note-less blocks, which the sweep never opens, so a direct assertion on it would be `false` on the mutant too* | hand-open a note-less panel, then enter *(CSS)* | delete the `:not(:has(…))` empty-pop rule |
| 10b | The `.unanchored-notes__handle` summary has `bounding_box()["height"] == 0` in print. *Row 10 only asserts the section prints, which is satisfied with the ⚠ handle still showing; measured, not `checkVisibility()`, per the trap above* | `beforeprint` then `emulate_media` *(CSS)* | delete the summary suppression |
| 10c | `.block-notes` does not overlap the block above it in print: its computed `margin-top` is positive. *Covers §3's negative-margin reset, which would otherwise print the note card over the element it annotates with nothing to catch it* | `beforeprint` then `emulate_media` *(CSS)* | delete the `.block-notes` margin reset |
| 10 | The **unanchored** notes section prints (fixture: a note whose element was deleted) | `beforeprint` then `emulate_media` *(shared)* | drop `.unanchored-notes > details` from the sweep |
| 11 | The `My note` label is visible in print and **absent on screen** | screen, then enter *(CSS)* | delete the label reveal rule, **or** the base-block `display: none` |
| 12 | The absolute date is visible in print and **absent on screen**; `.note-card__meta-rel` is not visible in print | screen, then enter *(CSS)* | delete the base-block hide for `.note-card__print-date`, **or** the relative-hide rule |
| 13 | The notes **hub** prints long notes **un-truncated**. *The date half of this row is deliberately gone: the hub has no `.note-card__meta-rel`, so removing the `.lesson` scope from the relative-hide rule is a **dead mutant** (§3). The live hub protection is the un-clamp rule staying unscoped* | `emulate_media` on the hub *(CSS)* | add a `.lesson` scope to the un-clamp rule |
| 14 | After a note card is focused, in print: other blocks are **not** dimmed, **and** the focused block's computed `outline-style` is `none`. *The outline half matters on paper — outlines, like borders, survive the browser's strip-background-graphics default, so a focused block would print visibly ringed. Both rules are (0,2,0) (`notes.css:278`, `:284`), so a (0,1,0) neutralisation is inert* | focus a card, then `emulate_media` *(CSS)* | delete the `.is-dimmed` reset; **separately**, write the `.is-highlighted` reset at (0,1,0) |
| 15 | The Print button is **visible on screen** on the lesson page and **not** in print | screen, then `emulate_media` *(CSS)* | write the print rule at (0,1,0) so its own gate wins; **or** move the gate below the print rule in source order |
| 16 | **Every slide** of a multi-slide lesson prints **stacked in the flow** — the slides' `bounding_box()["y"]` values are strictly increasing — a note on slide 2 is visible, and `.slideshow-bar` is not. *The geometric check is the discriminator, not `checkVisibility()`: under the "keep only `display: block`" mutant every slide stays `position: absolute; inset: 0` inside the stage's `clamp()` height, so all of them are `display: block`, `opacity: 1`, visible, and occupying the **identical** non-zero rect. Visibility and box-presence predicates all pass on that mutant; only the y-ordering separates them*. *The test must first `wait_for_selector(".slideshow-deck", state="attached")`: §2d's rules target only the post-enhancement DOM, so entering print before deferred `slideshow.js` has built the deck leaves `courses.css:355`'s FOUC pre-hide in charge and the row goes RED on a correct build* | await `.slideshow-deck`, `beforeprint`, then `emulate_media` *(CSS)* | delete the §2d block; or keep only `display: block` without the `position`/`height`/`overflow` resets; or omit the `.slideshow-bar` hide |
| 16b | A slide in the **mid-fade state** prints at full opacity. The fixture **injects** that state via `page.evaluate` — take a non-active slide, remove its `hidden`, set `style.opacity = "0"` — rather than racing the real 320 ms fade, exactly as rows 5b/5c/19 inject their states. *Racing it cannot work in either direction: a polling read passes on the mutant, because `settleHidden` clears the inline opacity at `slideshow.js:147` and the slide falls back to `.slideshow-deck .slide { opacity: 1 }`; and a single immediate read would land mid-transition on the correct build. Injection removes the clock from the test entirely* | inject the state, then `beforeprint` + `emulate_media`, single non-polling read *(CSS)* | delete `opacity: 1 !important`; **separately**, delete `transition: none !important` (which alone leaves the correct build reading a fraction) |
| 16c | A mid-edit note on a **non-active slide** carries a **non-empty inline `style.height`** after the enter path. *The trigger's shape is what makes this falsifiable, and driving it naively breaks it: reaching a note's Edit control on slide 2 requires navigating there, which makes slide 2 **active and not `[hidden]`** — `scrollHeight > 0`, the un-hide branch never runs, the stamp lands anyway, and the row goes green on its own mutant. Slide 2 must be `[hidden]` at `beforeprint`. Asserted on the stamp, not on rendered height: with the un-hide step deleted the stamp is skipped and the CSS group alone still renders the textarea full-height on Chromium — so a rendered-height assertion here would be green on its own mutant, and would in fact be asserting exactly what row 7c asserts on a correct build. The user-visible loss this step prevents is Firefox/WebKit-only and therefore not observable in this suite* | multi-slide fixture; await `.slideshow-deck` **first**, then click Next to slide 2, open the note's inline edit, click Prev back to slide 1 and wait for `settleHidden` to re-add `[hidden]` to slide 2 (or inject the edit form on slide 2 via `page.evaluate`), then `beforeprint` *(event)* | delete the temporary-un-hide step, leaving only the skip-when-zero invariant |
| 17 | A panel the student opened by hand is **still open** after the leave path | `beforeprint`, then `afterprint` *(shared)* | make the leave path close all panels rather than only the recorded ones |
| 18 | Panels opened by print **are closed** after the leave path | `beforeprint`, then `afterprint` *(event)* | skip the removal loop |
| 19 | Clamp residue is removed from the panels print opened. The fixture **injects** `.note-card__body--clamp` and a `.note-card__more` via `page.evaluate` after the enter path, rather than waiting for `setupClamp` — §2e forbids depending on the async toggle, and an absence assertion would otherwise pass vacuously | `beforeprint`, inject, `afterprint` *(event)* | skip the de-clamp cleanup |
| 20 | A full enter/leave cycle with **no residue present** leaves the page usable: a **second** enter/leave cycle still opens and closes the panels. *This is the only row exercising the empty-cleanup branch; a leave path that throws on it would abort mid-restore and leave panels open* | two `beforeprint`/`afterprint` cycles *(event)* | make the cleanup throw when the class or button is absent |
| 20b | After the first enter the fixture **re-closes one swept panel** via `page.evaluate`; a **second** enter re-opens it, and one leave then closes exactly the recorded set. *The re-close is what makes this falsifiable: without it the first enter has already opened everything, a mode flag's early return is invisible, and both builds pass. Pins §2 responsibility 7* | `beforeprint`, re-close one panel, `beforeprint`, `afterprint` *(event)* | add an `entered` boolean that makes enter return early |
| 21 | For a dark-theme student, the computed `color` of lesson body text has a **contrast ratio ≥ 4.5:1 against `#FFFFFF`**. Correct build: `--text-primary` resolves to the light value (`#1E1C18`-family, ≈ 15:1). Mutant: `#F2EFE9`, ≈ 1.1:1 | `emulate_media` *(CSS)* | delete the `tokens.css` print override, **or** move it above the dark block at line 79 |
| 21b | A dark-theme lesson containing a **callout** prints its heading at a contrast ratio **≥ 4.5:1 against `#FFFFFF`**. Correct build: the light `.callout--*` value (`#2563c9` for `--example`, ≈5.7:1). Mutant: `#7db0f7`, ≈2.2:1 | `emulate_media`, dark theme *(CSS)* | delete the `courses.css` `--callout-accent` print block |
| 22 | A lesson using an author text colour prints `--tc-red` at a **contrast ratio ≥ 4.5:1 against `#FFFFFF`**. Correct build: the `:root` value, ≈ 6.4:1. Mutant: `#EA8A82`, ≈ 2.6:1 | `emulate_media`, dark theme *(CSS)* | omit the `--tc-*` group from the override set |

Rows 21–22 assert a **computed contrast ratio**, not "the colour changed" or "it is not white": on
the mutant build both values are non-white and non-transparent, so any loose predicate passes. The
thresholds above are the discriminator, in the same spirit as row 11's height threshold.

**Dark-theme fixture (rows 21–22).** Set the **user's stored theme** to `dark` before login, so the
server renders `data-theme-pref="dark"` and `data-theme="dark"`. Do **not** reach for the
`libli_theme` cookie: the prepaint script consults it only when **`data-theme-pref`** is absent, so a
cookie-based fixture on a server-rendered page silently does nothing and the assertion measures a light page — passing on a
build with the override deleted. Each row additionally asserts `data-theme` resolves to `dark` on the
loaded page, so a mis-wired fixture fails loudly instead of quietly.

Three measurement traps in this repo's history bear directly on rows 1, 2, 6 and 11, and must be
respected or the tests will pass on a broken build:

- **`bounding_box()` stays non-zero through a closed `<details>`** — measured 52.4×22 for a real
  element inside a closed group — and `querySelectorAll` counts it. The only correct discriminator is
  **`el.checkVisibility()` with no options**, which per spec returns `false` unconditionally when a
  flat-tree ancestor has `content-visibility: hidden`. (It exists in current Playwright Chromium, so
  the e2e needs no feature detection; `unit_nav.js:18`'s guarded pattern is for shipped code.)
- **Playwright reports a `.visually-hidden` element as VISIBLE** (1×1 with a zero clip rect, so its
  bounding box is non-empty). `expect(...).to_be_visible()` on `.note-card__on` therefore cannot
  fail, and `.note-card__on` must never stand in for the note body. Rows 1, 2 and 11 use
  `checkVisibility()` **plus** a numeric `bounding_box()["height"]` threshold, never bare presence.
- **`checkVisibility()` with no options returns `true` for `visibility: hidden`.** Its defaults are
  `contentVisibilityAuto: false, opacityProperty: false, visibilityProperty: false` — it is the right
  discriminator for `content-visibility` (the closed-`<details>` case above) and the wrong one for
  the two `<summary>` elements §3 suppresses with `visibility`. Rows 6a2 and 10b therefore measure
  `bounding_box()["height"]` instead. Using one method for both is how a row ends up RED on a correct
  build.
- **`wait_for_selector(sel)` defaults to `state="visible"`** and will hang on a clipped-but-present
  element; use `state="attached"`.

### Non-e2e

- **Template test:** `lesson_unit.html` passes `show_print=True`; `quiz_unit.html` and
  `quiz_results.html` do not. Mutant: render the button unconditionally in `_unit_strip.html`. This
  replaces an e2e row — rendering the template proves the absence without a login, a seeded quiz and
  a page load.
- **Token-parity test:** for **every** token name the `[data-theme="dark"]` block declares — the
  `--primary*`, `--accent*`, `--surface-*`, `--text-*`, `--border-*`, `--success*`, `--warning*`,
  `--danger*`, `--tc-*`, `--scroll-edge` and `--shadow-*` families — the `@media print` block
  declares the same name with `:root`'s declaration for it. `--scrim-solid` is excluded: it is
  declared only in `:root` (`tokens.css:49`), which an existing source-level test already enforces.
  `color-mix()` tokens are compared **by formula**, which is what makes the `--primary*` / `--accent*`
  family checkable.

  **Scope is repo-wide, not `tokens.css`-wide.** Every `[data-theme="dark"]` declaration in a shipped
  stylesheet needs a print counterpart or an explicit exclusion. The sweep found two sets that reach a
  printed lesson — `tokens.css:79` and `courses.css:2010–2014`'s `--callout-accent` — and three that
  do not: `error.css:50`, `editor.css:924`, `tags.css:329`. The test names those exclusions
  explicitly, so a later reader can tell "checked and excluded" from "missed", and it fails if a
  **new** `[data-theme="dark"]` rule appears in a shipped sheet without being classified.

  Lives in **`tests/test_print_tokens_css.py`** (new), not in `test_text_colour_css.py`, and must
  **not** reuse that file's `_block()` helper: `re.search(re.escape(selector) + r"\s*\{(.*?)
\}")`
  takes the *first* match, so with two `[data-theme="dark"]` blocks in the file it would compare the
  screen block against itself and pass vacuously. The contract is that the print block is located via
  its `@media print` wrapper and the screen block by its position before line 79. Mutants: change one
  value; omit the `--primary*` family entirely; **and** make both selectors resolve to the same block
  — that third one must turn the test RED, or the test is not doing its job.
- **CSS deletion tripwire** in `tests/test_notes_presentation.py`: the shipped `notes.css` contains
  the print block. Framed as a *wholesale-deletion* tripwire only — a substring assertion cannot
  detect the specificity failure the §3 table warns about, since a rule can be present and inert.
  Cascade-level confirmation comes from the e2e A/B (rows 5a–c, 15, 16 measured with and without the
  rule), per the project rule that a CSS claim needs an A/B, not a measurement.
- **i18n:** all **three** new msgids (`My note`, `added %(date)s`, `edited %(date)s`) reach the `pl`
  catalogue with the §6 translations, each asserted **non-empty and non-fuzzy** — the state `makemessages` leaves behind would otherwise ship green.
  The `Print` half is asserted as a new **source reference** on the existing entry, not as a new
  msgid; asserting the msgid exists would pass on a build where the `{% trans %}` was never added.

### Not automatically verified

`break-inside: avoid` cannot be observed by `emulate_media`, which does not paginate. It is covered
by the deletion tripwire only, plus a **manual print-preview check in light and dark** before the PR
is opened. This is stated rather than quietly assumed, so the gap is visible.

### Test-run mechanics

`-m e2e` is mandatory or the e2e tests deselect and the run exits 5; the test-DB container must be
started first; `pytest`'s exit code can report 0 with failures present, so the summary line must be
grepped rather than the exit code trusted. Runs stay scoped to the affected tests, not the whole
suite.
