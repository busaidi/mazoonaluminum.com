# sales/services.py

from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core.models import AuditLog
from core.services.audit import log_event

from .models import SalesDocument, SalesLine, DeliveryNote, DeliveryLine


# ======================================================
# عروض الأسعار وأوامر البيع
# ======================================================

@transaction.atomic
def create_quotation(contact, date=None, user=None, **kwargs) -> SalesDocument:
    """
    إنشاء عرض سعر بسيط في حالة المسودة.

    - يضبط kind = QUOTATION
    - يضبط status = DRAFT
    - في حال تمرير user:
        يتم ضبط created_by / updated_by = user
    - يسجل عملية التدقيق (Audit) عند الإنشاء.
    """
    if date is None:
        date = timezone.localdate()

    extra_fields = kwargs.copy()

    if user is not None:
        # في حال وجود الحقول في الموديل (موجودة في BaseModel لكن احتياط)
        extra_fields.setdefault("created_by", user)
        extra_fields.setdefault("updated_by", user)

    doc = SalesDocument.objects.create(
        kind=SalesDocument.Kind.QUOTATION,
        status=SalesDocument.Status.DRAFT,
        contact=contact,
        date=date,
        **extra_fields,
    )

    # --- الأوديت: إنشاء عرض سعر ---
    log_event(
        action=AuditLog.Action.CREATE,
        message=_("تم إنشاء عرض السعر %(number)s") % {
            "number": doc.display_number
        },
        actor=user,
        target=doc,
        extra={
            "kind": doc.kind,
            "status": doc.status,
            "contact_id": doc.contact_id,
        },
    )

    return doc


@transaction.atomic
def confirm_quotation_to_order(document: SalesDocument, user=None) -> SalesDocument:
    """
    تحويل عرض سعر قائم إلى أمر بيع دون إنشاء سجل جديد.

    القواعد:
    - يجب أن يكون المستند من نوع عرض سعر.
    - يجب ألا يكون المستند ملغياً.
    - يجب ألا يكون المستند محذوفاً (soft delete).
    - يجب ألا يكون المستند مفوترًا.
    - يتم تحويل النوع إلى ORDER.
    - يتم تحويل الحالة إلى CONFIRMED.
    - يتم تحديث updated_by إذا تم تمرير user.
    - يتم تسجيل عملية الأوديت لتغيير النوع والحالة.
    """

    # ممنوع التعامل مع مستند محذوف soft delete
    if getattr(document, "is_deleted", False):
        raise ValidationError(_("لا يمكن تحويل مستند محذوف."))

    # يجب أن يكون عرض سعر
    if not document.is_quotation:
        raise ValidationError(_("لا يمكن تحويل هذا المستند لأنه ليس عرض سعر."))

    # ممنوع تحويل مستند ملغي
    if document.is_cancelled:
        raise ValidationError(_("لا يمكن تحويل مستند ملغي إلى أمر بيع."))

    # احتياط: ممنوع تحويل مستند مفوتر
    if document.is_invoiced:
        raise ValidationError(_("لا يمكن تحويل مستند مفوتر إلى أمر بيع."))

    old_kind = document.kind
    old_status = document.status

    # تحديث النوع والحالة
    document.kind = SalesDocument.Kind.ORDER
    document.status = SalesDocument.Status.CONFIRMED

    update_fields = ["kind", "status"]
    if user is not None and hasattr(document, "updated_by"):
        document.updated_by = user
        update_fields.append("updated_by")

    document.save(update_fields=update_fields)

    # إعادة احتساب الإجماليات إن وُجدت الدالة في الموديل
    if hasattr(document, "recompute_totals"):
        document.recompute_totals(save=True)

    # --- الأوديت: تحويل عرض إلى أمر بيع ---
    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=_("تم تحويل عرض السعر %(number)s إلى أمر بيع.") % {
            "number": document.display_number
        },
        actor=user,
        target=document,
        extra={
            "old_kind": old_kind,
            "new_kind": document.kind,
            "old_status": old_status,
            "new_status": document.status,
        },
    )

    return document


