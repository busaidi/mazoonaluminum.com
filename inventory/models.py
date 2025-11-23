# products/models.py

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.urls import reverse
from django.utils import timezone
from modeltranslation.translator import TranslationOptions, register


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Product(TimeStampedModel):
    slug = models.SlugField(unique=True, max_length=200)

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)

    # ممكن تضيف:
    sku = models.CharField(
        max_length=100,
        unique=True,
        verbose_name=_("SKU"),
    )

    default_price = models.DecimalField(max_digits=12, decimal_places=3, default=0)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        # ممكن تخليها لمسار كتالوج المنتجات
        return reverse("products:detail", kwargs={"slug": self.slug})
