# Theme-aware HTML-element sandbox + mat-pp course CSS rewrite

## Purpose

Author-supplied content in **HTML elements** (`HtmlElement`) renders inside a sandboxed,
opaque-origin iframe whose baseline stylesheet is hardcoded light
(`_BASE_STYLE = "html,body{background:#fff;color:#111}"` in `courses/htmlsandbox.py`). When the app
is in dark mode the iframe stays a white rectangle, and any course CSS written against a light ground
(the `mat-pp` "matematyka" course has ~900 lines of it) is visually disconnected from the rest of the
app.

This change makes HTML-element content **follow the app's colour mode** — light *and* dark, across
surfaces, text, borders, and accents — in two coordinated pieces:

1. **Sandbox plumbing** (all courses benefit): teach the opaque-origin iframe the app's resolved
   theme and give author CSS the app's design tokens.
2. **`mat-pp` CSS rewrite** (this course): route the course's ~900 lines of hardcoded colour onto
   those tokens, adopting the app's brand palette for accents (**Option B**, chosen during
   brainstorming).

### Goals

- HTML-element content matches the app in both themes, including a **live** flip when the user hits
  the in-app theme toggle (no reload).
- Correct **first paint** with no flash in the common cases (explicit light/dark pref, or `auto`
  following the OS).
- The `mat-pp` course renders coherently in dark mode: neutrals from app tokens, accents from the
  app's teal/amber brand, correct/wrong from the app's green/red semantics.

### Non-goals (out of scope)

- **Other courses' custom CSS.** They inherit the themed neutrals baseline and the OS `@media`
  fallback, but their own literal colours won't adapt until similarly rewritten. Only `mat-pp` is
  rewritten here.
- **Institution branding overrides inside the sandbox.** The injected token block inlines the app's
  default brand inputs; a rebranded institution's HTML-element accents won't pick up the override.
  Documented future enhancement.
- **JS / layout / behaviour of the course.** This is colour-only. `html_js`, `html_seed_js`, DOM
  structure, and course logic are untouched.

## Background: how the pieces work today

- **Render path.** `courses/templatetags/courses_extras.py::render_element` (a `@register.simple_tag`)
  dispatches `HtmlElement` to `HtmlElement.render(unit, course)` (`courses/models.py`), which calls
  `htmlsandbox.build_srcdoc(html, css, js, seed, origin=...)` and drops the result into
  `templates/courses/elements/htmlelement.html` as `<iframe sandbox="allow-scripts" srcdoc="{{ doc }}">`.
- **Containment.** The iframe is `sandbox="allow-scripts"` with **no** `allow-same-origin` → opaque
  origin. It cannot read the parent's `data-theme`, cookies, or `localStorage`. Cross-document
  `postMessage` in both directions still works (the existing resize reporter already uses child→parent
  messages).
- **App theme.** `core/context_processors.py` supplies `theme_pref` (`auto|light|dark`) and
  `data_theme` (`light|dark`, with `auto` projected to `light` server-side). `templates/base.html`
  stamps `<html data-theme=... data-theme-pref=...>` and a pre-paint script resolves `auto` against
  `prefers-color-scheme`. `core/static/core/js/ui.js` handles the toggle: it cycles the pref, updates
  `data-theme`/cookie, and (if authenticated) POSTs the new pref.
- **Design tokens.** `core/static/core/css/tokens.css` already defines a complete light + dark token
  system, light values on `:root` and dark values on `[data-theme="dark"]`: surfaces
  (`--surface-base/-raised/-sunken`), text (`--text-primary/-secondary/-tertiary/-inverse`), borders
  (`--border-subtle/-default/-strong`), semantic (`--success/-subtle`, `--warning/-subtle`,
  `--danger/-subtle`), and brand (`--primary`, `--accent`, derived from `--brand-primary`/
  `--brand-accent` via `color-mix`).

## Architecture

### Three-layer theme delivery

The opaque-origin iframe learns the theme through three layers, so it is correct with or without JS:

1. **CSS fallback (no JS required).** The injected token block defines light values on `:root`, dark
   values under `@media (prefers-color-scheme: dark)`, and — so an explicit attribute wins in *both*
   directions — dark values under `:root[data-theme="dark"]` and light values under
   `:root[data-theme="light"]`. With zero JS and no server bake, the iframe follows the OS.

2. **Server bake (correct first paint, no flash).** `render_element` reads `theme_pref` + `data_theme`
   from the template context and passes a concrete theme down to `build_srcdoc`, which stamps
   `<html data-theme="dark">` (or `light`) on the sandbox document — but **only for an explicit
   pref**. For `theme_pref == "auto"` (or when the context lacks these values, e.g. editor preview /
   tests without a request), it bakes **nothing** and lets the `@media` fallback follow the OS. This
   avoids the `auto` + OS-dark mismatch that baking the server's `light` projection would cause.

   | `theme_pref` | Parent paints | Baked `data-theme` | Iframe first paint |
   |---|---|---|---|
   | `auto`, OS light | light | *(none)* | `@media` → light ✓ |
   | `auto`, OS dark | dark | *(none)* | `@media` → dark ✓ |
   | `light` | light | `light` | `[data-theme=light]` → light ✓ |
   | `dark` | dark | `dark` | `[data-theme=dark]` → dark ✓ |

