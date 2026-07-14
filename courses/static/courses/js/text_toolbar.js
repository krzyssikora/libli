(function () {
  "use strict";

  // ---- Rich text editor: progressively enhance [data-rte-source] textareas. ----
  // With JS off, the plain textarea submits raw HTML (sanitised server-side).
  // With JS on, we mount a contenteditable surface, drive it from the toolbar's
  // [data-cmd] buttons, and sync its innerHTML back into the hidden textarea so
  // the form still submits HTML under name="body". The server sanitises regardless.
  var TAG_CMD = { h2: "h2", h3: "h3", h4: "h4", blockquote: "blockquote" };

  function exec(cmd, value) {
    try { document.execCommand(cmd, false, value || null); } catch (e) { /* ignore */ }
  }

  // Toggle the persistent document-global styleWithCSS flag. MUST be a direct
  // execCommand call — the exec() wrapper does `value || null`, so exec("styleWithCSS",
  // false) would pass null, and any 3rd-arg other than the literal "false" turns
  // styleWithCSS ON. That inversion would break bold/italic/underline.
  function styleWithCss(on) {
    try { document.execCommand("styleWithCSS", false, on); } catch (e) { /* ignore */ }
  }

  // Surface speaks inline text-align (execCommand output); stored/submitted HTML
  // speaks ta-* classes (sanitizer-friendly). These bridge the two, both pure.
  function styleToClass(html) {
    var box = document.createElement("div");
    box.innerHTML = html;
    box.querySelectorAll("*").forEach(function (el) {
      var val = ((el.style && el.style.textAlign) || "").trim().toLowerCase();
      if (val === "left" || val === "center" || val === "right") {
        el.classList.remove("ta-left", "ta-center", "ta-right");
        el.classList.add("ta-" + val);
        el.style.textAlign = "";
        if (!el.getAttribute("style")) el.removeAttribute("style");
      }
    });
    return box.innerHTML;
  }

  function classToStyle(html) {
    var box = document.createElement("div");
    box.innerHTML = html;
    ["left", "center", "right"].forEach(function (v) {
      box.querySelectorAll(".ta-" + v).forEach(function (el) {
        el.style.textAlign = v;
        el.classList.remove("ta-" + v);
        if (!el.getAttribute("class")) el.removeAttribute("class");
      });
    });
    return box.innerHTML;
  }

  function applyCmd(cmd, surface) {
    surface.focus();
    switch (cmd) {
      // Reset styleWithCSS so these emit <b>/<i>/<u> (sanitizer-kept), never
      // <span style> (stripped) — in case a prior align click left the flag true.
      case "bold": styleWithCss(false); exec("bold"); break;
      case "italic": styleWithCss(false); exec("italic"); break;
      case "underline": styleWithCss(false); exec("underline"); break;
      case "alignleft": case "aligncenter": case "alignright": {
        var JUSTIFY = { alignleft: "justifyLeft", aligncenter: "justifyCenter", alignright: "justifyRight" };
        styleWithCss(true);   // force inline text-align (not FF's align attr)
        exec(JUSTIFY[cmd]);
        styleWithCss(false);  // MUST reset — persistent document-global flag
        break;
      }
      case "h2": case "h3": case "h4": case "blockquote":
        exec("formatBlock", "<" + TAG_CMD[cmd] + ">"); break;
      case "ul": exec("insertUnorderedList"); break;
      case "ol": exec("insertOrderedList"); break;
      case "code": exec("formatBlock", "<pre>"); break;
      case "link":
        var url = window.prompt("URL");
        if (url) exec("createLink", url);
        break;
      case "math":
        if (!window.libliMathInput) break;
        var sel = window.getSelection();
        var range = sel && sel.rangeCount ? sel.getRangeAt(0) : null;
        window.libliMathInput.open(function (latex) {
          surface.focus();
          var node = document.createTextNode("\\(" + latex + "\\)");
          if (range) {
            range.deleteContents();
            range.insertNode(node);
            range.setStartAfter(node); range.collapse(true);
            sel.removeAllRanges(); sel.addRange(range);
          } else {
            surface.appendChild(node);
          }
          surface.dispatchEvent(new Event("input"));
        });
        break;
      default: break;
    }
  }

  function wireRte(textarea) {
    if (textarea.dataset.rteWired) return;
    textarea.dataset.rteWired = "1";
    var wrap = textarea.closest(".el-editor--text") || textarea.parentNode;
    var toolbar = wrap.querySelector("[data-rte-toolbar]");

    var surface = document.createElement("div");
    surface.className = "rte-surface";
    surface.setAttribute("contenteditable", "true");
    // Enter must yield a <div> block on BOTH Chrome and Firefox (FF defaults to <br>),
    // so per-block alignment is usable cross-browser.
    try { document.execCommand("defaultParagraphSeparator", false, "div"); } catch (e) { /* ignore */ }
    surface.innerHTML = classToStyle(textarea.value);
    textarea.hidden = true;
    textarea.parentNode.insertBefore(surface, textarea);

    function sync() { textarea.value = styleToClass(surface.innerHTML); }
    surface.addEventListener("input", sync);
    // Ensure the latest content is in the textarea before the form submits.
    var form = textarea.closest("form");
    if (form) form.addEventListener("submit", sync);

    if (toolbar) {
      toolbar.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-cmd]");
        if (!btn) return;
        e.preventDefault();
        applyCmd(btn.getAttribute("data-cmd"), surface);
        sync();
      });
    }

    function refreshActive() {
      if (!toolbar) return;
      var map = { bold: "bold", italic: "italic", underline: "underline" };
      toolbar.querySelectorAll("[data-cmd]").forEach(function (btn) {
        var cmd = btn.getAttribute("data-cmd");
        if (map[cmd]) {
          var on = false;
          try { on = document.queryCommandState(map[cmd]); } catch (e) { on = false; }
          btn.classList.toggle("is-on", !!on);
        }
      });
      // Alignment buttons: data-cmd != queryCommandState name, and Left is derived,
      // so they can't join the flat bold/italic map above.
      var center = false, right = false;
      try { center = document.queryCommandState("justifyCenter"); } catch (e) { center = false; }
      try { right = document.queryCommandState("justifyRight"); } catch (e) { right = false; }
      var cBtn = toolbar.querySelector('[data-cmd="aligncenter"]');
      var rBtn = toolbar.querySelector('[data-cmd="alignright"]');
      var lBtn = toolbar.querySelector('[data-cmd="alignleft"]');
      if (cBtn) cBtn.classList.toggle("is-on", !!center);
      if (rBtn) rBtn.classList.toggle("is-on", !!right);
      if (lBtn) lBtn.classList.toggle("is-on", !center && !right);
    }
    surface.addEventListener("keyup", refreshActive);
    surface.addEventListener("mouseup", refreshActive);
    document.addEventListener("selectionchange", function () {
      if (!surface.isConnected) return;       // skip stale surfaces from prior edits
      if (document.activeElement === surface) refreshActive();
    });
  }

  function initRte(root) {
    (root || document).querySelectorAll("[data-rte-source]").forEach(wireRte);
  }

  // ---- Math live preview. EXACT spec: must bypass the KaTeX idempotency guard. ----
  window.libliInitMathLive = function (root) {
    (root || document).querySelectorAll("[data-math-live]").forEach(function (live) {
      var editor = live.closest(".el-editor--math");
      var input = editor && editor.querySelector("[data-math-input]");
      if (!input) return;                       // defensive: markup changed
      function rerender() {
        delete live.dataset.katexDone;          // bypass the idempotency guard
        live.textContent = input.value;         // raw LaTeX into the render target
        if (window.libliRenderMath) window.libliRenderMath(live);
      }
      if (!input.dataset.mathWired) {            // wire the debounced input once
        var t; input.addEventListener("input", function () { clearTimeout(t); t = setTimeout(rerender, 250); });
        input.dataset.mathWired = "1";
      }
      rerender();                                // initial render on open
    });
  };

  // Initial passes for content already present at page load (e.g. ?add server render).
  initRte(document);
  window.libliInitMathLive(document);

  // Re-run RTE enhancement after editor fragment swaps (editor.js swaps innerHTML).
  window.libliInitRte = initRte;
})();
