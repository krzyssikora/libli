{# libli service worker (spec docs/superpowers/specs/2026-09-29-pwa-c1-installable-app-design.md §2). #}
{# Values arrive as JSON from core.views.service_worker; all JS stays inside verbatim. #}
const VERSION = {{ version_json|safe }};
const PRECACHE = {{ precache_json|safe }};
const CACHE_STATIC = {{ cache_static_json|safe }};
const PASSTHROUGH_PREFIXES = {{ prefixes_json|safe }};
const PASSTHROUGH_SUFFIXES = {{ suffixes_json|safe }};
{% verbatim %}
// No "use strict" here: a directive must be a script's FIRST statement, and the
// value slots above come first. Workers are classic scripts, not modules.
const STATIC_CACHE = "libli-static-" + VERSION;
const OFFLINE_CACHE = "libli-offline-" + VERSION;
const OFFLINE_URL = "/offline/";

self.addEventListener("install", (event) => {
  // A failed precache fails the install, and the previous worker stays in charge.
  event.waitUntil(
    caches.open(OFFLINE_CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  const keep = new Set([STATIC_CACHE, OFFLINE_CACHE]);
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key.startsWith("libli-") && !keep.has(key))
          .map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

// Rule 0. Pathname only: the archive download may carry ?confirm=1.
function passthrough(request) {
  if (request.method !== "GET") return true;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return true;
  const path = url.pathname;
  return PASSTHROUGH_PREFIXES.some((prefix) => path.startsWith(prefix)) ||
    PASSTHROUGH_SUFFIXES.some((suffix) => path.endsWith(suffix));
}

function staticFirst(event) {
  const request = event.request;
  // Look up WITHOUT caches.open(): open() CREATES a missing cache, so even a hit
  // served after a newer (or kill) worker deleted this cache would resurrect it
  // as an orphan. Only the miss path opens it, to put.
  return caches.match(request, { cacheName: STATIC_CACHE }).then((hit) => {
    if (hit) return hit;
    return fetch(request).then((response) => {
      // 200 only: a 206 cannot be put, and an error must never be cached.
      if (response.status === 200 && response.type === "basic") {
        const copy = response.clone();
        event.waitUntil(
          caches.open(STATIC_CACHE)
            .then((cache) => cache.put(request, copy))
            .catch(() => {})
        );
      }
      return response;
    });
  });
}

function offlinePage() {
  // By the literal URL, never the navigation request; ignoreVary because the
  // response carries Vary: Cookie, Accept-Language.
  return caches.match(OFFLINE_URL, { cacheName: OFFLINE_CACHE, ignoreVary: true })
    .then((hit) => hit || Response.error());
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (passthrough(request)) return;                                   // rule 0
  const path = new URL(request.url).pathname;
  if (CACHE_STATIC && path.startsWith("/static/")) {                  // rule 1
    event.respondWith(staticFirst(event));
    return;
  }
  if (request.mode === "navigate" && request.destination === "document") {  // rule 2
    // Only a REJECTED fetch (no network) falls back; every HTTP response,
    // including Caddy's 503 maintenance page, passes through unchanged.
    event.respondWith(fetch(request).catch(offlinePage));
  }
  // rule 3: everything else passes.
});
{% endverbatim %}
