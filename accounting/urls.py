# accounting/urls.py

from django.urls import path
from .views import InvoiceListView, InvoiceCreateView, InvoiceDetailView, InvoicePaymentCreateView, \
    AccountingDashboardView, CustomerListView, CustomerCreateView, CustomerUpdateView, CustomerDeleteView, \
    CustomerDetailView, CustomerPaymentCreateView

app_name = "accounting"

urlpatterns = [
    path("", AccountingDashboardView.as_view(), name="dashboard"),
    path("invoices/", InvoiceListView.as_view(), name="invoice_list"),
    path("invoices/new/", InvoiceCreateView.as_view(), name="invoice_create"),
    path("invoices/<str:number>/", InvoiceDetailView.as_view(), name="invoice_detail"),
    path("invoices/<str:number>/payments/new/", InvoicePaymentCreateView.as_view(), name="invoice_add_payment"),

    path("customers/", CustomerListView.as_view(), name="customer_list"),
    path("customers/new/", CustomerCreateView.as_view(), name="customer_create"),
    path("customers/<int:pk>/", CustomerDetailView.as_view(), name="customer_detail"),
    path("customers/<int:pk>/edit/", CustomerUpdateView.as_view(), name="customer_edit"),
    path("customers/<int:pk>/delete/",CustomerDeleteView.as_view(),name="customer_delete",),
    path("customers/<int:pk>/payments/new/",CustomerPaymentCreateView.as_view(),name="customer_add_payment",),
]
