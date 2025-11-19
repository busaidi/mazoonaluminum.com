from django.contrib import admin
from django.utils.html import format_html

from .models import BlogPost, Comment, Product, Category, Tag, ContactMessage


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name_ar", "slug")
    search_fields = ("name_ar", "name_en", "slug")
    prepopulated_fields = {"slug": ("name_ar",)}

@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name_ar", "slug")
    search_fields = ("name_ar", "name_en", "slug")
    prepopulated_fields = {"slug": ("name_ar",)}


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ("title_ar", "slug", "is_published", "published_at", "thumbnail_tag")
    list_filter = ("is_published", "published_at", "categories", "tags")
    search_fields = ("title_ar", "title_en", "body_ar", "body_en", "slug")
    prepopulated_fields = {"slug": ("title_ar",)}
    date_hierarchy = "published_at"
    filter_horizontal = ("categories", "tags")

    fieldsets = (
        ("العنوان والمحتوى", {
            "fields": (
                "title_ar", "title_en",
                "body_ar", "body_en",
                "slug", "categories", "tags",
                "thumbnail",
                "is_published", "published_at",
            )
        }),
        ("Meta SEO", {
            "fields": (
                "meta_title_ar", "meta_title_en",
                "meta_description_ar", "meta_description_en",
            ),
        }),
    )

    def thumbnail_tag(self, obj):
        if obj.thumbnail:
            return format_html(
                '<img src="{}" style="height:40px; border-radius:4px;" />',
                obj.thumbnail.url,
            )
        return "-"
    thumbnail_tag.short_description = "Thumbnail"



@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("post", "name", "email", "is_approved", "created_at")
    list_filter = ("is_approved", "created_at")
    search_fields = ("name", "email", "content")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name_ar", "slug", "price", "is_active", "image_tag")
    list_filter = ("is_active",)
    search_fields = ("name_ar", "name_en", "description_ar", "description_en")
    prepopulated_fields = {"slug": ("name_ar",)}

    def image_tag(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="height:40px; border-radius:4px;" />',
                obj.image.url,
            )
        return "-"

    image_tag.short_description = "Image"

@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "subject", "created_at")
    list_filter = ("created_at",)
    search_fields = ("name", "email", "subject", "message")
    readonly_fields = ("name", "email", "subject", "message", "created_at")

    fieldsets = (
        (None, {
            "fields": ("name", "email", "subject", "message")
        }),
        ("معلومات النظام", {
            "classes": ("collapse",),
            "fields": ("created_at",),
        }),
    )