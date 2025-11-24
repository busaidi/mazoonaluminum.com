# uom/forms.py
from django import forms
from django.utils.translation import gettext_lazy as _

from .models import UnitOfMeasure


class UnitOfMeasureForm(forms.ModelForm):
    class Meta:
        model = UnitOfMeasure
        fields = [
            "name_ar",
            "name_en",
            "code",
            "symbol",
            "category",
            "is_active",
            "notes",
        ]

        labels = {
            "name_ar": _("الاسم (عربي)"),
            "name_en": _("الاسم (إنجليزي)"),
            "code": _("الكود"),
            "symbol": _("الرمز المختصر"),
            "category": _("الفئة"),
            "is_active": _("نشطة"),
            "notes": _("ملاحظات"),
        }

        help_texts = {
            "code": _("كود الوحدة مثل: M, KG, PCS, ROLL, BAR."),
            "symbol": _("اختياري: رمز قصير يظهر بجانب الأرقام."),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # إضافة كلاس Bootstrap
        for name, field in self.fields.items():
            widget = field.widget
            css = widget.attrs.get("class", "")
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = (css + " form-check-input").strip()
            else:
                widget.attrs["class"] = (css + " form-control").strip()
