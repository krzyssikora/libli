from django.urls import path

from integrations import views

app_name = "integrations"

urlpatterns = [
    # Included at the project root, so the pattern carries the full path.
    path("integrations/webhook/", views.webhook_guide, name="webhook_guide"),
]
