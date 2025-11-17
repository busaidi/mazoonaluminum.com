from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum, Value, DecimalField, Q
from django.db.models.functions import Coalesce
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
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
from .services import build_lines_from_formset


# ========= Staff / Fiscal Year helpers =========


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Mixin for views that require an accounting staff user.
    Uses the same logic as `is_accounting_staff` in the accounting app,
    but يسمح أيضاً لأي مستخدم is_staff أو is_superuser يدخل.
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
    Decorator بسيط ليتطلب مستخدم ستاف/سوبر يوزر.
    نستخدمه بدلاً من accounting_staff_required في شاشة الدفتر.
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


class FiscalYearRequiredMixin:
    """
    Mixin أذكى للتحقق من تهيئة السنوات المالية:

    - لو ما فيه أي سنة مالية → تحويل لإعداد السنة الأولى.
    - لو فيه سنوات لكن كلها مقفلة → السماح بالدخول مع إظهار تحذير عام.
    - لو فيه سنة/سنوات مفتوحة لكن تاريخ اليوم خارج نطاقها → إظهار تنبيه معلوماتي.
    """

    def dispatch(self, request, *args, **kwargs):
        qs = FiscalYear.objects.all()

        # 1) لا توجد أي سنة مالية → لازم نمر على معالج الإعداد
        if not qs.exists():
            messages.warning(
                request,
                _("يجب إنشاء سنة مالية واحدة على الأقل قبل استخدام دفتر الأستاذ."),
            )
            return redirect("ledger:fiscal_year_list")

        # 2) توجد سنوات، لكن كلها مقفلة
        open_years = qs.filter(is_closed=False)
        if not open_years.exists():
            messages.warning(
                request,
                _(
                    "كل السنوات المالية مقفلة حاليًا. يمكنك استعراض التقارير، "
                    "ولكن لا يمكن إنشاء قيود جديدة إلا بعد فتح سنة مالية جديدة."
                ),
            )
            # نسمح بالوصول للـ view (تقارير، عرض حسابات، ... إلخ)
            return super().dispatch(request, *args, **kwargs)

        # 3) توجد سنوات مفتوحة، لكن تاريخ اليوم لا يقع ضمن أي سنة مفتوحة
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
    Decorator version of FiscalYearRequiredMixin for function-based views.
    نفس منطق الميكسين:
      - لا توجد أي سنة مالية → تحويل للإعداد.
      - كل السنوات مقفلة → تحذير مع السماح بالدخول (للتقارير).
      - سنة مفتوحة لكن اليوم خارج نطاقها → تنبيه معلوماتي فقط.
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
            return redirect("ledger:fiscal_year_list")

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
    يرفع ValidationError لو:
      - ما فيه سنة تغطي التاريخ
      - أو السنة مقفلة
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

# ========= Initial fiscal year setup =========


@ledger_staff_required
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

        # تحقق أولي من الفورمات (الهيدر + الأسطر)
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
                # أولاً: تأكيد أن التاريخ داخل سنة مالية مفتوحة
                date = entry_form.cleaned_data.get("date")
                ensure_open_fiscal_year_for_date(date)

                # إنشاء رأس القيد بدون حفظ الخطوط بعد
                entry = entry_form.save(commit=False)
                entry.created_by = request.user
                # Fiscal year and number will be automatically set in save()
                entry.save()

                # بناء الأسطر من الفورم سِت
                lines, total_debit, total_credit = build_lines_from_formset(
                    line_formset
                )


                # التأكد من توازن القيد
                if total_debit != total_credit:
                    raise ValidationError(
                        _(
                            "القيد غير متوازن: مجموع المدين لا يساوي مجموع الدائن."
                        )
                    )

                # إنشاء الأسطر
                for line_data in lines:
                    JournalLine.objects.create(entry=entry, **line_data)

        except ValidationError as e:
            # لو فيه مشكلة في الأسطر أو التوازن يرجع نفس الصفحة
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

        try:
            with transaction.atomic():
                # تأكيد أن التاريخ الجديد داخل سنة مالية مفتوحة
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

                # حذف الأسطر القديمة واستبدالها بالجديدة
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
        return redirect("ledger:journalentry_detail", pk=entry.pk)



# ========= Trial balance report =========


@ledger_staff_required
@fiscal_year_required
def trial_balance_view(request):
    form = TrialBalanceFilterForm(request.GET or None)
    rows = None
    totals = None

    qs = (
        JournalLine.objects
        .posted()
        .select_related("account", "entry")
    )

    if form.is_valid():
        fiscal_year = form.cleaned_data.get("fiscal_year")
        date_from = form.cleaned_data.get("date_from")
        date_to = form.cleaned_data.get("date_to")

        # نحدد سنة مالية فعّالة لو ما تم اختيار شيء وما فيه تواريخ
        effective_fiscal_year = fiscal_year
        if not effective_fiscal_year and not date_from and not date_to:
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
    }
    return render(request, "ledger/reports/trial_balance.html", context)


# ========= Account ledger report =========

