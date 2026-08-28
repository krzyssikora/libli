# Public privacy notice and getting-started page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the landing footer's two inert `Privacy` / `Help` placeholders into real public pages in English and Polish, and delete the redundant `EN / PL` span.

**Architecture:** Two anonymous top-level routes render trusted repo markdown (or a per-language admin override row) through one pipeline: markdown → nh3 sanitise → block-token pass → inline-token pass → `mark_safe`. Deployment identity (controller, contact, supervisory authority, demo flag) is injected by `{libli:…}` sentinel tokens read from the cached site-config bundle, so nothing deployment-specific is hardcoded in the shipped text. A new eighth settings tab edits both the identity fields and the per-page/per-language overrides.

**Tech Stack:** Django 5, `nh3` (sanitiser), `markdown` (with `fenced_code` + `tables`), pytest + pytest-django, gettext/`.po` catalogues.

**Spec:** `docs/superpowers/specs/2026-08-28-public-privacy-and-getting-started-design.md`

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the spec.

- **The public pages must never 500.** `render_public_page` catches `OSError` only — never a bare `except` — and returns `("", code)`. This is safe *only* because the file read pins `encoding="utf-8"`; an unpinned read raises `UnicodeDecodeError` (a `ValueError`), which would escape the guard.
- **The pinned `nh3.clean` call.** `attributes={"a": {"href", "title"}}` — **`rel` must NOT appear**. `nh3.clean(..., attributes={"a": {"href","title","rel"}})` raises `ValueError: "rel" attribute is not allowed for tag "a" when link_rel is set`. Keep nh3's default `link_rel`, which stamps `rel="noopener noreferrer"` on every `<a>`.
- **`PUBLIC_PAGE_TAGS`** = `h1 h2 h3 h4 h5 h6 p br ul ol li strong b em i code pre blockquote a hr table thead tbody tr th td`. **`img` is excluded on purpose.**
- **`PUBLIC_PAGE_URL_SCHEMES`** = `{"http", "https", "mailto"}`. nh3 already blocks `javascript:`/`data:` by default; this set excludes `ftp:`/`tel:`/`magnet:`.
- **Every token value is coerced with `str(...)` before `html.escape`.** This guards the *lazy-proxy* case: several values are `gettext_lazy` proxies, and `str()` forces them at substitution time under the active language. **Note honestly: this is a non-killing constraint.** The spec's paired mutant ("drop the `str()` coercion") no longer dies, because `retention_phrase` resolved the only int into a formatted string. Keep the coercion for the lazy case; do not write a test that cannot fail.
- **Token substitution uses a function replacement**, never a string replacement: `re.sub(pattern, lambda m: value, html)`. `re.sub` interprets `\1`, `\g<0>` and a trailing backslash in the replacement, and these values are admin- and translator-controlled.
- **The inline pass must re-emit its delimiters.** The pattern consumes `>` and `<`; a replacement returning only the run text yields `<pHello libli/p>`.
- **Two block tokens** (`demo_notice`, `controller_address`), **six inline tokens**. Neither block token appears in the inline map.
- **`normalize_lang` on every path** that touches a language code: DB lookup, file lookup, `PublicPage.save()`, and the settings panel's language list (de-duplicated, order-preserving).
- **`_build()` and `_DEFAULTS` both gain six keys.** `notification_retention_days` and `demo_instance` are **bare attribute reads** — never the `inst.<field> or _DEFAULTS[...]` idiom, which would rewrite `0` to `90` and make `False` unrepresentable.
- **No shipped sentence may assert a fact a deployment can change** (recorded exceptions are listed in the spec's §Accepted decisions).
- **Permission:** both settings views use `@login_required` + `@permission_required("institution.change_institution", raise_exception=True)`, POST-only with a GET redirect.

## How to run tests

The test-DB container must be running **first**, or the run appears hung for ~4 minutes:

```bash
docker compose -f docker-compose.test.yml up -d
uv run python -m pytest tests/test_public_pages.py -v
```

`uv` is not on `PATH` as a bare command in every shell; use `uv run python -m pytest`. Never run a whole-repo sweep as a task step — scope each run to the files the task touches. Grep the summary line: pytest can exit 0 while reporting `1 failed`.

## File Structure

| File | Responsibility |
|---|---|
| `core/public_pages.py` *(new)* | `PAGES` registry, `normalize_lang`, sanitiser config, both token passes, `render_public_page`. The whole trust boundary in one readable file. |
| `core/views_public.py` *(new)* | Two thin anonymous views: fetch `cfg`, call the renderer, render the template. |
| `core/urls.py` | Two new routes, no `login_required`. |
| `core/services.py` | `_build()` + `_DEFAULTS` gain six keys. |
| `institution/models.py` | `PublicPage` model; five new `Institution` fields. |
| `institution/forms.py` | `PublicPagesForm` (ModelForm on `Institution`). |
| `institution/views_manage.py` | Two POST targets, `TABS` entry, `_settings_context` kwargs, `page_overrides` builder. |
| `institution/admin.py` | Register `PublicPage`. |
| `templates/core/public_page.html` *(new)* | Shared page shell: body, `lang` wrapper, meta description, footer. |
| `templates/institution/manage/_public_pages_tab.html` *(new)* | The panel: two sibling forms. |
| `docs/public/*.md` *(new, 4 files)* | Shipped EN + PL content. |

**Circular-import note, load-bearing:** `institution/models.py` imports `normalize_lang` from `core.public_pages` at module level. `core/public_pages.py` must therefore import `PublicPage` **inside** `render_public_page`, not at module level — exactly the pattern `core/services.py:71` already uses (`def _build(): from institution.models import Institution`). A module-level import in `core/public_pages.py` creates a cycle that fails at startup.

---

### Task 1: `normalize_lang` and the `PAGES` registry

**Files:**
- Create: `core/public_pages.py`
- Test: `tests/test_public_pages.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `normalize_lang(lang) -> str`; `PAGES: dict[str, Page]` where `Page` is a frozen dataclass with fields `slug: str`, `path: str`, `title` (lazy), `description` (lazy). There is deliberately **no** `url_name` field: markdown cannot reverse a URL, so it would be dead data.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_public_pages.py
import pytest

from core.public_pages import PAGES
from core.public_pages import normalize_lang


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("en", "en"), ("pl", "pl"), ("pl-PL", "pl"),
        ("PL-pl", "PL"), ("", "en"), (None, "en"),
    ],
)
def test_normalize_lang(raw, expected):
    assert normalize_lang(raw) == expected


def test_pages_registry_shape():
    assert set(PAGES) == {"privacy", "getting-started"}
    assert PAGES["privacy"].path == "public/privacy.md"
    assert PAGES["getting-started"].path == "public/getting-started.md"
    for page in PAGES.values():
        assert str(page.title)
        assert str(page.description)
```

Note `("PL-pl", "PL")`: `normalize_lang` splits on `-` and does **not** lower-case, matching `localized_doc_path` in `core/help.py` exactly. Django hands us lower-cased codes, so this only pins that we do not add behaviour the help module lacks.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_public_pages.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.public_pages'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/public_pages.py
"""Public (anonymous) content pages: privacy notice and getting-started.

Renders trusted repo markdown from docs/public/, or a per-language admin
override row, through ONE pipeline: markdown -> nh3 sanitise -> block-token
pass -> inline-token pass -> mark_safe.

Deliberately does NOT reuse core.help.render_markdown_doc: that function's
docstring states its input is trusted repo markdown to which "the renderer
applies no sanitization". Database content must not travel that path. Only
localized_doc_path and DOCS_ROOT are reused from core.help; consequently the
`src="static:REL"` and {el:slug} sentinels do NOT work in docs/public/.
"""

from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _


def normalize_lang(lang):
    """Bare language code: falsy -> "en", regional -> its base ("pl-PL" -> "pl").

    Mirrors localized_doc_path in core/help.py so the DB lookup and the file
    lookup key on the same space. Used on every path that touches a language
    code, including PublicPage.save() and the settings panel's language list.
    """
    return (lang or "en").split("-")[0]


@dataclass(frozen=True)
class Page:
    slug: str
    path: str  # markdown base path, relative to core.help.DOCS_ROOT
    title: object  # gettext_lazy
    description: object  # gettext_lazy; the <meta name="description">


PAGES = {
    "privacy": Page(
        "privacy",
        "public/privacy.md",
        _("Privacy notice"),
        _("What libli stores about you, who can see it, how long it is kept, "
          "and how to exercise your data-protection rights."),
    ),
    "getting-started": Page(
        "getting-started",
        "public/getting-started.md",
        _("Getting started"),
        _("What libli is, how schools use it, and how to get an account or "
          "reach a human."),
    ),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_public_pages.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add core/public_pages.py tests/test_public_pages.py
git commit -m "feat(public-pages): add normalize_lang and the PAGES registry"
```

---

### Task 2: The sanitiser

**Files:**
- Modify: `core/public_pages.py`
- Test: `tests/test_public_pages.py`

**Interfaces:**
- Consumes: nothing (same module as Task 1; the sanitiser references neither `PAGES` nor `normalize_lang`).
- Produces: `PUBLIC_PAGE_TAGS: frozenset[str]`; `render_markdown(source: str) -> str` — markdown-rendered, sanitised HTML with no token substitution yet.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_public_pages.py
from core.public_pages import render_markdown


def test_table_survives_sanitisation():
    html = render_markdown("| a | b |\n| --- | --- |\n| 1 | 2 |\n")
    assert "<table>" in html
    assert "<td>1</td>" in html


def test_deep_heading_survives():
    assert "<h5>Deep</h5>" in render_markdown("##### Deep\n")


def test_two_space_line_break_survives():
    assert "<br" in render_markdown("a  \nb\n")


def test_script_is_stripped():
    html = render_markdown("<script>alert(1)</script>ok\n")
    assert "<script" not in html
    assert "alert(1)" not in html


def test_ftp_href_is_stripped_but_anchor_remains():
    # nh3 with a restricted url_schemes drops the href ATTRIBUTE and keeps the
    # element. Asserting `"<a" not in html` would be red on a correct build.
    html = render_markdown("[y](ftp://h/f)\n")
    assert "ftp:" not in html
    assert "<a" in html
    assert ">y</a>" in html


def test_javascript_href_does_not_survive():
    # Regression only: nh3 blocks javascript: by DEFAULT, so this passes with or
    # without PUBLIC_PAGE_URL_SCHEMES. Kept knowingly; the ftp test is the one
    # that actually kills the mutant.
    assert "javascript:" not in render_markdown("[j](javascript:alert(1))\n")


def test_image_is_excluded_on_purpose():
    assert "<img" not in render_markdown("![alt](https://example.com/a.png)\n")


def test_sanitiser_does_not_raise_on_a_link():
    # Guards the pinned attribute set: including "rel" raises ValueError on EVERY
    # call, because nh3 sets link_rel by default.
    html = render_markdown("[y](https://example.com)\n")
    assert 'rel="noopener noreferrer"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_public_pages.py -v`
Expected: FAIL — `ImportError: cannot import name 'render_markdown'`

- [ ] **Step 3: Write minimal implementation**

Add to `core/public_pages.py`. **New imports go into the module's top-of-file import block, isort-ordered — stdlib, then third-party, then `core.*`, one name per line** — not at the point of use, which would trip ruff `E402` and `I`. **This applies to the test modules too:** every block below headed `# append to tests/...` means append the *body*; its imports belong in that file's top import block. `pyproject.toml`'s `per-file-ignores` for `tests/**` covers only `S105/S106/S107`, so `E402` fires in tests exactly as it does in application code. The same applies to Tasks 3 and 8. After assembling each test module, run `uv run ruff check --no-cache --fix <file>` and `uv run ruff format <file>` before committing, so the final gate has nothing left to find.

```python
import markdown
import nh3

# A DOCUMENT allow-list, not courses.sanitize's rich-text one. That module's
# ALLOWED_TAGS (courses/sanitize.py:15) has no h1/table/thead/tbody/tr/th/td/hr,
# so a document passed through it loses its tables and headings silently.
PUBLIC_PAGE_TAGS = frozenset({
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "ul", "ol", "li",
    "strong", "b", "em", "i", "code", "pre", "blockquote", "a", "hr",
    "table", "thead", "tbody", "tr", "th", "td",
})
# "rel" must NOT be here: nh3 raises ValueError when link_rel is set (its
# default), and we keep that default so every <a> gets rel="noopener noreferrer"
# -- the right behaviour on an anonymous surface. Markdown cannot emit rel anyway.
PUBLIC_PAGE_ATTRIBUTES = {"a": {"href", "title"}}
# nh3 ALREADY blocks javascript: and data: by default. This set excludes ftp:,
# tel:, magnet: and friends. (courses/sanitize.py:43's comment claims otherwise
# and is wrong.)
PUBLIC_PAGE_URL_SCHEMES = {"http", "https", "mailto"}


def render_markdown(source):
    """Markdown -> sanitised HTML. No token substitution: that runs after."""
    html = markdown.markdown(source or "", extensions=["fenced_code", "tables"])
    return nh3.clean(
        html,
        tags=set(PUBLIC_PAGE_TAGS),
        attributes=PUBLIC_PAGE_ATTRIBUTES,
        url_schemes=PUBLIC_PAGE_URL_SCHEMES,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_public_pages.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/public_pages.py tests/test_public_pages.py
git commit -m "feat(public-pages): add the document sanitiser allow-list"
```

---

### Task 3: The two token passes

**Files:**
- Modify: `core/public_pages.py`
- Test: `tests/test_public_pages.py`

**Interfaces:**
- Consumes: `render_markdown` (Task 2).
- Produces: `substitute_tokens(html: str, cfg: dict) -> str` — runs the block pass then the inline pass. `BLOCK_TOKENS: frozenset[str]`, `INLINE_TOKENS: frozenset[str]`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_public_pages.py
from core.public_pages import substitute_tokens

BASE_CFG = {
    "name": "Greenfield School",
    "controller_name": "",
    "controller_address": "",
    "contact_email": "",
    "supervisory_authority": "",
    "notification_retention_days": 90,
    "demo_instance": False,
}


def cfg(**over):
    return {**BASE_CFG, **over}


def render(source, **over):
    return substitute_tokens(render_markdown(source), cfg(**over))


def test_delimiters_are_re_emitted():
    # As-pinned-wrongly this yields "<pHello Greenfield School/p>".
    out = render("Hello {libli:site_name}\n")
    assert out == "<p>Hello Greenfield School</p>"


def test_controller_name_falls_back_to_site_name():
    assert "Greenfield School" in render("{libli:controller_name}\n")


def test_controller_name_is_escaped():
    out = render("{libli:controller_name}\n", controller_name="A <b>B</b>")
    assert "<b>" not in out
    assert "&lt;b&gt;" in out


def test_backslash_group_reference_does_not_raise():
    # A string replacement would raise re.error or emit a capture group here.
    out = render("{libli:controller_name}\n", controller_name=r"A\1B")
    assert r"A\1B" in out


def test_unknown_token_renders_literally():
    assert "{libli:nope}" in render("{libli:nope}\n")


def test_retention_phrase_at_default_and_zero():
    assert "after 90 days" in render("{libli:retention_phrase}\n")
    assert "only when you delete them" in render(
        "{libli:retention_phrase}\n", notification_retention_days=0
    )


def test_supervisory_authority_fallback():
    assert "your national data protection authority" in render(
        "{libli:supervisory_authority}\n"
    )
    assert "UODO" in render(
        "{libli:supervisory_authority}\n", supervisory_authority="UODO"
    )


def test_contact_email_fallback():
    assert "the person who runs this site" in render("{libli:contact_email}\n")
    assert "dpo@x.pl" in render("{libli:contact_email}\n", contact_email="dpo@x.pl")


def test_embed_domains_normalised_and_deduped(settings):
    settings.ALLOWED_EMBED_DOMAINS = ["www.youtube.com", "youtube.com", "youtu.be"]
    out = render("{libli:embed_domains}\n")
    assert "youtube.com" in out
    assert "www.youtube.com" not in out
    assert out.count("youtube.com") == 1


def test_embed_domains_empty_renders_a_phrase(settings):
    settings.ALLOWED_EMBED_DOMAINS = []
    assert "no embed providers are enabled" in render("{libli:embed_domains}\n")


def test_demo_notice_block_present_and_absent():
    on = render("a\n\n{libli:demo_notice}\n\nb\n", demo_instance=True)
    assert "public-page__notice" in on
    off = render("a\n\n{libli:demo_notice}\n\nb\n", demo_instance=False)
    assert "public-page__notice" not in off
    assert "<p></p>" not in off  # the WHOLE paragraph goes, not just the token
    assert "{libli:demo_notice}" not in off


def test_controller_address_block_set_and_blank():
    on = render(
        "{libli:controller_address}\n",
        controller_address="Ul. Kwiatowa 1\r\n00-001 Warszawa",
    )
    assert "<p>Ul. Kwiatowa 1<br>00-001 Warszawa</p>" in on
    assert "\r" not in on  # CRLF normalised BEFORE nl2br
    off = render("x\n\n{libli:controller_address}\n\ny\n")
    assert "<p></p>" not in off
    assert "{libli:controller_address}" not in off


def test_block_tokens_are_not_in_the_inline_map():
    # A misplaced block token must fall to the UNKNOWN branch (literal text),
    # not be substituted with escaped markup.
    out = render("- {libli:demo_notice}\n", demo_instance=True)
    assert "{libli:demo_notice}" in out
    assert "&lt;p" not in out


def test_token_in_an_href_is_left_literal():
    out = render("[mail](mailto:{libli:contact_email})\n", contact_email="dpo@x.pl")
    assert "mailto:{libli:contact_email}" in out
    assert "mailto:dpo@x.pl" not in out


def test_token_after_a_raw_gt_in_a_title_IS_substituted():
    # Documented, accepted residual risk: nh3 leaves a raw > unescaped inside an
    # attribute, which ends the >...< run early. The value is still escaped, so
    # it cannot break out of the quotes. Asserting the opposite would be RED.
    out = render(
        '[x](https://e.com "a > {libli:contact_email}")\n',
        contact_email="dpo@x.pl",
    )
    assert "dpo@x.pl" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_public_pages.py -v`
Expected: FAIL — `ImportError: cannot import name 'substitute_tokens'`

- [ ] **Step 3: Write minimal implementation**

Add to `core/public_pages.py`:

```python
import html as html_lib
import re

from django.conf import settings
from django.utils.html import format_html
from django.utils.translation import ngettext

BLOCK_TOKENS = frozenset({"demo_notice", "controller_address"})
INLINE_TOKENS = frozenset({
    "controller_name", "contact_email", "site_name",
    "supervisory_authority", "embed_domains", "retention_phrase",
})

_INLINE_RE = re.compile(r"\{libli:(\w+)\}")
_RUN_RE = re.compile(r">([^<]*)<")


def _block_re(name):
    return re.compile(r"<p>\s*\{libli:" + name + r"\}\s*</p>")


def _nl2br(value):
    """Normalise CRLF FIRST, then convert. A <textarea> submits \\r\\n, and
    replacing only \\n would leave a stray \\r inside the rendered address."""
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _demo_notice_html():
    # format_html, not concatenation: this string is inserted AFTER nh3, so it is
    # the one value on the page reaching the browser unsanitised. A translator's
    # bare & or < in a hand-edited .po would otherwise emit malformed HTML.
    return format_html(
        '<p class="public-page__notice">{}</p>',
        _("This is a demonstration site. Anything you enter here is visible to "
          "the person who runs it — please do not enter real pupil data."),
    )


def _inline_values(cfg):
    """The six inline token values, each already a str, each with its degenerate
    case resolved. Escaping happens at substitution, not here."""
    days = cfg["notification_retention_days"]
    domains = []
    for host in settings.ALLOWED_EMBED_DOMAINS:
        host = host[4:] if host.startswith("www.") else host
        if host not in domains:
            domains.append(host)
    return {
        "controller_name": cfg["controller_name"] or cfg["name"],
        "contact_email": cfg["contact_email"] or _("the person who runs this site"),
        "site_name": cfg["name"],
        "supervisory_authority": (
            cfg["supervisory_authority"] or _("your national data protection authority")
        ),
        "embed_domains": (
            ", ".join(domains) if domains else _("no embed providers are enabled")
        ),
        # ngettext, not _: Polish declares nplurals=3, so a single msgid gives
        # one form for 1, 2 and 22 days. Resolved here, at substitution time, so
        # the active language picks the form.
        "retention_phrase": (
            ngettext(
                "after %(days)d day", "after %(days)d days", days
            ) % {"days": days}
            if days
            else _("only when you delete them")
        ),
    }


def substitute_tokens(html, cfg):
    """Block pass then inline pass. Runs AFTER sanitisation."""
    # --- Block pass: replace the token WITH its enclosing <p>. Substituting a
    # <p> block inline would nest paragraphs; substituting "" would leave an
    # empty <p></p> on every page where the block is off.
    # Driven off BLOCK_TOKENS so the frozenset cannot drift out of sync with
    # the literals -- a set that nothing reads is documentation, not code.
    address = cfg["controller_address"]
    if address:
        rendered = "<p>" + _nl2br(html_lib.escape(str(address))) + "</p>"
    else:
        rendered = ""
    block_values = {
        "demo_notice": _demo_notice_html() if cfg["demo_instance"] else "",
        "controller_address": rendered,
    }
    assert set(block_values) == set(BLOCK_TOKENS)
    for name in BLOCK_TOKENS:
        value = block_values[name]
        html = _block_re(name).sub(lambda m, v=value: v, html)

    # --- Inline pass: TEXT RUNS ONLY, delimiters re-emitted. A token inside an
    # attribute is left literal (it lies outside any >...< run).
    values = _inline_values(cfg)

    def replace_one(match):
        name = match.group(1)
        if name not in INLINE_TOKENS:
            return match.group(0)  # unknown OR a misplaced block token -> literal
        return html_lib.escape(str(values[name]))

    def substitute_run(match):
        return ">" + _INLINE_RE.sub(replace_one, match.group(1)) + "<"

    return _RUN_RE.sub(substitute_run, html)
```

Add the import `from django.utils.translation import gettext_lazy as _` if not already present from Task 1 (it is).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_public_pages.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/public_pages.py tests/test_public_pages.py
git commit -m "feat(public-pages): add the block and inline token passes"
```

---

### Task 4: `PublicPage` model, `Institution` fields, migration, admin

**Files:**
- Modify: `institution/models.py`, `institution/admin.py`
- Create: `institution/migrations/00XX_publicpage_and_controller_fields.py` (generated)
- Test: `tests/test_public_pages_model.py`

**Interfaces:**
- Consumes: `normalize_lang` (Task 1).
- Produces: `institution.models.PublicPage` with fields `slug`, `language`, `body_markdown`, `updated_at`; `Institution.controller_name`, `.controller_address`, `.contact_email`, `.supervisory_authority`, `.demo_instance`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_public_pages_model.py
import pytest

from institution.models import Institution
from institution.models import PublicPage


@pytest.mark.django_db
def test_save_normalises_a_regional_language_code():
    # The Django admin is a second sanctioned write path, so the invariant must
    # live in save(), not only in the settings panel.
    row = PublicPage.objects.create(slug="privacy", language="pl-PL", body_markdown="x")
    row.refresh_from_db()
    assert row.language == "pl"


@pytest.mark.django_db
def test_str_and_ordering():
    PublicPage.objects.create(slug="privacy", language="pl", body_markdown="x")
    PublicPage.objects.create(slug="getting-started", language="en", body_markdown="y")
    assert [str(r) for r in PublicPage.objects.all()] == [
        "getting-started [en]",
        "privacy [pl]",
    ]


@pytest.mark.django_db
def test_slug_language_is_unique():
    from django.db import transaction
    from django.db.utils import IntegrityError

    PublicPage.objects.create(slug="privacy", language="en", body_markdown="a")
    # transaction.atomic is the standard idiom: without it the IntegrityError
    # leaves the test's outer atomic block needing rollback, and any assertion
    # added after this raises TransactionManagementError.
    with pytest.raises(IntegrityError), transaction.atomic():
        PublicPage.objects.create(slug="privacy", language="en", body_markdown="b")


@pytest.mark.django_db
def test_new_institution_fields_default_blank_and_false():
    inst = Institution.load()
    assert inst.controller_name == ""
    assert inst.controller_address == ""
    assert inst.contact_email == ""
    assert inst.supervisory_authority == ""
    assert inst.demo_instance is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_public_pages_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'PublicPage'`

- [ ] **Step 3: Write minimal implementation**

Add to `institution/models.py` (module-level import at the top):

```python
from core.public_pages import normalize_lang
```

Add the five fields to `Institution`, next to the existing config fields:

```python
    controller_name = models.CharField(
        max_length=200, blank=True, verbose_name=_("Data controller name"),
        help_text=_("Shown on the public privacy notice. Falls back to the "
                    "institution name when blank."),
    )
    controller_address = models.TextField(
        blank=True, verbose_name=_("Data controller address"),
        help_text=_("Postal address. Omitted from the notice entirely when blank."),
    )
    contact_email = models.EmailField(
        blank=True, verbose_name=_("Contact address for data requests"),
    )
    supervisory_authority = models.CharField(
        max_length=200, blank=True, verbose_name=_("Supervisory authority"),
        help_text=_("The data-protection regulator for your country (in Poland, "
                    "UODO). A neutral phrase is used when blank."),
    )
    demo_instance = models.BooleanField(
        default=False, verbose_name=_("This is a demonstration site"),
        help_text=_("Adds a warning to the public pages telling visitors not to "
                    "enter real pupil data."),
    )
```

And the new model at the end of the file:

```python
class PublicPage(models.Model):
    """Per-(page, language) admin override of a shipped public page.

    Deleting a row IS the "revert to default" action -- there is no separate
    flag, so the two cannot diverge. `slug` carries no choices: Django
    serialises choices into migrations, and the PAGES titles are lazy strings
    with no business in a migration file. A row whose slug is no longer in
    PAGES is inert (invisible to the panel, unreachable by the resolver) and is
    cleaned up by hand here in the admin.
    """

    slug = models.CharField(max_length=32)
    language = models.CharField(max_length=5)
    body_markdown = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slug", "language"]
        constraints = [
            models.UniqueConstraint(
                fields=["slug", "language"], name="uniq_publicpage_slug_language"
            )
        ]

    def save(self, *args, **kwargs):
        # INVARIANT: always a bare code. Enforced here rather than only in the
        # settings panel, because the Django admin is a second write path and a
        # "pl-PL" row is one the normalised lookup can never match.
        self.language = normalize_lang(self.language)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.slug} [{self.language}]"
```

Register it in `institution/admin.py`:

```python
from institution.models import PublicPage


@admin.register(PublicPage)
class PublicPageAdmin(admin.ModelAdmin):
    list_display = ("slug", "language", "updated_at")
    list_filter = ("slug", "language")
```

- [ ] **Step 4: Generate and inspect the migration**

```bash
uv run python manage.py makemigrations institution
```

Read the generated file. It must contain exactly one `CreateModel` for `PublicPage` (with the `UniqueConstraint`) and five `AddField` operations. If it contains anything else, stop and investigate — an unrelated model change has been swept in.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_public_pages_model.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add institution/models.py institution/admin.py institution/migrations/ tests/test_public_pages_model.py
git commit -m "feat(public-pages): add PublicPage and the controller-identity fields"
```

---

### Task 5: Site-config bundle keys

**Files:**
- Modify: `core/services.py`
- Test: `tests/test_public_pages_config.py`

**Interfaces:**
- Consumes: the fields from Task 4.
- Produces: `get_site_config()` carrying `controller_name`, `controller_address`, `contact_email`, `supervisory_authority`, `demo_instance`, `notification_retention_days`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_public_pages_config.py
import pytest

from core.services import _DEFAULTS
from core.services import get_site_config
from institution.models import Institution

NEW_KEYS = {
    "controller_name", "controller_address", "contact_email",
    "supervisory_authority", "demo_instance", "notification_retention_days",
}


def test_defaults_carry_every_new_key_with_the_right_values():
    assert NEW_KEYS <= set(_DEFAULTS)
    assert _DEFAULTS["demo_instance"] is False
    assert _DEFAULTS["notification_retention_days"] == 90
    for key in ("controller_name", "controller_address", "contact_email",
                "supervisory_authority"):
        assert _DEFAULTS[key] == ""


@pytest.mark.django_db
def test_bundle_carries_every_new_key_with_an_institution_row():
    Institution.load()
    assert NEW_KEYS <= set(get_site_config())


@pytest.mark.django_db
def test_bundle_carries_every_new_key_with_NO_institution_row():
    # The public pages must render on a fresh install. _build() returns
    # dict(_DEFAULTS) here, so key parity between the two paths is load-bearing.
    Institution.objects.all().delete()
    from core.services import invalidate_site_config

    invalidate_site_config()
    assert NEW_KEYS <= set(get_site_config())


@pytest.mark.django_db
def test_retention_zero_survives_the_bundle():
    # The `inst.x or _DEFAULTS[x]` idiom every other line uses would rewrite
    # this to 90 -- inverting the meaning of "never purge".
    inst = Institution.load()
    inst.notification_retention_days = 0
    inst.save()
    assert get_site_config()["notification_retention_days"] == 0


@pytest.mark.django_db
def test_demo_instance_false_survives_the_bundle():
    inst = Institution.load()
    inst.demo_instance = False
    inst.save()
    assert get_site_config()["demo_instance"] is False


@pytest.mark.django_db
def test_demo_instance_true_reaches_the_bundle():
    inst = Institution.load()
    inst.demo_instance = True
    inst.save()
    assert get_site_config()["demo_instance"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_public_pages_config.py -v`
Expected: FAIL — `KeyError` / assertion errors on the missing keys

- [ ] **Step 3: Write minimal implementation**

In `core/services.py`, add to the `_DEFAULTS` dict:

```python
    "controller_name": "",
    "controller_address": "",
    "contact_email": "",
    "supervisory_authority": "",
    "notification_retention_days": 90,
    "demo_instance": False,
```

And to the literal dict returned by `_build()`:

```python
        "controller_name": inst.controller_name or _DEFAULTS["controller_name"],
        "controller_address": (
            inst.controller_address or _DEFAULTS["controller_address"]
        ),
        "contact_email": inst.contact_email or _DEFAULTS["contact_email"],
        "supervisory_authority": (
            inst.supervisory_authority or _DEFAULTS["supervisory_authority"]
        ),
        # BARE reads, following "onboarded" above -- NOT the `or _DEFAULTS[...]`
        # idiom. 0 means "never purge" and False is a real value; coalescing
        # would rewrite 0 -> 90 and make False unrepresentable.
        "notification_retention_days": inst.notification_retention_days,
        "demo_instance": inst.demo_instance,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_public_pages_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/services.py tests/test_public_pages_config.py
git commit -m "feat(public-pages): carry controller identity in the site-config bundle"
```

---

### Task 6: Shipped privacy notice (EN + PL)

**Files:**
- Create: `docs/public/privacy.md`, `docs/public/privacy.pl.md`

**Interfaces:**
- Consumes: `render_markdown` and `substitute_tokens` (Tasks 2–3) for the Task 7 guards.
- Produces: the two shipped privacy files. These must exist before Task 8, whose renderer reads them.

**Authoring rules that are enforced by tests in Task 7 — read before writing:**
1. `{libli:demo_notice}` and `{libli:controller_address}` must each be **a paragraph of their own at top level**, with **no heading immediately above them**, and their sections must read correctly when the paragraph is removed.
2. **No `{libli:…}` token inside a link target or any attribute.** `{libli:contact_email}` renders as plain text only — never `[write](mailto:{libli:contact_email})`.
3. Tokens sit in **case-neutral positions** in the Polish text (after a colon, or as their own clause), because Polish inflects.
4. Column-alignment syntax (`|:---:|`) has no effect — nh3 drops the `style` attribute.

- [ ] **Step 1: Write `docs/public/privacy.md`**

Write the full English notice with these ten sections, following the spec's §Content → Privacy notice. Required substance, in order:

1. `# Privacy notice`, an effective-date line, then **Who is responsible** — `{libli:controller_name}`, then `{libli:controller_address}` as its own paragraph, then a separate sentence giving `{libli:contact_email}` as plain text.
2. `{libli:demo_notice}` — its own paragraph, no heading above it.
3. **What we hold, and why** — account and identity (username, optional email address, display and real names, an external ID when your school uses single sign-on); the learning record; groups and classes; your own notes, tags and uploads; preferences; support reports. **State explicitly that every answer you submit to a question is kept with its timestamp, not only your latest one.**
4. **What libli does not collect** — no IP addresses in the application, no analytics, no advertising, no profiling or automated decision-making, nothing sold or shared for marketing, and no cookies set by libli beyond the functional ones listed below.
5. **Cookies and local storage** — the four-row table exactly as the spec gives it (`sessionid` two weeks *persistent, not a session cookie*; `csrftoken` about a year; `messages` short-lived; `libli_theme` one year), then the by-prefix paragraph naming `libli_`, `libli:` **and** `libli-`.
6. **Other services** — `{libli:embed_domains}`; that the browser contacts them only on pages where a teacher placed an embed **and those providers may set their own cookies and storage**; SSO; the mail provider; the results webhook when enabled; the web server's access logs, which **do** record IP addresses even though the application never stores them; and that adding an image by URL makes the **server** fetch it, carrying no user data.
7. **Who can see your information** — teachers see their own students; platform admins see everything; students see nothing about each other; notes and tags are private to their author.
8. **How long we keep it** — read notifications are removed `{libli:retention_phrase}` — the sentence must read correctly under **both** expansions ("removed after 90 days" and "removed only when you delete them"), which is why the token carries the whole predicate; the purge runs on a schedule the operator installs; unread notifications are never removed on age; learning records have no automatic expiry.
9. **Your rights** — access, rectification, erasure, restriction, portability, objection; then, **after a colon**, `{libli:supervisory_authority}`. Then plainly: there is no self-service export or delete today, requests go to the contact address and are handled by hand, and **deactivating an account is not erasure**.
10. **Children**, **Security** (phrased as a property of the production deployment the operator runs — HTTPS and secure cookies come from the production settings; Django password hashing and role-based access are unconditional), and **Changes to this notice**.

- [ ] **Step 2: Write `docs/public/privacy.pl.md`**

A full Polish translation of the same document, same section order, same tokens. Watch rule 3: in section 9 write the lead-in so `{libli:supervisory_authority}` follows a colon rather than a preposition that would govern case.

- [ ] **Step 3: Verify both files parse and render**

`tests/test_public_pages_content.py` does not exist yet -- it is authored in Task 7, which is where
the shipped-markdown guards land. Verify this task's own artifacts directly instead:

```bash
uv run python -c "
from django import setup; import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local'); setup()
from core.help import DOCS_ROOT
from core.public_pages import render_markdown, substitute_tokens
cfg = {'name': 'X', 'controller_name': '', 'controller_address': '',
       'contact_email': '', 'supervisory_authority': '',
       'notification_retention_days': 90, 'demo_instance': True}
for rel in ('public/privacy.md', 'public/privacy.pl.md'):
    html = substitute_tokens(render_markdown((DOCS_ROOT/rel).read_text(encoding='utf-8')), cfg)
    assert '{libli:' not in html, rel
    assert 'public-page__notice' in html, rel
    assert html.count('<h1>') == 1, rel
print('both privacy files render clean')
"
```
Expected: `both privacy files render clean`.

- [ ] **Step 4: Commit**

```bash
git add docs/public/privacy.md docs/public/privacy.pl.md
git commit -m "docs(public-pages): add the shipped privacy notice in EN and PL"
```

---

### Task 7: Shipped getting-started (EN + PL) and the shipped-markdown guards

**Files:**
- Create: `docs/public/getting-started.md`, `docs/public/getting-started.pl.md`
- Test: `tests/test_public_pages_content.py`

**Interfaces:**
- Consumes: the four shipped files (Tasks 6–7).
- Produces: guard tests over all four.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_public_pages_content.py
import re

import pytest

from core.help import DOCS_ROOT
from core.public_pages import PAGES
from core.public_pages import render_markdown
from core.public_pages import substitute_tokens
from tests.test_public_pages import cfg

SHIPPED = [
    "public/privacy.md", "public/privacy.pl.md",
    "public/getting-started.md", "public/getting-started.pl.md",
]


@pytest.mark.parametrize("rel", SHIPPED)
def test_shipped_file_exists_and_is_utf8(rel):
    assert (DOCS_ROOT / rel).read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("rel", SHIPPED)
def test_demo_notice_is_placed_where_the_block_regex_matches(rel):
    # Misplaced (indented, in a list, mid-sentence) the token silently renders as
    # literal text, swallowing the do-not-enter-real-pupil-data warning.
    source = (DOCS_ROOT / rel).read_text(encoding="utf-8")
    assert "{libli:demo_notice}" in source
    html = substitute_tokens(render_markdown(source), cfg(demo_instance=True))
    assert "public-page__notice" in html
    assert "{libli:demo_notice}" not in html


@pytest.mark.parametrize("rel", SHIPPED)
def test_no_block_token_has_a_heading_immediately_above_it(rel):
    # The block pass deletes the paragraph and nothing else, so a heading above
    # it would be orphaned on every non-demo deployment.
    lines = (DOCS_ROOT / rel).read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if "{libli:demo_notice}" in line or "{libli:controller_address}" in line:
            above = [x for x in lines[:i] if x.strip()]
            assert not (above and above[-1].lstrip().startswith("#")), (
                f"{rel}: heading immediately above {line.strip()}"
            )


@pytest.mark.parametrize("rel", SHIPPED)
def test_no_token_survives_inside_an_attribute(rel):
    source = (DOCS_ROOT / rel).read_text(encoding="utf-8")
    html = substitute_tokens(render_markdown(source), cfg(demo_instance=True))
    for tag in re.findall(r"<[^>]+>", html):
        assert "{libli:" not in tag, f"{rel}: token inside {tag}"


@pytest.mark.parametrize("rel", SHIPPED)
def test_no_unresolved_token_remains_in_either_configuration(rel):
    source = (DOCS_ROOT / rel).read_text(encoding="utf-8")
    for demo in (True, False):
        html = substitute_tokens(render_markdown(source), cfg(demo_instance=demo))
        assert "{libli:" not in html, f"{rel}: unresolved token (demo={demo})"


@pytest.mark.parametrize("rel", SHIPPED)
def test_no_empty_paragraph_when_blocks_are_off(rel):
    source = (DOCS_ROOT / rel).read_text(encoding="utf-8")
    html = substitute_tokens(render_markdown(source), cfg(demo_instance=False))
    assert "<p></p>" not in html


@pytest.mark.parametrize("rel", SHIPPED)
def test_exactly_one_h1(rel):
    source = (DOCS_ROOT / rel).read_text(encoding="utf-8")
    html = substitute_tokens(render_markdown(source), cfg())
    assert html.count("<h1>") == 1


def test_every_registered_page_has_both_language_files():
    for page in PAGES.values():
        assert (DOCS_ROOT / page.path).exists()
        pl = page.path.removesuffix(".md") + ".pl.md"
        assert (DOCS_ROOT / pl).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_public_pages_content.py -v`
Expected: FAIL — the two getting-started files do not exist.

- [ ] **Step 3: Write `docs/public/getting-started.md`**

`# Getting started`, one sentence on what libli is, then two clearly-headed parts, following the spec's §Content → Getting started:

- **Evaluating libli?** — courses and lessons, roughly thirty element types including interactive and mathematical ones, quizzes with automatic marking, teacher analytics, English and Polish. Then `{libli:demo_notice}` **as its own top-level paragraph** (so the demo claim is gated and a school's own deployment never tells its parents the site is a demo). Then how to reach a human — `{libli:contact_email}` as plain text — and a plain markdown link to `/privacy/`, because a school's DPO asks for it first.
- **Trying to log in?** — accounts are created by your school rather than self-service; forgotten passwords go through the reset link on the login page; invitations expire after 14 days, so ask for a fresh one; anything broken goes to your teacher or the contact address.

**Note:** this file carries `{libli:demo_notice}` (required by the guard over all four files) but no `{libli:controller_address}` — an address does not belong on a getting-started page. The heading-placement guard simply finds no `controller_address` match here and passes.

- [ ] **Step 4: Write `docs/public/getting-started.pl.md`**

Full Polish translation, same structure, same tokens.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_public_pages_content.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add docs/public/getting-started.md docs/public/getting-started.pl.md tests/test_public_pages_content.py
git commit -m "docs(public-pages): add getting-started in EN and PL with shipped-markdown guards"
```

---

### Task 8: `render_public_page`

**Files:**
- Modify: `core/public_pages.py`
- Test: `tests/test_public_pages_render.py`

**Interfaces:**
- Consumes: `PAGES`, `normalize_lang`, `render_markdown`, `substitute_tokens` (Tasks 1–3); `PublicPage` (Task 4); the four shipped files (Tasks 6–7).
- Produces: `render_public_page(slug: str, lang: str, cfg: dict) -> tuple[SafeString, str]` returning `(html, resolved_lang)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_public_pages_render.py
import pytest

from core.public_pages import render_public_page
from institution.models import PublicPage
from tests.test_public_pages import cfg


@pytest.mark.django_db
def test_repo_template_is_served_when_no_override():
    html, lang = render_public_page("privacy", "en", cfg())
    assert lang == "en"
    assert "<h1>" in html


@pytest.mark.django_db
def test_override_beats_the_repo_template():
    PublicPage.objects.create(slug="privacy", language="en", body_markdown="# Mine\n")
    html, _lang = render_public_page("privacy", "en", cfg())
    assert "<h1>Mine</h1>" in html


@pytest.mark.django_db
def test_blank_override_row_is_treated_as_no_override():
    # Assert POSITIVELY that the repo template was served. The mutant here is
    # `if row:` instead of `if row and row.body_markdown.strip():`, under which
    # source == "   " and markdown renders "" -- so a mere `"<h1>Mine</h1>" not
    # in html` is green on BOTH builds. Requiring real template content is what
    # makes it red.
    PublicPage.objects.create(slug="privacy", language="en", body_markdown="   ")
    html, _lang = render_public_page("privacy", "en", cfg())
    assert "<h1>" in html
    assert "Privacy" in html  # the shipped notice's own heading text


@pytest.mark.django_db
def test_deleting_the_override_falls_back_to_the_template():
    row = PublicPage.objects.create(
        slug="privacy", language="en", body_markdown="# Mine\n"
    )
    row.delete()
    html, _lang = render_public_page("privacy", "en", cfg())
    assert "<h1>Mine</h1>" not in html


@pytest.mark.django_db
def test_regional_request_hits_the_bare_code_override_row():
    PublicPage.objects.create(slug="privacy", language="pl", body_markdown="# Moje\n")
    html, lang = render_public_page("privacy", "pl-PL", cfg())
    assert "<h1>Moje</h1>" in html
    assert lang == "pl"


@pytest.mark.django_db
def test_an_en_only_override_does_not_leak_into_pl():
    PublicPage.objects.create(slug="privacy", language="en", body_markdown="# EnOnly\n")
    html, _lang = render_public_page("privacy", "pl", cfg())
    assert "EnOnly" not in html


@pytest.mark.django_db
def test_resolved_lang_is_en_when_the_base_path_comes_back(monkeypatch):
    # localized_doc_path returns a PATH, not a language, and silently returns the
    # English base when the sibling is absent. resolved_lang is derived from
    # WHICH path came back -- pinned here because the derivation is not obvious.
    import core.public_pages as pp

    monkeypatch.setattr(pp, "localized_doc_path", lambda base, code: base)
    _html, lang = render_public_page("privacy", "pl", cfg())
    assert lang == "en"


@pytest.mark.django_db
def test_resolved_lang_is_the_code_when_a_sibling_comes_back(monkeypatch):
    # The other half of the same derivation: mutant "return code unconditionally"
    # passes the test above only if this one also exists.
    import core.public_pages as pp

    monkeypatch.setattr(
        pp, "localized_doc_path",
        lambda base, code: base.removesuffix(".md") + f".{code}.md",
    )
    _html, lang = render_public_page("privacy", "pl", cfg())
    assert lang == "pl"


@pytest.mark.django_db
def test_pl_request_serves_the_pl_sibling():
    # End-to-end against the real shipped files (Task 6 creates privacy.pl.md).
    html, lang = render_public_page("privacy", "pl", cfg())
    assert lang == "pl"
    assert html != ""


@pytest.mark.django_db
def test_missing_file_renders_an_empty_body_not_a_500(monkeypatch):
    import core.public_pages as pp

    monkeypatch.setitem(
        pp.PAGES, "privacy",
        pp.Page("privacy", "public/does-not-exist.md", "T", "D"),
    )
    html, lang = render_public_page("privacy", "en", cfg())
    assert html == ""
    assert lang == "en"


@pytest.mark.django_db
def test_repo_file_branch_is_sanitised_too(tmp_path, monkeypatch):
    """The spec's mutant is "sanitise only the override branch". Task 2's test
    calls render_markdown directly and Task 9's uses an override row, so
    NEITHER exercises the repo-file branch -- this one does."""
    import core.public_pages as pp

    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "privacy.md").write_text(
        "# T\n\n<script>alert(1)</script>\n", encoding="utf-8"
    )
    monkeypatch.setattr(pp, "DOCS_ROOT", tmp_path)
    html, _lang = render_public_page("privacy", "en", cfg())
    assert "<script" not in html
    assert "alert(1)" not in html


def test_the_file_read_pins_utf8():
    """Platform-independent guard. On Linux CI the preferred encoding is already
    UTF-8, so dropping encoding="utf-8" still decodes the Polish file and a
    behavioural test stays green -- the mutant would only die on a cp1250 dev
    machine. Assert on the source instead; this is the authoritative check."""
    import inspect

    from core.public_pages import render_public_page as fn

    assert 'encoding="utf-8"' in inspect.getsource(fn)


@pytest.mark.django_db
def test_output_is_marked_safe():
    from django.utils.safestring import SafeString

    html, _lang = render_public_page("privacy", "en", cfg())
    assert isinstance(html, SafeString)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_public_pages_render.py -v`
Expected: FAIL — `ImportError: cannot import name 'render_public_page'`

- [ ] **Step 3: Write minimal implementation**

Add to `core/public_pages.py`:

```python
import logging

from django.utils.safestring import mark_safe

from core.help import DOCS_ROOT
from core.help import localized_doc_path

logger = logging.getLogger(__name__)


def render_public_page(slug, lang, cfg):
    """Return (safe html, resolved_lang) for one public page.

    cfg is the site-config bundle, passed in by the view so this stays
    injectable from unit tests and the tokens have one source of truth.
    """
    # Imported INSIDE the function on purpose: institution.models imports
    # normalize_lang from this module, so a module-level import here is a cycle.
    # Mirrors core/services.py:71, which does the same for Institution.
    from institution.models import PublicPage

    page = PAGES[slug]  # KeyError on an unregistered slug is a programming error
    code = normalize_lang(lang)

    row = PublicPage.objects.filter(slug=slug, language=code).first()
    if row and row.body_markdown.strip():
        source, resolved = row.body_markdown, code
    else:
        rel = localized_doc_path(page.path, code)
        resolved = code if rel != page.path else "en"
        try:
            # encoding is MANDATORY: without it the platform default applies
            # (cp1250 on Windows dev machines) and a Polish file raises
            # UnicodeDecodeError -- a ValueError, which would escape the guard
            # below and 500 the marketing surface.
            source = (DOCS_ROOT / rel).read_text(encoding="utf-8")
        except OSError:
            logger.exception("public page %s (%s) could not be read", slug, rel)
            return mark_safe(""), code  # noqa: S308 - empty string

    # Safe by construction: nh3-sanitised, then every substituted value is
    # html.escape'd. (The suppression itself is the trailing noqa below --
    # ruff only honours # noqa on the line reporting the violation.)
    html = substitute_tokens(render_markdown(source), cfg)
    return mark_safe(html), resolved  # noqa: S308
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_public_pages_render.py -v`
Expected: PASS. The shipped markdown exists by now (Tasks 6–7), so this suite is green as it stands — no deferred failures.

- [ ] **Step 5: Commit**

```bash
git add core/public_pages.py tests/test_public_pages_render.py
git commit -m "feat(public-pages): add render_public_page with the override chain"
```

---

### Task 9: Views, URLs, page template and CSS

**Files:**
- Create: `core/views_public.py`, `templates/core/public_page.html`
- Modify: `core/urls.py`, `core/static/core/css/app.css`
- Test: `tests/test_public_pages_views.py`

**Interfaces:**
- Consumes: `render_public_page` (Task 8), `get_site_config` (Task 5).
- Produces: URL names `core:privacy` and `core:getting_started`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_public_pages_views.py
import pytest
from django.urls import reverse

from institution.models import Institution
from institution.models import PublicPage

URLS = ["core:privacy", "core:getting_started"]


@pytest.mark.django_db
@pytest.mark.parametrize("name", URLS)
def test_anonymous_gets_200(client, name):
    assert client.get(reverse(name)).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("name", URLS)
def test_anonymous_gets_200_in_polish(client, name):
    session = client.session
    session["_language"] = "pl"
    session.save()
    assert client.get(reverse(name)).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("name", URLS)
def test_renders_with_no_institution_row(client, name):
    from core.services import invalidate_site_config

    Institution.objects.all().delete()
    invalidate_site_config()
    assert client.get(reverse(name)).status_code == 200


@pytest.mark.django_db
def test_a_table_reaches_the_response_as_a_real_element(client):
    # RESPONSE-level, not sanitiser-level: every sanitiser test stays green
    # through a double-escaping bug. This one does not.
    PublicPage.objects.create(
        slug="privacy", language="en",
        body_markdown="# T\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n",
    )
    body = client.get(reverse("core:privacy")).content.decode()
    assert "<table>" in body
    assert "&lt;table&gt;" not in body


@pytest.mark.django_db
def test_script_in_an_override_does_not_reach_the_response(client):
    PublicPage.objects.create(
        slug="privacy", language="en",
        body_markdown="# T\n\n<script>alert(1)</script>\n",
    )
    body = client.get(reverse("core:privacy")).content.decode()
    assert "<script>alert(1)</script>" not in body


@pytest.mark.django_db
def test_controller_name_from_settings_reaches_the_page(client):
    inst = Institution.load()
    inst.controller_name = "Greenfield School Trust"
    inst.save()
    body = client.get(reverse("core:privacy")).content.decode()
    assert "Greenfield School Trust" in body


@pytest.mark.django_db
@pytest.mark.parametrize("slug,name", [("privacy", "core:privacy"),
                                       ("getting-started", "core:getting_started")])
def test_page_emits_its_real_description_title_and_one_h1(client, slug, name):
    from core.public_pages import PAGES

    body = client.get(reverse(name)).content.decode()
    # Non-empty, and the RIGHT description: `'name="description"' in body`
    # passes on content="" and on the wrong context key.
    assert str(PAGES[slug].description)[:40] in body
    assert str(PAGES[slug].title) in body  # <title> carries the registry title
    assert body.count("<h1>") == 1  # base.html has none; the markdown owns it


@pytest.mark.django_db
def test_body_is_marked_with_the_resolved_language(client):
    # Assert on the ARTICLE: base.html:4 already emits <html lang="pl">, so a
    # bare `'lang="pl"' in body` is green even with the attribute deleted.
    session = client.session
    session["_language"] = "pl"
    session.save()
    body = client.get(reverse("core:privacy")).content.decode()
    assert '<article class="public-page" lang="pl">' in body


@pytest.mark.django_db
def test_an_english_fallback_body_is_marked_en_inside_a_pl_page(client, monkeypatch):
    # The real fallback case: English prose served inside <html lang="pl">.
    import core.public_pages as pp

    monkeypatch.setattr(pp, "localized_doc_path", lambda base, code: base)
    session = client.session
    session["_language"] = "pl"
    session.save()
    body = client.get(reverse("core:privacy")).content.decode()
    assert '<article class="public-page" lang="en">' in body
    assert '<html lang="pl"' in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_public_pages_views.py -v`
Expected: FAIL — `NoReverseMatch: 'privacy' is not a valid view function or pattern name`

- [ ] **Step 3: Write the views**

```python
# core/views_public.py
"""Anonymous public content pages. The first non-login_required content
surface in the codebase -- keep it that way: no auth, no user data."""

from django.shortcuts import render
from django.utils import translation

from core.public_pages import PAGES
from core.public_pages import render_public_page
from core.services import get_site_config


def _public_page(request, slug):
    page = PAGES[slug]
    html, resolved_lang = render_public_page(
        slug, translation.get_language(), get_site_config()
    )
    return render(
        request,
        "core/public_page.html",
        {
            "body": html,
            "resolved_lang": resolved_lang,
            "title": page.title,
            "description": page.description,
        },
    )


def privacy(request):
    return _public_page(request, "privacy")


def getting_started(request):
    return _public_page(request, "getting-started")
```

- [ ] **Step 4: Wire the URLs**

In `core/urls.py`, add the import and two routes — **no `login_required`**:

```python
from core import views_public

    path("privacy/", views_public.privacy, name="privacy"),
    path("getting-started/", views_public.getting_started, name="getting_started"),
```

- [ ] **Step 5: Write the page template**

```django
{# templates/core/public_page.html #}
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{{ title }} · {{ site.name|default:"libli" }}{% endblock %}
{% block extra_head %}<meta name="description" content="{{ description }}">{% endblock %}
{% block content %}
{# The markdown owns the <h1>; the registry title fills <title> and the meta
   description only, so a page never renders two <h1> elements. resolved_lang is
   emitted unconditionally -- LANGUAGE_CODE can be regional while resolved_lang
   is always bare, so comparing them would mark every page as a fallback. #}
<article class="public-page" lang="{{ resolved_lang }}">{{ body }}</article>
{% endblock %}
{% block footer %}{% include "core/_public_footer.html" %}{% endblock %}
```

- [ ] **Step 6: Add the CSS**

Append to `core/static/core/css/app.css`, composing from existing tokens (no new tokens):

```css
/* Public pages (privacy, getting-started). Prose column matching the 46rem
   content cap used elsewhere; no new design tokens. */
.public-page {
  max-width: 46rem; margin: var(--space-8) auto; padding: 0 var(--space-5);
  color: var(--text-primary);
}
.public-page h1 { margin-bottom: var(--space-2); }
/* tokens.css defines 1-6, 8, 10 only: var(--space-7) is UNDEFINED and would
   make the whole declaration invalid, silently dropping the margin. */
.public-page h2 { margin-top: var(--space-8); }
.public-page table {
  width: 100%; border-collapse: collapse; margin: var(--space-4) 0;
}
.public-page th, .public-page td {
  border: 1px solid var(--border-subtle); padding: var(--space-2);
  text-align: left; vertical-align: top;
}
.public-page__notice {
  border: 1px solid var(--border-subtle); border-left-width: 4px;
  background: var(--surface-sunken); padding: var(--space-4);
  border-radius: var(--radius-sm);
}
```

- [ ] **Step 7: Run tests**

No placeholder file is needed: `base.html` has no `{% block footer %}` until Task 10, and Django never executes a block a child defines but the parent does not declare — so the `{% include %}` inside it cannot raise `TemplateDoesNotExist` here.

```bash
uv run python -m pytest tests/test_public_pages_views.py -v
```
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add core/views_public.py core/urls.py templates/core/public_page.html core/static/core/css/app.css tests/test_public_pages_views.py
git commit -m "feat(public-pages): serve /privacy/ and /getting-started/ anonymously"
```

---

### Task 10: The footer block, landing, entrance, and the auth height fix

**Files:**
- Modify: `templates/base.html`, `templates/core/landing.html`, `templates/allauth/layouts/entrance.html`, `core/static/core/css/app.css`, `core/static/core/css/auth.css`
- Create: `templates/core/_public_footer.html` (first created here; Task 9's `{% include %}` is never executed — see Task 9 Step 7)
- Test: `tests/test_public_pages_footer.py`

**Interfaces:**
- Consumes: the URL names from Task 9.
- Produces: a `footer` block in `base.html`, empty for every template that does not fill it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_public_pages_footer.py
import pytest
from django.urls import reverse

from tests.factories import make_verified_user


@pytest.mark.django_db
def test_landing_footer_links_both_pages_and_drops_the_en_pl_span(client):
    body = client.get(reverse("landing")).content.decode()
    assert reverse("core:privacy") in body
    assert reverse("core:getting_started") in body
    # The span duplicated the header switcher, which is already live for
    # anonymous visitors. It must be gone, not merely hidden.
    assert "EN / PL" not in body


@pytest.mark.django_db
def test_entrance_pages_carry_both_links(client):
    body = client.get(reverse("account_login")).content.decode()
    assert reverse("core:privacy") in body
    assert reverse("core:getting_started") in body


@pytest.mark.django_db
def test_authenticated_home_renders_no_footer(client):
    user = make_verified_user()
    client.force_login(user)
    body = client.get(reverse("home")).content.decode()
    assert reverse("core:privacy") not in body


@pytest.mark.django_db
def test_public_pages_carry_the_footer(client):
    body = client.get(reverse("core:privacy")).content.decode()
    assert reverse("core:getting_started") in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_public_pages_footer.py -v`
Expected: FAIL — `EN / PL` still present, entrance has no links

- [ ] **Step 3: Add the footer block to `base.html`**

Immediately after `</main>` and **before** the first `<script>` tag — the only position that puts the footer in normal document flow ahead of the deferred scripts and the support dialog:

```django
  </main>
  {% block footer %}{% endblock %}
  <script src="{% static 'core/js/ui.js' %}" defer></script>
```

- [ ] **Step 4: Write the shared footer partial**

```django
{# templates/core/_public_footer.html #}
{% load i18n %}
<footer class="public-footer">
  <a href="{% url 'core:privacy' %}">{% trans "Privacy" %}</a>
  {# Labelled "Help" but pointing at /getting-started/: /help/ is the staff area
     (core/urls.py:17, login_required). Deliberate -- see the spec's Accepted
     decisions. Do not "fix" by renumbering the staff help URLs. #}
  <a href="{% url 'core:getting_started' %}">{% trans "Help" %}</a>
</footer>
```

- [ ] **Step 5: Update the landing footer**

In `templates/core/landing.html`, replace the three placeholder spans with two real links and **delete the `EN / PL` line entirely**:

```django
<footer class="landing-footer">
  <span class="brand">libli<span class="brand__dot">.</span></span>
  <span>· {{ site.name|default:"libli" }}</span>
  <span class="app-header__spacer"></span>
  <a href="{% url 'core:privacy' %}">{% trans "Privacy" %}</a>
  <a href="{% url 'core:getting_started' %}">{% trans "Help" %}</a>
</footer>
```

- [ ] **Step 6: Fill the footer block on the entrance layout**

Append to `templates/allauth/layouts/entrance.html`:

```django
{% block footer %}{% include "core/_public_footer.html" %}{% endblock %}
```

- [ ] **Step 7: Add the CSS, including the auth height fix**

Append to `app.css`:

```css
.public-footer {
  display: flex; gap: var(--space-4); justify-content: center;
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--border-subtle);
  color: var(--text-secondary); font-size: .875rem;
}
```

In `auth.css`, move the viewport floor from `.auth-main` to `body.auth`. Without the floor on the new flex container, `flex: 1` has no free space to absorb: the footer would not reach the bottom fold **and** the login card would lose its vertical centring.

```css
body.auth { min-height: 100vh; display: flex; flex-direction: column; }
/* .auth-main: DROP min-height, ADD flex: 1, KEEP justify-content: center */
.auth-main { flex: 1; }
```

- [ ] **Step 8: Run tests**

Run: `uv run python -m pytest tests/test_public_pages_footer.py -v`
Expected: PASS

- [ ] **Step 9: Verify the entrance layout by screenshot**

No HTML assertion can see this — the links exist in the markup either way. Load `/accounts/login/` and confirm **both**: the footer sits at the bottom fold, **and** the login card is still vertically centred. Checking only the first would let the centring regression through.

- [ ] **Step 10: Commit**

```bash
git add templates/base.html templates/core/landing.html templates/core/_public_footer.html templates/allauth/layouts/entrance.html core/static/core/css/app.css core/static/core/css/auth.css tests/test_public_pages_footer.py
git commit -m "feat(public-pages): link the pages from the landing and entrance footers"
```

---

### Task 11: The settings tab

**Files:**
- Modify: `institution/forms.py`, `institution/views_manage.py`, `institution/urls.py`, `templates/institution/manage/settings.html`, `templates/institution/manage/_tabs.html`
- Create: `templates/institution/manage/_public_pages_tab.html`
- Test: `tests/test_public_pages_settings.py`

**Interfaces:**
- Consumes: `PublicPage`, the five `Institution` fields (Task 4); `PAGES`, `normalize_lang` (Task 1).
- Produces: URL names `institution:settings_public_pages`, `institution:settings_page_overrides`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_public_pages_settings.py
import pytest
from django.urls import reverse
from django.urls import reverse_lazy

from institution.models import Institution
from institution.models import PublicPage
from tests.factories import make_verified_user


PANEL = reverse_lazy("institution:settings") + "?tab=public-pages"


def _admin():
    from django.contrib.auth.models import Permission

    user = make_verified_user()
    user.user_permissions.add(
        Permission.objects.get(codename="change_institution")
    )
    return user


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name", ["institution:settings_public_pages", "institution:settings_page_overrides"]
)
def test_requires_the_permission(client, name):
    client.force_login(make_verified_user())
    assert client.post(reverse(name), {}).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name", ["institution:settings_public_pages", "institution:settings_page_overrides"]
)
def test_get_redirects_rather_than_rendering(client, name):
    client.force_login(_admin())
    assert client.get(reverse(name)).status_code == 302


