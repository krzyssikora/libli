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
   deployment. Controller identity must come from settings, and an admin must be able to replace
   the shipped text wholesale.

## Background: what exists today

- `config/urls.py:22` mounts `core.urls` at the **root**, so `/help/` already belongs to the
  staff help area (`core/urls.py:17`). That view is `@login_required` and its topics are gated on
  role marker perms (`core/views_help.py:14`, `core/help.py` `TOPICS`). **The public page cannot
  live at `/help/`.**
- Every content path in the application is `@login_required`. The landing page is the only
  anonymous surface. These two pages are the **first public content surface** in the codebase.
- `core/help.py` already owns the markdown idioms this work reuses:
  - `render_markdown_doc(rel_path)` — reads from `DOCS_ROOT` and renders with the `fenced_code`
    and `tables` extensions.
  - `localized_doc_path(base, lang)` — returns the `<name>.<code>.md` sibling when it exists on
    disk, else the English base. Handles a falsy language and a regional code (`pl-PL` → `pl`).
  - Sentinel token rewriting — `src="static:REL"` (`_STATIC_SRC`) and `{el:slug}` (`_EL_TOKEN_RE`),
    where **an unknown slug is left as literal text** so a typo is visible and testable rather
    than a silent blank.
- `.dockerignore` excludes `docs/superpowers`, `docs/mockups` and `docs/planning` but **keeps**
  `docs/help`. A new `docs/public/` therefore ships in the production image, and the existing
  markdown pipeline works in production.
- The settings area has an established pattern: `institution/urls.py` maps
  `/manage/settings/<area>/` to a `settings_<area>` view in `institution/views_manage.py`, each
  `@login_required` + `@permission_required(..., raise_exception=True)`, POST-only with a GET
  redirect guard, rendering the shared `institution/manage/settings.html` via
  `_settings_context(request, inst, active_section, **forms)`.

## Scope

**In scope:** two public pages, their content in English and Polish, the rendering mechanism, the
admin override model and its editing UI, four new `Institution` fields, footer links on the
landing and entrance layouts, and deletion of the `EN / PL` span.

**Out of scope:** authenticated pages keep having no footer. The staff help area is untouched —
no URL renumbering, no change to `core/help.py`. No cookie-consent banner (see §Cookies below for
why none is needed).

## Architecture

### URLs

Two top-level routes in `core/urls.py`, **without** `login_required`:

| Path | Name | Page |
|---|---|---|
| `/privacy/` | `core:privacy` | Privacy notice |
| `/getting-started/` | `core:getting_started` | Getting started |

**Accepted wart:** the footer label reads "Help" but points at `/getting-started/`, because
`/help/` is the staff area. This is chosen deliberately over renumbering existing staff help
links and bookmarks. Do not "fix" it.

### New module: `core/public_pages.py`

All page logic lives in one new module so the trust boundary is in a single readable file. It
does **not** extend `core/help.py`, whose module docstring states its input is trusted repo
markdown to which "the renderer applies no sanitization" — feeding database content through that
function would silently break a documented contract.

The module owns:

- `PAGES` — the registry: slug → (markdown base path, gettext_lazy title, URL name). Two entries:
  `privacy` → `public/privacy.md`, `getting-started` → `public/getting-started.md`.
- `PUBLIC_PAGE_TAGS` / `PUBLIC_PAGE_ATTRIBUTES` / `PUBLIC_PAGE_URL_SCHEMES` — the sanitiser
  allow-list for **document** content (see below).
- `render_public_page(slug, lang)` — the single entry point used by both views.
- `substitute_tokens(html, cfg)` — the `{libli:...}` pass.

### Sanitisation: a document allow-list, not the rich-text one

The rendered markdown is sanitised with `nh3`, following the pattern of `courses/sanitize.py` but
**not reusing `sanitize_html`**. That function's `ALLOWED_TAGS` (`courses/sanitize.py:15`) is
tuned for rich-text *body* content and contains no `h1`, `table`, `thead`, `tbody`, `tr`, `th`,
`td`, or `hr`. Passing a document through it would silently delete the privacy notice's cookie
table and flatten its headings.

`PUBLIC_PAGE_TAGS` is therefore its own set, sized for prose documents:

```
h1 h2 h3 h4 p ul ol li strong b em i code pre blockquote a hr
table thead tbody tr th td
```

with `PUBLIC_PAGE_ATTRIBUTES = {"a": {"href", "title", "rel"}}` and
`PUBLIC_PAGE_URL_SCHEMES = {"http", "https", "mailto"}` (mirroring `courses/sanitize.py:42-44`,
which locks out `javascript:`/`data:` that nh3 permits by default).

