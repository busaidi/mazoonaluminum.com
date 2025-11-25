# contacts/forms.py
from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from .models import Contact, ContactAddress


class ContactForm(forms.ModelForm):
    """
    الفورم الأساسي لـ Contact (جهة اتصال عامة).
    يدعم:
      - فرد / شركة (kind)
      - ربط الشخص بشركة (company)
      - بيانات الاتصال
      - العنوان الرئيسي (مترجم)
      - الأدوار + الحالة
    """

    class Meta:
        model = Contact
        fields = [
            # ==== نوع الجهة ====
            "kind",

            # ==== الربط مع شركة (Contact من نوع COMPANY) ====
            "company",

            # ==== الحقول المترجمة ====
            "name_ar",
            "name_en",
            "company_name_ar",
            "company_name_en",
            "address_ar",
            "address_en",
            "country_ar",
            "country_en",
            "governorate_ar",
            "governorate_en",
            "wilaya_ar",
            "wilaya_en",
            "village_ar",
            "village_en",
            "postal_code_ar",
            "postal_code_en",
            "po_box_ar",
            "po_box_en",

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
            "address_ar": _("العنوان التفصيلي (عربي)"),
            "address_en": _("العنوان التفصيلي (إنجليزي)"),
            "country_ar": _("الدولة (عربي)"),
            "country_en": _("الدولة (إنجليزي)"),
            "governorate_ar": _("المحافظة (عربي)"),
            "governorate_en": _("المحافظة (إنجليزي)"),
            "wilaya_ar": _("الولاية (عربي)"),
            "wilaya_en": _("الولاية (إنجليزي)"),
            "village_ar": _("القرية / المنطقة (عربي)"),
            "village_en": _("القرية / المنطقة (إنجليزي)"),
            "postal_code_ar": _("الرمز البريدي (عربي)"),
            "postal_code_en": _("الرمز البريدي (إنجليزي)"),
            "po_box_ar": _("صندوق البريد (عربي)"),
            "po_box_en": _("صندوق البريد (إنجليزي)"),
            "phone": _("رقم الهاتف"),
            "email": _("البريد الإلكتروني"),
            "tax_number": _("الرقم الضريبي / VAT"),
            "is_customer": _("زبون"),
            "is_supplier": _("مورد / شريك"),
            "is_owner": _("مالك"),
            "is_employee": _("موظف"),
            "is_active": _("نشط"),
        }
        widgets = {
            "address_ar": forms.Textarea(attrs={"rows": 3}),
            "address_en": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # نقيّد الشركات في الحقل company على جهات الاتصال من نوع COMPANY و active
        if "company" in self.fields:
            self.fields["company"].queryset = (
                Contact.objects.companies().active().order_by("name")
            )

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
    - label مختصر اختياري مثل "المكتب الرئيسي"
    - عنوان كامل + تفاصيل الموقع.
    """

    class Meta:
        model = ContactAddress
        fields = [
            "label_ar",
            "label_en",
            "address_type",
            "address_ar",
            "address_en",
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
            "label_ar": _("عنوان مختصر (عربي)"),
            "label_en": _("عنوان مختصر (إنجليزي)"),
            "address_type": _("نوع العنوان"),
            "address_ar": _("العنوان التفصيلي (عربي)"),
            "address_en": _("العنوان التفصيلي (إنجليزي)"),
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
            "address_ar": forms.Textarea(attrs={"rows": 2}),
            "address_en": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            css = field.widget.attrs.get("class", "")
            if name == "address_type":
                field.widget.attrs["class"] = (css + " form-select form-select-sm").strip()
            elif name in ("is_primary", "is_active"):
                field.widget.attrs["class"] = (css + " form-check-input").strip()
            else:
                field.widget.attrs["class"] = (css + " form-control form-control-sm").strip()


ContactAddressFormSet = inlineformset_factory(
    Contact,
    ContactAddress,
    form=ContactAddressForm,
    extra=1,
    can_delete=True,
)
