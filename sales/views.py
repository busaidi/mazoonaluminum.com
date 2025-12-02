# sales/views.py

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.http.response import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import (
    ListView,
    DetailView,
    CreateView,
    TemplateView,
    UpdateView,
)

from inventory.models import Product

from core.models import AuditLog
from core.services.audit import log_event

from .forms import SalesDocumentForm, DeliveryNoteForm, SalesLineFormSet
from .models import SalesDocument, DeliveryNote
from . import services
from .services import reopen_cancelled_sales_document


# ======================================================================
# الـ Base View لقسم المبيعات
# ======================================================================
class SalesBaseView(LoginRequiredMixin):
    """
    جميع الفيوهات في قسم المبيعات ترث من هذا الـ Base:
    - يضمن أن المستخدم مسجّل دخول (LoginRequiredMixin).
    - يضيف متغير sales_section في الـ context لاستخدامه في الـ navbar.
    """
    sales_section = None

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["sales_section"] = self.sales_section
        return ctx


# ======================================================================
# لوحة تحكم المبيعات (Dashboard)
# ======================================================================
class SalesDashboardView(SalesBaseView, TemplateView):
    """
    لوحة تحكم قسم المبيعات:
    - تعرض عدد وإجمالي عروض الأسعار وأوامر البيع.
    - تعرض مذكرات التسليم.
    - تعرض إحصائيات workflow (مسودة / مؤكد / مفوتر / مسلَّم).
    - تعرض آخر المستندات وأفضل العملاء.
    """
    template_name = "sales/dashboard.html"
    sales_section = "dashboard"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        def _q3(value):
            """
            دالة مساعدة لضبط الأرقام المالية:
            - لو القيمة None → تتحول إلى 0.
            - تُحوَّل إلى Decimal.
            - تُرجع القيمة بثلاث خانات عشرية ثابتة (0.000).
            """
            if value is None:
                value = Decimal("0")
            if not isinstance(value, Decimal):
                value = Decimal(str(value))
            return value.quantize(Decimal("0.000"))

        # QuerySets أساسية مع select_related لتقليل عدد الاستعلامات
        quotations_qs = SalesDocument.objects.quotations().select_related("contact")
        orders_qs = SalesDocument.objects.orders().select_related("contact")
        docs_qs = SalesDocument.objects.select_related("contact")
        deliveries_qs = DeliveryNote.objects.select_related("order", "order__contact")

        # إجماليات عامّة
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

        # حالات الـ workflow
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

        # آخر المستندات
        ctx["recent_quotations"] = quotations_qs.order_by("-date", "-id")[:5]
        ctx["recent_orders"] = orders_qs.order_by("-date", "-id")[:5]
        ctx["recent_deliveries"] = deliveries_qs.order_by("-date", "-id")[:5]

        # أفضل العملاء حسب إجمالي أوامر البيع المؤكدة
        raw_top_customers = (
            orders_qs.filter(status=SalesDocument.Status.CONFIRMED)
            .values("contact_id", "contact__name")
            .annotate(total=Sum("total_amount"))
            .order_by("-total")[:5]
        )

        top_customers = []
        for row in raw_top_customers:
            row = dict(row)
            row["total"] = _q3(row["total"])
            top_customers.append(row)

        ctx["top_customers"] = top_customers

        return ctx


# ======================================================================
# قائمة / إنشاء / تفاصيل / تعديل مستندات المبيعات
# ======================================================================
class SalesDocumentListView(SalesBaseView, ListView):
    """
    قائمة مستندات المبيعات مع دعم الفلترة:
    - حسب النوع: عرض / أمر.
    - حسب الفوترة: مفوتر / غير مفوتر (للأوامر فقط).
    - حسب اسم جهة الاتصال (بحث نصي).
    """
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

        # فلتر النوع: عرض / أمر
        if kind == "quotation":
            qs = qs.filter(kind=SalesDocument.Kind.QUOTATION)
        elif kind == "order":
            qs = qs.filter(kind=SalesDocument.Kind.ORDER)

        # فلتر الفوترة (للأوامر فقط)
        if invoiced in ("yes", "no"):
            # لو تم اختيار عروض فقط، نتجاهل فلتر الفوترة
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

        # البحث باسم جهة الاتصال
        if q:
            qs = qs.filter(contact__name__icontains=q)

        return qs

    def get_context_data(self, **kwargs):
        """
        إضافة قيم الفلاتر الحالية للـ context
        حتى نستخدمها في الفورم / واجهة البحث.
        """
        ctx = super().get_context_data(**kwargs)
        request = self.request

        ctx["current_kind"] = request.GET.get("kind", "")
        ctx["current_invoiced"] = request.GET.get("invoiced", "")
        ctx["current_q"] = request.GET.get("q", "")

        return ctx


