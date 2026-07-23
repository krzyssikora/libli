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

Row ink density (exact per-row samples across all 1600 px, not band averages):

| y | 400 | 440 | 476 | 504 | 518 | **525** | 532 | 560 | 616 | 660 |
|---|---|---|---|---|---|---|---|---|---|---|
| ink | 17.1% | 18.4% | 24.9% | 34.7% | 48.8% | **60%** | 73.5% | 86.9% | 95.2% | 100% |

The desk/foreground band occupies the bottom quarter and becomes very nearly solid. **y=525 (78% of
height) is the first row above 60%** — that is the band's effective onset and the anchor for the fade
ramp in §1.

These two measurements drive the entire CSS design below and are the reason it is not the obvious
one:

- **The head sits at the very top of the frame (y=6).** Any vertical crop removes it. This rules out
  `mask-size: cover` in a short box, which would have cropped 22–38% off the top at desktop widths
  and decapitated the figure on every render.
- **The bottom quarter is nearly solid ink.** Painted unmodified it is a full-width tinted rectangle
  with a hard horizontal top edge at y≈525. The fix is the **bottom-fade ramp baked into the alpha in
  §1** — *not* the `@supports` guard, which is mask feature-detection and addresses an unrelated
  failure (a no-mask engine painting an unmasked tinted box). The ramp is not optional decoration.

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
2. **Bottom fade baked into the alpha — a smoothstep ramp starting at `0.60·H`.** Multiply alpha by
   `1 - smoothstep(t)` where `t = clamp((y - 0.60·H) / (0.40·H), 0, 1)` and
   `smoothstep(t) = 3t² - 2t³`. So: `1.0` for `y ≤ 403`, `≈0.82` at y=476, **`≈0.57` at y=525** (the
   band's onset), `≈0.11` at y=616, and `0.0` at the bottom edge.

   Both the start point and the curve are chosen against the measured ladder. A **linear** ramp from
   `0.72·H` — the obvious first choice — still multiplies by **0.78** at y=525, so the band's hard
   *top* edge survives at three-quarters strength: it would dissolve the band's bottom (which nothing
   was complaining about) and leave the actual artifact. Starting at `0.60·H` with a smoothstep curve
   attenuates the onset to ~57% while holding the figure at full strength through y=403, and the
   eased curve avoids substituting a visible ramp-start seam for the edge it removes.

   **What the ramp actually costs, stated plainly:** the person and the laptop both extend to y=671
   (see the table above), so the ramp fades the figure's lower body and the laptop's base along with
   the desk. That is intended and acceptable — that region *is* desk, visually — but a screenshot
   reviewer should expect the lower third of the subject to be attenuated rather than flag it as a
   bug.

**Size budget: ≤ 60 KB.** Measured, the derived file is **17 KB** at native 1600×672 with
`optimize=True`. Downscaling is counterproductive and must not be done "for weight": the same image
resampled to 1280×538 measures **26 KB**, because resampling introduces gradients in what is
otherwise a flat two-tone alpha channel. Test 8 asserts the ceiling.

No generation script is committed. The **recipe** is recorded in a comment in `error.css`, which is
where a maintainer would look: `LA` mode, 1600×672, `alpha = 255 - L`, linear ramp to zero from
`0.72·H`, `optimize=True`. The comment records that the input was a one-off local file and
deliberately **does not** contain the literal `C:/Users/krzys/...` path — `error.css` is committed and
served publicly as static content, and a machine-specific home directory is both a leak and useless
to anyone else.

`learner_wb.png` (the white-on-black inverse) is **not** used — the mask technique makes a second
asset unnecessary.

### 2. `core/static/core/css/error.css` (new)

Follows the established per-page CSS pattern (`auth.css`, `doc-page.css`, `settings.css`): a small
standalone sheet linked from the two templates via `{% block extra_css %}`, never appended to the
global `app.css`.

**The watermark.** A decorative `::after` on `body.error-page`. The box is sized by
**`aspect-ratio`, not by a height guess**, so the mask never has to crop:

```css
@supports (mask-image: none) or (-webkit-mask-image: none) {
  body.error-page::after {
    content: "";
    position: fixed; left: 0; right: 0; bottom: 0;  /* bleeds off both edges */
    margin-inline: auto;                            /* re-centres when max-height clamps — see below */
    aspect-ratio: 1600 / 672;                       /* box matches the artwork */
    max-height: 60dvh;                              /* never dominates a short window */
    background-color: var(--text-primary);          /* the tint — token, not a literal */
    -webkit-mask-image: url("../img/learner.png");
            mask-image: url("../img/learner.png");
    -webkit-mask-repeat: no-repeat;       mask-repeat: no-repeat;
    -webkit-mask-position: center bottom; mask-position: center bottom;
    -webkit-mask-size: contain;           mask-size: contain;
    -webkit-mask-mode: alpha;             mask-mode: alpha;
    opacity: .07;
    z-index: 0;
    pointer-events: none;
  }
  [data-theme="dark"] body.error-page::after { opacity: .10; }
}
```

