# accounting/views.py

from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import (
    login_required,
    permission_required,
    user_passes_test,
)
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum, Value, DecimalField, F
from django.db.models.functions import Coalesce
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import (
    CreateView,
    DetailView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
)
from openpyxl import Workbook

from contacts.models import Contact
from core.models import AuditLog
from core.services.audit import log_event
from core.services.notifications import create_notification
from core.views.attachments import AttachmentPanelMixin

from .forms import (
    AccountForm,
    AccountLedgerFilterForm,
    ChartOfAccountsImportForm,
    FiscalYearForm,
    InvoiceForm,
    InvoiceItemFormSet,
    JournalEntryFilterForm,
    JournalEntryForm,
    JournalForm,
    JournalLineFormSet,
    LedgerSettingsForm,
    SettingsForm,
    TrialBalanceFilterForm,
)
from .mixins import ProductJsonMixin
from .models import (
    Account,
    FiscalYear,
    Invoice,
    Journal,
    JournalEntry,
    JournalLine,
    LedgerSettings,
    Settings,
    get_default_journal_for_manual_entry,
)
from .services import (
    build_lines_from_formset,
    ensure_default_chart_of_accounts,
    import_chart_of_accounts_from_excel,
)


# ============================================================
# Helper permissions
# ============================================================


def is_accounting_staff(user):
    """
    صلاحية بسيطة لموظفي المحاسبة:
    - مستخدم مسجل وفعّال
    - عضو في مجموعة 'accounting_staff'
    """
    return (
        user.is_authenticated
        and user.is_active
        and user.groups.filter(name="accounting_staff").exists()
    )


accounting_staff_required = user_passes_test(is_accounting_staff)


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    مزيّن للمشاهد التي تحتاج مستخدم محاسبة/ستاف:
    - يسمح لأي مستخدم is_staff أو is_superuser
    - أو عضو في مجموعة accounting_staff
    """

    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False

        if user.is_staff or user.is_superuser:
            return True

        return is_accounting_staff(user)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        messages.error(self.request, _("ليس لديك صلاحية للوصول إلى هذه الصفحة."))
        return redirect("login")


def ledger_staff_required(view_func):
    """
    Decorator بسيط ليتطلب مستخدم ستاف/سوبر يوزر/محاسبة.
    نستخدمه في شاشات دفتر الأستاذ (داخل تطبيق accounting).
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect("login")

        if not (user.is_staff or user.is_superuser or is_accounting_staff(user)):
            messages.error(
                request,
                _("ليس لديك صلاحية للوصول إلى هذه الصفحة."),
            )
            return redirect("login")

        return view_func(request, *args, **kwargs)

    return _wrapped


# ============================================================
# Mixins (sections / dates / fiscal year)
# ============================================================


class AccountingSectionMixin:
    """
    يحقن 'accounting_section' في الكونتكست حتى تقدر القوالب
    تميّز القسم الحالي (فواتير، إعدادات، ...).
    """

    section = None  # override في الكلاسات

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["accounting_section"] = self.section
        return ctx


class TodayInitialDateMixin:
    """
    يضع تاريخ اليوم كقيمة افتراضية لحقل 'date' إذا لم تُمرّر.
    """

    def get_initial(self):
        initial = super().get_initial()
        initial.setdefault("date", timezone.now().date())
        return initial


class FiscalYearRequiredMixin:
    """
    تحقق من وجود سنوات مالية، وتحذيرات لو كلها مقفلة أو التاريخ خارج النطاق.
    """

    def dispatch(self, request, *args, **kwargs):
        qs = FiscalYear.objects.all()

        # 1) لا توجد أي سنة مالية
        if not qs.exists():
            messages.warning(
                request,
                _("يجب إنشاء سنة مالية واحدة على الأقل قبل استخدام دفتر الأستاذ."),
            )
            return redirect("accounting:fiscal_year_list")

        # 2) توجد سنوات لكن كلها مقفلة
        open_years = qs.filter(is_closed=False)
        if not open_years.exists():
            messages.warning(
                request,
                _(
                    "كل السنوات المالية مقفلة حاليًا. يمكنك استعراض التقارير، "
                    "ولكن لا يمكن إنشاء قيود جديدة إلا بعد فتح سنة مالية جديدة."
                ),
            )
            return super().dispatch(request, *args, **kwargs)

        # 3) توجد سنوات مفتوحة، لكن اليوم خارج نطاقها
        today = timezone.now().date()
        if not open_years.filter(start_date__lte=today, end_date__gte=today).exists():
            messages.info(
                request,
                _(
                    "توجد سنة مالية مفتوحة، لكن تاريخ اليوم لا يقع ضمن نطاقها. "
                    "تأكد من اختيار الفترة/السنة الصحيحة في التقارير."
                ),
            )

        return super().dispatch(request, *args, **kwargs)


