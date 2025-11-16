from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

User = get_user_model()


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

    # New field: allow this account to be used in settlements
    allow_settlement = models.BooleanField(
        default=True,
        help_text="Allow this account to be used in settlements.",
    )

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class JournalEntry(models.Model):
    date = models.DateField(default=timezone.now)
    reference = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    posted = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
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


class JournalLine(models.Model):
    entry = models.ForeignKey(
        JournalEntry,
        related_name="lines",
        on_delete=models.CASCADE,
    )
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    description = models.CharField(max_length=255, blank=True)
    debit = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    credit = models.DecimalField(max_digits=12, decimal_places=3, default=0)
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

