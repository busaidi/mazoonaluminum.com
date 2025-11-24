# inventory/services.py
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum, Q
from django.utils.translation import gettext_lazy as _

from .models import StockLevel, StockMove


# ============================================================
# Core helpers to adjust stock levels
# ============================================================

@transaction.atomic
def _adjust_stock_level(*, product, warehouse, location, delta: Decimal) -> StockLevel:
    """
    يعدّل مستوى المخزون (quantity_on_hand) بمقدار delta *بالوحدة الأساسية للمنتج* (base_uom).

    إذا لم يوجد StockLevel لهذا المنتج + (مخزن/موقع) يتم إنشاؤه بصفر ثم التطبيق.

    نستخدم select_for_update + F expressions لسلامة التوازي (concurrency).
    """
    if delta == 0:
        level, _ = StockLevel.objects.get_or_create(
            product=product,
            warehouse=warehouse,
            location=location,
            defaults={
                "quantity_on_hand": Decimal("0.000"),
                "quantity_reserved": Decimal("0.000"),
                "min_stock": Decimal("0.000"),
            },
        )
        return level

    level, created = (
        StockLevel.objects.select_for_update()
        .get_or_create(
            product=product,
            warehouse=warehouse,
            location=location,
            defaults={
                "quantity_on_hand": Decimal("0.000"),
                "quantity_reserved": Decimal("0.000"),
                "min_stock": Decimal("0.000"),
            },
        )
    )

    level.quantity_on_hand = F("quantity_on_hand") + Decimal(delta)
    level.save(update_fields=["quantity_on_hand"])
    level.refresh_from_db(fields=["quantity_on_hand"])
    return level



def _apply_move_delta(move: StockMove, *, factor: Decimal) -> None:
    """
    يطبّق تأثير حركة مخزون واحدة على StockLevel.

    factor:
      +1  = تطبيق الحركة (posting)
      -1  = عكس الحركة (unposting أو حذف)

    ملاحظة:
      - نستخدم get_base_quantity بحيث تكون كل التعديلات على StockLevel
        بوحدة القياس الأساسية للمنتج (product.base_uom) مهما كانت وحدة الحركة.
    """
    base_qty = move.get_base_quantity() or Decimal("0")
    qty = base_qty * factor
    if qty == 0:
        return

    # Incoming: نضيف للـ destination
    if move.move_type == StockMove.MoveType.IN:
        if not move.to_warehouse or not move.to_location:
            raise ValidationError(_("Incoming move requires destination warehouse and location."))
        _adjust_stock_level(
            product=move.product,
            warehouse=move.to_warehouse,
            location=move.to_location,
            delta=qty,  # qty بالـ base_uom
        )

    # Outgoing: نطرح من الـ source
    elif move.move_type == StockMove.MoveType.OUT:
        if not move.from_warehouse or not move.from_location:
            raise ValidationError(_("Outgoing move requires source warehouse and location."))
        _adjust_stock_level(
            product=move.product,
            warehouse=move.from_warehouse,
            location=move.from_location,
            delta=-qty,
        )

    # Transfer: من المصدر إلى الوجهة
    elif move.move_type == StockMove.MoveType.TRANSFER:
        if not (move.from_warehouse and move.from_location and move.to_warehouse and move.to_location):
            raise ValidationError(_("Transfer move requires both source and destination."))

        _adjust_stock_level(
            product=move.product,
            warehouse=move.from_warehouse,
            location=move.from_location,
            delta=-qty,
        )
        _adjust_stock_level(
            product=move.product,
            warehouse=move.to_warehouse,
            location=move.to_location,
            delta=qty,
        )



# ============================================================
# Status-driven posting logic
# ============================================================

