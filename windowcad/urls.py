# windowcad/urls.py
from django.urls import path

from .views import (
    WindowDesignListView,
    WindowDesignDetailView,
    WindowSketchView,
    download_window_dxf,
)

app_name = "windowcad"

urlpatterns = [
    # قائمة كل التصاميم
    path(
        "",
        WindowDesignListView.as_view(),
        name="window_list",
    ),

    # صفحة الرسم (Sketch) – ترسم الفتحة + المليونات
    path(
        "sketch/",
        WindowSketchView.as_view(),
        name="window_sketch",
    ),

    # تفاصيل تصميم محدد + رسم SVG + الهاردوير
    path(
        "<int:pk>/",
        WindowDesignDetailView.as_view(),
        name="window_detail",
    ),

    # تنزيل DXF للتصميم
    path(
        "<int:pk>/dxf/",
        download_window_dxf,
        name="window_dxf",
    ),
]
