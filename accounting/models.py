from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models.signals import post_delete
from django.dispatch import receiver


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
    def total_invoiced(self):
        from django.db.models import Sum
        return self.invoices.aggregate(s=Sum("total_amount")).get("s") or 0

    @property
    def total_paid(self):
        from django.db.models import Sum
        return self.payments.aggregate(s=Sum("amount")).get("s") or 0

    @property
    def balance(self):
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
        help_text="Human-readable invoice number, e.g. MAZ-2025-0001.",
    )
    issued_at = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)

    description = models.TextField(blank=True)

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

    @property
    def balance(self):
        return self.total_amount - self.paid_amount

    def update_paid_amount(self):
        """
        Recalculate 'paid_amount' from related payments.
        You can call this in signals or after saving a Payment.
        """
        from django.db.models import Sum
        total = self.payments.aggregate(s=Sum("amount")).get("s") or 0
        self.paid_amount = total

        # auto-update status if fully/partially paid
        if self.paid_amount >= self.total_amount and self.total_amount > 0:
            self.status = Invoice.Status.PAID
        elif 0 < self.paid_amount < self.total_amount:
            self.status = Invoice.Status.PARTIALLY_PAID
        elif self.paid_amount == 0 and self.status in {
            Invoice.Status.PAID,
            Invoice.Status.PARTIALLY_PAID,
        }:
            # رجعها Draft أو Sent حسب استخدامك لاحقًا
            self.status = Invoice.Status.SENT

        self.save(update_fields=["paid_amount", "status"])


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
def update_invoice_on_payment_delete(sender, instance: Payment, **kwargs):
    """
    When a payment is deleted, recalc invoice.paid_amount.
    """
    if instance.invoice_id:
        instance.invoice.update_paid_amount()
