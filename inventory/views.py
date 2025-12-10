from typing import Any, Dict, Optional

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.db.models import F, Sum, DecimalField, ProtectedError, Q
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from django.views.generic import (
    ListView, DetailView, CreateView, TemplateView,
    UpdateView, DeleteView
)
from tablib import Dataset

# Core Imports (Audit & Logging)
from core.models import AuditLog
from core.services.audit import log_event

# Forms
from .forms import (
    ReceiptMoveForm, DeliveryMoveForm, TransferMoveForm, StockMoveLineFormSet,
    WarehouseForm, ProductForm, StockLocationForm, ProductCategoryForm,
    InventoryCountFormSet, StartInventoryForm, ReorderRuleForm
)

# Models
from .models import (
    StockMove, Product, Warehouse, StockLevel, ReorderRule,
    InventorySettings, StockLocation, ProductCategory, InventoryAdjustment,
    StockMoveLine
)

# Resources (django-import-export)
from .resources import ProductResource

# Services
from .services import (
    confirm_stock_move,
    cancel_stock_move,
    apply_inventory_adjustment,
    create_inventory_session
)

# Utils
from .utils import render_pdf_view


# ============================================================
# Configuration Map
# ============================================================

MOVE_TYPE_META = {
    StockMove.MoveType.IN: {
        "title": _("استلام بضاعة (وارد)"),
        "label": _("وارد"),
        "color": "success",
        "create_url": "inventory:receipt_create",
        "list_url": "inventory:receipt_list",
        "form_class": ReceiptMoveForm,
    },
    StockMove.MoveType.OUT: {
        "title": _("أوامر صرف (صادر)"),
        "label": _("صادر"),
        "color": "primary",
        "create_url": "inventory:delivery_create",
        "list_url": "inventory:delivery_list",
        "form_class": DeliveryMoveForm,
    },
    StockMove.MoveType.TRANSFER: {
        "title": _("تحويلات داخلية"),
        "label": _("تحويل"),
        "color": "warning",
        "create_url": "inventory:transfer_create",
        "list_url": "inventory:transfer_list",
        "form_class": TransferMoveForm,
    },
}


# ============================================================
# Mixins & Helpers
# ============================================================

class StockMoveContextMixin:
    """
    Mixin to inject metadata about the move type (Color, Label, URLs)
    into the context and handle move_type dispatching.
    """
    move_type = None

    def dispatch(self, request, *args, **kwargs):
        self.move_type = kwargs.get("move_type")

        # Fallback: check object instance if not in URL
        if not self.move_type and hasattr(self, 'object') and self.object:
            self.move_type = self.object.move_type

        # Basic validation (optional, allows loose coupling)
        if self.move_type and self.move_type not in MOVE_TYPE_META:
            pass

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_type = self.move_type

        # Fallback logic for context
        if not current_type and hasattr(self, 'object') and self.object:
            current_type = self.object.move_type

        meta = MOVE_TYPE_META.get(current_type)
        if meta:
            context.update({
                "page_title": meta["title"],
                "move_type_label": meta["label"],
                "move_type_color": meta["color"],
                "create_url": reverse(meta["create_url"]),
                "list_url": reverse(meta["list_url"]),
            })

        context["current_move_type"] = current_type
        context["active_section"] = "inventory_operations"
        return context


class ProtectedDeleteMixin:
    """
    Mixin to prevent 500 Server Error when deleting protected objects.
    """
    def post(self, request, *args, **kwargs):
        try:
            return super().delete(request, *args, **kwargs)
        except ProtectedError:
            msg = _("لا يمكن حذف هذا السجل لأنه مرتبط ببيانات أخرى (مثل حركات مخزنية). يفضل أرشفتها بدلاً من حذفها.")
            messages.error(request, msg)
            return redirect(self.get_success_url())


# ============================================================
# Dashboard
# ============================================================

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_dashboard"

        context["total_products"] = Product.objects.active().count()
        context["total_warehouses"] = Warehouse.objects.active().count()
        # Custom manager method usually faster
        context["low_stock_count"] = len(ReorderRule.objects.get_triggered_rules())
        context["draft_moves_count"] = StockMove.objects.draft().count()

        context["latest_moves"] = (
            StockMove.objects
            .with_related()
            .filter(status=StockMove.Status.DONE)
            .order_by("-move_date", "-id")[:5]
        )
        return context


