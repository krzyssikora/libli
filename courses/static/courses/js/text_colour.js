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

  // ---- Protected regions: maths spans and {{...}} markers -------------------
  //
  // Colouring inside either is a permanent corruption, not a cosmetic slip:
  //   - maths: sanitize_cell stashes a balanced \(...\) region INCLUDING any injected
  //     markup, then escapes it. Both sanitisers are idempotent, so re-saving never
  //     heals it -- the damage outlives the undo window.
  //   - markers: fillblank.parse runs AFTER sanitize_html, so {{<span>a</span>|b}}
  //     still matches the marker regex and the markup becomes the accepted answer.
  //
  // The marker test runs on EVERY surface, not just marker-bearing fields: apply()
  // receives only `root` and has no signal for which field it is editing, and "{{"
  // occurs zero times in the imported corpus, so the false-refusal cost is nil.
  var MATH_RE = /\\\(|\\\)|\\\[|\\\]/g;
  var MARKER_RE = /\{\{(.*?)\}\}/g;

  // A DOM Range yields (node, offset) pairs, not indices into textContent. This is
  // the mapping step; getting it wrong is how a region test silently passes.
  function textOffsets(root, range) {
    // Handles BOTH container kinds. A selection's Range has TEXT containers, but
    // selectNodeContents(el) yields an ELEMENT container -- and a text-node-only walk
    // returns null for those, which made splitOrClear dead code and let Clear wipe a
    // whole coloured run instead of splitting it.
    var texts = [];
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    var acc = 0, node;
    while ((node = walker.nextNode())) {
      texts.push({ node: node, start: acc });
      acc += node.nodeValue.length;
    }
    function offsetOf(container, offset) {
      var i;
      if (container.nodeType === 3) {
        for (i = 0; i < texts.length; i++) {
          if (texts[i].node === container) return texts[i].start + offset;
        }
        return null;
      }
      // Element container: `offset` counts CHILD NODES, so the text offset is the
      // start of the first text node at or after that child.
      var limit = container.childNodes[offset] || null;
      if (!limit) {
        var last = null;
        for (i = 0; i < texts.length; i++) {
          if (container.contains(texts[i].node)) last = texts[i];
        }
        return last ? last.start + last.node.nodeValue.length : null;
      }
      for (i = 0; i < texts.length; i++) {
        if (texts[i].node === limit || limit.contains(texts[i].node)) {
          return texts[i].start;
        }
      }
      return null;
    }
    var start = offsetOf(range.startContainer, range.startOffset);
    var end = offsetOf(range.endContainer, range.endOffset);
    if (start === null || end === null) return null;
    return [Math.min(start, end), Math.max(start, end)];
  }

  // Returns {regions: [[start, end], ...], ok: bool}. ok=false means a delimiter is
  // unbalanced or unclosed anywhere in the scan root -- apply() then FAILS CLOSED.
  function regions(root) {
    var text = root.textContent || "";
    var out = [], ok = true, open = null, m;
    MATH_RE.lastIndex = 0;
    while ((m = MATH_RE.exec(text))) {
      var isOpen = m[0] === "\\(" || m[0] === "\\[";
      if (isOpen) {
        if (open !== null) { ok = false; break; }
        open = m.index;
      } else {
        if (open === null) { ok = false; break; }
        out.push([open, m.index + m[0].length]);
        open = null;
      }
    }
    if (open !== null) ok = false;
    MARKER_RE.lastIndex = 0;
    while ((m = MARKER_RE.exec(text))) out.push([m.index, m.index + m[0].length]);
    return { regions: out, ok: ok };
  }

  // Four cases, per the spec's table. The enclosing case is ALLOWED only when the
  // region carries no element boundary: foreColor's behaviour across a boundary is
  // recorded as an unknown, and sanitize_cell already round-trips such a region
  // lossily, so a span there is not a gesture the storage layer can support.
  function regionVerdict(root, span) {
    var found = regions(root);
    if (!found.ok) return "refused";
    for (var i = 0; i < found.regions.length; i++) {
      var r = found.regions[i];
      var enclosing = span[0] <= r[0] && span[1] >= r[1];
      var disjoint = span[1] <= r[0] || span[0] >= r[1];
      if (disjoint) continue;
      if (!enclosing) return "refused";
      if (regionCrossesElement(root, r)) return "refused";
    }
    return "ok";
  }

  function regionCrossesElement(root, region) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    var acc = 0, owner = null, node;
    while ((node = walker.nextNode())) {
      var start = acc, end = acc + node.nodeValue.length;
      acc = end;
      if (end <= region[0] || start >= region[1]) continue;
      if (owner === null) owner = node.parentNode;
      else if (owner !== node.parentNode) return true;
    }
    return false;
  }

  function styleWithCss(on) {
    try { document.execCommand("styleWithCSS", false, on); } catch (e) { /* ignore */ }
  }

  function announce(root) {
    var editor = root.closest ? root.closest(".editor") : null;
    var text = editor && editor.getAttribute("data-msg-colour-region");
    if (!text) return;                       // degrade silently, as the conflict path does
    var bar = document.createElement("div");
    bar.className = "op-error";
    bar.setAttribute("data-colour-refusal", "");
    bar.textContent = text;
    editor.prepend(bar);
    setTimeout(function () { bar.remove(); }, 6000);
  }

  function eachTc(el, fn) {
    if (tcClassOf(el)) fn(el);
    var inner = el.querySelectorAll(".tc-red, .tc-blue, .tc-green, .tc-orange");
    for (var i = 0; i < inner.length; i++) fn(inner[i]);
  }

  function apply(root, slot) {
    var sel = window.getSelection();
    if (!sel || !sel.rangeCount) return "refused";
    var range = sel.getRangeAt(0);
    if (!root.contains(range.commonAncestorContainer)) return "refused";
    var span = textOffsets(root, range);
    if (!span) return "refused";
    if (regionVerdict(root, span) === "refused") { announce(root); return "refused"; }

    var value = SENTINEL;
    if (slot) {
      value = null;
      for (var i = 0; i < MAP.length; i++) {
        if (MAP[i].slot === slot) {
          value = "rgb(" + MAP[i].rgb.join(", ") + ")";
          break;
        }
      }
      if (!value) return "refused";   // unknown slot: refuse, never guess a colour
    }
    styleWithCss(true);
    try { document.execCommand("foreColor", false, value); } catch (e) { /* ignore */ }
    styleWithCss(false);   // MUST reset: document-global, and a leaked true breaks bold

    if (slot) {
      mapColours(root, { dropUnmapped: true });
      return "ok";
    }

    // Clear. Stored colour is class-carried, so execCommand cannot split it and the
    // surviving tc-* may be an ANCESTOR (partial selection) or a DESCENDANT (the
    // selection enclosed it). Walk both directions, and split explicitly when the
    // range covers only part of a coloured element.
    var sentinels = root.querySelectorAll('[style*="rgb(1, 2, 3)"]');
    for (var s = 0; s < sentinels.length; s++) {
      var el = sentinels[s];
      eachTc(el, clearTc);                                   // el + descendants
      var up = el.parentNode;
      while (up && up !== root) {
        if (tcClassOf(up)) splitOrClear(root, up, span);
        up = up.parentNode;
      }
      clearInlineColour(el);
    }
    dropAttributelessSpans(root);
    return "ok";
  }

  // If the cleared range covers the whole element, drop its class. Otherwise split it
  // into cleared and still-coloured parts -- execCommand does not do this for
  // class-carried colour, and stripping wholesale would clear text outside the range.
  function splitOrClear(root, el, span) {
    var elRange = document.createRange();
    elRange.selectNodeContents(el);
    var bounds = textOffsets(root, elRange);
    if (!bounds) { clearTc(el); return; }
    if (span[0] <= bounds[0] && span[1] >= bounds[1]) { clearTc(el); return; }
    var slot = tcClassOf(el);
    clearTc(el);
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
    var acc = bounds[0], node, pending = [];
    while ((node = walker.nextNode())) {
      pending.push([node, acc, acc + node.nodeValue.length]);
      acc += node.nodeValue.length;
    }
    for (var i = 0; i < pending.length; i++) {
      var entry = pending[i], text = entry[0], from = entry[1], to = entry[2];
      if (to <= span[0] || from >= span[1]) {
        var keep = document.createElement("span");
        keep.className = "tc-" + slot;
        text.parentNode.insertBefore(keep, text);
        keep.appendChild(text);
      }
    }
  }

  // Narrower than tidyPastedSpans' rule (b): this one unwraps ONLY spans with zero
  // attributes -- the shells left behind after clearing removes a class and a colour.
  // Rule (b) additionally unwraps class/style-only spans and is paste-gated.
  function dropAttributelessSpans(root) {
    var spans = root.querySelectorAll("span");
    for (var i = spans.length - 1; i >= 0; i--) {
      var span = spans[i];
      if (span.attributes.length) continue;
      while (span.firstChild) span.parentNode.insertBefore(span.firstChild, span);
      span.parentNode.removeChild(span);
    }
  }

  window.libliColour = {
    MAP: MAP,
    SENTINEL: SENTINEL,
    normaliseColour: normaliseColour,
    slotFor: slotFor,
    mapColours: mapColours,
    tidyPastedSpans: tidyPastedSpans,
    activeSlot: activeSlot,
    apply: apply,
    regions: regions
  };

  // ---- KaTeX normalisation -------------------------------------------------
  //
  // Two hooks, because one does not cover the other:
  //
  //  * INLINE prose maths goes through window.renderMathInElement. Wrapping it works
  //    only because math.js resolves that global at CALL time.
  //
  //  * DISPLAY maths ([data-katex]) cannot be reached via window.libliRenderMath:
  //    math.js assigns that symbol during its own evaluation (so it does not exist at
  //    our insertion point, and the assignment would clobber a wrapper installed
  //    earlier), and its initial pass calls the LOCAL renderMath. renderOne calls a
  //    bare `katex.render(...)`, resolved at call time on window.katex -- so that is
  //    the hook that actually covers the initial render.
  //
  // The render path never drops an unmapped colour, so existing \color{purple}
  // content keeps rendering exactly as it does today.
  function wrapRenderMathInElement() {
    var original = window.renderMathInElement;
    if (typeof original !== "function") return false;
    if (original.__libliColourWrapped) return true;
    var wrapped = function (element, options) {
      var result = original.apply(this, arguments);
      try { mapColours(element, { dropUnmapped: false }); } catch (e) { /* ignore */ }
      return result;
    };
    wrapped.__libliColourWrapped = true;
    window.renderMathInElement = wrapped;
    return true;
  }

  function wrapKatexRender() {
    if (!window.katex || typeof window.katex.render !== "function") return false;
    if (window.katex.render.__libliColourWrapped) return true;
    var original = window.katex.render;
    var wrapped = function (expression, element, options) {
      var result = original.apply(this, arguments);
      try { mapColours(element, { dropUnmapped: false }); } catch (e) { /* ignore */ }
      return result;
    };
    wrapped.__libliColourWrapped = true;
    window.katex.render = wrapped;
    return true;
  }

  // Defensive: if either global is not defined yet, retry once the document is ready
  // rather than silently no-opping for the whole page.
  // Evaluate BOTH before testing: `!a() || !b()` short-circuits and never calls b()
  // when a() fails -- which is exactly the case on a page that loads katex.min.js but
  // not auto-render.min.js, leaving katex.render unwrapped. The bug is invisible on
  // real pages (which load both) and only bites in isolation.
  var inlineWrapped = wrapRenderMathInElement();
  var renderWrapped = wrapKatexRender();
  if (!inlineWrapped || !renderWrapped) {
    // Note: this retry is dead for a script added AFTER load; it exists for the
    // ordinary defer-in-document-order case.
    document.addEventListener("DOMContentLoaded", function () {
      wrapRenderMathInElement();
      wrapKatexRender();
    });
  }
})();
