(function () {
  "use strict";

  // Pure DOM + string logic for internal/external links. Deliberately separate from
  // link_dialog.js and text_toolbar.js so it can be loaded into a blank page and
  // unit-tested (see tests/test_link_apply.py) -- logic inside text_toolbar.js's
  // IIFE would only be reachable by driving the whole editor.

  var PERMALINK = /^\/courses\/n\/(\d+)\/$/;   // anchored: must match the dialog

  // ---- URL contract: an ORDERED table, first match wins ---------------------
  // Order is load-bearing. An absolute same-origin permalink satisfies BOTH the
  // normalisation row and the scheme-allowlist row; evaluating the allowlist first
  // would accept it verbatim and then trip the outbound-marker misclassification the
  // normalisation exists to prevent.
  function normalizeUrl(input, origin) {
    var v = (input || "").trim();
    if (!v) return { reject: "relative" };

    // 1. protocol-relative: an off-site link wearing a relative disguise. It survives
    //    the sanitiser untouched and matches NEITHER student-side selector, so it
    //    would render with no marker at all.
    if (v.indexOf("//") === 0) return { reject: "protocol-relative" };

    // 2. absolute same-origin permalink -> relative form
    if (origin && v.indexOf(origin + "/") === 0) {
      var rest = v.slice(origin.length);
      if (PERMALINK.test(rest)) return { href: rest };
    }

    // 3. has a scheme? Only when the leading token has NO dot -- `example.com:8080/x`
    //    is a syntactically valid scheme token but is really a host:port.
    var m = /^([A-Za-z][A-Za-z0-9+.-]*):/.exec(v);
    if (m && m[1].indexOf(".") === -1) {
      var scheme = m[1].toLowerCase();
      if (scheme === "http" || scheme === "https" || scheme === "mailto") {
        return { href: v };
      }
      return { reject: "scheme" };
    }

    // 4. bare host: first segment contains a dot, no whitespace, no leading / or .
    if (v.charAt(0) !== "/" && v.charAt(0) !== "." && !/\s/.test(v)) {
      var first = v.split("/")[0];
      if (first.indexOf(".") !== -1) return { href: "https://" + v };
    }

    // 5. catch-all -- the table is TOTAL over input strings.
    return { reject: "relative" };
  }

  // ---- anchor enumeration ---------------------------------------------------
  function elementOf(node) {
    // Range.startContainer is usually a TEXT node, which has no closest().
    return node && node.nodeType === 3 ? node.parentNode : node;
  }

  function enclosing(surface, range) {
    // An anchor ENCLOSES a range when BOTH boundary points are within it. Covers a
    // caret inside a link and a selection exactly coextensive with its text. Anchors
    // never nest, so at most one can enclose. A caret at a leading/trailing text
    // boundary counts as enclosed -- deliberately: clicking just after a link's last
    // character means "edit this link", matching how typing there behaves.
    var start = elementOf(range.startContainer);
    var a = start && start.closest ? start.closest("a") : null;
    if (!a || !surface.contains(a)) return null;
    return a.contains(range.endContainer) ? a : null;
  }

  function anchorsFor(surface, range) {
    var enc = enclosing(surface, range);
    if (range.collapsed) return enc ? [enc] : [];
    var out = [];
    var all = surface.querySelectorAll("a");
    for (var i = 0; i < all.length; i++) {
      if (range.intersectsNode(all[i])) out.push(all[i]);
    }
    if (enc && out.indexOf(enc) === -1) out.push(enc);
    return out;
  }

  // ---- mutation -------------------------------------------------------------
  function textNode(s) { return document.createTextNode(s == null ? "" : String(s)); }

  function unwrap(a) {
    var parent = a.parentNode;
    while (a.firstChild) parent.insertBefore(a.firstChild, a);
    parent.removeChild(a);
  }

  function makeAnchor(href, text) {
    var a = document.createElement("a");
    a.setAttribute("href", href);
    a.appendChild(textNode(text));
    return a;
  }

  function collapseAfter(node) {
    var sel = window.getSelection();
    var r = document.createRange();
    r.setStartAfter(node);
    r.collapse(true);
    sel.removeAllRanges();
    sel.addRange(r);
  }

  // A marker is an empty text node used as a stable position handle across mutations
  // that would otherwise detach the nodes we are holding.
  function marker() { return textNode(""); }

  function dropMarker(m) { if (m.parentNode) m.parentNode.removeChild(m); }

  function apply(surface, range, result) {
    var touched = anchorsFor(surface, range);

    if (result && result.remove) {
      // No deleteContents here: the recovered text is exactly what this preserves.
      // The caret is pinned with a MARKER, not with a neighbouring node: normalize()
      // merges adjacent text nodes into the FIRST and removes the rest, so a caret
      // anchored to one of the removed nodes would make setStartAfter throw
      // InvalidNodeTypeError. Insert the marker after the last unwrapped anchor's
      // content, normalise, then collapse to the marker's position and drop it.
      var endMark = marker();
      if (touched.length) {
        var lastAnchor = touched[touched.length - 1];
        lastAnchor.parentNode.insertBefore(endMark, lastAnchor.nextSibling);
      }
      for (var i = 0; i < touched.length; i++) unwrap(touched[i]);
      if (endMark.parentNode) {
        var sel = window.getSelection();
        var r = document.createRange();
        r.setStartBefore(endMark);
        r.collapse(true);
        sel.removeAllRanges();
        sel.addRange(r);
        dropMarker(endMark);
      }
      surface.normalize();   // AFTER the caret is set: normalize invalidates handles
      return;
    }

    var enc = enclosing(surface, range);
    if (enc) {
      // Rule 1: edit in place. If the text came back byte-identical to the anchor's
      // own textContent, touch only the href so inline <b>/<em>/math survives an
      // author who only wanted to fix the URL.
      enc.setAttribute("href", result.href);
      if (result.text !== enc.textContent) {
        while (enc.firstChild) enc.removeChild(enc.firstChild);
        enc.appendChild(textNode(result.text));
      }
      collapseAfter(enc);
      return;
    }

    if (!range.collapsed) {
      // Rule 2. Marker nodes first: unwrapping removes the element a boundary
      // container may BE, leaving the range pointing at a detached node so the
      // following deleteContents()/insertNode() would misbehave or throw.
      var startMark = marker();
      var endMark2 = marker();
      var r2 = range.cloneRange();
      r2.collapse(false);
      r2.insertNode(endMark2);
      var r1 = range.cloneRange();
      r1.collapse(true);
      r1.insertNode(startMark);

      for (var j = 0; j < touched.length; j++) unwrap(touched[j]);

      var work = document.createRange();
      work.setStartAfter(startMark);   // after/before, so removing the markers
      work.setEndBefore(endMark2);     // cannot shift the boundaries
      work.deleteContents();
      var anchor = makeAnchor(result.href, result.text);
      work.insertNode(anchor);
      dropMarker(startMark);
      dropMarker(endMark2);
      collapseAfter(anchor);           // BEFORE normalize, which detaches handles
      surface.normalize();
      return;
    }

    // Rule 3.
    var fresh = makeAnchor(result.href, result.text);
    range.insertNode(fresh);
    collapseAfter(fresh);
    surface.normalize();
  }

  window.libliLinkApply = {
    anchorsFor: anchorsFor,
    enclosing: enclosing,
    apply: apply,
    normalizeUrl: normalizeUrl
  };
})();
