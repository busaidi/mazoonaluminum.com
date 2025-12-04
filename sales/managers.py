# sales/managers.py
from django.db import models

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
    - فلاتر حسب الحالة (مسودة / مؤكد / ملغي)
    - فلاتر الفوترة (مفوتر / غير مفوتر)
    - فلتر حسب جهة الاتصال
    """

    # -------- soft delete --------

    def alive(self):
        """
        السجلات غير المحذوفة (الافتراضي).
        """
        return self.filter(is_deleted=False)

    def deleted(self):
        """
        السجلات المحذوفة فقط.
        """
        return self.filter(is_deleted=True)

    def with_deleted(self):
        """
        كل السجلات (محذوفة وغير محذوفة).
        """
        return self.all()

    # -------- النوع: عرض / أمر --------

    def quotations(self):
        """
        كل عروض الأسعار (غير المحذوفة).
        """
        return self.alive().filter(kind="quotation")

    def orders(self):
        """
        كل أوامر البيع (غير المحذوفة).
        """
        return self.alive().filter(kind="order")

    # -------- الحالة: مسودة / مؤكد / ملغي --------

    def drafts(self):
        """
        مستندات في حالة مسودة.
        """
        return self.alive().filter(status="draft")

    def confirmed(self):
        """
        مستندات مؤكدة.
        """
        return self.alive().filter(status="confirmed")

    def cancelled(self):
        """
        مستندات ملغاة.
        """
        return self.alive().filter(status="cancelled")

    # -------- الفوترة --------

    def invoiced(self):
        """
        المستندات التي تم فوترتها.
        """
        return self.alive().filter(is_invoiced=True)

    def not_invoiced(self):
        """
        المستندات التي لم تُفوتر بعد.
        """
        return self.alive().filter(is_invoiced=False)

    # -------- بحسب جهة الاتصال --------

    def for_contact(self, contact: Contact | int):
        """
        فلتر بحسب جهة الاتصال (كائن Contact أو رقم id)،
        مع استثناء السجلات المحذوفة تلقائياً.
        """
        contact_id = contact.pk if isinstance(contact, Contact) else contact
        return self.alive().filter(contact_id=contact_id)


class SalesDocumentManager(models.Manager):
    """
    Manager افتراضي لـ SalesDocument:

    - يعيد فقط السجلات غير المحذوفة كـ default.
    - يعرّض نفس الفلاتر الموجودة في SalesDocumentQuerySet.
    - يوفر .with_deleted() و .only_deleted() عند الحاجة.
    """

    def _base_queryset(self) -> SalesDocumentQuerySet:
        """
        QuerySet أساس يُستخدم داخلياً.
        """
        return SalesDocumentQuerySet(self.model, using=self._db)

    def get_queryset(self):
        """
        الافتراضي: السجلات غير المحذوفة فقط.
        """
        return self._base_queryset().alive()

    # -------- الوصول للسجلات المحذوفة --------

    def with_deleted(self):
        """
        كل السجلات بما فيها المحذوفة.
        """
        return self._base_queryset().with_deleted()

    def only_deleted(self):
        """
        السجلات المحذوفة فقط.
        """
        return self._base_queryset().deleted()

    # -------- wrappers للفلاتر المتخصصة --------

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


# ===================================================================
# QuerySet و Manager لبنود المبيعات
# ===================================================================


class SalesLineQuerySet(models.QuerySet):
    """
    QuerySet لبنود المبيعات:

    - فلاتر حسب المستند
    - فلاتر حسب المنتج
    - فلاتر حسب جهة الاتصال (عبر المستند)
    - فلاتر حسب نوع المستند (عرض / أمر)
    """

    def for_document(self, document):
        """
        بنود مستند معيّن (كائن مستند أو رقم id).
        """
        doc_id = document.pk if hasattr(document, "pk") else document
        return self.filter(document_id=doc_id)

    def for_product(self, product: Product | int):
        """
        بنود مرتبطة بمنتج معيّن.
        """
        product_id = product.pk if isinstance(product, Product) else product
        return self.filter(product_id=product_id)

    def for_contact(self, contact: Contact | int):
        """
        بنود مرتبطة بعميل معيّن عبر المستند.
        """
        contact_id = contact.pk if isinstance(contact, Contact) else contact
        return self.filter(document__contact_id=contact_id)

    def quotations(self):
        """
        بنود عروض الأسعار فقط.
        """
        return self.filter(document__kind="quotation")

    def orders(self):
        """
        بنود أوامر البيع فقط.
        """
        return self.filter(document__kind="order")


class SalesLineManager(models.Manager):
    """
    Manager افتراضي لـ SalesLine.

    لا يوجد soft delete هنا، فنرجع كل البنود مع دعم
    نفس الفلاتر الموجودة في SalesLineQuerySet.
    """

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
    QuerySet لمذكرات التسليم:

    - دعم soft delete (is_deleted)
    - فلاتر حسب الحالة (مسودة / مؤكد / ملغي)
    - فلاتر حسب أمر البيع
    - فلاتر حسب جهة الاتصال (سواء من المذكرة نفسها أو من أمر البيع)
    """

    # -------- soft delete --------

    def alive(self):
        """
        السجلات غير المحذوفة.
        """
        return self.filter(is_deleted=False)

    def deleted(self):
        """
        السجلات المحذوفة فقط.
        """
        return self.filter(is_deleted=True)

    def with_deleted(self):
        """
        كل السجلات (محذوفة وغير محذوفة).
        """
        return self.all()

    # -------- الحالة --------

    def drafts(self):
        """
        مذكرات في حالة مسودة.
        """
        return self.alive().filter(status="draft")

    def confirmed(self):
        """
        مذكرات مؤكدة.
        """
        return self.alive().filter(status="confirmed")

    def cancelled(self):
        """
        مذكرات ملغاة.
        """
        return self.alive().filter(status="cancelled")

    # -------- بحسب أمر البيع / العميل --------

    def for_order(self, order):
        """
        كل المذكرات لأمر بيع معيّن (كائن أو رقم id).
        """
        order_id = order.pk if hasattr(order, "pk") else order
        return self.alive().filter(order_id=order_id)

    def for_contact(self, contact: Contact | int):
        """
        كل المذكرات المرتبطة بعميل معيّن، سواء:
        - من حقل contact في المذكرة نفسها، أو
        - من contact في أمر البيع المرتبط.
        """
        contact_id = contact.pk if isinstance(contact, Contact) else contact
        return self.alive().filter(
            models.Q(contact_id=contact_id)
            | models.Q(order__contact_id=contact_id)
        )


