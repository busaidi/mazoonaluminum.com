# sales/urls.py
from django.urls import path
from . import views

# اسم التطبيق مهم جداً لاستخدامه في القوالب
# مثال: {% url 'sales:quotation_list' %}
app_name = 'sales'

urlpatterns = [

    path('', views.SalesDashboardView.as_view(), name='dashboard'),
    # ===================================================================
    # 1. قوائم المبيعات (List Views)
    # ===================================================================
    path('quotations/', views.QuotationListView.as_view(), name='quotation_list'),
    path('orders/', views.OrderListView.as_view(), name='order_list'),

    # ===================================================================
    # 2. إنشاء المستندات (Create Views)
    # ===================================================================
    path('quotations/add/', views.QuotationCreateView.as_view(), name='quotation_create'),
    path('orders/add/', views.OrderCreateView.as_view(), name='order_create'),

    # ===================================================================
    # 3. تفاصيل وتعديل المستندات (Detail & Update)
    # لاحظ أننا نستخدم نفس الـ View للتعديل سواء كان عرض سعر أو أمر بيع
    # ===================================================================
    path('documents/<int:pk>/', views.SalesDocumentDetailView.as_view(), name='document_detail'),
    path('documents/<int:pk>/edit/', views.SalesDocumentUpdateView.as_view(), name='document_edit'),

    # ===================================================================
    # 4. إجراءات منطقية (Actions)
    # ===================================================================
    # الحذف
    path('documents/<int:pk>/delete/', views.delete_document, name='document_delete'),

    # التحويل من عرض سعر إلى أمر بيع
    path('documents/<int:pk>/convert/', views.convert_quotation_to_order, name='document_convert'),

    # تأكيد المستند
    path('documents/<int:pk>/confirm/', views.confirm_document, name='document_confirm'),

    # ===================================================================
    # 5. مذكرات التسليم (Delivery Notes)
    # ===================================================================

# Delivery Notes
    path('deliveries/', views.DeliveryListView.as_view(), name='delivery_list'),
    path('deliveries/add/', views.DeliveryNoteCreateView.as_view(), name='delivery_create'),
    path('deliveries/<int:pk>/', views.DeliveryDetailView.as_view(), name='delivery_detail'),
    path('deliveries/<int:pk>/confirm/', views.confirm_delivery, name='delivery_confirm'),
    path('deliveries/<int:pk>/delete/', views.delete_delivery, name='delivery_delete'),

    # ملاحظة: في ملف views.py السابق قمنا بالإشارة إلى 'delivery_list' عند النجاح
    # يجب إضافة الـ View الخاص بالقائمة لاحقاً، أو توجيه المستخدم لمكان آخر مؤقتاً.
    # path('deliveries/', views.DeliveryListView.as_view(), name='delivery_list'),
]