3. **Live bridge (flip without reload).** `ui.js` broadcasts the newly-effective theme to every
   `.html-el__frame` via `postMessage` when the toggle is clicked, and also pushes the current
   effective theme to each frame **on that frame's `load`** (covering `loading="lazy"` frames that
   enter the viewport *after* a toggle, whose baked srcdoc reflects the original server theme). A tiny
   listener inside the srcdoc sets `document.documentElement.dataset.theme` on receipt.

### Components & changes

**1. `courses/htmlsandbox.py`**

- **`_BASE_STYLE`** becomes token-driven:
  `html{color-scheme:light dark}html,body{background:var(--surface-raised);color:var(--text-primary)}`.
- **New token block** injected into `<head>` (a module constant, e.g. `_THEME_TOKENS`): a
  self-contained copy of the **colour** custom properties from `tokens.css`, in the robust four-part
  pattern above:
  - `:root { …light values… }`
  - `@media (prefers-color-scheme: dark) { :root { …dark values… } }`
  - `:root[data-theme="dark"] { …dark values… }`
  - `:root[data-theme="light"] { …light values… }`

  It includes the raw brand inputs (`--brand-primary`, `--brand-accent`), the derived brand families
  (`--primary*`, `--accent*`), surfaces, text, borders, and semantic tokens — mirroring `tokens.css`
  verbatim so names and values stay identical to the app. Fonts, shadows, spacing, and radius tokens
  are **not** injected (not needed for colour theming; keeps the payload small). `color-mix` is
  CSS-native and needs no external asset. This block is inserted **before** any author `css` so author
  rules still win.
- **`build_srcdoc(html, css, js, seed, *, origin, theme=None)`** — new keyword-only `theme`. When
  `theme in ("light", "dark")`, emit `<html data-theme="{theme}">`; otherwise emit plain `<html>`.
- **Theme listener** appended to the srcdoc scripts (sibling of `_RESIZE_REPORTER`): on a
  `message` event of shape `{type:"libli:htmlel:theme", theme:"light"|"dark"}`, set
  `document.documentElement.setAttribute("data-theme", theme)`. Validates the type and that theme is
  one of the two allowed values before applying.

**2. `courses/models.py` — `HtmlElement.render`**

- Signature becomes `render(self, unit, course, theme=None)`; passes `theme=theme` into
  `build_srcdoc`.

**3. `courses/templatetags/courses_extras.py` — `render_element`**

- Gains `takes_context=True` (the template call sites `{% render_element el … %}` are unchanged;
  Django injects `context` as the first parameter). For the `HtmlElement` branch it computes:
  `theme = data_theme if theme_pref in ("light","dark") else None`, reading
  `context.get("theme_pref")` / `context.get("data_theme")`, and passes it to `obj.render(...)`.
  Absent context values → `theme=None` → media fallback. Non-`HtmlElement` branches are unchanged.

**4. `core/static/core/js/ui.js` — theme bridge**

- A helper `broadcastTheme(theme)` that posts `{type:"libli:htmlel:theme", theme}` to
  `contentWindow` of every `iframe.html-el__frame` (target origin `"*"` — the child is opaque-origin
  and cannot be named).
- Called from the toggle handler with the newly-effective theme (`effective(next)`).
- On page load, attach a `load` listener to each `.html-el__frame` that posts the **current**
  effective theme to that frame (handles lazy frames + post-toggle mounts).

**5. `mat-pp` course CSS (`Course.html_css` for slug `mat-pp`) — full rewrite (Option B)**

Two moves, in order:

- **(a) Redefine the course's own `:root` colour vars in terms of app tokens**, so every rule already
  using them auto-themes:
  - `--colour-light-background: var(--surface-sunken)`
  - `--colour-light-blue: var(--primary-subtle)`
  - `--colour-blue-border: var(--primary)`
  - `--colour-light-green: var(--success-subtle)`
  - `--colour-light-red: var(--danger-subtle)`
  (Dimension vars — `--navbar-height`, `--corner-radius`, etc. — are left as-is.)
