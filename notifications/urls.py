from django.urls import path

from notifications import push_views
from notifications import views

app_name = "notifications"

urlpatterns = [
    path("notifications/", views.notification_list, name="list"),
    path("notifications/<int:pk>/read/", views.mark_read, name="mark_read"),
    path("notifications/read-all/", views.mark_all_read, name="mark_all_read"),
    path("notifications/<int:pk>/open/", push_views.open_notification, name="open"),
    path(
        "notifications/push/subscribe/",
        push_views.push_subscribe,
        name="push_subscribe",
    ),
    path(
        "notifications/push/unsubscribe/",
        push_views.push_unsubscribe,
        name="push_unsubscribe",
    ),
    path("notifications/push/claim/", push_views.push_claim, name="push_claim"),
]
