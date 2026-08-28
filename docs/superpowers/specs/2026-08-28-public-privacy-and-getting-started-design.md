# Public privacy notice and getting-started page

## Purpose

The landing footer currently renders three inert `<span>` elements — `Privacy`, `Help`, and
`EN / PL` (`templates/core/landing.html:31-33`). They were ported verbatim from the accepted
mockup (`docs/mockups/landing_accepted.html:112`) as deliberate placeholders; the Phase 0d-2
spec records the intent explicitly:

> **Landing footer:** brand + school name + Privacy/Help **placeholders** + a **static,
> display-only** `EN / PL` indicator (**not** a second switch — the header's language switch is
> the only interactive control).

Nothing was ever built behind them. This work makes two of them real and deletes the third.

Three things drive the design:

1. **libli.pl is a live demo aimed at prospective customers.** The person reading that footer is
   mostly a school decision-maker or DPO evaluating whether to trust libli with pupils' data — not
   a student who forgot a password. The privacy notice is therefore a sales asset as much as a
   compliance artifact, and the getting-started page must speak to an evaluator first.
2. **A privacy notice must be reachable at the point of account creation.** The login/signup pages
   (`templates/allauth/layouts/entrance.html`) currently have no footer at all. That is the
   placement that matters most.
3. **The repo is re-deployable.** `Institution` is a single-row, runtime-editable model
   (`institution/models.py:17`), so anything hardcoded into the repo ships to every future
   deployment. Controller identity must come from settings, an admin must be able to replace the
   shipped text wholesale, and **no shipped sentence may assert a fact a deployment can change**
   (the recorded exceptions are listed in §Accepted decisions).

## Background: what exists today

- `config/urls.py:22` mounts `core.urls` at the **root**, so `/help/` already belongs to the
  staff help area (`core/urls.py:17`). That view is `@login_required` and its topics are gated on
  role marker perms (`core/views_help.py:14`). **The public page cannot live at `/help/`.**
- Every content path in the application is `@login_required`. The landing page is the only
  anonymous surface, and `landing` (`core/views.py:63`) **bounces authenticated users to `home`**.
  These two pages are the **first public content surface** in the codebase.
- **`localized_doc_path` and `DOCS_ROOT` are reused from `core/help.py`; nothing else is.**
  `localized_doc_path` returns the `<name>.<code>.md` sibling when it exists on disk, else the
  English base. `render_markdown_doc` is deliberately **not** reused (see §Sanitisation), so the
  `src="static:REL"` and `{el:slug}` sentinels **do not work in `docs/public/`**.
- `.dockerignore` keeps `docs/help`, so a new `docs/public/` ships in the production image.
- **`core` has no `models.py` and no `migrations/` package.** `institution` has both.
- **`get_site_config()` has two return paths.** `_build()` (`core/services.py:70`) returns
  `dict(_DEFAULTS)` when no `Institution` row exists, and a literal dict otherwise. Any new key
  must be added to **both**, or a fresh install `KeyError`s. Every line of that literal dict uses
  the `inst.<field> or _DEFAULTS["<field>"]` idiom **except** `"onboarded": inst.onboarded` — the
  one boolean, deliberately read bare.
- The settings area is **one page with query-param tabs**: `TABS` (a 7-tuple), `_active_tab`,
  `_index_url(tab)`, `_settings_context(request, inst, active_tab, *, branding=None, …,
  support=None)` — a **fixed keyword signature** — and `_action(request, form_cls, ctx_key, tab,
  success_msg)`, which binds a **ModelForm on `Institution`**. The `settings` view renders every
  panel on GET.
- `templates/base.html` defines `head_title`, `header`, `main_class`, `content`, `extra_body`,
  `extra_js`. **There is no footer block**; `</main>` is followed immediately by the `ui.js` and
  `scroll_affordance.js` script tags, then `extra_body`/`extra_js` and the conditional support
  dialog. The landing footer lives inside `{% block content %}`, so it is not a precedent that
  transfers to the entrance layout, which does not own `content`.
- `set_ui_language` (`core/views.py:169`) carries **only `@require_POST`**, and
  `LanguageSeederMiddleware` writes the session language key on a plain anonymous request whose
  resolved language is not enabled. **An anonymous visitor can acquire a `sessionid` cookie
  without ever logging in.**
- **No cookie lifetimes are configured.** Neither `SESSION_COOKIE_AGE`,
  `SESSION_EXPIRE_AT_BROWSER_CLOSE` nor `CSRF_COOKIE_AGE` appears under `config/settings/`, so
  Django's defaults apply: `sessionid` is a **two-week persistent** cookie (1 209 600 s), *not* a
  session cookie, and `csrftoken` is ~**one year** (31 449 600 s).
- **`MESSAGE_STORAGE` is not configured**, so `FallbackStorage` writes a `messages` cookie first —
  and allauth uses messages heavily on the login/signup flow.
- **`notification_retention_days = 0` means "never purge".** `notifications/retention.py:69` gates
  the age purge on `if days > 0`, and the query filters `read_at__isnull=False` — so the window
  applies to **read** notifications only, and unread ones are never age-purged. The purge itself
  is an operator-installed cron line (`docs/deployment.md:407`), not something the image runs.

