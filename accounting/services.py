# accounting/services.py

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ledger.models import (
    LedgerSettings,
    FiscalYear,
    JournalEntry,
    JournalLine,
    Account,
)


def post_sales_invoice_to_ledger(invoice, *, user=None):
    """
    ترحيل فاتورة مبيعات إلى دفتر الأستاذ.
    يعتمد على:
    - دفتر المبيعات من LedgerSettings.sales_journal
    - حساب العملاء من LedgerSettings.sales_receivable_account
    - حساب المبيعات 0٪ من LedgerSettings.sales_revenue_0_account
    (لاحقاً ممكن نوسّع للـ 5٪ والـ VAT حسب الفاتورة نفسها).
    """

    if invoice.ledger_entry_id is not None:
        return invoice.ledger_entry

    if invoice.total_amount <= 0:
        raise ValueError("Cannot post invoice with non-positive total amount.")

    settings_obj = LedgerSettings.get_solo()

    sales_journal = settings_obj.sales_journal
    if sales_journal is None:
        raise ValueError("يرجى ضبط دفتر المبيعات في إعدادات دفتر الأستاذ.")

    fiscal_year = FiscalYear.for_date(invoice.issued_at)
    if fiscal_year is None:
        raise ValueError("لا توجد سنة مالية تحتوي تاريخ الفاتورة.")

    ar_account = settings_obj.sales_receivable_account
    revenue_account = settings_obj.sales_revenue_0_account

    if ar_account is None or revenue_account is None:
        raise ValueError(
            "يرجى ضبط حساب العملاء وحساب المبيعات 0٪ في إعدادات دفتر الأستاذ."
        )

    amount = invoice.total_amount
    posted_by = user if user and user.is_authenticated else None

    with transaction.atomic():
        entry = JournalEntry.objects.create(
            fiscal_year=fiscal_year,
            journal=sales_journal,
            date=invoice.issued_at,
            reference=invoice.number,
            description=f"Sales invoice {invoice.number} for {invoice.customer.name}",
            posted=True,
            posted_at=timezone.now(),
            posted_by=posted_by,
        )

        # مدين: العملاء
        JournalLine.objects.create(
            entry=entry,
            account=ar_account,
            debit=amount,
            credit=Decimal("0"),
            description=f"Invoice {invoice.number} - customer receivable",
        )

        # دائن: المبيعات
        JournalLine.objects.create(
            entry=entry,
            account=revenue_account,
            debit=Decimal("0"),
            credit=amount,
            description=f"Invoice {invoice.number} - sales revenue",
        )

        invoice.ledger_entry = entry
        invoice.save(update_fields=["ledger_entry"])

        return entry



def unpost_sales_invoice_from_ledger(invoice, reversal_date=None, user=None):
    """
    Reverse the ledger posting for a sales invoice:
    - Create a reversing JournalEntry.
    - Clear invoice.ledger_entry.
    - Set invoice.status back to DRAFT.

    This is the 'إلغاء الترحيل' behavior (option 2).
    """

    # ما في قيد أصلاً؟
    if invoice.ledger_entry_id is None:
        return None

    # فاتورة فيها دفعات؟ حالياً نمنع إلغاء الترحيل
    if invoice.paid_amount and invoice.paid_amount > 0:
        raise ValueError("Cannot unpost an invoice that has payments.")

    original_entry = invoice.ledger_entry

    # تاريخ قيد الإلغاء: اليوم افتراضاً
    reversal_date = reversal_date or timezone.now().date()

    fiscal_year = FiscalYear.for_date(reversal_date)
    if fiscal_year is None:
        raise ValueError("No fiscal year found for reversal date.")

    posted_by = user if user and user.is_authenticated else None

    with transaction.atomic():
        reversal_entry = JournalEntry.objects.create(
            fiscal_year=fiscal_year,
            journal=original_entry.journal,
            date=reversal_date,
            reference=original_entry.reference,
            description=f"Reversal of {original_entry.number} for invoice {invoice.number}",
            posted=True,
            posted_at=timezone.now(),
            posted_by=posted_by,
        )

        # عكس كل السطور: المدين يصير دائن والعكس
        for line in original_entry.lines.all():
            JournalLine.objects.create(
                entry=reversal_entry,
                account=line.account,
                debit=line.credit,
                credit=line.debit,
                description=f"Reversal of line #{line.pk} from {original_entry.number}",
            )

        # فك الربط + رجوع الفاتورة لمسودة
        invoice.ledger_entry = None
        invoice.status = invoice.Status.DRAFT
        invoice.save(update_fields=["ledger_entry", "status"])

        return reversal_entry
