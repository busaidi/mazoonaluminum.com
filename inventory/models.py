# inventory/models.py

from decimal import Decimal, ROUND_UP
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum, Q  # Removed unused F
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from solo.models import SingletonModel

from core.models import BaseModel
# تأكد من صحة مسار المدراء (Managers)
from inventory.managers import (
    ProductCategoryManager,
    ProductManager,
    StockLocationManager,
    StockMoveManager,
    StockLevelManager,
    WarehouseManager, ReorderRuleManager,
)
from uom.models import UnitOfMeasure

# ============================================================
# ثوابت الأرقام العشرية
# ============================================================
DECIMAL_ZERO = Decimal("0.000")


# ============================================================
# إعدادات المخزون العامة
# ============================================================
class InventorySettings(SingletonModel):
    """
    إعدادات المخزون العامة.
    """

    allow_negative_stock = models.BooleanField(
        default=True,
        verbose_name=_("السماح بالمخزون السالب"),
        help_text=_("إذا تم تفعيله، يمكن للمستخدمين تأكيد حركات صرف حتى لو لم تتوفر كمية كافية."),
    )

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


# ============================================================
# تصنيفات المنتجات
# ============================================================
class ProductCategory(BaseModel):
    """
    شجرة تصنيفات المنتجات.
    """
    slug = models.SlugField(
        max_length=120,
        unique=True,
        verbose_name=_("المعرّف (Slug)"),
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
        # Added indexes for better performance
        indexes = [
            models.Index(fields=["slug"], name="prodcat_slug_idx"),
            models.Index(fields=["is_active"], name="prodcat_active_idx"),
        ]

    def __str__(self) -> str:
        if self.parent:
            return f"{self.parent} → {self.name}"
        return self.name

    @property
    def full_path(self) -> str:
        parts = [self.name]
        parent = self.parent
        while parent is not None:
            parts.append(parent.name)
            parent = parent.parent
        parts.reverse()
        return " / ".join(parts)


# ============================================================
# دالة مسار حفظ صورة المنتج
# ============================================================
def product_image_upload_to(instance: "Product", filename: str) -> str:
    safe_code = (instance.code or "unknown").replace("/", "_")
    ext = Path(filename).suffix
    return f"products/{safe_code}/main{ext}"


# ============================================================
# المنتجات
# ============================================================
class Product(BaseModel):
    """
    المنتج الأساسي.
    """

    class ProductType(models.TextChoices):
        STOCKABLE = "stockable", _("صنف مخزني")
        SERVICE = "service", _("خدمة")
        CONSUMABLE = "consumable", _("مستهلكات")

    # ----------------------------
    # بيانات التعريف
    # ----------------------------
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name=_("التصنيف"),
    )

    code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_("كود المنتج (SKU)"),
        help_text=_("كود داخلي فريد."),
    )

    barcode = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        verbose_name=_("الباركود"),
        help_text=_("EAN-13, UPC, أو أي رمز شريطي."),
    )

    name = models.CharField(
        max_length=255,
        verbose_name=_("اسم المنتج"),
    )

    short_description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("وصف مختصر"),
    )

    description = models.TextField(
        blank=True,
        verbose_name=_("وصف تفصيلي"),
    )

    product_type = models.CharField(
        max_length=20,
        choices=ProductType.choices,
        default=ProductType.STOCKABLE,
        verbose_name=_("نوع المنتج"),
    )

    # ----------------------------
    # التسعير والتكلفة
    # ----------------------------
    default_sale_price = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("سعر البيع الافتراضي"),
    )

    # متوسط التكلفة المحسوب
    average_cost = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("متوسط التكلفة"),
        help_text=_("يتم تحديثه تلقائياً عند التوريد بناءً على المتوسط المرجح."),
    )

    # ----------------------------
    # وحدات القياس (UOM)
    # ----------------------------
    base_uom = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name="products_as_base",
        verbose_name=_("وحدة القياس الأساسية"),
    )

    alt_uom = models.ForeignKey(
        UnitOfMeasure,
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

    # الوزن
    weight_uom = models.ForeignKey(
        UnitOfMeasure,
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

    # ----------------------------
    # الحالة والتحكم
    # ----------------------------
    image = models.ImageField(
        upload_to=product_image_upload_to,
        null=True,
        blank=True,
        verbose_name=_("الصورة"),
    )

    is_stock_item = models.BooleanField(
        default=True,
        verbose_name=_("يُتابَع في المخزون"),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("نشط"),
    )

    is_published = models.BooleanField(
        default=False,
        verbose_name=_("منشور"),
    )

    objects = ProductManager()

    class Meta:
        verbose_name = _("منتج")
        verbose_name_plural = _("المنتجات")
        ordering = ("code",)
        indexes = [
            models.Index(fields=["code"], name="product_code_idx"),
            models.Index(fields=["barcode"], name="product_barcode_idx"),
            models.Index(fields=["is_active"], name="product_active_idx"),
        ]

    def __str__(self) -> str:
        return f"[{self.code}] {self.name}"

    # ============================
    # التحقق (Validation)
    # ============================
    def clean(self):
        super().clean()

        # سعر البيع
        if self.default_sale_price is not None and self.default_sale_price < 0:
            raise ValidationError(_("سعر البيع لا يمكن أن يكون سالباً."))

        # متوسط التكلفة
        if self.average_cost is not None and self.average_cost < 0:
            raise ValidationError(_("متوسط التكلفة لا يمكن أن يكون سالباً."))

        # ربط الوحدة البديلة مع عامل التحويل
        if self.alt_uom and (self.alt_factor is None or self.alt_factor <= 0):
            raise ValidationError(_("يجب تحديد عامل تحويل صالح للوحدة البديلة."))

        if self.alt_factor and not self.alt_uom:
            raise ValidationError(_("لا يمكن تحديد عامل تحويل بدون وحدة بديلة."))

        # وزن لكل وحدة أساس
        if self.weight_per_base is not None:
            if self.weight_per_base < 0:
                raise ValidationError(_("الوزن لكل وحدة أساس لا يمكن أن يكون سالباً."))
            if not self.weight_uom:
                raise ValidationError(
                    _("يجب تحديد وحدة الوزن عند ضبط الوزن لكل وحدة أساس.")
                )

    # ============================
    # دوال مساعدة
    # ============================

    def to_base(self, qty, uom=None) -> Decimal:
        """تحويل الكمية إلى وحدة الأساس."""
        if qty is None:
            return Decimal(0)

        qty = Decimal(qty)
        if uom is None or uom == self.base_uom:
            return qty

        if uom == self.alt_uom and self.alt_factor:
            return qty * self.alt_factor

        raise ValidationError(_("وحدة القياس غير مرتبطة بهذا المنتج."))

    def to_alt(self, qty, uom=None) -> Decimal:
        """
        تحويل الكمية إلى الوحدة البديلة (إن كانت مضبوطة).
        إذا لم تُمرّر uom نفترض أن الكمية بوحدة الأساس.
        """
        if not self.alt_uom or not self.alt_factor:
            raise ValidationError(_("لا توجد وحدة بديلة مضبوطة لهذا المنتج."))

        if qty is None:
            return Decimal(0)

        qty = Decimal(qty)
        from_uom = uom or self.base_uom

        if from_uom == self.alt_uom:
            return qty  # أصلاً بديلة

        if from_uom == self.base_uom:
            if self.alt_factor == 0:
                # لن يحدث بسبب التحقق في clean، ولكن للأمان
                raise ZeroDivisionError("alt_factor cannot be zero")
            return qty / self.alt_factor

        raise ValidationError(_("وحدة القياس غير مرتبطة بهذا المنتج."))

    @property
    def total_on_hand(self) -> Decimal:
        """إجمالي الكمية المتوفرة (للعرض فقط)."""
        return self.stock_levels.aggregate(t=Sum("quantity_on_hand"))["t"] or DECIMAL_ZERO

    @property
    def calculated_available_qty(self):
        """
        تستخدم في القوالب عندما يكون المنتج محملاً مع with_stock_summary.
        """
        total = getattr(self, 'total_qty', Decimal(0)) or Decimal(0)
        reserved = getattr(self, 'total_reserved', Decimal(0)) or Decimal(0)
        return total - reserved

    @property
    def image_url(self):
        """إرجاع رابط الصورة (مفيد في القوالب)."""
        if self.image and hasattr(self.image, "url"):
            return self.image.url
        return None


# ============================================================
# المستودعات
# ============================================================
class Warehouse(BaseModel):
    code = models.CharField(max_length=20, unique=True, verbose_name=_("كود المستودع"))
    name = models.CharField(max_length=200, verbose_name=_("اسم المستودع"))
    description = models.TextField(blank=True, verbose_name=_("الوصف"))
    is_active = models.BooleanField(default=True, verbose_name=_("نشط"))

    objects = WarehouseManager()

    class Meta:
        verbose_name = _("مستودع")
        verbose_name_plural = _("المستودعات")
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} – {self.name}"


# ============================================================
# مواقع المخزون
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
        unique_together = ("warehouse", "code")
        verbose_name = _("موقع مخزون")
        verbose_name_plural = _("مواقع المخزون")
        ordering = ("warehouse__code", "code")

    def __str__(self) -> str:
        return f"{self.warehouse.code}/{self.code}"


# ============================================================
# حركات المخزون (Header)
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
        max_length=20, choices=MoveType.choices, default=MoveType.IN, verbose_name=_("نوع الحركة")
    )
    adjustment = models.ForeignKey(
        "inventory.InventoryAdjustment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_moves",
        verbose_name=_("وثيقة الجرد المرتبطة"),
        help_text=_("يتم تعبئته آلياً إذا كانت الحركة ناتجة عن تسوية جردية.")
    )

    # المصدر والوجهة
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True,
                                       related_name="outgoing_moves", verbose_name=_("من مستودع"))
    from_location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, null=True, blank=True,
                                      related_name="outgoing_moves", verbose_name=_("من موقع"))

    to_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True,
                                     related_name="incoming_moves", verbose_name=_("إلى مستودع"))
    to_location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="incoming_moves", verbose_name=_("إلى موقع"))

    move_date = models.DateTimeField(default=timezone.now, verbose_name=_("تاريخ الحركة"))
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, verbose_name=_("الحالة"))
    reference = models.CharField(max_length=255, blank=True, verbose_name=_("مرجع خارجي"))
    note = models.TextField(blank=True, verbose_name=_("ملاحظات"))

    objects = StockMoveManager()

    class Meta:
        verbose_name = _("حركة مخزون")
        verbose_name_plural = _("حركات المخزون")
        ordering = ("-move_date", "-id")

    def __str__(self) -> str:
        return f"Move #{self.pk} ({self.get_move_type_display()})"

    # ============================
    # سياق الترقيم
    # ============================
    def get_numbering_context(self) -> dict:
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

    # ============================
    # التحقق (Validation)
    # ============================
    def clean(self):
        super().clean()

        # حركة واردة
        if self.move_type == self.MoveType.IN:
            if not self.to_warehouse or not self.to_location:
                raise ValidationError(_("الحركة الواردة تتطلب تحديد مستودع وموقع وجهة."))
            if self.from_warehouse or self.from_location:
                raise ValidationError(_("الحركة الواردة لا يجب أن تحتوي على مصدر (من مستودع/من موقع)."))

        # حركة صادرة
        elif self.move_type == self.MoveType.OUT:
            if not self.from_warehouse or not self.from_location:
                raise ValidationError(_("الحركة الصادرة تتطلب تحديد مستودع وموقع مصدر."))
            if self.to_warehouse or self.to_location:
                raise ValidationError(_("الحركة الصادرة لا يجب أن تحتوي على وجهة (إلى مستودع/إلى موقع)."))

        # تحويل داخلي
        elif self.move_type == self.MoveType.TRANSFER:
            if not (self.from_warehouse and self.from_location and self.to_warehouse and self.to_location):
                raise ValidationError(_("حركة التحويل تتطلب تحديد مصدر ووجهة (مستودع + موقع) معاً."))

            # لا يجوز تحويل من نفس المستودع والموقع إلى نفسه
            if (
                    self.from_warehouse_id == self.to_warehouse_id
                    and self.from_location_id == self.to_location_id
            ):
                raise ValidationError(_("لا يمكن تحويل المخزون إلى نفس المستودع ونفس الموقع."))

        # تحقق توافق المواقع مع المستودعات (إن كانت محددة)
        if self.from_location and self.from_warehouse:
            if self.from_location.warehouse_id != self.from_warehouse_id:
                raise ValidationError(_("موقع المصدر لا يتبع نفس مستودع المصدر."))

        if self.to_location and self.to_warehouse:
            if self.to_location.warehouse_id != self.to_warehouse_id:
                raise ValidationError(_("موقع الوجهة لا يتبع نفس مستودع الوجهة."))

    @property
    def is_done(self) -> bool:
        """Helper to check if the move is in DONE status."""
        return self.status == self.Status.DONE


