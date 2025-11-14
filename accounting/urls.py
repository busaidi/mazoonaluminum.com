# accounting/urls.py

from django.urls import path

from . import views

app_name = "accounting"

urlpatterns = [
    # Dashboard
    path("", views.AccountingDashboardView.as_view(), name="dashboard"),

    # Invoices
    path("invoices/", views.InvoiceListView.as_view(), name="invoice_list"),
    path("invoices/new/", views.InvoiceCreateView.as_view(), name="invoice_create"),
    path(
        "invoices/<str:number>/",
        views.InvoiceDetailView.as_view(),
        name="invoice_detail",
    ),
    path(
        "invoices/<str:number>/payments/new/",
        views.InvoicePaymentCreateView.as_view(),
        name="invoice_add_payment",
    ),
    path(
        "invoices/<str:number>/print/",
        views.InvoicePrintView.as_view(),
        name="invoice_print",
    ),

    # Customers
    path("customers/", views.CustomerListView.as_view(), name="customer_list"),
    path("customers/new/", views.CustomerCreateView.as_view(), name="customer_create"),
    path(
        "customers/<int:pk>/",
        views.CustomerDetailView.as_view(),
        name="customer_detail",
    ),
    path(
        "customers/<int:pk>/edit/",
        views.CustomerUpdateView.as_view(),
        name="customer_edit",
    ),
    path(
        "customers/<int:pk>/delete/",
        views.CustomerDeleteView.as_view(),
        name="customer_delete",
    ),
    path(
        "customers/<int:pk>/payments/new/",
        views.CustomerPaymentCreateView.as_view(),
        name="customer_add_payment",
    ),

    # Orders (staff)
    path("orders/", views.staff_order_list, name="order_list"),
    path("orders/create/", views.staff_order_create, name="order_create"),
    path("orders/<int:pk>/", views.staff_order_detail, name="order_detail"),
    path("orders/<int:pk>/confirm/", views.staff_order_confirm, name="order_confirm"),
]
