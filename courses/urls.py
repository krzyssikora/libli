from django.urls import path

from courses import views

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
]
