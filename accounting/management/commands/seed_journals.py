# accounting/management/commands/seed_journals.py

from django.core.management.base import BaseCommand

from accounting.models import Journal, LedgerSettings


class Command(BaseCommand):
    """
    Seed default journals and map them into LedgerSettings.
    """

    help = "Create default journals (general, sales, purchase, cash, bank, opening, closing) and link them to LedgerSettings."

    def handle(self, *args, **options):
        # ---------------------------------------------------------------------
        # 1) Create default journals (idempotent: safe to run multiple times)
        # ---------------------------------------------------------------------
        journal_defs = [
            {
                "code": "GEN",
                "name": "General Journal",
                "type": Journal.Type.GENERAL,
                "is_default": True,     # default manual journal
            },
            {
                "code": "SALE",
                "name": "Sales Journal",
                "type": Journal.Type.SALES,
            },
            {
                "code": "PURCH",
                "name": "Purchase Journal",
                "type": Journal.Type.PURCHASE,
            },
            {
                "code": "CASH",
                "name": "Cash Journal",
                "type": Journal.Type.CASH,
            },
            {
                "code": "BANK",
                "name": "Bank Journal",
                "type": Journal.Type.BANK,
            },
            {
                "code": "OPEN",
                "name": "Opening Balance Journal",
                "type": Journal.Type.GENERAL,
            },
            {
                "code": "CLOSE",
                "name": "Year Closing Journal",
                "type": Journal.Type.GENERAL,
            },
        ]

        code_to_journal = {}

        for data in journal_defs:
            code = data["code"]

            journal, created = Journal.objects.get_or_create(
                code=code,
                defaults={
                    "name": data["name"],
                    "type": data["type"],
                    "is_default": data.get("is_default", False),
                    "is_active": True,
                },
            )

            # If already exists, you can optionally update name/type
            if not created:
                journal.name = data["name"]
                journal.type = data["type"]
                # do not override is_default/is_active blindly
                journal.save(update_fields=["name", "type"])

            code_to_journal[code] = journal

            msg = f"Journal [{code}] - {journal.name}"
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created: {msg}"))
            else:
                self.stdout.write(self.style.WARNING(f"Exists: {msg}"))

        # ---------------------------------------------------------------------
        # 2) Map journals into LedgerSettings singleton
        # ---------------------------------------------------------------------
        settings = LedgerSettings.get_solo()

        # Default manual journal → GEN
        settings.default_manual_journal = code_to_journal.get("GEN")

        # Sales / Purchase
        settings.sales_journal = code_to_journal.get("SALE")
        settings.purchase_journal = code_to_journal.get("PURCH")

        # Cash / Bank
        settings.cash_journal = code_to_journal.get("CASH")
        settings.bank_journal = code_to_journal.get("BANK")

        # Opening / Closing
        settings.opening_balance_journal = code_to_journal.get("OPEN")
        settings.closing_journal = code_to_journal.get("CLOSE")

        settings.save()

        self.stdout.write(self.style.SUCCESS("LedgerSettings updated with default journals."))
        self.stdout.write(self.style.SUCCESS("Done seeding journals."))
