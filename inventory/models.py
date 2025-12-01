# inventory/models.py

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum, F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from solo.models import SingletonModel

from core.models import TimeStampedModel, BaseModel
from inventory.managers import (
    ProductCategoryManager,
    ProductManager,
    StockLocationManager,
    StockMoveManager,
    StockLevelManager,
    WarehouseManager,
)
from uom.models import UnitOfMeasure


DECIMAL_ZERO = Decimal("0.000")


# ============================================================
# تصنيفات المنتجات
# ============================================================
class ProductCategory(TimeStampedModel):
    """
    شجرة تصنيفات بسيطة للمنتجات.
    مثال: أنظمة ألمنيوم، إكسسوارات، زجاج، خدمات...
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
    # دوال مساعدة
    # ============================

    @property
    def full_path(self) -> str:
        """
        يرجع المسار الكامل للتصنيف، مثلاً:
        "أنظمة / معزول حرارياً / سحاب".
        مفيد للقوائم والتقارير.
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
        يرجع فقط التصنيفات الفرعية النشطة.
        """
        return self.children.filter(is_active=True)

    def products_count(self) -> int:
        """
        عدد المنتجات النشطة في هذا التصنيف (مباشرة فقط).
        """
        return self.products.filter(is_active=True).count()

    def can_be_deleted(self) -> bool:
        """
        قاعدة بسيطة:
        - لا يوجد تصنيفات فرعية
        - لا يوجد منتجات
        """
        return not self.children.exists() and not self.products.exists()


# ============================================================
# المنتجات
# ============================================================
class Product(TimeStampedModel):
    """
    المنتج الأساسي للمخزون.
    يُستخدم في المخزون / الأوامر / الفواتير.
    نشر المنتج للموقع/البوابة يتحكم به الحقل is_published.
    """

    class ProductType(models.TextChoices):
        STOCKABLE = "stockable", _("صنف مخزني")
        SERVICE = "service", _("خدمة")
        CONSUMABLE = "consumable", _("مستهلكات")

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
        verbose_name=_("كود المنتج"),
        help_text=_("كود داخلي فريد، مثل: MZN-46-FRAME"),
    )

    name = models.CharField(
        max_length=255,
        verbose_name=_("اسم المنتج"),
    )

    default_sale_price = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("سعر البيع الافتراضي (لكل وحدة أساس)"),
        help_text=_("سعر البيع الداخلي الافتراضي لكل وحدة القياس الأساسية للمنتج."),
    )

    default_cost_price = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("سعر التكلفة التقريبي"),
        help_text=_("يُستخدم للتقارير الداخلية وتقدير تكلفة المخزون (اختياري)."),
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

    # نوع المنتج (مخزني / خدمة / مستهلكات)
    product_type = models.CharField(
        max_length=20,
        choices=ProductType.choices,
        default=ProductType.STOCKABLE,
        verbose_name=_("نوع المنتج"),
        help_text=_("يحدد إذا كان المنتج مخزني، خدمة أو مستهلكات."),
    )

    # ============================
    # وحدات القياس
    # ============================

    base_uom = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name="products_as_base",
        verbose_name=_("وحدة القياس الأساسية"),
        help_text=_("الوحدة الأساسية للمخزون، مثل: م، قطعة."),
    )

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

    weight_uom = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="products_as_weight",
        verbose_name=_("وحدة الوزن"),
        help_text=_("الوحدة المستخدمة للوزن، مثل: كجم."),
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
    # أعلام الحالة والمخزون
    # ============================

    is_stock_item = models.BooleanField(
        default=True,
        verbose_name=_("يُتابَع في المخزون"),
        help_text=_("إذا تم تعطيله، لن يتم تتبع هذا المنتج في حركات المخزون."),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("نشط"),
        help_text=_("إذا تم تعطيله، لن يظهر في المستندات الجديدة."),
    )

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
    # تحويل الكميات بين الوحدات
    # ============================

    def convert_qty(self, qty, from_uom, to_uom):
        """
        تحويل الكمية بين الوحدة الأساسية والبديلة باستخدام alt_factor.

        القاعدة:
        - 1 وحدة بديلة = alt_factor * وحدة أساسية
        """
        if qty is None:
            return None

        qty = Decimal(qty)

        if from_uom == to_uom:
            return qty

        if not self.alt_uom or not self.alt_factor:
            raise ValueError("لم يتم ضبط وحدة بديلة / عامل تحويل لهذا المنتج.")

        factor = Decimal(self.alt_factor)

        # من بديلة إلى أساسية
        if from_uom == self.alt_uom and to_uom == self.base_uom:
            return qty * factor

        # من أساسية إلى بديلة
        if from_uom == self.base_uom and to_uom == self.alt_uom:
            if factor == 0:
                raise ZeroDivisionError("alt_factor لا يمكن أن يكون صفر.")
            return qty / factor

        raise ValueError("تحويل غير مدعوم لهذا المنتج (الوحدة غير مرتبطة).")

    def to_base(self, qty, uom=None):
        """
        يرجع الكمية دائماً بوحدة القياس الأساسية.
        إذا لم تُحدد وحدة، يُفترض أن الكمية بوحدة الأساس.
        """
        if qty is None:
            return None

        if uom is None or uom == self.base_uom:
            return Decimal(qty)

        return self.convert_qty(qty=qty, from_uom=uom, to_uom=self.base_uom)

    def to_alt(self, qty, uom=None):
        """
        يرجع الكمية بوحدة القياس البديلة (إذا كانت مضبوطة).
        إذا لم تُحدد وحدة، يُفترض أن الكمية بوحدة الأساس.
        """
        if qty is None:
            return None

        if not self.alt_uom:
            raise ValueError("لم يتم ضبط وحدة بديلة لهذا المنتج.")

        from_uom = uom or self.base_uom
        return self.convert_qty(qty=qty, from_uom=from_uom, to_uom=self.alt_uom)

    def qty_to_weight(self, qty, qty_uom=None):
        """
        تحويل أي كمية (أساس أو بديلة) إلى وزن بوحدة الوزن weight_uom.

        الخطوات:
        1) تحويل الكمية إلى وحدة الأساس.
        2) ضربها في الوزن لكل وحدة أساس weight_per_base.
        """
        if qty is None:
            return None

        if self.weight_uom is None or self.weight_per_base is None:
            raise ValueError("لم يتم ضبط الوزن لهذا المنتج.")

        qty_base = self.to_base(qty=qty, uom=qty_uom)
        return qty_base * Decimal(self.weight_per_base)

    def weight_to_qty(self, weight, to_uom=None):
        """
        تحويل وزن (بوحدة الوزن) إلى كمية (أساس أو بديلة).

        الخطوات:
        1) حساب كمية وحدة الأساس: qty_base = weight / weight_per_base
        2) إذا كانت to_uom وحدة بديلة، تحويل من أساس إلى بديلة.
        """
        if weight is None:
            return None

        if self.weight_uom is None or self.weight_per_base is None:
            raise ValueError("لم يتم ضبط الوزن لهذا المنتج.")

        weight = Decimal(weight)

        if self.weight_per_base == 0:
            raise ZeroDivisionError("weight_per_base لا يمكن أن يكون صفر.")

        qty_base = weight / Decimal(self.weight_per_base)

        if to_uom is None or to_uom == self.base_uom:
            return qty_base

        if to_uom == self.alt_uom:
            return self.convert_qty(
                qty=qty_base,
                from_uom=self.base_uom,
                to_uom=self.alt_uom,
            )

        raise ValueError("وحدة الهدف غير مدعومة لهذا المنتج.")

    def get_price_for_uom(self, uom=None, kind="sale") -> Decimal:
        """
        ترجع السعر حسب نوعه (بيع أو تكلفة) وبحسب وحدة القياس:

        - kind = "sale": يرجع default_sale_price
        - kind = "cost": يرجع default_cost_price

        القواعد:
        1) إذا لم تُمرّر uom → نفترض وحدة الأساس.
        2) إذا uom == base_uom → يرجع السعر كما هو.
        3) إذا uom == alt_uom → يتم ضرب السعر في alt_factor.
           (لأن 1 وحدة بديلة = alt_factor من الأساس)
        """

        # --- اختيار نوع السعر (بيع أو تكلفة) ---
        if kind == "sale":
            base_price = self.default_sale_price
        elif kind == "cost":
            base_price = self.default_cost_price
        else:
            raise ValueError("kind يجب أن يكون 'sale' أو 'cost'.")

        # --- إذا الوحدة الأساسية → نرجع السعر مباشرة ---
        if uom is None or uom == self.base_uom:
            return Decimal(base_price)

        # --- إذا الوحدة البديلة → نطبّق alt_factor ---
        if uom == self.alt_uom:
            if not self.alt_factor:
                raise ValueError("لم يتم ضبط عامل التحويل للوحدة البديلة لهذا المنتج.")
            return Decimal(base_price) * Decimal(self.alt_factor)

        # --- وحدة غير مرتبطة بالمنتج ---
        raise ValueError("وحدة القياس المطلوبة غير مرتبطة بهذا المنتج.")

    # ============================
    # دوال مساعدة للمخزون
    # ============================

    @property
    def total_on_hand(self) -> Decimal:
        """
        إجمالي الكمية المتوفرة لهذا المنتج في كل المستودعات / المواقع.
        """
        agg = self.stock_levels.aggregate(total=Sum("quantity_on_hand"))
        return agg["total"] or DECIMAL_ZERO

    def low_stock_levels(self):
        """
        يرجع QuerySet من StockLevel حيث المنتج تحت الحد الأدنى في المواقع.
        """
        return self.stock_levels.filter(
            min_stock__gt=DECIMAL_ZERO,
            quantity_on_hand__lt=F("min_stock"),
        )

    @property
    def has_low_stock_anywhere(self) -> bool:
        """
        هل هذا المنتج تحت الحد الأدنى في أي مستودع/موقع؟
        """
        return self.low_stock_levels().exists()

    def total_on_hand_in_warehouse(self, warehouse) -> Decimal:
        """
        إجمالي الكمية المتوفرة في مستودع معيّن.
        """
        agg = self.stock_levels.filter(warehouse=warehouse).aggregate(
            total=Sum("quantity_on_hand")
        )
        return agg["total"] or DECIMAL_ZERO

    def has_stock(self, warehouse=None) -> bool:
        """
        هل يوجد أي رصيد لهذا المنتج؟

        - إذا تم تمرير warehouse: يبحث فقط في هذا المستودع.
        - إذا لم يُمرر: يبحث في كل المستودعات.
        """
        if warehouse is not None:
            return self.total_on_hand_in_warehouse(warehouse) > DECIMAL_ZERO
        return self.total_on_hand > DECIMAL_ZERO

    def can_be_deleted(self) -> bool:
        """
        قاعدة بسيطة: يمكن حذف المنتج إذا لم يكن له أي حركات مخزون.
        (يمكن لاحقاً توسيعها للأوامر / الفواتير...)
        """
        return not self.stock_moves.exists()


# ============================================================
# المستودعات
# ============================================================
class Warehouse(TimeStampedModel):
    """
    مستودع فعلي أو منطقي.
    مثال: مستودع رئيسي، معرض، مخزن خارجي...
    """

    code = models.CharField(
        max_length=20,
        unique=True,
        verbose_name=_("كود المستودع"),
        help_text=_("كود قصير، مثل: WH-MCT."),
    )

    name = models.CharField(
        max_length=200,
        verbose_name=_("اسم المستودع"),
    )

    description = models.TextField(
        blank=True,
        verbose_name=_("الوصف"),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("نشط"),
    )

    objects = WarehouseManager()

    class Meta:
        verbose_name = _("مستودع")
        verbose_name_plural = _("المستودعات")
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} – {self.name}"

    @property
    def stock_levels_qs(self):
        """
        جميع أرصدة المخزون في هذا المستودع مع ربط المنتج والموقع.
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
        return agg["total"] or DECIMAL_ZERO

    @property
    def low_stock_count(self) -> int:
        """
        عدد الأصناف التي تحت الحد الأدنى min_stock.
        """
        return self.stock_levels.filter(
            min_stock__gt=DECIMAL_ZERO,
            quantity_on_hand__lt=F("min_stock"),
        ).count()

    @property
    def has_low_stock(self) -> bool:
        """
        هل يوجد أي صنف منخفض المخزون في هذا المستودع؟
        """
        return self.low_stock_count > 0


