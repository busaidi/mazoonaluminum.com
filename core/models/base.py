import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    """
    Adds created_at / updated_at fields.
    Use this for almost all models.
    """
    created_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
        verbose_name=_("تاريخ الإنشاء"),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("آخر تحديث"),
    )

    class Meta:
        abstract = True


class UserStampedModel(models.Model):
    """
    Adds created_by / updated_by fields.
    These are optional and can be filled in views/services.
    """
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_created",
        verbose_name=_("أنشئ بواسطة"),
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_updated",
        verbose_name=_("آخر تعديل بواسطة"),
    )

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """
    Soft delete support:
    - is_deleted: mark record as deleted without actually removing it
    - deleted_at / deleted_by: track who deleted and when
    """
    is_deleted = models.BooleanField(
        default=False,
        verbose_name=_("محذوف؟"),
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("تاريخ الحذف"),
    )
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_deleted",
        verbose_name=_("حُذف بواسطة"),
    )

    class Meta:
        abstract = True

    def soft_delete(self, user=None, save=True):
        """
        Mark the object as deleted without actually removing it from DB.
        Call this from services instead of obj.delete().
        """
        if not self.is_deleted:
            self.is_deleted = True
            self.deleted_at = timezone.now()
            if user is not None:
                self.deleted_by = user

            if save:
                self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])


class BaseModel(TimeStampedModel, UserStampedModel, SoftDeleteModel):
    """
    Base model for Mazoon ERP:

    - public_id (UUID) for internal usage, APIs, integrations
    - created_at / updated_at
    - created_by / updated_by
    - soft delete (is_deleted, deleted_at, deleted_by)

    Note:
    - We do NOT replace the default integer `id` field.
      This keeps existing models safe and migrations simple.
    """
    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        verbose_name=_("المعرّف العام (UUID)"),
    )

    class Meta:
        abstract = True
