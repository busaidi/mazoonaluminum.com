# ledger/forms.py
from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Account, JournalEntry, FiscalYear


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = [
            "code",
            "name",
            "type",
            "parent",
            "is_active",
            "allow_settlement",
        ]
        labels = {
            "code": _("الكود"),
            "name": _("اسم الحساب"),
            "type": _("النوع"),
            "parent": _("الحساب الأب"),
            "is_active": _("نشط؟"),
            "allow_settlement": _("يُستخدم في التسويات؟"),
        }


# ======= Journal Entry / Lines =======

class JournalEntryForm(forms.ModelForm):
    class Meta:
        model = JournalEntry
        # ما نخلي المستخدم يختار السنة المالية يدوياً الآن، نعيّنها من التاريخ تلقائياً
        fields = ["date", "reference", "description"]
        labels = {
            "date": _("التاريخ"),
            "reference": _("المرجع"),
            "description": _("الوصف"),
        }
        widgets = {
            "date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "description": forms.Textarea(
                attrs={"rows": 2, "class": "form-control"}
            ),
        }


class JournalLineForm(forms.Form):
    account = forms.ModelChoiceField(
        queryset=Account.objects.filter(is_active=True),
        required=False,
        label=_("الحساب"),
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    description = forms.CharField(
        max_length=255,
        required=False,
        label=_("الوصف"),
        widget=forms.TextInput(attrs={"class": "form-control form-control-sm"}),
    )
    debit = forms.DecimalField(
        max_digits=12,
        decimal_places=3,
        required=False,
        label=_("مدين"),
        widget=forms.NumberInput(attrs={"class": "form-control form-control-sm"}),
    )
    credit = forms.DecimalField(
        max_digits=12,
        decimal_places=3,
        required=False,
        label=_("دائن"),
        widget=forms.NumberInput(attrs={"class": "form-control form-control-sm"}),
    )
    DELETE = forms.BooleanField(
        required=False,
        label=_("حذف؟"),
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    # ✅ الإصلاح: إضافة تحقق مخصص
    def clean(self):
        cleaned_data = super().clean()
        debit = cleaned_data.get("debit") or Decimal("0")
        credit = cleaned_data.get("credit") or Decimal("0")
        account = cleaned_data.get("account")

        # ✅ لا يسمح بالقيم السالبة
        if debit < 0:
            self.add_error("debit", _("قيمة المدين لا يمكن أن تكون سالبة."))

        if credit < 0:
            self.add_error("credit", _("قيمة الدائن لا يمكن أن تكون سالبة."))

        # ✅ لا يسمح أن يكون السطر مدينًا ودائنًا معاً
        if debit > 0 and credit > 0:
            raise forms.ValidationError(
                _("لا يمكن أن يكون السطر مدينًا ودائنًا في نفس الوقت.")
            )

        # ✅ تحقق من وجود حساب إذا كان هناك مبلغ
        if (debit > 0 or credit > 0) and not account:
            raise forms.ValidationError(
                _("يجب اختيار حساب للسطر الذي يحتوي على مبلغ مدين أو دائن.")
            )

        return cleaned_data


JournalLineFormSet = forms.formset_factory(
    JournalLineForm,
    extra=2,
    can_delete=True,
)


# ======= Reports Forms =======

class TrialBalanceFilterForm(forms.Form):
    fiscal_year = forms.ModelChoiceField(
        queryset=FiscalYear.objects.order_by("-year"),
        required=False,
        label=_("السنة المالية"),
        empty_label=_("كل السنوات"),
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    date_from = forms.DateField(
        required=False,
        label=_("من تاريخ"),
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control form-control-sm"}
        ),
    )
    date_to = forms.DateField(
        required=False,
        label=_("إلى تاريخ"),
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control form-control-sm"}
        ),
    )


class AccountLedgerFilterForm(forms.Form):
    account = forms.ModelChoiceField(
        queryset=Account.objects.filter(is_active=True),
        required=False,
        label=_("الحساب"),
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    fiscal_year = forms.ModelChoiceField(
        queryset=FiscalYear.objects.order_by("-year"),
        required=False,
        label=_("السنة المالية"),
        empty_label=_("كل السنوات"),
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    date_from = forms.DateField(
        required=False,
        label=_("من تاريخ"),
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control form-control-sm"}
        ),
    )
    date_to = forms.DateField(
        required=False,
        label=_("إلى تاريخ"),
        widget=forms.DateInput(
            attrs={"type": "date", "class": "form-control form-control-sm"}
        ),
    )
