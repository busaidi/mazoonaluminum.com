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
        جهات الاتصال المرتبطة بمستخدم (بوابة).
        """
        return self.exclude(user__isnull=True)

    def persons(self):
        # نستخدم القيمة النصية مباشرة لتفادي الـ circular import
        return self.filter(kind="person")

    def companies(self):
        return self.filter(kind="company")

    # --------- فلاتر متعلقة بالشركة ---------

    def with_company(self):
        """
        جهات اتصال مرتبطة بسجل شركة (company ليس null).
        مفيد عندما تريد الأشخاص التابعين للشركات.
        """
        return self.exclude(company__isnull=True)

    def without_company(self):
        """
        جهات اتصال لا تتبع شركة معينة (company is null).
        """
        return self.filter(company__isnull=True)

    def people_of_company(self, company):
        """
        كل الأشخاص (kind=person) الذين يتبعون شركة معيّنة.
        company يمكن أن يكون instance أو id.
        """
        company_id = getattr(company, "pk", company)
        return self.filter(kind="person", company_id=company_id)


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

    # فلاتر الشركة
    def with_company(self):
        return self.get_queryset().with_company()

    def without_company(self):
        return self.get_queryset().without_company()

    def people_of_company(self, company):
        return self.get_queryset().people_of_company(company)
