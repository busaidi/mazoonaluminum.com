# sales/services.py

from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import SalesDocument, SalesLine, DeliveryNote, DeliveryLine


# ======================================================
# عروض الأسعار وأوامر البيع
# ======================================================

def create_quotation(contact, date=None, user=None, **kwargs) -> SalesDocument:
    """
    إنشاء عرض سعر بسيط في حالة المسودة.

    - يضبط kind = QUOTATION
    - status = DRAFT
    - لو تم تمرير user:
        created_by / updated_by = user
    """
    if date is None:
        date = timezone.localdate()

    extra_fields = kwargs.copy()

    if user is not None:
        # لو الموديل فيه الحقول (عندنا أكيد، لكنه احتياط)
        extra_fields.setdefault("created_by", user)
        extra_fields.setdefault("updated_by", user)

    doc = SalesDocument.objects.create(
        kind=SalesDocument.Kind.QUOTATION,
        status=SalesDocument.Status.DRAFT,
        contact=contact,
        date=date,
        **extra_fields,
    )
    return doc


@transaction.atomic
def confirm_quotation_to_order(document: SalesDocument, user=None) -> SalesDocument:
    """
    يحول عرض سعر قائم إلى أمر بيع دون إنشاء مستند جديد.
    - يتحقق أن المستند عرض سعر
    - يتحقق أنه غير ملغي
    - يتحقق أنه غير محذوف soft delete (إن وجد)
    - يحوله إلى أمر بيع
    - يضع حالته (مؤكد)
    - يحدّث updated_by لو تم تمرير user
    """

    # ممنوع التعامل مع مستند محذوف soft delete
    if getattr(document, "is_deleted", False):
        raise ValidationError(_("لا يمكن تحويل مستند محذوف."))

    # --- التحقق من النوع ---
    if not document.is_quotation:
        raise ValidationError(_("لا يمكن تحويل هذا المستند لأنه ليس عرض سعر."))

    # --- ممنوع تحويل مستند ملغي ---
    if document.is_cancelled:
        raise ValidationError(_("لا يمكن تحويل مستند ملغي إلى أمر بيع."))

    # احتياط: لو كان عليه فواتير
    if document.is_invoiced:
        raise ValidationError(_("لا يمكن تحويل مستند مفوتر إلى أمر بيع."))

    # --- تحديث النوع والحالة ---
    document.kind = SalesDocument.Kind.ORDER
    document.status = SalesDocument.Status.CONFIRMED

    if user is not None and hasattr(document, "updated_by"):
        document.updated_by = user

    document.save(update_fields=["kind", "status", "updated_by"] if hasattr(document, "updated_by") else ["kind", "status"])

    # --- إعادة حساب الإجمالي / الحقول المشتقة إن وجدت ---
    if hasattr(document, "recompute_totals"):
        document.recompute_totals(save=True)

    return document


@transaction.atomic
def mark_order_invoiced(order: SalesDocument, user=None) -> SalesDocument:
    """
    تعليم أمر البيع كمفوتر.
    (الربط مع فاتورة المحاسبة يصير في تطبيق المحاسبة لاحقاً)
    """
    if getattr(order, "is_deleted", False):
        raise ValidationError(_("لا يمكن فوتر أمر محذوف."))

    if not order.is_order:
        raise ValidationError(_("هذا المستند ليس أمر بيع."))

    if order.is_cancelled:
        raise ValidationError(_("لا يمكن فوتر أمر بيع ملغي."))

    if order.is_invoiced:
        # لا شيء لتغييره
        return order

    order.is_invoiced = True

    update_fields = ["is_invoiced"]
    if user is not None and hasattr(order, "updated_by"):
        order.updated_by = user
        update_fields.append("updated_by")

    order.save(update_fields=update_fields)
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
    - يتحقق أن order هو أمر بيع وغير ملغي وغير محذوف.
    - يضبط created_by / updated_by لو تم تمرير user.
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
    return dn


