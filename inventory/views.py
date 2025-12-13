# /home/ubuntu/PycharmProjects/mazoonaluminum.com/inventory/views.py

from __future__ import annotations

from typing import Optional

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import DecimalField, F, Prefetch, Q, Sum
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from tablib import Dataset

# Core (Audit)
from core.models import AuditLog
from core.services.audit import log_event

# Forms
from .forms import (
    DeliveryMoveForm,
    InventoryAdjustmentLineFormSet,
    InventoryAdjustmentStartForm,
    ProductCategoryForm,
    ProductForm,
    ReceiptMoveForm,
    ReorderRuleForm,
    StockLocationForm,
    StockMoveLineFormSet,
    TransferMoveForm,
    WarehouseForm,
)

# Models
from .models import (
    DECIMAL_ZERO,
    InventoryAdjustment,
    InventorySettings,
    Product,
    ProductCategory,
    ReorderRule,
    StockLevel,
    StockLocation,
    StockMove,
    StockMoveLine,
    Warehouse,
)

# Resources (django-import-export)
from .resources import ProductResource

# Services (Business logic + audit + notifications)
from .services import (
    apply_inventory_adjustment,
    cancel_stock_move,
    confirm_stock_move,
    create_inventory_session,
)

# Utils
from .utils import render_pdf_view


