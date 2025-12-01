# core/managers.py
from django.db import models


class SoftDeleteQuerySet(models.QuerySet):
    """
    QuerySet يدعم:
    - .alive() أو .not_deleted(): لإرجاع غير المحذوفين
    - .dead() أو .deleted(): لإرجاع المحذوفين فقط
    """

    def alive(self):
        return self.filter(is_deleted=False)

    def not_deleted(self):
        return self.alive()

    def dead(self):
        return self.filter(is_deleted=True)

    def deleted(self):
        return self.dead()


class SoftDeleteManager(models.Manager):
    """
    Manager افتراضي يعرض كل السجلات
    Manager ثاني (active) يعرض فقط غير المحذوفين.
    """

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db)

    def alive(self):
        return self.get_queryset().alive()

    def not_deleted(self):
        return self.alive()

    def deleted(self):
        return self.get_queryset().deleted()


class ActiveObjectsManager(SoftDeleteManager):
    """
    Manager يعرض فقط غير المحذوفين.
    هذا اللي نستخدمه كـ .active
    """

    def get_queryset(self):
        return super().get_queryset().alive()