class SalesDocumentCreateView(SalesBaseView, CreateView):
    """
    إنشاء مستند مبيعات جديد (عرض سعر):

    - يثبت النوع دائماً كعرض سعر (QUOTATION).
    - يثبت الحالة كمسودة (DRAFT).
    - يتعامل مع الهيدر + بنود المبيعات (SalesLineFormSet).
    - يضبط created_by / updated_by من المستخدم الحالي.
    - يعيد احتساب الإجماليات بعد حفظ البنود.
    - يسجل عملية الأوديت لإنشاء المستند.
    """
    model = SalesDocument
    form_class = SalesDocumentForm
    template_name = "sales/sales/form.html"
    sales_section = "sales_create"

    def get_context_data(self, **kwargs):
        """
        تجهيز الـ formset الخاص ببنود المبيعات مع النموذج الرئيسي.
        """
        context = super().get_context_data(**kwargs)

        if self.request.method == "POST":
            context["lines_formset"] = SalesLineFormSet(self.request.POST)
        else:
            context["lines_formset"] = SalesLineFormSet()

        return context

    def form_valid(self, form):
        """
        منطق الحفظ عند إنشاء المستند:
        - التحقق من صلاحية الـ formset.
        - ضبط kind/status.
        - ضبط created_by / updated_by.
        - حفظ الهيدر ثم البنود.
        - إعادة احتساب الإجماليات.
        - تسجيل الأوديت على الإنشاء.
        """
        context = self.get_context_data()
        lines_formset = context["lines_formset"]

        # التحقق من الـ formset قبل الحفظ
        if not lines_formset.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        # نوع المستند وحالته الافتراضية
        form.instance.kind = SalesDocument.Kind.QUOTATION
        form.instance.status = SalesDocument.Status.DRAFT

        # تعبئة created_by / updated_by من المستخدم الحالي
        user = self.request.user
        if user.is_authenticated:
            if hasattr(form.instance, "created_by") and not form.instance.pk:
                form.instance.created_by = user
            if hasattr(form.instance, "updated_by"):
                form.instance.updated_by = user

        # حفظ الهيدر أولاً
        self.object = form.save()

        # ضبط المستند في الـ formset وحفظ البنود
        lines_formset.instance = self.object
        lines_formset.save()

        # إعادة احتساب الإجمالي بعد حفظ البنود
        self.object.recompute_totals(save=True)

        # --- الأوديت: إنشاء مستند مبيعات ---
        log_event(
            action=AuditLog.Action.CREATE,
            message=_("تم إنشاء مستند المبيعات %(number)s") % {
                "number": self.object.display_number
            },
            actor=user if user.is_authenticated else None,
            target=self.object,
            extra={
                "kind": self.object.kind,
                "status": self.object.status,
                "contact_id": self.object.contact_id,
                "total_amount": str(self.object.total_amount),
            },
        )

        messages.success(self.request, _("تم إنشاء عرض السعر بنجاح."))
        return redirect(self.get_success_url())

    def get_success_url(self):
        """
        بعد الحفظ ننتقل إلى صفحة تفاصيل المستند.
        """
        return reverse("sales:sales_detail", args=[self.object.pk])


class SalesDocumentDetailView(SalesBaseView, DetailView):
    """
    عرض تفاصيل مستند المبيعات:
    - معلومات الهيدر.
    - بنود المبيعات.
    - مذكرات التسليم المرتبطة.
    """
    model = SalesDocument
    template_name = "sales/sales/detail.html"
    context_object_name = "document"
    sales_section = "sales_detail"

    def get_queryset(self):
        """
        تحسين الاستعلام باستخدام:
        - select_related لجهة الاتصال.
        - prefetch_related للبنود ومذكرات التسليم.
        """
        return (
            SalesDocument.objects
            .select_related("contact")
            .prefetch_related("lines", "delivery_notes")
        )