@transaction.atomic
def mark_order_invoiced(order: SalesDocument, user=None) -> SalesDocument:
    """
    تعليم أمر البيع على أنه مفوتر.

    (الربط الفعلي مع فاتورة المحاسبة سيتم في تطبيق المحاسبة لاحقاً)

    القواعد:
    - لا يمكن التعامل مع أمر محذوف soft delete.
    - يجب أن يكون المستند أمر بيع (وليس عرض سعر).
    - لا يمكن فوتر أمر ملغي.
    - في حال كان مفوترًا مسبقاً يتم إرجاعه كما هو.
    - يتم تسجيل عملية الأوديت عند التعليم كمفوتر.
    """
    if getattr(order, "is_deleted", False):
        raise ValidationError(_("لا يمكن فوتر أمر محذوف."))

    if not order.is_order:
        raise ValidationError(_("هذا المستند ليس أمر بيع."))

    if order.is_cancelled:
        raise ValidationError(_("لا يمكن فوتر أمر بيع ملغي."))

    if order.is_invoiced:
        # لا يوجد تغيير مطلوب
        return order

    order.is_invoiced = True

    update_fields = ["is_invoiced"]
    if user is not None and hasattr(order, "updated_by"):
        order.updated_by = user
        update_fields.append("updated_by")

    order.save(update_fields=update_fields)

    # --- الأوديت: تعليم أمر البيع كمفوتر ---
    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=_("تم تعليم أمر البيع %(number)s كمفوتر.") % {
            "number": order.display_number
        },
        actor=user,
        target=order,
        extra={
            "is_invoiced": True,
            "status": order.status,
            "kind": order.kind,
        },
    )

    return order


# ======================================================
# مذكرات التسليم
# ======================================================

@transaction.atomic
def create_delivery_note_for_order(
    order: SalesDocument,
    date=None,
    notes: str = "",
    user=None,
) -> DeliveryNote:
    """
    إنشاء مذكرة تسليم جديدة مرتبطة بأمر بيع.

    القواعد:
    - لا يمكن الإنشاء لأمر محذوف soft delete.
    - يجب أن يكون المستند أمر بيع (وليس عرض سعر).
    - لا يمكن الإنشاء لأمر ملغي.
    - يتم ضبط created_by / updated_by إذا تم تمرير user.
    - يتم تسجيل عملية الأوديت عند إنشاء مذكرة التسليم.
    """
    if getattr(order, "is_deleted", False):
        raise ValidationError(_("لا يمكن إنشاء مذكرة تسليم لأمر بيع محذوف."))

    if not order.is_order:
        raise ValidationError(_("لا يمكن إنشاء مذكرة تسليم إلا لأمر بيع."))

    if order.is_cancelled:
        raise ValidationError(_("لا يمكن إنشاء مذكرة تسليم لأمر بيع ملغي."))

    if date is None:
        date = timezone.localdate()

    extra_fields = {
        "order": order,
        "date": date,
        "status": DeliveryNote.Status.DRAFT,
        "notes": notes,
    }

    if user is not None:
        extra_fields.setdefault("created_by", user)
        extra_fields.setdefault("updated_by", user)

    dn = DeliveryNote.objects.create(**extra_fields)

    # --- الأوديت: إنشاء مذكرة تسليم ---
    log_event(
        action=AuditLog.Action.CREATE,
        message=_("تم إنشاء مذكرة التسليم %(dn)s لأمر البيع %(order)s") % {
            "dn": dn.display_number,
            "order": order.display_number,
        },
        actor=user,
        target=dn,
        extra={
            "order_id": order.id,
            "order_number": order.display_number,
            "status": dn.status,
            "date": str(dn.date),
        },
    )

    return dn


