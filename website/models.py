from django.db import models
from django.utils import timezone
from django.utils.translation import get_language
from django.urls import reverse


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Category(TimeStampedModel):
    slug = models.SlugField(unique=True, max_length=100)

    name_ar = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        ordering = ("name_ar",)

    def __str__(self):
        return self.name_ar

    @property
    def name(self):
        lang = get_language() or "ar"
        if lang.startswith("en") and self.name_en:
            return self.name_en
        return self.name_ar


class Tag(TimeStampedModel):
    slug = models.SlugField(unique=True, max_length=100)

    name_ar = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        ordering = ("name_ar",)

    def __str__(self):
        return self.name_ar

    @property
    def name(self):
        lang = get_language() or "ar"
        if lang.startswith("en") and self.name_en:
            return self.name_en
        return self.name_ar


class BlogPost(TimeStampedModel):
    slug = models.SlugField(unique=True, max_length=200)

    title_ar = models.CharField(max_length=200)
    title_en = models.CharField(max_length=200, blank=True, null=True)

    body_ar = models.TextField()
    body_en = models.TextField(blank=True, null=True)

    # --- SEO FIELDS ---
    meta_title_ar = models.CharField(max_length=255, blank=True, null=True)
    meta_title_en = models.CharField(max_length=255, blank=True, null=True)

    meta_description_ar = models.CharField(max_length=300, blank=True, null=True)
    meta_description_en = models.CharField(max_length=300, blank=True, null=True)
    # -------------------

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
        return self.title_ar or self.slug

    @property
    def title(self):
        lang = get_language() or "ar"
        if lang.startswith("en") and self.title_en:
            return self.title_en
        return self.title_ar

    @property
    def meta_title(self):
        lang = get_language() or "ar"
        if lang.startswith("en") and self.meta_title_en:
            return self.meta_title_en
        return self.meta_title_ar or self.title

    @property
    def meta_description(self):
        lang = get_language() or "ar"
        if lang.startswith("en") and self.meta_description_en:
            return self.meta_description_en
        # fallback: من العربي أو من الجسم
        desc = self.meta_description_ar or self.body_ar[:250]
        return desc

    @property
    def body(self):
        lang = get_language() or "ar"
        if lang.startswith("en") and self.body_en:
            return self.body_en
        return self.body_ar


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

    name_ar = models.CharField(max_length=200)
    name_en = models.CharField(max_length=200, blank=True, null=True)

    description_ar = models.TextField(blank=True, null=True)
    description_en = models.TextField(blank=True, null=True)

    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    # 👇 الجديد:
    image = models.ImageField(
        upload_to="products/",
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ("name_ar",)

    def __str__(self):
        return self.name_ar

    @property
    def name(self):
        lang = get_language() or "ar"
        if lang.startswith("en") and self.name_en:
            return self.name_en
        return self.name_ar

    @property
    def description(self):
        lang = get_language() or "ar"
        if lang.startswith("en") and self.description_en:
            return self.description_en or ""
        return self.description_ar or ""

    def get_absolute_url(self):
        return reverse("product_detail", kwargs={"slug": self.slug})
