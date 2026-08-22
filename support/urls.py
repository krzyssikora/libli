from django.urls import path

from support import views
from support import views_manage

app_name = "support"

urlpatterns = [
    path("report/", views.report_create, name="report_create"),
    path("manage/issue-reports/", views_manage.report_list, name="report_list"),
    path(
        "manage/issue-reports/<int:pk>/",
        views_manage.report_detail,
        name="report_detail",
    ),
    path(
        "manage/issue-reports/<int:pk>/status/",
        views_manage.report_set_status,
        name="report_set_status",
    ),
    path(
        "manage/issue-reports/<int:pk>/delete/",
        views_manage.report_delete,
        name="report_delete",
    ),
    path(
        "manage/issue-reports/<int:pk>/screenshot/",
        views_manage.screenshot,
        name="screenshot",
    ),
    path(
        "manage/settings/support/reporters/", views_manage.reporters, name="reporters"
    ),
]
