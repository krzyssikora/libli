from django.urls import path

from institution import views_manage

app_name = "institution"

urlpatterns = [
    path("manage/settings/", views_manage.settings, name="settings"),
    path(
        "manage/settings/branding/",
        views_manage.settings_branding,
        name="settings_branding",
    ),
    path(
        "manage/settings/access/",
        views_manage.settings_access,
        name="settings_access",
    ),
    path(
        "manage/settings/uploads/",
        views_manage.settings_uploads,
        name="settings_uploads",
    ),
    path(
        "manage/settings/sso/",
        views_manage.settings_sso,
        name="settings_sso",
    ),
]
