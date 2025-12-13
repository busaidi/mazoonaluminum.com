from __future__ import annotations

from django import forms
from django.forms import inlineformset_factory
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from .models import (
    Product,
    ProductCategory,
    Warehouse,
    StockLocation,
    StockMove,
    StockMoveLine,
    InventoryAdjustment,
    InventoryAdjustmentLine,
    ReorderRule,
)

# ============================================================
# Bootstrap Mixin (موحد)
# ============================================================
class BootstrapFormMixin:
    """
    Automatically apply Bootstrap 5 classes.
    """

    def _apply_bootstrap(self):
        for field in self.fields.values():
            widget = field.widget

            if isinstance(widget, (forms.TextInput, forms.Textarea, forms.NumberInput, forms.DateInput)):
                widget.attrs.setdefault("class", "form-control")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            elif isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap()


# ============================================================
# Stock Move (Header)
# ============================================================
class BaseStockMoveForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = StockMove
        fields = ["reference", "move_date", "note"]
        widgets = {
            "move_date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }


class ReceiptMoveForm(BaseStockMoveForm):
    class Meta(BaseStockMoveForm.Meta):
        fields = BaseStockMoveForm.Meta.fields + ["to_warehouse", "to_location"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to_warehouse"].empty_label = _("اختر المستودع...")
        self.fields["to_location"].queryset = StockLocation.objects.internal().active()


class DeliveryMoveForm(BaseStockMoveForm):
    class Meta(BaseStockMoveForm.Meta):
        fields = BaseStockMoveForm.Meta.fields + ["from_warehouse", "from_location"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["from_location"].queryset = StockLocation.objects.internal().active()


class TransferMoveForm(BaseStockMoveForm):
    class Meta(BaseStockMoveForm.Meta):
        fields = BaseStockMoveForm.Meta.fields + [
            "from_warehouse", "from_location",
            "to_warehouse", "to_location",
        ]

    def clean(self):
        data = super().clean()
        if (
            data.get("from_warehouse") == data.get("to_warehouse")
            and data.get("from_location") == data.get("to_location")
        ):
            raise forms.ValidationError(_("لا يمكن التحويل لنفس الموقع."))
        return data


# ============================================================
# Stock Move Lines
# ============================================================
class StockMoveLineForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = StockMoveLine
        fields = ["product", "quantity", "uom"]
        widgets = {
            "quantity": forms.NumberInput(attrs={"step": "0.001", "min": "0.001"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["product"].queryset = (
            Product.objects.active().stock_items().with_category()
        )
        self.fields["product"].empty_label = _("اختر المنتج...")


StockMoveLineFormSet = inlineformset_factory(
    StockMove,
    StockMoveLine,
    form=StockMoveLineForm,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


# ============================================================
# Product
# ============================================================
class ProductForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "code", "barcode", "category", "product_type",

            # translations
            "name_ar", "name_en",
            "short_description_ar", "short_description_en",
            "description_ar", "description_en",

            # UOM
            "base_uom", "alt_uom", "alt_factor",

            # weight
            "weight_uom", "weight_per_base",

            # pricing
            "default_sale_price",

            # media & flags
            "image", "is_active", "is_published",
        ]

    def clean(self):
        """
        UX-level validation only.
        Heavy logic is in model.clean()
        """
        data = super().clean()
        ptype = data.get("product_type")

        if ptype == Product.ProductType.SERVICE:
            for f in ("alt_uom", "alt_factor", "weight_uom", "weight_per_base"):
                if data.get(f):
                    self.add_error(f, _("الخدمات لا تستخدم هذا الحقل."))

        return data


# ============================================================
# Warehouse
# ============================================================
class WarehouseForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = [
            "code",
            "name_ar", "name_en",
            "description_ar", "description_en",
            "is_active",
        ]


# ============================================================
# Product Category
# ============================================================
class ProductCategoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ProductCategory
        fields = [
            "name_ar", "name_en",
            "slug",
            "parent",
            "description_ar", "description_en",
            "is_active",
        ]

    def clean_slug(self):
        slug = self.cleaned_data.get("slug")
        if not slug:
            name = self.cleaned_data.get("name_en") or self.cleaned_data.get("name_ar")
            if name:
                slug = slugify(name, allow_unicode=True)
        return slug


# ============================================================
# Stock Location
# ============================================================
class StockLocationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = StockLocation
        fields = ["warehouse", "code", "name_ar", "name_en", "type", "is_active"]


# ============================================================
# Inventory Adjustment
# ============================================================
class InventoryAdjustmentStartForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = InventoryAdjustment
        fields = ["warehouse", "category", "location", "note"]
        widgets = {
            "note": forms.Textarea(attrs={"rows": 2}),
        }


class InventoryAdjustmentLineForm(forms.ModelForm):
    class Meta:
        model = InventoryAdjustmentLine
        fields = ["counted_qty"]
        widgets = {
            "counted_qty": forms.NumberInput(attrs={
                "class": "form-control form-control-sm",
                "step": "0.001",
            }),
        }


InventoryAdjustmentLineFormSet = inlineformset_factory(
    InventoryAdjustment,
    InventoryAdjustmentLine,
    form=InventoryAdjustmentLineForm,
    extra=0,
    can_delete=False,
)


# ============================================================
# Reorder Rule
# ============================================================
class ReorderRuleForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ReorderRule
        fields = [
            "product",
            "warehouse",
            "location",
            "min_qty",
            "target_qty",
            "is_active",
        ]

    def clean(self):
        data = super().clean()
        if (
            data.get("min_qty") is not None
            and data.get("target_qty") is not None
            and data["target_qty"] <= data["min_qty"]
        ):
            raise forms.ValidationError(
                _("الكمية المستهدفة يجب أن تكون أكبر من الحد الأدنى.")
            )
        return data