@pytest.mark.django_db
def test_panel_renders_one_textarea_per_page_per_language(client):
    client.force_login(_admin())
    body = client.get(PANEL).content.decode()
    for slug in ("privacy", "getting-started"):
        for lang in ("en", "pl"):
            assert f'name="override-{slug}-{lang}"' in body
    # EXACT count: a presence check does not kill "iterate settings.LANGUAGES",
    # which is a superset and would render extra textareas while staying green.
    assert body.count('name="override-') == 4


@pytest.mark.django_db
def test_regional_enabled_language_is_normalised_and_deduped(client):
    inst = Institution.load()
    inst.enabled_languages = ["pl", "pl-PL"]
    inst.save()
    client.force_login(_admin())
    body = client.get(PANEL).content.decode()
    assert body.count('name="override-privacy-pl"') == 1
    assert 'name="override-privacy-pl-PL"' not in body


@pytest.mark.django_db
def test_saving_writes_a_row_and_blanking_deletes_it(client):
    client.force_login(_admin())
    url = reverse("institution:settings_page_overrides")
    client.post(url, {"override-privacy-en": "# Mine\n"})
    assert PublicPage.objects.filter(slug="privacy", language="en").exists()
    client.post(url, {"override-privacy-en": "   "})
    assert not PublicPage.objects.filter(slug="privacy", language="en").exists()


