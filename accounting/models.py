from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
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


# ============================================================
# Invoice & InvoiceItem
# ============================================================

class Invoice(StatefulDomainModel):
    """
    فاتورة مبيعات/مشتريات/خدمات (بدون تفاصيل ضريبية معقدة حالياً).
    """

    # 🔹 نوع الفاتورة: مبيعات / مشتريات
    class InvoiceType(models.TextChoices):
        SALES = "sales", _("فاتورة مبيعات")
        PURCHASE = "purchase", _("فاتورة مشتريات")

    class Status(models.TextChoices):
        DRAFT = "draft", _("مسودة")
        SENT = "sent", _("تم الإرسال")
        PARTIALLY_PAID = "partially_paid", _("مدفوعة جزئياً")
        PAID = "paid", _("مدفوعة بالكامل")
        CANCELLED = "cancelled", _("ملغاة")

    # نوع الفاتورة
    type = models.CharField(
        max_length=20,
        choices=InvoiceType.choices,
        default=InvoiceType.SALES,  # كل الفواتير القديمة = مبيعات
        verbose_name=_("نوع الفاتورة"),
        db_index=True,
    )

    # نفس العلاقة لكن بتسمية أعم
    customer = models.ForeignKey(
        "contacts.Contact",
        on_delete=models.PROTECT,
        related_name="invoices",
        verbose_name=_("الطرف"),
        help_text=_("زبون في حالة المبيعات، ومورد في حالة المشتريات."),
    )

    issued_at = models.DateField(
        default=timezone.now,
        verbose_name=_("تاريخ الفاتورة"),
    )
    due_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("تاريخ الاستحقاق"),
    )

    description = models.TextField(
        blank=True,
        verbose_name=_("وصف عام"),
    )

    terms = models.TextField(
        blank=True,
        verbose_name=_("الشروط والأحكام"),
        help_text=_("تظهر في الفاتورة للطرف."),
    )

    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name=_("الإجمالي"),
    )
    paid_amount = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("0.000"),
        verbose_name=_("المبلغ المدفوع"),
        help_text=_("مجموع الدفعات المرتبطة (لأغراض السرعة فقط)."),
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name=_("الحالة"),
        db_index=True,
    )

    ledger_entry = models.OneToOneField(
        "JournalEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoice",
        verbose_name=_("قيد اليومية المرتبط"),
        help_text=_("قيد الترحيل في دفتر الأستاذ إن وُجد."),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("تاريخ الإنشاء"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("آخر تحديث"),
    )

    objects = InvoiceManager()

    class Meta:
        ordering = ("-issued_at", "-id")
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["issued_at"]),
            models.Index(fields=["type", "status", "issued_at"]),  # للفلترة في الليست
        ]
        verbose_name = _("فاتورة")
        verbose_name_plural = _("الفواتير")

    # ---------- Helpers ----------

    @property
    def display_number(self) -> str:
        """
        رقم عرض بسيط يعتمد على الـ PK.
        يمكن تغييره لاحقاً عند إضافة منطق ترقيم مستقل.
        """
        if self.pk:
            return f"INV-{self.pk}"
        return _("فاتورة (غير محفوظة)")

    @property
    def balance(self) -> Decimal:
        """
        الرصيد المتبقي = الإجمالي - المدفوع.
        """
        return (self.total_amount or Decimal("0")) - (
            self.paid_amount or Decimal("0")
        )

    def __str__(self) -> str:
        # يوضح نوع الفاتورة في الستـرنج
        return f"{self.get_type_display()} - {self.display_number} - {self.customer.name}"

    # ---------- Validation ----------

    def clean(self):
        super().clean()
        if self.total_amount is not None and self.paid_amount is not None:
            if self.paid_amount > self.total_amount:
                raise ValidationError(
                    {"paid_amount": _("المبلغ المدفوع لا يمكن أن يتجاوز إجمالي الفاتورة.")}
                )

    # ---------- Core logic ----------

    def save(self, *args, **kwargs):
        """
        على أول حفظ:
        - تطبيق default_due_days / default_terms من Settings لو غير محددة.
        - لا يوجد أي منطق ترقيم هنا حالياً.
        """
        is_new = self._state.adding

        if is_new:
            settings_obj = Settings.get_solo()

            if not self.due_date and settings_obj.default_due_days:
                self.due_date = self.issued_at + timedelta(
                    days=settings_obj.default_due_days
                )

            if not self.terms and settings_obj.default_terms:
                self.terms = settings_obj.default_terms

        super().save(*args, **kwargs)

    # ---------- Domain event hooks ----------

    @on_lifecycle("created")
    def _on_created(self) -> None:
        """
        يُستدعى بعد أول save() ناجح وبعد commit للـ transaction.
        نمرر display_number كسيريال مؤقت.
        """
        self.emit(
            InvoiceCreated(
                invoice_id=self.pk,
                serial=self.display_number,
            )
        )

    @on_transition(Status.DRAFT, Status.SENT)
    def _on_sent(self) -> None:
        """
        يُستدعى عند الانتقال من DRAFT → SENT.
        """
        self.emit(
            InvoiceSent(
                invoice_id=self.pk,
                serial=self.display_number,
            )
        )


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(
        Invoice,
        related_name="items",
        on_delete=models.CASCADE,
        verbose_name=_("الفاتورة"),
    )
    # توحيداً مع بقية النظام: نستخدم inventory.Product
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
        return (self.quantity or Decimal("0")) * (self.unit_price or Decimal("0"))

    def clean(self):
        """
        السطر صالح إذا:
        - product موجود، أو
        - description مكتوب.
        """
        if not self.product and not self.description:
            raise ValidationError(_("يجب اختيار منتج أو كتابة وصف للبند."))

    def __str__(self) -> str:
        label = self.product or self.description or _("بند")
        return f"{label} × {self.quantity}"


