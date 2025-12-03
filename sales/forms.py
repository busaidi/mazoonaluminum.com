# sales/forms.py

from django import forms
from django.forms.models import BaseInlineFormSet, inlineformset_factory
from django.utils.translation import gettext_lazy as _

from inventory.models import Product
from .models import SalesDocument, DeliveryNote, SalesLine


# ===================================================================
# SalesDocumentForm
# ===================================================================


class SalesDocumentForm(forms.ModelForm):
    """
    فورم مستند المبيعات:
    - لا نعرض حقل kind للمستخدم.
    - نثبّت النوع = QUOTATION عند الإنشاء.
    """

    class Meta:
        model = SalesDocument
        # لاحظ: حذفنا kind من الحقول
        fields = ["contact", "date", "due_date", "notes", "customer_notes"]
        widgets = {
            "contact": forms.Select(attrs={"class": "form-select"}),
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "due_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "customer_notes": forms.Textarea(
                attrs={"rows": 3, "class": "form-control"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # لو مستند جديد → ثبّت النوع كعرض سعر قبل الفالديشن
        if not self.instance.pk:
            self.instance.kind = SalesDocument.Kind.QUOTATION


    def clean(self):
        """
        التحقق من أن تاريخ الانتهاء لا يسبق تاريخ المستند.
        """
        cleaned_data = super().clean()
        date = cleaned_data.get("date")
        due_date = cleaned_data.get("due_date")

        if date and due_date and due_date < date:
            self.add_error("due_date", _("Due date cannot be before document date."))

        return cleaned_data


# ===================================================================
# DeliveryNoteForm
# ===================================================================


class DeliveryNoteForm(forms.ModelForm):
    """
    فورم مذكرة التسليم.
    (order يُحدد من الـ URL وليس من الفورم)
    """

    class Meta:
        model = DeliveryNote
        fields = ["date", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }


# ===================================================================
# SalesLineForm + Inline Formset
# ===================================================================


class SalesLineForm(forms.ModelForm):
    """
    Single sales line form used in the inline formset.
    line_total is computed on the model, so it is not exposed here.
    """

    # 👈 حقل كود المنتج (فورم فقط، ليس من الموديل)
    product_code = forms.CharField(
        label=_("Product code"),
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "placeholder": _("e.g. MZN-46-FRAME"),
                "autocomplete": "off",
            }
        ),
        help_text=_("Enter internal product code to search quickly."),
    )

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
            "product": forms.Select(
                attrs={
                    "class": "form-select form-select-sm",
                }
            ),
            "description": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    # 👈 نخليه واضح أنه وصف السطر (manual) مثل أودو
                    "placeholder": _("Optional line description (shown on document)…"),
                }
            ),
            "quantity": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm text-end",
                    "step": "0.001",
                    "min": "0",
                }
            ),
            "unit_price": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm text-end",
                    "step": "0.001",
                    "min": "0",
                }
            ),
            "discount_percent": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm text-end",
                    "step": "0.01",
                    "min": "0",
                    "max": "100",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # لو السطر مربوط بمنتج، عبّي product_code تلقائيًا من product.code
        product = getattr(self.instance, "product", None)
        if product and hasattr(product, "code") and not self.initial.get("product_code"):
            self.initial["product_code"] = product.code

    def clean(self):
        """
        Basic per-line validation.

        - Skip completely untouched forms (handled by formset).
        - If quantity > 0, require either product or description.
        - If product_code is filled and product is empty, try to resolve by code.
        """
        cleaned_data = super().clean()

        product = cleaned_data.get("product")
        description = cleaned_data.get("description")
        quantity = cleaned_data.get("quantity") or 0
        code = cleaned_data.get("product_code")

        # Skip validation for completely empty forms (handled at formset level)
        if not self.has_changed():
            return cleaned_data

        # 🧩 1) لو فيه كود وما حُدِّد منتج من السلكت → نحاول نجيبه من Product.code
        if code and not product:
            try:
                product = Product.objects.get(code__iexact=code.strip())
                cleaned_data["product"] = product
                self.instance.product = product
            except Product.DoesNotExist:
                self.add_error(
                    "product_code",
                    _("No product found with this code."),
                )
                # نرجع مباشرة، عشان ما نكمل باقي الفالديشن على سطر فاسد
                return cleaned_data

        # 🧩 2) التحقق من أن السطر له معنى
        if quantity > 0 and not (product or description):
            raise forms.ValidationError(
                _("You must select a product or enter a description for this line.")
            )

        return cleaned_data


class BaseSalesLineFormSet(BaseInlineFormSet):
    """
    Inline formset for sales lines.

    - Ensures at least one non-deleted, non-empty line.
    - You can extend this later for cross-line validations.
    """

    def clean(self):
        super().clean()

        has_valid_line = False

        for form in self.forms:
            # Some forms may not have cleaned_data (e.g., invalid forms)
            if not hasattr(form, "cleaned_data"):
                continue

            # Skip forms marked for deletion
            if form.cleaned_data.get("DELETE", False):
                continue

            # Skip forms that did not change at all
            if not form.has_changed():
                continue

            product = form.cleaned_data.get("product")
            description = form.cleaned_data.get("description")
            quantity = form.cleaned_data.get("quantity") or 0
            unit_price = form.cleaned_data.get("unit_price") or 0

            # Consider this a meaningful line if it has some content
            if product or description or quantity or unit_price:
                has_valid_line = True

        # If we require at least one line, enforce it here
        if self.total_form_count() > 0 and not has_valid_line:
            raise forms.ValidationError(
                _("You must add at least one sales line.")
            )



SalesLineFormSet = inlineformset_factory(
    parent_model=SalesDocument,
    model=SalesLine,
    form=SalesLineForm,          # 👈 نفس الفورم
    formset=BaseSalesLineFormSet,
    extra=5,
    can_delete=True,
    min_num=0,
    validate_min=False,
)