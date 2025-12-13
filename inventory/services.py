# /home/ubuntu/PycharmProjects/mazoonaluminum.com/inventory/services.py

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Optional, TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.utils.translation import gettext as _

from core.models import AuditLog, Notification
from core.services.audit import log_event
from core.services.notifications import create_notification

from .models import (
    InventoryAdjustment,
    InventoryAdjustmentLine,
    InventorySettings,
    Product,
    StockLevel,
    StockLocation,
    StockMove,
    StockMoveLine,
)

if TYPE_CHECKING:
    from django.contrib.auth import get_user_model
    User = get_user_model()

DECIMAL_ZERO = Decimal("0.000")
DECIMAL_ONE = Decimal("1.000")
DECIMAL_MINUS_ONE = Decimal("-1.000")


# ============================================================
# Notifications (Unified helper)
# ============================================================

def _notify(
    *,
    recipient: Optional["User"],
    verb: str,
    target: Optional[Any] = None,
    level: str = Notification.Levels.INFO,
    url: str | None = None,
) -> None:
    """
    Create a notification using core service.
    Uses Notification.Levels.* enums for level.
    """
    if recipient is None:
        return
    if not getattr(recipient, "is_active", True):
        return

    create_notification(
        recipient=recipient,
        verb=verb,
        target=target,
        level=level,
        url=url,
    )


# ============================================================
# Audit "extra" builders (JSON-safe)
# ============================================================

def _build_move_audit_extra(move: StockMove, *, factor: Decimal | None = None) -> dict[str, Any]:
    try:
        totals = move.lines.aggregate(
            lines_count=Sum(1),  # not supported; fallback below
        )
        # Django doesn't support Sum(1) like this. We'll compute separately:
        lines_count = move.lines.count()
        total_qty = move.lines.aggregate(t=Sum("quantity"))["t"] or DECIMAL_ZERO
    except Exception:
        lines_count = 0
        total_qty = DECIMAL_ZERO

    extra: dict[str, Any] = {
        "move_type": str(move.move_type),
        "status": str(move.status),
        "reference": str(move.reference or ""),
        "lines_count": int(lines_count),
        "total_quantity": str(total_qty),
    }

    if move.from_warehouse_id:
        extra["from_warehouse"] = str(move.from_warehouse.code)
    if move.from_location_id:
        extra["from_location"] = str(move.from_location.code)
    if move.to_warehouse_id:
        extra["to_warehouse"] = str(move.to_warehouse.code)
    if move.to_location_id:
        extra["to_location"] = str(move.to_location.code)

    if factor is not None:
        extra["factor"] = str(factor)

    return extra


def _build_reservation_audit_extra(level: StockLevel, delta: Decimal) -> dict[str, Any]:
    return {
        "product": str(level.product.code),
        "warehouse": str(level.warehouse.code),
        "location": str(level.location.code),
        "delta_reserved": str(delta),
        "current_reserved": str(level.quantity_reserved),
    }


# ============================================================
# Stock level core primitive (locked)
# ============================================================

def _get_or_create_level_locked(
    *,
    product_id: int,
    warehouse_id: int,
    location_id: int,
) -> StockLevel:
    """
    Select-for-update + get_or_create for StockLevel.
    Ensures row-level lock on PostgreSQL; SQLite locks database.
    """
    level, _ = StockLevel.objects.select_for_update().get_or_create(
        product_id=product_id,
        warehouse_id=warehouse_id,
        location_id=location_id,
        defaults={
            "quantity_on_hand": DECIMAL_ZERO,
            "quantity_reserved": DECIMAL_ZERO,
            "min_stock": DECIMAL_ZERO,
        },
    )
    return level


def _adjust_on_hand_locked(
    *,
    product_id: int,
    warehouse_id: int,
    location_id: int,
    delta: Decimal,
) -> StockLevel:
    level = _get_or_create_level_locked(
        product_id=product_id,
        warehouse_id=warehouse_id,
        location_id=location_id,
    )

    if delta == 0:
        return level

    StockLevel.objects.filter(pk=level.pk).update(quantity_on_hand=F("quantity_on_hand") + delta)
    level.refresh_from_db(fields=["quantity_on_hand"])
    return level


