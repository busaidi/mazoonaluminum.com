from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("lab/", views.lab, name="lab"),



    path("blog/", views.blog_list, name="blog_list"),
    path("blog/category/<slug:category_slug>/", views.blog_list, name="blog_category"),
    path("blog/tag/<slug:tag_slug>/", views.blog_tag, name="blog_tag"),
    path("blog/<slug:slug>/", views.blog_detail, name="blog_detail"),
    path("products/", views.product_list, name="product_list"),
    path("products/<slug:slug>/", views.product_detail, name="product_detail"),
    path("contact/", views.contact, name="contact"),
]
