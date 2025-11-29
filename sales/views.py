# sales/views.py
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.db.models import Sum, Q
from django.utils import timezone
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import (
    ListView, DetailView, CreateView, TemplateView, UpdateView
)

from .forms import SalesDocumentForm, DeliveryNoteForm
from .models import SalesDocument, DeliveryNote
from . import services


# ======================================================================
# Base View
# ======================================================================
class SalesBaseView(LoginRequiredMixin):
    sales_section = None

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["sales_section"] = self.sales_section
        return ctx


# ======================================================================
# Dashboard
# ======================================================================
class SalesDashboardView(SalesBaseView, TemplateView):
    template_name = "sales/dashboard.html"
    sales_section = "dashboard"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        quotations_qs = SalesDocument.objects.quotations().select_related("contact")
        orders_qs = SalesDocument.objects.orders().select_related("contact")
        docs_qs = SalesDocument.objects.select_related("contact")
        deliveries_qs = DeliveryNote.objects.select_related("order", "order__contact")

        # إجماليات
        ctx["total_sales_docs"] = docs_qs.count()
        ctx["total_sales_amount"] = docs_qs.aggregate(s=Sum("total_amount"))["s"] or 0

        # عروض الأسعار
        ctx["quotation_count"] = quotations_qs.count()
        ctx["total_quotation_amount"] = quotations_qs.aggregate(s=Sum("total_amount"))["s"] or 0

        # أوامر البيع
        ctx["order_count"] = orders_qs.count()
        ctx["total_order_amount"] = orders_qs.aggregate(s=Sum("total_amount"))["s"] or 0

        # مذكرات التسليم
        ctx["delivery_count"] = deliveries_qs.count()
        ctx["total_delivery_amount"] = deliveries_qs.aggregate(s=Sum("order__total_amount"))["s"] or 0

        # workflow
        ctx["draft_count"] = docs_qs.filter(status=SalesDocument.Status.DRAFT).count()
        ctx["confirmed_count"] = docs_qs.filter(status=SalesDocument.Status.CONFIRMED).count()
        ctx["invoiced_count"] = docs_qs.filter(is_invoiced=True).count()
        ctx["delivered_count"] = deliveries_qs.filter(status=DeliveryNote.Status.CONFIRMED).count()

        # recent
        ctx["recent_quotations"] = quotations_qs.order_by("-date", "-id")[:5]
        ctx["recent_orders"] = orders_qs.order_by("-date", "-id")[:5]
        ctx["recent_deliveries"] = deliveries_qs.order_by("-date", "-id")[:5]

        # أفضل العملاء
        ctx["top_customers"] = (
            orders_qs.filter(status=SalesDocument.Status.CONFIRMED)
            .values("contact_id", "contact__name")
            .annotate(total=Sum("total_amount"))
            .order_by("-total")[:5]
        )

        return ctx


# ======================================================================
# Unified CRUD (list / create / detail / update)
# ======================================================================
class SalesDocumentListView(SalesBaseView, ListView):
    model = SalesDocument
    template_name = "sales/sales/list.html"
    context_object_name = "documents"
    paginate_by = 25
    sales_section = "sales_list"

    def get_queryset(self):
        qs = (
            SalesDocument.objects
            .select_related("contact")
            .order_by("-date", "-id")
        )

        request = self.request
        kind = request.GET.get("kind") or ""
        invoiced = request.GET.get("invoiced") or ""
        q = request.GET.get("q") or ""

        # -----------------------------
        # فلتر النوع: عرض / أمر
        # -----------------------------
        if kind == "quotation":
            qs = qs.filter(kind=SalesDocument.Kind.QUOTATION)
        elif kind == "order":
            qs = qs.filter(kind=SalesDocument.Kind.ORDER)

        # -----------------------------
        # فلتر الفوترة (للأوامر فقط)
        # -----------------------------
        if invoiced in ("yes", "no"):
            # لو المستخدم اختار عروض فقط، نتجاهل فلتر الفوترة
            if kind != "quotation":
                if invoiced == "yes":
                    qs = qs.filter(
                        kind=SalesDocument.Kind.ORDER,
                        is_invoiced=True,
                    )
                elif invoiced == "no":
                    qs = qs.filter(
                        kind=SalesDocument.Kind.ORDER,
                        is_invoiced=False,
                    )

        # -----------------------------
        # البحث بالعميل
        # -----------------------------
        if q:
            qs = qs.filter(contact__name__icontains=q)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        request = self.request

        ctx["current_kind"] = request.GET.get("kind", "")
        ctx["current_invoiced"] = request.GET.get("invoiced", "")
        ctx["current_q"] = request.GET.get("q", "")

        return ctx


