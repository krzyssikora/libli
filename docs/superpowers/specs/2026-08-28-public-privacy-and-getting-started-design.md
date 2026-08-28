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
   (the two recorded exceptions are listed in §Accepted decisions).

## Background: what exists today

- `config/urls.py:22` mounts `core.urls` at the **root**, so `/help/` already belongs to the
  staff help area (`core/urls.py:17`). That view is `@login_required` and its topics are gated on
  role marker perms (`core/views_help.py:14`). **The public page cannot live at `/help/`.**
- Every content path in the application is `@login_required`. The landing page is the only
  anonymous surface, and `landing` (`core/views.py:63`) **bounces authenticated users to `home`**.
  These two pages are the **first public content surface** in the codebase.
- **`localized_doc_path` and `DOCS_ROOT` are reused from `core/help.py`; nothing else is.**
  `localized_doc_path` returns the `<name>.<code>.md` sibling when it exists on disk, else the
  English base, coalescing a falsy language and normalising a regional code (`pl-PL` → `pl`).
  `render_markdown_doc` is deliberately **not** reused (see §Sanitisation), so the
  `src="static:REL"` and `{el:slug}` sentinels **do not work in `docs/public/`** — an author
  copying a pattern from `docs/help/` would get literal sentinel text on the page.
- `.dockerignore` excludes `docs/superpowers`, `docs/mockups` and `docs/planning` but **keeps**
  `docs/help`. A new `docs/public/` therefore ships in the production image.
- **`core` has no `models.py` and no `migrations/` package.** It is in `INSTALLED_APPS` but has
  never held a model. `institution` already has both (see §Where the model lives).
- **`get_site_config()` has two return paths.** `_build()` (`core/services.py:70`) returns
  `dict(_DEFAULTS)` when no `Institution` row exists, and a separate literal dict otherwise. Any
  new key must be added to **both**, or a fresh install `KeyError`s.
- The settings area is **one page with query-param tabs**, not separate pages:
  `institution/views_manage.py` holds `TABS` (a 7-tuple), `_active_tab` (reads `?tab=`),
  `_index_url(tab)`, `_settings_context(request, inst, active_tab, *, branding=None, …, support=None)`
  — a **fixed keyword signature** — and `_action(request, form_cls, ctx_key, tab, success_msg)`,
  which binds `form_cls(request.POST, request.FILES, instance=inst)`, i.e. a **ModelForm on
  `Institution`**. The `settings` view renders every panel on GET.
- `templates/base.html` defines `header`, `main_class`, `content`, `extra_body`, `extra_js`.
  **There is no footer block**, and nothing after `</main>` but scripts. The landing footer lives
  inside `{% block content %}`, so it is not a precedent that transfers to the entrance layout,
  which does not own `content`.
- `set_ui_language` (`core/views.py:169`) carries **only `@require_POST`** — not `login_required`
  — and `LanguageSeederMiddleware` (`core/middleware.py:16`) writes the session language key on a
  plain anonymous request whose resolved language is not enabled. **An anonymous visitor can
  acquire a `sessionid` cookie without ever logging in.**
- **`MESSAGE_STORAGE` is not configured**, so Django's default `FallbackStorage` writes a
  `messages` cookie first — and allauth uses messages heavily on the login/signup flow, exactly
  the anonymous surface this notice is now linked from.

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

**Out of scope:** authenticated pages render no footer (the new block is empty for them). The
staff help area is untouched. No cookie-consent banner (see §The consent-banner decision). No
crawler configuration — no `robots.txt`, no sitemap; only a meta description on the shared
template is in scope.

## Architecture

### URLs

Two top-level routes in `core/urls.py`, **without** `login_required`:

| Path | Name | Page |
|---|---|---|
| `/privacy/` | `core:privacy` | Privacy notice |
| `/getting-started/` | `core:getting_started` | Getting started |

Views live in a new `core/views_public.py`.

**Accepted wart:** the footer label reads "Help" but points at `/getting-started/`, because
`/help/` is the staff area. Chosen deliberately over renumbering existing staff help links.

### Where the model lives

`PublicPage` goes in **`institution`**, not `core`. `core` has no `models.py` and no
`migrations/` package, so putting it there would mean creating the app's first model module *and*
its first migrations package — a needless deploy-ordering wrinkle on a live instance.
`institution` already owns both, and owns the single-row deployment configuration these overrides
are part of. One migration adds the model **and** the five new `Institution` fields together.

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