def fiscal_year_required(view_func):
    """
    نسخة Decorator من FiscalYearRequiredMixin لنمط الـ function-based views.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        qs = FiscalYear.objects.all()

        # 1) لا توجد أي سنة مالية
        if not qs.exists():
            messages.warning(
                request,
                _("يجب إنشاء سنة مالية واحدة على الأقل قبل استخدام دفتر الأستاذ."),
            )
            return redirect("accounting:fiscal_year_list")

        open_years = qs.filter(is_closed=False)

        # 2) كل السنوات مقفلة
        if not open_years.exists():
            messages.warning(
                request,
                _(
                    "كل السنوات المالية مقفلة حاليًا. يمكنك استعراض التقارير، "
                    "ولكن لا يمكن إنشاء قيود جديدة إلا بعد فتح سنة مالية جديدة."
                ),
            )
            return view_func(request, *args, **kwargs)

        # 3) سنة/سنوات مفتوحة لكن تاريخ اليوم خارج نطاقها
        today = timezone.now().date()
        if not open_years.filter(start_date__lte=today, end_date__gte=today).exists():
            messages.info(
                request,
                _(
                    "توجد سنة مالية مفتوحة، لكن تاريخ اليوم لا يقع ضمن نطاقها. "
                    "تأكد من اختيار الفترة/السنة الصحيحة في التقارير."
                ),
            )

        return view_func(request, *args, **kwargs)

    return _wrapped


def ensure_open_fiscal_year_for_date(date):
    """
    Helper للتأكد أن التاريخ يقع داخل سنة مالية "مفتوحة".
    يستخدم في إنشاء/تعديل قيود اليومية.
    """
    if not date:
        raise ValidationError(_("يجب تحديد تاريخ للقيد."))

    fy = FiscalYear.for_date(date)
    if fy is None:
        raise ValidationError(
            _(
                "لا توجد سنة مالية تغطي هذا التاريخ. "
                "يرجى إنشاء سنة مالية مناسبة أو تعديل التاريخ."
            )
        )

    if fy.is_closed:
        raise ValidationError(
            _("لا يمكن إنشاء أو تعديل قيد ضمن سنة مالية مقفلة.")
        )

    return fy


# ============================================================
# Dashboard
# ============================================================


@method_decorator(accounting_staff_required, name="dispatch")
class AccountingDashboardView(AccountingSectionMixin, TemplateView):
    """
    لوحة تحكم المحاسبة:
    - تفصل بين فواتير المبيعات والمشتريات حسب الحقل Invoice.type
    - تعرض KPIs + آخر فواتير مبيعات + آخر فواتير مشتريات + ملخص حسابات
    """
    section = "dashboard"
    template_name = "accounting/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        invoices = Invoice.objects.select_related("customer")

        # 🔹 فصل المبيعات عن المشتريات حسب الحقل: type = Invoice.InvoiceType.*
        sales_invoices = invoices.filter(type=Invoice.InvoiceType.SALES)
        purchase_invoices = invoices.filter(type=Invoice.InvoiceType.PURCHASE)

        # --------- أرقام أساسية ---------
        def agg(qs, field):
            return qs.aggregate(s=Sum(field))["s"] or Decimal("0")

        sales_invoice_count = sales_invoices.count()
        purchase_invoice_count = purchase_invoices.count()

        sales_total_amount = agg(sales_invoices, "total_amount")
        sales_total_paid = agg(sales_invoices, "paid_amount")
        sales_total_balance = sales_total_amount - sales_total_paid

        purchase_total_amount = agg(purchase_invoices, "total_amount")
        purchase_total_paid = agg(purchase_invoices, "paid_amount")
        purchase_total_balance = purchase_total_amount - purchase_total_paid

        # لو حاب تحافظ على المتغيّرات القديمة:
        invoice_count = sales_invoice_count + purchase_invoice_count

        # --------- آخر الفواتير ---------
        recent_sales_invoices = sales_invoices.order_by("-issued_at", "-id")[:5]
        recent_purchase_invoices = purchase_invoices.order_by("-issued_at", "-id")[:5]

        # --------- الحسابات ---------
        accounts_count = Account.objects.count()
        key_accounts = (
            Account.objects.filter(is_active=True, parent__isnull=True)
            .order_by("code")[:5]
        )

        ctx.update(
            {
                # KPIs القديمة (للرجوع للخلف)
                "invoice_count": invoice_count,
                "total_amount": sales_total_amount,
                "total_balance": sales_total_balance,

                # KPIs مفصّلة
                "sales_invoice_count": sales_invoice_count,
                "purchase_invoice_count": purchase_invoice_count,
                "sales_total_amount": sales_total_amount,
                "sales_total_balance": sales_total_balance,
                "purchase_total_amount": purchase_total_amount,
                "purchase_total_balance": purchase_total_balance,

                # جداول آخر الفواتير
                "recent_sales_invoices": recent_sales_invoices,
                "recent_purchase_invoices": recent_purchase_invoices,

                # الحسابات
                "accounts_count": accounts_count,
                "key_accounts": key_accounts,

                "accounting_section": "dashboard",
            }
        )
        return ctx




class LedgerDashboardView(FiscalYearRequiredMixin, StaffRequiredMixin, TemplateView):
    """
    لوحة تحكم دفتر الأستاذ (الحسابات / القيود).
    (حالياً ما لها URL، لو حبيت تضيفها لاحقاً).
    """
    template_name = "accounting/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        today = timezone.now().date()
        month_start = today.replace(day=1)

        accounts_count = Account.objects.count()

        entries_qs = JournalEntry.objects.posted()
        entries_count = entries_qs.count()

        month_entries = entries_qs.filter(
            date__gte=month_start,
            date__lte=today,
        )
        month_entries_count = month_entries.count()

        month_totals = (
            JournalLine.objects.posted()
            .filter(entry__in=month_entries)
            .aggregate(
                debit=Coalesce(
                    Sum("debit"),
                    Value(0),
                    output_field=DecimalField(max_digits=12, decimal_places=3),
                ),
                credit=Coalesce(
                    Sum("credit"),
                    Value(0),
                    output_field=DecimalField(max_digits=12, decimal_places=3),
                ),
            )
        )
        month_debit = month_totals["debit"] or Decimal("0")
        month_credit = month_totals["credit"] or Decimal("0")

        recent_entries = (
            JournalEntry.objects.posted()
            .order_by("-date", "-id")[:10]
        )

        ctx.update(
            {
                "accounts_count": accounts_count,
                "entries_count": entries_count,
                "month_entries_count": month_entries_count,
                "month_debit": month_debit,
                "month_credit": month_credit,
                "recent_entries": recent_entries,
                "today": today,
                "month_start": month_start,
                "ledger_section": "dashboard",
            }
        )
        return ctx


# ============================================================
# Invoices
# ============================================================


# ============================================================
# Invoices
# ============================================================

@method_decorator(accounting_staff_required, name="dispatch")
class BaseInvoiceListView(AccountingSectionMixin, ListView):
    """
    قائمة فواتير مع إمكانية التصفية بالحالة + النوع (مبيعات/مشتريات).
    تستخدم كـ base لكل القوائم.
    """
    section = "invoices"
    model = Invoice
    template_name = "accounting/invoices/list.html"
    context_object_name = "invoices"
    paginate_by = 20

    # None = كل الأنواع، أو Invoice.InvoiceType.SALES / PURCHASE
    invoice_type = None

    def get_queryset(self):
        qs = super().get_queryset().select_related("customer")

        # تصفية بالنوع لو محدد
        if self.invoice_type:
            qs = qs.filter(type=self.invoice_type)

        # تصفية بالحالة من الكويري سترنغ
        status = self.request.GET.get("status")
        if status:
            qs = qs.filter(status=status)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_filter"] = self.request.GET.get("status", "")
        ctx["invoice_type"] = self.invoice_type
        if self.invoice_type:
            # يعطيك "فاتورة مبيعات" / "فاتورة مشتريات" حسب الترانسليشن
            ctx["invoice_type_label"] = Invoice.InvoiceType(self.invoice_type).label
        else:
            ctx["invoice_type_label"] = _("كل الفواتير")
        return ctx


@method_decorator(accounting_staff_required, name="dispatch")
class SalesInvoiceListView(BaseInvoiceListView):
    """
    قائمة فواتير المبيعات فقط.
    URL: /accounting/sales/invoices/
    """
    invoice_type = Invoice.InvoiceType.SALES


@method_decorator(accounting_staff_required, name="dispatch")
class PurchaseInvoiceListView(BaseInvoiceListView):
    """
    قائمة فواتير المشتريات فقط.
    URL: /accounting/purchases/invoices/
    """
    invoice_type = Invoice.InvoiceType.PURCHASE


@method_decorator(accounting_staff_required, name="dispatch")
class InvoiceListView(BaseInvoiceListView):
    """
    قائمة عامة (قديمة) لكل الفواتير بدون تصفية النوع.
    URL: /accounting/invoices/
    """
    invoice_type = None


class BaseInvoiceCreateView(AccountingSectionMixin, ProductJsonMixin, CreateView):
    """
    Base لإنشاء الفاتورة، نستخدمه للمبيعات والمشتريات.
    النوع يتحدد من الكلاس الفرعي.
    """
    section = "invoices"
    model = Invoice
    form_class = InvoiceForm
    template_name = "accounting/invoices/form.html"

    # None = يترك الديفولت في الموديل (sales)،
    # أو نحددها في الكلاسات الفرعية.
    invoice_type = None

    def get_initial(self):
        initial = super().get_initial()

        # نحاول نقرأ ID من ?customer= أو ?contact=
        customer_id = (
            self.request.GET.get("customer")
            or self.request.GET.get("contact")
        )

        if customer_id:
            try:
                initial["customer"] = Contact.objects.get(pk=customer_id)
            except (ValueError, Contact.DoesNotExist):
                pass

        # Pre-fill default terms from Settings
        if not initial.get("terms"):
            settings_obj = Settings.get_solo()
            if settings_obj.default_terms:
                initial["terms"] = settings_obj.default_terms

        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        if self.request.POST:
            ctx["item_formset"] = InvoiceItemFormSet(self.request.POST)
        else:
            ctx["item_formset"] = InvoiceItemFormSet()

        ctx = self.inject_products_json(ctx)

        # عشان الهيدر في القالب يعرف النوع
        ctx["invoice_type"] = self.invoice_type or Invoice.InvoiceType.SALES
        if self.invoice_type:
            ctx["invoice_type_label"] = Invoice.InvoiceType(self.invoice_type).label
        else:
            ctx["invoice_type_label"] = _("فاتورة")

        return ctx

    def form_valid(self, form):
        context = self.get_context_data()
        item_formset = context["item_formset"]

        if not item_formset.is_valid():
            return self.form_invalid(form)

        with transaction.atomic():
            invoice = form.save(commit=False)

            # نثبّت النوع حسب الكلاس الفرعي
            if self.invoice_type:
                invoice.type = self.invoice_type

            invoice.total_amount = Decimal("0")
            invoice.save()
            self.object = invoice

            item_formset.instance = invoice
            item_formset.save()

            total = sum(
                (item.subtotal for item in invoice.items.all()),
                Decimal("0"),
            )
            invoice.total_amount = total
            invoice.save(update_fields=["total_amount"])

        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        """
        بعد الحفظ يودّي على صفحة التفاصيل حسب نوع الفاتورة.
        """
        inv_type = self.object.type

        if inv_type == Invoice.InvoiceType.SALES:
            return reverse(
                "accounting:sales_invoice_detail",
                kwargs={"pk": self.object.pk},
            )
        if inv_type == Invoice.InvoiceType.PURCHASE:
            return reverse(
                "accounting:purchase_invoice_detail",
                kwargs={"pk": self.object.pk},
            )
        # مسار عام قديم
        return reverse(
            "accounting:invoice_detail",
            kwargs={"pk": self.object.pk},
        )


class SalesInvoiceCreateView(BaseInvoiceCreateView):
    """
    إنشاء فاتورة مبيعات.
    URL: /accounting/sales/invoices/new/
    """
    invoice_type = Invoice.InvoiceType.SALES


class PurchaseInvoiceCreateView(BaseInvoiceCreateView):
    """
    إنشاء فاتورة مشتريات.
    URL: /accounting/purchases/invoices/new/
    """
    invoice_type = Invoice.InvoiceType.PURCHASE


class InvoiceCreateView(BaseInvoiceCreateView):
    """
    مسار عام (قديم) لو احتجناه من مكان آخر.
    النوع هنا يعتمد على الديفولت في الموديل (sales).
    """
    invoice_type = None


@method_decorator(accounting_staff_required, name="dispatch")
class InvoiceUpdateView(AccountingSectionMixin, ProductJsonMixin, UpdateView):
    """
    تعديل فاتورة وبنودها.
    (تعمل لكل الأنواع، وتعيد التوجيه حسب نوع الفاتورة).
    """
    section = "invoices"
    model = Invoice
    form_class = InvoiceForm
    template_name = "accounting/invoices/form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        invoice = self.object

        if self.request.POST:
            ctx["item_formset"] = InvoiceItemFormSet(
                self.request.POST,
                instance=invoice,
            )
        else:
            ctx["item_formset"] = InvoiceItemFormSet(instance=invoice)

        ctx = self.inject_products_json(ctx)

        ctx["invoice_type"] = invoice.type
        ctx["invoice_type_label"] = invoice.get_type_display()

        return ctx

    def form_valid(self, form):
        context = self.get_context_data()
        item_formset = context["item_formset"]

        if not item_formset.is_valid():
            return self.form_invalid(form)

        invoice = form.save(commit=False)
        invoice.total_amount = Decimal("0")
        invoice.save()
        self.object = invoice

        item_formset.instance = invoice
        item_formset.save()

        total = sum((item.subtotal for item in invoice.items.all()), Decimal("0"))
        invoice.total_amount = total
        invoice.save(update_fields=["total_amount"])

        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        """
        نفس منطق الـ Create: نودّي المستخدم على ديتيل حسب النوع.
        """
        inv_type = self.object.type

        if inv_type == Invoice.InvoiceType.SALES:
            return reverse(
                "accounting:sales_invoice_detail",
                kwargs={"pk": self.object.pk},
            )
        if inv_type == Invoice.InvoiceType.PURCHASE:
            return reverse(
                "accounting:purchase_invoice_detail",
                kwargs={"pk": self.object.pk},
            )
        return reverse(
            "accounting:invoice_detail",
            kwargs={"pk": self.object.pk},
        )


@method_decorator(accounting_staff_required, name="dispatch")
class InvoiceDetailView(AttachmentPanelMixin, AccountingSectionMixin, DetailView):
    """
    عرض تفاصيل فاتورة (مع مرفقات) لأي نوع.
    """
    section = "invoices"
    model = Invoice
    template_name = "accounting/invoices/detail.html"
    context_object_name = "invoice"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx = self.inject_attachment_panel_context(ctx)
        ctx["invoice_type"] = self.object.type
        ctx["invoice_type_label"] = self.object.get_type_display()
        return ctx


@method_decorator(accounting_staff_required, name="dispatch")
class InvoicePrintView(AccountingSectionMixin, DetailView):
    """
    صفحة الطباعة للفاتورة (أي نوع).
    """
    section = "invoices"
    model = Invoice
    template_name = "accounting/invoices/print.html"
    context_object_name = "invoice"



# ============================================================
# Sales / Invoice Settings
# ============================================================


@staff_member_required
def accounting_settings_view(request):
    """
    شاشة إعدادات المبيعات/الفواتير (أيام الاستحقاق، VAT، النصوص...).
    (من غير منطق ترقيم للفواتير).
    """
    settings_obj = Settings.get_solo()

    if request.method == "POST":
        form = SettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, _("تم تحديث إعدادات المبيعات والفواتير بنجاح."))
            # مطابق لاسم URL: path("settings/", views.accounting_settings_view, name="accounting_settings")
            return redirect("accounting:accounting_settings")
    else:
        form = SettingsForm(instance=settings_obj)

    context = {
        "form": form,
        "accounting_section": "settings",
    }
    return render(request, "accounting/settings/settings.html", context)


# ============================================================
# Fiscal years
# ============================================================


@ledger_staff_required
def fiscal_year_setup_view(request):
    """
    معالج إعداد السنة المالية الأولى.
    لو توجد سنة مسبقاً → يحوّل إلى لوحة التحكم.
    """
    if FiscalYear.objects.exists():
        return redirect("accounting:dashboard")

    if request.method == "POST":
        form = FiscalYearForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                _("تم إنشاء السنة المالية الأولى بنجاح. يمكنك الآن استخدام دفتر الأستاذ."),
            )
            return redirect("accounting:dashboard")
    else:
        today = timezone.now().date()
        initial = {
            "year": today.year,
            "start_date": today.replace(month=1, day=1),
            "end_date": today.replace(month=12, day=31),
            "is_closed": False,
        }
        form = FiscalYearForm(initial=initial)

    return render(
        request,
        "accounting/setup/fiscal_year_setup.html",
        {"form": form},
    )


class FiscalYearListView(StaffRequiredMixin, ListView):
    model = FiscalYear
    template_name = "accounting/settings/fiscal_year_list.html"
    context_object_name = "years"

    def get_queryset(self):
        return FiscalYear.objects.all().order_by("-start_date")


class FiscalYearCreateView(StaffRequiredMixin, CreateView):
    model = FiscalYear
    form_class = FiscalYearForm
    template_name = "accounting/settings/fiscal_year_form.html"
    success_url = reverse_lazy("accounting:fiscal_year_list")

    def form_valid(self, form):
        messages.success(self.request, _("تم إنشاء السنة المالية بنجاح"))
        return super().form_valid(form)


class FiscalYearUpdateView(StaffRequiredMixin, UpdateView):
    model = FiscalYear
    form_class = FiscalYearForm
    template_name = "accounting/settings/fiscal_year_form.html"
    success_url = reverse_lazy("accounting:fiscal_year_list")

    def form_valid(self, form):
        fy = form.instance
        if fy.is_closed:
            messages.warning(self.request, _("لا يمكن تعديل سنة مالية مقفلة"))
            return redirect("accounting:fiscal_year_list")
        messages.success(self.request, _("تم تحديث بيانات السنة المالية"))
        return super().form_valid(form)


class FiscalYearCloseView(StaffRequiredMixin, View):
    def post(self, request, pk):
        fy = get_object_or_404(FiscalYear, pk=pk)
        fy.is_closed = True
        fy.save()
        messages.success(request, _("تم إقفال السنة المالية"))
        return redirect("accounting:fiscal_year_list")


# ============================================================
# Accounts & Chart of Accounts
# ============================================================


class AccountListView(FiscalYearRequiredMixin, StaffRequiredMixin, ListView):
    model = Account
    template_name = "accounting/accounts/list.html"
    context_object_name = "accounts"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["ledger_section"] = "accounts"
        return ctx


class AccountCreateView(FiscalYearRequiredMixin, StaffRequiredMixin, CreateView):
    model = Account
    form_class = AccountForm
    template_name = "accounting/accounts/form.html"

    def get_success_url(self):
        messages.success(self.request, _("تم إنشاء الحساب بنجاح."))
        return reverse("accounting:account_list")


class AccountUpdateView(FiscalYearRequiredMixin, StaffRequiredMixin, UpdateView):
    model = Account
    form_class = AccountForm
    template_name = "accounting/accounts/form.html"

    def get_success_url(self):
        messages.success(self.request, _("تم تحديث الحساب بنجاح."))
        return reverse("accounting:account_list")


@ledger_staff_required
def chart_of_accounts_bootstrap_view(request):
    """
    إنشاء شجرة حسابات افتراضية مرة واحدة.
    """
    created = ensure_default_chart_of_accounts()

    if created > 0:
        messages.success(
            request,
            _("تم إنشاء شجرة الحسابات الافتراضية (%(count)d حسابًا).")
            % {"count": created},
        )
    else:
        messages.info(
            request,
            _("لم يتم إنشاء أي حسابات جديدة، يبدو أن شجرة الحسابات موجودة مسبقًا."),
        )

    return redirect("accounting:account_list")


@ledger_staff_required
def chart_of_accounts_import_view(request):
    """
    استيراد شجرة الحسابات من ملف إكسل.
    """
    if request.method == "POST":
        form = ChartOfAccountsImportForm(request.POST, request.FILES)
        if form.is_valid():
            file_obj = form.cleaned_data["file"]
            replace_existing = form.cleaned_data["replace_existing"]
            fiscal_year = form.cleaned_data.get("fiscal_year")

            try:
                result = import_chart_of_accounts_from_excel(
                    file_obj,
                    replace_existing=replace_existing,
                    fiscal_year=fiscal_year,
                )
            except ValidationError as e:
                messages.error(
                    request,
                    getattr(e, "message", str(e)),
                )
                return render(
                    request,
                    "accounting/setup/import.html",
                    {"form": form},
                )

            messages.success(
                request,
                _(
                    "تم استيراد شجرة الحسابات. "
                    "حسابات جديدة: %(created)d، محدثة: %(updated)d، "
                    "تم تعطيلها: %(deactivated)d."
                )
                % {
                    "created": result["created"],
                    "updated": result["updated"],
                    "deactivated": result["deactivated"],
                },
            )

            if result["errors"]:
                messages.warning(
                    request,
                    _("انتهى الاستيراد مع بعض الملاحظات (راجع الكونسول)."),
                )
                for err in result["errors"]:
                    print(f"[CoA Import] {err}")

            return redirect("accounting:account_list")
    else:
        form = ChartOfAccountsImportForm()

    return render(
        request,
        "accounting/setup/import.html",
        {"form": form},
    )


@ledger_staff_required
def chart_of_accounts_export_view(request):
    """
    تصدير شجرة الحسابات الحالية إلى ملف Excel.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Chart of Accounts"

    headers = ["code", "name", "type", "parent_code", "allow_settlement", "is_active"]
    ws.append(headers)

    for acc in Account.objects.order_by("code"):
        ws.append(
            [
                acc.code,
                acc.name,
                acc.type,
                acc.parent.code if acc.parent else "",
                1 if getattr(acc, "allow_settlement", False) else 0,
                1 if getattr(acc, "is_active", True) else 0,
            ]
        )

    response = HttpResponse(
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    )
    response["Content-Disposition"] = 'attachment; filename="chart_of_accounts.xlsx"'
    wb.save(response)
    return response


