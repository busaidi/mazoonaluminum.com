# sales/services.py

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core.models import AuditLog
from core.services.audit import log_event
from inventory.models import Product
from uom.models import UnitOfMeasure

from .models import SalesDocument, SalesLine, DeliveryNote, DeliveryLine


# ======================================================
# خدمات مستندات المبيعات (عروض الأسعار وأوامر البيع)
# ======================================================


@transaction.atomic
def create_quotation(contact, date=None, user=None, **kwargs) -> SalesDocument:
    """
    إنشاء عرض سعر بسيط في حالة المسودة.

    المسؤوليات:
    - ضبط kind = QUOTATION.
    - ضبط status = DRAFT.
    - ضبط created_by / updated_by (إن تم تمرير user).
    - تسجيل عملية التدقيق (Audit Log) عند الإنشاء.

    ملاحظة:
    - الإشعارات (Notifications) تتم حالياً من الفيوهات وليس من هنا،
      لأن المستفيد غالباً هو المستخدم الحالي (request.user).
    """
    if date is None:
        # نستخدم التاريخ المحلي للسيرفر (مع احترام إعدادات التايمزون في Django)
        date = timezone.localdate()

    # نسمح بتمرير حقول إضافية مثل الملاحظات أو أرقام مرجعية عبر **kwargs
    extra_fields = kwargs.copy()

    if user is not None:
        # في حال وجود user نضبط created_by / updated_by مرة واحدة هنا
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
    - يجب أن يكون المستند من نوع عرض سعر (quotation).
    - يجب ألا يكون المستند ملغياً.
    - يجب ألا يكون المستند محذوفاً (soft delete).
    - يجب ألا يكون المستند مفوترًا (is_invoiced=False).
    - يتم تحويل النوع إلى ORDER.
    - يتم تحويل الحالة إلى CONFIRMED.
    - يتم تحديث updated_by إذا تم تمرير user.
    - يتم تسجيل عملية الأوديت لتغيير النوع والحالة.

    ملاحظة:
    - الفيو (ConvertQuotationToOrderView) يتكفّل بعرض الرسائل للمستخدم
      وإطلاق الإشعار عند النجاح.
    """

    # منع التعامل مع سجلات محذوفة (soft delete)
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

    # تحويل النوع والحالة لأمر بيع مؤكد
    document.kind = SalesDocument.Kind.ORDER
    document.status = SalesDocument.Status.CONFIRMED

    update_fields = ["kind", "status"]
    if user is not None and hasattr(document, "updated_by"):
        document.updated_by = user
        update_fields.append("updated_by")

    document.save(update_fields=update_fields)

    # إعادة احتساب الإجماليات لو الدالة موجودة في الموديل
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
    - يجب أن يكون المستند أمر بيع (is_order=True).
    - لا يمكن فوتر أمر ملغي.
    - في حال كان مفوترًا مسبقاً يتم إرجاعه كما هو.
    - يتم تسجيل عملية الأوديت عند التعليم كمفوتر.

    ملاحظة:
    - الفيو (MarkOrderInvoicedView) يتكفّل بعرض الرسائل والإشعارات.
    """
    if getattr(order, "is_deleted", False):
        raise ValidationError(_("لا يمكن فوتر أمر محذوف."))

    if not order.is_order:
        raise ValidationError(_("هذا المستند ليس أمر بيع."))

    if order.is_cancelled:
        raise ValidationError(_("لا يمكن فوتر أمر بيع ملغي."))

    if order.is_invoiced:
        # لو مفوتر مسبقاً نرجعه كما هو بدون أي تغيير
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
# خدمات مذكرات التسليم
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

    ملاحظة:
    - الفيو (DeliveryNoteCreateView) يتكفّل بإطلاق الإشعارات وعرض الرسائل.
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
        # نترك contact فارغاً هنا، والموديل/الفيو يتولى effective_contact
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
    uom=None,
    user=None,
) -> DeliveryLine:
    """
    إضافة بند تسليم بسيط إلى مذكرة تسليم.

    القواعد:
    - لا يمكن الإضافة على مذكرة محذوفة soft delete.
    - لا يمكن الإضافة على مذكرة ملغاة.
    - يمكن أن يكون السطر بمنتج أو وصف فقط.
    - يتم ضبط created_by / updated_by إذا تم تمرير user.
    - يتم تسجيل عملية الأوديت عند إضافة البند.

    ملاحظة:
    - هذا السيرفس يمكن استخدامه من واجهات مختلفة (HTML / API)،
      لذلك يهتم فقط بالمنطق والأوديت.
    """
    if getattr(delivery, "is_deleted", False):
        raise ValidationError(_("لا يمكن إضافة بنود لمذكرة تسليم محذوفة."))

    if delivery.status == DeliveryNote.Status.CANCELLED:
        raise ValidationError(_("لا يمكن إضافة بنود لمذكرة تسليم ملغاة."))

    # نضمن أن الكمية ليست None (الفورم يتكفّل بالتحقق عادة)
    quantity = quantity or 0

    extra_fields = {
        "delivery": delivery,
        "product": product,
        "quantity": quantity,
        # لو ما في وصف نستخدم اسم المنتج كخيار افتراضي
        "description": description or (product.name if product else ""),
        "uom": uom,  # دعم تخزين وحدة القياس
    }

    # تعبئة created_by / updated_by عند الحاجة
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
            "uom_id": getattr(uom, "id", None),
            "uom_code": getattr(uom, "code", None),
        },
    )

    return line


