# Unit-level slideshow mode

## Purpose

Today every element of a unit (lesson or quiz) is rendered on one scrolling page.
Some units read better one screen at a time — a quiz where questions appear
individually, or a lesson taught step by step. This feature adds a **slideshow
mode** to any unit: its elements are shown one slide at a time, with a
`N / total` counter and free Prev/Next navigation.

A unit is a slideshow **iff it contains at least one slide-break element** — there
is no separate on/off flag to keep in sync. Authors add a "slide break" between
elements in the builder; the elements between two breaks form one slide. Add a
break → the unit paginates; remove them all → it is a normal scrolling page again.

The mechanism is deliberately **presentation-only**: every element still renders
into the page exactly as today, and quiz answering / marking are untouched.
Slideshow is a client-side view over server-partitioned slide groups, with a clean
no-JS fallback (JS off → all slides stacked = today's flat page).

### Out of scope

- A separate in-unit **"slideshow element"** (an image carousel embedded in a
  single slide) is a distinct future feature. The name "slideshow" here refers
  only to this unit-level mode; if the future carousel forces a naming collision,
  the unit-level mode can later be renamed ("slides"/"paginated") cheaply.
- **Gated progression** (must answer before advancing) is explicitly not built —
  navigation is free in both directions. Could become a future per-unit option.
- The quiz **results/review** page stays flat (paginating a post-submission
  review adds nothing). Slideshow applies only while *taking* a unit.

## Architecture / components

### Terminology: `Element` join-rows vs content objects

This is load-bearing throughout. In `courses/models.py`, a unit's `node.elements`
are `Element` **GFK join-rows** — each has its own `pk`, an `order`, and a
`content_object` pointing at one concrete element (`TextElement`,
`ChoiceQuestionElement`, the new `SlideBreakElement`, …). The rendering, progress,
and template code all key off the **join-row**: `render_element el` renders
`el.content_object`, the template writes `data-element-id="{{ el.pk }}"` using the
**join-row** pk, and the `seen` view's completion set is a set of **join-row** pks.
Everywhere this spec says "element" in the render/partition/progress context it
means the `Element` join-row, never the unwrapped `content_object`.

### 1. Data model — `SlideBreakElement`

A new concrete element type, the 15th, added to `ELEMENT_MODELS` in
`courses/models.py`. **Registry sweep:** `ELEMENT_MODELS`, the builder palette /
`FORM_FOR_TYPE`, and the transfer `SERIALIZERS`/schema maps (below) are the known
places a type must be registered, but the implementation must **grep for every map
that enumerates element types** — `type_key`→label, `type_key`→icon, any
`ELEMENT_TYPE_CHOICES`, admin registration, and similar — and add the `slide_break`
entry (or intentionally exclude it, e.g. from analytics) so no map silently omits it
or `KeyError`s. It follows the exact shape of every other element type:
subclasses `ElementBase`, declares `elements = GenericRelation(Element)`, and is
pointed at by an `Element` GFK join-row. It has **no content fields** — it is a
pure delimiter. One migration creates the model; its `ContentType` row is created
by Django's normal `ContentType` machinery.

`is_slideshow` is a **derived** property, never stored: a unit is a slideshow iff
its element list contains at least one join-row whose `content_object` is a
`SlideBreakElement`. It is a model-level helper computed from the loaded element
list, used **only by non-taking consumers** (e.g. a builder badge). The taking
articles do not use it — they gate on `slides|length` instead (see §2).

### 2. Rendering — server partitions elements into slides

`build_lesson_context` and `build_quiz_context` (`courses/views.py`) already load
the unit's ordered elements (join-rows) with `content_object` prefetched. Each
gains one step: **partition the ordered join-row list into `slides`** — a list of
lists of `Element` **join-rows** (never unwrapped to `content_object`) — splitting
at each slide-break. A break is detected by
`isinstance(el.content_object, SlideBreakElement)`. Break join-rows are **consumed**
(never rendered as content). The partition rule:

- Split the ordered join-row list on each break.
- **Drop empty groups**, so a leading, trailing, or doubled break never produces
  an empty slide.
- A non-slideshow unit (no breaks) yields exactly **one slide** holding every
  join-row.

A small pure helper `partition_into_slides(elements)` in a new `courses/slideshow.py`
does the split (input and output are `Element` join-rows) and is unit-tested in
isolation. Both context builders call it and add `slides` (list of lists of
join-rows) to their context dicts. The taking template and `slideshow.js` gate
purely on `slides|length > 1`, so the taking-view context does **not** carry a
separate `is_slideshow` key — that avoids a second source of truth that could drift
from the slide-count gate (the I1 contradiction). `is_slideshow` may still exist as
a derived model property for **non-taking** consumers (e.g. a builder badge), but it
is not passed to the taking articles. **Every** template
render of the two article partials must supply `slides`;
the partials are written to loop `slides` and never fall back to a flat `elements`
loop, so a caller that forgets it renders a blank unit. Audit the other callers
that build `elements` lists (e.g. builder/preview paths in `views_manage.py`): any
that render `_lesson_article.html` / `_quiz_article.html` must route through the
context builders or supply `slides` themselves.

The article templates `templates/courses/_lesson_article.html` and
`templates/courses/_quiz_article.html` change from a flat
`{% for el in elements %}` loop to a nested one:

```
{% for slide in slides %}
  <div class="slide">
    {% for el in slide %}
      <section data-element-id="{{ el.pk }}" ...>...</section>
    {% endfor %}
  </div>
{% endfor %}
```

The wrapper is a non-semantic `<div class="slide">` (not a `<section>`) to avoid the
historical `display: contents` accessibility-tree caveat on semantic elements.
Backward-compatibility for the (vast majority) non-slideshow units is preserved by
CSS: `.slide` defaults to **`display: contents`**, so the wrapper vanishes from the
layout box tree and the inner `data-element-id` sections behave exactly as today —
no existing CSS or e2e selector sees a structural change.

**Where `[data-slideshow]` goes, and when.** The attribute is placed on the
**article root element** — `<article class="lesson">` / `<article class="quiz">` —
which is the element the CSS ancestor selector `[data-slideshow] .slide` and
`slideshow.js`'s `[data-slideshow]` lookup both anchor to. It is emitted iff
`slides|length > 1` (the template condition), **not** merely `is_slideshow`. This
decouples "has a break" from "actually paginates": a unit whose only break is
leading or trailing collapses to a single content slide, so it gets **no**
`[data-slideshow]`, no control bar, and `.slide` stays `display: contents` — it
renders as an ordinary flat page. Only when `[data-slideshow]` is present does
`.slide` become a real block the client shows/hides. The render/JS gate is the slide
**count** everywhere, so a single-slide "slideshow" is indistinguishable from a
normal unit at runtime.

**Quiz question numbering (a required constraint on the hide mechanism).**
`courses.css` numbers quiz questions with a pure CSS counter
(`.quiz { counter-reset: quiz-q }`, `.quiz .el--question { counter-increment:
quiz-q }`, `::before { content: counter(quiz-q) }`). CSS counters do **not**
increment inside elements hidden with `display: none` or the `hidden` attribute —
so if inactive slides were hidden that way, each visible slide's questions would
renumber from 1 ("Question 1", "Question 2" on every slide).

**Recommended resolution — `display: none` hide + server-side numbering.** Hide
inactive slides with `display: none` (the simplest, most robust hide), and move quiz
question numbering **off** the CSS counter by computing the number server-side into
the markup. This is preferred because `display: none` is **IntersectionObserver-safe
and scroll-safe by construction**: a `display:none` slide has zero geometry, so
(a) it contributes nothing to scroll height, and (b) `progress.js`'s
`IntersectionObserver` correctly reports its elements as **not** intersecting — so
they are never prematurely marked seen before the slide is revealed. Requirements:
- Emit the question number server-side (e.g. a `1.`, `2.` … computed over the unit's
  question elements) and **remove/disable** the existing
  `.quiz .el--question::before { content: counter(quiz-q) }` rule, or questions
  render doubled.
- This changes numbering for **every** quiz (not just slideshow ones), so affected
  quiz tests and screenshots must be updated accordingly. (Accepted: the server-side
  number must match what the CSS counter produced for a normal flat quiz.)

**Fallback resolution — counting-preserving CSS hide (only if server-side
renumbering is undesirable).** Keep the CSS counter and instead hide inactive slides
with a method that still generates boxes (so the counter increments): e.g.
`visibility: hidden` + `position: absolute` within a `position: relative` article.
This path is **more fragile** and, if chosen, MUST guarantee three consequences,
each tested: (a) inactive slides contribute **zero** scroll height (article
`position: relative`, inactive slides clipped so page scroll tracks only the active
slide); (b) inactive slides **never** register as viewport-intersecting to the
IntersectionObserver (else their elements get marked seen early — note
`visibility:hidden` alone does **not** stop IO, which is geometry-based, so the slide
must be clipped/moved out of the viewport, not merely made invisible); (c) the hide
does **not** zero the widget layout width (see §I2 relayout below), so MathLive/
GeoGebra don't collapse. Also mark inactive slides inert to AT/focus (`aria-hidden`
+ not focusable).

