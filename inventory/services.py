# inventory/services.py

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum, Q
from django.utils.translation import gettext_lazy as _

from core.models import AuditLog
from core.services.audit import log_event

from .models import StockLevel, StockMove


DECIMAL_ZERO = Decimal("0.000")


# ============================================================
# دوال مساعدة لسجل التدقيق لحركات المخزون
# ============================================================

def _build_move_audit_extra(move: StockMove, *, factor: Decimal | None = None) -> dict:
    """
    يبني دكشنري موحّد للمعلومات الإضافية لكل حدث متعلق بحركة مخزون.
    مفيد لعرض تفاصيل الحركة لاحقاً في سجل التدقيق.
    """
    try:
        lines_count = move.lines.count()
    except Exception:
        lines_count = 0

    try:
        total_lines_quantity = move.total_lines_quantity
    except Exception:
        total_lines_quantity = DECIMAL_ZERO

    extra = {
        "move_type": move.move_type,
        "status": move.status,
        "from_warehouse_id": move.from_warehouse_id,
        "to_warehouse_id": move.to_warehouse_id,
        "from_location_id": move.from_location_id,
        "to_location_id": move.to_location_id,
        "lines_count": lines_count,
        "total_lines_quantity": str(total_lines_quantity),
    }

    if factor is not None:
        extra["factor"] = str(factor)

    return extra


def _build_reservation_audit_extra(
    *,
    product,
    warehouse,
    location,
    quantity: Decimal,
    before_available: Decimal | None = None,
    after_reserved: Decimal | None = None,
) -> dict:
    """
    دكشنري موحّد لمعلومات حجز / فك حجز المخزون،
    بحيث نظام النتفيكشن يقدر يستخدمه لو حاب.
    """
    extra = {
        "product_id": getattr(product, "pk", None),
        "product_code": getattr(product, "code", None),
        "warehouse_id": getattr(warehouse, "pk", None),
        "warehouse_code": getattr(warehouse, "code", None),
        "location_id": getattr(location, "pk", None),
        "quantity": str(quantity),
    }

    if before_available is not None:
        extra["available_before"] = str(before_available)
    if after_reserved is not None:
        extra["reserved_after"] = str(after_reserved)

    return extra


# ============================================================
# دوال أساسية لتعديل أرصدة المخزون
# ============================================================

@transaction.atomic
def _adjust_stock_level(*, product, warehouse, location, delta: Decimal) -> StockLevel:
    """
    يعدّل مستوى المخزون (quantity_on_hand) بمقدار delta
    *بالوحدة الأساسية للمنتج* (base_uom).

    - إذا لم يوجد StockLevel لهذا (المنتج + المستودع + الموقع) يتم إنشاؤه بصفر.
    - نستخدم select_for_update + F expressions لسلامة التوازي.
    - لا يسمح بأن تصبح الكمية المتوفرة أقل من صفر (متوافق مع CheckConstraint).
    """
    level, _ = (
        StockLevel.objects.select_for_update()
        .get_or_create(
            product=product,
            warehouse=warehouse,
            location=location,
            defaults={
                "quantity_on_hand": DECIMAL_ZERO,
                "quantity_reserved": DECIMAL_ZERO,
                "min_stock": DECIMAL_ZERO,
            },
        )
    )

    delta = Decimal(delta or 0)

    if delta != 0:
        # نحسب القيمة الجديدة للتأكد أنها لن تصبح سالبة
        current = level.quantity_on_hand or DECIMAL_ZERO
        new_value = current + delta
        if new_value < 0:
            raise ValidationError(
                _(
                    "لا يمكن أن يصبح رصيد المخزون سالباً. "
                    "الرصيد الحالي: %(current)s، التغيير المطلوب: %(delta)s."
                ),
                params={"current": current, "delta": delta},
            )

        level.quantity_on_hand = F("quantity_on_hand") + delta
        level.save(update_fields=["quantity_on_hand"])
        level.refresh_from_db(fields=["quantity_on_hand"])

    return level


