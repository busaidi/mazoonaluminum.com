# inventory/urls.py

from django.urls import path
from . import views
from .models import StockMove

app_name = "inventory"

urlpatterns = [
    # Dashboard
    path("", views.DashboardView.as_view(), name="dashboard"),

    # Settings
    path("settings/", views.InventorySettingsView.as_view(), name="settings"),

    # ==========================
    # Operations (Stock Moves)
    # ==========================
    path("moves/in/", views.StockMoveListView.as_view(), {"move_type": StockMove.MoveType.IN}, name="receipt_list"),
    path("moves/in/create/", views.StockMoveCreateView.as_view(), {"move_type": StockMove.MoveType.IN},
         name="receipt_create"),

    path("moves/out/", views.StockMoveListView.as_view(), {"move_type": StockMove.MoveType.OUT}, name="delivery_list"),
    path("moves/out/create/", views.StockMoveCreateView.as_view(), {"move_type": StockMove.MoveType.OUT},
         name="delivery_create"),

    path("moves/transfer/", views.StockMoveListView.as_view(), {"move_type": StockMove.MoveType.TRANSFER},
         name="transfer_list"),
    path("moves/transfer/create/", views.StockMoveCreateView.as_view(), {"move_type": StockMove.MoveType.TRANSFER},
         name="transfer_create"),

    # Move Details & Actions
    path("moves/<int:pk>/", views.StockMoveDetailView.as_view(), name="move_detail"),
    path("moves/<int:pk>/confirm/", views.confirm_move_view, name="move_confirm"),
    path("moves/<int:pk>/cancel/", views.cancel_move_view, name="move_cancel"),
    path("moves/<int:pk>/pdf/", views.stock_move_pdf_view, name="move_pdf"),

    # ==========================
    # Inventory Adjustments (Stock Taking)
    # ==========================
    path("adjustments/", views.InventoryAdjustmentListView.as_view(), name="adjustment_list"),
    path("adjustments/create/", views.InventoryAdjustmentCreateView.as_view(), name="adjustment_create"),
    path("adjustments/<int:pk>/", views.InventoryAdjustmentDetailView.as_view(), name="adjustment_detail"),
    path("adjustments/<int:pk>/count/", views.InventoryAdjustmentUpdateView.as_view(), name="adjustment_count"),
    path("adjustments/<int:pk>/apply/", views.apply_adjustment_view, name="adjustment_apply"),

    # ==========================
    # Master Data
    # ==========================
    # Products
    path("products/", views.ProductListView.as_view(), name="product_list"),
    path("products/create/", views.ProductCreateView.as_view(), name="product_create"),
    path("products/import/", views.import_products_view, name="product_import"),
    path("products/export/", views.export_products_view, name="product_export"),
    path("products/<str:code>/", views.ProductDetailView.as_view(), name="product_detail"),
    path("products/<str:code>/edit/", views.ProductUpdateView.as_view(), name="product_edit"),
    path("products/<str:code>/delete/", views.ProductDeleteView.as_view(), name="product_delete"),

    # Warehouses
    path("warehouses/", views.WarehouseListView.as_view(), name="warehouse_list"),
    path("warehouses/create/", views.WarehouseCreateView.as_view(), name="warehouse_create"),
    path("warehouses/<int:pk>/edit/", views.WarehouseUpdateView.as_view(), name="warehouse_edit"),
    path("warehouses/<int:pk>/delete/", views.WarehouseDeleteView.as_view(), name="warehouse_delete"),

    # Locations
    path("locations/", views.StockLocationListView.as_view(), name="location_list"),
    path("locations/create/", views.StockLocationCreateView.as_view(), name="location_create"),
    path("locations/<int:pk>/edit/", views.StockLocationUpdateView.as_view(), name="location_edit"),
    path("locations/<int:pk>/delete/", views.StockLocationDeleteView.as_view(), name="location_delete"),

    # Categories
    path("categories/", views.ProductCategoryListView.as_view(), name="category_list"),
    path("categories/create/", views.ProductCategoryCreateView.as_view(), name="category_create"),
    path("categories/<int:pk>/edit/", views.ProductCategoryUpdateView.as_view(), name="category_edit"),
    path("categories/<int:pk>/delete/", views.ProductCategoryDeleteView.as_view(), name="category_delete"),

    # ==========================
    # Reports & Rules
    # ==========================
    path("stock-levels/", views.StockLevelListView.as_view(), name="stock_level_list"),

    # ✅ التصحيح هنا: تغيير الاسم من valuation_report إلى inventory_valuation
    path("valuation/", views.InventoryValuationView.as_view(), name="inventory_valuation"),

    # Reorder Rules
    path("reorder-rules/", views.ReorderRuleListView.as_view(), name="reorder_rule_list"),
    path("reorder-rules/create/", views.ReorderRuleCreateView.as_view(), name="reorder_rule_create"),
    path("reorder-rules/<int:pk>/edit/", views.ReorderRuleUpdateView.as_view(), name="reorder_rule_edit"),
    path("reorder-rules/<int:pk>/delete/", views.ReorderRuleDeleteView.as_view(), name="reorder_rule_delete"),
]