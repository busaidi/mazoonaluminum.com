# sales/views.py

from decimal import Decimal
from urllib.parse import urlencode

from django.db import transaction
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

from core.models import AuditLog, Notification
from core.services.audit import log_event
from core.services.notifications import create_notification

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
    Create new SalesDocument (Quotation):

    - Force kind = QUOTATION, status = DRAFT.
    - Handle header + lines (SalesLineFormSet).
    - Set created_by / updated_by from current user.
    - Recompute totals after saving lines.
    - Log audit event.
    - Create notification for current user.
    """
    model = SalesDocument
    form_class = SalesDocumentForm
    template_name = "sales/sales/form.html"
    sales_section = "sales_create"

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------
    def _get_lines_formset(self):
        if self.request.method == "POST":
            return SalesLineFormSet(self.request.POST)
        return SalesLineFormSet()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("lines_formset", self._get_lines_formset())
        return context

    def _set_header_defaults(self, form):
        """Force default kind/status and user fields on header."""
        form.instance.kind = SalesDocument.Kind.QUOTATION
        form.instance.status = SalesDocument.Status.DRAFT

        user = self.request.user
        if user.is_authenticated:
            if hasattr(form.instance, "created_by") and not form.instance.pk:
                form.instance.created_by = user
            if hasattr(form.instance, "updated_by"):
                form.instance.updated_by = user

    def _save_lines(self, lines_formset):
        """
        Save lines (create/update/delete) and handle UoM selection.
        Assumes self.object (header) is already saved.
        """
        # delete removed lines
        for obj in getattr(lines_formset, "deleted_objects", []):
            obj.delete()

        for line_form in lines_formset.forms:
            # skip empty/extra/deleted forms
            if not getattr(line_form, "cleaned_data", None):
                continue
            if not line_form.cleaned_data:
                continue
            if line_form.cleaned_data.get("DELETE"):
                continue

            line = line_form.save(commit=False)

            product = line_form.cleaned_data.get("product")
            if not product:
                # no product → skip line
                continue

            # UoM handling (base / alt) if model has uom field
            if hasattr(line, "uom"):
                uom_kind = self.request.POST.get(f"{line_form.prefix}-uom_kind")  # "base" | "alt" | ""
                selected_uom = None

                if uom_kind == "base" and getattr(product, "base_uom", None):
                    selected_uom = product.base_uom
                elif uom_kind == "alt" and getattr(product, "alt_uom", None):
                    selected_uom = product.alt_uom
                elif getattr(product, "base_uom", None):
                    # fallback
                    selected_uom = product.base_uom

                if selected_uom is not None:
                    line.uom = selected_uom

            # make sure line points to header
            if hasattr(line, "document") and line.document_id is None:
                line.document = self.object

            line.save()

    def _log_audit(self):
        """Create audit log for document creation."""
        user = self.request.user
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

    def _notify_user(self):
        """Create notification for current user."""
        user = self.request.user
        if not user.is_authenticated:
            return

        create_notification(
            recipient=user,
            verb=_("تم إنشاء مستند المبيعات %(number)s") % {
                "number": self.object.display_number
            },
            target=self.object,
            level=Notification.Levels.SUCCESS,
            url=reverse("sales:sales_detail", args=[self.object.pk]),
        )

    # --------------------------------------------------
    # Main save logic
    # --------------------------------------------------
    @transaction.atomic
    def form_valid(self, form):
        context = self.get_context_data(form=form)
        lines_formset = context["lines_formset"]

        if not lines_formset.is_valid():
            # return page with both form + formset errors
            return self.render_to_response(context)

        # 1) header defaults + save header
        self._set_header_defaults(form)
        self.object = form.save()

        # 2) bind formset to header and save lines
        lines_formset.instance = self.object
        self._save_lines(lines_formset)

        # 3) recompute totals
        self.object.recompute_totals(save=True)

        # 4) audit + notification
        self._log_audit()
        self._notify_user()

        # 5) success + redirect
        messages.success(self.request, _("تم إنشاء عرض السعر بنجاح."))
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("sales:sales_detail", args=[self.object.pk])


class SalesDocumentDetailView(SalesBaseView, DetailView):
    """
    عرض تفاصيل مستند المبيعات:
    - معلومات الهيدر (العميل، التواريخ، العملة، الإجمالي).
    - بنود المبيعات المرتبطة بالمستند.
    - مذكرات التسليم المرتبطة (إن وُجدت).
    - رابط لسجل التدقيق (AuditLog) الخاص بهذا المستند فقط.
    """
    model = SalesDocument
    template_name = "sales/sales/detail.html"
    context_object_name = "document"
    sales_section = "sales_detail"

    def get_queryset(self):
        """
        تحسين الاستعلام باستخدام:
        - select_related لجهة الاتصال (contact).
        - prefetch_related للبنود (lines) ومذكرات التسليم (delivery_notes).
        """
        return (
            SalesDocument.objects
            .select_related("contact")
            .prefetch_related("lines", "delivery_notes")
        )

    def get_context_data(self, **kwargs):
        """
        إضافة بيانات إضافية للتمبليت:

        - audit_log_url:
          رابط صفحة سجل التدقيق لهذا المستند فقط، مع فلترة:
          target_model = "sales.SalesDocument"
          target_id    = document.pk
        """
        ctx = super().get_context_data(**kwargs)
        document: SalesDocument = ctx["document"]

        query = urlencode({
            "target_model": "sales.SalesDocument",
            "target_id": document.pk,
        })

        ctx["audit_log_url"] = reverse("core:audit_log_list") + f"?{query}"

        return ctx


class SalesDocumentUpdateView(SalesBaseView, UpdateView):
    """
    تعديل مستند المبيعات:
    - تحديث بيانات الهيدر.
    - تعديل بنود المبيعات عبر formset.
    - ضبط updated_by بالمستخدم الحالي.
    - إعادة احتساب الإجماليات بعد الحفظ.
    - تسجيل الأوديت على التعديل مع حفظ القيم القديمة والجديدة.
    - إنشاء إشعار بتحديث المستند.
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
        - حفظ البنود المرتبطة.
        - إعادة احتساب الإجماليات.
        - تسجيل الأوديت كتعديل.
        - إنشاء إشعار بتحديث المستند.
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

        # --- نتفيكشن: إشعار بتعديل المستند ---
        if user.is_authenticated:
            create_notification(
                recipient=user,
                verb=_("تم تحديث مستند المبيعات %(number)s") % {
                    "number": self.object.display_number
                },
                target=self.object,
                level=Notification.Levels.INFO,
                url=reverse("sales:sales_detail", args=[self.object.pk]),
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
    (والـ service بدوره يتكفّل بالمنطق والأوديت).

    هنا نركّز فقط على:
    - استدعاء الـ service.
    - عرض الرسائل للمستخدم.
    - إنشاء إشعار بنجاح التحويل.
    """
    sales_section = "sales_detail"

    def post(self, request, pk):
        document = get_object_or_404(SalesDocument.objects.quotations(), pk=pk)

        try:
            services.confirm_quotation_to_order(document, user=request.user)
        except Exception as e:
            messages.error(request, str(e))
            return redirect(document.get_absolute_url())

        # نتفيكشن بسيط للمستخدم الحالي
        if request.user.is_authenticated:
            create_notification(
                recipient=request.user,
                verb=_("تم تحويل عرض السعر %(number)s إلى أمر بيع") % {
                    "number": document.display_number
                },
                target=document,
                level=Notification.Levels.SUCCESS,
                url=document.get_absolute_url(),
            )

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

    هنا نضيف إشعار بسيط للمستخدم عند النجاح.
    """
    sales_section = "sales_detail"

    def post(self, request, pk):
        order = get_object_or_404(SalesDocument.objects.orders(), pk=pk)

        try:
            services.mark_order_invoiced(order, user=request.user)
        except Exception as e:
            messages.error(request, str(e))
            return redirect(order.get_absolute_url())

        if request.user.is_authenticated:
            create_notification(
                recipient=request.user,
                verb=_("تم تعليم أمر البيع %(number)s كمفوتر") % {
                    "number": order.display_number
                },
                target=order,
                level=Notification.Levels.INFO,
                url=order.get_absolute_url(),
            )

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
    - يتم إنشاء إشعار للمستخدم الحالي.
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
        - إنشاء إشعار للمستخدم.
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

        # --- نتفيكشن: إشعار بإنشاء مذكرة التسليم ---
        if user.is_authenticated:
            create_notification(
                recipient=user,
                verb=_("تم إنشاء مذكرة التسليم %(dn)s لأمر البيع %(order)s") % {
                    "dn": self.object.display_number,
                    "order": self.order.display_number,
                },
                target=self.object,
                level=Notification.Levels.SUCCESS,
                url=reverse("sales:delivery_note_detail", args=[self.object.pk]),
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

    هنا نقوم فقط:
    - باستدعاء الـ service.
    - عرض الرسائل.
    - إنشاء إشعار بإلغاء المستند.
    """
    sales_section = "sales_detail"

    def post(self, request, pk):
        document = get_object_or_404(SalesDocument, pk=pk)

        try:
            services.cancel_sales_document(document, user=request.user)
        except Exception as e:
            messages.error(request, str(e))
            return redirect(document.get_absolute_url())

        if request.user.is_authenticated:
            create_notification(
                recipient=request.user,
                verb=_("تم إلغاء مستند المبيعات %(number)s") % {
                    "number": document.display_number
                },
                target=document,
                level=Notification.Levels.WARNING,
                url=document.get_absolute_url(),
            )

        messages.success(request, _("تم إلغاء المستند بنجاح."))
        return redirect(document.get_absolute_url())


class ResetSalesDocumentToDraftView(SalesBaseView, View):
    """
    إعادة مستند المبيعات إلى حالة المسودة
    باستخدام service: reset_sales_document_to_draft
    (والأوديت يتم من داخل الـ service).

    هنا نضيف فقط إشعار عند النجاح.
    """
    sales_section = "sales_detail"

    def post(self, request, pk):
        document = get_object_or_404(SalesDocument, pk=pk)

        try:
            services.reset_sales_document_to_draft(document, user=request.user)
        except Exception as e:
            messages.error(request, str(e))
            return redirect(document.get_absolute_url())

        if request.user.is_authenticated:
            create_notification(
                recipient=request.user,
                verb=_("تمت إعادة مستند المبيعات %(number)s إلى حالة المسودة") % {
                    "number": document.display_number
                },
                target=document,
                level=Notification.Levels.INFO,
                url=document.get_absolute_url(),
            )

        messages.success(request, _("تمت إعادة المستند إلى حالة المسودة بنجاح."))
        return redirect(document.get_absolute_url())


@login_required
def sales_reopen_view(request, pk):
    """
    فيو وظيفي (Function-Based View) لإعادة فتح مستند ملغي
    إلى حالة المسودة كعرض سعر
    باستخدام service: reopen_cancelled_sales_document
    (والـ service يسجل الأوديت).

    هنا نضيف إشعار بسيط لإعادة الفتح.
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

        create_notification(
            recipient=request.user,
            verb=_("تمت إعادة فتح مستند المبيعات %(number)s كعرض سعر") % {
                "number": document.display_number
            },
            target=document,
            level=Notification.Levels.SUCCESS,
            url=document.get_absolute_url(),
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
def product_api(request, pk=None):
    """
    Endpoint موحّد:

    - ?q=ABC → بحث بالكود/الاسم (autocomplete)
    - /product/api/<pk>/ → معلومات UoM + الأسعار
    """

    # 1) حالة البحث (autocomplete)
    q = request.GET.get("q")
    if q is not None:
        q = q.strip()
        results = []
        if q:
            qs = Product.objects.filter(code__icontains=q)[:10]
            for p in qs:
                results.append({
                    "id": p.id,
                    "code": p.code,
                    "name": p.name,
                })
        return JsonResponse({"results": results})

    # 2) حالة طلب معلومات منتج معيّن
    if pk is not None:
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

        def label(u):
            if not u:
                return ""
            return getattr(u, "name", str(u))

        data = {
            "id": product.id,
            "code": product.code,
            "name": product.name,

            # uom info
            "base_uom": label(base_uom),
            "alt_uom": label(alt_uom),
            "alt_factor": str(alt_factor or ""),

            # prices
            "base_price": str(base_price or ""),
            "alt_price": str(alt_price or ""),
        }

        return JsonResponse(data)

    # 3) استخدام خاطئ → نرجّع خطأ
    return JsonResponse({"error": "Invalid request"}, status=400)


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
