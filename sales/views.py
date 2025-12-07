# sales/views.py

import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum, Q
from django.forms.models import inlineformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext_lazy as _
from django.views import generic

from core.models import AuditLog
from inventory.models import Product

from .models import SalesDocument, SalesLine, DeliveryNote, DeliveryLine, DECIMAL_ZERO
from .forms import (
    SalesDocumentForm,
    SalesLineFormSet,
    DeliveryNoteForm,
    DeliveryLineFormSet,
    DeliveryFromOrderLineFormSet,  # ✅ مهم لهذا الفيو
    DirectDeliveryLineFormSet,
    DirectDeliveryNoteForm,
    LinkOrderForm, DeliveryLineForm,
)
from .services import (
    SalesService,
    log_sales_document_action,
    log_delivery_note_action,
)


# ===================================================================
# 0. Dashboard
# ===================================================================

class SalesDashboardView(LoginRequiredMixin, generic.TemplateView):
    template_name = "sales/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        base_qs = (
            SalesDocument.objects.filter(is_deleted=False)
            .select_related("contact")
        )

        # إجمالي المستندات والمبالغ
        total_sales_amount = base_qs.aggregate(t=Sum("total_amount"))["t"] or 0
        total_documents_count = base_qs.count()

        # مسودات (نعتبرها عروض أسعار)
        draft_qs = base_qs.filter(status=SalesDocument.Status.DRAFT)
        draft_quotations_count = draft_qs.count()
        draft_total_amount = draft_qs.aggregate(t=Sum("total_amount"))["t"] or 0

        # أوامر مؤكدة
        confirmed_qs = base_qs.filter(status=SalesDocument.Status.CONFIRMED)
        confirmed_orders_count = confirmed_qs.count()
        confirmed_total_amount = confirmed_qs.aggregate(t=Sum("total_amount"))["t"] or 0

        # ملغية
        cancelled_documents_count = base_qs.filter(
            status=SalesDocument.Status.CANCELLED
        ).count()

        # أوامر مؤكدة بإنتظار التسليم / تسليم جزئي
        pending_orders_qs = confirmed_qs.filter(
            delivery_status__in=[
                SalesDocument.DeliveryStatus.PENDING,
                SalesDocument.DeliveryStatus.PARTIAL,
            ]
        )
        pending_orders_count = pending_orders_qs.count()

        # مذكرات التسليم
        delivery_qs = (
            DeliveryNote.objects.filter(is_deleted=False)
            .select_related("contact", "order")
        )
        delivery_notes_count = delivery_qs.count()

        # أحدث مستندات (عام)
        recent_documents = base_qs.order_by("-date", "-id")[:5]

        # أحدث مسودات (نستخدمها كـ "Latest quotations")
        latest_drafts = draft_qs.order_by("-date", "-id")[:5]

        # أحدث أوامر مؤكدة
        latest_orders = confirmed_qs.order_by("-date", "-id")[:5]

        # أحدث مذكرات تسليم
        latest_deliveries = delivery_qs.order_by("-date", "-id")[:5]

        # أعلى العملاء حسب إجمالي المبيعات (للمستندات المؤكدة)
        top_customers = (
            confirmed_qs.values("contact_id", "contact__name")
            .annotate(total_sales=Sum("total_amount"))
            .order_by("-total_sales")[:5]
        )

        context.update(
            {
                "total_sales_amount": total_sales_amount,
                "total_documents_count": total_documents_count,
                "draft_quotations_count": draft_quotations_count,
                "draft_total_amount": draft_total_amount,
                "confirmed_orders_count": confirmed_orders_count,
                "confirmed_total_amount": confirmed_total_amount,
                "cancelled_documents_count": cancelled_documents_count,
                "pending_orders_count": pending_orders_count,
                "delivery_notes_count": delivery_notes_count,
                "recent_documents": recent_documents,
                "latest_drafts": latest_drafts,
                "latest_orders": latest_orders,
                "latest_deliveries": latest_deliveries,
                "top_customers": top_customers,
            }
        )

        return context


