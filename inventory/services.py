# inventory/services.py
from decimal import Decimal

from django.db import transaction
from django.db.models import F

from .models import StockLevel, StockMove


def _adjust_stock_level(*, product, warehouse=None, location=None, delta: Decimal):
    """
    يعدّل مستوى المخزون (quantity_on_hand) بمقدار delta.
    إذا لم يوجد StockLevel لهذا المنتج + (مخزن/موقع) يتم إنشاؤه بصفر ثم التطبيق.

    نستخدم select_for_update + F expressions لسلامة التوازي (concurrency).
    """
    if not delta:
        return

    with transaction.atomic():
        level, created = (
            StockLevel.objects
            .select_for_update()
            .get_or_create(
                product=product,
                warehouse=warehouse,
                location=location,
                defaults={
                    "quantity_on_hand": Decimal("0"),
                    "quantity_reserved": Decimal("0"),
                },
            )
        )

        # تعديل الكمية المتوفرة
        level.quantity_on_hand = F("quantity_on_hand") + delta
        level.save(update_fields=["quantity_on_hand"])

        # تحديث الكائن في الذاكرة بعد استخدام F
        level.refresh_from_db(fields=["quantity_on_hand"])

    return level


def _apply_move_delta(move: StockMove, factor: Decimal):
    """
    يطبق أثر حركة مخزون على StockLevel.

    - factor =  1  عند الإنشاء (post_save created=True)
    - factor = -1  عند الحذف (post_delete) لعكس الأثر
    """
    qty = Decimal(move.quantity) * factor

    # إدخال IN: من خارج النظام إلى (to_warehouse / to_location)
    if move.move_type == StockMove.MoveType.IN:
        _adjust_stock_level(
            product=move.product,
            warehouse=move.to_warehouse,
            location=move.to_location,
            delta=qty,  # +qty عند الإنشاء / -qty عند الحذف
        )

    # إخراج OUT: من (from_warehouse / from_location) إلى خارج النظام
    elif move.move_type == StockMove.MoveType.OUT:
        _adjust_stock_level(
            product=move.product,
            warehouse=move.from_warehouse,
            location=move.from_location,
            delta=-qty,  # -qty عند الإنشاء / +qty عند الحذف
        )

    # تحويل TRANSFER: من مخزن/موقع إلى مخزن/موقع آخر داخل النظام
    elif move.move_type == StockMove.MoveType.TRANSFER:
        # من (from) ننقص
        _adjust_stock_level(
            product=move.product,
            warehouse=move.from_warehouse,
            location=move.from_location,
            delta=-qty,
        )
        # إلى (to) نزيد
        _adjust_stock_level(
            product=move.product,
            warehouse=move.to_warehouse,
            location=move.to_location,
            delta=qty,
        )


def apply_stock_move_on_create(move: StockMove):
    """
    تُستدعى عند إنشاء حركة جديدة (post_save, created=True).

    ملاحظة: حالياً نطبّق الأثر دائماً عند الإنشاء، بغض النظر عن status.
    لو حاب لاحقاً تطبّق الأثر فقط عند DONE وتدعم تغيير الحالة من DRAFT → DONE
    نقدر نضيف منطق إضافي.
    """
    _apply_move_delta(move, factor=Decimal("1"))


def apply_stock_move_on_delete(move: StockMove):
    """
    تُستدعى عند حذف حركة مخزون (post_delete) لعكس الأثر.
    """
    _apply_move_delta(move, factor=Decimal("-1"))
