# sales/services.py
from decimal import Decimal
from typing import Any, Mapping, Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import Notification, AuditLog
from core.services.audit import log_event
from core.services.notifications import create_notification
from .models import SalesDocument, DeliveryNote, DeliveryLine


class SalesService:
    """
    خدمة مركزية لإدارة عمليات المبيعات المعقدة.
    تضمن هذه الخدمة سلامة البيانات باستخدام Database Transactions.
    """

    # ============================================================
    # 1) تأكيد مستند المبيعات (تحويله إلى أمر بيع)
    # ============================================================
    @staticmethod
    @transaction.atomic
    def confirm_document(
        document: SalesDocument,
        *,
        actor=None,  # user (اختياري)
    ) -> SalesDocument:
        """
        تأكيد مستند المبيعات.

        القواعد:
        - لا يمكن تأكيد مستند ملغي.
        - لا يمكن تأكيد مستند مؤكد مسبقاً.
        - لا يمكن تأكيد مستند بدون بنود.
        """
        document.refresh_from_db()

        # 1. التحقق من القواعد
        if document.status == SalesDocument.Status.CONFIRMED:
            raise ValidationError(_("المستند مؤكد بالفعل."))

        if document.status == SalesDocument.Status.CANCELLED:
            raise ValidationError(_("لا يمكن تأكيد مستند ملغي."))

        if not document.lines.exists():
            raise ValidationError(_("لا يمكن تأكيد مستند بدون أي بنود مبيعات."))

        # 2. تغيير الحالة إلى مؤكد
        document.status = SalesDocument.Status.CONFIRMED
        # document.date = timezone.localdate()  # لو حبيت تعدل التاريخ لليوم
        document.save(update_fields=["status", "updated_at"])

        # 3. تحديث المجاميع
        document.recompute_totals(save=True)

        # 4. Audit Log + (بدون نتفيكشن افتراضياً)
        log_sales_document_action(
            user=actor,
            document=document,
            action=AuditLog.Action.STATUS_CHANGE,
            message=_("تم تأكيد مستند المبيعات رقم %(number)s.") % {
                "number": document.display_number,
            },
            extra={
                "status": document.status,
                "total_amount": float(document.total_amount or 0),
            },
            notify=False,
        )

        return document

    # ============================================================
    # 2) إنشاء مذكرة تسليم من أمر بيع
    # ============================================================
    @staticmethod
    @transaction.atomic
    def create_delivery_note(
            order: SalesDocument,
            lines_data: list | None = None,
            *,
            actor=None,  # user (اختياري)
    ) -> DeliveryNote:
        """
        إنشاء مذكرة تسليم بناءً على أمر بيع مؤكد.

        :param order: مستند مبيعات بحالة CONFIRMED
        :param lines_data: قائمة اختيارية من الدكت للتسليم الجزئي:
            [{"sales_line_id": 123, "quantity": "5.000"}, ...]
        """
        # 1. التحقق: نعتمد على الحالة
        if order.status != SalesDocument.Status.CONFIRMED:
            raise ValidationError(
                _("يجب أن يكون المستند أمر بيع مؤكد لإنشاء مذكرة تسليم.")
            )

        # 2. إنشاء "هيدر" مذكرة التسليم
        delivery = DeliveryNote.objects.create(
            contact=order.contact,
            order=order,
            date=timezone.localdate(),
            status=DeliveryNote.Status.DRAFT,
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
        )

        # --- تحسين الأداء (Optimization) ---
        # نحول القائمة إلى قاموس (Dictionary) لتسريع البحث من O(N) إلى O(1)
        # المفتاح هو ID السطر (كنص لضمان التوافق)
        lines_map = {}
        if lines_data:
            for item in lines_data:
                sid = str(item.get("sales_line_id", ""))
                if sid:
                    lines_map[sid] = item
        # -----------------------------------

        # 3. معالجة البنود
        items_created = 0
        order_lines = order.lines.all()

        for line in order_lines:
            remaining = line.remaining_quantity

            # تخطي الأسطر المكتملة (التي رصيدها صفر)
            if remaining <= 0:
                continue

            qty_to_deliver = remaining

            # دعم التسليم الجزئي المخصص (إذا تم تمرير lines_data)
            if lines_data is not None:
                # نبحث في الـ Map بدلاً من البحث في القائمة
                target_data = lines_map.get(str(line.id))

                if not target_data:
                    # هذا السطر لم يتم اختياره من قبل المستخدم، لذا نتخطاه
                    continue

                try:
                    qty_to_deliver = Decimal(str(target_data["quantity"]))
                except (KeyError, ValueError, TypeError):
                    raise ValidationError(
                        _(
                            "كمية غير صالحة للبند المرتبط بالمنتج %(product)s."
                        )
                        % {"product": line.product or line.description}
                    )

            # التحقق من تجاوز الكمية المتبقية
            if qty_to_deliver > remaining:
                raise ValidationError(
                    _(
                        "الكمية المراد تسليمها للمنتج %(product)s (%(qty)s) "
                        "تتجاوز الكمية المتبقية (%(rem)s)."
                    )
                    % {
                        "product": line.product or line.description,
                        "qty": qty_to_deliver,
                        "rem": remaining
                    }
                )

            # إنشاء بند التسليم
            if qty_to_deliver > 0:
                DeliveryLine.objects.create(
                    delivery=delivery,
                    sales_line=line,
                    product=line.product,
                    description=line.description,
                    uom=line.uom,
                    quantity=qty_to_deliver,
                )
                items_created += 1

        # التحقق النهائي: هل تم إنشاء أي بنود؟
        if items_created == 0:
            # لا يوجد ما يُسلّم فعليًا، احذف المسودة لتجنب وجود مستندات فارغة
            delivery.delete()
            msg = _("لم يتم إنشاء مذكرة تسليم.")
            if lines_data:
                msg += _(" لم يتم اختيار أي بنود، أو الكميات المدخلة غير صحيحة.")
            else:
                msg += _(" جميع الكميات في هذا الأمر تم تسليمها بالفعل.")
            raise ValidationError(msg)

        # 4. Audit Log
        log_delivery_note_action(
            user=actor,
            delivery=delivery,
            action=AuditLog.Action.CREATE,
            message=_(
                "تم إنشاء مذكرة تسليم من أمر البيع رقم %(number)s."
            ) % {"number": order.display_number},
            extra={
                "order_id": order.pk,
                "order_number": order.display_number,
            },
            notify=False,
        )

        return delivery

    # ============================================================
    # 3) تأكيد مذكرة التسليم
    # ============================================================
    @staticmethod
    @transaction.atomic
    def confirm_delivery(
        delivery: DeliveryNote,
        *,
        actor=None,  # user (اختياري)
    ) -> DeliveryNote:
        """
        تأكيد مذكرة التسليم:
        1. تغيير الحالة إلى CONFIRMED.
        2. خصم المخزون (لاحقاً عبر InventoryService).
        3. تحديث حالة أمر البيع (إذا وجد) عبر recompute_delivery_status.
        """
        delivery.refresh_from_db()

        if delivery.status == DeliveryNote.Status.CONFIRMED:
            raise ValidationError(_("مذكرة التسليم مؤكدة بالفعل."))

        if delivery.status == DeliveryNote.Status.CANCELLED:
            raise ValidationError(_("لا يمكن تأكيد مذكرة تسليم ملغاة."))

        if not delivery.lines.exists():
            raise ValidationError(_("لا يمكن تأكيد مذكرة تسليم بدون أي بنود."))

        # 1. تغيير الحالة
        delivery.status = DeliveryNote.Status.CONFIRMED
        delivery.clean()  # التحقق من الربط بأمر إلخ.
        delivery.save(update_fields=["status", "updated_at"])

        # 2. خصم المخزون (placeholder)
        # TODO: استدعاء InventoryService لخصم الكميات هنا

        # 3. تحديث حالة أمر البيع (فقط إذا كان التسليم مرتبطاً بأمر)
        if delivery.order:
            delivery.order.recompute_delivery_status(save=True)

        # 4. Audit Log لمذكرة التسليم
        log_delivery_note_action(
            user=actor,
            delivery=delivery,
            action=AuditLog.Action.STATUS_CHANGE,
            message=_("تم تأكيد مذكرة التسليم رقم %(number)s.") % {
                "number": delivery.display_number,
            },
            extra={
                "status": delivery.status,
                "order_id": delivery.order_id,
            },
            notify=False,
        )

        # 5. (اختياري) لوج لأمر البيع من ناحية حالة التسليم
        if delivery.order:
            log_sales_document_action(
                user=actor,
                document=delivery.order,
                action=AuditLog.Action.STATUS_CHANGE,
                message=_(
                    "تم تحديث حالة التسليم لأمر البيع رقم %(number)s."
                )
                % {"number": delivery.order.display_number},
                extra={
                    "delivery_status": delivery.order.delivery_status,
                },
                notify=False,
            )

        return delivery

    # ============================================================
    # 4) إلغاء أمر البيع
    # ============================================================
    @staticmethod
    @transaction.atomic
    def cancel_order(
        document: SalesDocument,
        *,
        actor=None,  # user (اختياري)
    ) -> SalesDocument:
        """
        إلغاء المستند (مع التحقق من عدم وجود تسليمات مؤكدة).
        يعتمد على clean() في الموديل أيضاً.
        """
        document.refresh_from_db()

        if document.status == SalesDocument.Status.CANCELLED:
            raise ValidationError(_("المستند ملغى بالفعل."))

        # التحقق موجود في الموديل (clean)
        document.clean()

        document.status = SalesDocument.Status.CANCELLED
        document.save(update_fields=["status", "updated_at"])

        # Audit Log
        log_sales_document_action(
            user=actor,
            document=document,
            action=AuditLog.Action.STATUS_CHANGE,
            message=_("تم إلغاء مستند المبيعات رقم %(number)s.") % {
                "number": document.display_number,
            },
            extra={"status": document.status},
            notify=False,
        )

        return document

    # ============================================================
    # 5) استعادة مستند ملغي
    # ============================================================
    @staticmethod
    @transaction.atomic
    def restore_document(
        document: SalesDocument,
        *,
        actor=None,  # user (اختياري)
    ) -> SalesDocument:
        """
        استعادة المستند الملغي وتحويله إلى مسودة.
        """
        document.refresh_from_db()

        if document.status != SalesDocument.Status.CANCELLED:
            raise ValidationError(_("المستند ليس في حالة إلغاء ليتم استعادته."))

        document.status = SalesDocument.Status.DRAFT
        document.save(update_fields=["status", "updated_at"])

        # Audit Log
        log_sales_document_action(
            user=actor,
            document=document,
            action=AuditLog.Action.STATUS_CHANGE,
            message=_("تم استعادة مستند المبيعات رقم %(number)s.") % {
                "number": document.display_number,
            },
            extra={"status": document.status},
            notify=False,
        )

        return document