# ===================================================================
# 1. Unified List View
# ===================================================================

class SalesListView(LoginRequiredMixin, generic.ListView):
    model = SalesDocument
    template_name = "sales/sales/list.html"
    context_object_name = "documents"
    paginate_by = 20

    def get_queryset(self):
        queryset = (
            SalesDocument.objects.filter(is_deleted=False)
            .select_related("contact")
        )

        q = self.request.GET.get("q", "").strip()
        if q:
            # Search by contact name, client_reference, or document id
            queryset = queryset.filter(
                Q(contact__name__icontains=q)
                | Q(client_reference__icontains=q)
                | Q(id__icontains=q)
            )

        status = self.request.GET.get("status")
        if status:
            queryset = queryset.filter(status=status)

        return queryset.order_by("-date", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_q"] = self.request.GET.get("q", "")
        context["current_status"] = self.request.GET.get("status", "")
        context["status_choices"] = SalesDocument.Status.choices
        return context


# ===================================================================
# 2. Mixin for create/update sales document
# ===================================================================

class SalesDocumentMixin:
    model = SalesDocument
    form_class = SalesDocumentForm
    template_name = "sales/sales/form.html"

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)

        # تحميل بيانات المنتجات (سعر + UOM) للجافاسكربت
        products = Product.objects.filter(is_active=True).select_related(
            "base_uom", "alt_uom"
        )
        products_dict = {}
        for p in products:
            products_dict[str(p.id)] = {
                "name": p.name,
                "price": float(p.default_sale_price) if p.default_sale_price else 0.0,
                "base_uom_id": p.base_uom_id,
                "base_uom_name": p.base_uom.name if p.base_uom else "",
                "alt_uom_id": p.alt_uom_id if p.alt_uom_id else None,
                "alt_uom_name": p.alt_uom.name if p.alt_uom else "",
                "alt_factor": float(p.alt_factor) if p.alt_factor else 1.0,
            }
        data["products_dict"] = products_dict

        # formset للأسطر
        if self.request.method == "POST":
            data["lines"] = SalesLineFormSet(
                self.request.POST,
                instance=self.object,
            )
        else:
            data["lines"] = SalesLineFormSet(instance=self.object)

        return data

    def form_invalid(self, form):
        """
        لو الفورم الأساسي نفسه فيه أخطاء (client, date, ...),
        نعيد نفس الصفحة مع عرض الأخطاء + الفورمسيت.
        """
        context = self.get_context_data(form=form)
        return self.render_to_response(context)

    def form_valid(self, form):
        """
        حفظ الهيدر + الأسطر في ترانزاكشن واحدة.
        """
        context = self.get_context_data()
        lines = context["lines"]

        if not lines.is_valid():
            # إعادة عرض الصفحة مع أخطاء الفورمسيت
            return self.render_to_response(self.get_context_data(form=form))

        is_create = self.object is None or not getattr(self.object, "pk", None)

        with transaction.atomic():
            self.object = form.save(commit=False)
            if is_create:
                self.object.created_by = self.request.user
            self.object.updated_by = self.request.user
            self.object.save()

            lines.instance = self.object
            lines.save()

            self.object.recompute_totals(save=True)

            action = AuditLog.Action.CREATE if is_create else AuditLog.Action.UPDATE
            if is_create:
                msg = _("تم إنشاء مستند مبيعات رقم %(number)s.") % {
                    "number": self.object.display_number,
                }
            else:
                msg = _("تم تعديل مستند مبيعات رقم %(number)s.") % {
                    "number": self.object.display_number,
                }

            log_sales_document_action(
                user=self.request.user,
                document=self.object,
                action=action,
                message=msg,
                extra={
                    "status": self.object.status,
                    "total_amount": float(self.object.total_amount or 0),
                },
                notify=False,
            )

        messages.success(self.request, _("تم حفظ المستند بنجاح."))
        return redirect(self.get_success_url())


