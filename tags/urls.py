from django.urls import path

from tags import views

app_name = "tags"

urlpatterns = [
    path(
        "courses/<slug:slug>/u/<int:node_pk>/tags/add/",
        views.tag_add,
        name="tag_add",
    ),
    path(
        "courses/<slug:slug>/u/<int:node_pk>/tags/remove/",
        views.tag_remove,
        name="tag_remove",
    ),
    path("tags/", views.my_tags, name="my_tags"),
    path("tags/<int:tag_pk>/rename/", views.tag_rename, name="tag_rename"),
    path("tags/<int:tag_pk>/recolor/", views.tag_recolor, name="tag_recolor"),
    path("tags/<int:tag_pk>/delete/", views.tag_delete, name="tag_delete"),
]
