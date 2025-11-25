# payments/views.py

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Q, Sum
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
)

from .forms import PaymentForm, PaymentMethodForm
from .models import Payment, PaymentMethod

# لو هذه الخدمات موجودة عندك في core
try:
    from core.models import AuditLog
    from core.services.audit import log_event
    from core.services.notifications import create_notification
except Exception:  # pragma: no cover - في حال ما كانت جاهزة الآن
    AuditLog = None

    def log_event(*args, **kwargs):
        return None

    def create_notification(*args, **kwargs):
        return None

# لو عندك لوحة مرفقات مشتركة
try:
    from core.views.attachments import AttachmentPanelMixin
except Exception:  # pragma: no cover
    class AttachmentPanelMixin:
        """
        Dummy mixin if attachments system is not ready yet.
        يمكنك حذف هذا الـ try/except عندما يكون الميكسن جاهز.
        """
        pass


# ============================================================
# Base mixin for payments staff
# ============================================================

class PaymentsStaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Restrict payments views to staff users.
    يمكنك لاحقاً استبدالها بمكسن مشترك من core.
    """

    raise_exception = True  # 403 بدال لفة لا نهائية

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and user.is_staff

    @property
    def section(self) -> str:
        """
        تستخدم من القوالب لتحديد التبويب الرئيسي النشط.
        بما أن الدفعات مرتبطة بالمحاسبة، نخليها 'accounting'.
        """
        return "accounting"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault("section", self.section)
        return ctx


# ============================================================
# Payment list
# ============================================================

class PaymentListView(PaymentsStaffRequiredMixin, ListView):
    model = Payment
    template_name = "payments/payment/list.html"
    context_object_name = "payments"
    paginate_by = 25

    def get_queryset(self):
        qs = Payment.objects.select_related("contact", "method").order_by(
            "-date",
            "-id",
        )
        q = self.request.GET.get("q", "").strip()
        direction = self.request.GET.get("direction", "").strip()

        if q:
            qs = qs.filter(
                Q(number__icontains=q)
                | Q(contact__name__icontains=q)
                | Q(reference__icontains=q)
            )

        if direction in [choice[0] for choice in Payment.Direction.choices]:
            qs = qs.filter(direction=direction)

        self.search_query = q
        self.direction_filter = direction
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        total_in = (
            self.get_queryset()
            .filter(direction=Payment.Direction.IN)
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0.000")
        )
        total_out = (
            self.get_queryset()
            .filter(direction=Payment.Direction.OUT)
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0.000")
        )

        ctx["q"] = getattr(self, "search_query", "")
        ctx["direction_filter"] = getattr(self, "direction_filter", "")
        ctx["total_in"] = total_in
        ctx["total_out"] = total_out
        ctx["subsection"] = "payments"
        return ctx


# ============================================================
# Payment detail
# ============================================================

class PaymentDetailView(PaymentsStaffRequiredMixin, AttachmentPanelMixin, DetailView):
    model = Payment
    template_name = "payments/payment/detail.html"
    context_object_name = "payment"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "payments"
        # لو حبيت تعرض التخصيصات (PaymentAllocation) في القالب:
        ctx["allocations"] = self.object.allocations.select_related("invoice")
        return ctx


# ============================================================
# Payment create / update
# ============================================================

class PaymentCreateView(PaymentsStaffRequiredMixin, CreateView):
    model = Payment
    form_class = PaymentForm
    template_name = "payments/payment/form.html"
    success_url = reverse_lazy("payments:payment_list")

    def get_initial(self):
        initial = super().get_initial()
        contact_id = self.request.GET.get("contact")
        if contact_id:
            initial["contact"] = contact_id
        return initial


    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "payments"
        ctx["title"] = _("إنشاء دفعة جديدة")
        return ctx

    def form_valid(self, form):
        # تعبئة المستخدمين
        if self.request.user.is_authenticated:
            form.instance.created_by = self.request.user
            form.instance.updated_by = self.request.user

        response = super().form_valid(form)

        messages.success(self.request, _("تم إنشاء الدفعة بنجاح."))

        # تسجيل في الـ AuditLog لو متوفر
        try:
            log_event(
                event_type="payment_created",
                user=self.request.user,
                obj=self.object,
                extra={
                    "amount": str(self.object.amount),
                    "direction": self.object.direction,
                },
            )
        except Exception:
            pass

        # إشعار (اختياري)
        try:
            create_notification(
                user=self.request.user,
                title=_("دفعة جديدة"),
                message=_("تم إنشاء الدفعة رقم %(number)s.") % {
                    "number": self.object.number or self.object.pk
                },
                related_object=self.object,
            )
        except Exception:
            pass

        return response


class PaymentUpdateView(PaymentsStaffRequiredMixin, UpdateView):
    model = Payment
    form_class = PaymentForm
    template_name = "payments/payment/form.html"
    success_url = reverse_lazy("payments:payment_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "payments"
        ctx["title"] = _("تعديل الدفعة")
        return ctx

    def form_valid(self, form):
        if self.request.user.is_authenticated:
            form.instance.updated_by = self.request.user

        response = super().form_valid(form)

        messages.success(self.request, _("تم تحديث بيانات الدفعة بنجاح."))

        try:
            log_event(
                event_type="payment_updated",
                user=self.request.user,
                obj=self.object,
                extra={
                    "amount": str(self.object.amount),
                    "direction": self.object.direction,
                },
            )
        except Exception:
            pass

        return response


# ============================================================
# Payment methods CRUD
# ============================================================

class PaymentMethodListView(PaymentsStaffRequiredMixin, ListView):
    model = PaymentMethod
    template_name = "payments/method/list.html"
    context_object_name = "methods"
    paginate_by = 50

    def get_queryset(self):
        qs = PaymentMethod.objects.all().order_by("name")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(code__icontains=q)
            )
        self.search_query = q
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = getattr(self, "search_query", "")
        ctx["subsection"] = "payment_methods"
        return ctx


class PaymentMethodCreateView(PaymentsStaffRequiredMixin, CreateView):
    model = PaymentMethod
    form_class = PaymentMethodForm
    template_name = "payments/method/form.html"
    success_url = reverse_lazy("payments:method_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "payment_methods"
        ctx["title"] = _("إضافة طريقة دفع")
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, _("تم إضافة طريقة الدفع بنجاح."))
        return response


class PaymentMethodUpdateView(PaymentsStaffRequiredMixin, UpdateView):
    model = PaymentMethod
    form_class = PaymentMethodForm
    template_name = "payments/method/form.html"
    success_url = reverse_lazy("payments:method_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "payment_methods"
        ctx["title"] = _("تعديل طريقة الدفع")
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, _("تم تحديث طريقة الدفع بنجاح."))
        return response
