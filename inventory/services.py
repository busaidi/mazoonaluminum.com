# inventory/services.py
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils.translation import gettext_lazy as _

from .models import StockLevel, StockMove


# ============================================================
# Core helpers to adjust stock levels
# ============================================================

@transaction.atomic
def _adjust_stock_level(*, product, warehouse, location, delta: Decimal) -> StockLevel:
    """
    يعدّل مستوى المخزون (quantity_on_hand) بمقدار delta.
    إذا لم يوجد StockLevel لهذا المنتج + (مخزن/موقع) يتم إنشاؤه بصفر ثم التطبيق.

    نستخدم select_for_update + F expressions لسلامة التوازي (concurrency).
    """
    if delta == 0:
        # لا حاجة لأي استعلامات إذا ما في تغيير
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

    # نستخدم F expression لتحديث الكمية بأمان في بيئة multi-user
    level.quantity_on_hand = F("quantity_on_hand") + Decimal(delta)
    level.save(update_fields=["quantity_on_hand"])

    # نرجع القيمة الجديدة بعد التحديث من قاعدة البيانات
    level.refresh_from_db(fields=["quantity_on_hand"])
    return level


def _apply_move_delta(move: StockMove, *, factor: Decimal) -> None:
    """
    يطبّق تأثير حركة مخزون واحدة على StockLevel.

    factor:
      +1  = تطبيق الحركة (posting)
      -1  = عكس الحركة (unposting أو حذف)
    """
    qty = (move.quantity or Decimal("0")) * factor
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
            delta=qty,
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
        # ننقص من المصدر
        _adjust_stock_level(
            product=move.product,
            warehouse=move.from_warehouse,
            location=move.from_location,
            delta=-qty,
        )
        # نضيف للوجهة
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
