# accounting/models.py

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Sum, Q, F, CheckConstraint
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounting.domain import InvoiceCreated, InvoiceSent
from accounting.managers import (
    FiscalYearManager,
    AccountManager,
    JournalManager,
    JournalEntryManager,
    JournalLineManager,
    InvoiceManager,
)
from core.domain.hooks import on_lifecycle, on_transition
from core.models.domain import StatefulDomainModel

User = get_user_model()

DECIMAL_ZERO = Decimal("0.000")


# ==============================================================================
# Invoice Settings (global)
# ==============================================================================

class Settings(models.Model):
    """
    Global invoice settings (due days, VAT, default terms, etc.).
    """

    default_due_days = models.PositiveSmallIntegerField(
        default=30,
        validators=[MaxValueValidator(365)],
        verbose_name=_("أيام الاستحقاق"),
    )
    auto_confirm_invoice = models.BooleanField(
        default=False,
        verbose_name=_("اعتماد تلقائي"),
    )
    auto_post_to_ledger = models.BooleanField(
        default=False,
        verbose_name=_("ترحيل تلقائي"),
    )

    default_vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("5.00"),
        verbose_name=_("نسبة الضريبة %"),
    )
    prices_include_vat = models.BooleanField(
        default=False,
        verbose_name=_("السعر شامل الضريبة"),
    )

    default_terms = models.TextField(
        blank=True,
        verbose_name=_("شروط افتراضية"),
    )
    footer_notes = models.TextField(
        blank=True,
        verbose_name=_("ملاحظات الفاتورة"),
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("إعدادات الفواتير")
        verbose_name_plural = _("إعدادات الفواتير")

    @classmethod
    def get_solo(cls) -> "Settings":
        """
        Simple singleton pattern: ensure there is always one settings row (pk=1).
        """
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self) -> str:
        return str(_("إعدادات الفواتير"))


# ==============================================================================
# Fiscal Year
# ==============================================================================

class FiscalYear(models.Model):
    """
    Simple fiscal year definition (used by JournalEntry).
    """

    year = models.PositiveIntegerField(
        unique=True,
        verbose_name=_("السنة"),
    )
    start_date = models.DateField(verbose_name=_("تاريخ البداية"))
    end_date = models.DateField(verbose_name=_("تاريخ النهاية"))
    is_closed = models.BooleanField(
        default=False,
        verbose_name=_("مقفلة؟"),
    )
    is_default = models.BooleanField(
        default=False,
        verbose_name=_("افتراضية"),
    )

    objects = FiscalYearManager()

    class Meta:
        ordering = ["-year"]
        constraints = [
            CheckConstraint(
                check=Q(start_date__lte=F("end_date")),
                name="fiscalyear_valid_dates",
            )
        ]
        verbose_name = _("سنة مالية")
        verbose_name_plural = _("السنوات المالية")

    def __str__(self) -> str:
        return str(self.year)

    @classmethod
    def for_date(cls, date):
        """
        Find fiscal year for a given date.
        """
        return cls.objects.filter(
            start_date__lte=date,
            end_date__gte=date,
        ).first()

    def save(self, *args, **kwargs):
        """
        Ensure only one default fiscal year at a time.
        """
        if self.is_default:
            FiscalYear.objects.exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


# ==============================================================================
# Account
# ==============================================================================

