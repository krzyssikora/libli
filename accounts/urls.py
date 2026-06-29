from django.urls import path

from accounts import views
from accounts import views_manage

app_name = "accounts"

urlpatterns = [
    path("invite/accept/<str:token>/", views.accept_invite, name="accept_invite"),
    path(
        "sso/not-provisioned/",
        views.sso_not_provisioned,
        name="sso_not_provisioned",
    ),
    path("manage/people/", views_manage.people, name="people"),
    path(
        "manage/people/invitations/",
        views_manage.people_invitations,
        name="people_invitations",
    ),
    path(
        "manage/people/users/<int:pk>/edit/",
        views_manage.user_edit,
        name="user_edit",
    ),
    path(
        "manage/people/users/<int:pk>/deactivate/",
        views_manage.user_deactivate,
        name="user_deactivate",
    ),
    path(
        "manage/people/users/<int:pk>/reactivate/",
        views_manage.user_reactivate,
        name="user_reactivate",
    ),
]
