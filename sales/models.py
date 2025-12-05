# sales/models.py
from decimal import Decimal, InvalidOperation

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# تأكد من أن التطبيقات التالية موجودة لديك
from contacts.models import Contact
from inventory.models import Product
from uom.models import UnitOfMeasure

from core.models.base import BaseModel, TimeStampedModel, UserStampedModel

# سنفترض أن ملف المدراء managers.py موجود في نفس المجلد
from .managers import (
    SalesDocumentManager,
    SalesLineManager,
    DeliveryNoteManager,
    DeliveryLineManager,
)

# ثوابت للأرقام العشرية لتفادي تكرار القيم النصية وحسابات دقيقة
DECIMAL_ZERO = Decimal("0.000")
DECIMAL_ONE = Decimal("1.000")
DECIMAL_HUNDRED = Decimal("100.00")


# ===================================================================
# نموذج مستند المبيعات (Quotation / Sales Order)
# ===================================================================

class SalesDocument(BaseModel):
    """
    مستند مبيعات موحد يمكن أن يكون:
    - عرض سعر (QUOTATION)
    - أمر بيع (ORDER)

    نفس السجل يمكن أن يتحول من عرض سعر إلى أمر بيع بتغيير الـ kind.
    """

    class Kind(models.TextChoices):
        QUOTATION = "quotation", _("عرض سعر")
        ORDER = "order", _("أمر بيع")

    class Status(models.TextChoices):
        DRAFT = "draft", _("مسودة")
        CONFIRMED = "confirmed", _("مؤكد")
        CANCELLED = "cancelled", _("ملغي")

    # ========== الحقول الأساسية ==========

    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        default=Kind.QUOTATION,
        verbose_name=_("نوع المستند"),
        db_index=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name=_("الحالة"),
        db_index=True,
    )

    # هذا الحقل مفيد لربط المستندات ببعضها (مثلاً نسخة من عرض سعر سابق)
    source_document = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_documents",
        verbose_name=_("المستند الأصلي"),
    )

    contact = models.ForeignKey(
        Contact,
        on_delete=models.PROTECT,
        related_name="sales_documents",
        verbose_name=_("العميل / جهة الاتصال"),
    )

    # مرجع العميل (رقم أمر الشراء PO الخاص بالعميل) - مهم جداً للشركات
    client_reference = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("مرجع العميل / رقم طلب الشراء"),
        help_text=_("رقم الإشارة الخاص بالعميل (PO Ref)."),
    )

    date = models.DateField(
        default=timezone.localdate,
        verbose_name=_("التاريخ"),
        db_index=True,
    )

    due_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("تاريخ الانتهاء / الصلاحية"),
    )

    # ========== المبالغ المالية ==========

    total_before_tax = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("الإجمالي قبل الضريبة"),
    )

    total_tax = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("إجمالي الضريبة"),
    )

    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("الإجمالي النهائي"),
    )

    currency = models.CharField(
        max_length=3,
        default="OMR",
        verbose_name=_("العملة"),
    )

    # ========== حالة الفوترة والتسليم ==========

    is_invoiced = models.BooleanField(
        default=False,
        verbose_name=_("مفوتر بالكامل"),
    )

    # ========== ملاحظات ==========

    notes = models.TextField(
        blank=True,
        verbose_name=_("ملاحظات داخلية"),
        help_text=_("ملاحظات لا تظهر للعميل.")
    )

    customer_notes = models.TextField(
        blank=True,
        verbose_name=_("ملاحظات للعميل"),
        help_text=_("تظهر في الطباعة للعميل (مثل شروط الدفع).")
    )

    # ========== Managers ==========

    objects = SalesDocumentManager()

    class Meta:
        ordering = ("-date", "-id")
        verbose_name = _("مستند مبيعات")
        verbose_name_plural = _("مستندات المبيعات")

    # ========== خصائص العرض والمنطق ==========

    def __str__(self) -> str:
        contact_name = getattr(self.contact, "name", "—")
        return f"{self.display_number} - {contact_name}"

    @property
    def display_number(self) -> str:
        """رقم العرض للمستخدم"""
        prefix = "SO"
        if self.is_quotation:
            prefix = "QN"  # Quotation Number

        if self.pk:
            return f"{prefix}-{self.pk:04d}"
        return f"{prefix}-DRAFT"

    @property
    def is_quotation(self) -> bool:
        return self.kind == self.Kind.QUOTATION

    @property
    def is_order(self) -> bool:
        return self.kind == self.Kind.ORDER

    @property
    def is_cancelled(self) -> bool:
        return self.status == self.Status.CANCELLED

    # ========== العمليات الحسابية ==========

    def recompute_totals(self, save: bool = True) -> None:
        """
        إعادة احتساب إجماليات المستند بناءً على البنود.
        """
        agg = self.lines.aggregate(s=models.Sum("line_total"))
        total = agg.get("s") or DECIMAL_ZERO

        self.total_before_tax = total
        # هنا يمكن إضافة منطق الضرائب لاحقاً
        self.total_tax = DECIMAL_ZERO
        self.total_amount = total + self.total_tax

        if save:
            self.save(
                update_fields=[
                    "total_before_tax",
                    "total_tax",
                    "total_amount",
                ]
            )

    # ========== التحقق من الصلاحيات ==========
    def can_be_converted_to_order(self) -> bool:
        return self.is_quotation and not self.is_cancelled

    def can_be_converted_to_invoice(self) -> bool:
        return self.is_order and not self.is_cancelled and not self.is_invoiced

    def get_absolute_url(self):
        from django.urls import reverse
        # تأكد من أن الـ URL name صحيح في ملف urls.py
        return reverse("sales:document_detail", kwargs={"pk": self.pk})