**Both content sources go through the same sanitiser.** There is deliberately no trust split
between the shipped template and the admin override: one path means there is no branch to get
wrong later, and the cost is only that a repo template may not use tags outside the allow-list.

### Content resolution

`render_public_page(slug, lang)` resolves in this order, per page **and** per language:

1. **Admin override** — `PublicPage.objects.filter(slug=slug, language=<lang>)`. A row whose
   `body_markdown` is non-blank wins.
2. **Repo template** — otherwise `localized_doc_path("public/<slug>.md", lang)` under `DOCS_ROOT`,
   reusing `core.help.localized_doc_path` unchanged. A Polish request serves
   `docs/public/<slug>.pl.md` when it exists, else falls back to the English base.

Then, for either source: markdown → `nh3.clean` → token substitution → rendered into the page
template.

A shipped template always exists, so a page always renders and the footer links are always live.
**Deleting the override row is the "revert to default" action** — there is no separate revert
flag to keep in sync.

### Token substitution

Identity is injected by a `{libli:NAME}` token pass that mirrors the existing `{el:slug}` and
`src="static:"` sentinel idiom, deliberately **not** by running content through the Django
template engine (which on the override path would be a template-injection vector).

Order matters: substitution runs **after** sanitisation, and every substituted value is
HTML-escaped at injection. Sanitising first then injecting escaped values means a controller name
containing markup can never introduce a tag, and the sanitiser can never mangle a legitimately
escaped value.

Tokens:

| Token | Source |
|---|---|
| `{libli:controller_name}` | `Institution.controller_name`, falling back to `Institution.name` |
| `{libli:controller_address}` | `Institution.controller_address` |
| `{libli:contact_email}` | `Institution.contact_email` |
| `{libli:site_name}` | `Institution.name` |
| `{libli:demo_notice}` | The demo paragraph when `Institution.demo_instance` is true; **empty string** otherwise |

**An unknown token is left as literal text**, matching the `{el:slug}` contract — a typo is
visible on the page and catchable by a test, never a silent blank.

`{libli:demo_notice}` is the one token whose replacement is itself markup rather than a plain
value: it expands to a pre-built, already-safe `<p class="public-page__notice">…</p>` string
built from a translated `gettext` message, not from user input, so it is exempt from escaping by
construction. It expands to the empty string when `demo_instance` is false, so a school's own
deployment shows nothing.

### New model: `core.PublicPage`

```
slug           CharField(max_length=32, choices from PAGES)
language       CharField(max_length=5)
body_markdown  TextField(blank=True)
updated_at     DateTimeField(auto_now=True)

UniqueConstraint(fields=["slug", "language"], name="uniq_publicpage_slug_language")
```

Chosen over four `TextField`s on `Institution` because `Institution.enabled_languages` is already
a runtime-editable JSON list — a per-language row needs no migration when a language is added,
whereas per-language columns would need one every time.

### New `Institution` fields

| Field | Type | Notes |
|---|---|---|
| `controller_name` | `CharField(max_length=200, blank=True)` | Falls back to `name` when blank |
| `controller_address` | `TextField(blank=True)` | |
| `contact_email` | `EmailField(blank=True)` | |
| `demo_instance` | `BooleanField(default=False)` | Gates `{libli:demo_notice}` |

All blank/False by default, so an existing deployment migrates without being forced to answer
anything. One migration adds all four.

These are read through the cached site-config bundle (`core/services.py:102` `get_site_config`),
which is already invalidated by the `Institution` `post_save` signal — so an admin editing them
sees the change immediately without a new invalidation path.

### Admin editing UI

A new settings section at `/manage/settings/public-pages/`
(`institution:settings_public_pages`), following the established pattern exactly: registered in
`institution/urls.py`, implemented in `institution/views_manage.py` as a POST-only view with a
GET redirect guard, `@login_required` + `@permission_required(..., raise_exception=True)`, and
rendered through the shared `institution/manage/settings.html` via `_settings_context`.

The section lists **each page × each enabled language** (from `Institution.enabled_languages`),
each with a textarea holding the current override (empty when none) and a "revert to default"
control that deletes the row. Saving a blank textarea is equivalent to reverting — it deletes any
existing row rather than storing a blank one, so "no override" has exactly one representation in
the database.

Kept deliberately minimal: a plain textarea, no markdown preview, no rich-text editor.

### Page template and styling

