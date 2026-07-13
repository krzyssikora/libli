(function () {
  "use strict";

  var MARKER = "{{choice}}";
  var MIN_OPTIONS = 2;
  var DEBOUNCE_MS = 150;

  // i18n: JS strings are NOT extracted by makemessages, so read translated text
  // from data-* attributes the server-rendered partial provides (English fallback).
  function i18nCyclerPrefix(editor) {
    return (editor && editor.getAttribute("data-cycler-label-prefix")) || "Cycler";
  }
  function i18nBlankError(editor, pos) {
    // template must NOT contain the literal {{choice}} (Django would parse it in the
    // {% trans %} attribute) -> wording avoids it; %(n)s is the cycler number.
    var t = (editor && editor.getAttribute("data-blank-error"))
      || "Cycler %(n)s: fill in its options, or remove its marker.";
    return t.split("%(n)s").join(String(pos));
  }

  // Per-editor stash of removed cycler data, keyed by editor root -> "i:j" -> {options, answer}.
  var stashByEditor = new WeakMap();
  function stashFor(editor) {
    var m = stashByEditor.get(editor);
    if (!m) { m = {}; stashByEditor.set(editor, m); }
    return m;
  }

  function countMarkers(stem) {
    if (!stem) return 0;
    return stem.split(MARKER).length - 1;
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

  function tpl(editor, sel) {
    return editor.querySelector("template[" + sel + "]").content.cloneNode(true);
  }

  function optionRows(cyc) {
    return Array.prototype.slice.call(cyc.querySelectorAll(".el-editor__option-row"));
  }

  // Re-sequence a cycler's radio values to DOM position (server reads answer by position).
  function resequence(cyc) {
    var radios = cyc.querySelectorAll('input[type="radio"]');
    for (var r = 0; r < radios.length; r++) radios[r].value = r;
  }

  function makeOptionRow(editor, i, j) {
    var frag = tpl(editor, "data-option-template");
    rewrite(frag, { "__i__": i, "__j__": j });
    return frag.firstElementChild;
  }

  function makeCyclerBlock(editor, i, j) {
    var frag = tpl(editor, "data-cycler-template");
    rewrite(frag, { "__i__": i, "__j__": j });
    var block = frag.firstElementChild;
    var opts = block.querySelector("[data-options]");
    // seed two empty option rows, unchecked (matches server create render)
    opts.appendChild(makeOptionRow(editor, i, j));
    opts.appendChild(makeOptionRow(editor, i, j));
    resequence(block);
    return block;
  }

  function readCyclerData(cyc) {
    var options = [];
    var answer = -1;
    optionRows(cyc).forEach(function (row, k) {
      options.push(row.querySelector('input[type="text"]').value);
      if (row.querySelector('input[type="radio"]').checked) answer = k;
    });
    return { options: options, answer: answer };
  }

  function writeCyclerData(editor, cyc, i, j, data) {
    var opts = cyc.querySelector("[data-options]");
    opts.innerHTML = "";
    var vals = (data && data.options) || ["", ""];
    if (vals.length < MIN_OPTIONS) vals = vals.concat(["", ""]).slice(0, MIN_OPTIONS);
    vals.forEach(function (v, k) {
      var row = makeOptionRow(editor, i, j);
      row.querySelector('input[type="text"]').value = v;
      if (data && data.answer === k) row.querySelector('input[type="radio"]').checked = true;
      opts.appendChild(row);
    });
    resequence(cyc);
  }

  // Reconcile ONE line: cycler block count == marker count (tail add/remove), labels, stash.
  function reconcileLine(editor, line) {
    var i = line.getAttribute("data-line-index");
    var stem = line.querySelector("[data-stem]");
    var want = countMarkers(stem ? stem.value : "");
    var cycWrap = line.querySelector("[data-cyclers]");
    var blocks = Array.prototype.slice.call(cycWrap.querySelectorAll("[data-cycler-row]"));
    var stash = stashFor(editor);

    // shrink from tail: stash removed blocks by (i,j)
    while (blocks.length > want) {
      var gone = blocks.pop();
      var gj = gone.getAttribute("data-cycler-index");
      stash[i + ":" + gj] = readCyclerData(gone);
      gone.remove();
    }
    // grow at tail: restore from stash if present, else a fresh seeded block
    while (blocks.length < want) {
      var j = String(blocks.length); // dense: next index == current count
      var block = makeCyclerBlock(editor, i, j);
      cycWrap.appendChild(block);
      var key = i + ":" + j;
      if (stash[key]) { writeCyclerData(editor, block, i, j, stash[key]); delete stash[key]; }
      blocks.push(block);
    }
    // (re)label positionally, using the translated prefix from the root
    var prefix = i18nCyclerPrefix(editor);
    blocks.forEach(function (b, pos) {
      var label = b.querySelector("[data-cycler-label]");
      if (label) label.textContent = prefix + " " + (pos + 1);
    });
  }

  // Hide (not just no-op) each remove-× when at the minimum: a visible-but-inert
  // control is exactly the confusion this editor exists to remove. min 2 options / 1 line.
  function refreshGuards(editor) {
    var lines = editor.querySelectorAll("[data-line-row]");
    var onlyOneLine = lines.length <= 1;
    lines.forEach(function (line) {
      var rl = line.querySelector("[data-remove-line]");
      if (rl) rl.hidden = onlyOneLine;
      line.querySelectorAll("[data-cycler-row]").forEach(function (cyc) {
        var atMin = optionRows(cyc).length <= MIN_OPTIONS;
        cyc.querySelectorAll("[data-remove-option]").forEach(function (b) { b.hidden = atMin; });
      });
    });
  }

  function reconcileAll(root) {
    (root || document).querySelectorAll("[data-switchgrid-editor]").forEach(function (editor) {
      editor.querySelectorAll("[data-line-row]").forEach(function (line) {
        reconcileLine(editor, line);
      });
      refreshGuards(editor);
    });
  }

  function nextLineIndex(editor) {
    // monotonic: max(existing)+1, NEVER child count (post-remove indices are gappy)
    var max = -1;
    editor.querySelectorAll("[data-line-row]").forEach(function (l) {
      var v = parseInt(l.getAttribute("data-line-index"), 10);
      if (!isNaN(v) && v > max) max = v;
    });
    return max + 1;
  }

  // ---- events ----
  // Per-LINE debounce: typing in one line must not cancel another line's pending
  // reconcile (a single shared timer would drop a cross-line edit until submit).
  var lineTimers = new WeakMap();
  var pendingTimers = new Set();
  function onInput(e) {
    var stem = e.target.closest("[data-stem]");
    if (!stem) return;
    var editor = stem.closest("[data-switchgrid-editor]");
    if (!editor) return;
    var line = stem.closest("[data-line-row]");
    var prev = lineTimers.get(line);
    if (prev) { clearTimeout(prev); pendingTimers.delete(prev); }
    var t = setTimeout(function () {
      lineTimers.delete(line);
      pendingTimers.delete(t);
      reconcileLine(editor, line);
      refreshGuards(editor);
    }, DEBOUNCE_MS);
    lineTimers.set(line, t);
    pendingTimers.add(t);
  }

  function flushPending() {
    pendingTimers.forEach(function (t) { clearTimeout(t); });
    pendingTimers.clear();
  }

  function reconcileEditor(editor) {
    // reconcile every line in ONE editor synchronously (note: reconcileAll's
    // querySelectorAll would NOT match the editor node itself, so iterate lines)
    editor.querySelectorAll("[data-line-row]").forEach(function (line) {
      reconcileLine(editor, line);
    });
    refreshGuards(editor);
  }

  function onClick(e) {
    var editor = e.target.closest("[data-switchgrid-editor]");
    if (!editor) return;

    if (e.target.closest("[data-add-line]")) {
      var i = nextLineIndex(editor);
      var frag = tpl(editor, "data-line-template");
      rewrite(frag, { "__i__": i });
      editor.querySelector("[data-lines]").appendChild(frag);
      var newLine = editor.querySelector('[data-line-row][data-line-index="' + i + '"]');
      reconcileLine(editor, newLine); // seeded stem has a marker -> materialize its cycler
      refreshGuards(editor);
      return;
    }
    var remLine = e.target.closest("[data-remove-line]");
    if (remLine) {
      var lines = editor.querySelectorAll("[data-line-row]");
      if (lines.length <= 1) return; // min 1 line
      var lr = remLine.closest("[data-line-row]");
      var li = lr.getAttribute("data-line-index");
      var stash = stashFor(editor);
      Object.keys(stash).forEach(function (k) { if (k.indexOf(li + ":") === 0) delete stash[k]; });
      lr.remove();
      refreshGuards(editor);
      return;
    }
    var addOpt = e.target.closest("[data-add-option]");
    if (addOpt) {
      var cyc = addOpt.closest("[data-cycler-row]");
      var li2 = cyc.closest("[data-line-row]").getAttribute("data-line-index");
      var cj = cyc.getAttribute("data-cycler-index");
      cyc.querySelector("[data-options]").appendChild(makeOptionRow(editor, li2, cj));
      resequence(cyc);
      refreshGuards(editor);
      return;
    }
    var remOpt = e.target.closest("[data-remove-option]");
    if (remOpt) {
      var cyc2 = remOpt.closest("[data-cycler-row]");
      if (optionRows(cyc2).length <= MIN_OPTIONS) return; // min 2 options
      remOpt.closest(".el-editor__option-row").remove();
      resequence(cyc2); // checked row may be gone -> that's fine (server backstop)
      refreshGuards(editor);
      return;
    }
  }

  // Submit guard: flush pending reconcile, then block all-blank cyclers with a clear message.
  function onSubmit(e) {
    var form = e.target;
    if (!form.querySelector) return;
    var editor = form.querySelector("[data-switchgrid-editor]");
    if (!editor) return;
    flushPending();               // cancel any pending per-line debounce timers
    reconcileEditor(editor);      // then reconcile synchronously so the DOM matches the stems before POST
    // clear stale inline errors so a re-submit doesn't leave a message on a now-valid cycler
    editor.querySelectorAll("[data-inline-error]").forEach(function (m) { m.remove(); });
    var bad = null, badPos = 0;
    editor.querySelectorAll("[data-line-row]").forEach(function (line) {
      Array.prototype.slice.call(line.querySelectorAll("[data-cycler-row]")).forEach(function (cyc, pos) {
        var anyFilled = optionRows(cyc).some(function (row) {
          return row.querySelector('input[type="text"]').value.trim() !== "";
        });
        if (!anyFilled && !bad) { bad = cyc; badPos = pos + 1; }
      });
    });
    if (bad) {
      e.preventDefault();
      e.stopPropagation();
      showBlankError(editor, bad, badPos);
    }
  }

  function showBlankError(editor, cyc, pos) {
    // minimal inline message; styled by CSS (.el-editor__inline-error)
    var msg = cyc.querySelector("[data-inline-error]");
    if (!msg) {
      msg = document.createElement("p");
      msg.className = "el-editor__inline-error field-error";
      msg.setAttribute("data-inline-error", "");
      cyc.appendChild(msg);
    }
    msg.textContent = i18nBlankError(editor, pos);
    cyc.scrollIntoView({ block: "center" });
    var firstText = cyc.querySelector('input[type="text"]');
    if (firstText) firstText.focus();
  }

  document.addEventListener("click", onClick);
  document.addEventListener("input", onInput);
  document.addEventListener("submit", onSubmit, true); // capture: run before the POST

  window.libliInitSwitchGridEditors = function (root) { reconcileAll(root); };
  document.addEventListener("DOMContentLoaded", function () { reconcileAll(document); });
})();
