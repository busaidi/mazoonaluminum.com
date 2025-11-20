# accounting/url.py

from django.urls import path

from . import views

app_name = "accounting"

urlpatterns = [
    # --------------------------------------------------
    # Accounting
    # --------------------------------------------------
    path("", views.AccountingDashboardView.as_view(), name="dashboard"),
    path("invoices/", views.InvoiceListView.as_view(), name="invoice_list"),
    path("invoices/new/", views.InvoiceCreateView.as_view(), name="invoice_create"),
    path("invoices/<str:serial>/edit/",views.InvoiceUpdateView.as_view(),name="invoice_update",),
    path("invoices/<str:serial>/",views.InvoiceDetailView.as_view(),name="invoice_detail",),
    path("invoices/<str:serial>/payments/new/",views.InvoicePaymentCreateView.as_view(),name="invoice_add_payment",),
    path("invoices/<str:serial>/print/",views.InvoicePrintView.as_view(),name="invoice_print",),
    path("invoices/<int:pk>/confirm/",views.invoice_confirm_view,name="invoice_confirm",),
    path("invoices/<int:pk>/unpost/",views.invoice_unpost_view,name="invoice_unpost",),

    #Setting
    path("settings/",views.accounting_settings_view,name="sales_settings",),


    path("customers/",views.CustomerListView.as_view(),name="customer_list",),
    path("customers/new/",views.CustomerCreateView.as_view(),name="customer_create",),
    path("customers/<int:pk>/",views.CustomerDetailView.as_view(),name="customer_detail",),
    path("customers/<int:pk>/edit/",views.CustomerUpdateView.as_view(),name="customer_edit",),
    path("customers/<int:pk>/delete/",views.CustomerDeleteView.as_view(),name="customer_delete",),
    path("customers/<int:pk>/payments/new/",views.CustomerPaymentCreateView.as_view(),name="customer_add_payment",),

    # --------------------------------------------------
    # Payments (staff)
    # --------------------------------------------------
    path("payments/", views.PaymentListView.as_view(), name="payment_list"),
    path("payments/new/", views.PaymentCreateView.as_view(), name="payment_create"),
    path("payments/<int:pk>/edit/",views.PaymentUpdateView.as_view(),name="payment_update",),
    path("payments/<int:pk>/apply/",views.apply_general_payment,name="payment_apply",),
    path("payments/<int:pk>/print/",views.PaymentPrintView.as_view(),name="payment_print",),

    # --------------------------------------------------
    # Orders (staff)
    # --------------------------------------------------
    path("orders/", views.OrderListView.as_view(), name="order_list"),
    path("orders/new/", views.OrderCreateView.as_view(), name="order_create"),
    path("orders/<int:pk>/", views.OrderDetailView.as_view(), name="order_detail"),
    path("orders/<int:pk>/edit/", views.OrderUpdateView.as_view(), name="order_update"),
    path("orders/<int:pk>/confirm/",views.staff_order_confirm, name="order_confirm",),
    path("orders/<int:pk>/to-invoice/",views.order_to_invoice,name="order_to_invoice",),
    path("orders/<int:pk>/print/",views.OrderPrintView.as_view(),name="order_print",),
]