# ===================================================================
# 3. Create & Update Views
# ===================================================================

class SalesCreateView(LoginRequiredMixin, SalesDocumentMixin, generic.CreateView):
    def get_success_url(self):
        return reverse("sales:document_detail", kwargs={"pk": self.object.pk})


class SalesDocumentUpdateView(LoginRequiredMixin, SalesDocumentMixin, generic.UpdateView):
    def get_success_url(self):
        return reverse("sales:document_detail", kwargs={"pk": self.object.pk})


class SalesDocumentDetailView(LoginRequiredMixin, generic.DetailView):
    model = SalesDocument
    template_name = "sales/sales/detail.html"
    context_object_name = "document"

    def get_queryset(self):
        return (
            SalesDocument.objects.filter(is_deleted=False)
            .select_related("contact")
            .prefetch_related("lines__product", "lines__uom")
        )


# ===================================================================
# 4. Business Logic Actions
# ===================================================================

@transaction.atomic
def confirm_document(request, pk):
    document = get_object_or_404(SalesDocument, pk=pk)
    try:
        SalesService.confirm_document(document)

        # Audit + Notification
        log_sales_document_action(
            user=request.user,
            document=document,
            action=AuditLog.Action.STATUS_CHANGE,
            message=_("تم تأكيد مستند المبيعات رقم %(number)s كأمر بيع.") % {
                "number": document.display_number,
            },
            extra={
                "status": document.status,
                "delivery_status": document.delivery_status,
            },
            notify=True,
        )

        messages.success(request, _("تم تأكيد المستند واعتماده كأمر بيع."))
    except ValidationError as e:
        messages.warning(request, str(e))
    return redirect("sales:document_detail", pk=pk)


@transaction.atomic
def create_delivery_from_order_view(request, pk):
    order = get_object_or_404(SalesDocument, pk=pk)
    try:
        delivery = SalesService.create_delivery_note(order)

        # Audit لمذكرة التسليم
        log_delivery_note_action(
            user=request.user,
            delivery=delivery,
            action=AuditLog.Action.CREATE,
            message=_("تم إنشاء مذكرة تسليم من أمر البيع رقم %(number)s.") % {
                "number": order.display_number,
            },
            extra={"order_id": order.pk},
            notify=False,
        )

        # Audit للأمر نفسه
        log_sales_document_action(
            user=request.user,
            document=order,
            action=AuditLog.Action.OTHER,
            message=_("تم إنشاء مذكرة تسليم مرتبطة بأمر البيع رقم %(number)s.") % {
                "number": order.display_number,
            },
            extra={"delivery_id": delivery.pk},
            notify=False,
        )

        messages.success(request, _("تم إنشاء مسودة التسليم."))
        return redirect("sales:delivery_detail", pk=delivery.pk)
    except ValidationError as e:
        messages.error(request, str(e))
        return redirect("sales:document_detail", pk=pk)


@transaction.atomic
def cancel_document_view(request, pk):
    document = get_object_or_404(SalesDocument, pk=pk)
    try:
        SalesService.cancel_order(document)

        log_sales_document_action(
            user=request.user,
            document=document,
            action=AuditLog.Action.STATUS_CHANGE,
            message=_("تم إلغاء مستند المبيعات رقم %(number)s.") % {
                "number": document.display_number,
            },
            extra={"status": document.status},
            notify=False,
        )

        messages.warning(request, _("تم إلغاء المستند."))
    except ValidationError as e:
        messages.error(request, str(e))
    return redirect("sales:document_detail", pk=pk)