Registered in the Django admin (`institution/admin.py`), read-mostly: the model holds live legal
text and keeps no history, so a superuser must be able to inspect rows without going through the
settings panel. `__str__` and `ordering` exist so that listing is legible.

`slug` carries **no `choices`**: Django serialises `choices` into migrations, so adding a third
page — or editing a title — would emit a spurious `AlterField`, and the `PAGES` titles are
`gettext_lazy` objects with no business in a migration file. The registry gates writes, and
`render_public_page` raises `KeyError` on an unregistered slug (a programming error, not a
request outcome).

Chosen over per-language `TextField`s on `Institution` because `Institution.enabled_languages` is
a runtime-editable JSON list — a per-language row needs no migration when a language is added.

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
five above plus `notification_retention_days`, which the notice cites and which is *not* in the
bundle today — and `_DEFAULTS` gains the same six, so the no-`Institution`-row path stays
key-identical. Without that, `cfg["controller_name"]` would `KeyError` and 500 the public pages on
a fresh install, which is precisely the failure §Error handling exists to prevent. The existing
`Institution` `post_save` signal already invalidates the cache; no new invalidation path.

### New module: `core/public_pages.py`

Owns `PAGES` (slug → markdown base path, `gettext_lazy` title, URL name), the sanitiser
allow-lists, `normalize_lang`, `render_public_page`, and the token passes. It does **not** extend
`core/help.py`, whose docstring states its input is trusted repo markdown to which "the renderer
applies no sanitization" — feeding database content through it would silently break a documented
contract.

### Sanitisation: a document allow-list, not the rich-text one

Rendered markdown is sanitised with `nh3`, following the pattern of `courses/sanitize.py` but
**not reusing `sanitize_html`**. That function's `ALLOWED_TAGS` (`courses/sanitize.py:15`) is
tuned for rich-text *body* content and contains no `h1`, `table`, `thead`, `tbody`, `tr`, `th`,
`td`, or `hr`. Passing a document through it would silently delete the cookie table and flatten
the headings.

```
PUBLIC_PAGE_TAGS = {
    h1 h2 h3 h4 h5 h6 p br ul ol li strong b em i code pre blockquote a hr
    table thead tbody tr th td
}
PUBLIC_PAGE_ATTRIBUTES  = {"a": {"href", "title", "rel"}}
PUBLIC_PAGE_URL_SCHEMES = {"http", "https", "mailto"}
```

`br` is included because a markdown line ending in two spaces emits `<br />` (verified), which
would otherwise vanish silently. `h5`/`h6` are included for the same reason — the notice has ten
numbered sections with sub-points, and silently merging a deep heading into surrounding prose is
the identical failure mode that disqualifies `sanitize_html`. **`img` is excluded on purpose**:
these pages are prose, and an image tag on an anonymous surface whose content an admin can edit is
avoidable attack surface. That omission is a decision, not an oversight.

**On the scheme list.** `nh3` **already blocks `javascript:` and `data:` by default** (verified:
both are stripped with and without `url_schemes`). `PUBLIC_PAGE_URL_SCHEMES` therefore does *not*
add protection against those two; what it actually excludes is `ftp:`, `tel:`, `magnet:` and
friends. The inherited comment at `courses/sanitize.py:41` claiming otherwise is wrong, and the
test table reflects measured behaviour rather than that comment.

**Both content sources go through the same sanitiser** — no trust split, so no branch to get
wrong later.

### Language normalisation

One helper, used on **every** path that touches a language code — the DB lookup, the file lookup,
the override **write** path, and the settings panel's language list:

```
def normalize_lang(lang):  # (lang or "en").split("-")[0]
```

This is load-bearing in both directions. On read: without it, a request where
`translation.get_language()` returns `pl-PL` — or `None`, which `core/help.py` documents as
possible — would silently miss a `pl` override row. On write: `enabled_languages` is a
runtime-editable JSON list, so an admin can put `pl-PL` in it; the panel would then create a row
with `language="pl-PL"` that the normalised lookup can never match — a saved override that
silently never appears. The panel iterates `normalize_lang(l) for l in enabled_languages`,
de-duplicated, and the save path normalises before writing. **`PublicPage.language` always stores
a bare code.**

