from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from contacts.models import Contact
from core.models import NumberedModel
from inventory.models import Product


class SalesDocumentQuerySet(models.QuerySet):
    def quotations(self):
        return self.filter(kind=SalesDocument.Kind.QUOTATION)

    def orders(self):
        return self.filter(kind=SalesDocument.Kind.ORDER)

    def deliveries(self):
        return self.filter(kind=SalesDocument.Kind.DELIVERY_NOTE)


class SalesDocument(NumberedModel):
    """
    مستند مبيعات عام:
    - يمكن أن يكون عرض سعر QUOTATION
    - أو طلب بيع ORDER
    - أو مذكرة تسليم DELIVERY_NOTE
    """

    class Kind(models.TextChoices):
        QUOTATION = "quotation", _("عرض سعر")
        ORDER = "order", _("طلب بيع")
        DELIVERY_NOTE = "delivery_note", _("مذكرة تسليم")

    class Status(models.TextChoices):
        DRAFT = "draft", _("مسودة")
        SENT = "sent", _("تم الإرسال")
        CONFIRMED = "confirmed", _("مؤكد")
        DELIVERED = "delivered", _("تم التسليم")
        CANCELLED = "cancelled", _("ملغي")
        INVOICED = "invoiced", _("مفوتر")

    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        default=Kind.QUOTATION,
        verbose_name=_("نوع المستند"),
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name=_("الحالة"),
    )
    source_document = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_documents",
        verbose_name=_("المستند الأصلي"),
        help_text=_("مثال: عرض السعر الذي تم إنشاء هذا الطلب منه."),
    )

    contact = models.ForeignKey(
        Contact,
        on_delete=models.PROTECT,
        related_name="sales_documents",
        verbose_name=_("العميل / جهة الاتصال"),
    )

    date = models.DateField(default=timezone.localdate, verbose_name=_("التاريخ"))
    due_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("تاريخ الانتهاء / صلاحية العرض"),
        help_text=_("اختياري: تاريخ صلاحية عرض السعر أو تاريخ الاستحقاق."),
    )

    # الحقول المالية الأساسية (ممكن تحسب تلقائياً من الأسطر)
    total_before_tax = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal("0.000"),
        verbose_name=_("الإجمالي قبل الضريبة"),
    )
    total_tax = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal("0.000"),
        verbose_name=_("إجمالي الضريبة"),
    )
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal("0.000"),
        verbose_name=_("الإجمالي النهائي"),
    )

    currency = models.CharField(
        max_length=3,
        default="OMR",
        verbose_name=_("العملة"),
    )

    notes = models.TextField(blank=True, verbose_name=_("ملاحظات داخلية"))
    customer_notes = models.TextField(
        blank=True,
        verbose_name=_("ملاحظات تظهر للعميل في المستند"),
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("تاريخ الإنشاء"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("آخر تحديث"))

    objects = SalesDocumentQuerySet.as_manager()

    class Meta:
        ordering = ("-date", "-id")
        verbose_name = _("مستند مبيعات")
        verbose_name_plural = _("مستندات المبيعات")

    def __str__(self) -> str:
        label = self.number or f"#{self.pk}"
        return f"{self.get_kind_display()} {label} - {self.contact.name}"

    # ====== خصائص مساعدة للـ UI ======
    @property
    def is_quotation(self) -> bool:
        return self.kind == self.Kind.QUOTATION

    @property
    def is_order(self) -> bool:
        return self.kind == self.Kind.ORDER

    @property
    def is_delivery_note(self) -> bool:
        return self.kind == self.Kind.DELIVERY_NOTE

    # هنا لاحقاً نضيف منطق التحويل:
    # - من عرض سعر → طلب
    # - من طلب → مذكرة تسليم
    # - ومن طلب/مذكرة → فاتورة


class SalesLine(models.Model):
    """
    سطر بنود لمستند المبيعات (عرض سعر/طلب/مذكرة تسليم).
    """

    document = models.ForeignKey(
        SalesDocument,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("المستند"),
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sales_lines",
        verbose_name=_("المنتج"),
    )

    description = models.CharField(
        max_length=255,
        verbose_name=_("الوصف"),
        help_text=_("يمكن تركه فارغاً ليتم استخدام اسم المنتج."),
        blank=True,
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("1.000"),
        verbose_name=_("الكمية"),
    )

    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("0.000"),
        verbose_name=_("سعر الوحدة"),
    )

    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name=_("نسبة الخصم"),
        help_text=_("بالنسبة المئوية %"),
    )

    line_total = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal("0.000"),
        verbose_name=_("الإجمالي للسطر"),
    )

    class Meta:
        ordering = ("id",)
        verbose_name = _("بند مبيعات")
        verbose_name_plural = _("بنود المبيعات")

    def __str__(self) -> str:
        return f"{self.document} - {self.display_name}"

    @property
    def display_name(self) -> str:
        if self.description:
            return self.description
        if self.product_id:
            return self.product.name
        return f"Line #{self.pk}"

    def compute_line_total(self) -> Decimal:
        base = (self.quantity or 0) * (self.unit_price or 0)
        if self.discount_percent:
            return base * (Decimal("1.00") - self.discount_percent / Decimal("100"))
        return base

    def save(self, *args, **kwargs):
        # نحسب إجمالي السطر تلقائياً
        self.line_total = self.compute_line_total()
        super().save(*args, **kwargs)
