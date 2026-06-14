from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.context_processors import THEME_VALUES
from core.middleware import LANGUAGE_SESSION_KEY as SESSION_KEY
from core.services import get_site_config


@login_required
def home(request):
    """Placeholder post-login page; the real adaptive dashboard is Phase 0d-2."""
    return render(request, "core/home.html")


@require_POST
def set_ui_language(request):
    """Switch UI language (session + User.language if authed); safe-redirect back."""
    lang = request.POST.get("language", "")
    if lang in get_site_config()["enabled_languages"]:
        request.session[SESSION_KEY] = lang
        if request.user.is_authenticated:
            request.user.language = lang
            request.user.save(update_fields=["language"])
    nxt = request.POST.get("next") or request.headers.get("referer", "")
    if not url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        nxt = reverse("home")
    return redirect(nxt)


@login_required
@require_POST
def set_theme(request):
    """Persist User.theme (fetch endpoint: 204 on success, 400 on bad value)."""
    theme = request.POST.get("theme", "")
    if theme not in THEME_VALUES:
        return HttpResponseBadRequest("invalid theme")
    request.user.theme = theme
    request.user.save(update_fields=["theme"])
    return HttpResponse(status=204)
