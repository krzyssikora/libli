# Slideshow deck redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the unit-level slideshow taking view into a fixed-height framed deck with arrow-only navigation, a stable footer bar, progress dots (counter fallback for large decks), and a cross-fade between slides.

**Architecture:** Presentation-layer only. `slideshow.js` builds a `.slideshow-deck` wrapper (a `.slideshow-stage` holding the slides + a footer `.slideshow-bar`) and drives a small `show()` state machine; `courses.css` gains the deck/stage/bar rules and re-scopes the existing global hide rules to the child combinator so they stop reaching slides once JS nests them in the deck. The two unit templates carry the translated `aria-label`/position strings via `window.SLIDESHOW_I18N`; no model, server, or builder change.

**Tech Stack:** Vanilla ES5-style JS (matching the existing `slideshow.js`), token-driven CSS, Django templates + gettext (`locale/pl`), Playwright e2e (`pytest -m e2e`).

## Global Constraints

- **No-JS fallback unchanged:** JS off → all slides stacked = flat page. All new behavior is gated behind the JS-built `.slideshow-deck`.
- **IntersectionObserver-safety:** inactive slides must be `display:none` **at rest** (only the active slide, plus a transiently-fading pair, may be rendered), or `progress.js`'s observer auto-completes multi-slide lessons on load. Do **not** give inactive deck slides a rendered `opacity:0`/`visibility:hidden` resting state.
- **Backward-compatible button names:** Playwright `get_by_role("button", name="Next")` matches the accessible name by case-insensitive substring, so `aria-label="Next slide"` keeps existing assertions matching. Preserve this.
- **ES5 style:** `var`, function expressions, no arrow functions/`const`/`let` — match the existing file so the linter/bundler stays happy.
- **Canonical fade duration:** JS `FADE_MS` and the CSS slide `transition` duration are the same **320ms** and must be kept in lockstep.
- **`DOTS_MAX = 12`:** ≤12 slides → dots; >12 → text counter.
- **Run e2e with:** `uv run pytest tests/test_e2e_slideshow.py -m e2e -v` (the file is marked `e2e`, excluded from the default run; the explicit `-m e2e` includes it). Python tooling is only on PATH via `uv run`.

---

### Task 1: Arrow-only nav buttons + i18n labels

Drop the visible button text; move the label to `aria-label`. Add the `pos` (position) and keep `nav` strings, with clean Polish translations. This is independently shippable and addresses the "inconsistent Polish button text" complaint on its own.

**Files:**
- Modify: `courses/static/courses/js/slideshow.js` (the `iconBtn` helper + its two call sites)
- Modify: `templates/courses/lesson_unit.html:29` and `templates/courses/quiz_unit.html:25` (the `window.SLIDESHOW_I18N` line)
- Modify: `courses/static/courses/css/courses.css` (`.slideshow-bar__prev/next` sizing for icon-only)
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: `tests/test_e2e_slideshow.py` (new `test_nav_buttons_are_arrow_only`)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `window.SLIDESHOW_I18N = { prev, next, nav, pos }` where `prev`/`next` are `aria-label` strings, `pos` is the position template `"Slide {n} of {total}"`. `iconBtn(cls, pathD, label)` sets `aria-label=label` and renders only the chevron SVG (no text span).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_e2e_slideshow.py` (reuses `_seed_slideshow_lesson_3`):

```python
@pytest.mark.django_db(transaction=True)
def test_nav_buttons_are_arrow_only(page, live_server):
    # Buttons render an icon only (no visible text) but keep an accessible name
    # via aria-label; get_by_role name= still resolves by substring match.
    student, path = _seed_slideshow_lesson_3("s_arrows")
    _login(page, live_server, "s_arrows")
    page.goto(f"{live_server.url}{path}")
    nxt = page.get_by_role("button", name="Next")
    expect(nxt).to_be_visible()
    # aria-label carries the accessible name; no visible text node.
    assert nxt.get_attribute("aria-label") == "Next slide"
    assert (nxt.inner_text() or "").strip() == ""
    prv = page.get_by_role("button", name="Previous")
    assert prv.get_attribute("aria-label") == "Previous slide"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_e2e_slideshow.py::test_nav_buttons_are_arrow_only -m e2e -v`
Expected: FAIL — today the buttons carry visible text ("Prev"/"Next") and `aria-label` is absent.

- [ ] **Step 3: Update the i18n strings in both templates**

In `templates/courses/lesson_unit.html` (line ~29) and `templates/courses/quiz_unit.html` (line ~25), replace the `SLIDESHOW_I18N` line with (identical in both files):

```html
  <script>window.SLIDESHOW_I18N = { prev: "{% trans 'Previous slide' %}", next: "{% trans 'Next slide' %}", nav: "{% trans 'Slides' %}", pos: "{% trans 'Slide {n} of {total}' %}" };</script>
