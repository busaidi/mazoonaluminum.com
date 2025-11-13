# accounting/urls.py

from django.urls import path
from . import views

app_name = "accounting"

urlpatterns = [
    # سنضيف روابط الفواتير والدفعات لاحقاً في المرحلة الثالثة
    # هذا مجرد placeholder عشان ما يعطي خطأ في تحميل urls
    path("ping/", views.ping, name="ping"),
]
