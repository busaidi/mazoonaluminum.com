# accounting/managers.py
from django.db import models
from django.utils import timezone


# ------------------------------------------------------------------------------
# FiscalYear
# ------------------------------------------------------------------------------


class FiscalYearQuerySet(models.QuerySet):
    def open(self):
        return self.filter(is_closed=False)

    def closed(self):
        return self.filter(is_closed=True)

    def for_year(self, year: int):
        return self.filter(year=year)

    def containing(self, date):
        """
        السنوات التي تحتوي التاريخ المعطى ضمن [start_date, end_date].
        """
        if not date:
            return self.none()
        return self.filter(start_date__lte=date, end_date__gte=date)


class FiscalYearManager(models.Manager.from_queryset(FiscalYearQuerySet)):
    def for_date(self, date):
        """
        التفاف مريح للاستخدام:
        FiscalYear.objects.for_date(date)
        """
        if not date:
            return None

        fy = self.containing(date).first()
        if fy:
            return fy
        return self.for_year(date.year).first()


# ------------------------------------------------------------------------------
# Account
# ------------------------------------------------------------------------------


class AccountQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def inactive(self):
        return self.filter(is_active=False)

    def settlement_allowed(self):
        """
        الحسابات المسموح استخدامها في التسويات (عملاء/موردين).
        """
        return self.active().filter(allow_settlement=True)


class AccountManager(models.Manager.from_queryset(AccountQuerySet)):
    pass


# ------------------------------------------------------------------------------
# Journal
# ------------------------------------------------------------------------------


class JournalQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def of_type(self, journal_type: str):
        return self.filter(type=journal_type)


class JournalManager(models.Manager.from_queryset(JournalQuerySet)):
    """
    Manager لدفاتر اليومية مع دوال جاهزة لاختيار الدفاتر الافتراضية.
    """

    def _get_default_by_types(self, preferred_types):
        """
        Helper داخلي لاختيار دفتر افتراضي حسب أنواع مفضلة.
        - يفضّل الدفاتر المعلمة كـ is_default=True إن وجدت.
        - وإلا يأخذ أول دفتر من النوع المطلوب.
        """
        qs = self.active()

        for journal_type in preferred_types:
            journal = (
                qs.filter(type=journal_type, is_default=True).first()
                or qs.filter(type=journal_type).first()
            )
            if journal:
                return journal
        return qs.first()

    def _get_default_from_settings(self, field_name, fallback_types):
        """
        يحاول أولاً جلب الدفتر من LedgerSettings.<field_name> إن وُجد
        وكان نشطًا، وإلا يرجع إلى fallback حسب النوع.
        """
        from .models import LedgerSettings  # import محلي لتجنّب الدوران

        try:
            settings_obj = LedgerSettings.get_solo()
        except Exception:
            settings_obj = None

        if settings_obj is not None:
            journal = getattr(settings_obj, field_name, None)
            if journal is not None and journal.is_active:
                return journal

        # fallback للسلوك السابق (حسب النوع)
        return self._get_default_by_types(fallback_types)

    def get_default_for_manual_entry(self):
        """
        دفتر افتراضي للقيود اليدوية:
        - أولاً: LedgerSettings.default_manual_journal (إن وجد وكان نشطًا)
        - ثانيًا: أي دفتر من النوع GENERAL.
        """
        from .models import Journal  # لاستخدام Journal.Type

        return self._get_default_from_settings(
            "default_manual_journal",
            [Journal.Type.GENERAL],
        )

    def get_default_for_sales_invoice(self):
        """
        دفتر افتراضي لفواتير المبيعات:
        - أولاً: LedgerSettings.sales_journal
        - ثانيًا: أي دفتر من النوع SALES.
        """
        from .models import Journal  # لاستخدام Journal.Type

        return self._get_default_from_settings(
            "sales_journal",
            [Journal.Type.SALES],
        )

    def get_default_for_customer_payment(self):
        """
        دفتر افتراضي لدفعات الزبائن (كاش أو بنك).
        الترتيب:
        - CASH ثم BANK (مع تفضيل is_default إن وجد).
        """
        from .models import Journal  # لاستخدام Journal.Type

        return self._get_default_by_types(
            [Journal.Type.CASH, Journal.Type.BANK]
        )


# ------------------------------------------------------------------------------
# JournalEntry
# ------------------------------------------------------------------------------


