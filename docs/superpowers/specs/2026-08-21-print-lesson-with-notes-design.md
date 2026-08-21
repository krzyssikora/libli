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

**No-JS gating, and the cascade trap it creates.** The button's only behaviour is `window.print()`,
so with JS off it is a rendered dead control — worse than no affordance. `base.html:15` already adds
a `js` class to `documentElement` in its prepaint script, so the button is gated on it:

```css
.unit-strip__print { display: none; }
html.js .unit-strip__print { display: inline-flex; }
```

That gate is **(0,2,1)**. The existing print rule beside it is `.unit-strip__edit { display: none; }`
at (0,1,0), which works only because nothing gates `.unit-strip__edit`. A print rule for the new
button written at (0,1,0) would **lose to its own gate** and the button would print on paper. The
print declaration must therefore match or beat (0,2,1) — see §3.

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
3. **Sweep only panels that carry note content.** `_block_notes.html` renders an
   `<aside class="block-notes">` for **every** element on the page, whether or not it has notes; a
   note-less panel contains a `<p class="block-notes__add-label">Add a note</p>` and a composer.
   Opening all of them would print an "Add a note" line under every block of a fifty-block lesson.
   The filter must also admit a panel whose note is mid-edit, because the inline-edit path
   *replaces* the card with a form (`notes.js:316`, `card.replaceWith(form)`) so no `.note-card`
   remains there (§2b):

   ```js
   panels = [...document.querySelectorAll(".block-notes__panel:not([open])")]
              .filter(p => p.querySelector(".note-card, .note-composer--edit"));
   ```

   plus the `.unanchored-notes > details` when it exists and is closed (it is rendered only when
   `unanchored_notes` is non-empty, and its notes are exactly the ones whose block was deleted — they
   must print, or the printout silently loses them).
4. **Record what it opened.** A module-local array, so a panel the student had already opened is
   never closed behind their back.
5. **Restore on the leave path** — remove `open` from precisely the recorded elements, clear the
   list, and undo the `setupClamp` residue (§2c).
6. **Two dispatchers, one state machine.** Safari fires `beforeprint`/`afterprint` unreliably, so
   `matchMedia("print")` change events drive the same enter/leave handlers. The guard is a
   module-local **`entered` boolean** (not "the array is non-empty", which cannot distinguish a
   completed cycle from a leave that fired before any enter): enter returns early when `entered` is
   true, leave returns early when it is false, and the recorded array is cleared on leave. The
   `matchMedia` listener routes on `e.matches` — `true` → enter, `false` → leave.

The theme is **not** handled here — see §4.

#### 2a. `positionPop` writes an inline `top` — a cascade hazard, not a paper defect

`notes.js` listens for `toggle` **in the capture phase** (`notes.js:531`) and, when a
`.block-notes__panel` opens, calls `positionPop`, which sets `pop.style.top = handle.offsetTop + "px"`
(`notes.js:522`) and may add `.block-notes__pop--clamped`.

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

#### 2b. A note being edited is not a `.note-card`

`notes.js`'s inline-edit path calls `card.replaceWith(form)` (`notes.js:316`), building a
`form.note-composer.note-composer--edit`; the card is **detached** for the duration and restored by
`form.replaceWith(card)` on cancel (`notes.js:309`).

Two consequences: the §2 sweep filter must accept `.note-composer--edit` (done above), and the §3
control-hiding rule must **not** blanket-hide `.note-composer`, or a student who presses `Ctrl+P`
mid-edit loses that note from the printout entirely. §3 hides
`.note-composer:not(.note-composer--edit)` and prints the edit form's textarea readably.

#### 2c. `setupClamp` truncates long notes to 6 lines, and leaves DOM residue

The same `toggle` handler calls `setupClamp` (`notes.js:97`), which adds `.note-card__body--clamp`
to every note body — `-webkit-line-clamp: 6; overflow: hidden` (`notes.css:186`) — and
`insertAdjacentElement`s a `<button class="note-card__more">` after each body that overflows.

