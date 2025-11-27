# accounting/forms.py
from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from contacts.models import Contact

from .models import (
    Invoice,
    InvoiceItem,
    Settings,
    Journal,
    LedgerSettings,
    FiscalYear,
    Account,
    JournalEntry, Payment,
)


# ============================================================
# Invoice forms
# ============================================================


from contacts.models import Contact
from django.utils.translation import gettext_lazy as _

class InvoiceForm(forms.ModelForm):
    """
    Main staff invoice form (header fields only).
    total_amount يُحسب من البنود، لذلك غير موجود في الفورم.
    """

    class Meta:
        model = Invoice
        fields = [
            "customer",
            "issued_at",
            "due_date",
            "description",
            "terms",
            "status",
        ]
        widgets = {
            "issued_at": forms.DateInput(
                format="%d-%m-%Y",
                attrs={
                    "placeholder": "DD-MM-YYYY",
                },
            ),
            "due_date": forms.DateInput(
                format="%d-%m-%Y",
                attrs={
                    "placeholder": "DD-MM-YYYY",
                },
            ),
            "description": forms.Textarea(attrs={"rows": 3}),
            "terms": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 🔹 ربط حقل الزبون بالـ Contact
        if "customer" in self.fields:
            # لو عندك فلاج is_customer في الموديل:
            # self.fields["customer"].queryset = Contact.objects.filter(is_customer=True).order_by("name")
            # حالياً نخليها كل الكونتاكت عشان تتأكد أنها تشتغل:
            self.fields["customer"].queryset = Contact.objects.order_by("name")
            self.fields["customer"].label = _("الزبون")

        # Bootstrap classes: select vs input
        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")
            if name in ("customer", "status"):
                field.widget.attrs["class"] = (css + " form-select").strip()
            else:
                field.widget.attrs["class"] = (css + " form-control").strip()

        # Input formats as Day-Month-Year
        self.fields["issued_at"].input_formats = ["%d-%m-%Y"]
        self.fields["due_date"].input_formats = ["%d-%m-%Y"]

    def clean(self):
        """
        Basic business validation:
        - due_date cannot be before issued_at
        """
        cleaned = super().clean()

        issued_at = cleaned.get("issued_at")
        due_date = cleaned.get("due_date")
        if issued_at and due_date and due_date < issued_at:
            self.add_error("due_date", _("Due date cannot be before issue date."))

        return cleaned



InvoiceItemFormSet = inlineformset_factory(
    Invoice,
    InvoiceItem,
    fields=["product", "description", "quantity", "unit_price"],
    extra=1,
    can_delete=True,
)


# ============================================================
# Sales / Invoice Settings (بدون ترقيم الآن)
# ============================================================


class SettingsForm(forms.ModelForm):
    """
    إعدادات الفواتير/المبيعات:
    - أيام الاستحقاق
    - سلوك الترحيل التلقائي
    - الضريبة
    - النصوص الافتراضية
    """

    class Meta:
        model = Settings
        fields = [
            # ---------- Invoice behavior ----------
            "default_due_days",
            "auto_confirm_invoice",
            "auto_post_to_ledger",

            # ---------- VAT behavior ----------
            "default_vat_rate",
            "prices_include_vat",

            # ---------- Text templates ----------
            "default_terms",
            "footer_notes",
        ]

        widgets = {
            # ====== Invoice behavior ======
            "default_due_days": forms.NumberInput(
                attrs={"class": "form-control", "min": 0, "max": 365}
            ),
            "auto_confirm_invoice": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "auto_post_to_ledger": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),

            # ====== VAT behavior ======
            "default_vat_rate": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "prices_include_vat": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),

            # ====== Text templates ======
            "default_terms": forms.Textarea(
                attrs={"class": "form-control", "rows": 4}
            ),
            "footer_notes": forms.Textarea(
                attrs={"class": "form-control", "rows": 3}
            ),
        }

        labels = {
            # ----- Invoice behavior -----
            "default_due_days": _("أيام الاستحقاق الافتراضية"),
            "auto_confirm_invoice": _("اعتماد الفاتورة تلقائيًا بعد الحفظ"),
            "auto_post_to_ledger": _("ترحيل تلقائي إلى دفتر الأستاذ بعد الاعتماد"),

            # ----- VAT behavior -----
            "default_vat_rate": _("نسبة ضريبة القيمة المضافة الافتراضية (%)"),
            "prices_include_vat": _("الأسعار شاملة للضريبة"),

            # ----- Text templates -----
            "default_terms": _("الشروط والأحكام الافتراضية"),
            "footer_notes": _("ملاحظات أسفل الفاتورة"),
        }

    def clean_default_vat_rate(self):
        rate = self.cleaned_data.get("default_vat_rate")
        if rate is None:
            return rate
        if rate < 0 or rate > 100:
            raise forms.ValidationError(_("نسبة الضريبة يجب أن تكون بين 0 و 100٪."))
        return rate


# ============================================================
# Accounts
# ============================================================


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
        widgets = {
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "type": forms.Select(attrs={"class": "form-select"}),
            "parent": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "allow_settlement": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
        }


