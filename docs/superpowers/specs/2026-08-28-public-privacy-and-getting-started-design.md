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
  `render_markdown_doc` is deliberately **not** reused (see §Sanitisation), so the
  `src="static:REL"` and `{el:slug}` sentinels **do not work in `docs/public/`**. Note that
  `render_markdown_doc` reads with `read_text(encoding="utf-8")` (`core/help.py:135`) — a
  deliberate choice this work must copy (see §Content resolution).
- `.dockerignore` keeps `docs/help`, so a new `docs/public/` ships in the production image.
- **`core` has no `models.py` and no `migrations/` package.** `institution` has both.
- **`get_site_config()` has two return paths.** `_build()` (`core/services.py:70`) returns
  `dict(_DEFAULTS)` when no `Institution` row exists, and a literal dict otherwise. Any new key
  must be added to **both**. Every line of that literal dict uses the
  `inst.<field> or _DEFAULTS["<field>"]` idiom **except** `"onboarded": inst.onboarded` — the one
  boolean, deliberately read bare.
- The settings area is **one page with query-param tabs**: `TABS` (a 7-tuple), `_active_tab`,
  `_index_url(tab)`, `_settings_context(request, inst, active_tab, *, branding=None, …,
  support=None)` — a **fixed keyword signature** — and `_action(request, form_cls, ctx_key, tab,
  success_msg)`, which binds a **ModelForm on `Institution`** and emits `messages.success`
  (`institution/views_manage.py:134`). The `settings` view renders every panel on GET.
- `templates/base.html` defines `head_title`, `header`, `main_class`, `content`, `extra_css`,
  `extra_head`, `extra_body`, `extra_js`. **There is no footer block**; `</main>` is followed
  immediately by the `ui.js` and `scroll_affordance.js` script tags, then `extra_body`/`extra_js`
  and the conditional support dialog. The landing footer lives inside `{% block content %}`, so it
  is not a precedent that transfers to the entrance layout, which does not own `content`.
- **`auth.css:3-11` gives `.auth-main` `min-height: calc(100vh - 2 * var(--space-6))`** plus
  generous padding — load-bearing for the entrance footer (see §The footer block).
- `set_ui_language` (`core/views.py:169`) carries **only `@require_POST`**, and
  `LanguageSeederMiddleware` writes the session language key on a plain anonymous request whose
  resolved language is not enabled. **An anonymous visitor can acquire a `sessionid` cookie
  without ever logging in.**
- **No cookie lifetimes are configured.** Neither `SESSION_COOKIE_AGE`,
  `SESSION_EXPIRE_AT_BROWSER_CLOSE` nor `CSRF_COOKIE_AGE` appears under `config/settings/`, so
  Django's defaults apply: `sessionid` is a **two-week persistent** cookie (1 209 600 s), *not* a
  session cookie, and `csrftoken` is ~**one year** (31 449 600 s). `libli_theme`'s one year is
  hardcoded twice in code — `core/views.py:147` (`max_age=31_536_000`) and
  `core/static/core/js/ui.js` — never in settings.
- **`MESSAGE_STORAGE` is not configured**, so `FallbackStorage` writes a `messages` cookie first.
- **`notification_retention_days = 0` means "never purge".** `notifications/retention.py:69` gates
  the age purge on `if days > 0`, and the query filters `read_at__isnull=False` — so the window
  applies to **read** notifications only. The purge is an operator-installed cron line
  (`docs/deployment.md:407`), not something the image runs.
- **The codebase writes exactly five localStorage keys**, under **three** different prefix styles:
  `libli-editor-view` (**hyphen**, `courses/static/courses/js/editor.js:763`),
  `libli:tabopen:<element-pk>:<slot-id>` (`editor.js:48`, built by string **concatenation**),
  `libli_outline_open:<course-slug>`, `libli_review_roster_collapsed`, and
  `libli_unit_tree_collapsed`. `libli_theme` is a **cookie**, covered by the cookie table, not
  localStorage.
  **`libli:reveal` and `libli:tagfilter` are `CustomEvent` type names, and
  `libli:htmlel:{height,req,theme}` are `postMessage` message types — none of them store
  anything.** Recorded explicitly so a later reader does not "restore" them to the storage list.
  The three prefix styles are why §Content item 5 documents `libli_`, `libli:` **and** `libli-`:
  a two-prefix claim is false at HEAD.
- **No first-party storage call uses a template literal.** The five `setItem` call sites pass one
  string literal (`editor.js:763`), a bare `KEY` identifier (`outline_tree.js`, `review_roster.js`,
  `unit_nav.js`), or a `slotStoreKey(...)` function call whose body concatenates a literal prefix
  (`editor.js:48`). Any scanner must handle those shapes, not interpolation.
- **`ALLOWED_IMAGE_FETCH_DOMAINS`** (`config/settings/base.py:235`) authorises **server-side**
  egress when a teacher adds an image by URL — a different mechanism from browser-side embeds.

## Scope

