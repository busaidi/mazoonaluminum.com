# accounting/management/commands/seed_accounts_oman.py

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounting.models import (
    Account,
    LedgerSettings,
    Journal,
    JournalEntry,
    DECIMAL_ZERO,
)


class Command(BaseCommand):
    """
    Seed عماني لشجرة الحسابات مع VAT 5%
    + إنشاء قيد رصيد افتتاحي واحد حسب الأعمدة opening_debit/opening_credit.
    """

    help = "Seed Oman chart of accounts with 5% VAT and create opening balance entry."

    @transaction.atomic
    def handle(self, *args, **options):
        # ==========================================================
        # 1) بيانات شجرة الحسابات (من الجدول الذي أرسلته بالضبط)
        # ==========================================================
        rows = [
            # code, name,            type,      parent_code, allow_settlement, is_active, opening_debit, opening_credit
            ("1000", "الأصول", "asset", None, 0, 1, None, None),
            ("1100", "الأصول المتداولة", "asset", "1000", 0, 1, None, None),
            ("1110", "النقد وما في حكمه", "asset", "1100", 0, 1, None, None),
            ("1111", "الصندوق", "asset", "1110", 0, 1, "500", None),
            ("1112", "البنك - حساب جاري", "asset", "1110", 0, 1, None, None),
            ("1120", "الذمم المدينة - العملاء", "asset", "1100", 1, 1, "2500", None),
            ("1125", "ضريبة القيمة المضافة المدفوعة (مدخلات الضريبة)", "asset", "1100", 1, 1, None, None),
            ("1130", "مصروفات مدفوعة مقدماً", "asset", "1100", 0, 1, None, None),
            ("1200", "المخزون", "asset", "1000", 0, 1, None, None),
            ("1210", "مخزون مواد خام", "asset", "1200", 0, 1, None, None),
            ("1220", "مخزون منتجات تامة", "asset", "1200", 0, 1, None, None),
            ("1300", "الأصول غير المتداولة", "asset", "1000", 0, 1, None, None),
            ("1310", "الممتلكات والمنشآت والمعدات", "asset", "1300", 0, 1, None, None),
            ("1320", "مجمع الإهلاك", "asset", "1300", 0, 1, None, None),

            ("2000", "الالتزامات", "liability", None, 0, 1, None, None),
            ("2100", "الالتزامات المتداولة", "liability", "2000", 0, 1, None, None),
            ("2110", "الذمم الدائنة - الموردون", "liability", "2100", 1, 1, None, "1200"),
            ("2120", "مصروفات مستحقة", "liability", "2100", 0, 1, None, None),
            ("2130", "ضريبة القيمة المضافة المستحقة (مخرجات الضريبة)", "liability", "2100", 1, 1, None, None),
            ("2140", "حساب تسوية ضريبة القيمة المضافة", "liability", "2100", 0, 1, None, None),
            ("2200", "الالتزامات غير المتداولة", "liability", "2000", 0, 1, None, None),
            ("2210", "قروض طويلة الأجل", "liability", "2200", 0, 1, None, None),

            ("3000", "حقوق الملكية", "equity", None, 0, 1, None, None),
            ("3100", "رأس المال", "equity", "3000", 0, 1, None, "1800"),
            ("3200", "الأرباح المحتجزة", "equity", "3000", 0, 1, None, None),
            ("3300", "مسحوبات المالك", "equity", "3000", 0, 1, None, None),

            ("4000", "الإيرادات", "revenue", None, 0, 1, None, None),
            ("4100", "مبيعات خاضعة للضريبة 5٪ (محلية)", "revenue", "4000", 0, 1, None, None),
            ("4110", "مبيعات خاضعة للضريبة 0٪ / صادرات", "revenue", "4000", 0, 1, None, None),
            ("4120", "مردودات وخصومات المبيعات", "revenue", "4000", 0, 1, None, None),
            ("4200", "إيرادات تشغيلية أخرى", "revenue", "4000", 0, 1, None, None),
            ("4300", "إيرادات أخرى", "revenue", "4000", 0, 1, None, None),

            ("5000", "تكلفة المبيعات", "expense", None, 0, 1, None, None),
            ("5100", "تكلفة البضائع المباعة", "expense", "5000", 0, 1, None, None),

            ("6000", "مصروفات تشغيلية", "expense", None, 0, 1, None, None),
            ("6100", "رواتب وأجور", "expense", "6000", 0, 1, None, None),
            ("6110", "مزايا الموظفين", "expense", "6000", 0, 1, None, None),
            ("6200", "إيجار", "expense", "6000", 0, 1, None, None),
            ("6210", "مرافق (كهرباء وماء)", "expense", "6000", 0, 1, None, None),
            ("6220", "اتصالات وإنترنت", "expense", "6000", 0, 1, None, None),
            ("6230", "مصروفات سيارات ونقل", "expense", "6000", 0, 1, None, None),
            ("6240", "مصروف إهلاك", "expense", "6000", 0, 1, None, None),
            ("6250", "عمولات ومصاريف بنكية", "expense", "6000", 0, 1, None, None),
            ("6260", "أتعاب مهنية واستشارية", "expense", "6000", 0, 1, None, None),
            ("6270", "تسويق وإعلان", "expense", "6000", 0, 1, None, None),
            ("6280", "مصروفات أخرى", "expense", "6000", 0, 1, None, None),
        ]

        # خريطة من الكود إلى كائن الحساب
        code_to_account = {}

        # ==========================================================
        # 2) إنشاء/تحديث الحسابات (idempotent)
        # ==========================================================
        for code, name, acc_type, parent_code, allow_settlement, is_active, op_debit, op_credit in rows:
            parent = None
            if parent_code:
                parent = code_to_account.get(parent_code) or Account.objects.filter(code=parent_code).first()

            obj, created = Account.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "type": acc_type,
                    "parent": parent,
                    "allow_settlement": bool(allow_settlement),
                    "is_active": bool(is_active),
                },
            )
            if not created:
                obj.name = name
                obj.type = acc_type
                obj.parent = parent
                obj.allow_settlement = bool(allow_settlement)
                obj.is_active = bool(is_active)
                obj.save(update_fields=["name", "type", "parent", "allow_settlement", "is_active"])
                self.stdout.write(self.style.WARNING(f"Updated account {code} - {name}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"Created account {code} - {name}"))

            code_to_account[code] = obj

        # ==========================================================
        # 3) تحديث LedgerSettings لأهم حسابات المبيعات والضريبة
        # ==========================================================
        ledger_settings = LedgerSettings.get_solo()
        ledger_settings.sales_receivable_account = code_to_account.get("1120")   # عملاء
        ledger_settings.sales_revenue_0_account = code_to_account.get("4100")   # مبيعات 5%
        ledger_settings.sales_vat_output_account = code_to_account.get("2130")  # ضريبة مستحقة 5%
        # حالياً ما عندنا حساب مستقل للدفعات المقدمة من العملاء، نخليه فاضي
        ledger_settings.save()
        self.stdout.write(self.style.SUCCESS("LedgerSettings updated."))

        # ==========================================================
        # 4) إنشاء دفتر رصيد افتتاحي + قيد رصيد افتتاحي (اختياري)
        # ==========================================================
        opening_journal, _ = Journal.objects.get_or_create(
            code="OPEN",
            defaults={
                "name": "دفتر أرصدة افتتاحية",
                "type": Journal.Type.GENERAL,
                "is_active": True,
            },
        )
        # نربطه في الإعدادات كدفتر رصيد افتتاحي
        ledger_settings.opening_balance_journal = opening_journal
        ledger_settings.save(update_fields=["opening_balance_journal"])

        # إذا كان موجود قيد سابق بنفس المرجع نستخدمه/نحدثه، حتى يكون idempotent
        entry, created_entry = JournalEntry.objects.get_or_create(
            journal=opening_journal,
            reference="OPENING_BALANCE_OMAN",
            defaults={
                "date": timezone.now().date(),
                "description": "قيد رصيد افتتاحي وفق شجرة الحسابات العمانية (VAT 5%)",
            },
        )
        if not created_entry:
            # نمسح السطور ونعيد تكوينها حسب الإكسل
            entry.lines.all().delete()
            self.stdout.write(self.style.WARNING("Existing opening balance entry found, lines will be recreated."))

        total_debit = DECIMAL_ZERO
        total_credit = DECIMAL_ZERO

        for code, name, acc_type, parent_code, allow_settlement, is_active, op_debit, op_credit in rows:
            if not op_debit and not op_credit:
                continue

            account = code_to_account[code]
            debit = Decimal(op_debit) if op_debit else DECIMAL_ZERO
            credit = Decimal(op_credit) if op_credit else DECIMAL_ZERO

            entry.lines.create(
                account=account,
                description="رصيد افتتاحي",
                debit=debit,
                credit=credit,
                order=0,
            )

            total_debit += debit
            total_credit += credit

        self.stdout.write(self.style.SUCCESS(
            f"Opening balance entry created with total debit={total_debit} / total credit={total_credit}"
        ))
        self.stdout.write(self.style.SUCCESS("Done seeding Oman accounts with opening balances."))