# ============================================================
# Journal Entry / Lines
# ============================================================


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
        ضبط QuerySet للدفاتر:
        - فقط الدفاتر النشطة
        - مرتبة بالكود
        """
        super().__init__(*args, **kwargs)
        self.fields["journal"].queryset = (
            Journal.objects.active().order_by("code")
        )
        self.fields["journal"].label = _("دفتر اليومية")
        self.fields["journal"].empty_label = _("اختر دفتر اليومية")


class JournalLineForm(forms.Form):
    account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.active()

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


# ============================================================
# Reports Forms
# ============================================================


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
        queryset=Account.objects.none(),
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
            attrs={"type": "date", "class": "form-control form-control-sm"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.active()


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
            "year": forms.NumberInput(
                attrs={"class": "form-control form-control-sm"}
            ),
            "start_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control form-control-sm"}
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control form-control-sm"}
            ),
            "is_closed": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
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


# ============================================================
# Chart of accounts import
# ============================================================


class ChartOfAccountsImportForm(forms.Form):
    file = forms.FileField(
        label=_("ملف إكسل لشجرة الحسابات"),
        help_text=_(
            "ملف بصيغة .xlsx يحتوي في الصف الأول على الأعمدة: "
            "code, name, type, parent_code, allow_settlement, is_active, "
            "opening_debit, opening_credit."
        ),
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control"}
        ),
    )
    replace_existing = forms.BooleanField(
        required=False,
        label=_("تعطيل الحسابات غير الموجودة في الملف"),
        help_text=_(
            "سيتم تعيين is_active=False لأي حساب ليس موجودًا في الملف المستورد."
        ),
        widget=forms.CheckboxInput(
            attrs={"class": "form-check-input"}
        ),
    )
    fiscal_year = forms.ModelChoiceField(
        queryset=FiscalYear.objects.order_by("-year"),
        required=False,
        label=_("السنة المالية للرصد الافتتاحي"),
        help_text=_(
            "اختياري: إذا اخترت سنة مالية، سيتم إنشاء قيد رصيد افتتاحي بهذه الأرصدة."
        ),
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )


# ============================================================
# Ledger settings & Journals
# ============================================================


class LedgerSettingsForm(forms.ModelForm):
    class Meta:
        model = LedgerSettings
        fields = [
            # دفاتر اليومية
            "default_manual_journal",
            "sales_journal",
            "purchase_journal",
            "cash_journal",
            "bank_journal",
            "opening_balance_journal",
            "closing_journal",

            # الحسابات الافتراضية للمبيعات
            "sales_receivable_account",
            "sales_revenue_0_account",
            "sales_vat_output_account",
            "sales_advance_account",
        ]

        widgets = {
            field: forms.Select(attrs={"class": "form-select"})
            for field in fields
        }

        labels = {
            # دفاتر اليومية
            "default_manual_journal": _("دفتر القيود اليدوية"),
            "sales_journal": _("دفتر المبيعات"),
            "purchase_journal": _("دفتر المشتريات"),
            "cash_journal": _("دفتر الكاش"),
            "bank_journal": _("دفتر البنك"),
            "opening_balance_journal": _("دفتر الرصيد الافتتاحي"),
            "closing_journal": _("دفتر إقفال السنة المالية"),

            # الحسابات (من LedgerSettings الجديدة)
            "sales_receivable_account": _("حساب العملاء (ذمم مدينة)"),
            "sales_revenue_0_account": _("حساب المبيعات 0٪ / صادرات"),
            "sales_vat_output_account": _("حساب ضريبة القيمة المضافة (مخرجات)"),
            "sales_advance_account": _("حساب الدفعات المقدّمة من العملاء"),
        }


class JournalForm(forms.ModelForm):
    class Meta:
        model = Journal
        fields = ["code", "name", "type", "is_default", "is_active"]
        widgets = {
            "code": forms.TextInput(attrs={"class": "form-control"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "type": forms.Select(attrs={"class": "form-select"}),
            "is_default": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "code": _("كود الدفتر"),
            "name": _("اسم الدفتر"),
            "type": _("نوع الدفتر"),
            "is_default": _("دفتر افتراضي"),
            "is_active": _("نشط"),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)

        is_default = self.cleaned_data.get("is_default")

        if commit:
            instance.save()

        if is_default:
            # عطّل الافتراضية عن غيره
            Journal.objects.exclude(pk=instance.pk).update(is_default=False)

            # لو ما عندنا LedgerSettings، ننشئه تلقائيًا
            settings_obj = LedgerSettings.get_solo()
            if settings_obj.default_manual_journal is None:
                settings_obj.default_manual_journal = instance
                settings_obj.save()

        return instance


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = [
            "type",
            "contact",
            "method",
            "date",
            "amount",
            "currency",
            "reference",
            "notes",
        ]
        labels = {
            "type": _("نوع الحركة"),
            "contact": _("الطرف"),
            "method": _("طريقة الدفع"),
            "date": _("التاريخ"),
            "amount": _("المبلغ"),
            "currency": _("العملة"),
            "reference": _("مرجع خارجي"),
            "notes": _("ملاحظات"),
        }
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ستايل Bootstrap خفيف
        for name, field in self.fields.items():
            css = "form-control form-control-sm"
            if isinstance(field.widget, (forms.Select, forms.SelectMultiple)):
                css = "form-select form-select-sm"
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (existing + " " + css).strip()