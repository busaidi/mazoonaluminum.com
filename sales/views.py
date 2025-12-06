# sales/views.py
import json
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext_lazy as _
from django.views import generic
from django.core.exceptions import ValidationError

# استيراد الموديلات والخدمات
from inventory.models import Product
from .models import SalesDocument, SalesLine, DeliveryNote, DeliveryLine
from .forms import (
    SalesDocumentForm,
    SalesLineFormSet,
    DeliveryNoteForm,
    DeliveryLineFormSet,
    DirectDeliveryLineFormSet,
    DirectDeliveryNoteForm,
    LinkOrderForm
)
from .services import SalesService


# ===================================================================
# 0. Dashboard
# ===================================================================

class SalesDashboardView(LoginRequiredMixin, generic.TemplateView):
    template_name = "sales/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # مسودات (عروض أسعار)
        context['draft_quotations_count'] = SalesDocument.objects.filter(
            status=SalesDocument.Status.DRAFT, is_deleted=False
        ).count()

        # أوامر مؤكدة بانتظار التسليم
        context['pending_orders_count'] = SalesDocument.objects.filter(
            status=SalesDocument.Status.CONFIRMED,
            delivery_status__in=[SalesDocument.DeliveryStatus.PENDING, SalesDocument.DeliveryStatus.PARTIAL],
            is_deleted=False
        ).count()

        # الإيرادات المؤكدة
        total_revenue = SalesDocument.objects.filter(
            status=SalesDocument.Status.CONFIRMED, is_deleted=False
        ).aggregate(t=Sum('total_amount'))['t']
        context['total_revenue'] = total_revenue if total_revenue else 0

        # آخر العمليات
        context['recent_documents'] = SalesDocument.objects.filter(is_deleted=False).order_by('-date')[:5]

        return context


# ===================================================================
# 1. القائمة الموحدة (Unified List View)
# ===================================================================