@pytest.mark.django_db
def test_override_save_emits_a_success_message(client):
    # _action owns messages.success and this view cannot reuse it, so without an
    # explicit call the one action publishing live legal text confirms nothing.
    from django.contrib.messages import get_messages

    client.force_login(_admin())
    response = client.post(
        reverse("institution:settings_page_overrides"),
        {"override-privacy-en": "# Mine\n"},
    )
    assert [str(m) for m in get_messages(response.wsgi_request)]


@pytest.mark.django_db
def test_hyphenated_slug_is_not_split_on_the_hyphen(client):
    client.force_login(_admin())
    client.post(
        reverse("institution:settings_page_overrides"),
        {"override-getting-started-en": "# G\n"},
    )
    assert PublicPage.objects.filter(slug="getting-started", language="en").exists()
    assert not PublicPage.objects.filter(slug="getting").exists()


@pytest.mark.django_db
def test_a_stale_language_row_is_listed_and_deletable(client):
    PublicPage.objects.create(slug="privacy", language="de", body_markdown="# D\n")
    inst = Institution.load()
    inst.enabled_languages = ["en", "pl"]
    inst.save()
    client.force_login(_admin())
    body = client.get(PANEL).content.decode()
    assert 'name="override-privacy-de"' in body
    client.post(
        reverse("institution:settings_page_overrides"), {"override-privacy-de": ""}
    )
    assert not PublicPage.objects.filter(slug="privacy", language="de").exists()