# ============================================================
# Configuration
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
    Injects move-type metadata into context.

    - move_type can come from:
      1) extra kwargs passed by URL pattern (kwargs["move_type"])
      2) class attribute (self.move_type)
      3) object.move_type (DetailView etc.)
    """

    move_type: Optional[str] = None

    def dispatch(self, request, *args, **kwargs):
        self.move_type = kwargs.get("move_type") or getattr(self, "move_type", None)
        return super().dispatch(request, *args, **kwargs)

    def _resolve_move_type_for_context(self) -> Optional[str]:
        if self.move_type:
            return self.move_type
        obj = getattr(self, "object", None)
        if obj is not None:
            return getattr(obj, "move_type", None)
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_type = self._resolve_move_type_for_context()

        meta = MOVE_TYPE_META.get(current_type)
        if meta:
            context.update(
                page_title=meta["title"],
                move_type_label=meta["label"],
                move_type_color=meta["color"],
                create_url=reverse(meta["create_url"]),
                list_url=reverse(meta["list_url"]),
            )

        context["current_move_type"] = current_type
        context["active_section"] = context.get("active_section") or "inventory_operations"
        return context


class ProtectedDeleteMixin:
    """
    Prevents 500 errors when deleting protected objects; shows a friendly message.
    """

    def post(self, request, *args, **kwargs):
        try:
            return super().delete(request, *args, **kwargs)
        except ProtectedError:
            messages.error(
                request,
                _("لا يمكن حذف هذا السجل لأنه مرتبط ببيانات أخرى (مثل حركات مخزنية). يفضل تعطيله/أرشفته بدلاً من الحذف."),
            )
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

        try:
            context["low_stock_count"] = len(ReorderRule.objects.get_triggered_rules())
        except Exception:
            context["low_stock_count"] = ReorderRule.objects.active().count()

        context["draft_moves_count"] = StockMove.objects.draft().count()

        context["latest_moves"] = (
            StockMove.objects.with_related()
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
        qs = StockMove.objects.with_related().order_by("-move_date", "-id")

        if self.move_type == StockMove.MoveType.IN:
            return qs.incoming()
        if self.move_type == StockMove.MoveType.OUT:
            return qs.outgoing()
        if self.move_type == StockMove.MoveType.TRANSFER:
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
        # Create a new draft instance only on GET
        if self.request.method == "GET":
            kwargs.setdefault("instance", StockMove(move_type=self.move_type))
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_operations"

        if self.request.POST:
            context["lines_formset"] = StockMoveLineFormSet(self.request.POST)
        else:
            context["lines_formset"] = StockMoveLineFormSet()

        return context

    def form_valid(self, form):
        context = self.get_context_data()
        lines_formset = context["lines_formset"]

        # Stamping
        form.instance.move_type = self.move_type
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user

        if not lines_formset.is_valid():
            messages.error(self.request, _("الرجاء التحقق من بيانات الأصناف."))
            return self.render_to_response(self.get_context_data(form=form))

        try:
            with transaction.atomic():
                self.object = form.save()
                lines_formset.instance = self.object
                lines_formset.save()

                # Audit: draft creation (confirm/cancel handled by services)
                log_event(
                    action=AuditLog.Action.CREATE,
                    message=_("Draft stock move created."),
                    actor=self.request.user,
                    target=self.object,
                    extra={
                        "move_type": str(self.object.move_type),
                        "reference": str(self.object.reference or ""),
                    },
                )

            messages.success(self.request, _("تم إنشاء الحركة كمسودة (Draft) بنجاح."))
            return redirect(self.get_success_url())

        except ValidationError as e:
            messages.error(self.request, " ".join(e.messages))
            return self.render_to_response(self.get_context_data(form=form))

        except Exception as e:
            messages.error(self.request, _("حدث خطأ أثناء الحفظ: ") + str(e))
            return self.render_to_response(self.get_context_data(form=form))

    def get_success_url(self):
        return reverse("inventory:move_detail", kwargs={"pk": self.object.pk})


class StockMoveDetailView(LoginRequiredMixin, StockMoveContextMixin, DetailView):
    model = StockMove
    template_name = "inventory/stock_move/detail.html"
    context_object_name = "move"

    def get_queryset(self):
        return StockMove.objects.with_related()


# ============================================================
# Move Actions (Service Integration)
# ============================================================

@require_POST
@login_required
def confirm_move_view(request, pk: int):
    move = get_object_or_404(StockMove, pk=pk)
    try:
        confirm_stock_move(move, user=request.user)
        messages.success(request, _("تم تأكيد الحركة المخزنية وتحديث الأرصدة."))
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    except Exception as e:
        messages.error(request, _("حدث خطأ غير متوقع: ") + str(e))
    return redirect("inventory:move_detail", pk=pk)


@require_POST
@login_required
def cancel_move_view(request, pk: int):
    move = get_object_or_404(StockMove, pk=pk)
    try:
        cancel_stock_move(move, user=request.user)
        messages.warning(request, _("تم إلغاء الحركة المخزنية وعكس تأثيرها."))
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    except Exception as e:
        messages.error(request, _("حدث خطأ غير متوقع: ") + str(e))
    return redirect("inventory:move_detail", pk=pk)


@login_required
def stock_move_pdf_view(request, pk: int):
    move = get_object_or_404(StockMove.objects.with_related(), pk=pk)

    doc_meta = {
        StockMove.MoveType.IN: ("GRN", _("سند استلام مخزني")),
        StockMove.MoveType.OUT: ("DN", _("إذن صرف بضاعة")),
        StockMove.MoveType.TRANSFER: ("TN", _("سند تحويل داخلي")),
    }
    doc_type, doc_title = doc_meta.get(move.move_type, ("MOV", _("حركة مخزنية")))

    context = {
        "move": move,
        "lines": move.lines.select_related("product", "uom").all(),
        "doc_title": doc_title,
        "doc_type": doc_type,
        "company_name": "Mazoon Aluminum",
        "print_date": timezone.now(),
        "user": request.user,
    }

    filename = f"{doc_type}-{move.reference or move.pk}.pdf"
    return render_pdf_view(request, "inventory/pdf/stock_move_document.html", context, filename)


# ============================================================
# Inventory Adjustments
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
    form_class = InventoryAdjustmentStartForm
    template_name = "inventory/adjustments/form.html"

    def form_valid(self, form):
        try:
            self.object = create_inventory_session(
                warehouse=form.cleaned_data["warehouse"],
                user=self.request.user,
                category=form.cleaned_data.get("category"),
                location=form.cleaned_data.get("location"),
                note=form.cleaned_data.get("note") or "",
            )
            messages.success(self.request, _("تم بدء جلسة الجرد بنجاح. يرجى إدخال الكميات الفعلية."))
            return redirect("inventory:adjustment_count", pk=self.object.pk)
        except ValidationError as e:
            form.add_error(None, " ".join(e.messages))
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
    Screen to enter counted quantities (via inline formset).
    """
    model = InventoryAdjustment
    template_name = "inventory/adjustments/count.html"
    fields = ["note"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_operations"

        if self.request.POST:
            context["lines_formset"] = InventoryAdjustmentLineFormSet(self.request.POST, instance=self.object)
        else:
            context["lines_formset"] = InventoryAdjustmentLineFormSet(instance=self.object)

        return context

    def form_valid(self, form):
        context = self.get_context_data()
        lines_formset = context["lines_formset"]

        if not lines_formset.is_valid():
            messages.error(self.request, _("يوجد خطأ في البيانات المدخلة."))
            return self.render_to_response(self.get_context_data(form=form))

        try:
            with transaction.atomic():
                self.object = form.save(commit=False)
                self.object.updated_by = self.request.user

                if self.object.status == InventoryAdjustment.Status.DRAFT:
                    self.object.status = InventoryAdjustment.Status.IN_PROGRESS

                self.object.save(update_fields=["note", "status", "updated_by"])
                lines_formset.save()

                # Audit: counts entry (apply handled by service)
                log_event(
                    action=AuditLog.Action.UPDATE,
                    message=_("Inventory counts updated."),
                    actor=self.request.user,
                    target=self.object,
                    extra={"status": str(self.object.status)},
                )

            messages.success(self.request, _("تم حفظ الكميات المجرودة."))
            return redirect("inventory:adjustment_detail", pk=self.object.pk)

        except Exception as e:
            messages.error(self.request, _("حدث خطأ أثناء الحفظ: ") + str(e))
            return self.render_to_response(self.get_context_data(form=form))


class InventoryAdjustmentDetailView(LoginRequiredMixin, DetailView):
    model = InventoryAdjustment
    template_name = "inventory/adjustments/detail.html"
    context_object_name = "adjustment"

    def get_queryset(self):
        return InventoryAdjustment.objects.with_related()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_operations"

        try:
            context["diff_lines"] = self.object.lines.with_difference()
        except Exception:
            context["diff_lines"] = self.object.lines.all()

        return context


@require_POST
@login_required
def apply_adjustment_view(request, pk: int):
    adjustment = get_object_or_404(InventoryAdjustment, pk=pk)
    try:
        apply_inventory_adjustment(adjustment, user=request.user)
        messages.success(request, _("تم ترحيل الجرد وتعديل الأرصدة وإنشاء الحركات اللازمة."))
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    except Exception as e:
        messages.error(request, _("حدث خطأ غير متوقع: ") + str(e))
    return redirect("inventory:adjustment_detail", pk=pk)


# ============================================================
# Reports
# ============================================================

class StockLevelListView(LoginRequiredMixin, ListView):
    model = StockLevel
    template_name = "inventory/stock_level/list.html"
    context_object_name = "levels"
    paginate_by = 50

    def get_queryset(self):
        qs = StockLevel.objects.with_related().exclude(quantity_on_hand=0, quantity_reserved=0)

        warehouse_id = self.request.GET.get("warehouse")
        q = (self.request.GET.get("q") or "").strip()

        if warehouse_id:
            qs = qs.filter(warehouse_id=warehouse_id)

        if q:
            qs = qs.filter(
                Q(product__name__icontains=q)
                | Q(product__code__icontains=q)
                | Q(location__name__icontains=q)
                | Q(warehouse__name__icontains=q)
            )

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
        qs = (
            StockLevel.objects.select_related(
                "product",
                "warehouse",
                "product__category",
                "product__base_uom",
            )
            .exclude(quantity_on_hand=0)
        )

        wh_id = self.request.GET.get("warehouse")
        cat_id = self.request.GET.get("category")

        if wh_id:
            qs = qs.filter(warehouse_id=wh_id)
        if cat_id:
            qs = qs.filter(product__category_id=cat_id)

        qs = qs.annotate(valuation=F("quantity_on_hand") * F("product__average_cost"))
        return qs.order_by("-valuation")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_reports"
        context["warehouses"] = Warehouse.objects.active()
        context["categories"] = ProductCategory.objects.all()

        qs = self.get_queryset()
        aggregates = qs.aggregate(
            total_qty=Sum("quantity_on_hand"),
            total_value=Sum("valuation", output_field=DecimalField()),
        )

        context["total_qty"] = aggregates["total_qty"] or DECIMAL_ZERO
        context["total_value"] = aggregates["total_value"] or DECIMAL_ZERO
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
        form.instance.updated_by = self.request.user
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
        context["page_title"] = _("تعديل القاعدة لـ: ") + str(self.object.product.name)
        context["active_section"] = "inventory_reports"
        return context


class ReorderRuleDeleteView(LoginRequiredMixin, ProtectedDeleteMixin, DeleteView):
    model = ReorderRule
    template_name = "inventory/reorder_rules/delete.html"
    success_url = reverse_lazy("inventory:reorder_rule_list")
    context_object_name = "rule"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_reports"
        return context


# ============================================================
# Master Data
# ============================================================

class ProductListView(LoginRequiredMixin, ListView):
    model = Product
    template_name = "inventory/products/list.html"
    context_object_name = "products"
    paginate_by = 20

    def get_queryset(self):
        qs = Product.objects.with_stock_summary().with_category().active()

        q = (self.request.GET.get("q") or "").strip()
        category = self.request.GET.get("category")

        if q:
            qs = qs.search(q)
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
        form.instance.updated_by = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("inventory:product_detail", kwargs={"code": self.object.code})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("إضافة منتج جديد")
        context["active_section"] = "inventory_master"
        context["cancel_url"] = reverse("inventory:product_list")
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
        context["cancel_url"] = reverse("inventory:product_detail", kwargs={"code": self.object.code})
        return context


class ProductDetailView(LoginRequiredMixin, DetailView):
    model = Product
    template_name = "inventory/products/detail.html"
    context_object_name = "product"

    def get_object(self, queryset=None):
        qs = queryset or Product.objects.all()
        code = self.kwargs.get("code")
        return get_object_or_404(qs.with_category().with_stock_summary(), code=code)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product = self.object
        context["active_section"] = "inventory_master"

        product_lines_prefetch = Prefetch(
            "lines",
            queryset=StockMoveLine.objects.filter(product=product).only("id", "move_id", "quantity"),
            to_attr="product_lines",
        )

        recent_moves = (
            StockMove.objects.for_product(product)
            .not_cancelled()
            .select_related("from_warehouse", "to_warehouse")
            .prefetch_related(product_lines_prefetch)
            .order_by("-move_date", "-id")[:10]
        )

        for move in recent_moves:
            qty = sum((line.quantity for line in getattr(move, "product_lines", [])), DECIMAL_ZERO)
            move.product_qty = qty
            move.product_qty_signed = -qty if move.move_type == StockMove.MoveType.OUT else qty

        context["recent_moves"] = recent_moves
        return context


class ProductDeleteView(LoginRequiredMixin, ProtectedDeleteMixin, DeleteView):
    model = Product
    template_name = "inventory/products/delete.html"
    success_url = reverse_lazy("inventory:product_list")
    slug_field = "code"
    slug_url_kwarg = "code"


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

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        return super().form_valid(form)

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

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("تعديل المستودع: ") + str(self.object.name)
        context["active_section"] = "inventory_master"
        return context


class WarehouseDeleteView(LoginRequiredMixin, ProtectedDeleteMixin, DeleteView):
    model = Warehouse
    template_name = "inventory/warehouse/delete.html"
    success_url = reverse_lazy("inventory:warehouse_list")


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

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        return super().form_valid(form)

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

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("تعديل التصنيف: ") + str(self.object.name)
        context["active_section"] = "inventory_master"
        return context


class ProductCategoryDeleteView(LoginRequiredMixin, ProtectedDeleteMixin, DeleteView):
    model = ProductCategory
    template_name = "inventory/categories/delete.html"
    success_url = reverse_lazy("inventory:category_list")


class StockLocationListView(LoginRequiredMixin, ListView):
    model = StockLocation
    template_name = "inventory/locations/list.html"
    context_object_name = "locations"

    def get_queryset(self):
        qs = StockLocation.objects.select_related("warehouse").all()
        wh_id = self.request.GET.get("warehouse")
        if wh_id:
            qs = qs.filter(warehouse_id=wh_id)
        return qs.order_by("warehouse__name", "code")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_master"
        context["warehouses"] = Warehouse.objects.active()
        return context


class StockLocationCreateView(LoginRequiredMixin, CreateView):
    model = StockLocation
    form_class = StockLocationForm
    template_name = "inventory/locations/form.html"
    success_url = reverse_lazy("inventory:location_list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        return super().form_valid(form)

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

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("تعديل الموقع: ") + str(self.object.name)
        context["active_section"] = "inventory_master"
        return context


class StockLocationDeleteView(LoginRequiredMixin, ProtectedDeleteMixin, DeleteView):
    model = StockLocation
    template_name = "inventory/locations/delete.html"
    success_url = reverse_lazy("inventory:location_list")


# ============================================================
# Settings
# ============================================================

class InventorySettingsView(LoginRequiredMixin, UpdateView):
    model = InventorySettings
    template_name = "inventory/settings/settings.html"
    fields = [
        "allow_negative_stock",
        "stock_move_in_prefix",
        "stock_move_out_prefix",
        "stock_move_transfer_prefix",
    ]
    success_url = "."

    def get_object(self, queryset=None):
        return InventorySettings.get_solo()

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, _("تم حفظ الإعدادات."))
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_settings"
        return context


# ============================================================
# Import/Export Products
# ============================================================

@login_required
def export_products_view(request):
    product_resource = ProductResource()
    dataset = product_resource.export()
    response = HttpResponse(
        dataset.xlsx,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    timestamp = timezone.now().strftime("%Y-%m-%d")
    response["Content-Disposition"] = f'attachment; filename="products_export_{timestamp}.xlsx"'
    return response


@login_required
def import_products_view(request):
    errors: list[str] = []

    if request.method == "POST":
        if "import_file" not in request.FILES:
            messages.error(request, _("الرجاء اختيار ملف."))
            return redirect("inventory:product_import")

        uploaded = request.FILES["import_file"]
        if not uploaded.name.endswith("xlsx"):
            messages.error(request, _("عفواً، الصيغة المدعومة هي xlsx فقط."))
            return redirect("inventory:product_import")

        product_resource = ProductResource()
        dataset = Dataset()

        try:
            dataset.load(uploaded.read(), format="xlsx")

            dry = product_resource.import_data(dataset, dry_run=True)

            if not dry.has_errors():
                product_resource.import_data(dataset, dry_run=False)
                messages.success(request, _("تم استيراد المنتجات بنجاح!"))
                return redirect("inventory:product_list")

            for i, row in enumerate(dry.rows):
                if not row.errors:
                    continue
                line_num = i + 2  # header + 1-indexed
                for err in row.errors:
                    err_msg = str(getattr(err, "error", err))

                    if "matching query does not exist" in err_msg:
                        if "ProductCategory" in err_msg:
                            err_msg = _("التصنيف المحدد غير موجود.")
                        elif "UnitOfMeasure" in err_msg:
                            err_msg = _("وحدة القياس المحددة غير موجودة.")

                    errors.append(f"{_('سطر')} {line_num}: {err_msg}")

            messages.error(request, _("فشلت العملية. يرجى مراجعة قائمة الأخطاء أدناه."))

        except Exception as e:
            messages.error(request, _("حدث خطأ غير متوقع: ") + str(e))

    return render(request, "inventory/products/import_form.html", {"import_errors": errors})
