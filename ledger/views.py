from decimal import Decimal
from functools import wraps

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

from accounting.views import is_accounting_staff, accounting_staff_required

from .forms import (
    AccountForm,
    JournalEntryForm,
    JournalLineFormSet,
    TrialBalanceFilterForm,
    AccountLedgerFilterForm,
    FiscalYearForm,
    JournalEntryFilterForm,
)
from .models import (
    Account,
    JournalEntry,
    JournalLine,
    FiscalYear,
    get_default_journal_for_manual_entry,
)


# ========= Staff / Fiscal Year helpers =========


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Mixin for views that require an accounting staff user.
    Uses the same logic as `is_accounting_staff` in the accounting app.
    """

    def test_func(self):
        return is_accounting_staff(self.request.user)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        messages.error(self.request, _("ليس لديك صلاحية للوصول إلى هذه الصفحة."))
        return redirect("login")


class FiscalYearRequiredMixin:
    """
    Mixin that ensures at least one FiscalYear exists
    before allowing access to ledger screens.
    """

    def dispatch(self, request, *args, **kwargs):
        if not FiscalYear.objects.exists():
            messages.warning(
                request,
                _("يجب إنشاء سنة مالية واحدة على الأقل قبل استخدام دفتر الأستاذ."),
            )
            return redirect("ledger:fiscal_year_setup")
        return super().dispatch(request, *args, **kwargs)


def fiscal_year_required(view_func):
    """
    Decorator version of FiscalYearRequiredMixin for function-based views.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not FiscalYear.objects.exists():
            messages.warning(
                request,
                _("يجب إنشاء سنة مالية واحدة على الأقل قبل استخدام دفتر الأستاذ."),
            )
            return redirect("ledger:fiscal_year_setup")
        return view_func(request, *args, **kwargs)

    return _wrapped


# ========= Initial fiscal year setup =========


@accounting_staff_required
def fiscal_year_setup_view(request):
    """
    Handle creation of the first fiscal year.
    If a fiscal year already exists, redirect to the dashboard.
    """
    if FiscalYear.objects.exists():
        # System already initialized, no need to run the wizard again
        return redirect("ledger:dashboard")

    if request.method == "POST":
        form = FiscalYearForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                _("تم إنشاء السنة المالية الأولى بنجاح. يمكنك الآن استخدام دفتر الأستاذ."),
            )
            return redirect("ledger:dashboard")
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
        "ledger/setup/fiscal_year_setup.html",
        {"form": form},
    )


# ========= Accounts =========


class AccountListView(FiscalYearRequiredMixin, StaffRequiredMixin, ListView):
    model = Account
    template_name = "ledger/accounts/list.html"
    context_object_name = "accounts"


class AccountCreateView(FiscalYearRequiredMixin, StaffRequiredMixin, CreateView):
    model = Account
    form_class = AccountForm
    template_name = "ledger/accounts/form.html"

    def get_success_url(self):
        messages.success(self.request, _("تم إنشاء الحساب بنجاح."))
        return reverse("ledger:account_list")


class AccountUpdateView(FiscalYearRequiredMixin, StaffRequiredMixin, UpdateView):
    model = Account
    form_class = AccountForm
    template_name = "ledger/accounts/form.html"

    def get_success_url(self):
        messages.success(self.request, _("تم تحديث الحساب بنجاح."))
        return reverse("ledger:account_list")


# ========= Journal entries =========


class JournalEntryListView(FiscalYearRequiredMixin, StaffRequiredMixin, ListView):
    """
    List journal entries with simple filtering:
    - Text search (q) on reference/description
    - Date range (date_from, date_to)
    - Posted status (posted / draft / all)
    - Journal
    """

    model = JournalEntry
    template_name = "ledger/journal/list.html"
    context_object_name = "entries"
    paginate_by = 50

    def get_filter_form(self):
        """
        Build and cache the filter form based on GET params.
        """
        if not hasattr(self, "_filter_form"):
            self._filter_form = JournalEntryFilterForm(self.request.GET or None)
        return self._filter_form

    def get_queryset(self):
        """
        Base queryset:
        - Use manager helper to annotate totals.
        - Apply filters from the filter form if valid.
        """
        qs = (
            JournalEntry.objects
            .with_totals()       # من الـ Manager: يضيف total_debit_value و total_credit_value
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

        # Text search (reference / description)
        if q:
            qs = qs.filter(
                Q(reference__icontains=q)
                | Q(description__icontains=q)
            )

        # Date range filter
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)

        # Posted / draft filter
        if posted == "posted":
            qs = qs.posted()
        elif posted == "draft":
            qs = qs.unposted()

        # Journal filter
        if journal:
            qs = qs.filter(journal=journal)

        return qs

    def get_context_data(self, **kwargs):
        """
        Add filter form and current query string (without page)
        to keep filters when paginating.
        """
        ctx = super().get_context_data(**kwargs)

        # Filter form
        ctx["filter_form"] = self.get_filter_form()

        # Build query string for pagination (excluding "page")
        query_dict = self.request.GET.copy()
        query_dict.pop("page", None)
        ctx["current_query"] = query_dict.urlencode()

        return ctx


