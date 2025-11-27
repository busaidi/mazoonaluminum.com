# banking/views.py

from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import (
    TemplateView,
    ListView,
    CreateView,
    UpdateView,
)

from accounting.views import AccountingStaffRequiredMixin
from .models import BankStatement, BankAccount
from .forms import BankStatementForm, BankAccountForm


class BankBaseView(AccountingStaffRequiredMixin):
    """
    Base view for banking screens so they appear as part of accounting UI.
    - يضبط accounting_section عشان يضوي تبويب "التسوية البنكية" في نافبار المحاسبة.
    - يضيف روابط banking_nav للروابط الفرعية.
    """

    accounting_section = "banking"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # نضمن وجود هذا المتغير للـ navbar في base_accounting.html
        ctx.setdefault("accounting_section", self.accounting_section)

        # روابط فرعية للبنك
        ctx.setdefault(
            "banking_nav",
            {
                "reconciliation_url": reverse("banking:bank_reconciliation"),
                "bank_account_list_url": reverse("banking:bank_account_list"),
                "bank_account_create_url": reverse("banking:bank_account_create"),
                "statement_list_url": reverse("banking:bank_statement_list"),
                "statement_upload_url": reverse("banking:bank_statement_upload"),
            },
        )
        return ctx


class BankReconciliationView(BankBaseView, TemplateView):
    """
    شاشة التسوية البنكية:
      - عرض قائمة مختصرة لآخر كشوف البنك.
      - اختيار كشف محدد.
      - عرض أسطر كشف البنك (BankStatementLine) للكشف المختار.
      - لاحقاً: عرض حركات النظام ومطابقتها.
    """

    template_name = "banking/bank_reconciliation.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        ctx["title"] = _("التسوية البنكية")

        # آخر كشوف البنك
        ctx["recent_statements"] = (
            BankStatement.objects.select_related("bank_account")
            .order_by("-date_from", "-id")[:10]
        )

        # كشف مختار من كويري سترنغ ?statement=ID
        statement_id = self.request.GET.get("statement")
        selected_statement = None
        statement_lines = []

        if statement_id:
            try:
                selected_statement = (
                    BankStatement.objects.select_related("bank_account")
                    .get(pk=statement_id)
                )
                statement_lines = selected_statement.lines.order_by("date", "id")
            except BankStatement.DoesNotExist:
                selected_statement = None
                statement_lines = []

        ctx["selected_statement"] = selected_statement
        ctx["statement_lines"] = statement_lines

        return ctx


class BankAccountListView(BankBaseView, ListView):
    """
    قائمة الحسابات البنكية المعرفة في النظام.
    """

    model = BankAccount
    template_name = "banking/bank_account_list.html"
    context_object_name = "accounts"
    ordering = ["name"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = _("الحسابات البنكية")
        return ctx


class BankAccountCreateView(BankBaseView, CreateView):
    """
    إنشاء حساب بنكي جديد وربطه بحساب محاسبي من دليل الحسابات.
    """

    model = BankAccount
    form_class = BankAccountForm
    template_name = "banking/bank_account_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = _("إضافة حساب بنكي جديد")
        return ctx

    def get_success_url(self):
        # بعد الإضافة يرجّع المستخدم لقائمة الحسابات البنكية
        return reverse("banking:bank_account_list")


class BankAccountUpdateView(BankBaseView, UpdateView):
    """
    تعديل حساب بنكي موجود.
    """

    model = BankAccount
    form_class = BankAccountForm
    template_name = "banking/bank_account_form.html"
    context_object_name = "account"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = _("تعديل حساب بنكي")
        return ctx

    def get_success_url(self):
        return reverse("banking:bank_account_list")


class BankStatementListView(BankBaseView, ListView):
    """
    قائمة كشوف البنك المسجلة في النظام.
    """

    model = BankStatement
    template_name = "banking/bank_statement_list.html"
    context_object_name = "statements"
    paginate_by = 25
    ordering = ["-date_from", "-id"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = _("كشوف البنك")
        return ctx


class BankStatementUploadView(BankBaseView, CreateView):
    """
    إنشاء / إدخال كشف بنك جديد (يدوي مع إمكانية إرفاق ملف).
    """

    model = BankStatement
    form_class = BankStatementForm
    template_name = "banking/bank_statement_form.html"
    context_object_name = "statement"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = _("إضافة كشف بنك جديد")
        return ctx

    def get_success_url(self):
        return reverse("banking:bank_statement_list")


class BankStatementUpdateView(BankBaseView, UpdateView):
    """
    تعديل كشف بنك موجود.
    """

    model = BankStatement
    form_class = BankStatementForm
    template_name = "banking/bank_statement_form.html"
    context_object_name = "statement"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = _("تعديل كشف البنك")
        return ctx

    def get_success_url(self):
        return reverse("banking:bank_statement_list")
