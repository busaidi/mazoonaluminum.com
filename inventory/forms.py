# inventory/forms.py

from django import forms
from django.forms import inlineformset_factory
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from .models import StockMove, StockMoveLine, Product, StockLocation, Warehouse, ProductCategory


# ============================================================
# نماذج حركات المخزون (Header Forms)
# ============================================================

class BaseStockMoveForm(forms.ModelForm):
    """
    النموذج الأساسي المشترك.
    يحتوي على المنطق العام لتنسيق Bootstrap وتحديد الحقول المشتركة.
    """

    class Meta:
        model = StockMove
        fields = ["reference", "move_date", "note"]
        widgets = {
            "move_date": forms.DateInput(attrs={"type": "date"}),
            "reference": forms.TextInput(
                attrs={"placeholder": _("مرجع اختياري (مثلاً رقم الفاتورة)")}
            ),
            "note": forms.Textarea(
                attrs={"rows": 3, "placeholder": _("ملاحظات إضافية...")}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ✅ DRY: تطبيق تنسيقات Bootstrap تلقائياً على جميع الحقول
        for name, field in self.fields.items():
            if isinstance(field.widget, (forms.TextInput, forms.Textarea, forms.DateInput, forms.NumberInput)):
                field.widget.attrs.setdefault("class", "form-control")
            elif isinstance(field.widget, (forms.Select,)):
                field.widget.attrs.setdefault("class", "form-select")


class ReceiptMoveForm(BaseStockMoveForm):
    """نموذج الاستلام (IN): يطلب الوجهة فقط"""

    class Meta(BaseStockMoveForm.Meta):
        fields = BaseStockMoveForm.Meta.fields + ["to_warehouse", "to_location"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # تحسينات UX
        self.fields["to_warehouse"].empty_label = _("اختر المستودع المستلم...")
        self.fields["to_location"].empty_label = _("اختر موقع التخزين...")

        # 💡 اختياري: تصفية المواقع لتظهر الداخلية فقط افتراضياً
        self.fields["to_location"].queryset = StockLocation.objects.internal().active()


class DeliveryMoveForm(BaseStockMoveForm):
    """نموذج الصرف (OUT): يطلب المصدر فقط"""

    class Meta(BaseStockMoveForm.Meta):
        fields = BaseStockMoveForm.Meta.fields + ["from_warehouse", "from_location"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["from_warehouse"].empty_label = _("اختر المستودع المصدر...")
        self.fields["from_location"].empty_label = _("اختر الموقع...")

        # تصفية المواقع الداخلية فقط (عادة لا نصرف من موقع عميل)
        self.fields["from_location"].queryset = StockLocation.objects.internal().active()


class TransferMoveForm(BaseStockMoveForm):
    """نموذج التحويل (TRANSFER): يطلب المصدر والوجهة"""

    class Meta(BaseStockMoveForm.Meta):
        fields = BaseStockMoveForm.Meta.fields + [
            "from_warehouse", "from_location",
            "to_warehouse", "to_location"
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["from_warehouse"].empty_label = _("من مستودع...")
        self.fields["to_warehouse"].empty_label = _("إلى مستودع...")

        # في التحويلات، عادة نتعامل مع مواقع داخلية في الطرفين
        internal_locs = StockLocation.objects.internal().active()
        self.fields["from_location"].queryset = internal_locs
        self.fields["to_location"].queryset = internal_locs


# ============================================================
# نموذج البنود (Line Form & Formset)
# ============================================================

class StockMoveLineForm(forms.ModelForm):
    class Meta:
        model = StockMoveLine
        fields = ["product", "quantity", "uom"]
        widgets = {
            "product": forms.Select(attrs={"class": "form-select product-select"}),
            # ✅ UX: منع الصفر في الواجهة
            "quantity": forms.NumberInput(attrs={"class": "form-control", "step": "0.001", "min": "0.001"}),
            "uom": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ✅ Performance & Logic: عرض المنتجات النشطة والمخزنية فقط
        # نستخدم المانجر الجديد stock_items()
        self.fields["product"].queryset = Product.objects.active().stock_items()
        self.fields["product"].empty_label = _("اختر المنتج...")

    def clean_quantity(self):
        """تحقق إضافي من الكمية (Server-side validation)"""
        qty = self.cleaned_data.get("quantity")
        if qty is not None and qty <= 0:
            raise forms.ValidationError(_("الكمية يجب أن تكون أكبر من صفر."))
        return qty


# Formset Factory
StockMoveLineFormSet = inlineformset_factory(
    StockMove,
    StockMoveLine,
    form=StockMoveLineForm,
    extra=1,  # صف واحد فارغ للكتابة
    can_delete=True,  # السماح بالحذف
    min_num=1,  # ✅ Validation: يجب إدخال بند واحد على الأقل
    validate_min=True,  # تفعيل التحقق من min_num
)


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "code", "name", "category", "product_type",
            "base_uom", "default_sale_price", "average_cost",
            "barcode", "is_stock_item", "is_active", "description"
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # تطبيق تنسيق Bootstrap
        for name, field in self.fields.items():
            if isinstance(field.widget, (forms.TextInput, forms.Textarea, forms.NumberInput)):
                field.widget.attrs.setdefault("class", "form-control")
            elif isinstance(field.widget, (forms.Select,)):
                field.widget.attrs.setdefault("class", "form-select")
            elif isinstance(field.widget, (forms.CheckboxInput,)):
                field.widget.attrs.setdefault("class", "form-check-input")

        # تحسينات UX
        self.fields["category"].empty_label = _("اختر التصنيف...")
        self.fields["base_uom"].empty_label = _("وحدة القياس...")


class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ["code", "name", "description", "is_active"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, (forms.TextInput, forms.Textarea)):
                field.widget.attrs.setdefault("class", "form-control")
            elif isinstance(field.widget, (forms.CheckboxInput,)):
                field.widget.attrs.setdefault("class", "form-check-input")


class ProductCategoryForm(forms.ModelForm):
    class Meta:
        model = ProductCategory
        fields = ["name", "slug", "parent", "description", "is_active"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, (forms.TextInput, forms.Textarea)):
                field.widget.attrs.setdefault("class", "form-control")
            elif isinstance(field.widget, (forms.Select,)):
                field.widget.attrs.setdefault("class", "form-select")
            elif isinstance(field.widget, (forms.CheckboxInput,)):
                field.widget.attrs.setdefault("class", "form-check-input")

        self.fields["parent"].empty_label = _("تصنيف رئيسي (بدون أب)")
        self.fields["slug"].help_text = _("يترك فارغاً للتوليد التلقائي من الاسم.")
        self.fields["slug"].required = False  # سنقوم بتوليده في الـ View إذا كان فارغاً

    def clean_slug(self):
        slug = self.cleaned_data.get("slug")
        name = self.cleaned_data.get("name")
        if not slug and name:
            slug = slugify(name, allow_unicode=True)
        return slug


class StockLocationForm(forms.ModelForm):
    class Meta:
        model = StockLocation
        fields = ["warehouse", "name", "code", "type", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, (forms.TextInput,)):
                field.widget.attrs.setdefault("class", "form-control")
            elif isinstance(field.widget, (forms.Select,)):
                field.widget.attrs.setdefault("class", "form-select")
            elif isinstance(field.widget, (forms.CheckboxInput,)):
                field.widget.attrs.setdefault("class", "form-check-input")

        self.fields["warehouse"].empty_label = _("اختر المستودع التابع له...")