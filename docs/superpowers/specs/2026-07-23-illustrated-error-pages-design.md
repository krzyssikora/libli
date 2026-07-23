# Illustrated error pages (404 / 403)

## Purpose

`templates/404.html` and `templates/403.html` are currently identical bare cards — a heading, one
terse sentence, a "Back to home" button. They are the only pages in libli that a lost or blocked user
is guaranteed to see, and they carry none of the product's voice and none of its visual language.

This work replaces both with an illustrated, bilingual (EN/PL) treatment that:

- tells the user, warmly, what happened and what to do about it;
- gives them the information a useful bug report needs (the address they actually tried);
- shares one decorative learner artwork rendered as a faint full-bleed watermark, tinted from the
  theme token so light and dark both work from a single asset.

**The artwork is a composed scene, not an isolated figure** — a seated person at roughly the left
quarter (source x ≈ 150–520), an open laptop at roughly the right quarter (x ≈ 1000–1400), and a
desk/foreground band spanning the full width across the bottom fifth (y ≈ 520–672). Every one of
those three regions is load-bearing, which is what makes the cropping and fading decisions below
non-optional rather than cosmetic.

**Out of scope.** `templates/500.html` is deliberately dependency-free — no base template, no
collected static, literal brand colours duplicated inline — because a broken static pipeline is
itself a plausible cause of a 500. It is not touched. No support/contact address is introduced: the
`Institution` model has no contact field, adding one is a separate settings slice, and the "report
this" line is therefore plain prose with no link.

## Architecture / components

### 1. `core/static/core/img/learner.png` (new asset)

**Source.** `C:/Users/krzys/Downloads/learner_bw.png` — opaque RGB, 1600×672, black scene on white.
It lives outside the repository and is **not** committed: it is a one-off input, and the derived
`learner.png` below is the artifact of record. If the derivation ever needs repeating and the source
is gone, it can be re-derived from the committed PNG, which carries the same silhouette.

**Derivation** (one-shot, via Pillow — already a project dependency, used by the help-shot
substrate). Output is an **`LA`-mode PNG at the source's native 1600×672**, luminance channel 0
throughout, with the silhouette carried entirely in the **alpha** channel — alpha is the only channel
a CSS mask consumes, so storing anything else is waste. Two steps:

1. **Alpha from luminance, not a hard threshold:** `alpha = 255 - L`. A hard threshold would throw
   away the source's anti-aliased edge pixels and produce a jagged silhouette; the inversion gives
   the same shape with smooth edges at the same file size.
2. **Bottom fade baked into the alpha.** Multiply alpha by a vertical ramp: `1.0` for `y < 0.55·H`,
   falling linearly to `0.0` at `y = H`. Without this, the near-solid desk band (see §Purpose)
   renders as a full-width tinted rectangle with a hard horizontal top edge across the bottom of
   every page — the exact appearance the `@supports` guard below exists to prevent. The ramp
   dissolves the band and lets the figure and laptop rise out of the page instead.

No generation script is committed. The derivation (source path, `alpha = 255 - L`, the ramp) is
recorded in a comment in `error.css`, which is where a maintainer would look.

`learner_wb.png` (the white-on-black inverse) is **not** used — the mask technique makes a second
asset unnecessary.

### 2. `core/static/core/css/error.css` (new)

Follows the established per-page CSS pattern (`auth.css`, `doc-page.css`, `settings.css`): a small
standalone sheet linked from the two templates via `{% block extra_css %}`, never appended to the
global `app.css`.

**The watermark.** A decorative `::after` on `body.error-page`:

```css
@supports (mask-image: url("")) or (-webkit-mask-image: url("")) {
  body.error-page::after {
    content: "";
    position: fixed; inset: auto 0 0 0;     /* bottom-anchored, bleeds off both edges */
    height: min(46vh, 420px);
    background-color: var(--text-primary);  /* the tint — theme token, not a literal */
    mask-image: url("../img/learner.png");
    mask-repeat: no-repeat;
    mask-position: center bottom;
    mask-size: cover;
    opacity: .07;
    z-index: 0;
    pointer-events: none;
  }
  [data-theme="dark"] body.error-page::after { opacity: .10; }
}
```

