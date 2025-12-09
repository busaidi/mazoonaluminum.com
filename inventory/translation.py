# inventory/translation.py

from modeltranslation.translator import register, TranslationOptions
from .models import (
    ProductCategory,
    Product,
    Warehouse,
    StockLocation,
    StockMove,
    InventoryAdjustment
)

# ============================================================
# البيانات الأساسية (Master Data)
# ============================================================

@register(ProductCategory)
class ProductCategoryTranslationOptions(TranslationOptions):
    fields = ('name', 'description')


@register(Product)
class ProductTranslationOptions(TranslationOptions):
    fields = ('name', 'short_description', 'description')


@register(Warehouse)
class WarehouseTranslationOptions(TranslationOptions):
    fields = ('name', 'description')


@register(StockLocation)
class StockLocationTranslationOptions(TranslationOptions):
    fields = ('name',)


# ============================================================
# العمليات (Operations)
# ============================================================
# نقوم بترجمة الملاحظات للسماح بإدخال ملاحظات ثنائية اللغة في الفواتير

@register(StockMove)
class StockMoveTranslationOptions(TranslationOptions):
    fields = ('note',)


@register(InventoryAdjustment)
class InventoryAdjustmentTranslationOptions(TranslationOptions):
    fields = ('note',)