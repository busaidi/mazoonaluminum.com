# sales/managers.py
from django.db import models
from django.db.models import Q

from contacts.models import Contact
from inventory.models import Product


# ===================================================================
# QuerySet و Manager لمستندات المبيعات
# ===================================================================


class SalesDocumentQuerySet(models.QuerySet):
    """
    QuerySet مخصص لمستندات المبيعات:
    - دعم soft delete (is_deleted)
    - فلاتر حسب النوع (عرض سعر / أمر بيع)
    - فلاتر حسب الحالة والفوترة
    """

    # -------- soft delete --------

    def alive(self):
        return self.filter(is_deleted=False)

    def deleted(self):
        return self.filter(is_deleted=True)

    def with_deleted(self):
        return self.all()

    # -------- النوع: عرض / أمر --------

    def quotations(self):
        return self.alive().filter(kind="quotation")

    def orders(self):
        return self.alive().filter(kind="order")

    # -------- الحالة: مسودة / مؤكد / ملغي --------

    def drafts(self):
        return self.alive().filter(status="draft")

    def confirmed(self):
        return self.alive().filter(status="confirmed")

    def cancelled(self):
        return self.alive().filter(status="cancelled")

    # -------- الفوترة --------

    def invoiced(self):
        return self.alive().filter(is_invoiced=True)

    def not_invoiced(self):
        return self.alive().filter(is_invoiced=False)

    # -------- بحسب جهة الاتصال --------

    def for_contact(self, contact: Contact | int):
        contact_id = contact.pk if isinstance(contact, Contact) else contact
        return self.alive().filter(contact_id=contact_id)

    def search(self, query):
        """
        بحث شامل في المستندات:
        - رقم المستند (ID)
        - اسم العميل
        - رقم هاتف العميل
        - مرجع العميل (Client Ref)
        """
        if not query:
            return self

        # نحاول تحويل البحث لرقم إذا كان المستخدم يبحث عن ID
        lookup = (
                Q(contact__name__icontains=query) |
                Q(contact__phone__icontains=query) |
                Q(client_reference__icontains=query)
        )

        # إذا كان البحث رقمي، ربما يبحث عن رقم المستند مباشرة
        if query.isdigit():
            lookup |= Q(pk=query)

        return self.alive().filter(lookup)


class SalesDocumentManager(models.Manager):
    """
    Manager افتراضي لـ SalesDocument.
    الافتراضي: يعيد السجلات غير المحذوفة فقط (alive).
    """

    def _base_queryset(self) -> SalesDocumentQuerySet:
        return SalesDocumentQuerySet(self.model, using=self._db)

    def get_queryset(self):
        return self._base_queryset().alive()

    # -------- الوصول للسجلات المحذوفة --------

    def with_deleted(self):
        return self._base_queryset().with_deleted()

    def only_deleted(self):
        return self._base_queryset().deleted()

    # -------- Wrappers --------

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

    def invoiced(self):
        return self.get_queryset().invoiced()

    def not_invoiced(self):
        return self.get_queryset().not_invoiced()

    def for_contact(self, contact: Contact | int):
        return self.get_queryset().for_contact(contact)

    def search(self, query):
        return self.get_queryset().search(query)


# ===================================================================
# QuerySet و Manager لبنود المبيعات
# ===================================================================


class SalesLineQuerySet(models.QuerySet):
    """
    QuerySet لبنود المبيعات.
    """

    def for_document(self, document):
        doc_id = document.pk if hasattr(document, "pk") else document
        return self.filter(document_id=doc_id)

    def for_product(self, product: Product | int):
        product_id = product.pk if isinstance(product, Product) else product
        return self.filter(product_id=product_id)

    def for_contact(self, contact: Contact | int):
        contact_id = contact.pk if isinstance(contact, Contact) else contact
        return self.filter(document__contact_id=contact_id)

    def quotations(self):
        return self.filter(document__kind="quotation")

    def orders(self):
        return self.filter(document__kind="order")