def _apply_move_delta(move: StockMove, *, factor: Decimal) -> None:
    """
    يطبّق تأثير حركة مخزون واحدة على StockLevel *على مستوى البنود*.

    factor:
      +1  = تطبيق الحركة (posting)
      -1  = عكس الحركة (unposting أو حذف)

    المنطق يعتمد على:
      - move.lines (StockMoveLine)
      - line.get_base_quantity()  → الكمية بوحدة الأساس للمنتج
      - move.move_type لتحديد الاتجاه (IN / OUT / TRANSFER)
    """
    lines = list(move.lines.select_related("product", "uom"))
    if not lines:
        return

    for line in lines:
        # لو المنتج لا يُتابَع في المخزون نتجاهله
        if not line.product.is_stock_item:
            continue

        base_qty = line.get_base_quantity() or DECIMAL_ZERO
        qty = base_qty * factor
        if qty == 0:
            continue

        # حركة واردة: نضيف للـ destination
        if move.move_type == StockMove.MoveType.IN:
            if not move.to_warehouse or not move.to_location:
                raise ValidationError(
                    _("حركة واردة تتطلب مستودعاً وموقعاً للوجهة.")
                )

            _adjust_stock_level(
                product=line.product,
                warehouse=move.to_warehouse,
                location=move.to_location,
                delta=qty,  # الكمية بالـ base_uom
            )

        # حركة صادرة: نطرح من المصدر
        elif move.move_type == StockMove.MoveType.OUT:
            if not move.from_warehouse or not move.from_location:
                raise ValidationError(
                    _("حركة صادرة تتطلب مستودعاً وموقعاً للمصدر.")
                )

            _adjust_stock_level(
                product=line.product,
                warehouse=move.from_warehouse,
                location=move.from_location,
                delta=-qty,
            )

        # تحويل: من المصدر إلى الوجهة
        elif move.move_type == StockMove.MoveType.TRANSFER:
            if not (
                move.from_warehouse
                and move.from_location
                and move.to_warehouse
                and move.to_location
            ):
                raise ValidationError(
                    _("حركة تحويل تتطلب تحديد المصدر والوجهة (مستودع + موقع لكل منهما).")
                )

            _adjust_stock_level(
                product=line.product,
                warehouse=move.from_warehouse,
                location=move.from_location,
                delta=-qty,
            )
            _adjust_stock_level(
                product=line.product,
                warehouse=move.to_warehouse,
                location=move.to_location,
                delta=qty,
            )


# ============================================================
# منطق التحديث بناءً على حالة الحركة (status)
# ============================================================

def apply_stock_move_status_change(
    *, move: StockMove, old_status: str | None, is_create: bool
) -> None:
    """
    تطبّق / تعكس أثر الحركة على المخزون بناءً على تغيير الحالة (status).

    القواعد:

      عند الإنشاء (is_create=True):
        - DRAFT      → لا شيء
        - DONE       → تطبيق الحركة (factor = +1)
        - CANCELLED  → لا شيء

      عند التعديل:
        - DRAFT      → DONE       => factor = +1
        - CANCELLED  → DONE       => factor = +1   (إعادة تفعيل)
        - DONE       → CANCELLED  => factor = -1   (إلغاء بعد التطبيق)
        - DONE       → DRAFT      => factor = -1   (رجوع لمسودة)
        - باقي الانتقالات لا تغيّر المخزون.

    بالإضافة لذلك:
      - نسجل جميع الانتقالات التي تؤثر على المخزون في AuditLog.Action.STATUS_CHANGE
        مع معلومات إضافية عن الحركة.
    """
    new_status = move.status

    # إنشاء جديد
    if is_create:
        if new_status == StockMove.Status.DONE:
            factor = Decimal("1")
            _apply_move_delta(move, factor=factor)

            # سجل تدقيق: تطبيق حركة جديدة مباشرة كـ DONE
            log_event(
                action=AuditLog.Action.STATUS_CHANGE,
                message=_("تم تطبيق حركة المخزون رقم %(id)s عند الإنشاء (إلى منفذة).") % {
                    "id": move.pk,
                },
                actor=None,  # لا يوجد request هنا، نتركها بدون actor
                target=move,
                extra=_build_move_audit_extra(move, factor=factor),
            )
        return

    # تحديث موجود مسبقاً
    if old_status is None or old_status == new_status:
        # لا يوجد تغيير في الحالة
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

    # سجل التدقيق لهذا الانتقال
    status_labels = dict(StockMove.Status.choices)
    old_label = status_labels.get(old_status, old_status)
    new_label = status_labels.get(new_status, new_status)

    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=_(
            "تغيير حالة حركة المخزون رقم %(id)s من %(old)s إلى %(new)s."
        ) % {
            "id": move.pk,
            "old": old_label,
            "new": new_label,
        },
        actor=None,
        target=move,
        extra=_build_move_audit_extra(move, factor=factor),
    )


