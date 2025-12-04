# sales/forms.py

from django import forms
from django.forms.models import BaseInlineFormSet, inlineformset_factory
from django.utils.translation import gettext_lazy as _

from inventory.models import Product
from .models import SalesDocument, DeliveryNote, SalesLine, DeliveryLine


# ===================================================================
# فورم مستند المبيعات (الهيدر)
# ===================================================================


class SalesDocumentForm(forms.ModelForm):
    """
    فورم مستند المبيعات (الهيدر):

    - لا نعرض حقل kind للمستخدم.
    - عند إنشاء مستند جديد نثبّت النوع = QUOTATION.
    """

    class Meta:
        model = SalesDocument
        # ملاحظة: kind غير موجود هنا عمداً
        fields = ["contact", "date", "due_date", "notes", "customer_notes"]
        widgets = {
            "contact": forms.Select(attrs={"class": "form-select"}),
            "date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control",
                }
            ),
            "due_date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "rows": 3,
                    "class": "form-control",
                }
            ),
            "customer_notes": forms.Textarea(
                attrs={
                    "rows": 3,
                    "class": "form-control",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        """
        عند إنشاء فورم جديد:
        - لو instance جديد → نثبت kind=QUOTATION قبل الفالديشن.
        """
        super().__init__(*args, **kwargs)

        if not self.instance.pk:
            self.instance.kind = SalesDocument.Kind.QUOTATION

    def clean(self):
        """
        التحقق من أن تاريخ الاستحقاق لا يسبق تاريخ المستند.
        """
        cleaned_data = super().clean()
        date = cleaned_data.get("date")
        due_date = cleaned_data.get("due_date")

        if date and due_date and due_date < date:
            self.add_error(
                "due_date",
                _("لا يمكن أن يكون تاريخ الاستحقاق قبل تاريخ المستند."),
            )

        return cleaned_data


# ===================================================================
# فورم مذكرة التسليم (الهيدر)
# ===================================================================


class DeliveryNoteForm(forms.ModelForm):
    """
    فورم مذكرة التسليم (الهيدر):

    - في المذكرات المستقلة: المستخدم يختار contact يدوياً.
    - في المذكرات المرتبطة بأمر بيع: الفيو يملأ contact من order.contact
      ويمكن للقالب أن يعرضه فقط بدون تعديل.
    """

    class Meta:
        model = DeliveryNote
        fields = ["contact", "date", "notes"]
        widgets = {
            "contact": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "rows": 3,
                    "class": "form-control",
                }
            ),
        }


# ===================================================================
# DeliveryLineForm + Inline Formset
# ===================================================================


