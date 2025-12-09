# uom/views.py

from django.views.generic import ListView, CreateView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from .models import UomCategory, UnitOfMeasure
from .forms import UomCategoryForm, UnitOfMeasureForm


# ==============================
# Uom Categories
# ==============================

class UomCategoryListView(LoginRequiredMixin, ListView):
    model = UomCategory
    template_name = "uom/category_list.html"
    context_object_name = "categories"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_master"  # لتفعيل التبويب في النافبار
        return context


class UomCategoryCreateView(LoginRequiredMixin, CreateView):
    model = UomCategory
    form_class = UomCategoryForm
    template_name = "uom/category_form.html"
    success_url = reverse_lazy("uom:category_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("إضافة فئة وحدات")
        context["active_section"] = "inventory_master"
        return context


class UomCategoryUpdateView(LoginRequiredMixin, UpdateView):
    model = UomCategory
    form_class = UomCategoryForm
    template_name = "uom/category_form.html"
    success_url = reverse_lazy("uom:category_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("تعديل الفئة: ") + self.object.name
        context["active_section"] = "inventory_master"
        return context


# ==============================
# Units of Measure
# ==============================

class UnitListView(LoginRequiredMixin, ListView):
    model = UnitOfMeasure
    template_name = "uom/unit_list.html"
    context_object_name = "units"

    def get_queryset(self):
        return UnitOfMeasure.objects.select_related("category").all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_section"] = "inventory_master"
        return context


class UnitCreateView(LoginRequiredMixin, CreateView):
    model = UnitOfMeasure
    form_class = UnitOfMeasureForm
    template_name = "uom/unit_form.html"
    success_url = reverse_lazy("uom:unit_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("إضافة وحدة قياس")
        context["active_section"] = "inventory_master"
        return context


class UnitUpdateView(LoginRequiredMixin, UpdateView):
    model = UnitOfMeasure
    form_class = UnitOfMeasureForm
    template_name = "uom/unit_form.html"
    success_url = reverse_lazy("uom:unit_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("تعديل الوحدة: ") + self.object.name
        context["active_section"] = "inventory_master"
        return context