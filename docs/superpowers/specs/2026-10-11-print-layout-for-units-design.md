# Print layout for units (lessons and quizzes)

## Purpose

A student who prints a unit (lesson or quiz) today gets the whole screen layout on paper:
the app top bar (language switch, theme toggle, nav links, notifications bell, avatar),
the bottom unit bar (prev/next, course-progress bar, Contents trigger), no explicit page
margins (no `@page` rule exists anywhere in the codebase, so top/bottom margins come out
near zero), no page numbers, and images that break across pages.

This change makes a printout contain **only the unit's content**, with a sensible page
frame: safe margins, a running header naming the unit, page numbers, and images that are
never split between two pages.

## Owner decisions (VERBATIM — do not reverse in review)

| # | Decision |
|---|---|
| D1 | Printing a lesson unit OR a quiz unit shows only the unit's content: hide the app top menu (.app-header nav cluster, account menu, everything except the brand logo) and the bottom unit bar (.unit-foot: prev/next, course progress, Contents trigger), plus the unit strip's print/edit controls (already partly hidden), TOC pin, mobile drawer. |
| D2 | Keep the libli brand logo once, at the top of page 1 (the existing .brand from the header; rest of header hidden). |
| D3 | Keep the breadcrumbs (course › chapter › unit) — as a context line above the unit title on page 1; moving them into the running header is allowed if it fits cleanly. |
| D4 | Explicit page margins via @page: ~15 mm all sides (printers have a 3–5 mm unprintable edge; today no @page rule exists anywhere and top/bottom margins look near 0). |
| D5 | Running header/footer via @page margin boxes: "libli · <unit title>" (top-left) and page "n / total" (counter(page) / counter(pages)), localised (Polish "Strona n / N" via i18n). Unit title must be emitted per page (inline <style> in the template; title needs CSS-string escaping and strip_math_delimiters). Supported in Chrome/Edge 131+; other browsers gracefully get margins without the header — acceptable. Text "libli" in the margin box, not an image. |
| D6 | Images must not be split across pages: break-inside: avoid on each image's box incl. its caption (el--image figure, table-cell images, gallery frame, dragimage/question images, float images). Every image-bearing element must have a print height cap that fits an A4 page with the D4 margins (existing caps 45/75/110/170 mm; add caps where missing, e.g. gallery, dragimage). Single questions also break-inside: avoid; long text, callouts and tables flow normally. |
| D7 | Scope: both lesson units (lesson_unit.html) and quiz units. Verify quiz print shows all questions; if the quiz page needs more than CSS to print sensibly, surface it rather than expanding scope silently. |

The user's words when approving: "Lessons and quizzes both, keep breadcrumbs (can be moved
to header, too), go ahead".

## Current state (verified on master `17b734da`)

- `templates/base.html` renders `<header class="app-header">` containing `.brand` (logo
  image when `site.logo_url`, else the text `libli.`), `.app-header__spacer` and
  `.app-header__cluster` (lang switch, theme toggle, nav toggle, `nav.app-nav`, bell,
  account menu, or a Log in link). No print rule touches any of it.
- `templates/courses/_unit_shell.html` holds `.unit-toc-pin`, `_unit_tree.html`
  (`.unit-tree`), `.unit-shell__main` (the article + `_unit_footer.html` → `footer.unit-foot`)
  and the mobile `.unit-drawer`. Only the TOC pin has a print rule
  (`courses.css` ~:1527, collapsed state only).
- `lesson_unit.html` and `quiz_unit.html` both extend `base.html`, include
  `_unit_strip.html` and `_unit_shell.html`. Both articles (`_lesson_article.html`,
  `_quiz_article.html`) include `_unit_crumbs.html` immediately above the `<h1>`; crumbs
  already have a print rule that lets them wrap (`courses.css` ~:1381). So D3's "above the
  unit title on page 1" is the existing position; this change only has to keep the crumbs
  visible in print.
