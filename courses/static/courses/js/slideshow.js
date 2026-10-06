(function () {
  "use strict";
  var article = document.querySelector("[data-slideshow]");
  if (!article) return;
  var slides = Array.prototype.slice.call(article.querySelectorAll(".slide"));
  if (slides.length <= 1) return; // degenerate guard (belt-and-suspenders)

  var i18n = window.SLIDESHOW_I18N ||
    { prev: "Previous slide", next: "Next slide", nav: "Slides", pos: "Slide {n} of {total}" };
  var idx = -1;
  var DOTS_MAX = 12;
  var FADE_MS = 320; // MUST match the CSS `.slideshow-deck .slide` transition duration
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)");
  var pending = null; // { out, inn, timer } while a fade is in flight

  // Icon buttons use INLINE monochrome currentColor line SVG (matching base.html's
  // inline-icon convention). NOT a sprite <use href="#..."> — the icon sprite
  // (templates/courses/manage/_icon_sprite.html) is included ONLY on the editor/builder
  // pages, NOT on the student taking pages where this control bar lives, so a <use>
  // reference would render blank. NOT unicode glyphs either.
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

  // --- Arrow buttons (re-included here: in the original file these sit below the
  //     `var bar` anchor, inside this replaced region).
  var prev = iconBtn("slideshow-bar__prev", "M15 6l-6 6 6 6", i18n.prev);
  var next = iconBtn("slideshow-bar__next", "M9 6l6 6-6 6", i18n.next);

  // --- Build the deck: move slides into a fixed-height stage; bar is the footer.
  var deck = document.createElement("div");
  deck.className = "slideshow-deck";
  var stage = document.createElement("div");
  // .scroll-y: the stage is a fixed height, so a tall slide is clipped at the
  // bottom — often on whitespace between blocks, which reads as "that's the end of
  // the slide" rather than "there is more". The shaded edge is the missing signal.
  // The stage is the right box to carry it precisely because it does NOT scroll
  // (the .slide inside it does), so the shading stays pinned while content moves
  // under it. data-scroll-y names the LIVE scroller: which slide that is changes on
  // every Prev/Next, so the affordance re-resolves it instead of binding one node.
  stage.className = "slideshow-stage scroll-y";
  stage.setAttribute("data-scroll-y", ".slide.is-active:not([hidden])");
  slides[0].parentNode.insertBefore(deck, slides[0]); // deck takes the slides' spot
  deck.appendChild(stage);
  slides.forEach(function (s) {
    stage.appendChild(s);          // move into the stage
    s.setAttribute("hidden", "");  // all-hidden resting baseline; show(0) reveals slide 0
  });

  // --- Position indicator: dots for small decks, a text counter past DOTS_MAX.
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

  // Quiz: "Finish quiz" takes the Next arrow's place on the last slide. Left below
  // the deck it is below the fold whenever the deck fills the window, and the
  // student presses the unit footer's Next (leaving the quiz) instead. Moving the
  // node keeps quiz.js's confirm + flush submit listener; with JS off the form
  // stays where the template put it.
  var finish = document.querySelector("[data-quiz-finish]"); // quiz only
  if (finish) bar.insertBefore(finish, status);

  // --- Fit the stage to the window: the deck's bar ends just above the sticky
  // unit footer, so a first-time student SEES the Prev/Next + dots without
  // scrolling. CSS cannot (the chrome above the deck varies 325-546px), so the
  // CSS clamp is only the pre-JS / no-JS height. Measured at the page top
  // (document offset, not viewport), so the height does not move as the student
  // scrolls. MIN/MAX mirror the CSS clamp: a short window still floors at 360px.
  var FIT_MIN = 360, FIT_MAX = 900, FIT_GAP = 16;
  var foot = document.querySelector(".unit-foot");
  function fit() {
    var top = stage.getBoundingClientRect().top + window.pageYOffset;
    var avail = document.documentElement.clientHeight - top - FIT_GAP -
      bar.getBoundingClientRect().height - (foot ? foot.getBoundingClientRect().height : 0);
    var h = Math.round(Math.max(FIT_MIN, Math.min(FIT_MAX, avail))) + "px";
    if (stage.style.height !== h) stage.style.height = h; // idempotent: no RO loop
  }

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
  function updateFinish() {
    if (!finish) return;
    var last = idx === slides.length - 1;
    finish.toggleAttribute("hidden", !last);
    next.toggleAttribute("hidden", last);
  }
  function onReveal(slide) {
    markSlideSeen(slide);
    updateFinish();
    window.dispatchEvent(new Event("resize")); // MathLive/GeoGebra/KaTeX re-measure
  }

  // --- show(): state machine. Task 4 layers a deferred cross-fade onto the
  // Task 2 swap; finalizePending() lets rapid navigation interrupt safely.
  function clamp(n) { return Math.max(0, Math.min(slides.length - 1, n)); }
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

  // Arm the stage's edge affordance. base.html loads scroll_affordance.js in the
  // body, BEFORE the {% block extra_js %} that carries this file, so its own
  // init(document) already ran against a document with no deck in it — the stage
  // must be handed over explicitly. wireY is idempotent, so the guard is only for
  // the load-order case where this file somehow runs first and the global init
  // picks the stage up instead.
  if (window.libliInitScrollAffordance) window.libliInitScrollAffordance(stage);

  show(0); // initial reveal (out === undefined → slide 0 settled active)

  // After show(0): the bar's height is final once Finish/arrow visibility is set.
  // The ResizeObserver catches what moves the deck's top after load -- a title
  // wrapping once fonts/KaTeX land, the Tags bar opening -- and is convergent:
  // fit() writes only on change, so its own resize settles in one pass.
  fit();
  window.addEventListener("resize", fit);
  if (window.ResizeObserver) new ResizeObserver(fit).observe(document.body);
})();
