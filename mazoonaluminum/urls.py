from django.contrib import admin
from django.urls import path, include
from django.conf.urls.i18n import i18n_patterns
from django.views.i18n import set_language
from django.conf import settings
from django.conf.urls.static import static

from django.contrib.sitemaps.views import sitemap
from website.views import robots_txt
from website.sitemaps import (
    StaticEnglishSitemap, StaticArabicSitemap,
    BlogPostEnglishSitemap, BlogPostArabicSitemap,
    ProductEnglishSitemap, ProductArabicSitemap,
)

sitemaps = {
    "static_en": StaticEnglishSitemap,
    "static_ar": StaticArabicSitemap,
    "blogs_en": BlogPostEnglishSitemap,
    "blogs_ar": BlogPostArabicSitemap,
    "products_en": ProductEnglishSitemap,
    "products_ar": ProductArabicSitemap,
}

urlpatterns = [
    path("i18n/setlang/", set_language, name="set_language"),
    path("robots.txt", robots_txt, name="robots_txt"),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
]

urlpatterns += i18n_patterns(
    path("admin/", admin.site.urls),
    path("", include("website.urls")),
    path("accounting/", include("accounting.urls")),
    path("", include("core.urls", namespace="core")),
    path("ledger/", include("ledger.urls", namespace="ledger")),
    path("portal/", include("portal.urls")),
    path("cart/", include("cart.urls", namespace="cart")),
    path("accounts/", include("django.contrib.auth.urls")),

)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
