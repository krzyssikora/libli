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

  function applyCmd(cmd, surface) {
    surface.focus();
    switch (cmd) {
      case "bold": exec("bold"); break;
      case "italic": exec("italic"); break;
      case "underline": exec("underline"); break;
      case "h2": case "h3": case "h4": case "blockquote":
        exec("formatBlock", "<" + TAG_CMD[cmd] + ">"); break;
      case "ul": exec("insertUnorderedList"); break;
      case "ol": exec("insertOrderedList"); break;
      case "code": exec("formatBlock", "<pre>"); break;
      case "link":
        var url = window.prompt("URL");
        if (url) exec("createLink", url);
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
    surface.innerHTML = textarea.value;
    textarea.hidden = true;
    textarea.parentNode.insertBefore(surface, textarea);

    function sync() { textarea.value = surface.innerHTML; }
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
    }
    surface.addEventListener("keyup", refreshActive);
    surface.addEventListener("mouseup", refreshActive);
    document.addEventListener("selectionchange", function () {
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
