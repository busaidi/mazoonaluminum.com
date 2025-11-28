# accounting/managers.py

from django.db import models
from django.utils import timezone


# ==============================================================================
# FiscalYear
# ==============================================================================


class FiscalYearQuerySet(models.QuerySet):
    """
    QuerySet helpers for FiscalYear.
    """

    def open(self):
        return self.filter(is_closed=False)

    def closed(self):
        return self.filter(is_closed=True)

    def for_year(self, year: int):
        return self.filter(year=year)

    def containing(self, date):
        """
        Fiscal years that contain the given date within [start_date, end_date].
        """
        if not date:
            return self.none()
        return self.filter(start_date__lte=date, end_date__gte=date)


class FiscalYearManager(models.Manager.from_queryset(FiscalYearQuerySet)):
    """
    Manager wrapper to expose convenient helpers like:
        FiscalYear.objects.for_date(date)
    """

    def for_date(self, date):
        """
        Get the fiscal year that contains `date`, or fallback to same calendar year.
        Returns None if nothing is found.
        """
        if not date:
            return None

        fy = self.containing(date).first()
        if fy:
            return fy
        return self.for_year(date.year).first()


# ==============================================================================
# Account
# ==============================================================================


class AccountQuerySet(models.QuerySet):
    """
    QuerySet helpers for Account.
    """

    def active(self):
        return self.filter(is_active=True)

    def inactive(self):
        return self.filter(is_active=False)

    def settlement_allowed(self):
        """
        Accounts that can be used for settlements (receivables / payables).
        """
        return self.active().filter(allow_settlement=True)


class AccountManager(models.Manager.from_queryset(AccountQuerySet)):
    """
    Manager for Account. Currently just exposes AccountQuerySet.
    """
    pass


# ==============================================================================
# Journal
# ==============================================================================


class JournalQuerySet(models.QuerySet):
    """
    QuerySet helpers for Journal.
    """

    def active(self):
        return self.filter(is_active=True)

    def of_type(self, journal_type: str):
        return self.filter(type=journal_type)


class JournalManager(models.Manager.from_queryset(JournalQuerySet)):
    """
    Manager for Journal with helpers to pick default journals.
    """

    def _get_default_by_types(self, preferred_types):
        """
        Internal helper to choose a default journal given a list of preferred types.

        Priority:
        - Journal with type in `preferred_types` AND is_default=True (if exists).
        - Otherwise: first journal with that type.
        - If nothing found: first active journal.
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
        Try LedgerSettings.<field_name> first (if active), then fall back to
        _get_default_by_types(fallback_types).
        """
        from .models import LedgerSettings  # local import to avoid circular

        try:
            settings_obj = LedgerSettings.get_solo()
        except Exception:
            settings_obj = None

        if settings_obj is not None:
            journal = getattr(settings_obj, field_name, None)
            if journal is not None and journal.is_active:
                return journal

        # Fallback to behavior based on journal type
        return self._get_default_by_types(fallback_types)

    def get_default_for_manual_entry(self):
        """
        Default journal for manual entries:

        Priority:
        1) LedgerSettings.default_manual_journal (if set & active)
        2) Any journal of type GENERAL (preferring is_default=True)
        """
        from .models import Journal  # to use Journal.Type

        return self._get_default_from_settings(
            "default_manual_journal",
            [Journal.Type.GENERAL],
        )

    def get_default_for_sales_invoice(self):
        """
        Default journal for sales invoices:

        Priority:
        1) LedgerSettings.sales_journal
        2) Any journal of type SALES
        """
        from .models import Journal  # to use Journal.Type

        return self._get_default_from_settings(
            "sales_journal",
            [Journal.Type.SALES],
        )

    def get_default_for_customer_payment(self):
        """
        Default journal for customer reconcile (cash or bank).

        Preference order:
        - CASH then BANK (preferring is_default=True when possible).
        """
        from .models import Journal  # to use Journal.Type

        return self._get_default_by_types(
            [Journal.Type.CASH, Journal.Type.BANK]
        )


# ==============================================================================
# JournalEntry
# ==============================================================================


class JournalEntryQuerySet(models.QuerySet):
    """
    QuerySet helpers for JournalEntry.
    """

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
        Filter entries within a date range [date_from, date_to].
        """
        qs = self
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return qs

    def with_totals(self):
        """
        Annotate each entry with:
          - total_debit_value
          - total_credit_value
        """
        return self.annotate(
            total_debit_value=models.Sum("lines__debit"),
            total_credit_value=models.Sum("lines__credit"),
        )


class JournalEntryManager(models.Manager.from_queryset(JournalEntryQuerySet)):
    """
    Manager for JournalEntry.

    ⚠️ No numbering logic here. Numbering is currently based on PK or
    will be handled later with a dedicated mechanism.
    """
    pass


# ==============================================================================
# JournalLine
# ==============================================================================


class JournalLineQuerySet(models.QuerySet):
    """
    QuerySet helpers for JournalLine.
    """

    def posted_only(self):
        """
        Lines whose parent entry is posted.
        """
        return self.filter(entry__posted=True)

    def posted(self):
        """
        Convenient alias:
            JournalLine.objects.posted()
        """
        return self.posted_only()

    def for_account(self, account):
        if account is None:
            return self.none()
        return self.filter(account=account)

    def within_period(self, date_from=None, date_to=None):
        """
        Lines within a given period based on entry.date.
        """
        qs = self
        if date_from:
            qs = qs.filter(entry__date__gte=date_from)
        if date_to:
            qs = qs.filter(entry__date__lte=date_to)
        return qs


class JournalLineManager(models.Manager.from_queryset(JournalLineQuerySet)):
    """
    Manager for JournalLine; exposes JournalLineQuerySet helpers.
    """
    pass


# ==============================================================================
# Invoice
# ==============================================================================


class InvoiceQuerySet(models.QuerySet):
    """
    Custom QuerySet for invoices with convenient filters.
    Status uses Invoice.status field values:
      - draft / sent / partially_paid / paid / cancelled
    """

    # ----- By status -----

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
        Open invoices (with remaining balance):
        - not cancelled
        - total_amount > paid_amount
        """
        return self.exclude(status="cancelled").filter(
            total_amount__gt=models.F("paid_amount")
        )

    # ----- Overdue -----

    def overdue(self):
        """
        Overdue invoices:
        - has due_date
        - due_date < today
        - not fully paid and not cancelled
        """
        today = timezone.localdate()
        return (
            self.exclude(status__in=["paid", "cancelled"])
            .filter(due_date__isnull=False, due_date__lt=today)
        )

    # ----- By customer -----

    def for_customer(self, customer):
        """
        Filter by customer:
        - accepts Contact instance or ID.
        """
        from contacts.models import Contact  # local import to avoid circular

        if isinstance(customer, Contact):
            customer_id = customer.pk
        else:
            customer_id = customer
        return self.filter(customer_id=customer_id)

    # ----- Date ranges -----

    def in_year(self, year: int):
        """
        Invoices within a specific calendar year (based on issued_at).
        """
        return self.filter(issued_at__year=year)

    def in_period(self, date_from, date_to):
        """
        Invoices within a period [date_from, date_to] (based on issued_at).
        """
        return self.filter(issued_at__gte=date_from, issued_at__lte=date_to)


class InvoiceManager(models.Manager.from_queryset(InvoiceQuerySet)):
    """
    Manager for Invoice using InvoiceQuerySet.
    High-level helpers can be added here later if needed.
    """
    pass
