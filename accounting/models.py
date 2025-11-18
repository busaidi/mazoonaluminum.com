from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


# ============================================================
# Helpers
# ============================================================

def generate_invoice_number() -> str:
    """
    Generate a human-readable invoice number per year, e.g. INV-2025-0001.
    Pattern: INV-<year>-<running_number>
    """
    year = timezone.now().year

    # آخر فاتورة في نفس السنة
    last_invoice = (
        Invoice.objects
        .filter(number__startswith=f"INV-{year}")
        .order_by("id")
        .last()
    )

    if last_invoice:
        # استخراج آخر رقم + 1
        last_number = int(last_invoice.number.split("-")[-1])
        new_number = last_number + 1
    else:
        new_number = 1

    return f"INV-{year}-{new_number:04d}"


# ============================================================
# Customer
# ============================================================

class Customer(models.Model):
    """
    Basic customer profile.
    If 'user' is set, it links to Django auth user (for portal login).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_profile",
        help_text="Optional: link to a Django user for portal access.",
    )
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    company_name = models.CharField(max_length=255, blank=True)
    tax_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="Optional: VAT / Tax ID if applicable.",
    )
    address = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name", "id")

    def __str__(self) -> str:
        return self.name

    # ---------- Aggregated helpers ----------

    @property
    def total_invoiced(self) -> Decimal:
        """
        Sum of all invoices.total_amount for this customer.
        """
        total = self.invoices.aggregate(s=Sum("total_amount")).get("s")
        return total or Decimal("0")

    @property
    def total_paid(self) -> Decimal:
        """
        Sum of all payments.amount for this customer.
        """
        total = self.payments.aggregate(s=Sum("amount")).get("s")
        return total or Decimal("0")

    @property
    def balance(self) -> Decimal:
        """
        Customer balance = total_invoiced - total_paid.
        """
        return self.total_invoiced - self.total_paid


# ============================================================
# Invoice & InvoiceItem
# ============================================================

class Invoice(models.Model):
    """
    Simple invoice model.
    'number' will be used later in URLs: /accounting/invoices/<number>/
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        PARTIALLY_PAID = "partially_paid", "Partially Paid"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    number = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        help_text="Human-readable invoice number, e.g. MAZ-2025-0001.",
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
            models.Index(fields=["number"]),
            models.Index(fields=["status"]),
            models.Index(fields=["issued_at"]),
        ]

    def __str__(self) -> str:
        return f"Invoice {self.number} - {self.customer.name}"

    # ---------- Core logic ----------

    @classmethod
    def generate_number(cls, issue_date=None):
        """
        توليد رقم فاتورة بناءً على إعدادات SalesSettings:
        - بادئة (prefix)
        - السنة
        - عدد الخانات (padding)
        - خيار إعادة الترقيم سنوياً
        مثال: INV-2025-0001
        """
        from django.utils import timezone
        from .models import SalesSettings  # نفس الملف

        if issue_date is None:
            issue_date = timezone.now().date()

        settings = SalesSettings.get_solo()
        prefix = settings.invoice_prefix or "INV"
        padding = settings.invoice_padding or 4

        year_str = str(issue_date.year)
        base_prefix = f"{prefix}-{year_str}-"

        # نجيب آخر رقم لنفس السنة/البادئة
        qs = cls.objects.filter(number__startswith=base_prefix)
        if settings.invoice_reset_yearly:
            qs = qs.filter(issued_at__year=issue_date.year)

        last = qs.order_by("-number").first()

        if last:
            try:
                last_seq = int(last.number.split("-")[-1])
            except (ValueError, IndexError):
                last_seq = 0
        else:
            last_seq = 0

        new_seq = last_seq + 1
        seq_str = str(new_seq).zfill(padding)

        return f"{prefix}-{year_str}-{seq_str}"

    def save(self, *args, **kwargs):
        """
        On first save:
        - Generate invoice number from SalesSettings if not provided.
        - Fill due_date using default_due_days if not set.
        - Fill terms from default_terms if empty.
        """
        from .models import SalesSettings  # نفس الملف

        is_new = self.pk is None

        if is_new:
            settings = SalesSettings.get_solo()

            # رقم الفاتورة من الإعدادات
            if not self.number:
                self.number = Invoice.generate_number(issue_date=self.issued_at)

            # تاريخ الاستحقاق الافتراضي
            if not self.due_date and settings.default_due_days:
                self.due_date = self.issued_at + timedelta(days=settings.default_due_days)

            # الشروط الافتراضية
            if not self.terms and settings.default_terms:
                self.terms = settings.default_terms

        super().save(*args, **kwargs)

    @property
    def balance(self) -> Decimal:
        """
        Invoice balance = total_amount - paid_amount.
        """
        return self.total_amount - self.paid_amount

    def update_paid_amount(self) -> None:
        """
        Recalculate 'paid_amount' from related payments,
        and auto-update status if fully/partially paid.
        """
        total = self.payments.aggregate(s=Sum("amount")).get("s") or Decimal("0")
        self.paid_amount = total

        # auto-update status if fully/partially paid
        if self.total_amount and self.paid_amount >= self.total_amount > 0:
            self.status = Invoice.Status.PAID
        elif self.total_amount and 0 < self.paid_amount < self.total_amount:
            self.status = Invoice.Status.PARTIALLY_PAID
        elif self.paid_amount == 0 and self.status in {
            Invoice.Status.PAID,
            Invoice.Status.PARTIALLY_PAID,
        }:
            # رجّعها Sent (أو Draft حسب ما تحب تغيّر لاحقًا)
            self.status = Invoice.Status.SENT

        self.save(update_fields=["paid_amount", "status"])

    # ---------- Posting helpers ----------

    def post_to_ledger(self):
        """
        Helper wrapper to post this invoice to the ledger.
        Keeps accounting logic inside accounting app.
        """
        from accounting.services import post_sales_invoice_to_ledger
        return post_sales_invoice_to_ledger(self)

    def unpost_from_ledger(self, *, reversal_date=None, user=None):
        """
        Helper wrapper to unpost this invoice from the ledger
        by creating a reversing entry.
        """
        from accounting.services import unpost_sales_invoice_from_ledger
        return unpost_sales_invoice_from_ledger(
            self,
            reversal_date=reversal_date,
            user=user,
        )

    # ---------- UI helpers (Mazoon badges) ----------

    @property
    def status_badge(self) -> str:
        """
        CSS classes for Mazoon theme badge based on invoice status.
        تستخدم في القالب مثل:
        <span class="{{ invoice.status_badge }}">{{ invoice.get_status_display }}</span>
        """
        mapping = {
            Invoice.Status.DRAFT: "badge-mazoon badge-draft",
            Invoice.Status.SENT: "badge-mazoon badge-sent",
            Invoice.Status.PARTIALLY_PAID: "badge-mazoon badge-partially-paid",
            Invoice.Status.PAID: "badge-mazoon badge-paid",
            Invoice.Status.CANCELLED: "badge-mazoon badge-cancelled",
        }
        return mapping.get(self.status, "badge-mazoon badge-draft")


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

