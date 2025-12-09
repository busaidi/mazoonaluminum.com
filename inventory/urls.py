# inventory/urls.py

from django.urls import path
from . import views
from .models import StockMove  # ✅ Import Enums for type safety

app_name = "inventory"

urlpatterns = [
    # ==============================
    # 1. لوحة التحكم (Dashboard)
    # ==============================
    path("", views.DashboardView.as_view(), name="dashboard"),

    # ==============================
    # 2. العمليات (Operations)
    # ==============================
    # ✅ FIX: Using Enum constants instead of magic strings

    # استلام (Receipts) - IN
    path(
        "operations/receipts/",
        views.StockMoveListView.as_view(),
        {"move_type": StockMove.MoveType.IN},
        name="receipt_list"
    ),
    path(
        "operations/receipts/create/",
        views.StockMoveCreateView.as_view(),
        {"move_type": StockMove.MoveType.IN},
        name="receipt_create"
    ),

    # صرف (Deliveries) - OUT
    path(
        "operations/deliveries/",
        views.StockMoveListView.as_view(),
        {"move_type": StockMove.MoveType.OUT},
        name="delivery_list"
    ),
    path(
        "operations/deliveries/create/",
        views.StockMoveCreateView.as_view(),
        {"move_type": StockMove.MoveType.OUT},
        name="delivery_create"
    ),

    # تحويل (Transfers) - TRANSFER
    path(
        "operations/transfers/",
        views.StockMoveListView.as_view(),
        {"move_type": StockMove.MoveType.TRANSFER},
        name="transfer_list"
    ),
    path(
        "operations/transfers/create/",
        views.StockMoveCreateView.as_view(),
        {"move_type": StockMove.MoveType.TRANSFER},
        name="transfer_create"
    ),

    # تفاصيل وإجراءات الحركة
    path("operations/move/<int:pk>/", views.StockMoveDetailView.as_view(), name="move_detail"),
    path("operations/move/<int:pk>/confirm/", views.confirm_move_view, name="move_confirm"),
    path("operations/move/<int:pk>/cancel/", views.cancel_move_view, name="move_cancel"),

    # ==============================
    # 3. التقارير والمخزون (Reporting)
    # ==============================
    path("stock-levels/", views.StockLevelListView.as_view(), name="stock_level_list"),
    path("reorder-rules/", views.ReorderRuleListView.as_view(), name="reorder_rule_list"),

    # ==============================
    # 4. البيانات الأساسية (Master Data)
    # ==============================
    # Products
    path("products/", views.ProductListView.as_view(), name="product_list"),
    path("products/create/", views.ProductCreateView.as_view(), name="product_create"),
    path("products/<str:code>/", views.ProductDetailView.as_view(), name="product_detail"),
    path("products/<str:code>/edit/", views.ProductUpdateView.as_view(), name="product_update"),

    # Warehouses
    path("warehouses/", views.WarehouseListView.as_view(), name="warehouse_list"),
    path("warehouses/create/", views.WarehouseCreateView.as_view(), name="warehouse_create"),
    path("warehouses/<int:pk>/edit/", views.WarehouseUpdateView.as_view(), name="warehouse_update"),

# Categories
    path("categories/", views.ProductCategoryListView.as_view(), name="category_list"),
    path("categories/create/", views.ProductCategoryCreateView.as_view(), name="category_create"),
    path("categories/<int:pk>/edit/", views.ProductCategoryUpdateView.as_view(), name="category_update"),

    # Stock Locations
    path("locations/", views.StockLocationListView.as_view(), name="location_list"),
    path("locations/create/", views.StockLocationCreateView.as_view(), name="location_create"),
    path("locations/<int:pk>/edit/", views.StockLocationUpdateView.as_view(), name="location_update"),


    # Inventory Adjustments (الجرد)
    path("adjustments/", views.InventoryAdjustmentListView.as_view(), name="adjustment_list"),
    path("adjustments/start/", views.InventoryAdjustmentCreateView.as_view(), name="adjustment_create"),
    path("adjustments/<int:pk>/count/", views.InventoryAdjustmentUpdateView.as_view(), name="adjustment_count"),
    path("adjustments/<int:pk>/", views.InventoryAdjustmentDetailView.as_view(), name="adjustment_detail"),
    path("adjustments/<int:pk>/apply/", views.apply_adjustment_view, name="adjustment_apply"),
    # ...

    # ==============================
    # 5. الإعدادات (Settings)
    # ==============================
    path("settings/", views.InventorySettingsView.as_view(), name="settings"),
]