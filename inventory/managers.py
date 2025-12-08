# inventory/managers.py

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

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
    )

DECIMAL_ZERO = Decimal("0.000")


# ============================================================
# ProductCategory
# ============================================================

class ProductCategoryQuerySet(models.QuerySet["ProductCategory"]):
    def active(self) -> "ProductCategoryQuerySet":
        """
        يرجع التصنيفات النشطة فقط.
        """
        return self.filter(is_active=True)

    def roots(self) -> "ProductCategoryQuerySet":
        """
        يرجع التصنيفات العليا (بدون أب).
        """
        return self.filter(parent__isnull=True)

    def children_of(self, parent: "ProductCategory") -> "ProductCategoryQuerySet":
        """
        يرجع التصنيفات الفرعية لتصنيف معيّن.
        """
        return self.filter(parent=parent)

    def with_products_count(self) -> "ProductCategoryQuerySet":
        """
        يضيف حقل products_count لعدد المنتجات النشطة في كل تصنيف.
        مفيد للعرض في القوائم.
        """
        return self.annotate(
            products_count=Count(
                "products",
                filter=Q(products__is_active=True),
            )
        )


class ProductCategoryManager(models.Manager.from_queryset(ProductCategoryQuerySet)):  # type: ignore[misc]
    """
    Manager خاص بتصنيفات المنتجات.
    """
    pass


# ============================================================
# Product
# ============================================================

class ProductQuerySet(models.QuerySet["Product"]):
    def active(self) -> "ProductQuerySet":
        """
        يرجع المنتجات النشطة فقط.
        """
        return self.filter(is_active=True)

    def published(self) -> "ProductQuerySet":
        """
        يرجع المنتجات المنشورة في الموقع / البوابة.
        (نستخدم المنتجات النشطة فقط).
        """
        return self.active().filter(is_published=True)

    # ===== حسب نوع المنتج (product_type) =====

    def stockable(self) -> "ProductQuerySet":
        """
        المنتجات المخزنية (stockable).
        """
        return self.filter(product_type="stockable")

    def services(self) -> "ProductQuerySet":
        """
        المنتجات من نوع خدمة (service).
        """
        return self.filter(product_type="service")

    def consumables(self) -> "ProductQuerySet":
        """
        المنتجات من نوع مستهلكات (consumable).
        """
        return self.filter(product_type="consumable")

    def stock_items(self) -> "ProductQuerySet":
        """
        المنتجات التي تُتابَع في المخزون فعلياً.
        - نوع المنتج مخزني stockable
        - الحقل is_stock_item = True
        """
        return self.stockable().filter(is_stock_item=True)

    def with_category(self) -> "ProductQuerySet":
        """
        يعمل select_related للتصنيف لتحسين الأداء في القوائم والتفاصيل.
        """
        return self.select_related("category")


class ProductManager(models.Manager.from_queryset(ProductQuerySet)):  # type: ignore[misc]
    """
    Manager خاص بالمنتجات.
    """
    pass


# ============================================================
# Warehouse
# ============================================================

class WarehouseQuerySet(models.QuerySet["Warehouse"]):
    def active(self) -> "WarehouseQuerySet":
        """
        يرجع المستودعات النشطة فقط.
        """
        return self.filter(is_active=True)

    def with_total_qty(self) -> "WarehouseQuerySet":
        """
        يضيف حقل total_qty لكل مستودع (مجموع quantity_on_hand من StockLevel).
        ملاحظة: هذا يعتمد على relation: warehouse.stock_levels
        """
        return self.annotate(
            total_qty=Sum("stock_levels__quantity_on_hand")
        )

    def with_low_stock(self) -> "WarehouseQuerySet":
        """
        يرجع المستودعات التي تحتوي على الأقل على صنف واحد تحت الحد الأدنى للمخزون.
        """
        return self.filter(
            stock_levels__min_stock__gt=DECIMAL_ZERO,
            stock_levels__quantity_on_hand__lt=F("stock_levels__min_stock"),
        ).distinct()


class WarehouseManager(models.Manager.from_queryset(WarehouseQuerySet)):  # type: ignore[misc]
    """
    Manager خاص بالمستودعات.
    """
    pass


# ============================================================
# StockLocation
# ============================================================

class StockLocationQuerySet(models.QuerySet["StockLocation"]):
    def active(self) -> "StockLocationQuerySet":
        """
        يرجع مواقع المخزون النشطة فقط.
        """
        return self.filter(is_active=True)

    def for_warehouse(self, warehouse: "Warehouse") -> "StockLocationQuerySet":
        """
        يرجع المواقع التابعة لمستودع معيّن.
        """
        return self.filter(warehouse=warehouse)

    def internal(self) -> "StockLocationQuerySet":
        """
        مواقع من نوع داخلي.
        """
        return self.filter(type="internal")

    def supplier(self) -> "StockLocationQuerySet":
        """
        مواقع من نوع مورد.
        """
        return self.filter(type="supplier")

    def customer(self) -> "StockLocationQuerySet":
        """
        مواقع من نوع عميل.
        """
        return self.filter(type="customer")

    def scrap(self) -> "StockLocationQuerySet":
        """
        مواقع من نوع تالفة (Scrap).
        """
        return self.filter(type="scrap")

    def transit(self) -> "StockLocationQuerySet":
        """
        مواقع من نوع قيد النقل (Transit).
        """
        return self.filter(type="transit")


