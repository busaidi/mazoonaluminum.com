# accounting/translation.py
from modeltranslation.translator import TranslationOptions, register
from .models import Customer


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
