# PWA C2 — web push notifications

Sub-project **C2** of the school hosting model's part C (per-school PWA). It builds on the
C1 service worker (`docs/superpowers/specs/2026-09-29-pwa-c1-installable-app-design.md`,
deployed and device-checked on libli.pl 2026-10-16).

## Intent

Students and teachers can get libli's existing notifications as push notifications on their
phones and computers — the same three kinds the bell and the emails already carry. Nothing new
is authored and no new event triggers a notification. Push is a third delivery channel beside
the in-app row and the email, opted into per device and tunable per kind.

Success: a teacher who turned push on gets "A quiz needs your review" on their phone within
seconds of a student submitting; tapping it opens the review page and the bell no longer shows
it unread. A box without push keys looks and behaves exactly as it does today.

## Owner decisions (VERBATIM — do not reverse in review)

Recorded from the 2026-10-16 brainstorming session; each row is the option Krzysztof chose.

| # | Decision |
|---|---|
| D1 | Scope = option A: push is a third channel for the EXISTING notifications (quiz needs review, quiz graded, enrolled). No new notification reasons; those are separate later projects. Audience: both students and teachers. |
| D2 | Opt-in = option B: a "Push notifications on this device" switch in the user's settings, PLUS a one-line invite in the bell dropdown, shown only where push can work and this device is not subscribed; dismissing it hides it for good on that device. No prompt after install. |
| D3 | Per-kind choice = option A: separate per-kind push switches (Email \| Push columns), independent of the email ones, stored per USER (not per device), default on. |
| D4 | Content = option A: the same wording as the email — headline as title, the email's body line as text, including the student's name for "needs review". Tapping opens the same page the email links to and marks the notification read. |
| D5 | Approach 1: `pywebpush`, sent synchronously in a post-commit callback like the email; no thread, no task queue. Per-box VAPID keys in the env file; without them push is entirely hidden. |
| D6 | Design sections 1–3 (data and sending; browser side; ops, testing, out of scope) approved as presented. |

## Current state (verified 2026-10-16)

- `notifications.services.notify()` creates a `Notification` row and registers
  `transaction.on_commit(lambda: deliver_notification_email(n))`. It returns early when
  `_MUTED` is set (demo provisioning) or recipient == actor.
- `notifications.emails.deliver_notification_email` wraps its whole body in log-and-swallow
  because Django stops running on_commit callbacks at the first one that raises
  (`notify_needs_review` queues one per teacher).
- `notifications.emails.email_content(notification)` returns `(subject, headline, body_line)`
  under the active language; `notification_url(notification)` reverses the target path.
- `NotificationEmailPreference`: OneToOne to user, three booleans named exactly like the
  `Notification.Kind` values; no row = all on.
- `core/views.py:user_settings` validates `UserSettingsForm` and `NotificationEmailForm`
  together and saves both in one atomic block; `templates/core/user_settings.html` renders an
  "Email notifications" section with one switch per kind.
- C1: `/sw.js` is `core.views.service_worker` rendering `templates/core/sw.js`;
  `core/static/core/js/pwa.js` registers it; the `pwa_enabled` context flag is
  `core.pwa.serve_normal()` (`PWA_ENABLED` and not `PWA_KILL_SWITCH`).
- `core/signals.py` already has a `user_logged_out` receiver.
- No task queue exists. No push library is installed.

## 1. Configuration

New settings in `config/settings/base.py`, read from the environment:

| Setting | Env var | Default |
|---|---|---|
| `PUSH_VAPID_PUBLIC_KEY` | `LIBLI_VAPID_PUBLIC_KEY` | `""` |
| `PUSH_VAPID_PRIVATE_KEY` | `LIBLI_VAPID_PRIVATE_KEY` | `""` |
| `PUSH_VAPID_SUBJECT` | `LIBLI_VAPID_SUBJECT` | `""` (a `mailto:` URI) |

`notifications.push.push_configured()` is True only when all three are non-blank, the subject
starts with `mailto:` or `https:` (push services reject any other JWT `sub`), **and**
`core.pwa.serve_normal()` is True. Without the C1 worker (flag off or kill switch on) no device
can display a push, so sending would only spend time. Everything below — sending, endpoints,
template UI, `push.js` — is gated on this single function; when it is False the product is
byte-for-byte today's.