**In scope:** two public pages, their content in English and Polish, the rendering mechanism, the
admin override model and its editing UI, five new `Institution` fields *and their editing UI*, a
new `footer` block in `base.html`, footer links on the landing and entrance layouts, the CSS for
the new surfaces (including the entrance layout's height fix), the i18n catalogue work, and
deletion of the `EN / PL` span.

**Files touched:** `institution/models.py`, `institution/migrations/`, `institution/forms.py`,
`institution/views_manage.py`, `institution/urls.py`, `institution/admin.py`,
`core/public_pages.py` (new), `core/views_public.py` (new), `core/urls.py`, `core/services.py`,
`core/static/core/css/app.css`, `core/static/core/css/auth.css`, `templates/base.html`,
`templates/core/landing.html`, `templates/core/public_page.html` (new),
`templates/allauth/layouts/entrance.html`, `templates/institution/manage/settings.html`,
`templates/institution/manage/_tabs.html`,
`templates/institution/manage/_public_pages_tab.html` (new), `docs/public/*.md`, `locale/pl/LC_MESSAGES/`.

**Out of scope:** authenticated pages render no footer. The staff help area is untouched. No
cookie-consent banner. No crawler configuration — only a meta description ships.

## Architecture

### URLs

Two top-level routes in `core/urls.py`, **without** `login_required`:

| Path | Name | Page |
|---|---|---|
| `/privacy/` | `core:privacy` | Privacy notice |
| `/getting-started/` | `core:getting_started` | Getting started |

Views live in a new `core/views_public.py`.

### Where the model lives

`PublicPage` goes in **`institution`**, not `core`, which has no `models.py` and no `migrations/`
package. One migration adds the model **and** the five new `Institution` fields together.

```
class PublicPage:
    slug           CharField(max_length=32)          # no choices - see below
    language       CharField(max_length=5)           # always a BARE code ("en", "pl")
    body_markdown  TextField(blank=True)
    updated_at     DateTimeField(auto_now=True)

    UniqueConstraint(fields=["slug", "language"], name="uniq_publicpage_slug_language")
    Meta.ordering = ["slug", "language"]
    __str__ -> f"{slug} [{language}]"

    def save(self, *args, **kwargs):
        self.language = normalize_lang(self.language)   # INVARIANT, enforced here
        super().save(*args, **kwargs)
```

**The bare-code invariant is enforced in `save()`, not only on the settings-panel write path.**
The model is also registered in the Django admin (`institution/admin.py`) — it holds live legal
text and keeps no history, so a superuser must be able to inspect rows — and that admin is a
second sanctioned write path where a `pl-PL` could otherwise be saved, producing a row the
normalised lookup can never match. Normalising in `save()` closes both paths at once.

`slug` carries **no `choices`**: Django serialises `choices` into migrations, so adding a page —
or editing a title — would emit a spurious `AlterField`, and the `PAGES` titles are
`gettext_lazy` objects with no business in a migration file. **Consequence:** removing a slug from
`PAGES` leaves its rows in the database, invisible to the panel and unreachable by the resolver.
Such rows are inert and cleaned up by hand via the Django admin — the cheaper treatment is
deliberate, because removing a page is a code change whereas disabling a language is a runtime
action.

### New `Institution` fields

| Field | Type | Notes |
|---|---|---|
| `controller_name` | `CharField(max_length=200, blank=True)` | Falls back to `name` when blank |
| `controller_address` | `TextField(blank=True)` | Multi-line; see the `nl2br` rule |
| `contact_email` | `EmailField(blank=True)` | |
| `supervisory_authority` | `CharField(max_length=200, blank=True)` | Falls back to a neutral phrase |
| `demo_instance` | `BooleanField(default=False)` | Gates every demo claim on both pages |

**`core/services.py` must be extended in both return paths.** `_build()` gains **six** keys — the
five above plus `notification_retention_days` — and `_DEFAULTS` gains the same six with these
**exact values**: `controller_name: ""`, `controller_address: ""`, `contact_email: ""`,
`supervisory_authority: ""`, `notification_retention_days: 90` (matching the model default), and
`demo_instance: False`. The last matters: a no-row install defaulting to `True` would tell every
fresh deployment it is a demo.

**Falsy rule — do not copy the surrounding idiom.** `notification_retention_days` and
`demo_instance` must be **bare attribute reads**, following `"onboarded": inst.onboarded`, *not*
the `inst.<field> or _DEFAULTS[...]` pattern every other line uses. `or`-coalescing would silently
rewrite a deliberate `0` ("never purge") to `90`, and would make a real `False` unrepresentable
the moment a default flipped. Only the four string fields coalesce.

### New module: `core/public_pages.py`

Owns `PAGES` (slug → markdown base path, `gettext_lazy` title, `gettext_lazy` meta description,
URL name), the sanitiser configuration, `normalize_lang`, `render_public_page`, and the token
passes.

### Sanitisation: a document allow-list, not the rich-text one

Rendered markdown is sanitised with `nh3`, following the pattern of `courses/sanitize.py` but
**not reusing `sanitize_html`**, whose `ALLOWED_TAGS` (`courses/sanitize.py:15`) is tuned for
rich-text *body* content and contains no `h1`, `table`, `thead`, `tbody`, `tr`, `th`, `td`, or
`hr`.

**The call is pinned exactly, because a plausible-looking variant raises on every request:**

```python
nh3.clean(
    html,
    tags=PUBLIC_PAGE_TAGS,
    attributes={"a": {"href", "title"}},   # NOT "rel" - see below
    url_schemes={"http", "https", "mailto"},
)
```

```
PUBLIC_PAGE_TAGS = {
    h1 h2 h3 h4 h5 h6 p br ul ol li strong b em i code pre blockquote a hr
    table thead tbody tr th td
}
```

**`rel` must NOT appear in the attribute set.** Verified by execution:
`nh3.clean(..., attributes={"a": {"href","title","rel"}})` raises
`ValueError: "rel" attribute is not allowed for tag "a" when link_rel is set; pass link_rel=None`.
`courses/sanitize.py:98` passes `link_rel=None` for exactly this reason, and this module
deliberately does not reuse it. We therefore **keep nh3's default `link_rel`**, which stamps
`rel="noopener noreferrer"` on every `<a>` (verified) — the right behaviour on an anonymous
surface, and markdown cannot emit a `rel` of its own anyway.

`br` is included because a two-space line ending emits `<br />` (verified) which would otherwise
vanish silently; `h5`/`h6` for the same reason. **`img` is excluded on purpose** — these pages are
prose, and an image tag on an anonymous surface whose content an admin can edit is avoidable
attack surface.

**Authoring note:** because no `style` attribute is permitted, markdown's `tables`
column-alignment syntax (`|:---:|`) has **no effect** — the extension emits
`style="text-align: …"`, which nh3 drops silently.

**On the scheme list.** `nh3` **already blocks `javascript:` and `data:` by default** (verified).
`url_schemes` does *not* add protection against those two; what it excludes is `ftp:`, `tel:`,
`magnet:` and friends. The inherited comment at `courses/sanitize.py:43` claiming otherwise is
wrong. Note the observed shape of that exclusion: nh3 strips the **`href` attribute** but keeps
the `<a>` element and its text (`<a rel="noopener noreferrer">y</a>`), which the test row reflects.

**Both content sources go through the same sanitiser** — no trust split, so no branch to get
wrong later.

### Language normalisation

```
def normalize_lang(lang):  # (lang or "en").split("-")[0]
```

Used on **every** path that touches a language code: the DB lookup, the file lookup,
`PublicPage.save()`, and the settings panel's language list. **The panel's normalised language
list is de-duplicated, order-preserving, and read from `get_site_config()` rather than from
`inst` directly** - `_build()` coalesces an empty stored list to `_DEFAULTS["enabled_languages"]`,
so reading `inst.enabled_languages` would render zero language rows on a deployment whose stored
list is empty while the public pages still resolved `["en", "pl"]`. `enabled_languages` is runtime-editable and the whole
justification for normalising is that an admin may put `pl-PL` in it — so `["pl", "pl-PL"]` would
otherwise yield two textareas per page sharing one `name="override-privacy-pl"`, where the last
value silently wins on POST.

### Content resolution

`render_public_page(slug, lang, cfg)` returns `(html, resolved_lang)`, where `html` is
**`mark_safe`-marked** (see §Marking the output safe). `cfg` is the site-config bundle supplied by
the view, which keeps the function injectable from unit tests.

1. `code = normalize_lang(lang)`.
2. **Admin override** — a `PublicPage` row for `(slug, code)` whose `body_markdown` is non-blank
   wins. A blank row is treated as *no override*. `resolved_lang = code`.
3. **Repo template** — otherwise `rel = localized_doc_path(PAGES[slug].path, code)` under
   `DOCS_ROOT`, read as **`read_text(encoding="utf-8")`**. The encoding is mandatory, not
   incidental: without it the platform default applies (cp1250 on this project's Windows dev
   machines, a gotcha this repo has already hit), and a Polish `.pl.md` raises
   `UnicodeDecodeError` — which is a `ValueError`, **not** an `OSError`, so it would escape the
   guard below as a 500 on the marketing surface. With the encoding pinned, the `OSError` guard is
   sufficient.
   **`resolved_lang` is derived from the path actually returned:**
   `resolved_lang = code if rel != PAGES[slug].path else "en"` — stated explicitly because
   `localized_doc_path` returns a *path*, not a language. The comparison is correct when
   `code == "en"` too (the paths are equal, yielding `"en"`).
4. Then: `markdown.markdown(..., extensions=["fenced_code", "tables"])` → `nh3.clean(...)` →
   block-token pass → inline-token pass → `mark_safe`.

On the `OSError` path the function returns `("", code)`.

**The chain does not fall back across languages.** A missing `pl` override does *not* borrow the
`en` override; it falls to the `pl` repo template. Serving English text to a Polish reader is the
worse failure. The risk this creates — an admin overriding one language only — is handled in the
UI: **the panel warns when a page is overridden in some but not all enabled languages.**

### Marking the output safe

`render_public_page` calls `mark_safe` on its return value, immediately after the token passes.
Django autoescapes context variables, so an unmarked string would render escaped tag source as
visible text on the page. Marking it *inside* the renderer keeps the "sanitised, then substituted,
then safe" contract in one place rather than splitting it between the module and the template.

This is also why the testing table carries a **response-level** assertion (a table renders as a
real `<table>` element in the HTTP response) alongside the sanitiser-level ones: every
sanitiser-level row would stay green through a double-escaping bug.

### Token substitution

Identity is injected by `{libli:NAME}` token passes mirroring the existing `{el:slug}` sentinel
idiom, deliberately **not** by the Django template engine. Substitution runs **after**
sanitisation.

**The precise invariant:** a substituted value contributes only text, plus — for
`controller_address` alone — `<br>` elements generated by the escape-then-`nl2br` step. **No value
can ever contribute a tag it contains itself.**

**Substitution uses a function replacement** — `re.sub(pattern, lambda m: value, html)` — never a
string replacement, because `re.sub` interprets `\1`, `\g<0>` and a trailing backslash in the
*replacement*, and these values are admin- and translator-controlled.

**Every token value is coerced with `str(...)` before `html.escape`.** Verified:
`html.escape(90)` raises `AttributeError: 'int' object has no attribute 'replace'`, and
`notification_retention_days` is a `PositiveIntegerField` — so without coercion the privacy page
500s on any deployment with the *default* retention window.

**Two passes, because a block token cannot work as an inline one.** Verified:
`markdown.markdown("{libli:demo_notice}\n\nhi")` yields `<p>{libli:demo_notice}</p>` — the token
is *already wrapped in a paragraph*. Substituting a `<p>…</p>` block there would produce invalid
nested paragraphs; substituting `""` would leave a stray empty `<p></p>` on every non-demo page.

**1. Block pass** — for each **block token**, matches it *with its enclosing paragraph*
(`<p>\s*\{libli:NAME\}\s*</p>`) and replaces the **whole match**. There are **two** block tokens:

- `demo_notice` — the notice block when `demo_instance` is true, the empty string when false.
- `controller_address` — the escaped, `nl2br`'d address wrapped in its paragraph when set, **the
  empty string when blank**, which removes the paragraph entirely.

`controller_address` is a block token *because* its degenerate case is "omit the address". The
inline pass can only replace a token with a string; it cannot delete an enclosing clause. Making
it inline and substituting `""` would leave the stray empty `<p></p>` this spec already identifies
as a failure mode — and would make its test unkillable, since a correct build and the mutant
("substitute `\"\"`") would emit byte-identical output. Block replacement is the only mechanism
here that both deletes the paragraph and gives the assertion something to discriminate on.

**Authoring constraint, same as `demo_notice`:** `{libli:controller_address}` must be a paragraph
of its own at top level, so §Content item 1 is authored as separate sentences and removing the
address paragraph leaves the surrounding prose grammatical.

**2. Inline pass**, running **after** the block pass and over the whole document *including* the
inserted notice:

```
re.sub(r">([^<]*)<", lambda m: ">" + substitute_run(m.group(1)) + "<", html)
    where substitute_run applies re.sub(r"\{libli:(\w+)\}", replace_one, run_text)
    and replace_one returns:
        - html.escape(str(value))                 for every inline token
        - the literal matched text                for anything else
          (including both BLOCK tokens - they are not in the inline map)
```

**The delimiters must be re-emitted.** The pattern *consumes* the `>` and `<`, so a replacement
returning only the run text deletes one bracket on each side of every match — verified:
`<p>Hello {libli:site_name}</p>` becomes `<pHello libli/p>`, destroying every rendered page. This
is the inverse of the block pass, which replaces its whole match deliberately; here the whole
match must be reconstructed.

**`controller_address` normalises line endings before converting them.** The field is edited in a
`<textarea>`, and browsers submit textarea content with **CRLF**, so the stored value contains
`\r\n`. Escaping and then replacing only `\n` yields `line1\r<br>line2` — which renders correctly
(the `\r` is HTML whitespace) but fails any test asserting the substring `line1<br>line2`. So:
normalise `\r\n` and `\r` to `\n`, then escape, then `\n` → `<br>`; and the test fixture uses CRLF
so it exercises the shape an admin actually produces.

**The inline pass's token map contains only the six inline tokens — neither block token is in
it.** That is what makes a misplaced block token fall into the unknown-token branch and render as
literal text (the accepted residual risk below). An implementer who builds one map of all eight
would instead render `html.escape("<p class=…>…</p>")` — visible markup, a worse and
differently-shaped failure than the one documented.

Operating on text runs between `>` and `<` makes "text content only" mechanical, and is why
running after the block pass is safe: the inserted notice's `class` attribute lies outside any
`>…<` run and cannot be corrupted. The pass does **not** exempt `<pre>`/`<code>`, so authors must
not show token syntax verbatim in a code fence.

**Tokens are not substituted inside attribute values — provided no attribute value contains a raw
`>`.** Verified: `markdown.markdown("[mail](mailto:{libli:contact_email})")` yields
`<a href="mailto:{libli:contact_email}">`, which nh3 preserves — substituting there would write an
admin-controlled value into a URL *after* it was vetted.

**The qualification is real and must not be dropped.** nh3 leaves a literal `>` unescaped inside
attribute values (a gotcha this repo has recorded before), so
`[x](https://e.com "a > b")` renders `title="a > b"`, and the `>([^<]*)<` run scan then starts a
"text run" *inside* the `title` attribute — swallowing the rest of the tag. A token positioned
after such a `>` within the same tag would be substituted into an attribute. **Accepted as
residual risk** rather than guarded: reaching it requires an override author, who already holds
`institution.change_institution` and can publish arbitrary prose anyway, and the stronger
invariant survives regardless — values are still `html.escape`d, so no value can contribute a tag.
A test pins the boundary with a link title containing `> {libli:contact_email}` so the behaviour
is recorded rather than assumed.

**Authoring constraint, not optional:** no `{libli:…}` token may appear inside a markdown link
target or any other attribute position. `[write to us](mailto:{libli:contact_email})` would
publish a literal href — a broken link on the very section (§Content item 9) that tells a data
subject how to exercise their rights. A shipped-markdown test asserts no `{libli:` token survives
inside an attribute in any of the four shipped files.

| Token | Kind | Source |
|---|---|---|
| `{libli:controller_name}` | inline | `cfg["controller_name"]` or `cfg["name"]` when blank |
| `{libli:controller_address}` | **block** | `cfg["controller_address"]`, escaped then `\n` → `<br>`; **paragraph removed when blank** |
| `{libli:contact_email}` | inline | `cfg["contact_email"]`, else "the person who runs this site" |
| `{libli:site_name}` | inline | `cfg["name"]` |
| `{libli:supervisory_authority}` | inline | `cfg["supervisory_authority"]`, else a neutral phrase |
| `{libli:embed_domains}` | inline | `settings.ALLOWED_EMBED_DOMAINS`, **normalised** then comma-joined; neutral phrase when empty |
| `{libli:retention_phrase}` | inline | **A complete phrase including the unit** — see below |
| `{libli:demo_notice}` | **block** | The notice when `cfg["demo_instance"]`, else empty |

**The retention token expands to a whole predicate, not a bare number.** It is named
`retention_phrase` rather than `notification_retention_days` precisely so no author is tempted to
write "after {token} days". At the default it renders "after 90 days"; at `0` it renders "until
you delete them". §Content item 8's sentence is authored so the token *is* the predicate, and both
the English and Polish sentences must read correctly under either expansion. Specifying it as a
bare number would make one of the two renderings always broken — "removed after 90" (no unit) or
"removed after until you delete them". The chosen fallback is **"only when you delete them"**, so
both expansions read correctly in the one frame: "removed after 90 days" and "removed only when
you delete them".

**Every deployment-dependent token has a defined degenerate case**, because a token that renders
nothing turns its sentence into a fragment. All seven deployment-dependent tokens, without
exception (`demo_notice`'s own degenerate case - the paragraph removed when `demo_instance` is
false - is specified with the block pass above):

| Token | Degenerate case |
|---|---|
| `controller_name` | blank → `cfg["name"]` (itself defaulting to `"My Institution"`) |
| `controller_address` | blank → **the whole paragraph is removed** (this is why it is a block token) |
| `contact_email` | blank → "the person who runs this site" (no bare empty address) |
| `site_name` | `cfg["name"]` is never blank (`_DEFAULTS` supplies it) |
| `supervisory_authority` | blank → "your national data protection authority" |
| `embed_domains` | empty → a phrase stating no embed providers are enabled |
| `retention_phrase` | `0` → "only when you delete them" (fits the same frame as "after N days") |

`controller_address` and `contact_email` matter most here and are the easiest to overlook: the
default state — no `Institution` row, or an admin who filled in only the name — is a state the
testing table deliberately exercises. Without these two fallbacks that state ships a live privacy
notice naming a controller **at no address**, telling a data subject to send erasure requests to
**an empty string**. Because the address clause is *omitted* rather than filled with a placeholder,
§Content items 1 and 9 must be authored as separate sentences, so removing one leaves the
surrounding prose grammatical.

`{libli:demo_notice}` expands to a pre-built `<p class="public-page__notice">…</p>` assembled with
`format_html` from a translated `gettext` message — never from user input. **The `format_html` is
not decorative:** the block pass runs after `nh3.clean`, so this message is the one string on the
page reaching the browser neither sanitised nor escaped, and a translator's bare `&` or `<` in a
hand-edited `.po` would emit malformed HTML on a live page. `format_html` keeps the trusted
wrapper markup and the escaped message separate.

**Authoring constraints for the demo notice**, both enforced by tests on the shipped markdown:

1. It **MUST be a paragraph of its own at top level.** Inside a list item or mid-sentence markdown
   emits no wrapping `<p>`, the regex will not match, and the literal token renders on a live page
   — silently swallowing the do-not-enter-real-pupil-data warning.
2. It **must carry no heading of its own, and its section must read correctly when the paragraph
   is removed.** The block pass deletes the paragraph and nothing else, so a heading above it
   would leave every non-demo deployment — the default, and every school — rendering an orphaned
   heading with no body.

### Admin editing UI

A new eighth tab, `public-pages`.

- `TABS` gains an eighth entry; `_tabs.html` gains its link and `settings.html` its `data-tab`
  panel.
- `_settings_context` gains **two** keyword arguments: `public_pages` (the `Institution`-fields
  form) and `page_overrides`, **always built on the display path** because the `settings` view
  renders every panel on GET.
- **`page_overrides` has a pinned shape and a pinned order:**

  ```
  [{"slug", "title",
    "rows": [{"language", "value", "enabled": bool, "missing_demo_notice": bool}],
    "partial": bool, "any_missing_demo_notice": bool}, ...]
  ```

  **`missing_demo_notice` is a per-row flag, not a page-level one.** The condition it reports —
  a non-blank override that omits `{libli:demo_notice}` — is a property of one language's text:
  with `en` and `pl` overrides where only one carries the token, a page-level boolean could not
  say which language lost the warning. `partial` genuinely *is* page-level. The page-level
  `any_missing_demo_notice` exists only as a roll-up for the panel's banner.

  Pages iterate in **`PAGES` registry order**; within a page, rows are the de-duplicated
  normalised enabled languages in `enabled_languages` order, followed by stale rows sorted by
  language. Order is pinned because "union" invites a Python `set`, whose iteration order would
  reshuffle textareas between renders and make positional assertions flaky. `partial` and
  `missing_demo_notice` are computed in `_settings_context`, never in the template.
- The panel contains **two independent sibling `<form>` elements** (HTML forbids nesting):
  - `institution:settings_public_pages` — the five `Institution` fields, via a new
    `PublicPagesForm(ModelForm on Institution)`. This one **does** reuse `_action(...)`, called
    as `_action(request, PublicPagesForm, "public_pages", "public-pages", <success msg>)`.
    **This is the first tab where the `ctx_key` and the tab slug diverge** — every existing call
    passes the same literal for both. They must differ here, because `_action` splats
    `**{ctx_key: form}` into `_settings_context` (`institution/views_manage.py:136`) and
    `"public-pages"` is not a valid Python identifier. Getting it wrong raises `TypeError` on the
    invalid-form re-render, a reachable path: `contact_email` is an `EmailField`, so a typo'd
    address would 500 the settings page.
  - `institution:settings_page_overrides` — the override rows. This **cannot** reuse `_action`,
    which binds a single ModelForm to `Institution`. Because `messages.success` lives inside
    `_action`, this view **must emit its own** before redirecting — otherwise the one action that
    publishes live legal text is also the only panel that confirms nothing.
- **The override view's iteration set is exactly the union the panel builds**: `PAGES` ×
  de-duplicated normalised `enabled_languages`, **unioned with the `(slug, language)` pairs of
  existing rows whose slug is still in `PAGES`**. The narrower reading — iterate only enabled
  languages — would render a stale row's textarea, accept its submission and silently ignore it,
  making the row undeletable. The **slug qualification is equally load-bearing in the other
  direction**: without it the view would iterate a pair for a slug no longer in `PAGES`, for which
  the panel never rendered a textarea, so `request.POST.get(...)` returns `""` and the
  delete-when-blank rule would **silently destroy a row this spec twice promises is inert and
  hand-managed** — a history-less deletion of live legal text. Stale *languages* are in the union;
  stale *slugs* are not.
- It reads `request.POST.get(f"override-{slug}-{language}", "")` per pair and **never parses
  submitted key names** — `getting-started` contains hyphens. Per pair: write when non-blank,
  **delete** any existing row when blank.
- Both views are `@login_required` +
  `@permission_required("institution.change_institution", raise_exception=True)`, POST-only with a
  GET redirect to `_index_url("public-pages")`.

The panel lists each page × each language, **plus any existing row whose language is no longer
enabled**, marked as such — without which, disabling a language would hide its rows while they
continued to be served.

**Two warnings, both computed server-side:** *partial override* (some but not all languages), and
*missing demo notice* (when `demo_instance` is true and a non-blank override omits
`{libli:demo_notice}`). Without the second, an admin pasting their own notice — who has never seen
the token — silently removes the warning from a live demo instance.

**Accepted residual risk:** an override that *misplaces* the token publishes literal text. The
panel warns on absence, not placement, because detecting placement means rendering markdown on
save; the consequence is visible text rather than a missing warning.

"Revert to default" is the same operation as saving blank — one code path.

### The footer block

`base.html` gains `{% block footer %}{% endblock %}` **immediately after `</main>`, before the
`<script>` tags** — the only position that puts the footer in normal document flow ahead of the
deferred scripts and the support-dialog include. It renders nothing unless filled, so
authenticated pages are unchanged *in output*.

- `templates/core/landing.html` — the two `<span>` placeholders become real `<a>` elements, and
  the `<span aria-hidden="true">EN / PL</span>` line is **deleted outright**. The landing footer
  stays inside `{% block content %}` where it already lives.
- `templates/allauth/layouts/entrance.html` — fills `{% block footer %}`.
- `templates/core/public_page.html` — fills the same block.

**The entrance layout needs a height fix, or the footer lands below the fold on every login
page.** `.auth-main` currently sets `min-height: calc(100vh - 2 * var(--space-6))` plus padding
(`auth.css:3-11`), so a footer after `</main>` starts outside the viewport — meaning the privacy
link at the point of account creation, driver #2 and "the placement that matters most", would be
reachable only by scrolling a page that otherwise never scrolls.

**The fix needs a viewport floor on the new flex container, not just a flex child.** The height
currently lives entirely on `.auth-main`; `body` carries no height rule. Simply making `body.auth`
a flex column and dropping `.auth-main`'s `min-height` leaves the container at *content* height,
so `flex: 1` has no free space to absorb — the footer would not reach the bottom fold, and the
login card would lose the vertical centring `.auth-main`'s `justify-content: center` gives it and
jump to the top of every entrance page. So the pinned fix is: `body.auth { min-height: 100vh;
display: flex; flex-direction: column }`, `.auth-main { flex: 1 }` **retaining its
`justify-content: center`**, and the `min-height` removed from `.auth-main` only.

**No HTML assertion can catch this** — the links exist in the markup either way — so it is
verified by screenshot, checking **both** that the footer sits at the bottom fold **and** that the
card is still vertically centred. Checking only the first would let the centring regression pass.

### Page template and CSS

One shared template extending `base.html`. The **markdown owns the `<h1>`**; the registry title
fills `{% block head_title %}` as `{{ title }} · {{ site.name|default:"libli" }}`. Each `PAGES`
entry also carries a `gettext_lazy` **meta description** — a real sentence, not the title reused —
emitted via `{% block extra_head %}`.

New CSS: `.public-page` (a prose container composing from the existing 46rem prose cap and body
type scale), `.public-page__notice` (the demo callout, composing from existing surface/border
tokens), the entrance footer's rules, and the `.auth-main` height fix above. `.public-page` does
not exist today — only `.landing-footer` (`app.css:300`). No new design tokens.

### Fallback language

The **view** puts `resolved_lang` in the context and the template always emits
`<div lang="{{ resolved_lang }}">` rather than comparing anything — `LANGUAGE_CODE` can be
regional while `resolved_lang` is always bare, so a naive comparison would mark *every* page as a
fallback.

### i18n

New translatable chrome — the `PAGES` titles and meta descriptions, the demo-notice message, the
two footer link labels, the settings tab and section labels, the override view's success message,
the neutral fallback phrases, and both panel warnings — needs `makemessages`, Polish strings, and
`compilemessages` before the PR.

**`retention_phrase` must use `ngettext`, not a single `msgid`.** Polish declares `nplurals=3`,
so one message id would give 1, 2 and 22 days the same form. The entry is
`msgid "after %(days)d day"` / `msgid_plural "after %(days)d days"`, and all three `msgstr[n]`
slots must be filled -- the 90-day default selects the third.

**Polish inflection is a design constraint, not a translator detail.** Substituted phrases land
mid-sentence in a language that governs case: "prawo do wniesienia skargi do …" requires the
genitive, so a nominative catalogue string reads wrong. **Any sentence hosting a token must be
authored so the token sits in a case-neutral position** — after a colon, or as its own clause —
and the Polish fallback phrases must match the frame their sentence uses. This applies to
`supervisory_authority`, the empty-embed phrase, `retention_phrase`, admin-entered
`controller_name`, **and the `contact_email` fallback phrase** - which lands mid-sentence in
§Content item 9 in exactly the case-governed position this section warns about, so that sentence
places it after a colon or as its own clause.

## Data flow

```
GET /privacy/
  -> core.views_public.privacy (no auth)
       lang = translation.get_language()
       cfg  = get_site_config()                   # bundle, now carrying the six added keys
       html, resolved_lang = render_public_page("privacy", lang, cfg)
                |
                +-- code = normalize_lang(lang)
                +-- PublicPage row (privacy, code) with non-blank body?
                |     yes -> source = row.body_markdown ; resolved_lang = code
                |     no  -> rel = localized_doc_path(PAGES["privacy"].path, code)
                |            resolved_lang = code if rel != PAGES["privacy"].path else "en"
                |            source = (DOCS_ROOT / rel).read_text(encoding="utf-8")
                |                     # OSError -> log, return ("", code)
                +-- markdown.markdown(source, extensions=["fenced_code", "tables"])
                +-- nh3.clean(html, tags=..., attributes={"a": {"href","title"}}, url_schemes=...)
                +-- block-token pass   (demo_notice + controller_address, each with its enclosing <p>)
                +-- inline-token pass  (text runs between > and <; str() then escape)
                +-- mark_safe
       -> render "core/public_page.html" with html, resolved_lang, title, description
```

## Error handling

- **Missing repo template.** `render_public_page` catches `OSError`, logs at `exception` level,
  and returns `("", code)`. Only `OSError` is caught; never a bare `except` — which is safe
  precisely because the encoding is pinned (an unpinned read could raise `UnicodeDecodeError`, a
  `ValueError`, and escape).
- **No `Institution` row** — `_DEFAULTS` carries every key the tokens read, with the exact values
  listed above.
- **Blank override row** — treated as "no override".
- **Missing Polish sibling** — English is served and `resolved_lang` reports `en`.
- **Unknown slug** — unreachable via URL; `KeyError` is a programming error.
- **Blank / degenerate token values** — every one has a defined fallback, so no sentence degrades
  into a fragment.

## Content

Both pages ship real prose in English and Polish, not placeholders.

### Privacy notice (`docs/public/privacy.md` + `privacy.pl.md`)

1. **Who is responsible** — `{libli:controller_name}`, `{libli:controller_address}`,
   `{libli:contact_email}`.
2. **`{libli:demo_notice}`** — its own top-level paragraph, with no heading of its own.
3. **What is held, and why** — account and identity (username, optional email, display/first/last
   name, `external_id`); the learning record; groups; the user's own notes, tags and uploads;
   preferences; support reports. **Names `Attempt` (`courses/models.py:3101`) explicitly**: every
   submitted answer is retained with its timestamp, not merely the latest.
4. **What libli does not collect** — scoped to libli's own processing: no IP addresses in the
   application (`support/telemetry.py:1`), no analytics, no advertising, no profiling or automated
   decision-making, no data sold or shared for marketing, and **no cookies set by libli beyond the
   functional ones listed below**.
5. **Cookies and local storage** — a four-row table with **accurate lifetimes**:

   | Cookie | Purpose | Lifetime |
   |---|---|---|
   | `sessionid` | Keeps your login and, before you log in, your language choice | **Two weeks** (Django default; persistent, not a session cookie) |
   | `csrftoken` | Anti-forgery check on forms | **About a year** (Django default) |
   | `messages` | Carries a one-off confirmation or error between pages | Short-lived |
   | `libli_theme` | Light/dark appearance | One year |

   Browser storage is described **by prefix, not enumerated**: libli stores interface preferences
   — which panels you left open, your editor view mode — in your browser's local storage under
   keys beginning **`libli_`, `libli:` or `libli-`**, written only while using the course editor
   or marking screens. **This is deliberate.** A list claiming to name them "exactly" would be
   false the moment a feature adds one, and this is a document whose value is that its claims
   hold.

   **All three prefixes are documented because all three exist.** `libli-editor-view`
   (`editor.js:763`) uses a hyphen; a two-prefix claim would be **false at HEAD**, and its guard
   test red on a correct build before any mutant. Renaming the key was considered and rejected —
   it would discard every author's stored view mode, and `editor.js:44-47` records that this
   project has previously refused exactly such a rename.

   A test asserts every storage key written by the first-party JS begins with one of the three
   documented prefixes. **Its mechanism is pinned**, because the keys are neither all literals nor
   ever template literals:
   - **Scan roots:** the project's own `<app>/static/**/*.js` under `BASE_DIR` only, explicitly
     excluding `.venv/`, `site-packages/` and `staticfiles/`. A bare `**/static/**/*.js` glob
     would sweep Django's bundled admin JS (`theme.js` writes `"theme"`; `nav_sidebar.js` writes
     `django.admin.navSidebarIsOpen`) and turn the test red for reasons unrelated to libli.
   - **Argument shapes**, and the rules must **compose** or the test is red at HEAD on two of the
     five write sites:
     1. Take the **leading string literal of a concatenation** (so `"libli:tabopen:" + pk + …`
        matches on `libli:tabopen:`).
     2. Resolve a **bare identifier** to its initialiser in the same file — and apply rule 1 to
        that initialiser, because it may itself be a concatenation. `outline_tree.js:7` is
        `var KEY = "libli_outline_open:" + (tree.dataset.courseSlug || "")`, so a rule expecting
        a plain `var NAME = "…"` literal fails there.
     3. Resolve a **call to a same-file function** to the leading string literal of that
        function's `return` expression. `editor.js:52` passes `slotStoreKey(details)`, whose body
        (`editor.js:48`) returns the concatenation — a scanner without this rule never reaches it.
     4. **Fail loudly on any shape it cannot resolve**, so a new dynamic key cannot slip past
        silently.

     There are no template literals in first-party JS today, so that case is future-proofing, not
     the representative one. With rules 1–3 composed, all five sites resolve and the test is green
     at HEAD.
