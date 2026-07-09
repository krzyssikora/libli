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

The script's defensive fallback literal (`window.SLIDESHOW_I18N || {…}`, used only
if the inline script were ever absent) must be extended from today's
`{prev, next}` to include `pos` and `nav` too, or `i18n.pos.replace(...)` would
throw. The two unit templates always inject the full set, so this is
defensive-only, but the fallback must stay crash-safe.

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
   first `.slide` currently occupies, leaving the head/`h1` above it and any
   trailing sibling after it (unanchored-notes block for lessons, the
   `[data-quiz-finish]` form for quizzes), so document order is preserved.
2. **Move** every existing `.slide` node into `stage` (they keep their
   `data-element-id` children, so mark-seen and all element wiring are
   untouched).
3. Build the `.slideshow-bar` (arrow buttons + position indicator + live region)
   and append it to `deck` as the footer.
4. **Initialize the resting state:** set the `hidden` attribute on **every**
   `.slide` (all start settled-hidden → `display:none`), so the deck has a
   well-defined resting state *before* the initial reveal. This is load-bearing:
   once moved into the deck the slides are matched by `.slideshow-deck .slide
   {display:block}` and are no longer matched by the child-combinator FOUC rule,
   so without an explicit `hidden` they would all render `display:block`,
   absolutely positioned and stacked, at `opacity:1`. `show(0)` then removes
   `hidden` from slide 0 to reveal it. (This mirrors the old `show()`'s
   forEach-over-all-slides initialization of the resting state; the new two-node
   fade model manages only the two transient nodes, so the all-hidden baseline
   must be established here.)

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

**Visibility contract inside the deck (load-bearing for the cross-fade AND for
IntersectionObserver-safety).** A cross-fade needs both the outgoing and incoming
slide rendered *at the same time*, but **at rest only the active slide may be
rendered** — `progress.js` runs an IntersectionObserver (threshold 0) over every
`[data-element-id]` and marks it seen on first intersection; it ignores
`opacity`/`visibility`. The original slideshow deliberately hides inactive slides
with `display:none` precisely because that is the only IntersectionObserver-safe
hide (the `courses.css` comment says so). If settled-hidden slides were merely
`visibility:hidden; opacity:0` (still rendered boxes inside the on-screen stage),
the observer would intersect every slide's top element on load and **auto-complete
a multi-slide lesson the moment it opens**, without the student paging through.

So the contract is: **`display:none` for settled (inactive) slides**, and
`display:block` + `opacity` only for the two transient states *during* a fade. A
slide reveal uses the standard pattern — set the incoming slide `display:block;
opacity:0`, force a reflow, then transition to `opacity:1` — so `display` is never
itself transitioned. Because only the previously-active slide (already seen) and
the incoming slide (being revealed, and marked seen by `onReveal` anyway) are ever
`display:block`, no *unvisited* slide is ever rendered, so **`progress.js` needs no
change** and premature auto-completion cannot occur.

There are **two** existing global hide rules on the slideshow slides, both of
which would otherwise force `display:none` on the mid-fade (non-`.is-active`) deck
slides and silently defeat the cross-fade:

- `html.js [data-slideshow] .slide:not(.is-active){display:none}` (the post-JS
  active-only hide), and
- `html.js [data-slideshow] .slide:not(:first-child):not(.is-active){display:none}`
  (the FOUC pre-hide).

**Scoping technique (concrete):** change the combinator in these two rules — and
in the sibling `[data-slideshow] .slide{display:block}` rule — from the
descendant combinator to the **child combinator**, i.e.
`[data-slideshow] > .slide`. Once `slideshow.js` moves the slides into
`.slideshow-deck > .slideshow-stage`, they are no longer *direct* children of the
`[data-slideshow]` article, so none of these three rules match them anymore — the
deck's own opacity/visibility rules then solely govern deck slides. In the pre-JS
/ no-JS / non-paginating cases the slides are still direct children of the
article, so the rules apply exactly as today (identical FOUC + no-JS-flat
behavior). This is specificity-neutral (no `:not(complex)` needed) and surgical.

Because the base rule `.slide{display:contents}` still matches deck slides, the
deck rule must **explicitly set `display:block`** on rendered deck slides
(`.slideshow-deck .slide{display:block; position:absolute; inset:0;
overflow-y:auto}`), which out-specifies `.slide{display:contents}` (2 classes vs
1) so absolute positioning takes effect; settled-hidden slides then override this
back to `display:none` via `.slideshow-deck .slide[hidden]{display:none}` (the
`hidden` attribute alone would lose to the 2-class deck rule, so this explicit
rule is required).