**Every `mask-*` longhand is duplicated with the `-webkit-` prefix** — all four, not just
`mask-image`. This is load-bearing: the `or (-webkit-mask-image: …)` arm of the `@supports` query
deliberately admits pre-15.4 Safari, and those engines ignore unprefixed `mask-repeat`,
`mask-position` and `mask-size`. Prefixing only `mask-image` would let them through the guard and
then paint the mask tiled, at its natural 1600×672, anchored top-left — worse than no watermark at
all.

Because the fill is `background-color: var(--text-primary)`, the silhouette is warm ink `#1E1C18` in
light and warm parchment `#F2EFE9` in dark — it re-tints itself from the theme with no swap logic, no
second asset, and no `filter: invert()`. `[data-theme="dark"]` is the only dark signal the project
uses (`tokens.css` has no `prefers-color-scheme` query), so keying off it is correct and complete.
`ManifestStaticFilesStorage` rewrites the `url()` at `collectstatic`; the empty `url("")` inside the
`@supports` condition is safely ignored by Django's `url_converter` (it returns the match unchanged
for an empty path).

It is a CSS pseudo-element, not an `<img>`: purely decorative, absent from the accessibility tree, no
alt text to translate, and `pointer-events: none` so it can never intercept a click.

**Narrow viewports.** `mask-size: cover` is correct only while the box is wider than the source's
2.38:1. On a 390 px phone the box is roughly square, `cover` scales the source by ~0.58, and the
visible window falls between the person and the laptop — the watermark degrades to a blank tinted
band containing no figure whatsoever. Therefore:

```css
@media (max-width: 900px) {
  body.error-page::after { mask-size: contain; height: min(32vh, 260px); }
}
```

`contain` keeps the whole composition in frame at the cost of the edge-to-edge bleed, which is the
right trade at that width. The 900 px breakpoint is where a full-width box stops exceeding the
source's aspect ratio at typical heights.

**Stacking.** The watermark takes `z-index: 0`; `body.error-page .app-header` and
`body.error-page .app-main` are raised to `z-index: 1` so content always paints above it. `.app-header`
is **already** `position: relative` (`app.css`, anchoring the mobile nav dropdown) so it needs only
the `z-index`; `.app-main` needs both. A negative `z-index` is deliberately *not* used — it risks
disappearing behind `body`'s own background, and the failure would be invisible in code review but
obvious on screen.

**Page structure.** The `.card` wrapper is dropped: the watermark treatment wants an open page, not a
boxed panel. Both templates override `{% block main_class %}` to `app-main error-page__main`, where
`.error-page__main` adds `min-height` and flex centring so the column sits optically centred rather
than jammed under the header (mirroring what `auth.css` does with `.auth-main`). Inside it:

| Element | Tag | Class |
|---|---|---|
| eyebrow (`404` / `403`) | `<p>` | `.error-page__code` |
| heading | `<h1>` | `.error-page__title` |
| lead paragraph | `<p>` | `.error-page__lead` |
| report / advice paragraph | `<p>` | `.error-page__note` |
| attempted path (404 only) | `<p>` wrapping a `<code>` | `.error-page__path` |
| actions row | `<p>` | `.error-page__actions` |

wrapped in `<div class="error-page__inner">` at `max-width: 40rem`. The actions row is a flex row
with `flex-wrap: wrap` and a gap, so a second button drops to its own line on narrow screens.
`.error-page__path` sets `overflow-wrap: anywhere` — `request.path` is attacker-controlled in
*length* as well as content, and a 2 000-character unbroken path would otherwise blow out the measure
or force horizontal page scroll.

### 3. `templates/404.html` (rewritten)

Continues to `{% extends "base.html" %}` — the header, nav, language switch and theme toggle all stay,
so a lost user always has a way out. Opens with `{% load static i18n %}` (the current file loads only
`i18n`, and a bare `{% static %}` without the load tag is a `TemplateSyntaxError`; `base.html`'s own
load tag does not propagate to child templates). Adds `{% block body_class %}error-page{% endblock %}`,
the `{% block main_class %}` override, and the `error.css` link in `{% block extra_css %}`.

