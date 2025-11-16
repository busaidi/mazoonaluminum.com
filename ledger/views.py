# ledger/views.py
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Sum, Value, DecimalField, Q
from django.db.models.functions import Coalesce
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import (
    ListView,
    CreateView,
    UpdateView,
    DetailView,
    TemplateView,
)

from .forms import (
    AccountForm,
    JournalEntryForm,
    JournalLineFormSet,
    TrialBalanceFilterForm,
    AccountLedgerFilterForm,
)
from .models import Account, JournalEntry, JournalLine


# ========= مكسين للتحقق من صلاحية الستاف =========

class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_staff

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        messages.error(self.request, _("ليس لديك صلاحية للوصول إلى هذه الصفحة."))
        return redirect("login")


# ========= الحسابات =========

class AccountListView(StaffRequiredMixin, ListView):
    model = Account
    template_name = "ledger/accounts/list.html"
    context_object_name = "accounts"


class AccountCreateView(StaffRequiredMixin, CreateView):
    model = Account
    form_class = AccountForm
    template_name = "ledger/accounts/form.html"

    def get_success_url(self):
        messages.success(self.request, _("تم إنشاء الحساب بنجاح."))
        return reverse("ledger:account_list")


class AccountUpdateView(StaffRequiredMixin, UpdateView):
    model = Account
    form_class = AccountForm
    template_name = "ledger/accounts/form.html"

    def get_success_url(self):
        messages.success(self.request, _("تم تحديث الحساب بنجاح."))
        return reverse("ledger:account_list")


# ========= قيود اليومية =========

class JournalEntryListView(StaffRequiredMixin, ListView):
    model = JournalEntry
    template_name = "ledger/journal/list.html"
    context_object_name = "entries"
    paginate_by = 50


class JournalEntryDetailView(StaffRequiredMixin, DetailView):
    model = JournalEntry
    template_name = "ledger/journal/detail.html"
    context_object_name = "entry"


class JournalEntryCreateView(StaffRequiredMixin, View):
    template_name = "ledger/journal/form.html"

    def get(self, request, *args, **kwargs):
        entry_form = JournalEntryForm(
            initial={"date": timezone.now().date()}
        )
        line_formset = JournalLineFormSet()
        return render(
            request,
            self.template_name,
            {"entry_form": entry_form, "line_formset": line_formset},
        )

    def post(self, request, *args, **kwargs):
        entry_form = JournalEntryForm(request.POST)
        line_formset = JournalLineFormSet(request.POST)

        if not (entry_form.is_valid() and line_formset.is_valid()):
            messages.error(request, _("الرجاء تصحيح الأخطاء في النموذج."))
            return render(
                request,
                self.template_name,
                {"entry_form": entry_form, "line_formset": line_formset},
            )

        entry = entry_form.save(commit=False)
        entry.created_by = request.user
        # السنة المالية ستُحدد تلقائيًا في save() حسب التاريخ
        entry.save()

        total_debit = Decimal("0")
        total_credit = Decimal("0")
        has_any_line = False

        for order, form in enumerate(line_formset.forms):
            if form.cleaned_data.get("DELETE"):
                continue

            account = form.cleaned_data.get("account")
            description = form.cleaned_data.get("description") or ""
            debit = form.cleaned_data.get("debit") or Decimal("0")
            credit = form.cleaned_data.get("credit") or Decimal("0")

            # سطر فاضي بالكامل → نتجاهله
            if not account and not description and debit == 0 and credit == 0:
                continue

            has_any_line = True

            JournalLine.objects.create(
                entry=entry,
                account=account,
                description=description,
                debit=debit,
                credit=credit,
                order=order,
            )

            total_debit += debit
            total_credit += credit

        if not has_any_line:
            entry.delete()
            messages.error(request, _("لا يوجد أي سطر صالح في القيد."))
            return render(
                request,
                self.template_name,
                {"entry_form": entry_form, "line_formset": line_formset},
            )

        if total_debit != total_credit:
            # rollback بسيط
            entry.lines.all().delete()
            entry.delete()
            messages.error(
                request,
                _("القيد غير متوازن: مجموع المدين لا يساوي مجموع الدائن."),
            )
            return render(
                request,
                self.template_name,
                {"entry_form": entry_form, "line_formset": line_formset},
            )

        messages.success(request, _("تم إنشاء قيد اليومية بنجاح."))
        return redirect("ledger:journalentry_detail", pk=entry.pk)


