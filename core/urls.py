# core/urls.py
from django.urls import path

from core.views import NotificationListView, NotificationReadRedirectView, notification_mark_all_read, \
    notification_delete, AuditLogListView
from core.views.attachments import AttachmentDeleteView, AttachmentCreateView

app_name = "core"

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
    path(
        "audit-log/",
        AuditLogListView.as_view(),
        name="audit_log_list",
    ),

    path("attachments/add/", AttachmentCreateView.as_view(), name="attachment_add"),
    path("attachments/<int:pk>/delete/", AttachmentDeleteView.as_view(), name="attachment_delete"),
]