One shared template, `templates/core/public_page.html`, extending `base.html`: page title from the
registry, the sanitised HTML in a `.public-page` prose container, and the footer links. Styling
reuses existing tokens and the prose width conventions already in `core/static/core/css/app.css`;
no new design tokens.

### Footer wiring

- `templates/core/landing.html:27-34` — the two `<span>` placeholders become real `<a>` elements,
  and the `<span aria-hidden="true">EN / PL</span>` line is **deleted outright**. It duplicated
  the working header language switcher (`templates/base.html:62`), which is outside the
  `is_authenticated` guard and therefore already present and functional for anonymous visitors on
  the landing page.
- `templates/allauth/layouts/entrance.html` — gains a matching minimal footer carrying the same
  two links. This is the point of account creation and the most important placement.
- Authenticated pages are untouched.

## Data flow

A public page request:

```
GET /privacy/
  -> core.views_public.privacy (no auth)
       lang = translation.get_language()          # SessionLocaleMiddleware already ran
       cfg  = get_site_config()                    # cached bundle
       html = render_public_page("privacy", lang)
                |
                +-- PublicPage row for (privacy, lang) with non-blank body?
                |     yes -> markdown source = row.body_markdown
                |     no  -> rel = localized_doc_path("public/privacy.md", lang)
                |            markdown source = (DOCS_ROOT / rel).read_text()
                |
                +-- markdown.markdown(source, extensions=["fenced_code", "tables"])
                +-- nh3.clean(html, tags=PUBLIC_PAGE_TAGS, ...)
                +-- substitute_tokens(html, cfg)   # escaped values; unknown tokens literal
       -> render "core/public_page.html"
```

The language comes from the request, so the existing `SessionLocaleMiddleware`
(`core/middleware.py:43`) governs it and the header switcher changes the page language with no
extra work.

## Error handling

- **Missing repo template.** `core/help.py` treats a missing file as a packaging bug and fails
  loud. That is right for a staff page but wrong for a *public* one — a 500 on the marketing
  surface is worse than a thin page. The view catches `OSError` from the template read, logs it
  at `exception` level, and renders the page shell with an empty body. The footer link therefore
  never produces a 500. This is the one deliberate divergence from the help module's contract,
  and it is recorded in the module docstring.
- **Unknown slug** — not reachable via URL (both routes are static paths, no slug capture), so
  there is no 404 path to design. `render_public_page` raises `KeyError` on an unregistered slug,
  which is a programming error, not a request outcome.
- **Blank override row** — treated as "no override" (see above), never as an empty page.
- **Missing Polish sibling** — already handled by `localized_doc_path`: falls back to English.
  A page is never blank because a translation is absent.
- **Blank `Institution` fields** — `controller_name` falls back to `name`; the others substitute
  to an empty string. The page still renders; it simply lacks that detail. The shipped content is
  written so an empty contact address degrades to a still-readable sentence.

## Content

### Privacy notice (`docs/public/privacy.md` + `privacy.pl.md`)

Real prose in both languages, not placeholders. Sections:

1. **Who is responsible** — `{libli:controller_name}`, `{libli:controller_address}`,
   `{libli:contact_email}`.
2. **`{libli:demo_notice}`** — on a demo instance only: this is a demonstration system, data
   entered here is visible to the operator, **do not enter real pupil data**.
3. **What is held, and why** — grouped by purpose: account and identity (username, optional
   email, display/first/last name, `external_id`); the learning record; groups and classes; the
   user's own notes, tags and uploads; preferences; support reports. This section **names
   `Attempt` (`courses/models.py:3101`) explicitly**: every submitted answer is retained with its
   timestamp, not merely the latest one. That is the fact a DPO would otherwise discover later
   and reasonably feel misled about.
4. **What is not collected** — no IP addresses in the application (the stance is already written
   into `support/telemetry.py:1`), no analytics, no advertising, no profiling or automated
   decision-making, no data sold or shared for marketing, no cookies beyond the functional ones.
5. **Cookies and local storage** — a three-row table: `sessionid` (login), `csrftoken`
   (security), `libli_theme` (appearance, `Max-Age` 31536000 ≈ 1 year,
   `core/static/core/js/ui.js:4`), plus the localStorage UI preferences
   (`libli_unit_tree_collapsed`, `libli-editor-view`, the outline-tree state). All first-party,
   none used for tracking — hence no consent banner.