@transaction.atomic
def restore_document_view(request, pk):
    document = get_object_or_404(SalesDocument, pk=pk)
    try:
        SalesService.restore_document(document)

        log_sales_document_action(
            user=request.user,
            document=document,
            action=AuditLog.Action.STATUS_CHANGE,
            message=_("تم استعادة مستند المبيعات رقم %(number)s.") % {
                "number": document.display_number,
            },
            extra={"status": document.status},
            notify=False,
        )

        messages.success(request, _("تم استعادة المستند بنجاح."))
    except ValidationError as e:
        messages.error(request, str(e))
    return redirect("sales:document_detail", pk=pk)


class SalesDocumentDeleteView(LoginRequiredMixin, generic.DeleteView):
    model = SalesDocument
    template_name = "sales/sales/delete.html"

    def get_success_url(self):
        # متوافق مع الروابط في القوالب (قائمة المبيعات)
        return reverse("sales:document_list")

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        number = self.object.display_number

        self.object.soft_delete(user=request.user)

        log_sales_document_action(
            user=request.user,
            document=self.object,
            action=AuditLog.Action.DELETE,
            message=_("تم حذف مستند المبيعات رقم %(number)s.") % {
                "number": number,
            },
            extra=None,
            notify=False,
        )

        messages.success(request, _("تم حذف المستند."))
        return redirect(self.get_success_url())


# ===================================================================
# 5. Delivery Note Views & Direct Delivery
# ===================================================================

class DeliveryListView(LoginRequiredMixin, generic.ListView):
    model = DeliveryNote
    template_name = "sales/delivery/list.html"
    context_object_name = "deliveries"
    paginate_by = 20

    def get_queryset(self):
        return (
            DeliveryNote.objects.filter(is_deleted=False)
            .select_related("contact", "order")
            .order_by("-date", "-id")
        )


class DeliveryDetailView(LoginRequiredMixin, generic.DetailView):
    model = DeliveryNote
    template_name = "sales/delivery/detail.html"
    context_object_name = "delivery"

    def get_queryset(self):
        return (
            DeliveryNote.objects.filter(is_deleted=False)
            .select_related("contact", "order")
            .prefetch_related("lines__product", "lines__uom")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Show link-order form only for direct deliveries that have a contact
        if not self.object.order and self.object.contact:
            context["link_order_form"] = LinkOrderForm(
                contact=self.object.contact
            )
        return context


class DirectDeliveryCreateView(LoginRequiredMixin, generic.CreateView):
    model = DeliveryNote
    form_class = DirectDeliveryNoteForm
    template_name = "sales/delivery/form.html"

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)

        products = Product.objects.filter(is_active=True).select_related(
            "base_uom", "alt_uom"
        )
        products_dict = {}
        for p in products:
            products_dict[str(p.id)] = {
                "base_uom_id": p.base_uom_id,
                "base_uom_name": p.base_uom.name if p.base_uom else "",
                "alt_uom_id": p.alt_uom_id if p.alt_uom_id else None,
                "alt_uom_name": p.alt_uom.name if p.alt_uom else "",
            }
        data["products_dict"] = products_dict
        data["products_json"] = json.dumps(products_dict)

        if self.request.POST:
            data["lines"] = DirectDeliveryLineFormSet(self.request.POST)
        else:
            data["lines"] = DirectDeliveryLineFormSet()
        return data

    def form_valid(self, form):
        context = self.get_context_data()
        lines = context["lines"]

        if not lines.is_valid():
            context["form"] = form
            context["lines"] = lines
            return self.render_to_response(context)

        with transaction.atomic():
            self.object = form.save(commit=False)
            self.object.created_by = self.request.user
            self.object.save()

            lines.instance = self.object
            lines.save()

            log_delivery_note_action(
                user=self.request.user,
                delivery=self.object,
                action=AuditLog.Action.CREATE,
                message=_("تم إنشاء مذكرة تسليم مباشر رقم %(number)s.") % {
                    "number": self.object.display_number,
                },
                extra={"kind": "direct"},
                notify=False,
            )

        messages.success(self.request, _("تم إنشاء مذكرة التسليم المباشر."))
        return redirect("sales:delivery_detail", pk=self.object.pk)


