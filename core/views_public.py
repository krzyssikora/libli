"""Anonymous public content pages. The first non-login_required content
surface in the codebase -- keep it that way: no auth, no user data."""

from django.conf import settings
from django.http import Http404
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


def for_schools(request):
    """The vendor's own school-facing page. Absent on a school's box.

    Reads the flag from settings, never Institution.load() -- that is
    get_or_create, a write, which core/services.py forbids on a GET render path.
    """
    if not settings.VENDOR_INSTANCE:
        raise Http404
    return _public_page(request, "for-schools")
