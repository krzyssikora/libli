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
]
