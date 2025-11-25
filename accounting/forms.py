# accounting/forms.py
from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _
from modeltranslation.forms import TranslationModelForm

from website.models import Product
from .models import Invoice, Payment, InvoiceItem, Order, OrderItem, Settings
from contacts.models import Contact


# ============================================================
# Invoice forms
# ============================================================

class InvoiceForm(forms.ModelForm):
    """
    Main staff invoice form (without number / total_amount fields).
    """

    class Meta:
        model = Invoice
        # NOTE: number & total_amount are excluded on purpose
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
        (total_amount is computed from items, so no check here)
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
# Payment forms
# ============================================================

class PaymentForInvoiceForm(forms.ModelForm):
    """
    Simple form to add a payment from the invoice screen.
    We do NOT expose customer/invoice fields; they are set in the view.
    """

    class Meta:
        model = Payment
        fields = ["date", "amount", "method", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes
        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")
            if name == "method":
                field.widget.attrs["class"] = (css + " form-select").strip()
            else:
                field.widget.attrs["class"] = (css + " form-control").strip()

    def clean_amount(self):
        """
        Ensure payment amount is strictly positive.
        """
        amount = self.cleaned_data.get("amount")
        if amount is not None and amount <= 0:
            raise forms.ValidationError(_("Amount must be greater than zero."))
        return amount



class PaymentForm(forms.ModelForm):
    """
    نموذج عام لإضافة دفعة:
    - اختيار العميل
    - (اختياري) ربطها بفاتورة
    """

    class Meta:
        model = Payment
        fields = ["customer", "invoice", "date", "amount", "method", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Bootstrap styling (select vs input)
        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")
            if name in ("customer", "invoice", "method"):
                field.widget.attrs["class"] = (css + " form-select").strip()
            else:
                field.widget.attrs["class"] = (css + " form-control").strip()

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is not None and amount <= 0:
            raise forms.ValidationError(_("Amount must be greater than zero."))
        return amount


class CustomerProfileForm(forms.ModelForm):
    """
    Form used in the customer customer to edit basic profile data (without user field).
    """

    class Meta:
        model = Contact
        fields = [
            "name",
            "company_name",
            "phone",
            "email",
            "tax_number",
            "address",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "company_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "tax_number": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


# ============================================================
# Simple order forms (customer + quick staff)
# ============================================================

class CustomerOrderForm(forms.Form):
    """
    Simple one-product order form from the customer customer.
    """
    quantity = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0.01,
        label=_("الكمية المطلوبة"),
    )
    notes = forms.CharField(
        label=_("ملاحظات إضافية (اختياري)"),
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Bootstrap styling
        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (css + " form-control").strip()


class StaffOrderForm(forms.Form):
    """
    Quick staff form: choose customer + product + quantity.
    """
    customer = forms.ModelChoiceField(
        queryset=Contact.objects.all(),
        label=_("الزبون"),
    )
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True),
        label=_("المنتج"),
    )
    quantity = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0.01,
        label=_("الكمية"),
    )
    notes = forms.CharField(
        label=_("ملاحظات (اختياري)"),
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Bootstrap styling: selects vs inputs
        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")
            if name in ("customer", "product"):
                field.widget.attrs["class"] = (css + " form-select").strip()
            else:
                field.widget.attrs["class"] = (css + " form-control").strip()


# ============================================================
# Order (staff) ModelForm + inline formset
# ============================================================

class OrderForm(forms.ModelForm):
    """
    Main staff order form (header fields only; items via formset).
    """

    class Meta:
        model = Order
        fields = ["customer", "status", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")
            if name in ("customer", "status"):
                field.widget.attrs["class"] = (css + " form-select").strip()
            else:
                field.widget.attrs["class"] = (css + " form-control").strip()


OrderItemFormSet = inlineformset_factory(
    Order,
    OrderItem,
    fields=["product", "uom", "description", "quantity", "unit_price"],
    extra=1,
    can_delete=True,
)


# ============================================================
# Payment allocation (general payment → specific invoice)
# ============================================================

class ApplyPaymentForm(forms.Form):
    """
    Form to allocate a general payment to a specific invoice
    (full or partial amount).
    """
    invoice = forms.ModelChoiceField(
        queryset=Invoice.objects.none(),
        label=_("اختر الفاتورة"),
        widget=forms.Select(
            attrs={
                "class": "form-select",
            }
        ),
    )
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=3,
        label=_("المبلغ المراد تسويته"),
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "placeholder": _("أدخل المبلغ"),
            }
        ),
    )

    def __init__(self, customer, max_amount: Decimal, *args, **kwargs):
        """
        customer   → filter invoices for this customer only.
        max_amount → available amount from the original general payment.
        """
        super().__init__(*args, **kwargs)

        # Invoices of this customer only
        self.fields["invoice"].queryset = Invoice.objects.filter(customer=customer)
        self.max_amount = max_amount

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError(_("المبلغ يجب أن يكون أكبر من صفر."))
        if amount > self.max_amount:
            raise forms.ValidationError(_("المبلغ أكبر من المبلغ المتاح في الدفعة."))
        return amount



