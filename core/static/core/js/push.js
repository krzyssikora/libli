/* PWA C2 push client (spec docs/superpowers/specs/2026-10-16-pwa-c2-web-push-design.md §6-§8).
   Loaded only when push is configured. Builds NO user-facing text: every line is
   server-rendered and hidden; this file toggles `hidden` and fills the one error line
   from data-msg-error. */
(function () {
  "use strict";

  var meta = document.querySelector('meta[name="libli-push"]');
  if (!meta) return;

  var DISMISS_KEY = "libli:push-invite-dismissed";
  var CANNOT = ["unsupported", "not-remembered", "ios-not-installed", "blocked"];
  var sessionEndpoint = meta.getAttribute("data-session-endpoint") || "";
  var busy = false;
  var api = { state: "pending", refresh: refresh };
  window.libliPush = api;

  function getCookie(name) {
    var m = document.cookie.match("(?:^|; )" + name + "=([^;]+)");
    return m ? decodeURIComponent(m[1]) : null;
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken") },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (!r.ok) throw new Error("push request failed: " + r.status);
      return r.json();
    });
  }

  function withTimeout(promise, ms) {
    return new Promise(function (resolve, reject) {
      var t = setTimeout(function () { reject(new Error("timeout")); }, ms);
      promise.then(function (v) { clearTimeout(t); resolve(v); },
                   function (e) { clearTimeout(t); reject(e); });
    });
  }

  function isIos() {
    return /iPhone|iPad|iPod/.test(navigator.userAgent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  }

  function standalone() {
    return window.matchMedia("(display-mode: standalone)").matches ||
      navigator.standalone === true;
  }

  function supported() {
    return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  }

  function registration() {
    var p = window.libliSwRegistration;
    if (!p) return Promise.resolve(undefined);
    return withTimeout(p, 5000).catch(function () { return undefined; });
  }

  function keyBytes(b64) {
    var s = (b64 + "===".slice((b64.length + 3) % 4)).replace(/-/g, "+").replace(/_/g, "/");
    var raw = atob(s), out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  function dismissed() {
    try { return window.localStorage.getItem(DISMISS_KEY) === "1"; } catch (e) { return false; }
  }
  function dismiss() {
    try { window.localStorage.setItem(DISMISS_KEY, "1"); } catch (e) { /* storage off: fine */ }
  }

  // The claim step (spec §6): acts, never reports a state.
  function claim(sub) {
    if (!sub || sub.endpoint === sessionEndpoint) return Promise.resolve();
    return post(meta.getAttribute("data-claim-url"), { endpoint: sub.endpoint })
      .then(function (res) {
        if (res.mine) { sessionEndpoint = sub.endpoint; return; }
        return sub.unsubscribe().catch(function () {});
      })
      .catch(function () { /* retried on the next page load */ });
  }

  function evaluate() {
    if (isIos() && !standalone()) return Promise.resolve({ state: "ios-not-installed" });
    if (!supported()) return Promise.resolve({ state: "unsupported" });
    return registration().then(function (reg) {
      if (!reg) return { state: "unsupported" };
      return reg.pushManager.getSubscription().catch(function () { return null; })
        .then(function (sub) { return claim(sub).then(function () { return reg; }); })
        .then(function (reg2) {
          if (meta.getAttribute("data-remembered") === "0") return { state: "not-remembered", reg: reg2 };
          if (Notification.permission === "denied") return { state: "blocked", reg: reg2 };
          return reg2.pushManager.getSubscription().catch(function () { return null; })
            .then(function (sub) { return { state: sub ? "on" : "off", reg: reg2, sub: sub }; });
        });
    });
  }

  // --- rendering ------------------------------------------------------------------

  function each(selector, fn) {
    [].forEach.call(document.querySelectorAll(selector), fn);
  }

  function showError(scope, on) {
    each(scope + " [data-push-error]", function (el) {
      var msg = on ? meta.getAttribute("data-msg-error") : "";
      el.textContent = msg;
      el.hidden = !on;
    });
  }

  function render(state) {
    api.state = state;
    document.documentElement.setAttribute("data-push-reported", state);
    var cannot = CANNOT.indexOf(state) !== -1;
    each("[data-push-device] [data-push-state]", function (el) {
      el.hidden = el.getAttribute("data-push-state") !== state;
    });
    each("[data-push-switch-wrap]", function (el) { el.hidden = cannot; });
    each("[data-push-help]", function (el) { el.hidden = cannot; });
    each("input[data-push-switch]", function (el) {
      // While a request is in flight keep the user's click visible (Playwright's
      // check() also requires the box to stay as clicked); refresh() settles it.
      if (!busy) el.checked = state === "on";
      el.disabled = cannot || busy;
    });
    each("[data-push-invite]", function (el) {
      el.hidden = !(state === "off" && !dismissed());
    });
  }

  function refresh() {
    // Terminal fallback: any rejection in the evaluation (e.g. a registration with no
    // usable pushManager) must still report a state -- never a disabled switch with
    // no line (spec §10, registration refused).
    return evaluate()
      .catch(function () { return { state: "unsupported" }; })
      .then(function (r) { render(r.state); return r; });
  }

  // --- actions --------------------------------------------------------------------

  function subscribe() {
    return Notification.requestPermission().then(function (perm) {
      if (perm !== "granted") return;
      return withTimeout(navigator.serviceWorker.ready, 10000).then(function (reg) {
        return reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: keyBytes(meta.getAttribute("data-vapid-key"))
        });
      }).then(function (sub) {
        return post(meta.getAttribute("data-subscribe-url"), sub.toJSON())
          .then(function () { sessionEndpoint = sub.endpoint; })
          .catch(function (err) {
            // Never leave the browser holding a subscription the server does not know.
            return sub.unsubscribe().catch(function () {}).then(function () { throw err; });
          });
      });
    });
  }

  function unsubscribe(sub) {
    return post(meta.getAttribute("data-unsubscribe-url"), { endpoint: sub.endpoint })
      .then(function () {
        sessionEndpoint = "";
        return sub.unsubscribe().catch(function () { /* the claim step tidies it */ });
      });
  }

  function act(scope, action) {
    if (busy) return Promise.resolve();
    busy = true;
    render(api.state);
    showError(scope, false);
    // Promise.resolve().then(action): a synchronous throw (e.g. an old Safari whose
    // requestPermission returns undefined) becomes a rejection, so busy always resets.
    return Promise.resolve().then(action)
      .then(function () { return false; }, function () { return true; })
      .then(function (failed) {
        busy = false;
        return refresh()
          .catch(function () { failed = true; })
          .then(function () { showError(scope, failed); });
      });
  }

  document.addEventListener("change", function (e) {
    var box = e.target.closest && e.target.closest("input[data-push-switch]");
    if (!box) return;
    var wantOn = box.checked;
    act("[data-push-device]", function () {
      if (wantOn) return subscribe();
      return registration().then(function (reg) {
        return reg ? reg.pushManager.getSubscription() : null;
      }).then(function (sub) { return sub ? unsubscribe(sub) : null; });
    });
  });

  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-push-invite-on]")) {
      act("[data-push-invite]", subscribe);
    } else if (e.target.closest("[data-push-invite-dismiss]")) {
      dismiss();
      each("[data-push-invite]", function (el) { el.hidden = true; });
    }
  });

  // Logout: tidy the browser BEFORE leaving -- unsubscribe (the push service then drops
  // anything still queued for this device) and close libli's notifications left in the
  // tray (a shared device). Held at most LOGOUT_WAIT_MS, so a hung browser API never
  // blocks logging out; the server's logout receiver remains the guarantee.
  var LOGOUT_WAIT_MS = 1000;
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.matches || !form.matches("form[data-logout-form]")) return;
    e.preventDefault();
    var sent = false;
    function send() {
      if (sent) return;
      sent = true;
      // The prototype's submit() fires no submit event, so this handler never re-runs.
      HTMLFormElement.prototype.submit.call(form);
    }
    setTimeout(send, LOGOUT_WAIT_MS);
    registration().then(function (reg) {
      if (!reg) return null;
      // Each step on its own: a missing API (a throw) must not skip the other.
      return Promise.all([
        Promise.resolve().then(function () {
          return reg.pushManager.getSubscription();
        }).then(function (sub) {
          return sub && sub.unsubscribe();
        }).catch(function () {}),
        Promise.resolve().then(function () {
          return reg.getNotifications();
        }).then(function (list) {
          list.forEach(function (n) { n.close(); });
        }).catch(function () {})
      ]);
    }).catch(function () {}).then(send);
  });

  refresh();
})();
