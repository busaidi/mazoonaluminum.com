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
]
