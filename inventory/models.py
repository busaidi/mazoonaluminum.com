# inventory/models.py

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum, F
from django.utils import timezone
from solo.models import SingletonModel
from django.utils.translation import gettext_lazy as _


from core.models import TimeStampedModel, NumberedModel
from inventory.managers import ProductCategoryManager, ProductManager, StockLocationManager, StockMoveManager, \
    StockLevelManager, WarehouseManager
from uom.models import UnitOfMeasure


# ============================================================
# Categories
# ============================================================
class ProductCategory(TimeStampedModel):
    """
    Simple category tree for inventory product.
    Example: Aluminum Systems, Accessories, Glass, Services...
    """

    slug = models.SlugField(
        max_length=120,
        unique=True,
        verbose_name=_("المعرّف (Slug)"),
        help_text=_("معرّف يصلح للرابط بدون مسافات، مثل: mazoon-46-system"),
    )

    name = models.CharField(
        max_length=200,
        verbose_name=_("اسم التصنيف"),
    )

    description = models.TextField(
        blank=True,
        verbose_name=_("وصف التصنيف"),
    )

    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("التصنيف الأب"),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("نشط"),
    )

    objects = ProductCategoryManager()

    class Meta:
        verbose_name = _("تصنيف منتج")
        verbose_name_plural = _("تصنيفات المنتجات")
        ordering = ("name",)

    def __str__(self) -> str:
        if self.parent:
            return f"{self.parent} → {self.name}"
        return self.name

    # ============================
    # Helpers
    # ============================

    @property
    def full_path(self) -> str:
        """
        Full hierarchical path, e.g. "Systems / Thermal Break / Sliding".
        Useful for dropdowns and reports.
        """
        parts = [self.name]
        parent = self.parent
        while parent is not None:
            parts.append(parent.name)
            parent = parent.parent
        parts.reverse()
        return " / ".join(parts)

    def active_children(self):
        """
        Return only active child categories.
        """
        return self.children.filter(is_active=True)

    def products_count(self) -> int:
        """
        Number of active products in this category (direct only).
        """
        # Product.category has related_name="products"
        return self.products.filter(is_active=True).count()

    def can_be_deleted(self) -> bool:
        """
        Simple rule:
        - No child categories
        - No products
        """
        return not self.children.exists() and not self.products.exists()
# ============================================================
# Products
# ============================================================

