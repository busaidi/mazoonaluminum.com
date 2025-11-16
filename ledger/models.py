# ledger/models.py
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

User = get_user_model()


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
    date = models.DateField(default=timezone.now, verbose_name=_("التاريخ"))
    reference = models.CharField(max_length=50, blank=True, verbose_name=_("المرجع"))
    description = models.TextField(blank=True, verbose_name=_("الوصف"))
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
        لو ما تم تعيين السنة المالية، نحاول نعيّنها تلقائياً من تاريخ القيد.
        """
        if self.date and self.fiscal_year is None:
            self.fiscal_year = FiscalYear.for_date(self.date)
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
