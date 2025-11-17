from django.db import models
from django.db.models import Sum
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
        if not date:
            return self.none()
        return self.filter(start_date__lte=date, end_date__gte=date)


class FiscalYearManager(models.Manager.from_queryset(FiscalYearQuerySet)):
    def for_date(self, date):
        """
        Wrapper مريح للوصول من خلال manager:
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

    def _get_default_by_types(self, preferred_types):
        """
        Internal helper لاختيار دفتر افتراضي حسب أنواع مفضلة.
        """
        qs = self.active()
        from .models import Journal  # circular import protection

        for journal_type in preferred_types:
            journal = (
                qs.filter(type=journal_type, is_default=True).first()
                or qs.filter(type=journal_type).first()
            )
            if journal:
                return journal
        return qs.first()

    def get_default_for_manual_entry(self):
        """
        دفتر افتراضي للقيود اليدوية (غالبًا General).
        """
        from .models import Journal
        return self._get_default_by_types([Journal.Type.GENERAL])

    def get_default_for_sales_invoice(self):
        """
        دفتر افتراضي لفواتير المبيعات.
        """
        from .models import Journal
        return self._get_default_by_types([Journal.Type.SALES])

    def get_default_for_customer_payment(self):
        """
        دفتر افتراضي لدفعات الزبائن (كاش أو بنك).
        """
        from .models import Journal
        return self._get_default_by_types([Journal.Type.CASH, Journal.Type.BANK])


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
        qs = self
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return qs

    def with_totals(self):
        return self.annotate(
            total_debit_value=Sum("lines__debit"),
            total_credit_value=Sum("lines__credit"),
        )


class JournalEntryManager(models.Manager.from_queryset(JournalEntryQuerySet)):

    def generate_number(self, journal, fiscal_year, date) -> str:
        """
        Generate a unique number of form: <PREFIX>-<YEAR>-<SEQ>
        e.g. GEN-2025-0001, CASH-2025-0002, etc.

        الترقيم هنا مرتبط بالـ prefix فقط:
        - prefix = journal.code.upper() أو "JE"
        - year من السنة المالية أو من التاريخ
        ثم نبحث عن آخر رقم يبدأ بهذا الـ prefix بغضّ النظر عن حقل journal،
        لأن حقل number عليه UNIQUE على مستوى الجدول كله.
        """
        # 1) تحديد السنة
        if fiscal_year is not None:
            year = fiscal_year.year
        elif date is not None:
            year = date.year
        else:
            year = timezone.now().year

        # 2) تحديد الـ prefix
        if journal is not None and journal.code:
            prefix = journal.code.upper()
        else:
            prefix = "JE"

        base_prefix = f"{prefix}-{year}-"

        # 3) جلب كل الأرقام الحالية التي تبدأ بهذه المقدمة
        qs = self.get_queryset().filter(number__startswith=base_prefix)
        if journal is not None:
            qs = qs.filter(journal=journal)

        numbers = list(qs.values_list("number", flat=True))

        max_seq = 0
        for num in numbers:
            if not num:
                continue
            parts = str(num).split("-")
            if not parts:
                continue
            tail = parts[-1]
            try:
                seq = int(tail)
            except ValueError:
                # لو tail مش رقم (بيانات قديمة أو تالفة) نتجاهله
                continue
            if seq > max_seq:
                max_seq = seq

        # 4) اقترح رقم جديد أعلى من كل الموجود
        new_seq = max_seq + 1

        # 5) تأكيد نهائي: طالما الرقم موجود في الجدول، زِد الـ sequence
        # هذا يحل مشكلات:
        # - بيانات قديمة بنفس الرقم لكن من دفتر آخر
        # - حالة الـ race condition النادرة
        while self.get_queryset().filter(number=f"{base_prefix}{new_seq:04d}").exists():
            new_seq += 1

        return f"{base_prefix}{new_seq:04d}"


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
        Alias مريح متوافق مع الاستخدام في الـ views:
        JournalLine.objects.posted()
        """
        return self.posted_only()

    def for_account(self, account):
        if account is None:
            return self.none()
        return self.filter(account=account)

    def within_period(self, date_from=None, date_to=None):
        qs = self
        if date_from:
            qs = qs.filter(entry__date__gte=date_from)
        if date_to:
            qs = qs.filter(entry__date__lte=date_to)
        return qs


class JournalLineManager(models.Manager.from_queryset(JournalLineQuerySet)):
    pass
