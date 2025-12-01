# sales/views.py

from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http.response import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.db.models import Sum
from django.utils import timezone
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import (
    ListView, DetailView, CreateView, TemplateView, UpdateView
)

from inventory.models import Product
# من الأفضل عدم استخدام UserStampedMixin هنا لأن عندنا form_valid مخصص
# from core.mixins import UserStampedMixin

from .forms import SalesDocumentForm, DeliveryNoteForm, SalesLineFormSet
from .models import SalesDocument, DeliveryNote
from . import services
from .services import reopen_cancelled_sales_document


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
from decimal import Decimal
from django.db.models import Sum

class SalesDashboardView(SalesBaseView, TemplateView):
    template_name = "sales/dashboard.html"
    sales_section = "dashboard"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        def _q3(value):
            """
            Helper بسيط يضمن:
            - لو القيمة None → تصبح 0
            - يرجع Decimal بثلاث خانات عشرية ثابتة
            """
            if value is None:
                value = Decimal("0")
            # نتأكد إنها Decimal
            if not isinstance(value, Decimal):
                value = Decimal(str(value))
            return value.quantize(Decimal("0.000"))

        quotations_qs = SalesDocument.objects.quotations().select_related("contact")
        orders_qs = SalesDocument.objects.orders().select_related("contact")
        docs_qs = SalesDocument.objects.select_related("contact")
        deliveries_qs = DeliveryNote.objects.select_related("order", "order__contact")

        # إجماليات
        ctx["total_sales_docs"] = docs_qs.count()
        ctx["total_sales_amount"] = _q3(
            docs_qs.aggregate(s=Sum("total_amount"))["s"]
        )

        # عروض الأسعار
        ctx["quotation_count"] = quotations_qs.count()
        ctx["total_quotation_amount"] = _q3(
            quotations_qs.aggregate(s=Sum("total_amount"))["s"]
        )

        # أوامر البيع
        ctx["order_count"] = orders_qs.count()
        ctx["total_order_amount"] = _q3(
            orders_qs.aggregate(s=Sum("total_amount"))["s"]
        )

        # مذكرات التسليم
        ctx["delivery_count"] = deliveries_qs.count()
        ctx["total_delivery_amount"] = _q3(
            deliveries_qs.aggregate(s=Sum("order__total_amount"))["s"]
        )

        # workflow
        ctx["draft_count"] = docs_qs.filter(
            status=SalesDocument.Status.DRAFT
        ).count()
        ctx["confirmed_count"] = docs_qs.filter(
            status=SalesDocument.Status.CONFIRMED
        ).count()
        ctx["invoiced_count"] = docs_qs.filter(
            is_invoiced=True
        ).count()
        ctx["delivered_count"] = deliveries_qs.filter(
            status=DeliveryNote.Status.CONFIRMED
        ).count()

        # recent
        ctx["recent_quotations"] = quotations_qs.order_by("-date", "-id")[:5]
        ctx["recent_orders"] = orders_qs.order_by("-date", "-id")[:5]
        ctx["recent_deliveries"] = deliveries_qs.order_by("-date", "-id")[:5]

        # أفضل العملاء
        raw_top_customers = (
            orders_qs.filter(status=SalesDocument.Status.CONFIRMED)
            .values("contact_id", "contact__name")
            .annotate(total=Sum("total_amount"))
            .order_by("-total")[:5]
        )

        # نطبّق _q3 على total لكل عميل
        top_customers = []
        for row in raw_top_customers:
            row = dict(row)  # نحوله dict عادي لو حاب تعدله بحرية
            row["total"] = _q3(row["total"])
            top_customers.append(row)

        ctx["top_customers"] = top_customers

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
    """
    إنشاء مستند مبيعات:
    - يثبت kind = QUOTATION و status = DRAFT.
    - يتعامل مع الـ header + lines معًا.
    - يضبط created_by / updated_by يدويًا من request.user.
    """
    model = SalesDocument
    form_class = SalesDocumentForm
    template_name = "sales/sales/form.html"
    sales_section = "sales_create"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.method == "POST":
            context["lines_formset"] = SalesLineFormSet(self.request.POST)
        else:
            context["lines_formset"] = SalesLineFormSet()

        return context

    def form_valid(self, form):
        """
        عند إنشاء مستند جديد:
        - نجبر النوع يكون QUOTATION دائماً (عرض سعر).
        - نثبت الحالة كمسودة.
        - نضبط created_by / updated_by.
        - نحفظ البنود من الـ inline formset.
        - نعيد احتساب الإجماليات بعد الحفظ.
        """

        context = self.get_context_data()
        lines_formset = context["lines_formset"]

        # Validate formset first
        if not lines_formset.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        # نوع المستند والحالة
        form.instance.kind = SalesDocument.Kind.QUOTATION
        form.instance.status = SalesDocument.Status.DRAFT

        # تعبئة created_by / updated_by
        user = self.request.user
        if user.is_authenticated:
            if hasattr(form.instance, "created_by") and not form.instance.pk:
                form.instance.created_by = user
            if hasattr(form.instance, "updated_by"):
                form.instance.updated_by = user

        # حفظ الهيدر
        self.object = form.save()

        # حفظ البنود
        lines_formset.instance = self.object
        lines_formset.save()

        # إعادة احتساب الإجماليات بعد حفظ البنود
        self.object.recompute_totals(save=True)

        messages.success(self.request, _("تم إنشاء عرض السعر بنجاح."))
        return redirect(self.get_success_url())

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
    """
    تحديث مستند المبيعات:
    - يضبط updated_by يدويًا.
    - يحدّث الهيدر + البنود + الإجماليات.
    """
    model = SalesDocument
    form_class = SalesDocumentForm
    template_name = "sales/sales/form.html"
    sales_section = "sales_edit"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # علشان التمبلت يستخدم {{ document }}
        context.setdefault("document", self.object)

        if self.request.method == "POST":
            context["lines_formset"] = SalesLineFormSet(
                self.request.POST,
                instance=self.object,
            )
        else:
            context["lines_formset"] = SalesLineFormSet(
                instance=self.object,
            )

        return context

    def form_valid(self, form):
        """
        تحديث مستند المبيعات + تحديث بنود المبيعات (inline formset).
        """
        context = self.get_context_data()
        lines_formset = context["lines_formset"]

        if not lines_formset.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        # updated_by
        user = self.request.user
        if user.is_authenticated and hasattr(form.instance, "updated_by"):
            form.instance.updated_by = user

        # حفظ الهيدر
        self.object = form.save()

        # حفظ البنود المرتبطة
        lines_formset.instance = self.object
        lines_formset.save()

        # إعادة احتساب الإجماليات بعد تعديل البنود
        self.object.recompute_totals(save=True)

        messages.success(self.request, _("تم تحديث المستند بنجاح."))
        return redirect(self.get_success_url())

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
            services.confirm_quotation_to_order(document, user=request.user)
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
            services.mark_order_invoiced(order, user=request.user)
        except Exception as e:
            messages.error(request, str(e))
            return redirect(order.get_absolute_url())

        messages.success(request, _("تم تعليم أمر البيع كمفوتر."))
        return redirect(order.get_absolute_url())


