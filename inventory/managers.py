# inventory/managers.py
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from django.apps import apps
from django.db import models
from django.db.models import Count, F, Prefetch, Q, Sum
from django.db.models.functions import Coalesce

if TYPE_CHECKING:
    from .models import (
        InventoryAdjustment,
        InventoryAdjustmentLine,
        Product,
        ProductCategory,
        ReorderRule,
        StockLevel,
        StockLocation,
        StockMove,
        StockMoveLine,
        Warehouse,
    )

DECIMAL_ZERO = Decimal("0.000")


# ============================================================
# Shared base QuerySet for SoftDeleteModel
# ============================================================
class SoftDeleteQuerySet(models.QuerySet):
    """
    Base QuerySet that respects BaseModel(SoftDeleteModel):
    - visible(): not deleted
    - deleted(): soft deleted
    - with_deleted(): return all
    """

    def visible(self):
        return self.filter(is_deleted=False)

    def deleted(self):
        return self.filter(is_deleted=True)

    def with_deleted(self):
        return self.all()


# ============================================================
# ProductCategory Manager
# ============================================================
class ProductCategoryQuerySet(SoftDeleteQuerySet, models.QuerySet["ProductCategory"]):
    def active(self) -> "ProductCategoryQuerySet":
        return self.visible().filter(is_active=True)

    def roots(self) -> "ProductCategoryQuerySet":
        return self.visible().filter(parent__isnull=True)

    def children_of(self, parent: "ProductCategory") -> "ProductCategoryQuerySet":
        return self.visible().filter(parent=parent)

    def with_products_count(self) -> "ProductCategoryQuerySet":
        return self.visible().annotate(
            products_count=Count(
                "products",
                filter=Q(products__is_deleted=False) & Q(products__is_active=True),
            )
        )


class ProductCategoryManager(models.Manager.from_queryset(ProductCategoryQuerySet)):  # type: ignore[misc]
    def get_queryset(self) -> ProductCategoryQuerySet:
        return super().get_queryset().visible()


# ============================================================
# Product Manager
# ============================================================
class ProductQuerySet(SoftDeleteQuerySet, models.QuerySet["Product"]):
    def active(self) -> "ProductQuerySet":
        return self.visible().filter(is_active=True)

    def published(self) -> "ProductQuerySet":
        return self.active().filter(is_published=True)

    def stockable(self) -> "ProductQuerySet":
        return self.visible().filter(product_type=self.model.ProductType.STOCKABLE)

    def services(self) -> "ProductQuerySet":
        return self.visible().filter(product_type=self.model.ProductType.SERVICE)

    def consumables(self) -> "ProductQuerySet":
        return self.visible().filter(product_type=self.model.ProductType.CONSUMABLE)

    def stock_items(self) -> "ProductQuerySet":
        return self.visible().filter(
            product_type__in=[
                self.model.ProductType.STOCKABLE,
                self.model.ProductType.CONSUMABLE,
            ]
        )

    def with_category(self) -> "ProductQuerySet":
        return self.select_related("category")

    def with_stock_summary(self) -> "ProductQuerySet":
        return self.annotate(
            total_qty=Coalesce(
                Sum("stock_levels__quantity_on_hand", filter=Q(stock_levels__is_deleted=False)),
                DECIMAL_ZERO,
            ),
            total_reserved=Coalesce(
                Sum("stock_levels__quantity_reserved", filter=Q(stock_levels__is_deleted=False)),
                DECIMAL_ZERO,
            ),
        )

    def search(self, query: Optional[str]) -> "ProductQuerySet":
        if not query:
            return self
        q = (query or "").strip()
        if not q:
            return self
        return self.filter(
            Q(code__icontains=q)
            | Q(name__icontains=q)  # modeltranslation resolves by active language
            | Q(barcode__icontains=q)
        )


class ProductManager(models.Manager.from_queryset(ProductQuerySet)):  # type: ignore[misc]
    def get_queryset(self) -> ProductQuerySet:
        return super().get_queryset().visible()


