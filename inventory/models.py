# inventory/models.py

from __future__ import annotations

from decimal import Decimal, ROUND_UP
from pathlib import Path
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from solo.models import SingletonModel

from core.models import BaseModel
from uom.models import UnitOfMeasure

from inventory.managers import (
    ProductCategoryManager,
    ProductManager,
    StockLocationManager,
    StockMoveManager,
    StockLevelManager,
    WarehouseManager,
    ReorderRuleManager,
    StockMoveLineManager,
    InventoryAdjustmentManager,
    InventoryAdjustmentLineManager,
)

# ============================================================
# Constants
# ============================================================
DECIMAL_ZERO = Decimal("0.000")
DECIMAL_ONE = Decimal("1.000")


# ============================================================
# Inventory Settings
# ============================================================
class InventorySettings(SingletonModel):
    allow_negative_stock = models.BooleanField(
        default=True,
        verbose_name=_("السماح بالمخزون السالب"),
        help_text=_("إذا تم تفعيله، يمكن تأكيد حركات الصرف حتى لو لم تتوفر كمية كافية."),
    )

    stock_move_in_prefix = models.CharField(max_length=10, default="IN", verbose_name=_("بادئة الحركات الواردة"))
    stock_move_out_prefix = models.CharField(max_length=10, default="OUT", verbose_name=_("بادئة الحركات الصادرة"))
    stock_move_transfer_prefix = models.CharField(max_length=10, default="TRF", verbose_name=_("بادئة التحويلات"))

    class Meta:
        verbose_name = _("إعدادات المخزون")

    def __str__(self) -> str:
        return "Inventory settings"


