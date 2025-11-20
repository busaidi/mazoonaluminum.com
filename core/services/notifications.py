# core/services/notifications.py
from django.contrib.contenttypes.models import ContentType

from core.models import Notification


def create_notification(
    recipient,
    verb: str,
    target=None,
    *,
    level: str = Notification.Levels.INFO,
    url: str | None = None,
):
    target_ct = None
    target_id = None

    if target is not None:
        target_ct = ContentType.objects.get_for_model(target.__class__)
        target_id = str(target.pk)

    return Notification.objects.create(
        recipient=recipient,
        verb=verb,
        level=level,
        url=url or "",
        target_content_type=target_ct,
        target_object_id=target_id,
    )

