# core/notifications.py
from django.urls import path

from core.views import AuditLogListView

app_name = "core"

urlpatterns = [

    path(
        "audit-log/",
        AuditLogListView.as_view(),
        name="audit_log_list",
    ),

]

