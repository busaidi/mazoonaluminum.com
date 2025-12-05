# sales/forms.py
from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from .models import SalesDocument, SalesLine, DeliveryNote, DeliveryLine


# ===================================================================
# أدوات مساعدة (Widgets)
# ===================================================================

class DateInput(forms.DateInput):
    """
    أداة مخصصة لإظهار تقويم HTML5
    بدلاً من حقل نص عادي.
    """
    input_type = 'date'


# ===================================================================
# نماذج مستند المبيعات (Sales Document)
# ===================================================================

class SalesDocumentForm(forms.ModelForm):
    """
    نموذج إنشاء وتعديل مستند المبيعات (الرأس / Header).
    """

    class Meta:
        model = SalesDocument
        fields = [
            'contact',
            'client_reference',
            'date',
            'due_date',
            'notes',
            'customer_notes',
        ]
        widgets = {
            'date': DateInput(attrs={'class': 'form-control'}),
            'due_date': DateInput(attrs={'class': 'form-control'}),
            # select2 تسهل البحث في قائمة العملاء الطويلة
            'contact': forms.Select(attrs={'class': 'form-control select2'}),
            'client_reference': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 3, 'placeholder': _('ملاحظات داخلية لفريق العمل...')}),
            'customer_notes': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 3, 'placeholder': _('ملاحظات تظهر في الطباعة للعميل...')}),
        }

    def clean(self):
        """
        تحقق إضافي: تاريخ الانتهاء لا يجب أن يكون قبل تاريخ المستند.
        """
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

    class Meta:
        model = SalesLine
        fields = ['product', 'description', 'quantity', 'uom', 'unit_price', 'discount_percent']
        widgets = {
            # هام: product-select ليتعرف عليه الجافا سكريبت ويجلب الوحدات
            'product': forms.Select(attrs={'class': 'form-control product-select'}),

            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('وصف إضافي...')}),

            # هام: qty-input للحساب التلقائي
            'quantity': forms.NumberInput(attrs={'class': 'form-control qty-input', 'step': '0.001'}),

            # هام: uom-select ليقوم الجافا سكريبت بتفريغه وتعبئته بالوحدات الصحيحة
            'uom': forms.Select(attrs={'class': 'form-control uom-select'}),

            # هام: price-input لتحديث السعر عند تغيير الوحدة أو المنتج
            'unit_price': forms.NumberInput(attrs={'class': 'form-control price-input', 'step': '0.001'}),

            # هام: discount-input لحساب الخصم
            'discount_percent': forms.NumberInput(attrs={'class': 'form-control discount-input', 'step': '0.01'}),
        }


# ===================================================================
# FormSet: لربط المستند ببنوده في صفحة واحدة
# ===================================================================

SalesLineFormSet = inlineformset_factory(
    SalesDocument,  # النموذج الأب
    SalesLine,  # النموذج الابن
    form=SalesLineForm,
    extra=1,  # عدد الأسطر الفارغة الإضافية
    can_delete=True,
)


# ===================================================================
# نماذج مذكرة التسليم (Delivery Note)
# ===================================================================

class DeliveryNoteForm(forms.ModelForm):
    """
    نموذج الرأس لمذكرة التسليم.
    """

    class Meta:
        model = DeliveryNote
        fields = ['contact', 'date', 'notes']
        widgets = {
            'date': DateInput(attrs={'class': 'form-control'}),
            'contact': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class DeliveryLineForm(forms.ModelForm):
    """
    نموذج سطر التسليم.
    """

    class Meta:
        model = DeliveryLine
        fields = ['product', 'description', 'quantity', 'uom']
        widgets = {
            # أضفنا الكلاسات هنا (product-select, uom-select)
            'product': forms.Select(attrs={'class': 'form-control product-select'}),
            'description': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control qty-input', 'step': '0.001'}),
            'uom': forms.Select(attrs={'class': 'form-control uom-select'}),
        }


# ===================================================================
# FormSet للتسليم
# ===================================================================

DeliveryLineFormSet = inlineformset_factory(
    DeliveryNote,
    DeliveryLine,
    form=DeliveryLineForm,
    extra=1,
    can_delete=True,
)