# core/services/notifications.py
from django.contrib.contenttypes.models import ContentType

from core.models import Notification


def create_notification(recipient, verb: str, target=None):
    """
    Create a notification for a given user.

    :param recipient: User instance who will receive the notification
    :param verb: Short text describing the event
    :param target: Optional model instance related to the event (Order, Invoice, ...)
    """
    target_ct = None
    target_id = None

    if target is not None:
        target_ct = ContentType.objects.get_for_model(target.__class__)
        # here we use the primary key, not public_id, so GenericForeignKey works correctly
        target_id = str(target.pk)

    return Notification.objects.create(
        recipient=recipient,
        verb=verb,
        target_content_type=target_ct,
        target_object_id=target_id,
    )
