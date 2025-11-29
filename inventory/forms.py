# inventory/forms.py

from django import forms
from django.core.exceptions import ValidationError
from django.forms.models import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from uom.models import UnitOfMeasure
from .models import (
    StockMove,
    Product,
    StockLevel,
    ProductCategory,
    InventorySettings,
    StockLocation,
    StockMoveLine,
)


class StockMoveForm(forms.ModelForm):
    """
    فورم رأس حركة المخزون (بدون المنتجات).
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

        # عناوين عربية (مع قابلية الترجمة)
        self.fields["move_type"].label = _("نوع الحركة")
        self.fields["from_warehouse"].label = _("من مخزن")
        self.fields["from_location"].label = _("من موقع")
        self.fields["to_warehouse"].label = _("إلى مخزن")
        self.fields["to_location"].label = _("إلى موقع")
        self.fields["move_date"].label = _("تاريخ/وقت الحركة")
        self.fields["status"].label = _("الحالة")
        self.fields["reference"].label = _("مرجع خارجي")
        self.fields["note"].label = _("ملاحظات")

        # Bootstrap classes
        for name, field in self.fields.items():
            widget = field.widget
            css = widget.attrs.get("class", "")
            if isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs["class"] = (
                    css.replace("form-control", "") + " form-select"
                ).strip()
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
            self.add_error(
                "from_location",
                _("الموقع المختار لا يتبع المخزن المحدد في حقل (من مخزن)."),
            )

        if to_loc and to_wh and to_loc.warehouse_id != to_wh.id:
            self.add_error(
                "to_location",
                _("الموقع المختار لا يتبع المخزن المحدد في حقل (إلى مخزن)."),
            )

        return cleaned


class StockMoveLineForm(forms.ModelForm):
    """
    فورم بند واحد في حركة المخزون (منتج + كمية + وحدة قياس).

    - يقيّد uom على الوحدة الأساسية + البديلة للمنتج.
    - يضبط افتراضيًا وحدة القياس على base_uom لو ما اختار المستخدم شيء.
    """

    class Meta:
        model = StockMoveLine
        fields = ["product", "quantity", "uom"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["product"].label = _("المنتج")
        self.fields["quantity"].label = _("الكمية")
        self.fields["uom"].label = _("وحدة القياس")

        # مبدئياً: كل الوحدات المفعّلة
        if "uom" in self.fields:
            self.fields["uom"].queryset = UnitOfMeasure.objects.filter(
                is_active=True
            )

        # نحاول نحدد المنتج لهذا السطر (من POST أو instance أو initial)
        product = self._get_current_product()
        if product:
            self._limit_uom_to_product(product)

        # Bootstrap classes
        for name, field in self.fields.items():
            widget = field.widget
            css = widget.attrs.get("class", "")
            if isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs["class"] = (
                    css.replace("form-control", "") + " form-select"
                ).strip()
            elif isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = (css + " form-check-input").strip()
            else:
                widget.attrs["class"] = (css + " form-control").strip()

    # ============================
    # Helpers
    # ============================

    def _get_current_product(self):
        """
        يحاول يستنتج المنتج لهذا السطر:
        - لو الفورم bound: من self.data
        - لو instance موجود: من instance.product
        - لو initial فيه product: يستخدمه
        """
        product = None

        if self.is_bound:
            product_key = self.add_prefix("product")  # مثال: form-0-product
            product_id = self.data.get(product_key)
            if product_id:
                try:
                    product = Product.objects.get(pk=product_id)
                except Product.DoesNotExist:
                    product = None
        else:
            # في حالة edit أو initial قبل POST
            if self.instance.pk and self.instance.product_id:
                product = self.instance.product
            elif "product" in self.initial:
                init_val = self.initial["product"]
                if isinstance(init_val, Product):
                    product = init_val
                else:
                    try:
                        product = Product.objects.get(pk=init_val)
                    except Product.DoesNotExist:
                        product = None

        return product

    def _limit_uom_to_product(self, product: Product):
        """
        يقيّد queryset لحقل uom على:
        - base_uom
        - alt_uom (لو موجودة)
        ويضبط initial على base_uom لو ما فيه اختيار من المستخدم.
        """
        allowed = [product.base_uom]
        if product.alt_uom_id:
            allowed.append(product.alt_uom)

        qs = UnitOfMeasure.objects.filter(pk__in=[u.pk for u in allowed])
        self.fields["uom"].queryset = qs

        # لو السطر جديد وما فيه uom جاية من POST → نخلي الافتراضي base_uom
        uom_key = self.add_prefix("uom")
        has_user_uom = self.is_bound and self.data.get(uom_key)

        if not self.instance.pk and not has_user_uom:
            self.fields["uom"].initial = product.base_uom

    # ============================
    # Validation
    # ============================

    def clean_quantity(self):
        qty = self.cleaned_data.get("quantity")
        if qty is None or qty <= 0:
            raise ValidationError(_("الكمية يجب أن تكون أكبر من صفر."))
        return qty

    def clean(self):
        cleaned = super().clean()
        product = cleaned.get("product")
        uom = cleaned.get("uom")

        if not product:
            return cleaned

        allowed_uoms = [product.base_uom]
        if product.alt_uom:
            allowed_uoms.append(product.alt_uom)

        # لو ما اختار وحدة → نخليها تلقائيًا base_uom
        if uom is None:
            cleaned["uom"] = product.base_uom
            uom = cleaned["uom"]

        if uom not in allowed_uoms:
            raise ValidationError(
                _(
                    "وحدة القياس المختارة لا تتوافق مع إعدادات هذا المنتج. "
                    "يُرجى اختيار وحدة من الوحدات المحددة للمنتج."
                )
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
    فورم إدارة المنتجات في نظام المخزون.
    واجهة عربية مع تكامل بسيط مع Bootstrap.
    """

    class Meta:
        model = Product
        fields = [
            "category",
            "product_type",  # 👈 جديد
            "code",
            "name",
            "short_description",
            # الأسعار
            "default_sale_price",
            "default_cost_price",
            "description",
            # UoM fields
            "base_uom",
            "alt_uom",
            "alt_factor",
            "weight_uom",
            "weight_per_base",
            # نوع المنتج وأعلام الحالة
            "product_type",
            "is_stock_item",
            "is_active",
            "is_published",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # عناوين عربية
        self.fields["category"].label = _("التصنيف")
        self.fields["product_type"].label = "نوع المنتج"
        self.fields["code"].label = _("كود المنتج")
        self.fields["name"].label = _("اسم المنتج")
        self.fields["short_description"].label = _("وصف مختصر")
        self.fields["description"].label = _("وصف تفصيلي")

        self.fields["default_sale_price"].label = _("سعر البيع الافتراضي")
        self.fields["default_cost_price"].label = _("سعر التكلفة التقريبي")

        self.fields["base_uom"].label = _("وحدة القياس الأساسية")
        self.fields["alt_uom"].label = _("وحدة بديلة")
        self.fields["alt_factor"].label = _("عامل تحويل الوحدة البديلة")
        self.fields["weight_uom"].label = _("وحدة الوزن")
        self.fields["weight_per_base"].label = _("الوزن لكل وحدة أساسية")

        self.fields["product_type"].label = _("نوع المنتج")
        self.fields["is_stock_item"].label = _("يُتابَع في المخزون")
        self.fields["is_active"].label = _("نشط")
        self.fields["is_published"].label = _("منشور على الموقع/البوابة")

        # Help texts
        self.fields["code"].help_text = _(
            "كود داخلي فريد، مثل: MZN-46-FRAME."
        )
        self.fields["product_type"].help_text = (
            "يحدد سلوك المنتج في المخزون والتقارير (مثل: صنف مخزني، خدمة، أصل ثابت...)."
        )
        self.fields["short_description"].help_text = _(
            "سطر واحد يظهر في القوائم والجداول."
        )
        self.fields["description"].help_text = _(
            "وصف كامل للمنتج يمكن استخدامه في الموقع أو العروض."
        )

        self.fields["default_sale_price"].help_text = _(
            "سعر البيع الداخلي الافتراضي لكل وحدة القياس الأساسية."
        )
        self.fields["default_cost_price"].help_text = _(
            "سعر التكلفة التقريبي يستخدم للتقارير الداخلية وتقدير تكلفة المخزون."
        )

        self.fields["base_uom"].help_text = _(
            "الوحدة الأساسية للمخزون، مثل: M للمتر، PCS للقطعة."
        )
        self.fields["alt_uom"].help_text = _(
            "وحدة أخرى للبيع أو الشراء (مثل: لفة، كرتون)."
        )
        self.fields["alt_factor"].help_text = _(
            "كم تساوي 1 وحدة بديلة من الوحدة الأساسية. "
            "مثال: إذا الأساس متر والبديلة لفة 6م، اكتب 6."
        )
        self.fields["weight_uom"].help_text = _(
            "الوحدة المستخدمة للوزن، مثل: KG."
        )
        self.fields["weight_per_base"].help_text = _(
            "الوزن في وحدة الوزن لكل 1 من الوحدة الأساسية. "
            "مثال: إذا الأساس متر ووحدة الوزن كجم، هذا الحقل هو كجم/م."
        )

        self.fields["product_type"].help_text = _(
            "يحدد إذا كان المنتج صنف مخزني، خدمة أو مستهلكات."
        )
        self.fields["is_stock_item"].help_text = _(
            "إذا تم تعطيله، لن يتم تتبع هذا المنتج في حركات المخزون."
        )
        self.fields["is_active"].help_text = _(
            "إذا تم تعطيله، لن يظهر في المستندات الجديدة."
        )
        self.fields["is_published"].help_text = _(
            "إذا تم تفعيله، يمكن عرضه في الموقع أو بوابة العملاء."
        )

        # حصر وحدات القياس على الوحدات النشطة
        active_uoms = UnitOfMeasure.objects.filter(is_active=True)
        if "base_uom" in self.fields:
            self.fields["base_uom"].queryset = active_uoms
        if "alt_uom" in self.fields:
            self.fields["alt_uom"].queryset = active_uoms
        if "weight_uom" in self.fields:
            self.fields["weight_uom"].queryset = active_uoms

        # Bootstrap classes
        for name, field in self.fields.items():
            widget = field.widget
            css = widget.attrs.get("class", "")
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = (css + " form-check-input").strip()
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs["class"] = (
                    css.replace("form-control", "") + " form-select"
                ).strip()
            else:
                widget.attrs["class"] = (css + " form-control").strip()

        # إعداد بعض الخصائص الرقمية
        if "default_sale_price" in self.fields:
            self.fields["default_sale_price"].widget.attrs.setdefault("step", "0.001")
            self.fields["default_sale_price"].widget.attrs.setdefault("min", "0")
        if "default_cost_price" in self.fields:
            self.fields["default_cost_price"].widget.attrs.setdefault("step", "0.001")
            self.fields["default_cost_price"].widget.attrs.setdefault("min", "0")

        if "alt_factor" in self.fields:
            self.fields["alt_factor"].widget.attrs.setdefault("step", "0.000001")
            self.fields["alt_factor"].widget.attrs.setdefault("min", "0")
        if "weight_per_base" in self.fields:
            self.fields["weight_per_base"].widget.attrs.setdefault("step", "0.000001")
            self.fields["weight_per_base"].widget.attrs.setdefault("min", "0")

    def clean_code(self):
        """
        تطبيع كود المنتج:
        - إزالة المسافات
        - تحويل إلى حروف كبيرة
        """
        code = self.cleaned_data.get("code", "") or ""
        code = code.strip().upper()
        return code

    def clean_alt_factor(self):
        """
        التأكد من أن alt_factor مضبوط فقط عند وجود alt_uom والعكس.
        """
        alt_uom = self.cleaned_data.get("alt_uom")
        alt_factor = self.cleaned_data.get("alt_factor")

        if alt_uom and not alt_factor:
            raise forms.ValidationError(
                _("يجب تحديد عامل التحويل عند اختيار وحدة بديلة.")
            )
        if alt_factor and not alt_uom:
            raise forms.ValidationError(
                _("لا يمكن تعيين عامل تحويل بدون وحدة بديلة.")
            )
        return alt_factor

    def clean_default_sale_price(self):
        value = self.cleaned_data.get("default_sale_price") or 0
        if value < 0:
            raise forms.ValidationError(_("لا يمكن أن يكون سعر البيع سالباً."))
        return value

    def clean_default_cost_price(self):
        value = self.cleaned_data.get("default_cost_price") or 0
        if value < 0:
            raise forms.ValidationError(_("لا يمكن أن يكون سعر التكلفة سالباً."))
        return value


class StockLevelForm(forms.ModelForm):
    """
    فورم لإدارة مستوى المخزون لمنتج معيّن في مخزن/موقع معيّن.
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

        # عناوين عربية
        self.fields["product"].label = _("المنتج")
        self.fields["warehouse"].label = _("المخزن")
        self.fields["location"].label = _("الموقع داخل المخزن")

        self.fields["quantity_on_hand"].label = _("الكمية الفعلية المتوفرة")
        self.fields["quantity_reserved"].label = _("الكمية المحجوزة (للطلبيات)")
        self.fields["min_stock"].label = _("الحد الأدنى / مستوى إعادة الطلب")

        self.fields["quantity_on_hand"].help_text = _(
            "الكمية الموجودة حاليًا على الرف في هذا المخزن/الموقع."
        )
        self.fields["quantity_reserved"].help_text = _(
            "كمية محجوزة لطلبيات لم تُسَلَّم بعد."
        )
        self.fields["min_stock"].help_text = _(
            "إذا نزل المخزون عن هذا الحد، يعتبر بحاجة لإعادة طلب."
        )

        # Bootstrap classes
        for name, field in self.fields.items():
            widget = field.widget
            css = widget.attrs.get("class", "")
            if isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs["class"] = (css + " form-select").strip()
            else:
                widget.attrs["class"] = (css + " form-control").strip()

        # في حالة التعديل: نمنع تعديل المنتج/المخزن/الموقع
        if self.instance and self.instance.pk:
            for name in ["product", "warehouse", "location"]:
                field = self.fields.get(name)
                if field:
                    field.disabled = True
                    field.required = False  # حتى لا يشتكي الفاليديشن

    # ============================
    # Validation للقيم غير السالبة
    # ============================

    def clean_quantity_on_hand(self):
        value = self.cleaned_data.get("quantity_on_hand")
        if value is not None and value < 0:
            raise ValidationError(_("لا يمكن أن تكون الكمية المتوفرة سالبة."))
        return value

    def clean_quantity_reserved(self):
        value = self.cleaned_data.get("quantity_reserved")
        if value is not None and value < 0:
            raise ValidationError(_("لا يمكن أن تكون الكمية المحجوزة سالبة."))
        return value

    def clean_min_stock(self):
        value = self.cleaned_data.get("min_stock")
        if value is not None and value < 0:
            raise ValidationError(_("لا يمكن أن يكون الحد الأدنى للمخزون سالباً."))
        return value

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
                    _(
                        "يوجد بالفعل مستوى مخزون لهذا المنتج في هذا المخزن وهذا الموقع."
                    )
                )

        return cleaned


class ProductCategoryForm(forms.ModelForm):
    """
    فورم لإدارة تصنيفات المنتجات في نظام المخزون.
    """

    class Meta:
        model = ProductCategory
        fields = ["slug", "name", "description", "parent", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["slug"].label = _("المعرّف (Slug)")
        self.fields["name"].label = _("اسم التصنيف")
        self.fields["description"].label = _("الوصف")
        self.fields["parent"].label = _("التصنيف الأب")
        self.fields["is_active"].label = _("نشط")

        self.fields["slug"].help_text = _(
            "معرّف بدون مسافات، يُستخدم في الروابط (مثال: mazoon-46-system)."
        )
        self.fields["parent"].help_text = _(
            "اختياري: لربط هذا التصنيف كتحت تصنيف من تصنيف آخر."
        )

        # ترتيب بسيط في الـ Select للتصنيف الأب
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
    """
    فورم إعدادات المخزون العامة (بادئات ترقيم حركات المخزون).
    """

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
                    "placeholder": _("IN- أو STM-IN- مثلاً"),
                }
            ),
            "stock_move_out_prefix": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "dir": "ltr",
                    "placeholder": _("OUT- أو STM-OUT- مثلاً"),
                }
            ),
            "stock_move_transfer_prefix": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "dir": "ltr",
                    "placeholder": _("TRF- أو STM-TRF- مثلاً"),
                }
            ),
        }
        labels = {
            "stock_move_in_prefix": _(
                "بادئة حركات الوارد (IN)"
            ),
            "stock_move_out_prefix": _(
                "بادئة حركات الصادر (OUT)"
            ),
            "stock_move_transfer_prefix": _(
                "بادئة حركات التحويل (TRANSFER)"
            ),
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

    # ===== Helper للتنظيف =====
    def _clean_prefix(self, field_name: str) -> str:
        value = self.cleaned_data.get(field_name, "") or ""
        # نشيل المسافات ونخليها حروف كبيرة
        return value.strip().upper()

    def clean_stock_move_in_prefix(self):
        return self._clean_prefix("stock_move_in_prefix")

    def clean_stock_move_out_prefix(self):
        return self._clean_prefix("stock_move_out_prefix")

    def clean_stock_move_transfer_prefix(self):
        return self._clean_prefix("stock_move_transfer_prefix")
