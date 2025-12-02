# core/models/audit.py
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import TimeStampedModel, SoftDeleteModel


class AuditLog(TimeStampedModel, SoftDeleteModel):
    """
    Simple audit log entry to record important business events.

    Designed to be generic and lightweight:
    - action: short code describing what happened
    - actor: who did it (user)
    - target: any model instance (via GenericForeignKey)
    - message: human-readable description
    - extra: JSON payload for structured data
    """

    class Action(models.TextChoices):
        CREATE = "create", _("إنشاء")
        UPDATE = "update", _("تعديل")
        DELETE = "delete", _("حذف")
        STATUS_CHANGE = "status_change", _("تغيير حالة")
        NOTIFICATION = "notification", _("إشعار")
        OTHER = "other", _("أخرى")

    # What happened
    action = models.CharField(
        max_length=32,
        choices=Action.choices,
        verbose_name=_("العملية"),
        db_index=True,
    )

    # Who did it (optional)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
        verbose_name=_("المستخدم"),
        help_text=_("المستخدم الذي قام بهذه العملية إن وُجد."),
    )

    # Generic relation to any target object (order, invoice, payment, etc.)
    target_content_type = models.ForeignKey(
        ContentType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
        verbose_name=_("نوع الكائن"),
    )
    target_object_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        verbose_name=_("معرّف الكائن"),
    )
    target = GenericForeignKey("target_content_type", "target_object_id")

    # Human-readable description
    message = models.TextField(
        verbose_name=_("الوصف"),
        blank=True,
    )

    # Extra structured data (JSON)
    extra = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("بيانات إضافية"),
    )

    class Meta:
        verbose_name = _("سجل تدقيق")
        verbose_name_plural = _("سجلات التدقيق")
        ordering = ("-created_at",)
        indexes = [
            # Fast filtering by actor (user audit history)
            models.Index(fields=["actor", "created_at"]),
            # Fast filtering by target (object audit history)
            models.Index(fields=["target_content_type", "target_object_id", "created_at"]),
            # Filter by action type
            models.Index(fields=["action", "created_at"]),
        ]

    def __str__(self) -> str:
        base = f"[{self.action}]"
        if self.message:
            return f"{base} {self.message[:80]}"
        if self.target:
            return f"{base} {self.target!r}"
        return f"{base} #{self.pk}"
