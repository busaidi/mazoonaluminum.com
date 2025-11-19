# core/views.py
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.generic import ListView, View

from core.models import Notification, AuditLog
from accounting.models import Invoice, Order


def is_accounting_staff(user):
    """
    Small helper to check if the user is accounting staff.
    This mirrors the logic used in accounting.views.
    """
    return (
        user.is_authenticated
        and user.is_active
        and user.groups.filter(name="accounting_staff").exists()
    )


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
        user = self.request.user
        return (
            Notification.objects
            .filter(recipient=user, is_deleted=False)
            .order_by("-created_at")
        )


@method_decorator(login_required, name="dispatch")
class NotificationReadRedirectView(View):
    """
    Mark notification as read and redirect to its related target
    (Order / Invoice) depending on user role (staff vs customer).
    """

    def get(self, request, public_id, *args, **kwargs):
        # Find the notification for the current user
        notification = get_object_or_404(
            Notification,
            public_id=public_id,
            recipient=request.user,
            is_deleted=False,
        )

        # Mark as read if not already
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=["is_read", "read_at"])

        target = notification.target

        # If no related object → go back to notifications list
        if target is None:
            messages.info(request, _("لا يوجد عنصر مرتبط بهذا الإشعار."))
            return redirect("core:notification_list")

        # Detect target type
        user = request.user
        staff = is_accounting_staff(user)

        # Invoice target
        if isinstance(target, Invoice):
            if staff:
                # Staff side invoice detail
                return redirect(
                    "accounting:invoice_detail",
                    number=target.number,
                )
            else:
                # Customer portal invoice detail
                return redirect(
                    "portal:invoice_detail",
                    number=target.number,
                )

        # Order target
        if isinstance(target, Order):
            if staff:
                # Staff side order detail
                return redirect(
                    "accounting:order_detail",
                    pk=target.pk,
                )
            else:
                # Customer portal order detail
                return redirect(
                    "portal:order_detail",
                    pk=target.pk,
                )

        # Fallback: unknown target type
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
