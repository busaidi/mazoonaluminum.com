# accounting/tests.py

from decimal import Decimal

from django.contrib.auth.models import User, Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Customer, Invoice, Payment


class AccountingModelTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name="Test Customer",
            phone="123456",
            email="customer@example.com",
        )

    def test_customer_balance_calculation(self):
        """
        Customer.total_invoiced / total_paid / balance should reflect
        related invoices and payments.
        """
        inv1 = Invoice.objects.create(
            customer=self.customer,
            number="INV-001",
            issued_at=timezone.now().date(),
            total_amount=Decimal("100.000"),
            status=Invoice.Status.SENT,
        )
        inv2 = Invoice.objects.create(
            customer=self.customer,
            number="INV-002",
            issued_at=timezone.now().date(),
            total_amount=Decimal("50.000"),
            status=Invoice.Status.SENT,
        )

        # 2 payments total 80
        Payment.objects.create(
            customer=self.customer,
            invoice=inv1,
            date=timezone.now().date(),
            amount=Decimal("30.000"),
            method=Payment.Method.CASH,
        )
        Payment.objects.create(
            customer=self.customer,
            invoice=inv2,
            date=timezone.now().date(),
            amount=Decimal("50.000"),
            method=Payment.Method.CASH,
        )

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.total_invoiced, Decimal("150.000"))
        self.assertEqual(self.customer.total_paid, Decimal("80.000"))
        self.assertEqual(self.customer.balance, Decimal("70.000"))

    def test_invoice_paid_amount_and_status_update(self):
        """
        Saving a Payment linked to an Invoice should update invoice.paid_amount
        and set status accordingly.
        """
        invoice = Invoice.objects.create(
            customer=self.customer,
            number="INV-003",
            issued_at=timezone.now().date(),
            total_amount=Decimal("100.000"),
            status=Invoice.Status.SENT,
        )

        # First partial payment
        Payment.objects.create(
            customer=self.customer,
            invoice=invoice,
            date=timezone.now().date(),
            amount=Decimal("40.000"),
            method=Payment.Method.CASH,
        )

        invoice.refresh_from_db()
        self.assertEqual(invoice.paid_amount, Decimal("40.000"))
        self.assertEqual(invoice.status, Invoice.Status.PARTIALLY_PAID)

        # Second payment completes the invoice
        Payment.objects.create(
            customer=self.customer,
            invoice=invoice,
            date=timezone.now().date(),
            amount=Decimal("60.000"),
            method=Payment.Method.CASH,
        )

        invoice.refresh_from_db()
        self.assertEqual(invoice.paid_amount, Decimal("100.000"))
        self.assertEqual(invoice.status, Invoice.Status.PAID)
        self.assertEqual(invoice.balance, Decimal("0.000"))

    def test_payment_clean_rejects_mismatched_invoice_customer(self):
        """
        Payment.clean() must raise ValidationError if invoice.customer != payment.customer.
        """
        other_customer = Customer.objects.create(
            name="Other Customer",
            phone="000",
            email="other@example.com",
        )

        invoice = Invoice.objects.create(
            customer=self.customer,
            number="INV-004",
            issued_at=timezone.now().date(),
            total_amount=Decimal("10.000"),
            status=Invoice.Status.SENT,
        )

        payment = Payment(
            customer=other_customer,
            invoice=invoice,
            date=timezone.now().date(),
            amount=Decimal("5.000"),
            method=Payment.Method.CASH,
        )

        with self.assertRaises(ValidationError):
            payment.clean()


class AccountingViewsTests(TestCase):
    def setUp(self):
        # Create accounting_staff group
        self.group = Group.objects.create(name="accounting_staff")

        # Create user and add to group
        self.user = User.objects.create_user(
            username="accountant",
            email="acc@example.com",
            password="testpassword123",
            is_active=True,
        )
        self.user.groups.add(self.group)

        # Create a customer and an invoice for view tests
        self.customer = Customer.objects.create(
            name="View Customer",
            phone="7890",
            email="view@example.com",
        )
        self.invoice = Invoice.objects.create(
            customer=self.customer,
            number="INV-100",
            issued_at=timezone.now().date(),
            total_amount=Decimal("200.000"),
            status=Invoice.Status.SENT,
        )

    def test_invoice_list_requires_login_and_group(self):
        """
        An accounting staff user should be able to access invoice list.
        """
        self.client.force_login(self.user)
        url = reverse("accounting:invoice_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("invoices", response.context)

    def test_invoice_detail_view(self):
        """
        Invoice detail is accessible by slug (number) for accounting staff.
        """
        self.client.force_login(self.user)
        url = reverse("accounting:invoice_detail", kwargs={"number": self.invoice.number})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["invoice"].serial, "INV-100")

    def test_invoice_create_view_post(self):
        """
        Basic test that posting a valid invoice form creates a new invoice.
        """
        self.client.force_login(self.user)
        url = reverse("accounting:invoice_create")

        data = {
            "customer": self.customer.pk,
            "number": "INV-200",
            "issued_at": timezone.now().date().isoformat(),
            "due_date": "",
            "description": "Test invoice",
            "total_amount": "150.000",
            "status": Invoice.Status.SENT,
        }

        response = self.client.post(url, data)
        # Expect redirect on success
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Invoice.objects.filter(number="INV-200", customer=self.customer).exists()
        )

    def test_invoice_payment_create_view_post(self):
        """
        Posting a valid payment for an invoice should create Payment and update invoice.
        """
        self.client.force_login(self.user)
        url = reverse(
            "accounting:invoice_add_payment",
            kwargs={"number": self.invoice.number},
        )

        data = {
            "date": timezone.now().date().isoformat(),
            "amount": "50.000",
            "method": Payment.Method.CASH,
            "notes": "Partial payment",
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

        # Check that payment is created
        payment_exists = Payment.objects.filter(
            invoice=self.invoice,
            customer=self.customer,
            amount=Decimal("50.000"),
        ).exists()
        self.assertTrue(payment_exists)

        # Check that invoice.paid_amount updated
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.paid_amount, Decimal("50.000"))