# ============================================================
# Product Categories
# ============================================================
class ProductCategory(BaseModel):
    slug = models.SlugField(max_length=120, verbose_name=_("المعرّف (Slug)"))
    name = models.CharField(max_length=200, verbose_name=_("اسم التصنيف"))
    description = models.TextField(blank=True, verbose_name=_("وصف التصنيف"))
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("التصنيف الأب"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("نشط"))

    objects = ProductCategoryManager()

    class Meta:
        verbose_name = _("تصنيف منتج")
        verbose_name_plural = _("تصنيفات المنتجات")
        ordering = ("name",)
        indexes = [
            models.Index(fields=["is_deleted", "is_active"], name="prodcat_del_active_idx"),
            models.Index(fields=["parent"], name="prodcat_parent_idx"),
        ]
        constraints = [
            # slug must be unique among non-deleted categories (PostgreSQL recommended)
            models.UniqueConstraint(
                fields=["slug"],
                condition=Q(is_deleted=False),
                name="uniq_prodcat_slug_visible",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.parent} → {self.name}" if self.parent else self.name

    @property
    def full_path(self) -> str:
        parts = [self.name]
        parent = self.parent
        while parent is not None:
            parts.append(parent.name)
            parent = parent.parent
        parts.reverse()
        return " / ".join(parts)


def product_image_upload_to(instance: "Product", filename: str) -> str:
    safe_code = (instance.code or "unknown").replace("/", "_")
    ext = Path(filename).suffix
    return f"products/{safe_code}/main{ext}"


# ============================================================
# Products
# ============================================================
class Product(BaseModel):
    class ProductType(models.TextChoices):
        STOCKABLE = "stockable", _("صنف مخزني")
        SERVICE = "service", _("خدمة")
        CONSUMABLE = "consumable", _("مستهلكات")

    category = models.ForeignKey(
        "inventory.ProductCategory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name=_("التصنيف"),
    )

    # Master identity
    code = models.CharField(max_length=50, verbose_name=_("كود المنتج (SKU)"))
    barcode = models.CharField(max_length=100, null=True, blank=True, verbose_name=_("الباركود"))

    # Translated via modeltranslation: name, short_description, description
    name = models.CharField(max_length=255, verbose_name=_("اسم المنتج"))
    short_description = models.CharField(max_length=255, blank=True, verbose_name=_("وصف مختصر"))
    description = models.TextField(blank=True, verbose_name=_("وصف تفصيلي"))

    product_type = models.CharField(
        max_length=20,
        choices=ProductType.choices,
        default=ProductType.STOCKABLE,
        verbose_name=_("نوع المنتج"),
    )

    # Pricing & cost
    default_sale_price = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("سعر البيع الافتراضي"),
    )
    average_cost = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("متوسط التكلفة"),
        help_text=_("يتم تحديثه تلقائياً عند التوريد."),
    )

    # UOM
    base_uom = models.ForeignKey(
        "uom.UnitOfMeasure",
        on_delete=models.PROTECT,
        related_name="products_as_base",
        verbose_name=_("وحدة القياس الأساسية"),
    )
    alt_uom = models.ForeignKey(
        "uom.UnitOfMeasure",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="products_as_alt",
        verbose_name=_("وحدة بديلة"),
    )
    alt_factor = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        verbose_name=_("عامل التحويل"),
        help_text=_("كم تساوي 1 وحدة بديلة من الوحدة الأساسية."),
    )

    # Weight
    weight_uom = models.ForeignKey(
        "uom.UnitOfMeasure",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="products_as_weight",
        verbose_name=_("وحدة الوزن"),
    )
    weight_per_base = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        verbose_name=_("الوزن لكل وحدة أساس"),
    )

    # Status/media
    image = models.ImageField(upload_to=product_image_upload_to, null=True, blank=True, verbose_name=_("الصورة"))
    is_active = models.BooleanField(default=True, verbose_name=_("نشط"))
    is_published = models.BooleanField(default=False, verbose_name=_("منشور"))

    objects = ProductManager()

    class Meta:
        verbose_name = _("منتج")
        verbose_name_plural = _("المنتجات")
        ordering = ("code",)
        indexes = [
            models.Index(fields=["is_deleted", "is_active"], name="product_del_active_idx"),
            models.Index(fields=["product_type"], name="product_type_idx"),
            models.Index(fields=["category"], name="product_category_idx"),
        ]
        constraints = [
            # code unique among non-deleted
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_product_code_visible",
            ),
            # barcode unique only when set and non-deleted
            models.UniqueConstraint(
                fields=["barcode"],
                condition=Q(is_deleted=False) & Q(barcode__isnull=False) & ~Q(barcode=""),
                name="uniq_product_barcode_visible_when_set",
            ),
            # non-negative at DB-level
            models.CheckConstraint(
                check=Q(default_sale_price__gte=0),
                name="product_default_sale_price_non_negative",
            ),
            models.CheckConstraint(
                check=Q(average_cost__gte=0),
                name="product_average_cost_non_negative",
            ),
            models.CheckConstraint(
                check=Q(alt_factor__isnull=True) | Q(alt_factor__gt=0),
                name="product_alt_factor_positive_when_set",
            ),
            models.CheckConstraint(
                check=Q(weight_per_base__isnull=True) | Q(weight_per_base__gte=0),
                name="product_weight_non_negative_when_set",
            ),
        ]

    def __str__(self) -> str:
        return f"[{self.code}] {self.name}"

    # -------------------------
    # Derived business flags
    # -------------------------
    @property
    def is_stock_item(self) -> bool:
        return self.product_type in {self.ProductType.STOCKABLE, self.ProductType.CONSUMABLE}

    @property
    def is_service(self) -> bool:
        return self.product_type == self.ProductType.SERVICE

    # -------------------------
    # Validation (domain rules)
    # -------------------------
    def clean(self):
        super().clean()
        errors: dict[str, str] = {}

        if self.default_sale_price is not None and self.default_sale_price < 0:
            errors["default_sale_price"] = _("سعر البيع لا يمكن أن يكون سالباً.")
        if self.average_cost is not None and self.average_cost < 0:
            errors["average_cost"] = _("متوسط التكلفة لا يمكن أن يكون سالباً.")

        if self.alt_uom_id and (self.alt_factor is None or self.alt_factor <= 0):
            errors["alt_factor"] = _("يجب تحديد عامل تحويل صالح للوحدة البديلة.")
        if self.alt_factor is not None and self.alt_factor != 0 and not self.alt_uom_id:
            errors["alt_uom"] = _("لا يمكن تحديد عامل تحويل بدون وحدة بديلة.")

        if self.weight_per_base is not None:
            if self.weight_per_base < 0:
                errors["weight_per_base"] = _("الوزن لكل وحدة أساس لا يمكن أن يكون سالباً.")
            if not self.weight_uom_id:
                errors["weight_uom"] = _("يجب تحديد وحدة الوزن.")

        # Service rules (strict default)
        if self.is_service:
            if self.weight_uom_id or (self.weight_per_base is not None and self.weight_per_base != 0):
                errors["weight_per_base"] = _("الخدمة لا تحتاج وزن. اترك حقول الوزن فارغة.")
                errors.setdefault("weight_uom", _("الخدمة لا تحتاج وزن."))

        if errors:
            raise ValidationError(errors)

    # -------------------------
    # UOM conversions
    # -------------------------
    def to_base(self, qty: Decimal, uom: Optional["UnitOfMeasure"] = None) -> Decimal:
        qty = Decimal(qty) if qty is not None else Decimal(0)
        if uom is None or uom == self.base_uom:
            return qty
        if uom == self.alt_uom and self.alt_factor:
            return qty * self.alt_factor
        raise ValidationError({"uom": _("وحدة القياس غير مرتبطة بهذا المنتج.")})

    def to_alt(self, qty: Decimal, uom: Optional["UnitOfMeasure"] = None) -> Decimal:
        if not self.alt_uom_id or not self.alt_factor:
            raise ValidationError(_("لا توجد وحدة بديلة مضبوطة لهذا المنتج."))
        qty = Decimal(qty) if qty is not None else Decimal(0)
        from_uom = uom or self.base_uom
        if from_uom == self.alt_uom:
            return qty
        if from_uom == self.base_uom:
            return qty / self.alt_factor
        raise ValidationError({"uom": _("وحدة القياس غير مرتبطة بهذا المنتج.")})

    # -------------------------
    # Stock helpers
    # -------------------------
    @property
    def total_on_hand(self) -> Decimal:
        return self.stock_levels.aggregate(t=Sum("quantity_on_hand"))["t"] or DECIMAL_ZERO

    @property
    def calculated_available_qty(self) -> Decimal:
        total = getattr(self, "total_qty", None)
        reserved = getattr(self, "total_reserved", None)
        total = total if total is not None else DECIMAL_ZERO
        reserved = reserved if reserved is not None else DECIMAL_ZERO
        return total - reserved

    @property
    def image_url(self) -> Optional[str]:
        return getattr(self.image, "url", None) if self.image else None


