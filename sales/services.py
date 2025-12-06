# sales/services.py
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import SalesDocument, DeliveryNote, DeliveryLine


class SalesService:
    """
    خدمة مركزية لإدارة عمليات المبيعات المعقدة.
    تضمن هذه الخدمة سلامة البيانات باستخدام Database Transactions.
    """

    @staticmethod
    @transaction.atomic
    def confirm_document(document: SalesDocument) -> SalesDocument:
        """
        تأكيد عرض السعر وتحويله إلى أمر بيع (بتغيير الحالة فقط).
        """
        # 1. التحقق من القواعد
        if document.status == SalesDocument.Status.CONFIRMED:
            raise ValidationError("المستند مؤكد بالفعل.")

        if document.status == SalesDocument.Status.CANCELLED:
            raise ValidationError("لا يمكن تأكيد مستند ملغي.")

        # 2. تغيير الحالة إلى مؤكد (يصبح أمر بيع)
        document.status = SalesDocument.Status.CONFIRMED

        # نحدث تاريخ الأمر إلى اليوم إذا كان لا يزال مسودة قديمة
        # (اختياري: يعتمد على سياسة الشركة، البعض يفضل الاحتفاظ بتاريخ العرض)
        # document.date = timezone.now().date()

        document.save(update_fields=['status', 'updated_at'])

        # TODO: يمكن هنا إضافة منطق لحجز الكميات مبدئياً (Soft Reservation)

        return document

    @staticmethod
    @transaction.atomic
    def create_delivery_note(order: SalesDocument, lines_data: list = None) -> DeliveryNote:
        """
        إنشاء مذكرة تسليم بناءً على أمر بيع مؤكد.
        """
        # 1. التحقق
        if not order.is_order:
            raise ValidationError("يجب أن يكون المستند أمر بيع مؤكد لإنشاء تسليم.")

        # 2. إنشاء "هيدر" مذكرة التسليم
        delivery = DeliveryNote.objects.create(
            contact=order.contact,
            order=order,
            date=timezone.now().date(),
            status=DeliveryNote.Status.DRAFT
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
                target_data = next((item for item in lines_data if item['sales_line_id'] == line.id), None)
                if target_data:
                    qty_to_deliver = Decimal(target_data['quantity'])
                else:
                    continue  # لم يتم اختياره للتسليم

            if qty_to_deliver > remaining:
                raise ValidationError(f"الكمية المراد تسليمها للمنتج {line.product} تتجاوز المتبقي.")

            if qty_to_deliver > 0:
                DeliveryLine.objects.create(
                    delivery=delivery,
                    sales_line=line,
                    product=line.product,
                    description=line.description,
                    uom=line.uom,
                    quantity=qty_to_deliver
                )
                items_created += 1

        if items_created == 0:
            delivery.delete()
            raise ValidationError("لم يتم إنشاء مذكرة تسليم لأن جميع الكميات قد تم تسليمها بالفعل.")

        return delivery

    @staticmethod
    @transaction.atomic
    def confirm_delivery(delivery: DeliveryNote):
        """
        تأكيد مذكرة التسليم:
        1. تغيير الحالة.
        2. خصم المخزون.
        3. تحديث حالة الأمر (إذا وجد).
        """
        if delivery.status == DeliveryNote.Status.CONFIRMED:
            raise ValidationError("التسليم مؤكد بالفعل.")

        # 1. تغيير الحالة
        delivery.status = DeliveryNote.Status.CONFIRMED
        delivery.save()

        # 2. خصم المخزون (Placeholder)
        # TODO: استدعاء InventoryService لخصم الكميات هنا
        # مثال: InventoryService.decrease_stock(delivery)

        # 3. تحديث حالة أمر البيع (فقط إذا كان التسليم مرتبطاً بأمر)
        if delivery.order:
            SalesService._update_order_delivery_status(delivery.order)

        return delivery

    @staticmethod
    def _update_order_delivery_status(order: SalesDocument):
        """
        دالة مساعدة لحساب وتحديث حالة التسليم لأمر البيع
        """
        all_delivered = True
        any_delivered = False

        for line in order.lines.all():
            remaining = line.remaining_quantity
            delivered = line.delivered_quantity

            if delivered > 0:
                any_delivered = True

            if remaining > 0:
                all_delivered = False

        if all_delivered and any_delivered:
            order.delivery_status = SalesDocument.DeliveryStatus.DELIVERED
        elif any_delivered:
            order.delivery_status = SalesDocument.DeliveryStatus.PARTIAL
        else:
            order.delivery_status = SalesDocument.DeliveryStatus.PENDING

        order.save(update_fields=['delivery_status'])

    @staticmethod
    @transaction.atomic
    def cancel_order(document: SalesDocument):
        """
        إلغاء المستند (مع التحقق من عدم وجود تسليمات)
        """
        # التحقق موجود في الموديل (clean)، لكن نعيد التأكيد هنا للأمان
        document.clean()

        document.status = SalesDocument.Status.CANCELLED
        document.save()

    @staticmethod
    @transaction.atomic
    def restore_document(document: SalesDocument):
        """
        استعادة المستند الملغي وتحويله إلى مسودة.
        """
        if document.status != SalesDocument.Status.CANCELLED:
            raise ValidationError("المستند ليس في حالة إلغاء ليتم استعادته.")

        document.status = SalesDocument.Status.DRAFT
        document.save(update_fields=['status', 'updated_at'])

        return document