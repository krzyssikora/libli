from django.contrib import admin
from django.http import JsonResponse
from django.urls import include
from django.urls import path


def healthz(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz, name="healthz"),
    path("accounts/", include("allauth.account.urls")),
]
