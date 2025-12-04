# sales/urls.py

from django.urls import path

from . import views
from .views import SalesDocumentPrintView, product_api

app_name = "sales"

urlpatterns = [
    # ==================================================
    # لوحة تحكم المبيعات
    # ==================================================
    path(
        "",
        views.SalesDashboardView.as_view(),
        name="dashboard",
    ),

    # ==================================================
    # CRUD موحّد لمستندات المبيعات (عرض سعر + أمر بيع)
    # ==================================================
    path(
        "sales/",
        views.SalesDocumentListView.as_view(),
        name="sales_list",
    ),
    path(
        "sales/new/",
        views.SalesDocumentCreateView.as_view(),
        name="sales_create",
    ),
    path(
        "sales/<int:pk>/",
        views.SalesDocumentDetailView.as_view(),
        name="sales_detail",
    ),
    path(
        "sales/<int:pk>/edit/",
        views.SalesDocumentUpdateView.as_view(),
        name="sales_edit",
    ),

    # ==================================================
    # API بحث المنتجات + معلومات وحدات القياس للسطر
    # ==================================================
    # البحث عن المنتج بالكود / الاسم (تُستخدم مع حقل product_code في الفورم)
    path(
        "product/api/",
        product_api,
        name="product_api_search",
    ),
    # جلب معلومات المنتج + وحدات القياس المرتبطة به
    path(
        "product/api/<int:pk>/",
        product_api,
        name="product_api_uom",
    ),

    # ==================================================
    # إجراءات على مستند المبيعات (تحويل / إلغاء / إعادة ضبط)
    # ==================================================
    # تحويل عرض سعر → أمر بيع
    path(
        "sales/<int:pk>/convert/",
        views.ConvertQuotationToOrderView.as_view(),
        name="quotation_convert",
    ),
    # إلغاء مستند المبيعات
    path(
        "sales/<int:pk>/cancel/",
        views.CancelSalesDocumentView.as_view(),
        name="sales_cancel",
    ),
    # إعادة المستند إلى حالة المسودة
    path(
        "sales/<int:pk>/reset/",
        views.ResetSalesDocumentToDraftView.as_view(),
        name="sales_reset",
    ),
    # إعادة فتح المستند الملغي (إلى عرض سعر + مسودة)
    path(
        "sales/<int:pk>/reopen/",
        views.sales_reopen_view,
        name="sales_reopen",
    ),

    # ==================================================
    # فوترة أمر البيع + الطباعة
    # ==================================================
    # تعليم أمر البيع كمفوتر
    path(
        "sales/<int:pk>/mark-invoiced/",
        views.MarkOrderInvoicedView.as_view(),
        name="order_mark_invoiced",
    ),
    # طباعة مستند المبيعات
    path(
        "sales/<int:pk>/print/",
        SalesDocumentPrintView.as_view(),
        name="sales_print",
    ),

    # ==================================================
    # مذكرات التسليم (مرتبطة بأمر بيع أو مستقلة)
    # ==================================================
    # إنشاء مذكرة تسليم جديدة لأمر بيع محدد
    path(
        "sales/<int:order_pk>/delivery/new/",
        views.DeliveryNoteCreateView.as_view(),
        name="delivery_note_create",
    ),
    # إنشاء مذكرة تسليم مستقلة (بدون أمر بيع)
    path(
        "deliveries/new/",
        views.StandaloneDeliveryNoteCreateView.as_view(),
        name="delivery_note_create_standalone",
    ),
    # قائمة مذكرات التسليم
    path(
        "deliveries/",
        views.DeliveryNoteListView.as_view(),
        name="delivery_note_list",
    ),
    # تفاصيل مذكرة تسليم واحدة
    path(
        "deliveries/<int:pk>/",
        views.DeliveryNoteDetailView.as_view(),
        name="delivery_note_detail",
    ),
]
