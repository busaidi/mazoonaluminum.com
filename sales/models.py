# sales/models.py
from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from contacts.models import Contact
from inventory.models import Product

from core.models.base import BaseModel, TimeStampedModel, UserStampedModel
from uom.models import UnitOfMeasure
from .managers import (
    SalesDocumentManager,
    SalesLineManager,
    DeliveryNoteManager,
    DeliveryLineManager,
)

# ثوابت للأرقام العشرية لتفادي تكرار القيم النصية
DECIMAL_ZERO = Decimal("0.000")
DECIMAL_ONE = Decimal("1.000")
DECIMAL_HUNDRED = Decimal("100.00")


# ===================================================================
# نموذج مستند المبيعات
# ===================================================================


class SalesDocument(BaseModel):
    """
    مستند مبيعات واحد يمكن أن يكون:
    - عرض سعر (QUOTATION)
    - أمر بيع (ORDER)

    نفس السجل يمكن أن يتحول من عرض سعر إلى أمر بيع
    بدون إنشاء مستند جديد.

    يرث من BaseModel:
    - public_id
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
        help_text=_("يُستخدم لاحقًا للربط مع مستندات أخرى مثل التسليم أو النسخ."),
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

    # ========== فوترة أمر البيع ==========

    is_invoiced = models.BooleanField(
        default=False,
        verbose_name=_("مفوتر"),
        help_text=_("يشير إلى أن أمر البيع تم فوترته بالكامل."),
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

    def __str__(self) -> str:
        contact_name = getattr(self.contact, "name", "—")
        return f"{self.display_number} - {contact_name}"

    @property
    def display_number(self) -> str:
        """
        رقم موحّد لجميع مستندات المبيعات.
        مثال: SO-0009
        """
        prefix = "SO"  # رقم موحّد لكل مستندات المبيعات
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

    # ========== منطق احتساب الإجماليات ==========

    def recompute_totals(self, save: bool = True) -> None:
        """
        إعادة احتساب إجماليات المستند بناءً على بنوده.
        - يتم جمع line_total من جميع البنود.
        - حالياً الضريبة = 0 (سيتم دعم الضريبة لاحقاً).
        """
        agg = self.lines.aggregate(s=models.Sum("line_total"))
        total = agg.get("s") or DECIMAL_ZERO

        self.total_before_tax = total
        self.total_tax = DECIMAL_ZERO
        self.total_amount = total

        if save:
            self.save(
                update_fields=[
                    "total_before_tax",
                    "total_tax",
                    "total_amount",
                ]
            )

    # ========== صلاحيات التحويل ==========
    def can_be_converted_to_order(self) -> bool:
        """
        يمكن التحويل إلى أمر بيع إذا كان المستند عرض سعر وغير ملغي.
        """
        return self.is_quotation and not self.is_cancelled

    def can_be_converted_to_invoice(self) -> bool:
        """
        يمكن التحويل إلى فاتورة إذا كان المستند أمر بيع، وغير ملغي،
        ولم يتم فوترته مسبقاً.
        """
        return self.is_order and not self.is_cancelled and not self.is_invoiced

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("sales:sales_detail", kwargs={"pk": self.pk})


# ===================================================================
# نموذج بند المبيعات
# ===================================================================


class SalesLine(TimeStampedModel, UserStampedModel):
    """
    بند مبيعات مرتبط بمستند مبيعات واحد.

    يرث من:
    - TimeStampedModel  → created_at / updated_at
    - UserStampedModel  → created_by / updated_by
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
        help_text=_("يُستخدم اسم المنتج تلقائيًا إذا تُرك هذا الحقل فارغًا."),
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
        help_text=_("الوحدة المستخدمة في هذا السطر (أساسية أو بديلة)."),
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
        verbose_name=_("نسبة الخصم"),
    )

    line_total = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("إجمالي السطر"),
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
        """
        اسم البند كما يظهر في القوائم:
        - الوصف إن وجد
        - وإلا اسم المنتج
        - وإلا نص افتراضي "سطر #"
        """
        if self.description:
            return self.description
        if self.product:
            return self.product.name
        if self.pk:
            return f"سطر #{self.pk}"
        return "سطر جديد"

    def compute_line_total(self) -> Decimal:
        """
        يحسب إجمالي السطر مع تطبيق نسبة الخصم (إن وُجدت).
        لا يغيّر السطر نفسه، فقط يرجع القيمة.
        """
        qty = self.quantity or DECIMAL_ZERO
        price = self.unit_price or DECIMAL_ZERO
        base = qty * price

        if self.discount_percent:
            discount_factor = Decimal("1.00") - (self.discount_percent / DECIMAL_HUNDRED)
            total = base * discount_factor
        else:
            total = base

        # حماية من الإدخال الخاطئ (مثلاً خصم > 100%)
        if total < DECIMAL_ZERO:
            total = DECIMAL_ZERO

        # إرجاع القيمة بثلاث خانات عشرية
        return total.quantize(Decimal("0.001"))

    def save(self, *args, **kwargs) -> None:
        """
        قبل الحفظ:
        - نحتسب إجمالي السطر line_total.

        بعد الحفظ:
        - نعيد احتساب إجماليات المستند المرتبط.
        """
        self.line_total = self.compute_line_total()
        super().save(*args, **kwargs)

        if self.document_id:
            self.document.recompute_totals(save=True)