```

- [ ] **Step 4: Rewrite `iconBtn` to be icon-only with `aria-label`**

In `courses/static/courses/js/slideshow.js`, replace the `iconBtn` function and its two call sites. New `iconBtn` (note: drops the `iconFirst` param and the visible `<span>`, adds `aria-label`):

```javascript
  // Icon-only button: chevron SVG + aria-label for the accessible name (screen
  // readers + Playwright get_by_role name=). No visible text.
  function iconBtn(cls, pathD, label) {
    var b = document.createElement("button");
    b.type = "button"; b.className = cls;
    b.setAttribute("aria-label", label);
    b.innerHTML = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
      'aria-hidden="true" focusable="false"><path d="' + pathD + '"/></svg>';
    return b;
  }
```

Update the fallback i18n default (add `pos`/`nav`, crash-safe) and the two call sites — find:

```javascript
  var i18n = window.SLIDESHOW_I18N || { prev: "Prev", next: "Next" };
```
replace with:
```javascript
  var i18n = window.SLIDESHOW_I18N ||
    { prev: "Previous slide", next: "Next slide", nav: "Slides", pos: "Slide {n} of {total}" };
```

Find the two `iconBtn(...)` calls:
```javascript
  var prev = iconBtn("slideshow-bar__prev", "M15 6l-6 6 6 6", i18n.prev, true);
  ...
  var next = iconBtn("slideshow-bar__next", "M9 6l6 6-6 6", i18n.next, false);
```
replace with (drop the trailing boolean):
```javascript
  var prev = iconBtn("slideshow-bar__prev", "M15 6l-6 6 6 6", i18n.prev);
  ...
  var next = iconBtn("slideshow-bar__next", "M9 6l6 6-6 6", i18n.next);
```

- [ ] **Step 5: Adjust the button CSS for icon-only**

In `courses/static/courses/css/courses.css`, **replace the entire `.slideshow-bar__prev, .slideshow-bar__next` rule** (currently sized for icon+text with `gap`/`padding`/`font-size`/`font-weight`) with this compact-square rule:

```css
.slideshow-bar__prev,
.slideshow-bar__next {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.15rem;
  height: 2.15rem;
  padding: 0;
  border-radius: .5rem;
  border: 1px solid var(--border-strong);
  background: var(--surface-raised);
  color: var(--text-primary);
  cursor: pointer;
}
```

(Leave the `:hover`, `:disabled`, and `.ic` rules that follow unchanged.)

- [ ] **Step 6: Add the Polish translations and compile**

Run makemessages for Polish only (English is the source language — the msgids ARE the English text, so no `en` catalog entry is needed and regenerating the `en` `.mo` would leave an uncommitted artifact):

Run: `uv run python manage.py makemessages -l pl`

Then in `locale/pl/LC_MESSAGES/django.po`, set the three NEW entries (they are additive — the existing `Prev`/`Next`/`Slides` entries stay, they're used by other templates). Ensure none is marked `#, fuzzy`:

```
msgid "Previous slide"
msgstr "Poprzedni slajd"

msgid "Next slide"
msgstr "Następny slajd"

msgid "Slide {n} of {total}"
msgstr "Slajd {n} z {total}"
```

Run: `uv run python manage.py compilemessages`

- [ ] **Step 7: Run the test to verify it passes + no regressions**

Run: `uv run pytest tests/test_e2e_slideshow.py -m e2e -v`
Expected: `test_nav_buttons_are_arrow_only` PASSES; all existing tests still pass (`get_by_role("button", name="Next")` matches `"Next slide"` by substring; no test asserts visible button text).

- [ ] **Step 8: Commit**

```bash
git add courses/static/courses/js/slideshow.js templates/courses/lesson_unit.html templates/courses/quiz_unit.html courses/static/courses/css/courses.css locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_e2e_slideshow.py
git commit -m "feat(slideshow): arrow-only nav buttons with translated aria-labels"
```

---

### Task 2: Fixed-height framed deck (stable bar)

Build the deck wrapper, move slides into a fixed-height stage, re-scope the global hide rules to the child combinator, establish the all-hidden resting baseline, and drive an instant-swap `show()` state machine (cross-fade comes in Task 4). Keep the existing text counter element for now so the four counter e2e tests stay green; the dots/status swap is Task 3. This delivers the core fix: the bar no longer moves.

**Files:**
- Modify: `courses/static/courses/js/slideshow.js` (deck build + `show()` rewrite)
- Modify: `courses/static/courses/css/courses.css` (child-combinator rescoping + `.slideshow-deck`/`.slideshow-stage` rules + bar-as-footer)
- Test: `tests/test_e2e_slideshow.py` (new seeds + structure/stability/no-premature-completion tests)

