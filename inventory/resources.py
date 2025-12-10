from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from .models import Product, ProductCategory, Product
from uom.models import UnitOfMeasure


class ProductResource(resources.ModelResource):
    # ربط الحقول بالعلاقات (بدل ما نكتب ID نكتب الاسم)
    category = fields.Field(
        column_name='category',
        attribute='category',
        widget=ForeignKeyWidget(ProductCategory, field='name')
    )
    base_uom = fields.Field(
        column_name='base_uom',
        attribute='base_uom',
        widget=ForeignKeyWidget(UnitOfMeasure, field='name')
    )

    class Meta:
        model = Product
        fields = ('code', 'name_ar', 'name_en', 'category', 'product_type', 'base_uom', 'default_sale_price', 'barcode')
        import_id_fields = ('code',)  # نستخدم الكود كمفتاح فريد عند الاستيراد
        skip_unchanged = True
        report_skipped = True