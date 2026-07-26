(function () {
  "use strict";
  // Progressive enhancement: [data-zoomable] images become click/Enter/Space triggers
  // that open ONE reused modal <dialog> holding a copy of the image, fitted to the
  // viewport and never upscaled (courses.css does the sizing -- no JS measurement).
  // With this script absent the images stay plain, non-interactive <img> elements.

  // Feature-detect on a throwaway element: the real dialog is created lazily on first
  // open, so there is nothing to probe yet. Returning here also leaves
  // window.libliInitImageZoom unexported, which editor.js's `&&` guard tolerates --
  // and means no image is ever made to look clickable when clicking cannot work.
  if (typeof document.createElement("dialog").showModal !== "function") return;

  function label(key, fallback) {
    // Read defensively: a page that ships the script without the i18n blob must not
    // throw, it must fall back.
    var blob = window.IMAGEZOOM_I18N || {};
    return blob[key] || fallback;
  }

  function trimmedAlt(img) {
    return (img.getAttribute("alt") || "").trim();
  }

  var dialog = null;
  var dialogImg = null;
  var trigger = null;

  function build() {
    dialog = document.createElement("dialog");
    dialog.className = "imgzoom";
    // The dialog is named for the CONTROL, always the generic string -- never the
    // image's alt, which the contained <img> already carries. Naming both would make a
    // screen reader read the description twice on entry.
    dialog.setAttribute("aria-label", label("dialog", "Enlarged image"));

    dialogImg = document.createElement("img");
    dialogImg.className = "imgzoom__img";
    dialog.appendChild(dialogImg);

    // Any click inside the overlay closes it, the image included. A double-click on a
    // trigger therefore opens then closes (the second click lands on the dialog, which
    // now sits under the cursor) -- that is the accepted behaviour, not a bug.
    dialog.addEventListener("click", function () {
      dialog.close();
    });

    dialog.addEventListener("close", function () {
      // removeAttribute, NOT src = "": an empty src resolves against the document URL
      // and makes the browser refetch the current HTML page as an image every close.
      dialogImg.removeAttribute("src");
      if (trigger) trigger.focus();
      document.documentElement.classList.remove("imgzoom-open");
    });

    document.body.appendChild(dialog);
  }

  function openOverlay(img) {
    if (!dialog) build();
    if (dialog.open) return; // showModal() on an open dialog throws InvalidStateError
    trigger = img;
    dialogImg.src = img.currentSrc || img.src; // already fetched: served from cache
    dialogImg.alt = trimmedAlt(img); // whitespace-only alt must not read as content
    dialog.showModal();
    // Explicit lock, not belt-and-braces: showModal() does NOT block wheel input over
    // the backdrop from scrolling the page behind it (measured: window.scrollY moved
    // 0 -> 400 under a wheel event with the overlay open and no lock). courses.css pairs
    // this class with `overflow: hidden` on <html>.
    document.documentElement.classList.add("imgzoom-open");
  }

  function armOne(img) {
    if (img.dataset.imgzoomReady === "1") return; // idempotent: the editor re-arms
    img.dataset.imgzoomReady = "1";
    img.setAttribute("role", "button");
    img.setAttribute("tabindex", "0");
    img.classList.add("imgzoom-trigger");
    // A trimmed-empty alt means the author declared the image decorative: name the
    // CONTROL so it is never a nameless button, and leave the image itself silent.
    if (!trimmedAlt(img)) {
      img.setAttribute("aria-label", label("enlarge", "Enlarge image"));
    }
  }

  function armAll(root) {
    var scope = root || document;
    // Arm `scope` itself when it matches, for parity with gallery.js's initGallery:
    // this is a public hook a caller may point straight at an image.
    if (scope.matches && scope.matches("[data-zoomable]")) armOne(scope);
    Array.prototype.forEach.call(scope.querySelectorAll("[data-zoomable]"), armOne);
  }

  // Two delegated listeners rather than N per image, so the click path does not depend
  // on the arming pass: an image in the DOM but not yet armed still zooms.
  document.addEventListener("click", function (e) {
    var img = e.target.closest && e.target.closest("[data-zoomable]");
    if (!img) return;
    // Defence in depth for a future container that nests an image in a <summary> or
    // <label>. It does NOT suppress image drag or text selection -- those start at
    // mousedown, long before click -- and no such suppression is wanted.
    e.preventDefault();
    openOverlay(img);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var img = e.target.closest && e.target.closest("[data-zoomable]");
    if (!img) return;
    e.preventDefault(); // Space would scroll the page
    openOverlay(img); // auto-repeat is harmless: later events hit the dialog.open guard
  });

  // Escape must close ONLY the overlay. unit_nav.js registers its drawer handler as
  // `document.addEventListener("keydown", onKeydown, true)` -- CAPTURE phase, on
  // document -- so it fires on the way down, before any listener on the dialog could
  // run: one Escape would close the overlay AND the drawer. Registering ours at boot,
  // also capture, also on document, puts it earlier in registration order, and
  // stopImmediatePropagation is what stops a same-node/same-phase peer. Never
  // preventDefault: that would suppress the dialog's own close request.
  document.addEventListener(
    "keydown",
    function (e) {
      if (e.key === "Escape" && dialog && dialog.open) e.stopImmediatePropagation();
    },
    true
  );

  window.libliInitImageZoom = armAll;
  armAll(document);
})();