@transaction.atomic
def add_delivery_line(
    delivery: DeliveryNote,
    product,
    quantity,
    description: str = "",
    user=None,
) -> DeliveryLine:
    """
    إضافة بند تسليم بسيط إلى مذكرة تسليم.

    القواعد:
    - لا يمكن الإضافة على مذكرة محذوفة soft delete.
    - لا يمكن الإضافة على مذكرة ملغاة.
    - يتم ضبط created_by / updated_by إذا تم تمرير user.
    - يتم تسجيل عملية الأوديت عند إضافة البند.
    """
    if getattr(delivery, "is_deleted", False):
        raise ValidationError(_("لا يمكن إضافة بنود لمذكرة تسليم محذوفة."))

    if delivery.status == DeliveryNote.Status.CANCELLED:
        raise ValidationError(_("لا يمكن إضافة بنود لمذكرة تسليم ملغاة."))

    extra_fields = {
        "delivery": delivery,
        "product": product,
        "quantity": quantity,
        "description": description or (product.name if product else ""),
    }

    if user is not None:
        extra_fields.setdefault("created_by", user)
        extra_fields.setdefault("updated_by", user)

    line = DeliveryLine.objects.create(**extra_fields)

    # --- الأوديت: إضافة بند تسليم ---
    log_event(
        action=AuditLog.Action.CREATE,
        message=_("تمت إضافة بند تسليم إلى %(dn)s") % {
            "dn": delivery.display_number,
        },
        actor=user,
        target=line,
        extra={
            "delivery_id": delivery.id,
            "delivery_number": delivery.display_number,
            "product_id": getattr(product, "id", None),
            "product_name": getattr(product, "name", None),
            "quantity": float(quantity),
        },
    )

    return line


# ======================================================
# حالات المستند (إلغاء / إعادة لمسودة / إعادة فتح الملغى)
# ======================================================

@transaction.atomic
def cancel_sales_document(document: SalesDocument, user=None) -> SalesDocument:
    """
    إلغاء مستند مبيعات بشكل آمن.

    القواعد:
    - لا يمكن إلغاء مستند محذوف soft delete.
    - لا يمكن إلغاء مستند مفوتر.
    - لا يمكن إلغاء أمر بيع لديه مذكرات تسليم.
    - يتم تسجيل عملية الأوديت عند الإلغاء.
    """
    if getattr(document, "is_deleted", False):
        raise ValidationError(_("لا يمكن إلغاء مستند محذوف."))

    # لا يمكن إلغاء مستند مفوتر
    if document.is_invoiced:
        raise ValidationError(_("لا يمكن إلغاء مستند مفوتر."))

    # إذا كان أمر بيع وله مذكرات تسليم → ممنوع
    if document.is_order and document.delivery_notes.exists():
        raise ValidationError(_("لا يمكن إلغاء أمر بيع لديه مذكرات تسليم."))

    old_status = document.status

    # تغيير الحالة إلى ملغي
    document.status = SalesDocument.Status.CANCELLED

    update_fields = ["status"]
    if user is not None and hasattr(document, "updated_by"):
        document.updated_by = user
        update_fields.append("updated_by")

    document.save(update_fields=update_fields)

    # --- الأوديت: إلغاء مستند ---
    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=_("تم إلغاء مستند المبيعات %(number)s") % {
            "number": document.display_number
        },
        actor=user,
        target=document,
        extra={
            "old_status": old_status,
            "new_status": document.status,
            "kind": document.kind,
            "is_invoiced": document.is_invoiced,
        },
    )

    return document


