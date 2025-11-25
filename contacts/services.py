# contacts/services.py
from django.db import transaction

from .models import Contact


def save_contact_with_addresses(contact_form, address_formset) -> Contact:
    """
    حفظ Contact مع العناوين المرتبطة به في معاملة واحدة (transaction).

    يفترض أن:
    - contact_form.is_valid() == True
    - address_formset.is_valid() == True
    """
    with transaction.atomic():
        contact = contact_form.save()
        address_formset.instance = contact
        address_formset.save()
    return contact


