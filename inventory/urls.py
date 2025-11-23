# inventory/urls.py

from django.urls import path

from . import views
from .views import InventorySettingsView

app_name = "inventory"

urlpatterns = [
    # ------------------------
    # Dashboard
    # ------------------------
    path(
        "",
        views.InventoryDashboardView.as_view(),
        name="dashboard",
    ),

    # ------------------------
    # Product categories
    # ------------------------
    path(
        "categories/",
        views.ProductCategoryListView.as_view(),
        name="category_list",
    ),
    path(
        "categories/new/",
        views.ProductCategoryCreateView.as_view(),
        name="category_create",
    ),
    path(
        "categories/<int:pk>/edit/",
        views.ProductCategoryUpdateView.as_view(),
        name="category_update",
    ),

    # ------------------------
    # Products
    # ------------------------
    path(
        "products/",
        views.ProductListView.as_view(),
        name="product_list",
    ),
    path(
        "products/new/",
        views.ProductCreateView.as_view(),
        name="product_create",
    ),
    path(
        "products/<int:pk>/",
        views.ProductDetailView.as_view(),
        name="product_detail",
    ),
    path(
        "products/<int:pk>/edit/",
        views.ProductUpdateView.as_view(),
        name="product_update",
    ),

    # ------------------------
    # Warehouses
    # ------------------------
    path(
        "warehouses/",
        views.WarehouseListView.as_view(),
        name="warehouse_list",
    ),
    path(
        "warehouses/new/",
        views.WarehouseCreateView.as_view(),
        name="warehouse_create",
    ),
    path(
        "warehouses/<int:pk>/edit/",
        views.WarehouseUpdateView.as_view(),
        name="warehouse_update",
    ),

    # ------------------------
    # Stock locations
    # ------------------------
    path(
        "locations/",
        views.StockLocationListView.as_view(),
        name="location_list",
    ),
    path(
        "locations/new/",
        views.StockLocationCreateView.as_view(),
        name="location_create",
    ),
    path(
        "locations/<int:pk>/edit/",
        views.StockLocationUpdateView.as_view(),
        name="location_update",
    ),

    # ------------------------
    # Stock moves
    # ------------------------
    path(
        "moves/",
        views.StockMoveListView.as_view(),
        name="move_list",
    ),
    path(
        "moves/new/",
        views.StockMoveCreateView.as_view(),
        name="move_create",
    ),
    path(
        "moves/<int:pk>/",
        views.StockMoveDetailView.as_view(),
        name="move_detail",
    ),
    path(
        "moves/<int:pk>/edit/",
        views.StockMoveUpdateView.as_view(),
        name="move_update",
    ),

    # ------------------------
    # Stock levels (read-only)
    # ------------------------
    # Stock Levels
    path(
        "stock-levels/",
        views.StockLevelListView.as_view(),
        name="stocklevel_list",
    ),
    path(
        "stock-levels/create/",
        views.StockLevelCreateView.as_view(),
        name="stocklevel_create",
    ),
    path(
        "stock-levels/<int:pk>/",
        views.StockLevelDetailView.as_view(),
        name="stocklevel_detail",
    ),
    path(
        "stock-levels/<int:pk>/edit/",
        views.StockLevelUpdateView.as_view(),
        name="stocklevel_update",
    ),


    #setting
    path("settings/", InventorySettingsView.as_view(), name="settings"),
]
