# inventory/urls.py

from django.urls import path
from . import views
from .models import StockMove

app_name = "inventory"

urlpatterns = [
    # ============================================================
    # 1. لوحة التحكم (Dashboard)
    # ============================================================
    path("", views.DashboardView.as_view(), name="dashboard"),

    # ============================================================
    # 2. العمليات اليومية (Operations)
    # ============================================================

    # --- أ. استلام (Receipts - IN) ---
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

    # --- ب. صرف (Deliveries - OUT) ---
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

    # --- ج. تحويل (Transfers) ---
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

    # --- د. تفاصيل وإجراءات الحركات (Common Actions) ---
    path("operations/move/<int:pk>/", views.StockMoveDetailView.as_view(), name="move_detail"),
    path("operations/move/<int:pk>/confirm/", views.confirm_move_view, name="move_confirm"),
    path("operations/move/<int:pk>/cancel/", views.cancel_move_view, name="move_cancel"),
    path("operations/move/<int:pk>/print/", views.stock_move_pdf_view, name="move_print"),  # 🖨️ PDF Print

    # --- هـ. تسوية الجرد (Inventory Adjustments) ---
    path("adjustments/", views.InventoryAdjustmentListView.as_view(), name="adjustment_list"),
    path("adjustments/start/", views.InventoryAdjustmentCreateView.as_view(), name="adjustment_create"),  # ✅ قبل pk
    path("adjustments/<int:pk>/", views.InventoryAdjustmentDetailView.as_view(), name="adjustment_detail"),
    path("adjustments/<int:pk>/count/", views.InventoryAdjustmentUpdateView.as_view(), name="adjustment_count"),
    path("adjustments/<int:pk>/apply/", views.apply_adjustment_view, name="adjustment_apply"),

    # ============================================================
    # 3. التقارير والتحكم (Reporting & Control)
    # ============================================================

    # أرصدة المخزون
    path("stock-levels/", views.StockLevelListView.as_view(), name="stock_level_list"),

    # تقييم المخزون (المالي)
    path("reports/valuation/", views.InventoryValuationView.as_view(), name="inventory_valuation"),

    # قواعد إعادة الطلب
    path("reorder-rules/", views.ReorderRuleListView.as_view(), name="reorder_rule_list"),
    path("reorder-rules/create/", views.ReorderRuleCreateView.as_view(), name="reorder_rule_create"),  # ✅ قبل pk
    path("reorder-rules/<int:pk>/edit/", views.ReorderRuleUpdateView.as_view(), name="reorder_rule_update"),
    path("reorder-rules/<int:pk>/delete/", views.ReorderRuleDeleteView.as_view(), name="reorder_rule_delete"),

    # ============================================================
    # 4. البيانات الأساسية (Master Data)
    # ============================================================

    # --- المنتجات (Products) ---
    # ⚠️ الترتيب هنا حاسم جداً لتجنب خطأ 404
    path("products/", views.ProductListView.as_view(), name="product_list"),
    path("products/create/", views.ProductCreateView.as_view(), name="product_create"),  # ✅ ثابت
    path("products/export/", views.export_products_view, name="product_export"),  # ✅ ثابت
    path("products/import/", views.import_products_view, name="product_import"),  # ✅ ثابت

    # الروابط الديناميكية تأتي في النهاية
    path("products/<str:code>/", views.ProductDetailView.as_view(), name="product_detail"),
    path("products/<str:code>/edit/", views.ProductUpdateView.as_view(), name="product_update"),

    # --- التصنيفات (Categories) ---
    path("categories/", views.ProductCategoryListView.as_view(), name="category_list"),
    path("categories/create/", views.ProductCategoryCreateView.as_view(), name="category_create"),
    path("categories/<int:pk>/edit/", views.ProductCategoryUpdateView.as_view(), name="category_update"),

    # --- المستودعات (Warehouses) ---
    path("warehouses/", views.WarehouseListView.as_view(), name="warehouse_list"),
    path("warehouses/create/", views.WarehouseCreateView.as_view(), name="warehouse_create"),
    path("warehouses/<int:pk>/edit/", views.WarehouseUpdateView.as_view(), name="warehouse_update"),

    # --- مواقع التخزين (Locations) ---
    path("locations/", views.StockLocationListView.as_view(), name="location_list"),
    path("locations/create/", views.StockLocationCreateView.as_view(), name="location_create"),
    path("locations/<int:pk>/edit/", views.StockLocationUpdateView.as_view(), name="location_update"),

    # ============================================================
    # 5. الإعدادات (Settings)
    # ============================================================
    path("settings/", views.InventorySettingsView.as_view(), name="settings"),
]