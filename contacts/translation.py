# contacts/translation.py
from modeltranslation.translator import TranslationOptions, register
from .models import Customer, CustomerAddress


@register(Customer)
class CustomerTranslationOptions(TranslationOptions):
    fields = (
        "name",
        "company_name",
        "address",
        "country",
        "governorate",
        "wilaya",
        "village",
        "postal_code",
        "po_box",
    )


@register(CustomerAddress)
class CustomerAddressTranslationOptions(TranslationOptions):
    fields = (
        "address",
        "country",
        "governorate",
        "wilaya",
        "village",
        "postal_code",
        "po_box",
    )
