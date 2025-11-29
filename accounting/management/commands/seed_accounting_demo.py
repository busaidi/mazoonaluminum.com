from decimal import Decimal
from datetime import date

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from accounting.models import (
    FiscalYear,
    Account,
    Journal,
    JournalEntry,
    JournalLine,
    Invoice,
    InvoiceItem,
    Payment,
    PaymentMethod,
    PaymentReconciliation,
    LedgerSettings,
)
from contacts.models import Contact


User = get_user_model()


DEC = lambda x: Decimal(str(x)).quantize(Decimal("0.000"))


class Command(BaseCommand):
    help = "Seed demo accounting data: journals, entries, invoices, and payments."

    # --------------------------
    # Helpers
    # --------------------------
    def get_account(self, code: str) -> Account:
        try:
            return Account.objects.get(code=code)
        except Account.DoesNotExist:
            raise SystemExit(f"Account with code {code} does not exist. "
                             f"Run the chart-of-accounts seeder first.")

    def get_or_create_fiscal_year(self) -> FiscalYear:
        today = date.today()
        fy, created = FiscalYear.objects.get_or_create(
            year=today.year,
            defaults={
                "start_date": date(today.year, 1, 1),
                "end_date": date(today.year, 12, 31),
                "is_default": True,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created fiscal year {fy.year}"))
        return fy

    def get_or_create_journals(self):
        journals = {}

        journals["general"], _ = Journal.objects.get_or_create(
            code="GEN",
            defaults={
                "name": "دفتر القيود العامة",
                "type": Journal.Type.GENERAL,
                "is_default": True,
            },
        )
        journals["sales"], _ = Journal.objects.get_or_create(
            code="SAL",
            defaults={
                "name": "دفتر المبيعات",
                "type": Journal.Type.SALES,
            },
        )
        journals["purchase"], _ = Journal.objects.get_or_create(
            code="PUR",
            defaults={
                "name": "دفتر المشتريات",
                "type": Journal.Type.PURCHASE,
            },
        )
        journals["bank"], _ = Journal.objects.get_or_create(
            code="BNK",
            defaults={
                "name": "دفتر البنك",
                "type": Journal.Type.BANK,
            },
        )
        journals["cash"], _ = Journal.objects.get_or_create(
            code="CASH",
            defaults={
                "name": "دفتر الكاش",
                "type": Journal.Type.CASH,
            },
        )

        return journals

    def configure_ledger_settings(self, journals):
        """
        Map default journals and main accounts (based on your Oman COA).
        """
        ls = LedgerSettings.get_solo()

        # Journals
        ls.default_manual_journal = journals["general"]
        ls.sales_journal = journals["sales"]
        ls.purchase_journal = journals["purchase"]
        ls.cash_journal = journals["cash"]
        ls.bank_journal = journals["bank"]

        # Accounts mapping (codes from the COA you provided)
        ls.sales_receivable_account = self.get_account("1120")
        ls.sales_revenue_0_account = self.get_account("4100")
        ls.sales_vat_output_account = self.get_account("2130")
        ls.sales_advance_account = self.get_account("3200")  # using retained earnings for demo

        ls.save()
        self.stdout.write(self.style.SUCCESS("LedgerSettings configured."))

    def get_or_create_payment_methods(self):
        cash, _ = PaymentMethod.objects.get_or_create(
            code="CASH",
            defaults={
                "name": "نقدي",
                "method_type": PaymentMethod.MethodType.CASH,
            },
        )
        bank, _ = PaymentMethod.objects.get_or_create(
            code="BANK",
            defaults={
                "name": "تحويل بنكي",
                "method_type": PaymentMethod.MethodType.BANK_TRANSFER,
            },
        )
        return cash, bank

    def get_or_create_contacts(self):
        customer, _ = Contact.objects.get_or_create(
            name_ar="عميل ديمو",
            defaults={
                "name_en": "Demo Customer",
                "is_customer": True,
                "is_supplier": False,
            },
        )
        supplier, _ = Contact.objects.get_or_create(
            name_ar="مورد ديمو",
            defaults={
                "name_en": "Demo Supplier",
                "is_customer": False,
                "is_supplier": True,
            },
        )
        return customer, supplier

    # --------------------------
    # Main handler
    # --------------------------
    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding demo accounting data..."))

        user = User.objects.filter(is_superuser=True).first()
        if not user:
            raise SystemExit("No superuser found. Create a superuser first.")

        fy = self.get_or_create_fiscal_year()
        journals = self.get_or_create_journals()
        self.configure_ledger_settings(journals)
        cash_method, bank_method = self.get_or_create_payment_methods()
        customer, supplier = self.get_or_create_contacts()

        today = timezone.now().date()
        now_dt = timezone.now()

        # ------------------------------------------------------------------
        # 1) Demo SALES invoice + journal entry + receipt payment
        # ------------------------------------------------------------------
        ar_account = self.get_account("1120")   # Accounts receivable
        sales_account = self.get_account("4100")
        vat_out_account = self.get_account("2130")
        bank_account = self.get_account("1112")  # Bank current account

        # Invoice total 1,050 (1,000 net + 5% VAT)
        invoice_sales = Invoice.objects.create(
            type=Invoice.InvoiceType.SALES,
            customer=customer,
            issued_at=today,
            due_date=today,
            description="Demo sales invoice with 5% VAT",
            status=Invoice.Status.PAID,  # already fully paid in this demo
        )

        InvoiceItem.objects.create(
            invoice=invoice_sales,
            description="Aluminum windows",
            quantity=Decimal("1.00"),
            unit_price=DEC("1050.000"),
        )
        invoice_sales.refresh_from_db()  # recalculate_totals ran in save()

        # Journal entry for the sales invoice
        je_sales = JournalEntry.objects.create(
            fiscal_year=fy,
            journal=journals["sales"],
            date=today,
            reference=f"INV-{invoice_sales.pk}",
            description="Posting demo sales invoice with VAT 5%",
            created_at=now_dt,
            created_by=user,
        )

        # DR Accounts Receivable 1050
        JournalLine.objects.create(
            entry=je_sales,
            account=ar_account,
            debit=DEC("1050.000"),
            credit=DEC("0.000"),
            order=1,
        )
        # CR Sales Revenue 1000
        JournalLine.objects.create(
            entry=je_sales,
            account=sales_account,
            debit=DEC("0.000"),
            credit=DEC("1000.000"),
            order=2,
        )
        # CR VAT Output 50
        JournalLine.objects.create(
            entry=je_sales,
            account=vat_out_account,
            debit=DEC("0.000"),
            credit=DEC("50.000"),
            order=3,
        )

        je_sales.posted = True
        je_sales.posted_at = now_dt
        je_sales.posted_by = user
        je_sales.save(update_fields=["posted", "posted_at", "posted_by"])

        # Link invoice to journal entry
        invoice_sales.ledger_entry = je_sales
        invoice_sales.save(update_fields=["ledger_entry"])

        # Payment (receipt) – customer pays full invoice
        payment_receipt = Payment.objects.create(
            type=Payment.Type.RECEIPT,
            contact=customer,
            method=bank_method,
            date=today,
            amount=invoice_sales.total_amount,
            currency="OMR",
            reference=f"RCPT-{invoice_sales.pk}",
            created_by=user,
        )

        # Journal entry for receipt
        je_receipt = JournalEntry.objects.create(
            fiscal_year=fy,
            journal=journals["bank"],
            date=today,
            reference=f"RCPT-{payment_receipt.pk}",
            description="Receipt from demo customer",
            created_at=now_dt,
            created_by=user,
        )

        # DR Bank 1050
        JournalLine.objects.create(
            entry=je_receipt,
            account=bank_account,
            debit=invoice_sales.total_amount,
            credit=DEC("0.000"),
            order=1,
        )
        # CR Accounts Receivable 1050
        JournalLine.objects.create(
            entry=je_receipt,
            account=ar_account,
            debit=DEC("0.000"),
            credit=invoice_sales.total_amount,
            order=2,
        )

        je_receipt.posted = True
        je_receipt.posted_at = now_dt
        je_receipt.posted_by = user
        je_receipt.save(update_fields=["posted", "posted_at", "posted_by"])

        payment_receipt.journal_entry = je_receipt
        payment_receipt.is_posted = True
        payment_receipt.posted_at = now_dt
        payment_receipt.save(update_fields=["journal_entry", "is_posted", "posted_at"])

        # Reconciliation payment -> invoice (full)
        PaymentReconciliation.objects.create(
            payment=payment_receipt,
            invoice=invoice_sales,
            amount=invoice_sales.total_amount,
            note="Demo full settlement of sales invoice",
        )
        invoice_sales.update_payment_status()

        # ------------------------------------------------------------------
        # 2) Demo PURCHASE invoice + journal entry + payment voucher
        # ------------------------------------------------------------------
        ap_account = self.get_account("2110")   # Accounts payable
        vat_in_account = self.get_account("1125")
        purchases_account = self.get_account("5100")

        # Supplier invoice total 840 (800 net + 40 VAT)
        invoice_purchase = Invoice.objects.create(
            type=Invoice.InvoiceType.PURCHASE,
            customer=supplier,  # same field name, used for both sides
            issued_at=today,
            due_date=today,
            description="Demo purchase invoice with 5% VAT",
            status=Invoice.Status.PAID,
        )

        InvoiceItem.objects.create(
            invoice=invoice_purchase,
            description="Aluminum profiles",
            quantity=Decimal("1.00"),
            unit_price=DEC("840.000"),
        )
        invoice_purchase.refresh_from_db()

        # Journal entry for purchase invoice
        je_purchase = JournalEntry.objects.create(
            fiscal_year=fy,
            journal=journals["purchase"],
            date=today,
            reference=f"PINV-{invoice_purchase.pk}",
            description="Posting demo purchase invoice with VAT 5%",
            created_at=now_dt,
            created_by=user,
        )

        # DR Purchases 800
        JournalLine.objects.create(
            entry=je_purchase,
            account=purchases_account,
            debit=DEC("800.000"),
            credit=DEC("0.000"),
            order=1,
        )
        # DR VAT Input 40
        JournalLine.objects.create(
            entry=je_purchase,
            account=vat_in_account,
            debit=DEC("40.000"),
            credit=DEC("0.000"),
            order=2,
        )
        # CR Accounts Payable 840
        JournalLine.objects.create(
            entry=je_purchase,
            account=ap_account,
            debit=DEC("0.000"),
            credit=DEC("840.000"),
            order=3,
        )

        je_purchase.posted = True
        je_purchase.posted_at = now_dt
        je_purchase.posted_by = user
        je_purchase.save(update_fields=["posted", "posted_at", "posted_by"])

        invoice_purchase.ledger_entry = je_purchase
        invoice_purchase.save(update_fields=["ledger_entry"])

        # Payment voucher to supplier (full amount)
        payment_voucher = Payment.objects.create(
            type=Payment.Type.PAYMENT,
            contact=supplier,
            method=bank_method,
            date=today,
            amount=invoice_purchase.total_amount,
            currency="OMR",
            reference=f"PAY-{invoice_purchase.pk}",
            created_by=user,
        )

        je_payment = JournalEntry.objects.create(
            fiscal_year=fy,
            journal=journals["bank"],
            date=today,
            reference=f"PAY-{payment_voucher.pk}",
            description="Payment to demo supplier",
            created_at=now_dt,
            created_by=user,
        )

        # DR Accounts Payable 840
        JournalLine.objects.create(
            entry=je_payment,
            account=ap_account,
            debit=invoice_purchase.total_amount,
            credit=DEC("0.000"),
            order=1,
        )
        # CR Bank 840
        JournalLine.objects.create(
            entry=je_payment,
            account=bank_account,
            debit=DEC("0.000"),
            credit=invoice_purchase.total_amount,
            order=2,
        )

        je_payment.posted = True
        je_payment.posted_at = now_dt
        je_payment.posted_by = user
        je_payment.save(update_fields=["posted", "posted_at", "posted_by"])

        payment_voucher.journal_entry = je_payment
        payment_voucher.is_posted = True
        payment_voucher.posted_at = now_dt
        payment_voucher.save(update_fields=["journal_entry", "is_posted", "posted_at"])

        PaymentReconciliation.objects.create(
            payment=payment_voucher,
            invoice=invoice_purchase,
            amount=invoice_purchase.total_amount,
            note="Demo full settlement of purchase invoice",
        )
        invoice_purchase.update_payment_status()

        self.stdout.write(self.style.SUCCESS("Demo accounting data created successfully."))
