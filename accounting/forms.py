# accounting/forms.py

from django import forms
from decimal import Decimal
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
    JournalEntry,
    Payment,
)


# ============================================================
# Bootstrap Mixin
# ============================================================

class BootstrapFormMixin:
    """
    Mixin to automatically add Bootstrap .form-control / .form-select / .form-check-input
    classes to fields.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            widget = field.widget
            css_class = widget.attrs.get("class", "")

            if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect)):
                css_class += " form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css_class += " form-select"
            else:
                css_class += " form-control"

            widget.attrs["class"] = css_class.strip()


# ============================================================
# Invoice forms
# ============================================================

class InvoiceForm(BootstrapFormMixin, forms.ModelForm):
    """
    Main invoice form (header fields only).
    Amounts (total, paid) are calculated automatically, so they are excluded.
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
            "issued_at": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 2}),
            "terms": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Customize customer label + ordering
        if "customer" in self.fields:
            self.fields["customer"].queryset = Contact.objects.order_by("name")
            self.fields["customer"].label = _("الطرف (العميل/المورد)")

    def clean(self):
        cleaned = super().clean()
        issued_at = cleaned.get("issued_at")
        due_date = cleaned.get("due_date")

        if issued_at and due_date and due_date < issued_at:
            self.add_error("due_date", _("تاريخ الاستحقاق لا يمكن أن يكون قبل تاريخ الفاتورة."))

        return cleaned


InvoiceItemFormSet = inlineformset_factory(
    Invoice,
    InvoiceItem,
    fields=["product", "description", "quantity", "unit_price"],
    extra=1,
    can_delete=True,
    widgets={
        "product": forms.Select(attrs={"class": "form-select product-select"}),
        "description": forms.TextInput(attrs={"class": "form-control"}),
        "quantity": forms.NumberInput(
            attrs={"class": "form-control qty-input", "step": "0.01"}
        ),
        "unit_price": forms.NumberInput(
            attrs={"class": "form-control price-input", "step": "0.001"}
        ),
    },
)


# ============================================================
# Settings Forms
# ============================================================

class SettingsForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Settings
        fields = [
            # Invoice behavior
            "default_due_days",
            "auto_confirm_invoice",
            "auto_post_to_ledger",
            # VAT behavior
            "default_vat_rate",
            "prices_include_vat",
            # Text templates
            "default_terms",
            "footer_notes",
        ]
        widgets = {
            "default_terms": forms.Textarea(attrs={"rows": 4}),
            "footer_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_default_vat_rate(self):
        rate = self.cleaned_data.get("default_vat_rate")
        if rate is not None and (rate < 0 or rate > 100):
            raise forms.ValidationError(_("نسبة الضريبة يجب أن تكون بين 0 و 100٪."))
        return rate


# ============================================================
# Accounts & Journals
# ============================================================

class AccountForm(BootstrapFormMixin, forms.ModelForm):
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


class JournalForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Journal
        fields = ["code", "name", "type", "is_default", "is_active"]

    def save(self, commit=True):
        """
        Ensure only one default journal at a time.
        """
        instance = super().save(commit=False)
        is_default = self.cleaned_data.get("is_default")

        if commit:
            instance.save()
            if is_default:
                Journal.objects.exclude(pk=instance.pk).update(is_default=False)

        return instance


# ============================================================
# Journal Entry Forms
# ============================================================

class JournalEntryForm(BootstrapFormMixin, forms.ModelForm):
    """
    Header form for manual journal entries.
    """

    class Meta:
        model = JournalEntry
        fields = ["date", "reference", "description", "journal"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "reference": forms.TextInput(),
            "description": forms.Textarea(attrs={"rows": 2}),
            "journal": forms.Select(),
        }


class JournalLineForm(forms.Form):
    """
    Simple line form for manual journal entry lines.
    Everything is required=False so we can do custom validation in the view later
    (for example: skip completely empty rows).
    """

    account = forms.ModelChoiceField(
        queryset=Account.objects.filter(is_active=True).order_by("code"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select account-select"}),
        label=_("الحساب"),
    )
    description = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
        label=_("الوصف"),
    )
    debit = forms.DecimalField(
        required=False,
        initial=0,
        max_digits=20,
        decimal_places=3,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "step": "0.001"}
        ),
        label=_("مدين"),
    )
    credit = forms.DecimalField(
        required=False,
        initial=0,
        max_digits=20,
        decimal_places=3,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "step": "0.001"}
        ),
        label=_("دائن"),
    )
    DELETE = forms.BooleanField(
        required=False,
        widget=forms.HiddenInput(),
    )


JournalLineFormSet = forms.formset_factory(
    JournalLineForm,
    extra=1,
    can_delete=True,
)


# ============================================================
# Ledger Settings Form
# ============================================================

class LedgerSettingsForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = LedgerSettings
        fields = [
            # Journals
            "default_manual_journal",
            "sales_journal",
            "purchase_journal",
            "cash_journal",
            "bank_journal",
            "opening_balance_journal",
            "closing_journal",
            # Accounts
            "sales_receivable_account",
            "sales_revenue_0_account",
            "sales_vat_output_account",
            "sales_advance_account",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Example: restrict receivable account to active asset accounts
        if "sales_receivable_account" in self.fields:
            self.fields["sales_receivable_account"].queryset = (
                Account.objects.active().filter(type=Account.Type.ASSET)
            )


# ============================================================
# Payment Form
# ============================================================

class PaymentForm(BootstrapFormMixin, forms.ModelForm):
    """
    Basic payment (receipt / payment voucher) form.
    """

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
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def clean_amount(self):
        """
        Extra guard (in addition to model validators) to avoid negative amounts.
        """
        amount = self.cleaned_data.get("amount")
        if amount is not None and amount <= 0:
            raise forms.ValidationError(_("المبلغ يجب أن يكون أكبر من صفر."))
        return amount


# ============================================================
# Fiscal Year & Reporting Filters
# ============================================================

class FiscalYearForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = FiscalYear
        fields = ["year", "start_date", "end_date", "is_closed", "is_default"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")

        if start and end and start > end:
            raise forms.ValidationError(_("تاريخ النهاية يجب أن يكون بعد تاريخ البداية."))

        return cleaned


class TrialBalanceFilterForm(BootstrapFormMixin, forms.Form):
    fiscal_year = forms.ModelChoiceField(
        queryset=FiscalYear.objects.order_by("-year"),
        required=False,
        label=_("السنة المالية"),
        empty_label=_("كل السنوات"),
    )
    date_from = forms.DateField(
        required=False,
        label=_("من تاريخ"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        required=False,
        label=_("إلى تاريخ"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )


class AccountLedgerFilterForm(TrialBalanceFilterForm):
    account = forms.ModelChoiceField(
        queryset=Account.objects.active().order_by("code"),
        required=False,
        label=_("الحساب"),
    )


class JournalEntryFilterForm(BootstrapFormMixin, forms.Form):
    POSTED_CHOICES = (
        ("", _("الكل")),
        ("posted", _("مُرحّل")),
        ("draft", _("مسودة")),
    )

    q = forms.CharField(
        required=False,
        label=_("بحث"),
        widget=forms.TextInput(attrs={"placeholder": _("بحث بالمرجع...")}),
    )
    date_from = forms.DateField(
        required=False,
        label=_("من"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        required=False,
        label=_("إلى"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    posted = forms.ChoiceField(
        required=False,
        label=_("الحالة"),
        choices=POSTED_CHOICES,
    )
    journal = forms.ModelChoiceField(
        required=False,
        label=_("الدفتر"),
        queryset=Journal.objects.active(),
    )


# ============================================================
# Chart of Accounts Import
# ============================================================

class ChartOfAccountsImportForm(BootstrapFormMixin, forms.Form):
    file = forms.FileField(label=_("ملف إكسل (.xlsx)"))
    replace_existing = forms.BooleanField(
        required=False,
        label=_("تعطيل الحسابات غير الموجودة"),
        initial=False,
    )
    fiscal_year = forms.ModelChoiceField(
        queryset=FiscalYear.objects.order_by("-year"),
        required=False,
        label=_("سنة الرصيد الافتتاحي"),
    )



class PaymentReconciliationForm(forms.Form):
    """
    نموذج لتسوية دفعة معينة مع مجموعة من الفواتير لنفس الطرف.
    يتم إنشاء حقل (مبلغ) لكل فاتورة بشكل ديناميكي في __init__.
    """

    def __init__(self, *args, payment: Payment, invoices, **kwargs):
        """
        :param payment: الدفعة المراد تسويتها
        :param invoices: قائمة الفواتير المفتوحة لنفس الطرف
        """
        super().__init__(*args, **kwargs)
        self.payment = payment
        self.invoices = invoices

        for invoice in invoices:
            field_name = self._field_name_for_invoice(invoice)
            # نحاول جلب أي تسوية سابقة لهذه الفاتورة مع هذه الدفعة
            allocation = invoice.allocations.filter(payment=payment).first()
            initial_amount = allocation.amount if allocation else Decimal("0.000")

            self.fields[field_name] = forms.DecimalField(
                label=_("المبلغ المخصص للفاتورة %(inv)s") % {
                    "inv": invoice.display_number
                },
                max_digits=12,
                decimal_places=3,
                required=False,
                initial=initial_amount,
                help_text=_("اتركه فارغًا أو صفر لإلغاء التخصيص لهذه الفاتورة."),
            )

    @staticmethod
    def _field_name_for_invoice(invoice: Invoice) -> str:
        return f"invoice_{invoice.pk}"

    def get_allocations_dict(self):
        """
        إرجاع قاموس {invoice_id: amount} مبني على البيانات المُدخلة في الفورم.
        """
        data = {}

        for invoice in self.invoices:
            field_name = self._field_name_for_invoice(invoice)
            value = self.cleaned_data.get(field_name)

            if value is None:
                # عدم تعبئة الحقل = نعتبره 0 (إلغاء أي تسوية سابقة)
                amount = Decimal("0.000")
            else:
                amount = Decimal(value)

            data[invoice.pk] = amount

        return data
