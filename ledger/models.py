from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import models, transaction, IntegrityError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .managers import (
    FiscalYearManager,
    AccountManager,
    JournalManager,
    JournalEntryManager,
    JournalLineManager,
)

User = get_user_model()


# ==============================================================================
# Fiscal Year
# ==============================================================================


class FiscalYear(models.Model):
    """
    Simple fiscal year:
    - year (e.g. 2025)
    - start_date
    - end_date
    - is_closed
    - is_default (optional default year for reports)
    """

    year = models.PositiveIntegerField(unique=True, verbose_name=_("السنة"))
    start_date = models.DateField(verbose_name=_("تاريخ البداية"))
    end_date = models.DateField(verbose_name=_("تاريخ النهاية"))
    is_closed = models.BooleanField(default=False, verbose_name=_("مقفلة؟"))
    is_default = models.BooleanField(
        default=False,
        verbose_name=_("سنة افتراضية للتقارير؟"),
        help_text=_(
            "تُستخدم هذه السنة كافتراضي في التقارير عند عدم اختيار سنة أخرى."
        ),
    )

    objects = FiscalYearManager()

    class Meta:
        ordering = ["-year"]

    def __str__(self) -> str:
        return str(self.year)

    @classmethod
    def for_date(cls, date):
        """
        Try to find the fiscal year that contains the given date.
        Fallback: match by year only (year = date.year).

        التفويض للـ Manager عشان يظل المنطق في طبقة واحدة.
        """
        return cls.objects.for_date(date)

    def save(self, *args, **kwargs):
        """
        Ensure only one fiscal year is marked as default.
        """
        super().save(*args, **kwargs)
        if self.is_default:
            FiscalYear.objects.exclude(pk=self.pk).update(is_default=False)

        class Meta:
            ordering = ["-year"]
            constraints = [
                models.CheckConstraint(
                    check=models.Q(start_date__lte=models.F("end_date")),
                    name="fiscalyear_start_before_end",
                )
            ]


# ==============================================================================
# Account
# ==============================================================================


class Account(models.Model):
    class Type(models.TextChoices):
        ASSET = "asset", _("أصل")
        LIABILITY = "liability", _("التزامات")
        EQUITY = "equity", _("حقوق ملكية")
        REVENUE = "revenue", _("إيرادات")
        EXPENSE = "expense", _("مصروفات")

    code = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=20, choices=Type.choices)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    is_active = models.BooleanField(default=True)

    # Allow this account to be used in settlements (customers, suppliers, etc.)
    allow_settlement = models.BooleanField(
        default=True,
        help_text=_("Allow this account to be used in settlements."),
    )

    objects = AccountManager()

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


# ==============================================================================
# Journal (Books)
# ==============================================================================


