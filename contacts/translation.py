# contacts/translation.py
from modeltranslation.translator import register, TranslationOptions

from .models import Contact, ContactAddress


@register(Contact)
class ContactTranslationOptions(TranslationOptions):
    """
    الحقول المترجمة في Contact:
    - الاسم
    - اسم الشركة
    - العنوان الحر
    - تفاصيل الموقع (دولة، محافظة، ولاية، قرية)
    - الرمز البريدي وصندوق البريد
    """
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


@register(ContactAddress)
class ContactAddressTranslationOptions(TranslationOptions):
    """
    الحقول المترجمة في ContactAddress:
    - وصف العنوان (label)
    - العنوان التفصيلي
    - تفاصيل الموقع (دولة، محافظة، ولاية، قرية)
    - الرمز البريدي وصندوق البريد
    """
    fields = (
        "label",
        "address",
        "country",
        "governorate",
        "wilaya",
        "village",
        "postal_code",
        "po_box",
    )
