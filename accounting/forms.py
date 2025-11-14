# accounting/forms.py
from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory

from website.models import Product
from .models import Invoice, Payment, Customer, InvoiceItem


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        # 👈 لاحظ: شلّينا number و total_amount من الحقول
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

        # تاريخ بصيغة Day-Month-Year
        self.fields["issued_at"].input_formats = ["%d-%m-%Y"]
        self.fields["due_date"].input_formats = ["%d-%m-%Y"]

    def clean(self):
        """
        Basic business validation:
        - due_date cannot be before issued_at
        (total_amount صار ينحسب من البنود، فما نتحقق عنه هنا)
        """
        cleaned = super().clean()

        issued_at = cleaned.get("issued_at")
        due_date = cleaned.get("due_date")
        if issued_at and due_date and due_date < issued_at:
            self.add_error("due_date", "Due date cannot be before issue date.")

        return cleaned




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
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount


InvoiceItemFormSet = inlineformset_factory(
    Invoice,
    InvoiceItem,
    fields=["product", "description", "quantity", "unit_price"],
    extra=1,
    can_delete=True,
)


class CustomerForm(forms.ModelForm):
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


class CustomerOrderForm(forms.Form):
    quantity = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0.01,
        label="الكمية المطلوبة",
    )
    notes = forms.CharField(
        label="ملاحظات إضافية (اختياري)",
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
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all(),
        label="الزبون",
    )
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True),
        label="المنتج",
    )
    quantity = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0.01,
        label="الكمية",
    )
    notes = forms.CharField(
        label="ملاحظات (اختياري)",
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


# ==========================
# Payment Recolonization form
# ==========================
class ApplyPaymentForm(forms.Form):
    """
    فورم لتسوية دفعة عامة على فاتورة معيّنة (كاملة أو جزئية).
    """
    invoice = forms.ModelChoiceField(
        queryset=Invoice.objects.none(),
        label="اختر الفاتورة",
        widget=forms.Select(attrs={
            "class": "form-select"
        })
    )
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=3,
        label="المبلغ المراد تسويته",
        widget=forms.NumberInput(attrs={
            "class": "form-control",
            "placeholder": "أدخل المبلغ"
        })
    )

    def __init__(self, customer, max_amount: Decimal, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # فواتير هذا الزبون فقط
        self.fields["invoice"].queryset = Invoice.objects.filter(customer=customer)
        self.max_amount = max_amount

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("المبلغ يجب أن يكون أكبر من صفر.")
        if amount > self.max_amount:
            raise forms.ValidationError("المبلغ أكبر من المبلغ المتاح في الدفعة.")
        return amount