class Journal(models.Model):
    """
    Simple journal (book) model:
    - General, Cash, Bank, Sales, Purchase, etc.
    """

    class Type(models.TextChoices):
        GENERAL = "general", _("دفتر عام")
        CASH = "cash", _("دفتر الكاش")
        BANK = "bank", _("دفتر البنك")
        SALES = "sales", _("دفتر المبيعات")
        PURCHASE = "purchase", _("دفتر المشتريات")

    code = models.CharField(
        max_length=20,
        unique=True,
        verbose_name=_("كود الدفتر"),
    )
    name = models.CharField(
        max_length=100,
        verbose_name=_("اسم الدفتر"),
    )
    type = models.CharField(
        max_length=20,
        choices=Type.choices,
        default=Type.GENERAL,
        verbose_name=_("نوع الدفتر"),
    )
    is_default = models.BooleanField(
        default=False,
        verbose_name=_("دفتر افتراضي"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("نشط"),
    )

    objects = JournalManager()

    class Meta:
        ordering = ["code"]
        verbose_name = _("دفتر اليومية")
        verbose_name_plural = _("دفاتر اليومية")

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


# ==============================================================================
# Journal Entry / Lines
# ==============================================================================


class JournalEntry(models.Model):
    """
    Basic journal entry linked to a fiscal year and a journal.
    """

    fiscal_year = models.ForeignKey(
        FiscalYear,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="entries",
        verbose_name=_("السنة المالية"),
    )
    journal = models.ForeignKey(
        "Journal",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="entries",
        verbose_name=_("دفتر اليومية"),
    )
    date = models.DateField(default=timezone.now, verbose_name=_("التاريخ"))
    reference = models.CharField(max_length=50, blank=True, verbose_name=_("المرجع"))
    description = models.TextField(blank=True, verbose_name=_("الوصف"))
    number = models.CharField(
        max_length=32,
        unique=True,
        null=True,
        blank=True,
        verbose_name=_("رقم القيد"),
    )
    posted = models.BooleanField(default=False, verbose_name=_("مرحّل"))

    posted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("تاريخ الترحيل"),
    )
    posted_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="posted_journal_entries",
        verbose_name=_("مُرحّل بواسطة"),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name=_("أنشئ بواسطة"),
        related_name="created_journal_entries",
    )

    objects = JournalEntryManager()

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self) -> str:
        # Prefer the generated number if available
        if self.number:
            return f"{self.number} ({self.date})"
        return f"JE-{self.id} ({self.date})"

    @property
    def display_number(self) -> str:
        """
        رقم عرض موحد:
        - إذا عندي number حقيقي (مثلاً GEN-2025-0001) أستخدمه
        - وإلا أستخدم JE-<id> كـ fallback
        """
        return self.number or f"JE-{self.id}"

    @property
    def total_debit(self) -> Decimal:
        return self.lines.aggregate(s=models.Sum("debit"))["s"] or Decimal("0")

    @property
    def total_credit(self) -> Decimal:
        return self.lines.aggregate(s=models.Sum("credit"))["s"] or Decimal("0")

    @property
    def is_balanced(self) -> bool:
        return self.total_debit == self.total_credit

    def save(self, *args, **kwargs):
        """
        - تعيين السنة المالية من التاريخ تلقائياً إذا لم تُحدّد.
        - توليد رقم القيد (مرة واحدة) بناءً على الدفتر + السنة.
        - التعامل مع حالات التضارب النادرة في UNIQUE على number.
        """
        # 1) تعيين / تحديث السنة المالية تلقائيًا من التاريخ دائمًا
        if self.date:
            fy = FiscalYear.for_date(self.date)
            if fy is not None:
                self.fiscal_year = fy

        # 2) توليد رقم القيد إن لم يكن موجوداً
        if not self.number:
            self.number = JournalEntry.objects.generate_number(
                journal=self.journal,
                fiscal_year=self.fiscal_year,
                date=self.date,
            )

        # 3) محاولة الحفظ مع معالجة تضارب UNIQUE على number
        max_retries = 3
        for _ in range(max_retries):
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError as exc:
                msg = str(exc).lower()
                # نتحقق بطريقة أوسع شوي من رسالة الخطأ
                if (
                    "journalentry.number" in msg
                    or "ledger_journalentry.number" in msg
                    or "unique constraint failed: ledger_journalentry.number" in msg
                ) and not self.pk:
                    # أعِد توليد الرقم بناءً على الوضع الحالي في قاعدة البيانات
                    self.number = JournalEntry.objects.generate_number(
                        journal=self.journal,
                        fiscal_year=self.fiscal_year,
                        date=self.date,
                    )
                    continue
                # أي خطأ آخر نرفعه كما هو
                raise

        # لو (نادرًا) فشل بعد عدة محاولات
        raise IntegrityError("Could not generate a unique JournalEntry.number")



class JournalLine(models.Model):
    entry = models.ForeignKey(
        JournalEntry,
        related_name="lines",
        on_delete=models.CASCADE,
        verbose_name=_("قيد اليومية"),
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        verbose_name=_("الحساب"),
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("الوصف"),
    )
    debit = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0,
        verbose_name=_("مدين"),
    )
    credit = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0,
        verbose_name=_("دائن"),
    )
    order = models.PositiveIntegerField(default=0)

    objects = JournalLineManager()

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.CheckConstraint(
                check=~(models.Q(debit__gt=0) & models.Q(credit__gt=0)),
                name="ledger_line_not_both_debit_credit",
            )
        ]

    def __str__(self) -> str:
        return f"{self.entry_id} - {self.account}"


# ==============================================================================
# Helpers: default journals (واجهة بسيطة على Manager)
# ==============================================================================