**Feature detection uses `none`, not `url("")`.** Both detect the same thing, but `none` is an
unambiguously valid value that cannot be matched by the manifest storage's `url(…)` rewrite pattern
at all. `url("")` would work — Django 5.2's `url_converter` returns the match unchanged for an empty
path — but that makes the whole watermark depend on an internal implementation detail, in a file the
manifest backend rewrites, with **no test coverage**: both `config/settings/test.py` and `local.py`
swap in plain `StaticFilesStorage`, so `collectstatic` under the manifest backend is never exercised
in CI. `none` needs no such appeal.

**`mask-mode: alpha` is declared, not assumed.** The asset is `LA` with luminance 0 everywhere, so
the design depends on the alpha channel being the mask source. `match-source` does resolve to alpha
for a raster image, but a luminance interpretation would make the watermark vanish outright (luminance
0 = fully masked) rather than degrade — declaring the mode removes the question.

**Why `aspect-ratio` + `contain` and no breakpoint.** Full-bleed width and a fixed short height are
incompatible with a 2.38:1 artwork whose subject reaches the top edge — one of the three has to give,
and cropping is the one that destroys the picture. Letting width drive height keeps the whole
composition in frame at every width with no breakpoint at all: at 390 px the box is 390×164 and the
scene is a thin full-width band; at 1280 px it is 1280×538. This replaces an earlier
`cover` + `max-width: 900px` scheme that cropped the subject out of frame on phones and cropped the
head off on desktops.

**`max-height: 60dvh` is the one clamp, and `margin-inline: auto` is what makes it survivable.** When
the clamp bites, the *box itself* shrinks to keep its `aspect-ratio`, which over-constrains
`left: 0; right: 0; width: <derived>`. CSS resolves an over-constrained absolutely-positioned box by
**ignoring `right`** (in LTR), so without auto inline margins the box goes flush left and the gutter
lands entirely on one side. Measured in Chromium at 1280×800: `x=0, width=1143` — a 137 px gap on the
**right only**, visibly lopsided; at 1280×600 it is `x=0, width=857`, a 423 px right-hand gutter.
`margin-inline: auto` consumes the slack symmetrically instead: measured `x=68.6` at 1280×800,
`x=125.7` at 1280×720, `x=211.4` at 1280×600, and `x=0` at 390×844 where the clamp never bites.