# ===================================================================
# نموذج بند المبيعات (Sales Line)
# ===================================================================

class SalesLine(TimeStampedModel, UserStampedModel):
    """
    بند (سطر) داخل مستند المبيعات.
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
        blank=True,
        verbose_name=_("الوصف"),
        help_text=_("يُستخدم اسم المنتج تلقائيًا إذا تُرِك فارغًا."),
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ONE,
        verbose_name=_("الكمية"),
    )

    uom = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        verbose_name=_("وحدة القياس"),
        null=True,
        blank=True,
    )

    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("سعر الوحدة"),
    )

    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name=_("نسبة الخصم %"),
    )

    line_total = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("إجمالي السطر"),
        help_text=_("الكمية × السعر - الخصم"),
    )

    objects = SalesLineManager()

    class Meta:
        ordering = ("id",)
        verbose_name = _("بند مبيعات")
        verbose_name_plural = _("بنود المبيعات")

    def __str__(self) -> str:
        return f"{self.document.display_number} - {self.display_name}"

    @property
    def display_name(self) -> str:
        if self.description:
            return self.description
        if self.product:
            return self.product.name
        return f"Line #{self.pk}"

    def compute_line_total(self) -> Decimal:
        """
        حساب القيمة الإجمالية للسطر
        """

        def to_decimal(value, default="0"):
            if value in (None, ""):
                return Decimal(default)
            try:
                return Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                return Decimal(default)

        qty = to_decimal(self.quantity, "0")
        price = to_decimal(self.unit_price, "0")
        discount = to_decimal(self.discount_percent, "0")

        base = qty * price

        if discount > 0:
            # معادلة الخصم: السعر الأصلي * (100 - نسبة الخصم) / 100
            base = base * (Decimal("100") - discount) / Decimal("100")

        return base.quantize(Decimal("0.000"))

    def save(self, *args, **kwargs) -> None:
        self.line_total = self.compute_line_total()
        super().save(*args, **kwargs)
        # تحديث إجمالي المستند الأب
        if self.document_id:
            self.document.recompute_totals(save=True)


# ===================================================================
# نموذج مذكرة التسليم (Delivery Note)
# ===================================================================

class DeliveryNote(BaseModel):
    """
    مذكرة تسليم بضاعة للعميل.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", _("مسودة")
        CONFIRMED = "confirmed", _("مؤكد / تم التسليم")
        CANCELLED = "cancelled", _("ملغي")

    contact = models.ForeignKey(
        Contact,
        on_delete=models.PROTECT,
        related_name="delivery_notes",
        verbose_name=_("العميل"),
        null=True,
        blank=True,
    )

    order = models.ForeignKey(
        SalesDocument,
        on_delete=models.PROTECT,
        related_name="delivery_notes",
        limit_choices_to={"kind": SalesDocument.Kind.ORDER},
        verbose_name=_("أمر البيع المرتبط"),
        null=True,
        blank=True,
    )

    date = models.DateField(
        default=timezone.localdate,
        verbose_name=_("تاريخ التسليم"),
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name=_("الحالة"),
    )

    notes = models.TextField(
        blank=True,
        verbose_name=_("ملاحظات"),
    )

    objects = DeliveryNoteManager()

    class Meta:
        ordering = ("-date", "-id")
        verbose_name = _("مذكرة تسليم")
        verbose_name_plural = _("مذكرات التسليم")

    def __str__(self) -> str:
        return f"{self.display_number} – {self.contact_name}"

    @property
    def display_number(self) -> str:
        if self.pk:
            return f"DN-{self.pk:04d}"
        return "DN-DRAFT"

    @property
    def is_confirmed(self) -> bool:
        return self.status == self.Status.CONFIRMED

    @property
    def effective_contact(self):
        """إرجاع العميل سواء تم تحديده هنا أو في أمر البيع المرتبط"""
        if self.contact:
            return self.contact
        if self.order and getattr(self.order, "contact", None):
            return self.order.contact
        return None

    @property
    def contact_name(self) -> str:
        contact = self.effective_contact
        return getattr(contact, "name", "—")


