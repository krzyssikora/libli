# Illustrated error pages (404 / 403)

## Purpose

`templates/404.html` and `templates/403.html` are currently identical bare cards — a heading, one
terse sentence, a "Back to home" button. They are the only pages in libli that a lost or blocked user
is guaranteed to see, and they carry none of the product's voice and none of its visual language.

This work replaces both with an illustrated, bilingual (EN/PL) treatment that:

- tells the user, warmly, what happened and what to do about it;
- gives them the information a useful bug report needs (the address they actually tried);
- shares one decorative learner silhouette rendered as a faint full-bleed watermark, tinted from the
  theme token so light and dark both work from a single asset.

**Out of scope.** `templates/500.html` is deliberately dependency-free — no base template, no
collected static, literal brand colours duplicated inline — because a broken static pipeline is
itself a plausible cause of a 500. It is not touched. No support/contact address is introduced: the
`Institution` model has no contact field, adding one is a separate settings slice, and the "report
this" line is therefore plain prose with no link.

## Architecture / components

Five artifacts, each with one job.

### 1. `core/static/core/img/learner.png` (new asset)

Derived one-off from the supplied `learner_bw.png` (opaque RGB, 1600×672, black figure on white).
Derivation: threshold the source to separate figure from background, then write a **`LA`-mode PNG**
whose luminance channel is 0 and whose **alpha channel carries the silhouette** — alpha is the only
channel a CSS mask consumes, so storing anything else is waste. Generated with Pillow (already a
project dependency, used by the help-shot substrate).

The generation is a one-shot; no script is committed. The derivation parameters (source filename,
threshold) are recorded in a comment in `error.css`, which is where a future maintainer would look.

`learner_wb.png` (the white-on-black inverse) is **not** used — the mask technique makes a second
asset unnecessary.

### 2. `core/static/core/img/README.md` — not created

Explicitly noted so the plan does not invent one. The `error.css` comment is the whole record.

### 3. `core/static/core/css/error.css` (new)

Follows the established per-page CSS pattern (`auth.css`, `doc-page.css`, `settings.css`): a small
standalone sheet linked from the two templates via `{% block extra_css %}`, never appended to the
global `app.css`.

Owns two things:

**The watermark.** A decorative `::after` on `body.error-page`:

```css
body.error-page::after {
  content: "";
  position: fixed; inset: auto 0 0 0;     /* bottom-anchored, bleeds off both edges */
  height: min(46vh, 420px);
  background-color: var(--text-primary);  /* the tint — theme token, not a literal */
  mask-image: url("../img/learner.png");  /* + -webkit- prefix */
  mask-repeat: no-repeat;
  mask-position: center bottom;
  mask-size: cover;
  opacity: .07;
  pointer-events: none;
}
[data-theme="dark"] body.error-page::after { opacity: .10; }
```

Because the fill is `background-color: var(--text-primary)`, the silhouette is warm ink `#1E1C18` in
light and warm parchment `#F2EFE9` in dark — it re-tints itself from the theme with no swap logic,
no second asset, and no `filter: invert()`. `ManifestStaticFilesStorage` rewrites the `url()` at
`collectstatic`, so cache-busting still applies.

It is a CSS pseudo-element, not an `<img>`: purely decorative, absent from the accessibility tree,
no alt text to translate, and `pointer-events: none` so it can never intercept a click.

**Mask-support guard.** The whole `::after` rule is wrapped in
`@supports (mask-image: url("")) or (-webkit-mask-image: url(""))`. Without the guard, an engine
lacking mask support would paint the `background-color` as a solid tinted rectangle across the
bottom of the page — subtle at 7% but wrong. With it, such an engine simply gets no watermark, which
is the correct degradation for decoration.

**Stacking.** The watermark takes `z-index: 0`; `body.error-page .app-header` and
`body.error-page .app-main` are raised to `position: relative; z-index: 1` so content always paints
above it. A negative `z-index` is deliberately *not* used — it risks disappearing behind `body`'s own
background depending on how the app paints its surfaces, and the failure would be invisible in code
review but obvious on screen.

**Page layout.** An `.error-page__inner` block centring the eyebrow / heading / prose / actions
column at a readable measure, with the actions row laid out horizontally and wrapping on narrow
viewports.

### 4. `templates/404.html` (rewritten)

Continues to `{% extends "base.html" %}` — the header, nav, language switch and theme toggle all stay,
so a lost user always has a way out. Adds `{% block body_class %}error-page{% endblock %}` and the
`error.css` link. Structure: eyebrow `404`, `<h1>`, two prose paragraphs, the attempted-path line,
and a "Back to main page" button pointing at `{% url 'home' %}` (replacing the current bare `href="/"`).

