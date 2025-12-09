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
    path("products/", views.ProductListView.as_view(), name="product_list"),
    path("products/<str:code>/", views.ProductDetailView.as_view(), name="product_detail"),

    path("warehouses/", views.WarehouseListView.as_view(), name="warehouse_list"),

    # ==============================
    # 5. الإعدادات (Settings)
    # ==============================
    path("settings/", views.InventorySettingsView.as_view(), name="settings"),
]