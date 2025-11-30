# sales/services.py

from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import SalesDocument, SalesLine, DeliveryNote, DeliveryLine


# ========== عروض الأسعار وأوامر البيع ==========

def create_quotation(contact, date=None, **kwargs) -> SalesDocument:
    """
    إنشاء عرض سعر بسيط في حالة المسودة.
    """
    if date is None:
        date = timezone.localdate()

    doc = SalesDocument.objects.create(
        kind=SalesDocument.Kind.QUOTATION,
        status=SalesDocument.Status.DRAFT,
        contact=contact,
        date=date,
        **kwargs,
    )
    return doc


@transaction.atomic
def confirm_quotation_to_order(document: SalesDocument) -> SalesDocument:
    """
    يحول عرض سعر قائم إلى أمر بيع دون إنشاء مستند جديد.
    - يتحقق أن المستند عرض سعر
    - يتحقق أنه غير ملغي
    - يحوله إلى أمر بيع
    - يضع حالته (مؤكد)
    """

    # --- التحقق من النوع ---
    if not document.is_quotation:
        raise ValidationError(_("لا يمكن تحويل هذا المستند لأنه ليس عرض سعر."))

    # --- ممنوع تحويل مستند ملغي ---
    if document.is_cancelled:
        raise ValidationError(_("لا يمكن تحويل مستند ملغي إلى أمر بيع."))

    # احتياط: لو كان عليه فواتير (غير منطقي لكنه أأمن)
    if document.is_invoiced:
        raise ValidationError(_("لا يمكن تحويل مستند مفوتر إلى أمر بيع."))

    # --- تحديث النوع والحالة ---
    document.kind = SalesDocument.Kind.ORDER
    document.status = SalesDocument.Status.CONFIRMED
    document.save(update_fields=["kind", "status"])

    # --- إعادة حساب الإجمالي / الحقول المشتقة إن وجدت ---
    if hasattr(document, "recompute_totals"):
        document.recompute_totals(save=True)

    return document


@transaction.atomic
def mark_order_invoiced(order: SalesDocument) -> SalesDocument:
    """
    تعليم أمر البيع كمفوتر.
    (الربط مع فاتورة المحاسبة يصير في تطبيق المحاسبة لاحقاً)
    """
    if not order.is_order:
        raise ValidationError(_("هذا المستند ليس أمر بيع."))

    if order.is_cancelled:
        raise ValidationError(_("لا يمكن فوتر أمر بيع ملغي."))

    if order.is_invoiced:
        # لا شيء لتغييره
        return order

    order.is_invoiced = True
    order.save(update_fields=["is_invoiced"])
    return order


# ========== مذكرات التسليم ==========

@transaction.atomic
def create_delivery_note_for_order(order: SalesDocument, date=None, notes: str = "") -> DeliveryNote:
    """
    إنشاء مذكرة تسليم جديدة مرتبطة بأمر بيع.
    حالياً لا تنسخ بنود أمر البيع، فقط تنشئ الرأس (الهيدر).
    لاحقاً ممكن نضيف خيار لنسخ البنود تلقائياً.
    """
    if not order.is_order:
        raise ValidationError(_("لا يمكن إنشاء مذكرة تسليم إلا لأمر بيع."))

    if order.is_cancelled:
        raise ValidationError(_("لا يمكن إنشاء مذكرة تسليم لأمر بيع ملغي."))

    if date is None:
        date = timezone.localdate()

    dn = DeliveryNote.objects.create(
        order=order,
        date=date,
        status=DeliveryNote.Status.DRAFT,
        notes=notes,
    )
    return dn


def add_delivery_line(delivery: DeliveryNote, product, quantity, description: str = "") -> DeliveryLine:
    """
    إضافة بند تسليم بسيط إلى مذكرة تسليم.
    حالياً لا يتحقق من الكميات مقابل أمر البيع.
    """
    if delivery.status == DeliveryNote.Status.CANCELLED:
        raise ValidationError(_("لا يمكن إضافة بنود لمذكرة تسليم ملغاة."))

    line = DeliveryLine.objects.create(
        delivery=delivery,
        product=product,
        quantity=quantity,
        description=description or (product.name if product else ""),
    )
    return line


