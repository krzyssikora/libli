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
  the inline `window.SLIDESHOW_I18N` strings (label + position-string change).
- `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`) — new Polish
  translations for the accessible labels and the position string.

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
both languages, which is what removes the Polish grammar inconsistency. All
slideshow strings live in `window.SLIDESHOW_I18N` (rendered by the two unit
templates) and their msgstrs in `locale/pl`:

| Key   | EN (msgid)                | PL (msgstr)          | Used as                       |
|-------|---------------------------|----------------------|-------------------------------|
| `prev`| `Previous slide`          | `Poprzedni slajd`    | Prev button `aria-label`      |
| `next`| `Next slide`              | `Następny slajd`     | Next button `aria-label`      |
| `nav` | `Slides`                  | `Slajdy` (existing)  | `<nav aria-label>` on the bar |
| `pos` | `Slide {n} of {total}`    | `Slajd {n} z {total}`| live-region position string   |

**`Prev`/`Next` are NOT obsoleted by this change.** Those msgids are still used
by other templates (`_unit_footer.html`, `manage/review_submission.html`,
`accounts/manage/*.html`, the setup wizard), so `makemessages` keeps them.
`Previous slide` / `Next slide` / `Slide {n} of {total}` are **new** msgids added
alongside the still-used ones — the i18n step is a plain add, not an
obsolete-entry (`#~`) cleanup. Set the three new PL msgstrs and run
`compilemessages`; per the repo's `uv run` tooling note, verify none of the three
is left `#, fuzzy` (Django ignores a fuzzy msgstr and falls back to the English
msgid).

**Position string interpolation.** `pos` carries the literal placeholder tokens
`{n}` and `{total}` through translation (they are inert text to gettext). The
client fills them per slide change: `i18n.pos.replace("{n}", idx+1).replace(
"{total}", slides.length)` → e.g. `"Slide 3 of 5"` / `"Slajd 3 z 5"`. This is
the single source for the announced position in **both** the dots and the counter
mode (see §3).

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
3. Build the `.slideshow-bar` (arrow buttons + position indicator + live region)
   and append it to `deck` as the footer.

Because only the `.slide` nodes move — not the unit head, the completion pill,
the quiz Finish form, or the unanchored notes — those remain in the article
outside the deck and behave exactly as before.

**Fixed height (the core fix).** `.slideshow-stage` gets a constant height
`clamp(360px, 62vh, 640px)` — constant for a given viewport, so the footer bar
sits at the same vertical position on every slide. Each `.slide` is
`position:absolute; inset:0; overflow-y:auto`.

**Content alignment is top-aligned, not vertically centered.** Content starts at
the top of the stage with the stage's padding; a short slide simply has trailing
whitespace below, and a slide taller than the stage scrolls inside it. This
deliberately avoids the flexbox `align-items:center` + `overflow-y:auto` clipping
bug (centered content taller than its container is clipped at the top and
unreachable by scroll). Top alignment is overflow-safe and predictable for
variable-height lesson/quiz content; the framed-card look the design approved
comes from the deck border/shadow, not from vertical centering. On every slide
change the incoming slide's `scrollTop` is reset to 0.

**Visibility contract inside the deck (load-bearing for the cross-fade).** A
cross-fade needs both the outgoing and incoming slide rendered at once, so inside
`.slideshow-deck` visibility is expressed with **opacity + `visibility`**, never
`display:none` (which cannot be transitioned). The existing global rule
`html.js [data-slideshow] .slide:not(.is-active){display:none}` must be **scoped
so it does not apply to slides inside `.slideshow-deck`** (the deck is JS-built,
so the rule still governs the brief pre-JS window and any non-deck case). Each
slide is in exactly one of these states, set via classes/attributes:

| State           | opacity | visibility | pointer-events | `hidden` attr | notes                    |
|-----------------|---------|------------|----------------|---------------|--------------------------|
| settled-active  | 1       | visible    | auto           | no            | the one current slide    |
| fading-in       | 0→1     | visible    | none           | no            | transitioning to active  |
| fading-out      | 1→0     | visible    | none           | no            | transitioning away       |
| settled-hidden  | 0       | hidden     | none           | yes           | all other slides         |

`.is-active` marks settled-active; the `hidden` attribute (plus
`visibility:hidden`) marks settled-hidden; the two transitional states are both
kept `visibility:visible` with opacity animating (§4). The absolute positioning
is also what lets the two mid-fade slides overlap in the same box.