class JournalEntryDetailView(FiscalYearRequiredMixin, StaffRequiredMixin, DetailView):
    model = JournalEntry
    template_name = "ledger/journal/detail.html"
    context_object_name = "entry"


class JournalEntryCreateView(FiscalYearRequiredMixin, StaffRequiredMixin, View):
    """
    Create a manual journal entry:
    - Prefills date with today
    - Prefills journal with the default manual journal (usually General Journal)
    - Validates lines and ensures the entry is balanced before saving
    """

    template_name = "ledger/journal/form.html"

    def get(self, request, *args, **kwargs):
        """
        Render empty form for a new journal entry with sensible defaults.
        """
        initial = {
            "date": timezone.now().date(),
        }

        # Default journal for manual entries (e.g. General Journal)
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
        """
        Validate and create a new journal entry with its lines.
        Only creates the entry if:
        - There is at least one valid line
        - The entry is balanced (total debit == total credit)
        """
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

        # Create the journal entry (without lines yet)
        entry = entry_form.save(commit=False)
        entry.created_by = request.user
        # Fiscal year and number will be automatically set in save()
        entry.save()

        total_debit = Decimal("0")
        total_credit = Decimal("0")
        has_any_line = False
        has_line_errors = False

        for order, form in enumerate(line_formset.forms):
            if form.cleaned_data.get("DELETE"):
                continue

            account = form.cleaned_data.get("account")
            description = form.cleaned_data.get("description") or ""
            debit = form.cleaned_data.get("debit") or Decimal("0")
            credit = form.cleaned_data.get("credit") or Decimal("0")

            # Completely empty line → skip
            if not account and not description and debit == 0 and credit == 0:
                continue

            # 1) Cannot have an amount without an account
            if (debit != 0 or credit != 0) and account is None:
                form.add_error(
                    "account",
                    _("يجب اختيار حساب للسطر الذي يحتوي على مبلغ مدين أو دائن."),
                )
                has_line_errors = True
                continue

            # 2) Cannot be both debit and credit at the same time
            if debit and credit:
                form.add_error(
                    "debit",
                    _("لا يمكن أن يكون السطر مدينًا ودائنًا في نفس الوقت."),
                )
                form.add_error(
                    "credit",
                    _("لا يمكن أن يكون السطر مدينًا ودائنًا في نفس الوقت."),
                )
                has_line_errors = True
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

        # If there are errors in lines, rollback and return the form
        if has_line_errors:
            entry.lines.all().delete()
            entry.delete()
            messages.error(request, _("الرجاء تصحيح الأخطاء في أسطر القيد."))
            return render(
                request,
                self.template_name,
                {
                    "entry_form": entry_form,
                    "line_formset": line_formset,
                },
            )

        # If no valid lines at all, rollback and return the form
        if not has_any_line:
            entry.delete()
            messages.error(request, _("لا يوجد أي سطر صالح في القيد."))
            return render(
                request,
                self.template_name,
                {
                    "entry_form": entry_form,
                    "line_formset": line_formset,
                },
            )

        # Ensure the entry is balanced (total debit == total credit)
        if total_debit != total_credit:
            entry.lines.all().delete()
            entry.delete()
            messages.error(
                request,
                _("القيد غير متوازن: مجموع المدين لا يساوي مجموع الدائن."),
            )
            return render(
                request,
                self.template_name,
                {
                    "entry_form": entry_form,
                    "line_formset": line_formset,
                },
            )

        messages.success(request, _("تم إنشاء قيد اليومية بنجاح."))
        return redirect("ledger:journalentry_detail", pk=entry.pk)


