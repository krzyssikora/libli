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