class StockLocationManager(models.Manager.from_queryset(StockLocationQuerySet)):  # type: ignore[misc]
    """
    Manager خاص بمواقع المخزون.
    """
    pass


# ============================================================
# StockMove
# ============================================================

class StockMoveQuerySet(models.QuerySet["StockMove"]):
    # ===== فلاتر الحالة =====

    def draft(self) -> "StockMoveQuerySet":
        """
        حركات في حالة مسودة.
        """
        return self.filter(status="draft")

    def done(self) -> "StockMoveQuerySet":
        """
        حركات منفذة.
        """
        return self.filter(status="done")

    def cancelled(self) -> "StockMoveQuerySet":
        """
        حركات ملغاة.
        """
        return self.filter(status="cancelled")

    def not_cancelled(self) -> "StockMoveQuerySet":
        """
        جميع الحركات ما عدا الملغاة.
        """
        return self.exclude(status="cancelled")

    # ===== فلاتر نوع الحركة =====

    def incoming(self) -> "StockMoveQuerySet":
        """
        حركات واردة (IN).
        """
        return self.filter(move_type="in")

    def outgoing(self) -> "StockMoveQuerySet":
        """
        حركات صادرة (OUT).
        """
        return self.filter(move_type="out")

    def transfers(self) -> "StockMoveQuerySet":
        """
        حركات تحويل بين مستودعات/مواقع (TRANSFER).
        """
        return self.filter(move_type="transfer")

    # ===== فلاتر مساعدة =====

    def for_product(self, product: "Product") -> "StockMoveQuerySet":
        """
        يرجع الحركات التي تحتوي على المنتج المحدد في أحد البنود (StockMoveLine).
        """
        return self.filter(lines__product=product).distinct()

    def for_warehouse(self, warehouse: "Warehouse") -> "StockMoveQuerySet":
        """
        يرجع أي حركة يكون فيها المستودع المحدد إما مصدر أو وجهة.
        """
        return self.filter(
            Q(from_warehouse=warehouse) | Q(to_warehouse=warehouse)
        )

    def for_location(self, location: "StockLocation") -> "StockMoveQuerySet":
        """
        يرجع أي حركة يكون فيها الموقع المحدد إما مصدر أو وجهة.
        """
        return self.filter(
            Q(from_location=location) | Q(to_location=location)
        )

    def with_related(self) -> "StockMoveQuerySet":
        """
        يحسّن الأداء في القوائم بالتالي:
          - select_related للمستودعات والمواقع (من/إلى)
          - prefetch_related للبنود والمنتجات ووحدات القياس
        """
        return (
            self.select_related(
                "from_warehouse",
                "to_warehouse",
                "from_location",
                "to_location",
            )
            .prefetch_related(
                "lines",
                "lines__product",
                "lines__uom",
            )
        )


class StockMoveManager(models.Manager.from_queryset(StockMoveQuerySet)):  # type: ignore[misc]
    """
    Manager خاص بحركات المخزون.

    ملاحظة:
    - عمليات تغيير الحالة (confirm / cancel) يفضّل أن تكون عبر services:
      confirm_stock_move / cancel_stock_move
      وليس عبر Manager مباشرة، حتى تبقى قواعد العمل في مكان واحد.
    """
    pass


# ============================================================
# StockLevel
# ============================================================

class StockLevelQuerySet(models.QuerySet["StockLevel"]):
    def below_min(self) -> "StockLevelQuerySet":
        """
        أرصدة المخزون التي تكون الكمية المتوفرة فيها أقل من الحد الأدنى.
        """
        return self.filter(
            min_stock__gt=DECIMAL_ZERO,
            quantity_on_hand__lt=F("min_stock"),
        )

    def available(self) -> "StockLevelQuerySet":
        """
        أرصدة المخزون التي فيها كمية متاحة (الكمية المتوفرة - المحجوزة > 0).

        الصيغة:
        quantity_on_hand > quantity_reserved
        """
        return self.filter(
            quantity_on_hand__gt=F("quantity_reserved")
        )

    def for_warehouse(self, warehouse: "Warehouse") -> "StockLevelQuerySet":
        """
        أرصدة مخزون لمستودع معيّن.
        """
        return self.filter(warehouse=warehouse)

    def for_product(self, product: "Product") -> "StockLevelQuerySet":
        """
        أرصدة مخزون لمنتج معيّن.
        """
        return self.filter(product=product)

    def with_related(self) -> "StockLevelQuerySet":
        """
        select_related للمنتج والمستودع والموقع لتحسين الأداء.
        """
        return self.select_related("product", "warehouse", "location")


class StockLevelManager(models.Manager.from_queryset(StockLevelQuerySet)):  # type: ignore[misc]
    """
    Manager خاص بأرصدة المخزون.
    """
    pass