# ============================================================
# مواقع المخزون داخل المستودعات
# ============================================================
class StockLocation(TimeStampedModel):
    """
    موقع مخزون داخل / مرتبط بالمستودع.
    أمثلة:
      - مخزون داخلي
      - مورد
      - عميل
      - تالفة (Scrap)
      - قيد النقل (Transit)
    """

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

    code = models.CharField(
        max_length=30,
        verbose_name=_("كود الموقع"),
        help_text=_("كود قصير، مثل: STOCK, SCRAP, SHOWROOM."),
    )

    name = models.CharField(
        max_length=200,
        verbose_name=_("اسم الموقع"),
    )

    type = models.CharField(
        max_length=20,
        choices=LocationType.choices,
        default=LocationType.INTERNAL,
        verbose_name=_("نوع الموقع"),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("نشط"),
    )

    objects = StockLocationManager()

    class Meta:
        verbose_name = _("موقع مخزون")
        verbose_name_plural = _("مواقع المخزون")
        unique_together = ("warehouse", "code")
        ordering = ("warehouse__code", "code")

    def __str__(self) -> str:
        return f"{self.warehouse.code}/{self.code} – {self.name}"


# ============================================================
# حركات المخزون (الرأس)
# ============================================================
class StockMove(BaseModel):
    """
    مستند حركة مخزون.
    يحتوي على معلومات عامة عن الحركة:
      - نوع الحركة (دخول / خروج / تحويل)
      - من مستودع / إلى مستودع
      - من موقع / إلى موقع
      - التاريخ، الحالة، المرجع، الملاحظات

    تفاصيل المنتجات في:
      - StockMoveLine (عدة بنود لكل حركة)
    """

    class MoveType(models.TextChoices):
        IN = "in", _("حركة واردة")
        OUT = "out", _("حركة صادرة")
        TRANSFER = "transfer", _("تحويل بين مواقع/مستودعات")

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

    from_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="outgoing_moves",
        verbose_name=_("من مستودع"),
    )

    from_location = models.ForeignKey(
        StockLocation,
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
        StockLocation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="incoming_moves",
        verbose_name=_("إلى موقع"),
    )

    move_date = models.DateTimeField(
        default=timezone.now,
        verbose_name=_("تاريخ الحركة"),
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name=_("الحالة"),
    )

    reference = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("مرجع خارجي"),
        help_text=_("مرجع خارجي اختياري، مثل: PO/2025/0001."),
    )

    note = models.TextField(
        blank=True,
        verbose_name=_("ملاحظات"),
    )

    objects = StockMoveManager()

    class Meta:
        verbose_name = _("حركة مخزون")
        verbose_name_plural = _("حركات المخزون")
        ordering = ("-move_date", "-id")
        indexes = [
            models.Index(
                fields=["move_date", "status"],
                name="stockmove_date_status_idx",
            ),
            models.Index(
                fields=["status"],
                name="stockmove_status_idx",
            ),
        ]
        constraints = [
            # منع تحويل من نفس المستودع ونفس الموقع إلى نفسه (إذا كانت الحقول كلها غير فارغة)
            models.CheckConstraint(
                name="stockmove_from_to_not_same",
                check=~(
                    Q(from_warehouse__isnull=False)
                    & Q(to_warehouse__isnull=False)
                    & Q(from_location__isnull=False)
                    & Q(to_location__isnull=False)
                    & Q(from_warehouse=F("to_warehouse"))
                    & Q(from_location=F("to_location"))
                ),
            ),
        ]

    # ============================
    # سياق الترقيم
    # ============================

    def get_numbering_context(self) -> dict:
        """
        يضيف بادئة prefix حسب نوع الحركة:
          - IN       → من إعدادات المخزون
          - OUT      → من إعدادات المخزون
          - TRANSFER → من إعدادات المخزون

        تُستخدم البادئة في pattern مثل: {prefix}-{seq:05d}
        """
        from inventory.models import InventorySettings  # import محلي لتجنب الدوران

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
        return f"حركة #{self.pk} ({self.get_move_type_display()})"

    # ============================
    # التحقق (Validation)
    # ============================

    def clean(self):
        super().clean()

        # تحقق من الحقول المطلوبة حسب نوع الحركة
        if self.move_type == self.MoveType.IN:
            if not self.to_warehouse or not self.to_location:
                raise ValidationError(
                    _("حركة واردة تتطلب مستودع وموقع وجهة (إلى مستودع/إلى موقع).")
                )
            if self.from_warehouse or self.from_location:
                raise ValidationError(
                    _("حركة واردة لا يجب أن تحتوي على مستودع/موقع مصدر.")
                )

        elif self.move_type == self.MoveType.OUT:
            if not self.from_warehouse or not self.from_location:
                raise ValidationError(
                    _("حركة صادرة تتطلب مستودع وموقع مصدر (من مستودع/من موقع).")
                )
            if self.to_warehouse or self.to_location:
                raise ValidationError(
                    _("حركة صادرة لا يجب أن تحتوي على مستودع/موقع وجهة.")
                )

        elif self.move_type == self.MoveType.TRANSFER:
            if not (
                self.from_warehouse
                and self.from_location
                and self.to_warehouse
                and self.to_location
            ):
                raise ValidationError(
                    _("حركة تحويل تتطلب مصدرًا ووجهة (مستودع + موقع) معاً.")
                )

            if self.from_location.warehouse_id != self.from_warehouse_id:
                raise ValidationError(
                    _("موقع المصدر يجب أن يكون تابعاً لمستودع المصدر.")
                )
            if self.to_location.warehouse_id != self.to_warehouse_id:
                raise ValidationError(
                    _("موقع الوجهة يجب أن يكون تابعاً لمستودع الوجهة.")
                )

    # ============================
    # دوال مساعدة
    # ============================

    @property
    def is_done(self) -> bool:
        """
        هل الحركة منفذة (DONE)؟
        """
        return self.status == self.Status.DONE

    @property
    def total_lines_quantity(self) -> Decimal:
        """
        مجموع الكميات في جميع البنود (بوحداتها كما هي في البنود).
        هذه المعلومة للعرض فقط، وليست أساس التحديث في StockLevel.
        """
        agg = self.lines.aggregate(total=Sum("quantity"))
        return agg["total"] or DECIMAL_ZERO

    def save(self, *args, **kwargs):
        """
        يربط تحديث المخزون بتغيير حالة الحركة (status).

        المنطق في apply_stock_move_status_change:
          - يمر على self.lines ويحدث StockLevel حسب:
            * نوع الحركة move_type
            * الكمية الأساسية (base_uom) لكل سطر
        """
        from .services import apply_stock_move_status_change  # import محلي

        is_create = self.pk is None
        old_status = None

        if not is_create:
            try:
                old_status = (
                    self.__class__.objects.only("status").get(pk=self.pk).status
                )
            except self.__class__.DoesNotExist:
                is_create = True
                old_status = None

        super().save(*args, **kwargs)

        apply_stock_move_status_change(
            move=self,
            old_status=old_status,
            is_create=is_create,
        )


