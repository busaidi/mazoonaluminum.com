# inventory/managers.py

from decimal import Decimal

from django.db import models
from django.db.models import F, Sum, Count, Q


DECIMAL_ZERO = Decimal("0.000")


# ============================
# ProductCategory
# ============================

class ProductCategoryQuerySet(models.QuerySet):
    def active(self):
        """
        يرجع التصنيفات النشطة فقط.
        """
        return self.filter(is_active=True)

    def roots(self):
        """
        يرجع التصنيفات العليا (بدون أب).
        """
        return self.filter(parent__isnull=True)

    def children_of(self, parent):
        """
        يرجع التصنيفات الفرعية لتصنيف معيّن.
        """
        return self.filter(parent=parent)

    def with_products_count(self):
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


class ProductCategoryManager(models.Manager.from_queryset(ProductCategoryQuerySet)):
    """
    Manager خاص بتصنيفات المنتجات.
    """
    pass


# ============================
# Product
# ============================

class ProductQuerySet(models.QuerySet):
    def active(self):
        """
        يرجع المنتجات النشطة فقط.
        """
        return self.filter(is_active=True)

    def published(self):
        """
        يرجع المنتجات المنشورة في الموقع / البوابة.
        (نستخدم المنتجات النشطة فقط).
        """
        return self.active().filter(is_published=True)

    # ===== حسب نوع المنتج (product_type) =====

    def stockable(self):
        """
        المنتجات المخزنية (stockable).
        """
        return self.filter(product_type="stockable")

    def services(self):
        """
        المنتجات من نوع خدمة (service).
        """
        return self.filter(product_type="service")

    def consumables(self):
        """
        المنتجات من نوع مستهلكات (consumable).
        """
        return self.filter(product_type="consumable")

    def stock_items(self):
        """
        المنتجات التي تُتابَع في المخزون فعلياً.
        - نوع المنتج مخزني stockable
        - الحقل is_stock_item = True
        """
        return self.stockable().filter(is_stock_item=True)

    def with_category(self):
        """
        يعمل select_related للتصنيف لتحسين الأداء في القوائم والتفاصيل.
        """
        return self.select_related("category")


class ProductManager(models.Manager.from_queryset(ProductQuerySet)):
    """
    Manager خاص بالمنتجات.
    """
    pass


# ============================
# Warehouse
# ============================

class WarehouseQuerySet(models.QuerySet):
    def active(self):
        """
        يرجع المستودعات النشطة فقط.
        """
        return self.filter(is_active=True)

    def with_total_qty(self):
        """
        يضيف حقل total_qty لكل مستودع (مجموع quantity_on_hand من StockLevel).
        """
        return self.annotate(
            total_qty=Sum("stock_levels__quantity_on_hand")
        )

    def with_low_stock(self):
        """
        يرجع المستودعات التي تحتوي على الأقل على صنف واحد تحت الحد الأدنى للمخزون.
        """
        return self.filter(
            stock_levels__min_stock__gt=DECIMAL_ZERO,
            stock_levels__quantity_on_hand__lt=F("stock_levels__min_stock"),
        ).distinct()


class WarehouseManager(models.Manager.from_queryset(WarehouseQuerySet)):
    """
    Manager خاص بالمستودعات.
    """
    pass


# ============================
# StockLocation
# ============================

class StockLocationQuerySet(models.QuerySet):
    def active(self):
        """
        يرجع مواقع المخزون النشطة فقط.
        """
        return self.filter(is_active=True)

    def for_warehouse(self, warehouse):
        """
        يرجع المواقع التابعة لمستودع معيّن.
        """
        return self.filter(warehouse=warehouse)

    def internal(self):
        """
        مواقع من نوع داخلي.
        """
        return self.filter(type="internal")

    def supplier(self):
        """
        مواقع من نوع مورد.
        """
        return self.filter(type="supplier")

    def customer(self):
        """
        مواقع من نوع عميل.
        """
        return self.filter(type="customer")

    def scrap(self):
        """
        مواقع من نوع تالفة (Scrap).
        """
        return self.filter(type="scrap")

    def transit(self):
        """
        مواقع من نوع قيد النقل (Transit).
        """
        return self.filter(type="transit")


class StockLocationManager(models.Manager.from_queryset(StockLocationQuerySet)):
    """
    Manager خاص بمواقع المخزون.
    """
    pass


# ============================
# StockMove
# ============================

class StockMoveQuerySet(models.QuerySet):
    # ===== فلاتر الحالة =====

    def draft(self):
        """
        حركات في حالة مسودة.
        """
        return self.filter(status="draft")

    def done(self):
        """
        حركات منفذة.
        """
        return self.filter(status="done")

    def cancelled(self):
        """
        حركات ملغاة.
        """
        return self.filter(status="cancelled")

    # ===== فلاتر نوع الحركة =====

    def incoming(self):
        """
        حركات واردة (IN).
        """
        return self.filter(move_type="in")

    def outgoing(self):
        """
        حركات صادرة (OUT).
        """
        return self.filter(move_type="out")

    def transfers(self):
        """
        حركات تحويل بين مستودعات/مواقع (TRANSFER).
        """
        return self.filter(move_type="transfer")

    # ===== فلاتر مساعدة =====

    def for_product(self, product):
        """
        يرجع الحركات التي تحتوي على المنتج المحدد في أحد البنود (StockMoveLine).
        """
        return self.filter(lines__product=product).distinct()

    def for_warehouse(self, warehouse):
        """
        يرجع أي حركة يكون فيها المستودع المحدد إما مصدر أو وجهة.
        """
        return self.filter(
            Q(from_warehouse=warehouse) | Q(to_warehouse=warehouse)
        )

    def with_related(self):
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


class StockMoveManager(models.Manager.from_queryset(StockMoveQuerySet)):
    """
    Manager خاص بحركات المخزون.
    """
    pass


# ============================
# StockLevel
# ============================

class StockLevelQuerySet(models.QuerySet):
    def below_min(self):
        """
        أرصدة المخزون التي تكون الكمية المتوفرة فيها أقل من الحد الأدنى.
        """
        return self.filter(
            min_stock__gt=DECIMAL_ZERO,
            quantity_on_hand__lt=F("min_stock"),
        )

    def available(self):
        """
        أرصدة المخزون التي فيها كمية متاحة (الكمية المتوفرة - المحجوزة > 0).
        """
        return self.filter(
            quantity_on_hand__gt=DECIMAL_ZERO,
        ).filter(
            quantity_on_hand__gt=F("quantity_reserved")
        )

    def for_warehouse(self, warehouse):
        """
        أرصدة مخزون لمستودع معيّن.
        """
        return self.filter(warehouse=warehouse)

    def for_product(self, product):
        """
        أرصدة مخزون لمنتج معيّن.
        """
        return self.filter(product=product)

    def with_related(self):
        """
        select_related للمنتج والمستودع والموقع لتحسين الأداء.
        """
        return self.select_related("product", "warehouse", "location")


class StockLevelManager(models.Manager.from_queryset(StockLevelQuerySet)):
    """
    Manager خاص بأرصدة المخزون.
    """
    pass