@ledger_staff_required
@fiscal_year_required
def account_ledger_view(request):
    form = AccountLedgerFilterForm(request.GET or None)

    account = None
    opening_balance = Decimal("0")
    running_lines = []
    effective_fiscal_year = None   # ← نضيفه هنا

    if form.is_valid():
        account = form.cleaned_data.get("account")
        fiscal_year = form.cleaned_data.get("fiscal_year")
        date_from = form.cleaned_data.get("date_from")
        date_to = form.cleaned_data.get("date_to")

        if account:
            # 1) Base queryset for this account (posted entries only)
            lines_qs = (
                JournalLine.objects
                .posted()
                .select_related("entry")
                .filter(account=account)
            )

            # تحديد السنة المالية الفعّالة
            effective_fiscal_year = fiscal_year
            if not effective_fiscal_year and not date_from and not date_to:
                today = timezone.now().date()
                effective_fiscal_year = FiscalYear.for_date(today)

            # Filter by fiscal year or date range
            if effective_fiscal_year:
                lines_qs = lines_qs.filter(entry__fiscal_year=effective_fiscal_year)
            else:
                lines_qs = lines_qs.within_period(date_from, date_to)

            lines_qs = lines_qs.order_by("entry__date", "entry_id", "id")

            # Helper to compute balance delta based on account type
            def calculate_balance(account_type, debit, credit):
                debit = debit or Decimal("0")
                credit = credit or Decimal("0")
                if account_type in [Account.Type.ASSET, Account.Type.EXPENSE]:
                    return debit - credit
                else:
                    return credit - debit

            # 2) Opening balance (before the selected period)
            opening_balance = Decimal("0")

            if effective_fiscal_year or date_from:
                opening_qs = JournalLine.objects.posted().filter(
                    account=account,
                )

                if effective_fiscal_year:
                    # قبل بداية السنة المالية
                    opening_qs = opening_qs.filter(
                        entry__date__lt=effective_fiscal_year.start_date
                    )
                elif date_from:
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

            # 3) Build running lines with cumulative balance
            balance = opening_balance

            for line in lines_qs:
                delta = calculate_balance(
                    account.type,
                    line.debit,
                    line.credit,
                )
                balance += delta

                running_lines.append({
                    "date": line.entry.date,
                    "entry_id": line.entry.id,
                    "entry_number": line.entry.display_number,
                    "reference": line.entry.reference or "-",
                    "description": line.description or line.entry.description,
                    "debit": line.debit or Decimal("0"),
                    "credit": line.credit or Decimal("0"),
                    "balance": balance,
                })

    context = {
        "form": form,
        "account": account,
        "opening_balance": opening_balance,
        "lines": running_lines,
        "effective_fiscal_year": effective_fiscal_year,  # ← هنا نمرّره للواجهة
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


@ledger_staff_required
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
    fy = entry.fiscal_year or FiscalYear.for_date(entry.date)
    if fy is None:
        messages.error(
            request,
            _("لا توجد سنة مالية تغطي تاريخ هذا القيد، لا يمكن ترحيله."),
        )
        if next_url:
            return redirect(next_url)
        return redirect("ledger:journalentry_detail", pk=entry.pk)

    if fy.is_closed:
        messages.error(
            request,
            _("لا يمكن ترحيل قيد ضمن سنة مالية مقفلة."),
        )
        if next_url:
            return redirect(next_url)
        return redirect("ledger:journalentry_detail", pk=entry.pk)

    # Set posting info
    with transaction.atomic():
        entry.posted = True
        entry.posted_at = timezone.now()
        entry.posted_by = request.user
        entry.save(update_fields=["posted", "posted_at", "posted_by"])

    messages.success(request, _("تم ترحيل القيد بنجاح."))

    if next_url:
        return redirect(next_url)
    return redirect("ledger:journalentry_detail", pk=entry.pk)


@ledger_staff_required
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
    # التحقق من السنة المالية (لا نسمح بإلغاء الترحيل في سنة مقفلة)
    fy = entry.fiscal_year or FiscalYear.for_date(entry.date)
    if fy and fy.is_closed:
        messages.error(
            request,
            _("لا يمكن إلغاء ترحيل قيد ضمن سنة مالية مقفلة."),
        )
        if next_url:
            return redirect(next_url)
        return redirect("ledger:journalentry_detail", pk=entry.pk)

    # Clear posting info
    with transaction.atomic():
        entry.posted = False
        entry.posted_at = None
        entry.posted_by = None
        entry.save(update_fields=["posted", "posted_at", "posted_by"])

    messages.success(request, _("تم إلغاء ترحيل القيد بنجاح."))

    if next_url:
        return redirect(next_url)
    return redirect("ledger:journalentry_detail", pk=entry.pk)



class FiscalYearListView(StaffRequiredMixin, ListView):
    model = FiscalYear
    template_name = "ledger/settings/fiscal_year_list.html"
    context_object_name = "years"

    def get_queryset(self):
        return (
            FiscalYear.objects.all()
            .order_by("-start_date")
        )

class FiscalYearCreateView(StaffRequiredMixin, CreateView):
    model = FiscalYear
    form_class = FiscalYearForm
    template_name = "ledger/settings/fiscal_year_form.html"
    success_url = reverse_lazy("ledger:fiscal_year_list")

    def form_valid(self, form):
        messages.success(self.request, _("تم إنشاء السنة المالية بنجاح"))
        return super().form_valid(form)

class FiscalYearUpdateView(StaffRequiredMixin, UpdateView):
    model = FiscalYear
    form_class = FiscalYearForm
    template_name = "ledger/settings/fiscal_year_form.html"
    success_url = reverse_lazy("ledger:fiscal_year_list")

    def form_valid(self, form):
        fy = form.instance
        if fy.is_closed:
            messages.warning(self.request, _("لا يمكن تعديل سنة مالية مقفلة"))
            return redirect("ledger:fiscal_year_list")
        messages.success(self.request, _("تم تحديث بيانات السنة المالية"))
        return super().form_valid(form)

class FiscalYearCloseView(StaffRequiredMixin, View):
    def post(self, request, pk):
        fy = get_object_or_404(FiscalYear, pk=pk)
        fy.is_closed = True
        fy.save()
        messages.success(request, _("تم إقفال السنة المالية"))
        return redirect("ledger:fiscal_year_list")