# ============================================================
# بنود حركات المخزون (التفاصيل)
# ============================================================
class StockMoveLine(TimeStampedModel):
    """
    سطر واحد في حركة مخزون.
    يحتوي على:
      - المنتج
      - الكمية
      - وحدة القياس

    تحديث المخزون الفعلي يتم بناءً على:
      - نوع الحركة move.move_type
      - الكمية المحوّلة لوحدة الأساس للمنتج (product.base_uom)
    """

    move = models.ForeignKey(
        StockMove,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("حركة المخزون"),
    )

    # related_name = "stock_moves" حتى نستخدم:
    # product.stock_moves في Product.can_be_deleted
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="stock_moves",
        verbose_name=_("المنتج"),
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name=_("الكمية"),
    )

    uom = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name="stock_move_lines",
        verbose_name=_("وحدة القياس"),
        help_text=_(
            "وحدة القياس المستخدمة في هذا السطر "
            "ويجب أن تكون وحدة الأساس أو الوحدة البديلة للمنتج."
        ),
    )

    class Meta:
        verbose_name = _("بند حركة مخزون")
        verbose_name_plural = _("بنود حركات المخزون")

    def __str__(self) -> str:
        uom_code = self.uom.code if self.uom_id else "?"
        return f"{self.product.code}: {self.quantity} {uom_code}"

    # ============================
    # التحقق (Validation)
    # ============================

    def clean(self):
        super().clean()

        if self.quantity is None or self.quantity <= 0:
            raise ValidationError(_("الكمية يجب أن تكون أكبر من صفر."))

        if self.product_id and self.uom_id:
            allowed_uoms = [self.product.base_uom]
            if self.product.alt_uom:
                allowed_uoms.append(self.product.alt_uom)

            # عمداً لا نسمح باستخدام وحدة الوزن كبند حركة
            if self.uom not in allowed_uoms:
                raise ValidationError(
                    _(
                        "وحدة القياس المختارة غير مضبوطة لهذا المنتج "
                        "(يجب أن تكون وحدة الأساس أو الوحدة البديلة)."
                    )
                )

    # ============================
    # دوال مساعدة
    # ============================

    def get_base_quantity(self) -> Decimal:
        """
        يرجع الكمية المحوّلة إلى وحدة المنتج الأساسية base_uom.
        هذه القيمة هي التي تُستخدم لتحديث StockLevel.
        """
        return self.product.to_base(self.quantity, uom=self.uom)


