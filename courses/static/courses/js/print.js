/* print.js — lesson print lifecycle.
 *
 * A print stylesheet cannot open a closed <details>: the content is hidden by
 * content-visibility on the UA ::details-content pseudo-element, which author
 * CSS cannot reliably override across engines. Adding `open` is the only
 * portable mechanism, so this file exists.
 *
 * Deliberately has NO mode flag. An earlier design used an `entered` boolean to
 * make a double-fire idempotent, but a flag cleared only on leave becomes a
 * trap: if NEITHER leave dispatcher fires, it sticks true and every later print
 * on that page silently sweeps nothing. Idempotence falls out of the data
 * structures instead -- enter only queries :not([open]), so a second enter finds
 * its work done; leave drains the Sets, so a second leave iterates empty ones.
 */
(function () {
  "use strict";

  var opened = new Set();   // panels WE opened -- never ones the student opened
  /* textarea -> its inline style.height BEFORE we touched it. A Map, not a Set:
     `textarea { resize: vertical }` (app.css) means a student's own
     drag-resize lives in that same inline property, so blanking it on the
     leave path would silently undo their resize. Restore exactly what was
     there -- usually "", sometimes their height. */
  var stamped = new Map();

  /* A textarea's value is not layout, so it reads correctly through a closed
     <details>. This is the only way to find a draft the student typed and then
     closed the panel on: the native toggle does not clear the textarea (only
     the Cancel path does, notes.js:230). */
  function hasTypedDraft(panel) {
    var inputs = panel.querySelectorAll(".note-composer__input");
    for (var i = 0; i < inputs.length; i++) {
      if (inputs[i].value.trim() !== "") return true;
    }
    return false;
  }

  function carriesNoteContent(panel) {
    return (
      panel.querySelector(".note-card, .note-composer--edit, .note-delete-confirm") !==
        null || hasTypedDraft(panel)
    );
  }

  /* "Surviving" = the composers the print CSS spares. Emphatically NOT every
     .note-composer__input: that reaches note-less panels the sweep never opens,
     which are still under content-visibility:hidden, so scrollHeight reads 0 and
     we would stamp height:0px across the whole lesson. */
  function survivingInputs(root) {
    var out = [];
    var forms = root.querySelectorAll(".note-composer");
    for (var i = 0; i < forms.length; i++) {
      var f = forms[i];
      var spared =
        f.classList.contains("note-composer--edit") ||
        f.classList.contains("note-composer--has-draft") ||
        f.querySelector(".note-composer__error") !== null;
      if (!spared) continue;
      var ta = f.querySelector(".note-composer__input");
      if (ta) out.push(ta);
    }
    return out;
  }

  /* Re-derived on EVERY enter, never only added: the mark is value-based and so
     runs even where the height stamp is skipped, so it is not covered by the
     stamped Set. A stale mark on a since-emptied composer would both spare it
     from the print hide and satisfy the empty-pop :has(), printing an empty
     bordered box on a note-less block. */
  function markDrafts() {
    var forms = document.querySelectorAll(".note-composer");
    for (var i = 0; i < forms.length; i++) {
      var ta = forms[i].querySelector(".note-composer__input");
      var has = ta && ta.value.trim() !== "";
      forms[i].classList.toggle("note-composer--has-draft", !!has);
    }
  }

  /* A textarea's intrinsic block size comes from `rows` (3 here), so height:auto
     resolves to three rows with the rest scrolled out of view. Stamping the
     measured scrollHeight is the mechanism that works on every engine;
     field-sizing:content in the CSS is Chromium-only progressive enhancement.
     Measured under the SCREEN cascade, which is wider on paper than the 15rem
     floating pop -- so the stamp is over-tall, never short. Over-tall prints
     trailing whitespace; short would clip the student's words. */
  function stampHeights() {
    var inputs = survivingInputs(document);
    for (var i = 0; i < inputs.length; i++) {
      var ta = inputs[i];
      var h = ta.scrollHeight;
      if (!h) {
        /* Inside a [hidden] deck slide, layout is skipped and scrollHeight is 0.
           Un-hide the ancestor just long enough to measure, synchronously, so
           nothing the user or the print snapshot can see is affected. */
        var slide = ta.closest(".slide[hidden]");
        if (slide) {
          slide.removeAttribute("hidden");
          h = ta.scrollHeight;
          slide.setAttribute("hidden", "");
        }
      }
      if (h) {
        if (!stamped.has(ta)) stamped.set(ta, ta.style.height);
        ta.style.height = h + "px";
      }
    }
  }

  /* Wide display maths. KaTeX cannot line-break a display, and paper cannot
     scroll, so a formula wider than the printed column was clipped -- equation
     numbers first, since #390 puts them after the formula. The print CSS
     shrinks such a display with
       font-size: min(1em, (100vw - inset) / width-in-em)
     on its .katex-html. In print `vw` is the printed content width (the page
     box minus the @page margins) whatever the screen was, and the lesson
     spans it (no side padding in print); `inset` is the room everything between the lesson's
     content box and the display takes (a deck slide's padding, a callout, a
     tab panel...), measured here from the screen layout. Every KaTeX length is
     in em, so the width in em is nearly a constant of the formula (see the
     small-size correction in fitWideMaths). min() keeps every display that fits at 1em, exactly as before.

     Deliberately NOT a container query (`100cqi`): `container-type` brings
     style containment, which scopes KaTeX's `katexEqnNo` counter to each
     display, and an align numbered (4)(5)(6) printed as (1)(1)(1).

     A display inside a closed tab, a hidden slide or a before/after panel is
     unrendered on screen (`[hidden]`) yet printed. So the width is measured on
     a CLONE inside the lesson -- wrapped in the element's own classes, so
     element-scoped rules such as `.el--math .mk` still apply -- and the inset
     of an unrendered display is its nearest rendered ancestor's plus the
     padding, border and margin of the unrendered boxes in between. The clones
     come after every real display, so their equation numbers can only be
     wider than the originals: an over-shrink, never a clip.

     Only a display laid out at its container's width is flagged: in a
     shrink-to-fit box (a drag chip, a choice label, a table cell) or a
     two-column layout the screen inset says nothing about the printed one, so
     those print as before. `inline` (auto-render wraps every display in a bare
     <span>, and a block inside an inline breaks out to the full width) and
     `contents` (a single-slide lesson's .slide) are box-less for this. */
  var FLOW = { block: 1, "flow-root": 1, "list-item": 1, inline: 1, contents: 1 };
  var A4_COLUMN_PX = (160 * 96) / 25.4; // 210mm minus the 25mm @page sides
  var BOX = ["paddingLeft", "paddingRight", "borderLeftWidth", "borderRightWidth",
             "marginLeft", "marginRight"];

  /* The lesson <article>, or null when some box on the way up is neither in
     plain block flow nor merely [hidden]. */
  function fitRoot(display) {
    for (var el = display; el; el = el.parentElement) {
      if (el.classList.contains("lesson")) return el;
      var cs = getComputedStyle(el);
      var shown = FLOW[cs.display] === 1 || (cs.display === "none" && el.hidden);
      if (!shown || cs.float !== "none") return null;
    }
    return null;
  }

  function contentWidth(el) {
    var cs = getComputedStyle(el);
    return el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  }

  function horizontalInset(display, lesson) {
    var extra = 0;
    var el = display;
    while (el !== lesson && el.getBoundingClientRect().width === 0) {
      var cs = getComputedStyle(el);
      BOX.forEach(function (p) {
        extra += parseFloat(cs[p]) || 0;
      });
      el = el.parentElement;
    }
    var width = el === lesson ? contentWidth(lesson) : el.getBoundingClientRect().width;
    return contentWidth(lesson) - width + extra;
  }

  function fitWideMaths() {
    var displays = document.querySelectorAll(".lesson [data-element-id] .katex-display");
    var host = document.createElement("div");
    host.setAttribute("aria-hidden", "true");
    host.style.cssText =
      "position:absolute;left:0;top:0;visibility:hidden;pointer-events:none;";
    var found = [];
    var lesson = null;
    for (var i = 0; i < displays.length; i++) {
      var kx = displays[i].querySelector(":scope > .katex");
      var root = kx && fitRoot(displays[i]);
      if (!root) continue;
      lesson = root;
      var el = displays[i].closest(".el");
      var wrap = document.createElement("div");
      wrap.className = el ? el.className : "";
      wrap.style.cssText = "width:max-content;margin:0;padding:0;border:0;";
      var box = document.createElement("div");
      box.className = "katex-display";
      box.style.cssText = "width:max-content;margin:0;padding:0;";
      box.appendChild(kx.cloneNode(true));
      wrap.appendChild(box);
      host.appendChild(wrap);
      found.push({ display: displays[i], box: box, inset: horizontalInset(displays[i], root) });
    }
    if (!found.length) return;
    lesson.appendChild(host);
    found.forEach(function (f) {
      f.katex = f.box.firstElementChild;
      f.html = f.katex.querySelector(":scope > .katex-html");
      f.fs = parseFloat(getComputedStyle(f.katex).fontSize);
      f.em = f.katex.getBoundingClientRect().width / f.fs;
      f.low = f.fs;
    });
    /* The width in em is NOT quite constant at small sizes: glyph advances
       round (Linux Chromium measured +2.3% at half size, enough to push the
       equation numbers off the page) and KaTeX's 1px rule minimums do not
       scale. So re-measure the clone at the size it will likely print at,
       predicted for the narrowest common column (A4: 160mm), and just below
       it, keeping the largest width per em: an over-shrink, never a clip.
       Repeat while a wider measurement pushes the size below what was
       sampled. Wider paper prints larger, where the width in em is no worse. */
    for (var pass = 0; pass < 6; pass++) {
      var todo = found.filter(function (f) {
        f.size = (A4_COLUMN_PX - Math.max(0, f.inset) - 2) / f.em;
        return f.em > 0 && f.size < f.low;
      });
      if (!todo.length) break;
      [1, 0.97].forEach(function (step) {
        todo.forEach(function (f) {
          f.html.style.fontSize = (f.size * step) / f.fs + "em";
        });
        todo.forEach(function (f) {
          var w = f.katex.getBoundingClientRect().width / (f.size * step);
          if (w > f.em) f.em = w;
        });
      });
      todo.forEach(function (f) {
        f.low = f.size * 0.97;
      });
    }
    host.remove();
    found.forEach(function (f) {
      if (!(f.em > 0)) return;
      f.display.style.setProperty("--print-fit-em", f.em.toFixed(4));
      f.display.style.setProperty("--print-fit-inset", Math.max(0, f.inset).toFixed(1) + "px");
      f.display.setAttribute("data-print-fit", "");
    });
  }

  function unfitWideMaths() {
    var fitted = document.querySelectorAll(".katex-display[data-print-fit]");
    for (var i = 0; i < fitted.length; i++) {
      fitted[i].removeAttribute("data-print-fit");
      fitted[i].style.removeProperty("--print-fit-em");
      fitted[i].style.removeProperty("--print-fit-inset");
    }
  }

  function enter() {
    /* Never let a measuring failure cost the notes sweep below. */
    try {
      fitWideMaths();
    } catch (e) {
      /* the maths prints as before: clipped, not lost */
    }
    var panels = document.querySelectorAll(".block-notes__panel:not([open])");
    for (var i = 0; i < panels.length; i++) {
      if (carriesNoteContent(panels[i])) {
        panels[i].open = true;
        opened.add(panels[i]);
      }
    }
    var un = document.querySelector(".unanchored-notes > details:not([open])");
    if (un) {
      un.open = true;
      opened.add(un);
    }
    /* Strictly after opening: a textarea inside a still-closed <details> is
       under content-visibility:hidden and measures 0. */
    markDrafts();
    stampHeights();
  }

  function leave() {
    unfitWideMaths();
    opened.forEach(function (el) {
      /* setupClamp (notes.js:97) runs from the capture-phase toggle handler and
         leaves .note-card__body--clamp plus injected .note-card__more buttons in
         the LIVE dom once the panel closes. Only the panels we opened: one the
         student opened was clamped by their own gesture. Every removal is a
         no-op when absent -- a throw here would abort the restore half-done. */
      var clamped = el.querySelectorAll(".note-card__body--clamp");
      for (var i = 0; i < clamped.length; i++) {
        clamped[i].classList.remove("note-card__body--clamp");
      }
      var more = el.querySelectorAll(".note-card__more");
      for (var j = 0; j < more.length; j++) more[j].remove();
      el.removeAttribute("open");
    });
    opened.clear();

    stamped.forEach(function (previous, ta) {
      ta.style.height = previous;
    });
    stamped.clear();

    var marked = document.querySelectorAll(".note-composer--has-draft");
    for (var k = 0; k < marked.length; k++) {
      marked[k].classList.remove("note-composer--has-draft");
    }
  }

  var btn = document.querySelector("[data-print-lesson]");
  if (btn) {
    btn.addEventListener("click", function () {
      window.print();
    });
  }

  /* Ctrl+P must work too -- most people will never find the button. */
  window.addEventListener("beforeprint", enter);
  window.addEventListener("afterprint", leave);

  /* Safari fires the above unreliably; the media query is the more dependable
     signal there. Routed on e.matches so a leave is never mistaken for an enter. */
  var mql = window.matchMedia("print");
  var onChange = function (e) {
    if (e.matches) enter();
    else leave();
  };
  if (mql.addEventListener) mql.addEventListener("change", onChange);
  else if (mql.addListener) mql.addListener(onChange);
})();
