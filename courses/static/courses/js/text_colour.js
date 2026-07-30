(function () {
  "use strict";

  // Canonical slot table, mirroring courses/colour.py. tests/test_colour_map_drift.py
  // extracts this literal verbatim and compares it to the Python one, so it must stay
  // a single plain array assigned to `var MAP`.
  var MAP = [
    { rgb: [178, 55, 42], slot: "red" },
    { rgb: [234, 138, 130], slot: "red" },
    { rgb: [255, 0, 0], slot: "red" },
    { rgb: [31, 97, 173], slot: "blue" },
    { rgb: [143, 188, 232], slot: "blue" },
    { rgb: [0, 0, 255], slot: "blue" },
    { rgb: [63, 107, 36], slot: "green" },
    { rgb: [159, 191, 123], slot: "green" },
    { rgb: [0, 128, 0], slot: "green" },
    { rgb: [138, 85, 20], slot: "orange" },
    { rgb: [232, 183, 97], slot: "orange" },
    { rgb: [255, 165, 0], slot: "orange" }
  ];

  var SLOTS = ["red", "blue", "green", "orange"];
  var TC_TAGS = { SPAN: 1, B: 1, I: 1, EM: 1, STRONG: 1, U: 1, A: 1 };
  // Applied by Clear, then dropped. Never in MAP -- asserted by the drift test.
  var SENTINEL = "rgb(1, 2, 3)";

  var KEYWORDS = {
    red: [255, 0, 0], blue: [0, 0, 255],
    green: [0, 128, 0], orange: [255, 165, 0]
  };

  function normaliseColour(value) {
    if (!value) return null;
    var text = String(value).trim().toLowerCase();
    if (KEYWORDS[text]) return KEYWORDS[text].slice();
    var hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/.exec(text);
    if (hex) {
      var digits = hex[1];
      if (digits.length === 3) {
        digits = digits[0] + digits[0] + digits[1] + digits[1] + digits[2] + digits[2];
      }
      return [
        parseInt(digits.slice(0, 2), 16),
        parseInt(digits.slice(2, 4), 16),
        parseInt(digits.slice(4, 6), 16)
      ];
    }
    var rgb = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,[^)]*)?\)$/.exec(text);
    if (rgb) {
      var out = [+rgb[1], +rgb[2], +rgb[3]];
      return (out[0] > 255 || out[1] > 255 || out[2] > 255) ? null : out;
    }
    return null;
  }

  function slotFor(value) {
    var triple = normaliseColour(value);
    if (!triple) return null;
    for (var i = 0; i < MAP.length; i++) {
      var m = MAP[i].rgb;
      if (m[0] === triple[0] && m[1] === triple[1] && m[2] === triple[2]) {
        return MAP[i].slot;
      }
    }
    return null;
  }

  function tcClassOf(el) {
    if (!el.classList) return null;
    for (var i = 0; i < SLOTS.length; i++) {
      if (el.classList.contains("tc-" + SLOTS[i])) return SLOTS[i];
    }
    return null;
  }

  function clearTc(el) {
    for (var i = 0; i < SLOTS.length; i++) el.classList.remove("tc-" + SLOTS[i]);
    if (el.getAttribute("class") === "") el.removeAttribute("class");
  }

  // Clear the COLOR LONGHAND, never the style attribute: KaTeX packs height,
  // vertical-align and margin-right into the same attribute, and removing it whole
  // destroys the rendered layout.
  function clearInlineColour(el) {
    el.style.color = "";
    if (el.getAttribute("style") === "") el.removeAttribute("style");
  }

  function wrapChildren(el, slot) {
    var span = document.createElement("span");
    span.className = "tc-" + slot;
    while (el.firstChild) span.appendChild(el.firstChild);
    el.appendChild(span);
    return span;
  }

  // Touches ONLY elements carrying an inline colour. Never touches an element without
  // one -- which is what makes it safe to run over freshly rendered KaTeX, whose output
  // is overwhelmingly colourless spans that a broader pass would flatten.
  //
  // opts.dropUnmapped: author path (true) drops an unmapped colour; render path (false)
  // leaves it exactly as-is, so existing \color{purple} content keeps rendering.
  function mapColours(root, opts) {
    if (!root || !root.querySelectorAll) return false;
    var dropUnmapped = !!(opts && opts.dropUnmapped);
    var changed = false;
    var styled = root.querySelectorAll("[style]");
    var all = [];
    for (var i = 0; i < styled.length; i++) all.push(styled[i]);
    if (root.getAttribute && root.getAttribute("style")) all.push(root);

    for (var j = 0; j < all.length; j++) {
      var el = all[j];
      if (!el.style || !el.style.color) continue;
      var slot = slotFor(el.style.color);
      if (!slot) {
        if (dropUnmapped) { clearInlineColour(el); changed = true; }
        continue;
      }
      changed = true;
      if (el === root) {
        // The root's own classes are never serialised (sync reads innerHTML), so a
        // class here would vanish on save with no sanitiser involved.
        clearInlineColour(el);
        wrapChildren(el, slot);
      } else if (TC_TAGS[el.tagName]) {
        clearTc(el);
        el.classList.add("tc-" + slot);
        clearInlineColour(el);
      } else {
        clearInlineColour(el);
        wrapChildren(el, slot);
      }
    }
    // Unconditional: the collapse also has to fire for CLASS-ONLY markup (a reloaded
    // surface carries tc-* with no inline colour at all), where nothing above sets
    // `changed`. It is idempotent, so running it always is free.
    collapseNested(root);
    return changed;
  }

  // <span class="tc-red"><span class="tc-blue">x</span></span> -> the inner one.
  // "Only rendered content" ignores whitespace-only text nodes, which execCommand
  // emits routinely and which an "only child" predicate would trip over.
  function collapseNested(root) {
    var outers = root.querySelectorAll(
      ".tc-red, .tc-blue, .tc-green, .tc-orange"
    );
    for (var i = 0; i < outers.length; i++) {
      var outer = outers[i];
      var inner = null, extra = false;
      for (var n = outer.firstChild; n; n = n.nextSibling) {
        if (n.nodeType === 3 && !n.nodeValue.trim()) continue;
        if (n.nodeType === 1 && tcClassOf(n) && !inner) { inner = n; continue; }
        extra = true;
      }
      if (inner && !extra) clearTc(outer);           // innermost wins
      // One element may carry two slots via the HTML source view; keep one.
      var slot = tcClassOf(outer);
      if (slot) { clearTc(outer); outer.classList.add("tc-" + slot); }
    }
  }

  // Paste hygiene ONLY. Rule (a) runs before rule (b) and (b) never fires inside a
  // .katex subtree: a .katex wrapper matches (b)'s predicate exactly, so a (b)-first
  // or bottom-up pass would destroy the subtree before (a) could read its annotation.
  function tidyPastedSpans(root) {
    if (!root || !root.querySelectorAll) return;
    // (a) a pasted .katex subtree -> its LaTeX source, re-delimited.
    var katex = root.querySelectorAll(".katex");
    for (var i = katex.length - 1; i >= 0; i--) {
      var node = katex[i];
      if (!node.parentNode) continue;
      var ann = node.querySelector('annotation[encoding="application/x-tex"]');
      var display = node.classList.contains("katex-display") ||
        (node.parentNode.classList &&
         node.parentNode.classList.contains("katex-display"));
      var latex = ann ? ann.textContent : "";
      var text = latex
        ? (display ? "\\[" + latex + "\\]" : "\\(" + latex + "\\)")
        : node.textContent;
      var target = display && node.parentNode.classList &&
        node.parentNode.classList.contains("katex-display")
        ? node.parentNode : node;
      target.parentNode.replaceChild(document.createTextNode(text), target);
    }
    // (b) any other span with no meaningful class and no attribute but class/style.
    var spans = root.querySelectorAll("span");
    for (var j = spans.length - 1; j >= 0; j--) {
      var span = spans[j];
      if (!span.parentNode) continue;
      if (tcClassOf(span)) continue;
      if (span.className && /\bta-(left|center|right)\b/.test(span.className)) continue;
      var onlyClassOrStyle = true;
      for (var k = 0; k < span.attributes.length; k++) {
        var name = span.attributes[k].name;
        if (name !== "class" && name !== "style") onlyClassOrStyle = false;
      }
      if (!onlyClassOrStyle) continue;
      if (span.style && span.style.color) continue;   // mapColours' business
      while (span.firstChild) span.parentNode.insertBefore(span.firstChild, span);
      span.parentNode.removeChild(span);
    }
  }

  function activeSlot(root) {
    var sel = window.getSelection();
    if (!sel || !sel.rangeCount) return null;
    var range = sel.getRangeAt(0);
    if (!root.contains(range.commonAncestorContainer)) return null;
    function slotAt(node) {
      if (node && node.nodeType === 3) node = node.parentNode;
      while (node && node !== root) {
        var slot = tcClassOf(node);
        if (slot) return slot;
        node = node.parentNode;
      }
      return null;
    }
    var start = slotAt(range.startContainer);
    var end = slotAt(range.endContainer);
    return start && start === end ? start : null;
  }

  window.libliColour = {
    MAP: MAP,
    SENTINEL: SENTINEL,
    normaliseColour: normaliseColour,
    slotFor: slotFor,
    mapColours: mapColours,
    tidyPastedSpans: tidyPastedSpans,
    activeSlot: activeSlot
  };
})();
