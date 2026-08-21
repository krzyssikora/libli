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
     `textarea { resize: vertical }` (app.css:166) means a student's own
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

  function enter() {
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
