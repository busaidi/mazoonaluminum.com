from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import ListView, CreateView, UpdateView, DetailView, TemplateView

from .forms import (
    AccountForm,
    JournalEntryForm,
    JournalLineFormSet,
    TrialBalanceFilterForm,
    AccountLedgerFilterForm,
)
from .models import Account, JournalEntry, JournalLine


class StaffRequiredMixin(UserPassesTestMixin):
    """Require staff users to access the view."""

    def test_func(self):
        return self.request.user.is_staff


# === Accounts ===


class AccountListView(LoginRequiredMixin, StaffRequiredMixin, ListView):
    model = Account
    template_name = "ledger/accounts/list.html"
    context_object_name = "accounts"


class AccountCreateView(LoginRequiredMixin, StaffRequiredMixin, CreateView):
    model = Account
    form_class = AccountForm
    template_name = "ledger/accounts/form.html"

    def get_success_url(self):
        return reverse("ledger:account_list")


class AccountUpdateView(LoginRequiredMixin, StaffRequiredMixin, UpdateView):
    model = Account
    form_class = AccountForm
    template_name = "ledger/accounts/form.html"

    def get_success_url(self):
        return reverse("ledger:account_list")


# === Journal entries ===


class JournalEntryListView(LoginRequiredMixin, StaffRequiredMixin, ListView):
    model = JournalEntry
    template_name = "ledger/journal/list.html"
    context_object_name = "entries"


class JournalEntryDetailView(LoginRequiredMixin, StaffRequiredMixin, DetailView):
    model = JournalEntry
    template_name = "ledger/journal/detail.html"
    context_object_name = "entry"


class JournalEntryCreateView(LoginRequiredMixin, StaffRequiredMixin, View):
    """Create a balanced journal entry with inline lines formset."""
    template_name = "ledger/journal/form.html"

    def get(self, request):
        entry_form = JournalEntryForm()
        line_formset = JournalLineFormSet()
        return render(
            request,
            self.template_name,
            {"entry_form": entry_form, "line_formset": line_formset},
        )

    def post(self, request):
        entry_form = JournalEntryForm(request.POST)
        line_formset = JournalLineFormSet(request.POST)

        if not (entry_form.is_valid() and line_formset.is_valid()):
            return render(
                request,
                self.template_name,
                {"entry_form": entry_form, "line_formset": line_formset},
            )

        # Build entry (not saved yet)
        entry = entry_form.save(commit=False)
        entry.created_by = request.user

        # Collect valid lines and compute totals
        total_debit = Decimal("0")
        total_credit = Decimal("0")
        valid_lines = []

        for form in line_formset:
            if not form.cleaned_data:
                # Completely empty form
                continue
            if form.cleaned_data.get("DELETE"):
                # Marked for deletion
                continue

            account = form.cleaned_data.get("account")
            description = form.cleaned_data.get("description") or ""
            debit = form.cleaned_data.get("debit") or Decimal("0")
            credit = form.cleaned_data.get("credit") or Decimal("0")

            # Completely empty row → ignore
            if not account and debit == 0 and credit == 0:
                continue

            # Amounts with no account → validation error
            if not account and (debit != 0 or credit != 0):
                form.add_error("account", _("يجب اختيار حساب لكل سطر يحتوي مبالغ."))
                return render(
                    request,
                    self.template_name,
                    {"entry_form": entry_form, "line_formset": line_formset},
                )

            valid_lines.append(
                {
                    "account": account,
                    "description": description,
                    "debit": debit,
                    "credit": credit,
                }
            )

            total_debit += debit
            total_credit += credit

        if not valid_lines:
            entry_form.add_error(None, _("يجب إدخال سطر واحد على الأقل في القيد."))
            return render(
                request,
                self.template_name,
                {"entry_form": entry_form, "line_formset": line_formset},
            )

        if total_debit != total_credit:
            entry_form.add_error(
                None,
                _("القيد غير متوازن. يجب أن يساوي إجمالي المدين إجمالي الدائن."),
            )
            return render(
                request,
                self.template_name,
                {"entry_form": entry_form, "line_formset": line_formset},
            )

        # Save entry and lines
        entry.posted = True
        entry.save()

        for idx, line_data in enumerate(valid_lines):
            JournalLine.objects.create(
                entry=entry,
                account=line_data["account"],
                description=line_data["description"],
                debit=line_data["debit"],
                credit=line_data["credit"],
                order=idx,
            )

        messages.success(request, _("تم إنشاء القيد بنجاح."))
        return redirect("ledger:journalentry_detail", pk=entry.pk)