class Product(TimeStampedModel):
    """
    Core inventory product.
    Master product used by inventory / orders / invoices.
    Website / portal visibility is controlled by `is_published`.
    """

    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name=_("التصنيف"),
    )

    # Internal product code / SKU
    code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_("كود المنتج"),
        help_text=_("كود داخلي فريد، مثل: MZN-46-FRAME"),
    )

    # Name/description (later can be linked to django-modeltranslation)
    name = models.CharField(
        max_length=255,
        verbose_name=_("اسم المنتج"),
    )

    short_description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("وصف مختصر"),
        help_text=_("سطر واحد يظهر في القوائم والجداول."),
    )

    description = models.TextField(
        blank=True,
        verbose_name=_("وصف تفصيلي"),
    )

    # ============================
    #   Units of measure
    # ============================

    # Base quantity UoM (e.g. m, pcs)
    base_uom = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name="products_as_base",
        verbose_name=_("وحدة القياس الأساسية"),
        help_text=_("الوحدة الأساسية للمخزون، مثل: M, PCS."),
    )

    # Optional alternative UoM (e.g. roll, box) with factor
    alt_uom = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="products_as_alt",
        verbose_name=_("وحدة بديلة"),
        help_text=_(
            "وحدة أخرى للبيع أو الشراء (مثل: لفة، كرتون). "
            "سيتم تعريف 1 وحدة بديلة كـ alt_factor من الوحدة الأساسية."
        ),
    )

    alt_factor = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        verbose_name=_("عامل تحويل الوحدة البديلة"),
        help_text=_(
            "كم تساوي 1 وحدة بديلة من الوحدة الأساسية. "
            "مثال: إذا الأساس متر والبديلة لفة 6م، اكتب 6."
        ),
    )

    # Weight UoM (e.g. kg) and relation to base unit
    weight_uom = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="products_as_weight",
        verbose_name=_("وحدة الوزن"),
        help_text=_("الوحدة المستخدمة للوزن، مثل: KG."),
    )

    weight_per_base = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        verbose_name=_("الوزن لكل وحدة أساسية"),
        help_text=_(
            "الوزن في وحدة الوزن لكل 1 من الوحدة الأساسية. "
            "مثال: إذا الأساس متر ووحدة الوزن كجم، هذا الحقل هو كجم/م."
        ),
    )

    # ============================
    #   Inventory / status flags
    # ============================

    # Is this tracked in stock?
    is_stock_item = models.BooleanField(
        default=True,
        verbose_name=_("يُتابَع في المخزون"),
        help_text=_("إذا تم تعطيله، لن يتم تتبع هذا المنتج في حركات المخزون."),
    )

    # Status flags
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("نشط"),
        help_text=_("إذا تم تعطيله، لن يظهر في المستندات الجديدة."),
    )

    # نشر المنتج على البورتال / الموقع
    is_published = models.BooleanField(
        default=False,
        verbose_name=_("منشور على الموقع/البوابة"),
        help_text=_("إذا تم تفعيله، يمكن عرض المنتج في الموقع أو بوابة العملاء."),
    )

    objects = ProductManager()

    class Meta:
        verbose_name = _("منتج")
        verbose_name_plural = _("المنتجات")
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} – {self.name}"

    # ============================
    #   UoM converters
    # ============================

    def convert_qty(self, qty, from_uom, to_uom):
        """
        Convert quantity between base_uom and alt_uom using alt_factor.

        Rules:
        - 1 alt_uom = alt_factor * base_uom
        """
        if qty is None:
            return None

        qty = Decimal(qty)

        # Same unit: nothing to do
        if from_uom == to_uom:
            return qty

        if not self.alt_uom or not self.alt_factor:
            raise ValueError("No alternative unit/factor configured for this product.")

        factor = Decimal(self.alt_factor)

        # alt -> base
        if from_uom == self.alt_uom and to_uom == self.base_uom:
            return qty * factor

        # base -> alt
        if from_uom == self.base_uom and to_uom == self.alt_uom:
            if factor == 0:
                raise ZeroDivisionError("alt_factor cannot be zero.")
            return qty / factor

        raise ValueError("Unsupported conversion for this product (unit is not linked).")

    def to_base(self, qty, uom=None):
        """
        Always return quantity in base_uom.
        If uom is None, assume qty is already in base_uom.
        """
        if qty is None:
            return None

        if uom is None or uom == self.base_uom:
            return Decimal(qty)

        return self.convert_qty(qty=qty, from_uom=uom, to_uom=self.base_uom)

    def to_alt(self, qty, uom=None):
        """
        Return quantity in alt_uom (if configured).
        If uom is None, assume qty is in base_uom.
        """
        if qty is None:
            return None

        if not self.alt_uom:
            raise ValueError("No alternative unit configured for this product.")

        from_uom = uom or self.base_uom
        return self.convert_qty(qty=qty, from_uom=from_uom, to_uom=self.alt_uom)

    def qty_to_weight(self, qty, qty_uom=None):
        """
        Convert any quantity (base or alt) to weight in 'weight_uom'.

        Steps:
        1) Convert qty to base_uom.
        2) Multiply by weight_per_base to get weight.
        """
        if qty is None:
            return None

        if self.weight_uom is None or self.weight_per_base is None:
            raise ValueError("Weight is not configured for this product.")

        qty_base = self.to_base(qty=qty, uom=qty_uom)
        return qty_base * Decimal(self.weight_per_base)

    def weight_to_qty(self, weight, to_uom=None):
        """
        Convert a weight (in 'weight_uom') back to quantity (base or alt).

        Steps:
        1) Compute quantity in base_uom: qty_base = weight / weight_per_base
        2) If to_uom is alt_uom, convert base -> alt
        """
        if weight is None:
            return None

        if self.weight_uom is None or self.weight_per_base is None:
            raise ValueError("Weight is not configured for this product.")

        weight = Decimal(weight)

        if self.weight_per_base == 0:
            raise ZeroDivisionError("weight_per_base cannot be zero.")

        qty_base = weight / Decimal(self.weight_per_base)

        if to_uom is None or to_uom == self.base_uom:
            return qty_base

        if to_uom == self.alt_uom:
            return self.convert_qty(
                qty=qty_base,
                from_uom=self.base_uom,
                to_uom=self.alt_uom,
            )

        raise ValueError("Unsupported target unit for this product.")

    # ============================
    # Inventory helpers
    # ============================

    @property
    def total_on_hand(self) -> Decimal:
        """
        Total quantity on hand across all warehouses/locations.

        Uses StockLevel -> related_name="stock_levels".
        """
        agg = self.stock_levels.aggregate(total=Sum("quantity_on_hand"))
        return agg["total"] or Decimal("0.000")

    def low_stock_levels(self):
        """
        Returns queryset of StockLevel rows where this product
        is below the minimum stock (per warehouse/location).
        """
        return self.stock_levels.filter(
            min_stock__gt=Decimal("0.000"),
            quantity_on_hand__lt=F("min_stock"),
        )

    @property
    def has_low_stock_anywhere(self) -> bool:
        """
        True if this product is below min stock in any warehouse/location.
        """
        return self.low_stock_levels().exists()

    def total_on_hand_in_warehouse(self, warehouse) -> Decimal:
        """
        Quantity on hand for this product in a specific warehouse.
        """
        agg = self.stock_levels.filter(warehouse=warehouse).aggregate(
            total=Sum("quantity_on_hand")
        )
        return agg["total"] or Decimal("0.000")

    def has_stock(self, warehouse=None) -> bool:
        """
        Returns True if there is any stock for this product.

        - If warehouse is provided: check only that warehouse.
        - Otherwise: check total_on_hand across all warehouses.
        """
        if warehouse is not None:
            return self.total_on_hand_in_warehouse(warehouse) > Decimal("0.000")
        return self.total_on_hand > Decimal("0.000")

    def can_be_deleted(self) -> bool:
        """
        Simple rule: product can be deleted if it has no stock moves.

        You can later extend this to check orders/invoices, etc.
        """
        return not self.stock_moves.exists()