6. **Third parties** — embeds a teacher adds (`{libli:embed_domains}`), stating that the browser
   contacts them directly **only** on pages where a teacher placed one, **and that those providers
   may set their own cookies and storage**; SSO / OpenID Connect when configured; the mail
   provider; the results webhook when an admin enables it; **the web server's access logs, which
   do include IP addresses even though the application never stores them**; and — a distinct
   mechanism — that when a teacher adds an image by URL, **the server** (not the reader's browser)
   fetches it from an allow-listed host, carrying no user data.
7. **Who can see what** — teachers see the records of their own students; platform admins see
   everything; students see nothing about each other; notes and tags are private to their author.
8. **How long it is kept** — **read** notifications are removed `{libli:retention_phrase}`, on a
   schedule **the operator's deployment installs** (a cron line, not something the application
   runs by itself); unread notifications are never removed on age. **Learning records have no
   automatic expiry** and persist while the account does. All three qualifications are
   load-bearing: without them the sentence is false on a deployment that sets `0`, on unread
   notifications, and on any deployment that skipped the cron.
9. **Your rights** — Art. 15–21 and the right to complain to the supervisory authority:
   `{libli:supervisory_authority}` (placed after a colon, per the inflection constraint) —
   followed by the operational truth: no self-service export or delete today, requests go to the
   contact address and are handled by hand, and **deactivating an account is not erasure**.
