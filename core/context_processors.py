# core/context_processors.py
from core.models import Notification


def notifications_context(request):
    """
    Provide notification info for the current authenticated user:
    - notif_unread_count: number of unread notifications
    - notif_recent: list of recent notifications (latest first)
    """
    user = request.user
    if not user.is_authenticated:
        return {}

    qs = (
        Notification.objects
        .filter(recipient=user, is_deleted=False)
        .order_by("-created_at")
    )

    unread_count = qs.filter(is_read=False).count()
    recent_notifications = list(qs[:10])

    return {
        "notif_unread_count": unread_count,
        "notif_recent": recent_notifications,
    }