# ============================================================
# Warehouse Manager
# ============================================================
class WarehouseQuerySet(SoftDeleteQuerySet, models.QuerySet["Warehouse"]):
    def active(self) -> "WarehouseQuerySet":
        return self.visible().filter(is_active=True)

    def with_total_qty(self) -> "WarehouseQuerySet":
        return self.visible().annotate(
            total_qty=Coalesce(
                Sum("stock_levels__quantity_on_hand", filter=Q(stock_levels__is_deleted=False)),
                DECIMAL_ZERO,
            )
        )


class WarehouseManager(models.Manager.from_queryset(WarehouseQuerySet)):  # type: ignore[misc]
    def get_queryset(self) -> WarehouseQuerySet:
        return super().get_queryset().visible()


# ============================================================
# StockLocation Manager
# ============================================================
class StockLocationQuerySet(SoftDeleteQuerySet, models.QuerySet["StockLocation"]):
    def active(self) -> "StockLocationQuerySet":
        return self.visible().filter(is_active=True)

    def for_warehouse(self, warehouse: "Warehouse") -> "StockLocationQuerySet":
        return self.visible().filter(warehouse=warehouse)

    def internal(self) -> "StockLocationQuerySet":
        return self.visible().filter(type=self.model.LocationType.INTERNAL)

    def with_related(self) -> "StockLocationQuerySet":
        return self.select_related("warehouse")


class StockLocationManager(models.Manager.from_queryset(StockLocationQuerySet)):  # type: ignore[misc]
    def get_queryset(self) -> StockLocationQuerySet:
        return super().get_queryset().visible()


# ============================================================
# StockMove Manager
# ============================================================
class StockMoveQuerySet(SoftDeleteQuerySet, models.QuerySet["StockMove"]):
    # ----------------------------
    # Status
    # ----------------------------
    def draft(self) -> "StockMoveQuerySet":
        return self.visible().filter(status=self.model.Status.DRAFT)

    def done(self) -> "StockMoveQuerySet":
        return self.visible().filter(status=self.model.Status.DONE)

    def cancelled(self) -> "StockMoveQuerySet":
        return self.visible().filter(status=self.model.Status.CANCELLED)

    def not_cancelled(self) -> "StockMoveQuerySet":
        return self.visible().exclude(status=self.model.Status.CANCELLED)

    # ----------------------------
    # Move Type
    # ----------------------------
    def incoming(self) -> "StockMoveQuerySet":
        return self.visible().filter(move_type=self.model.MoveType.IN)

    def outgoing(self) -> "StockMoveQuerySet":
        return self.visible().filter(move_type=self.model.MoveType.OUT)

    def transfers(self) -> "StockMoveQuerySet":
        return self.visible().filter(move_type=self.model.MoveType.TRANSFER)

    # ----------------------------
    # Logic filters
    # ----------------------------
    def for_product(self, product: "Product") -> "StockMoveQuerySet":
        return self.visible().filter(lines__is_deleted=False, lines__product=product).distinct()

    def search(self, query: Optional[str]) -> "StockMoveQuerySet":
        if not query:
            return self
        q = (query or "").strip()
        if not q:
            return self
        return self.filter(Q(pk__icontains=q) | Q(reference__icontains=q) | Q(note__icontains=q))

    # ----------------------------
    # Performance
    # ----------------------------
    def with_related(self) -> "StockMoveQuerySet":
        """
        Fix NameError:
        StockMoveLine is only imported under TYPE_CHECKING.
        Use apps.get_model() to avoid NameError/circular imports.
        """
        StockMoveLineModel = apps.get_model("inventory", "StockMoveLine")

        return (
            self.select_related(
                "from_warehouse",
                "to_warehouse",
                "from_location",
                "to_location",
                "created_by",
                "updated_by",
            )
            .prefetch_related(
                Prefetch(
                    "lines",
                    queryset=StockMoveLineModel.objects.visible().select_related("product", "uom"),
                )
            )
        )


class StockMoveManager(models.Manager.from_queryset(StockMoveQuerySet)):  # type: ignore[misc]
    def get_queryset(self) -> StockMoveQuerySet:
        return super().get_queryset().visible()


# ============================================================
# StockMoveLine Manager
# ============================================================
class StockMoveLineQuerySet(SoftDeleteQuerySet, models.QuerySet["StockMoveLine"]):
    def for_product(self, product: "Product") -> "StockMoveLineQuerySet":
        return self.visible().filter(product=product)

    def with_related(self) -> "StockMoveLineQuerySet":
        # You confirmed FK name is `move`
        return self.select_related("move", "product", "uom")


