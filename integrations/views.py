"""Public, no-login integration docs rendered from trusted repo markdown."""

from django.shortcuts import render
from django.utils import translation

from integrations.docs import render_markdown_doc

# Guide file per UI language. English is the canonical fallback for any
# language without its own translation.
_GUIDE_BY_LANG = {
    "en": "integrations/sis-webhook.md",
    "pl": "integrations/sis-webhook.pl.md",
}


def webhook_guide(request):
    lang = (translation.get_language() or "en").split("-")[0]
    rel_path = _GUIDE_BY_LANG.get(lang, _GUIDE_BY_LANG["en"])
    html = render_markdown_doc(rel_path)
    return render(request, "integrations/webhook_guide.html", {"content": html})
