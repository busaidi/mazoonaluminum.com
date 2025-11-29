# contacts/translation.py
from modeltranslation.translator import register, TranslationOptions

from .models import Contact, ContactAddress


@register(Contact)
class ContactTranslationOptions(TranslationOptions):
    """
    ترجمة الحقول الأساسية لجهة الاتصال:
    - الاسم
    - اسم الشركة الحر
    """
    fields = (
        "name",
        "company_name",
    )


@register(ContactAddress)
class ContactAddressTranslationOptions(TranslationOptions):
    """
    ترجمة العنوان التفصيلي + بيانات الموقع الأساسية:
    - address
    - country
    - governorate
    - wilaya
    - village
    """
    fields = (
        "address",
        "country",
        "governorate",
        "wilaya",
        "village",
    )