### Content resolution

`render_public_page(slug, lang, cfg)` returns `(html, resolved_lang)`. `cfg` is the site-config
bundle, supplied by the view — passing it in rather than re-reading it keeps the function
injectable from unit tests and gives the tokens a single source of truth.

1. `code = normalize_lang(lang)`.
2. **Admin override** — a `PublicPage` row for `(slug, code)` whose `body_markdown` is non-blank
   wins. A blank row is treated as *no override*, so "no override" has exactly one meaning.
3. **Repo template** — otherwise `localized_doc_path(PAGES[slug].path, code)` under `DOCS_ROOT`.
   The path comes from the registry, never from an f-string, so the registry is the single source
   of truth and an unregistered slug raises `KeyError` as claimed.
4. Then: `markdown.markdown(..., extensions=["fenced_code", "tables"])` → `nh3.clean(...)` →
   block-token pass → inline-token pass.

**The chain does not fall back across languages.** A missing `pl` override does *not* borrow the
`en` override; it falls to the `pl` repo template. Serving English text to a Polish reader is the
worse failure, so language-appropriate content wins. The real risk this creates — an admin
overriding one language only, leaving the live notice saying substantively different things in
two languages — is handled in the UI rather than the resolver: **the settings panel shows override
status per language and warns when a page is overridden in some but not all enabled languages.**

`resolved_lang` is the language actually served, which may be `en` when a Polish sibling is absent.

A shipped template always exists, so a page always renders and the footer links are always live.
**Deleting the override row is the "revert to default" action** — no separate revert flag.

### Token substitution

Identity is injected by `{libli:NAME}` token passes mirroring the existing `{el:slug}` sentinel
idiom, deliberately **not** by the Django template engine (which on the override path would be a
template-injection vector). Substitution runs **after** sanitisation.

**The precise invariant:** a substituted value contributes only text, plus — for
`controller_address` alone — `<br>` elements generated by the escape-then-`nl2br` step. **No value
can ever contribute a tag it contains itself.** (Stated this way rather than "substitution can
never introduce a tag", which the `nl2br` rule contradicts and which would mislead anyone adding a
similar rule later.)

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

1. **Block pass** — matches the token *with its enclosing paragraph*
   (`<p>\s*\{libli:demo_notice\}\s*</p>`) and replaces the **whole match**: the notice block when
   `demo_instance` is true, the empty string when false. Only `demo_notice` is a block token.
   **Authoring constraint: `{libli:demo_notice}` MUST be a paragraph of its own at top level.**
   Inside a list item or mid-sentence, markdown emits no wrapping `<p>` and the regex will not
   match, leaving the literal token text on a live page — which would silently swallow the
   do-not-enter-real-pupil-data warning. The shipped markdown is tested for this directly (see
   the test table), so a misplacement fails CI rather than reaching a visitor.
2. **Inline pass** — the value tokens, substituted **in text content only**.

**Tokens are never substituted inside attribute values.** Verified:
`markdown.markdown("[mail](mailto:{libli:contact_email})")` yields
`<a href="mailto:{libli:contact_email}">`, and nh3 preserves it — so substituting there would
write an admin-controlled value into a URL *after* the URL was vetted, and a whole-href token
would let a value choose the scheme. The inline pass operates only on text between `>` and `<`; a
token inside an attribute is **left literal**, exactly like an unknown token. The pass does
**not** exempt `<pre>`/`<code>`, so authors must not show token syntax verbatim in a code fence.

| Token | Kind | Source |
|---|---|---|
| `{libli:controller_name}` | inline | `cfg["controller_name"]` or `cfg["name"]` when blank |
| `{libli:controller_address}` | inline | `cfg["controller_address"]`, escaped then `\n` → `<br>` |
| `{libli:contact_email}` | inline | `cfg["contact_email"]` |
| `{libli:site_name}` | inline | `cfg["name"]` |
| `{libli:supervisory_authority}` | inline | `cfg["supervisory_authority"]`, or a neutral fallback |
| `{libli:embed_domains}` | inline | `settings.ALLOWED_EMBED_DOMAINS`, comma-joined |
| `{libli:notification_retention_days}` | inline | `cfg["notification_retention_days"]` |
| `{libli:demo_notice}` | **block** | The notice when `cfg["demo_instance"]`, else empty |

