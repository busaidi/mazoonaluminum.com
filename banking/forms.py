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
            widget = field.widget

            # إذا كان الحقل Checkbox نستخدم تنسيقاً مختلفاً
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.update({"class": "form-check-input"})
            else:
                # يشمل الحقول النصية، الأرقام، التاريخ، الملف... الخ
                # في Bootstrap 5, file input يستخدم أيضاً form-control
                widget.attrs.update({"class": "form-control"})


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
            "name": _("مثال: بنك مسقط - جاري 1234"),
            "account": _("الحساب المحاسبي المرتبط في شجرة الحسابات"),
        }

    def clean_account(self):
        """
        تحقق إضافي: التأكد أن حساب الأستاذ المختار ليس مربوطاً بحساب بنكي آخر.
        (رغم أن OneToOneField يمنع ذلك، لكن رسالة الفورم تكون أوضح للمستخدم)
        """
        account = self.cleaned_data.get("account")

        if not account:
            return account

        # نستثني الحساب الحالي في حالة التعديل (self.instance.pk)
        qs = BankAccount.objects.filter(account=account).exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError(
                _("عذراً، هذا الحساب المحاسبي مرتبط بالفعل بحساب بنكي آخر.")
            )
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
            "date": forms.DateInput(
                attrs={
                    "type": "date",
                    "placeholder": _("اختر تاريخ الكشف"),
                }
            ),
        }
        labels = {
            "bank_account": _("الحساب البنكي"),
            "name": _("وصف الكشف"),
            "date": _("تاريخ الكشف"),
            "start_balance": _("الرصيد الافتتاحي"),
            "end_balance": _("الرصيد الختامي"),
            # نخليه واضح إن الملف المستخدم للاستيراد هو Excel/CSV
            "imported_file": _("ملف الحركات (Excel/CSV)"),
        }
        help_texts = {
            "imported_file": _(
                "اختياري: ارفع ملف الحركات بصيغة CSV أو Excel لاستخدامه في الاستيراد الآلي."
            ),
        }

    def clean_imported_file(self):
        """
        التحقق من امتداد الملف المرفوع.
        نقبل فقط ملفات Excel أو CSV للاستيراد.
        (لو حاب تسمح بـ PDF أيضاً كمجرد مرفق، نضيف الامتداد .pdf هنا)
        """
        file = self.cleaned_data.get("imported_file")
        if file:
            ext = os.path.splitext(file.name)[1].lower()  # استخراج الامتداد
            valid_extensions = [".csv", ".xls", ".xlsx"]
            if ext not in valid_extensions:
                raise ValidationError(
                    _("نسق الملف غير مدعوم. يرجى رفع ملف بصيغة CSV أو Excel.")
                )
        return file

    def clean(self):
        """
        تحقق منطقي عام بين الحقول
        يمكن لاحقاً إضافة منطق:
        - مقارنة الرصيد الافتتاحي/الختامي مع مجموع الحركات المستوردة
        - تحذير لو رصيد البنك بالسالب (Overdraft)
        """
        cleaned_data = super().clean()
        start_balance = cleaned_data.get("start_balance")
        end_balance = cleaned_data.get("end_balance")

        # حالياً فقط نعيد البيانات بدون شروط إضافية
        # لأن كشف البنك قد يكون مكشوف (سالب) وهذا مقبول.
        # يمكنك إضافة أي تنبيهات لاحقاً عبر messages في الـ View.

        return cleaned_data
