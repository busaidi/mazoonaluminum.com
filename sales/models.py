# sales/models.py
from decimal import Decimal, InvalidOperation

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

# تأكد من أن التطبيقات التالية موجودة لديك
from contacts.models import Contact
from inventory.models import Product
from uom.models import UnitOfMeasure

from core.models.base import BaseModel, TimeStampedModel, UserStampedModel
from .managers import (
    SalesDocumentManager,
    SalesLineManager,
    DeliveryNoteManager,
    DeliveryLineManager,
)

# ثوابت دقيقة للأرقام المالية
DECIMAL_ZERO = Decimal("0.000")
DECIMAL_ONE = Decimal("1.000")


# ===================================================================
# نموذج مستند المبيعات (Unified Sales Document)
# ===================================================================

class SalesDocument(BaseModel):
    """
    مستند مبيعات موحد.
    - الدورة: DRAFT -> SENT -> CONFIRMED (يصبح أمر بيع) -> [DELIVERY]
    """

    class Status(models.TextChoices):
        DRAFT = "draft", _("عرض سعر (مسودة)")
        SENT = "sent", _("عرض سعر (مرسل)")
        CONFIRMED = "confirmed", _("أمر بيع (مؤكد)")
        CANCELLED = "cancelled", _("ملغي")

    class DeliveryStatus(models.TextChoices):
        PENDING = "pending", _("قيد الانتظار")
        PARTIAL = "partial", _("تسليم جزئي")
        DELIVERED = "delivered", _("تم التسليم")

    # ========== الحقول الأساسية ==========

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name=_("الحالة"),
        db_index=True,
    )

    contact = models.ForeignKey(
        Contact,
        on_delete=models.PROTECT,
        related_name="sales_documents",
        verbose_name=_("العميل"),
    )

    client_reference = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("مرجع العميل (PO)"),
        help_text=_("رقم الإشارة الخاص بالعميل أو رقم أمر الشراء.")
    )

    date = models.DateField(
        default=timezone.localdate,
        verbose_name=_("التاريخ"),
        db_index=True,
    )

    due_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("تاريخ الانتهاء/الصلاحية"),
    )

    # ========== العناوين ==========

    shipping_address = models.TextField(
        blank=True,
        verbose_name=_("عنوان الشحن"),
    )

    billing_address = models.TextField(
        blank=True,
        verbose_name=_("عنوان الفوترة"),
    )

    # ========== المبالغ المالية ==========

    total_before_tax = models.DecimalField(
        max_digits=14, decimal_places=3, default=DECIMAL_ZERO, verbose_name=_("الإجمالي قبل الضريبة")
    )
    total_tax = models.DecimalField(
        max_digits=14, decimal_places=3, default=DECIMAL_ZERO, verbose_name=_("إجمالي الضريبة")
    )
    total_amount = models.DecimalField(
        max_digits=14, decimal_places=3, default=DECIMAL_ZERO, verbose_name=_("الإجمالي النهائي")
    )
    currency = models.CharField(max_length=3, default="OMR", verbose_name=_("العملة"))

    # ========== حالة الفوترة والتسليم ==========

    is_invoiced = models.BooleanField(default=False, verbose_name=_("مفوتر بالكامل"))

    delivery_status = models.CharField(
        max_length=20,
        default=DeliveryStatus.PENDING,
        choices=DeliveryStatus.choices,
        verbose_name=_("حالة التسليم"),
    )

    # ========== ملاحظات ==========

    notes = models.TextField(blank=True, verbose_name=_("ملاحظات داخلية"))
    customer_notes = models.TextField(blank=True, verbose_name=_("ملاحظات للعميل"))

    objects = SalesDocumentManager()

    class Meta:
        ordering = ("-date", "-id")
        verbose_name = _("مستند مبيعات")
        verbose_name_plural = _("مستندات المبيعات")

    def __str__(self) -> str:
        return f"{self.display_number} - {self.contact}"

    # ========== المنطق والتحقق (Validation) ==========

    def clean(self):
        """قواعد التحقق لضمان سلامة البيانات"""
        # القاعدة: لا يمكن إلغاء الطلب إذا كان هناك تسليمات مؤكدة مرتبطة به
        if self.status == self.Status.CANCELLED and self.pk:
            has_confirmed_deliveries = self.delivery_notes.filter(status=DeliveryNote.Status.CONFIRMED).exists()
            if has_confirmed_deliveries:
                raise ValidationError(
                    _("لا يمكن إلغاء أمر البيع لأنه يحتوي على عمليات تسليم مؤكدة. قم بإلغاء التسليم أولاً.")
                )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    # ========== الخصائص (Properties) ==========

    @property
    def is_quotation(self) -> bool:
        """يعتبر عرض سعر طالما لم يتم تأكيده"""
        return self.status in [self.Status.DRAFT, self.Status.SENT]

    @property
    def is_order(self) -> bool:
        """يعتبر أمر بيع عند التأكيد"""
        return self.status == self.Status.CONFIRMED

    @property
    def display_number(self) -> str:
        """
        تغيير البادئة بناءً على الحالة:
        QN = Quotation
        SO = Sales Order
        """
        prefix = "QN" if self.is_quotation else "SO"

        if not self.pk:
            return f"{prefix}-NEW"

        return f"{prefix}-{self.pk:04d}"

    def recompute_totals(self, save: bool = True) -> None:
        """إعادة احتساب إجمالي المستند بناءً على السطور"""
        agg = self.lines.aggregate(s=models.Sum("line_total"))
        total = agg.get("s") or DECIMAL_ZERO

        self.total_before_tax = total
        self.total_tax = DECIMAL_ZERO  # (يمكن إضافة منطق الضرائب هنا مستقبلاً)
        self.total_amount = total + self.total_tax

        if save:
            self.save(update_fields=["total_before_tax", "total_tax", "total_amount"])


