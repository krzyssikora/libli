# Lesson print foundations

Two pre-existing defects make `Ctrl+P` on a lesson produce a wrong page today. Both are pure
`@media print` CSS. This is a prerequisite for
`2026-08-21-print-lesson-with-notes-design.md`, which adds a student-facing Print button — shipping
that button on top of these defects would be shipping a blank or truncated printout.

Split out deliberately: neither defect is caused by the notes feature, both affect pages that feature
never touches, and keeping them separate makes both diffs reviewable.

## Purpose

**Printing a lesson mostly works.** The repo carries 10 `@media print` blocks — 2 in
`core/static/core/css/app.css` (1183, 1913) and 8 in `courses/static/courses/css/courses.css` (103,
967, 1113, 1349, 1852, 2105, 2308, 2359). Tabs un-hide every `[role="tabpanel"][hidden]` and every
carousel slide; before/after prints both sides; reveal-gates un-hide downstream blocks while gate
buttons drop out; images get mm height caps. It is a considered story with two holes.

**Hole 1 — a dark-theme student prints a blank page.** `tokens.css:79` sets
`[data-theme="dark"] { --text-primary: #F2EFE9 }` (near-white). No print rule anywhere resets the
theme, `print-color-adjust` appears nowhere in the repo, and browsers strip backgrounds when
printing. Near-white text on white paper, on every page of the app.

**Hole 2 — a multi-slide lesson prints only the active slide.** `slideshow.js` hides inactive slides
with the `hidden` attribute and there is no print reveal for them — unlike tabs and carousels, whose
print block at `courses.css:1852` carries the comment *"printing a carousel silently loses every
slide but the current one."* The identical defect in slideshows was never fixed.

**Out of scope:** any JS; any template change; any print affordance. This PR is CSS and tests only.

## Architecture

### 1. Dark theme — a `@media print` override at the end of `tokens.css`

**Selector and placement are load-bearing.** `:root` and `[data-theme="dark"]` are both (0,1,0) and
both match `<html>`, so an override wins only by source order and is **silently inert** anywhere
above line 79. The block must be `@media print { [data-theme="dark"] { … } }` at the **end** of the
file.

**The rule for its contents, with no exceptions:** restate **every token name the
`[data-theme="dark"] ` block declares**, using `:root`'s declaration for that name **verbatim**. Not
"the literal ones" — the seven brand tokens (`tokens.css:81–87`: `--primary`, `--primary-hover`,
`--primary-active`, `--primary-subtle`, `--accent`, `--accent-hover`, `--accent-subtle`) are
`color-mix()` formulas that differ genuinely from `:root`'s (dark mixes toward `white`, light toward
`black`; `--primary-subtle` is 24% vs 16%), so copying `:root`'s formula is exactly what is needed.

The set is easy to under-count. Besides `--surface-*`, `--text-*` and `--border-*`, the dark block
redefines the four author-selectable **body-text** colours as light tints — `--tc-red: #EA8A82`,
`--tc-blue: #8FBCE8`, `--tc-green: #9FBF7B`, `--tc-orange: #E8B761` — plus `--success`, `--warning`,
`--danger` and their `-subtle` partners, `--scroll-edge`, `--surface-overlay` and `--shadow-*`.
Omitting `--tc-*` leaves a lesson with coloured text still printing near-white-on-white.

`--scrim-solid` is **not** in the set: declared only in `:root` (`tokens.css:49`), never in the dark
block, and an existing source-level test enforces that absence.

**Restating `--tc-*` breaks an existing test, which must be updated in the same commit.**
`tests/test_colour_map_drift.py:50–58` scans the **whole file** with
`re.findall(rf"--tc-{slot}:\s*(#[0-9A-Fa-f]{{6}})", tokens)` across the four slots and then asserts
`seen == 8` ("4 slots x 2 themes"). A print block restating the four tokens makes that **12**, so a
*correct* implementation fails an existing test. This is not optional to notice: `tokens.css` is in
`is_global_path`'s member list (`tests/test_affected_tests.py:133`), so this branch selects the whole
suite and the failure will fire.