def apply_stock_move_status_change(*, move: StockMove, old_status: str | None, is_create: bool) -> None:
    """
    تطبّق / تعكس أثر الحركة على المخزون بناءً على تغيير الحالة (status).

    القواعد:
      - عند الإنشاء:
          * DRAFT      → لا شيء
          * DONE       → تطبيق الحركة (factor = +1)
          * CANCELLED  → لا شيء
      - عند التعديل:
          * DRAFT      → DONE       => factor = +1
          * CANCELLED  → DONE       => factor = +1   (إعادة تفعيل)
          * DONE       → CANCELLED  => factor = -1   (إلغاء بعد التطبيق)
          * DONE       → DRAFT      => factor = -1   (رجوع لمسودة)
          * باقي الانتقالات لا تغيّر المخزون.
    """
    new_status = move.status

    # إنشاء جديد
    if is_create:
        if new_status == StockMove.Status.DONE:
            _apply_move_delta(move, factor=Decimal("1"))
        return

    # تحديث موجود مسبقاً
    if old_status is None or old_status == new_status:
        # لا تغيير بالحالة
        return

    transition_map: dict[tuple[str, str], Decimal] = {
        (StockMove.Status.DRAFT, StockMove.Status.DONE): Decimal("1"),
        (StockMove.Status.CANCELLED, StockMove.Status.DONE): Decimal("1"),
        (StockMove.Status.DONE, StockMove.Status.CANCELLED): Decimal("-1"),
        (StockMove.Status.DONE, StockMove.Status.DRAFT): Decimal("-1"),
    }

    factor = transition_map.get((old_status, new_status))
    if factor is None:
        # انتقال لا يؤثر على المخزون (مثلاً DRAFT → CANCELLED)
        return

    _apply_move_delta(move, factor=factor)


def apply_stock_move_on_delete(move: StockMove) -> None:
    """
    تُستدعى عند حذف حركة مخزون لعكس الأثر *فقط إذا كانت الحركة DONE*.
    """
    if move.status != StockMove.Status.DONE:
        return

    _apply_move_delta(move, factor=Decimal("-1"))


# ============================================================
# Reservation helpers (order-level reservations)
# ============================================================
# ============================================================
# Dashboard helpers
# ============================================================

def get_stock_summary_per_warehouse():
    """
    ملخص إجمالي الكمية لكل مستودع.
    يرجع QuerySet من dicts:
      - warehouse__code
      - warehouse__name
      - total_qty
    """
    return (
        StockLevel.objects
        .select_related("warehouse")
        .values("warehouse__code", "warehouse__name")
        .annotate(total_qty=Sum("quantity_on_hand"))
        .order_by("warehouse__code")
    )


def get_low_stock_levels():
    """
    جميع مستويات المخزون التي تحت الحد الأدنى:
      min_stock > 0 && quantity_on_hand < min_stock
    مع select_related للعرض في القوالب بدون N+1.
    """
    return (
        StockLevel.objects
        .select_related("product", "warehouse", "location")
        .filter(
            min_stock__gt=Decimal("0.000"),
            quantity_on_hand__lt=F("min_stock"),
        )
    )


@transaction.atomic
def reserve_stock_for_order(
    *,
    product,
    warehouse,
    location,
    quantity: Decimal,
    allow_negative: bool = False,
) -> StockLevel:
    """
    يحجز كمية من المخزون (quantity_reserved) لأجل طلب (Sales Order مثلاً).

    - يزيد quantity_reserved
    - لا يغيّر quantity_on_hand
    - يمكن ربطه بمناداة من OrderLine في تطبيق accounting.

    ملاحظة:
      - يفضّل تمرير location صريحة (مثلاً موقع الشحن الرئيسي في ذلك المخزن).
      - لو تحتاج تحديد location تلقائياً، ممكن تضيف منطق إضافي حسب نظامك.
    """
    if quantity <= 0:
        raise ValidationError(_("Reservation quantity must be positive."))

    level, created = (
        StockLevel.objects.select_for_update()
        .get_or_create(
            product=product,
            warehouse=warehouse,
            location=location,
            defaults={
                "quantity_on_hand": Decimal("0.000"),
                "quantity_reserved": Decimal("0.000"),
                "min_stock": Decimal("0.000"),
            },
        )
    )

    # الكمية المتاحة فعلياً = الموجود - المحجوز
    available = level.quantity_on_hand - level.quantity_reserved
    if not allow_negative and available < quantity:
        raise ValidationError(
            _("Not enough available stock to reserve. Available: %(available)s, requested: %(requested)s"),
            params={"available": available, "requested": quantity},
        )

    level.quantity_reserved = F("quantity_reserved") + Decimal(quantity)
    level.save(update_fields=["quantity_reserved"])
    level.refresh_from_db(fields=["quantity_reserved"])
    return level