# ============================================================
# Stock Moves (CRUD)
# ============================================================

class StockMoveListView(LoginRequiredMixin, StockMoveContextMixin, ListView):
    model = StockMove
    template_name = "inventory/stock_move/list.html"
    context_object_name = "moves"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().with_related().order_by("-move_date", "-id")

        if self.move_type == StockMove.MoveType.IN:
            return qs.incoming()
        elif self.move_type == StockMove.MoveType.OUT:
            return qs.outgoing()
        elif self.move_type == StockMove.MoveType.TRANSFER:
            return qs.transfers()

        return qs.none()


class StockMoveCreateView(LoginRequiredMixin, StockMoveContextMixin, CreateView):
    model = StockMove
    template_name = "inventory/stock_move/form.html"

    def get_form_class(self):
        meta = MOVE_TYPE_META.get(self.move_type)
        return meta["form_class"] if meta else ReceiptMoveForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if not kwargs.get('instance'):
            kwargs['instance'] = self.model(move_type=self.move_type)
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['lines_formset'] = StockMoveLineFormSet(self.request.POST)
        else:
            context['lines_formset'] = StockMoveLineFormSet()
        return context

    def form_valid(self, form):
        context = self.get_context_data()
        lines_formset = context['lines_formset']

        form.instance.move_type = self.move_type
        form.instance.created_by = self.request.user

        if form.is_valid() and lines_formset.is_valid():
            try:
                with transaction.atomic():
                    self.object = form.save()
                    lines_formset.instance = self.object
                    lines_formset.save()

                    # ✅ Explicit Audit Log for Draft Creation
                    # لأن إنشاء المسودة لا يمر عبر services.py، نسجله هنا
                    log_event(
                        action=AuditLog.Action.CREATE,
                        message=f"Draft Stock Move Created: {self.object.reference or self.object.pk}",
                        actor=self.request.user,
                        target=self.object,
                        extra={
                            "move_type": str(self.object.move_type),
                            "warehouse": str(self.object.to_warehouse or self.object.from_warehouse)
                        }
                    )

                messages.success(self.request, _("تم إنشاء الحركة كمسودة (Draft) بنجاح."))
                return redirect(self.get_success_url())

            except Exception as e:
                messages.error(self.request, _("حدث خطأ أثناء الحفظ: ") + str(e))
                return self.form_invalid(form)
        else:
            if lines_formset.errors:
                messages.error(self.request, _("الرجاء التحقق من بيانات الأصناف."))
            return self.render_to_response(self.get_context_data(form=form))

    def get_success_url(self):
        return reverse("inventory:move_detail", kwargs={'pk': self.object.pk})


class StockMoveDetailView(LoginRequiredMixin, StockMoveContextMixin, DetailView):
    model = StockMove
    template_name = "inventory/stock_move/detail.html"
    context_object_name = "move"

    def get_queryset(self):
        return super().get_queryset().with_related()


# ============================================================
# Move Actions (Service Integration)
# ============================================================

@require_POST
@login_required
def confirm_move_view(request, pk):
    move = get_object_or_404(StockMove, pk=pk)
    try:
        # Service handles Logic + Audit + Notification
        confirm_stock_move(move, user=request.user)
        messages.success(request, _("تم تأكيد الحركة المخزنية وتحديث الأرصدة."))
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    except Exception as e:
        messages.error(request, _("حدث خطأ غير متوقع: ") + str(e))

    return redirect("inventory:move_detail", pk=pk)


@require_POST
@login_required
def cancel_move_view(request, pk):
    move = get_object_or_404(StockMove, pk=pk)
    try:
        # Service handles Logic + Audit + Notification
        cancel_stock_move(move, user=request.user)
        messages.warning(request, _("تم إلغاء الحركة المخزنية وعكس تأثيرها."))
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    except Exception as e:
        messages.error(request, _("حدث خطأ غير متوقع: ") + str(e))

    return redirect("inventory:move_detail", pk=pk)


