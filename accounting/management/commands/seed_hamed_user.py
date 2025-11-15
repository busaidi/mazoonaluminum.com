from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group


class Command(BaseCommand):
    help = "Create user 'hamed' with password 'hamd' and assign accounting_staff group."

    def handle(self, *args, **options):
        username = "hamed"
        password = "hamed"  # change if you want exactly 'حمد'

        # Create or get user
        user, created = User.objects.get_or_create(username=username)

        if created:
            user.set_password(password)
            user.is_active = True
            user.is_staff = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f"User '{username}' created."))
        else:
            self.stdout.write(self.style.WARNING(f"User '{username}' already exists. Updating password."))
            user.set_password(password)
            user.is_active = True
            user.is_staff = True
            user.save()

        # Assign group
        try:
            group = Group.objects.get(name="accounting_staff")
            user.groups.add(group)
            self.stdout.write(self.style.SUCCESS(f"User '{username}' added to 'accounting_staff' group."))
        except Group.DoesNotExist:
            self.stdout.write(self.style.ERROR("Group 'accounting_staff' does not exist. Run seed_accounting_staff_group first."))
