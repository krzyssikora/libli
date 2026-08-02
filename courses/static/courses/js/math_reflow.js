// Rejoins math spans that the rich-text editor split across <div>/<br> boundaries,
// so KaTeX's auto-render — which only matches inside a SINGLE text node — can see
// them. Installs pre-hooks on the same two globals text_colour.js post-hooks.
//
// Install runs exactly once, with no deferred retry. text_colour.js retries its own
// installs when a global was missing; copying that here would be a bug, because
// marker properties do not propagate through another module's wrapper, so a retry
// would wrap an already-wrapped chain and reflow twice per call. This module loads
// after katex.min.js and auto-render.min.js in document order, so one attempt is
// enough. The marker below is a double-include guard, not a retry enabler, and it
// lives on window rather than on either wrapped function for the same reason.
(function () {
  "use strict";

  // Verbatim copy of auto-render's defaults, IN ITS ORDER (first match wins is
  // load-bearing). Pinned against the vendored file by tests/test_math_reflow_defaults.py.
  var DEFAULT_DELIMITERS = [
    { left: "$$", right: "$$", display: true },
    { left: "\\(", right: "\\)", display: false },
    { left: "\\begin{equation}", right: "\\end{equation}", display: true },
    { left: "\\begin{align}", right: "\\end{align}", display: true },
    { left: "\\begin{alignat}", right: "\\end{alignat}", display: true },
    { left: "\\begin{gather}", right: "\\end{gather}", display: true },
    { left: "\\begin{CD}", right: "\\end{CD}", display: true },
    { left: "\\[", right: "\\]", display: true }
  ];

  // auto-render's own default ignore list, plus four this module adds:
  //  * the RTE surface — text_toolbar.js sync() writes its innerHTML back into the
  //    POSTed textarea, so a DOM mutation there is a DATA mutation. Scoped with
  //    :not([contenteditable="false"]) because a false value is not editable.
  //  * .katex — KaTeX's output holds the original TeX in a MathML annotation.
  //  * .katex-error — NOT nested inside .katex; holds raw TeX with throwOnError:false.
  //  * math/annotation — defence in depth if KaTeX's output mode ever changes.
  var IGNORE_SELECTOR =
    "script,noscript,style,textarea,pre,code,option," +
    '[contenteditable]:not([contenteditable="false"]),' +
    ".katex,.katex-error,math,annotation";

  function isIgnored(node, extraSelector) {
    if (!node || node.nodeType !== 1) return false;
    if (node.matches && node.matches(IGNORE_SELECTOR)) return true;
    return !!(extraSelector && node.matches && node.matches(extraSelector));
  }

  // Caller-supplied ignoredTags/ignoredClasses are UNIONED into the fixed list.
  // Ignoring more than the renderer never changes what renders; ignoring less
  // would let the reflow fold away wrappers in a subtree the renderer skips.
  function extraIgnoreSelector(options) {
    var parts = [];
    var i;
    if (options && options.ignoredTags) {
      for (i = 0; i < options.ignoredTags.length; i++) {
        parts.push(String(options.ignoredTags[i]));
      }
    }
    if (options && options.ignoredClasses) {
      for (i = 0; i < options.ignoredClasses.length; i++) {
        parts.push("." + String(options.ignoredClasses[i]));
      }
    }
    return parts.length ? parts.join(",") : null;
  }

  // Post-order: every descendant is processed before its parent may fold it away,
  // and a parent classifies its children on their POST-processing state.
  function walk(node, extraSelector, visit) {
    var children = [].slice.call(node.childNodes);  // snapshot: visit() mutates
    for (var i = 0; i < children.length; i++) {
      var child = children[i];
      if (child.nodeType !== 1) continue;
      if (isIgnored(child, extraSelector)) continue;
      walk(child, extraSelector, visit);
    }
    try { visit(node); } catch (e) { /* per-element atomicity; see the spec */ }
  }

  // ---- scan: a faithful port of auto-render's splitAtDelimiters ---------------

  // Port of findEndOfMath: a backslash SKIPS the following character (so an escaped
  // \] is not a closer), and a closer is only accepted at brace depth <= 0.
  function findEndOfMath(delim, text, startIndex) {
    var index = startIndex;
    var braceLevel = 0;
    var delimLength = delim.length;
    while (index < text.length) {
      var ch = text[index];
      if (braceLevel <= 0 && text.slice(index, index + delimLength) === delim) {
        return index;
      }
      if (ch === "\\") index++;
      else if (ch === "{") braceLevel++;
      else if (ch === "}") braceLevel--;
      index++;
    }
    return -1;
  }

  // Openings: left to right, first delimiter in the CALLER'S ARRAY ORDER that
  // matches at this position wins. No escape handling — auto-render does none.
  // An unclosed opener stops the scan dead, exactly as auto-render's loop breaks.
  function findSpans(text, delimiters) {
    var spans = [];
    var pos = 0;
    while (pos < text.length) {
      var chosen = null;
      for (var i = 0; i < delimiters.length; i++) {
        if (text.startsWith(delimiters[i].left, pos)) { chosen = delimiters[i]; break; }
      }
      if (!chosen) { pos++; continue; }
      var end = findEndOfMath(chosen.right, text, pos + chosen.left.length);
      if (end === -1) break;
      spans.push({ start: pos, end: end + chosen.right.length, delim: chosen });
      pos = end + chosen.right.length;
    }
    return spans;
  }

  function delimitersFor(options) {
    var given = options && options.delimiters;
    return (given && given.length && typeof given[0] === "object")
      ? given : DEFAULT_DELIMITERS;
  }

  // ---- mergeable / barrier ---------------------------------------------------

  // "No effective attributes" = none, or only an EMPTY class and/or style. nh3
  // emits class="" on div/p when every class value is rejected, which is what a
  // pasted formula carries on every line; treating that as attributed would make
  // the feature a no-op on the dominant authoring path.
  function noEffectiveAttributes(el) {
    for (var i = 0; i < el.attributes.length; i++) {
      var attr = el.attributes[i];
      if ((attr.name === "class" || attr.name === "style") && attr.value === "") continue;
      return false;
    }
    return true;
  }

  function isBareBr(node) {
    return node.nodeType === 1 && node.tagName === "BR" && noEffectiveAttributes(node);
  }

  // extraSelector must reach CLASSIFICATION, not just descent: walk() refusing to
  // descend into an extra-ignored child does not stop mergeChildren from folding
  // that child away, which is exactly what the union exists to prevent.
  function isMergeableBlock(node, extraSelector) {
    if (node.nodeType !== 1) return false;
    if (isIgnored(node, extraSelector)) return false;
    if (node.tagName !== "DIV" && node.tagName !== "P") return false;
    if (!noEffectiveAttributes(node)) return false;
    for (var i = 0; i < node.childNodes.length; i++) {
      var child = node.childNodes[i];
      if (child.nodeType === 3) continue;
      if (isBareBr(child)) continue;
      return false;
    }
    return true;
  }

  function isMergeable(node, extraSelector) {
    if (node.nodeType === 3) return true;
    if (isIgnored(node, extraSelector)) return false;
    return isBareBr(node) || isMergeableBlock(node, extraSelector);
  }

  // ---- run text + offset->child map ------------------------------------------

  // The collapse is applied DURING the build so the map stays intact: one surviving
  // newline can come from three children at once, and a post-hoc regex collapse
  // would give every later span a wrong covered range.
  //
  // `leaf` tracks, per character, the actual DOM Text node it came from — or null for
  // a manufactured (synthetic-boundary or authored-<br>) newline. Rule 4 keys off
  // `leaf`, not `map`: `map` only identifies the covered RUN CHILD, but a mergeable
  // div/p can itself hold two real text nodes split by an authored <br>, so comparing
  // `map` alone wrongly treats a span crossing that internal <br> as "already inside
  // one text node" — the exact granularity KaTeX's own auto-render uses, since it
  // matches only within a single text node's .data.
  function buildRun(children) {
    var text = "";
    var map = [];          // map[i] = index into `children` for text[i]
    var synthetic = [];    // synthetic[i] = true when text[i] is a manufactured \n
    var leaf = [];         // leaf[i] = the DOM Text node text[i] came from, or null

    function pushChar(ch, childIndex, isSynthetic, leafNode) {
      text += ch;
      map.push(childIndex);
      synthetic.push(!!isSynthetic);
      leaf.push(leafNode || null);
    }

    function pushText(str, childIndex, leafNode) {
      for (var i = 0; i < str.length; i++) pushChar(str[i], childIndex, false, leafNode);
    }

    function pushBoundary(childIndex) {
      if (!text.length) return;                                  // never lead the run
      if (text.charAt(text.length - 1) === "\n") return;         // collapse
      pushChar("\n", childIndex, true, null);
    }

    function pushBlockText(node, childIndex) {
      for (var i = 0; i < node.childNodes.length; i++) {
        var child = node.childNodes[i];
        if (child.nodeType === 3) pushText(child.data, childIndex, child);
        else if (isBareBr(child)) {
          if (text.length && text.charAt(text.length - 1) !== "\n") {
            pushChar("\n", childIndex, false, null);   // an AUTHORED break, not synthetic
          }
        }
      }
    }

    for (var i = 0; i < children.length; i++) {
      var node = children[i];
      if (node.nodeType === 3) {
        // Whitespace-only text nodes contribute nothing, so hand-written test
        // markup with indentation behaves like nh3 output, which carries none.
        if (/\S/.test(node.data)) pushText(node.data, i, node);
      } else if (isBareBr(node)) {
        if (text.length && text.charAt(text.length - 1) !== "\n") {
          pushChar("\n", i, false, null);
        }
      } else {
        pushBoundary(i);
        pushBlockText(node, i);
        pushBoundary(i);
      }
    }
    while (text.length && text.charAt(text.length - 1) === "\n") {
      text = text.slice(0, -1); map.pop(); synthetic.pop(); leaf.pop();
    }
    return { text: text, map: map, synthetic: synthetic, leaf: leaf };
  }

  // ---- phase 1 ---------------------------------------------------------------

  function textFragment(doc, run, from, to) {
    // Drops synthetic newlines; keeps authored ones as <br> elements, because a \n
    // character outside a math span is HTML whitespace and collapses to a space.
    //
    // FIX (round 1): a "covered but not spanned" range can contain a \n that is
    // NEITHER synthetic NOR a still-live authored <br> element — it can be a real
    // newline already sitting inside an existing Text node, put there by an EARLIER,
    // NESTED mergeChildren call in this same walk (post-order visits a child block
    // before its parent, so a span entirely inside one block is merged there first).
    // `run.leaf[i]` is set exactly for such a character. Rebuilding it as a fresh
    // <br> element here would tear apart a merge that already happened one level
    // down and was already correct — measured against
    // <div>\(x<br>y\) prose \[a</div><div>b\]</div>: the intra-div \(x<br>y\) merges
    // correctly INSIDE the div on this same pass, but the outer merge of the
    // \[a…b\] span (which covers the whole div as its "covered" range) used to
    // re-split that already-good text node back into text/<br>/text, so pass 1
    // differed from pass 2. Only a \n with leaf === null — a manufactured boundary
    // or a genuine, not-yet-processed <br> element — is a candidate for conversion.
    var nodes = [];
    var buffer = "";
    for (var i = from; i < to; i++) {
      var ch = run.text.charAt(i);
      if (ch === "\n" && !run.leaf[i]) {
        if (run.synthetic[i]) continue;
        if (buffer) { nodes.push(doc.createTextNode(buffer)); buffer = ""; }
        nodes.push(doc.createElement("br"));
        continue;
      }
      buffer += ch;
    }
    if (buffer) nodes.push(doc.createTextNode(buffer));
    return nodes;
  }

  function mergeChildren(element, options, extraSelector) {
    var doc = element.ownerDocument || document;
    var children = [].slice.call(element.childNodes);
    var runs = [];
    var current = [];
    var i;
    for (i = 0; i < children.length; i++) {
      if (isMergeable(children[i], extraSelector)) current.push(i);
      else { if (current.length) runs.push(current); current = []; }
    }
    if (current.length) runs.push(current);

    for (var r = runs.length - 1; r >= 0; r--) {
      var indices = runs[r];
      var nodes = [];
      for (i = 0; i < indices.length; i++) nodes.push(children[indices[i]]);
      var run = buildRun(nodes);
      var spans = findSpans(run.text, delimitersFor(options));

      // Rule 4: a span is skipped only when it lies wholly inside a single existing
      // TEXT NODE — the granularity auto-render itself uses — not merely inside a
      // single run CHILD. A mergeable div/p can hold two real text nodes split by an
      // authored <br>, and a span crossing that internal <br> must be rewritten on
      // the FIRST pass so pass 1 already produces pass 2's output, not just self-heal
      // by a later idempotent call.
      //
      // MEASURED discriminating case (comparing `map`, i.e. run-child index, instead
      // of `leaf`, i.e. text-node identity, is non-idempotent HERE specifically):
      // <div>c<br>z$$x</div><div>$$c<br><br>$$x<br> x$$c</div> — with `map`-based rule
      // 4 and the leaf-aware textFragment fix both otherwise in place, pass 1 leaves
      // `$$x<br> x$$c` with a live <br>; pass 2 gives `$$x\n x$$c`. Fuzzed at 500
      // structured random documents: map-based rule 4 alone (textFragment fixed) was
      // non-idempotent on 14/500 shapes; leaf-based rule 4 fixed it on all of them.
      // NOTE: <div>\(x<br>y\) prose \[a</div><div>b\]</div> — the fixture that
      // motivated the textFragment fix below — does NOT discriminate rule 4 itself:
      // map and leaf agree at every call site that fixture exercises, because the
      // <br> there splits a span within one element's OWN direct children, where
      // map already distinguishes them regardless of leaf. Do not cite that fixture
      // as evidence for THIS rule.
      var planned = [];
      for (i = 0; i < spans.length; i++) {
        var startLeaf = run.leaf[spans[i].start];
        var endLeaf = run.leaf[spans[i].end - 1];
        if (startLeaf && startLeaf === endLeaf) continue;
        var first = run.map[spans[i].start];
        var last = run.map[spans[i].end - 1];
        planned.push({ span: spans[i], first: first, last: last });
      }
      if (!planned.length) continue;

      // Covered ranges may OVERLAP (a child can hold the end of one span and the
      // start of the next), so coalesce into maximal disjoint replacement groups.
      var groups = [];
      for (i = 0; i < planned.length; i++) {
        var g = groups.length ? groups[groups.length - 1] : null;
        if (g && planned[i].first <= g.last) {
          g.last = Math.max(g.last, planned[i].last);
          g.spans.push(planned[i].span);
        } else {
          groups.push({ first: planned[i].first, last: planned[i].last,
                        spans: [planned[i].span] });
        }
      }

      for (var gi = groups.length - 1; gi >= 0; gi--) {
        var group = groups[gi];
        var startOffset = run.text.length, endOffset = 0;
        for (i = 0; i < run.map.length; i++) {
          if (run.map[i] >= group.first && run.map[i] <= group.last) {
            if (i < startOffset) startOffset = i;
            if (i + 1 > endOffset) endOffset = i + 1;
          }
        }
        var replacement = [];
        var cursor = startOffset;
        for (i = 0; i < group.spans.length; i++) {
          var span = group.spans[i];
          replacement = replacement.concat(textFragment(doc, run, cursor, span.start));
          replacement.push(doc.createTextNode(run.text.slice(span.start, span.end)));
          cursor = span.end;
        }
        replacement = replacement.concat(textFragment(doc, run, cursor, endOffset));

        // MUST index `nodes` (the run), NOT `children` (all of the element's
        // children). buildRun pushes childIndex from its own loop over `nodes`, so
        // run.map values are RUN-LOCAL. Indexing `children` with them diverges the
        // moment a run does not start at child 0 — measured, that destroys author
        // content: <span>hi</span><div>\[a</div><div>b\]</div> came out as
        // "\[a\nb\]<div>b\]</div>", losing the <span> and leaving a stale <div>.
        // A heading or an image above a split display block is exactly that shape.
        var anchor = nodes[group.first];
        for (i = 0; i < replacement.length; i++) {
          element.insertBefore(replacement[i], anchor);
        }
        for (i = group.first; i <= group.last; i++) {
          if (nodes[i] && nodes[i].parentNode === element) {
            element.removeChild(nodes[i]);
          }
        }
      }
    }
  }

  // ---- phase 1b ---------------------------------------------------------------

  // Matches courses/sanitize.py's _BR: case-insensitive, optional whitespace,
  // optional slash. Enumerating only <br> and <br/> would miss <br /> and <BR>,
  // and that miss would be invisible — the corpus count for this shape is 0.
  var LITERAL_BR = /<br\s*\/?>/gi;

  // Separate full pass over the same walk, run after phase 1 completes for the
  // entire subtree. sanitize_cell flattens cell content at save, so a table
  // cell's math span already lies inside a single text node — a rule-4 SKIP in
  // mergeChildren, never a rule-5 rewrite target. Hanging this off the rule-5
  // path would ship a phase 1b that never fires on any cell.
  function phase1b(element, options) {
    var delimiters = delimitersFor(options);
    for (var i = 0; i < element.childNodes.length; i++) {
      var node = element.childNodes[i];
      if (node.nodeType !== 3) continue;
      var spans = findSpans(node.data, delimiters);
      if (!spans.length) continue;
      var out = "";
      var cursor = 0;
      for (var s = 0; s < spans.length; s++) {
        out += node.data.slice(cursor, spans[s].start);
        out += node.data
          .slice(spans[s].start, spans[s].end)
          .replace(LITERAL_BR, "\n");
        cursor = spans[s].end;
      }
      out += node.data.slice(cursor);
      if (out !== node.data) node.data = out;
    }
  }

  // ---- phase 2 -----------------------------------------------------------

  // Ten EXACT literals, closing brace included. Not ten names, and not a prefix
  // match: \begin{align} would prefix-match \begin{aligned}, which works in both
  // modes, and promoting it would convert correct inline math to a display block.
  var DISPLAY_ONLY_ENVS = [
    "\\begin{align}", "\\begin{align*}", "\\begin{alignat}", "\\begin{alignat*}",
    "\\begin{gather}", "\\begin{gather*}", "\\begin{equation}", "\\begin{equation*}",
    "\\begin{CD}", "\\begin{split}"
  ];

  function containsDisplayOnlyEnv(body) {
    for (var i = 0; i < DISPLAY_ONLY_ENVS.length; i++) {
      if (body.indexOf(DISPLAY_ONLY_ENVS[i]) !== -1) return true;
    }
    return false;
  }

  // Separate full pass over the same walk, run after phase 1 and phase 1b have
  // completed for the entire subtree: promote-then-merge would leave a split
  // \(\begin{align*}…\end{align*}\) unpromoted, because it is not yet inside a
  // single text node. Operates per text node, not per run: rule 5's output is
  // several adjacent text nodes, and a promotion candidate never spans them (a
  // span that spanned nodes would already have been merged).
  function phase2(element, options) {
    var delimiters = delimitersFor(options);
    var hasDisplay = false;
    for (var d = 0; d < delimiters.length; d++) {
      if (delimiters[d].left === "\\[") hasDisplay = true;
    }
    if (!hasDisplay) return;   // no-op unless \[ is in the effective set
    for (var i = 0; i < element.childNodes.length; i++) {
      var node = element.childNodes[i];
      if (node.nodeType !== 3) continue;
      // Spans come from the EFFECTIVE partition, so a \(...\) sequence sitting
      // inside a $$...$$ span is correctly not a candidate.
      var spans = findSpans(node.data, delimiters);
      var out = "";
      var cursor = 0;
      var changed = false;
      for (var s = 0; s < spans.length; s++) {
        var span = spans[s];
        out += node.data.slice(cursor, span.start);
        var raw = node.data.slice(span.start, span.end);
        if (span.delim.left === "\\(" &&
            containsDisplayOnlyEnv(raw.slice(2, raw.length - 2))) {
          out += "\\[" + raw.slice(2, raw.length - 2) + "\\]";
          changed = true;
        } else {
          out += raw;
        }
        cursor = span.end;
      }
      out += node.data.slice(cursor);
      if (changed) node.data = out;
    }
  }

  function reflow(root, options) {
    if (!root) return;  // three callers pass an unguarded root; leave auto-render's
                        // own "No element provided to render" error unchanged
    var extra = extraIgnoreSelector(options);
    // matches/closest are absent on Document and DocumentFragment, exactly as
    // math.js:18 already guards for [data-katex].
    if (isIgnored(root, extra)) return;
    if (root.closest && root.closest(IGNORE_SELECTOR)) return;
    if (extra && root.closest && root.closest(extra)) return;
    walk(root, extra, function (element) {
      mergeChildren(element, options, extra);   // phase 1
    });
    walk(root, extra, function (element) {
      phase1b(element, options);                // phase 1b
    });
    walk(root, extra, function (element) {
      phase2(element, options);                 // phase 2
    });
  }

  // The export is UNCONDITIONAL — only the hooks below are guarded on the KaTeX
  // globals. The DOM test harness loads this module alone, with no KaTeX.
  window.libliMathReflow = reflow;
  window.libliMathReflowDefaults = DEFAULT_DELIMITERS;

  if (window.__libliMathReflowWrapped) return;

  var autoRender = window.renderMathInElement;
  var katexObj = window.katex;
  if (typeof autoRender !== "function" || !katexObj ||
      typeof katexObj.render !== "function") {
    return;  // no KaTeX on this page: install nothing, change nothing
  }

  window.renderMathInElement = function (root, options) {
    try { reflow(root, options); } catch (e) { /* never block typesetting */ }
    return autoRender.apply(this, arguments);
  };

  // Reuses the ported findEndOfMath rather than a regex: /^\s*\\\[([\s\S]*)\\\]\s*$/
  // is greedy and would strip `\[a\] + \[b\]` — the one case that must be refused.
  function stripWrapper(expr) {
    if (typeof expr !== "string") return expr;
    var start = 0;
    while (start < expr.length && /\s/.test(expr.charAt(start))) start++;
    var end = expr.length;
    while (end > start && /\s/.test(expr.charAt(end - 1))) end--;
    var body = expr.slice(start, end);
    var pairs = [{ left: "\\[", right: "\\]" }, { left: "\\(", right: "\\)" }];
    for (var i = 0; i < pairs.length; i++) {
      var pair = pairs[i];
      if (body.indexOf(pair.left) !== 0) continue;
      var close = findEndOfMath(pair.right, body, pair.left.length);
      if (close === -1) continue;
      if (close + pair.right.length !== body.length) continue;  // not the outermost
      return body.slice(pair.left.length, close);
    }
    return expr;
  }

  var originalRender = katexObj.render;
  katexObj.render = function (expr, element, options) {
    var stripped = expr;
    try { stripped = stripWrapper(expr); } catch (e) { stripped = expr; }
    // options is passed through untouched — the hook writes nothing into it.
    return originalRender.call(this, stripped, element, options);
  };

  window.__libliMathReflowWrapped = true;
})();
