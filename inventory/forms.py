from django import forms
from django.forms import inlineformset_factory
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from .models import (
    StockMove, StockMoveLine, Product, StockLocation, Warehouse,
    ProductCategory, InventoryAdjustment, InventoryAdjustmentLine, ReorderRule
)


# ============================================================
# نماذج حركات المخزون (Header Forms)
# ============================================================
# ملاحظة: حركات المخزون عادة لا تحتاج ترجمة لأن الملاحظات خاصة بالعملية نفسها

class BaseStockMoveForm(forms.ModelForm):
    """النموذج الأساسي المشترك"""

    class Meta:
        model = StockMove
        fields = ["reference", "move_date", "note"]
        widgets = {
            "move_date": forms.DateInput(attrs={"type": "date"}),
            "reference": forms.TextInput(attrs={"placeholder": _("مرجع اختياري (مثلاً رقم الفاتورة)")}),
            "note": forms.Textarea(attrs={"rows": 3, "placeholder": _("ملاحظات إضافية...")}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, (forms.TextInput, forms.Textarea, forms.DateInput, forms.NumberInput)):
                field.widget.attrs.setdefault("class", "form-control")
            elif isinstance(field.widget, (forms.Select,)):
                field.widget.attrs.setdefault("class", "form-select")


class ReceiptMoveForm(BaseStockMoveForm):
    class Meta(BaseStockMoveForm.Meta):
        fields = BaseStockMoveForm.Meta.fields + ["to_warehouse", "to_location"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to_warehouse"].empty_label = _("اختر المستودع المستلم...")
        self.fields["to_location"].empty_label = _("اختر موقع التخزين...")
        self.fields["to_location"].queryset = StockLocation.objects.internal().active()


class DeliveryMoveForm(BaseStockMoveForm):
    class Meta(BaseStockMoveForm.Meta):
        fields = BaseStockMoveForm.Meta.fields + ["from_warehouse", "from_location"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["from_warehouse"].empty_label = _("اختر المستودع المصدر...")
        self.fields["from_location"].empty_label = _("اختر الموقع...")
        self.fields["from_location"].queryset = StockLocation.objects.internal().active()


class TransferMoveForm(BaseStockMoveForm):
    class Meta(BaseStockMoveForm.Meta):
        fields = BaseStockMoveForm.Meta.fields + ["from_warehouse", "from_location", "to_warehouse", "to_location"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["from_warehouse"].empty_label = _("من مستودع...")
        self.fields["to_warehouse"].empty_label = _("إلى مستودع...")
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
            "quantity": forms.NumberInput(attrs={"class": "form-control", "step": "0.001", "min": "0.001"}),
            "uom": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.active().stock_items()
        self.fields["product"].empty_label = _("اختر المنتج...")

    def clean_quantity(self):
        qty = self.cleaned_data.get("quantity")
        if qty is not None and qty <= 0:
            raise forms.ValidationError(_("الكمية يجب أن تكون أكبر من صفر."))
        return qty


StockMoveLineFormSet = inlineformset_factory(
    StockMove, StockMoveLine, form=StockMoveLineForm,
    extra=1, can_delete=True, min_num=1, validate_min=True,
)


# ============================================================
# نماذج البيانات الأساسية (مع دعم الترجمة)
# ============================================================

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        # ✅ FIX: إضافة حقول الترجمة
        fields = [
            "code",
            "name_ar", "name_en",
            "category", "product_type",
            "base_uom", "default_sale_price", "average_cost",
            "barcode", "is_stock_item", "is_active",
            "description_ar", "description_en"
        ]
        widgets = {
            "description_ar": forms.Textarea(attrs={"rows": 3}),
            "description_en": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "name_ar": _("اسم المنتج (عربي)"),
            "name_en": _("اسم المنتج (إنجليزي)"),
            "description_ar": _("الوصف (عربي)"),
            "description_en": _("الوصف (إنجليزي)"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Bootstrap styling
        for field in self.fields.values():
            if isinstance(field.widget, (forms.TextInput, forms.Textarea, forms.NumberInput, forms.Select)):
                field.widget.attrs.setdefault("class", "form-control")
                if isinstance(field.widget, forms.Select):
                    field.widget.attrs.setdefault("class", "form-select")
            elif isinstance(field.widget, (forms.CheckboxInput,)):
                field.widget.attrs.setdefault("class", "form-check-input")

        self.fields["category"].empty_label = _("اختر التصنيف...")
        self.fields["base_uom"].empty_label = _("وحدة القياس...")


class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        # ✅ FIX: إضافة حقول الترجمة
        fields = ["code", "name_ar", "name_en", "description_ar", "description_en", "is_active"]
        widgets = {
            "description_ar": forms.Textarea(attrs={"rows": 2}),
            "description_en": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {
            "name_ar": _("اسم المستودع (عربي)"),
            "name_en": _("اسم المستودع (إنجليزي)"),
            "description_ar": _("الوصف (عربي)"),
            "description_en": _("الوصف (إنجليزي)"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, (forms.TextInput, forms.Textarea)):
                field.widget.attrs.setdefault("class", "form-control")
            elif isinstance(field.widget, (forms.CheckboxInput,)):
                field.widget.attrs.setdefault("class", "form-check-input")


class ProductCategoryForm(forms.ModelForm):
    class Meta:
        model = ProductCategory
        # ✅ FIX: إضافة حقول الترجمة
        fields = ["name_ar", "name_en", "slug", "parent", "description_ar", "description_en", "is_active"]
        widgets = {
            "description_ar": forms.Textarea(attrs={"rows": 3}),
            "description_en": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "name_ar": _("اسم التصنيف (عربي)"),
            "name_en": _("اسم التصنيف (إنجليزي)"),
            "description_ar": _("الوصف (عربي)"),
            "description_en": _("الوصف (إنجليزي)"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, (forms.TextInput, forms.Textarea, forms.Select)):
                field.widget.attrs.setdefault("class", "form-control")
                if isinstance(field.widget, forms.Select):
                    field.widget.attrs.setdefault("class", "form-select")
            elif isinstance(field.widget, (forms.CheckboxInput,)):
                field.widget.attrs.setdefault("class", "form-check-input")

        self.fields["parent"].empty_label = _("تصنيف رئيسي (بدون أب)")
        self.fields["slug"].help_text = _("يترك فارغاً للتوليد التلقائي من الاسم الإنجليزي.")
        self.fields["slug"].required = False

    def clean_slug(self):
        slug = self.cleaned_data.get("slug")
        # نفضل التوليد من الاسم الإنجليزي لأنه أنظف في الروابط
        name_en = self.cleaned_data.get("name_en")
        name_ar = self.cleaned_data.get("name_ar")

        if not slug:
            if name_en:
                slug = slugify(name_en)
            elif name_ar:
                slug = slugify(name_ar, allow_unicode=True)
        return slug


class StockLocationForm(forms.ModelForm):
    class Meta:
        model = StockLocation
        # ✅ FIX: إضافة حقول الترجمة
        fields = ["warehouse", "name_ar", "name_en", "code", "type", "is_active"]
        labels = {
            "name_ar": _("اسم الموقع (عربي)"),
            "name_en": _("اسم الموقع (إنجليزي)"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, (forms.TextInput, forms.Select)):
                field.widget.attrs.setdefault("class", "form-control")
                if isinstance(field.widget, forms.Select):
                    field.widget.attrs.setdefault("class", "form-select")
            elif isinstance(field.widget, (forms.CheckboxInput,)):
                field.widget.attrs.setdefault("class", "form-check-input")

        self.fields["warehouse"].empty_label = _("اختر المستودع التابع له...")


# ============================================================
# نماذج الجرد (Inventory Adjustment)
# ============================================================

class StartInventoryForm(forms.ModelForm):
    class Meta:
        model = InventoryAdjustment
        fields = ["warehouse", "category", "location", "note"]
        widgets = {
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, (forms.TextInput, forms.Textarea, forms.Select)):
                field.widget.attrs.setdefault("class", "form-control")
                if isinstance(field.widget, forms.Select):
                    field.widget.attrs.setdefault("class", "form-select")

        self.fields["warehouse"].empty_label = _("اختر المستودع...")
        self.fields["category"].empty_label = _("الكل (جميع التصنيفات)")
        self.fields["location"].empty_label = _("الكل (جميع المواقع)")


class InventoryLineCountForm(forms.ModelForm):
    class Meta:
        model = InventoryAdjustmentLine
        fields = ["counted_qty"]
        widgets = {
            "counted_qty": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.001"}),
        }


InventoryCountFormSet = inlineformset_factory(
    InventoryAdjustment, InventoryAdjustmentLine, form=InventoryLineCountForm,
    fields=["counted_qty"], extra=0, can_delete=False,
)


# ============================================================
# قواعد إعادة الطلب
# ============================================================

class ReorderRuleForm(forms.ModelForm):
    class Meta:
        model = ReorderRule
        fields = ["product", "warehouse", "location", "min_qty", "target_qty", "is_active"]
        widgets = {
            "min_qty": forms.NumberInput(attrs={"step": "1"}),
            "target_qty": forms.NumberInput(attrs={"step": "1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, (forms.TextInput, forms.NumberInput, forms.Select)):
                field.widget.attrs.setdefault("class", "form-control")
                if isinstance(field.widget, forms.Select):
                    field.widget.attrs.setdefault("class", "form-select")
            elif isinstance(field.widget, (forms.CheckboxInput,)):
                field.widget.attrs.setdefault("class", "form-check-input")

        self.fields["product"].empty_label = _("اختر المنتج...")
        self.fields["warehouse"].empty_label = _("اختر المستودع...")
        self.fields["location"].empty_label = _("كل المواقع (افتراضي)")

        self.fields["min_qty"].help_text = _("عندما يصل المخزون لهذا الرقم (أو أقل)، سيقترح النظام الشراء.")
        self.fields["target_qty"].help_text = _("الكمية التي نريد الوصول إليها بعد الشراء (الحد الأقصى).")

    def clean(self):
        cleaned_data = super().clean()
        min_qty = cleaned_data.get("min_qty")
        target_qty = cleaned_data.get("target_qty")
        if min_qty is not None and target_qty is not None:
            if target_qty <= min_qty:
                raise forms.ValidationError(_("الكمية المستهدفة (Target) يجب أن تكون أكبر من الحد الأدنى (Min)."))
        return cleaned_data