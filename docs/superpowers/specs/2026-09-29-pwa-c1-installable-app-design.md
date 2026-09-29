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
- `test.py`: pin `PWA_ENABLED = False` and `PWA_KILL_SWITCH = False` (pinned, not
  inherited, for the same reason as `VENDOR_INSTANCE`: `base.py` reads a developer's
  `.env`). Tests opt in with `override_settings`.
- A context processor exposes `pwa_enabled` = `PWA_ENABLED and not PWA_KILL_SWITCH`.

### 2. `/sw.js` — the worker, rendered by a view

- Route `path("sw.js", views.service_worker, name="service_worker")` in `core/urls.py`
  (root path ⇒ default scope `/`; no `Service-Worker-Allowed` header needed).
- Public (no login). `Content-Type: text/javascript; charset=utf-8`,
  `Cache-Control: no-cache`.
- Rendered from `templates/core/sw.js` with two values:
  - **`VERSION`**: the first 12 hex chars of a SHA-256 over, in order: the staticfiles
    manifest's bytes (read through the storage; the literal `"nomanifest"` when the
    storage has none, as in dev and tests), the SOURCE of `core/sw.js` and
    `core/offline.html` templates, and the site-config fields the offline page renders
    (`name`, `primary`). Computed per request (cheap; the manifest bytes may be cached at
    process level since they cannot change without a restart). Any static change, worker
    or offline-page template change, or rename/recolour yields a new worker, and browsers
    update on their next navigation. No deploy change is needed.
  - **`PRECACHE`**: `["/offline/"]`. The offline page is self-contained (§4), so nothing
    else is needed.
- Cache names: `libli-static-<VERSION>` and `libli-offline-<VERSION>`. Every libli cache
  starts with `libli-`.
- **install**: open `libli-offline-<VERSION>`, `add("/offline/")`, then `skipWaiting()`.
  If the precache fetch fails, install fails and the previous worker stays in charge.
- **activate**: delete every cache whose name starts with `libli-` and is not one of the
  two current names; then `clients.claim()`.
- **fetch** — only `GET` and same-origin requests are considered; for anything else the
  handler returns without calling `respondWith` (browser default):
  1. `/static/…`: cache-first from `libli-static-<VERSION>`; on a miss, fetch, and store
     the response only if `response.ok` and `response.type === "basic"`. Safe even for an
     unhashed `/static/` URL, because `VERSION` covers the whole manifest: any change to
     any static file retires the entire cache.
  2. `request.mode === "navigate"`: `fetch(request)`; **only** when the fetch rejects
     (a network failure) respond with the cached `/offline/`. Every HTTP response —
     503 maintenance, 404, 500, a redirect to login — passes through unchanged.
  3. Everything else — `/media/` (keeps HTTP Range for video seeking; GBs of media never
     enter the cache), `/sw.js`, `/site.webmanifest`, JSON/fragment endpoints — is not
     intercepted.
- No user data ever enters a cache (static assets and an anonymous page only), so logout
  clears nothing.

### 3. Kill switch

- With `PWA_KILL_SWITCH` on, `/sw.js` serves a different body: on `install`,
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
  page never shows a broken image). Shows the school's `name`.
- Copy (EN + PL): heading "You're offline", line "Check your connection and try again.",
  a **Try again** button (`location.reload()`); an `online` event listener reloads too.
  A small inline script is allowed; the page loads nothing external.
- Language: the UI language active when the worker installs. Accepted: after a language
  switch the offline page follows at the next worker update.

### 5. Manifest and head tags

- `webmanifest` adds `"id": "/"`, `"scope": "/"`, `"lang": cfg["default_language"]`,
  and `"description"`: a new short msgid `_("Lessons and courses from your school")`
  (EN + PL). Existing fields and icons unchanged.
- `{% favicon_links %}` adds `<meta name="apple-mobile-web-app-title" content="<short
  name>">` (the same `_short_name` the manifest uses) and
  `<meta name="mobile-web-app-capable" content="yes">`.

### 6. `pwa.js`

`core/static/core/js/pwa.js`, included from `base.html` with `defer` only when
`pwa_enabled`.

- If `"serviceWorker" in navigator`: `navigator.serviceWorker.register("/sw.js",
  {scope: "/", updateViaCache: "none"})`, errors logged to the console and otherwise
  ignored (the site works without a worker).
- Install item (§7): on `beforeinstallprompt`, `preventDefault()`, keep the event, and
  switch the item to prompt mode. On click in prompt mode, call `event.prompt()`, then
  drop the event (it is single-use) and return the item to link mode. On `appinstalled`,
  hide the item.
- Standalone detection: `matchMedia("(display-mode: standalone)").matches ||
  navigator.standalone === true` ⇒ hide the item.

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

**Django-client tests**
- `/sw.js`: anonymous 200, `text/javascript`, `no-cache`; body contains the `VERSION` and
  `/offline/`. `VERSION` changes when (a) the manifest bytes change (patched storage),
  (b) the institution name changes, (c) the primary colour changes — and is stable across
  two requests with nothing changed.
- Kill switch on: body contains `unregister` and no `respondWith`; `pwa.js` absent from a
  rendered page. `PWA_ENABLED` off: `pwa.js` absent. On: present.
- `/offline/`: anonymous 200, `no-store`, `noindex`; fetched as a logged-in user the
  response contains neither the username, the email nor the bell markup; it references no
  `/static/` URL.
- Manifest: `id`, `scope`, `lang` (follows `default_language`), `description`.
- Head tags on a rendered page: `apple-mobile-web-app-title`, `mobile-web-app-capable`.
- Account menu: the `data-install-app` link points at `/install-app/`.
- `/install-app/`: anonymous 200 in EN and PL; footer link present on a public page.
- Any existing test that iterates `PAGES` must stay green with the new page (check the
  overrides-panel and content-guard tests).

**Playwright e2e** (`-m e2e`, Chromium, `override_settings(PWA_ENABLED=True)`), each
syncing on conditions, never sleeps:
1. The worker registers and controls the page (`navigator.serviceWorker.controller`);
   a reload's static response reports `from_service_worker`.
2. Offline: `context.set_offline(True)` → navigate → offline page text; back online →
   Try again → the real page.
3. A 404 URL while controlled shows the real 404 page, not the offline page.
4. A `/media/` response is never `from_service_worker`.
5. Update: rename the institution → navigate → a new worker controls the page and
   `caches.keys()` holds only the new `VERSION`'s names.
6. Kill switch: turn it on → navigate → `getRegistrations()` is empty and no `libli-`
   cache remains.
7. Install item: a synthetic `beforeinstallprompt` (with a stub `prompt`) switches it to
   prompt mode and a click calls the stub; with `matchMedia` stubbed to standalone via an
   init script, the item is hidden.

Each guard gets a mutant shown RED: navigations served from cache; the `navigate`
fallback on any non-ok response (a 503 becomes the offline page); `/media/` cached; the
activate cleanup removed; `VERSION` made constant; `respondWith` left in the kill body;
the offline page extending `base.html`.

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