Each slide is in exactly one of these states, set via classes/attributes:

| State           | display | opacity | pointer-events | `hidden` attr | notes                              |
|-----------------|---------|---------|----------------|---------------|------------------------------------|
| settled-active  | block   | 1       | auto           | no            | the one current slide; only one rendered at rest |
| fading-in       | block   | 0→1     | none           | no            | transient; rendered during fade    |
| fading-out      | block   | 1→0     | none           | no            | transient; rendered during fade    |
| settled-hidden  | none    | —       | —              | yes           | all other slides; `display:none` = IntersectionObserver-safe |

`.is-active` marks settled-active; the `hidden` attribute (→ `display:none`) marks
settled-hidden; the two transient states drop `hidden` (→ `display:block`) with
opacity animating (§4). The absolute positioning is what lets the two mid-fade
slides overlap in the same box; at rest, exactly one slide (the active one) is
`display:block` and all others are `display:none`.

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
  (`role="status" aria-live="polite"`), hidden with a **clip-based sr-only
  pattern** (kept in layout: `position:absolute; width:1px; height:1px;
  clip-path/clip; overflow:hidden`) — **never** `display:none` or
  `visibility:hidden`, both of which stop `aria-live` from announcing and remove
  the node from the text tree (which the e2e in Testing case 4 reads). It always
  carries the `pos` string —
  `"Slide 3 of 5"` / `"Slajd 3 z 5"` — updated on every slide change, whether
  dots or the counter are visible. The visible dots and the visible counter are
  both `aria-hidden`, so screen readers hear exactly one, consistently phrased,
  position announcement in either mode. This preserves the position
  announcement today's `role=status` counter provided while decoupling the SR
  phrasing from whichever visible indicator is shown.

### 4. Cross-fade transition

The current-index tracker starts at a **sentinel `idx = -1`** (no slide active
yet), so the initial `show(0)` on load is *not* mistaken for a same-index no-op.
`show(n)` clamps `n` to `[0, slides.length-1]`, then:

**`idx` capture/reassign ordering (load-bearing).** Step 0 compares the target
against the **old** `idx`, and `out` is captured from the **old** `idx`; `idx` is
reassigned to the clamped target **only after** Step 0's guard and the `out`
capture — i.e. `if (idx !== -1 && target === idx) return; out = slides[idx]; idx =
target; in = slides[idx];`. A naive `idx = clamp(n)` at the top of `show()` (as in
today's code) would destroy Step 0's same-index detection and make `out === in`
(the contradictory-state / blank-stage failure Step 0 exists to prevent).

**Step 0 — boundary no-op (must be first).** If a slide is already active
(`idx !== -1`) **and** the clamped target equals the current index, **return
immediately**, before touching any fade or finalize state. This preserves today's
idempotent no-op when ArrowRight is held on the last slide or ArrowLeft on the
first — without it, `out` and `in` would be the same node put into contradictory
fading-out/fading-in states and could finish `settled-hidden` (blank stage). The
`idx !== -1` guard is what lets the very first `show(0)` through.

**Step 1 — non-visual synchronous updates (fire immediately, every `show()`).**
Synchronously: update the active dot / counter text and the
`[data-slideshow-status]` live-region `pos` string; set the Prev/Next `disabled`
flags for the new index. Pinning these here — **not** inside the finalize
timeout — keeps the SR position announcement immediate and stops a just-disabled
boundary button being clickable mid-fade.

**Step 2 — render incoming, focus, reveal (synchronous).** Bring `in` into
**fading-in** *first* (`display:block`, `opacity:0`, on top, `tabindex="-1"`) and
reset its `scrollTop` to 0 — the incoming slide must be rendered and focusable
before anything focuses it. **Only now** move focus to `in` via
`focus({preventScroll:true})` (a `display:none`/`hidden` element cannot receive
focus, so this ordering relative to Step 1's `disabled`-toggle is load-bearing:
disabling the focused Next button drops focus to `<body>`, and the rescue focus
must land on the now-rendered `in` so the arrow-key handler's
`article.contains(target)` guard still matches and keyboard nav survives the
boundary). Then call **`onReveal(in)`** synchronously (mark-seen + quiz-finish
gate + `resize`) — synchronous, not deferred to finalize, so every navigated
slide is marked seen exactly once even if its fade is interrupted, and so the
`resize`-driven widget re-measure runs against the now-rendered slide.

If there is **no outgoing slide** — test the **captured `out`** (`!out`), *not*
`idx`: by this point the capture/reassign step has already set `idx = target`
(`0` on initial load), so `idx === -1` is stale and never true here; `out` is
`slides[-1] === undefined` on the initial `show(0)`, so `!out` is the correct
condition — settle `in` straight to **settled-active** with no cross-fade (remove
its `hidden` attribute, set `.is-active`, `opacity:1`, no `out` to fade), then
stop (`idx` is already `0`) — Steps 3's
finalize has nothing to hide. Otherwise put `out` into **fading-out**, force a
reflow, then CSS transitions `out`→`opacity:0` and `in`→`opacity:1` over
`FADE_MS`, and continue to Step 3.

**Step 3 — deferred finalize (visibility swap only).** Only the class/attribute
swap is deferred: `out` → settled-hidden (`hidden` → `display:none`), `in` →
settled-active (`.is-active`). It is driven by **`setTimeout(finalize, delay)`**,
not `transitionend` — under reduced motion the CSS transition is `none`, so
`transitionend` would never fire and the outgoing slide would be left visible.
`delay` is `FADE_MS` normally and `0` when
`window.matchMedia("(prefers-reduced-motion: reduce)").matches` (checked live), so
reduced-motion finalizes immediately with no ~320ms wait.

**Single canonical duration.** `FADE_MS` (the JS finalize delay) and the CSS
`transition` duration on the deck slides are the same 320ms and **must be kept in
lockstep** — if they drift, finalize fires mid-transition (visible flash) or late
(lag). Treat 320ms as one canonical value referenced from both places; a change to
one must update the other.

**Reduced motion.** The *visual* is handled purely in CSS — the opacity
transition, scoped to **`.slideshow-deck .slide`** (not the bare `.slide`, which
is also used as `display:contents` outside the deck), is wrapped in
`@media (prefers-reduced-motion: reduce)` as `transition:none`, so it applies
regardless of JS. The **only** JS involvement is the finalize `delay` (0 vs
`FADE_MS`) so the outgoing slide is reliably hidden in both modes; this is the one
small, deliberate JS branch (correcting the earlier "no JS branch" wording).

**Interrupted / rapid navigation.** Rapid clicks or a held ArrowLeft/ArrowRight
can start a new navigation before the current fade finalizes. Handling: each new
`show(n)` first **immediately finalizes any in-flight fade** (snap the pending
`out` to settled-hidden and the pending `in` to settled-active, cancelling the
pending timeout) and then starts the new fade from the now-settled slide. This
guarantees that after any sequence of inputs there is **exactly one**
settled-active slide and every other slide is settled-hidden — never two stacked
visible slides and never a stuck-`hidden` active slide. Because `onReveal` fires
synchronously in Step 2 (not in the deferred finalize), every navigated slide is
marked seen exactly once even when its fade is interrupted; mark-seen is
idempotent and marking a briefly-shown slide seen is acceptable, matching today's
per-`show` behavior.

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
  (scoped to `.slideshow-deck`) never apply → all slides render stacked in normal
  flow = today's flat page. The two global hide rules keep their `display:none`
  but now use the **child combinator** (`[data-slideshow] > .slide`); with JS off
  the slides stay direct children of the article, so the no-JS-flat and pre-JS
  FOUC behavior are byte-for-byte as today — the combinator change only stops them
  reaching slides once JS nests them in the deck.
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
   `[data-slideshow-status]` reads the `pos` string — matching the seed's actual
   slide count, e.g. `"Slide 2 of 3"` for a 3-slide seed and `"Slide 1 of 13"`
   for the ≥13-slide seed — and updates on navigation.
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
6. **No premature auto-completion (progress.js / display:none regression).** Open
   a fresh multi-slide lesson and assert it is **not** marked completed on load
   (the completion pill is not `is-complete`) and stays incomplete until the
   student pages to the last slide — guarding the `display:none`-at-rest contract
   that keeps `progress.js`'s IntersectionObserver from marking unvisited slides
   seen. (Complements the existing `test_lesson_completes_after_paging_tall_slides`,
   which asserts the positive path.)

Reduced-motion is verified by inspection of the compiled CSS rule (`transition:
none` under the media query) rather than a motion-timing e2e, which would be
flaky; the finalize-delay branch is covered indirectly because tests run with
motion enabled by default and cases 1–5 exercise the normal `FADE_MS` path.