# ============================================================
# Settings (سلوك الفواتير والضريبة والنصوص فقط – بدون ترقيم)
# ============================================================


class Settings(models.Model):
    """
    إعدادات الفواتير داخل تطبيق accounting.

    ملاحظة:
    - لا تحتوي على أي إعدادات خاصة بالترقيم.
    """

    # ---------- Default invoice behavior ----------

    default_due_days = models.PositiveSmallIntegerField(
        default=30,
        validators=[MinValueValidator(0), MaxValueValidator(365)],
        verbose_name=_("عدد أيام الاستحقاق الافتراضي"),
        help_text=_("يُستخدم لحساب تاريخ الاستحقاق من تاريخ الفاتورة."),
    )
    auto_confirm_invoice = models.BooleanField(
        default=False,
        verbose_name=_("اعتماد الفاتورة تلقائيًا بعد الحفظ؟"),
        help_text=_("إذا كان مفعلًا، تنتقل الفاتورة من مسودة إلى مُرسلة تلقائيًا."),
    )
    auto_post_to_ledger = models.BooleanField(
        default=False,
        verbose_name=_("ترحيل تلقائي إلى دفتر الأستاذ بعد الاعتماد؟"),
        help_text=_(
            "إذا كان مفعلًا، يتم إنشاء قيد تلقائي في دفتر الأستاذ عند اعتماد الفاتورة."
        ),
    )

    # ---------- VAT behavior ----------

    default_vat_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("5.00"),
        verbose_name=_("نسبة ضريبة القيمة المضافة الافتراضية (%)"),
        help_text=_("يمكن تجاهلها إن لم تُفعّل ضريبة VAT في النظام."),
    )
    prices_include_vat = models.BooleanField(
        default=False,
        verbose_name=_("الأسعار شاملة للضريبة؟"),
    )

    # ---------- Text templates ----------

    default_terms = models.TextField(
        blank=True,
        verbose_name=_("الشروط والأحكام الافتراضية"),
    )
    footer_notes = models.TextField(
        blank=True,
        verbose_name=_("ملاحظات أسفل الفاتورة"),
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("تاريخ آخر تعديل"),
    )

    class Meta:
        verbose_name = _("إعدادات الفواتير")
        verbose_name_plural = _("إعدادات الفواتير")

    def __str__(self) -> str:
        return _("إعدادات الفواتير")

    # ---------- Singleton helper ----------

    @classmethod
    def get_solo(cls) -> "Settings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


# ==============================================================================
# Fiscal Year
# ==============================================================================


class FiscalYear(models.Model):
    year = models.PositiveIntegerField(unique=True, verbose_name=_("السنة"))
    start_date = models.DateField(verbose_name=_("تاريخ البداية"))
    end_date = models.DateField(verbose_name=_("تاريخ النهاية"))
    is_closed = models.BooleanField(default=False, verbose_name=_("مقفلة؟"))
    is_default = models.BooleanField(
        default=False,
        verbose_name=_("سنة افتراضية للتقارير؟"),
        help_text=_("تُستخدم كسنة افتراضية في التقارير."),
    )

    objects = FiscalYearManager()

    class Meta:
        ordering = ["-year"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(start_date__lte=models.F("end_date")),
                name="fiscalyear_start_before_end",
            )
        ]
        verbose_name = _("سنة مالية")
        verbose_name_plural = _("السنوات المالية")

    def __str__(self) -> str:
        return str(self.year)

    @classmethod
    def for_date(cls, date):
        """
        يجد السنة المالية التي تحتوي التاريخ (مفوض للـ Manager).
        """
        return cls.objects.for_date(date)

    def save(self, *args, **kwargs):
        """
        ضمان أن سنة واحدة فقط تحمل is_default=True.
        """
        super().save(*args, **kwargs)
        if self.is_default:
            FiscalYear.objects.exclude(pk=self.pk).update(is_default=False)


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
        verbose_name=_("الحساب الأب"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("نشط"),
    )

    allow_settlement = models.BooleanField(
        default=True,
        help_text=_("السماح باستخدام الحساب في التسويات (عملاء/موردين)."),
    )

    objects = AccountManager()

    class Meta:
        ordering = ["code"]
        verbose_name = _("حساب")
        verbose_name_plural = _("الحسابات")

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