10. **Children**, **security**, and **changes and effective date**. Security is phrased as a
    property of the production deployment the operator is responsible for. The effective date
    lives in the markdown itself.

### The consent-banner decision

No consent banner ships. ePrivacy and Polish *Prawo telekomunikacyjne* art. 173 exempt storage
**strictly necessary** for a service the user requested. `sessionid`, `csrftoken` and `messages`
clear that bar; `csrftoken`'s ~one-year default lifetime does **not** remove it from the exemption,
since it carries no identifier and exists solely for the anti-forgery check. The first-party
debatable items are the one-year `libli_theme` cookie and the localStorage UI keys; both are
first-party, purely cosmetic, carry no identifier, are never read by a third party and are never
used to recognise a returning visitor.

**The genuinely consent-shaped storage is the third-party embeds', not libli's own.** Those appear
only on authenticated pages a teacher authored; **the two public pages carry no embeds at all.**
Embed storage on authenticated course pages is recorded as residual risk for the operator to
weigh. **This is a decision taken with the risk noted, not a legal opinion.**

### Getting started (`docs/public/getting-started.md` + `getting-started.pl.md`)

- **"Evaluating libli?"** — what the platform does (courses and lessons, roughly thirty element
  types including interactive and mathematical ones, quizzes with automatic marking, teacher
  analytics, English and Polish); **`{libli:demo_notice}` as its own top-level paragraph**, gated
  on `demo_instance` here too so a school deploying libli never tells its own parents that the
  school's instance is a demonstration site; how to reach a human; and an explicit link to the
  privacy notice.