**Widget relayout on reveal (applies to BOTH resolutions).** MathLive `math-field`
and GeoGebra iframes compute layout on init and can render at zero/wrong size when
initialized inside a hidden slide, and do not self-correct when later shown. So on
slide reveal `slideshow.js` MUST dispatch a relayout signal — a `window`/element
`resize` event (which the existing GeoGebra/aspect-ratio and MathLive glue already
respond to) or a per-widget refresh — so widgets on non-first slides re-measure. An
e2e/QA check asserts a math or GeoGebra widget on slide 2 renders at correct size
after navigating to it.

An e2e test MUST assert question numbers are **contiguous across slides** (slide 2
starts where slide 1 left off), to lock whichever mechanism is chosen.

### 3. Client — `courses/static/courses/js/slideshow.js`

A new script, loaded on both lesson and quiz unit pages (deferred, alongside the
existing per-page scripts). It is a no-op unless it finds a `[data-slideshow]`
article. When it does:

- Reads the `.slide` sections and renders a **control bar**: `◀ Prev · 2 / 7 ·
  Next ▶` (bilingual EN/PL strings). The bar is inserted **immediately after the
  last `.slide`** (`lastSlide.after(bar)`) — inside the article, below the active
  slide region and **above** the article's trailing content (the quiz Finish form,
  or a lesson's unanchored-notes block). Do **not** `.unit-shell__main.append(...)`
  (that lands below `_unit_footer.html`). So the runtime order on the last slide of a
  quiz is: active slide → control bar → Finish form. Prev/Next use monochrome
  `currentColor` line SVG icons per the repo's icon convention and are real
  focusable `<button>` elements.
