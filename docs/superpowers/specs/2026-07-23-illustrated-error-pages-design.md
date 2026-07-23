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

### The artwork, measured

It is a composed scene, not an isolated figure. Measured from the source (ink = luminance < 128):

| Region | x extent | y extent |
|---|---|---|
| seated person | ≈ 150–560 | **6 – 671** (head starts at 1% of height) |
| open laptop | ≈ 950–1450 | 234 – 671 |
| whole composition | 0 – 1600 | 6 – 671 |

Row ink density climbs from ~9–17% across the upper two thirds to **68% at y≈504, 90% at y≈560, and
94% at y≈616** — the desk/foreground band occupies the bottom quarter and is very nearly solid.

These two measurements drive the entire CSS design below and are the reason it is not the obvious
one:

- **The head sits at the very top of the frame (y=6).** Any vertical crop removes it. This rules out
  `mask-size: cover` in a short box, which would have cropped 22–38% off the top at desktop widths
  and decapitated the figure on every render.
- **The bottom quarter is nearly solid ink.** Painted unmodified it is a full-width tinted rectangle
  with a hard horizontal top edge — the exact artifact the `@supports` guard below exists to prevent.

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
2. **Bottom fade baked into the alpha.** Multiply alpha by a vertical ramp: `1.0` for `y < 0.72·H`,
   falling linearly to `0.0` at `y = H`. The 0.72 threshold is taken from the density ladder above —
   it sits just above the y≈504 row where ink jumps from 25% to 68% — so the ramp dissolves the desk
   band while leaving the person and the laptop at full strength. A ramp starting earlier (e.g.
   0.55·H) would begin fading the figure's torso for no benefit.

**Size budget: ≤ 60 KB.** Measured, the derived file is **17 KB** at native 1600×672 with
`optimize=True`. Downscaling is counterproductive and must not be done "for weight": the same image
resampled to 1280×538 measures **26 KB**, because resampling introduces gradients in what is
otherwise a flat two-tone alpha channel. Test 8 asserts the ceiling.

No generation script is committed. The derivation (source path, `alpha = 255 - L`, the 0.72 ramp) is
recorded in a comment in `error.css`, which is where a maintainer would look.

`learner_wb.png` (the white-on-black inverse) is **not** used — the mask technique makes a second
asset unnecessary.

### 2. `core/static/core/css/error.css` (new)

Follows the established per-page CSS pattern (`auth.css`, `doc-page.css`, `settings.css`): a small
standalone sheet linked from the two templates via `{% block extra_css %}`, never appended to the
global `app.css`.

**The watermark.** A decorative `::after` on `body.error-page`. The box is sized by
**`aspect-ratio`, not by a height guess**, so the mask never has to crop:

```css
@supports (mask-image: url("")) or (-webkit-mask-image: url("")) {
  body.error-page::after {
    content: "";
    position: fixed; left: 0; right: 0; bottom: 0;  /* bleeds off both edges */
    aspect-ratio: 1600 / 672;                       /* box matches the artwork */
    max-height: 60vh;                               /* never dominates a short window */
    background-color: var(--text-primary);          /* the tint — token, not a literal */
    -webkit-mask-image: url("../img/learner.png");
            mask-image: url("../img/learner.png");
    -webkit-mask-repeat: no-repeat;    mask-repeat: no-repeat;
    -webkit-mask-position: center bottom; mask-position: center bottom;
    -webkit-mask-size: contain;        mask-size: contain;
    opacity: .07;
    z-index: 0;
    pointer-events: none;
  }
  [data-theme="dark"] body.error-page::after { opacity: .10; }
}
```

**Why `aspect-ratio` + `contain` and no breakpoint.** Full-bleed width and a fixed short height are
incompatible with a 2.38:1 artwork whose subject reaches the top edge — one of the three has to give,
and cropping is the one that destroys the picture. Letting width drive height keeps the whole
composition in frame at every width with no breakpoint at all: at 390 px the box is 390×164 and the
scene is a thin full-width band; at 1280 px it is 1280×538. `max-height: 60vh` is the one clamp, and
because `mask-size` is `contain` (not `100% 100%`), a clamped box letterboxes horizontally rather than
distorting the figure. This replaces an earlier `cover` + `max-width: 900px` scheme that cropped the
subject out of frame on phones and cropped the head off on desktops.

