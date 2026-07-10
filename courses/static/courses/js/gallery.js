(function () {
  "use strict";

  var i18n = window.GALLERY_I18N ||
    { prev: "Previous image", next: "Next image", nav: "Gallery", go: "Go to image {n}", pos: "Image {n} of {total}" };
  var DOTS_MAX = 12;
  var FADE_MS = 320; // MUST match the .el--gallery cross-fade transition in courses.css

  function iconBtn(cls, pathD, label) {
    var b = document.createElement("button");
    b.type = "button"; b.className = cls;
    b.setAttribute("aria-label", label);
    b.innerHTML = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
      'aria-hidden="true" focusable="false"><path d="' + pathD + '"/></svg>';
    return b;
  }

  function initOne(container) {
    // Idempotent: the editor's live-preview pane is rebuilt on every fragment swap and
    // re-runs this over the whole pane. Re-entering an already-enhanced gallery would
    // append a second nav bar and re-wrap the figures in a second stage.
    if (container.dataset.galleryReady === "1") return;
    container.dataset.galleryReady = "1";

    var items = Array.prototype.slice.call(container.querySelectorAll(".gallery__item"));
    if (items.length < 2) return; // 0/1 figure: leave the no-JS stack, no bar
    container.classList.add("gallery--js");

    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)");
    var idx = -1;
    var pending = null;

    // Stage overlays the figures; bar is the controls.
    var stage = document.createElement("div");
    stage.className = "gallery__stage";
    items[0].parentNode.insertBefore(stage, items[0]);
    // At rest every item is aria-hidden; show(0) reveals the first. Items stay
    // laid out (CSS: absolute, height auto) so measure() can read their natural
    // height even while invisible.
    items.forEach(function (it) { stage.appendChild(it); it.setAttribute("aria-hidden", "true"); });

    var prev = iconBtn("gallery__prev", "M15 6l-6 6 6 6", i18n.prev);
    var next = iconBtn("gallery__next", "M9 6l6 6-6 6", i18n.next);

    var useDots = items.length <= DOTS_MAX;
    var dots = [];
    var indicator;
    if (useDots) {
      indicator = document.createElement("div");
      indicator.className = "gallery__dots";
      items.forEach(function (_it, k) {
        var d = document.createElement("button");
        d.type = "button"; d.className = "gallery__dot";
        d.setAttribute("aria-label", i18n.go.replace("{n}", k + 1));
        d.addEventListener("click", function () { show(k); });
        indicator.appendChild(d);
        dots.push(d);
      });
    } else {
      indicator = document.createElement("span");
      indicator.className = "gallery__counter";
      indicator.setAttribute("aria-hidden", "true");
    }

    var status = document.createElement("span");
    status.className = "gallery__status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");

    var bar = document.createElement("nav");
    bar.className = "gallery__bar";
    bar.setAttribute("aria-label", i18n.nav);
    bar.appendChild(prev);
    bar.appendChild(indicator);
    bar.appendChild(next);
    bar.appendChild(status);
    container.appendChild(bar);

    function posText() { return i18n.pos.replace("{n}", idx + 1).replace("{total}", items.length); }
    function updateIndicator() {
      if (useDots) {
        dots.forEach(function (d, k) {
          d.classList.toggle("is-active", k === idx);
          if (k === idx) { d.setAttribute("aria-current", "true"); } else { d.removeAttribute("aria-current"); }
        });
      } else {
        indicator.textContent = (idx + 1) + " / " + items.length;
      }
      status.textContent = posText();
    }

    function clamp(n) { return Math.max(0, Math.min(items.length - 1, n)); }
    function settleHidden(it) {
      it.classList.remove("is-active");
      it.style.opacity = "";
      it.setAttribute("aria-hidden", "true");
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
      if (idx !== -1 && target === idx) return;
      finalizePending();
      var out = items[idx];
      idx = target;
      var inn = items[idx];
      updateIndicator();
      prev.disabled = idx === 0;
      prev.setAttribute("aria-disabled", idx === 0 ? "true" : "false");
      next.disabled = idx === items.length - 1;
      next.setAttribute("aria-disabled", idx === items.length - 1 ? "true" : "false");
      inn.removeAttribute("aria-hidden");
      if (!out) {
        inn.style.opacity = "";
        inn.classList.add("is-active");
        return;
      }
      out.setAttribute("aria-hidden", "true");  // AT sees only the incoming slide during the fade
      inn.style.opacity = "0";
      void inn.offsetWidth;
      inn.classList.add("is-active");
      inn.style.opacity = "1";
      out.style.opacity = "0";
      var delay = reduce && reduce.matches ? 0 : FADE_MS;
      pending = { out: out, inn: inn, timer: null };
      pending.timer = setTimeout(function () { settleHidden(out); inn.style.opacity = ""; pending = null; }, delay);
    }

    prev.addEventListener("click", function () { show(idx - 1); });
    next.addEventListener("click", function () { show(idx + 1); });

    container.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      var t = e.target, tag = t && t.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || (t && t.isContentEditable)) return;
      if (!container.contains(t)) return;
      e.preventDefault();
      show(idx + (e.key === "ArrowRight" ? 1 : -1));
    });

    // Stable-frame reservation: reserve the tallest figure + tallest desc so the
    // frame offset is constant across slides. Recompute on resize AND whenever a
    // figure changes size (fonts / KaTeX typeset) via ResizeObserver. Clear the
    // reservation before measuring so we read natural heights, not the reserve.
    var descs = Array.prototype.slice.call(container.querySelectorAll(".gallery__desc"));
    var measureScheduled = false;
    function measure() {
      // Clear the reservations first so we read NATURAL heights, not the reserve.
      stage.style.minHeight = "";
      descs.forEach(function (d) { d.style.minHeight = ""; });
      var maxDesc = 0;
      descs.forEach(function (d) { maxDesc = Math.max(maxDesc, d.offsetHeight); });
      descs.forEach(function (d) { d.style.minHeight = maxDesc + "px"; });
      var maxItem = 0;
      items.forEach(function (it) { maxItem = Math.max(maxItem, it.offsetHeight); });
      stage.style.minHeight = maxItem + "px";
    }
    var ro = window.ResizeObserver ? new ResizeObserver(scheduleMeasure) : null;
    // measure() mutates the same elements the ResizeObserver watches, so run it on
    // the next frame and coalesce bursts — this avoids re-entrant RO firing and the
    // "ResizeObserver loop limit exceeded" console error.
    function scheduleMeasure() {
      if (measureScheduled) return;
      measureScheduled = true;
      window.requestAnimationFrame(function () {
        measureScheduled = false;
        // A preview-pane swap detaches this container but leaves the resize listener
        // bound; stop measuring (and observing) a gallery that is no longer in the DOM.
        if (!container.isConnected) {
          if (ro) ro.disconnect();
          window.removeEventListener("resize", scheduleMeasure);
          return;
        }
        measure();
      });
    }
    if (ro) items.forEach(function (it) { ro.observe(it); });
    window.addEventListener("resize", scheduleMeasure);

    show(0);
    measure();
  }

  // Enhance every gallery under `root` (default: the whole document). Exposed so the
  // editor can re-run it over the live-preview pane after each fragment swap, the same
  // way editor.js re-runs window.libliRenderMath / window.libliEnhanceDnd. Idempotent.
  function initGallery(root) {
    var scope = root || document;
    if (scope.matches && scope.matches("[data-gallery]")) initOne(scope);
    Array.prototype.forEach.call(scope.querySelectorAll("[data-gallery]"), initOne);
  }

  window.libliInitGallery = initGallery;
  initGallery(document);
})();