class DeliveryLineForm(forms.ModelForm):
    """
    فورم سطر تسليم واحد ضمن مذكرة التسليم:

    - product_code حقل مساعد للبحث بالكود (يُستخدم مع JS + API).
    - product (FK) لا يظهر للمستخدم، ويُعبّأ تلقائياً بعد اختيار المنتج.
    """

    product_code = forms.CharField(
        label=_("رمز المنتج"),
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "autocomplete": "off",
            }
        ),
    )

    class Meta:
        model = DeliveryLine
        fields = ["product", "description", "quantity", "uom"]
        widgets = {
            "product": forms.HiddenInput(),
            "description": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                }
            ),
            "quantity": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm text-end",
                    "step": "0.001",
                    "min": "0",
                }
            ),
            "uom": forms.Select(
                attrs={
                    "class": "form-select form-select-sm",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        """
        عند تحميل السطر:
        - لو السطر مرتبط بمنتج → نعبّي product_code من product.code.
        """
        super().__init__(*args, **kwargs)

        product = getattr(self.instance, "product", None)
        if product and hasattr(product, "code") and not self.initial.get("product_code"):
            self.initial["product_code"] = product.code

    def clean(self):
        """
        منطق الفالديشن لسطر التسليم:

        - لو الفورم لم يتغيّر نهائياً → نرجع البيانات كما هي (الفورمست يتكفّل).
        - لو فيه product_code بدون product → نحاول نبحث عن المنتج بالكود.
        - لو الكمية > 0 ولا يوجد منتج ولا وصف → نرمي خطأ.
        """
        cleaned_data = super().clean()

        product = cleaned_data.get("product")
        description = cleaned_data.get("description")
        quantity = cleaned_data.get("quantity") or 0
        code = cleaned_data.get("product_code")

        # لو الفورم ما تغيّر، نخليه يمر والفورمست يتصرف
        if not self.has_changed():
            return cleaned_data

        # 1) محاولة ربط المنتج عن طريق الكود لو المنتج غير محدد
        if code and not product:
            try:
                product = Product.objects.get(code__iexact=code.strip())
                cleaned_data["product"] = product
                self.instance.product = product

                # لو ما فيه وصف، نستخدم اسم المنتج تلقائياً
                if not description:
                    cleaned_data["description"] = product.name
                    self.instance.description = product.name

            except Product.DoesNotExist:
                self.add_error(
                    "product_code",
                    _("لم يتم العثور على منتج بهذا الكود."),
                )
                return cleaned_data

        # 2) التحقق من أن السطر له معنى
        if quantity > 0 and not (product or description):
            raise forms.ValidationError(
                _("يجب اختيار منتج أو كتابة وصف لهذا السطر."),
            )

        return cleaned_data


class BaseDeliveryLineFormSet(BaseInlineFormSet):
    """
    Inline formset لبنود التسليم:

    - نتأكد أن على الأقل يوجد سطر واحد له معنى (منتج / وصف / كمية).
    """

    def clean(self):
        super().clean()

        has_valid_line = False

        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue

            # نتجاهل السطور المحددة للحذف
            if form.cleaned_data.get("DELETE", False):
                continue

            product = form.cleaned_data.get("product")
            description = form.cleaned_data.get("description")
            quantity = form.cleaned_data.get("quantity") or 0

            if product or description or quantity:
                has_valid_line = True

        if self.total_form_count() > 0 and not has_valid_line:
            raise forms.ValidationError(
                _("يجب إضافة سطر تسليم واحد على الأقل."),
            )


DeliveryLineFormSet = inlineformset_factory(
    parent_model=DeliveryNote,
    model=DeliveryLine,
    form=DeliveryLineForm,
    formset=BaseDeliveryLineFormSet,
    extra=5,
    can_delete=True,
    min_num=0,
    validate_min=False,
)


# ===================================================================
# SalesLineForm + Inline Formset
# ===================================================================


class SalesLineForm(forms.ModelForm):
    """
    فورم سطر مبيعات واحد ضمن مستند المبيعات:

    - product_code حقل يساعد في البحث بالكود الداخلي (يظهر للمستخدم).
    - product_name حقل واجهة فقط لعرض اسم المنتج (يُعبأ من الـ JS).
    - product (FK) مخفي، ويُعبّأ تلقائياً بعد اختيار الكود.
    - uom_kind حقل مخفي لحفظ نوع الوحدة (أساسية/بديلة) بين الطلبات.
    - line_total يُحسب في الموديل، لذلك لا يظهر في الفورم.
    """

    product_code = forms.CharField(
        label=_("رمز المنتج"),
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm",
                "autocomplete": "off",
            }
        ),
        help_text=_("أدخل الكود الداخلي للمنتج للبحث السريع."),
    )

    # 👈 حقل واجهة للاسم (يرجع بعد الفالديشن)
    product_name = forms.CharField(
        label=_("اسم المنتج"),
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-sm product-name-input",
                "autocomplete": "off",
                "readonly": "readonly",
                "placeholder": _("اسم المنتج"),
            }
        ),
    )

    # 👈 حقل نوع الوحدة (لو موجود في الموديل اضفه في Meta أيضاً)
    uom_kind = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = SalesLine
        fields = [
            "product",
            "description",
            "quantity",
            "unit_price",
            "discount_percent",
            "uom_kind",  # 👈 لو ما عندك هذا الحقل في الموديل اشطبه من هنا وخله بس كحقل فورم
        ]
        widgets = {
            # المنتج مخفي، والاختيار يتم عبر product_code + JS + API
            "product": forms.HiddenInput(),
            "description": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                }
            ),
            "quantity": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm text-end",
                    "step": "0.001",
                    "min": "0",
                }
            ),
            "unit_price": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm text-end",
                    "step": "0.001",
                    "min": "0",
                }
            ),
            "discount_percent": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm text-end",
                    "step": "0.01",
                    "min": "0",
                    "max": "100",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        """
        عند تحميل السطر:
        - لو السطر مرتبط بمنتج → نعبّي product_code و product_name من المنتج.
        """
        super().__init__(*args, **kwargs)

        product = getattr(self.instance, "product", None)
        if product:
            if hasattr(product, "code") and not self.initial.get("product_code"):
                self.initial["product_code"] = product.code

            if hasattr(product, "name") and not self.initial.get("product_name"):
                self.initial["product_name"] = product.name

    def clean(self):
        """
        منطق الفالديشن لسطر المبيعات:

        - نتجاهل الفورمات التي لم تتغير نهائياً (handled by formset).
        - لو فيه product_code بدون product → نحاول نبحث بالكود.
        - لو الكمية > 0 ولا يوجد منتج ولا وصف → نرمي خطأ.
        """
        cleaned_data = super().clean()

        product = cleaned_data.get("product")
        description = cleaned_data.get("description")
        quantity = cleaned_data.get("quantity") or 0
        code = cleaned_data.get("product_code")

        # لو الفورم ما تغيّر، نخليه يمر والفورمست يتصرف
        if not self.has_changed():
            return cleaned_data

        # 1) محاولة ربط المنتج عن طريق الكود لو المنتج غير محدد
        if code and not product:
            try:
                product = Product.objects.get(code__iexact=code.strip())
                cleaned_data["product"] = product
                self.instance.product = product

                # لو ما فيه وصف، نستخدم اسم المنتج تلقائياً
                if not description:
                    cleaned_data["description"] = product.name
                    self.instance.description = product.name

                # نحدّث اسم المنتج للواجهة أيضاً
                cleaned_data["product_name"] = getattr(product, "name", "")

            except Product.DoesNotExist:
                self.add_error(
                    "product_code",
                    _("لم يتم العثور على منتج بهذا الكود."),
                )
                return cleaned_data

        # 2) التحقق من أن السطر له معنى
        if quantity > 0 and not (product or description):
            raise forms.ValidationError(
                _("يجب اختيار منتج أو كتابة وصف لهذا السطر."),
            )

        return cleaned_data



