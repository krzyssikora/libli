# Slideshow deck redesign

## Purpose

The unit-level slideshow mode (shipped in PR #82) works, but its taking-page
presentation has two rough edges the author flagged:

1. **The nav buttons carry visible text labels** (`Prev`/`Next` in English,
   `Poprzednie`/`Następna` in Polish). The Polish pair is grammatically
   inconsistent — *"Poprzednie"* is neuter-plural while *"Następna"* is
   feminine-singular, so they do not agree. The buttons already render chevron
   SVGs; the text is redundant chrome that also forces this per-language
   grammar problem.

2. **The nav bar has no stable position.** `slideshow.js` inserts the bar in
   normal document flow *after* the last slide, and only one slide is visible at
   a time (the rest are `display:none`). So the bar's vertical position tracks
   the height of whichever slide is showing — it jumps up on a short slide and
   drops on a tall one. There is also no visual sense of a "deck": slides
   hard-swap with no transition, and each slide reads as loose stacked blocks
   rather than one framed stage.

This feature restyles the slideshow taking view into a **fixed-height framed
deck** with **arrow-only navigation** and a **cross-fade** between slides. It is
a presentation-layer change only: no model, no server-side partitioning, no quiz
answering/marking, and no builder changes. Everything new is gated behind
`html.js` + the JS-built deck, so the **no-JS fallback is unchanged** (JS off →
all slides stacked = today's flat page).

### Out of scope

- **Clickable progress dots / jump-to-slide.** Dots are a non-interactive
  position indicator; navigation stays arrows + keyboard only. Jump-to-slide is
  a possible future enhancement.
- **The quiz results/review page** stays flat — this touches only the *taking*
  view, exactly as the original slideshow feature scoped it.
- **Any change to slide partitioning, `SlideBreakElement`, mark-seen, quiz
  Finish gating, or MathLive/GeoGebra re-measure.** These behaviors are
  preserved verbatim; only their surrounding chrome changes.

## Architecture / components

The whole change lives in four files:

- `courses/static/courses/js/slideshow.js` — builds the deck DOM, arrow-only
  buttons, dots/counter, and drives the cross-fade.
- `courses/static/courses/css/courses.css` — the `.slideshow-deck` /
  `.slideshow-stage` / restyled `.slideshow-bar` rules, all token-driven and
  light/dark aware.
- `templates/courses/lesson_unit.html` and `templates/courses/quiz_unit.html` —
  the inline `window.SLIDESHOW_I18N` strings (label text change only).
- `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`) — new/updated Polish
  translations for the accessible labels.

### 1. Arrow-only buttons with preserved accessible name

Today `iconBtn()` builds each button as chevron SVG **plus** a visible
`<span>` whose text is the button's accessible name. The redesign drops the
visible `<span>` and instead sets the translated label as an **`aria-label`** on
the button. The chevron SVG stays `aria-hidden` as today.

Consequences:

- Screen readers still announce a name for each button (now from `aria-label`).
- Playwright's `get_by_role("button", name=...)` matches the accessible name by
  **case-insensitive substring** (its default), so the existing e2e assertions
  that query `name="Next"` keep matching an `aria-label` of `"Next slide"`. This
  substring behavior is load-bearing for backward-compatible tests and is
  asserted explicitly (see Testing).

The label **strings** change to read cleanly as standalone accessible names in
both languages, which is what removes the Polish grammar inconsistency:

| Key    | EN (msgid)       | PL (msgstr)        |
|--------|------------------|--------------------|
| `prev` | `Previous slide` | `Poprzedni slajd`  |
| `next` | `Next slide`     | `Następny slajd`   |
| `nav`  | `Slides`         | `Slajdy` (existing)|

The `nav` string remains the `<nav aria-label>` for the control bar. Because the
`prev`/`next` msgids change (`Prev`→`Previous slide`, `Next`→`Next slide`), this
requires a `makemessages` + `compilemessages` pass; the old `Prev`/`Next`
entries become obsolete. Watch the fuzzy-flag gotcha (per the repo's
`uv run` tooling note) — the two new PL msgstrs must be set and **not** left
`#, fuzzy`, or Django ignores them and falls back to the English msgid.

### 2. The fixed-height framed deck (structure)

`slideshow.js` currently inserts only the `.slideshow-bar` after the last slide.
The redesign has it build a **deck wrapper** so the stage and the bar form one
bordered card and the bar sits at a constant position:

```
<div class="slideshow-deck">          <!-- bordered card: surface-raised + shadow -->
  <div class="slideshow-stage">       <!-- fixed height; position:relative -->
    <div class="slide is-active">…</div>   <!-- position:absolute; inset:0; overflow-y:auto -->
    <div class="slide" hidden>…</div>
    …
  </div>
  <nav class="slideshow-bar">…footer: ‹  · dots/counter ·  ›…</nav>
</div>
```

Build sequence in JS (all client-side; runs only when `slides.length > 1`):

1. Create `deck` and `stage`; insert `deck` into the article at the position the
   first `.slide` currently occupies (i.e. before the trailing unanchored-notes
   block), so document order is preserved.
2. **Move** every existing `.slide` node into `stage` (they keep their
   `data-element-id` children, so mark-seen and all element wiring are
   untouched).
3. Build the `.slideshow-bar` (arrow buttons + position indicator) and append it
   to `deck` as the footer.

Because only the `.slide` nodes move — not the unit head, the completion pill,
the quiz Finish form, or the unanchored notes — those remain in the article
outside the deck and behave exactly as before.

**Fixed height (the core fix).** `.slideshow-stage` gets a constant height
`clamp(360px, 62vh, 640px)` — constant for a given viewport, so the footer bar
sits at the same vertical position on every slide. Each `.slide` is
`position:absolute; inset:0; overflow-y:auto`: short slides show with whitespace
(content vertically centered), slides taller than the stage **scroll inside the
stage**. On every slide change the active slide's `scrollTop` resets to 0.

The absolute-positioned, stacked slides are also what makes the cross-fade
possible (both slides occupy the same box during the transition).

### 3. The restyled bar — arrows + position indicator

- **Arrow buttons**: icon-only, ~34px square, token-styled (border +
  `--surface-raised`; the Next button uses `--primary` as the primary action,
  Prev is neutral). Disabled state (first/last slide) keeps today's reduced
  opacity + `pointer-events:none`. The chevron paths are unchanged
  (`M15 6l-6 6 6 6` / `M9 6l6 6-6 6`).
- **Position indicator**: **progress dots** when `slides.length <= 12` — one dot
  per slide, the active dot elongated (pill), all `aria-hidden` (decorative).
  When `slides.length > 12`, dots would overflow, so fall back to a **text
  counter** (`N / total`, tabular-nums) instead — the same terse counter used
  today.
- **Accessibility of position**: a visually-hidden live region
  (`role="status" aria-live="polite"`) always announces `"Slide N of total"` on
  each change, regardless of whether dots or the counter are shown. In the
  `>12` case the visible counter can double as this live region; in the dots
  case the live region is a separate visually-hidden span. This preserves the
  screen-reader position announcement that today's `role=status` counter
  provided.

### 4. Cross-fade transition

`show(n)` drives the transition instead of an instant swap:

- The incoming slide is made visible at `opacity:0` on top of the outgoing one;
  a forced reflow then transitions the outgoing slide to `opacity:0` and the
  incoming to `opacity:1` over ~320ms, after which the outgoing slide is
  `hidden`.
- Dots/counter, disabled states, `onReveal()` (mark-seen + quiz-finish gate +
  widget re-measure) fire on the incoming slide as they do today. `onReveal`
  timing is unchanged relative to the slide becoming active.
- **`prefers-reduced-motion: reduce`** collapses the transition to an instant
  swap (CSS `transition:none` under the media query). This is handled in CSS, so
  it applies no matter what and needs no JS branch.

## Data flow

Unchanged from the shipped slideshow feature. The server still partitions
elements into `slides` groups and renders them into `.slide` wrappers inside the
article (`build_lesson_context` / `build_quiz_context`, `_lesson_article.html` /
`_quiz_article.html`). `slideshow.js` is still a pure client-side view over that
server-rendered DOM. Mark-seen still POSTs join-row pks to `data-seen-url` on
reveal (lessons); the quiz Finish form is still gated to the last slide. The only
difference is the DOM shape the script builds and how it animates between slides.

## Error handling

- **No-JS**: `slideshow.js` never runs, no deck is built, the CSS deck rules
  (scoped to the JS-built `.slideshow-deck`) never apply → all slides render
  stacked in normal flow = today's flat page. The pre-JS anti-FOUC rule (show
  only the first slide until the script runs) is preserved.
