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
`courses/models.py`. It follows the exact shape of every other element type:
subclasses `ElementBase`, declares `elements = GenericRelation(Element)`, and is
pointed at by an `Element` GFK join-row. It has **no content fields** — it is a
pure delimiter. One migration creates the model; its `ContentType` row is created
by Django's normal `ContentType` machinery.

`is_slideshow` is a **derived** property, never stored: a unit is a slideshow iff
its element list contains at least one join-row whose `content_object` is a
`SlideBreakElement`. It is computed in the context builders from the already-loaded,
`content_object`-prefetched element list, so it costs no extra query.

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
join-rows) and `is_slideshow` (bool) to their context dicts. **Every** template
render of the two article partials must supply both `slides` and `is_slideshow`;
the partials are written to loop `slides` and never fall back to a flat `elements`
loop, so a caller that forgets them renders a blank unit. Audit the other callers
that build `elements` lists (e.g. builder/preview paths in `views_manage.py`): any
that render `_lesson_article.html` / `_quiz_article.html` must route through the
context builders or supply `slides`/`is_slideshow` themselves.

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
`.slide` become a real block the client shows/hides. (`is_slideshow` remains a
useful derived flag, but the render/JS gate is the slide **count**, so a
single-slide "slideshow" is indistinguishable from a normal unit at runtime.)

**Quiz question numbering (a required constraint on the hide mechanism).**
`courses.css` numbers quiz questions with a pure CSS counter
(`.quiz { counter-reset: quiz-q }`, `.quiz .el--question { counter-increment:
quiz-q }`, `::before { content: counter(quiz-q) }`). CSS counters do **not**
increment inside elements hidden with `display: none` or the `hidden` attribute —
so if inactive slides were hidden that way, each visible slide's questions would
renumber from 1 ("Question 1", "Question 2" on every slide). Therefore the hide
mechanism **must preserve counter incrementing / box generation**. Acceptable
resolutions (implementation picks one):
1. Hide inactive slides with a counting-preserving method — e.g.
   `visibility: hidden` combined with `position: absolute` (or clip) so the box is
   still generated (counter increments) but removed from flow — and additionally
   make inactive slides inert to AT/focus (`aria-hidden` + not focusable), since
   `visibility: hidden` already removes them from the a11y tree but positioned
   content still needs `inert`-like handling. **Layout containment is required:**
   absolutely-positioned inactive slides still contribute to their container's
   scrollable overflow and anchor to the nearest positioned ancestor, so a tall
   hidden slide would otherwise add phantom scroll area or overlay from page top.
   The active-slide container must therefore be `position: relative` and clip/zero
   out inactive slides (`overflow: hidden` on the container, or the inactive slide
   sized to zero) so page scroll height reflects **only** the active slide. Add a
   QA note / assertion that scroll height tracks the active slide, not the tallest;
   **or**
2. Move quiz question numbering off the pure CSS counter (compute numbers
   server-side into the markup) so hiding by `display: none` is safe. This
   resolution MUST also **remove/disable** the existing
   `.quiz .el--question::before { content: counter(quiz-q) }` rule, or questions
   render doubled; and note that it changes numbering for **every** quiz (not just
   slideshow ones), so affected quiz tests and screenshots must be updated
   accordingly.
An e2e test MUST assert question numbers are **contiguous across slides** (slide 2
starts where slide 1 left off), to lock whichever mechanism is chosen.

### 3. Client — `courses/static/courses/js/slideshow.js`

A new script, loaded on both lesson and quiz unit pages (deferred, alongside the
existing per-page scripts). It is a no-op unless it finds a `[data-slideshow]`
article. When it does:

- Reads the `.slide` sections and renders a **control bar**: `◀ Prev · 2 / 7 ·
  Next ▶` (bilingual EN/PL strings). The bar is inserted at a defined DOM point:
  appended inside `.unit-shell__main` after the article partial (so it sits below
  the current slide, above the unit footer). Prev/Next use monochrome
  `currentColor` line SVG icons per the repo's icon convention and are real
  focusable `<button>` elements.
- The counter carries `role="status"` / `aria-live="polite"` so slide changes are
  announced to assistive tech.
- Shows slide 0, hides the rest (via the counting-preserving mechanism from §2).
  **The initial show of slide 0 counts as a reveal** and marks all of slide 0's
  join-rows seen (same path as a Prev/Next reveal, see Data flow) — otherwise a
  tall slide 0 whose bottom element never intersects the viewport would never be
  reported seen. **Free navigation**: both Prev and Next are live; each is disabled
  only at its respective end (Prev on the first slide, Next on the last).
