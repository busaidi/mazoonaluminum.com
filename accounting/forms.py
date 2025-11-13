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
            "total_amount",
            "status",
        ]
        widgets = {
            "issued_at": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")
            if name in ("customer", "status"):
                field.widget.attrs["class"] = (css + " form-select").strip()
            else:
                field.widget.attrs["class"] = (css + " form-control").strip()


class PaymentForInvoiceForm(forms.ModelForm):
    """
    فورم بسيط لإضافة دفعة من شاشة الفاتورة.
    لا نعرض حقل customer ولا invoice؛ سنملأها في الفيو.
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
        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")
            if name == "method":
                field.widget.attrs["class"] = (css + " form-select").strip()
            else:
                field.widget.attrs["class"] = (css + " form-control").strip()

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
        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (css + " form-control").strip()


class CustomerProfileForm(forms.ModelForm):
    """
    فورم تعديل بيانات الزبون من بوابة الزبون (بدون user).
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