# ======================================================================
# Delivery Notes
# ======================================================================
class DeliveryNoteCreateView(SalesBaseView, CreateView):
    """
    إنشاء مذكرة تسليم:
    - يضبط created_by / updated_by لو الموديل يرث UserStampedModel.
    """
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

        # تعبئة created_by / updated_by
        user = self.request.user
        if user.is_authenticated:
            if hasattr(form.instance, "created_by") and not form.instance.pk:
                form.instance.created_by = user
            if hasattr(form.instance, "updated_by"):
                form.instance.updated_by = user

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
            services.cancel_sales_document(document, user=request.user)
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
            services.reset_sales_document_to_draft(document, user=request.user)
        except Exception as e:
            messages.error(request, str(e))
            return redirect(document.get_absolute_url())

        messages.success(request, _("تمت إعادة المستند إلى حالة المسودة بنجاح."))

        return redirect(document.get_absolute_url())


@login_required
def sales_reopen_view(request, pk):
    """
    إعادة فتح مستند ملغي وإرجاعه إلى حالة المسودة (Draft + Quotation)
    باستخدام service: reopen_cancelled_sales_document
    """
    document = get_object_or_404(SalesDocument, pk=pk)

    # نسمح فقط عبر POST (عشان زر الفورم في القالب)
    if request.method != "POST":
        return redirect("sales:sales_detail", pk=document.pk)

    try:
        reopen_cancelled_sales_document(document, user=request.user)
        messages.success(
            request,
            _("تمت إعادة فتح المستند وإرجاعه إلى حالة المسودة (عرض سعر)."),
        )
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    except Exception:
        messages.error(
            request,
            _("حدث خطأ غير متوقع أثناء إعادة فتح المستند."),
        )

    return redirect("sales:sales_detail", pk=document.pk)


def product_uom_info(request, pk):
    """
    ترجع معلومات وحدات القياس المرتبطة بالمنتج:
    - الوحدة الأساسية
    - الوحدة البديلة (إن وجدت)
    - عامل التحويل بينهما
    - سعر البيع لكل وحدة (أساسية وبديلة)
    """
    product = get_object_or_404(Product, pk=pk)

    base_uom = product.base_uom
    alt_uom = product.alt_uom
    alt_factor = product.alt_factor

    base_price = product.get_price_for_uom(
        uom=base_uom,
        kind="sale",
    )

    alt_price = None
    if alt_uom and alt_factor:
        alt_price = product.get_price_for_uom(
            uom=alt_uom,
            kind="sale",
        )

    def uom_label(uom):
        if not uom:
            return ""
        return getattr(uom, "name", str(uom))

    data = {
        "base_uom": uom_label(base_uom),
        "alt_uom": uom_label(alt_uom),
        "has_alt": bool(alt_uom),
        "alt_factor": str(alt_factor) if alt_uom and alt_factor else "",
        "base_price": str(base_price) if base_price is not None else "",
        "alt_price": str(alt_price) if alt_price is not None else "",
    }
    return JsonResponse(data)


class SalesDocumentPrintView(SalesBaseView, DetailView):
    """
    Printable read-only view for a sales document (quotation or order).
    Uses a clean template optimized for printing.
    """
    model = SalesDocument
    template_name = "sales/sales/print.html"
    context_object_name = "document"

    def get_queryset(self):
        return (
            SalesDocument.objects
            .select_related("contact")
            .prefetch_related("lines__product", "delivery_notes")
        )