class Account(models.Model):
    """
    Chart of accounts – hierarchical, with main type.
    """

    class Type(models.TextChoices):
        ASSET = "asset", _("أصل")
        LIABILITY = "liability", _("التزامات")
        EQUITY = "equity", _("حقوق ملكية")
        REVENUE = "revenue", _("إيرادات")
        EXPENSE = "expense", _("مصروفات")

    code = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        verbose_name=_("كود الحساب"),
    )
    name = models.CharField(
        max_length=255,
        verbose_name=_("اسم الحساب"),
    )
    type = models.CharField(
        max_length=20,
        choices=Type.choices,
        verbose_name=_("نوع الحساب"),
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        verbose_name=_("الأب"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("نشط"),
    )
    allow_settlement = models.BooleanField(
        default=True,
        verbose_name=_("يقبل التسوية"),
    )

    objects = AccountManager()

    class Meta:
        ordering = ["code"]
        verbose_name = _("حساب")
        verbose_name_plural = _("الحسابات")

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


# ==============================================================================
# Journal & JournalEntry & JournalLine
# ==============================================================================

class Journal(models.Model):
    """
    Journal definition (general, sales, purchase, bank, etc.).
    """

    class Type(models.TextChoices):
        GENERAL = "general", _("عام")
        CASH = "cash", _("كاش")
        BANK = "bank", _("بنك")
        SALES = "sales", _("مبيعات")
        PURCHASE = "purchase", _("مشتريات")

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
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = JournalManager()

    class Meta:
        ordering = ["code"]
        verbose_name = _("دفتر يومية")
        verbose_name_plural = _("دفاتر اليومية")

    def __str__(self) -> str:
        return f"{self.name}"


class JournalEntry(models.Model):
    """
    Journal entry header. Lines are stored in JournalLine.
    """

    fiscal_year = models.ForeignKey(
        FiscalYear,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name=_("السنة المالية"),
    )
    journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name=_("الدفتر"),
    )
    date = models.DateField(
        default=timezone.now,
        verbose_name=_("التاريخ"),
    )
    reference = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("المرجع"),
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("الوصف"),
    )

    posted = models.BooleanField(
        default=False,
        verbose_name=_("مرحّل"),
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    objects = JournalEntryManager()

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = _("قيد يومية")
        verbose_name_plural = _("قيود اليومية")

    @property
    def total_debit(self) -> Decimal:
        return self.lines.aggregate(sum=Sum("debit"))["sum"] or Decimal(0)

    @property
    def total_credit(self) -> Decimal:
        return self.lines.aggregate(sum=Sum("credit"))["sum"] or Decimal(0)

    @property
    def imbalance(self):
        """
        الفرق بين إجمالي المدين وإجمالي الدائن.
        موجب = زيادة مدين، سالب = زيادة دائن.
        """
        return (self.total_debit or 0) - (self.total_credit or 0)

    @property
    def is_balanced(self) -> bool:
        return self.total_debit == self.total_credit

    @property
    def display_number(self) -> str:
        return f"JE-{self.pk}" if self.pk else "JE-New"

    def save(self, *args, **kwargs):
        """
        Auto-assign fiscal_year based on date if not set.
        """
        if self.date and not self.fiscal_year:
            self.fiscal_year = FiscalYear.for_date(self.date)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.display_number} | {self.description[:30]}"


class JournalLine(models.Model):
    """
    Single debit/credit line in a journal entry.
    يدعم الآن التسوية البنكية عبر BankReconciliation
    (banking.BankReconciliation.bank_line <-> journal_item).
    """

    entry = models.ForeignKey(
        JournalEntry,
        related_name="lines",
        on_delete=models.CASCADE,
        verbose_name=_("القيد"),
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
        default=Decimal("0.000"),
        verbose_name=_("مدين"),
    )
    credit = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("0.000"),
        verbose_name=_("دائن"),
    )

    # حقل منطقي بسيط: هل تمت تسوية هذا السطر بالكامل أم لا؟
    # حاليًا سنعتمد بالأساس على الخاصية is_fully_reconciled،
    # ويمكنك لاحقاً مزامنة هذا الحقل معها إن أردت.
    reconciled = models.BooleanField(
        default=False,
        verbose_name=_("مُسوّى بالكامل"),
    )

    order = models.PositiveIntegerField(default=0)

    objects = JournalLineManager()

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            # Do not allow a line with both debit and credit > 0
            CheckConstraint(
                check=~(Q(debit__gt=0) & Q(credit__gt=0)),
                name="no_double_entry_in_line",
            ),
            # Do not allow zero-value lines
            CheckConstraint(
                check=(Q(debit__gt=0) | Q(credit__gt=0)),
                name="no_zero_value_line",
            ),
        ]
        verbose_name = _("سطر قيد")
        verbose_name_plural = _("سطور القيود")

    # =========================
    # خصائص متعلقة بالتسوية
    # =========================

    @property
    def signed_amount(self) -> Decimal:
        """
        القيمة المحاسبية للسطر:
        - للحسابات المدينة (مثل البنك): الإيداع = مدين موجب، السحب = دائن سالب.
        وبالتالي استخدام (debit - credit) يجعل الإشارة متوافقة مع BankStatementLine.amount
        (موجب للإيداع، سالب للسحب).
        """
        return (self.debit or Decimal("0.000")) - (self.credit or Decimal("0.000"))

    @property
    def amount_reconciled(self) -> Decimal:
        """
        مجموع المبالغ التي تم تسويتها من خلال BankReconciliation
        (الربط بين هذا السطر وبين سطور البنك).
        """
        total = self.bank_reconciliations.aggregate(
            sum=Sum("amount_reconciled")
        )["sum"] or Decimal("0.000")
        return total

    @property
    def amount_open(self) -> Decimal:
        """
        المبلغ المتبقي غير المُسوّى:
        signed_amount - amount_reconciled
        إذا كان الناتج 0 يعني أن السطر تمت تسويته بالكامل.
        """
        return self.signed_amount - self.amount_reconciled

    @property
    def is_fully_reconciled(self) -> bool:
        """
        هل هذا السطر تمت تسويته بالكامل؟
        """
        return self.amount_open == 0

    def __str__(self) -> str:
        return f"{self.account.name}: D({self.debit}) C({self.credit})"