## Scope

**In scope:** two public pages, their content in English and Polish, the rendering mechanism, the
admin override model and its editing UI, five new `Institution` fields *and their editing UI*, a
new `footer` block in `base.html`, footer links on the landing and entrance layouts, the CSS for
the new surfaces, the i18n catalogue work, and deletion of the `EN / PL` span.

**Files touched:** `institution/models.py`, `institution/migrations/`, `institution/forms.py`,
`institution/views_manage.py`, `institution/urls.py`, `institution/admin.py`,
`core/public_pages.py` (new), `core/views_public.py` (new), `core/urls.py`, `core/services.py`,
`core/static/core/css/app.css`, `core/static/core/css/auth.css`, `templates/base.html`,
`templates/core/landing.html`, `templates/core/public_page.html` (new),
`templates/allauth/layouts/entrance.html`, `templates/institution/manage/settings.html`,
`templates/institution/manage/_tabs.html`, `docs/public/*.md`, `locale/pl/LC_MESSAGES/`.

**Out of scope:** authenticated pages render no footer. The staff help area is untouched. No
cookie-consent banner (see §The consent-banner decision). No crawler configuration — no
`robots.txt`, no sitemap; only a meta description on the shared template is in scope.

## Architecture

### URLs

Two top-level routes in `core/urls.py`, **without** `login_required`:

| Path | Name | Page |
|---|---|---|
| `/privacy/` | `core:privacy` | Privacy notice |
| `/getting-started/` | `core:getting_started` | Getting started |

Views live in a new `core/views_public.py`.

**Accepted wart:** the footer label reads "Help" but points at `/getting-started/`, because
`/help/` is the staff area.

### Where the model lives

`PublicPage` goes in **`institution`**, not `core`, which has no `models.py` and no `migrations/`
package — putting it there would mean creating the app's first model module *and* its first
migrations package, a needless deploy-ordering wrinkle on a live instance. One migration adds the
model **and** the five new `Institution` fields together.

```
class PublicPage:
    slug           CharField(max_length=32)          # no choices - see below
    language       CharField(max_length=5)           # always a BARE code ("en", "pl")
    body_markdown  TextField(blank=True)
    updated_at     DateTimeField(auto_now=True)

    UniqueConstraint(fields=["slug", "language"], name="uniq_publicpage_slug_language")
    Meta.ordering = ["slug", "language"]
    __str__ -> f"{slug} [{language}]"
```

Registered in the Django admin (`institution/admin.py`): the model holds live legal text and keeps
no history, so a superuser must be able to inspect rows without going through the settings panel.

`slug` carries **no `choices`**: Django serialises `choices` into migrations, so adding a page —
or editing a title — would emit a spurious `AlterField`, and the `PAGES` titles are
`gettext_lazy` objects with no business in a migration file. **Consequence, stated so it is not a
surprise:** removing a slug from `PAGES` leaves its rows in the database, invisible to the panel
(which iterates the registry) and unreachable by the resolver (which raises `KeyError`). Such rows
are inert and are cleaned up by hand via the Django admin — the slug-axis counterpart of the
stale-language handling below, deliberately given the cheaper treatment because removing a page is
a code change, whereas disabling a language is a runtime action.

### New `Institution` fields

| Field | Type | Notes |
|---|---|---|
| `controller_name` | `CharField(max_length=200, blank=True)` | Falls back to `name` when blank |
| `controller_address` | `TextField(blank=True)` | Multi-line; see the `nl2br` rule |
| `contact_email` | `EmailField(blank=True)` | |
| `supervisory_authority` | `CharField(max_length=200, blank=True)` | Falls back to a neutral phrase |
| `demo_instance` | `BooleanField(default=False)` | Gates every demo claim on both pages |

All blank/False by default, so an existing deployment migrates without answering anything.

**`core/services.py` must be extended in both return paths.** `_build()` gains **six** keys — the
five above plus `notification_retention_days`, which the notice cites and which is not in the
bundle today — and `_DEFAULTS` gains the same six, so the no-`Institution`-row path stays
key-identical. Without that, `cfg["controller_name"]` would `KeyError` and 500 the public pages on
a fresh install.

**Falsy rule — do not copy the surrounding idiom.** `notification_retention_days` and
`demo_instance` must be **bare attribute reads**, following `"onboarded": inst.onboarded`, *not*
the `inst.<field> or _DEFAULTS[...]` pattern every other line uses. `0` and `False` are meaningful
values here: `or`-coalescing would silently rewrite a deliberate `0` ("never purge") to `90`, and
would make a real `False` unrepresentable the moment a default flipped. Only the four string
fields coalesce.

### New module: `core/public_pages.py`

Owns `PAGES` (slug → markdown base path, `gettext_lazy` title, `gettext_lazy` meta description,
URL name), the sanitiser allow-lists, `normalize_lang`, `render_public_page`, and the token
passes. It does **not** extend `core/help.py`, whose docstring states its input is trusted repo
markdown to which "the renderer applies no sanitization".

