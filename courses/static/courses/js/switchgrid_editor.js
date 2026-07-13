(function () {
  "use strict";

  function nextIndex(container, selector, attr) {
    var max = -1;
    container.querySelectorAll(selector).forEach(function (el) {
      var v = parseInt(el.getAttribute(attr), 10);
      if (!isNaN(v) && v > max) max = v;
    });
    return max + 1;
  }

  function rewrite(frag, subs) {
    frag.querySelectorAll("*").forEach(function (n) {
      ["name", "data-line-index", "data-cycler-index"].forEach(function (a) {
        if (n.hasAttribute(a)) {
          var v = n.getAttribute(a);
          Object.keys(subs).forEach(function (k) { v = v.split(k).join(subs[k]); });
          n.setAttribute(a, v);
        }
      });
    });
  }

  function onClick(e) {
    var editor = e.target.closest("[data-switchgrid-editor]");
    if (!editor) return;

    if (e.target.closest("[data-add-line]")) {
      var linesWrap = editor.querySelector("[data-lines]");
      var i = nextIndex(linesWrap, "[data-line-row]", "data-line-index");
      var frag = editor.querySelector("template[data-line-template]").content.cloneNode(true);
      rewrite(frag, { "__i__": i });
      linesWrap.appendChild(frag);
      return;
    }
    var addCyc = e.target.closest("[data-add-cycler]");
    if (addCyc) {
      var lineRow = addCyc.closest("[data-line-row]");
      var i2 = lineRow.getAttribute("data-line-index");
      var cycWrap = lineRow.querySelector("[data-cyclers]");
      var j = nextIndex(cycWrap, "[data-cycler-row]", "data-cycler-index");
      var cfrag = editor.querySelector("template[data-cycler-template]").content.cloneNode(true);
      rewrite(cfrag, { "__i__": i2, "__j__": j });
      cycWrap.appendChild(cfrag);
      return;
    }
    var addOpt = e.target.closest("[data-add-option]");
    if (addOpt) {
      var cycRow = addOpt.closest("[data-cycler-row]");
      var lineRow2 = cycRow.closest("[data-line-row]");
      var i3 = lineRow2.getAttribute("data-line-index");
      var j3 = cycRow.getAttribute("data-cycler-index");
      var ofrag = editor.querySelector("template[data-option-template]").content.cloneNode(true);
      // derive the current cycler's real field names for the cloned option row
      rewrite(ofrag, { "__i__": i3, "__j__": j3 });
      var optsWrap = cycRow.querySelector("[data-options]");
      optsWrap.appendChild(ofrag);
      // renumber the answer-radios by DOM position so each radio's value
      // stays equal to its live index (server derives correctness by
      // position among that cycler's options, not by the template's
      // static value)
      var radios = optsWrap.querySelectorAll('input[type="radio"]');
      for (var r = 0; r < radios.length; r++) {
        radios[r].value = r;
      }
    }
  }

  document.addEventListener("click", onClick);
  // exposed as a no-op initializer for symmetry with other enhancers (delegation is global)
  window.libliInitSwitchGridEditors = function () {};
})();
