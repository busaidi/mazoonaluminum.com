# inventory/models.py

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum, F
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


from core.models import TimeStampedModel


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
        verbose_name=_("Slug"),
        help_text=_("URL-safe identifier, e.g. mazoon-46-system"),
    )

    name = models.CharField(
        max_length=200,
        verbose_name=_("Category name"),
    )

    description = models.TextField(
        blank=True,
        verbose_name=_("Description"),
    )

    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("Parent category"),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active"),
    )

    class Meta:
        verbose_name = _("Product category")
        verbose_name_plural = _("Product categories")
        ordering = ("name",)

    def __str__(self) -> str:
        if self.parent:
            return f"{self.parent} → {self.name}"
        return self.name


# ============================================================
# Products
# ============================================================

class Product(TimeStampedModel):
    """
    Core inventory product.
    This is the master product used by inventory / orders / invoices.
    Website / portal visibility is controlled by `is_published`.
    """

    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name=_("Category"),
    )

    # Internal product code / SKU
    code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_("Product code"),
        help_text=_("Internal code / SKU, e.g. MZN-46-FRAME."),
    )

    # Name/description (يمكن لاحقاً ربطها بـ django-modeltranslation)
    name = models.CharField(
        max_length=255,
        verbose_name=_("Product name"),
    )

    short_description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Short description"),
        help_text=_("One-line description shown in lists."),
    )

    description = models.TextField(
        blank=True,
        verbose_name=_("Full description"),
    )

    # Unit of measure (base)
    uom = models.CharField(
        max_length=20,
        default="PCS",
        verbose_name=_("Unit of measure"),
        help_text=_("Example: PCS, M, KG, SET."),
    )

    # Is this tracked in stock?
    is_stock_item = models.BooleanField(
        default=True,
        verbose_name=_("Stock item"),
        help_text=_("If disabled, stock will not be tracked for this product."),
    )

    # Status flags
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active"),
        help_text=_("If disabled, product is not used in new documents."),
    )

    # نشر المنتج على البورتال / الموقع
    is_published = models.BooleanField(
        default=False,
        verbose_name=_("Published"),
        help_text=_("If enabled, product can appear on website / portal."),
    )

    class Meta:
        verbose_name = _("Product")
        verbose_name_plural = _("Products")
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} – {self.name}"


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

    class Meta:
        verbose_name = _("Warehouse")
        verbose_name_plural = _("Warehouses")
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} – {self.name}"

    @property
    def stock_levels(self):
        """
        كل مستويات المخزون المرتبطة بهذا المستودع.
        نستخدم select_related لتقليل الاستعلامات في القوالب.
        """
        return (
            self.stock_levels
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

class StockMove(TimeStampedModel):
    """
    Single stock movement from a source location to a destination location.
    You can later link it to PurchaseOrder, SalesOrder, Manufacturing, etc.
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

    uom = models.CharField(
        max_length=20,
        verbose_name=_("Unit of measure"),
        help_text=_("Usually copied from product.uom."),
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

    class Meta:
        verbose_name = _("Stock move")
        verbose_name_plural = _("Stock moves")
        ordering = ("-move_date", "-id")

    def __str__(self) -> str:
        return f"{self.product.code}: {self.quantity} {self.uom}"

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

    @property
    def is_done(self) -> bool:
        return self.status == self.Status.DONE


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
    def is_below_min(self) -> bool:
        """
        هل الكمية الحالية أقل من الحد الأدنى المحدد لهذا المستوى؟
        """
        if not self.min_stock:
            return False
        return self.quantity_on_hand < self.min_stock