@pytest.mark.django_db
def test_a_row_with_an_unregistered_slug_survives_a_save(client):
    # The union is qualified to slugs still in PAGES. Without that, the
    # delete-when-blank rule would silently destroy a row the spec calls inert.
    PublicPage.objects.create(slug="retired", language="en", body_markdown="# R\n")
    client.force_login(_admin())
    client.post(reverse("institution:settings_page_overrides"), {})
    assert PublicPage.objects.filter(slug="retired").exists()


@pytest.mark.django_db
def test_partial_override_warning(client):
    PublicPage.objects.create(slug="privacy", language="en", body_markdown="# Mine\n")
    client.force_login(_admin())
    body = client.get(PANEL).content.decode()
    assert "some but not all" in body


@pytest.mark.django_db
def test_missing_demo_notice_warning(client):
    inst = Institution.load()
    inst.demo_instance = True
    inst.save()
    PublicPage.objects.create(
        slug="privacy", language="en", body_markdown="# No token here\n"
    )
    client.force_login(_admin())
    body = client.get(PANEL).content.decode()
    assert "demonstration warning" in body


@pytest.mark.django_db
def test_saving_the_identity_form_updates_the_page(client):
    client.force_login(_admin())
    client.post(
        reverse("institution:settings_public_pages"),
        {"controller_name": "Trust X", "controller_address": "",
         "contact_email": "", "supervisory_authority": "", },
    )
    assert Institution.load().controller_name == "Trust X"


