(function () {
  "use strict";
  var article = document.querySelector("[data-slideshow]");
  if (!article) return;
  var slides = Array.prototype.slice.call(article.querySelectorAll(".slide"));
  if (slides.length <= 1) return; // degenerate guard (belt-and-suspenders)

  var i18n = window.SLIDESHOW_I18N || { prev: "Prev", next: "Next" };
  var idx = 0;

  // Icon buttons use INLINE monochrome currentColor line SVG (matching base.html's
  // inline-icon convention). NOT a sprite <use href="#..."> — the icon sprite
  // (templates/courses/manage/_icon_sprite.html) is included ONLY on the editor/builder
  // pages, NOT on the student taking pages where this control bar lives, so a <use>
  // reference would render blank. NOT unicode glyphs either. The visible <span> label
  // gives the button its accessible name (so page.get_by_role("button", name=...) still
  // matches). Chevron paths: left "M15 6l-6 6 6 6", right "M9 6l6 6-6 6".
  function iconBtn(cls, pathD, label, iconFirst) {
    var b = document.createElement("button");
    b.type = "button"; b.className = cls;
    var svg = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
              'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
              'aria-hidden="true" focusable="false"><path d="' + pathD + '"/></svg>';
    var lbl = document.createElement("span"); lbl.textContent = label;
    if (iconFirst) { b.insertAdjacentHTML("beforeend", svg); b.appendChild(lbl); }
    else { b.appendChild(lbl); b.insertAdjacentHTML("beforeend", svg); }
    return b;
  }

  var bar = document.createElement("nav");
  bar.className = "slideshow-bar";
  bar.setAttribute("aria-label", i18n.nav || "Slides");
  var prev = iconBtn("slideshow-bar__prev", "M15 6l-6 6 6 6", i18n.prev, true);
  var counter = document.createElement("span");
  counter.className = "slideshow-bar__counter";
  counter.setAttribute("data-slideshow-counter", "");
  counter.setAttribute("role", "status");
  counter.setAttribute("aria-live", "polite");
  var next = iconBtn("slideshow-bar__next", "M9 6l6 6-6 6", i18n.next, false);
  bar.appendChild(prev); bar.appendChild(counter); bar.appendChild(next);
  slides[slides.length - 1].after(bar); // after last slide, above trailing Finish/notes

  function show(n) {
    idx = Math.max(0, Math.min(slides.length - 1, n));
    slides.forEach(function (s, k) {
      var active = k === idx;
      s.classList.toggle("is-active", active);
      s.toggleAttribute("hidden", !active);
      if (active) { s.setAttribute("tabindex", "-1"); }
    });
    counter.textContent = (idx + 1) + " / " + slides.length;
    prev.disabled = idx === 0;
    next.disabled = idx === slides.length - 1;
    onReveal(slides[idx]);           // Task 9/10 hooks
    slides[idx].scrollIntoView({ block: "start" });
    try { slides[idx].focus(); } catch (e) {}
  }

  function onReveal(slide) { /* extended in Task 9 (mark-seen) + Task 10 (relayout, Finish) */ }

  prev.addEventListener("click", function () { show(idx - 1); });
  next.addEventListener("click", function () { show(idx + 1); });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    var t = e.target;
    var tag = t && t.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" ||
        (t && t.isContentEditable) || tag === "MATH-FIELD") return; // arrows meaningful in fields
    if (!article.contains(t) && !bar.contains(t)) return;
    e.preventDefault();
    show(idx + (e.key === "ArrowRight" ? 1 : -1));
  });

  show(0); // initial reveal
})();
