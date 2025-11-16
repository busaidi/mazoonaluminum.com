# ledger/management/commands/seed_accounts.py
from django.core.management.base import BaseCommand
from ledger.models import Account


class Command(BaseCommand):
    help = "Seed basic chart of accounts for the Ledger app."

    def handle(self, *args, **options):
        # نمط: code, name, type, parent_code, allow_settlement
        accounts_data = [
            # ===== ASSETS =====
            ("1000", "Assets", Account.Type.ASSET, None, False),
            ("1100", "Current Assets", Account.Type.ASSET, "1000", False),
            ("1110", "Cash on Hand", Account.Type.ASSET, "1100", False),
            ("1120", "Bank Account", Account.Type.ASSET, "1100", False),
            ("1130", "Accounts Receivable", Account.Type.ASSET, "1100", True),
            ("1200", "Inventory", Account.Type.ASSET, "1000", False),

            # ===== LIABILITIES =====
            ("2000", "Liabilities", Account.Type.LIABILITY, None, False),
            ("2100", "Current Liabilities", Account.Type.LIABILITY, "2000", False),
            ("2110", "Accounts Payable", Account.Type.LIABILITY, "2100", True),
            ("2120", "Accrued Expenses", Account.Type.LIABILITY, "2100", False),

            # ===== EQUITY =====
            ("3000", "Equity", Account.Type.EQUITY, None, False),
            ("3100", "Owner Capital", Account.Type.EQUITY, "3000", False),
            ("3200", "Retained Earnings", Account.Type.EQUITY, "3000", False),

            # ===== REVENUE =====
            ("4000", "Revenue", Account.Type.REVENUE, None, False),
            ("4100", "Sales Revenue", Account.Type.REVENUE, "4000", False),
            ("4200", "Service Revenue", Account.Type.REVENUE, "4000", False),

            # ===== EXPENSES =====
            ("5000", "Expenses", Account.Type.EXPENSE, None, False),
            ("5100", "Cost of Goods Sold", Account.Type.EXPENSE, "5000", False),
            ("5200", "Salaries Expense", Account.Type.EXPENSE, "5000", False),
            ("5300", "Rent Expense", Account.Type.EXPENSE, "5000", False),
            ("5400", "Utilities Expense", Account.Type.EXPENSE, "5000", False),
            ("5500", "General & Admin Expense", Account.Type.EXPENSE, "5000", False),
        ]

        # أولاً: ننشئ كل الحسابات بدون parent (نخزّنها في dict)
        created_or_found = {}
        for code, name, acc_type, parent_code, allow_settlement in accounts_data:
            parent = None
            if parent_code:
                parent = created_or_found.get(parent_code) or Account.objects.filter(code=parent_code).first()

            obj, created = Account.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "type": acc_type,
                    "parent": parent,
                    "is_active": True,
                    "allow_settlement": allow_settlement,
                },
            )

            # لو موجود من قبل، نتأكد من تحديث بعض الحقول الأساسية (اختياري)
            if not created:
                updated = False
                if obj.name != name:
                    obj.name = name
                    updated = True
                if obj.type != acc_type:
                    obj.type = acc_type
                    updated = True
                if obj.parent != parent:
                    obj.parent = parent
                    updated = True
                if obj.allow_settlement != allow_settlement:
                    obj.allow_settlement = allow_settlement
                    updated = True
                if updated:
                    obj.save()

            created_or_found[code] = obj
            self.stdout.write(
                f"{'Created' if created else 'Exists '} account {code} - {name}"
            )

        self.stdout.write(self.style.SUCCESS("Basic chart of accounts seeded successfully."))