@pytest.mark.django_db
def test_invalid_identity_form_rerenders_without_a_type_error(client):
    # _action splats **{ctx_key: form}; "public-pages" is not a valid identifier.
    client.force_login(_admin())
    resp = client.post(
        reverse("institution:settings_public_pages"), {"contact_email": "not-an-email"}
    )
    assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_public_pages_settings.py -v`
Expected: FAIL — `NoReverseMatch`

- [ ] **Step 3: Add the form**

```python
# institution/forms.py
class PublicPagesForm(forms.ModelForm):
    """Controller identity for the public privacy notice."""

    class Meta:
        model = Institution
        fields = [
            "controller_name", "controller_address", "contact_email",
            "supervisory_authority", "demo_instance",
        ]
```

- [ ] **Step 4: Add the views**

In `institution/views_manage.py`: add `from institution.forms import PublicPagesForm` alongside the existing form imports; add `"public-pages"` to `TABS`; add the two new kwargs to `_settings_context`'s signature (`public_pages=None, page_overrides=None`) and into the context dict it builds; then add the `page_overrides` builder plus both views:

```python
def _page_overrides():
    """One dict per registered slug, in PAGES order. Built on the DISPLAY path,
    because the settings view renders every panel on GET. Takes no argument:
    everything comes from get_site_config() and PublicPage.objects.

    Languages come from get_site_config() (the COALESCED bundle), not from inst:
    _build() coalesces an empty stored list to the default, so reading inst
    directly would render zero language rows on a deployment whose stored list
    is empty while the public pages still resolved ["en", "pl"].
    """
    from core.public_pages import PAGES
    from core.public_pages import normalize_lang
    from core.services import get_site_config
    from institution.models import PublicPage

    enabled = []
    for code in get_site_config()["enabled_languages"]:
        code = normalize_lang(code)
        if code not in enabled:
            enabled.append(code)

    rows_by_key = {
        (r.slug, r.language): r for r in PublicPage.objects.all()
    }
    demo = get_site_config()["demo_instance"]
    out = []
    for slug, page in PAGES.items():
        stale = sorted(
            lang for (s, lang) in rows_by_key if s == slug and lang not in enabled
        )
        rows = []
        for lang in enabled + stale:
            row = rows_by_key.get((slug, lang))
            value = row.body_markdown if row else ""
            rows.append({
                "language": lang,
                "value": value,
                "enabled": lang in enabled,
                # Per-ROW, not per-page: with en and pl overrides where only one
                # carries the token, a page-level flag cannot say which language
                # lost the warning.
                "missing_demo_notice": bool(
                    demo and value.strip() and "{libli:demo_notice}" not in value
                ),
            })
        filled = [r for r in rows if r["enabled"] and r["value"].strip()]
        out.append({
            "slug": slug,
            "title": page.title,
            "rows": rows,
            "partial": 0 < len(filled) < len(enabled),
            "any_missing_demo_notice": any(r["missing_demo_notice"] for r in rows),
        })
    return out


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_public_pages(request):
    # ctx_key "public_pages" MUST differ from the tab slug "public-pages":
    # _action splats **{ctx_key: form}, and "public-pages" is not a valid Python
    # identifier. This is the first tab where the two diverge.
    return _action(
        request, PublicPagesForm, "public_pages", "public-pages",
        _("Public page settings saved."),
    )


