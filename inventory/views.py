# inventory/views.py

from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db.models import Sum, Q, F, Case, When, IntegerField
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    TemplateView,
    ListView,
    DetailView,
    CreateView,
    UpdateView,
)

from core.models import AuditLog, Notification
from core.services.audit import log_event
from core.services.notifications import create_notification
from .forms import (
    StockMoveForm,
    ProductForm,
    StockLevelForm,
    ProductCategoryForm,
    InventorySettingsForm,
    StockMoveLineFormSet,
)
from .models import (
    ProductCategory,
    Product,
    Warehouse,
    StockLocation,
    StockMove,
    StockLevel,
    InventorySettings,
)
from .services import (
    get_stock_summary_per_warehouse,
    get_low_stock_levels,
    filter_below_min_stock_levels,
    get_low_stock_total,
    filter_stock_moves_queryset,
    filter_products_queryset, cancel_stock_move, confirm_stock_move,
)

User = get_user_model()


# ============================================================
# هيلبر مشترك للنوتفيكيشن في قسم المخزون
# ============================================================

def _notify_inventory_staff(
    *,
    actor,
    verb: str,
    target,
    level: str = Notification.Levels.INFO,
    url: str | None = None,
) -> None:
    """
    إرسال نوتفيكيشن لكل مستخدم ستاف في قسم النظام (ما عدا الفاعل نفسه):

    - actor: المستخدم الذي قام بالعملية (قد يكون None).
    - verb: النص الظاهر في النوتفيكيشن (قصير وواضح).
    - target: الكائن المرتبط (Product, StockMove, InventorySettings, ...).
    - level: مستوى النوتفيكيشن (info / success / warning / error).
    - url: رابط داخلي (نمرّر نتيجة reverse مباشرة).
    """
    qs = User.objects.filter(is_active=True, is_staff=True)

    # استثناء الفاعل من قائمة المستلمين (حتى لا يستلم تنبيه لنفسه)
    if actor is not None and getattr(actor, "is_authenticated", False):
        qs = qs.exclude(pk=actor.pk)

    url = url or ""

    for recipient in qs:
        create_notification(
            recipient=recipient,
            verb=verb,
            target=target,
            level=level,
            url=url,
        )


# ============================================================
# مكسين الصلاحيات للمخزون
# ============================================================

class InventoryStaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    مكسين يقيّد شاشات المخزون على المستخدمين الستاف فقط.

    - يتأكد أن المستخدم مسجّل دخول (LoginRequiredMixin).
    - يتأكد أن المستخدم is_staff (UserPassesTestMixin).
    - يضبط section = "inventory" لاستخدامه في الـ layout / الـ navbar.
    """

    raise_exception = True  # يرجّع 403 بدل دوّامة إعادة التوجيه
    section = "inventory"

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and user.is_staff


# ============================================================
# لوحة تحكم المخزون
# ============================================================

class InventoryDashboardView(InventoryStaffRequiredMixin, TemplateView):
    """
    لوحة تحكم المخزون:

    - إحصائيات عامة عن المنتجات والتصنيفات والمستودعات.
    - عدد حركات المخزون (كلها والمنفّذة).
    - آخر 10 حركات مخزون مع بنودها.
    - ملخص رصيد المخزون لكل مستودع.
    - قائمة بالمستويات تحت الحد الأدنى.
    """
    template_name = "inventory/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        total_products = Product.objects.count()
        active_products = Product.objects.filter(is_active=True).count()
        published_products = Product.objects.filter(is_published=True).count()

        total_categories = ProductCategory.objects.count()
        total_warehouses = Warehouse.objects.count()
        total_locations = StockLocation.objects.count()

        total_moves = StockMove.objects.count()
        done_moves = StockMove.objects.filter(status=StockMove.Status.DONE).count()

        # آخر 10 حركات مخزون (مع البنود)
        recent_moves = (
            StockMove.objects
            .select_related(
                "from_warehouse",
                "to_warehouse",
                "from_location",
                "to_location",
            )
            .prefetch_related("lines__product", "lines__uom")
            .order_by("-move_date", "-id")[:10]
        )

        # ملخص رصيد المخزون لكل مستودع
        stock_per_warehouse = get_stock_summary_per_warehouse()

        # مستويات مخزون تحت الحد الأدنى
        low_stock_levels = get_low_stock_levels()

        ctx.update(
            {
                "subsection": "dashboard",
                "total_products": total_products,
                "active_products": active_products,
                "published_products": published_products,
                "total_categories": total_categories,
                "total_warehouses": total_warehouses,
                "total_locations": total_locations,
                "total_moves": total_moves,
                "done_moves": done_moves,
                "recent_moves": recent_moves,
                "stock_per_warehouse": stock_per_warehouse,
                "low_stock_levels": low_stock_levels,
            }
        )
        return ctx


# ============================================================
# تصنيفات المنتجات
# ============================================================

class ProductCategoryListView(InventoryStaffRequiredMixin, ListView):
    """
    قائمة تصنيفات المنتجات مع دعم البحث النصي.
    """
    model = ProductCategory
    template_name = "inventory/category/list.html"
    context_object_name = "categories"
    paginate_by = 25

    def get_queryset(self):
        qs = ProductCategory.objects.all().order_by("name")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(slug__icontains=q)
            )
        self.search_query = q
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = getattr(self, "search_query", "")
        ctx["subsection"] = "categories"
        return ctx


class ProductCategoryCreateView(InventoryStaffRequiredMixin, CreateView):
    """
    إنشاء تصنيف جديد للمنتجات.
    """
    model = ProductCategory
    form_class = ProductCategoryForm
    template_name = "inventory/category/form.html"
    success_url = reverse_lazy("inventory:category_list")

    def form_valid(self, form):
        messages.success(self.request, _("تم إنشاء التصنيف بنجاح."))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "categories"
        ctx["mode"] = "create"
        return ctx


class ProductCategoryUpdateView(InventoryStaffRequiredMixin, UpdateView):
    """
    تعديل تصنيف المنتجات.
    """
    model = ProductCategory
    form_class = ProductCategoryForm
    template_name = "inventory/category/form.html"
    success_url = reverse_lazy("inventory:category_list")

    def form_valid(self, form):
        messages.success(self.request, _("تم تحديث التصنيف بنجاح."))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "categories"
        ctx["mode"] = "update"
        return ctx


# ============================================================
# المنتجات
# ============================================================

class ProductListView(InventoryStaffRequiredMixin, ListView):
    """
    قائمة المنتجات مع فلاتر وملخص بسيط للمخزون لكل منتج.
    """
    model = Product
    template_name = "inventory/product/list.html"
    context_object_name = "products"
    paginate_by = 25

    def get_queryset(self):
        """
        قائمة المنتجات مع:

        - select_related للتصنيف لأجل الأداء.
        - annotate لاحتساب:
            total_on_hand_agg: إجمالي الكمية على كل المواقع.
            has_low_stock_anywhere_agg: عدد المواقع تحت الحد الأدنى.
        - فلاتر:
            q, category, product_type, only_published
        """

        base_qs = (
            Product.objects
            .select_related("category")
            .annotate(
                # إجمالي المخزون (بدون ما نصطدم مع property total_on_hand)
                total_on_hand_agg=Sum("stock_levels__quantity_on_hand"),

                # عدد المواقع اللي تحت الحد الأدنى (0 أو أكثر)
                has_low_stock_anywhere_agg=Sum(
                    Case(
                        When(
                            stock_levels__min_stock__gt=Decimal("0.000"),
                            stock_levels__quantity_on_hand__lt=F("stock_levels__min_stock"),
                            then=1,
                        ),
                        default=0,
                        output_field=IntegerField(),
                    )
                ),
            )
            .order_by("code")
        )

        q = self.request.GET.get("q", "").strip()
        category_id = self.request.GET.get("category") or None
        product_type = self.request.GET.get("product_type") or None
        only_published = self.request.GET.get("published") == "1"

        qs = filter_products_queryset(
            base_qs,
            q=q,
            category_id=category_id,
            product_type=product_type,
            only_published=only_published,
        )

        # نخزّن الفلاتر لأجل الـ context
        self.search_query = q
        self.category_filter = category_id
        self.product_type_filter = product_type
        self.only_published = only_published

        # نحسب اللابل لنوع المنتج الحالي (للاستخدام في القالب)
        self.product_type_filter_label = None
        if product_type:
            for value, label in Product.ProductType.choices:
                if value == product_type:
                    self.product_type_filter_label = label
                    break

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = getattr(self, "search_query", "")
        ctx["category_filter"] = getattr(self, "category_filter", None)
        ctx["product_type_filter"] = getattr(self, "product_type_filter", None)
        ctx["product_type_filter_label"] = getattr(self, "product_type_filter_label", None)
        ctx["only_published"] = getattr(self, "only_published", False)

        ctx["categories"] = ProductCategory.objects.filter(is_active=True)
        ctx["product_type_choices"] = Product.ProductType.choices

        ctx["subsection"] = "products"
        return ctx


class ProductDetailView(InventoryStaffRequiredMixin, DetailView):
    """
    عرض تفاصيل المنتج:
    - بيانات المنتج الأساسية.
    - Snapshot لرصيد المخزون على مستوى المستودع/الموقع.
    - رابط سريع لسجل التدقيق (AuditLog) لهذا المنتج فقط.
    """
    model = Product
    template_name = "inventory/product/detail.html"
    context_object_name = "product"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        product = self.object

        # snapshot لرصيد المخزون لهذا المنتج
        stock_levels = (
            StockLevel.objects
            .select_related("warehouse", "location")
            .filter(product=product)
            .order_by("warehouse__code", "location__code")
        )

        total_on_hand = stock_levels.aggregate(
            total=Sum("quantity_on_hand")
        )["total"] or Decimal("0")

        # رابط سجل الأوديت لهذا المنتج
        query = urlencode({
            "target_model": "inventory.Product",
            "target_id": product.pk,
        })
        audit_log_url = reverse("core:audit_log_list") + f"?{query}"

        ctx["stock_levels"] = stock_levels
        ctx["total_on_hand"] = total_on_hand
        ctx["audit_log_url"] = audit_log_url
        ctx["subsection"] = "products"
        return ctx


class ProductCreateView(InventoryStaffRequiredMixin, CreateView):
    """
    إنشاء منتج جديد:

    - يضبط created_by / updated_by بالمستخدم الحالي (إن وُجد).
    - يعرض رسالة نجاح.
    - يسجّل حدث في سجل التدقيق (AuditLog).
    - يرسل نوتفيكيشن لباقي مستخدمي الستاف في المخزون.
    """
    model = Product
    form_class = ProductForm
    template_name = "inventory/product/form.html"
    success_url = reverse_lazy("inventory:product_list")

    def form_valid(self, form):
        user = self.request.user

        # تعبئة created_by / updated_by من المستخدم الحالي
        if user.is_authenticated:
            if hasattr(form.instance, "created_by") and not form.instance.pk:
                form.instance.created_by = user
            if hasattr(form.instance, "updated_by"):
                form.instance.updated_by = user

        response = super().form_valid(form)

        messages.success(self.request, _("تم إنشاء المنتج بنجاح."))

        # --- الأوديت: إنشاء منتج ---
        log_event(
            action=AuditLog.Action.CREATE,
            message=_("تم إنشاء المنتج %(code)s") % {
                "code": self.object.code
            },
            actor=user if user.is_authenticated else None,
            target=self.object,
            extra={
                "category_id": self.object.category_id,
                "product_type": self.object.product_type,
                "is_stock_item": self.object.is_stock_item,
                "is_active": self.object.is_active,
                "is_published": self.object.is_published,
                "default_sale_price": str(self.object.default_sale_price),
                "default_cost_price": str(self.object.default_cost_price),
            },
        )

        # --- النوتفيكيشن: إنشاء منتج جديد ---
        product_url = reverse("inventory:product_detail", args=[self.object.pk])
        _notify_inventory_staff(
            actor=user,
            verb=_("تم إنشاء المنتج %(code)s") % {"code": self.object.code},
            target=self.object,
            level=Notification.Levels.INFO,
            url=product_url,
        )

        return response

    def get_initial(self):
        """
        قيم افتراضية بسيطة للمنتج الجديد.
        """
        initial = super().get_initial()
        initial.setdefault("is_stock_item", True)
        initial.setdefault("is_active", True)
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "products"
        ctx["mode"] = "create"
        return ctx


class ProductUpdateView(InventoryStaffRequiredMixin, UpdateView):
    """
    تعديل بيانات المنتج:

    - يحدّث updated_by بالمستخدم الحالي.
    - يسجّل حدث في سجل التدقيق (AuditLog).
    - يرسل نوتفيكيشن لباقي مستخدمي الستاف.
    """
    model = Product
    form_class = ProductForm
    template_name = "inventory/product/form.html"
    success_url = reverse_lazy("inventory:product_list")

    def form_valid(self, form):
        user = self.request.user

        # تعبئة updated_by فقط
        if user.is_authenticated and hasattr(form.instance, "updated_by"):
            form.instance.updated_by = user

        response = super().form_valid(form)

        messages.success(self.request, _("تم تحديث بيانات المنتج بنجاح."))

        # --- الأوديت: تحديث منتج ---
        log_event(
            action=AuditLog.Action.UPDATE,
            message=_("تم تحديث بيانات المنتج %(code)s") % {
                "code": self.object.code
            },
            actor=user if user.is_authenticated else None,
            target=self.object,
            extra={
                "category_id": self.object.category_id,
                "product_type": self.object.product_type,
                "is_stock_item": self.object.is_stock_item,
                "is_active": self.object.is_active,
                "is_published": self.object.is_published,
                "default_sale_price": str(self.object.default_sale_price),
                "default_cost_price": str(self.object.default_cost_price),
            },
        )

        # --- النوتفيكيشن: تحديث منتج ---
        product_url = reverse("inventory:product_detail", args=[self.object.pk])
        _notify_inventory_staff(
            actor=user,
            verb=_("تم تحديث بيانات المنتج %(code)s") % {"code": self.object.code},
            target=self.object,
            level=Notification.Levels.INFO,
            url=product_url,
        )

        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "products"
        ctx["mode"] = "update"
        return ctx


# ============================================================
# المستودعات
# ============================================================

class WarehouseListView(InventoryStaffRequiredMixin, ListView):
    """
    قائمة المستودعات مع بحث نصي.
    """
    model = Warehouse
    template_name = "inventory/warehouse/list.html"
    context_object_name = "warehouses"
    paginate_by = 50

    def get_queryset(self):
        qs = Warehouse.objects.all().order_by("code")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(code__icontains=q)
                | Q(name__icontains=q)
            )
        self.search_query = q
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = getattr(self, "search_query", "")
        ctx["subsection"] = "warehouses"
        return ctx


class WarehouseCreateView(InventoryStaffRequiredMixin, CreateView):
    """
    إنشاء مستودع جديد.
    """
    model = Warehouse
    fields = ["code", "name", "description", "is_active"]
    template_name = "inventory/warehouse/form.html"
    success_url = reverse_lazy("inventory:warehouse_list")

    def form_valid(self, form):
        messages.success(self.request, _("تم إنشاء المستودع بنجاح."))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "warehouses"
        ctx["mode"] = "create"
        return ctx


class WarehouseUpdateView(InventoryStaffRequiredMixin, UpdateView):
    """
    تعديل بيانات المستودع.
    """
    model = Warehouse
    fields = ["code", "name", "description", "is_active"]
    template_name = "inventory/warehouse/form.html"
    success_url = reverse_lazy("inventory:warehouse_list")

    def form_valid(self, form):
        messages.success(self.request, _("تم تحديث بيانات المستودع بنجاح."))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "warehouses"
        ctx["mode"] = "update"
        return ctx


# ============================================================
# مواقع المخزون داخل المستودع
# ============================================================

class StockLocationListView(InventoryStaffRequiredMixin, ListView):
    """
    قائمة مواقع المخزون داخل المستودعات.
    """
    model = StockLocation
    template_name = "inventory/location/list.html"
    context_object_name = "locations"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            StockLocation.objects
            .select_related("warehouse")
            .order_by("warehouse__code", "code")
        )

        q = self.request.GET.get("q", "").strip()
        wh = self.request.GET.get("warehouse") or None

        if q:
            qs = qs.filter(
                Q(code__icontains=q)
                | Q(name__icontains=q)
                | Q(warehouse__code__icontains=q)
            )

        if wh:
            qs = qs.filter(warehouse_id=wh)

        self.search_query = q
        self.warehouse_filter = wh
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = getattr(self, "search_query", "")
        ctx["warehouse_filter"] = getattr(self, "warehouse_filter", None)
        ctx["warehouses"] = Warehouse.objects.filter(is_active=True)
        ctx["subsection"] = "locations"
        return ctx


class StockLocationCreateView(InventoryStaffRequiredMixin, CreateView):
    """
    إنشاء موقع جديد داخل مستودع.
    """
    model = StockLocation
    fields = ["warehouse", "code", "name", "type", "is_active"]
    template_name = "inventory/location/form.html"
    success_url = reverse_lazy("inventory:location_list")

    def form_valid(self, form):
        messages.success(self.request, _("تم إنشاء الموقع بنجاح."))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "locations"
        ctx["mode"] = "create"
        return ctx


class StockLocationUpdateView(InventoryStaffRequiredMixin, UpdateView):
    """
    تعديل موقع المخزون.
    """
    model = StockLocation
    fields = ["warehouse", "code", "name", "type", "is_active"]
    template_name = "inventory/location/form.html"
    success_url = reverse_lazy("inventory:location_list")

    def form_valid(self, form):
        messages.success(self.request, _("تم تحديث بيانات الموقع بنجاح."))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "locations"
        ctx["mode"] = "update"
        return ctx


# ============================================================
# حركات المخزون
# ============================================================

class StockMoveListView(InventoryStaffRequiredMixin, ListView):
    """
    قائمة حركات المخزون مع فلاتر حسب النوع والحالة والبحث النصي.
    """
    model = StockMove
    template_name = "inventory/stockmove/list.html"
    context_object_name = "moves"
    paginate_by = 50

    def get_queryset(self):
        # Base queryset مع العلاقات والترتيب
        qs = (
            StockMove.objects
            .select_related(
                "from_warehouse",
                "to_warehouse",
                "from_location",
                "to_location",
            )
            .prefetch_related("lines__product", "lines__uom")
            .order_by("-move_date", "-id")
        )

        q = self.request.GET.get("q", "").strip()
        move_type = self.request.GET.get("move_type") or None
        status = self.request.GET.get("status") or None

        qs = filter_stock_moves_queryset(
            qs,
            q=q,
            move_type=move_type,
            status=status,
        ).distinct()

        self.search_query = q
        self.move_type_filter = move_type
        self.status_filter = status
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = getattr(self, "search_query", "")
        ctx["move_type_filter"] = getattr(self, "move_type_filter", None)
        ctx["status_filter"] = getattr(self, "status_filter", None)
        ctx["move_type_choices"] = StockMove.MoveType.choices
        ctx["status_choices"] = StockMove.Status.choices
        ctx["subsection"] = "moves"
        return ctx


class StockMoveDetailView(InventoryStaffRequiredMixin, DetailView):
    """
    عرض تفاصيل حركة المخزون:
    - بيانات الحركة (من/إلى مستودع/موقع).
    - بنود الحركة (المنتجات والكميات).
    - رابط لسجل الأوديت لهذه الحركة فقط.
    """
    model = StockMove
    template_name = "inventory/stockmove/detail.html"
    context_object_name = "stockmove"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        move = self.object

        ctx["lines"] = move.lines.select_related("product", "uom").all()

        # رابط سجل الأوديت لهذه الحركة
        query = urlencode({
            "target_model": "inventory.StockMove",
            "target_id": move.pk,
        })
        ctx["audit_log_url"] = reverse("core:audit_log_list") + f"?{query}"

        ctx["subsection"] = "moves"
        return ctx


class StockMoveCreateView(InventoryStaffRequiredMixin, CreateView):
    """
    إنشاء حركة مخزون جديدة:

    - تعبئة created_by / updated_by من المستخدم الحالي.
    - إنشاء وحفظ البنود عبر formset.
    - عرض رسالة نجاح للمستخدم.
    - تسجيل حدث في سجل التدقيق (AuditLog).
    - إرسال نوتفيكيشن لباقي مستخدمي الستاف.
    """
    model = StockMove
    form_class = StockMoveForm
    template_name = "inventory/stockmove/form.html"
    success_url = reverse_lazy("inventory:move_list")

    def get_initial(self):
        """
        ملء بعض الحقول افتراضياً من الـ query string لو موجودة.
        مثال:
          ?move_type=in&from_warehouse=1&to_warehouse=2
        """
        initial = super().get_initial()
        request = self.request

        for field in [
            "move_type",
            "from_warehouse",
            "from_location",
            "to_warehouse",
            "to_location",
        ]:
            value = request.GET.get(field)
            if value:
                initial[field] = value

        return initial

    def get_context_data(self, **kwargs):
        """
        تجهيز الـ inline formset للبنود:
        - في حالة POST نستخدم البيانات القادمة من الفورم.
        - في حالة GET نهيئ initial (مثل تعبئة المنتج لو جاي من شاشة المنتج).
        """
        ctx = super().get_context_data(**kwargs)

        if self.request.POST:
            line_formset = StockMoveLineFormSet(
                self.request.POST,
                instance=self.object,
            )
        else:
            # هنا نمرر initial لو جايين من زر "حركة مخزون" في المنتج
            product_id = self.request.GET.get("product")
            initial = []

            if product_id:
                # نعبي أول سطر بالمنتج افتراضياً
                initial.append({"product": product_id})

            line_formset = StockMoveLineFormSet(
                instance=self.object,
                initial=initial,
            )

        ctx["line_formset"] = line_formset
        ctx["subsection"] = "moves"
        ctx["mode"] = "create"
        return ctx

    def form_valid(self, form):
        """
        منطق الحفظ عند إنشاء حركة المخزون:
        - التحقق من صلاحية formset البنود.
        - تعبئة created_by / updated_by.
        - حفظ رأس الحركة ثم البنود.
        - تسجيل الأوديت.
        - إرسال نوتفيكيشن.
        """
        context = self.get_context_data()
        line_formset = context["line_formset"]

        if not line_formset.is_valid():
            # وجود أخطاء في البنود → نرجع نفس الصفحة مع الأخطاء
            return self.render_to_response(self.get_context_data(form=form))

        user = self.request.user

        # تعبئة created_by / updated_by
        if user.is_authenticated:
            if hasattr(form.instance, "created_by") and not form.instance.pk:
                form.instance.created_by = user
            if hasattr(form.instance, "updated_by"):
                form.instance.updated_by = user

        # حفظ رأس الحركة
        self.object = form.save()

        # ربط البنود بالرأس ثم حفظها
        line_formset.instance = self.object
        line_formset.save()

        messages.success(self.request, _("تم إنشاء حركة المخزون بنجاح."))

        # --- الأوديت: إنشاء حركة مخزون ---
        log_event(
            action=AuditLog.Action.CREATE,
            message=_("تم إنشاء حركة مخزون رقم %(id)s") % {
                "id": self.object.pk
            },
            actor=user if user.is_authenticated else None,
            target=self.object,
            extra={
                "move_type": self.object.move_type,
                "status": self.object.status,
                "from_warehouse_id": self.object.from_warehouse_id,
                "to_warehouse_id": self.object.to_warehouse_id,
                "from_location_id": self.object.from_location_id,
                "to_location_id": self.object.to_location_id,
                "total_lines_quantity": str(self.object.total_lines_quantity),
            },
        )

        # --- النوتفيكيشن: حركة مخزون جديدة ---
        move_url = reverse("inventory:move_detail", args=[self.object.pk])
        _notify_inventory_staff(
            actor=user,
            verb=_("تم إنشاء حركة مخزون جديدة رقم %(id)s") % {"id": self.object.pk},
            target=self.object,
            level=Notification.Levels.INFO,
            url=move_url,
        )

        return HttpResponseRedirect(self.get_success_url())


class StockMoveUpdateView(InventoryStaffRequiredMixin, UpdateView):
    """
    تعديل حركة المخزون:

    - تعديل رأس الحركة (التواريخ، النوع، المستودعات..).
    - تعديل البنود عبر formset.
    - تحديث updated_by.
    - تسجيل حدث في سجل الأوديت.
    - إرسال نوتفيكيشن لباقي الستاف.
    """
    model = StockMove
    form_class = StockMoveForm
    template_name = "inventory/stockmove/form.html"
    success_url = reverse_lazy("inventory:move_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        if self.request.POST:
            ctx["line_formset"] = StockMoveLineFormSet(self.request.POST, instance=self.object)
        else:
            ctx["line_formset"] = StockMoveLineFormSet(instance=self.object)

        ctx["subsection"] = "moves"
        ctx["mode"] = "update"
        return ctx

    def form_valid(self, form):
        """
        منطق التحديث:
        - التحقق من formset.
        - تحديث updated_by.
        - حفظ الرأس والبنود.
        - تسجيل حدث الأوديت.
        - إرسال نوتفيكيشن.
        """
        context = self.get_context_data()
        line_formset = context["line_formset"]

        if not line_formset.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        user = self.request.user

        # تعبئة updated_by
        if user.is_authenticated and hasattr(form.instance, "updated_by"):
            form.instance.updated_by = user

        self.object = form.save()
        line_formset.instance = self.object
        line_formset.save()

        messages.success(self.request, _("تم تحديث حركة المخزون بنجاح."))

        # --- الأوديت: تحديث حركة مخزون ---
        log_event(
            action=AuditLog.Action.UPDATE,
            message=_("تم تحديث حركة المخزون رقم %(id)s") % {
                "id": self.object.pk
            },
            actor=user if user.is_authenticated else None,
            target=self.object,
            extra={
                "move_type": self.object.move_type,
                "status": self.object.status,
                "from_warehouse_id": self.object.from_warehouse_id,
                "to_warehouse_id": self.object.to_warehouse_id,
                "from_location_id": self.object.from_location_id,
                "to_location_id": self.object.to_location_id,
                "total_lines_quantity": str(self.object.total_lines_quantity),
            },
        )

        # --- النوتفيكيشن: تحديث حركة مخزون ---
        move_url = reverse("inventory:move_detail", args=[self.object.pk])
        _notify_inventory_staff(
            actor=user,
            verb=_("تم تحديث حركة المخزون رقم %(id)s") % {"id": self.object.pk},
            target=self.object,
            level=Notification.Levels.INFO,
            url=move_url,
        )

        return HttpResponseRedirect(self.get_success_url())


# ============================================================
# مستويات المخزون
# ============================================================

class StockLevelListView(InventoryStaffRequiredMixin, ListView):
    """
    قائمة مستويات المخزون (Product + Warehouse + Location)
    مع فلاتر بحث ومستودع وتحت الحد الأدنى.
    """
    model = StockLevel
    template_name = "inventory/stocklevel/list.html"
    context_object_name = "stock_levels"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            StockLevel.objects
            .select_related("product", "warehouse", "location")
            .order_by("product__code", "warehouse__code", "location__code")
        )

        q = self.request.GET.get("q", "").strip()
        wh = self.request.GET.get("warehouse") or None
        below_min = self.request.GET.get("below_min") == "1"

        if q:
            qs = qs.filter(
                Q(product__code__icontains=q)
                | Q(product__name__icontains=q)
                | Q(warehouse__code__icontains=q)
                | Q(location__code__icontains=q)
            )

        if wh:
            qs = qs.filter(warehouse_id=wh)

        if below_min:
            qs = filter_below_min_stock_levels(qs)

        self.search_query = q
        self.warehouse_filter = wh
        self.below_min_only = below_min
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = getattr(self, "search_query", "")
        ctx["warehouse_filter"] = getattr(self, "warehouse_filter", None)
        ctx["below_min_only"] = getattr(self, "below_min_only", False)
        ctx["warehouses"] = Warehouse.objects.filter(is_active=True)

        # إجمالي المستويات تحت الحد الأدنى (بدون فلاتر البحث)
        ctx["low_total"] = get_low_stock_total()

        ctx["subsection"] = "stock_levels"
        return ctx


class StockLevelDetailView(InventoryStaffRequiredMixin, DetailView):
    """
    عرض تفاصيل مستوى مخزون محدّد.
    """
    model = StockLevel
    template_name = "inventory/stocklevel/detail.html"
    context_object_name = "object"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "stock_levels"
        return ctx


class StockLevelCreateView(InventoryStaffRequiredMixin, CreateView):
    """
    إنشاء مستوى مخزون جديد (Product + Warehouse + Location).
    """
    model = StockLevel
    form_class = StockLevelForm
    template_name = "inventory/stocklevel/form.html"

    def get_success_url(self):
        return reverse("inventory:stocklevel_detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, _("تم إنشاء مستوى المخزون بنجاح."))
        return super().form_valid(form)

    def get_initial(self):
        """
        لو جاي من رابط فيه product / warehouse / location في الـ query string
        نملأها تلقائيًا كقيمة افتراضية.
        مثال: /inventory/stock-levels/create/?product=5&warehouse=2
        """
        initial = super().get_initial()
        product_id = self.request.GET.get("product")
        warehouse_id = self.request.GET.get("warehouse")
        location_id = self.request.GET.get("location")

        if product_id:
            initial["product"] = product_id
        if warehouse_id:
            initial["warehouse"] = warehouse_id
        if location_id:
            initial["location"] = location_id

        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "stock_levels"
        ctx["mode"] = "create"
        return ctx


class StockLevelUpdateView(InventoryStaffRequiredMixin, UpdateView):
    """
    تعديل مستوى المخزون.
    """
    model = StockLevel
    form_class = StockLevelForm
    template_name = "inventory/stocklevel/form.html"

    def get_success_url(self):
        return reverse("inventory:stocklevel_detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, _("تم تحديث مستوى المخزون بنجاح."))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "stock_levels"
        ctx["mode"] = "update"
        return ctx


# ============================================================
# إعدادات المخزون
# ============================================================

class InventorySettingsView(InventoryStaffRequiredMixin, UpdateView):
    """
    شاشة إعدادات المخزون (نمط django-solo):

    - نموذج واحد فقط من InventorySettings.
    - مناسب لتعريف إعدادات عامة (مستودع افتراضي، سياسات، ...).
    - عند تغيير الإعدادات يتم إشعار مستخدمي الستاف.
    """
    model = InventorySettings
    form_class = InventorySettingsForm
    template_name = "inventory/settings/form.html"
    success_url = reverse_lazy("inventory:settings")

    def get_object(self, queryset=None):
        # نمط django-solo: يرجع سجل واحد فقط
        return InventorySettings.get_solo()

    def form_valid(self, form):
        user = self.request.user
        messages.success(self.request, _("تم حفظ إعدادات المخزون بنجاح."))

        response = super().form_valid(form)

        # --- النوتفيكيشن: تحديث إعدادات المخزون ---
        settings_url = reverse("inventory:settings")
        _notify_inventory_staff(
            actor=user,
            verb=_("تم تحديث إعدادات المخزون."),
            target=self.object,
            level=Notification.Levels.INFO,
            url=settings_url,
        )

        return response


class StockMoveConfirmView(InventoryStaffRequiredMixin, DetailView):
    """
    تأكيد حركة مخزون موجودة باستخدام السيرفس confirm_stock_move:

    - يسمح فقط بتأكيد حركة ليست في حالة CANCELLED.
    - لو كانت DONE مسبقًا → لا يعيد التطبيق.
    - عند النجاح:
        * يتم تسجيل الأوديت داخل السيرفس.
        * يتم إرسال رسالة نجاح للمستخدم.
        * يتم إرسال نوتفيكيشن لبقية الستاف.
    """
    model = StockMove
    context_object_name = "stockmove"

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        user = request.user

        try:
            move = confirm_stock_move(self.object, user=user)
            messages.success(
                request,
                _("تم تأكيد حركة المخزون رقم %(id)s بنجاح.") % {"id": move.pk},
            )

            # 🔔 نوتفيكيشن لبقية الستاف
            move_url = reverse("inventory:move_detail", args=[move.pk])
            _notify_inventory_staff(
                actor=user,
                verb=_("تم تأكيد حركة المخزون رقم %(id)s.") % {"id": move.pk},
                target=move,
                level=Notification.Levels.SUCCESS,
                url=move_url,
            )

        except ValidationError as e:
            # لو السيرفس رفض التغيير (مثلاً حركة ملغاة أو بيانات ناقصة)
            error_msg = e.messages[0] if hasattr(e, "messages") and e.messages else str(e)
            messages.error(request, error_msg)

        # في جميع الأحوال نرجع لصفحة التفاصيل
        return HttpResponseRedirect(
            reverse("inventory:move_detail", args=[self.object.pk])
        )

    def get(self, request, *args, **kwargs):
        """
        لو أحد فتح الرابط بـ GET نرجعه مباشرة لصفحة التفاصيل
        (التأكيد مطلوب عبر POST من الفورم/الزر).
        """
        self.object = self.get_object()
        return HttpResponseRedirect(
            reverse("inventory:move_detail", args=[self.object.pk])
        )



class StockMoveCancelView(InventoryStaffRequiredMixin, DetailView):
    """
    إلغاء حركة مخزون باستخدام السيرفس cancel_stock_move:

    - DRAFT  → CANCELLED (بدون أثر مخزني).
    - DONE   → CANCELLED (يعكس أثر الحركة على المخزون).
    - CANCELLED مسبقًا → لا شيء.
    """
    model = StockMove
    context_object_name = "stockmove"

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        user = request.user

        try:
            move = cancel_stock_move(self.object, user=user)
            messages.success(
                request,
                _("تم إلغاء حركة المخزون رقم %(id)s بنجاح.") % {"id": move.pk},
            )

            # 🔔 نوتفيكيشن لبقية الستاف
            move_url = reverse("inventory:move_detail", args=[move.pk])
            _notify_inventory_staff(
                actor=user,
                verb=_("تم إلغاء حركة المخزون رقم %(id)s.") % {"id": move.pk},
                target=move,
                level=Notification.Levels.WARNING,
                url=move_url,
            )

        except ValidationError as e:
            error_msg = e.messages[0] if hasattr(e, "messages") and e.messages else str(e)
            messages.error(request, error_msg)

        return HttpResponseRedirect(
            reverse("inventory:move_detail", args=[self.object.pk])
        )

    def get(self, request, *args, **kwargs):
        """
        مثل confirm: لو GET نرجعه لصفحة التفاصيل مباشرة.
        """
        self.object = self.get_object()
        return HttpResponseRedirect(
            reverse("inventory:move_detail", args=[self.object.pk])
        )