- The counter carries `role="status"` / `aria-live="polite"` so slide changes are
  announced to assistive tech.
- Shows slide 0, hides the rest (via the hide mechanism from §2). **The initial show
  of slide 0 counts as a reveal** and (on lesson pages — see Progress completion)
  marks all of slide 0's join-rows seen (same path as a Prev/Next reveal) —
  otherwise a tall slide 0 whose bottom element never intersects the viewport would
  never be reported seen. **Free navigation**: both Prev and Next are live; each is
  disabled only at its respective end (Prev on the first slide, Next on the last).
- **Scroll on slide change:** paging scrolls the newly active slide's top into view
  (or resets page scroll to the article top). Without this, paging from a tall slide
  the reader scrolled down in to a shorter slide would leave the viewport past the
  new slide's content, showing blank space.
- **Keyboard nav:** on slide change, move focus to the newly active slide's
  container (or the control bar) so keyboard users follow the change. The `.slide`
  wrapper is a plain `<div>` and is not focusable by default, so the focus target
  must carry `tabindex="-1"` (or focus the control bar, whose `<button>`s are already
  focusable) for the `.focus()` to actually land. Left/Right
  arrow keys advance/retreat — but the handler MUST **ignore events whose target is
  an editable element** (text/number `input`, `textarea`, `[contenteditable]`,
  `math-field`/MathLive, or anything else with a caret): quiz slides contain answer
  fields where arrows move the caret, and paginating on those keystrokes would break
  answer entry. Bail when `document.activeElement` (or `event.target`) is such a
  field, so arrows only paginate when focus is on non-editable article content or the
  control bar. Both Prev/Next buttons are focusable regardless. An e2e test drives
  an arrow keypress inside a quiz text field and asserts the slide does **not**
  change.