# ========= Edit unposted Journal =========


class JournalEntryUpdateView(FiscalYearRequiredMixin, StaffRequiredMixin, View):
    """
    Edit an existing (unposted) journal entry using the same form as creation.
    """

    template_name = "ledger/journal/form.html"

    def get_entry(self):
        return get_object_or_404(JournalEntry, pk=self.kwargs["pk"])

    def dispatch(self, request, *args, **kwargs):
        self.entry = self.get_entry()

        # Do not allow editing a posted entry
        if self.entry.posted:
            messages.error(request, _("لا يمكن تعديل قيد مُرحّل."))
            return redirect("ledger:journalentry_detail", pk=self.entry.pk)

        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        # Header part of the form
        entry_form = JournalEntryForm(instance=self.entry)

        # Lines: build initial data from existing lines
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

        # Do not touch the database until we are sure everything is valid
        entry = entry_form.save(commit=False)

        total_debit = Decimal("0")
        total_credit = Decimal("0")
        has_any_line = False
        new_lines = []

        for order, form in enumerate(line_formset.forms):
            if form.cleaned_data.get("DELETE"):
                continue

            account = form.cleaned_data.get("account")
            description = form.cleaned_data.get("description") or ""
            debit = form.cleaned_data.get("debit") or Decimal("0")
            credit = form.cleaned_data.get("credit") or Decimal("0")

            # Completely empty line → skip
            if not account and not description and debit == 0 and credit == 0:
                continue

            has_any_line = True

            new_lines.append(
                {
                    "account": account,
                    "description": description,
                    "debit": debit,
                    "credit": credit,
                    "order": order,
                }
            )

            total_debit += debit
            total_credit += credit

        # No valid lines at all
        if not has_any_line:
            messages.error(request, _("لا يوجد أي سطر صالح في القيد."))
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

        # Must be balanced
        if total_debit != total_credit:
            messages.error(
                request,
                _("القيد غير متوازن: مجموع المدين لا يساوي مجموع الدائن."),
            )
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

        # At this point everything is valid → save entry and rewrite lines
        entry.save()

        # Replace existing lines with the new set
        self.entry.lines.all().delete()
        for line_data in new_lines:
            JournalLine.objects.create(entry=entry, **line_data)

        messages.success(request, _("تم تحديث قيد اليومية بنجاح."))
        return redirect("ledger:journalentry_detail", pk=entry.pk)


# ========= Trial balance report =========


@accounting_staff_required
@fiscal_year_required
def trial_balance_view(request):
    form = TrialBalanceFilterForm(request.GET or None)
    rows = None
    totals = None

    # Start from all posted lines (نستخدم helper من المانجر)
    qs = (
        JournalLine.objects
        .posted()  # == filter(entry__posted=True)
        .select_related("account", "entry")
    )

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


# ========= Account ledger report =========


@accounting_staff_required
@fiscal_year_required
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
            # 1) Base queryset for this account (posted entries only)
            lines_qs = (
                JournalLine.objects
                .posted()     # helper من المانجر
                .select_related("entry")
                .filter(account=account)
            )

            # Filter by fiscal year or date range
            if fiscal_year:
                lines_qs = lines_qs.filter(entry__fiscal_year=fiscal_year)
            else:
                if date_from:
                    lines_qs = lines_qs.filter(entry__date__gte=date_from)
                if date_to:
                    lines_qs = lines_qs.filter(entry__date__lte=date_to)

            lines_qs = lines_qs.order_by("entry__date", "entry_id", "id")

            # Helper to compute balance delta based on account type
            def calculate_balance(account_type, debit, credit):
                debit = debit or Decimal("0")
                credit = credit or Decimal("0")
                if account_type in [Account.Type.ASSET, Account.Type.EXPENSE]:
                    # Natural debit balance
                    return debit - credit
                else:
                    # Liability / equity / revenue → natural credit balance
                    return credit - debit

            # 2) Opening balance (before the selected period)
            opening_balance = Decimal("0")

            if fiscal_year or date_from:
                opening_qs = JournalLine.objects.posted().filter(
                    account=account,
                )

                if fiscal_year:
                    # All lines before the start of the selected fiscal year
                    opening_qs = opening_qs.filter(
                        entry__date__lt=fiscal_year.start_date,
                    )

                if date_from and not fiscal_year:
                    # Date-based period only
                    opening_qs = opening_qs.filter(entry__date__lt=date_from)

                opening_totals = opening_qs.aggregate(
                    debit=Coalesce(
                        Sum("debit"),
                        Value(0),
                        output_field=DecimalField(
                            max_digits=12, decimal_places=3
                        ),
                    ),
                    credit=Coalesce(
                        Sum("credit"),
                        Value(0),
                        output_field=DecimalField(
                            max_digits=12, decimal_places=3
                        ),
                    ),
                )

                opening_balance = calculate_balance(
                    account.type,
                    opening_totals["debit"],
                    opening_totals["credit"],
                )

            # 3) Build running lines with cumulative balance
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
                        "entry_number": line.entry.display_number,  # ← هنا
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
    }
    return render(request, "ledger/reports/account_ledger.html", context)