# ============================================================
# Journal entries (CRUD + post/unpost)
# ============================================================


class JournalEntryListView(FiscalYearRequiredMixin, StaffRequiredMixin, ListView):
    """
    قائمة قيود اليومية مع فلاتر (نص، تاريخ، حالة، دفتر).
    """
    model = JournalEntry
    template_name = "accounting/journal/list.html"
    context_object_name = "entries"
    paginate_by = 50

    def get_filter_form(self):
        if not hasattr(self, "_filter_form"):
            self._filter_form = JournalEntryFilterForm(self.request.GET or None)
        return self._filter_form

    def get_queryset(self):
        qs = (
            JournalEntry.objects.with_totals()
            .select_related("journal")
            .order_by("-date", "-id")
        )

        form = self.get_filter_form()
        if not form.is_valid():
            return qs

        q = form.cleaned_data.get("q")
        date_from = form.cleaned_data.get("date_from")
        date_to = form.cleaned_data.get("date_to")
        posted = form.cleaned_data.get("posted")
        journal = form.cleaned_data.get("journal")

        if q:
            qs = qs.filter(
                Q(reference__icontains=q) | Q(description__icontains=q)
            )

        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)

        if posted == "posted":
            qs = qs.posted()
        elif posted == "draft":
            qs = qs.unposted()

        if journal:
            qs = qs.filter(journal=journal)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        ctx["filter_form"] = self.get_filter_form()

        query_dict = self.request.GET.copy()
        query_dict.pop("page", None)
        ctx["current_query"] = query_dict.urlencode()
        ctx["ledger_section"] = "entries"

        return ctx


