from django.urls import path

from institution import views_manage
from institution import views_setup

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
    path(
        "manage/settings/notifications/",
        views_manage.settings_notifications,
        name="settings_notifications",
    ),
    path(
        "manage/settings/notifications/purge/",
        views_manage.settings_notifications_purge,
        name="settings_notifications_purge",
    ),
    path(
        "manage/settings/integrations/",
        views_manage.settings_integrations,
        name="settings_integrations",
    ),
    path(
        "manage/settings/integrations/test/",
        views_manage.settings_integrations_test,
        name="settings_integrations_test",
    ),
    # Phase 5e — first-run setup wizard
    # skip MUST precede <str:step> so /manage/setup/skip/ is not captured as a step.
    path("manage/setup/", views_setup.setup, name="setup"),
    path("manage/setup/skip/", views_setup.setup_skip, name="setup_skip"),
    path("manage/setup/<str:step>/", views_setup.setup_step, name="setup_step"),
]
