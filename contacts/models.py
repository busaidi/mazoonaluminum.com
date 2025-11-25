# contacts/models.py
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Customer(models.Model):
    """
    ملف الزبون العالمي (تطبيق contacts).

    - مشترك بين المحاسبة، الطلبات، البوابة، وغيرها.
    - يحتفظ بعنوان أساسي (للتوافق مع الكود القديم).
    - العناوين الإضافية تُخزَّن في CustomerAddress.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_profile",
        help_text=_("اختياري: ربط الزبون بحساب مستخدم للدخول إلى البوابة."),
        verbose_name=_("المستخدم المرتبط"),
    )

    # --------- بيانات أساسية ---------
    name = models.CharField(
        _("اسم الزبون"),
        max_length=255,
    )
    phone = models.CharField(
        _("رقم الهاتف"),
        max_length=50,
        blank=True,
    )
    email = models.EmailField(
        _("البريد الإلكتروني"),
        blank=True,
    )
    company_name = models.CharField(
        _("اسم الشركة"),
        max_length=255,
        blank=True,
    )
    tax_number = models.CharField(
        _("الرقم الضريبي / ضريبة القيمة المضافة"),
        max_length=50,
        blank=True,
        help_text=_("اختياري: رقم ضريبة القيمة المضافة أو الرقم الضريبي إن وجد."),
    )

    # --------- العنوان الأساسي (محفوظ للتوافق) ---------
    country = models.CharField(
        _("الدولة"),
        max_length=255,
        blank=True,
        help_text=_("اسم الدولة (يمكن ترجمته)."),
    )
    governorate = models.CharField(
        _("المحافظة"),
        max_length=255,
        blank=True,
        help_text=_("اسم المحافظة (يمكن ترجمته)."),
    )
    wilaya = models.CharField(
        _("الولاية"),
        max_length=255,
        blank=True,
        help_text=_("اسم الولاية (يمكن ترجمته)."),
    )
    village = models.CharField(
        _("القرية / الحي"),
        max_length=255,
        blank=True,
        help_text=_("اسم القرية أو الحي (يمكن ترجمته)."),
    )
    postal_code = models.CharField(
        _("الرمز البريدي"),
        max_length=20,
        blank=True,
        help_text=_("الرمز البريدي (يمكن ترجمته عند الحاجة)."),
    )
    po_box = models.CharField(
        _("صندوق البريد"),
        max_length=20,
        blank=True,
        help_text=_("رقم صندوق البريد (يمكن ترجمته عند الحاجة)."),
    )

    # عنوان حر (نصي)
    address = models.TextField(
        _("العنوان الكامل (نصي)"),
        blank=True,
    )

    created_at = models.DateTimeField(
        _("تاريخ الإنشاء"),
        auto_now_add=True,
    )

    class Meta:
        ordering = ("name", "id")
        verbose_name = _("الزبون")
        verbose_name_plural = _("الزبائن")

    def __str__(self) -> str:
        return self.name

    # ---------- بيانات مُجمَّعة (من المحاسبة) ----------

    @property
    def total_invoiced(self) -> Decimal:
        """
        إجمالي قيمة الفواتير الصادرة لهذا الزبون.
        يعتمد على العلاقة العكسية من accounting.Invoice.customer.
        """
        total = self.invoices.aggregate(s=models.Sum("total_amount")).get("s")
        return total or Decimal("0")

    @property
    def total_paid(self) -> Decimal:
        """
        إجمالي الدفعات المستلمة من هذا الزبون.
        """
        total = self.payments.aggregate(s=models.Sum("amount")).get("s")
        return total or Decimal("0")

    @property
    def balance(self) -> Decimal:
        """
        رصيد الزبون = إجمالي الفواتير - إجمالي الدفعات.
        """
        return self.total_invoiced - self.total_paid


class CustomerAddress(models.Model):
    """
    عناوين متعددة لكل زبون.

    يمكن استخدام نوع العنوان + حقل (is_primary)
    لاختيار عنوان الفوترة أو الشحن في الفواتير والطلبات.
    """

    class AddressType(models.TextChoices):
        BILLING = "billing", _("عنوان الفوترة")
        SHIPPING = "shipping", _("عنوان الشحن")
        OTHER = "other", _("عنوان آخر")

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="addresses",
        verbose_name=_("الزبون"),
    )

    # مثال: "المكتب الرئيسي"، "المخزن"، "الموقع 1"
    label = models.CharField(
        _("وصف العنوان"),
        max_length=100,
        help_text=_("اسم قصير للتمييز بين العناوين: المكتب الرئيسي، المخزن، الموقع 1..."),
    )

    type = models.CharField(
        _("نوع العنوان"),
        max_length=20,
        choices=AddressType.choices,
        default=AddressType.BILLING,
    )

    # تفاصيل العنوان (ستُترجم عبر modeltranslation)
    address = models.TextField(
        _("العنوان التفصيلي"),
        blank=True,
    )

    country = models.CharField(
        _("الدولة"),
        max_length=255,
        blank=True,
    )
    governorate = models.CharField(
        _("المحافظة"),
        max_length=255,
        blank=True,
    )
    wilaya = models.CharField(
        _("الولاية"),
        max_length=255,
        blank=True,
    )
    village = models.CharField(
        _("القرية / الحي"),
        max_length=255,
        blank=True,
    )
    postal_code = models.CharField(
        _("الرمز البريدي"),
        max_length=20,
        blank=True,
    )
    po_box = models.CharField(
        _("صندوق البريد"),
        max_length=20,
        blank=True,
    )

    is_primary = models.BooleanField(
        _("عنوان أساسي"),
        default=False,
        help_text=_("إذا كان مفعّلًا، يُعتبر العنوان الأساسي لهذا النوع (فوترة / شحن)."),
    )

    is_active = models.BooleanField(
        _("نشط"),
        default=True,
    )

    created_at = models.DateTimeField(
        _("تاريخ الإضافة"),
        auto_now_add=True,
    )

    class Meta:
        ordering = ("customer", "type", "-is_primary", "id")
        verbose_name = _("عنوان زبون")
        verbose_name_plural = _("عناوين الزبائن")

    def __str__(self) -> str:
        return f"{self.customer} – {self.label}"