**Interfaces:**
- Consumes: `i18n` object and `iconBtn` from Task 1.
- Produces: DOM `article > .slideshow-deck > (.slideshow-stage > .slide*, nav.slideshow-bar)`. `show(n)` state machine with `var idx = -1` sentinel, `clamp(n)`, `updateIndicator()`, `onReveal(slide)`. Slides carry the `hidden` attribute when inactive (`display:none`) and `.is-active` when active.

- [ ] **Step 1: Write the failing tests (structure, bar stability, no premature completion) + new seeds**

Add two seed helpers to `tests/test_e2e_slideshow.py`:

```python
def _seed_slideshow_lesson_short_first_tall_later(username):
    """3 slides: slide 0 short, slide 2 very tall. In a fixed-height deck the
    footer bar must sit at the same y on slide 0 and slide 2."""
    from courses.models import SlideBreakElement
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    add_element(unit, TextElement.objects.create(body="<p>short</p>"))
    add_element(unit, SlideBreakElement.objects.create())
    add_element(unit, TextElement.objects.create(body="<p>middle</p>"))
    add_element(unit, SlideBreakElement.objects.create())
    tall = "".join(f"<p>Paragraph {i} of a tall last slide.</p>" for i in range(200))
    add_element(unit, TextElement.objects.create(body=tall))
    EnrollmentFactory(student=student, course=course)
    return student, _unit_path(unit)


def _seed_slideshow_lesson_many(username):
    """13-slide lesson (t brk t brk ... t) for the >DOTS_MAX counter fallback."""
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    layout = []
    for i in range(13):
        if i:
            layout.append("brk")
        layout.append("t")
    unit = seed_slideshow_unit(course, "lesson", layout=layout)
    EnrollmentFactory(student=student, course=course)
    return student, _unit_path(unit)
```

Add three tests:

```python
@pytest.mark.django_db(transaction=True)
def test_deck_structure(page, live_server):
    student, path = _seed_slideshow_lesson_3("s_struct")
    _login(page, live_server, "s_struct")
    page.goto(f"{live_server.url}{path}")
    # deck wraps stage (with the slides) and the bar as its footer
    expect(page.locator(".slideshow-deck .slideshow-stage .slide")).to_have_count(3)
    expect(page.locator(".slideshow-deck > .slideshow-bar")).to_have_count(1)
    # head + trailing regions stay OUTSIDE the deck
    expect(page.locator(".slideshow-deck [data-unit-done]")).to_have_count(0)


@pytest.mark.django_db(transaction=True)
def test_bar_position_is_stable_across_slides(page, live_server):
    # The core fix: bar y must not move between a short slide and a tall one.
    student, path = _seed_slideshow_lesson_short_first_tall_later("s_stable")
    _login(page, live_server, "s_stable")
    page.goto(f"{live_server.url}{path}")
    bar = page.locator(".slideshow-bar")
    y0 = bar.bounding_box()["y"]
    page.get_by_role("button", name="Next").click()
    page.get_by_role("button", name="Next").click()  # to the tall slide 2
    y2 = bar.bounding_box()["y"]
    assert abs(y0 - y2) < 2, f"bar moved: {y0} -> {y2}"


@pytest.mark.django_db(transaction=True)
def test_multi_slide_lesson_not_completed_on_load(page, live_server):
    # display:none-at-rest keeps progress.js's IntersectionObserver from marking
    # unvisited slides seen, so a fresh multi-slide lesson is NOT auto-completed.
    student, path = _seed_slideshow_lesson_3("s_noauto")
    _login(page, live_server, "s_noauto")
    page.goto(f"{live_server.url}{path}")
    expect(page.locator(".slideshow-bar")).to_be_visible()  # deck built
    expect(page.locator("[data-unit-done]")).not_to_have_class(re.compile(r"is-complete"))
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_e2e_slideshow.py::test_deck_structure tests/test_e2e_slideshow.py::test_bar_position_is_stable_across_slides tests/test_e2e_slideshow.py::test_multi_slide_lesson_not_completed_on_load -m e2e -v`
Expected: FAIL — no `.slideshow-deck`/`.slideshow-stage` exists yet, and the flow-inserted bar moves with slide height.

- [ ] **Step 3: Re-scope the global hide rules to the child combinator**

In `courses/static/courses/css/courses.css`, change the combinator in these three rules from descendant to child so they stop matching once JS nests the slides in the deck. Replace:

```css
[data-slideshow] .slide { display: block; }
```
```css
html.js [data-slideshow] .slide:not(.is-active) { display: none; }
```
```css
html.js [data-slideshow] .slide:not(:first-child):not(.is-active) { display: none; }
```
with (only the combinator changes, `.slide` → `> .slide`):

```css
[data-slideshow] > .slide { display: block; }
```
```css
html.js [data-slideshow] > .slide:not(.is-active) { display: none; }
```
```css
html.js [data-slideshow] > .slide:not(:first-child):not(.is-active) { display: none; }
```