So on a short window the watermark **pillarboxes** — it shrinks and sits centred with equal gaps
left and right, and stops being full-bleed. That is expected, **but symmetry is not**: the screenshot
self-critique must check that the gaps are equal, because an unequal gap is exactly the signature of
`margin-inline: auto` having been dropped. `contain` (rather than `100% 100%`) is what keeps the
clamped case proportional instead of squashing the figure.

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
out` looks see-through and can't be tapped").

**Both rules live in `error.css`, scoped to `body.error-page`, and outside the `@supports` block**
(they are about the page's own chrome, not about mask support):

```css
body.error-page .app-header { z-index: 2; }                    /* already position:relative in app.css */
.error-page__main           { position: relative; z-index: 1; } /* needs both */
```

**Every `<main>` rule keys off `.error-page__main`, never `.app-main`.** That class exists only on
these two pages, so it is self-scoping — and it is also what test 8 asserts the sheet defines. Keying
the rules off `.app-main` instead would leave `.error-page__main` added to the element and never
used, failing test 8's first assertion while looking correct.

The scoping is not stylistic — it is a hard requirement. Written globally in `app.css`,
`.app-main { position: relative; z-index: 1 }` would turn every `<main>` in the app into a stacking
context and trap the `position: fixed` overlays that live inside `{% block content %}` beneath the
newly-raised header: `.modal` (`app.css`, used by `templates/courses/catalog.html`), `.unit-drawer`
and the editor overlay (`courses/css/courses.css`, `editor.css`), and `.math-modal` at `z-index: 1000`.
All of them would paint and hit-test under the opaque header band — the same bug the `app.css` comment
memorialises, inverted. The error pages have no such overlays, so the scoped form is safe.

A negative `z-index` on the watermark is deliberately *not* used — it risks disappearing behind
`body`'s own background.

**Page structure.** The markup goes in `{% block content %}`, which `base.html` renders inside
`<main>`; `{% block main_class %}` only re-classes that inherited `<main>` to
`app-main error-page__main`. The `.card` wrapper is dropped — the watermark treatment wants an open
page, not a boxed panel.

**Vertical centring is derived, never guessed.** The tempting
`min-height: calc(100vh - 2 * var(--space-6))` copied from `.auth-main` is *wrong here*: that
precedent works because `templates/allauth/layouts/entrance.html` **replaces** `{% block header %}`, so
auth pages have no `.app-header` at all. The error pages deliberately keep the header (≈57 px:
`var(--space-3)` padding × 2 + a 32 px control row + 1 px border, and more below 640 px where the
header wraps), so subtracting only the main padding overshoots and every error page would render a
stray vertical scrollbar. Instead, let layout do the arithmetic:

```css
body.error-page   { display: flex; flex-direction: column; min-height: 100dvh; }
.error-page__main { flex: 1; display: flex; flex-direction: column; justify-content: safe center; }
```

No hard-coded header height, and `100dvh` rather than `100vh` so a mobile browser's collapsing URL bar
does not overshoot either. `safe center`, not bare `center`: this spec explicitly contemplates a
2 000-character attacker-supplied path, and centring an over-tall flex column is the classic way to
push its top out of the scrollable area where it can never be reached. `safe` degrades to `start`
exactly when overflow would occur.

Both classes apply to `<main>` (`app-main error-page__main`), so `.app-main`'s
`max-width: 960px; margin: 0 auto; padding: var(--space-8) var(--space-5)` **stays in force and is
deliberately kept** — 960 px is a fine outer bound and the inner column is narrower anyway. The
`{% if messages %}` alerts `base.html` renders inside `<main>` become flex children; they are given
`width: 100%` — written scoped as `.error-page__main > .alert { width: 100%; }`, since `.alert` is a
global class in `app.css` and an unscoped rule would leak.

Inside, wrapped in `<div class="error-page__inner">` at `max-width: 40rem`. **The table is DOM
order.** The path line sits directly under the lead, because the lead's own advice is "check the
address you entered" — the address must be the next thing the eye meets, with the report-it sentence
after it.

| # | Element | Tag | Class | Type / colour |
|---|---|---|---|---|
| 1 | eyebrow (`404` / `403`) | `<p>` | `.error-page__code` | `3rem`, weight 700, `var(--accent)`, `--heading-letter-spacing`, tight bottom margin |
| 2 | heading | `<h1>` | `.error-page__title` | `1.75rem`, weight 600, `var(--text-primary)` |
| 3 | lead paragraph | `<p>` | `.error-page__lead` | `1.0625rem`, `var(--text-primary)`, line-height 1.6 |
| 4 | attempted path (**404 only**) | `<p>` wrapping a `<code>` | `.error-page__path` | label `0.875rem` `var(--text-tertiary)`; the `<code>` is styled via the descendant selector **`.error-page__path code`** in `--font-mono`, `0.875rem`, `var(--surface-sunken)` chip with `--radius-sm` and `--border-subtle` |
| 5 | report / advice paragraph (**404 only**) | `<p>` | `.error-page__note` | `0.9375rem`, `var(--text-secondary)` |
| 6 | actions row | `<p>` | `.error-page__actions` | — |

Left-aligned, not centred: the lead and note are multi-line prose, and centred ragged prose is harder
to read. Vertical rhythm is `var(--space-4)` between blocks and `var(--space-6)` above the actions row.
Colours are tokens only — no raw hex anywhere in the sheet, per `test_auth_styles.py`'s rule for a new
per-page sheet.

The actions row is a flex row with `flex-wrap: wrap` and `gap: var(--space-3)`, so a second button
drops to its own line on narrow screens. `.error-page__path` sets `overflow-wrap: anywhere` —
`request.path` is attacker-controlled in *length* as well as content, and a 2 000-character unbroken
path would otherwise blow out the measure or force horizontal page scroll.

### 3. `templates/404.html` (rewritten)

Continues to `{% extends "base.html" %}` — the header, nav, language switch and theme toggle all stay,
so a lost user always has a way out. (One caveat, knowingly out of scope: `base.html`'s brand link is
`href="{% url 'home' %}"`, which is `@login_required` — the same trap this spec fixes for the action
button. It is pre-existing on *every* page in the app, so changing it belongs in its own diff; the
"way out" claim here rests on the in-page action button, which does point at `landing`.) Opens with
`{% load static i18n %}` (the current file loads only
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

**Element sequence: `__code`, `__title`, `__lead`, `__actions` — four of the six.** `.error-page__note`
and `.error-page__path` are **404-only**: the 403 has no path to show (below), and its "ask your
administrator" advice is already folded into the lead sentence rather than split into a second
paragraph. An implementer should not invent a fourth paragraph to fill `__note`.

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

**Both locales must be regenerated, and both compiled catalogs are part of the diff.**
`locale/en/LC_MESSAGES/django.mo` and `locale/pl/LC_MESSAGES/django.mo` are both tracked in git.
`docs/development/conventions.md` documents the cycle as `makemessages -l pl` **only** — following
that literally would never touch `locale/en/LC_MESSAGES/django.po`, so the retired msgids would stay
live rather than becoming obsolete, the three new msgids would never appear, and test 7's brand-new
`locale/en` `#~`-absence assertion would pass **vacuously against a file nobody regenerated**. Run
`makemessages -l pl -l en`, then the manual `#~` / fuzzy cleanup, then `compilemessages`. The `.po`
edits alone would leave the runtime reading a stale catalog and the Polish render test failing.

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

