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
    )

    # Who did it (optional)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
        verbose_name=_("المستخدم"),
    )

    # Generic relation to any target object (order, invoice, payment, etc.)
    target_content_type = models.ForeignKey(
        ContentType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    target_object_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
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

    def __str__(self) -> str:
        return f"[{self.action}] {self.message or self.pk}"
