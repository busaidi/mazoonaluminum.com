# inventory/services.py

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import TYPE_CHECKING, Optional, Dict, Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.utils.translation import gettext as _

# ✅ الاستيراد الموحد كما في ملف Sales
from core.models import AuditLog, Notification
from core.services.audit import log_event

from .models import (
    StockLevel,
    StockMove,
    StockMoveLine,
    InventorySettings,
    Product,
    InventoryAdjustment,
    StockLocation,
    InventoryAdjustmentLine
)

if TYPE_CHECKING:
    from django.contrib.auth import get_user_model

    User = get_user_model()

DECIMAL_ZERO = Decimal("0.000")


# ============================================================
# 1. Internal Helpers (Audit & Notifications)
# ============================================================

def _notify_user(
        recipient: User,
        verb: str,
        level: str,
        target_obj=None,
        url: str = "",
) -> None:
    """إنشاء إشعار للمستخدم."""
    if not recipient or not recipient.is_active:
        return

    Notification.objects.create(
        recipient=recipient,
        verb=verb,
        level=level,
        target=target_obj,
        url=url,
    )


def _build_move_audit_extra(move: StockMove, *, factor: Decimal | None = None) -> Dict[str, Any]:
    """
    بناء بيانات JSON إضافية.
    ⚠️ يتم تحويل Decimal إلى str لتجنب مشاكل JSON Serialization.
    """
    try:
        lines_count = move.lines.count()
        total_qty = move.lines.aggregate(t=Sum("quantity"))["t"] or 0
    except Exception:
        lines_count = 0
        total_qty = 0

    extra = {
        "move_type": str(move.move_type),
        "status": str(move.status),
        "reference": str(move.reference or ""),
        "lines_count": lines_count,
        "total_quantity": str(total_qty),
    }

    if move.from_warehouse_id:
        extra["from_warehouse"] = move.from_warehouse.name
    if move.to_warehouse_id:
        extra["to_warehouse"] = move.to_warehouse.name
    if factor is not None:
        extra["factor"] = str(factor)

    return extra


def _build_reservation_audit_extra(stock_level: StockLevel, delta: Decimal) -> Dict[str, Any]:
    return {
        "product": stock_level.product.code,
        "warehouse": stock_level.warehouse.name,
        "location": stock_level.location.name,
        "delta_reserved": str(delta),
        "current_reserved": str(stock_level.quantity_reserved),
    }


# ============================================================
# 2. Domain Logic (Costing & Stock Calculations)
# ============================================================

def _update_product_average_cost(move: StockMove) -> None:
    """تحديث متوسط التكلفة (Weighted Average)."""
    if move.move_type != StockMove.MoveType.IN:
        return

    # استخدام iterator للأداء العالي
    for line in move.lines.select_related("product").iterator():
        if line.product.product_type != Product.ProductType.STOCKABLE:
            continue

        incoming_qty = line.get_base_quantity()
        incoming_cost = line.cost_price or DECIMAL_ZERO

        if incoming_qty <= 0:
            continue

        # 🔒 Locking
        product = Product.objects.select_for_update().get(pk=line.product_id)

        current_total_qty = product.total_on_hand
        current_avg_cost = product.average_cost or DECIMAL_ZERO

        # Logic: إذا الرصيد الحالي <= 0، السعر الجديد هو سعر الشراء فقط (لمنع تشوه المتوسط)
        if current_total_qty <= 0:
            new_avg_cost = incoming_cost
        else:
            current_total_value = current_total_qty * current_avg_cost
            incoming_total_value = incoming_qty * incoming_cost
            new_total_qty = current_total_qty + incoming_qty

            if new_total_qty > 0:
                new_avg_cost = (current_total_value + incoming_total_value) / new_total_qty
            else:
                new_avg_cost = incoming_cost

        # تحديث فقط عند التغير
        if abs(product.average_cost - new_avg_cost) > Decimal("0.0001"):
            product.average_cost = new_avg_cost
            product.save(update_fields=["average_cost"])


def _snapshot_out_cost(move: StockMove) -> None:
    """تثبيت التكلفة للحركات الصادرة."""
    if move.move_type != StockMove.MoveType.OUT:
        return

    updates = []
    for line in move.lines.select_related("product").all():
        if line.cost_price == DECIMAL_ZERO and line.product.average_cost > 0:
            line.cost_price = line.product.average_cost
            updates.append(line)

    if updates:
        StockMoveLine.objects.bulk_update(updates, ["cost_price"])