The public key is the base64url-encoded uncompressed P-256 point (the form
`PushManager.subscribe({applicationServerKey})` takes); the private key is its base64url raw
scalar, the form `pywebpush` accepts.

A management command `generate_vapid_keys` prints a fresh pair in exactly those two forms as
`LIBLI_VAPID_PUBLIC_KEY=…` / `LIBLI_VAPID_PRIVATE_KEY=…` lines. It writes nothing.

## 2. Data (one migration, `notifications`)

**`PushSubscription`** — one row per subscribed browser.

| Field | Type | Notes |
|---|---|---|
| `user` | FK → user, `CASCADE`, `related_name="push_subscriptions"` | |
| `endpoint` | `URLField(max_length=1024, unique=True)` | push-service URL; unique across users |
| `p256dh` | `CharField(max_length=128)` | client public key |
| `auth` | `CharField(max_length=64)` | client auth secret |
| `user_agent` | `CharField(max_length=200, blank=True)` | truncated request UA, for diagnostics |
| `created_at` | `DateTimeField(auto_now_add=True)` | |
| `subscribed_at` | `DateTimeField()` | set to `now()` on every subscribe upsert; orders the 5-device cap |
| `last_success_at` | `DateTimeField(null=True, blank=True)` | set after a 2xx from the push service |

**`NotificationPushPreference`** — mirrors `NotificationEmailPreference`: OneToOne to user
(`related_name="notification_push_pref"`), booleans `quiz_needs_review`, `quiz_graded`,
`enrolled`, all `default=True`; no row = all on. A separate model rather than widening the email
one: the email model's name and docstring are email-specific and a rename migration buys
nothing.

Both get a `__str__` like their neighbours. Neither is exported by course transfer (they are
user data, not course content); no FORMAT_VERSION bump.

## 3. Sending

`notify()` registers a second, independent on_commit callback after the email one:

```python
transaction.on_commit(lambda: deliver_notification_email(n))
transaction.on_commit(lambda: deliver_notification_push(n))
```

Both callbacks are individually log-and-swallow, so a failure in either never skips the other
or a later recipient's callbacks. The existing `_MUTED` early return covers push automatically.

`notifications.push.deliver_notification_push(notification)`:

The whole body, steps 1–5, sits inside one `try/except Exception` that logs and swallows (same
reasoning as email; `push_configured()` is inside it too, so nothing in this function can raise
into the on_commit chain):

1. Return if not `push_configured()`.
2. Return if the recipient's push preference for `notification.kind` is off
   (`push_kind_enabled(user, kind)`, same shape as `email_enabled`).
