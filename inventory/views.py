# inventory/views.py

from django.views.generic import ListView, DetailView, CreateView, TemplateView, UpdateView
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.http import Http404
from django.db import transaction
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError

from .models import StockMove, Product, Warehouse, StockLevel, ReorderRule, InventorySettings, StockLocation, \
    ProductCategory, InventoryAdjustment
from .forms import ReceiptMoveForm, DeliveryMoveForm, TransferMoveForm, StockMoveLineFormSet, WarehouseForm, \
    ProductForm, StockLocationForm, ProductCategoryForm, InventoryCountFormSet, StartInventoryForm
from .services import confirm_stock_move, cancel_stock_move, apply_inventory_adjustment, create_inventory_session

# ============================================================
# خريطة إعدادات أنواع الحركات (Configuration Map)
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
# Mixins (أدوات مساعدة للكلاسات)
# ============================================================

class StockMoveContextMixin:
    """
    ميكسن لتجهيز سياق القالب (العناوين، الألوان) والتحقق من نوع الحركة.
    """
    move_type = None

    def dispatch(self, request, *args, **kwargs):
        # 1. التقاط نوع الحركة من الرابط (kwargs)
        self.move_type = kwargs.get("move_type")

        # 2. تحقق صارم: إذا تم تمرير نوع حركة، يجب أن يكون صحيحاً
        if self.move_type and self.move_type not in MOVE_TYPE_META:
            raise Http404(_("نوع حركة المخزون غير صحيح."))

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # تحديد النوع الحالي (إما من الرابط أو من الكائن نفسه في صفحة التفاصيل)
        current_type = self.move_type
        if not current_type and hasattr(self, 'object') and self.object:
            current_type = self.object.move_type

        # جلب الإعدادات من الخريطة
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
        context["active_section"] = "inventory_operations"  # لتظليل النافبار
        return context


# ============================================================
# Views: العمليات (Operations)
# ============================================================

class StockMoveListView(LoginRequiredMixin, StockMoveContextMixin, ListView):
    model = StockMove
    template_name = "inventory/stock_move/list.html"
    context_object_name = "moves"
    paginate_by = 20

    def get_queryset(self):
        # ✅ الأداء: جلب العلاقات + استبعاد الملغاة + الترتيب الأحدث أولاً
        qs = super().get_queryset().with_related().not_cancelled().order_by("-move_date", "-id")

        # الفلترة حسب النوع الممرر في الرابط
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
        # اختيار الفورم المناسب ديناميكياً
        meta = MOVE_TYPE_META.get(self.move_type)
        return meta["form_class"] if meta else ReceiptMoveForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # تهيئة Formset للبنود
        if self.request.POST:
            context['lines_formset'] = StockMoveLineFormSet(self.request.POST)
        else:
            context['lines_formset'] = StockMoveLineFormSet()
        return context

    def form_valid(self, form):
        context = self.get_context_data()
        lines_formset = context['lines_formset']

        # 1. حقن نوع الحركة تلقائياً
        form.instance.move_type = self.move_type

        # 2. التحقق من صحة البنود
        if not lines_formset.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        # 3. الحفظ داخل معاملة ذرية (Transaction)
        with transaction.atomic():
            self.object = form.save()  # حفظ الهيدر
            lines_formset.instance = self.object  # ربط البنود بالهيدر
            lines_formset.save()  # حفظ البنود

        messages.success(self.request, _("تم إنشاء الحركة بنجاح كمسودة."))
        return redirect(self.get_success_url())

    def get_success_url(self):
        meta = MOVE_TYPE_META.get(self.move_type)
        return reverse(meta["list_url"])


class StockMoveDetailView(LoginRequiredMixin, StockMoveContextMixin, DetailView):
    model = StockMove
    template_name = "inventory/stock_move/detail.html"
    context_object_name = "move"

    def get_queryset(self):
        return super().get_queryset().with_related()


# ============================================================
# Views: الإجراءات (Actions: Confirm/Cancel)
# ============================================================

@require_POST
@login_required
def confirm_move_view(request, pk):
    move = get_object_or_404(StockMove, pk=pk)
    try:
        confirm_stock_move(move, user=request.user)
        messages.success(request, _("تم تأكيد حركة المخزون وتحديث الأرصدة بنجاح."))

    except ValidationError as e:
        # أخطاء منطقية (مثل: رصيد غير كافٍ)
        messages.error(request, " ".join(e.messages))
    except Exception:
        # أخطاء غير متوقعة
        messages.error(request, _("حدث خطأ غير متوقع أثناء المعالجة."))

    return redirect("inventory:move_detail", pk=pk)


@require_POST
@login_required
def cancel_move_view(request, pk):
    move = get_object_or_404(StockMove, pk=pk)
    try:
        cancel_stock_move(move, user=request.user)
        messages.warning(request, _("تم إلغاء حركة المخزون."))

    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    except Exception:
        messages.error(request, _("حدث خطأ غير متوقع أثناء الإلغاء."))

    return redirect("inventory:move_detail", pk=pk)


