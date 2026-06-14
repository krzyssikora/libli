from django.contrib import admin
from django.http import JsonResponse
from django.urls import include
from django.urls import path

from config.views import home


def healthz(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz, name="healthz"),
    path("home/", home, name="home"),
    path("", include("accounts.urls")),
    # allauth, mounted under one prefix: account views + socialaccount views +
    # the per-provider OIDC login/callback URLs (provider urls are not in
    # socialaccount.urls).
    path("accounts/", include("allauth.account.urls")),
    path("accounts/", include("allauth.socialaccount.urls")),
    path("accounts/", include("allauth.socialaccount.providers.openid_connect.urls")),
]