Every token reads from `cfg` (the bundle) except `embed_domains`, which is a Django setting rather
than institution state. **An unknown token is left as literal text**, matching the `{el:slug}`
contract — a typo is visible and catchable, never a silent blank.

`controller_address` is escaped and *then* has newlines converted to `<br>`. Escaping first means
`<br>` is the only markup that can result; a postal address is inherently multi-line and
`html.escape` alone would collapse it onto one line.

`{libli:demo_notice}` expands to a pre-built `<p class="public-page__notice">…</p>` built from a
translated `gettext` message — never from user input — so it is safe by construction.

`supervisory_authority`, `embed_domains` and `notification_retention_days` are tokens rather than
prose because all three are per-deployment facts: the competent authority follows the controller's
establishment, `ALLOWED_EMBED_DOMAINS` is an `env.list`, and retention is admin-editable.
Hardcoding any of them would put a false statement in a compliance document the moment a
deployment changed it. When `supervisory_authority` is blank the token renders a neutral phrase
("your national data protection authority") rather than naming a regulator that may be wrong.

### Admin editing UI

A new eighth tab, `public-pages`. The delta from the existing pattern, stated precisely because
this section does **not** simply follow it:

- `TABS` gains an eighth entry; `templates/institution/manage/_tabs.html` gains its link and
  `templates/institution/manage/settings.html` gains its `data-tab` panel.
- `_settings_context` gains **two** new keyword arguments: `public_pages` (the `Institution`-fields
  form) and `page_overrides`. `page_overrides` is **always built on the display path**, not only
  on a failed POST, because the `settings` view renders every panel on GET.
- The panel contains **two independent sibling `<form>` elements** (HTML forbids nesting), each
  with its own action, `{% csrf_token %}` and submit control:
  - `institution:settings_public_pages` — the five `Institution` fields, via a new
    `PublicPagesForm(ModelForm on Institution)`. This one **does** reuse `_action(...)`.
  - `institution:settings_page_overrides` — the override rows. This **cannot** reuse `_action`,
    which binds a single ModelForm to `Institution`; the overrides are a variable-length set keyed
    by `(slug, language)`.
- The override view **iterates the known `(slug, language)` pairs** and reads
  `request.POST.get(f"override-{slug}-{language}", "")`, ignoring unrecognised keys. It **never
  parses submitted key names** — `getting-started` contains hyphens, so `override-getting-started-pl`
  cannot be split unambiguously. Per pair: write the row when the value is non-blank, **delete**
  any existing row when it is blank.
- Both views are `@login_required` + `@permission_required("institution.change_institution",
  raise_exception=True)` — the permission every sibling settings view uses — and both keep the
  POST-only contract with a GET redirect to `_index_url("public-pages")`.

The panel lists **each page × each normalised enabled language**, each with a textarea holding the
current override (empty when none), **plus any existing row whose language is no longer enabled**,
marked as such. Without that last part, removing a language from `enabled_languages` would hide
its override rows from the panel while they continued to be served to anyone whose session still
resolved to that code — text still published with no UI path to inspect or delete it.

The panel also **warns when a page is overridden in some but not all enabled languages** (the
partial-override risk from §Content resolution).

"Revert to default" is the same operation as saving blank — one code path, so the two cannot
diverge. Deliberately minimal: plain textareas, no preview, no rich-text editor.

### The footer block

`base.html` gains `{% block footer %}{% endblock %}` **after `</main>`**. It renders nothing
unless a template fills it, so authenticated pages are unchanged *in output* even though the file
changes. This is the mechanism the entrance layout needs — it overrides `header`/`body_class`/
`main_class`/`extra_css` but not `content`, and `extra_body` sits after the `<script>` tags.

- `templates/core/landing.html` — the two `<span>` placeholders become real `<a>` elements, and
  the `<span aria-hidden="true">EN / PL</span>` line is **deleted outright**. It duplicated the
  header language switcher (`templates/base.html:62`), which is outside the `is_authenticated`
  guard and already functional for anonymous visitors. The landing footer stays inside
  `{% block content %}` where it already lives.