# ===================================================================
# نموذج بند المبيعات (Sales Line)
# ===================================================================

class SalesLine(TimeStampedModel, UserStampedModel):
    document = models.ForeignKey(SalesDocument, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, blank=True)
    description = models.CharField(max_length=255, blank=True)

    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=DECIMAL_ONE)
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, null=True, blank=True)

    unit_price = models.DecimalField(max_digits=12, decimal_places=3, default=DECIMAL_ZERO)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))

    line_total = models.DecimalField(max_digits=14, decimal_places=3, default=DECIMAL_ZERO)

    objects = SalesLineManager()

    class Meta:
        ordering = ("id",)
        verbose_name = _("بند مبيعات")

    def __str__(self) -> str:
        return f"{self.document.display_number} - {self.product or self.description}"

    def compute_line_total(self) -> Decimal:
        qty = self.quantity or DECIMAL_ZERO
        price = self.unit_price or DECIMAL_ZERO
        discount = self.discount_percent or DECIMAL_ZERO

        base = qty * price
        if discount > 0:
            base = base * (Decimal("100") - discount) / Decimal("100")

        return base.quantize(Decimal("0.000"))

    @property
    def delivered_quantity(self) -> Decimal:
        """الكمية التي تم تسليمها بالفعل (من مذكرات التسليم المؤكدة)"""
        total_delivered = self.delivery_lines.filter(
            delivery__status=DeliveryNote.Status.CONFIRMED
        ).aggregate(sum_qty=models.Sum('quantity'))['sum_qty'] or DECIMAL_ZERO
        return total_delivered

    @property
    def remaining_quantity(self) -> Decimal:
        return self.quantity - self.delivered_quantity

    def save(self, *args, **kwargs) -> None:
        self.line_total = self.compute_line_total()
        super().save(*args, **kwargs)
        # تحديث إجمالي المستند عند حفظ السطر
        if self.document_id:
            self.document.recompute_totals(save=True)


# ===================================================================
# نموذج مذكرة التسليم (Delivery Note)
# ===================================================================

class DeliveryNote(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("مسودة")
        CONFIRMED = "confirmed", _("مؤكد / تم التسليم")
        CANCELLED = "cancelled", _("ملغي")

    contact = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name="delivery_notes", null=True, blank=True)

    order = models.ForeignKey(
        SalesDocument,
        on_delete=models.PROTECT,
        related_name="delivery_notes",
        limit_choices_to={"status": SalesDocument.Status.CONFIRMED},
        verbose_name=_("أمر البيع"),
        null=True,  # للسماح بالتسليم المباشر
        blank=True,
    )

    date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)

    objects = DeliveryNoteManager()

    class Meta:
        ordering = ("-date", "-id")
        verbose_name = _("مذكرة تسليم")

    def __str__(self) -> str:
        return f"{self.display_number}"

    @property
    def display_number(self) -> str:
        return f"DN-{self.pk:04d}" if self.pk else "DN-DRAFT"

    def clean(self):
        """التحقق من البيانات"""
        # (إصلاح هام): التحقق من وجود Order قبل فحص حالته
        if self.status == self.Status.CONFIRMED and self.order:
            if self.order.status == SalesDocument.Status.CANCELLED:
                raise ValidationError(_("لا يمكن تأكيد التسليم لأمر بيع ملغي."))


# ===================================================================
# نموذج بند التسليم (Delivery Line)
# ===================================================================

class DeliveryLine(TimeStampedModel, UserStampedModel):
    delivery = models.ForeignKey(DeliveryNote, on_delete=models.CASCADE, related_name="lines")

    sales_line = models.ForeignKey(
        SalesLine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_lines",
        verbose_name=_("بند الطلب")
    )

    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, blank=True)
    description = models.CharField(max_length=255, blank=True)
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, null=True, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=DECIMAL_ONE)

    objects = DeliveryLineManager()

    class Meta:
        ordering = ("id",)
        verbose_name = _("بند تسليم")

    def save(self, *args, **kwargs):
        # نسخ البيانات من سطر المبيعات إذا وجدت ولم يتم تحديدها يدوياً
        if self.sales_line:
            if not self.product:
                self.product = self.sales_line.product
            if not self.uom:
                self.uom = self.sales_line.uom

        super().save(*args, **kwargs)