class SalesLineManager(models.Manager):
    def get_queryset(self):
        return SalesLineQuerySet(self.model, using=self._db)

    def for_document(self, document):
        return self.get_queryset().for_document(document)

    def for_product(self, product: Product | int):
        return self.get_queryset().for_product(product)

    def for_contact(self, contact: Contact | int):
        return self.get_queryset().for_contact(contact)

    def quotations(self):
        return self.get_queryset().quotations()

    def orders(self):
        return self.get_queryset().orders()


# ===================================================================
# QuerySet و Manager لمذكرات التسليم
# ===================================================================


class DeliveryNoteQuerySet(models.QuerySet):
    """
    QuerySet لمذكرات التسليم مع دعم البحث المتقدم عن العميل.
    """

    # -------- soft delete --------

    def alive(self):
        return self.filter(is_deleted=False)

    def deleted(self):
        return self.filter(is_deleted=True)

    def with_deleted(self):
        return self.all()

    # -------- الحالة --------

    def drafts(self):
        return self.alive().filter(status="draft")

    def confirmed(self):
        return self.alive().filter(status="confirmed")

    def cancelled(self):
        return self.alive().filter(status="cancelled")

    # -------- بحسب أمر البيع / العميل --------

    def for_order(self, order):
        order_id = order.pk if hasattr(order, "pk") else order
        return self.alive().filter(order_id=order_id)

    def for_contact(self, contact: Contact | int):
        """
        بحث عن العميل في حقل المذكرة أو حقل الأمر المرتبط.
        """
        contact_id = contact.pk if isinstance(contact, Contact) else contact
        return self.alive().filter(
            Q(contact_id=contact_id) | Q(order__contact_id=contact_id)
        )


class DeliveryNoteManager(models.Manager):
    def _base_queryset(self) -> DeliveryNoteQuerySet:
        return DeliveryNoteQuerySet(self.model, using=self._db)

    def get_queryset(self):
        return self._base_queryset().alive()

    def with_deleted(self):
        return self._base_queryset().with_deleted()

    def only_deleted(self):
        return self._base_queryset().deleted()

    def drafts(self):
        return self.get_queryset().drafts()

    def confirmed(self):
        return self.get_queryset().confirmed()

    def cancelled(self):
        return self.get_queryset().cancelled()

    def for_order(self, order):
        return self.get_queryset().for_order(order)

    def for_contact(self, contact: Contact | int):
        return self.get_queryset().for_contact(contact)


# ===================================================================
# QuerySet و Manager لبنود التسليم
# ===================================================================


class DeliveryLineQuerySet(models.QuerySet):
    """
    QuerySet لبنود التسليم.
    """

    def for_delivery(self, delivery):
        delivery_id = delivery.pk if hasattr(delivery, "pk") else delivery
        return self.filter(delivery_id=delivery_id)

    def for_product(self, product: Product | int):
        product_id = product.pk if isinstance(product, Product) else product
        return self.filter(product_id=product_id)

    def for_order(self, order):
        order_id = order.pk if hasattr(order, "pk") else order
        return self.filter(delivery__order_id=order_id)

    def for_contact(self, contact: Contact | int):
        contact_id = contact.pk if isinstance(contact, Contact) else contact
        return self.filter(
            Q(delivery__contact_id=contact_id)
            | Q(delivery__order__contact_id=contact_id)
        )


class DeliveryLineManager(models.Manager):
    def get_queryset(self):
        return DeliveryLineQuerySet(self.model, using=self._db)

    def for_delivery(self, delivery):
        return self.get_queryset().for_delivery(delivery)

    def for_product(self, product: Product | int):
        return self.get_queryset().for_product(product)

    def for_order(self, order):
        return self.get_queryset().for_order(order)

    def for_contact(self, contact: Contact | int):
        return self.get_queryset().for_contact(contact)