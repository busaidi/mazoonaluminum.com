# core/urls/notifications.py
from django.urls import path

from core.views import (
    NotificationListView,
    NotificationReadRedirectView,
    notification_mark_all_read,
    notification_delete,
)

urlpatterns = [
    path(
        "notifications/",
        NotificationListView.as_view(),
        name="notification_list",
    ),
    path(
        "notifications/<uuid:public_id>/",
        NotificationReadRedirectView.as_view(),
        name="notification_read_redirect",
    ),
    path(
        "notifications/mark-all-read/",
        notification_mark_all_read,
        name="notification_mark_all_read",
    ),
    path(
        "notifications/<uuid:public_id>/delete/",
        notification_delete,
        name="notification_delete",
    ),
]