# ============================================================
# Negative stock validation
# ============================================================

def _validate_negative_stock(move: StockMove) -> None:
    settings = InventorySettings.get_solo()
    if settings.allow_negative_stock:
        return

    if move.move_type == StockMove.MoveType.IN:
        return

    # OUT and TRANSFER: validate source
    source_wh_id = move.from_warehouse_id
    source_loc_id = move.from_location_id
    if not source_wh_id or not source_loc_id:
        return

    # Requirements per product in base UOM
    requirements: dict[int, Decimal] = defaultdict(Decimal)
    product_names: dict[int, str] = {}

    for line in move.lines.select_related("product", "uom").all():
        if not getattr(line.product, "is_stock_item", True):
            continue
        requirements[line.product_id] += line.get_base_quantity()
        product_names[line.product_id] = line.product.name

    # Lock levels and validate
    for prod_id, required_qty in requirements.items():
        level = StockLevel.objects.select_for_update().filter(
            product_id=prod_id,
            warehouse_id=source_wh_id,
            location_id=source_loc_id,
        ).values("quantity_on_hand").first()

        current_qty = level["quantity_on_hand"] if level else DECIMAL_ZERO
        if current_qty < required_qty:
            prod_name = product_names.get(prod_id, _("Unknown Product"))
            raise ValidationError(
                _("الرصيد غير كافٍ للمنتج '%(prod)s'. المتاح: %(curr)s، المطلوب: %(req)s.") % {
                    "prod": prod_name,
                    "curr": current_qty,
                    "req": required_qty,
                }
            )


# ============================================================
# Costing
# ============================================================

def _update_product_average_cost(move: StockMove) -> None:
    """
    Weighted average cost update for IN moves.
    Updates Product.average_cost for STOCKABLE items only.
    """
    if move.move_type != StockMove.MoveType.IN:
        return

    # Iterate for memory safety
    for line in move.lines.select_related("product", "uom").iterator():
        product = line.product
        if product.product_type != Product.ProductType.STOCKABLE:
            continue

        incoming_qty = line.get_base_quantity()
        if incoming_qty <= 0:
            continue

        incoming_cost = line.cost_price or DECIMAL_ZERO

        # Lock product row
        locked_product = Product.objects.select_for_update().get(pk=product.pk)

        current_qty = locked_product.total_on_hand
        current_avg = locked_product.average_cost or DECIMAL_ZERO

        if current_qty <= 0:
            new_avg = incoming_cost
        else:
            current_value = current_qty * current_avg
            incoming_value = incoming_qty * incoming_cost
            new_total_qty = current_qty + incoming_qty
            new_avg = (current_value + incoming_value) / new_total_qty if new_total_qty > 0 else incoming_cost

        # Save only if changed meaningfully
        if (locked_product.average_cost or DECIMAL_ZERO) != new_avg:
            locked_product.average_cost = new_avg
            locked_product.save(update_fields=["average_cost"])


def _snapshot_out_cost(move: StockMove) -> None:
    """
    For OUT moves, fill cost_price from product.average_cost if cost_price is zero.
    """
    if move.move_type != StockMove.MoveType.OUT:
        return

    updates: list[StockMoveLine] = []
    for line in move.lines.select_related("product").all():
        if (line.cost_price or DECIMAL_ZERO) == DECIMAL_ZERO and (line.product.average_cost or DECIMAL_ZERO) > 0:
            line.cost_price = line.product.average_cost
            updates.append(line)

    if updates:
        StockMoveLine.objects.bulk_update(updates, ["cost_price"])


# ============================================================
# Apply move deltas (stock levels)
# ============================================================

