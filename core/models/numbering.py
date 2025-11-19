# core/models/numbering.py
from django.db import models
from django.utils.translation import gettext_lazy as _


class NumberingScheme(models.Model):
    """
    Numbering configuration per model.

    Example row:
    - model_label: "accounting.Invoice"
    - field_name: "number"
    - pattern: "INV-{year}-{seq:04d}"
    - reset: "year"
    - start: 1
    """

    class ResetPolicy(models.TextChoices):
        NEVER = "never", _("لا يتم إعادة الترقيم")
        YEAR = "year", _("يُعاد سنوياً")
        MONTH = "month", _("يُعاد شهرياً")

    model_label = models.CharField(
        max_length=100,
        unique=True,
        verbose_name=_("اسم الموديل (label)"),
        help_text=_("مثال: accounting.Invoice أو accounting.Order"),
    )

    field_name = models.CharField(
        max_length=50,
        default="number",
        verbose_name=_("اسم الحقل"),
        help_text=_("عادة يكون 'number'."),
    )

    pattern = models.CharField(
        max_length=100,
        verbose_name=_("نمط الترقيم"),
        help_text=_("مثال: INV-{year}-{seq:04d} أو SO-{year}-{month:02d}-{seq:03d}"),
    )

    reset = models.CharField(
        max_length=10,
        choices=ResetPolicy.choices,
        default=ResetPolicy.YEAR,
        verbose_name=_("سياسة إعادة الترقيم"),
    )

    start = models.PositiveIntegerField(
        default=1,
        verbose_name=_("قيمة البداية للتسلسل"),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("مفعّل"),
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("آخر تعديل"),
    )

    class Meta:
        verbose_name = _("إعداد ترقيم")
        verbose_name_plural = _("إعدادات الترقيم")
        indexes = [
            models.Index(fields=["model_label"]),
        ]

    def __str__(self) -> str:
        return f"{self.model_label} → {self.pattern}"

    def clean(self):
        super().clean()
        if "{seq" not in self.pattern:
            from django.core.exceptions import ValidationError
            raise ValidationError(_("نمط الترقيم يجب أن يحتوي على المتغير {seq}."))

    @classmethod
    def get_for_instance(cls, instance: models.Model) -> "NumberingScheme":
        """
        Get active scheme for given model instance label.
        """
        label = instance._meta.label  # e.g. "accounting.Invoice"
        try:
            return cls.objects.get(model_label=label, is_active=True)
        except cls.DoesNotExist:
            raise ValueError(f"No active NumberingScheme configured for '{label}'")