### Sanitisation: a document allow-list, not the rich-text one

Rendered markdown is sanitised with `nh3`, following the pattern of `courses/sanitize.py` but
**not reusing `sanitize_html`**, whose `ALLOWED_TAGS` (`courses/sanitize.py:15`) is tuned for
rich-text *body* content and contains no `h1`, `table`, `thead`, `tbody`, `tr`, `th`, `td`, or
`hr`. Passing a document through it would silently delete the cookie table and flatten headings.

```
PUBLIC_PAGE_TAGS = {
    h1 h2 h3 h4 h5 h6 p br ul ol li strong b em i code pre blockquote a hr
    table thead tbody tr th td
}
PUBLIC_PAGE_ATTRIBUTES  = {"a": {"href", "title", "rel"}}
PUBLIC_PAGE_URL_SCHEMES = {"http", "https", "mailto"}
```

`br` is included because a two-space line ending emits `<br />` (verified) which would otherwise
vanish silently; `h5`/`h6` for the same reason. **`img` is excluded on purpose** — these pages are
prose, and an image tag on an anonymous surface whose content an admin can edit is avoidable
attack surface.

**Authoring note:** because `PUBLIC_PAGE_ATTRIBUTES` permits no `style`, markdown's `tables`
column-alignment syntax (`|:---:|`) has **no effect** — the extension emits
`style="text-align: …"` on `th`/`td`, which nh3 drops silently.

**On the scheme list.** `nh3` **already blocks `javascript:` and `data:` by default** (verified:
both are stripped with and without `url_schemes`). `PUBLIC_PAGE_URL_SCHEMES` does *not* add
protection against those two; what it excludes is `ftp:`, `tel:`, `magnet:` and friends. The
inherited comment at `courses/sanitize.py:41` claiming otherwise is wrong, and the test table
reflects measured behaviour rather than that comment.

**Both content sources go through the same sanitiser** — no trust split, so no branch to get
wrong later.

### Language normalisation

One helper, used on **every** path that touches a language code — the DB lookup, the file lookup,
the override **write** path, and the settings panel's language list:

```
def normalize_lang(lang):  # (lang or "en").split("-")[0]
```

Load-bearing in both directions. On read: a request where `translation.get_language()` returns
`pl-PL` — or `None` — would otherwise miss a `pl` override row. On write: `enabled_languages` is a
runtime-editable JSON list, so an admin can put `pl-PL` in it, and the panel would create a row
the normalised lookup can never match. **`PublicPage.language` always stores a bare code.**

### Content resolution

`render_public_page(slug, lang, cfg)` returns `(html, resolved_lang)`. `cfg` is the site-config
bundle, supplied by the view — passing it in keeps the function injectable from unit tests and
gives the tokens a single source of truth.

1. `code = normalize_lang(lang)`.
2. **Admin override** — a `PublicPage` row for `(slug, code)` whose `body_markdown` is non-blank
   wins. A blank row is treated as *no override*. `resolved_lang = code`.
3. **Repo template** — otherwise `rel = localized_doc_path(PAGES[slug].path, code)` under
   `DOCS_ROOT`. The path comes from the registry, never an f-string.
   **`resolved_lang` is derived from the path `localized_doc_path` actually returned:**
   `resolved_lang = code if rel != PAGES[slug].path else "en"`. This is stated explicitly because
   `localized_doc_path` returns a *path*, not a language, and silently falls back to the English
   base — an implementer otherwise has to invent the derivation. The comparison is correct when
   `code == "en"` too (the paths are equal, yielding `"en"`).
4. Then: `markdown.markdown(..., extensions=["fenced_code", "tables"])` → `nh3.clean(...)` →
   block-token pass → inline-token pass.

On the `OSError` path the function returns `("", code)` — an empty body has no language of its
own, and reporting the requested language keeps the wrapper consistent with the rest of the page.

**The chain does not fall back across languages.** A missing `pl` override does *not* borrow the
`en` override; it falls to the `pl` repo template. Serving English text to a Polish reader is the
worse failure, so language-appropriate content wins. The real risk this creates — an admin
overriding one language only, leaving the live notice saying substantively different things in two
languages — is handled in the UI: **the panel warns when a page is overridden in some but not all
enabled languages.**

A shipped template always exists, so a page always renders and the footer links are always live.
**Deleting the override row is the "revert to default" action.**

### Token substitution

Identity is injected by `{libli:NAME}` token passes mirroring the existing `{el:slug}` sentinel
idiom, deliberately **not** by the Django template engine (which on the override path would be a
template-injection vector). Substitution runs **after** sanitisation.

**The precise invariant:** a substituted value contributes only text, plus — for
`controller_address` alone — `<br>` elements generated by the escape-then-`nl2br` step. **No value
can ever contribute a tag it contains itself.**

**Substitution uses a function replacement** — `re.sub(pattern, lambda m: value, html)` — never a
string replacement. `re.sub` interprets `\1`, `\g<0>` and a trailing backslash in the *replacement*;
`controller_name`, `controller_address` and `contact_email` are admin-controlled and the
demo-notice text is translator-controlled, so a stray backslash would otherwise raise `re.error`
(a 500 on the public surface) or corrupt the output. `html.escape` does not neutralise backslashes.