def _apply_move_delta(move: StockMove, *, factor: Decimal) -> None:
    """
    Apply move lines to stock levels.
    factor:
      +1  confirm
      -1  reverse
    """
    for line in move.lines.select_related("product", "uom").iterator():
        if not getattr(line.product, "is_stock_item", True):
            continue

        base_qty = line.get_base_quantity()
        if base_qty == 0:
            continue

        qty = base_qty * factor

        if move.move_type == StockMove.MoveType.IN:
            _adjust_on_hand_locked(
                product_id=line.product_id,
                warehouse_id=move.to_warehouse_id,
                location_id=move.to_location_id,
                delta=qty,
            )

        elif move.move_type == StockMove.MoveType.OUT:
            _adjust_on_hand_locked(
                product_id=line.product_id,
                warehouse_id=move.from_warehouse_id,
                location_id=move.from_location_id,
                delta=-qty,  # OUT reduces; note qty already includes factor
            )

        else:  # TRANSFER
            _adjust_on_hand_locked(
                product_id=line.product_id,
                warehouse_id=move.from_warehouse_id,
                location_id=move.from_location_id,
                delta=-qty,
            )
            _adjust_on_hand_locked(
                product_id=line.product_id,
                warehouse_id=move.to_warehouse_id,
                location_id=move.to_location_id,
                delta=qty,
            )


# ============================================================
# Public Services
# ============================================================

@transaction.atomic
def confirm_stock_move(move: StockMove, user: Optional["User"] = None) -> StockMove:
    """
    Confirm a stock move:
    DRAFT -> DONE
    """
    move = StockMove.objects.select_for_update().get(pk=move.pk)

    if move.status == StockMove.Status.DONE:
        return move

    if move.status != StockMove.Status.DRAFT:
        raise ValidationError(_("يجب أن تكون الحالة مسودة لتأكيد الحركة."))

    # Validate negative stock first
    _validate_negative_stock(move)

    # Costing
    if move.move_type == StockMove.MoveType.IN:
        _update_product_average_cost(move)
    elif move.move_type == StockMove.MoveType.OUT:
        _snapshot_out_cost(move)

    # Apply stock
    _apply_move_delta(move, factor=DECIMAL_ONE)

    # Update status
    move.status = StockMove.Status.DONE
    if user is not None and getattr(user, "is_authenticated", False):
        move.updated_by = user
    move.save(update_fields=["status", "updated_by"])

    # Audit
    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=_("Stock move confirmed."),
        actor=user,
        target=move,
        extra=_build_move_audit_extra(move, factor=DECIMAL_ONE),
    )

    # Notify creator (if different)
    if move.created_by_id and (user is None or move.created_by_id != getattr(user, "id", None)):
        _notify(
            recipient=move.created_by,
            verb=_("تم تأكيد الحركة المخزنية رقم %(ref)s") % {"ref": move.reference or str(move.pk)},
            level=Notification.Levels.SUCCESS,
            target=move,
        )

    return move


@transaction.atomic
def cancel_stock_move(move: StockMove, user: Optional["User"] = None) -> StockMove:
    """
    Cancel a stock move:
    - DRAFT -> CANCELLED
    - DONE  -> CANCELLED (reverse stock)
    """
    move = StockMove.objects.select_for_update().get(pk=move.pk)

    if move.status == StockMove.Status.CANCELLED:
        raise ValidationError(_("الحركة ملغاة بالفعل."))

    was_done = (move.status == StockMove.Status.DONE)

    if was_done:
        # Reverse stock
        _apply_move_delta(move, factor=DECIMAL_MINUS_ONE)

    move.status = StockMove.Status.CANCELLED
    if user is not None and getattr(user, "is_authenticated", False):
        move.updated_by = user
    move.save(update_fields=["status", "updated_by"])

    # Audit
    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=_("Stock move cancelled."),
        actor=user,
        target=move,
        extra=_build_move_audit_extra(move, factor=DECIMAL_MINUS_ONE if was_done else None),
    )

    # Notify creator
    if move.created_by_id and (user is None or move.created_by_id != getattr(user, "id", None)):
        _notify(
            recipient=move.created_by,
            verb=_("تم إلغاء الحركة المخزنية رقم %(ref)s") % {"ref": move.reference or str(move.pk)},
            level=Notification.Levels.WARNING,
            target=move,
        )

    return move


