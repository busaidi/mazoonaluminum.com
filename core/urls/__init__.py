# core/urls/__init__.py
from .attachments import urlpatterns as attachment_urlpatterns
from .notifications import urlpatterns as notification_urlpatterns
from .audit import urlpatterns as audit_urlpatterns

app_name = "core"

urlpatterns = [
    *attachment_urlpatterns,
    *notification_urlpatterns,
    *audit_urlpatterns,
]