# ============================================================
# بنود الحركة (Lines)
# ============================================================
class StockMoveLine(BaseModel):
    move = models.ForeignKey(StockMove, on_delete=models.CASCADE, related_name="lines", verbose_name=_("الحركة"))
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_moves", verbose_name=_("المنتج"))
    quantity = models.DecimalField(max_digits=12, decimal_places=3, verbose_name=_("الكمية"))
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, verbose_name=_("وحدة القياس"))

    # تكلفة الوحدة لحظة الحركة (لتثبيت السعر تاريخياً)
    cost_price = models.DecimalField(max_digits=12, decimal_places=3, default=DECIMAL_ZERO,
                                     verbose_name=_("تكلفة الوحدة"))

    class Meta:
        verbose_name = _("بند حركة")
        verbose_name_plural = _("بنود الحركة")
        indexes = [
            models.Index(fields=["product", "move"], name="stockmoveline_prod_move_idx"),
        ]

    def clean(self):
        super().clean()

        if self.quantity is None or self.quantity <= 0:
            raise ValidationError(_("الكمية يجب أن تكون أكبر من صفر."))

        # لا نسمح بتكلفة سالبة
        if self.cost_price is not None and self.cost_price < 0:
            raise ValidationError(_("تكلفة الوحدة لا يمكن أن تكون سالبة."))

        # تحقق من أن وحدة القياس مرتبطة بالمنتج (أساس أو بديلة فقط)
        if self.product_id and self.uom_id:
            allowed_uoms = [self.product.base_uom]
            if self.product.alt_uom:
                allowed_uoms.append(self.product.alt_uom)

            if self.uom not in allowed_uoms:
                raise ValidationError(
                    _("وحدة القياس يجب أن تكون وحدة الأساس أو الوحدة البديلة للمنتج.")
                )

    def get_base_quantity(self) -> Decimal:
        return self.product.to_base(self.quantity, self.uom)

    @property
    def line_total_cost(self) -> Decimal:
        """
        التكلفة الإجمالية لهذا البند = الكمية * تكلفة الوحدة.
        مفيد للتقارير.
        """
        return (self.quantity or DECIMAL_ZERO) * (self.cost_price or DECIMAL_ZERO)