- Only the lesson page has a Print button (`.unit-strip__print`, `print.js`). The quiz is
  printed with Ctrl+P. Adding a quiz Print button is **not** in scope.
- `print.js` handles notes on `beforeprint`/`afterprint`. Nothing in this change needs JS.
- Image print caps exist for `.el--image--{small,medium,large,full} img`
  (45/75/110/170 mm) and `.cell-img--full` (170 mm). The gallery frame is
  `aspect-ratio: 4/3; max-height: 70vh` (in print `vh` resolves against the page box, so it
  already fits). `.dragimage__img` is `max-width: 100%; height: auto` with no height cap.
- No `break-inside` rule exists for any content except `.lesson .note-card` (notes.css).
- Questions render as `<div class="el el--question" data-question>`; in a quiz each element
  is wrapped in `.slide > section[data-element-id]`; in a lesson in
  `section.lesson-block[data-element-id]`.

## Architecture / components

### 1. Page box — `@page` (D4, D5)

A new `@page` rule in `core/static/core/css/app.css` (global, so every printed page in the
app gets safe margins — the unit pages are the main consumer, and a safe margin is never
wrong elsewhere):

```css
@page { margin: 15mm; }
```

The **running header** is unit-specific, so it is emitted per page, not in a static sheet.
A new shared partial `templates/courses/_print_page_header.html`, included from the
`extra_css` block of `lesson_unit.html`, `quiz_unit.html` **and `quiz_results.html`**,
emits the block below. `quiz_results.html` is in scope because every request for a
submitted quiz redirects there (`courses/views.py` ~:1487), so a student printing their
finished quiz prints that page; it extends `base.html`, has `unit` in context and an
`extra_css` block. The partial starts with `{% load i18n courses_extras %}` (an included
template does not inherit its parent's loads). It emits:

```html
<style>
@page {
  @top-left  { content: "libli · <escaped unit title>"; … }
  @top-right { content: "<escaped 'Page'> " counter(page) " / " counter(pages); … }
}
</style>
```

- Placement: top-left and top-right, both in the top margin, so the bottom margin stays
  clean. Typography: small (~8pt), secondary grey (`#5A544A`, the light-palette
  `--text-secondary`), and the body font family stack. Both colour and font stack are
  written as **literal values** inside the inline `@page` block (the font stack copied
  verbatim from `--font-ui` in `tokens.css`:
  `"Inter", "libli-dice", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`),
  never `var(...)`, because custom properties do not reach margin boxes reliably.
- The page label is a translatable string (bound as described in the next bullet but one,
  with the `print page counter` context) → Polish `Strona`, so the
  Polish printout reads `Strona 3 / 7`. The label goes through the same CSS-string escaping
  as the title (it is author-controlled via the `.po` file, and a translator's quote must
  not break the rule).
- Long unit titles: the header title is truncated **server-side** so the result does not
  depend on the engine: `{{ unit.title|strip_math_delimiters|truncatechars:70|css_string }}`
  (70 characters incl. the ellipsis fits the A4 top-left box at ~8pt beside the page
  counter). `white-space: nowrap; overflow: hidden; text-overflow: ellipsis` on `@top-left`
  stays as a belt-and-braces bonus only. A truncated title in the header is acceptable
  because the full title is printed as the `<h1>` on page 1.
- The translated label is bound with the `as` form, since `{% trans %}` output cannot be
  piped into a filter: `{% translate "Page" context "print page counter" as page_label %}`
  then `{{ page_label|css_string }}`. The `context` (pgettext) keeps this msgid separate
  from the existing `"Page"` msgid used by the support issue-report templates
  (`locale/pl/LC_MESSAGES/django.po`). The `pl` catalogue gets the entry
  `msgctxt "print page counter" / msgid "Page" / msgstr "Strona"` and the `.mo` is
  recompiled.
- Breadcrumbs (D3) stay in the content flow above the `<h1>`; they are **not** moved into
  the header (a three-level path plus title does not fit a margin box cleanly).

### 2. CSS-string escaping filter

A new template filter `css_string` in `courses/templatetags/courses_extras.py`. It takes a
plain string and returns the **inside** of a CSS double-quoted string, marked safe:

- every character that is not printable-safe in a CSS string inside an HTML `<style>`
  element is replaced with a CSS hex escape: backslash, the code point in **minimal
  lowercase hex** (no zero-padding), then exactly one space — e.g. `"` → `\22 `,
  `'` → `\27 `, `\` → `\5c `, `<` → `\3c `, `>` → `\3e `, `&` → `\26 `, newline →
  `\a `: at minimum `\`, `"`, `'`, `<`, `>`, `&`, and every control character
  (U+0000–U+001F, U+007F) including newline and carriage return;
- all other characters (including Polish diacritics and other non-ASCII) pass through
  unchanged.

Escaping `<` and `>` is what makes `</style>` in an author title inert. The input is first
passed through `strip_math_delimiters`, which removes only `\(`, `\)`, `\[`, `\]` (an
author title like `Funkcja \(f(x)=x^2\)` must read `Funkcja f(x)=x^2` in the header,
matching the `<title>` element; a `$…$` title passes through unchanged, and leftover
LaTeX backslashes such as `\frac` are expected and are escaped by `css_string`; the filter
itself is NOT changed, it has other callers) and
`truncatechars:70`. Order in the template:
`{{ unit.title|strip_math_delimiters|truncatechars:70|css_string }}`.

### 3. Hiding screen chrome in print (D1, D2)

New `@media print` rules:

- In `app.css` (owns the header and `.app-main`):
  `.app-header__spacer, .app-header__cluster { display: none; }`; `.app-header` in print
  gets `padding: 0 0 var(--space-4); background: none; border: 0;`; `.app-main` in print
  gets `padding: 0; max-width: none;`. The brand sits at the 15 mm page edge; the article
  keeps its existing screen padding (`.unit-shell__main > .lesson/.quiz`, `1.25rem 1.5rem`,
  courses.css ~:1075), so its text is inset 1.5rem from the brand. That inset is accepted
  and not changed. `.brand` stays (D2) — logo image or text, whichever the site uses. It appears
  once because the header is in normal flow at the top of the document.
- Also in `app.css`: Django flash messages (`.app-main > .alert`) → `display: none` in
  print. They are transient UI feedback, not unit content (D1). The selector is the
  direct-child form on purpose: the quiz **preview** notice
  (`aside.alert.alert--info[data-quiz-preview-notice]`, inside the article) is also an
  `.alert` and intentionally **prints**, because it explains what the printout is (an
  author's preview).
- Interactive question/quiz controls, in `courses.css` → `display: none` in print:
  - `.quiz-finish` (the "Finish quiz" form). On a multi-slide quiz it now lives in
    `.slideshow-bar` (merged #370), which the existing slideshow print block already
    hides; on a single-slide quiz it sits at the end of the article. The rule hides it in
    both places.
  - `.el--question .question__form button[type="submit"]` — every question's
    Check/Submit button and the reveal button (`_reveal_button.html`, also
    `type="submit"`), in lessons and quizzes alike.
  - Non-question action buttons (swept from `templates/courses/elements/*.html` and the
    `render_*` tags in `courses_extras.py`): `.filltable__confirm` (fill-table "Check"),
    `.markdone__save` (mark-done "Save"), `.fillgate__confirm`, `.stepper__next`
    ("Show next"), `.switchgate__confirm`, `.switchgrid__confirm`, and
    `[data-guess-check]` (guess-number check). These are all hidden in one rule.
  - **Steppers print every step**, following the reveal-gate precedent (`app.css` ~:1524
    prints every gated block and hides only the gate button). Otherwise a stepper the
    student has not fully stepped through would print truncated with no sign that steps
    are missing, once "Show next" is hidden. A print rule after `courses.css` ~:2932,
    `.stepper.is-stepping [data-stepper-step]:not(.stepper-shown) { display: revert !important; }`
    (same selector, so equal weight; source order and `!important` beat the screen hide),
    also beats the `.stepper-armed` pre-hide inline in `lesson_unit.html`, which has no
    `!important`.
  - Already hidden by existing print rules (no change, listed for completeness): the
    reveal-gate buttons (`[data-reveal-gate]:not([data-filltablegate])`, app.css) and
    `.ba__toggle` (courses.css before/after print block).
  - Kept: `.question__feedback` (the student's verdict, marks and attempts-left line) —
    that is the student's result, i.e. content of their printout.
  - Kept: `.switchgate__cycler` / `.switchgrid__cycler` — they are buttons, but their text
    IS the student's chosen value, so they are content.
  - Kept: `.answer-switch` ("Your answer / Correct answer") — on paper it acts as a legend
    saying which copy of the answer is shown.
- In `courses.css` (owns the unit shell): `.unit-foot`, `.unit-tree`, `.unit-drawer`,
  `.unit-toc-pin` (all states), the **whole** `.unit-strip` (it holds only the tag panel,
  Print and Edit — see "Open question resolved by the spec" below), and the **whole**
  `.draft-banner` (author-only "this unit is unpublished" notice; today only its form is
  hidden in print) → `display: none`.
- **Scope of the `app.css` rules:** the header, flash-message and `.app-main` print rules
  are global, on purpose, like `@page`: every page that extends `base.html` (course page,
  results, dashboards, manage pages) prints without the nav cluster and flash messages
  and with an unpadded main. None of that chrome is useful on paper on any page, and one
  global rule is simpler than a per-page opt-in. The standalone gradebook print page
  (`gradebook_print.html`) neither extends `base.html` nor loads `app.css`, so it is
  entirely unaffected (including `@page`); no test asserts anything about it.
- Weight of the `.unit-drawer` hide: `courses.css` ~:1405 has
  `.unit-drawer:not([hidden]) { display: block; position: fixed; … }` (0,2,0) inside
  `@media (max-width: 640px)`, which matches in print on small paper (print media is
  evaluated against the page area). The print rule is therefore
  `.unit-drawer, .unit-drawer:not([hidden]) { display: none; }`, placed after ~:1405.
- `.unit-shell` / `.unit-shell__main` must not reserve the tree's column in print: with
  `.unit-tree` hidden, `.unit-shell__main`'s left edge equals `.unit-shell`'s left edge.
- **Not touched:** student notes (`.block-notes`, the unanchored-notes panel). They have a
  deliberate, existing print behaviour (`notes.css` print block, `print.js`) that prints a
  student's own notes beside the content they annotate. Notes are the student's work on the
  content, so they stay; tags are a navigation/filing aid, so they go.

Each new print block sits **after** every screen rule it overrides (media queries add no
specificity; this codebase has been bitten by that repeatedly — see the comments at
`courses.css` ~:166 and ~:1527). Selector weight must match or exceed the screen rule it
overrides; where a screen rule is a state-gated reveal (like the TOC pin's
`html.unit-tree-collapsed [data-unit-shell] > .unit-toc-pin`), the print rule matches
that weight.

**Open question resolved by the spec:** the unit strip's tag chips (`.unit-tags`) are the
student's own tags on the unit, which is personal metadata, not unit content. They are
hidden in print with the rest of the strip: `@media print { .unit-strip { display: none; } }`. (Reviewer: if you disagree, the D1
wording "only the unit's content" is the deciding text.)

### 4. Keeping images and questions whole (D6)

A new `@media print` block in `courses.css`, placed after every screen rule for the
affected selectors:

```css
@media print {
  .el--image,                    /* figure: img + figcaption (incl. .el--image--float) */
  .el--gallery .gallery__item,   /* one gallery card: frame + description */
  img.cell-img,                  /* table / fill-table cell image (class is on the <img>) */
  .dragimage__stage,             /* drag-to-image board: img + percent-placed badges */
  .el--question,
  .quiz-results__item { break-inside: avoid; }  /* §6 */
  .el__qnum { break-after: avoid; }  /* quiz "3 / 10" badge stays with its question */
}
```

D6 noun → selector map (the source for the coverage test):

| D6 noun | Selector |
|---|---|
| el--image figure (with caption) | `.el--image` |
| float images | `.el--image` (`.el--image--float` is also `.el--image`) |
| table-cell images | `img.cell-img` (`_table_cell.html`, `_filltable_cell.html`). An `<img>` is an atomic replaced box and never splits anyway, so this entry is for explicitness/coverage only; tables (and so their rows) flow normally per D6, and no row-level protection is added |
| gallery frame | `.el--gallery .gallery__item` (frame + description) |
| dragimage | `.dragimage__stage`; its element root `.el--dragimage` is also `.el--question` |
| question images / single questions | `.el--question` (covers images in stems and options) |
| quiz results row (submitted quiz) | `.quiz-results__item` (see §6) |
| quiz question-number badge | `.el__qnum` (`break-after: avoid`; it is a sibling before `.el--question` in `section[data-element-id]`) |

- **Height caps:** every capped image keeps its existing cap. `.dragimage__img` gets
  `max-height: 170mm` in print. This is safe for the badges: `.dragimage__stage` is
  `display: inline-block; max-width: 100%` (shrink-to-fit) and `.dragimage__img` is
  `display: block; height: auto`, so a max-height scales the image's width proportionally,
  the stage follows, and the percent-placed badges stay on their spots. An e2e test pins
  this (Testing #8). The gallery frame needs no new cap (see "Current state").
- **Gallery carousel in print:** once `gallery.js` enhances a gallery
  (`.el--gallery.gallery--js`), every `.gallery__item` is `position: absolute; opacity: 0`
  except `.is-active`, and `gallery.js` sets an inline `min-height` on `.gallery__stage`
  and on `.gallery__desc`. No print rule undoes this today, so a printed gallery shows one
  image (the rest stacked invisibly) plus its prev/next bar, and `break-inside` on
  overlapping absolute items does nothing. A new print block, on the pattern of the
  slideshow (~:3302) and tabs-carousel (~:2629) print blocks, placed after the gallery
  screen rules:
  `.el--gallery.gallery--js .gallery__stage { position: static !important; min-height: 0 !important; }`,
  `.el--gallery.gallery--js .gallery__item { position: static !important; opacity: 1 !important; transition: none !important; }`
  `.el--gallery.gallery--js .gallery__item + .gallery__item { margin-top: var(--space-4); }`
  (the same gap as the no-JS stack; safe because gallery.js appends `.gallery__bar` after
  the last item),
  `.el--gallery.gallery--js .gallery__desc { min-height: 0 !important; }`, and
  `.el--gallery .gallery__bar, .el--gallery .gallery__status { display: none !important; }`.
  So every gallery image prints, stacked, each card unsplit.
- **A4 budget:** A4 is 297 mm tall; minus 2 × 15 mm margins = 267 mm content height. The
  largest cap (170 mm) plus a caption fits with room to spare, so `break-inside: avoid`
  can always be honoured for a single image.
- **A question taller than a page** (e.g. a long multi-grid) cannot be kept whole; the
  browser then breaks it anyway. That is accepted, not a defect.
- Callouts, tables, tabs, long text: **no** new break rules (D6: "flow normally").

### 5. Quiz pages (D7)

Quiz units render as a slide deck when they have more than one slide
(`.quiz--slideshow[data-slideshow]`). The existing `.slideshow-deck` print block
(`courses.css` ~:3302) un-hides every slide and resets their positioning. The plan must
**verify** with a print-emulated e2e that every question of a multi-slide quiz is visible
in print media. If it is not, and fixing it needs more than CSS, the run halts and reports
it (D7) instead of expanding scope.

### 6. Quiz results page (`quiz_results.html`)

This page is the printout of a submitted quiz (see §1). Beyond the running header:

- **Chrome:** it includes `_unit_strip.html` (hidden by §3's `.unit-strip` rule) and ends
  with a "Back to course" link `a.btn.btn--ghost`, a direct child of
  `article.quiz-results` → `.quiz-results > .btn { display: none; }` in print.
- **D6:** each result row is `li.quiz-results__item`. Rows for reveal-capable questions
  wrap a rendered `.el--question`; rows for other questions render stem, badge, feedback
  and explanation directly in the `<li>` with no `.el--question`. So
  `.quiz-results__item` is added to the `break-inside: avoid` list (it covers both row
  kinds) and to the D6 map.
- **D3:** the results page has no breadcrumbs on screen (it never includes
  `_unit_crumbs.html`, and its view does not build `unit_nav`). They are knowingly left
  absent in print too: the running header and the `<h1>` ("<title> — results") name the
  unit. Adding crumbs to this page is out of scope.

## Data flow

No server-side data change. The only new server-side output is the inline `<style>` block
per unit page, built from `unit.title` (already in both templates' context) and a
translated label. No model, migration, view, or JS change.

## Error handling

- **Unsupported browser** (no margin-box support): the `@page` margin still applies; the
  margin-box rules are ignored silently by the CSS parser. No fallback is needed (D5).
- **Hostile / odd titles:** quotes, backslashes, `</style>`, newlines, and math delimiters
  in `unit.title` must not break the stylesheet or the page. Covered by `css_string` unit
  tests and a template-render test.
- **Empty title:** the header reads `libli · ` — acceptable; titles are required in the
  model, so this is theoretical.
- **Browser's own headers/footers option:** when the student enables "Headers and footers"
  in Chrome's print dialog, Chrome may print its own header/footer as well. That is user
  choice and out of scope.

## Testing

Unit / template tests (fast, non-e2e):

1. `css_string` filter: each escaped character class (`"`, `'`, `\`, `<`, `>`, `&`,
   newline, other control chars) produces the documented hex escape; Polish diacritics pass
   through; `</style>` input produces no literal `<`.
2. Template render of a lesson unit and a quiz unit: the response contains the `@page`
   block with `@top-left` holding the stripped, escaped title, and `@top-right` holding
   `counter(page)` and `counter(pages)`. Fixture title
   `Funkcja \(f(x)\) "x" </style>` → the `@top-left` content is exactly
   `"libli · Funkcja f(x) \22 x\22  \3c /style\3e "`, and the response contains no literal
   `</style>` between the partial's opening `<style>` and its own closing tag. In Polish
   (`pl`), the label is `Strona`. A unit
   with a 200-character title made only of letters and spaces (no character `css_string`
   escapes) emits a header title of at most 70 characters ending in the ellipsis `…`.
3. CSS source tests, in the established style of `tests/test_*css*.py`: the `@page` margin
   rule exists in `app.css`; each new print rule appears **after** the screen rule it
   overrides (source-order assertion, the same technique as `test_print_tokens_css.py`);
   the `break-inside: avoid` selector list contains every selector in the D6 noun →
   selector map, **and** each of those class names is found in at least one template under
   `templates/courses/` (or in `gallery.js` for classes it creates), so a selector that
   matches nothing fails the test.

e2e (Playwright, `-m e2e`, `page.emulate_media(media="print")`):

4. Lesson unit in print media: `.app-header__cluster`, `.unit-foot`, `.unit-tree`,
   `.unit-toc-pin`, `.unit-strip`, a flash message (`.app-main > .alert`), a question's
   Check button, and (author viewing an unpublished unit) `.draft-banner` are not visible; `.brand` and the crumbs are visible;
   `.unit-tree` computes `display: none` and `.unit-shell__main`'s bounding-box left edge
   equals `.unit-shell`'s (no tree track reserved). `emulate_media` keeps the browser
   viewport rather than the A4 page area, so the real page-width layout is covered only by
   the `page.pdf()` check below. The flash message is produced by injecting
   `<div class="alert alert--info">x</div>` as the first child of `.app-main` via
   `page.evaluate` before emulating print (this test checks a style rule, not a user
   flow); the test first asserts the injected `.app-main > .alert` count is 1, then that it
   is not visible. The `.unit-toc-pin` check runs with `unit-tree-collapsed` set on
   `<html>` (the only state in which the pin displays on screen): assert the pin is
   visible under screen media first, then not visible under print media — otherwise the
   assertion is vacuous.
5. Quiz unit (multi-slide) in print media (and test 2's `@page`-block assertion is also
   run against the submitted quiz's `quiz_results.html` render): same chrome assertions, **every** question of
   every slide is visible, and neither `.slideshow-bar` nor any `.quiz-finish` is visible.
   A single-slide quiz: its in-article `.quiz-finish` is not visible.
   Submitted quiz → `quiz_results.html` in print media: `.unit-strip` and the
   `.quiz-results > .btn` "Back to course" link are not visible (each first asserted
   attached); a non-reveal result row (`li.quiz-results__item` without `.el--question`)
   computes `break-inside: avoid`.
6. `break-inside` computed value is `avoid` on an `.el--image` figure and an
   `.el--question` in print media. This is a **cascade** check only (the rule is not
   overridden by anything later); whether a page break actually avoids the box is covered
   by the manual `page.pdf()` check, which includes a float image near a page boundary.
7. Light **and** dark stored theme for test 4 (dark theme already maps to the light palette
   in print). In both, under print media `.app-header` computes `background-color`
   `rgba(0, 0, 0, 0)`, `background-image` `none`, and `border-bottom-width` `0px` — so the
   hidden header leaves no band.
8. Drag-to-image question with a tall portrait image (fixture ≥ 600×1600 px) at the
   default test viewport; precondition: its rendered height under screen media is
   > 643 px (170 mm at 96 dpi), so the cap actually engages. Then in print
   media: `.dragimage__img` height ≤ 170 mm (≤ 643 px); `.dragimage__stage`'s width equals
   the image's width (±1 px); and each badge's **centre** equals
   `img.left + data-x·img.width`, `img.top + data-y·img.height` within 2 px (badges are
   centred with `translate(-50%,-50%)`, so containment would be the wrong check: it
   passes when the stage stays wide and badges drift horizontally). Fixture zones at
   interior coordinates (x, y in 0.2–0.8), including one with x = 0.8 so horizontal drift
   shows.
9. A JS-enhanced gallery with ≥3 images in print media: every `.gallery__item` image is
   visible (non-zero box, opacity 1), the items do not overlap, and `.gallery__bar` is not
   visible.
10. A lesson with a fill-table, a mark-done element and a stepper in print media:
   `.filltable__confirm`, `.markdone__save` and `.stepper__next` are not visible (each
   first asserted attached, count ≥ 1). The stepper has ≥3 steps and is left un-stepped
   (only the first step shown on screen — asserted first); in print media **every**
   `[data-stepper-step]` is visible.

Visual verification (manual, recorded in the PR): `page.pdf()` of a long lesson with images
(including a gallery, a float-right image positioned near a page boundary, and a unit
with a very long title), of a multi-slide quiz, and of a submitted quiz's results page, A4,
rendered in Chromium, opened and checked for: running header text and page numbers on
every page, ~15 mm margins, no image split across a page boundary, no screen chrome.
Screenshots in the PR description.

Margin-box content cannot be read from the DOM, so automated tests assert the **emitted
CSS** (test 2) and the visual check covers the rendered result. No new dependency (such as
a PDF text extractor) is added for this.

Every `tests/test_*css*.py` and `courses/tests/test_*css*.py` is run after the CSS edits
(project rule: marker tests partition on text a new rule can duplicate).