@transaction.atomic
def confirm_delivery_view(request, pk):
    delivery = get_object_or_404(DeliveryNote, pk=pk)
    try:
        SalesService.confirm_delivery(delivery)

        log_delivery_note_action(
            user=request.user,
            delivery=delivery,
            action=AuditLog.Action.STATUS_CHANGE,
            message=_("تم تأكيد مذكرة التسليم رقم %(number)s وتحديث المخزون.") % {
                "number": delivery.display_number,
            },
            extra={"status": delivery.status},
            notify=True,
        )

        messages.success(request, _("تم تأكيد التسليم وتحديث المخزون."))
    except ValidationError as e:
        messages.error(request, str(e))
    return redirect("sales:delivery_detail", pk=pk)


class DeliveryDeleteView(LoginRequiredMixin, generic.DeleteView):
    model = DeliveryNote
    template_name = "sales/sales/delete.html"
    success_url = reverse_lazy("sales:delivery_list")

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        number = self.object.display_number

        self.object.soft_delete(user=request.user)

        log_delivery_note_action(
            user=request.user,
            delivery=self.object,
            action=AuditLog.Action.DELETE,
            message=_("تم حذف مذكرة التسليم رقم %(number)s.") % {
                "number": number,
            },
            extra=None,
            notify=False,
        )

        messages.success(request, _("تم حذف مذكرة التسليم."))
        return redirect(self.success_url)


def link_delivery_to_order_view(request, pk):
    """Link a direct delivery note to an existing confirmed order."""
    delivery = get_object_or_404(DeliveryNote, pk=pk)

    if request.method == "POST":
        form = LinkOrderForm(request.POST, contact=delivery.contact)
        if form.is_valid():
            order = form.cleaned_data["order"]
            delivery.order = order
            delivery.save()

            # Recompute delivery status on the linked order
            if order:
                order.recompute_delivery_status(save=True)

            # Audit لمذكرة التسليم
            log_delivery_note_action(
                user=request.user,
                delivery=delivery,
                action=AuditLog.Action.UPDATE,
                message=_(
                    "تم ربط مذكرة التسليم رقم %(dn)s بأمر البيع رقم %(order)s."
                ) % {
                    "dn": delivery.display_number,
                    "order": order.display_number,
                },
                extra={"order_id": order.pk},
                notify=False,
            )

            # Audit لأمر البيع (تحديث حالة التسليم)
            if order:
                log_sales_document_action(
                    user=request.user,
                    document=order,
                    action=AuditLog.Action.STATUS_CHANGE,
                    message=_(
                        "تم تحديث حالة التسليم لأمر البيع رقم %(number)s بعد ربط مذكرة التسليم."
                    ) % {
                        "number": order.display_number,
                    },
                    extra={"delivery_status": order.delivery_status},
                    notify=False,
                )

            messages.success(
                request, _("تم ربط التسليم بالأمر بنجاح.")
            )
            return redirect("sales:delivery_detail", pk=pk)

    messages.error(request, _("حدث خطأ أثناء الربط."))
    return redirect("sales:delivery_detail", pk=pk)


# ===================================================================
# 6. Delivery From Order (CreateView + ModelFormSet)
# ===================================================================

