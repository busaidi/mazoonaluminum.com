# sales/urls.py
from django.urls import path
from . import views

app_name = 'sales'

urlpatterns = [
    path('', views.SalesDashboardView.as_view(), name='dashboard'),

    # القائمة الموحدة
    path('documents/', views.SalesListView.as_view(), name='document_list'),

    # الإنشاء
    path('documents/add/', views.SalesCreateView.as_view(), name='document_create'),

    # التفاصيل والتعديل
    path('documents/<int:pk>/', views.SalesDocumentDetailView.as_view(), name='document_detail'),
    path('documents/<int:pk>/edit/', views.SalesDocumentUpdateView.as_view(), name='document_edit'),

    # الإجراءات
    path('documents/<int:pk>/confirm/', views.confirm_document, name='document_confirm'),  # الزر السحري
    path('documents/<int:pk>/cancel/', views.cancel_document_view, name='document_cancel'),
    path('documents/<int:pk>/restore/', views.restore_document_view, name='document_restore'),
    path('documents/<int:pk>/delete/', views.SalesDocumentDeleteView.as_view(), name='document_delete'),

    # التسليم
    path('documents/<int:pk>/create-delivery/', views.create_delivery_from_order_view, name='document_create_delivery'),
    path('deliveries/', views.DeliveryListView.as_view(), name='delivery_list'),
    path('deliveries/<int:pk>/', views.DeliveryDetailView.as_view(), name='delivery_detail'),
    path('deliveries/<int:pk>/confirm/', views.confirm_delivery_view, name='delivery_confirm'),
    path('deliveries/<int:pk>/delete/', views.DeliveryDeleteView.as_view(), name='delivery_delete'),

    # Delivery
    path('deliveries/', views.DeliveryListView.as_view(), name='delivery_list'),


    # رابط التسليم المباشر الجديد
    path('deliveries/direct/', views.DirectDeliveryCreateView.as_view(), name='delivery_create_direct'),
    path('deliveries/<int:pk>/link-order/', views.link_delivery_to_order_view, name='delivery_link_order'),
]