class JournalEntryDetailView(FiscalYearRequiredMixin, StaffRequiredMixin, DetailView):
    section = "entries"
    model = JournalEntry
    template_name = "accounting/journal/detail.html"
    context_object_name = "entry"


class JournalEntryCreateView(FiscalYearRequiredMixin, StaffRequiredMixin, View):
    """
    إنشاء قيد يومية يدوي:
    - يسبق التاريخ اليوم
    - يضع دفتر افتراضي للقيد اليدوي إن وجد
    - يتحقق من توازن القيد قبل الحفظ
    """
    template_name = "accounting/journal/form.html"

    def get(self, request, *args, **kwargs):
        initial = {
            "date": timezone.now().date(),
        }

        default_journal = get_default_journal_for_manual_entry()
        if default_journal is not None:
            initial["journal"] = default_journal

        entry_form = JournalEntryForm(initial=initial)
        line_formset = JournalLineFormSet()
        return render(
            request,
            self.template_name,
            {
                "entry_form": entry_form,
                "line_formset": line_formset,
            },
        )

    def post(self, request, *args, **kwargs):
        entry_form = JournalEntryForm(request.POST)
        line_formset = JournalLineFormSet(request.POST)

        if not (entry_form.is_valid() and line_formset.is_valid()):
            messages.error(request, _("الرجاء تصحيح الأخطاء في النموذج."))
            return render(
                request,
                self.template_name,
                {
                    "entry_form": entry_form,
                    "line_formset": line_formset,
                },
            )

        try:
            with transaction.atomic():
                date = entry_form.cleaned_data.get("date")
                ensure_open_fiscal_year_for_date(date)

                entry = entry_form.save(commit=False)
                entry.created_by = request.user
                entry.save()

                lines, total_debit, total_credit = build_lines_from_formset(
                    line_formset
                )

                if total_debit != total_credit:
                    raise ValidationError(
                        _(
                            "القيد غير متوازن: مجموع المدين لا يساوي مجموع الدائن."
                        )
                    )

                for line_data in lines:
                    JournalLine.objects.create(entry=entry, **line_data)

        except ValidationError as e:
            messages.error(request, e.messages[0])
            return render(
                request,
                self.template_name,
                {
                    "entry_form": entry_form,
                    "line_formset": line_formset,
                },
            )

        messages.success(request, _("تم إنشاء قيد اليومية بنجاح."))
        return redirect("accounting:journal_entry_detail", pk=entry.pk)