# ==============================================================================
# LedgerSettings
# ==============================================================================

class LedgerSettings(models.Model):
    """
    Mapping of default journals and accounts used by automatic postings.
    """

    # --- Journals ---
    default_manual_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("دفتر القيود اليدوية"),
    )
    sales_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("دفتر المبيعات"),
    )
    purchase_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("دفتر المشتريات"),
    )
    cash_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("دفتر الكاش"),
    )
    bank_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("دفتر البنك"),
    )
    opening_balance_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("دفتر الرصيد الافتتاحي"),
    )
    closing_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("دفتر إقفال السنة"),
    )

    # --- Accounts ---
    sales_receivable_account = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("حساب المدينون (العملاء)"),
    )
    sales_revenue_0_account = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("حساب المبيعات"),
    )
    sales_vat_output_account = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("حساب الضريبة المستحقة"),
    )
    sales_advance_account = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("حساب الدفعات المقدمة"),
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("إعدادات الدفاتر")
        verbose_name_plural = _("إعدادات الدفاتر")

    @classmethod
    def get_solo(cls) -> "LedgerSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


# ==============================================================================
# Invoice & InvoiceItem
# ==============================================================================

class Invoice(StatefulDomainModel):
    """
    فاتورة (مبيعات / مشتريات)
    """

    class InvoiceType(models.TextChoices):
        SALES = "sales", _("فاتورة مبيعات")
        PURCHASE = "purchase", _("فاتورة مشتريات")

    class Status(models.TextChoices):
        DRAFT = "draft", _("مسودة")
        SENT = "sent", _("تم الإرسال")
        PARTIALLY_PAID = "partially_paid", _("مدفوعة جزئياً")
        PAID = "paid", _("مدفوعة بالكامل")
        CANCELLED = "cancelled", _("ملغاة")

    type = models.CharField(
        max_length=20,
        choices=InvoiceType.choices,
        default=InvoiceType.SALES,
        db_index=True,
        verbose_name=_("نوع الفاتورة"),
    )

    customer = models.ForeignKey(
        "contacts.Contact",
        on_delete=models.PROTECT,
        related_name="invoices",
        verbose_name=_("الطرف"),
    )

    issued_at = models.DateField(default=timezone.now, verbose_name=_("تاريخ الفاتورة"))
    due_date = models.DateField(null=True, blank=True, verbose_name=_("تاريخ الاستحقاق"))

    description = models.TextField(blank=True, verbose_name=_("الوصف العام"))
    terms = models.TextField(blank=True, verbose_name=_("الشروط"))

    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("الإجمالي"),
    )

    # سنلغي الاعتماد على paid_amount المخزن، الآن نحسبه مباشرة من التسويات
    paid_amount = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ZERO,
        editable=False,
        verbose_name=_("المبلغ المدفوع (قديم، سيتم إلغاءه لاحقاً)"),
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        verbose_name=_("الحالة"),
    )

    ledger_entry = models.OneToOneField(
        "JournalEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoice",
        verbose_name=_("قيد اليومية"),
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("تاريخ الإنشاء"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("آخر تحديث"))

    # ------------------------------------------------------
    # خصائص الدفع
    # ------------------------------------------------------
    @property
    def allocated_amount(self) -> Decimal:
        """المبلغ الذي تم تسويته فعلياً من خلال الدفعات."""
        return (
            self.allocations.aggregate(sum=Sum("amount"))["sum"]
            or Decimal("0.000")
        )

    @property
    def balance(self) -> Decimal:
        """الرصيد المتبقي على الفاتورة."""
        return self.total_amount - self.allocated_amount

    @property
    def is_fully_paid(self) -> bool:
        """هل الفاتورة مدفوعة بالكامل؟"""
        return self.total_amount > 0 and self.balance <= 0

    @property
    def display_number(self):
        return f"INV-{self.pk}" if self.pk else _("مسودة")

    # ------------------------------------------------------
    # تحديث حالة الفاتورة حسب التسويات
    # ------------------------------------------------------
    def update_payment_status(self) -> None:
        """تحديث حالة الفاتورة."""
        if self.status in [self.Status.DRAFT, self.Status.CANCELLED]:
            return

        allocated = self.allocated_amount

        if allocated >= self.total_amount and self.total_amount > 0:
            self.status = self.Status.PAID
        elif allocated > 0:
            self.status = self.Status.PARTIALLY_PAID
        else:
            self.status = self.Status.SENT

        self.save(update_fields=["status"])

    # ------------------------------------------------------
    def __str__(self):
        return f"{self.get_type_display()} #{self.pk} - {self.customer}"


class InvoiceItem(models.Model):
    """
    Line item on an invoice (product + quantity + unit_price).
    """

    invoice = models.ForeignKey(
        Invoice,
        related_name="items",
        on_delete=models.CASCADE,
        verbose_name=_("الفاتورة"),
    )
    product = models.ForeignKey(
        "inventory.Product",
        on_delete=models.PROTECT,
        verbose_name=_("المنتج"),
        null=True,
        blank=True,
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("الوصف"),
    )
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("1.00"),
        verbose_name=_("الكمية"),
    )
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        verbose_name=_("سعر الوحدة"),
    )

    class Meta:
        verbose_name = _("بند فاتورة")
        verbose_name_plural = _("بنود الفاتورة")

    @property
    def subtotal(self) -> Decimal:
        return (self.quantity or 0) * (self.unit_price or 0)

    def clean(self):
        if not self.product and not self.description:
            raise ValidationError(_("يجب اختيار منتج أو كتابة وصف للبند."))

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Recalculate invoice total after saving the line.
        self.invoice.recalculate_totals()

    def delete(self, *args, **kwargs):
        invoice = self.invoice
        super().delete(*args, **kwargs)
        # Recalculate totals on parent invoice after deletion.
        invoice.recalculate_totals()

    def __str__(self) -> str:
        return f"{self.product or self.description} ({self.quantity})"