def add_delivery_line(
    delivery: DeliveryNote,
    product,
    quantity,
    description: str = "",
    user=None,
) -> DeliveryLine:
    """
    إضافة بند تسليم بسيط إلى مذكرة تسليم.
    - يتحقق أن مذكرة التسليم غير ملغاة وغير محذوفة.
    - يضبط created_by / updated_by لو تم تمرير user.
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
    return line


# ======================================================
# حالات المستند (إلغاء / إعادة لمسودة / إعادة فتح الملغى)
# ======================================================

@transaction.atomic
def cancel_sales_document(document: SalesDocument, user=None) -> SalesDocument:
    """
    يلغي المستند بشكل آمن.
    القواعد:
    - ممنوع إلغاء مستند مفوتر.
    - ممنوع إلغاء أمر بيع لديه مذكرات تسليم.
    - ممنوع إلغاء مستند محذوف soft delete.
    """
    if getattr(document, "is_deleted", False):
        raise ValidationError(_("لا يمكن إلغاء مستند محذوف."))

    # ممنوع إلغاء مستند مفوتر
    if document.is_invoiced:
        raise ValidationError(_("لا يمكن إلغاء مستند مفوتر."))

    # إذا أمر بيع وله مذكرات تسليم → ممنوع
    if document.is_order and document.delivery_notes.exists():
        raise ValidationError(_("لا يمكن إلغاء أمر بيع لديه مذكرات تسليم."))

    # تغيير الحالة
    document.status = SalesDocument.Status.CANCELLED

    update_fields = ["status"]
    if user is not None and hasattr(document, "updated_by"):
        document.updated_by = user
        update_fields.append("updated_by")

    document.save(update_fields=update_fields)
    return document


@transaction.atomic
def reset_sales_document_to_draft(document: SalesDocument, user=None) -> SalesDocument:
    """
    إعادة المستند إلى حالة المسودة (Draft) بشكل آمن.

    القواعد:
    - لا يمكن إعادة مستند مفوتر إلى مسودة.
    - لا يمكن إعادة أمر بيع له مذكرات تسليم إلى مسودة.
    - لا يمكن إعادة مستند ملغي إلى مسودة (له منطق آخر).
    - لا يمكن التعامل مع مستند محذوف.
    - إذا كان أمر بيع بلا تسليم → يُعاد إلى مسودة + يتحول إلى عرض سعر.
    """
    if getattr(document, "is_deleted", False):
        raise ValidationError(_("لا يمكن إعادة مستند محذوف إلى حالة المسودة."))

    if document.is_invoiced:
        raise ValidationError(_("لا يمكن إعادة مستند مفوتر إلى حالة المسودة."))

    if document.is_order and document.delivery_notes.exists():
        raise ValidationError(_("لا يمكن إعادة أمر بيع يملك مذكرات تسليم إلى حالة المسودة."))

    if document.is_cancelled:
        raise ValidationError(_("لا يمكن إعادة مستند ملغي إلى حالة المسودة."))

    if document.is_order:
        document.kind = SalesDocument.Kind.QUOTATION

    document.status = SalesDocument.Status.DRAFT

    update_fields = ["kind", "status"]
    if user is not None and hasattr(document, "updated_by"):
        document.updated_by = user
        update_fields.append("updated_by")

    document.save(update_fields=update_fields)
    return document


@transaction.atomic
def reopen_cancelled_sales_document(document: SalesDocument, user=None) -> SalesDocument:
    """
    إعادة فتح مستند ملغي وإرجاعه إلى حالة المسودة (Draft + Quotation)
    بشرط ألا يكون له أثر محاسبي أو مخزني.

    القواعد:
    - يجب أن يكون المستند في حالة الإلغاء.
    - لا يمكن إعادة فتح مستند مفوتر.
    - لا يمكن إعادة فتح مستند له مذكرات تسليم.
    - لا يمكن التعامل مع مستند محذوف.
    """
    if getattr(document, "is_deleted", False):
        raise ValidationError(_("لا يمكن إعادة فتح مستند محذوف."))

    if not document.is_cancelled:
        raise ValidationError(_("لا يمكن إعادة فتح مستند غير ملغي."))

    if document.is_invoiced:
        raise ValidationError(_("لا يمكن إعادة فتح مستند ملغي تم إصدار فاتورة عليه."))

    if document.delivery_notes.exists():
        raise ValidationError(_("لا يمكن إعادة فتح مستند ملغي له مذكرات تسليم."))

    # نرجعه عرض سعر + مسودة
    document.kind = SalesDocument.Kind.QUOTATION
    document.status = SalesDocument.Status.DRAFT

    update_fields = ["kind", "status"]
    if user is not None and hasattr(document, "updated_by"):
        document.updated_by = user
        update_fields.append("updated_by")

    document.save(update_fields=update_fields)

    if hasattr(document, "recompute_totals"):
        document.recompute_totals(save=True)

    return document


def can_reopen_cancelled(document: SalesDocument) -> bool:
    return (
        document.is_cancelled
        and not document.is_invoiced
        and not getattr(document, "is_deleted", False)
        and not document.delivery_notes.exists()
    )
