# core/models/notifications.py
from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from core.models import BaseModel

User = get_user_model()


class Notification(BaseModel):
    """
    Simple notification model for Mazoon ERP.
    - recipient: المستخدم اللي يستلم التنبيه
    - verb: وصف قصير (مثال: "تم إنشاء طلب جديد")
    - target: كيان مرتبط (فاتورة، طلب، دفعة، ... إلخ) عبر GenericForeignKey
    """

    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Recipient",
    )

    verb = models.CharField(
        max_length=255,
        verbose_name="Verb",
        help_text="Short description of the event, e.g. 'New order created'.",
    )

    # Generic relation to any model (Order, Invoice, Payment, ...)
    target_content_type = models.ForeignKey(
        ContentType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notification_targets",
    )
    target_object_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
    )
    target = GenericForeignKey("target_content_type", "target_object_id")

    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ["-created_at"]

    def mark_as_read(self, user=None):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            if user and not self.updated_by:
                self.updated_by = user
            self.save(update_fields=["is_read", "read_at", "updated_by"])
