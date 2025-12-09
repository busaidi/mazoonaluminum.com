# inventory/managers.py

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from django.db import models
from django.db.models import F, Sum, Count, Q

if TYPE_CHECKING:
    from .models import (
        ProductCategory,
        Product,
        Warehouse,
        StockLocation,
        StockMove,
        StockLevel,
        ReorderRule,
    )

DECIMAL_ZERO = Decimal("0.000")


# ============================================================
# ProductCategory
# ============================================================

class ProductCategoryQuerySet(models.QuerySet["ProductCategory"]):
    def active(self) -> "ProductCategoryQuerySet":
        """يرجع التصنيفات النشطة فقط."""
        return self.filter(is_active=True)

    def roots(self) -> "ProductCategoryQuerySet":
        """يرجع التصنيفات العليا (بدون أب)."""
        return self.filter(parent__isnull=True)

    def children_of(self, parent: "ProductCategory") -> "ProductCategoryQuerySet":
        """يرجع التصنيفات الفرعية لتصنيف معيّن."""
        return self.filter(parent=parent)

    def with_products_count(self) -> "ProductCategoryQuerySet":
        """
        يضيف حقل products_count لعدد المنتجات النشطة في كل تصنيف.
        """
        return self.annotate(
            products_count=Count(
                "products",
                filter=Q(products__is_active=True),
            )
        )


class ProductCategoryManager(models.Manager.from_queryset(ProductCategoryQuerySet)):  # type: ignore[misc]
    pass


# ============================================================
# Product
# ============================================================

class ProductQuerySet(models.QuerySet["Product"]):
    def active(self) -> "ProductQuerySet":
        return self.filter(is_active=True)

    def published(self) -> "ProductQuerySet":
        return self.active().filter(is_published=True)

    # ===== حسب نوع المنتج (Dynamic Choices) =====

    def stockable(self) -> "ProductQuerySet":
        return self.filter(product_type=self.model.ProductType.STOCKABLE)

    def services(self) -> "ProductQuerySet":
        return self.filter(product_type=self.model.ProductType.SERVICE)

    def consumables(self) -> "ProductQuerySet":
        return self.filter(product_type=self.model.ProductType.CONSUMABLE)

    def stock_items(self) -> "ProductQuerySet":
        """المنتجات التي تُتابَع في المخزون فعلياً."""
        return self.stockable().filter(is_stock_item=True)

    def for_sales(self) -> "ProductQuerySet":
        """
        المنتجات المتاحة للبيع (مخزنية أو خدمية).
        """
        return self.active().filter(
            Q(product_type=self.model.ProductType.STOCKABLE) |
            Q(product_type=self.model.ProductType.SERVICE)
        )

    # ===== تحسينات الأداء والبحث =====

    def with_category(self) -> "ProductQuerySet":
        return self.select_related("category")

    def with_stock_summary(self) -> "ProductQuerySet":
        """
        يضيف حقولاً محسوبة: total_qty, total_reserved.
        """
        return self.annotate(
            total_qty=Sum("stock_levels__quantity_on_hand", default=DECIMAL_ZERO),
            total_reserved=Sum("stock_levels__quantity_reserved", default=DECIMAL_ZERO),
        )

    def search(self, query: Optional[str]) -> "ProductQuerySet":
        """
        بحث ذكي في الكود، الاسم، والباركود.
        """
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
# Warehouse
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
# StockLocation
# ============================================================

class StockLocationQuerySet(models.QuerySet["StockLocation"]):
    def active(self) -> "StockLocationQuerySet":
        return self.filter(is_active=True)

    def for_warehouse(self, warehouse: "Warehouse") -> "StockLocationQuerySet":
        return self.filter(warehouse=warehouse)

    # ===== Dynamic Choices =====

    def internal(self) -> "StockLocationQuerySet":
        return self.filter(type=self.model.LocationType.INTERNAL)

    def supplier(self) -> "StockLocationQuerySet":
        return self.filter(type=self.model.LocationType.SUPPLIER)

    def customer(self) -> "StockLocationQuerySet":
        return self.filter(type=self.model.LocationType.CUSTOMER)

    def scrap(self) -> "StockLocationQuerySet":
        return self.filter(type=self.model.LocationType.SCRAP)

    def transit(self) -> "StockLocationQuerySet":
        return self.filter(type=self.model.LocationType.TRANSIT)


class StockLocationManager(models.Manager.from_queryset(StockLocationQuerySet)):  # type: ignore[misc]
    pass


# ============================================================
# StockMove
# ============================================================

class StockMoveQuerySet(models.QuerySet["StockMove"]):
    # ===== فلاتر الحالة (Dynamic Choices) =====
    def draft(self) -> "StockMoveQuerySet":
        return self.filter(status=self.model.Status.DRAFT)

    def done(self) -> "StockMoveQuerySet":
        return self.filter(status=self.model.Status.DONE)

    def cancelled(self) -> "StockMoveQuerySet":
        return self.filter(status=self.model.Status.CANCELLED)

    def not_cancelled(self) -> "StockMoveQuerySet":
        return self.exclude(status=self.model.Status.CANCELLED)

    # ===== فلاتر نوع الحركة (Dynamic Choices) =====
    def incoming(self) -> "StockMoveQuerySet":
        return self.filter(move_type=self.model.MoveType.IN)

    def outgoing(self) -> "StockMoveQuerySet":
        return self.filter(move_type=self.model.MoveType.OUT)

    def transfers(self) -> "StockMoveQuerySet":
        return self.filter(move_type=self.model.MoveType.TRANSFER)

    # ===== فلاتر مساعدة =====
    def for_product(self, product: "Product") -> "StockMoveQuerySet":
        return self.filter(lines__product=product).distinct()

    def for_warehouse(self, warehouse: "Warehouse") -> "StockMoveQuerySet":
        return self.filter(
            Q(from_warehouse=warehouse) | Q(to_warehouse=warehouse)
        )

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
# StockLevel
# ============================================================

class StockLevelQuerySet(models.QuerySet["StockLevel"]):
    def below_min(self) -> "StockLevelQuerySet":
        """(Legacy) يعتمد على حقل min_stock القديم."""
        return self.filter(
            min_stock__gt=DECIMAL_ZERO,
            quantity_on_hand__lt=F("min_stock"),
        )

    def available(self) -> "StockLevelQuerySet":
        """الكمية المتاحة (المتوفرة > المحجوزة)."""
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
# ReorderRule
# ============================================================

class ReorderRuleQuerySet(models.QuerySet["ReorderRule"]):
    def active(self) -> "ReorderRuleQuerySet":
        return self.filter(is_active=True)

    def for_warehouse(self, warehouse: "Warehouse") -> "ReorderRuleQuerySet":
        return self.filter(warehouse=warehouse)

    def for_product(self, product: "Product") -> "ReorderRuleQuerySet":
        return self.filter(product=product)

    def for_location(self, location: "StockLocation") -> "ReorderRuleQuerySet":
        return self.filter(location=location)

    def with_related(self) -> "ReorderRuleQuerySet":
        return self.select_related("product", "warehouse", "location")

    def below_min(self) -> List["ReorderRule"]:
        """
        يرجع قائمة بالقواعد التي أصبح رصيدها أقل من الحد الأدنى المحدد.
        ملاحظة: تُرجع List وليس QuerySet لأن الحساب يتم في بايثون.
        """
        return [rule for rule in self.iterator() if rule.is_below_min()]


class ReorderRuleManager(models.Manager.from_queryset(ReorderRuleQuerySet)):  # type: ignore[misc]
    pass