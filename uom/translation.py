# uom/translation.py
from modeltranslation.translator import register, TranslationOptions

from .models import UomCategory, UnitOfMeasure


@register(UomCategory)
class UomCategoryTranslationOptions(TranslationOptions):
    # الحقول اللي نريد لها نسخ ar/en
    fields = ("name", "description",)


@register(UnitOfMeasure)
class UnitOfMeasureTranslationOptions(TranslationOptions):
    fields = ("name", "symbol", "notes",)