@login_required
@permission_required("institution.change_institution", raise_exception=True)
def settings_page_overrides(request):
    from core.public_pages import PAGES
    from institution.models import PublicPage

    if request.method == "GET":
        return redirect(_index_url("public-pages"))

    # The iteration set is the SAME union the panel builds -- and it is
    # qualified to slugs still in PAGES. Without that qualification, a row for a
    # retired slug (for which the panel rendered no textarea) would read as ""
    # and the delete-when-blank rule would silently destroy live legal text.
    for page in _page_overrides():
        for row in page["rows"]:
            key = f"override-{page['slug']}-{row['language']}"
            # Never parse submitted key names: "getting-started" contains
            # hyphens, so override-getting-started-pl cannot be split safely.
            value = request.POST.get(key, "")
            if value.strip():
                obj, _created = PublicPage.objects.get_or_create(
                    slug=page["slug"], language=row["language"]
                )
                obj.body_markdown = value
                obj.save()
            else:
                PublicPage.objects.filter(
                    slug=page["slug"], language=row["language"]
                ).delete()
    # _action owns messages.success, and this view cannot reuse it -- so it must
    # emit its own, or the one action that publishes live legal text is the only
    # panel that confirms nothing.
    messages.success(request, _("Public page content saved."))
    return redirect(_index_url("public-pages"))
