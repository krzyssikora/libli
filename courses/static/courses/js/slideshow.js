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
  stage.className = "slideshow-stage";
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
  var finish = document.querySelector("[data-quiz-finish]"); // quiz only
  function updateFinish() {
    if (finish) finish.toggleAttribute("hidden", idx !== slides.length - 1);
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

  show(0); // initial reveal (out === undefined → slide 0 settled active)
})();
