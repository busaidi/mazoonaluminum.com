from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

#generate invoice number
def generate_invoice_number():
    year = timezone.now().year

    # استرجاع آخر فاتورة في نفس السنة
    last_invoice = Invoice.objects.filter(
        number__startswith=f"INV-{year}"
    ).order_by("id").last()

    if last_invoice:
        # استخراج آخر رقم + 1
        last_number = int(last_invoice.number.split("-")[-1])
        new_number = last_number + 1
    else:
        new_number = 1

    return f"INV-{year}-{new_number:04d}"


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

    def __str__(self):
        return self.name

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
        help_text="Terms and conditions shown on the invoice."
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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-issued_at", "-id")
        indexes = [
            models.Index(fields=["number"]),
            models.Index(fields=["status"]),
            models.Index(fields=["issued_at"]),
        ]

    def __str__(self):
        return f"Invoice {self.number} - {self.customer.name}"

    def save(self, *args, **kwargs):
        """
        On first save, if no number provided, auto-generate one.
        """
        if not self.number:
            self.number = generate_invoice_number()
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
            # رجعها Sent (أو Draft حسب ما تحب تغيّر لاحقًا)
            self.status = Invoice.Status.SENT

        self.save(update_fields=["paid_amount", "status"])



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
        blank=True,  # 👈 صار اختياري
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
        إذا الاثنين فاضيين، نعتبره سطر فارغ (عادة formset يتجاهله)،
        لكن لو وصل هنا نرمي خطأ بسيط.
        """
        from django.core.exceptions import ValidationError

        if not self.product and not self.description:
            raise ValidationError(
                "يجب اختيار منتج أو كتابة وصف للبند."
            )

    def __str__(self):
        if self.product:
            return f"{self.product} × {self.quantity}"
        return f"{self.description or 'Item'} × {self.quantity}"



class Payment(models.Model):
    """
    Payment can be linked to a specific invoice, or just to a customer.
    Later, views will handle automatic linking and updating invoice totals.
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

    def __str__(self):
        if self.invoice:
            return f"Payment {self.amount} for {self.invoice.number}"
        return f"Payment {self.amount} ({self.customer.name})"

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


@receiver(post_delete, sender=Payment)
def update_invoice_on_payment_delete(sender, instance: "Payment", **kwargs):
    """
    When a payment is deleted, recalc invoice.paid_amount.
    """
    if instance.invoice_id:
        instance.invoice.update_paid_amount()


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
    # نستخدم AUTH_USER_MODEL بدل استيراد User مباشرة
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
        related_name="source_order",
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

    def __str__(self):
        return f"طلب #{self.pk} - {self.customer}"

    @property
    def total_amount(self) -> Decimal:
        """
        Sum of item.quantity * item.unit_price for this order.
        نستخدم الجمع في البايثون هنا لتبسيط الأمور.
        """
        return sum((item.subtotal for item in self.items.all()), Decimal("0"))


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
    description = models.CharField(     # 👈 هذا الحقل الجديد
        max_length=255,
        blank=True,
        default="",                      # أنصح تضيف default عشان ما يسألك أثناء المايغريشن
        verbose_name="الوصف",
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=3)

    @property
    def subtotal(self) -> Decimal:
        return self.quantity * self.unit_price

