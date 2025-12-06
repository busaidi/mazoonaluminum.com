# sales/managers.py
from django.db import models
from django.db.models import Q
import datetime

# تأكد من استيراد الموديلات بشكل صحيح لتجنب Circular Import إذا لزم الأمر
# ولكن بما أننا نمرر الكائنات كـ arguments، فالأمر آمن غالباً.
from contacts.models import Contact
from inventory.models import Product


# ===================================================================
# QuerySet و Manager لمستندات المبيعات
# ===================================================================

class SalesDocumentQuerySet(models.QuerySet):
    """
    QuerySet مخصص لمستندات المبيعات.
    """

    # -------- soft delete --------
    def alive(self):
        return self.filter(is_deleted=False)

    def deleted(self):
        return self.filter(is_deleted=True)

    def with_deleted(self):
        return self.all()

    # -------- النوع --------
    def quotations(self):
        return self.alive().filter(kind="quotation")

    def orders(self):
        return self.alive().filter(kind="order")

    # -------- الحالة العامة --------
    def drafts(self):
        return self.alive().filter(status="draft")

    def confirmed(self):
        return self.alive().filter(status="confirmed")

    def cancelled(self):
        return self.alive().filter(status="cancelled")

    # -------- حالة التسليم (جديد) --------
    def pending_delivery(self):
        """الطلبات التي لم يتم تسليمها أو تم تسليمها جزئياً"""
        return self.alive().filter(kind="order", delivery_status__in=["pending", "partial"])

    def fully_delivered(self):
        return self.alive().filter(kind="order", delivery_status="delivered")

    # -------- الفوترة --------
    def invoiced(self):
        return self.alive().filter(is_invoiced=True)

    def not_invoiced(self):
        return self.alive().filter(is_invoiced=False)

    # -------- التواريخ (جديد) --------
    def date_range(self, start_date, end_date):
        """فلترة المستندات ضمن نطاق زمني معين"""
        if start_date and end_date:
            return self.alive().filter(date__range=(start_date, end_date))
        return self.alive()

    # -------- العملاء والبحث --------
    def for_contact(self, contact):
        contact_id = contact.pk if hasattr(contact, "pk") else contact
        return self.alive().filter(contact_id=contact_id)

    def search(self, query):
        """
        بحث شامل: ID, اسم العميل, هاتف, المرجع
        """
        if not query:
            return self

        lookup = (
                Q(contact__name__icontains=query) |
                Q(contact__phone__icontains=query) |
                Q(client_reference__icontains=query) |
                Q(display_number__icontains=query)  # إذا كنت تحفظ رقم العرض في قاعدة البيانات
        )

        if str(query).isdigit():
            lookup |= Q(pk=query)

        return self.alive().filter(lookup)


class SalesDocumentManager(models.Manager):
    def _base_queryset(self):
        return SalesDocumentQuerySet(self.model, using=self._db)

    def get_queryset(self):
        return self._base_queryset().alive()

    # تمرير الميثودات من QuerySet إلى Manager
    def with_deleted(self): return self._base_queryset().with_deleted()

    def quotations(self): return self.get_queryset().quotations()

    def orders(self): return self.get_queryset().orders()

    def drafts(self): return self.get_queryset().drafts()

    def confirmed(self): return self.get_queryset().confirmed()

    def cancelled(self): return self.get_queryset().cancelled()

    # الجديدة
    def pending_delivery(self): return self.get_queryset().pending_delivery()

    def fully_delivered(self): return self.get_queryset().fully_delivered()

    def date_range(self, start, end): return self.get_queryset().date_range(start, end)

    def invoiced(self): return self.get_queryset().invoiced()

    def not_invoiced(self): return self.get_queryset().not_invoiced()

    def for_contact(self, contact): return self.get_queryset().for_contact(contact)

    def search(self, query): return self.get_queryset().search(query)


# ===================================================================
# QuerySet و Manager لبنود المبيعات
# ===================================================================

class SalesLineQuerySet(models.QuerySet):
    def for_document(self, document):
        doc_id = document.pk if hasattr(document, "pk") else document
        return self.filter(document_id=doc_id)

    def for_product(self, product):
        product_id = product.pk if hasattr(product, "pk") else product
        return self.filter(product_id=product_id)

    def for_contact(self, contact):
        contact_id = contact.pk if hasattr(contact, "pk") else contact
        return self.filter(document__contact_id=contact_id)

    def quotations(self): return self.filter(document__kind="quotation")

    def orders(self): return self.filter(document__kind="order")


class SalesLineManager(models.Manager):
    def get_queryset(self): return SalesLineQuerySet(self.model, using=self._db)

    def for_document(self, doc): return self.get_queryset().for_document(doc)

    def for_product(self, prod): return self.get_queryset().for_product(prod)

    def for_contact(self, cont): return self.get_queryset().for_contact(cont)

    def quotations(self): return self.get_queryset().quotations()

    def orders(self): return self.get_queryset().orders()


# ===================================================================
# QuerySet و Manager لمذكرات التسليم
# ===================================================================

class DeliveryNoteQuerySet(models.QuerySet):
    # -------- soft delete --------
    def alive(self): return self.filter(is_deleted=False)

    def deleted(self): return self.filter(is_deleted=True)

    def with_deleted(self): return self.all()

    # -------- الحالة --------
    def drafts(self): return self.alive().filter(status="draft")

    def confirmed(self): return self.alive().filter(status="confirmed")

    def cancelled(self): return self.alive().filter(status="cancelled")

    # -------- بحسب العميل / الأمر --------
    def for_order(self, order):
        order_id = order.pk if hasattr(order, "pk") else order
        return self.alive().filter(order_id=order_id)

    def for_contact(self, contact):
        contact_id = contact.pk if hasattr(contact, "pk") else contact
        # بحث ذكي: في المذكرة مباشرة أو في الأمر المرتبط
        return self.alive().filter(
            Q(contact_id=contact_id) | Q(order__contact_id=contact_id)
        )


class DeliveryNoteManager(models.Manager):
    def _base_queryset(self): return DeliveryNoteQuerySet(self.model, using=self._db)

    def get_queryset(self): return self._base_queryset().alive()

    def with_deleted(self): return self._base_queryset().with_deleted()

    def drafts(self): return self.get_queryset().drafts()

    def confirmed(self): return self.get_queryset().confirmed()

    def cancelled(self): return self.get_queryset().cancelled()

    def for_order(self, order): return self.get_queryset().for_order(order)

    def for_contact(self, contact): return self.get_queryset().for_contact(contact)


# ===================================================================
# QuerySet و Manager لبنود التسليم
# ===================================================================

class DeliveryLineQuerySet(models.QuerySet):
    def for_delivery(self, delivery):
        delivery_id = delivery.pk if hasattr(delivery, "pk") else delivery
        return self.filter(delivery_id=delivery_id)

    def for_product(self, product):
        product_id = product.pk if hasattr(product, "pk") else product
        return self.filter(product_id=product_id)

    def for_contact(self, contact):
        contact_id = contact.pk if hasattr(contact, "pk") else contact
        return self.filter(
            Q(delivery__contact_id=contact_id) | Q(delivery__order__contact_id=contact_id)
        )


class DeliveryLineManager(models.Manager):
    def get_queryset(self): return DeliveryLineQuerySet(self.model, using=self._db)

    def for_delivery(self, delivery): return self.get_queryset().for_delivery(delivery)

    def for_product(self, product): return self.get_queryset().for_product(product)

    def for_contact(self, contact): return self.get_queryset().for_contact(contact)