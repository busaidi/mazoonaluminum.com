# sales/forms.py

from django import forms
from django.forms.models import BaseInlineFormSet, inlineformset_factory
from django.utils.translation import gettext_lazy as _

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
                    "placeholder": _("Optional description..."),
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

    def clean(self):
        """
        Basic per-line validation.

        - Skip completely untouched forms (handled by formset).
        - If quantity > 0, require either product or description.
        """
        cleaned_data = super().clean()
        product = cleaned_data.get("product")
        description = cleaned_data.get("description")
        quantity = cleaned_data.get("quantity") or 0

        # Skip validation for completely empty forms (handled at formset level)
        if not self.has_changed():
            return cleaned_data

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
    form=SalesLineForm,
    formset=BaseSalesLineFormSet,
    extra=5,          # one empty row by default
    can_delete=True,  # allow deleting lines
    min_num=0,        # we enforce "at least one" in clean()
    validate_min=False,
)