@transaction.atomic
def delivery_from_order_create_view(request, pk):
    """
    إنشاء مذكرة تسليم من أمر بيع:

    - يعرض كل سطور أمر البيع كبنود في الجدول.
    - يملأ الكمية الافتراضية من remaining_quantity.
    - يمنع إدخال كمية أكبر من المتبقي.
    """
    order = get_object_or_404(SalesDocument, pk=pk)

    # سطور أمر البيع اللي بنبني عليها الفورمسيت
    sales_lines_qs = (
        order.lines
        .select_related("product", "uom")
        .order_by("id")
    )
    sales_lines = list(sales_lines_qs)
    lines_count = len(sales_lines)

    # 👈 FormSet مخصص بعدد سطور الأمر
    DeliveryFromOrderFormSet = inlineformset_factory(
        DeliveryNote,
        DeliveryLine,
        form=DeliveryLineForm,
        extra=lines_count,
        can_delete=False,
    )

    if request.method == "POST":
        # instance فيه order + contact عشان ما يطلع خطأ contact
        delivery_instance = DeliveryNote(
            order=order,
            contact=order.contact,
        )
        form = DeliveryNoteForm(request.POST, instance=delivery_instance)

        lines_formset = DeliveryFromOrderFormSet(
            request.POST,
            instance=delivery_instance,
        )

        if form.is_valid() and lines_formset.is_valid():
            has_qty_error = False

            # 🔒 منع إدخال كمية أكبر من المتبقي
            for line_form in lines_formset.forms:
                if not line_form.cleaned_data:
                    continue

                sales_line = line_form.cleaned_data.get("sales_line")
                qty = line_form.cleaned_data.get("quantity")

                # سطر فاضي أو كمية صفرية نتجاهله
                if not sales_line or qty in (None, DECIMAL_ZERO):
                    continue

                if qty > sales_line.remaining_quantity:
                    line_form.add_error(
                        "quantity",
                        _(
                            "لا يمكن تسليم كمية أكبر من الكمية المتبقية (%(remaining)s)."
                        )
                        % {"remaining": sales_line.remaining_quantity},
                    )
                    has_qty_error = True

            if has_qty_error:
                # نعيد عرض الصفحة مع الأخطاء + ربط كل فورم بسطره
                line_rows = list(zip(lines_formset.forms, sales_lines))
                context = {
                    "form": form,
                    "lines": lines_formset,
                    "line_rows": line_rows,
                    "order": order,
                }
                return render(request, "sales/delivery/from_order_form.html", context)

            # ✅ الحفظ الفعلي
            with transaction.atomic():
                delivery = form.save(commit=False)

                if request.user.is_authenticated:
                    delivery.created_by = request.user
                    delivery.updated_by = request.user
                delivery.save()

                lines_formset.instance = delivery
                lines_formset.save()

                # تحديث حالة التسليم للأمر
                order.recompute_delivery_status(save=True)

            messages.success(
                request,
                _("تم إنشاء مذكرة تسليم مرتبطة بأمر البيع %(number)s.")
                % {"number": order.display_number},
            )
            return redirect("sales:delivery_detail", pk=delivery.pk)

        # لو الفورم أو الفورمسيت فيهم أخطاء
        line_rows = list(zip(lines_formset.forms, sales_lines))
        context = {
            "form": form,
            "lines": lines_formset,
            "line_rows": line_rows,
            "order": order,
        }
        return render(request, "sales/delivery/from_order_form.html", context)

    else:
        # GET: نبني الفورم + الفورمسيت مع initial من سطور الأمر
        delivery_instance = DeliveryNote(
            order=order,
            contact=order.contact,
        )
        form = DeliveryNoteForm(instance=delivery_instance)

        lines_formset = DeliveryFromOrderFormSet(instance=delivery_instance)

        # نعبي initial لكل فورم من سطر الأمر المقابل
        for form_line, sl in zip(lines_formset.forms, sales_lines):
            form_line.initial["sales_line"] = sl.pk
            form_line.initial["product"] = sl.product
            form_line.initial["uom"] = sl.uom
            form_line.initial["quantity"] = sl.remaining_quantity
            form_line.initial["description"] = sl.description or ""

        # 👈 هنا نربط كل line_form مع sales_line عشان التمبلت
        line_rows = list(zip(lines_formset.forms, sales_lines))

        context = {
            "form": form,
            "lines": lines_formset,
            "line_rows": line_rows,
            "order": order,
        }
        return render(request, "sales/delivery/from_order_form.html", context)