# ===================================================================
# نموذج مذكرة التسليم
# ===================================================================


class DeliveryNote(BaseModel):
    """
    مذكرة تسليم:

    - يمكن أن ترتبط بأمر بيع (order) أو تكون مستقلة.
    - في حالة الربط بأمر بيع يمكن الاعتماد على العميل من أمر البيع.
    - في حالة المستقلة يتم تحديد العميل مباشرة في المذكرة.

    يرث من BaseModel:
    - public_id
    - created_at / updated_at
    - created_by / updated_by
    - is_deleted / deleted_at / deleted_by
    """

    class Status(models.TextChoices):
        DRAFT = "draft", _("مسودة")
        CONFIRMED = "confirmed", _("مؤكد")
        CANCELLED = "cancelled", _("ملغي")

    contact = models.ForeignKey(
        Contact,
        on_delete=models.PROTECT,
        related_name="delivery_notes",
        verbose_name=_("العميل / جهة الاتصال"),
        null=True,
        blank=True,
        help_text=_("يمكن تركه فارغًا إذا كانت المذكرة مربوطة بأمر بيع وسيتم استخدام عميل أمر البيع."),
    )

    order = models.ForeignKey(
        SalesDocument,
        on_delete=models.PROTECT,
        related_name="delivery_notes",
        limit_choices_to={"kind": SalesDocument.Kind.ORDER},
        verbose_name=_("أمر البيع"),
        null=True,
        blank=True,
        help_text=_("اختياري: ربط مذكرة التسليم بأمر بيع معيّن."),
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
        """
        رقم مبسّط لمذكرة التسليم:
        مثال: DN-0003
        """
        if self.pk:
            return f"DN-{self.pk:04d}"
        return "DN-DRAFT"

    @property
    def is_confirmed(self) -> bool:
        return self.status == self.Status.CONFIRMED

    @property
    def effective_contact(self):
        """
        المرجع القياسي للعميل في القوالب:
        - إن وُجد contact على المذكرة → يُستخدم.
        - وإلا إن وُجد order.contact → يُستخدم.
        - وإلا يرجع None.
        """
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
# نموذج بند التسليم
# ===================================================================


class DeliveryLine(TimeStampedModel, UserStampedModel):
    """
    بند تسليم بسيط ضمن مذكرة تسليم.

    حالياً:
    - لا يوجد ربط إلزامي بسطر أمر البيع (يمكن إضافته لاحقاً عند الحاجة).

    يرث من:
    - TimeStampedModel  → created_at / updated_at
    - UserStampedModel  → created_by / updated_by
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

    uom = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        verbose_name=_("وحدة القياس"),
        help_text=_("الوحدة المستخدمة في هذا السطر (أساسية أو بديلة)."),
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
        """
        اسم البند كما يظهر في القوائم:
        - الوصف إن وجد
        - وإلا اسم المنتج
        - وإلا نص افتراضي "سطر #"
        """
        if self.description:
            return self.description
        if self.product:
            return self.product.name
        if self.pk:
            return f"سطر #{self.pk}"
        return "سطر جديد"