class SalesListView(LoginRequiredMixin, generic.ListView):
    model = SalesDocument
    template_name = "sales/sales/list.html"
    context_object_name = "documents"
    paginate_by = 20

    def get_queryset(self):
        queryset = SalesDocument.objects.filter(is_deleted=False).select_related("contact")

        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(contact__name__icontains=q) | queryset.filter(id__icontains=q)

        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)

        return queryset.order_by("-date", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_q'] = self.request.GET.get('q', '')
        context['current_status'] = self.request.GET.get('status', '')
        context['status_choices'] = SalesDocument.Status.choices
        return context


# ===================================================================
# 2. الميكس (Mixin) لإنشاء وتعديل المستندات
# ===================================================================

class SalesDocumentMixin:
    model = SalesDocument
    form_class = SalesDocumentForm
    template_name = "sales/form.html"

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        products = Product.objects.filter(is_active=True).select_related('base_uom', 'alt_uom')
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

        if self.request.POST:
            data["lines"] = SalesLineFormSet(self.request.POST, instance=self.object)
        else:
            data["lines"] = SalesLineFormSet(instance=self.object)
        return data

    def form_valid(self, form):
        context = self.get_context_data()
        lines = context["lines"]

        if lines.is_valid():
            with transaction.atomic():
                self.object = form.save(commit=False)
                if not self.object.pk:
                    self.object.created_by = self.request.user

                self.object.updated_by = self.request.user
                self.object.save()

                lines.instance = self.object
                lines.save()

                self.object.recompute_totals()

            messages.success(self.request, _("تم حفظ المستند بنجاح."))
            return super().form_valid(form)
        else:
            return self.render_to_response(self.get_context_data(form=form))


# ===================================================================
# 3. Create & Update Views
# ===================================================================

class SalesCreateView(LoginRequiredMixin, SalesDocumentMixin, generic.CreateView):
    def get_success_url(self):
        return reverse("sales:document_detail", kwargs={'pk': self.object.pk})


class SalesDocumentUpdateView(LoginRequiredMixin, SalesDocumentMixin, generic.UpdateView):
    def get_success_url(self):
        return reverse("sales:document_detail", kwargs={'pk': self.object.pk})


class SalesDocumentDetailView(LoginRequiredMixin, generic.DetailView):
    model = SalesDocument
    template_name = "sales/sales/detail.html"
    context_object_name = "document"

    def get_queryset(self):
        return SalesDocument.objects.filter(is_deleted=False).select_related("contact").prefetch_related(
            "lines__product", "lines__uom")


# ===================================================================
# 4. Business Logic Actions
# ===================================================================

@transaction.atomic
def confirm_document(request, pk):
    document = get_object_or_404(SalesDocument, pk=pk)
    try:
        SalesService.confirm_document(document)
        messages.success(request, _("تم تأكيد المستند واعتماده كأمر بيع."))
    except ValidationError as e:
        messages.warning(request, str(e))
    return redirect("sales:document_detail", pk=pk)


@transaction.atomic
def create_delivery_from_order_view(request, pk):
    order = get_object_or_404(SalesDocument, pk=pk)
    try:
        delivery = SalesService.create_delivery_note(order)
        messages.success(request, _("تم إنشاء مسودة التسليم."))
        return redirect("sales:delivery_detail", pk=delivery.pk)
    except ValidationError as e:
        messages.error(request, str(e))
        return redirect("sales:document_detail", pk=pk)


def cancel_document_view(request, pk):
    document = get_object_or_404(SalesDocument, pk=pk)
    try:
        SalesService.cancel_order(document)
        messages.warning(request, _("تم إلغاء المستند."))
    except ValidationError as e:
        messages.error(request, str(e))
    return redirect("sales:document_detail", pk=pk)


def restore_document_view(request, pk):
    document = get_object_or_404(SalesDocument, pk=pk)
    try:
        SalesService.restore_document(document)
        messages.success(request, _("تم استعادة المستند بنجاح."))
    except ValidationError as e:
        messages.error(request, str(e))
    return redirect("sales:document_detail", pk=pk)


class SalesDocumentDeleteView(LoginRequiredMixin, generic.DeleteView):
    model = SalesDocument
    template_name = "sales/sales/delete.html"

    def get_success_url(self):
        return reverse("sales:document_list")

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.soft_delete(user=request.user)
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
        return DeliveryNote.objects.filter(is_deleted=False).select_related("contact", "order").order_by("-date", "-id")


class DeliveryDetailView(LoginRequiredMixin, generic.DetailView):
    model = DeliveryNote
    template_name = "sales/delivery/detail.html"
    context_object_name = "delivery"

    def get_queryset(self):
        return DeliveryNote.objects.filter(is_deleted=False).select_related("contact", "order").prefetch_related(
            "lines__product", "lines__uom")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not self.object.order and self.object.contact:
            context['link_order_form'] = LinkOrderForm(contact=self.object.contact)
        return context


class DirectDeliveryCreateView(LoginRequiredMixin, generic.CreateView):
    model = DeliveryNote
    form_class = DirectDeliveryNoteForm
    template_name = "sales/delivery/form.html"

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        products = Product.objects.filter(is_active=True).select_related('base_uom', 'alt_uom')
        products_dict = {}
        for p in products:
            products_dict[str(p.id)] = {
                "base_uom_id": p.base_uom_id,
                "base_uom_name": p.base_uom.name if p.base_uom else "",
                "alt_uom_id": p.alt_uom_id if p.alt_uom_id else None,
                "alt_uom_name": p.alt_uom.name if p.alt_uom else "",
            }
        data["products_dict"] = products_dict

        if self.request.POST:
            data["lines"] = DirectDeliveryLineFormSet(self.request.POST)
        else:
            data["lines"] = DirectDeliveryLineFormSet()
        return data

    def form_valid(self, form):
        context = self.get_context_data()
        lines = context["lines"]

        if lines.is_valid():
            with transaction.atomic():
                self.object = form.save(commit=False)
                self.object.created_by = self.request.user
                self.object.save()
                lines.instance = self.object
                lines.save()

            messages.success(self.request, _("تم إنشاء مذكرة التسليم المباشر."))
            return redirect("sales:delivery_detail", pk=self.object.pk)

        return self.render_to_response(self.get_context_data(form=form))


@transaction.atomic
def confirm_delivery_view(request, pk):
    delivery = get_object_or_404(DeliveryNote, pk=pk)
    try:
        SalesService.confirm_delivery(delivery)
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
        self.object.soft_delete(user=request.user)
        messages.success(request, _("تم حذف مذكرة التسليم."))
        return redirect(self.success_url)


def link_delivery_to_order_view(request, pk):
    """ربط تسليم مباشر بأمر بيع"""
    delivery = get_object_or_404(DeliveryNote, pk=pk)

    if request.method == 'POST':
        form = LinkOrderForm(request.POST, contact=delivery.contact)
        if form.is_valid():
            order = form.cleaned_data['order']
            delivery.order = order
            delivery.save()

            # تحديث حالة الأمر
            SalesService._update_order_delivery_status(order)

            messages.success(request, _("تم ربط التسليم بالأمر بنجاح."))
            return redirect('sales:delivery_detail', pk=pk)

    messages.error(request, _("حدث خطأ أثناء الربط."))
    return redirect('sales:delivery_detail', pk=pk)