def _adjust_stock_level(
        *, product: Product, warehouse, location, delta: Decimal
) -> StockLevel:
    """تعديل الرصيد المخزني مع القفل (Locking)."""

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
    """التحقق من الرصيد السالب قبل التنفيذ."""
    settings = InventorySettings.get_solo()
    if settings.allow_negative_stock:
        return

    if move.move_type == StockMove.MoveType.IN:
        return

    source_wh = move.from_warehouse
    source_loc = move.from_location

    if not source_wh or not source_loc:
        return

    requirements = defaultdict(Decimal)
    product_names = {}

    for line in move.lines.select_related("product").all():
        key = (line.product_id, source_wh.id, source_loc.id)
        qty = line.get_base_quantity()
        requirements[key] += qty
        product_names[line.product_id] = line.product.name

    for (prod_id, wh_id, loc_id), required_qty in requirements.items():
        try:
            level = StockLevel.objects.select_for_update().get(
                product_id=prod_id, warehouse_id=wh_id, location_id=loc_id
            )
            current_qty = level.quantity_on_hand
        except StockLevel.DoesNotExist:
            current_qty = DECIMAL_ZERO

        if current_qty < required_qty:
            prod_name = product_names.get(prod_id, _("Unknown Product"))
            raise ValidationError(
                _("الرصيد غير كافٍ للمنتج '%(prod)s'. المتاح: %(curr)s، المطلوب: %(req)s.") % {
                    "prod": prod_name,
                    "curr": current_qty,
                    "req": required_qty
                }
            )


def _apply_move_delta(move: StockMove, *, factor: Decimal) -> None:
    """تطبيق الحركة على الأرصدة."""
    for line in move.lines.select_related("product", "uom").iterator():
        if not getattr(line.product, "is_stock_item", True):
            continue

        qty = line.get_base_quantity() * factor
        if qty == 0:
            continue

        if move.move_type == StockMove.MoveType.IN:
            _adjust_stock_level(
                product=line.product,
                warehouse=move.to_warehouse,
                location=move.to_location,
                delta=qty
            )
        elif move.move_type == StockMove.MoveType.OUT:
            _adjust_stock_level(
                product=line.product,
                warehouse=move.from_warehouse,
                location=move.from_location,
                delta=-qty
            )
        elif move.move_type == StockMove.MoveType.TRANSFER:
            _adjust_stock_level(
                product=line.product,
                warehouse=move.from_warehouse,
                location=move.from_location,
                delta=-qty
            )
            _adjust_stock_level(
                product=line.product,
                warehouse=move.to_warehouse,
                location=move.to_location,
                delta=qty
            )


# ============================================================
# 3. Public Services (Transactional)
# ============================================================

@transaction.atomic
def confirm_stock_move(move: StockMove, user: Optional[User] = None) -> StockMove:
    """DRAFT -> DONE"""
    move = StockMove.objects.select_for_update().get(pk=move.pk)

    if move.status == StockMove.Status.DONE:
        return move

    if move.status != StockMove.Status.DRAFT:
        raise ValidationError(_("يجب أن تكون الحالة مسودة لتأكيد الحركة."))

    # 1. Validation
    _validate_negative_stock(move)

    # 2. Cost Updates
    if move.move_type == StockMove.MoveType.IN:
        _update_product_average_cost(move)
    elif move.move_type == StockMove.MoveType.OUT:
        _snapshot_out_cost(move)

    # 3. Update Stock Levels
    _apply_move_delta(move, factor=Decimal("1"))

    # 4. Update Status
    move.status = StockMove.Status.DONE
    move.save(update_fields=["status"])

    # 5. Audit Log (Inside transaction)
    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=f"Stock Move confirmed: {move.reference}",
        actor=user,
        target=move,
        extra=_build_move_audit_extra(move, factor=Decimal("1"))
    )

    # 6. Notification
    if move.created_by and move.created_by != user:
        _notify_user(
            recipient=move.created_by,
            verb=_("تم تأكيد الحركة المخزنية رقم %(ref)s") % {"ref": move.reference},
            level=Notification.Levels.SUCCESS,
            target_obj=move
        )

    return move