**Test files.** Tests 1–5 in `tests/test_error_pages.py`, tests 6–7 in
`tests/test_i18n_error_pages.py`, test 8 in `tests/test_error_page_styles.py`, the screenshots in
`tests/test_e2e_error_pages.py` — one narrow file per concern, matching the repo's existing
`test_i18n_*` / `test_*_styles` / `test_e2e_*` split. The i18n file's naming is what makes the
`#~`/fuzzy guard discoverable next to its siblings.

**The no-access 403 fixture shape**, used by tests 4, 5, 6 and both 403 screenshots.
`courses/access.py` grants access if the user `is_staff` **or** owns the course **or** is enrolled
**or** teaches a non-archived group attached to it — "no access" is four negatives, not one, and the
project's factories do not all produce a prod-shaped non-staff user. Pin it explicitly: a user who is
**not** `is_staff`, **not** `is_superuser`, **not** the course's `owner`, has **no** `Enrollment` on
it, and teaches **no** group attached to it; plus a course owned by somebody else. Name the factory
calls in the test.

**It is a shared *shape*, not a shared fixture object** — the two harnesses cannot use one.
`tests/factories.py`'s `make_login(client, username)` calls `client.force_login()`, which authenticates
a *Django test client*; a Playwright `page` has no visibility into that session. So tests 4–6 use the
`client`-based fixture, and the e2e module re-seeds the same user/course shape and logs in by driving
the real form at `/accounts/login/` with `tests.factories.TEST_PASSWORD`, per the precedent in
`tests/test_e2e_html_element.py`. The e2e user additionally needs a verified email
(`make_verified_user`) for that form to succeed.

**The e2e module must copy two more things from that precedent, both non-optional:**

1. `pytestmark = pytest.mark.e2e` at module top. `pyproject.toml` sets
   `addopts = "-q -m 'not e2e'"`, so an *unmarked* module silently joins the default suite and CI's
   unit job and launches Chromium there — the runaway-browser failure this project has already hit.
   The module is run explicitly with `-m e2e`.
2. The `scope="session", autouse=True` fixture setting `DJANGO_ALLOW_ASYNC_UNSAFE=true`. The module
   seeds a user and a course from the test thread while sync Playwright is live; without it the ORM
   calls raise `SynchronousOnlyOperation`.

1. **404 renders the new page.** `client.get("/no-such-page/")` → status 404, the new heading and both
   prose strings present, the old `We couldn't find that page.` absent.
2. **404 echoes the attempted path — asserted on the new markup, not on a bare substring.**
   `base.html`'s language-switch form renders `<input type="hidden" name="next" value="{{ request.path }}">`
   on every page, so for `GET /no-such-page/` the substring `/no-such-page/` is **already** in the body
   before a single line of `.error-page__path` exists. A bare-substring assertion is therefore vacuous
   — the same trap test 5 avoids for `Log in`. Assert the rendered element instead:
   `f"<code>{path}</code>"`. This requires the `<code>` element to carry **no attributes and no
   surrounding whitespace** (it is styled via the `.error-page__path code` descendant selector, per
   §2), so the exact string matches verbatim.
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
7. **Both catalogs are clean.** The three existing assertions (`tests/test_i18n_auth.py`,
   `tests/test_i18n_notes.py`, `tests/test_tags_i18n.py`) read **only**
   `locale/pl/LC_MESSAGES/django.po`, so they cover half this change. Add the matching guard for
   `locale/en/LC_MESSAGES/django.po`, asserting **both** `"#~" not in text` **and**
   `"#, fuzzy" not in text` — exactly mirroring its PL sibling
   `test_i18n_auth.py::test_po_catalog_clean`. Guarding only `#~` would leave an EN fuzzy entry
   unguarded, and §Catalog churn's own instruction is about both catalogs.
