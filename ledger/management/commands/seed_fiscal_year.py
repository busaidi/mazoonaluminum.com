# ledger/management/commands/seed_fiscal_year.py
from datetime import date

from django.core.management.base import BaseCommand
from django.utils.translation import gettext as _

from ledger.models import FiscalYear


class Command(BaseCommand):
    """Seed a default fiscal year for the current year."""

    help = _("إنشاء سنة مالية افتراضية للسنة الحالية في نظام دفتر الأستاذ.")

    def handle(self, *args, **options):
        year = date.today().year
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)

        fy, created = FiscalYear.objects.get_or_create(
            year=year,
            defaults={
                "date_from": start_date,
                "date_to": end_date,
                "is_closed": False,
            },
        )

        if created:
            msg = _("تم إنشاء السنة المالية %(year)s بنجاح.") % {"year": year}
            self.stdout.write(self.style.SUCCESS(msg))
        else:
            msg = _("السنة المالية %(year)s موجودة مسبقًا.") % {"year": year}
            self.stdout.write(self.style.WARNING(msg))
