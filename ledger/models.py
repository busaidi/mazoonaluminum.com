# ledger/models.py
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

User = get_user_model()

def get_default_journal_for_manual_entry():
    """
    Returns the default journal for manual entries (typically General Journal).
    Fallback:
      - First active GENERAL journal
      - Otherwise any active journal
      - Otherwise None
    """
    from .models import Journal  # local import to avoid circular imports

    qs = Journal.objects.filter(is_active=True)

    # Prefer general type with is_default=True
    journal = (
        qs.filter(type=Journal.Type.GENERAL, is_default=True).first()
        or qs.filter(type=Journal.Type.GENERAL).first()
    )

    if journal:
        return journal

    # Fallback: any active journal
    return qs.first()


def get_default_journal_for_sales_invoice():
    """
    Default journal for sales invoices (Sales Journal).
    To be used later from the accounting app when auto-posting invoices.
    """
    from .models import Journal

    qs = Journal.objects.filter(is_active=True)
    return (
        qs.filter(type=Journal.Type.SALES, is_default=True).first()
        or qs.filter(type=Journal.Type.SALES).first()
    )


def get_default_journal_for_customer_payment():
    """
    Default journal for customer payments (Cash / Bank Journal).
    To be used later from the accounting app when auto-posting payments.
    """
    from .models import Journal

    qs = Journal.objects.filter(is_active=True)

    # Prefer CASH, then BANK
    journal = (
        qs.filter(type=Journal.Type.CASH, is_default=True).first()
        or qs.filter(type=Journal.Type.CASH).first()
        or qs.filter(type=Journal.Type.BANK, is_default=True).first()
        or qs.filter(type=Journal.Type.BANK).first()
    )

    if journal:
        return journal

    return None



def generate_journal_entry_number(journal, fiscal_year, date):
    """
    Generate a journal entry number of the form:
    <PREFIX>-<YEAR>-<SEQ>

    Examples:
      GEN-2025-0001
      CASH-2025-0001
      SALES-2025-0001

    - PREFIX comes from journal.code (or "JE" if no journal).
    - YEAR comes from fiscal_year.year (fallback to date.year).
    - SEQ is a running sequence per (journal, year).
    """
    from .models import JournalEntry  # safe: resolved at runtime

    # Determine year
    if fiscal_year is not None:
        year = fiscal_year.year
    elif date is not None:
        year = date.year
    else:
        year = timezone.now().year

    # Determine prefix
    if journal is not None and journal.code:
        prefix = journal.code.upper()
    else:
        prefix = "JE"

    base_prefix = f"{prefix}-{year}-"

    # Get last entry for this journal + year (by id for stability)
    qs = JournalEntry.objects.filter(number__startswith=base_prefix)
    if journal is not None:
        qs = qs.filter(journal=journal)
    else:
        qs = qs.filter(journal__isnull=True)

    last_entry = qs.order_by("id").last()

    if last_entry and last_entry.number:
        try:
            last_seq = int(last_entry.number.split("-")[-1])
        except (ValueError, IndexError):
            last_seq = 0
        new_seq = last_seq + 1
    else:
        new_seq = 1

    return f"{base_prefix}{new_seq:04d}"

class FiscalYear(models.Model):
    """
    سنة مالية بسيطة: سنة + تاريخ بداية + تاريخ نهاية + حالة إقفال.
    """
    year = models.PositiveIntegerField(unique=True, verbose_name=_("السنة"))
    start_date = models.DateField(verbose_name=_("تاريخ البداية"))
    end_date = models.DateField(verbose_name=_("تاريخ النهاية"))
    is_closed = models.BooleanField(default=False, verbose_name=_("مقفلة؟"))

    class Meta:
        ordering = ["-year"]

    def __str__(self) -> str:
        return str(self.year)

    @classmethod
    def for_date(cls, date):
        """
        حاول إيجاد السنة المالية التي تحتوي هذا التاريخ.
        ولو ما حصل، يحاول بالسنة فقط (year = date.year).
        """
        if not date:
            return None

        fy = cls.objects.filter(
            start_date__lte=date,
            end_date__gte=date,
        ).first()

        if fy:
            return fy

        return cls.objects.filter(year=date.year).first()


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

    # يسمح باستخدام الحساب في التسوية (مثل العملاء والموردين)
    allow_settlement = models.BooleanField(
        default=True,
        help_text=_("Allow this account to be used in settlements."),
    )

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


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

    class Meta:
        ordering = ["code"]
        verbose_name = _("دفتر اليومية")
        verbose_name_plural = _("دفاتر اليومية")

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"




class JournalEntry(models.Model):
    """
    قيد يومية بسيط، مربوط بسنة مالية.
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
    )

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self) -> str:
        return f"JE-{self.id} ({self.date})"

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
        - لو ما تم تعيين السنة المالية، نحاول نعيّنها تلقائياً من تاريخ القيد.
        - لو لم يتم تعيين رقم القيد (number)، نولّده بناءً على الدفتر والسنة.
        """
        # Auto-assign fiscal year from date if not set
        if self.date and self.fiscal_year is None:
            self.fiscal_year = FiscalYear.for_date(self.date)

        # Auto-generate number only once (do not change it on later saves)
        if not self.number:
            self.number = generate_journal_entry_number(
                journal=self.journal,
                fiscal_year=self.fiscal_year,
                date=self.date,
            )

        super().save(*args, **kwargs)



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
