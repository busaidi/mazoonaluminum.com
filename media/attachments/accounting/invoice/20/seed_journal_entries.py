from decimal import Decimal
import random

from django.core.management.base import BaseCommand
from django.utils import timezone

from ledger.models import (
    Account,
    FiscalYear,
    Journal,
    JournalEntry,
    JournalLine,
)


class Command(BaseCommand):
    help = "Seed demo journal entries and lines for testing the ledger."

    def handle(self, *args, **options):
        # Safety check: do not create duplicates if seed entries already exist
        if JournalEntry.objects.filter(reference__startswith="SEED-").exists():
            self.stdout.write(
                self.style.WARNING(
                    "Seed journal entries already exist (reference starts with 'SEED-'). "
                    "Delete them first if you want to reseed."
                )
            )
            return

        # Ensure we have at least one fiscal year
        fiscal_year = FiscalYear.objects.order_by("-year").first()
        if fiscal_year is None:
            today = timezone.now().date()
            fiscal_year = FiscalYear.objects.create(
                year=today.year,
                start_date=today.replace(month=1, day=1),
                end_date=today.replace(month=12, day=31),
                is_closed=False,
            )
            self.stdout.write(
                self.style.WARNING(
                    f"No fiscal year found. Created fiscal year {fiscal_year.year}."
                )
            )

        # Ensure we have journals
        journals = {j.code: j for j in Journal.objects.filter(is_active=True)}
        if not journals:
            self.stdout.write(
                self.style.ERROR(
                    "No journals found. Please run `python manage.py seed_journals` first."
                )
            )
            return

        # Helper to pick a journal by type or fallback
        def get_journal_by_type(journal_type, fallback_code="GEN"):
            j = (
                Journal.objects.filter(type=journal_type, is_active=True)
                .order_by("code")
                .first()
            )
            if j:
                return j
            # Fallback to specific code if exists
            if fallback_code in journals:
                return journals[fallback_code]
            # Last fallback: any active journal
            return Journal.objects.filter(is_active=True).order_by("code").first()

        general_journal = get_journal_by_type(Journal.Type.GENERAL)
        cash_journal = get_journal_by_type(Journal.Type.CASH)
        sales_journal = get_journal_by_type(Journal.Type.SALES)

        # Ensure we have accounts to work with
        assets = list(Account.objects.filter(type=Account.Type.ASSET, is_active=True))
        liabilities = list(
            Account.objects.filter(type=Account.Type.LIABILITY, is_active=True)
        )
        equity = list(Account.objects.filter(type=Account.Type.EQUITY, is_active=True))
        revenues = list(
            Account.objects.filter(type=Account.Type.REVENUE, is_active=True)
        )
        expenses = list(
            Account.objects.filter(type=Account.Type.EXPENSE, is_active=True)
        )

        if not assets or not revenues:
            self.stdout.write(
                self.style.ERROR(
                    "Not enough accounts to create demo entries "
                    "(need at least one ASSET and one REVENUE account)."
                )
            )
            return

        # Simple helpers to safely pick an account from a list or fallback
        def pick_or_fallback(primary_list, fallback_list):
            if primary_list:
                return random.choice(primary_list)
            if fallback_list:
                return random.choice(fallback_list)
            return Account.objects.filter(is_active=True).order_by("code").first()

        created_entries = 0
        created_lines = 0

        today = timezone.now().date()

        # === 1) General journal entries (manual adjustments) ===
        for i in range(1, 4):
            date = today.replace(day=max(1, today.day - i))
            amount = Decimal(str(100 * i))

            asset_acc = pick_or_fallback(assets, [])
            expense_acc = pick_or_fallback(expenses, assets)

            entry = JournalEntry.objects.create(
                fiscal_year=fiscal_year,
                journal=general_journal,
                date=date,
                reference=f"SEED-GEN-{i:03d}",
                description=f"Seed general journal entry {i}",
                posted=(i % 2 == 0),  # every second entry is posted
                posted_at=timezone.now() if i % 2 == 0 else None,
                posted_by=None,
            )
            created_entries += 1

            # Debit expense, credit asset (or vice versa, just to have movement)
            JournalLine.objects.create(
                entry=entry,
                account=expense_acc,
                description="Seed general debit",
                debit=amount,
                credit=Decimal("0"),
                order=0,
            )
            JournalLine.objects.create(
                entry=entry,
                account=asset_acc,
                description="Seed general credit",
                debit=Decimal("0"),
                credit=amount,
                order=1,
            )
            created_lines += 2

        # === 2) Sales journal entries (typical invoice posting) ===
        for i in range(1, 4):
            date = today.replace(day=max(1, today.day - (i + 3)))
            amount = Decimal(str(250 * i))

            ar_acc = pick_or_fallback(assets, [])
            revenue_acc = pick_or_fallback(revenues, [])

            entry = JournalEntry.objects.create(
                fiscal_year=fiscal_year,
                journal=sales_journal,
                date=date,
                reference=f"SEED-SALES-{i:03d}",
                description=f"Seed sales entry {i}",
                posted=True,  # usually sales entries are posted
                posted_at=timezone.now(),
                posted_by=None,
            )
            created_entries += 1

            # Debit A/R, credit Revenue
            JournalLine.objects.create(
                entry=entry,
                account=ar_acc,
                description="Seed sales debit (Accounts Receivable)",
                debit=amount,
                credit=Decimal("0"),
                order=0,
            )
            JournalLine.objects.create(
                entry=entry,
                account=revenue_acc,
                description="Seed sales credit (Revenue)",
                debit=Decimal("0"),
                credit=amount,
                order=1,
            )
            created_lines += 2

        # === 3) Cash journal entries (simple cash movements) ===
        for i in range(1, 3):
            date = today.replace(day=max(1, today.day - (i + 6)))
            amount = Decimal(str(150 * i))

            cash_related_acc = pick_or_fallback(assets, [])
            expense_acc = pick_or_fallback(expenses, assets)

            entry = JournalEntry.objects.create(
                fiscal_year=fiscal_year,
                journal=cash_journal,
                date=date,
                reference=f"SEED-CASH-{i:03d}",
                description=f"Seed cash entry {i}",
                posted=True,
                posted_at=timezone.now(),
                posted_by=None,
            )
            created_entries += 1

            # Debit expense, credit cash (or asset)
            JournalLine.objects.create(
                entry=entry,
                account=expense_acc,
                description="Seed cash expense debit",
                debit=amount,
                credit=Decimal("0"),
                order=0,
            )
            JournalLine.objects.create(
                entry=entry,
                account=cash_related_acc,
                description="Seed cash credit",
                debit=Decimal("0"),
                credit=amount,
                order=1,
            )
            created_lines += 2

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created_entries} journal entries with {created_lines} lines."
            )
        )