# ==============================================================================
# Journal
# ==============================================================================


class Journal(models.Model):
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
    fiscal_year = models.ForeignKey(
        FiscalYear,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="entries",
        verbose_name=_("السنة المالية"),
    )
    journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="entries",
        verbose_name=_("دفتر اليومية"),
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

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("أنشئ في"),
    )
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
        verbose_name = _("قيد يومية")
        verbose_name_plural = _("قيود اليومية")

    # ---------- Helpers ----------

    @property
    def display_number(self) -> str:
        """
        رقم عرض بسيط يعتمد على الـ PK.
        """
        if self.pk:
            return f"JE-{self.pk}"
        return _("قيد (غير محفوظ)")

    def __str__(self) -> str:
        return f"{self.display_number} ({self.date})"

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
        - لا يوجد أي منطق ترقيم مستقل، نعتمد على الـ PK.
        """
        if self.date:
            fy = FiscalYear.for_date(self.date)
            if fy is not None:
                self.fiscal_year = fy

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
        default=Decimal("0.000"),
        verbose_name=_("مدين"),
    )
    credit = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("0.000"),
        verbose_name=_("دائن"),
    )
    order = models.PositiveIntegerField(
        default=0,
        verbose_name=_("ترتيب السطر"),
    )

    objects = JournalLineManager()

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.CheckConstraint(
                check=~(models.Q(debit__gt=0) & models.Q(credit__gt=0)),
                name="journalline_not_both_debit_credit",
            )
        ]
        verbose_name = _("سطر قيد")
        verbose_name_plural = _("سطور القيود")

    def __str__(self) -> str:
        return f"{self.entry_id} - {self.account}"


# ==============================================================================
# Helpers: default journals
# ==============================================================================


def get_default_journal_for_manual_entry():
    return Journal.objects.get_default_for_manual_entry()


def get_default_journal_for_sales_invoice():
    return Journal.objects.get_default_for_sales_invoice()


def get_default_journal_for_customer_payment():
    return Journal.objects.get_default_for_customer_payment()


# ==============================================================================
# LedgerSettings
# ==============================================================================


class LedgerSettings(models.Model):
    """
    إعدادات دفتر الأستاذ:
    - ربط دفاتر اليومية بوظائف النظام (مبيعات، مشتريات، بنك، كاش، ...).
    - ربط الحسابات الافتراضية لعمليات المبيعات (عملاء، مبيعات، ضريبة، دفعات مقدمة).
    """

    default_manual_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_default_manual_journal",
        limit_choices_to={"is_active": True},
        verbose_name=_("دفتر القيود اليدوية"),
    )
    sales_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_sales_journal",
        limit_choices_to={"is_active": True},
        verbose_name=_("دفتر المبيعات"),
    )
    purchase_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_purchase_journal",
        limit_choices_to={"is_active": True},
        verbose_name=_("دفتر المشتريات"),
    )
    cash_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_cash_journal",
        limit_choices_to={"is_active": True},
        verbose_name=_("دفتر الكاش"),
    )
    bank_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_bank_journal",
        limit_choices_to={"is_active": True},
        verbose_name=_("دفتر البنك"),
    )
    opening_balance_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_opening_balance_journal",
        limit_choices_to={"is_active": True},
        verbose_name=_("دفتر الرصيد الافتتاحي"),
    )
    closing_journal = models.ForeignKey(
        Journal,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_closing_journal",
        limit_choices_to={"is_active": True},
        verbose_name=_("دفتر إقفال السنة"),
    )

    sales_receivable_account = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_sales_receivable_account",
        verbose_name=_("حساب العملاء (ذمم مدينة)"),
        limit_choices_to={"is_active": True},
    )
    sales_revenue_0_account = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_sales_revenue_0_account",
        verbose_name=_("حساب المبيعات 0٪"),
        limit_choices_to={"is_active": True},
    )
    sales_vat_output_account = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_sales_vat_output_account",
        verbose_name=_("حساب ضريبة القيمة المضافة المستحقة (مخرجات)"),
        limit_choices_to={"is_active": True},
    )
    sales_advance_account = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="as_sales_advance_account",
        verbose_name=_("حساب دفعات مقدّمة من العملاء"),
        limit_choices_to={"is_active": True},
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("تاريخ آخر تعديل"),
    )

    class Meta:
        verbose_name = _("إعدادات دفتر الأستاذ")
        verbose_name_plural = _("إعدادات دفتر الأستاذ")

    def __str__(self) -> str:
        return _("إعدادات دفتر الأستاذ")

    @classmethod
    def get_solo(cls) -> "LedgerSettings":
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
