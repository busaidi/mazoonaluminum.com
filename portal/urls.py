# portal/notifications.py
from django.urls import path

from .views import (
    PortalDashboardView,
    PortalInvoiceListView,
    PortalInvoiceDetailView,
    PortalPaymentListView,
    PortalInvoicePrintView,
    PortalProfileUpdateView,
    PortalOrderListView,
    PortalOrderDetailView,
    PortalOrderCreateView,
    CartCheckoutView,
)

app_name = "portal"

urlpatterns = [
    # Dashboard / Profile
    path("", PortalDashboardView.as_view(), name="dashboard"),
    path("profile/", PortalProfileUpdateView.as_view(), name="profile"),

    # Invoices / Payments
    path("invoices/", PortalInvoiceListView.as_view(), name="invoice_list"),
    path("invoices/<str:number>/", PortalInvoiceDetailView.as_view(), name="invoice_detail"),
    path("invoices/<str:number>/print/", PortalInvoicePrintView.as_view(), name="invoice_print"),
    path("payments/", PortalPaymentListView.as_view(), name="payment_list"),

    # Orders
    path("orders/", PortalOrderListView.as_view(), name="order_list"),
    path("orders/<int:pk>/", PortalOrderDetailView.as_view(), name="order_detail"),
    path("orders/create/<int:product_id>/",PortalOrderCreateView.as_view(),name="order_create",),
    path("cart/checkout/",CartCheckoutView.as_view(),name="cart_checkout",),
]
