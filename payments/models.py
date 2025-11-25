# payments/models.py

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import NumberedModel  # ⇐ عدّل المسار حسب مشروعك الفعلي


class PaymentMethod(models.Model):
    """
    تعريف طرق الدفع (نقدي، شيك، تحويل بنكي، بطاقة، إلخ).
    يمكن استخدامه في أماكن مختلفة (عملاء، موردين، أخرى).
    """

    class MethodType(models.TextChoices):
        CASH = "cash", _("نقدي")
        BANK_TRANSFER = "bank_transfer", _("تحويل بنكي")
        CHEQUE = "cheque", _("شيك")
        CARD = "card", _("بطاقة")
        OTHER = "other", _("أخرى")

    name = models.CharField(
        max_length=100,
        verbose_name=_("اسم طريقة الدفع"),
        help_text=_("مثال: نقدًا، تحويل بنكي، شيك..."),
    )
    code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_("الكود"),
        help_text=_("كود داخلي لتمييز طريقة الدفع (مثال: CASH, BANK_OMAN)."),
    )
    method_type = models.CharField(
        max_length=20,
        choices=MethodType.choices,
        default=MethodType.CASH,
        verbose_name=_("نوع الطريقة"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("نشط؟"),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("طريقة دفع")
        verbose_name_plural = _("طرق الدفع")
        ordering = ("name", "id")

    def __str__(self) -> str:
        return self.name


class Payment(NumberedModel):
    """
    حركة دفع واحدة (قبض من عميل، صرف لمورد، أو حركة أخرى).

    - يرث من NumberedModel:
      - number
      - serial
      - وربما حقول أخرى حسب تنفيذك.
    """

    class Direction(models.TextChoices):
        IN = "in", _("قبض (من عميل)")
        OUT = "out", _("صرف (لمورد أو آخر)")

    direction = models.CharField(
        max_length=10,
        choices=Direction.choices,
        default=Direction.IN,
        verbose_name=_("نوع الحركة"),
    )

    # الطرف (عميل / مورد / جهة أخرى) – الآن موحَّد على contacts.Contact
    contact = models.ForeignKey(
        "contacts.Contact",
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name=_("الطرف"),
        help_text=_("العميل أو المورد المرتبط بهذه الحركة."),
    )

    method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name=_("طريقة الدفع"),
    )

    date = models.DateField(
        default=timezone.now,
        verbose_name=_("تاريخ الدفع"),
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name=_("المبلغ"),
    )

    currency = models.CharField(
        max_length=10,
        default="OMR",
        verbose_name=_("العملة"),
    )

    reference = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("مرجع خارجي"),
        help_text=_("مثال: رقم شيك، رقم عملية بنكية، رقم إيصال..."),
    )

    notes = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("ملاحظات"),
    )

    journal_entry = models.ForeignKey(
        "ledger.JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
        verbose_name=_("قيد اليومية"),
    )

    is_posted = models.BooleanField(
        default=False,
        verbose_name=_("مرحَّل إلى الدفتر؟"),
    )
    posted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("تاريخ الترحيل"),
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments_created",
        verbose_name=_("أنشأها"),
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments_updated",
        verbose_name=_("آخر تعديل بواسطة"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("تاريخ الإنشاء"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("تاريخ التحديث"),
    )

    class Meta:
        verbose_name = _("دفعة")
        verbose_name_plural = _("دفعات")
        ordering = ("-date", "-id")
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["contact"]),
            models.Index(fields=["serial"]),  # من NumberedModel
        ]

    def __str__(self) -> str:
        label = self.number or f"#{self.pk}"
        return f"Payment {label} {self.amount} ({self.contact})"

    @property
    def signed_amount(self) -> Decimal:
        """
        تعيد المبلغ بإشارة موجبة للقبض وسالبة للصرف.
        """
        if self.direction == self.Direction.OUT:
            return -self.amount
        return self.amount

    def mark_posted(self):
        """
        تستدعى بعد إنشاء قيد اليومية في ledger.
        """
        self.is_posted = True
        self.posted_at = timezone.now()
        self.save(update_fields=["is_posted", "posted_at"])

    @property
    def method_badge(self) -> str:
        """
        CSS classes for Mazoon theme badge based on payment method or type.
        مثال في القالب:
        <span class="{{ payment.method_badge }}">{{ payment.method.name }}</span>
        """
        # لو حاب تربطها بـ method.method_type:
        mtype = self.method.method_type if self.method_id else None
        mapping = {
            PaymentMethod.MethodType.CASH: "badge-mazoon badge-confirmed",
            PaymentMethod.MethodType.BANK_TRANSFER: "badge-mazoon badge-sent",
            PaymentMethod.MethodType.CARD: "badge-mazoon badge-partially-paid",
            PaymentMethod.MethodType.CHEQUE: "badge-mazoon badge-draft",
            PaymentMethod.MethodType.OTHER: "badge-mazoon badge-draft",
        }
        return mapping.get(mtype, "badge-mazoon badge-draft")


class PaymentAllocation(models.Model):
    """
    ربط دفعة واحدة بعدة فواتير (Invoice).
    """

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name="allocations",
        verbose_name=_("الدفعة"),
    )
    invoice = models.ForeignKey(
        "accounting.Invoice",
        on_delete=models.PROTECT,
        related_name="payment_allocations",
        verbose_name=_("الفاتورة"),
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name=_("المبلغ المخصص للفاتورة"),
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("تخصيص دفعة لفاتورة")
        verbose_name_plural = _("تخصيصات الدفعات للفواتير")
        unique_together = ("payment", "invoice")

    def __str__(self) -> str:
        return f"{self.payment} → {self.invoice} ({self.amount})"
