# inventory/managers.py

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from django.db import models
from django.db.models import F, Sum, Count, Q

if TYPE_CHECKING:
    # يتم استيراد النماذج هنا فقط لأغراض التلميح (Type Hinting)
    # هذا يمنع مشكلة Circular Import
    from .models import (
        ProductCategory,
        Product,
        Warehouse,
        StockLocation,
        StockMove,
        StockLevel,
        ReorderRule,
        InventoryAdjustment,
        InventoryAdjustmentLine,
        StockMoveLine,
    )

DECIMAL_ZERO = Decimal("0.000")


# ============================================================
# ProductCategory Manager
# ============================================================
class ProductCategoryQuerySet(models.QuerySet["ProductCategory"]):
    def active(self) -> "ProductCategoryQuerySet":
        return self.filter(is_active=True)

    def roots(self) -> "ProductCategoryQuerySet":
        return self.filter(parent__isnull=True)

    def children_of(self, parent: "ProductCategory") -> "ProductCategoryQuerySet":
        return self.filter(parent=parent)

    def with_products_count(self) -> "ProductCategoryQuerySet":
        return self.annotate(
            products_count=Count("products", filter=Q(products__is_active=True))
        )

class ProductCategoryManager(models.Manager.from_queryset(ProductCategoryQuerySet)):  # type: ignore[misc]
    pass


# ============================================================
# Product Manager
# ============================================================
class ProductQuerySet(models.QuerySet["Product"]):
    def active(self) -> "ProductQuerySet":
        return self.filter(is_active=True)

    def published(self) -> "ProductQuerySet":
        return self.active().filter(is_published=True)

    def stockable(self) -> "ProductQuerySet":
        return self.filter(product_type=self.model.ProductType.STOCKABLE)

    def services(self) -> "ProductQuerySet":
        return self.filter(product_type=self.model.ProductType.SERVICE)

    def consumables(self) -> "ProductQuerySet":
        return self.filter(product_type=self.model.ProductType.CONSUMABLE)

    def stock_items(self) -> "ProductQuerySet":
        return self.stockable().filter(is_stock_item=True)

    def with_category(self) -> "ProductQuerySet":
        return self.select_related("category")

    def with_stock_summary(self) -> "ProductQuerySet":
        """إضافة حقول وهمية للكميات: total_qty, total_reserved."""
        return self.annotate(
            total_qty=Sum("stock_levels__quantity_on_hand", default=DECIMAL_ZERO),
            total_reserved=Sum("stock_levels__quantity_reserved", default=DECIMAL_ZERO),
        )

    def search(self, query: Optional[str]) -> "ProductQuerySet":
        if not query:
            return self
        return self.filter(
            Q(code__icontains=query) |
            Q(name__icontains=query) |
            Q(barcode__icontains=query)
        )

class ProductManager(models.Manager.from_queryset(ProductQuerySet)):  # type: ignore[misc]
    pass


# ============================================================
# Warehouse Manager
# ============================================================
class WarehouseQuerySet(models.QuerySet["Warehouse"]):
    def active(self) -> "WarehouseQuerySet":
        return self.filter(is_active=True)

    def with_total_qty(self) -> "WarehouseQuerySet":
        return self.annotate(
            total_qty=Sum("stock_levels__quantity_on_hand", default=DECIMAL_ZERO)
        )

class WarehouseManager(models.Manager.from_queryset(WarehouseQuerySet)):  # type: ignore[misc]
    pass


# ============================================================
# StockLocation Manager
# ============================================================
class StockLocationQuerySet(models.QuerySet["StockLocation"]):
    def active(self) -> "StockLocationQuerySet":
        return self.filter(is_active=True)

    def for_warehouse(self, warehouse: "Warehouse") -> "StockLocationQuerySet":
        return self.filter(warehouse=warehouse)

    def internal(self) -> "StockLocationQuerySet":
        return self.filter(type=self.model.LocationType.INTERNAL)

class StockLocationManager(models.Manager.from_queryset(StockLocationQuerySet)):  # type: ignore[misc]
    pass