- [ ] **Step 4: Add the deck / stage / bar-footer CSS**

In `courses/static/courses/css/courses.css`, immediately after the (now child-combinator) FOUC rule, add:

```css
/* ── Slideshow deck (JS-built) ─────────────────────────────────────────────
   slideshow.js wraps the moved slides in .slideshow-deck > .slideshow-stage and
   appends .slideshow-bar as the deck footer. The stage is a FIXED height so the
   footer bar sits at a constant y on every slide (short slides get whitespace;
   tall slides scroll inside the stage). Deck slides are display:none at rest
   (only the active one renders) — IntersectionObserver-safe, same as the global
   rules that no longer reach them. */
.slideshow-deck {
  border: 1px solid var(--border-strong);
  border-radius: .75rem;
  background: var(--surface-raised);
  box-shadow: 0 6px 22px rgb(0 0 0 / 8%);
  overflow: hidden;
  margin-block: var(--space-6);
}
.slideshow-stage {
  position: relative;
  height: clamp(360px, 62vh, 640px);
}
/* 2 classes → out-specifies .slide{display:contents}; absolute so slides stack
   for the eventual cross-fade and the stage owns the fixed height. */
.slideshow-deck .slide {
  display: block;
  position: absolute;
  inset: 0;
  overflow-y: auto;
  padding: var(--space-6);
}
/* settled-hidden: display:none beats the 2-class deck rule only if explicit. */
.slideshow-deck .slide[hidden] { display: none; }
```

Then **replace the entire existing `.slideshow-bar` rule** (it is now the deck footer, not a flow element after the last slide — this drops the old `margin-top`/`padding-top` and adds `padding`/`background`):

```css
.slideshow-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-default);
}
```

- [ ] **Step 5: Rewrite `slideshow.js` — build the deck + `show()` state machine**

First, **change the sentinel**: the file has `var idx = 0;` (line ~9, above the replaced region so it survives); **change it to `var idx = -1;`** and add `var DOTS_MAX = 12;` on the next line. This is required — Task 2's `show()` opens with `if (idx !== -1 && target === idx) return;`, so leaving `idx = 0` would make the initial `show(0)` return immediately and never reveal slide 0 (blank deck).

Then replace the body of `courses/static/courses/js/slideshow.js` from the `var bar = document.createElement("nav");` line through the final `show(0);` with the following. Keep everything **above** `var bar` — the `article`/`slides` guards, `i18n`, and `iconBtn` — from Task 1. **Note:** in the current file the `var prev = iconBtn(...)` and `var next = iconBtn(...)` definitions sit *below* `var bar` (lines ~33 and ~39), i.e. **inside** the replaced region, so this replacement block **re-includes them at its top** (do not expect them to survive from Task 1).