- **(b) Sweep the literal colours** rule-by-rule onto tokens:

  | Course literal(s) | → app token |
  |---|---|
  | `white`, `#f7f7f7`, `#eeeeee`, `#eaeaea` (surfaces) | `--surface-raised` / `--surface-sunken` |
  | `#333`, `gray` (as text) | `--text-primary` / `--text-secondary` |
  | `gray`, `black`, `lightgray`, `darkgray` (as borders) | `--border-default` / `--border-strong` |
  | question blue `rgb(2,42,135)`, `#202060`, `navy`, `blue` | `--primary` |
  | light-blue example / equation fills | `--primary-subtle` / `--primary` |
  | blue action buttons (white-on-blue) | bg `--primary`, fg `--text-inverse` |
  | `orangered` warnings | `--warning` |
  | `green`, `darkgreen` (correct), `red` (wrong), true/false | `--success` / `--danger` |
  | `magenta`, `yellow`, decorative demo colours | nearest token; keep intent, ensure both-theme legibility |

  The change is **colour-only**: selectors, layout, `!important` usage, images, `figure`/`embed`
  rules, tables' structural borders, and the entire `html_js` stay byte-for-byte except colour values.
  The current low-contrast white-on-`#88cafe` button (faithfully shown in the mockup) is corrected to
  `--text-inverse` on `--primary` in the rewrite.

The accepted colour direction is captured by the brainstorming mockup (Option B: teal `--primary`,
amber `--warning`/`--accent`, `--success`/`--danger` for correctness), verified in light and dark.

## Data flow

1. Consumption page renders → context processor provides `theme_pref` + `data_theme` →
   `render_element` (now `takes_context`) computes the concrete `theme` (explicit pref only) →
   `HtmlElement.render` → `build_srcdoc` stamps `<html data-theme>` (or not, for `auto`).
2. The srcdoc's injected token block resolves every `var(--…)` in the course CSS for the active
   theme; the four-part selector pattern makes the baked attribute win, else `@media` follows the OS.
3. User clicks the app theme toggle → `ui.js` updates the parent `data-theme` and `broadcastTheme` →
   each sandbox iframe's listener sets its own `documentElement` `data-theme` → the token block
   re-resolves → content flips live.
4. A lazy iframe entering the viewport fires `load` → `ui.js` posts the current effective theme to it
   → it matches immediately even if a toggle happened earlier.

## Error handling & edge cases

- **Missing context values** (`render_element` called where `data_theme`/`theme_pref` aren't in
  context — editor preview via `render_to_string`, unit tests, non-request renders): `theme=None`,
  no bake, `@media` fallback governs. No error.
- **`auto` pref:** deliberately not baked; `@media` matches the OS, matching the parent's own `auto`
  resolution. The live bridge still corrects the iframe if the user later toggles.
- **`postMessage` validation:** the srcdoc listener ignores any message whose `type` isn't
  `"libli:htmlel:theme"` or whose `theme` isn't exactly `"light"`/`"dark"`, so unrelated
  cross-document messages can't mutate the sandbox. The parent posts with target origin `"*"` only the
  minimal `{type, theme}` payload (no secrets; the opaque child cannot be addressed by origin).
- **CSP:** unaffected. `_csp` already allows `style-src 'unsafe-inline'` and `script-src
  'unsafe-inline'`; the token `<style>` and listener `<script>` are inline, and `color-mix` needs no
  network. No new asset fetches (fonts/shadows deliberately excluded).
- **Non-`HtmlElement` elements:** the `render_element` change only branches inside the `HtmlElement`
  path; question/other elements render exactly as before.
- **Author CSS override:** the token block precedes author `css`, so a course that *wants* a fixed
  colour can still set it; nothing here forces author content to theme.
- **Other courses:** with literal light colours and no rewrite, they get themed neutrals + OS
  fallback but keep their own accents. Acceptable and documented; no regression versus today (today
  they're always light).

## Testing

- **`courses/htmlsandbox.py` unit tests** (`tests/test_htmlsandbox.py`): token block present in the
  srcdoc (a representative token in both light and dark positions); `build_srcdoc(theme="dark")`
  emits `<html data-theme="dark">`; `theme=None` emits no `data-theme`; the theme listener script is
  present; `_BASE_STYLE` references `var(--surface-raised)`/`var(--text-primary)`.
- **`render_element` theme threading** (`tests/test_html_element.py`): with `theme_pref="dark"`,
  `data_theme="dark"` in context the rendered iframe srcdoc carries `data-theme="dark"`; with
  `theme_pref="auto"` it carries none; with `theme_pref="light"` it carries `data-theme="light"`.
  Confirm no direct-Python callers of `render_element` break under `takes_context`.
- **E2E (drives the REAL toggle)** (`tests/test_e2e_html_element.py`, per the "e2e must drive real UI"
  rule): load a lesson with an HTML element, assert the sandbox iframe's `documentElement`
  `data-theme`; **click the actual app theme toggle** (not a JS shortcut); assert the iframe's
  `documentElement` `data-theme` flips to match. Cover a lazy/second frame if practical.
- **Visual QA** (per "verify UI with screenshots"): Playwright screenshots of a `mat-pp` lesson in
  light and dark, self-critiqued for contrast/legibility of question boxes, examples, equations,
  true/false, tables, correct/wrong states, and buttons — before shipping.
- **Regression:** full suite green, including the i18n catalog tests if any translatable strings are
  touched (they are not expected to be).
