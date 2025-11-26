from decimal import Decimal
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from openpyxl import load_workbook

from .models import (
    LedgerSettings,
    FiscalYear,
    JournalEntry,
    JournalLine, Account, Journal,
)

def build_lines_from_formset(line_formset):
    """
    يحوّل الفورم سِت لليست أسطر جاهزة للإنشاء + يحسب الإجماليات.

    يعتمد على:
    - clean() في JournalLineForm للتحقق الأساسي (القيم السالبة، مدين/دائن معاً، إلخ).
    - يتعامل مع DELETE + الأسطر الفارغة.

    يعيد:
    - lines: قائمة dict فيها بيانات كل سطر.
    - total_debit: مجموع المدين.
    - total_credit: مجموع الدائن.

    يرفع ValidationError في حال:
    - لا يوجد أي سطر صالح.
    """

    lines = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    has_any_line = False

    for order, form in enumerate(line_formset.forms):
        if form.cleaned_data.get("DELETE"):
            continue

        account = form.cleaned_data.get("account")
        description = form.cleaned_data.get("description") or ""
        debit = form.cleaned_data.get("debit") or Decimal("0")
        credit = form.cleaned_data.get("credit") or Decimal("0")

        # سطر فارغ بالكامل → تجاهل
        if not account and not description and debit == 0 and credit == 0:
            continue

        has_any_line = True

        lines.append(
            {
                "account": account,
                "description": description,
                "debit": debit,
                "credit": credit,
                "order": order,
            }
        )

        total_debit += debit
        total_credit += credit

    if not has_any_line:
        raise ValidationError(_("لا يوجد أي سطر صالح في القيد."))

    return lines, total_debit, total_credit


def ensure_default_chart_of_accounts():
    """
    ينشئ شجرة حسابات افتراضية أساسية إذا لم يكن هناك أي حساب في النظام.

    يعيد عدد الحسابات التي تم إنشاؤها.
    """

    if Account.objects.exists():
        # يوجد حسابات مسبقاً → لا نعمل شيء
        return 0

    accounts_data = [
        # code, name, type, allow_settlement
        ("1000", _("الصندوق"), Account.Type.ASSET, True),
        ("1010", _("البنك"), Account.Type.ASSET, True),
        ("1100", _("العملاء"), Account.Type.ASSET, True),
        ("1200", _("المخزون"), Account.Type.ASSET, False),

        ("2000", _("الموردون"), Account.Type.LIABILITY, True),

        ("3000", _("رأس المال"), Account.Type.EQUITY, False),

        ("4000", _("مبيعات"), Account.Type.REVENUE, False),

        ("5000", _("مشتريات"), Account.Type.EXPENSE, False),
        ("5100", _("مصروفات عمومية وإدارية"), Account.Type.EXPENSE, False),
    ]

    created_count = 0
    for code, name, acc_type, allow_settlement in accounts_data:
        Account.objects.create(
            code=code,
            name=name,
            type=acc_type,
            allow_settlement=allow_settlement,
        )
        created_count += 1

    return created_count