# ======================================================
# تغييرات حالات مستند المبيعات
# (إلغاء / إعادة لمسودة / إعادة فتح الملغى)
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

    ملاحظة:
    - الفيو (CancelSalesDocumentView) يعرض الرسائل والإشعارات.
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

    ملاحظة:
    - الفيو (ResetSalesDocumentToDraftView) يتعامل مع الرسائل والإشعارات.
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

    # لو المستند أمر بيع بدون مذكرات تسليم نرجعه لعرض سعر
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

    ملاحظة:
    - الفيو (sales_reopen_view) يرسل إشعاراً للمستخدم عند النجاح.
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

    الشروط:
    - أن يكون في حالة الإلغاء.
    - غير مفوتر.
    - غير محذوف soft delete.
    - لا توجد عليه مذكرات تسليم.
    """

    # نفصل الشروط خطوة خطوة عشان تكون واضحة في الديبَغ
    if getattr(document, "is_deleted", False):
        return False

    if not document.is_cancelled:
        return False

    if document.is_invoiced:
        return False

    if document.delivery_notes.exists():
        return False

    return True




#حفظ السالس اوردر
@transaction.atomic
def save_sales_lines_from_post(*, document: SalesDocument, post_data, user=None) -> None:
    """
    حفظ/تحديث/حذف بنود مستند المبيعات بناءً على POST يدوي.

    يتوقع الحقول بالشكل:
    - lines-TOTAL_FORMS
    - lines-0-id
    - lines-0-product
    - lines-0-description
    - lines-0-quantity
    - lines-0-unit_price
    - lines-0-discount_percent
    - lines-0-uom
    - lines-0-DELETE (اختياري)
    """
    total_forms = int(post_data.get("lines-TOTAL_FORMS") or 0)

    for i in range(total_forms):
        prefix = f"lines-{i}"

        line_id = post_data.get(f"{prefix}-id") or None
        delete_flag = post_data.get(f"{prefix}-DELETE")

        product_id = post_data.get(f"{prefix}-product") or ""
        description = (post_data.get(f"{prefix}-description") or "").strip()
        quantity = post_data.get(f"{prefix}-quantity") or ""
        unit_price = post_data.get(f"{prefix}-unit_price") or ""
        discount_percent = post_data.get(f"{prefix}-discount_percent") or ""
        uom_id = post_data.get(f"{prefix}-uom") or ""

        has_content = bool(product_id or description or quantity or unit_price)

        # لو فيه id نحاول نجيب السطر الحالي
        line = None
        if line_id:
            try:
                line = SalesLine.objects.get(pk=line_id, document=document)
            except SalesLine.DoesNotExist:
                line = None

        # 1) حذف
        if delete_flag and line:
            line.delete()
            continue

        # 2) صف فاضي → احذفه لو موجود أو تجاهله لو جديد
        if not has_content:
            if line:
                line.delete()
            continue

        # 3) إنشاء أو تحديث
        if line is None:
            line = SalesLine(document=document)

        line.product_id = int(product_id) if product_id else None
        line.description = description
        line.quantity = quantity or None
        line.unit_price = unit_price or None
        line.discount_percent = discount_percent or "0"
        line.uom_id = int(uom_id) if uom_id else None

        if user is not None:
            if hasattr(line, "created_by") and line.pk is None:
                line.created_by = user
            if hasattr(line, "updated_by"):
                line.updated_by = user

        # هذا الـ save يستدعي compute_line_total + recompute_totals على الوثيقة
        line.save()

    # احتياط لو حاب تتأكد من الإجماليات مرة وحدة:
    if hasattr(document, "recompute_totals"):
        document.recompute_totals(save=True)




@transaction.atomic
def save_sales_lines_from_formset(*, document, lines_formset, user):
    """
    Save / update SalesLine rows for a SalesDocument using a bound formset.

    - Uses form.cleaned_data (so validation already done).
    - Respects DELETE checkbox.
    - Creates/updates lines and removes deleted ones.
    """

    if not lines_formset.is_valid():
        # Safety net: view يجب أن يتأكد من is_valid قبل النداء، لكن نخليها احتياطياً
        raise ValidationError(_("خطأ في بنود المستند، يرجى التحقق من القيم."))

    # All existing lines for this document (to know what to delete later)
    existing_ids = set(
        SalesLine.objects.filter(document=document).values_list("id", flat=True)
    )
    kept_ids = set()
    line_index = 0  # نستخدمه كـ sort_order أو line_number لو موجود

    for form in lines_formset:
        cd = getattr(form, "cleaned_data", None) or {}
        if not cd:
            continue

        # 1) حذف السطر إذا مؤشر DELETE
        if cd.get("DELETE"):
            line_id = cd.get("id")
            if line_id:
                SalesLine.objects.filter(id=line_id, document=document).delete()
            continue

        # 2) قراءة الحقول الأساسية
        product  = cd.get("product")
        uom      = cd.get("uom")
        quantity = cd.get("quantity")
        unit_price = cd.get("unit_price")
        discount_percent = cd.get("discount_percent")
        description = cd.get("description")

        # تأمين الـ Decimal: لو None نخليها 0
        quantity = quantity if quantity is not None else Decimal("0")
        unit_price = unit_price if unit_price is not None else Decimal("0")
        discount_percent = discount_percent if discount_percent is not None else Decimal("0")

        # 3) تجاهل الأسطر الفارغة (بدون منتج أو كمية <= 0)
        if not product or not uom or quantity <= 0:
            continue

        # 4) form.save(commit=False) يبني SalesLine مع حقول الفورم
        line = form.save(commit=False)

        line.document = document
        line.product = product
        line.uom = uom
        line.quantity = quantity
        line.unit_price = unit_price
        line.discount_percent = discount_percent
        line.description = description

        # لو عندك حقل ترتيب مثل line_number أو sort_order
        if hasattr(line, "line_number") and not line.line_number:
            line.line_number = line_index + 1
        if hasattr(line, "sort_order"):
            line.sort_order = line_index

        # created_by / updated_by لو موجودة في BaseModel
        if not line.pk and hasattr(line, "created_by_id") and not line.created_by_id:
            line.created_by = user
        if hasattr(line, "updated_by"):
            line.updated_by = user

        line.save()
        form.instance = line  # خله متزامن مع الفورم
        kept_ids.add(line.id)
        line_index += 1

    # 5) حذف أي أسطر كانت موجودة في الداتا بيس ولم ترجع من الفورم
    to_delete_ids = existing_ids - kept_ids
    if to_delete_ids:
        SalesLine.objects.filter(document=document, id__in=to_delete_ids).delete()

    # 6) تأكد أن في الأقل سطر واحد
    if line_index == 0:
        raise ValidationError(_("يجب إضافة سطر واحد على الأقل للمستند."))




def initial_lines_from_post(post_data):
    """
    تُستخدم لإعادة بناء بنود المبيعات من POST في حالة:
    - form_invalid في الإنشاء.
    - form_invalid في التعديل.

    ترجع قائمة عناصر فيها نفس الأسماء التي يتوقعها القالب:
    - pk
    - product
    - product_id
    - uom_id
    - quantity
    - unit_price
    - discount_percent
    - description
    - line_total  (اختياري / مبدئي)
    """

    total_forms_raw = post_data.get("lines-TOTAL_FORMS", "0") or "0"
    try:
        total_forms = int(total_forms_raw)
    except ValueError:
        total_forms = 0

    lines = []

    for i in range(total_forms):
        prefix = f"lines-{i}-"

        line_id = post_data.get(prefix + "id") or None
        product_id = post_data.get(prefix + "product") or None
        uom_id = (
            post_data.get(prefix + "uom")
            or post_data.get(prefix + "uom_select")
            or None
        )
        description = post_data.get(prefix + "description") or ""
        quantity_raw = post_data.get(prefix + "quantity") or ""
        unit_price_raw = post_data.get(prefix + "unit_price") or ""
        discount_raw = post_data.get(prefix + "discount_percent") or ""
        delete_flag = post_data.get(prefix + "DELETE")

        # لو السطر كله فاضي وما فيه أي قيمة حقيقية → نتجاهله
        if not any([
            line_id,
            product_id,
            description.strip(),
            quantity_raw.strip(),
            unit_price_raw.strip(),
            discount_raw.strip(),
        ]):
            continue

        # نحاول نحول الكمية والسعر والخصم لأرقام (لو حاب تستخدمها للحساب)
        def _to_decimal(val, default="0"):
            val = (val or "").strip()
            if not val:
                return Decimal(default)
            try:
                return Decimal(val)
            except Exception:
                return Decimal(default)

        quantity = _to_decimal(quantity_raw, "0")
        unit_price = _to_decimal(unit_price_raw, "0")
        discount_percent = _to_decimal(discount_raw, "0")

        # نحسب إجمالي السطر مبدئيًا (للعرض فقط، مو شرط)
        line_total = quantity * unit_price
        if discount_percent > 0:
            line_total = line_total * (Decimal("100") - discount_percent) / Decimal("100")

        product = None
        if product_id:
            try:
                product = Product.objects.get(pk=product_id)
            except Product.DoesNotExist:
                product = None

        # نبني عنصر بسيط بنفس شكل الـ object اللي في حالة الـ GET
        line_obj = SimpleNamespace(
            pk=line_id,
            product=product,
            product_id=product_id,
            uom_id=uom_id,
            quantity=quantity,              # ← مهم
            unit_price=unit_price,          # ← مهم
            discount_percent=discount_percent,
            description=description,
            line_total=line_total,
        )

        lines.append(line_obj)

    return lines