from django.urls import path
from . import views
from .views import SalesDocumentPrintView, product_api

app_name = "sales"

urlpatterns = [
    # لوحة التحكم
    path("", views.SalesDashboardView.as_view(), name="dashboard"),


    # CRUD الموحد للمبيعات (عرض سعر + أمر بيع)
    path("sales/", views.SalesDocumentListView.as_view(), name="sales_list"),
    path("sales/new/", views.SalesDocumentCreateView.as_view(), name="sales_create"),
    path("product/api/", product_api, name="product_api_search"),  # للبحث
    path("product/api/<int:pk>/", product_api, name="product_api_uom"),  # للمعلومات
    path("sales/<int:pk>/", views.SalesDocumentDetailView.as_view(), name="sales_detail"),
    path("sales/<int:pk>/edit/", views.SalesDocumentUpdateView.as_view(), name="sales_edit"),




    # تحويل عرض السعر → أمر بيع
    path("sales/<int:pk>/convert/", views.ConvertQuotationToOrderView.as_view(), name="quotation_convert"),
    path("sales/<int:pk>/cancel/", views.CancelSalesDocumentView.as_view(), name="sales_cancel"),
    path("sales/<int:pk>/reset/", views.ResetSalesDocumentToDraftView.as_view(), name="sales_reset"),
    path("sales/<int:pk>/reopen/", views.sales_reopen_view, name="sales_reopen"),


    # تعليم أمر البيع كمفوتر
    path("sales/<int:pk>/mark-invoiced/", views.MarkOrderInvoicedView.as_view(), name="order_mark_invoiced"),
    path("sales/<int:pk>/print/", SalesDocumentPrintView.as_view(), name="sales_print"),

    # مذكرات التسليم
    path("sales/<int:order_pk>/delivery/new/", views.DeliveryNoteCreateView.as_view(), name="delivery_note_create"),
    path("deliveries/", views.DeliveryNoteListView.as_view(), name="delivery_note_list"),
    path("deliveries/<int:pk>/", views.DeliveryNoteDetailView.as_view(), name="delivery_note_detail"),
]
