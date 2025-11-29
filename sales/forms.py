# sales/forms.py
from django import forms
from .models import SalesDocument, DeliveryNote


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
            "due_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "notes": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "customer_notes": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # لو مستند جديد → ثبّت النوع كعرض سعر قبل الفالديشن
        if not self.instance.pk:
            self.instance.kind = SalesDocument.Kind.QUOTATION



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
