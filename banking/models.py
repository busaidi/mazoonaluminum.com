import uuid
from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.db.models import Sum, F

# نفترض أن تطبيق المحاسبة لديك يحتوي على هذه الموديلات
# إذا كان اسم المودل مختلفاً لديك، يرجى تعديل الاستيراد فقط
from accounting.models import Account, JournalLine


# ---------------------------------------------------------
# 1. إعدادات الحساب البنكي
# ---------------------------------------------------------

class BankAccount(models.Model):
    """
    تعريف الحساب البنكي وربطه بحساب الأستاذ العام (GL Account).
    """
    name = models.CharField(
        max_length=255,
        verbose_name=_("اسم الحساب البنكي"),
        help_text=_("مثال: بنك مسقط - جاري 1234"),
    )

    # ربط الحساب البنكي بحساب في شجرة الحسابات
    account = models.OneToOneField(
        Account,
        on_delete=models.PROTECT,
        related_name="bank_account_config",
        verbose_name=_("الحساب المحاسبي (GL)"),
        help_text=_("الحساب في دليل الحسابات الذي ستتم عليه القيود"),
    )

    bank_name = models.CharField(max_length=255, blank=True, verbose_name=_("اسم البنك"))
    account_number = models.CharField(max_length=64, blank=True, verbose_name=_("رقم الحساب"))
    iban = models.CharField(max_length=64, blank=True, verbose_name=_("IBAN"))
    currency = models.CharField(max_length=10, default="OMR", verbose_name=_("العملة"))

    is_active = models.BooleanField(default=True, verbose_name=_("نشط"))

    class Meta:
        verbose_name = _("حساب بنكي")
        verbose_name_plural = _("حسابات بنكية")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.currency})"


# ---------------------------------------------------------
# 2. كشف الحساب (الهيدر)
# ---------------------------------------------------------

class BankStatement(models.Model):
    """
    يمثل "ملف" كشف الحساب الذي يتم رفعه أو إدخاله شهرياً.
    يستخدم للمطابقة بين الرصيد الافتتاحي والختامي.
    """
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="statements",
        verbose_name=_("الحساب البنكي")
    )

    name = models.CharField(
        max_length=255,
        verbose_name=_("مرجع الكشف"),
        help_text=_("مثال: كشف يناير 2024")
    )

    date = models.DateField(verbose_name=_("تاريخ الكشف"))

    # الأرصدة للتحقق
    start_balance = models.DecimalField(max_digits=18, decimal_places=3, verbose_name=_("الرصيد الافتتاحي"))
    end_balance = models.DecimalField(max_digits=18, decimal_places=3, verbose_name=_("الرصيد الختامي"))

    imported_file = models.FileField(
        upload_to="bank_statements/",
        blank=True,
        null=True,
        verbose_name=_("ملف الكشف (Excel/PDF)")
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("كشف حساب")
        verbose_name_plural = _("كشوفات الحساب")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.name} - {self.bank_account.name}"

    @property
    def computed_balance(self):
        """
        يحسب الرصيد النهائي بناءً على الحركات المدخلة:
        الافتتاحي + مجموع الحركات
        """
        lines_sum = self.lines.aggregate(total=Sum('amount'))['total'] or Decimal('0.000')
        return self.start_balance + lines_sum

    @property
    def is_valid(self):
        """هل يطابق الرصيد المحسوب الرصيد الختامي المدخل؟"""
        return self.computed_balance == self.end_balance


# ---------------------------------------------------------
# 3. سطور كشف الحساب (Transactions)
# ---------------------------------------------------------