The fix is one line — change the expected count to `12` with a comment naming the print block as the
third occurrence set. The per-value `SLOTS.get(normalise_colour(value)) == slot` assertion inside the
loop still passes, because the print block restates `:root`'s values, which already map correctly. Do
**not** narrow the regex to dodge the count: scanning every occurrence is what makes the test catch a
drifted value anywhere in the file, including in the new block.

### 2. Dark theme, part two — `--callout-accent` in `courses.css`

`tokens.css` is not the only file with dark-only declarations. `courses.css:2010–2014` declares a
second set:

```css
[data-theme="dark"] .callout--example { --callout-accent: #7db0f7; }   /* …note, tip, warning, task */
```

`--callout-accent` drives callout heading and marker `color` (`courses.css:1962`, `:1972`) and the
`border-left: 3px solid` rail (`:1944`). These are in a **later-loaded sheet at (0,2,0)**, so the
`tokens.css` block cannot reach them: a dark-theme student printing a lesson with callouts gets
`#7db0f7` (≈2.2:1) headings on white.

A matching `@media print { [data-theme="dark"] .callout--* { … } }` block is appended to
`courses.css`. **The value source is not `:root`** — `--callout-accent` is never declared there; its
light values are on the modifier classes themselves (`courses.css:2004–2008`,
`.callout--example { --callout-accent: #2563c9 }` … `.callout--task { #a8318f }`). The general
contract is: *restate the value from the light-theme declaration of the same selector.*

### 3. Slideshow — written against the post-enhancement DOM

**This is the part that is easy to get inert.** `slideshow.js:49–56` **moves** every slide out of
`[data-slideshow]` into a JS-built wrapper: `.slideshow-deck > .slideshow-stage > .slide`, plus
`.slideshow-bar` as the deck footer (`:95`). The three server-side rules that hide slides —
`courses.css:348`, the FOUC pre-hide at `:355` (0,5,1), and the `hidden` attribute — **stop matching
once the deck is built**. `courses.css:361–363` says so itself: *"the global rules that no longer
reach them."* Any print rule written against `[data-slideshow] > .slide` is inert, and so is any
mutant of it.

The rules actually in force after enhancement:

| Rule | Effect |
|---|---|
| `.slideshow-deck { overflow: hidden }` (`:364`) | clips past the stage |
| `.slideshow-stage { position: relative; height: clamp(360px, 62vh, 900px) }` (`:380`) | fixed-height box |
| `.slideshow-deck .slide { display: block; position: absolute; inset: 0; overflow-y: auto; transition: opacity 320ms ease }` (`:386`) | slides stack |
| `.slideshow-deck .slide[hidden] { display: none }` (`:396`) | only the active slide renders |

`display: block` alone is **not** enough — it leaves every slide absolutely positioned at `inset: 0`
inside a clipping fixed-height box, i.e. still one visible slide. Mirroring the carousel precedent at
`courses.css:1868–1870` in full, appended to the end of `courses.css`:

```css
@media print {
  .slideshow-deck {
    overflow: visible !important;
    border: 0; border-radius: 0; box-shadow: none; background: none; margin-block: 0;
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

Three declarations need their own justification, because the obvious reason is wrong for two of them:

- **`opacity: 1 !important`** beats an **inline** style, which nothing else can. The hazard is the
  **outgoing** slide: `slideshow.js:180` sets `inn.style.opacity = "0"` but `:186` restores it to
  `"1"` synchronously three statements later, so `inn` is never observably transparent. It is
  `out.style.opacity = "0"` at `:187`, held for the full `FADE_MS = 320` until `settleHidden(out)` at
  `:191`, during which the outgoing slide is **not yet `[hidden]`** and so is revealed by the rules
  above.
- **`transition: none !important`** is required *alongside* it and winning the cascade is not enough
  without it. `courses.css:393` puts `transition: opacity 320ms ease` on the same rule this block
  overrides; changing a transitioned property's computed value starts an *animation* rather than
  applying it, so `opacity: 1` alone makes the slide fade toward opaque over a further 320 ms while
  the print snapshot samples mid-animation. `courses.css:398–400`'s `prefers-reduced-motion` block is
  the existing precedent for this shape.
- **`.slideshow-bar`** is hidden on the principle the carousel block applies to `.tabs__cbar` /
  `.tabs__status` (`courses.css:1870`): once every slide prints, Prev/Next is meaningless ink.

The remaining `!important`s are order-proof insurance rather than weight requirements — the print
block is appended to the same file, so each print selector ties its screen counterpart and would win
on source order anyway. (`.slideshow-stage` also carries `.scroll-y` from `app.css:1886`, which is
why its `position` reset is needed at all.)

**All new rules are appended at the end of `courses.css`** so no existing line number shifts.

## Data flow

None. No JS, no request, no persisted state, no migration. Two stylesheets gain a `@media print`
block each; a third (`tokens.css`) gains one.

## Error handling

- **No-JS.** Without `html.js` the deck is never built and the screen rules that hide slides never
  apply, so all slides already print. The §3 block is inert there, harmlessly.
- **A single-slide lesson.** `slideshow.js` builds no deck; the §3 selectors match nothing.
- **Light theme.** The §1/§2 blocks are scoped to `[data-theme="dark"]` and never apply.

## Testing

Falsify, don't merely run: each assertion is paired with the mutant that must turn it RED.

Print media is entered with `page.emulate_media(media="print")`, which re-evaluates CSS media queries
(and, measured in this repo's Chromium, does deliver a `matchMedia("print")` change — relevant only
to the notes PR, which has JS). No JS lifecycle is involved here.

### e2e — `tests/test_e2e_print_foundations.py` (new, `pytestmark = pytest.mark.e2e`)

Fixtures follow `tests/test_e2e_notes.py`: allauth `input[name='login']`, `TEST_PASSWORD`,
`seed_roles()`, `published=True`.

| # | Assertion | Mutant that must make it RED |
|---|---|---|
| 1 | Dark-theme lesson body text prints at contrast **≥ 4.5:1 against `#FFFFFF`**. Correct: `--text-primary` light value (`#1E1C18`), 17.0:1. Mutant: `#F2EFE9`, ≈1.1:1 | delete the `tokens.css` print override, **or** move it above the dark block at line 79 |
| 2 | A dark-theme lesson using an author text colour prints `--tc-red` at **≥ 4.5:1**. Correct: `:root` value (`#B2372A`), 6.05:1. Mutant: `#EA8A82`, 2.48:1 | omit the `--tc-*` group from the override set |
| 3 | A dark-theme lesson with a **callout** prints its heading at **≥ 4.5:1**. Correct: `#2563c9`, 5.67:1. Mutant: `#7db0f7`, 2.23:1 | delete the `courses.css` `--callout-accent` print block |
| 4 | **Every slide** of a multi-slide lesson prints **stacked in flow** — the slides' `bounding_box()["y"]` values are **strictly increasing** — and `.slideshow-bar` is not visible. Must `wait_for_selector(".slideshow-deck", state="attached")` first | delete the block; keep only `display: block` without the `position`/`height`/`overflow` resets; omit the `.slideshow-bar` hide |
| 5 | A slide in the **mid-fade state** prints at full opacity. **Order is load-bearing:** inject the state via `page.evaluate` on the *screen* cascade — take a non-active slide, remove its `hidden`, set `style.opacity = "0"`, **then force a style flush** (`void slide.offsetWidth`) — and only **then** `emulate_media(media="print")`, followed by a single non-polling read.

The flush is not decoration. Without it the two mutations coalesce into one style recalc, so the slide goes from *not rendered* (`[hidden]` → `display: none`) straight to `opacity: 1` and **no transition is ever started** — the `transition: none` mutant then reads a solid `1` and stays GREEN. The two `evaluate` calls are ~1 ms apart while a frame is ~16 ms away, so coalescing is the likely case, not a corner. `slideshow.js:184` is the in-repo proof: `void inn.offsetWidth; // force reflow so opacity transitions`. Injecting *after* entering print means the inline `0` loses to `opacity: 1 !important` immediately, the computed value never changes, no transition is ever started, and the `transition: none` mutant reads a solid `1` and stays GREEN | delete `opacity: 1 !important`; **separately**, delete `transition: none !important` |

Two things make these rows falsifiable, and both are easy to lose:

- **Row 4's discriminator is geometric, not visibility.** Under the "keep only `display: block`"
  mutant every slide is `display: block`, `opacity: 1`, visible, with a non-zero box — they all
  occupy the **identical** rect inside the stage's fixed height. `checkVisibility()` and
  `bounding_box()` presence both pass on that mutant; only strictly-increasing `y` separates them.
- **Row 5 must not race the real fade and must not poll.** Polling passes on the mutant, because
  `settleHidden` clears the inline opacity at `slideshow.js:147` and the slide goes opaque on its
  own; a single immediate read on the *correct* build would land mid-transition without the
  `transition: none` reset. Injecting the state removes the clock from the test entirely.

**The dark-theme fixture (rows 1–3):** set the **user's stored theme** to `dark` before login, so the
server renders `data-theme-pref="dark"` and `data-theme="dark"`. Do **not** reach for the
`libli_theme` cookie: `base.html:17–26`'s prepaint script consults it only when `data-theme-pref` is
absent, so a cookie fixture silently does nothing and the row measures a light page — passing on a
build with the override deleted. Each row also asserts `data-theme` resolves to `dark`, so a
mis-wired fixture fails loudly.

Assert a **computed contrast ratio**, never "the colour changed" or "is not white": on the mutant
builds the values are non-white and non-transparent, so any loose predicate passes.

### Non-e2e — `tests/test_print_tokens_css.py` (new)

For **every** token name the `[data-theme="dark"]` block declares — `--primary*`, `--accent*`,
`--surface-*`, `--text-*`, `--border-*`, `--success*`, `--warning*`, `--danger*`, `--tc-*`,
`--scroll-edge`, `--surface-overlay`, `--shadow-*` — the `@media print` block declares the same name
with `:root`'s declaration for it. `color-mix()` tokens are compared **by formula**, which is what
makes the `--primary*` / `--accent*` family checkable. `--scrim-solid` is excluded.

**The extraction contract is itself load-bearing.** Do **not** reuse `test_text_colour_css.py:68`'s
`_block()` helper — `re.search(re.escape(selector) + r"\s*\{(.*?)\n\}")` takes the *first* match, so
with two `[data-theme="dark"]` blocks in the file it compares the screen block against itself and
passes vacuously. Locate the two **structurally**, not by line number: the screen block is the
`[data-theme="dark"] {` at **column 0** (`tokens.css:79–111`), the print block is the indented one
inside `@media print`. `tests/test_imagezoom_render.py:112` already does exactly this with
`re.search(r'^\[data-theme="dark"\]\s*\{', source, re.MULTILINE)` — reuse that shape. (A
"before line 79" locator would select nothing, since the screen block *begins* at 79.)

**Scope is repo-wide, and deliberately limited to column-0 rules.** Every
`[data-theme="dark"]` declaration at the start of a line in a shipped stylesheet needs a
print counterpart or a recorded exclusion; the test fails if a new one appears unclassified.
An **indented** dark rule -- one nested inside a media query, as `error.css:50` is -- is not
matched and not required to be classified. That is a stated trade-off, not an oversight:
dropping the anchor would also match the prose mentions in `notes.css:17` and `tags.css:2`,
and a sweep that cries wolf on comments gets disabled. The sweep finds
five sets:

| Rule | Disposition |
|---|---|
| `tokens.css:79` | covered (§1) |
| `courses.css:2010–2014` | covered (§2) |
| `error.css:50`, `editor.css:924` | excluded — on pages this feature does not print |
| `tags.css:329` | excluded — the **sheet** is loaded by `lesson_unit.html:36`, but `.tag-delete-confirm` is built only by `wireDeleteConfirm()` (`tags.js:103,108`) from `.tag-section__manage` delete links, which exist only in `_tag_section.html` → `my_tags.html`. The element never reaches a printed lesson |

Mutants: change one value; omit the `--primary*` family; make both selectors resolve to the same
block (that third one must turn it RED, or the test is not doing its job).

### Test-run mechanics

`-m e2e` is mandatory or the e2e tests deselect and the run exits 5; start the test-DB container
first; `pytest` can exit 0 with failures, so grep the summary rather than trusting the exit code.
Keep runs scoped to the affected tests.