# ===================================================================
# نموذج بند التسليم (Delivery Line)
# ===================================================================

class DeliveryLine(TimeStampedModel, UserStampedModel):
    """
    سطر داخل مذكرة التسليم.
    """

    delivery = models.ForeignKey(
        DeliveryNote,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("مذكرة التسليم"),
    )

    # تحسين: ربط سطر التسليم بسطر أمر البيع لمعرفة ما تم تسليمه بالضبط
    sales_line = models.ForeignKey(
        SalesLine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_lines",
        verbose_name=_("بند أمر البيع"),
        help_text=_("السطر المرتبط في أمر البيع (لحساب الكميات المتبقية)."),
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="delivery_lines",
        verbose_name=_("المنتج"),
    )

    description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("الوصف"),
    )

    uom = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        verbose_name=_("وحدة القياس"),
        null=True,
        blank=True,
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ONE,
        verbose_name=_("الكمية المسلّمة"),
    )

    objects = DeliveryLineManager()

    class Meta:
        ordering = ("id",)
        verbose_name = _("بند تسليم")
        verbose_name_plural = _("بنود التسليم")

    def __str__(self) -> str:
        return f"{self.delivery.display_number} – {self.display_name}"

    @property
    def display_name(self) -> str:
        if self.description:
            return self.description
        if self.product:
            return self.product.name
        return f"Line #{self.pk}"

    def save(self, *args, **kwargs):
        # منطق اختياري: إذا تم تحديد سطر مبيعات ولم يتم تحديد المنتج، ننسخه من سطر المبيعات
        if self.sales_line and not self.product:
            self.product = self.sales_line.product

        # إذا لم يتم تحديد وحدة القياس، ننسخها من المنتج أو سطر المبيعات
        if not self.uom:
            if self.sales_line and self.sales_line.uom:
                self.uom = self.sales_line.uom
            # هنا يمكنك إضافة شرط لجلب وحدة القياس الافتراضية للمنتج إذا وجدت

        super().save(*args, **kwargs)