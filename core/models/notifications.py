# core/models/notifications.py
from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from core.models import BaseModel

User = get_user_model()


class NotificationQuerySet(models.QuerySet):
    def visible(self):
        return self.filter(is_deleted=False)

    def for_user(self, user):
        return self.visible().filter(recipient=user)

    def unread(self):
        return self.filter(is_read=False)


class NotificationManager(models.Manager.from_queryset(NotificationQuerySet)):
    pass


class Notification(BaseModel):
    """
    Simple notification model for Mazoon ERP.
    - recipient: المستخدم الذي يستلم التنبيه
    - verb: وصف قصير
    - target: كيان مرتبط (فاتورة، طلب، ...)
    - context: سياق الإشعار (مثلاً: 'staff', 'customer' ... إلخ)
    """

    class Levels(models.TextChoices):
        INFO = "info", "Info"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"

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

    level = models.CharField(
        max_length=20,
        choices=Levels.choices,
        default=Levels.INFO,
    )

    url = models.CharField(
        max_length=500,
        blank=True,
        help_text="Resolved URL to redirect when the notification is clicked.",
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

    objects = NotificationManager()

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

    # ==== Helpers للـ UI (Bootstrap) ====

    @property
    def bootstrap_level_class(self) -> str:
        """
        CSS class لعرض البادج حسب المستوى.
        """
        mapping = {
            self.Levels.INFO: "bg-secondary-subtle text-secondary-emphasis",
            self.Levels.SUCCESS: "bg-success-subtle text-success-emphasis",
            self.Levels.WARNING: "bg-warning-subtle text-warning-emphasis",
            self.Levels.ERROR: "bg-danger-subtle text-danger-emphasis",
        }
        return mapping.get(self.level, "bg-secondary-subtle text-secondary-emphasis")

    @property
    def icon_name(self) -> str:
        """
        اسم أيقونة (Bootstrap Icons) حسب المستوى.
        """
        mapping = {
            self.Levels.INFO: "bi-info-circle",
            self.Levels.SUCCESS: "bi-check-circle",
            self.Levels.WARNING: "bi-exclamation-triangle",
            self.Levels.ERROR: "bi-x-circle",
        }
        return mapping.get(self.level, "bi-info-circle")
