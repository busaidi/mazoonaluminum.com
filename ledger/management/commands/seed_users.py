from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = "Seed accounting users (Accountant & Finance Manager)"

    def handle(self, *args, **options):

        # Accountant user
        accountant, created = User.objects.get_or_create(
            username="accountant",
            defaults={
                "first_name": "Accountant",
                "is_staff": True,
            }
        )
        if created:
            accountant.set_password("123456")
            accountant.save()

        # Finance Manager user
        manager, created = User.objects.get_or_create(
            username="finance_manager",
            defaults={
                "first_name": "Finance Manager",
                "is_staff": True,
                "is_superuser": True,
            }
        )
        if created:
            manager.set_password("123456")
            manager.save()

        self.stdout.write(self.style.SUCCESS("Users seeded successfully."))