class BaseSalesLineFormSet(BaseInlineFormSet):
    """
    Inline formset لبنود المبيعات:

    - نتأكد من وجود سطر واحد على الأقل له قيمة حقيقية
      (منتج / وصف / كمية / سعر).
    - يمكن لاحقاً إضافة فالديشنات مشتركة بين السطور
      (مثل خصم ما يتعدى نسبة معينة...).
    """

    def clean(self):
        super().clean()

        has_valid_line = False

        for form in self.forms:
            # بعض الفورمات قد لا تحتوي cleaned_data (أخطاء سابقة)
            if not hasattr(form, "cleaned_data"):
                continue

            # نتجاهل السطور المحددة للحذف
            if form.cleaned_data.get("DELETE", False):
                continue

            # نتجاهل السطور التي لم تتغير نهائياً
            if not form.has_changed():
                continue

            product = form.cleaned_data.get("product")
            description = form.cleaned_data.get("description")
            quantity = form.cleaned_data.get("quantity") or 0
            unit_price = form.cleaned_data.get("unit_price") or 0

            # نعتبر السطر "له معنى" لو فيه أي قيمة من هذه
            if product or description or quantity or unit_price:
                has_valid_line = True

        if self.total_form_count() > 0 and not has_valid_line:
            raise forms.ValidationError(
                _("يجب إضافة سطر مبيعات واحد على الأقل."),
            )


SalesLineFormSet = inlineformset_factory(
    parent_model=SalesDocument,
    model=SalesLine,
    form=SalesLineForm,
    formset=BaseSalesLineFormSet,
    extra=5,
    can_delete=True,
    min_num=0,
    validate_min=False,
)
