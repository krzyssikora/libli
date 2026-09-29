# PWA C1 — installable app, service worker, offline page

Sub-project **C1** of the school hosting model's part C (per-school PWA). C2 (web push)
builds on this worker and gets its own spec. Real offline use (reading lessons without a
connection) is out of scope for both.

## Intent

A school's pupils and teachers can install libli as an app — on Android, iPhone/iPad and
desktop Chrome/Edge — carrying the school's name and icon, launching full-screen, and
showing a friendly offline page instead of the browser's error when the connection drops.
Static assets load from a local cache so launches are quick on poor school Wi-Fi. A
release must never leave anyone looking at stale pages, and a misbehaving worker must be
recallable from every device.

Priority order given by Krzysztof: installability and branding, then push (C2), then
speed, then offline use (not built).

## Owner decisions (VERBATIM — do not reverse in review)

| # | Decision |
|---|---|
| D1 | Split: C1 = installability + service worker with static cache + offline page; C2 = push notifications on top of the C1 worker. Offline lesson reading is out of scope. |
| D2 | C1 includes the offline page. |
| D3 | Install discovery = option C: an "Install app" item in the account menu (native prompt where the browser supports it) plus a help page. No banner, no auto-prompt. |
| D4 | Approach 1: a hand-written worker served by a Django view. No Workbox, no build step. |
| D5 | The install guide is a PUBLIC page (anonymous, like `/privacy/`), because the staff-only Help never reaches pupils. |
| D6 | Pages (HTML) and `/media/` are never cached by the worker. |
| D7 | Worker off in dev and in the test suite by default; on in production. |
| D8 | Kill switch via an environment variable. |

## Current state (verified 2026-09-29)

- `/site.webmanifest` is a view (`core/views.py:webmanifest`): `name`, `short_name`,
  `start_url: "/"`, `display: "standalone"`, `background_color`, `theme_color`
  (`effective_primary`), icons 192/512/maskable-512 or the institution's favicon override.
- `{% favicon_links %}` (`core/templatetags/branding.py`) emits the icon links,
  `apple-touch-icon`, `<link rel="manifest">` and `<meta name="theme-color">` into
  `base.html`.
- libli registers **no** service worker today.
- Production static storage is `whitenoise.storage.CompressedManifestStaticFilesStorage`
  (hashed names, `staticfiles.json`); `config/settings/local.py` and
  `config/settings/test.py` override it with the plain `StaticFilesStorage`.
