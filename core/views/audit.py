# core/views.py

from datetime import timedelta
from urllib.parse import urlencode

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.generic import ListView

from core.models import AuditLog


class AuditLogListView(LoginRequiredMixin, ListView):
    """
    عرض قائمة سجلات التدقيق (Audit Log):

    يدعم الفلترة حسب:
    - action
    - actor (نص حر)
    - q (بحث في الرسالة)
    - target_model + target_id
    - date_from / date_to
    - section: تبويب عام / مبيعات / حسابات
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

        # لو عندك soft delete
        if hasattr(AuditLog, "is_deleted"):
            qs = qs.filter(is_deleted=False)

        request = self.request

        # قيم الفلتر من الـ GET
        action = request.GET.get("action") or ""
        actor_query = request.GET.get("actor") or ""
        q = request.GET.get("q") or ""
        target_model = request.GET.get("target_model") or ""
        target_id = request.GET.get("target_id") or ""
        date_from = request.GET.get("date_from") or ""
        date_to = request.GET.get("date_to") or ""
        section = request.GET.get("section") or ""  # "", "sales", "accounting"

        # 1) section tabs: عام / مبيعات / حسابات
        if section == "sales":
            qs = qs.filter(target_content_type__app_label="sales")
        elif section == "accounting":
            qs = qs.filter(target_content_type__app_label="accounting")

        # 2) نوع العملية
        if action:
            qs = qs.filter(action=action)

        # 3) المستخدم
        if actor_query:
            qs = qs.filter(
                Q(actor__username__icontains=actor_query)
                | Q(actor__first_name__icontains=actor_query)
                | Q(actor__last_name__icontains=actor_query)
            )

        # 4) نص الرسالة
        if q:
            qs = qs.filter(message__icontains=q)

        # 5) نوع الهدف
        if target_model:
            try:
                app_label, model_name = target_model.split(".")
                ct = ContentType.objects.get(
                    app_label=app_label,
                    model=model_name.lower(),
                )
                qs = qs.filter(target_content_type=ct)
            except (ValueError, ContentType.DoesNotExist):
                pass

        # 6) رقم الهدف
        if target_id:
            qs = qs.filter(target_object_id=str(target_id))

        # 7) نطاق التاريخ
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        request = self.request

        current_filters = {
            "action": request.GET.get("action", ""),
            "actor": request.GET.get("actor", ""),
            "q": request.GET.get("q", ""),
            "target_model": request.GET.get("target_model", ""),
            "target_id": request.GET.get("target_id", ""),
            "date_from": request.GET.get("date_from", ""),
            "date_to": request.GET.get("date_to", ""),
            "section": request.GET.get("section", ""),
        }

        ctx["actions"] = AuditLog.Action.choices
        ctx["current_filters"] = current_filters
        ctx["current_section"] = current_filters["section"]

        # ---------------- base_query لعلامات الترقيم والفلترة ----------------
        base_params = {}
        for key, value in request.GET.items():
            if key == "page":
                continue
            if value in ("", None):
                continue
            base_params[key] = value

        ctx["base_query"] = urlencode(base_params)

        # ---------------- Presets حسب المستند ----------------
        target_model = current_filters["target_model"]
        target_id = current_filters["target_id"]

        # هذا المستند فقط
        if target_model and target_id:
            params_doc = {
                "target_model": target_model,
                "target_id": target_id,
            }
            ctx["preset_this_document_query"] = urlencode(params_doc)
        else:
            ctx["preset_this_document_query"] = ""

        # كل مستندات المبيعات
        params_sales = {
            "target_model": "sales.SalesDocument",
        }
        ctx["preset_sales_documents_query"] = urlencode(params_sales)

        # ---------------- Presets زمنية: آخر ٧ أيام / اليوم / آخر ٣٠ يوم ----------------
        today = timezone.localdate()
        seven_days_ago = today - timedelta(days=7)
        thirty_days_ago = today - timedelta(days=30)

        # آخر ٧ أيام (نحافظ على بقية الفلاتر الحالية)
        params_last7 = base_params.copy()
        params_last7["date_from"] = seven_days_ago.isoformat()
        params_last7["date_to"] = today.isoformat()
        ctx["preset_last7_query"] = urlencode(params_last7)

        # اليوم فقط
        params_today = base_params.copy()
        params_today["date_from"] = today.isoformat()
        params_today["date_to"] = today.isoformat()
        ctx["preset_today_query"] = urlencode(params_today)

        # آخر ٣٠ يوم
        params_last30 = base_params.copy()
        params_last30["date_from"] = thirty_days_ago.isoformat()
        params_last30["date_to"] = today.isoformat()
        ctx["preset_last30_query"] = urlencode(params_last30)

        # ---------------- Tabs: عام / مبيعات / حسابات ----------------
        # تبويب "عام" = بدون section + نفضي target_model/target_id
        params_all = {
            k: v
            for k, v in base_params.items()
            if k not in ("section", "target_model", "target_id")
        }
        ctx["tab_all_query"] = urlencode(params_all)

        # تبويب "مبيعات" = section=sales فقط (بداية نظيفة)
        ctx["tab_sales_query"] = urlencode({"section": "sales"})

        # تبويب "حسابات" = section=accounting فقط
        ctx["tab_accounting_query"] = urlencode({"section": "accounting"})

        return ctx