- **Hiding is applied by JS**, never by unconditional default CSS — so with JS off,
  no slide is hidden and all slides render stacked (today's flat page). Graceful
  degradation is automatic.
- **FOUC mitigation:** because `slideshow.js` is deferred, a naïve approach flashes
  all slides stacked for a beat before collapsing to slide 0. Avoid this with a tiny
  **synchronous** head script that adds a `js` class to the root element, and a CSS
  rule gated on it (`.js [data-slideshow] .slide:not(:first-child) { display: none }`,
  or the chosen hide) that pre-hides non-first slides before paint. No-JS never sets
  `.js`, so the all-slides-visible fallback is preserved. `slideshow.js` then takes
  over active-slide management on load.
- **Degenerate guards:** because `[data-slideshow]` is only emitted when
  `slides > 1` (§2), the script normally never even activates for a one-slide or
  zero-slide unit. As belt-and-suspenders it still guards `slides.length <= 1` as a
  no-op — renders **no** control bar, hides nothing — and `slides.length === 0` must
  not throw (no index-0-of-empty access), so no other deferred script on the page is
  disrupted.
- **Quiz "Finish" gating:** the Finish form is the existing `.quiz-finish` /
  `[data-quiz-finish]` form rendered in `_quiz_article.html` **after** the elements
  loop (so, with slides, after the last `.slide` — outside every `.slide`, a sibling
  of them within the article). It **renders visible by default** (no-JS shows it, as
  today); `slideshow.js` finds it by `[data-quiz-finish]` and keeps it hidden until
  the **last** slide is active, so a student must at least reach the last slide before
  finishing. Because it is outside every `.slide`, the hide mechanism never treats it
  as slide content. (This is a reach-the-end gate only, not an answering/engagement
  guarantee — free navigation lets a student page straight to the end.) Per-question
  AJAX answering (`quiz.js`) is unchanged.

### 4. Authoring — builder integration

- **Slide break** joins the builder's add-element palette as a divider-style entry
  with a monochrome line-SVG icon.
- **Create pipeline (must be wired explicitly).** `builder.save_element`
  (`courses/builder.py`) is form-driven: the generic branch does
  `FORM_FOR_TYPE[type_key](...)` then `form.save()`, so a type with no entry would
  `KeyError`. "No edit form" means *no fields to edit*, **not** "unwired." Wire the
  break in via one of: (a) a trivial field-less `SlideBreakElementForm` registered
  in `FORM_FOR_TYPE` whose `save()` creates the `SlideBreakElement`; or (b) a
  dedicated `type_key == "slide_break"` branch in `save_element` that creates the
  `SlideBreakElement` + its `Element` join-row directly without a form. Either way,
  creation produces the concrete row + join-row at the chosen order position like
  any other element.
- In the builder's element list, a break renders as a distinct **thin divider row**
  (not a content card), so the author sees exactly where slides split. It is
  reorderable and deletable like any element, and has no editable fields.
- The builder legend/help gains a one-line note: "Add a slide break to split this
  unit into a slideshow."

## Data flow

**Authoring:** author adds a "Slide break" in the builder → `save_element` creates a
`SlideBreakElement` + its `Element` join-row at the chosen order position (per §4's
explicit branch/form), exactly like any other element.

**Rendering a unit (taking):**
1. `quiz_unit` / `lesson_unit` view → `build_*_context` loads ordered join-rows
   (with `content_object`) → `partition_into_slides` produces `slides` (list of
   lists of join-rows).
2. Template renders `.slide` wrappers around each group's `data-element-id`
   sections; article carries `[data-slideshow]` iff `slides|length > 1` (the
   authoritative rule from §2 — the unit actually paginates; **not** merely
   `is_slideshow`).
3. Browser: `slideshow.js` finds `[data-slideshow]`, builds the control bar, shows
   slide 0. Prev/Next toggle slide visibility. On revealing a slide, the script
   marks **all** of that slide's `data-element-id` elements as seen (not only those
   that happen to intersect the viewport) — see below. For quizzes, per-question
   answers post independently as before; Finish appears only on the last slide.