@transaction.atomic
def reserve_stock(
    *,
    product: Product,
    warehouse,
    location,
    quantity: Decimal,
    check_availability: bool = True,
    user: Optional["User"] = None,
) -> StockLevel:
    """
    Reserve stock quantity (in base UOM).
    """
    if quantity is None or quantity <= 0:
        raise ValidationError(_("الكمية يجب أن تكون موجبة."))

    level = _get_or_create_level_locked(
        product_id=product.pk,
        warehouse_id=warehouse.pk,
        location_id=location.pk,
    )

    if check_availability:
        current_avail = (level.quantity_on_hand or DECIMAL_ZERO) - (level.quantity_reserved or DECIMAL_ZERO)
        if current_avail < quantity:
            raise ValidationError(
                _("الكمية المتاحة (%(avail)s) غير كافية للحجز (%(req)s).") % {
                    "avail": current_avail,
                    "req": quantity,
                }
            )

    StockLevel.objects.filter(pk=level.pk).update(quantity_reserved=F("quantity_reserved") + quantity)
    level.refresh_from_db(fields=["quantity_reserved"])

    log_event(
        action=AuditLog.Action.UPDATE,
        message=_("Stock reserved."),
        actor=user,
        target=level,
        extra=_build_reservation_audit_extra(level, quantity),
    )

    return level


@transaction.atomic
def release_stock(
    *,
    product: Product,
    warehouse,
    location,
    quantity: Decimal,
    user: Optional["User"] = None,
) -> StockLevel:
    """
    Release reserved stock (in base UOM).
    """
    if quantity is None or quantity <= 0:
        raise ValidationError(_("الكمية يجب أن تكون موجبة."))

    level = StockLevel.objects.select_for_update().get(
        product=product,
        warehouse=warehouse,
        location=location,
    )

    if (level.quantity_reserved or DECIMAL_ZERO) < quantity:
        raise ValidationError(_("لا يمكن فك حجز أكبر من الكمية المحجوزة."))

    StockLevel.objects.filter(pk=level.pk).update(quantity_reserved=F("quantity_reserved") - quantity)
    level.refresh_from_db(fields=["quantity_reserved"])

    log_event(
        action=AuditLog.Action.UPDATE,
        message=_("Stock reservation released."),
        actor=user,
        target=level,
        extra=_build_reservation_audit_extra(level, -quantity),
    )

    return level


@transaction.atomic
def create_inventory_session(
    *,
    warehouse: "StockLocation" | Any,
    user: "User",
    category=None,
    location=None,
    note: str = "",
) -> InventoryAdjustment:
    """
    Create an inventory adjustment session and snapshot current quantities.
    """
    if location and location.warehouse_id != warehouse.id:
        raise ValidationError(_("الموقع لا يتبع المستودع المختار."))

    adjustment = InventoryAdjustment.objects.create(
        warehouse=warehouse,
        category=category,
        location=location,
        note=note,
        status=InventoryAdjustment.Status.DRAFT,
        created_by=user,
        updated_by=user,
    )

    levels = StockLevel.objects.filter(warehouse=warehouse).exclude(quantity_on_hand=0)
    if location:
        levels = levels.filter(location=location)
    if category:
        levels = levels.filter(product__category=category)

    lines = [
        InventoryAdjustmentLine(
            adjustment=adjustment,
            product_id=level.product_id,
            location_id=level.location_id,
            theoretical_qty=level.quantity_on_hand,
            counted_qty=None,
            created_by=user,
            updated_by=user,
        )
        for level in levels.select_related("product", "location")
    ]
    InventoryAdjustmentLine.objects.bulk_create(lines)

    log_event(
        action=AuditLog.Action.CREATE,
        message=_("Inventory session started."),
        actor=user,
        target=adjustment,
        extra={
            "lines_count": len(lines),
            "warehouse": str(getattr(warehouse, "code", getattr(warehouse, "name", ""))),
        },
    )

    return adjustment


