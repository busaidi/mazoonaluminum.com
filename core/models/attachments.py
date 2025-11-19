# core/models/attachments.py
from __future__ import annotations

import os

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _


def attachment_upload_to(instance: "Attachment", filename: str) -> str:
    """
    مسار رفع المرفقات داخل media/.
    مثال:
        attachments/accounting/invoice/123/filename.pdf
    """
    if instance.content_type:
        app_label = instance.content_type.app_label
        model_name = instance.content_type.model  # lowercase model name
    else:
        app_label = "unknown"
        model_name = "unknown"

    return os.path.join(
        "attachments",
        app_label,
        model_name,
        str(instance.object_id or "unassigned"),
        filename,
    )


class Attachment(models.Model):
    """
    مرفق عام يمكن ربطه بأي موديل في النظام (فاتورة، أمر، عميل، مشروع، ...).
    """

    # ---------- الربط العام بأي كيان ----------
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name=_("نوع الكيان"),
    )
    object_id = models.PositiveIntegerField(
        verbose_name=_("معرّف الكيان"),
    )
    content_object = GenericForeignKey("content_type", "object_id")

    # ---------- بيانات الملف ----------
    file = models.FileField(
        upload_to=attachment_upload_to,
        verbose_name=_("الملف"),
    )
    title = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("عنوان المرفق"),
        help_text=_("اسم داخلي يساعدك على تمييز المرفق."),
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("وصف"),
        help_text=_("ملاحظات إضافية حول المرفق (اختياري)."),
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_attachments",
        verbose_name=_("تم الرفع بواسطة"),
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("تاريخ الرفع"),
    )

    is_public = models.BooleanField(
        default=True,
        verbose_name=_("مرئي للواجهة؟"),
        help_text=_("يمكن استخدامه لاحقًا لفلترة المرفقات في البورتال/الويب."),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("مفعّل"),
        help_text=_("بدلاً من الحذف النهائي، يمكنك إلغاء التفعيل لإخفاء المرفق."),
    )

    class Meta:
        verbose_name = _("مرفق")
        verbose_name_plural = _("المرفقات")
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["uploaded_at"]),
            models.Index(fields=["is_active"]),
        ]
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        if self.title:
            return self.title
        return os.path.basename(self.file.name or "") or f"Attachment #{self.pk}"