@transaction.atomic
def cancel_stock_move(move: StockMove, user: Optional[User] = None) -> StockMove:
    """DONE/DRAFT -> CANCELLED"""
    move = StockMove.objects.select_for_update().get(pk=move.pk)

    if move.status == StockMove.Status.CANCELLED:
        raise ValidationError(_("الحركة ملغاة بالفعل."))

    was_done = (move.status == StockMove.Status.DONE)

    # إذا كانت منفذة، نعكس الكميات
    if was_done:
        _apply_move_delta(move, factor=Decimal("-1"))

    move.status = StockMove.Status.CANCELLED
    move.save(update_fields=["status"])

    # Audit
    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=f"Stock Move cancelled: {move.reference}",
        actor=user,
        target=move,
        extra=_build_move_audit_extra(move, factor=Decimal("-1") if was_done else None)
    )

    # Notification
    if move.created_by and move.created_by != user:
        _notify_user(
            recipient=move.created_by,
            verb=_("تم إلغاء الحركة المخزنية رقم %(ref)s") % {"ref": move.reference},
            level=Notification.Levels.WARNING,
            target_obj=move,
        )

    return move


@transaction.atomic
def reserve_stock(
        product: Product,
        warehouse,
        location,
        quantity: Decimal,
        check_availability: bool = True,
        user: Optional[User] = None
) -> StockLevel:
    """حجز كمية."""
    if quantity <= 0:
        raise ValidationError(_("الكمية يجب أن تكون موجبة."))

    level = _adjust_stock_level(
        product=product, warehouse=warehouse, location=location, delta=0
    )

    if check_availability:
        current_avail = level.quantity_on_hand - level.quantity_reserved
        if current_avail < quantity:
            raise ValidationError(
                _("الكمية المتاحة (%(avail)s) غير كافية للحجز (%(req)s).") %
                {"avail": current_avail, "req": quantity}
            )

    level.quantity_reserved = F("quantity_reserved") + quantity
    level.save(update_fields=["quantity_reserved"])
    level.refresh_from_db(fields=["quantity_reserved"])

    # Audit
    log_event(
        action=AuditLog.Action.UPDATE,
        message=f"Reserved stock: {quantity} for {product.code}",
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
        user: Optional[User] = None
) -> StockLevel:
    """فك حجز."""
    if quantity <= 0:
        raise ValidationError(_("الكمية يجب أن تكون موجبة."))

    level = StockLevel.objects.select_for_update().get(
        product=product, warehouse=warehouse, location=location
    )

    if level.quantity_reserved < quantity:
        raise ValidationError(_("لا يمكن فك حجز أكبر من الكمية المحجوزة."))

    level.quantity_reserved = F("quantity_reserved") - quantity
    level.save(update_fields=["quantity_reserved"])
    level.refresh_from_db(fields=["quantity_reserved"])

    # Audit
    log_event(
        action=AuditLog.Action.UPDATE,
        message=f"Released stock: {quantity} for {product.code}",
        actor=user,
        target=level,
        extra=_build_reservation_audit_extra(level, -quantity)
    )

    return level


@transaction.atomic
def create_inventory_session(
        warehouse,
        user: User,
        category=None,
        location=None,
        note: str = ""
) -> InventoryAdjustment:
    """إنشاء وثيقة جرد."""
    if location and location.warehouse_id != warehouse.id:
        raise ValidationError(_("الموقع لا يتبع المستودع المختار."))

    adjustment = InventoryAdjustment.objects.create(
        warehouse=warehouse,
        category=category,
        location=location,
        note=note,
        status=InventoryAdjustment.Status.DRAFT,
        created_by=user,
    )

    # Snapshot
    levels = StockLevel.objects.filter(warehouse=warehouse).exclude(quantity_on_hand=0)
    if location:
        levels = levels.filter(location=location)
    if category:
        levels = levels.filter(product__category=category)

    lines_to_create = [
        InventoryAdjustmentLine(
            adjustment=adjustment,
            product=level.product,
            location=level.location,
            theoretical_qty=level.quantity_on_hand,
            counted_qty=None
        )
        for level in levels.select_related("product", "location")
    ]
    InventoryAdjustmentLine.objects.bulk_create(lines_to_create)

    # Audit
    log_event(
        action=AuditLog.Action.CREATE,
        message=f"Inventory Session Started",
        actor=user,
        target=adjustment,
        extra={"lines_count": len(lines_to_create), "warehouse": warehouse.name}
    )

    return adjustment


