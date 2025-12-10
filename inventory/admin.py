# from django.contrib import admin
# from modeltranslation.admin import TranslationAdmin
# from .models import (
#     InventorySettings, ProductCategory, Product, Warehouse, StockLocation,
#     StockMove, StockMoveLine, StockLevel, ReorderRule, InventoryAdjustment
# )
#
# @admin.register(InventorySettings)
# class InventorySettingsAdmin(TranslationAdmin):
#     pass
#
# @admin.register(ProductCategory)
# class ProductCategoryAdmin(TranslationAdmin):
#     list_display = ('name', 'parent', 'is_active')
#     search_fields = ('name', 'description')
#
# @admin.register(Product)
# class ProductAdmin(TranslationAdmin):
#     list_display = ('code', 'name', 'category', 'product_type', 'total_on_hand', 'is_active')
#     search_fields = ('code', 'name', 'barcode')
#     list_filter = ('product_type', 'category', 'is_active')
#     readonly_fields = ('average_cost',)
#
# @admin.register(Warehouse)
# class WarehouseAdmin(TranslationAdmin):
#     list_display = ('code', 'name', 'is_active')
#
# @admin.register(StockLocation)
# class StockLocationAdmin(TranslationAdmin):
#     list_display = ('code', 'name', 'warehouse', 'type')
#     list_filter = ('warehouse', 'type')
#
# class StockMoveLineInline(admin.TabularInline):
#     model = StockMoveLine
#     extra = 0
#     autocomplete_fields = ['product']
#
# @admin.register(StockMove)
# class StockMoveAdmin(admin.ModelAdmin):
#     list_display = ('reference', 'move_type', 'move_date', 'from_warehouse', 'to_warehouse', 'status')
#     list_filter = ('move_type', 'status', 'move_date')
#     inlines = [StockMoveLineInline]
#     date_hierarchy = 'move_date'
#
# @admin.register(StockLevel)
# class StockLevelAdmin(admin.ModelAdmin):
#     list_display = ('product', 'warehouse', 'location', 'quantity_on_hand', 'quantity_reserved')
#     list_filter = ('warehouse', 'location')
#     search_fields = ('product__name', 'product__code')
#
# @admin.register(ReorderRule)
# class ReorderRuleAdmin(admin.ModelAdmin):
#     list_display = ('product', 'warehouse', 'location', 'min_qty', 'target_qty', 'is_active')
#
# @admin.register(InventoryAdjustment)
# class InventoryAdjustmentAdmin(TranslationAdmin):
#     list_display = ('pk', 'warehouse', 'date', 'status')
#     list_filter = ('status', 'warehouse')