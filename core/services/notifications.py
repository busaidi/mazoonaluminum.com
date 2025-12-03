# core/services/notifications.py

from __future__ import annotations

from typing import Any, Optional

from django.contrib.contenttypes.models import ContentType

from core.models import Notification


def create_notification(
    recipient,
    verb: str,
    target: Optional[Any] = None,
    *,
    level: str = Notification.Levels.INFO,
    url: str | None = None,
) -> Notification:
    """
    Create a simple in-app notification.

    Parameters
    ----------
    recipient:
        User instance who will receive the notification.

    verb:
        Short description of what happened. Keep it concise and clear.

    target:
        Optional model instance (invoice, sales document, payment...) that this
        notification refers to. Will be stored via GenericForeignKey.

    level:
        Visual level (info / success / warning / error). Use Notification.Levels.*.

    url:
        Optional URL path (e.g. '/sales/documents/1/') or full URL.
        This will be used by NotificationReadRedirectView.

    Returns
    -------
    Notification
        The created Notification instance.
    """
    target_ct = None
    target_id = None

    if target is not None:
        target_ct = ContentType.objects.get_for_model(target, for_concrete_model=True)
        target_id = str(getattr(target, "pk", getattr(target, "id", None)))

    notification = Notification.objects.create(
        recipient=recipient,
        verb=verb,
        level=level,
        url=url or "",
        target_content_type=target_ct,
        target_object_id=target_id,
    )

    return notification
