from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission


class Command(BaseCommand):
    help = "Create or update 'accounting_staff' group with accounting permissions."

    def handle(self, *args, **options):
        # Create group (or get existing)
        group, created = Group.objects.get_or_create(name="accounting_staff")

        # Get all permissions for the 'accounting' app
        # Here we include add/change/view and exclude delete_*
        perms = Permission.objects.filter(
            content_type__app_label="accounting"
        ).exclude(codename__startswith="delete_")

        # Attach permissions to the group
        for perm in perms:
            group.permissions.add(perm)

        group.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"'accounting_staff' group ready. Permissions count: {perms.count()}."
            )
        )