def _parse_bool(value):
    """
    Helper to parse boolean-ish values from Excel.
    Accepted truthy values: 1, true, yes, y (case-insensitive).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if not s:
        return None
    return s in {"1", "true", "yes", "y", "نعم", "صح"}


def import_chart_of_accounts_from_excel(
    file_obj,
    *,
    replace_existing: bool = False,
    fiscal_year: FiscalYear | None = None,
):
    """
    Import chart of accounts from an Excel file (xlsx).

    Expected columns:
      - code, name, type (required)
      - parent_code, allow_settlement, is_active (optional)
      - opening_debit, opening_credit (optional; used for opening balance)

    Behavior:
      - If account code exists → update.
      - Else → create.
      - If replace_existing=True → accounts not in file: is_active=False.
      - If file contains opening balances:
        * If fiscal_year is None → ValidationError (لازم تختار سنة).
        * Else → create ONE opening JournalEntry in that fiscal year.
    """

    wb = load_workbook(file_obj, data_only=True)
    ws = wb.active

    # --- header mapping ---
    header_map = {}
    for col in range(1, ws.max_column + 1):
        raw = ws.cell(row=1, column=col).value
        if raw is None:
            continue
        name = str(raw).strip().lower()
        if not name:
            continue
        header_map[name] = col

    required = ["code", "name", "type"]
    missing = [h for h in required if h not in header_map]
    if missing:
        raise ValidationError(
            _("Missing required columns in Excel: %(cols)s")
            % {"cols": ", ".join(missing)}
        )

    rows = []
    seen_codes: set[str] = set()
    errors: list[str] = []

    type_map = {
        "asset": Account.Type.ASSET,
        "liability": Account.Type.LIABILITY,
        "equity": Account.Type.EQUITY,
        "revenue": Account.Type.REVENUE,
        "expense": Account.Type.EXPENSE,
    }

    # --- read rows ---
    for row_idx in range(2, ws.max_row + 1):
        code_val = ws.cell(row=row_idx, column=header_map["code"]).value
        if code_val is None or str(code_val).strip() == "":
            continue

        code = str(code_val).strip()
        name = str(ws.cell(row=row_idx, column=header_map["name"]).value or "").strip()
        type_raw = ws.cell(row=row_idx, column=header_map["type"]).value

        if not name:
            errors.append(f"Row {row_idx}: empty name for code '{code}'")
            continue

        if not type_raw:
            errors.append(f"Row {row_idx}: empty type for code '{code}'")
            continue

        type_str = str(type_raw).strip().lower()
        if type_str not in type_map:
            errors.append(
                f"Row {row_idx}: invalid type '{type_str}' for code '{code}'. "
                "Expected one of: asset, liability, equity, revenue, expense."
            )
            continue

        parent_code = None
        if "parent_code" in header_map:
            parent_cell = ws.cell(row=row_idx, column=header_map["parent_code"]).value
            if parent_cell is not None:
                parent_code = str(parent_cell).strip() or None

        allow_settlement = None
        if "allow_settlement" in header_map:
            allow_cell = ws.cell(
                row=row_idx, column=header_map["allow_settlement"]
            ).value
            allow_settlement = _parse_bool(allow_cell)

        is_active = None
        if "is_active" in header_map:
            active_cell = ws.cell(row=row_idx, column=header_map["is_active"]).value
            is_active = _parse_bool(active_cell)

        # opening balances
        opening_debit = Decimal("0")
        opening_credit = Decimal("0")
        if "opening_debit" in header_map:
            val = ws.cell(row=row_idx, column=header_map["opening_debit"]).value
            if val not in (None, ""):
                opening_debit = Decimal(str(val))
        if "opening_credit" in header_map:
            val = ws.cell(row=row_idx, column=header_map["opening_credit"]).value
            if val not in (None, ""):
                opening_credit = Decimal(str(val))

        rows.append(
            {
                "row_idx": row_idx,
                "code": code,
                "name": name,
                "type": type_map[type_str],
                "parent_code": parent_code,
                "allow_settlement": allow_settlement,
                "is_active": is_active,
                "opening_debit": opening_debit,
                "opening_credit": opening_credit,
            }
        )
        seen_codes.add(code)

    created = 0
    updated = 0
    deactivated = 0

    with transaction.atomic():
        # --- create/update accounts ---
        accounts_by_code = {a.code: a for a in Account.objects.all()}

        for row in rows:
            code = row["code"]
            name = row["name"]
            acc_type = row["type"]
            allow_settlement = row["allow_settlement"]
            is_active = row["is_active"]

            defaults = {
                "name": name,
                "type": acc_type,
            }
            if allow_settlement is not None:
                defaults["allow_settlement"] = allow_settlement
            if is_active is not None:
                defaults["is_active"] = is_active

            if code in accounts_by_code:
                acc = accounts_by_code[code]
                for field, value in defaults.items():
                    setattr(acc, field, value)
                acc.parent = None
                acc.save()
                updated += 1
            else:
                acc = Account.objects.create(
                    code=code,
                    parent=None,
                    **defaults,
                )
                accounts_by_code[code] = acc
                created += 1

        # --- set parents ---
        for row in rows:
            code = row["code"]
            parent_code = row["parent_code"]
            if not parent_code:
                continue

            acc = accounts_by_code.get(code)
            parent = accounts_by_code.get(parent_code)
            if not parent:
                errors.append(
                    f"Row {row['row_idx']}: parent_code '{parent_code}' not found for account '{code}'."
                )
                continue

            if parent.code == acc.code:
                errors.append(
                    f"Row {row['row_idx']}: account '{code}' cannot be its own parent."
                )
                continue

            acc.parent = parent
            acc.save(update_fields=["parent"])

        # --- deactivate missing accounts if needed ---
        if replace_existing:
            qs = Account.objects.exclude(code__in=seen_codes)
            deactivated = qs.update(is_active=False)

        # --- opening balance logic ---
        # اجمع الأرصدة الافتتاحية
        opening_lines = []
        total_debit = Decimal("0")
        total_credit = Decimal("0")

        for row in rows:
            od = row["opening_debit"]
            oc = row["opening_credit"]
            if od == 0 and oc == 0:
                continue

            opening_lines.append((accounts_by_code[row["code"]], od, oc))
            total_debit += od
            total_credit += oc

        if opening_lines:
            # لو فيه رصيد افتتاحي في الملف ولا تم اختيار سنة مالية → خطأ منطقي
            if fiscal_year is None:
                raise ValidationError(
                    _(
                        "الملف يحتوي على أرصدة افتتاحية، "
                        "لكن لم يتم اختيار سنة مالية للرصد الافتتاحي."
                    )
                )

            if total_debit != total_credit:
                raise ValidationError(
                    _(
                        "الرصيد الافتتاحي غير متوازن: إجمالي المدين (%(debit)s) "
                        "لا يساوي إجمالي الدائن (%(credit)s)."
                    )
                    % {"debit": total_debit, "credit": total_credit}
                )

            # اختر دفتر الرصيد الافتتاحي من إعدادات الليدجر إن وجد،
            # وإذا مش مضبوط → استخدم الدفتر اليدوي الافتراضي،
            # وإذا حتى هذا مش مضبوط → ارجع للسلوك القديم get_default_for_manual_entry()
            settings_obj = LedgerSettings.get_solo()
            journal = (
                settings_obj.opening_balance_journal
                or settings_obj.default_manual_journal
                or Journal.objects.get_default_for_manual_entry()
            )

            # المرجع يبقى مرتبط بالسنة الجديدة (سنة الهدف)
            ref = f"OPENING-{fiscal_year.year}"

            # حاول نربط القيد بالسنة السابقة إن وجدت
            prev_fy = (
                FiscalYear.objects.filter(year=fiscal_year.year - 1)
                .order_by("-id")
                .first()
            )
            if prev_fy:
                entry_fiscal_year = prev_fy
                opening_date = prev_fy.end_date
            else:
                # لو ما فيه سنة سابقة، نخليها قبل بداية السنة بيوم وبدون سنة مالية
                entry_fiscal_year = None
                opening_date = fiscal_year.start_date - timedelta(days=1)

            # امسح أي قيد افتتاحي سابق بنفس المرجع (بغض النظر عن السنة المالية)
            JournalEntry.objects.filter(
                journal=journal,
                reference=ref,
            ).delete()

            entry = JournalEntry.objects.create(
                fiscal_year=entry_fiscal_year,
                journal=journal,
                date=opening_date,
                reference=ref,
                description=_("رصيد افتتاحي مستورد من إكسل"),
                posted=True,
                posted_at=timezone.now(),
            )

            order = 1
            for acc, od, oc in opening_lines:
                JournalLine.objects.create(
                    entry=entry,
                    account=acc,
                    description=_("رصيد افتتاحي"),
                    debit=od,
                    credit=oc,
                    order=order,
                )
                order += 1

    return {
        "created": created,
        "updated": updated,
        "deactivated": deactivated,
        "errors": errors,
    }



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