# ============================================================
# Warehouses
# ============================================================

class Warehouse(TimeStampedModel):
    """
    Physical / logical warehouse.
    Example: Main Warehouse, Showroom, External Storage.
    """

    code = models.CharField(
        max_length=20,
        unique=True,
        verbose_name=_("Warehouse code"),
        help_text=_("Short code, e.g. WH-MCT."),
    )

    name = models.CharField(
        max_length=200,
        verbose_name=_("Warehouse name"),
    )

    description = models.TextField(
        blank=True,
        verbose_name=_("Description"),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active"),
    )

    objects = WarehouseManager()

    class Meta:
        verbose_name = _("Warehouse")
        verbose_name_plural = _("Warehouses")
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} – {self.name}"

    @property
    def stock_levels_qs(self):
        """
        All stock levels for this warehouse with related product and location.

        Note:
        We use 'stock_levels_qs' to avoid shadowing the reverse relation
        'stock_levels' from StockLevel.related_name.
        """
        return (
            self.stock_levels  # ← هذا الآن هو الـ reverse manager الحقيقي
            .select_related("product", "location")
            .all()
        )

    @property
    def total_quantity_on_hand(self) -> Decimal:
        """
        إجمالي الكمية المتوفرة في هذا المستودع (كل المنتجات وكل المواقع).
        """
        agg = self.stock_levels.aggregate(total=Sum("quantity_on_hand"))
        return agg["total"] or Decimal("0")

    @property
    def low_stock_count(self) -> int:
        """
        عدد الأصناف التي تحت الحد الأدنى min_stock.
        """
        return self.stock_levels.filter(
            min_stock__gt=0,
            quantity_on_hand__lt=F("min_stock"),
        ).count()

    @property
    def has_low_stock(self) -> bool:
        """
        هل يوجد أي صنف منخفض المخزون في هذا المستودع؟
        """
        return self.low_stock_count > 0


