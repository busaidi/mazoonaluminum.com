# sales/forms.py
from django import forms
from django.forms import inlineformset_factory, modelformset_factory
from django.forms.formsets import formset_factory
from django.utils.translation import gettext_lazy as _

from .models import SalesDocument, SalesLine, DeliveryNote, DeliveryLine


# ===================================================================
# Widgets helpers
# ===================================================================

class DateInput(forms.DateInput):
    """HTML5 date input widget."""
    input_type = "date"


# ===================================================================
# Sales Document Forms
# ===================================================================

class SalesDocumentForm(forms.ModelForm):
    """
    Form for creating/updating the sales document header.
    """

    class Meta:
        model = SalesDocument
        fields = [
            "contact",
            "client_reference",
            "currency",
            "date",
            "due_date",
            "billing_address",
            "shipping_address",
            "notes",
            "customer_notes",
        ]
        widgets = {
            "date": DateInput(attrs={"class": "form-control"}),
            "due_date": DateInput(attrs={"class": "form-control"}),

            "contact": forms.Select(
                attrs={"class": "form-control select2"}
            ),
            "client_reference": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "currency": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "readonly": "readonly",
                }
            ),
            "billing_address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": _("عنوان الفوترة"),
                }
            ),
            "shipping_address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": _("عنوان الشحن"),
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": _("ملاحظات داخلية..."),
                }
            ),
            "customer_notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": _("ملاحظات للعميل..."),
                }
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        date = cleaned_data.get("date")
        due_date = cleaned_data.get("due_date")

        if date and due_date and due_date < date:
            self.add_error(
                "due_date",
                _("تاريخ الانتهاء لا يمكن أن يكون قبل تاريخ المستند."),
            )
        return cleaned_data


# ===================================================================
# Sales Line Forms
# ===================================================================

class SalesLineForm(forms.ModelForm):
    class Meta:
        model = SalesLine
        fields = [
            "product",
            "description",
            "quantity",
            "uom",
            "unit_price",
            "discount_percent",
        ]
        widgets = {
            "product": forms.Select(
                attrs={
                    "class": "form-control form-control-sm table-input product-select",
                }
            ),
            "description": forms.TextInput(
                attrs={
                    "class": "form-control description-input",
                    "placeholder": "أدخل وصفاً إضافياً لهذا البند...",
                }
            ),
            "quantity": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm table-input qty-input text-center",
                    "step": "0.001",
                    "min": "0",
                }
            ),
            "uom": forms.Select(
                attrs={
                    "class": "form-control form-control-sm table-input uom-select text-center",
                }
            ),
            "unit_price": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm table-input price-input text-end",
                    "step": "0.001",
                    "min": "0",
                }
            ),
            "discount_percent": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm table-input discount-input text-end",
                    "step": "0.01",
                    "min": "0",
                    "max": "100",
                }
            ),
        }

    def clean_quantity(self):
        qty = self.cleaned_data.get("quantity") or 0
        if qty <= 0:
            raise forms.ValidationError("الكمية يجب أن تكون أكبر من صفر.")
        return qty


SalesLineFormSet = inlineformset_factory(
    SalesDocument,
    SalesLine,
    form=SalesLineForm,
    extra=1,
    can_delete=True,
)


# ===================================================================
# Delivery Note Forms (linked to order)
# ===================================================================

class DeliveryNoteForm(forms.ModelForm):
    class Meta:
        model = DeliveryNote
        fields = ["date", "notes"]
        widgets = {
            "date": DateInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),
        }