- **Keyboard nav:** on slide change, move focus to the newly active slide's
  container (or the control bar) so keyboard users follow the change. Left/Right
  arrow keys advance/retreat — but the handler MUST **ignore events whose target is
  an editable element** (text/number `input`, `textarea`, `[contenteditable]`,
  `math-field`/MathLive, or anything else with a caret): quiz slides contain answer
  fields where arrows move the caret, and paginating on those keystrokes would break
  answer entry. Bail when `document.activeElement` (or `event.target`) is such a
  field, so arrows only paginate when focus is on non-editable article content or the
  control bar. Both Prev/Next buttons are focusable regardless. An e2e test drives
  an arrow keypress inside a quiz text field and asserts the slide does **not**
  change.
- **Hiding is applied by JS**, never by default CSS — so with JS off, no slide is
  hidden and all slides render stacked (today's flat page). Graceful degradation is
  automatic.
- **Degenerate guards:** because `[data-slideshow]` is only emitted when
  `slides > 1` (§2), the script normally never even activates for a one-slide or
  zero-slide unit. As belt-and-suspenders it still guards `slides.length <= 1` as a
  no-op — renders **no** control bar, hides nothing — and `slides.length === 0` must
  not throw (no index-0-of-empty access), so no other deferred script on the page is
  disrupted.
- **Quiz "Finish" gating:** the Finish form stays after the slides in the DOM;
  `slideshow.js` keeps it hidden until the **last** slide is active, so a student
  must at least reach the last slide before finishing. (This is a reach-the-end
  gate only, not an answering/engagement guarantee — free navigation lets a student
  page straight to the end.) Per-question AJAX answering (`quiz.js`) is unchanged.

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
   lists of join-rows) + `is_slideshow`.
2. Template renders `.slide` wrappers around each group's `data-element-id`
   sections; article carries `[data-slideshow]` iff `is_slideshow`.
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
- **Mark a whole slide seen on reveal (client).** On today's flat page the reader
  scrolls past every element so all intersect the `progress.js`
  `IntersectionObserver`. In a slideshow, a slide may stack several elements taller
  than the viewport; a reader can click Next without scrolling to the bottom
  element, which would then never intersect and never be reported seen — so the
  lesson could never complete despite the reader visiting every slide. To avoid
  this, on slide reveal — **including the initial show of slide 0** —
  `slideshow.js` reports **every** `data-element-id` in the newly shown slide as
  seen. The existing `seen` endpoint already accepts a **JSON array of pks**
  (`progress.js` POSTs `JSON.stringify(Array.from(seen))`), so this is **one batched
  POST** per reveal carrying that slide's join-row pks — not N single-pk requests —
  reusing the same payload shape and CSRF/keepalive handling. Visiting all slides
  therefore reports all content join-rows seen → server marks the unit complete.
  (Coordinate with `progress.js` so the two do not double-fire; simplest is for
  `slideshow.js` to add the slide's pks into the same seen-set/flush machinery
  rather than issue an independent request.)

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
- **Notes (lessons):** notes anchor to elements, so they travel into whatever slide
  their element lands on — no change.

## Testing

**Unit:**
- `partition_into_slides`: split-on-break; drop leading/trailing/consecutive-break
  empties; non-slideshow unit → single slide with all join-rows; only-breaks → no
  slides. Assert the output holds `Element` join-rows (identity preserved), not
  unwrapped content objects.
- `is_slideshow` derivation true/false.
- `seen` view completion set excludes breaks (by content-type filter) → slideshow
  lesson completes when all content join-rows reported seen.

**View / context:**
- `build_lesson_context` and `build_quiz_context` produce the expected `slides`
  structure (list of lists of join-rows) and `is_slideshow` flag.
- Break join-row pk excluded from `current`.

**Template:**
- Slide `<div class="slide">` wrappers present; `[data-slideshow]` emitted iff
  slideshow.
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
- Course export → import preserves slide breaks.

**Conventions honored:** every view ships styled and verified with light+dark
screenshots; monochrome `currentColor` line-SVG icons via the shared `.icon` util;
`uv run` for ruff/pytest/python with **both** `ruff check` and `ruff format
--check`; module-level translatable strings use `gettext_lazy`; run the i18n catalog
tests if a build removes translatable strings and keep the catalog free of obsolete
`#~` entries; no hardcoded test passwords (use `tests.factories.TEST_PASSWORD`);
Django `{# #}` comments single-line only (`{% comment %}` for multi-line).
