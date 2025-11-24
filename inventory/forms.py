# inventory/forms.py

from django import forms
from django.core.exceptions import ValidationError
from django.forms.models import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from uom.models import UnitOfMeasure
from .models import StockMove, Product, StockLevel, ProductCategory, InventorySettings, StockLocation, StockMoveLine


class StockMoveForm(forms.ModelForm):
    """
    فورم رأس حركة المخزون (بدون منتجات)
    """

    class Meta:
        model = StockMove
        fields = [
            "move_type",
            "from_warehouse",
            "from_location",
            "to_warehouse",
            "to_location",
            "move_date",
            "status",
            "reference",
            "note",
        ]
        widgets = {
            "move_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["move_type"].label = "نوع الحركة"
        self.fields["from_warehouse"].label = "من مخزن"
        self.fields["from_location"].label = "من موقع"
        self.fields["to_warehouse"].label = "إلى مخزن"
        self.fields["to_location"].label = "إلى موقع"
        self.fields["move_date"].label = "تاريخ/وقت الحركة"
        self.fields["status"].label = "الحالة"
        self.fields["reference"].label = "مرجع خارجي"
        self.fields["note"].label = "ملاحظات"

        for name, field in self.fields.items():
            widget = field.widget
            css = widget.attrs.get("class", "")
            if isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs["class"] = (css.replace("form-control", "") + " form-select").strip()
            elif isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = (css + " form-check-input").strip()
            else:
                widget.attrs["class"] = (css + " form-control").strip()

    def clean(self):
        cleaned = super().clean()

        from_wh = cleaned.get("from_warehouse")
        from_loc = cleaned.get("from_location")
        to_wh = cleaned.get("to_warehouse")
        to_loc = cleaned.get("to_location")

        # تأكد أن المواقع تتبع المخازن عند تعبئتها
        if from_loc and from_wh and from_loc.warehouse_id != from_wh.id:
            self.add_error("from_location", "الموقع المختار لا يتبع المخزن المحدد (من مخزن).")

        if to_loc and to_wh and to_loc.warehouse_id != to_wh.id:
            self.add_error("to_location", "الموقع المختار لا يتبع المخزن المحدد (إلى مخزن).")

        return cleaned




class StockMoveLineForm(forms.ModelForm):
    """
    فورم بند واحد في حركة المخزون (منتج + كمية + وحدة قياس)
    """

    class Meta:
        model = StockMoveLine
        fields = ["product", "quantity", "uom"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["product"].label = "المنتج"
        self.fields["quantity"].label = "الكمية"
        self.fields["uom"].label = "وحدة القياس"

        # وحدات قياس مفعّلة فقط
        self.fields["uom"].queryset = UnitOfMeasure.objects.filter(is_active=True)

        for name, field in self.fields.items():
            widget = field.widget
            css = widget.attrs.get("class", "")
            if isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs["class"] = (css.replace("form-control", "") + " form-select").strip()
            else:
                widget.attrs["class"] = (css + " form-control").strip()

    def clean_quantity(self):
        qty = self.cleaned_data.get("quantity")
        if qty is None or qty <= 0:
            raise ValidationError("الكمية يجب أن تكون أكبر من صفر.")
        return qty

    def clean(self):
        cleaned = super().clean()
        product = cleaned.get("product")
        uom = cleaned.get("uom")

        if product and uom:
            allowed_uoms = [product.base_uom]
            if product.alt_uom:
                allowed_uoms.append(product.alt_uom)
            if uom not in allowed_uoms:
                raise ValidationError(
                    "وحدة القياس المختارة لا تتوافق مع إعدادات هذا المنتج. "
                    "يُرجى اختيار وحدة من الوحدات المحددة للمنتج."
                )

        return cleaned


StockMoveLineFormSet = inlineformset_factory(
    StockMove,
    StockMoveLine,
    form=StockMoveLineForm,
    extra=3,         # عدد صفوف جديدة افتراضية
    can_delete=True, # يسمح بحذف البنود
)






class ProductForm(forms.ModelForm):
    """
    Form for managing products in inventory.
    Arabic UI labels, with simple Bootstrap integration.
    """

    class Meta:
        model = Product
        fields = [
            "category",
            "code",
            "name",
            "short_description",
            "description",
            # UoM fields
            "base_uom",
            "alt_uom",
            "alt_factor",
            "weight_uom",
            "weight_per_base",
            # Flags
            "is_stock_item",
            "is_active",
            "is_published",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Arabic labels & help texts for UI
        self.fields["category"].label = "التصنيف"
        self.fields["code"].label = "كود المنتج"
        self.fields["name"].label = "اسم المنتج"
        self.fields["short_description"].label = "وصف مختصر"
        self.fields["description"].label = "وصف تفصيلي"

        self.fields["base_uom"].label = "وحدة القياس الأساسية"
        self.fields["alt_uom"].label = "وحدة بديلة"
        self.fields["alt_factor"].label = "عامل تحويل الوحدة البديلة"
        self.fields["weight_uom"].label = "وحدة الوزن"
        self.fields["weight_per_base"].label = "الوزن لكل وحدة أساسية"

        self.fields["is_stock_item"].label = "يُتابَع في المخزون"
        self.fields["is_active"].label = "نشط"
        self.fields["is_published"].label = "منشور على الموقع/البوابة"

        self.fields["code"].help_text = "كود داخلي فريد، مثل: MZN-46-FRAME"
        self.fields["short_description"].help_text = "سطر واحد يظهر في القوائم والجداول."
        self.fields["description"].help_text = "وصف كامل للمنتج يمكن استخدامه في الموقع أو العروض."

        self.fields["base_uom"].help_text = "الوحدة الأساسية للمخزون، مثل: M للمتر، PCS للقطعة."
        self.fields["alt_uom"].help_text = "وحدة أخرى للبيع أو الشراء (مثل: لفة، كرتون)."
        self.fields["alt_factor"].help_text = (
            "كم تساوي 1 وحدة بديلة من الوحدة الأساسية. "
            "مثال: إذا الأساس متر والبديلة لفة 6م، اكتب 6."
        )
        self.fields["weight_uom"].help_text = "الوحدة المستخدمة للوزن، مثل: KG."
        self.fields["weight_per_base"].help_text = (
            "الوزن في وحدة الوزن لكل 1 من الوحدة الأساسية. "
            "مثال: إذا الأساس متر ووحدة الوزن كجم، هذا الحقل هو كجم/م."
        )

        self.fields["is_stock_item"].help_text = "إذا تم تعطيله، لن يتم تتبع هذا المنتج في حركات المخزون."
        self.fields["is_active"].help_text = "إذا تم تعطيله، لن يظهر في المستندات الجديدة."
        self.fields["is_published"].help_text = "إذا تم تفعيله، يمكن عرضه في الموقع أو بوابة العملاء."

        # Limit UoM fields to active units
        active_uoms = UnitOfMeasure.objects.filter(is_active=True)
        if "base_uom" in self.fields:
            self.fields["base_uom"].queryset = active_uoms
        if "alt_uom" in self.fields:
            self.fields["alt_uom"].queryset = active_uoms
        if "weight_uom" in self.fields:
            self.fields["weight_uom"].queryset = active_uoms

        # Add Bootstrap classes
        for name, field in self.fields.items():
            widget = field.widget
            css = widget.attrs.get("class", "")
            # Keep checkboxes as form-check-input
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = (css + " form-check-input").strip()
            else:
                widget.attrs["class"] = (css + " form-control").strip()

        # Optional: numeric field tuning
        if "alt_factor" in self.fields:
            self.fields["alt_factor"].widget.attrs.setdefault("step", "0.000001")
            self.fields["alt_factor"].widget.attrs.setdefault("min", "0")
        if "weight_per_base" in self.fields:
            self.fields["weight_per_base"].widget.attrs.setdefault("step", "0.000001")
            self.fields["weight_per_base"].widget.attrs.setdefault("min", "0")

    def clean_code(self):
        """
        Normalize product code:
        - strip spaces
        - uppercase
        """
        code = self.cleaned_data.get("code", "") or ""
        code = code.strip().upper()
        return code

    def clean_alt_factor(self):
        """
        Ensure alt_factor is only set when alt_uom is provided and vice versa.
        """
        alt_uom = self.cleaned_data.get("alt_uom")
        alt_factor = self.cleaned_data.get("alt_factor")

        if alt_uom and not alt_factor:
            raise forms.ValidationError("يجب تحديد عامل التحويل عند اختيار وحدة بديلة.")
        if alt_factor and not alt_uom:
            raise forms.ValidationError("لا يمكن تعيين عامل تحويل بدون وحدة بديلة.")
        return alt_factor



class StockLevelForm(forms.ModelForm):
    """
    Form لإدارة مستوى المخزون لمنتج معيّن في مخزن/موقع معيّن.
    - في الإنشاء: يمكن اختيار المنتج + المخزن + الموقع.
    - في التعديل: نعرض المنتج + المخزن + الموقع لكن بدون تعديل (disabled).
    """

    class Meta:
        model = StockLevel
        fields = [
            "product",
            "warehouse",
            "location",
            "quantity_on_hand",
            "quantity_reserved",
            "min_stock",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ==== عناوين عربية ====
        self.fields["product"].label = "المنتج"
        self.fields["warehouse"].label = "المخزن"
        self.fields["location"].label = "الموقع داخل المخزن"

        self.fields["quantity_on_hand"].label = "الكمية الفعلية المتوفرة"
        self.fields["quantity_reserved"].label = "الكمية المحجوزة (للطلبيات)"
        self.fields["min_stock"].label = "الحد الأدنى / مستوى إعادة الطلب"

        self.fields["quantity_on_hand"].help_text = "الكمية الموجودة حاليًا على الرف في هذا المخزن/الموقع."
        self.fields["quantity_reserved"].help_text = "كمية محجوزة لطلبيات لم تُسَلَّم بعد."
        self.fields["min_stock"].help_text = "إذا نزل المخزون عن هذا الحد، يعتبر بحاجة لإعادة طلب."

        # ==== Bootstrap classes ====
        for name, field in self.fields.items():
            widget = field.widget
            css = widget.attrs.get("class", "")
            if isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs["class"] = (css + " form-select").strip()
            else:
                widget.attrs["class"] = (css + " form-control").strip()

        # ==== في حالة التعديل: نمنع تعديل المنتج/المخزن/الموقع ====
        if self.instance and self.instance.pk:
            for name in ["product", "warehouse", "location"]:
                field = self.fields.get(name)
                if field:
                    field.disabled = True
                    field.required = False  # عشان ما يشتكي الفاليديشن

    def clean(self):
        """
        منع تكرار مستوى المخزون لنفس (المنتج + المخزن + الموقع).
        مفيدة خاصةً في حالة الإنشاء.
        """
        cleaned = super().clean()
        product = cleaned.get("product")
        warehouse = cleaned.get("warehouse")
        location = cleaned.get("location")

        if not self.instance.pk and product and warehouse and location:
            exists = StockLevel.objects.filter(
                product=product,
                warehouse=warehouse,
                location=location,
            ).exists()
            if exists:
                raise ValidationError(
                    "يوجد بالفعل مستوى مخزون لهذا المنتج في هذا المخزن وهذا الموقع."
                )

        return cleaned



class ProductCategoryForm(forms.ModelForm):
    """
    Form لإدارة تصنيفات المنتجات في نظام المخزون.
    """

    class Meta:
        model = ProductCategory
        fields = ["slug", "name", "description", "parent", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["slug"].label = "المعرّف (Slug)"
        self.fields["name"].label = "اسم التصنيف"
        self.fields["description"].label = "الوصف"
        self.fields["parent"].label = "التصنيف الأب"
        self.fields["is_active"].label = "نشط"

        self.fields["slug"].help_text = "معرّف بدون مسافات، يُستخدم في الروابط (مثال: mazoon-46-system)."
        self.fields["parent"].help_text = "اختياري: لربط هذا التصنيف كتحت تصنيف من تصنيف آخر."

        # ترتيب بسيط في الـ Select للتصنيف الأب (اختياري)
        self.fields["parent"].queryset = ProductCategory.objects.order_by("name")

        # Bootstrap classes
        for name, field in self.fields.items():
            widget = field.widget
            css = widget.attrs.get("class", "")
            if isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs["class"] = (css + " form-select").strip()
            elif isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = (css + " form-check-input").strip()
            else:
                widget.attrs["class"] = (css + " form-control").strip()




class InventorySettingsForm(forms.ModelForm):
    class Meta:
        model = InventorySettings
        fields = [
            "stock_move_in_prefix",
            "stock_move_out_prefix",
            "stock_move_transfer_prefix",
        ]
        widgets = {
            "stock_move_in_prefix": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "dir": "ltr",
                    "placeholder": "IN- أو STM-IN- مثلاً",
                }
            ),
            "stock_move_out_prefix": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "dir": "ltr",
                    "placeholder": "OUT- أو STM-OUT- مثلاً",
                }
            ),
            "stock_move_transfer_prefix": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "dir": "ltr",
                    "placeholder": "TRF- أو STM-TRF- مثلاً",
                }
            ),
        }
        labels = {
            "stock_move_in_prefix": _("بادئة حركات الوارد (IN)"),
            "stock_move_out_prefix": _("بادئة حركات الصادر (OUT)"),
            "stock_move_transfer_prefix": _("بادئة حركات التحويل (TRANSFER)"),
        }
        help_texts = {
            "stock_move_in_prefix": _(
                "تُستخدم كبادئة لحركات المخزون الواردة. "
                "مثال: IN- أو STM-IN-. سيتم استخدامها داخل نمط ترقيم يحتوي على {seq}."
            ),
            "stock_move_out_prefix": _(
                "تُستخدم كبادئة لحركات المخزون الصادرة. "
                "مثال: OUT- أو STM-OUT-."
            ),
            "stock_move_transfer_prefix": _(
                "تُستخدم كبادئة لحركات تحويل المخزون بين المواقع. "
                "مثال: TRF- أو STM-TRF-."
            ),
        }

    # ====== Helper للتنظيف ======
    def _clean_prefix(self, field_name: str) -> str:
        value = self.cleaned_data.get(field_name, "") or ""
        # نشيل المسافات ونخليها كابيتال
        return value.strip().upper()

    def clean_stock_move_in_prefix(self):
        return self._clean_prefix("stock_move_in_prefix")

    def clean_stock_move_out_prefix(self):
        return self._clean_prefix("stock_move_out_prefix")

    def clean_stock_move_transfer_prefix(self):
        return self._clean_prefix("stock_move_transfer_prefix")