- **Degenerate single-slide unit**: the existing `slides.length <= 1` guard
  returns early → no deck, no bar, normal page. Unchanged.
- **Very long slide** (taller than the stage): scrolls inside the stage; the bar
  stays put. Content is never hidden behind the bar (the bar is a sibling footer,
  not an overlay).
- **Many slides (>12)**: dots would overflow the bar, so the counter fallback is
  used — no layout break.
- **Label i18n**: if the PL msgstrs are missing or left fuzzy, Django falls back
  to the English msgid (`Next slide` etc.) — degraded but not broken. The
  `compilemessages` step + a no-fuzzy check prevent this.

## Testing

Extend `tests/test_e2e_slideshow.py` (Playwright) and adjust any template/JS
assertions. Key cases:

1. **Arrows keep an accessible name, no visible text.** Assert the Prev/Next
   buttons have a non-empty accessible name (via `aria-label`) and that
   `get_by_role("button", name="Next")` still resolves — pinning the
   substring-match behavior the backward-compatible assertions rely on.
2. **Bar position is stable across slides (the core fix).** Measure the nav
   bar's bounding-box `y` on slide 1 and on a taller later slide; assert they are
   equal (within a small tolerance). This is the direct regression test for the
   author's original complaint.
3. **Deck structure.** Assert `.slideshow-deck` wraps `.slideshow-stage` and the
   `.slideshow-bar`, and that the unit head / unanchored notes / quiz Finish form
   are **outside** the deck.
4. **Position indicator.** With ≤12 slides, assert one dot per slide and that the
   active dot tracks the current slide; with >12 slides, assert the text counter
   is shown instead. Assert the visually-hidden live region reads "Slide N of
   total" in both cases.
5. **Existing behaviors still green.** The current suite (Prev/Next pagination +
   counter/position update, Next-disabled-on-last, keyboard ← / →, mark-seen,
   quiz Finish gating, no-JS flat fallback, single-slide guard) must still pass,
   adjusted only where it asserted the old visible button text or the old
   flow-inserted bar.

Reduced-motion is handled purely in CSS (`transition:none` under the media
query); it is verified by inspection of the compiled rule rather than a
motion-timing e2e, which would be flaky.