class JournalEntryUpdateView(FiscalYearRequiredMixin, StaffRequiredMixin, View):
    """
    تعديل قيد يومية غير مرحّل باستخدام نفس نموذج الإنشاء.
    """
    template_name = "accounting/journal/form.html"

    def get_entry(self):
        return get_object_or_404(JournalEntry, pk=self.kwargs["pk"])

    def dispatch(self, request, *args, **kwargs):
        self.entry = self.get_entry()

        if self.entry.posted:
            messages.error(request, _("لا يمكن تعديل قيد مُرحّل."))
            return redirect("accounting:journal_entry_detail", pk=self.entry.pk)

        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        entry_form = JournalEntryForm(instance=self.entry)

        initial = []
        for line in self.entry.lines.all().order_by("order", "id"):
            initial.append(
                {
                    "account": line.account,
                    "description": line.description,
                    "debit": line.debit,
                    "credit": line.credit,
                }
            )
        line_formset = JournalLineFormSet(initial=initial)

        return render(
            request,
            self.template_name,
            {
                "entry_form": entry_form,
                "line_formset": line_formset,
                "entry": self.entry,
                "is_update": True,
            },
        )

    def post(self, request, *args, **kwargs):
        entry_form = JournalEntryForm(request.POST, instance=self.entry)
        line_formset = JournalLineFormSet(request.POST)

        if not (entry_form.is_valid() and line_formset.is_valid()):
            messages.error(request, _("الرجاء تصحيح الأخطاء في النموذج."))
            return render(
                request,
                self.template_name,
                {
                    "entry_form": entry_form,
                    "line_formset": line_formset,
                    "entry": self.entry,
                    "is_update": True,
                },
            )

        try:
            with transaction.atomic():
                date = entry_form.cleaned_data.get("date")
                ensure_open_fiscal_year_for_date(date)

                entry = entry_form.save(commit=False)

                lines, total_debit, total_credit = build_lines_from_formset(
                    line_formset
                )

                if total_debit != total_credit:
                    raise ValidationError(
                        _(
                            "القيد غير متوازن: مجموع المدين لا يساوي مجموع الدائن."
                        )
                    )

                entry.save()

                self.entry.lines.all().delete()
                for line_data in lines:
                    JournalLine.objects.create(entry=entry, **line_data)

        except ValidationError as e:
            messages.error(request, e.messages[0])
            return render(
                request,
                self.template_name,
                {
                    "entry_form": entry_form,
                    "line_formset": line_formset,
                    "entry": self.entry,
                    "is_update": True,
                },
            )

        messages.success(request, _("تم تحديث قيد اليومية بنجاح."))
        return redirect("accounting:journal_entry_detail", pk=entry.pk)


