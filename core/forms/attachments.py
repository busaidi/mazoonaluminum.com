# core/forms.py
from django import forms
from django.utils.translation import gettext_lazy as _

from core.models import Attachment


class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Attachment
        fields = ["file", "title", "description"]
        widgets = {
            "file": forms.FileInput(attrs={"class": "form-control"}),
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(
                attrs={"class": "form-control", "rows": 2}
            ),
        }
        labels = {
            "file": _("الملف"),
            "title": _("عنوان المرفق"),
            "description": _("وصف (اختياري)"),
        }

    def clean_file(self):
        f = self.cleaned_data.get("file")
        if not f:
            return f

        # حد الحجم 10MB
        max_size = 10 * 1024 * 1024
        if f.size > max_size:
            raise forms.ValidationError(_("حجم الملف أكبر من 10 ميغابايت."))

        # منع بعض الإمتدادات
        blocked_ext = [".exe", ".bat", ".cmd", ".sh"]
        name = f.name.lower()
        if any(name.endswith(ext) for ext in blocked_ext):
            raise forms.ValidationError(_("نوع الملف غير مسموح."))

        return f