class Payment(models.Model):
    """
    Payment can be linked to a specific invoice, or just to a customer.
    Views handle automatic linking and updating invoice totals.
    """

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        CARD = "card", "Card"
        OTHER = "other", "Other"

    customer = models.ForeignKey(
        Customer,
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
        ]

    def __str__(self) -> str:
        if self.invoice:
            return f"Payment {self.amount} for {self.invoice.number}"
        return f"Payment {self.amount} ({self.customer.name})"

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
        On save, call super() then update related invoice.paid_amount if any.
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


@receiver(post_delete, sender=Payment)
def update_invoice_on_payment_delete(sender, instance: "Payment", **kwargs):
    """
    When a payment is deleted, recalc invoice.paid_amount.
    """
    if instance.invoice_id:
        instance.invoice.update_paid_amount()


# ============================================================
# Orders (header + items)
# ============================================================

class Order(models.Model):
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
        Customer,
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

    def __str__(self) -> str:
        return f"طلب #{self.pk} - {self.customer}"

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


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="الطلب",
    )
    product = models.ForeignKey(
        "website.Product",
        on_delete=models.PROTECT,
        verbose_name="المنتج",
        null=True,
        blank=True,
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="الوصف",
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=3)

    @property
    def subtotal(self) -> Decimal:
        return self.quantity * self.unit_price



class SalesSettings(models.Model):
    """
    Global sales/invoice settings:
    - Invoice numbering
    - Default due days
    - Default VAT behavior
    - Default terms
    هذا موديل "singleton" (صف واحد فقط) مثل LedgerSettings.
    """

    # ---------- Invoice numbering ----------
    invoice_prefix = models.CharField(
        max_length=20,
        default="INV",
        verbose_name=_("بادئة أرقام الفواتير"),
        help_text=_("تظهر في بداية رقم الفاتورة مثل INV-2025-0001."),
    )
    invoice_padding = models.PositiveSmallIntegerField(
        default=4,
        verbose_name=_("عدد الخانات الرقمية"),
        help_text=_("مثلاً 4 تعني 0001، 0002، ..."),
    )
    invoice_reset_yearly = models.BooleanField(
        default=True,
        verbose_name=_("إعادة ترقيم الفواتير سنويًا؟"),
        help_text=_("إذا كان مفعلًا، يبدأ الترقيم من 1 في كل سنة جديدة."),
    )

    # ---------- Default invoice behavior ----------
    default_due_days = models.PositiveSmallIntegerField(
        default=30,
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
        help_text=_("إذا كان مفعلًا، يتم إنشاء قيد تلقائي في دفتر الأستاذ عند اعتماد الفاتورة."),
    )

    # ---------- VAT behavior ----------
    default_vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("5.00"),
        verbose_name=_("نسبة ضريبة القيمة المضافة الافتراضية (%)"),
        help_text=_("تُستخدم للفواتير التي تحتوي على ضريبة (يمكن تجاهلها إذا لم تُفعّل VAT)."),
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

    @classmethod
    def get_solo(cls) -> "SalesSettings":
        """
        يعيد صف الإعدادات الوحيد، وينشئ واحد إذا غير موجود.
        """
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
