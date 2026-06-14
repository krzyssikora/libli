from django.contrib import admin
from django.http import JsonResponse
from django.urls import include
from django.urls import path

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
    path("accounts/", include("allauth.account.urls")),
    path("accounts/", include("allauth.socialaccount.urls")),
    path("accounts/", include("allauth.socialaccount.providers.openid_connect.urls")),
]