Two consequences, both this feature's to fix:

- **In print:** every note longer than six lines is silently truncated — the feature would destroy
  the exact content it exists to preserve. Undone in CSS (§3).
- **After print:** the clamp classes and the injected buttons **persist in the live DOM** once the
  leave path closes the panels, and the print CSS no longer applies to them. The student is left with
  clamped notes and *Show more* buttons they never asked for. So the leave path must also remove
  `.note-card__body--clamp` and any `.note-card__more` from **the panels `print.js` opened** — panels
  the student opened by hand were clamped by their own gesture and are left alone.

#### 2d. Slideshow lessons print one slide — the hole in the existing print story

`courses.css:348` sets `html.js [data-slideshow] > .slide:not(.is-active) { display: none; }`, and
`slideshow.js:148` additionally sets the `hidden` **attribute** on every inactive slide. There is
**no `@media print` reveal for slides** — the only print-time slide handling in the repo is the
carousel block at `courses.css:1852`, whose own comment reads *"printing a carousel silently loses
every slide but the current one"*. That exact defect is live for slideshows and nobody has fixed it.

So a multi-slide lesson prints **only the active slide** today, and this feature would faithfully
open the note panels on slides that never paint. A student printing an annotated slideshow lesson
would get one slide and a fraction of their notes.

**In scope**, on the same reasoning as §4: shipping a Print button that silently drops most of the
lesson is shipping a broken feature. The fix mirrors the tabs/carousel precedent directly:

```css
@media print {
  html.js [data-slideshow] > .slide,
  html.js [data-slideshow] > .slide[hidden] { display: block !important; }
}
```

Both selectors and `!important` are required for the same reason the tabs comment gives: the screen
rules are `html.js [data-slideshow] > .slide:not(.is-active)` and the `[hidden]` attribute, and a
half-reveal leaves either the class-hidden or the attribute-hidden slides missing. It belongs in
`courses.css` beside the existing slideshow rules, not in `notes.css`.

#### 2e. `toggle` is asynchronous — the mitigations must be order-independent

The HTML specification queues a task for the `<details>` toggle event; it does not fire synchronously
on assignment. Whether that task runs before the browser snapshots the print document is
engine-dependent, so `positionPop` / `setupClamp` may run during the print pass, after it, or — if
the leave path already closed the panel, since the handler re-checks `panel.open` — not at all.

Two requirements follow. The §2a mitigation must be **CSS**, which applies whenever the declarations
land and needs no ordering guarantee (this is the decisive reason to prefer it over clearing
`pop.style.top` in JS). And **no test may assert that the toggle side effects happened** — only that
the printed result is correct either way. The §2c leave-path cleanup is written to be a no-op when
the side effects never ran, and its test establishes the residue deterministically rather than
waiting for `setupClamp` (see Testing).

### 3. The print stylesheet — a new `@media print` block at the end of `notes.css`

The file currently has none.

#### Specificity is the load-bearing constraint

`@media print` adds **no** specificity — `courses.css:1346` already records this lesson in a comment.
The rules being undone are not weak:

| Rule to undo | Selector | Weight |
|---|---|---|
| pop floats into the margin (`notes.css:90–107`) | `.notes-js .block-notes__panel[open] .block-notes__pop` | (0,4,0) |
| pop clamped to the right (`notes.css:110–113`) | `.notes-js .block-notes__panel[open] .block-notes__pop--clamped` | (0,4,0) |
| Print button's no-JS gate (§1) | `html.js .unit-strip__print` | (0,2,1) |
| inline `top` from `positionPop` | — | inline |

So a print rule written at (0,1,0) is **inert regardless of source order**, and a mutant written at
(0,1,0) is equally inert and will mislead. Every print declaration that undoes one of the above must
either **match the original selector's weight or beat it**, or carry `!important`; the inline `top`
needs `!important` unconditionally.