# ============================================================
# أرصدة المخزون (Stock Levels) - تم تعديله للسماح بالسالب
# ============================================================
class StockLevel(BaseModel):
    """
    يخزن الكمية الحالية لكل منتج في كل موقع.
    تم إزالة القيد الذي يمنع السالب.
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock_levels",
                                verbose_name=_("المنتج"))
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="stock_levels",
                                  verbose_name=_("المستودع"))
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="stock_levels",
                                 verbose_name=_("الموقع"))

    quantity_on_hand = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("الكمية المتوفرة"),
    )

    quantity_reserved = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("الكمية المحجوزة"),
    )

    min_stock = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("الحد الأدنى (Legacy)"),
        help_text=_("يفضل استخدام قواعد إعادة الطلب بدلاً من هذا الحقل."),
    )

    objects = StockLevelManager()

    class Meta:
        verbose_name = _("رصيد مخزون")
        verbose_name_plural = _("أرصدة المخزون")
        unique_together = ("product", "warehouse", "location")
        constraints = [
            # تمت إزالة قيد quantity_on_hand__gte=0 للسماح بالسالب

            # الكمية المحجوزة منطقياً لا يجب أن تكون سالبة
            models.CheckConstraint(
                name="stocklevel_reserved_non_negative",
                check=Q(quantity_reserved__gte=0),
            ),
        ]
        indexes = [
            models.Index(
                fields=["product", "warehouse", "location"],
                name="stocklevel_prod_wh_loc_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product} @ {self.location} = {self.quantity_on_hand}"

    def clean(self):
        """
        تأكد أن الموقع يتبع نفس المستودع.
        """
        super().clean()

        if self.location_id and self.warehouse_id:
            # نستخدم values_list لتخفيف الحمل
            loc_warehouse_id = StockLocation.objects.values_list(
                "warehouse_id", flat=True
            ).get(pk=self.location_id)

            if loc_warehouse_id != self.warehouse_id:
                raise ValidationError(
                    _("الموقع المختار لا يتبع نفس المستودع المحدد في رصيد المخزون.")
                )

    @property
    def qty(self) -> Decimal:
        """Alias لـ quantity_on_hand"""
        return self.quantity_on_hand

    @property
    def available_quantity(self) -> Decimal:
        """المتاح للبيع = المتوفر - المحجوز (قد يكون سالباً الآن)"""
        return self.quantity_on_hand - self.quantity_reserved


# ============================================================
# قواعد إعادة الطلب (Reorder Rules)
# ============================================================
class ReorderRule(BaseModel):
    """
    قاعدة إعادة طلب لكل (منتج، مستودع، موقع اختياري).
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="reorder_rules",
        verbose_name=_("المنتج"),
    )

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="reorder_rules",
        verbose_name=_("المستودع"),
    )

    location = models.ForeignKey(
        StockLocation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reorder_rules",
        verbose_name=_("الموقع داخل المستودع (اختياري)"),
        help_text=_("اتركه فارغاً لتطبيق القاعدة على مستوى المستودع بالكامل."),
    )

    min_qty = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("الحد الأدنى"),
        help_text=_("عند نزول الرصيد عن هذه الكمية، يظهر تنبيه إعادة الطلب."),
    )

    target_qty = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("الكمية المستهدفة"),
        help_text=_(
            "الكمية التي تود الوصول إليها بعد الشراء/التوريد. "
            "يُستخدم لحساب الكمية المقترحة للطلب."
        ),
    )

    multiple_of = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name=_("مضاعفات الكمية"),
        help_text=_(
            "اختياري: إن كان يجب الطلب دائماً بمضاعفات معينة "
            "(مثال: بار بطول 6م، تكتب 6)."
        ),
    )

    lead_time_days = models.PositiveIntegerField(
        default=0,
        verbose_name=_("مدة التوريد (أيام)"),
        help_text=_("اختياري: عدد الأيام التقريبية لوصول البضاعة بعد الطلب."),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("نشطة"),
    )

    objects = ReorderRuleManager()

    class Meta:
        verbose_name = _("قاعدة إعادة طلب")
        verbose_name_plural = _("قواعد إعادة الطلب")
        constraints = [
            models.UniqueConstraint(
                fields=["product", "warehouse", "location"],
                name="uniq_reorder_rule_per_product_wh_loc",
            )
        ]
        indexes = [
            models.Index(
                fields=["product", "warehouse"],
                name="reorder_prod_wh_idx",
            ),
        ]

    def __str__(self) -> str:
        loc_label = f" / {self.location.code}" if self.location_id else ""
        return f"{self.product.code} @ {self.warehouse.code}{loc_label}"

    # ============================
    # دوال مساعدة
    # ============================

    @property
    def get_current_stock(self):
        """
        حساب الرصيد الحالي بناءً على النطاق (مستودع كامل أو موقع محدد).
        """
        if self.location:
            # حالة موقع محدد
            try:
                level = StockLevel.objects.get(
                    product=self.product,
                    warehouse=self.warehouse,
                    location=self.location
                )
                return level.quantity_on_hand
            except StockLevel.DoesNotExist:
                return DECIMAL_ZERO
        else:
            # حالة المستودع بالكامل (تجميع كل المواقع)
            total = StockLevel.objects.filter(
                product=self.product,
                warehouse=self.warehouse
            ).aggregate(t=models.Sum("quantity_on_hand"))["t"]

            # ✅ الإصلاح هنا: Aggregate ترجع None إذا لم توجد سجلات
            return total if total is not None else DECIMAL_ZERO

    def get_recommended_qty(self) -> Decimal:
        """
        يحسب الكمية المقترحة للطلب.
        Uses ROUND_UP correctly from decimal module.
        """
        current_stock = self.get_current_stock
        diff = Decimal(self.target_qty or DECIMAL_ZERO) - (current_stock or DECIMAL_ZERO)

        if diff <= 0:
            return DECIMAL_ZERO

        if self.multiple_of:
            mult = Decimal(self.multiple_of)
            if mult > 0:
                # تقريب لأعلى مضاعف
                # ROUND_UP imported at the top
                q = (diff / mult).quantize(Decimal("1."), rounding=ROUND_UP)
                return q * mult

        return diff

    @property
    def is_below_min(self):
        """هل الرصيد أقل من الحد الأدنى؟"""
        # ✅ الإصلاح هنا أيضاً لزيادة الأمان
        current = self.get_current_stock
        if current is None:
            current = DECIMAL_ZERO

        minimum = self.min_qty or DECIMAL_ZERO

        return current < minimum