```

In `_settings_context`, always build the overrides:

```python
        "page_overrides": (
            page_overrides if page_overrides is not None else _page_overrides()
        ),
        "public_pages": public_pages or PublicPagesForm(instance=inst),
```

- [ ] **Step 5: Wire the URLs**

```python
    path(
        "manage/settings/public-pages/",
        views_manage.settings_public_pages,
        name="settings_public_pages",
    ),
    path(
        "manage/settings/public-pages/content/",
        views_manage.settings_page_overrides,
        name="settings_page_overrides",
    ),
```

- [ ] **Step 6: Add the panel and the tab link**

Create `templates/institution/manage/_public_pages_tab.html` — **two sibling forms**, because HTML forbids nesting:

```django
{% load i18n %}
<form class="settings__form" method="post" action="{% url 'institution:settings_public_pages' %}">
  {% csrf_token %}
  <div class="settings__section">
    <h2 class="settings__section-title">{% trans "Who runs this site" %}</h2>
    {% for field in public_pages %}
      <div class="settings__field">
        <label class="settings__label" for="{{ field.id_for_label }}">{{ field.label }}</label>
        {{ field }}
        {% if field.help_text %}<p class="settings__help">{{ field.help_text }}</p>{% endif %}
        {{ field.errors }}
      </div>
    {% endfor %}
  </div>
  <div class="settings__actions"><button class="btn" type="submit">{% trans "Save" %}</button></div>