If any `.visually-hidden` element is ever revealed in print, **all nine** of its declarations must be
reset — the class is defined three times (`app.css:1384` with six declarations, `notes.css:4` and
`tags.css:6` with nine each, adding `padding: 0`, `margin: -1px`, `border: 0`) and `lesson_unit.html`
loads all three sheets. The `.tabs__panel-label` reveal at `courses.css:1858` is the precedent for a
complete reset. §3 deliberately avoids needing this by using a real element for the label, below.

#### Scoping — the card rules are NOT lesson-only by construction

`_note_card.html` is included by exactly two templates, `_block_notes.html` and `_unanchored.html`,
both inside `<article class="lesson">`. **But the print block is written against classes, not
templates**, and `notes/templates/notes/course_notes.html` — the notes hub — also loads `notes.css`
and renders `.note-card`, `.note-card__body` and `.note-card__meta` via `_readonly_note_card.html`.
An unscoped rule hiding the relative date would strip the **only** date from the hub's printout,
where no `.note-card__print-date` and no label element exist to replace it. The hub is a page a
student is likely to print.

Therefore every card-level print rule is scoped to `.lesson` (e.g. `.lesson .note-card__meta-rel`),
which also raises its weight usefully. Rules that apply to elements existing only inside a lesson
(`.block-notes__*`, `.unanchored-notes`) need no scoping but take it for consistency. The hub's
printout is unchanged by this feature.

#### The block must

- **Return the pop to flow.** Reset every property the (0,4,0) rule sets, not just the positioning
  ones: `position`, `top` (`!important`, per the inline style), `left`, `right`, `width`,
  `margin-top`, `padding`, `background`, `border`, `max-height`, `overflow-y`, `z-index` and
  `box-shadow`. `right` is named explicitly because `.block-notes__pop--clamped` sets
  `left: auto; right: 0`: resetting `left` alone leaves `right: 0` applied. A partial reset leaves the
  pop printing as a bordered, padded floating card flush against its block, which is not "in flow".
- **Un-clamp bodies.** `.note-card__body--clamp { display: block; -webkit-line-clamp: none;
  overflow: visible; }`, and hide `.note-card__more`.
- **Hide every control, except a note being edited.** `.block-notes__handle` (the toggle icon),
  `.note-card__actions` (edit / delete), `.block-notes__add-more` ("Add another note", rendered
  whenever a block *has* notes), `.block-notes__add-label` ("Add a note"), and
  **`.note-composer:not(.note-composer--edit)`**. The `:not()` is required by §2b. For the edit form
  that survives, hide `.note-composer__actions` and print `.note-composer__input` readably —
  `border: 0; resize: none; height: auto;` — so a mid-edit note prints as text rather than as a
  form control.
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
- **Style the unanchored section.** `.unanchored-notes` carries a dashed border and raised
  background, and its `<summary class="unanchored-notes__handle">` renders a literal `⚠` glyph plus
  "N notes whose block was removed" — screen chrome, and a bare glyph against the project's
  monochrome-SVG convention. In print the summary is **hidden** and the dashed container is flattened
  to a plain rule; the notes themselves print as ordinary cards at the end of the lesson. Their
  provenance is already carried by the `MY NOTE` label.

The Print button's print rule goes **inside** the existing block at `courses.css:2308`, at a weight
that beats its (0,2,1) gate:

```css
/* Affordances for a second browser tab and for the print dialog are noise on paper. */
@media print { .unit-strip__edit, html.js .unit-strip__print { display: none; } }
```

Inside, not beside: a rule placed next to the block rather than within it would hide the Print button
on screen as well — the entire affordance — and would look almost identical in review. The comment
at `courses.css:2307` currently reads "An affordance for a second browser tab is noise on paper." and
describes `.unit-strip__edit` only; it is rewritten as above, **line-count neutral**.

#### The `MY NOTE` label — decided

`_note_card.html` gains a print-only element:

```html
<p class="note-card__print-label" aria-hidden="true">{% trans "My note" %}</p>
```

