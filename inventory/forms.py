# inventory/forms.py

from django import forms
from django.core.exceptions import ValidationError

from .models import StockMove, Product, StockLevel, ProductCategory


class StockMoveForm(forms.ModelForm):
    """
    Form لحركة المخزون مع تجهيز بسيط للـ widgets
    (نستخدمه مع القالب اللي فيه JS للتحكم في from/to).
    """

    class Meta:
        model = StockMove
        fields = [
            "product",
            "move_type",
            "from_warehouse",
            "from_location",
            "to_warehouse",
            "to_location",
            "quantity",
            "uom",
            "move_date",
            "status",
            "reference",
            "note",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # إضافة كلاس Bootstrap بشكل عام
        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")
            # نترك textarea/select على راحتهم، بس نضيف class عام
            field.widget.attrs["class"] = (css + " form-control").strip()

        # بعض الحقول نفضلها تظهر كـ select (لو مش ظاهرة من قبل)
        for name in ["move_type", "status", "product",
                     "from_warehouse", "from_location",
                     "to_warehouse", "to_location"]:
            field = self.fields.get(name)
            if field:
                css = field.widget.attrs.get("class", "")
                # نخليها form-select بدل form-control لو تحب
                # لكن عشان ما نلخبط باقي التصميم، نخليها كما هي الآن.
                field.widget.attrs["class"] = css.replace(
                    "form-control", ""
                ).strip() + " form-select"

        # تحسين بسيط لحقل التاريخ/الوقت
        if "move_date" in self.fields:
            self.fields["move_date"].widget.input_type = "datetime-local"





class ProductForm(forms.ModelForm):
    """
    Form لإدارة المنتجات في المخزون.
    الواجهة باللغة العربية، مع بعض التهيئة البسيطة للحقول.
    """

    class Meta:
        model = Product
        fields = [
            "category",
            "code",
            "name",
            "short_description",
            "description",
            "uom",
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
        self.fields["uom"].label = "وحدة القياس"
        self.fields["is_stock_item"].label = "يُتابَع في المخزون"
        self.fields["is_active"].label = "نشط"
        self.fields["is_published"].label = "منشور على الموقع/البوابة"

        self.fields["code"].help_text = "كود داخلي فريد، مثل: MZN-46-FRAME"
        self.fields["short_description"].help_text = "سطر واحد يظهر في القوائم والجداول."
        self.fields["description"].help_text = "وصف كامل للمنتج يمكن استخدامه في الموقع أو العروض."
        self.fields["uom"].help_text = "مثال: PCS, M, KG, SET"
        self.fields["is_stock_item"].help_text = "إذا تم تعطيله، لن يتم تتبع هذا المنتج في حركات المخزون."
        self.fields["is_active"].help_text = "إذا تم تعطيله، لن يظهر في المستندات الجديدة."
        self.fields["is_published"].help_text = "إذا تم تفعيله، يمكن عرضه في الموقع أو بوابة العملاء."

        # Add Bootstrap classes
        for name, field in self.fields.items():
            widget = field.widget
            css = widget.attrs.get("class", "")
            # checkbox نتركها على راحة Bootstrap (form-check)
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = (css + " form-check-input").strip()
            else:
                widget.attrs["class"] = (css + " form-control").strip()

    def clean_code(self):
        """
        Normalize product code:
        - strip spaces
        - uppercase

        This keeps all product codes in a consistent format.
        """
        code = self.cleaned_data.get("code", "") or ""
        code = code.strip().upper()
        return code



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