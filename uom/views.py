# uom/views.py
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Q
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, CreateView, UpdateView

from .models import UnitOfMeasure
from .forms import UnitOfMeasureForm


class UomStaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    نفس فكرة InventoryStaffRequiredMixin لكن خاصة بوحدات القياس.
    تقدر لاحقاً تنقلها لـ core وتستخدمها في كل التطبيقات.
    """
    raise_exception = True  # 403 بدل redirect loop

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and user.is_staff


class UnitOfMeasureListView(UomStaffRequiredMixin, ListView):
    model = UnitOfMeasure
    template_name = "uom/unit_list.html"
    context_object_name = "units"
    paginate_by = 25

    def get_queryset(self):
        # select_related لأداء أفضل
        qs = (
            UnitOfMeasure.objects
            .select_related("category")
            .order_by("category", "name")  # name = الحقل المترجم حسب اللغة الحالية
        )

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(name_ar__icontains=q)      # بحث بالاسم العربي
                | Q(name_en__icontains=q)    # بحث بالاسم الإنجليزي
                | Q(code__icontains=q)
                | Q(symbol__icontains=q)     # لو symbol مترجم وتريد تبحث في الاثنين: symbol_ar/symbol_en
            )
        self.search_query = q
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "uom"
        ctx["q"] = getattr(self, "search_query", "")
        return ctx


class UnitOfMeasureCreateView(UomStaffRequiredMixin, CreateView):
    model = UnitOfMeasure
    form_class = UnitOfMeasureForm
    template_name = "uom/unit_form.html"
    success_url = reverse_lazy("uom:unit_list")

    def form_valid(self, form):
        messages.success(self.request, _("تم إضافة وحدة القياس بنجاح."))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "uom"
        ctx["mode"] = "create"
        return ctx


class UnitOfMeasureUpdateView(UomStaffRequiredMixin, UpdateView):
    model = UnitOfMeasure
    form_class = UnitOfMeasureForm
    template_name = "uom/unit_form.html"
    success_url = reverse_lazy("uom:unit_list")

    def form_valid(self, form):
        messages.success(self.request, _("تم تحديث وحدة القياس بنجاح."))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["subsection"] = "uom"
        ctx["mode"] = "update"
        return ctx
