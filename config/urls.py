from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include
from django.urls import path

from core.media_serve import serve_media
from core.views import home
from core.views import landing


def healthz(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz, name="healthz"),
    path("home/", home, name="home"),
    path("", landing, name="landing"),
    path("", include("core.urls")),
    path("", include("accounts.urls")),
    path("", include("courses.urls")),
    path("", include("grouping.urls")),
    path("", include("notes.urls")),
    path("", include("notifications.urls")),
    path("", include("tags.urls")),
    path("", include("institution.urls")),
    path("", include("integrations.urls")),
    path("", include("support.urls")),
    path("accounts/", include("allauth.account.urls")),
    path("accounts/", include("allauth.socialaccount.urls")),
    path("accounts/", include("allauth.socialaccount.providers.openid_connect.urls")),
]

if settings.DEBUG:
    # serve_media, not the stock django.views.static.serve that static() wires up:
    # Django implements no HTTP Range handling, and without 206 responses a browser
    # will not let a student seek inside a <video> (no skipping, no replaying a
    # passage without starting over). See core/media_serve.py — including its note
    # on what a real deployment needs, since this branch is DEBUG-only.
    urlpatterns += static(
        settings.MEDIA_URL, view=serve_media, document_root=settings.MEDIA_ROOT
    )
