import uuid
from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model

User = get_user_model()


class TimeStampedModel(models.Model):
    """
    Adds created_at / updated_at fields.
    """
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UserStampedModel(models.Model):
    """
    Adds created_by / updated_by fields.
    These are optional and can be filled in views.
    """
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_created",
    )
    updated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_updated",
    )

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """
    Soft delete support:
    - is_deleted: mark record as deleted without actually removing it
    - deleted_at / deleted_by: track who deleted and when
    """
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_deleted",
    )

    class Meta:
        abstract = True

    def soft_delete(self, user=None):
        """
        Mark the object as deleted without actually removing it from DB.
        """
        if not self.is_deleted:
            self.is_deleted = True
            self.deleted_at = timezone.now()
            if user is not None:
                self.deleted_by = user
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
        verbose_name="Public ID",
    )

    class Meta:
        abstract = True