@transaction.atomic
def reset_sales_document_to_draft(document: SalesDocument, user=None) -> SalesDocument:
    """
    إعادة مستند المبيعات إلى حالة المسودة (Draft) بشكل آمن.

    القواعد:
    - لا يمكن إعادة مستند محذوف soft delete إلى مسودة.
    - لا يمكن إعادة مستند مفوتر إلى مسودة.
    - لا يمكن إعادة أمر بيع له مذكرات تسليم إلى مسودة.
    - لا يمكن إعادة مستند ملغي إلى مسودة (له دالة خاصة).
    - إذا كان أمر بيع بدون مذكرات تسليم → يرجع إلى عرض سعر + مسودة.
    - يتم تسجيل عملية الأوديت عند الإرجاع إلى المسودة.
    """
    if getattr(document, "is_deleted", False):
        raise ValidationError(_("لا يمكن إعادة مستند محذوف إلى حالة المسودة."))

    if document.is_invoiced:
        raise ValidationError(_("لا يمكن إعادة مستند مفوتر إلى حالة المسودة."))

    if document.is_order and document.delivery_notes.exists():
        raise ValidationError(_("لا يمكن إعادة أمر بيع يملك مذكرات تسليم إلى حالة المسودة."))

    if document.is_cancelled:
        raise ValidationError(_("لا يمكن إعادة مستند ملغي إلى حالة المسودة."))

    old_kind = document.kind
    old_status = document.status

    if document.is_order:
        document.kind = SalesDocument.Kind.QUOTATION

    document.status = SalesDocument.Status.DRAFT

    update_fields = ["kind", "status"]
    if user is not None and hasattr(document, "updated_by"):
        document.updated_by = user
        update_fields.append("updated_by")

    document.save(update_fields=update_fields)

    if hasattr(document, "recompute_totals"):
        document.recompute_totals(save=True)

    # --- الأوديت: إعادة إلى مسودة ---
    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=_("تمت إعادة مستند المبيعات %(number)s إلى حالة المسودة.") % {
            "number": document.display_number
        },
        actor=user,
        target=document,
        extra={
            "old_kind": old_kind,
            "new_kind": document.kind,
            "old_status": old_status,
            "new_status": document.status,
        },
    )

    return document


@transaction.atomic
def reopen_cancelled_sales_document(document: SalesDocument, user=None) -> SalesDocument:
    """
    إعادة فتح مستند مبيعات ملغي وإرجاعه إلى حالة المسودة (Draft)
    كعرض سعر، بشرط عدم وجود أثر محاسبي أو مخزني عليه.

    القواعد:
    - يجب أن يكون المستند في حالة الإلغاء.
    - لا يمكن إعادة فتح مستند محذوف soft delete.
    - لا يمكن إعادة فتح مستند مفوتر.
    - لا يمكن إعادة فتح مستند له مذكرات تسليم.
    - يتم تسجيل عملية الأوديت عند إعادة الفتح.
    """
    if getattr(document, "is_deleted", False):
        raise ValidationError(_("لا يمكن إعادة فتح مستند محذوف."))

    if not document.is_cancelled:
        raise ValidationError(_("لا يمكن إعادة فتح مستند غير ملغي."))

    if document.is_invoiced:
        raise ValidationError(_("لا يمكن إعادة فتح مستند ملغي تم إصدار فاتورة عليه."))

    if document.delivery_notes.exists():
        raise ValidationError(_("لا يمكن إعادة فتح مستند ملغي له مذكرات تسليم."))

    old_kind = document.kind
    old_status = document.status

    # إرجاعه إلى عرض سعر + مسودة
    document.kind = SalesDocument.Kind.QUOTATION
    document.status = SalesDocument.Status.DRAFT

    update_fields = ["kind", "status"]
    if user is not None and hasattr(document, "updated_by"):
        document.updated_by = user
        update_fields.append("updated_by")

    document.save(update_fields=update_fields)

    if hasattr(document, "recompute_totals"):
        document.recompute_totals(save=True)

    # --- الأوديت: إعادة فتح المستند الملغي ---
    log_event(
        action=AuditLog.Action.STATUS_CHANGE,
        message=_("تمت إعادة فتح مستند المبيعات الملغي %(number)s") % {
            "number": document.display_number
        },
        actor=user,
        target=document,
        extra={
            "old_kind": old_kind,
            "new_kind": document.kind,
            "old_status": old_status,
            "new_status": document.status,
        },
    )

    return document


def can_reopen_cancelled(document: SalesDocument) -> bool:
    """
    دالة مساعدة للـ UI: هل يمكن إعادة فتح هذا المستند الملغي؟
    """
    return (
        document.is_cancelled
        and not document.is_invoiced
        and not getattr(document, "is_deleted", False)
        and not document.delivery_notes.exists()
    )
