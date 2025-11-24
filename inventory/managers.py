# inventory/managers.py
from decimal import Decimal

from django.db import models
from django.db.models import F, Sum, Count


# ============================
# ProductCategory
# ============================

class ProductCategoryQuerySet(models.QuerySet):
    def active(self):
        """Only active categories."""
        return self.filter(is_active=True)

    def roots(self):
        """Top-level categories (no parent)."""
        return self.filter(parent__isnull=True)

    def children_of(self, parent):
        """Children of a given parent category."""
        return self.filter(parent=parent)

    def with_products_count(self):
        """
        Annotate with products_count for quick display in lists.
        """
        return self.annotate(products_count=Count("products"))


class ProductCategoryManager(models.Manager.from_queryset(ProductCategoryQuerySet)):
    """Manager for ProductCategory."""
    pass


# ============================
# Product
# ============================

class ProductQuerySet(models.QuerySet):
    def active(self):
        """Only active products."""
        return self.filter(is_active=True)

    def published(self):
        """Products published on website/portal."""
        return self.active().filter(is_published=True)

    def stock_items(self):
        """Products that are tracked in stock."""
        return self.filter(is_stock_item=True)

    def with_category(self):
        """Select related category for list/detail performance."""
        return self.select_related("category")


class ProductManager(models.Manager.from_queryset(ProductQuerySet)):
    """Manager for Product."""
    pass


# ============================
# Warehouse
# ============================

class WarehouseQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def with_total_qty(self):
        """
        Annotate each warehouse with total_qty (sum of quantity_on_hand).
        """
        return self.annotate(
            total_qty=Sum("stock_levels__quantity_on_hand")
        )

    def with_low_stock(self):
        """
        Warehouses that have at least one StockLevel below min_stock.
        """
        return self.filter(
            stock_levels__min_stock__gt=Decimal("0.000"),
            stock_levels__quantity_on_hand__lt=F("stock_levels__min_stock"),
        ).distinct()


class WarehouseManager(models.Manager.from_queryset(WarehouseQuerySet)):
    """Manager for Warehouse."""
    pass


# ============================
# StockLocation
# ============================

class StockLocationQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def for_warehouse(self, warehouse):
        return self.filter(warehouse=warehouse)

    def internal(self):
        return self.filter(type="internal")

    def supplier(self):
        return self.filter(type="supplier")

    def customer(self):
        return self.filter(type="customer")

    def scrap(self):
        return self.filter(type="scrap")

    def transit(self):
        return self.filter(type="transit")


class StockLocationManager(models.Manager.from_queryset(StockLocationQuerySet)):
    """Manager for StockLocation."""
    pass


# ============================
# StockMove
# ============================

class StockMoveQuerySet(models.QuerySet):
    # Status filters
    def draft(self):
        return self.filter(status="draft")

    def done(self):
        return self.filter(status="done")

    def cancelled(self):
        return self.filter(status="cancelled")

    # Move type filters
    def incoming(self):
        return self.filter(move_type="in")

    def outgoing(self):
        return self.filter(move_type="out")

    def transfers(self):
        return self.filter(move_type="transfer")

    def for_product(self, product):
        return self.filter(product=product)

    def for_warehouse(self, warehouse):
        """
        Any move where the warehouse is either source or destination.
        """
        return self.filter(
            models.Q(from_warehouse=warehouse)
            | models.Q(to_warehouse=warehouse)
        )

    def with_related(self):
        """
        Select related foreign keys for better performance in lists.
        """
        return self.select_related(
            "product",
            "uom",            # ✅ مهم الآن بعد ما صارت FK
            "from_warehouse",
            "to_warehouse",
            "from_location",
            "to_location",
        )



class StockMoveManager(models.Manager.from_queryset(StockMoveQuerySet)):
    """Manager for StockMove."""
    pass


# ============================
# StockLevel
# ============================

class StockLevelQuerySet(models.QuerySet):
    def below_min(self):
        """
        Stock levels where quantity_on_hand is below min_stock.
        """
        return self.filter(
            min_stock__gt=Decimal("0.000"),
            quantity_on_hand__lt=F("min_stock"),
        )

    def for_warehouse(self, warehouse):
        return self.filter(warehouse=warehouse)

    def for_product(self, product):
        return self.filter(product=product)

    def with_related(self):
        return self.select_related("product", "warehouse", "location")


class StockLevelManager(models.Manager.from_queryset(StockLevelQuerySet)):
    """Manager for StockLevel."""
    pass
