# sales/services.py
from decimal import Decimal

from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

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
    def confirm_document(document: SalesDocument) -> SalesDocument:
        """
        تأكيد عرض السعر وتحويله إلى أمر بيع (بتغيير الحالة فقط).

        القواعد:
        - لا يمكن تأكيد مستند ملغي.
        - لا يمكن تأكيد مستند مؤكد مسبقاً.
        - لا يمكن تأكيد مستند بدون بنود.
        """
        # إعادة تحميل من الداتابيز (اختياري، لكن آمن لو مرّ كائن قديم)
        document.refresh_from_db()

        # 1. التحقق من القواعد
        if document.status == SalesDocument.Status.CONFIRMED:
            raise ValidationError(_("المستند مؤكد بالفعل."))

        if document.status == SalesDocument.Status.CANCELLED:
            raise ValidationError(_("لا يمكن تأكيد مستند ملغي."))

        if not document.lines.exists():
            raise ValidationError(_("لا يمكن تأكيد مستند بدون أي بنود مبيعات."))

        # 2. تغيير الحالة إلى مؤكد (يصبح أمر بيع)
        document.status = SalesDocument.Status.CONFIRMED

        # ملاحظة: يمكن تفعيل هذا إن حبيت تغيير تاريخ الأمر إلى اليوم
        # document.date = timezone.localdate()

        document.save(update_fields=["status", "updated_at"])

        # تحديث المجاميع فقط للاحتياط
        document.recompute_totals(save=True)

        return document

    # ============================================================
    # 2) إنشاء مذكرة تسليم من أمر بيع
    # ============================================================
    @staticmethod
    @transaction.atomic
    def create_delivery_note(
        order: SalesDocument,
        lines_data: list | None = None,
    ) -> DeliveryNote:
        """
        إنشاء مذكرة تسليم بناءً على أمر بيع مؤكد.

        :param order: مستند مبيعات بحالة CONFIRMED
        :param lines_data: قائمة اختيارية من الدكت:
            [
              {"sales_line_id": 123, "quantity": "5.000"},
              ...
            ]
            إذا لم تُمرَّر، سيتم إنشاء تسليم لكل الكميات المتبقية بالكامل.
        """
        # 1. التحقق
        if not order.is_order:
            raise ValidationError(
                _("يجب أن يكون المستند أمر بيع مؤكد لإنشاء مذكرة تسليم.")
            )

        # 2. إنشاء "هيدر" مذكرة التسليم
        delivery = DeliveryNote.objects.create(
            contact=order.contact,
            order=order,
            date=timezone.localdate(),
            status=DeliveryNote.Status.DRAFT,
        )

        # 3. معالجة البنود
        items_created = 0
        order_lines = order.lines.all()

        for line in order_lines:
            remaining = line.remaining_quantity

            # تخطي الأسطر المكتملة
            if remaining <= 0:
                continue

            qty_to_deliver = remaining

            # دعم التسليم الجزئي المخصص (إذا تم تمرير lines_data)
            if lines_data:
                target_data = next(
                    (item for item in lines_data if item["sales_line_id"] == line.id),
                    None,
                )
                if not target_data:
                    # هذا السطر لم يتم اختياره للتسليم
                    continue

                try:
                    qty_to_deliver = Decimal(target_data["quantity"])
                except (KeyError, ValueError, TypeError):
                    raise ValidationError(
                        _(
                            "كمية غير صالحة للبند المرتبط بالمنتج %(product)s."
                        )
                        % {"product": line.product or line.description}
                    )

            if qty_to_deliver > remaining:
                raise ValidationError(
                    _(
                        "الكمية المراد تسليمها للمنتج %(product)s "
                        "تتجاوز الكمية المتبقية في أمر البيع."
                    )
                    % {"product": line.product or line.description}
                )

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

        if items_created == 0:
            # لا يوجد ما يُسلّم فعليًا، احذف المسودة
            delivery.delete()
            raise ValidationError(
                _(
                    "لم يتم إنشاء مذكرة تسليم لأن جميع الكميات قد تم تسليمها بالفعل "
                    "أو لم يتم اختيار أي بنود للتسليم."
                )
            )

        return delivery

    # ============================================================
    # 3) تأكيد مذكرة التسليم
    # ============================================================
    @staticmethod
    @transaction.atomic
    def confirm_delivery(delivery: DeliveryNote) -> DeliveryNote:
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
        # clean() في الموديل سيتأكد من عدم الارتباط بأمر ملغي، إلخ.
        delivery.clean()
        delivery.save(update_fields=["status", "updated_at"])

        # 2. خصم المخزون (placeholder)
        # TODO: استدعاء InventoryService لخصم الكميات هنا، مثال:
        # InventoryService.decrease_stock_for_delivery(delivery)

        # 3. تحديث حالة أمر البيع (فقط إذا كان التسليم مرتبطاً بأمر)
        if delivery.order:
            delivery.order.recompute_delivery_status(save=True)

        return delivery

    # ============================================================
    # 4) إلغاء أمر البيع
    # ============================================================
    @staticmethod
    @transaction.atomic
    def cancel_order(document: SalesDocument) -> SalesDocument:
        """
        إلغاء المستند (مع التحقق من عدم وجود تسليمات مؤكدة).
        يعتمد على clean() في الموديل أيضاً.
        """
        document.refresh_from_db()

        if document.status == SalesDocument.Status.CANCELLED:
            # يعتبر إلغاءً صامتاً؛ أو يمكنك رفع خطأ لو تحب
            raise ValidationError(_("المستند ملغى بالفعل."))

        # التحقق موجود في الموديل (clean) - سيمنع الإلغاء في حال وجود تسليمات مؤكدة
        document.clean()

        document.status = SalesDocument.Status.CANCELLED
        document.save(update_fields=["status", "updated_at"])

        return document

    # ============================================================
    # 5) استعادة مستند ملغي
    # ============================================================
    @staticmethod
    @transaction.atomic
    def restore_document(document: SalesDocument) -> SalesDocument:
        """
        استعادة المستند الملغي وتحويله إلى مسودة.
        """
        document.refresh_from_db()

        if document.status != SalesDocument.Status.CANCELLED:
            raise ValidationError(_("المستند ليس في حالة إلغاء ليتم استعادته."))

        document.status = SalesDocument.Status.DRAFT
        document.save(update_fields=["status", "updated_at"])

        return document