3. Load the recipient's `PushSubscription` rows; return if none.
4. Build the payload under `translation.override(recipient.language or LANGUAGE_CODE)`:
   `subject, headline, body_line = email_content(notification)` →
   `{"title": headline, "body": body_line, "url": reverse("notifications:open", args=[notification.pk]), "tag": f"libli-{notification.pk}", "icon": icon_url}`
   as JSON. The URL is a path; the worker resolves it against its own origin. `icon_url` is
   `get_site_config()["favicon_url"]` when the institution has a favicon override, else
   `static("core/img/favicon/icon-192.png")` (the manifest's 192px default). It travels in the
   PAYLOAD, never in `/sw.js`: the worker's bytes must not depend on the per-process 300 s
   config cache (`core/pwa.py:offline_branding`'s rule), and a payload read at send time picks
   up a branding change within that TTL, which is fine for a notification.
5. For each subscription, its own `try`: `pywebpush.webpush(subscription_info, data,
   vapid_private_key, vapid_claims={"sub": PUSH_VAPID_SUBJECT}, ttl=86400, timeout=5)`.
   The `vapid_claims` dict is built FRESH for every call: `webpush` writes `aud` (from that
   endpoint's origin) and `exp` into the dict it is given, so a shared dict would send later
   subscriptions on a different push service with the wrong `aud` (a silent 403).
   - 2xx → update `last_success_at`.
   - `WebPushException` whose response status is 404 or 410 → delete that subscription row
     (the browser unsubscribed or the subscription expired).
   - Any other exception → log with the subscription pk and notification pk; continue with
     the next subscription.

No retry. A push that fails is lost; the bell row and the email are unaffected.

**Latency bound (accepted under D5, tightened here).** The callbacks run in the triggering
request after commit, so push time adds to that response. Three limits bound it:

1. The per-call `timeout=5` (`requests` applies it to the connect and to each read separately).
2. **At most 5 subscriptions per user** — the subscribe endpoint (§4) deletes that user's oldest
   rows (by `subscribed_at`) beyond five.
3. **A per-request push budget of 10 s.** `notifications.push` keeps a `ContextVar` holding the
   monotonic deadline of the current request's push work; a `request_started` receiver (in
   `notifications/signals.py`, §4) resets it to unset. The first push in a request sets the
   deadline to now + 10 s; before each `webpush` call, if the deadline has passed, every remaining
   push in that request is skipped with ONE warning log line naming how many were skipped. A
   skipped push is lost; the bell row and email are unaffected. Outside a request (management
   commands, shell) the budget is never reset, so a long-running command stops pushing 10 s into
   its push work — accepted: no command today sends notifications in bulk.

Numbers. A "needs review" to 1–3 teachers × 1–2 devices: tens of ms each. The largest fan-out is
bulk group enrolment — `grouping/services.py:add_students_to_group` reaches `notify_enrolled`
once per student, so adding a class of 30 queues 30 push callbacks: with a healthy service
~30 × 1–2 × 100–200 ms ≈ 3–12 s (fresh TLS per call), the budget cutting the tail; with a hung
service the request is held for at most ~10 s + one in-flight call (≤ ~15–20 s), instead of the
unbounded 30 × 5 × 5 s = 750 s. The runbook says a hung push service slows quiz submits, grading
and enrolment by up to that, and that blanking the VAPID keys + recreate turns push off.

### The tap target: `notifications/<pk>/open/`

New GET view `notifications:open`, login required. Looks up `Notification(pk=pk,
recipient=request.user)`. Not found — another user's pk, or the user's own notification since
purged by `notifications/retention.py` (a push can sit in the tray, or be queued up to
`ttl=86400`) — redirects to `notifications:list`, the same response in both cases so there is no
oracle. Found: sets `read_at` if unset, then redirects to `notification_url(n)` or, when that is
None, `notifications:list`.
A GET with a side effect is deliberate: the worker cannot send the CSRF token a POST needs, and
the only effect is marking the viewer's own notification read. A logged-out device gets the
normal login redirect with `next` back to this URL.

## 4. Subscription endpoints

All three are POST, CSRF-protected (called by `push.js` with the cookie token), JSON body,
JSON response. Django's `CsrfViewMiddleware` runs first, so a POST without a valid token gets
its HTML 403 before any of the following; for CSRF-valid requests the checks run in this order: `push_configured()` False → 404; anonymous → 403
`{"ok": false}` (NOT `login_required`'s 302, which `fetch` would follow to an HTML page);
malformed body → 400. `push.js` treats any non-200 as a failure and shows its generic error line
("Couldn't change push notifications. Try again.").

- `notifications/push/subscribe/` — body `{"endpoint", "keys": {"p256dh", "auth"}}`.
  Validate: endpoint is an `https://` URL ≤ 1024 chars whose host is a known push service —
  `PUSH_ENDPOINT_HOSTS` in `notifications/push.py`, matched exactly or as a dot-suffix:
  `fcm.googleapis.com` (Chrome, Edge-on-Android, Samsung), `push.services.mozilla.com`
  (Firefox), `push.apple.com` (Safari/iOS), `notify.windows.com` (Edge on Windows). Any other
  host (an IP literal, an internal name, a server the caller controls) → 400. Without this, any
  logged-in user could make the server POST to an arbitrary host on every notification for them,
  and a host that trickles bytes would hold the triggering request past the timeout. A host the
  device checklist finds missing is added to the constant in a follow-up release; both keys present, base64url, within
  the field lengths. Invalid → 400. `update_or_create(endpoint=…)` setting user, keys and UA,
  so an endpoint already owned by another user MOVES to the current one (a shared computer).
  The upsert's defaults also set `subscribed_at = now()` (a non-auto `DateTimeField` on the
  model, distinct from `created_at`), so a re-subscribed or moved endpoint counts as newest.
  Then delete this user's rows beyond the newest five by `subscribed_at`, **always excluding the
  endpoint just written** (§3 latency bound). A concurrent duplicate insert (double click, two
  tabs) that raises `IntegrityError` is caught and the update retried once.
  Store the endpoint in `request.session["push_endpoint"]`. → `{"ok": true}`.
- `notifications/push/unsubscribe/` — body `{"endpoint"}`. Delete the row only if it belongs to
  the current user (another user's endpoint: no-op, still 200 — no oracle). Remove the session
  key if it matches. → `{"ok": true}`.
- `notifications/push/claim/` — body `{"endpoint"}`. Called by `push.js` on page load when the
  browser is subscribed but the page says the session does not know this endpoint (§6).
  If a row with that endpoint belongs to the current user → store it in
  `request.session["push_endpoint"]`, → `{"mine": true}`. Otherwise (no row, or another user's
  row) → delete any row with that endpoint (the browser is about to unsubscribe it, so it is dead
  for everyone) and → `{"mine": false}`. It never creates a row: a browser subscription is never
  silently attached to a user who did not turn push on. Deleting another user's row here, while
  `unsubscribe` refuses to, is deliberate: an endpoint is an unguessable capability URL that only
  the browser holding it can present, and that browser is about to unsubscribe it, so the row
  can never deliver again. `unsubscribe` is a user-initiated action and keeps the stricter rule.

### Logout

A new `user_logged_out` receiver in a new `notifications/signals.py`, connected by a new
`NotificationsConfig.ready()` that imports it (today `notifications/apps.py` has no `ready()`,
and `core`'s receivers connect only because `CoreConfig.ready()` imports `core.signals`). It is a
no-op when `user` is None or the session lacks `push_endpoint`; otherwise
delete the subscription with that endpoint **and** that user. Django sends the signal before it
flushes the session, so the key is still readable. Because `claim` (above) writes the key on the
first page load of every session in which the browser is subscribed, the key is present even
when the subscription was made in an earlier session. The browser side also unsubscribes (§6).
Net effect: after an explicit logout nothing of that user's arrives on that device, and the next
person to log in on it sees push off (§6's claim step unsubscribes a leftover browser
subscription that is not theirs).

**Accepted gap — a session that ends WITHOUT logout.** When a session expires or the browser is
closed without logging out (common on shared school computers), no signal fires: the device keeps
receiving that user's pushes (including student names in "needs review", D4) until that user
turns push off, or someone else logs in on the same browser profile and loads a page (the claim
step then deletes the row). No mitigation is built (a server-side session-expiry sweep cannot
know which browser holds which endpoint beyond the session table, and `ttl` only limits queued
delivery). The settings help under the device switch says: "On a shared computer, log out when
you finish, or leave this off." — a new msgid.

## 5. Service worker additions (`templates/core/sw.js`)

Inside the existing `{% verbatim %}` block:

- `push` — parse `event.data.json()`. A payload that fails to parse shows nothing and returns;
  under `userVisibleOnly: true` the browser may then show its own generic "site updated in the
  background" notice, which is accepted because the server's payloads always parse.
  `event.waitUntil(self.registration.showNotification(title, {body, tag, icon, data:
  {url}}))`, every value taken from the payload (§3 step 4). No `badge` (no monochrome asset
  exists; Android falls back to its default glyph). `core.views.service_worker` gains NO new
  value slot, so `/sw.js` bytes and `worker_version()` are unaffected by branding.
- `notificationclick` — close the notification; resolve `data.url` against
  `self.location.origin`, refusing anything off-origin; then
  inside `event.waitUntil`, `clients.matchAll({type: "window"})` (controlled clients only —
  `WindowClient.navigate()` rejects for a client this worker does not control): focus the first
  and `navigate()` it to the URL; if there is none, or `focus()`/`navigate()` rejects or
  `navigate()` resolves null, fall back to `clients.openWindow(url)`.

The kill worker (C1) gains no push handlers: killing the worker silences push on that device,
which is the intended effect. `pushsubscriptionchange` is not handled (out of scope; a lost
subscription is fixed by turning the switch on again).

## 6. Push client (`core/static/core/js/push.js`)

Loaded on every authenticated page only when `push_configured()` (a context flag
`push_available`). The page carries `<meta name="libli-push" data-vapid-key="…"
data-session-endpoint="…">`, the latter being `request.session.get("push_endpoint", "")`.
It exposes the device state, evaluated **in this order, first match wins**:

| # | State | Condition |
|---|---|---|
| 1 | `ios-not-installed` | iOS/iPadOS (UA matches `iPhone\|iPad\|iPod`, OR `navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1` for iPadOS's desktop UA) AND not standalone (`display-mode: standalone` false and `navigator.standalone !== true`). First because iOS Safari outside the installed app has no `PushManager` and would otherwise read as `unsupported`. |
| 2 | `unsupported` | no `serviceWorker`, `PushManager` or `Notification` |
| 3 | `blocked` | `Notification.permission === "denied"` (wins over a leftover subscription) |
| 4 | `on` | `registration.pushManager.getSubscription()` is non-null (after the claim step below) |
| 5 | `off` | otherwise |

**Claim step (on load).** It runs BEFORE the state table, in every state where a
subscription can be read (including `blocked`: a denied permission still leaves
`getSubscription()` readable, and a leftover row must still be claimed or deleted). When a browser subscription exists and its endpoint differs from
`data-session-endpoint`, `push.js` POSTs it to `push/claim/` (§4) before reporting a state:
`{"mine": true}` → `on`; `{"mine": false}` → `subscription.unsubscribe()` and `off`. A failed
claim request reports `on` and retries on the next page load. This is what makes the session
know the endpoint for logout, and what turns a previous user's leftover subscription off for the
next user.

`subscribe()` (from a click only): `Notification.requestPermission()` → on `"granted"`,
`pushManager.subscribe({userVisibleOnly: true, applicationServerKey})` → POST to the subscribe
endpoint. `unsubscribe()`: POST to the unsubscribe endpoint, then `subscription.unsubscribe()`.
If the subscribe POST fails after `pushManager.subscribe()` succeeded, `subscribe()` calls
`subscription.unsubscribe()` before reporting, so the browser never holds a subscription the
server does not know. If `subscription.unsubscribe()` fails after the unsubscribe POST
succeeded, the leftover is handled by the claim step. After any action, success or failure,
`push.js` re-runs the FULL on-load evaluation (claim step included) against an in-memory session
endpoint it updates after each successful subscribe/unsubscribe, and shows a short error line on
failure.

On submit of the logout form (`templates/base.html`'s form gains `data-logout-form`; allauth's
own logout confirmation page at a GET of `account_logout` lacks it, which is accepted — the
server receiver still runs there),
`push.js` calls `subscription.unsubscribe()` best-effort (it does not delay or block the logout;
the server-side receiver in §4 is the guarantee, this only tidies the browser).

The one remaining mismatch: the server row deleted after a 410/404 while the browser still
believes it is subscribed reads `on`; turning the switch off then on fixes it. No further
background re-sync (YAGNI).

## 7. Settings page

The "Email notifications" section becomes **"Notifications"** when `push_available`; otherwise
it is unchanged (same heading, same copy, email switches only).

With push:

- First row: **"Push notifications on this device"** with a switch driven by `push.js`, acting
  immediately (not part of the form, no "Save changes"). It sits inside the settings `<form>`
  visually, so it is a checkbox with **no `name`** (never submitted) and no `<button>` is used
  for it (a button would submit the form). It is server-rendered **unchecked and disabled**;
  push.js enables it only once it has reported a state (claim step included), and disables it
  again while a request is in flight. For the
  states where it cannot work, the switch is replaced by one line: `unsupported` → "This browser can't show push notifications.";
  `ios-not-installed` → "On iPhone and iPad, add libli to your Home Screen first." + a link to the
  C1 install guide (`{% url 'core:install_app' %}`); `blocked` → "Notifications are blocked for libli in this browser's settings."
- Then one row per kind with **two switches, Email and Push**, column headers above them. The
  push switches are a `NotificationPushForm` (three booleans, `instance=pref`, unsaved instance
  on GET exactly like the email form) saved in the same atomic block. It is built, validated and
  saved ONLY when `push_configured()` is True; otherwise it is not bound to `request.POST` at all
  and an existing preference row is left untouched (the missing checkboxes would otherwise read
  as False and switch every push kind off on a dark box or under the kill switch). Help texts become neutral
  ("When a quiz I submitted is graded.", "When I'm enrolled in a course.", "When a student's quiz
  needs my review.") — new msgids, Polish filled by hand.
- The per-kind Push switches show whatever the user's preference is even when this device is off
  (they are per user, D3).

The lede is reworded to say email and push are chosen separately and the bell always shows
everything.

## 8. Bell invite (`notifications/_bell_panel.html`)

A `hidden` row at the top of the panel, rendered only when `push_available`:
"Get notifications on this device — **Turn on** · ×". `push.js` unhides it only when the state
is `off` and the localStorage flag `libli:push-invite-dismissed` is not set (every storage access
in try/catch; storage failing = show it). On iOS this means it appears only inside the installed
app. **Turn on** runs `subscribe()`; on success the row hides. **×** sets the flag and hides it.
The row is the same for empty and non-empty panels.

## 8a. Strings and localization

push.js builds NO user-facing text. The repo has no JS gettext catalog; its convention is
server-rendered `{% trans %}` text (e.g. `data-msg-*` attributes in
`templates/courses/manage/builder.html`). So:

- Every device-state line (§7: unsupported, iOS-not-installed with its link, blocked), the
  shared-computer help line (§4), and the whole bell invite row (§8) are server-rendered with
  `{% trans %}` inside elements that start `hidden`; push.js only toggles `hidden`.
- The one dynamic string, the error line ("Couldn't change push notifications. Try again."), is
  carried as `data-msg-error` on the `libli-push` meta and placed with `textContent`.
- Push payload text is localized server-side (§3 step 4), so the worker builds no text either.

All of these, plus the §7 section heading, column headers, lede and neutral help texts, are new
msgids with Polish filled by hand (0 fuzzy).

## 9. Operations

- **Dependency:** `pywebpush` (brings `cryptography`, `http-ece`, `requests`, `py-vapid`).
  `uv.lock` changes and a migration ships: this is a migration release, eligible for B2
  rehearsal step 7 (`docs/deployment.md` §9).
- **Ships dark:** a box without the three env vars behaves as today.
- **Runbook:** a new `docs/deployment.md` §9 subsection "Push notifications":
  1. `manage.sh generate_vapid_keys` on the box (or anywhere) → two lines.
  2. Add both lines plus `LIBLI_VAPID_SUBJECT=mailto:<contact>` (the `mailto:` prefix is
     required) to `.env.production` (same
     guarded append pattern as the PWA kill switch).
  3. Recreate the app container (never `restart`; ~24 s maintenance page).
  4. Smoke test: turn push on on a phone; have a teacher account grade one of that account's
     submissions; the push arrives, tapping opens the results page, the bell shows it read.
  5. Note: a hung push service slows the requests that trigger notifications (quiz submit,
     grading, enrolment) by up to the §3 bound; to turn push off, blank the three VAPID vars and
     recreate the app container.
- **Key rules (in the runbook):** keys are per box — never copy them between schools; never
  rotate a key in use (every existing subscription silently stops working; users must turn push
  on again). The restore runbook gains a line: the VAPID keys come back with `.env.production`,
  not with the database.
- **Device checklist on libli.pl** after merge (in the PR body): Android Chrome, iPhone/iPad
  home-screen app, desktop Chrome/Edge — subscribe from settings, subscribe from the bell
  invite, receive each kind, tap-through marks read, per-kind push off suppresses, logout stops
  delivery, kill switch silences.

## 10. Testing

Unit (pytest, `pywebpush.webpush` mocked — we test our decisions, not the crypto):

- `push_configured()` truth table (each key blank, subject without `mailto:`/`https:`, PWA off,
  kill switch on).
- Delivery: not configured / kind off / no subscriptions → no call; muted → no call; each
  language → payload title/body equal `email_content`'s headline/body_line; URL is
  `notifications:open`; `tag` is `libli-<pk>`. Push ignores the email gates: a recipient with a
  blank email still gets a push, and email-off + push-on still pushes.
- Two subscriptions on different push-service hosts: each mocked `webpush` call receives its
  own `vapid_claims` dict object (mutant: one dict hoisted out of the loop).
- 404 and 410 delete only that subscription; another error logs and the NEXT subscription is
  still sent; `last_success_at` set on success.
- Payload `icon`: the override URL when set, the static 192px icon otherwise; `/sw.js` bytes
  identical with and without a favicon override (guards §5's no-new-slot rule).
- Independence — every test runs the callbacks with `captureOnCommitCallbacks(execute=True)`
  and names its mutant:
  - email raising still pushes (mutant: email's log-and-swallow removed; email is registered
    first, so this is the guard that the email failure does not stop the push callback);
  - push's swallow (mutant: the `try` narrowed so `push_configured()` or the preference lookup
    sits outside it): `notify_needs_review` to two teachers where the FIRST teacher's push
    path raises — the SECOND teacher's email and push both still go. ("Push raising still
    emails" for a single recipient is vacuous — that email already ran — and is not used.)
- Device cap: a sixth subscribe deletes that user's oldest row and no other user's; a user with
  five newer rows re-subscribing an OLDER endpoint keeps it (mutant: cap ordered by `created_at`
  or not excluding the current endpoint); a concurrent-insert `IntegrityError` retries as an
  update and returns 200.
- Endpoints (the 404 and anonymous cases send a valid CSRF token — the default test client, or
  `enforce_csrf_checks=True` with a token — else they would see the middleware's 403): 404 when
  not configured (checked before auth); anonymous → 403 JSON, not 302;
  CSRF required; validation 400s; upsert moves an endpoint between users; unsubscribe of another
  user's endpoint deletes nothing; session key set and cleared.
- Claim: own row → `mine: true` and session key set; another user's row → deleted, `mine:
  false`; no row → `mine: false`, nothing created.
- Logout receiver, driven through a real POST to `account_logout` (not by calling the function,
  so a receiver that is never connected fails the test): deletes the session's row and only that
  user's; no-op with no session key;
  no-op with `user=None`; a subscription made in an EARLIER session is deleted once a claim has
  run in the current one.
- `notifications:open`: marks read, redirects to the target, falls back to the list when the
  target cannot be reversed; another user's pk and a missing pk both redirect to the list with
  identical responses and mark nothing; idempotent on a read notification; an anonymous GET
  redirects to login with `next=` the open URL and marks nothing (mutant: `login_required`
  dropped).
- Endpoint host allowlist: each listed host and a subdomain of it accepted; an IP literal,
  `localhost`, `fcm.googleapis.com.evil.example` and `evilfcm.googleapis.com` → 400.
- Push budget: with a mocked clock, pushes after the deadline are skipped with one warning and
  not sent; a `request_started` resets it so the next request pushes again (mutant: no reset).
- Settings: push switches saved with the form, unsaved pref on GET, section unchanged (no push
  markup) when not configured; with push NOT configured, a settings POST leaves an existing push
  preference row with `False` values unchanged and creates none; bell invite absent when not configured.
- `generate_vapid_keys` output decodes to a valid P-256 pair (public 65 bytes, private 32).
- Migration: `makemigrations --check` clean; the new migration depends on the current graph head.

e2e (Playwright Chromium):

- Settings device switch and bell invite against a stubbed `PushManager` /
  `Notification.permission` (init script): `off → on` POSTs the subscription; `on → off` POSTs
  unsubscribe; `blocked` and `ios-not-installed` show their lines; dismiss persists across a
  reload. The `ios-not-installed` case stubs an iPhone UA WITH `PushManager` and `Notification`
  deleted (as real iOS Safari outside the app), and an iPadOS case (`MacIntel` +
  `maxTouchPoints = 5`); both must show the install line, not "can't show push".
- Subscribe POST returning 500: the browser subscription is rolled back and the switch reads off.
- The device switch is disabled until push.js reports a state (a held claim response keeps it
  disabled), and enabled after.
- Every state line and the bell row render in Polish under `pl` (server-rendered, not JS).
- `notificationclick` with only an uncontrolled window open falls back to `openWindow` (or the
  helper test, if the CDP route is unworkable).
- `blocked` with a leftover subscription whose endpoint the server reports `mine: false`: the
  claim still runs and the row is deleted; the state reads blocked.
- Claim on load: a stubbed subscription whose endpoint the server reports `mine: false` is
  unsubscribed and the switch reads off; `mine: true` reads on.
- Worker: with `context.grant_permissions(["notifications"])`, deliver a push through CDP
  `ServiceWorker.deliverPushMessage` (origin + registration id from
  `ServiceWorker.workerRegistrationUpdated`) with a JSON payload, and assert
  `registration.getNotifications()` returns the title/body/tag; if the CDP route proves
  unworkable, the worker exposes its handlers as named functions and the test calls them in the
  worker context instead (record which in the plan); drive `notificationclick` where Playwright allows it, else cover
  the URL-resolution helper (off-origin refusal) directly.
- Real delivery through FCM / Mozilla / Apple push services is NOT automatable — covered by the
  device checklist.

Every new guard is falsified against a named mutant (shown RED), as usual.

## Out of scope

New notification reasons (deadlines, announcements, new lesson published); quiet hours; a device
list with remove buttons; `pushsubscriptionchange` re-sync; a task queue or background thread;
batching or grouping pushes; push for anonymous users.