**Two passes, because a block token cannot work as an inline one.** Verified:
`markdown.markdown("{libli:demo_notice}\n\nhi")` yields `<p>{libli:demo_notice}</p>` — the token
is *already wrapped in a paragraph* before substitution. Substituting a `<p>…</p>` block there
would produce invalid nested paragraphs; substituting `""` would leave a stray empty `<p></p>` on
every non-demo page.

**1. Block pass** — matches the token *with its enclosing paragraph*
(`<p>\s*\{libli:demo_notice\}\s*</p>`) and replaces the **whole match**: the notice block when
`demo_instance` is true, the empty string when false. Only `demo_notice` is a block token.

**2. Inline pass**, which runs **after** the block pass and over the whole document *including*
the notice block just inserted. Its algorithm is pinned, because the block pass's is:

```
re.sub(r">([^<]*)<", lambda run: substitute_run(run.group(1)), html)
    where substitute_run applies re.sub(r"\{libli:(\w+)\}", replace_one, run_text)
    and replace_one returns:
        - html.escape(value)                      for every inline token
        - nl2br(html.escape(value))               for controller_address only
        - the literal matched text                for an unknown token
```

Operating on text runs between `>` and `<` is what makes "text content only" mechanical rather
than aspirational, and it is why running after the block pass is safe: the inserted notice's
`class="public-page__notice"` attribute lies outside any `>…<` run and therefore cannot be
corrupted. The pass does **not** exempt `<pre>`/`<code>`, so authors must not show token syntax
verbatim in a code fence.

**Tokens are never substituted inside attribute values.** Verified:
`markdown.markdown("[mail](mailto:{libli:contact_email})")` yields
`<a href="mailto:{libli:contact_email}">`, and nh3 preserves it — so substituting there would
write an admin-controlled value into a URL *after* the URL was vetted, and a whole-href token
would let a value choose the scheme.

**Authoring constraint, and it is not optional:** no `{libli:…}` token may appear inside a
markdown link target or any other attribute position. `[write to us](mailto:{libli:contact_email})`
would publish a literal `mailto:{libli:contact_email}` href — a broken link on the very section
(§Content item 9) that tells a data subject how to exercise their rights. `{libli:contact_email}`
renders as plain text only. A shipped-markdown test asserts no `{libli:` token survives inside an
attribute in the rendered output of all four shipped files.

| Token | Kind | Source |
|---|---|---|
| `{libli:controller_name}` | inline | `cfg["controller_name"]` or `cfg["name"]` when blank |
| `{libli:controller_address}` | inline | `cfg["controller_address"]`, escaped then `\n` → `<br>` |
| `{libli:contact_email}` | inline | `cfg["contact_email"]` |
| `{libli:site_name}` | inline | `cfg["name"]` |
| `{libli:supervisory_authority}` | inline | `cfg["supervisory_authority"]`, else a neutral phrase |
| `{libli:embed_domains}` | inline | `settings.ALLOWED_EMBED_DOMAINS`, comma-joined; neutral phrase when empty |
| `{libli:notification_retention_days}` | inline | `cfg["notification_retention_days"]`; see the zero-case |
| `{libli:demo_notice}` | **block** | The notice when `cfg["demo_instance"]`, else empty |

Every token reads from `cfg` except `embed_domains`, a Django setting rather than institution
state. **An unknown token is left as literal text**, matching the `{el:slug}` contract.

**Every deployment-dependent token has a defined degenerate case**, because a token that renders
nothing turns its surrounding sentence into a fragment:

- `controller_name` blank → `cfg["name"]`.
- `supervisory_authority` blank → "your national data protection authority".
- `embed_domains` empty (a deployment may set `LIBLI_ALLOWED_EMBED_DOMAINS` to nothing) → a
  neutral phrase stating no embed providers are enabled.
- **`notification_retention_days == 0` → a neutral phrase ("kept until deleted"), not the digit
  `0`.** Rendering "purged after 0 days" would assert the exact opposite of the truth:
  `notifications/retention.py:69` skips the age purge entirely at 0.

`{libli:demo_notice}` expands to a pre-built `<p class="public-page__notice">…</p>` built from a
translated `gettext` message — never from user input — so it is safe by construction.
**Authoring constraint: it MUST be a paragraph of its own at top level.** Inside a list item or
mid-sentence markdown emits no wrapping `<p>`, the regex will not match, and the literal token
text renders on a live page — silently swallowing the do-not-enter-real-pupil-data warning. The
shipped markdown is tested for this directly, so a misplacement fails CI.

### Admin editing UI

A new eighth tab, `public-pages`. The delta from the existing pattern, stated precisely because
this section does **not** simply follow it:

- `TABS` gains an eighth entry; `_tabs.html` gains its link and `settings.html` its `data-tab`
  panel.
- `_settings_context` gains **two** new keyword arguments: `public_pages` (the `Institution`-fields
  form) and `page_overrides`, **always built on the display path** because the `settings` view
  renders every panel on GET.