def get_default_journal_for_manual_entry():
    """
    Default journal for manual entries:
    - Typically GENERAL journal.
    - Fallback: any active journal.

    واجهة خفيفة تستدعي Journal.objects.get_default_for_manual_entry()
    عشان ما تكسر أي كود قديم يستخدم هذه الدوال.
    """
    return Journal.objects.get_default_for_manual_entry()


def get_default_journal_for_sales_invoice():
    """
    Default journal for sales invoices (Sales Journal).
    To be used from the accounting app when auto-posting invoices.
    """
    return Journal.objects.get_default_for_sales_invoice()


def get_default_journal_for_customer_payment():
    """
    Default journal for customer payments (Cash / Bank).
    Order:
      1) CASH (is_default=True, then any CASH)
      2) BANK (is_default=True, then any BANK)
      3) Any active journal as a last resort.
    """
    return Journal.objects.get_default_for_customer_payment()


# ==============================================================================
# Helpers: journal entry numbering (واجهة على الـ Manager)
# ==============================================================================


def generate_journal_entry_number(journal, fiscal_year, date):
    """
    Backwards-compatible helper.

    الآن المنطق الحقيقي في JournalEntryManager.generate_number،
    وهذه الدالة مجرد واجهة لو فيه أي كود قديم يستدعيها.
    """
    return JournalEntry.objects.generate_number(
        journal=journal,
        fiscal_year=fiscal_year,
        date=date,
    )

class LedgerSettings(models.Model):
    """
    إعدادات دفتر الأستاذ:
    ربط دفاتر اليومية بوظائف النظام (مبيعات، مشتريات، بنك، كاش، قيود يدوية، رصيد افتتاحي).
    هذه الإعدادات يفترض أن تكون صف واحد فقط (singleton).
    """

    default_manual_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_default_manual_journal",
        limit_choices_to={"is_active": True},
        verbose_name=_("دفتر القيود اليدوية"),
        help_text=_("يستخدم لأي قيد يُنشأ يدويًا من داخل دفتر الأستاذ."),
    )

    sales_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_sales_journal",
        limit_choices_to={"is_active": True},
        verbose_name=_("دفتر المبيعات"),
        help_text=_("يستخدم لقيود فواتير المبيعات."),
    )

    purchase_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_purchase_journal",
        limit_choices_to={"is_active": True},
        verbose_name=_("دفتر المشتريات"),
        help_text=_("يستخدم لقيود فواتير الموردين."),
    )

    cash_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_cash_journal",
        limit_choices_to={"is_active": True},
        verbose_name=_("دفتر الكاش"),
        help_text=_("يستخدم لحركات الصندوق النقدي."),
    )

    bank_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_bank_journal",
        limit_choices_to={"is_active": True},
        verbose_name=_("دفتر البنك"),
        help_text=_("يستخدم لحركات حسابات البنك."),
    )

    opening_balance_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_opening_balance_journal",
        limit_choices_to={"is_active": True},
        verbose_name=_("دفتر الرصيد الافتتاحي"),
        help_text=_("يستخدم لقيود الأرصدة الافتتاحية عند إنشاء أو استيراد رصيد افتتاحي."),
    )

    closing_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_closing_journal",
        limit_choices_to={"is_active": True},
        verbose_name=_("دفتر إقفال السنة"),
        help_text=_("يستخدم لقيود إقفال السنة المالية."),
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("تاريخ آخر تعديل"),
    )

    def __str__(self) -> str:
        return _("إعدادات دفتر الأستاذ")


    class Meta:
        verbose_name = _("إعدادات دفتر الأستاذ")
        verbose_name_plural = _("إعدادات دفتر الأستاذ")

    @classmethod
    def get_solo(cls) -> "LedgerSettings":
        """
        يعيد صف الإعدادات الوحيد، وينشئ واحد إذا غير موجود.
        """
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def as_mapping(self):
        return {
            "default_manual": self.default_manual_journal,
            "sales": self.sales_journal,
            "purchase": self.purchase_journal,
            "cash": self.cash_journal,
            "bank": self.bank_journal,
            "opening": self.opening_balance_journal,
            "closing": self.closing_journal,
        }
