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
    visit(node);
  }

  function mergeChildren(element, options, extraSelector) { /* Task 4 */ }

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
      mergeChildren(element, options, extra);   // Task 4
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

  var originalRender = katexObj.render;
  katexObj.render = function (expr, element, options) {
    return originalRender.apply(this, arguments);  // Task 7 adds the strip
  };

  window.__libliMathReflowWrapped = true;
})();
