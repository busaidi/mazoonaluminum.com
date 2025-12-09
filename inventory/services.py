# inventory/services.py

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.utils.translation import gettext as _

from core.models import AuditLog
from core.services.audit import log_event

from .models import (
    StockLevel,
    StockMove,
    StockMoveLine,
    InventorySettings,
    Product
)

DECIMAL_ZERO = Decimal("0.000")


# ============================================================
# دوال مساعدة لسجل التدقيق (Audit Helpers)
# ============================================================

def _build_move_audit_extra(move: StockMove, *, factor: Decimal | None = None) -> dict:
    """بناء بيانات إضافية لسجل التدقيق عند تغيير حالة الحركة."""
    try:
        lines_count = move.lines.count()
        total_qty = move.lines.aggregate(t=Sum("quantity"))["t"] or 0
    except Exception:
        lines_count = 0
        total_qty = 0

    extra = {
        "move_type": move.move_type,
        "status": move.status,
        "reference": move.reference,
        "lines_count": lines_count,
        "total_quantity": str(total_qty),
    }

    if move.from_warehouse_id: extra["from_warehouse"] = move.from_warehouse.code
    if move.to_warehouse_id: extra["to_warehouse"] = move.to_warehouse.code
    if factor is not None: extra["factor"] = str(factor)

    return extra


def _build_reservation_audit_extra(stock_level: StockLevel, delta: Decimal) -> dict:
    """بيانات إضافية عند الحجز أو فك الحجز."""
    return {
        "product": stock_level.product.code,
        "warehouse": stock_level.warehouse.code,
        "location": stock_level.location.code,
        "delta_reserved": str(delta),
        "current_reserved": str(stock_level.quantity_reserved),
    }


# ============================================================
# منطق التكلفة (Global Weighted Average Cost)
# ============================================================

def _update_product_average_cost(move: StockMove) -> None:
    """
    تحديث متوسط التكلفة للمنتجات بناءً على حركة واردة (IN).
    المعادلة:
    New Avg = ((Current Qty * Current Avg) + (Incoming Qty * Incoming Cost)) / (Current Qty + Incoming Qty)
    """
    if move.move_type != StockMove.MoveType.IN:
        return

    # استخدام select_related لتقليل الاستعلامات
    for line in move.lines.select_related("product").all():
        if line.product.product_type != Product.ProductType.STOCKABLE:
            continue

        incoming_qty = line.get_base_quantity()
        incoming_cost = line.cost_price or DECIMAL_ZERO

        if incoming_qty <= 0:
            continue

        # 🔒 Critical Section: قفل المنتج لمنع Race Condition على average_cost
        product = Product.objects.select_for_update().get(pk=line.product_id)

        current_total_qty = product.total_on_hand
        current_avg_cost = product.average_cost or DECIMAL_ZERO

        current_total_value = current_total_qty * current_avg_cost
        incoming_total_value = incoming_qty * incoming_cost

        new_total_qty = current_total_qty + incoming_qty

        if new_total_qty > 0:
            new_avg_cost = (current_total_value + incoming_total_value) / new_total_qty
            product.average_cost = new_avg_cost
            product.save(update_fields=["average_cost"])


def _snapshot_out_cost(move: StockMove) -> None:
    """
    للحركات الصادرة (OUT): ننسخ متوسط التكلفة الحالي للمنتج إلى البند.
    """
    if move.move_type != StockMove.MoveType.OUT:
        return

    updates = []
    for line in move.lines.select_related("product").all():
        if line.cost_price == DECIMAL_ZERO and line.product.average_cost > 0:
            line.cost_price = line.product.average_cost
            updates.append(line)

    if updates:
        StockMoveLine.objects.bulk_update(updates, ["cost_price"])


# ============================================================
# دوال التحديث الجوهري (Core Adjustment)
# ============================================================

