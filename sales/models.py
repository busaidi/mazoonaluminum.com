from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from contacts.models import Contact
from core.models import NumberedModel
from inventory.models import Product


class SalesDocumentQuerySet(models.QuerySet):
    """QuerySet مخصص لمستندات المبيعات مع فلاتر جاهزة."""

    def quotations(self):
        return self.filter(kind=SalesDocument.Kind.QUOTATION)

    def orders(self):
        return self.filter(kind=SalesDocument.Kind.ORDER)

    def deliveries(self):
        return self.filter(kind=SalesDocument.Kind.DELIVERY_NOTE)

    def for_contact(self, contact: Contact | int):
        """فلتر بحسب جهة الاتصال (كائن أو id)."""
        contact_id = contact.pk if isinstance(contact, Contact) else contact
        return self.filter(contact_id=contact_id)


class SalesDocument(models.Model):
    """مستند مبيعات عام.

    يمكن أن يكون:
    - عرض سعر QUOTATION
    - طلب بيع ORDER
    - مذكرة تسليم DELIVERY_NOTE

    المنطق الخاص بالتحويل بين الأنواع (عرض → طلب → مذكرة → فاتورة)
    موجود في طبقة الخدمات (sales.services) وليس هنا، للحفاظ على
    نظافة طبقة الموديل.
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

    # ====== تعريف الحقول الأساسية ======

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
        help_text=_("مثال: عرض السعر الذي تم إنشاء هذا الطلب منه."),
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
        verbose_name=_("تاريخ الانتهاء / صلاحية العرض"),
        help_text=_("اختياري: تاريخ صلاحية عرض السعر أو تاريخ الاستحقاق."),
    )

    # ====== الحقول المالية الأساسية ======
    # يمكن حسابها تلقائياً من الأسطر عبر recompute_totals()
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

    notes = models.TextField(
        blank=True,
        verbose_name=_("ملاحظات داخلية"),
    )
    customer_notes = models.TextField(
        blank=True,
        verbose_name=_("ملاحظات تظهر للعميل في المستند"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("تاريخ الإنشاء"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("آخر تحديث"),
    )

    objects = SalesDocumentQuerySet.as_manager()

    class Meta:
        ordering = ("-date", "-id")
        verbose_name = _("مستند مبيعات")
        verbose_name_plural = _("مستندات المبيعات")

    # ====== تمثيل نصي ======

    def __str__(self) -> str:
        """تمثيل نصي قياسي للمستند."""
        contact_name = self.contact.name if self.contact else "—"
        return f"{self.display_number} - {contact_name}"

    # ====== خصائص مساعدة للـ UI ======

    @property
    def display_number(self) -> str:
        """
        رقم عرض بسيط يعتمد على نوع المستند + الـ PK بصيغة ثابتة.

        مثال:
        - QUOTATION -> Q-0005
        - ORDER -> SO-0012
        - DELIVERY_NOTE -> DN-0003
        """
        prefix_map = {
            self.Kind.QUOTATION: "Q",
            self.Kind.ORDER: "SO",
            self.Kind.DELIVERY_NOTE: "DN",
        }

        prefix = prefix_map.get(self.kind, "SD")  # SD = Sales Document افتراضي

        # قبل الحفظ ما يكون فيه pk
        if self.pk:
            return f"{prefix}-{self.pk:04d}"  # تعبئة إلى 4 أرقام
        return f"{prefix}-DRAFT"

    @property
    def is_quotation(self) -> bool:
        return self.kind == self.Kind.QUOTATION

    @property
    def is_order(self) -> bool:
        return self.kind == self.Kind.ORDER

    @property
    def is_delivery_note(self) -> bool:
        return self.kind == self.Kind.DELIVERY_NOTE

    @property
    def kind_label(self) -> str:
        """النص المعروض لنوع المستند (استخدامه في التمبلت أسهل)."""
        return self.get_kind_display()

    @property
    def status_label(self) -> str:
        return self.get_status_display()

    # ====== منطق الأعمال الخفيف على مستوى الموديل ======

    def recompute_totals(self, save: bool = True) -> None:
        """يعيد حساب الإجماليات من بنود المبيعات المرتبطة.

        هذه الدالة لا تتعامل مع الضرائب المعقدة حالياً:
        - الإجمالي قبل الضريبة = مجموع line_total
        - الضريبة = 0
        - الإجمالي النهائي = الإجمالي قبل الضريبة
        """
        agg = self.lines.aggregate(s=models.Sum("line_total"))
        total_before_tax = agg["s"] or Decimal("0.000")

        self.total_before_tax = total_before_tax
        self.total_tax = Decimal("0.000")
        self.total_amount = total_before_tax

        if save:
            self.save(
                update_fields=["total_before_tax", "total_tax", "total_amount"]
            )

    def can_be_converted_to_order(self) -> bool:
        """هل يمكن تحويل هذا المستند إلى طلب بيع؟"""
        return self.is_quotation and self.status != self.Status.CANCELLED

    def can_be_converted_to_delivery(self) -> bool:
        """هل يمكن تحويل هذا المستند إلى مذكرة تسليم؟"""
        return self.is_order and self.status not in {
            self.Status.CANCELLED,
            self.Status.DELIVERED,
        }

    def can_be_converted_to_invoice(self) -> bool:
        """هل يمكن تحويل هذا المستند إلى فاتورة؟ (يستخدم في الأزرار)."""
        return (
            self.kind in {self.Kind.ORDER, self.Kind.DELIVERY_NOTE}
            and self.status not in {self.Status.CANCELLED, self.Status.INVOICED}
        )

    # ====== URL helper ======

    def get_absolute_url(self):
        """يعيد رابط التفاصيل المناسب حسب نوع المستند."""
        from django.urls import reverse  # import داخلي لتجنب الدوائر

        if self.is_quotation:
            name = "sales:quotation_detail"
        elif self.is_order:
            name = "sales:order_detail"
        else:
            name = "sales:delivery_detail"

        return reverse(name, kwargs={"pk": self.pk})


class SalesLine(models.Model):
    """بند مبيعات (سطر) مرتبط بمستند مبيعات واحد."""

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

    def __str__(self) -> str:  # pragma: no cover - تمثيل نصي بسيط
        return f"{self.document} - {self.display_name}"

    @property
    def display_name(self) -> str:
        """اسم مناسب للعرض في الجداول والتقارير."""
        if self.description:
            return self.description
        if self.product_id:
            return self.product.name
        return f"Line #{self.pk}"

    def compute_line_total(self) -> Decimal:
        """حساب إجمالي السطر مع أخذ الخصم في الاعتبار."""
        qty = self.quantity or Decimal("0")
        price = self.unit_price or Decimal("0")
        base = qty * price

        if self.discount_percent:
            return base * (Decimal("1.00") - self.discount_percent / Decimal("100"))

        return base

    def save(self, *args, **kwargs):
        """حساب line_total تلقائياً في كل عملية حفظ."""
        self.line_total = self.compute_line_total()
        super().save(*args, **kwargs)
