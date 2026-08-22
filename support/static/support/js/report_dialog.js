(function () {
  "use strict";

  var dialog = document.getElementById("report-dialog");
  var trigger = document.querySelector("[data-report-trigger]");
  if (!dialog || !trigger) return;

  var form = dialog.querySelector("[data-report-form]");
  var banner = dialog.querySelector("[data-report-banner]");
  var description = dialog.querySelector("[data-report-description]");
  var counter = dialog.querySelector("[data-report-counter]");
  var fileInput = dialog.querySelector("[data-report-file]");
  var preview = dialog.querySelector("[data-report-preview]");
  var maxLength = parseInt(description.getAttribute("maxlength"), 10);
  // Translated strings come from the server, never from JS literals.
  var strings = dialog.querySelector("[data-msg-generic]");
  function msg(key) { return strings.getAttribute("data-msg-" + key); }

  // image/* -> extension. NOT blob.type.split("/")[1], which yields "svg+xml"
  // and "x-icon" — filenames that fail the extension validator with the very
  // error the re-wrap exists to prevent.
  var MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp"
  };

  function collect() {
    var values = {
      page_url: window.location.href,
      page_title: document.title,
      viewport_w: String(window.innerWidth),
      viewport_h: String(window.innerHeight),
      screen_w: String(window.screen ? window.screen.width : ""),
      screen_h: String(window.screen ? window.screen.height : ""),
      dpr: String(window.devicePixelRatio || 1),
      theme: document.documentElement.getAttribute("data-theme") || "",
      ui_language: document.documentElement.getAttribute("lang") || "",
      timezone: ""
    };
    try {
      values.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
    } catch (e) { /* older engines: leave blank, the server drops it */ }
    Object.keys(values).forEach(function (key) {
      var input = form.querySelector('[data-tel="' + key + '"]');
      if (input) input.value = values[key];
    });
    preview.innerHTML = "";
    Object.keys(values).forEach(function (key) {
      if (!values[key]) return;
      var dt = document.createElement("dt");
      dt.textContent = key;
      var dd = document.createElement("dd");
      dd.textContent = values[key];
      preview.appendChild(dt);
      preview.appendChild(dd);
    });
  }

  function clearErrors() {
    banner.hidden = true;
    banner.textContent = "";
    dialog.querySelectorAll("[data-error-for]").forEach(function (node) {
      node.hidden = true;
      node.textContent = "";
    });
  }

  function showBanner(text) {
    banner.textContent = text;
    banner.hidden = false;
  }

  function updateCounter() {
    counter.textContent = description.value.length + " / " + maxLength;
  }

  trigger.addEventListener("click", function (event) {
    event.preventDefault();
    clearErrors();
    collect();          // re-read on EVERY open: the user may have resized
    updateCounter();
    dialog.showModal();
  });

  dialog.querySelector("[data-report-cancel]").addEventListener("click", function () {
    dialog.close();
  });

  description.addEventListener("input", updateCounter);

  // Paste to attach. getAsFile() returns a browser-dependent name that is often
  // extensionless or "blob", and FileExtensionValidator parses the filename — so
  // the blob is re-wrapped with a MIME-derived extension.
  dialog.addEventListener("paste", function (event) {
    var items = (event.clipboardData || {}).items || [];
    for (var i = 0; i < items.length; i += 1) {
      if (items[i].kind !== "file") continue;
      var blob = items[i].getAsFile();
      if (!blob) continue;
      var ext = MIME_EXT[blob.type];
      if (!ext) {
        showBanner(msg("badimage"));
        return;
      }
      var file = new File([blob], "screenshot." + ext, { type: blob.type });
      var transfer = new DataTransfer();
      transfer.items.add(file);
      fileInput.files = transfer.files;
      event.preventDefault();
      return;
    }
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    clearErrors();
    fetch(form.action, {
      method: "POST",
      body: new FormData(form),          // carries the CSRF token
      headers: { "X-Requested-With": "XMLHttpRequest" }
    }).then(function (response) {
      var type = response.headers.get("content-type") || "";
      // Check Content-Type BEFORE parsing: Django's CSRF failure view returns a
      // 403 with an HTML body, and a 500 or a 405 is not JSON either.
      if (type.indexOf("application/json") === -1) {
        showBanner(msg("generic"));
        return null;
      }
      return response.json().then(function (payload) {
        return { status: response.status, payload: payload };
      });
    }).then(function (result) {
      if (!result) return;
      if (result.status === 201) {
        showBanner(result.payload.message);
        window.setTimeout(function () {
          form.reset();
          fileInput.value = "";     // reset() alone can leave a picked file
          dialog.close();
          clearErrors();
        }, 1500);
        return;
      }
      if (result.payload.errors) {
        Object.keys(result.payload.errors).forEach(function (field) {
          var node = dialog.querySelector('[data-error-for="' + field + '"]');
          var text = result.payload.errors[field].join(" ");
          if (node) {
            node.textContent = text;
            node.hidden = false;
          } else {
            // __all__ and any unknown key go to the banner — otherwise a
            // Form.clean() error is returned and silently dropped.
            showBanner(text);
          }
        });
      }
      if (result.payload.message) showBanner(result.payload.message);
      if (result.status === 401) {
        // The spec's 401 row: "Show message, OFFER A LINK TO LOG IN; never
        // navigate away silently." A banner alone strands a user whose session
        // expired with a typed description still in the dialog.
        var link = document.createElement("a");
        link.href = strings.getAttribute("data-login-url");
        link.textContent = msg("login");
        banner.appendChild(document.createTextNode(" "));
        banner.appendChild(link);
      }
    }).catch(function () {
      showBanner(msg("generic"));
    });
  });
})();
