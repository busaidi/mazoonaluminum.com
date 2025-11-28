# banking/urls.py
from django.urls import path
from . import views

app_name = "banking"

urlpatterns = [
    # =============================================
    # 1. إدارة الحسابات البنكية (Bank Accounts)
    # =============================================
    path(
        "accounts/",
        views.BankAccountListView.as_view(),
        name="bank_account_list",
    ),
    path(
        "accounts/new/",
        views.BankAccountCreateView.as_view(),
        name="bank_account_create",
    ),
    path(
        "accounts/<int:pk>/edit/",
        views.BankAccountUpdateView.as_view(),
        name="bank_account_edit",
    ),
    # (اختياري) حذف حساب بنكي
    path(
        "accounts/<int:pk>/delete/",
        views.BankAccountDeleteView.as_view(),
        name="bank_account_delete",
    ),

    # =============================================
    # 2. كشوفات الحساب (Bank Statements)
    # =============================================
    path(
        "statements/",
        views.BankStatementListView.as_view(),
        name="bank_statement_list",
    ),
    path(
        "statements/upload/",
        views.BankStatementUploadView.as_view(),
        name="bank_statement_upload",
    ),
    # صفحة تعرض تفاصيل الكشف + الأسطر التي داخله (للمراجعة)
    path(
        "statements/<int:pk>/",
        views.BankStatementDetailView.as_view(),
        name="bank_statement_detail",
    ),
    path(
        "statements/<int:pk>/edit/",
        views.BankStatementUpdateView.as_view(),
        name="bank_statement_edit",
    ),
    path(
        "statements/<int:pk>/delete/",
        views.BankStatementDeleteView.as_view(),
        name="bank_statement_delete",
    ),

    # =============================================
    # 3. واجهة التسوية (The Reconciliation Workbench)
    # =============================================

    # الصفحة الرئيسية للتسوية: تعرض عمودين (البنك vs الدفاتر) لحساب محدد
    path(
        "accounts/<int:pk>/reconcile/",
        views.ReconciliationDashboardView.as_view(),
        name="reconciliation_dashboard",
    ),

    # =============================================
    # 4. إجراءات التسوية (API / AJAX Actions)
    # هذه الروابط سنستخدمها لاحقاً عند ضغط زر "تسوية" أو "إلغاء"
    # =============================================

    # تنفيذ عملية تسوية (ربط سطر بنكي بسطر محاسبي)
    path(
        "reconcile/perform/",
        views.perform_reconciliation,
        name="reconcile_perform",
    ),

    # إلغاء تسوية (فك الربط)
    path(
        "reconcile/undo/",
        views.undo_reconciliation,
        name="reconcile_undo",
    ),
]