# ============================================================
# Views: التقارير والبيانات الأساسية (Reporting & Master Data)
# ============================================================

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "inventory/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_dashboard"

        # إحصائيات سريعة
        context["total_products"] = Product.objects.active().count()
        context["low_stock_count"] = StockLevel.objects.below_min().count()
        context["draft_moves_count"] = StockMove.objects.draft().count()

        # آخر 5 حركات (غير ملغاة)
        context["latest_moves"] = (
            StockMove.objects
            .with_related()
            .not_cancelled()
            .order_by("-move_date", "-id")[:5]
        )
        return context


class StockLevelListView(LoginRequiredMixin, ListView):
    model = StockLevel
    template_name = "inventory/stock_level_list.html"
    context_object_name = "levels"
    paginate_by = 50

    def get_queryset(self):
        # 1. القائمة الأساسية (استبعاد الأصفار + جلب العلاقات)
        qs = StockLevel.objects.with_related().exclude(
            quantity_on_hand=0, quantity_reserved=0
        )

        # 2. ✅ (Bonus) دعم الفلترة حسب المستودع من الرابط
        # الرابط يأتي كـ: ?warehouse=3
        warehouse_id = self.request.GET.get("warehouse")
        if warehouse_id:
            qs = qs.filter(warehouse_id=warehouse_id)

        # 3. ✅ (Fix) حل مشكلة الترتيب UnorderedObjectListWarning
        # نرتب حسب اسم المستودع أولاً ثم اسم المنتج
        return qs.order_by("warehouse__name", "product__name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_reports"
        return context


class ReorderRuleListView(LoginRequiredMixin, ListView):
    model = ReorderRule
    template_name = "inventory/reorder_rule_list.html"
    context_object_name = "rules"
    paginate_by = 50

    def get_queryset(self):
        return ReorderRule.objects.with_related().active().order_by("warehouse", "product")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_reports"
        return context


class ProductListView(LoginRequiredMixin, ListView):
    model = Product
    template_name = "inventory/products/list.html"
    context_object_name = "products"
    paginate_by = 20

    def get_queryset(self):
        # استخدام المانجر: active + summary + category relation
        qs = Product.objects.with_stock_summary().with_category().active()

        # دعم البحث البسيط
        query = self.request.GET.get("q")
        if query:
            qs = qs.search(query)

        return qs.order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_master"
        return context


class ProductDetailView(LoginRequiredMixin, DetailView):
    model = Product
    template_name = "inventory/products/detail.html"
    context_object_name = "product"

    def get_object(self, queryset=None):
        if queryset is None:
            queryset = self.get_queryset()
        # البحث بالكود (Code)
        code = self.kwargs.get("code")
        return get_object_or_404(
            queryset.with_stock_summary().with_category(),
            code=code
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_master"

        # آخر 10 حركات لهذا المنتج
        context["recent_moves"] = (
            StockMove.objects
            .for_product(self.object)
            .with_related()
            .not_cancelled()
            .order_by("-move_date", "-id")[:10]
        )
        return context


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


class InventorySettingsView(LoginRequiredMixin, UpdateView):
    model = InventorySettings
    template_name = "inventory/settings.html"
    fields = ["allow_negative_stock", "stock_move_in_prefix", "stock_move_out_prefix", "stock_move_transfer_prefix"]
    success_url = "."  # البقاء في نفس الصفحة

    def get_object(self, queryset=None):
        return InventorySettings.get_solo()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_settings"
        return context


# ============================================================
# إدارة المنتجات (Create / Update)
# ============================================================

class ProductCreateView(LoginRequiredMixin, CreateView):
    model = Product
    form_class = ProductForm
    template_name = "inventory/products/form.html"

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

    # لأننا نستخدم code في الرابط بدلاً من pk
    slug_field = "code"
    slug_url_kwarg = "code"

    def get_success_url(self):
        return reverse("inventory:product_detail", kwargs={"code": self.object.code})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("تعديل منتج: ") + self.object.code
        context["active_section"] = "inventory_master"
        return context


# ============================================================
# إدارة المستودعات (Create / Update)
# ============================================================

class WarehouseCreateView(LoginRequiredMixin, CreateView):
    model = Warehouse
    form_class = WarehouseForm
    template_name = "inventory/warehouse/form.html"
    success_url = "/inventory/warehouses/"  # أو استخدام reverse_lazy

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("إضافة مستودع جديد")
        context["active_section"] = "inventory_master"
        return context


class WarehouseUpdateView(LoginRequiredMixin, UpdateView):
    model = Warehouse
    form_class = WarehouseForm
    template_name = "inventory/warehouse/form.html"
    success_url = "/inventory/warehouses/"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("تعديل المستودع: ") + self.object.name
        context["active_section"] = "inventory_master"
        return context


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
    success_url = "/inventory/categories/"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("إضافة تصنيف جديد")
        context["active_section"] = "inventory_master"
        return context


class ProductCategoryUpdateView(LoginRequiredMixin, UpdateView):
    model = ProductCategory
    form_class = ProductCategoryForm
    template_name = "inventory/categories/form.html"
    success_url = "/inventory/categories/"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("تعديل التصنيف: ") + self.object.name
        context["active_section"] = "inventory_master"
        return context


# ============================================================
# إدارة مواقع التخزين (Stock Locations)
# ============================================================

class StockLocationListView(LoginRequiredMixin, ListView):
    model = StockLocation
    template_name = "inventory/locations/list.html"
    context_object_name = "locations"

    def get_queryset(self):
        qs = StockLocation.objects.select_related("warehouse").all()
        # فلترة حسب المستودع إذا تم تمريره
        wh_id = self.request.GET.get("warehouse")
        if wh_id:
            qs = qs.filter(warehouse_id=wh_id)
        return qs.order_by("warehouse__name", "code")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_master"
        return context


class StockLocationCreateView(LoginRequiredMixin, CreateView):
    model = StockLocation
    form_class = StockLocationForm
    template_name = "inventory/locations/form.html"
    success_url = "/inventory/locations/"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("إضافة موقع تخزين")
        context["active_section"] = "inventory_master"
        return context


class StockLocationUpdateView(LoginRequiredMixin, UpdateView):
    model = StockLocation
    form_class = StockLocationForm
    template_name = "inventory/locations/form.html"
    success_url = "/inventory/locations/"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("تعديل الموقع: ") + self.object.name
        context["active_section"] = "inventory_master"
        return context


# ============================================================
# إدارة تسوية الجرد (Inventory Adjustment)
# ============================================================

class InventoryAdjustmentListView(LoginRequiredMixin, ListView):
    model = InventoryAdjustment
    template_name = "inventory/adjustments/list.html"
    context_object_name = "adjustments"
    paginate_by = 20

    def get_queryset(self):
        return InventoryAdjustment.objects.select_related("warehouse").order_by("-date", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_operations"
        return context


class InventoryAdjustmentCreateView(LoginRequiredMixin, CreateView):
    """بدء جلسة جرد جديدة (Wizard Step 1)"""
    model = InventoryAdjustment
    form_class = StartInventoryForm
    template_name = "inventory/adjustments/form.html"

    def form_valid(self, form):
        # بدلاً من الحفظ المباشر، نستدعي السيرفس لأخذ اللقطة
        try:
            self.object = create_inventory_session(
                warehouse=form.cleaned_data["warehouse"],
                user=self.request.user,
                category=form.cleaned_data["category"],
                location=form.cleaned_data["location"],
                note=form.cleaned_data["note"]
            )
            messages.success(self.request, _("تم بدء جلسة الجرد بنجاح. يرجى إدخال الكميات الفعلية."))
            return redirect("inventory:adjustment_count", pk=self.object.pk)
        except Exception as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("بدء جرد جديد")
        context["active_section"] = "inventory_operations"
        return context


class InventoryAdjustmentUpdateView(LoginRequiredMixin, UpdateView):
    """شاشة إدخال العد (Wizard Step 2)"""
    model = InventoryAdjustment
    template_name = "inventory/adjustments/count.html"
    fields = ["note"]  # حقل وهمي لأننا نستخدم Formset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['lines_formset'] = InventoryCountFormSet(self.request.POST, instance=self.object)
        else:
            # عرض الأسطر مرتبة بالموقع ثم المنتج لتسهيل العد
            # ملاحظة: Formset يستخدم الـ Manager الافتراضي، للترتيب قد نحتاج override queryset في الـ formset،
            # ولكن للتبسيط الآن سيعرضهم حسب الإنشاء.
            context['lines_formset'] = InventoryCountFormSet(instance=self.object)

        context["active_section"] = "inventory_operations"
        return context

    def form_valid(self, form):
        context = self.get_context_data()
        lines_formset = context['lines_formset']

        if lines_formset.is_valid():
            lines_formset.save()
            # تحديث الحالة إلى "قيد المراجعة" إذا كانت مسودة
            if self.object.status == InventoryAdjustment.Status.DRAFT:
                self.object.status = InventoryAdjustment.Status.IN_PROGRESS
                self.object.save(update_fields=["status"])

            messages.success(self.request, _("تم حفظ الكميات المجرودة."))
            return redirect("inventory:adjustment_detail", pk=self.object.pk)

        return self.render_to_response(self.get_context_data(form=form))


class InventoryAdjustmentDetailView(LoginRequiredMixin, DetailView):
    """شاشة المراجعة والتنفيذ (Wizard Step 3)"""
    model = InventoryAdjustment
    template_name = "inventory/adjustments/detail.html"
    context_object_name = "adjustment"

    def get_queryset(self):
        return super().get_queryset().select_related("warehouse")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_operations"
        return context


@require_POST
@login_required
def apply_adjustment_view(request, pk):
    adjustment = get_object_or_404(InventoryAdjustment, pk=pk)
    try:
        apply_inventory_adjustment(adjustment, user=request.user)
        messages.success(request, _("تم ترحيل الجرد وتعديل الأرصدة بنجاح."))
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    except Exception as e:
        messages.error(request, _("حدث خطأ غير متوقع: ") + str(e))

    return redirect("inventory:adjustment_detail", pk=pk)