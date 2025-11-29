# contacts/forms.py
from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from .models import Contact, ContactAddress


class ContactForm(forms.ModelForm):
    """
    الفورم الأساسي لـ Contact (جهة اتصال عامة).

    ✅ بعد الريفاكتور:
      - بدون حقول عنوان (لا address_* ولا country_* ...الخ)
      - العناوين تُدار بالكامل عبر ContactAddress + formset
      - يبقى هنا:
        * نوع الجهة (فرد / شركة)
        * الربط مع شركة (company)
        * الاسم بالعربي/الإنجليزي
        * اسم الشركة الحر بالعربي/الإنجليزي
        * بيانات الاتصال (هاتف، إيميل، رقم ضريبي)
        * الأدوار (زبون، مورد، مالك، موظف)
        * حالة النشاط
    """

    class Meta:
        model = Contact
        fields = [
            # ==== نوع الجهة ====
            "kind",

            # ==== الربط مع شركة (Contact من نوع COMPANY) ====
            "company",

            # ==== الحقول المترجمة (modeltranslation) ====
            "name_ar",
            "name_en",
            "company_name_ar",
            "company_name_en",

            # ==== بيانات الاتصال ====
            "phone",
            "email",
            "tax_number",

            # ==== الأدوار ====
            "is_customer",
            "is_supplier",
            "is_owner",
            "is_employee",

            # ==== الحالة ====
            "is_active",
        ]
        labels = {
            "kind": _("نوع جهة الاتصال"),
            "company": _("الشركة (من جهات الاتصال)"),
            "name_ar": _("الاسم (عربي)"),
            "name_en": _("الاسم (إنجليزي)"),
            "company_name_ar": _("اسم الشركة (عربي – نص حر)"),
            "company_name_en": _("اسم الشركة (إنجليزي – نص حر)"),
            "phone": _("رقم الهاتف"),
            "email": _("البريد الإلكتروني"),
            "tax_number": _("الرقم الضريبي / VAT"),
            "is_customer": _("زبون"),
            "is_supplier": _("مورد / شريك"),
            "is_owner": _("مالك"),
            "is_employee": _("موظف"),
            "is_active": _("نشط"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # نقيّد الشركات في الحقل company على جهات الاتصال من نوع COMPANY و active
        if "company" in self.fields:
            self.fields["company"].queryset = (
                Contact.objects.companies().active().order_by("name")
            )

        # توحيد الـ CSS مع ثيم Mazoon (Bootstrap)
        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")

            # حقول select (نوع الجهة + الشركة)
            if name in ("kind", "company"):
                field.widget.attrs["class"] = (css + " form-select").strip()

            # حقول الأدوار + الحالة (checkboxes)
            elif name in ("is_customer", "is_supplier", "is_owner", "is_employee", "is_active"):
                field.widget.attrs["class"] = (css + " form-check-input").strip()

            # باقي الحقول input / textarea
            else:
                field.widget.attrs["class"] = (css + " form-control").strip()


class ContactAddressForm(forms.ModelForm):
    """
    فورم لعناوين جهة الاتصال المتعددة:
    - address_type: فوترة / شحن / مكتب / آخر
    - address: العنوان التفصيلي
    - country / governorate / wilaya / village
    - postal_code / po_box
    - is_primary: لتحديد العنوان الرئيسي لهذا النوع
    """

    class Meta:
        model = ContactAddress
        fields = [
            "address_type",
            "address",       # نص العنوان التفصيلي
            "country",
            "governorate",
            "wilaya",
            "village",
            "postal_code",
            "po_box",
            "is_primary",
            "is_active",
        ]
        labels = {
            "address_type": _("نوع العنوان"),

            "address": _("العنوان التفصيلي"),

            "country": _("الدولة"),
            "governorate": _("المحافظة"),
            "wilaya": _("الولاية"),
            "village": _("القرية / المنطقة"),

            "postal_code": _("الرمز البريدي"),
            "po_box": _("صندوق البريد"),
            "is_primary": _("عنوان رئيسي لهذا النوع"),
            "is_active": _("نشط"),
        }
        widgets = {
            "address": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")

            # نوع العنوان (select صغير)
            if name == "address_type":
                field.widget.attrs["class"] = (css + " form-select form-select-sm").strip()

            # checkboxes
            elif name in ("is_primary", "is_active"):
                field.widget.attrs["class"] = (css + " form-check-input").strip()

            # باقي الحقول input / textarea
            else:
                field.widget.attrs["class"] = (css + " form-control form-control-sm").strip()

ContactAddressFormSet = inlineformset_factory(
    Contact,
    ContactAddress,
    form=ContactAddressForm,
    extra=1,
    can_delete=True,
)
