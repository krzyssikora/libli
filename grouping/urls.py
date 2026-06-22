from django.urls import path

from grouping import views

app_name = "grouping"

urlpatterns = [
    path("manage/cohorts/", views.cohort_list, name="cohort_list"),
    path("manage/cohorts/new/", views.cohort_create, name="cohort_create"),
    path("manage/cohorts/<slug:slug>/edit/", views.cohort_edit, name="cohort_edit"),
    path(
        "manage/cohorts/<slug:slug>/promote/",
        views.cohort_promote,
        name="cohort_promote",
    ),
    path(
        "manage/cohorts/<slug:slug>/archive/",
        views.cohort_archive,
        name="cohort_archive",
    ),
    path(
        "manage/cohorts/<slug:slug>/assign/",
        views.cohort_assign_students,
        name="cohort_assign_students",
    ),
    path(
        "manage/cohorts/<slug:slug>/delete/",
        views.cohort_delete,
        name="cohort_delete",
    ),
    path("manage/groups/", views.group_list, name="group_list"),
    path("manage/groups/new/", views.group_create, name="group_create"),
    path("manage/groups/<int:pk>/edit/", views.group_edit, name="group_edit"),
    path("manage/groups/<int:pk>/archive/", views.group_archive, name="group_archive"),
    path("manage/groups/<int:pk>/delete/", views.group_delete, name="group_delete"),
    path("groups/mine/", views.my_groups, name="my_groups"),
    path("groups/<int:pk>/", views.group_detail, name="group_detail"),
]
