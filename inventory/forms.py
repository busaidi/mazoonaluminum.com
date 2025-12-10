from django import forms
from django.forms import inlineformset_factory
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from .models import (
    StockMove, StockMoveLine, Product, StockLocation, Warehouse,
    ProductCategory, InventoryAdjustment, InventoryAdjustmentLine, ReorderRule
)


# ============================================================
# Mixin لتنسيق Bootstrap (لتقليل التكرار)
# ============================================================
class BootstrapFormMixin:
    """يضيف كلاسات Bootstrap تلقائياً للحقول."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget,
                          (forms.TextInput, forms.Textarea, forms.NumberInput, forms.DateInput, forms.EmailInput,
                           forms.URLInput)):
                widget.attrs.setdefault("class", "form-control")
            elif isinstance(widget, (forms.Select,)):
                widget.attrs.setdefault("class", "form-select")
            elif isinstance(widget, (forms.CheckboxInput,)):
                widget.attrs.setdefault("class", "form-check-input")


# ============================================================
# نماذج حركات المخزون (Header Forms)
# ============================================================

class BaseStockMoveForm(BootstrapFormMixin, forms.ModelForm):
    """النموذج الأساسي المشترك للحركات"""

    class Meta:
        model = StockMove
        # نستخدم 'note' فقط، وسيقوم النظام بحفظها في لغة المستخدم الحالية
        fields = ["reference", "move_date", "note"]
        widgets = {
            "move_date": forms.DateInput(attrs={"type": "date"}),
            "reference": forms.TextInput(attrs={"placeholder": _("مرجع اختياري (مثلاً رقم الفاتورة)")}),
            "note": forms.Textarea(attrs={"rows": 2, "placeholder": _("ملاحظات عن الحركة...")}),
        }


class ReceiptMoveForm(BaseStockMoveForm):
    """حركة واردة (Purchase/In)"""

    class Meta(BaseStockMoveForm.Meta):
        fields = BaseStockMoveForm.Meta.fields + ["to_warehouse", "to_location"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to_warehouse"].empty_label = _("اختر المستودع المستلم...")
        self.fields["to_location"].empty_label = _("اختر موقع التخزين...")
        # نعرض فقط المواقع الداخلية النشطة
        self.fields["to_location"].queryset = StockLocation.objects.internal().active()


class DeliveryMoveForm(BaseStockMoveForm):
    """حركة صادرة (Sales/Out)"""

    class Meta(BaseStockMoveForm.Meta):
        fields = BaseStockMoveForm.Meta.fields + ["from_warehouse", "from_location"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["from_warehouse"].empty_label = _("اختر المستودع المصدر...")
        self.fields["from_location"].empty_label = _("اختر الموقع...")
        self.fields["from_location"].queryset = StockLocation.objects.internal().active()


class TransferMoveForm(BaseStockMoveForm):
    """حركة تحويل داخلي"""

    class Meta(BaseStockMoveForm.Meta):
        fields = BaseStockMoveForm.Meta.fields + ["from_warehouse", "from_location", "to_warehouse", "to_location"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["from_warehouse"].empty_label = _("من مستودع...")
        self.fields["to_warehouse"].empty_label = _("إلى مستودع...")

        internal_locs = StockLocation.objects.internal().active()
        self.fields["from_location"].queryset = internal_locs
        self.fields["to_location"].queryset = internal_locs

    def clean(self):
        cleaned_data = super().clean()
        from_wh = cleaned_data.get("from_warehouse")
        to_wh = cleaned_data.get("to_warehouse")
        from_loc = cleaned_data.get("from_location")
        to_loc = cleaned_data.get("to_location")

        if from_wh and to_wh and from_wh == to_wh and from_loc == to_loc:
            raise forms.ValidationError(_("لا يمكن التحويل لنفس الموقع والمستودع."))

        return cleaned_data


# ============================================================
# نموذج البنود (Line Form & Formset)
# ============================================================

class StockMoveLineForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = StockMoveLine
        fields = ["product", "quantity", "uom"]
        widgets = {
            "product": forms.Select(attrs={"class": "form-select product-select"}),  # كلاس إضافي لـ Select2 إذا أردت
            "quantity": forms.NumberInput(attrs={"step": "0.001", "min": "0.001"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # نعرض فقط المنتجات المخزنية النشطة
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

class ProductForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "code",
            "name_ar", "name_en",
            "category", "product_type",
            "base_uom",
            "default_sale_price",
            # "average_cost",  <-- عادة لا نسمح بتعديل التكلفة يدوياً من هنا، تتم عبر الجرد أو التوريد
            "barcode", "is_stock_item", "is_active",
            "short_description_ar", "short_description_en",  # تمت إضافتها
            "description_ar", "description_en"
        ]
        widgets = {
            "description_ar": forms.Textarea(attrs={"rows": 3}),
            "description_en": forms.Textarea(attrs={"rows": 3}),
            "short_description_ar": forms.TextInput(),
            "short_description_en": forms.TextInput(),
        }
        labels = {
            "name_ar": _("اسم المنتج (عربي)"),
            "name_en": _("اسم المنتج (إنجليزي)"),
            "short_description_ar": _("وصف مختصر (عربي)"),
            "short_description_en": _("وصف مختصر (إنجليزي)"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].empty_label = _("اختر التصنيف...")
        self.fields["base_uom"].empty_label = _("وحدة القياس...")


class WarehouseForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ["code", "name_ar", "name_en", "description_ar", "description_en", "is_active"]
        widgets = {
            "description_ar": forms.Textarea(attrs={"rows": 2}),
            "description_en": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {
            "name_ar": _("اسم المستودع (عربي)"),
            "name_en": _("اسم المستودع (إنجليزي)"),
        }


class ProductCategoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ProductCategory
        fields = ["name_ar", "name_en", "slug", "parent", "description_ar", "description_en", "is_active"]
        widgets = {
            "description_ar": forms.Textarea(attrs={"rows": 3}),
            "description_en": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "name_ar": _("اسم التصنيف (عربي)"),
            "name_en": _("اسم التصنيف (إنجليزي)"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].empty_label = _("تصنيف رئيسي (بدون أب)")
        self.fields["slug"].help_text = _("يترك فارغاً للتوليد التلقائي من الاسم الإنجليزي.")
        self.fields["slug"].required = False

    def clean_slug(self):
        slug = self.cleaned_data.get("slug")
        name_en = self.cleaned_data.get("name_en")
        name_ar = self.cleaned_data.get("name_ar")

        if not slug:
            if name_en:
                slug = slugify(name_en)
            elif name_ar:
                slug = slugify(name_ar, allow_unicode=True)
        return slug


class StockLocationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = StockLocation
        fields = ["warehouse", "name_ar", "name_en", "code", "type", "is_active"]
        labels = {
            "name_ar": _("اسم الموقع (عربي)"),
            "name_en": _("اسم الموقع (إنجليزي)"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].empty_label = _("اختر المستودع التابع له...")


# ============================================================
# نماذج الجرد (Inventory Adjustment)
# ============================================================

class StartInventoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = InventoryAdjustment
        fields = ["warehouse", "category", "location", "note"]
        widgets = {
            "note": forms.Textarea(attrs={"rows": 2, "placeholder": _("ملاحظات عن جلسة الجرد...")}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].empty_label = _("اختر المستودع...")
        self.fields["category"].empty_label = _("الكل (جميع التصنيفات)")
        self.fields["location"].empty_label = _("الكل (جميع المواقع)")


class InventoryLineCountForm(forms.ModelForm):
    """فورم بسيط لعد الكميات داخل الـ Formset"""

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

class ReorderRuleForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ReorderRule
        fields = ["product", "warehouse", "location", "min_qty", "target_qty", "is_active"]
        widgets = {
            "min_qty": forms.NumberInput(attrs={"step": "1"}),
            "target_qty": forms.NumberInput(attrs={"step": "1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].empty_label = _("اختر المنتج...")
        self.fields["warehouse"].empty_label = _("اختر المستودع...")
        self.fields["location"].empty_label = _("كل المواقع (افتراضي)")

        self.fields["min_qty"].help_text = _("الحد الأدنى الذي يطلق التنبيه.")
        self.fields["target_qty"].help_text = _("الكمية المراد الوصول إليها.")

    def clean(self):
        cleaned_data = super().clean()
        min_qty = cleaned_data.get("min_qty")
        target_qty = cleaned_data.get("target_qty")

        if min_qty is not None and target_qty is not None:
            if target_qty <= min_qty:
                raise forms.ValidationError(_("الكمية المستهدفة (Target) يجب أن تكون أكبر من الحد الأدنى (Min)."))

        return cleaned_data