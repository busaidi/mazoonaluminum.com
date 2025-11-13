from django.urls import path

from .views import (
    PortalDashboardView,
    PortalInvoiceListView,
    PortalInvoiceDetailView,
    PortalPaymentListView,
    PortalInvoicePrintView,
    PortalProfileUpdateView,
)

app_name = "portal"

urlpatterns = [
    path("", PortalDashboardView.as_view(), name="dashboard"),
    path("profile/", PortalProfileUpdateView.as_view(), name="profile"),
    path("invoices/", PortalInvoiceListView.as_view(), name="invoice_list"),
    path("invoices/<str:number>/", PortalInvoiceDetailView.as_view(), name="invoice_detail"),
    path("invoices/<str:number>/print/", PortalInvoicePrintView.as_view(), name="invoice_print"),
    path("payments/", PortalPaymentListView.as_view(), name="payment_list"),
]