@ledger_staff_required
@fiscal_year_required
def journalentry_post_view(request, pk):
    """
    ترحيل قيد اليومية.
    """
    entry = get_object_or_404(JournalEntry, pk=pk)
    next_url = request.POST.get("next") or request.GET.get("next")

    if request.method != "POST":
        if next_url:
            return redirect(next_url)
        return redirect("accounting:journal_entry_detail", pk=entry.pk)

    if entry.posted:
        messages.info(request, _("القيد مُرحّل بالفعل."))
        if next_url:
            return redirect(next_url)
        return redirect("accounting:journal_entry_detail", pk=entry.pk)

    if not entry.is_balanced:
        messages.error(request, _("لا يمكن ترحيل قيد غير متوازن."))
        if next_url:
            return redirect(next_url)
        return redirect("accounting:journal_entry_detail", pk=entry.pk)

    fy = entry.fiscal_year or FiscalYear.for_date(entry.date)
    if fy is None:
        messages.error(
            request,
            _("لا توجد سنة مالية تغطي تاريخ هذا القيد، لا يمكن ترحيله."),
        )
        if next_url:
            return redirect(next_url)
        return redirect("accounting:journal_entry_detail", pk=entry.pk)

    if fy.is_closed:
        messages.error(
            request,
            _("لا يمكن ترحيل قيد ضمن سنة مالية مقفلة."),
        )
        if next_url:
            return redirect(next_url)
        return redirect("accounting:journal_entry_detail", pk=entry.pk)

    with transaction.atomic():
        entry.posted = True
        entry.posted_at = timezone.now()
        entry.posted_by = request.user
        entry.save(update_fields=["posted", "posted_at", "posted_by"])

    messages.success(request, _("تم ترحيل القيد بنجاح."))

    if next_url:
        return redirect(next_url)
    return redirect("accounting:journal_entry_detail", pk=entry.pk)