@login_required
def stock_move_pdf_view(request, pk):
    move = get_object_or_404(StockMove, pk=pk)

    doc_meta = {
        StockMove.MoveType.IN: ("GRN", _("سند استلام مخزني")),
        StockMove.MoveType.OUT: ("DN", _("إذن صرف بضاعة")),
        StockMove.MoveType.TRANSFER: ("TN", _("سند تحويل داخلي")),
    }
    doc_type, doc_title = doc_meta.get(move.move_type, ("MOV", _("حركة مخزنية")))

    context = {
        'move': move,
        'lines': move.lines.select_related('product', 'uom').all(),
        'doc_title': doc_title,
        'doc_type': doc_type,
        'company_name': "Mazoon Aluminum",
        'print_date': timezone.now(),
        'user': request.user,
    }

    filename = f"{doc_type}-{move.reference or move.pk}.pdf"
    return render_pdf_view(request, 'inventory/pdf/stock_move_document.html', context, filename)


# ============================================================
# Inventory Adjustment (Stock Taking)
# ============================================================

class InventoryAdjustmentListView(LoginRequiredMixin, ListView):
    model = InventoryAdjustment
    template_name = "inventory/adjustments/list.html"
    context_object_name = "adjustments"
    paginate_by = 20

    def get_queryset(self):
        return InventoryAdjustment.objects.with_related().order_by("-date", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_operations"
        return context


class InventoryAdjustmentCreateView(LoginRequiredMixin, CreateView):
    model = InventoryAdjustment
    form_class = StartInventoryForm
    template_name = "inventory/adjustments/form.html"

    def form_valid(self, form):
        try:
            # Service handles creation + Logic + Audit
            self.object = create_inventory_session(
                warehouse=form.cleaned_data["warehouse"],
                user=self.request.user,
                category=form.cleaned_data["category"],
                location=form.cleaned_data["location"],
                note=form.cleaned_data["note"]
            )
            messages.success(self.request, _("تم بدء جلسة الجرد بنجاح. يرجى إدخال الكميات الفعلية."))
            return redirect("inventory:adjustment_count", pk=self.object.pk)
        except ValidationError as e:
            form.add_error(None, e)
            return self.form_invalid(form)
        except Exception as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("بدء جرد جديد")
        context["active_section"] = "inventory_operations"
        return context


class InventoryAdjustmentUpdateView(LoginRequiredMixin, UpdateView):
    """
    Screen to enter counted quantities.
    """
    model = InventoryAdjustment
    template_name = "inventory/adjustments/count.html"
    fields = ["note"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['lines_formset'] = InventoryCountFormSet(self.request.POST, instance=self.object)
        else:
            context['lines_formset'] = InventoryCountFormSet(instance=self.object)

        context["active_section"] = "inventory_operations"
        return context

    def form_valid(self, form):
        context = self.get_context_data()
        lines_formset = context['lines_formset']

        if lines_formset.is_valid():
            with transaction.atomic():
                self.object = form.save(commit=False)
                self.object.updated_by = self.request.user

                if self.object.status == InventoryAdjustment.Status.DRAFT:
                    self.object.status = InventoryAdjustment.Status.IN_PROGRESS

                self.object.save()
                lines_formset.save()

                # ✅ Audit Log for Data Entry
                # تسجيل عملية إدخال الكميات
                log_event(
                    action=AuditLog.Action.UPDATE,
                    message=f"Inventory Counts Updated for #{self.object.pk}",
                    actor=self.request.user,
                    target=self.object
                )

            messages.success(self.request, _("تم حفظ الكميات المجرودة."))
            return redirect("inventory:adjustment_detail", pk=self.object.pk)

        messages.error(self.request, _("يوجد خطأ في البيانات المدخلة."))
        return self.render_to_response(self.get_context_data(form=form))


class InventoryAdjustmentDetailView(LoginRequiredMixin, DetailView):
    model = InventoryAdjustment
    template_name = "inventory/adjustments/detail.html"
    context_object_name = "adjustment"

    def get_queryset(self):
        return super().get_queryset().with_related()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_operations"
        context["diff_lines"] = self.object.lines.with_difference()
        return context


@require_POST
@login_required
def apply_adjustment_view(request, pk):
    adjustment = get_object_or_404(InventoryAdjustment, pk=pk)
    try:
        # Service handles Logic + Audit (Moves Generation)
        apply_inventory_adjustment(adjustment, user=request.user)
        messages.success(request, _("تم ترحيل الجرد وتعديل الأرصدة وإنشاء الحركات اللازمة."))
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    except Exception as e:
        messages.error(request, _("حدث خطأ غير متوقع: ") + str(e))

    return redirect("inventory:adjustment_detail", pk=pk)


# ============================================================
# Reports & Analysis
# ============================================================

class StockLevelListView(LoginRequiredMixin, ListView):
    model = StockLevel
    template_name = "inventory/stock_level/list.html"
    context_object_name = "levels"
    paginate_by = 50

    def get_queryset(self):
        qs = StockLevel.objects.with_related().exclude(
            quantity_on_hand=0, quantity_reserved=0
        )

        warehouse_id = self.request.GET.get("warehouse")
        product_query = self.request.GET.get("q")

        if warehouse_id:
            qs = qs.filter(warehouse_id=warehouse_id)
        if product_query:
            qs = qs.filter(product__name__icontains=product_query)

        return qs.order_by("warehouse__name", "product__name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_reports"
        context["warehouses"] = Warehouse.objects.active()
        return context


class InventoryValuationView(LoginRequiredMixin, ListView):
    model = StockLevel
    template_name = "inventory/reports/valuation.html"
    context_object_name = "stock_items"
    paginate_by = 50

    def get_queryset(self):
        qs = StockLevel.objects.select_related(
            "product", "warehouse", "product__category", "product__base_uom"
        ).exclude(quantity_on_hand=0)

        wh_id = self.request.GET.get("warehouse")
        cat_id = self.request.GET.get("category")

        if wh_id: qs = qs.filter(warehouse_id=wh_id)
        if cat_id: qs = qs.filter(product__category_id=cat_id)

        qs = qs.annotate(valuation=F('quantity_on_hand') * F('product__average_cost'))
        return qs.order_by("-valuation")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_reports"
        context["warehouses"] = Warehouse.objects.active()
        context["categories"] = ProductCategory.objects.all()

        aggregates = self.get_queryset().aggregate(
            total_qty=Sum("quantity_on_hand"),
            total_value=Sum("valuation", output_field=DecimalField())
        )
        context["total_qty"] = aggregates["total_qty"] or 0
        context["total_value"] = aggregates["total_value"] or 0
        return context


# ============================================================
# Reorder Rules
# ============================================================

class ReorderRuleListView(LoginRequiredMixin, ListView):
    model = ReorderRule
    template_name = "inventory/reorder_rules/list.html"
    context_object_name = "rules"
    paginate_by = 50

    def get_queryset(self):
        return ReorderRule.objects.with_related().active().order_by("warehouse", "product")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_reports"
        return context


class ReorderRuleCreateView(LoginRequiredMixin, CreateView):
    model = ReorderRule
    form_class = ReorderRuleForm
    template_name = "inventory/reorder_rules/form.html"
    success_url = reverse_lazy("inventory:reorder_rule_list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("إضافة قاعدة إعادة طلب")
        context["active_section"] = "inventory_reports"
        return context


class ReorderRuleUpdateView(LoginRequiredMixin, UpdateView):
    model = ReorderRule
    form_class = ReorderRuleForm
    template_name = "inventory/reorder_rules/form.html"
    success_url = reverse_lazy("inventory:reorder_rule_list")

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("تعديل القاعدة لـ: ") + self.object.product.name
        context["active_section"] = "inventory_reports"
        return context


class ReorderRuleDeleteView(LoginRequiredMixin, DeleteView):
    model = ReorderRule
    template_name = "inventory/reorder_rules/delete.html"
    success_url = reverse_lazy("inventory:reorder_rule_list")
    context_object_name = "rule"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_reports"
        return context


# ============================================================
# Master Data (Product, Warehouse, Location, Category)
# ============================================================

# --- Products ---
class ProductListView(LoginRequiredMixin, ListView):
    model = Product
    template_name = "inventory/products/list.html"
    context_object_name = "products"
    paginate_by = 20

    def get_queryset(self):
        qs = Product.objects.with_stock_summary().with_category().active()
        query = self.request.GET.get("q")
        category = self.request.GET.get("category")

        if query:
            qs = qs.search(query)
        if category:
            qs = qs.filter(category_id=category)

        return qs.order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_master"
        context["categories"] = ProductCategory.objects.all()
        return context


class ProductCreateView(LoginRequiredMixin, CreateView):
    model = Product
    form_class = ProductForm
    template_name = "inventory/products/form.html"

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        # Optional: Log Product Creation
        return response

    def get_success_url(self):
        return reverse("inventory:product_detail", kwargs={"code": self.object.code})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("إضافة منتج جديد")
        context["active_section"] = "inventory_master"
        return context


class ProductUpdateView(LoginRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = "inventory/products/form.html"
    slug_field = "code"
    slug_url_kwarg = "code"

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("inventory:product_detail", kwargs={"code": self.object.code})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("تعديل منتج: ") + str(self.object.code)
        context["active_section"] = "inventory_master"
        return context


class ProductDetailView(LoginRequiredMixin, DetailView):
    model = Product
    template_name = "inventory/products/detail.html"
    context_object_name = "product"

    def get_object(self, queryset=None):
        if queryset is None: queryset = self.get_queryset()
        code = self.kwargs.get("code")
        return get_object_or_404(queryset.with_stock_summary().with_category(), code=code)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_master"
        context["recent_moves"] = (
            StockMove.objects.for_product(self.object)
            .with_related()
            .not_cancelled()
            .order_by("-move_date", "-id")[:10]
        )
        return context


class ProductDeleteView(LoginRequiredMixin, ProtectedDeleteMixin, DeleteView):
    model = Product
    template_name = "inventory/products/delete.html"
    success_url = reverse_lazy("inventory:product_list")
    slug_field = "code"
    slug_url_kwarg = "code"


# --- Warehouses ---
class WarehouseListView(LoginRequiredMixin, ListView):
    model = Warehouse
    template_name = "inventory/warehouse/list.html"
    context_object_name = "warehouses"

    def get_queryset(self):
        return Warehouse.objects.active().with_total_qty().order_by("code")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_master"
        return context


class WarehouseCreateView(LoginRequiredMixin, CreateView):
    model = Warehouse
    form_class = WarehouseForm
    template_name = "inventory/warehouse/form.html"
    success_url = reverse_lazy("inventory:warehouse_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("إضافة مستودع جديد")
        context["active_section"] = "inventory_master"
        return context


class WarehouseUpdateView(LoginRequiredMixin, UpdateView):
    model = Warehouse
    form_class = WarehouseForm
    template_name = "inventory/warehouse/form.html"
    success_url = reverse_lazy("inventory:warehouse_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("تعديل المستودع: ") + self.object.name
        context["active_section"] = "inventory_master"
        return context


class WarehouseDeleteView(LoginRequiredMixin, ProtectedDeleteMixin, DeleteView):
    model = Warehouse
    template_name = "inventory/warehouse/delete.html"
    success_url = reverse_lazy("inventory:warehouse_list")


# --- Categories ---
class ProductCategoryListView(LoginRequiredMixin, ListView):
    model = ProductCategory
    template_name = "inventory/categories/list.html"
    context_object_name = "categories"

    def get_queryset(self):
        return ProductCategory.objects.select_related("parent").with_products_count().order_by("parent__name", "name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_master"
        return context


class ProductCategoryCreateView(LoginRequiredMixin, CreateView):
    model = ProductCategory
    form_class = ProductCategoryForm
    template_name = "inventory/categories/form.html"
    success_url = reverse_lazy("inventory:category_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("إضافة تصنيف جديد")
        context["active_section"] = "inventory_master"
        return context


class ProductCategoryUpdateView(LoginRequiredMixin, UpdateView):
    model = ProductCategory
    form_class = ProductCategoryForm
    template_name = "inventory/categories/form.html"
    success_url = reverse_lazy("inventory:category_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("تعديل التصنيف: ") + self.object.name
        context["active_section"] = "inventory_master"
        return context


class ProductCategoryDeleteView(LoginRequiredMixin, ProtectedDeleteMixin, DeleteView):
    model = ProductCategory
    template_name = "inventory/categories/delete.html"
    success_url = reverse_lazy("inventory:category_list")


# --- Locations ---
class StockLocationListView(LoginRequiredMixin, ListView):
    model = StockLocation
    template_name = "inventory/locations/list.html"
    context_object_name = "locations"

    def get_queryset(self):
        qs = StockLocation.objects.select_related("warehouse").all()
        wh_id = self.request.GET.get("warehouse")
        if wh_id: qs = qs.filter(warehouse_id=wh_id)
        return qs.order_by("warehouse__name", "code")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_master"
        return context


class StockLocationCreateView(LoginRequiredMixin, CreateView):
    model = StockLocation
    form_class = StockLocationForm
    template_name = "inventory/locations/form.html"
    success_url = reverse_lazy("inventory:location_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("إضافة موقع تخزين")
        context["active_section"] = "inventory_master"
        return context


class StockLocationUpdateView(LoginRequiredMixin, UpdateView):
    model = StockLocation
    form_class = StockLocationForm
    template_name = "inventory/locations/form.html"
    success_url = reverse_lazy("inventory:location_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("تعديل الموقع: ") + self.object.name
        context["active_section"] = "inventory_master"
        return context


class StockLocationDeleteView(LoginRequiredMixin, ProtectedDeleteMixin, DeleteView):
    model = StockLocation
    template_name = "inventory/locations/delete.html"
    success_url = reverse_lazy("inventory:location_list")


# ============================================================
# Settings & Import/Export
# ============================================================

class InventorySettingsView(LoginRequiredMixin, UpdateView):
    model = InventorySettings
    template_name = "inventory/settings/settings.html"
    fields = ["allow_negative_stock", "stock_move_in_prefix", "stock_move_out_prefix", "stock_move_transfer_prefix"]
    success_url = "."

    def get_object(self, queryset=None):
        return InventorySettings.get_solo()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_settings"
        return context


@login_required
def export_products_view(request):
    product_resource = ProductResource()
    dataset = product_resource.export()
    response = HttpResponse(
        dataset.xlsx,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    timestamp = timezone.now().strftime("%Y-%m-%d")
    response['Content-Disposition'] = f'attachment; filename="products_export_{timestamp}.xlsx"'
    return response


@login_required
def import_products_view(request):
    errors = []
    if request.method == 'POST':
        product_resource = ProductResource()
        dataset = Dataset()

        if 'import_file' not in request.FILES:
            messages.error(request, _("الرجاء اختيار ملف."))
            return redirect('inventory:product_import')

        new_products = request.FILES['import_file']

        if not new_products.name.endswith('xlsx'):
            messages.error(request, _("عفواً، الصيغة المدعومة هي xlsx فقط."))
            return redirect('inventory:product_import')

        try:
            imported_data = dataset.load(new_products.read(), format='xlsx')
            result = product_resource.import_data(dataset, dry_run=True)

            if not result.has_errors():
                product_resource.import_data(dataset, dry_run=False)
                messages.success(request, _("تم استيراد المنتجات بنجاح!"))
                return redirect('inventory:product_list')
            else:
                for i, row in enumerate(result.rows):
                    if row.errors:
                        for err in row.errors:
                            line_num = i + 2
                            err_msg = str(err.error)
                            if "matching query does not exist" in err_msg:
                                if "ProductCategory" in err_msg:
                                    err_msg = _("التصنيف المحدد غير موجود.")
                                elif "UnitOfMeasure" in err_msg:
                                    err_msg = _("وحدة القياس المحددة غير موجودة.")
                            errors.append(f"سطر {line_num}: {err_msg}")

                messages.error(request, _("فشلت العملية. يرجى مراجعة قائمة الأخطاء أدناه."))

        except Exception as e:
            messages.error(request, f"حدث خطأ غير متوقع: {str(e)}")

    return render(request, 'inventory/products/import_form.html', {'import_errors': errors})