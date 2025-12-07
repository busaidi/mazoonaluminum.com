# sales/managers.py
from django.db import models
from django.db.models import Q


# ===================================================================
# QuerySet و Manager لمستندات المبيعات
# ===================================================================

class SalesDocumentQuerySet(models.QuerySet):
    """
    QuerySet مخصص لمستندات المبيعات.
    """

    # -------- soft delete (تأكد أن is_deleted موجود في BaseModel) --------
    def alive(self):
        """
        يرجع فقط المستندات غير المحذوفة (منطقياً) إذا كان is_deleted موجوداً.
        """
        return self.filter(is_deleted=False) if hasattr(self.model, "is_deleted") else self

    def deleted(self):
        return self.filter(is_deleted=True) if hasattr(self.model, "is_deleted") else self.none()

    # -------- النوع (مبني على الحالة) --------
    def quotations(self):
        """
        عروض الأسعار: المستندات في حالة المسودة أو المرسلة.
        نستخدم Status enums من الموديل لتفادي تكرار النصوص.
        """
        return self.alive().filter(
            status__in=[
                self.model.Status.DRAFT,
                self.model.Status.SENT,
            ]
        )

    def orders(self):
        """
        أوامر البيع: المستندات المؤكدة فقط.
        """
        return self.alive().filter(status=self.model.Status.CONFIRMED)

    # -------- الحالة العامة --------
    def drafts(self):
        return self.alive().filter(status=self.model.Status.DRAFT)

    def confirmed(self):
        return self.alive().filter(status=self.model.Status.CONFIRMED)

    def cancelled(self):
        return self.alive().filter(status=self.model.Status.CANCELLED)

    # -------- حالة التسليم --------
    def pending_delivery(self):
        """
        الطلبات (المؤكدة) التي لم يتم تسليمها أو تم تسليمها جزئياً.
        """
        return self.alive().filter(
            status=self.model.Status.CONFIRMED,
            delivery_status__in=[
                self.model.DeliveryStatus.PENDING,
                self.model.DeliveryStatus.PARTIAL,
            ],
        )

    def fully_delivered(self):
        """
        الطلبات (المؤكدة) التي تم تسليمها بالكامل.
        """
        return self.alive().filter(
            status=self.model.Status.CONFIRMED,
            delivery_status=self.model.DeliveryStatus.DELIVERED,
        )

    # -------- الفوترة --------
    def invoiced(self):
        return self.alive().filter(is_invoiced=True)

    def not_invoiced(self):
        return self.alive().filter(is_invoiced=False)

    # -------- التواريخ --------
    def date_range(self, start_date, end_date):
        if start_date and end_date:
            return self.alive().filter(date__range=(start_date, end_date))
        return self.alive()

    # -------- العملاء والبحث --------
    def for_contact(self, contact):
        """
        ترشيح المستندات لعميل معيّن (object أو id).
        """
        contact_id = contact.pk if hasattr(contact, "pk") else contact
        return self.alive().filter(contact_id=contact_id)

    def search(self, query):
        """
        بحث شامل: اسم العميل، الهاتف، مرجع العميل، و ID المستند إذا كان الإدخال رقمياً.
        """
        if not query:
            return self

        lookup = (
            Q(contact__name__icontains=query)
            | Q(contact__phone__icontains=query)
            | Q(client_reference__icontains=query)
            # display_number هو property وليس حقلاً في DB، لذلك لا يمكن البحث به هنا
        )

        # إذا كان البحث رقمياً، نبحث في الـ ID
        # هذا يغطي البحث برقم الطلب (مثلاً المستخدم كتب 50 للبحث عن SO-0050)
        if str(query).isdigit():
            lookup |= Q(pk=query)

        return self.alive().filter(lookup)