**Every `mask-*` longhand is duplicated with the `-webkit-` prefix** — all four, as written above,
and any `mask-*` in any future rule. This is load-bearing: the `or (-webkit-mask-image: …)` arm of
the `@supports` query deliberately admits pre-15.4 Safari, and those engines ignore unprefixed
`mask-repeat`, `mask-position` and `mask-size`. Prefixing only `mask-image` would let them through
the guard and then paint the mask tiled, at its natural 1600×672, anchored top-left — worse than no
watermark at all. There is exactly one `mask-*` rule (no media-query override), so there is one place
to keep consistent.

Because the fill is `background-color: var(--text-primary)`, the silhouette is warm ink `#1E1C18` in
light and warm parchment `#F2EFE9` in dark — it re-tints itself from the theme with no swap logic, no
second asset, and no `filter: invert()`. `[data-theme="dark"]` is the only dark signal the project
uses (`tokens.css` has no `prefers-color-scheme` query), so keying off it is correct and complete.
`ManifestStaticFilesStorage` rewrites the `url()` at `collectstatic`; the empty `url("")` inside the
`@supports` condition is safely ignored by Django's `url_converter` (it returns the match unchanged
for an empty path).

It is a CSS pseudo-element, not an `<img>`: purely decorative, absent from the accessibility tree, no
alt text to translate, and `pointer-events: none` so it can never intercept a click.

