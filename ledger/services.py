# ledger/services.py
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


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
