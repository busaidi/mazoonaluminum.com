# banking/models.py
from django.db import models
from django.utils.translation import gettext_lazy as _

from accounting.models import Account, JournalEntry, Payment  # حسب مسارك الفعلي

class BankAccount(models.Model):
    """
    تعريف حساب بنكي وربطه بحساب محاسبي (دفتر أستاذ).
    الفكرة:
      - كل حساب بنكي فعلي (بنك مسقط - جاري) يكون له حساب محاسبي واحد.
      - account = حساب الأستاذ من جدول الحسابات.
    """

    name = models.CharField(
        max_length=255,
        verbose_name=_("اسم الحساب البنكي (داخلياً)"),
        help_text=_("مثال: بنك مسقط - جاري / حساب الرواتب"),
    )

    account = models.OneToOneField(
        Account,
        on_delete=models.PROTECT,
        related_name="bank_account",
        verbose_name=_("الحساب المحاسبي"),
        help_text=_("اختر الحساب المحاسبي من دليل الحسابات الذي يمثل هذا الحساب البنكي."),
    )

    bank_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("اسم البنك"),
        help_text=_("مثال: بنك مسقط، بنك نزوى، بنك ظفار..."),
    )

    iban = models.CharField(
        max_length=64,
        blank=True,
        verbose_name=_("IBAN"),
    )

    account_number = models.CharField(
        max_length=64,
        blank=True,
        verbose_name=_("رقم الحساب"),
    )

    currency = models.CharField(
        max_length=10,
        default="OMR",
        verbose_name=_("العملة"),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("نشط"),
    )

    class Meta:
        verbose_name = _("حساب بنكي")
        verbose_name_plural = _("حسابات بنكية")
        ordering = ["name"]

    def __str__(self):
        # نحاول نرجّع شيء واضح في القوائم
        parts = []
        if self.bank_name:
            parts.append(self.bank_name)
        if self.account_number:
            parts.append(self.account_number)
        if not parts:
            parts.append(self.name)
        return " - ".join(parts)


class BankStatement(models.Model):
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="statements",
        verbose_name=_("الحساب البنكي"),
    )
    date_from = models.DateField(verbose_name=_("من تاريخ"))
    date_to = models.DateField(verbose_name=_("إلى تاريخ"))
    opening_balance = models.DecimalField(max_digits=18, decimal_places=3, verbose_name=_("الرصيد الافتتاحي"))
    closing_balance = models.DecimalField(max_digits=18, decimal_places=3, verbose_name=_("الرصيد الختامي"))
    imported_file = models.FileField(
        upload_to="bank_statements/",
        blank=True,
        null=True,
        verbose_name=_("ملف الكشف"),
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ("draft", _("مسودة")),
            ("in_progress", _("قيد التسوية")),
            ("reconciled", _("مُسوّى")),
        ],
        default="draft",
        verbose_name=_("الحالة"),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.bank_account} [{self.date_from} → {self.date_to}]"


class BankStatementLine(models.Model):
    statement = models.ForeignKey(
        BankStatement,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("كشف البنك"),
    )
    date = models.DateField(verbose_name=_("التاريخ"))
    description = models.CharField(max_length=255, verbose_name=_("الوصف"))
    reference = models.CharField(max_length=128, blank=True, verbose_name=_("المرجع"))
    amount = models.DecimalField(
        max_digits=18,
        decimal_places=3,
        verbose_name=_("المبلغ (+/-)"),
    )
    balance_after = models.DecimalField(
        max_digits=18,
        decimal_places=3,
        blank=True,
        null=True,
        verbose_name=_("الرصيد بعد الحركة"),
    )

    match_status = models.CharField(
        max_length=20,
        choices=[
            ("unmatched", _("غير مُسوّى")),
            ("partial", _("مسوى جزئياً")),
            ("matched", _("مسوى بالكامل")),
        ],
        default="unmatched",
        verbose_name=_("حالة التسوية"),
    )

    payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_lines",
        verbose_name=_("سند دفع/قبض"),
    )
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_lines",
        verbose_name=_("قيد اليومية"),
    )

    external_id = models.CharField(
        max_length=128,
        blank=True,
        verbose_name=_("معرّف البنك"),
    )

    class Meta:
        ordering = ["date", "id"]

    def __str__(self):
        return f"{self.date} - {self.amount} - {self.description}"
