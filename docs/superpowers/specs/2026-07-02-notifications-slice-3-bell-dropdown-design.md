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

A bell `.menu` is added as a **direct child of `.app-header__cluster`,
immediately before the account `.menu` (avatar) and *outside* `#primary-nav`**.
This placement matters: in the real `base.html` the hamburger toggle and the
whole `<nav id="primary-nav" data-nav-panel>` sit *between* the theme-toggle and
the avatar, so "between theme-toggle and avatar" is **not** specific enough —
dropping the bell inside/adjacent to `#primary-nav` would collapse it into the
hamburger on mobile and break the §5 always-visible clamp strategy. Put it after
`#primary-nav` closes and before the account menu. It renders **only for
authenticated users** (inside the existing `{% if user.is_authenticated %}`
block).

```
<div class="menu bell">
  <a class="btn--icon bell__trigger" href="{% url 'notifications:list' %}"
    data-menu-trigger aria-haspopup="true" aria-expanded="false"
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
  (`preventDefault`) and toggles the panel instead (see §4). It stays a **link**
  (no `role="button"`) so semantics match behaviour: screen readers announce a
  link, Enter activates it natively (JS-open when enhanced, navigate when not),
  and `aria-haspopup`/`aria-expanded` advertise the popup. We deliberately do
  **not** add Space-key activation — a link isn't expected to honour Space, and
  the native href is the fallback either way (M2).
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
  panel's "See all" footer. It is a **single node inside `<nav id="primary-nav">`**
  (shown inline on desktop, collapsed under the hamburger on mobile via
  `display:contents`) — not a top-level link with a separate mobile copy, so
  removing that one node covers both surfaces. Still grep every `notifications:list`
  link usage to confirm no other reference exists, and update existing tests that
  assert the link's presence (per the PR #60 lesson: moving/removing a nav link
  breaks tests that clicked/asserted it) to target the bell instead.
- **No `data-*` hook on the wrapper (M3):** the `.menu` component keys off
  `[data-menu-trigger]`/`[data-menu-panel]`, and the click-marks-read handler
  selects `.notif-menu__row[data-mark-read-url]` document-wide, so the wrapper
  needs no `data-bell-menu` attribute — it is omitted rather than left vestigial.
- **No-JS aria (M4):** `aria-haspopup`/`aria-expanded` are hardcoded on the
  trigger even though a no-JS user has no popup to open. This is an accepted
  progressive-enhancement trade-off, **consistent with the existing account/admin
  menu `<button>` triggers**, which hardcode the same attributes and likewise only
  function with JS. Not worth moving to JS-set-on-enhancement for one control.

### 2. Panel partial (`notifications/templates/notifications/_bell_panel.html`)

New partial, rendered inline (server-side, present in the DOM, hidden until
opened — the `.menu` idiom). Structure:

- **Header:** a "Notifications" title as a **non-heading styled element** (e.g.
  `<p class="notif-menu__title">`), **not an `<h2>`** — the panel renders in the
  page header, so a heading here would inject an `<h2>` ahead of the page's `<h1>`
  in DOM order and disrupt screen-reader heading navigation. Instead the panel is
  labelled for AT via **`aria-label="{% trans 'Notifications' %}"` on
  `.menu__panel`** (committing to `aria-label`, not `aria-labelledby`, so there's
  no dependency on adding a unique `id` to the title element). Consistent with the
  account/admin menus, which use no headings. Beside the title: a "Mark all read"
  POST form
  (`{% url 'notifications:mark_all_read' %}`, `{% csrf_token %}`), shown only
  when `notifications_unread`. Submitting it redirects to `/notifications/` (the
  verbatim `mark_all_read` behaviour) — an accepted confirmation-view jump (I1).
- **List:** iterate `notifications_recent` (≤ 8 rows). Each row:
  - Whole row is `<a class="notif-menu__row" href="{{ n.url }}"
    {% if not n.read_at %}data-mark-read-url="{% url 'notifications:mark_read' n.pk %}"{% endif %}>`
    **when `n.url` is truthy**; otherwise a non-link `<div class="notif-menu__row">`
    that keeps the **same `notif-menu__row` class** (plus `--unread` when
    applicable) for identical layout/tint, and only drops `href` +
    `data-mark-read-url` (nothing to navigate to or mark-through).
  - **`data-mark-read-url` is emitted only on *unread* rows** (`{% if not n.read_at %}`):
    the bell shows read rows too, and firing a `mark_read` POST on an
    already-read row would be a wasted (though idempotent) round-trip. Gating the
    attribute — not the `href` — means read rows still navigate on click but skip
    the redundant fetch (M1).
  - **URL-less rows are not individually clearable from the bell** (I5): they have
    no per-row affordance here. This is deliberate and bounded — such rows only
    arise when `notification_url` can't resolve (missing `data`), and they are
    still cleared by the panel's "Mark all read" or on the full list page (both
    reachable). Documented so the badge-persistence case is a known trade-off, not
    a surprise.
  - Unread rows add `notif-menu__row--unread` (dot + tint, mirroring
    `.notif-row--unread`). The predicate is **`{% if not n.read_at %}`** — the
    same field-driven condition `list.html` uses — since the bell shows both read
    and unread recent rows (M2).
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
- **Footer:** a "See all" `<a>` to `{% url 'notifications:list' %}`. The decorative
  "→" is a **template-level literal outside** the `{% trans 'See all' %}` unit (or
  a CSS `::after` glyph), so translators only ever see "See all" — the arrow never
  leaks into the `.po` msgid (M4).
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
- The per-row `n.url = notification_url(n)` monkey-patch is safe: `Notification`
  defines no `url` field, property, or accessor (its fields are `recipient`,
  `kind`, `actor`, `target_type`, `target_id`, `data`, `created_at`, `read_at`),
  so neither the assignment nor the `{{ n.url }}` template lookup collides (M4).

### 4. Interactions (`core/js/ui.js`)

Two small additions to the existing menu/theme IIFE:

- **Anchor trigger enhancement (C1):** the existing `.menu` trigger handler binds
  `<button>`s and only calls `e.stopPropagation()`. The bell trigger is an `<a>`,
  so a JS click would otherwise both open the panel *and* navigate to the list.
  **Resolution: patch the shared `.menu` trigger handler to call
  `e.preventDefault()` when the trigger's tag is `A`** (`trigger.tagName === "A"`)
  — a no-op for the existing `<button>` triggers, so it's a single deterministic
  code path, not per-trigger bell wiring. **Exception (M3): skip `preventDefault`
  for modified clicks** — when `e.metaKey || e.ctrlKey || e.shiftKey ||
  e.button !== 0` — so ctrl/cmd/shift-click still opens `/notifications/` in a new
  tab/window (middle-click already fires `auxclick`, not `click`, so it is
  unaffected). A plain primary click toggles the panel. With JS off, no handler
  runs and the plain `<a href>` navigation is the no-JS fallback.
- **Click-marks-read:** on `click` of any `.notif-menu__row[data-mark-read-url]`,
  fire `fetch(url, {method:"POST", headers:{"X-CSRFToken": getCookie("csrftoken")},
  body: <empty/urlencoded>, credentials:"same-origin", keepalive:true,
  redirect:"manual"})` and do **not** `preventDefault` — the browser follows the
  `<a href>` to the target. `keepalive:true` lets the POST complete after
  navigation unloads the page; `redirect:"manual"` stops at `mark_read`'s 302 so
  the fetch does **not** follow it into a wasted background render of
  `/notifications/` (M3).
- **Badge timing is best-effort, not guaranteed on the immediate landing (I2):**
  the mark-read POST races the navigation, so the landing page's context processor
  may read `unread_count` *before* the POST commits and still show the old count;
  the badge then settles on a later load. No client-side badge math is done. The
  guarantee is "eventually consistent within a reload," not "decremented on the
  very next page." **And in the worst case it may not clear at all (M4):** if the
  browser drops the in-flight `keepalive` POST on unload (engine quirk / body-size
  limits), that click never marks the row read — it's lost, not merely delayed.
  The guaranteed clearing paths remain the panel's "Mark all read" and the list
  page's POST-form mark-read (both already reachable), so this degrades gracefully.
  "Mark all read" is itself a normal POST-redirect (no race) that reloads the list
  with a fresh badge.
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
  never overflows horizontally — the bell is in the always-visible cluster, so
  this works without involving the hamburger. **Dependency to verify:** confirm
  against the current header layout (PR #34) that `.app-header__cluster` (and thus
  the bell) really sits *outside* the collapsing hamburger area at mobile widths —
  the whole clamp strategy rests on it. Check during the screenshot pass.
- **Vertical overflow (I1):** the panel is `position:absolute`, so an 8-row list
  plus header + footer can run past the bottom of a short viewport (landscape
  phones, small laptops) with no page scroll to reveal it. Give `.notif-menu` a
  `max-height` clamped to the viewport (e.g. `min(<cap>, calc(100vh - <header+gap>))`)
  and `overflow-y:auto` so the rows scroll within the panel. Verify the last row
  and the footer are reachable in the light+dark screenshot pass.
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
  literal `8` — each with a populated/`None` `.url`) and `notifications_unread`;
  anonymous request exposes neither. Add an **`assertNumQueries` guard** (M5)
  around the processor for an authed user with several notifications, locking the
  §3 "one added query for `recent_for`, no N+1 from `notification_url`" invariant
  against future regressions (assert the fixed added-query count, not just the
  content).
- **Shell render:** bell trigger present for authed users as an `<a>` with `href`
  to the list (the no-JS path, C1), `aria-label`, and `aria-haspopup` — and assert
  it carries **no** `role="button"` (the trigger stays a link; I1); unread badge
  shows the count, is absent at zero, and renders `99+` when the count exceeds 99
  (M2); the
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
  (I2). Use a **bounded** wait (Playwright's default `expect`-poll timeout, not an
  open-ended loop) so that if the POST is ever dropped (M4's worst case) the
  assertion fails visibly instead of hanging (M3). Also assert the trigger's
  `aria-expanded` toggles on open/close.
  Follows the `e2e-must-drive-real-ui` convention — drive the actual click path, no
  `page.evaluate` shortcut.

---

## Out of scope (future slices)

- **Announcements** (announcement → group broadcast) — the still-unbuilt half of
  the Notifications roadmap row.
- **Retention/purge** of read + orphaned rows.
- Real-time push / websockets — the badge is refreshed on navigation only.
- Refactoring `list.html` to share the row partial.