```javascript
  // --- Arrow buttons (re-included here: in the original file these sit below the
  //     `var bar` anchor, inside this replaced region).
  var prev = iconBtn("slideshow-bar__prev", "M15 6l-6 6 6 6", i18n.prev);
  var next = iconBtn("slideshow-bar__next", "M9 6l6 6-6 6", i18n.next);

  // --- Build the deck: move slides into a fixed-height stage; bar is the footer.
  var deck = document.createElement("div");
  deck.className = "slideshow-deck";
  var stage = document.createElement("div");
  stage.className = "slideshow-stage";
  slides[0].parentNode.insertBefore(deck, slides[0]); // deck takes the slides' spot
  deck.appendChild(stage);
  slides.forEach(function (s) {
    stage.appendChild(s);          // move into the stage
    s.setAttribute("hidden", "");  // all-hidden resting baseline; show(0) reveals slide 0
  });

  // --- Position indicator (Task 2: text counter; Task 3 swaps in dots + status).
  var counter = document.createElement("span");
  counter.className = "slideshow-bar__counter";
  counter.setAttribute("data-slideshow-counter", "");
  counter.setAttribute("role", "status");
  counter.setAttribute("aria-live", "polite");

  var bar = document.createElement("nav");
  bar.className = "slideshow-bar";
  bar.setAttribute("aria-label", i18n.nav || "Slides");
  bar.appendChild(prev);
  bar.appendChild(counter);
  bar.appendChild(next);
  deck.appendChild(bar); // footer of the deck

  function updateIndicator() {
    counter.textContent = (idx + 1) + " / " + slides.length;
  }

  // --- seen / finish plumbing (unchanged behavior) ---
  var seenUrl = article.getAttribute("data-seen-url"); // lessons only; quizzes lack it
  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }
  var markDone = window.unitMarkDone;
  function markSlideSeen(slide) {
    if (!seenUrl) return;
    var pks = Array.prototype.map.call(
      slide.querySelectorAll("[data-element-id]"),
      function (el) { return parseInt(el.getAttribute("data-element-id"), 10); }
    ).filter(function (n) { return !isNaN(n); });
    if (!pks.length) return;
    fetch(seenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify(pks),
      keepalive: true,
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && d.completed) markDone(); })
      .catch(function () {});
  }
  var finish = document.querySelector("[data-quiz-finish]"); // quiz only
  function updateFinish() {
    if (finish) finish.toggleAttribute("hidden", idx !== slides.length - 1);
  }
  function onReveal(slide) {
    markSlideSeen(slide);
    updateFinish();
    window.dispatchEvent(new Event("resize")); // MathLive/GeoGebra/KaTeX re-measure
  }

  // --- show(): state machine. Task 2 = instant swap; Task 4 adds the cross-fade.
  function clamp(n) { return Math.max(0, Math.min(slides.length - 1, n)); }
  function show(n) {
    var target = clamp(n);
    if (idx !== -1 && target === idx) return;   // Step 0: boundary no-op
    var out = slides[idx];                        // old idx (undefined on initial)
    idx = target;
    var inn = slides[idx];
    // Step 1: non-visual sync updates
    updateIndicator();
    prev.disabled = idx === 0;
    next.disabled = idx === slides.length - 1;
    // Step 2: render incoming, focus, reveal (in must be rendered before focus)
    inn.removeAttribute("hidden");
    inn.setAttribute("tabindex", "-1");
    inn.scrollTop = 0;
    inn.classList.add("is-active");
    try { inn.focus({ preventScroll: true }); } catch (e) {}
    onReveal(inn);
    // Step 3 (instant in Task 2): hide the outgoing slide
    if (out && out !== inn) {
      out.classList.remove("is-active");
      out.setAttribute("hidden", "");
    }
  }

  prev.addEventListener("click", function () { show(idx - 1); });
  next.addEventListener("click", function () { show(idx + 1); });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    var t = e.target;
    var tag = t && t.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" ||
        (t && t.isContentEditable) || tag === "MATH-FIELD") return;
    if (!article.contains(t) && !bar.contains(t)) return;
    e.preventDefault();
    show(idx + (e.key === "ArrowRight" ? 1 : -1));
  });

  show(0); // initial reveal (out === undefined → slide 0 settled active)
```

- [ ] **Step 6: Run the new + existing tests**

Run: `uv run pytest tests/test_e2e_slideshow.py -m e2e -v`
Expected: the three new tests PASS; the four counter tests (`test_prev_next_paginate_and_counter`, `test_arrow_in_text_field...`, `test_arrow_in_select_or_radio...`, `test_arrow_on_bar_advances_slide`) still PASS (the `[data-slideshow-counter]` element is retained this task); `test_lesson_completes_after_paging_tall_slides`, `test_finish_hidden_until_last_slide`, `test_math_widget_on_slide_2...`, `test_single_slide_no_control_bar`, `test_no_js_shows_all_slides` still PASS.

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/js/slideshow.js courses/static/courses/css/courses.css tests/test_e2e_slideshow.py
git commit -m "feat(slideshow): fixed-height framed deck with a stable footer bar"
```

---

### Task 3: Progress dots + dedicated live region

Replace the visible text counter with progress dots (≤`DOTS_MAX` slides) or a text counter (>`DOTS_MAX`), and move the screen-reader position announcement to a single dedicated clip-based `[data-slideshow-status]` live region. Migrate the four e2e tests that asserted `[data-slideshow-counter]` text on small seeds.

**Files:**
- Modify: `courses/static/courses/js/slideshow.js` (indicator build + `updateIndicator`)
- Modify: `courses/static/courses/css/courses.css` (dots, counter, sr-only status)
- Test: `tests/test_e2e_slideshow.py` (migrate 4 counter tests; add dots/counter/status test)

**Interfaces:**
- Consumes: the `bar`, `idx`, `slides`, `i18n`, `DOTS_MAX`, `updateIndicator()` seam from Task 2.
- Produces: `[data-slideshow-dots]` (one `.slideshow-bar__dot` per slide, active one `.is-active`, `aria-hidden`) OR `[data-slideshow-counter]` (`aria-hidden`, only when `slides.length > DOTS_MAX`); always `[data-slideshow-status]` (`role=status`, clip sr-only) carrying the `pos` string. `posText()` helper: `i18n.pos.replace("{n}", idx+1).replace("{total}", slides.length)`.

- [ ] **Step 1: Write/adjust the failing tests**

Add a new test and a large-deck helper is already added in Task 2 (`_seed_slideshow_lesson_many`). New test:

Two separate tests (kept separate so each uses a single login per fresh `page` — logging in twice on one page hangs, because allauth redirects the already-authenticated second `_login` away from the login form and the `.fill()` times out):

```python
@pytest.mark.django_db(transaction=True)
def test_position_indicator_dots_and_status(page, live_server):
    # ≤12 slides → dots (one per slide, active tracks position); status live region
    # announces "Slide N of 3" and updates on navigation.
    student, path = _seed_slideshow_lesson_3("s_dots")
    _login(page, live_server, "s_dots")
    page.goto(f"{live_server.url}{path}")
    expect(page.locator("[data-slideshow-dots] .slideshow-bar__dot")).to_have_count(3)
    expect(page.locator("[data-slideshow-counter]")).to_have_count(0)
    expect(page.locator("[data-slideshow-status]")).to_have_text("Slide 1 of 3")
    dots = page.locator("[data-slideshow-dots] .slideshow-bar__dot")
    expect(dots.nth(0)).to_have_class(re.compile(r"is-active"))
    page.get_by_role("button", name="Next").click()
    expect(page.locator("[data-slideshow-status]")).to_have_text("Slide 2 of 3")
    expect(dots.nth(1)).to_have_class(re.compile(r"is-active"))