@ledger_staff_required
@fiscal_year_required
def journalentry_unpost_view(request, pk):
    """
    إلغاء ترحيل قيد يومية.
    """
    entry = get_object_or_404(JournalEntry, pk=pk)
    next_url = request.POST.get("next") or request.GET.get("next")

    if request.method != "POST":
        if next_url:
            return redirect(next_url)
        return redirect("accounting:journal_entry_detail", pk=entry.pk)

    if not entry.posted:
        messages.info(request, _("القيد غير مُرحّل."))
        if next_url:
            return redirect(next_url)
        return redirect("accounting:journal_entry_detail", pk=entry.pk)

    fy = entry.fiscal_year or FiscalYear.for_date(entry.date)
    if fy and fy.is_closed:
        messages.error(
            request,
            _("لا يمكن إلغاء ترحيل قيد ضمن سنة مالية مقفلة."),
        )
        if next_url:
            return redirect(next_url)
        return redirect("accounting:journal_entry_detail", pk=entry.pk)

    with transaction.atomic():
        entry.posted = False
        entry.posted_at = None
        entry.posted_by = None
        entry.save(update_fields=["posted", "posted_at", "posted_by"])

    messages.success(request, _("تم إلغاء ترحيل القيد بنجاح."))

    if next_url:
        return redirect(next_url)
    return redirect("accounting:journal_entry_detail", pk=entry.pk)


# ============================================================
# Reports (Trial balance / Account ledger)
# ============================================================


@ledger_staff_required
@fiscal_year_required
def trial_balance_view(request):
    form = TrialBalanceFilterForm(request.GET or None)
    rows = None
    totals = None
    effective_fiscal_year = None

    qs = (
        JournalLine.objects
        .posted()
        .select_related("account", "entry")
    )

    if form.is_valid():
        fiscal_year = form.cleaned_data.get("fiscal_year")
        date_from = form.cleaned_data.get("date_from")
        date_to = form.cleaned_data.get("date_to")

        effective_fiscal_year = fiscal_year
        if not effective_fiscal_year and not date_from and not date_to:
            effective_fiscal_year = FiscalYear.objects.filter(
                is_default=True,
                is_closed=False,
            ).first()

            if not effective_fiscal_year:
                today = timezone.now().date()
                effective_fiscal_year = FiscalYear.for_date(today)

        if effective_fiscal_year:
            qs = qs.filter(entry__fiscal_year=effective_fiscal_year)
        else:
            qs = qs.within_period(date_from, date_to)

        rows = (
            qs.values(
                "account__code",
                "account__name",
                "account__type",
            )
            .annotate(
                debit=Coalesce(
                    Sum("debit"),
                    Value(0),
                    output_field=DecimalField(max_digits=12, decimal_places=3),
                ),
                credit=Coalesce(
                    Sum("credit"),
                    Value(0),
                    output_field=DecimalField(max_digits=12, decimal_places=3),
                ),
            )
            .order_by("account__code")
        )

        totals = rows.aggregate(
            total_debit=Coalesce(
                Sum("debit"),
                Value(0),
                output_field=DecimalField(max_digits=12, decimal_places=3),
            ),
            total_credit=Coalesce(
                Sum("credit"),
                Value(0),
                output_field=DecimalField(max_digits=12, decimal_places=3),
            ),
        )

    context = {
        "form": form,
        "rows": rows,
        "totals": totals,
        "effective_fiscal_year": effective_fiscal_year,
        "ledger_section": "reports",
    }
    return render(request, "accounting/reports/trial_balance.html", context)


