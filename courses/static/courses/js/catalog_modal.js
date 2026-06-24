"use strict";
// Progressive enhancement: intercept [data-catalog-detail] links, fetch the
// server fragment with the XHR header, show it in the modal. With JS off the
// link is a normal navigation to the full detail page.
(function () {
  var modal = document.querySelector("[data-catalog-modal]");
  if (!modal) return;
  var body = modal.querySelector("[data-catalog-modal-body]");

  function close() {
    modal.hidden = true;
    body.innerHTML = "";
  }

  document.addEventListener("click", function (e) {
    var link = e.target.closest("[data-catalog-detail]");
    if (link) {
      e.preventDefault();
      fetch(link.href, { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); })
        .then(function (html) {
          body.innerHTML = html;
          modal.hidden = false;
        })
        .catch(function () {
          window.location = link.href;  // degrade to the full detail page on fetch failure
        });
      return;
    }
    if (e.target.closest("[data-catalog-modal-close]") || e.target === modal) {
      close();
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !modal.hidden) close();
  });
})();
