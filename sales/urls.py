# sales/urls.py
from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    path(
        "",
        views.SalesDashboardView.as_view(),
        name="dashboard",
    ),

    # ===== Quotations =====
    path(
        "quotations/",
        views.QuotationListView.as_view(),
        name="quotation_list",
    ),
    path(
        "quotations/new/",
        views.QuotationCreateView.as_view(),
        name="quotation_create",
    ),
    path(
        "quotations/<int:pk>/",
        views.QuotationDetailView.as_view(),
        name="quotation_detail",
    ),
    path(
        "quotations/<int:pk>/edit/",
        views.QuotationUpdateView.as_view(),
        name="quotation_edit"),
    path(
        "quotations/<int:pk>/convert-to-order/",
        views.QuotationToOrderView.as_view(),
        name="quotation_convert_to_order",
    ),

    # ===== Orders =====
    path(
        "orders/",
        views.SalesOrderListView.as_view(),
        name="order_list",
    ),
    path(
        "orders/new/",
        views.SalesOrderCreateView.as_view(),
        name="order_create",
    ),
    path(
        "orders/<int:pk>/",
        views.SalesOrderDetailView.as_view(),
        name="order_detail",
    ),
    path(
        "orders/<int:pk>/convert-to-delivery/",
        views.OrderToDeliveryView.as_view(),
        name="order_convert_to_delivery",
    ),
    path(
        "orders/<int:pk>/convert-to-invoice/",
        views.OrderToInvoiceView.as_view(),
        name="order_convert_to_invoice",
    ),

    # ===== Delivery Notes =====
    path(
        "delivery-notes/",
        views.DeliveryNoteListView.as_view(),
        name="delivery_list",
    ),
    path(
        "delivery-notes/new/",
        views.DeliveryNoteCreateView.as_view(),
        name="delivery_create",
    ),
    path(
        "delivery-notes/<int:pk>/",
        views.DeliveryNoteDetailView.as_view(),
        name="delivery_detail",
    ),
    path(
        "delivery-notes/<int:pk>/convert-to-invoice/",
        views.DeliveryToInvoiceView.as_view(),
        name="delivery_convert_to_invoice",
    ),
]