class DeliveryNoteManager(models.Manager):
    """
    Manager افتراضي لـ DeliveryNote.

    - الافتراضي يعرض غير المحذوفة فقط.
    - يوفر دوال مساعدة للحالات والفلاتر الشائعة.
    """

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
    QuerySet لبنود التسليم:

    - فلاتر حسب مذكرة التسليم
    - فلاتر حسب المنتج
    - فلاتر حسب أمر البيع
    - فلاتر حسب جهة الاتصال (سواء من مذكرة التسليم أو من أمر البيع)
    """

    def for_delivery(self, delivery):
        """
        بنود مذكرة تسليم معيّنة (كائن أو رقم id).
        """
        delivery_id = delivery.pk if hasattr(delivery, "pk") else delivery
        return self.filter(delivery_id=delivery_id)

    def for_product(self, product: Product | int):
        """
        بنود مرتبطة بمنتج معيّن.
        """
        product_id = product.pk if isinstance(product, Product) else product
        return self.filter(product_id=product_id)

    def for_order(self, order):
        """
        بنود مذكرات تسليم مربوطة بأمر بيع معيّن.
        """
        order_id = order.pk if hasattr(order, "pk") else order
        return self.filter(delivery__order_id=order_id)

    def for_contact(self, contact: Contact | int):
        """
        بنود مذكرات تسليم لعميل معيّن، سواء من:
        - contact في المذكرة نفسها، أو
        - contact في أمر البيع المرتبط بالمذكرة.
        """
        contact_id = contact.pk if isinstance(contact, Contact) else contact
        return self.filter(
            models.Q(delivery__contact_id=contact_id)
            | models.Q(delivery__order__contact_id=contact_id)
        )


class DeliveryLineManager(models.Manager):
    """
    Manager افتراضي لـ DeliveryLine.

    لا يوجد soft delete هنا، فنرجع كل البنود مع فلاتر مساعدة.
    """

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