@transaction.atomic
def apply_inventory_adjustment(adjustment: InventoryAdjustment, user: User) -> None:
    """ترحيل الجرد وإنشاء حركات التسوية."""
    adjustment = InventoryAdjustment.objects.select_for_update().get(pk=adjustment.pk)

    if adjustment.status == InventoryAdjustment.Status.APPLIED:
        raise ValidationError(_("تم ترحيل الجرد مسبقاً."))

    grouped_diffs = defaultdict(lambda: {'gain': [], 'loss': []})
    location_ids = set()
    has_diffs = False

    # حساب الفروقات
    for line in adjustment.lines.select_related("product", "location").all():
        if line.counted_qty is None:
            continue

        try:
            current_level = StockLevel.objects.select_for_update().get(
                product=line.product,
                warehouse=adjustment.warehouse,
                location=line.location
            )
            current_qty = current_level.quantity_on_hand
        except StockLevel.DoesNotExist:
            current_qty = DECIMAL_ZERO

        real_diff = line.counted_qty - current_qty

        if real_diff == 0:
            continue

        has_diffs = True
        line.real_diff_for_move = real_diff
        location_ids.add(line.location.id)

        if real_diff > 0:
            grouped_diffs[line.location.id]['gain'].append(line)
        else:
            grouped_diffs[line.location.id]['loss'].append(line)

    # إذا لم توجد فروقات، نغلق الجرد فقط
    if not has_diffs:
        adjustment.status = InventoryAdjustment.Status.APPLIED
        adjustment.updated_by = user
        adjustment.save(update_fields=["status", "updated_by"])
        return

    # إنشاء الحركات
    locations_map = {loc.id: loc for loc in StockLocation.objects.filter(id__in=location_ids)}
    moves_count = 0

    for loc_id, types in grouped_diffs.items():
        location = locations_map[loc_id]

        # 1. زيادة (Gain)
        if types['gain']:
            move_in = StockMove.objects.create(
                move_type=StockMove.MoveType.IN,
                to_warehouse=adjustment.warehouse,
                to_location=location,
                status=StockMove.Status.DRAFT,
                reference=f"ADJ-IN-{adjustment.pk}-{location.code}",
                note=_("تسوية جردية - زيادة"),
                adjustment=adjustment,
                created_by=user
            )
            StockMoveLine.objects.bulk_create([
                StockMoveLine(
                    move=move_in,
                    product=l.product,
                    quantity=abs(l.real_diff_for_move),
                    uom=l.product.base_uom,
                    cost_price=l.product.average_cost
                ) for l in types['gain']
            ])
            confirm_stock_move(move_in, user=user)
            moves_count += 1

        # 2. عجز (Loss)
        if types['loss']:
            move_out = StockMove.objects.create(
                move_type=StockMove.MoveType.OUT,
                from_warehouse=adjustment.warehouse,
                from_location=location,
                status=StockMove.Status.DRAFT,
                reference=f"ADJ-OUT-{adjustment.pk}-{location.code}",
                note=_("تسوية جردية - عجز"),
                adjustment=adjustment,
                created_by=user
            )
            StockMoveLine.objects.bulk_create([
                StockMoveLine(
                    move=move_out,
                    product=l.product,
                    quantity=abs(l.real_diff_for_move),
                    uom=l.product.base_uom
                ) for l in types['loss']
            ])
            confirm_stock_move(move_out, user=user)
            moves_count += 1

    adjustment.status = InventoryAdjustment.Status.APPLIED
    adjustment.updated_by = user
    adjustment.save(update_fields=["status", "updated_by"])

    # Audit
    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=f"Inventory Adjustment Applied #{adjustment.pk}",
        actor=user,
        target=adjustment,
        extra={"moves_created": moves_count}
    )

    if adjustment.created_by and adjustment.created_by != user:
        _notify_user(
            recipient=adjustment.created_by,
            verb=_("تم ترحيل وثيقة الجرد رقم %(id)s") % {'id': adjustment.pk},
            level=Notification.Levels.INFO,
            target_obj=adjustment
        )