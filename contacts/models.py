# contacts/models.py
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from .managers import ContactManager


class Contact(models.Model):
    """
    كيان اتصال عام (Contact):
    ممكن يكون:
      - زبون
      - مورد / شريك
      - مالك
      - موظف
      - أو أكثر من دور في نفس الوقت.
    """

    class ContactKind(models.TextChoices):
        PERSON = "person", _("فرد")
        COMPANY = "company", _("شركة")

    # ربط اختياري مع مستخدم Django (بوابة عملاء / موظفين)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contact_profile",
        verbose_name=_("المستخدم (اختياري)"),
        help_text=_("ربط جهة الاتصال بحساب مستخدم (بوابة العملاء/الموظفين)."),
    )

    # نوع الكيان (فرد / شركة)
    kind = models.CharField(
        max_length=20,
        choices=ContactKind.choices,
        default=ContactKind.PERSON,
        verbose_name=_("نوع جهة الاتصال"),
    )

    # --------- معلومات أساسية (ستكون مترجمة عبر modeltranslation) ---------
    name = models.CharField(
        max_length=255,
        verbose_name=_("الاسم"),
        help_text=_("اسم الشخص أو اسم الشركة."),
    )

    company_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("اسم الشركة (نص حر)"),
        help_text=_("يُستخدم للعرض حتى لو لم تربطه بسجل شركة في جهات الاتصال."),
    )

    # 🔹 الشركة (Contact من نوع COMPANY) – شخص واحد ممكن يرتبط بشركة واحدة
    company = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="people",
        limit_choices_to={"kind": ContactKind.COMPANY},
        verbose_name=_("الشركة (جهة اتصال)"),
        help_text=_("اربط هذا الشخص بسجل شركة في جهات الاتصال."),
    )

    # --------- بيانات الاتصال ---------
    phone = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("رقم الهاتف"),
    )

    email = models.EmailField(
        blank=True,
        verbose_name=_("البريد الإلكتروني"),
    )

    tax_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("الرقم الضريبي / VAT"),
    )

    # --------- أدوار جهة الاتصال (يمكن يجمع أكثر من دور) ---------
    is_customer = models.BooleanField(
        default=False,
        verbose_name=_("زبون"),
    )
    is_supplier = models.BooleanField(
        default=False,
        verbose_name=_("مورد / شريك"),
    )
    is_owner = models.BooleanField(
        default=False,
        verbose_name=_("مالك"),
    )
    is_employee = models.BooleanField(
        default=False,
        verbose_name=_("موظف"),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("نشط"),
    )

    # --------- العنوان الرئيسي (حقول بسيطة – ستُترجم) ---------
    country = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("الدولة"),
    )
    governorate = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("المحافظة"),
    )
    wilaya = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("الولاية"),
    )
    village = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("القرية / المنطقة"),
    )
    postal_code = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("الرمز البريدي"),
    )
    po_box = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("صندوق البريد"),
    )

    address = models.TextField(
        blank=True,
        verbose_name=_("عنوان تفصيلي (حر)"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("تاريخ الإنشاء"),
    )

    # المانجر الافتراضي المخصص
    objects = ContactManager()

    class Meta:
        ordering = ("name", "id")
        verbose_name = _("جهة اتصال")
        verbose_name_plural = _("جهات الاتصال")

    def __str__(self) -> str:
        return self.name

    # --------- خصائص لنوع الكيان ---------

    @property
    def is_person(self) -> bool:
        """
        هل هذه الجهة عبارة عن فرد؟
        """
        return self.kind == self.ContactKind.PERSON

    @property
    def is_company(self) -> bool:
        """
        هل هذه الجهة عبارة عن شركة؟
        """
        return self.kind == self.ContactKind.COMPANY

    # ---------- خصائص تجميعية (مفيدة لو هو زبون) ----------

    @property
    def total_invoiced(self) -> Decimal:
        """
        مجموع الفواتير لهذه الجهة لو كانت زبون.
        يعتمد على related_name='invoices' في Invoice.contact.
        """
        related = getattr(self, "invoices", None)
        if related is None:
            return Decimal("0")
        value = related.aggregate(s=Sum("total_amount")).get("s")
        return value or Decimal("0")

    @property
    def total_paid(self) -> Decimal:
        """
        مجموع المدفوعات لهذه الجهة لو كانت زبون.
        يعتمد على related_name='reconcile' في Payment.contact.
        """
        related = getattr(self, "reconcile", None)
        if related is None:
            return Decimal("0")
        value = related.aggregate(s=Sum("amount")).get("s")
        return value or Decimal("0")

    @property
    def balance(self) -> Decimal:
        """
        رصيد الجهة (كزبون) = الفواتير - المدفوعات.
        """
        return self.total_invoiced - self.total_paid


class ContactAddress(models.Model):
    """
    عناوين متعددة لكل جهة اتصال.
    ممكن تستخدم:
      - عنوان فوترة
      - عنوان شحن
      - عنوان مقر رئيسي
      - ...الخ
    """

    class AddressType(models.TextChoices):
        BILLING = "billing", _("عنوان فوترة")
        SHIPPING = "shipping", _("عنوان شحن")
        OFFICE = "office", _("مكتب / مقر")
        OTHER = "other", _("عنوان آخر")

    contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE,
        related_name="addresses",
        verbose_name=_("جهة الاتصال"),
    )

    # سيكون مترجم عبر modeltranslation
    label = models.CharField(
        max_length=100,
        verbose_name=_("وصف العنوان"),
        help_text=_("مثال: المكتب الرئيسي، المخزن، موقع المشروع 1..."),
    )

    address_type = models.CharField(
        max_length=20,
        choices=AddressType.choices,
        default=AddressType.OTHER,
        verbose_name=_("نوع العنوان"),
    )

    # سيكون مترجم (أو على الأقل address)
    address = models.TextField(
        blank=True,
        verbose_name=_("العنوان التفصيلي"),
    )

    country = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("الدولة"),
    )
    governorate = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("المحافظة"),
    )
    wilaya = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("الولاية"),
    )
    village = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("القرية / المنطقة"),
    )
    postal_code = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("الرمز البريدي"),
    )
    po_box = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("صندوق البريد"),
    )

    is_primary = models.BooleanField(
        default=False,
        verbose_name=_("العنوان الرئيسي لهذا النوع"),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("نشط"),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("تاريخ الإنشاء"),
    )

    class Meta:
        ordering = ("contact", "address_type", "-is_primary", "id")
        verbose_name = _("عنوان جهة اتصال")
        verbose_name_plural = _("عناوين جهات الاتصال")

    def __str__(self) -> str:
        return f"{self.contact} – {self.label}"