8. **Static and template wiring guard**, per the repo's standing convention for a new per-page sheet
   (`tests/test_auth_styles.py`, `test_settings_styles.py`, `test_tags_static.py`,
   `test_callout_css.py`). Assert that:
   - `error.css` exists and defines the `.error-page` vocabulary (`.error-page__main`, `__inner`,
     `__code`, `__title`, `__lead`, `__note`, `__path`, `__actions`);
   - it contains `@supports` and **all four** `-webkit-mask-*` longhands — §2 calls these load-bearing,
     so a future "cleanup" of the prefixes must not ship green;
   - the tint is `background-color: var(--text-primary)` and the sheet is token-only with no raw hex,
     mirroring `test_auth_styles.py`'s rule for a new per-page sheet;
   - **the stacking invariant holds**: parse the three `z-index` values out of `error.css` and assert
     `watermark < .app-main < .app-header`. §2 argues this reproduces an already-shipped regression if
     inverted, so leaving it to a human eyeballing screenshots is not enough — a later edit that drops
     `z-index: 1` from `.app-main` or swaps the two must go red;
   - both templates emit the stylesheet link and the `error-page` body class;
   - `core/static/core/img/learner.png` exists, opens as an `LA`-mode image, is **exactly 1600×672**,
     and is **≤ 60 KB**. The dimensions assertion is not decoration: §2 hard-codes
     `aspect-ratio: 1600 / 672`, and §1 explicitly contemplates the PNG being re-derived later — a
     re-derivation at another size would silently pillarbox or float the watermark with nothing going
     red. Assert the matching `aspect-ratio: 1600 / 672` string in `error.css` too, so the asset and
     the stylesheet fail *together*. (The project has learned this once already, via the help-shot
     dims guard.)

**Falsification.** Every test above is written to fail first: delete the thing it guards and confirm
it goes red before keeping it. A passing test that has never been seen to fail proves nothing — this
project has shipped vacuous tests before.

**Visual verification is part of "done", not optional**, per the standing `verify-ui-with-screenshots`
convention. **Six Playwright shots, countable, with viewports pinned to width *and height*:**

| # | Page | Theme | Viewport | Watermark regime |
|---|---|---|---|---|
| 1–2 | 404, 403 | light | **1280×900** | unclamped — full-bleed, box 1280×538 |
| 3–4 | 404, 403 | dark | **1280×900** | unclamped |
| 5–6 | 404, 403 | light | **390×844** | unclamped — box 390×164 |

Height must be pinned, not defaulted: pytest-playwright's default viewport is **1280×720**, where
`60dvh` = 432 px and the box clamps to ~1029 px wide — so every "1280" shot would land in the
*clamped* regime and the full-bleed rendering §2 reasons about would never be photographed. 1280×900
puts the desktop shots in the unclamped case. The phone width is a composition risk, not a colour one,
so it does not need a second theme sweep.

The shots are **verification artifacts and are not committed**: write them to the session scratchpad
directory, review them, and leave them out of the diff. (This differs from the help-shot substrate,
which deliberately commits its PNGs under `core/static/core/img/help/` because they are shipped page
content.)

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
- *Viewports:* per the matrix above — 1280×900 and 390×844, both dimensions set explicitly.

Self-critique the shots before calling the work done, specifically checking:

- the watermark reads as atmosphere rather than as a picture, and never fights the text for contrast
  in either theme;
- **no hard horizontal rule appears where the desk band begins** (y≈525 of the artwork — this is the
  artifact the smoothstep ramp exists to kill, and it is the band's *top* edge, not its bottom);
- **the figure's head is in frame** — it sits at y=6, so any vertical crop is immediately visible;
- the lower third of the figure and the laptop base are *expected* to be faded (see §1) — not a bug;
- the whole scene is present at 390 px;
- content paints above the watermark, and the header's account / bell / mobile-nav dropdowns still
  overlay page content on both pages (the `z-index` invariant in §2);
- **left and right gutters are equal** if any shot does land in the clamped regime — an unequal gutter
  is the signature of `margin-inline: auto` having been dropped.

**Worktree DB isolation.** Concurrent worktrees collide on the Postgres `test_libli` database. This
worktree's `.env` already names a unique database (`libli_errpages`, so the test DB is
`test_libli_errpages`). **Verify it, do not overwrite it** — `.env` is untracked, so a clobber is
unrecoverable.
