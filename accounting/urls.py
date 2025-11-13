# accounting/urls.py

from django.urls import path
from . import views as acc_views
from .views import InvoiceListView, InvoiceCreateView, InvoiceDetailView, InvoicePaymentCreateView, \
    AccountingDashboardView, CustomerListView, CustomerCreateView, CustomerUpdateView, CustomerDeleteView, \
    CustomerDetailView, CustomerPaymentCreateView, InvoicePrintView, OrderListView, OrderDetailView

app_name = "accounting"

urlpatterns = [
    path("", AccountingDashboardView.as_view(), name="dashboard"),
    path("invoices/", InvoiceListView.as_view(), name="invoice_list"),
    path("invoices/new/", InvoiceCreateView.as_view(), name="invoice_create"),
    path("invoices/<str:number>/", InvoiceDetailView.as_view(), name="invoice_detail"),
    path("invoices/<str:number>/payments/new/", InvoicePaymentCreateView.as_view(), name="invoice_add_payment"),
    path("invoices/<str:number>/print/", InvoicePrintView.as_view(), name="invoice_print"),

    path("customers/", CustomerListView.as_view(), name="customer_list"),
    path("customers/new/", CustomerCreateView.as_view(), name="customer_create"),
    path("customers/<int:pk>/", CustomerDetailView.as_view(), name="customer_detail"),
    path("customers/<int:pk>/edit/", CustomerUpdateView.as_view(), name="customer_edit"),
    path("customers/<int:pk>/delete/",CustomerDeleteView.as_view(),name="customer_delete",),
    path("customers/<int:pk>/payments/new/",CustomerPaymentCreateView.as_view(),name="customer_add_payment",),

    # path("orders/", OrderListView.as_view(), name="order_list"),
    # path("orders/<int:pk>/", OrderDetailView.as_view(), name="order_detail"),
    # path("orders/", acc_views.staff_order_list, name="accounting_orders_list"),
    # path("orders/create/", acc_views.staff_order_create, name="accounting_order_create"),
    # path("orders/<int:pk>/", acc_views.staff_order_detail, name="accounting_order_detail"),
    # path("orders/<int:pk>/confirm/", acc_views.staff_order_confirm, name="accounting_order_confirm"),

    # path("orders/", acc_views.staff_order_list, name="accounting_orders_list"),
    # path("orders/create/", acc_views.staff_order_create, name="accounting_order_create"),
    # path("orders/<int:pk>/", acc_views.staff_order_detail, name="accounting_order_detail"),
    # path("orders/<int:pk>/confirm/", acc_views.staff_order_confirm, name="accounting_order_confirm"),
    path("orders/", acc_views.staff_order_list, name="order_list"),
    path("orders/create/", acc_views.staff_order_create, name="order_create"),
    path("orders/<int:pk>/", acc_views.staff_order_detail, name="order_detail"),
    path("orders/<int:pk>/confirm/", acc_views.staff_order_confirm, name="order_confirm"),
]