# ============================================================
# StockMove Manager
# ============================================================
class StockMoveQuerySet(models.QuerySet["StockMove"]):
    def draft(self) -> "StockMoveQuerySet":
        return self.filter(status=self.model.Status.DRAFT)

    def done(self) -> "StockMoveQuerySet":
        return self.filter(status=self.model.Status.DONE)

    def cancelled(self) -> "StockMoveQuerySet":
        return self.filter(status=self.model.Status.CANCELLED)

    def not_cancelled(self) -> "StockMoveQuerySet":
        return self.exclude(status=self.model.Status.CANCELLED)

    def incoming(self) -> "StockMoveQuerySet":
        return self.filter(move_type=self.model.MoveType.IN)

    def outgoing(self) -> "StockMoveQuerySet":
        return self.filter(move_type=self.model.MoveType.OUT)

    def transfers(self) -> "StockMoveQuerySet":
        return self.filter(move_type=self.model.MoveType.TRANSFER)

    def with_related(self) -> "StockMoveQuerySet":
        return (
            self.select_related(
                "from_warehouse", "to_warehouse",
                "from_location", "to_location",
            )
            .prefetch_related(
                "lines", "lines__product", "lines__uom",
            )
        )

class StockMoveManager(models.Manager.from_queryset(StockMoveQuerySet)):  # type: ignore[misc]
    pass


# ============================================================
# StockLevel Manager
# ============================================================
class StockLevelQuerySet(models.QuerySet["StockLevel"]):
    def available(self) -> "StockLevelQuerySet":
        """المتاح = المتوفر - المحجوز"""
        return self.filter(quantity_on_hand__gt=F("quantity_reserved"))

    def for_warehouse(self, warehouse: "Warehouse") -> "StockLevelQuerySet":
        return self.filter(warehouse=warehouse)

    def for_product(self, product: "Product") -> "StockLevelQuerySet":
        return self.filter(product=product)

    def with_related(self) -> "StockLevelQuerySet":
        return self.select_related("product", "warehouse", "location")

class StockLevelManager(models.Manager.from_queryset(StockLevelQuerySet)):  # type: ignore[misc]
    pass


# ============================================================
# ReorderRule Manager
# ============================================================
class ReorderRuleQuerySet(models.QuerySet["ReorderRule"]):
    def active(self) -> "ReorderRuleQuerySet":
        return self.filter(is_active=True)

    def with_related(self) -> "ReorderRuleQuerySet":
        return self.select_related("product", "warehouse", "location")

    # --- هذا هو التحديث الجديد ---
    def get_triggered_rules(self) -> List["ReorderRule"]:
        """
        يرجع قائمة بالقواعد التي وصل رصيدها للحد الأدنى وتستوجب الشراء.
        """
        rules = self.active().select_related('product', 'warehouse', 'location')
        results = []
        for rule in rules:
            if rule.is_below_min:
                results.append(rule)
        return results

class ReorderRuleManager(models.Manager.from_queryset(ReorderRuleQuerySet)):  # type: ignore[misc]
    pass


# ============================================================
# StockMoveLine Manager
# ============================================================
class StockMoveLineQuerySet(models.QuerySet["StockMoveLine"]):
    def for_product(self, product: "Product") -> "StockMoveLineQuerySet":
        return self.filter(product=product)

    def with_related(self) -> "StockMoveLineQuerySet":
        return self.select_related("move", "product", "uom")

class StockMoveLineManager(models.Manager.from_queryset(StockMoveLineQuerySet)):  # type: ignore[misc]
    pass


# ============================================================
# InventoryAdjustment Manager
# ============================================================
class InventoryAdjustmentQuerySet(models.QuerySet["InventoryAdjustment"]):
    def draft(self) -> "InventoryAdjustmentQuerySet":
        return self.filter(status=self.model.Status.DRAFT)

    def applied(self) -> "InventoryAdjustmentQuerySet":
        return self.filter(status=self.model.Status.APPLIED)

    def with_related(self) -> "InventoryAdjustmentQuerySet":
        return self.select_related("warehouse", "category", "location")

class InventoryAdjustmentManager(models.Manager.from_queryset(InventoryAdjustmentQuerySet)):  # type: ignore[misc]
    pass


# ============================================================
# InventoryAdjustmentLine Manager
# ============================================================
class InventoryAdjustmentLineQuerySet(models.QuerySet["InventoryAdjustmentLine"]):
    def with_related(self) -> "InventoryAdjustmentLineQuerySet":
        return self.select_related("adjustment", "product", "location")

    def with_difference(self) -> "InventoryAdjustmentLineQuerySet":
        """ترجع فقط الأسطر التي يوجد فرق بين الفعلي والنظري."""
        return self.filter(counted_qty__isnull=False).exclude(
            counted_qty=F('theoretical_qty')
        )

class InventoryAdjustmentLineManager(models.Manager.from_queryset(InventoryAdjustmentLineQuerySet)):  # type: ignore[misc]
    pass