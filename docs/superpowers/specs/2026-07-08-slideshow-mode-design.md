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
into the page exactly as today, and quiz answering / marking / progress tracking
are untouched. Slideshow is a client-side view over server-partitioned slide
groups, with a clean no-JS fallback (JS off → all slides stacked = today's flat
page).

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

### 1. Data model — `SlideBreakElement`

A new concrete element type, the 15th, added to `ELEMENT_MODELS` in
`courses/models.py`. It follows the exact shape of every other element type:
subclasses `ElementBase`, declares `elements = GenericRelation(Element)`, and is
pointed at by an `Element` GFK join-row. It has **no content fields** — it is a
pure delimiter. One migration creates the model (and its `ContentType` row is
created by Django's normal `ContentType` machinery / a `RunPython` if the code
needs it eagerly for the transfer registry; the migration is otherwise trivial
since there are no fields).

`is_slideshow` is a **derived** property, never stored: a unit is a slideshow iff
its element list contains at least one `SlideBreakElement`. It is computed in the
context builders from the already-loaded, `content_object`-prefetched element
list, so it costs no extra query.

### 2. Rendering — server partitions elements into slides

`build_lesson_context` and `build_quiz_context` (`courses/views.py`) already load
the unit's ordered elements with `content_object` prefetched. Each gains one step:
**partition the ordered element list into `slides`** — a list of lists of *content*
elements — splitting at each slide-break. Breaks are **consumed** (never rendered
as content). The partition rule:

- Split the ordered element list on each break.
- **Drop empty groups**, so a leading, trailing, or doubled break never produces
  an empty slide.
- A non-slideshow unit (no breaks) yields exactly **one slide** holding every
  element.

A small pure helper (e.g. `partition_into_slides(elements)` in a suitable module —
`courses/quiz.py` or a new `courses/slideshow.py`) does the split and is unit-tested
in isolation. Both context builders call it and add `slides` and `is_slideshow` to
their context dicts.

The article templates `templates/courses/_lesson_article.html` and
`templates/courses/_quiz_article.html` change from a flat
`{% for el in elements %}` loop to a nested one:

```
{% for slide in slides %}
  <section class="slide">
    {% for el in slide %}
      <section data-element-id="{{ el.pk }}" ...>...</section>
    {% endfor %}
  </section>
{% endfor %}
```

Backward-compatibility for the (vast majority) non-slideshow units is preserved by
CSS: `.slide` defaults to **`display: contents`**, so the wrapper vanishes from the
layout box tree and the inner `data-element-id` sections behave exactly as today —
no existing CSS or e2e selector sees a structural change. Only when the article
carries the `[data-slideshow]` attribute (emitted iff `is_slideshow`) does `.slide`
become a real block that the client can show/hide.

### 3. Client — `courses/static/courses/js/slideshow.js`

A new script, loaded on both lesson and quiz unit pages (deferred, alongside the
existing per-page scripts). It is a no-op unless it finds a `[data-slideshow]`
article. When it does:

- Reads the `.slide` sections and renders a **control bar**: `◀ Prev · 2 / 7 ·
  Next ▶` (bilingual EN/PL strings). Prev/Next use monochrome `currentColor` line
  SVG icons per the repo's icon convention.
- Shows slide 0, hides the rest. **Free navigation**: both Prev and Next are live;
  each is disabled only at its respective end (Prev on the first slide, Next on the
  last).
