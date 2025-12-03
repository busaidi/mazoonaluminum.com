# core/models/notifications.py

from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel

User = get_user_model()


class NotificationQuerySet(models.QuerySet):
    def visible(self):
        """Return non-deleted notifications."""
        return self.filter(is_deleted=False)

    def for_user(self, user: User):
        """Return visible notifications for a specific user."""
        return self.visible().filter(recipient=user)

    def unread(self):
        """Return unread + visible notifications."""
        return self.visible().filter(is_read=False)


class NotificationManager(models.Manager.from_queryset(NotificationQuerySet)):
    pass


class Notification(BaseModel):
    """
    Simple in-app notification model for Mazoon ERP.

    - recipient: user who receives the notification
    - verb: short description of the event
    - level: visual level (info / success / warning / error)
    - url: URL to open when the notification is clicked
    - target: generic relation to a domain object (invoice, order, ...)
    """

    class Levels(models.TextChoices):
        INFO = "info", _("Info")
        SUCCESS = "success", _("Success")
        WARNING = "warning", _("Warning")
        ERROR = "error", _("Error")

    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("Recipient"),
    )

    verb = models.CharField(
        max_length=255,
        verbose_name=_("Verb"),
        help_text=_("Short description of the event, e.g. 'New order created'."),
    )

    level = models.CharField(
        max_length=20,
        choices=Levels.choices,
        default=Levels.INFO,
        verbose_name=_("Level"),
    )

    url = models.CharField(
        max_length=500,
        blank=True,
        verbose_name=_("URL"),
        help_text=_("Resolved URL to redirect when the notification is clicked."),
    )

    # Generic relation to any model (Order, Invoice, Payment, ...)
    target_content_type = models.ForeignKey(
        ContentType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notification_targets",
        verbose_name=_("Target content type"),
    )
    target_object_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        verbose_name=_("Target object ID"),
    )
    target = GenericForeignKey("target_content_type", "target_object_id")

    is_read = models.BooleanField(
        default=False,
        verbose_name=_("Is read?"),
    )
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Read at"),
    )

    objects = NotificationManager()

    class Meta:
        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.recipient} – {self.verb[:50]}"

    def mark_as_read(self, user: User | None = None) -> None:
        """
        Mark this notification as read (idempotent).
        """
        if self.is_read:
            return

        self.is_read = True
        self.read_at = timezone.now()

        if user is not None and not self.updated_by:
            self.updated_by = user

        self.save(update_fields=["is_read", "read_at", "updated_by"])

    # ==== Helpers for Bootstrap UI ====

    @property
    def bootstrap_level_class(self) -> str:
        """
        Bootstrap v5 compatible classes for badge/alert background + text.
        """
        try:
            level_enum = self.Levels(self.level)
        except ValueError:
            # Fallback if somehow the value is invalid
            return "bg-secondary-subtle text-secondary-emphasis"

        mapping = {
            self.Levels.INFO: "bg-secondary-subtle text-secondary-emphasis",
            self.Levels.SUCCESS: "bg-success-subtle text-success-emphasis",
            self.Levels.WARNING: "bg-warning-subtle text-warning-emphasis",
            self.Levels.ERROR: "bg-danger-subtle text-danger-emphasis",
        }
        return mapping.get(
            level_enum,
            "bg-secondary-subtle text-secondary-emphasis",
        )

    @property
    def icon_name(self) -> str:
        """
        Bootstrap Icons name to represent the level.
        """
        try:
            level_enum = self.Levels(self.level)
        except ValueError:
            return "bi-info-circle"

        mapping = {
            self.Levels.INFO: "bi-info-circle",
            self.Levels.SUCCESS: "bi-check-circle",
            self.Levels.WARNING: "bi-exclamation-triangle",
            self.Levels.ERROR: "bi-x-circle",
        }
        return mapping.get(level_enum, "bi-info-circle")
