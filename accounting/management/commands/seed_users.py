from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group
from accounting.models import Customer


class Command(BaseCommand):
    help = "Seed default users: admin/admin, hamed/hamed (added to accounting_staff), agent/agent (with customer)."

    # -------------------------------------------------------
    # Ensure the accounting_staff group exists
    # -------------------------------------------------------
    def get_or_create_accounting_group(self):
        group, created = Group.objects.get_or_create(name="accounting_staff")
        if created:
            self.stdout.write(self.style.SUCCESS("Group 'accounting_staff' created."))
        else:
            self.stdout.write(self.style.WARNING("Group 'accounting_staff' already exists."))
        return group

    # -------------------------------------------------------
    # Create admin user
    # -------------------------------------------------------
    def create_admin(self):
        username = "admin"
        password = "admin"

        user, created = User.objects.get_or_create(username=username)

        user.set_password(password)
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS("Admin 'admin' created."))
        else:
            self.stdout.write(self.style.WARNING("Admin 'admin' exists. Password updated."))

    # -------------------------------------------------------
    # Create hamed user and add to group
    # -------------------------------------------------------
    def create_hamed(self, group):
        username = "hamed"
        password = "hamed"

        user, created = User.objects.get_or_create(username=username)

        user.set_password(password)
        user.is_active = True
        user.is_staff = True       # staff = True
        user.is_superuser = False  # not a superuser unless you want
        user.save()

        # Add to accounting_staff group
        user.groups.add(group)

        if created:
            self.stdout.write(self.style.SUCCESS("User 'hamed' created and added to accounting_staff."))
        else:
            self.stdout.write(self.style.WARNING("User 'hamed' exists. Password updated & ensured in group."))

    # -------------------------------------------------------
    # Create agent user + linked customer
    # -------------------------------------------------------
    def create_agent(self):
        username = "agent"
        password = "agent"
        customer_name = "agent"

        user, created = User.objects.get_or_create(username=username)

        user.set_password(password)
        user.is_active = True
        user.is_staff = False     # customer user
        user.is_superuser = False
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS("User 'agent' created."))
        else:
            self.stdout.write(self.style.WARNING("User 'agent' exists. Password updated."))

        # Create or update the linked customer
        customer, c_created = Customer.objects.get_or_create(
            name=customer_name,
            defaults={"user": user}
        )

        if customer.user != user:
            customer.user = user
            customer.save()

        if c_created:
            self.stdout.write(self.style.SUCCESS("Customer 'agent' created and linked."))
        else:
            self.stdout.write(self.style.WARNING("Customer 'agent' exists. Link updated."))

    # -------------------------------------------------------
    # Handle
    # -------------------------------------------------------
    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Seeding default users..."))

        # Ensure the accounting_staff group exists
        accounting_group = self.get_or_create_accounting_group()

        # Create users
        self.create_admin()
        self.create_hamed(accounting_group)
        self.create_agent()

        self.stdout.write(self.style.SUCCESS("Done!"))