# ========= تقرير ميزان المراجعة =========

def trial_balance_view(request):
    form = TrialBalanceFilterForm(request.GET or None)
    rows = None
    totals = None

    qs = JournalLine.objects.select_related("account", "entry")

    if form.is_valid():
        fiscal_year = form.cleaned_data.get("fiscal_year")
        date_from = form.cleaned_data.get("date_from")
        date_to = form.cleaned_data.get("date_to")

        if fiscal_year:
            qs = qs.filter(entry__fiscal_year=fiscal_year)
        else:
            if date_from:
                qs = qs.filter(entry__date__gte=date_from)
            if date_to:
                qs = qs.filter(entry__date__lte=date_to)

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

        if rows:
            totals = rows.aggregate(
                total_debit=Sum("debit"),
                total_credit=Sum("credit"),
            )

    context = {
        "form": form,
        "rows": rows,
        "totals": totals,
    }
    return render(request, "ledger/reports/trial_balance.html", context)


# ========= كشف حساب (Account Ledger) =========

def account_ledger_view(request):
    form = AccountLedgerFilterForm(request.GET or None)

    account = None
    opening_balance = Decimal("0")
    running_lines = []

    if form.is_valid():
        account = form.cleaned_data.get("account")
        fiscal_year = form.cleaned_data.get("fiscal_year")
        date_from = form.cleaned_data.get("date_from")
        date_to = form.cleaned_data.get("date_to")

        if account:
            lines_qs = JournalLine.objects.select_related("entry").filter(
                account=account
            )

            # فلترة بالسنة المالية أو بالتواريخ
            if fiscal_year:
                lines_qs = lines_qs.filter(entry__fiscal_year=fiscal_year)
            else:
                if date_from:
                    lines_qs = lines_qs.filter(entry__date__gte=date_from)
                if date_to:
                    lines_qs = lines_qs.filter(entry__date__lte=date_to)

            lines_qs = lines_qs.order_by("entry__date", "entry_id", "id")

            # حساب رصيد افتتاحي (قبل date_from أو بداية السنة المالية)
            opening_qs = JournalLine.objects.filter(account=account)

            if fiscal_year:
                opening_qs = opening_qs.filter(
                    entry__fiscal_year=fiscal_year,
                    entry__date__lt=fiscal_year.start_date,
                )

            if date_from and not fiscal_year:
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
            opening_balance = (
                opening_totals["debit"] - opening_totals["credit"]
            )

            # بناء خطوط مع رصيد تراكمي
            balance = opening_balance
            for line in lines_qs:
                balance += (line.debit - line.credit)
                running_lines.append(
                    {
                        "date": line.entry.date,
                        "entry_id": line.entry.id,
                        "reference": line.entry.reference,
                        "description": line.description or line.entry.description,
                        "debit": line.debit,
                        "credit": line.credit,
                        "balance": balance,
                    }
                )

    context = {
        "form": form,
        "account": account,
        "opening_balance": opening_balance,
        "lines": running_lines,
    }
    return render(request, "ledger/reports/account_ledger.html", context)


# ========= لوحة معلومات بسيطة =========

class LedgerDashboardView(StaffRequiredMixin, TemplateView):
    template_name = "ledger/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        today = timezone.now().date()
        month_start = today.replace(day=1)

        accounts_count = Account.objects.count()
        entries_qs = JournalEntry.objects.all()
        entries_count = entries_qs.count()

        month_entries = entries_qs.filter(
            date__gte=month_start,
            date__lte=today,
        )
        month_entries_count = month_entries.count()

        month_totals = (
            JournalLine.objects.filter(entry__in=month_entries)
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
            JournalEntry.objects.order_by("-date", "-id")[:10]
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
            }
        )
        return ctx