- **`page_overrides` has a pinned shape** — one dict per registered slug, since the template, the
  textarea naming, the stale marking and both warnings all read it:

  ```
  [{"slug", "title", "rows": [{"language", "value", "enabled": bool}],
    "partial": bool, "missing_demo_notice": bool}, ...]
  ```

  `partial` and `missing_demo_notice` are computed in `_settings_context`, never in the template.
- The panel contains **two independent sibling `<form>` elements** (HTML forbids nesting), each
  with its own action, `{% csrf_token %}` and submit control:
  - `institution:settings_public_pages` — the five `Institution` fields, via a new
    `PublicPagesForm(ModelForm on Institution)`. This one **does** reuse `_action(...)`.
  - `institution:settings_page_overrides` — the override rows. This **cannot** reuse `_action`,
    which binds a single ModelForm to `Institution`.
- **The override view's iteration set is exactly the union the panel builds**: `PAGES` ×
  `normalize_lang(enabled_languages)`, **unioned with the `(slug, language)` pairs of existing
  `PublicPage` rows**. This is stated because the narrower reading — iterate only enabled
  languages — would render a stale row's textarea, accept its submission and silently ignore it,
  making the row undeletable and defeating the reason stale rows are listed at all.
- It reads `request.POST.get(f"override-{slug}-{language}", "")` for each pair and **never parses
  submitted key names** — `getting-started` contains hyphens, so `override-getting-started-pl`
  cannot be split unambiguously. Per pair: write the row when non-blank, **delete** any existing
  row when blank.
- Both views are `@login_required` +
  `@permission_required("institution.change_institution", raise_exception=True)` — the permission
  every sibling settings view uses — and both keep the POST-only contract with a GET redirect to
  `_index_url("public-pages")`.

The panel lists **each page × each normalised enabled language**, each with a textarea holding the
current override, **plus any existing row whose language is no longer enabled**, marked as such —
without which, removing a language from `enabled_languages` would hide its rows from the panel
while they continued to be served to anyone whose session still resolved to that code.

**Two warnings, both computed server-side:**

1. **Partial override** — a page overridden in some but not all enabled languages.
2. **Missing demo notice** — when `demo_instance` is true and a non-blank override for a page does
   not contain `{libli:demo_notice}`. Without this, an admin pasting their own notice — who has
   never seen the token and has no reason to include it — silently removes the
   do-not-enter-real-pupil-data warning from a live demo instance. Gating CI on the shipped
   markdown while leaving the one path that can delete the warning unguarded would be incoherent.

**Accepted residual risk on the override path:** an override that *misplaces* the token (indented,
in a list, in a table cell) publishes the literal `{libli:demo_notice}` text. The panel warns on
absence, not on placement, because detecting placement means rendering the markdown on save; that
is deliberately out of scope, and the consequence is visible text rather than a missing warning.

"Revert to default" is the same operation as saving blank — one code path. Deliberately minimal:
plain textareas, no preview, no rich-text editor.

### The footer block

`base.html` gains `{% block footer %}{% endblock %}` **immediately after `</main>`, before the
`<script>` tags** — the only position that puts the footer in normal document flow ahead of the
deferred scripts and the support-dialog include. It renders nothing unless a template fills it, so
authenticated pages are unchanged *in output* even though the file changes.

- `templates/core/landing.html` — the two `<span>` placeholders become real `<a>` elements, and
  the `<span aria-hidden="true">EN / PL</span>` line is **deleted outright**. It duplicated the
  header language switcher (`templates/base.html:62`), already functional for anonymous visitors.
  The landing footer stays inside `{% block content %}` where it already lives.
- `templates/allauth/layouts/entrance.html` — fills `{% block footer %}`. The point of account
  creation, and the most important placement.
- `templates/core/public_page.html` — fills the same block, so the pages link to each other.

### Page template and CSS

One shared template extending `base.html`. The **markdown owns the `<h1>`**; the registry title
fills `{% block head_title %}` as `{{ title }} · {{ site.name|default:"libli" }}`, so a page never
renders two `<h1>` elements. Each `PAGES` entry also carries a `gettext_lazy` **meta description**
— a real sentence, not the title reused, since it is the only crawler-facing artefact that ships
and the pages exist to be found by evaluating schools.

New CSS is required and is **not** merely tokens: `.public-page` (a prose container composing from
the existing 46rem prose cap and body type scale), `.public-page__notice` (the demo callout,
composing from existing surface/border tokens), and the entrance footer's rules. `.public-page`
does not exist in `app.css` today — only `.landing-footer` (`app.css:300`) — so both
`core/static/core/css/app.css` and `core/static/core/css/auth.css` are touched. No new design
tokens.

### Fallback language

The **view** puts `resolved_lang` in the context and the template always emits
`<div lang="{{ resolved_lang }}">` rather than comparing anything. A template-level comparison
would be both awkward (Django cannot compare two context variables inside `{% if %}`) and wrong:
`LANGUAGE_CODE` in `base.html:4` can be regional (`pl-PL`) while `resolved_lang` is always bare, so
a naive comparison would mark *every* page as a fallback. Always emitting the resolved language is
correct in both the matching and the falling-back case.

