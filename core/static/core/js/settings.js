// Progressive enhancement for institution settings (no-JS baseline already works):
// grey out default_language segments whose language isn't currently enabled, and
// swap the logo thumbnail when a new file is picked.
(function () {
  "use strict";
  function syncDefaultLang() {
    var enabled = {};
    document.querySelectorAll('input[name="enabled_languages"]').forEach(function (cb) {
      enabled[cb.value] = cb.checked;
    });
    document.querySelectorAll('.seg input[name="default_language"]').forEach(function (r) {
      r.closest("label").style.opacity = enabled[r.value] ? "" : ".45";
    });
  }
  document.querySelectorAll('input[name="enabled_languages"]').forEach(function (cb) {
    cb.addEventListener("change", syncDefaultLang);
  });
  syncDefaultLang();

  var fileInput = document.querySelector('.settings-logo-actions input[type=file]');
  var prev = document.querySelector(".settings-logo-prev");
  if (fileInput && prev) {
    fileInput.addEventListener("change", function () {
      if (fileInput.files && fileInput.files[0]) {
        var url = URL.createObjectURL(fileInput.files[0]);
        prev.innerHTML = '<img src="' + url + '" alt="">';
      }
    });
  }
})();
