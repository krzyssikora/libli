// Drag-and-drop enhancement for the import upload form. Progressive: the native
// <input type="file"> keeps working (and stays `required`) with JS disabled; this
// only adds drag/drop and a selected-filename readout on top of it.
(function () {
  "use strict";

  function wire(zone) {
    var input = zone.querySelector("[data-dropzone-input]");
    var nameEl = zone.querySelector("[data-dropzone-name]");
    if (!input) return;

    function showName() {
      if (nameEl) nameEl.textContent = input.files.length ? input.files[0].name : "";
    }
    input.addEventListener("change", showName);
    showName();

    ["dragenter", "dragover"].forEach(function (evt) {
      zone.addEventListener(evt, function (e) {
        e.preventDefault();
        zone.classList.add("is-over");
      });
    });
    ["dragleave", "dragend", "drop"].forEach(function (evt) {
      zone.addEventListener(evt, function (e) {
        e.preventDefault();
        zone.classList.remove("is-over");
      });
    });
    zone.addEventListener("drop", function (e) {
      var files = e.dataTransfer && e.dataTransfer.files;
      if (files && files.length) {
        // Assign the dropped FileList to the input so a normal form submit carries it.
        input.files = files;
        showName();
      }
    });
  }

  document.querySelectorAll("[data-dropzone]").forEach(wire);
})();