### i18n

New translatable chrome — the `PAGES` titles **and meta descriptions**, the demo-notice message,
the two footer link labels, the settings tab and section labels, the neutral fallback phrases
(supervisory authority, empty embed list, zero-retention), and both panel warnings — needs
`makemessages`, Polish strings, and `compilemessages` before the PR. Given this repo's history of
fuzzy pre-fills producing wrong Polish and of binary `.mo` merge conflicts, this is an explicit
step. Page *bodies* are not gettext strings — they are the `.pl.md` siblings.

## Data flow

```
GET /privacy/
  -> core.views_public.privacy (no auth)
       lang = translation.get_language()          # SessionLocaleMiddleware already ran
       cfg  = get_site_config()                   # bundle, now carrying the six added keys
       html, resolved_lang = render_public_page("privacy", lang, cfg)
                |
                +-- code = normalize_lang(lang)
                +-- PublicPage row (privacy, code) with non-blank body?
                |     yes -> source = row.body_markdown ; resolved_lang = code
                |     no  -> rel = localized_doc_path(PAGES["privacy"].path, code)
                |            resolved_lang = code if rel != PAGES["privacy"].path else "en"
                |            source = (DOCS_ROOT / rel).read_text()  # OSError -> log, return ("", code)
                +-- markdown.markdown(source, extensions=["fenced_code", "tables"])
                +-- nh3.clean(html, tags=PUBLIC_PAGE_TAGS, ...)
                +-- block-token pass   (demo_notice, with its enclosing <p>)
                +-- inline-token pass  (text runs between > and <; escaped; function replacement)
       -> render "core/public_page.html" with html, resolved_lang, title, description
```

## Error handling

- **Missing repo template.** `render_public_page` — not the view — catches `OSError`, logs at
  `exception` level, and returns `("", code)`. One owner, one contract, so unit tests can assert
  it directly. Only `OSError` is caught; never a bare `except`. A deliberate divergence from
  `core/help.py`'s fail-loud stance: a 500 on the marketing surface is worse than a thin page.
- **No `Institution` row** — `_DEFAULTS` carries every key the tokens read.
- **Blank override row** — treated as "no override".
- **Missing Polish sibling** — English is served and `resolved_lang` reports `en`.
- **Unknown slug** — unreachable via URL; `KeyError` is a programming error.
- **Blank / degenerate token values** — every one has a defined fallback (see the token section),
  so no sentence can degrade into a fragment.

## Content

Both pages ship real prose in English and Polish, not placeholders.

### Privacy notice (`docs/public/privacy.md` + `privacy.pl.md`)

1. **Who is responsible** — `{libli:controller_name}`, `{libli:controller_address}`,
   `{libli:contact_email}`.
2. **`{libli:demo_notice}`** — its own top-level paragraph. Demo instances only.
3. **What is held, and why** — account and identity (username, optional email, display/first/last
   name, `external_id`); the learning record; groups; the user's own notes, tags and uploads;
   preferences; support reports. **Names `Attempt` (`courses/models.py:3101`) explicitly**: every
   submitted answer is retained with its timestamp, not merely the latest.
4. **What libli does not collect** — scoped to libli's own processing: no IP addresses in the
   application (`support/telemetry.py:1`), no analytics, no advertising, no profiling or automated
   decision-making, no data sold or shared for marketing, and **no cookies set by libli beyond the
   functional ones listed below**. The scoping matters: a flat claim would be false on any page
   carrying a third-party embed, and item 6 says so.
5. **Cookies and local storage** — a four-row table with **accurate lifetimes**, since a DPO
   checks these against the browser inspector first:

   | Cookie | Purpose | Lifetime |
   |---|---|---|
   | `sessionid` | Keeps your login and, before you log in, your language choice | **Two weeks** (Django default; persistent, not a session cookie) |
   | `csrftoken` | Anti-forgery check on forms | **About a year** (Django default) |
   | `messages` | Carries a one-off confirmation or error between pages | Short-lived |
   | `libli_theme` | Light/dark appearance | One year |

   Plus the localStorage keys, named exactly: `libli_unit_tree_collapsed`, `libli-editor-view`,
   and `libli_outline_open:<course-slug>`.
6. **Third parties** — embeds a teacher adds (`{libli:embed_domains}`), stating that the browser
   contacts them directly **only** on pages where a teacher placed one, **and that those providers
   may set their own cookies and storage**; SSO / OpenID Connect when configured; the mail
   provider; the results webhook when an admin enables it; **and the web server's access logs,
   which do include IP addresses even though the application never stores them.**
7. **Who can see what** — teachers see the records of their own students; platform admins see
   everything; students see nothing about each other; notes and tags are private to their author.
8. **How long it is kept** — **read** notifications are removed after
   `{libli:notification_retention_days}`, on a schedule **the operator's deployment installs**
   (a cron line, not something the application runs by itself); unread notifications are never
   removed on age. **Learning records have no automatic expiry** and persist while the account
   does. All three qualifications are load-bearing: without them the sentence is false on a
   deployment that sets `0`, on unread notifications, and on any deployment that skipped the cron.
