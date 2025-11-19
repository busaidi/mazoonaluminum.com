from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from accounting.models import Customer


class Command(BaseCommand):
    help = "Create customer 'agent' with linked user 'agent' and password 'agent'."

    def handle(self, *args, **options):
        username = "agent"
        password = "agent"
        customer_name = "agent"

        # Create or get the user
        user, created = User.objects.get_or_create(username=username)
        if created:
            user.set_password(password)
            user.is_active = True
            user.is_staff = False   # customer users are NOT staff
            user.save()
            self.stdout.write(self.style.SUCCESS("User 'agent' created."))
        else:
            self.stdout.write(self.style.WARNING("User 'agent' already exists. Updating password."))
            user.set_password(password)
            user.is_active = True
            user.is_staff = False
            user.save()

        # Create or get the customer entry
        customer, c_created = Customer.objects.get_or_create(
            name=customer_name,
            defaults={"user": user}
        )

        # If customer exists but user not matched, fix it
        if customer.user != user:
            customer.user = user
            customer.save()

        if c_created:
            self.stdout.write(self.style.SUCCESS("Customer 'agent' created and linked to user."))
        else:
            self.stdout.write(self.style.WARNING("Customer 'agent' already exists. Updated link."))

        self.stdout.write(self.style.SUCCESS("Done."))