**The action button points at `{% url 'landing' %}`, not `{% url 'home' %}`.** `home` is
`@login_required`, so an anonymous visitor clicking a `home`-targeted button would be bounced to
`/accounts/login/?next=/home/` — neither "the main page" nor the warm way out the Purpose promises.
`landing` is the public entry mapped at `""`, and it redirects authenticated users to `home` itself,
so a single URL is correct for both audiences. (The current templates' bare `href="/"` reaches the
same place; this keeps that behaviour while naming the route.)

**The path line** renders `{{ request_path }}` — Django's `page_not_found` view puts `quote(request.path)`
in the 404 template context — inside `{% if request_path %}`, so the block disappears when the
template is rendered without that context.

### 4. `templates/403.html` (rewritten)

The same shell, the same CSS, the same `landing` button, different copy, and two structural
differences. Where 404 says "nothing here", 403 says "here, but not yours".

- **No path line.** Django's `permission_denied` view passes only `{"exception": ...}` — there is no
  `request_path` to show, and synthesising one from `request.path` would diverge from the 404's
  meaning.
- **A conditional Log in action**, shown when `user.is_authenticated` is false, pointing at
  `{% url 'account_login' %}?next={{ request.get_full_path|urlencode }}`. `get_full_path`, not
  `path`: the latter drops the query string, so a forbidden `/course/x/?tab=notes` would return the
  user to a different page after login.
- **The header's own Log in CTA is suppressed on this page.** `base.html` already renders a
  `btn--ghost` "Log in" for every anonymous request unless `hide_auth_cta` is set. Without
  suppression an anonymous 403 would show two controls with the identical label. Because Django's
  built-in `permission_denied` view renders with a fixed context that the template cannot extend, the
  template sets the flag around the inherited header instead:
  `{% block header %}{% with hide_auth_cta=1 %}{{ block.super }}{% endwith %}{% endblock %}` —
  `block.super` renders the parent block in the current context, so the `{% with %}` applies.

**Reachability, stated honestly.** Every `raise PermissionDenied` in the project sits behind
`@login_required` (`courses/views.py` and peers), so an anonymous request to those URLs gets a 302 to
login and **never a 403**. The anonymous branch is therefore effectively unreachable in production
today. It is kept because it is one `{% if %}`, because it is the correct behaviour the moment any
non-login-gated view raises `PermissionDenied`, and because a 403 page whose only advice to a
logged-out visitor is "ask your administrator" would be actively unhelpful. Its test is a direct
template render (see §Testing), not a live request — because no live request can produce it.

## Data flow

```
unmatched URL ──► Django handler404 ──► page_not_found()
                                          context = {request_path, exception} + RequestContext
                                          └─► templates/404.html ─extends─► base.html
                                                                 ─extra_css─► error.css ─url()─► learner.png

PermissionDenied ──► handler403 ──► permission_denied()
                                      context = {exception} + RequestContext
                                      └─► templates/403.html ─extends─► base.html (same CSS/asset)
```

Both views pass `request`, so context processors run and `base.html` renders with a full header
(branding, language switch, theme toggle, nav). Language selection is unchanged: `LocaleMiddleware`
resolves the active language per request, and every user-visible string on both pages goes through
`{% trans %}`.

## Copy

Verbatim English source strings and their Polish translations. These are the msgids; the plan renders
them into the templates and the catalogs unchanged.

### 404

| | English | Polish |
|---|---|---|
| title | `Page not found` *(existing msgid, kept)* | `Nie znaleziono strony` |
| eyebrow | `404` *(not translated — a numeral)* | — |
| heading | `Nothing here` | `Nic tu nie ma` |
| body | `We appreciate your eagerness to discover, but there's nothing at this address. Check the address you entered, or go back to the main page.` | `Doceniamy zapał do odkrywania, ale pod tym adresem nic nie ma. Sprawdź wpisany adres lub wróć na stronę główną.` |
| report | `If a link inside libli brought you here, please report it to your administrator, describing the steps that led to this page.` | `Jeśli ta strona otworzyła się po kliknięciu linku w aplikacji, zgłoś to administratorowi, opisując kroki, które do niej doprowadziły.` |
| path label | `You tried:` | `Próbowano otworzyć:` |
| action | `Back to main page` | `Powrót do strony głównej` |

### 403