9. **Your rights** — Art. 15–21 and the right to complain to `{libli:supervisory_authority}`,
   followed by the operational truth: no self-service export or delete today
   (`accounts/views_manage.py` offers deactivate/reactivate only), requests go to the contact
   address and are handled by hand, and **deactivating an account is not erasure**.
10. **Children**, **security**, and **changes and effective date**. Security is phrased as a
    property of the production deployment the operator is responsible for — HTTPS and secure
    cookies come from `config/settings/production.py`. Django password hashing and role-based
    access are unconditional. The effective date lives in the markdown itself.

### The consent-banner decision

No consent banner ships. The reasoning, recorded rather than asserted, because a DPO will test it:
ePrivacy and Polish *Prawo telekomunikacyjne* art. 173 exempt storage **strictly necessary** for a
service the user requested. `sessionid`, `csrftoken` and `messages` clear that bar. Note that
`csrftoken`'s ~one-year default lifetime does **not** remove it from the exemption: it carries no
identifier and exists solely for the anti-forgery check. The first-party debatable items are the
one-year `libli_theme` cookie and the localStorage UI keys; both are first-party, purely cosmetic,
carry no identifier, are never read by a third party and are never used to recognise a returning
visitor, which is the treatment this project adopts.

**The genuinely consent-shaped storage is the third-party embeds', not libli's own.** Those appear
only on authenticated pages a teacher authored; **the two public pages carry no embeds at all**,
so the surfaces a banner would guard set nothing beyond the exempt cookies. Embed storage on
authenticated course pages is recorded here as residual risk for the operator to weigh, not
resolved by this work. **This is a decision taken with the risk noted, not a legal opinion.**

### Getting started (`docs/public/getting-started.md` + `getting-started.pl.md`)

One sentence on what libli is, then a split by reader:

- **"Evaluating libli?"** — what the platform does (courses and lessons, roughly thirty element
  types including interactive and mathematical ones, quizzes with automatic marking, teacher
  analytics, English and Polish); **`{libli:demo_notice}` as its own top-level paragraph**, so the
  demo claim and the do-not-enter-real-data warning are gated on `demo_instance` here too and a
  school deploying libli never tells its own parents that the school's instance is a
  demonstration site; how to reach a human; and an explicit link to the privacy notice.
- **"Trying to log in?"** — accounts are created by your school rather than self-service;
  forgotten passwords go through the reset link; invitations expire after 14 days
  (`accounts.models.INVITE_TTL`); anything broken goes to a teacher or the contact address.

## Testing

Every assertion is paired with the mutant that must turn it red.

| Assertion | Mutant that must make it fail |
|---|---|
| Both pages return 200 to an **anonymous** client, in both languages | Add `login_required` to a view |
| Both pages render with **no `Institution` row at all** | Add the keys to `_build()` but not `_DEFAULTS` |
| `get_site_config()` carries all six added keys on **both** return paths | Add them to one path only |
| **`notification_retention_days = 0` survives into `get_site_config()`** | Use the `or _DEFAULTS` idiom for it |
| **`demo_instance = False` survives into `get_site_config()`** | Use the `or _DEFAULTS` idiom for it |
| A non-blank override row is served instead of the repo template | Reverse the resolution order |
| Deleting the override row falls back to the repo template | Make the fallback unconditional |
| A blank override row is treated as "no override" | Treat any existing row as winning |
| An `en`-only override does **not** leak into the `pl` page | Add a cross-language fallback |
| The panel warns when a page is overridden in some but not all languages | Drop the `partial` flag |
| **The panel warns when `demo_instance` and an override omits `{libli:demo_notice}`** | Drop the `missing_demo_notice` flag |
| A `pl-PL` request serves the `pl` override row | Drop `normalize_lang` from the DB lookup |
| A `pl-PL` entry in `enabled_languages` saves a row with `language="pl"` | Drop `normalize_lang` from the write path |
| `<script>` in an **override** does not reach the response | Drop `nh3.clean` |
| A tag outside `PUBLIC_PAGE_TAGS` in a **repo markdown fixture** is stripped | Sanitise only the override branch |
| An `ftp://` href does not survive | Drop `PUBLIC_PAGE_URL_SCHEMES` |
| A `javascript:` href does not survive (regression only — passes either way, kept knowingly) | *(none — documented as non-killing)* |
| A **table** in a page survives sanitisation | Swap in `courses.sanitize.sanitize_html` |
| An `h5` heading survives sanitisation | Drop `h5`/`h6` from the allow-list |
| A two-space line break survives as `<br>` | Drop `br` from the allow-list |
| `controller_name` containing markup is escaped | Drop the escaping at substitution |
| `controller_name = r"A\1B"` renders literally and does not raise | Use a string replacement in `re.sub` |
| A multi-line `controller_address` renders `<br>`-separated | Drop the `nl2br` step |
| A token inside an `href` is left literal, not substituted | Substitute over the whole document |
| **No `{libli:` token survives inside an attribute in any of the four shipped files** | Put a token in a shipped link target |
| An unknown `{libli:nope}` token renders literally | Substitute unknown tokens with `""` |
| `{libli:controller_name}` falls back to `cfg["name"]` when blank | Remove the fallback |
| `{libli:supervisory_authority}` falls back to the neutral phrase when blank | Hardcode "UODO" |
| **`{libli:embed_domains}` renders the neutral phrase when the list is empty** | Join an empty list |
| **`{libli:notification_retention_days}` renders the neutral phrase at `0`, not "0"** | Render the integer unconditionally |
| The `pl` sibling is served under `pl` | Ignore the language argument |
| A missing `pl` sibling falls back to English and the body is marked `lang="en"` | Return `code` unconditionally as `resolved_lang` |
| `demo_instance = True` renders the demo block on **both** pages | Hardcode the token to `""` |
| `demo_instance = False` renders no demo block on **both** pages, **and no empty `<p></p>`** | Substitute inline instead of block |
| The shipped markdown places `{libli:demo_notice}` where the block regex matches (both pages, both languages) | Indent the token into a list item |
| A missing template file renders a page shell, not a 500 | Remove the `OSError` guard |
| Each page renders exactly one `<h1>`, from the markdown; `<title>` carries the registry title | Render the registry title as an `<h1>` |
| **Each page emits a non-empty `<meta name="description">`** | Drop the meta tag |
| The notice's stated `sessionid` lifetime matches `settings.SESSION_COOKIE_AGE` | Change the setting without the text |
| No cookie outside the four documented names is set on the public or entrance pages | Add an undocumented cookie |
| Landing footer has both links **and** no literal `EN / PL` | Restore the span |
| The entrance layout carries both links | Remove its `footer` block |
| An authenticated page renders **no** footer | Put content in `base.html`'s `footer` block |
| Both settings views 403 for an authed user without `institution.change_institution` | Drop `permission_required` |
| A GET to either settings POST target redirects rather than rendering | Drop the GET guard |
| **With no stale rows present**, the panel renders exactly `len(PAGES) × len(normalised enabled_languages)` textareas | Iterate `settings.LANGUAGES`, or English only |
| The panel also lists a row whose language is no longer enabled | List only enabled languages |
| **Blanking a stale-language row's textarea deletes it** | Iterate only enabled languages in the view |
| Saving a blank textarea deletes the row rather than storing a blank | Store the blank |
| A POST key for `getting-started` writes the `getting-started` slug, not `getting` | Parse the key name by splitting on `-` |
| Posting `controller_name` through the settings form changes the privacy page's output | Omit the field from the form |

