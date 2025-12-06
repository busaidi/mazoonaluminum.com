# sales/forms.py
from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from .models import SalesDocument, SalesLine, DeliveryNote, DeliveryLine


# ===================================================================
# أدوات مساعدة (Widgets)
# ===================================================================

class DateInput(forms.DateInput):
    """أداة مخصصة لإظهار تقويم HTML5"""
    input_type = 'date'


# ===================================================================
# نماذج مستند المبيعات (Sales Document)
# ===================================================================

class SalesDocumentForm(forms.ModelForm):
    """
    نموذج إنشاء وتعديل مستند المبيعات (الرأس).
    """

    class Meta:
        model = SalesDocument
        fields = [
            'contact',
            'client_reference',
            'currency',
            'date',
            'due_date',
            'billing_address',
            'shipping_address',
            'notes',
            'customer_notes',
        ]
        widgets = {
            'date': DateInput(attrs={'class': 'form-control'}),
            'due_date': DateInput(attrs={'class': 'form-control'}),
            'contact': forms.Select(attrs={'class': 'form-control select2'}),
            'client_reference': forms.TextInput(attrs={'class': 'form-control'}),
            'currency': forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),

            'billing_address': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 2, 'placeholder': _('عنوان الفوترة')}),
            'shipping_address': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 2, 'placeholder': _('عنوان الشحن')}),

            'notes': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 3, 'placeholder': _('ملاحظات داخلية...')}),
            'customer_notes': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 3, 'placeholder': _('ملاحظات للعميل...')}),
        }

    def clean(self):
        cleaned_data = super().clean()
        date = cleaned_data.get("date")
        due_date = cleaned_data.get("due_date")

        if date and due_date and due_date < date:
            self.add_error('due_date', _("تاريخ الانتهاء لا يمكن أن يكون قبل تاريخ المستند."))
        return cleaned_data


class SalesLineForm(forms.ModelForm):
    """
    نموذج السطر الواحد (يستخدم داخل FormSet).
    """
    total_display = forms.CharField(
        required=False,
        disabled=True,
        label=_("الإجمالي"),
        widget=forms.TextInput(attrs={'class': 'form-control line-total', 'readonly': True})
    )

    class Meta:
        model = SalesLine
        fields = ['product', 'description', 'quantity', 'uom', 'unit_price', 'discount_percent']
        widgets = {
            'product': forms.Select(attrs={'class': 'form-control product-select'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('وصف...')}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control qty-input', 'step': '0.001', 'min': '0'}),
            'uom': forms.Select(attrs={'class': 'form-control uom-select'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control price-input', 'step': '0.001'}),
            'discount_percent': forms.NumberInput(
                attrs={'class': 'form-control discount-input', 'step': '0.01', 'min': '0', 'max': '100'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['total_display'].initial = self.instance.line_total


SalesLineFormSet = inlineformset_factory(
    SalesDocument,
    SalesLine,
    form=SalesLineForm,
    extra=1,
    can_delete=True,
)


# ===================================================================
# نماذج مذكرة التسليم (Delivery Note) - المرتبطة بأمر
# ===================================================================

class DeliveryNoteForm(forms.ModelForm):
    class Meta:
        model = DeliveryNote
        fields = ['date', 'notes']
        widgets = {
            'date': DateInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class DeliveryLineForm(forms.ModelForm):
    class Meta:
        model = DeliveryLine
        fields = ['product', 'description', 'quantity', 'uom']
        widgets = {
            'product': forms.Select(attrs={'class': 'form-control', 'disabled': True}),
            'description': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control qty-input', 'step': '0.001'}),
            'uom': forms.Select(attrs={'class': 'form-control', 'disabled': True}),
        }


DeliveryLineFormSet = inlineformset_factory(
    DeliveryNote,
    DeliveryLine,
    form=DeliveryLineForm,
    extra=0,
    can_delete=True,
)


# ===================================================================
# Direct Delivery Forms (تسليم مباشر بدون أمر)
# ===================================================================

class DirectDeliveryNoteForm(forms.ModelForm):
    class Meta:
        model = DeliveryNote
        fields = ['contact', 'date', 'notes']
        widgets = {
            'contact': forms.Select(attrs={'class': 'form-control select2'}),
            'date': DateInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class DirectDeliveryLineForm(forms.ModelForm):
    class Meta:
        model = DeliveryLine
        fields = ['product', 'description', 'quantity', 'uom']
        widgets = {
            'product': forms.Select(attrs={'class': 'form-control product-select'}),
            'description': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control qty-input', 'step': '0.001'}),
            'uom': forms.Select(attrs={'class': 'form-control uom-select'}),
        }


DirectDeliveryLineFormSet = inlineformset_factory(
    DeliveryNote,
    DeliveryLine,
    form=DirectDeliveryLineForm,
    extra=1,
    can_delete=True,
)


# ===================================================================
# نموذج ربط التسليم بأمر (Link Order)
# ===================================================================

class LinkOrderForm(forms.Form):
    order = forms.ModelChoiceField(
        queryset=SalesDocument.objects.none(),
        label=_("اختر أمر البيع"),
        widget=forms.Select(attrs={'class': 'form-control select2'}),
        empty_label=_("--- اختر الأمر المرتبط ---")
    )

    def __init__(self, *args, **kwargs):
        contact = kwargs.pop('contact', None)
        super().__init__(*args, **kwargs)
        if contact:
            self.fields['order'].queryset = SalesDocument.objects.filter(
                contact=contact,
                status=SalesDocument.Status.CONFIRMED,
                is_deleted=False
            ).order_by('-date')