@transaction.atomic
def release_stock_reservation(
    *,
    product,
    warehouse,
    location,
    quantity: Decimal,
) -> StockLevel:
    """
    يفك الحجز عن كمية من المخزون (يقلل quantity_reserved).

    يُستخدم عند:
      - إلغاء الطلب
      - تحويل الطلب لشحنة فعلية (StockMove OUT) حيث سيتم تقليل on_hand أيضاً.
    """
    if quantity <= 0:
        raise ValidationError(_("Release quantity must be positive."))

    try:
        level = (
            StockLevel.objects.select_for_update()
            .get(
                product=product,
                warehouse=warehouse,
                location=location,
            )
        )
    except StockLevel.DoesNotExist:
        # لا يوجد مستوى أصلاً، يعني لا يوجد شيء محجوز
        raise ValidationError(_("No reserved stock to release for this product/location."))

    if level.quantity_reserved < quantity:
        raise ValidationError(
            _("Cannot release more than reserved. Reserved: %(reserved)s, requested: %(requested)s"),
            params={"reserved": level.quantity_reserved, "requested": quantity},
        )

    level.quantity_reserved = F("quantity_reserved") - Decimal(quantity)
    level.save(update_fields=["quantity_reserved"])
    level.refresh_from_db(fields=["quantity_reserved"])
    return level


def get_available_stock(*, product, warehouse, location) -> Decimal:
    """
    يعيد الكمية المتاحة (on_hand - reserved) لموقع معين.
    مفيدة قبل تأكيد طلب جديد.
    """
    try:
        level = StockLevel.objects.get(
            product=product,
            warehouse=warehouse,
            location=location,
        )
    except StockLevel.DoesNotExist:
        return Decimal("0.000")

    return (level.quantity_on_hand or Decimal("0.000")) - (level.quantity_reserved or Decimal("0.000"))
# ============================================================
# Stock level list helpers
# ============================================================

def filter_below_min_stock_levels(qs):
    """
    يطبّق فلتر 'تحت الحد الأدنى' على QuerySet معيّن.
    يُستخدم في شاشة مستويات المخزون وغيرها.
    """
    return qs.filter(
        min_stock__gt=Decimal("0.000"),
        quantity_on_hand__lt=F("min_stock"),
    )


def get_low_stock_total() -> int:
    """
    يعيد العدد الإجمالي لمستويات المخزون تحت الحد الأدنى
    (بدون أي فلاتر بحث).
    """
    base_qs = StockLevel.objects.all()
    return filter_below_min_stock_levels(base_qs).count()
# ============================================================
# Stock move list helpers
# ============================================================

def filter_stock_moves_queryset(
    qs,
    *,
    q: str | None = None,
    move_type: str | None = None,
    status: str | None = None,
):
    """
    يطبّق فلاتر البحث القياسية على QuerySet لحركات المخزون:

      - q         : بحث بالكود / اسم المنتج / المرجع / كود المخزن
      - move_type : نوع الحركة (in / out / transfer)
      - status    : حالة الحركة (draft / done / cancelled)

    لا يغيّر select_related أو order_by — هذا مسئولية الفيو.
    """
    if q:
        q = q.strip()
        if q:
            qs = qs.filter(
                Q(product__code__icontains=q)
                | Q(product__name__icontains=q)
                | Q(reference__icontains=q)
                | Q(from_warehouse__code__icontains=q)
                | Q(to_warehouse__code__icontains=q)
            )

    # فلترة نوع الحركة (نتأكد أن القيمة من الخيارات المسموحة)
    if move_type in dict(StockMove.MoveType.choices):
        qs = qs.filter(move_type=move_type)

    # فلترة الحالة
    if status in dict(StockMove.Status.choices):
        qs = qs.filter(status=status)

    return qs
# ============================================================
# Product list helpers
# ============================================================

def filter_products_queryset(
    qs,
    *,
    q: str | None = None,
    category_id: str | None = None,
    only_published: bool = False,
):
    """
    يطبّق فلاتر البحث القياسية على QuerySet للمنتجات:

      - q             : بحث بالكود / الاسم / الوصف المختصر
      - category_id   : رقم التصنيف (id) لتقييد النتائج
      - only_published: لو True يعرض المنتجات المنشورة فقط

    لا يغيّر select_related أو order_by — هذا مسئولية الفيو.
    """
    if q:
        q = q.strip()
        if q:
            qs = qs.filter(
                Q(code__icontains=q)
                | Q(name__icontains=q)
                | Q(short_description__icontains=q)
            )

    if category_id:
        qs = qs.filter(category_id=category_id)

    if only_published:
        qs = qs.filter(is_published=True)

    return qs