**Stacking — the ordering invariant is `watermark 0 < .app-main 1 < .app-header 2`.** Both must be
raised above the watermark, but they must **not** share a layer. Giving `.app-header` a `z-index`
turns it into a stacking context, re-scoping its descendants' `z-index: 50` (`.menu__panel` — account
menu, bell panel) and `z-index: 40` (`.app-nav` mobile panel) inside it. If `.app-main` then sat at
the same `z-index: 1`, DOM order would decide and the later `.app-main` would paint *and hit-test*
above the header's whole subtree — including the dropdown panels, which hang down over main.
`app.css` carries a comment recording that this precise regression has already happened once ("`Log
out` looks see-through and can't be tapped"). So: `.app-header { z-index: 2 }` (it is **already**
`position: relative` in `app.css`, anchoring the mobile nav dropdown, so only the `z-index` is new)
and `.app-main { position: relative; z-index: 1 }` (needs both). A negative `z-index` on the
watermark is deliberately *not* used — it risks disappearing behind `body`'s own background.

**Page structure.** The markup goes in `{% block content %}`, which `base.html` renders inside
`<main>`; `{% block main_class %}` only re-classes that inherited `<main>` to
`app-main error-page__main`. The `.card` wrapper is dropped — the watermark treatment wants an open
page, not a boxed panel.

`.error-page__main` sets `min-height: calc(100vh - 2 * var(--space-6))` with flex column centring,
mirroring `.auth-main`. Note the difference from that precedent: `.auth-main` is used *instead of*
`.app-main`, whereas here both classes apply, so `.app-main`'s `max-width: 960px; margin: 0 auto;
padding: var(--space-8) var(--space-5)` **stays in force and is deliberately kept** — 960px is a fine
outer bound and the inner column is narrower anyway. The `{% if messages %}` alerts `base.html`
renders inside `<main>` become flex children; they are given `width: 100%` so a stray alert spans the
column rather than shrink-wrapping.

Inside, wrapped in `<div class="error-page__inner">` at `max-width: 40rem`:

| Element | Tag | Class |
|---|---|---|
| eyebrow (`404` / `403`) | `<p>` | `.error-page__code` |
| heading | `<h1>` | `.error-page__title` |
| lead paragraph | `<p>` | `.error-page__lead` |
| report / advice paragraph | `<p>` | `.error-page__note` |
| attempted path (404 only) | `<p>` wrapping a `<code>` | `.error-page__path` |
| actions row | `<p>` | `.error-page__actions` |

The actions row is a flex row with `flex-wrap: wrap` and a gap, so a second button drops to its own
line on narrow screens. `.error-page__path` sets `overflow-wrap: anywhere` — `request.path` is
attacker-controlled in *length* as well as content, and a 2 000-character unbroken path would
otherwise blow out the measure or force horizontal page scroll.

### 3. `templates/404.html` (rewritten)

Continues to `{% extends "base.html" %}` — the header, nav, language switch and theme toggle all stay,
so a lost user always has a way out. Opens with `{% load static i18n %}` (the current file loads only
`i18n`, and a bare `{% static %}` without the load tag is a `TemplateSyntaxError`; `base.html`'s own
load tag does not propagate to child templates). Keeps
`{% block head_title %}{% trans "Page not found" %} · libli{% endblock %}` **unchanged** — the title
msgid survives as the tab title and does not migrate into the visible `<h1>`. Adds
`{% block body_class %}error-page{% endblock %}`, the `{% block main_class %}` override, and the
`error.css` link in `{% block extra_css %}`.

**The action button points at `{% url 'landing' %}`, not `{% url 'home' %}`.** `home` is
`@login_required`, so an anonymous visitor clicking a `home`-targeted button would be bounced to
`/accounts/login/?next=/home/` — neither "the main page" nor the warm way out the Purpose promises.
`landing` is the public entry mapped at `""`, and it redirects authenticated users to `home` itself,
so a single URL is correct for both audiences. (The current templates' bare `href="/"` reaches the
same place; this keeps that behaviour while naming the route.) It is a single `.btn`.

**The path line** renders `{{ request_path }}` — Django's `page_not_found` view puts `quote(request.path)`
in the 404 template context — inside `{% if request_path %}`, so the block disappears when the
template is rendered without that context.

### 4. `templates/403.html` (rewritten)

The same shell, the same CSS, the same `landing` target, different copy, and two structural
differences. Where 404 says "nothing here", 403 says "here, but not yours". Keeps
`{% block head_title %}{% trans "Access denied" %} · libli{% endblock %}` unchanged.

- **No path line.** Django's `permission_denied` view passes only `{"exception": ...}` — there is no
  `request_path` to show, and synthesising one from `request.path` would diverge from the 404's
  meaning.
- **A conditional Log in action**, shown when `user.is_authenticated` is false, pointing at
  `{% url 'account_login' %}?next={{ request.get_full_path|urlencode }}`. `get_full_path`, not
  `path`: the latter drops the query string, so a forbidden `/course/x/?tab=notes` would return the
  user to a different page after login. **Button hierarchy:** in the anonymous case `Log in` comes
  **first** as the `.btn` and `Back to main page` follows as `.btn--ghost`, because logging in is the
  likely fix; when authenticated, `Back to main page` is the lone `.btn`.
- **The header's own Log in CTA is suppressed on this page.** `base.html` renders a `btn--ghost`
  "Log in" for every anonymous request unless `hide_auth_cta` is set, which would put two controls
  with the identical label on the page. `hide_auth_cta` is **not** a view-supplied flag: it is
  computed on every request by `core/context_processors.py::ui_prefs` from
  `request.resolver_match.view_name`, and is true only for `account_*` / `accounts:*` / `landing` —
  so on a 403 raised by `courses:course_outline` it is `False`. Because Django's built-in
  `permission_denied` view renders with a fixed context the template cannot extend, the template
  shadows the context-processor value around the inherited header:
  `{% block header %}{% with hide_auth_cta=1 %}{{ block.super }}{% endwith %}{% endblock %}` —
  `BlockNode.super()` re-renders the parent block against the same mutable `Context`, so the pushed
  `{% with %}` layer is visible to it.

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
the runtime reading a stale catalog and the Polish render test failing.

**One fuzzy match is near-certain and must be cleared.** The retired `Back to home` already carries
the Polish msgstr `Powrót do strony głównej` — byte-identical to the Polish this spec assigns the new
`Back to main page`. `makemessages` will almost certainly resurrect it as a `#, fuzzy` match, and a
fuzzy entry is **ignored at runtime**, so test 6 would fail with a perfectly correct translation
sitting in the file. Strip the `#, fuzzy` flag from `Back to main page` in both catalogs before
running `compilemessages`.

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
- **A missing or misnamed `learner.png` is a build failure, not a soft one.** Production uses
  `whitenoise.storage.CompressedManifestStaticFilesStorage`, whose post-processing rewrites `url()`
  references in CSS and, with `manifest_strict` at its default, **raises** on an absent target — so
  `collectstatic` aborts and the deploy stops. That is the realistic failure and the reason test 8's
  asset assertion is a build guard rather than a nicety. The genuinely graceful case is narrower: an
  asset deleted from disk *after* a successful collect resolves `mask-image` to nothing and the
  masked element paints nothing, so the page loses its decoration and keeps every word. No layout
  depends on the asset's presence.
- **No mask support.** Handled by the `@supports` guard; degrades to no watermark. (Engines without
  `aspect-ratio` — Safari 14 and older — get a zero-height box, which is the same degradation.)
- **A 403 for an anonymous user.** Handled structurally by the conditional Log in action, with the
  reachability caveat stated above.

## Testing

`pytest` with `pytest-django`, per the repo's existing conventions. Django forces `DEBUG=False` under
test, so `client.get(...)` renders the **real** templates — no `override_settings` gymnastics needed.

**The shared 403 fixture**, used by tests 4, 5, 6 and both 403 screenshots. `courses/access.py`
grants access if the user `is_staff` **or** owns the course **or** is enrolled **or** teaches a
non-archived group attached to it — "no access" is four negatives, not one, and the project's factories
do not all produce a prod-shaped non-staff user. Pin it explicitly: a user who is **not** `is_staff`,
**not** `is_superuser`, **not** the course's `owner`, has **no** `Enrollment` on it, and teaches **no**
group attached to it; plus a course owned by somebody else. Name the factory calls in the test.

1. **404 renders the new page.** `client.get("/no-such-page/")` → status 404, the new heading and both
   prose strings present, the old `We couldn't find that page.` absent.
2. **404 echoes the attempted path.** The requested path appears in the response body.
3. **404 never emits a raw tag from the path.** Request `/<script>alert(1)</script>/` and assert the
   **payload** `b"<script>alert"` is absent while `b"%3Cscript%3Ealert"` is present. Asserting on the
   bare `b"<script>"` would be wrong: `base.html` emits three literal `<script>` tags of its own (the
   two pre-paint blocks and the deferred `ui.js`), so that assertion fails unconditionally on every
   response from these pages. Note honestly what this test does and does not prove: because `quote()`
   has already stripped every HTML-special character, the rendered bytes are identical with and
   without `|safe`, so it cannot catch a stray `|safe`. What it *does* catch — and what makes it
   non-vacuous — is a future edit swapping `{{ request_path }}` for the un-quoted `{{ request.path }}`,
   which would emit the raw payload and turn the page red.
4. **403 renders the new page**, driven through a real permission-denied surface: log in as the
   fixture user above and `GET` the course's `courses:course_outline` URL (`courses/views.py`,
   `if not can_access_course(...): raise PermissionDenied`). Assert 403 and the new copy.
