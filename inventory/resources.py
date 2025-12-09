# inventory/resources.py

from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from .models import Product, ProductCategory
from uom.models import UnitOfMeasure


class ProductResource(resources.ModelResource):
    # 1. التعامل مع التصنيف (Category)
    # في الإكسل نكتب الاسم، والنظام يبحث عنه في جدول التصنيفات
    category = fields.Field(
        column_name='category',
        attribute='category',
        widget=ForeignKeyWidget(ProductCategory, field='name')
    )

    # 2. التعامل مع وحدة القياس (UoM)
    base_uom = fields.Field(
        column_name='uom',
        attribute='base_uom',
        widget=ForeignKeyWidget(UnitOfMeasure, field='name')
    )

    class Meta:
        model = Product
        # الحقول التي نريد استيرادها/تصديرها
        fields = ('code', 'name', 'category', 'base_uom', 'default_sale_price',
                  'average_cost', 'barcode', 'is_stock_item', 'is_active')

        # استخدام الكود كمعرف فريد (لتحديث المنتج إذا كان موجوداً بدلاً من تكراره)
        import_id_fields = ('code',)

        # استبعاد الـ ID الافتراضي لأننا نعتمد على الكود
        exclude = ('id',)

        # ترتيب الأعمدة في ملف الإكسل
        export_order = ('code', 'name', 'category', 'uom', 'default_sale_price', 'barcode')

    # ✅ الإصلاح: معالجة البيانات قبل الاستيراد
    def before_import_row(self, row, **kwargs):
        """
        يتم استدعاء هذه الدالة لكل سطر في الإكسل قبل معالجته.
        نستخدمها لتنظيف البيانات، خاصة الحقول التي يجب أن تكون فريدة (Unique) مثل الباركود.
        """

        # تنظيف حقل الباركود
        if 'barcode' in row:
            barcode_val = row['barcode']
            # إذا كان الباركود فارغاً أو مسافات بيضاء فقط -> حوله إلى None
            # هذا يمنع قاعدة البيانات من اعتباره "نصاً مكرراً فارغاً"
            if barcode_val is None or str(barcode_val).strip() == '':
                row['barcode'] = None

        # تنظيف حقل التصنيف (اختياري: لتجنب الأخطاء إذا كان فارغاً)
        if 'category' in row:
            if not row['category']:
                row['category'] = None

        # تنظيف حقل الوحدة
        if 'uom' in row:
            if not row['uom']:
                row['uom'] = None