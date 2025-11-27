from django.urls import path
from . import views

app_name = "accounting"

urlpatterns = [
    # ---------------- Dashboard ----------------
    path("", views.AccountingDashboardView.as_view(), name="dashboard"),

    # ================= SALES INVOICES =================
    path("sales/invoices/", views.SalesInvoiceListView.as_view(), name="sales_invoice_list"),
    path("sales/invoices/new/", views.SalesInvoiceCreateView.as_view(), name="sales_invoice_create"),
    path("sales/invoices/<int:pk>/", views.InvoiceDetailView.as_view(), name="sales_invoice_detail"),
    path("sales/invoices/<int:pk>/edit/", views.InvoiceUpdateView.as_view(), name="sales_invoice_edit"),
    path("sales/invoices/<int:pk>/print/", views.InvoicePrintView.as_view(), name="sales_invoice_print"),
    path("sales/invoices/<int:pk>/confirm/", views.invoice_confirm_view, name="sales_invoice_confirm"),
    path("sales/invoices/<int:pk>/unpost/", views.invoice_unpost_view, name="sales_invoice_unpost"),

    # ================= PURCHASE INVOICES =================
    path("purchases/invoices/", views.PurchaseInvoiceListView.as_view(), name="purchase_invoice_list"),
    path("purchases/invoices/new/", views.PurchaseInvoiceCreateView.as_view(), name="purchase_invoice_create"),
    path("purchases/invoices/<int:pk>/", views.InvoiceDetailView.as_view(), name="purchase_invoice_detail"),
    path("purchases/invoices/<int:pk>/edit/", views.InvoiceUpdateView.as_view(), name="purchase_invoice_edit"),
    path("purchases/invoices/<int:pk>/print/", views.InvoicePrintView.as_view(), name="purchase_invoice_print"),
    path("purchases/invoices/<int:pk>/confirm/", views.invoice_confirm_view, name="purchase_invoice_confirm"),
    path("purchases/invoices/<int:pk>/unpost/", views.invoice_unpost_view, name="purchase_invoice_unpost"),


    # ---------------- Accounts ----------------
    path("accounts/", views.AccountListView.as_view(), name="account_list"),
    path("accounts/new/", views.AccountCreateView.as_view(), name="account_create"),
    path("accounts/<int:pk>/edit/", views.AccountUpdateView.as_view(), name="account_edit"),

    # Payments
    path("payments/", views.PaymentListView.as_view(), name="payment_list"),
    path("payments/new/", views.PaymentCreateView.as_view(), name="payment_create"),
    path("payments/<int:pk>/", views.PaymentDetailView.as_view(), name="payment_detail"),
    path("payments/<int:pk>/edit/", views.PaymentUpdateView.as_view(), name="payment_update"),

    # ---------------- Journals ----------------
    path("journals/", views.journal_list_view, name="journal_list"),
    path("journals/new/", views.journal_create_view, name="journal_create"),
    path("journals/<int:pk>/edit/", views.journal_update_view, name="journal_edit"),

    # ---------------- Journal entries ----------------
    path("entries/", views.JournalEntryListView.as_view(), name="journal_entry_list"),
    path("entries/new/", views.JournalEntryCreateView.as_view(), name="journal_entry_create"),
    path("entries/<int:pk>/", views.JournalEntryDetailView.as_view(), name="journal_entry_detail"),
    path("entries/<int:pk>/edit/", views.JournalEntryUpdateView.as_view(), name="journal_entry_update"),
    path("entries/<int:pk>/post/", views.journalentry_post_view, name="journal_entry_post"),
    path("entries/<int:pk>/unpost/", views.journalentry_unpost_view, name="journal_entry_unpost"),

    # ---------------- Reports ----------------
    path("reports/trial-balance/", views.trial_balance_view, name="trial_balance"),
    path("reports/account-ledger/", views.account_ledger_view, name="account_ledger"),

    # ---------------- Fiscal year & settings ----------------
    path("setup/fiscal-year/", views.fiscal_year_setup_view, name="fiscal_year_setup"),
    path("settings/fiscal-years/", views.FiscalYearListView.as_view(), name="fiscal_year_list"),
    path("settings/fiscal-years/new/", views.FiscalYearCreateView.as_view(), name="fiscal_year_create"),
    path("settings/fiscal-years/<int:pk>/edit/", views.FiscalYearUpdateView.as_view(), name="fiscal_year_edit"),
    path("settings/fiscal-years/<int:pk>/close/", views.FiscalYearCloseView.as_view(), name="fiscal_year_close"),

    path("settings/chart-of-accounts/bootstrap/", views.chart_of_accounts_bootstrap_view, name="chart_of_accounts_bootstrap"),
    path("settings/chart-of-accounts/import/", views.chart_of_accounts_import_view, name="chart_of_accounts_import"),
    path("settings/chart-of-accounts/export/", views.chart_of_accounts_export_view, name="chart_of_accounts_export"),
    path("settings/journals/", views.ledger_settings_view, name="ledger_settings"),
    path("settings/", views.accounting_settings_view, name="accounting_settings"),
]