@pytest.mark.django_db(transaction=True)
def test_position_indicator_counter_fallback_over_dots_max(page, live_server):
    # >12 slides → text counter, no dots; status still announces "Slide 1 of 13".
    student, path = _seed_slideshow_lesson_many("s_many")
    _login(page, live_server, "s_many")
    page.goto(f"{live_server.url}{path}")
    expect(page.locator("[data-slideshow-counter]")).to_have_text("1 / 13")
    expect(page.locator("[data-slideshow-dots]")).to_have_count(0)
    expect(page.locator("[data-slideshow-status]")).to_have_text("Slide 1 of 13")
```

Migrate the four tests that assert `[data-slideshow-counter]` text on ≤12-slide seeds to assert `[data-slideshow-status]` instead. Apply these exact replacements:

- In `test_prev_next_paginate_and_counter`:
  - `expect(page.locator("[data-slideshow-counter]")).to_have_text("1 / 3")` → `expect(page.locator("[data-slideshow-status]")).to_have_text("Slide 1 of 3")`
  - `expect(page.locator("[data-slideshow-counter]")).to_have_text("2 / 3")` → `expect(page.locator("[data-slideshow-status]")).to_have_text("Slide 2 of 3")`
- In `test_arrow_in_text_field_does_not_change_slide`:
  - `expect(page.locator("[data-slideshow-counter]")).to_have_text("1 / 3")` → `expect(page.locator("[data-slideshow-status]")).to_have_text("Slide 1 of 3")`
- In `test_arrow_in_select_or_radio_does_not_change_slide`:
  - same replacement as above (`"1 / 3"` → status `"Slide 1 of 3"`)
- In `test_arrow_on_bar_advances_slide`:
  - `expect(page.locator("[data-slideshow-counter]")).to_have_text("2 / 3")` → `expect(page.locator("[data-slideshow-status]")).to_have_text("Slide 2 of 3")`

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_e2e_slideshow.py::test_position_indicator_dots_and_status tests/test_e2e_slideshow.py::test_position_indicator_counter_fallback_over_dots_max -m e2e -v`
Expected: FAIL — no `[data-slideshow-dots]` / `[data-slideshow-status]` yet.

- [ ] **Step 3: Replace the indicator build + `updateIndicator` in `slideshow.js`**