def apply_stock_move_on_delete(move: StockMove) -> None:
    """
    تُستدعى عند حذف حركة مخزون لعكس الأثر *فقط إذا كانت الحركة في حالة DONE*.

    - تعكس أثر الحركة على المخزون (factor = -1)
    - تسجل حدثًا في سجل التدقيق (STATUS_CHANGE) بأن الحركة المحذوفة تم عكسها.
    """
    if move.status != StockMove.Status.DONE:
        return

    factor = Decimal("-1")
    _apply_move_delta(move, factor=factor)

    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=_(
            "تم حذف حركة المخزون رقم %(id)s وتم عكس أثرها على المخزون."
        ) % {
            "id": move.pk,
        },
        actor=None,
        target=move,
        extra=_build_move_audit_extra(move, factor=factor),
    )


# ============================================================
# دوال حجز المخزون (للطلبيات)
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
    - يمكن ربطه بمناداة من OrderLine في تطبيق آخر.

    إذا allow_negative=False:
      - لا يسمح بحجز أكثر من الكمية المتاحة (on_hand - reserved).
    """
    quantity = Decimal(quantity or 0)
    if quantity <= 0:
        raise ValidationError(_("كمية الحجز يجب أن تكون أكبر من صفر."))

    level, _ = (
        StockLevel.objects.select_for_update()
        .get_or_create(
            product=product,
            warehouse=warehouse,
            location=location,
            defaults={
                "quantity_on_hand": DECIMAL_ZERO,
                "quantity_reserved": DECIMAL_ZERO,
                "min_stock": DECIMAL_ZERO,
            },
        )
    )

    available = (level.quantity_on_hand or DECIMAL_ZERO) - (
        level.quantity_reserved or DECIMAL_ZERO
    )
    if not allow_negative and available < quantity:
        raise ValidationError(
            _(
                "لا توجد كمية كافية للحجز. المتاح: %(available)s، المطلوب حجزه: %(requested)s."
            ),
            params={"available": available, "requested": quantity},
        )

    level.quantity_reserved = F("quantity_reserved") + quantity
    level.save(update_fields=["quantity_reserved"])
    level.refresh_from_db(fields=["quantity_reserved"])

    # 🔔 سجل تدقيق / نتفيكشن للحجز
    log_event(
        action=AuditLog.Action.UPDATE,
        message=_(
            "تم حجز كمية %(qty)s من المنتج %(product)s في المستودع %(wh)s."
        ) % {
            "qty": quantity,
            "product": getattr(product, "code", str(product)),
            "wh": getattr(warehouse, "code", str(warehouse)),
        },
        actor=None,
        target=level,
        extra=_build_reservation_audit_extra(
            product=product,
            warehouse=warehouse,
            location=location,
            quantity=quantity,
            before_available=available,
            after_reserved=level.quantity_reserved,
        ),
    )

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
    quantity = Decimal(quantity or 0)
    if quantity <= 0:
        raise ValidationError(_("كمية فك الحجز يجب أن تكون أكبر من صفر."))

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
        raise ValidationError(
            _("لا يوجد مخزون محجوز لفكه لهذا المنتج في هذا الموقع.")
        )

    if (level.quantity_reserved or DECIMAL_ZERO) < quantity:
        raise ValidationError(
            _(
                "لا يمكن فك حجز كمية أكبر من الكمية المحجوزة. "
                "المحجوز: %(reserved)s، المطلوب فكّه: %(requested)s."
            ),
            params={"reserved": level.quantity_reserved, "requested": quantity},
        )

    before_reserved = level.quantity_reserved or DECIMAL_ZERO

    level.quantity_reserved = F("quantity_reserved") - quantity
    level.save(update_fields=["quantity_reserved"])
    level.refresh_from_db(fields=["quantity_reserved"])

    # 🔔 سجل تدقيق / نتفيكشن لفك الحجز
    log_event(
        action=AuditLog.Action.UPDATE,
        message=_(
            "تم فك حجز كمية %(qty)s من المنتج %(product)s في المستودع %(wh)s."
        ) % {
            "qty": quantity,
            "product": getattr(product, "code", str(product)),
            "wh": getattr(warehouse, "code", str(warehouse)),
        },
        actor=None,
        target=level,
        extra=_build_reservation_audit_extra(
            product=product,
            warehouse=warehouse,
            location=location,
            quantity=quantity,
            before_available=None,  # هنا الأهم هو الحجز قبل/بعد
            after_reserved=level.quantity_reserved,
        ),
    )

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
        return DECIMAL_ZERO

    return (level.quantity_on_hand or DECIMAL_ZERO) - (
        level.quantity_reserved or DECIMAL_ZERO
    )


# ============================================================
# ملخصات وتقارير بسيطة للمخزون
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

    مع select_related للعرض في القوالب بدون مشكلة N+1.
    """
    return (
        StockLevel.objects
        .select_related("product", "warehouse", "location")
        .filter(
            min_stock__gt=DECIMAL_ZERO,
            quantity_on_hand__lt=F("min_stock"),
        )
    )


