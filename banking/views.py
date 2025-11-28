import pandas as pd  # لقراءة ملفات الاكسل
from decimal import Decimal

from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext as _
from django.views.generic import (
    TemplateView, ListView, CreateView, UpdateView, DetailView, DeleteView
)
from django.db import transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.contrib import messages

from accounting.models import JournalLine
# تأكد من مسار الاستيراد الصحيح للميكسن الخاص بك
from accounting.views import AccountingStaffRequiredMixin

from .models import (
    BankStatement,
    BankAccount,
    BankStatementLine,
    BankReconciliation
)
from .forms import BankStatementForm, BankAccountForm


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
    ordering = ["-date", "-id"]  # تم تعديل date_from إلى date حسب المودل الجديد

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = _("سجل كشوفات البنك")
        return ctx


class BankStatementUploadView(BankBaseView, CreateView):
    """
    الفيو المسؤول عن رفع الملف وقراءته (Parsing).
    هنا يحدث السحر: تحويل Excel إلى Database Rows.
    """
    model = BankStatement
    form_class = BankStatementForm
    template_name = "banking/bank_statement_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = _("رفع كشف بنكي جديد")
        return ctx

    def form_valid(self, form):
        # 1. نبدأ عملية ذرية (Atomic Transaction)
        # إذا حدث أي خطأ أثناء قراءة الملف، لا يتم حفظ الكشف ولا الأسطر
        with transaction.atomic():
            # حفظ الهيدر (الكشف) أولاً
            self.object = form.save()

            # 2. معالجة الملف إذا وجد
            uploaded_file = self.object.imported_file
            if uploaded_file:
                try:
                    self.process_file(uploaded_file, self.object)
                    messages.success(self.request, _("تم رفع ومعالجة الكشف بنجاح."))
                except Exception as e:
                    # في حال الخطأ، نظهر رسالة للمستخدم ونوقف الحفظ
                    form.add_error('imported_file', f"خطأ في قراءة الملف: {str(e)}")
                    return self.form_invalid(form)

        return super().form_valid(form)

    def process_file(self, file_obj, statement_obj):
        """
        دالة مساعدة لقراءة ملف الاكسل/CSV
        يفترض أن الملف يحتوي أعمدة: Date, Description, Reference, Amount
        """
        # تحديد الامتداد واستخدام المكتبة المناسبة
        if file_obj.name.endswith('.csv'):
            df = pd.read_csv(file_obj)
        else:
            df = pd.read_excel(file_obj)

        # تنظيف أسماء الأعمدة (إزالة المسافات وتحويلها لأحرف صغيرة)
        df.columns = df.columns.str.strip().str.lower()

        # التأكد من وجود الأعمدة الإجبارية (يمكنك تعديل الأسماء حسب صيغة بنكك)
        # مثال: نفترض أن البنك يسمي العمود 'transaction date' و 'amount'
        # هنا سنبحث عن أقرب اسم

        # -- منطق تبسيط للتوضيح --
        # سنفترض أن المستخدم يرفع ملفاً فيه أعمدة بالأسماء التالية:
        # date, label, ref, amount

        lines_to_create = []
        for index, row in df.iterrows():
            # تحويل التاريخ
            # date_val = pd.to_datetime(row.get('date')).date()

            # إنشاء السطر
            line = BankStatementLine(
                statement=statement_obj,
                date=row.get('date'),  # يجب التأكد أن الصيغة مقروءة لبايثون
                label=row.get('label') or row.get('description') or "No Desc",
                ref=row.get('ref', ''),
                amount=Decimal(str(row.get('amount', 0))),  # التحويل لـ Decimal مهم جداً
                # amount_residual سيتم حسابه تلقائياً في المودل عند الحفظ
            )
            lines_to_create.append(line)

        # الحفظ الجماعي (Bulk Create) أسرع، لكنه لا يشغل دالة save() الخاصة بالمودل
        # لذلك سنستخدم الحفظ العادي لضمان عمل logic الـ residual
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
        ctx["title"] = f"تفاصيل الكشف: {self.object.name}"
        # جلب الأسطر
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

        ctx["title"] = f"تسوية: {bank_account.name}"

        # 1. جلب حركات البنك غير المسواة (أو المسواة جزئياً)
        # نستبعد الحركات التي amount_residual = 0
        ctx["bank_lines"] = (
            BankStatementLine.objects
            .filter(statement__bank_account=bank_account)
            .exclude(amount_residual=0)
            .order_by("date")
        )

        # 2. جلب قيود المحاسبة غير المسواة
        # نفترض في مودل JournalItem لديك حقل لتتبع حالة التسوية أو نعتمد على جدول الربط
        # الطريقة الأدق: نجلب القيود التي ليس لها BankReconciliation يغطي كامل المبلغ
        # للتبسيط هنا: سنفترض أننا نريد عرض كل القيود على حساب البنك في دفتر الأستاذ
        # التي لم يتم ربطها بالكامل.

        # ملاحظة: هذا الكويري يعتمد على تصميم JournalItem لديك.
        # سنفترض وجود flag اسمه is_reconciled في JournalItem أو نحسبه
        ctx["journal_items"] = (
            JournalLine.objects
            .filter(account=gl_account)  # فقط القيود التي تخص هذا البنك
            .filter(reconciled=False)  # غير مسواة (حسب مودل المحاسبة لديك)
            .order_by("date")
        )

        return ctx


# =========================================================
# 5. API / AJAX Actions (JSON Responses)
# =========================================================

@require_POST
def perform_reconciliation(request):
    """
    يستقبل طلب AJAX لربط سطر بنكي بسطر محاسبي.
    Data: {bank_line_id: 1, journal_item_id: 50, amount: 100}
    """
    import json
    data = json.loads(request.body)

    bank_line_id = data.get("bank_line_id")
    journal_item_id = data.get("journal_item_id")
    amount = data.get("amount")  # المبلغ المراد تسويته

    try:
        with transaction.atomic():
            # جلب الكائنات
            bank_line = get_object_or_404(BankStatementLine, pk=bank_line_id)
            journal_item = get_object_or_404(JournalLine, pk=journal_item_id)

            # إنشاء التسوية
            rec = BankReconciliation.objects.create(
                bank_line=bank_line,
                journal_item=journal_item,
                amount_reconciled=Decimal(amount)
            )

            # (اختياري) تحديث حالة القيد المحاسبي لـ "مسوى" إذا تغطى المبلغ بالكامل
            # journal_item.check_reconciled_status() 

            return JsonResponse({
                "status": "success",
                "message": "تمت المطابقة بنجاح",
                "new_residual": str(bank_line.amount_residual)  # لإرسال المتبقي للواجهة لتحديثها
            })

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@require_POST
def undo_reconciliation(request):
    """
    فك التسوية (حذف الربط)
    Data: {reconciliation_id: 55}
    """
    import json
    data = json.loads(request.body)
    rec_id = data.get("reconciliation_id")

    try:
        rec = get_object_or_404(BankReconciliation, pk=rec_id)
        rec.delete()  # دالة delete في المودل ستعيد الأموال للسطر البنكي تلقائياً

        return JsonResponse({"status": "success", "message": "تم إلغاء المطابقة"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)