class SalesDocumentCreateView(SalesBaseView, CreateView):
    model = SalesDocument
    form_class = SalesDocumentForm
    template_name = "sales/sales/form.html"
    sales_section = "sales_create"

    def form_valid(self, form):
        """
        عند إنشاء مستند جديد:
        - نجبر النوع يكون QUOTATION دائماً (عرض سعر).
        - نثبت الحالة كمسودة.
        - نعيد احتساب الإجماليات بعد الحفظ.
        """

        # نجبر النوع يكون عرض سعر دائماً، ولا نعتمد على أي قيمة من الفورم
        form.instance.kind = SalesDocument.Kind.QUOTATION

        # الحالة الافتراضية للمستند الجديد
        form.instance.status = SalesDocument.Status.DRAFT

        response = super().form_valid(form)

        # إعادة احتساب الإجماليات بعد الحفظ
        self.object.recompute_totals(save=True)

        messages.success(self.request, _("تم إنشاء عرض السعر بنجاح."))
        return response

    def get_success_url(self):
        return reverse("sales:sales_detail", args=[self.object.pk])



class SalesDocumentDetailView(SalesBaseView, DetailView):
    model = SalesDocument
    template_name = "sales/sales/detail.html"
    context_object_name = "document"
    sales_section = "sales_detail"

    def get_queryset(self):
        return (
            SalesDocument.objects
            .select_related("contact")
            .prefetch_related("lines", "delivery_notes")
        )


class SalesDocumentUpdateView(SalesBaseView, UpdateView):
    model = SalesDocument
    form_class = SalesDocumentForm
    template_name = "sales/sales/form.html"
    sales_section = "sales_edit"

    def form_valid(self, form):
        response = super().form_valid(form)
        self.object.recompute_totals(save=True)
        messages.success(self.request, _("تم تحديث المستند بنجاح."))
        return response

    def get_success_url(self):
        return reverse("sales:sales_detail", args=[self.object.pk])


# ======================================================================
# Convert Quotation → Order
# ======================================================================
class ConvertQuotationToOrderView(SalesBaseView, View):
    sales_section = "sales_detail"

    def post(self, request, pk):
        document = get_object_or_404(SalesDocument.objects.quotations(), pk=pk)

        try:
            services.confirm_quotation_to_order(document)
        except Exception as e:
            messages.error(request, str(e))
            return redirect(document.get_absolute_url())

        messages.success(request, _("تم تحويل عرض السعر إلى أمر بيع بنجاح."))
        return redirect(document.get_absolute_url())


# ======================================================================
# Mark Order as Invoiced
# ======================================================================
class MarkOrderInvoicedView(SalesBaseView, View):
    sales_section = "sales_detail"

    def post(self, request, pk):
        order = get_object_or_404(SalesDocument.objects.orders(), pk=pk)

        try:
            services.mark_order_invoiced(order)
        except Exception as e:
            messages.error(request, str(e))
            return redirect(order.get_absolute_url())

        messages.success(request, _("تم تعليم أمر البيع كمفوتر."))
        return redirect(order.get_absolute_url())


# ======================================================================
# Delivery Notes
# ======================================================================
class DeliveryNoteCreateView(SalesBaseView, CreateView):
    model = DeliveryNote
    form_class = DeliveryNoteForm
    template_name = "sales/delivery/form.html"
    sales_section = "deliveries"

    def dispatch(self, request, *args, **kwargs):
        self.order = get_object_or_404(
            SalesDocument.objects.orders(),
            pk=self.kwargs.get("order_pk"),
        )
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.order = self.order
        form.instance.status = DeliveryNote.Status.DRAFT
        response = super().form_valid(form)
        messages.success(self.request, _("تم إنشاء مذكرة التسليم بنجاح."))
        return response

    def get_success_url(self):
        return reverse("sales:delivery_note_detail", args=[self.object.pk])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["order"] = self.order
        return ctx


class DeliveryNoteDetailView(SalesBaseView, DetailView):
    model = DeliveryNote
    template_name = "sales/delivery/detail.html"
    context_object_name = "delivery"
    sales_section = "deliveries"

    def get_queryset(self):
        return (
            DeliveryNote.objects
            .select_related("order", "order__contact")
            .prefetch_related("lines")
        )


class DeliveryNoteListView(SalesBaseView, ListView):
    model = DeliveryNote
    template_name = "sales/delivery/list.html"
    context_object_name = "deliveries"
    paginate_by = 25
    sales_section = "deliveries"

    def get_queryset(self):
        return (
            DeliveryNote.objects
            .select_related("order", "order__contact")
            .order_by("-date", "-id")
        )


class CancelSalesDocumentView(SalesBaseView, View):
    sales_section = "sales_detail"

    def post(self, request, pk):
        document = get_object_or_404(SalesDocument, pk=pk)

        try:
            services.cancel_sales_document(document)
        except Exception as e:
            messages.error(request, str(e))
            return redirect(document.get_absolute_url())

        messages.success(request, _("تم إلغاء المستند بنجاح."))
        return redirect(document.get_absolute_url())


class ResetSalesDocumentToDraftView(SalesBaseView, View):
    """
    إعادة مستند المبيعات إلى حالة المسودة.
    """
    sales_section = "sales_detail"

    def post(self, request, pk):
        document = get_object_or_404(SalesDocument, pk=pk)

        try:
            services.reset_sales_document_to_draft(document)
        except Exception as e:
            messages.error(request, str(e))
            return redirect(document.get_absolute_url())

        messages.success(request, _("تمت إعادة المستند إلى حالة المسودة بنجاح."))
        return redirect(document.get_absolute_url())