# ============================================================
# فلاتر جاهزة لقوائم المخزون / الحركات / المنتجات
# ============================================================

def filter_below_min_stock_levels(qs):
    """
    يطبّق فلتر 'تحت الحد الأدنى' على QuerySet معيّن لمستويات المخزون.
    يُستخدم في شاشة مستويات المخزون وغيرها.
    """
    return qs.filter(
        min_stock__gt=DECIMAL_ZERO,
        quantity_on_hand__lt=F("min_stock"),
    )


def get_low_stock_total() -> int:
    """
    يعيد العدد الإجمالي لمستويات المخزون تحت الحد الأدنى
    (بدون أي فلاتر بحث).
    """
    base_qs = StockLevel.objects.all()
    return filter_below_min_stock_levels(base_qs).count()


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

    ملاحظة:
      - المنتج الآن على مستوى StockMoveLine، لذلك نستخدم lines__product__...
    """
    if q:
        q = q.strip()
        if q:
            qs = qs.filter(
                Q(lines__product__code__icontains=q)
                | Q(lines__product__name__icontains=q)
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


def filter_products_queryset(
    qs,
    *,
    q: str | None = None,
    category_id: str | None = None,
    product_type: str | None = None,
    only_published: bool = False,
):
    """
    يطبّق فلاتر البحث القياسية على QuerySet للمنتجات:

      - q             : بحث بالكود / الاسم / الوصف المختصر
      - category_id   : رقم التصنيف (id) لتقييد النتائج
      - product_type  : نوع المنتج (من choices في الموديل)
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

    if product_type:
        qs = qs.filter(product_type=product_type)

    if only_published:
        qs = qs.filter(is_published=True)

    return qs