Sentence case in the msgid, matching the catalogue's existing `Add a note` / `Edit note` /
`Delete note`; the shouting is presentation, applied in the print block as
`text-transform: uppercase; letter-spacing: .08em`, exactly the `.ba__side-heading` treatment at
`courses.css:2113`. Hidden on screen (`display: none` in the base block), revealed in print.

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
  <span class="note-card__print-date">{{ note.updated|date:"SHORT_DATE_FORMAT" }}</span>
</p>
```

Both phrasings already read **`note.updated`** — `note.created` is never rendered — so the print date
uses `note.updated` too, for consistency with the relative form it replaces. Localised by Django's
`L10N` / `DATE_FORMAT` machinery, **not** through `gettext`: a date *format* is not a translatable
message, and routing it through the catalogue is the easily-wrong choice.

In the print block, scoped to `.lesson`: `.note-card__meta-rel` is hidden and
`.note-card__print-date` is revealed. `_readonly_note_card.html` (the hub) is **not** edited and
keeps its bare text node, so the `.lesson` scope is what stops the hub losing its date.

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
of `tokens.css`. §3 devotes a subsection to exactly this hazard; the same discipline applies here.

**The override set is larger than "surfaces and text."** `[data-theme="dark"]` also redefines the
four author-selectable **body-text** colours as light tints — `--tc-red: #EA8A82`,
`--tc-blue: #8FBCE8`, `--tc-green: #9FBF7B`, `--tc-orange: #E8B761` — plus `--success`, `--warning`,
`--danger`, their `-subtle` partners, and the `--primary*` / `--accent*` family. Omitting the `--tc-*`
group would leave a lesson with coloured text still printing near-white-on-white, which is the very
defect this section exists to fix, only narrower. The print block enumerates the **full** set of
literal tokens the dark block declares.

Two tokens need explicit handling: `--scrim-solid` is declared **only** in `:root` (`tokens.css:49`),
never in the dark block, so it is not part of the override set; and the `color-mix()`-derived tokens
re-resolve automatically once the surfaces they reference are overridden, so they are restated only
where the dark block gives them a *different formula*, not merely a different result.

The cost is that the light literals are stated twice. That is pinned by a parity test (see Testing)
comparing the print block against `:root`'s **literal** declarations, so the two cannot drift.

This is a pre-existing, site-wide defect pulled into this branch because shipping a Print button that
yields a blank page for every dark-theme student would be shipping a broken feature. It remains
separable: the notes work stands without it.

### 5. Degradation (no JS)

With JS off, `notes.js` never adds `.notes-js`, the panels stay closed, and the Print button is
hidden by the `html.js` gate in §1 rather than rendered dead.

The no-JS route is the existing `?notes=1` query parameter, which **already works today**:
`_block_notes.html` server-renders `<details … open>` when `notes_show` is set and the block has
notes, so `…/u/<pk>/?notes=1` followed by `Ctrl+P` prints a lesson with its notes open, with no JS at
all. Because §4's theme fix is CSS, this route is correct in dark theme too. The §2d slide reveal is
gated on `html.js`, which is absent without JS — and so is the screen rule that hides inactive
slides, so all slides print. No new server-side work is required for this route.

### 6. i18n

**One** new msgid: `My note` (§3). `Print` (§1) is **not** new — `msgid "Print"` already exists at
`locale/pl/LC_MESSAGES/django.po:5231` with `msgstr "Drukuj"`, referenced from
`analytics_matrix.html` and `gradebook_print.html`; `makemessages` will only add a `#:` source
reference to that entry. The absolute date is not on this list either: it is a Django format, not a
msgid (§3).

