# sales/views.py
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    UpdateView,
    TemplateView,
)

from contacts.models import Contact
from .forms import SalesDocumentForm, SalesLineFormSet
from .models import SalesDocument
from .services import (
    convert_quotation_to_order,
    convert_order_to_delivery,
    convert_sales_document_to_invoice,
)


# ============================================================
# Base mixins
# ============================================================

class SalesStaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Restrict sales views to staff users.
    """

    raise_exception = True  # return 403 instead of redirect loop

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and user.is_staff

    @property
    def section(self) -> str:
        """
        Used by main layout (base.html) to highlight the 'Sales' app.
        """
        return "sales"


class BaseSalesDocumentMixin(SalesStaffRequiredMixin):
    """
    Common helpers for all SalesDocument views.

    Subclasses MUST set:
        - document_kind (SalesDocument.Kind.QUOTATION / ORDER / DELIVERY_NOTE)
    """

    model = SalesDocument
    form_class = SalesDocumentForm
    context_object_name = "document"
    document_kind: str | None = None

    # ---------- kind helpers ----------

    def get_document_kind(self) -> str:
        """
        Return current document kind; raise if not set.
        """
        if self.document_kind is None:
            raise ValueError("document_kind must be set on view subclass.")
        return self.document_kind

    def _kind_name(self) -> str:
        """
        Small helper to map kind to url name prefix.
        QUOTATION -> 'quotation', ORDER -> 'order', DELIVERY_NOTE -> 'delivery'
        """
        kind = self.get_document_kind()
        if kind == SalesDocument.Kind.QUOTATION:
            return "quotation"
        if kind == SalesDocument.Kind.ORDER:
            return "order"
        return "delivery"

    # ---------- queryset / context ----------

    def get_queryset(self):
        qs = (
            SalesDocument.objects
            .select_related("contact")
            .prefetch_related("lines__product")
            .filter(kind=self.get_document_kind())
        )
        # simple search by number or contact name (يُستخدم في الـ ListView فقط عمليًا)
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(number__icontains=q)
                | Q(contact__name__icontains=q)
                | Q(contact__company_name__icontains=q)
            )
        self.search_query = q
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # للـ base.html (تحديد التطبيق في النافبار العام)
        ctx["section"] = self.section

        # للـ base_sales.html (تحديد التاب الفرعي: عروض / أوامر / مذكرات)
        kind = self.get_document_kind()
        if kind == SalesDocument.Kind.QUOTATION:
            ctx["sales_section"] = "quotations"
            ctx["page_title"] = _("عروض الأسعار")
            ctx["kind_label"] = _("عرض سعر")
        elif kind == SalesDocument.Kind.ORDER:
            ctx["sales_section"] = "orders"
            ctx["page_title"] = _("طلبات البيع")
            ctx["kind_label"] = _("طلب بيع")
        else:
            ctx["sales_section"] = "deliveries"
            ctx["page_title"] = _("مذكرات التسليم")
            ctx["kind_label"] = _("مذكرة تسليم")

        ctx["q"] = getattr(self, "search_query", "")
        return ctx

    def get_success_url(self):
        """
        بعد الحفظ نرجع على صفحة التفاصيل حسب الـ kind.
        """
        return reverse(
            f"sales:{self._kind_name()}_detail",
            kwargs={"pk": self.object.pk},
        )


# ============================================================
# List Views
# ============================================================

class QuotationListView(BaseSalesDocumentMixin, ListView):
    template_name = "sales/quotation/list.html"
    paginate_by = 25
    document_kind = SalesDocument.Kind.QUOTATION
    # لا نحتاج أي context هنا؛ BaseSalesDocumentMixin يتكفل بـ sales_section


class SalesOrderListView(BaseSalesDocumentMixin, ListView):
    template_name = "sales/order/list.html"
    paginate_by = 25
    document_kind = SalesDocument.Kind.ORDER


class DeliveryNoteListView(BaseSalesDocumentMixin, ListView):
    template_name = "sales/delivery/list.html"
    paginate_by = 25
    document_kind = SalesDocument.Kind.DELIVERY_NOTE


# ============================================================
# Create Views
# ============================================================

class BaseSalesDocumentCreateView(BaseSalesDocumentMixin, CreateView):
    """
    Shared create view: handles header form + inline lines formset.
    """
    template_name = "sales/quotation/form.html"

    def get_initial(self):
        initial = super().get_initial()
        initial["currency"] = "OMR"
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        if self.request.method == "POST":
            ctx["line_formset"] = SalesLineFormSet(self.request.POST)
        else:
            ctx["line_formset"] = SalesLineFormSet()

        # page title override per kind
        kind = self.get_document_kind()
        if kind == SalesDocument.Kind.QUOTATION:
            ctx["form_title"] = _("إنشاء عرض سعر جديد")
            # kind_label تم ضبطه في BaseSalesDocumentMixin = "عرض سعر"
        elif kind == SalesDocument.Kind.ORDER:
            ctx["form_title"] = _("إنشاء طلب بيع جديد")
            # في حالة رغبتك، ممكن تغير kind_label هنا بشكل مخصص
        else:
            ctx["form_title"] = _("إنشاء مذكرة تسليم جديدة")

        return ctx

    def form_valid(self, form):
        ctx = self.get_context_data(form=form)
        line_formset = ctx.get("line_formset")

        if line_formset is None or not line_formset.is_valid():
            return self.render_to_response(ctx)

        with transaction.atomic():
            # set document kind before saving
            doc: SalesDocument = form.save(commit=False)
            doc.kind = self.get_document_kind()
            doc.save()

            line_formset.instance = doc
            line_formset.save()

            # إعادة حساب الإجماليات باستخدام منطق الموديل
            doc.recompute_totals()

        messages.success(self.request, _("تم حفظ مستند المبيعات بنجاح."))
        self.object = doc
        return redirect(self.get_success_url())


class QuotationCreateView(BaseSalesDocumentCreateView):
    document_kind = SalesDocument.Kind.QUOTATION


class SalesOrderCreateView(BaseSalesDocumentCreateView):
    document_kind = SalesDocument.Kind.ORDER


class DeliveryNoteCreateView(BaseSalesDocumentCreateView):
    document_kind = SalesDocument.Kind.DELIVERY_NOTE


# ============================================================
# Update Views
# ============================================================

class QuotationUpdateView(BaseSalesDocumentMixin, UpdateView):
    """
    تعديل عرض سعر مع نفس فورم الإنشاء (الهيدر + الـ line_formset).
    """
    template_name = "sales/quotation/form.html"
    document_kind = SalesDocument.Kind.QUOTATION

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        doc: SalesDocument = self.object

        if self.request.method == "POST":
            ctx["line_formset"] = SalesLineFormSet(
                self.request.POST,
                instance=doc,
            )
        else:
            ctx["line_formset"] = SalesLineFormSet(instance=doc)

        ctx["form_title"] = _("تعديل عرض السعر")
        # kind_label جهزه BaseSalesDocumentMixin = "عرض سعر"
        return ctx

    def form_valid(self, form):
        ctx = self.get_context_data(form=form)
        line_formset = ctx.get("line_formset")
        doc: SalesDocument = self.object

        if line_formset is None or not line_formset.is_valid():
            return self.render_to_response(ctx)

        with transaction.atomic():
            doc = form.save(commit=False)
            # نتأكد أنه بقي kind = QUOTATION
            doc.kind = SalesDocument.Kind.QUOTATION
            doc.save()

            line_formset.instance = doc
            line_formset.save()

            # إعادة حساب الإجماليات باستخدام منطق الموديل
            doc.recompute_totals()

        messages.success(self.request, _("تم تحديث عرض السعر بنجاح."))
        self.object = doc
        return redirect(self.get_success_url())


# ============================================================
# Detail Views
# ============================================================

class BaseSalesDocumentDetailView(BaseSalesDocumentMixin, DetailView):
    """
    Detail view مع نفس الـ context (section, sales_section, page_title, kind_label).
    """
    # يستخدم نفس الـ template_name من subclass
    pass


class QuotationDetailView(BaseSalesDocumentDetailView):
    template_name = "sales/quotation/detail.html"
    document_kind = SalesDocument.Kind.QUOTATION


class SalesOrderDetailView(BaseSalesDocumentDetailView):
    template_name = "sales/order/detail.html"
    document_kind = SalesDocument.Kind.ORDER


class DeliveryNoteDetailView(BaseSalesDocumentDetailView):
    template_name = "sales/delivery/detail.html"
    document_kind = SalesDocument.Kind.DELIVERY_NOTE


# ============================================================
# Workflow / conversion Views
# ============================================================

class QuotationToOrderView(SalesStaffRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        quotation = get_object_or_404(
            SalesDocument.objects.filter(kind=SalesDocument.Kind.QUOTATION),
            pk=pk,
        )

        try:
            order = convert_quotation_to_order(quotation)
        except ValueError:
            messages.error(request, _("هذا المستند ليس عرض سعر ولا يمكن تحويله."))
            return redirect("sales:quotation_detail", pk=quotation.pk)

        messages.success(
            request,
            _("تم تحويل عرض السعر إلى طلب بيع (المعرف: %(pk)s).")
            % {"pk": order.pk},
        )
        return redirect("sales:order_detail", pk=order.pk)


class OrderToDeliveryView(SalesStaffRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        order = get_object_or_404(
            SalesDocument.objects.filter(kind=SalesDocument.Kind.ORDER),
            pk=pk,
        )

        try:
            delivery = convert_order_to_delivery(order)
        except ValueError:
            messages.error(request, _("هذا المستند ليس طلب بيع ولا يمكن تحويله."))
            return redirect("sales:order_detail", pk=order.pk)

        messages.success(
            request,
            _("تم تحويل طلب البيع إلى مذكرة تسليم (المعرف: %(pk)s).")
            % {"pk": delivery.pk},
        )
        return redirect("sales:delivery_detail", pk=delivery.pk)


class BaseSalesToInvoiceView(SalesStaffRequiredMixin, View):
    """
    Base view لتحويل (طلب / مذكرة) إلى فاتورة.
    """
    allowed_kind: str | None = None

    def post(self, request, pk, *args, **kwargs):
        if self.allowed_kind is None:
            raise ValueError("allowed_kind must be set.")

        doc = get_object_or_404(
            SalesDocument.objects.filter(kind=self.allowed_kind),
            pk=pk,
        )

        try:
            invoice = convert_sales_document_to_invoice(doc)
        except RuntimeError:
            messages.error(
                request,
                _("لا يمكن إنشاء فاتورة: نموذج الفاتورة غير متوفر في نظام المحاسبة."),
            )
            if self.allowed_kind == SalesDocument.Kind.ORDER:
                return redirect("sales:order_detail", pk=doc.pk)
            else:
                return redirect("sales:delivery_detail", pk=doc.pk)
        except ValueError:
            messages.error(request, _("هذا المستند لا يمكن تحويله إلى فاتورة."))
            if self.allowed_kind == SalesDocument.Kind.ORDER:
                return redirect("sales:order_detail", pk=doc.pk)
            else:
                return redirect("sales:delivery_detail", pk=doc.pk)

        serial = getattr(invoice, "serial", None) or invoice.pk
        messages.success(
            request,
            _("تم إنشاء الفاتورة (رقم: %(serial)s) لهذا المستند.")
            % {"serial": serial},
        )

        # نحاول توجيه المستخدم لصفحة الفاتورة لو فيه get_absolute_url
        if hasattr(invoice, "get_absolute_url"):
            return redirect(invoice.get_absolute_url())

        # fallback: نرجع لتفاصيل المستند
        if self.allowed_kind == SalesDocument.Kind.ORDER:
            return redirect("sales:order_detail", pk=doc.pk)
        else:
            return redirect("sales:delivery_detail", pk=doc.pk)


class OrderToInvoiceView(BaseSalesToInvoiceView):
    allowed_kind = SalesDocument.Kind.ORDER


class DeliveryToInvoiceView(BaseSalesToInvoiceView):
    allowed_kind = SalesDocument.Kind.DELIVERY_NOTE


# ============================================================
# Dashboard
# ============================================================

class SalesDashboardView(SalesStaffRequiredMixin, TemplateView):
    template_name = "sales/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        docs = SalesDocument.objects.select_related("contact")

        quotations = docs.filter(kind=SalesDocument.Kind.QUOTATION)
        orders = docs.filter(kind=SalesDocument.Kind.ORDER)
        deliveries = docs.filter(kind=SalesDocument.Kind.DELIVERY_NOTE)

        # أرقام عامة
        ctx["quotation_count"] = quotations.count()
        ctx["order_count"] = orders.count()
        ctx["delivery_count"] = deliveries.count()
        ctx["total_sales_docs"] = docs.count()

        # إجمالي المبالغ لكل نوع
        def _sum(qs):
            return qs.aggregate(s=Sum("total_amount"))["s"] or Decimal("0.000")

        ctx["total_quotation_amount"] = _sum(quotations)
        ctx["total_order_amount"] = _sum(orders)
        ctx["total_delivery_amount"] = _sum(deliveries)
        ctx["total_sales_amount"] = _sum(docs)

        # حسب الحالة (workflow)
        ctx["draft_count"] = docs.filter(status=SalesDocument.Status.DRAFT).count()
        ctx["confirmed_count"] = docs.filter(status=SalesDocument.Status.CONFIRMED).count()
        ctx["delivered_count"] = docs.filter(status=SalesDocument.Status.DELIVERED).count()
        ctx["invoiced_count"] = docs.filter(status=SalesDocument.Status.INVOICED).count()

        # آخر المستندات
        ctx["recent_quotations"] = quotations.order_by("-date", "-id")[:5]
        ctx["recent_orders"] = orders.order_by("-date", "-id")[:5]
        ctx["recent_deliveries"] = deliveries.order_by("-date", "-id")[:5]

        # أفضل العملاء (حسب إجمالي المبيعات)
        top_customers = (
            docs.values("contact_id", "contact__name")
            .annotate(total=Sum("total_amount"))
            .filter(contact_id__isnull=False)
            .order_by("-total")[:5]
        )
        ctx["top_customers"] = top_customers

        # للـ base.html
        ctx["section"] = self.section
        # للـ base_sales.html (تحديد تبويب "لوحة المبيعات")
        ctx["sales_section"] = "dashboard"

        return ctx