**Progress completion (server + client interplay).** The `seen` view
(`courses/views.py`) computes `current = set(node.elements.values_list("pk",
flat=True))` — a set of `Element` **join-row** pks that must all be reported seen
for completion. Two changes:
- **Exclude breaks from `current`.** Filter the `node.elements` queryset by
  content type, not concrete pk:
  `node.elements.exclude(content_type=<ContentType of SlideBreakElement>)` (resolve
  the `ContentType` once). A break renders invisibly and is never reported seen, so
  leaving it in `current` would make a slideshow lesson unable to reach 100%. This
  is a distinct queryset/code path from the `partition_into_slides` helper.
- **Mark a whole slide seen on reveal (client) — lesson pages only.** Quiz pages
  have **no** `seen`/progress path: the `seen` view is `require_lesson=True`, and
  `progress.js` binds only to `.lesson[data-seen-url]`. Quiz completion is
  answer-driven (Finish → `finalize_submission`), not seen-driven. So the
  mark-seen-on-reveal behavior described here fires **only on lesson unit pages**.
  `slideshow.js` decides this the drift-proof way: it POSTs seen data **only if the
  article carries `data-seen-url`** (lesson articles do; quiz articles do not), so
  the same code path is correct for both unit types with no page-type sniffing; on a
  quiz page it does no seen reporting at all (it still paginates and gates Finish).
  On today's flat lesson page the reader scrolls past every element
  so all intersect the `progress.js` `IntersectionObserver`. In a slideshow lesson,
  a slide may stack several elements taller than the viewport; a reader can click
  Next without scrolling to the bottom element, which would then never intersect and
  never be reported seen — so the lesson could never complete despite the reader
  visiting every slide. To avoid this, on slide reveal — **including the initial
  show of slide 0** — `slideshow.js` reports **every** `data-element-id` in the newly
  shown slide as seen, by **issuing one batched POST** to the lesson's seen endpoint
  (read from the article's `data-seen-url`), carrying that slide's join-row pks as a
  JSON array — the exact payload shape `progress.js` already uses
  (`JSON.stringify(Array.from(seen))`), with the same CSRF/keepalive handling. It is
  an **independent** request, **not** a mutation of `progress.js`'s internal seen-set
  (that IIFE exposes no hook). This is safe **only because the `seen` view unions**
  the posted pks into the stored set rather than replacing it — verified in
  `courses/views.py`: `merged = set(progress.seen_element_ids) | incoming;
  progress.seen_element_ids = sorted(merged)`. So two independent partial posters
  (progress.js's cumulative set + slideshow.js's per-slide subset) cannot clobber
  each other, and double-firing is idempotent. A test MUST lock this: two separate
  partial POSTs with **disjoint** pk subsets both survive, and completion is reached
  from their union (guarding against a future change to replace-semantics). Visiting
  all slides therefore reports all content join-rows seen → server marks the unit
  complete.

## Error handling

- **Completion-set correctness (required server fix):** exclude slide-break
  join-rows from the `seen` view's `current` set by content-type filter (above).
  Covered by a unit test: a slideshow lesson reaches `completed` after all *content*
  join-rows are reported seen, even though the break never is.
- **Multi-element / tall slides:** handled by "mark a whole slide seen on reveal"
  (above); tested with a slide whose stacked elements exceed the viewport.
- **Empty / degenerate break placement:** leading, trailing, and consecutive breaks
  are handled by the "drop empty groups" rule — they never yield empty slides. A
  unit consisting only of breaks yields zero content slides; `slides.length <= 1`
  makes `slideshow.js` a no-op (no control bar, nothing hidden), so this renders as
  an ordinary (empty) page with no JS error.
- **No-JS / no-IntersectionObserver:** with JS off, all slides show (no hiding is
  applied) — the unit degrades to today's flat page; answering and the no-JS
  progress/finish fallbacks work unchanged.
- **Export/import (dual registry).** Transfer keeps two registries in lockstep: the
  exporter's `SERIALIZERS` map in `courses/transfer/export.py` (type_key → model /
  serializer) and the importer-side registry in `courses/transfer/schema.py`. An
  **unregistered** model is not silently dropped — `serialize_element_data` raises
  `TransferError` (a hard export failure). Both registries must gain a `slide_break`
  entry with a trivial no-field serializer so course export/import round-trips
  breaks.