# ============================================================
# 2. تسوية الجرد (Inventory Adjustment Models)
# ============================================================

class InventoryAdjustment(BaseModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', _('مسودة / قيد العد')
        IN_PROGRESS = 'in_progress', _('قيد المراجعة')
        APPLIED = 'applied', _('تم الترحيل')
        CANCELLED = 'cancelled', _('ملغاة')

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="adjustments",
        verbose_name=_("المستودع")
    )

    date = models.DateField(
        default=timezone.now,
        verbose_name=_("تاريخ الجرد")
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name=_("الحالة")
    )

    # نطاق الجرد (اختياري للفلترة)
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("نطاق التصنيف"),
        help_text=_("اختياري: لجرد قسم معين فقط.")
    )

    location = models.ForeignKey(
        StockLocation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("نطاق الموقع"),
        help_text=_("اختياري: لجرد رف/موقع معين فقط.")
    )

    note = models.TextField(blank=True, verbose_name=_("ملاحظات"))

    # حقل مساعد لمعرفة المستخدم الذي أنشأ الجرد (إذا لم يكن في BaseModel)
    # created_by = models.ForeignKey(...)

    class Meta:
        verbose_name = _("وثيقة جرد")
        verbose_name_plural = _("وثائق الجرد")
        ordering = ("-date", "-id")

    def __str__(self):
        return f"INV-ADJ #{self.pk} ({self.warehouse})"


class InventoryAdjustmentLine(BaseModel):
    adjustment = models.ForeignKey(
        InventoryAdjustment,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("وثيقة الجرد")
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        verbose_name=_("المنتج")
    )

    location = models.ForeignKey(
        StockLocation,
        on_delete=models.PROTECT,
        verbose_name=_("الموقع المحدد")
    )

    # اللقطة (Snapshot)
    theoretical_qty = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name=_("الكمية النظرية (النظام)"),
        help_text=_("الرصيد المسجل في النظام لحظة إنشاء الوثيقة.")
    )

    # الواقع (Actual)
    counted_qty = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name=_("الكمية الفعلية (العد)"),
        help_text=_("ما تم عده فعلياً. اتركه فارغاً إذا لم يتم العد بعد.")
    )

    class Meta:
        verbose_name = _("بند جرد")
        verbose_name_plural = _("بنود الجرد")
        unique_together = ("adjustment", "product", "location")

    @property
    def difference(self):
        """الفرق = الفعلي - النظري"""
        if self.counted_qty is None:
            return None
        return self.counted_qty - self.theoretical_qty