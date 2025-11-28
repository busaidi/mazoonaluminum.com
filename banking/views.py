# banking/views.py

import pandas as pd  # لقراءة ملفات الاكسل
from decimal import Decimal
import json

from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.generic import (
    TemplateView,
    ListView,
    CreateView,
    UpdateView,
    DetailView,
    DeleteView,
)

from accounting.models import JournalLine
# تأكد من مسار الاستيراد الصحيح للميكسن الخاص بك
from accounting.views import AccountingStaffRequiredMixin

from .forms import BankStatementForm, BankAccountForm
from .models import (
    BankStatement,
    BankAccount,
    BankStatementLine,
    BankReconciliation,
)


# =========================================================
# 1. Base Logic & Mixins
# =========================================================

class BankBaseView(AccountingStaffRequiredMixin):
    """
    بيئة العمل الأساسية للبنك.
    تضمن ظهور القوائم الجانبية الصحيحة وتمرير الروابط المشتركة.
    """
    accounting_section = "banking"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault("accounting_section", self.accounting_section)

        # روابط التنقل السريع في النافبار الفرعية
        ctx["banking_nav"] = {
            "account_list": reverse("banking:bank_account_list"),
            "statement_list": reverse("banking:bank_statement_list"),
            "upload_statement": reverse("banking:bank_statement_upload"),
        }
        return ctx


# =========================================================
# 2. Bank Accounts Management
# =========================================================