Two known hazards apply to the one genuinely new entry: `makemessages` pre-fills fuzzy entries with a
**wrong** translation, and clearing one requires deleting **both** the `#, fuzzy` marker and the
bogus `msgstr`; and the binary `.mo` must be regenerated at the end rather than carried stale through
a long branch.

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
                        entered ? return : entered = true
                                 │
                  ┌──────────────┴───────────────┐
                  ▼                              ▼
      open the closed panels containing      record exactly which
      .note-card or .note-composer--edit,    elements were opened
      plus .unanchored-notes > details
                                 │
                                 ▼
              (notes.js's capture-phase toggle handler MAY run,
               now or later or never — §2e: positionPop stamps an
               inline top and may add --clamped; setupClamp clamps
               bodies to 6 lines and injects Show-more buttons)
                                 │
                                 ▼
        @media print in notes.css (scoped .lesson) undoes both,
        order-independently, at (0,4,0)+/!important; hides handle /
        actions / add-more / add-label / non-edit composer; resets
        is-dimmed / is-highlighted; reveals My note + the absolute
        date and hides the relative one.
        @media print in courses.css reveals every slideshow slide
        and hides the Print button at (0,2,1).
        @media print in tokens.css supplies the light palette.
                                 │
                                 ▼
                       browser paints the sheet
                       (or writes the PDF)
                                 │
                                 ▼
            'afterprint'  OR  matchMedia change (e.matches === false)
                                 │
                        entered ? entered = false : return
                                 │
                    close exactly the panels we opened; strip
                    .note-card__body--clamp and .note-card__more
                    from inside them; clear the array. Theme and
                    slides need no restore — never mutated.