# ==============================================================================
# Payments
# ==============================================================================

class PaymentMethod(models.Model):
    """
    Payment method (cash, bank transfer, cheque, card, etc.).
    """

    class MethodType(models.TextChoices):
        CASH = "cash", _("نقدي")
        BANK_TRANSFER = "bank_transfer", _("تحويل بنكي")
        CHEQUE = "cheque", _("شيك")
        CARD = "card", _("بطاقة")
        OTHER = "other", _("أخرى")

    name = models.CharField(
        max_length=100,
        verbose_name=_("الاسم"),
    )
    code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_("الكود"),
    )
    method_type = models.CharField(
        max_length=20,
        choices=MethodType.choices,
        default=MethodType.CASH,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("طريقة دفع")
        verbose_name_plural = _("طرق الدفع")

    def __str__(self) -> str:
        return self.name


class Payment(models.Model):
    """
    سند قبض / صرف
    """

    class Type(models.TextChoices):
        RECEIPT = "receipt", _("سند قبض")
        PAYMENT = "payment", _("سند صرف")

    type = models.CharField(
        max_length=20,
        choices=Type.choices,
        default=Type.RECEIPT,
        db_index=True,
        verbose_name=_("النوع"),
    )

    contact = models.ForeignKey(
        "contacts.Contact",
        on_delete=models.PROTECT,
        related_name="reconcile",
        verbose_name=_("الطرف"),
    )

    method = models.ForeignKey(
        "PaymentMethod",
        on_delete=models.PROTECT,
        verbose_name=_("طريقة الدفع"),
    )

    date = models.DateField(default=timezone.now, db_index=True, verbose_name=_("التاريخ"))

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name=_("المبلغ"),
    )

    currency = models.CharField(max_length=10, default="OMR")
    reference = models.CharField(max_length=255, blank=True, verbose_name=_("مرجع خارجي"))
    notes = models.CharField(max_length=255, blank=True, verbose_name=_("ملاحظات"))

    journal_entry = models.ForeignKey(
        "JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reconcile",
    )

    is_posted = models.BooleanField(default=False)
    posted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # ------------------------------------------------------
    # المبلغ غير المخصص
    # ------------------------------------------------------
    @property
    def allocated_amount(self) -> Decimal:
        """المبلغ الذي تم تسويته من هذه الدفعة."""
        total = self.allocations.aggregate(sum=Sum("amount"))["sum"] or Decimal("0.000")
        return total

    @property
    def unallocated_amount(self) -> Decimal:
        """المبلغ المتبقي من الدفعة."""
        return self.amount - self.allocated_amount

    # ------------------------------------------------------
    @property
    def display_number(self):
        return f"PAY-{self.pk}" if self.pk else _("جديد")

    def __str__(self):
        return f"{self.get_type_display()} {self.amount} - {self.contact}"



