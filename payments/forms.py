# payments/forms.py

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Payment, PaymentMethod


class PaymentMethodForm(forms.ModelForm):
    class Meta:
        model = PaymentMethod
        fields = [
            "name",
            "code",
            "method_type",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "code": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "method_type": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class PaymentForm(forms.ModelForm):
    date = forms.DateField(
        label=_("تاريخ الدفع"),
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control form-control-sm",
            }
        ),
    )

    class Meta:
        model = Payment
        fields = [
            "direction",
            "contact",
            "method",
            "date",
            "amount",
            "currency",
            "reference",
            "notes",
        ]
        widgets = {
            "direction": forms.Select(
                attrs={"class": "form-select form-select-sm"}
            ),
            "contact": forms.Select(
                attrs={"class": "form-select form-select-sm"}
            ),
            "method": forms.Select(
                attrs={"class": "form-select form-select-sm"}
            ),
            "amount": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "step": "0.001",
                }
            ),
            "currency": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
            "reference": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
            "notes": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
        }
