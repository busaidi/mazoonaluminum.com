# banking/forms.py
import os
from django import forms
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from .models import BankStatement, BankAccount


# ---------------------------------------------------------
# Mixin لتنسيق البوتستراب تلقائياً
# ---------------------------------------------------------
class BootstrapFormMixin:
    """
    كلاس مساعد يضيف كلاسات CSS الخاصة بالبوتستراب لكل الحقول تلقائياً
    بدلاً من تكرارها في كل Widget.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            # إذا كان الحقل Checkbox نستخدم تنسيقاً مختلفاً
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': 'form-check-input'})
            else:
                field.widget.attrs.update({'class': 'form-control'})


# ---------------------------------------------------------
# 1. فورم الحساب البنكي
# ---------------------------------------------------------
class BankAccountForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = [
            "name",
            "account",
            "bank_name",
            "account_number",
            "iban",
            "currency",
            "is_active",
        ]
        labels = {
            "name": _("الاسم التعريفي"),
            "account": _("حساب الأستاذ (GL)"),
            "bank_name": _("اسم البنك"),
            "account_number": _("رقم الحساب"),
            "iban": _("IBAN"),
            "currency": _("العملة"),
            "is_active": _("حساب نشط"),
        }
        help_texts = {
            "name": _("مثال: الحساب الجاري - بنك مسقط"),
            "account": _("الحساب المحاسبي المرتبط في شجرة الحسابات"),
        }

    def clean_account(self):
        """
        تحقق إضافي: التأكد أن حساب الأستاذ المختار ليس مربوطاً بحساب بنكي آخر.
        (رغم أن OneToOneField يمنع ذلك، لكن رسالة الفورم تكون أوضح للمستخدم)
        """
        account = self.cleaned_data.get('account')
        # نستثني الحساب الحالي في حالة التعديل (self.instance.pk)
        if (BankAccount.objects.filter(account=account)
                .exclude(pk=self.instance.pk)
                .exists()):
            raise ValidationError(_("عذراً، هذا الحساب المحاسبي مرتبط بالفعل بحساب بنكي آخر."))
        return account


# ---------------------------------------------------------
# 2. فورم كشف الحساب
# ---------------------------------------------------------
class BankStatementForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BankStatement
        fields = [
            "bank_account",
            "name",
            "date",
            "start_balance",
            "end_balance",
            "imported_file",
        ]
        widgets = {
            # تحديد نوع الحقل كتاريخ ليظهر التقويم في المتصفح
            "date": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {
            "bank_account": _("الحساب البنكي"),
            "name": _("وصف الكشف"),
            "date": _("تاريخ الكشف"),
            "start_balance": _("الرصيد الافتتاحي"),
            "end_balance": _("الرصيد الختامي"),
            "imported_file": _("ملف الحركات (Excel/CSV)"),
        }

    def clean_imported_file(self):
        """
        التحقق من امتداد الملف المرفوع.
        نقبل فقط ملفات Excel أو CSV.
        """
        file = self.cleaned_data.get('imported_file')
        if file:
            ext = os.path.splitext(file.name)[1].lower()  # استخراج الامتداد
            valid_extensions = ['.csv', '.xls', '.xlsx']
            if ext not in valid_extensions:
                raise ValidationError(_("نسق الملف غير مدعوم. يرجى رفع ملف بصيغة CSV أو Excel."))
        return file

    def clean(self):
        """
        تحقق منطقي عام بين الحقول
        """
        cleaned_data = super().clean()
        start_balance = cleaned_data.get("start_balance")
        end_balance = cleaned_data.get("end_balance")

        # يمكنك إضافة منطق هنا، مثلاً تحذير إذا كان الرصيد بالسالب
        # ولكن لن نوقف العملية لأن رصيد البنك قد يكون مكشوفاً (Overdraft)

        return cleaned_data