class SalesDocumentManager(models.Manager):
    def _base_queryset(self):
        return SalesDocumentQuerySet(self.model, using=self._db)

    def get_queryset(self):
        # بشكل افتراضي نرجّع الـ alive فقط (غير المحذوفة منطقياً)
        return self._base_queryset().alive()

    # Proxy methods ترتاح في الاستخدام في Views و Services
    def quotations(self):
        return self.get_queryset().quotations()

    def orders(self):
        return self.get_queryset().orders()

    def drafts(self):
        return self.get_queryset().drafts()

    def confirmed(self):
        return self.get_queryset().confirmed()

    def cancelled(self):
        return self.get_queryset().cancelled()

    def pending_delivery(self):
        return self.get_queryset().pending_delivery()

    def fully_delivered(self):
        return self.get_queryset().fully_delivered()

    def invoiced(self):
        return self.get_queryset().invoiced()

    def not_invoiced(self):
        return self.get_queryset().not_invoiced()

    def date_range(self, start, end):
        return self.get_queryset().date_range(start, end)

    def for_contact(self, contact):
        return self.get_queryset().for_contact(contact)

    def search(self, query):
        return self.get_queryset().search(query)


# ===================================================================
# QuerySet و Manager لبنود المبيعات
# ===================================================================

class SalesLineQuerySet(models.QuerySet):
    def for_document(self, document):
        """
        ترشيح البنود لمستند معيّن (object أو id).
        """
        doc_id = document.pk if hasattr(document, "pk") else document
        return self.filter(document_id=doc_id)

    def for_product(self, product):
        """
        ترشيح البنود لمنتج معيّن (object أو id).
        """
        product_id = product.pk if hasattr(product, "pk") else product
        return self.filter(product_id=product_id)

    def quotations(self):
        """
        بنود تنتمي لعروض أسعار (مسودة أو مرسلة).
        """
        return self.filter(
            document__status__in=[
                self.model.document.field.related_model.Status.DRAFT,
                self.model.document.field.related_model.Status.SENT,
            ]
        )

    def orders(self):
        """
        بنود تنتمي لأوامر بيع مؤكدة.
        """
        return self.filter(
            document__status=self.model.document.field.related_model.Status.CONFIRMED
        )


class SalesLineManager(models.Manager):
    def get_queryset(self):
        return SalesLineQuerySet(self.model, using=self._db)

    def for_document(self, doc):
        return self.get_queryset().for_document(doc)

    def for_product(self, prod):
        return self.get_queryset().for_product(prod)

    def quotations(self):
        return self.get_queryset().quotations()

    def orders(self):
        return self.get_queryset().orders()


# ===================================================================
# QuerySet و Manager لمذكرات التسليم
# ===================================================================

class DeliveryNoteQuerySet(models.QuerySet):
    def alive(self):
        """
        يرجع فقط المذكرات غير المحذوفة (منطقياً) إذا كان is_deleted موجوداً.
        """
        return self.filter(is_deleted=False) if hasattr(self.model, "is_deleted") else self

    def drafts(self):
        return self.alive().filter(status=self.model.Status.DRAFT)

    def confirmed(self):
        return self.alive().filter(status=self.model.Status.CONFIRMED)

    def cancelled(self):
        return self.alive().filter(status=self.model.Status.CANCELLED)

    def for_order(self, order):
        order_id = order.pk if hasattr(order, "pk") else order
        return self.alive().filter(order_id=order_id)

    def for_contact(self, contact):
        contact_id = contact.pk if hasattr(contact, "pk") else contact
        return self.alive().filter(
            Q(contact_id=contact_id) | Q(order__contact_id=contact_id)
        )


class DeliveryNoteManager(models.Manager):
    def _base_queryset(self):
        return DeliveryNoteQuerySet(self.model, using=self._db)

    def get_queryset(self):
        return self._base_queryset().alive()

    def drafts(self):
        return self.get_queryset().drafts()

    def confirmed(self):
        return self.get_queryset().confirmed()

    def cancelled(self):
        return self.get_queryset().cancelled()

    def for_order(self, order):
        return self.get_queryset().for_order(order)

    def for_contact(self, contact):
        return self.get_queryset().for_contact(contact)


# ===================================================================
# Delivery Line Manager
# ===================================================================

class DeliveryLineQuerySet(models.QuerySet):
    def for_delivery(self, delivery):
        delivery_id = delivery.pk if hasattr(delivery, "pk") else delivery
        return self.filter(delivery_id=delivery_id)


class DeliveryLineManager(models.Manager):
    def get_queryset(self):
        return DeliveryLineQuerySet(self.model, using=self._db)

    def for_delivery(self, delivery):
        return self.get_queryset().for_delivery(delivery)
