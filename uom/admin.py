from django.contrib import admin

from uom.models import UnitOfMeasure, UomCategory


# Register your models here.
@admin.register(UnitOfMeasure)
class UomCategoryAdmin(admin.ModelAdmin):
    pass


@admin.register(UomCategory)
class UomCategoryAdmin(admin.ModelAdmin):
    pass