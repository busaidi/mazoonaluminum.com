from django.core.management.base import BaseCommand
from accounting.models import Invoice, Payment, Customer
from django.utils import timezone
from decimal import Decimal


class Command(BaseCommand):
    help = "Seed demo invoices and payments"

    def handle(self, *args, **options):
        today = timezone.now().date()

        # Ensure at least one customer exists
        customer, _ = Customer.objects.get_or_create(
            name="Test Customer",
            defaults={"phone": "0000", "company_name": "Demo Co."}
        )

        # ----------------------
        # Create sample invoices
        # ----------------------
        invoices_data = [
            {"customer": customer, "total_amount": Decimal("5000"), "status": Invoice.Status.SENT},
            {"customer": customer, "total_amount": Decimal("2500"), "status": Invoice.Status.PARTIALLY_PAID},
            {"customer": customer, "total_amount": Decimal("1200"), "status": Invoice.Status.PAID},
        ]

        created_invoices = []

        for data in invoices_data:
            inv = Invoice.objects.create(
                customer=data["customer"],
                total_amount=data["total_amount"],
                status=data["status"],
                issued_at=today
            )
            created_invoices.append(inv)
            self.stdout.write(f"Created invoice #{inv.number} amount {inv.total_amount}")

        # ----------------------
        # Create sample payments
        # ----------------------
        Payment.objects.create(
            customer=customer,
            amount=Decimal("2500"),
            date=today,
            invoice=created_invoices[0],  # First invoice
        )

        Payment.objects.create(
            customer=customer,
            amount=Decimal("1000"),
            date=today,
            invoice=created_invoices[1],  # Partially paid
        )

        self.stdout.write(self.style.SUCCESS("Invoices & payments seeded successfully."))