class StockMoveLineManager(models.Manager.from_queryset(StockMoveLineQuerySet)):  # type: ignore[misc]
    def get_queryset(self) -> StockMoveLineQuerySet:
        return super().get_queryset().visible()


# ============================================================
# StockLevel Manager
# ============================================================
class StockLevelQuerySet(SoftDeleteQuerySet, models.QuerySet["StockLevel"]):
    def for_warehouse(self, warehouse: "Warehouse") -> "StockLevelQuerySet":
        return self.visible().filter(warehouse=warehouse)

    def for_product(self, product: "Product") -> "StockLevelQuerySet":
        return self.visible().filter(product=product)

    def available(self) -> "StockLevelQuerySet":
        return self.visible().filter(quantity_on_hand__gt=F("quantity_reserved"))

    def with_related(self) -> "StockLevelQuerySet":
        return self.select_related("product", "warehouse", "location")


class StockLevelManager(models.Manager.from_queryset(StockLevelQuerySet)):  # type: ignore[misc]
    def get_queryset(self) -> StockLevelQuerySet:
        return super().get_queryset().visible()


# ============================================================
# ReorderRule Manager
# ============================================================
class ReorderRuleQuerySet(SoftDeleteQuerySet, models.QuerySet["ReorderRule"]):
    def active(self) -> "ReorderRuleQuerySet":
        return self.visible().filter(is_active=True)

    def with_related(self) -> "ReorderRuleQuerySet":
        return self.select_related("product", "warehouse", "location")

    def triggered(self) -> "ReorderRuleQuerySet":
        return self.active().with_related()

    def get_triggered_rules(self):
        rules = self.active().with_related()
        return [r for r in rules if r.is_below_min]


class ReorderRuleManager(models.Manager.from_queryset(ReorderRuleQuerySet)):  # type: ignore[misc]
    def get_queryset(self) -> ReorderRuleQuerySet:
        return super().get_queryset().visible()


# ============================================================
# InventoryAdjustment Manager
# ============================================================
class InventoryAdjustmentQuerySet(SoftDeleteQuerySet, models.QuerySet["InventoryAdjustment"]):
    def draft(self) -> "InventoryAdjustmentQuerySet":
        return self.visible().filter(status=self.model.Status.DRAFT)

    def applied(self) -> "InventoryAdjustmentQuerySet":
        return self.visible().filter(status=self.model.Status.APPLIED)

    def in_progress(self) -> "InventoryAdjustmentQuerySet":
        return self.visible().filter(status=self.model.Status.IN_PROGRESS)

    def not_cancelled(self) -> "InventoryAdjustmentQuerySet":
        return self.visible().exclude(status=self.model.Status.CANCELLED)

    def with_related(self) -> "InventoryAdjustmentQuerySet":
        InventoryAdjustmentLineModel = apps.get_model("inventory", "InventoryAdjustmentLine")

        return (
            self.select_related("warehouse", "category", "location", "created_by", "updated_by")
            .prefetch_related(
                Prefetch(
                    "lines",
                    queryset=InventoryAdjustmentLineModel.objects.visible().select_related("product", "location"),
                )
            )
        )


class InventoryAdjustmentManager(models.Manager.from_queryset(InventoryAdjustmentQuerySet)):  # type: ignore[misc]
    def get_queryset(self) -> InventoryAdjustmentQuerySet:
        return super().get_queryset().visible()


# ============================================================
# InventoryAdjustmentLine Manager
# ============================================================
class InventoryAdjustmentLineQuerySet(SoftDeleteQuerySet, models.QuerySet["InventoryAdjustmentLine"]):
    def with_related(self) -> "InventoryAdjustmentLineQuerySet":
        return self.select_related("adjustment", "product", "location")

    def with_difference(self) -> "InventoryAdjustmentLineQuerySet":
        return self.visible().filter(counted_qty__isnull=False).exclude(counted_qty=F("theoretical_qty"))


class InventoryAdjustmentLineManager(models.Manager.from_queryset(InventoryAdjustmentLineQuerySet)):  # type: ignore[misc]
    def get_queryset(self) -> InventoryAdjustmentLineQuerySet:
        return super().get_queryset().visible()