- **Hiding is applied by JS**, never by default CSS — so with JS off, no slide is
  hidden and all slides render stacked (today's flat page). Graceful degradation is
  automatic.
- **Quiz "Finish" gating:** the Finish form stays after the slides in the DOM;
  `slideshow.js` keeps it hidden until the **last** slide is active, so a student
  cannot finish before seeing every question. Per-question AJAX answering (`quiz.js`)
  is unchanged.

### 4. Authoring — builder integration

- **Slide break** joins the builder's add-element palette as a divider-style entry
  with a monochrome line-SVG icon.
- In the builder's element list, a break renders as a distinct **thin divider row**
  (not a content card), so the author sees exactly where slides split. It is
  reorderable and deletable like any element, and has **no edit form** (nothing to
  edit) — adding one simply inserts the row.
- The builder legend/help gains a one-line note: "Add a slide break to split this
  unit into a slideshow."

## Data flow

**Authoring:** author adds a "Slide break" in the builder → a `SlideBreakElement`
row + its `Element` join-row are created at the chosen order position, exactly like
any other element.

**Rendering a unit (taking):**
1. `quiz_unit` / `lesson_unit` view → `build_*_context` loads ordered elements
   (with `content_object`) → `partition_into_slides` produces `slides` +
   `is_slideshow`.
2. Template renders `.slide` wrappers around each group's `data-element-id`
   sections; article carries `[data-slideshow]` iff `is_slideshow`.
3. Browser: `slideshow.js` finds `[data-slideshow]`, builds the control bar, shows
   slide 0. Prev/Next toggle slide visibility. Revealing a slide makes its
   `data-element-id` sections visible → the existing `progress.js`
   `IntersectionObserver` marks them seen. For lessons this means completion
   naturally requires visiting every slide. For quizzes, per-question answers post
   independently as before; Finish appears only on the last slide.

**Progress completion (server):** the `seen` view (`courses/views.py`) computes
`current = set(node.elements...)` — the set of element pks that must all be seen for
completion. This set must **exclude slide-break pks**, because a break renders
invisibly and is never "seen"; otherwise a slideshow lesson could never reach 100%.

## Error handling

- **Completion-set correctness (the one required server fix):** filter slide-break
  element pks out of the `seen` view's `current` set. Covered by a unit test that a
  slideshow lesson reaches `completed` after all *content* elements are seen, even
  though the break never is.
- **Empty / degenerate break placement:** leading, trailing, and consecutive breaks
  are handled by the "drop empty groups" rule — they never yield empty slides. A
  unit consisting only of breaks yields zero content slides (renders empty; harmless
  edge).
- **No-JS / no-IntersectionObserver:** with JS off, all slides show (no hiding is
  applied) — the unit degrades to today's flat page; answering and the no-JS
  progress/finish fallbacks work unchanged.
- **Export/import:** `SlideBreakElement` is registered in the `courses/transfer/`
  serializers so course export/import round-trips breaks. Trivial (no fields), but
  required — an unregistered type would be dropped on export.
- **Scoring/analytics:** already skip non-`QuestionElement` content objects, so
  breaks are ignored for free (no change needed; guarded by existing behavior).
- **Notes (lessons):** notes anchor to elements, so they travel into whatever slide
  their element lands on — no change.

## Testing

**Unit:**
- `partition_into_slides`: split-on-break; drop leading/trailing/consecutive-break
  empties; non-slideshow unit → single slide with all elements; only-breaks → no
  slides.
- `is_slideshow` derivation true/false.
- `seen` view completion set excludes breaks → slideshow lesson completes when all
  content elements seen.

**View / context:**
- `build_lesson_context` and `build_quiz_context` produce the expected `slides`
  structure and `is_slideshow` flag.
- Break pk excluded from `current`.

**Template:**
- Slide wrappers present; `[data-slideshow]` emitted iff slideshow.
- No-JS render shows all slides visible (no hiding attribute/class applied
  server-side).

**e2e (Playwright, real gestures — per the repo's "e2e must drive real UI" rule):**
- Real Prev/Next clicks flip the visible slide and update the `N / total` counter.
- Quiz Finish hidden until the last slide is active.
- Lesson auto-completes after paging through all slides.
- Course export → import preserves slide breaks.

**Conventions honored:** every view ships styled and verified with light+dark
screenshots; monochrome `currentColor` line-SVG icons via the shared `.icon` util;
`uv run` for ruff/pytest/python with **both** `ruff check` and `ruff format
--check`; module-level translatable strings use `gettext_lazy`; run the i18n catalog
tests if a build removes translatable strings and keep the catalog free of obsolete
`#~` entries; no hardcoded test passwords (use `tests.factories.TEST_PASSWORD`);
Django `{# #}` comments single-line only (`{% comment %}` for multi-line).
