from django.urls import path

from support import views

app_name = "support"

urlpatterns = [
    path("report/", views.report_create, name="report_create"),
]
