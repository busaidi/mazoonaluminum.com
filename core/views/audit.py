# core/views/audit.py

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.views.generic import ListView
from django.utils.translation import gettext as _

from core.models import AuditLog


class AuditLogListView(LoginRequiredMixin, ListView):
    """
    عرض سجلات الأوديت مع إمكانية الفلترة حسب المستند الهدف.

    الفلترة تتم عن طريق باراميترات GET:
    - target_model = "app_label.ModelName"  (مثال: "sales.SalesDocument")
    - target_id    = رقم الـ PK الخاص بالمستند

    مثال على رابط:
    /core/audit-log/?target_model=sales.SalesDocument&target_id=15
    """
    model = AuditLog
    template_name = "core/audit/audit_log_list.html"
    context_object_name = "logs"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            AuditLog.objects
            .select_related("actor", "target_content_type")
            .order_by("-created_at")
        )

        request = self.request
        target_model = request.GET.get("target_model") or ""
        target_id = request.GET.get("target_id") or ""

        # لو تم تمرير target_model و target_id نحاول نفلتر على المستند المحدد
        if target_model and target_id:
            try:
                app_label, model_name = target_model.split(".", 1)
                model_name = model_name.lower()
            except ValueError:
                # لو الفورمات غير صحيح نتجاهل الفلترة
                return qs

            try:
                ct = ContentType.objects.get(app_label=app_label, model=model_name)
            except ContentType.DoesNotExist:
                return qs

            qs = qs.filter(
                target_content_type=ct,
                target_object_id=str(target_id),
            )

        return qs

    def get_context_data(self, **kwargs):
        """
        نضيف معلومات عن الفلترة الحالية للـ context
        حتى نعرضها في الواجهة (عنوان، وصف...).
        """
        ctx = super().get_context_data(**kwargs)
        request = self.request

        ctx["target_model"] = request.GET.get("target_model") or ""
        ctx["target_id"] = request.GET.get("target_id") or ""

        # نص بسيط في الهيدر إذا كان الفلتر لمستند معيّن
        if ctx["target_model"] and ctx["target_id"]:
            ctx["page_title"] = _("سجل التدقيق للمستند %(target)s رقم %(pk)s") % {
                "target": ctx["target_model"],
                "pk": ctx["target_id"],
            }
        else:
            ctx["page_title"] = _("جميع سجلات التدقيق")

        return ctx