5. **403 Log in action, split in two** because the surface in test 4 is `@login_required` and so can
   never produce an anonymous 403:
   - *authenticated:* on test 4's response, assert the login `?next=` href is **absent**.
   - *anonymous:* render `templates/403.html` directly (`RequestFactory` + `AnonymousUser`, through a
     `RequestContext` so the context processors run) and assert the login href **is** present.
   - *no duplicate:* on that anonymous render, assert `Log in` occurs **exactly once**, which is what
     pins the `hide_auth_cta` header suppression.

   Both halves assert on the `?next=` href, never on the bare string `Log in` — `base.html` renders
   its own `Log in` CTA for anonymous visitors, so a bare-substring assertion would pass whether or
   not the conditional action was ever implemented.
6. **Polish renders on both pages.** Follow the proven pattern in `tests/test_i18n_catalog.py`: write
   `session["_language"] = "pl"` and `.save()` **after** `make_login` (login cycles the session, so an
   earlier write is discarded), and also send `HTTP_ACCEPT_LANGUAGE="pl"` — `translation.override`
   alone does not control what the test client renders. The 404 half is `GET /no-such-page/`; the 403
   half reuses test 4's fixture and surface. Assert the PL strings appear and the EN source strings do
   not. This is the test that catches the realistic failure — a msgid added to the template but not to
   the catalog, or left `#, fuzzy`.
