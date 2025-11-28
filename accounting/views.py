# accounting/views.py

from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum, Value, DecimalField, F
from django.db.models.functions import Coalesce
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
    DeleteView, FormView,
)
from openpyxl import Workbook
from openpyxl.styles import Font

from contacts.models import Contact

from core.views.attachments import AttachmentPanelMixin  # (لو تحتاجه لاحقاً)
from .mixins import ProductJsonMixin
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
    PaymentForm, PaymentReconciliationForm,
)
from .models import (
    Account,
    FiscalYear,
    Invoice,
    Journal,
    JournalEntry,
    JournalLine,
    LedgerSettings,
    Payment,
    PaymentMethod,
    Settings,
)
from .services import (
    build_lines_from_formset,
    ensure_default_chart_of_accounts,
    import_chart_of_accounts_from_excel, allocate_payment_to_invoices, clear_payment_allocations,
)


# ============================================================
# Permissions & Mixins
# ============================================================

def user_has_accounting_access(user):
    if not (user.is_authenticated and user.is_active):
        return False
    if user.is_staff or user.is_superuser:
        return True
    return user.groups.filter(name="accounting_staff").exists()


def ledger_staff_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not user_has_accounting_access(request.user):
            messages.error(request, _("عذراً، ليس لديك صلاحية للوصول لهذه الصفحة."))
            return redirect("dashboard:index")
        return view_func(request, *args, **kwargs)

    return _wrapped_view


class AccountingStaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    مكسين لصلاحيات المحاسبة (يستخدم في جميع فيوز المحاسبة تقريبًا).
    """

    raise_exception = False

    def test_func(self):
        return user_has_accounting_access(self.request.user)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        messages.error(self.request, _("عذراً، ليس لديك صلاحية للوصول لهذه الصفحة."))
        return redirect("dashboard:index")


class AccountingSectionMixin:
    """
    مكسين بسيط لحمل اسم التبويب الحالي في الـ navbar.
    """

    accounting_section = None

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.accounting_section:
            ctx["accounting_section"] = self.accounting_section
        return ctx


class AccountingBaseView(AccountingStaffRequiredMixin, AccountingSectionMixin):
    """
    Base mixin يُستخدم في معظم فيوز المحاسبة
    (صلاحيات + تفعيل التبويب في النافبار).
    """
    pass


class FiscalYearRequiredMixin:
    """
    مكسين للتأكد من وجود سنة مالية واحدة على الأقل قبل السماح بالدخول.
    """

    def dispatch(self, request, *args, **kwargs):
        if not FiscalYear.objects.exists():
            messages.warning(request, _("يجب إعداد سنة مالية أولاً."))
            return redirect("accounting:fiscal_year_create")
        return super().dispatch(request, *args, **kwargs)


def ensure_open_fiscal_year_for_date(date):
    if not date:
        raise ValidationError(_("يجب تحديد التاريخ."))

    fy = FiscalYear.for_date(date)
    if not fy:
        raise ValidationError(_("لا توجد سنة مالية تغطي هذا التاريخ."))
    if fy.is_closed:
        raise ValidationError(_("السنة المالية لهذا التاريخ مقفلة."))
    return fy


# ============================================================
# Dashboard
# ============================================================

class AccountingDashboardView(AccountingBaseView, TemplateView):
    accounting_section = "dashboard"
    template_name = "accounting/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        ctx.update({
            "invoices_count": Invoice.objects.count(),
            "unposted_entries": JournalEntry.objects.unposted().count(),
            "recent_invoices": Invoice.objects.order_by("-created_at")[:5],
            "recent_payments": Payment.objects.order_by("-date")[:5],
            "sales_total_amount":
                Invoice.objects.filter(type=Invoice.InvoiceType.SALES).aggregate(s=Sum('total_amount'))['s'] or 0,
            "purchase_total_amount":
                Invoice.objects.filter(type=Invoice.InvoiceType.PURCHASE).aggregate(s=Sum('total_amount'))['s'] or 0,
            "sales_invoice_count": Invoice.objects.filter(type=Invoice.InvoiceType.SALES).count(),
            "purchase_invoice_count": Invoice.objects.filter(type=Invoice.InvoiceType.PURCHASE).count(),
            "payments_receipt_total": Payment.objects.filter(type=Payment.Type.RECEIPT).aggregate(s=Sum('amount'))[
                                          's'] or 0,
            "payments_payment_total": Payment.objects.filter(type=Payment.Type.PAYMENT).aggregate(s=Sum('amount'))[
                                          's'] or 0,
            "recent_sales_invoices": Invoice.objects.filter(type=Invoice.InvoiceType.SALES).order_by('-id')[:5],
            "key_accounts": Account.objects.filter(parent__isnull=True)[:5],
        })
        return ctx


# ============================================================
# Invoices (Base Logic)
# ============================================================

class BaseInvoiceListView(AccountingBaseView, ListView):
    model = Invoice
    template_name = "accounting/invoices/list.html"
    context_object_name = "invoices"
    paginate_by = 20
    invoice_type = None  # SALES / PURCHASE

    def get_queryset(self):
        qs = super().get_queryset().select_related("customer")
        if self.invoice_type:
            qs = qs.filter(type=self.invoice_type)

        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)

        return qs.order_by("-issued_at", "-id")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['invoice_type'] = self.invoice_type
        ctx['status_filter'] = self.request.GET.get('status', '')
        return ctx


class SalesInvoiceListView(BaseInvoiceListView):
    invoice_type = Invoice.InvoiceType.SALES
    accounting_section = "sales_invoices"


class PurchaseInvoiceListView(BaseInvoiceListView):
    invoice_type = Invoice.InvoiceType.PURCHASE
    accounting_section = "purchase_invoices"


class BaseInvoiceCreateView(AccountingBaseView, ProductJsonMixin, CreateView):
    model = Invoice
    form_class = InvoiceForm
    template_name = "accounting/invoices/form.html"
    invoice_type = None  # SALES / PURCHASE

    def get_initial(self):
        initial = super().get_initial()
        settings = Settings.get_solo()
        if settings.default_terms:
            initial["terms"] = settings.default_terms
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["item_formset"] = InvoiceItemFormSet(self.request.POST)
        else:
            ctx["item_formset"] = InvoiceItemFormSet()

        ctx = self.inject_products_json(ctx)
        ctx["invoice_type"] = self.invoice_type
        ctx["title"] = _("فاتورة جديدة")
        return ctx

    def form_valid(self, form):
        context = self.get_context_data()
        item_formset = context["item_formset"]

        if item_formset.is_valid():
            with transaction.atomic():
                self.object = form.save(commit=False)
                if self.invoice_type:
                    self.object.type = self.invoice_type
                self.object.save()

                item_formset.instance = self.object
                item_formset.save()

                self.object.recalculate_totals()

            messages.success(self.request, _("تم حفظ الفاتورة بنجاح."))
            return redirect(self.get_success_url())
        else:
            return self.render_to_response(self.get_context_data(form=form))

    def get_success_url(self):
        if self.object.type == Invoice.InvoiceType.SALES:
            return reverse("accounting:sales_invoice_detail", kwargs={"pk": self.object.pk})
        return reverse("accounting:purchase_invoice_detail", kwargs={"pk": self.object.pk})


class SalesInvoiceCreateView(BaseInvoiceCreateView):
    invoice_type = Invoice.InvoiceType.SALES
    accounting_section = "sales_invoices"


class PurchaseInvoiceCreateView(BaseInvoiceCreateView):
    invoice_type = Invoice.InvoiceType.PURCHASE
    accounting_section = "purchase_invoices"


class InvoiceDetailView(AccountingBaseView, DetailView):
    model = Invoice
    template_name = "accounting/invoices/detail.html"
    context_object_name = "invoice"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['invoice_type'] = self.object.type
        if self.object.type == Invoice.InvoiceType.SALES:
            ctx["accounting_section"] = "sales_invoices"
        else:
            ctx["accounting_section"] = "purchase_invoices"
        return ctx


class InvoiceUpdateView(AccountingBaseView, ProductJsonMixin, UpdateView):
    model = Invoice
    form_class = InvoiceForm
    template_name = "accounting/invoices/form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["item_formset"] = InvoiceItemFormSet(self.request.POST, instance=self.object)
        else:
            ctx["item_formset"] = InvoiceItemFormSet(instance=self.object)

        ctx = self.inject_products_json(ctx)
        ctx["title"] = _("تعديل الفاتورة")
        ctx['invoice_type'] = self.object.type

        if self.object.type == Invoice.InvoiceType.SALES:
            ctx["accounting_section"] = "sales_invoices"
        else:
            ctx["accounting_section"] = "purchase_invoices"

        return ctx

    def form_valid(self, form):
        context = self.get_context_data()
        item_formset = context["item_formset"]

        if item_formset.is_valid():
            with transaction.atomic():
                self.object = form.save()
                item_formset.save()
                self.object.recalculate_totals()

            messages.success(self.request, _("تم تحديث الفاتورة بنجاح."))
            return redirect(self.get_success_url())
        else:
            return self.render_to_response(self.get_context_data(form=form))

    def get_success_url(self):
        if self.object.type == Invoice.InvoiceType.SALES:
            return reverse("accounting:sales_invoice_detail", kwargs={"pk": self.object.pk})
        return reverse("accounting:purchase_invoice_detail", kwargs={"pk": self.object.pk})


class InvoicePrintView(AccountingStaffRequiredMixin, DetailView):
    model = Invoice
    template_name = "accounting/invoices/print.html"


def invoice_confirm_view(request, pk):
    messages.info(request, "ميزة الاعتماد قيد التطوير.")
    return redirect("accounting:sales_invoice_detail", pk=pk)


def invoice_unpost_view(request, pk):
    messages.info(request, "ميزة إلغاء الترحيل قيد التطوير.")
    return redirect("accounting:sales_invoice_detail", pk=pk)


# ============================================================
# Payments
# ============================================================

class PaymentListView(AccountingBaseView, ListView):
    model = Payment
    template_name = "accounting/payment/list.html"
    context_object_name = "reconcile"
    accounting_section = "reconcile"
    paginate_by = 25


class PaymentCreateView(AccountingBaseView, CreateView):
    model = Payment
    form_class = PaymentForm
    template_name = "accounting/payment/form.html"
    accounting_section = "reconcile"
    success_url = reverse_lazy("accounting:payment_list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, _("تم إنشاء السند بنجاح."))
        return super().form_valid(form)


class PaymentUpdateView(AccountingBaseView, UpdateView):
    model = Payment
    form_class = PaymentForm
    template_name = "accounting/payment/form.html"
    accounting_section = "reconcile"
    success_url = reverse_lazy("accounting:payment_list")


class PaymentDetailView(AccountingBaseView, DetailView):
    model = Payment
    template_name = "accounting/payment/detail.html"
    accounting_section = "reconcile"


class PaymentDeleteView(AccountingStaffRequiredMixin, DeleteView):
    model = Payment
    success_url = reverse_lazy("accounting:payment_list")
    template_name = "accounting/confirm_delete.html"


# ============================================================
# Journals & Entries
# ============================================================

class JournalListView(AccountingBaseView, ListView):
    model = Journal
    template_name = "accounting/settings/journal/list.html"
    context_object_name = "journals"
    accounting_section = "settings"


class JournalCreateView(AccountingBaseView, CreateView):
    model = Journal
    form_class = JournalForm
    template_name = "accounting/settings/journal/form.html"
    success_url = reverse_lazy("accounting:journal_list")
    accounting_section = "settings"


class JournalUpdateView(AccountingBaseView, UpdateView):
    model = Journal
    form_class = JournalForm
    template_name = "accounting/settings/journal/form.html"
    success_url = reverse_lazy("accounting:journal_list")
    accounting_section = "settings"


class JournalEntryListView(AccountingBaseView, ListView):
    model = JournalEntry
    template_name = "accounting/journal/list.html"
    context_object_name = "entries"
    paginate_by = 50
    accounting_section = "entries"

    def get_queryset(self):
        qs = JournalEntry.objects.select_related("journal").order_by("-date", "-id")

        q = self.request.GET.get('q')
        posted = self.request.GET.get('posted')

        if q:
            qs = qs.filter(Q(reference__icontains=q) | Q(description__icontains=q))

        if posted == 'posted':
            qs = qs.filter(posted=True)
        elif posted == 'draft':
            qs = qs.filter(posted=False)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = JournalEntryFilterForm(self.request.GET)
        return ctx


class JournalEntryCreateView(
    FiscalYearRequiredMixin, AccountingBaseView, CreateView
):
    model = JournalEntry
    form_class = JournalEntryForm
    template_name = "accounting/journal/form.html"
    accounting_section = "entries"
    context_object_name = "entry"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["line_formset"] = JournalLineFormSet(self.request.POST)
        else:
            ctx["line_formset"] = JournalLineFormSet()
        return ctx

    def get_initial(self):
        initial = super().get_initial()
        initial["date"] = timezone.now().date()
        try:
            settings = LedgerSettings.get_solo()
            if settings.default_manual_journal:
                initial["journal"] = settings.default_manual_journal
        except Exception:
            pass
        return initial

    def form_valid(self, form):
        context = self.get_context_data()
        line_formset = context["line_formset"]

        if not line_formset.is_valid():
            print("DEBUG: Formset Errors:", line_formset.errors)
            print("DEBUG: Non-form Errors:", line_formset.non_form_errors)

            messages.error(self.request, _("هناك خطأ في إدخال البيانات، راجع الحقول."))
            return self.render_to_response(self.get_context_data(form=form))

        try:
            with transaction.atomic():
                ensure_open_fiscal_year_for_date(form.cleaned_data['date'])

                self.object = form.save(commit=False)
                self.object.created_by = self.request.user
                self.object.save()

                lines, dr, cr = build_lines_from_formset(line_formset)

                diff = dr - cr
                if abs(diff) > Decimal("0.001"):
                    raise ValidationError(
                        _("القيد غير متوازن.\nالمدين: %(dr)s | الدائن: %(cr)s | الفرق: %(diff)s")
                        % {'dr': dr, 'cr': cr, 'diff': diff}
                    )

                for line_data in lines:
                    JournalLine.objects.create(entry=self.object, **line_data)

            messages.success(self.request, _("تم حفظ القيد بنجاح."))
            return redirect("accounting:journal_entry_detail", pk=self.object.pk)

        except ValidationError as e:
            error_msg = e.message if hasattr(e, 'message') else str(e)
            form.add_error(None, error_msg)
            return self.render_to_response(self.get_context_data(form=form))


class JournalEntryUpdateView(AccountingBaseView, UpdateView):
    model = JournalEntry
    form_class = JournalEntryForm
    template_name = "accounting/journal/form.html"
    accounting_section = "entries"
    context_object_name = "entry"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if 'line_formset' not in ctx:
            if self.request.POST:
                ctx["line_formset"] = JournalLineFormSet(self.request.POST)
            else:
                initial_lines = []
                for line in self.object.lines.all().order_by('order'):
                    initial_lines.append({
                        'account': line.account,
                        'description': line.description,
                        'debit': line.debit,
                        'credit': line.credit
                    })
                ctx["line_formset"] = JournalLineFormSet(initial=initial_lines)
        ctx["is_update"] = True
        return ctx

    def form_valid(self, form):
        if self.object.posted:
            messages.error(self.request, _("لا يمكن تعديل قيد مرحل."))
            return redirect("accounting:journal_entry_detail", pk=self.object.pk)

        context = self.get_context_data()
        line_formset = context["line_formset"]

        if line_formset.is_valid():
            try:
                with transaction.atomic():
                    ensure_open_fiscal_year_for_date(form.cleaned_data['date'])

                    self.object = form.save()

                    self.object.lines.all().delete()

                    lines, dr, cr = build_lines_from_formset(line_formset)

                    if abs(dr - cr) > Decimal("0.001"):
                        raise ValidationError(
                            _("القيد غير متوازن. الفرق: %(diff)s") % {'diff': abs(dr - cr)}
                        )

                    for line_data in lines:
                        JournalLine.objects.create(entry=self.object, **line_data)

                messages.success(self.request, _("تم تحديث القيد بنجاح."))
                return redirect("accounting:journal_entry_detail", pk=self.object.pk)
            except ValidationError as e:
                form.add_error(None, e.message if hasattr(e, 'message') else str(e))
                return self.render_to_response(self.get_context_data(form=form, line_formset=line_formset))
        else:
            return self.render_to_response(self.get_context_data(form=form, line_formset=line_formset))


class JournalEntryDetailView(AccountingBaseView, DetailView):
    model = JournalEntry
    template_name = "accounting/journal/detail.html"
    context_object_name = "entry"
    accounting_section = "entries"


def journalentry_post_view(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk)

    if request.method != 'POST':
        messages.warning(request, _("عملية غير مسموحة."))
        return redirect("accounting:journal_entry_detail", pk=pk)

    if not entry.is_balanced:
        messages.error(request, _("القيد غير متوازن."))
    else:
        entry.posted = True
        entry.posted_at = timezone.now()
        entry.posted_by = request.user
        entry.save()
        messages.success(request, _("تم ترحيل القيد."))
    return redirect("accounting:journal_entry_detail", pk=pk)


def journalentry_unpost_view(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk)

    if request.method != 'POST':
        messages.warning(request, _("عملية غير مسموحة."))
        return redirect("accounting:journal_entry_detail", pk=pk)

    entry.posted = False
    entry.save()
    messages.success(request, _("تم إلغاء الترحيل."))
    return redirect("accounting:journal_entry_detail", pk=pk)


# ============================================================
# Accounts
# ============================================================

class AccountListView(AccountingBaseView, ListView):
    model = Account
    template_name = "accounting/accounts/list.html"
    context_object_name = "accounts"
    accounting_section = "settings"


class AccountCreateView(AccountingBaseView, CreateView):
    model = Account
    form_class = AccountForm
    template_name = "accounting/accounts/form.html"
    success_url = reverse_lazy("accounting:account_list")
    accounting_section = "settings"


class AccountUpdateView(AccountingBaseView, UpdateView):
    model = Account
    form_class = AccountForm
    template_name = "accounting/accounts/form.html"
    success_url = reverse_lazy("accounting:account_list")
    accounting_section = "settings"


# ============================================================
# Settings & Fiscal Years
# ============================================================

def accounting_settings_view(request):
    settings_obj = Settings.get_solo()
    if request.method == "POST":
        form = SettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, _("تم حفظ الإعدادات."))
            return redirect("accounting:accounting_settings")
    else:
        form = SettingsForm(instance=settings_obj)
    return render(
        request,
        "accounting/settings/settings.html",
        {"form": form, "accounting_section": "settings"},
    )


def ledger_settings_view(request):
    settings = LedgerSettings.get_solo()
    if request.method == "POST":
        form = LedgerSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            form.save()
            messages.success(request, _("تم حفظ إعدادات الدفاتر."))
            return redirect("accounting:ledger_settings")
    else:
        form = LedgerSettingsForm(instance=settings)

    return render(
        request,
        "accounting/settings/ledger_settings_form.html",
        {"form": form, "accounting_section": "settings"},
    )


class FiscalYearListView(AccountingBaseView, ListView):
    model = FiscalYear
    template_name = "accounting/settings/fiscal_year_list.html"
    context_object_name = "years"
    accounting_section = "settings"


class FiscalYearCreateView(AccountingBaseView, CreateView):
    model = FiscalYear
    form_class = FiscalYearForm
    template_name = "accounting/settings/fiscal_year_form.html"
    success_url = reverse_lazy("accounting:fiscal_year_list")
    accounting_section = "settings"


class FiscalYearUpdateView(AccountingBaseView, UpdateView):
    model = FiscalYear
    form_class = FiscalYearForm
    template_name = "accounting/settings/fiscal_year_form.html"
    success_url = reverse_lazy("accounting:fiscal_year_list")
    accounting_section = "settings"


class FiscalYearCloseView(AccountingStaffRequiredMixin, View):
    def post(self, request, pk):
        fy = get_object_or_404(FiscalYear, pk=pk)
        fy.is_closed = True
        fy.save()
        messages.success(request, _("تم إقفال السنة المالية."))
        return redirect("accounting:fiscal_year_list")


# ============================================================
# Chart of Accounts
# ============================================================

@ledger_staff_required
def chart_of_accounts_bootstrap_view(request):
    created = ensure_default_chart_of_accounts()
    if created:
        messages.success(request, _(f"تم إنشاء {created} حساب افتراضي."))
    else:
        messages.info(request, _("الحسابات موجودة مسبقاً."))
    return redirect("accounting:account_list")


@ledger_staff_required
def chart_of_accounts_import_view(request):
    if request.method == "POST":
        form = ChartOfAccountsImportForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                res = import_chart_of_accounts_from_excel(
                    form.cleaned_data['file'],
                    replace_existing=form.cleaned_data['replace_existing'],
                    fiscal_year=form.cleaned_data['fiscal_year']
                )
                messages.success(request, _(f"تم الاستيراد: {res['created']} جديد, {res['updated']} محدث."))
                if res['errors']:
                    for e in res['errors']:
                        messages.warning(request, e)
                return redirect("accounting:account_list")
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = ChartOfAccountsImportForm()
    return render(
        request,
        "accounting/setup/import.html",
        {"form": form, "accounting_section": "settings"},
    )


@ledger_staff_required
def chart_of_accounts_export_view(request):
    wb = Workbook()
    ws = wb.active
    ws.title = "Chart of Accounts"

    headers = ["code", "name", "type", "parent_code", "allow_settlement", "is_active"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for acc in Account.objects.all().select_related('parent').order_by('code'):
        ws.append([
            acc.code,
            acc.name,
            acc.type,
            acc.parent.code if acc.parent else "",
            1 if acc.allow_settlement else 0,
            1 if acc.is_active else 0
        ])

    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename=\"chart_of_accounts.xlsx\"'
    wb.save(response)
    return response


# ============================================================
# Reports
# ============================================================

@ledger_staff_required
def trial_balance_view(request):
    form = TrialBalanceFilterForm(request.GET or None)
    rows = []
    totals = {"debit": Decimal(0), "credit": Decimal(0)}
    report_title = _("ميزان المراجعة")

    qs = JournalLine.objects.filter(entry__posted=True)

    if form.is_valid():
        fiscal_year = form.cleaned_data.get("fiscal_year")
        date_from = form.cleaned_data.get("date_from")
        date_to = form.cleaned_data.get("date_to")

        if fiscal_year:
            qs = qs.filter(entry__fiscal_year=fiscal_year)
        if date_from:
            qs = qs.filter(entry__date__gte=date_from)
        if date_to:
            qs = qs.filter(entry__date__lte=date_to)

    data = qs.values("account__code", "account__name").annotate(
        total_debit=Coalesce(Sum("debit"), Value(0), output_field=DecimalField()),
        total_credit=Coalesce(Sum("credit"), Value(0), output_field=DecimalField())
    ).order_by("account__code")

    for item in data:
        dr = item["total_debit"]
        cr = item["total_credit"]
        if dr == 0 and cr == 0:
            continue
        rows.append({
            "code": item["account__code"],
            "name": item["account__name"],
            "debit": dr,
            "credit": cr
        })
        totals["debit"] += dr
        totals["credit"] += cr

    return render(request, "accounting/reports/trial_balance.html", {
        "form": form,
        "rows": rows,
        "totals": totals,
        "title": report_title,
        "accounting_section": "reports",
    })


@ledger_staff_required
def account_ledger_view(request):
    form = AccountLedgerFilterForm(request.GET or None)
    account = None
    lines = []
    opening_balance = Decimal(0)
    current_balance = Decimal(0)

    if form.is_valid() and form.cleaned_data.get("account"):
        account = form.cleaned_data["account"]
        date_from = form.cleaned_data.get("date_from")

        # Opening Balance Logic
        op_qs = JournalLine.objects.filter(account=account, entry__posted=True)
        if date_from:
            op_qs = op_qs.filter(entry__date__lt=date_from)

        agg = op_qs.aggregate(
            dr=Coalesce(Sum("debit"), Value(0), output_field=DecimalField()),
            cr=Coalesce(Sum("credit"), Value(0), output_field=DecimalField())
        )

        # Standard Accounting Equation
        if account.type in [Account.Type.ASSET, Account.Type.EXPENSE]:
            opening_balance = agg['dr'] - agg['cr']
        else:
            opening_balance = agg['cr'] - agg['dr']

        current_balance = opening_balance

        # Running Lines
        qs = JournalLine.objects.filter(account=account, entry__posted=True).select_related('entry').order_by(
            'entry__date', 'entry__id')
        if date_from:
            qs = qs.filter(entry__date__gte=date_from)
        if form.cleaned_data.get("date_to"):
            qs = qs.filter(entry__date__lte=form.cleaned_data.get("date_to"))

        for line in qs:
            dr = line.debit
            cr = line.credit

            if account.type in [Account.Type.ASSET, Account.Type.EXPENSE]:
                current_balance += (dr - cr)
            else:
                current_balance += (cr - dr)

            lines.append({
                "date": line.entry.date,
                "ref": line.entry.reference,
                "desc": line.description or line.entry.description,
                "debit": dr,
                "credit": cr,
                "balance": current_balance
            })

    return render(request, "accounting/reports/account_ledger.html", {
        "form": form,
        "account": account,
        "lines": lines,
        "opening_balance": opening_balance,
        "closing_balance": current_balance,
        "accounting_section": "reports",
    })


# ============================================================
# Payment Methods Configuration
# ============================================================

class PaymentMethodListView(AccountingBaseView, ListView):
    model = PaymentMethod
    template_name = "accounting/settings/payment_method_list.html"
    context_object_name = "methods"
    accounting_section = "settings"


class PaymentMethodCreateView(AccountingBaseView, CreateView):
    model = PaymentMethod
    fields = ["name", "code", "method_type", "is_active"]
    template_name = "accounting/settings/payment_method_form.html"
    success_url = reverse_lazy("accounting:payment_method_list")
    accounting_section = "settings"

    def form_valid(self, form):
        messages.success(self.request, _("تم إضافة طريقة الدفع بنجاح."))
        return super().form_valid(form)


class PaymentMethodUpdateView(AccountingBaseView, UpdateView):
    model = PaymentMethod
    fields = ["name", "code", "method_type", "is_active"]
    template_name = "accounting/settings/payment_method_form.html"
    success_url = reverse_lazy("accounting:payment_method_list")
    accounting_section = "settings"

    def form_valid(self, form):
        messages.success(self.request, _("تم تحديث طريقة الدفع."))
        return super().form_valid(form)


class PaymentPrintView(AccountingStaffRequiredMixin, DetailView):
    model = Payment
    template_name = "accounting/payment/print.html"
    context_object_name = "payment"



class PaymentReconcileView(AccountingStaffRequiredMixin, FormView):
    """
    شاشة تسوية دفعة معينة مع الفواتير المفتوحة لنفس الطرف.

    - تعرض جميع الفواتير المفتوحة / غير المدفوعة لنفس العميل.
    - تُنشئ حقلاً لكل فاتورة لإدخال مبلغ التسوية.
    - عند الحفظ تستدعي خدمة allocate_payment_to_invoices في services.
    """

    template_name = "accounting/reconcile/reconcile_payment.html"
    form_class = PaymentReconciliationForm

    # ------------------------------------------------------
    # جلب الدفعة المستهدفة من الـ URL
    # ------------------------------------------------------
    def dispatch(self, request, *args, **kwargs):
        self.payment = get_object_or_404(
            Payment.objects.select_related("contact"),
            pk=kwargs.get("pk"),
        )
        return super().dispatch(request, *args, **kwargs)

    # ------------------------------------------------------
    # الفواتير المتاحة للتسوية
    # ------------------------------------------------------
    def get_invoices_queryset(self):
        """
        يرجّع الفواتير المفتوحة لنفس الطرف المرتبط بهذه الدفعة.
        - لو الدفعة قبض من عميل → نستخدم فواتير مبيعات.
        - لو الدفعة صرف لمورد → نستخدم فواتير مشتريات.
        - نستثني فقط الملغاة والمدفوعة بالكامل.
        - وبعدها نفلتر في الذاكرة على balance > 0.
        """
        payment_type = self.payment.type  # حقل string عندك

        # نبدأ بكل فواتير هذا الكونتاكت
        qs = Invoice.objects.filter(customer=self.payment.contact)

        # نحدد نوع الفاتورة حسب نوع الدفعة
        if payment_type in ("customer_receipt", "in", "incoming", None, ""):
            qs = qs.filter(type=Invoice.InvoiceType.SALES)
        elif payment_type in ("supplier_payment", "out", "outgoing"):
            qs = qs.filter(type=Invoice.InvoiceType.PURCHASE)
        # غير كذا نخليها بدون فلتر type لو حاب (أو تقدر تضيف منطق خاص لاحقاً)

        # نستثني فقط الملغاة والمدفوعة بالكامل
        qs = qs.exclude(
            status__in=[
                Invoice.Status.CANCELLED,
                Invoice.Status.PAID,
            ]
        ).order_by("issued_at", "pk")

        # balance خاصية بايثون تعتمد على allocations، فنفلتر في الذاكرة
        open_invoices = [inv for inv in qs if inv.balance > 0]

        return open_invoices


    # ------------------------------------------------------
    # تمرير الدفعة والفواتير إلى الفورم
    # ------------------------------------------------------
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        invoices = self.get_invoices_queryset()
        kwargs["payment"] = self.payment
        kwargs["invoices"] = invoices
        return kwargs

    # ------------------------------------------------------
    # إعداد الكونتكست للقالب (الدفعة + الفواتير + الحقول)
    # ------------------------------------------------------
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        invoices = self.get_invoices_queryset()
        form = context["form"]

        invoice_rows = []
        for inv in invoices:
            field_name = PaymentReconciliationForm._field_name_for_invoice(inv)
            # نتأكد أن الحقل موجود فعلاً في الفورم
            if field_name in form.fields:
                invoice_rows.append(
                    {
                        "invoice": inv,
                        "field": form[field_name],
                    }
                )

        context.update(
            {
                "payment": self.payment,
                "invoices": invoices,
                "invoice_rows": invoice_rows,
                "has_open_invoices": bool(invoices),
                # عشان الناف / التبويب
                "section": "accounting",
                "subsection": "reconcile",
                "accounting_section": "payments",
            }
        )
        return context

    # ------------------------------------------------------
    # منطق حفظ التسوية
    # ------------------------------------------------------
    def form_valid(self, form):
        """
        عند الضغط على "حفظ التسوية":
        - نبني قاموس {invoice_id: amount}
        - نستدعي خدمة allocate_payment_to_invoices
        - في حال وجود خطأ محاسبي نعرضه في الفورم
        """
        allocations_dict = form.get_allocations_dict()

        try:
            allocate_payment_to_invoices(self.payment, allocations_dict)
        except ValidationError as e:
            form.add_error(None, e)
            return self.form_invalid(form)

        messages.success(
            self.request,
            _("تم حفظ تسوية الدفعة مع الفواتير بنجاح."),
        )

        return redirect(
            reverse("accounting:payment_detail", args=[self.payment.pk])
        )


class PaymentClearReconciliationView(AccountingStaffRequiredMixin, View):
    """
    إلغاء جميع التسويات المتعلقة بهذه الدفعة.
    """

    def post(self, request, pk, *args, **kwargs):
        payment = get_object_or_404(Payment, pk=pk)

        clear_payment_allocations(payment)

        messages.success(
            request,
            _("تم إلغاء جميع تسويات هذه الدفعة وإرجاع الأرصدة كما كانت."),
        )

        return redirect(reverse("accounting:payment_detail", args=[payment.pk]))