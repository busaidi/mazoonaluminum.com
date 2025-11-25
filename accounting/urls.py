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
