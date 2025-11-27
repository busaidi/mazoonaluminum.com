# banking/forms.py
from django import forms
from django.utils.translation import gettext_lazy as _

from .models import BankStatement, BankAccount


class BankStatementForm(forms.ModelForm):
    class Meta:
        model = BankStatement
        fields = [
            "bank_account",
            "date_from",
            "date_to",
            "opening_balance",
            "closing_balance",
            "imported_file",
        ]
        widgets = {
            "bank_account": forms.Select(attrs={"class": "form-select"}),
            "date_from": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "date_to": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "opening_balance": forms.NumberInput(attrs={"step": "0.001", "class": "form-control"}),
            "closing_balance": forms.NumberInput(attrs={"step": "0.001", "class": "form-control"}),
            "imported_file": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }
        labels = {
            "bank_account": _("الحساب البنكي"),
            "date_from": _("من تاريخ"),
            "date_to": _("إلى تاريخ"),
            "opening_balance": _("الرصيد الافتتاحي"),
            "closing_balance": _("الرصيد الختامي"),
            "imported_file": _("ملف الكشف (اختياري)"),
        }


class BankAccountForm(forms.ModelForm):
    """
    فورم لإضافة / تعديل حساب بنكي.
    """

    class Meta:
        model = BankAccount
        fields = [
            "name",
            "account",
            "bank_name",
            "account_number",
            "iban",
            "currency",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "account": forms.Select(attrs={"class": "form-select"}),
            "bank_name": forms.TextInput(attrs={"class": "form-control"}),
            "account_number": forms.TextInput(attrs={"class": "form-control"}),
            "iban": forms.TextInput(attrs={"class": "form-control"}),
            "currency": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "name": _("اسم الحساب البنكي (داخلياً)"),
            "account": _("الحساب المحاسبي"),
            "bank_name": _("اسم البنك"),
            "account_number": _("رقم الحساب البنكي"),
            "iban": _("IBAN"),
            "currency": _("العملة"),
            "is_active": _("نشط"),
        }
        help_texts = {
            "account": _(
                "اختر الحساب من دليل الحسابات الذي يمثل هذا الحساب البنكي (غالباً من نوع أصول - بنك)."
            ),
        }