| | English | Polish |
|---|---|---|
| title | `Access denied` *(existing msgid, kept)* | `Brak dostępu` |
| eyebrow | `403` *(not translated)* | — |
| heading | `Not for you` | `Nie dla ciebie` |
| body | `This page exists, but your account doesn't have permission to open it. If you think you should have access, ask your administrator.` | `Ta strona istnieje, ale twoje konto nie ma uprawnień, żeby ją otworzyć. Jeśli uważasz, że powinno je mieć, zwróć się do administratora.` |
| action | `Back to main page` | `Powrót do strony głównej` |
| action (anon) | `Log in` *(existing msgid, reused)* | `Zaloguj się` |

**The blunt 403 heading is a deliberate, user-approved voice choice.** `Not for you` / `Nie dla
ciebie` is terser than the warm register the rest of the page uses, and in informal Polish it lands
close to a brush-off. That contrast is intended: the heading is the joke, the paragraph beneath it
does the helpful work. Recorded here so review does not relitigate it.

### Polish constraints (user-set, non-negotiable)

- **"link", never "odnośnik".** The existing catalog uses `link` throughout (`link do resetowania
  hasła`, `Wklej dowolny link`) and `odnośnik` appears zero times.
- **Informal `ty` register**, matching the existing catalog (`Nie masz uprawnień do wyświetlenia tej
  strony.`).
- **No gendered past-tense forms.** Polish past tense is gendered, so `trafiłeś` / `trafiłaś` would
  misgender half the audience; the report sentence is phrased impersonally
  (`Jeśli ta strona otworzyła się po kliknięciu linku…`) and the path label uses the impersonal
  `Próbowano otworzyć:` for the same reason.

### Catalog churn

`Back to home` is used in exactly three places: `templates/403.html`, `templates/404.html`, and a
**hardcoded, untranslated** literal in `templates/500.html`. Once both translated pages move to
`Back to main page`, the `Back to home` msgid has no remaining `{% trans %}` reference and must be
**deleted** from both `locale/en` and `locale/pl` — not left as an `#~` obsolete entry.
`We couldn't find that page.` and `You don't have permission to view this page.` are likewise
superseded and get the same treatment. `Page not found`, `Access denied` and `Log in` survive and are
reused.

**Compiled catalogs are part of the diff.** `locale/en/LC_MESSAGES/django.mo` and
`locale/pl/LC_MESSAGES/django.mo` are both tracked in git, and `docs/development/conventions.md`
documents the `makemessages` → translate → `compilemessages` cycle. The `.po` edits alone would leave
the runtime reading a stale catalog and the Polish render test failing. The known `makemessages`
fuzzy-flag gotcha applies: newly added strings that resemble deleted ones come back marked `#, fuzzy`
and are ignored at runtime until the flag is removed.

## Error handling

The failure modes worth designing for are all rendering-time, because these templates run precisely
when something has already gone wrong:

- **Attacker-controlled path.** `request_path` is echoed on the 404. The **primary** defence is
  Django's own `quote()` in `page_not_found`, which percent-encodes `<`, `>`, `"`, `'`, `&`, `(` and
  `)` before the value ever reaches the template — an injected `<script>` arrives as
  `%3Cscript%3E`. Template autoescaping is defence-in-depth on top of that, and `|safe` on this value
  is forbidden. See §Testing for what the corresponding test can and cannot prove.
- **Missing context.** `{% if request_path %}` means the 404 template renders correctly when included
  or rendered directly without the view's context, rather than emitting an empty `You tried:` label.
- **Missing static.** If `learner.png` fails to load, `mask-image` resolves to nothing and — per the
  CSS mask model — the masked element paints nothing. The page loses its decoration and keeps every
  word. No layout depends on the asset's presence.
- **No mask support.** Handled by the `@supports` guard; degrades to no watermark.
- **A 403 for an anonymous user.** Handled structurally by the conditional Log in action, with the
  reachability caveat stated above.

## Testing

`pytest` with `pytest-django`, per the repo's existing conventions. Django forces `DEBUG=False` under
test, so `client.get(...)` renders the **real** templates — no `override_settings` gymnastics needed.

1. **404 renders the new page.** `client.get("/no-such-page/")` → status 404, the new heading and both
   prose strings present, the old `We couldn't find that page.` absent.
