from django.urls import path

from notes import views

app_name = "notes"

urlpatterns = [
    path(
        "courses/<slug:slug>/u/<int:node_pk>/notes/add/",
        views.note_add,
        name="note_add",
    ),
    path("notes/<int:note_pk>/edit/", views.note_edit, name="note_edit"),
    path("notes/<int:note_pk>/delete/", views.note_delete, name="note_delete"),
]