class SettingsForm(forms.ModelForm):
    class Meta:
        model = Settings
        fields = [
            # ---------- Order numbering ----------
            "order_prefix",
            "order_padding",
            "order_start_value",
            "order_reset_policy",
            "order_custom_pattern",

            # ---------- Invoice numbering ----------
            "invoice_prefix",
            "invoice_padding",
            "invoice_start_value",
            "invoice_reset_policy",
            "invoice_custom_pattern",

            # ---------- Payment numbering ----------
            "payment_prefix",
            "payment_padding",
            "payment_start_value",
            "payment_reset_policy",
            "payment_custom_pattern",

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
            # ====== Order numbering ======
            "order_prefix": forms.TextInput(
                attrs={"class": "form-control", "dir": "ltr"}
            ),
            "order_padding": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "max": 10}
            ),
            "order_start_value": forms.NumberInput(
                attrs={"class": "form-control", "min": 1}
            ),
            "order_reset_policy": forms.Select(
                attrs={"class": "form-select"}
            ),
            "order_custom_pattern": forms.TextInput(
                attrs={"class": "form-control", "dir": "ltr"}
            ),

            # ====== Invoice numbering ======
            "invoice_prefix": forms.TextInput(
                attrs={"class": "form-control", "dir": "ltr"}
            ),
            "invoice_padding": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "max": 10}
            ),
            "invoice_start_value": forms.NumberInput(
                attrs={"class": "form-control", "min": 1}
            ),
            "invoice_reset_policy": forms.Select(
                attrs={"class": "form-select"}
            ),
            "invoice_custom_pattern": forms.TextInput(
                attrs={"class": "form-control", "dir": "ltr"}
            ),

            # ====== Payment numbering ======
            "payment_prefix": forms.TextInput(
                attrs={"class": "form-control", "dir": "ltr"}
            ),
            "payment_padding": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "max": 10}
            ),
            "payment_start_value": forms.NumberInput(
                attrs={"class": "form-control", "min": 1}
            ),
            "payment_reset_policy": forms.Select(
                attrs={"class": "form-select"}
            ),
            "payment_custom_pattern": forms.TextInput(
                attrs={"class": "form-control", "dir": "ltr"}
            ),

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
            # ----- Order numbering -----
            "order_prefix": _("بادئة أرقام الطلبات"),
            "order_padding": _("عدد الخانات الرقمية للطلبات"),
            "order_start_value": _("قيمة البداية لتسلسل الطلبات"),
            "order_reset_policy": _("سياسة إعادة الترقيم للطلبات"),
            "order_custom_pattern": _("نمط ترقيم الطلبات (اختياري)"),

            # ----- Invoice numbering -----
            "invoice_prefix": _("بادئة أرقام الفواتير"),
            "invoice_padding": _("عدد الخانات الرقمية للفواتير"),
            "invoice_start_value": _("قيمة البداية لتسلسل الفواتير"),
            "invoice_reset_policy": _("سياسة إعادة الترقيم للفواتير"),
            "invoice_custom_pattern": _("نمط الترقيم المخصص (اختياري)"),

            # ----- Payment numbering -----
            "payment_prefix": _("بادئة أرقام الدفعات"),
            "payment_padding": _("عدد الخانات الرقمية للدفعات"),
            "payment_start_value": _("قيمة البداية لتسلسل الدفعات"),
            "payment_reset_policy": _("سياسة إعادة الترقيم للدفعات"),
            "payment_custom_pattern": _("نمط ترقيم الدفعات (اختياري)"),

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

    # ====== Prefix cleaning ======
    def clean_order_prefix(self):
        prefix = self.cleaned_data.get("order_prefix", "") or ""
        return prefix.strip().upper()

    def clean_invoice_prefix(self):
        prefix = self.cleaned_data.get("invoice_prefix", "") or ""
        return prefix.strip().upper()

    def clean_payment_prefix(self):
        prefix = self.cleaned_data.get("payment_prefix", "") or ""
        return prefix.strip().upper()

    # ====== VAT ======
    def clean_default_vat_rate(self):
        rate = self.cleaned_data.get("default_vat_rate")
        if rate is None:
            return rate
        if rate < 0 or rate > 100:
            raise forms.ValidationError(_("نسبة الضريبة يجب أن تكون بين 0 و 100٪."))
        return rate

    # ====== Pattern validation ======
    def clean_order_custom_pattern(self):
        pattern = self.cleaned_data.get("order_custom_pattern", "") or ""
        if pattern and "{seq" not in pattern:
            raise forms.ValidationError(_("نمط ترقيم الطلبات يجب أن يحتوي على {seq}."))
        return pattern

    def clean_invoice_custom_pattern(self):
        pattern = self.cleaned_data.get("invoice_custom_pattern", "") or ""
        if pattern and "{seq" not in pattern:
            raise forms.ValidationError(_("نمط الترقيم المخصص يجب أن يحتوي على {seq}."))
        return pattern

    def clean_payment_custom_pattern(self):
        pattern = self.cleaned_data.get("payment_custom_pattern", "") or ""
        if pattern and "{seq" not in pattern:
            raise forms.ValidationError(_("نمط ترقيم الدفعات يجب أن يحتوي على {seq}."))
        return pattern
