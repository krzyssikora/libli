{# libli kill worker (spec §3): served whenever the worker must go away. #}
{% verbatim %}
// LIBLI_SW_KILL -- the runbook's curl check greps for this marker; only this file carries it.
"use strict";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key.startsWith("libli-")).map((key) => caches.delete(key))))
      .then(() => self.registration.unregister())
  );
});
{% endverbatim %}