</form>

<form class="settings__form" method="post" action="{% url 'institution:settings_page_overrides' %}">
  {% csrf_token %}
  {% for page in page_overrides %}
    <div class="settings__section">
      <h2 class="settings__section-title">{{ page.title }}</h2>
      {% if page.partial %}
        <p class="alert alert--warning">{% trans "This page is overridden in some but not all of your languages. Visitors will see different text depending on their language." %}</p>
      {% endif %}
      {% if page.any_missing_demo_notice %}
        <p class="alert alert--warning">{% trans "This is a demonstration site, but one of your versions below does not include the {libli:demo_notice} token, so it will not show the demonstration warning." %}</p>
      {% endif %}
      {% for row in page.rows %}
        <div class="settings__field">
          <label class="settings__label" for="override-{{ page.slug }}-{{ row.language }}">
            {{ row.language|upper }}{% if not row.enabled %} — {% trans "no longer enabled" %}{% endif %}
          </label>
          {# No .settings__input rule exists; styling comes from app.css:150's bare
             `textarea` selector. The class is carried for consistency with the SSO
             panel, which uses it the same way. #}
          <textarea class="settings__input" rows="8"
                    id="override-{{ page.slug }}-{{ row.language }}"
                    name="override-{{ page.slug }}-{{ row.language }}">{{ row.value }}</textarea>
        </div>
      {% endfor %}
    </div>
  {% endfor %}
  <p class="settings__help">{% trans "Leave a box empty to use the text that ships with libli. Saving replaces the published notice immediately and keeps no history — keep your own copy." %}</p>
  <div class="settings__actions"><button class="btn" type="submit">{% trans "Save" %}</button></div>
</form>
```

In `templates/institution/manage/settings.html`, after the `support` panel:

```django
  <div data-tab="public-pages" {% if active_tab != "public-pages" %}hidden{% endif %}>
    {% include "institution/manage/_public_pages_tab.html" %}
  </div>
```

In `templates/institution/manage/_tabs.html`, after the `support` link — this label is the string Task 13 translates:

```django
  <a class="settings__tab{% if active_tab == 'public-pages' %} is-on{% endif %}"
     href="{% url 'institution:settings' %}?tab=public-pages">{% trans "Public pages" %}</a>
```

- [ ] **Step 7: Run tests**

Run: `uv run python -m pytest tests/test_public_pages_settings.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add institution/ templates/institution/ tests/test_public_pages_settings.py
git commit -m "feat(public-pages): add the public-pages settings tab"
```

---

### Task 12: The claim-guard tests

**Files:**
- Test: `tests/test_public_pages_guards.py`

**Interfaces:**
- Consumes: everything above.
- Produces: tests only. These exist so that changing a setting fails CI rather than silently falsifying the published notice.

- [ ] **Step 1: Write the tests**

```python
# tests/test_public_pages_guards.py
"""Guards for the factual claims the shipped privacy notice makes.

Each asserts that a value the notice STATES still matches the code. Changing
any of them must fail here rather than quietly turn the notice into a lie.
"""
import re

import pytest
from django.conf import settings

from core.help import DOCS_ROOT

PRIVACY = (DOCS_ROOT / "public/privacy.md").read_text(encoding="utf-8")
PRIVACY_PL = (DOCS_ROOT / "public/privacy.pl.md").read_text(encoding="utf-8")


def test_session_cookie_age_matches_the_stated_two_weeks():
    assert settings.SESSION_COOKIE_AGE == 1209600
    assert "two weeks" in PRIVACY.lower()
    # The Polish notice states the same lifetimes and is equally falsifiable.
    assert "dwa tygodnie" in PRIVACY_PL.lower()


def test_session_cookie_is_still_persistent():
    # Setting this True makes sessionid a browser-session cookie while
    # SESSION_COOKIE_AGE stays 1209600 -- every other guard would stay green
    # while "persistent, not a session cookie" became false.
    assert not settings.SESSION_EXPIRE_AT_BROWSER_CLOSE


def test_csrf_cookie_age_matches_the_stated_year():
    assert settings.CSRF_COOKIE_AGE == 31449600


def test_theme_cookie_max_age_matches_the_stated_year():
    source = (settings.BASE_DIR / "core" / "views.py").read_text(encoding="utf-8")
    assert "31_536_000" in source


@pytest.mark.django_db
def test_no_undocumented_cookie_is_set_on_the_public_or_entrance_pages(client):
    """The notice names exactly four cookies. Anything else set on a surface a
    visitor can reach before logging in makes that list false."""
    from django.urls import reverse

    documented = {"sessionid", "csrftoken", "messages", "libli_theme"}
    for name in ("core:privacy", "core:getting_started", "account_login"):
        response = client.get(reverse(name))
        assert set(response.cookies) <= documented, (
            f"{name} set an undocumented cookie: {set(response.cookies) - documented}"
        )


def test_every_first_party_storage_key_uses_a_documented_prefix():
    """The notice claims all browser storage uses libli_, libli: or libli-.

    Scan roots are the project's own app static dirs only: a bare
    **/static/**/*.js glob sweeps .venv and Django's bundled admin JS (which
    writes "theme" and "django.admin.*") and would be red for unrelated reasons.
    """
    prefixes = ("libli_", "libli:", "libli-")
    call_re = re.compile(
        r"(?:local|session)Storage\.(?:set|get|remove)Item\(\s*([^,)]+)"
    )
    lit_re = re.compile(r'^["\']([^"\']*)')
    unresolved = []
    bad = []

    for path in settings.BASE_DIR.glob("*/static/**/*.js"):
        skip = {".venv", "site-packages", "staticfiles"}
        if any(part in skip for part in path.parts):
            continue
        source = path.read_text(encoding="utf-8")
        for raw in call_re.findall(source):
            arg = raw.strip()
            key = None
            # Rule 1: leading string literal of a (possibly concatenated) expr.
            match = lit_re.match(arg)
            if match:
                key = match.group(1)
            else:
                # Rule 2: bare identifier -> its initialiser, then rule 1. The
                # initialiser may itself be a concatenation (outline_tree.js:7).
                init = re.search(rf"\b{re.escape(arg)}\s*=\s*(.+)", source)
                # Rule 3: same-file function call -> its return expression.
                call = re.match(r"(\w+)\s*\(", arg)
                if init and lit_re.match(init.group(1).strip()):
                    key = lit_re.match(init.group(1).strip()).group(1)
                elif call:
                    ret = re.search(
                        rf"function\s+{re.escape(call.group(1))}"
                        rf"\s*\([^)]*\)\s*\{{[^}}]*?return\s+(.+)",
                        source, re.S,
                    )
                    if ret and lit_re.match(ret.group(1).strip()):
                        key = lit_re.match(ret.group(1).strip()).group(1)
            if key is None:
                unresolved.append(f"{path.name}: {arg}")  # rule 4: fail loudly
            elif not key.startswith(prefixes):
                bad.append(f"{path.name}: {key}")

    assert not unresolved, f"unresolved storage key expressions: {unresolved}"
    assert not bad, f"storage keys outside the documented prefixes: {bad}"
```

- [ ] **Step 2: Run the tests**

Run: `uv run python -m pytest tests/test_public_pages_guards.py -v`
Expected: PASS. If `test_every_first_party_storage_key_uses_a_documented_prefix` reports unresolved expressions, extend the resolver rules — do **not** loosen the assertion, which would destroy the guarantee.

- [ ] **Step 3: Commit**

```bash
git add tests/test_public_pages_guards.py
git commit -m "test(public-pages): guard the factual claims the notice makes"
```

---

### Task 13: i18n catalogue

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.mo`

**Interfaces:**
- Consumes: every `gettext_lazy` string added in Tasks 1–11.
- Produces: a complete Polish catalogue.

- [ ] **Step 1: Regenerate the catalogue**

```bash
uv run python manage.py makemessages -l pl
```

- [ ] **Step 2: Translate every new string**

New strings needing Polish: both `PAGES` titles and both meta descriptions; the demo-notice sentence; the three neutral fallback phrases ("the person who runs this site", "your national data protection authority", "no embed providers are enabled"); the `retention_phrase` **`ngettext` entry** (`msgid "after %(days)d day"` / `msgid_plural "after %(days)d days"`) — **all three** Polish `msgstr[n]` slots must be filled, since `nplurals=3` and the 90-day default selects `msgstr[2]` — plus "only when you delete them"; the two footer link labels; the settings tab label, section titles, field labels and help texts; both panel warnings; the "no longer enabled" marker; and both success messages.

**Clear every `#, fuzzy` marker on a new entry.** A fuzzy pre-fill puts a *wrong* Polish string into the catalogue, and clearing it means deleting **both** the `#, fuzzy` comment line and the wrong `msgstr` body.

**Inflection matters** for the substituted phrases: they land mid-sentence in a language that governs case. The privacy text places `{libli:supervisory_authority}` after a colon precisely so a nominative catalogue string reads correctly there.

- [ ] **Step 3: Compile and verify**

```bash
uv run python manage.py compilemessages
uv run python -m pytest tests/test_public_pages_views.py tests/test_public_pages_content.py -v
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(public-pages): add Polish strings for the public pages and settings tab"
```

---

## Final verification

- [ ] **Run the full public-pages suite**

```bash
uv run python -m pytest tests/test_public_pages.py tests/test_public_pages_model.py tests/test_public_pages_config.py tests/test_public_pages_render.py tests/test_public_pages_content.py tests/test_public_pages_views.py tests/test_public_pages_footer.py tests/test_public_pages_settings.py tests/test_public_pages_guards.py -v
```

Grep the summary line: pytest can exit 0 while reporting `1 failed`.

- [ ] **Run the branch gate** (whole-repo, once, not per task)

```bash
uv run python -m pytest -q
uv run ruff check --no-cache .
uv run ruff format --check .
```

- [ ] **Screenshot check** — `/privacy/` and `/getting-started/` in light and dark, plus `/accounts/login/` confirming the footer is at the bottom fold **and** the card is still centred. Judge dark mode on its own terms rather than assuming it follows from light.
