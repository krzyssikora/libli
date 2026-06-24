from django.urls import path

from courses import views
from courses import views_manage
from courses import views_media

app_name = "courses"

urlpatterns = [
    path("courses/", views.my_courses, name="my_courses"),
    path("courses/<slug:slug>/", views.course_outline, name="course_outline"),
    path("courses/<slug:slug>/results/", views.course_results, name="course_results"),
    path("courses/<slug:slug>/u/<int:node_pk>/", views.lesson_unit, name="lesson_unit"),
    path("courses/<slug:slug>/u/<int:node_pk>/seen/", views.seen, name="seen"),
    path(
        "courses/<slug:slug>/u/<int:node_pk>/complete/",
        views.complete,
        name="complete",
    ),
    path(
        "courses/<slug:slug>/u/<int:node_pk>/q/<int:element_pk>/check/",
        views.check_answer,
        name="check_answer",
    ),
    path(
        "courses/<slug:slug>/u/<int:node_pk>/quiz/",
        views.quiz_unit,
        name="quiz_unit",
    ),
    path(
        "courses/<slug:slug>/u/<int:node_pk>/quiz/q/<int:element_pk>/answer/",
        views.quiz_answer,
        name="quiz_answer",
    ),
    path(
        "courses/<slug:slug>/u/<int:node_pk>/quiz/finish/",
        views.quiz_finish,
        name="quiz_finish",
    ),
    path(
        "courses/<slug:slug>/u/<int:node_pk>/quiz/results/",
        views.quiz_results,
        name="quiz_results",
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
    path(
        "manage/courses/<slug:slug>/build/node/<int:pk>/",
        views_manage.node_panel,
        name="manage_node_panel",
    ),
    # --- node-op / element-op routes (stubs in Task 6; real views in Tasks 7-8) ---
    path(
        "manage/courses/<slug:slug>/build/node/add/",
        views_manage.node_add,
        name="manage_node_add",
    ),
    path(
        "manage/courses/<slug:slug>/build/node/rename/",
        views_manage.node_rename,
        name="manage_node_rename",
    ),
    path(
        "manage/courses/<slug:slug>/build/node/move/",
        views_manage.node_move,
        name="manage_node_move",
    ),
    path(
        "manage/courses/<slug:slug>/build/node/delete/",
        views_manage.node_delete,
        name="manage_node_delete",
    ),
    path(
        "manage/courses/<slug:slug>/build/element/move/",
        views_manage.element_move,
        name="manage_element_move",
    ),
    path(
        "manage/courses/<slug:slug>/build/element/delete/",
        views_manage.element_delete,
        name="manage_element_delete",
    ),
    # --- editor｜preview page (Phase 1b-ii, Task 4) ---
    path(
        "manage/courses/<slug:slug>/build/unit/<int:pk>/edit/",
        views_manage.editor,
        name="manage_editor",
    ),
    # --- element add/save/form (STUBS in Task 4; real views in Task 6) ---
    path(
        "manage/courses/<slug:slug>/build/element/add/",
        views_manage.element_add,
        name="manage_element_add",
    ),
    path(
        "manage/courses/<slug:slug>/build/element/save/",
        views_manage.element_save,
        name="manage_element_save",
    ),
    path(
        "manage/courses/<slug:slug>/build/element/<int:pk>/form/",
        views_manage.element_form,
        name="manage_element_form",
    ),
    path(
        "manage/courses/<slug:slug>/build/element/<int:pk>/try/",
        views_manage.element_try,
        name="manage_element_try",
    ),
    # --- media manager routes (Phase 1b-ii, 5.13) ---
    path(
        "manage/courses/<slug:slug>/media/",
        views_media.media_manager,
        name="manage_media",
    ),
    path(
        "manage/courses/<slug:slug>/media/upload/",
        views_media.media_upload,
        name="manage_media_upload",
    ),
    path(
        "manage/courses/<slug:slug>/media/rename/",
        views_media.media_rename,
        name="manage_media_rename",
    ),
    path(
        "manage/courses/<slug:slug>/media/<int:pk>/delete/",
        views_media.media_delete,
        name="manage_media_delete",
    ),
    path(
        "manage/courses/<slug:slug>/media/picker/",
        views_media.media_picker,
        name="manage_media_picker",
    ),
    path("catalog/", views.catalog, name="catalog"),
    path("catalog/<slug:slug>/", views.catalog_detail, name="catalog_detail"),
    path("catalog/<slug:slug>/enroll/", views.self_enroll, name="self_enroll"),
]
