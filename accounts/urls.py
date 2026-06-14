from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("invite/accept/<str:token>/", views.accept_invite, name="accept_invite"),
    path(
        "sso/not-provisioned/",
        views.sso_not_provisioned,
        name="sso_not_provisioned",
    ),
]
