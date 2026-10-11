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
`extra_css` block of both `lesson_unit.html` and `quiz_unit.html`, emits:

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
  `--text-secondary`; literal because custom properties do not reach margin boxes
  reliably), the body font family stack.
- The page label is a translatable string, `{% trans "Page" %}` → Polish `Strona`, so the
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
  element is replaced with a CSS hex escape `\HHHHHH ` (hex code point + one space
  terminator): at minimum `\`, `"`, `'`, `<`, `>`, `&`, and every control character
  (U+0000–U+001F, U+007F) including newline and carriage return;
- all other characters (including Polish diacritics and other non-ASCII) pass through
  unchanged.

Escaping `<` and `>` is what makes `</style>` in an author title inert. The input is first
passed through `strip_math_delimiters` (an author title like `Funkcja $f(x)=x^2$` must
read `Funkcja f(x)=x^2` in the header, matching the `<title>` element) and
`truncatechars:70`. Order in the template:
`{{ unit.title|strip_math_delimiters|truncatechars:70|css_string }}`.

### 3. Hiding screen chrome in print (D1, D2)

New `@media print` rules:

- In `app.css` (owns the header and `.app-main`):
  `.app-header__spacer, .app-header__cluster { display: none; }`; `.app-header` in print
  gets `padding: 0 0 var(--space-4); background: none; border: 0;`; `.app-main` in print
  gets `padding: 0; max-width: none;`. So the brand and the article share the 15 mm page
  edge. `.brand` stays (D2) — logo image or text, whichever the site uses. It appears
  once because the header is in normal flow at the top of the document.
- Also in `app.css`: Django flash messages (`.app-main > .alert`) → `display: none` in
  print. They are transient UI feedback, not unit content (D1).
- In `courses.css` (owns the unit shell): `.unit-foot`, `.unit-tree`, `.unit-drawer`,
  `.unit-toc-pin` (all states), the **whole** `.unit-strip` (it holds only the tag panel,
  Print and Edit — see "Open question resolved by the spec" below), and the **whole**
  `.draft-banner` (author-only "this unit is unpublished" notice; today only its form is
  hidden in print) → `display: none`.
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
  .el--question { break-inside: avoid; }
}
```

D6 noun → selector map (the source for the coverage test):

| D6 noun | Selector |
|---|---|
| el--image figure (with caption) | `.el--image` |
| float images | `.el--image` (`.el--image--float` is also `.el--image`) |
| table-cell images | `img.cell-img` (`_table_cell.html`, `_filltable_cell.html`) |
| gallery frame | `.el--gallery .gallery__item` (frame + description) |
| dragimage | `.dragimage__stage`; its element root `.el--dragimage` is also `.el--question` |
| question images / single questions | `.el--question` (covers images in stems and options) |

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
  plus the same `margin-top: var(--space-4)` gap between items as the no-JS stack,
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
   `counter(page)` and `counter(pages)`. In Polish (`pl`), the label is `Strona`. A unit
   with a 200-character title emits a header title of at most 70 characters ending in the
   ellipsis.
3. CSS source tests, in the established style of `tests/test_*css*.py`: the `@page` margin
   rule exists in `app.css`; each new print rule appears **after** the screen rule it
   overrides (source-order assertion, the same technique as `test_print_tokens_css.py`);
   the `break-inside: avoid` selector list contains every selector in the D6 noun →
   selector map, **and** each of those class names is found in at least one template under
   `templates/courses/` (or in `gallery.js` for classes it creates), so a selector that
   matches nothing fails the test.

e2e (Playwright, `-m e2e`, `page.emulate_media(media="print")`):

4. Lesson unit in print media: `.app-header__cluster`, `.unit-foot`, `.unit-tree`,
   `.unit-toc-pin`, `.unit-strip`, a flash `.alert`, and (author viewing an unpublished
   unit) `.draft-banner` are not visible; `.brand` and the crumbs are visible;
   `.unit-tree` computes `display: none` and `.unit-shell__main`'s bounding-box left edge
   equals `.unit-shell`'s (no tree track reserved). `emulate_media` keeps the browser
   viewport rather than the A4 page area, so the real page-width layout is covered only by
   the `page.pdf()` check below.
5. Quiz unit (multi-slide) in print media: same chrome assertions, and **every** question
   of every slide is visible.
6. `break-inside` computed value is `avoid` on an `.el--image` figure and an
   `.el--question` in print media.
7. Light **and** dark stored theme for test 4 (dark theme already maps to the light palette
   in print; this checks the hidden header did not leave a dark band).
8. Drag-to-image question with a tall image (taller than 170 mm at print width) in print
   media: `.dragimage__img` height ≤ 170 mm, and every badge's bounding box lies inside the
   image's bounding box.
9. A JS-enhanced gallery with ≥3 images in print media: every `.gallery__item` image is
   visible (non-zero box, opacity 1), the items do not overlap, and `.gallery__bar` is not
   visible.

Visual verification (manual, recorded in the PR): `page.pdf()` of a long lesson with images
(including a gallery and a unit with a very long title) and of a multi-slide quiz, A4,
rendered in Chromium, opened and checked for: running header text and page numbers on
every page, ~15 mm margins, no image split across a page boundary, no screen chrome.
Screenshots in the PR description.

Margin-box content cannot be read from the DOM, so automated tests assert the **emitted
CSS** (test 2) and the visual check covers the rendered result. No new dependency (such as
a PDF text extractor) is added for this.

Every `tests/test_*css*.py` and `courses/tests/test_*css*.py` is run after the CSS edits
(project rule: marker tests partition on text a new rule can duplicate).