class BankAccountListView(BankBaseView, ListView):
    model = BankAccount
    template_name = "banking/bank_account_list.html"
    context_object_name = "accounts"
    ordering = ["name"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = _("الحسابات البنكية")
        return ctx


class BankAccountCreateView(BankBaseView, CreateView):
    model = BankAccount
    form_class = BankAccountForm
    template_name = "banking/bank_account_form.html"
    success_url = reverse_lazy("banking:bank_account_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = _("إضافة حساب بنكي جديد")
        return ctx


class BankAccountUpdateView(BankBaseView, UpdateView):
    model = BankAccount
    form_class = BankAccountForm
    template_name = "banking/bank_account_form.html"
    success_url = reverse_lazy("banking:bank_account_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = _("تعديل بيانات الحساب البنكي")
        return ctx


class BankAccountDeleteView(BankBaseView, DeleteView):
    model = BankAccount
    template_name = "banking/confirm_delete.html"  # تأكد من وجود تمبلت عام للحذف
    success_url = reverse_lazy("banking:bank_account_list")


# =========================================================
# 3. Bank Statements (Upload & Processing)
# =========================================================

class BankStatementListView(BankBaseView, ListView):
    model = BankStatement
    template_name = "banking/bank_statement_list.html"
    context_object_name = "statements"
    paginate_by = 25
    ordering = ["-date", "-id"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = _("سجل كشوفات البنك")
        return ctx


class BankStatementUploadView(BankBaseView, CreateView):
    """
    الفيو المسؤول عن رفع الملف وقراءته (Parsing).
    هنا يحدث السحر: تحويل Excel/CSV إلى أسطر في قاعدة البيانات.
    """
    model = BankStatement
    form_class = BankStatementForm
    template_name = "banking/bank_statement_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = _("رفع كشف بنكي جديد")
        return ctx

    def form_valid(self, form):
        """
        حفظ الهيدر + استيراد الأسطر من الملف في معاملة ذرّية واحدة.
        """
        with transaction.atomic():
            # حفظ الهيدر (الكشف)
            self.object = form.save()

            # معالجة الملف إذا وجد
            uploaded_file = self.object.imported_file
            if uploaded_file:
                try:
                    self.process_file(uploaded_file, self.object)
                    messages.success(self.request, _("تم رفع ومعالجة الكشف بنجاح."))
                except Exception as e:
                    # في حال الخطأ، نظهر رسالة للمستخدم ونوقف الحفظ
                    form.add_error("imported_file", _("خطأ في قراءة الملف: ") + str(e))
                    # rollback ضمن الـ atomic
                    raise

        return super().form_valid(form)

    def process_file(self, file_obj, statement_obj):
        """
        دالة مساعدة لقراءة ملف الاكسل/CSV.
        يفترض أن الملف يحتوي أعمدة: date, label/description, ref, amount
        يمكنك لاحقاً تخصيص mapping حسب فورمات كل بنك.
        """
        # اختيار الدالة المناسبة حسب الامتداد
        filename = file_obj.name.lower()
        if filename.endswith(".csv"):
            df = pd.read_csv(file_obj)
        else:
            df = pd.read_excel(file_obj)

        # تنظيف أسماء الأعمدة
        df.columns = df.columns.str.strip().str.lower()

        lines_to_create = []

        for _, row in df.iterrows():
            # الحصول على القيم مع fallbacks بسيطة
            date_val = row.get("date")
            label_val = (
                row.get("label")
                or row.get("description")
                or row.get("memo")
                or _("بدون وصف")
            )
            ref_val = row.get("ref") or row.get("reference") or ""
            amount_val = row.get("amount", 0)

            # تحويل المبلغ إلى Decimal (مع التعامل مع NaN)
            if pd.isna(amount_val):
                amount_val = 0

            amount_dec = Decimal(str(amount_val))

            line = BankStatementLine(
                statement=statement_obj,
                date=date_val,  # تأكد أن pandas يرجع تاريخ/Datetime قابل للحفظ
                label=label_val,
                ref=ref_val,
                amount=amount_dec,
                # amount_residual سيتم ضبطه في save() للموديل
            )
            lines_to_create.append(line)

        # حفظ الأسطر واحداً واحداً لضمان تشغيل منطق save() (amount_residual / is_reconciled)
        for line in lines_to_create:
            line.save()

    def get_success_url(self):
        # نذهب لصفحة التفاصيل لمراجعة ما تم رفعه
        return reverse("banking:bank_statement_detail", kwargs={"pk": self.object.pk})


class BankStatementDetailView(BankBaseView, DetailView):
    """عرض تفاصيل الكشف والأسطر التي بداخله"""
    model = BankStatement
    template_name = "banking/bank_statement_detail.html"
    context_object_name = "statement"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = _("تفاصيل الكشف: ") + self.object.name
        ctx["lines"] = self.object.lines.order_by("date", "id")
        return ctx


class BankStatementUpdateView(BankBaseView, UpdateView):
    model = BankStatement
    form_class = BankStatementForm
    template_name = "banking/bank_statement_form.html"

    def get_success_url(self):
        return reverse("banking:bank_statement_list")


class BankStatementDeleteView(BankBaseView, DeleteView):
    model = BankStatement
    success_url = reverse_lazy("banking:bank_statement_list")
    template_name = "banking/confirm_delete.html"


# =========================================================
# 4. Reconciliation Dashboard (The Core Feature)
# =========================================================

class ReconciliationDashboardView(BankBaseView, DetailView):
    """
    لوحة القيادة للتسوية.
    تعرض عمودين:
    1. حركات البنك غير المسواة (لهذا الحساب).
    2. قيود المحاسبة غير المسواة (لنفس حساب الأستاذ).
    """
    model = BankAccount
    template_name = "banking/reconciliation_dashboard.html"
    context_object_name = "bank_account"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        bank_account = self.object
        gl_account = bank_account.account  # حساب الأستاذ المرتبط

        ctx["title"] = _("تسوية: ") + bank_account.name

        # 1. جلب حركات البنك غير المسواة (أو المسواة جزئياً)
        ctx["bank_lines"] = (
            BankStatementLine.objects
            .filter(statement__bank_account=bank_account)
            .exclude(amount_residual=0)
            .order_by("date", "id")
        )

        # 2. جلب قيود المحاسبة غير المسواة لهذا الحساب
        # نستخدم حقل reconciled (bool) الذي يحدث عبر التسوية البنكية
        ctx["journal_items"] = (
            JournalLine.objects
            .filter(account=gl_account, reconciled=False)
            .order_by("entry__date", "id")
        )

        return ctx


# =========================================================
# 5. API / AJAX Actions (JSON Responses)
# =========================================================

@require_POST
def perform_reconciliation(request):
    """
    يستقبل طلب AJAX لربط سطر بنكي بسطر محاسبي.
    Data (JSON):
      {
        "bank_line_id": 1,
        "journal_item_id": 50,
        "amount": "100.000"
      }
    """
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    bank_line_id = data.get("bank_line_id")
    journal_item_id = data.get("journal_item_id")
    amount_raw = data.get("amount")

    if not (bank_line_id and journal_item_id and amount_raw):
        return JsonResponse(
            {"status": "error", "message": _("بيانات غير مكتملة.")},
            status=400,
        )

    try:
        amount = Decimal(str(amount_raw))
    except Exception:
        return JsonResponse(
            {"status": "error", "message": _("صيغة المبلغ غير صحيحة.")},
            status=400,
        )

    if amount == 0:
        return JsonResponse(
            {"status": "error", "message": _("لا يمكن تسوية مبلغ صفر.")},
            status=400,
        )

    try:
        with transaction.atomic():
            bank_line = get_object_or_404(BankStatementLine, pk=bank_line_id)
            journal_item = get_object_or_404(JournalLine, pk=journal_item_id)

            # إنشاء التسوية (التحقق المنطقي في clean() للموديل)
            rec = BankReconciliation.objects.create(
                bank_line=bank_line,
                journal_item=journal_item,
                amount_reconciled=amount,
            )

            # تحديث حالة القيد المحاسبي (مسوى/غير مسوى) بناءً على الخاصية is_fully_reconciled
            journal_item.refresh_from_db()
            journal_item.reconciled = journal_item.is_fully_reconciled
            journal_item.save(update_fields=["reconciled"])

            # إعادة تحميل سطر البنك بعد تحديث المتبقي عن طريق الموديل
            bank_line.refresh_from_db()

            return JsonResponse(
                {
                    "status": "success",
                    "message": _("تمت المطابقة بنجاح."),
                    "bank_line_residual": str(bank_line.amount_residual),
                    "bank_line_is_reconciled": bank_line.is_reconciled,
                    "journal_item_reconciled": journal_item.reconciled,
                    "journal_item_open_amount": str(journal_item.amount_open),
                    "reconciliation_id": rec.pk,
                }
            )

    except Exception as e:
        return JsonResponse(
            {"status": "error", "message": str(e)},
            status=400,
        )


@require_POST
def undo_reconciliation(request):
    """
    فك التسوية (حذف الربط)
    Data (JSON):
      {
        "reconciliation_id": 55
      }
    """
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    rec_id = data.get("reconciliation_id")
    if not rec_id:
        return JsonResponse(
            {"status": "error", "message": _("رقم التسوية مفقود.")},
            status=400,
        )

    try:
        with transaction.atomic():
            rec = get_object_or_404(BankReconciliation, pk=rec_id)
            bank_line = rec.bank_line
            journal_item = rec.journal_item

            # delete() في الموديل يعيد المتبقي لسطر البنك
            rec.delete()

            # تحديث سطر البنك
            bank_line.refresh_from_db()

            # تحديث حالة القيد المحاسبي
            journal_item.refresh_from_db()
            journal_item.reconciled = journal_item.is_fully_reconciled
            journal_item.save(update_fields=["reconciled"])

        return JsonResponse(
            {
                "status": "success",
                "message": _("تم إلغاء المطابقة."),
                "bank_line_residual": str(bank_line.amount_residual),
                "bank_line_is_reconciled": bank_line.is_reconciled,
                "journal_item_reconciled": journal_item.reconciled,
                "journal_item_open_amount": str(journal_item.amount_open),
            }
        )
    except Exception as e:
        return JsonResponse(
            {"status": "error", "message": str(e)},
            status=400,
        )