# ========== حالات المستند (إلغاء / إعادة لمسودة) ==========

@transaction.atomic
def cancel_sales_document(document: SalesDocument) -> SalesDocument:
    """
    يلغي المستند بشكل آمن.
    القواعد:
    - ممنوع إلغاء مستند مفوتر.
    - ممنوع إلغاء أمر بيع لديه مذكرات تسليم.
    """

    # ممنوع إلغاء مستند مفوتر
    if document.is_invoiced:
        raise ValidationError(_("لا يمكن إلغاء مستند مفوتر."))

    # إذا أمر بيع وله مذكرات تسليم → ممنوع
    if document.is_order and document.delivery_notes.exists():
        raise ValidationError(_("لا يمكن إلغاء أمر بيع لديه مذكرات تسليم."))

    # تغيير الحالة
    document.status = SalesDocument.Status.CANCELLED
    document.save(update_fields=["status"])
    return document


@transaction.atomic
def reset_sales_document_to_draft(document: SalesDocument) -> SalesDocument:
    """
    إعادة المستند إلى حالة المسودة (Draft) بشكل آمن.

    القواعد:
    - لا يمكن إعادة مستند مفوتر إلى مسودة.
    - لا يمكن إعادة أمر بيع له مذكرات تسليم إلى مسودة.
    - لا يمكن إعادة مستند ملغي إلى مسودة.
    - إذا كان أمر بيع بلا تسليم → يُعاد إلى مسودة + يتحول إلى عرض سعر.
    """

    # ممنوع إعادة مستند مفوتر إلى مسودة
    if document.is_invoiced:
        raise ValidationError(_("لا يمكن إعادة مستند مفوتر إلى حالة المسودة."))

    # إذا أمر بيع وله مذكرات تسليم → ممنوع
    if document.is_order and document.delivery_notes.exists():
        raise ValidationError(_("لا يمكن إعادة أمر بيع يملك مذكرات تسليم إلى حالة المسودة."))

    # لا نعيد الملغي لمسودة (له منطق مختلف لو حبيت لاحقاً)
    if document.is_cancelled:
        raise ValidationError(_("لا يمكن إعادة مستند ملغي إلى حالة المسودة."))

    # إذا كان أمر بيع بدون تسليم → رجّعه عرض سعر
    if document.is_order:
        document.kind = SalesDocument.Kind.QUOTATION

    document.status = SalesDocument.Status.DRAFT
    document.save(update_fields=["kind", "status"])

    return document
@transaction.atomic
def reopen_cancelled_sales_document(document: SalesDocument) -> SalesDocument:
    """
    إعادة فتح مستند ملغي وإرجاعه إلى حالة المسودة (Draft + Quotation)
    بشرط ألا يكون له أثر محاسبي أو مخزني.

    القواعد:
    - يجب أن يكون المستند في حالة الإلغاء.
    - لا يمكن إعادة فتح مستند مفوتر.
    - لا يمكن إعادة فتح مستند له مذكرات تسليم.
    - عند الإعادة، يتم إرجاعه كعرض سعر في حالة مسودة.
    """

    # يجب أن يكون ملغيًا
    if not document.is_cancelled:
        raise ValidationError(_("لا يمكن إعادة فتح مستند غير ملغي."))

    # ممنوع إذا مفوتر
    if document.is_invoiced:
        raise ValidationError(_("لا يمكن إعادة فتح مستند ملغي تم إصدار فاتورة عليه."))

    # ممنوع إذا له مذكرات تسليم
    if document.delivery_notes.exists():
        raise ValidationError(_("لا يمكن إعادة فتح مستند ملغي له مذكرات تسليم."))

    # نرجعه عرض سعر + مسودة
    document.kind = SalesDocument.Kind.QUOTATION
    document.status = SalesDocument.Status.DRAFT
    document.save(update_fields=["kind", "status"])

    # لو عندك إعادة حساب إجمالي
    if hasattr(document, "recompute_totals"):
        document.recompute_totals(save=True)

    return document
def can_reopen_cancelled(document: SalesDocument) -> bool:
    return (
        document.is_cancelled
        and not document.is_invoiced
        and not document.delivery_notes.exists()
    )
