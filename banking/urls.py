# banking/urls.py
from django.urls import path
from . import views

app_name = "banking"

urlpatterns = [
    # التسوية البنكية
    path(
        "reconciliation/",
        views.BankReconciliationView.as_view(),
        name="bank_reconciliation",
    ),

    # الحسابات البنكية
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

    # كشوف البنك
    path(
        "statements/",
        views.BankStatementListView.as_view(),
        name="bank_statement_list",
    ),
    path(
        "statements/new/",
        views.BankStatementUploadView.as_view(),
        name="bank_statement_upload",
    ),
    path(
        "statements/<int:pk>/edit/",
        views.BankStatementUpdateView.as_view(),
        name="bank_statement_edit",
    ),
]