### 3. The restyled bar — arrows + position indicator

- **Arrow buttons**: icon-only, ~34px square, token-styled (border +
  `--surface-raised`; the Next button uses `--primary` as the primary action,
  Prev is neutral). Disabled state (first/last slide) keeps today's reduced
  opacity + `pointer-events:none`. The chevron paths are unchanged
  (`M15 6l-6 6 6 6` / `M9 6l6 6-6 6`).
- **Position indicator**: **progress dots** when `slides.length <= DOTS_MAX`
  (`DOTS_MAX = 12`) — one dot per slide, in a `[data-slideshow-dots]` container,
  the active dot elongated (pill) and marked with an `is-active` class, all
  `aria-hidden` (decorative). The 12 cutoff is a simple guard chosen so a full
  dot row does not wrap the bar at the app's narrowest supported width (~320px);
  it lives as the named `DOTS_MAX` constant so it is not a bare magic number.
  When `slides.length > DOTS_MAX`, dots would overflow, so the indicator is a
  **text counter** instead — `[data-slideshow-counter]` showing `N / total`
  (e.g. `"3 / 20"`, tabular-nums), the same terse counter shown today.
- **Accessibility of position (single source, identical in both modes)**: a
  **dedicated visually-hidden live region** `[data-slideshow-status]`
  (`role="status" aria-live="polite"`) always carries the `pos` string —
  `"Slide 3 of 5"` / `"Slajd 3 z 5"` — updated on every slide change, whether
  dots or the counter are visible. The visible dots and the visible counter are
  both `aria-hidden`, so screen readers hear exactly one, consistently phrased,
  position announcement in either mode. This preserves the position
  announcement today's `role=status` counter provided while decoupling the SR
  phrasing from whichever visible indicator is shown.

### 4. Cross-fade transition

`show(n)` drives the transition instead of an instant swap. Let `out` be the
current settled-active slide and `in` the target:

1. Put `in` into **fading-in** (visible, `opacity:0`, on top), reset its
   `scrollTop` to 0, and put `out` into **fading-out**.
2. Force a reflow, then let CSS transition `out`→`opacity:0` and `in`→`opacity:1`
   over `FADE_MS = 320`.
3. **Finalize** after the fade: `out` → settled-hidden (`hidden`,
   `visibility:hidden`), `in` → settled-active (`.is-active`). Finalization is
   driven by a **`setTimeout(finalize, delay)`**, not `transitionend` — under
   reduced motion the CSS transition is `none`, so `transitionend` would never
   fire and the outgoing slide would be left visible. `delay` is `FADE_MS`
   normally and `0` when
   `window.matchMedia("(prefers-reduced-motion: reduce)").matches` (checked once,
   live), so reduced-motion finalizes immediately with no ~320ms wait.
4. Dots/counter, the `[data-slideshow-status]` live region, the Prev/Next
   disabled states, and `onReveal()` (mark-seen + quiz-finish gate + `resize`)
   all fire for `in` as they do today; `onReveal`'s timing relative to a slide
   becoming active is unchanged.

**Reduced motion.** The *visual* is handled purely in CSS — `.slide`'s opacity
transition is wrapped in `@media (prefers-reduced-motion: reduce)` as
`transition:none`, so it applies regardless of JS. The **only** JS involvement is
the finalize `delay` (0 vs `FADE_MS`) so the outgoing slide is reliably hidden in
both modes; this is the one small, deliberate JS branch (correcting the earlier
"no JS branch" wording).

**Interrupted / rapid navigation.** Rapid clicks or a held ArrowLeft/ArrowRight
can start a new navigation before the current fade finalizes. Handling: each new
`show(n)` first **immediately finalizes any in-flight fade** (snap the pending
`out` to settled-hidden and the pending `in` to settled-active, cancelling the
pending timeout) and then starts the new fade from the now-settled slide. This
guarantees that after any sequence of inputs there is **exactly one**
settled-active slide and every other slide is settled-hidden — never two stacked
visible slides and never a stuck-`hidden` active slide. `onReveal` (hence
mark-seen) fires once per `show()` call, i.e. once per slide navigated to,
including a slide quickly passed through; mark-seen is idempotent and marking a
briefly-shown slide seen is acceptable, matching today's per-`show` behavior.