# ============================================================
# Stock locations
# ============================================================

class StockLocation(TimeStampedModel):
    """
    Locations inside / related to a warehouse.
    Example types:
      - Internal stock location
      - Supplier
      - Customer
      - Scrap
    """

    class LocationType(models.TextChoices):
        INTERNAL = "internal", _("Internal")
        SUPPLIER = "supplier", _("Supplier")
        CUSTOMER = "customer", _("Customer")
        SCRAP = "scrap", _("Scrap")
        TRANSIT = "transit", _("Transit")

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="locations",
        verbose_name=_("Warehouse"),
    )

    code = models.CharField(
        max_length=30,
        verbose_name=_("Location code"),
        help_text=_("Short code, e.g. STOCK, SCRAP, SHOWROOM."),
    )

    name = models.CharField(
        max_length=200,
        verbose_name=_("Location name"),
    )

    type = models.CharField(
        max_length=20,
        choices=LocationType.choices,
        default=LocationType.INTERNAL,
        verbose_name=_("Location type"),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active"),
    )
    objects = StockLocationManager()

    class Meta:
        verbose_name = _("Stock location")
        verbose_name_plural = _("Stock locations")
        unique_together = ("warehouse", "code")
        ordering = ("warehouse__code", "code")

    def __str__(self) -> str:
        return f"{self.warehouse.code}/{self.code} – {self.name}"


# ============================================================
# Stock moves
# ============================================================