# ============================================================
# Warehouses
# ============================================================
class Warehouse(BaseModel):
    code = models.CharField(max_length=20, verbose_name=_("كود المستودع"))
    name = models.CharField(max_length=200, verbose_name=_("اسم المستودع"))
    description = models.TextField(blank=True, verbose_name=_("الوصف"))
    is_active = models.BooleanField(default=True, verbose_name=_("نشط"))

    objects = WarehouseManager()

    class Meta:
        verbose_name = _("مستودع")
        verbose_name_plural = _("المستودعات")
        ordering = ("code",)
        indexes = [
            models.Index(fields=["is_deleted", "is_active"], name="warehouse_del_active_idx"),
            models.Index(fields=["code"], name="warehouse_code_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_warehouse_code_visible",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} – {self.name}"


# ============================================================
# Stock Locations
# ============================================================
class StockLocation(BaseModel):
    class LocationType(models.TextChoices):
        INTERNAL = "internal", _("داخلي")
        SUPPLIER = "supplier", _("مورد")
        CUSTOMER = "customer", _("عميل")
        SCRAP = "scrap", _("تالفة")
        TRANSIT = "transit", _("قيد النقل")

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="locations",
        verbose_name=_("المستودع"),
    )
    code = models.CharField(max_length=30, verbose_name=_("كود الموقع"))
    name = models.CharField(max_length=200, verbose_name=_("اسم الموقع"))
    type = models.CharField(
        max_length=20,
        choices=LocationType.choices,
        default=LocationType.INTERNAL,
        verbose_name=_("نوع الموقع"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("نشط"))

    objects = StockLocationManager()

    class Meta:
        verbose_name = _("موقع مخزون")
        verbose_name_plural = _("مواقع المخزون")
        ordering = ("warehouse__code", "code")
        indexes = [
            models.Index(fields=["is_deleted", "is_active"], name="location_del_active_idx"),
            models.Index(fields=["warehouse"], name="location_wh_idx"),
            models.Index(fields=["type"], name="location_type_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "code"],
                condition=Q(is_deleted=False),
                name="uniq_location_wh_code_visible",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.warehouse.code}/{self.code}"


# ============================================================
# Stock Moves (Header)
# ============================================================
class StockMove(BaseModel):
    class MoveType(models.TextChoices):
        IN = "in", _("حركة واردة")
        OUT = "out", _("حركة صادرة")
        TRANSFER = "transfer", _("تحويل داخلي")

    class Status(models.TextChoices):
        DRAFT = "draft", _("مسودة")
        DONE = "done", _("منفذة")
        CANCELLED = "cancelled", _("ملغاة")

    move_type = models.CharField(
        max_length=20,
        choices=MoveType.choices,
        default=MoveType.IN,
        verbose_name=_("نوع الحركة"),
    )
    adjustment = models.ForeignKey(
        "inventory.InventoryAdjustment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_moves",
        verbose_name=_("وثيقة الجرد المرتبطة"),
    )

    from_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="outgoing_moves",
        verbose_name=_("من مستودع"),
    )
    from_location = models.ForeignKey(
        "inventory.StockLocation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="outgoing_moves",
        verbose_name=_("من موقع"),
    )

    to_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="incoming_moves",
        verbose_name=_("إلى مستودع"),
    )
    to_location = models.ForeignKey(
        "inventory.StockLocation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="incoming_moves",
        verbose_name=_("إلى موقع"),
    )

    move_date = models.DateTimeField(default=timezone.now, verbose_name=_("تاريخ الحركة"))
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, verbose_name=_("الحالة"))
    reference = models.CharField(max_length=255, blank=True, verbose_name=_("مرجع خارجي"))
    note = models.TextField(blank=True, verbose_name=_("ملاحظات"))

    objects = StockMoveManager()

    class Meta:
        verbose_name = _("حركة مخزون")
        verbose_name_plural = _("حركات المخزون")
        ordering = ("-move_date", "-id")
        indexes = [
            models.Index(fields=["is_deleted", "status"], name="stockmove_del_status_idx"),
            models.Index(fields=["move_type"], name="stockmove_type_idx"),
            models.Index(fields=["move_date"], name="stockmove_date_idx"),
            models.Index(fields=["reference"], name="stockmove_reference_idx"),
        ]

    def __str__(self) -> str:
        ref = f"[{self.reference}] " if self.reference else ""
        return f"{ref}{self.get_move_type_display()} #{self.pk}"

    def clean(self):
        super().clean()
        errors: dict[str, str] = {}

        if self.move_type == self.MoveType.IN:
            if not self.to_warehouse_id or not self.to_location_id:
                errors["to_warehouse"] = _("الحركة الواردة تتطلب تحديد مستودع وجهة.")
                errors["to_location"] = _("الحركة الواردة تتطلب تحديد موقع وجهة.")
            if self.from_warehouse_id or self.from_location_id:
                errors["from_warehouse"] = _("الحركة الواردة لا يجب أن تحتوي على مصدر.")
                errors["from_location"] = _("الحركة الواردة لا يجب أن تحتوي على مصدر.")

        elif self.move_type == self.MoveType.OUT:
            if not self.from_warehouse_id or not self.from_location_id:
                errors["from_warehouse"] = _("الحركة الصادرة تتطلب تحديد مستودع مصدر.")
                errors["from_location"] = _("الحركة الصادرة تتطلب تحديد موقع مصدر.")
            if self.to_warehouse_id or self.to_location_id:
                errors["to_warehouse"] = _("الحركة الصادرة لا يجب أن تحتوي على وجهة.")
                errors["to_location"] = _("الحركة الصادرة لا يجب أن تحتوي على وجهة.")

        elif self.move_type == self.MoveType.TRANSFER:
            if not (self.from_warehouse_id and self.from_location_id and self.to_warehouse_id and self.to_location_id):
                errors["from_warehouse"] = _("التحويل يتطلب تحديد مصدر ووجهة.")
            if self.from_warehouse_id == self.to_warehouse_id and self.from_location_id == self.to_location_id:
                errors["to_location"] = _("لا يمكن تحويل المخزون لنفس الموقع.")

        if self.from_location_id and self.from_warehouse_id:
            if self.from_location.warehouse_id != self.from_warehouse_id:
                errors["from_location"] = _("موقع المصدر لا يتبع نفس مستودع المصدر.")
        if self.to_location_id and self.to_warehouse_id:
            if self.to_location.warehouse_id != self.to_warehouse_id:
                errors["to_location"] = _("موقع الوجهة لا يتبع نفس مستودع الوجهة.")

        if errors:
            raise ValidationError(errors)

    @property
    def is_done(self) -> bool:
        return self.status == self.Status.DONE


