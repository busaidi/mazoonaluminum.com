from django.contrib.sitemaps import Sitemap
from .models import BlogPost, Product


# -------- صفحات ثابتة: إنجليزي --------
class StaticEnglishSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7

    def items(self):
        # هذه أسماء الـ URL patterns (name=...) في website/urls.py
        return ["home", "about", "lab", "blog_list", "product_list", "contact"]

    def location(self, item):
        paths = {
            "home": "/en/",
            "about": "/en/about/",
            "lab": "/en/lab/",
            "blog_list": "/en/blog/",
            "product_list": "/en/products/",
            "contact": "/en/contact/",
        }
        return paths[item]


# -------- صفحات ثابتة: عربي --------
class StaticArabicSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7

    def items(self):
        return ["home", "about", "lab", "blog_list", "product_list", "contact"]

    def location(self, item):
        paths = {
            "home": "/ar/",
            "about": "/ar/about/",
            "lab": "/ar/lab/",
            "blog_list": "/ar/blog/",
            "product_list": "/ar/products/",
            "contact": "/ar/contact/",
        }
        return paths[item]


# -------- التدوينات: إنجليزي --------
class BlogPostEnglishSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return BlogPost.objects.all()

    def location(self, obj):
        return f"/en/blog/{obj.slug}/"

    def lastmod(self, obj):
        return obj.updated_at


# -------- التدوينات: عربي --------
class BlogPostArabicSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return BlogPost.objects.all()

    def location(self, obj):
        return f"/ar/blog/{obj.slug}/"

    def lastmod(self, obj):
        return obj.updated_at


# -------- المنتجات: إنجليزي --------
class ProductEnglishSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7

    def items(self):
        return Product.objects.filter(is_active=True)

    def location(self, obj):
        return f"/en/products/{obj.slug}/"

    def lastmod(self, obj):
        return obj.updated_at


# -------- المنتجات: عربي --------
class ProductArabicSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7

    def items(self):
        return Product.objects.filter(is_active=True)

    def location(self, obj):
        return f"/ar/products/{obj.slug}/"

    def lastmod(self, obj):
        return obj.updated_at