6. **Third parties** — embeds a teacher adds, naming the current allow-list from
   `config/settings/base.py:214` (YouTube, Vimeo, GeoGebra, Edpuzzle, Lumi) and stating honestly
   that the browser contacts them directly **only** on pages where a teacher placed one; SSO /
   OpenID Connect when configured; the mail provider; the results webhook
   (`integrations/models.py:7`) when an admin enables it; **and the web server's access logs,
   which do include IP addresses even though the application never stores them.** That
   distinction is stated, not fudged into a flat "we don't log IPs".
7. **Who can see what** — teachers see the records of their own students; platform admins see
   everything; students see nothing about each other; notes and tags are private to their author.
8. **How long it is kept** — notifications are purged per `notification_retention_days`
   (default 90; `notifications/management/commands/purge_notifications.py` is the only purge job);
   **learning records have no automatic expiry today** and persist while the account does. Stated
   plainly.
9. **Your rights** — Art. 15–21 and the right to complain to UODO, followed by the operational
   truth: there is no self-service export or delete today (`accounts/views_manage.py` offers
   deactivate/reactivate only), requests go to the contact address and are handled by hand, and
   **deactivating an account is not erasure**.
10. **Children**, **security** (HTTPS, secure cookies, Django password hashing, role-based
    access — no overclaiming), and **changes and effective date**. The effective date lives in the
    markdown text itself, since only a human knows whether a change was substantive.

### Getting started (`docs/public/getting-started.md` + `getting-started.pl.md`)

One sentence on what libli is, then a split by reader:

- **"Evaluating libli?"** — what the platform does (courses and lessons, roughly thirty element
  types including interactive and mathematical ones, quizzes with automatic marking, teacher
  analytics, English and Polish); that **this site is a live demo**, what a visitor may click, and
  the same do-not-enter-real-data warning; how to reach a human; and an explicit link to the
  privacy notice, because that is the first thing a school's DPO asks for.
- **"Trying to log in?"** — accounts are created by your school rather than self-service;
  forgotten passwords go through the reset link on the login page; invitations expire after 14
  days (`accounts.models.INVITE_TTL`) so ask for a fresh one; anything broken goes to a teacher or
  the contact address.

## Testing

Every assertion must be able to fail. Each is paired with the mutant that must turn it red.

| Assertion | Mutant that must make it fail |
|---|---|
| Both pages return 200 to an **anonymous** client, in both languages | Add `login_required` to a view |
| A non-blank override row is served instead of the repo template | Reverse the resolution order |
| Deleting the override row falls back to the repo template | Make the fallback unconditional/absent |
| A blank override row is treated as "no override" | Treat any existing row as winning |
| `<script>alert(1)</script>` in an override does **not** reach the response | Drop the `nh3.clean` call |
| A `javascript:` href in an override does not survive | Drop `PUBLIC_PAGE_URL_SCHEMES` |
| A **table** in a page survives sanitisation | Swap in `courses.sanitize.sanitize_html` |
| `controller_name` containing markup is escaped in the output | Drop the escaping at substitution |
| An unknown `{libli:nope}` token renders literally | Substitute unknown tokens with `""` |
| `{libli:controller_name}` falls back to `Institution.name` when blank | Remove the fallback |
| The `pl` sibling is served under `pl` | Ignore the language argument |
| A missing `pl` sibling falls back to English | Remove the `exists()` check |
| `demo_instance = True` renders the demo paragraph | Hardcode the token to `""` |
| `demo_instance = False` renders **no** demo paragraph | Hardcode the token to the paragraph |
| A missing template file renders a page shell, not a 500 | Remove the `OSError` guard |
| Landing footer contains both links **and** no longer contains the literal `EN / PL` | Restore the span |
| The entrance layout carries both links | Remove the footer block |
| The settings section requires the permission (403 for an authed user without it) | Drop `permission_required` |
| Saving a blank textarea deletes the row rather than storing a blank one | Store the blank |

Unit tests cover `render_public_page` and `substitute_tokens` directly; view tests cover the two
routes, both languages, and the anonymous case; template tests cover the two footers. No new e2e
test is warranted — there is no interactive behaviour on these pages.

## Accepted decisions worth not re-litigating

- **"Help" points at `/getting-started/`.** `/help/` is the staff area; renumbering it is not
  worth it.
- **One sanitiser for both sources**, rather than trusting repo markdown and sanitising only
  overrides. The single path cannot be got wrong later.
- **Deleting a row is the revert action**, rather than a separate default flag.
- **A public page degrades to an empty body rather than a 500** when its template is missing —
  the opposite of `core/help.py`'s fail-loud stance, and deliberately so.
- **The effective date lives in the content**, not in a field, because only a human knows whether
  an edit was substantive.
