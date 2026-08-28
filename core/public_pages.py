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

import html as html_lib
import re
from dataclasses import dataclass

import markdown
import nh3
from django.conf import settings
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext


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
        _(
            "What libli stores about you, who can see it, how long it is kept, "
            "and how to exercise your data-protection rights."
        ),
    ),
    "getting-started": Page(
        "getting-started",
        "public/getting-started.md",
        _("Getting started"),
        _(
            "What libli is, how schools use it, and how to get an account or "
            "reach a human."
        ),
    ),
}


# A DOCUMENT allow-list, not courses.sanitize's rich-text one. That module's
# ALLOWED_TAGS (courses/sanitize.py:15) has no h1/table/thead/tbody/tr/th/td/hr,
# so a document passed through it loses its tables and headings silently.
PUBLIC_PAGE_TAGS = frozenset(
    {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "br",
        "ul",
        "ol",
        "li",
        "strong",
        "b",
        "em",
        "i",
        "code",
        "pre",
        "blockquote",
        "a",
        "hr",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
    }
)
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


BLOCK_TOKENS = frozenset({"demo_notice", "controller_address"})
INLINE_TOKENS = frozenset(
    {
        "controller_name",
        "contact_email",
        "site_name",
        "supervisory_authority",
        "embed_domains",
        "retention_phrase",
    }
)

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
        _(
            "This is a demonstration site. Anything you enter here is visible to "
            "the person who runs it — please do not enter real pupil data."
        ),
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
            ngettext("after %(days)d day", "after %(days)d days", days) % {"days": days}
            if days
            else _("only when the item they refer to is removed")
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