```

## Error handling

- **The leave path never fires** (a known browser inconsistency, notably on a cancelled print job).
  The page would be left with panels open and clamp residue inside them. Mitigation: both dispatchers
  drive the same handlers through the `entered` guard, so whichever arrives restores the page.
  Because the theme and the slide reveal are CSS-only, no visual state can be stranded.
- **The toggle side effects never ran** (§2e). The leave-path cleanup removes classes and elements
  that may not exist; it must be written as a no-op in that case, not an error.
- **A student had panels open before printing.** Handled by construction: `print.js` records only the
  panels it opened itself, and restores and de-clamps only those.
- **A note is mid-edit when printing** (§2b). The edit form survives the control-hiding rule and its
  textarea prints as text; the note is not lost.
- **A multi-slide lesson** (§2d). All slides print, so notes on every slide are reachable.
- **No JS.** The button is hidden rather than dead, and `?notes=1` is the working alternative (§5).
- **A unit with no notes.** The button still prints, producing the lesson exactly as it prints today.
  Because the sweep is filtered, no note-less panel is opened and no "Add a note" furniture is
  emitted.

## Testing

The house rule applies: **falsify the tests, do not merely run them.** Each assertion below is paired
with the mutant that must turn it RED, chosen from the failure mode it is meant to catch.

### How print state is entered in a test — pin this first

`page.emulate_media(media="print")` **only** re-evaluates CSS media queries. It does **not** dispatch
`beforeprint`, and `window.print()` is a no-op in headless Chromium. So neither one alone can drive
these tests:

- **CSS-only assertions about elements outside a `<details>`** need `emulate_media` alone.
- **Anything inside `.block-notes__pop`** — which is inside `::details-content` — additionally needs
  the panels open, or `checkVisibility()` returns `false` on a **correct** build and the assertion is
  either red-on-green or unfalsifiable. Such rows use `emulate_media` **plus** an explicit
  `page.evaluate("window.dispatchEvent(new Event('beforeprint'))")`.
- **Leave-path assertions** dispatch `afterprint` the same way.

The two dispatchers are exercised distinctly: the **event** route via explicit `dispatchEvent`, and
the **media** route via `emulate_media(media="print")` alone with no dispatch — which is a real
`matchMedia("print")` change and therefore genuinely drives the second listener. Because the media
route is also the trigger the CSS-only rows use, only row 2 asserts JS behaviour under it; its mutant
(deleting the `matchMedia` registration) is the only one that kills it, since the CSS rows do not
depend on any listener.

The `matchMedia` handler routes on `e.matches` (§2 responsibility 6), so a synthetic
`mql.dispatchEvent(new Event("change"))` — which carries no `matches` — must **not** be used; it
would take the leave path and go red on a correct build.

### e2e — `tests/test_e2e_print_lesson_notes.py` (new, `pytestmark = pytest.mark.e2e`)

Fixtures follow the pattern already proven in `tests/test_e2e_notes.py`: allauth
`input[name='login']`, `TEST_PASSWORD`, `seed_roles()`, `published=True` on the unit.

| # | Assertion | Trigger | Mutant that must make it RED |
|---|---|---|---|
| 1 | A note body is **genuinely visible** after the event route | explicit `beforeprint` dispatch | delete the `beforeprint`/`afterprint` listener registration |
| 2 | A note body is **genuinely visible** after the media route | `emulate_media` only | delete the `matchMedia` listener registration |
| 3 | Clicking the **real button** calls `window.print()` (stubbed via `add_init_script` to set a flag) | real click, no `page.evaluate` shortcut | delete the click listener |
| 4 | A note body longer than 6 lines prints **in full** | `emulate_media` + `beforeprint` | delete the un-clamp rule |
| 5a | `.block-notes__pop` is `position: static` in print at a ≥1200px viewport | `emulate_media` + `beforeprint` | delete the `position` reset, **or** re-write it at (0,1,0) |
| 5b | An inline `top` set by the fixture is overridden | fixture sets `pop.style.top` via `page.evaluate`, then `beforeprint` | drop `!important` from the `top` reset |
| 5c | `right: 0` from `--clamped` is overridden | fixture adds `block-notes__pop--clamped` via `page.evaluate`, then `beforeprint` | delete the `right` reset |
| 6 | `.block-notes__handle`, `.note-card__actions`, `.note-composer`, `.block-notes__add-more`, `.block-notes__add-label` are all **not** visible | `emulate_media` + `beforeprint` | delete the control-hiding rule |
| 7 | A note **mid-edit** still prints its text | open inline edit, then `emulate_media` + `beforeprint` | drop the `:not(.note-composer--edit)` from the hide rule |
| 8 | A **note-less** block prints no note furniture at all | `emulate_media` + `beforeprint` | drop the filter from the sweep (open every panel) |
| 9 | The **unanchored** notes section prints (fixture: a note whose element was deleted) | `emulate_media` + `beforeprint` | drop `.unanchored-notes > details` from the sweep |
| 10 | The `My note` label is visible in print and **absent on screen** | `emulate_media` + `beforeprint` | delete the label reveal rule |
| 11 | The absolute date is visible in print and `.note-card__meta-rel` is **not** | `emulate_media` + `beforeprint` | delete the date reveal / relative-hide rule |
| 12 | The notes **hub** (`course_notes.html`) still prints its relative date | `emulate_media` on the hub | drop the `.lesson` scope from the relative-hide rule |
| 13 | Blocks are **not** dimmed in print after a note card is focused | focus a card, then `emulate_media` | delete the `.is-dimmed` reset |
| 14 | The Print button is **visible on screen** on the lesson page and **not** in print | screen, then `emulate_media` | move the rule outside the block, **or** write it at (0,1,0) so its own `html.js` gate wins |
| 15 | **Every slide** of a multi-slide lesson prints, and a note on slide 2 is visible | `emulate_media` + `beforeprint` | delete the §2d slide reveal, or reveal only `[hidden]` and not `:not(.is-active)` |
| 16 | A panel the student opened by hand is **still open** after the leave path | `beforeprint` then `afterprint` | make the leave path close all panels rather than only the recorded ones |
| 17 | Panels opened by print **are closed** after the leave path | `beforeprint` then `afterprint` | skip the removal loop |
| 18 | Clamp residue is removed from the panels print opened. The fixture **injects** `.note-card__body--clamp` and a `.note-card__more` via `page.evaluate` after the enter path, rather than waiting for `setupClamp` — §2e forbids depending on the async toggle, and an absence assertion would otherwise pass vacuously on a build with the cleanup deleted | `beforeprint`, inject, then `afterprint` | skip the de-clamp cleanup |
| 19 | For a dark-theme student, printed text colour is **dark**; fixture must produce `data-theme-pref="dark"`, not `auto` | `emulate_media` | delete the `tokens.css` print override, **or** move it above the dark block at line 79 |
| 20 | A lesson using an author text colour (`--tc-red`) prints it dark enough to read | `emulate_media`, dark theme | omit the `--tc-*` group from the override set |

Three measurement traps in this repo's history bear directly on assertions 1, 2, 6 and 10, and must
be respected or the tests will pass on a broken build:

- **`bounding_box()` stays non-zero through a closed `<details>`** — measured 52.4×22 for a real
  element inside a closed group — and `querySelectorAll` counts it. The only correct discriminator is
  **`el.checkVisibility()` with no options**, which per spec returns `false` unconditionally when a
  flat-tree ancestor has `content-visibility: hidden`. (It exists in current Playwright Chromium, so
  the e2e needs no feature detection; `unit_nav.js:18`'s guarded pattern is for shipped code.)
- **Playwright reports a `.visually-hidden` element as VISIBLE** (1×1 with a zero clip rect, so its
  bounding box is non-empty). `expect(...).to_be_visible()` on `.note-card__on` therefore cannot
  fail, and `.note-card__on` must never stand in for the note body. Assertions 1, 2 and 10 use
  `checkVisibility()` **plus** a numeric `bounding_box()["height"]` threshold, never bare presence.
- **`wait_for_selector(sel)` defaults to `state="visible"`** and will hang on a clipped-but-present
  element; use `state="attached"`.

### Non-e2e

- **Template test:** `lesson_unit.html` passes `show_print=True`; `quiz_unit.html` and
  `quiz_results.html` do not. Mutant: render the button unconditionally in `_unit_strip.html`. This
  replaces an e2e row — rendering the template proves the absence without a login, a seeded quiz and
  a page load.
- **Token-parity test:** for **each token name the `[data-theme="dark"]` block declares as a
  literal** (the `--surface-*`, `--text-*`, `--border-*`, `--success*`, `--warning*`, `--danger*`,
  `--tc-*`, `--scroll-edge` and `--shadow-*` families), the `@media print` block declares the same
  name with the value `:root` gives it. `--scrim-solid` is excluded — it is declared only in `:root`
  (`tokens.css:49`), which an existing source-level test already enforces. `color-mix()`-derived
  tokens are compared by formula, not resolved value, and are only required where the dark block
  supplies a different formula. Mutant: change one value in the print block.
- **CSS deletion tripwire** in `tests/test_notes_presentation.py`: the shipped `notes.css` contains
  the print block. Framed as a *wholesale-deletion* tripwire only — a substring assertion cannot
  detect the specificity failure the §3 table warns about, since a rule can be present and inert.
  Cascade-level confirmation comes from the e2e A/B (assertions 5a–c and 14 measured with and without
  the rule), per the project rule that a CSS claim needs an A/B, not a measurement.
- **i18n:** `My note` reaches the `pl` catalogue as a new msgid. The `Print` half is asserted as a
  new **source reference** on the existing entry, not as a new msgid — asserting the msgid exists
  would pass on a build where the `{% trans %}` was never added.

### Not automatically verified

`break-inside: avoid` cannot be observed by `emulate_media`, which does not paginate. It is covered
by the deletion tripwire only, plus a **manual print-preview check in light and dark** before the PR
is opened. This is stated rather than quietly assumed, so the gap is visible.

### Test-run mechanics

`-m e2e` is mandatory or the e2e tests deselect and the run exits 5; the test-DB container must be
started first; `pytest`'s exit code can report 0 with failures present, so the summary line must be
grepped rather than the exit code trusted. Runs stay scoped to the affected tests, not the whole
suite.

Edits to existing comments — `courses.css:2307` (rewritten above to cover both selectors) and
`courses.css:2102` (which enumerates what print hides and should gain `.unit-strip__print`) — must be
**line-count neutral**, so the many line-number citations in neighbouring comments and in this spec
do not rot.