2. **404 echoes the attempted path.** The requested path appears in the response body.
3. **404 never emits a raw tag from the path.** Request a path containing `<script>`; assert
   `b"<script>"` is **absent** and the percent-encoded `%3Cscript%3E` is **present**. Note honestly
   what this does and does not prove: because `quote()` has already stripped every HTML-special
   character, the rendered bytes are identical with and without `|safe`, so this test cannot catch a
   stray `|safe`. What it *does* catch — and what makes it non-vacuous — is a future edit that swaps
   `{{ request_path }}` for the un-quoted `{{ request.path }}`, which would emit the raw tag and turn
   the page red.
4. **403 renders the new page**, driven through a real permission-denied surface: log in as a user
   with no access to a course, `GET` that course's `courses:course_outline` URL
   (`courses/views.py`, `if not can_access_course(...): raise PermissionDenied`), assert 403 and the
   new copy.
5. **403 Log in action, split in two** because the surface in test 4 is `@login_required` and so can
   never produce an anonymous 403:
   - *authenticated:* on the response from test 4's surface, assert the login `?next=` href is
     **absent**.
   - *anonymous:* render `templates/403.html` directly (`RequestFactory` + `AnonymousUser`, through
     a `RequestContext` so the context processors run) and assert the login href **is** present.
   Both halves assert on the `?next=` href, never on the bare string `Log in` — `base.html` renders
   its own `Log in` CTA for anonymous visitors, so a bare-substring assertion would pass whether or
   not the conditional action was ever implemented.
   - *no duplicate:* on the anonymous render, assert `Log in` occurs **exactly once**, which is what
     pins the `hide_auth_cta` header suppression.
6. **Polish renders on both pages.** Following the proven pattern in `tests/test_i18n_catalog.py`
   (set `session["_language"] = "pl"` *and* send `HTTP_ACCEPT_LANGUAGE="pl"` — `translation.override`
   alone does not control what the test client renders): assert the PL strings appear and the EN
   source strings do not. This is the test that catches the realistic failure — a msgid added to the
   template but not to the catalog.
7. **Both catalogs are free of obsolete entries.** The three existing `#~` assertions
   (`tests/test_i18n_auth.py`, `tests/test_i18n_notes.py`, `tests/test_tags_i18n.py`) read **only**
   `locale/pl/LC_MESSAGES/django.po`, so they cover half this change. Add the matching
   `#~`-absence assertion for `locale/en/LC_MESSAGES/django.po`.
8. **Static and template wiring guard**, per the repo's standing convention for a new per-page sheet
   (`tests/test_auth_styles.py`, `test_settings_styles.py`, `test_tags_static.py`, `test_callout_css.py`):
   assert `core/static/core/css/error.css` exists and defines the `.error-page` vocabulary, that both
   templates emit the stylesheet link and the `error-page` body class, and that
   `core/static/core/img/learner.png` exists and opens as an `LA`-mode image. Without this a deleted
   `{% block extra_css %}` line or a missing asset would ship green.

**Falsification.** Every test above is written to fail first: delete the thing it guards and confirm
it goes red before keeping it. A passing test that has never been seen to fail proves nothing — this
project has shipped vacuous tests before.

**Visual verification is part of "done", not optional**, per the standing `verify-ui-with-screenshots`
convention. Four Playwright shots: 404 and 403, each in light and dark.

- *Reaching the 404:* `live_server.url + "/no-such-page/"`.
- *Reaching the 403:* log in as a user with no access to a seeded course, then navigate to that
  course's outline URL — the same surface as test 4.
- *Forcing the theme:* set the `libli_theme` cookie to `light` / `dark` before navigating.
  `base.html`'s pre-paint script reads `data-theme-pref` and falls back to that cookie, so a naive
  `goto` renders light every time.
- *Widths:* one desktop (1280) and one phone (390) pass, because the phone width is where
  `mask-size` switches and where the composition is most at risk.

Self-critique the shots before calling the work done, specifically checking: the watermark reads as
atmosphere rather than as a picture; it never fights the text for contrast in either theme; **no hard
horizontal edge appears across the bottom of the page** (the bottom-fade ramp is doing its job); the
figure is actually in frame at 390 px; and content genuinely paints above the watermark.

**Worktree DB isolation.** This work runs in a git worktree alongside others, and concurrent worktrees
collide on the Postgres `test_libli` database. The worktree needs its own `.env` with a unique
`DATABASE_URL` before any test run — a known, previously-hit failure mode, not a speculative one.
