# uom/urls.py

from django.urls import path
from . import views

app_name = "uom"

urlpatterns = [
    # Categories
    path("categories/", views.UomCategoryListView.as_view(), name="category_list"),
    path("categories/create/", views.UomCategoryCreateView.as_view(), name="category_create"),
    path("categories/<int:pk>/edit/", views.UomCategoryUpdateView.as_view(), name="category_update"),

    # Units
    path("units/", views.UnitListView.as_view(), name="unit_list"),
    path("units/create/", views.UnitCreateView.as_view(), name="unit_create"),
    path("units/<int:pk>/edit/", views.UnitUpdateView.as_view(), name="unit_update"),
]