class StockMove(NumberedModel):
    """
    Single stock movement from a source location to a destination location.
    You can later link it to PurchaseOrder, SalesOrder, Manufacturing, etc.

    Important:
    - Stored quantity is in whatever UoM the user selected (uom field).
    - For updating StockLevel we should always convert to product.base_uom
      using product.to_base(...) (see get_base_quantity()).
    """

    class MoveType(models.TextChoices):
        IN = "in", _("Incoming")
        OUT = "out", _("Outgoing")
        TRANSFER = "transfer", _("Transfer")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        DONE = "done", _("Done")
        CANCELLED = "cancelled", _("Cancelled")

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="stock_moves",
        verbose_name=_("Product"),
    )

    move_type = models.CharField(
        max_length=20,
        choices=MoveType.choices,
        default=MoveType.IN,
        verbose_name=_("Move type"),
    )

    from_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="outgoing_moves",
        verbose_name=_("From warehouse"),
    )

    from_location = models.ForeignKey(
        StockLocation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="outgoing_moves",
        verbose_name=_("From location"),
    )

    to_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="incoming_moves",
        verbose_name=_("To warehouse"),
    )

    to_location = models.ForeignKey(
        StockLocation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="incoming_moves",
        verbose_name=_("To location"),
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name=_("Quantity"),
    )


    # 🔴 كان CharField, الآن ForeignKey على UnitOfMeasure
    uom = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name="stock_moves",
        verbose_name=_("Unit of measure"),
        help_text=_(
            "Unit of measure used for this move "
            "(must be base or alternative UoM of the product)."
        ),
        null=True,   # ✅ مؤقتاً عشان نعدي مرحلة المايغريشن بدون مشكلة
        blank=True,  # ✅
    )


    move_date = models.DateTimeField(
        default=timezone.now,
        verbose_name=_("Move date"),
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name=_("Status"),
    )

    reference = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Reference"),
        help_text=_("Optional external reference, e.g. PO/2025/0001."),
    )

    note = models.TextField(
        blank=True,
        verbose_name=_("Note"),
    )

    objects = StockMoveManager()

    class Meta:
        verbose_name = _("Stock move")
        verbose_name_plural = _("Stock moves")
        ordering = ("-move_date", "-id")

    # ============================
    # Numbering context
    # ============================

    def get_numbering_context(self) -> dict:
        """
        نضيف prefix حسب نوع الحركة:
          - IN       → من إعدادات المخزون
          - OUT      → من إعدادات المخزون
          - TRANSFER → من إعدادات المخزون

        هذا الـ prefix يُستخدم في pattern مثل: {prefix}-{seq:05d}
        """
        from inventory.models import InventorySettings  # import محلي

        # نأخذ أي سياق أساسي من NumberedModel (لو موجود)
        try:
            ctx = super().get_numbering_context() or {}
        except AttributeError:
            ctx = {}

        settings = InventorySettings.get_solo()

        prefix_map = {
            self.MoveType.IN: settings.stock_move_in_prefix or "IN",
            self.MoveType.OUT: settings.stock_move_out_prefix or "OUT",
            self.MoveType.TRANSFER: settings.stock_move_transfer_prefix or "TRF",
        }

        ctx["prefix"] = prefix_map.get(self.move_type, "MV")
        return ctx

    def __str__(self) -> str:
        # نعرض كود المنتج + الكمية + كود وحدة القياس
        uom_code = self.uom.code if self.uom_id else "?"
        return f"{self.product.code}: {self.quantity} {uom_code}"

    # ============================
    # Validation
    # ============================

    def clean(self):
        super().clean()

        if self.quantity is None or self.quantity <= 0:
            raise ValidationError(_("Quantity must be greater than zero."))

        # تأكد من الحقول المطلوبة حسب نوع الحركة
        if self.move_type == self.MoveType.IN:
            if not self.to_warehouse or not self.to_location:
                raise ValidationError(_("Incoming move requires destination warehouse and location."))
            if self.from_warehouse or self.from_location:
                raise ValidationError(_("Incoming move should not have source warehouse/location."))

        elif self.move_type == self.MoveType.OUT:
            if not self.from_warehouse or not self.from_location:
                raise ValidationError(_("Outgoing move requires source warehouse and location."))
            if self.to_warehouse or self.to_location:
                raise ValidationError(_("Outgoing move should not have destination warehouse/location."))

        elif self.move_type == self.MoveType.TRANSFER:
            if not (self.from_warehouse and self.from_location and self.to_warehouse and self.to_location):
                raise ValidationError(_("Transfer move requires both source and destination."))

            if self.from_location.warehouse_id != self.from_warehouse_id:
                raise ValidationError(_("Source location must belong to source warehouse."))
            if self.to_location.warehouse_id != self.to_warehouse_id:
                raise ValidationError(_("Destination location must belong to destination warehouse."))

        # ✅ تأكد أن الـ UoM المختارة متوافقة مع المنتج:
        if self.product_id and self.uom_id:
            allowed_uoms = [self.product.base_uom]
            if self.product.alt_uom:
                allowed_uoms.append(self.product.alt_uom)
            # هنا عمداً ما نسمح بوحدة الوزن لحركة المخزون (نخزن المخزون دائماً بوحدة الكمية)
            if self.uom not in allowed_uoms:
                raise ValidationError(
                    _("Selected unit of measure is not configured for this product (must be base or alternative UoM).")
                )

    # ============================
    # Helpers
    # ============================

    @property
    def is_done(self) -> bool:
        return self.status == self.Status.DONE

    def get_base_quantity(self) -> Decimal:
        """
        Return quantity of this move converted to product.base_uom.

        This should be used when updating StockLevel.quantity_on_hand so that
        all stock levels are stored in a single consistent UoM (the base_uom).
        """
        return self.product.to_base(self.quantity, uom=self.uom)

    def save(self, *args, **kwargs):
        """
        Override save to ربط تعديل المخزون بحالة الحركة (status).

        المنطق:
          - إذا كانت حركة جديدة (بدون pk):
              * لو status = DONE → نطبّق تأثير الحركة على المخزون.
              * غير ذلك → لا شيء.
          - إذا كانت حركة موجودة:
              * نقرأ الحالة القديمة من قاعدة البيانات.
              * نستدعي خدمة apply_stock_move_status_change لتطبيق فرق الحالة.
        """
        from .services import apply_stock_move_status_change  # import محلي لتجنّب circular import

        is_create = self.pk is None
        old_status = None

        if not is_create:
            try:
                old_status = self.__class__.objects.only("status").get(pk=self.pk).status
            except self.__class__.DoesNotExist:
                is_create = True
                old_status = None

        super().save(*args, **kwargs)

        apply_stock_move_status_change(move=self, old_status=old_status, is_create=is_create)




