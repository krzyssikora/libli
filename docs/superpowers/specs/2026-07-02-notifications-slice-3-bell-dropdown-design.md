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
**and** marks it read (the badge reflects that on a subsequent page load — the
mark-read POST races navigation; see §4). A "Mark all read" action and a
"See all →" link to the full `/notifications/` list round it out. The text
"Notifications" nav link is removed; the **bell trigger is itself an `<a>` linking
to `/notifications/`**, progressively enhanced into a dropdown when JS is present.
It is thus the single entry point while still giving no-JS users a working link to
the full list.

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
  redirects to the list. Reused **verbatim**: the bell's "Mark all read" therefore
  lands the user on `/notifications/` (all rows now read) as a confirmation view —
  a deliberate, accepted context switch, not an oversight (see §2). `mark_read` is
  likewise reused verbatim (its redirect target is irrelevant — the bell fires it
  via fetch and ignores the response).
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
  <a class="btn--icon bell__trigger" href="{% url 'notifications:list' %}"
    role="button" data-menu-trigger aria-haspopup="true" aria-expanded="false"
    aria-label="{% trans 'Notifications' %}">
    <svg class="icon" ...>…bell…</svg>  {# monochrome currentColor line SVG, see below #}
    {% if notifications_unread %}<span class="nav-badge">{% if notifications_unread > 99 %}99+{% else %}{{ notifications_unread }}{% endif %}</span>{% endif %}
  </a>
  <div class="menu__panel notif-menu" data-menu-panel hidden>
    {% include "notifications/_bell_panel.html" %}
  </div>
</div>
```

- **The trigger is an `<a href="…list">`, not a `<button>`** (C1 fix): with no JS
  it navigates to the full list; with JS, `ui.js` intercepts the click
  (`preventDefault`) and toggles the panel instead (see §4). `role="button"` +
  `aria-haspopup`/`aria-expanded` keep the enhanced semantics.
- The bell icon is a **monochrome `currentColor` line SVG** with the shared
  `.icon` class (per the `icons-monochrome-svg` convention — never a multicolour
  emoji). Mirror the inline-`<svg class="icon">` markup already used in
  `notes/templates/notes/_outline_badge.html`; the plan supplies the actual bell
  path data (a simple bell outline). The header's existing text glyphs
  (`◐`/`☰`/`▾`) are pre-existing exceptions, not a pattern to copy.
- The unread `.nav-badge` moves from the old nav link onto the bell trigger, and
  is **capped at `99+`** so a large count can't distort the compact trigger.
- The text `<a … 'notifications:list'>Notifications</a>` link is **removed**. Its
  replacement entry points are the bell trigger (which links to the list) and the
  panel's "See all" footer. **Audit before removing:** grep every
  `notifications:list` link usage — the link may be duplicated in the mobile
  hamburger panel (`#primary-nav` flattens there via `display:contents`), and
  existing tests assert its presence (per the PR #60 lesson: moving/removing a nav
  link breaks tests that clicked/asserted it). Update those tests to target the
  bell instead.

### 2. Panel partial (`notifications/templates/notifications/_bell_panel.html`)

New partial, rendered inline (server-side, present in the DOM, hidden until
opened — the `.menu` idiom). Structure:

- **Header:** `<h2>`-level "Notifications" title + a "Mark all read" POST form
  (`{% url 'notifications:mark_all_read' %}`, `{% csrf_token %}`), shown only
  when `notifications_unread`. Submitting it redirects to `/notifications/` (the
  verbatim `mark_all_read` behaviour) — an accepted confirmation-view jump (I1).
- **List:** iterate `notifications_recent` (≤ 8 rows). Each row:
  - Whole row is `<a class="notif-menu__row" href="{{ n.url }}"
    data-mark-read-url="{% url 'notifications:mark_read' n.pk %}">` **when
    `n.url` is truthy**; otherwise a non-link `<div>` (no href, no
    data-attribute — nothing to navigate to or mark-through).
  - **URL-less rows are not individually clearable from the bell** (I5): they have
    no per-row affordance here. This is deliberate and bounded — such rows only
    arise when `notification_url` can't resolve (missing `data`), and they are
    still cleared by the panel's "Mark all read" or on the full list page (both
    reachable). Documented so the badge-persistence case is a known trade-off, not
    a surprise.
  - Unread rows add `notif-menu__row--unread` (dot + tint, mirroring
    `.notif-row--unread`).
  - Body: the same kind branches as `list.html`
    (`quiz_needs_review` / `quiz_graded` / `enrolled`) via `blocktrans` on the
    denormalized `n.data`.
  - Relative time: rendered as a **single translatable unit** —
    `{% blocktrans with time=n.created_at|timesince %}{{ time }} ago{% endblocktrans %}`
    — so the word order stays translator-controlled (PL and others don't place
    "ago" after the interval). Do **not** concatenate a standalone
    `{% trans "ago" %}` (I4). Built-in `timesince`, no `humanize` dependency. A
    just-created row renders "0 minutes ago"; that raw output is accepted (no
    "just now" special-casing — YAGNI) (M5).
- **Footer:** "See all →" `<a>` to `{% url 'notifications:list' %}`.
- **Empty state** (no `notifications_recent`): "You have no notifications yet."

The partial is standalone (no `{% extends %}`); `list.html` is **not** refactored
to use it — the two surfaces render similar rows but differ enough (pager,
per-row mark-read buttons on the full page) that sharing would couple them
without real payoff. Kept separate deliberately.

### 3. Data (`core.context_processors`)

Extend `notifications_badge` to also expose the recent list:

```python
# core/context_processors.py — module-level, the single source of truth for the cap
BELL_RECENT_LIMIT = 8


def notifications_badge(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from notifications.services import notification_url, recent_for, unread_count

    recent = list(recent_for(user, BELL_RECENT_LIMIT))
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
- `BELL_RECENT_LIMIT` lives in `core.context_processors` (the sole consumer); the
  test that asserts the cap imports it rather than hardcoding `8` (M1).

### 4. Interactions (`core/js/ui.js`)

Two small additions to the existing menu/theme IIFE:

- **Anchor trigger enhancement (C1):** the existing `.menu` trigger handler binds
  `<button>`s and only calls `e.stopPropagation()`. The bell trigger is an `<a>`,
  so the handler must also `e.preventDefault()` on it (or the new bell wiring
  does) — otherwise a JS click would both open the panel *and* navigate to the
  list. With JS off, no handler runs and the plain `<a href>` navigation is the
  no-JS fallback. Reconcile in `ui.js` so anchor triggers are supported without
  breaking the existing button triggers.
- **Click-marks-read:** on `click` of any `.notif-menu__row[data-mark-read-url]`,
  fire `fetch(url, {method:"POST", headers:{"X-CSRFToken": getCookie("csrftoken")},
  body: <empty/urlencoded>, credentials:"same-origin", keepalive:true})` and do
  **not** `preventDefault` — the browser follows the `<a href>` to the target.
  `keepalive:true` lets the POST complete after navigation unloads the page.
- **Badge timing is best-effort, not guaranteed on the immediate landing (I2):**
  the mark-read POST races the navigation, so the landing page's context processor
  may read `unread_count` *before* the POST commits and still show the old count;
  the badge then settles on a later load. No client-side badge math is done. The
  guarantee is "eventually consistent within a reload," not "decremented on the
  very next page." "Mark all read" is a normal POST-redirect (no race) that
  reloads the list with a fresh badge.
- **No-JS fallback:** the `.menu` panel only opens via JS, so a no-JS user never
  sees the dropdown — but the bell trigger is an `<a href="…list">`, so it still
  links them to the full `/notifications/` list page (unchanged, POST-form
  mark-read). Requiring JS *inside* the dropdown is therefore consistent, not a
  regression, and the list stays reachable.
- **Keyboard / a11y:** the shared `.menu`/`ui.js` already provides Escape-to-close,
  outside-click-close, and `aria-expanded` sync on the trigger; the bell reuses it
  unchanged (M6). The panel's rows are ordinary focusable `<a>`s, so tab order
  works without extra JS. A test asserts `aria-expanded` toggles on open/close.
- Wiring lives in the same IIFE as the existing menu/theme code; it selects rows
  at load (the panel is server-rendered, always in the DOM).

### 5. Styling (`app.css`)

- `.bell` / `.bell__trigger`: icon button matching `.btn--icon`; badge positioned
  top-right of the bell.
- `.notif-menu` panel: right-aligned under the bell (the `.menu__panel` base
  already positions absolutely); `min-width`/`max-width` on desktop; on mobile
  clamp to viewport (`max-width: calc(100vw - <gutter>)`, right-anchored) so it
  never overflows — the bell is in the always-visible cluster, so this works
  without involving the hamburger. **Dependency to verify (M3):** confirm against
  the current header layout (PR #34) that `.app-header__cluster` (and thus the
  bell) really sits *outside* the collapsing hamburger area at mobile widths — the
  whole clamp strategy rests on it. Check during the screenshot pass.
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
- "{{ time }} ago" — the relative-time `blocktrans` unit from §2 (new). **Not** a
  standalone "ago" token (I4).
- "You have no notifications yet." (new)

### 7. Scope guardrails

- **No migration, no new model, no new view, no new URL.**
- Badge stays server-computed.
- `recipient == actor` self-suppression, email delivery, and the full list page
  are all untouched.

---

## Testing

- **Context processor:** authenticated request exposes `notifications_recent`
  (list, capped at `BELL_RECENT_LIMIT` — the test imports the constant, not a
  literal `8`, M1 — each with a populated/`None` `.url`) and `notifications_unread`;
  anonymous request exposes neither.
- **Shell render:** bell trigger present for authed users with `href` to the list
  (the no-JS path, C1), `role="button"`, and `aria-label`; unread badge shows the
  count, is absent at zero, and renders `99+` when the count exceeds 99 (M2); the
  old text "Notifications" nav link is gone **from every location** — assert on the
  mobile-nav copy too, and update any existing test that asserted the top-level
  link so it targets the bell (I3).
- **Panel:** rows render kind-specific messages + the "{{ time }} ago" relative
  time; unread rows get the unread class; a row with a resolvable target is an
  `<a>` carrying `href` + `data-mark-read-url`; a row with no resolvable URL is a
  non-link with neither; "Mark all read" present only when there are unread; empty
  state when none.
- **e2e (real Playwright gestures):** open the bell dropdown, click a notification
  row, assert the browser lands on the target page **and** that the unread badge
  eventually shows the decremented count — poll/reload until it settles rather than
  asserting a single reload suffices, because the keepalive POST races navigation
  (I2). Also assert the trigger's `aria-expanded` toggles on open/close (M6).
  Follows the `e2e-must-drive-real-ui` convention — drive the actual click path, no
  `page.evaluate` shortcut.

---

## Out of scope (future slices)

- **Announcements** (announcement → group broadcast) — the still-unbuilt half of
  the Notifications roadmap row.
- **Retention/purge** of read + orphaned rows.
- Real-time push / websockets — the badge is refreshed on navigation only.
- Refactoring `list.html` to share the row partial.