class BankStatementLine(models.Model):
    """
    السطر الواحد داخل كشف البنك.
    """
    statement = models.ForeignKey(
        BankStatement,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("الكشف التابع له")
    )

    date = models.DateField(verbose_name=_("التاريخ"))
    label = models.CharField(max_length=255, verbose_name=_("البيان/الوصف"))
    ref = models.CharField(max_length=100, blank=True, verbose_name=_("المرجع البنكي"))

    # المبلغ: موجب للإيداع، سالب للسحب
    amount = models.DecimalField(max_digits=18, decimal_places=3, verbose_name=_("المبلغ"))

    # هذا الحقل هو الأهم: كم تبقى من المبلغ لم تتم تسويته؟
    amount_residual = models.DecimalField(
        max_digits=18,
        decimal_places=3,
        editable=False,  # لا يعدله المستخدم يدوياً
        verbose_name=_("المتبقي للتسوية")
    )

    is_reconciled = models.BooleanField(default=False, editable=False, verbose_name=_("مُسوّى بالكامل"))

    # لربط العملية بشريك (عميل/مورد) إذا عرفناه (اختياري)
    partner_name = models.CharField(max_length=255, blank=True, null=True, verbose_name=_("اسم الشريك المقترح"))

    class Meta:
        verbose_name = _("حركة بنكية")
        verbose_name_plural = _("حركات بنكية")
        ordering = ["date", "id"]

    def save(self, *args, **kwargs):
        # عند إنشاء السطر لأول مرة، المتبقي يساوي كامل المبلغ
        if self.pk is None:
            self.amount_residual = self.amount

        # تحديد حالة التسوية تلقائياً
        if self.amount_residual == 0:
            self.is_reconciled = True
        else:
            self.is_reconciled = False

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.date} | {self.label} | {self.amount}"


# ---------------------------------------------------------
# 4. مودل التسوية (الجوهر)
# ---------------------------------------------------------

class BankReconciliation(models.Model):
    """
    جدول الربط (Many-to-Many Link).
    يربط حركة بنكية مع سطر قيد محاسبي.
    """
    bank_line = models.ForeignKey(
        BankStatementLine,
        on_delete=models.PROTECT,  # لا تحذف السطر البنكي إذا كان مسوى
        related_name="reconciliations",
        verbose_name=_("حركة البنك")
    )

    journal_item = models.ForeignKey(
        JournalLine,
        on_delete=models.PROTECT,  # لا تحذف القيد إذا كان مسوى
        related_name="bank_reconciliations",
        verbose_name=_("سطر القيد المحاسبي")
    )

    amount_reconciled = models.DecimalField(
        max_digits=18,
        decimal_places=3,
        verbose_name=_("المبلغ المُسوّى")
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("تسوية")
        verbose_name_plural = _("سجل التسويات")

    def clean(self):
        """
        قواعد التحقق قبل الحفظ:
        1. لا يمكن تسوية مبلغ أكبر من المتبقي في سطر البنك.
        2. لا يمكن تسوية مبلغ أكبر من المتبقي في القيد (إذا كنت تتبع متبقي القيد).
        """
        if self.pk is None:  # فحص فقط عند الإنشاء الجديد
            # التأكد من الإشارات (يجب أن يكونا بنفس الإشارة أو عكسها حسب منطقك، عادة الدفع يقابل الخصم)
            # هنا نفترض التسوية بالمطلق للمبالغ للتبسيط، أو التحقق من القيمة

            # فحص سطر البنك
            if abs(self.amount_reconciled) > abs(self.bank_line.amount_residual):
                raise ValidationError(_("المبلغ المراد تسويته أكبر من المبلغ المتبقي في سطر البنك."))

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        # 1. تنفيذ التحقق
        self.full_clean()

        # 2. الحفظ
        super().save(*args, **kwargs)

        # 3. تحديث الأرصدة بعد الحفظ (فقط إذا كان جديداً لتبسيط المثال)
        if is_new:
            self._update_bank_line_residual()

    def delete(self, *args, **kwargs):
        # عند الحذف (إلغاء التسوية)، يجب إعادة المبلغ للسطر البنكي
        amount_to_restore = self.amount_reconciled
        bank_line = self.bank_line

        super().delete(*args, **kwargs)

        bank_line.amount_residual += amount_to_restore
        bank_line.save()  # سيقوم بتحديث is_reconciled تلقائياً

    def _update_bank_line_residual(self):
        """تحديث المتبقي في سطر البنك"""
        line = self.bank_line
        line.amount_residual = line.amount_residual - self.amount_reconciled
        line.save()  # دالة Save في السطر البنكي ستحدث حالة is_reconciled

    def __str__(self):
        return f"Rec: {self.amount_reconciled} ({self.bank_line.id} <-> {self.journal_item.id})"