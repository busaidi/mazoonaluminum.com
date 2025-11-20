from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ledger.models import (
    LedgerSettings,
    FiscalYear,
    JournalEntry,
    JournalLine,
)


def post_sales_invoice_to_ledger(invoice, *, user=None):
    """
    ترحيل فاتورة مبيعات إلى دفتر الأستاذ.
    يعتمد على:
    - دفتر المبيعات من LedgerSettings.sales_journal
    - حساب العملاء من LedgerSettings.sales_receivable_account
    - حساب المبيعات 0٪ من LedgerSettings.sales_revenue_0_account
    """
    if invoice.ledger_entry_id is not None:
        return invoice.ledger_entry

    if invoice.total_amount <= 0:
        # توحيد الأسلوب مع باقي الرسائل:
        raise ValueError("لا يمكن ترحيل فاتورة إجماليها صفر أو أقل.")

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
            reference=invoice.serial,
            description=f"Sales invoice {invoice.serial} for {invoice.customer.name}",
            posted=True,
            posted_at=timezone.now(),
            posted_by=posted_by,
        )

        # Debit: Accounts receivable
        JournalLine.objects.create(
            entry=entry,
            account=ar_account,
            debit=amount,
            credit=Decimal("0"),
            description=f"Invoice {invoice.serial} - customer receivable",
        )

        # Credit: Sales revenue
        JournalLine.objects.create(
            entry=entry,
            account=revenue_account,
            debit=Decimal("0"),
            credit=amount,
            description=f"Invoice {invoice.serial} - sales revenue",
        )

        invoice.ledger_entry = entry
        invoice.save(update_fields=["ledger_entry"])

        return entry


def unpost_sales_invoice_from_ledger(invoice, reversal_date=None, user=None):
    """
    إلغاء ترحيل فاتورة مبيعات من دفتر الأستاذ:
    - إنشاء قيد عكسي جديد.
    - إزالة الربط invoice.ledger_entry.
    - إعادة حالة الفاتورة إلى DRAFT.
    """
    if invoice.ledger_entry_id is None:
        return None

    if invoice.paid_amount and invoice.paid_amount > 0:
        raise ValueError("لا يمكن إلغاء ترحيل فاتورة عليها دفعات.")

    original_entry = invoice.ledger_entry
    reversal_date = reversal_date or timezone.now().date()

    fiscal_year = FiscalYear.for_date(reversal_date)
    if fiscal_year is None:
        raise ValueError("لا توجد سنة مالية تغطي تاريخ الإلغاء.")

    posted_by = user if user and user.is_authenticated else None

    with transaction.atomic():
        reversal_entry = JournalEntry.objects.create(
            fiscal_year=fiscal_year,
            journal=original_entry.journal,
            date=reversal_date,
            reference=original_entry.reference,
            description=f"Reversal of {original_entry.serial} for invoice {invoice.serial}",
            posted=True,
            posted_at=timezone.now(),
            posted_by=posted_by,
        )

        # Reverse all lines (swap debit/credit)
        for line in original_entry.lines.all():
            JournalLine.objects.create(
                entry=reversal_entry,
                account=line.account,
                debit=line.credit,
                credit=line.debit,
                description=f"Reversal of line #{line.pk} from {original_entry.serial}",
            )

        invoice.ledger_entry = None
        invoice.status = invoice.Status.DRAFT
        invoice.save(update_fields=["ledger_entry", "status"])

        return reversal_entry


# =====================================================================
# Orders → Invoices (service)
# =====================================================================

def convert_order_to_invoice(order, *, issued_at=None):
    """
    Convert a sales order into an invoice and link them together.

    Behaviour matches the existing view logic:
    - Create an invoice for the same customer.
    - Copy all order items into invoice items.
    - Compute total from item subtotals.
    - Link order.invoice to the created invoice.
    - Try to mark order as CONFIRMED if the constant exists.

    NOTE:
    - This function does NOT inject any hard-coded terms.
      Terms are left to the Invoice model / settings logic.
    """
    InvoiceModel = order._meta.apps.get_model("accounting", "Invoice")
    InvoiceItemModel = order._meta.apps.get_model("accounting", "InvoiceItem")

    invoice = InvoiceModel(
        customer=order.customer,
        status=InvoiceModel.Status.DRAFT,
        description=order.notes or "",
        issued_at=issued_at or timezone.now(),
    )
    invoice.total_amount = Decimal("0")
    invoice.save()  # number generated in model

    total = Decimal("0")
    invoice_items = []
    for item in order.items.all():
        inv_item = InvoiceItemModel(
            invoice=invoice,
            product=item.product,
            description=item.description,
            quantity=item.quantity,
            unit_price=item.unit_price,
        )
        invoice_items.append(inv_item)
        total += inv_item.subtotal

    InvoiceItemModel.objects.bulk_create(invoice_items)

    invoice.total_amount = total
    invoice.save(update_fields=["total_amount"])

    # Link order → invoice and optionally confirm order
    order.invoice = invoice
    update_fields = ["invoice"]
    status_confirmed = getattr(order, "STATUS_CONFIRMED", None)
    if status_confirmed is not None:
        order.status = status_confirmed
        update_fields.append("status")
    order.save(update_fields=update_fields)

    return invoice


# =====================================================================
# General payment allocation (service)
# =====================================================================

def allocate_general_payment(payment, invoice, amount: Decimal, *, partial_notes: str | None = None):
    """
    Allocate a general payment to a specific invoice.

    Rules:
    - 'payment' must currently have no invoice (general payment).
    - 'amount' must be > 0 and <= payment.amount.

    Cases:
    - Full allocation (amount == payment.amount):
        Attach the existing payment directly to the invoice.
    - Partial allocation (amount < payment.amount):
        Create a new payment for the invoice and reduce the
        amount of the original general payment.

    Returns:
        (is_full_allocation: bool, remaining_amount: Decimal, created_payment_or_none)
    """
    if amount <= 0 or amount > payment.amount:
        raise ValueError("قيمة المبلغ المراد تسويته غير صحيحة.")

    # Full allocation: attach this payment to the invoice
    if amount == payment.amount:
        payment.invoice = invoice
        payment.save(update_fields=["invoice"])
        return True, Decimal("0"), None

    # Partial: create a new payment for the invoice
    PaymentModel = payment.__class__
    new_payment = PaymentModel.objects.create(
        customer=payment.customer,
        invoice=invoice,
        amount=amount,
        date=payment.date,
        method=payment.method,
        notes=partial_notes or "",
    )

    payment.amount = payment.amount - amount
    payment.save(update_fields=["amount"])

    return False, payment.amount, new_payment