- **`ElementBase.render()` by-convention template.** `ElementBase.render()` resolves
  `courses/elements/<model_name>.html` by convention. The taking view consumes
  breaks before render (they never reach `render_element`), but a defensive, empty
  `courses/elements/slidebreakelement.html` MUST be added so any generic path that
  iterates all elements and calls `.render()` (e.g. a builder preview) cannot 500 on
  a missing template.
- **Scoring/analytics:** already skip non-`QuestionElement` content objects, so
  breaks are ignored for free (no change needed; guarded by existing behavior).
- **Notes (lessons):** element-anchored notes travel into whatever slide their
  element lands on — no change. The trailing `notes/_unanchored.html` block sits
  **outside** the `slides` loop (it follows the elements loop in
  `_lesson_article.html`), so in slideshow mode it remains a single block at the
  article bottom, visible regardless of the active slide. This is intended — do not
  try to partition unanchored notes into slides.

## Testing

**Unit:**
- `partition_into_slides`: split-on-break; drop leading/trailing/consecutive-break
  empties; non-slideshow unit → single slide with all join-rows; only-breaks → no
  slides. Assert the output holds `Element` join-rows (identity preserved), not
  unwrapped content objects.
- `is_slideshow` derivation true/false.
- `seen` view completion set excludes breaks (by content-type filter) → slideshow
  lesson completes when all content join-rows reported seen.
- **Seen union semantics:** two separate POSTs with disjoint pk subsets both survive
  (the view unions, not replaces); completion is reached from their union.

**View / context:**
- `build_lesson_context` and `build_quiz_context` produce the expected `slides`
  structure (list of lists of join-rows). (The taking context carries no
  `is_slideshow` key — the render gate is `slides|length`.)
- Break join-row pk excluded from `current`.

**Template:**
- Slide `<div class="slide">` wrappers present; `[data-slideshow]` emitted iff
  `slides|length > 1` (present for a genuine multi-slide unit; **absent** for a
  single-slide unit such as one with only a lone trailing/leading break).
- No-JS render shows all slides visible (no hiding attribute/class applied
  server-side).

**e2e (Playwright, real gestures — per the repo's "e2e must drive real UI" rule):**
- Real Prev/Next clicks flip the visible slide and update the `N / total` counter.
- **Quiz question numbers are contiguous across slides** (locks the hide mechanism
  vs. the CSS counter).
- Quiz Finish hidden until the last slide is active.
- Lesson auto-completes after paging through all slides, **including a slide whose
  stacked elements are taller than the viewport** (mark-whole-slide-seen path).
- **Tall slide 0:** a viewport-exceeding first slide is marked seen on initial show
  (init-as-reveal), so a lesson can complete without the reader scrolling that slide
  to the bottom.
- **Single-slide "slideshow":** a unit whose only break is trailing (or leading)
  yields one content slide → no `[data-slideshow]`, no control bar, flat render.
- **Arrow-in-input:** an arrow keypress while focus is in a quiz answer field moves
  the caret and does **not** change the slide.
- **Arrow-advances:** Left/Right arrows **do** advance/retreat the slide when focus
  is on the control bar / non-editable article content (the positive case, so a
  handler that never advances can't pass).
- **Widget relayout:** a MathLive or GeoGebra widget on slide 2 renders at correct
  size after navigating to it (reveal-time relayout signal fired).
- Course export → import preserves slide breaks.

**Conventions honored:** every view ships styled and verified with light+dark
screenshots; monochrome `currentColor` line-SVG icons via the shared `.icon` util;
`uv run` for ruff/pytest/python with **both** `ruff check` and `ruff format
--check`; module-level translatable strings use `gettext_lazy`; run the i18n catalog
tests if a build removes translatable strings and keep the catalog free of obsolete
`#~` entries; no hardcoded test passwords (use `tests.factories.TEST_PASSWORD`);
Django `{# #}` comments single-line only (`{% comment %}` for multi-line).