**Focus & page scroll on slide change.** The current `show()` calls
`slides[idx].scrollIntoView({block:"start"})` and `slides[idx].focus()`. In the
fixed-height deck this changes: the deck does not move, so **per-change
`scrollIntoView` is removed** (scrolling the whole page to the deck top on every
arrow press would be jarring). Focus still moves to the incoming slide
(`tabindex="-1"`) for keyboard/AT context, but via `focus({preventScroll:true})`
so it does not provoke a page scroll. Because the focused slide lives inside the
deck inside the article, the arrow-key handler's `article.contains(target) ||
bar.contains(target)` guard still matches — so when the active Next/Prev button
becomes `disabled` at the last/first slide (losing button focus), keyboard arrow
navigation keeps working via the slide focus.

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
  only the first slide until the script runs) is preserved and still uses
  `display:none` because it governs the pre-deck window.
- **Degenerate single-slide unit**: the existing `slides.length <= 1` guard
  returns early → no deck, no bar, normal page. Unchanged.
- **Very long slide** (taller than the stage): scrolls inside the stage; the bar
  stays put. Content is never hidden behind the bar (the bar is a sibling footer,
  not an overlay) and never clipped at the top (top-aligned content, §2).
- **Many slides (>12)**: dots would overflow the bar, so the counter fallback is
  used — no layout break. The `[data-slideshow-status]` live region is unchanged.
- **Reduced motion**: instant swap (CSS), finalized synchronously (JS `delay=0`).
- **Label/position i18n**: if a PL msgstr is missing or left fuzzy, Django falls
  back to the English msgid (`Next slide`, `Slide {n} of {total}`) — degraded but
  not broken. The `compilemessages` step + a no-fuzzy check prevent this.

## Testing

Extend `tests/test_e2e_slideshow.py` (Playwright) and adjust the JS/template
assertions. Two new seeds are required (the current `seed_slideshow_unit` /
`_seed_slideshow_lesson_tall` helpers only produce ≤3 slides, all with slide 0
tall):

- a **short-first / tall-later** seed (short slide 0, a tall slide 2) for the
  bar-position-stability test;
- a **≥13-slide** seed (a `layout` alternating content/`brk` to yield 13 slides)
  for the counter-fallback test.

Key cases:

1. **Arrows keep an accessible name, no visible text.** Assert the Prev/Next
   buttons have a non-empty accessible name (from `aria-label`) and no visible
   text node, and that `get_by_role("button", name="Next")` still resolves —
   pinning the substring-match behavior the backward-compatible assertions rely
   on.
2. **Bar position is stable across slides (the core fix).** Using the
   short-first/tall-later seed, measure the nav bar's bounding-box `y` on slide 1
   and on the tall later slide; assert they are equal (within a small tolerance).
   This is the direct regression test for the author's original complaint.
3. **Deck structure.** Assert `.slideshow-deck` wraps `.slideshow-stage` and the
   `.slideshow-bar`, and that the unit head / unanchored notes / quiz Finish form
   are **outside** the deck.
4. **Position indicator + live region.** With ≤12 slides, assert
   `[data-slideshow-dots]` has one dot per slide and the `is-active` dot tracks
   the current slide; with the ≥13-slide seed, assert `[data-slideshow-counter]`
   is shown (e.g. `"1 / 13"`) and no dots. In **both** cases assert
   `[data-slideshow-status]` reads the `pos` string (`"Slide N of 5"` /
   `"Slide N of 13"`) and updates on navigation.
5. **Existing behaviors still green, with counter assertions migrated.** The
   four current tests that locate `[data-slideshow-counter]` and assert `"N / M"`
   text (`test_prev_next_paginate_and_counter`,
   `test_arrow_in_text_field_does_not_change_slide`,
   `test_arrow_in_select_or_radio_does_not_change_slide`,
   `test_arrow_on_bar_advances_slide`) run on ≤3-slide seeds where the counter is
   now replaced by dots — they must be **rewritten to assert position against
   `[data-slideshow-status]`** (stable in both modes) and/or the active dot,
   since `[data-slideshow-counter]` no longer exists for ≤12-slide units. The
   rest of the suite (Next-disabled-on-last, keyboard ← / →, mark-seen, quiz
   Finish gating, no-JS flat fallback, single-slide guard) must still pass,
   adjusted only where it asserted the old visible button text or the old
   flow-inserted bar.

Reduced-motion is verified by inspection of the compiled CSS rule (`transition:
none` under the media query) rather than a motion-timing e2e, which would be
flaky; the finalize-delay branch is covered indirectly because tests run with
motion enabled by default and cases 1–5 exercise the normal `FADE_MS` path.
