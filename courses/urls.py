from django.urls import path

from courses import views
from courses import views_manage

app_name = "courses"

urlpatterns = [
    path("courses/", views.my_courses, name="my_courses"),
    path("courses/<slug:slug>/", views.course_outline, name="course_outline"),
    path("courses/<slug:slug>/u/<int:node_pk>/", views.lesson_unit, name="lesson_unit"),
    path("courses/<slug:slug>/u/<int:node_pk>/seen/", views.seen, name="seen"),
    path(
        "courses/<slug:slug>/u/<int:node_pk>/complete/",
        views.complete,
        name="complete",
    ),
    # --- /manage/ authoring surface (Phase 1b-i) ---
    path("manage/courses/", views_manage.course_list, name="manage_course_list"),
    path(
        "manage/courses/new/",
        views_manage.course_create,
        name="manage_course_create",
    ),
    path(
        "manage/courses/<slug:slug>/edit/",
        views_manage.course_edit,
        name="manage_course_edit",
    ),
    path(
        "manage/courses/<slug:slug>/delete/",
        views_manage.course_delete,
        name="manage_course_delete",
    ),
    path(
        "manage/courses/<slug:slug>/build/",
        views_manage.builder,
        name="manage_builder",
    ),
]
