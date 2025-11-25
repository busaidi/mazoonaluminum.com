# payments/urls.py

from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    # =========================
    # Payments
    # =========================
    path(
        "",
        views.PaymentListView.as_view(),
        name="payment_list",
    ),
    path(
        "new/",
        views.PaymentCreateView.as_view(),
        name="payment_create",
    ),
    path(
        "<int:pk>/",
        views.PaymentDetailView.as_view(),
        name="payment_detail",
    ),
    path(
        "<int:pk>/edit/",
        views.PaymentUpdateView.as_view(),
        name="payment_edit",
    ),

    # =========================
    # Payment methods
    # =========================
    path(
        "methods/",
        views.PaymentMethodListView.as_view(),
        name="method_list",
    ),
    path(
        "methods/new/",
        views.PaymentMethodCreateView.as_view(),
        name="method_create",
    ),
    path(
        "methods/<int:pk>/edit/",
        views.PaymentMethodUpdateView.as_view(),
        name="method_edit",
    ),
]
