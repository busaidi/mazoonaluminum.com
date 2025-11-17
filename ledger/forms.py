# ledger/forms.py
from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Account, JournalEntry, FiscalYear, Journal


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
        fields = ["date", "reference", "description", "journal"]
        labels = {
            "date": _("التاريخ"),
            "reference": _("المرجع"),
            "description": _("الوصف"),
            "journal": _("دفتر اليومية"),
        }
        widgets = {
            "date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control form-control-sm",
                }
            ),
            "reference": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
            "description": forms.Textarea(
                attrs={"class": "form-control form-control-sm", "rows": 2}
            ),
            "journal": forms.Select(
                attrs={"class": "form-select form-select-sm"}
            ),
        }

    def __init__(self, *args, **kwargs):
        """
        ضبط كويِري سِت للدفاتر:
        - فقط الدفاتر النشطة
        - مرتبة بالكود
        """
        super().__init__(*args, **kwargs)
        # نستخدم المانجر: Journal.objects.active()
        self.fields["journal"].queryset = (
            Journal.objects.active().order_by("code")
        )
        self.fields["journal"].label = _("دفتر اليومية")
        self.fields["journal"].empty_label = _("اختر دفتر اليومية")


class JournalLineForm(forms.Form):
    account = forms.ModelChoiceField(
        queryset=Account.objects.active(),
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
        min_value=0,
        label=_("مدين"),
        widget=forms.NumberInput(
            attrs={"class": "form-control form-control-sm"}
        ),
    )
    credit = forms.DecimalField(
        max_digits=12,
        decimal_places=3,
        required=False,
        min_value=0,
        label=_("دائن"),
        widget=forms.NumberInput(
            attrs={"class": "form-control form-control-sm"}
        ),
    )

    DELETE = forms.BooleanField(
        required=False,
        label=_("حذف؟"),
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def clean(self):
        """
        تحقق مخصص للسطر:
        - لا يسمح بالقيم السالبة
        - لا يمكن أن يكون مدينًا ودائنًا في نفس الوقت
        - إذا في مبلغ لازم يكون في حساب
        """
        cleaned_data = super().clean()
        debit = cleaned_data.get("debit") or Decimal("0")
        credit = cleaned_data.get("credit") or Decimal("0")
        account = cleaned_data.get("account")

        # لا يسمح بالقيم السالبة
        if debit < 0:
            self.add_error("debit", _("قيمة المدين لا يمكن أن تكون سالبة."))

        if credit < 0:
            self.add_error("credit", _("قيمة الدائن لا يمكن أن تكون سالبة."))

        # لا يسمح أن يكون السطر مدينًا ودائنًا معاً
        if debit > 0 and credit > 0:
            raise forms.ValidationError(
                _("لا يمكن أن يكون السطر مدينًا ودائنًا في نفس الوقت.")
            )

        # تحقق من وجود حساب إذا كان هناك مبلغ
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
        queryset=Account.objects.active(),
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


class FiscalYearForm(forms.ModelForm):
    class Meta:
        model = FiscalYear
        fields = ["year", "start_date", "end_date", "is_closed", "is_default"]
        labels = {
            "year": _("السنة"),
            "start_date": _("تاريخ البداية"),
            "end_date": _("تاريخ النهاية"),
            "is_closed": _("مقفلة؟"),
            "is_default": _("سنة افتراضية للتقارير؟"),
        }
        widgets = {
            "start_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control form-control-sm"}
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control form-control-sm"}
            ),
            "is_default": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("start_date")
        end = cleaned_data.get("end_date")

        if start and end and start > end:
            raise forms.ValidationError(
                _("تاريخ البداية لا يمكن أن يكون بعد تاريخ النهاية.")
            )
        # TODO
        # لو حاب مستقبلاً تمنع جعل سنة مقفلة افتراضية، تقدر تضيف هنا تحقق
        # لكن حالياً الإقفال يتم من View مستقل، فمش ضروري
        return cleaned_data


class JournalEntryFilterForm(forms.Form):
    """
    Simple filter form for journal entries list:
    - Text search (reference/description)
    - Date range
    - Posted status
    - Journal
    """

    POSTED_CHOICES = (
        ("", _("الكل")),
        ("posted", _("مُرحّل")),
        ("draft", _("مسودة")),
    )

    q = forms.CharField(
        required=False,
        label=_("بحث"),
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "placeholder": _("بحث بالمرجع أو الوصف"),
            }
        ),
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
    posted = forms.ChoiceField(
        required=False,
        label=_("الحالة"),
        choices=POSTED_CHOICES,
        widget=forms.Select(
            attrs={"class": "form-select form-select-sm"},
        ),
    )
    journal = forms.ModelChoiceField(
        required=False,
        label=_("دفتر اليومية"),
        queryset=Journal.objects.active().order_by("code"),
        widget=forms.Select(
            attrs={"class": "form-select form-select-sm"},
        ),
    )
