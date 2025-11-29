from django.db import models

from contacts.models import Contact


class SalesDocumentQuerySet(models.QuerySet):
    """QuerySet مخصص لمستندات المبيعات مع فلاتر جاهزة."""

    def quotations(self):
        return self.filter(kind="quotation")

    def orders(self):
        return self.filter(kind="order")

    def for_contact(self, contact: Contact | int):
        """فلتر بحسب جهة الاتصال (كائن أو id)."""
        contact_id = contact.pk if isinstance(contact, Contact) else contact
        return self.filter(contact_id=contact_id)