class JournalEntryQuerySet(models.QuerySet):
    def posted(self):
        return self.filter(posted=True)

    def unposted(self):
        return self.filter(posted=False)

    def for_fiscal_year(self, fiscal_year):
        if fiscal_year is None:
            return self.none()
        return self.filter(fiscal_year=fiscal_year)

    def for_period(self, date_from=None, date_to=None):
        """
        تقييد القيود ضمن فترة زمنية:
        [date_from, date_to]
        """
        qs = self
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return qs

    def with_totals(self):
        """
        annotate بمجموع المدين والدائن لكل قيد:
        - total_debit_value
        - total_credit_value
        """
        return self.annotate(
            total_debit_value=models.Sum("lines__debit"),
            total_credit_value=models.Sum("lines__credit"),
        )


class JournalEntryManager(models.Manager.from_queryset(JournalEntryQuerySet)):
    """
    Manager لقيود اليومية.

    ⚠️ لا يوجد أي منطق ترقيم هنا الآن.
    الترقيم (إن عاد لاحقاً) سيكون عبر PK أو ريفاكتور جديد منفصل.
    """
    pass


# ------------------------------------------------------------------------------
# JournalLine
# ------------------------------------------------------------------------------


class JournalLineQuerySet(models.QuerySet):
    def posted_only(self):
        """
        أسطر القيود المُرحّلة فقط.
        """
        return self.filter(entry__posted=True)

    def posted(self):
        """
        Alias مريح:
        JournalLine.objects.posted()
        """
        return self.posted_only()

    def for_account(self, account):
        if account is None:
            return self.none()
        return self.filter(account=account)

    def within_period(self, date_from=None, date_to=None):
        """
        أسطر ضمن فترة زمنية اعتمادًا على تاريخ القيد.
        """
        qs = self
        if date_from:
            qs = qs.filter(entry__date__gte=date_from)
        if date_to:
            qs = qs.filter(entry__date__lte=date_to)
        return qs


class JournalLineManager(models.Manager.from_queryset(JournalLineQuerySet)):
    pass


# ------------------------------------------------------------------------------
# Invoice
# ------------------------------------------------------------------------------


class InvoiceQuerySet(models.QuerySet):
    """
    QuerySet مخصص للفواتير مع فلاتر جاهزة للتقارير وواجهات المستخدِم.
    الحالة تعتمد على الحقل status في Invoice:
    - draft / sent / partially_paid / paid / cancelled
    """

    # ----- بحسب الحالة -----

    def drafts(self):
        return self.filter(status="draft")

    def sent(self):
        return self.filter(status="sent")

    def partially_paid(self):
        return self.filter(status="partially_paid")

    def paid(self):
        return self.filter(status="paid")

    def cancelled(self):
        return self.filter(status="cancelled")

    def open(self):
        """
        فواتير مفتوحة (عليها رصيد):
        - ليست ملغاة
        - total_amount > paid_amount
        """
        return self.exclude(status="cancelled").filter(
            total_amount__gt=models.F("paid_amount")
        )

    # ----- التزامات متأخرة -----

    def overdue(self):
        """
        فواتير متأخرة:
        - لها due_date
        - due_date < اليوم
        - ليست مدفوعة بالكامل ولا ملغاة
        """
        today = timezone.localdate()
        return (
            self.exclude(status__in=["paid", "cancelled"])
            .filter(due_date__isnull=False, due_date__lt=today)
        )

    # ----- حسب الزبون -----

    def for_customer(self, customer):
        """
        فلتر بحسب الزبون:
        - يقبل Contact instance أو ID.
        """
        from contacts.models import Contact  # import محلي لتفادي الدوران

        if isinstance(customer, Contact):
            customer_id = customer.pk
        else:
            customer_id = customer
        return self.filter(customer_id=customer_id)

    # ----- نطاق الزمن -----

    def in_year(self, year: int):
        """فواتير ضمن سنة معينة (حسب issued_at__year)."""
        return self.filter(issued_at__year=year)

    def in_period(self, date_from, date_to):
        """
        فواتير ضمن فترة زمنية:
        [date_from, date_to]
        """
        return self.filter(issued_at__gte=date_from, issued_at__lte=date_to)


class InvoiceManager(models.Manager.from_queryset(InvoiceQuerySet)):
    """
    Manager للفواتير يستخدم InvoiceQuerySet.
    يمكنك لاحقًا إضافة دوال high-level هنا إذا احتجت.
    """
    pass
