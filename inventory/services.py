# inventory/services.py

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

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
# Audit Helpers
# ============================================================

def _build_move_audit_extra(move: StockMove, *, factor: Decimal | None = None) -> dict:
    """بناء بيانات إضافية لسجل التدقيق."""
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
    return {
        "product": stock_level.product.code,
        "warehouse": stock_level.warehouse.code,
        "location": stock_level.location.code,
        "delta_reserved": str(delta),
        "current_reserved": str(stock_level.quantity_reserved),
    }


# ============================================================
# Cost Logic (Weighted Average Cost)
# ============================================================

def _update_product_average_cost(move: StockMove) -> None:
    """
    تحديث متوسط التكلفة.
    المنطق المحسن: إذا كان الرصيد الحالي صفراً أو سالباً، فإن التكلفة الجديدة تعتمد كلياً على الوارد الجديد.
    """
    if move.move_type != StockMove.MoveType.IN:
        return

    # استخدام iterator لتقليل استهلاك الذاكرة في الحركات الكبيرة
    for line in move.lines.select_related("product").iterator():
        if line.product.product_type != Product.ProductType.STOCKABLE:
            continue

        incoming_qty = line.get_base_quantity()
        incoming_cost = line.cost_price or DECIMAL_ZERO

        if incoming_qty <= 0:
            continue

        # 🔒 Critical Section
        product = Product.objects.select_for_update().get(pk=line.product_id)

        current_total_qty = product.total_on_hand
        current_avg_cost = product.average_cost or DECIMAL_ZERO

        # ✅ تحسين: إذا كان الرصيد السابق 0 أو أقل (سالب)، نعتمد السعر الجديد مباشرة
        # لأن دمج السالب مع الموجب في معادلة المتوسط يعطي نتائج غير منطقية مالياً.
        if current_total_qty <= 0:
            new_avg_cost = incoming_cost
        else:
            # المعادلة القياسية: (القيمة الحالية + قيمة الوارد) / الكمية الكلية الجديدة
            current_total_value = current_total_qty * current_avg_cost
            incoming_total_value = incoming_qty * incoming_cost
            new_total_qty = current_total_qty + incoming_qty

            # حماية من القسمة على صفر (نظرياً)
            if new_total_qty > 0:
                new_avg_cost = (current_total_value + incoming_total_value) / new_total_qty
            else:
                new_avg_cost = incoming_cost

        # تحديث فقط إذا تغيرت القيمة لتقليل الكتابة على الداتابيز
        if product.average_cost != new_avg_cost:
            product.average_cost = new_avg_cost
            product.save(update_fields=["average_cost"])


def _snapshot_out_cost(move: StockMove) -> None:
    """
    للحركات الصادرة: تثبيت التكلفة الحالية في لحظة الصرف.
    """
    if move.move_type != StockMove.MoveType.OUT:
        return

    updates = []
    # هنا لا نستخدم iterator لأننا سنقوم بتحديث نفس الكائنات
    for line in move.lines.select_related("product").all():
        # نملأ التكلفة فقط إذا كانت 0
        if line.cost_price == DECIMAL_ZERO and line.product.average_cost > 0:
            line.cost_price = line.product.average_cost
            updates.append(line)

    if updates:
        StockMoveLine.objects.bulk_update(updates, ["cost_price"])


# ============================================================
# Core Adjustment Logic
# ============================================================

