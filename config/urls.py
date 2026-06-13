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
    path("accounts/", include("allauth.account.urls")),
]