class DeliveryLineForm(forms.ModelForm):
    """
    Delivery line when note is linked to a Sales Order:
    - product/uom تأتي من سطر المبيعات وتظهر فقط (disabled).
    - يجب تمرير sales_line كحقل مخفي لربط البيانات.
    """

    class Meta:
        model = DeliveryLine
        fields = ["sales_line", "product", "description", "quantity", "uom"]
        widgets = {
            "sales_line": forms.HiddenInput(),
            "product": forms.Select(
                attrs={"class": "form-control", "disabled": True}
            ),
            "description": forms.TextInput(
                attrs={"class": "form-control"}
            ),
            "quantity": forms.NumberInput(
                attrs={
                    "class": "form-control qty-input",
                    "step": "0.001",
                    "min": "0.001",
                }
            ),
            "uom": forms.Select(
                attrs={"class": "form-control", "disabled": True}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # الحقول المعطّلة لا تُرسل في POST، لذلك نخليها غير مطلوبة لتجاوز التحقق
        self.fields["product"].required = False
        self.fields["uom"].required = False
        # sales_line مطلوب لكي نتمكن من جلب البيانات منه
        self.fields["sales_line"].required = True

    def clean(self):
        cleaned_data = super().clean()

        sales_line = cleaned_data.get("sales_line")
        quantity = cleaned_data.get("quantity")

        # نحافظ على تعبئة المنتج والوحدة من سطر المبيعات
        if sales_line:
            self.instance.product = sales_line.product
            self.instance.uom = sales_line.uom

            if not cleaned_data.get("description"):
                self.instance.description = sales_line.description

        # 🔴 منع إدخال كمية أكبر من المتبقي في أمر البيع (تحقق فوري في الفورم)
        if sales_line and quantity is not None:
            remaining = sales_line.remaining_quantity
            if quantity > remaining:
                self.add_error(
                    "quantity",
                    _(
                        "كمية هذا التسليم (%(qty)s) تتجاوز الكمية المتبقية في أمر البيع "
                        "(المتاح حالياً: %(rem)s)."
                    )
                    % {
                        "qty": quantity,
                        "rem": remaining,
                    },
                )

        return cleaned_data



# هذا الفورمسيت يُستخدم في شاشة تعديل / عرض مذكرة تسليم موجودة
DeliveryLineFormSet = inlineformset_factory(
    DeliveryNote,
    DeliveryLine,
    form=DeliveryLineForm,
    extra=0,
    can_delete=True,
)

# ===================================================================
# Delivery From Order: FormSet مستقل مبني على DeliveryLineForm
# ===================================================================

DeliveryFromOrderLineFormSet = formset_factory(
    DeliveryLineForm,
    extra=0,
    can_delete=False,
)

# ===================================================================
# Direct Delivery Forms (تسليم مباشر بدون أمر)
# ===================================================================

class DirectDeliveryNoteForm(forms.ModelForm):
    class Meta:
        model = DeliveryNote
        fields = ["contact", "date", "notes"]
        widgets = {
            "contact": forms.Select(
                attrs={
                    "class": "form-control select2",
                }
            ),
            "date": DateInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),
        }


class DirectDeliveryLineForm(forms.ModelForm):
    """
    Delivery line for direct delivery (no order):
    - المستخدم يختار product/uom والكمية يدويًا.
    """
    class Meta:
        model = DeliveryLine
        fields = ["product", "description", "quantity", "uom"]
        widgets = {
            "product": forms.Select(
                attrs={
                    "class": "form-control product-select",
                }
            ),
            "description": forms.TextInput(
                attrs={
                    "class": "form-control",
                }
            ),
            "quantity": forms.NumberInput(
                attrs={
                    "class": "form-control qty-input",
                    "step": "0.001",
                    "min": "0.001",
                }
            ),
            "uom": forms.Select(
                attrs={
                    "class": "form-control uom-select",
                }
            ),
        }


DirectDeliveryLineFormSet = inlineformset_factory(
    DeliveryNote,
    DeliveryLine,
    form=DirectDeliveryLineForm,
    extra=1,
    can_delete=True,
)


# ===================================================================
# Link Order Form
# ===================================================================

class LinkOrderForm(forms.Form):
    order = forms.ModelChoiceField(
        queryset=SalesDocument.objects.none(),
        label=_("اختر أمر البيع"),
        widget=forms.Select(
            attrs={
                "class": "form-control select2",
            }
        ),
        empty_label=_("--- اختر الأمر المرتبط ---"),
    )

    def __init__(self, *args, **kwargs):
        contact = kwargs.pop("contact", None)
        super().__init__(*args, **kwargs)
        if contact:
            self.fields["order"].queryset = (
                SalesDocument.objects.filter(
                    contact=contact,
                    status=SalesDocument.Status.CONFIRMED,
                    is_deleted=False,
                )
                .order_by("-date")
            )
