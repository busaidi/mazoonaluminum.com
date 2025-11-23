# inventory/views.py
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Sum, Q, F
from django.urls import reverse_lazy
from django.urls.base import reverse
from django.views.generic import (
    TemplateView,
    ListView,
    DetailView,
    CreateView,
    UpdateView,
)

from .models import (
    ProductCategory,
    Product,
    Warehouse,
    StockLocation,
    StockMove,
    StockLevel,
)


# ============================================================
# Base mixin for inventory staff
# ============================================================

class InventoryStaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Restrict inventory views to staff users.
    Later you can replace this with a shared mixin from core if needed.
    """

    raise_exception = True  # return 403 instead of redirect loop
    section = "inventory"   # for layout/nav highlighting

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and user.is_staff


# ============================================================
# Dashboard
# ============================================================

class InventoryDashboardView(InventoryStaffRequiredMixin, TemplateView):
    """
    Simple inventory dashboard with high-level KPIs.
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

        # recent 10 moves
        recent_moves = (
            StockMove.objects
            .select_related(
                "product",
                "from_warehouse",
                "to_warehouse",
                "from_location",
                "to_location",
            )
            .order_by("-move_date", "-id")[:10]
        )

        # stock summary per warehouse (نستخدم warehouse مباشرة + quantity_on_hand)
        stock_per_warehouse = (
            StockLevel.objects
            .select_related("warehouse")
            .values("warehouse__code", "warehouse__name")
            .annotate(total_qty=Sum("quantity_on_hand"))
            .order_by("warehouse__code")
        )

        # Low stock: min_stock > 0 && quantity_on_hand < min_stock
        low_stock_levels = (
            StockLevel.objects
            .select_related("product", "warehouse", "location")
            .filter(min_stock__gt=0, quantity_on_hand__lt=F("min_stock"))
        )

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
# Product categories
# ============================================================