**The path line** renders `{{ request_path }}` — Django's `page_not_found` view puts a `quote()`-d
`request.path` in the 404 template context. It is wrapped in `{% if request_path %}` so the block
disappears when the template is rendered without that context, and it is emitted through normal
template autoescaping (never `|safe`), because `request.path` is attacker-controlled.

### 5. `templates/403.html` (rewritten)

The same shell and the same CSS, different copy and one structural difference. Where 404 says
"nothing here", 403 says "here, but not yours".

- **No path line.** Django's `permission_denied` view passes only `{"exception": ...}` — there is no
  `request_path` to show, and inventing one from `request.path` would diverge from the 404's meaning.
- **A conditional Log in button.** When `user.is_authenticated` is false, a "Log in" action is shown
  alongside "Back to main page", carrying `?next={{ request.path|urlencode }}` — for an anonymous
  visitor, logging in is the actual fix, and sending them to the login page without a `next` would
  strand them.

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
**deleted** from both `locale/en` and `locale/pl` — not left as an `#~` obsolete entry, because
`tests/test_i18n_auth.py`, `tests/test_i18n_notes.py` and `tests/test_tags_i18n.py` all assert `#~`
is absent. `We couldn't find that page.` and `You don't have permission to view this page.` are
likewise superseded and get the same treatment. `Page not found`, `Access denied` and `Log in`
survive and are reused.

## Error handling

The failure modes worth designing for are all rendering-time, because these templates run precisely
when something has already gone wrong:

- **Attacker-controlled path.** `request_path` is echoed on the 404. Django `quote()`s it and the
  template autoescapes it; the design forbids `|safe` on that value, and a test asserts an injected
  `<script>` comes back escaped. Getting this wrong would turn the 404 page into reflected XSS.
- **Missing context.** `{% if request_path %}` means the 404 template renders correctly when included
  or rendered directly without the view's context, rather than emitting an empty `You tried:` label.
- **Missing static.** If `learner.png` fails to load, `mask-image` resolves to nothing and — per the
  CSS mask model — the masked element paints nothing. The page loses its decoration and keeps every
  word. No layout depends on the asset's presence.
- **No mask support.** Handled by the `@supports` guard above; degrades to no watermark.
- **A 403 for an anonymous user.** Handled structurally by the conditional Log in action rather than
  left as a dead end.

## Testing

`pytest` with `pytest-django`, per the repo's existing conventions. Django forces `DEBUG=False` under
test, so `client.get(...)` renders the **real** templates — no `override_settings` gymnastics needed.

1. **404 renders the new page.** `client.get("/no-such-page/")` → status 404, the new heading and both
   prose strings present, the old `We couldn't find that page.` absent.
2. **404 echoes the attempted path.** The requested path appears in the response body.
3. **404 escapes the attempted path.** Request a path containing `<script>`; assert the raw tag is
   **not** in the body and the escaped form is. This is the security-relevant test.
4. **403 renders the new page**, driven through a real permission-denied surface rather than by
   rendering the template in isolation.
5. **403 shows Log in only when anonymous** — present for an anonymous client, absent for a logged-in
   one.
6. **Polish renders on both pages.** Following the proven pattern in `tests/test_i18n_catalog.py`
   (set `session["_language"] = "pl"` *and* send `HTTP_ACCEPT_LANGUAGE="pl"` — `translation.override`
   alone does not control what the test client renders): assert the PL strings appear and the EN
   source strings do not. This is the test that catches the realistic failure — a msgid added to the
   template but not to the catalog.
7. **Catalogs stay clean.** The existing `#~`-absence assertions already cover the deletions; the plan
   verifies them rather than adding a duplicate.

**Visual verification is part of "done", not optional.** Playwright screenshots of both pages in both
themes (four shots), self-critiqued before the work is called complete, per the project's standing
`verify-ui-with-screenshots` convention. The specific things to look at: that the watermark reads as
atmosphere rather than as a picture, that it never fights the text for contrast, that it survives a
narrow viewport without swallowing the actions row, and that content genuinely paints above it.

**Worktree DB isolation.** This work runs in a git worktree alongside others, and concurrent worktrees
collide on the Postgres `test_libli` database. The worktree needs its own `.env` with a unique
`DATABASE_URL` before any test run — a known, previously-hit failure mode, not a speculative one.