def _adjust_stock_level(
        *,
        product: Product,
        warehouse,
        location,
        delta: Decimal,
) -> StockLevel:
    """
    تعديل رصيد المخزون (quantity_on_hand).

    ملاحظات للمطورين:
    - يجب استدعاؤها دائماً من داخل سياق @transaction.atomic خارجي.
    - تقوم بعمل select_for_update على StockLevel لقفل السجل أثناء التعديل.
    """
    level, _ = StockLevel.objects.select_for_update().get_or_create(
        product=product,
        warehouse=warehouse,
        location=location,
        defaults={
            "quantity_on_hand": DECIMAL_ZERO,
            "quantity_reserved": DECIMAL_ZERO,
            "min_stock": DECIMAL_ZERO,
        },
    )

    if delta != 0:
        level.quantity_on_hand = F("quantity_on_hand") + delta
        level.save(update_fields=["quantity_on_hand"])
        level.refresh_from_db(fields=["quantity_on_hand"])

    return level


def _validate_negative_stock(move: StockMove) -> None:
    """
    يتحقق من أن الحركات الصادرة أو التحويلات لن تُنقص المخزون عن الصفر
    إذا كان الإعداد يمنع المخزون السالب.
    """
    settings = InventorySettings.get_solo()
    if settings.allow_negative_stock:
        return

    if move.move_type == StockMove.MoveType.IN:
        return

    source_wh = move.from_warehouse
    source_loc = move.from_location

    if not source_wh or not source_loc:
        return

    # تجميع الكميات المطلوبة + تخزين أسماء المنتجات
    requirements = {}
    product_names = {}

    for line in move.lines.select_related("product").all():
        key = (line.product_id, source_wh.id, source_loc.id)
        qty = line.get_base_quantity()

        requirements[key] = requirements.get(key, DECIMAL_ZERO) + qty
        product_names[line.product_id] = line.product.name

    # التحقق من الأرصدة
    for (prod_id, wh_id, loc_id), required_qty in requirements.items():
        try:
            # 🔒 Lock: قفل السجل لمنع أي صرف متزامن يكسر الرصيد
            level = StockLevel.objects.select_for_update().get(
                product_id=prod_id,
                warehouse_id=wh_id,
                location_id=loc_id
            )
            current_qty = level.quantity_on_hand
        except StockLevel.DoesNotExist:
            current_qty = DECIMAL_ZERO

        if current_qty < required_qty:
            prod_name = product_names.get(prod_id, _("منتج غير معروف"))

            raise ValidationError(
                _(
                    "لا يتوفر رصيد كافٍ للمنتج '%(prod)s'. "
                    "الموجود: %(curr)s، المطلوب: %(req)s. "
                    "(الإعدادات تمنع المخزون السالب)"
                ) % {
                    "prod": prod_name,
                    "curr": current_qty,
                    "req": required_qty
                }
            )


def _apply_move_delta(move: StockMove, *, factor: Decimal) -> None:
    """
    توجيه الكميات للمستودعات الصحيحة بناءً على نوع الحركة.
    """
    for line in move.lines.select_related("product", "uom").iterator():
        product = line.product
        if not getattr(product, "is_stock_item", True):
            continue

        qty = line.get_base_quantity() * factor
        if qty == 0: continue

        if move.move_type == StockMove.MoveType.IN:
            _adjust_stock_level(
                product=product,
                warehouse=move.to_warehouse,
                location=move.to_location,
                delta=qty
            )

        elif move.move_type == StockMove.MoveType.OUT:
            _adjust_stock_level(
                product=product,
                warehouse=move.from_warehouse,
                location=move.from_location,
                delta=-qty
            )

        elif move.move_type == StockMove.MoveType.TRANSFER:
            _adjust_stock_level(
                product=product,
                warehouse=move.from_warehouse,
                location=move.from_location,
                delta=-qty
            )
            _adjust_stock_level(
                product=product,
                warehouse=move.to_warehouse,
                location=move.to_location,
                delta=qty
            )


# ============================================================
# العمليات الرئيسية (Public Services)
# ============================================================