@ledger_staff_required
@fiscal_year_required
def account_ledger_view(request):
    form = AccountLedgerFilterForm(request.GET or None)

    account = None
    opening_balance = Decimal("0")
    running_lines = []
    effective_fiscal_year = None

    if form.is_valid():
        account = form.cleaned_data.get("account")
        fiscal_year = form.cleaned_data.get("fiscal_year")
        date_from = form.cleaned_data.get("date_from")
        date_to = form.cleaned_data.get("date_to")

        if account:
            lines_qs = (
                JournalLine.objects
                .posted()
                .select_related("entry")
                .filter(account=account)
            )

            effective_fiscal_year = fiscal_year
            if not effective_fiscal_year and not date_from and not date_to:
                effective_fiscal_year = FiscalYear.objects.filter(
                    is_default=True,
                    is_closed=False,
                ).first()

                if not effective_fiscal_year:
                    today = timezone.now().date()
                    effective_fiscal_year = FiscalYear.for_date(today)

            if effective_fiscal_year:
                lines_qs = lines_qs.filter(entry__fiscal_year=effective_fiscal_year)
            else:
                lines_qs = lines_qs.within_period(date_from, date_to)

            lines_qs = lines_qs.order_by("entry__date", "entry_id", "id")

            def calculate_balance(account_type, debit, credit):
                debit = debit or Decimal("0")
                credit = credit or Decimal("0")
                if account_type in [Account.Type.ASSET, Account.Type.EXPENSE]:
                    return debit - credit
                return credit - debit

            if effective_fiscal_year or date_from:
                opening_qs = JournalLine.objects.posted().filter(account=account)

                if effective_fiscal_year:
                    opening_qs = opening_qs.filter(
                        entry__date__lt=effective_fiscal_year.start_date
                    )
                else:
                    opening_qs = opening_qs.filter(entry__date__lt=date_from)

                opening_totals = opening_qs.aggregate(
                    debit=Coalesce(
                        Sum("debit"),
                        Value(0),
                        output_field=DecimalField(max_digits=12, decimal_places=3),
                    ),
                    credit=Coalesce(
                        Sum("credit"),
                        Value(0),
                        output_field=DecimalField(max_digits=12, decimal_places=3),
                    ),
                )
                opening_balance = calculate_balance(
                    account.type,
                    opening_totals["debit"],
                    opening_totals["credit"],
                )

            balance = opening_balance
            for line in lines_qs:
                delta = calculate_balance(
                    account.type,
                    line.debit,
                    line.credit,
                )
                balance += delta
                running_lines.append(
                    {
                        "date": line.entry.date,
                        "entry_id": line.entry.id,
                        "entry_number": line.entry.display_number,
                        "reference": line.entry.reference or "-",
                        "description": line.description or line.entry.description,
                        "debit": line.debit or Decimal("0"),
                        "credit": line.credit or Decimal("0"),
                        "balance": balance,
                    }
                )

    context = {
        "form": form,
        "account": account,
        "opening_balance": opening_balance,
        "lines": running_lines,
        "effective_fiscal_year": effective_fiscal_year,
        "ledger_section": "reports",
    }
    return render(request, "accounting/reports/account_ledger.html", context)


# ============================================================
# Ledger settings & Journals (master data)
# ============================================================


@ledger_staff_required
def ledger_settings_view(request):
    """
    شاشة إعدادات دفتر الأستاذ:
    ربط دفاتر اليومية بوظائف النظام (مبيعات، مشتريات، بنك، كاش، رصيد افتتاحي، إقفال).
    """
    settings_obj = LedgerSettings.get_solo()

    if request.method == "POST":
        form = LedgerSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, _("تم حفظ إعدادات دفاتر اليومية بنجاح."))
            return redirect("accounting:ledger_settings")
    else:
        form = LedgerSettingsForm(instance=settings_obj)

    return render(
        request,
        "accounting/settings/ledger_settings_form.html",
        {
            "form": form,
            "ledger_section": "settings",
        },
    )


@ledger_staff_required
def journal_list_view(request):
    """
    عرض قائمة دفاتر اليومية.
    """
    journals = Journal.objects.all().order_by("code")
    return render(
        request,
        "accounting/settings/journal/list.html",
        {"journals": journals},
    )


@ledger_staff_required
def journal_create_view(request):
    """
    إنشاء دفتر يومية جديد.
    """
    if request.method == "POST":
        form = JournalForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _("تم إنشاء دفتر اليومية بنجاح."))
            return redirect("accounting:journal_list")
    else:
        form = JournalForm()

    return render(
        request,
        "accounting/settings/journal/form.html",
        {
            "form": form,
            "title": _("دفتر جديد"),
        },
    )


@ledger_staff_required
def journal_update_view(request, pk):
    """
    تعديل دفتر يومية.
    """
    journal = get_object_or_404(Journal, pk=pk)

    if request.method == "POST":
        form = JournalForm(request.POST, instance=journal)
        if form.is_valid():
            form.save()
            messages.success(request, _("تم تحديث دفتر اليومية بنجاح."))
            return redirect("accounting:journal_list")
    else:
        form = JournalForm(instance=journal)

    return render(
        request,
        "accounting/settings/journal/form.html",
        {
            "form": form,
            "title": _("تعديل دفتر"),
            "journal": journal,
        },
    )


def invoice_confirm_view(request):
    return None


def invoice_unpost_view(request):
    return None