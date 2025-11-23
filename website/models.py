# مثلا: website/models.py

from django.db import models
from django.utils import timezone
from django.urls import reverse


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Category(TimeStampedModel):
    slug = models.SlugField(unique=True, max_length=100)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Tag(TimeStampedModel):
    slug = models.SlugField(unique=True, max_length=100)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class BlogPost(TimeStampedModel):
    slug = models.SlugField(unique=True, max_length=200)

    # الحقول المترجمة (سيتم توسيعها بـ modeltranslation)
    title = models.CharField(max_length=200)
    body = models.TextField()

    # --- SEO FIELDS (مترجمة أيضاً) ---
    meta_title = models.CharField(max_length=255, blank=True, null=True)
    meta_description = models.CharField(max_length=300, blank=True, null=True)
    # -----------------------------------

    # صورة رئيسية للتدوينة
    thumbnail = models.ImageField(
        upload_to="blog/",
        blank=True,
        null=True,
    )

    is_published = models.BooleanField(default=True)
    published_at = models.DateTimeField(default=timezone.now)

    categories = models.ManyToManyField(
        Category,
        related_name="posts",
        blank=True,
    )

    tags = models.ManyToManyField(
        Tag,
        related_name="posts",
        blank=True,
    )

    class Meta:
        ordering = ("-published_at", "-id")

    def __str__(self):
        return self.title or self.slug

    def get_absolute_url(self):
        return reverse("blog_detail", kwargs={"slug": self.slug})


class Comment(TimeStampedModel):
    post = models.ForeignKey(
        BlogPost,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)
    content = models.TextField()
    is_approved = models.BooleanField(default=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"Comment by {self.name} on {self.post}"


class Product(TimeStampedModel):
    slug = models.SlugField(unique=True, max_length=200)

    # مترجم
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)

    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    image = models.ImageField(
        upload_to="products/",
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("product_detail", kwargs={"slug": self.slug})


class ContactMessage(models.Model):
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    subject = models.CharField(max_length=200, blank=True)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} - {self.subject or 'Contact message'}"
