# sales/services.py

from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import SalesDocument, SalesLine, DeliveryNote, DeliveryLine


# ========== عروض الأسعار وأوامر البيع ==========

def create_quotation(contact, date=None, **kwargs) -> SalesDocument:
    """
    إنشاء عرض سعر بسيط.
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

    # --- تحديث النوع والحالة ---
    document.kind = SalesDocument.Kind.ORDER
    document.status = SalesDocument.Status.CONFIRMED
    document.save(update_fields=["kind", "status"])

    # --- إعادة حساب الإجمالي / الحقول المشتقة إن وجدت ---
    if hasattr(document, "recompute_totals"):
        document.recompute_totals(save=True)

    return document


def mark_order_invoiced(order: SalesDocument) -> SalesDocument:
    """
    تعليم أمر البيع كمفوتر.
    (الربط مع فاتورة المحاسبة يصير في تطبيق المحاسبة لاحقاً)
    """
    if not order.is_order:
        raise ValidationError("هذا المستند ليس أمر بيع.")

    if order.is_cancelled:
        raise ValidationError("لا يمكن فوتر أمر بيع ملغي.")

    if order.is_invoiced:
        return order  # لا شيء لتغييره

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
        raise ValidationError("لا يمكن إنشاء مذكرة تسليم إلا لأمر بيع.")

    if order.is_cancelled:
        raise ValidationError("لا يمكن إنشاء مذكرة تسليم لأمر بيع ملغي.")

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
        raise ValidationError("لا يمكن إضافة بنود لمذكرة تسليم ملغاة.")

    line = DeliveryLine.objects.create(
        delivery=delivery,
        product=product,
        quantity=quantity,
        description=description or (product.name if product else ""),
    )
    return line


def cancel_sales_document(document: SalesDocument):
    """
    يلغي المستند بشكل آمن.
    """

    # ممنوع إلغاء مستند مفوتر
    if document.is_invoiced:
        raise Exception("لا يمكن إلغاء مستند مفوتر.")

    # إذا أمر بيع وله مذكرات تسليم → ممنوع
    if document.is_order and document.delivery_notes.exists():
        raise Exception("لا يمكن إلغاء أمر بيع لديه مذكرات تسليم.")

    # تغيير الحالة
    document.status = SalesDocument.Status.CANCELLED
    document.save()


def reset_sales_document_to_draft(document: SalesDocument):
    """
    إعادة المستند إلى حالة المسودة (Draft) بشكل آمن.

    القيود المقترحة:
    - لا يمكن إعادة مستند مفوتر إلى مسودة.
    - لا يمكن إعادة أمر بيع له مذكرات تسليم إلى مسودة.
    """

    # ممنوع إعادة مستند مفوتر إلى مسودة
    if document.is_invoiced:
        raise Exception(_("لا يمكن إعادة مستند مفوتر إلى حالة المسودة."))

    # إذا أمر بيع وله مذكرات تسليم → ممنوع
    if document.is_order and document.delivery_notes.exists():
        raise Exception(_("لا يمكن إعادة أمر بيع يملك مذكرات تسليم إلى حالة المسودة."))

    # إذا كان ملغي، ممكن تخليه ممنوع أو مسموح
    # هنا بمنطق محافظ: لا نعيد الملغي لمسودة
    if document.is_cancelled:
        raise Exception(_("لا يمكن إعادة مستند ملغي إلى حالة المسودة."))

    document.status = SalesDocument.Status.DRAFT
    document.save()