# ========= Dashboard =========


class LedgerDashboardView(FiscalYearRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "ledger/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        today = timezone.now().date()
        month_start = today.replace(day=1)

        # Total accounts
        accounts_count = Account.objects.count()

        # Only posted journal entries are considered in stats
        entries_qs = JournalEntry.objects.posted()
        entries_count = entries_qs.count()

        # Posted entries for the current month
        month_entries = entries_qs.filter(
            date__gte=month_start,
            date__lte=today,
        )
        month_entries_count = month_entries.count()

        # Monthly totals (debit / credit) for posted entries
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

        # Recent posted entries
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
            }
        )
        return ctx


# ========= Posting / Unposting journal entries =========


@accounting_staff_required
@fiscal_year_required
def journalentry_post_view(request, pk):
    """
    Post a journal entry:
    - Only allowed via POST
    - Entry must be balanced
    - يحاول الرجوع إلى next لو مُرسل من الفورم (مثلاً صفحة الليست)
    """
    entry = get_object_or_404(JournalEntry, pk=pk)
    next_url = request.POST.get("next") or request.GET.get("next")

    if request.method != "POST":
        # لو جاي بغير POST وبرضه فيه next → رجعنا له
        if next_url:
            return redirect(next_url)
        return redirect("ledger:journalentry_detail", pk=entry.pk)

    if entry.posted:
        messages.info(request, _("القيد مُرحّل بالفعل."))
        if next_url:
            return redirect(next_url)
        return redirect("ledger:journalentry_detail", pk=entry.pk)

    if not entry.is_balanced:
        messages.error(request, _("لا يمكن ترحيل قيد غير متوازن."))
        if next_url:
            return redirect(next_url)
        return redirect("ledger:journalentry_detail", pk=entry.pk)

    # Set posting info
    entry.posted = True
    entry.posted_at = timezone.now()
    entry.posted_by = request.user
    entry.save(update_fields=["posted", "posted_at", "posted_by"])

    messages.success(request, _("تم ترحيل القيد بنجاح."))

    if next_url:
        return redirect(next_url)
    return redirect("ledger:journalentry_detail", pk=entry.pk)


@accounting_staff_required
@fiscal_year_required
def journalentry_unpost_view(request, pk):
    """
    Unpost a journal entry:
    - Only allowed via POST
    - يحاول الرجوع إلى next لو مُرسل من الفورم (مثلاً صفحة الليست)
    """
    entry = get_object_or_404(JournalEntry, pk=pk)
    next_url = request.POST.get("next") or request.GET.get("next")

    if request.method != "POST":
        if next_url:
            return redirect(next_url)
        return redirect("ledger:journalentry_detail", pk=entry.pk)

    if not entry.posted:
        messages.info(request, _("القيد غير مُرحّل."))
        if next_url:
            return redirect(next_url)
        return redirect("ledger:journalentry_detail", pk=entry.pk)

    # Clear posting info
    entry.posted = False
    entry.posted_at = None
    entry.posted_by = None
    entry.save(update_fields=["posted", "posted_at", "posted_by"])

    messages.success(request, _("تم إلغاء ترحيل القيد بنجاح."))

    if next_url:
        return redirect(next_url)
    return redirect("ledger:journalentry_detail", pk=entry.pk)

