from django.core.management.base import BaseCommand

from ledger.models import Journal


class Command(BaseCommand):
    help = "Seed default journals (General, Cash, Bank, Sales, Purchase)."

    def handle(self, *args, **options):
        data = [
            ("GEN", "دفتر عام", Journal.Type.GENERAL, True),
            ("CASH", "دفتر الكاش", Journal.Type.CASH, False),
            ("BANK", "دفتر البنك", Journal.Type.BANK, False),
            ("SALES", "دفتر المبيعات", Journal.Type.SALES, False),
            ("PUR", "دفتر المشتريات", Journal.Type.PURCHASE, False),
        ]

        created = 0
        updated = 0

        for code, name, type_, is_default in data:
            obj, was_created = Journal.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "type": type_,
                    "is_default": is_default,
                    "is_active": True,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded journals: {created} created, {updated} updated."
            )
        )
