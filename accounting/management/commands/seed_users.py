from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group

from contacts.models import Contact


class Command(BaseCommand):
    help = (
        "Seed default users:\n"
        "- admin/admin (superuser)\n"
        "- hamed/hamed (staff in accounting_staff)\n"
        "- agent/agent (customer user with translated Oman profile)"
    )

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
        user.is_superuser = False  # not a superuser
        user.first_name = "Hamed"
        user.last_name = "Al Busaidi"
        user.save()

        # Add to accounting_staff group
        user.groups.add(group)

        if created:
            self.stdout.write(
                self.style.SUCCESS("User 'hamed' created and added to accounting_staff.")
            )
        else:
            self.stdout.write(
                self.style.WARNING("User 'hamed' exists. Password updated & ensured in group.")
            )

    # -------------------------------------------------------
    # Create agent user + linked translated customer
    # -------------------------------------------------------
    def create_agent(self):
        username = "agent"
        password = "agent"

        # بيانات وهمية عمانية
        full_name_en = "Ahmed Saif Al Busaidi"
        full_name_ar = "أحمد سيف البوسعيدي"

        company_name_en = "Mazoon Modern Trading"
        company_name_ar = "مزون للتجارة الحديثة"

        address_en = "Villa 12, Al Khoudh 6, Seeb, Muscat, Oman"
        address_ar = "فيلا ١٢، الخوض ٦، ولاية السيب، محافظة مسقط، سلطنة عمان"

        country_en = "Oman"
        country_ar = "سلطنة عمان"

        governorate_en = "Muscat"
        governorate_ar = "محافظة مسقط"

        wilaya_en = "Seeb"
        wilaya_ar = "ولاية السيب"

        village_en = "Al Khoudh 6"
        village_ar = "الخوض ٦"

        postal_code_en = "123"
        postal_code_ar = "١٢٣"

        po_box_en = "256"
        po_box_ar = "٢٥٦"

        phone = "+96892123456"
        email = "agent@example.com"
        tax_number = "OM123456789"

        # إنشاء / تحديث المستخدم
        user, created = User.objects.get_or_create(username=username)

        user.set_password(password)
        user.is_active = True
        user.is_staff = False     # customer user
        user.is_superuser = False
        user.first_name = "Ahmed Saif"
        user.last_name = "Al Busaidi"
        user.email = email
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS("User 'agent' created."))
        else:
            self.stdout.write(self.style.WARNING("User 'agent' exists. Password updated."))

        # إنشاء أو تحديث العميل المرتبط
        # نستخدم user كمفتاح أساسي للربط
        customer, c_created = Contact.objects.get_or_create(
            user=user,
            defaults={
                # الحقول المترجمة (modeltranslation)
                "name_ar": full_name_ar,
                "name_en": full_name_en,
                "company_name_ar": company_name_ar,
                "company_name_en": company_name_en,
                "address_ar": address_ar,
                "address_en": address_en,
                "country_ar": country_ar,
                "country_en": country_en,
                "governorate_ar": governorate_ar,
                "governorate_en": governorate_en,
                "wilaya_ar": wilaya_ar,
                "wilaya_en": wilaya_en,
                "village_ar": village_ar,
                "village_en": village_en,
                "postal_code_ar": postal_code_ar,
                "postal_code_en": postal_code_en,
                "po_box_ar": po_box_ar,
                "po_box_en": po_box_en,

                # الحقول غير المترجمة
                "phone": phone,
                "email": email,
                "tax_number": tax_number,
            },
        )

        # إذا كان العميل موجود من قبل، نحدّث بياناته عشان تتوافق مع الفورم الجديد
        updated = False
        if not c_created:
            # تأكد أن المستخدم مربوط
            if customer.user != user:
                customer.user = user
                updated = True

            # نحدّث البيانات المترجمة / غير المترجمة
            for field, value in {
                "name_ar": full_name_ar,
                "name_en": full_name_en,
                "company_name_ar": company_name_ar,
                "company_name_en": company_name_en,
                "address_ar": address_ar,
                "address_en": address_en,
                "country_ar": country_ar,
                "country_en": country_en,
                "governorate_ar": governorate_ar,
                "governorate_en": governorate_en,
                "wilaya_ar": wilaya_ar,
                "wilaya_en": wilaya_en,
                "village_ar": village_ar,
                "village_en": village_en,
                "postal_code_ar": postal_code_ar,
                "postal_code_en": postal_code_en,
                "po_box_ar": po_box_ar,
                "po_box_en": po_box_en,
                "phone": phone,
                "email": email,
                "tax_number": tax_number,
            }.items():
                if getattr(customer, field, None) != value:
                    setattr(customer, field, value)
                    updated = True

            if updated:
                customer.save()
                self.stdout.write(
                    self.style.WARNING(
                        "Customer for 'agent' existed. Data updated to match translated form."
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "Customer for 'agent' existed. No field changes were necessary."
                    )
                )
        else:
            self.stdout.write(
                self.style.SUCCESS("Customer for 'agent' created with translated Oman profile.")
            )

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
