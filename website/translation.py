# website/translation.py

from modeltranslation.translator import register, TranslationOptions
from .models import Category, Tag, BlogPost, Product


@register(Category)
class CategoryTR(TranslationOptions):
    fields = ("name",)


@register(Tag)
class TagTR(TranslationOptions):
    fields = ("name",)


@register(BlogPost)
class BlogPostTR(TranslationOptions):
    fields = (
        "title",
        "body",
        "meta_title",
        "meta_description",
    )


@register(Product)
class ProductTR(TranslationOptions):
    fields = (
        "name",
        "description",
    )
