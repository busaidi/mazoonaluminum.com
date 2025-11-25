# accounting/models.py

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Sum
from django.forms.models import inlineformset_factory
from django.utils.translation import gettext as _
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

from accounting.domain import InvoiceCreated, InvoiceSent, OrderCreated
from core.domain.hooks import on_lifecycle, on_transition
from core.models.base import BaseModel, NumberedModel
from core.models.domain import (
    StatefulDomainModel, DomainEventsMixin,
)


# ============================================================
# Invoice & InvoiceItem
# ============================================================

class Invoice(NumberedModel, StatefulDomainModel):
    """
    Simple invoice model.
    'serial' is used in URLs: /accounting/invoices/<serial>/
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        PARTIALLY_PAID = "partially_paid", "Partially Paid"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"

    customer = models.ForeignKey(
        "contacts.Customer",
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    issued_at = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)

    description = models.TextField(blank=True)

    terms = models.TextField(
        blank=True,
        help_text="Terms and conditions shown on the invoice.",
    )

    total_amount = models.DecimalField(max_digits=12, decimal_places=3)
    paid_amount = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0,
        help_text="Cached sum of related payments for quick display.",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    ledger_entry = models.OneToOneField(
        "ledger.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoice",
        help_text="Linked ledger journal entry for this invoice, if posted.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-issued_at", "-id")
        indexes = [
            models.Index(fields=["serial"]),
            models.Index(fields=["status"]),
            models.Index(fields=["issued_at"]),
        ]

    def __str__(self) -> str:
        return f"Invoice {self.serial} - {self.customer.name}"

    # ---------- Core logic ----------

    def save(self, *args, **kwargs):
        """
        On first save:
        - Apply due_date / terms defaults from Settings if not set.
        - Let NumberedModel handle serial generation if needed.
        - Domain events (InvoiceCreated, transitions, ...) are handled
          by StatefulDomainModel / DomainEventsMixin via lifecycle hooks.
        """
        from accounting.models import Settings  # to avoid circular imports

        # استخدم _state.adding بدل pk is None (أدق مع Django)
        is_new = self._state.adding

        if is_new:
            settings = Settings.get_solo()

            if not self.due_date and settings.default_due_days:
                self.due_date = self.issued_at + timedelta(days=settings.default_due_days)

            if not self.terms and settings.default_terms:
                self.terms = settings.default_terms

        # NumberedModel + StatefulDomainModel will do their job in MRO
        super().save(*args, **kwargs)

    # ---------- Domain event hooks ----------

    @on_lifecycle("created")
    def _on_created(self) -> None:
        """
        This hook is called automatically after the first save()
        when the DB transaction is committed.

        It emits an InvoiceCreated event for further processing
        (notifications, integrations, etc.).
        """
        self.emit(
            InvoiceCreated(
                invoice_id=self.pk,
                serial=self.serial,
            )
        )

    @on_transition(Status.DRAFT, Status.SENT)
    def _on_sent(self) -> None:
        """
        This hook is called automatically when the invoice status
        changes from DRAFT -> SENT (after DB commit).

        It emits an InvoiceSent event so that other parts of the system
        (e.g. notifications, emails, integrations) can react.
        """
        self.emit(
            InvoiceSent(
                invoice_id=self.pk,
                serial=self.serial,
            )
        )


    # لاحقًا لو حبيت:
    # from core.domain.hooks import on_transition
    # from accounting.domain import InvoiceSent
    #
    # @on_transition(Status.DRAFT, Status.SENT)
    # def _on_sent(self) -> None:
    #     self.emit(
    #         InvoiceSent(
    #             invoice_id=self.pk,
    #             serial=self.serial,
    #         )
    #     )


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(
        Invoice,
        related_name="items",
        on_delete=models.CASCADE,
        verbose_name="الفاتورة",
    )
    product = models.ForeignKey(
        "website.Product",
        on_delete=models.PROTECT,
        verbose_name="المنتج",
        null=True,
        blank=True,  # اختياري
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="الوصف",
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=3)

    @property
    def subtotal(self) -> Decimal:
        return self.quantity * self.unit_price

    def clean(self):
        """
        سطر الفاتورة يكون صالح إذا:
        - product موجود، أو
        - description مكتوب
        """
        if not self.product and not self.description:
            raise ValidationError("يجب اختيار منتج أو كتابة وصف للبند.")

    def __str__(self) -> str:
        if self.product:
            return f"{self.product} × {self.quantity}"
        return f"{self.description or 'Item'} × {self.quantity}"


# ============================================================
# Payment + signal
# ============================================================

class Payment(NumberedModel):
    """
    Payment can be linked to a specific invoice, or just to a customer.

    - يرث من NumberedModel:
      - حقل number (للعرض في الفواتير/التقارير)
      - حقل serial (للاستخدام في الروابط أو البحث السريع لو حبيت لاحقًا)
    - الترقيم يستخدم نفس محرك الترقيم في الكور (NumberingScheme/NumberSequence).
    """

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        CARD = "card", "Card"
        OTHER = "other", "Other"

    customer = models.ForeignKey(
        "contacts.Customer",
        on_delete=models.PROTECT,
        related_name="payments",
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
        help_text="Optional: if linked, affects invoice paid_amount.",
    )

    date = models.DateField(default=timezone.now)
    amount = models.DecimalField(max_digits=12, decimal_places=3)

    method = models.CharField(
        max_length=20,
        choices=Method.choices,
        default=Method.CASH,
    )

    notes = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-date", "-id")
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["customer"]),
            models.Index(fields=["serial"]),  # من NumberedModel
        ]

    def __str__(self) -> str:
        """
        نحاول نظهر رقم الدفع (number) إن وجد،
        مع الحفاظ على فكرة الربط بالفاتورة لو موجودة.
        """
        label = self.number or f"#{self.pk}"
        if self.invoice:
            return f"Payment {label} {self.amount} for {self.invoice.number}"
        return f"Payment {label} {self.amount} ({self.customer.name})"

    # ---------- Validation / save hooks ----------

    def clean(self):
        """
        Ensure that if invoice is set, its customer matches payment.customer.
        """
        if self.invoice and self.invoice.customer_id != self.customer_id:
            raise ValidationError(
                {"invoice": "Invoice customer must match payment customer."}
            )

    def save(self, *args, **kwargs):
        """
        - NumberedModel يتكفّل بتوليد number/serial إذا كانوا فاضيين.
        - بعد الحفظ، نحدّث paid_amount في الفاتورة لو موجودة.
        """
        super().save(*args, **kwargs)
        if self.invoice_id:
            self.invoice.update_paid_amount()

    # ---------- UI helpers (Mazoon badges) ----------

    @property
    def method_badge(self) -> str:
        """
        CSS classes for Mazoon theme badge based on payment method.
        مثال في القالب:
        <span class="{{ payment.method_badge }}">{{ payment.get_method_display }}</span>
        """
        mapping = {
            Payment.Method.CASH: "badge-mazoon badge-confirmed",
            Payment.Method.BANK_TRANSFER: "badge-mazoon badge-sent",
            Payment.Method.CARD: "badge-mazoon badge-partially-paid",
            Payment.Method.OTHER: "badge-mazoon badge-draft",
        }
        return mapping.get(self.method, "badge-mazoon badge-draft")





# ============================================================
# Orders (header + items)
# ============================================================

class Order(NumberedModel, DomainEventsMixin):
    """
    Sales/online order header.

    - يرث من NumberedModel → يحصل على number + serial بنفس محرك الترقيم.
    - DomainEventsMixin ما زال مسؤول عن تجميع/إطلاق الـ Domain Events.
    """

    STATUS_DRAFT = "draft"
    STATUS_PENDING = "pending"      # طلب أونلاين ينتظر تأكيد موظف
    STATUS_CONFIRMED = "confirmed"  # تم التأكيد
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "مسودة"),
        (STATUS_PENDING, "بانتظار التأكيد"),
        (STATUS_CONFIRMED, "مؤكد"),
        (STATUS_CANCELLED, "ملغي"),
    ]

    customer = models.ForeignKey(
        "contacts.Customer",
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="الزبون",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders_created",
        verbose_name="تم إدخاله بواسطة",
    )
    invoice = models.OneToOneField(
        "Invoice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order",
        verbose_name="الفاتورة الناتجة",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    is_online = models.BooleanField(
        default=False,
        help_text="صحيح إذا كان الطلب تم من بوابة الزبون.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="confirmed_orders",
        verbose_name="تم تأكيده بواسطة",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, verbose_name="ملاحظات داخلية")

    class Meta:
        ordering = ("-created_at", "id")
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["serial"]),  # من NumberedModel
        ]

    def __str__(self) -> str:
        """
        نعرض رقم الطلب لو موجود (number)، وإلا نرجع للـ pk مثل السابق.
        """
        label = self.number or f"#{self.pk}"
        return f"طلب {label} - {self.customer}"

    @property
    def total_amount(self) -> Decimal:
        """
        Sum of item.quantity * item.unit_price for this order.
        """
        return sum((item.subtotal for item in self.items.all()), Decimal("0"))

    # ---------- UI helpers (Mazoon badges) ----------

    @property
    def status_badge(self) -> str:
        """
        CSS classes for Mazoon theme badge based on order status.
        مثال في القالب:
        <span class="{{ order.status_badge }}">{{ order.get_status_display }}</span>
        """
        mapping = {
            self.STATUS_DRAFT: "badge-mazoon badge-draft",
            self.STATUS_PENDING: "badge-mazoon badge-pending",
            self.STATUS_CONFIRMED: "badge-mazoon badge-confirmed",
            self.STATUS_CANCELLED: "badge-mazoon badge-cancelled",
        }
        return mapping.get(self.status, "badge-mazoon badge-draft")

    @property
    def type_label(self) -> str:
        """
        نص نوع الطلب حسب اللغة الحالية:
        - أونلاين
        - موظف
        تُستخدم في القالب:
        {{ order.type_label }}
        """
        return _("أونلاين") if self.is_online else _("موظف")

    @property
    def type_badge(self) -> str:
        """
        CSS classes for Mazoon theme badge based on order type.
        تُستخدم في القالب:
        <span class="{{ order.type_badge }}">{{ order.type_label }}</span>
        """
        if self.is_online:
            # نفس فكرة bg-mazoon-accent text-dark اللي كنت تستخدمها
            return "badge-mazoon badge-online"
        return "badge-mazoon badge-staff"

    # ---------- Domain events ----------

    @on_lifecycle("created")
    def _on_created(self) -> None:
        """
        يتم استدعاؤها تلقائياً بعد إنشاء الطلب أول مرة
        (بعد حفظه في قاعدة البيانات ونجاح الـ transaction).

        نطلق هذا الإيفنت فقط للطلبات الأونلاين (is_online=True).
        """
        if not self.is_online:
            return

        self.emit(
            OrderCreated(
                order_id=self.pk,
            )
        )




class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="الطلب",
    )
    # Use inventory.Product instead of website.Product
    product = models.ForeignKey(
        "inventory.Product",
        on_delete=models.PROTECT,
        verbose_name="المنتج",
        related_name="order_items",
        null=True,
        blank=True,
    )
    # UoM field (adjust app/model string if your UoM model lives in another app)
    uom = models.ForeignKey(
        "uom.UnitOfMeasure",
        on_delete=models.PROTECT,
        verbose_name="وحدة القياس",
        null=True,
        blank=True,
        related_name="order_items",
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="الوصف",
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=3)

    class Meta:
        verbose_name = "بند طلب"
        verbose_name_plural = "بنود الطلبات"

    def __str__(self) -> str:
        label = self.description or (str(self.product) if self.product else "")
        return f"{label} x {self.quantity}"

    @property
    def subtotal(self) -> Decimal:
        """
        Subtotal = quantity * unit_price.
        Unit price is assumed "per selected UoM".
        """
        return self.quantity * self.unit_price






class Settings(models.Model):
    """
    Global sales/invoice settings:
    - Invoice numbering (linked to core.NumberingScheme for accounting.Invoice)
    - Default due days
    - Default VAT behavior
    - Default terms

    هذا موديل "singleton" (صف واحد فقط) مثل LedgerSettings.
    """

    class InvoiceResetPolicy(models.TextChoices):
        NEVER = "never", _("لا يتم إعادة الترقيم")
        YEAR = "year", _("يُعاد سنويًا")
        MONTH = "month", _("يُعاد شهريًا")

    # ---------- Invoice numbering ----------
    invoice_number_active = models.BooleanField(
        default=True,
        verbose_name=_("تفعيل ترقيم الفواتير؟"),
        help_text=_("إذا تم تعطيله، لن يتم توليد أرقام تلقائية للفواتير."),
    )

    invoice_prefix = models.CharField(
        max_length=20,
        default="INV",
        verbose_name=_("بادئة أرقام الفواتير"),
        help_text=_("تظهر في بداية رقم الفاتورة مثل INV-2025-0001."),
    )

    invoice_padding = models.PositiveSmallIntegerField(
        default=4,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        verbose_name=_("عدد الخانات الرقمية"),
        help_text=_("مثلاً 4 تعني 0001، 0002، ..."),
    )

    invoice_start_value = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        verbose_name=_("قيمة البداية للتسلسل"),
        help_text=_("مثلاً 1 تعني أن أول فاتورة ستكون 0001، ويمكن البدء من رقم أكبر عند الحاجة."),
    )

    invoice_reset_policy = models.CharField(
        max_length=10,
        choices=InvoiceResetPolicy.choices,
        default=InvoiceResetPolicy.YEAR,
        verbose_name=_("سياسة إعادة الترقيم"),
        help_text=_("تحدد متى يبدأ التسلسل من جديد: لا يعاد، أو سنويًا، أو شهريًا."),
    )

    invoice_custom_pattern = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("نمط الترقيم المخصص (اختياري)"),
        help_text=_(
            "اتركه فارغًا لاستخدام البادئة وعدد الخانات. "
            "يمكنك استخدام المتغيرات {year}، {month}، {day}، و {seq:04d}. "
            "يجب أن يحتوي النمط على {seq}."
        ),
    )

    # ---------- Payment numbering ----------
    payment_number_active = models.BooleanField(
        default=True,
        verbose_name=_("تفعيل ترقيم الدفعات؟"),
        help_text=_("إذا تم تعطيله، لن يتم توليد أرقام تلقائية للدفعات."),
    )

    payment_prefix = models.CharField(
        max_length=20,
        default="PAY",
        verbose_name=_("بادئة أرقام الدفعات"),
        help_text=_("تظهر في بداية رقم الدفع مثل PAY-2025-0001."),
    )

    payment_padding = models.PositiveSmallIntegerField(
        default=4,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        verbose_name=_("عدد الخانات الرقمية للدفعات"),
        help_text=_("مثلاً 4 تعني 0001، 0002، ... للدفعات."),
    )

    payment_start_value = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        verbose_name=_("قيمة البداية لتسلسل الدفعات"),
        help_text=_("مثلاً 1 تعني أن أول دفعة ستكون 0001."),
    )

    payment_reset_policy = models.CharField(
        max_length=10,
        choices=InvoiceResetPolicy.choices,  # نعيد استخدام نفس الاختيارات
        default=InvoiceResetPolicy.YEAR,
        verbose_name=_("سياسة إعادة الترقيم للدفعات"),
        help_text=_("تحدد متى يبدأ تسلسل الدفعات من جديد."),
    )

    payment_custom_pattern = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("نمط الترقيم المخصص للدفعات (اختياري)"),
        help_text=_(
            "اتركه فارغًا لاستخدام البادئة وعدد الخانات. "
            "يمكنك استخدام المتغيرات {year}، {month}، {day}، و {seq:04d}. "
            "يجب أن يحتوي النمط على {seq}."
        ),
    )
    # ---------- Order numbering ----------
    order_number_active = models.BooleanField(
        default=True,
        verbose_name=_("تفعيل ترقيم الطلبات؟"),
        help_text=_("إذا تم تعطيله، لن يتم توليد أرقام تلقائية للطلبات."),
    )

    order_prefix = models.CharField(
        max_length=20,
        default="ORD",
        verbose_name=_("بادئة أرقام الطلبات"),
        help_text=_("تظهر في بداية رقم الطلب مثل ORD-2025-0001."),
    )

    order_padding = models.PositiveSmallIntegerField(
        default=4,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        verbose_name=_("عدد الخانات الرقمية للطلبات"),
        help_text=_("مثلاً 4 تعني 0001، 0002، ... للطلبات."),
    )

    order_start_value = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        verbose_name=_("قيمة البداية لتسلسل الطلبات"),
        help_text=_("مثلاً 1 تعني أن أول طلب سيكون 0001."),
    )

    order_reset_policy = models.CharField(
        max_length=10,
        choices=InvoiceResetPolicy.choices,
        default=InvoiceResetPolicy.YEAR,
        verbose_name=_("سياسة إعادة الترقيم للطلبات"),
        help_text=_("تحدد متى يبدأ تسلسل الطلبات من جديد."),
    )

    order_custom_pattern = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("نمط الترقيم المخصص للطلبات (اختياري)"),
        help_text=_(
            "اتركه فارغًا لاستخدام البادئة وعدد الخانات. "
            "يمكنك استخدام المتغيرات {year}، {month}، {day}، و {seq:04d}. "
            "يجب أن يحتوي النمط على {seq}."
        ),
    )

    # ---------- Default invoice behavior ----------
    default_due_days = models.PositiveSmallIntegerField(
        default=30,
        validators=[MinValueValidator(0), MaxValueValidator(365)],
        verbose_name=_("عدد أيام الاستحقاق الافتراضي"),
        help_text=_("يُستخدم لحساب تاريخ الاستحقاق من تاريخ الفاتورة."),
    )

    auto_confirm_invoice = models.BooleanField(
        default=False,
        verbose_name=_("اعتماد الفاتورة تلقائيًا بعد الحفظ؟"),
        help_text=_("إذا كان مفعلًا، تنتقل الفاتورة من Draft إلى Sent تلقائيًا."),
    )

    auto_post_to_ledger = models.BooleanField(
        default=False,
        verbose_name=_("ترحيل تلقائي إلى دفتر الأستاذ بعد الاعتماد؟"),
        help_text=_(
            "إذا كان مفعلًا، يتم إنشاء قيد تلقائي في دفتر الأستاذ عند اعتماد الفاتورة."
        ),
    )

    # ---------- VAT behavior ----------
    default_vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("5.00"),
        verbose_name=_("نسبة ضريبة القيمة المضافة الافتراضية (%)"),
        help_text=_(
            "تُستخدم للفواتير التي تحتوي على ضريبة "
            "(يمكن تجاهلها إذا لم تُفعّل VAT)."
        ),
    )

    prices_include_vat = models.BooleanField(
        default=False,
        verbose_name=_("الأسعار شاملة للضريبة؟"),
        help_text=_("إذا كان مفعلًا، تعتبر أسعار البنود شاملة للضريبة."),
    )

    # ---------- Text templates ----------
    default_terms = models.TextField(
        blank=True,
        verbose_name=_("الشروط والأحكام الافتراضية"),
        help_text=_("يتم نسخها تلقائيًا في حقل الشروط داخل الفاتورة الجديدة."),
    )

    footer_notes = models.TextField(
        blank=True,
        verbose_name=_("ملاحظات أسفل الفاتورة"),
        help_text=_("نص يظهر في أسفل الفاتورة المطبوعة (اختياري)."),
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("تاريخ آخر تعديل"),
    )

    class Meta:
        verbose_name = _("إعدادات المبيعات")
        verbose_name_plural = _("إعدادات المبيعات")

    def __str__(self) -> str:
        return _("إعدادات المبيعات")

    # ---------- Singleton helper ----------
    @classmethod
    def get_solo(cls) -> "Settings":
        """
        يعيد صف الإعدادات الوحيد، وينشئ واحد إذا غير موجود.
        """
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    # ---------- NumberingScheme sync ----------
    def save(self, *args, **kwargs):
        """
        نحفظ إعدادات المبيعات + نزامن سكيم الترقيم في core.NumberingScheme
        للموديلات:
        - accounting.Invoice
        - accounting.Payment
        - accounting.Order
        كل واحد بإعداداته الخاصة.
        """
        super().save(*args, **kwargs)

        from core.models.numbering import NumberingScheme

        # ----------------- invoice pattern -----------------
        if self.invoice_custom_pattern:
            invoice_pattern = self.invoice_custom_pattern
        else:
            inv_seq_format = f"0{self.invoice_padding}d"
            invoice_pattern = (
                f"{self.invoice_prefix}-"
                "{year}-"
                "{seq:" + inv_seq_format + "}"
            )

        NumberingScheme.objects.update_or_create(
            model_label="accounting.Invoice",
            defaults={
                "field_name": "number",
                "pattern": invoice_pattern,
                "start": self.invoice_start_value,
                "reset": self.invoice_reset_policy,
                "is_active": self.invoice_number_active,
            },
        )

        # ----------------- payment pattern -----------------
        if self.payment_custom_pattern:
            payment_pattern = self.payment_custom_pattern
        else:
            pay_seq_format = f"0{self.payment_padding}d"
            payment_pattern = (
                f"{self.payment_prefix}-"
                "{year}-"
                "{seq:" + pay_seq_format + "}"
            )

        NumberingScheme.objects.update_or_create(
            model_label="accounting.Payment",
            defaults={
                "field_name": "number",
                "pattern": payment_pattern,
                "start": self.payment_start_value,
                "reset": self.payment_reset_policy,
                "is_active": self.payment_number_active,
            },
        )

        # ----------------- order pattern -----------------
        if self.order_custom_pattern:
            order_pattern = self.order_custom_pattern
        else:
            ord_seq_format = f"0{self.order_padding}d"
            order_pattern = (
                f"{self.order_prefix}-"
                "{year}-"
                "{seq:" + ord_seq_format + "}"
            )

        NumberingScheme.objects.update_or_create(
            model_label="accounting.Order",
            defaults={
                "field_name": "number",
                "pattern": order_pattern,
                "start": self.order_start_value,
                "reset": self.order_reset_policy,
                "is_active": self.order_number_active,
            },
        )