Unit tests cover `render_public_page`, `normalize_lang` and both token passes directly; view tests
cover the two routes, both languages, and the anonymous case; template tests cover all three
footers. No new e2e test is warranted — these pages have no interactive behaviour.

## Accepted decisions worth not re-litigating

- **"Help" points at `/getting-started/`.** `/help/` is the staff area. **Known consequence:** an
  authenticated staff user viewing a public page sees two "Help" links with different destinations
  — the nav one (`base.html:87` → `core:help_index`) and the footer one. This does *not* affect the
  landing page, which bounces authenticated users to `home`. Relabelling the footer link "Getting
  started" would remove the collision; the "Help" label is kept because it was chosen deliberately,
  and the narrow staff-only overlap does not outweigh that.
- **The model lives in `institution`, not `core`**, because `core` has no migrations package.
- **One sanitiser for both sources**, so the trust split cannot be got wrong later.
- **`img` is excluded** from the allow-list deliberately.
- **No cross-language override fallback** — language-appropriate text beats content-identical
  text, with the partial-override risk handled by a UI warning instead.
- **Deleting a row is the revert action** — one code path, not two.
- **Rows for an unregistered slug are inert** and cleaned up by hand in the Django admin.
- **The panel warns on a missing demo notice but not on a misplaced one** — detecting placement
  means rendering markdown on save, which is out of scope; a misplaced token shows visible text
  rather than silently dropping a warning.
- **A public page degrades to an empty body rather than a 500.**
- **The effective date lives in the content**, because only a human knows whether an edit was
  substantive.
- **Recorded exceptions to "no shipped sentence may assert a changeable fact":** the security
  paragraph is phrased as a property of the production deployment rather than tokenised; cookie
  **names** are hardcoded because they are properties of the code; and cookie **lifetimes** are
  hardcoded to Django's defaults, which are not configured anywhere today — a test asserts the
  stated `sessionid` lifetime still matches `settings.SESSION_COOKIE_AGE`, so setting that value
  later fails CI rather than silently falsifying the notice.
- **Per-request cost is accepted.** Every hit does a DB query, a file read, a markdown render and
  an `nh3.clean`. Adequate at demo scale; if it ever matters, cache on
  `(slug, lang, PublicPage.updated_at)`.
- **Crawler configuration is out of scope** — a meta description ships, but no `robots.txt` or
  sitemap work, and nothing verifies the deployment permits crawling.
- **Overrides keep no history.** A single mutable row holds the live privacy notice; an accidental
  save or revert destroys the previously published text. Accepted at this scale; mitigated by the
  panel warning before reverting, by the Django admin registration, and by telling admins to keep
  their own copy of any published notice.