# ============================================================
# أرصدة المخزون
# ============================================================
class StockLevel(TimeStampedModel):
    """
    الرصيد الحالي لكل (منتج، مستودع، موقع).

    نكرر المستودع هنا بالرغم من أنه موجود في StockLocation
    حتى نسهل الاستعلامات ونعمل تجميع (aggregate) على مستوى المستودع
    بدون join إضافي.
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="stock_levels",
        verbose_name=_("المنتج"),
    )

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="stock_levels",
        verbose_name=_("المستودع"),
    )

    location = models.ForeignKey(
        StockLocation,
        on_delete=models.PROTECT,
        related_name="stock_levels",
        verbose_name=_("الموقع داخل المستودع"),
    )

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
        verbose_name=_("كمية محجوزة"),
    )

    min_stock = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("الحد الأدنى للمخزون"),
    )

    objects = StockLevelManager()

    class Meta:
        verbose_name = _("رصيد مخزون")
        verbose_name_plural = _("أرصدة المخزون")
        unique_together = ("product", "warehouse", "location")
        indexes = [
            models.Index(
                fields=["product", "warehouse"],
                name="stk_lvl_prod_wh_idx",
            ),
            models.Index(
                fields=["warehouse", "location"],
                name="stk_lvl_wh_loc_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                name="stocklevel_quantity_on_hand_non_negative",
                check=Q(quantity_on_hand__gte=0),
            ),
            models.CheckConstraint(
                name="stocklevel_quantity_reserved_non_negative",
                check=Q(quantity_reserved__gte=0),
            ),
            models.CheckConstraint(
                name="stocklevel_min_stock_non_negative",
                check=Q(min_stock__gte=0),
            ),
        ]

    def __str__(self):
        return f"{self.product} @ {self.warehouse} / {self.location}"

    @property
    def qty(self) -> Decimal:
        """
        اسم قديم متوافق مع الخلف: alias لـ quantity_on_hand.
        """
        return self.quantity_on_hand

    # ============================
    # خصائص مساعدة
    # ============================

    @property
    def available_quantity(self) -> Decimal:
        """
        الكمية المتاحة = المتوفرة - المحجوزة.
        """
        return (self.quantity_on_hand or DECIMAL_ZERO) - (
            self.quantity_reserved or DECIMAL_ZERO
        )

    @property
    def is_below_min(self) -> bool:
        """
        هل الرصيد الحالي أقل من الحد الأدنى المضبوط؟
        """
        if not self.min_stock:
            return False
        return self.quantity_on_hand < self.min_stock


# ============================================================
# إعدادات المخزون العامة
# ============================================================
class InventorySettings(SingletonModel):
    """
    إعدادات المخزون العامة (مثل بادئات ترقيم حركات المخزون).
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