class SalesDocumentUpdateView(SalesBaseView, UpdateView):
    """
    تعديل مستند المبيعات:
    - تحديث بيانات الهيدر.
    - تعديل بنود المبيعات عبر formset.
    - ضبط updated_by بالمستخدم الحالي.
    - إعادة احتساب الإجماليات بعد الحفظ.
    - تسجيل الأوديت على التعديل مع حفظ القيم القديمة والجديدة.
    """
    model = SalesDocument
    form_class = SalesDocumentForm
    template_name = "sales/sales/form.html"
    sales_section = "sales_edit"

    def get_context_data(self, **kwargs):
        """
        تجهيز الـ formset للبنود، وإضافة document للـ context
        لاستخدامه في القالب.
        """
        context = super().get_context_data(**kwargs)

        # نضيف document للـ context لو القالب يحتاجه
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
        منطق التحديث:
        - التحقق من صلاحية formset.
        - حفظ قيم قديمة (kind/status/total_amount) للأوديت.
        - ضبط updated_by.
        - حفظ الهيدر.
        - حفظ البنود.
        - إعادة احتساب الإجماليات.
        - تسجيل الأوديت كتعديل.
        """
        context = self.get_context_data()
        lines_formset = context["lines_formset"]

        if not lines_formset.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        # حفظ القيم القديمة قبل التعديل (للأوديت)
        old_kind = self.object.kind
        old_status = self.object.status
        old_total_amount = self.object.total_amount

        # ضبط updated_by بالمستخدم الحالي
        user = self.request.user
        if user.is_authenticated and hasattr(form.instance, "updated_by"):
            form.instance.updated_by = user

        # حفظ الهيدر
        self.object = form.save()

        # حفظ البنود المرتبطة
        lines_formset.instance = self.object
        lines_formset.save()

        # إعادة احتساب الإجماليات
        self.object.recompute_totals(save=True)

        # --- الأوديت: تعديل مستند مبيعات ---
        log_event(
            action=AuditLog.Action.UPDATE,
            message=_("تم تحديث مستند المبيعات %(number)s") % {
                "number": self.object.display_number
            },
            actor=user if user.is_authenticated else None,
            target=self.object,
            extra={
                "old_kind": old_kind,
                "new_kind": self.object.kind,
                "old_status": old_status,
                "new_status": self.object.status,
                "old_total_amount": str(old_total_amount),
                "new_total_amount": str(self.object.total_amount),
            },
        )

        messages.success(self.request, _("تم تحديث المستند بنجاح."))
        return redirect(self.get_success_url())

    def get_success_url(self):
        """
        بعد التعديل نعود إلى صفحة التفاصيل.
        """
        return reverse("sales:sales_detail", args=[self.object.pk])


# ======================================================================
# تحويل عرض سعر → أمر بيع
# ======================================================================
class ConvertQuotationToOrderView(SalesBaseView, View):
    """
    فيو بسيط ينفّذ عملية تحويل عرض السعر إلى أمر بيع
    عبر service: confirm_quotation_to_order
    (والـ service بدوره يسجل الأوديت).
    """
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
# تعليم أمر البيع كمفوتر
# ======================================================================
class MarkOrderInvoicedView(SalesBaseView, View):
    """
    فيو مسؤول عن تعليم أمر البيع كمفوتر
    عبر service: mark_order_invoiced
    (والـ service يسجل الأوديت).
    """
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
# مذكرات التسليم (إنشاء / عرض / قائمة)
# ======================================================================
class DeliveryNoteCreateView(SalesBaseView, CreateView):
    """
    إنشاء مذكرة تسليم جديدة مرتبطة بأمر بيع:
    - يتم جلب أمر البيع من الـ URL (order_pk).
    - يتم ضبط created_by / updated_by بالمستخدم الحالي.
    - يتم تسجيل الأوديت عند إنشاء المذكرة.
    """
    model = DeliveryNote
    form_class = DeliveryNoteForm
    template_name = "sales/delivery/form.html"
    sales_section = "deliveries"

    def dispatch(self, request, *args, **kwargs):
        """
        جلب أمر البيع المستهدف من قاعدة البيانات قبل تنفيذ باقي المنطق.
        """
        self.order = get_object_or_404(
            SalesDocument.objects.orders(),
            pk=self.kwargs.get("order_pk"),
        )
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        """
        منطق الحفظ عند إنشاء مذكرة التسليم:
        - ربطها بأمر البيع.
        - تثبيت الحالة كمسودة.
        - ضبط created_by / updated_by.
        - تسجيل الأوديت بعد الحفظ.
        """
        form.instance.order = self.order
        form.instance.status = DeliveryNote.Status.DRAFT

        # تعبئة created_by / updated_by
        user = self.request.user
        if user.is_authenticated:
            if hasattr(form.instance, "created_by") and not form.instance.pk:
                form.instance.created_by = user
            if hasattr(form.instance, "updated_by"):
                form.instance.updated_by = user

        # حفظ المذكرة
        response = super().form_valid(form)

        # --- الأوديت: إنشاء مذكرة تسليم ---
        log_event(
            action=AuditLog.Action.CREATE,
            message=_("تم إنشاء مذكرة التسليم %(dn)s لأمر البيع %(order)s") % {
                "dn": self.object.display_number,
                "order": self.order.display_number,
            },
            actor=user if user.is_authenticated else None,
            target=self.object,
            extra={
                "order_id": self.order.id,
                "order_number": self.order.display_number,
                "status": self.object.status,
                "date": str(self.object.date),
            },
        )

        messages.success(self.request, _("تم إنشاء مذكرة التسليم بنجاح."))
        return response

    def get_success_url(self):
        """
        بعد الإنشاء ننتقل إلى صفحة تفاصيل مذكرة التسليم.
        """
        return reverse("sales:delivery_note_detail", args=[self.object.pk])

    def get_context_data(self, **kwargs):
        """
        تمرير أمر البيع للقالب لعرض معلوماته في الصفحة.
        """
        ctx = super().get_context_data(**kwargs)
        ctx["order"] = self.order
        return ctx


class DeliveryNoteDetailView(SalesBaseView, DetailView):
    """
    عرض تفاصيل مذكرة التسليم:
    - معلومات المذكرة.
    - أمر البيع المرتبط.
    - بنود التسليم.
    """
    model = DeliveryNote
    template_name = "sales/delivery/detail.html"
    context_object_name = "delivery"
    sales_section = "deliveries"

    def get_queryset(self):
        """
        تحسين الاستعلام باستخدام:
        - select_related لأمر البيع وجهة الاتصال.
        - prefetch_related لبنود التسليم.
        """
        return (
            DeliveryNote.objects
            .select_related("order", "order__contact")
            .prefetch_related("lines")
        )


class DeliveryNoteListView(SalesBaseView, ListView):
    """
    قائمة مذكرات التسليم مع ترقيم الصفحات.
    """
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


# ======================================================================
# إلغاء / إعادة لمسودة / إعادة فتح مستند مبيعات
# ======================================================================
class CancelSalesDocumentView(SalesBaseView, View):
    """
    إلغاء مستند مبيعات باستخدام service: cancel_sales_document
    (والـ service يسجل الأوديت).
    """
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
    إعادة مستند المبيعات إلى حالة المسودة
    باستخدام service: reset_sales_document_to_draft
    (والأوديت يتم من داخل الـ service).
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
    فيو وظيفي (Function-Based View) لإعادة فتح مستند ملغي
    إلى حالة المسودة كعرض سعر
    باستخدام service: reopen_cancelled_sales_document
    (والـ service يسجل الأوديت).
    """
    document = get_object_or_404(SalesDocument, pk=pk)

    # نسمح فقط بطلب POST (من زر في الفورم)
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


