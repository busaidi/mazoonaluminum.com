from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from contacts.models import Contact
from inventory.models import Product

from core.models.base import BaseModel, TimeStampedModel, UserStampedModel
from .managers import SalesDocumentManager, SalesLineManager, DeliveryNoteManager, DeliveryLineManager


# ===================================================================
# SalesDocument
# ===================================================================


class SalesDocument(BaseModel):
    """
    مستند مبيعات:
    - عرض سعر
    - أمر بيع

    نفس السجل يمكن أن يتحول من عرض إلى أمر بدون إنشاء وثيقة جديدة.

    يرث من BaseModel:
    - public_id (UUID)
    - created_at / updated_at
    - created_by / updated_by
    - is_deleted / deleted_at / deleted_by
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

    source_document = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_documents",
        verbose_name=_("المستند الأصلي"),
        help_text=_("يُستخدم لاحقاً للتسليم أو النسخ."),
    )

    contact = models.ForeignKey(
        Contact,
        on_delete=models.PROTECT,
        related_name="sales_documents",
        verbose_name=_("العميل / جهة الاتصال"),
    )

    date = models.DateField(
        default=timezone.localdate,
        verbose_name=_("التاريخ"),
        db_index=True,
    )

    due_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("تاريخ الانتهاء"),
    )

    # ========== المبالغ ==========

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

    # ========== فوترة أمر البيع ==========

    is_invoiced = models.BooleanField(
        default=False,
        verbose_name=_("مفوتر"),
        help_text=_("يشير إلى أن أمر البيع تم فوترته."),
    )

    # ========== ملاحظات ==========

    notes = models.TextField(
        blank=True,
        verbose_name=_("ملاحظات داخلية"),
    )

    customer_notes = models.TextField(
        blank=True,
        verbose_name=_("ملاحظات للعميل"),
    )

    # ========== Manager ==========

    objects = SalesDocumentManager()

    class Meta:
        ordering = ("-date", "-id")
        verbose_name = _("مستند مبيعات")
        verbose_name_plural = _("مستندات المبيعات")

    # ========== تمثيل وخصائص مساعدة للـ UI ==========

    def __str__(self):
        contact_name = getattr(self.contact, "name", "—")
        return f"{self.display_number} - {contact_name}"

    @property
    def display_number(self) -> str:
        """
        رقم موحّد لجميع مستندات المبيعات.
        مثال: SO-0009
        """
        prefix = "SO"  # رقم موحّد لكل المستندات
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

    # ========== المنطق البسيط ==========

    def recompute_totals(self, save: bool = True):
        """
        إعادة احتساب إجماليات المستند بناءً على بنوده.
        """
        agg = self.lines.aggregate(s=models.Sum("line_total"))
        total = agg["s"] or Decimal("0.000")

        self.total_before_tax = total
        self.total_tax = Decimal("0.000")
        self.total_amount = total

        if save:
            self.save(update_fields=["total_before_tax", "total_tax", "total_amount"])

    def can_be_converted_to_order(self) -> bool:
        return self.is_quotation and not self.is_cancelled

    def can_be_converted_to_invoice(self) -> bool:
        return self.is_order and not self.is_cancelled and not self.is_invoiced

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("sales:sales_detail", kwargs={"pk": self.pk})


# ===================================================================
# SalesLine
# ===================================================================


class SalesLine(TimeStampedModel, UserStampedModel):
    """
    بند مبيعات مرتبط بمستند واحد.

    يرث:
    - created_at / updated_at
    - created_by / updated_by
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
        help_text=_("يُستخدم اسم المنتج إذا تُرك فارغًا."),
        verbose_name=_("الوصف"),
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
    )

    line_total = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal("0.000"),
        verbose_name=_("إجمالي السطر"),
    )

    objects = SalesLineManager()

    class Meta:
        ordering = ("id",)
        verbose_name = _("بند مبيعات")
        verbose_name_plural = _("بنود المبيعات")

    def __str__(self):
        return f"{self.document.display_number} - {self.display_name}"

    @property
    def display_name(self):
        if self.description:
            return self.description
        if self.product:
            return self.product.name
        return f"Line #{self.pk}"

    def compute_line_total(self) -> Decimal:
        """
        يحسب إجمالي السطر مع الخصم.
        لا يغيّر السطر نفسه، فقط يرجع القيمة.
        """
        qty = self.quantity or Decimal("0")
        price = self.unit_price or Decimal("0")
        base = qty * price

        if self.discount_percent:
            discount_factor = Decimal("1.00") - (self.discount_percent / Decimal("100"))
            total = base * discount_factor
        else:
            total = base

        # تأكد أنه ما يصير رقم سالب بالغلط (لو دخل خصم أكبر من 100%)
        if total < Decimal("0"):
            total = Decimal("0.000")

        # نرجعه بثلاث خانات (نفس الحقل)
        return total.quantize(Decimal("0.001"))

    def save(self, *args, **kwargs):
        """
        قبل الحفظ نحسب إجمالي السطر،
        وبعد الحفظ نعيد حساب إجمالي المستند.
        """
        self.line_total = self.compute_line_total()
        super().save(*args, **kwargs)

        if self.document_id:
            self.document.recompute_totals(save=True)


# ===================================================================
# DeliveryNote
# ===================================================================


class DeliveryNote(BaseModel):
    """
    مذكرة تسليم مرتبطة بأمر بيع واحد.
    يمكن أن يكون لأمر البيع عدة مذكرات.

    يرث من BaseModel:
    - public_id
    - created_at / updated_at
    - created_by / updated_by
    - soft delete
    """

    class Status(models.TextChoices):
        DRAFT = "draft", _("مسودة")
        CONFIRMED = "confirmed", _("مؤكد")
        CANCELLED = "cancelled", _("ملغي")

    order = models.ForeignKey(
        SalesDocument,
        on_delete=models.PROTECT,
        related_name="delivery_notes",
        limit_choices_to={"kind": SalesDocument.Kind.ORDER},
        verbose_name=_("أمر البيع"),
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

    def __str__(self):
        return f"{self.display_number} – {self.order.display_number}"

    @property
    def display_number(self) -> str:
        """
        رقم بسيط مثل:
        DN-0003
        """
        if self.pk:
            return f"DN-{self.pk:04d}"
        return "DN-DRAFT"

    @property
    def is_confirmed(self) -> bool:
        return self.status == self.Status.CONFIRMED


# ===================================================================
# DeliveryLine
# ===================================================================


class DeliveryLine(TimeStampedModel, UserStampedModel):
    """
    بند تسليم بسيط ضمن مذكرة تسليم.
    (بدون ربط إلزامي بسطر أمر البيع حالياً)

    يرث:
    - created_at / updated_at
    - created_by / updated_by
    """

    delivery = models.ForeignKey(
        DeliveryNote,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("مذكرة التسليم"),
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
        help_text=_("يُستخدم اسم المنتج إذا تُرك فارغًا."),
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("1.000"),
        verbose_name=_("الكمية المسلّمة"),
    )

    objects = DeliveryLineManager()

    class Meta:
        ordering = ("id",)
        verbose_name = _("بند تسليم")
        verbose_name_plural = _("بنود التسليم")

    def __str__(self):
        name = self.description or (self.product.name if self.product else "—")
        return f"{self.delivery.display_number} – {name}"

    @property
    def display_name(self):
        if self.description:
            return self.description
        if self.product:
            return self.product.name
        return f"Line #{self.pk}"
