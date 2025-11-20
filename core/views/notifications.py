# core/views.py
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.generic import ListView, View

from core.models import Notification, AuditLog


@method_decorator(login_required, name="dispatch")
class NotificationListView(ListView):
    """
    List notifications for the current user.
    """
    model = Notification
    template_name = "core/notifications/list.html"
    context_object_name = "notifications"
    paginate_by = 20

    def get_queryset(self):
        # استخدام المانجر/الكويري ست الجاهزة بدل تكرار الفلاتر
        return Notification.objects.for_user(self.request.user)


@method_decorator(login_required, name="dispatch")
class NotificationReadRedirectView(View):
    def get(self, request, public_id, *args, **kwargs):
        notification = get_object_or_404(
            Notification,
            public_id=public_id,
            recipient=request.user,
            is_deleted=False,
        )

        if not notification.is_read:
            notification.mark_as_read(user=request.user)

        url = notification.url or ""

        # لو النوتفيكشن يحمل رابط خارجي كامل (نادر)
        if url.startswith("http://") or url.startswith("https://"):
            return redirect(url)

        # لو فيه path يبدأ من /ar/ أو /en/ نخليه كما هو (متوافق مع بيانات قديمة)
        if url.startswith("/ar/") or url.startswith("/en/"):
            return redirect(url)

        # الآن نتعامل مع path مثل "/accounting/orders/1/"
        if url.startswith("/"):
            lang = getattr(request, "LANGUAGE_CODE", "en")
            # نضيف /ar أو /en قبل الـ path
            final_url = f"/{lang}{url}"
            return redirect(final_url)

        # fallback: لو ما عرفنا نتعامل مع الـ url
        messages.info(request, _("تعذّر فتح الرابط المرتبط بهذا الإشعار."))
        return redirect("core:notification_list")



@login_required
@require_POST
def notification_mark_all_read(request):
    """
    Mark all notifications for the current user as read.
    """
    qs = Notification.objects.filter(
        recipient=request.user,
        is_deleted=False,
        is_read=False,
    )
    now = timezone.now()
    qs.update(is_read=True, read_at=now)
    messages.success(request, _("تم تعليم جميع الإشعارات كمقروءة."))
    return redirect("core:notification_list")


@login_required
@require_POST
def notification_delete(request, public_id):
    """
    Soft delete a single notification for the current user.
    """
    notification = get_object_or_404(
        Notification,
        public_id=public_id,
        recipient=request.user,
        is_deleted=False,
    )
    notification.soft_delete(user=request.user)
    messages.success(request, _("تم حذف الإشعار."))
    return redirect("core:notification_list")


@method_decorator(staff_member_required, name="dispatch")
class AuditLogListView(ListView):
    """
    Staff-only list view to inspect audit logs.
    """
    model = AuditLog
    template_name = "core/audit/log_list.html"
    context_object_name = "logs"
    paginate_by = 50

    def get_queryset(self):
        """
        Optional filters:
        - ?action=create/update/...
        - ?user=<user_id>
        - ?q=search text in message
        """
        qs = (
            super()
            .get_queryset()
            .select_related("actor", "target_content_type")
        )

        action = self.request.GET.get("action")
        if action:
            qs = qs.filter(action=action)

        user_id = self.request.GET.get("user")
        if user_id:
            qs = qs.filter(actor_id=user_id)

        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(message__icontains=q)

        return qs
