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
