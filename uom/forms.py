# uom/forms.py
from django import forms
from django.utils.translation import gettext_lazy as _
from .models import UnitOfMeasure, UomCategory


class UomCategoryForm(forms.ModelForm):
    class Meta:
        model = UomCategory
        # ✅ FIX: استدعاء حقول الترجمة صراحةً
        fields = [
            "code",
            "name_ar", "name_en",
            "description_ar", "description_en",
            "is_active"
        ]

        labels = {
            "code": _("كود الفئة"),
            "name_ar": _("الاسم (عربي)"),
            "name_en": _("الاسم (إنجليزي)"),
            "description_ar": _("الوصف (عربي)"),
            "description_en": _("الوصف (إنجليزي)"),
            "is_active": _("نشطة"),
        }

        widgets = {
            "description_ar": forms.Textarea(attrs={"rows": 2}),
            "description_en": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # تنسيق Bootstrap الموحد
        for field in self.fields.values():
            if isinstance(field.widget, (forms.TextInput, forms.Textarea)):
                field.widget.attrs.setdefault("class", "form-control")
            elif isinstance(field.widget, (forms.CheckboxInput,)):
                field.widget.attrs.setdefault("class", "form-check-input")


class UnitOfMeasureForm(forms.ModelForm):
    class Meta:
        model = UnitOfMeasure
        # ✅ FIX: إضافة حقول الترجمة للرمز والملاحظات أيضاً
        fields = [
            "category",
            "code",
            "name_ar", "name_en",
            "symbol_ar", "symbol_en",
            "notes_ar", "notes_en",
            "is_active",
        ]

        labels = {
            "category": _("الفئة"),
            "code": _("الكود"),
            "name_ar": _("اسم الوحدة (عربي)"),
            "name_en": _("اسم الوحدة (إنجليزي)"),
            "symbol_ar": _("الرمز (عربي)"),
            "symbol_en": _("الرمز (إنجليزي)"),
            "notes_ar": _("ملاحظات (عربي)"),
            "notes_en": _("ملاحظات (إنجليزي)"),
            "is_active": _("نشطة"),
        }

        widgets = {
            "notes_ar": forms.Textarea(attrs={"rows": 2}),
            "notes_en": forms.Textarea(attrs={"rows": 2}),
        }

        help_texts = {
            "code": _("مثال: M, KG, PCS"),
            "symbol_ar": _("مثال: م، كجم"),
            "symbol_en": _("مثال: m, kg"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["category"].empty_label = _("اختر الفئة...")

        # تنسيق Bootstrap
        for name, field in self.fields.items():
            widget = field.widget
            # الحفاظ على الكلاسات الموجودة وإضافة كلاسات بوتستراب
            css = widget.attrs.get("class", "")

            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = (css + " form-check-input").strip()
            elif isinstance(widget, (forms.TextInput, forms.Textarea, forms.Select)):
                widget.attrs["class"] = (css + " form-control").strip()