- `templates/allauth/layouts/entrance.html` — fills `{% block footer %}` with a minimal footer
  carrying the two links. The point of account creation, and the most important placement.
- `templates/core/public_page.html` — fills the same block, so the pages link to each other.

### Page template and CSS

One shared template extending `base.html`. The **markdown owns the `<h1>`**; the registry title is
used for `<title>` and the meta description only, so a page never renders two `<h1>` elements.

New CSS is required and is **not** merely tokens: `.public-page` (a prose container composing from
the existing 46rem prose cap and body type scale), `.public-page__notice` (the demo callout,
composing from existing surface/border tokens), and the entrance footer's rules. `.public-page`
does not exist in `app.css` today — only `.landing-footer` (`app.css:300`) — so both
`core/static/core/css/app.css` and `core/static/core/css/auth.css` are touched. No new design
tokens.

### Fallback language

The **view** computes the wrapper language and puts `resolved_lang` in the context; the template
always emits `<div lang="{{ resolved_lang }}">` rather than comparing anything. A template-level
comparison would be both awkward (Django cannot compare two context variables inside `{% if %}`)
and wrong: `LANGUAGE_CODE` in `base.html:4` can be regional (`pl-PL`) while `resolved_lang` is
always bare, so a naive comparison would mark *every* page as a fallback. Always emitting the
resolved language is correct in both the matching and the falling-back case, and needs no
comparison at all.

### i18n

New translatable chrome — the `PAGES` titles, the demo-notice message, the two footer link
labels, the settings tab and section labels, and the partial-override warning — needs
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
                |     yes -> source = row.body_markdown
                |     no  -> rel = localized_doc_path(PAGES["privacy"].path, code)
                |            source = (DOCS_ROOT / rel).read_text()  # OSError -> log, return ("", code)
                +-- markdown.markdown(source, extensions=["fenced_code", "tables"])
                +-- nh3.clean(html, tags=PUBLIC_PAGE_TAGS, ...)
                +-- block-token pass   (demo_notice, with its enclosing <p>)
                +-- inline-token pass  (text nodes only; escaped; function replacement)
       -> render "core/public_page.html" with html, resolved_lang, title