class ProductCategoryListView(InventoryStaffRequiredMixin, ListView):
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
    model = ProductCategory
    fields = ["slug", "name", "description", "parent", "is_active"]
    template_name = "inventory/category/form.html"
    success_url = reverse_lazy("inventory:category_list")

    def form_valid(self, form):
        messages.success(self.request, "Category created successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "categories"
        ctx["mode"] = "create"
        return ctx


class ProductCategoryUpdateView(InventoryStaffRequiredMixin, UpdateView):
    model = ProductCategory
    fields = ["slug", "name", "description", "parent", "is_active"]
    template_name = "inventory/category/form.html"
    success_url = reverse_lazy("inventory:category_list")

    def form_valid(self, form):
        messages.success(self.request, "Category updated successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "categories"
        ctx["mode"] = "update"
        return ctx


# ============================================================
# Products
# ============================================================

class ProductListView(InventoryStaffRequiredMixin, ListView):
    model = Product
    template_name = "inventory/product/list.html"
    context_object_name = "products"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            Product.objects
            .select_related("category")
            .order_by("code")
        )
        q = self.request.GET.get("q", "").strip()
        category_id = self.request.GET.get("category") or None
        only_published = self.request.GET.get("published") == "1"

        if q:
            qs = qs.filter(
                Q(code__icontains=q)
                | Q(name__icontains=q)
                | Q(short_description__icontains=q)
            )

        if category_id:
            qs = qs.filter(category_id=category_id)

        if only_published:
            qs = qs.filter(is_published=True)

        self.search_query = q
        self.category_filter = category_id
        self.only_published = only_published
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = getattr(self, "search_query", "")
        ctx["category_filter"] = getattr(self, "category_filter", None)
        ctx["only_published"] = getattr(self, "only_published", False)
        ctx["categories"] = ProductCategory.objects.filter(is_active=True)
        ctx["subsection"] = "products"
        return ctx


class ProductDetailView(InventoryStaffRequiredMixin, DetailView):
    model = Product
    template_name = "inventory/product/detail.html"
    context_object_name = "product"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        product = self.object

        # stock snapshot per level
        stock_levels = (
            StockLevel.objects
            .select_related("warehouse", "location")
            .filter(product=product)
            .order_by("warehouse__code", "location__code")
        )

        total_on_hand = stock_levels.aggregate(
            total=Sum("quantity_on_hand")
        )["total"] or Decimal("0")

        ctx["stock_levels"] = stock_levels
        ctx["total_on_hand"] = total_on_hand
        ctx["subsection"] = "products"
        return ctx


class ProductCreateView(InventoryStaffRequiredMixin, CreateView):
    model = Product
    fields = [
        "category",
        "code",
        "name",
        "short_description",
        "description",
        "uom",
        "is_stock_item",
        "is_active",
        "is_published",
    ]
    template_name = "inventory/product/form.html"
    success_url = reverse_lazy("inventory:product_list")

    def form_valid(self, form):
        messages.success(self.request, "Product created successfully.")
        return super().form_valid(form)

    def get_initial(self):
        initial = super().get_initial()
        initial.setdefault("uom", "PCS")
        initial.setdefault("is_stock_item", True)
        initial.setdefault("is_active", True)
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "products"
        ctx["mode"] = "create"
        return ctx


class ProductUpdateView(InventoryStaffRequiredMixin, UpdateView):
    model = Product
    fields = [
        "category",
        "code",
        "name",
        "short_description",
        "description",
        "uom",
        "is_stock_item",
        "is_active",
        "is_published",
    ]
    template_name = "inventory/product/form.html"
    success_url = reverse_lazy("inventory:product_list")

    def form_valid(self, form):
        messages.success(self.request, "Product updated successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "products"
        ctx["mode"] = "update"
        return ctx


# ============================================================
# Warehouses
# ============================================================

class WarehouseListView(InventoryStaffRequiredMixin, ListView):
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
    model = Warehouse
    fields = ["code", "name", "description", "is_active"]
    template_name = "inventory/warehouse/form.html"
    success_url = reverse_lazy("inventory:warehouse_list")

    def form_valid(self, form):
        messages.success(self.request, "Warehouse created successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "warehouses"
        ctx["mode"] = "create"
        return ctx


class WarehouseUpdateView(InventoryStaffRequiredMixin, UpdateView):
    model = Warehouse
    fields = ["code", "name", "description", "is_active"]
    template_name = "inventory/warehouse/form.html"
    success_url = reverse_lazy("inventory:warehouse_list")

    def form_valid(self, form):
        messages.success(self.request, "Warehouse updated successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "warehouses"
        ctx["mode"] = "update"
        return ctx


# ============================================================
# Stock locations
# ============================================================

class StockLocationListView(InventoryStaffRequiredMixin, ListView):
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
    model = StockLocation
    fields = ["warehouse", "code", "name", "type", "is_active"]
    template_name = "inventory/location/form.html"
    success_url = reverse_lazy("inventory:location_list")

    def form_valid(self, form):
        messages.success(self.request, "Location created successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "locations"
        ctx["mode"] = "create"
        return ctx


class StockLocationUpdateView(InventoryStaffRequiredMixin, UpdateView):
    model = StockLocation
    fields = ["warehouse", "code", "name", "type", "is_active"]
    template_name = "inventory/location/form.html"
    success_url = reverse_lazy("inventory:location_list")

    def form_valid(self, form):
        messages.success(self.request, "Location updated successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "locations"
        ctx["mode"] = "update"
        return ctx


# ============================================================
# Stock moves
# ============================================================

class StockMoveListView(InventoryStaffRequiredMixin, ListView):
    model = StockMove
    template_name = "inventory/stockmove/list.html"
    context_object_name = "moves"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            StockMove.objects
            .select_related(
                "product",
                "from_warehouse",
                "to_warehouse",
                "from_location",
                "to_location",
            )
            .order_by("-move_date", "-id")
        )

        q = self.request.GET.get("q", "").strip()
        move_type = self.request.GET.get("move_type") or None
        status = self.request.GET.get("status") or None

        if q:
            qs = qs.filter(
                Q(product__code__icontains=q)
                | Q(product__name__icontains=q)
                | Q(reference__icontains=q)
                | Q(from_warehouse__code__icontains=q)
                | Q(to_warehouse__code__icontains=q)
            )

        if move_type in dict(StockMove.MoveType.choices):
            qs = qs.filter(move_type=move_type)

        if status in dict(StockMove.Status.choices):
            qs = qs.filter(status=status)

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
    model = StockMove
    template_name = "inventory/stockmove/detail.html"
    context_object_name = "stockmove"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "moves"
        return ctx


class StockMoveCreateView(InventoryStaffRequiredMixin, CreateView):
    model = StockMove
    fields = [
        "move_type",
        "product",
        "from_warehouse",
        "from_location",
        "to_warehouse",
        "to_location",
        "quantity",
        "uom",
        "move_date",
        "status",
        "reference",
        "note",
    ]
    template_name = "inventory/stockmove/form.html"
    success_url = reverse_lazy("inventory:move_list")

    def get_initial(self):
        initial = super().get_initial()
        # قيمة أولية منطقية للكمية
        initial.setdefault("quantity", Decimal("0.000"))
        return initial

    def form_valid(self, form):
        """
        هنا نخلي Django يتكفل بعملية الحفظ مرة واحدة فقط
        عن طريق super().form_valid(form)
        وبعدها نضيف رسالة النجاح.
        """
        response = super().form_valid(form)
        messages.success(self.request, "Stock move created successfully.")
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "moves"
        ctx["mode"] = "create"
        return ctx



class StockMoveUpdateView(InventoryStaffRequiredMixin, UpdateView):
    model = StockMove
    fields = [
        "move_type",
        "product",
        "from_warehouse",
        "from_location",
        "to_warehouse",
        "to_location",
        "quantity",
        "uom",
        "move_date",
        "status",
        "reference",
        "note",
    ]
    template_name = "inventory/stockmove/form.html"
    success_url = reverse_lazy("inventory:move_list")

    def form_valid(self, form):
        messages.success(self.request, "Stock move updated successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "moves"
        ctx["mode"] = "update"
        return ctx


# ============================================================
# Stock levels (read-only list)
# ============================================================

class StockLevelListView(InventoryStaffRequiredMixin, ListView):
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

        if q:
            qs = qs.filter(
                Q(product__code__icontains=q)
                | Q(product__name__icontains=q)
                | Q(warehouse__code__icontains=q)
                | Q(location__code__icontains=q)
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
        ctx["subsection"] = "stock_levels"
        return ctx




class StockLevelDetailView(InventoryStaffRequiredMixin, DetailView):
    model = StockLevel
    template_name = "inventory/stocklevel/detail.html"
    context_object_name = "object"



class StockLevelUpdateView(InventoryStaffRequiredMixin, UpdateView):
    model = StockLevel
    fields = [
        "min_quantity",
        "max_quantity",
    ]
    template_name = "inventory/stocklevel/form.html"

    def get_success_url(self):
        return reverse("inventory:stocklevel_detail", kwargs={"pk": self.object.pk})
