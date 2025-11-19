# core/views/__init__.py

from .notifications import (
    NotificationListView,
    NotificationReadRedirectView,
    notification_mark_all_read,
    notification_delete,
    AuditLogListView,
)

from .attachments import (
    AttachmentParentMixin,
    BaseAttachmentCreateView,
    BaseAttachmentDeleteView,
)

__all__ = [
    # Notifications
    "NotificationListView",
    "NotificationReadRedirectView",
    "notification_mark_all_read",
    "notification_delete",
    "AuditLogListView",
    # Attachments
    "AttachmentParentMixin",
    "BaseAttachmentCreateView",
    "BaseAttachmentDeleteView",
]