- The container does not know its release sha (only compose's `LIBLI_IMAGE_TAG` does).
- Caddy serves `/media/` directly and answers **503** (`maintenance.html`) while the app
  restarts on a deploy.
- In-app Help (`/help/`) is `login_required` and role-gated to staff; pupils never see it.
  Public pages (`core/public_pages.py:PAGES`) are anonymous, localized markdown under
  `docs/public/`, with optional per-language admin override rows.

## Design

### 1. Settings

- `base.py`: `PWA_ENABLED = env.bool("LIBLI_PWA_ENABLED", default=False)` and
  `PWA_KILL_SWITCH = env.bool("LIBLI_PWA_KILL_SWITCH", default=False)`.
- `production.py`: `PWA_ENABLED = env.bool("LIBLI_PWA_ENABLED", default=True)`.
- `base.py`: `PWA_CACHE_UNHASHED_STATIC = False` (not read from the environment; a
  test-only override, see §2 `CACHE_STATIC`).
- `test.py`: pin `PWA_ENABLED = False` and `PWA_KILL_SWITCH = False` (pinned, not
  inherited, for the same reason as `VENDOR_INSTANCE`: `base.py` reads a developer's
  `.env`). Tests opt in with `override_settings`.
- A context processor exposes `pwa_enabled` = `PWA_ENABLED and not PWA_KILL_SWITCH`.
- What `/sw.js` serves, for every combination (always HTTP 200 — a 404 would make the
  browser keep whatever worker it already has, forever):

  | `PWA_ENABLED` | `PWA_KILL_SWITCH` | `/sw.js` body | `pwa.js` included |
  |---|---|---|---|
  | on | off | normal worker (§2) | yes |
  | on | on | kill worker (§3) | no |
  | off | off | kill worker (§3) | no |
  | off | on | kill worker (§3) | no |

  So "off" is not merely "stop registering": it also removes the worker from any device
  that already has one. The kill switch exists separately so an operator can recall the
  worker on a production box without touching `LIBLI_PWA_ENABLED`.
- Module `core/pwa.py` holds the logic: `worker_version()` (VERSION, §2),
  `_manifest_bytes()` (memoised with `functools.lru_cache(maxsize=1)`; tests that patch
  the storage call `_manifest_bytes.cache_clear()` through a fixture), `serve_normal()`
  (the first row of the table), `offline_branding()` (§4), `cache_static()` (§2) and the
  passthrough constants of §2. "The storage has a manifest" is decided in ONE place:
  `_manifest_bytes()` returns the manifest file's bytes when the configured staticfiles
  storage has a `manifest_name` attribute and that file exists in the storage, else
  `b"nomanifest"`; `cache_static()` is `_manifest_bytes() != b"nomanifest" or
  settings.PWA_CACHE_UNHASHED_STATIC`.

### 2. `/sw.js` — the worker, rendered by a view

- Route `path("sw.js", views.service_worker, name="service_worker")` in `core/urls.py`
  (root path ⇒ default scope `/`; no `Service-Worker-Allowed` header needed).
- Public (no login). `Content-Type: text/javascript; charset=utf-8`,
  `Cache-Control: no-cache`.
- Rendered from `templates/core/sw.js` (the kill body from `templates/core/sw_kill.js`).
  The JS body of each template sits inside `{% verbatim %}` blocks; only the value slots
  are outside them, so a `{#`, `{{` or `{%` in worker code can never be eaten by the
  template engine.
  Every value below reaches the JS as a `json.dumps(...)` string computed in the view and
  emitted with `|safe` (autoescape would otherwise turn `"` into `&quot;` and a Python
  `True` is not JS). A client test asserts the body contains `["/media/"]` verbatim.
  Values:
  - **`VERSION`** = `core.pwa.worker_version()`: the first 12 hex chars of a SHA-256
    over, in order: `_manifest_bytes()` (the staticfiles manifest read through the
    storage; the literal `b"nomanifest"` when the storage has none, as in dev and tests;
    memoised per process because it cannot change without a restart), the SOURCE of the
    `core/sw.js` and `core/offline.html` templates, and the two values
    `offline_branding()` returns (§4). Computed per request otherwise.
    `offline_branding()` reads the database directly —
    `Institution.objects.filter(pk=1).prefetch_related("brand_colors").first()`, the
    primary colour being the `brand_colors` row with key `primary` passed through
    `_safe_color` and then `effective_primary({"primary": value})`; a missing row yields
    `(default_name(), PRIMARY_DEFAULT)`. It must NEVER call `Institution.load()` (that is
    `get_or_create`: a database write on an anonymous GET). It deliberately bypasses
    `get_site_config()`: that cache is per-process LocMem with a 300 s TTL and is
    invalidated only in the process that saved, so after a rename different gunicorn
    workers would serve different `/sw.js` bytes for up to 5 minutes and a device could
    flip v2 → v1 → v2, each activate deleting the other's caches. `/sw.js` is fetched once
    per navigation at most, so the query is cheap. Any static change,
    worker or offline-page template change, or rename/recolour yields a new worker, and
    browsers update on their next navigation. No deploy change is needed.
    `core/offline.html` must not `{% include %}` or `{% extends %}` anything, or a change
    in the included file would not move VERSION (a test asserts it). Accepted: a release
    that changes ONLY the offline page's translations leaves devices on the old wording
    until the next VERSION change.
  - **`PRECACHE`**: `["/offline/"]`. The offline page is self-contained (§4), so nothing
    else is needed.
  - **`CACHE_STATIC`** = `core.pwa.cache_static()`: true iff the static storage has a
    manifest (production), or `settings.PWA_CACHE_UNHASHED_STATIC` is true (default
    False; only the e2e tests set it). Without a manifest, VERSION does not track static content, so caching `/static/`
    would freeze a developer's JS/CSS edits — exactly the stale-worker trap. With
    `CACHE_STATIC` false, rule 1 below is skipped and `/static/` goes to the network.
  - **`PASSTHROUGH_PREFIXES`** = `["/media/"]` and **`PASSTHROUGH_SUFFIXES`** =
    `["/export/"]` (constants in `core/pwa.py`): paths the worker never touches, not even
    as navigations. `/export/` covers the course and subtree archive downloads
    (`courses:manage_course_export`, `courses:manage_node_export`), GET navigations of up
    to ~1 GiB that must not be streamed through the worker.
- Cache names: `libli-static-<VERSION>` and `libli-offline-<VERSION>`. Every libli cache
  starts with `libli-`.
- **install**: open `libli-offline-<VERSION>`, `add("/offline/")`, then `skipWaiting()`.
  If the precache fetch fails, install fails and the previous worker stays in charge.
- **activate**: delete every cache whose name starts with `libli-` and is not one of the
  two current names; then `clients.claim()`.
- **fetch** — evaluated in this order; "pass" means the handler returns without calling
  `respondWith` (browser default):
  0. Not `GET`, not same-origin, path starts with a `PASSTHROUGH_PREFIXES` entry, or ends
     with a `PASSTHROUGH_SUFFIXES` entry → pass. This runs BEFORE the navigate rule, so a
     `/media/` URL opened in a tab (an image, a PDF, a video) and an archive download are
     never intercepted either. `/media/` passthrough keeps HTTP Range working for video
     seeking and keeps GBs of media out of the cache.
  1. `CACHE_STATIC` and path starts with `/static/`: cache-first from
     `libli-static-<VERSION>`; on a miss, fetch and return the response, and store a
     clone only if `response.status === 200` and `response.type === "basic"` (a 206
     cannot be `put`). The `put` is fire-and-forget (`event.waitUntil`), its rejection
     caught and ignored. In production this is safe even for an unhashed `/static/` URL,
     because `VERSION` covers the whole manifest: any change to any static file retires
     the entire cache.
  2. `request.mode === "navigate"` and `request.destination === "document"` (top-level
     only — a same-origin iframe that fails offline shows the browser's own frame error,
     not a full offline page inside the frame): `fetch(request)`; **only** when the fetch rejects
     (a network failure) respond with
     `caches.match("/offline/", {cacheName: "libli-offline-<VERSION>", ignoreVary: true})`
     — matched by the literal `/offline/` URL, never by the navigation request (whose URL
     differs), and with `ignoreVary` because the response carries `Vary: Cookie,
     Accept-Language`. If that match is empty, `Response.error()`. Every HTTP response —
     503 maintenance, 404, 500, a redirect to login — passes through unchanged.
  3. Everything else (`/sw.js`, `/site.webmanifest`, JSON/fragment endpoints, `/static/`
     when `CACHE_STATIC` is false) → pass.
- No user data ever enters a cache (static assets and an anonymous page only), so logout
  clears nothing.

### 3. Kill switch

- Whenever the table in §1 says so, `/sw.js` serves `templates/core/sw_kill.js`: on `install`,
  `skipWaiting()`; on `activate`, delete every cache whose name starts with `libli-`, then
  `self.registration.unregister()`. No fetch handler.
- `pwa.js` is not included while the switch is on (via `pwa_enabled`), so nothing
  re-registers.
- Every browser revalidates `/sw.js` on navigation (`no-cache` + `updateViaCache:
  "none"`), so the switch reaches every device on its next visit. Undo: unset the var and
  restart the stack.
- Runbook (`docs/deployment.md`) gains a short "PWA kill switch" section;
  `.env.production.example` gains `LIBLI_PWA_KILL_SWITCH=` (blank) with a one-line comment.

### 4. `/offline/`

- Route `path("offline/", views.offline, name="offline")`. Public, `Cache-Control:
  no-store`, `X-Robots-Tag: noindex`.
- Template `templates/core/offline.html` is **standalone** (like `500.html`), NOT
  `base.html`: no nav, no user name, no bell, no static files. The page is rendered for
  whoever fetches it but stored and shown to whoever uses the device, so it must not
  depend on the request's user at all.
- Inline CSS with light/dark via `prefers-color-scheme`; the default libli mark inlined as
  SVG (the favicon override lives under `/media/`, which the worker never caches, so the
  page never shows a broken image). Renders exactly the two values of
  `core.pwa.offline_branding()`: the name (`(name or "").strip()` or `default_name()`,
  the manifest's fallback) as the heading's context line, and the effective primary as
  the Try again button's BORDER only. The button is outlined: its label uses the page's
  own text colour (light and dark variants), so contrast is AA whatever colour a school
  picked — there is no on-primary contrast helper to reuse. No
  other institution field appears, so VERSION tracks everything the page shows.
- Copy (EN + PL): heading "You're offline", line "Check your connection and try again.",
  a **Try again** button (`location.reload()`); an `online` event listener reloads too.
  A small inline script is allowed; the page loads nothing external.
- Language: the UI language active when the worker installs. Accepted: after a language
  switch the offline page follows at the next worker update.

### 5. Manifest and head tags

- `webmanifest` adds `"id": "/"`, `"scope": "/"`, `"lang": cfg["default_language"]`,
  and `"description"`: a new short msgid `_("Lessons and courses from your school")`
  (EN + PL), rendered inside `translation.override(cfg["default_language"])` so it is
  always in the language `lang` declares, whatever the requesting session's language.
  Existing fields and icons unchanged.
- `{% favicon_links %}` adds `<meta name="apple-mobile-web-app-title" content="<short
  name>">` (the same `_short_name` the manifest uses) and
  `<meta name="mobile-web-app-capable" content="yes">`.

### 6. `pwa.js`

`core/static/core/js/pwa.js`, included from `base.html` with `defer` only when
`pwa_enabled`.

- Registration runs first and independently of the install item. Every install-item
  handler returns immediately when `[data-install-app]` is absent (anonymous, login and
  public pages render no account menu), so no page throws.
- If `"serviceWorker" in navigator`: `navigator.serviceWorker.register("/sw.js",
  {scope: "/", updateViaCache: "none"})`, errors logged to the console and otherwise
  ignored (the site works without a worker).
- Install item (§7): on `beforeinstallprompt`, `preventDefault()`, keep the event, and
  switch the item to prompt mode. On click in prompt mode, call `event.prompt()`, then
  drop the event (it is single-use) and return the item to link mode. On `appinstalled`,
  hide the item.
- Standalone detection: `matchMedia("(display-mode: standalone)").matches ||
  navigator.standalone === true` ⇒ hide the item.
- "Hide" means setting the `hidden` attribute AND a new `app.css` rule
  `.menu__item[hidden] { display: none; }`: `.menu__item { display: block }`
  (`app.css:291`) otherwise beats the UA `[hidden]` rule and the item stays visible —
  the same reason `app.css` already re-asserts `[hidden]` for four other components.
- Accepted: Chrome may fire `beforeinstallprompt` before the deferred `pwa.js` attaches
  its listener. The item then stays in link mode, which is a working path (the guide), so
  no early inline listener is added.

### 7. "Install app" in the account menu

- In `base.html`'s account menu, after Settings:
  `<a class="menu__item" href="{% url 'core:install_app' %}" data-install-app>`
  `{% trans "Install app" %}</a>`.
- Link mode (default, no-JS, iOS Safari, Firefox): navigates to the guide.
- Prompt mode (`pwa.js`, §6): same label; the click calls `preventDefault()` and opens the
  browser's install dialog.
- Hidden when running installed.
- Rendered regardless of `pwa_enabled` (the guide is useful even with the worker off —
  Chrome and iOS install without one). Accepted consequence: with `pwa.js` absent (worker
  off or kill switch on) the item cannot hide itself inside an installed app and stays a
  plain link to the guide.

### 8. `/install-app/` — the install guide

- New entry in `PAGES`: slug `install-app`, path `public/install-app.md`, title
  `_("Install the app")`, description `_("How to add libli to your phone, tablet or
  computer as an app.")`. View `views_public.install_app`, route
  `path("install-app/", …, name="install_app")`. Not in `DEMO_NOTICE_SLUGS`, not in
  `VENDOR_ONLY_SLUGS` — so it appears in the platform admin's public-page overrides panel
  like the others.
- `docs/public/install-app.md` + `install-app.pl.md`, text only. Sections: Android
  (Chrome menu → Install app / Add to Home screen), iPhone and iPad (Safari Share → Add to
  Home Screen), computer (install icon in Chrome/Edge's address bar), Good to know (on
  iPhone/iPad you log in once more inside the app; lessons still need a connection; how to
  remove the app).
- Linked from: the account menu (§7), `_public_footer.html` (after Help), the
  `getting-started` page (a sentence + link, EN + PL; boxes with an override row for that
  page keep their override), and the top of the staff Help index (`help/index.html`).

## Testing

`PWA_ENABLED` is off in the suite (§1), so existing tests never run under a worker.

**Django-client tests** (each names the settings it runs under)
- `/sw.js`, under `override_settings(PWA_ENABLED=True, PWA_KILL_SWITCH=False)`:
  anonymous 200, `text/javascript`, `no-cache`; the body contains
  `core.pwa.worker_version()`'s value and `/offline/`. `worker_version()` changes when
  (a) the manifest bytes change (patched storage + `_manifest_bytes.cache_clear()`
  fixture), (b) the institution name changes, (c) the `BrandColor` row with key
  `primary` changes — and is stable across two calls with nothing changed. With no
  `Institution` row, `offline_branding()` returns `(default_name(), PRIMARY_DEFAULT)` and
  creates no row.
- `/sw.js` for the other three rows of the §1 table (each row its own case): 200, the
  body contains `unregister`, `caches.delete` and `libli-`, and no `respondWith`; a
  rendered page has no `pwa.js`. First row: a rendered page includes `pwa.js`.
- `CACHE_STATIC`: false under the suite's plain storage; true with
  `PWA_CACHE_UNHASHED_STATIC=True`; true with a storage that reports a manifest.
- Passthrough: `reverse("courses:manage_course_export", …)` and
  `reverse("courses:manage_node_export", …)` each end with a `PASSTHROUGH_SUFFIXES`
  entry, and `settings.MEDIA_URL` starts with a `PASSTHROUGH_PREFIXES` entry — so renaming
  a route cannot silently route a GB download through the worker.
- `core/offline.html` source contains neither `{% include` nor `{% extends`.
- `offline_branding()` reads the database, not the cache: warm `get_site_config()`, then
  rename with a SIGNAL-FREE write (`Institution.objects.filter(pk=1).update(name=…)`,
  and likewise a `BrandColor` queryset `update`) so the cache really is stale — a
  `.save()` would fire the `post_save` invalidation in-process and the test could not
  fail. `offline_branding()` and `/offline/` show the new values.
- An anonymous page (the login page) renders with `pwa_enabled` and no account menu; the
  e2e suite's anonymous visit in e2e 3 asserts no console error from `pwa.js`.
- `/offline/`: anonymous 200, `no-store`, `noindex`; fetched as a logged-in user the
  response contains neither the username, the email nor the bell markup; it references no
  `/static/` URL.
- Manifest: `id`, `scope`, `lang` (follows `default_language`), `description` in
  `default_language` even when the request's session language differs.
- Head tags on a rendered page: `apple-mobile-web-app-title`, `mobile-web-app-capable`.
- Account menu: the `data-install-app` link points at `/install-app/`.
- `/install-app/`: anonymous 200 in EN and PL; footer link present on a public page.
- Any existing test that iterates `PAGES` must stay green with the new page (check the
  overrides-panel and content-guard tests).

**Playwright e2e** (`-m e2e`, Chromium, `override_settings(PWA_ENABLED=True,
PWA_CACHE_UNHASHED_STATIC=True)`), each syncing on conditions, never sleeps. Every test
first waits until `navigator.serviceWorker.controller` is non-null (reloading once after
registration if needed):
1. Static is really cached, not merely passed through `respondWith`: after a reload,
   poll (with a timeout — the `put` is fire-and-forget) until
   `caches.open("libli-static-<worker_version()>")` → `match(<a /static/ URL the page
   loaded>)` is non-empty (`from_service_worker` alone is true for any `respondWith`, so it
   is not the assertion).
2. Offline, two recovery paths tested separately (either handler deleted turns exactly
   one red):
   a. `context.set_offline(True)` → navigate → offline page text → `set_offline(False)`
      with NO click → wait for the real page (covers the `online` listener).
   b. Outage emulated by a `context.route` abort → navigate → offline page text →
      `unroute` (fires no `online` event) → click Try again → the real page (covers the
      button).
   **Spike first** (the plan's first e2e task). Try, in order: (i) Playwright with
   `PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS=1` (service-worker routing and network
   events in Chromium are gated behind it); (ii) `Network.emulateNetworkConditions`
   (offline) through a CDP session attached to the service-worker target; (iii) stopping
   the live server's listener for the offline window. If none makes the worker's own
   fetch reject, STOP and ask Krzysztof whether e2e 2 and its mutants move to the manual
   device checklist; do not ship a test that cannot fail. Within the working option,
   confirm on the pinned Chromium that
   `set_offline` fails fetches made from INSIDE the worker, and find a `context.route`
   filter that catches the worker's inner fetch. That fetch is a new Request whose mode
   is not `navigate`, so the filter keys on the target URL path (plus
   `resource_type == "document"` only if the spike shows it holds for worker-originated
   fetches), never on `is_navigation_request()`. If `set_offline` does not reach the
   worker, case (a) also uses the route abort and fires `online` by
   `set_offline(True)`/`set_offline(False)` around the unroute.
3. A 404 URL while controlled shows the real 404 page, not the offline page. Also, an
   anonymous visit to the login page while controlled logs no console error.
4. `/media/` passthrough, as both a subresource and a navigation: load a real in-scope
   page on the live server whose markup contains an `<img src="/media/…">` — a published
   lesson with an image element built by the existing factories (never `page.set_content`,
   whose `about:blank` document is not controlled by the worker) and then navigate the tab to a `/media/…` URL. The test
   settings have `DEBUG=False`, so Django answers 404 — which is fine, because the
   property is interception, not content: each observed `/media/` response must have
   `from_service_worker == False`, and the test asserts that at least one subresource and
   one navigation response WERE observed (so it cannot pass over zero responses).
5. Update: rename the institution → navigate → poll until
   `navigator.serviceWorker.controller` is non-null and `caches.keys()` holds only names
   ending in the new `worker_version()` (both already-true-safe conditions; never wait for
   a `controllerchange` event attached after load, which may already have fired).
6. Kill switch: turn it on → navigate → poll until `getRegistrations()` is empty and no
   `libli-` cache remains.
7. Install item — every assertion made with the account menu OPEN and a sibling item
   ("Settings") asserted visible first, since a closed `.menu__panel` hides everything
   and would make a hidden-check vacuous:
   a. A synthetic `beforeinstallprompt` (stub `prompt`) switches it to prompt mode; a
      click calls the stub once and stays on the page; a second click navigates to
      `/install-app/` (the event is single-use).
   b. A synthetic `appinstalled` hides it (`to_be_hidden()`).
   c. With `matchMedia` stubbed to standalone via an init script, it is hidden on load.

Each guard gets a mutant shown RED, with the test that turns red named in the plan:
rule 1 made network-only or its `put` removed (e2e 1); the `online` listener or the Try again handler removed (e2e 2a / 2b); navigations served from cache; the navigate fallback on any non-ok response (a 503
becomes the offline page); the offline match done by the navigation request instead of
`"/offline/"`; `/media/` cached; the passthrough check moved after the navigate rule;
the `status === 200`/`basic` store guard removed; the GET-only/same-origin filter removed;
the activate cleanup removed; `offline_branding()` reading `get_site_config()` (the
signal-free rename test); the kept prompt event not dropped after use (e2e 7a); `VERSION` made constant; `respondWith` left in the kill
body; the offline page extending `base.html`; the `.menu__item[hidden]` rule removed.

**Manual device checklist** (Krzysztof, on real devices, before the PR merges):
Android Chrome install; iPhone Safari install (name and icon right); desktop Chrome/Edge
install; airplane mode → offline page; iOS standalone back-navigation walk (a unit, a
quiz, settings — any dead end is written down, not fixed in this PR); SSO login inside
the installed app; uninstall.

## Rollout

libli.pl gets it first (canary) on merge; school boxes through a normal *Deploy release*.
No migration, no new dependency, no `deploy.sh` change.

## Risks

- **A broken worker stuck on devices** → the kill switch (§3); and a fixed release reaches
  every device on its next visit because `/sw.js` is never cached.
- **Cache growth** → only static files actually fetched; old versions deleted on activate;
  media never cached.
- **Stale pages** → impossible by construction: pages are never cached.
- **Dev confusion** → the worker is off in dev; the stale-worker trap on `127.0.0.1:8000`
  stays a foreign-project problem.

## Out of scope

Push notifications (C2); offline lesson reading; install screenshots in the guide;
`theme-color` per light/dark theme; any iOS back-navigation fixes the checklist finds.
