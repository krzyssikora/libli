from django.urls import path

from core import views

app_name = "core"

urlpatterns = [
    path("ui/set-language/", views.set_ui_language, name="set_ui_language"),
    path("ui/set-theme/", views.set_theme, name="set_theme"),
    path("settings/", views.user_settings, name="user_settings"),
]
