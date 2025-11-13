# accounting/models.py
from django.db import models
from django.conf import settings

class Customer(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_profile",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=50, blank=True)
    company_name = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.name

class Invoice(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="invoices")
    number = models.CharField(max_length=50, unique=True)
    issued_at = models.DateField()
    due_date = models.DateField(null=True, blank=True)

    description = models.TextField(blank=True)  # وصف عام
    total_amount = models.DecimalField(max_digits=12, decimal_places=3)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=3, default=0)

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("open", "Open"),
        ("paid", "Paid"),
        ("cancelled", "Cancelled"),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")

    def __str__(self):
        return f"Invoice {self.number} - {self.customer}"


class Payment(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="payments")
    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name="payments",
        null=True, blank=True
    )
    date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=3)
    notes = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Payment {self.amount} for {self.customer}"