- **"Trying to log in?"** — accounts are created by your school rather than self-service;
  forgotten passwords go through the reset link; invitations expire after 14 days
  (`accounts.models.INVITE_TTL`); anything broken goes to a teacher or the contact address.

## Testing

Every assertion is paired with the mutant that must turn it red.

| Assertion | Mutant that must make it fail |
|---|---|
| Both pages return 200 to an **anonymous** client, in both languages | Add `login_required` to a view |
| **`nh3.clean` is called without `rel` in the attribute set (no `ValueError` on any request)** | Add `"rel"` to the attribute set |
| **A Polish page whose markdown contains non-ASCII renders (no `UnicodeDecodeError`)** | Drop `encoding="utf-8"` from `read_text` |
| **The privacy page renders at the default retention (no `AttributeError` on an int)** | Drop the `str()` coercion |
| Both pages render with **no `Institution` row at all** | Add the keys to `_build()` but not `_DEFAULTS` |
| `get_site_config()` carries all six added keys on **both** return paths | Add them to one path only |
| `notification_retention_days = 0` survives into `get_site_config()` | Use the `or _DEFAULTS` idiom for it |
| `demo_instance = False` survives into `get_site_config()` | Use the `or _DEFAULTS` idiom for it |
| `_DEFAULTS["demo_instance"]` is `False` and `_DEFAULTS["notification_retention_days"]` is `90` | Set either to the other value |
| **A table renders as a real `<table>` element in the HTTP response** | Drop `mark_safe` (double-escaping) |
| A non-blank override row is served instead of the repo template | Reverse the resolution order |
| Deleting the override row falls back to the repo template | Make the fallback unconditional |
| A blank override row is treated as "no override" | Treat any existing row as winning |
| An `en`-only override does **not** leak into the `pl` page | Add a cross-language fallback |
| The panel warns on a partial override | Drop the `partial` flag |
| The panel warns when `demo_instance` and an override omits `{libli:demo_notice}` | Drop the flag |
| A `pl-PL` request serves the `pl` override row | Drop `normalize_lang` from the DB lookup |
| **`PublicPage(language="pl-PL").save()` stores `"pl"`** | Drop `normalize_lang` from `save()` |
| **`enabled_languages = ["pl","pl-PL"]` renders one `pl` textarea per page** | Skip de-duplication |
| `<script>` in an **override** does not reach the response | Drop `nh3.clean` |
| A tag outside `PUBLIC_PAGE_TAGS` in a **repo markdown fixture** is stripped | Sanitise only the override branch |
| **The rendered output contains no `ftp:` URL; the `<a>` element remains, stripped of its href** | Drop `url_schemes` |
| A `javascript:` href does not survive (regression only — passes either way, kept knowingly) | *(none — documented as non-killing)* |
| A **table** survives sanitisation | Swap in `courses.sanitize.sanitize_html` |
| An `h5` heading survives sanitisation | Drop `h5`/`h6` from the allow-list |
| A two-space line break survives as `<br>` | Drop `br` from the allow-list |
| `controller_name` containing markup is escaped | Drop the escaping at substitution |
| `controller_name = r"A\1B"` renders literally and does not raise | Use a string replacement in `re.sub` |
| A multi-line `controller_address` renders `<br>`-separated | Drop the `nl2br` step |
| A token inside an `href` is left literal, not substituted | Substitute over the whole document |
| No `{libli:` token survives inside an attribute in any of the four shipped files | Put a token in a shipped link target |
| An unknown `{libli:nope}` token renders literally | Substitute unknown tokens with `""` |
| **An inline-positioned `{libli:demo_notice}` renders literally, not as escaped markup** | Add `demo_notice` to the inline map |
| `{libli:controller_name}` falls back to `cfg["name"]` when blank | Remove the fallback |
| `{libli:supervisory_authority}` falls back to the neutral phrase when blank | Hardcode "UODO" |
| **A blank `contact_email` renders the fallback phrase, never an empty address** | Substitute `""` |
| **A blank `controller_address` removes its whole paragraph, leaving no empty `<p></p>`** | Make it an inline token substituting `""` |
| **A set `controller_address` renders inside its own paragraph** | Drop the block branch |
| **A token after a raw `>` in a link title IS substituted into the attribute, and the value is still escaped so it cannot break out of the quotes** | *(boundary pinned; documented residual risk)* |
| **`{libli:embed_domains}` strips `www.` and de-duplicates** | Join the raw setting |
| **`<p>x {libli:site_name}</p>` renders with its `<p>` and `</p>` intact** | Drop the delimiters from the inline `re.sub` replacement |
| **A CRLF `controller_address` renders `line1<br>line2` with no stray `\r`** | Skip the newline normalisation |
| `{libli:embed_domains}` renders the neutral phrase when the list is empty | Join an empty list |
| **`{libli:retention_phrase}` renders "after 90 days" at 90 and "only when you delete them" at 0** | Render the bare integer |
| The `pl` sibling is served under `pl` | Ignore the language argument |
| A missing `pl` sibling falls back to English and the body is marked `lang="en"` | Return `code` unconditionally |
| `demo_instance = True` renders the demo block on **both** pages | Hardcode the token to `""` |
| `demo_instance = False` renders no demo block on **both** pages, **and no empty `<p></p>`** | Substitute inline instead of block |
| The shipped markdown places `{libli:demo_notice}` where the block regex matches | Indent the token into a list item |
| **No shipped file has a heading immediately preceding the demo-notice line** | Add one above it |
| A missing template file renders a page shell, not a 500 | Remove the `OSError` guard |
| Each page renders exactly one `<h1>`, from the markdown; `<title>` carries the registry title | Render the registry title as an `<h1>` |
| Each page emits a non-empty `<meta name="description">` | Drop the meta tag |
| The notice's stated `sessionid` lifetime matches `settings.SESSION_COOKIE_AGE` | Change the setting without the text |
| **The stated `csrftoken` lifetime matches `settings.CSRF_COOKIE_AGE`** | Change the setting without the text |
| **The stated `libli_theme` lifetime matches `core/views.py`'s `max_age` constant** | Change the constant without the text |
| **`settings.SESSION_EXPIRE_AT_BROWSER_CLOSE` is falsy** (the notice calls `sessionid` persistent) | Set it to `True` without changing the notice |
| **Every storage key written by FIRST-PARTY JS begins with `libli_`, `libli:` or `libli-`** | Add a key with another prefix |
| **That scan excludes `.venv`/`site-packages`/`staticfiles`** | Glob `**/static/**/*.js` (Django admin JS turns it red) |
| **That scan resolves `KEY` identifiers and concatenated prefixes, and fails loudly on unresolvable shapes** | Match string literals only (5 of 6 sites unchecked) |
| No cookie outside the four documented names is set on the public or entrance pages | Add an undocumented cookie |
| **A `PublicPage` row whose slug is not in `PAGES` survives a panel save untouched** | Union over all existing rows regardless of slug |
| **The `public_pages` ctx_key re-renders an invalid form without `TypeError`** | Pass `"public-pages"` as the ctx_key |
| Landing footer has both links **and** no literal `EN / PL` | Restore the span |
| The entrance layout carries both links | Remove its `footer` block |
| **`/home/`** renders **no** footer | Put content in `base.html`'s `footer` block |
| Both settings views 403 without `institution.change_institution` | Drop `permission_required` |
| A GET to either settings POST target redirects rather than rendering | Drop the GET guard |
| With no stale rows present, the panel renders exactly `len(PAGES) × len(de-duplicated normalised enabled_languages)` textareas | Iterate `settings.LANGUAGES`, or English only |
| The panel also lists a row whose language is no longer enabled | List only enabled languages |
| Blanking a stale-language row's textarea deletes it | Iterate only enabled languages in the view |
| Saving a blank textarea deletes the row rather than storing a blank | Store the blank |
| **The override view emits a success message** | Drop the `messages.success` call |
| A POST key for `getting-started` writes the `getting-started` slug, not `getting` | Parse the key by splitting on `-` |
| Posting `controller_name` through the settings form changes the privacy page's output | Omit the field from the form |