```

## Error handling

- **Missing repo template.** `render_public_page` — not the view — catches `OSError` from the
  read, logs at `exception` level, and returns `("", code)`. The view is unaware and renders the
  page shell with an empty body. One owner, one contract, so unit tests can assert it directly.
  Only `OSError` is caught; never a bare `except`. A deliberate divergence from `core/help.py`'s
  fail-loud stance: a 500 on the marketing surface is worse than a thin page.
- **No `Institution` row** — `_DEFAULTS` carries every key the tokens read, so the pages render.
- **Blank override row** — treated as "no override".
- **Missing Polish sibling** — `localized_doc_path` falls back to English; `resolved_lang` reports
  `en` and the wrapper marks the body accordingly.
- **Unknown slug** — unreachable via URL; `KeyError` is a programming error, not a request outcome.
- **Blank `Institution` fields** — `controller_name` falls back to `name`,
  `supervisory_authority` to a neutral phrase, the rest to empty. Shipped content is written so an
  empty contact detail still reads as a sentence.

## Content

Both pages ship real prose in English and Polish, not placeholders.

### Privacy notice (`docs/public/privacy.md` + `privacy.pl.md`)

1. **Who is responsible** — `{libli:controller_name}`, `{libli:controller_address}`,
   `{libli:contact_email}`.
2. **`{libli:demo_notice}`** — its own top-level paragraph. Demo instances only: this is a
   demonstration system, data entered here is visible to the operator, **do not enter real pupil
   data**.
3. **What is held, and why** — account and identity (username, optional email, display/first/last
   name, `external_id`); the learning record; groups; the user's own notes, tags and uploads;
   preferences; support reports. **Names `Attempt` (`courses/models.py:3101`) explicitly**: every
   submitted answer is retained with its timestamp, not merely the latest — the fact a DPO would
   otherwise discover later and reasonably feel misled about.
4. **What libli does not collect** — scoped to libli's own processing: no IP addresses in the
   application (`support/telemetry.py:1`), no analytics, no advertising, no profiling or automated
   decision-making, no data sold or shared for marketing, and **no cookies set by libli beyond the
   functional ones listed below**. The scoping matters: a flat "no cookies beyond the functional
   ones" would be false on any page carrying a third-party embed, and item 6 says so.
5. **Cookies and local storage** — a four-row table: `sessionid` (**session — keeps your login
   and, before you log in, your language choice**), `csrftoken` (security), `messages` (carries a
   one-off confirmation or error between pages; short-lived, present because `MESSAGE_STORAGE` is
   unset and allauth uses messages on the login flow), and `libli_theme` (appearance, `Max-Age`
   31536000 ≈ 1 year, `core/static/core/js/ui.js:4`). Plus the localStorage keys, named exactly:
   `libli_unit_tree_collapsed`, `libli-editor-view`, and `libli_outline_open:<course-slug>`.
6. **Third parties** — embeds a teacher adds (`{libli:embed_domains}`), stating that the browser
   contacts them directly **only** on pages where a teacher placed one, **and that those providers
   may set their own cookies and storage**; SSO / OpenID Connect when configured; the mail
   provider; the results webhook (`integrations/models.py:7`) when an admin enables it; **and the
   web server's access logs, which do include IP addresses even though the application never
   stores them.** Stated, not fudged into a flat "we don't log IPs".
7. **Who can see what** — teachers see the records of their own students; platform admins see
   everything; students see nothing about each other; notes and tags are private to their author.
8. **How long it is kept** — notifications purged after
   `{libli:notification_retention_days}` days; **learning records have no automatic expiry today**
   and persist while the account does. Stated plainly.
9. **Your rights** — Art. 15–21 and the right to complain to `{libli:supervisory_authority}`,
   followed by the operational truth: no self-service export or delete today
   (`accounts/views_manage.py` offers deactivate/reactivate only), requests go to the contact
   address and are handled by hand, and **deactivating an account is not erasure**.
10. **Children**, **security**, and **changes and effective date**. Security is phrased as a
    property of the production deployment the operator is responsible for — HTTPS and secure
    cookies come from `config/settings/production.py`, so a flat claim would be false on a
    deployment running other settings. Django password hashing and role-based access are
    unconditional. No overclaiming. The effective date lives in the markdown itself, since only a
    human knows whether an edit was substantive.

### The consent-banner decision

No consent banner ships. The reasoning, recorded rather than asserted, because a DPO will test it:
ePrivacy and Polish *Prawo telekomunikacyjne* art. 173 exempt storage **strictly necessary** for a
service the user requested. `sessionid`, `csrftoken` and `messages` clear that bar plainly. The
first-party debatable items are the one-year `libli_theme` cookie and the localStorage UI keys;
both are first-party, purely cosmetic, carry no identifier, are never read by a third party and are
never used to recognise a returning visitor, which is the treatment this project adopts.

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
  demonstration site; how to reach a human; and an explicit link to the privacy notice, because
  that is the first thing a school's DPO asks for.
- **"Trying to log in?"** — accounts are created by your school rather than self-service;
  forgotten passwords go through the reset link on the login page; invitations expire after 14
  days (`accounts.models.INVITE_TTL`) so ask for a fresh one; anything broken goes to a teacher or
  the contact address.

## Testing

Every assertion is paired with the mutant that must turn it red.

| Assertion | Mutant that must make it fail |
|---|---|
| Both pages return 200 to an **anonymous** client, in both languages | Add `login_required` to a view |
| Both pages render with **no `Institution` row at all** | Add the keys to `_build()` but not `_DEFAULTS` |
| `get_site_config()` carries all six added keys on **both** return paths | Add them to one path only |
| A non-blank override row is served instead of the repo template | Reverse the resolution order |
| Deleting the override row falls back to the repo template | Make the fallback unconditional |
| A blank override row is treated as "no override" | Treat any existing row as winning |
| An `en`-only override does **not** leak into the `pl` page | Add a cross-language fallback |
| The panel warns when a page is overridden in some but not all languages | Drop the warning |
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
| An unknown `{libli:nope}` token renders literally | Substitute unknown tokens with `""` |
| `{libli:controller_name}` falls back to `cfg["name"]` when blank | Remove the fallback |
| `{libli:supervisory_authority}` falls back to the neutral phrase when blank | Hardcode "UODO" |
| The `pl` sibling is served under `pl` | Ignore the language argument |
| A missing `pl` sibling falls back to English and the body is marked `lang="en"` | Drop `resolved_lang` |
| `demo_instance = True` renders the demo block on **both** pages | Hardcode the token to `""` |
| `demo_instance = False` renders no demo block on **both** pages, **and no empty `<p></p>`** | Substitute inline instead of block |
| **The shipped markdown places `{libli:demo_notice}` where the block regex matches** (both pages, both languages) | Indent the token into a list item |
| `{libli:embed_domains}` reflects a patched `ALLOWED_EMBED_DOMAINS` | Hardcode the host list |
| `{libli:notification_retention_days}` reflects a changed `Institution` value | Hardcode `90` |
| A missing template file renders a page shell, not a 500 | Remove the `OSError` guard |
| Each page renders exactly one `<h1>`, from the markdown; `<title>` carries the registry title | Render the registry title as an `<h1>` |
| No cookie outside the four documented names is set on the public or entrance pages | Add an undocumented cookie |
| Landing footer has both links **and** no literal `EN / PL` | Restore the span |
| The entrance layout carries both links | Remove its `footer` block |
| An authenticated page renders **no** footer | Put content in `base.html`'s `footer` block |
| Both settings views 403 for an authed user without `institution.change_institution` | Drop `permission_required` |
| A GET to either settings POST target redirects rather than rendering | Drop the GET guard |
| The panel renders `len(PAGES) × len(normalised enabled_languages)` textareas | Iterate `settings.LANGUAGES`, or English only |
| The panel also lists a row whose language is no longer enabled | List only enabled languages |
| Saving a blank textarea deletes the row rather than storing a blank | Store the blank |
| A POST key for `getting-started` writes the `getting-started` slug, not `getting` | Parse the key name by splitting on `-` |
| Posting `controller_name` through the settings form changes the privacy page's output | Omit the field from the form |

Unit tests cover `render_public_page`, `normalize_lang` and both token passes directly; view tests
cover the two routes, both languages, and the anonymous case; template tests cover all three
footers. No new e2e test is warranted — these pages have no interactive behaviour.

## Accepted decisions worth not re-litigating

- **"Help" points at `/getting-started/`.** `/help/` is the staff area; renumbering it is not
  worth it. **Known consequence:** an authenticated staff user viewing a public page sees two
  "Help" links with different destinations — the nav one (`base.html:87` → `core:help_index`) and
  the footer one. This does *not* affect the landing page, which bounces authenticated users to
  `home`. Relabelling the footer link "Getting started" would remove the collision; the "Help"
  label is kept because it was chosen deliberately, and the narrow staff-only overlap does not
  outweigh that. Worth revisiting if it ever confuses anyone.
- **The model lives in `institution`, not `core`**, because `core` has no migrations package.
- **One sanitiser for both sources**, so the trust split cannot be got wrong later.
- **`img` is excluded** from the allow-list deliberately.
- **No cross-language override fallback** — language-appropriate text beats content-identical
  text, with the partial-override risk handled by a UI warning instead.
- **Deleting a row is the revert action** — one code path, not two.
- **A public page degrades to an empty body rather than a 500** — the opposite of `core/help.py`'s
  fail-loud stance, and deliberately so.
- **The effective date lives in the content**, because only a human knows whether an edit was
  substantive.
- **Two recorded exceptions to "no shipped sentence may assert a changeable fact":** the security
  paragraph is phrased as a property of the production deployment rather than tokenised, and the
  cookie names are hardcoded because they are properties of the code, not of a deployment.
- **Per-request cost is accepted.** Every hit does a DB query, a file read, a markdown render and
  an `nh3.clean`. Adequate at demo scale; if it ever matters, cache on
  `(slug, lang, PublicPage.updated_at)`.
- **Crawler configuration is out of scope.** The pages are *intended* to be found by evaluating
  schools, and a meta description ships, but no `robots.txt` or sitemap work is in this PR and
  nothing here verifies the deployment permits crawling.
- **Overrides keep no history.** A single mutable row holds the live privacy notice; an accidental
  save or revert destroys the previously published text, and the effective date inside that text
  goes with it. Accepted at this scale; mitigated by the panel warning before reverting, by the
  Django admin registration above, and by telling admins to keep their own copy of any published
  notice.