7. **Both catalogs are free of obsolete entries.** The three existing `#~` assertions
   (`tests/test_i18n_auth.py`, `tests/test_i18n_notes.py`, `tests/test_tags_i18n.py`) read **only**
   `locale/pl/LC_MESSAGES/django.po`, so they cover half this change. Add the matching `#~`-absence
   assertion for `locale/en/LC_MESSAGES/django.po`.
8. **Static and template wiring guard**, per the repo's standing convention for a new per-page sheet
   (`tests/test_auth_styles.py`, `test_settings_styles.py`, `test_tags_static.py`,
   `test_callout_css.py`). Assert that:
   - `error.css` exists and defines the `.error-page` vocabulary (`.error-page__main`, `__inner`,
     `__code`, `__title`, `__lead`, `__note`, `__path`, `__actions`);
   - it contains `@supports` and **all four** `-webkit-mask-*` longhands — §2 calls these load-bearing,
     so a future "cleanup" of the prefixes must not ship green;
   - the tint is `background-color: var(--text-primary)` and the sheet is token-only with no raw hex,
     mirroring `test_auth_styles.py`'s rule for a new per-page sheet;
   - both templates emit the stylesheet link and the `error-page` body class;
   - `core/static/core/img/learner.png` exists, opens as an `LA`-mode image, and is **≤ 60 KB**.

**Falsification.** Every test above is written to fail first: delete the thing it guards and confirm
it goes red before keeping it. A passing test that has never been seen to fail proves nothing — this
project has shipped vacuous tests before.

**Visual verification is part of "done", not optional**, per the standing `verify-ui-with-screenshots`
convention. Four Playwright shots: 404 and 403, each in light and dark.

- *Reaching the 404:* `live_server.url + "/no-such-page/"` (anonymous is fine).
- *Reaching the 403:* log in as the fixture user, then navigate to the course outline URL — the same
  surface as test 4.
- *Forcing the theme:* **the mechanism differs by page and getting it wrong silently produces the
  wrong pixels.** `core/context_processors.py::_resolve_theme_pref` gives `User.theme` absolute
  precedence for an authenticated user (its docstring: "User.theme is never empty, so for an authed
  user the later rungs are unreachable"), so `data-theme-pref` renders non-empty and `base.html`'s
  pre-paint `if (!pref)` branch never consults the cookie. Therefore: set the `libli_theme` cookie for
  the **anonymous 404** shots, and set `user.theme = "light" / "dark"` on the fixture user for the
  **authenticated 403** shots. `tests/test_e2e_html_element.py` already encodes the latter technique.
- *Widths:* one desktop (1280) and one phone (390) pass — the phone width is where the composition is
  most at risk.

Self-critique the shots before calling the work done, specifically checking: the watermark reads as
atmosphere rather than as a picture; it never fights the text for contrast in either theme; **no hard
horizontal edge appears across the bottom of the page** (the 0.72 ramp is doing its job); **the
figure's head is in frame** (the measurement above says it sits at y=6, so a crop would be immediately
visible); the whole scene is present at 390 px; content paints above the watermark; and the header's
account / bell / mobile-nav dropdowns still overlay page content on both pages (the `z-index` ordering
invariant in §2).

**Worktree DB isolation.** Concurrent worktrees collide on the Postgres `test_libli` database. This
worktree's `.env` already names a unique database (`libli_errpages`, so the test DB is
`test_libli_errpages`). **Verify it, do not overwrite it** — `.env` is untracked, so a clobber is
unrecoverable.