Unit tests cover `render_public_page`, `normalize_lang` and both token passes directly; view tests
cover the two routes, both languages, and the anonymous case; template tests cover all three
footers. **The entrance footer's above-the-fold placement is verified by screenshot**, since no
HTML assertion can see it. No new e2e test is otherwise warranted.

## Accepted decisions worth not re-litigating

- **"Help" points at `/getting-started/`.** `/help/` is the staff area. **Known consequence:** an
  authenticated staff user viewing a public page sees two "Help" links with different destinations
  — the nav one (`base.html:87`) and the footer one. This does *not* affect the landing page,
  which bounces authenticated users to `home`. Relabelling the footer link "Getting started" would
  remove the collision; the "Help" label is kept because it was chosen deliberately.
- **The model lives in `institution`, not `core`**, because `core` has no migrations package.
- **`nh3`'s default `link_rel` is kept** (every `<a>` gets `rel="noopener noreferrer"`) rather than
  passing `link_rel=None` to allow a `rel` attribute markdown cannot emit anyway.
- **One sanitiser for both sources**, so the trust split cannot be got wrong later.
- **`img` is excluded** from the allow-list deliberately.
- **No cross-language override fallback** — language-appropriate text beats content-identical text.
- **Browser storage is described by prefix, not enumerated** — five localStorage keys exist under
  three prefix styles (`libli_`, `libli:`, `libli-`), and a "named exactly" list would rot; a
  prefix test over first-party JS keeps the categorical claim true by construction. The
  `libli-editor-view` hyphen is documented rather than renamed, because renaming would discard
  every author's stored view mode.