# ============================================================
# 1) لوج لمستندات المبيعات
# ============================================================

def log_sales_document_action(
    *,
    user,                    # actor (يمكن أن يكون None)
    document,                # SalesDocument instance
    action: str | AuditLog.Action,
    message: str = "",
    extra: Optional[Mapping[str, Any]] = None,
    notify: bool = False,
    notify_recipient=None,   # لو حاب ترسلها لشخص آخر (مثلاً created_by)
) -> None:
    """
    نقطة مركزية لتسجيل أحداث مستندات المبيعات في AuditLog
    + (اختياري) إنشاء Notification.

    action:
      - استخدم AuditLog.Action.CREATE / UPDATE / STATUS_CHANGE / DELETE / OTHER
        أو string بنفس القيم الموجودة في choices.
    """

    # --- 1) AuditLog ---
    log_event(
        action=action,
        message=message,
        actor=user,
        target=document,
        extra=extra,
    )

    # --- 2) Notification (اختياري) ---
    if notify:
        recipient = notify_recipient or getattr(document, "created_by", None) or user

        if recipient is not None:
            verb = message or _(
                "تم تحديث مستند المبيعات رقم %(number)s."
            ) % {"number": document.display_number}

            # رابط تفصيلي للمستند
            try:
                url = reverse("sales:document_detail", args=[document.pk])
            except Exception:
                url = ""

            create_notification(
                recipient=recipient,
                verb=verb,
                target=document,
                level=Notification.Levels.INFO,
                url=url,
            )


# ============================================================
# 2) لوج لمذكرات التسليم
# ============================================================

def log_delivery_note_action(
    *,
    user,
    delivery,                # DeliveryNote instance
    action: str | AuditLog.Action,
    message: str = "",
    extra: Optional[Mapping[str, Any]] = None,
    notify: bool = False,
    notify_recipient=None,
) -> None:
    """
    تسجيل أحداث مذكرات التسليم في AuditLog + (اختياري) نتفيكشن.
    """

    # --- 1) AuditLog ---
    log_event(
        action=action,
        message=message,
        actor=user,
        target=delivery,
        extra=extra,
    )

    # --- 2) Notification (اختياري) ---
    if notify:
        recipient = notify_recipient or getattr(delivery, "created_by", None) or user

        if recipient is not None:
            verb = message or _(
                "تم تحديث مذكرة التسليم رقم %(number)s."
            ) % {"number": delivery.display_number}

            try:
                url = reverse("sales:delivery_detail", args=[delivery.pk])
            except Exception:
                url = ""

            create_notification(
                recipient=recipient,
                verb=verb,
                target=delivery,
                level=Notification.Levels.INFO,
                url=url,
            )
