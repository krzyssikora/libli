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
    try { visit(node); } catch (e) {
      // per-element atomicity; see the spec. mergeChildren inserts replacement
      // nodes THEN removes the originals, so a throw between those two loops can
      // leave both in the DOM (duplicated content) with no other signal anywhere
      // -- warn so that window is at least diagnosable.
      if (window.console && window.console.warn) window.console.warn(e);
    }
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

  // The three values courses/sanitize.py's ALIGN_CLASS_VALUES permits on a block.
  var ALIGN_TOKENS = { "ta-left": true, "ta-center": true, "ta-right": true };

  // "" = no align class; one of the three = exactly one; null = INELIGIBLE (two or
  // more align tokens, or any token outside the three). nh3 filters class values
  // token-wise, so <p class="ta-center ta-left"> survives sanitising with BOTH
  // tokens -- measured against this repo's real config -- and has to be decided
  // rather than assumed away.
  //
  // Parsed as a token SET, never as the raw attribute string, so class=" ta-center "
  // and class="ta-center" agree. One deliberate side effect: class=" " yields an
  // empty set and therefore "", where noEffectiveAttributes (value === "") made it a
  // barrier. A whitespace-only class has no rendering effect, so the widening is
  // harmless; it is pinned by a test rather than left to be rediscovered.
  function alignToken(el) {
    var raw = el.getAttribute("class");
    if (raw === null) return "";
    var parts = raw.split(/\s+/);
    var found = "";
    for (var i = 0; i < parts.length; i++) {
      if (!parts[i]) continue;
      if (!ALIGN_TOKENS[parts[i]]) return null;
      if (found) return null;
      found = parts[i];
    }
    return found;
  }

  // The block-level attribute test. Differs from noEffectiveAttributes (which stays
  // as-is for isBareBr) in exactly one way: a `class` is judged by alignToken rather
  // than required to be empty. `style` must still be empty, and any other attribute
  // is still disqualifying.
  function blockAttributesOk(el) {
    for (var i = 0; i < el.attributes.length; i++) {
      var attr = el.attributes[i];
      if (attr.name === "style" && attr.value === "") continue;
      if (attr.name === "class") continue;      // validity decided by alignToken
      return false;
    }
    return alignToken(el) !== null;
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
    if (!blockAttributesOk(node)) return false;
    for (var i = 0; i < node.childNodes.length; i++) {
      var child = node.childNodes[i];
      if (child.nodeType === 3) continue;
      if (isBareBr(child)) continue;
      return false;
    }
    return true;
  }

  // Five kinds, because the partition now needs more than isMergeable's single
  // boolean: compatibility is pairwise, and WS_TEXT / TEXT / BR / BLOCK each behave
  // differently when they meet a signed run.
  //
  // The leading isIgnored test is load-bearing, and specifically for BR: a bare <br>
  // is classified via isBareBr and never reaches isMergeableBlock, so this guard is
  // the ONLY thing keeping an ignored <br> out of a run. isMergeable used to provide
  // it at its line-169 check; this function replaces isMergeable's only call site.
  function classifyChild(node, extraSelector) {
    if (node.nodeType === 3) return /\S/.test(node.data) ? "TEXT" : "WS_TEXT";
    if (node.nodeType !== 1) return "BARRIER";
    if (isIgnored(node, extraSelector)) return "BARRIER";
    if (isBareBr(node)) return "BR";
    if (isMergeableBlock(node, extraSelector)) return "BLOCK";
    return "BARRIER";
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
    // A synthetic newline is kept as a literal "\n" character (not dropped, not a
    // <br>): HTML collapses a bare \n to a single space, which is exactly the word
    // separation a synthetic boundary stands in for. Dropping it instead glues the
    // author's prose across the boundary -- e.g. "tail" / "head" -> "tailhead" --
    // whenever the neighbour is a bare text node or another group's replacement
    // text, rather than a surviving element (which keeps its own break). MEASURED
    // over 15 shapes; see docs/superpowers/specs/2026-08-01-display-math-authoring-
    // design.md rule 5 for the fix history. An AUTHORED newline still becomes a
    // real <br> element, because that break must survive further reflow passes.
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
        if (run.synthetic[i]) { buffer += "\n"; continue; }
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
    // A run now carries a SIGNATURE: the (alignToken, tagName) pair of its first
    // BLOCK member. `token === null` means not yet established; `""` means
    // established-unsigned; a non-empty string means signed. Membership rules M1-M5
    // are spelled out in the spec's Architecture section.
    var runs = [];
    var current = null;
    var i;

    function endRun() {
      if (current && current.indices.length) runs.push(current);
      current = null;
    }

    function newRun(index, token, tag, sawTextOrBr) {
      return { indices: [index], token: token, tag: tag, sawTextOrBr: sawTextOrBr };
    }

    for (i = 0; i < children.length; i++) {
      var kind = classifyChild(children[i], extraSelector);
      if (kind === "BARRIER") { endRun(); continue; }
      if (!current) {
        current = { indices: [], token: null, tag: null, sawTextOrBr: false };
      }

      if (kind === "WS_TEXT") {
        // M4: transparent. Never establishes a signature, never ends a run. nh3
        // preserves inter-tag newlines and the imported corpus has 505 of them
        // between sibling divs, so treating these as breaks would make the whole
        // feature a no-op on real content while every fixture stayed green.
        current.indices.push(i);
        continue;
      }

      if (kind === "TEXT" || kind === "BR") {
        if (current.token) {
          // M3: ends a signed run AND becomes the first member of a new one -- it is
          // not excluded from every run. Excluding it would regress a shape that
          // merges on master: <div class="ta-center">x</div>\[a<div>b\]</div>.
          endRun();
          current = newRun(i, null, null, true);
        } else {
          current.indices.push(i);
          current.sawTextOrBr = true;
        }
        continue;
      }

      var tok = alignToken(children[i]);
      var tag = children[i].tagName;
      if (current.token === null) {
        if (tok !== "" && current.sawTextOrBr) {
          // M5: a SIGNED block arriving into a run that already accumulated TEXT/BR
          // members breaks it rather than signing it retroactively. WS_TEXT is
          // deliberately NOT in that condition -- a run holding only transparent
          // whitespace stays joinable, which is the corpus shape.
          endRun();
          current = newRun(i, tok, tag, false);
        } else {
          current.indices.push(i);                  // M1: establishes the signature
          current.token = tok;
          current.tag = tag;
        }
      } else {
        // M2: compatible iff both unsigned (tag irrelevant, so DIV/P may mix), or
        // same token AND same tag.
        var ok = current.token === ""
          ? tok === ""
          : (tok === current.token && tag === current.tag);
        if (ok) current.indices.push(i);
        else { endRun(); current = newRun(i, tok, tag, false); }
      }
    }
    endRun();

    for (var r = runs.length - 1; r >= 0; r--) {
      var indices = runs[r].indices;
      var runToken = runs[r].token;
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
        if (runToken) {
          // SIGNED run: reuse the first covered block as the wrapper so the align
          // class survives. run.map never holds a zero-character member (buildRun
          // skips whitespace-only text nodes), and in a signed run every non-BLOCK
          // member is exactly such a node -- so nodes[group.first] is always a block.
          //
          // The ORDER below is a fault-tolerance requirement, not an arbitrary
          // choice. Snapshot first: after the insert, the replacement nodes are
          // themselves children of the wrapper, so "the original children" is only
          // recoverable from a snapshot -- a `while (wrapper.firstChild) remove()`
          // reading empties the wrapper and loses the merged line. Insert before
          // removing: today's unsigned path inserts then removes, so a throw between
          // the loops leaves duplicated content, which is survivable; clearing first
          // would lose the line outright.
          var wrapper = nodes[group.first];
          var original = [].slice.call(wrapper.childNodes);
          for (i = 0; i < replacement.length; i++) {
            wrapper.appendChild(replacement[i]);
          }
          for (i = 0; i < original.length; i++) {
            // Removed unconditionally, NOT "those represented in the replacement": a
            // child contributing zero characters (a leading <br> whose newline
            // pushBlockText suppressed) is represented nowhere and must still go,
            // exactly as the unsigned path drops it by deleting the whole block.
            if (original[i].parentNode === wrapper) wrapper.removeChild(original[i]);
          }
          for (i = group.first + 1; i <= group.last; i++) {
            // first + 1, never first: removing the wrapper would delete the content
            // just placed in it.
            if (nodes[i] && nodes[i].parentNode === element) {
              element.removeChild(nodes[i]);
            }
          }
        } else {
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

  // katex.render's stripWrapper hook checks both pairs on every call; hoisted so
  // a hot render loop does not re-allocate this literal each time.
  var STRIP_WRAPPER_PAIRS = [
    { left: "\\[", right: "\\]" },
    { left: "\\(", right: "\\)" }
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
    for (var i = 0; i < STRIP_WRAPPER_PAIRS.length; i++) {
      var pair = STRIP_WRAPPER_PAIRS[i];
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