DECIMAL_ZERO = Decimal("0.000")


class PaymentReconciliation(models.Model):
    """
    تسوية تربط بين دفعة (Payment) وفاتورة (Invoice).

    - يمكن للدفعة الواحدة أن تُسوى مع عدة فواتير.
    - ويمكن للفاتورة الواحدة أن تستقبل عدة دفعات.
    - الحقل amount يمثل الجزء من الدفعة المطبق على هذه الفاتورة.
    """

    payment = models.ForeignKey(
        "Payment",
        on_delete=models.CASCADE,
        related_name="allocations",
        verbose_name=_("الدفعة"),
    )

    invoice = models.ForeignKey(
        "Invoice",
        on_delete=models.CASCADE,
        related_name="allocations",
        verbose_name=_("الفاتورة"),
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name=_("المبلغ المطبَّق"),
        help_text=_("كم جزء من الدفعة تم تطبيقه على هذه الفاتورة."),
    )

    note = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("ملاحظة"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("تاريخ الإنشاء"),
    )

    class Meta:
        verbose_name = _("تسوية دفعة مع فاتورة")
        verbose_name_plural = _("تسويات الدفعات مع الفواتير")
        ordering = ["-created_at", "id"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gt=DECIMAL_ZERO),
                name="reconciliation_amount_positive",
            ),
            models.UniqueConstraint(
                fields=["payment", "invoice"],
                name="unique_payment_invoice_pair",
            ),
        ]

    def __str__(self):
        return f"تسوية: دفعة {self.payment_id} → فاتورة {self.invoice_id} ({self.amount})"

    # ------------------------------------------------------
    # الطرف المرتبط
    # ------------------------------------------------------
    @property
    def contact(self):
        return getattr(self.payment, "contact", None) or getattr(self.invoice, "customer", None)

    # ------------------------------------------------------
    # التحقق المنطقي
    # ------------------------------------------------------
    def clean(self):
        from django.core.exceptions import ValidationError

        # التأكد أن الطرفين متطابقين
        payment_contact = getattr(self.payment, "contact", None)
        invoice_contact = getattr(self.invoice, "customer", None)

        if payment_contact and invoice_contact and payment_contact != invoice_contact:
            raise ValidationError(_("الدفعة والفاتورة يجب أن تكون لنفس الطرف."))

        # المبلغ
        if self.amount <= DECIMAL_ZERO:
            raise ValidationError(_("المبلغ المطبق يجب أن يكون أكبر من صفر."))

        # لا يتجاوز الباقي على الفاتورة
        if self.amount > self.invoice.balance:
            raise ValidationError(_("المبلغ المطبق أكبر من المبلغ المتبقي على الفاتورة."))

        # لا يتجاوز الباقي في الدفعة
        if self.amount > self.payment.unallocated_amount:
            raise ValidationError(_("المبلغ المطبق أكبر من الجزء غير المخصص من الدفعة."))