def _adjust_stock_level(
        *,
        product: Product,
        warehouse,
        location,
        delta: Decimal,
) -> StockLevel:
    """
    تعديل رصيد المخزون مع ضمان القفل (Locking).
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
        # إعادة تحميل القيم للأمان إذا كنا سنستخدمها فوراً
        level.refresh_from_db(fields=["quantity_on_hand"])

    return level


def _validate_negative_stock(move: StockMove) -> None:
    """
    يتحقق من عدم كسر قاعدة "ممنوع السالب" للحركات الصادرة والتحويلات.
    """
    settings = InventorySettings.get_solo()
    if settings.allow_negative_stock:
        return

    # الوارد لا يسبب نقصاً
    if move.move_type == StockMove.MoveType.IN:
        return

    # للصادر والتحويل: مصدر الكمية هو from_warehouse / from_location
    source_wh = move.from_warehouse
    source_loc = move.from_location

    if not source_wh or not source_loc:
        return

    # تجميع الكميات المطلوبة لكل منتج
    requirements = {}
    product_names = {}

    for line in move.lines.select_related("product").all():
        key = (line.product_id, source_wh.id, source_loc.id)
        qty = line.get_base_quantity()

        requirements[key] = requirements.get(key, DECIMAL_ZERO) + qty
        product_names[line.product_id] = line.product.name

    # التحقق
    for (prod_id, wh_id, loc_id), required_qty in requirements.items():
        try:
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
    """تطبيق الكميات على الأرصدة."""
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
            # خصم من المصدر
            _adjust_stock_level(
                product=product,
                warehouse=move.from_warehouse,
                location=move.from_location,
                delta=-qty
            )
            # إضافة للوجهة
            _adjust_stock_level(
                product=product,
                warehouse=move.to_warehouse,
                location=move.to_location,
                delta=qty
            )


# ============================================================
# Public Services (Main Actions)
# ============================================================

@transaction.atomic
def confirm_stock_move(move: StockMove, user=None) -> StockMove:
    """DRAFT -> DONE"""
    # إعادة جلب مع القفل
    move = StockMove.objects.select_for_update().get(pk=move.pk)

    if move.status == StockMove.Status.DONE:
        return move

    if move.status != StockMove.Status.DRAFT:
        raise ValidationError(_("لا يمكن تأكيد حركة ليست في حالة مسودة."))

    # 1. التحقق (Validation)
    _validate_negative_stock(move)

    # 2. تحديث التكاليف (قبل التحريك، لضمان دقة البيانات)
    if move.move_type == StockMove.MoveType.IN:
        _update_product_average_cost(move)
    elif move.move_type == StockMove.MoveType.OUT:
        _snapshot_out_cost(move)

    # 3. تحريك الأرصدة
    _apply_move_delta(move, factor=Decimal("1"))

    # 4. تحديث الحالة
    move.status = StockMove.Status.DONE
    move.save(update_fields=["status"])

    # 5. السجلات
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
    """Done/Draft -> Cancelled"""
    move = StockMove.objects.select_for_update().get(pk=move.pk)

    if move.status == StockMove.Status.CANCELLED:
        raise ValidationError(_("الحركة ملغاة بالفعل."))

    was_done = (move.status == StockMove.Status.DONE)

    # إذا كانت منفذة، نعكس التأثير
    if was_done:
        # ملاحظة: عند الإلغاء، لا نقوم عادة "بإلغاء" تحديث متوسط التكلفة
        # لأنه عملية معقدة جداً تاريخياً. نكتفي بعكس الكميات.
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
# Reservation Services
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
    if quantity <= 0:
        raise ValidationError(_("كمية الحجز يجب أن تكون موجبة."))

    level = _adjust_stock_level(
        product=product, warehouse=warehouse, location=location, delta=0
    )

    if check_availability:
        # نحسب المتاح يدوياً هنا لأن الخاصية available_quantity لا تعمل داخل transaction بشكل مباشر
        # قبل الحفظ، لذا نعتمد على القيم الحالية
        current_avail = level.quantity_on_hand - level.quantity_reserved
        if current_avail < quantity:
            raise ValidationError(
                _("الكمية المتاحة (%(avail)s) غير كافية للحجز المطلوب (%(req)s).")
                % {"avail": current_avail, "req": quantity}
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
    if quantity <= 0:
        raise ValidationError(_("الكمية يجب أن تكون موجبة."))

    level = StockLevel.objects.select_for_update().get(
        product=product, warehouse=warehouse, location=location
    )

    # لا نسمح بفك حجز أكثر مما هو محجوز
    # ملاحظة: نستخدم القيم الحالية في الذاكرة للفحص
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
# Inventory Adjustment Services
# ============================================================

@transaction.atomic
def create_inventory_session(
        warehouse,
        user,
        category=None,
        location=None,
        note=""
) -> InventoryAdjustment:
    # 1. تحقق من الموقع
    if location and location.warehouse_id != warehouse.id:
        raise ValidationError(_("الموقع المحدد لا يتبع للمستودع المختار."))

    # 2. إنشاء الوثيقة
    # نفترض وجود حقل created_by في الموديل (أو BaseModel)
    # إذا لم يكن موجوداً، يجب إزالته من هنا.
    adjustment = InventoryAdjustment.objects.create(
        warehouse=warehouse,
        category=category,
        location=location,
        note=note,
        status=InventoryAdjustment.Status.DRAFT,
        # created_by=user  <-- تأكد من وجود هذا الحقل في الموديل الخاص بك
    )

    # 3. Snapshot (أخذ لقطة للوضع الحالي)
    levels = StockLevel.objects.filter(warehouse=warehouse)

    if location:
        levels = levels.filter(location=location)

    if category:
        levels = levels.filter(product__category=category)

    # استثناء الصفري لتقليل حجم البيانات
    levels = levels.exclude(quantity_on_hand=0)

    adjustment_lines = []
    for level in levels.select_related("product", "location"):
        adjustment_lines.append(
            InventoryAdjustmentLine(
                adjustment=adjustment,
                product=level.product,
                location=level.location,
                theoretical_qty=level.quantity_on_hand,
                counted_qty=None
            )
        )

    InventoryAdjustmentLine.objects.bulk_create(adjustment_lines)

    return adjustment


@transaction.atomic
def apply_inventory_adjustment(adjustment: InventoryAdjustment, user) -> None:
    """
    ترحيل الجرد وإنشاء حركات التسوية.
    """
    if adjustment.status == InventoryAdjustment.Status.APPLIED:
        raise ValidationError(_("تم ترحيل وثيقة الجرد هذه مسبقاً."))

    grouped_diffs = defaultdict(lambda: {'gain': [], 'loss': []})
    location_ids = set()
    has_diffs = False

    # تكرار البنود وحساب الفرق الحي
    # نستخدم select_for_update داخل الحلقة لضمان أننا نقرأ الرصيد الحي لحظة الترحيل
    # هذا يمنع أي تضارب إذا تم بيع منتج أثناء عملية الترحيل
    for line in adjustment.lines.select_related("product", "location", "product__base_uom").all():
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

        # الفرق = الكمية التي تم عدها - الكمية الموجودة فعلياً في النظام الآن
        real_diff = line.counted_qty - current_qty

        if real_diff == 0:
            continue

        has_diffs = True
        loc_id = line.location.id
        location_ids.add(loc_id)

        # تخزين الفرق لاستخدامه لاحقاً
        line.real_diff_for_move = real_diff

        if real_diff > 0:
            grouped_diffs[loc_id]['gain'].append(line)
        else:
            grouped_diffs[loc_id]['loss'].append(line)

    if not has_diffs:
        adjustment.status = InventoryAdjustment.Status.APPLIED
        adjustment.save()
        return

    # جلب كائنات المواقع المطلوبة
    locations_map = {
        loc.id: loc
        for loc in StockLocation.objects.filter(id__in=location_ids)
    }

    # إنشاء الحركات (IN / OUT)
    for loc_id, types in grouped_diffs.items():
        location = locations_map[loc_id]

        # 1. معالجة الزيادة (Gain) -> حركة واردة
        gain_lines = types['gain']
        if gain_lines:
            move_in = StockMove.objects.create(
                move_type=StockMove.MoveType.IN,
                to_warehouse=adjustment.warehouse,
                to_location=location,
                status=StockMove.Status.DRAFT,
                reference=f"INV-ADJ-IN-{adjustment.pk}-{location.code}",
                note=_("تسوية جردية - زيادة (وثيقة #%(id)s)") % {'id': adjustment.pk},
                adjustment=adjustment,
                # created_by=user
            )

            move_lines_in = []
            for line in gain_lines:
                move_lines_in.append(StockMoveLine(
                    move=move_in,
                    product=line.product,
                    quantity=abs(line.real_diff_for_move),
                    uom=line.product.base_uom,
                    cost_price=line.product.average_cost  # نستخدم التكلفة الحالية للزيادة
                ))
            StockMoveLine.objects.bulk_create(move_lines_in)
            confirm_stock_move(move_in, user=user)

        # 2. معالجة النقص (Loss) -> حركة صادرة
        loss_lines = types['loss']
        if loss_lines:
            move_out = StockMove.objects.create(
                move_type=StockMove.MoveType.OUT,
                from_warehouse=adjustment.warehouse,
                from_location=location,
                status=StockMove.Status.DRAFT,
                reference=f"INV-ADJ-OUT-{adjustment.pk}-{location.code}",
                note=_("تسوية جردية - عجز (وثيقة #%(id)s)") % {'id': adjustment.pk},
                adjustment=adjustment,
                # created_by=user
            )

            move_lines_out = []
            for line in loss_lines:
                move_lines_out.append(StockMoveLine(
                    move=move_out,
                    product=line.product,
                    quantity=abs(line.real_diff_for_move),
                    uom=line.product.base_uom,
                    # للصادر، التكلفة تحسب تلقائياً داخل confirm_stock_move
                ))
            StockMoveLine.objects.bulk_create(move_lines_out)
            confirm_stock_move(move_out, user=user)

    adjustment.status = InventoryAdjustment.Status.APPLIED
    # adjustment.updated_by = user
    adjustment.save()