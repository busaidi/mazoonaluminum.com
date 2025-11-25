# sales/forms.py
from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from .models import SalesDocument, SalesLine


class SalesDocumentForm(forms.ModelForm):
    """
    Base form for SalesDocument.
    Kind will be fixed per view (quotation / order / delivery).
    """

    class Meta:
        model = SalesDocument
        fields = [
            "contact",
            "date",
            "due_date",
            "currency",
            "notes",
            "customer_notes",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "customer_notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "contact": _("العميل / جهة الاتصال"),
            "date": _("التاريخ"),
            "due_date": _("تاريخ الانتهاء / الصلاحية"),
            "currency": _("العملة"),
            "notes": _("ملاحظات داخلية"),
            "customer_notes": _("ملاحظات العميل (تظهر في المستند)"),
        }


class SalesLineForm(forms.ModelForm):
    """
    Line form used in inline formset for SalesDocument.
    """

    class Meta:
        model = SalesLine
        fields = [
            "product",
            "description",
            "quantity",
            "unit_price",
            "discount_percent",
        ]
        widgets = {
            "description": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
        }
        labels = {
            "product": _("المنتج"),
            "description": _("الوصف"),
            "quantity": _("الكمية"),
            "unit_price": _("سعر الوحدة"),
            "discount_percent": _("نسبة الخصم %"),
        }


SalesLineFormSet = inlineformset_factory(
    parent_model=SalesDocument,
    model=SalesLine,
    form=SalesLineForm,
    extra=3,
    can_delete=True,
)
