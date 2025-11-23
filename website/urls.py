from django.urls import path
from .views import (
    HomeView,
    AboutView,
    LabView,
    BlogListView,
    BlogDetailView,
    BlogTagView,
    ProductListView,
    ProductDetailView,
    ContactView,
)


urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("about/", AboutView.as_view(), name="about"),
    path("lab/", LabView.as_view(), name="lab"),

    # BLOG
    path("blog/", BlogListView.as_view(), name="blog_list"),
    path("blog/category/<slug:category_slug>/", BlogListView.as_view(), name="blog_category"),
    path("blog/tag/<slug:tag_slug>/", BlogTagView.as_view(), name="blog_tag"),
    path("blog/<slug:slug>/", BlogDetailView.as_view(), name="blog_detail"),

    # PRODUCTS
    path("product/", ProductListView.as_view(), name="product_list"),
    path("product/<slug:slug>/", ProductDetailView.as_view(), name="product_detail"),

    # CONTACT
    path("contact/", ContactView.as_view(), name="contact"),
]
