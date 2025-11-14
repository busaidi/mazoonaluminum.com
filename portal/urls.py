from django.urls import path

from . import views

from .views import (
    PortalDashboardView,
    PortalInvoiceListView,
    PortalInvoiceDetailView,
    PortalPaymentListView,
    PortalInvoicePrintView,
    PortalProfileUpdateView,
    PortalOrderListView,
    PortalOrderDetailView,
)

app_name = "portal"

urlpatterns = [
    path("", PortalDashboardView.as_view(), name="dashboard"),
    path("profile/", PortalProfileUpdateView.as_view(), name="profile"),

    path("invoices/", PortalInvoiceListView.as_view(), name="invoice_list"),
    path("invoices/<str:number>/", PortalInvoiceDetailView.as_view(), name="invoice_detail"),
    path("invoices/<str:number>/print/", PortalInvoicePrintView.as_view(), name="invoice_print"),
    path("payments/", PortalPaymentListView.as_view(), name="payment_list"),

    path("orders/", PortalOrderListView.as_view(), name="order_list"),
    path("orders/<int:pk>/", PortalOrderDetailView.as_view(), name="order_detail"),

    path(
        "orders/create/<int:product_id>/",
        views.portal_order_create,
        name="portal_order_create",
    ),
    path("cart/checkout/", views.cart_checkout, name="cart_checkout"),
]