# === Reports ===


def trial_balance_view(request):
    """Simple trial balance grouped by account, with totals and balance."""
    form = TrialBalanceFilterForm(request.GET or None)
    rows = None
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    total_balance = Decimal("0")

    qs = JournalLine.objects.select_related("account", "entry")

    if form.is_valid():
        date_from = form.cleaned_data.get("date_from")
        date_to = form.cleaned_data.get("date_to")
        if date_from:
            qs = qs.filter(entry__date__gte=date_from)
        if date_to:
            qs = qs.filter(entry__date__lte=date_to)

        decimal_field = DecimalField(max_digits=12, decimal_places=3)

        qs = (
            qs.values(
                "account__code",
                "account__name",
                "account__type",
            )
            .annotate(
                debit=Coalesce(
                    Sum("debit", output_field=decimal_field),
                    Value(Decimal("0"), output_field=decimal_field),
                ),
                credit=Coalesce(
                    Sum("credit", output_field=decimal_field),
                    Value(Decimal("0"), output_field=decimal_field),
                ),
            )
            .order_by("account__code")
        )

        # Convert to list and compute balance + totals
        rows = []
        for row in qs:
            debit = row["debit"] or Decimal("0")
            credit = row["credit"] or Decimal("0")
            balance = debit - credit

            row["balance"] = balance

            total_debit += debit
            total_credit += credit
            total_balance += balance

            rows.append(row)

    context = {
        "form": form,
        "rows": rows,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "total_balance": total_balance,
    }
    return render(request, "ledger/reports/trial_balance.html", context)





def account_ledger_view(request):
    """Account ledger report for a single account with running balance."""
    form = AccountLedgerFilterForm(request.GET or None)
    lines = None
    account = None
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    total_balance = Decimal("0")

    if form.is_valid():
        account = form.cleaned_data["account"]
        date_from = form.cleaned_data.get("date_from")
        date_to = form.cleaned_data.get("date_to")

        qs = JournalLine.objects.filter(account=account).select_related("entry")

        if date_from:
            qs = qs.filter(entry__date__gte=date_from)
        if date_to:
            qs = qs.filter(entry__date__lte=date_to)

        qs = qs.order_by("entry__date", "entry_id", "id")

        # Compute totals for the period
        decimal_field = DecimalField(max_digits=12, decimal_places=3)
        agg = qs.aggregate(
            debit=Coalesce(
                Sum("debit", output_field=decimal_field),
                Value(Decimal("0"), output_field=decimal_field),
            ),
            credit=Coalesce(
                Sum("credit", output_field=decimal_field),
                Value(Decimal("0"), output_field=decimal_field),
            ),
        )

        total_debit = agg["debit"] or Decimal("0")
        total_credit = agg["credit"] or Decimal("0")
        total_balance = total_debit - total_credit

        # Build running balance per line
        running_balance = Decimal("0")
        lines = []
        for line in qs:
            debit = line.debit or Decimal("0")
            credit = line.credit or Decimal("0")
            running_balance += debit - credit
            # Attach running balance to the instance (for template use)
            line.running_balance = running_balance
            lines.append(line)

    context = {
        "form": form,
        "account": account,
        "lines": lines,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "total_balance": total_balance,
    }
    return render(request, "ledger/reports/account_ledger.html", context)


# === Dashboard ===


class LedgerDashboardView(LoginRequiredMixin, StaffRequiredMixin, TemplateView):
    """Simple dashboard for ledger overview."""
    template_name = "ledger/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        today = timezone.localdate()
        month_start = today.replace(day=1)

        # Basic aggregates
        accounts_count = Account.objects.count()
        entries_count = JournalEntry.objects.count()
        month_entries_count = JournalEntry.objects.filter(
            date__gte=month_start,
            date__lte=today,
        ).count()

        month_lines = JournalLine.objects.filter(
            entry__date__gte=month_start,
            entry__date__lte=today,
        )

        month_debit = month_lines.aggregate(s=Sum("debit"))["s"] or 0
        month_credit = month_lines.aggregate(s=Sum("credit"))["s"] or 0

        # Last 5 entries
        recent_entries = (
            JournalEntry.objects.order_by("-date", "-id")
            .prefetch_related("lines")[:5]
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
