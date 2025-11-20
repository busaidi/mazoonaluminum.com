# core/notifications.py
from django.urls import path
from core.views.attachments import AttachmentDeleteView, AttachmentCreateView

app_name = "core"

urlpatterns = [
    path("attachments/add/", AttachmentCreateView.as_view(), name="attachment_add"),
    path("attachments/<int:pk>/delete/", AttachmentDeleteView.as_view(), name="attachment_delete"),
]