# ============================================================
# Stock levels
# ============================================================

class StockLevel(TimeStampedModel):
    """
    Current stock level per (product, warehouse, location).

    - warehouse مكرر هنا رغم أنه موجود في StockLocation، حتى نسهل الاستعلامات
      ونعمل aggregate على مستوى المخزن مباشرة بدون join مع location.
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="stock_levels",
        verbose_name=_("Product"),
    )

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="stock_levels",
        verbose_name=_("Warehouse"),
    )

    location = models.ForeignKey(
        StockLocation,
        on_delete=models.PROTECT,
        related_name="stock_levels",
        verbose_name=_("Location inside warehouse"),
    )

    # الكمية الفعلية على الرف
    quantity_on_hand = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("0.000"),
        verbose_name=_("Quantity on hand"),
    )

    # كمية محجوزة (للأوامر) – مستقبلية
    quantity_reserved = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("0.000"),
        verbose_name=_("Reserved quantity"),
    )

    # حد إعادة الطلب / الحد الأدنى المقبول
    min_stock = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("0.000"),
        verbose_name=_("Minimum stock"),
    )

    objects = StockLevelManager()

    class Meta:
        verbose_name = _("Stock level")
        verbose_name_plural = _("Stock levels")
        unique_together = ("product", "warehouse", "location")

    def __str__(self):
        return f"{self.product} @ {self.warehouse} / {self.location}"

    @property
    def qty(self):
        """
        Backwards-compatible alias for quantity_on_hand.
        """
        return self.quantity_on_hand

    # الحقول موجودة عندك هنا

    # ============================
    # خصائص مساعدة
    # ============================

    @property
    def available_quantity(self) -> Decimal:
        """
        Available quantity = on_hand - reserved.
        """
        return (self.quantity_on_hand or Decimal("0.000")) - (
                self.quantity_reserved or Decimal("0.000")
        )

    @property
    def is_below_min(self) -> bool:
        """
        Is current quantity below configured minimum?
        """
        if not self.min_stock:
            return False
        return self.quantity_on_hand < self.min_stock





class InventorySettings(SingletonModel):
    """
    إعدادات المخزون العامة (منها البادئة لترقيم حركات المخزون).
    """

    stock_move_in_prefix = models.CharField(
        max_length=10,
        default="IN",
        verbose_name=_("بادئة الحركات الواردة (IN)"),
    )
    stock_move_out_prefix = models.CharField(
        max_length=10,
        default="OUT",
        verbose_name=_("بادئة الحركات الصادرة (OUT)"),
    )
    stock_move_transfer_prefix = models.CharField(
        max_length=10,
        default="TRF",
        verbose_name=_("بادئة حركات التحويل (TRANSFER)"),
    )

    class Meta:
        verbose_name = _("إعدادات المخزون")

    def __str__(self) -> str:
        return "Inventory settings"