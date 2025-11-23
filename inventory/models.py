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

    # Name/description (يمكن لاحقاً ربطها بـ django-modeltranslation)
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

    # Unit of measure (base)
    uom = models.CharField(
        max_length=20,
        default="PCS",
        verbose_name=_("وحدة القياس"),
        help_text=_("مثال: PCS, M, KG, SET"),
    )

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

    class Meta:
        verbose_name = _("منتج")
        verbose_name_plural = _("المنتجات")
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} – {self.name}"

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
                # نقرأ الحالة القديمة فقط بدون تحميل كل الحقول
                old_status = self.__class__.objects.only("status").get(pk=self.pk).status
            except self.__class__.DoesNotExist:
                # حالة نادرة جداً، نعاملها كإنشاء جديد
                is_create = True
                old_status = None

        # نحفظ أولاً (حتى يكون عندنا pk وأي تغييرات أخرى)
        super().save(*args, **kwargs)

        # بعدها نطبّق منطق تعديل المخزون بناءً على تغيير الحالة
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
