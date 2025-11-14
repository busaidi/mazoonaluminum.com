# accounting/forms.py

from django import forms

from website.models import Product
from .models import Invoice, Payment, Customer


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = [
            "customer",
            "number",
            "issued_at",
            "due_date",
            "description",
            "terms",
            "total_amount",
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
        - total_amount must be > 0
        - due_date cannot be before issued_at
        """
        cleaned = super().clean()

        total_amount = cleaned.get("total_amount")
        if total_amount is not None and total_amount <= 0:
            self.add_error("total_amount", "Total amount must be greater than zero.")

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