# ======================================================================
# API بسيطة لمعلومات وحدات القياس للمنتج (للـ JS في الفورم)
# ======================================================================
def product_uom_info(request, pk):
    """
    إرجاع معلومات وحدات القياس المرتبطة بالمنتج (كـ JSON):

    - الوحدة الأساسية.
    - الوحدة البديلة (إن وجدت).
    - عامل التحويل بينهما.
    - سعر البيع لكل وحدة (أساسية وبديلة).
    """
    product = get_object_or_404(Product, pk=pk)

    base_uom = product.base_uom
    alt_uom = product.alt_uom
    alt_factor = product.alt_factor

    # سعر البيع بالوحدة الأساسية
    base_price = product.get_price_for_uom(
        uom=base_uom,
        kind="sale",
    )

    # سعر البيع بالوحدة البديلة (إن وُجدت)
    alt_price = None
    if alt_uom and alt_factor:
        alt_price = product.get_price_for_uom(
            uom=alt_uom,
            kind="sale",
        )

    def uom_label(uom):
        """
        دالة مساعدة لعرض اسم الوحدة (أو نص فارغ إن لم تكن موجودة).
        """
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


# ======================================================================
# عرض نسخة قابلة للطباعة من مستند المبيعات
# ======================================================================
class SalesDocumentPrintView(SalesBaseView, DetailView):
    """
    عرض مخصص للطباعة لمستند المبيعات (عرض أو أمر):

    - يستخدم قالب بسيط ونظيف مهيّأ للطباعة.
    - لا يحتوي على أزرار أو عناصر تفاعلية غير ضرورية.
    """
    model = SalesDocument
    template_name = "sales/sales/print.html"
    context_object_name = "document"

    def get_queryset(self):
        """
        تحسين الاستعلام:
        - جلب جهة الاتصال المرتبطة.
        - جلب بنود المبيعات مع المنتجات.
        - جلب مذكرات التسليم.
        """
        return (
            SalesDocument.objects
            .select_related("contact")
            .prefetch_related("lines__product", "delivery_notes")
        )
