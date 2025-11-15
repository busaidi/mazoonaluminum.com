# accounting/forms.py
from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from website.models import Product
from .models import Invoice, Payment, Customer, InvoiceItem, Order, OrderItem


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

# ============================================================
# Customer forms
# ============================================================

class CustomerForm(forms.ModelForm):
    """
    Staff form to create / update customers from accounting screens.
    """

    class Meta:
        model = Customer
        fields = [
            "name",
            "company_name",
            "phone",
            "email",
            "tax_number",
            "address",
        ]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add Bootstrap on all fields
        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (css + " form-control").strip()


class CustomerProfileForm(forms.ModelForm):
    """
    Form used in the customer portal to edit basic profile data (without user field).
    """

    class Meta:
        model = Customer
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
# Simple order forms (portal + quick staff)
# ============================================================

class CustomerOrderForm(forms.Form):
    """
    Simple one-product order form from the customer portal.
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
        queryset=Customer.objects.all(),
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
    fields=["product", "description", "quantity", "unit_price"],
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