In `courses/static/courses/js/slideshow.js`, replace the counter-creation block (from Task 2's `var counter = document.createElement("span");` through the `deck.appendChild(bar);` line — the entire block quoted below) with a dots-or-counter build plus a dedicated status region. Replace this block:

```javascript
  var counter = document.createElement("span");
  counter.className = "slideshow-bar__counter";
  counter.setAttribute("data-slideshow-counter", "");
  counter.setAttribute("role", "status");
  counter.setAttribute("aria-live", "polite");

  var bar = document.createElement("nav");
  bar.className = "slideshow-bar";
  bar.setAttribute("aria-label", i18n.nav || "Slides");
  bar.appendChild(prev);
  bar.appendChild(counter);
  bar.appendChild(next);
  deck.appendChild(bar); // footer of the deck
```

with:

```javascript
  // Position indicator: dots for small decks, a text counter past DOTS_MAX.
  // Both are decorative (aria-hidden); a single sr-only live region announces
  // the position for screen readers in either mode.
  var useDots = slides.length <= DOTS_MAX;
  var dots = [];
  var indicator;
  if (useDots) {
    indicator = document.createElement("div");
    indicator.className = "slideshow-bar__dots";
    indicator.setAttribute("data-slideshow-dots", "");
    indicator.setAttribute("aria-hidden", "true");
    slides.forEach(function () {
      var d = document.createElement("span");
      d.className = "slideshow-bar__dot";
      indicator.appendChild(d);
      dots.push(d);
    });
  } else {
    indicator = document.createElement("span");
    indicator.className = "slideshow-bar__counter";
    indicator.setAttribute("data-slideshow-counter", "");
    indicator.setAttribute("aria-hidden", "true");
  }

  var status = document.createElement("span");
  status.className = "slideshow-bar__status";
  status.setAttribute("data-slideshow-status", "");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");

  var bar = document.createElement("nav");
  bar.className = "slideshow-bar";
  bar.setAttribute("aria-label", i18n.nav || "Slides");
  bar.appendChild(prev);
  bar.appendChild(indicator);
  bar.appendChild(next);
  bar.appendChild(status);
  deck.appendChild(bar); // footer of the deck
```

Then replace the Task 2 `updateIndicator` function — find this exact block (it references the now-deleted `counter` var, so it MUST be replaced too, or execution throws a `ReferenceError`):

```javascript
  function updateIndicator() {
    counter.textContent = (idx + 1) + " / " + slides.length;
  }
```
with:

```javascript
  function posText() {
    return i18n.pos.replace("{n}", idx + 1).replace("{total}", slides.length);
  }
  function updateIndicator() {
    if (useDots) {
      dots.forEach(function (d, k) { d.classList.toggle("is-active", k === idx); });
    } else {
      indicator.textContent = (idx + 1) + " / " + slides.length;
    }
    status.textContent = posText();
  }
```

- [ ] **Step 4: Add the dots / counter / sr-only status CSS**

In `courses/static/courses/css/courses.css`, after the `.slideshow-bar__counter` rule, add:

```css
.slideshow-bar__dots { display: flex; align-items: center; gap: .5rem; }
.slideshow-bar__dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--border-strong);
  transition: width .3s ease, background .3s ease;
}
.slideshow-bar__dot.is-active {
  width: 20px;
  border-radius: 5px;
  background: var(--primary);
}
/* Clip-based sr-only: stays in the a11y/text tree so aria-live announces and
   Playwright can read its text — NOT display:none / visibility:hidden. */
.slideshow-bar__status {
  position: absolute;
  width: 1px; height: 1px;
  padding: 0; margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
```

- [ ] **Step 5: Run the migrated + new tests**

Run: `uv run pytest tests/test_e2e_slideshow.py -m e2e -v`
Expected: `test_position_indicator_dots_and_status` and `test_position_indicator_counter_fallback_over_dots_max` PASS; the four migrated tests PASS against `[data-slideshow-status]`; all other tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/slideshow.js courses/static/courses/css/courses.css tests/test_e2e_slideshow.py
git commit -m "feat(slideshow): progress dots + dedicated sr-only position live region"
```

---

### Task 4: Cross-fade transition

Layer the cross-fade onto the working deck: the incoming slide fades in while the outgoing fades out, the visibility swap defers to a `setTimeout` matched to the CSS duration, reduced motion collapses to an instant swap, and interrupted navigation finalizes the in-flight fade before starting the next.

**Files:**
- Modify: `courses/static/courses/js/slideshow.js` (`show()` + a `finalize`/interrupt guard)
- Modify: `courses/static/courses/css/courses.css` (opacity transition + reduced-motion)
- Test: `tests/test_e2e_slideshow.py` (rapid-navigation interrupt guard)

**Interfaces:**
- Consumes: the Task 2 `show()` state machine + Task 3 indicator.
- Produces: `FADE_MS = 320` (matches the CSS `transition` duration); a `finalizePending()` helper that settles any in-flight fade; reduced-motion via `prefers-reduced-motion` (CSS `transition:none` + JS `delay=0`).

- [ ] **Step 1: Write the failing test (rapid navigation lands on exactly one active slide)**

```python
@pytest.mark.django_db(transaction=True)
def test_rapid_navigation_settles_one_active_slide(page, live_server):
    # Two fast Next clicks (interrupting the first fade) must leave exactly one
    # settled-active slide and the correct position — never two stacked/blank.
    student, path = _seed_slideshow_lesson_3("s_rapid")
    _login(page, live_server, "s_rapid")
    page.goto(f"{live_server.url}{path}")
    nxt = page.get_by_role("button", name="Next")
    nxt.click()
    nxt.click()  # interrupt the first fade
    expect(page.locator(".slide.is-active")).to_have_count(1)
    expect(page.locator("[data-slideshow-status]")).to_have_text("Slide 3 of 3")
    expect(nxt).to_be_disabled()
```

- [ ] **Step 2: Run to verify it fails or is flaky**

Run: `uv run pytest tests/test_e2e_slideshow.py::test_rapid_navigation_settles_one_active_slide -m e2e -v`
Expected: this may PASS with the Task 2 instant swap (no fade to interrupt); it is the regression guard for the fade added below. Proceed to add the fade, then re-run.

- [ ] **Step 3: Add the transition + reduced-motion CSS**

In `courses/static/courses/css/courses.css`, add to the deck-slide rules (scoped to `.slideshow-deck .slide`, NOT the bare `.slide` used elsewhere as `display:contents`):

```css
.slideshow-deck .slide { opacity: 1; transition: opacity 320ms ease; }
@media (prefers-reduced-motion: reduce) {
  .slideshow-deck .slide { transition: none; }
}
```

- [ ] **Step 4: Convert `show()`'s instant swap into a deferred cross-fade**

In `courses/static/courses/js/slideshow.js`, add these inside the IIFE **before** the `show`/`finalizePending` definitions (e.g. just after the `var idx = -1;` line):

```javascript
  var FADE_MS = 320; // MUST match the CSS `.slideshow-deck .slide` transition duration
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)");
  var pending = null; // { out, inn, timer } while a fade is in flight
