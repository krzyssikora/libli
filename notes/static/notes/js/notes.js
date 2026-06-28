/* notes.js — progressive-enhancement layer for Phase 4a personal notes.
 *
 * Degrades gracefully: with JS disabled the <details> accordion, native POST
 * forms, and standalone edit/confirm pages all still work unchanged.
 *
 * Four behaviours (all via event delegation — works for dynamically added cards):
 *   1. Fragment submit — add-composer intercept (201→append, 422→replace composer)
 *   2. Inline edit    — ✏️ click → inline form (body from DOM) → fetch note_edit
 *   3. Inline delete  — 🗑 click → inline confirm → fetch POST → remove card
 *   4. Association    — hover/focus on handle or card → highlight + SVG connector
 */
(function () {
  "use strict";

  /* ── CSRF ────────────────────────────────────────────────────────────── */
  function getCsrf() {
    /* Prefer the cookie (always fresh after any response); fall back to the
       first hidden input on the page (present in every composer).            */
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    var el = document.querySelector('[name="csrfmiddlewaretoken"]');
    return el ? el.value : "";
  }

  /* ── HTML helpers ────────────────────────────────────────────────────── */
  /* Parse an HTML string and return the first child element. */
  function parseHtml(html) {
    var div = document.createElement("div");
    div.innerHTML = html.trim();
    return div.firstElementChild;
  }

  /* Extract the plain-text body from a .note-card, converting <br> to \n. */
  function getCardBody(card) {
    var bodyEl = card.querySelector(".note-card__body");
    if (!bodyEl) return "";
    var clone = bodyEl.cloneNode(true);
    clone.querySelectorAll("br").forEach(function (br) {
      br.replaceWith("\n");
    });
    return clone.textContent.trim();
  }

  /* Add tabindex="0" to any .note-card that is not yet keyboard-focusable.
     Called after initial DOM scan and after any dynamic card insertion.     */
  function makeFocusable(root) {
    var scope = root || document;
    scope.querySelectorAll(".note-card").forEach(function (card) {
      if (!card.hasAttribute("tabindex")) {
        card.setAttribute("tabindex", "0");
      }
    });
  }

  /* Update the count badge in a .block-notes aside after add/delete. */
  function updateHandleCount(aside) {
    if (!aside) return;
    var list = aside.querySelector(".block-notes__list");
    var n = list ? list.querySelectorAll(".note-card").length : 0;
    var badge = aside.querySelector(".block-notes__count");
    if (!badge) return;
    /* Keep it simple — the server uses "N note" / "N notes" in English;
       we match that for JS-added/removed cards. The server refreshes on
       full reload anyway.                                                    */
    badge.textContent = n === 1 ? "1 note" : n + " notes";
  }

  /* ── 1. Fragment submit (add composer + JS-built edit form) ──────────── */
  document.addEventListener("submit", function (e) {
    var form = e.target.closest(".note-composer");
    if (!form) return;

    var action = form.getAttribute("action") || "";
    var isAdd  = action.indexOf("/notes/add/") !== -1;
    var isEdit = form.dataset.noteAction === "edit" ||
                 action.indexOf("/edit/") !== -1;

    if (!isAdd && !isEdit) return; /* not a notes form we own */
    e.preventDefault();

    var data = new FormData(form);
    /* Ensure the CSRF token is present (FormData picks up the hidden input
       in template-rendered forms; for JS-built forms we inject it here).    */
    if (!data.get("csrfmiddlewaretoken")) {
      data.set("csrfmiddlewaretoken", getCsrf());
    }

    fetch(action, {
      method: "POST",
      headers: { "X-Requested-With": "fetch" },
      body: data,
    })
      .then(function (resp) {
        var status = resp.status;
        return resp.text().then(function (html) {
          return { status: status, html: html };
        });
      })
      .then(function (result) {
        var status = result.status;
        var html   = result.html;

        if (isAdd) {
          if (status === 201) {
            /* Append the new card to the block's list, clear the textarea. */
            var panel = form.closest(".block-notes__panel");
            var list  = panel
              ? panel.querySelector(".block-notes__list")
              : null;
            if (list) {
              var card = parseHtml(html);
              list.appendChild(card);
              makeFocusable(list);
            }
            var ta = form.querySelector("textarea[name='body']");
            if (ta) ta.value = "";
            /* Update the handle badge count. */
            updateHandleCount(form.closest(".block-notes"));
          } else if (status === 422) {
            /* Replace the composer with the error version. */
            var newForm = parseHtml(html);
            form.replaceWith(newForm);
          }
        } else if (isEdit) {
          if (status === 200) {
            /* Replace the inline edit form with the updated card. */
            var updatedCard = parseHtml(html);
            makeFocusable(updatedCard.parentNode || document);
            updatedCard.setAttribute("tabindex", "0");
            form.replaceWith(updatedCard);
          } else if (status === 422) {
            /* Show the error composer in place of the edit form. */
            var errorForm = parseHtml(html);
            form.replaceWith(errorForm);
          }
        }
      })
      .catch(function () {
        /* Network error — leave the form in its current state. */
      });
  });

  /* ── 2. Inline edit (✏️) ─────────────────────────────────────────────── */
  document.addEventListener("click", function (e) {
    var editLink = e.target.closest(".note-action--edit");
    if (!editLink) return;
    e.preventDefault();

    var card = editLink.closest(".note-card");
    if (!card) return;

    var body    = getCardBody(card);
    var editUrl = editLink.getAttribute("href");

    /* Build the inline edit form programmatically (no innerHTML with user
       content — use element creation + .value for the textarea).            */
    var form = document.createElement("form");
    form.className = "note-composer note-composer--edit";
    form.method    = "post";
    form.setAttribute("action", editUrl);
    form.dataset.noteAction = "edit"; /* marker for the submit handler */

    /* CSRF hidden input */
    var csrfInput = document.createElement("input");
    csrfInput.type  = "hidden";
    csrfInput.name  = "csrfmiddlewaretoken";
    csrfInput.value = getCsrf();
    form.appendChild(csrfInput);

    /* Body textarea — prefilled from DOM (no extra GET round-trip). */
    var ta       = document.createElement("textarea");
    ta.className = "note-composer__input";
    ta.name      = "body";
    ta.rows      = 3;
    ta.maxLength = 5000;
    ta.value     = body;
    form.appendChild(ta);

    /* Actions row */
    var actions        = document.createElement("div");
    actions.className  = "note-composer__actions";

    var saveBtn       = document.createElement("button");
    saveBtn.type      = "submit";
    saveBtn.className = "btn btn--sm";
    saveBtn.textContent = "Save";

    var cancelBtn       = document.createElement("button");
    cancelBtn.type      = "button";
    cancelBtn.className = "btn btn--ghost btn--sm note-composer__cancel";
    cancelBtn.textContent = "Cancel";

    /* Cancel: restore the original card. */
    cancelBtn.addEventListener("click", function () {
      form.replaceWith(card);
    });

    actions.appendChild(saveBtn);
    actions.appendChild(cancelBtn);
    form.appendChild(actions);

    card.replaceWith(form);
    ta.focus();
    /* Move caret to end of textarea. */
    ta.selectionStart = ta.selectionEnd = ta.value.length;
  });

  /* ── 3. Inline delete-confirm (🗑) ───────────────────────────────────── */
  document.addEventListener("click", function (e) {
    var delLink = e.target.closest(".note-action--delete");
    if (!delLink) return;
    e.preventDefault();

    var card   = delLink.closest(".note-card");
    if (!card) return;
    var delUrl = delLink.getAttribute("href");

    /* Build the inline confirm affordance. */
    var confirm        = document.createElement("div");
    confirm.className  = "note-delete-confirm";
    confirm.setAttribute("role", "group");
    confirm.setAttribute("aria-label", "Confirm deletion");

    var prompt        = document.createElement("span");
    prompt.className  = "note-delete-confirm__prompt";
    prompt.textContent = "Delete?";

    var yesBtn       = document.createElement("button");
    yesBtn.type      = "button";
    yesBtn.className = "btn btn--sm";
    yesBtn.textContent = "Yes";

    var noBtn       = document.createElement("button");
    noBtn.type      = "button";
    noBtn.className = "btn btn--ghost btn--sm";
    noBtn.textContent = "No";

    yesBtn.addEventListener("click", function () {
      var aside = card.closest(".block-notes");
      var data  = new FormData();
      data.set("csrfmiddlewaretoken", getCsrf());

      fetch(delUrl, {
        method:   "POST",
        headers:  { "X-Requested-With": "fetch" },
        body:     data,
        redirect: "follow",
      })
        .then(function (resp) {
          if (resp.ok) {
            confirm.remove();
            updateHandleCount(aside);
          } else {
            /* Server refused — restore the card. */
            confirm.replaceWith(card);
          }
        })
        .catch(function () {
          confirm.replaceWith(card);
        });
    });

    noBtn.addEventListener("click", function () {
      confirm.replaceWith(card);
    });

    confirm.appendChild(prompt);
    confirm.appendChild(yesBtn);
    confirm.appendChild(noBtn);
    card.replaceWith(confirm);
    yesBtn.focus();
  });

  /* ── 4. Association highlight + SVG connector ────────────────────────── */
  var currentAnchorId    = null;
  var svgConnector       = null;
  var reducedMotion      = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;

  /* Return the data-anchor-element value for the hovered/focused element,
     or null if not a handle/card trigger.
     - Handle: read from parent .block-notes (the aside owns the anchor).
     - Card:   read directly from the .note-card element.                    */
  function getAnchorId(el) {
    var handle = el.closest(".block-notes__handle");
    if (handle) {
      var aside = handle.closest(".block-notes");
      return aside ? aside.getAttribute("data-anchor-element") : null;
    }
    var card = el.closest(".note-card");
    if (card) {
      return card.getAttribute("data-anchor-element") || null;
    }
    return null;
  }

  /* Remove all highlight/dim classes and the SVG connector line. */
  function clearHighlight() {
    document.querySelectorAll(
      ".lesson-block.is-highlighted, .lesson-block.is-dimmed"
    ).forEach(function (el) {
      el.classList.remove("is-highlighted", "is-dimmed");
    });
    document.querySelectorAll(
      ".note-card.is-highlighted, .block-notes__handle.is-highlighted"
    ).forEach(function (el) {
      el.classList.remove("is-highlighted");
    });
    if (svgConnector) {
      svgConnector.remove();
      svgConnector = null;
    }
  }

  /* Draw a dashed SVG connector from the right edge of .lesson-block__body
     to the left edge of the handle — desktop (>=1024px) only.              */
  function drawConnector(handleEl, blockEl) {
    if (reducedMotion) return;
    if (window.innerWidth < 1024) return;

    var bodyEl   = blockEl.querySelector(".lesson-block__body");
    var bRect    = bodyEl
      ? bodyEl.getBoundingClientRect()
      : blockEl.getBoundingClientRect();
    var hRect    = handleEl.getBoundingClientRect();

    var x1 = bRect.right;
    var y1 = bRect.top + bRect.height / 2;
    var x2 = hRect.left;
    var y2 = hRect.top + hRect.height / 2;

    /* Clamp connector y-coordinates so the line stays visible on screen. */
    var vh = window.innerHeight;
    y1 = Math.max(0, Math.min(y1, vh));
    y2 = Math.max(0, Math.min(y2, vh));

    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("aria-hidden", "true");
    svg.style.cssText =
      "position:fixed;top:0;left:0;width:100%;height:100%;" +
      "pointer-events:none;z-index:998;overflow:visible";

    var line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", x1);
    line.setAttribute("y1", y1);
    line.setAttribute("x2", x2);
    line.setAttribute("y2", y2);
    line.setAttribute("stroke", "var(--note-accent, var(--primary))");
    line.setAttribute("stroke-width", "1.5");
    line.setAttribute("stroke-dasharray", "4 4");
    line.setAttribute("opacity", "0.55");

    svg.appendChild(line);
    document.body.appendChild(svg);
    svgConnector = svg;
  }

  /* Apply the highlight to the matching block + its cards; dim all others. */
  function applyHighlight(anchorId) {
    if (!anchorId) return;
    var targetBlock = document.querySelector(
      '.lesson-block[data-element-id="' + anchorId + '"]'
    );
    if (!targetBlock) return;

    targetBlock.classList.add("is-highlighted");

    document.querySelectorAll(".lesson-block").forEach(function (block) {
      if (block !== targetBlock) block.classList.add("is-dimmed");
    });

    /* Highlight the handle for this block. */
    var aside = targetBlock.querySelector(".block-notes");
    if (aside) {
      var handle = aside.querySelector(".block-notes__handle");
      if (handle) handle.classList.add("is-highlighted");
    }

    /* Highlight all note cards anchored to this element. */
    document.querySelectorAll(
      '.note-card[data-anchor-element="' + anchorId + '"]'
    ).forEach(function (c) {
      c.classList.add("is-highlighted");
    });

    /* Draw the connector on desktop. */
    if (aside) {
      var h = aside.querySelector(".block-notes__handle");
      if (h) drawConnector(h, targetBlock);
    }
  }

  /* mouseover/mouseout bubble — use them for delegation (mouseenter/mouseleave
     do not bubble so cannot be delegated).                                   */
  document.addEventListener("mouseover", function (e) {
    var target   = e.target;
    if (!target || !target.closest) return;

    var anchorId = getAnchorId(target);
    if (!anchorId) return; /* not a handle or card trigger */
    if (anchorId === currentAnchorId) return; /* no change */

    currentAnchorId = anchorId;
    clearHighlight();
    applyHighlight(anchorId);
  });

  document.addEventListener("mouseout", function (e) {
    var target = e.target;
    if (!target || !target.closest) return;
    /* Only clear when leaving a handle or card. */
    if (!target.closest(".block-notes__handle") &&
        !target.closest(".note-card")) return;

    var relatedTarget = e.relatedTarget;
    if (relatedTarget && relatedTarget.closest) {
      /* Moving to another handle/card — let the mouseover on the new target
         handle the transition.                                               */
      if (relatedTarget.closest(".block-notes__handle") ||
          relatedTarget.closest(".note-card")) return;
    }

    currentAnchorId = null;
    clearHighlight();
  });

  /* focusin/focusout bubble normally — delegation works directly. */
  document.addEventListener("focusin", function (e) {
    var target   = e.target;
    if (!target || !target.closest) return;

    var anchorId = getAnchorId(target);
    if (!anchorId) return;
    if (anchorId === currentAnchorId) return;

    currentAnchorId = anchorId;
    clearHighlight();
    applyHighlight(anchorId);
  });

  document.addEventListener("focusout", function (e) {
    var relatedTarget = e.relatedTarget;
    if (relatedTarget && relatedTarget.closest) {
      if (relatedTarget.closest(".block-notes__handle") ||
          relatedTarget.closest(".note-card")) return;
    }
    currentAnchorId = null;
    clearHighlight();
  });

  /* ── Init ────────────────────────────────────────────────────────────── */
  /* Make existing note cards keyboard-focusable. Handles (<summary>) are
     natively focusable. Cards (<article>) are not — add tabindex.          */
  makeFocusable(document);

})();
