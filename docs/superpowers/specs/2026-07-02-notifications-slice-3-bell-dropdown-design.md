# Notifications Slice 3 — Bell Dropdown — Design

*Drafted 2026-07-02. Third notifications slice, following Slice 1 (event
notifications + in-app list, PR #61) and Slice 2 (email delivery, PR #62). This
slice adds the in-app **bell dropdown** in the nav — the surface the
`recent_for(user, limit)` service was built and reserved to feed.*

Companion docs: [`roadmap.md`](../../roadmap.md) (Deferred → Notifications row),
`2026-07-01-notifications-slice-1-design.md`,
`2026-07-02-notifications-slice-2-email-delivery-design.md`.

---

## Goal

A header-cluster **bell** icon carrying the unread badge opens a dropdown of the
user's most recent notifications. Clicking a notification navigates to its target
**and** marks it read (badge drops on the next page load). A "Mark all read"
action and a "See all →" link to the full `/notifications/` list round it out.
The text "Notifications" nav link is removed — the bell becomes the single entry
point.

This is a **read/surface** slice: it reuses the entire Slice-1/2 substrate. **No
new model, no migration, no new view.**

---

## What already exists (reused verbatim)

- `notifications.services.recent_for(user, limit)` — returns
  `Notification.objects.filter(recipient=user)[:limit]` (respects the model's
  default `-created_at, -id` ordering). Built + tested in Slice 1, reserved for
  exactly this dropdown.
- `notifications.services.unread_count(user)` — feeds the badge.
- `notifications.services.notification_url(n)` — reverses a row's target URL from
  denormalized `data` (pure `reverse()`, no DB load; `None` when unresolvable).
- `notifications.views.mark_read(request, pk)` — `@require_POST`, marks one row
  read (idempotent), redirects to the list. **Reused as the click-through
  target of a fire-and-forget `fetch`.**
- `notifications.views.mark_all_read(request)` — `@require_POST`, bulk-marks,
  redirects to the list.
- `core.context_processors.notifications_badge` — currently exposes
  `notifications_unread` for authenticated users, `{}` for anonymous.
- The `.menu` component (`base.html` + `core/js/ui.js`): a `.menu` wrapper owns a
  `[data-menu-trigger]` + `[data-menu-panel][hidden]` pair; `ui.js` handles
  open/close, "opening one closes others", outside-click, and Escape. Already
  used by the Admin and account menus.
- The theme-toggle `fetch(...POST, {X-CSRFToken})` idiom in `ui.js` — the model
  for the click-marks-read fetch.
- Kind-specific `blocktrans` message rendering + `.notif-row--unread` styling in
  `notifications/templates/notifications/list.html`.

---

## Design

### 1. Placement & markup (`base.html`)

A bell `.menu` is added to `.app-header__cluster`, between the theme-toggle
button and the account-menu avatar. It renders **only for authenticated users**
(inside the existing `{% if user.is_authenticated %}` block).

```
<div class="menu bell" data-bell-menu>
  <button class="btn--icon bell__trigger" type="button" data-menu-trigger
    aria-haspopup="true" aria-expanded="false"
    aria-label="{% trans 'Notifications' %}">
    🔔  {# monochrome currentColor SVG per the icons-monochrome-svg convention #}
    {% if notifications_unread %}<span class="nav-badge">{{ notifications_unread }}</span>{% endif %}
  </button>
  <div class="menu__panel notif-menu" data-menu-panel hidden>
    {% include "notifications/_bell_panel.html" %}
  </div>
</div>
```

- The bell icon is a **monochrome `currentColor` line SVG** using the shared
  `.icon` utility (per the `icons-monochrome-svg` convention — never a
  multicolour emoji; the 🔔 above is a placeholder for the spec).
- The unread `.nav-badge` moves from the old nav link onto the bell trigger.
- The text `<a … 'notifications:list'>Notifications</a>` link is **removed** from
  `#primary-nav`. Its only replacement entry point is the bell + the "See all"
  footer.

### 2. Panel partial (`notifications/templates/notifications/_bell_panel.html`)

New partial, rendered inline (server-side, present in the DOM, hidden until
opened — the `.menu` idiom). Structure:

- **Header:** `<h2>`-level "Notifications" title + a "Mark all read" POST form
  (`{% url 'notifications:mark_all_read' %}`, `{% csrf_token %}`), shown only
  when `notifications_unread`.
- **List:** iterate `notifications_recent` (≤ 8 rows). Each row:
  - Whole row is `<a class="notif-menu__row" href="{{ n.url }}"
    data-mark-read-url="{% url 'notifications:mark_read' n.pk %}">` **when
    `n.url` is truthy**; otherwise a non-link `<div>` (no href, no
    data-attribute — nothing to navigate to or mark-through).
  - Unread rows add `notif-menu__row--unread` (dot + tint, mirroring
    `.notif-row--unread`).
  - Body: the same kind branches as `list.html`
    (`quiz_needs_review` / `quiz_graded` / `enrolled`) via `blocktrans` on the
    denormalized `n.data`.
  - Relative time: `{{ n.created_at|timesince }}` + `{% trans "ago" %}`
    (built-in `timesince`; no `humanize` dependency added).
- **Footer:** "See all →" `<a>` to `{% url 'notifications:list' %}`.
- **Empty state** (no `notifications_recent`): "You have no notifications yet."

The partial is standalone (no `{% extends %}`); `list.html` is **not** refactored
to use it — the two surfaces render similar rows but differ enough (pager,
per-row mark-read buttons on the full page) that sharing would couple them
without real payoff. Kept separate deliberately.

### 3. Data (`core.context_processors`)

Extend `notifications_badge` to also expose the recent list:

```python
def notifications_badge(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from notifications.services import notification_url, recent_for, unread_count

    recent = list(recent_for(user, 8))
    for n in recent:
        n.url = notification_url(n)
    return {
        "notifications_unread": unread_count(user),
        "notifications_recent": recent,
    }
```

- Adds **one** indexed query (`recent_for`, covered by the
  `recipient, -created_at` index) per authenticated request, alongside the
  existing `unread_count` query. `notification_url` is pure Python (`reverse()`),
  no extra queries; `data` is denormalized so no `actor`/target joins (no N+1).
- Anonymous branch unchanged (`{}`).
- The `8` cap is a module-level constant (e.g. `BELL_RECENT_LIMIT = 8`) so the
  count has one source of truth.

### 4. Interactions (`core/js/ui.js`)

Click-marks-read via fire-and-forget fetch (reuses the theme-toggle pattern):

- On `click` of any `.notif-menu__row[data-mark-read-url]`, fire
  `fetch(url, {method:"POST", headers:{"X-CSRFToken": getCookie("csrftoken")},
  body: <empty/urlencoded>, credentials:"same-origin", keepalive:true})` and do
  **not** `preventDefault` — the browser follows the `<a href>` to the target.
  `keepalive:true` lets the POST complete after navigation unloads the page.
- No client-side badge math: navigation triggers a fresh page load whose context
  processor recomputes `notifications_unread` (now decremented). "Mark all read"
  is a normal POST-redirect that reloads the list with a fresh badge.
- No-JS fallback: the `.menu` panel only opens via JS, so a no-JS user never sees
  the dropdown — they use the full `/notifications/` list page (unchanged,
  POST-form mark-read). Requiring JS *inside* the dropdown is therefore
  consistent, not a regression.
- Wiring lives in the same IIFE as the existing menu/theme code; it selects rows
  at load (the panel is server-rendered, always in the DOM).

### 5. Styling (`app.css`)

- `.bell` / `.bell__trigger`: icon button matching `.btn--icon`; badge positioned
  top-right of the bell.
- `.notif-menu` panel: right-aligned under the bell (the `.menu__panel` base
  already positions absolutely); `min-width`/`max-width` on desktop; on mobile
  clamp to viewport (`max-width: calc(100vw - <gutter>)`, right-anchored) so it
  never overflows — the bell is in the always-visible cluster, so this works
  without involving the hamburger.
- `.notif-menu__row`: block link, hover state, unread dot + subtle tint; muted
  relative-time; header/footer separators via the existing `.menu__sep` idiom
  where it fits.
- Verified **light + dark** via a throwaway Playwright screenshot harness before
  shipping (per the `verify-ui-with-screenshots` convention; delete-after-review).

### 6. i18n

New/confirmed strings marked for translation, added to EN + PL `.po`, `.mo`
recompiled (`uv run python manage.py compilemessages`; clear stray `fuzzy` flags
and verify PL guesses per the `uv-run-tooling` note):

- "Notifications" (bell `aria-label` / panel title — already present elsewhere)
- "Mark all read" (already exists on the list page)
- "See all" (new)
- "ago" (new; or fold into a `blocktrans` "{{ time }} ago" to keep it natural)
- "You have no notifications yet." (new)

### 7. Scope guardrails

- **No migration, no new model, no new view, no new URL.**
- Badge stays server-computed.
- `recipient == actor` self-suppression, email delivery, and the full list page
  are all untouched.

---

## Testing

- **Context processor:** authenticated request exposes `notifications_recent`
  (list, capped at 8, each with a populated/`None` `.url`) and
  `notifications_unread`; anonymous request exposes neither.
- **Shell render:** bell trigger + `aria-label` present for authed users; unread
  badge shows the count and is absent at zero; the old text "Notifications" nav
  link is gone.
- **Panel:** rows render kind-specific messages + relative time; unread rows get
  the unread class; a row with a resolvable target is an `<a>` carrying
  `href` + `data-mark-read-url`; a row with no resolvable URL is a non-link with
  neither; "Mark all read" present only when there are unread; empty state when
  none.
- **e2e (real Playwright gestures):** open the bell dropdown, click a notification
  row, assert the browser lands on the target page **and** that on reload the
  unread badge has decremented by one (proves the keepalive fetch marked it
  read). Follows the `e2e-must-drive-real-ui` convention — drive the actual click
  path, no `page.evaluate` shortcut.

---

## Out of scope (future slices)

- **Announcements** (announcement → group broadcast) — the still-unbuilt half of
  the Notifications roadmap row.
- **Retention/purge** of read + orphaned rows.
- Real-time push / websockets — the badge is refreshed on navigation only.
- Refactoring `list.html` to share the row partial.