- **Deleting a row is the revert action** — one code path, not two.
- **Rows for an unregistered slug are inert** and cleaned up by hand in the Django admin.
- **The panel warns on a missing demo notice but not on a misplaced one** — detecting placement
  means rendering markdown on save, which is out of scope.
- **A public page degrades to an empty body rather than a 500.**
- **The effective date lives in the content.**
- **Recorded exceptions to "no shipped sentence may assert a changeable fact":** the security
  paragraph is phrased as a property of the production deployment; cookie **names** are hardcoded
  as properties of the code; and cookie **lifetimes and persistence** are hardcoded to their
  current values, with guard tests on all **four** (`SESSION_COOKIE_AGE`, `CSRF_COOKIE_AGE`,
  `core/views.py`'s `max_age`, and `SESSION_EXPIRE_AT_BROWSER_CLOSE`) so changing any of them fails
  CI rather than silently falsifying the notice. The fourth is not redundant: setting
  `SESSION_EXPIRE_AT_BROWSER_CLOSE = True` makes `sessionid` a browser-session cookie while
  `SESSION_COOKIE_AGE` stays `1209600`, so the other three guards would all stay green while the
  notice's "persistent, not a session cookie" became false.
- **The `messages` cookie row is knowingly unguarded.** Configuring `MESSAGE_STORAGE` to a session
  backend would remove that cookie entirely, leaving the notice describing one that no longer
  exists — and the "no undocumented cookie" test catches additions, not removals. Accepted because
  the failure direction is **over-disclosure**, which is benign in a privacy notice, unlike the
  lifetime claims where the error direction is understating what is stored.
- **Per-request cost is accepted.** If it ever matters, cache on
  `(slug, lang, PublicPage.updated_at)`.
- **Crawler configuration is out of scope** — a meta description ships, nothing else.
- **Overrides keep no history.** Mitigated by the panel warning before reverting, by the Django
  admin registration, and by telling admins to keep their own copy of any published notice.