@transaction.atomic
def confirm_stock_move(move: StockMove, user=None) -> StockMove:
    """
    تأكيد حركة المخزون (DRAFT -> DONE).
    """
    move = StockMove.objects.select_for_update().get(pk=move.pk)

    if move.status == StockMove.Status.DONE:
        return move

    if move.status != StockMove.Status.DRAFT:
        raise ValidationError(_("لا يمكن تأكيد حركة ليست في حالة مسودة."))

    # 1. فحص السالب
    _validate_negative_stock(move)

    # 2. تحديث التكاليف
    if move.move_type == StockMove.MoveType.IN:
        _update_product_average_cost(move)

    if move.move_type == StockMove.MoveType.OUT:
        _snapshot_out_cost(move)

    # 3. ترحيل الكميات
    _apply_move_delta(move, factor=Decimal("1"))

    # 4. تحديث الحالة
    move.status = StockMove.Status.DONE
    move.save(update_fields=["status"])

    # 5. Audit Log
    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=f"Stock Move confirmed: {move.reference or move.pk}",
        actor=user,
        target=move,
        extra=_build_move_audit_extra(move, factor=Decimal("1"))
    )

    return move


@transaction.atomic
def cancel_stock_move(move: StockMove, user=None) -> StockMove:
    """
    إلغاء حركة المخزون.
    """
    move = StockMove.objects.select_for_update().get(pk=move.pk)

    if move.status == StockMove.Status.CANCELLED:
        raise ValidationError(_("الحركة ملغاة بالفعل."))

    # حفظ الحالة القديمة لتحديد ما إذا كان يجب عكس المخزون
    was_done = (move.status == StockMove.Status.DONE)

    if was_done:
        _apply_move_delta(move, factor=Decimal("-1"))

    move.status = StockMove.Status.CANCELLED
    move.save(update_fields=["status"])

    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=f"Stock Move cancelled: {move.reference or move.pk}",
        actor=user,
        target=move,
        extra=_build_move_audit_extra(
            move,
            factor=Decimal("-1") if was_done else None
        )
    )

    return move


# ============================================================
# خدمات الحجز (Reservation Services)
# ============================================================

@transaction.atomic
def reserve_stock(
        product: Product,
        warehouse,
        location,
        quantity: Decimal,
        check_availability: bool = True,
        user=None
) -> StockLevel:
    """
    حجز كمية (زيادة quantity_reserved).
    """
    if quantity <= 0:
        raise ValidationError(_("كمية الحجز يجب أن تكون موجبة."))

    # ضمان وجود الـ StockLevel
    level = _adjust_stock_level(
        product=product, warehouse=warehouse, location=location, delta=0
    )

    if check_availability:
        available = level.available_quantity
        if available < quantity:
            raise ValidationError(
                _("الكمية المتاحة (%(avail)s) غير كافية للحجز المطلوب (%(req)s).")
                % {"avail": available, "req": quantity}
            )

    level.quantity_reserved = F("quantity_reserved") + quantity
    level.save(update_fields=["quantity_reserved"])
    level.refresh_from_db(fields=["quantity_reserved"])

    log_event(
        action=AuditLog.Action.UPDATE,
        message=f"Reserved stock for {product.code}",
        actor=user,
        target=level,
        extra=_build_reservation_audit_extra(level, quantity)
    )

    return level


@transaction.atomic
def release_stock(
        product: Product,
        warehouse,
        location,
        quantity: Decimal,
        user=None
) -> StockLevel:
    """
    فك حجز كمية (إنقاص quantity_reserved).
    """
    if quantity <= 0:
        raise ValidationError(_("الكمية يجب أن تكون موجبة."))

    level = StockLevel.objects.select_for_update().get(
        product=product, warehouse=warehouse, location=location
    )

    if level.quantity_reserved < quantity:
        raise ValidationError(_("لا يمكن فك حجز كمية أكبر من المحجوز فعلياً."))

    level.quantity_reserved = F("quantity_reserved") - quantity
    level.save(update_fields=["quantity_reserved"])
    level.refresh_from_db(fields=["quantity_reserved"])

    log_event(
        action=AuditLog.Action.UPDATE,
        message=f"Released stock reservation for {product.code}",
        actor=user,
        target=level,
        extra=_build_reservation_audit_extra(level, -quantity)
    )

    return level


# ============================================================
# دوال التوافق (Legacy)
# ============================================================

def apply_stock_move_status_change(*args, **kwargs):
    pass