```

Add a finalize/interrupt helper (place it just above `show`):

```javascript
  function settleHidden(slide) {
    slide.classList.remove("is-active");
    slide.style.opacity = "";
    slide.setAttribute("hidden", "");
  }
  function finalizePending() {
    if (!pending) return;
    clearTimeout(pending.timer);
    if (pending.out && pending.out !== pending.inn) settleHidden(pending.out);
    pending.inn.classList.add("is-active");
    pending.inn.style.opacity = "";
    pending = null;
  }
```

Replace the whole `show` function from Task 2 with the cross-fade version:

```javascript
  function show(n) {
    var target = clamp(n);
    if (idx !== -1 && target === idx) return;   // Step 0: boundary no-op
    finalizePending();                           // settle any in-flight fade first
    var out = slides[idx];                        // old idx (undefined on initial)
    idx = target;
    var inn = slides[idx];
    // Step 1: non-visual sync updates
    updateIndicator();
    prev.disabled = idx === 0;
    next.disabled = idx === slides.length - 1;
    // Step 2: render incoming, focus, reveal (must be rendered before focus)
    inn.removeAttribute("hidden");
    inn.setAttribute("tabindex", "-1");
    inn.scrollTop = 0;
    if (!out) {                                   // initial reveal: no cross-fade
      inn.style.opacity = "";
      inn.classList.add("is-active");
      try { inn.focus({ preventScroll: true }); } catch (e) {}
      onReveal(inn);
      return;                                     // idx already set
    }
    inn.style.opacity = "0";                       // fading-in start
    try { inn.focus({ preventScroll: true }); } catch (e) {}
    onReveal(inn);
    // Step 3: fade — reflow, then animate both; defer the visibility swap.
    void inn.offsetWidth;                          // force reflow so opacity transitions
    inn.classList.add("is-active");
    inn.style.opacity = "1";
    out.style.opacity = "0";
    var delay = reduce && reduce.matches ? 0 : FADE_MS;
    pending = { out: out, inn: inn, timer: null };
    pending.timer = setTimeout(function () {
      settleHidden(out);
      inn.style.opacity = "";
      pending = null;
    }, delay);
  }
```

(The click/keyboard handlers and `show(0)` from Task 2 are unchanged — `show(0)` hits the `!out` initial-reveal branch.)

- [ ] **Step 5: Run the fade + full slideshow suite**

Run: `uv run pytest tests/test_e2e_slideshow.py -m e2e -v`
Expected: `test_rapid_navigation_settles_one_active_slide` PASSES; every other test still PASSES (the fade does not change end-state class/attribute assertions; `.slide.is-active` and `[data-slideshow-status]` settle correctly).

- [ ] **Step 6: Verify the reduced-motion CSS by inspection**

Confirm `courses/static/courses/css/courses.css` contains the `@media (prefers-reduced-motion: reduce) { .slideshow-deck .slide { transition: none; } }` rule and that `FADE_MS` in `slideshow.js` is `320`, matching the `transition: opacity 320ms` declaration (Global Constraint: lockstep).

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/js/slideshow.js courses/static/courses/css/courses.css tests/test_e2e_slideshow.py
git commit -m "feat(slideshow): cross-fade between slides with reduced-motion + interrupt handling"
```

---

## Notes for the executor

- **Run only the slideshow e2e file per task** (`uv run pytest tests/test_e2e_slideshow.py -m e2e -v`); the controller runs the full suite + `ruff check` + `ruff format --check` at Definition-of-Done.
- **CSS token names** (`--surface-raised`, `--border-strong`, `--border-subtle`, `--surface-default`, `--primary`, `--text-primary`, `--space-4/5/6`) are the existing app tokens used by the current `.slideshow-bar` block — if any differ in this codebase, match the surrounding rules rather than inventing names.
- **ES5 only** in `slideshow.js` (`var`, function expressions) to match the file and its lint config.
- **i18n:** after Task 1, if a repo i18n catalog test asserts "no fuzzy / no obsolete `#~`", run it — a stray `#, fuzzy` on the new PL msgstrs makes Django ignore them. Remove any fuzzy flag on the three new entries.
