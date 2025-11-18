# ledger/urls.py
from django.urls import path
from . import views
from .views import JournalEntryUpdateView

app_name = "ledger"

urlpatterns = [
    # Dashboard
    path("setup/fiscal-year/", views.fiscal_year_setup_view, name="fiscal_year_setup"),
    path("", views.LedgerDashboardView.as_view(), name="dashboard"),

    # Accounts
    path("accounts/", views.AccountListView.as_view(), name="account_list"),
    path("accounts/new/", views.AccountCreateView.as_view(), name="account_create"),
    path("accounts/<int:pk>/edit/", views.AccountUpdateView.as_view(), name="account_edit"),

    # Journal entries
    path("entries/", views.JournalEntryListView.as_view(), name="journalentry_list"),
    path("entries/new/", views.JournalEntryCreateView.as_view(), name="journalentry_create"),
    path("entries/<int:pk>/", views.JournalEntryDetailView.as_view(), name="journalentry_detail"),
    path("entries/<int:pk>/edit/",views.JournalEntryUpdateView.as_view(),name="journalentry_update",),

    #posted unposted
    path("entries/<int:pk>/post/",views.journalentry_post_view,name="journalentry_post",),
    path("entries/<int:pk>/unpost/",views.journalentry_unpost_view,name="journalentry_unpost",),

    # Reports
    path("reports/trial-balance/", views.trial_balance_view, name="trial_balance"),
    path("reports/account-ledger/", views.account_ledger_view, name="account_ledger"),

    # Fiscal Years Management
    path("settings/fiscal-years/", views.FiscalYearListView.as_view(), name="fiscal_year_list"),
    path("settings/fiscal-years/new/", views.FiscalYearCreateView.as_view(), name="fiscal_year_create"),
    path("settings/fiscal-years/<int:pk>/edit/", views.FiscalYearUpdateView.as_view(), name="fiscal_year_edit"),
    path("settings/fiscal-years/<int:pk>/close/", views.FiscalYearCloseView.as_view(), name="fiscal_year_close"),
    path("settings/chart-of-accounts/bootstrap/",views.chart_of_accounts_bootstrap_view,name="chart_of_accounts_bootstrap",),
    path("settings/chart-of-accounts/import/",views.chart_of_accounts_import_view,name="chart_of_accounts_import",),
    path("settings/chart-of-accounts/export/",views.chart_of_accounts_export_view,name="chart_of_accounts_export",),
    path("settings/journals/",views.ledger_settings_view,name="ledger_settings",),

]