# ============================================================
# Stock Move Lines
# ============================================================
class StockMoveLine(BaseModel):
    move = models.ForeignKey(StockMove, on_delete=models.CASCADE, related_name="lines", verbose_name=_("الحركة"))
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_moves", verbose_name=_("المنتج"))
    quantity = models.DecimalField(max_digits=12, decimal_places=3, verbose_name=_("الكمية"))
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, verbose_name=_("وحدة القياس"))
    cost_price = models.DecimalField(max_digits=12, decimal_places=3, default=DECIMAL_ZERO, verbose_name=_("تكلفة الوحدة"))

    objects = StockMoveLineManager()

    class Meta:
        verbose_name = _("بند حركة")
        verbose_name_plural = _("بنود الحركة")
        indexes = [
            models.Index(fields=["is_deleted", "move"], name="stockmoveline_del_move_idx"),
            models.Index(fields=["product", "move"], name="stockmoveline_prod_move_idx"),
        ]
        constraints = [
            models.CheckConstraint(check=Q(quantity__gt=0), name="stockmoveline_qty_gt_zero"),
            models.CheckConstraint(check=Q(cost_price__gte=0), name="stockmoveline_cost_non_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.product.code} - {self.quantity} {self.uom}"

    def clean(self):
        super().clean()
        errors: dict[str, str] = {}

        if self.quantity is None or self.quantity <= 0:
            errors["quantity"] = _("الكمية يجب أن تكون أكبر من صفر.")
        if self.cost_price is not None and self.cost_price < 0:
            errors["cost_price"] = _("تكلفة الوحدة لا يمكن أن تكون سالبة.")

        if self.product_id and self.uom_id:
            allowed_ids = {self.product.base_uom_id}
            if self.product.alt_uom_id:
                allowed_ids.add(self.product.alt_uom_id)
            if self.uom_id not in allowed_ids:
                errors["uom"] = _("وحدة القياس غير صحيحة لهذا المنتج.")

        if errors:
            raise ValidationError(errors)

    def get_base_quantity(self) -> Decimal:
        return self.product.to_base(self.quantity, self.uom)

    @property
    def line_total_cost(self) -> Decimal:
        return (self.quantity or DECIMAL_ZERO) * (self.cost_price or DECIMAL_ZERO)


# ============================================================
# Stock Levels
# ============================================================
class StockLevel(BaseModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock_levels", verbose_name=_("المنتج"))
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="stock_levels", verbose_name=_("المستودع"))
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="stock_levels", verbose_name=_("الموقع"))

    quantity_on_hand = models.DecimalField(max_digits=12, decimal_places=3, default=DECIMAL_ZERO, verbose_name=_("الكمية المتوفرة"))
    quantity_reserved = models.DecimalField(max_digits=12, decimal_places=3, default=DECIMAL_ZERO, verbose_name=_("الكمية المحجوزة"))
    min_stock = models.DecimalField(max_digits=12, decimal_places=3, default=DECIMAL_ZERO, verbose_name=_("الحد الأدنى (Legacy)"))

    objects = StockLevelManager()

    class Meta:
        verbose_name = _("رصيد مخزون")
        verbose_name_plural = _("أرصدة المخزون")
        indexes = [
            models.Index(fields=["is_deleted", "warehouse"], name="stocklevel_del_wh_idx"),
            models.Index(fields=["product", "warehouse", "location"], name="stocklevel_prod_wh_loc_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "warehouse", "location"],
                condition=Q(is_deleted=False),
                name="uniq_stocklevel_prod_wh_loc_visible",
            ),
            models.CheckConstraint(check=Q(quantity_reserved__gte=0), name="stocklevel_reserved_non_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.product} @ {self.location} = {self.quantity_on_hand}"

    def clean(self):
        super().clean()
        if self.location_id and self.warehouse_id:
            if self.location.warehouse_id != self.warehouse_id:
                raise ValidationError({"location": _("الموقع المختار لا يتبع نفس المستودع.")})

    @property
    def qty(self) -> Decimal:
        return self.quantity_on_hand

    @property
    def available_quantity(self) -> Decimal:
        return (self.quantity_on_hand or DECIMAL_ZERO) - (self.quantity_reserved or DECIMAL_ZERO)


# ============================================================
# Reorder Rules
# ============================================================
class ReorderRule(BaseModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reorder_rules", verbose_name=_("المنتج"))
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="reorder_rules", verbose_name=_("المستودع"))
    location = models.ForeignKey(
        StockLocation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reorder_rules",
        verbose_name=_("الموقع (اختياري)"),
    )

    min_qty = models.DecimalField(max_digits=12, decimal_places=3, default=DECIMAL_ZERO, verbose_name=_("الحد الأدنى"))
    target_qty = models.DecimalField(max_digits=12, decimal_places=3, default=DECIMAL_ZERO, verbose_name=_("الكمية المستهدفة"))
    multiple_of = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True, verbose_name=_("مضاعفات الكمية"))
    lead_time_days = models.PositiveIntegerField(default=0, verbose_name=_("مدة التوريد (أيام)"))
    is_active = models.BooleanField(default=True, verbose_name=_("نشطة"))

    objects = ReorderRuleManager()

    class Meta:
        verbose_name = _("قاعدة إعادة طلب")
        verbose_name_plural = _("قواعد إعادة الطلب")
        indexes = [
            models.Index(fields=["is_deleted", "is_active"], name="reorder_del_active_idx"),
            models.Index(fields=["product", "warehouse"], name="reorder_prod_wh_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "warehouse", "location"],
                condition=Q(is_deleted=False),
                name="uniq_reorder_rule_visible",
            ),
            models.CheckConstraint(check=Q(min_qty__gte=0), name="reorder_min_qty_non_negative"),
            models.CheckConstraint(check=Q(target_qty__gte=0), name="reorder_target_qty_non_negative"),
            models.CheckConstraint(
                check=Q(multiple_of__isnull=True) | Q(multiple_of__gt=0),
                name="reorder_multiple_positive_when_set",
            ),
        ]

    def __str__(self) -> str:
        loc_label = f" / {self.location.code}" if self.location_id else ""
        return f"{self.product.code} @ {self.warehouse.code}{loc_label}"

    @property
    def current_stock(self) -> Decimal:
        if self.location_id:
            level = StockLevel.objects.filter(
                product_id=self.product_id,
                warehouse_id=self.warehouse_id,
                location_id=self.location_id,
            ).values("quantity_on_hand").first()
            return level["quantity_on_hand"] if level else DECIMAL_ZERO

        total = StockLevel.objects.filter(
            product_id=self.product_id,
            warehouse_id=self.warehouse_id,
        ).aggregate(t=Sum("quantity_on_hand"))["t"]
        return total if total is not None else DECIMAL_ZERO

    def get_recommended_qty(self) -> Decimal:
        target = self.target_qty or DECIMAL_ZERO
        current = self.current_stock or DECIMAL_ZERO
        diff = target - current

        if diff <= 0:
            return DECIMAL_ZERO

        if self.multiple_of and self.multiple_of > 0:
            mult = Decimal(self.multiple_of)
            q = (diff / mult).quantize(Decimal("1."), rounding=ROUND_UP)
            return q * mult

        return diff

    @property
    def is_below_min(self) -> bool:
        return (self.current_stock or DECIMAL_ZERO) < (self.min_qty or DECIMAL_ZERO)


# ============================================================
# Inventory Adjustments
# ============================================================
class InventoryAdjustment(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("مسودة")
        IN_PROGRESS = "in_progress", _("قيد المراجعة")
        APPLIED = "applied", _("تم الترحيل")
        CANCELLED = "cancelled", _("ملغاة")

    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="adjustments", verbose_name=_("المستودع"))
    date = models.DateField(default=timezone.localdate, verbose_name=_("تاريخ الجرد"))
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, verbose_name=_("الحالة"))
    category = models.ForeignKey(ProductCategory, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("نطاق التصنيف"))
    location = models.ForeignKey(StockLocation, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_("نطاق الموقع"))
    note = models.TextField(blank=True, verbose_name=_("ملاحظات"))

    objects = InventoryAdjustmentManager()

    class Meta:
        verbose_name = _("وثيقة جرد")
        verbose_name_plural = _("وثائق الجرد")
        ordering = ("-date", "-id")
        indexes = [
            models.Index(fields=["is_deleted", "warehouse"], name="invadj_del_wh_idx"),
            models.Index(fields=["warehouse", "date"], name="invadj_wh_date_idx"),
            models.Index(fields=["status"], name="invadj_status_idx"),
        ]

    def __str__(self) -> str:
        return f"INV-ADJ #{self.pk} ({self.warehouse})"

    @property
    def is_applied(self) -> bool:
        return self.status == self.Status.APPLIED


class InventoryAdjustmentLine(BaseModel):
    adjustment = models.ForeignKey(InventoryAdjustment, on_delete=models.CASCADE, related_name="lines", verbose_name=_("وثيقة الجرد"))
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name=_("المنتج"))
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, verbose_name=_("الموقع المحدد"))
    theoretical_qty = models.DecimalField(max_digits=12, decimal_places=3, verbose_name=_("الكمية النظرية"))
    counted_qty = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True, verbose_name=_("الكمية الفعلية"))

    objects = InventoryAdjustmentLineManager()

    class Meta:
        verbose_name = _("بند جرد")
        verbose_name_plural = _("بنود الجرد")
        indexes = [
            models.Index(fields=["is_deleted", "adjustment"], name="invadjline_del_adj_idx"),
            models.Index(fields=["product"], name="invadjline_product_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["adjustment", "product", "location"],
                condition=Q(is_deleted=False),
                name="uniq_inv_adj_line_visible",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product} @ {self.location} (Theo: {self.theoretical_qty})"

    @property
    def difference(self) -> Optional[Decimal]:
        if self.counted_qty is None:
            return None
        return self.counted_qty - self.theoretical_qty
