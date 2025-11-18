from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _

from ledger.models import Journal
from ledger.models import LedgerSettings


class Command(BaseCommand):
    help = "Seed default journals (General, Cash, Bank, Sales, Purchase, Opening, Closing) and link them to LedgerSettings."

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Seeding default journals..."))

        # تعريف الدفاتر الافتراضية
        journal_defs = [
            {
                "code": "GEN",
                "name": "دفتر عام",
                "type": Journal.Type.GENERAL,
                "is_default": True,
            },
            {
                "code": "CASH",
                "name": "دفتر الكاش",
                "type": Journal.Type.CASH,
                "is_default": False,
            },
            {
                "code": "BANK",
                "name": "دفتر البنك",
                "type": Journal.Type.BANK,
                "is_default": False,
            },
            {
                "code": "SALES",
                "name": "دفتر المبيعات",
                "type": Journal.Type.SALES,
                "is_default": False,
            },
            {
                "code": "PURCH",
                "name": "دفتر المشتريات",
                "type": Journal.Type.PURCHASE,
                "is_default": False,
            },
            {
                "code": "OPEN",
                "name": "دفتر الرصيد الافتتاحي",
                "type": Journal.Type.GENERAL,
                "is_default": False,
            },
            {
                "code": "CLOSE",
                "name": "دفتر إقفال السنة",
                "type": Journal.Type.GENERAL,
                "is_default": False,
            },
        ]

        journals_by_code = {}

        # إنشاء / تحديث الدفاتر
        for jd in journal_defs:
            code = jd["code"]
            name = jd["name"]
            jtype = jd["type"]
            is_default = jd["is_default"]

            journal, created = Journal.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "type": jtype,
                    "is_default": is_default,
                    "is_active": True,
                },
            )

            if not created:
                # تحديث الاسم والنوع والحالة
                journal.name = name
                journal.type = jtype
                journal.is_active = True
                # نخلي is_default نضبطه بعدين عشان ما نطفي غيرنا بالغلط
                journal.save()
                self.stdout.write(
                    self.style.WARNING(f"Journal '{code}' already exists. Updated basic fields.")
                )
            else:
                self.stdout.write(self.style.SUCCESS(f"Journal '{code}' created."))

            journals_by_code[code] = journal

        # ضبط الدفتر الافتراضي (is_default)
        # نخلي فقط GEN هو الافتراضي
        Journal.objects.update(is_default=False)
        gen = journals_by_code.get("GEN")
        if gen:
            gen.is_default = True
            gen.save()
            self.stdout.write(self.style.SUCCESS("Journal 'GEN' set as default manual journal."))

        # ربطها مع LedgerSettings
        self.stdout.write(self.style.WARNING("Linking journals to LedgerSettings..."))
        settings_obj = LedgerSettings.get_solo()

        def set_if_empty(field_name, journal_code):
            if not hasattr(settings_obj, field_name):
                return
            current = getattr(settings_obj, field_name)
            if current is None and journal_code in journals_by_code:
                setattr(settings_obj, field_name, journals_by_code[journal_code])

        set_if_empty("default_manual_journal", "GEN")
        set_if_empty("sales_journal", "SALES")
        set_if_empty("purchase_journal", "PURCH")
        set_if_empty("cash_journal", "CASH")
        set_if_empty("bank_journal", "BANK")
        set_if_empty("opening_balance_journal", "OPEN")
        set_if_empty("closing_journal", "CLOSE")

        settings_obj.save()
        self.stdout.write(self.style.SUCCESS("LedgerSettings updated."))

        self.stdout.write(self.style.SUCCESS("Done seeding journals."))
