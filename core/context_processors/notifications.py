# core/context_processors/notifications.py
from core.models import Notification


def notifications_context(request):
    """
    Provide notification info for the current authenticated user:
    - notif_unread_count: number of unread notifications
    - notif_recent: list of recent notifications (latest first)
    - notif_has_unread: boolean flag
    """
    user = request.user
    if not user.is_authenticated:
        return {}

    base_qs = Notification.objects.for_user(user)

    unread_count = base_qs.unread().count()
    recent_notifications = list(
        base_qs.select_related("target_content_type")[:10]
    )

    return {
        "notif_unread_count": unread_count,
        "notif_recent": recent_notifications,
        "notif_has_unread": unread_count > 0,
    }