@transaction.atomic
def apply_inventory_adjustment(adjustment: InventoryAdjustment, user: "User") -> None:
    """
    Apply inventory adjustment:
    - Create IN moves for gains and OUT moves for losses (grouped per location)
    - Confirm generated moves
    - Mark adjustment as APPLIED
    """
    adjustment = InventoryAdjustment.objects.select_for_update().get(pk=adjustment.pk)

    if adjustment.status == InventoryAdjustment.Status.APPLIED:
        raise ValidationError(_("تم ترحيل الجرد مسبقاً."))

    # Build diffs grouped by location
    grouped: dict[int, dict[str, list[tuple[int, Decimal]]]] = defaultdict(lambda: {"gain": [], "loss": []})
    location_ids: set[int] = set()
    product_ids: set[int] = set()

    # Preload current levels for this warehouse for performance
    # Key: (product_id, location_id) -> qty
    current_levels = {
        (row["product_id"], row["location_id"]): (row["quantity_on_hand"] or DECIMAL_ZERO)
        for row in StockLevel.objects.select_for_update()
        .filter(warehouse=adjustment.warehouse)
        .values("product_id", "location_id", "quantity_on_hand")
    }

    for line in adjustment.lines.select_related("product", "location").all():
        if line.counted_qty is None:
            continue

        current_qty = current_levels.get((line.product_id, line.location_id), DECIMAL_ZERO)
        diff = (line.counted_qty or DECIMAL_ZERO) - current_qty

        if diff == 0:
            continue

        location_ids.add(line.location_id)
        product_ids.add(line.product_id)

        if diff > 0:
            grouped[line.location_id]["gain"].append((line.product_id, diff))
        else:
            grouped[line.location_id]["loss"].append((line.product_id, abs(diff)))

    if not grouped:
        adjustment.status = InventoryAdjustment.Status.APPLIED
        adjustment.updated_by = user
        adjustment.save(update_fields=["status", "updated_by"])
        return

    # Maps
    locations_map = {loc.id: loc for loc in StockLocation.objects.filter(id__in=location_ids)}
    products_map = {p.id: p for p in Product.objects.filter(id__in=product_ids).select_related("base_uom")}

    moves_created = 0

    for loc_id, buckets in grouped.items():
        location = locations_map[loc_id]

        # Gains -> IN
        if buckets["gain"]:
            move_in = StockMove.objects.create(
                move_type=StockMove.MoveType.IN,
                to_warehouse=adjustment.warehouse,
                to_location=location,
                status=StockMove.Status.DRAFT,
                reference=f"ADJ-IN-{adjustment.pk}-{location.code}",
                note=_("تسوية جردية - زيادة"),
                adjustment=adjustment,
                created_by=user,
                updated_by=user,
            )

            lines = []
            for prod_id, qty in buckets["gain"]:
                prod = products_map[prod_id]
                lines.append(
                    StockMoveLine(
                        move=move_in,
                        product=prod,
                        quantity=qty,
                        uom=prod.base_uom,
                        cost_price=prod.average_cost or DECIMAL_ZERO,
                        created_by=user,
                        updated_by=user,
                    )
                )
            StockMoveLine.objects.bulk_create(lines)

            confirm_stock_move(move_in, user=user)
            moves_created += 1

        # Loss -> OUT
        if buckets["loss"]:
            move_out = StockMove.objects.create(
                move_type=StockMove.MoveType.OUT,
                from_warehouse=adjustment.warehouse,
                from_location=location,
                status=StockMove.Status.DRAFT,
                reference=f"ADJ-OUT-{adjustment.pk}-{location.code}",
                note=_("تسوية جردية - عجز"),
                adjustment=adjustment,
                created_by=user,
                updated_by=user,
            )

            lines = []
            for prod_id, qty in buckets["loss"]:
                prod = products_map[prod_id]
                lines.append(
                    StockMoveLine(
                        move=move_out,
                        product=prod,
                        quantity=qty,
                        uom=prod.base_uom,
                        cost_price=DECIMAL_ZERO,  # will snapshot on confirm
                        created_by=user,
                        updated_by=user,
                    )
                )
            StockMoveLine.objects.bulk_create(lines)

            confirm_stock_move(move_out, user=user)
            moves_created += 1

    adjustment.status = InventoryAdjustment.Status.APPLIED
    adjustment.updated_by = user
    adjustment.save(update_fields=["status", "updated_by"])

    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=_("Inventory adjustment applied."),
        actor=user,
        target=adjustment,
        extra={"moves_created": moves_created},
    )

    if adjustment.created_by_id and adjustment.created_by_id != getattr(user, "id", None):
        _notify(
            recipient=adjustment.created_by,
            verb=_("تم ترحيل وثيقة الجرد رقم %(id)s") % {"id": adjustment.pk},
            level=Notification.Levels.INFO,
            target=adjustment,
        )
