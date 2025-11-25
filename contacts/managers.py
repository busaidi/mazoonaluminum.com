# contacts/managers.py
from django.db import models
from django.db.models import Q


class ContactQuerySet(models.QuerySet):
    """
    QuerySet مخصص لـ Contact:
    فلاتر جاهزة حسب الأدوار والحالة ونوع الكيان.
    """

    def active(self):
        return self.filter(is_active=True)

    def inactive(self):
        return self.filter(is_active=False)

    def customers(self):
        return self.filter(is_customer=True)

    def suppliers(self):
        return self.filter(is_supplier=True)

    def owners(self):
        return self.filter(is_owner=True)

    def employees(self):
        return self.filter(is_employee=True)

    def customers_or_suppliers(self):
        """
        كل من له علاقة مالية (زبون أو مورد).
        """
        return self.filter(Q(is_customer=True) | Q(is_supplier=True))

    def with_user(self):
        """
        الكونتاكتات المرتبطة بمستخدم (بوابة).
        """
        return self.exclude(user__isnull=True)

    def persons(self):
        # نستخدم القيمة النصية مباشرة لتفادي الـ circular import
        return self.filter(kind="person")

    def companies(self):
        return self.filter(kind="company")


class ContactManager(models.Manager):
    """
    المانجر الافتراضي لـ Contact المعتمد على ContactQuerySet.
    """

    def get_queryset(self):
        return ContactQuerySet(self.model, using=self._db)

    # نرجّع نفس الميثودات من الكويري ست
    def active(self):
        return self.get_queryset().active()

    def inactive(self):
        return self.get_queryset().inactive()

    def customers(self):
        return self.get_queryset().customers()

    def suppliers(self):
        return self.get_queryset().suppliers()

    def owners(self):
        return self.get_queryset().owners()

    def employees(self):
        return self.get_queryset().employees()

    def customers_or_suppliers(self):
        return self.get_queryset().customers_or_suppliers()

    def with_user(self):
        return self.get_queryset().with_user()

    def persons(self):
        return self.get_queryset().persons()

    def companies(self):
        return self.get_queryset().companies()
