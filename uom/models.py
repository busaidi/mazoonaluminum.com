# uom/models.py
from django.db import models
from django.utils.translation import gettext_lazy as _


class UomCategory(models.Model):
    """
    High-level category for units:
    length, weight, area, volume, piece, time, etc.
    """

    code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_("كود الفئة"),
        help_text=_("مثال: length, weight, area, volume, unit, time."),
    )

    # حقل واحد فقط، والترجمة تتكفّل فيها modeltranslation
    name = models.CharField(
        max_length=100,
        verbose_name=_("الاسم"),
    )

    description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("وصف"),
        help_text=_("وصف مختصر للفئة، اختياري."),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("نشطة؟"),
    )

    class Meta:
        verbose_name = _("فئة وحدة قياس")
        verbose_name_plural = _("فئات وحدات القياس")
        ordering = ("code", "id")

    def __str__(self) -> str:
        # modeltranslation سترجع القيمة المناسبة حسب اللغة الحالية
        # فإذا اللغة 'ar' سترجع name_ar، وإذا 'en' سترجع name_en
        return self.name or self.code


class UnitOfMeasure(models.Model):
    """
    Generic unit of measure used across the system.

    Examples:
    - length: m, cm, mm, km
    - weight: kg, g, ton
    - piece/unit: pcs, set, box
    - area: m2
    - volume: m3, L
    """

    category = models.ForeignKey(
        UomCategory,
        on_delete=models.PROTECT,
        related_name="units",
        verbose_name=_("فئة الوحدة"),
    )

    code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_("كود الوحدة"),
        help_text=_("مثال: M, KG, PCS, ROLL."),
    )

    # نفس الفكرة: حقل واحد فقط
    name = models.CharField(
        max_length=100,
        verbose_name=_("اسم الوحدة"),
    )

    symbol = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("الرمز"),
        help_text=_("مثال: م, كجم, pcs (اختياري)."),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("نشطة؟"),
    )

    notes = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("ملاحظات"),
        help_text=_("أي ملاحظات إضافية عن هذه الوحدة (اختياري)."),
    )

    class Meta:
        verbose_name = _("وحدة قياس")
        verbose_name_plural = _("وحدات القياس")
        ordering = ("category", "code", "id")

    def __str__(self) -> str:
        # name سيرجع المترجم حسب اللغة
        return f"{self.name} ({self.code})"
